"""연결된 기능(NDF)이 없는 FC 포트도 HBA 로 남고, WWPN · Link 는 추측하지 않는다 (2026-10-15).

배경:
    `storage.hbas[]` 의 FC 판정은 NetworkDeviceFunction(NDF)에 기대고 있었다. 실측 Dell R740 의 FC NetworkPort 는
    PortProtocol · FibreChannel 블록 없이 `ActiveLinkTechnology: "FibreChannel"` 만 준다. 그래서 NDF 를 받지 못하면
    (컬렉션 404 · 500) HBA 가 조용히 빠졌고, 포트 주소(= WWNN 20:00:…)가 FC 카드의 `network.adapters[].mac` 으로 들어갔다.

규칙:
    - 연결된 NDF 가 없고 `<PortId>-` 접두의 짝 없는 NDF 도 없는 포트가 링크 기술(Port.LinkNetworkTechnology /
      NetworkPort.ActiveLinkTechnology)로 FibreChannel 을 밝히면 FC 포트다. 판정 함수(_classify_port_protocol)는 그대로다 —
      함수에 넣으면 RD-F15 의 기능별 판정과 짝 없는 NDF 경로에서 같은 포트가 두 번 나온다(녹화본 재현 8건).
    - wwpn 은 NDF 의 WWPN / PermanentWWPN 에서만 채운다. 포트 주소는 wwpn 으로 올리지 않는다(장비마다 WWNN 일 수 있다).
    - link_status 는 Port.LinkStatus 정규화 결과다 — 필드가 없으면 `unknown`.
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

NF = (404, {}, "HTTP 404: Not Found")
CHASSIS = "/redfish/v1/Chassis/System.Embedded.1"
ADP = CHASSIS + "/NetworkAdapters/FC.Slot.1"
WWPN = "21:00:34:80:0D:6C:2A:4C"
WWNN = "20:00:34:80:0D:6C:2A:4C"


def _install(monkeypatch, routes, calls=None):
    def fake_get(ip, path, *a, **kw):
        if calls is not None:
            calls.append(path)
        return routes.get(path, NF)
    monkeypatch.setattr(rg, "_get", fake_get)


def _dell_fc_routes(*, ndf=None, port_extra=None, port_link_status="Down", orphan=False):
    """실측 R740 FC 카드 모양 — NetworkPorts(구 스키마) + ActiveLinkTechnology, 포트 주소는 WWNN."""
    port = {"Id": "FC.Slot.1-1", "ActiveLinkTechnology": "FibreChannel",
            "AssociatedNetworkAddresses": [WWNN], "CurrentLinkSpeedMbps": None}
    if port_link_status is not None:
        port["LinkStatus"] = port_link_status
    port.update(port_extra or {})
    routes = {
        rg._p(CHASSIS) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": ADP}]}, None),
        rg._p(ADP): (200, {"Id": "FC.Slot.1", "Manufacturer": "QLogic Corp.", "Model": "QLogic FC16 2P QLE2692 Adapter",
                           "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": 1},
                                            "FirmwarePackageVersion": "15.05.14"}],
                           "NetworkPorts": {"@odata.id": ADP + "/NetworkPorts"},
                           "NetworkDeviceFunctions": {"@odata.id": ADP + "/NetworkDeviceFunctions"}}, None),
        rg._p(ADP) + "/NetworkPorts": (200, {"Members": [{"@odata.id": ADP + "/NetworkPorts/FC.Slot.1-1"}]}, None),
        rg._p(ADP) + "/NetworkPorts/FC.Slot.1-1": (200, port, None),
    }
    if ndf == "ok":
        nid = "FC.Slot.1-1-1" if orphan else "FC.Slot.1-1"
        body = {"Id": nid, "NetDevFuncType": "FibreChannel",
                "FibreChannel": {"WWPN": WWPN, "WWNN": WWNN}}
        if not orphan:
            body["Links"] = {"PhysicalPortAssignment": {"@odata.id": ADP + "/NetworkPorts/FC.Slot.1-1"}}
        routes[rg._p(ADP) + "/NetworkDeviceFunctions"] = (200, {"Members": [
            {"@odata.id": ADP + "/NetworkDeviceFunctions/" + nid}]}, None)
        routes[rg._p(ADP) + "/NetworkDeviceFunctions/" + nid] = (200, body, None)
    elif ndf == "500":
        routes[rg._p(ADP) + "/NetworkDeviceFunctions"] = (500, {}, "HTTP 500: Internal Server Error")
    elif ndf == "member404":
        routes[rg._p(ADP) + "/NetworkDeviceFunctions"] = (200, {"Members": [
            {"@odata.id": ADP + "/NetworkDeviceFunctions/FC.Slot.1-1"}]}, None)
    # ndf None → 컬렉션 404 (미노출)
    return routes


def _run(monkeypatch, routes):
    _install(monkeypatch, routes)
    return rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, "u", "p", 30, False)


def test_fc_port_without_ndf_is_still_an_hba_and_nothing_is_guessed(monkeypatch):
    out, errors = _run(monkeypatch, _dell_fc_routes())
    assert errors == [], "NDF 컬렉션 404 는 미노출 — 오류가 아니다"
    assert len(out["fc_hbas"]) == 1, "FC 포트가 HBA 목록에서 빠지면 안 된다"
    hba = out["fc_hbas"][0]
    assert hba["port_type"] == "FibreChannel"
    assert hba["wwpn"] is None and hba["wwnn"] is None, "포트 주소(WWNN)를 wwpn 으로 추측하지 않는다"
    assert hba["link_status"] == "down" and hba["link_speed_gbps"] is None
    assert out["ports"][0]["port_type"] == "FibreChannel"
    assert out["ports"][0]["associated_address"] == WWNN.lower(), "포트 주소는 associated_address 에 그대로 남는다"
    assert out["adapters"][0]["mac"] is None, "FC 포트의 WWN 은 카드 mac 이 아니다"


def test_ndf_collection_failure_keeps_the_hba_and_reports_the_failure(monkeypatch):
    out, errors = _run(monkeypatch, _dell_fc_routes(ndf="500"))
    assert len(out["fc_hbas"]) == 1 and out["fc_hbas"][0]["wwpn"] is None
    assert len(errors) == 1 and "NetworkDeviceFunctions" in errors[0]["message"]
    assert errors[0].get("code") == rg._CODE_NON_BLOCKING_SUBRESOURCE


def test_listed_ndf_member_that_cannot_be_read_is_recorded(monkeypatch):
    out, errors = _run(monkeypatch, _dell_fc_routes(ndf="member404"))
    assert len(out["fc_hbas"]) == 1 and out["fc_hbas"][0]["wwpn"] is None, "기능을 못 읽어도 FC 포트는 남는다"
    hits = [e for e in errors if "NetworkDeviceFunction " in e["message"]]
    assert len(hits) == 1 and hits[0].get("code") == rg._CODE_NON_BLOCKING_SUBRESOURCE, errors


def test_normal_ndf_join_is_unchanged(monkeypatch):
    out, errors = _run(monkeypatch, _dell_fc_routes(ndf="ok"))
    assert errors == []
    assert [(h["port_id"], h["wwpn"], h["wwnn"]) for h in out["fc_hbas"]] == [
        ("FC.Slot.1-1", WWPN.lower(), WWNN.lower())]
    assert out["ports"][0]["associated_address"] == WWPN.lower(), "CSUS-R13: FC 포트 주소는 NDF 의 WWPN 으로 교정"


def test_orphan_child_ndf_gives_exactly_one_hba(monkeypatch):
    """iDRAC8 형: NDF Id 가 `<PortId>-1` 이고 PhysicalPortAssignment 가 없다 — 포트와 짝 없는 NDF 가 같은 HBA 를 두 번 내지 않는다."""
    out, errors = _run(monkeypatch, _dell_fc_routes(ndf="ok", orphan=True))
    assert errors == []
    assert [(h["port_id"], h["wwpn"]) for h in out["fc_hbas"]] == [("FC.Slot.1-1-1", WWPN.lower())]
    # 2026-10-18 (F1): 이름(`<PortId>-1`)으로 부모 포트를 찾았으면 그 포트의 LinkStatus(fixture: Down)를 쓴다 — 종전 unknown.
    assert out["fc_hbas"][0]["link_status"] == "down", "짝 없는 기능은 이름으로 찾은 부모 포트의 상태를 쓴다 (2026-10-18)"
    assert out["adapters"][0]["mac"] is None, "짝 없는 구조에서도 WWNN 을 mac 으로 접지 않는다"


def test_port_link_network_technology_fc_without_ndf(monkeypatch):
    """신 Port 스키마(`Ports`)의 LinkNetworkTechnology=FibreChannel 도 같은 규칙."""
    chassis = "/redfish/v1/Chassis/1"
    adp = chassis + "/NetworkAdapters/HBA1"
    routes = {
        rg._p(chassis) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": adp}]}, None),
        rg._p(adp): (200, {"Id": "HBA1", "Manufacturer": "Vendor", "Model": "32Gb 2p FC HBA",
                           "Ports": {"@odata.id": adp + "/Ports"}}, None),
        rg._p(adp) + "/Ports": (200, {"Members": [{"@odata.id": adp + "/Ports/1"}]}, None),
        rg._p(adp) + "/Ports/1": (200, {"Id": "1", "LinkNetworkTechnology": "FibreChannel", "LinkStatus": "LinkUp",
                                        "CurrentSpeedGbps": 32}, None),
    }
    _install(monkeypatch, routes)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", chassis, "u", "p", 30, False)
    assert errors == []
    assert [(h["port_type"], h["link_status"], h["link_speed_gbps"], h["wwpn"]) for h in out["fc_hbas"]] == [
        ("FibreChannel", "up", 32, None)]


def test_joined_ethernet_function_is_not_overridden_by_link_technology(monkeypatch):
    """연결된 NDF 가 있으면 링크 기술 규칙을 쓰지 않는다 — 기능의 명시 신호가 이긴다."""
    routes = _dell_fc_routes()
    routes[rg._p(ADP) + "/NetworkDeviceFunctions"] = (200, {"Members": [
        {"@odata.id": ADP + "/NetworkDeviceFunctions/FC.Slot.1-1"}]}, None)
    routes[rg._p(ADP) + "/NetworkDeviceFunctions/FC.Slot.1-1"] = (200, {
        "Id": "FC.Slot.1-1", "NetDevFuncType": "Ethernet",
        "Links": {"PhysicalPortAssignment": {"@odata.id": ADP + "/NetworkPorts/FC.Slot.1-1"}}}, None)
    out, _errors = _run(monkeypatch, routes)
    assert out["fc_hbas"] == []
    assert out["ports"][0]["port_type"] == "Ethernet"


def test_link_status_absent_is_null(monkeypatch):
    """2026-10-18 사용자 결정: 문자열은 up/down 둘뿐 — 포트에 LinkStatus 가 없으면 null(장비 미제공)이고 down 으로 적지 않는다."""
    rg._reset_notices()
    out, _errors = _run(monkeypatch, _dell_fc_routes(port_link_status=None))
    assert out["fc_hbas"][0]["link_status"] is None, "상태를 받지 못하면 null — 추측해서 up/down 을 넣지 않는다"
    assert any("링크 상태 미제공" in n["message"] for n in rg.notices()), rg.notices()


def test_wwpn_is_derived_from_the_single_port_wwn_when_ndf_has_none(monkeypatch):
    """FC 블록 포트 + WWPN 없는 NDF (2026-10-18 배제 규칙): 포트 WWN 목록이 **하나**뿐이고 WWNN 을 모르면 그 값이 WWPN 이다
    (실측 CSUS node01: 포트 목록 = [WWPN]). 2026-10-15 의 "항상 null" 은 사이트에서 포트 주소를 wwpn 에 넣는 임시 조치를 낳았다."""
    rg._reset_notices()
    chassis = "/redfish/v1/Chassis/r001u01"
    adp = chassis + "/NetworkAdapters/PCIeCard10"
    routes = {
        rg._p(chassis) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": adp}]}, None),
        rg._p(adp): (200, {"Id": "PCIeCard10", "Manufacturer": "HPE", "Model": "SN1100Q 16Gb 2P FC HBA",
                           "Ports": {"@odata.id": adp + "/Ports"},
                           "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}}, None),
        rg._p(adp) + "/Ports": (200, {"Members": [{"@odata.id": adp + "/Ports/PCIeCard10Port1"}]}, None),
        rg._p(adp) + "/Ports/PCIeCard10Port1": (200, {
            "Id": "PCIeCard10Port1", "FibreChannel": {"AssociatedWorldWideNames": ["50:01:43:80:12:34:56:79"]}}, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [
            {"@odata.id": adp + "/NetworkDeviceFunctions/PCIeCard10Port1"}]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions/PCIeCard10Port1": (200, {
            "Id": "PCIeCard10Port1", "NetDevFuncType": "FibreChannel", "FibreChannel": {}}, None),
    }
    _install(monkeypatch, routes)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", chassis, "u", "p", 30, False)
    assert errors == []
    assert len(out["fc_hbas"]) == 1 and out["fc_hbas"][0]["wwpn"] == "50:01:43:80:12:34:56:79"
    assert out["ports"][0]["associated_address"] == "50:01:43:80:12:34:56:79"
    assert any("포트 주소에서 정함" in n["message"] for n in rg.notices()), rg.notices()


def test_wwpn_is_null_when_two_port_wwns_remain_and_wwnn_is_unknown(monkeypatch):
    """포트 WWN 목록이 둘인데 기능이 WWNN 을 주지 않으면 어느 것이 WWPN 인지 모른다 — null + notice (추측 금지)."""
    rg._reset_notices()
    chassis = "/redfish/v1/Chassis/r001u01"
    adp = chassis + "/NetworkAdapters/PCIeCard10"
    routes = {
        rg._p(chassis) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": adp}]}, None),
        rg._p(adp): (200, {"Id": "PCIeCard10", "Manufacturer": "HPE", "Model": "SN1100Q 16Gb 2P FC HBA",
                           "Ports": {"@odata.id": adp + "/Ports"},
                           "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}}, None),
        rg._p(adp) + "/Ports": (200, {"Members": [{"@odata.id": adp + "/Ports/PCIeCard10Port1"}]}, None),
        rg._p(adp) + "/Ports/PCIeCard10Port1": (200, {
            "Id": "PCIeCard10Port1",
            "FibreChannel": {"AssociatedWorldWideNames": ["51:40:2E:C0:20:82:EB:E9", "51:40:2E:C0:20:82:EB:E8"]}}, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [
            {"@odata.id": adp + "/NetworkDeviceFunctions/PCIeCard10Port1"}]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions/PCIeCard10Port1": (200, {
            "Id": "PCIeCard10Port1", "NetDevFuncType": "FibreChannel", "FibreChannel": {}}, None),
    }
    _install(monkeypatch, routes)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", chassis, "u", "p", 30, False)
    assert errors == []
    assert len(out["fc_hbas"]) == 1 and out["fc_hbas"][0]["wwpn"] is None
    assert any("WWPN 미확정" in n["message"] for n in rg.notices()), rg.notices()


def test_wwpn_is_derived_by_excluding_the_known_wwnn(monkeypatch):
    """포트 WWN 목록 [WWNN, WWPN](실측 CSUS node03 순서) + 기능이 WWNN 만 줄 때 — WWNN 을 빼고 남은 하나가 WWPN."""
    rg._reset_notices()
    chassis = "/redfish/v1/Chassis/r001u01"
    adp = chassis + "/NetworkAdapters/PCIeCard10"
    routes = {
        rg._p(chassis) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": adp}]}, None),
        rg._p(adp): (200, {"Id": "PCIeCard10", "Manufacturer": "HPE", "Model": "SN1100Q 16Gb 2P FC HBA",
                           "Ports": {"@odata.id": adp + "/Ports"},
                           "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}}, None),
        rg._p(adp) + "/Ports": (200, {"Members": [{"@odata.id": adp + "/Ports/PCIeCard10Port1"}]}, None),
        rg._p(adp) + "/Ports/PCIeCard10Port1": (200, {
            "Id": "PCIeCard10Port1",
            "FibreChannel": {"AssociatedWorldWideNames": ["51:40:2E:C0:20:82:EB:E9", "51:40:2E:C0:20:82:EB:E8"]}}, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [
            {"@odata.id": adp + "/NetworkDeviceFunctions/PCIeCard10Port1"}]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions/PCIeCard10Port1": (200, {
            "Id": "PCIeCard10Port1", "NetDevFuncType": "FibreChannel",
            "FibreChannel": {"WWNN": "51:40:2E:C0:20:82:EB:E9"}}, None),
    }
    _install(monkeypatch, routes)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", chassis, "u", "p", 30, False)
    assert errors == []
    assert [(h["wwpn"], h["wwnn"]) for h in out["fc_hbas"]] == [("51:40:2e:c0:20:82:eb:e8", "51:40:2e:c0:20:82:eb:e9")]
    assert out["ports"][0]["associated_address"] == "51:40:2e:c0:20:82:eb:e8", "FC 포트 주소도 정한 WWPN 으로 교정"


def test_make_fc_hba_uses_only_the_function_wwpn():
    assert rg._make_fc_hba("A", {}, "1", "FibreChannel", "up", 16.0, "10:00:00:11:22:33:44:55", {})["wwpn"] is None
    assert rg._make_fc_hba("A", {}, "1", "FibreChannel", "up", 16.0, "10:00:00:11:22:33:44:55",
                           {"wwpn": "20:00:00:11:22:33:44:55"})["wwpn"] == "20:00:00:11:22:33:44:55"


def test_classify_port_protocol_still_ignores_link_technology_fc():
    """설계 고정: 링크 기술 규칙은 포트 루프에만 있다 (판정 함수에 넣으면 RD-F15 · 짝 없는 NDF 경로가 중복을 만든다)."""
    assert rg._classify_port_protocol(None, "FibreChannel", None, None) is None
    assert rg._classify_port_protocol(None, "Ethernet", None, None) == "Ethernet"
