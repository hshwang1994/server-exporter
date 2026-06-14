"""redfish Round 8 robustness/correctness 회귀 (string-method 패턴 클래스).

  - _str 헬퍼 (문자열 메서드 전 비-str 방어)
  - #0 _classify_rmc_label 비-str manager_id (.lower UNWRAPPED P0)
  - #1 gather_memory name trailing whitespace 정규화
  - #2 gather_bmc 비-str Gateway
"""
from __future__ import annotations

import pytest

import emulator_harness as H

rg = H.rg


def _fake_get(tree):
    def fake(bmc_ip, path, username, password, timeout, verify_ssl):
        return (200, tree[path], None) if path in tree else (404, {}, "HTTP 404: Not Found")
    return fake


def test_str_helper():
    assert rg._str("Abc") == "Abc"
    assert rg._str(123) == "" and rg._str(None) == "" and rg._str({"a": 1}) == "" and rg._str([1]) == ""


def test_classify_rmc_label_non_str_manager_id():
    """manager_layout truthy + 비-str Id → (id or '').lower() AttributeError 방어 (UNWRAPPED P0)."""
    r = rg._classify_rmc_label("/redfish/v1/Managers/1", 123, "rmc_primary")  # 가드 전: int.lower crash
    assert r is None or isinstance(r, str)
    # 정상 str id 동작 불변
    r2 = rg._classify_rmc_label("/redfish/v1/Managers/RMC", "RMC", "rmc_primary")
    assert r2 is None or isinstance(r2, str)


def test_gather_memory_name_stripped(monkeypatch):
    """Cisco trailing whitespace Name → _strip_or_none 으로 정규화(processors 와 일관)."""
    monkeypatch.setattr(rg, "_get", _fake_get({
        "Systems/1/Memory": {"Members": [{"@odata.id": "/redfish/v1/Systems/1/Memory/d1"}]},
        "Systems/1/Memory/d1": {"Id": "d1", "Name": "  DIMM_A1  ", "CapacityMiB": 16384},
    }))
    out, errs = rg.gather_memory("1.2.3.4", "/redfish/v1/Systems/1", "u", "p", 5, False)
    assert out["slots"][0]["name"] == "DIMM_A1"  # 가드 전: '  DIMM_A1  '


def test_gather_bmc_non_str_gateway(monkeypatch):
    """IPv4Addresses[].Gateway 가 비-str(dict) → bmc_gateways 에 비-str 누적 안 함."""
    monkeypatch.setattr(rg, "_get", _fake_get({
        "Managers/1": {"Id": "1", "EthernetInterfaces": {"@odata.id": "/redfish/v1/Managers/1/EthernetInterfaces"}},
        "Managers/1/EthernetInterfaces": {"Members": [{"@odata.id": "/redfish/v1/Managers/1/EthernetInterfaces/1"}]},
        "Managers/1/EthernetInterfaces/1": {"IPv4Addresses": [
            {"Address": "10.0.0.5", "Gateway": {"bad": "dict"}}]},  # 비-str Gateway
    }))
    data, errs = rg.gather_bmc("1.2.3.4", "/redfish/v1/Managers/1", "hpe", "u", "p", 5, False)
    gws = (data or {}).get("default_gateways") or data.get("gateways") or []
    assert all(isinstance(g, str) for g in gws)  # 비-str gateway 미누적
