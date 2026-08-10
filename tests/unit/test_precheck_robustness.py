"""precheck_bundle.py fault-injection 회귀 (rule 27 / rule 95 R1 #2).

배경 (audit 2026-06-09):
    precheck 는 모든 gather 의 첫 관문이다. 대부분 IPv6 듀얼스택 / timeout / 예외 처리가
    견고하나, _try_redfish_auth 의 Systems Members[0] 접근이 비-dict 멤버(예: [null])에서
    AttributeError 로 모듈 전체를 죽일 수 있다. 본 테스트는 그 crash 를 드러내고(RED) 가드
    후 graceful(GREEN)을 고정한다.

검증 가능: http_get 을 monkeypatch 해 네트워크 0 (오프라인).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "common" / "library"))

# ansible stub (redfish unit test 와 동일 패턴 — AnsibleModule import 충족)
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


def _fresh_result():
    r = pb._init_result("redfish", [443])
    r["probe_facts"] = {}
    return r


def _patch_systems_response(monkeypatch, members):
    """http_get 를 Systems 응답 stub 으로 교체 (네트워크 0)."""
    def fake_get(url, timeout, verify=False, auth=None):
        return True, None, {"status_code": 200, "json": {"Members": members}}
    monkeypatch.setattr(pb, "http_get", fake_get)


def test_auth_systems_members_null_entry_does_not_crash(monkeypatch):
    """Systems Members 가 [null] → members[0].get AttributeError 방어."""
    _patch_systems_response(monkeypatch, [None])
    result = _fresh_result()
    ok = pb._try_redfish_auth("10.0.0.1", 443, "u", "p", 8.0, False, result)  # 가드 전: AttributeError
    assert ok is True
    assert result["auth_success"] is True
    # 비-dict 멤버는 first_system_uri 추출 불가 — 키 부재가 정상 (crash 아님)
    assert "first_system_uri" not in result["probe_facts"]


def test_auth_systems_members_string_entry_does_not_crash(monkeypatch):
    """Members 가 ['/redfish/...'] (문자열) → 역시 crash 없이 무시."""
    _patch_systems_response(monkeypatch, ["/redfish/v1/Systems/1"])
    result = _fresh_result()
    ok = pb._try_redfish_auth("10.0.0.1", 443, "u", "p", 8.0, False, result)
    assert ok is True and result["auth_success"] is True


def test_auth_wellformed_member_extracts_uri(monkeypatch):
    """정상 dict 멤버는 first_system_uri 추출 (가드가 정상 경로 불변)."""
    _patch_systems_response(monkeypatch, [{"@odata.id": "/redfish/v1/Systems/1"}])
    result = _fresh_result()
    ok = pb._try_redfish_auth("10.0.0.1", 443, "u", "p", 8.0, False, result)
    assert ok is True
    assert result["probe_facts"]["first_system_uri"] == "/redfish/v1/Systems/1"


def test_probe_redfish_non_dict_json_does_not_crash(monkeypatch):
    """ServiceRoot 가 비-dict JSON('error' 등) 반환 → AttributeError 없이 graceful.

    2026-08-10 (Phase 4-A): 종전에는 crash 만 막고 ok=True 로 통과시켰다. 이제 본문이
    ServiceRoot 인지 구조로 판정하므로 비-dict 는 **Redfish 아님**으로 거부한다
    (crash 방어는 그대로 유효 — 예외 없이 판정 결과만 돌려준다).
    """
    monkeypatch.setattr(pb, "http_get",
                        lambda *a, **k: (True, None, {"status_code": 200, "json": "errorstring"}))
    ok, err, facts = pb.probe_redfish("10.0.0.1", 443, 5)  # 가드 전: str.get AttributeError
    assert ok is False and facts is None
    assert "ServiceRoot 아님" in err


def test_auth_non_dict_json_does_not_crash(monkeypatch):
    """Systems 가 비-dict JSON → json_data.get('Members') AttributeError 방어 (UNWRAPPED P0)."""
    monkeypatch.setattr(pb, "http_get",
                        lambda *a, **k: (True, None, {"status_code": 200, "json": 12345}))
    result = _fresh_result()
    ok = pb._try_redfish_auth("10.0.0.1", 443, "u", "p", 8.0, False, result)  # 가드 전: int.get
    assert ok is True and result["auth_success"] is True


def test_tcp_check_bad_host_returns_false_not_crash():
    """tcp_check 가 해석 불가 host 에 DNS 실패로 graceful (crash 아님)."""
    ok, err = pb.tcp_check("nonexistent.invalid.", 443, 0.5)
    assert ok is False and err
