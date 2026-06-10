"""Round 15 — 회귀 테스트.

본 파일은 Round 15 검증에서 확정된 버그 fix 의 회귀 가드다.
각 테스트는 "fix 전이라면 실패, fix 후 통과" 형태로 동작을 고정한다.

대상 fix:
  - adapter_common.adapter_match_score: version/distribution/os_type 보너스 (specificity 대칭)
  - redfish_gather._normalize_bios_date: invalid ISO (예: 2024-13-32) 생성 방지 → raw 보존
  - redfish_gather._merge_power_dual: serial-primary dedup (다른 name 같은 serial 합침)
  - diagnosis_mapper.build_diagnosis: 비-dict probe_facts → update() ValueError 방어
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "module_utils"))
sys.path.insert(0, str(REPO / "filter_plugins"))

# ansible stub (redfish_gather 가 ansible.module_utils.basic.AnsibleModule import)
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402
from adapter_common import adapter_match_score  # noqa: E402
from diagnosis_mapper import build_diagnosis  # noqa: E402
from jedec_mapper import jedec_to_vendor  # noqa: E402


# ── adapter_match_score version/distribution/os_type 보너스 ────────────────

def test_match_score_version_distribution_os_bonus():
    """version(+15)/distribution(+15)/os_type(+5) 매치도 match_score 보너스 (이전엔 누락)."""
    a = {"match": {"os_type": "linux", "distribution_patterns": ["rhel.*"],
                   "version_patterns": [r"9\..*"]}}
    facts = {"detected_os": "linux", "distribution": "rhel", "version": "9.4"}
    assert adapter_match_score(a, facts) == 35  # 5 + 15 + 15


def test_match_score_version_distribution_empty_skips_bonus():
    """정보 없음(빈 값) → 보너스만 제외, disqualify 아님 (model/firmware 와 동일 정책)."""
    a = {"match": {"os_type": "linux", "distribution_patterns": ["rhel.*"],
                   "version_patterns": [r"9\..*"]}}
    assert adapter_match_score(a, {}) == 0


def test_match_score_version_known_mismatch_disqualifies():
    """version 알려졌는데 불일치 → -9999 (model/firmware 와 동일)."""
    a = {"match": {"version_patterns": [r"9\..*"]}}
    assert adapter_match_score(a, {"version": "8.10"}) == -9999


# ── _normalize_bios_date invalid ISO 방지 ────────────────────────────────

def test_bios_date_valid_mmddyyyy():
    assert rg._normalize_bios_date("09/10/2024") == "2024-09-10"


def test_bios_date_european_ddmmyyyy_swap():
    # 첫 자리 > 12 → DD/MM/YYYY 로 해석 (swap)
    assert rg._normalize_bios_date("25/12/2024") == "2024-12-25"


def test_bios_date_iso_datetime_prefix():
    assert rg._normalize_bios_date("2024-03-01T12:00:00Z") == "2024-03-01"


def test_bios_date_invalid_after_swap_returns_raw():
    """32/13/2024 → swap 후 2024-13-32 (invalid) → raw 원문 보존 (invalid ISO emit 안 함)."""
    assert rg._normalize_bios_date("32/13/2024") == "32/13/2024"


def test_bios_date_zero_month_day_returns_raw():
    """00/00/2024 → 2024-00-00 invalid → raw 보존."""
    assert rg._normalize_bios_date("00/00/2024") == "00/00/2024"


def test_bios_date_invalid_plain_iso_returns_raw():
    """2024-13-32 (월 13 / 일 32) → invalid → raw 보존 (이전엔 그대로 emit)."""
    assert rg._normalize_bios_date("2024-13-32") == "2024-13-32"


def test_bios_date_none_and_na():
    assert rg._normalize_bios_date(None) is None
    assert rg._normalize_bios_date("N/A") is None


# ── _merge_power_dual serial-primary dedup ───────────────────────────────

def test_merge_power_dual_dedup_different_names_same_serial():
    """같은 serial 을 legacy/subsystem 이 다른 name 으로 emit → 1 PSU 로 dedup."""
    legacy = {"power_supplies": [
        {"name": "PSU0-Legacy", "model": "PS-1234", "serial": "SN-A1", "health": "OK"},
    ], "power_control": {"power_consumed_watts": 100}}
    subsystem = {"power_supplies": [
        {"name": "PSU0-Subsystem", "model": "PS-1234", "serial": "SN-A1", "health": "OK"},
    ], "power_control": None}
    merged = rg._merge_power_dual(legacy, subsystem)
    assert len(merged["power_supplies"]) == 1


def test_merge_power_dual_no_serial_keeps_distinct_names():
    """serial 부재 + 같은 model + 다른 name → 별개 PSU 로 보존 (over-dedup 방지)."""
    legacy = {"power_supplies": [
        {"name": "PSU0", "model": "PS-1234", "serial": None, "health": "OK"},
        {"name": "PSU1", "model": "PS-1234", "serial": None, "health": "OK"},
    ], "power_control": None}
    merged = rg._merge_power_dual(legacy, {})
    assert len(merged["power_supplies"]) == 2


# ── diagnosis_mapper 비-dict probe_facts 방어 ────────────────────────────

def test_build_diagnosis_non_dict_probe_facts_no_crash():
    """손상된 캐시/외부 JSON 으로 probe_facts 가 문자열 → details.update() ValueError 방어."""
    out = build_diagnosis({"probe_facts": "corrupted-string"}, "redfish", "dell_idrac9")
    assert isinstance(out, dict) and isinstance(out["details"], dict)
    # 정상 dict probe_facts 는 여전히 병합
    out2 = build_diagnosis({"probe_facts": {"model": "R760"}}, "redfish", "x")
    assert out2["details"]["model"] == "R760"


# ── (Round 2 fresh): gather_processors all-Absent → warning (수집실패와 구분) ─────

def _fake_get_from_tree(tree):
    def fake(bmc_ip, path, username, password, timeout, verify_ssl):
        if path in tree:
            return 200, tree[path], None
        return 404, {}, "HTTP 404"
    return fake


def test_gather_processors_all_absent_emits_warning(monkeypatch):
    """멤버는 있으나 전부 Absent/Disabled → processors=[] + warning (컬렉션 GET 실패와 구분)."""
    tree = {
        "Systems/1/Processors": {"Members": [
            {"@odata.id": "/redfish/v1/Systems/1/Processors/0"},
            {"@odata.id": "/redfish/v1/Systems/1/Processors/1"},
        ]},
        "Systems/1/Processors/0": {"Id": "0", "Status": {"State": "Absent"}},
        "Systems/1/Processors/1": {"Id": "1", "Status": {"State": "Disabled"}},
    }
    monkeypatch.setattr(rg, "_get", _fake_get_from_tree(tree))
    procs, errors = rg.gather_processors("1.2.3.4", "/redfish/v1/Systems/1", "u", "p", 5, False)
    assert procs == []
    assert any("Absent" in (e.get("message") or "") for e in errors)


def test_gather_processors_normal_no_false_warning(monkeypatch):
    """정상 CPU 수집 시 all-absent warning 이 잘못 나오지 않음."""
    tree = {
        "Systems/1/Processors": {"Members": [{"@odata.id": "/redfish/v1/Systems/1/Processors/0"}]},
        "Systems/1/Processors/0": {"Id": "0", "Status": {"State": "Enabled"},
                                   "TotalCores": 8, "Model": "Xeon"},
    }
    monkeypatch.setattr(rg, "_get", _fake_get_from_tree(tree))
    procs, errors = rg.gather_processors("1.2.3.4", "/redfish/v1/Systems/1", "u", "p", 5, False)
    assert len(procs) == 1
    assert not any("Absent" in (e.get("message") or "") for e in errors)


# ── (Round 3 fresh): jedec_mapper bare 2-char hex ID 정규화 ─────────────────

def test_jedec_bare_2char_hex_normalized():
    """bank-prefix 없는 2자리 JEDEC ID ('AD'/'CE'/'2C') → vendor 명 (이전엔 raw 반환)."""
    assert jedec_to_vendor("AD") == "SK hynix"
    assert jedec_to_vendor("CE") == "Samsung"
    assert jedec_to_vendor("2C") == "Micron Technology"


def test_jedec_existing_formats_unchanged():
    """기존 포맷 회귀 — bank-prefixed / 0x / vendor-name / None 불변."""
    assert jedec_to_vendor("00AD063200AD") == "SK hynix"   # Linux dmidecode bank-prefixed
    assert jedec_to_vendor("0xCE00") == "Samsung"          # Cisco CIMC
    assert jedec_to_vendor("Samsung") == "Samsung"          # 이미 vendor 명
    assert jedec_to_vendor(None) is None
    assert jedec_to_vendor("") is None
