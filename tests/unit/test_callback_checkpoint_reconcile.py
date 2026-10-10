"""F01 (2026-10-05): 플레이북 종료 보충이 CHECKPOINT 로 이미 수집한 값을 가리지 않는다.

배경
----
`json_only` 는 OUTPUT 을 내지 못한 host 를 `v2_playbook_on_stats` 에서 보충한다. 종전에는 그 보충이 CHECKPOINT
(Add-on 전 조립본)를 보지 않고 기본 실패 envelope 을 OUTPUT 파일에 썼다. Layer A/B 는 OUTPUT 줄을 CHECKPOINT 보다
우선하므로, CHECKPOINT 에 있던 `memory.installed_mb=4096` 같은 값이 최종 결과에서 `memory=null` · `OUTPUT_BUILD_FAILED`
로 사라졌다 (Astra 검토의 합성 재현).

고정하는 것
  - CHECKPOINT 뒤 OUTPUT 태스크 실패 → 보충 envelope 은 CHECKPOINT 값 + 오류 1건(Layer A 와 같은 문장)
  - Add-on 이 시작만 되고 끝나지 않음 → addon 오류 1건
  - 정상 host 와 섞여도 정상 host 는 그대로, 중복 없음
  - 진짜 최종 failed OUTPUT(rescue 경로가 낸 것)은 덮지 않는다
  - CHECKPOINT 가 없으면 종전 관측 기반 보충 그대로
  - 콜백 → Layer A 를 실제 파일로 이어 붙인 결과에서도 값이 남는다 (직렬화 실패 포함)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.unit.test_callback_envelope_reconcile import (  # noqa: E402 - 콜백 대역과 Driver 재사용
    Driver,
    _Result,
    _assert_envelope_contract,
    _success_envelope,
    json_only,
)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import finalize_gather_output as fz  # noqa: E402


def _with_memory(ip):
    env = _success_envelope(ip)
    env["data"] = {"cpu": {}, "memory": {"installed_mb": 4096, "slots": [{"locator": "DIMM0", "size_mb": 4096}]}}
    return env


def _checkpoint(d, ip, env):
    d.cb.v2_runner_on_ok(_Result(d.hosts[ip], "CHECKPOINT", action="ansible.builtin.debug",
                                 result={"msg": json.dumps(env, ensure_ascii=False)}))


def _output_task_failed(d, ip):
    d.cb.v2_runner_on_failed(_Result(d.hosts[ip], "OUTPUT", action="ansible.builtin.debug",
                                     result={"msg": "template error while templating string"}))


def _marker(d, ip, name):
    d.cb.v2_runner_on_ok(_Result(d.hosts[ip], name, result={"ansible_facts": {"_addon_phase": "x"}}))


def _until_checkpoint(d, ip, env):
    d.precheck(ip)
    d.credentials(ip)
    d.classify(ip)
    d.credential_probe(ip)
    d.remote_task(ip)
    _checkpoint(d, ip, env)


def test_output_task_failure_after_checkpoint_keeps_collected_data(capsys):
    d = Driver(capsys)
    _until_checkpoint(d, "10.0.0.1", _with_memory("10.0.0.1"))
    _output_task_failed(d, "10.0.0.1")
    out = d.finish()
    assert len(out) == 1
    env = out[0]
    _assert_envelope_contract(env, "checkpoint-reconciled")
    assert env["status"] == "success", "CHECKPOINT 의 status 를 그대로 둔다"
    assert env["data"]["memory"]["installed_mb"] == 4096, "이미 수집한 값이 남아야 한다"
    assert env["errors"][-1] == {
        "section": "gather", "message": json_only._CHECKPOINT_EMIT_FAILED,
        "detail": "finalized from checkpoint; reconciled by callback at playbook end; OUTPUT was not emitted after assembly"}
    assert env["diagnosis"]["failure_code"] is None, "진단은 CHECKPOINT 값 그대로 (새 실패 코드를 만들지 않는다)"


def test_addon_started_but_not_done_is_reported_as_addon(capsys):
    d = Driver(capsys)
    _until_checkpoint(d, "10.0.0.1", _with_memory("10.0.0.1"))
    _marker(d, "10.0.0.1", "ADDON_START")
    out = d.finish()
    assert out[0]["errors"][-1]["section"] == "addon"
    assert out[0]["errors"][-1]["message"] == json_only._CHECKPOINT_ADDON_INTERRUPTED
    assert out[0]["data"]["memory"]["installed_mb"] == 4096


def test_addon_done_then_output_failure_is_emit_failed(capsys):
    d = Driver(capsys)
    _until_checkpoint(d, "10.0.0.1", _with_memory("10.0.0.1"))
    _marker(d, "10.0.0.1", "ADDON_START")
    _marker(d, "10.0.0.1", "ADDON_DONE")
    _output_task_failed(d, "10.0.0.1")
    out = d.finish()
    assert out[0]["errors"][-1]["section"] == "gather"
    assert out[0]["errors"][-1]["message"] == json_only._CHECKPOINT_EMIT_FAILED


def test_mixed_with_a_normal_host_no_duplicate(capsys):
    d = Driver(capsys)
    _until_checkpoint(d, "10.0.0.1", _with_memory("10.0.0.1"))
    d.output("10.0.0.1", _success_envelope("10.0.0.1"))
    _until_checkpoint(d, "10.0.0.2", _with_memory("10.0.0.2"))
    _output_task_failed(d, "10.0.0.2")
    out = d.finish()
    assert [e["ip"] for e in out] == ["10.0.0.1", "10.0.0.2"], "정상 host 는 1번만, 보충 host 도 1번만"
    assert out[0] == _success_envelope("10.0.0.1"), "정상 OUTPUT 은 손대지 않는다"
    assert out[1]["data"]["memory"]["installed_mb"] == 4096


def test_real_final_failed_output_is_not_replaced(capsys):
    """rescue 경로가 낸 진짜 최종 failed OUTPUT 은 이미 emitted — CHECKPOINT 로 덮지 않는다."""
    d = Driver(capsys)
    _until_checkpoint(d, "10.0.0.1", _with_memory("10.0.0.1"))
    failed = _success_envelope("10.0.0.1") | {"status": "failed"}
    d.output("10.0.0.1", failed)
    out = d.finish()
    assert out == [failed]


def test_without_checkpoint_the_observed_fallback_is_unchanged(capsys):
    d = Driver(capsys)
    d.precheck("10.0.0.1")
    d.credentials("10.0.0.1")
    d.classify("10.0.0.1")
    d.credential_probe("10.0.0.1")
    _output_task_failed(d, "10.0.0.1")
    out = d.finish()
    assert out[0]["status"] == "failed"
    assert out[0]["diagnosis"]["failure_code"] == "OUTPUT_BUILD_FAILED"
    assert "finalized from checkpoint" not in out[0]["errors"][-1]["detail"]


def test_reconcile_switch_off_keeps_no_checkpoint_state(capsys, monkeypatch):
    monkeypatch.setenv("JSON_ONLY_NO_RECONCILE", "1")
    d = Driver(capsys)
    d.precheck("10.0.0.1")
    _checkpoint(d, "10.0.0.1", _with_memory("10.0.0.1"))
    assert all("checkpoint_env" not in (ctx or {}) for ctx in d.cb._hosts.values())


def test_checkpoint_sentences_match_layer_a():
    assert json_only._CHECKPOINT_EMIT_FAILED == fz.EMIT_FAILED
    assert json_only._CHECKPOINT_ADDON_INTERRUPTED == fz.ADDON_INTERRUPTED


# ── 콜백 → Layer A 를 실제 파일로 이어 붙인다 ───────────────────────────────────────

def _files(monkeypatch, ws):
    monkeypatch.setenv("ANSIBLE_JSON_OUTPUT_FILE", str(ws / "gather_output.json"))
    monkeypatch.setenv("ANSIBLE_JSON_CHECKPOINT_FILE", str(ws / "gather_checkpoint.jsonl"))
    monkeypatch.setenv("ANSIBLE_JSON_PROGRESS_FILE", str(ws / "gather_progress.jsonl"))


def _layer_a(ws, ips):
    (ws / "gather_manifest.json").write_text(json.dumps({
        "schema": 1, "build": {"job": "j", "number": "1", "url": "u"}, "channel": "os",
        "request": {"loc": "git", "deploymentEnvironmentId": "1", "eventUuid": "e", "callbackUrl": "http://x"},
        "ips": ips}), encoding="utf-8")
    (ws / "gather_rc.txt").write_text("2\n", encoding="utf-8")
    names = {"manifest": "gather_manifest.json", "output": "gather_output.json", "checkpoint": "gather_checkpoint.jsonl",
             "progress": "gather_progress.jsonl", "rc": "gather_rc.txt", "final": "gather_final.jsonl",
             "report": "gather_finalize_report.json"}
    code, report = fz.finalize(ws, REPO, "completed", names)
    final = [json.loads(line) for line in (ws / "gather_final.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return code, report, final


def _full(ip):
    env = _with_memory(ip)
    env["sections"] = {s: "success" for s in fz.ALL_SECTIONS}
    env["meta"], env["correlation"] = {}, {}
    return env


def test_chain_callback_then_layer_a_keeps_checkpoint_values(capsys, monkeypatch, tmp_path):
    _files(monkeypatch, tmp_path)
    d = Driver(capsys)
    _until_checkpoint(d, "10.0.0.1", _full("10.0.0.1"))
    _output_task_failed(d, "10.0.0.1")
    d.finish()
    code, report, final = _layer_a(tmp_path, ["10.0.0.1"])
    assert code == 0 and report["accepted"] == 1 and report["filled"] == 0
    assert final[0]["data"]["memory"]["installed_mb"] == 4096, "Astra 재현: 종전에는 memory=null 로 사라졌다"
    assert final[0]["status"] == "success"
    events = [json.loads(line) for line in (tmp_path / "gather_progress.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {"event": "reconciled", "source": "checkpoint"}.items() <= next(e for e in events if e["event"] == "reconciled").items()


def test_chain_unparsable_output_line_falls_back_to_checkpoint(capsys, monkeypatch, tmp_path):
    """OUTPUT msg 가 JSON 이 아니면(직렬화 실패) 콜백은 문자열 줄을 낸다 — 2026-10-10 (FL-F02): 그 줄은 13 필드 envelope 이 아니라
    emitted 로 세지 않고(emit_failed: shape), 플레이북 끝에 콜백이 CHECKPOINT 조립본으로 바로 보충한다. Layer A 는 문자열 줄을
    손상으로 버리고(damage) 보충된 OUTPUT 줄을 쓴다 — 종전에는 콜백이 emitted 로 세어 Layer A 가 CHECKPOINT 로 떨어졌다."""
    _files(monkeypatch, tmp_path)
    d = Driver(capsys)
    _until_checkpoint(d, "10.0.0.1", _full("10.0.0.1"))
    d.cb.v2_runner_on_ok(_Result(d.hosts["10.0.0.1"], "OUTPUT", action="ansible.builtin.debug",
                                 result={"msg": "{not json"}))
    d.finish()
    events = [json.loads(line) for line in (tmp_path / "gather_progress.jsonl").read_text(encoding="utf-8").splitlines()]
    assert next(e for e in events if e["event"] == "emit_failed")["detail"] == "shape"
    assert "emitted" not in {e["event"] for e in events if e["event"] != "reconciled"} or         [e["event"] for e in events].index("reconciled") < [e["event"] for e in events].index("emitted") if "emitted" in {e["event"] for e in events} else True
    assert {"event": "reconciled", "source": "checkpoint"}.items() <= next(e for e in events if e["event"] == "reconciled").items()
    code, report, final = _layer_a(tmp_path, ["10.0.0.1"])
    assert code == 2, "손상 줄(문자열)을 버렸으므로 damage"
    assert report["by_origin"] == {"output": 1, "checkpoint": 0, "synthetic": 0}, "콜백이 보충한 OUTPUT 줄을 쓴다"
    assert final[0]["data"]["memory"]["installed_mb"] == 4096
    assert final[0]["errors"][-1]["message"] == fz.EMIT_FAILED


@pytest.mark.parametrize("addon_started", [False, True])
def test_chain_mixed_batch_counts(capsys, monkeypatch, tmp_path, addon_started):
    _files(monkeypatch, tmp_path)
    d = Driver(capsys)
    _until_checkpoint(d, "10.0.0.1", _full("10.0.0.1"))
    d.output("10.0.0.1", _full("10.0.0.1"))
    _until_checkpoint(d, "10.0.0.2", _full("10.0.0.2"))
    if addon_started:
        _marker(d, "10.0.0.2", "ADDON_START")
    else:
        _output_task_failed(d, "10.0.0.2")
    d.finish()
    code, report, final = _layer_a(tmp_path, ["10.0.0.1", "10.0.0.2"])
    assert report["kept"] == 2 and report["filled"] == 0
    assert [e["data"]["memory"]["installed_mb"] for e in final] == [4096, 4096]
    assert final[1]["errors"][-1]["section"] == ("addon" if addon_started else "gather")
