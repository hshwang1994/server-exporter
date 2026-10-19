"""OS memory.summary — 전체 합계 미확정은 null · 0 GB 로 반올림되는 DIMM 은 그룹 제외 (2026-10-19, B-1 / B-10).

os-gather/tasks/{linux,windows}/gather_memory.yml 의 *실제* summary 템플릿을 추출해 렌더한다
(test_network_summary_join_at1.py 패턴 — yaml.safe_load → set_fact 키 → jinja2 Environment → ast.literal_eval).

- B-1 (Linux): grand_total_gb 는 DMI 슬롯 합 → MEM_PHYS_MB → MemTotal(KB) 순 그대로. 셋 다 없으면 종전 0 → null.
- B-10 (Linux · Windows): capacity_mb > 0 이어도 GB 반올림(half-even)이 0 인 DIMM(512 MiB 이하)은
  unit_capacity_gb 0 그룹을 만들지 않고 합계를 부풀리지 않는다 (storage summary 와 같은 규칙).
"""
from __future__ import annotations

import ast
from pathlib import Path

import yaml
from jinja2 import Environment

REPO = Path(__file__).resolve().parents[2]
LINUX_MEM = REPO / "os-gather" / "tasks" / "linux" / "gather_memory.yml"
WINDOWS_MEM = REPO / "os-gather" / "tasks" / "windows" / "gather_memory.yml"


def _ansible_bool(value):
    """ansible `bool` 필터 최소 구현 (Windows build fragment 의 summary 식이 쓴다)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return bool(value)


def _set_fact(yml: Path, task_name: str, var: str):
    """task_name 태스크의 set_fact 에서 var 값(템플릿 문자열 또는 중첩 dict) 추출."""
    for t in yaml.safe_load(yml.read_text(encoding="utf-8")):
        if isinstance(t, dict) and t.get("name") == task_name:
            sf = t.get("ansible.builtin.set_fact") or {}
            assert var in sf, f"{task_name}: {var} 없음"
            return sf[var]
    raise AssertionError(f"{yml.name}: task {task_name!r} 미발견")


def _render(tmpl: str, **ctx):
    env = Environment()  # noqa: S701 — 테스트 전용, autoescape 불필요
    env.filters["bool"] = _ansible_bool
    out = env.from_string(tmpl).render(**ctx).strip()
    return ast.literal_eval(out)


def _slot(capacity_mb, **kw):
    base = {"capacity_mb": capacity_mb, "type": "DDR4", "speed_mhz": 3200, "manufacturer": "Samsung",
            "part_number": "M393A2K43DB3", "serial": None, "locator": None}
    base.update(kw)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# Linux — "linux | memory | compute summary groups" (_l_mem_summary)
# ═══════════════════════════════════════════════════════════════════════════
def _linux_summary(slots, phys_mb="", total_kb=""):
    tmpl = _set_fact(LINUX_MEM, "linux | memory | compute summary groups", "_l_mem_summary")
    return _render(tmpl, _l_mem_slots=slots, _l_mem_rp={"MEM_PHYS_MB": phys_mb, "MEM_TOTAL_KB": total_kb})


def test_linux_nothing_known_is_null_not_zero():
    """B-1: 슬롯 없음 + MEM_PHYS_MB '' + MEM_TOTAL_KB '' → grand_total_gb null (종전 0)."""
    assert _linux_summary([], phys_mb="", total_kb="") == {"groups": [], "grand_total_gb": None}


def test_linux_phys_mb_fallback_when_no_slots():
    assert _linux_summary([], phys_mb="262144")["grand_total_gb"] == 256


def test_linux_memtotal_kb_fallback_is_last():
    # MemTotal 16384000 KB → 15.6 GiB → 반올림 16 (종전과 같은 값 — fallback 순서 불변)
    assert _linux_summary([], phys_mb="", total_kb="16384000")["grand_total_gb"] == 16
    # MEM_PHYS_MB(설치량) 가 있으면 MemTotal(가시량) 보다 앞
    assert _linux_summary([], phys_mb="262144", total_kb="16384000")["grand_total_gb"] == 256


def test_linux_dmi_sum_wins_over_phys_mb():
    out = _linux_summary([_slot(16384), _slot(16384)], phys_mb="65536")
    assert out["grand_total_gb"] == 32
    assert [(g["unit_capacity_gb"], g["quantity"], g["group_total_gb"]) for g in out["groups"]] == [(16, 2, 32)]


def test_linux_sub_gb_dimm_makes_no_group_and_total_stays_null():
    """B-10: 256 MiB 슬롯 하나 → unit_capacity_gb 0 그룹을 만들지 않고, 합계도 0 으로 '확정' 하지 않는다."""
    out = _linux_summary([_slot(256)], phys_mb="", total_kb="")
    assert out["groups"] == []
    assert out["grand_total_gb"] is None


def test_linux_sub_gb_dimm_does_not_inflate_or_zero_group():
    out = _linux_summary([_slot(256), _slot(16384), _slot(16384)], phys_mb="")
    assert [(g["unit_capacity_gb"], g["quantity"]) for g in out["groups"]] == [(16, 2)]
    assert out["grand_total_gb"] == 32


def test_linux_zero_or_non_numeric_total_kb_is_not_known():
    """MemTotal '0' / 비숫자는 "안다" 가 아니다 → null (총량 0 GB 를 날조하지 않는다). capacity null 슬롯도 그룹을 만들지 않는다."""
    assert _linux_summary([], phys_mb="", total_kb="0")["grand_total_gb"] is None
    assert _linux_summary([_slot(None)], phys_mb="", total_kb="n/a") == {"groups": [], "grand_total_gb": None}


# ═══════════════════════════════════════════════════════════════════════════
# Windows — "windows | memory | summary + totals" (_w_mem_summary)
# ═══════════════════════════════════════════════════════════════════════════
def _windows_summary(slots):
    tmpl = _set_fact(WINDOWS_MEM, "windows | memory | summary + totals", "_w_mem_summary")
    return _render(tmpl, _w_mem_slots=slots)


def test_windows_sub_gb_dimm_makes_no_group():
    """B-10: 256 MiB 슬롯 → 그룹 없음 (슬롯 합 0 — 전체 합계는 build fragment 가 설치량/가시량/null 로 정한다, 아래)."""
    out = _windows_summary([_slot(256, slot="DIMM A", locator="DIMM A")])
    assert out["groups"] == []
    assert out["grand_total_gb"] == 0


def test_windows_sub_gb_dimm_does_not_inflate_other_groups():
    out = _windows_summary([_slot(256), _slot(8192), _slot(8192)])
    assert [(g["unit_capacity_gb"], g["quantity"]) for g in out["groups"]] == [(8, 2)]
    assert out["grand_total_gb"] == 16


def test_windows_fragment_summary_total_is_null_when_nothing_known():
    """슬롯 합 0 + 설치량/가시량 모두 없음 → grand_total_gb null (Linux B-1 과 같은 계약 — Windows 는 종전부터 null)."""
    tmpl = _set_fact(WINDOWS_MEM, "windows | memory | build fragment", "_data_fragment")["memory"]["summary"]
    out = _render(tmpl, _w_mem_summary=_windows_summary([_slot(256)]),
                  _w_mem_phys_mb=None, _w_mem_vis_mb=None, _w_mem_read_failed=False)
    assert out == {"groups": [], "grand_total_gb": None}
