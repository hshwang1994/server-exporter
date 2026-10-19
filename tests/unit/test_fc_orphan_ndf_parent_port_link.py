"""짝 없는 FC 기능(NDF)이 이름으로 찾은 부모 포트의 링크 상태 · 속도를 쓴다 (2026-10-18, F1) + 기능의 포트 링크 2종 색인 (F1b).

배경:
    Dell 은 NDF Id 를 `<PortId>-<n>` 으로 매기고(iDRAC8 형은 PhysicalPortAssignment 가 없다) URI · Id 매칭이 둘 다 빗나가
    기능이 '고아' 가 된다. 종전 고아 경로는 부모 포트(`<PortId>-` 접두)를 찾아 **분류에는** 썼지만 HBA 의 link_status 는
    'unknown', link_speed_gbps 는 None 으로 하드코딩했다 — 포트가 Up · 16000 Mbps 라도 버려졌다(녹화본 변형 재현).

규칙:
    - 부모 포트를 찾았으면 그 포트의 LinkStatus(_hba_link_status: up / down — 2026-10-19 부터 둘뿐) 와 속도(_normalize_port_speed)를 쓴다.
    - port_id 는 종전처럼 기능 Id — 호출자 · 불변식 시험이 `<PortId>-` 접두로 포트와 맞춘다.
    - 부모를 못 찾으면 종전처럼 link None(장비 미제공 — 'unknown' 문자열은 폐지) · speed None.
    - (F1b) 기능의 PhysicalPortAssignment(→ NetworkPorts/…)와 PhysicalNetworkPortAssignment(→ Ports/…)를 모두 색인해
      어댑터가 어느 컬렉션을 노출하든 URI join 이 된다.
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


def _install(monkeypatch, routes):
    def fake_get(ip, path, *a, **kw):
        return routes.get(path, NF)
    monkeypatch.setattr(rg, "_get", fake_get)
    rg._reset_notices()


def _routes(*, port_link_status="Down", speed_mbps=None, orphan_id="FC.Slot.1-1-1"):
    """실측 R740 FC 카드 모양(NetworkPorts 구 스키마) + iDRAC8 형 짝 없는 기능."""
    port = {"Id": "FC.Slot.1-1", "ActiveLinkTechnology": "FibreChannel",
            "AssociatedNetworkAddresses": [WWNN], "CurrentLinkSpeedMbps": speed_mbps}
    if port_link_status is not None:
        port["LinkStatus"] = port_link_status
    return {
        rg._p(CHASSIS) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": ADP}]}, None),
        rg._p(ADP): (200, {"Id": "FC.Slot.1", "Manufacturer": "QLogic Corp.", "Model": "QLogic FC16 2P QLE2692 Adapter",
                           "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": 1}, "FirmwarePackageVersion": "15.05.14"}],
                           "NetworkPorts": {"@odata.id": ADP + "/NetworkPorts"},
                           "NetworkDeviceFunctions": {"@odata.id": ADP + "/NetworkDeviceFunctions"}}, None),
        rg._p(ADP) + "/NetworkPorts": (200, {"Members": [{"@odata.id": ADP + "/NetworkPorts/FC.Slot.1-1"}]}, None),
        rg._p(ADP) + "/NetworkPorts/FC.Slot.1-1": (200, port, None),
        rg._p(ADP) + "/NetworkDeviceFunctions": (200, {"Members": [{"@odata.id": ADP + "/NetworkDeviceFunctions/" + orphan_id}]}, None),
        rg._p(ADP) + "/NetworkDeviceFunctions/" + orphan_id: (200, {
            "Id": orphan_id, "NetDevFuncType": "FibreChannel", "FibreChannel": {"WWPN": WWPN, "WWNN": WWNN}}, None),
    }


def _run(monkeypatch, routes):
    _install(monkeypatch, routes)
    return rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, "u", "p", 30, False)


def test_orphan_function_inherits_parent_port_link_up_and_speed(monkeypatch):
    out, errors = _run(monkeypatch, _routes(port_link_status="Up", speed_mbps=16000))
    assert errors == []
    assert [(h["port_id"], h["wwpn"], h["link_status"], h["link_speed_gbps"]) for h in out["fc_hbas"]] == [
        ("FC.Slot.1-1-1", WWPN.lower(), "up", 16.0)], "부모 포트(FC.Slot.1-1)의 Up · 16000 Mbps 를 상속 — 종전 unknown/None"
    assert len(out["ports"]) == 1 and out["ports"][0]["port_type"] is None or out["ports"][0]["port_type"] != "Ethernet"
    assert out["adapters"][0]["mac"] is None, "FC 포트의 WWNN 을 카드 mac 으로 접지 않는다"
    assert not [n for n in rg.notices() if "링크 상태 미제공" in n["message"]]


def test_orphan_function_inherits_parent_port_link_down(monkeypatch):
    out, _errors = _run(monkeypatch, _routes(port_link_status="Down"))
    assert [(h["link_status"], h["link_speed_gbps"]) for h in out["fc_hbas"]] == [("down", None)]


def test_orphan_function_is_down_when_parent_port_has_no_link_status(monkeypatch):
    """부모 포트에 LinkStatus 키가 없으면 장비가 링크 상태를 주지 않는 것 — down + '미제공' notice (2026-10-19: 값은 항상 up/down)."""
    out, _errors = _run(monkeypatch, _routes(port_link_status=None))
    assert [h["link_status"] for h in out["fc_hbas"]] == ["down"]
    assert any("링크 상태 미제공" in n["message"] and "FC.Slot.1-1-1" in n["message"] for n in rg.notices()), rg.notices()


def test_orphan_function_inherits_unresolved_parent_value_as_down_with_notice(monkeypatch):
    """부모 포트의 LinkStatus 가 Unknown 처럼 up/down 으로 정규화되지 않으면 down 이고 '값 미확정' notice 에 원문이 남는다 (2026-10-19)."""
    rg._reset_notices()
    out, _errors = _run(monkeypatch, _routes(port_link_status="Unknown"))
    assert [h["link_status"] for h in out["fc_hbas"]] == ["down"]
    assert any("값 미확정" in n["message"] and "FC.Slot.1-1-1=Unknown" in n["message"] for n in rg.notices()), rg.notices()


def test_orphan_function_without_any_parent_is_down(monkeypatch):
    out, _errors = _run(monkeypatch, _routes(port_link_status="Up", speed_mbps=16000, orphan_id="9"))
    hbas = {h["port_id"]: h for h in out["fc_hbas"]}
    assert hbas["9"]["link_status"] == "down" and hbas["9"]["link_speed_gbps"] is None, "부모를 못 찾으면 상속할 포트가 없다 — down + 미제공 notice"
    # 포트 쪽: 기능이 안 붙었고 `FC.Slot.1-1-` 접두의 고아도 없으니 lt_fc 규칙으로 FC 포트 — HBA 1건(wwpn 은 WWNN 이라 null)
    assert hbas["FC.Slot.1-1"]["wwpn"] is None and hbas["FC.Slot.1-1"]["link_status"] == "up"


def test_function_joins_through_the_new_port_link_when_only_ports_collection_is_exposed(monkeypatch):
    """(F1b) 기능 Id 가 포트 Id 와 다르고 PhysicalPortAssignment 는 NetworkPorts/… 를, PhysicalNetworkPortAssignment 는 Ports/… 를
    가리키는데 어댑터는 `Ports` 만 노출 — 종전에는 첫 링크(NetworkPorts)만 색인해 join 이 빗나가 고아가 됐다."""
    adp = CHASSIS + "/NetworkAdapters/HBA2"
    routes = {
        rg._p(CHASSIS) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": adp}]}, None),
        rg._p(adp): (200, {"Id": "HBA2", "Manufacturer": "Vendor", "Model": "32Gb 2p FC HBA",
                           "Ports": {"@odata.id": adp + "/Ports"},
                           "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}}, None),
        rg._p(adp) + "/Ports": (200, {"Members": [{"@odata.id": adp + "/Ports/P1"}]}, None),
        rg._p(adp) + "/Ports/P1": (200, {"Id": "P1", "LinkNetworkTechnology": "FibreChannel", "LinkStatus": "LinkUp",
                                         "CurrentSpeedGbps": 32, "FibreChannel": {}}, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [{"@odata.id": adp + "/NetworkDeviceFunctions/NDF-A"}]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions/NDF-A": (200, {
            "Id": "NDF-A", "NetDevFuncType": "FibreChannel", "FibreChannel": {"WWPN": WWPN, "WWNN": WWNN},
            "Links": {"PhysicalPortAssignment": {"@odata.id": adp + "/NetworkPorts/P1"},
                      "PhysicalNetworkPortAssignment": {"@odata.id": adp + "/Ports/P1"}}}, None),
    }
    out, errors = _run(monkeypatch, routes)
    assert errors == []
    assert [(h["port_id"], h["wwpn"], h["link_status"], h["link_speed_gbps"]) for h in out["fc_hbas"]] == [
        ("P1", WWPN.lower(), "up", 32)], "join 성공 — port_id 는 포트 Id, 링크 · 속도는 포트의 것"
    assert out["ports"][0]["associated_address"] == WWPN.lower(), "CSUS-R13: FC 포트 주소는 기능의 WWPN"


def test_ndf_index_keeps_both_port_links(monkeypatch):
    adp = CHASSIS + "/NetworkAdapters/HBA2"
    routes = {
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [{"@odata.id": adp + "/NetworkDeviceFunctions/1"}]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions/1": (200, {
            "Id": "1", "NetDevFuncType": "FibreChannel", "FibreChannel": {"WWPN": WWPN},
            "Links": {"PhysicalPortAssignment": {"@odata.id": adp + "/NetworkPorts/1"},
                      "PhysicalNetworkPortAssignment": {"@odata.id": adp + "/Ports/1"}}}, None),
    }
    _install(monkeypatch, routes)
    ndfs = rg._fetch_ndf_index("10.0.0.1", {"NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}},
                               "u", "p", 30, False, [])
    assert ndfs[0]["port_uri"] == rg._p(adp + "/NetworkPorts/1"), "종전 키 · 값 유지"
    assert ndfs[0]["port_uris"] == [rg._p(adp + "/NetworkPorts/1"), rg._p(adp + "/Ports/1")]
