"""Phase 3-A: OS 관리 포트 사전 점검이 공통 Precheck 로 통합된 뒤의 동작 고정.

배경
----
종전 os-gather 는 PLAY 1 에서 `wait_for` 3연타(5986 → 5985 → 22)로 자체 포트 감지를 했다.
다른 두 채널(redfish/esxi)이 쓰는 `common/tasks/precheck/run_precheck.yml` 과 구조가 달라
진단 값도 별도 하드코딩이었고, 실패 종류(거부 / 시간 초과 / 주소 해석 실패)를 구분하지 못했다.

Phase 3-A 는 **구조만** 공통화한다. 다음은 그대로 유지해야 한다:
  - 포트 우선순위 5986 → 5985 → 22 와 첫 성공 시 중단
  - OS Type 판정 규칙 (22=linux / 5985·5986=windows, scheme https/http)
  - 포트당 타임아웃 2초, 재시도 없음
  - 프로토콜 미검증 (SSH banner / WinRM WSMan probe 는 다음 Phase)

네트워크 0 — socket 계층을 monkeypatch 한다.
"""
from __future__ import annotations

import socket
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


# ---------------------------------------------------------------------------
# 포트별 결과를 지정해 run_module 을 1회 돌리는 하네스
# ---------------------------------------------------------------------------
class _ExitJson(Exception):
    def __init__(self, result):
        super().__init__("exit")
        self.result = result


def run_os_precheck(monkeypatch, port_results, *, timeout_port=2.0, ports=None,
                    poll_interval=0.0):
    """port_results: {port: 'ok'|'timeout'|'refused'|'dns'|'other'}"""
    seen: list[tuple[int, float]] = []

    def fake_tcp(host, port, timeout):
        seen.append((port, timeout))
        kind = port_results.get(port, "timeout")
        if kind == "ok":
            return True, None, None
        if kind == "dns":
            return False, "DNS 해석 실패: Name or service not known", pb.TCP_FAIL_DNS
        if kind == "refused":
            return False, "연결 거부됨 (port={0})".format(port), pb.TCP_FAIL_REFUSED
        if kind == "other":
            return False, "EHOSTUNREACH", pb.TCP_FAIL_OTHER
        return False, "연결 시간 초과 (timeout={0}s)".format(timeout), pb.TCP_FAIL_TIMEOUT

    monkeypatch.setattr(pb, "tcp_check_ex", fake_tcp)

    class _Fake:
        params = dict(host="192.0.2.30", channel="os", ports=ports or [],
                      timeout_port=timeout_port, timeout_protocol=15.0, timeout_auth=8.0,
                      username=None, password=None, verify_ssl=False,
                      probe_protocol=False,   # OS 는 프로토콜 검증을 하지 않는다
                      port_poll_interval=poll_interval)

        def exit_json(self, **kw):
            raise _ExitJson(kw)

    monkeypatch.setattr(pb, "AnsibleModule", lambda **_kw: _Fake())
    with pytest.raises(_ExitJson) as exc:
        pb.run_module()
    return exc.value.result, seen


# ═══════════════════════════════════════════════════════════════════════════
# Case 1~3 — 포트 우선순위와 OS Type 판정
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("open_port,exp_os,exp_scheme,exp_probed", [
    (5986, "windows", "https", [5986]),
    (5985, "windows", "http",  [5986, 5985]),
    (22,   "linux",   None,    [5986, 5985, 22]),
])
def test_case01_03_port_priority_and_os_type(monkeypatch, open_port, exp_os, exp_scheme, exp_probed):
    result, seen = run_os_precheck(monkeypatch, {open_port: "ok"})

    assert [p for p, _t in seen] == exp_probed, "포트 순서 5986 → 5985 → 22, 첫 성공에서 중단"
    assert result["reachable"] is True and result["port_open"] is True
    assert result["selected_port"] == open_port
    assert result["detected_os"] == exp_os
    assert result["detected_port"] == open_port
    assert result["winrm_scheme"] == exp_scheme
    assert result["failure_stage"] is None and result["failure_code"] is None
    # Case 16 — 성공 경로의 checked_ports 는 실제 시도한 포트만
    assert result["checked_ports"] == exp_probed


# ═══════════════════════════════════════════════════════════════════════════
# Case 4~7 — 실패 종류별 대표 stage/code
# ═══════════════════════════════════════════════════════════════════════════
def test_case04_all_timeout(monkeypatch):
    result, _ = run_os_precheck(monkeypatch, {})
    assert result["reachable"] is False
    assert result["failure_stage"] == "reachable"
    assert result["failure_code"] == "TCP_CONNECT_FAILED", "timeout 을 장비 다운으로 확정하지 않는다"
    assert result["detected_os"] is None
    assert result["checked_ports"] == [5986, 5985, 22]


def test_case05_all_refused(monkeypatch):
    result, _ = run_os_precheck(
        monkeypatch, {5986: "refused", 5985: "refused", 22: "refused"})
    assert result["reachable"] is True, "RST 는 호스트가 살아 있다는 능동적 관측"
    assert result["port_open"] is False
    assert result["failure_stage"] == "port"
    assert result["failure_code"] == "TCP_CONNECTION_REFUSED"


@pytest.mark.parametrize("results,exp_stage,exp_code", [
    # 대표 선정 규칙: RST 를 하나라도 관측하면 REFUSED (가장 강한 관측)
    ({5986: "timeout", 5985: "refused", 22: "timeout"}, "port", "TCP_CONNECTION_REFUSED"),
    ({5986: "refused", 5985: "timeout", 22: "timeout"}, "port", "TCP_CONNECTION_REFUSED"),
    ({5986: "timeout", 5985: "timeout", 22: "refused"}, "port", "TCP_CONNECTION_REFUSED"),
    # RST 가 없으면 CONNECT_FAILED
    ({5986: "timeout", 5985: "other", 22: "timeout"},   "reachable", "TCP_CONNECT_FAILED"),
])
def test_case06_mixed_results_use_deterministic_rule(monkeypatch, results, exp_stage, exp_code):
    """포트마다 결과가 달라도 대표 code 는 probe 순서와 무관하게 결정적이어야 한다."""
    result, _ = run_os_precheck(monkeypatch, results)
    assert result["failure_stage"] == exp_stage, results
    assert result["failure_code"] == exp_code, results
    # 포트별 원본 사유는 전부 detail 에 보존된다
    for port in results:
        assert "port={0}".format(port) in result["detail"], f"{port} 사유 소실"


def test_case07_dns_resolution_failure(monkeypatch):
    result, _ = run_os_precheck(
        monkeypatch, {5986: "dns", 5985: "dns", 22: "dns"})
    assert result["failure_stage"] == "reachable"
    assert result["failure_code"] == "DNS_RESOLUTION_FAILED"
    assert "DNS" in result["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# Case 8~9 — 주소군 처리 (IPv4 / 복수 주소)
# ═══════════════════════════════════════════════════════════════════════════
def test_case08_09_dual_stack_first_success_wins(monkeypatch):
    """tcp_check_ex 는 getaddrinfo 순서대로 시도하고 첫 성공에서 반환한다."""
    order: list[tuple[int, str]] = []

    def fake_getaddrinfo(host, port, type=None):  # noqa: A002
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.30", port)),
        ]

    class _Sock:
        def __init__(self, family):
            self.family = family

        def settimeout(self, _t):
            pass

        def connect(self, addr):
            order.append((self.family, addr[0]))
            if self.family == socket.AF_INET6:
                raise OSError("EAFNOSUPPORT")   # IPv6 비활성 host

        def close(self):
            pass

    monkeypatch.setattr(pb.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(pb.socket, "socket", lambda f, *_a: _Sock(f))

    ok, err, kind = pb.tcp_check_ex("192.0.2.30", 22, 2.0)
    assert ok is True and err is None and kind is None
    assert [addr for _f, addr in order] == ["::1", "192.0.2.30"], (
        "IPv6 실패 후 IPv4 로 graceful degradation 해야 한다"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Case 10~15 — 이후 흐름(Credential / Gathering)은 이번 Phase 범위 밖이지만,
#              precheck 가 그 흐름에 넘기는 값이 바뀌지 않았는지 고정한다
# ═══════════════════════════════════════════════════════════════════════════
def test_port_precheck_never_sets_auth_success(monkeypatch):
    """Case 10~13 전제 — 포트 점검 단계는 인증을 시도하지 않는다."""
    for results in ({5986: "ok"}, {22: "ok"}, {}, {5986: "refused"}):
        result, _ = run_os_precheck(monkeypatch, results)
        assert result["auth_success"] is None, results


def test_protocol_not_claimed_without_probe(monkeypatch):
    """포트가 열렸다고 SSH/WinRM 프로토콜을 확인했다고 표시하지 않는다."""
    result, _ = run_os_precheck(monkeypatch, {5986: "ok"})
    assert result["port_open"] is True
    assert result["protocol_supported"] is False, (
        "probe_protocol=false 는 '확인하지 않았다'는 뜻 — true 로 위장하면 안 된다"
    )
    assert result["protocol_checked"] is False
    assert result["failure_stage"] is None, "확인하지 않은 것을 실패로 만들지도 않는다"


# ═══════════════════════════════════════════════════════════════════════════
# 타임아웃 / 재시도 보존
# ═══════════════════════════════════════════════════════════════════════════
def test_timeout_is_passed_through_not_defaulted(monkeypatch):
    """OS 는 2초를 쓴다. 모듈 기본값 3.0 이 조용히 적용되면 안 된다."""
    _result, seen = run_os_precheck(monkeypatch, {}, timeout_port=2.0)
    assert [t for _p, t in seen] == [2.0, 2.0, 2.0]


def test_no_retry_per_port(monkeypatch):
    """포트당 1회만 시도한다 (재시도 정책 변경 금지)."""
    _result, seen = run_os_precheck(monkeypatch, {})
    assert [p for p, _t in seen] == [5986, 5985, 22], "포트당 중복 시도 없음"


# ═══════════════════════════════════════════════════════════════════════════
# Case 18 — 민감정보 비노출
# ═══════════════════════════════════════════════════════════════════════════
def test_case18_no_credentials_in_result(monkeypatch):
    result, _ = run_os_precheck(monkeypatch, {5986: "refused", 5985: "timeout", 22: "dns"})
    blob = " ".join(str(v) for v in result.values())
    for secret in ("password", "Passw0rd", "Goodmit0802!", "Authorization", "Basic "):
        assert secret not in blob, f"민감정보 노출: {secret!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Cross-channel — 공통 코드 수정이 redfish / esxi 를 바꾸지 않았는지
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("channel", ["redfish", "esxi"])
def test_other_channels_still_probe_protocol(monkeypatch, channel):
    """probe_protocol 기본값은 true — 기존 두 채널의 Stage 3 는 그대로 수행된다."""
    monkeypatch.setattr(
        pb, "tcp_check_ex", lambda *_a, **_k: (True, None, None))
    monkeypatch.setattr(
        pb, "http_get",
        lambda *_a, **_k: (True, None, {"status_code": 200, "json": {"@odata.id": "/redfish/v1", "@odata.type": "#ServiceRoot.v1_15_0.ServiceRoot", "RedfishVersion": "1.6.0"}}))

    class _Fake:
        params = dict(host="192.0.2.10", channel=channel, ports=[], timeout_port=3.0,
                      timeout_protocol=15.0, timeout_auth=8.0, username=None, password=None,
                      verify_ssl=False, probe_protocol=True, port_poll_interval=0.0)

        def exit_json(self, **kw):
            raise _ExitJson(kw)

    monkeypatch.setattr(pb, "AnsibleModule", lambda **_kw: _Fake())
    with pytest.raises(_ExitJson) as exc:
        pb.run_module()
    result = exc.value.result

    assert result["protocol_supported"] is True, f"{channel} Stage 3 가 사라지면 안 된다"
    assert result["protocol_checked"] is True
    assert result["checked_ports"] == [443], f"{channel} checked_ports 종전과 동일"
    assert result["failure_stage"] is None and result["failure_code"] is None
