"""Regression for precheck_bundle.probe_redfish.

배경: probe_redfish가 ServiceRoot 401/403/503 응답을 "Redfish 미지원"으로
오판정 → 통신 정상이고 인증만 필요한 BMC (HPE iLO5/6 일부, Lenovo XCC 일부)
를 차단했음. probe_esxi (line 260) 의 status_code 허용 패턴을 따라 정정.

본 테스트는:
  - 200/JSON       → ok + probe_facts (redfish_version, systems_uri)
  - 401/403/503    → ok + root_status_code, requires_auth_at_root (회귀 차단)
  - 404/timeout/SSL → fail (실제 미지원/장애 — false positive 방지)
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "common" / "library"))

# Windows 환경에서 ansible import 불가 (grp/pwd 부재) — top-level import 회피용 stub.
# probe_redfish 자체는 ansible API 미사용, http_get / urllib만 사용.
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object  # placeholder, 호출되지 않음
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


def test_service_root_200_returns_probe_facts():
    payload = {
        "status_code": 200,
        "json": {
            "RedfishVersion": "1.13.0",
            "Product": "iDRAC",
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
        },
    }
    with patch.object(precheck_bundle, "http_get", _http_get_returning(True, None, payload)):
        ok, err, facts = precheck_bundle.probe_redfish("10.1.1.1", 443, 6.0)
    assert ok is True
    assert err is None
    assert facts["redfish_version"] == "1.13.0"
    assert facts["product"] == "iDRAC"
    assert facts["systems_uri"] == "/redfish/v1/Systems"


def test_service_root_401_treated_as_supported():
    """회귀 차단: 401 = '인증 필요한 Redfish 서비스 살아있음' (미지원 아님)."""
    payload = {"status_code": 401, "json": None}
    with patch.object(precheck_bundle, "http_get", _http_get_returning(False, "HTTP 401", payload)):
        ok, _, facts = precheck_bundle.probe_redfish("10.1.1.1", 443, 6.0)
    assert ok is True
    assert facts["root_status_code"] == 401
    assert facts["requires_auth_at_root"] is True


def test_service_root_403_treated_as_supported():
    payload = {"status_code": 403, "json": None}
    with patch.object(precheck_bundle, "http_get", _http_get_returning(False, "HTTP 403", payload)):
        ok, _, facts = precheck_bundle.probe_redfish("10.1.1.1", 443, 6.0)
    assert ok is True
    assert facts["root_status_code"] == 403
    assert facts["requires_auth_at_root"] is True


def test_service_root_503_treated_as_supported():
    """503 = BMC 일시 과부하/부팅 직후 — 본 수집에서 재시도. 미지원 아님."""
    payload = {"status_code": 503, "json": None}
    with patch.object(precheck_bundle, "http_get", _http_get_returning(False, "HTTP 503", payload)):
        ok, _, facts = precheck_bundle.probe_redfish("10.1.1.1", 443, 6.0)
    assert ok is True
    assert facts["root_status_code"] == 503
    assert facts["requires_auth_at_root"] is False


def test_service_root_406_treated_as_supported():
    """회귀 차단 (cycle 2026-04-30): 406 = Accept 헤더 협상 불일치.
    HPE iLO 펌웨어 ServiceRoot RedfishVersion 1.17.0 등 일부 BMC가 Accept 헤더
    누락된 요청을 거부. http_get에 Accept/OData-Version 명시 + 406도 supported로 분류.
    """
    payload = {"status_code": 406, "json": None}
    with patch.object(precheck_bundle, "http_get", _http_get_returning(False, "HTTP 406", payload)):
        ok, _, facts = precheck_bundle.probe_redfish("10.1.1.1", 443, 6.0)
    assert ok is True
    assert facts["root_status_code"] == 406
    assert facts["requires_auth_at_root"] is False
    assert facts["header_negotiation_issue"] is True


def test_service_root_405_treated_as_supported():
    """405 = Method Not Allowed. Redfish 서비스 살아있고 GET 제한이 있는 드문 펌웨어."""
    payload = {"status_code": 405, "json": None}
    with patch.object(precheck_bundle, "http_get", _http_get_returning(False, "HTTP 405", payload)):
        ok, _, facts = precheck_bundle.probe_redfish("10.1.1.1", 443, 6.0)
    assert ok is True
    assert facts["root_status_code"] == 405
    assert facts["header_negotiation_issue"] is True


def test_service_root_404_real_unsupported():
    """404 = /redfish/v1/ 자체가 없음 → 진짜 Redfish 미지원."""
    payload = {"status_code": 404, "json": None}
    with patch.object(precheck_bundle, "http_get", _http_get_returning(False, "HTTP 404", payload)):
        ok, err, facts = precheck_bundle.probe_redfish("10.1.1.1", 443, 6.0)
    assert ok is False
    assert err == "HTTP 404"
    assert facts is None


def test_service_root_timeout_real_failure():
    """timeout = 실 통신 장애. payload=None."""
    with patch.object(precheck_bundle, "http_get", _http_get_returning(False, "요청 시간 초과 (timeout=6.0s)", None)):
        ok, err, facts = precheck_bundle.probe_redfish("10.1.1.1", 443, 6.0)
    assert ok is False
    assert "시간 초과" in err
    assert facts is None


def test_service_root_ssl_failure():
    """SSL handshake 실패 = 실 장애."""
    with patch.object(precheck_bundle, "http_get", _http_get_returning(False, "SSL: WRONG_VERSION_NUMBER", None)):
        ok, err, facts = precheck_bundle.probe_redfish("10.1.1.1", 443, 6.0)
    assert ok is False
    assert err.startswith("SSL")
    assert facts is None


def test_service_root_500_real_failure():
    """500 = BMC 내부 오류, 응답 형태 깨짐 → 미지원 처리 (인증 fallback도 무의미)."""
    payload = {"status_code": 500, "json": None}
    with patch.object(precheck_bundle, "http_get", _http_get_returning(False, "HTTP 500", payload)):
        ok, _, _ = precheck_bundle.probe_redfish("10.1.1.1", 443, 6.0)
    assert ok is False
