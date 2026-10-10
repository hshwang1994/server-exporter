"""prodgen evidence — host selection by channel (FL-F17), Harness verdict consistency (N3), required scenario sets (HC-02).

2026-10-10. The evidence collector decides promotion. Its host set must be the same set the pipeline accepted (seAcceptTargets /
inventory.sh: os · esxi = service_ip, redfish = bmc_ip, then ip), its Harness judgement must not trust the `verdict` field alone,
and every required scenario must exist in scenarios.json (the shared Harness job can only run what is defined)."""
from __future__ import annotations

import json
import pathlib

import pytest

from scripts.ai.prodgen import evidence as ev

REPO = pathlib.Path(__file__).resolve().parents[3]
CASES = json.loads((REPO / "tests" / "fixtures" / "input_validation" / "cases.json").read_text(encoding="utf-8"))["cases"]
PRIMARY = {"os": "service_ip", "esxi": "service_ip", "redfish": "bmc_ip"}
OTHER = {"os": "bmc_ip", "esxi": "bmc_ip", "redfish": "service_ip"}


def _inventory(case, channel):
    out = []
    for h in case["inventory"]:
        if not isinstance(h, dict):
            out.append(h)
            continue
        e = {}
        for k, v in h.items():
            e[PRIMARY[channel] if k == "PRIMARY" else (OTHER[channel] if k == "OTHER" else k)] = v
        out.append(e)
    return out


@pytest.mark.parametrize("channel", ["os", "esxi", "redfish"])
def test_hosts_from_inventory_follow_the_channel_primary_key_like_seaccepttargets(channel):
    """accept cases: the collector's host list equals the pipeline's accepted order; the other channel's key is ignored."""
    for case in CASES:
        if "accept" not in case:
            continue
        got = ev._hosts_from_inventory(json.dumps(_inventory(case, channel)), channel)
        assert got == case["accept"], (channel, case["name"], got)


def test_hosts_from_inventory_both_keys_present_picks_the_channel_key():
    inv = json.dumps([{"service_ip": "192.0.2.10", "bmc_ip": "192.0.2.20"}])
    assert ev._hosts_from_inventory(inv, "os") == ["192.0.2.10"]
    assert ev._hosts_from_inventory(inv, "esxi") == ["192.0.2.10"]
    assert ev._hosts_from_inventory(inv, "redfish") == ["192.0.2.20"]
    assert ev._hosts_from_inventory(inv, None) == ["192.0.2.10"], "unknown channel keeps the legacy order"


def test_evaluate_main_uses_the_build_target_type_for_the_host_set():
    """A redfish build whose inventory also carries service_ip: body_one_per_host must compare against the bmc_ip set."""
    item = {"params": {"inventory_json": json.dumps([{"service_ip": "192.0.2.10", "bmc_ip": "192.0.2.20"}]), "target_type": "redfish",
                       "callbackUrl": "http://10.0.0.5/api", "loc": "git"}, "result": "SUCCESS", "building": False}
    body = {"gatherInfoJson": [dict.fromkeys(ev.ENVELOPE_KEYS, None) | {"ip": "192.0.2.20", "status": "success", "data": {"x": 1}}]}
    summary = {"outcome": "completed", "accepted": 1, "lines": 1, "filled": 0, "callback": {"delivered": True, "http_code": 200, "attempts": 1}}
    checks = {c["name"]: c for c in ev.evaluate_main("E2E-E", item, summary, body, None, "[Portal 전송] HTTP 200")}
    assert checks["hosts_given"]["observed"] == ["192.0.2.20"]
    assert checks["body_one_per_host"]["ok"] and checks["accepted_eq_hosts"]["ok"]


def _hr(verdict="PASS", checks=None, partial=None, problems=None):
    return {"scenario": "normal_success", "verdict": verdict, "checks": checks if checks is not None else [{"name": "delivered", "ok": True}],
            "partial": partial or [], "problems": problems or [], "meta": {"functions_sha256": "f" * 64}}


def _item():
    return {"params": {"SCENARIO": "normal_success", "FUNCTIONS_SRC": "checkout"}, "result": "SUCCESS", "building": False}


def _ctl():
    return {"functions_source": "checkout", "source_sha256": "s" * 64}


def test_harness_verdict_pass_must_agree_with_its_own_checks_partial_and_problems():
    ok = ev.evaluate_harness("normal_success", _item(), _hr(), _ctl(), "SUCCESS")
    assert all(c["ok"] for c in ok), [c for c in ok if not c["ok"]]
    # a hand-edited PASS over a failed check
    bad = {c["name"]: c for c in ev.evaluate_harness("normal_success", _item(), _hr(checks=[{"name": "delivered", "ok": False}]), _ctl(), "SUCCESS")}
    assert bad["verdict"]["ok"] and not bad["verdict_consistent"]["ok"]
    # PASS while the Harness recorded missing inputs (PARTIAL would be the honest verdict)
    bad = {c["name"]: c for c in ev.evaluate_harness("normal_success", _item(), _hr(partial=["sink not reached"]), _ctl(), "SUCCESS")}
    assert not bad["verdict_consistent"]["ok"]
    # PASS without any recorded checks is not evidence
    bad = {c["name"]: c for c in ev.evaluate_harness("normal_success", _item(), {"scenario": "normal_success", "verdict": "PASS", "meta": {"functions_sha256": "f" * 64}}, _ctl(), "SUCCESS")}
    assert not bad["verdict_consistent"]["ok"]
    # a FAIL verdict is simply a failed `verdict` check (no consistency claim is made about it)
    fail = {c["name"]: c for c in ev.evaluate_harness("normal_success", _item(), _hr(verdict="FAIL", checks=[{"name": "delivered", "ok": False}]), _ctl(), "SUCCESS")}
    assert not fail["verdict"]["ok"] and "verdict_consistent" not in fail


def test_required_sets_exist_in_scenarios_json_and_include_the_callback_close_path():
    names = set(ev.harness_expected_results())
    assert names, "scenarios.json unreadable"
    assert set(ev.REQUIRED_HARNESS) <= names and set(ev.REQUIRED_HARNESS_TREE) <= names
    assert "sink_close" in ev.REQUIRED_HARNESS, "HC-02: the Callback connection-close path is required evidence"
    assert set(ev.REQUIRED_HARNESS_TREE) <= set(ev.REQUIRED_HARNESS)
    assert names - set(ev.REQUIRED_HARNESS) == {"sink_hold"}, "every judged scenario is required; sink_hold is the auxiliary sink holder"
