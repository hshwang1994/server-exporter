"""json_only — 2026-10-03 Phase 4 D4: 진행 이벤트(progress JSONL) · CHECKPOINT 캡처 · manifest 대조.

강제 종료 뒤에는 `on_stats` 보충이 돌지 않으므로(2026-10-03 WSL 실측), 콜백은 host 전이를 파일 이벤트로 남기고
Layer A(scripts/finalize_gather_output.py)가 그것으로 누락 envelope 을 보충한다. Ansible 은 실행하지 않고 콜백 인터페이스만 대역으로 구동한다.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "callback_plugins"))

try:
    import ansible.plugins.callback  # noqa: F401
except ImportError:
    _cb = types.ModuleType("ansible.plugins.callback")
    _cb.CallbackBase = type("CallbackBase", (), {"__init__": lambda self, *a, **k: None})
    _plugins = sys.modules.setdefault("ansible.plugins", types.ModuleType("ansible.plugins"))
    _plugins.callback = _cb
    sys.modules.setdefault("ansible", types.ModuleType("ansible")).plugins = _plugins
    sys.modules["ansible.plugins.callback"] = _cb

import json_only  # noqa: E402


class _Host:
    def __init__(self, name, host_vars=None):
        self.name = name
        self._vars = dict(host_vars or {})

    def get_name(self):
        return self.name

    def get_vars(self):
        return dict(self._vars)


class _Task:
    def __init__(self, name):
        self.name = name


class _Result:
    def __init__(self, host, task_name, action="ansible.builtin.set_fact", result=None, **fields):
        self.host = host
        self.task = _Task(task_name)
        self.result = dict(result or {})
        self.task_fields = {"name": task_name, "action": action, "delegate_to": None,
                            "connection": "smart", "ignore_unreachable": None, "no_log": None}
        self.task_fields.update(fields)

    _host = property(lambda self: self.host)
    _task = property(lambda self: self.task)
    _result = property(lambda self: self.result)
    _task_fields = property(lambda self: self.task_fields)


class _Inventory:
    def __init__(self, names):
        self._names = names

    def get_hosts(self, pattern):
        return [_Host(n) for n in self._names]


class _VM:
    def __init__(self, names):
        self._inventory = _Inventory(names)


class _Play:
    def __init__(self, names, name="os-gather | linux"):
        self._vm = _VM(names)
        self._name = name

    def get_variable_manager(self):
        return self._vm

    def get_name(self):
        return self._name


def _envelope(ip):
    return {"schema_version": "1", "target_type": "os", "collection_method": "agent", "ip": ip, "hostname": "h",
            "vendor": None, "status": "success", "sections": {}, "diagnosis": {}, "meta": {}, "correlation": {},
            "errors": [], "data": {}}


@pytest.fixture
def cb(tmp_path, monkeypatch):
    monkeypatch.setenv("ANSIBLE_JSON_OUTPUT_FILE", str(tmp_path / "gather_output.json"))
    monkeypatch.setenv("ANSIBLE_JSON_PROGRESS_FILE", str(tmp_path / "gather_progress.jsonl"))
    monkeypatch.setenv("ANSIBLE_JSON_CHECKPOINT_FILE", str(tmp_path / "gather_checkpoint.jsonl"))
    monkeypatch.setenv("ANSIBLE_JSON_MANIFEST_FILE", str(tmp_path / "gather_manifest.json"))
    (tmp_path / "gather_manifest.json").write_text(json.dumps({"schema": 1, "channel": "os", "ips": ["10.0.0.1", "10.0.0.2"]}), encoding="utf-8")
    c = json_only.CallbackModule()
    c._playbook_channel = "os"
    return c


def _events(tmp_path):
    p = tmp_path / "gather_progress.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.is_file() else []


def test_host_lifecycle_events_are_appended_in_order(cb, tmp_path, capsys):
    h = _Host("10.0.0.1", {"ansible_host": "10.0.0.1"})
    diag = {"reachable": True, "port_open": True, "protocol_supported": True, "auth_success": None,
            "failure_stage": None, "failure_code": None, "failure_reason": None, "details": {"channel": "os"}}
    cb.v2_runner_on_ok(_Result(h, "precheck | set diagnosis", result={"ansible_facts": {"_diagnosis": diag, "_cred_location": "git", "_cred_load_outcome": "ok"}}))
    cb.v2_runner_on_ok(_Result(h, "linux | preflight", action="ansible.builtin.raw", result={"rc": 0}))
    cb.v2_runner_on_ok(_Result(h, "CHECKPOINT", action="ansible.builtin.debug", result={"msg": json.dumps(_envelope("10.0.0.1"))}))
    cb.v2_runner_on_ok(_Result(h, "ADDON_START", result={"ansible_facts": {"_addon_marker": "started"}}))
    cb.v2_runner_on_ok(_Result(h, "ADDON_DONE", result={"ansible_facts": {"_addon_marker": "done"}}))
    cb.v2_runner_on_ok(_Result(h, "OUTPUT", action="ansible.builtin.debug", result={"msg": json.dumps(_envelope("10.0.0.1"))}))
    ev = _events(tmp_path)
    # 2026-10-05 (8차 R3): 정체 감시와 그 진행 신호(alive)는 없앴다 — 작업 태스크 성공은 진행 이벤트를 남기지 않는다
    assert [e["event"] for e in ev] == ["first_seen", "precheck", "cred_load", "auth_proven", "checkpoint", "addon_started",
                                        "addon_done", "emitted"]
    assert ev[1]["diagnosis"] == diag and ev[2]["outcome"] == "ok" and ev[2]["location"] == "git"
    assert ev[3]["task"] == "linux | preflight" and all(e["host"] == "10.0.0.1" for e in ev)
    assert all(e["ip"] == "10.0.0.1" for e in ev), "first_seen 을 포함한 모든 줄에 ip 가 실린다 (Phase 5 실측 뒤 정정)"
    assert all(len(json.dumps(e, ensure_ascii=False)) <= 200 for e in ev if e["event"] != "precheck"), "precheck 외 줄은 200B 이하"
    # CHECKPOINT 는 stdout 으로 나가지 않고 파일에만 남는다
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and json.loads(out[0])["ip"] == "10.0.0.1", "stdout 에는 OUTPUT 만"
    cp = (tmp_path / "gather_checkpoint.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(cp) == 1 and json.loads(cp[0]) == _envelope("10.0.0.1")
    assert (tmp_path / "gather_output.json").read_text(encoding="utf-8").count("\n") == 1


def test_lost_event_carries_truncated_detail(cb, tmp_path):
    h = _Host("10.0.0.2", {"ansible_host": "10.0.0.2"})
    cb.v2_runner_on_unreachable(_Result(h, "linux | preflight", action="ansible.builtin.raw",
                                        result={"msg": "Failed to connect to the host via ssh: " + "x" * 500}))
    ev = _events(tmp_path)
    assert [e["event"] for e in ev] == ["first_seen", "lost"]
    assert ev[1]["detail"].startswith("Failed to connect") and len(ev[1]["detail"]) == 160


def test_ignore_unreachable_probe_does_not_mark_lost(cb, tmp_path):
    h = _Host("10.0.0.2", {"ansible_host": "10.0.0.2"})
    cb.v2_runner_on_unreachable(_Result(h, "probe", action="ansible.builtin.raw", result={"msg": "auth"}, ignore_unreachable=True))
    assert [e["event"] for e in _events(tmp_path)] == ["first_seen"]


def test_play_start_records_inventory_and_warns_on_manifest_mismatch(cb, tmp_path, capsys):
    cb.v2_playbook_on_play_start(_Play(["10.0.0.1", "10.0.0.2"]))
    ev = _events(tmp_path)
    assert ev[-1]["event"] == "inventory" and ev[-1]["hosts"] == ["10.0.0.1", "10.0.0.2"] and ev[-1]["host"] is None
    assert "접수 manifest" not in capsys.readouterr().err
    cb.v2_playbook_on_play_start(_Play(["10.0.0.1"]))
    err = capsys.readouterr().err
    assert "inventory 와 접수 manifest 가 다르다" in err and "10.0.0.2" in err


def test_without_env_vars_nothing_is_written_and_nothing_breaks(tmp_path, monkeypatch):
    for var in ("ANSIBLE_JSON_PROGRESS_FILE", "ANSIBLE_JSON_CHECKPOINT_FILE", "ANSIBLE_JSON_MANIFEST_FILE", "ANSIBLE_JSON_OUTPUT_FILE"):
        monkeypatch.delenv(var, raising=False)
    c = json_only.CallbackModule()
    h = _Host("10.0.0.3", {"ansible_host": "10.0.0.3"})
    c.v2_runner_on_ok(_Result(h, "CHECKPOINT", action="ansible.builtin.debug", result={"msg": json.dumps(_envelope("10.0.0.3"))}))
    c.v2_runner_on_ok(_Result(h, "OUTPUT", action="ansible.builtin.debug", result={"msg": json.dumps(_envelope("10.0.0.3"))}))
    c.v2_playbook_on_play_start(_Play(["10.0.0.3"]))
    assert not list(tmp_path.iterdir()), "환경변수가 없으면 파일을 만들지 않는다 (종전 동작)"


def test_unwritable_progress_path_only_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANSIBLE_JSON_PROGRESS_FILE", str(tmp_path / "no" / "such" / "dir" / "p.jsonl"))
    monkeypatch.delenv("ANSIBLE_JSON_CHECKPOINT_FILE", raising=False)
    monkeypatch.delenv("ANSIBLE_JSON_MANIFEST_FILE", raising=False)
    monkeypatch.delenv("ANSIBLE_JSON_OUTPUT_FILE", raising=False)
    c = json_only.CallbackModule()
    c.v2_runner_on_ok(_Result(_Host("10.0.0.4"), "x", action="ansible.builtin.raw", result={"rc": 0}))
    assert "progress 기록 실패" in capsys.readouterr().err


# ── 2026-10-05 (8차 R3): 정체 감시가 없어져 진행 신호(alive)도 없다 ──────────────────────────────────────────
def test_work_tasks_leave_no_alive_events(cb, tmp_path):
    """종전에는 작업 태스크 성공마다(host 당 10 s 에 1번) alive 를 남겨 정체 감시가 읽었다. 감시가 없어져 진행 기록에 남기지 않는다 —
    진행 기록은 결과 복원용 전이 이벤트(first_seen · precheck · cred_load · auth_proven · checkpoint · addon_* · emitted · lost)뿐이다."""
    h = _Host("10.0.0.9", {"ansible_host": "10.0.0.9"})
    cb.v2_runner_on_ok(_Result(h, "linux | cpu", action="ansible.builtin.shell", result={"rc": 0}))
    cb.v2_runner_on_ok(_Result(h, "redfish | try_account | attempt", action="redfish_gather", result={"status": "success"}))
    assert "alive" not in [e["event"] for e in _events(tmp_path)]
    assert not hasattr(json_only, "_ALIVE_EVERY_SEC") and not hasattr(cb, "_alive_at") and not hasattr(cb, "_alive")

