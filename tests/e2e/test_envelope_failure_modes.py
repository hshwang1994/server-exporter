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

# 2026-08-12: 누출 가드가 검사 대상인 **진짜 비밀번호를 소스에 그대로** 적어 두고 있었다.
#   가드 파일 자체가 누출 지점이라, 평문 대신 sha256 앞 8자리로 대조하는 공용 가드로
#   바꾼다. 입력으로 넣던 실 자격증명도 합성 canary 로 바꾼다 (검사 의미는 동일).
from tests.secret_guard import (  # noqa: E402
    CANARY_PASSWORD, CANARY_RECOVERY, CANARY_TARGET, assert_no_secret,
)


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
        r"zzz-canary-target-zzz",
        r"zzz-canary-password-zzz",
        # generic patterns: password=..., "password":"<val>" 형식
        r"password\s*[=:]\s*[^\s\"',}]{4,}",
    )
)


# ---------------------------------------------------------------------------
# Sample fallback envelopes (always 블록이 만들 수 있는 형태 시뮬레이션)
#
# 각 fixture 는 실제 site.yml fallback envelope 의 모양을 본떠 작성.
# 수정 시 redfish-gather/site.yml:254-272, os-gather/site.yml:359-377 (linux) /
# :548-566 (windows), esxi-gather/site.yml:246-268 의 always 블록과 정합 유지 필요.
#
# 2026-08-10 정정 (인용 라인 stale + diagnosis shape 오기재):
#   - 종전 인용 라인(redfish :163-181 등)은 HEAD 에서 다른 코드(OEM graceful 블록)를 가리켰다.
#   - 종전 fixture 는 diagnosis 를 {"precheck": {...}, "gather_mode": ..., "details": {...}}
#     **중첩 구조**로 만들었으나, production 은 build_diagnosis()(filter_plugins/
#     diagnosis_mapper.py:60-68)가 반환하는 **flat 구조**다
#     ({reachable, port_open, protocol_supported, auth_success, failure_stage,
#       failure_reason, details}). `precheck` 라는 하위 키를 만드는 production 코드는 없다
#     (schema/baseline_v1/*.json 10건 전수 확인). 중첩 fixture 는 실제 회귀를 잡지 못한다.
#   - collection_method 도 실제 값과 달랐다 (os: "ansible"→"agent",
#     esxi: "vmware"→"vsphere_api" — os-gather/site.yml:152, esxi-gather/site.yml:187).
# ---------------------------------------------------------------------------
# Phase 2 (2026-08-10): failure_stage -> failure_code 기본 매핑.
# production 정본은 field_dictionary.yml + 각 site.yml 이며, 여기서는 fixture 생성용 사본이다.
_STAGE_TO_CODE: dict[str, str] = {
    "reachable": "TCP_CONNECT_FAILED",
    "port": "TCP_CONNECTION_REFUSED",
    "protocol": "PROTOCOL_CHECK_FAILED",
    "auth": "AUTH_PROBE_FAILED",
    "gather": "GATHER_FAILED",
    "fallback": "OUTPUT_BUILD_FAILED",
}


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
        "hostname": None,
        "vendor": vendor,
        "status": "failed",
        "sections": sections,
        # production 과 동일한 flat shape (diagnosis_mapper.build_diagnosis 반환형).
        # 각 boolean 은 "그 단계 통과를 확인했는가" — failure_stage 이전 단계만 true.
        "diagnosis": {
            "reachable": failure_stage != "reachable",
            "port_open": failure_stage not in ("reachable", "port"),
            "protocol_supported": failure_stage
            not in ("reachable", "port", "protocol"),
            # auth 는 3-값. precheck 는 Stage 4 를 수행하지 않으므로
            # (precheck_bundle.py:546-548) 실패 경로에서 true 가 될 수 없다.
            "auth_success": None,
            "failure_stage": failure_stage,
            # Phase 2: 시스템 분기용 안정 식별자 (정상 결과에서도 키는 존재)
            "failure_code": _STAGE_TO_CODE[failure_stage],
            "failure_reason": failure_reason,
            "details": {"channel": target_type, "gather_mode": "fallback"},
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
        # production flat shape — 수집이 진행된 경로라 site.yml 이 auth_success 를
        # true 로 덮어쓴 상태 (redfish-gather/site.yml:191-206 / esxi:194-210).
        "diagnosis": {
            "reachable": True,
            "port_open": True,
            "protocol_supported": True,
            "auth_success": True,
            "failure_stage": None,
            # partial 이라는 이유로 대표 stage/code 를 강제로 만들지 않는다 (build_status 정책 유지)
            "failure_code": None,
            "failure_reason": None,
            "details": {
                "channel": target_type,
                "adapter_candidate": "redfish_dell_idrac9",
                "gather_mode": "normal",
            },
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
        "hostname": None,
        "vendor": None,
        "status": "failed",
        "sections": {},
        "diagnosis": {
            "reachable": None,
            "port_open": None,
            "protocol_supported": None,
            "auth_success": None,
            "failure_stage": "fallback",
            "failure_code": "OUTPUT_BUILD_FAILED",
            "failure_reason": "수집 결과를 생성하지 못했습니다. 수집기 내부 오류이므로 실행 로그를 확인하세요.",
            "details": {
                "gather_mode": "fallback",
                "reason": "_output 미생성 (block/rescue 모두 실패)",
            },
        },
        "meta": {},
        "correlation": {},
        "errors": [
            {
                "section": "gather",
                "message": "수집 결과를 생성하지 못했습니다. 수집기 내부 오류이므로 실행 로그를 확인하세요.",
            }
        ],
        "data": {},
    },
    # ------------------------------- OS ----------------------------------
    "os__precheck_unreachable": _failed_envelope(
        target_type="os",
        collection_method="agent",
        failure_stage="port",
        failure_reason="SSH(22) / WinRM(5985/5986) 포트 모두 닫힘",
        sections_supported=("system", "cpu", "memory", "storage", "network", "users"),
    ),
    "os__precheck_auth_fail": _failed_envelope(
        target_type="os",
        collection_method="agent",
        failure_stage="auth",
        failure_reason="OS 자격증명 후보 모두 실패 (1차/2차)",
        sections_supported=("system", "cpu", "memory", "storage", "network"),
    ),
    "os__collect_partial": _partial_envelope(
        target_type="os",
        collection_method="agent",
        success=("system", "cpu", "memory"),
        failed=("storage", "network"),
    ),
    "os__block_rescue_failed": {
        # production-audit (2026-04-29): details dict shape (os-gather/site.yml:308-326,475-493)
        "schema_version": "1",
        "target_type": "os",
        "collection_method": "agent",
        "ip": "10.100.64.10",
        "hostname": None,
        "vendor": None,
        "status": "failed",
        "sections": {},
        "diagnosis": {
            "reachable": None,
            "port_open": None,
            "protocol_supported": None,
            "auth_success": None,
            "failure_stage": "fallback",
            "failure_code": "OUTPUT_BUILD_FAILED",
            "failure_reason": "수집 결과를 생성하지 못했습니다. 수집기 내부 오류이므로 실행 로그를 확인하세요.",
            "details": {
                "gather_mode": "fallback",
                "reason": "_output 미생성 (block/rescue 모두 실패)",
            },
        },
        "meta": {},
        "correlation": {},
        "errors": [
            {
                "section": "gather",
                "message": "수집 결과를 생성하지 못했습니다. 수집기 내부 오류이므로 실행 로그를 확인하세요.",
            }
        ],
        "data": {},
    },
    # ------------------------------ ESXi ---------------------------------
    "esxi__precheck_unreachable": _failed_envelope(
        target_type="esxi",
        collection_method="vsphere_api",
        failure_stage="reachable",
        failure_reason="ESXi/vCenter 호스트 도달 불가",
        sections_supported=("system", "hardware", "cpu", "memory", "storage", "network"),
    ),
    "esxi__precheck_auth_fail": _failed_envelope(
        target_type="esxi",
        collection_method="vsphere_api",
        failure_stage="auth",
        failure_reason="ESXi 자격증명 후보 모두 실패 (1차/2차)",
        sections_supported=("system", "hardware", "cpu", "memory", "storage", "network"),
    ),
    "esxi__collect_partial": _partial_envelope(
        target_type="esxi",
        collection_method="vsphere_api",
        success=("system", "hardware", "cpu", "memory"),
        failed=("storage", "network"),
    ),
    "esxi__block_rescue_failed": {
        # production-audit (2026-04-29): details dict shape (esxi-gather/site.yml:183-201)
        "schema_version": "1",
        "target_type": "esxi",
        "collection_method": "vsphere_api",
        "ip": "10.100.64.10",
        "hostname": None,
        "vendor": None,
        "status": "failed",
        "sections": {},
        "diagnosis": {
            "reachable": None,
            "port_open": None,
            "protocol_supported": None,
            "auth_success": None,
            "failure_stage": "fallback",
            "failure_code": "OUTPUT_BUILD_FAILED",
            "failure_reason": "수집 결과를 생성하지 못했습니다. 수집기 내부 오류이므로 실행 로그를 확인하세요.",
            "details": {
                "gather_mode": "fallback",
                "reason": "_output 미생성 (block/rescue 모두 실패)",
            },
        },
        "meta": {},
        "correlation": {},
        "errors": [
            {
                "section": "gather",
                "message": "수집 결과를 생성하지 못했습니다. 수집기 내부 오류이므로 실행 로그를 확인하세요.",
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
    # 알려진 실 자격증명이 섞였는지 digest 로 대조한다 (평문을 저장하지 않는 가드).
    assert_no_secret(serialized, "envelope")
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

    # 6) ip 는 비어 있지 않고, hostname 은 null 또는 문자열 — IP 로 대체하지 않는다 (2026-06-16 정책 / 2026-09-03 B-01)
    assert envelope["ip"], "ip 비어 있음"
    assert envelope["hostname"] is None or isinstance(envelope["hostname"], str), "hostname 은 null|str"
    assert envelope["hostname"] != envelope["ip"], "hostname 이 IP 로 대체됐다 (ip-fallback 잔재)"

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
