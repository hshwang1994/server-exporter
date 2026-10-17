"""응답 오염(정수 · dict · list Id)과 카드 1장의 예외가 네트워크 카드 섹션 전체를 지우지 않는다 (2026-10-18, F3a · F3b).

배경:
    포트 `Id` 가 정수이고 짝 없는 기능이 하나라도 있으면 고아 루프의 `nid.startswith(_pid + '-')` 가 TypeError 를 냈고,
    섹션 runner 가 그 예외를 잡아 `data.network_adapters` 를 None 으로 버렸다 — adapters · ports · fc_hbas 전부
    (`storage.hbas: []`, `network.adapters: []`). 녹화본 변형(real_hpe_dl380, 포트 Id → 1)으로 재현했다.

규칙:
    - Id 문자열 연산은 _id_text(str 그대로 · int → str · 그 밖 '')로 통일한다. 출력 `port_id` 는 raw 그대로다.
    - 카드 1장의 예외는 그 카드에서 격리한다 — 부분 항목은 되돌리고 비차단 오류 1건만 남긴다(다른 카드 데이터 보존).
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
WWPN = "51:40:2E:C0:20:8F:39:30"
WWNN = "51:40:2E:C0:20:8F:39:31"


def _install(monkeypatch, routes):
    def fake_get(ip, path, *a, **kw):
        return routes.get(path, NF)
    monkeypatch.setattr(rg, "_get", fake_get)
    rg._reset_notices()


def _card(card_id, port_id, ndf_id, *, ndf_linked=True, wwpn=WWPN):
    adp = f"{CHASSIS}/NetworkAdapters/{card_id}"
    port = {"Id": port_id, "LinkNetworkTechnology": "FibreChannel", "LinkStatus": "LinkUp", "CurrentSpeedGbps": 16,
            "FibreChannel": {}}
    ndf = {"Id": ndf_id, "NetDevFuncType": "FibreChannel", "FibreChannel": {"WWPN": wwpn, "WWNN": WWNN}}
    if ndf_linked:
        ndf["Links"] = {"PhysicalNetworkPortAssignment": {"@odata.id": adp + "/Ports/p"}}
    return adp, {
        rg._p(adp): (200, {"Id": card_id, "Manufacturer": "Vendor", "Model": "FC HBA",
                           "Ports": {"@odata.id": adp + "/Ports"},
                           "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}}, None),
        rg._p(adp) + "/Ports": (200, {"Members": [{"@odata.id": adp + "/Ports/p"}]}, None),
        rg._p(adp) + "/Ports/p": (200, port, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [{"@odata.id": adp + "/NetworkDeviceFunctions/f"}]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions/f": (200, ndf, None),
    }


def _chassis_routes(*cards):
    routes = {rg._p(CHASSIS) + "/NetworkAdapters": (200, {"Members": [{"@odata.id": adp} for adp, _ in cards]}, None)}
    for _, r in cards:
        routes.update(r)
    return routes


def _run(monkeypatch, routes):
    _install(monkeypatch, routes)
    return rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, "u", "p", 30, False)


def test_integer_port_id_with_an_orphan_function_does_not_raise(monkeypatch):
    """포트 Id 1(int) + 고아 기능 "1-1": 종전 TypeError → 섹션 전체 소실. 지금은 HBA 1건(고아 경로, 부모 링크 상속) · 중복 없음."""
    out, errors = _run(monkeypatch, _chassis_routes(_card("HBA1", 1, "1-1", ndf_linked=False)))
    assert errors == []
    assert [(h["port_id"], h["wwpn"], h["link_status"], h["link_speed_gbps"]) for h in out["fc_hbas"]] == [("1-1", WWPN.lower(), "up", 16)]
    assert out["ports"][0]["port_id"] == 1, "출력 port_id 는 raw(int) 그대로"
    assert len(out["adapters"]) == 1 and len(out["ports"]) == 1


def test_dict_and_list_ids_do_not_raise(monkeypatch):
    adp, routes = _card("HBA1", {"x": 1}, ["a"], ndf_linked=False)
    out, _errors = _run(monkeypatch, _chassis_routes((adp, routes)))
    assert len(out["adapters"]) == 1 and len(out["ports"]) == 1, "오염된 Id 라도 카드 · 포트는 남는다"


def test_id_text_normalization():
    assert rg._id_text("1-1") == "1-1"
    assert rg._id_text(1) == "1"
    assert rg._id_text(True) == "" and rg._id_text(None) == "" and rg._id_text({"x": 1}) == "" and rg._id_text(["a"]) == ""


def test_exception_in_one_card_is_isolated_and_rolled_back(monkeypatch):
    """두 번째 카드 처리 중 예외 → 첫 카드의 adapters · ports · fc_hbas 는 그대로, 두 번째 카드는 부분 항목 없이 오류 1건."""
    c1 = _card("HBA1", "1", "1")
    c2 = _card("HBA2", "1", "1", wwpn="51:40:2E:C0:20:8F:3B:DC")
    routes = _chassis_routes(c1, c2)
    orig = rg._fetch_ndf_index

    def boom(bmc_ip, adata, *a, **kw):
        if rg._safe(adata, "Id") == "HBA2":
            raise ValueError("synthetic card failure")
        return orig(bmc_ip, adata, *a, **kw)
    monkeypatch.setattr(rg, "_fetch_ndf_index", boom)
    out, errors = _run(monkeypatch, routes)
    assert [a["id"] for a in out["adapters"]] == ["HBA1"], "실패 카드의 부분 항목(adapters)은 되돌린다"
    assert len(out["ports"]) == 1 and len(out["fc_hbas"]) == 1 and out["fc_hbas"][0]["wwpn"] == WWPN.lower()
    assert len(errors) == 1 and "처리 예외" in errors[0]["message"] and "HBA2" in errors[0]["message"]
    assert errors[0].get("code") == rg._CODE_NON_BLOCKING_SUBRESOURCE and "ValueError" in errors[0]["detail"]


def test_exception_in_one_card_keeps_the_section_collected_not_none(monkeypatch):
    """섹션 runner 수준: 예외가 카드 안에서 격리되므로 섹션 결과는 None 이 아니고 collected + failed(오류 있음)다."""
    c1 = _card("HBA1", "1", "1")
    c2 = _card("HBA2", "1", "1", wwpn="51:40:2E:C0:20:8F:3B:DC")
    routes = _chassis_routes(c1, c2)
    orig = rg._fetch_ndf_index

    def boom(bmc_ip, adata, *a, **kw):
        if rg._safe(adata, "Id") == "HBA2":
            raise ValueError("synthetic card failure")
        return orig(bmc_ip, adata, *a, **kw)
    monkeypatch.setattr(rg, "_fetch_ndf_index", boom)
    _install(monkeypatch, routes)
    errors, collected, failed, unsupported = [], [], [], []
    run = rg._make_section_runner(errors, collected, failed, unsupported)
    val = run("network_adapters", rg.gather_network_adapters_chassis, "10.0.0.1", CHASSIS, "u", "p", 30, False)
    assert val is not None and len(val["fc_hbas"]) == 1
    assert collected == ["network_adapters"] and failed == ["network_adapters"] and unsupported == []
