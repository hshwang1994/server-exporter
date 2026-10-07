#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from finalize_gather_output import read_jsonl, shape_gate

ALIVE_INTERVAL_SEC = 60
OS_FORKS_MAX = 50
ESXI_FORKS_PER_VCPU = 2
REDFISH_FORKS_PER_VCPU = 4
PRECHECK_STAGES = ('reachable', 'port', 'protocol')
PRECHECK_TASK_PREFIX = 'precheck |'
COMPLETED_RCS = (0, 2, 4, 8)
SIGNAL_RCS = {129: 'HUP', 130: 'INT', 143: 'TERM'}
INFRA_STATES = ('runner_restart', 'runner_oom', 'agent_disconnect')
TERMINAL_STATES = ('completed', 'gather_limit', 'prep_failed', 'failed_run', 'process_lost', 'aborted', 'resume_impossible')
CONFIRMED_EVENTS = ('emitted', 'reconciled')

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
    'ansible_pid': '.gather_ansible_pid',
}
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
    out = {'vmstat': _counter(_read(vmstat), 'oom_kill'), 'cgroup': None, 'cgroup_path': None}
    for line in (_read(self_cgroup) or '').splitlines():
        if line.startswith('0::'):
            rel = line[3:].strip()
            out['cgroup_path'] = rel
            out['cgroup'] = _counter(_read(os.path.join(cgroup_root, rel.lstrip('/'), 'memory.events')), 'oom_kill')
            break
    return out


def oom_observation(start: dict | None, now: dict | None) -> dict | None:
    start = start or {}
    now = now or {}
    obs = {}
    if (start.get('cgroup') is not None and now.get('cgroup') is not None and start.get('cgroup_path') == now.get('cgroup_path')
            and now['cgroup'] > start['cgroup']):
        obs['cgroup'] = {'path': now.get('cgroup_path'), 'delta': now['cgroup'] - start['cgroup']}
    if start.get('vmstat') is not None and now.get('vmstat') is not None and now['vmstat'] > start['vmstat']:
        obs['system'] = {'delta': now['vmstat'] - start['vmstat']}
    return obs or None


def _obs_text(obs: dict | None) -> str:
    parts = []
    if obs and obs.get('cgroup'):
        parts.append(f"이 실행이 속한 cgroup({obs['cgroup']['path']}) oom_kill +{obs['cgroup']['delta']}")
    if obs and obs.get('system'):
        parts.append(f"Runner 전체 oom_kill +{obs['system']['delta']}")
    return ', '.join(parts)


_KLOG_LINE = re.compile(r'^\[\s*(\d+(?:\.\d+)?)\]\s?(.*)$')
_KILLED = re.compile(r'Killed process (\d+) \(([^)]*)\)')
_OOM_KILL = re.compile(r'\boom-kill:.*?\bpid=(\d+)')
_OOM_TASK = re.compile(r'\btask=([^,]*)')


def parse_kernel_oom(text: str | None, since: float | None) -> list:
    kills = {}
    for line in (text or '').splitlines():
        m = _KLOG_LINE.match(line.strip())
        if not m:
            continue
        at = float(m.group(1))
        if since is not None and at <= float(since):
            continue
        msg = m.group(2)
        k = _KILLED.search(msg)
        if k:
            pid, comm = int(k.group(1)), k.group(2)
        else:
            o = _OOM_KILL.search(msg)
            if not o:
                continue
            t = _OOM_TASK.search(msg)
            pid, comm = int(o.group(1)), (t.group(1) if t else '')
        kills.setdefault(pid, {'at': at, 'pid': pid, 'comm': comm})
    return sorted(kills.values(), key=lambda x: x['at'])


def kernel_log_text() -> str | None:
    try:
        out = subprocess.run(['dmesg'], capture_output=True, text=True, errors='replace', timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def kernel_log_mark(text: str | None) -> float | None:
    if text is None:
        return None
    mark = 0.0
    for line in text.splitlines():
        m = _KLOG_LINE.match(line.strip())
        if m:
            mark = max(mark, float(m.group(1)))
    return mark


def kernel_oom_kills(mark: float | None, read=kernel_log_text) -> dict:
    if mark is None:
        return {'readable': False, 'kills': [], 'why': '시도 시작 때 커널 로그를 읽지 못해 기준점이 없음'}
    text = read()
    if text is None:
        return {'readable': False, 'kills': []}
    return {'readable': True, 'kills': parse_kernel_oom(text, mark)}


def _kernel_reader(probes: dict):
    if 'dmesg' in probes:
        return lambda: probes['dmesg']
    return kernel_log_text


def _kernel_state(kernel: dict | None):
    if kernel is None:
        return None
    return 'readable' if kernel.get('readable') else 'unreadable'


def _ansible_pid(ws: Path):
    text = _read(ws / NAMES['ansible_pid'])
    try:
        return int(text.split()[0]) if text and text.split() else None
    except ValueError:
        return None


def run_pids(att: dict, ws: Path) -> dict:
    pids = {}
    try:
        if att.get('pid'):
            pids[int(att['pid'])] = 'run_gather.sh'
    except (TypeError, ValueError):
        pass
    ap = _ansible_pid(ws)
    if ap:
        pids[ap] = 'ansible-playbook'
    return pids


def oom_link(att: dict, ws: Path, kernel: dict | None) -> dict | None:
    if not kernel or not kernel.get('readable'):
        return None
    pids = run_pids(att, ws)
    for k in kernel.get('kills') or []:
        if k.get('pid') in pids:
            return {'pid': k['pid'], 'role': pids[k['pid']], 'comm': k.get('comm') or '', 'at': k.get('at')}
    return None


def _unlinked_note(obs: dict | None, kernel: dict | None) -> str | None:
    if not obs:
        return None
    if kernel is not None and not kernel.get('readable'):
        why = kernel.get('why') or '커널 로그를 읽지 못함'
    else:
        why = '커널 로그에 이 실행의 PID 가 없음'
    return f"OOM 관측({_obs_text(obs)}) — 이 실행과 연결된 근거 없음({why}), 원인 미확인"


def attempt_exec_sec(att: dict, alive_mtime, now: float, boot_changed: bool, btime, interval: int = ALIVE_INTERVAL_SEC) -> int:
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
    vcpu = vcpu if isinstance(vcpu, int) and vcpu >= 1 else 2
    if channel == 'os':
        cap = os_cap if isinstance(os_cap, int) and os_cap >= 1 else OS_FORKS_MAX
    elif channel == 'esxi':
        cap = ESXI_FORKS_PER_VCPU * vcpu
    else:
        cap = REDFISH_FORKS_PER_VCPU * vcpu
    return max(1, min(max(1, hosts), cap))


def fix_tail(path: Path, fragments: Path, now: float) -> bool:
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


def present_hosts(ws: Path, ips: list) -> set:
    accepted = set(ips)
    report = {'truncated_tail': [], 'corrupt_lines': []}
    out = set()
    for _n, _t, obj in read_jsonl(ws / NAMES['output'], report, 'output'):
        if isinstance(obj, dict) and isinstance(obj.get('ip'), str) and obj['ip'] in accepted:
            out.add(obj['ip'])
    return out


def confirmed_hosts(ws: Path, st: dict, ips: list):
    accepted = set(ips)
    out, pre = set(), set()
    report = {'truncated_tail': [], 'corrupt_lines': []}
    for _n, _t, ev in read_jsonl(ws / NAMES['progress'], report, 'progress'):
        if isinstance(ev, dict) and ev.get('event') in CONFIRMED_EVENTS:
            key = ev.get('ip') or ev.get('host')
            if isinstance(key, str) and key in accepted:
                out.add(key)
    for a in st.get('attempts') or []:
        for ip in a.get('completed_ips') or []:
            if ip in accepted:
                out.add(ip)
        for ip in a.get('precheck_failed_ips') or []:
            if ip in accepted:
                pre.add(ip)
    return out, pre


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
    atts = st.get('attempts') or []
    att = atts[-1] if atts else None
    if att is None or att.get('state'):
        return None
    probes = probes or {}
    cur_boot = probes['boot_id'] if 'boot_id' in probes else boot_id()
    btime = probes['btime'] if 'btime' in probes else boot_time()
    boot_changed = bool(att.get('boot_id') and cur_boot and cur_boot != att['boot_id'])
    alive = _mtime(ws / NAMES['alive'])
    sec = attempt_exec_sec(att, alive, now, boot_changed, btime, int(st.get('alive_interval_sec') or ALIVE_INTERVAL_SEC))
    obs = kernel = link = None
    if boot_changed:
        state, evidence = 'runner_restart', f"boot_id {str(att['boot_id'])[:8]} -> {cur_boot[:8]}"
    else:
        obs = oom_observation(att.get('oom_kill_start'), probes['oom'] if 'oom' in probes else oom_counters())
        kernel = probes['kernel'] if 'kernel' in probes else kernel_oom_kills(att.get('kernel_mark'), _kernel_reader(probes))
        link = oom_link(att, ws, kernel)
        note = _unlinked_note(obs, kernel)
        if link:
            state = 'runner_oom'
            evidence = f"커널 OOM 종료 기록: PID {link['pid']}({link['comm'] or '-'})는 이 실행의 {link['role']}, 끝 기록 없이 사라짐"
        elif agent_lost:
            state = 'agent_disconnect'
            evidence = 'Jenkins 가 실행 중 Runner 연결이 끊겼다고 보고했다' + (f'; {note}' if note else '')
        else:
            state, evidence = 'process_lost', note
    if boot_changed:
        source = 'boot'
    elif alive is not None and alive >= int(att['started_epoch']):
        source = 'alive'
    else:
        source = 'start'
    att.update(state=state, evidence=evidence, exec_sec=sec, ran_sec=sec, ended_epoch=None, ended_at=None,
               end_source=source, closed_at=iso(now), timed_out=False, oom_observed=obs, oom_link=link,
               kernel_log=_kernel_state(kernel), ansible_pid=_ansible_pid(ws))
    try:
        channel, ips = load_manifest(ws)
        done, pre = completed_hosts(ws, channel, ips)
        att.update(completed_after=len(done), completed_ips=sorted(done), precheck_failed_ips=sorted(pre))
    except StateError:
        pass
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
    confirmed_out, confirmed_pre = confirmed_hosts(ws, st, ips)
    present = present_hosts(ws, ips)
    lost = sorted(confirmed_out - present, key=ips.index)
    pre_all = (pre_failed | confirmed_pre) - done
    kept = (confirmed_out & present) - done
    pending = [ip for ip in ips if ip not in done and ip not in pre_all and ip not in kept]
    used = exec_used(st)
    limit = max(0, int(gather_max) - used)
    probes = probes or {}
    att = {'n': len(st['attempts']) + 1, 'started_epoch': int(now), 'started_at': iso(now), 'pid': int(pid),
           'boot_id': probes['boot_id'] if 'boot_id' in probes else boot_id(),
           'kernel_mark': probes['kernel_mark'] if 'kernel_mark' in probes else kernel_log_mark(_kernel_reader(probes)()),
           'oom_kill_start': probes['oom'] if 'oom' in probes else oom_counters(),
           'vault_tmp': vault_tmp, 'cp_dir': cp_dir, 'hosts_total': len(ips), 'completed_before': len(done),
           'precheck_failed': len(pre_all), 'pending': len(pending), 'limit_sec': limit,
           'forks': forks_for(channel, len(pending), vcpu, os_cap), 'tail_fixed': fixed}
    if lost:
        att.update(state='resume_impossible', end_source='results_lost', exec_sec=0, ran_sec=0, rc=92, timed_out=False,
                   ended_epoch=int(now), ended_at=iso(now), completed_after=len(done), lost_ips=lost,
                   evidence=(f"결과가 확정됐던 대상 {len(lost)}대의 결과 줄이 작업 폴더에 없다: {', '.join(lost[:10])}"
                             f"{' 외 ' + str(len(lost) - 10) + '대' if len(lost) > 10 else ''}"))
    elif not pending:
        att.update(state='completed', end_source='no_pending', exec_sec=0, ran_sec=0, rc=0, timed_out=False,
                   ended_epoch=int(now), ended_at=iso(now), completed_after=len(done))
    elif limit <= 0:
        att.update(state='gather_limit', end_source='limit_exhausted', exec_sec=0, ran_sec=0, rc=124, timed_out=True,
                   ended_epoch=int(now), ended_at=iso(now), completed_after=len(done))
    else:
        (ws / NAMES['limit_hosts']).write_text(''.join(ip + '\n' for ip in pending), encoding='utf-8')
        _append_progress_marker(ws, now, att['n'], pending)
    try:
        (ws / NAMES['ansible_pid']).unlink()
    except OSError:
        pass
    st['attempts'].append(att)
    save_state(ws, st)
    return {'attempt': att['n'], 'state': att.get('state'), 'pending': len(pending), 'limit': limit, 'forks': att['forks'],
            'hosts_total': len(ips), 'completed': len(done), 'precheck_failed': len(pre_all), 'exec_used': used,
            'resumed': att['n'] > 1, 'closed_previous': (closed or {}).get('state'), 'closed_evidence': (closed or {}).get('evidence'),
            'tail_fixed': fixed, 'limit_file': NAMES['limit_hosts'], 'channel': channel, 'lost': len(lost),
            'evidence': att.get('evidence') or ''}


def classify_end(rc: int, exec_sec: int, limit: int, obs: dict | None = None, link: dict | None = None, kernel: dict | None = None):
    timed_out = rc in (124, 137) and exec_sec >= int(limit or 0)
    if rc in COMPLETED_RCS:
        return 'completed', None, False
    if timed_out:
        return 'gather_limit', None, True
    if rc in (90, 91):
        return 'prep_failed', None, False
    if rc in SIGNAL_RCS or rc == 137:
        sig = SIGNAL_RCS.get(rc, 'KILL')
        if link:
            return ('runner_oom',
                    f"커널 OOM 종료 기록: PID {link['pid']}({link.get('comm') or '-'})는 이 실행의 {link['role']}, 뒤이어 signal {sig}", False)
        note = _unlinked_note(obs, kernel)
        return ('aborted' if rc in SIGNAL_RCS else 'process_lost'), f"signal {sig}" + (f"; {note}" if note else ''), False
    note = (f"OOM 관측({_obs_text(obs)}) — 이 실행은 종료 코드 {rc} 로 스스로 끝나 원인으로 보지 않음") if obs else None
    return 'failed_run', note, False


def end(ws: Path, *, rc: int, ssh_closed: int = 0, now: float | None = None, probes: dict | None = None) -> dict:
    now = time.time() if now is None else now
    st = load_state(ws)
    if not st['attempts']:
        raise StateError('시작 기록(begin)이 없다')
    att = st['attempts'][-1]
    if att.get('state'):
        return att
    probes = probes or {}
    rc = int(rc)
    channel, ips = load_manifest(ws)
    done, pre = completed_hosts(ws, channel, ips)
    exec_sec = max(0, int(now) - int(att['started_epoch']))
    obs = oom_observation(att.get('oom_kill_start'), probes['oom'] if 'oom' in probes else oom_counters())
    kernel = None
    if rc in SIGNAL_RCS or rc == 137:
        kernel = probes['kernel'] if 'kernel' in probes else kernel_oom_kills(att.get('kernel_mark'), _kernel_reader(probes))
    link = oom_link(att, ws, kernel)
    state, evidence, timed_out = classify_end(rc, exec_sec, int(att.get('limit_sec') or 0), obs, link, kernel)
    att.update(state=state, evidence=evidence, timed_out=timed_out, rc=rc, exec_sec=exec_sec, ran_sec=exec_sec,
               ended_epoch=int(now), ended_at=iso(now), end_source=('signal' if rc in SIGNAL_RCS else 'exit'),
               ssh_closed=int(ssh_closed), completed_after=len(done), completed_ips=sorted(done), precheck_failed_ips=sorted(pre),
               oom_observed=obs, oom_link=link, kernel_log=_kernel_state(kernel), ansible_pid=_ansible_pid(ws))
    save_state(ws, st)
    try:
        (ws / NAMES['rc']).write_text(f'{rc}\n', encoding='utf-8')
    except OSError:
        pass
    return att


def lock_is_free(lock_path: Path) -> bool:
    try:
        import fcntl
    except ImportError:
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


def classify(ws: Path, *, agent_lost: bool = False, user_abort: bool = False, now: float | None = None, probes: dict | None = None) -> dict:
    now = time.time() if now is None else now
    if not (ws / NAMES['run']).is_file():
        return {'state': 'not_started', 'attempt': 0}
    st = load_state(ws)
    if not st['attempts']:
        return {'state': 'not_started', 'attempt': 0}
    att = st['attempts'][-1]
    if not att.get('state'):
        if not lock_is_free(ws / NAMES['lock']):
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
    if user_abort and att.get('state') in ('aborted', 'runner_oom', 'process_lost', 'agent_disconnect') and not att.get('user_abort'):
        prev = f"{att.get('state')}: {att.get('evidence')}" if att.get('evidence') else att.get('state')
        att.update(state='aborted', user_abort=True, evidence=f"Jenkins 사용자 취소(파이프라인 확인); 종전 판정 {prev}")
        save_state(ws, st)
    channel, ips = load_manifest(ws)
    done, pre_failed = completed_hosts(ws, channel, ips)
    used = exec_used(st)
    before = int(att.get('completed_before') or 0)
    return {'attempt': att['n'], 'state': att.get('state'), 'evidence': att.get('evidence'), 'rc': att.get('rc'),
            'timed_out': bool(att.get('timed_out')), 'exec_sec': att.get('exec_sec'), 'exec_used': used,
            'limit_left': max(0, int(st.get('gather_max_sec') or 0) - used), 'hosts_total': len(ips), 'completed': len(done),
            'precheck_failed': len(pre_failed), 'pending_left': len(ips) - len(done) - len(pre_failed),
            'progress': len(done) - before, 'infra': att.get('state') in INFRA_STATES, 'end_source': att.get('end_source'),
            'lost': len(att.get('lost_ips') or [])}


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
    c.add_argument('--user-abort', action='store_true')
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
            out = classify(ws, agent_lost=a.agent_lost, user_abort=a.user_abort)
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
