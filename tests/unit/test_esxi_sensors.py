"""ESXi power / thermal ← vSphere 하드웨어 센서 (2026-10-19, 사용자 승인 — ADR-2026-10-19-esxi-sensors-and-linux-iscsi).

무엇을 고정하나
--------------
1. `esxi_disks._build_sensors` — runtime.healthSystemRuntime.systemHealthInfo.numericSensorInfo 를 Redfish 와 같은 항목 모양으로:
   temperature → temperatures[] (currentReading×10^unitModifier 반올림 · physical_context 는 엔티티 접두), fan → fans[] (RPM),
   "Power Supply N" power 센서 → power_supplies[] 1건(health 최악값 · 식별/용량 null), PSU 가 아닌 Watts 센서가 정확히 1개 → power_consumed_watts.
   systemHealthInfo 없음 → available=false. 실측 덤프 3대(tests/reference/esxi, Cisco TA-UNODE-G1 · ESXi 7)를 그대로 재생한다 —
   덤프의 healthState.key 는 수집기가 잘라 둔 자리라 green 으로 채운다(값 계약은 합성 케이스가 본다).
2. `esxi-gather/tasks/normalize_power_thermal.yml` — success / not_supported / failed 세 갈래의 fragment · sections · errors.
3. `filter_plugins/power_summary.py` ↔ `normalize_standard.yml` `_rf_power_summary` 가 같은 입력에 같은 값 (한쪽만 바꾸면 여기서 막힌다).
4. 계약 배선 — adapter 5종 sections_supported · supported_sections.yml · sections.yml · field_dictionary channel · 범위 감사 허용 목록.

pyvmomi 없음 · 실장비 미검증 (실호스트 값은 Jenkins ESXi 매트릭스로 확인한다).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

yaml = pytest.importorskip("yaml")
from jinja2 import StrictUndefined  # noqa: E402
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "filter_plugins"))
sys.path.insert(0, str(REPO / "tests" / "unit"))

from power_summary import power_summary  # noqa: E402
from test_esxi_raid_lun_logical_volumes import _content, _module  # noqa: E402

DUMPS = sorted((REPO / "tests" / "reference" / "esxi").glob("*/pyvmomi_host_dump.json"))
PT_YML = REPO / "esxi-gather" / "tasks" / "normalize_power_thermal.yml"


# ─────────────────────────────────────────────────────────────────────────────
# 합성 센서 / 호스트
# ─────────────────────────────────────────────────────────────────────────────
def sensor(name, stype, reading, mod=0, units="unspecified", health="green", sid="0.0.0.0"):
    return NS(name=name, sensorType=stype, currentReading=reading, unitModifier=mod, baseUnits=units,
              healthState=NS(key=health), id=sid, rateUnits="none")


def host_with(sensors, *, no_health=False, no_info=False):
    if no_health:
        runtime = NS(healthSystemRuntime=None)
    elif no_info:
        runtime = NS(healthSystemRuntime=NS(systemHealthInfo=None, hardwareStatusInfo=None))
    else:
        runtime = NS(healthSystemRuntime=NS(systemHealthInfo=NS(numericSensorInfo=sensors), hardwareStatusInfo=None))
    return NS(name="esxi01", runtime=runtime,
              configManager=NS(storageSystem=NS(storageDeviceInfo=NS(scsiLun=[]))),
              config=NS(storageDevice=NS(hostBusAdapter=[], scsiTopology=None)), hardware=NS(pciDevice=[]))


def build(sensors, **kw):
    return _module()._build_sensors(_content([host_with(sensors, **kw)]))


def dump_sensors(path: Path, health="green"):
    j = json.loads(path.read_text(encoding="utf-8"))
    rows = ((j.get("runtime") or {}).get("healthSystemRuntime") or {}).get("systemHealthInfo", {}).get("numericSensorInfo") or []
    return [sensor(r["name"], r["sensorType"], r["currentReading"], r.get("unitModifier", 0), r.get("baseUnits"), health, r.get("id"))
            for r in rows]


SYNTH = [
    sensor("System Board 4 RISER2_OUTLETTMP", "temperature", 4700, -2, "degrees C"),
    sensor("Processor 1 P1_TEMP_SENS", "temperature", 5550, -2, "degrees C", "yellow"),
    sensor("Memory Module 22 DDR4_P2_H2_TEMP", "temperature", 4900, -2, "degrees C"),
    sensor("Power Supply 1 PSU1_TEMP", "temperature", 4500, -2, "degrees C"),
    sensor("Disk or Disk Bay 7 HDD8_TEMP", "temperature", 31, 0, "degrees C", "unknown"),
    sensor("Fan Device 6 FAN6_TACH2", "fan", 1410000, -2, "RPM"),
    sensor("Fan Device 1 FAN1_TACH1", "fan", 60, 0, "Percent", "red"),
    sensor("Power Supply 2 PSU2_PIN", "power", 23200, -2, "Watts"),
    sensor("Power Supply 2 PSU2_STATUS", "power", 1, 0, "unspecified", "red"),
    sensor("Power Supply 1 PSU1_PIN", "power", 23200, -2, "Watts"),
    sensor("Power Supply 1 PSU1_IOUT", "power", 1900, -2, "Amps"),
    sensor("Power Module (DC-to-DC) 0 PS_RDNDNT_MODE", "power", 1, 0, "unspecified"),
    sensor("System Board 0 POWER_USAGE", "power", 47200, -2, "Watts"),
    sensor("Processor 2 PVPP_GH", "voltage", 261, -2, "Volts"),
    sensor("Memory Module 22 DDR4_P2_H2_ECC", "memory", 0, -2, "error"),
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. 모듈 파트
# ─────────────────────────────────────────────────────────────────────────────
class TestBuildSensors:
    def test_temperatures_scaled_rounded_with_health_and_context(self):
        out = build(SYNTH)
        assert out["available"] is True and out["sensor_count"] == len(SYNTH)
        temps = {t["name"]: t for t in out["temperatures"]}
        assert len(temps) == 5
        t = temps["System Board 4 RISER2_OUTLETTMP"]
        assert t == {"name": "System Board 4 RISER2_OUTLETTMP", "reading_celsius": 47, "health": "OK", "state": "Enabled",
                     "upper_critical": None, "physical_context": "SystemBoard"}
        assert temps["Processor 1 P1_TEMP_SENS"]["reading_celsius"] == 56 and temps["Processor 1 P1_TEMP_SENS"]["health"] == "Warning"
        assert temps["Processor 1 P1_TEMP_SENS"]["physical_context"] == "CPU"
        assert temps["Memory Module 22 DDR4_P2_H2_TEMP"]["physical_context"] == "Memory"
        assert temps["Power Supply 1 PSU1_TEMP"]["physical_context"] == "PowerSupply"
        assert temps["Disk or Disk Bay 7 HDD8_TEMP"]["physical_context"] == "StorageDevice"
        assert temps["Disk or Disk Bay 7 HDD8_TEMP"]["health"] is None, "unknown 은 null — 추정하지 않는다"
        assert all(isinstance(t["reading_celsius"], int) for t in out["temperatures"])

    def test_fans_keep_units_and_red_is_critical(self):
        fans = {f["name"]: f for f in build(SYNTH)["fans"]}
        assert fans["Fan Device 6 FAN6_TACH2"] == {"name": "Fan Device 6 FAN6_TACH2", "reading": 14100, "reading_units": "RPM",
                                                   "health": "OK", "state": "Enabled"}
        assert fans["Fan Device 1 FAN1_TACH1"] == {"name": "Fan Device 1 FAN1_TACH1", "reading": 60, "reading_units": "Percent",
                                                   "health": "Critical", "state": "Enabled"}

    def test_power_supplies_grouped_by_name_with_worst_health_and_redfish_keys(self):
        out = build(SYNTH)
        psus = out["power_supplies"]
        assert [p["name"] for p in psus] == ["Power Supply 1", "Power Supply 2"]
        assert set(psus[0]) == {"name", "model", "serial", "manufacturer", "part_number", "power_capacity_w", "firmware_version", "health", "state"}
        assert psus[0]["health"] == "OK" and psus[1]["health"] == "Critical", "PSU2 는 STATUS 센서가 red — 최악값"
        assert all(p["state"] == "Enabled" and p["power_capacity_w"] is None and p["model"] is None for p in psus)
        # 소비전력: PSU 가 아닌 Watts 센서가 1개(POWER_USAGE) → 그 값. PSU 의 PIN/IOUT · 전압 · 메모리 센서는 섞이지 않는다
        assert out["power_control"] == {"power_consumed_watts": 472, "power_capacity_watts": None, "interval_in_min": None,
                                        "min_consumed_watts": None, "avg_consumed_watts": None, "max_consumed_watts": None}
        assert [(s["name"], s["watts"], s["psu"]) for s in out["power_sensors"]] == [
            ("Power Supply 2 PSU2_PIN", 232, 2), ("Power Supply 1 PSU1_PIN", 232, 1), ("System Board 0 POWER_USAGE", 472, None)]

    def test_two_non_psu_watts_sensors_do_not_pick_one(self):
        sensors = SYNTH + [sensor("System Board 1 PWR_IN", "power", 50000, -2, "Watts")]
        out = build(sensors)
        assert out["power_control"]["power_consumed_watts"] is None, "둘 중 하나를 고르지 않는다 (null)"
        assert len(out["power_sensors"]) == 4

    def test_no_psu_and_no_watts_gives_null_power_control(self):
        out = build([SYNTH[0], SYNTH[5]])
        assert out["power_supplies"] == [] and out["power_control"] is None
        assert len(out["temperatures"]) == 1 and len(out["fans"]) == 1

    def test_missing_health_info_is_not_available(self):
        for kw in ({"no_health": True}, {"no_info": True}):
            out = build([], **kw)
            assert out["available"] is False and out["temperatures"] == [] and out["power_supplies"] == [] and out["power_control"] is None

    def test_empty_sensor_list_is_available_with_empty_lists(self):
        out = build([])
        assert out["available"] is True and out["sensor_count"] == 0 and out["temperatures"] == [] and out["fans"] == []

    def test_reading_scaling_helpers(self):
        m = _module()
        assert m._sensor_reading(sensor("x", "fan", 1410000, -2, "RPM")) == 14100
        assert m._sensor_reading(sensor("x", "temperature", 5550, -2, "degrees C")) == 55.5
        assert m._sensor_reading(NS(currentReading=None, unitModifier=0)) is None
        assert m._sensor_reading(NS(currentReading="abc", unitModifier=0)) is None
        assert m._sensor_health(NS(healthState={"key": "Yellow"})) == "Warning", "dict 모양(덤프 재생)도 받는다 · 대소문자 무시"
        assert m._sensor_health(NS(healthState=None)) is None
        assert m._physical_context("Fan Device 6 FAN6_TACH2") == "Fan" and m._physical_context("Riser 1") is None
        assert m._fan_units("rpm") == "RPM" and m._fan_units("percentage") == "Percent" and m._fan_units("foo") == "foo"

    @pytest.mark.skipif(not DUMPS, reason="tests/reference/esxi 덤프 없음")
    @pytest.mark.parametrize("dump", DUMPS, ids=[p.parent.name for p in DUMPS])
    def test_real_dumps_replay(self, dump):
        out = build(dump_sensors(dump))
        assert out["available"] is True and out["sensor_count"] == 126
        assert len(out["temperatures"]) == 28 and len(out["fans"]) == 12
        assert [p["name"] for p in out["power_supplies"]] == ["Power Supply 1", "Power Supply 2"]
        assert out["power_control"]["power_consumed_watts"] == {"10_100_64_1": 472, "10_100_64_2": 432, "10_100_64_3": 456}[dump.parent.name]
        assert all(f["reading_units"] == "RPM" and 10000 <= f["reading"] <= 15000 for f in out["fans"])
        assert all(20 <= t["reading_celsius"] <= 70 for t in out["temperatures"])
        assert {t["physical_context"] for t in out["temperatures"]} <= {"SystemBoard", "PowerSupply", "CPU", "Memory", None}
        # power_summary 까지 — 용량은 센서에 없으므로 null, 소비전력은 있다
        s = power_summary({"power_supplies": out["power_supplies"], "power_control": out["power_control"]})
        assert s["psu_count"] == 2 and s["psu_active"] == 2 and s["redundant"] is True
        assert s["total_capacity_w"] is None and s["capacity_unknown_count"] == 2 and s["consumed_capacity_pct"] is None
        assert s["consumed_watts"] == out["power_control"]["power_consumed_watts"] and s["health_rollup"] == "OK"

    def test_main_result_carries_sensors_key(self):
        text = (REPO / "esxi-gather" / "library" / "esxi_disks.py").read_text(encoding="utf-8")
        assert "sensors = _safe_build('sensors', _build_sensors, target, part_errors, default={})" in text
        assert "sensors=sensors," in text


# ─────────────────────────────────────────────────────────────────────────────
# 2. normalize_power_thermal.yml 렌더
# ─────────────────────────────────────────────────────────────────────────────
def _env():
    env = NativeEnvironment(undefined=StrictUndefined)
    env.filters["power_summary"] = power_summary
    env.filters["bool"] = lambda v: v if isinstance(v, bool) else str(v).strip().lower() in ("true", "yes", "1", "on")
    return env


def _render_tree(env, value, ctx):
    if isinstance(value, str):
        return env.from_string(value).render(**ctx)
    if isinstance(value, dict):
        return {k: _render_tree(env, v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_tree(env, v, ctx) for v in value]
    return value


def run_pt(ctx):
    env = _env()
    ctx = dict(ctx)
    for task in yaml.safe_load(PT_YML.read_text(encoding="utf-8")):
        sf = task.get("ansible.builtin.set_fact")
        if not isinstance(sf, dict):
            continue
        for key, value in sf.items():
            ctx[key] = _render_tree(env, value, ctx)
    return ctx


def test_task_file_has_merge_after_fragment_and_only_own_sections():
    tasks = yaml.safe_load(PT_YML.read_text(encoding="utf-8"))
    names = [t.get("name") for t in tasks]
    assert names[-1] == "esxi | normalize power/thermal | merge fragment" and "merge_fragment.yml" in str(tasks[-1])
    frag = tasks[1]["ansible.builtin.set_fact"]
    assert frag["_sections_supported_fragment"] == ["power", "thermal"]
    for key in ("_data_fragment", "_sections_collected_fragment", "_sections_failed_fragment", "_sections_unsupported_fragment", "_errors_fragment"):
        assert key in frag


def test_render_success_builds_power_and_thermal_with_summary():
    sensors = build(SYNTH)
    ctx = run_pt({"_e_disks_failed_parts": [], "_e_raw_sensors": sensors, "_e_disks_err": None})
    assert ctx["_e_pt_failed"] is False and ctx["_e_pt_available"] is True
    frag = ctx["_data_fragment"]
    assert set(frag) == {"power", "thermal"}
    assert frag["thermal"] == {"temperatures": sensors["temperatures"], "fans": sensors["fans"]}
    assert frag["power"]["power_supplies"] == sensors["power_supplies"] and frag["power"]["power_control"] == sensors["power_control"]
    assert frag["power"]["summary"] == {"psu_count": 2, "psu_active": 2, "redundant": True, "total_capacity_w": None, "capacity_unknown_count": 2,
                                        "critical_count": 1, "warning_count": 0, "ok_count": 1, "unknown_health_count": 0,
                                        "health_rollup": "Critical", "consumed_watts": 472, "consumed_capacity_pct": None}
    assert ctx["_sections_collected_fragment"] == ["power", "thermal"]
    assert ctx["_sections_failed_fragment"] == [] and ctx["_sections_unsupported_fragment"] == [] and ctx["_errors_fragment"] == []


def test_render_not_available_is_not_supported_without_errors():
    ctx = run_pt({"_e_disks_failed_parts": [], "_e_raw_sensors": build([], no_info=True), "_e_disks_err": None})
    assert ctx["_data_fragment"] == {}
    assert ctx["_sections_unsupported_fragment"] == ["power", "thermal"]
    assert ctx["_sections_collected_fragment"] == [] and ctx["_sections_failed_fragment"] == [] and ctx["_errors_fragment"] == []


def test_render_old_module_without_sensors_key_is_not_supported():
    ctx = run_pt({"_e_disks_failed_parts": [], "_e_raw_sensors": {}, "_e_disks_err": None})
    assert ctx["_sections_unsupported_fragment"] == ["power", "thermal"] and ctx["_data_fragment"] == {}


@pytest.mark.parametrize("parts", [["sensors"], ["connect"], ["host_select"], ["module"], ["physical_disks", "sensors"]])
def test_render_failed_part_marks_both_sections_failed_with_two_errors(parts):
    ctx = run_pt({"_e_disks_failed_parts": parts, "_e_raw_sensors": {}, "_e_disks_err": "sensors: boom"})
    assert ctx["_sections_failed_fragment"] == ["power", "thermal"] and ctx["_sections_unsupported_fragment"] == []
    assert ctx["_data_fragment"] == {} and ctx["_sections_collected_fragment"] == []
    assert [e["section"] for e in ctx["_errors_fragment"]] == ["power", "thermal"]
    for e in ctx["_errors_fragment"]:
        assert e["detail"] == "sensors: boom" and e["message"].endswith("수집하지 못했습니다. 대상 상태와 수집 로그를 확인하세요.")


def test_render_other_part_failure_does_not_touch_power_thermal():
    sensors = build(SYNTH)
    ctx = run_pt({"_e_disks_failed_parts": ["physical_disks", "listening_ports"], "_e_raw_sensors": sensors, "_e_disks_err": "x"})
    assert ctx["_sections_collected_fragment"] == ["power", "thermal"] and ctx["_errors_fragment"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. power_summary 필터 ↔ Redfish _rf_power_summary Jinja 대조
# ─────────────────────────────────────────────────────────────────────────────
def _rf_power_summary_template():
    for task in yaml.safe_load((REPO / "redfish-gather" / "tasks" / "normalize_standard.yml").read_text(encoding="utf-8")):
        sf = task.get("ansible.builtin.set_fact") or {}
        if "_rf_power_summary" in sf:
            return sf["_rf_power_summary"]
    raise AssertionError("_rf_power_summary 미발견")


PSU = lambda state="Enabled", health="OK", cap=750: {"name": "PSU", "state": state, "health": health, "power_capacity_w": cap}  # noqa: E731
MIRROR_CASES = [
    {"power_supplies": [PSU(), PSU()], "power_control": {"power_consumed_watts": 261}},
    {"power_supplies": [PSU(cap=None), PSU(cap=None), PSU(cap=None), PSU(cap=None)], "power_control": {"power_consumed_watts": 591}},
    {"power_supplies": [PSU(), PSU(cap=None, health="Warning")], "power_control": {"power_consumed_watts": 300}},
    {"power_supplies": [PSU(state="Absent", cap=None), PSU(health="Critical", cap=1100)], "power_control": {"power_consumed_watts": None}},
    {"power_supplies": [PSU(state="UnavailableOffline", health=None, cap="800")], "power_control": None},
    {"power_supplies": [], "power_control": None},
    {"power_supplies": [PSU(cap=750)], "power_control": {"power_consumed_watts": 123.0}},
]


@pytest.mark.parametrize("power", MIRROR_CASES, ids=[f"case{i}" for i in range(len(MIRROR_CASES))])
def test_power_summary_filter_matches_redfish_jinja(power):
    rendered = NativeEnvironment().from_string(_rf_power_summary_template()).render(_rf_d_power=power)
    assert power_summary(power) == rendered


# ─────────────────────────────────────────────────────────────────────────────
# 4. 계약 배선
# ─────────────────────────────────────────────────────────────────────────────
def test_every_esxi_adapter_supports_power_and_thermal():
    for path in sorted((REPO / "adapters" / "esxi").glob("*.yml")):
        caps = set(yaml.safe_load(path.read_text(encoding="utf-8"))["capabilities"]["sections_supported"])
        assert {"power", "thermal"} <= caps, path.name
        assert ("power" in caps) == ("thermal" in caps), path.name


def test_channel_declarations_include_esxi_for_power_and_thermal():
    supported = yaml.safe_load((REPO / "common" / "vars" / "supported_sections.yml").read_text(encoding="utf-8"))
    assert {"power", "thermal"} <= set(supported["channel_sections"]["esxi"])
    sections = yaml.safe_load((REPO / "schema" / "sections.yml").read_text(encoding="utf-8"))["sections"]
    assert "esxi" in sections["power"]["channels"] and "esxi" in sections["thermal"]["channels"]
    fd = yaml.safe_load((REPO / "schema" / "field_dictionary.yml").read_text(encoding="utf-8"))["fields"]
    for key, entry in fd.items():
        if key.startswith("power.") or key.startswith("thermal."):
            assert "esxi" in entry["channel"], key
    allow = yaml.safe_load((REPO / "tests" / "reference" / "esxi" / "coverage_allowlist.yml").read_text(encoding="utf-8"))
    assert "runtime.healthSystemRuntime" not in (allow.get("groups") or {}), "이제 읽는 속성은 허용 목록에서 빠져야 한다"


def test_site_includes_power_thermal_before_build_sections():
    site = (REPO / "esxi-gather" / "site.yml").read_text(encoding="utf-8")
    assert site.index("tasks/normalize_power_thermal.yml") > site.index("tasks/collect_disks.yml")
    assert site.index("tasks/normalize_power_thermal.yml") < site.index("build_sections.yml")
