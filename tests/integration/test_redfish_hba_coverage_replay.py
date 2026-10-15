"""실장비 녹화본으로 본 Redfish HBA 누락 보완 (2026-10-15).

real_dell_r740 · real_hpe_csus3200 녹화본을 그대로(또는 응답을 주입·변형해) 모듈 main() 에 재생하고, normalize_standard →
build_sections → build_status 의 실제 식으로 envelope 의 섹션 · status · errors[] 까지 확인한다 (C4 시험과 같은 방식, 네트워크 0).

    - FC 기능(NDF) 목록을 못 받아도 FC 포트는 HBA 로 남는다 — WWPN 은 추측하지 않는다(null), WWNN 이 mac 으로 들어가지 않는다.
    - iDRAC8 형(짝 없는 NDF) 구조에서 HBA 가 중복되지 않는다.
    - CSUS 녹화본에 섀시를 덧붙인 **합성** 다중 섀시: 다른 카드면 더하고, 같은 카드(같은 WWPN)면 더하지 않는다.
      다른 파티션도 연결한 섀시와 System 에 연결되지 않은 섀시는 보지 않는다.
합성 변형은 실장비 다중 섀시 응답이 아니다 — 사이트 실측 전까지 '실장비 미검증' 이다 (tests/evidence/2026-10-15-redfish-hba-coverage.md).
"""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import jinja2
import pytest
import yaml

import emulator_harness as H

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "redfish"
NORM_STD = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
NORM_COMMON = REPO / "common" / "tasks" / "normalize"
SM = yaml.safe_load((REPO / "common" / "vars" / "section_messages.yml").read_text(encoding="utf-8"))
rg = H.rg


@pytest.fixture(autouse=True)
def _module_state():
    yield
    rg._reset_response_cache(enabled=False)
    rg._reset_auth_observation()
    rg._reset_notices()


class _Captured(Exception):
    def __init__(self, result):
        self.result = result


def _module(layout):
    class _Module:
        def __init__(self, **kwargs):
            self.check_mode = False
            self.params = {"bmc_ip": "192.0.2.1", "username": "std", "password": "<pw>", "timeout": 30,
                           "verify_ssl": False, "mode": "gather", "manager_layout": layout, "attempt": None}

        def exit_json(self, **result):
            raise _Captured(result)

        def fail_json(self, **result):
            raise AssertionError(result)
    return _Module


def _load(fixture):
    rec = json.loads((FIX / fixture / "recording.json").read_text(encoding="utf-8"))
    meta_p = FIX / fixture / "meta.json"
    layout = json.loads(meta_p.read_text(encoding="utf-8")).get("manager_layout") if meta_p.is_file() else None
    return rec, layout


def _gather(monkeypatch, recording, layout=None, calls=None):
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)

    def counted(bmc_ip, path, *a, **kw):
        if calls is not None:
            calls.append(path)
        return get_impl(bmc_ip, path, *a, **kw)

    monkeypatch.setattr(rg, "_get_impl", counted)
    monkeypatch.setattr(rg, "_get_noauth", noauth_impl)
    if realm_impl is not None:
        monkeypatch.setattr(rg, "_probe_realm_hint", realm_impl)
    monkeypatch.setattr(rg, "AnsibleModule", _module(layout))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)
    try:
        rg.main()
    except _Captured as caught:
        return caught.result
    raise AssertionError("module did not return")


def _set_fact_value(path, key):
    for t in yaml.safe_load(path.read_text(encoding="utf-8")):
        sf = t.get("ansible.builtin.set_fact") or {}
        if key in sf:
            return sf[key]
    raise AssertionError(f"{path.name}: {key}")


def _render(expr, **ctx):
    return ast.literal_eval(jinja2.Environment().from_string(expr).render(**ctx).strip())


def _envelope(result):
    """모듈 결과 → normalize_standard(섹션 · errors fragment) → build_sections → build_status (C4 와 같은 식)."""
    common = dict(_rf_proc_map=_set_fact_value(NORM_STD, "_rf_proc_map"), _rf_aux_sections=_set_fact_value(NORM_STD, "_rf_aux_sections"))
    collected = _render(_set_fact_value(NORM_STD, "_sections_collected_fragment"), _rf_collected_raw=result["collected"], **common)
    failed = _render(_set_fact_value(NORM_STD, "_sections_failed_fragment"), _rf_failed_raw=result["failed_sections"], **common)
    unsupported = _render(_set_fact_value(NORM_STD, "_sections_unsupported_fragment"),
                          _rf_unsupported_raw=result.get("unsupported_sections", []), **common)
    supported = _render(_set_fact_value(NORM_STD, "_sections_supported_fragment"))
    sections = _render(_set_fact_value(NORM_COMMON / "build_sections.yml", "_norm_sections"),
                       _all_sec_supported=supported, _all_sec_collected=collected, _all_sec_failed=failed, _all_sec_unsupported=unsupported)
    status = jinja2.Environment().from_string(_set_fact_value(NORM_COMMON / "build_status.yml", "_out_status")).render(
        _norm_sections=sections).strip()
    errors = _render(_set_fact_value(NORM_STD, "_errors_fragment"), _rf_raw_collect=result, **SM)
    return sections, status, errors


def _netad(result):
    return result["data"]["network_adapters"]


def _netad_notices(result):
    return [n["message"] for n in result.get("notices") or [] if isinstance(n, dict) and n.get("section") == "network_adapters"]


# ── 녹화본 그대로 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture", ["real_dell_r740", "real_hpe_dl380", "real_hpe_csus3200", "real_lenovo_sr650"])
def test_unmodified_recordings_get_no_new_network_adapter_notices_or_errors(monkeypatch, fixture):
    rec, layout = _load(fixture)
    r = _gather(monkeypatch, rec, layout)
    golden = json.loads((FIX / fixture / "expected_output.json").read_text(encoding="utf-8"))
    assert _netad(r)["fc_hbas"] == golden["data"]["network_adapters"]["fc_hbas"], "기존에 잡히던 HBA 는 그대로"
    assert _netad_notices(r) == []
    assert not [e for e in r["errors"] if e.get("section") == "network_adapters"]


# ── R740: FC 기능 목록을 못 받는 경우 ───────────────────────────────────────────

def _r740_variant(kind):
    rec, layout = _load("real_dell_r740")
    r = copy.deepcopy(rec)
    for k in list(r):
        if "/FC.Slot." not in k or "/NetworkDeviceFunctions" not in k:
            continue
        st, body = r[k][0], r[k][1]
        if k.endswith("/NetworkDeviceFunctions"):
            if kind in ("ndf404", "ndf500"):
                code = 404 if kind == "ndf404" else 500
                r[k] = [code, {}, f"HTTP {code}: injected"]
            elif kind == "orphan" and isinstance(body, dict):
                nb = dict(body)
                nb["Members"] = [{"@odata.id": m["@odata.id"] + "-1"} for m in body.get("Members", [])]
                r[k] = [st, nb, None]
        elif kind == "orphan" and isinstance(body, dict):
            nb = dict(body)
            nb["Id"] = nb["Id"] + "-1"
            nb["@odata.id"] = nb.get("@odata.id", "") + "-1"
            links = dict(nb.get("Links") or {})
            links.pop("PhysicalPortAssignment", None)
            links.pop("PhysicalNetworkPortAssignment", None)
            nb["Links"] = links
            r[k + "-1"] = [st, nb, None]
            del r[k]
    return r, layout


@pytest.mark.parametrize("kind", ["ndf404", "ndf500"])
def test_r740_fc_ports_stay_hbas_without_guessed_values(monkeypatch, kind):
    rec, layout = _r740_variant(kind)
    r = _gather(monkeypatch, rec, layout)
    hbas = _netad(r)["fc_hbas"]
    assert sorted(h["port_id"] for h in hbas) == ["FC.Slot.1-1", "FC.Slot.1-2", "FC.Slot.7-1", "FC.Slot.7-2"]
    assert all(h["wwpn"] is None and h["wwnn"] is None for h in hbas), "WWPN 을 포트 주소(WWNN)로 추측하지 않는다"
    assert all(h["link_status"] == "down" and h["port_type"] == "FibreChannel" for h in hbas)
    fc_cards = [a for a in _netad(r)["adapters"] if a["id"].startswith("FC.")]
    assert [a["mac"] for a in fc_cards] == [None, None], "FC 포트의 WWNN 을 카드 mac 으로 접지 않는다"
    sections, status, errors = _envelope(r)
    assert sections["storage"] == "success" and sections["network"] == "success" and status == "success"
    net = [e for e in errors if e["section"] == "network"]
    if kind == "ndf404":
        assert net == [], "NDF 미노출(404)은 오류가 아니다"
    else:
        # envelope 은 섹션당 오류 1건으로 묶고 기술 근거는 detail 에 모은다 (errors[] 계약)
        assert len(net) == 1, errors
        assert "FC.Slot.1/NetworkDeviceFunctions" in net[0]["detail"] and "FC.Slot.7/NetworkDeviceFunctions" in net[0]["detail"]


def test_r740_idrac8_shaped_orphan_functions_do_not_duplicate_hbas(monkeypatch):
    rec, layout = _r740_variant("orphan")
    r = _gather(monkeypatch, rec, layout)
    hbas = _netad(r)["fc_hbas"]
    assert len(hbas) == 4 and len({h["wwpn"] for h in hbas}) == 4
    assert all(h["wwpn"].startswith("21:00:") for h in hbas), "WWPN 은 NDF 의 값(21:00:…)이다"
    fc_cards = [a for a in _netad(r)["adapters"] if a["id"].startswith("FC.")]
    assert [a["mac"] for a in fc_cards] == [None, None]


# ── CSUS 3200 녹화본 + 합성 섀시 ───────────────────────────────────────────────

def _csus_with_extra_chassis(*, distinct=True, link_to_partition=True, shared_partition=False, unlinked=False):
    rec, layout = _load("real_hpe_csus3200")
    r = copy.deepcopy(rec)
    new_id = "r001u03" if unlinked else "r001u02"

    def clone(s):
        s = s.replace("r001u01", new_id).replace("chassis_u1", "chassis_u" + new_id[-1])
        if distinct:
            s = s.replace("51:40:2E:C0:20:82:C2", "51:40:2E:C0:20:99:C2").replace("MY5503", "MY5599")
        return s

    for k in list(rec):
        if k == "get::Chassis/r001u01" or k.startswith("get::Chassis/r001u01/NetworkAdapters") \
                or k.startswith("get::Chassis/r001u01/PCIeDevices"):
            r[clone(k)] = json.loads(clone(json.dumps(rec[k])))
    if link_to_partition and not unlinked:
        sys_body = r["get::Systems/Partition0"][1]
        sys_body["Links"]["Chassis"].append({"@odata.id": f"/redfish/v1/Chassis/{new_id}"})
    if unlinked:
        r["get::Chassis"][1]["Members"].append({"@odata.id": f"/redfish/v1/Chassis/{new_id}"})
    if shared_partition:
        r["get::Systems"][1]["Members"].append({"@odata.id": "/redfish/v1/Systems/Partition1"})
        r["get::Systems/Partition1"] = [200, {"@odata.id": "/redfish/v1/Systems/Partition1", "Id": "Partition1",
                                              "Links": {"Chassis": [{"@odata.id": f"/redfish/v1/Chassis/{new_id}"}]}}, None]
    return r, layout


def test_csus_second_linked_chassis_with_other_cards_adds_their_hbas(monkeypatch):
    rec, layout = _csus_with_extra_chassis(distinct=True)
    calls = []
    r = _gather(monkeypatch, rec, layout, calls)
    hbas = _netad(r)["fc_hbas"]
    assert len(hbas) == 8 and len({h["wwpn"] for h in hbas}) == 8
    assert sum(1 for h in hbas if h["wwpn"].startswith("51:40:2e:c0:20:99")) == 4
    assert [a["id"] for a in _netad(r)["adapters"]] == ["PCIeCard10", "PCIeCard15", "PCIeCard10", "PCIeCard15"], \
        "섀시가 달라도 같은 Id 가 나올 수 있다 — Id 로 중복을 판단하지 않는다 (고유 키는 wwpn)"
    assert "Chassis/r001u02/NetworkAdapters" in calls
    assert _netad_notices(r) == [] and not [e for e in r["errors"] if e.get("section") == "network_adapters"]


def test_csus_second_linked_chassis_with_the_same_cards_adds_nothing(monkeypatch):
    rec, layout = _csus_with_extra_chassis(distinct=False)
    r = _gather(monkeypatch, rec, layout)
    hbas = _netad(r)["fc_hbas"]
    assert len(hbas) == 4 and len({h["wwpn"] for h in hbas}) == 4, "같은 WWPN 의 FC 포트는 한 번만"
    assert len(_netad(r)["ports"]) == 4


def test_csus_chassis_shared_with_another_partition_is_not_collected(monkeypatch):
    rec, layout = _csus_with_extra_chassis(distinct=True, shared_partition=True)
    calls = []
    r = _gather(monkeypatch, rec, layout, calls)
    assert len(_netad(r)["fc_hbas"]) == 4, "다른 파티션도 연결한 섀시의 카드는 이 System 에 넣지 않는다"
    assert "Chassis/r001u02/NetworkAdapters" not in calls
    assert any("r001u02" in m and "다른 System" in m for m in _netad_notices(r)), _netad_notices(r)


def test_csus_chassis_not_linked_to_the_system_is_never_queried(monkeypatch):
    rec, layout = _csus_with_extra_chassis(distinct=True, unlinked=True)
    calls = []
    r = _gather(monkeypatch, rec, layout, calls)
    assert len(_netad(r)["fc_hbas"]) == 4
    assert not [c for c in calls if c.startswith("Chassis/r001u03/NetworkAdapters")]
