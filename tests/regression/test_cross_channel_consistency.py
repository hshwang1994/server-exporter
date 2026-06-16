"""Cross-channel envelope consistency regression.

Validates that the 13-field envelope (rule 13 R5) is structurally identical
across all 3 channels (os / esxi / redfish), so downstream callers can parse
any baseline without channel-specific branches.

Test groups:
  T1 — Envelope 13 fields present (rule 13 R5)
  T2 — target_type / collection_method enum
  T3 — hostname fallback chain non-null (concern 7 invariant)
  T4 — vendor canonical form (cycle-016 BUG #2 regression)
  T5 — status enum (rule 13 R8 — 4 scenarios A/B/C/D)
  T6 — sections values enum
  T7 — diagnosis dict shape (production-audit BUG fix invariant)
  T8 — errors[] is list (rule 22 R8 fragment type)
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _canonical_sections() -> set[str]:
    """schema/sections.yml 의 canonical 섹션 집합 (정본). 현재 11종."""
    with open(_PROJECT_ROOT / "schema" / "sections.yml", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return set((doc.get("sections") or {}).keys())


# 알려진 stale 섹션 — 코드는 수집하나 baseline 미반영 (lab 재생성 대기).
#   thermal: cycle 2026-06-14 (Track 4) 추가. baseline 9종이 그 이전이라 누락.
#            lab 재생성 후 본 set 에서 제거 → xfail 이 xpass 로 뒤집혀 알림 (NEXT_ACTIONS 2026-06-16).
KNOWN_STALE_SECTIONS: frozenset[str] = frozenset({"thermal"})

# rule 13 R5 — 13-field envelope
ENVELOPE_FIELDS: tuple[str, ...] = (
    "target_type",
    "collection_method",
    "ip",
    "hostname",
    "vendor",
    "status",
    "sections",
    "diagnosis",
    "meta",
    "correlation",
    "errors",
    "data",
    "schema_version",
)

VALID_TARGET_TYPES: frozenset[str] = frozenset({"os", "esxi", "redfish"})
VALID_COLLECTION_METHODS: frozenset[str] = frozenset(
    {"agent", "vsphere_api", "redfish_api"}
)
VALID_STATUS: frozenset[str] = frozenset({"success", "partial", "failed"})
VALID_SECTION_STATUS: frozenset[str] = frozenset(
    {"success", "not_supported", "failed", "partial"}
)
# rule 50 R1 — vendor 정규화 정본 (vendor_aliases.yml + 신규 4 vendor)
# cycle 2026-06-04 (사용자 결정): 출력 표시값 매핑 — 내부 canonical 'hpe' 는 envelope
# 에서 'hp' (CSUS 3200 → 'hpCsus') 로 노출. 'hpe' 는 always-fallback degradation 대비 허용 유지.
CANONICAL_VENDORS: frozenset[str | None] = frozenset(
    {
        None,  # OS channel can be null (vendor-agnostic)
        "dell",
        "hpe",       # 내부 canonical (always-fallback degradation 시 출력 가능)
        "hp",        # HPE 출력 표시값 (vendor_output_display)
        "hpCsus",    # HPE CSUS 3200 출력 표시값 (adapter_output_display)
        "lenovo",
        "supermicro",
        "cisco",
        "huawei",
        "inspur",
        "fujitsu",
        "quanta",
    }
)


# ---------------------------------------------------------------------------
# T1 — Envelope 13 fields present
# ---------------------------------------------------------------------------
def test_envelope_thirteen_fields_present(baseline_envelope: dict) -> None:
    """rule 13 R5 — every baseline must expose all 13 envelope fields."""
    label = baseline_envelope["__label"]
    for field in ENVELOPE_FIELDS:
        assert field in baseline_envelope, (
            f"[{label}] envelope field missing: {field}"
        )


def test_envelope_no_extra_fields(baseline_envelope: dict) -> None:
    """rule 13 R5 — no fields beyond the 13 (excluding test-only __label keys)."""
    label = baseline_envelope["__label"]
    extra = {
        k for k in baseline_envelope
        if not k.startswith("__") and k not in ENVELOPE_FIELDS
    }
    assert not extra, (
        f"[{label}] unexpected envelope field(s): {sorted(extra)}"
    )


# ---------------------------------------------------------------------------
# T2 — target_type / collection_method enum
# ---------------------------------------------------------------------------
def test_target_type_enum(baseline_envelope: dict) -> None:
    label = baseline_envelope["__label"]
    target = baseline_envelope.get("target_type")
    assert target in VALID_TARGET_TYPES, (
        f"[{label}] target_type invalid: {target!r}"
    )


def test_collection_method_matches_target_type(baseline_envelope: dict) -> None:
    """Each target_type pairs with one collection_method (rule 13 R5)."""
    label = baseline_envelope["__label"]
    expected = baseline_envelope["__expected_collection_method"]
    actual = baseline_envelope.get("collection_method")
    assert actual == expected, (
        f"[{label}] collection_method mismatch: {actual!r} != {expected!r}"
    )


# ---------------------------------------------------------------------------
# T3 — hostname 은 절대 ip 와 같지 않다 (2026-06-16 strict-null 정책)
# ---------------------------------------------------------------------------
# 2026-06-16 (사용자 지시): hostname IP fallback 폐지 — "없는 건 없는 것".
# 장비가 hostname 미제공 시 hostname=null (이전 cycle 2026-05-07 의 ip fallback 폐지).
# 따라서 hostname 은 null 일 수 있고, ip 와 같은 값이면 옛 fallback 잔재(정책 위반)다.
# 정본: common/tasks/normalize/build_output.yml:31-33 / docs/20 §8.


def test_hostname_not_ip_fallback(baseline_envelope: dict) -> None:
    """hostname 은 ip 와 같으면 안 된다 (옛 ip-fallback 잔재 차단). null 은 허용 —
    장비가 hostname 미제공 시 정상적으로 null (2026-06-16 strict-null 정책)."""
    label = baseline_envelope["__label"]
    hostname = baseline_envelope.get("hostname")
    ip = baseline_envelope.get("ip")
    assert hostname != ip, (
        f"[{label}] hostname=={ip!r} (ip 와 동일) — IP fallback 잔재. "
        f"장비가 hostname 미제공이면 null 이어야 함 (2026-06-16 정책)"
    )
    # 빈 문자열도 금지 (null 로 정규화돼야 함 — '' 는 미정규화 잔재)
    assert hostname != "", (
        f"[{label}] hostname='' — '' 는 null 로 정규화돼야 함 (build_output `or none`)"
    )


def test_ip_present(baseline_envelope: dict) -> None:
    """ip is always present — hostname fallback ultimate sentinel."""
    label = baseline_envelope["__label"]
    ip = baseline_envelope.get("ip")
    assert ip, f"[{label}] ip empty — fallback chain ultimate sentinel missing"


# ---------------------------------------------------------------------------
# T4 — vendor canonical form (cycle-016 BUG #2 regression)
# ---------------------------------------------------------------------------
def test_vendor_canonical(baseline_envelope: dict) -> None:
    """ESXi/Redfish vendor must be canonical (e.g., 'cisco' not 'Cisco
    Systems Inc'). cycle-016 production-audit BUG #2 regression."""
    label = baseline_envelope["__label"]
    vendor = baseline_envelope.get("vendor")
    assert vendor in CANONICAL_VENDORS, (
        f"[{label}] vendor not canonical: {vendor!r} "
        f"(expected one of {sorted(str(v) for v in CANONICAL_VENDORS)})"
    )


# ---------------------------------------------------------------------------
# T5 — status enum (rule 13 R8 — 4 scenarios A/B/C/D)
# ---------------------------------------------------------------------------
def test_status_enum(baseline_envelope: dict) -> None:
    label = baseline_envelope["__label"]
    status = baseline_envelope.get("status")
    assert status in VALID_STATUS, (
        f"[{label}] status invalid: {status!r}"
    )


# ---------------------------------------------------------------------------
# T6 — sections values enum
# ---------------------------------------------------------------------------
# (T11 — sections 완전성: schema/sections.yml 11종 전부 present — 아래 정의)
# ---------------------------------------------------------------------------
def test_sections_values_enum(baseline_envelope: dict) -> None:
    label = baseline_envelope["__label"]
    sections = baseline_envelope.get("sections", {})
    assert isinstance(sections, dict), (
        f"[{label}] sections not dict: {type(sections).__name__}"
    )
    for section_name, section_status in sections.items():
        assert section_status in VALID_SECTION_STATUS, (
            f"[{label}] sections.{section_name} invalid: {section_status!r}"
        )


# ---------------------------------------------------------------------------
# T11 — sections 완전성 (schema/sections.yml 11종 전부 present)
# ---------------------------------------------------------------------------
# 2026-06-16: thermal(2026-06-14 추가) 이 baseline 9종에 전부 누락된 stale 발견.
# 코드는 thermal 을 정상 수집(real_* fixture 가 검증)하나 baseline 이 뒤처짐.
# 본 테스트는 (1) 향후 새 섹션 누락 = hard fail (코드 회귀 조기 경보),
#           (2) 알려진 stale(thermal) = xfail (가시화, suite green 유지, lab 재생성 추적).


def test_sections_has_all_canonical(baseline_envelope: dict) -> None:
    """모든 baseline 의 sections 는 schema/sections.yml 의 canonical 섹션을 전부 포함해야
    한다. 누락이 KNOWN_STALE 밖이면 hard fail(코드/baseline 회귀). KNOWN_STALE(thermal)
    누락은 xfail — lab baseline 재생성 대기 (NEXT_ACTIONS 2026-06-16)."""
    label = baseline_envelope["__label"]
    canonical = _canonical_sections()
    present = set((baseline_envelope.get("sections") or {}).keys())
    missing = canonical - present
    hard_missing = missing - KNOWN_STALE_SECTIONS
    assert not hard_missing, (
        f"[{label}] sections 누락(stale 아님 — 코드/baseline 회귀 의심): {sorted(hard_missing)} "
        f"(canonical={sorted(canonical)})"
    )
    if missing:
        pytest.xfail(
            f"[{label}] 알려진 stale 섹션 누락: {sorted(missing)} — "
            f"lab baseline 재생성 대기 (NEXT_ACTIONS 2026-06-16 thermal staleness)"
        )


# ---------------------------------------------------------------------------
# T7 — diagnosis dict shape (production-audit BUG fix invariant)
# ---------------------------------------------------------------------------
def test_diagnosis_is_dict(baseline_envelope: dict) -> None:
    """diagnosis must be dict, not list/str (production-audit shape fix)."""
    label = baseline_envelope["__label"]
    diagnosis = baseline_envelope.get("diagnosis")
    assert isinstance(diagnosis, dict), (
        f"[{label}] diagnosis not dict: {type(diagnosis).__name__}"
    )


def test_diagnosis_has_4stage_keys(baseline_envelope: dict) -> None:
    """precheck 4-stage keys must be present in success path
    (rule 27 — ping → port → protocol → auth)."""
    label = baseline_envelope["__label"]
    diagnosis = baseline_envelope.get("diagnosis", {})
    for key in ("reachable", "port_open", "protocol_supported", "auth_success"):
        assert key in diagnosis, (
            f"[{label}] diagnosis.{key} missing — precheck shape broken"
        )


# ---------------------------------------------------------------------------
# T8 — errors[] is list (rule 22 R8 fragment type)
# ---------------------------------------------------------------------------
def test_errors_is_list(baseline_envelope: dict) -> None:
    """rule 22 R8 — _errors_fragment is list of dicts."""
    label = baseline_envelope["__label"]
    errors = baseline_envelope.get("errors")
    assert isinstance(errors, list), (
        f"[{label}] errors not list: {type(errors).__name__}"
    )
    for i, err in enumerate(errors):
        assert isinstance(err, dict), (
            f"[{label}] errors[{i}] not dict: {type(err).__name__}"
        )


# ---------------------------------------------------------------------------
# T9 — schema_version present and matches policy (rule 13 R3)
# ---------------------------------------------------------------------------
def test_schema_version_is_one(baseline_envelope: dict) -> None:
    """schema_version is currently 1 (rule 13 R3 — bumped only by user)."""
    label = baseline_envelope["__label"]
    sv = baseline_envelope.get("schema_version")
    assert sv == "1", (
        f"[{label}] schema_version expected '1', got {sv!r}"
    )


# ---------------------------------------------------------------------------
# T10 — Aggregate: all 8 baselines covered (rule 21 R1 baseline registry)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "channel,expected_min",
    [
        ("redfish", 5),  # 4 real-device (dell/hpe/lenovo/cisco) + 1 MOCK (hpe_csus_3200, lab 부재 — envelope shape only)
        ("os", 3),       # ubuntu + windows + rhel810_raw_fallback
        ("esxi", 1),     # esxi
    ],
)
def test_baseline_coverage_per_channel(
    all_baselines: list[dict], channel: str, expected_min: int
) -> None:
    """Each channel must have at least N baselines (regression early warning)."""
    matched = [b for b in all_baselines if b.get("target_type") == channel]
    assert len(matched) >= expected_min, (
        f"channel '{channel}' baseline count {len(matched)} < expected {expected_min} "
        f"(present: {[b['__label'] for b in matched]})"
    )
