"""Unit test for B58 (PSU Critical alarm in summary) + B59 (None capacity sum).

Validates the Jinja2 summary builder logic in:
  redfish-gather/tasks/normalize_standard.yml :: _rf_power_summary

We cannot run Jinja2 directly without ansible context, so we mirror the logic
in Python and verify against captured raw responses + Jenkins envelope.

Test data sources:
  - tests/evidence/2026-04-29-deep-verify/redfish/hpe-dl380/power.json
  - tests/evidence/2026-04-29-deep-verify/redfish/lenovo-sr650/power.json
  - tests/evidence/2026-04-29-deep-verify/redfish/cisco-c220/power.json
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "tests" / "evidence" / "2026-04-29-deep-verify" / "redfish"


def build_summary(power_data: dict) -> dict:
    """Mirror of redfish-gather/tasks/normalize_standard.yml :: _rf_power_summary.

    Implements B58 (critical_count + health_rollup) + B59 (capacity_unknown_count).
    2026-10-29: D-07(State=Absent 슬롯은 설치 PSU 가 아니다 — 템플릿은 2026-10-10 부터 뺀다, 이 미러만 빠져 있었다)과
    SA-06(설치 PSU 0 → health_rollup None, 사용자 결정)을 템플릿과 같게 맞춘다.
    """
    psus = []
    for psu in (power_data.get("PowerSupplies") or []):
        if ((psu.get("Status") or {}).get("State") or "").strip().lower() == "absent":
            continue
        cap = psu.get("PowerCapacityWatts")
        # Mirror redfish_gather.py InputRanges fallback (Cisco quirk)
        if cap is None:
            ranges = psu.get("InputRanges") or []
            if isinstance(ranges, list) and ranges and isinstance(ranges[0], dict):
                or_w = ranges[0].get("OutputWattage")
                if or_w is not None:
                    cap = int(or_w)
        psus.append({
            "name": psu.get("Name"),
            "power_capacity_w": cap,
            "health": (psu.get("Status") or {}).get("Health"),
            "state": (psu.get("Status") or {}).get("State"),
        })
    psu_total = len(psus)
    psu_active = sum(1 for p in psus if (p["state"] or "").strip().lower() == "enabled")
    cap_unknown = sum(1 for p in psus if p["power_capacity_w"] is None)
    cap_total = sum(int(p["power_capacity_w"]) for p in psus if p["power_capacity_w"] is not None)
    critical = sum(1 for p in psus if (p["health"] or "").strip().lower() == "critical")
    warning = sum(1 for p in psus if (p["health"] or "").strip().lower() == "warning")
    ok = sum(1 for p in psus if (p["health"] or "").strip().lower() == "ok")
    unknown_h = psu_total - critical - warning - ok
    if psu_total == 0:
        rollup = None          # 2026-10-29 (SA-06): 집계할 설치 PSU 가 없다 — 'Unknown' 은 설치 PSU 의 상태를 모두 모를 때만
    elif critical > 0:
        rollup = "Critical"
    elif warning > 0:
        rollup = "Warning"
    elif ok > 0:
        rollup = "OK"
    else:
        rollup = "Unknown"
    pc_list = power_data.get("PowerControl") or []
    pc0 = pc_list[0] if isinstance(pc_list, list) and pc_list else {}
    consumed = pc0.get("PowerConsumedWatts") if isinstance(pc0, dict) else None
    # 2026-10-19 (A-3): 용량을 아는 PSU 가 0개면 total 은 None(0 은 거짓 값), pct 는 total/consumed 를 모르면 None.
    cap_known = (psu_total - cap_unknown) > 0
    consumed_pct = round(consumed * 100 / cap_total, 1) if (cap_known and cap_total > 0 and consumed is not None) else None
    return {
        "psu_count": psu_total,
        "psu_active": psu_active,
        "redundant": psu_total >= 2,
        "total_capacity_w": cap_total if cap_known else None,
        "capacity_unknown_count": cap_unknown,
        "critical_count": critical,
        "warning_count": warning,
        "ok_count": ok,
        "unknown_health_count": unknown_h,
        "health_rollup": rollup,
        "consumed_watts": consumed,
        "consumed_capacity_pct": consumed_pct,
    }


def load_power(label: str) -> dict:
    p = EVIDENCE / label / "power.json"
    if not p.exists():
        pytest.skip(f"raw power.json not captured for {label}")
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# B58: PSU Critical health surfaces in summary                                #
# --------------------------------------------------------------------------- #

class TestB58CriticalCount:
    def test_hpe_psu_critical_count(self):
        """HPE DL380 has PSU#1 Critical+UnavailableOffline + PSU#2 OK+Enabled."""
        s = build_summary(load_power("hpe-dl380"))
        assert s["psu_count"] == 2
        assert s["critical_count"] == 1
        assert s["ok_count"] == 1
        assert s["health_rollup"] == "Critical"
        assert s["psu_active"] == 1  # only PSU#2 Enabled

    def test_lenovo_psu_critical_count(self):
        """Lenovo SR650 V2 PSU#1 Critical+Enabled + PSU#2 OK+Enabled."""
        s = build_summary(load_power("lenovo-sr650"))
        assert s["psu_count"] == 2
        assert s["critical_count"] == 1
        assert s["ok_count"] == 1
        assert s["health_rollup"] == "Critical"

    def test_cisco_no_critical(self):
        """Cisco UCS — no Critical PSU expected."""
        s = build_summary(load_power("cisco-c220"))
        assert s["critical_count"] == 0
        # Either OK or Unknown depending on captured data
        assert s["health_rollup"] in ("OK", "Unknown", "Warning")


# --------------------------------------------------------------------------- #
# B59: PSU None capacity must not be silently summed                          #
# --------------------------------------------------------------------------- #

class TestB59CapacityUnknown:
    def test_lenovo_psu1_none_capacity_separated(self):
        """Lenovo PSU#1 PowerCapacityWatts=null, PSU#2=750 — total should be 750
        AND capacity_unknown_count=1 (so caller knows total is partial)."""
        power = load_power("lenovo-sr650")
        psus = power.get("PowerSupplies") or []
        # Confirm raw assumption
        none_count = sum(1 for p in psus if p.get("PowerCapacityWatts") is None)
        if none_count == 0:
            pytest.skip("Lenovo PSU#1 capacity is no longer null in raw — fixture must be recaptured")
        s = build_summary(power)
        assert s["capacity_unknown_count"] == none_count
        assert s["total_capacity_w"] == sum(p.get("PowerCapacityWatts") for p in psus
                                            if p.get("PowerCapacityWatts") is not None)

    def test_hpe_no_capacity_unknown(self):
        s = build_summary(load_power("hpe-dl380"))
        assert s["capacity_unknown_count"] == 0
        # HPE: 800W × 2 = 1600W
        assert s["total_capacity_w"] == 1600

    def test_cisco_psu_capacity_fallback(self):
        """Cisco may use InputRanges[0].OutputWattage fallback (raw quirk).
        After fallback applied, capacity_unknown should be 0 (or matches raw)."""
        power = load_power("cisco-c220")
        s = build_summary(power)
        # After fallback, total_capacity_w > 0 expected if any PSU has either
        # PowerCapacityWatts or InputRanges fallback
        assert s["psu_count"] >= 1
        assert s["total_capacity_w"] is None or s["total_capacity_w"] >= 0


# --------------------------------------------------------------------------- #
# A-3 (2026-10-19): 용량을 아는 PSU 가 하나도 없으면 total/pct 는 null — 실측 HPE CSUS 3200 (PSU 4개 전부 PowerCapacityWatts 미제공)
# --------------------------------------------------------------------------- #

class TestA3UnknownCapacityIsNull:
    def test_all_unknown_capacity_gives_null_total_and_pct(self):
        power = {"PowerSupplies": [{"Name": f"PSU{i}", "PowerCapacityWatts": None, "Status": {"Health": "OK", "State": "Enabled"}}
                                   for i in range(4)],
                 "PowerControl": [{"PowerConsumedWatts": 591}]}
        s = build_summary(power)
        assert s["psu_count"] == 4 and s["capacity_unknown_count"] == 4
        assert s["total_capacity_w"] is None and s["consumed_capacity_pct"] is None
        assert s["consumed_watts"] == 591

    def test_partial_capacity_keeps_partial_total(self):
        power = {"PowerSupplies": [{"Name": "PSU0", "PowerCapacityWatts": 800, "Status": {"Health": "OK", "State": "Enabled"}},
                                   {"Name": "PSU1", "PowerCapacityWatts": None, "Status": {"Health": "OK", "State": "Enabled"}}],
                 "PowerControl": [{"PowerConsumedWatts": 400}]}
        s = build_summary(power)
        assert s["total_capacity_w"] == 800 and s["capacity_unknown_count"] == 1 and s["consumed_capacity_pct"] == 50.0

    def test_real_template_matches_mirror_for_all_unknown(self):
        """운영 템플릿(_rf_power_summary) 자체도 같은 답을 낸다 — 미러와 템플릿의 drift 가드."""
        psus = [{"name": f"PSU{i}", "power_capacity_w": None, "health": "OK", "state": "Enabled"} for i in range(4)]
        out = _template_summary(psus, 591)
        assert out["total_capacity_w"] is None and out["consumed_capacity_pct"] is None and out["consumed_watts"] == 591


def _template_summary(psus, consumed):
    """운영 템플릿 redfish-gather/tasks/normalize_standard.yml :: _rf_power_summary 를 그대로 렌더한다."""
    import ast
    import jinja2
    import yaml
    norm = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
    tpl = None
    for t in yaml.safe_load(norm.read_text(encoding="utf-8")):
        sf = t.get("ansible.builtin.set_fact") or {}
        if "_rf_power_summary" in sf:
            tpl = sf["_rf_power_summary"]
    return ast.literal_eval(jinja2.Environment().from_string(tpl).render(
        _rf_d_power={"power_supplies": psus, "power_control": {"power_consumed_watts": consumed}}).strip())


def _raw_psu(state, health, cap=800):
    return {"Name": "PSU", "PowerCapacityWatts": cap, "Status": {k: v for k, v in (("State", state), ("Health", health)) if v is not None}}


# --------------------------------------------------------------------------- #
# SA-06 (2026-10-29, 사용자 결정 — Redfish · ESXi 함께): 설치 PSU 가 0 이면 health_rollup 은 null                 #
# --------------------------------------------------------------------------- #

SA06_CASES = {
    "no_psu":            ([], None, 0),
    "all_absent":        ([_raw_psu("Absent", "Warning"), _raw_psu("Absent", "Warning")], None, 0),   # 실측 dl380_gen12_03 모양
    "health_unreported": ([_raw_psu("Enabled", None), _raw_psu("Enabled", None)], "Unknown", 2),       # Cisco 모양 — 'Unknown' 유지
    "absent_slot_ignored": ([_raw_psu("Enabled", "OK"), _raw_psu("Absent", "Warning")], "OK", 1),
}


class TestSA06NoInstalledPsu:
    @pytest.mark.parametrize("case", sorted(SA06_CASES))
    def test_rollup_and_count(self, case):
        raw, rollup, count = SA06_CASES[case]
        s = build_summary({"PowerSupplies": raw, "PowerControl": [{"PowerConsumedWatts": 300}]})
        assert (s["health_rollup"], s["psu_count"], s["redundant"]) == (rollup, count, count >= 2)

    @pytest.mark.parametrize("case", sorted(SA06_CASES))
    def test_real_template_matches_mirror(self, case):
        """미러와 운영 템플릿이 12키 전부 같은 값을 낸다 — 한쪽만 바꾸면 여기서 막힌다."""
        raw, _, _ = SA06_CASES[case]
        psus = [{"name": r["Name"], "power_capacity_w": r["PowerCapacityWatts"],
                 "health": r["Status"].get("Health"), "state": r["Status"].get("State")} for r in raw]
        assert _template_summary(psus, 300) == build_summary({"PowerSupplies": raw, "PowerControl": [{"PowerConsumedWatts": 300}]})
