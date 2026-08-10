"""probe_os — OS 관리 프로토콜 판정 (Phase 3-B 이후).

이력
----
- 종전(~Phase 3-A): `/wsman` 이 200/401/403/405/503 중 하나면 WinRM 으로 인정했다.
  이는 사실상 "아무 HTTP 응답이나 오면 WinRM" 이라 5985/5986 에 떠 있는 **일반 웹서버를
  Windows 로 오판**할 수 있는 규칙이었다. (이 함수는 그동안 운영 경로에 배선돼 있지 않아
  실제 사고는 없었다.)
- Phase 3-B (2026-08-10): 상태 코드 whitelist 를 버리고 **WS-Management 헤더 근거**로 판정한다.
  자격증명을 보내지 않고 얻을 수 있는 근거는 응답 헤더뿐이며, 인정하는 근거는 둘뿐이다:
    (1) WWW-Authenticate 에 WSMAN realm  → 결정적
    (2) Server=Microsoft-HTTPAPI + 인증 요구 → 강한 정황 (http.sys 가 /wsman 을 보호 중)

SSH 는 RFC 4253 §4.2 의 identification 을 확인한다 (선행 추가 줄 허용, SSH-2.0 / SSH-1.99 만).
"""
from __future__ import annotations

import socket
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "common" / "library"))

_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import precheck_bundle  # noqa: E402


def _http_get_returning(ok, err, payload):
    def fake(url, timeout, verify=False, auth=None):
        return ok, err, payload

    return fake


def _resp(status, headers=None, ok=False):
    return ok, None if ok else "HTTP {0}".format(status), {
        "status_code": status, "json": None, "headers": headers or {},
    }


# ═══════════════════════════════════════════════════════════════════════════
# WinRM 인정 — WS-Management 헤더 근거가 있을 때만
# ═══════════════════════════════════════════════════════════════════════════
WSMAN_401 = {
    "www-authenticate": 'Negotiate, Basic realm="WSMAN"',
    "server": "Microsoft-HTTPAPI/2.0",
}
HTTPAPI_401 = {"www-authenticate": "Negotiate", "server": "Microsoft-HTTPAPI/2.0"}


@pytest.mark.parametrize("port,scheme", [(5986, "https"), (5985, "http")])
def test_winrm_accepted_on_wsman_realm(port, scheme):
    """`Basic realm="WSMAN"` 은 결정적 근거."""
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(*_resp(401, WSMAN_401))):
        ok, err, facts = precheck_bundle.probe_os("192.0.2.30", port, 5.0)
    assert ok is True, err
    assert facts == {}, "소프트웨어 버전 등 새 필드를 외부 JSON 에 싣지 않는다"


def test_winrm_accepted_on_httpapi_with_auth_challenge():
    """Server=Microsoft-HTTPAPI + 인증 요구 = /wsman 이 보호되고 있다는 강한 정황."""
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(*_resp(401, HTTPAPI_401))):
        ok, err, _facts = precheck_bundle.probe_os("192.0.2.30", 5985, 5.0)
    assert ok is True, err


# ═══════════════════════════════════════════════════════════════════════════
# False Positive 방지 (§17) — 포트 번호만 맞는 서비스를 Windows 로 보지 않는다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("status,headers,label", [
    (200, {"server": "nginx/1.24.0"}, "5985 에 뜬 일반 HTTP 서버"),
    (200, {"server": "Apache/2.4.58"}, "일반 HTTPS 서버"),
    (404, {"server": "nginx/1.24.0"}, "경로 없음"),
    (403, {"server": "nginx/1.24.0"}, "권한 거부"),
    (405, {"server": "Apache/2.4.58", "allow": "GET, HEAD"}, "메서드 미지원"),
    (503, {"server": "nginx/1.24.0"}, "서비스 불가"),
    (401, {"www-authenticate": 'Basic realm="Restricted"',
           "server": "nginx/1.24.0"}, "Basic 인증 붙은 일반 웹서버"),
    (200, {}, "헤더 없음"),
])
def test_generic_web_server_is_not_winrm(status, headers, label):
    """종전 whitelist(200/401/403/405/503)면 전부 WinRM 으로 통과했을 응답들."""
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(*_resp(status, headers, ok=(status == 200)))):
        ok, err, facts = precheck_bundle.probe_os("192.0.2.30", 5985, 5.0)
    assert ok is False, "{0} 을 WinRM 으로 오판하면 안 된다".format(label)
    assert facts is None
    assert "WinRM 응답 아님" in err


def test_winrm_tls_handshake_failure(monkeypatch):
    """5986 TLS handshake 실패 — payload 자체가 없다."""
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(False, "연결 실패: TLS handshake 오류", None)):
        ok, err, facts = precheck_bundle.probe_os("192.0.2.30", 5986, 5.0)
    assert ok is False and facts is None
    assert "TLS" in err


def test_winrm_timeout_real_failure():
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(False, "요청 시간 초과", None)):
        ok, _err, facts = precheck_bundle.probe_os("192.0.2.30", 5986, 5.0)
    assert ok is False
    assert facts is None


def test_winrm_uses_default_wsman_path():
    """프로젝트가 custom WinRM path 를 설정하지 않으므로 기본 /wsman 을 쓴다."""
    seen = {}

    def fake(url, timeout, verify=False, auth=None):
        seen["url"] = url
        seen["verify"] = verify
        return _resp(401, WSMAN_401)

    with patch.object(precheck_bundle, "http_get", fake):
        precheck_bundle.probe_os("192.0.2.30", 5986, 5.0)

    assert seen["url"] == "https://192.0.2.30:5986/wsman"
    assert seen["verify"] is False, (
        "Windows 수집이 ansible_winrm_server_cert_validation: ignore 를 쓰므로 "
        "probe 가 더 엄격하면 정상 서버가 탈락한다"
    )
    assert precheck_bundle.WINRM_ENDPOINT_PATH == "/wsman"


# ═══════════════════════════════════════════════════════════════════════════
# SSH identification (RFC 4253 §4.2)
# ═══════════════════════════════════════════════════════════════════════════
def _ssh_socket(chunks):
    """recv 가 chunks 를 순서대로 돌려주는 가짜 소켓."""
    it = iter(chunks)

    class _Sock:
        def __init__(self, *_a):
            pass

        def settimeout(self, _t):
            pass

        def connect(self, _a):
            pass

        def recv(self, _n):
            return next(it, b"")

        def close(self):
            pass

    return _Sock


def _patch_socket(monkeypatch, sock_cls):
    monkeypatch.setattr(
        precheck_bundle.socket, "getaddrinfo",
        lambda h, p, type=None: [                       # noqa: A002
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (h, p))])
    monkeypatch.setattr(precheck_bundle.socket, "socket", lambda *_a: sock_cls())


@pytest.mark.parametrize("banner", [
    b"SSH-2.0-OpenSSH_8.0\r\n",
    b"SSH-1.99-OpenSSH_5.3\r\n",
])
def test_ssh_identification_accepted(monkeypatch, banner):
    _patch_socket(monkeypatch, _ssh_socket([banner]))
    ok, err, facts = precheck_bundle.probe_os("192.0.2.30", 22, 5.0)
    assert ok is True, err
    assert facts == {}, "identification 원문을 외부 JSON 에 싣지 않는다"


def test_ssh_identification_after_extra_lines(monkeypatch):
    """RFC 4253 §4.2 — identification 앞에 다른 줄을 보내는 서버도 정상이다."""
    _patch_socket(monkeypatch, _ssh_socket([
        b"************************************\r\n",
        b"* Authorized access only           *\r\n",
        b"************************************\r\n",
        b"SSH-2.0-OpenSSH_9.6\r\n",
    ]))
    ok, err, _facts = precheck_bundle.probe_os("192.0.2.30", 22, 5.0)
    assert ok is True, err


def test_non_ssh_service_on_port_22_rejected(monkeypatch):
    """False Positive 방지 — 22 번에 뜬 일반 TCP 서비스를 Linux 로 보지 않는다."""
    _patch_socket(monkeypatch, _ssh_socket([b"220 smtp.example.com ESMTP\r\n"]))
    ok, err, facts = precheck_bundle.probe_os("192.0.2.30", 22, 5.0)
    assert ok is False and facts is None
    assert "SSH identification 미수신" in err or "SSH" in err


def test_silent_service_on_port_22_rejected(monkeypatch):
    """아무것도 보내지 않는 서비스도 SSH 가 아니다."""
    _patch_socket(monkeypatch, _ssh_socket([b""]))
    ok, err, _facts = precheck_bundle.probe_os("192.0.2.30", 22, 5.0)
    assert ok is False
    assert "미수신" in err


def test_unknown_ssh_protoversion_rejected(monkeypatch):
    """SSH- 접두사만 맞는 응답을 그대로 통과시키지 않는다."""
    _patch_socket(monkeypatch, _ssh_socket([b"SSH-9.9-Experimental\r\n"]))
    ok, err, _facts = precheck_bundle.probe_os("192.0.2.30", 22, 5.0)
    assert ok is False
    assert "protoversion" in err


def test_ssh_read_is_bounded(monkeypatch):
    """무제한으로 읽지 않는다 — 줄 수 상한에서 멈춘다."""
    noise = [b"noise line\r\n"] * 50
    _patch_socket(monkeypatch, _ssh_socket(noise + [b"SSH-2.0-OpenSSH_9.6\r\n"]))
    ok, _err, _facts = precheck_bundle.probe_os("192.0.2.30", 22, 5.0)
    assert ok is False, "상한을 넘는 선행 줄 뒤의 identification 은 읽지 않는다"
    assert precheck_bundle._SSH_ID_MAX_LINES <= 16
    assert precheck_bundle._SSH_ID_MAX_BYTES <= 4096


def test_unsupported_port():
    ok, err, facts = precheck_bundle.probe_os("192.0.2.30", 9999, 5.0)
    assert ok is False
    assert "지원하지 않는 OS 포트" in err
    assert facts is None


def test_probe_never_leaks_credentials(monkeypatch):
    """probe 는 자격증명을 보내지 않는다."""
    seen = {}

    def fake(url, timeout, verify=False, auth=None):
        seen["auth"] = auth
        return _resp(401, WSMAN_401)

    with patch.object(precheck_bundle, "http_get", fake):
        precheck_bundle.probe_os("192.0.2.30", 5985, 5.0)
    assert seen["auth"] is None, "Protocol Probe 단계에서 자격증명을 보내면 안 된다"
