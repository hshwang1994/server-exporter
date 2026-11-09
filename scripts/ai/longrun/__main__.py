"""`python -m scripts.ai.longrun` — 저장소 루트에서 실행한다 (2026-11-09).

  start          --work DIR [--cwd DIR] -- CMD ...   CMD 를 분리 실행 (rc 3: 같은 작업 폴더에 살아 있는 실행이 있음)
  watch          --work DIR [--pattern RE | --all]   Monitor 용 — 새 줄만, 읽은 위치를 남긴다. 실행이 끝나면 끝 표식 뒤 종료
  status         --work DIR                          실행 여부 · 최신 로그 꼬리 · state.json 요약
  promote-chain  --sha SHA --plan PLAN.json [...]   승격 체인 (chain.py). --detach 면 분리 실행 후 바로 돌아온다
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import DEFAULT_HOME, REPO_ROOT
from .chain import PHASES, Chain, valid_sha
from .detached import emit, latest_log, pid_alive, read_pid, start, watch

# 승격 체인 감시에 쓰는 줄: 단계 · 판정 · 빌드 번호 · 결과 · ref · 오류
CHAIN_PATTERN = (r" --- | \[PASS\] | \[NG\] | \[HOLD\] |=== |\[SAME\]|\[DIFF\]|\[INFO\]|build #\d+ started|adopt #|keep #|"
                 r" s checkout=|promote rc=|뒤 ref|verdict=|Traceback|Error|HTTP [45]\d\d")


def _start(a) -> int:
    argv = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not argv:
        sys.stderr.write("실행할 명령이 없다 (-- 뒤에 적는다)\n")
        return 2
    rc, pid, log = start(Path(a.work), argv, cwd=Path(a.cwd) if a.cwd else None)
    if rc == 3:
        print(f"이미 실행 중: pid={pid} (작업 폴더 {a.work})")
        return 3
    print(f"detached pid={pid}\nlog={log}\nwork={a.work}")
    return 0


def _watch(a) -> int:
    pattern = None if a.all else (a.pattern or CHAIN_PATTERN)
    for line in watch(Path(a.work), pattern, poll_s=a.poll):
        emit(line)
    return 0


def _status(a) -> int:
    work = Path(a.work)
    pid = read_pid(work)
    print(f"pid={pid or '-'} alive={bool(pid) and pid_alive(pid)}")
    log = latest_log(work)
    if log:
        tail = log.read_bytes().decode("utf-8", "replace").splitlines()[-a.lines:]
        print(f"log={log}")
        for line in tail:
            print("  " + line[:300])
    st = work / "state.json"
    if st.exists():
        d = json.loads(st.read_text(encoding="utf-8"))
        print("state: " + json.dumps({k: d.get(k) for k in ("sha", "prod_before", "prod_after", "matrix", "ci", "canary",
                                                          "repo_was_private")}, ensure_ascii=False))
        for h in d.get("history", [])[-5:]:
            print(f"  history {h}")
    return 0


def _chain(a) -> int:
    if not valid_sha(a.sha):
        sys.stderr.write("--sha 는 40자리 소문자 16진수\n")
        return 2
    work = (Path(a.work) if a.work else DEFAULT_HOME / f"promote-{a.sha[:8]}").resolve()
    if a.detach:
        # 분리 실행은 저장소 루트에서 돈다 — 상대 경로를 지금 위치 기준 절대 경로로 바꿔 넘긴다
        args = ["promote-chain", "--sha", a.sha, "--plan", str(Path(a.plan).resolve()), "--work", str(work),
                "--netrc", str(Path(a.netrc).resolve()), "--vault-password-file", str(Path(a.vault_password_file).resolve()),
                "--from", a.start, "--to", a.stop, *(["--plan-only"] if a.plan_only else []), *(["--fresh"] if a.fresh else [])]
        rc, pid, log = start(work, [sys.executable, "-X", "utf8", "-m", "scripts.ai.longrun", *args], cwd=REPO_ROOT)
        if rc == 3:
            print(f"이미 실행 중: pid={pid} (작업 폴더 {work}) - 같은 작업 폴더로 둘 띄우지 않는다")
            return 3
        print(f"detached pid={pid}\nlog={log}\nwork={work}\n"
              f"감시: python -m scripts.ai.longrun watch --work {work}  (Monitor 로 걸고, 끊기면 같은 명령으로 다시 건다)")
        return 0
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    ch = Chain(a.sha, plan, work, Path(a.netrc), Path(a.vault_password_file), fresh=a.fresh)
    return ch.run(a.start, a.stop, a.plan_only)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.ai.longrun", description="장시간 실행 (분리 실행 · 빌드 기록 · 이어받기 · 파일 감시)")
    sub = ap.add_subparsers(dest="cmd_name", required=True)
    p = sub.add_parser("start", help="명령을 분리 실행")
    p.add_argument("--work", required=True)
    p.add_argument("--cwd")
    p.add_argument("cmd", nargs=argparse.REMAINDER)
    p.set_defaults(func=_start)
    p = sub.add_parser("watch", help="Monitor 용 로그 감시")
    p.add_argument("--work", required=True)
    p.add_argument("--pattern")
    p.add_argument("--all", action="store_true", help="모든 새 줄")
    p.add_argument("--poll", type=float, default=15.0)
    p.set_defaults(func=_watch)
    p = sub.add_parser("status", help="실행 여부 · 로그 꼬리 · state 요약")
    p.add_argument("--work", required=True)
    p.add_argument("--lines", type=int, default=15)
    p.set_defaults(func=_status)
    p = sub.add_parser("promote-chain", help="main 매트릭스 → CI → promote → canary")
    p.add_argument("--sha", required=True)
    p.add_argument("--plan", required=True, help="계획 파일 (chain.py 머리말 형식 — 직전 승격의 next_plan.json)")
    p.add_argument("--work", help=f"작업 폴더 (기본 {DEFAULT_HOME}/promote-<sha8>)")
    p.add_argument("--netrc", default=str(Path.home() / "prodgen_netrc.txt"))
    p.add_argument("--vault-password-file", default=str(Path.home() / "prodgen_vault_pw.txt"))
    p.add_argument("--from", dest="start", default="preflight", choices=PHASES)
    p.add_argument("--to", dest="stop", default="canary_cmp", choices=PHASES)
    p.add_argument("--plan-only", action="store_true", help="읽기 전용 점검 + 보낼 내용 출력 (POST 0 · push 0)")
    p.add_argument("--fresh", action="store_true", help="고른 단계를 앞 시도 기록 없이 처음부터 (기본은 이어 돌리기)")
    p.add_argument("--detach", action="store_true", help="분리 실행하고 바로 돌아온다")
    p.set_defaults(func=_chain)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
