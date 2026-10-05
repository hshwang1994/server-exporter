#!/usr/bin/env python3
"""gather_watch.py — 수집 정체 감시 (2026-10-05, F12).

왜 있나
  종전에는 예산 공식이 낸 **예상 시간**이 그대로 ansible 배치의 중단 기준(GNU timeout)이었다. 예상이 빗나가면 아직 정상으로
  진행 중인 수집도 잘렸다. 지금 중단 기준은 둘이다.
    1) 운영 상한 — 남은 stage · 전체 시간에서 마무리 예비 시간을 뺀 값 (scripts/gather_budget.sh 의 budget, GNU timeout 이 집행)
    2) 정체 — **예상 시간이 지난 뒤** 모든 host 에서 진행이 STALL 초 동안 없을 때만 (이 스크립트)
  진행 중인 수집은 예상 시간을 넘겨도 운영 상한까지 기다리고, 아무것도 진행되지 않는 배치만 일찍 끝낸다.

진행으로 보는 것 (실제로 무언가 끝났다는 관측만)
  - gather_progress.jsonl 의 새 이벤트: first_seen · precheck · cred_load · auth_proven · alive(작업 태스크 성공) · checkpoint ·
    addon_started · addon_done · emitted · reconciled  (json_only 콜백이 쓴다)
  - heartbeat 디렉터리 파일의 수정 시각이 늘어남 — Redfish 모듈이 새 응답을 받을 때 갱신한다(한 태스크 안의 긴 페이지 수집)
  진행으로 보지 않는 것: 실패 · retry · rescue 의 set_fact · lost · 프로세스가 살아 있다는 사실 · 같은 페이지 재요청(캐시 hit 는 네트워크가 없다)

멈추는 방법
  ansible 을 감싼 GNU timeout 프로세스에 SIGINT 를 보낸다 — timeout 이 받은 신호를 자식 프로세스 그룹에 넘기고 kill-after(90 s)를
  건다(배치 상한 도달 때와 같은 정리 경로). 멈추기 전에 이유를 --out JSON 으로 남긴다: {reason: stalled, idle_sec, expected_sec, …}.
  Jenkinsfile_portal 이 그 파일을 보고 outcome=timeout · limit_reason=stalled 로 기록한다(새 failure_code 없음).

STALL 기본 420 s = 가장 긴 단일 태스크 상한 300 s(Add-on) + 120 s. 태스크 하나는 자기 timeout 안에서 끝나거나 실패하므로, 정상
흐름에서 진행 이벤트 사이 간격은 이보다 짧다. Redfish 긴 수집은 heartbeat 로 진행이 보인다.

사용 (Jenkinsfile_portal Gather 의 ansible 셸 — 운영 Linux Runner 전용):
  python3 scripts/gather_watch.py --pidfile P --progress gather_progress.jsonl --heartbeat-dir D --expected 905 --stall 420 --out gather_watch.json &
종료 코드: 언제나 0 (감시 실패가 수집을 끊지 않는다).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

PROGRESS_EVENTS = frozenset({'first_seen', 'precheck', 'cred_load', 'auth_proven', 'alive', 'checkpoint',
                             'addon_started', 'addon_done', 'emitted', 'reconciled'})


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open('/proc/%d/stat' % pid, encoding='utf-8', errors='replace') as fh:
            if fh.read().rsplit(')', 1)[1].split()[0] == 'Z':
                return False
    except (OSError, IndexError):
        pass
    return True


def _read_pid(path: str, wait_sec: float, poll: float):
    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        try:
            with open(path, encoding='utf-8') as fh:
                text = fh.read().strip()
            if text.isdigit():
                return int(text)
        except OSError:
            pass
        time.sleep(min(poll, 0.5))
    return None


class _ProgressTail:

    def __init__(self, path: str):
        self.path = path
        self.offset = 0

    def new_events(self) -> int:
        try:
            with open(self.path, 'rb') as fh:
                fh.seek(self.offset)
                chunk = fh.read()
        except OSError:
            return 0
        end = chunk.rfind(b'\n')
        if end < 0:
            return 0
        self.offset += end + 1
        count = 0
        for raw in chunk[:end].split(b'\n'):
            try:
                row = json.loads(raw.decode('utf-8', errors='replace'))
            except ValueError:
                continue
            if isinstance(row, dict) and row.get('event') in PROGRESS_EVENTS:
                count += 1
        return count


def _heartbeat_mtime(directory: str) -> float:
    if not directory:
        return 0.0
    latest = 0.0
    try:
        with os.scandir(directory) as it:
            for entry in it:
                try:
                    latest = max(latest, entry.stat().st_mtime)
                except OSError:
                    continue
    except OSError:
        return 0.0
    return latest


def watch(pidfile: str, progress: str, heartbeat_dir: str, expected: float, stall: float, out: str,
          poll: float = 10.0, pid_wait: float = 60.0, clock=time.monotonic, sleep=time.sleep) -> dict:
    start = clock()
    pid = _read_pid(pidfile, pid_wait, poll)
    if pid is None:
        return {'result': 'no_pid'}
    tail = _ProgressTail(progress)
    last_progress = start
    hb_seen = _heartbeat_mtime(heartbeat_dir)
    events = 0
    while True:
        if not _alive(pid):
            return {'result': 'finished', 'events': events}
        now = clock()
        n = tail.new_events()
        if n:
            events += n
            last_progress = now
        hb = _heartbeat_mtime(heartbeat_dir)
        if hb > hb_seen:
            hb_seen = hb
            last_progress = now
        elapsed, idle = now - start, now - last_progress
        if elapsed >= expected and idle >= stall:
            record = {'reason': 'stalled', 'expected_sec': int(expected), 'stall_sec': int(stall), 'elapsed_sec': int(elapsed),
                      'idle_sec': int(idle), 'progress_events': events, 'stopped_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            try:
                with open(out, 'w', encoding='utf-8') as fh:
                    json.dump(record, fh, ensure_ascii=False)
            except OSError:
                pass
            sys.stdout.write('[수집] 진행이 %d초 동안 없어 수집을 중단합니다 (예상 시간 %d초가 지난 뒤, 진행 이벤트 %d건)\n'
                             % (int(idle), int(expected), events))
            sys.stdout.flush()
            try:
                os.kill(pid, signal.SIGINT)
            except OSError:
                pass
            return dict(record, result='stalled')
        sleep(poll)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--pidfile', required=True, help='감시할 GNU timeout 프로세스의 pid 파일')
    ap.add_argument('--progress', required=True, help='json_only 콜백의 gather_progress.jsonl')
    ap.add_argument('--heartbeat-dir', default='', help='Redfish 모듈 heartbeat 디렉터리 (SE_PROGRESS_DIR)')
    ap.add_argument('--expected', type=float, required=True, help='예상 시간(초) — 이 시간이 지나기 전에는 멈추지 않는다')
    ap.add_argument('--stall', type=float, default=420.0, help='진행이 없는 시간(초)이 이만큼이면 멈춘다')
    ap.add_argument('--out', required=True, help='멈췄을 때 이유를 쓸 JSON 파일')
    ap.add_argument('--poll', type=float, default=10.0)
    ap.add_argument('--pid-wait', type=float, default=60.0)
    a = ap.parse_args(argv)
    try:
        watch(a.pidfile, a.progress, a.heartbeat_dir, a.expected, a.stall, a.out, poll=a.poll, pid_wait=a.pid_wait)
    except Exception as e:
        sys.stderr.write('[gather_watch] 감시 중 오류 — 감시 없이 계속: %s: %s\n' % (type(e).__name__, e))
    return 0


if __name__ == '__main__':
    sys.exit(main())
