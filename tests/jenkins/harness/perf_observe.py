#!/usr/bin/env python3
"""perf_observe.py — Runner 자원 관측기 (main 전용 도구, 2026-10-04 최종 실행 지시 §7 · Plan §8 "perf_observe"). **읽기 전용** — /proc 만 읽는다.

무엇을 재나
  같은 Runner 에서 도는 Gather 빌드의 ansible 프로세스 트리를 **빌드별로 귀속**한다: 각 프로세스의 /proc/<pid>/environ 에 Jenkinsfile_portal 이
  넣는 `SE_BUILD_ID=<BUILD_TAG>` 가 있다(fork 된 worker · ssh · 원격 모듈 python 이 모두 상속). 빌드마다 PSS 합(/proc/<pid>/smaps_rollup, 없으면
  RSS), RSS 합, 활성 worker 수(= `ansible-playbook` cmdline 프로세스 수 − 메인 프로세스 수; forks 상한이 아니라 **지금 살아 있는 worker**),
  메인 프로세스 PSS(고정 비용 후보)를 INTERVAL 마다 JSONL 한 줄로 남긴다. 노드 전체는 MemAvailable · SwapFree · loadavg · /proc/stat 누적치.
  다른 사용자의 프로세스는 읽지 못한다(권한) — 같은 agent 사용자가 돌리는 빌드가 관측 대상이고 그게 전부다.
  configured forks 나 RSS 합만으로 "활성 fork 당 PSS" 를 확정하지 않기 위한 도구다(최종 지시 §7).

사용 (Jenkins Job clovirone-cicd/clovirone-server-gather-perf-observe — tests/jenkins/harness/Jenkinsfile_perf_observe):
  python3 tests/jenkins/harness/perf_observe.py --duration 900 --interval 2 --idle-exit 90 --out perf_observe.jsonl --meta perf_observe_meta.json
  --idle-exit N : 빌드를 한 번이라도 본 뒤 N 초 동안 아무 빌드도 없으면 끝낸다(Gather 가 끝나면 자동 종료). 0 이면 duration 까지.
집계는 perf_observe_report.py. Python 3.6+ (Runner 시스템 python3 3.9 · venv 3.12).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

PROC = "/proc"


def read_meminfo() -> dict:
    out = {}
    try:
        with open(os.path.join(PROC, "meminfo"), encoding="ascii", errors="replace") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                    try:
                        out[key] = int(rest.split()[0])
                    except (ValueError, IndexError):
                        pass
    except OSError:
        pass
    return out


def read_cpu():
    try:
        with open(os.path.join(PROC, "stat"), encoding="ascii", errors="replace") as fh:
            fields = fh.readline().split()
        vals = [int(x) for x in fields[1:]]
        return vals[3], sum(vals)
    except (OSError, ValueError, IndexError):
        return None, None


def read_load():
    try:
        with open(os.path.join(PROC, "loadavg"), encoding="ascii", errors="replace") as fh:
            return float(fh.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def proc_build_id(pid: int):
    try:
        with open(os.path.join(PROC, str(pid), "environ"), "rb") as fh:
            env = fh.read()
    except OSError:
        return None
    for part in env.split(b"\0"):
        if part.startswith(b"SE_BUILD_ID="):
            return part[len(b"SE_BUILD_ID="):].decode("utf-8", "replace")
    return None


def proc_cmdline(pid: int) -> str:
    try:
        with open(os.path.join(PROC, str(pid), "cmdline"), "rb") as fh:
            raw = fh.read()
    except OSError:
        return ""
    return " ".join(p.decode("utf-8", "replace") for p in raw.split(b"\0") if p)


def proc_pss_rss(pid: int):
    """(pss_kb | None, rss_kb | None). smaps_rollup (kernel ≥ 4.14) 가 없거나 못 읽으면 status 의 VmRSS 만."""
    pss = rss = None
    try:
        with open(os.path.join(PROC, str(pid), "smaps_rollup"), encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith("Pss:"):
                    pss = int(line.split()[1])
                elif line.startswith("Rss:"):
                    rss = int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    if rss is None:
        try:
            with open(os.path.join(PROC, str(pid), "status"), encoding="ascii", errors="replace") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        rss = int(line.split()[1])
                        break
        except (OSError, ValueError, IndexError):
            pass
    return pss, rss


def proc_state_ppid(pid: int):
    try:
        with open(os.path.join(PROC, str(pid), "stat"), encoding="ascii", errors="replace") as fh:
            raw = fh.read()
        tail = raw[raw.rindex(")") + 2:].split()
        return tail[0], int(tail[1])
    except (OSError, ValueError, IndexError):
        return None, None


def sample_builds(self_pid: int) -> dict:
    """{build_id: {procs, pss_kb, rss_kb, playbook_procs, active_workers, main_pid, main_pss_kb, ssh_procs, other_procs, pids:[…≤60]}}"""
    builds = {}
    playbook = {}
    for name in os.listdir(PROC):
        if not name.isdigit():
            continue
        pid = int(name)
        if pid == self_pid:
            continue
        bid = proc_build_id(pid)
        if not bid:
            continue
        cmd = proc_cmdline(pid)
        pss, rss = proc_pss_rss(pid)
        state, ppid = proc_state_ppid(pid)
        b = builds.setdefault(bid, {"procs": 0, "pss_kb": 0, "rss_kb": 0, "pss_known": 0, "playbook_procs": 0, "active_workers": 0,
                                    "main_pid": None, "main_pss_kb": None, "ssh_procs": 0, "other_procs": 0, "pids": []})
        b["procs"] += 1
        b["pss_kb"] += pss or 0
        b["rss_kb"] += rss or 0
        if pss is not None:
            b["pss_known"] += 1
        first = cmd.split(" ", 1)[0] if cmd else ""
        if "ansible-playbook" in cmd:
            b["playbook_procs"] += 1
            playbook.setdefault(bid, []).append({"pid": pid, "ppid": ppid, "pss_kb": pss})
        elif first.endswith("ssh") or first.endswith("sshpass"):
            b["ssh_procs"] += 1
        else:
            b["other_procs"] += 1
        if len(b["pids"]) < 60:
            b["pids"].append({"pid": pid, "ppid": ppid, "state": state, "pss_kb": pss, "rss_kb": rss, "cmd": cmd[:100]})
    for bid, procs in playbook.items():
        pids = {p["pid"] for p in procs}
        mains = [p for p in procs if p["ppid"] not in pids]
        b = builds[bid]
        if mains:
            b["main_pid"] = mains[0]["pid"]
            b["main_pss_kb"] = mains[0]["pss_kb"]
        b["active_workers"] = max(0, len(procs) - len(mains))
    return builds


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--duration", type=int, default=900)
    ap.add_argument("--interval", type=int, default=2)
    ap.add_argument("--idle-exit", type=int, default=90, help="빌드를 본 뒤 이 시간(초) 동안 빌드가 없으면 종료 (0 = 끝까지)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--meta", default="")
    ap.add_argument("--tag", default="")
    a = ap.parse_args(argv)
    if not os.path.isdir(PROC):
        sys.stderr.write("[perf-observe] /proc 가 없다 — Linux 에서만 돈다\n")
        return 2
    start = time.time()
    self_pid = os.getpid()
    seen_any = False
    last_seen = None
    samples = 0
    peak = {}
    exit_reason = "duration"
    with open(a.out, "w", encoding="utf-8") as fh:
        while time.time() < start + a.duration:
            ts = time.time()
            mem = read_meminfo()
            idle, total = read_cpu()
            builds = sample_builds(self_pid)
            line = {"ts": round(ts, 1), "mem_total_kb": mem.get("MemTotal"), "mem_available_kb": mem.get("MemAvailable"),
                    "swap_total_kb": mem.get("SwapTotal"), "swap_free_kb": mem.get("SwapFree"), "load1": read_load(),
                    "cpu_idle": idle, "cpu_total": total, "builds": builds}
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
            fh.flush()
            samples += 1
            for bid, b in builds.items():
                pk = peak.setdefault(bid, {"pss_kb": 0, "active_workers": 0, "first_ts": round(ts, 1), "last_ts": round(ts, 1)})
                pk["pss_kb"] = max(pk["pss_kb"], b["pss_kb"])
                pk["active_workers"] = max(pk["active_workers"], b["active_workers"])
                pk["last_ts"] = round(ts, 1)
            if builds:
                seen_any = True
                last_seen = ts
            elif seen_any and a.idle_exit and last_seen is not None and ts - last_seen > a.idle_exit:
                exit_reason = "idle_exit"
                break
            time.sleep(max(0.2, a.interval - (time.time() - ts)))
    meta = {"host": socket.gethostname(), "tag": a.tag, "start": round(start, 1), "end": round(time.time(), 1), "samples": samples,
            "interval": a.interval, "duration": a.duration, "idle_exit": a.idle_exit, "exit_reason": exit_reason,
            "nproc": os.cpu_count(), "mem_total_kb": read_meminfo().get("MemTotal"), "builds_seen": peak,
            "kernel": (os.uname().release if hasattr(os, "uname") else None)}
    if a.meta:
        with open(a.meta, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)
    sys.stdout.write(json.dumps(meta, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
