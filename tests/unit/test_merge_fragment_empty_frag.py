"""merge_fragment 빈 _data_fragment 는 누적 data 를 보존(덮어쓰지 않음).

gather_runtime 의 rescue 가 all-null runtime 을 emit 하면 merge_fragment 의 2-level
wholesale 교체(L89-90)로 gather_system 이 이미 수집한 runtime 을 통째로 덮어써 데이터
유실. 수정: rescue 가 `_data_fragment: {}` 를 emit → 빈 fragment 는 identity merge 여야
한다. merge_fragment.yml 의 **실제 'merge data' Jinja2 표현식**을 렌더링해 검증한다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MF_YML = REPO / "common" / "tasks" / "normalize" / "merge_fragment.yml"
_MERGE_TASK = "normalize | merge_fragment | merge data"


def _merge_template() -> str:
    for t in yaml.safe_load(MF_YML.read_text(encoding="utf-8")):
        if isinstance(t, dict) and t.get("name") == _MERGE_TASK:
            return t["ansible.builtin.set_fact"]["_merged_data"]
    raise AssertionError(f"task {_MERGE_TASK!r} not found")


def _merge(base, frag):
    env = NativeEnvironment()
    env.filters["union"] = lambda a, b: list(dict.fromkeys(list(a) + list(b)))
    out = env.from_string(_merge_template()).render(_merged_data=base, _data_fragment=frag)
    if isinstance(out, str):
        out = ast.literal_eval(out.strip())
    return out


_GOOD_RUNTIME = {
    "timezone": "Etc/UTC", "ntp_active": True, "firewall_tool": "firewalld",
    "firewall_state": "active", "listening_ports": ["22", "53"],
    "swap_total_mb": 4095, "swap_used_mb": 0, "swap_free_mb": 4095,
}


def test_empty_fragment_preserves_accumulated_runtime():
    """rescue 의 빈 fragment({}) → gather_system 이 수집한 runtime 보존."""
    base = {"system": {"runtime": dict(_GOOD_RUNTIME), "vendor": "Dell"}}
    merged = _merge(base, {})
    assert merged["system"]["runtime"] == _GOOD_RUNTIME   # 보존 (가드 전: rescue all-null 로 덮임)
    assert merged["system"]["vendor"] == "Dell"


def test_all_null_runtime_fragment_would_clobber_proves_mechanism():
    """기존 버그 재현: all-null runtime fragment 는 wholesale 교체로 좋은 데이터를 덮는다.

    rescue 가 {} 대신 이 dict 를 emit 하던 것이 원인 — 수정으로 더는 emit 되지 않음."""
    base = {"system": {"runtime": dict(_GOOD_RUNTIME)}}
    all_null = {"system": {"runtime": {k: None for k in _GOOD_RUNTIME}}}
    merged = _merge(base, all_null)
    assert merged["system"]["runtime"]["firewall_state"] is None  # 덮임 → 데이터 유실(구 동작)


def test_normal_fragment_still_merges():
    """정상 fragment 병합 불변 (회귀 방어) — 새 섹션 추가는 정상 누적."""
    base = {"system": {"runtime": dict(_GOOD_RUNTIME)}}
    frag = {"cpu": {"model": "Xeon"}}
    merged = _merge(base, frag)
    assert merged["system"]["runtime"] == _GOOD_RUNTIME
    assert merged["cpu"] == {"model": "Xeon"}
