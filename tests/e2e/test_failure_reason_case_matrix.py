"""Phase 5-A: Portal Grid 실패 사유 18 Case 최종 렌더 + 단계 진행 관계 Contract.

목적
----
1. 사용자가 Grid 문장만 읽고 "어디까지 됐고 어디서 막혔는지" 알 수 있는가.
2. 그 문장이 주장하는 앞 단계 성공이 **실제 관측값(Machine Diagnosis)** 과 일치하는가.
   문구와 Boolean 이 서로 다른 이야기를 하면 테스트 실패다 (§29).

렌더 방식은 합성 fixture 가 아니라 **production 코드 자체**다.
  - precheck 경로: `precheck_bundle.run_module()` 실제 실행 (socket 계층만 대체)
  - site.yml 경로: rescue 의 `_diagnosis` set_fact 템플릿을 추출해 Jinja2 로 렌더
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "common" / "library"))

_b = types.ModuleType("ansible.module_utils.basic")
_b.AnsibleModule = object
_m = types.ModuleType("ansible.module_utils")
_m.basic = _b
_a = types.ModuleType("ansible")
_a.module_utils = _m
sys.modules.setdefault("ansible", _a)
sys.modules.setdefault("ansible.module_utils", _m)
sys.modules.setdefault("ansible.module_utils.basic", _b)

import precheck_bundle as pb  # noqa: E402

from tests.e2e.test_failure_reason_contract import (  # noqa: E402
    _assert_claims_match_observation,
    _assert_diagnosis_shape,
    _assert_grid_ready,
    _render_diagnosis,
)

ESXI_SERVICE_CONTENT = (
    REPO / "tests/fixtures/esxi/lab/esxi_7_0_3_service_content.xml"
).read_bytes()

_RF_TASK = "redfish | rescue | Portal 표시용 failure_reason 보장"
_ESXI_TASK = "esxi | rescue | Portal 표시용 failure_reason 보장"
_OS_TASKS = {
    "linux": "linux | rescue | Portal 표시용 diagnosis 보장",
    "windows": "windows | rescue | Portal 표시용 diagnosis 보장",
}

# precheck 를 통과한 상태의 진단 (rescue 진입 시 base)
_PRECHECK_OK = {
    "reachable": True, "port_open": True, "protocol_supported": True,
    "auth_success": None, "failure_stage": None, "failure_code": None,
    "failure_reason": None, "details": {},
}


class _ExitJson(Exception):
    def __init__(self, result):
        super().__init__("exit")
        self.result = result


def _run_precheck(channel: str, *, tcp=None, http=None, soap=None,
                  probe_protocol=True) -> dict[str, Any]:
    """precheck_bundle 을 실제로 실행해 진단 dict 를 얻는다."""
    patches = []
    if tcp is not None:
        patches.append(patch.object(pb, "tcp_check_ex", lambda *_a, **_k: tcp))
        patches.append(patch.object(pb, "tcp_check_budget", lambda *_a, **_k: tcp))
    if http is not None:
        patches.append(patch.object(pb, "http_get", lambda *_a, **_k: http))
    if soap is not None:
        patches.append(patch.object(pb, "http_post_soap", lambda *_a, **_k: soap))
    if channel == "os" and http is None and soap is None:
        patches.append(patch.object(pb, "probe_os",
                                    lambda *_a, **_k: (False, "SSH 식별 응답 아님", None)))

    ports = {"os": [], "redfish": [], "esxi": []}[channel]

    class _Fake:
        params = dict(host="192.0.2.10", channel=channel, ports=ports,
                      timeout_port=2.0, timeout_protocol=5.0, timeout_auth=8.0,
                      username=None, password=None, verify_ssl=False,
                      probe_protocol=probe_protocol, port_poll_interval=0.0)

        def exit_json(self, **kw):
            raise _ExitJson(kw)

    patches.append(patch.object(pb, "AnsibleModule", lambda **_kw: _Fake()))
    for p in patches:
        p.start()
    try:
        with pytest.raises(_ExitJson) as exc:
            pb.run_module()
    finally:
        for p in reversed(patches):
            p.stop()

    sys.path.insert(0, str(REPO / "filter_plugins"))
    from diagnosis_mapper import build_diagnosis  # noqa: PLC0415
    return build_diagnosis(exc.value.result, channel)


# ═══════════════════════════════════════════════════════════════════════════
# Case 1~6 — precheck 단계 (실제 모듈 실행)
# ═══════════════════════════════════════════════════════════════════════════
_TCP_TIMEOUT = (False, "연결 시간 초과", pb.TCP_FAIL_TIMEOUT)
_TCP_DNS = (False, "DNS 해석 실패", pb.TCP_FAIL_DNS)
_TCP_REFUSED = (False, "연결 거부됨", pb.TCP_FAIL_REFUSED)
_TCP_OK = (True, None, None)


def _case(name):
    return name


CASES_PRECHECK = [
    ("C1 DNS 실패", "redfish", dict(tcp=_TCP_DNS), "reachable", "DNS_RESOLUTION_FAILED"),
    ("C2 TCP Timeout", "redfish", dict(tcp=_TCP_TIMEOUT), "reachable", "TCP_CONNECT_FAILED"),
    ("C3 Connection Refused", "redfish", dict(tcp=_TCP_REFUSED), "port", "TCP_CONNECTION_REFUSED"),
    ("C4 OS Protocol 실패", "os", dict(tcp=_TCP_OK), "protocol", "PROTOCOL_CHECK_FAILED"),
    ("C5 Redfish Protocol 실패", "redfish",
     dict(tcp=_TCP_OK, http=(True, None, {"status_code": 200, "json": {"a": 1}, "headers": {}})),
     "protocol", "PROTOCOL_CHECK_FAILED"),
    ("C6 ESXi Protocol 실패", "esxi",
     dict(tcp=_TCP_OK, soap=(True, None, {"status_code": 200, "body": b"<html>x</html>"})),
     "protocol", "PROTOCOL_CHECK_FAILED"),
]


@pytest.mark.parametrize("label,channel,kwargs,stage,code", CASES_PRECHECK,
                         ids=[c[0] for c in CASES_PRECHECK])
def test_precheck_cases(label, channel, kwargs, stage, code):
    diag = _run_precheck(channel, **kwargs)
    _assert_diagnosis_shape(diag, label)
    _assert_grid_ready(diag["failure_reason"], label)
    _assert_claims_match_observation(diag, label)
    assert diag["failure_stage"] == stage, label
    assert diag["failure_code"] == code, label
    # 인증을 시도하지 않는 경로 — false 는 거짓 정보다
    assert diag["auth_success"] is None, label


def test_reachable_stage_never_claims_communication_ok():
    """§3 — TCP 연결 실패를 '통신은 되지만' 으로 표현하지 않는다."""
    for tcp in (_TCP_DNS, _TCP_TIMEOUT):
        diag = _run_precheck("redfish", tcp=tcp)
        reason = diag["failure_reason"]
        assert diag["reachable"] is False
        for banned in ("통신은 되지만", "관리 연결은 확인되었지만", "서버는 응답하지만",
                       "접속은 확인되었지만"):
            assert banned not in reason, reason


def test_port_stage_never_claims_server_responded():
    """§5 — RST 를 최종 서버 응답으로 확정하지 않는다."""
    diag = _run_precheck("redfish", tcp=_TCP_REFUSED)
    assert diag["reachable"] is True and diag["port_open"] is False
    for banned in ("서버는 응답하지만", "관리 연결은 확인되었지만", "접속은 확인되었지만"):
        assert banned not in diag["failure_reason"]


def test_protocol_stage_reports_confirmed_connection():
    """§6 — protocol 단계는 TCP 관리 연결 성공을 사용자에게 알린다."""
    for channel, kwargs in (
        ("os", dict(tcp=_TCP_OK)),
        ("redfish", dict(tcp=_TCP_OK,
                         http=(True, None, {"status_code": 200, "json": {"a": 1}, "headers": {}}))),
        ("esxi", dict(tcp=_TCP_OK,
                      soap=(True, None, {"status_code": 200, "body": b"<html>x</html>"}))),
    ):
        diag = _run_precheck(channel, **kwargs)
        assert diag["port_open"] is True, channel
        assert "관리 연결은 확인되었지만" in diag["failure_reason"], channel
        # 단순 "응답이 없습니다" 로 뭉개지 않는다
        assert "확인하지 못했습니다" in diag["failure_reason"], channel


# ═══════════════════════════════════════════════════════════════════════════
# Case 7~18 — site.yml rescue 경로
# ═══════════════════════════════════════════════════════════════════════════
def _os_diag(os_type: str, auth_ok: bool) -> dict[str, Any]:
    ctx: dict[str, Any] = {"_os_auth_ok": auth_ok, "_os_attempts_meta": {"attempted_count": 2}}
    if os_type == "windows":
        ctx["ansible_port"] = "5986"
    return _render_diagnosis("os-gather/site.yml", _OS_TASKS[os_type], ctx)


def _esxi_diag(auth_ok: bool, facts_ok: bool) -> dict[str, Any]:
    return _render_diagnosis(
        "esxi-gather/site.yml", _ESXI_TASK,
        {"_diagnosis": {**_PRECHECK_OK, "details": {"channel": "esxi"}},
         "_e_auth_ok": auth_ok, "_e_facts_ok": facts_ok})


def _rf_diag(collect_ok: bool, rejected: bool) -> dict[str, Any]:
    return _render_diagnosis(
        "redfish-gather/site.yml", _RF_TASK,
        {"_diagnosis": dict(_PRECHECK_OK), "_rf_collect_ok": collect_ok,
         "_rf_auth_rejected": rejected})


CASES_RESCUE = [
    # label,                      diag,                          stage,   code,                auth_success
    ("C7 Linux 자격 전멸",        lambda: _os_diag("linux", False),   "auth",   "AUTH_PROBE_FAILED", None),
    ("C8 Windows 자격 전멸",      lambda: _os_diag("windows", False), "auth",   "AUTH_PROBE_FAILED", None),
    ("C9 ESXi 자격 전멸",         lambda: _esxi_diag(False, False),   "auth",   "AUTH_PROBE_FAILED", None),
    ("C10 Redfish 자격 실패",     lambda: _rf_diag(False, False),     "gather", "GATHER_FAILED",     None),
    ("C11 Redfish HTTP 401 실증", lambda: _rf_diag(False, True),      "auth",   "AUTH_PROBE_FAILED", False),
    ("C12 Redfish HTTP 403",      lambda: _rf_diag(False, False),     "gather", "GATHER_FAILED",     None),
    ("C13 Linux 수집 실패",       lambda: _os_diag("linux", True),    "gather", "GATHER_FAILED",     True),
    ("C14 Windows 수집 실패",     lambda: _os_diag("windows", True),  "gather", "GATHER_FAILED",     True),
    ("C15 ESXi 수집 실패",        lambda: _esxi_diag(True, False),    "gather", "GATHER_FAILED",     True),
    ("C16 Redfish 수집 실패",     lambda: _rf_diag(False, False),     "gather", "GATHER_FAILED",     None),
    ("C17 ESXi 결과 처리 실패",   lambda: _esxi_diag(True, True),     "gather", "GATHER_FAILED",     True),
    ("C18 Redfish 결과 처리 실패", lambda: _rf_diag(True, False),     "gather", "GATHER_FAILED",     None),
]


@pytest.mark.parametrize("label,make,stage,code,auth", CASES_RESCUE,
                         ids=[c[0] for c in CASES_RESCUE])
def test_rescue_cases(label, make, stage, code, auth):
    diag = make()
    _assert_diagnosis_shape(diag, label)
    _assert_grid_ready(diag["failure_reason"], label)
    _assert_claims_match_observation(diag, label)
    assert diag["failure_stage"] == stage, label
    assert diag["failure_code"] == code, label
    assert diag["auth_success"] is auth, label


def test_auth_stage_claims_only_protocol_level_success():
    """§7 — 자격 후보 전멸을 '인증에 실패했습니다' 로 단정하지 않는다."""
    for label, diag, service in (
        ("linux", _os_diag("linux", False), "SSH"),
        ("windows", _os_diag("windows", False), "WinRM"),
        ("esxi", _esxi_diag(False, False), "vSphere API"),
    ):
        reason = diag["failure_reason"]
        assert diag["auth_success"] is None, label
        assert f"{service}는 확인되었지만" in reason or f"{service} 서비스는 확인되었지만" in reason, reason
        assert "인증이 거부" not in reason, "거부를 관측하지 못했는데 단정하면 안 된다"
        assert "비밀번호가 잘못" not in reason
        assert "접속은 확인되었지만" not in reason, "인증 성공을 암시하면 안 된다"


def test_explicit_rejection_only_with_structured_401():
    """§8 — 명시적 거부 문구는 구조화된 401 관측이 있을 때만."""
    rejected = _rf_diag(False, True)
    unknown = _rf_diag(False, False)

    assert rejected["auth_success"] is False
    assert "인증이 거부되었습니다" in rejected["failure_reason"]
    assert unknown["auth_success"] is None
    assert "인증이 거부" not in unknown["failure_reason"], (
        "401 을 관측하지 못한 경로에서 거부를 단정하면 안 된다"
    )


def test_gather_stage_respects_auth_success():
    """§9 — auth_success=null 인 gather 실패는 '접속은 확인되었지만' 이라고 쓰지 않는다."""
    rf = _rf_diag(False, False)
    assert rf["auth_success"] is None
    assert "접속은 확인되었지만" not in rf["failure_reason"]
    assert "Redfish 서비스는 확인되었지만" in rf["failure_reason"], (
        "실제로 확인된 마지막 단계(Protocol)까지만 표현한다"
    )

    for diag in (_os_diag("linux", True), _os_diag("windows", True), _esxi_diag(True, False)):
        assert diag["auth_success"] is True
        assert "접속은 확인되었지만" in diag["failure_reason"]


def test_normalization_failure_wording():
    """§10 — 수집 성공이 확인된 경로에서만 '정보 수집 후' 라고 쓴다."""
    for diag in (_esxi_diag(True, True), _rf_diag(True, False)):
        assert "정보 수집 후 결과를 처리하는 중" in diag["failure_reason"]
    # 수집 성공을 확인하지 못한 경로에서는 쓰지 않는다
    for diag in (_rf_diag(False, False), _esxi_diag(False, False), _os_diag("linux", False)):
        assert "정보 수집 후" not in diag["failure_reason"]


def test_all_case_reasons_are_distinct_enough():
    """같은 의미는 같은 문체, 다른 단계는 다른 문장이어야 한다 (§13)."""
    reasons = {label: make()["failure_reason"] for label, make, *_ in CASES_RESCUE}
    # C10 / C12 / C16 은 Redfish 가 인증과 수집을 구분하지 못해 **의도적으로 동일**하다.
    assert reasons["C10 Redfish 자격 실패"] == reasons["C12 Redfish HTTP 403"]
    assert reasons["C10 Redfish 자격 실패"] == reasons["C16 Redfish 수집 실패"]
    # C17 / C18 은 결과 처리(정규화) 실패라 채널과 무관하게 **의도적으로 동일**하다.
    assert reasons["C17 ESXi 결과 처리 실패"] == reasons["C18 Redfish 결과 처리 실패"]
    # 나머지는 단계/채널마다 달라야 한다
    distinct = {reasons[k] for k in reasons if k not in
                ("C12 Redfish HTTP 403", "C16 Redfish 수집 실패")}
    assert len(distinct) == 9, sorted(distinct)


def test_no_secrets_in_any_case():
    for label, make, *_ in CASES_RESCUE:
        blob = str(make())
        for secret in ("password", "Passw0rd", "Goodmit0802!", "Authorization",
                       "Cookie", "Basic ", "token"):
            assert secret not in blob, f"[{label}] 민감정보 노출: {secret}"
