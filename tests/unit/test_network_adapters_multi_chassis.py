"""System 이 연결한 섀시가 여럿일 때의 NetworkAdapters 수집 — 누락 · 중복 · 소유 (2026-10-15).

종전에는 `ComputerSystem.Links.Chassis[0]` 하나만 봐서 다른 섀시에 꽂힌 HBA 가 조용히 빠졌다 (DMTF: Links.Chassis 는
"physical containers associated with this resource" 배열). 규칙:
    - 1순위 섀시(Links.Chassis[0])는 종전과 같다.
    - 나머지 섀시는 **다른 System 이 그 섀시를 연결하지 않았다는 것을 끝까지 확인했을 때만** 본다 — 공유 중이거나 확인하지
      못하면 수집하지 않고 notice 를 남긴다(다른 파티션의 HBA 를 섞지 않는다).
    - 나머지 섀시는 경로를 조립하지 않고 섀시의 `NetworkAdapters` 링크를 따라간다. 링크가 없으면 조용히 건너뛴다.
    - Chassis 컬렉션 전체는 보지 않는다(System 에 연결된 섀시만).
    - 중복은 추가 섀시에서 온 것만, 확인된 단위로만 뺀다: 같은 카드 · 포트 리소스, null 이 아닌 같은 WWPN.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

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
CREDS = ("u", "p", 30, False)
S1 = "/redfish/v1/Systems/S1"
S2 = "/redfish/v1/Systems/S2"
C1 = "/redfish/v1/Chassis/C1"
C2 = "/redfish/v1/Chassis/C2"
C3 = "/redfish/v1/Chassis/C3"


def _install(monkeypatch, routes, calls=None):
    def fake_get(ip, path, *a, **kw):
        if calls is not None:
            calls.append(path)
        return routes.get(path, NF)
    monkeypatch.setattr(rg, "_get", fake_get)
    rg._reset_notices()


def _nic_card(chassis, card_id="NIC.1", mac="aa:bb:cc:00:00:01"):
    adp = f"{chassis}/NetworkAdapters/{card_id}"
    return adp, {
        rg._p(adp): (200, {"Id": card_id, "Manufacturer": "Vendor", "Model": "25GbE 2P NIC",
                           "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": 1}}],
                           "Ports": {"@odata.id": adp + "/Ports"}}, None),
        rg._p(adp) + "/Ports": (200, {"Members": [{"@odata.id": adp + "/Ports/1"}]}, None),
        rg._p(adp) + "/Ports/1": (200, {"Id": "1", "PortProtocol": "Ethernet", "LinkStatus": "LinkUp",
                                        "Ethernet": {"AssociatedMACAddresses": [mac]}}, None),
    }


def _fc_card(chassis, card_id="PCIeCard10", wwpns=("51:40:2e:c0:20:82:c2:2c",), serial="MY550301NK"):
    adp = f"{chassis}/NetworkAdapters/{card_id}"
    routes = {
        rg._p(adp): (200, {"Id": card_id, "Manufacturer": "HPE", "Model": "SN1100Q 16Gb 2P FC HBA",
                           "SerialNumber": serial,
                           "Ports": {"@odata.id": adp + "/Ports"},
                           "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}}, None),
        rg._p(adp) + "/Ports": (200, {"Members": [{"@odata.id": f"{adp}/Ports/P{i}"} for i in range(len(wwpns))]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [
            {"@odata.id": f"{adp}/NetworkDeviceFunctions/P{i}"} for i in range(len(wwpns))]}, None),
    }
    for i, w in enumerate(wwpns):
        routes[rg._p(adp) + f"/Ports/P{i}"] = (200, {"Id": f"P{i}", "LinkStatus": "LinkDown",
                                                    "FibreChannel": {"AssociatedWorldWideNames": [w] if w else []}}, None)
        routes[rg._p(adp) + f"/NetworkDeviceFunctions/P{i}"] = (200, {
            "Id": f"P{i}", "NetDevFuncType": "FibreChannel", "FibreChannel": {"WWPN": w} if w else {}}, None)
    return adp, routes


def _system(links, sid="S1"):
    return (200, {"Id": sid, "Links": {"Chassis": [{"@odata.id": u} for u in links]}}, None)


def _base(chassis_cards, extra_chassis_bodies=None, systems=(S1,), other_systems=None):
    """chassis_cards: {chassis_uri: [(adp_uri, routes)]}. 1번째 섀시는 조립 경로, 나머지는 섀시 링크로 연결한다."""
    routes = {rg._p("/redfish/v1/Systems"): (200, {"Members": [{"@odata.id": s} for s in systems]}, None)}
    for s, links in (other_systems or {}).items():
        routes[rg._p(s)] = _system(links, sid=s.rsplit("/", 1)[-1])
    for ch, cards in chassis_cards.items():
        members = []
        for adp, r in cards:
            members.append({"@odata.id": adp})
            routes.update(r)
        routes[rg._p(ch) + "/NetworkAdapters"] = (200, {"Members": members}, None)
        routes[rg._p(ch)] = (200, {"Id": ch.rsplit("/", 1)[-1],
                                   "NetworkAdapters": {"@odata.id": ch + "/NetworkAdapters"}}, None)
    routes.update(extra_chassis_bodies or {})
    return routes


def _gather(monkeypatch, routes, extras, calls=None, system_uri=S1, primary=C1):
    _install(monkeypatch, routes, calls)
    return rg.gather_network_adapters_chassis("10.0.0.1", primary, *CREDS, system_uri, extras)


# ── Links.Chassis 해석 ─────────────────────────────────────────────────────────

def test_resolve_system_chassis_uris_keeps_order_and_drops_duplicates(monkeypatch):
    _install(monkeypatch, {rg._p(S1): (200, {"Links": {"Chassis": [
        {"@odata.id": C2}, {"@odata.id": C1}, {"@odata.id": C2 + "/"}, {"x": 1}, {"@odata.id": 7}]}}, None)})
    assert rg._resolve_system_chassis_uris("ip", S1, *CREDS) == [C2, C1]
    _install(monkeypatch, {})
    assert rg._resolve_system_chassis_uris("ip", S1, *CREDS) == []
    assert rg._resolve_system_chassis_uris("ip", None, *CREDS) == []


def test_single_resolver_is_unchanged(monkeypatch):
    _install(monkeypatch, {rg._p(S1): _system([C2, C1])})
    assert rg._resolve_system_chassis_uri("ip", S1, C3, *CREDS) == C2
    _install(monkeypatch, {rg._p(S1): (200, {"Id": "S1"}, None)})
    assert rg._resolve_system_chassis_uri("ip", S1, C3, *CREDS) == C3


# ── 둘째 섀시 수집 ─────────────────────────────────────────────────────────────

def test_hba_in_second_linked_chassis_is_collected(monkeypatch):
    routes = _base({C1: [_nic_card(C1)], C2: [_fc_card(C2)]})
    out, errors = _gather(monkeypatch, routes, [C2])
    assert errors == []
    assert [a["id"] for a in out["adapters"]] == ["NIC.1", "PCIeCard10"], "1순위 섀시 카드 뒤에 둘째 섀시 카드"
    assert [h["wwpn"] for h in out["fc_hbas"]] == ["51:40:2e:c0:20:82:c2:2c"]
    assert rg.notices() == []


def test_collect_all_sections_wires_extra_chassis_and_keeps_system_get_count(monkeypatch):
    calls = []
    routes = _base({C1: [_nic_card(C1)], C2: [_fc_card(C2)]})
    routes[rg._p(S1)] = _system([C1, C2])
    # Chassis 컬렉션에는 System 에 연결되지 않은 C3 도 있다 — 보지 않아야 한다
    routes[rg._p(C3) + "/NetworkAdapters"] = (200, {"Members": [{"@odata.id": C3 + "/NetworkAdapters/X"}]}, None)
    _install(monkeypatch, routes, calls)
    all_errors, collected, failed, unsupported = [], [], [], []
    data = rg._collect_all_sections("10.0.0.1", "generic", S1, None, C1, *CREDS,
                                    all_errors, collected, failed, unsupported)
    assert [h["wwpn"] for h in data["network_adapters"]["fc_hbas"]] == ["51:40:2e:c0:20:82:c2:2c"]
    assert calls.count(rg._p(S1)) == 2, "ComputerSystem GET 은 종전과 같은 2회 (Links.Chassis 해석 + gather_system)"
    assert not [c for c in calls if c.startswith(rg._p(C3))], "System 에 연결되지 않은 섀시는 조회하지 않는다"


def test_extra_chassis_without_network_adapters_link_is_silent(monkeypatch):
    calls = []
    routes = _base({C1: [_nic_card(C1)]}, extra_chassis_bodies={rg._p(C2): (200, {"Id": "C2", "ChassisType": "Enclosure"}, None)})
    out, errors = _gather(monkeypatch, routes, [C2], calls)
    assert errors == [] and rg.notices() == []
    assert rg._p(C2) + "/NetworkAdapters" not in calls, "링크가 없으면 경로를 조립해 묻지 않는다"
    assert [a["id"] for a in out["adapters"]] == ["NIC.1"]


@pytest.mark.parametrize("status", [400, 403, 404, 500])
@pytest.mark.parametrize("where", ["chassis", "collection"])
def test_unreadable_linked_chassis_or_collection_is_a_nonblocking_error(monkeypatch, status, where):
    routes = _base({C1: [_nic_card(C1)], C2: [_fc_card(C2)]})
    target = rg._p(C2) if where == "chassis" else rg._p(C2) + "/NetworkAdapters"
    routes[target] = (status, {}, f"HTTP {status}: injected")
    out, errors = _gather(monkeypatch, routes, [C2])
    assert [a["id"] for a in out["adapters"]] == ["NIC.1"], "1순위 섀시 카드는 그대로"
    hits = [e for e in errors if e.get("code") == rg._CODE_NON_BLOCKING_SUBRESOURCE]
    assert len(hits) == 1 and str(status) in hits[0]["message"], errors
    final, _clean = rg._compute_final_status(["system", "network_adapters"], ["network_adapters"], errors)
    assert final == "partial", "하위 리소스 실패(403 포함)는 비차단 code 라 host 실패가 아니다 (envelope 에서는 보조 섹션이라 status 불변)"


def test_primary_404_with_extra_cards_is_not_an_error(monkeypatch):
    routes = _base({C2: [_fc_card(C2)]})
    out, errors = _gather(monkeypatch, routes, [C2])
    assert errors == [] and len(out["fc_hbas"]) == 1


def test_primary_failure_with_extra_cards_is_recorded(monkeypatch):
    routes = _base({C2: [_fc_card(C2)]})
    routes[rg._p(C1) + "/NetworkAdapters"] = (500, {}, "HTTP 500: Internal Server Error")
    out, errors = _gather(monkeypatch, routes, [C2])
    assert len(out["fc_hbas"]) == 1
    assert len(errors) == 1 and rg._p(C1) in errors[0]["message"]
    assert errors[0].get("code") == rg._CODE_NON_BLOCKING_SUBRESOURCE


def test_everything_absent_stays_unsupported(monkeypatch):
    routes = _base({}, extra_chassis_bodies={rg._p(C2): (200, {"Id": "C2"}, None)})
    _install(monkeypatch, routes)
    all_errors, collected, failed, unsupported = [], [], [], []
    run = rg._make_section_runner(all_errors, collected, failed, unsupported)
    val = run("network_adapters", rg.gather_network_adapters_chassis, "10.0.0.1", C1, *CREDS, S1, [C2])
    assert unsupported == ["network_adapters"] and all_errors == []
    assert val == {"adapters": [], "ports": [], "fc_hbas": [], "infiniband": []}
    assert any(n["section"] == "network_adapters" and "404" in n["message"] for n in rg.notices())


def test_chassis_sources_never_mix_with_the_systems_path(monkeypatch):
    calls = []
    routes = _base({C1: [_nic_card(C1)], C2: [_fc_card(C2)]})
    _gather(monkeypatch, routes, [C2], calls)
    assert rg._p(S1) + "/NetworkAdapters" not in calls


# ── 소유 확인 ──────────────────────────────────────────────────────────────────

def test_chassis_shared_with_another_system_is_not_collected(monkeypatch):
    calls = []
    routes = _base({C1: [_nic_card(C1)], C2: [_fc_card(C2)]}, systems=(S1, S2), other_systems={S2: [C2]})
    out, errors = _gather(monkeypatch, routes, [C2], calls)
    assert errors == []
    assert [a["id"] for a in out["adapters"]] == ["NIC.1"] and out["fc_hbas"] == []
    assert rg._p(C2) + "/NetworkAdapters" not in calls and rg._p(C2) not in calls
    assert any("C2" in n["message"] and "다른 System" in n["message"] for n in rg.notices()), rg.notices()


def test_chassis_linked_only_by_this_system_is_collected_on_multi_system_bmc(monkeypatch):
    routes = _base({C1: [_nic_card(C1)], C2: [_fc_card(C2)]}, systems=(S1, S2), other_systems={S2: [C3]})
    out, errors = _gather(monkeypatch, routes, [C2])
    assert errors == [] and len(out["fc_hbas"]) == 1


@pytest.mark.parametrize("broken", ["systems_listing", "other_system"])
def test_ownership_that_cannot_be_confirmed_is_not_guessed(monkeypatch, broken):
    calls = []
    routes = _base({C1: [_nic_card(C1)], C2: [_fc_card(C2)]}, systems=(S1, S2), other_systems={S2: [C3]})
    if broken == "systems_listing":
        routes[rg._p("/redfish/v1/Systems")] = (500, {}, "HTTP 500: Internal Server Error")
    else:
        routes[rg._p(S2)] = (503, {}, "HTTP 503: Service Unavailable")
    out, errors = _gather(monkeypatch, routes, [C2], calls)
    assert out["fc_hbas"] == [] and rg._p(C2) + "/NetworkAdapters" not in calls
    assert len(errors) == 1 and errors[0].get("code") == rg._CODE_NON_BLOCKING_SUBRESOURCE
    assert any("소유를 확인할 수 없음" in n["message"] for n in rg.notices()), rg.notices()


def test_single_system_bmc_needs_no_extra_system_reads(monkeypatch):
    calls = []
    routes = _base({C1: [_nic_card(C1)], C2: [_fc_card(C2)]})
    _gather(monkeypatch, routes, [C2], calls)
    assert calls.count(rg._p("/redfish/v1/Systems")) == 1 and rg._p(S2) not in calls


# ── 중복 (확인된 단위만) ───────────────────────────────────────────────────────

def test_same_adapter_resource_listed_by_two_chassis_is_collected_once(monkeypatch):
    nic_adp, nic_routes = _nic_card(C1)
    routes = _base({C1: [(nic_adp, nic_routes)], C2: [(nic_adp, nic_routes)]})
    out, errors = _gather(monkeypatch, routes, [C2])
    assert errors == [] and [a["id"] for a in out["adapters"]] == ["NIC.1"] and len(out["ports"]) == 1


def test_same_fc_port_identity_from_second_chassis_is_dropped_per_port(monkeypatch):
    """다른 리소스 주소로 같은 WWPN 이 다시 나오면 그 포트와 HBA 항목만 뺀다 — 카드 항목은 (리소스가 다르니) 남긴다."""
    w = "51:40:2e:c0:20:82:c2:2c"
    routes = _base({C1: [_fc_card(C1, "PCIeCard10", (w,))], C2: [_fc_card(C2, "PCIeCard10", (w,))]})
    out, errors = _gather(monkeypatch, routes, [C2])
    assert errors == []
    assert [h["wwpn"] for h in out["fc_hbas"]] == [w]
    assert len(out["ports"]) == 1
    assert len(out["adapters"]) == 2


def test_partial_overlap_keeps_the_new_ports(monkeypatch):
    a, b, c = "51:40:2e:c0:20:82:c2:2c", "51:40:2e:c0:20:82:c2:2e", "51:40:2e:c0:20:82:c2:94"
    routes = _base({C1: [_fc_card(C1, "PCIeCard10", (a, b))], C2: [_fc_card(C2, "PCIeCard15", (b, c))]})
    out, _errors = _gather(monkeypatch, routes, [C2])
    assert [h["wwpn"] for h in out["fc_hbas"]] == [a, b, c], "겹친 WWPN 만 빠지고 새 포트는 남는다"


def test_null_wwpn_ports_are_never_treated_as_duplicates(monkeypatch):
    routes = _base({C1: [_fc_card(C1, "PCIeCard10", (None,))], C2: [_fc_card(C2, "PCIeCard15", (None,))]})
    out, _errors = _gather(monkeypatch, routes, [C2])
    assert [h["wwpn"] for h in out["fc_hbas"]] == [None, None], "WWPN 을 모르면 같은 포트인지 확인할 수 없다 — 둘 다 남긴다"
    assert len(out["ports"]) == 2


def test_adapter_id_collision_across_chassis_keeps_both(monkeypatch):
    routes = _base({C1: [_fc_card(C1, "PCIeCard10", ("51:40:2e:c0:20:82:c2:2c",), "S-A")],
                    C2: [_fc_card(C2, "PCIeCard10", ("51:40:2e:c0:20:99:c2:2c",), "S-B")]})
    out, _errors = _gather(monkeypatch, routes, [C2])
    assert [a["id"] for a in out["adapters"]] == ["PCIeCard10", "PCIeCard10"], "Id 로 중복을 판단하지 않는다"
    assert len(out["fc_hbas"]) == 2
