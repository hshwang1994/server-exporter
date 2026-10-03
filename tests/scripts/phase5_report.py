#!/usr/bin/env python3
"""phase5_report.py — Phase 5 (Plan §10-3) 에뮬레이션 결과 요약 / 표 생성.

  summarize --workdir DIR ...   phase5_scale_run.sh 가 남긴 원본 파일(time.txt, mem.json, gather_*.json*, stdout.log,
                                orphans.txt, gather_finalize_report.json)을 읽어 DIR/summary.json 한 개로 요약한다.
  table --glob 'PATTERN'        여러 summary.json 을 읽어 Markdown 표로 찍는다 (증거 문서용).

실측값만 기록한다. p95 같은 통계는 만들지 않는다 — 반복 3회 값을 그대로 둔다.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys


def _read(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return ''


def parse_time_v(text):
    """GNU time -v 출력 -> dict. wall 은 초(float)."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('Elapsed (wall clock) time'):
            val = line.split('): ', 1)[-1].strip()
            parts = val.split(':')
            try:
                secs = 0.0
                for p in parts:
                    secs = secs * 60 + float(p)
                out['wall_s'] = round(secs, 2)
            except ValueError:
                out['wall_raw'] = val
        elif line.startswith('Maximum resident set size'):
            out['max_rss_kb'] = int(line.rsplit(':', 1)[-1])
        elif line.startswith('User time'):
            out['user_s'] = float(line.rsplit(':', 1)[-1])
        elif line.startswith('System time'):
            out['sys_s'] = float(line.rsplit(':', 1)[-1])
        elif line.startswith('Exit status'):
            out['exit_status'] = int(line.rsplit(':', 1)[-1])
        elif line.startswith('Command terminated by signal'):
            out['terminated_by_signal'] = int(line.rsplit(' ', 1)[-1])
        elif line.startswith('Percent of CPU'):
            out['cpu_pct'] = line.rsplit(':', 1)[-1].strip()
    return out


def jsonl_stats(path):
    """JSONL 파일 -> 줄 수 / 유효 JSON 수 / 바이트 / 마지막 줄 절단 여부 + 객체 목록."""
    st = {'exists': os.path.isfile(path), 'bytes': 0, 'lines': 0, 'valid_json': 0, 'invalid': 0,
          'truncated_tail': False}
    objs = []
    if not st['exists']:
        return st, objs
    raw = _read(path)
    st['bytes'] = os.path.getsize(path)
    if not raw:
        return st, objs
    lines = raw.split('\n')
    trailing = raw.endswith('\n')
    if trailing:
        lines = lines[:-1]
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        st['lines'] += 1
        try:
            objs.append(json.loads(line))
            st['valid_json'] += 1
        except ValueError:
            st['invalid'] += 1
            if i == len(lines) - 1 and not trailing:
                st['truncated_tail'] = True
    return st, objs


def envelope_hist(objs):
    codes = collections.Counter()
    stages = collections.Counter()
    statuses = collections.Counter()
    ips = set()
    bad_shape = 0
    for o in objs:
        if not isinstance(o, dict):
            bad_shape += 1
            continue
        ips.add(o.get('ip'))
        statuses[str(o.get('status'))] += 1
        d = o.get('diagnosis') or {}
        codes[str(d.get('failure_code'))] += 1
        stages[str(d.get('failure_stage'))] += 1
        if len(o) != 13:
            bad_shape += 1
    return {'count': len(objs), 'distinct_ips': len(ips), 'status': dict(statuses), 'failure_code': dict(codes),
            'failure_stage': dict(stages), 'not_13_keys': bad_shape}


def summarize(a):
    ws = a.workdir
    tv = parse_time_v(_read(os.path.join(ws, 'time.txt')))
    try:
        mem = json.loads(_read(os.path.join(ws, 'mem.json')) or '{}')
    except ValueError:
        mem = {}
    out_st, out_objs = jsonl_stats(os.path.join(ws, 'gather_output.json'))
    prog_st, prog_objs = jsonl_stats(os.path.join(ws, 'gather_progress.jsonl'))
    cp_st, _ = jsonl_stats(os.path.join(ws, 'gather_checkpoint.jsonl'))
    final_st, final_objs = jsonl_stats(os.path.join(ws, 'gather_final.jsonl'))
    # stdout 에 나간 envelope 수 (호출자가 파싱하는 면) - '{' 로 시작하는 줄만 센다
    stdout_lines = [l for l in _read(os.path.join(ws, 'stdout.log')).split('\n') if l.startswith('{')]
    stdout_valid = 0
    for l in stdout_lines:
        try:
            json.loads(l)
            stdout_valid += 1
        except ValueError:
            pass
    prog_events = collections.Counter(str(e.get('event')) for e in prog_objs if isinstance(e, dict))
    try:
        report = json.loads(_read(os.path.join(ws, 'gather_finalize_report.json')) or '{}')
    except ValueError:
        report = {}
    filled = [o for o in final_objs if isinstance(o, dict)
              and ((o.get('diagnosis') or {}).get('details') or {}).get('finalizer') == 'layer_a']
    orphans = _read(os.path.join(ws, 'orphans.txt'))
    orphan_t0 = orphan_t2 = None          # 이 실행의 PGID 로 남은 프로세스 (권위 있는 고아 판정)
    other_t0 = other_t2 = None            # machine 전체에서 이름이 ansible 류인 프로세스 (다른 세션 포함 - 참고용)
    sections = re.findall(r'== (pgid=\S+|global) t\+(\d)s\n(.*?)\(end\)', orphans, flags=re.S)
    if sections:
        for kind, t, body in sections:
            n = len([l for l in body.split('\n') if l.strip() and l.strip() != '(none)'])
            if kind.startswith('pgid'):
                if t == '0':
                    orphan_t0 = n
                else:
                    orphan_t2 = n
            elif t == '0':
                other_t0 = n
            else:
                other_t2 = n
    else:
        # 구형식(2026-10-03 matrix 실행분): machine 전체 grep 만 있었다 -> other_* 로 분류한다.
        parts = re.split(r'== t\+2s\n', orphans)
        if len(parts) == 2:
            other_t0 = len([l for l in parts[0].split('\n')[1:] if l.strip() and l.strip() != '(none)'])
            other_t2 = len([l for l in parts[1].split('\n') if l.strip() and l.strip() != '(none)'])
    stderr_txt = _read(os.path.join(ws, 'stderr.log'))
    notices = [l for l in stderr_txt.split('\n') if l.startswith('[json_only]')]
    accepted = report.get('accepted')
    invariant_ok = (accepted is not None
                    and accepted == (report.get('kept') or 0) + (report.get('filled') or 0)
                    and final_st['valid_json'] == accepted)
    summary = {
        'label': a.label, 'hosts': a.hosts, 'forks': a.forks, 'budget_sec': a.budget_sec,
        'progress_enabled': bool(a.progress), 'rc': a.rc, 'outcome': a.outcome,
        'wall_s_measured': round(float(a.wall_end) - float(a.wall_start), 2),
        'time_v': tv,
        'mem_tree': {k: mem.get(k) for k in ('peak_sum_rss_kb', 'peak_sum_pss_kb', 'procs_at_peak', 'peak_t_s',
                                               'max_live_procs', 'samples')},
        'output_file': out_st, 'output_envelopes': envelope_hist(out_objs),
        'stdout_envelopes': len(stdout_lines), 'stdout_valid_json': stdout_valid,
        'progress_file': prog_st, 'progress_events': dict(prog_events),
        'checkpoint_file': cp_st,
        'finalize': {'rc': a.finalize_rc, 'wall_s': round(float(a.finalize_end) - float(a.finalize_start), 3),
                     'accepted': accepted, 'kept': report.get('kept'), 'filled': report.get('filled'),
                     'by_origin': report.get('by_origin'), 'dropped': len(report.get('dropped') or []),
                     'conflicts': len(report.get('conflicts') or []),
                     'truncated_tail': len(report.get('truncated_tail') or []),
                     'corrupt_lines': len(report.get('corrupt_lines') or []),
                     'exit_code': report.get('exit_code'), 'invariant_ok': invariant_ok},
        'final_file': final_st, 'filled_envelopes': envelope_hist(filled),
        'orphans_t0': orphan_t0, 'orphans_t2': orphan_t2, 'timeout_pid': a.timeout_pid,
        'other_ansible_procs_t0': other_t0, 'other_ansible_procs_t2': other_t2,
        'stderr_json_only_lines': len(notices), 'stderr_bytes': len(stderr_txt),
    }
    with open(os.path.join(ws, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    brief = {'label': a.label, 'hosts': a.hosts, 'forks': a.forks, 'rc': a.rc, 'outcome': a.outcome,
             'wall_s': summary['wall_s_measured'], 'time_v_wall': tv.get('wall_s'),
             'max_rss_mb': round((tv.get('max_rss_kb') or 0) / 1024, 1),
             'tree_pss_mb': round((mem.get('peak_sum_pss_kb') or 0) / 1024, 1),
             'out_lines': out_st['lines'], 'prog_lines': prog_st['lines'], 'prog_kb': round(prog_st['bytes'] / 1024, 1),
             'cp_lines': cp_st['lines'], 'fin_s': summary['finalize']['wall_s'],
             'kept': report.get('kept'), 'filled': report.get('filled'), 'invariant_ok': invariant_ok,
             'orphans_pgid': [orphan_t0, orphan_t2], 'other_ansible_procs': [other_t0, other_t2]}
    print(json.dumps(brief, ensure_ascii=False))


def table(a):
    rows = []
    for p in sorted(glob.glob(a.glob)):
        try:
            rows.append(json.loads(_read(p)))
        except ValueError:
            continue
    rows.sort(key=lambda r: (r.get('hosts', 0), r.get('forks', 0), str(r.get('label'))))
    hdr = ['label', 'hosts', 'forks', 'progress', 'rc', 'outcome', 'wall(s)', 'maxRSS single(MB)',
           'tree PSS peak(MB)', 'tree RSS peak(MB)', 'procs@peak', 'OUTPUT lines', 'stdout env', 'progress lines',
           'progress KB', 'checkpoint lines', 'finalize(s)', 'kept', 'filled', 'req==res', 'orphans(pgid) t0/t2',
           'other ansible procs t0/t2']
    print('| ' + ' | '.join(hdr) + ' |')
    print('|' + '---|' * len(hdr))
    for r in rows:
        tv = r.get('time_v') or {}
        mt = r.get('mem_tree') or {}
        fz = r.get('finalize') or {}
        cells = [
            r.get('label'), r.get('hosts'), r.get('forks'), 'on' if r.get('progress_enabled') else 'off', r.get('rc'),
            r.get('outcome'), tv.get('wall_s', r.get('wall_s_measured')),
            round((tv.get('max_rss_kb') or 0) / 1024, 1), round((mt.get('peak_sum_pss_kb') or 0) / 1024, 1),
            round((mt.get('peak_sum_rss_kb') or 0) / 1024, 1), mt.get('procs_at_peak'),
            (r.get('output_file') or {}).get('lines'), r.get('stdout_envelopes'),
            (r.get('progress_file') or {}).get('lines'), round(((r.get('progress_file') or {}).get('bytes') or 0) / 1024, 1),
            (r.get('checkpoint_file') or {}).get('lines'), fz.get('wall_s'), fz.get('kept'), fz.get('filled'),
            'yes' if fz.get('invariant_ok') else 'NO', '%s/%s' % (r.get('orphans_t0'), r.get('orphans_t2')),
            '%s/%s' % (r.get('other_ansible_procs_t0'), r.get('other_ansible_procs_t2')),
        ]
        print('| ' + ' | '.join(str(x) for x in cells) + ' |')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('summarize')
    s.add_argument('--workdir', required=True)
    s.add_argument('--hosts', type=int, required=True)
    s.add_argument('--forks', type=int, required=True)
    s.add_argument('--budget-sec', type=int, required=True)
    s.add_argument('--progress', type=int, required=True)
    s.add_argument('--label', default='')
    s.add_argument('--rc', type=int, required=True)
    s.add_argument('--outcome', required=True)
    s.add_argument('--wall-start', required=True)
    s.add_argument('--wall-end', required=True)
    s.add_argument('--finalize-rc', type=int, required=True)
    s.add_argument('--finalize-start', required=True)
    s.add_argument('--finalize-end', required=True)
    s.add_argument('--timeout-pid', type=int, default=0)
    s.set_defaults(fn=summarize)
    t = sub.add_parser('table')
    t.add_argument('--glob', required=True)
    t.set_defaults(fn=table)
    a = ap.parse_args(argv)
    a.fn(a)
    return 0


if __name__ == '__main__':
    sys.exit(main())
