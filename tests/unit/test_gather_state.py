"""scripts/gather_state.py — 수집 실행 기록 · 재개 대상 · 누적 실행 시간 (2026-10-06, 9차).

가짜 시계(now 인자)와 시험용 관측값(probes: boot_id · btime · oom)으로 돈다 — 운영 코드에 시험 분기는 없다.
고정하는 것
  - 실행 시간은 보수적으로 센다: 끝 기록이 있으면 그 값, 없으면 마지막 생존 표시 + 표시 주기(60초). 끝난 순간이 주기 안 어디였든
    계산값 >= 실제 실행 시간이고, 비정상 종료가 반복돼도 누적이 줄지 않는다. 재부팅이면 새 부팅 시각, 그리고 지금을 넘지 않는다.
  - 이번 시도의 한계 = 수집 실행 한계 − 누적 실행 시간. 기다린 시간은 여기에 없다(대기는 Jenkinsfile_portal 이 따로 센다).
  - 남은 대상 = 접수 IP − 형태 검사를 통과한 결과 줄의 IP − Precheck 실패가 관측된 IP. 재개 표식이 지난 시도의 관측을 지운다.
  - 잘린 마지막 줄은 조각 파일로 옮긴다(다음 시도가 이어 쓸 때 두 줄이 같이 깨지지 않게).
  - 원인은 근거가 있을 때만: 재부팅(boot_id) · OOM(같은 cgroup 카운터 증가, cgroup 을 못 읽을 때만 Runner 전체) · 연결 끊김(Jenkins 보고).
    근거가 없으면 원인 미확인(process_lost) — 다시 시도하지 않는다.
  - 메모리 · 남은 빌드 시간으로 시작을 막지 않는다. 동시 실행 수는 채널 상한 그대로다.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "gather_state.py"
_spec = importlib.util.spec_from_file_location("gather_state", SCRIPT)
gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gs)

LINUX = sys.platform.startswith("linux")
ALL = ["system", "hardware", "bmc", "cpu", "memory", "storage", "network", "firmware", "users", "power", "thermal"]
T0 = 1_800_000_000
PROBES = {"boot_id": "boot-a", "btime": T0 - 86400, "oom": {"vmstat": 0, "cgroup": 0, "cgroup_path": "/system.slice/jenkins-agent.service"}}


def _envelope(ip, channel="os"):
    import finalize_gather_output as fz   # gather_state 가 sys.path 에 scripts/ 를 넣었다
    return {"schema_version": "1", "target_type": channel, "collection_method": fz.CHANNEL_METHOD[channel], "ip": ip, "hostname": f"h-{ip}",
            "vendor": None, "status": "success", "sections": {s: "success" for s in ALL},
            "diagnosis": {k: None for k in fz.DIAGNOSIS_KEYS} | {"details": {}}, "meta": {}, "correlation": {}, "errors": [],
            "data": {"system": {"hostname": f"h-{ip}"}}}


def _precheck(ip, stage):
    return {"ts": "2026-10-06T00:00:00+00:00", "host": ip, "ip": ip, "event": "precheck", "task": "precheck | run",
            "diagnosis": {"failure_stage": stage, "failure_code": "TCP_CONNECT_FAILED" if stage else None}}


def _ws(tmp_path, ips, channel="os", outputs=(), progress=(), raw_output=None):
    (tmp_path / "gather_manifest.json").write_text(json.dumps({"schema": 1, "build": {"job": "j", "number": "7"}, "channel": channel,
                                                               "ips": list(ips)}), encoding="utf-8")
    if raw_output is not None:
        (tmp_path / "gather_output.json").write_text(raw_output, encoding="utf-8")
    elif outputs:
        (tmp_path / "gather_output.json").write_text("".join(json.dumps(o) + "\n" for o in outputs), encoding="utf-8")
    if progress:
        (tmp_path / "gather_progress.jsonl").write_text("".join(json.dumps(e) + "\n" for e in progress), encoding="utf-8")
    return tmp_path


def _begin(ws, now, gather_max=21600, agent_lost=False, probes=None, vault="", cp=""):
    return gs.begin(ws, pid=4242, vault_tmp=vault, cp_dir=cp, gather_max=gather_max, vcpu=8, os_cap=None, prev_agent_lost=agent_lost,
                    now=now, probes=probes or PROBES)


def _alive(ws, t):
    p = ws / ".gather_alive"
    p.touch()
    os.utime(p, (t, t))


def _state(ws):
    return json.loads((ws / "gather_run.json").read_text(encoding="utf-8"))


# ── 보수적 실행 시간 ─────────────────────────────────────────────────────────────────────────────────────────

def test_exec_time_with_a_reliable_end_is_exact():
    att = {"started_epoch": T0, "ended_epoch": T0 + 1234}
    assert gs.attempt_exec_sec(att, None, T0 + 99999, False, None) == 1234


@pytest.mark.parametrize("crash_after", [0, 1, 59, 60, 61, 119, 120, 3599, 3600, 3601, 7259])
def test_exec_time_without_an_end_never_undercounts(crash_after):
    """생존 표시는 시작 직후 한 번, 그 뒤 60초마다 쓴다. 어느 순간에 끝나도 계산값 >= 실제 실행 시간, 더 센 몫은 60초 이하."""
    interval = 60
    marks = [T0 + k * interval for k in range(crash_after // interval + 1)]   # 끝나기 전까지 쓴 생존 표시
    last_alive = marks[-1]
    got = gs.attempt_exec_sec({"started_epoch": T0}, last_alive, T0 + 10 * 86400, False, None, interval)
    assert crash_after <= got <= crash_after + interval


def test_exec_time_never_seen_alive_counts_one_interval_and_is_capped_by_reboot_and_now():
    att = {"started_epoch": T0}
    assert gs.attempt_exec_sec(att, None, T0 + 9999, False, None) == 60
    assert gs.attempt_exec_sec(att, T0 - 500, T0 + 9999, False, None) == 60, "앞 시도의 생존 표시는 이 시도의 근거가 아니다"
    assert gs.attempt_exec_sec(att, T0 + 600, T0 + 9999, True, T0 + 630) == 630, "재부팅 뒤 시각은 넘지 않는다"
    assert gs.attempt_exec_sec(att, T0 + 600, T0 + 610, False, None) == 610, "지금보다 뒤를 세지 않는다"


def test_repeated_abnormal_ends_accumulate_and_shrink_the_next_limit(tmp_path):
    """비정상 종료 세 번(끝 기록 없음) — 매번 begin 이 근거로 닫고, 누적은 실제 실행 시간의 합보다 작지 않다."""
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"])
    real = 0
    now = T0
    plan = _begin(ws, now)
    assert plan["limit"] == 21600 and plan["exec_used"] == 0
    for crash_after, wait in ((1000, 3600), (59, 600), (7200, 86400)):
        _alive(ws, now)
        for k in range(1, crash_after // 60 + 1):
            _alive(ws, now + 60 * k)
        real += crash_after
        now = now + crash_after + wait                       # 끝 기록 없이 사라지고, 실행 기반을 wait 초 기다렸다
        plan = _begin(ws, now)
        assert plan["closed_previous"] == "process_lost"
        assert plan["exec_used"] >= real, "덜 세지 않는다"
        assert plan["exec_used"] <= real + 60 * len(_state(ws)["attempts"]), "더 세는 몫은 시도마다 표시 주기 이하"
        assert plan["limit"] == 21600 - plan["exec_used"], "기다린 시간(wait)은 한계에서 빠지지 않는다"


def test_limit_exhausted_does_not_start_and_reports_the_gather_limit(tmp_path):
    ws = _ws(tmp_path, ["10.0.0.1"])
    _begin(ws, T0, gather_max=600)
    gs.end(ws, rc=124, now=T0 + 600, probes=PROBES)
    plan = _begin(ws, T0 + 5000, gather_max=600)
    assert plan["limit"] == 0 and plan["state"] == "gather_limit"
    att = _state(ws)["attempts"][-1]
    assert att["rc"] == 124 and att["timed_out"] is True and att["exec_sec"] == 0 and att["end_source"] == "limit_exhausted"


# ── 남은 대상 ───────────────────────────────────────────────────────────────────────────────────────────

def test_pending_excludes_finished_and_precheck_failed_hosts(tmp_path):
    ips = ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5"]
    bad = _envelope("10.0.0.4")
    bad["status"] = "weird"                                   # 형태 검사를 통과하지 못한 줄은 결과가 아니다
    ws = _ws(tmp_path, ips, outputs=[_envelope("10.0.0.1"), bad],
             progress=[_precheck("10.0.0.2", "port"), _precheck("10.0.0.3", None), _precheck("10.0.0.5", "auth")])
    plan = _begin(ws, T0)
    assert plan["completed"] == 1 and plan["precheck_failed"] == 1
    assert (ws / ".gather_limit_hosts").read_text(encoding="utf-8").split() == ["10.0.0.3", "10.0.0.4", "10.0.0.5"]
    marker = [json.loads(l) for l in (ws / "gather_progress.jsonl").read_text(encoding="utf-8").splitlines()][-1]
    assert marker["event"] == "attempt" and marker["n"] == 1 and marker["hosts"] == ["10.0.0.3", "10.0.0.4", "10.0.0.5"]


def test_attempt_marker_resets_previous_observations(tmp_path):
    """다시 수집하는 대상의 지난 관측은 재개 표식이 지운다 — 표식 뒤의 관측만 남는다."""
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"],
             progress=[_precheck("10.0.0.1", "reachable"),
                       {"event": "attempt", "n": 2, "hosts": ["10.0.0.1"], "host": None, "ip": None},
                       _precheck("10.0.0.2", "protocol")])
    done, pre = gs.completed_hosts(ws, "os", ["10.0.0.1", "10.0.0.2"])
    assert done == set() and pre == {"10.0.0.2"}


def test_nothing_pending_finishes_without_running(tmp_path):
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"], outputs=[_envelope("10.0.0.1")], progress=[_precheck("10.0.0.2", "port")])
    plan = _begin(ws, T0)
    assert plan["pending"] == 0 and plan["state"] == "completed"
    att = _state(ws)["attempts"][-1]
    assert att["rc"] == 0 and att["end_source"] == "no_pending" and not (ws / ".gather_limit_hosts").exists()


def test_truncated_tail_is_moved_aside_and_the_host_is_gathered_again(tmp_path):
    whole = json.dumps(_envelope("10.0.0.1")) + "\n"
    cut = json.dumps(_envelope("10.0.0.2"))[:80]
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"], raw_output=whole + cut)
    plan = _begin(ws, T0)
    assert plan["tail_fixed"] == ["gather_output.json"]
    assert (ws / "gather_output.json").read_text(encoding="utf-8") == whole
    frag = json.loads((ws / "gather_tail_fragments.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert frag["file"] == "gather_output.json" and frag["fragment"] == cut and frag["bytes"] == len(cut)
    assert (ws / ".gather_limit_hosts").read_text(encoding="utf-8").split() == ["10.0.0.2"]


# ── 끝 · 판정 ──────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rc,ran,oom_after,state,timed_out", [
    (0, 100, 0, "completed", False), (2, 100, 0, "completed", False), (4, 100, 0, "completed", False), (8, 100, 0, "completed", False),
    (124, 600, 0, "gather_limit", True), (137, 700, 0, "gather_limit", True),
    (124, 100, 0, "failed_run", False),                       # 한계 전 124 는 한계 도달이 아니다
    (137, 100, 0, "process_lost", False),                     # 한계 전 KILL, OOM 근거 없음 — 원인 미확인
    (137, 100, 1, "runner_oom", False),                       # 같은 cgroup 의 OOM 카운터가 늘었다
    (1, 100, 1, "runner_oom", False),
    (90, 5, 0, "prep_failed", False), (91, 5, 0, "prep_failed", False),
    (143, 50, 0, "aborted", False), (130, 50, 0, "aborted", False), (129, 50, 0, "aborted", False),
])
def test_end_classifies_with_evidence_only(tmp_path, rc, ran, oom_after, state, timed_out):
    ws = _ws(tmp_path, ["10.0.0.1"])
    _begin(ws, T0, gather_max=600)
    oom = {"vmstat": 0, "cgroup": oom_after, "cgroup_path": "/system.slice/jenkins-agent.service"}
    att = gs.end(ws, rc=rc, now=T0 + ran, probes={"oom": oom})
    assert att["state"] == state and att["timed_out"] is timed_out and att["exec_sec"] == ran and att["end_source"] in ("exit", "signal")
    assert (ws / "gather_rc.txt").read_text(encoding="utf-8").strip() == str(rc)
    run = _state(ws)
    assert run["ran_sec"] == run["exec_used_sec"] == ran and run["rc"] == rc and run["state"] == state


def test_oom_evidence_uses_the_same_cgroup_and_falls_back_to_the_runner_only_without_it():
    cg = "/system.slice/jenkins-agent.service"
    assert gs.oom_evidence({"cgroup": 3, "cgroup_path": cg, "vmstat": 10}, {"cgroup": 4, "cgroup_path": cg, "vmstat": 10})
    assert gs.oom_evidence({"cgroup": 3, "cgroup_path": cg, "vmstat": 10}, {"cgroup": 3, "cgroup_path": cg, "vmstat": 11}) is None, \
        "같은 cgroup 을 읽었는데 그대로면 이 Runner 의 다른 프로세스가 끝난 것이다"
    assert gs.oom_evidence({"cgroup": None, "vmstat": 10}, {"cgroup": None, "vmstat": 11})
    assert gs.oom_evidence({"cgroup": 3, "cgroup_path": cg, "vmstat": 10}, {"cgroup": 9, "cgroup_path": "/other", "vmstat": 10}) is None
    assert gs.oom_evidence(None, None) is None


def test_open_attempt_is_closed_with_evidence(tmp_path):
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"])
    _begin(ws, T0)
    _alive(ws, T0 + 300)
    reboot = dict(PROBES, boot_id="boot-b", btime=T0 + 330)
    out = gs.classify(ws, now=T0 + 4000, probes=reboot)
    assert out["state"] == "runner_restart" and out["infra"] is True and out["exec_sec"] == 330 and "boot_id" in out["evidence"]

    (tmp_path / "b").mkdir()
    ws2 = _ws(tmp_path / "b", ["10.0.0.1"])
    _begin(ws2, T0)
    oom = dict(PROBES, oom={"vmstat": 0, "cgroup": 1, "cgroup_path": "/system.slice/jenkins-agent.service"})
    assert gs.classify(ws2, now=T0 + 100, probes=oom)["state"] == "runner_oom"

    (tmp_path / "c").mkdir()
    ws3 = _ws(tmp_path / "c", ["10.0.0.1"])
    _begin(ws3, T0)
    lost = gs.classify(ws3, agent_lost=True, now=T0 + 100, probes=PROBES)
    assert lost["state"] == "agent_disconnect" and lost["infra"] is True

    (tmp_path / "d").mkdir()
    ws4 = _ws(tmp_path / "d", ["10.0.0.1"])
    _begin(ws4, T0)
    unknown = gs.classify(ws4, now=T0 + 100, probes=PROBES)
    assert unknown["state"] == "process_lost" and unknown["infra"] is False and unknown["end_source"] == "start"


def test_progress_counts_only_this_attempt(tmp_path):
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2", "10.0.0.3"], outputs=[_envelope("10.0.0.1")])
    _begin(ws, T0)
    with open(ws / "gather_output.json", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(_envelope("10.0.0.2")) + "\n")
    gs.end(ws, rc=0, now=T0 + 50, probes=PROBES)
    out = gs.classify(ws, now=T0 + 60, probes=PROBES)
    assert out["completed"] == 2 and out["progress"] == 1 and out["pending_left"] == 1 and out["hosts_total"] == 3
    assert gs.count(ws) == "2/3"


def test_not_started_without_a_record(tmp_path):
    assert gs.classify(_ws(tmp_path, ["10.0.0.1"]), now=T0)["state"] == "not_started"


def test_stale_paths_of_a_vanished_attempt_are_removed_only_when_they_match(tmp_path, monkeypatch):
    ws = _ws(tmp_path, ["10.0.0.1"])
    _begin(ws, T0, vault="/etc/passwd", cp="/tmp/not-ours")
    out = gs.classify(ws, now=T0 + 100, probes=PROBES)
    assert out["state"] == "process_lost" and _state(ws)["attempts"][-1]["stale_removed"] == [], "이름 규칙이 다르면 지우지 않는다"


@pytest.mark.skipif(not LINUX, reason="flock 은 Runner(Linux) · WSL 에서 본다")
def test_a_running_previous_attempt_is_not_closed(tmp_path):
    import fcntl
    ws = _ws(tmp_path, ["10.0.0.1"])
    _begin(ws, T0)
    fd = os.open(str(ws / ".gather.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        out = gs.classify(ws, now=T0 + 10, probes=PROBES)
        assert out["state"] == "running" and out["attempt"] == 1 and out["infra"] is True and out["progress"] == 0 and out["pending_left"] == 1
        assert not _state(ws)["attempts"][-1].get("state"), "도는 중인 시도를 닫지 않는다"
    finally:
        os.close(fd)
    assert gs.classify(ws, now=T0 + 20, probes=PROBES)["state"] == "process_lost"


@pytest.mark.skipif(not LINUX, reason="/tmp 이름 규칙 · 소유자 확인은 Runner(Linux) · WSL 에서 본다")
def test_stale_vault_and_ssh_paths_are_removed(tmp_path):
    # run_gather.sh 와 같은 방법(coreutils mktemp — 영숫자만)으로 만든다
    vault = subprocess.run(["mktemp", "/tmp/se_vault.XXXXXXXXXX"], capture_output=True, text=True, check=True).stdout.strip()
    cp = subprocess.run(["mktemp", "-d", "/tmp/se_cp.XXXXXX"], capture_output=True, text=True, check=True).stdout.strip()
    ws = _ws(tmp_path, ["10.0.0.1"])
    _begin(ws, T0, vault=vault, cp=cp)
    out = gs.classify(ws, now=T0 + 100, probes=PROBES)
    assert out["state"] == "process_lost"
    assert sorted(_state(ws)["attempts"][-1]["stale_removed"]) == ["cp_dir", "vault_tmp"]
    assert not os.path.exists(vault) and not os.path.exists(cp)


# ── 동시 실행 수 · 메모리 ───────────────────────────────────────────────────────────────────────────────

def test_forks_are_channel_caps_without_memory():
    assert gs.forks_for("os", 500, 8, None) == 50 and gs.forks_for("os", 500, 8, 80) == 80 and gs.forks_for("os", 3, 8, None) == 3
    assert gs.forks_for("esxi", 100, 8, None) == 16 and gs.forks_for("redfish", 100, 8, None) == 32
    assert gs.forks_for("redfish", 0, None, None) == 1
    src = SCRIPT.read_text(encoding="utf-8")
    for gone in ("meminfo", "MemAvailable", "SE_MEM_AVAILABLE_MB", "SE_PER_FORK_MB", "SE_NODE_SHARE_PCT", "mem_cap"):
        assert gone not in src, gone


# ── 명령줄 (run_gather.sh · Jenkinsfile_portal 이 부르는 형태) ───────────────────────────────────────────

def test_cli_round_trip(tmp_path):
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"], outputs=[_envelope("10.0.0.1")])
    env = dict(os.environ, PYTHONIOENCODING="utf-8")   # Runner 는 UTF-8 — Windows 콘솔 코드 페이지와 무관하게 본다
    run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), *a], capture_output=True, text=True, encoding="utf-8", timeout=60, env=env)
    r = run("begin", "--ws", str(ws), "--pid", "1", "--gather-max", "21600", "--vcpu", "4", "--os-forks-cap", "")
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    assert plan["pending"] == 1 and plan["forks"] == 1 and plan["limit"] == 21600 and plan["channel"] == "os"
    r = run("end", "--ws", str(ws), "--rc", "0", "--ssh-closed", "2")
    assert r.returncode == 0 and json.loads(r.stdout)["state"] == "completed"
    r = run("classify", "--ws", str(ws))
    assert r.returncode == 0 and json.loads(r.stdout)["state"] == "completed"
    r = run("count", "--ws", str(ws))
    assert r.returncode == 0 and r.stdout.strip() == "1/2"
    (ws / "gather_manifest.json").write_text("{}", encoding="utf-8")
    r = run("begin", "--ws", str(ws), "--pid", "1", "--gather-max", "100")
    assert r.returncode == 2 and "[수집 기록]" in r.stderr
