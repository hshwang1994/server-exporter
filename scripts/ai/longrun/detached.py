"""분리 실행 · 생존 확인 · 파일 감시 (2026-11-09).

- start(): argv 를 호출한 셸과 분리된 프로세스로 띄운다. 같은 작업 폴더에 살아 있는 프로세스가 있으면 띄우지 않는다(rc 3).
- pid_alive(): Windows 에서 `os.kill(pid, 0)` 은 프로세스를 끝낸다 — 쓰지 않고 OpenProcess/GetExitCodeProcess 로 본다.
- watch(): 최신 `detached_*.log` 의 새 줄 중 pattern 에 맞는 줄만 내보내고, 읽은 위치를 `watch_offset.txt` 에 남긴다.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Iterator

PID_FILE = "pid.txt"
OFFSET_FILE = "watch_offset.txt"
LOG_GLOB = "detached_*.log"
STILL_ACTIVE = 259

# Windows creationflags
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat = Path(f"/proc/{pid}/stat")
    try:  # 끝났지만 부모가 거두지 않은 프로세스(zombie)는 살아 있지 않다
        return stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def read_pid(work: Path) -> int:
    try:
        return int((work / PID_FILE).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return 0


def running_pid(work: Path) -> int:
    """작업 폴더에 기록된 프로세스가 살아 있으면 그 PID, 아니면 0."""
    pid = read_pid(work)
    return pid if pid and pid_alive(pid) else 0


def acquire(work: Path) -> int:
    """이 프로세스를 작업 폴더의 실행자로 기록한다. 다른 살아 있는 실행자가 있으면 그 PID 를 돌려준다(기록하지 않음)."""
    work.mkdir(parents=True, exist_ok=True)
    other = running_pid(work)
    if other and other != os.getpid():
        return other
    (work / PID_FILE).write_text(str(os.getpid()), encoding="ascii")
    return 0


def start(work: Path, argv: list[str], cwd: Path | None = None, env: dict | None = None) -> tuple[int, int, Path | None]:
    """(rc, pid, log). rc 0 띄움 · 3 이미 실행 중(pid = 그 프로세스)."""
    work.mkdir(parents=True, exist_ok=True)
    other = running_pid(work)
    if other:
        return 3, other, None
    log = work / f"detached_{time.strftime('%Y%m%d-%H%M%S')}.log"
    kw: dict = {"stdin": subprocess.DEVNULL, "close_fds": True, "cwd": str(cwd) if cwd else None, "env": env}
    if os.name == "nt":
        flag_sets = [CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB,
                     CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW]
    else:
        flag_sets = [0]
        kw["start_new_session"] = True
    last_exc: OSError | None = None
    proc = None
    with open(log, "ab") as fp:
        for flags in flag_sets:
            try:
                if os.name == "nt":
                    proc = subprocess.Popen(argv, stdout=fp, stderr=subprocess.STDOUT, creationflags=flags, **kw)
                else:
                    proc = subprocess.Popen(argv, stdout=fp, stderr=subprocess.STDOUT, **kw)
                break
            except OSError as exc:  # job 이 이탈을 허락하지 않으면 이탈 없이 다시
                last_exc = exc
    if proc is None:
        raise last_exc or OSError("spawn failed")
    (work / PID_FILE).write_text(str(proc.pid), encoding="ascii")
    return 0, proc.pid, log


def latest_log(work: Path) -> Path | None:
    logs = sorted(work.glob(LOG_GLOB))
    return logs[-1] if logs else None


def watch(work: Path, pattern: str | None, *, poll_s: float = 15.0, alive: Callable[[int], bool] = pid_alive,
          sleep: Callable[[float], None] = time.sleep) -> Iterator[str]:
    """새 줄(pattern 이 있으면 맞는 줄만)을 내보낸다. 실행자가 끝나면 남은 줄을 다 내보내고 끝 표식을 낸 뒤 멈춘다."""
    rx = re.compile(pattern) if pattern else None
    pid = read_pid(work)
    off_file = work / OFFSET_FILE
    while True:
        running = bool(pid) and alive(pid)
        log = latest_log(work)
        if log is not None:
            pos = 0
            try:
                saved = off_file.read_text(encoding="ascii").split()
                if len(saved) == 2 and saved[0] == log.name:
                    pos = int(saved[1])
            except (OSError, ValueError):
                pos = 0
            data = log.read_bytes()
            chunk = data[pos:]
            cut = chunk.rfind(b"\n")
            body = chunk if not running else chunk[:cut + 1] if cut >= 0 else b""
            if body:
                for line in body.decode("utf-8", "replace").splitlines():
                    if rx is None or rx.search(line):
                        yield line.strip()[:300]
                off_file.write_text(f"{log.name} {pos + len(body)}", encoding="ascii")
        if not running:
            yield f"[MONITOR] 실행 프로세스 pid {pid or '-'} 종료 (작업 폴더 {work})"
            return
        sleep(poll_s)


def emit(line: str) -> None:
    sys.stdout.buffer.write((line + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()
