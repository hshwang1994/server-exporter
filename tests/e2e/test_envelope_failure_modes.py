"""P0 envelope failure-mode 회귀 fixture.

목적
----
3-channel (redfish/os/esxi) site.yml 의 block/rescue/always 패턴이
모든 실패 시나리오에서 13 필드 envelope 을 출력하는지 검증한다.

검증 대상 13 필드 (rule 13 R5 / rule 20 R1 정본 = build_output.yml)
    target_type, collection_method, ip, hostname, vendor,
    status, sections, diagnosis, meta, correlation, errors, data,
    schema_version

실패 시나리오 4 종 × 채널 3 = 12 fixture
    - precheck_unreachable : ping 실패 (단계 1)
    - precheck_auth_fail   : 인증 실패 (단계 4)
    - collect_partial      : 일부 섹션만 실패
    - block_rescue_failed  : block + rescue 모두 실패 → always fallback

본 테스트는 *envelope 구조 회귀* 만 검증한다. 실제 ansible-playbook 실행은
Jenkins Stage 4 (E2E Regression) 책임.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# 13 필드 정본 (rule 13 R5 / rule 20 R1)
# ---------------------------------------------------------------------------
ENVELOPE_REQUIRED_KEYS: tuple[str, ...] = (
    "schema_version",
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
)

ALLOWED_STATUSES: frozenset[str] = frozenset({"success", "partial", "failed"})

ALLOWED_TARGET_TYPES: frozenset[str] = frozenset({"redfish", "os", "esxi"})

# 비밀값 leak 방어 (사용자 명시 password — fixture 안에 절대 포함 금지)
SECRET_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in (
        r"Passw0rd1!",
        r"Goodmit0802!",
        r"Dellidrac1!",
        r"hpinvent1!",
        r"VMware1!",
        # generic patterns: password=..., "password":"<val>" 형식
        r"password\s*[=:]\s*[^\s\"',}]{4,}",
    )
)


# ---------------------------------------------------------------------------
# Sample fallback envelopes (always 블록이 만들 수 있는 형태 시뮬레이션)
#
# 각 fixture 는 실제 site.yml fallback envelope 의 모양을 본떠 작성.
# 수정 시 redfish-gather/site.yml:163-181, os-gather/site.yml:278-296,
# esxi-gather/site.yml:160-178 의 always 블록과 정합 유지 필요.
# ---------------------------------------------------------------------------
def _empty_sections() -> dict[str, str]:
    return {}


def _failed_envelope(
    target_type: str,
    collection_method: str,
    failure_stage: str,
    failure_reason: str,
    *,
    sections_supported: tuple[str, ...] = (),
    vendor: str | None = None,
) -> dict[str, Any]:
    """always 블록 fallback envelope 시뮬레이션."""
    sections = {name: "failed" for name in sections_supported}
    return {
        "schema_version": "1",
        "target_type": target_type,
        "collection_method": collection_method,
        "ip": "10.100.64.10",
        "hostname": "10.100.64.10",
        "vendor": vendor,
        "status": "failed",
        "sections": sections,
        "diagnosis": {
            "precheck": {
                "reachable": failure_stage != "reachable",
                "port_open": failure_stage not in ("reachable", "port"),
                "protocol_supported": failure_stage
                not in ("reachable", "port", "protocol"),
                "auth_success": failure_stage
                not in ("reachable", "port", "protocol", "auth"),
                "failure_stage": failure_stage,
                "failure_reason": failure_reason,
            },
            "gather_mode": "fallback",
            "details": {},
        },
        "meta": {},
        "correlation": {},
        "errors": [
            {
                "section": "gather",
                "message": failure_reason,
            }
        ],
        "data": {},
    }


def _partial_envelope(
    target_type: str,
    collection_method: str,
    *,
    success: tuple[str, ...],
    failed: tuple[str, ...],
    vendor: str | None = None,
) -> dict[str, Any]:
    """일부 섹션 성공/실패 시 envelope 시뮬레이션."""
    sections: dict[str, str] = {name: "success" for name in success}
    for name in failed:
        sections[name] = "failed"
    return {
        "schema_version": "1",
        "target_type": target_type,
        "collection_method": collection_method,
        "ip": "10.100.64.10",
        "hostname": "host01.example.com",
        "vendor": vendor,
        "status": "partial",
        "sections": sections,
        "diagnosis": {
            "precheck": {
                "reachable": True,
                "port_open": True,
                "protocol_supported": True,
                "auth_success": True,
            },
            "gather_mode": "normal",
            "details": {"adapter_candidate": "redfish_dell_idrac9"},
        },
        "meta": {
            "adapter_id": "redfish_dell_idrac9",
            "duration_ms": 4523,
        },
        "correlation": {
            "host_ip": "10.100.64.10",
            "system_uuid": None,
            "serial_number": None,
        },
        "errors": [
            {
                "section": name,
                "message": f"{name} collection failed: timeout",
            }
            for name in failed
        ],
        "data": {name: {"_placeholder": True} for name in success},
    }


# ---------------------------------------------------------------------------
# 12 envelope fixture  (4 모드 × 3 채널)
# ---------------------------------------------------------------------------
ENVELOPES: dict[str, dict[str, Any]] = {
    # ------------------------------ Redfish ------------------------------
    "redfish__precheck_unreachable": _failed_envelope(
        target_type="redfish",
        collection_method="redfish_api",
        failure_stage="reachable",
        failure_reason="대상 호스트에 ICMP/TCP 도달 불가 — BMC 전원/네트워크 확인",
        sections_supported=(
            "system",
            "hardware",
            "bmc",
            "cpu",
            "memory",
            "storage",
            "network",
            "firmware",
            "power",
        ),
    ),
    "redfish__precheck_auth_fail": _failed_envelope(
        target_type="redfish",
        collection_method="redfish_api",
        failure_stage="auth",
        failure_reason="BMC 인증 실패 — 자격증명 후보 모두 실패",
        sections_supported=("system", "hardware", "bmc", "cpu", "memory"),
        vendor="dell",
    ),
    "redfish__collect_partial": _partial_envelope(
        target_type="redfish",
        collection_method="redfish_api",
        success=("system", "hardware", "bmc", "cpu", "memory"),
        failed=("storage", "network", "firmware", "power"),
        vendor="dell",
    ),
    "redfish__block_rescue_failed": {
        # always 블록의 hard-coded fallback (redfish-gather/site.yml:182-201)
        # production-audit (2026-04-29): details 가 dict shape 으로 통일됨 — 호출자 TypeError 차단
        "schema_version": "1",
        "target_type": "redfish",
        "collection_method": "redfish_api",
        "ip": "10.100.64.10",
        "hostname": "10.100.64.10",
        "vendor": None,
        "status": "failed",
        "sections": {},
        "diagnosis": {
            "reachable": None,
            "port_open": None,
            "protocol_supported": None,
            "auth_success": None,
            "failure_stage": "fallback",
            "failure_reason": "_output 미생성 — block/rescue 모두 실패",
            "details": {
                "gather_mode": "fallback",
                "reason": "_output 미생성 — block/rescue 모두 실패",
            },
        },
        "meta": {},
        "correlation": {},
        "errors": [
            {
                "section": "gather",
                "message": "_output 미생성 — block/rescue 모두 실패",
            }
        ],
        "data": {},
    },
    # ------------------------------- OS ----------------------------------
    "os__precheck_unreachable": _failed_envelope(
        target_type="os",
        collection_method="ansible",
        failure_stage="port",
        failure_reason="SSH(22) / WinRM(5985/5986) 포트 모두 닫힘",
        sections_supported=("system", "cpu", "memory", "storage", "network", "users"),
    ),
    "os__precheck_auth_fail": _failed_envelope(
        target_type="os",
        collection_method="ansible",
        failure_stage="auth",
        failure_reason="OS 자격증명 후보 모두 실패 (1차/2차)",
        sections_supported=("system", "cpu", "memory", "storage", "network"),
    ),
    "os__collect_partial": _partial_envelope(
        target_type="os",
        collection_method="ansible",
        success=("system", "cpu", "memory"),
        failed=("storage", "network"),
    ),
    "os__block_rescue_failed": {
        # production-audit (2026-04-29): details dict shape (os-gather/site.yml:308-326,475-493)
        "schema_version": "1",
        "target_type": "os",
        "collection_method": "ansible",
        "ip": "10.100.64.10",
        "hostname": "10.100.64.10",
        "vendor": None,
        "status": "failed",
        "sections": {},
        "diagnosis": {
            "reachable": None,
            "port_open": None,
            "protocol_supported": None,
            "auth_success": None,
            "failure_stage": "fallback",
            "failure_reason": "_output 미생성 — block/rescue 모두 실패",
            "details": {
                "gather_mode": "fallback",
                "reason": "_output 미생성 — block/rescue 모두 실패",
            },
        },
        "meta": {},
        "correlation": {},
        "errors": [
            {
                "section": "gather",
                "message": "_output 미생성 — block/rescue 모두 실패",
            }
        ],
        "data": {},
    },
    # ------------------------------ ESXi ---------------------------------
    "esxi__precheck_unreachable": _failed_envelope(
        target_type="esxi",
        collection_method="vmware",
        failure_stage="reachable",
        failure_reason="ESXi/vCenter 호스트 도달 불가",
        sections_supported=("system", "hardware", "cpu", "memory", "storage", "network"),
    ),
    "esxi__precheck_auth_fail": _failed_envelope(
        target_type="esxi",
        collection_method="vmware",
        failure_stage="auth",
        failure_reason="ESXi 자격증명 후보 모두 실패 (1차/2차)",
        sections_supported=("system", "hardware", "cpu", "memory", "storage", "network"),
    ),
    "esxi__collect_partial": _partial_envelope(
        target_type="esxi",
        collection_method="vmware",
        success=("system", "hardware", "cpu", "memory"),
        failed=("storage", "network"),
    ),
    "esxi__block_rescue_failed": {
        # production-audit (2026-04-29): details dict shape (esxi-gather/site.yml:183-201)
        "schema_version": "1",
        "target_type": "esxi",
        "collection_method": "vmware",
        "ip": "10.100.64.10",
        "hostname": "10.100.64.10",
        "vendor": None,
        "status": "failed",
        "sections": {},
        "diagnosis": {
            "reachable": None,
            "port_open": None,
            "protocol_supported": None,
            "auth_success": None,
            "failure_stage": "fallback",
            "failure_reason": "_output 미생성 — block/rescue 모두 실패",
            "details": {
                "gather_mode": "fallback",
                "reason": "_output 미생성 — block/rescue 모두 실패",
            },
        },
        "meta": {},
        "correlation": {},
        "errors": [
            {
                "section": "gather",
                "message": "_output 미생성 — block/rescue 모두 실패",
            }
        ],
        "data": {},
    },
}


# ---------------------------------------------------------------------------
# 검증 헬퍼
# ---------------------------------------------------------------------------
def _assert_no_secret_leak(envelope: dict[str, Any]) -> None:
    """envelope 안에 password 원문/사용자 명시 비밀값 노출 없는지 확인."""
    serialized = json.dumps(envelope, ensure_ascii=False)
    for pattern in SECRET_VALUE_PATTERNS:
        match = pattern.search(serialized)
        assert match is None, (
            f"envelope 안에 비밀값 leak 의심 — pattern={pattern.pattern!r} "
            f"matched={match.group(0)!r}"
        )


def _assert_envelope_shape(envelope: dict[str, Any]) -> None:
    """13 필드 + 타입 + status/target_type 허용 범위 확인."""
    # 1) 13 필드 모두 존재
    for key in ENVELOPE_REQUIRED_KEYS:
        assert key in envelope, f"envelope 13 필드 중 '{key}' 누락"

    # 2) schema_version
    assert envelope["schema_version"] == "1", (
        f"schema_version 불일치: {envelope.get('schema_version')!r}"
    )

    # 3) target_type / collection_method
    assert envelope["target_type"] in ALLOWED_TARGET_TYPES, (
        f"target_type 허용 외: {envelope['target_type']!r}"
    )
    assert isinstance(envelope["collection_method"], str)
    assert envelope["collection_method"], "collection_method 비어 있음"

    # 4) status
    assert envelope["status"] in ALLOWED_STATUSES, (
        f"status 허용 외: {envelope['status']!r}"
    )

    # 5) 타입 검증
    assert isinstance(envelope["sections"], dict), "sections 는 dict"
    assert isinstance(envelope["diagnosis"], dict), "diagnosis 는 dict"
    assert isinstance(envelope["meta"], dict), "meta 는 dict"
    assert isinstance(envelope["correlation"], dict), "correlation 는 dict"
    assert isinstance(envelope["errors"], list), "errors 는 list"
    assert isinstance(envelope["data"], dict), "data 는 dict"

    # 6) ip / hostname 비어 있지 않음
    assert envelope["ip"], "ip 비어 있음"
    assert envelope["hostname"], "hostname 비어 있음"

    # 7) vendor 는 None 또는 str
    assert envelope["vendor"] is None or isinstance(envelope["vendor"], str), (
        f"vendor 타입 오류: {type(envelope['vendor']).__name__}"
    )


def _assert_failed_envelope_invariants(envelope: dict[str, Any]) -> None:
    """status=failed 시 errors[] 가 비어 있지 않아야 한다 (운영 가시성)."""
    if envelope["status"] != "failed":
        return
    assert len(envelope["errors"]) > 0, "status=failed 인데 errors[] 비어 있음"
    # 각 error 항목은 section/message 키를 가져야 함 (build_errors.yml 정합)
    for err in envelope["errors"]:
        assert isinstance(err, dict), f"errors[] 요소가 dict 가 아님: {err!r}"
        assert "section" in err, f"errors[] 항목에 section 키 누락: {err!r}"
        assert "message" in err, f"errors[] 항목에 message 키 누락: {err!r}"


def _assert_partial_envelope_invariants(envelope: dict[str, Any]) -> None:
    """status=partial 시 sections 안에 success 와 failed 가 모두 있어야 한다."""
    if envelope["status"] != "partial":
        return
    statuses = set(envelope["sections"].values())
    assert "success" in statuses or "collected" in statuses, (
        f"status=partial 인데 sections 에 success/collected 없음: {statuses}"
    )
    assert "failed" in statuses, (
        f"status=partial 인데 sections 에 failed 없음: {statuses}"
    )


# ---------------------------------------------------------------------------
# pytest entry-points
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "fixture_id,envelope",
    list(ENVELOPES.items()),
    ids=list(ENVELOPES.keys()),
)
class TestEnvelopeFailureModes:
    """모든 실패 시나리오 envelope 이 13 필드 정본을 만족하는지 회귀 검증."""

    def test_envelope_shape(self, fixture_id: str, envelope: dict[str, Any]) -> None:
        _assert_envelope_shape(envelope)

    def test_no_secret_leak(
        self, fixture_id: str, envelope: dict[str, Any]
    ) -> None:
        _assert_no_secret_leak(envelope)

    def test_failed_invariants(
        self, fixture_id: str, envelope: dict[str, Any]
    ) -> None:
        _assert_failed_envelope_invariants(envelope)

    def test_partial_invariants(
        self, fixture_id: str, envelope: dict[str, Any]
    ) -> None:
        _assert_partial_envelope_invariants(envelope)


def test_fixture_count_matches_design() -> None:
    """plan 파일 정본 = 12 fixture (4 모드 × 3 채널). 우발적 누락 회귀."""
    assert len(ENVELOPES) == 12, f"fixture 개수 불일치: {len(ENVELOPES)}"
    target_types = {env["target_type"] for env in ENVELOPES.values()}
    assert target_types == {"redfish", "os", "esxi"}, (
        f"channel coverage 불일치: {target_types}"
    )


def test_required_keys_constant_unchanged() -> None:
    """ENVELOPE_REQUIRED_KEYS 13개 정본 — 의도치 않은 추가/삭제 회귀."""
    assert len(ENVELOPE_REQUIRED_KEYS) == 13, (
        f"13 필드 정본 변경 감지: {len(ENVELOPE_REQUIRED_KEYS)}. "
        f"rule 13 R5 + rule 20 R1 정본은 build_output.yml — 함께 갱신 필요."
    )
