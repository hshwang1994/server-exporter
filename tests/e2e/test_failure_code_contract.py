"""Phase 2 계약: failure_stage / failure_code 를 시스템이 안정적으로 분기할 수 있어야 한다.

배경
----
Phase 1 에서 `diagnosis.failure_reason`(Portal Grid 표시용 사람 문장)은 모든 실패 경로에서
채워지도록 고정했다. 그러나 외부 시스템이 실패 **종류**로 분기하려면 사람 문장을 파싱해야 했다.

Phase 2 는 두 축을 완성한다.

  failure_stage : **실행이 중단된 단계** (원인이 아니다)
                  reachable | port | protocol | auth | gather | fallback | null
  failure_code  : 실패 종류의 **안정 식별자** (신규 nullable 필드, 정상 결과에서도 키 존재)

본 테스트는 합성 fixture 가 아니라 production site.yml / precheck_bundle 을 직접 렌더·실행해
검증한다. 헬퍼는 test_failure_reason_contract 와 공유한다 (렌더 환경 정의 중복 방지).
"""
from __future__ import annotations

import json
import socket
from typing import Any

import pytest

# 2026-08-12: 누출 가드가 검사 대상인 **진짜 비밀번호를 소스에 그대로** 적어 두고 있었다.
#   가드 파일 자체가 누출 지점이라, 평문 대신 sha256 앞 8자리로 대조하는 공용 가드로
#   바꾼다. 입력으로 넣던 실 자격증명도 합성 canary 로 바꾼다 (검사 의미는 동일).
from tests.secret_guard import (  # noqa: E402
    CANARY_PASSWORD, CANARY_RECOVERY, CANARY_TARGET, assert_no_secret,
)

import yaml

from tests.precheck_stub import ICMP_REPLY, ICMP_SILENT  # noqa: E402

from tests.e2e.test_failure_reason_contract import (
    REPO,
    _ESXI_TASK,
    _FALLBACK_CTX,
    _OS_TASKS,
    _PRECHECK_OK_DIAG,
    _RF_TASK,
    render_redfish_rescue,
    _failed_envelopes,
    _render_diagnosis,
    _render_fallback_envelopes,
    _run_precheck,
    pb,
)

# ---------------------------------------------------------------------------
# Contract 정본 (field_dictionary 와 일치해야 한다 — 아래 마지막 테스트가 대조)
# ---------------------------------------------------------------------------
ALLOWED_STAGES: frozenset[str] = frozenset(
    {"reachable", "port", "protocol", "auth", "gather", "fallback"}
)

ALLOWED_CODES: frozenset[str] = frozenset({
    "DNS_RESOLUTION_FAILED",
    # 2026-09-03: reachable 이 "관리 TCP 응답 OR ICMP Echo 응답" 이 되면서, 종전
    #   TCP_CONNECT_FAILED 하나가 겸하던 두 상황이 갈렸다.
    #     TARGET_UNREACHABLE : TCP 도 ICMP 도 무응답            (stage=reachable)
    #     TCP_CONNECT_FAILED : ICMP 는 응답, 관리 TCP 만 무응답 (stage=port)
    #   ICMP 전용 code 는 만들지 않는다 — ICMP 는 도달 근거를 더할 뿐 실패를 만들지 않는다.
    "TARGET_UNREACHABLE",
    "TCP_CONNECT_FAILED",
    "TCP_CONNECTION_REFUSED",
    "PROTOCOL_CHECK_FAILED",
    "AUTH_PROBE_FAILED",
    # 2026-08-12: Credential 선택이 Location 축을 갖게 되면서 "자격 세트 자체가 없어
    #   인증을 시도조차 못 했다" 가 별도 상태가 됐다. AUTH_PROBE_FAILED 로 뭉개면
    #   소비 시스템이 두 상황을 구분할 수 없다.
    "CREDENTIAL_SET_UNAVAILABLE",
    "GATHER_FAILED",
    "OUTPUT_BUILD_FAILED",
})

# code -> 허용 stage. code 와 stage 는 1:1 이다.
#   2026-09-03: TCP_CONNECT_FAILED 의 허용 stage 에서 reachable 을 **뺐다**. ICMP 응답으로
#   도달이 확인된 상태에서만 이 code 가 나오므로, 멈춘 위치는 언제나 관리 포트 단계다.
#   TCP·ICMP 모두 무응답인 경우는 TARGET_UNREACHABLE 이 맡는다.
CODE_TO_STAGES: dict[str, frozenset[str]] = {
    "DNS_RESOLUTION_FAILED":  frozenset({"reachable"}),
    "TARGET_UNREACHABLE":     frozenset({"reachable"}),
    "TCP_CONNECT_FAILED":     frozenset({"port"}),
    "TCP_CONNECTION_REFUSED": frozenset({"port"}),
    "PROTOCOL_CHECK_FAILED":  frozenset({"protocol"}),
    "AUTH_PROBE_FAILED":      frozenset({"auth"}),
    # stage 는 원인이 아니라 **멈춘 위치**다 (CLAUDE.md §9). 자격 세트를 못 열어 멈춘
    # 곳도 자격증명 단계이므로 auth 다. 원인 구분은 code 와 auth_success 가 표현한다.
    "CREDENTIAL_SET_UNAVAILABLE": frozenset({"auth"}),
    "GATHER_FAILED":          frozenset({"gather"}),
    "OUTPUT_BUILD_FAILED":    frozenset({"fallback"}),
}


def _assert_stage_code(diag: dict[str, Any], label: str) -> None:
    assert "failure_code" in diag, f"[{label}] failure_code 키 부재 (shape 고정 위반)"
    stage, code = diag.get("failure_stage"), diag.get("failure_code")
    assert stage in ALLOWED_STAGES, f"[{label}] 허용 밖 failure_stage: {stage!r}"
    assert code in ALLOWED_CODES, f"[{label}] 허용 밖 failure_code: {code!r}"
    assert stage in CODE_TO_STAGES[code], (
        f"[{label}] code/stage 조합 위반: {code} 는 {sorted(CODE_TO_STAGES[code])} 에서만 "
        f"허용되는데 stage={stage!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Case 1~5 — precheck 단계별 stage/code
# ═══════════════════════════════════════════════════════════════════════════
def test_case01_success_has_null_stage_and_code(monkeypatch):
    result = _run_precheck(
        monkeypatch, "redfish",
        http=(True, None, {"status_code": 200, "json": {"@odata.id": "/redfish/v1", "@odata.type": "#ServiceRoot.v1_15_0.ServiceRoot", "RedfishVersion": "1.6.0"}}),
    )
    assert "failure_code" in result, "정상 결과에도 키는 존재해야 한다"
    assert result["failure_stage"] is None
    assert result["failure_code"] is None
    assert result["failure_reason"] is None


def test_case02_dns_failure(monkeypatch):
    # _run_precheck 이 socket 계층을 통째로 대체하므로, 그보다 상위 seam 인 tcp_check_ex 를
    # 직접 대체해 DNS 실패 kind 를 주입한다 (오류 문자열이 아니라 구조화된 kind 로 분류되는지 확인).
    monkeypatch.setattr(
        pb, "tcp_check_ex",
        lambda *_a, **_k: (False, "DNS 해석 실패: Name or service not known", pb.TCP_FAIL_DNS),
    )
    result = _run_precheck(monkeypatch, "redfish")
    assert result["failure_stage"] == "reachable"
    assert result["failure_code"] == "DNS_RESOLUTION_FAILED"
    assert result["auth_success"] is None
    _assert_stage_code(result, "C2 DNS")


@pytest.mark.parametrize("exc,label", [
    (socket.timeout(), "timeout"),
    (OSError("EHOSTUNREACH"), "no route"),
])
def test_case03_no_response_is_target_unreachable_not_device_down(exc, label, monkeypatch):
    """timeout / no route + ICMP 무응답 → TARGET_UNREACHABLE.

    2026-09-03 이름 변경 (종전 TCP_CONNECT_FAILED). 이 code 는 "우리가 쓴 probe(TCP·ICMP)
    로 응답을 보지 못했다" 는 **관측**이지 "장비가 꺼졌다" 는 **확정**이 아니다. 그 경계를
    아래 assertion 이 계속 지킨다 — 사용자 문장이 전원/다운을 주장하면 실패한다.
    """
    result = _run_precheck(monkeypatch, "redfish", connect_exc=exc)
    assert result["failure_stage"] == "reachable", label
    assert result["failure_code"] == "TARGET_UNREACHABLE", label
    assert result["auth_success"] is None
    for banned in ("전원", "다운", "꺼졌"):
        assert banned not in result["failure_reason"], (
            f"[{label}] 관측하지 않은 원인을 단정한다: {result['failure_reason']!r}"
        )
    _assert_stage_code(result, f"C3 {label}")


@pytest.mark.parametrize("exc,label", [
    (socket.timeout(), "timeout"),
    (OSError("EHOSTUNREACH"), "no route"),
])
def test_case03b_icmp_reply_moves_failure_to_port_stage(exc, label, monkeypatch):
    """TCP 무응답이어도 ICMP Echo Reply 가 오면 도달은 성립한다 (2026-09-03).

    reachable = TCP 응답 OR ICMP 응답. 도달이 확인된 뒤 막힌 곳은 관리 포트이므로
    stage=port + TCP_CONNECT_FAILED 이고, 사용자 문장도 "IP 사용 여부" 가 아니라
    "관리 포트 / 방화벽 확인" 으로 바뀐다.
    """
    result = _run_precheck(monkeypatch, "redfish", connect_exc=exc, icmp=ICMP_REPLY)
    assert result["reachable"] is True, label
    assert result["port_open"] is False, "도달했다고 관리 포트가 열린 것은 아니다"
    assert result["failure_stage"] == "port", label
    assert result["failure_code"] == "TCP_CONNECT_FAILED", label
    assert result["failure_reason"] == pb.REASON_PORT_UNREACHABLE, label
    assert "icmp" in (result["detail"] or ""), "ICMP 관측 근거가 detail 에 남아야 한다"
    _assert_stage_code(result, f"C3b {label}")


def test_icmp_failure_never_creates_its_own_code(monkeypatch):
    """ICMP 는 실패를 만들지 않는다 — 전용 failure_code / stage 가 생기면 실패."""
    result = _run_precheck(monkeypatch, "redfish", connect_exc=socket.timeout(),
                           icmp=(False, "icmp: 확인 불가 (ping 명령 없음)"))
    # ping 을 아예 못 쓰는 환경이어도 판정은 종전(TCP 전용)과 같아야 한다
    assert result["failure_stage"] == "reachable"
    assert result["failure_code"] == "TARGET_UNREACHABLE"
    assert "ICMP" not in result["failure_code"]
    assert result["failure_reason"] == pb.REASON_IP_UNCONFIRMED
    for code in ALLOWED_CODES:
        assert "ICMP" not in code, f"ICMP 전용 code 가 생겼다: {code}"


def test_case04_connection_refused(monkeypatch):
    """RST 를 실제로 관측했을 때만 REFUSED."""
    result = _run_precheck(monkeypatch, "redfish", connect_exc=ConnectionRefusedError())
    assert result["reachable"] is True, "RST 는 호스트가 살아 있다는 증거"
    assert result["failure_stage"] == "port"
    assert result["failure_code"] == "TCP_CONNECTION_REFUSED"
    _assert_stage_code(result, "C4 refused")


@pytest.mark.parametrize("channel", ["redfish", "esxi"])
def test_case05_protocol_check_failed(channel, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    result = _run_precheck(monkeypatch, channel, http=(False, "TLS handshake 오류", None))
    assert result["failure_stage"] == "protocol"
    assert result["failure_code"] == "PROTOCOL_CHECK_FAILED"
    assert result["auth_success"] is None
    _assert_stage_code(result, f"C5 protocol/{channel}")


# ═══════════════════════════════════════════════════════════════════════════
# Case 6~8 — 자격 확인 단계 / HTTP 401 · 403 구분
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("status,expect_auth,note", [
    (401, False, "명시적 인증 거부를 구조화된 status 로 관측"),
    (403, None,  "인증 후 권한 부족일 수 있어 거부로 확정 불가"),
    (500, None,  "서버 오류 — 인증 여부 확정 불가"),
    (408, None,  "timeout — 인증 여부 확정 불가"),
])
def test_case06_08_auth_probe_and_401_403(status, expect_auth, note, monkeypatch):
    result = pb._init_result("redfish", [443])
    monkeypatch.setattr(
        pb, "http_get",
        lambda *_a, s=status, **_k: (False, f"HTTP {s}", {"status_code": s, "json": None}),
    )
    pb._try_redfish_auth("192.0.2.10", 443, "svc", "pw", 8.0, False, result)

    label = f"HTTP {status} ({note})"
    assert result["failure_stage"] == "auth", label
    assert result["failure_code"] == "AUTH_PROBE_FAILED", label
    assert result["auth_success"] is expect_auth, (
        f"{label}: auth_success 기대 {expect_auth!r}, 실제 {result['auth_success']!r}"
    )
    _assert_stage_code(result, label)


# ═══════════════════════════════════════════════════════════════════════════
# 2026-08-12: "자격을 보냈는데 통하지 않았다" ↔ "보낼 자격 자체가 없었다"
#
# Credential 선택이 Location 축을 갖게 되면서(vault/<loc>/...) 후자가 실제로 발생한다:
# se_location 미전달 / 미등록 Location / 해당 Location vault 파일 부재 / 복호화 실패.
# 두 상황을 같은 code 로 만들면 소비 시스템이 구분할 수 없고, 운영자도 엉뚱한 곳
# (대상 장비 계정)을 뒤진다. 아래가 그 구분을 고정한다.
#
# 공통: stage 는 둘 다 auth (멈춘 위치는 자격증명 단계로 같다),
#       auth_success 는 둘 다 None (어느 쪽도 '명시적 거부' 를 관측하지 않았다),
#       사용자 문장도 같다 (4번) — 구분은 **code 와 detail** 이 한다.
# ═══════════════════════════════════════════════════════════════════════════
_CRED_UNAVAILABLE_OUTCOMES = [
    "not_resolved",                  # se_location 미전달 / 미등록 Location / vendor 미결정
    "credential_set_missing",        # 해당 Location 의 vault 파일 부재
    "credential_set_undecryptable",  # 파일은 있으나 복호화 실패
]


@pytest.mark.parametrize("outcome", _CRED_UNAVAILABLE_OUTCOMES)
def test_credential_set_unavailable_is_distinct_from_auth_probe_failed(outcome):
    """3채널 모두 CREDENTIAL_SET_UNAVAILABLE 을 낸다 (AUTH_PROBE_FAILED 로 뭉개지 않는다)."""
    esxi = _render_diagnosis(
        "esxi-gather/site.yml", _ESXI_TASK,
        {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None, "details": {"channel": "esxi"}},
         "_e_auth_ok": False, "_e_facts_ok": False, "_cred_load_outcome": outcome})
    assert esxi["failure_code"] == "CREDENTIAL_SET_UNAVAILABLE", f"esxi/{outcome}"
    assert esxi["failure_stage"] == "auth", f"esxi/{outcome}"
    assert esxi["auth_success"] is None, f"esxi/{outcome}"
    _assert_stage_code(esxi, f"esxi/{outcome}")

    for os_type in ("linux", "windows"):
        ctx: dict[str, Any] = {
            "_os_auth_ok": False, "_os_attempts_meta": {}, "_cred_load_outcome": outcome,
        }
        if os_type == "windows":
            ctx["ansible_port"] = "5986"
        diag = _render_diagnosis("os-gather/site.yml", _OS_TASKS[os_type], ctx)
        label = f"{os_type}/{outcome}"
        assert diag["failure_code"] == "CREDENTIAL_SET_UNAVAILABLE", label
        assert diag["failure_stage"] == "auth", label
        assert diag["auth_success"] is None, label
        _assert_stage_code(diag, label)

    rf = render_redfish_rescue(
        {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None},
         "_rf_collect_ok": False, "_rf_auth_observations": [],
         "_cred_load_outcome": outcome, "_cred_reason": "resolved"})
    assert rf["failure_code"] == "CREDENTIAL_SET_UNAVAILABLE", f"redfish/{outcome}"
    assert rf["failure_stage"] == "auth", f"redfish/{outcome}"
    assert rf["auth_success"] is None, f"redfish/{outcome}"
    _assert_stage_code(rf, f"redfish/{outcome}")


def test_credential_set_loaded_still_yields_auth_probe_failed():
    """자격 세트를 정상으로 열었는데 전멸했다면 그것은 AUTH_PROBE_FAILED 다 (오분류 방지)."""
    for outcome in ("loaded", "empty_accounts"):
        esxi = _render_diagnosis(
            "esxi-gather/site.yml", _ESXI_TASK,
            {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None,
                            "details": {"channel": "esxi"}},
             "_e_auth_ok": False, "_e_facts_ok": False, "_cred_load_outcome": outcome})
        assert esxi["failure_code"] == "AUTH_PROBE_FAILED", outcome


def test_redfish_vendor_unresolved_is_not_credential_unavailable():
    """vendor 미상은 credential set 문제가 아니다 — 빈 자격 best-effort 경로를 유지한다.

    이 경로에서 CREDENTIAL_SET_UNAVAILABLE 을 내면 '자격증명을 배치하라' 고 안내하게
    되는데, 실제로는 장비 정체를 식별하지 못한 것이라 조치가 다르다.
    """
    rf = render_redfish_rescue(
        {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None},
         "_rf_collect_ok": False, "_rf_auth_observations": [],
         "_cred_load_outcome": "not_resolved", "_cred_reason": "vendor_unresolved"})
    assert rf["failure_code"] != "CREDENTIAL_SET_UNAVAILABLE"


def test_missing_cred_outcome_does_not_invent_credential_failure():
    """`_cred_load_outcome` 이 아예 없으면 credential set 문제라고 단정하지 않는다.

    관측하지 못한 것을 단정하지 않는다는 원칙. 변수가 없다는 것은 resolve 단계에
    도달조차 못했다는 뜻일 수 있고, 그것을 '자격 세트 부재' 로 보고하면 거짓이다.
    """
    esxi = _render_diagnosis(
        "esxi-gather/site.yml", _ESXI_TASK,
        {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None,
                        "details": {"channel": "esxi"}},
         "_e_auth_ok": False, "_e_facts_ok": False})
    assert esxi["failure_code"] == "AUTH_PROBE_FAILED"


def test_credential_scope_is_exposed_in_diagnosis_details():
    """실패한 경우에도 **어떤 credential set 을 썼는지** envelope 으로 알 수 있어야 한다.

    종전에는 실패 원인이 자격증명인지 판단할 때 어떤 vault 를 열었는지 알 방법이 없었다.
    location/channel/vendor 조합 문자열이며 Secret 이 아니다.
    """
    diag = _render_diagnosis(
        "os-gather/site.yml", _OS_TASKS["linux"],
        {"_os_auth_ok": False, "_os_attempts_meta": {}, "_cred_scope": "ic/os/linux"})
    assert diag["details"]["credential_scope"] == "ic/os/linux"

    esxi = _render_diagnosis(
        "esxi-gather/site.yml", _ESXI_TASK,
        {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None,
                        "details": {"channel": "esxi"}},
         "_e_auth_ok": False, "_e_facts_ok": False, "_cred_scope": "ic/esxi"})
    assert esxi["details"]["credential_scope"] == "ic/esxi"

    rf = render_redfish_rescue(
        {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None},
         "_rf_collect_ok": False, "_rf_auth_observations": [],
         "_cred_scope": "ic/redfish/dell"})
    assert rf["details"]["credential_scope"] == "ic/redfish/dell"


def test_credential_scope_is_null_when_unresolved():
    """scope 를 못 정했으면 빈 문자열이 아니라 null 이다 (소비자가 '있다' 로 오독하지 않게)."""
    diag = _render_diagnosis(
        "os-gather/site.yml", _OS_TASKS["linux"],
        {"_os_auth_ok": False, "_os_attempts_meta": {}, "_cred_scope": ""})
    assert diag["details"]["credential_scope"] is None


def test_credential_exhaustion_never_claims_auth_false():
    """불변식 7 — 자격 후보 전멸을 실제 인증 실패로 확정하지 않는다 (3채널)."""
    esxi = _render_diagnosis(
        "esxi-gather/site.yml", _ESXI_TASK,
        {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None, "details": {"channel": "esxi"}},
         "_e_auth_ok": False, "_e_facts_ok": False})
    assert esxi["auth_success"] is None and esxi["failure_code"] == "AUTH_PROBE_FAILED"

    for os_type in ("linux", "windows"):
        ctx: dict[str, Any] = {"_os_auth_ok": False, "_os_attempts_meta": {}}
        if os_type == "windows":
            ctx["ansible_port"] = "5986"
        diag = _render_diagnosis("os-gather/site.yml", _OS_TASKS[os_type], ctx)
        assert diag["auth_success"] is None, os_type
        assert diag["failure_code"] == "AUTH_PROBE_FAILED", os_type
        assert diag["failure_stage"] == "auth", os_type


# ═══════════════════════════════════════════════════════════════════════════
# Case 9~12 — gather 단계
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("auth_ok,facts_ok,exp_stage,exp_code,exp_auth", [
    (False, False, "auth",   "AUTH_PROBE_FAILED", None),
    (True,  False, "gather", "GATHER_FAILED",     True),
    (True,  True,  "gather", "GATHER_FAILED",     True),
])
def test_case09_esxi_gather_stage(auth_ok, facts_ok, exp_stage, exp_code, exp_auth):
    diag = _render_diagnosis(
        "esxi-gather/site.yml", _ESXI_TASK,
        {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None, "details": {"channel": "esxi"}},
         "_e_auth_ok": auth_ok, "_e_facts_ok": facts_ok})
    label = f"esxi/auth={auth_ok}/facts={facts_ok}"
    assert diag["failure_stage"] == exp_stage, label
    assert diag["failure_code"] == exp_code, label
    assert diag["auth_success"] is exp_auth, label
    _assert_stage_code(diag, label)


# 2026-08-12 (C1 / C4): redfish rescue 의 4필드는 `_rf_auth_outcome` 하나에서 파생된다.
#   종전에는 stage/code/auth_success 와 failure_reason 이 서로 다른 조건으로 갈려
#   "stage=gather 인데 자격증명 문장" 같은 자기모순 결과가 정상 경로로 나갔다.
@pytest.mark.parametrize("collect_ok,obs,exp_stage,exp_code,exp_auth", [
    # 수집 성공 관측 → 인증은 통과한 것이 증명됨
    (True,  [],                       "gather", "GATHER_FAILED",     True),
    # 자격을 실은 첫 요청이 2xx → 인증 통과 관측
    (False, [{"role": "primary", "status": 200}], "gather", "GATHER_FAILED", True),
    # 자격 요청을 **보내기 전에** 멈췄다 (adapter 선택 / vault 로드 / vendor 정규화 예외).
    #   CLAUDE.md §9 — failure_stage 는 워크플로가 멈춘 위치다. 시도조차 안 한 것을
    #   auth 로 라벨링하면 사용자가 자격증명을 헛되이 뒤진다.
    (False, [],                       "gather", "GATHER_FAILED",     None),
    # timeout / TLS → status 미확정
    (False, [{"role": "primary", "status": None}], "auth", "AUTH_PROBE_FAILED", None),
    # 403 은 인증 통과 후 권한 문제일 수 있어 거부로 확정하지 않는다
    (False, [{"role": "primary", "status": 403}], "auth", "AUTH_PROBE_FAILED", None),
])
def test_case10_redfish_rescue_derives_all_fields_from_auth_outcome(
        collect_ok, obs, exp_stage, exp_code, exp_auth):
    diag = render_redfish_rescue(
        {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None},
         "_rf_collect_ok": collect_ok, "_rf_auth_observations": obs})
    label = f"redfish/collect_ok={collect_ok}/obs={obs}"
    assert diag["failure_stage"] == exp_stage, label
    assert diag["failure_code"] == exp_code, label
    assert diag["auth_success"] is exp_auth, label
    _assert_stage_code(diag, label)
    # 4번 문장(자격증명)은 stage=auth 와만, 5번 문장은 stage=gather 와만 짝지어진다
    from tests.e2e.test_failure_reason_contract import FAILURE_REASONS  # noqa: PLC0415
    expected_reason = ("_fr_gather_failed" if exp_stage == "gather"
                       else "_fr_credential_failed")
    assert diag["failure_reason"] == FAILURE_REASONS[expected_reason], label


def test_case10_redfish_never_blames_credentials_after_auth_passed():
    """인증 통과가 관측된 뒤의 수집 실패를 자격증명 문제로 표시하지 않는다 (P0-1)."""
    from tests.e2e.test_failure_reason_contract import FAILURE_REASONS  # noqa: PLC0415
    for ctx in ({"_rf_collect_ok": True},
                {"_rf_collect_ok": False,
                 "_rf_auth_observations": [{"role": "primary", "status": 200}]}):
        diag = render_redfish_rescue({"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None},
                                      **ctx})
        assert diag["failure_reason"] != FAILURE_REASONS["_fr_credential_failed"], ctx
        assert diag["auth_success"] is True, ctx


@pytest.mark.parametrize("os_type", ["linux", "windows"])
def test_case11_12_os_gather_exception(os_type):
    ctx: dict[str, Any] = {"_os_auth_ok": True, "_os_attempts_meta": {}}
    if os_type == "windows":
        ctx["ansible_port"] = "5986"
    diag = _render_diagnosis("os-gather/site.yml", _OS_TASKS[os_type], ctx)
    assert diag["failure_stage"] == "gather", os_type
    assert diag["failure_code"] == "GATHER_FAILED", os_type
    assert diag["auth_success"] is True, "자격 probe 통과는 관측된 사실"
    _assert_stage_code(diag, f"os/{os_type} gather")


# ═══════════════════════════════════════════════════════════════════════════
# Case 13 — Partial (기존 status 정책 유지)
# ═══════════════════════════════════════════════════════════════════════════
def test_case13_partial_does_not_force_stage_or_code():
    env = json.loads((REPO / "schema/examples/os_partial.json").read_text(encoding="utf-8"))
    assert env["status"] == "partial"
    diag = env["diagnosis"]
    assert "failure_code" in diag, "partial 에도 키는 존재 (shape 고정)"
    assert diag["failure_stage"] is None, "partial 이라는 이유로 대표 stage 를 만들지 않는다"
    assert diag["failure_code"] is None, "partial 이라는 이유로 대표 code 를 만들지 않는다"


# ═══════════════════════════════════════════════════════════════════════════
# Case 14 — OS 포트 전멸(문서화된 예외) / Fallback
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("channel", ["os", "redfish", "esxi"])
def test_all_ports_timeout_is_target_unreachable(channel, monkeypatch):
    """전 포트 무응답 + ICMP 무응답은 채널 무관 reachable + TARGET_UNREACHABLE."""
    result = _run_precheck(monkeypatch, channel, connect_exc=socket.timeout())
    assert result["failure_stage"] == "reachable", channel
    assert result["failure_code"] == "TARGET_UNREACHABLE", channel
    assert result["auth_success"] is None, channel
    _assert_stage_code(result, f"{channel} 전 포트 timeout")


@pytest.mark.parametrize("channel", ["os", "redfish", "esxi"])
def test_all_ports_timeout_with_icmp_reply_is_port_stage(channel, monkeypatch):
    """ICMP OR 판정은 3 채널 공통이다 (OS 후보 탐색 경로 포함)."""
    result = _run_precheck(monkeypatch, channel, connect_exc=socket.timeout(),
                           icmp=ICMP_REPLY)
    assert result["reachable"] is True, channel
    assert result["port_open"] is False, channel
    assert result["failure_stage"] == "port", channel
    assert result["failure_code"] == "TCP_CONNECT_FAILED", channel
    _assert_stage_code(result, f"{channel} 전 포트 timeout + ICMP 응답")


def test_os_refused_now_observable(monkeypatch):
    """Phase 3-A: OS 도 RST 를 실제로 관측한다 (Phase 2 의 매핑 예외 해소)."""
    result = _run_precheck(monkeypatch, "os", connect_exc=ConnectionRefusedError())
    assert result["reachable"] is True, "RST 는 호스트가 살아 있다는 증거"
    assert result["failure_stage"] == "port"
    assert result["failure_code"] == "TCP_CONNECTION_REFUSED"
    assert result["auth_success"] is None
    _assert_stage_code(result, "OS refused")


@pytest.mark.parametrize("site", list(_FALLBACK_CTX))
def test_case14_fallback_stage_code(site):
    for idx, env in enumerate(_render_fallback_envelopes(site, _FALLBACK_CTX[site])):
        diag = env["diagnosis"]
        label = f"fallback/{site}#{idx}"
        assert diag["failure_stage"] == "fallback", label
        assert diag["failure_code"] == "OUTPUT_BUILD_FAILED", label
        _assert_stage_code(diag, label)


# ═══════════════════════════════════════════════════════════════════════════
# 불변식 3·4·5·6 — status=failed 결과 전수
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,envelope", _failed_envelopes(),
                         ids=lambda v: v if isinstance(v, str) else "")
def test_failed_envelope_carries_stage_and_code(label, envelope):
    if envelope.get("status") != "failed":
        pytest.skip("failed 상태가 아님")
    diag = envelope.get("diagnosis")
    assert isinstance(diag, dict), f"[{label}] diagnosis 가 dict 가 아님"
    assert diag.get("failure_stage"), f"[{label}] status=failed 인데 failure_stage 가 비어 있다"
    assert diag.get("failure_code"), f"[{label}] status=failed 인데 failure_code 가 비어 있다"
    _assert_stage_code(diag, label)


# ═══════════════════════════════════════════════════════════════════════════
# 불변식 9·10 — schema 자산 정합
# ═══════════════════════════════════════════════════════════════════════════
def test_schema_examples_follow_stage_code_policy():
    for path in sorted((REPO / "schema/examples").glob("*.json")):
        env = json.loads(path.read_text(encoding="utf-8"))
        diag = env.get("diagnosis") or {}
        assert "failure_code" in diag, f"{path.name}: failure_code 키 없음"
        if env.get("status") in ("success", "partial"):
            assert diag["failure_stage"] is None, f"{path.name}: {env['status']} 인데 stage 존재"
            assert diag["failure_code"] is None, f"{path.name}: {env['status']} 인데 code 존재"
        else:
            _assert_stage_code(diag, path.name)
            assert diag.get("failure_reason"), f"{path.name}: failed 인데 reason 없음"


def test_baselines_carry_null_failure_code():
    files = sorted((REPO / "schema/baseline_v1").glob("*.json"))
    assert files, "baseline 이 없다"
    for path in files:
        env = json.loads(path.read_text(encoding="utf-8"))
        diag = env.get("diagnosis") or {}
        assert "failure_code" in diag, f"{path.name}: failure_code 키 없음"
        assert diag["failure_stage"] is None, f"{path.name}: success baseline 인데 stage 존재"
        assert diag["failure_code"] is None, f"{path.name}: success baseline 인데 code 존재"


def test_field_dictionary_matches_contract():
    """불변식 5 — 허용 집합의 정본은 field_dictionary 다. 코드와 어긋나면 실패."""
    fd = yaml.safe_load((REPO / "schema/field_dictionary.yml").read_text(encoding="utf-8"))
    fields = fd.get("fields", fd)
    assert set(fields["diagnosis.failure_code"]["enum"]) == set(ALLOWED_CODES)
    assert set(fields["diagnosis.failure_stage"]["enum"]) == set(ALLOWED_STAGES)


# ═══════════════════════════════════════════════════════════════════════════
# 불변식 11 — errors[].detail 민감정보 미노출
# ═══════════════════════════════════════════════════════════════════════════
def test_auth_detail_carries_no_credentials(monkeypatch):
    result = pb._init_result("redfish", [443])
    monkeypatch.setattr(
        pb, "http_get",
        lambda *_a, **_k: (False, "HTTP 401", {"status_code": 401, "json": None}),
    )
    pb._try_redfish_auth("192.0.2.10", 443, "svc_admin", "zzz-canary-password-zzz", 8.0, False, result)
    blob = " ".join(str(result.get(k)) for k in ("detail", "failure_reason", "failure_code"))
    # 알려진 실 자격증명이 섞였는지 digest 로 대조한다 (평문을 저장하지 않는 가드).
    assert_no_secret(blob, "auth detail")
    for secret in (CANARY_PASSWORD, "svc_admin", "Basic ", "password="):
        assert secret not in blob, f"민감정보 노출: {secret!r}"


# ═══════════════════════════════════════════════════════════════════════════
# 불변식 12 — Phase 1 사용자 문구 Contract 유지
# ═══════════════════════════════════════════════════════════════════════════
def test_phase1_reason_contract_still_holds():
    """failure_code 도입이 Portal 표시용 failure_reason 을 훼손하지 않았는지."""
    from tests.e2e.test_failure_reason_contract import _assert_grid_ready  # noqa: PLC0415

    samples = [
        ("redfish/gather", render_redfish_rescue(
            {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None},
             "_rf_collect_ok": False, "_rf_auth_rejected": False})),
        ("redfish/auth-rejected", render_redfish_rescue(
            {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None},
             "_rf_collect_ok": False, "_rf_auth_rejected": True})),
        ("esxi/auth", _render_diagnosis(
            "esxi-gather/site.yml", _ESXI_TASK,
            {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None,
                            "details": {"channel": "esxi"}},
             "_e_auth_ok": False, "_e_facts_ok": False})),
        ("linux/gather", _render_diagnosis(
            "os-gather/site.yml", _OS_TASKS["linux"],
            {"_os_auth_ok": True, "_os_attempts_meta": {}})),
        # 2026-08-11 (Phase 5-A): OS 포트 실패 문구는 site.yml 이 아니라 precheck 가 만든다.
        # (Phase 6-B) 세 관측이 같은 1번 문구를 쓴다 — 구분은 failure_code 가 유지한다.
        ("os/unreachable", {"failure_reason": pb.reason_for_failure_code("TARGET_UNREACHABLE")}),
        ("os/connect-failure", {"failure_reason": pb.reason_for_failure_code("TCP_CONNECT_FAILED")}),
        ("os/port-refused", {"failure_reason": pb.reason_for_failure_code("TCP_CONNECTION_REFUSED")}),
        ("os/protocol", {"failure_reason": pb.CHANNEL_PROTOCOL_MESSAGES["os"]}),
    ]
    for label, diag in samples:
        _assert_grid_ready(diag["failure_reason"], label)
