"""다중 노드 개수 (2026-10-29 SA-01 · SA-02) — 원천 컬렉션을 끝까지 읽고 나열된 멤버를 모두 읽었을 때만 정수(0 포함)다.

링크 없음 · 404 · GET 실패 · 절단 · 멤버 일부 실패는 null 이다. 목록(switches · endpoints · resource_blocks · partitions …)은
읽은 멤버만 담고 미제공이면 [] 그대로다(사용자 결정 — 목록은 [] 유지, 개수만 null). 실패는 errors[] 가 따로 말한다.
실측 근거: CSUS 3200 FlexGrid 는 Endpoints 링크가 없다(real_hpe_csus3200* recording) — 종전 endpoint_count 0 은 "보지 못함" 이었다.
기대값은 원천 응답과 규칙으로 손으로 적었다(현재 출력 복사 아님, rule 95 R3).
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "tests" / "integration"))
for _n in ("ansible", "ansible.module_utils", "ansible.module_utils.basic"):
    sys.modules.setdefault(_n, types.ModuleType(_n))
if not hasattr(sys.modules["ansible.module_utils.basic"], "AnsibleModule"):
    sys.modules["ansible.module_utils.basic"].AnsibleModule = object

import redfish_gather as rg  # noqa: E402
import emulator_harness as H  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "redfish"
CREDS = ("u", "p", 10, False)
IP = "10.0.0.1"
NOT_FOUND = (404, {}, "HTTP 404: Not Found")
SERVER_ERROR = (500, {}, "HTTP 500: Internal Server Error")


@pytest.fixture(autouse=True)
def _reset():
    rg._reset_response_cache(enabled=False)
    rg._reset_notices()
    yield
    rg._reset_notices()


def _routes(monkeypatch, table):
    """path(_p 형) → (status, body, err). 없는 경로는 404."""
    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        return table.get(path, NOT_FOUND)
    monkeypatch.setattr(rg, "_get", fake_get)


def _coll(*uris):
    return (200, {"Members": [{"@odata.id": u} for u in uris], "Members@odata.count": len(uris)}, None)


def _ok(body):
    return (200, body, None)


SW = "/redfish/v1/Fabrics/FlexGrid/Switches"
EP = "/redfish/v1/Fabrics/FlexGrid/Endpoints"


# ── _gather_fabric_members: (목록, 확인 여부) ─────────────────────────────────────────────────────────────

def test_fabric_members_link_absent_is_unconfirmed(monkeypatch):
    _routes(monkeypatch, {})
    errs = []
    assert rg._gather_fabric_members(IP, None, *CREDS, errs, kind="endpoint") == ([], False)
    assert errs == []


def test_fabric_members_404_is_unconfirmed_without_error(monkeypatch):
    _routes(monkeypatch, {})
    errs = []
    assert rg._gather_fabric_members(IP, EP, *CREDS, errs, kind="endpoint") == ([], False)
    assert errs == [], "선택 링크의 404 는 미제공 — 오류가 아니다(RD-F18)"


def test_fabric_members_failure_is_unconfirmed_with_error(monkeypatch):
    _routes(monkeypatch, {rg._p(EP): SERVER_ERROR})
    errs = []
    assert rg._gather_fabric_members(IP, EP, *CREDS, errs, kind="endpoint") == ([], False)
    assert [e["section"] for e in errs] == ["multi_node.fabrics.endpoint"]


def test_fabric_members_empty_collection_is_confirmed_zero(monkeypatch):
    _routes(monkeypatch, {rg._p(EP): _coll()})
    errs = []
    assert rg._gather_fabric_members(IP, EP, *CREDS, errs, kind="endpoint") == ([], True)


def test_fabric_members_members_key_absent_is_unconfirmed(monkeypatch):
    _routes(monkeypatch, {rg._p(EP): _ok({"Name": "Endpoint Collection"})})
    assert rg._gather_fabric_members(IP, EP, *CREDS, [], kind="endpoint") == ([], False)


def test_fabric_members_partial_member_failure_keeps_read_members(monkeypatch):
    _routes(monkeypatch, {
        rg._p(SW): _coll(SW + "/A", SW + "/B"),
        rg._p(SW + "/A"): _ok({"Id": "A", "SwitchType": "NUMAlink", "Status": {"State": "Enabled", "Health": "OK"}}),
        rg._p(SW + "/B"): SERVER_ERROR,
    })
    errs = []
    members, ok = rg._gather_fabric_members(IP, SW, *CREDS, errs, kind="switch")
    assert ok is False and [m["id"] for m in members] == ["A"]
    assert len(errs) == 1


def test_fabric_members_member_without_odata_id_is_unconfirmed(monkeypatch):
    _routes(monkeypatch, {
        rg._p(SW): (200, {"Members": [{"@odata.id": SW + "/A"}, {}]}, None),
        rg._p(SW + "/A"): _ok({"Id": "A"}),
    })
    members, ok = rg._gather_fabric_members(IP, SW, *CREDS, [], kind="switch")
    assert ok is False and [m["id"] for m in members] == ["A"]


# ── gather_fabrics: switch_count · endpoint_count · fabric_count 근거 ───────────────────────────────────────

def _fabric_table(fabric_body, extra=None):
    t = {
        "Fabrics": _coll("/redfish/v1/Fabrics/FlexGrid"),
        "Fabrics/FlexGrid": _ok(fabric_body),
        rg._p(SW): _coll(SW + "/HARP0", SW + "/HARP1"),
        rg._p(SW + "/HARP0"): _ok({"Id": "HARP0", "Status": {"State": "Enabled"}}),
        rg._p(SW + "/HARP1"): _ok({"Id": "HARP1", "Status": {"State": "Enabled"}}),
    }
    t.update(extra or {})
    return t


ROOT = {"Fabrics": {"@odata.id": "/redfish/v1/Fabrics"}}


def test_flexgrid_without_endpoints_link_counts_null_list_empty(monkeypatch):
    """실측 CSUS FlexGrid 모양: Switches 링크만 있고 Endpoints 키가 없다 → endpoint_count null · endpoints [] · switch_count 2."""
    _routes(monkeypatch, _fabric_table({"Id": "FlexGrid", "Switches": {"@odata.id": SW}}))
    st = {}
    fabrics, errs = rg.gather_fabrics(IP, ROOT, *CREDS, state_out=st)
    assert errs == [] and st == {"complete": True}
    (f,) = fabrics
    assert f["switch_count"] == 2 and f["endpoint_count"] is None and f["endpoints"] == []


def test_flexgrid_empty_endpoints_collection_is_confirmed_zero(monkeypatch):
    _routes(monkeypatch, _fabric_table({"Id": "FlexGrid", "Switches": {"@odata.id": SW}, "Endpoints": {"@odata.id": EP}},
                                       {rg._p(EP): _coll()}))
    fabrics, _ = rg.gather_fabrics(IP, ROOT, *CREDS)
    assert fabrics[0]["endpoint_count"] == 0 and fabrics[0]["endpoints"] == []


def test_fabrics_collection_failure_or_absent_link(monkeypatch):
    _routes(monkeypatch, {"Fabrics": SERVER_ERROR})
    st = {}
    fabrics, errs = rg.gather_fabrics(IP, ROOT, *CREDS, state_out=st)
    assert fabrics is None and len(errs) == 1 and st["complete"] is False
    st = {}
    assert rg.gather_fabrics(IP, {}, *CREDS, state_out=st) == (None, []) and st["complete"] is False


def test_fabrics_partial_fabric_failure_is_not_complete(monkeypatch):
    t = _fabric_table({"Id": "FlexGrid", "Switches": {"@odata.id": SW}})
    t["Fabrics"] = _coll("/redfish/v1/Fabrics/FlexGrid", "/redfish/v1/Fabrics/Other")
    t["Fabrics/Other"] = SERVER_ERROR
    _routes(monkeypatch, t)
    st = {}
    fabrics, errs = rg.gather_fabrics(IP, ROOT, *CREDS, state_out=st)
    assert [f["id"] for f in fabrics] == ["FlexGrid"] and st["complete"] is False and len(errs) == 1


# ── gather_composition_service: resource_block_count ───────────────────────────────────────────────────

RB = "/redfish/v1/CompositionService/ResourceBlocks"
COMP_ROOT = {"CompositionService": {"@odata.id": "/redfish/v1/CompositionService"}}


def _comp_table(rb_coll, blocks=None, with_link=True):
    t = {"CompositionService": _ok({"ServiceEnabled": True, **({"ResourceBlocks": {"@odata.id": RB}} if with_link else {})})}
    if rb_coll is not None:
        t[rg._p(RB)] = rb_coll
    t.update(blocks or {})
    return t


@pytest.mark.parametrize("label, table, count, n_blocks, n_errs", [
    ("link absent", _comp_table(None, with_link=False), None, 0, 0),
    ("collection 404", _comp_table(None), None, 0, 0),
    ("collection 500", _comp_table(SERVER_ERROR), None, 0, 1),
    ("empty collection", _comp_table(_coll()), 0, 0, 0),
    ("all blocks read", _comp_table(_coll(RB + "/a", RB + "/b"),
                                    {rg._p(RB + "/a"): _ok({"Id": "a"}), rg._p(RB + "/b"): _ok({"Id": "b"})}), 2, 2, 0),
    ("one block fails", _comp_table(_coll(RB + "/a", RB + "/b"),
                                    {rg._p(RB + "/a"): _ok({"Id": "a"}), rg._p(RB + "/b"): SERVER_ERROR}), None, 1, 1),
    ("one block 404", _comp_table(_coll(RB + "/a", RB + "/b"), {rg._p(RB + "/a"): _ok({"Id": "a"})}), None, 1, 0),
])
def test_resource_block_count_only_when_confirmed(monkeypatch, label, table, count, n_blocks, n_errs):
    _routes(monkeypatch, table)
    comp, errs = rg.gather_composition_service(IP, COMP_ROOT, *CREDS)
    assert comp["resource_block_count"] == count, label
    assert len(comp["resource_blocks"]) == n_blocks and len(errs) == n_errs, label


# ── _collect_multi_node_topology.summary: 수집 결과의 확인 여부를 그대로 옮긴다 ───────────────────────────────────

def _topology(monkeypatch, sys_r, mgr_r, chs_r, comp, fabrics, fab_complete):
    monkeypatch.setattr(rg, "gather_systems_multi", lambda *a, **k: sys_r)
    monkeypatch.setattr(rg, "gather_managers_multi", lambda *a, **k: mgr_r)
    monkeypatch.setattr(rg, "gather_chassis_multi", lambda *a, **k: chs_r)
    monkeypatch.setattr(rg, "gather_composition_service", lambda *a, **k: (comp, []))

    def fake_fabrics(*a, state_out=None, **k):
        if state_out is not None:
            state_out["complete"] = fab_complete
        return fabrics, []
    monkeypatch.setattr(rg, "gather_fabrics", fake_fabrics)
    return rg._collect_multi_node_topology(IP, "hpe", {"Systems": {}, "Managers": {}, "Chassis": {}}, *CREDS,
                                           manager_layout="rmc_primary")["summary"]


def test_topology_summary_counts(monkeypatch):
    two = {"partitions": [{"id": "P0"}, {"id": "P1"}], "errors": [], "complete": True}
    s = _topology(monkeypatch, two, {"managers": [{"id": "RMC"}], "errors": [], "complete": True},
                  {"chassis": [], "errors": [], "complete": True},
                  {"resource_block_count": 4, "resource_blocks": []}, [{"id": "FlexGrid"}], True)
    assert (s["partition_count"], s["manager_count"], s["chassis_count"], s["resource_block_count"], s["fabric_count"]) == (2, 1, 0, 4, 1)
    assert s["representative_partition"] == "P0"
    # 컬렉션을 끝까지 못 읽음 · CompositionService 미노출 · Fabrics 미노출 → 개수 null(종전 0), 목록은 그대로
    s = _topology(monkeypatch, {**two, "complete": False}, {"managers": [], "errors": [{}], "complete": False},
                  {"chassis": [{"id": "r001u01"}], "errors": [], "complete": False}, None, None, False)
    assert (s["partition_count"], s["manager_count"], s["chassis_count"], s["resource_block_count"], s["fabric_count"]) == \
        (None, None, None, None, None)
    assert s["representative_partition"] == "P0", "대표 partition 은 읽은 목록에서 정한다(종전과 같다)"
    # Fabrics 목록은 있으나 일부 Fabric 을 못 읽음 → fabric_count null
    s = _topology(monkeypatch, two, {"managers": [], "errors": [], "complete": True}, {"chassis": [], "errors": [], "complete": True},
                  {"resource_block_count": None, "resource_blocks": [{"id": "a"}]}, [{"id": "FlexGrid"}], False)
    assert s["fabric_count"] is None and s["resource_block_count"] is None and s["manager_count"] == 0


# ── 실측 recording 재생 (real_hpe_csus3200_01, manager_layout=rmc_primary) ─────────────────────────────────────

def _replay(name, mutate=None):
    case = FIX / name
    rec = json.loads((case / "recording.json").read_text(encoding="utf-8"))
    if mutate:
        mutate(rec)
    meta = json.loads((case / "meta.json").read_text(encoding="utf-8"))
    g, n, r = H.make_replayer(rec)
    return H.run_gather(g, n, realm_impl=r, manager_layout=meta.get("manager_layout"),
                        firmware_scope=meta.get("firmware_inventory_scope"))


def test_csus_recording_flexgrid_endpoints_null_and_counts_confirmed():
    mn = _replay("real_hpe_csus3200_01")["multi_node"]
    assert mn["summary"]["partition_count"] == 1 and mn["summary"]["manager_count"] == 1
    assert mn["summary"]["chassis_count"] == 3 and mn["summary"]["resource_block_count"] == 1 and mn["summary"]["fabric_count"] == 1
    (f,) = mn["fabrics"]
    assert f["id"] == "FlexGrid" and f["switch_count"] == 2
    assert f["endpoint_count"] is None and f["endpoints"] == [], "원천 FlexGrid 에 Endpoints 링크가 없다 — 0 이 아니라 미제공"


def test_csus_recording_service_root_without_fabrics_and_composition():
    def mutate(rec):
        root = rec["noauth::"][1]
        root.pop("Fabrics", None)
        root.pop("CompositionService", None)
    mn = _replay("real_hpe_csus3200_01", mutate)["multi_node"]
    assert mn["fabrics"] is None and mn["composition"] is None
    assert mn["summary"]["fabric_count"] is None and mn["summary"]["resource_block_count"] is None   # 종전 0


def test_csus_recording_managers_collection_failure():
    def mutate(rec):
        rec["get::Managers"] = [500, {}, "HTTP 500: Internal Server Error"]
    res = _replay("real_hpe_csus3200_01", mutate)
    mn = res["multi_node"]
    assert mn["summary"]["manager_count"] is None and mn["managers"] == []   # 종전 0
    assert any(e["section"] == "multi_node.managers" for e in mn["errors"])
