"""`storage.hbas: []` 가 "HBA 없음" 인지 "확인 못 함" 인지 구분되는가 (2026-10-15).

    정상 수집 · FC 기능 없음        → hbas []   errors 없음  notices 없음
    NetworkAdapters 를 주지 않음    → hbas []   errors 없음  notices 'NetworkAdapters 리소스 404 … 미수집'  (섹션은 unsupported)
    목록이 비어 있음(모든 경로)     → hbas []   errors 없음  notices 'NetworkAdapters 목록이 비어 있음 … 미확인'
    수집 실패                       → hbas [] 또는 일부   errors[] (section network)   — status 는 바뀌지 않는다(보조 수집)

200 빈 목록은 다른 경로(Systems/{id}/NetworkAdapters — 일부 펌웨어 위치)도 본다. 빈 entry(빈 슬롯) 필터는 표준 근거
(NetworkDeviceFunctionCount · Controllers[].Links)가 있는 카드를 지우지 않는다.
"""
from __future__ import annotations

import pytest
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
    # 2026-10-19 (A-5): 섀시 목록이 비면 Systems/{id}/NetworkInterfaces(표준 링크)를 먼저 묻고(여기선 404), 그다음 iDRAC8 경로다.
    assert calls[:3] == [CH_NA, rg._p(SYSTEM) + "/NetworkInterfaces", SYS_NA]
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


# ── 미제공(키 없음 · 포트 없음)은 down + notice (값 계약 고정 — 2026-10-19: 값은 항상 up/down, null · 'unknown' 폐지) ─────────

def test_link_status_not_provided_is_down_with_notice_and_never_guessed_up(monkeypatch):
    rg._reset_notices()
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
    assert by_port["1"]["link_status"] == "down" and by_port["1"]["wwpn"] == "10:00:00:90:fa:00:00:01"
    assert by_port["9"]["link_status"] == "down" and by_port["9"]["link_speed_gbps"] is None
    assert all(h["link_status"] in ("up", "down") for h in out["fc_hbas"]), "값은 up/down 둘뿐 — null · unknown 없음"
    assert any("링크 상태 미제공" in n["message"] and "1, 9" in n["message"] and "down 으로 기록" in n["message"]
               for n in rg.notices()), rg.notices()
    assert not any("값 미확정" in n["message"] for n in rg.notices()), "키 없음은 '미제공' — '값 미확정' 이 아니다"


@pytest.mark.parametrize("raw, shown", [(None, "null"), ("Unknown", "Unknown"), ("WeirdState", "WeirdState")])
def test_link_status_unresolved_value_is_down_with_its_own_notice(monkeypatch, raw, shown):
    """키는 있는데 up/down 으로 정규화되지 않는 값(null · Unknown · 미인식) — down 이고, '미제공' 과 다른 notice 에 원문을 남긴다 (2026-10-19)."""
    rg._reset_notices()
    adp = CHASSIS + "/NetworkAdapters/FC1"
    routes = {
        CH_NA: (200, {"Members": [{"@odata.id": adp}]}, None),
        rg._p(adp): (200, {"Id": "FC1", "Manufacturer": "Vendor", "Model": "FC HBA",
                           "Ports": {"@odata.id": adp + "/Ports"},
                           "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}}, None),
        rg._p(adp) + "/Ports": (200, {"Members": [{"@odata.id": adp + "/Ports/1"}]}, None),
        rg._p(adp) + "/Ports/1": (200, {"Id": "1", "LinkStatus": raw, "FibreChannel": {}}, None),
        rg._p(adp) + "/NetworkDeviceFunctions": (200, {"Members": [{"@odata.id": adp + "/NetworkDeviceFunctions/1"}]}, None),
        rg._p(adp) + "/NetworkDeviceFunctions/1": (200, {"Id": "1", "NetDevFuncType": "FibreChannel",
                                                          "FibreChannel": {"WWPN": "10:00:00:90:fa:00:00:01"}}, None),
    }
    _install(monkeypatch, routes)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS)
    assert errors == []
    assert [h["link_status"] for h in out["fc_hbas"]] == ["down"]
    assert any("값 미확정" in n["message"] and ("1=%s" % shown) in n["message"] and "down 으로 기록" in n["message"]
               for n in rg.notices()), rg.notices()
    assert not any("링크 상태 미제공" in n["message"] for n in rg.notices()), "키가 있으면 '미제공' 이 아니다"


# ── 2026-10-18: 조용한 누락 · 가림 경로 보완 (F4 · F5 · F7 · F8) ────────────────────────────────

def _nameless_card_with_functions(members, coll=(200, None, None)):
    """Controllers 없음 · Manufacturer/Model 빈 문자열 — 최상위 NetworkDeviceFunctions 링크만 있는 카드."""
    adp = CHASSIS + "/NetworkAdapters/slot"
    routes = {CH_NA: (200, {"Members": [{"@odata.id": adp}]}, None),
              rg._p(adp): (200, {"Id": "slot", "Manufacturer": "", "Model": "",
                                 "NetworkDeviceFunctions": {"@odata.id": adp + "/NetworkDeviceFunctions"}}, None)}
    st, body, err = coll
    if body is None:
        body = {"Members": [{"@odata.id": adp + "/NetworkDeviceFunctions/" + m} for m in members]}
    routes[rg._p(adp) + "/NetworkDeviceFunctions"] = (st, body, err)
    for i, m in enumerate(members):
        routes[rg._p(adp) + "/NetworkDeviceFunctions/" + m] = (200, {
            "Id": m, "NetDevFuncType": "FibreChannel", "FibreChannel": {"WWPN": "10:00:00:90:fa:1b:2c:%02x" % i}}, None)
    return adp, routes


def test_nameless_card_with_fc_functions_is_kept_with_one_extra_request(monkeypatch):
    """(F4) 이름 · 컨트롤러 근거가 없어도 기능 목록에 FC 기능이 있으면 카드를 남긴다 — 기능 목록은 1회만 읽는다(재사용)."""
    calls = []
    adp, routes = _nameless_card_with_functions(["1", "2"])
    _install(monkeypatch, routes, calls)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS)
    assert errors == []
    assert [a["id"] for a in out["adapters"]] == ["slot"] and out["adapters"][0]["model"] is None
    assert len(out["fc_hbas"]) == 2 and all(h["link_status"] == "down" for h in out["fc_hbas"]), "포트 없는 기능 — 링크 상태 down(미제공, 2026-10-19)"
    assert calls.count(rg._p(adp) + "/NetworkDeviceFunctions") == 1, "기능 목록 조회는 1회(읽은 목록을 재사용)"
    assert any("카드 유지" in m for m in _notices()), _notices()


def test_nameless_card_with_an_empty_function_list_is_skipped_quietly(monkeypatch):
    adp, routes = _nameless_card_with_functions([])
    _install(monkeypatch, routes)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS)
    assert out["adapters"] == [] and errors == [] and _notices() == [], "기능 0건은 진짜 빈 슬롯 — 종전처럼 조용히 제외"


def test_nameless_card_whose_function_list_fails_is_skipped_with_an_error(monkeypatch):
    adp, routes = _nameless_card_with_functions([], coll=(500, {}, "HTTP 500: Internal Server Error"))
    _install(monkeypatch, routes)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS)
    assert out["adapters"] == []
    assert len(errors) == 1 and errors[0].get("code") == rg._CODE_NON_BLOCKING_SUBRESOURCE


def test_primary_failure_is_not_hidden_by_an_empty_fallback_list(monkeypatch):
    """(F8) 1순위 섀시 503 + Systems 경로 200 빈 목록 → 503 이 비차단 오류로 남고 notice 는 '비어 있음'. 섹션은 failed(미지원 아님)."""
    routes = {CH_NA: (503, {}, "HTTP 503: Service Unavailable"), SYS_NA: (200, {"Members": []}, None)}
    _install(monkeypatch, routes)
    run, state = _runner()
    val = run("network_adapters", rg.gather_network_adapters_chassis, "10.0.0.1", CHASSIS, *CREDS, SYSTEM, None)
    assert val["fc_hbas"] == []
    assert len(state["errors"]) == 1 and "503" in state["errors"][0]["message"] and CH_NA in state["errors"][0]["message"]
    assert state["errors"][0].get("code") == rg._CODE_NON_BLOCKING_SUBRESOURCE
    assert state["failed"] == ["network_adapters"] and state["unsupported"] == []
    assert any("비어 있음" in m for m in _notices())
    # envelope status 는 보조 섹션이라 바뀌지 않는다 — 녹화본 수준 확인은 test_redfish_hba_coverage_replay (F8 변형)


def test_fallback_failure_is_not_hidden_by_an_empty_primary_list(monkeypatch):
    routes = {CH_NA: (200, {"Members": []}, None), SYS_NA: (500, {}, "HTTP 500: Internal Server Error")}
    _install(monkeypatch, routes)
    _out, errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, "u", "p", 30, False, SYSTEM, None)
    assert len(errors) == 1 and SYS_NA in errors[0]["message"] and "500" in errors[0]["message"]


def test_all_listed_cards_unreadable_leaves_a_notice_even_when_classified_unsupported(monkeypatch):
    """(F7) 카드 목록은 200 인데 카드 GET 이 전부 404 → runner 는 미지원으로 분류해 오류를 버린다 — notice 로 사실을 남긴다."""
    a1, a2 = CHASSIS + "/NetworkAdapters/c1", CHASSIS + "/NetworkAdapters/c2"
    routes = {CH_NA: (200, {"Members": [{"@odata.id": a1}, {"@odata.id": a2}]}, None)}
    _install(monkeypatch, routes)
    run, state = _runner()
    val = run("network_adapters", rg.gather_network_adapters_chassis, "10.0.0.1", CHASSIS, *CREDS)
    assert val["adapters"] == [] and state["unsupported"] == ["network_adapters"] and state["errors"] == []
    assert any("목록 2건 중 읽은 카드 0건(404 2건)" in m for m in _notices()), _notices()


def test_one_unreadable_card_among_readable_ones_is_an_error_not_a_notice(monkeypatch):
    a1, routes1 = _fc_card(CHASSIS, "c1")
    a2 = CHASSIS + "/NetworkAdapters/c2"
    routes = {CH_NA: (200, {"Members": [{"@odata.id": a1}, {"@odata.id": a2}]}, None)}
    routes.update(routes1)
    _install(monkeypatch, routes)
    out, errors = rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS)
    assert [a["id"] for a in out["adapters"]] == ["c1"] and len(errors) == 1
    assert not [m for m in _notices() if "읽은 카드 0건" in m]


def test_other_path_failure_is_appended_to_the_404_notice(monkeypatch):
    """(F5) 1순위 404 + Systems 500: 미지원 분류(2026-10-15 결정)는 그대로, 다른 경로의 실패 사실은 notice 문장에 덧붙인다."""
    routes = {SYS_NA: (500, {}, "HTTP 500: Internal Server Error")}
    _install(monkeypatch, routes)
    run, state = _runner()
    run("network_adapters", rg.gather_network_adapters_chassis, "10.0.0.1", CHASSIS, *CREDS, SYSTEM, None)
    assert state["unsupported"] == ["network_adapters"]
    hits = [m for m in _notices() if "리소스 404" in m]
    assert len(hits) == 1 and "다른 경로 실패" in hits[0] and SYS_NA in hits[0] and "500" in hits[0], _notices()


def test_pure_404_notice_text_is_unchanged(monkeypatch):
    _install(monkeypatch, {})
    rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, *CREDS, SYSTEM, None)
    assert _notices() == ["NetworkAdapters 리소스 404, 네트워크 카드(FC HBA 포함) 정보 미수집"]
