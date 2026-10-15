"""redfish 기타 robustness/correctness 회귀 (Round 1 #13/#21/#22/#23).

  - #23 _p('/redfish/v1/') → '' → _get ServiceRoot 오인 방지
  - #13 firmware @odata.id 후행 슬래시 → 빈 fw_id 방지
  - #21 power watt 필드 int 통일 (BMC 문자열 watt 타입 불일치)
  - #22 FC WWPN 이 MAC(6 octet)으로 잘못 fallback 되지 않음
"""
from __future__ import annotations

import pytest

import emulator_harness as H

rg = H.rg


def _fake_get_from_tree(tree):
    def fake(bmc_ip, path, username, password, timeout, verify_ssl):
        return (200, tree[path], None) if path in tree else (404, {}, "HTTP 404: Not Found")
    return fake


# ── #23 _p 빈 path 무효화 ──
def test_p_empty_path_is_invalidated():
    assert rg._p("/redfish/v1/") == "__invalid_odata_id__"
    assert rg._p("/redfish/v1") == "__invalid_odata_id__"
    # 정상 path 불변
    assert rg._p("/redfish/v1/Systems/1") == "Systems/1"
    assert rg._p("/redfish/v1/Chassis/1/Power") == "Chassis/1/Power"


# ── #13 firmware 후행 슬래시 id ──
def test_firmware_trailing_slash_id(monkeypatch):
    monkeypatch.setattr(rg, "_get", _fake_get_from_tree({
        "UpdateService/FirmwareInventory": {"Members": [
            {"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/BMC-Pending/",
             "Name": "BMC", "Version": "1.0"},
        ]},
    }))
    fw_list, errors = rg.gather_firmware("1.2.3.4", "u", "p", 5, False)
    assert fw_list and fw_list[0]["id"] == "BMC-Pending"  # 가드 전: '' (후행 슬래시)


# ── #21 power watt int 통일 ──
def test_power_string_watts_cast_to_int(monkeypatch):
    monkeypatch.setattr(rg, "_get", _fake_get_from_tree({
        "Chassis/1/Power": {"PowerControl": [{
            "PowerConsumedWatts": "1500",
            "PowerMetrics": {"MinConsumedWatts": "100", "AverageConsumedWatts": "200",
                             "MaxConsumedWatts": "300", "IntervalInMin": 5},
        }]},
    }))
    result, errors = rg.gather_power("1.2.3.4", "/redfish/v1/Chassis/1", "u", "p", 5, False)
    pc = result["power_control"]
    assert pc["power_consumed_watts"] == 1500 and isinstance(pc["power_consumed_watts"], int)
    assert pc["min_consumed_watts"] == 100 and pc["max_consumed_watts"] == 300


def test_power_int_watts_unchanged(monkeypatch):
    """정상 int watt 불변 (golden 호환)."""
    monkeypatch.setattr(rg, "_get", _fake_get_from_tree({
        "Chassis/1/Power": {"PowerControl": [{"PowerConsumedWatts": 150,
            "PowerMetrics": {"MinConsumedWatts": 140, "MaxConsumedWatts": 179}}]},
    }))
    result, _ = rg.gather_power("1.2.3.4", "/redfish/v1/Chassis/1", "u", "p", 5, False)
    assert result["power_control"]["power_consumed_watts"] == 150


# ── #22 FC WWPN MAC fallback 방어 ──
def test_fc_hba_mac_not_used_as_wwpn():
    """ndf 에 wwpn 없고 primary_addr 가 MAC(6 octet) → WWPN 으로 오기재 안 함."""
    hba = rg._make_fc_hba("A0", {"model": "HBA X"}, "1", "FibreChannel", "up", 32.0,
                          "00:11:22:33:44:55", {})  # MAC
    assert hba["wwpn"] is None


def test_fc_hba_port_address_is_not_used_as_wwpn():
    """2026-10-15: 8-octet 포트 주소도 wwpn 으로 올리지 않는다 (종전 Round 1 #22 fallback 제거).

    포트 주소의 뜻은 장비마다 다르다 — 실측 Dell R740 NetworkPort.AssociatedNetworkAddresses 는 WWNN(20:00:…)이고,
    Port.FibreChannel.AssociatedWorldWideNames 는 [WWNN, WWPN] 순서일 수 있다(CSUS-R13). wwpn 은 NDF 의 WWPN 만 쓴다.
    """
    hba = rg._make_fc_hba("A0", {"model": "HBA X"}, "1", "FibreChannel", "up", 32.0,
                          "10:00:00:11:22:33:44:55", {})  # 8 octet 주소
    assert hba["wwpn"] is None


def test_fc_hba_ndf_wwpn_preferred():
    """ndf.wwpn 이 있으면 우선 (primary_addr 무시)."""
    hba = rg._make_fc_hba("A0", {"model": "X"}, "1", "FibreChannel", "up", 32.0,
                          "00:11:22:33:44:55", {"wwpn": "20:00:00:11:22:33:44:55"})
    assert hba["wwpn"] == "20:00:00:11:22:33:44:55"
