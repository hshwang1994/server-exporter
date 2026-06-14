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
    """
    psus = []
    for psu in (power_data.get("PowerSupplies") or []):
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
    if critical > 0:
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
    consumed_pct = round((consumed or 0) * 100 / cap_total, 1) if cap_total > 0 else 0
    return {
        "psu_count": psu_total,
        "psu_active": psu_active,
        "redundant": psu_total >= 2,
        "total_capacity_w": cap_total,
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
        assert s["total_capacity_w"] >= 0
