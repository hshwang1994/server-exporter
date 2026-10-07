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
CG = "/user.slice/user-985.slice/session-570.scope"   # Agent 세션 범위 — 여러 빌드가 함께 쓴다
KERNEL_NONE = {"readable": True, "kills": []}          # 커널 로그를 읽었고 OOM 종료 기록이 없다
PROBES = {"boot_id": "boot-a", "btime": T0 - 86400, "kernel_mark": 1000.0, "kernel": KERNEL_NONE,
          "oom": {"vmstat": 0, "cgroup": 0, "cgroup_path": CG}}


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
    (137, 100, 1, "process_lost", False),                     # 10차 R5: 공유 cgroup 의 OOM 카운터 증가만으로는 이 실행의 OOM 이 아니다
    (1, 100, 1, "failed_run", False),                         # 10차 R5: 스스로 끝난 실행 실패를 OOM 으로 가리지 않는다(Astra 재현 사례)
    (90, 5, 0, "prep_failed", False), (91, 5, 0, "prep_failed", False),
    (143, 50, 0, "aborted", False), (130, 50, 0, "aborted", False), (129, 50, 0, "aborted", False),
    (143, 50, 1, "aborted", False),                           # 10차 R5: TERM + 공유 카운터 증가는 관측일 뿐이다(PID 근거 없음)
])
def test_end_classifies_with_evidence_only(tmp_path, rc, ran, oom_after, state, timed_out):
    ws = _ws(tmp_path, ["10.0.0.1"])
    _begin(ws, T0, gather_max=600)
    oom = {"vmstat": 0, "cgroup": oom_after, "cgroup_path": CG}
    att = gs.end(ws, rc=rc, now=T0 + ran, probes={"oom": oom, "kernel": KERNEL_NONE})
    assert att["state"] == state and att["timed_out"] is timed_out and att["exec_sec"] == ran and att["end_source"] in ("exit", "signal")
    assert (ws / "gather_rc.txt").read_text(encoding="utf-8").strip() == str(rc)
    run = _state(ws)
    assert run["ran_sec"] == run["exec_used_sec"] == ran and run["rc"] == rc and run["state"] == state
    if oom_after:
        assert att["oom_observed"] == {"cgroup": {"path": CG, "delta": 1}}, "관측은 남긴다"
        if state != "completed":
            assert "원인" in (att["evidence"] or ""), att["evidence"]
    assert att["oom_link"] is None


def _ansible_pid(ws, pid):
    (ws / ".gather_ansible_pid").write_text(f"{pid}\n", encoding="utf-8")


def test_oom_of_this_runs_process_with_the_following_signal_is_the_runner_oom(tmp_path):
    # 반례 4(필수): 이 수집 실행의 프로세스(ansible-playbook 주 프로세스)가 OOM 으로 끝났다는 커널 기록이 있고, 그에 따른 종료 신호가 왔다
    #   (2026-10-06 Runner03 격리 시험 — 커널이 수집 프로세스를 OOM 으로 끝내자 systemd 가 범위를 멈추며 수집 셸에 TERM)
    ws = _ws(tmp_path, ["10.0.0.1"])
    _begin(ws, T0, gather_max=600)
    _ansible_pid(ws, 5151)
    kernel = {"readable": True, "kills": [{"at": 1500.0, "pid": 5151, "comm": "ansible-playboo"}]}
    att = gs.end(ws, rc=143, now=T0 + 5, probes={"oom": dict(PROBES["oom"], cgroup=1), "kernel": kernel})
    assert att["state"] == "runner_oom" and att["end_source"] == "signal" and att["rc"] == 143
    assert att["oom_link"] == {"pid": 5151, "role": "ansible-playbook", "comm": "ansible-playboo", "at": 1500.0}
    assert "PID 5151" in att["evidence"] and att["evidence"].endswith("signal TERM")
    assert att["ansible_pid"] == 5151 and att["kernel_log"] == "readable"
    assert gs.TERMINAL_STATES.count("runner_oom") == 0 and "runner_oom" in gs.INFRA_STATES, "이어서 수집하는 실행 기반 장애다"
    # 같은 근거로 KILL(137, 한계 전)도 runner_oom
    (tmp_path / "k").mkdir()
    ws2 = _ws(tmp_path / "k", ["10.0.0.1"])
    _begin(ws2, T0, gather_max=600)
    _ansible_pid(ws2, 6161)
    att2 = gs.end(ws2, rc=137, now=T0 + 5, probes={"oom": PROBES["oom"], "kernel": {"readable": True, "kills": [{"at": 1200.0, "pid": 6161, "comm": "python3"}]}})
    assert att2["state"] == "runner_oom" and "KILL" in att2["evidence"]


@pytest.mark.parametrize("rc,state", [(1, "failed_run"), (137, "process_lost"), (143, "aborted")])
def test_other_process_oom_in_the_shared_cgroup_is_only_an_observation(tmp_path, rc, state):
    # 반례 1 · 2(필수): 같은 공유 cgroup 의 다른 프로세스가 종료 직전에 OOM 으로 끝났다(카운터 +1, 커널 기록의 PID 는 이 실행의 것이 아니다).
    #   이 수집은 별도 원인으로 rc=1 / kill -9 / TERM 으로 끝났다 — OOM 을 원인으로 적지 않고 관측만 남긴다(불필요한 재시도 없음)
    ws = _ws(tmp_path, ["10.0.0.1"])
    _begin(ws, T0, gather_max=600)
    _ansible_pid(ws, 5151)
    kernel = {"readable": True, "kills": [{"at": 1990.0, "pid": 9999, "comm": "java"}]}
    att = gs.end(ws, rc=rc, now=T0 + 50, probes={"oom": dict(PROBES["oom"], cgroup=1), "kernel": kernel})
    assert att["state"] == state and att["oom_link"] is None
    assert att["oom_observed"] == {"cgroup": {"path": CG, "delta": 1}}
    assert "원인" in att["evidence"] and "runner_oom" not in att["evidence"], att["evidence"]
    assert att["state"] not in gs.INFRA_STATES


def test_another_process_entering_an_isolated_scope_after_start_is_not_this_runs_oom(tmp_path):
    # 반례(필수, 10차 보정): 시도 시작 때 cgroup 에 이 실행만 있었더라도 그 뒤 다른 프로세스가 들어와 OOM 으로 끝날 수 있다 —
    #   시작 때의 구성원과 카운터 증가만으로는 원인이 아니다. 커널 기록의 PID 가 이 실행의 것이 아니면 TERM 은 취소(aborted)로 남는다
    ws = _ws(tmp_path, ["10.0.0.1"])
    scope = "/system.slice/run-r1234.scope"
    probes = dict(PROBES, oom={"vmstat": 0, "cgroup": 0, "cgroup_path": scope})
    _begin(ws, T0, gather_max=600, probes=probes)
    _ansible_pid(ws, 5151)
    kernel = {"readable": True, "kills": [{"at": 1700.0, "pid": 7171, "comm": "stress"}]}
    att = gs.end(ws, rc=143, now=T0 + 30, probes={"oom": {"vmstat": 1, "cgroup": 1, "cgroup_path": scope}, "kernel": kernel})
    assert att["state"] == "aborted" and att["oom_observed"]["cgroup"] == {"path": scope, "delta": 1} and att["oom_observed"]["system"] == {"delta": 1}


def test_worker_fork_oom_is_not_this_runs_oom_gp64(tmp_path):
    # GP-64 (10차 마무리 6): Jenkins Agent·Ansible 주 프로세스는 살아 있고 이 수집에 속한 작업자(fork)만 OOM 으로 끝난 경우.
    #   작업자 PID 는 run_gather.sh·ansible-playbook 주 프로세스가 아니고 기록되지도 않는다 → 커널 로그에 그 PID 의 OOM 기록이
    #   있어도 이 실행에 직접 귀속할 수 없다. 공유 카운터·종료 코드만으로 OOM 을 추정하는 새 로직을 두지 않는다 — 한계로 남긴다.
    ws = _ws(tmp_path, ["10.0.0.1"])
    _begin(ws, T0, gather_max=600)            # run_gather.sh pid=4242
    _ansible_pid(ws, 5151)                    # ansible-playbook 주 프로세스
    worker = {"readable": True, "kills": [{"at": 1500.0, "pid": 8888, "comm": "python3"}]}   # 작업자 fork — run_pids 에 없다
    # oom_link: 작업자 PID 는 이 실행의 PID 집합(run_gather.sh·ansible 주)에 없어 연결되지 않는다
    assert gs.oom_link({"pid": 4242, "started_epoch": T0}, ws, worker) is None
    # 주 프로세스가 살아 정상 종료 코드로 끝났고(작업자 하나가 죽어 rc=1) OOM 카운터가 올랐다 → 관측만 남기고 원인은 아니다(failed_run)
    att = gs.end(ws, rc=1, now=T0 + 40, probes={"oom": dict(PROBES["oom"], cgroup=1), "kernel": worker})
    assert att["state"] == "failed_run" and att["oom_link"] is None
    assert att["oom_observed"] == {"cgroup": {"path": CG, "delta": 1}}
    assert att["state"] not in gs.INFRA_STATES      # 같은 Runner runner_oom 재개 경로로 가지 않는다
    # 설령 주 프로세스가 신호로 끝났더라도(137) 커널 기록의 OOM PID 가 작업자뿐이면 연결 없음 → process_lost(원인 미확인)
    (tmp_path / "s").mkdir()
    ws2 = _ws(tmp_path / "s", ["10.0.0.1"])
    _begin(ws2, T0, gather_max=600)
    _ansible_pid(ws2, 5151)
    att2 = gs.end(ws2, rc=137, now=T0 + 40, probes={"oom": dict(PROBES["oom"], cgroup=1), "kernel": worker})
    assert att2["state"] == "process_lost" and att2["oom_link"] is None and "원인 미확인" in att2["evidence"]


def test_unreadable_kernel_log_is_never_an_oom_cause(tmp_path):
    ws = _ws(tmp_path, ["10.0.0.1"])
    _begin(ws, T0, gather_max=600)
    _ansible_pid(ws, 5151)
    att = gs.end(ws, rc=137, now=T0 + 30, probes={"oom": dict(PROBES["oom"], cgroup=1), "kernel": {"readable": False, "kills": []}})
    assert att["state"] == "process_lost" and att["kernel_log"] == "unreadable" and "커널 로그를 읽지 못함" in att["evidence"]


def test_user_abort_overlapping_an_oom_increase_is_recorded_as_aborted(tmp_path):
    # 반례 3(필수): OOM 카운터 증가와 사용자 취소가 겹쳤다. 파이프라인이 취소로 확인하면(classify --user-abort) 그 시도는 aborted 다 —
    #   이 실행의 PID 가 OOM 으로 끝난 기록이 있었더라도 취소한 요청을 다시 시작하지 않는다
    ws = _ws(tmp_path, ["10.0.0.1"])
    _begin(ws, T0, gather_max=600)
    _ansible_pid(ws, 5151)
    kernel = {"readable": True, "kills": [{"at": 1100.0, "pid": 5151, "comm": "ansible-playboo"}]}
    att = gs.end(ws, rc=143, now=T0 + 20, probes={"oom": dict(PROBES["oom"], cgroup=1), "kernel": kernel})
    assert att["state"] == "runner_oom"
    out = gs.classify(ws, user_abort=True, now=T0 + 25, probes=PROBES)
    assert out["state"] == "aborted" and out["infra"] is False and "사용자 취소" in out["evidence"] and "runner_oom" in out["evidence"]
    rec = _state(ws)["attempts"][-1]
    assert rec["user_abort"] is True and rec["oom_observed"] == {"cgroup": {"path": CG, "delta": 1}}
    # 이미 스스로 끝난 시도(completed)는 취소로 바꾸지 않는다
    (tmp_path / "c").mkdir()
    ws2 = _ws(tmp_path / "c", ["10.0.0.1"])
    _begin(ws2, T0)
    gs.end(ws2, rc=0, now=T0 + 5, probes=PROBES)
    assert gs.classify(ws2, user_abort=True, now=T0 + 6, probes=PROBES)["state"] == "completed"


def test_kernel_oom_records_are_parsed_by_pid_and_window():
    text = "\n".join([
        "[  900.000001] Out of memory: Killed process 1111 (java) total-vm:1kB, anon-rss:1kB",                # 시도 전 — 뺀다
        "[ 1500.250000] oom-kill:constraint=CONSTRAINT_MEMCG,nodemask=(null),cpuset=/,mems_allowed=0,oom_memcg=/x,task_memcg=/x,task=python3,pid=2222,uid=985",
        "[ 1500.260000] Memory cgroup out of memory: Killed process 2222 (python3) total-vm:9kB, anon-rss:9kB",
        "[ 1600.000000] Out of memory: Killed process 3333 (ansible-playboo) total-vm:1kB, anon-rss:1kB, UID:985 oom_score_adj:0",
        "unrelated line", "[ 1700.0] something else",
    ])
    kills = gs.parse_kernel_oom(text, since=1000.0)
    assert kills == [{"at": 1500.25, "pid": 2222, "comm": "python3"}, {"at": 1600.0, "pid": 3333, "comm": "ansible-playboo"}]
    assert gs.parse_kernel_oom(text, since=None)[0]["pid"] == 1111
    assert gs.parse_kernel_oom("", since=0) == [] and gs.parse_kernel_oom(None, since=0) == []
    # 기준점과 같은 시각의 줄은 시도 시작 때 이미 있던 줄이다 — 뺀다
    assert [k["pid"] for k in gs.parse_kernel_oom(text, since=1500.26)] == [3333]
    assert gs.parse_kernel_oom(text, since=1500.25)[0] == {"at": 1500.26, "pid": 2222, "comm": "python3"}, "같은 PID 의 뒤 줄(Killed process)은 남는다"


# 2026-10-07 Runner03(VMware) 실측 형식 그대로 — 커널 로그 시각(printk)이 /proc/uptime 보다 약 22초 늦었다(시도 시작 uptime 1357006.19, 그 뒤의 OOM 기록 1356984.27)
RUNNER03_BEFORE = "\n".join([
    "[1309802.489401] oom-kill:constraint=CONSTRAINT_MEMCG,nodemask=(null),cpuset=/,mems_allowed=0,oom_memcg=/system.slice/se-oom-probe-1255082.scope,"
    "task_memcg=/system.slice/se-oom-probe-1255082.scope,task=python3,pid=1255125,uid=0",
    "[1309802.489415] Memory cgroup out of memory: Killed process 1255125 (python3) total-vm:756444kB, anon-rss:63904kB, file-rss:5760kB, shmem-rss:0kB, UID:0 pgtables:200kB oom_score_adj:0",
    "[1356960.100000] IPv6: ADDRCONF(NETDEV_CHANGE): ens192: link becomes ready",
])
RUNNER03_AFTER = RUNNER03_BEFORE + "\n" + "\n".join([
    "[1356984.274808] oom-kill:constraint=CONSTRAINT_MEMCG,nodemask=(null),cpuset=/,mems_allowed=0,oom_memcg=/system.slice/se-oom10-isolated_9th-1332166.scope,"
    "task_memcg=/system.slice/se-oom10-isolated_9th-1332166.scope,task=python3,pid=1332436,uid=985",
    "[1356984.274820] Memory cgroup out of memory: Killed process 1332436 (python3) total-vm:756444kB, anon-rss:63896kB, file-rss:5888kB, shmem-rss:0kB, UID:985 pgtables:200kB oom_score_adj:0",
])


def test_kernel_log_mark_is_taken_from_the_kernel_logs_own_clock():
    assert gs.kernel_log_mark(RUNNER03_BEFORE) == 1356960.1
    assert gs.kernel_log_mark("no timestamps here\n") == 0.0, "읽었지만 시각이 붙은 줄이 없다"
    assert gs.kernel_log_mark(None) is None, "읽지 못했다 — 기준점 없음"
    assert gs.kernel_oom_kills(None, lambda: RUNNER03_AFTER) == {"readable": False, "kills": [], "why": "시도 시작 때 커널 로그를 읽지 못해 기준점이 없음"}
    assert gs.kernel_oom_kills(1356960.1, lambda: None) == {"readable": False, "kills": []}
    assert gs.kernel_oom_kills(1356960.1, lambda: RUNNER03_AFTER)["kills"] == [{"at": 1356984.274808, "pid": 1332436, "comm": "python3"}]


def test_this_runs_oom_is_linked_even_when_the_kernel_log_clock_lags_uptime(tmp_path):
    # 10차 실기(2026-10-07, Runner03 격리 시험)에서 찾은 결함 — 시도 시작을 /proc/uptime 으로 잡았더니 커널 로그 시각이 그보다 늦어
    #   이 실행의 OOM 종료 기록이 '시작 전' 으로 빠졌고 runner_oom 이 aborted 가 됐다. 기준점을 커널 로그 자신의 시계로 잡으면 연결된다
    ws = _ws(tmp_path, ["10.0.0.1"])
    begin_probes = {k: v for k, v in PROBES.items() if k not in ("kernel_mark", "kernel")}
    _begin(ws, T0, gather_max=600, probes=dict(begin_probes, dmesg=RUNNER03_BEFORE))
    assert gs.load_state(ws)["attempts"][-1]["kernel_mark"] == 1356960.1
    _ansible_pid(ws, 1332436)
    att = gs.end(ws, rc=143, now=T0 + 5, probes={"oom": dict(PROBES["oom"], cgroup=1), "dmesg": RUNNER03_AFTER})
    assert att["state"] == "runner_oom" and att["oom_link"] == {"pid": 1332436, "role": "ansible-playbook", "comm": "python3", "at": 1356984.274808}
    # 시작 때 커널 로그를 읽지 못했으면 기준점이 없다 — 나중에 읽혀도 오래된 같은 PID 번호를 이 실행으로 잇지 않는다
    (tmp_path / "n").mkdir()
    ws2 = _ws(tmp_path / "n", ["10.0.0.1"])
    _begin(ws2, T0, gather_max=600, probes=dict(begin_probes, dmesg=None))
    assert gs.load_state(ws2)["attempts"][-1]["kernel_mark"] is None
    _ansible_pid(ws2, 1332436)
    att2 = gs.end(ws2, rc=143, now=T0 + 5, probes={"oom": dict(PROBES["oom"], cgroup=1), "dmesg": RUNNER03_AFTER})
    assert att2["state"] == "aborted" and att2["oom_link"] is None and att2["kernel_log"] == "unreadable"
    assert "기준점" in att2["evidence"], att2["evidence"]


def test_oom_observation_reports_scope_and_never_decides_the_cause():
    assert gs.oom_observation({"cgroup": 3, "cgroup_path": CG, "vmstat": 10}, {"cgroup": 4, "cgroup_path": CG, "vmstat": 10}) == \
        {"cgroup": {"path": CG, "delta": 1}}
    assert gs.oom_observation({"cgroup": 3, "cgroup_path": CG, "vmstat": 10}, {"cgroup": 3, "cgroup_path": CG, "vmstat": 11}) == \
        {"system": {"delta": 1}}, "Runner 전체 증가는 Runner 전체 관측으로만"
    assert gs.oom_observation({"cgroup": 3, "cgroup_path": CG, "vmstat": 10}, {"cgroup": 9, "cgroup_path": "/other", "vmstat": 10}) is None
    assert gs.oom_observation(None, None) is None
    assert not hasattr(gs, "oom_evidence"), "카운터 증가를 원인으로 쓰던 함수는 없다"


def test_open_attempt_is_closed_with_evidence(tmp_path):
    ws = _ws(tmp_path, ["10.0.0.1", "10.0.0.2"])
    _begin(ws, T0)
    _alive(ws, T0 + 300)
    reboot = dict(PROBES, boot_id="boot-b", btime=T0 + 330)
    out = gs.classify(ws, now=T0 + 4000, probes=reboot)
    assert out["state"] == "runner_restart" and out["infra"] is True and out["exec_sec"] == 330 and "boot_id" in out["evidence"]

    # 끝 기록 없이 사라짐 + 공유 cgroup 카운터 증가만 — 원인 미확인(10차 R5)
    (tmp_path / "b").mkdir()
    ws2 = _ws(tmp_path / "b", ["10.0.0.1"])
    _begin(ws2, T0)
    oom = dict(PROBES, oom={"vmstat": 0, "cgroup": 1, "cgroup_path": CG})
    out2 = gs.classify(ws2, now=T0 + 100, probes=oom)
    assert out2["state"] == "process_lost" and out2["infra"] is False and "원인 미확인" in out2["evidence"]

    # 끝 기록 없이 사라짐 + 이 실행의 PID 가 OOM 으로 끝난 커널 기록 — runner_oom
    (tmp_path / "b2").mkdir()
    ws2b = _ws(tmp_path / "b2", ["10.0.0.1"])
    _begin(ws2b, T0)
    killed = dict(PROBES, kernel={"readable": True, "kills": [{"at": 1300.0, "pid": 4242, "comm": "bash"}]})
    out2b = gs.classify(ws2b, now=T0 + 100, probes=killed)
    assert out2b["state"] == "runner_oom" and out2b["infra"] is True and "run_gather.sh" in out2b["evidence"]

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


def _emitted(ip):
    return {"ts": "2026-10-06T00:00:00+00:00", "host": ip, "ip": ip, "event": "emitted", "task": "OUTPUT"}


def test_confirmed_hosts_whose_results_vanished_are_not_gathered_again(tmp_path):
    # 10차 R3: 결과가 확정됐던 대상(진행 기록 emitted)의 결과 줄이 결과 파일에서 사라졌다 — 다시 수집하지 않고 재개 불가로 남긴다
    ips = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    ws = _ws(tmp_path, ips, outputs=[_envelope("10.0.0.1"), _envelope("10.0.0.2")], progress=[_emitted("10.0.0.1"), _emitted("10.0.0.2")])
    first = _begin(ws, T0)
    assert first["state"] is None and first["pending"] == 1
    gs.end(ws, rc=137, now=T0 + 10, probes=PROBES)             # 첫 시도가 바깥에서 끝났다(실행 기반 장애 등)
    (ws / "gather_output.json").write_text(json.dumps(_envelope("10.0.0.1")) + "\n", encoding="utf-8")   # 10.0.0.2 의 결과 줄이 사라졌다
    plan = _begin(ws, T0 + 100)
    assert plan["state"] == "resume_impossible" and plan["lost"] == 1 and "10.0.0.2" in plan["evidence"]
    att = _state(ws)["attempts"][-1]
    assert att["state"] == "resume_impossible" and att["lost_ips"] == ["10.0.0.2"] and att["rc"] == 92
    assert not (ws / ".gather_limit_hosts").exists() or "10.0.0.2" not in (ws / ".gather_limit_hosts").read_text()


def test_same_count_but_different_hosts_is_detected_by_ip(tmp_path):
    # 개수가 같아도 확정됐던 대상의 결과가 다른 대상의 결과로 바뀌었으면 그 대상의 결과는 사라진 것이다(앞 시도 기록의 completed_ips 로 대조)
    ips = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    ws = _ws(tmp_path, ips, outputs=[_envelope("10.0.0.1"), _envelope("10.0.0.2")])
    _begin(ws, T0)
    att = gs.end(ws, rc=137, now=T0 + 10, probes=PROBES)
    assert att["completed_ips"] == ["10.0.0.1", "10.0.0.2"]
    (ws / "gather_output.json").write_text("".join(json.dumps(e) + "\n" for e in (_envelope("10.0.0.1"), _envelope("10.0.0.3"))), encoding="utf-8")
    plan = _begin(ws, T0 + 100)
    assert plan["state"] == "resume_impossible" and "10.0.0.2" in plan["evidence"]


def test_unconfirmed_hosts_stay_pending_and_confirmed_invalid_lines_are_not_regathered(tmp_path):
    ips = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    bad = dict(_envelope("10.0.0.2"), status="weird")          # 결과 줄은 있지만 형태 검사를 통과하지 못한다
    ws = _ws(tmp_path, ips, outputs=[_envelope("10.0.0.1"), bad], progress=[_emitted("10.0.0.1"), _emitted("10.0.0.2")])
    plan = _begin(ws, T0)
    assert plan["state"] is None and plan["pending"] == 1, "확정 근거가 없는 10.0.0.3 만 남은 대상이다"
    assert (ws / ".gather_limit_hosts").read_text(encoding="utf-8") == "10.0.0.3\n"


def test_precheck_failures_recorded_by_earlier_attempts_are_not_regathered(tmp_path):
    ips = ["10.0.0.1", "10.0.0.2"]
    ws = _ws(tmp_path, ips, progress=[_precheck("10.0.0.2", "reachable")])
    _begin(ws, T0)
    att = gs.end(ws, rc=137, now=T0 + 10, probes=PROBES)
    assert att["precheck_failed_ips"] == ["10.0.0.2"]
    (ws / "gather_progress.jsonl").unlink()                    # 진행 기록이 사라져도 앞 시도 기록으로 확정 실패를 안다
    plan = _begin(ws, T0 + 100)
    assert plan["pending"] == 1 and (ws / ".gather_limit_hosts").read_text(encoding="utf-8") == "10.0.0.1\n"


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
