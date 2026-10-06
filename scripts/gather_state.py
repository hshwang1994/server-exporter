#!/usr/bin/env python3
"""gather_state.py — 수집 실행 기록 · 재개 대상 · 누적 실행 시간 (2026-10-06, 9차).

scripts/run_gather.sh 가 ansible 실행 앞뒤로 부르고(begin · end), Jenkinsfile_portal 이 시도가 끝날 때마다 판정(classify)을 읽는다.
같은 빌드 · 같은 작업 폴더 안에서만 쓴다. 다른 Runner 로 상태를 옮기지 않고, 새 저장소를 만들지 않는다.

begin     · 이전 시도가 끝 기록 없이 사라졌으면 근거로 닫는다 — Runner 재부팅(boot_id) · OOM(카운터 증가) · 연결 끊김(Jenkins 보고)
            · 근거가 없으면 원인 미확인(process_lost). 그 시도가 남긴 vault 임시 파일 · SSH 다중화 폴더를 지운다.
          · 잘린 마지막 줄(개행 없음)을 gather_tail_fragments.jsonl 로 옮긴다 — 다음 시도가 이어 쓸 때 두 줄이 같이 깨지지 않게.
          · 남은 대상 = 접수 IP − 형태 검사를 통과한 결과 줄이 있는 IP − Precheck 실패가 관측된 IP(다시 수집하지 않는다).
          · 이번 실행 한계 = 수집 실행 한계 − 누적 실행 시간. 동시 실행 수는 채널 상한 그대로다(메모리 계산 없음).
          · --limit 파일 · 시도 표식(gather_progress.jsonl 의 attempt 사건) · 시도 기록(gather_run.json)을 쓴다.
end       이번 시도의 끝 시각 · 종료 코드 · 한계 도달 · 원인(근거가 있을 때만 OOM)을 적는다.
classify  마지막 시도의 판정을 JSON 한 줄로 낸다. 끝 기록이 없고 잠금이 풀렸으면(프로세스가 사라졌으면) 그 자리에서 닫는다.
count     결과가 확정된 대상 수 / 접수 수 (진행 표시용).

실행 시간은 이 Runner 의 시계로 잰 ansible 실행 시간의 합이다 — 동시에 수집한 Host 시간을 겹쳐 세지 않는다. 끝 기록 없이 사라진 시도는
마지막 생존 표시(.gather_alive 의 수정 시각) + 표시 주기(60초)까지 센다. 그래서 비정상 종료가 반복돼도 누적이 줄지 않는다
(한 번에 최대 60초를 더 셀 수는 있다). Runner 가 다시 부팅했으면 새 부팅 시각을 넘지 않게 자른다.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import stat
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from finalize_gather_output import read_jsonl, shape_gate  # noqa: E402 - 같은 폴더의 Layer A 판정을 그대로 쓴다(복제 없음)

ALIVE_INTERVAL_SEC = 60
OS_FORKS_MAX = 50
ESXI_FORKS_PER_VCPU = 2
REDFISH_FORKS_PER_VCPU = 4
PRECHECK_STAGES = ('reachable', 'port', 'protocol')
PRECHECK_TASK_PREFIX = 'precheck |'
COMPLETED_RCS = (0, 2, 4, 8)
SIGNAL_RCS = {129: 'HUP', 130: 'INT', 143: 'TERM'}
INFRA_STATES = ('runner_restart', 'runner_oom', 'agent_disconnect')
TERMINAL_STATES = ('completed', 'gather_limit', 'prep_failed', 'failed_run', 'process_lost', 'aborted')

NAMES = {
    'manifest': 'gather_manifest.json',
    'output': 'gather_output.json',
    'checkpoint': 'gather_checkpoint.jsonl',
    'progress': 'gather_progress.jsonl',
    'run': 'gather_run.json',
    'rc': 'gather_rc.txt',
    'fragments': 'gather_tail_fragments.jsonl',
    'alive': '.gather_alive',
    'limit_hosts': '.gather_limit_hosts',
    'lock': '.gather.lock',
}
# run_gather.sh 가 mktemp 로 만드는 이 실행만의 임시 경로 — 끝 기록 없이 사라진 시도의 것만 지운다(이름 · 소유자를 확인한다)
STALE_PATTERNS = {'vault_tmp': re.compile(r'^/tmp/se_vault\.[A-Za-z0-9]{8,}$'), 'cp_dir': re.compile(r'^/tmp/se_cp\.[A-Za-z0-9]{6,}$')}


class StateError(Exception):
    pass


def iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


def _read(path) -> str | None:
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None


def boot_id(path='/proc/sys/kernel/random/boot_id') -> str | None:
    text = _read(path)
    return text.strip() if text and text.strip() else None


def boot_time(path='/proc/stat') -> int | None:
    for line in (_read(path) or '').splitlines():
        if line.startswith('btime '):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def _counter(text: str | None, name: str) -> int | None:
    for line in (text or '').splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == name:
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def oom_counters(vmstat='/proc/vmstat', self_cgroup='/proc/self/cgroup', cgroup_root='/sys/fs/cgroup') -> dict:
    """OOM 종료 횟수 — 이 프로세스가 속한 cgroup(v2 memory.events, Agent 세션 범위)과 이 Runner 전체(/proc/vmstat)."""
    out = {'vmstat': _counter(_read(vmstat), 'oom_kill'), 'cgroup': None, 'cgroup_path': None}
    for line in (_read(self_cgroup) or '').splitlines():
        if line.startswith('0::'):
            rel = line[3:].strip()
            out['cgroup_path'] = rel
            out['cgroup'] = _counter(_read(os.path.join(cgroup_root, rel.lstrip('/'), 'memory.events')), 'oom_kill')
            break
    return out


def oom_evidence(start: dict | None, now: dict | None) -> str | None:
    """시작과 지금 사이에 OOM 종료가 기록됐는가. 같은 부팅 안에서만 비교한다(재부팅은 따로 판정).

    cgroup v2 의 memory.events oom_kill 은 그 cgroup(하위 포함)에 속한 프로세스가 어떤 OOM 으로든 끝난 횟수다. 두 시점 모두 같은 cgroup 의 값을
    읽었으면 그것만 본다 — 이 Runner 의 다른 프로세스가 끝난 것을 이 수집의 근거로 쓰지 않는다. cgroup 값을 읽지 못했을 때만 Runner 전체
    (/proc/vmstat)를 본다.
    """
    start = start or {}
    now = now or {}
    if start.get('cgroup') is not None and now.get('cgroup') is not None and start.get('cgroup_path') == now.get('cgroup_path'):
        if now['cgroup'] > start['cgroup']:
            return f"Agent cgroup {now.get('cgroup_path')} memory.events oom_kill +{now['cgroup'] - start['cgroup']}"
        return None
    if start.get('vmstat') is not None and now.get('vmstat') is not None and now['vmstat'] > start['vmstat']:
        return f"/proc/vmstat oom_kill +{now['vmstat'] - start['vmstat']} (이 Runner 전체)"
    return None


def attempt_exec_sec(att: dict, alive_mtime, now: float, boot_changed: bool, btime, interval: int = ALIVE_INTERVAL_SEC) -> int:
    """시도 하나의 실행 시간(초). 믿을 수 있는 끝 시각(ended_epoch)이 있으면 그 값을 쓰고, 없으면 마지막 생존 표시 + 표시 주기까지 센다.

    생존 표시를 한 번도 못 남겼으면 시작 + 표시 주기. Runner 가 다시 부팅했으면 새 부팅 시각, 그리고 지금을 넘지 않는다.
    끝난 순간이 표시 주기 안 어디였든 계산값 ≥ 실제 실행 시간이다 — 비정상 종료가 반복돼도 누적 실행 한계를 덜 세지 않는다.
    """
    started = int(att['started_epoch'])
    if att.get('ended_epoch') is not None:
        return max(0, int(att['ended_epoch']) - started)
    base = started
    if alive_mtime is not None and alive_mtime >= started:
        base = int(alive_mtime)
    end = base + int(interval)
    if boot_changed and btime:
        end = min(end, int(btime))
    end = min(end, int(now))
    return max(0, end - started)


def forks_for(channel: str, hosts: int, vcpu, os_cap) -> int:
    """동시 실행 수 — 채널 상한 그대로다(OS 50 또는 Runner 노드 환경변수 SE_FORKS_CAP_OS, ESXi 2×vCPU, Redfish 4×vCPU). 메모리를 보지 않는다."""
    vcpu = vcpu if isinstance(vcpu, int) and vcpu >= 1 else 2
    if channel == 'os':
        cap = os_cap if isinstance(os_cap, int) and os_cap >= 1 else OS_FORKS_MAX
    elif channel == 'esxi':
        cap = ESXI_FORKS_PER_VCPU * vcpu
    else:
        cap = REDFISH_FORKS_PER_VCPU * vcpu
    return max(1, min(max(1, hosts), cap))


def fix_tail(path: Path, fragments: Path, now: float) -> bool:
    """개행 없이 끝난 마지막 줄(쓰는 도중 끊긴 줄)을 fragments 로 옮기고 원본을 마지막 개행까지 자른다. 옮겼으면 True."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return False
    if not data or data.endswith(b'\n'):
        return False
    cut = data.rfind(b'\n') + 1
    rec = {'file': path.name, 'at': iso(now), 'bytes': len(data) - cut, 'fragment': data[cut:].decode('utf-8', 'replace')}
    with open(fragments, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
        fh.flush()
        os.fsync(fh.fileno())
    with open(path, 'r+b') as fh:
        fh.truncate(cut)
        fh.flush()
        os.fsync(fh.fileno())
    return True


def load_manifest(ws: Path):
    try:
        m = json.loads((ws / NAMES['manifest']).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise StateError(f'manifest 를 읽지 못했다: {e}') from e
    channel = m.get('channel') if isinstance(m, dict) else None
    ips = [str(x) for x in (m.get('ips') or [])] if isinstance(m, dict) else []
    if channel not in ('os', 'esxi', 'redfish') or not ips:
        raise StateError(f'manifest 내용 불량: channel={channel!r} ips={len(ips)}')
    return channel, ips


def completed_hosts(ws: Path, channel: str, ips: list):
    """(결과 줄이 있는 IP 집합, Precheck 실패가 관측된 IP 집합 — 결과 줄은 아직 없는 것). 판정은 Layer A 의 shape_gate 그대로."""
    accepted = set(ips)
    report = {'truncated_tail': [], 'corrupt_lines': []}
    done = set()
    for _n, _t, obj in read_jsonl(ws / NAMES['output'], report, 'output'):
        if shape_gate(obj, channel, accepted) is None:
            done.add(obj['ip'])
    pre = {}
    for _n, _t, ev in read_jsonl(ws / NAMES['progress'], report, 'progress'):
        if not isinstance(ev, dict):
            continue
        if ev.get('event') == 'attempt' and isinstance(ev.get('hosts'), list):
            for h in ev['hosts']:
                if isinstance(h, str):
                    pre.pop(h, None)
            continue
        key = ev.get('ip') or ev.get('host')
        if not isinstance(key, str) or key not in accepted:
            continue
        if ev.get('event') == 'precheck' and str(ev.get('task') or '').startswith(PRECHECK_TASK_PREFIX):
            diag = ev.get('diagnosis') if isinstance(ev.get('diagnosis'), dict) else {}
            pre[key] = diag.get('failure_stage') in PRECHECK_STAGES
    precheck_failed = {ip for ip, failed in pre.items() if failed and ip not in done}
    return done, precheck_failed


def new_state(gather_max: int) -> dict:
    return {'schema': 2, 'gather_max_sec': int(gather_max), 'alive_interval_sec': ALIVE_INTERVAL_SEC, 'attempts': []}


def load_state(ws: Path, gather_max: int | None = None) -> dict:
    text = _read(ws / NAMES['run'])
    if text is None or not text.strip():
        return new_state(gather_max or 0)
    try:
        st = json.loads(text)
    except ValueError as e:
        raise StateError(f'gather_run.json 을 읽지 못했다: {e}') from e
    if not isinstance(st, dict) or st.get('schema') != 2 or not isinstance(st.get('attempts'), list):
        raise StateError('gather_run.json 이 이 형식(schema 2)이 아니다')
    if gather_max:
        st['gather_max_sec'] = int(gather_max)
    return st


def exec_used(st: dict) -> int:
    return sum(int(a.get('exec_sec') or 0) for a in st.get('attempts', []) if a.get('state'))


def _legacy_fields(st: dict) -> None:
    """종전 형식의 키 — Jenkinsfile · Harness · 증거 수집기가 읽는다. ran_sec 은 누적 실행 시간이다."""
    atts = st.get('attempts') or []
    if not atts:
        return
    first, last = atts[0], atts[-1]
    st['exec_used_sec'] = exec_used(st)
    st['started_at'] = first.get('started_at')
    st['ended_at'] = last.get('ended_at') or last.get('closed_at')
    st['ran_sec'] = st['exec_used_sec']
    st['limit_sec'] = last.get('limit_sec')
    st['rc'] = last.get('rc')
    st['timed_out'] = bool(last.get('timed_out'))
    st['ssh_closed'] = int(last.get('ssh_closed') or 0)
    st['state'] = last.get('state')
    st['attempt_count'] = len(atts)


def save_state(ws: Path, st: dict) -> None:
    _legacy_fields(st)
    path = ws / NAMES['run']
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(st, ensure_ascii=False) + '\n')
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _mtime(path: Path):
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return None


def remove_stale_paths(att: dict) -> list:
    """끝 기록 없이 사라진 시도가 남긴 이 실행만의 임시 경로를 지운다 — 이름 규칙과 소유자가 맞는 것만."""
    removed = []
    uid = os.getuid() if hasattr(os, 'getuid') else None
    for key, pattern in STALE_PATTERNS.items():
        p = att.get(key)
        if not isinstance(p, str) or not pattern.match(p):
            continue
        try:
            st_ = os.lstat(p)
        except OSError:
            continue
        if uid is not None and st_.st_uid != uid:
            continue
        try:
            if stat.S_ISDIR(st_.st_mode) and not stat.S_ISLNK(st_.st_mode):
                shutil.rmtree(p)
            else:
                os.unlink(p)
            removed.append(key)
        except OSError:
            pass
    return removed


def close_open_attempt(st: dict, ws: Path, now: float, agent_lost: bool = False, probes: dict | None = None) -> dict | None:
    """끝 기록 없이 사라진 마지막 시도를 근거로 닫는다. probes 는 시험이 넣는 관측값(boot_id · btime · oom)이고 운영은 실제로 읽는다."""
    atts = st.get('attempts') or []
    att = atts[-1] if atts else None
    if att is None or att.get('state'):
        return None
    probes = probes or {}
    cur_boot = probes['boot_id'] if 'boot_id' in probes else boot_id()
    btime = probes['btime'] if 'btime' in probes else boot_time()
    oom_now = probes['oom'] if 'oom' in probes else oom_counters()
    boot_changed = bool(att.get('boot_id') and cur_boot and cur_boot != att['boot_id'])
    alive = _mtime(ws / NAMES['alive'])
    sec = attempt_exec_sec(att, alive, now, boot_changed, btime, int(st.get('alive_interval_sec') or ALIVE_INTERVAL_SEC))
    if boot_changed:
        state, evidence = 'runner_restart', f"boot_id {str(att['boot_id'])[:8]} -> {cur_boot[:8]}"
    else:
        evidence = oom_evidence(att.get('oom_kill_start'), oom_now)
        if evidence:
            state = 'runner_oom'
        elif agent_lost:
            state, evidence = 'agent_disconnect', 'Jenkins 가 실행 중 Runner 연결이 끊겼다고 보고했다'
        else:
            state, evidence = 'process_lost', None
    if boot_changed:
        source = 'boot'
    elif alive is not None and alive >= int(att['started_epoch']):
        source = 'alive'
    else:
        source = 'start'
    att.update(state=state, evidence=evidence, exec_sec=sec, ran_sec=sec, ended_epoch=None, ended_at=None,
               end_source=source, closed_at=iso(now), timed_out=False)
    att['stale_removed'] = remove_stale_paths(att)
    return att


def _append_progress_marker(ws: Path, now: float, n: int, hosts: list) -> None:
    rec = {'ts': datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat(timespec='seconds'),
           'host': None, 'ip': None, 'event': 'attempt', 'task': None, 'detail': f'attempt {n}', 'n': n, 'hosts': hosts}
    with open(ws / NAMES['progress'], 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')


def begin(ws: Path, *, pid: int, vault_tmp: str, cp_dir: str, gather_max: int, vcpu, os_cap, prev_agent_lost: bool,
          now: float | None = None, probes: dict | None = None) -> dict:
    now = time.time() if now is None else now
    channel, ips = load_manifest(ws)
    st = load_state(ws, gather_max)
    closed = close_open_attempt(st, ws, now, prev_agent_lost, probes)
    if prev_agent_lost and st['attempts']:
        st['attempts'][-1]['agent_lost'] = True
    fixed = [NAMES[key] for key in ('output', 'checkpoint', 'progress') if fix_tail(ws / NAMES[key], ws / NAMES['fragments'], now)]
    done, pre_failed = completed_hosts(ws, channel, ips)
    pending = [ip for ip in ips if ip not in done and ip not in pre_failed]
    used = exec_used(st)
    limit = max(0, int(gather_max) - used)
    probes = probes or {}
    att = {'n': len(st['attempts']) + 1, 'started_epoch': int(now), 'started_at': iso(now), 'pid': int(pid),
           'boot_id': probes['boot_id'] if 'boot_id' in probes else boot_id(),
           'oom_kill_start': probes['oom'] if 'oom' in probes else oom_counters(),
           'vault_tmp': vault_tmp, 'cp_dir': cp_dir, 'hosts_total': len(ips), 'completed_before': len(done),
           'precheck_failed': len(pre_failed), 'pending': len(pending), 'limit_sec': limit,
           'forks': forks_for(channel, len(pending), vcpu, os_cap), 'tail_fixed': fixed}
    if not pending:
        att.update(state='completed', end_source='no_pending', exec_sec=0, ran_sec=0, rc=0, timed_out=False,
                   ended_epoch=int(now), ended_at=iso(now), completed_after=len(done))
    elif limit <= 0:
        att.update(state='gather_limit', end_source='limit_exhausted', exec_sec=0, ran_sec=0, rc=124, timed_out=True,
                   ended_epoch=int(now), ended_at=iso(now), completed_after=len(done))
    else:
        (ws / NAMES['limit_hosts']).write_text(''.join(ip + '\n' for ip in pending), encoding='utf-8')
        _append_progress_marker(ws, now, att['n'], pending)
    st['attempts'].append(att)
    save_state(ws, st)
    return {'attempt': att['n'], 'state': att.get('state'), 'pending': len(pending), 'limit': limit, 'forks': att['forks'],
            'hosts_total': len(ips), 'completed': len(done), 'precheck_failed': len(pre_failed), 'exec_used': used,
            'resumed': att['n'] > 1, 'closed_previous': (closed or {}).get('state'), 'closed_evidence': (closed or {}).get('evidence'),
            'tail_fixed': fixed, 'limit_file': NAMES['limit_hosts'], 'channel': channel}


def classify_end(rc: int, exec_sec: int, limit: int, oom_start: dict | None, oom_now: dict | None):
    """끝 기록을 남긴 시도의 판정 — (state, evidence, timed_out). OOM 은 카운터 증가 근거가 있을 때만이다."""
    timed_out = rc in (124, 137) and exec_sec >= int(limit or 0)
    if rc in COMPLETED_RCS:
        return 'completed', None, False
    if timed_out:
        return 'gather_limit', None, True
    if rc in (90, 91):
        return 'prep_failed', None, False
    if rc in SIGNAL_RCS:
        return 'aborted', f'signal {SIGNAL_RCS[rc]}', False
    evidence = oom_evidence(oom_start, oom_now)
    if evidence:
        return 'runner_oom', evidence, False
    return ('process_lost' if rc == 137 else 'failed_run'), None, False


def end(ws: Path, *, rc: int, ssh_closed: int = 0, now: float | None = None, probes: dict | None = None) -> dict:
    now = time.time() if now is None else now
    st = load_state(ws)
    if not st['attempts']:
        raise StateError('시작 기록(begin)이 없다')
    att = st['attempts'][-1]
    if att.get('state'):
        return att
    probes = probes or {}
    channel, ips = load_manifest(ws)
    done, _pre = completed_hosts(ws, channel, ips)
    exec_sec = max(0, int(now) - int(att['started_epoch']))
    state, evidence, timed_out = classify_end(int(rc), exec_sec, int(att.get('limit_sec') or 0), att.get('oom_kill_start'),
                                              probes['oom'] if 'oom' in probes else oom_counters())
    att.update(state=state, evidence=evidence, timed_out=timed_out, rc=int(rc), exec_sec=exec_sec, ran_sec=exec_sec,
               ended_epoch=int(now), ended_at=iso(now), end_source=('signal' if int(rc) in SIGNAL_RCS else 'exit'),
               ssh_closed=int(ssh_closed), completed_after=len(done))
    save_state(ws, st)
    try:
        (ws / NAMES['rc']).write_text(f'{int(rc)}\n', encoding='utf-8')
    except OSError:
        pass
    return att


def lock_is_free(lock_path: Path) -> bool:
    """잠금이 풀렸는가 — 이 빌드의 수집 프로세스(run_gather.sh · ansible)가 모두 끝났는가."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Runner 는 Linux 다
        return True
    try:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return True
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def classify(ws: Path, *, agent_lost: bool = False, now: float | None = None, probes: dict | None = None) -> dict:
    now = time.time() if now is None else now
    if not (ws / NAMES['run']).is_file():
        return {'state': 'not_started', 'attempt': 0}
    st = load_state(ws)
    if not st['attempts']:
        return {'state': 'not_started', 'attempt': 0}
    att = st['attempts'][-1]
    if not att.get('state'):
        if not lock_is_free(ws / NAMES['lock']):
            # 이 시도의 수집 프로세스가 아직 돈다(Agent 연결만 끊겼던 동안 계속 돈 실행) — 닫지 않고, 지금까지의 진행만 센다(읽기 전용)
            channel, ips = load_manifest(ws)
            done, pre_failed = completed_hosts(ws, channel, ips)
            before = int(att.get('completed_before') or 0)
            return {'attempt': att['n'], 'state': 'running', 'infra': True, 'hosts_total': len(ips), 'completed': len(done),
                    'precheck_failed': len(pre_failed), 'pending_left': len(ips) - len(done) - len(pre_failed), 'progress': len(done) - before}
        close_open_attempt(st, ws, now, agent_lost, probes)
        save_state(ws, st)
    elif agent_lost and not att.get('agent_lost'):
        att['agent_lost'] = True
        save_state(ws, st)
    channel, ips = load_manifest(ws)
    done, pre_failed = completed_hosts(ws, channel, ips)
    used = exec_used(st)
    before = int(att.get('completed_before') or 0)
    return {'attempt': att['n'], 'state': att.get('state'), 'evidence': att.get('evidence'), 'rc': att.get('rc'),
            'timed_out': bool(att.get('timed_out')), 'exec_sec': att.get('exec_sec'), 'exec_used': used,
            'limit_left': max(0, int(st.get('gather_max_sec') or 0) - used), 'hosts_total': len(ips), 'completed': len(done),
            'precheck_failed': len(pre_failed), 'pending_left': len(ips) - len(done) - len(pre_failed),
            'progress': len(done) - before, 'infra': att.get('state') in INFRA_STATES, 'end_source': att.get('end_source')}


def count(ws: Path) -> str:
    channel, ips = load_manifest(ws)
    done, pre_failed = completed_hosts(ws, channel, ips)
    return f'{len(done) + len(pre_failed)}/{len(ips)}'


def _int_or_none(v):
    try:
        return int(v) if str(v).strip() else None
    except (TypeError, ValueError):
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='수집 실행 기록 · 재개 대상 · 누적 실행 시간')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('begin')
    b.add_argument('--ws', required=True)
    b.add_argument('--pid', type=int, required=True)
    b.add_argument('--vault-tmp', default='')
    b.add_argument('--cp-dir', default='')
    b.add_argument('--gather-max', type=int, required=True)
    b.add_argument('--vcpu', default='')
    b.add_argument('--os-forks-cap', default='')
    b.add_argument('--prev-agent-lost', action='store_true')
    e = sub.add_parser('end')
    e.add_argument('--ws', required=True)
    e.add_argument('--rc', type=int, required=True)
    e.add_argument('--ssh-closed', type=int, default=0)
    c = sub.add_parser('classify')
    c.add_argument('--ws', required=True)
    c.add_argument('--agent-lost', action='store_true')
    n = sub.add_parser('count')
    n.add_argument('--ws', required=True)
    a = ap.parse_args(argv)
    ws = Path(a.ws)
    try:
        if a.cmd == 'begin':
            out = begin(ws, pid=a.pid, vault_tmp=a.vault_tmp, cp_dir=a.cp_dir, gather_max=a.gather_max,
                        vcpu=_int_or_none(a.vcpu) or 2, os_cap=_int_or_none(a.os_forks_cap), prev_agent_lost=a.prev_agent_lost)
        elif a.cmd == 'end':
            out = end(ws, rc=a.rc, ssh_closed=a.ssh_closed)
        elif a.cmd == 'classify':
            out = classify(ws, agent_lost=a.agent_lost)
        else:
            sys.stdout.write(count(ws) + '\n')
            return 0
    except StateError as exc:
        sys.stderr.write(f'[수집 기록] {exc}\n')
        return 2
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
