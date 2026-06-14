"""F50 (cycle 2026-05-06): Dell Manager.Oem.Dell.DelliDRACCard 추출 회귀.

배경: 사용자 지적 "되는데 안된다고 적혀있어서 안되는게 더 있는지 확인" → 사이트 실측에서
Dell iDRAC9 Manager.Oem.Dell.DelliDRACCard 풍부 데이터 (IPMIVersion, LastUpdateTime 등)
가 server-exporter 코드에서 무시되고 있었음. cycle 2026-05-06 phase 2 에서 추출 추가.

source: 10.100.15.27 사이트 실측 + dell.com/support DellManager.v1_4_0 문서.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

# ansible stub
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402


def test_bmc_oem_dell_idrac_card_extracted(monkeypatch):
    """vendor='dell' + Manager.Oem.Dell.DelliDRACCard → oem 4 필드 추출."""
    manager_data = {
        "Id": "iDRAC.Embedded.1",
        "Model": "16G Monolithic",
        "FirmwareVersion": "7.10.70.00",
        "ManagerType": "BMC",
        "Oem": {
            "Dell": {
                "@odata.type": "#DellManager.v1_4_0.DellManager",
                "DelliDRACCard": {
                    "@odata.type": "#DelliDRACCard.v1_1_0.DelliDRACCard",
                    "IPMIVersion": "2.0",
                    "LastSystemInventoryTime": "2025-12-07T10:47:13+00:00",
                    "LastUpdateTime": "2026-05-06T08:18:46+00:00",
                    "URLString": "https://10.100.15.27:443",
                },
            },
        },
    }

    # _get 을 mock — Manager URL get 시 manager_data 반환
    def fake_get(bmc_ip, path, u, p, t, v):
        if path.endswith("Managers/iDRAC.Embedded.1") or path.endswith("/Managers/iDRAC.Embedded.1"):
            return 200, manager_data, None
        return 200, {}, None

    monkeypatch.setattr(rg, "_get", fake_get)

    result, errors = rg.gather_bmc(
        bmc_ip="10.100.15.27",
        manager_uri="/redfish/v1/Managers/iDRAC.Embedded.1",
        vendor="dell",
        username="root", password="pw",
        timeout=30, verify_ssl=False,
    )

    assert "oem" in result
    oem = result["oem"]
    assert oem.get("idrac_ipmi_version") == "2.0"
    assert oem.get("idrac_last_inventory_time") == "2025-12-07T10:47:13+00:00"
    assert oem.get("idrac_last_update_time") == "2026-05-06T08:18:46+00:00"
    assert oem.get("idrac_url") == "https://10.100.15.27:443"


def test_bmc_oem_dell_missing_oem_returns_none_fields(monkeypatch):
    """vendor='dell' + Manager.Oem.Dell 부재 → oem 필드 모두 None (예외 없음)."""
    manager_data = {
        "Id": "iDRAC.Embedded.1",
        "ManagerType": "BMC",
        # Oem 키 자체 부재
    }

    monkeypatch.setattr(rg, "_get", lambda *a, **kw: (200, manager_data, None))

    result, errors = rg.gather_bmc(
        bmc_ip="10.100.15.27",
        manager_uri="/redfish/v1/Managers/iDRAC.Embedded.1",
        vendor="dell",
        username="root", password="pw",
        timeout=30, verify_ssl=False,
    )
    assert "oem" in result
    oem = result["oem"]
    # 4 필드 모두 None (예외 없이)
    for k in ("idrac_ipmi_version", "idrac_last_inventory_time",
              "idrac_last_update_time", "idrac_url"):
        assert oem.get(k) is None


def test_bmc_oem_cisco_no_extraction(monkeypatch):
    """vendor='cisco' + Manager.Oem 부재 (실측 10.100.15.2) → result['oem'] 미설정."""
    manager_data = {
        "Id": "CIMC",
        "ManagerType": "BMC",
        "Model": "TA-UNODE-G1",
        "FirmwareVersion": "4.1(2g)",
        "Oem": {},  # 빈 dict (실측)
    }

    monkeypatch.setattr(rg, "_get", lambda *a, **kw: (200, manager_data, None))

    result, errors = rg.gather_bmc(
        bmc_ip="10.100.15.2",
        manager_uri="/redfish/v1/Managers/CIMC",
        vendor="cisco",
        username="admin", password="pw",
        timeout=30, verify_ssl=False,
    )
    # Cisco 분기 미추가 → result['oem'] 빈 dict default (init)
    assert result.get("oem") == {}
    # 표준 필드 정상
    assert result.get("firmware_version") == "4.1(2g)"
