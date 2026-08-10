"""Phase 4-B: ESXi Protocol Detection — `/sdk` HTTP status 가 아니라 vim25 SOAP 응답으로 판정.

배경
----
종전 `probe_esxi` 는 `GET /sdk` 의 **HTTP status** 만 봤다
(`200/301/302/401/403/404/405/500/503` whitelist). 443 에서 뭐라도 응답하면 통과라
일반 HTTPS 서버가 전부 "vSphere" 로 판정될 수 있었다.

현재는 vSphere Web Services API 의 `RetrieveServiceContent` 를 실제로 POST 하고,
응답이 구조적으로 vim25 인지 확인한다. HTTP status 는 Evidence 로만 남긴다.

성공 근거는 둘뿐이다.
  (1) `{urn:vim25}RetrieveServiceContentResponse` → `returnval` → `about` 에
      API 2.0 부터 필수인 `apiType` / `apiVersion` 이 있다.
  (2) SOAP Fault 인데 detail 안 요소가 `urn:vim25` / `urn:internalvim25` 네임스페이스다.
      (일반 SOAP Fault 와 구별되는 지점이 **네임스페이스**이며 문자열 검색이 아니다.)

이 파일은 Positive(§17)와 False Positive(§18)를 모두 고정한다. 네트워크 0 —
`http_post_soap` 를 monkeypatch 한다.
"""
from __future__ import annotations

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

import precheck_bundle as pb  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "esxi"
LAB_SERVICE_CONTENT = (FIXTURES / "lab" / "esxi_7_0_3_service_content.xml").read_bytes()


def _post_returning(ok, err, payload):
    def fake(url, body, timeout, verify=False, extra_headers=None,
             content_type=None, max_bytes=None):
        return ok, err, payload
    return fake


def _probe_with(body, status=200, ok=True, err=None):
    payload = None if body is None and status is None else {
        "status_code": status, "body": body,
    }
    with patch.object(pb, "http_post_soap", _post_returning(ok, err, payload)):
        return pb.probe_esxi("192.0.2.10", 443, 6.0)


# ═══════════════════════════════════════════════════════════════════════════
# §5 — 실제로 보내는 요청 (추측이 아니라 pyVmomi 직렬화 결과와 동일해야 한다)
# ═══════════════════════════════════════════════════════════════════════════
def test_request_is_retrieve_service_content_soap_post():
    seen = {}

    def fake(url, body, timeout, verify=False, extra_headers=None,
             content_type=None, max_bytes=None):
        seen.update(url=url, body=body, timeout=timeout, verify=verify,
                    headers=extra_headers or {}, content_type=content_type,
                    max_bytes=max_bytes)
        return True, None, {"status_code": 200, "body": LAB_SERVICE_CONTENT}

    with patch.object(pb, "http_post_soap", fake):
        ok, _err, _facts = pb.probe_esxi("192.0.2.10", 443, 6.0)

    assert ok is True
    assert seen["url"] == "https://192.0.2.10:443/sdk"
    text = seen["body"].decode("utf-8")
    assert '<RetrieveServiceContent xmlns="urn:vim25">' in text
    assert '<_this versionId="6.0" type="ServiceInstance">ServiceInstance</_this>' in text
    # vim25 는 SOAP 1.1 — WS-Management(SOAP 1.2) 와 Content-Type 이 다르다
    assert seen["content_type"] == "text/xml; charset=UTF-8"
    assert seen["headers"].get("SOAPAction") == '"urn:vim25/6.0"'
    # ServiceContent 는 Identify 응답보다 커서 상한을 따로 준다
    assert seen["max_bytes"] > pb._IDENTIFY_MAX_BYTES


def test_request_carries_no_credentials():
    """§9 — Protocol Probe 는 자격증명을 보내지 않는다."""
    seen = {}

    def fake(url, body, timeout, verify=False, extra_headers=None,
             content_type=None, max_bytes=None):
        seen.update(body=body, headers=extra_headers or {})
        return True, None, {"status_code": 200, "body": LAB_SERVICE_CONTENT}

    with patch.object(pb, "http_post_soap", fake):
        pb.probe_esxi("192.0.2.10", 443, 6.0)

    header_names = {k.lower() for k in seen["headers"]}
    assert "authorization" not in header_names
    assert "cookie" not in header_names
    blob = seen["body"].decode("utf-8").lower()
    for secret in ("password", "passwd", "sessionid", "login", "authorization"):
        assert secret not in blob, "요청 본문에 자격증명 관련 문자열: {0}".format(secret)


def test_tls_policy_unchanged():
    """§12 — 인증서 검증 정책은 이번 Phase 에서 바꾸지 않는다 (호출부 verify 를 그대로 전달)."""
    seen = {}

    def fake(url, body, timeout, verify=False, extra_headers=None,
             content_type=None, max_bytes=None):
        seen["verify"] = verify
        seen["timeout"] = timeout
        return True, None, {"status_code": 200, "body": LAB_SERVICE_CONTENT}

    with patch.object(pb, "http_post_soap", fake):
        pb.probe_esxi("192.0.2.10", 443, 30.0, verify=False)
    assert seen["verify"] is False
    assert seen["timeout"] == 30.0


def test_no_retry_on_non_vsphere_body():
    """§14 — Retry 를 새로 만들지 않는다. 요청은 정확히 1회."""
    calls = {"n": 0}

    def fake(url, body, timeout, verify=False, extra_headers=None,
             content_type=None, max_bytes=None):
        calls["n"] += 1
        return True, None, {"status_code": 200, "body": b"<html><body>hi</body></html>"}

    with patch.object(pb, "http_post_soap", fake):
        ok, _err, _facts = pb.probe_esxi("192.0.2.10", 443, 6.0)
    assert ok is False
    assert calls["n"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# §17 Positive — 실제 ServiceContent 응답
# ═══════════════════════════════════════════════════════════════════════════
def test_lab_service_content_accepted():
    ok, err, facts = _probe_with(LAB_SERVICE_CONTENT)
    assert ok is True and err is None
    assert facts["vsphere_endpoint"] == "https://192.0.2.10:443/sdk"
    # HTTP 200 이면 종전과 동일하게 root_status_code 를 싣지 않는다 (baseline 정합)
    assert "root_status_code" not in facts


@pytest.mark.parametrize("name", [
    "lab/esxi_7_0_3_service_content.xml",
    "synthetic/esxi_6_0_0_service_content.xml",
    "synthetic/esxi_6_7_0_service_content.xml",
    "synthetic/esxi_8_0_3_service_content.xml",
])
def test_service_content_across_versions(name):
    """§11 — 특정 API 버전 하나에 종속되지 않는다.

    lab/ 만 실측 AboutInfo 기반이고 synthetic/ 은 합성이다 — 합성 통과를
    "해당 ESXi 버전 검증 완료" 로 읽지 않는다. 구조 독립성만 고정한다.
    """
    raw = (FIXTURES / name).read_bytes()
    ok, facts, why = pb.parse_service_content(raw)
    assert ok is True, why
    assert facts["evidence"] == "service_content"
    assert facts["api_type"] == "HostAgent"
    assert facts["api_version"]


def test_namespace_prefix_variation_accepted():
    """§17-3 — 접두사 표기가 달라도 네임스페이스가 맞으면 통과 (파서 기준 판정)."""
    raw = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<env:Envelope xmlns:env="http://schemas.xmlsoap.org/soap/envelope/"'
        ' xmlns:vim="urn:vim25">'
        "<env:Body><vim:RetrieveServiceContentResponse><vim:returnval>"
        '<vim:rootFolder type="Folder">ha-folder-root</vim:rootFolder>'
        "<vim:about><vim:name>VMware ESXi</vim:name>"
        "<vim:apiType>HostAgent</vim:apiType>"
        "<vim:apiVersion>7.0.3.0</vim:apiVersion></vim:about>"
        "</vim:returnval></vim:RetrieveServiceContentResponse></env:Body>"
        "</env:Envelope>"
    ).encode("utf-8")
    ok, facts, why = pb.parse_service_content(raw)
    assert ok is True, why
    assert facts["api_version"] == "7.0.3.0"


def test_non_200_keeps_status_as_evidence():
    """§16 — status 는 판정 근거가 아니라 Evidence. 본문이 ServiceContent 면 통과한다."""
    ok, err, facts = _probe_with(LAB_SERVICE_CONTENT, status=500, ok=False, err="HTTP 500")
    assert ok is True and err is None
    assert facts["root_status_code"] == 500


@pytest.mark.parametrize("name", [
    "synthetic/vsphere_fault_vim25.xml",
    "synthetic/vsphere_fault_internalvim25.xml",
])
def test_vsphere_structured_fault_is_protocol_evidence(name):
    """§8 — vSphere 고유 네임스페이스로 직렬화된 Fault 는 endpoint 존재의 직접 증거."""
    raw = (FIXTURES / name).read_bytes()
    ok, facts, why = pb.parse_service_content(raw)
    assert ok is True, why
    assert facts["evidence"] == "vim25_fault"
    assert facts["fault"]


# ═══════════════════════════════════════════════════════════════════════════
# §18 False Positive — 아래 17종은 절대 vSphere 로 판정되면 안 된다
# ═══════════════════════════════════════════════════════════════════════════
_GENERIC_SOAP = (
    '<?xml version="1.0"?>'
    '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
    "<soapenv:Body><GetWeatherResponse xmlns=\"http://example.invalid/weather\">"
    "<Temperature>21</Temperature></GetWeatherResponse>"
    "</soapenv:Body></soapenv:Envelope>"
).encode("utf-8")

_FALSE_POSITIVE_BODIES = [
    ("일반 HTTPS HTML", b"<html><head><title>nginx</title></head><body>ok</body></html>"),
    ("일반 JSON", b'{"status":"ok","service":"api"}'),
    ("일반 XML", b"<?xml version='1.0'?><config><item>1</item></config>"),
    ("빈 SOAP Envelope",
     b'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
     b"<soapenv:Body/></soapenv:Envelope>"),
    ("다른 SOAP 서비스 Response", _GENERIC_SOAP),
    ("일반 SOAP Fault", (FIXTURES / "synthetic" / "generic_soap_fault_NEGATIVE.xml").read_bytes()),
    ("잘린 XML",
     b'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
     b'<soapenv:Body><RetrieveServiceContentResponse xmlns="urn:vim25"><returnval>'),
    ("vSphere 문자열만 있는 일반 XML",
     b"<?xml version='1.0'?><result><note>urn:vim25 RetrieveServiceContentResponse "
     b"ServiceInstance VMware ESXi apiType HostAgent</note></result>"),
    ("Envelope 는 맞지만 다른 vim25 응답",
     b'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
     b'<soapenv:Body><LoginResponse xmlns="urn:vim25"><returnval/></LoginResponse>'
     b"</soapenv:Body></soapenv:Envelope>"),
    ("ServiceContent 인데 about 없음",
     b'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
     b'<soapenv:Body><RetrieveServiceContentResponse xmlns="urn:vim25"><returnval>'
     b'<rootFolder type="Folder">ha-folder-root</rootFolder>'
     b"</returnval></RetrieveServiceContentResponse></soapenv:Body></soapenv:Envelope>"),
    ("about 인데 apiType 없음",
     b'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
     b'<soapenv:Body><RetrieveServiceContentResponse xmlns="urn:vim25"><returnval>'
     b"<about><name>VMware ESXi</name><apiVersion>7.0.3.0</apiVersion></about>"
     b"</returnval></RetrieveServiceContentResponse></soapenv:Body></soapenv:Envelope>"),
    ("about 인데 apiVersion 공백",
     b'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
     b'<soapenv:Body><RetrieveServiceContentResponse xmlns="urn:vim25"><returnval>'
     b"<about><apiType>HostAgent</apiType><apiVersion>   </apiVersion></about>"
     b"</returnval></RetrieveServiceContentResponse></soapenv:Body></soapenv:Envelope>"),
    ("네임스페이스 없는 RetrieveServiceContentResponse",
     b'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
     b"<soapenv:Body><RetrieveServiceContentResponse><returnval>"
     b"<about><apiType>HostAgent</apiType><apiVersion>7.0.3.0</apiVersion></about>"
     b"</returnval></RetrieveServiceContentResponse></soapenv:Body></soapenv:Envelope>"),
]


@pytest.mark.parametrize("label,body", _FALSE_POSITIVE_BODIES,
                         ids=[label for label, _ in _FALSE_POSITIVE_BODIES])
def test_false_positive_bodies_rejected(label, body):
    ok, facts, _why = pb.parse_service_content(body)
    assert ok is False, "{0} 를 vSphere 로 오판했다".format(label)
    assert facts is None


@pytest.mark.parametrize("status", [200, 301, 302, 401, 403, 404, 405, 500, 503])
def test_status_alone_never_confirms_vsphere(status):
    """§7 — HTTP status 는 Evidence 일 수 있어도 vSphere Protocol Identity 가 아니다."""
    ok, err, facts = _probe_with(
        b"<html><body>gateway</body></html>", status=status,
        ok=(status == 200), err=None if status == 200 else "HTTP {0}".format(status))
    assert ok is False, "HTTP {0} 만으로 통과하면 안 된다".format(status)
    assert facts is None
    assert "HTTP {0}".format(status) in err


def test_status_alone_with_empty_body_rejected():
    ok, err, facts = _probe_with(b"", status=200, ok=True)
    assert ok is False and facts is None
    assert err


# ═══════════════════════════════════════════════════════════════════════════
# 연결 자체 실패 (본문 없음) — 종전과 동일하게 원본 오류를 보존한다
# ═══════════════════════════════════════════════════════════════════════════
def test_timeout_reports_original_error():
    with patch.object(pb, "http_post_soap",
                      _post_returning(False, "요청 시간 초과 (timeout=6.0s)", None)):
        ok, err, facts = pb.probe_esxi("192.0.2.10", 443, 6.0)
    assert ok is False and facts is None
    assert "시간 초과" in err


def test_tls_error_reports_original_error():
    with patch.object(pb, "http_post_soap",
                      _post_returning(False, "연결 실패: CERTIFICATE_VERIFY_FAILED", None)):
        ok, err, facts = pb.probe_esxi("192.0.2.10", 443, 6.0)
    assert ok is False and facts is None
    assert "연결 실패" in err


def test_failure_detail_has_no_raw_soap_dump():
    """§16 — Raw SOAP 전체를 detail 로 흘리지 않는다."""
    big = (b'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
           b"<soapenv:Body>" + b"<pad>x</pad>" * 500 + b"</soapenv:Body></soapenv:Envelope>")
    ok, err, _facts = _probe_with(big, status=200)
    assert ok is False
    assert len(err) < 300, "실패 사유가 본문 덤프가 되면 안 된다"
    assert "<pad>" not in err


def test_oversized_body_rejected_before_parsing():
    huge = b"<a>" + b"x" * (pb._SERVICE_CONTENT_MAX_BYTES + 1) + b"</a>"
    ok, facts, why = pb.parse_service_content(huge)
    assert ok is False and facts is None
    assert "상한" in why
