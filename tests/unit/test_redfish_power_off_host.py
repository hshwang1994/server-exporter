"""전원 Off 호스트 · 빈 DIMM 슬롯 · Absent PSU placeholder · 비-Enabled 센서 reading (2026-10-27, C2 — 02-system/02-memory/05-power/05-thermal).

실측(용인 2차 Mock DL380 Gen12 #03 — 호스트 PowerState Off 스냅샷, #01 — 전원 On · Absent 센서 7)과 합성 응답으로 다음 규칙을 고정한다.
  - 호스트 PowerState Off 는 notice 1건으로만 남긴다(섹션 status 불변, 인과 해석 없음).
  - Status 가 없고 CapacityMiB 0/None 이며 제조사·부품·시리얼이 전부 빈 Memory 멤버는 빈 슬롯 → 제외 + 건수 notice. 값이 하나라도 있으면 보존.
  - State=Absent PSU 의 PowerCapacityWatts 0 · FirmwareVersion "0.00" 은 placeholder → null (state 유지). Absent 가 아니면 불변.
  - Status.State 가 있고 Enabled 가 아닌 온도/팬의 reading 은 null (state · upper_critical 유지). Status 가 없는 센서(CSUS ThermalMetrics)는 불변.
전부 녹화 재생·합성이다. 기대값은 손으로 적었다(골든 스냅샷 아님). 실장비 지원 증거가 아니다.
"""
from __future__ import annotations

import copy
import json
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
OFF_NOTICE = "호스트 전원 Off 관측"
EMPTY_SLOT_NOTICE = "빈 DIMM 슬롯"


def _replay(name):
    case = FIX / name
    rec = json.loads((case / "recording.json").read_text(encoding="utf-8"))
    meta = json.loads((case / "meta.json").read_text(encoding="utf-8")) if (case / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    res = H.run_gather(g, n, realm_impl=r, manager_layout=meta.get("manager_layout"), firmware_scope=meta.get("firmware_inventory_scope"))
    return res, [x["message"] for x in rg.notices()]


def _golden(name):
    return json.loads((FIX / name / "expected_output.json").read_text(encoding="utf-8"))


# ── 1. 실측 재생: DL380 Gen12 #03 (호스트 Off) ───────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def off_host():
    return _replay("real_hpe_dl380_gen12_03")


def test_power_off_host_stays_success_and_is_noticed_once(off_host):
    res, notices = off_host
    assert res["status"] == "success" and res["failed_sections"] == [] and res["error_count"] == 0
    assert sum(1 for m in notices if OFF_NOTICE in m) == 1
    assert res["data"]["system"]["power_state"] == "Off"


def test_power_off_host_empty_dimm_slots_are_excluded_with_count(off_host):
    res, notices = off_host
    slots = res["data"]["memory"]["slots"]
    assert len(slots) == 16 and all(s["capacity_mb"] == 32768 for s in slots)
    assert res["data"]["memory"]["total_mib"] == 524288                      # 빈 슬롯은 합계에 0 이었다 — 합계 불변
    assert [m for m in notices if EMPTY_SLOT_NOTICE in m] == ["빈 DIMM 슬롯 16개 제외 (Status 없음 · CapacityMiB 0 · 제조사/부품/시리얼 없음)"]


def test_power_off_host_absent_psu_placeholders_become_null(off_host):
    res, _ = off_host
    psus = res["data"]["power"]["power_supplies"]
    assert len(psus) == 2
    for p in psus:
        assert p["state"] == "Absent" and p["health"] == "Warning"
        assert p["power_capacity_w"] is None and p["firmware_version"] is None
    # PowerControl[0].PowerCapacityWatts=1600 은 BMC 가 준 값이다 — PSU 합 폴백이 아니라 그대로 둔다
    assert res["data"]["power"]["power_control"]["power_capacity_watts"] == 1600


def test_power_off_host_unavailable_sensors_have_null_readings_but_keep_state(off_host):
    res, _ = off_host
    temps, fans = res["data"]["thermal"]["temperatures"], res["data"]["thermal"]["fans"]
    assert len(temps) == 42 and len(fans) == 6
    assert all(t["reading_celsius"] is None and t["state"] == "UnavailableOffline" for t in temps)
    assert temps[0]["name"] == "01-Inlet Ambient" and temps[0]["upper_critical"] == 42
    assert all(f["reading"] is None and f["state"] == "UnavailableOffline" and f["reading_units"] == "Percent" for f in fans)


def test_power_off_host_storage_is_empty_not_fabricated(off_host):
    res, _ = off_host
    assert res["data"]["storage"]["controllers"] == [] and res["data"]["network_adapters"]["fc_hbas"] == []


# ── 2. 실측 재생: DL380 Gen12 #01 (전원 On) · CSUS · SR650 V4 — 영향 범위가 Absent/비-Enabled 에 한정된다 ─────────────────────

def test_powered_on_host_only_absent_sensor_readings_change():
    res, notices = _replay("real_hpe_dl380_gen12_01")
    gold = _golden("real_hpe_dl380_gen12_01")
    assert not any(OFF_NOTICE in m or EMPTY_SLOT_NOTICE in m for m in notices)
    assert len(res["data"]["memory"]["slots"]) == 16 == len(gold["data"]["memory"]["slots"])
    psus = res["data"]["power"]["power_supplies"]
    assert [p["state"] for p in psus] == ["Enabled", "UnavailableOffline"]
    assert all(p["power_capacity_w"] == 1600 and p["firmware_version"] == "2.00" for p in psus)   # Absent 가 아니면 불변
    temps = res["data"]["thermal"]["temperatures"]
    # WP3 는 Absent 센서의 0 을 null 로 두었고, WP6(C10 05-thermal-001)이 그 항목 자체를 제외한다 — 7건은 건수 notice 로만 남는다
    assert not [t for t in temps if t["state"] == "Absent"] and len(temps) == 49
    assert any(m.startswith("Absent 센서 7건 제외") for m in notices)
    enabled_now = [(t["name"], t["reading_celsius"]) for t in temps if t["state"] == "Enabled"]
    enabled_gold = [(t["name"], t["reading_celsius"]) for t in gold["data"]["thermal"]["temperatures"] if t["state"] == "Enabled"]
    assert enabled_now == enabled_gold and len(enabled_now) == 49


@pytest.mark.parametrize("name", ["real_hpe_csus3200_01", "real_lenovo_sr650_v4_01", "real_dell_r740"])
def test_hosts_without_absent_or_offline_parts_are_unchanged(name):
    res, notices = _replay(name)
    gold = _golden(name)
    for k in H.GOLDEN_KEYS:
        assert json.loads(json.dumps(res[k], sort_keys=True)) == gold[k], (name, k)
    assert not any(OFF_NOTICE in m or EMPTY_SLOT_NOTICE in m for m in notices)


# ── 3. 합성 응답 — 규칙의 경계 ─────────────────────────────────────────────────────────────────────────────────────────────

IP, CREDS = "10.0.0.1", ("u", "p", 30, False)
SYSTEM = "/redfish/v1/Systems/1"


def _routed_get(routes, calls):
    def fake_get(bmc_ip, path, *a, **kw):
        calls.append(path)
        return routes.get(path, (404, {}, "HTTP 404: Not Found"))
    return fake_get


def _system(power_state="On"):
    return {"@odata.id": SYSTEM, "Id": "1", "Manufacturer": "Synthetic", "Model": "M", "SerialNumber": "S1", "PowerState": power_state,
            "Links": {"Chassis": [{"@odata.id": "/redfish/v1/Chassis/1"}]}}


def _dimm(i, **kw):
    body = {"@odata.id": f"/redfish/v1/Systems/1/Memory/d{i}", "Id": f"d{i}", "Name": f"DIMM {i}", "DeviceLocator": f"PROC 1 DIMM {i}"}
    body.update(kw)
    return body


def _collect(monkeypatch, routes):
    calls, all_errors, collected, failed, unsupported = [], [], [], [], []
    rg._reset_notices()
    monkeypatch.setattr(rg, "_get", _routed_get(routes, calls))
    data = rg._collect_all_sections(IP, "generic", SYSTEM, None, None, *CREDS, all_errors, collected, failed, unsupported)
    return data, [n["message"] for n in rg.notices()], all_errors


def _routes(power_state="On", dimms=(), power=None, thermal=None):
    r = {"Systems/1": (200, _system(power_state), None)}
    if dimms:
        r["Systems/1/Memory"] = (200, {"Members": [{"@odata.id": d["@odata.id"]} for d in dimms]}, None)
        for d in dimms:
            r[rg._p(d["@odata.id"])] = (200, d, None)
    if power is not None:
        r["Chassis/1/Power"] = (200, power, None)
    if thermal is not None:
        r["Chassis/1/Thermal"] = (200, thermal, None)
    return r


@pytest.mark.parametrize("power_state,expected", [("Off", 1), ("off", 1), ("On", 0), ("PoweringOff", 0), (None, 0)])
def test_only_power_state_off_yields_one_notice(monkeypatch, power_state, expected):
    _, notices, _ = _collect(monkeypatch, _routes(power_state))
    assert sum(1 for m in notices if OFF_NOTICE in m) == expected


def test_empty_slot_rule_needs_all_three_signals(monkeypatch):
    dimms = [
        _dimm(1, Status={"State": "Enabled", "Health": "OK"}, CapacityMiB=32768, Manufacturer="Hynix", PartNumber="P", SerialNumber="S"),
        _dimm(2, CapacityMiB=0),                                                 # Status 없음 · 0 · 식별자 없음 → 빈 슬롯
        _dimm(3, CapacityMiB=0, Manufacturer="Micron"),                          # 제조사가 있으면 보존 (0 MiB DIMM 은 날조가 아니라 장비 값)
        _dimm(4, Status={"State": "Enabled"}, CapacityMiB=0),                    # Status 가 있으면 보존
        _dimm(5),                                                                # CapacityMiB 자체가 없음 + 식별자 없음 → 빈 슬롯
        _dimm(6, Status={"State": "Absent"}, CapacityMiB=0),                     # 종전 규칙(Absent) 그대로 제외 — 빈 슬롯 건수에는 안 센다
    ]
    data, notices, _ = _collect(monkeypatch, _routes(dimms=dimms))
    assert [s["id"] for s in data["memory"]["slots"]] == ["d1", "d3", "d4"]
    assert data["memory"]["total_mib"] == 32768
    assert [m for m in notices if EMPTY_SLOT_NOTICE in m] == ["빈 DIMM 슬롯 2개 제외 (Status 없음 · CapacityMiB 0 · 제조사/부품/시리얼 없음)"]


def test_absent_psu_zero_and_dummy_firmware_become_null_but_other_values_stay(monkeypatch):
    power = {"PowerSupplies": [
        {"Name": "PSU1", "Status": {"State": "Enabled", "Health": "OK"}, "PowerCapacityWatts": 800, "FirmwareVersion": "2.00"},
        {"Name": "PSU2", "Status": {"State": "Absent", "Health": "Warning"}, "PowerCapacityWatts": 0, "FirmwareVersion": "0.00"},
        {"Name": "PSU3", "Status": {"State": "Absent"}, "PowerCapacityWatts": 750, "FirmwareVersion": "1.10"},   # Absent 여도 0/"0.00" 이 아니면 그대로
        {"Name": "PSU4", "Status": {"State": "UnavailableOffline", "Health": "Critical"}, "PowerCapacityWatts": 0, "FirmwareVersion": "0.00"},  # Absent 아님 → 불변
    ], "PowerControl": [{"PowerConsumedWatts": 100}]}          # PowerCapacityWatts 없음 → PSU 합 폴백
    data, _, _ = _collect(monkeypatch, _routes(power=power))
    psus = {p["name"]: p for p in data["power"]["power_supplies"]}
    assert (psus["PSU1"]["power_capacity_w"], psus["PSU1"]["firmware_version"]) == (800, "2.00")
    assert (psus["PSU2"]["power_capacity_w"], psus["PSU2"]["firmware_version"], psus["PSU2"]["state"]) == (None, None, "Absent")
    assert (psus["PSU3"]["power_capacity_w"], psus["PSU3"]["firmware_version"]) == (750, "1.10")
    assert (psus["PSU4"]["power_capacity_w"], psus["PSU4"]["firmware_version"]) == (0, "0.00")
    assert data["power"]["power_control"]["power_capacity_watts"] == 800          # Absent(PSU3 750) 제외, UnavailableOffline(0) 포함


def test_sensor_reading_null_only_when_state_present_and_not_enabled(monkeypatch):
    thermal = {"Temperatures": [
        {"Name": "t-enabled", "ReadingCelsius": 31, "Status": {"State": "Enabled"}, "UpperThresholdCritical": 70},
        {"Name": "t-offline", "ReadingCelsius": 0, "Status": {"State": "UnavailableOffline"}, "UpperThresholdCritical": 70},
        {"Name": "t-absent", "ReadingCelsius": 0, "Status": {"State": "Absent"}},
        {"Name": "t-nostatus", "ReadingCelsius": 0},                                   # CSUS 처럼 Status 없음 → 그대로
        {"Name": "t-enabled-zero", "ReadingCelsius": 0, "Status": {"State": "Enabled"}},  # Enabled 의 0 은 측정값
    ], "Fans": [
        {"Name": "f-enabled", "Reading": 4200, "ReadingUnits": "RPM", "Status": {"State": "Enabled"}},
        {"Name": "f-offline", "Reading": 0, "ReadingUnits": "Percent", "Status": {"State": "UnavailableOffline"}},
    ]}
    data, _, _ = _collect(monkeypatch, _routes(thermal=thermal))
    t = {x["name"]: x for x in data["thermal"]["temperatures"]}
    assert t["t-enabled"]["reading_celsius"] == 31
    assert t["t-offline"]["reading_celsius"] is None and t["t-offline"]["state"] == "UnavailableOffline" and t["t-offline"]["upper_critical"] == 70
    assert "t-absent" not in t                                    # WP6: Absent 항목은 제외 (test_redfish_thermal_power_meaning.py)
    assert t["t-nostatus"]["reading_celsius"] == 0 and t["t-nostatus"]["state"] is None
    assert t["t-enabled-zero"]["reading_celsius"] == 0
    f = {x["name"]: x for x in data["thermal"]["fans"]}
    assert f["f-enabled"]["reading"] == 4200 and f["f-offline"]["reading"] is None and f["f-offline"]["state"] == "UnavailableOffline"


def test_helpers_are_pure():
    assert rg._psu_absent_placeholders_to_none("Absent", 0, "0.00") == (None, None)
    assert rg._psu_absent_placeholders_to_none("Absent", 0, "") == (None, None)
    assert rg._psu_absent_placeholders_to_none("absent", None, None) == (None, None)
    assert rg._psu_absent_placeholders_to_none("Enabled", 0, "0.00") == (0, "0.00")
    assert rg._psu_absent_placeholders_to_none(None, 0, "0.00") == (0, "0.00")
    assert rg._sensor_reading_if_enabled({"Status": {"State": "Enabled"}}, 5) == 5
    assert rg._sensor_reading_if_enabled({"Status": {"State": "Absent"}}, 0) is None
    assert rg._sensor_reading_if_enabled({"Status": {"State": ""}}, 0) == 0
    assert rg._sensor_reading_if_enabled({}, 0) == 0
    assert rg._sensor_reading_if_enabled({"Status": "weird"}, 7) == 7
