"""precheck detail 전달 + 진단 배선 회귀 (Phase 1-A, 2026-08-10).

배경
----
precheck_bundle 은 실패 원인을 `detail` 에 문자열로 담아 반환한다
(`_init_result:385` 생성, `run_module` 의 각 실패 분기가 채움). 그런데 2026-08-10
이전까지 이 값은 최종 envelope 에 **한 번도 도달하지 못했다**:

  1. `build_diagnosis()` 가 diagnosis dict 에 detail 을 싣지 않고
     (`filter_plugins/diagnosis_mapper.py:60-68`),
  2. 대신 전제로 삼은 `errors[0].detail` 은 `_fail_error_detail` 변수로 채워지는데
     (`common/tasks/normalize/build_failed_output.yml:49`),
  3. 그 변수를 **set 하는 코드가 저장소에 하나도 없었다.**

결과: `"port=443: 연결 시간 초과 (timeout=3.0s)"` 같은 가장 구체적인 기술 정보가
호출자에게 전혀 전달되지 않았다. 본 테스트는 (a) 모듈이 각 실패 단계에서 detail 을
실제로 채우는지, (b) 그 detail 에 자격증명이 섞이지 않는지, (c) YAML 배선이
유지되는지를 고정한다.

네트워크 0 — socket / http_get 을 monkeypatch 한다.
"""
from __future__ import annotations

import re
import socket
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "common" / "library"))

# ansible stub (기존 precheck unit test 와 동일 패턴)
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_mu = types.ModuleType("ansible.module_utils")
_stub_mu.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_mu
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_mu)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import precheck_bundle as pb  # noqa: E402


# ---------------------------------------------------------------------------
# run_module() 구동용 최소 AnsibleModule 대역
# ---------------------------------------------------------------------------
class _ExitJson(Exception):
    """exit_json 호출을 잡아 결과를 회수하기 위한 sentinel."""

    def __init__(self, result: dict) -> None:
        super().__init__("exit_json")
        self.result = result


class _FakeModule:
    def __init__(self, params: dict) -> None:
        self.params = params

    def exit_json(self, **kwargs):
        raise _ExitJson(kwargs)


def _run(monkeypatch, *, channel="redfish", ports=None, **overrides) -> dict:
    """run_module() 을 1회 실행하고 exit_json 결과 dict 를 반환."""
    params = {
        "host": "192.0.2.10",
        "channel": channel,
        "ports": ports if ports is not None else [],
        "timeout_port": 3.0,
        "timeout_protocol": 15.0,
        "timeout_auth": 8.0,
        "username": None,
        "password": None,
        "verify_ssl": False,
    }
    params.update(overrides)
    monkeypatch.setattr(pb, "AnsibleModule", lambda **_kw: _FakeModule(params))
    with pytest.raises(_ExitJson) as exc:
        pb.run_module()
    return exc.value.result


def _tcp_raising(exc: BaseException):
    """tcp_check 내부 connect 가 특정 예외를 던지도록 socket 계층을 대체."""
    class _Sock:
        def settimeout(self, _t):
            pass

        def connect(self, _addr):
            raise exc

        def close(self):
            pass

    def _fake_socket(_family, _socktype, _proto):
        return _Sock()

    return _fake_socket


def _addrinfo_ipv4(host, port, type=None):  # noqa: A002 - socket API 시그니처 유지
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]


# ---------------------------------------------------------------------------
# C2~C6 — 각 실패 단계에서 detail 이 실제로 채워지는가
# ---------------------------------------------------------------------------
def test_detail_populated_on_dns_failure(monkeypatch):
    """C2 — DNS 해석 실패 시 detail 에 사유가 남는다."""
    def _boom(host, port, type=None):  # noqa: A002
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(pb.socket, "getaddrinfo", _boom)
    result = _run(monkeypatch)

    assert result["failure_stage"] == "reachable"
    assert result["detail"], "DNS 실패인데 detail 이 비어 있다"
    assert "DNS" in result["detail"]


def test_detail_populated_on_tcp_timeout(monkeypatch):
    """C3 — TCP timeout 시 detail 에 timeout 값까지 남는다."""
    monkeypatch.setattr(pb.socket, "getaddrinfo", _addrinfo_ipv4)
    monkeypatch.setattr(pb.socket, "socket", _tcp_raising(socket.timeout()))
    result = _run(monkeypatch)

    assert result["reachable"] is False
    assert result["port_open"] is False
    assert result["failure_stage"] == "reachable"
    assert "port=443" in result["detail"]
    assert "3.0" in result["detail"], "timeout 값이 detail 에 없다"


def test_detail_populated_on_connection_refused(monkeypatch):
    """C4 — RST 는 host alive 증거. reachable=true + port 단계 실패 + detail."""
    monkeypatch.setattr(pb.socket, "getaddrinfo", _addrinfo_ipv4)
    monkeypatch.setattr(pb.socket, "socket", _tcp_raising(ConnectionRefusedError()))
    result = _run(monkeypatch)

    assert result["reachable"] is True, "거부 응답은 호스트가 살아있다는 증거"
    assert result["port_open"] is False
    assert result["failure_stage"] == "port"
    assert "거부" in result["detail"]


def test_detail_populated_on_other_os_error(monkeypatch):
    """C5 — 기타 OSError 도 원문이 detail 에 보존된다."""
    monkeypatch.setattr(pb.socket, "getaddrinfo", _addrinfo_ipv4)
    monkeypatch.setattr(pb.socket, "socket", _tcp_raising(OSError("EHOSTUNREACH")))
    result = _run(monkeypatch)

    assert result["failure_stage"] == "reachable"
    assert "EHOSTUNREACH" in result["detail"]


def test_detail_populated_on_protocol_failure(monkeypatch):
    """C6 — 포트는 열렸으나 프로토콜 확인 실패 시 detail 에 원인이 남는다."""
    monkeypatch.setattr(pb.socket, "getaddrinfo", _addrinfo_ipv4)

    class _OkSock:
        def settimeout(self, _t):
            pass

        def connect(self, _addr):
            return None

        def close(self):
            pass

    monkeypatch.setattr(pb.socket, "socket", lambda *_a: _OkSock())
    # ServiceRoot 가 500 → 허용 status 목록(401/403/405/406/503) 밖 → 프로토콜 실패
    monkeypatch.setattr(
        pb, "http_get",
        lambda url, timeout, verify=False, auth=None: (
            False, "HTTP 500", {"status_code": 500, "json": None}
        ),
    )
    result = _run(monkeypatch)

    assert result["reachable"] is True
    assert result["port_open"] is True
    assert result["protocol_supported"] is False
    assert result["failure_stage"] == "protocol"
    assert result["detail"] == "HTTP 500"


def test_detail_is_none_on_success(monkeypatch):
    """성공 시 detail 은 None — 이후 gather 단계 실패에 precheck detail 이 새지 않는다."""
    monkeypatch.setattr(pb.socket, "getaddrinfo", _addrinfo_ipv4)

    class _OkSock:
        def settimeout(self, _t):
            pass

        def connect(self, _addr):
            return None

        def close(self):
            pass

    monkeypatch.setattr(pb.socket, "socket", lambda *_a: _OkSock())
    monkeypatch.setattr(
        pb, "http_get",
        lambda url, timeout, verify=False, auth=None: (
            True, None, {"status_code": 200, "json": {"RedfishVersion": "1.6.0"}}
        ),
    )
    result = _run(monkeypatch)

    assert result["protocol_supported"] is True
    assert result["failure_stage"] is None
    assert result["detail"] is None


# ---------------------------------------------------------------------------
# 보안 — detail 은 호출자에게 전달되므로 자격증명이 섞이면 안 된다
# ---------------------------------------------------------------------------
_SECRET_PATTERNS = tuple(
    re.compile(p) for p in (
        r"Passw0rd1!", r"Goodmit0802!", r"Dellidrac1!", r"hpinvent1!", r"VMware1!",
        r"password\s*[=:]\s*\S{4,}",
        r"Basic\s+[A-Za-z0-9+/=]{8,}",   # base64 Authorization 헤더
    )
)


def test_detail_never_contains_credentials(monkeypatch):
    """인증 단계 실패의 detail 에도 계정/비밀번호/Authorization 이 없어야 한다.

    `_try_redfish_auth:449` 는 http_get 의 err 를 그대로 detail 로 쓴다. http_get 은
    자격증명을 헤더로만 실어 보내고 err 문자열에는 담지 않는다(`:205-216`) — 그 계약을
    회귀로 고정한다. Phase 1-A 로 detail 이 실제 envelope 까지 전달되므로 필수 방어선.
    """
    result = pb._init_result("redfish", [443])
    monkeypatch.setattr(
        pb, "http_get",
        lambda url, timeout, verify=False, auth=None: (False, "HTTP 401", {"status_code": 401, "json": None}),
    )
    ok = pb._try_redfish_auth(
        "192.0.2.10", 443, "svc_admin", "Goodmit0802!", 8.0, False, result
    )

    assert ok is False
    assert result["auth_success"] is False
    assert result["failure_stage"] == "auth"
    blob = f"{result['detail']} {result['failure_reason']}"
    for pat in _SECRET_PATTERNS:
        assert not pat.search(blob), f"detail/reason 에 비밀값 패턴 노출: {pat.pattern}"
    assert "svc_admin" not in blob


# ---------------------------------------------------------------------------
# YAML 배선 회귀 — 코드가 있어도 배선이 끊기면 detail 은 다시 사라진다
# ---------------------------------------------------------------------------
def test_run_precheck_wires_fail_error_detail():
    """run_precheck.yml 이 _fail_error_detail 을 set 해야 build_failed_output 이 쓴다."""
    text = (REPO / "common/tasks/precheck/run_precheck.yml").read_text(encoding="utf-8")
    assert "_fail_error_detail:" in text, (
        "_fail_error_detail 배선이 사라졌다 — errors[0].detail 이 다시 항상 null 이 된다"
    )
    assert "_precheck_raw.detail" in text


def test_build_failed_output_still_consumes_fail_error_detail():
    """소비처(build_failed_output.yml:49)가 유지되는지 — 양쪽이 다 있어야 전달된다."""
    text = (REPO / "common/tasks/normalize/build_failed_output.yml").read_text(encoding="utf-8")
    assert "_fail_error_detail" in text


# ---------------------------------------------------------------------------
# B-8 — Redfish 실패 메시지의 도달 불가능 분기 회귀
# ---------------------------------------------------------------------------
def test_redfish_failure_message_has_no_dead_auth_branch():
    """`auth_success is none` 분기는 항상 참이라 뒤 분기를 죽인다 — 재도입 차단.

    이 시점의 auth_success 는 항상 None 이다: precheck 가 인증정보를 받지 않아
    Stage 4 를 건너뛰고(precheck_bundle.py:546-548), auth_success=true 로 덮어쓰는
    태스크는 이 메시지보다 뒤에 있다(redfish-gather/site.yml:191-206).
    """
    text = (REPO / "redfish-gather/site.yml").read_text(encoding="utf-8")
    start = text.index("abort if collect completely failed")
    block = text[start:start + 2000]
    assert "d.auth_success" not in block, (
        "실패 메시지 분기에서 auth_success 를 다시 조건으로 쓰고 있다 — "
        "이 값은 항상 None 이라 뒤 분기가 도달 불가능해진다 (B-8 재발)"
    )


# ---------------------------------------------------------------------------
# B-4 — OS checked_ports 가 실제 검사 순서와 일치하는가
# ---------------------------------------------------------------------------
def test_os_checked_ports_match_actual_probe_order():
    """PLAY 1 의 실제 순서는 5986 → 5985 → 22 (os-gather/site.yml:40-69)."""
    text = (REPO / "os-gather/site.yml").read_text(encoding="utf-8")

    # 포트 감지 순서 자체가 바뀌면 아래 기대값도 함께 바뀌어야 한다
    order = re.findall(r"^\s*port:\s*(\d+)\s*$", text, flags=re.MULTILINE)
    assert order[:3] == ["5986", "5985", "22"], f"wait_for 순서 변경됨: {order[:3]}"

    # 리터럴 checked_ports 값만 수집 (들여쓰기/정렬 공백 무시)
    literals = re.findall(r"checked_ports:\s*(\[[^\]]*\])", text)
    normalized = [re.sub(r"\s+", "", v) for v in literals]

    # 포트 전멸 경로 + linux 성공 경로: 3개 모두 시도됨
    assert normalized.count("[5986,5985,22]") == 2, (
        f"포트 전멸 / linux 성공 경로의 checked_ports 가 실제 검사 이력과 어긋난다: {normalized}"
    )
    # windows: 5986 성공 시 거기서 멈추므로 [5986], 5985 로 붙었을 때만 [5986, 5985]
    assert "[5986] if ((ansible_port | default(5986) | int) == 5986) else [5986, 5985]" in text

    # 역순/누락 표기 재발 차단
    assert "[22,5985,5986]" not in normalized
    assert "[22]" not in normalized
    assert "[5985,5986]" not in normalized


# ---------------------------------------------------------------------------
# B-7 — rescue 메시지의 태스크명 prefix 채널 간 대칭
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("site", ["redfish-gather/site.yml", "esxi-gather/site.yml"])
def test_rescue_message_carries_failed_task_name(site):
    """json_only callback 이 fatal 태스크 출력을 막으므로 errors[].message 가 유일한 단서."""
    text = (REPO / site).read_text(encoding="utf-8")
    assert "[task: {{ ansible_failed_task.name" in text, (
        f"{site} rescue 메시지에 실패 태스크명 prefix 가 없다"
    )
