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

# 2026-08-12: 누출 가드가 검사 대상인 **진짜 비밀번호를 소스에 그대로** 적어 두고 있었다.
#   가드 파일 자체가 누출 지점이라, 평문 대신 sha256 앞 8자리로 대조하는 공용 가드로
#   바꾼다. 입력으로 넣던 실 자격증명도 합성 canary 로 바꾼다 (검사 의미는 동일).
from tests.secret_guard import (  # noqa: E402
    CANARY_PASSWORD, CANARY_RECOVERY, CANARY_TARGET, assert_no_secret,
)


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
# WinRM — WS-Management Identify 응답으로만 판정
# ═══════════════════════════════════════════════════════════════════════════
WSMID = "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd"

IDENTIFY_OK = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:wsmid="{ns}"><s:Body><wsmid:IdentifyResponse>'
    "<wsmid:ProtocolVersion>http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd</wsmid:ProtocolVersion>"
    "<wsmid:ProductVendor>Microsoft Corporation</wsmid:ProductVendor>"
    "<wsmid:ProductVersion>OS: 0.0.0 SP: 0.0 Stack:1.0</wsmid:ProductVersion>"
    "</wsmid:IdentifyResponse></s:Body></s:Envelope>"
).format(ns=WSMID).encode()


def _post_returning(ok, err, payload):
    def fake(url, body, timeout, verify=False, extra_headers=None):
        return ok, err, payload

    return fake


def _soap(status, body, ok=True):
    return ok, None if ok else "HTTP {0}".format(status), {
        "status_code": status, "body": body,
    }


@pytest.mark.parametrize("port,scheme", [(5986, "https"), (5985, "http")])
def test_winrm_accepted_on_identify_response(port, scheme):
    """정상 비인증 IdentifyResponse → WinRM 인정."""
    with patch.object(precheck_bundle, "http_post_soap",
                      _post_returning(*_soap(200, IDENTIFY_OK))):
        ok, err, facts = precheck_bundle.probe_os("192.0.2.30", port, 5.0)
    assert ok is True, err
    assert facts == {}, "raw SOAP / 버전 문자열을 외부 JSON 에 싣지 않는다"


def test_identify_request_shape():
    """비인증 Identify 요청 형식 — SOAP POST + WSMANIDENTIFY 헤더, 자격증명 없음."""
    seen = {}

    def fake(url, body, timeout, verify=False, extra_headers=None):
        seen.update(url=url, body=body, verify=verify, headers=extra_headers or {})
        return _soap(200, IDENTIFY_OK)

    with patch.object(precheck_bundle, "http_post_soap", fake):
        precheck_bundle.probe_os("192.0.2.30", 5986, 5.0)

    assert seen["url"] == "https://192.0.2.30:5986/wsman"
    assert seen["headers"].get("WSMANIDENTIFY") == "unauthenticated"
    assert b"Identify" in seen["body"] and WSMID.encode() in seen["body"]
    assert b"Authorization" not in seen["body"]
    assert seen["verify"] is False, (
        "Windows 수집이 ansible_winrm_server_cert_validation: ignore 를 쓰므로 "
        "probe 가 더 엄격하면 정상 서버가 탈락한다"
    )
    assert precheck_bundle.WINRM_ENDPOINT_PATH == "/wsman"


@pytest.mark.parametrize("ns", [
    "https://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd",
    "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity",
])
def test_identify_namespace_variants_accepted(ns):
    """문서/구현마다 http/https 와 .xsd 유무가 갈린다 — 관측된 표기를 모두 허용."""
    body = IDENTIFY_OK.replace(WSMID.encode(), ns.encode())
    with patch.object(precheck_bundle, "http_post_soap",
                      _post_returning(*_soap(200, body))):
        ok, err, _f = precheck_bundle.probe_os("192.0.2.30", 5985, 5.0)
    assert ok is True, err


# ═══════════════════════════════════════════════════════════════════════════
# False Positive 방지 (§9) — Identify 응답이 아니면 전부 거부
# ═══════════════════════════════════════════════════════════════════════════
_HTML = b"<html><body>It works!</body></html>"
_OTHER_NS_XML = (
    '<?xml version="1.0"?><r:IdentifyResponse xmlns:r="http://example.com/other">'
    "<r:ProtocolVersion>http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd</r:ProtocolVersion>"
    "<r:ProductVendor>Microsoft Corporation</r:ProductVendor>"
    "</r:IdentifyResponse>"
).encode()
_NO_PROTOCOL = (
    '<?xml version="1.0"?><wsmid:IdentifyResponse xmlns:wsmid="{ns}">'
    "<wsmid:ProductVendor>Microsoft Corporation</wsmid:ProductVendor>"
    "</wsmid:IdentifyResponse>"
).format(ns=WSMID).encode()
_BAD_PROTOCOL = (
    '<?xml version="1.0"?><wsmid:IdentifyResponse xmlns:wsmid="{ns}">'
    "<wsmid:ProtocolVersion>http://example.com/not-wsman</wsmid:ProtocolVersion>"
    "<wsmid:ProductVendor>Microsoft Corporation</wsmid:ProductVendor>"
    "</wsmid:IdentifyResponse>"
).format(ns=WSMID).encode()
_TRUNCATED = IDENTIFY_OK[: len(IDENTIFY_OK) // 2]


@pytest.mark.parametrize("status,body,label", [
    (200, _HTML, "단순 HTTP 200 (일반 웹서버)"),
    (401, b"", "단순 HTTP 401"),
    (403, b"", "단순 HTTP 403"),
    (404, _HTML, "/wsman 없음"),
    (405, b"", "메서드 미지원"),
    (500, b"", "서버 오류"),
    (200, b'<?xml version="1.0"?><root><ok/></root>', "일반 XML"),
    (200, _OTHER_NS_XML, "다른 네임스페이스의 IdentifyResponse"),
    (200, _NO_PROTOCOL, "ProtocolVersion 없음"),
    (200, _BAD_PROTOCOL, "ProtocolVersion 이 WS-Management 아님"),
    (200, _TRUNCATED, "잘린 IdentifyResponse"),
])
def test_non_wsman_response_rejected(status, body, label):
    ok = status == 200
    with patch.object(precheck_bundle, "http_post_soap",
                      _post_returning(*_soap(status, body, ok=ok))):
        got, err, facts = precheck_bundle.probe_os("192.0.2.30", 5985, 5.0)
    assert got is False, "{0} 을 WinRM 으로 오판하면 안 된다".format(label)
    assert facts is None
    assert "IdentifyResponse 아님" in err


def test_header_heuristic_is_gone():
    """헤더만으로 통과시키던 경로가 제거됐는지 — Microsoft-HTTPAPI + 401 도 거부."""
    assert not hasattr(precheck_bundle, "_looks_like_wsman"), (
        "헤더 heuristic 함수가 남아 있으면 안 된다"
    )
    with patch.object(precheck_bundle, "http_post_soap",
                      _post_returning(False, "HTTP 401", {"status_code": 401, "body": b""})):
        ok, _err, _f = precheck_bundle.probe_os("192.0.2.30", 5985, 5.0)
    assert ok is False, "Microsoft-HTTPAPI / WWW-Authenticate 만으로 WinRM 판정 금지"


def test_non_windows_wsman_device_not_windows():
    """WS-Management 는 표준이라 비-Windows 장비도 구현한다 — Windows 로 확정하지 않는다."""
    body = IDENTIFY_OK.replace(b"Microsoft Corporation", b"Openwsman Project")
    with patch.object(precheck_bundle, "http_post_soap",
                      _post_returning(*_soap(200, body))):
        ok, err, _f = precheck_bundle.probe_os("192.0.2.30", 5985, 5.0)
    assert ok is False
    assert "Windows WinRM 이 아님" in err and "Openwsman" in err


def test_xml_bomb_body_is_bounded():
    """파싱 전에 본문 크기를 제한한다 (ElementTree 엔티티 확장 방어)."""
    huge = b"<a>" + b"x" * (precheck_bundle._IDENTIFY_MAX_BYTES + 10) + b"</a>"
    is_wsman, vendor, why = precheck_bundle.parse_identify_response(huge)
    assert is_wsman is False and vendor is None
    assert "상한" in why


def test_winrm_tls_handshake_failure():
    """5986 TLS handshake 실패 — payload 자체가 없다."""
    with patch.object(precheck_bundle, "http_post_soap",
                      _post_returning(False, "연결 실패: TLS handshake 오류", None)):
        ok, err, facts = precheck_bundle.probe_os("192.0.2.30", 5986, 5.0)
    assert ok is False and facts is None
    assert "TLS" in err


def test_winrm_timeout_real_failure():
    with patch.object(precheck_bundle, "http_post_soap",
                      _post_returning(False, "요청 시간 초과", None)):
        ok, _err, facts = precheck_bundle.probe_os("192.0.2.30", 5986, 5.0)
    assert ok is False
    assert facts is None


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


def test_probe_never_leaks_credentials():
    """probe 는 자격증명을 보내지 않는다 (Credential Probe 와 분리)."""
    seen = {}

    def fake(url, body, timeout, verify=False, extra_headers=None):
        seen.update(body=body, headers=extra_headers or {})
        return _soap(200, IDENTIFY_OK)

    with patch.object(precheck_bundle, "http_post_soap", fake):
        precheck_bundle.probe_os("192.0.2.30", 5985, 5.0)

    blob = seen["body"].decode() + " " + " ".join(
        "{0}:{1}".format(k, v) for k, v in seen["headers"].items())
    # 알려진 실 자격증명이 섞였는지 digest 로 대조한다 (평문을 저장하지 않는 가드).
    assert_no_secret(blob, "protocol probe 요청")
    for secret in ("Authorization", "Basic ", "password", "Cookie", CANARY_PASSWORD):
        assert secret not in blob, "Protocol Probe 에 {0} 이 실리면 안 된다".format(secret)
