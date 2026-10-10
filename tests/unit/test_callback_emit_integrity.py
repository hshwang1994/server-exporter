"""json_only — OUTPUT 기록 무결성 (2026-10-10 FL-F02 · FL-F05).

실측(2026-10-10, Runner01~04 ansible-core 2.20.3): raw 출력의 비 UTF-8 바이트가 lone surrogate 로 들어오면 json_only 의 콜백 dispatch 가
"'utf-8' codec can't encode characters ... surrogates not allowed" 로 실패해 그 host 의 OUTPUT 이 사라지고, on_stats 가 OUTPUT_BUILD_FAILED
합성 envelope 을 썼다(수집은 성공했는데 결과만 잃었다). 또 쓰기 실패 뒤에도 `emitted` 를 남겨 gather_state 가 "확정 결과가 사라졌다"(재개 불가)
로 끝냈다. 여기서 고정하는 것:
  - lone surrogate → U+FFFD, NaN/Infinity → null, 고친 사실은 diagnosis.details.notices 에 남는다 (13 필드 밖 새 키 없음)
  - 결과 파일에 쓰지 못했거나 13 필드 envelope 이 아니면 emitted 가 아니라 emit_failed 사건이다
  - 결과 파일 줄은 언제나 엄격한 UTF-8 · RFC 8259 JSON 이다 (Layer A 의 parse_constant 거부 · Groovy JsonSlurper 와 호환)
Ansible 은 실행하지 않고 콜백 인터페이스만 대역으로 구동한다.
"""
from __future__ import annotations

import json
import math
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "callback_plugins"))

try:                                          # ansible 이 있으면 실물 기반 클래스를 쓴다
    import ansible.plugins.callback  # noqa: F401
except ImportError:                           # 없으면 최소 대역 (콜백 계약만 검증하면 된다)
    _cb = types.ModuleType("ansible.plugins.callback")

    class _CallbackBase:                      # noqa: D401 - CallbackBase 대역
        def __init__(self, *_a, **_k):
            pass

    _cb.CallbackBase = _CallbackBase
    _plugins = sys.modules.setdefault("ansible.plugins", types.ModuleType("ansible.plugins"))
    _plugins.callback = _cb
    sys.modules.setdefault("ansible", types.ModuleType("ansible")).plugins = _plugins
    sys.modules["ansible.plugins.callback"] = _cb

import json_only  # noqa: E402

ENVELOPE_KEYS = ("schema_version", "target_type", "collection_method", "ip", "hostname", "vendor", "status",
                 "sections", "diagnosis", "meta", "correlation", "errors", "data")
ALL = ["system", "hardware", "bmc", "cpu", "memory", "storage", "network", "firmware", "users", "power", "thermal"]
SURR = "A\udcff\udcfeB"   # 2026-10-10 Runner 실측과 같은 lone surrogate 2개


class _Host:
    def __init__(self, name):
        self.name = name

    def get_name(self):
        return self.name

    def get_vars(self):
        return {"ansible_host": self.name}


class _Task:
    def __init__(self, name):
        self.name = name


class _Result:
    def __init__(self, host, task_name, result, action="ansible.builtin.debug"):
        self.host = host
        self.task = _Task(task_name)
        self.result = dict(result)
        self.task_fields = {"name": task_name, "action": action, "delegate_to": None, "connection": "smart",
                            "ignore_unreachable": None, "no_log": None}

    _host = property(lambda self: self.host)
    _task = property(lambda self: self.task)
    _result = property(lambda self: self.result)
    _task_fields = property(lambda self: self.task_fields)


class _Stats:
    def __init__(self, hosts):
        self.processed = {h: 1 for h in hosts}


def _envelope(ip, **data):
    return {"schema_version": "1", "target_type": "os", "collection_method": "agent", "ip": ip, "hostname": "h", "vendor": None,
            "status": "success", "sections": {s: "success" for s in ALL},
            "diagnosis": {"reachable": True, "port_open": True, "protocol_supported": True, "auth_success": True,
                          "failure_stage": None, "failure_code": None, "failure_reason": None, "details": {"channel": "os"}},
            "meta": {}, "correlation": {"host_ip": ip}, "errors": [], "data": dict(data)}


def _callback(monkeypatch, tmp_path, output_file=None):
    out = tmp_path / "gather_output.json" if output_file is None else output_file
    monkeypatch.setenv("ANSIBLE_JSON_OUTPUT_FILE", str(out))
    monkeypatch.setenv("ANSIBLE_JSON_PROGRESS_FILE", str(tmp_path / "gather_progress.jsonl"))
    monkeypatch.setenv("ANSIBLE_JSON_CHECKPOINT_FILE", str(tmp_path / "gather_checkpoint.jsonl"))
    monkeypatch.delenv("JSON_ONLY_NO_RECONCILE", raising=False)
    return json_only.CallbackModule(), out


def _progress_events(tmp_path):
    p = tmp_path / "gather_progress.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ── _sanitize ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_sanitize_replaces_lone_surrogates_and_non_finite_numbers_and_records_what_it_did():
    stats = {}
    out = json_only._sanitize({"a": SURR, "b": [1.5, float("nan"), float("inf")], "c": {"d": -float("inf"), "e": "ok"}}, stats)
    assert out["a"] == "A��B" and out["b"] == [1.5, None, None] and out["c"] == {"d": None, "e": "ok"}
    assert stats["surrogates"] == 2 and stats["non_finite"] == ["b[1]", "b[2]", "c.d"]
    json.dumps(out, ensure_ascii=False, allow_nan=False).encode("utf-8")        # 엄격한 UTF-8 · RFC 8259


def test_sanitize_leaves_clean_values_untouched():
    stats = {}
    src = {"k": "한글 ✓", "n": 1, "f": 2.5, "l": [None, True]}
    assert json_only._sanitize(src, stats) == src and stats == {}


# ── _emit ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_emit_writes_strict_utf8_json_and_notes_the_sanitising_in_details(monkeypatch, tmp_path, capsys):
    cb, out = _callback(monkeypatch, tmp_path)
    env = _envelope("10.0.0.1", system={"model": SURR, "temp": float("nan")})
    assert cb._emit(env) is True
    raw = out.read_bytes()
    raw.decode("utf-8")                                   # 쓰기 성공 + 유효한 UTF-8
    line = json.loads(raw.decode("utf-8").strip(), parse_constant=lambda n: (_ for _ in ()).throw(ValueError(n)))
    assert line["data"]["system"] == {"model": "A��B", "temp": None}
    notices = line["diagnosis"]["details"]["notices"]
    assert any("non-UTF-8" in n and "2 chars" in n for n in notices) and any("non-finite" in n and "data.system.temp" in n for n in notices)
    assert set(line) == set(ENVELOPE_KEYS), "새 top-level 키 없음"
    stdout_line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert stdout_line == line, "stdout 과 파일이 같은 줄"


def test_emit_returns_false_when_the_output_file_cannot_be_written(monkeypatch, tmp_path, capsys):
    cb, _ = _callback(monkeypatch, tmp_path, output_file=tmp_path / "missing-dir" / "gather_output.json")
    assert cb._emit(_envelope("10.0.0.2")) is False
    assert "OUTPUT 파일 쓰기 실패" in capsys.readouterr().err


# ── OUTPUT 태스크 → emitted / emit_failed ──────────────────────────────────────────────────────────────────────

def test_output_with_surrogates_is_recorded_and_counted_as_emitted(monkeypatch, tmp_path, capsys):
    cb, out = _callback(monkeypatch, tmp_path)
    host = _Host("10.0.0.3")
    cb.v2_runner_on_ok(_Result(host, "OUTPUT", {"msg": _envelope("10.0.0.3", system={"serial": SURR})}))
    events = [e["event"] for e in _progress_events(tmp_path)]
    assert "emitted" in events and "emit_failed" not in events
    assert json.loads(out.read_text(encoding="utf-8").splitlines()[0])["data"]["system"]["serial"] == "A��B"
    cb.v2_playbook_on_stats(_Stats(["10.0.0.3"]))
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1, "보충 없음 — 이미 낸 host"


def test_output_write_failure_is_emit_failed_not_emitted_and_stats_fills_from_checkpoint(monkeypatch, tmp_path, capsys):
    """결과 파일에 못 썼으면 emitted 가 아니다. 플레이북 끝에 CHECKPOINT 조립본으로 보충을 시도한다(그 쓰기도 같은 파일이라 실패하면 경고)."""
    bad = tmp_path / "missing-dir" / "gather_output.json"
    cb, _ = _callback(monkeypatch, tmp_path, output_file=bad)
    host = _Host("10.0.0.4")
    cb.v2_runner_on_ok(_Result(host, "CHECKPOINT", {"msg": _envelope("10.0.0.4", system={"model": "cp"})}))
    cb.v2_runner_on_ok(_Result(host, "OUTPUT", {"msg": _envelope("10.0.0.4", system={"model": "final"})}))
    events = _progress_events(tmp_path)
    kinds = [e["event"] for e in events]
    assert "emit_failed" in kinds and "emitted" not in kinds
    assert [e for e in events if e["event"] == "emit_failed"][0]["detail"] == "write"
    assert cb._hosts["10.0.0.4"]["emitted"] is False
    bad.parent.mkdir()                                     # 파일을 쓸 수 있게 되면 보충은 checkpoint 조립본으로
    cb.v2_playbook_on_stats(_Stats(["10.0.0.4"]))
    lines = [json.loads(l) for l in bad.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["data"]["system"]["model"] == "cp"
    assert lines[0]["errors"][-1]["detail"].startswith("finalized from checkpoint")
    assert [e for e in _progress_events(tmp_path) if e["event"] == "reconciled"][0]["source"] == "checkpoint"


def test_output_that_is_not_a_13_field_envelope_is_emit_failed_shape(monkeypatch, tmp_path, capsys):
    cb, out = _callback(monkeypatch, tmp_path)
    host = _Host("10.0.0.5")
    cb.v2_runner_on_ok(_Result(host, "OUTPUT", {"msg": {"foo": 1}}))
    events = _progress_events(tmp_path)
    assert [e for e in events if e["event"] == "emit_failed"][0]["detail"] == "shape"
    assert "emitted" not in [e["event"] for e in events]
    cb.v2_playbook_on_stats(_Stats(["10.0.0.5"]))
    lines = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert lines[0] == {"foo": 1} and set(lines[1]) == set(ENVELOPE_KEYS) and lines[1]["ip"] == "10.0.0.5"


def test_checkpoint_line_is_sanitised_too(monkeypatch, tmp_path, capsys):
    cb, _ = _callback(monkeypatch, tmp_path)
    cb.v2_runner_on_ok(_Result(_Host("10.0.0.6"), "CHECKPOINT", {"msg": _envelope("10.0.0.6", system={"model": SURR})}))
    cp = (tmp_path / "gather_checkpoint.jsonl").read_text(encoding="utf-8")
    assert json.loads(cp.splitlines()[0])["data"]["system"]["model"] == "A��B"


def test_progress_detail_with_surrogates_does_not_lose_the_event(monkeypatch, tmp_path):
    cb, _ = _callback(monkeypatch, tmp_path)
    cb._progress("10.0.0.7", "lost", task="t", detail=SURR)
    ev = _progress_events(tmp_path)
    assert ev and ev[-1]["event"] == "lost" and ev[-1]["detail"] == "A��B"
