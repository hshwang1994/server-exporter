"""ESXi system.serial_number / hardware.serial — nPartition 접미사 제거 (2026-10-19 A-1-ESXi, 사용자 결정).

HPE CSUS 3200 / Superdome Flex 의 OS 측 시스템 시리얼은 '물리 시리얼-파티션번호'(SGHD3TLNDD-000) 다. OS · Redfish 채널은
filter_plugins/serial_normalizer.py 의 normalize_os_serial 로 접미사를 떼는데 ESXi 는 원문을 그대로 내 같은 장비의 시리얼이 채널마다
달랐다. 세 조건(HPE alias · CSUS 3200/Superdome Flex 모델 · '-NNN' 접미사)이 모두 맞을 때만 동작하고 다른 서버는 불변이다.

normalize_system.yml 의 실제 set_fact 세 task 를 순서대로 렌더한다 (실장비 미검증 — lab 에 CSUS 3200 ESXi 가 없다).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "unit"))
sys.path.insert(0, str(REPO / "filter_plugins"))

from identity_normalizer import normalize_mac, normalize_uuid  # noqa: E402
from linux_raw_harness import ansible_env, render_tree  # noqa: E402
from serial_normalizer import normalize_os_serial  # noqa: E402

SYS = REPO / "esxi-gather" / "tasks" / "normalize_system.yml"
CORRELATION = REPO / "common" / "tasks" / "normalize" / "build_correlation.yml"


def _regex_search(value, pattern, *groups, **_kw):
    """ansible.builtin.regex_search 최소 호환 — 미매치 None, '\\1' 인자가 있으면 그룹 list."""
    m = re.search(pattern, str(value))
    if not m:
        return None
    if groups:
        return [m.group(int(g.lstrip("\\"))) for g in groups]
    return m.group(0)


def _env():
    env = ansible_env()
    env.filters.update({"normalize_uuid": normalize_uuid, "normalize_mac": normalize_mac,
                        "normalize_os_serial": normalize_os_serial, "regex_search": _regex_search})
    return env


def run_normalize_system(facts: dict, raw_host: dict | None = None, raw_dns: dict | None = None) -> dict:
    """normalize_system.yml 의 set_fact task 를 적힌 순서대로 렌더한 컨텍스트."""
    env = _env()
    ctx = {"_e_raw_facts": facts, "_e_raw_host": raw_host or {}, "_e_raw_dns": raw_dns or {}, "_e_facts_ok": True}
    for task in yaml.safe_load(SYS.read_text(encoding="utf-8")):
        if isinstance(task, dict) and "ansible.builtin.set_fact" in task:
            ctx.update({k: render_tree(env, v, ctx) for k, v in task["ansible.builtin.set_fact"].items()})
    return ctx


def _serials(serial, vendor, model):
    frag = run_normalize_system({"ansible_product_serial": serial, "ansible_system_vendor": vendor, "ansible_product_name": model})["_data_fragment"]
    return frag["system"]["serial_number"], frag["hardware"]["serial"]


@pytest.mark.parametrize("serial, vendor, model, expected", [
    ("SGHD3TLNDD-000", "HPE", "Compute Scale-up Server 3200", "SGHD3TLNDD"),
    ("SGHD3TLNDD-000", "Hewlett Packard Enterprise", "Compute Scale-up Server 3200, 4S XNC Base Chassis", "SGHD3TLNDD"),
    ("SGHD3TLNDD-001", "HPE", "Superdome Flex 280", "SGHD3TLNDD"),          # 2026-10-19 같은 hpCsus 패밀리 — 필터 쪽 패턴 미러
    ("CZ12345678", "HPE", "ProLiant DL380 Gen11", "CZ12345678"),             # HPE 지만 nPar 장비가 아니다 → 불변
    ("ABCDEF-000", "Dell Inc.", "PowerEdge R760", "ABCDEF-000"),             # 다른 제조사의 하이픈 시리얼 → 불변
    ("SGHD3TLNDD-000", None, "Compute Scale-up Server 3200", "SGHD3TLNDD-000"),  # vendor 를 모르면 정규화하지 않는다 (fail-safe)
    ("SGHD3TLNDD-000", "HPE", None, "SGHD3TLNDD-000"),                       # model 을 모르면 정규화하지 않는다
], ids=["csus3200", "csus3200-chassis-model", "superdome-flex", "proliant-unchanged", "dell-unchanged", "no-vendor", "no-model"])
def test_system_and_hardware_serial_strip_npar_suffix_only_for_hpe_npar_models(serial, vendor, model, expected):
    assert _serials(serial, vendor, model) == (expected, expected)


@pytest.mark.parametrize("sentinel", ["NA", "N/A", "", "System Serial Number", "To Be Filled By O.E.M.", None])
def test_dmi_sentinel_is_still_null_before_the_npar_filter(sentinel):
    """자리표시자는 식별자가 아니다(2026-10-10 LX-F12) — nPar 필터가 그 뒤에 와도 None 은 None 이다."""
    facts = {"ansible_system_vendor": "HPE", "ansible_product_name": "Compute Scale-up Server 3200"}
    if sentinel is not None:
        facts["ansible_product_serial"] = sentinel
    frag = run_normalize_system(facts)["_data_fragment"]
    assert frag["system"]["serial_number"] is None and frag["hardware"]["serial"] is None


def test_both_serial_templates_apply_sentinel_first_then_the_shared_npar_filter():
    """순서 계약: dmi_sentinel_null('serial') → normalize_os_serial(vendor, model). 벤더 지식은 필터 한 곳(rule 12 R1) — 템플릿에 모델/벤더 리터럴 없음."""
    tasks = yaml.safe_load(SYS.read_text(encoding="utf-8"))
    frag = next(t for t in tasks if isinstance(t, dict) and "_data_fragment" in (t.get("ansible.builtin.set_fact") or {}))["ansible.builtin.set_fact"]["_data_fragment"]
    for tpl in (frag["system"]["serial_number"], frag["hardware"]["serial"]):
        assert "dmi_sentinel_null('serial') | normalize_os_serial(" in tpl, tpl
        assert "ansible_system_vendor" in tpl and "ansible_product_name" in tpl, tpl
        assert not re.search(r"HPE|Hewlett|3200|Superdome", tpl), "벤더/모델 리터럴은 템플릿이 아니라 serial_normalizer.py 에만"


def test_correlation_serial_copies_the_normalized_hardware_serial():
    """correlation.serial_number 는 hardware.serial 복사(build_correlation.yml) — 접미사가 떨어진 값이 그대로 간다 (별도 규칙 없음)."""
    frag = run_normalize_system({"ansible_product_serial": "SGHD3TLNDD-000", "ansible_system_vendor": "HPE",
                                 "ansible_product_name": "Compute Scale-up Server 3200"})["_data_fragment"]
    tpl = next(t for t in yaml.safe_load(CORRELATION.read_text(encoding="utf-8")) if "ansible.builtin.set_fact" in t)["ansible.builtin.set_fact"]["_correlation"]
    corr = render_tree(_env(), tpl, {"_merged_data": {"hardware": frag["hardware"], "system": frag["system"]}})
    assert corr["serial_number"] == "SGHD3TLNDD"
