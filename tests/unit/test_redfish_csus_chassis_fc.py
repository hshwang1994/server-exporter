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


# ── 1b. 2026-10-28: 카드 정상 · 카드 LinkUp 은 FC 포트 링크가 아니다 (사례 5 · 6 · 7) ─────────────────────────────────────────

def _csus01_recording():
    return json.loads((FIX / "real_hpe_csus3200_01" / "recording.json").read_text(encoding="utf-8"))


def _has_linkup_condition(status):
    return any(str(c.get("MessageId", "")).endswith(".LinkUp") for c in (status or {}).get("Conditions") or [])


def test_csus_healthy_fc_cards_without_port_link_status_stay_down():
    """사례 5 (실측 녹화 재생): 카드는 정상(PCIeDevice Health OK · State Enabled · H3Alert LinkUp 조건)이고 FC 포트에 LinkStatus 가 없다 → down.

    카드 상태 · 카드 조건은 포트 링크 값이 아니다 — `링크 상태 미제공` notice 끝에 카드 단위 참고로만 붙고(A안), `값 미확정` notice 는 없다.
    """
    rec = _csus01_recording()
    for card in ("11", "14"):
        st = rec[f"get::Chassis/r001u01/PCIeDevices/{card}"][1]["Status"]
        assert st["Health"] == "OK" and st["State"] == "Enabled" and _has_linkup_condition(st), card
        for port in ("1", "2"):
            assert "LinkStatus" not in rec[f"get::Chassis/r001u01/NetworkAdapters/PCIeCard{card}/Ports/PCIeCard{card}Port{port}"][1]
    data, _, notices, _, _ = _collect("real_hpe_csus3200_01", H3)
    got = {(h["adapter_id"], h["port_id"]): h["link_status"] for h in data["network_adapters"]["fc_hbas"]}
    assert got == {("PCIeCard11", "PCIeCard11Port1"): "down", ("PCIeCard11", "PCIeCard11Port2"): "down",
                   ("PCIeCard14", "PCIeCard14Port1"): "down", ("PCIeCard14", "PCIeCard14Port2"): "down"}
    assert len(_fc_notices(notices)) == 2 and not [m for m in notices if "링크 상태 값 미확정" in m]


def test_csus_raid_and_nic_card_linkup_never_becomes_an_fc_hba():
    """사례 6 (실측 녹화 재생): RAID(PCIeDevices/3) · NIC(1/8/9/16) 카드도 같은 LinkUp 조건을 갖지만 FC HBA 가 생기지 않고 up 도 없다.

    FC 포트의 network ports 쪽 link_status 는 네트워크 정규화 그대로(unknown) — HBA 의 down 정책이 네트워크로 넘어가지 않는다.
    """
    rec = _csus01_recording()
    for dev in ("1", "3", "8", "9", "16"):
        assert _has_linkup_condition(rec[f"get::Chassis/r001u01/PCIeDevices/{dev}"][1]["Status"]), dev
    data, _, _, _, _ = _collect("real_hpe_csus3200_01", H3)
    na = data["network_adapters"]
    assert {h["adapter_id"] for h in na["fc_hbas"]} == {"PCIeCard11", "PCIeCard14"}
    assert all(h["link_status"] == "down" for h in na["fc_hbas"])
    nic = [p for p in na["ports"] if p["adapter_id"] in ("PCIeCard1", "PCIeCard8", "PCIeCard9", "PCIeCard16")]
    assert len(nic) == 8 and all(p["port_type"] == "Ethernet" for p in nic)
    fc_ports = [p for p in na["ports"] if p["adapter_id"] in ("PCIeCard11", "PCIeCard14")]
    assert len(fc_ports) == 4 and all(p["port_type"] == "FibreChannel" and p["link_status"] == "unknown" for p in fc_ports)


def _synthetic_card(card, ports, pcie_condition=None):
    """합성 카드 1장의 응답 경로(실장비 응답이 아니다). ports = [(port_id, 본문)].

    pcie_condition 이 있으면 Controllers[0].Links.PCIeDevices 1건 + 그 PCIeDevice(Health OK · State Enabled · 조건 1건)를 둔다.
    """
    base = "Chassis/X/NetworkAdapters/" + card
    uri = "/redfish/v1/" + base
    adapter = {"Id": card, "Model": "Synthetic " + card, "Manufacturer": "Synthetic", "Ports": {"@odata.id": uri + "/Ports"}}
    routes = {
        "Chassis/X/NetworkAdapters": (200, {"Members": [{"@odata.id": uri}]}, None),
        base + "/Ports": (200, {"Members": [{"@odata.id": uri + "/Ports/" + pid} for pid, _ in ports]}, None),
    }
    for pid, body in ports:
        routes[base + "/Ports/" + pid] = (200, dict(body, Id=pid), None)
    if pcie_condition:
        adapter["Controllers"] = [{"Links": {"PCIeDevices": [{"@odata.id": "/redfish/v1/Chassis/X/PCIeDevices/" + card}]}}]
        routes["Chassis/X/PCIeDevices/" + card] = (200, {"Id": card, "Status": {"Health": "OK", "State": "Enabled", "Conditions": [
            {"MessageId": pcie_condition, "MessageArgs": ["syn/" + card], "Timestamp": "2026-10-28T00:00:00Z"}]}}, None)
    routes[base] = (200, adapter, None)
    return routes


def _gather_synthetic(monkeypatch, routes):
    rg._reset_notices()
    monkeypatch.setattr(rg, "_get", _routed(routes, []))
    out, _ = rg.gather_network_adapters_chassis("ip", "/redfish/v1/Chassis/X", *CREDS, pcie_link_registries=H3)
    return out, [x["message"] for x in rg.notices()]


def _fc_port(n, **kw):
    return dict({"FibreChannel": {"AssociatedWorldWideNames": ["10:00:00:00:c9:00:00:%02x" % n]}}, **kw)


def test_synthetic_healthy_looking_fc_port_without_link_status_is_down(monkeypatch):
    """사례 5 (합성 — 실장비 Up 근거 아님): 포트 Status OK · LinkState Enabled · CurrentSpeedGbps 32 와 카드 LinkUp 조건이 다 있어도
    포트 LinkStatus 가 없으면 down + `링크 상태 미제공`. 관리 상태 · 속도 · 장치 상태는 링크 판정 필드가 아니다."""
    looks_fine = {"Status": {"Health": "OK", "State": "Enabled"}, "LinkState": "Enabled", "CurrentSpeedGbps": 32}
    out, msgs = _gather_synthetic(monkeypatch, _synthetic_card(
        "FC5", [("1", _fc_port(1, **looks_fine)), ("2", _fc_port(2, **looks_fine))], pcie_condition="H3Alert.1.8.LinkUp"))
    assert [(h["port_id"], h["link_status"]) for h in out["fc_hbas"]] == [("1", "down"), ("2", "down")]
    fc = _fc_notices(msgs)
    assert len(fc) == 1 and "네트워크 카드 FC5: FC 포트 1, 2 링크 상태 미제공, down 으로 기록" in fc[0]
    assert "카드 syn/FC5 조건 LinkUp(2026-10-28T00:00:00Z, 카드 단위)" in fc[0]
    assert not [m for m in msgs if "링크 상태 값 미확정" in m]


def test_synthetic_fused_card_ethernet_linkup_never_lifts_the_fc_port(monkeypatch):
    """사례 6 (합성 — 실장비 Up 근거 아님): 한 카드에 Ethernet 포트(LinkUp)와 LinkStatus 없는 FC 포트가 함께 있다.

    FC hba 는 down, Ethernet 링크 up 은 network ports 에만 있다. 이더넷 포트가 있는 카드라 카드 조건 문구도 붙지 않는다(A안 조건 (1)).
    """
    eth = {"Ethernet": {"AssociatedMACAddresses": ["AA:BB:CC:00:00:01"]}, "LinkStatus": "LinkUp"}
    out, msgs = _gather_synthetic(monkeypatch, _synthetic_card("MIX6", [("1", eth), ("2", _fc_port(2))], pcie_condition="H3Alert.1.8.LinkUp"))
    assert [(h["port_id"], h["link_status"]) for h in out["fc_hbas"]] == [("2", "down")]
    ports = {p["port_id"]: (p["port_type"], p["link_status"]) for p in out["ports"]}
    assert ports == {"1": ("Ethernet", "up"), "2": ("FibreChannel", "unknown")}
    fc = _fc_notices(msgs)
    assert len(fc) == 1 and "FC 포트 2 링크 상태 미제공" in fc[0] and "조건 LinkUp" not in fc[0]


def test_synthetic_four_fc_ports_are_judged_one_by_one(monkeypatch):
    """사례 7 (합성 — 실장비 Up 근거 아님): 한 카드 4포트 LinkUp · LinkDown · 키 없음 · Enabled → up · down · down · down.

    미제공 · 미확정 notice 에는 해당 포트만 적힌다. network ports 는 네트워크 정규화를 따른다 — 2026-10-29 (SA-09) 부터 Enabled 는 링크 값이
    아니라 unknown 이고(종전 up) 원문은 network_adapters notice 1건으로 남는다. HBA 값 · '값 미확정' notice 는 종전 그대로다(HBA 정책 불변).
    """
    out, msgs = _gather_synthetic(monkeypatch, _synthetic_card("FC7", [
        ("1", _fc_port(1, LinkStatus="LinkUp")), ("2", _fc_port(2, LinkStatus="LinkDown")),
        ("3", _fc_port(3)), ("4", _fc_port(4, LinkStatus="Enabled"))]))
    assert [(h["port_id"], h["link_status"]) for h in out["fc_hbas"]] == [("1", "up"), ("2", "down"), ("3", "down"), ("4", "down")]
    assert [m for m in msgs if "링크 상태 미제공" in m] == [
        "네트워크 카드 FC7: FC 포트 3 링크 상태 미제공, down 으로 기록 (storage.hbas link_status)"]
    assert [m for m in msgs if "링크 상태 값 미확정" in m and "storage.hbas" in m] == [
        "네트워크 카드 FC7: FC 포트 4=Enabled 링크 상태 값 미확정, down 으로 기록 (storage.hbas link_status)"]
    assert [m for m in msgs if "network.ports link_status" in m] == [
        "네트워크 포트 링크 상태 값 미확정, unknown 으로 기록 (network.ports link_status) — FC7/4=Enabled"]
    assert {p["port_id"]: p["link_status"] for p in out["ports"]} == {"1": "up", "2": "down", "3": "unknown", "4": "unknown"}


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
