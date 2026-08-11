"""Phase 6-A 실장비 회귀: SOAP POST 헤더 이름이 wire 에서 대소문자 그대로 나가는가.

실측 사고 (2026-08-11, lab Windows 10.100.64.120)
------------------------------------------------
`probe_os` 의 비인증 WS-Management Identify 가 5985/5986 양쪽에서 **HTTP 401 + 본문 0** 을
받아 정상 Windows 호스트가 전부 프로토콜 판정 실패(detected_os=None)로 떨어졌다.

원인은 판정 로직이 아니라 **전송 계층**이었다. `urllib.request` 는 헤더 이름을 두 번 정규화한다.
  - `Request.add_header()`  : `key.capitalize()`
  - `AbstractHTTPHandler.do_open()` : `name.title()`
그래서 `WSMANIDENTIFY` 가 `Wsmanidentify` 로 나갔고, WinRM 의 비인증 Identify 처리는
이 헤더 이름을 대소문자 그대로 본다. 헤더 이름만 보존해 보내면 같은 호스트가
**HTTP 200 + 완전한 IdentifyResponse** 를 돌려준다 (양성 대조군 확보).

왜 기존 테스트가 못 잡았나
--------------------------
WinRM 단위 테스트는 전부 `http_post_soap` **자체를 mock** 했다. 버그가 사는 계층이
테스트에 존재하지 않아 980+ 테스트 전수 통과와 실장비 100% 실패가 동시에 성립했다.
→ 이 파일은 **그 아래(http.client)** 를 seam 으로 잡아 재발을 막는다.
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

# lab Windows 10.100.64.120 이 실제로 돌려준 응답 (2026-08-11 캡처, 460 bytes 축약본)
REAL_IDENTIFY_RESPONSE = (
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:wsmid="http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd">'
    "<s:Header/><s:Body><wsmid:IdentifyResponse>"
    "<wsmid:ProtocolVersion>http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd</wsmid:ProtocolVersion>"
    "<wsmid:ProductVendor>Microsoft Corporation</wsmid:ProductVendor>"
    "<wsmid:ProductVersion>OS: 0.0.0 SP: 0.0 Stack: 3.0</wsmid:ProductVersion>"
    "</wsmid:IdentifyResponse></s:Body></s:Envelope>"
).encode("utf-8")


class _FakeResponse:
    def __init__(self, status=200, body=b""):
        self.status = status
        self._body = body

    def read(self, n=None):
        return self._body[:n] if n else self._body


class _FakeConn:
    """http.client 연결 대역 — 실제로 나간 헤더를 기록한다."""

    captured: dict = {}

    def __init__(self, host, port=None, timeout=None, context=None):
        _FakeConn.captured = {"host": host, "port": port, "timeout": timeout,
                              "context": context}

    def request(self, method, path, body=None, headers=None):
        _FakeConn.captured.update(method=method, path=path, body=body,
                                  headers=dict(headers or {}))

    def getresponse(self):
        return _FakeResponse(200, REAL_IDENTIFY_RESPONSE)

    def close(self):
        pass


@pytest.fixture()
def capture(monkeypatch):
    _FakeConn.captured = {}
    monkeypatch.setattr(pb.http.client, "HTTPSConnection", _FakeConn)
    monkeypatch.setattr(pb.http.client, "HTTPConnection", _FakeConn)
    return _FakeConn


# ═══════════════════════════════════════════════════════════════════════════
# 핵심 회귀 — 헤더 이름 대소문자
# ═══════════════════════════════════════════════════════════════════════════
def test_winrm_identify_header_name_is_not_normalized(capture):
    """`WSMANIDENTIFY` 가 `Wsmanidentify` 로 바뀌면 실장비가 401 을 준다."""
    pb.http_post_soap("https://192.0.2.10:5986/wsman", pb._IDENTIFY_REQUEST, 5.0,
                      verify=False, extra_headers={"WSMANIDENTIFY": "unauthenticated"})
    headers = capture.captured["headers"]
    assert "WSMANIDENTIFY" in headers, (
        "헤더 이름이 정규화됐다. 실장비 WinRM 은 이 이름을 대소문자 그대로 본다: {0}".format(
            sorted(headers))
    )
    assert headers["WSMANIDENTIFY"] == "unauthenticated"
    # 정규화된 변형이 함께 나가면 안 된다
    for wrong in ("Wsmanidentify", "WsmanIdentify", "wsmanidentify"):
        assert wrong not in headers, wrong


def test_esxi_soapaction_header_name_is_not_normalized(capture):
    """vSphere 쪽 헤더도 같은 이유로 보존돼야 한다 (현재는 관대하지만 계약을 고정한다)."""
    pb.http_post_soap("https://192.0.2.20:443/sdk", pb._RETRIEVE_SERVICE_CONTENT_REQUEST,
                      30.0, verify=False,
                      content_type=pb._SOAP11_CONTENT_TYPE,
                      extra_headers={"SOAPAction": '"urn:vim25/6.0"'},
                      max_bytes=pb._SERVICE_CONTENT_MAX_BYTES)
    headers = capture.captured["headers"]
    assert "SOAPAction" in headers, sorted(headers)
    assert headers["SOAPAction"] == '"urn:vim25/6.0"'
    assert headers["Content-Type"] == "text/xml; charset=UTF-8"


def test_content_type_header_name_is_not_normalized(capture):
    pb.http_post_soap("https://192.0.2.10:5986/wsman", b"<x/>", 5.0)
    assert "Content-Type" in capture.captured["headers"]
    assert "Content-type" not in capture.captured["headers"]


# ═══════════════════════════════════════════════════════════════════════════
# 전송 계층 교체가 기존 계약을 깨지 않았는가
# ═══════════════════════════════════════════════════════════════════════════
def test_request_shape_unchanged(capture):
    pb.http_post_soap("https://192.0.2.10:5986/wsman", pb._IDENTIFY_REQUEST, 7.0,
                      verify=False, extra_headers={"WSMANIDENTIFY": "unauthenticated"})
    c = capture.captured
    assert c["method"] == "POST"
    assert c["path"] == "/wsman"
    assert c["host"] == "192.0.2.10" and c["port"] == 5986
    assert c["timeout"] == 7.0
    assert c["body"] == pb._IDENTIFY_REQUEST, "요청 본문은 바뀌지 않는다"


def test_http_scheme_uses_plain_connection(monkeypatch):
    seen = {}

    class _Plain(_FakeConn):
        def __init__(self, host, port=None, timeout=None, context=None):
            seen["kind"] = "http"
            super().__init__(host, port, timeout, context)

    class _Tls(_FakeConn):
        def __init__(self, host, port=None, timeout=None, context=None):
            seen["kind"] = "https"
            super().__init__(host, port, timeout, context)

    monkeypatch.setattr(pb.http.client, "HTTPConnection", _Plain)
    monkeypatch.setattr(pb.http.client, "HTTPSConnection", _Tls)

    pb.http_post_soap("http://192.0.2.10:5985/wsman", b"<x/>", 5.0)
    assert seen["kind"] == "http"
    pb.http_post_soap("https://192.0.2.10:5986/wsman", b"<x/>", 5.0)
    assert seen["kind"] == "https"


def test_success_returns_body_and_status(capture):
    ok, err, payload = pb.http_post_soap(
        "https://192.0.2.10:5986/wsman", pb._IDENTIFY_REQUEST, 5.0,
        extra_headers={"WSMANIDENTIFY": "unauthenticated"})
    assert ok is True and err is None
    assert payload["status_code"] == 200
    is_wsman, vendor, why = pb.parse_identify_response(payload["body"])
    assert is_wsman is True, why
    assert vendor == "Microsoft Corporation"


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
def test_non_2xx_keeps_status_as_evidence(monkeypatch, status):
    class _Conn(_FakeConn):
        def getresponse(self):
            return _FakeResponse(status, b"")

    monkeypatch.setattr(pb.http.client, "HTTPSConnection", _Conn)
    ok, err, payload = pb.http_post_soap("https://192.0.2.10:5986/wsman", b"<x/>", 5.0)
    assert ok is False
    assert err == "HTTP {0}".format(status)
    assert payload["status_code"] == status


def test_timeout_and_connection_errors_have_no_payload(monkeypatch):
    import socket as _socket

    class _Timeout(_FakeConn):
        def getresponse(self):
            raise _socket.timeout()

    class _Refused(_FakeConn):
        def request(self, *a, **k):
            raise ConnectionRefusedError("refused")

    monkeypatch.setattr(pb.http.client, "HTTPSConnection", _Timeout)
    ok, err, payload = pb.http_post_soap("https://192.0.2.10:5986/wsman", b"<x/>", 5.0)
    assert ok is False and payload is None and "시간 초과" in err

    monkeypatch.setattr(pb.http.client, "HTTPSConnection", _Refused)
    ok, err, payload = pb.http_post_soap("https://192.0.2.10:5986/wsman", b"<x/>", 5.0)
    assert ok is False and payload is None and "연결 실패" in err


def test_max_bytes_still_applied(monkeypatch):
    class _Big(_FakeConn):
        def getresponse(self):
            return _FakeResponse(200, b"x" * 100000)

    monkeypatch.setattr(pb.http.client, "HTTPSConnection", _Big)
    _ok, _err, payload = pb.http_post_soap("https://192.0.2.10:443/sdk", b"<x/>", 5.0,
                                           max_bytes=1024)
    assert len(payload["body"]) == 1024


def test_no_credentials_in_request(capture):
    pb.http_post_soap("https://192.0.2.10:5986/wsman", pb._IDENTIFY_REQUEST, 5.0,
                      extra_headers={"WSMANIDENTIFY": "unauthenticated"})
    blob = "{0} {1}".format(capture.captured["headers"], capture.captured["body"]).lower()
    for secret in ("authorization", "password", "cookie", "basic "):
        assert secret not in blob, secret


def test_probe_os_windows_accepts_real_lab_response(monkeypatch):
    """실장비 응답 그대로를 넣으면 probe_os 가 Windows 로 판정한다 (전 경로 통합)."""
    monkeypatch.setattr(pb.http.client, "HTTPSConnection", _FakeConn)
    ok, err, facts = pb.probe_os("192.0.2.10", 5986, 5.0)
    assert ok is True, err
    assert facts == {}
