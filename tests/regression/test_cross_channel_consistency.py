"""Cross-channel envelope consistency regression.

Validates that the 13-field envelope is structurally identical
across all 3 channels (os / esxi / redfish), so downstream callers can parse
any baseline without channel-specific branches.

Test groups:
  T1 — Envelope 13 fields present
  T2 — target_type / collection_method enum
  T3 — hostname fallback chain non-null invariant
  T4 — vendor canonical form regression
  T5 — status enum (4 scenarios A/B/C/D)
  T6 — sections values enum
  T7 — diagnosis dict shape invariant
  T8 — errors[] is list (fragment type)
"""
from __future__ import annotations

import pytest

# 13-field envelope
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
# vendor 정규화 정본 (vendor_aliases.yml + 신규 4 vendor)
# 출력 표시값 매핑 — 내부 canonical 'hpe' 는 envelope
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
    """Every baseline must expose all 13 envelope fields."""
    label = baseline_envelope["__label"]
    for field in ENVELOPE_FIELDS:
        assert field in baseline_envelope, (
            f"[{label}] envelope field missing: {field}"
        )


def test_envelope_no_extra_fields(baseline_envelope: dict) -> None:
    """No fields beyond the 13 (excluding test-only __label keys)."""
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
    """Each target_type pairs with one collection_method."""
    label = baseline_envelope["__label"]
    expected = baseline_envelope["__expected_collection_method"]
    actual = baseline_envelope.get("collection_method")
    assert actual == expected, (
        f"[{label}] collection_method mismatch: {actual!r} != {expected!r}"
    )


# ---------------------------------------------------------------------------
# T3 — hostname fallback chain non-null invariant
# ---------------------------------------------------------------------------
# cisco_baseline.json hostname=null drift 보정 완료.
# build_output.yml fallback chain (system.hostname OR system.fqdn OR ip) 의도대로
# hostname 을 ip ("10.100.15.2") 로 보정 + evidence 기록. xfail 제거.
# 실 lab Cisco UCS 검증은 별도 진행.


def test_hostname_never_null(baseline_envelope: dict) -> None:
    """build_output.yml fallback chain (system.hostname OR system.fqdn OR ip)
    guarantees non-null hostname. Concern 7: if hostname == ip that is the
    intentional ip_fallback path, not a bug."""
    label = baseline_envelope["__label"]
    hostname = baseline_envelope.get("hostname")
    assert hostname is not None and hostname != "", (
        f"[{label}] hostname is empty — fallback chain broken"
    )


def test_ip_present(baseline_envelope: dict) -> None:
    """ip is always present — hostname fallback ultimate sentinel."""
    label = baseline_envelope["__label"]
    ip = baseline_envelope.get("ip")
    assert ip, f"[{label}] ip empty — fallback chain ultimate sentinel missing"


# ---------------------------------------------------------------------------
# T4 — vendor canonical form regression
# ---------------------------------------------------------------------------
def test_vendor_canonical(baseline_envelope: dict) -> None:
    """ESXi/Redfish vendor must be canonical (e.g., 'cisco' not 'Cisco
    Systems Inc')."""
    label = baseline_envelope["__label"]
    vendor = baseline_envelope.get("vendor")
    assert vendor in CANONICAL_VENDORS, (
        f"[{label}] vendor not canonical: {vendor!r} "
        f"(expected one of {sorted(str(v) for v in CANONICAL_VENDORS)})"
    )


# ---------------------------------------------------------------------------
# T5 — status enum (4 scenarios A/B/C/D)
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
# T7 — diagnosis dict shape invariant
# ---------------------------------------------------------------------------
def test_diagnosis_is_dict(baseline_envelope: dict) -> None:
    """diagnosis must be dict, not list/str (shape fix)."""
    label = baseline_envelope["__label"]
    diagnosis = baseline_envelope.get("diagnosis")
    assert isinstance(diagnosis, dict), (
        f"[{label}] diagnosis not dict: {type(diagnosis).__name__}"
    )


def test_diagnosis_has_4stage_keys(baseline_envelope: dict) -> None:
    """precheck 4-stage keys must be present in success path
    (ping → port → protocol → auth)."""
    label = baseline_envelope["__label"]
    diagnosis = baseline_envelope.get("diagnosis", {})
    for key in ("reachable", "port_open", "protocol_supported", "auth_success"):
        assert key in diagnosis, (
            f"[{label}] diagnosis.{key} missing — precheck shape broken"
        )


# ---------------------------------------------------------------------------
# T8 — errors[] is list (fragment type)
# ---------------------------------------------------------------------------
def test_errors_is_list(baseline_envelope: dict) -> None:
    """_errors_fragment is list of dicts."""
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
# T9 — schema_version present and matches policy
# ---------------------------------------------------------------------------
def test_schema_version_is_one(baseline_envelope: dict) -> None:
    """schema_version is currently 1 (bumped only by user)."""
    label = baseline_envelope["__label"]
    sv = baseline_envelope.get("schema_version")
    assert sv == "1", (
        f"[{label}] schema_version expected '1', got {sv!r}"
    )


# ---------------------------------------------------------------------------
# T10 — Aggregate: all 8 baselines covered (baseline registry)
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
