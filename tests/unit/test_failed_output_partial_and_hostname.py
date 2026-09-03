"""build_failed_output.yml — rescue 경로 envelope 계약 (2026-09-03, B-36).

- 예외 직전까지 성공한 섹션은 success 로 남고 status 는 partial (하나도 없으면 failed).
- hostname 은 build_output.yml 과 같은 체인(system.hostname → fqdn → bmc → null), IP 대체 금지,
  diagnosis.details.hostname_source 동반.
- correlation 이 아직 없으면 누적 data 에서 만든다 (uuid 소문자 정규화).

production YAML 의 표현식을 추출해 렌더한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from identity_normalizer import normalize_uuid  # noqa: E402

YML = REPO / "common" / "tasks" / "normalize" / "build_failed_output.yml"


def _combine(d, other, recursive=False):
    r = dict(d or {})
    r.update(other or {})
    return r


def _env():
    env = NativeEnvironment()
    env.filters["combine"] = _combine
    env.filters["normalize_uuid"] = normalize_uuid
    return env


def _sf(name_sub: str) -> dict:
    for t in yaml.safe_load(YML.read_text(encoding="utf-8")):
        if isinstance(t, dict) and name_sub in str(t.get("name", "")):
            return t["ansible.builtin.set_fact"]
    raise AssertionError(name_sub)


def _render(tmpl, ctx):
    return _env().from_string(tmpl).render(**ctx) if isinstance(tmpl, str) else tmpl


def test_collected_sections_stay_success_and_status_partial():
    sf = _sf("build sections")
    ctx = {"_fail_sec_supported": ["system", "hardware", "cpu"], "_all_sec_collected": ["system", "hardware"], "_all_sec_failed": []}
    sections = _render(sf["_norm_sections"], ctx)
    assert sections["system"] == "success" and sections["hardware"] == "success"
    assert sections["cpu"] == "failed"
    assert sections["bmc"] == "not_supported" and len(sections) == 11
    assert _render(sf["_out_status"], ctx) == "partial"


def test_no_collected_section_means_failed():
    sf = _sf("build sections")
    ctx = {"_fail_sec_supported": ["system", "cpu"], "_all_sec_collected": [], "_all_sec_failed": []}
    sections = _render(sf["_norm_sections"], ctx)
    assert sections["system"] == "failed" and sections["cpu"] == "failed"
    assert _render(sf["_out_status"], ctx) == "failed"
    # 누적 변수 자체가 없는 초기 예외
    assert _render(sf["_out_status"], {"_fail_sec_supported": ["system"]}) == "failed"


def test_section_in_both_collected_and_failed_counts_as_failed():
    sf = _sf("build sections")
    ctx = {"_fail_sec_supported": ["storage"], "_all_sec_collected": ["storage"], "_all_sec_failed": ["storage"]}
    assert _render(sf["_norm_sections"], ctx)["storage"] == "failed"
    assert _render(sf["_out_status"], ctx) == "failed"


def test_hostname_chain_and_source():
    sf = _sf("resolve hostname + source")
    sys_ = {"_merged_data": {"system": {"hostname": "r760-6", "fqdn": None}}}
    assert _render(sf["_out_hostname"], sys_) == "r760-6"
    assert _render(sf["_out_hostname_source"], sys_) == "system"
    fq = {"_merged_data": {"system": {"hostname": None, "fqdn": "web01.corp"}}}
    assert _render(sf["_out_hostname"], fq) == "web01.corp"
    bmc = {"_merged_data": {"system": None, "bmc": {"network_hostname": "ILO1"}}}
    assert _render(sf["_out_hostname"], bmc) == "ILO1"
    assert _render(sf["_out_hostname_source"], bmc) == "bmc"
    none = {"_merged_data": {"system": None}, "_out_ip": "10.0.0.1", "inventory_hostname": "10.0.0.1"}
    assert _render(sf["_out_hostname"], none) is None
    assert _render(sf["_out_hostname_source"], none) == "none"


def test_correlation_derived_from_merged_data_when_missing():
    sf = _sf("build fallback meta")
    ctx = {"_merged_data": {"hardware": {"serial": "ABC123", "uuid": "4C4C4544-0042-4A10-8038-B2C04F303333"}, "system": None, "bmc": None},
           "_out_ip": "10.0.0.5"}
    corr = _render(sf["_correlation"], ctx)
    assert corr == {"serial_number": "ABC123", "system_uuid": "4c4c4544-0042-4a10-8038-b2c04f303333", "bmc_ip": None, "host_ip": "10.0.0.5"}
    # 이미 있으면 그대로
    assert _render(sf["_correlation"], {"_correlation": {"serial_number": "X"}}) == {"serial_number": "X"}
    # hardware 가 없으면 system 식별자로
    corr2 = _render(sf["_correlation"], {"_merged_data": {"hardware": None, "system": {"serial_number": "S1", "system_uuid": None}}, "_out_ip": "1.1.1.1"})
    assert corr2["serial_number"] == "S1" and corr2["system_uuid"] is None


def test_assembled_output_has_12_keys_hostname_null_and_source():
    sf = _sf("assemble output")
    ctx = {
        "_out_target_type": "os", "_out_collection_method": "agent", "_out_ip": "10.0.0.7", "_out_vendor": None,
        "_out_hostname": None, "_out_hostname_source": "none", "_out_status": "failed",
        "_norm_sections": {"system": "failed"}, "_diagnosis": {"failure_reason": "x", "details": {"channel": "os"}},
        "_meta": {}, "_correlation": {"host_ip": "10.0.0.7"}, "_fail_errors": [{"section": "gather", "message": "x", "detail": None}],
        "_merged_data": {"system": None}, "inventory_hostname": "10.0.0.7",
    }
    out = _render(sf["_output"], ctx)
    assert set(out) == {"target_type", "collection_method", "ip", "hostname", "vendor", "status", "sections",
                        "diagnosis", "meta", "correlation", "errors", "data"}
    assert out["hostname"] is None and out["ip"] == "10.0.0.7"
    assert out["diagnosis"]["details"]["hostname_source"] == "none"
    assert out["diagnosis"]["details"]["channel"] == "os"
    assert out["status"] == "failed"
