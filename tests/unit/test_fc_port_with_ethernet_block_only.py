"""FC 링크 기술 포트가 `Ethernet` 블록만 노출해도(FibreChannel 블록 없음) FC 포트다 (2026-10-18, F2).

배경:
    신 Port 스키마의 FC HBA 는 WWPN 을 `Ethernet.AssociatedMACAddresses` 에 담아 노출한다(실측 HPE iLO6 DL380 — FC 포트에
    `FibreChannel: {}` 과 `Ethernet` 블록이 함께 있다). FibreChannel 블록까지 없는 변형에서는 판정 함수의 Ethernet 블록-존재
    분기가 'Ethernet' 을 돌려 포트 루프의 lt_fc 규칙(cls is None 요구)이 영원히 불발 → 기능(NDF)을 못 받으면
    HBA 0건 · 오류 0건 · success 로 끝났다(녹화본 변형 재현).

규칙:
    - 링크 기술이 FibreChannel 인 포트에서는 Ethernet 블록 존재가 Ethernet 의 근거가 아니다(판정 함수는 None).
      판정 함수는 여전히 링크 기술만으로 FC 를 **돌려주지 않는다**(2026-10-15 폐기 원안과 다름 — 중복 방지).
    - 연결된 기능이 Ethernet(NetDevFuncType) 이면 종전처럼 Ethernet 이다 — 기능의 명시 신호가 이긴다.
    - 기능이 없을 때 WWPN 은 포트 주소 배제 규칙(_derive_port_wwpn)으로 정한다 — 8옥텟 값만, WWNN 제외.
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
CHASSIS = "/redfish/v1/Chassis/1"
ADP = CHASSIS + "/NetworkAdapters/DE041000"
WWPN = "51:40:2E:C0:20:8F:39:30"
WWNN = "51:40:2E:C0:20:8F:39:31"


def _install(monkeypatch, routes):
    def fake_get(ip, path, *a, **kw):
        return routes.get(path, NF)
    monkeypatch.setattr(rg, "_get", fake_get)
    rg._reset_notices()


def _routes(*, ndf=None, extra_ndf=None):
    """실측 DL380 FC 카드(iLO6) 변형 — Port 에 FibreChannel 블록 없이 Ethernet 블록(=WWPN)만."""
    routes = {
        rg._p(CHASSIS) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": ADP}]}, None),
        rg._p(ADP): (200, {"Id": "DE041000", "Manufacturer": "Hewlett Packard Enterprise", "Model": "HPE SN1610Q 32Gb 2p FC HBA",
                           "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": 1, "NetworkDeviceFunctionCount": 1},
                                            "FirmwarePackageVersion": "2.08.05"}],
                           "Ports": {"@odata.id": ADP + "/Ports"},
                           "NetworkDeviceFunctions": {"@odata.id": ADP + "/NetworkDeviceFunctions"}}, None),
        rg._p(ADP) + "/Ports": (200, {"Members": [{"@odata.id": ADP + "/Ports/1"}]}, None),
        rg._p(ADP) + "/Ports/1": (200, {"Id": "1", "LinkNetworkTechnology": "FibreChannel", "LinkStatus": "LinkDown",
                                        "CurrentSpeedGbps": 0, "Ethernet": {"AssociatedMACAddresses": [WWPN]}}, None),
    }
    members = []
    bodies = {}
    if ndf == "fc":
        members.append("1")
        bodies["1"] = {"Id": "1", "NetDevFuncType": "FibreChannel", "FibreChannel": {"WWPN": WWPN, "WWNN": WWNN},
                       "Links": {"PhysicalNetworkPortAssignment": {"@odata.id": ADP + "/Ports/1"}}}
    elif ndf == "eth":
        members.append("1")
        bodies["1"] = {"Id": "1", "NetDevFuncType": "Ethernet", "Ethernet": {"MACAddress": "14:23:f3:b0:7a:40"},
                       "Links": {"PhysicalNetworkPortAssignment": {"@odata.id": ADP + "/Ports/1"}}}
    elif ndf == "orphan":
        members.append("1-1")
        bodies["1-1"] = {"Id": "1-1", "NetDevFuncType": "FibreChannel", "FibreChannel": {"WWPN": WWPN, "WWNN": WWNN}}
    if ndf == "500":
        routes[rg._p(ADP) + "/NetworkDeviceFunctions"] = (500, {}, "HTTP 500: Internal Server Error")
    elif ndf is not None:
        routes[rg._p(ADP) + "/NetworkDeviceFunctions"] = (200, {"Members": [
            {"@odata.id": ADP + "/NetworkDeviceFunctions/" + m} for m in members]}, None)
        for m, body in bodies.items():
            routes[rg._p(ADP) + "/NetworkDeviceFunctions/" + m] = (200, body, None)
    return routes


def _run(monkeypatch, routes):
    _install(monkeypatch, routes)
    return rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, "u", "p", 30, False)


def test_fc_port_with_ethernet_block_only_and_no_functions_is_an_hba(monkeypatch):
    out, errors = _run(monkeypatch, _routes(ndf=None))
    assert errors == [], "기능 컬렉션 404 는 미노출 — 오류가 아니다"
    assert [(h["port_type"], h["link_status"], h["wwpn"]) for h in out["fc_hbas"]] == [("FibreChannel", "down", WWPN.lower())], \
        "Ethernet 블록만 있어도 FC 포트 — WWPN 은 포트 주소(8옥텟) 배제 규칙으로"
    assert out["ports"][0]["port_type"] == "FibreChannel" and out["ports"][0]["associated_address"] == WWPN.lower()
    assert out["adapters"][0]["mac"] is None, "WWPN 을 카드 mac 으로 접지 않는다"
    assert any("포트 주소에서 정함" in n["message"] for n in rg.notices()), rg.notices()


def test_fc_port_with_ethernet_block_only_and_function_failure_keeps_the_hba(monkeypatch):
    out, errors = _run(monkeypatch, _routes(ndf="500"))
    assert len(out["fc_hbas"]) == 1 and out["fc_hbas"][0]["port_type"] == "FibreChannel"
    assert len(errors) == 1 and errors[0].get("code") == rg._CODE_NON_BLOCKING_SUBRESOURCE


def test_joined_fc_function_is_unchanged(monkeypatch):
    out, errors = _run(monkeypatch, _routes(ndf="fc"))
    assert errors == []
    assert [(h["port_id"], h["wwpn"], h["wwnn"]) for h in out["fc_hbas"]] == [("1", WWPN.lower(), WWNN.lower())]
    assert not [n for n in rg.notices() if "포트 주소에서 정함" in n["message"]], "기능이 WWPN 을 주면 포트 주소 규칙은 쓰지 않는다"


def test_joined_ethernet_function_still_wins_over_link_technology(monkeypatch):
    out, _errors = _run(monkeypatch, _routes(ndf="eth"))
    assert out["fc_hbas"] == []
    assert out["ports"][0]["port_type"] == "Ethernet", "기능의 명시 신호(NetDevFuncType=Ethernet)가 이긴다"


def test_orphan_fc_function_on_such_a_port_gives_exactly_one_hba(monkeypatch):
    """`<PortId>-1` 고아 FC 기능 + FC 링크 기술 포트(Ethernet 블록만): HBA 는 정확히 1건(고아 경로), 포트는 Ethernet 이 아니다."""
    out, errors = _run(monkeypatch, _routes(ndf="orphan"))
    assert errors == []
    assert [(h["port_id"], h["wwpn"], h["link_status"]) for h in out["fc_hbas"]] == [("1-1", WWPN.lower(), "down")]
    assert out["ports"][0]["port_type"] != "Ethernet", "INV-1: FC 링크 기술 포트가 Ethernet 으로 나가지 않는다"


def test_classify_vectors_for_the_ethernet_block_guard():
    assert rg._classify_port_protocol(None, "FibreChannel", None, {"Ethernet": {"AssociatedMACAddresses": [WWPN]}}) is None, \
        "FC 링크 기술 포트의 Ethernet 블록은 Ethernet 근거가 아니다 — 판정 함수는 FC 도 돌려주지 않는다(None)"
    assert rg._classify_port_protocol(None, "Ethernet", None, {"Ethernet": {}}) == "Ethernet"
    assert rg._classify_port_protocol(None, None, {"wwpn": "10:00:00:11:22:33:44:55"}, {"Ethernet": {}}) == "Ethernet", \
        "CNA 핀 유지: 링크 기술 없이 Ethernet 블록 + MAC 파생 WWN 은 Ethernet"
    assert rg._classify_port_protocol(None, "FibreChannel", {"func_type": "Ethernet"}, {"Ethernet": {}}) == "Ethernet"


def test_derive_port_wwpn_rules():
    # 8옥텟만 — 6옥텟 MAC 은 후보가 아니다
    assert rg._derive_port_wwpn({"Ethernet": {"AssociatedMACAddresses": ["14:23:f3:b0:7a:40"]}}, "FibreChannel", {}) is None
    assert rg._derive_port_wwpn({"Ethernet": {"AssociatedMACAddresses": [WWPN]}}, "FibreChannel", {}) == WWPN.lower()
    # 링크 기술이 FC 가 아니면 Ethernet 블록은 보지 않는다
    assert rg._derive_port_wwpn({"Ethernet": {"AssociatedMACAddresses": [WWPN]}}, "Ethernet", {}) is None
    # [WWNN, WWPN] + 기능 WWNN → 배제로 WWPN
    assert rg._derive_port_wwpn({"FibreChannel": {"AssociatedWorldWideNames": [WWNN, WWPN]}}, None,
                                {"wwnn": WWNN.lower()}) == WWPN.lower()
    # 둘인데 WWNN 을 모르면 None
    assert rg._derive_port_wwpn({"FibreChannel": {"AssociatedWorldWideNames": [WWNN, WWPN]}}, None, {}) is None
    # 하나뿐이면 그 값
    assert rg._derive_port_wwpn({"FibreChannel": {"AssociatedWWNs": [WWPN]}}, None, None) == WWPN.lower()
    # 구 NetworkPort 의 AssociatedNetworkAddresses 는 쓰지 않는다 (Dell 실측 WWNN)
    assert rg._derive_port_wwpn({"AssociatedNetworkAddresses": [WWNN]}, "FibreChannel", {}) is None
