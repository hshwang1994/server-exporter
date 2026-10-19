"""CSUS 3200 단일 서버 정합 · 수집 범위 보완 (2026-10-19) — 모듈 헬퍼와 normalize_standard 템플릿 단위 시험.

실 4노드 전수 미러(RMC 1.75.108) 재검수에서 확인한 것을 고정한다 — 전부 "정보가 없을 때만" 발동하고, 정보를 주는 벤더(Dell/HPE/Lenovo 실 녹화본)는
요청·값이 바뀌지 않는다(그쪽은 test_real_capture_replay / test_request_budget 골든이 지킨다).

  A-5  섀시 NetworkAdapters 가 비면 Systems/{id}/NetworkInterfaces 의 Links.NetworkAdapter 로 카드를 찾는다
  A-7  System 에 PartNumber/SKU 가 없으면 섀시 값으로 보충
  A-8  StorageControllers 없는 Storage 멤버 — 드라이브 위치 ⊂ PCIe 슬롯 위치인 PCIeDevice 를 컨트롤러로 식별 (1개일 때만)
  A-9  adapter firmware_inventory_scope=complex_only — PCIe 장치 · PSU 펌웨어를 firmware[] 에 보충
  A-10 Storage 에 드라이브가 0건이면 섀시 Drives 컬렉션 폴백
  A-11 System 이 연결한 섀시가 2개 이상이면 Power/Thermal 합산 (1개면 종전과 같은 호출)
  A-3/A-4/A-6/B-1/B-10/B-11 normalize_standard.yml 템플릿 — power null · adapter_count · 빈 컨트롤러 제거 · 메모리 총량 null/폴백 · cores_per_socket
"""
from __future__ import annotations

import ast
import re
import sys
import types
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
for _n in ("ansible", "ansible.module_utils", "ansible.module_utils.basic"):
    sys.modules.setdefault(_n, types.ModuleType(_n))
if not hasattr(sys.modules["ansible.module_utils.basic"], "AnsibleModule"):
    sys.modules["ansible.module_utils.basic"].AnsibleModule = object

import redfish_gather as rg  # noqa: E402

NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
CREDS = ("u", "p", 10, False)
IP = "10.0.0.1"


@pytest.fixture(autouse=True)
def _reset():
    rg._reset_response_cache(enabled=False)
    rg._reset_notices()
    yield
    rg._reset_notices()


def _routes(monkeypatch, table, calls=None):
    """path → (status, body, err). 없는 경로는 404. calls 에 요청 경로를 순서대로 쌓는다."""
    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        if calls is not None:
            calls.append(path)
        return table.get(path, (404, {}, "HTTP 404: Not Found"))
    monkeypatch.setattr(rg, "_get", fake_get)


def _notices(section):
    return [n["message"] for n in rg.notices() if n.get("section") == section]


# ── 공통 fixture 조각 (실측 CSUS node03 모양을 축약) ────────────────────────────────────────
SYS = "/redfish/v1/Systems/Partition0"
CH = "/redfish/v1/Chassis/r001u01"
CHASSIS_BODY = {"@odata.id": CH, "Id": "r001u01", "Name": "rack1/chassis_u1", "Manufacturer": "HPE",
                "Model": "Compute Scale-up Server 3200, 4S XNC Base Chassis", "PartNumber": "R9N70A", "SerialNumber": "SGHD3QHLDT",
                "PCIeDevices": {"@odata.id": CH + "/PCIeDevices"}, "Drives": {"@odata.id": CH + "/Drives"},
                "NetworkAdapters": {"@odata.id": CH + "/NetworkAdapters"}, "Status": {"Health": "OK"}}
PCIE_COLL = {"Members": [{"@odata.id": CH + "/PCIeDevices/2"}, {"@odata.id": CH + "/PCIeDevices/3"}]}
PCIE_2 = {"Id": "2", "Model": "HPE SN1100Q 16Gb 2p FC HBA", "Manufacturer": "Hewlett Packard Enterprise", "FirmwareVersion": "9.15.05 (d0d5)",
          "Slot": {"Location": {"PartLocation": {"ServiceLabel": "rack1/chassis_u1/cpu1/io_slot2"}}}}
PCIE_3 = {"Id": "3", "Model": "HPE SR3258p-16i/e PCIe4 Controller", "Manufacturer": "Adaptec", "FirmwareVersion": "03.01.44.040-0",
          "SerialNumber": "5D12F3000B4", "Status": {"Health": "OK"},
          "Slot": {"Location": {"PartLocation": {"ServiceLabel": "rack1/chassis_u1/cpu0/io_slot3"}}}}
DRIVE_1 = {"Id": "DriveSlot1InPCIeSlot3Box1", "Name": "Drive rack1/chassis_u1/cpu0/io_slot3/box1/drive_bay1", "Model": "MO001600PXMTN",
           "CapacityBytes": 1600321314816, "MediaType": "SSD", "Protocol": "SAS", "SerialNumber": "YFN0A0SP0T83", "Status": {"Health": "OK"},
           "PhysicalLocation": {"PartLocation": {"ServiceLabel": "rack1/chassis_u1/cpu0/io_slot3/box1/drive_bay1"}}}
DRIVE_2 = dict(DRIVE_1, Id="DriveSlot2InPCIeSlot3Box1", SerialNumber="YFN0A0SR0T83",
               PhysicalLocation={"PartLocation": {"ServiceLabel": "rack1/chassis_u1/cpu0/io_slot3/box1/drive_bay2"}})
STORAGE_1 = {"@odata.id": SYS + "/Storage/1", "Id": "1", "Name": "Npar 0 Storage",
             "Drives": [{"@odata.id": CH + "/Drives/DriveSlot1InPCIeSlot3Box1"}, {"@odata.id": CH + "/Drives/DriveSlot2InPCIeSlot3Box1"}]}


def _csus_storage_routes(drives=True):
    t = {
        rg._p(CH): (200, CHASSIS_BODY, None),
        rg._p(CH + "/PCIeDevices"): (200, PCIE_COLL, None),
        rg._p(CH + "/PCIeDevices/2"): (200, PCIE_2, None),
        rg._p(CH + "/PCIeDevices/3"): (200, PCIE_3, None),
        rg._p(CH + "/Drives/DriveSlot1InPCIeSlot3Box1"): (200, DRIVE_1, None),
        rg._p(CH + "/Drives/DriveSlot2InPCIeSlot3Box1"): (200, DRIVE_2, None),
        rg._p(SYS + "/Storage"): (200, {"Members": [{"@odata.id": SYS + "/Storage/1"}]}, None),
        rg._p(SYS + "/Storage/1"): (200, STORAGE_1 if drives else dict(STORAGE_1, Drives=[]), None),
    }
    return t


# ── A-7 ──────────────────────────────────────────────────────────────────────────
def test_a7_system_part_number_and_sku_fall_back_to_chassis(monkeypatch):
    sys_body = {"Id": "Partition0", "SerialNumber": "SGHD3QHLDT-000", "UUID": "x"}
    _routes(monkeypatch, {rg._p(SYS): (200, sys_body, None), rg._p(CH): (200, dict(CHASSIS_BODY, SKU="SKU-1"), None)})
    data, errors = rg.gather_system(IP, SYS, "hpe", *CREDS, CH, "Compute Scale-up Server 3200")
    assert errors == []
    assert data["part_number"] == "R9N70A" and data["sku"] == "SKU-1"
    assert data["model"] == "Compute Scale-up Server 3200" and data["manufacturer"] == "HPE"


def test_a7_system_values_win_when_present(monkeypatch):
    sys_body = {"Id": "1", "PartNumber": "01YM03A03", "SKU": "J0KV603", "Manufacturer": "Dell Inc.", "Model": "PowerEdge R740"}
    _routes(monkeypatch, {rg._p(SYS): (200, sys_body, None), rg._p(CH): (200, dict(CHASSIS_BODY, SKU="OTHER"), None)})
    data, _ = rg.gather_system(IP, SYS, "dell", *CREDS, CH, None)
    assert data["part_number"] == "01YM03A03" and data["sku"] == "J0KV603"


# ── A-8 ──────────────────────────────────────────────────────────────────────────
def test_a8_controller_identity_from_pcie_slot_location(monkeypatch):
    calls = []
    _routes(monkeypatch, _csus_storage_routes(), calls)
    data, errors = rg.gather_storage(IP, SYS, *CREDS, [CH])
    assert errors == []
    (ctrl,) = data["controllers"]
    assert ctrl["name"] == "HPE SR3258p-16i/e PCIe4 Controller"
    assert ctrl["controller_model"] == "HPE SR3258p-16i/e PCIe4 Controller"
    assert ctrl["controller_manufacturer"] == "Adaptec" and ctrl["controller_firmware"] == "03.01.44.040-0"
    assert ctrl["controller_health"] == "OK" and len(ctrl["drives"]) == 2
    assert any("PCIe 장치 3" in m for m in _notices("storage"))
    assert rg._p(CH + "/PCIeDevices") in calls and rg._p(CH + "/Drives") not in calls, "드라이브가 있으면 섀시 Drives 폴백은 돌지 않는다"


def test_a8_ambiguous_or_no_match_leaves_controller_unidentified(monkeypatch):
    table = _csus_storage_routes()
    # PCIe 장치 2 의 슬롯을 드라이브 위치와 같은 io_slot3 으로 — 후보 2개
    table[rg._p(CH + "/PCIeDevices/2")] = (200, dict(PCIE_2, Slot=PCIE_3["Slot"]), None)
    _routes(monkeypatch, table)
    data, _ = rg.gather_storage(IP, SYS, *CREDS, [CH])
    (ctrl,) = data["controllers"]
    assert ctrl["name"] == "Npar 0 Storage" and "controller_model" not in ctrl
    assert any("2개" in m for m in _notices("storage"))


def test_a8_not_called_without_chassis_or_when_controller_info_exists(monkeypatch):
    calls = []
    table = _csus_storage_routes()
    table[rg._p(SYS + "/Storage/1")] = (200, dict(STORAGE_1, StorageControllers=[{"Name": "PERC H740P Adapter", "Model": "PERC H740P Adapter"}]), None)
    _routes(monkeypatch, table, calls)
    data, _ = rg.gather_storage(IP, SYS, *CREDS, [CH])
    assert data["controllers"][0]["controller_model"] == "PERC H740P Adapter"
    assert rg._p(CH + "/PCIeDevices") not in calls
    calls.clear()
    _routes(monkeypatch, _csus_storage_routes(), calls)
    data, _ = rg.gather_storage(IP, SYS, *CREDS)      # chassis_uris 없음 — 종전과 같다
    assert "controller_model" not in data["controllers"][0] and rg._p(CH + "/PCIeDevices") not in calls


# ── A-10 ─────────────────────────────────────────────────────────────────────────
def test_a10_chassis_drives_fallback_when_storage_has_no_drives(monkeypatch):
    table = _csus_storage_routes(drives=False)
    table[rg._p(CH + "/Drives")] = (200, {"Members": [{"@odata.id": CH + "/Drives/DriveSlot1InPCIeSlot3Box1"},
                                                     {"@odata.id": CH + "/Drives/DriveSlot2InPCIeSlot3Box1"}]}, None)
    calls = []
    _routes(monkeypatch, table, calls)
    data, errors = rg.gather_storage(IP, SYS, *CREDS, [CH])
    assert errors == []
    ids = [c["id"] for c in data["controllers"]]
    assert ids == ["1", "Chassis.r001u01"]
    extra = data["controllers"][1]
    assert extra["name"] == "rack1/chassis_u1 Drives" and len(extra["drives"]) == 2
    assert extra["drives"][0]["serial"] == "YFN0A0SP0T83"
    assert any("섀시 r001u01 의 Drives 2건" in m for m in _notices("storage"))


def test_a10_empty_chassis_drives_adds_nothing(monkeypatch):
    table = _csus_storage_routes(drives=False)
    table[rg._p(CH + "/Drives")] = (200, {"Members": []}, None)
    calls = []
    _routes(monkeypatch, table, calls)
    data, errors = rg.gather_storage(IP, SYS, *CREDS, [CH])
    assert errors == [] and [c["id"] for c in data["controllers"]] == ["1"]
    assert rg._p(CH + "/Drives") in calls and _notices("storage") == []


# ── A-9 ──────────────────────────────────────────────────────────────────────────
def test_a9_firmware_supplement_from_pcie_and_psu(monkeypatch):
    _routes(monkeypatch, _csus_storage_routes())
    fw = [{"id": "ComplexFW", "name": "Complex Firmware", "version": "1.75.108", "updateable": True, "component": "x", "pending": False}]
    power = {"power_supplies": [{"name": "rack1/chassis_u1/psu0", "model": "CRPS", "firmware_version": "Release -0005"},
                                {"name": "rack1/chassis_u1/psu1", "model": "CRPS", "firmware_version": None}]}
    errors = []
    out = rg._supplement_firmware_from_pcie_psu(IP, fw, [CH], power, *CREDS, errors)
    assert errors == []
    assert [f["id"] for f in out] == ["ComplexFW", "PCIeDevice.2", "PCIeDevice.3", "PowerSupply.0"]
    assert out[2] == {"id": "PCIeDevice.3", "name": "HPE SR3258p-16i/e PCIe4 Controller", "version": "03.01.44.040-0",
                      "updateable": None, "component": "rack1/chassis_u1/cpu0/io_slot3", "pending": False}
    assert out[3]["version"] == "Release -0005" and out[3]["component"] == "rack1/chassis_u1/psu0"
    assert any("PCIe 장치 2건 · PSU 1건" in m for m in _notices("firmware"))
    # 멱등 — 이미 있는 id 는 다시 넣지 않는다
    again = rg._supplement_firmware_from_pcie_psu(IP, out, [CH], power, *CREDS, errors)
    assert [f["id"] for f in again] == [f["id"] for f in out]


def test_a9_collect_all_sections_only_supplements_when_scope_is_complex_only(monkeypatch):
    table = _csus_storage_routes()
    table.update({
        rg._p(SYS): (200, {"Id": "Partition0", "Links": {"Chassis": [{"@odata.id": CH}]}}, None),
        rg._p("UpdateService/FirmwareInventory"): (200, {"Members": [{"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/ComplexFW"}]}, None),
        rg._p("/redfish/v1/UpdateService/FirmwareInventory/ComplexFW"): (200, {"Id": "ComplexFW", "Name": "Complex Firmware", "Version": "1.75.108"}, None),
    })
    _routes(monkeypatch, table)
    for scope, expected in ((None, ["ComplexFW"]), ("complex_only", ["ComplexFW", "PCIeDevice.2", "PCIeDevice.3"])):
        rg._reset_notices()
        errs, collected, failed, unsupported = [], [], [], []
        data = rg._collect_all_sections(IP, "hpe", SYS, None, CH, *CREDS, errs, collected, failed, unsupported,
                                        manager_layout="rmc_primary", firmware_scope=scope)
        assert [f["id"] for f in data["firmware"]] == expected, scope
        assert "firmware" in collected and "firmware" not in failed


# ── A-11 ─────────────────────────────────────────────────────────────────────────
def _power_body(psu_name, cap, consumed):
    return {"PowerSupplies": [{"Name": psu_name, "PowerCapacityWatts": cap, "Status": {"Health": "OK", "State": "Enabled"}}],
            "PowerControl": [{"PowerConsumedWatts": consumed, "PowerCapacityWatts": cap,
                              "PowerMetrics": {"IntervalInMin": 1, "MinConsumedWatts": 1, "AverageConsumedWatts": 2, "MaxConsumedWatts": 3}}]}


def test_a11_two_chassis_power_is_merged(monkeypatch):
    c1, c2 = "/redfish/v1/Chassis/r001u01", "/redfish/v1/Chassis/r001u02"
    _routes(monkeypatch, {rg._p(c1) + "/Power": (200, _power_body("PSU0", 2400, 591), None),
                          rg._p(c2) + "/Power": (200, _power_body("PSU0", 2400, 600), None)})
    data, errors = rg._gather_power_for_system(IP, [c1, c2], c1, *CREDS)
    assert errors == []
    assert [p["name"] for p in data["power_supplies"]] == ["PSU0", "PSU0"]
    pc = data["power_control"]
    assert pc["power_consumed_watts"] == 1191 and pc["power_capacity_watts"] == 4800
    assert pc["min_consumed_watts"] is None and pc["avg_consumed_watts"] is None and pc["max_consumed_watts"] is None
    assert any("섀시 2개" in m for m in _notices("power"))


def test_a11_chassis_without_power_resource_is_skipped_and_single_chassis_unchanged(monkeypatch):
    c1, c2 = "/redfish/v1/Chassis/r001u01", "/redfish/v1/Chassis/RackGroup"
    _routes(monkeypatch, {rg._p(c1) + "/Power": (200, _power_body("PSU0", None, 591), None)})
    data, errors = rg._gather_power_for_system(IP, [c1, c2], c1, *CREDS)
    assert errors == [] and len(data["power_supplies"]) == 1
    assert data["power_control"]["power_consumed_watts"] == 591 and data["power_control"]["power_capacity_watts"] is None
    assert any("RackGroup" in m and "Power 리소스 없음" in m for m in _notices("power"))
    # 1개면 종전 gather_power 와 같은 결과
    rg._reset_notices()
    single, e1 = rg._gather_power_for_system(IP, [c1], c1, *CREDS)
    direct, e2 = rg.gather_power(IP, c1, *CREDS)
    assert single == direct and e1 == e2 and _notices("power") == []


def test_a11_two_chassis_thermal_is_concatenated(monkeypatch):
    c1, c2 = "/redfish/v1/Chassis/r001u01", "/redfish/v1/Chassis/r001u02"
    body = {"Temperatures": [{"Name": "Inlet", "ReadingCelsius": 22, "Status": {"Health": "OK", "State": "Enabled"}}],
            "Fans": [{"Name": "Fan0", "Reading": 4000, "ReadingUnits": "RPM", "Status": {"Health": "OK", "State": "Enabled"}}]}
    _routes(monkeypatch, {rg._p(c1) + "/Thermal": (200, body, None), rg._p(c2) + "/Thermal": (200, body, None)})
    data, errors = rg._gather_thermal_for_system(IP, [c1, c2], c1, *CREDS)
    assert errors == [] and len(data["temperatures"]) == 2 and len(data["fans"]) == 2


# ── A-5 ──────────────────────────────────────────────────────────────────────────
def test_a5_network_interfaces_link_used_only_when_chassis_path_has_no_cards(monkeypatch):
    ni = SYS + "/NetworkInterfaces"
    table = {
        rg._p(ni): (200, {"Members": [{"@odata.id": ni + "/NetworkIfPCIeCard10"}]}, None),
        rg._p(ni + "/NetworkIfPCIeCard10"): (200, {"Id": "NetworkIfPCIeCard10", "Links": {"NetworkAdapter": {"@odata.id": CH + "/NetworkAdapters/PCIeCard10"}}}, None),
    }
    calls, errors = [], []
    _routes(monkeypatch, table, calls)          # 섀시 NetworkAdapters 는 404
    sources, tried, fails, saw_empty = rg._network_adapter_sources(IP, CH, SYS, [], *CREDS, errors)
    assert [o for o, _ in sources] == ["system_interfaces"]
    assert sources[0][1] == [{"@odata.id": CH + "/NetworkAdapters/PCIeCard10"}]
    assert tried == [rg._p(CH) + "/NetworkAdapters", rg._p(ni)] and fails[0][0] == 404
    assert rg._p(SYS) + "/NetworkAdapters" not in calls, "NetworkInterfaces 로 찾았으면 Systems/{id}/NetworkAdapters 는 묻지 않는다"
    # 섀시 경로가 카드를 주면 NetworkInterfaces 는 요청하지 않는다
    calls.clear()
    table[rg._p(CH) + "/NetworkAdapters"] = (200, {"Members": [{"@odata.id": CH + "/NetworkAdapters/PCIeCard10"}]}, None)
    _routes(monkeypatch, table, calls)
    sources, tried, fails, _ = rg._network_adapter_sources(IP, CH, SYS, [], *CREDS, [])
    assert [o for o, _ in sources] == ["primary"] and rg._p(ni) not in calls


# ── normalize_standard.yml 템플릿 (A-3 · A-4 · A-6 · B-1 · B-10 · B-11 · firmware 'controller') ──
def _tpl(var_name):
    for t in yaml.safe_load(NORM.read_text(encoding="utf-8")):
        sf = t.get("ansible.builtin.set_fact") or {}
        if var_name in sf:
            return sf[var_name]
    raise AssertionError(var_name)


def _render(var_name, **ctx):
    env = jinja2.Environment()
    env.filters["regex_replace"] = lambda v, pat, rep="", *a, **k: re.sub(pat, rep, str(v))
    env.filters["combine"] = lambda a, b: {**a, **b}
    return ast.literal_eval(env.from_string(_tpl(var_name)).render(**ctx).strip())


def test_a3_power_summary_unknown_capacity_is_null_not_zero():
    psus = [{"state": "Enabled", "health": "OK", "power_capacity_w": None} for _ in range(4)]
    s = _render("_rf_power_summary", _rf_d_power={"power_supplies": psus, "power_control": {"power_consumed_watts": 591}})
    assert s["psu_count"] == 4 and s["capacity_unknown_count"] == 4
    assert s["total_capacity_w"] is None and s["consumed_capacity_pct"] is None and s["consumed_watts"] == 591
    # 일부만 알면 부분 합 + pct (종전과 같다)
    psus[0]["power_capacity_w"] = 800
    s = _render("_rf_power_summary", _rf_d_power={"power_supplies": psus, "power_control": {"power_consumed_watts": 400}})
    assert s["total_capacity_w"] == 800 and s["capacity_unknown_count"] == 3 and s["consumed_capacity_pct"] == 50.0
    # 소비전력을 모르면 pct 는 null
    s = _render("_rf_power_summary", _rf_d_power={"power_supplies": psus, "power_control": {}})
    assert s["consumed_watts"] is None and s["consumed_capacity_pct"] is None


def test_a4_adapter_count_excludes_fc_only_cards():
    netad = {"adapters": [{"id": "PCIeCard10"}, {"id": "PCIeCard15"}],
             "ports": [{"adapter_id": "PCIeCard10", "port_type": "FibreChannel", "associated_address": "51:40:2e:c0:20:82:c2:2c"},
                       {"adapter_id": "PCIeCard10", "port_type": "FibreChannel", "associated_address": "51:40:2e:c0:20:82:c2:2e"},
                       {"adapter_id": "PCIeCard15", "port_type": "FibreChannel", "associated_address": "51:40:2e:c0:20:82:c2:94"},
                       {"adapter_id": "PCIeCard15", "port_type": "FibreChannel", "associated_address": "51:40:2e:c0:20:82:c2:96"}]}
    s = _render("_rf_summary_network", _rf_d_netad=netad, _rf_norm_interfaces=[])
    assert s["adapter_count"] == 0 and s["port_count"] == 0 and s["groups"] == []
    # Dell R740 모양: NIC 2 + FC 1 + 포트 정보 없는 카드 1 → 3
    netad = {"adapters": [{"id": "NIC.Integrated.1"}, {"id": "NIC.Slot.2"}, {"id": "FC.Slot.1"}, {"id": "NIC.Mezzanine.3"}],
             "ports": [{"adapter_id": "NIC.Integrated.1", "port_type": "Ethernet", "associated_address": "aa:bb:cc:dd:ee:01"},
                       {"adapter_id": "NIC.Slot.2", "port_type": "Ethernet", "associated_address": "aa:bb:cc:dd:ee:02"},
                       {"adapter_id": "FC.Slot.1", "port_type": "FibreChannel", "associated_address": "21:00:00:24:ff:8b:1a:01"},
                       {"adapter_id": "NIC.Slot.2", "port_type": "InfiniBand", "associated_address": None}]}
    s = _render("_rf_summary_network", _rf_d_netad=netad, _rf_norm_interfaces=[])
    assert s["adapter_count"] == 3


def test_a6_identity_less_empty_storage_container_is_dropped():
    storage = {"controllers": [{"id": "1", "name": "Npar 0 Storage", "health": None, "drives": []},
                               {"id": "AHCI.Embedded.1-1", "name": "AHCI", "controller_model": "C620 SSATA", "drives": []},
                               {"id": "RAID.Slot.6-1", "name": "PERC", "controller_model": "PERC H740P", "drives": [{"name": "d1", "capacity_bytes": 1048576}]}],
               "volumes": []}
    out = _render("_rf_norm_controllers", _rf_d_storage=storage)
    assert [c["id"] for c in out] == ["AHCI.Embedded.1-1", "RAID.Slot.6-1"]
    # 볼륨이 참조하는 컨테이너는 정체가 없어도 남긴다
    storage["volumes"] = [{"id": "v", "controller_id": "1"}]
    assert [c["id"] for c in _render("_rf_norm_controllers", _rf_d_storage=storage)][0] == "1"


def test_b1_b10_memory_summary_total_null_or_fallback_and_small_dimm_guard():
    # DIMM 정보 없음 + total_mib 없음 + MemorySummary 없음 → null (종전 0)
    s = _render("_rf_summary_memory", _rf_d_memory={"slots": [], "total_mib": None}, _rf_d_system={})
    assert s == {"groups": [], "grand_total_gb": None}
    # DIMM 없음 · total_mib 524288 → 512
    s = _render("_rf_summary_memory", _rf_d_memory={"slots": [], "total_mib": 524288}, _rf_d_system={})
    assert s["grand_total_gb"] == 512
    # DIMM 없음 · MemorySummary 512 GiB → 512
    s = _render("_rf_summary_memory", _rf_d_memory={"slots": [], "total_mib": None}, _rf_d_system={"memory_summary": {"total_gib": 512}})
    assert s["grand_total_gb"] == 512
    # 256 MiB DIMM 은 그룹을 만들지 않는다 (unit_capacity_gb 0 금지)
    s = _render("_rf_summary_memory", _rf_d_memory={"slots": [{"capacity_mb": 256}, {"capacity_mb": 32768}], "total_mib": 33024}, _rf_d_system={})
    assert [g["unit_capacity_gb"] for g in s["groups"]] == [32] and s["grand_total_gb"] == 32


def test_b11_cores_per_socket_is_group_average():
    cpus = [{"model": "X", "total_cores": 8}, {"model": "X", "total_cores": 8}, {"model": "X", "total_cores": 16}]
    s = _render("_rf_summary_cpu", _rf_d_cpus=cpus)
    (g,) = s["groups"]
    assert g["sockets"] == 3 and g["total_cores"] == 32 and g["cores_per_socket"] == 10


def test_firmware_category_controller_token():
    fw = [{"id": "PCIeDevice.3", "name": "HPE SR3258p-16i/e PCIe4 Controller"}, {"id": "PCIeDevice.2", "name": "HPE SN1100Q 16Gb 2p FC HBA"},
          {"id": "PowerSupply.0", "name": "CRPS: Common Redundant Power Supply"}, {"id": "iDRAC", "name": "Integrated Dell Remote Access Controller"},
          {"id": "NIC.1", "name": "Broadcom Ethernet Controller"}]
    out = _render("_rf_firmware_categorized", _rf_d_firmware=fw)
    assert [f["category"] for f in out] == ["storage_controller", "other", "psu", "bmc", "nic"]


def test_firmware_category_gbe_token_is_nic():
    """2026-10-19 (A-9): CSUS PCIe 장치 이름('MLX MCX631102 10/25GbE 2p SFP28 Adptr')에는 nic/ethernet/제조사 토큰이 없다 — 'gbe' 로 nic.
    FC HBA('16Gb') 는 걸리지 않고 other 로 남는다."""
    fw = [{"id": "PCIeDevice.9", "name": "MLX MCX631102 10/25GbE 2p SFP28 Adptr"}, {"id": "PCIeDevice.2", "name": "HPE SN1100Q 16Gb 2p FC HBA"},
          {"id": "NIC.Slot.2", "name": "BRCM 10GbE 2P 57412S Adptr"}]
    out = _render("_rf_firmware_categorized", _rf_d_firmware=fw)
    assert [f["category"] for f in out] == ["nic", "other", "nic"]
