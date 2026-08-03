"""FCoE 지원 CNA 의 이더넷 기능을 FC HBA 로 오분류하지 않는지 회귀 (cycle 2026-08-03).

배경 (사이트 실측 — Jenkins DAY_1/git/소연등록redfish #4, Dell PowerEdge R630 8대):
    NetworkAdapters Systems-경로 fallback 으로 NIC 카드 데이터가 처음 들어오자,
    같은 물리 포트 4개가 서로 다르게 분류되는 **자기모순**이 드러났다.

      data.network.ports[].port_type          = "Ethernet"
      data.network.summary.groups[].link_type = "ethernet"
      data.storage.hbas[].port_type           = "FibreChannel"   ← 모순

    대상 NIC = `BRCM 10G/GbE 2+2P 57800 rNDC` (Broadcom 57800 = **FCoE 지원 CNA**).
    이런 CNA 는 이더넷 기능에도 MAC 파생 WWN 을 달고 나온다
    (실측 WWPN `20:01:90:b1:1c:1f:e2:8e` = MAC `90:b1:1c:1f:e2:8d` + 1).

원인:
    `_classify_port_protocol` 에서 CSUS-FC1 휴리스틱(`ndf_wwpn` 존재 → FibreChannel)이
    **Ethernet 판정보다 위**에 있어, 명시적인 Ethernet 신호를 덮어썼다. 이 휴리스틱은
    원래 NetDevFuncType 을 아예 주지 않는 HPE CSUS RMC 펌웨어 전용이었다.

fix:
    `ndf_wwpn` 휴리스틱을 함수 맨 끝(명시 신호 전무 시)으로 강등. FCoE 가 실제로 설정된
    장비는 `NetDevFuncType=FibreChannelOverEthernet` 을 주므로 위쪽 FCoE 분기에서 잡힌다.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

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


def _ndf(**kw):
    base = {"func_type": None, "net_dev_tech": None, "wwpn": None, "wwnn": None,
            "node_guid": None, "port_guid": None}
    base.update(kw)
    return base


# ── 오분류 방지 (사이트 재현) ────────────────────────────────────────────────

def test_ethernet_func_type_with_wwpn_is_ethernet():
    """NetDevFuncType=Ethernet 인데 WWPN 이 있어도 Ethernet — 명시 신호가 이긴다."""
    ndf = _ndf(func_type="Ethernet", net_dev_tech="Ethernet",
               wwpn="20:01:90:b1:1c:1f:e2:8e")
    assert rg._classify_port_protocol(None, None, ndf, None) == "Ethernet"


def test_ethernet_port_protocol_with_wwpn_is_ethernet():
    """Port.PortProtocol=Ethernet 이면 NDF 에 WWPN 이 있어도 Ethernet."""
    ndf = _ndf(wwpn="20:01:90:b1:1c:1f:e2:90")
    assert rg._classify_port_protocol("Ethernet", None, ndf, None) == "Ethernet"


def test_ethernet_port_block_with_wwpn_is_ethernet():
    """Port.Ethernet dict 만 있는 펌웨어에서도 WWPN 이 Ethernet 을 덮지 못한다."""
    ndf = _ndf(wwpn="20:01:90:b1:1c:1f:e2:92")
    pdata = {"Ethernet": {"AssociatedMACAddresses": ["90:b1:1c:1f:e2:91"]}}
    assert rg._classify_port_protocol(None, None, ndf, pdata) == "Ethernet"


# ── 진짜 FC/FCoE 는 그대로 (회귀 가드) ───────────────────────────────────────

def test_explicit_fibrechannel_func_type_still_fc():
    ndf = _ndf(func_type="FibreChannel", wwpn="21:00:00:24:ff:0a:0b:0c")
    assert rg._classify_port_protocol(None, None, ndf, None) == "FibreChannel"


def test_configured_fcoe_still_detected():
    """FCoE 가 실제로 설정된 CNA 는 NetDevFuncType 으로 잡힌다 — 본 강등의 영향 없음."""
    ndf = _ndf(func_type="FibreChannelOverEthernet", wwpn="20:01:90:b1:1c:1f:e2:8e")
    assert rg._classify_port_protocol(None, None, ndf, None) == "FCoE"
    assert rg._classify_port_protocol("FCoE", None, _ndf(), None) == "FCoE"


def test_fc_port_protocol_still_fc():
    for pp in ("FC", "FCP", "FibreChannel"):
        assert rg._classify_port_protocol(pp, None, _ndf(), None) == "FibreChannel"


def test_csus_wwpn_only_still_fc():
    """CSUS-FC1 본래 케이스(명시 신호 전무 + WWPN)는 여전히 FibreChannel — 강등해도 보존."""
    ndf = _ndf(wwpn="51:40:2e:c0:20:82:c2:2c")
    assert rg._classify_port_protocol(None, None, ndf, None) == "FibreChannel"


def test_infiniband_still_wins_over_wwpn():
    ndf = _ndf(net_dev_tech="InfiniBand", wwpn="51:40:2e:c0:20:82:c2:2c")
    assert rg._classify_port_protocol(None, None, ndf, None) == "InfiniBand"


# ── end-to-end: 사이트 NIC 이 storage.hbas 에 들어가지 않는다 ────────────────

def test_site_cna_produces_no_fc_hba(monkeypatch):
    """사이트 재현: 57800 rNDC(이더넷 기능 + MAC 파생 WWPN) → hbas 0, ports 는 Ethernet."""
    chassis = "/redfish/v1/Chassis/System.Embedded.1"
    adp = chassis + "/NetworkAdapters/NIC.Integrated.1"
    routes = {
        rg._p(chassis) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": adp}]}, None),
        rg._p(adp): (200, {
            "Id": "NIC.Integrated.1", "Name": "Network Adapter View",
            "Manufacturer": "Dell", "Model": "BRCM 10G/GbE 2+2P 57800 rNDC",
            "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": 4},
                             "FirmwarePackageVersion": "15.20.13"}],
            "NetworkPorts": {"@odata.id": adp + "/NetworkPorts"},
            "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"},
        }, None),
        rg._p(adp) + "/NetworkPorts": (200, {"Members": [
            {"@odata.id": adp + "/NetworkPorts/NIC.Integrated.1-1"}]}, None),
        rg._p(adp) + "/NetworkPorts/NIC.Integrated.1-1": (200, {
            "Id": "NIC.Integrated.1-1", "Name": "Network Port View",
            "PhysicalPortNumber": "1", "LinkStatus": "Down",
            "AssociatedNetworkAddresses": ["90:b1:1c:1f:e2:8d"],
            "Ethernet": {"AssociatedMACAddresses": ["90:b1:1c:1f:e2:8d"]},
        }, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [
            {"@odata.id": adp + "/NetworkDeviceFunctions/NIC.Integrated.1-1-1"}]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions/NIC.Integrated.1-1-1": (200, {
            "Id": "NIC.Integrated.1-1-1",
            "NetDevFuncType": "Ethernet",
            # FCoE 지원 CNA 라 이더넷 기능에도 MAC 파생 WWN 이 붙어 나온다
            "FibreChannel": {"WWPN": "20:01:90:b1:1c:1f:e2:8e",
                             "WWNN": "20:00:90:b1:1c:1f:e2:8e"},
            "Links": {"PhysicalPortAssignment": {
                "@odata.id": adp + "/NetworkPorts/NIC.Integrated.1-1"}},
        }, None),
    }
    monkeypatch.setattr(rg, "_get",
                        lambda ip, path, *a, **kw: routes.get(path, (404, {}, "HTTP 404: Not Found")))
    out, _ = rg.gather_network_adapters_chassis("10.0.0.1", chassis, "u", "p", 30, False)

    assert out["fc_hbas"] == [], "FCoE 지원 CNA 의 이더넷 기능이 FC HBA 로 오분류됨"
    assert out["infiniband"] == []
    assert [p["port_type"] for p in out["ports"]] == ["Ethernet"]
    assert out["adapters"][0]["model"] == "BRCM 10G/GbE 2+2P 57800 rNDC"


def _site_routes(chassis, *, ndf_link_to_port: bool, ndf_func_type):
    """사이트 Dell R630 토폴로지 — NDF Id = `<PortId>-<funcIdx>` (예: ...1-1 ↔ ...1-1-1)."""
    adp = chassis + "/NetworkAdapters/NIC.Integrated.1"
    ndf = {
        "Id": "NIC.Integrated.1-1-1",
        # FCoE 지원 CNA 라 이더넷 기능에도 MAC 파생 WWN 이 붙는다 (실측 NIC fw 15.20.13)
        "FibreChannel": {"WWPN": "20:01:90:b1:1c:1f:e2:8e",
                         "WWNN": "20:00:90:b1:1c:1f:e2:8e"},
    }
    if ndf_func_type is not None:
        ndf["NetDevFuncType"] = ndf_func_type
    if ndf_link_to_port:
        ndf["Links"] = {"PhysicalPortAssignment": {
            "@odata.id": adp + "/NetworkPorts/NIC.Integrated.1-1"}}
    return {
        rg._p(chassis) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": adp}]}, None),
        rg._p(adp): (200, {
            "Id": "NIC.Integrated.1", "Manufacturer": "Dell",
            "Model": "BRCM 10G/GbE 2+2P 57800 rNDC",
            "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": 4},
                             "FirmwarePackageVersion": "15.20.13"}],
            "NetworkPorts": {"@odata.id": adp + "/NetworkPorts"},
            "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"},
        }, None),
        rg._p(adp) + "/NetworkPorts": (200, {"Members": [
            {"@odata.id": adp + "/NetworkPorts/NIC.Integrated.1-1"}]}, None),
        rg._p(adp) + "/NetworkPorts/NIC.Integrated.1-1": (200, {
            "Id": "NIC.Integrated.1-1", "LinkStatus": "Down",
            "AssociatedNetworkAddresses": ["90:b1:1c:1f:e2:8d"],
            "Ethernet": {"AssociatedMACAddresses": ["90:b1:1c:1f:e2:8d"]},
        }, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [
            {"@odata.id": adp + "/NetworkDeviceFunctions/NIC.Integrated.1-1-1"}]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions/NIC.Integrated.1-1-1": (200, ndf, None),
    }


def test_orphan_ndf_inherits_parent_port_signal(monkeypatch):
    """사이트 잔여 2대 재현: NDF↔Port join 실패(orphan) + NetDevFuncType 부재 + WWPN 존재.

    부모 포트(`NIC.Integrated.1-1`)가 Ethernet 이므로 FC HBA 로 잡히면 안 된다.
    (구 코드는 컨텍스트 없이 분류 → WWPN 최후 휴리스틱 → FibreChannel 오분류)
    """
    chassis = "/redfish/v1/Chassis/System.Embedded.1"
    routes = _site_routes(chassis, ndf_link_to_port=False, ndf_func_type=None)
    monkeypatch.setattr(rg, "_get",
                        lambda ip, path, *a, **kw: routes.get(path, (404, {}, "HTTP 404: Not Found")))
    out, _ = rg.gather_network_adapters_chassis("10.0.0.1", chassis, "u", "p", 30, False)
    assert out["fc_hbas"] == [], "orphan NDF 가 부모 포트(Ethernet) 신호를 못 물려받음"
    assert [p["port_type"] for p in out["ports"]] == ["Ethernet"]


def test_orphan_ndf_with_fcoe_type_still_hba(monkeypatch):
    """orphan 이라도 NetDevFuncType 이 FCoE 면 HBA 로 잡힌다 — 부모 상속이 진짜 FCoE 를 덮지 않음."""
    chassis = "/redfish/v1/Chassis/System.Embedded.1"
    routes = _site_routes(chassis, ndf_link_to_port=False,
                          ndf_func_type="FibreChannelOverEthernet")
    monkeypatch.setattr(rg, "_get",
                        lambda ip, path, *a, **kw: routes.get(path, (404, {}, "HTTP 404: Not Found")))
    out, _ = rg.gather_network_adapters_chassis("10.0.0.1", chassis, "u", "p", 30, False)
    assert len(out["fc_hbas"]) == 1
    assert out["fc_hbas"][0]["port_type"] == "FCoE"
    assert out["fc_hbas"][0]["wwpn"] == "20:01:90:b1:1c:1f:e2:8e"


def test_ndf_id_prefix_match_requires_separator():
    """접두 매칭이 구분자 '-' 를 요구해 `...1-1` 이 `...1-10-1` 을 삼키지 않는다."""
    assert "NIC.Integrated.1-10-1".startswith("NIC.Integrated.1-1" + "-") is False
    assert "NIC.Integrated.1-1-1".startswith("NIC.Integrated.1-1" + "-") is True
