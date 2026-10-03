#!/usr/bin/env python3
"""phase5_mem_sampler.py — Phase 5 (Plan §10-3) 보조 도구: 프로세스 트리의 합산 메모리를 주기적으로 샘플링한다.

`/usr/bin/time -v` 의 "Maximum resident set size" 는 wait4() rusage 의 ru_maxrss 라서 트리 안에서 **가장 큰 프로세스 하나**의
RSS 다 (ansible-playbook 메인 + fork 된 worker 전체의 합이 아니다). 그래서 이 도구가 루트 PID 의 자손 전체를 /proc 로 걸어
VmRSS 합과 Pss 합(공유 페이지를 비례 배분 — fork 된 worker 의 COW 공유를 중복 계산하지 않는다)의 피크를 따로 기록한다.

usage: phase5_mem_sampler.py --root-pid PID --out FILE [--interval 0.5]
루트 PID 가 끝나면(존재하지 않거나 zombie) 종료하고 JSON 을 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import time


def _proc_table():
    """pid → (ppid, state). /proc/<pid>/stat 의 comm 에 공백/괄호가 있어도 안전하게 마지막 ')' 뒤를 파싱한다."""
    table = {}
    for name in os.listdir('/proc'):
        if not name.isdigit():
            continue
        try:
            with open(f'/proc/{name}/stat', 'rb') as fh:
                raw = fh.read()
        except OSError:
            continue
        rp = raw.rfind(b')')
        fields = raw[rp + 2:].split()
        if len(fields) < 2:
            continue
        table[int(name)] = (int(fields[1]), fields[0].decode(errors='replace'))
    return table


def _descendants(root, table):
    children = {}
    for pid, (ppid, _) in table.items():
        children.setdefault(ppid, []).append(pid)
    out, stack = [], [root]
    while stack:
        pid = stack.pop()
        out.append(pid)
        stack.extend(children.get(pid, []))
    return out


def _mem_kb(pid):
    rss = pss = 0
    try:
        with open(f'/proc/{pid}/status') as fh:
            for line in fh:
                if line.startswith('VmRSS:'):
                    rss = int(line.split()[1])
                    break
    except OSError:
        return 0, 0
    try:
        with open(f'/proc/{pid}/smaps_rollup') as fh:
            for line in fh:
                if line.startswith('Pss:'):
                    pss = int(line.split()[1])
                    break
    except OSError:
        pss = rss
    return rss, pss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root-pid', type=int, required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--interval', type=float, default=0.5)
    a = ap.parse_args()

    t0 = time.time()
    peak = {'rss_kb': 0, 'pss_kb': 0, 'procs': 0, 't': 0.0}
    peak_procs = 0
    samples = 0
    series = []
    while True:
        table = _proc_table()
        state = table.get(a.root_pid, (None, 'X'))[1]
        if state in ('X', 'Z'):
            break
        pids = _descendants(a.root_pid, table)
        rss = pss = 0
        live = 0
        for pid in pids:
            if table.get(pid, (None, 'X'))[1] == 'Z':
                continue
            r, p = _mem_kb(pid)
            if r:
                live += 1
            rss += r
            pss += p
        samples += 1
        t = round(time.time() - t0, 2)
        series.append((t, rss, pss, live))
        if pss > peak['pss_kb']:
            peak = {'rss_kb': rss, 'pss_kb': pss, 'procs': live, 't': t}
        peak_procs = max(peak_procs, live)
        time.sleep(a.interval)

    # 시계열은 20점으로 압축 (피크 시점 포함) — 증거 문서에 곡선 모양만 남기기 위함.
    step = max(1, len(series) // 20)
    thinned = series[::step]
    with open(a.out, 'w', encoding='utf-8') as fh:
        json.dump({'samples': samples, 'interval_s': a.interval, 'duration_s': round(time.time() - t0, 2),
                   'peak_sum_rss_kb': peak['rss_kb'], 'peak_sum_pss_kb': peak['pss_kb'],
                   'procs_at_peak': peak['procs'], 'peak_t_s': peak['t'], 'max_live_procs': peak_procs,
                   'series_t_rss_pss_procs': thinned}, fh)


if __name__ == '__main__':
    main()
