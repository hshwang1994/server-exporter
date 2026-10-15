"""`storage.hbas: []` 가 "HBA 없음" 인지 "확인 못 함" 인지 구분되는가 (2026-10-15).

    정상 수집 · FC 기능 없음        → hbas []   errors 없음  notices 없음
    NetworkAdapters 를 주지 않음    → hbas []   errors 없음  notices 'NetworkAdapters 리소스 404 … 미수집'  (섹션은 unsupported)
    목록이 비어 있음(모든 경로)     → hbas []   errors 없음  notices 'NetworkAdapters 목록이 비어 있음 … 미확인'
    수집 실패                       → hbas [] 또는 일부   errors[] (section network)   — status 는 바뀌지 않는다(보조 수집)

200 빈 목록은 다른 경로(Systems/{id}/NetworkAdapters — 일부 펌웨어 위치)도 본다. 빈 entry(빈 슬롯) 필터는 표준 근거
(NetworkDeviceFunctionCount · Controllers[].Links)가 있는 카드를 지우지 않는다.
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
CREDS = ("u", "p", 30, False)
CHASSIS = "/redfish/v1/Chassis/1"
SYSTEM = "/redfish/v1/Systems/1"
CH_NA = rg._p(CHASSIS) + "/NetworkAdapters"
SYS_NA = rg._p(SYSTEM) + "/NetworkAdapters"


def _install(monkeypatch, routes, calls=None):
    def fake_get(ip, path, *a, **kw):
        if calls is not None:
            calls.append(path)
        return routes.get(path, NF)
    monkeypatch.setattr(rg, "_get", fake_get)
    rg._reset_notices()


def _fc_card(base, card_id="FC1", body_extra=None):
    adp = f"{base}/NetworkAdapters/{card_id}"
    body = {"Id": card_id, "Manufacturer": "Vendor", "Model": "16Gb 2P FC HBA",
            "Ports": {"@odata.id": adp + "/Ports"},
            "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}}
    body.update(body_extra or {})
    return adp, {
        rg._p(adp): (200, body, None),
        rg._p(adp) + "/Ports": (200, {"Members": [{"@odata.id": adp + "/Ports/1"}]}, None),
        rg._p(adp) + "/Ports/1": (200, {"Id": "1", "LinkStatus": "LinkDown", "FibreChannel": {}}, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [{"@odata.id": adp + "/NetworkDeviceFunctions/1"}]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions/1": (200, {"Id": "1", "NetDevFuncType": "FibreChannel",
                                                          "FibreChannel": {"WWPN": "10:00:00:90:fa:1b:2c:3d"},
                                                          "Links": {"PhysicalPortAssignment": {"@odata.id": adp + "/Ports/1"}}}, None),
    }


def _notices(section="network_adapters"):
    return [n["message"] for n in rg.notices() if n["section"] == section]


def _runner():
    state = {"errors": [], "collected": [], "failed": [], "unsupported": []}
    run = rg._make_section_runner(state["errors"], state["collected"], state["failed"], state["unsupported"])
    return run, state


# ── 200 빈 목록 → 다른 경로 ────────────────────────────────────────────────────

def test_empty_chassis_list_falls_back_to_the_systems_path(monkeypatch):
    adp, card = _fc_card(SYSTEM)
    routes = {CH_NA: (200, {"Members": []}, None), SYS_NA: (200, {"Members": [{"@odata.id": adp}]}, None), **card}
    calls = []
    _install(monkeypatch, routes, calls)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS, SYSTEM)
    assert calls[:2] == [CH_NA, SYS_NA]
    assert errors == [] and [h["wwpn"] for h in out["fc_hbas"]] == ["10:00:00:90:fa:1b:2c:3d"]
    assert _notices() == []


def test_chassis_with_cards_does_not_try_the_systems_path(monkeypatch):
    adp, card = _fc_card(CHASSIS)
    calls = []
    _install(monkeypatch, {CH_NA: (200, {"Members": [{"@odata.id": adp}]}, None), **card}, calls)
    rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS, SYSTEM)
    assert SYS_NA not in calls


def test_empty_everywhere_is_not_an_error_but_is_not_silent(monkeypatch):
    _install(monkeypatch, {CH_NA: (200, {"Members": []}, None)})
    run, st = _runner()
    val = run("network_adapters", rg.gather_network_adapters_chassis, "10.0.0.1", CHASSIS, *CREDS, SYSTEM)
    assert val["fc_hbas"] == [] and st["errors"] == [] and st["unsupported"] == []
    assert st["collected"] == ["network_adapters"] and st["failed"] == []
    assert len(_notices()) == 1 and "비어 있음" in _notices()[0]


# ── 미제공(404) / 실패 ──────────────────────────────────────────────────────────

def test_resource_absent_is_unsupported_with_a_notice(monkeypatch):
    _install(monkeypatch, {})
    run, st = _runner()
    val = run("network_adapters", rg.gather_network_adapters_chassis, "10.0.0.1", CHASSIS, *CREDS, SYSTEM)
    assert val["fc_hbas"] == [] and st["unsupported"] == ["network_adapters"] and st["errors"] == []
    assert len(_notices()) == 1 and "404" in _notices()[0] and "미수집" in _notices()[0]


def test_collection_failure_is_visible_and_does_not_fail_the_host(monkeypatch):
    _install(monkeypatch, {CH_NA: (503, {}, "HTTP 503: Service Unavailable")})
    run, st = _runner()
    run("network_adapters", rg.gather_network_adapters_chassis, "10.0.0.1", CHASSIS, *CREDS, SYSTEM)
    assert st["unsupported"] == [] and len(st["errors"]) == 1 and "HTTP 503" in st["errors"][0]["message"]
    assert _notices() == [], "실패는 errors[] 로 — notice 로 덮지 않는다"
    status, _clean = rg._compute_final_status(["system"] + st["collected"], st["failed"], st["errors"])
    assert status != "failed"


def test_standard_path_signal_decides_absence_even_if_the_fallback_path_fails(monkeypatch):
    """표준 위치(Chassis) 404 + Systems 경로(일부 펌웨어 위치) 500 → 종전처럼 표준 위치 신호로 판정한다 — 미지원 + notice.

    Systems 경로는 표준이 아니라(ComputerSystem 에 NetworkAdapters 없음) 미지원 장비가 그 경로에 500 을 주는 경우를 실패로
    올리면 매 수집 잡음이 된다. 시도한 두 경로는 오류 detail 의 tried 목록에 남는다.
    """
    _install(monkeypatch, {SYS_NA: (500, {}, "HTTP 500: Internal Server Error")})
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS, SYSTEM)
    assert out["fc_hbas"] == [] and len(errors) == 1 and "HTTP 404" in errors[0]["message"]
    assert "Systems/1/NetworkAdapters" in (errors[0]["detail"] or "")
    run, st = _runner()
    _install(monkeypatch, {SYS_NA: (500, {}, "HTTP 500: Internal Server Error")})
    run("network_adapters", rg.gather_network_adapters_chassis, "10.0.0.1", CHASSIS, *CREDS, SYSTEM)
    assert st["unsupported"] == ["network_adapters"] and len(_notices()) == 1


# ── 빈 entry 필터 ──────────────────────────────────────────────────────────────

def _single_card_routes(body):
    adp = CHASSIS + "/NetworkAdapters/slot"
    return adp, {CH_NA: (200, {"Members": [{"@odata.id": adp}]}, None), rg._p(adp): (200, body, None)}


def test_empty_slot_entry_is_still_skipped(monkeypatch):
    calls = []
    adp, routes = _single_card_routes({"Id": "slot", "Manufacturer": "", "Model": "",
                                       "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": 0}}]})
    _install(monkeypatch, routes, calls)
    out, _errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS)
    assert out["adapters"] == []


def test_controllerless_entry_with_only_a_top_level_ports_link_is_skipped(monkeypatch):
    """실측 CSUS 'Rmp' 모양 — Controllers 없음 · Manufacturer/Model null · 최상위 Ports 링크만. 종전처럼 제외(포트도 묻지 않는다)."""
    calls = []
    adp, routes = _single_card_routes({"Id": "Rmp", "Manufacturer": None, "Model": None,
                                       "Ports": {"@odata.id": CHASSIS + "/NetworkAdapters/slot/Ports"}})
    _install(monkeypatch, routes, calls)
    out, _errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS)
    assert out["adapters"] == [] and rg._p(adp) + "/Ports" not in calls


def test_card_with_function_count_is_kept_even_without_names(monkeypatch):
    adp, routes = _single_card_routes({"Id": "slot", "Manufacturer": "", "Model": "",
                                       "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": 0,
                                                                                   "NetworkDeviceFunctionCount": 2}}]})
    _install(monkeypatch, routes)
    out, _errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS)
    assert [a["id"] for a in out["adapters"]] == ["slot"]


def test_card_with_controller_port_links_is_kept_even_without_names(monkeypatch):
    adp, routes = _single_card_routes({"Id": "slot", "Manufacturer": "", "Model": "",
                                       "Controllers": [{"Links": {"Ports": [{"@odata.id": CHASSIS + "/NetworkAdapters/slot/Ports/1"}]}}]})
    _install(monkeypatch, routes)
    out, _errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS)
    assert [a["id"] for a in out["adapters"]] == ["slot"]


# ── unknown 의 두 원인 (값 계약 고정) ──────────────────────────────────────────

def test_link_status_unknown_has_two_causes_and_is_never_guessed(monkeypatch):
    adp = CHASSIS + "/NetworkAdapters/FC1"
    routes = {
        CH_NA: (200, {"Members": [{"@odata.id": adp}]}, None),
        rg._p(adp): (200, {"Id": "FC1", "Manufacturer": "Vendor", "Model": "FC HBA",
                           "Ports": {"@odata.id": adp + "/Ports"},
                           "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}}, None),
        rg._p(adp) + "/Ports": (200, {"Members": [{"@odata.id": adp + "/Ports/1"}]}, None),
        # (a) 포트는 읽었지만 LinkStatus 필드가 없다
        rg._p(adp) + "/Ports/1": (200, {"Id": "1", "FibreChannel": {}}, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [
            {"@odata.id": adp + "/NetworkDeviceFunctions/1"}, {"@odata.id": adp + "/NetworkDeviceFunctions/9"}]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions/1": (200, {"Id": "1", "NetDevFuncType": "FibreChannel",
                                                          "FibreChannel": {"WWPN": "10:00:00:90:fa:00:00:01"}}, None),
        # (b) 짝이 되는 포트 리소스가 없는 FC 기능
        rg._p(adp) + "/NetworkDeviceFunctions/9": (200, {"Id": "9", "NetDevFuncType": "FibreChannel",
                                                          "FibreChannel": {"WWPN": "10:00:00:90:fa:00:00:09"}}, None),
    }
    _install(monkeypatch, routes)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS)
    assert errors == []
    by_port = {h["port_id"]: h for h in out["fc_hbas"]}
    assert by_port["1"]["link_status"] == "unknown" and by_port["1"]["wwpn"] == "10:00:00:90:fa:00:00:01"
    assert by_port["9"]["link_status"] == "unknown" and by_port["9"]["link_speed_gbps"] is None
