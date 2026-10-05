"""F12 (2026-10-05): 수집 정체 감시 — 진행 중인 수집은 기다리고, 아무것도 진행되지 않는 배치만 멈춘다.

시간을 줄여 실제 프로세스로 확인한다(예상 · 정체 시간을 초 단위 이하로). 감시 대상은 GNU timeout 대신 `sleep` 프로세스다 —
감시가 보내는 SIGINT 를 받고 끝나는지까지 본다. 운영 Runner(Linux) 전용 도구라 POSIX 에서만 돈다 (CI Gate 가 Runner 에서 실행).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import gather_watch as gw  # noqa: E402

pytestmark = pytest.mark.skipif(os.name == "nt", reason="운영 Linux Runner 도구 — POSIX 신호 의미가 필요하다")
PORTAL = (REPO / "Jenkinsfile_portal").read_text(encoding="utf-8")


@pytest.fixture
def target(tmp_path):
    proc = subprocess.Popen(["sleep", "60"])
    (tmp_path / "pid").write_text(str(proc.pid), encoding="utf-8")
    yield proc, tmp_path
    if proc.poll() is None:
        proc.kill()
        proc.wait()


def _watch(tmp_path, expected, stall, **kw):
    t0 = time.monotonic()
    res = gw.watch(str(tmp_path / "pid"), str(tmp_path / "progress.jsonl"), str(tmp_path / "hb"), expected, stall,
                   str(tmp_path / "watch.json"), poll=0.05, pid_wait=2, **kw)
    return res, time.monotonic() - t0


def _writer(path, event, every, until):
    def run():
        end = time.monotonic() + until
        while time.monotonic() < end:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": "t", "host": "h", "ip": "192.0.2.1", "event": event, "task": "x"}) + "\n")
            time.sleep(every)
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


def test_no_progress_stops_after_expected_plus_stall(target):
    proc, tmp = target
    res, took = _watch(tmp, expected=0.4, stall=0.3)
    assert res["result"] == "stalled" and took >= 0.4
    assert proc.wait(timeout=5) != 0, "감시가 보낸 SIGINT 로 끝난다"
    rec = json.loads((tmp / "watch.json").read_text(encoding="utf-8"))
    assert rec["reason"] == "stalled" and rec["progress_events"] == 0


def test_never_stops_before_the_expected_time(target):
    proc, tmp = target
    res, took = _watch(tmp, expected=1.2, stall=0.1)
    assert res["result"] == "stalled" and took >= 1.2, "정체 판단은 예상 시간이 지난 뒤에만"


def test_progress_events_keep_a_slow_batch_running(target):
    proc, tmp = target
    _writer(tmp / "progress.jsonl", "alive", 0.15, 1.5)
    res, took = _watch(tmp, expected=0.2, stall=0.5)
    assert res["result"] == "stalled" and took >= 1.5, "진행이 이어지는 동안은 예상 시간을 넘겨도 멈추지 않는다"
    assert res["progress_events"] >= 5


def test_redfish_heartbeat_counts_as_progress(target):
    proc, tmp = target
    hb = tmp / "hb"
    hb.mkdir()

    def touch():
        end = time.monotonic() + 1.2
        while time.monotonic() < end:
            (hb / "redfish-192.0.2.1").write_text(str(time.time()), encoding="utf-8")
            os.utime(hb / "redfish-192.0.2.1", (time.time(), time.time()))
            time.sleep(0.1)
    threading.Thread(target=touch, daemon=True).start()
    res, took = _watch(tmp, expected=0.1, stall=0.4)
    assert res["result"] == "stalled" and took >= 1.2


def test_failures_retries_and_lost_are_not_progress(target):
    proc, tmp = target
    _writer(tmp / "progress.jsonl", "lost", 0.05, 3)
    res, took = _watch(tmp, expected=0.2, stall=0.4)
    assert res["result"] == "stalled" and took < 2.0 and res["progress_events"] == 0


def test_a_partial_last_line_is_read_once_complete(tmp_path):
    p = tmp_path / "progress.jsonl"
    p.write_text('{"event":"alive"}\n{"event":"ali', encoding="utf-8")
    tail = gw._ProgressTail(str(p))
    assert tail.new_events() == 1
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('ve"}\n')
    assert tail.new_events() == 1 and tail.new_events() == 0


def test_finished_batch_leaves_no_record(tmp_path):
    proc = subprocess.Popen(["sleep", "0.3"])
    (tmp_path / "pid").write_text(str(proc.pid), encoding="utf-8")
    res, _ = _watch(tmp_path, expected=5, stall=5)
    proc.wait()
    assert res["result"] == "finished" and not (tmp_path / "watch.json").exists()


def test_missing_pid_file_gives_up_quietly(tmp_path):
    res = gw.watch(str(tmp_path / "nope"), str(tmp_path / "p"), "", 1, 1, str(tmp_path / "w"), poll=0.05, pid_wait=0.3)
    assert res == {"result": "no_pid"}


def test_main_never_fails_the_build(tmp_path, monkeypatch):
    monkeypatch.setattr(gw, "watch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert gw.main(["--pidfile", "x", "--progress", "y", "--expected", "1", "--out", "z"]) == 0


def test_gather_shell_runs_the_watch_beside_a_foreground_timeout():
    gather = PORTAL[PORTAL.index("stage('서버 정보 수집')"):]
    i_watch = gather.index('python3 "\\${WORKSPACE}/scripts/gather_watch.py"')
    i_exec = gather.index("bash -c 'echo \\$\\$ > \"\\$1\"; shift; exec \"\\$@\"' se-gather")
    i_timeout = gather.index('timeout --signal=INT --kill-after=90 "\\${SE_GATHER_BUDGET_SEC}"')
    assert i_watch < i_exec < i_timeout, "감시를 먼저 띄우고, timeout 은 exec 로 pid 를 남긴 채 foreground 로 돈다"
    assert 'if [ "\\${SE_GATHER_WATCH}" = "true" ]; then' in gather
    assert "boolean watchOn = (exec.limit_source?.toString() == 'ceiling')" in gather, "시험용 강제 제한에서는 감시를 끈다"
    assert "limitReason = 'stalled'" in gather and "env.SE_GATHER_LIMIT_REASON = limitReason" in gather
    assert "0|2|4|8) rm -f" in gather, "끝까지 돈 실행의 감시 기록은 버린다"


def test_watch_is_shipped_in_the_production_tree():
    manifest = (REPO / "production_manifest.yml").read_text(encoding="utf-8")
    assert "  - path: scripts/gather_watch.py\n    language: python\n" in manifest


def test_shell_wiring_stops_a_hung_run_through_gnu_timeout(tmp_path):
    """Jenkinsfile 과 같은 배선(감시를 먼저 띄우고, exec 로 pid 를 남긴 foreground timeout)으로 진행이 멈춘 실행을 끝낸다.
    가짜 ansible 은 진행 이벤트를 1.5 s 보내고 멈춘다 — 감시가 timeout 에 INT 를 보내면 timeout 이 그 신호를 넘겨 실행이 끝난다."""
    import shutil
    if not shutil.which("timeout"):
        pytest.skip("GNU timeout 없음")
    fake = tmp_path / "fake-ansible"
    fake.write_text("#!/bin/bash\nfor i in 1 2 3; do echo '{\"event\":\"alive\"}' >> \"$1\"; sleep 0.5; done\nsleep 120\n", encoding="utf-8")
    fake.chmod(0o755)
    script = (
        "set +e\n"
        f"T={tmp_path}\n"
        f"python3 {REPO / 'scripts' / 'gather_watch.py'} --pidfile $T/pid --progress $T/progress.jsonl --heartbeat-dir $T/hb "
        "--expected 1 --stall 1 --out $T/watch.json --poll 0.2 &\n"
        "WP=$!\n"
        "bash -c 'echo $$ > \"$1\"; shift; exec \"$@\"' se-gather \"$T/pid\" timeout --signal=INT --kill-after=5 60 $T/fake-ansible $T/progress.jsonl\n"
        "rc=$?\n"
        "kill $WP 2>/dev/null; wait $WP 2>/dev/null\n"
        "echo rc=$rc\n"
    )
    t0 = time.monotonic()
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    took = time.monotonic() - t0
    rc = int(r.stdout.strip().splitlines()[-1].split("=")[1])
    assert rc not in (0, 124), f"정체 감시로 끝났다 (timeout 상한 60 s 가 아니다): rc={rc}"
    assert 2.0 <= took < 15, took
    assert json.loads((tmp_path / "watch.json").read_text(encoding="utf-8"))["reason"] == "stalled"
