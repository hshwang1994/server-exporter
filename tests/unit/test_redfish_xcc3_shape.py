"""Lenovo XCC3 응답 모양 (2026-10-27, C4 — 03-network-001/002 · 04-firmware-006 · 05-power-003 · 02-memory-003 · hardware.oem).

실측(용인 2차 SR650 V4 ×4 + 1차 SR650 V4, DL380 Gen12, CSUS)으로 다음을 고정한다.
  (a) 호스트 EthernetInterfaces 중 FC/IB 포트 주소(8옥텟 또는 network_adapters.ports 의 FC/IB 주소)는 network.interfaces 에서 제외하고
      normalize notice 1건을 남긴다. 모듈 raw(data.network)·ports[]·hbas[] 개수는 바뀌지 않는다 (사용자 3차 지시 (iii)).
  (b) Status.State=Disabled 이고 Version 이 빈 '-Pending' 펌웨어는 제외 + notice, Version 이 있으면 pending:true 보존.
  (c) PSU 문자열 strip · link unknown ∧ speed null 인 NIC 만 같은 MAC 의 Ethernet 포트로 보충 · DIMM locator DeviceLocator → ServiceLabel → Slot ·
      Lenovo hardware.oem machine_type/led_indicator 를 System.SubModel/IndicatorLED 로.
  (i) XCC3 는 NetworkDeviceFunctions 컬렉션이 200·0건이어도 Port 신호로 FC 포트 4건이 hbas·ports 에 수집된다 (사용자 3차 지시).
  (ii) 디스크·FC 가 없는 장비는 physical_disks/hbas 가 정확히 [] 이고 placeholder 가 없다.
기대값은 손으로 적었다.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "tests" / "integration"))
sys.path.insert(0, str(REPO / "tests" / "scripts"))

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
import inventory_parity as IP  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "redfish"
NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"


def _set_fact(task_name, key):
    for t in yaml.safe_load(NORM.read_text(encoding="utf-8")):
        if isinstance(t, dict) and t.get("name") == task_name:
            return t["ansible.builtin.set_fact"][key]
    raise AssertionError(task_name)


BUNDLE_TPL = _set_fact("redfish | normalize_standard | interfaces (bundle)", "_rf_norm_interfaces_bundle")
NOTICE_TPL = _set_fact("redfish | normalize_standard | interfaces", "_rf_norm_notices")


def _render(tpl, **ctx):
    return NativeEnvironment().from_string(tpl).render(**ctx)


def _golden(name):
    return json.loads((FIX / name / "expected_output.json").read_text(encoding="utf-8"))


def _replay(name):
    case = FIX / name
    rec = json.loads((case / "recording.json").read_text(encoding="utf-8"))
    meta = json.loads((case / "meta.json").read_text(encoding="utf-8")) if (case / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    res = H.run_gather(g, n, realm_impl=r, manager_layout=meta.get("manager_layout"), firmware_scope=meta.get("firmware_inventory_scope"))
    return res, [x["message"] for x in rg.notices()]


# ── (a) FC/IB 주소 EthernetInterfaces 제외 — normalize 층, 모듈 raw 불변 ──────────────────────────────────────────────────

def _bundle_for(name):
    g = _golden(name)["data"]
    return _render(BUNDLE_TPL, _rf_d_network=g["network"], _rf_d_netad=g["network_adapters"]), g


def test_xcc3_fc_in_host_ethernet_is_excluded_from_interfaces_only():
    b, g = _bundle_for("real_lenovo_sr650_v4_02")
    assert len(g["network"]) == 9 and b["fc_excluded"] == 4 and len(b["interfaces"]) == 5
    macs = [i["mac"] for i in b["interfaces"]]
    assert all(len(m.replace(":", "")) == 12 for m in macs)                          # 남은 것은 전부 6옥텟
    assert "21:00:f4:c7:aa:a4:6f:fe" not in macs                                      # = hbas[0].wwpn
    # 모듈 raw·ports·hbas 는 그대로 (사용자 3차 지시 (iii)): 제외는 interfaces 만
    assert len(g["network_adapters"]["fc_hbas"]) == 4
    assert sum(1 for p in g["network_adapters"]["ports"] if p["port_type"] == "FibreChannel") == 4
    notices = _render(NOTICE_TPL, _rf_norm_interfaces_bundle=b)
    assert len(notices) == 1 and notices[0]["section"] == "network" and "4건" in notices[0]["message"]


@pytest.mark.parametrize("name,ifaces,fc_hbas", [
    ("real_lenovo_sr650_v4_03", 15 - 4, 4),
    ("real_lenovo_sr650_v4_01", 5, 0),                 # FC 없음 → 제외 0
    ("real_hpe_dl380_gen12_01", 10, 4),               # iLO 7: FC 포트는 EthernetInterfaces 에 없다 → 제외 0
    ("real_hpe_csus3200_01", 8, 4),
    ("real_dell_r740", 12, 4),                       # Dell: 호스트 EthernetInterfaces 12 (FC 포트는 NetworkAdapters 에만)
])
def test_exclusion_only_touches_hosts_that_expose_fc_as_ethernet(name, ifaces, fc_hbas):
    b, g = _bundle_for(name)
    assert len(b["interfaces"]) == ifaces and len(g["network_adapters"]["fc_hbas"]) == fc_hbas
    assert b["fc_excluded"] == len(g["network"]) - ifaces
    notices = _render(NOTICE_TPL, _rf_norm_interfaces_bundle=b)
    assert (len(notices) == 1) == (b["fc_excluded"] > 0)                          # 제외가 있을 때만 notice 1건


def test_exclusion_rule_uses_address_length_and_fc_ib_port_addresses():
    netad = {"ports": [
        {"adapter_id": "a", "port_id": "1", "port_type": "FibreChannel", "associated_address": "21:00:00:11:22:33:44:55", "link_status": "down"},
        {"adapter_id": "b", "port_id": "1", "port_type": "InfiniBand", "associated_address": "00:11:22:33:44:55", "link_status": "up"},
        {"adapter_id": "c", "port_id": "1", "port_type": "Ethernet", "associated_address": "aa:bb:cc:dd:ee:01", "link_status": "up", "current_link_speed_mbps": 25000},
    ], "adapters": [], "fc_hbas": [], "infiniband": []}
    network = [
        {"id": "NIC1", "name": "eth", "mac": "aa:bb:cc:dd:ee:01", "link_status": None, "speed_mbps": None, "ipv4": []},     # unknown+null → 포트로 보충
        {"id": "NIC2", "name": "eth", "mac": "aa:bb:cc:dd:ee:02", "link_status": None, "speed_mbps": None, "ipv4": []},     # 포트 없음 → 그대로
        {"id": "NIC3", "name": "fc", "mac": "21:00:00:11:22:33:44:55", "link_status": None, "speed_mbps": 0, "ipv4": []},    # 8옥텟 → 제외
        {"id": "NIC4", "name": "ib", "mac": "00:11:22:33:44:55", "link_status": None, "speed_mbps": 0, "ipv4": []},         # IB 포트 주소와 같음 → 제외
        {"id": "NIC5", "name": "eth", "mac": "aa:bb:cc:dd:ee:03", "link_status": "LinkUp", "speed_mbps": 1000, "ipv4": []},  # 값이 있으면 보충 안 함
    ]
    b = _render(BUNDLE_TPL, _rf_d_network=network, _rf_d_netad=netad)
    out = {i["id"]: i for i in b["interfaces"]}
    assert sorted(out) == ["NIC1", "NIC2", "NIC5"] and b["fc_excluded"] == 2
    assert out["NIC1"]["link_status"] == "up" and out["NIC1"]["speed_mbps"] == 25000
    assert out["NIC2"]["link_status"] == "unknown" and out["NIC2"]["speed_mbps"] is None
    assert out["NIC5"]["link_status"] == "linkup" and out["NIC5"]["speed_mbps"] == 1000
    assert out["NIC5"]["is_primary"] is False and out["NIC1"]["is_primary"] is True   # IPv4 없음 → 첫 up NIC fallback


# ── (i)(ii) 사용자 3차 지시 — XCC3 FC 포트 수집 · 장치 없는 장비의 빈 목록 ──────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["real_lenovo_sr650_v4_02", "real_lenovo_sr650_v4_03"])
def test_xcc3_collects_fc_ports_even_with_empty_ndf_collection(name):
    rec = json.loads((FIX / name / "recording.json").read_text(encoding="utf-8"))
    res, _ = _replay(name)
    # FC 카드(hbas 의 adapter_id)의 NetworkDeviceFunctions 컬렉션은 200 이지만 0건이다 — NIC 카드(E810)는 NDF 가 있다
    fc_adapters = {h["adapter_id"] for h in res["data"]["network_adapters"]["fc_hbas"]}
    assert fc_adapters
    for aid in fc_adapters:
        key = f"get::Chassis/1/NetworkAdapters/{aid}/NetworkDeviceFunctions"
        assert rec[key][0] == 200 and (rec[key][1].get("Members@odata.count") or len(rec[key][1].get("Members") or [])) == 0, aid
    assert len(res["data"]["network_adapters"]["fc_hbas"]) == 4
    assert sum(1 for p in res["data"]["network_adapters"]["ports"] if p["port_type"] == "FibreChannel") == 4
    parity = IP.run(recording=str(FIX / name / "recording.json"), module_doc=res)
    assert parity["verdict"]["pass"] and parity["exposure"]["fc_ports"] == 4


@pytest.mark.parametrize("name,disks,hbas", [
    ("real_hpe_csus3200_02", 4, 0),      # FC 카드 없음
    ("real_hpe_dl380_gen12_03", 0, 0),   # 전원 Off — Storage 0
    ("real_hpe_csus3200", 0, 4),         # 1차 CSUS 01 — 디스크 미노출
    ("real_lenovo_sr650_v4_01", 4, 0),
])
def test_absent_devices_give_exact_empty_lists_not_placeholders(name, disks, hbas):
    res, _ = _replay(name)
    drives = [d for c in res["data"]["storage"]["controllers"] for d in (c.get("drives") or [])]
    assert len(drives) == disks and len(res["data"]["network_adapters"]["fc_hbas"]) == hbas
    assert all(d.get("id") or d.get("serial") for d in drives)
    parity = IP.run(recording=str(FIX / name / "recording.json"), module_doc=res)
    assert parity["verdict"]["pass"]


# ── (b) Disabled · Version 없는 -Pending 제외 ───────────────────────────────────────────────────────────────────────────────

def _routed(routes, calls):
    def fake(bmc_ip, path, *a, **kw):
        calls.append(path)
        return routes.get(path, (404, {}, "HTTP 404: Not Found"))
    return fake


def test_disabled_pending_without_version_is_dropped_with_notice(monkeypatch):
    coll = {"Members": [{"@odata.id": f"/redfish/v1/UpdateService/FirmwareInventory/{i}"} for i in ("UEFI", "UEFI-Pending", "BMC-Pending-Staged")]}
    routes = {
        "UpdateService/FirmwareInventory": (200, coll, None),
        "UpdateService/FirmwareInventory/UEFI": (200, {"Id": "UEFI", "Name": "Firmware:UEFI", "Version": "20L-1.50", "Status": {"State": "Enabled"}}, None),
        "UpdateService/FirmwareInventory/UEFI-Pending": (200, {"Id": "UEFI-Pending", "Name": "Firmware:UEFI", "Version": "", "Status": {"State": "Disabled"}}, None),
        "UpdateService/FirmwareInventory/BMC-Pending-Staged": (200, {"Id": "BMC-Pending-Staged", "Name": "Firmware:BMC", "Version": "38R-2.98", "Status": {"State": "Disabled"}}, None),
    }
    calls = []
    rg._reset_notices()
    monkeypatch.setattr(rg, "_get", _routed(routes, calls))
    fw, errs = rg.gather_firmware("10.0.0.1", "u", "p", 30, False)
    ids = {f["id"]: f for f in fw}
    assert sorted(ids) == ["BMC-Pending-Staged", "UEFI"] and errs == []
    assert ids["BMC-Pending-Staged"]["pending"] is True and ids["BMC-Pending-Staged"]["version"] == "38R-2.98"
    assert [n["message"] for n in rg.notices() if "UEFI-Pending" in n["message"]] == ["UEFI-Pending: Disabled · Version 없음(예정된 업데이트 없음) — 목록에서 제외"]


def test_xcc3_recording_drops_the_four_empty_pending_slots():
    res, notices = _replay("real_lenovo_sr650_v4_01")
    fw = res["data"]["firmware"]
    assert len(fw) == 24 and not [f for f in fw if f["id"].endswith("-Pending")]
    assert all(f["version"] for f in fw)
    assert sum(1 for m in notices if "Disabled · Version 없음" in m) == 4


# ── (c) PSU strip · locator 순서 · Lenovo oem ─────────────────────────────────────────────────────────────────────────────

def test_psu_strings_are_stripped_in_both_power_paths():
    res, _ = _replay("real_lenovo_sr650_v4_01")
    assert [p["model"] for p in res["data"]["power"]["power_supplies"]] == ["CRPS1300D5", "CRPS1300D5"]
    res2, _ = _replay("real_hpe_csus3200_01")                                        # PowerSubsystem 경로 — 값 불변(공백 없음)
    assert all(p["model"] == p["model"].strip() for p in res2["data"]["power"]["power_supplies"] if p["model"])


@pytest.mark.parametrize("body,expected", [
    ({"DeviceLocator": "DIMM_A1", "MemoryLocation": {"Slot": 0}, "Location": {"PartLocation": {"ServiceLabel": "ignored"}}}, "DIMM_A1"),
    ({"MemoryLocation": {"Slot": 23}, "Location": {"PartLocation": {"ServiceLabel": "DIMM 23"}}}, "DIMM 23"),      # Lenovo XCC3 실측
    ({"MemoryLocation": {"Slot": 0}, "Location": {"PartLocation": {"ServiceLabel": "rack1/chassis_u1/cpu0/dimmA0"}}}, "rack1/chassis_u1/cpu0/dimmA0"),  # CSUS
    ({"MemoryLocation": {"Slot": 32}}, "32"),                                                                            # ServiceLabel 없음 → str(Slot)
    ({}, None),
])
def test_memory_locator_prefers_device_locator_then_service_label_then_slot(monkeypatch, body, expected):
    member = dict({"Id": "M", "Name": "DIMM", "CapacityMiB": 16384, "Status": {"State": "Enabled"}}, **body)
    routes = {"Systems/1/Memory": (200, {"Members": [{"@odata.id": "/redfish/v1/Systems/1/Memory/M"}]}, None),
              "Systems/1/Memory/M": (200, member, None)}
    monkeypatch.setattr(rg, "_get", _routed(routes, []))
    out, _ = rg.gather_memory("10.0.0.1", "/redfish/v1/Systems/1", "u", "p", 30, False)
    assert out["slots"][0]["locator"] == expected


def test_lenovo_oem_fills_machine_type_and_led_from_system_when_chassis_lacks_them():
    sys_body = {"Model": "ThinkSystem SR650 V4", "SubModel": "7DGD", "IndicatorLED": "Off", "Oem": {"Lenovo": {"SystemStatus": "OSBooted"}}}
    oem = rg._extract_oem_lenovo(sys_body, chassis_data={"Oem": {"Lenovo": {"ProductName": "ThinkSystem SR650 V4"}}})
    assert oem["machine_type"] == "7DGD" and oem["led_indicator"] == "Off" and oem["product_name"] == "ThinkSystem SR650 V4"
    # chassis OEM 이 주면(XCC1/2) 그 값이 먼저다
    oem2 = rg._extract_oem_lenovo(sys_body, chassis_data={"Oem": {"Lenovo": {"MachineType": "7X06", "LEDIndicators": ["X"]}}})
    assert oem2["machine_type"] == "7X06" and oem2["led_indicator"] == ["X"]
    assert rg._extract_oem_lenovo({"Model": "M"})["machine_type"] is None


def test_xcc3_recording_oem_has_machine_type_and_led():
    res, _ = _replay("real_lenovo_sr650_v4_01")
    oem = res["data"]["system"]["oem"]
    assert oem["machine_type"] == "7DGD" and oem["led_indicator"] == "Off" and oem["system_status"] == "OSBooted"
