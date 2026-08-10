"""Phase 3-B: OS 후보 탐색 — TCP + 기대 프로토콜 확인까지 되어야 선택.

배경
----
Phase 3-A 까지 OS 는 "포트가 열렸는가" 만으로 OS Type 을 확정했다. 5986/5985/22 에 다른
서비스가 떠 있으면 Windows / Linux 를 오판한다. Phase 3-B 는 각 후보에서 실제
SSH identification / WinRM WS-Management 응답까지 확인하고, 프로토콜이 아니면
**다음 후보로 계속 진행**한다.

핵심 불변식
  - 포트 우선순위 5986 → 5985 → 22 유지
  - 포트가 열려도 프로토콜 불일치면 탐색을 멈추지 않는다
  - 뒤 후보가 성공하면 앞 후보 실패와 무관하게 **전체 성공**
  - 열린 포트가 있었으나 프로토콜을 하나도 못 찾으면 stage=protocol / PROTOCOL_CHECK_FAILED
  - Protocol Probe 만으로 auth_success 를 true 로 만들지 않는다
  - Phase 3-A 의 포트 폴링 동작을 깨지 않는다
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

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


class _ExitJson(Exception):
    def __init__(self, result):
        super().__init__("exit")
        self.result = result


def run_os(monkeypatch, tcp, proto, *, timeout_port=2.0, timeout_proto=5.0,
           poll_interval=1.0):
    """tcp: {port: 'ok'|'timeout'|'refused'|'dns'} / proto: {port: True|False}"""
    tcp_calls: list[int] = []
    proto_calls: list[tuple[int, float]] = []

    def fake_tcp(host, port, budget, poll, connect_timeout=5.0):
        tcp_calls.append(port)
        kind = tcp.get(port, "timeout")
        if kind == "ok":
            return True, None, None
        if kind == "dns":
            return False, "DNS 해석 실패", pb.TCP_FAIL_DNS
        if kind == "refused":
            return False, "연결 거부됨 (port={0})".format(port), pb.TCP_FAIL_REFUSED
        return False, "연결 시간 초과", pb.TCP_FAIL_TIMEOUT

    def fake_proto(host, port, timeout):
        proto_calls.append((port, timeout))
        if proto.get(port):
            return True, None, {}
        return False, "WinRM 응답 아님 (HTTP 200, server=nginx)", None

    monkeypatch.setattr(pb, "tcp_check_budget", fake_tcp)
    monkeypatch.setattr(pb, "probe_os", fake_proto)

    class _Fake:
        params = dict(host="192.0.2.30", channel="os", ports=[], timeout_port=timeout_port,
                      timeout_protocol=timeout_proto, timeout_auth=8.0,
                      username=None, password=None, verify_ssl=False,
                      probe_protocol=True, port_poll_interval=poll_interval)

        def exit_json(self, **kw):
            raise _ExitJson(kw)

    monkeypatch.setattr(pb, "AnsibleModule", lambda **_kw: _Fake())
    with pytest.raises(_ExitJson) as exc:
        pb.run_module()
    return exc.value.result, tcp_calls, proto_calls


# ═══════════════════════════════════════════════════════════════════════════
# Case 1~4 — 정상 판정
# ═══════════════════════════════════════════════════════════════════════════
def test_case01_winrm_https_ok(monkeypatch):
    result, tcp_calls, proto_calls = run_os(
        monkeypatch, {5986: "ok"}, {5986: True})
    assert result["detected_os"] == "windows"
    assert result["winrm_scheme"] == "https"
    assert result["selected_port"] == 5986
    assert result["protocol_supported"] is True
    assert result["checked_ports"] == [5986]
    assert tcp_calls == [5986] and [p for p, _t in proto_calls] == [5986]


def test_case02_5986_not_winrm_then_5985_ok(monkeypatch):
    """포트가 열려도 WinRM 이 아니면 다음 후보로 계속 진행한다."""
    result, tcp_calls, proto_calls = run_os(
        monkeypatch, {5986: "ok", 5985: "ok"}, {5986: False, 5985: True})
    assert result["detected_os"] == "windows"
    assert result["winrm_scheme"] == "http"
    assert result["selected_port"] == 5985
    assert result["protocol_supported"] is True
    assert result["checked_ports"] == [5986, 5985]
    assert [p for p, _t in proto_calls] == [5986, 5985], "5986 프로토콜 실패 후 5985 검사"


def test_case03_both_winrm_ports_not_winrm_then_ssh(monkeypatch):
    """§9 성공 우선 — 앞 후보 프로토콜 실패가 전체 실패로 이어지지 않는다."""
    result, _tcp, proto_calls = run_os(
        monkeypatch,
        {5986: "ok", 5985: "ok", 22: "ok"},
        {5986: False, 5985: False, 22: True})
    assert result["detected_os"] == "linux"
    assert result["selected_port"] == 22
    assert result["winrm_scheme"] is None
    assert result["protocol_supported"] is True
    assert result["failure_stage"] is None and result["failure_code"] is None
    assert result["checked_ports"] == [5986, 5985, 22]
    assert [p for p, _t in proto_calls] == [5986, 5985, 22]


def test_case13_earlier_timeout_later_success(monkeypatch):
    """5986 프로토콜 실패 + 5985 timeout + 22 SSH 성공 → Linux, 전체 성공."""
    result, _tcp, _proto = run_os(
        monkeypatch,
        {5986: "ok", 5985: "timeout", 22: "ok"},
        {5986: False, 22: True})
    assert result["detected_os"] == "linux"
    assert result["failure_stage"] is None
    assert result["checked_ports"] == [5986, 5985, 22]


# ═══════════════════════════════════════════════════════════════════════════
# Case 12 — 열린 포트는 있으나 프로토콜 전부 실패
# ═══════════════════════════════════════════════════════════════════════════
def test_case12_open_ports_but_no_protocol(monkeypatch):
    result, _tcp, _proto = run_os(
        monkeypatch,
        {5986: "ok", 5985: "ok", 22: "ok"},
        {5986: False, 5985: False, 22: False})
    assert result["reachable"] is True
    assert result["port_open"] is True, "TCP 는 실제로 열렸다"
    assert result["protocol_supported"] is False, "검사했고 확인하지 못했다"
    assert result["protocol_checked"] is True
    assert result["failure_stage"] == "protocol"
    assert result["failure_code"] == "PROTOCOL_CHECK_FAILED"
    assert result["detected_os"] is None, "프로토콜 미확인이면 OS 를 확정하지 않는다"
    assert result["checked_ports"] == [5986, 5985, 22]
    assert "관리 포트에는 연결되었지만" in result["failure_reason"]
    for port in (5986, 5985, 22):
        assert "port={0}".format(port) in result["detail"], "포트별 근거 보존"


def test_partial_open_and_protocol_fail(monkeypatch):
    """일부만 열리고 그 포트의 프로토콜이 실패해도 stage=protocol 이다."""
    result, _tcp, _proto = run_os(
        monkeypatch, {5986: "timeout", 5985: "ok", 22: "refused"}, {5985: False})
    assert result["failure_stage"] == "protocol"
    assert result["failure_code"] == "PROTOCOL_CHECK_FAILED"
    assert result["port_open"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Case 11 — TCP 단계 전멸 (Phase 3-A 매핑 유지)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("tcp,exp_stage,exp_code", [
    ({}, "reachable", "TCP_CONNECT_FAILED"),
    ({5986: "refused", 5985: "refused", 22: "refused"}, "port", "TCP_CONNECTION_REFUSED"),
    ({5986: "timeout", 5985: "refused", 22: "timeout"}, "port", "TCP_CONNECTION_REFUSED"),
    ({5986: "dns", 5985: "dns", 22: "dns"}, "reachable", "DNS_RESOLUTION_FAILED"),
])
def test_case11_all_tcp_failed_keeps_phase3a_mapping(monkeypatch, tcp, exp_stage, exp_code):
    result, _t, proto_calls = run_os(monkeypatch, tcp, {})
    assert result["failure_stage"] == exp_stage
    assert result["failure_code"] == exp_code
    assert result["port_open"] is False
    assert result["protocol_supported"] is False
    assert proto_calls == [], "TCP 가 안 열리면 프로토콜 probe 를 하지 않는다"
    assert result["checked_ports"] == [5986, 5985, 22]


# ═══════════════════════════════════════════════════════════════════════════
# Case 16 — auth_success 는 Protocol Probe 로 true 가 되지 않는다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("tcp,proto", [
    ({5986: "ok"}, {5986: True}),                     # 프로토콜 성공
    ({5986: "ok"}, {5986: False}),                    # 프로토콜 실패
    ({}, {}),                                          # TCP 전멸
])
def test_case16_auth_success_stays_null(monkeypatch, tcp, proto):
    result, _t, _p = run_os(monkeypatch, tcp, proto)
    assert result["auth_success"] is None, (
        "Protocol Probe 는 자격증명을 보내지 않는다. true 는 Credential Probe 몫"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Case 4 — Protocol Probe timeout 이 bounded 인가
# ═══════════════════════════════════════════════════════════════════════════
def test_protocol_probe_uses_bounded_timeout(monkeypatch):
    _result, _t, proto_calls = run_os(
        monkeypatch, {5986: "ok"}, {5986: True}, timeout_proto=5.0)
    assert proto_calls == [(5986, 5.0)], "포트 예산(2초)과 별개의 bounded timeout"


def test_port_polling_preserved(monkeypatch):
    """Phase 3-A 폴링 인자가 후보 탐색에서도 그대로 전달된다."""
    seen = []

    def fake_tcp(host, port, budget, poll, connect_timeout=5.0):
        seen.append((port, budget, poll))
        return False, "연결 시간 초과", pb.TCP_FAIL_TIMEOUT

    monkeypatch.setattr(pb, "tcp_check_budget", fake_tcp)
    monkeypatch.setattr(pb, "probe_os", lambda *_a: (False, "x", None))

    class _Fake:
        params = dict(host="192.0.2.30", channel="os", ports=[], timeout_port=2.0,
                      timeout_protocol=5.0, timeout_auth=8.0, username=None, password=None,
                      verify_ssl=False, probe_protocol=True, port_poll_interval=1.0)

        def exit_json(self, **kw):
            raise _ExitJson(kw)

    monkeypatch.setattr(pb, "AnsibleModule", lambda **_kw: _Fake())
    with pytest.raises(_ExitJson):
        pb.run_module()

    assert seen == [(5986, 2.0, 1.0), (5985, 2.0, 1.0), (22, 2.0, 1.0)], (
        "포트별 예산 2초 / poll 1초 / 순서 5986→5985→22 유지"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Case 14 — checked_ports 정확성 (중복 없음 / 실제 시도 순서)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("tcp,proto,expected", [
    ({5986: "ok"}, {5986: True}, [5986]),
    ({5986: "ok", 5985: "ok"}, {5986: False, 5985: True}, [5986, 5985]),
    ({5986: "ok", 5985: "ok", 22: "ok"}, {22: True}, [5986, 5985, 22]),
    ({}, {}, [5986, 5985, 22]),
    ({5986: "ok", 5985: "ok", 22: "ok"}, {}, [5986, 5985, 22]),
])
def test_case14_checked_ports(monkeypatch, tcp, proto, expected):
    result, _t, _p = run_os(monkeypatch, tcp, proto)
    assert result["checked_ports"] == expected
    assert len(result["checked_ports"]) == len(set(result["checked_ports"]))


# ═══════════════════════════════════════════════════════════════════════════
# Case 22 — 민감정보 비노출
# ═══════════════════════════════════════════════════════════════════════════
def test_case22_no_credentials_in_result(monkeypatch):
    result, _t, _p = run_os(
        monkeypatch, {5986: "ok", 5985: "refused", 22: "ok"}, {5986: False, 22: False})
    blob = " ".join(str(v) for v in result.values())
    for secret in ("password", "Passw0rd", "Goodmit0802!", "Authorization", "Basic "):
        assert secret not in blob, "민감정보 노출: {0}".format(secret)


# ═══════════════════════════════════════════════════════════════════════════
# Case 18 — 기존 채널 회귀 (후보 탐색이 redfish/esxi 로 새지 않는다)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("channel", ["redfish", "esxi"])
def test_other_channels_do_not_use_candidate_flow(monkeypatch, channel):
    calls = {"candidate": 0}
    monkeypatch.setattr(
        pb, "_search_os_candidates",
        lambda *_a, **_k: calls.__setitem__("candidate", calls["candidate"] + 1))
    monkeypatch.setattr(pb, "tcp_check_budget", lambda *_a, **_k: (True, None, None))
    monkeypatch.setattr(
        pb, "http_get",
        lambda *_a, **_k: (True, None, {"status_code": 200,
                                        "json": {"@odata.id": "/redfish/v1", "@odata.type": "#ServiceRoot.v1_15_0.ServiceRoot", "RedfishVersion": "1.6.0"},
                                        "headers": {}}))

    class _Fake:
        params = dict(host="192.0.2.10", channel=channel, ports=[], timeout_port=3.0,
                      timeout_protocol=15.0, timeout_auth=8.0, username=None, password=None,
                      verify_ssl=False, probe_protocol=True, port_poll_interval=0.0)

        def exit_json(self, **kw):
            raise _ExitJson(kw)

    monkeypatch.setattr(pb, "AnsibleModule", lambda **_kw: _Fake())
    with pytest.raises(_ExitJson) as exc:
        pb.run_module()

    assert calls["candidate"] == 0, "{0} 는 OS 후보 탐색을 타면 안 된다".format(channel)
    result = exc.value.result
    assert result["protocol_supported"] is True
    assert result["checked_ports"] == [443]
    assert result["failure_stage"] is None and result["failure_code"] is None


def test_os_with_probe_protocol_false_keeps_phase3a_flow(monkeypatch):
    """probe_protocol=false (Phase 3-A 경로) 는 그대로 남아 있다."""
    monkeypatch.setattr(pb, "tcp_check_budget", lambda *_a, **_k: (True, None, None))
    probed = {"n": 0}
    monkeypatch.setattr(
        pb, "probe_os",
        lambda *_a: (probed.__setitem__("n", probed["n"] + 1), (True, None, {}))[1])

    class _Fake:
        params = dict(host="192.0.2.30", channel="os", ports=[], timeout_port=2.0,
                      timeout_protocol=5.0, timeout_auth=8.0, username=None, password=None,
                      verify_ssl=False, probe_protocol=False, port_poll_interval=1.0)

        def exit_json(self, **kw):
            raise _ExitJson(kw)

    monkeypatch.setattr(pb, "AnsibleModule", lambda **_kw: _Fake())
    with pytest.raises(_ExitJson) as exc:
        pb.run_module()
    result = exc.value.result

    assert probed["n"] == 0, "probe_protocol=false 면 프로토콜을 확인하지 않는다"
    assert result["protocol_supported"] is False
    assert result["protocol_checked"] is False
    assert result["detected_os"] == "windows", "TCP 기준 판정 (Phase 3-A 동작)"
