"""scripts/gather_state.py ↔ json_only `emit_failed` (2026-10-10 FL-F02).

json_only now records `emit_failed` (not `emitted`) when the OUTPUT line could not be written or is not a 13-field envelope.
gather_state must treat such a host as unfinished (re-collected on resume) and must not count it as a confirmed result whose line
vanished (which ended the build as resume_impossible, rc 92)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("gather_state_ef", REPO / "scripts" / "gather_state.py")
gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gs)

T0 = 1_800_000_000
PROBES = {"boot_id": "boot-a", "btime": T0 - 86400, "kernel_mark": 1000.0, "kernel": {"readable": True, "kills": []},
          "oom": {"vmstat": 0, "cgroup": 0, "cgroup_path": "/cg"}}
ALL = ["system", "hardware", "bmc", "cpu", "memory", "storage", "network", "firmware", "users", "power", "thermal"]


def _env(ip):
    return {"schema_version": "1", "target_type": "os", "collection_method": "agent", "ip": ip, "hostname": "h", "vendor": None,
            "status": "success", "sections": {s: "success" for s in ALL},
            "diagnosis": {"reachable": None, "port_open": None, "protocol_supported": None, "auth_success": None,
                          "failure_stage": None, "failure_code": None, "failure_reason": None, "details": {}},
            "meta": {}, "correlation": {}, "errors": [], "data": {}}


def _ev(ip, event, **extra):
    return {"ts": "2026-10-10T00:00:00+00:00", "host": ip, "ip": ip, "event": event, "task": "OUTPUT", "detail": None} | extra


def _ws(tmp_path, ips, outputs, progress):
    (tmp_path / "gather_manifest.json").write_text(json.dumps({"schema": 1, "build": {"job": "j", "number": "7"}, "channel": "os", "ips": ips}), encoding="utf-8")
    (tmp_path / "gather_output.json").write_text("".join(json.dumps(o) + "\n" for o in outputs), encoding="utf-8")
    (tmp_path / "gather_progress.jsonl").write_text("".join(json.dumps(e) + "\n" for e in progress), encoding="utf-8")
    return tmp_path


def _begin(ws, now):
    return gs.begin(ws, pid=1, vault_tmp="", cp_dir="", gather_max=21600, vcpu=8, os_cap=None, prev_agent_lost=True, now=now, probes=PROBES)


def test_emit_failed_host_is_pending_not_lost(tmp_path):
    """attempt 1: host A emitted (line present), host B emit_failed (no line) and the attempt vanished without an end record."""
    ws = _ws(tmp_path, ["192.0.2.1", "192.0.2.2"], outputs=[_env("192.0.2.1")],
             progress=[_ev("192.0.2.1", "emitted"), _ev("192.0.2.2", "emit_failed", detail="write")])
    first = _begin(ws, T0)
    assert first["attempt"] == 1 and first["state"] is None   # the recorded attempt is left open on purpose
    plan = _begin(ws, T0 + 120)
    assert plan["attempt"] == 2 and plan["state"] is None and plan["lost"] == 0, plan
    assert plan["pending"] == 1 and plan["completed"] == 1
    assert (ws / ".gather_limit_hosts").read_text(encoding="utf-8").split() == ["192.0.2.2"]


def test_emitted_without_a_line_is_still_resume_impossible(tmp_path):
    """the contract the fix relies on: `emitted` means the line was written — if it is gone, the resume is refused (10차 R3)."""
    ws = _ws(tmp_path, ["192.0.2.1"], outputs=[], progress=[_ev("192.0.2.1", "emitted")])
    _begin(ws, T0)
    plan = _begin(ws, T0 + 120)
    assert plan["state"] == "resume_impossible" and plan["lost"] == 1
