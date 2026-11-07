"""전원·온도 의미 (2026-10-27, C10 — 05-thermal-001 · 05-power-002 · 05-power-007 · 05-thermal-003).

  - Status.State=Absent 인 온도 센서/팬은 항목을 두지 않고 건수 notice 1건 (legacy /Thermal · ThermalSubsystem 양쪽). Status 가 없으면 Absent 아님.
  - PSU 입력 전력/전압 키가 있고 0 이면 관측 notice 1건(인과 해석 없음, psu_active·state 불변). 키 없음/null 은 무시, Absent 슬롯은 제외.
  - 소비전력 폴백: EnvironmentMetrics → TelemetryService → PSU Metrics.OutputPowerWatts 합 → PSU Metrics.InputPowerWatts 합.
  - ThermalSubsystem: 이름 폴백 DataSourceUri 마지막 세그먼트, SpeedPercent.SpeedRPM → reading(RPM) — 18 label 미발동, 합성으로만.
실측: DL380 Gen12 #01(Absent 7 · PSU#2 LineInputVoltage 0), SR650 V4 #01(PSU1 PowerInputWatts 0), #03(UnavailableOffline 은 Absent 아님). 기대값은 손으로 적었다.
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


def _replay(name):
    case = FIX / name
    rec = json.loads((case / "recording.json").read_text(encoding="utf-8"))
    meta = json.loads((case / "meta.json").read_text(encoding="utf-8")) if (case / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    res = H.run_gather(g, n, realm_impl=r, manager_layout=meta.get("manager_layout"), firmware_scope=meta.get("firmware_inventory_scope"))
    return res, [x["message"] for x in rg.notices()]


def _routed(routes, calls):
    def fake(bmc_ip, path, *a, **kw):
        calls.append(path)
        return routes.get(path, (404, {}, "HTTP 404: Not Found"))
    return fake


# ── 실측 재생 ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,temps_after,absent", [
    ("real_hpe_dl380_gen12_01", 49, 7), ("real_hpe_dl380_gen12_02", 36, 8), ("real_hpe_dl380_gen12_04", 46, 8), ("real_hpe_dl380", 43, 9),
])
def test_absent_temperature_sensors_are_dropped_with_one_count_notice(name, temps_after, absent):
    res, notices = _replay(name)
    temps = res["data"]["thermal"]["temperatures"]
    assert len(temps) == temps_after and not [t for t in temps if t["state"] == "Absent"]
    assert all(t["reading_celsius"] is not None for t in temps if t["state"] == "Enabled")
    assert [m for m in notices if m.startswith("Absent 센서")] == [f"Absent 센서 {absent}건 제외 (온도 {absent} · 팬 0) — 미장착 슬롯"]
    assert len(res["data"]["thermal"]["fans"]) == 6


def test_unavailable_offline_is_not_absent_and_csus_has_no_status():
    res, notices = _replay("real_hpe_dl380_gen12_03")
    assert len(res["data"]["thermal"]["temperatures"]) == 42 and not any(m.startswith("Absent 센서") for m in notices)
    res2, notices2 = _replay("real_hpe_csus3200_01")
    assert len(res2["data"]["thermal"]["temperatures"]) == 63 and not any(m.startswith("Absent 센서") for m in notices2)


def test_zero_input_is_noticed_as_observation_only():
    res, notices = _replay("real_hpe_dl380_gen12_01")                         # PSU#2: UnavailableOffline, LineInputVoltage 0
    assert [m for m in notices if m.startswith("전원 공급 장치")] == ["전원 공급 장치 HpeServerPowerSupply[1]: 입력 전압 0 V 관측"]
    psus = res["data"]["power"]["power_supplies"]
    assert [p["state"] for p in psus] == ["Enabled", "UnavailableOffline"]    # 상태 불변
    res2, notices2 = _replay("real_lenovo_sr650_v4_01")                       # PSU1: Enabled/Critical, PowerInputWatts 0
    assert [m for m in notices2 if m.startswith("전원 공급 장치")] == ["전원 공급 장치 PSU1[0]: 입력 전력 0 W 관측"]
    res3, notices3 = _replay("real_hpe_dl380_gen12_03")                       # Absent PSU 2: 관측 notice 없음
    assert not [m for m in notices3 if m.startswith("전원 공급 장치")]
    res4, notices4 = _replay("real_dell_r740")                                # 입력 220 V / 151 W: 없음
    assert not [m for m in notices4 if m.startswith("전원 공급 장치")]


# ── 합성 — 규칙의 경계 ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_zero_input_notice_only_when_key_present(monkeypatch):
    rg._reset_notices()
    power = {"PowerSupplies": [
        {"Name": "A", "MemberId": "0", "Status": {"State": "Enabled"}, "LineInputVoltage": 0, "PowerInputWatts": 0},
        {"Name": "B", "MemberId": "1", "Status": {"State": "Enabled"}},                                  # 키 없음 → 없음
        {"Name": "C", "MemberId": "2", "Status": {"State": "Enabled"}, "LineInputVoltage": None},        # null → 없음
        {"Name": "D", "MemberId": "3", "Status": {"State": "Absent"}, "LineInputVoltage": 0},            # Absent → 없음
        {"Name": "E", "MemberId": "4", "Status": {"State": "Enabled"}, "PowerInputWatts": 0},
    ]}
    monkeypatch.setattr(rg, "_get", _routed({"Chassis/1/Power": (200, power, None)}, []))
    out, errs = rg.gather_power("10.0.0.1", "/redfish/v1/Chassis/1", *CREDS)
    assert [n["message"] for n in rg.notices()] == ["전원 공급 장치 A[0]: 입력 전력 0 W / 입력 전압 0 V 관측", "전원 공급 장치 E[4]: 입력 전력 0 W 관측"]
    assert len(out["power_supplies"]) == 5 and errs == []


def _subsystem_routes(psu_metrics, telemetry=None):
    r = {
        "Chassis/1/Power": (404, {}, "HTTP 404: Not Found"),
        "Chassis/1/PowerSubsystem": (200, {"PowerSupplies": {"@odata.id": "/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies"}}, None),
        "Chassis/1/PowerSubsystem/PowerSupplies": (200, {"Members": [{"@odata.id": f"/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies/{i}"} for i in range(len(psu_metrics))]}, None),
    }
    for i, m in enumerate(psu_metrics):
        r[f"Chassis/1/PowerSubsystem/PowerSupplies/{i}"] = (200, {"Id": str(i), "Name": f"PSU{i}", "PowerCapacityWatts": 800, "Status": {"State": "Enabled"},
                                                                  "Metrics": {"@odata.id": f"/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies/{i}/Metrics"}}, None)
        r[f"Chassis/1/PowerSubsystem/PowerSupplies/{i}/Metrics"] = (200, m, None)
    return r


def test_consumed_power_fallback_prefers_psu_output_sum_over_input_sum(monkeypatch):
    rg._reset_notices()
    routes = _subsystem_routes([{"InputPowerWatts": {"Reading": 400}, "OutputPowerWatts": {"Reading": 350}},
                                {"InputPowerWatts": {"Reading": 420}, "OutputPowerWatts": {"Reading": 360}}])
    monkeypatch.setattr(rg, "_get", _routed(routes, []))
    out, _ = rg.gather_power("10.0.0.1", "/redfish/v1/Chassis/1", *CREDS)
    assert out["power_control"]["power_consumed_watts"] == 710                 # 출력 합 (입력 합 820 이 아님)
    routes2 = _subsystem_routes([{"InputPowerWatts": {"Reading": 400}}, {"InputPowerWatts": {"Reading": 420}}])
    monkeypatch.setattr(rg, "_get", _routed(routes2, []))
    out2, _ = rg.gather_power("10.0.0.1", "/redfish/v1/Chassis/1", *CREDS)
    assert out2["power_control"]["power_consumed_watts"] == 820                # 출력이 없으면 입력 합
    routes3 = _subsystem_routes([{"InputPowerWatts": {"Reading": 0}, "InputVoltage": {"Reading": 0}, "OutputPowerWatts": {"Reading": 0}}])
    monkeypatch.setattr(rg, "_get", _routed(routes3, []))
    rg.gather_power("10.0.0.1", "/redfish/v1/Chassis/1", *CREDS)
    assert [n["message"] for n in rg.notices()] == ["전원 공급 장치 PSU0[0]: 입력 전력 0 W / 입력 전압 0 V 관측"]


def test_thermal_subsystem_absent_name_fallback_and_rpm(monkeypatch):
    rg._reset_notices()
    routes = {
        "Chassis/1/Thermal": (404, {}, "HTTP 404: Not Found"),
        "Chassis/1/ThermalSubsystem": (200, {"ThermalMetrics": {"@odata.id": "/redfish/v1/Chassis/1/ThermalSubsystem/ThermalMetrics"},
                                             "Fans": {"@odata.id": "/redfish/v1/Chassis/1/ThermalSubsystem/Fans"}}, None),
        "Chassis/1/ThermalSubsystem/ThermalMetrics": (200, {"TemperatureReadingsCelsius": [
            {"DeviceName": "CPU1", "Reading": 41.2, "Status": {"State": "Enabled"}},
            {"Reading": 30.0, "DataSourceUri": "/redfish/v1/Chassis/1/Sensors/InletTemp", "Status": {"State": "Enabled"}},   # 이름 폴백
            {"DeviceName": "Slot9", "Reading": 0, "Status": {"State": "Absent"}},                                           # 제외
            {"DeviceName": "NoStatus", "Reading": 25.0},                                                                     # Status 없음 → 보존
        ]}, None),
        "Chassis/1/ThermalSubsystem/Fans": (200, {"Members": [{"@odata.id": "/redfish/v1/Chassis/1/ThermalSubsystem/Fans/0"},
                                                              {"@odata.id": "/redfish/v1/Chassis/1/ThermalSubsystem/Fans/1"}]}, None),
        "Chassis/1/ThermalSubsystem/Fans/0": (200, {"Name": "Fan0", "SpeedPercent": {"SpeedRPM": 4410}, "Status": {"State": "Enabled"}}, None),    # RPM 폴백
        "Chassis/1/ThermalSubsystem/Fans/1": (200, {"Name": "Fan1", "SpeedPercent": {"Reading": 40}, "Status": {"State": "Absent"}}, None),         # 제외
    }
    monkeypatch.setattr(rg, "_get", _routed(routes, []))
    out, errs = rg.gather_thermal("10.0.0.1", "/redfish/v1/Chassis/1", *CREDS)
    names = [t["name"] for t in out["temperatures"]]
    assert names == ["CPU1", "InletTemp", "NoStatus"]
    assert [t["reading_celsius"] for t in out["temperatures"]] == [41, 30, 25]
    assert out["fans"] == [{"name": "Fan0", "reading": 4410, "reading_units": "RPM", "health": None, "state": "Enabled"}]
    assert [n["message"] for n in rg.notices()] == ["Absent 센서 2건 제외 (온도 1 · 팬 1) — 미장착 슬롯"]


def test_helpers():
    assert rg._sensor_is_absent({"Status": {"State": "Absent"}}) and rg._sensor_is_absent({"Status": {"State": " absent "}})
    assert not rg._sensor_is_absent({"Status": {"State": "Enabled"}}) and not rg._sensor_is_absent({}) and not rg._sensor_is_absent({"Status": "x"})
    rg._reset_notices()
    rg._psu_zero_input_notice("P", None, None, None); rg._psu_zero_input_notice("P", "1", 5, 230)
    assert rg.notices() == []
    rg._psu_zero_input_notice(None, "2", 0, None)
    assert [n["message"] for n in rg.notices()] == ["전원 공급 장치 PSU[2]: 입력 전력 0 W 관측"]
