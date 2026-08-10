"""probe_redfish — Redfish Protocol 판정 (Phase 4-A 이후).

이력
----
- 종전(~Phase 3-B): HTTP 2xx 면 **본문을 보지 않고** 성공. 추가로 401/403/405/406/503 을
  "BMC 가 Redfish 를 응답한다는 증거" 로 보고 성공 처리했다.
  → 443 에 뜬 일반 HTTPS 서버가 200 + HTML/JSON 을 돌려줘도 Redfish 로 판정됐다.
- Phase 4-A (2026-08-10): `/redfish/v1/` **응답 본문이 ServiceRoot 인지** 구조로 검증한다.
  HTTP status 는 실패 evidence 로만 쓰고 성공 근거로는 쓰지 않는다.

최소 성공 조건 (규격 + 저장소 fixture 38개 실측 양쪽 근거):
  1. JSON object
  2. `@odata.type` 이 `#ServiceRoot.` 로 시작
  3. `@odata.id` 가 `/redfish/v1` 또는 `/redfish/v1/`
  4. `RedfishVersion` 이 비어 있지 않은 문자열 (ServiceRoot_v1.xml Nullable="false")

vendor fixture 회귀는 `test_redfish_service_root_fixtures.py` 가 전수 검증한다.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "common" / "library"))

# Windows 환경에서 ansible import 불가 (grp/pwd 부재) — top-level import 회피용 stub.
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


SERVICE_ROOT = {
    "@odata.context": "/redfish/v1/$metadata#ServiceRoot.ServiceRoot",
    "@odata.id": "/redfish/v1",
    "@odata.type": "#ServiceRoot.v1_15_0.ServiceRoot",
    "Id": "RootService",
    "Name": "Root Service",
    "RedfishVersion": "1.17.0",
    "Product": "Integrated Dell Remote Access Controller",
    "Systems": {"@odata.id": "/redfish/v1/Systems"},
    "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
    "Managers": {"@odata.id": "/redfish/v1/Managers"},
}


def _http_get_returning(ok, err, payload):
    def fake(url, timeout, verify=False, auth=None):
        return ok, err, payload

    return fake


def _resp(status, json_body, ok=True):
    return ok, None if ok else "HTTP {0}".format(status), {
        "status_code": status, "json": json_body, "headers": {},
    }


# ═══════════════════════════════════════════════════════════════════════════
# Positive — 실제 ServiceRoot
# ═══════════════════════════════════════════════════════════════════════════
def test_service_root_accepted_and_returns_probe_facts():
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(*_resp(200, SERVICE_ROOT))):
        ok, err, facts = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is True, err
    assert facts["redfish_version"] == "1.17.0"
    assert facts["systems_uri"] == "/redfish/v1/Systems"
    assert facts["product"] == "Integrated Dell Remote Access Controller"


@pytest.mark.parametrize("odata_id", ["/redfish/v1", "/redfish/v1/"])
def test_trailing_slash_variants_accepted(odata_id):
    """실측상 vendor 마다 @odata.id 의 trailing slash 가 갈린다 (22 vs 6)."""
    body = dict(SERVICE_ROOT, **{"@odata.id": odata_id})
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(*_resp(200, body))):
        ok, err, _f = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is True, err


@pytest.mark.parametrize("version", ["1.0.0", "1.6.0", "1.17.0", "1.22.1"])
def test_various_redfish_versions_accepted(version):
    body = dict(SERVICE_ROOT, RedfishVersion=version)
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(*_resp(200, body))):
        ok, err, facts = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is True, err
    assert facts["redfish_version"] == version


@pytest.mark.parametrize("odata_type", [
    "#ServiceRoot.v1_0_2.ServiceRoot",
    "#ServiceRoot.v1_5_1.ServiceRoot",
    "#ServiceRoot.v1_16_1.ServiceRoot",
])
def test_various_serviceroot_schema_versions_accepted(odata_type):
    """ServiceRoot 스키마 버전 차이는 허용한다."""
    body = dict(SERVICE_ROOT, **{"@odata.type": odata_type})
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(*_resp(200, body))):
        ok, err, _f = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is True, err


def test_probe_sends_no_credentials():
    """Protocol Probe 는 Credential Probe 가 아니다."""
    seen = {}

    def fake(url, timeout, verify=False, auth=None):
        seen.update(url=url, auth=auth, verify=verify)
        return _resp(200, SERVICE_ROOT)

    with patch.object(precheck_bundle, "http_get", fake):
        precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)

    assert seen["url"] == "https://192.0.2.10:443/redfish/v1/"
    assert seen["auth"] is None
    assert seen["verify"] is False, "기존 BMC TLS 호환 정책(verify=False) 유지"


# ═══════════════════════════════════════════════════════════════════════════
# False Positive 방지 (§16) — ServiceRoot 가 아니면 전부 거부
# ═══════════════════════════════════════════════════════════════════════════
_GENERIC_ODATA = {
    "@odata.context": "/api/$metadata#Products",
    "@odata.id": "/api/Products(1)",
    "@odata.type": "#Product.v1_0_0.Product",
    "Name": "Widget",
}
_LOOKALIKE = {   # ServiceRoot 비슷하지만 최소 조건 미달
    "@odata.id": "/redfish/v1",
    "Id": "RootService",
    "Name": "Root Service",
    "RedfishVersion": "1.6.0",
}


@pytest.mark.parametrize("body,label", [
    (None, "HTML 등 JSON 아님 (파싱 실패)"),
    ({}, "빈 JSON"),
    ({"status": "ok", "version": "1.0"}, "일반 JSON"),
    (_GENERIC_ODATA, "Redfish 와 무관한 OData JSON"),
    ([1, 2, 3], "JSON Array"),
    ("errorstring", "JSON 문자열"),
    (_LOOKALIKE, "@odata.type 없는 ServiceRoot 유사 JSON"),
    (dict(SERVICE_ROOT, **{"@odata.id": "/api/v1"}), "@odata.id 불일치"),
    (dict(SERVICE_ROOT, RedfishVersion=""), "RedfishVersion 빈 문자열"),
    ({k: v for k, v in SERVICE_ROOT.items() if k != "RedfishVersion"},
     "RedfishVersion 부재"),
])
def test_non_serviceroot_body_rejected(body, label):
    """HTTP 200 이어도 본문이 ServiceRoot 가 아니면 Redfish 가 아니다."""
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(*_resp(200, body))):
        ok, err, facts = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is False, "{0} 을 Redfish 로 오판하면 안 된다".format(label)
    assert facts is None
    assert "ServiceRoot 아님" in err


@pytest.mark.parametrize("status", [401, 403, 404, 405, 406, 500, 503])
def test_http_status_alone_never_means_redfish(status):
    """종전 whitelist(401/403/405/406/503)면 통과했을 status 를 전부 거부."""
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(*_resp(status, None, ok=False))):
        ok, err, facts = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is False, "HTTP {0} 만으로 Redfish 판정 금지".format(status)
    assert facts is None
    assert str(status) in err, "어떤 status 였는지는 evidence 로 남긴다"


def test_probe_never_sets_auth_success():
    """401 을 받아도 Protocol Probe 는 auth_success 를 건드리지 않는다."""
    result = precheck_bundle._init_result("redfish", [443])
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(*_resp(401, None, ok=False))):
        ok, _err, _f = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is False
    assert result["auth_success"] is None, "Protocol Probe 는 인증을 시도하지 않는다"


# ═══════════════════════════════════════════════════════════════════════════
# Transport 실패 / retry 정책 (기존 유지)
# ═══════════════════════════════════════════════════════════════════════════
def test_timeout_real_failure():
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(False, "요청 시간 초과", None)):
        ok, err, facts = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is False and facts is None
    assert "시간 초과" in err


def test_ssl_failure():
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(False, "연결 실패: TLS handshake 오류", None)):
        ok, err, facts = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is False and facts is None
    assert "TLS" in err


def test_retry_only_when_no_payload(monkeypatch):
    """payload=None 일 때만 1회 retry (기존 정책 유지)."""
    monkeypatch.setattr(precheck_bundle, "_time_sleep_patch_target", None, raising=False)
    calls = {"n": 0}

    def fake(url, timeout, verify=False, auth=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, "요청 시간 초과", None      # payload None → retry 대상
        return _resp(200, SERVICE_ROOT)

    monkeypatch.setattr("time.sleep", lambda _s: None)
    with patch.object(precheck_bundle, "http_get", fake):
        ok, err, facts = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is True, err
    assert calls["n"] == 2
    assert facts["retry_count"] == 1


def test_no_retry_when_http_response_present(monkeypatch):
    """HTTP 응답이 온 status 는 재시도하지 않는다 (기존 정책 유지)."""
    calls = {"n": 0}

    def fake(url, timeout, verify=False, auth=None):
        calls["n"] += 1
        return _resp(404, None, ok=False)

    monkeypatch.setattr("time.sleep", lambda _s: None)
    with patch.object(precheck_bundle, "http_get", fake):
        ok, _err, _f = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is False
    assert calls["n"] == 1, "HTTP 응답이 왔으면 retry 없음"


def test_non_serviceroot_200_does_not_retry(monkeypatch):
    """200 이지만 ServiceRoot 가 아닌 경우도 재시도하지 않는다 (retry 정책 불변)."""
    calls = {"n": 0}

    def fake(url, timeout, verify=False, auth=None):
        calls["n"] += 1
        return _resp(200, {"hello": "world"})

    monkeypatch.setattr("time.sleep", lambda _s: None)
    with patch.object(precheck_bundle, "http_get", fake):
        ok, _err, _f = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert ok is False
    assert calls["n"] == 1


def test_error_evidence_is_length_bounded():
    """Raw body 를 통째로 흘리지 않는다."""
    huge = {"@odata.type": "#Something." + "x" * 5000}
    with patch.object(precheck_bundle, "http_get",
                      _http_get_returning(*_resp(200, huge))):
        _ok, err, _f = precheck_bundle.probe_redfish("192.0.2.10", 443, 5.0)
    assert len(err) < 200, "evidence 길이 제한"
