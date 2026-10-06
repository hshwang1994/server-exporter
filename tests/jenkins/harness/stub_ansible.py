#!/usr/bin/env python3
"""stub_ansible.py — Harness 가짜 ansible-playbook (2026-10-06, 9차). 운영 경로가 아니다.

tests/jenkins/harness/fixture.py 의 gather_stage 가 가짜 venv 의 bin/ansible-playbook 으로 이 파일을 부르게 만든다. Jenkinsfile_harness 가
운영 함수 seGatherStage(짧은 시험 상수)를 실행하면 실제 scripts/run_gather.sh 가 이 가짜를 `--limit @<남은 대상 파일>` 과 함께 실행한다.

하는 일 (시도마다 — 시도 번호는 받은 기록 수로 센다)
  1. --limit 파일의 대상을 <stub>/received.jsonl 에 {attempt, hosts} 로 남긴다 — 다시 수집한 대상이 남은 대상뿐인지 시험이 본다.
  2. plan.json 의 그 시도 항목대로 결과를 쓴다
       precheck_fail : Precheck 실패 진단(progress 'precheck', task "precheck | …", failure_stage reachable)만 남긴다 — OUTPUT 없음
       checkpoint    : CHECKPOINT 줄만 남긴다(조립본) — OUTPUT 없음, 실행 중이던 대상
       emit          : OUTPUT 줄(templates.jsonl 의 그 대상 envelope) — "all" · 앞에서 N 대 · 접수 순번 목록(1부터)
  3. orphan_hold 초 동안 잠금 fd 를 물려받은 자식이 남는다(Agent 연결만 끊긴 동안 계속 돈 이전 수집 흉내).
     crash 면 수집 셸(run_gather.sh, gather_run.json 의 pid)을 SIGKILL — 끝 기록 없이 사라진 시도 흉내. hang 이면 오래 기다린다.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time


def _append(path: str | None, line: str) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()


def main(argv: list[str]) -> int:
    stub = os.environ["SE_HARNESS_STUB_DIR"]
    ws = os.environ.get("WORKSPACE") or os.getcwd()
    lim = None
    if "--limit" in argv:
        lim = argv[argv.index("--limit") + 1].lstrip("@")
    hosts = [h.strip() for h in open(lim, encoding="utf-8") if h.strip()] if lim else []
    with open(os.path.join(stub, "plan.json"), encoding="utf-8") as fh:
        plan = json.load(fh)
    received = os.path.join(stub, "received.jsonl")
    n = 1
    if os.path.exists(received):
        with open(received, encoding="utf-8") as fh:
            n = sum(1 for line in fh if line.strip()) + 1
    _append(received, json.dumps({"attempt": n, "hosts": hosts}))
    attempts = plan.get("attempts") or []
    step = attempts[n - 1] if n - 1 < len(attempts) else {"emit": "all"}
    ips = plan["ips"]
    with open(os.path.join(stub, "templates.jsonl"), encoding="utf-8") as fh:
        templates = {json.loads(line)["ip"]: line.strip() for line in fh if line.strip()}

    def pick(spec):
        if spec == "all":
            return list(hosts)
        if isinstance(spec, int):
            return hosts[:spec]
        return [ips[i - 1] for i in (spec or []) if ips[i - 1] in hosts]

    out = os.environ.get("ANSIBLE_JSON_OUTPUT_FILE")
    prog = os.environ.get("ANSIBLE_JSON_PROGRESS_FILE")
    cp = os.environ.get("ANSIBLE_JSON_CHECKPOINT_FILE")
    ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    for ip in pick(step.get("precheck_fail")):
        diag = {"reachable": False, "port_open": False, "protocol_supported": None, "auth_success": None, "failure_stage": "reachable",
                "failure_code": "TARGET_UNREACHABLE", "failure_reason": plan.get("precheck_reason") or "unreachable (harness)",
                "details": {"channel": plan.get("channel"), "checked_ports": [22], "harness": True}}
        _append(prog, json.dumps({"ts": ts, "host": ip, "ip": ip, "event": "precheck", "task": "precheck | 진단 결과 저장", "detail": None,
                                  "diagnosis": diag}, ensure_ascii=False))
    for ip in pick(step.get("checkpoint")):
        _append(cp, templates[ip])
        _append(prog, json.dumps({"ts": ts, "host": ip, "ip": ip, "event": "checkpoint", "task": "CHECKPOINT", "detail": None}))
    for ip in pick(step.get("emit", "all")):
        _append(out, templates[ip])
        _append(prog, json.dumps({"ts": ts, "host": ip, "ip": ip, "event": "emitted", "task": "OUTPUT", "detail": None}))
    if step.get("orphan_hold"):
        if os.fork() == 0:                      # 잠금 fd(9)를 물려받은 채 남는다 — run_gather.sh 의 flock 이 이 프로세스가 끝나기를 기다린다
            time.sleep(int(step["orphan_hold"]))
            os._exit(0)
    time.sleep(int(step.get("sleep", 0)))
    if step.get("crash"):
        with open(os.path.join(ws, "gather_run.json"), encoding="utf-8") as fh:
            pid = json.load(fh)["attempts"][-1]["pid"]
        os.kill(int(pid), signal.SIGKILL)
        os._exit(0)
    if step.get("hang"):
        time.sleep(3600)
    return int(step.get("rc", 0))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
