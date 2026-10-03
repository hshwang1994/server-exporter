#!/usr/bin/env python3
"""phase5_finalize_bench.py — Phase 5 (Plan §10-3) Layer A finalizer 마이크로벤치: 1000 host 입력 파일을 합성하고 실행 시간을 잰다.

실장비도 ansible 도 쓰지 않는다. tests/evidence/2026-09-03-live/*.json 의 **실제 envelope 1개**를 템플릿으로 ip 만 바꿔
gather_output.json(OUTPUT 줄) / gather_checkpoint.jsonl / gather_progress.jsonl / gather_manifest.json 을 만든 뒤
scripts/finalize_gather_output.py 를 반복 실행해 wall-clock 과 보고(accepted/kept/filled)를 기록한다.

시나리오 (host 수 N 고정):
  all_output   N 개 모두 OUTPUT 줄 보유 (정상 완료 — shape gate / 파싱 처리량)
  mixed        70% OUTPUT · 15% CHECKPOINT 만 · 15% progress(precheck 진단) 만  (중단 빌드의 전형)
  no_output    OUTPUT 0 · 전원 progress(precheck 진단) 만 (최악 — 전원 synthetic)

usage: phase5_finalize_bench.py --repo-root DIR --workdir DIR --template-success FILE --template-failed FILE
                                [--hosts 1000] [--repeat 3] [--scenarios all_output,mixed,no_output]
IP 는 127.0.<1..>.<1..250> 합성값이다 (연결 없음).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time


def _ips(n):
    return [f"127.0.{1 + i // 250}.{1 + i % 250}" for i in range(n)]


def _load_template(path):
    with open(path, encoding='utf-8') as fh:
        env = json.load(fh)
    if isinstance(env, list):
        env = env[0]
    assert isinstance(env, dict) and len(env) == 13, f'template {path} is not a 13-key envelope'
    return env


def _retarget(env, ip):
    e = json.loads(json.dumps(env))
    e['ip'] = ip
    corr = e.get('correlation')
    if isinstance(corr, dict):
        corr['host_ip'] = ip
    return e


def _progress_rows(ip, events, diag):
    ts = '2026-10-03T00:00:00+00:00'
    rows = [{'ts': ts, 'host': ip, 'ip': ip, 'event': 'first_seen', 'task': None, 'detail': None}]
    for ev in events:
        row = {'ts': ts, 'host': ip, 'ip': ip, 'event': ev, 'task': f'task for {ev}', 'detail': None}
        if ev == 'precheck':
            row['diagnosis'] = diag
        rows.append(row)
    return rows


def synthesize(ws, scenario, ips, success_env, failed_env):
    os.makedirs(ws, exist_ok=True)
    for name in ('gather_output.json', 'gather_checkpoint.jsonl', 'gather_progress.jsonl', 'gather_final.jsonl',
                 'gather_finalize_report.json'):
        try:
            os.remove(os.path.join(ws, name))
        except FileNotFoundError:
            pass
    manifest = {'schema': 1, 'build': {'job': 'phase5-finalize-bench', 'number': scenario, 'url': None},
                'channel': success_env['target_type'], 'request': {'loc': 'x'}, 'ips': ips}
    with open(os.path.join(ws, 'gather_manifest.json'), 'w', encoding='utf-8') as fh:
        fh.write(json.dumps(manifest) + '\n')
    with open(os.path.join(ws, 'gather_rc.txt'), 'w', encoding='utf-8') as fh:
        fh.write('124\n' if scenario != 'all_output' else '0\n')
    n = len(ips)
    diag = failed_env['diagnosis']
    counts = {'output': 0, 'checkpoint': 0, 'progress_only': 0}
    sep = (',', ':')
    with open(os.path.join(ws, 'gather_output.json'), 'w', encoding='utf-8') as fo, \
            open(os.path.join(ws, 'gather_checkpoint.jsonl'), 'w', encoding='utf-8') as fc, \
            open(os.path.join(ws, 'gather_progress.jsonl'), 'w', encoding='utf-8') as fp:
        fp.write(json.dumps({'ts': 'x', 'host': None, 'ip': None, 'event': 'inventory', 'task': 'play', 'detail': None,
                             'hosts': ips}, separators=sep) + '\n')
        for i, ip in enumerate(ips):
            if scenario == 'all_output':
                kind = 'output'
            elif scenario == 'no_output':
                kind = 'progress_only'
            else:
                frac = i / n
                kind = 'output' if frac < 0.70 else ('checkpoint' if frac < 0.85 else 'progress_only')
            counts[kind] += 1
            if kind == 'output':
                fo.write(json.dumps(_retarget(success_env, ip), ensure_ascii=False, separators=sep) + '\n')
                rows = _progress_rows(ip, ['precheck', 'auth_proven', 'checkpoint', 'emitted'], None)
                rows[1]['diagnosis'] = success_env['diagnosis']
            elif kind == 'checkpoint':
                fc.write(json.dumps(_retarget(success_env, ip), ensure_ascii=False, separators=sep) + '\n')
                rows = _progress_rows(ip, ['precheck', 'auth_proven', 'checkpoint', 'addon_started'], success_env['diagnosis'])
            else:
                rows = _progress_rows(ip, ['precheck'], diag)
            for r in rows:
                fp.write(json.dumps(r, ensure_ascii=False, separators=sep) + '\n')
    sizes = {name: os.path.getsize(os.path.join(ws, name)) for name in
             ('gather_output.json', 'gather_checkpoint.jsonl', 'gather_progress.jsonl', 'gather_manifest.json')}
    return counts, sizes


def run_finalize(repo_root, ws, outcome):
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, os.path.join(repo_root, 'scripts', 'finalize_gather_output.py'),
                           '--workspace', ws, '--repo-root', repo_root, '--outcome', outcome],
                          capture_output=True, text=True)
    wall = time.perf_counter() - t0
    with open(os.path.join(ws, 'gather_finalize_report.json'), encoding='utf-8') as fh:
        report = json.load(fh)
    final_lines = sum(1 for l in open(os.path.join(ws, 'gather_final.jsonl'), encoding='utf-8') if l.strip())
    return {'wall_s': round(wall, 3), 'rc': proc.returncode, 'accepted': report.get('accepted'),
            'kept': report.get('kept'), 'filled': report.get('filled'), 'by_origin': report.get('by_origin'),
            'dropped': len(report.get('dropped') or []), 'exit_code': report.get('exit_code'),
            'final_lines': final_lines, 'final_bytes': os.path.getsize(os.path.join(ws, 'gather_final.jsonl')),
            'stderr': proc.stderr.strip()[-200:]}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--repo-root', required=True)
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--template-success', required=True)
    ap.add_argument('--template-failed', required=True)
    ap.add_argument('--hosts', type=int, default=1000)
    ap.add_argument('--repeat', type=int, default=3)
    ap.add_argument('--scenarios', default='all_output,mixed,no_output')
    a = ap.parse_args(argv)
    success_env = _load_template(a.template_success)
    failed_env = _load_template(a.template_failed)
    assert success_env['target_type'] == failed_env['target_type']
    ips = _ips(a.hosts)
    results = []
    for scenario in a.scenarios.split(','):
        ws = os.path.join(a.workdir, scenario)
        counts, sizes = synthesize(ws, scenario, ips, success_env, failed_env)
        runs = []
        for _ in range(a.repeat):
            runs.append(run_finalize(a.repo_root, ws, 'completed' if scenario == 'all_output' else 'timeout'))
        results.append({'scenario': scenario, 'hosts': a.hosts, 'inputs': counts, 'input_bytes': sizes, 'runs': runs})
        print(json.dumps(results[-1], ensure_ascii=False))
    with open(os.path.join(a.workdir, 'finalize_bench.json'), 'w', encoding='utf-8') as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
