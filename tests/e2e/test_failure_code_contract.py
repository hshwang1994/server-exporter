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
import yaml

from tests.e2e.test_failure_reason_contract import (
    REPO,
    _ESXI_TASK,
    _FALLBACK_CTX,
    _OS_TASKS,
    _PRECHECK_OK_DIAG,
    _RF_TASK,
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
    "TCP_CONNECT_FAILED",
    "TCP_CONNECTION_REFUSED",
    "PROTOCOL_CHECK_FAILED",
    "AUTH_PROBE_FAILED",
    "GATHER_FAILED",
    "OUTPUT_BUILD_FAILED",
})

# code -> 허용 stage. 기본은 1:1 이며 **문서화된 예외 1건**만 추가로 허용한다.
#   OS 포트 감지 실패: wait_for 는 RST 를 관측하지 못해 REFUSED 를 쓸 수 없다. 관측한 사실은
#   "TCP 연결에 실패했다" 뿐이고, 실행이 멈춘 단계는 포트 감지 단계이므로 stage=port 다.
CODE_TO_STAGES: dict[str, frozenset[str]] = {
    "DNS_RESOLUTION_FAILED":  frozenset({"reachable"}),
    "TCP_CONNECT_FAILED":     frozenset({"reachable", "port"}),
    "TCP_CONNECTION_REFUSED": frozenset({"port"}),
    "PROTOCOL_CHECK_FAILED":  frozenset({"protocol"}),
    "AUTH_PROBE_FAILED":      frozenset({"auth"}),
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
def test_case03_tcp_connect_failed_not_unreachable(exc, label, monkeypatch):
    """timeout / no route 를 '장비 다운'으로 확정하지 않는다 (UNREACHABLE 금지)."""
    result = _run_precheck(monkeypatch, "redfish", connect_exc=exc)
    assert result["failure_stage"] == "reachable", label
    assert result["failure_code"] == "TCP_CONNECT_FAILED", label
    assert result["auth_success"] is None
    _assert_stage_code(result, f"C3 {label}")


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


@pytest.mark.parametrize("collect_ok", [False, True])
def test_case10_redfish_gather_keeps_auth_unknown(collect_ok):
    """Redfish 는 인증과 수집이 한 결과에 섞여 있어 auth 를 확정할 수 없다."""
    diag = _render_diagnosis(
        "redfish-gather/site.yml", _RF_TASK,
        {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None}, "_rf_collect_ok": collect_ok})
    label = f"redfish/collect_ok={collect_ok}"
    assert diag["failure_stage"] == "gather", label
    assert diag["failure_code"] == "GATHER_FAILED", label
    assert diag["auth_success"] is None, (
        "Gathering 실패만으로 auth_success=true 를 새로 만들지 않는다"
    )
    _assert_stage_code(diag, label)


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
def test_all_ports_timeout_is_connect_failed(channel, monkeypatch):
    """전 포트 무응답은 채널 무관 reachable + TCP_CONNECT_FAILED (UNREACHABLE 확정 금지)."""
    result = _run_precheck(monkeypatch, channel, connect_exc=socket.timeout())
    assert result["failure_stage"] == "reachable", channel
    assert result["failure_code"] == "TCP_CONNECT_FAILED", channel
    assert result["auth_success"] is None, channel
    _assert_stage_code(result, f"{channel} 전 포트 timeout")


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
    pb._try_redfish_auth("192.0.2.10", 443, "svc_admin", "Goodmit0802!", 8.0, False, result)
    blob = " ".join(str(result.get(k)) for k in ("detail", "failure_reason", "failure_code"))
    for secret in ("Goodmit0802!", "svc_admin", "Basic ", "password="):
        assert secret not in blob, f"민감정보 노출: {secret!r}"


# ═══════════════════════════════════════════════════════════════════════════
# 불변식 12 — Phase 1 사용자 문구 Contract 유지
# ═══════════════════════════════════════════════════════════════════════════
def test_phase1_reason_contract_still_holds():
    """failure_code 도입이 Portal 표시용 failure_reason 을 훼손하지 않았는지."""
    from tests.e2e.test_failure_reason_contract import _assert_grid_ready  # noqa: PLC0415

    samples = [
        ("redfish/gather", _render_diagnosis(
            "redfish-gather/site.yml", _RF_TASK,
            {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None}, "_rf_collect_ok": False})),
        ("esxi/auth", _render_diagnosis(
            "esxi-gather/site.yml", _ESXI_TASK,
            {"_diagnosis": {**_PRECHECK_OK_DIAG, "failure_code": None,
                            "details": {"channel": "esxi"}},
             "_e_auth_ok": False, "_e_facts_ok": False})),
        ("linux/gather", _render_diagnosis(
            "os-gather/site.yml", _OS_TASKS["linux"],
            {"_os_auth_ok": True, "_os_attempts_meta": {}})),
        ("os/port", _render_diagnosis(
            "os-gather/site.yml",
            "failed-output | Portal 표시용 failure_reason 을 OS 문맥으로",
            {"_diagnosis": {"failure_stage": "reachable", "failure_code": "TCP_CONNECT_FAILED",
                            "failure_reason": None, "details": {"channel": "os"}}})),
    ]
    for label, diag in samples:
        _assert_grid_ready(diag["failure_reason"], label)
