"""CSUS 섀시 링크 gating · composition count · FC HBA 카드 조건 notice (2026-10-27, C5 · FIX 6 · 03-storage-004 결정 11 A안).

  - 섀시 본문에 Power/PowerSubsystem(Thermal/ThermalSubsystem) 링크가 없으면 그 경로를 요청하지 않는다(미지원 = 404 와 같은 분류).
    PowerSubsystem 만 있으면 legacy GET 없이 신 경로, EnvironmentMetrics 링크가 없으면 그 GET 도 없다. 본문을 모르면 종전과 같다.
  - ResourceBlock 의 Processors/Memory 가 idRef 배열이 아니면 count 는 null (0 날조 금지, FIX 6).
  - FC HBA "링크 상태 미제공" notice 에 카드 조건(LinkUp/LinkDown · Timestamp)을 덧붙이는 3중 판별:
      (1) FC 전용 카드(hbas 생성 ∧ 이더넷 포트 0) (2) 바로 그 어댑터의 Controllers[0].Links.PCIeDevices 1건으로 받은 PCIeDevice 본문
      (3) MessageId 등록부 접두가 adapter 가 선언한 값(pcie_port_link_condition_registries) ∧ 마지막 세그먼트 LinkUp/LinkDown.
    셋 중 하나라도 빠지면 종전 문장만. hbas[].link_status 값은 바꾸지 않는다(A안). RAID/NIC 카드의 LinkUp 은 섞이지 않는다(사용자 3차 검토).
실측: 용인 2차 csus3200_01/03 + 1차 CSUS 01(fixture), DL380/SR650/Dell 은 대조군. 기대값은 손으로 적었다.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "tests" / "integration"))

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
import emulator_harness as H  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "redfish"
CREDS = ("u", "p", 30, False)
H3 = ["H3Alert"]


def _routed(routes, calls):
    def fake(bmc_ip, path, *a, **kw):
        calls.append(path)
        return routes.get(path, (404, {}, "HTTP 404: Not Found"))
    return fake


def _collect(name, registries, mutate=None):
    """실녹화를 emulator_harness.run_gather(main() 1:1 미러 — 대표 시리얼 resolver · product_hint 포함)로 재생하고
    pcie_link_registries 를 넘긴다. 요청 다중집합은 test_request_budget._replay_counts 와 같은 방식(get + noauth::)으로 센다."""
    case = FIX / name
    rec = json.loads((case / "recording.json").read_text(encoding="utf-8"))
    if mutate:
        mutate(rec)
    meta = json.loads((case / "meta.json").read_text(encoding="utf-8")) if (case / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    calls = Counter()

    def gw(bmc_ip, path, u, p, t, v):
        calls[path] += 1
        return g(bmc_ip, path, u, p, t, v)

    def nw(bmc_ip, path, t, v):
        calls["noauth::" + path] += 1
        return n(bmc_ip, path, t, v)

    res = H.run_gather(gw, nw, realm_impl=r, manager_layout=meta.get("manager_layout"),
                       firmware_scope=meta.get("firmware_inventory_scope"), pcie_link_registries=registries)
    return res["data"], res["multi_node"], [x["message"] for x in rg.notices()], calls, res


def _fc_notices(notices):
    return [m for m in notices if "링크 상태 미제공" in m]


# ── 1. FC HBA 카드 조건 notice — 실측 긍정 · 음성 ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,cards", [
    ("real_hpe_csus3200_01", {"PCIeCard11": ("rack1/chassis_u1/cpu2/io_slot11", "2026-10-16T01:06:26Z"), "PCIeCard14": ("rack1/chassis_u1/cpu3/io_slot14", "2026-10-21T01:16:06Z")}),
    ("real_hpe_csus3200_03", None),
    ("real_hpe_csus3200", None),      # 1차 CSUS 01 (H3Alert.1.7)
])
def test_csus_fc_cards_get_card_condition_appended_and_values_stay_down(name, cards):
    data, _, notices, _, _ = _collect(name, H3)
    fc = _fc_notices(notices)
    hbas = data["network_adapters"]["fc_hbas"]
    assert hbas and all(h["link_status"] == "down" for h in hbas)                      # A안: 값은 그대로 down
    assert fc and all("링크 단절을 확인한 값 아님; 카드 " in m and " 조건 LinkUp(" in m and ", 카드 단위)" in m for m in fc)
    if cards:
        for card, (label, ts) in cards.items():
            m = next(x for x in fc if f"네트워크 카드 {card}:" in x)
            assert f"카드 {label} 조건 LinkUp({ts}, 카드 단위)" in m
    # 음성 (a)(b): RAID(PCIeDevices/3)·Mellanox NIC 카드의 LinkUp 은 어떤 notice 에도 섞이지 않는다
    assert not [m for m in notices if "io_slot3 " in m or "io_slot3)" in m or "PCIeCard1:" in m and "조건" in m]
    assert not [m for m in notices if ("PCIeCard8" in m or "PCIeCard9" in m or "PCIeCard16" in m) and "조건 LinkUp" in m]


def test_csus_without_fc_card_is_unchanged():
    data, _, notices, _, _ = _collect("real_hpe_csus3200_02", H3)
    assert data["network_adapters"]["fc_hbas"] == [] and not _fc_notices(notices)


def test_no_phrase_without_registry_declaration():
    """(d) adapter 가 등록부를 선언하지 않으면 종전 문장만 — 벤더 이름으로 가르지 않는다."""
    _, _, notices, _, _ = _collect("real_hpe_csus3200_01", None)
    fc = _fc_notices(notices)
    assert fc and all("조건 LinkUp" not in m and "링크 단절을 확인한 값 아님" not in m for m in fc)
    _, _, notices2, _, _ = _collect("real_hpe_csus3200_01", ["OtherRegistry"])
    assert all("조건 LinkUp" not in m for m in _fc_notices(notices2))


def test_no_phrase_when_only_pcie_training_condition_or_ambiguous_links():
    """(c) PcieLinkTrainingOk 만 남기면 문구 없음 · (f) 링크 2건이면 문구 없음."""
    def only_training(rec):
        for k in list(rec):
            if "/PCIeDevices/" in k and isinstance(rec[k][1], dict):
                conds = (rec[k][1].get("Status") or {}).get("Conditions") or []
                rec[k][1]["Status"]["Conditions"] = [c for c in conds if not str(c.get("MessageId", "")).endswith(("LinkUp", "LinkDown"))]
    _, _, notices, _, _ = _collect("real_hpe_csus3200_01", H3, mutate=only_training)
    fc = _fc_notices(notices)
    assert fc and all("조건 LinkUp" not in m for m in fc)

    def two_links(rec):
        for k in list(rec):
            if k.endswith("/NetworkAdapters/PCIeCard11") and isinstance(rec[k][1], dict):
                ctrl = rec[k][1]["Controllers"][0]
                ctrl["Links"]["PCIeDevices"] = ctrl["Links"]["PCIeDevices"] + [{"@odata.id": "/redfish/v1/Chassis/r001u01/PCIeDevices/14"}]
    _, _, notices2, _, _ = _collect("real_hpe_csus3200_01", H3, mutate=two_links)
    m11 = next(x for x in _fc_notices(notices2) if "PCIeCard11:" in x)
    assert "조건 LinkUp" not in m11
    m14 = next(x for x in _fc_notices(notices2) if "PCIeCard14:" in x)
    assert "조건 LinkUp" in m14                                                       # 다른 카드는 그대로


def test_linkdown_condition_is_reported_as_card_level_only():
    """합성 변형(실측 대체 아님): LinkDown 이어도 포트 값은 down 그대로이고 문구만 LinkDown."""
    def flip(rec):
        b = rec["get::Chassis/r001u01/PCIeDevices/11"][1]
        for c in b["Status"]["Conditions"]:
            if str(c.get("MessageId", "")).endswith("LinkUp"):
                c["MessageId"] = c["MessageId"][:-len("LinkUp")] + "LinkDown"; c.pop("Timestamp", None)
    data, _, notices, _, _ = _collect("real_hpe_csus3200_01", H3, mutate=flip)
    m11 = next(x for x in _fc_notices(notices) if "PCIeCard11:" in x)
    assert "조건 LinkDown(Timestamp 없음, 카드 단위)" in m11
    assert all(h["link_status"] == "down" for h in data["network_adapters"]["fc_hbas"])


@pytest.mark.parametrize("name", ["real_hpe_dl380_gen12_01", "real_lenovo_sr650_v4_02", "real_dell_r740"])
def test_vendors_with_port_link_status_are_untouched(name):
    """(e) Port LinkStatus 가 있는 장비: notice 문구 없음, GOLDEN_KEYS 데이터 동일."""
    data, _, notices, _, _ = _collect(name, H3)
    assert not _fc_notices(notices)
    gold = json.loads((FIX / name / "expected_output.json").read_text(encoding="utf-8"))
    assert json.loads(json.dumps(data, sort_keys=True)) == gold["data"]


def test_condition_helper():
    body = {"Status": {"Conditions": [
        {"MessageId": "H3Alert.1.8.PcieLinkTrainingOk", "MessageArgs": ["x"], "Timestamp": "t0"},
        {"MessageId": "H3Alert.1.8.LinkUp", "MessageArgs": ["rack1/slot11"], "Timestamp": "2026-10-16T01:06:26Z"},
        {"MessageId": "H3Alert.1.8.LinkDown", "MessageArgs": ["later"], "Timestamp": "t2"},
    ]}}
    assert rg._pcie_port_link_condition(body, ["H3Alert"]) == ("LinkUp", "2026-10-16T01:06:26Z", "rack1/slot11")
    assert rg._pcie_port_link_condition(body, ["Other"]) is None
    assert rg._pcie_port_link_condition(body, None) is None and rg._pcie_port_link_condition(body, []) is None
    assert rg._pcie_port_link_condition({"Status": {"Conditions": [{"MessageId": "H3Alert.1.8.LinkUp"}]}}, ["H3Alert"]) == ("LinkUp", None, None)
    assert rg._pcie_port_link_condition(None, ["H3Alert"]) is None


# ── 2. 섀시 링크 gating — 요청 수 ────────────────────────────────────────────────────────────────────────────────────────

def test_csus_fixed_path_404s_are_no_longer_requested():
    """RackGroup/Rack1 의 Power·PowerSubsystem·Thermal·ThermalSubsystem(8) + r001u01 의 Power·Thermal·EnvironmentMetrics(×2 = 6) 가 사라진다."""
    _, _, _, calls, _ = _collect("real_hpe_csus3200_01", H3)
    gone = {"Chassis/RackGroup/Power", "Chassis/RackGroup/PowerSubsystem", "Chassis/RackGroup/Thermal", "Chassis/RackGroup/ThermalSubsystem",
            "Chassis/Rack1/Power", "Chassis/Rack1/PowerSubsystem", "Chassis/Rack1/Thermal", "Chassis/Rack1/ThermalSubsystem",
            "Chassis/r001u01/Power", "Chassis/r001u01/Thermal", "Chassis/r001u01/EnvironmentMetrics"}
    assert not (gone & set(calls)), gone & set(calls)
    assert "Chassis/r001u01/PowerSubsystem" in calls and "Chassis/r001u01/ThermalSubsystem" in calls


def test_gating_rules_synthetic(monkeypatch):
    legacy_only = {"Power": {"@odata.id": "/redfish/v1/Chassis/1/Power"}}
    new_only = {"PowerSubsystem": {"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem"}, "ThermalSubsystem": {"@odata.id": "/redfish/v1/Chassis/1/ThermalSubsystem"}}
    none_ = {"Id": "RackGroup"}
    routes = {"Chassis/1/Power": (200, {"PowerSupplies": [{"Name": "P", "PowerCapacityWatts": 10, "Status": {"State": "Enabled"}}]}, None),
              "Chassis/1/PowerSubsystem": (200, {"PowerSupplies": {"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies"}}, None),
              "Chassis/1/PowerSubsystem/PowerSupplies": (200, {"Members": []}, None),
              "Chassis/1/ThermalSubsystem": (200, {}, None)}
    # 본문 없음(종전): legacy 먼저
    calls = []; monkeypatch.setattr(rg, "_get", _routed(routes, calls))
    out, errs = rg.gather_power("ip", "/redfish/v1/Chassis/1", *CREDS)
    assert calls[0] == "Chassis/1/Power" and out["power_supplies"]
    # 링크 둘 다 없음: 요청 0 + 404 분류
    calls = []; monkeypatch.setattr(rg, "_get", _routed(routes, calls))
    out, errs = rg.gather_power("ip", "/redfish/v1/Chassis/1", *CREDS, chassis_body=none_)
    assert calls == [] and out == {} and rg._is_404_only_error(errs)
    out, errs = rg.gather_thermal("ip", "/redfish/v1/Chassis/1", *CREDS, chassis_body=none_)
    assert calls == [] and out == {} and rg._is_404_only_error(errs)
    # 신 링크만: legacy GET 없이 신 경로, EnvironmentMetrics 도 요청 없음
    calls = []; monkeypatch.setattr(rg, "_get", _routed(routes, calls))
    rg.gather_power("ip", "/redfish/v1/Chassis/1", *CREDS, chassis_body=new_only)
    assert "Chassis/1/Power" not in calls and "Chassis/1/EnvironmentMetrics" not in calls and calls[0] == "Chassis/1/PowerSubsystem"
    # legacy 링크 있음: 종전대로
    calls = []; monkeypatch.setattr(rg, "_get", _routed(routes, calls))
    out, _ = rg.gather_power("ip", "/redfish/v1/Chassis/1", *CREDS, chassis_body=legacy_only)
    assert calls[0] == "Chassis/1/Power" and out["power_supplies"]


@pytest.mark.parametrize("name", ["real_hpe_dl380_gen12_01", "real_lenovo_sr650_v4_01", "real_dell_r740"])
def test_other_vendors_request_sets_unchanged(name):
    """DL380/SR650/Dell 의 요청 다중집합은 request_budget 과 같다 (gating 은 링크가 있는 장비에서 요청을 늘리지도 줄이지도 않는다)."""
    _, _, _, calls, _ = _collect(name, H3)
    budget = json.loads((FIX / name / "request_budget.json").read_text(encoding="utf-8"))
    actual = sorted(f"{p} x{c}" for p, c in calls.items())
    assert actual == sorted(budget["expected_http_calls"])


# ── 3. composition count (FIX 6) ─────────────────────────────────────────────────────────────────────────────────────────

def test_composition_counts_are_null_when_not_idref_arrays(monkeypatch):
    root = {"CompositionService": {"@odata.id": "/redfish/v1/CompositionService"}}
    routes = {
        "CompositionService": (200, {"ServiceEnabled": True, "ResourceBlocks": {"@odata.id": "/redfish/v1/CompositionService/ResourceBlocks"}}, None),
        "CompositionService/ResourceBlocks": (200, {"Members": [{"@odata.id": "/redfish/v1/CompositionService/ResourceBlocks/A"}, {"@odata.id": "/redfish/v1/CompositionService/ResourceBlocks/B"}]}, None),
        "CompositionService/ResourceBlocks/A": (200, {"Id": "A", "Processors": {"@odata.id": "/x"}, "Memory": {"@odata.id": "/y"}}, None),     # CSUS 모양: 컬렉션 링크
        "CompositionService/ResourceBlocks/B": (200, {"Id": "B", "Processors": [{"@odata.id": "/p1"}, {"@odata.id": "/p2"}], "Memory": []}, None),
    }
    monkeypatch.setattr(rg, "_get", _routed(routes, []))
    out, errs = rg.gather_composition_service("ip", root, *CREDS)
    blocks = {b["id"]: b for b in out["resource_blocks"]}
    assert blocks["A"]["processor_count"] is None and blocks["A"]["memory_count"] is None
    assert blocks["B"]["processor_count"] == 2 and blocks["B"]["memory_count"] == 0


def test_csus_recording_composition_counts_are_null():
    _, multi, _, _, _ = _collect("real_hpe_csus3200_01", H3)
    comp = (multi or {}).get("composition")
    assert comp and comp["resource_blocks"]
    assert all(b["processor_count"] is None and b["memory_count"] is None for b in comp["resource_blocks"])
