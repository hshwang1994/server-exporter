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

# 2026-08-12: 누출 가드가 검사 대상인 **진짜 비밀번호를 소스에 그대로** 적어 두고 있었다.
#   가드 파일 자체가 누출 지점이라, 평문 대신 sha256 앞 8자리로 대조하는 공용 가드로
#   바꾼다. 입력으로 넣던 실 자격증명도 합성 canary 로 바꾼다 (검사 의미는 동일).
from tests.secret_guard import (  # noqa: E402
    CANARY_PASSWORD, CANARY_RECOVERY, CANARY_TARGET, assert_no_secret,
)


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

from tests.precheck_stub import ICMP_REPLY, ICMP_SILENT  # noqa: E402

from tests.e2e.test_failure_reason_contract import (  # noqa: E402
    FR_CATALOG,
    fr,
    _assert_claims_match_observation,
    _assert_diagnosis_shape,
    _assert_grid_ready,
    _render_diagnosis,
    render_redfish_rescue,
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
                  probe_protocol=True, icmp=ICMP_SILENT) -> dict[str, Any]:
    """precheck_bundle 을 실제로 실행해 진단 dict 를 얻는다.

    2026-09-03: TCP 전멸 시 모듈이 ICMP 를 한 번 더 확인하므로 결과를 주입한다
    (실 ping 금지). 기본값 "응답 없음" 은 종전(TCP 전용) 판정과 결과가 같다.
    """
    patches = [patch.object(pb, "icmp_check", lambda *_a, **_k: icmp)]
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
                      probe_protocol=probe_protocol, port_poll_interval=0.0,
                      icmp_probe=True, timeout_icmp=1.0)

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
    ("C2 TCP Timeout", "redfish", dict(tcp=_TCP_TIMEOUT), "reachable", "TARGET_UNREACHABLE"),
    # 2026-09-03: TCP 는 무응답인데 ICMP 는 응답 → 도달 성립, 실패는 port 단계로 내려간다
    ("C2b TCP Timeout + ICMP 응답", "redfish",
     dict(tcp=_TCP_TIMEOUT, icmp=ICMP_REPLY), "port", "TCP_CONNECT_FAILED"),
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
        for banned in ("통신은 되지만", "관리 포트에는 연결됐지만", "서버는 응답하지만",
                       "접속은 확인"):
            assert banned not in reason, reason


def test_port_stage_never_claims_server_responded():
    """§5 — RST 를 최종 서버 응답으로 확정하지 않는다."""
    diag = _run_precheck("redfish", tcp=_TCP_REFUSED)
    assert diag["reachable"] is True and diag["port_open"] is False
    for banned in ("서버는 응답하지만", "관리 포트에는 연결됐지만", "접속은 확인"):
        assert banned not in diag["failure_reason"]


def test_protocol_stage_reports_confirmed_connection():
    """§6 — protocol 단계는 TCP 관리 연결 성공을 사용자에게 알린다.

    2026-09-21 기대 문구 변경: 채널별 문장이다 ("접속한 대상에서 Redfish 응답을 확인하지
    못했습니다. 대상 종류와 Redfish 서비스 설정을 확인하세요."). 대상 종류가 맞아도 이 code 가
    나오므로(서비스 중지 / 응답 지연 / TLS) "종류가 틀렸다" 고 단정하지 않는다.
    """
    for channel, kwargs in (
        ("os", dict(tcp=_TCP_OK)),
        ("redfish", dict(tcp=_TCP_OK,
                         http=(True, None, {"status_code": 200, "json": {"a": 1}, "headers": {}}))),
        ("esxi", dict(tcp=_TCP_OK,
                      soap=(True, None, {"status_code": 200, "body": b"<html>x</html>"}))),
    ):
        diag = _run_precheck(channel, **kwargs)
        assert diag["port_open"] is True, channel
        assert diag["failure_reason"] == fr("protocol_unconfirmed", channel), channel
        assert "접속한 대상에서" in diag["failure_reason"], channel
        # 단순 "응답이 없습니다" 로 뭉개지 않는다
        assert "확인하지 못했습니다" in diag["failure_reason"], channel
        assert "맞지 않습니다" not in diag["failure_reason"], "대상 종류 불일치를 단정하면 안 된다"


# ═══════════════════════════════════════════════════════════════════════════
# Case 7~18 — site.yml rescue 경로
# ═══════════════════════════════════════════════════════════════════════════
def _os_diag(os_type: str, auth_ok: bool, **extra: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {"_os_auth_ok": auth_ok, "_os_attempts_meta": {"attempted_count": 2}}
    if os_type == "windows":
        ctx["ansible_port"] = "5986"
    ctx.update(extra)
    return _render_diagnosis("os-gather/site.yml", _OS_TASKS[os_type], ctx)


def _esxi_diag(auth_ok: bool, facts_ok: bool, **extra: Any) -> dict[str, Any]:
    return _render_diagnosis(
        "esxi-gather/site.yml", _ESXI_TASK,
        {"_diagnosis": {**_PRECHECK_OK, "details": {"channel": "esxi"}},
         "_e_auth_ok": auth_ok, "_e_facts_ok": facts_ok, **extra})


def _rf_diag(collect_ok: bool, rejected: bool, *, statuses=None, **extra: Any) -> dict[str, Any]:
    """redfish rescue 렌더.

    2026-08-12: 자격 요청을 **보냈는지** 가 stage 를 가른다 (CLAUDE.md §9 — failure_stage 는
    워크플로가 멈춘 위치). statuses 를 주면 그 후보들에 대해 자격 요청을 보낸 상태가 된다.
    아무것도 주지 않으면 '자격 요청 전에 멈췄다'(adapter 선택 / vault 로드 예외 등)로 본다.
    """
    obs = [{"role": "primary", "label": f"c{i}", "status": st}
           for i, st in enumerate(statuses or [])]
    return render_redfish_rescue(
        {"_diagnosis": dict(_PRECHECK_OK), "_rf_collect_ok": collect_ok,
         "_rf_auth_rejected": rejected, "_rf_auth_observations": obs, **extra})


CASES_RESCUE = [
    # label,                      diag,                          stage,   code,                auth_success
    ("C7 Linux 자격 전멸",        lambda: _os_diag("linux", False),   "auth",   "AUTH_PROBE_FAILED", None),
    ("C8 Windows 자격 전멸",      lambda: _os_diag("windows", False), "auth",   "AUTH_PROBE_FAILED", None),
    ("C9 ESXi 자격 전멸",         lambda: _esxi_diag(False, False),   "auth",   "AUTH_PROBE_FAILED", None),
    ("C10 Redfish 자격 실패",     lambda: _rf_diag(False, False, statuses=[None]), "auth", "AUTH_PROBE_FAILED", None),
    ("C11 Redfish HTTP 401 실증", lambda: _rf_diag(False, True, statuses=[401]), "auth", "AUTH_PROBE_FAILED", False),
    ("C12 Redfish HTTP 403",      lambda: _rf_diag(False, False, statuses=[403]), "auth", "AUTH_PROBE_FAILED", None),
    ("C13 Linux 수집 실패",       lambda: _os_diag("linux", True),    "gather", "GATHER_FAILED",     True),
    ("C14 Windows 수집 실패",     lambda: _os_diag("windows", True),  "gather", "GATHER_FAILED",     True),
    ("C15 ESXi 수집 실패",        lambda: _esxi_diag(True, False),    "gather", "GATHER_FAILED",     True),
    ("C16 Redfish 수집 실패",     lambda: _rf_diag(False, False, statuses=[500]), "auth", "AUTH_PROBE_FAILED", None),
    ("C17 ESXi 결과 처리 실패",   lambda: _esxi_diag(True, True),     "gather", "GATHER_FAILED",     True),
    ("C18 Redfish 결과 처리 실패", lambda: _rf_diag(True, False),     "gather", "GATHER_FAILED",     True),
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
    """§7 — 자격 후보 전멸을 '거부됐다' 로 단정하지 않는다.

    OS / ESXi 는 잘못된 자격 / 연결 끊김 / timeout / 제한 쉘을 구분하지 못한다. 그래서
    "Vault 계정으로 로그인하지 못했습니다" 라는 관측만 말한다 (2026-09-21 채널별 문장).
    """
    for label, diag, channel in (
        ("linux", _os_diag("linux", False), "os"),
        ("windows", _os_diag("windows", False), "os"),
        ("esxi", _esxi_diag(False, False), "esxi"),
    ):
        reason = diag["failure_reason"]
        assert diag["auth_success"] is None, label
        assert reason == fr("auth_unconfirmed", channel), label
        assert "거부" not in reason, "거부를 관측하지 못했는데 단정하면 안 된다"
        assert "다르거나" not in reason, "계정 불일치는 확인된 경우에만 말한다"
        assert "로그인했지만" not in reason, "인증 성공을 암시하면 안 된다"


def test_explicit_rejection_has_its_own_sentence():
    """2026-09-21 사용자 확정 — 401 실증은 '계정이 다르거나 권한이 없다' 문장을 쓴다.

    종전(2026-08-11)에는 401 이든 timeout 이든 같은 문장이었다. 관리자에게는 "비밀번호를
    맞추면 된다" 와 "원인을 더 봐야 한다" 가 다른 일이다. 확인된 경우에만 쓰므로 표준 후보
    **전원**의 401 이 필요하다 (한 후보의 401 로 전체를 단정하지 않는다).
    """
    rejected = _rf_diag(False, True, statuses=[401])
    unknown = _rf_diag(False, False, statuses=[None])

    assert rejected["auth_success"] is False
    assert rejected["failure_stage"] == "auth"
    assert rejected["failure_code"] == "AUTH_PROBE_FAILED"
    assert unknown["auth_success"] is None
    assert unknown["failure_stage"] == "auth"

    assert rejected["failure_reason"] == fr("auth_rejected", "redfish")
    assert unknown["failure_reason"] == fr("auth_unconfirmed", "redfish")
    assert "다르거나" not in unknown["failure_reason"]


def test_gather_stage_respects_auth_success():
    """§9 — 접속 성공을 관측하지 못한 실패는 '로그인했지만' 이라고 쓰지 않는다."""
    rf = _rf_diag(False, False, statuses=[None])
    assert rf["auth_success"] is None
    assert "성공했지만" not in rf["failure_reason"]
    assert rf["failure_reason"] == fr("auth_unconfirmed", "redfish")

    for diag, channel in ((_os_diag("linux", True), "os"), (_os_diag("windows", True), "os"),
                          (_esxi_diag(True, False), "esxi")):
        assert diag["auth_success"] is True
        assert diag["failure_reason"] == fr("gather_after_auth", channel)
        assert "로그인했지만" in diag["failure_reason"]


def test_normalization_failure_wording():
    """수집 뒤 처리 실패도 '로그인했지만 정보를 가져오지 못했다' 다 — 관리자 조치가 같다."""
    assert _esxi_diag(True, True)["failure_reason"] == fr("gather_after_auth", "esxi")
    assert _rf_diag(True, False)["failure_reason"] == fr("gather_after_auth", "redfish")
    for diag in (_esxi_diag(True, True), _rf_diag(True, False)):
        assert diag["failure_stage"] == "gather"

    # 2026-08-12: 자격 요청을 **보내기 전에** 멈춘 실패는 auth 가 아니다.
    #   2026-09-21: 그 경우는 수집기 내부 오류 문장이다 (대상 계정 문제로 보내지 않는다).
    pre_auth = _rf_diag(False, False)
    assert pre_auth["failure_stage"] == "gather"
    assert pre_auth["failure_code"] == "GATHER_FAILED"
    assert pre_auth["auth_success"] is None
    assert pre_auth["failure_reason"] == fr("gather_internal")


def test_all_rescue_reasons_come_from_the_catalog():
    """rescue 경로 문장은 전부 카탈로그의 (키, 채널) 문장이다 — 리터럴 금지."""
    allowed = {fr(k, c, "미지정") for k, e in FR_CATALOG.items() for c in e}
    for label, make, *_ in CASES_RESCUE:
        reason = make()["failure_reason"]
        assert reason in allowed, f"[{label}] 카탈로그 밖 문장: {reason!r}"


# ═══════════════════════════════════════════════════════════════════════════
# 2026-09-21 — Vault 설정 원인 구분 (OS / ESXi) + loc 표시
# ═══════════════════════════════════════════════════════════════════════════
def _vault_cases():
    # (label, ctx, 기대 code, 기대 키)
    return [
        ("위치 미등록", {"_cred_reason": "unknown_location", "_cred_load_outcome": "not_resolved"},
         "CREDENTIAL_SET_UNAVAILABLE", "loc_unregistered"),
        ("위치 Vault 없음", {"_cred_reason": "resolved",
                            "_cred_load_outcome": "credential_set_missing",
                            "_cred_location_vault_exists": False},
         "CREDENTIAL_SET_UNAVAILABLE", "loc_vault_missing"),
        ("종류 파일 없음", {"_cred_reason": "resolved",
                           "_cred_load_outcome": "credential_set_missing",
                           "_cred_location_vault_exists": True},
         "CREDENTIAL_SET_UNAVAILABLE", "loc_vault_no_account"),
        ("복호화 실패", {"_cred_reason": "resolved",
                        "_cred_load_outcome": "credential_set_undecryptable"},
         "CREDENTIAL_SET_UNAVAILABLE", "loc_vault_unreadable"),
        # 계정 0개 — 계정 없이 접속을 **시도한 뒤** 실패했으므로 code 는 AUTH_PROBE_FAILED 유지
        ("계정 0개", {"_cred_reason": "resolved", "_cred_load_outcome": "empty_accounts"},
         "AUTH_PROBE_FAILED", "loc_vault_no_account"),
    ]


@pytest.mark.parametrize("target", ["linux", "windows", "esxi"])
@pytest.mark.parametrize("label,ctx,code,key", _vault_cases(), ids=lambda v: v if isinstance(v, str) else "")
def test_os_esxi_vault_causes_are_distinguished(target, label, ctx, code, key):
    ctx = {**ctx, "_cred_location": "ic"}
    if target == "esxi":
        diag = _esxi_diag(False, False, **ctx)
        channel = "esxi"
    else:
        diag = _os_diag(target, False, **ctx)
        channel = "os"
    tag = f"{target}/{label}"
    _assert_grid_ready(diag["failure_reason"], tag)
    _assert_claims_match_observation(diag, tag)
    assert diag["failure_stage"] == "auth", tag
    assert diag["failure_code"] == code, tag
    assert diag["auth_success"] is None, tag
    assert diag["failure_reason"] == fr(key, channel, "ic"), tag
    assert "해당 위치(ic)" in diag["failure_reason"], tag


def test_loc_falls_back_to_se_location_and_then_placeholder():
    """_cred_location 이 없으면(자격 해석 전 예외) se_location, 그것도 없으면 '미지정'."""
    from_extra = _os_diag("linux", False, se_location="seoul-dc1")
    assert "해당 위치(seoul-dc1)" in from_extra["failure_reason"]
    nothing = _os_diag("linux", False)
    assert "해당 위치(미지정)" in nothing["failure_reason"]


# ═══════════════════════════════════════════════════════════════════════════
# 2026-09-21 — Redfish 자격 단계 판정 수정 (시도 0회가 GATHER_FAILED 로 새던 3경우)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,ctx,key", [
    # 실행 위치 미등록: 표준 vault 는 전역이라 loaded 인데 중단 게이트는 _cred_reason 으로 멈춘다
    ("위치 미등록", {"_cred_reason": "unknown_location", "_cred_standard_outcome": "loaded",
                    "_cred_load_outcome": "loaded"}, "loc_unregistered"),
    # 표준 계정 0개 + vendor 식별 → 빈 자격 시도 없음
    ("표준 계정 0개", {"_cred_reason": "resolved", "_cred_standard_outcome": "empty_accounts",
                      "_cred_load_outcome": "empty_accounts"}, "project_vault_no_account"),
    # vendor 미상 + 표준 vault 부재 → 중단 게이트가 수집 전에 멈춘다
    ("vendor 미상 + 표준 없음", {"_cred_reason": "vendor_unresolved",
                               "_cred_standard_outcome": "credential_set_missing",
                               "_cred_load_outcome": "credential_set_missing"},
     "project_vault_missing"),
    ("표준 복호화 실패", {"_cred_reason": "resolved",
                        "_cred_standard_outcome": "credential_set_undecryptable",
                        "_cred_load_outcome": "credential_set_undecryptable"},
     "project_vault_unreadable"),
])
def test_redfish_credential_unavailable_is_not_gather(label, ctx, key):
    diag = _rf_diag(False, False, _cred_location="ic", **ctx)
    assert diag["failure_stage"] == "auth", label
    assert diag["failure_code"] == "CREDENTIAL_SET_UNAVAILABLE", label
    assert diag["auth_success"] is None, label
    assert diag["failure_reason"] == fr(key, "redfish", "ic"), label


def test_redfish_standard_vault_is_not_called_location_vault():
    """Redfish 표준 계정은 위치와 무관한 전역 vault 다 — '해당 위치의 Vault' 라고 쓰지 않는다."""
    for ctx in ({"_cred_reason": "resolved", "_cred_standard_outcome": "credential_set_missing"},
                {"_cred_reason": "resolved", "_cred_standard_outcome": "credential_set_undecryptable"},
                {"_cred_reason": "resolved", "_cred_standard_outcome": "empty_accounts"}):
        reason = _rf_diag(False, False, _cred_location="ic", **ctx)["failure_reason"]
        assert "해당 위치" not in reason, reason
        assert "개더링 프로젝트" in reason, reason
    for statuses, rejected in (([None], False), ([401], True)):
        reason = _rf_diag(False, rejected, statuses=statuses, _cred_location="ic")["failure_reason"]
        assert "해당 위치" not in reason and "표준 계정" in reason, reason


def test_redfish_anonymous_attempt_with_no_standard_account():
    """vendor 미상이라 빈 자격으로 한 번 시도했는데 실패 — 표준 계정 부재를 알린다 (code 는 AUTH)."""
    diag = _rf_diag(False, False, _cred_reason="vendor_unresolved",
                    _cred_standard_outcome="empty_accounts",
                    _rf_failed_attempt_notes=["empty-credential attempt failed"])
    assert diag["failure_code"] == "AUTH_PROBE_FAILED"
    assert diag["failure_reason"] == fr("project_vault_no_account", "redfish")


def test_no_secrets_in_any_case():
    for label, make, *_ in CASES_RESCUE:
        blob = str(make())
        assert_no_secret(blob, f"[{label}] envelope")
        for secret in ("password", "Passw0rd", CANARY_PASSWORD, "Authorization",
                       "Cookie", "Basic ", "token"):
            assert secret not in blob, f"[{label}] 민감정보 노출: {secret}"
