"""전력 측정값 반올림 · 측정 범위 제외 · PSU 0 rollup (2026-10-29 SA-17 · SA-19 · SA-06).

  SA-17  측정값(소비 · min/avg/max · PSU 입출력 · Telemetry 합계)은 _safe_round_int 로 정수화한다 — round() 는 half-even
         (591.5 → 592, 592.5 → 592). 정격(PowerCapacityWatts)은 종전 _safe_int(절삭) 그대로다. 타입은 정수(사용자 결정).
  SA-19  EnvironmentMetrics PowerWatts.ReadingRangeMin/Max 는 DMTF Sensor 의 측정 가능 범위이지 관측한 최소/최대가 아니다
         → min/max_consumed_watts 는 null (source: https://redfish.dmtf.org/schemas/v1/Sensor.json).
  SA-06  설치 PSU 가 0 이면 power.summary.health_rollup 은 null — 'Unknown' 은 PSU 는 있으나 상태를 모두 모를 때만이다.
         Redfish(_rf_power_summary Jinja)와 ESXi(filter_plugins/power_summary.py)가 같은 값을 낸다(사용자 결정 — 두 채널 함께).
기대값은 원천 값과 위 규칙으로 손으로 적었다(현재 출력 복사 아님, rule 95 R3).
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
sys.path.insert(0, str(REPO / "filter_plugins"))
for _n in ("ansible", "ansible.module_utils", "ansible.module_utils.basic"):
    sys.modules.setdefault(_n, types.ModuleType(_n))
if not hasattr(sys.modules["ansible.module_utils.basic"], "AnsibleModule"):
    sys.modules["ansible.module_utils.basic"].AnsibleModule = object

import redfish_gather as rg  # noqa: E402
import emulator_harness as H  # noqa: E402
import normalize_chain as NC  # noqa: E402
from power_summary import power_summary  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "redfish"
CH = "/redfish/v1/Chassis/1"


@pytest.fixture(autouse=True)
def _reset():
    rg._reset_notices()
    yield
    rg._reset_notices()


def _fake_get(routes):
    """routes = [(경로 부분 문자열, (status, body)), ...] — 앞에서부터 처음 맞는 것. 없으면 404 (BMC 가 그 경로를 주지 않음)."""
    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        for needle, (status, body) in routes:
            if needle in path:
                return status, body, None
        return 404, {}, "HTTP 404: Not Found"
    return fake_get


def _replay(name):
    rec = json.loads((FIX / name / "recording.json").read_text(encoding="utf-8"))
    meta = json.loads((FIX / name / "meta.json").read_text(encoding="utf-8")) if (FIX / name / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    return rec, H.run_gather(g, n, realm_impl=r, manager_layout=meta.get("manager_layout"),
                             firmware_scope=meta.get("firmware_inventory_scope"))


# ── SA-17 반올림 함수 ────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    (591.5, 592), (592.5, 592), (815.75, 816), (945.75, 946), (600.25, 600), ("1000.5", 1000),   # half-even: x.5 는 짝수 쪽
    ("903.0", 903), (412, 412), ("412.6", 413), (0, 0), (0.4, 0),
    ("N/A", None), ("", None), (None, None), (float("nan"), None), (float("inf"), None), ("-inf", None), ([], None),
])
def test_safe_round_int_is_half_even_and_rejects_non_numbers(raw, expected):
    assert rg._safe_round_int(raw) == expected


def test_capacity_helper_still_truncates():
    """정격은 SA-17 범위 밖 — _safe_int 는 int() 절삭 그대로, 소수 문자열은 받지 않는다."""
    assert rg._safe_int(799.9) == 799 and rg._safe_int("800") == 800 and rg._safe_int("800.5") is None


# ── SA-17 Telemetry TotalPowerConsumedWatts (HPE CSUS 경로) ─────────────────────────────────────────────────────────────

_REPORT = "/redfish/v1/TelemetryService/MetricReports/Chassisr001u01_TotalPowerConsumedWatts"


def _telemetry(value):
    return [("MetricReports/Chassisr001u01_TotalPowerConsumedWatts",
             (200, {"MetricValues": [{"MetricId": "TotalPowerConsumedWatts", "MetricValue": value}]})),
            ("TelemetryService/MetricReports", (200, {"Members": [{"@odata.id": _REPORT}]}))]


@pytest.mark.parametrize("value, expected", [
    ("815.75", 816), ("591.5", 592), ("592.5", 592), ("945.75", 946), ("600.25", 600), ("1000.5", 1000), ("903.0", 903),
    ("N/A", None), ("NaN", None), ("", None),
])
def test_telemetry_total_power_rounds(monkeypatch, value, expected):
    monkeypatch.setattr(rg, "_get", _fake_get(_telemetry(value)))
    assert rg._telemetry_total_power("10.0.0.1", "/redfish/v1/Chassis/r001u01", "u", "p", 30, False) == expected


@pytest.mark.parametrize("name, source, expected", [
    ("real_hpe_csus3200", "591.5", 592),      # 종전 절삭 591
    ("real_hpe_csus3200_02", "815.75", 816),  # 종전 절삭 815
    ("real_hpe_csus3200_01", "903.0", 903),   # 원천이 정수 — 불변
    ("real_hpe_csus3200_03", "867.0", 867),
])
def test_csus_recordings_consumed_watts_follow_source(name, source, expected):
    rec, res = _replay(name)
    rep = rec["get::TelemetryService/MetricReports/Chassisr001u01_TotalPowerConsumedWatts"][1]
    assert [m["MetricValue"] for m in rep["MetricValues"] if m["MetricId"] == "TotalPowerConsumedWatts"] == [source]
    power = res["data"]["power"]
    assert power["power_control"]["power_consumed_watts"] == expected
    assert isinstance(power["power_control"]["power_consumed_watts"], int)


# ── SA-17 · SA-19 PowerSubsystem 경로 (PSU Metrics · EnvironmentMetrics) ─────────────────────────────────────────────────

def _psub(metrics, env_metrics=None):
    """PSU 마다 Metrics 를 둔 PowerSubsystem. 정격 800.9 W 는 절삭 확인용."""
    routes, members = [], []
    for i, mm in enumerate(metrics):
        base = f"Chassis/1/PowerSubsystem/PowerSupplies/{i}"
        routes.append((base + "/Metrics", (200, mm)))
        routes.append((base, (200, {"Name": f"PSU{i}", "Id": str(i), "PowerCapacityWatts": 800.9,
                                    "Status": {"Health": "OK", "State": "Enabled"},
                                    "Metrics": {"@odata.id": f"/redfish/v1/{base}/Metrics"}})))
        members.append({"@odata.id": f"/redfish/v1/{base}"})
    routes.append(("Chassis/1/PowerSubsystem/PowerSupplies", (200, {"Members": members})))
    routes.append(("Chassis/1/PowerSubsystem", (200, {"PowerSupplies": {"@odata.id": f"{CH}/PowerSubsystem/PowerSupplies"}})))
    if env_metrics is not None:
        routes.append(("Chassis/1/EnvironmentMetrics", (200, env_metrics)))
    return routes


def test_psu_output_sum_rounds_each_reading(monkeypatch):
    """EnvironmentMetrics · Telemetry 없음 → PSU 출력 합. PSU 마다 반올림한 뒤 더한다: 230.5 → 230, 231.5 → 232 (half-even) = 462."""
    monkeypatch.setattr(rg, "_get", _fake_get(_psub([
        {"InputPowerWatts": {"Reading": 250.5}, "OutputPowerWatts": {"Reading": 230.5}},
        {"InputPowerWatts": {"Reading": 251.5}, "OutputPowerWatts": {"Reading": 231.5}}])))
    data, errs = rg._gather_power_subsystem("10.0.0.1", CH, "u", "p", 30, False)
    assert errs == []
    assert data["power_control"]["power_consumed_watts"] == 462
    assert [p["power_capacity_w"] for p in data["power_supplies"]] == [800, 800]   # 정격은 절삭 그대로
    assert data["power_control"]["power_capacity_watts"] == 1600


def test_psu_input_sum_is_last_fallback_and_rounds(monkeypatch):
    """출력 키가 없으면 입력 합: 250.5 → 250, 251.5 → 252 = 502."""
    monkeypatch.setattr(rg, "_get", _fake_get(_psub([
        {"InputPowerWatts": {"Reading": 250.5}}, {"InputPowerWatts": {"Reading": "251.5"}}])))
    data, errs = rg._gather_power_subsystem("10.0.0.1", CH, "u", "p", 30, False)
    assert errs == [] and data["power_control"]["power_consumed_watts"] == 502


@pytest.mark.parametrize("reading, expected", [(412.5, 412), (413.5, 414), ("412.6", 413), ("N/A", None)])
def test_environment_metrics_reading_rounds_and_range_is_not_min_max(monkeypatch, reading, expected):
    """SA-19: ReadingRangeMin/Max(측정 가능 범위 0 ~ 2000 W)를 min/max 소비전력으로 쓰지 않는다."""
    monkeypatch.setattr(rg, "_get", _fake_get(_psub(
        [{}], env_metrics={"PowerWatts": {"Reading": reading, "ReadingRangeMin": 0, "ReadingRangeMax": 2000}})))
    data, errs = rg._gather_power_subsystem("10.0.0.1", CH, "u", "p", 30, False)
    pc = data["power_control"]
    assert errs == []
    assert pc["power_consumed_watts"] == expected
    assert pc["min_consumed_watts"] is None and pc["max_consumed_watts"] is None
    assert pc["avg_consumed_watts"] is None and pc["interval_in_min"] is None


# ── SA-17 legacy Power 경로 ──────────────────────────────────────────────────────────────────────────────────────────────

def test_legacy_power_rounds_measurements_and_truncates_ratings(monkeypatch):
    power = {
        "PowerSupplies": [{"Name": "PS1", "MemberId": "0", "PowerCapacityWatts": 799.9, "PowerInputWatts": 300.5,
                           "LineInputVoltage": 230, "Status": {"Health": "OK", "State": "Enabled"}}],
        "PowerControl": [{"PowerConsumedWatts": 591.5, "PowerCapacityWatts": 1600.7,
                          "PowerMetrics": {"IntervalInMin": 20, "MinConsumedWatts": 100.5,
                                           "AverageConsumedWatts": "300.5", "MaxConsumedWatts": 501.5}}],
    }
    monkeypatch.setattr(rg, "_get", _fake_get([("Chassis/1/Power", (200, power))]))
    data, errs = rg.gather_power("10.0.0.1", CH, "u", "p", 30, False)
    assert errs == []
    assert data["power_control"] == {
        "power_consumed_watts": 592,     # 591.5 (half-even)
        "power_capacity_watts": 1600,    # 정격 — 절삭 그대로
        "interval_in_min": 20,
        "min_consumed_watts": 100,       # 100.5 (half-even)
        "avg_consumed_watts": 300,       # 소수 문자열 "300.5" — 종전 _safe_int 는 None 으로 버렸다
        "max_consumed_watts": 502,       # 501.5 (half-even)
    }
    assert data["power_supplies"][0]["power_capacity_w"] == 799
    assert rg._NOTICES == []             # 입력 300.5 W → 0 W 관측 아님


def test_legacy_zero_input_notice_uses_rounded_reading(monkeypatch):
    """0 W 관측 notice 는 반올림한 값이 0 일 때만 — 0.4 W 는 0, 0.6 W 는 1 W 다."""
    psus = [{"Name": "PS1", "MemberId": "0", "PowerInputWatts": 0.4, "Status": {"Health": "OK", "State": "Enabled"}},
            {"Name": "PS2", "MemberId": "1", "PowerInputWatts": 0.6, "Status": {"Health": "OK", "State": "Enabled"}}]
    monkeypatch.setattr(rg, "_get", _fake_get([("Chassis/1/Power", (200, {"PowerSupplies": psus}))]))
    rg.gather_power("10.0.0.1", CH, "u", "p", 30, False)
    assert [n["message"] for n in rg._NOTICES if n["section"] == "power"] == ["전원 공급 장치 PS1[0]: 입력 전력 0 W 관측"]


# ── SA-06 health_rollup — Redfish Jinja 와 ESXi filter 가 같은 규칙 ────────────────────────────────────────────────────────

def _psu(state="Enabled", health="OK"):
    return {"name": "PSU", "state": state, "health": health, "power_capacity_w": 800}


def _rf_power_summary(power):
    return NC.env().from_string(NC.task(NC.SUMMARIES)["_rf_power_summary"]).render(_rf_d_power=power)


@pytest.mark.parametrize("psus, rollup, count", [
    ([], None, 0),                                                    # 집계할 PSU 가 없다 (종전 'Unknown')
    ([_psu("Absent", None), _psu("Absent", "Warning")], None, 0),     # 빈 슬롯만 (실측 dl380_gen12_03: Absent + Health Warning ×2)
    ([_psu(health=None), _psu(health="")], "Unknown", 2),            # 설치 PSU 는 있으나 상태 미보고
    ([_psu(), _psu()], "OK", 2),
    ([_psu(), _psu(health="Warning")], "Warning", 2),
    ([_psu(health="Warning"), _psu(health="Critical")], "Critical", 2),
    ([_psu("Absent", "Critical"), _psu()], "OK", 1),                 # 빈 슬롯의 상태는 세지 않는다
], ids=["no_psu", "all_absent", "health_unreported", "ok", "warning", "critical", "absent_slot_ignored"])
def test_health_rollup_same_rule_on_redfish_and_esxi(psus, rollup, count):
    power = {"power_supplies": psus, "power_control": None}
    rf = _rf_power_summary(power)
    assert rf == power_summary(power)
    assert (rf["health_rollup"], rf["psu_count"]) == (rollup, count)


def test_dl380_gen12_03_all_absent_psus_rollup_null():
    """실측 recording: PSU 슬롯 2개가 모두 State=Absent(Health=Warning) — 설치 PSU 0 → health_rollup null, psu_count 0."""
    rec, res = _replay("real_hpe_dl380_gen12_03")
    assert [(p["Status"]["State"], p["Status"]["Health"]) for p in rec["get::Chassis/1/Power"][1]["PowerSupplies"]] == [
        ("Absent", "Warning"), ("Absent", "Warning")]
    ctx = NC.render(NC.raw_collect(res))
    s = ctx["_rf_power_summary"]
    assert (s["psu_count"], s["health_rollup"], s["redundant"]) == (0, None, False)
    assert len(res["data"]["power"]["power_supplies"]) == 2      # 목록에는 남는다 (D-07)
