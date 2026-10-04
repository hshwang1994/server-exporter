#!/usr/bin/env python3
"""perf_observe_report.py — perf_observe.py 의 JSONL 을 빌드별로 집계한다 (main 전용 도구, 2026-10-04 최종 실행 지시 §7).

입력 : --samples <perf_observe.jsonl> (여러 개 가능 — 노드마다 하나) · --label <파일 라벨>(같은 순서, 선택)
출력 : --out report.json (+ --md report.md 표). 빌드(SE_BUILD_ID)마다
        node · first/last ts · duration_s · samples · peak_pss_mb(트리 PSS 합의 최댓값) · peak_rss_mb · peak_active_workers(살아 있는 worker 수 최댓값) ·
        main_pss_mb_at_peak(메인 프로세스 = 고정 비용 후보) · per_worker_pss_mb_at_peak = (peak_pss − main_pss) / workers_at_peak ·
        per_worker_pss_mb_max(모든 샘플 중 worker 당 PSS 최댓값) · mem_available_min_mb · mem_available_drop_mb(빌드 직전 60 s 기준) · swap_delta_mb ·
        overlapped_with(같은 샘플에 함께 있던 다른 빌드) · combined_peak_pss_mb(겹친 샘플의 PSS 합 최댓값).
      노드 요약: mem_total_mb · mem_available_min_mb · combined_peak_pss_mb(모든 빌드 합의 최댓값) · 그 시각의 활성 worker 합.
      `pss_known_ratio` < 1 이면 일부 프로세스의 PSS 를 못 읽어 RSS 만 합산된 것이다 — 그 빌드의 PSS 값은 하한으로 읽는다.
해석 책임은 사람에게 있다: 이 도구는 상수(per_fork_mb · fixed_mb · node_share)를 **제안하지 않고** 관측값만 적는다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def load_samples(path: str) -> list:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _mb(kb):
    return None if kb is None else round(kb / 1024.0, 1)


def summarise(rows: list, label: str) -> dict:
    builds = {}
    node_combined_peak = 0.0
    node_combined_workers_at_peak = 0
    mem_total = next((r.get("mem_total_kb") for r in rows if r.get("mem_total_kb")), None)
    mem_min = min((r.get("mem_available_kb") for r in rows if r.get("mem_available_kb") is not None), default=None)
    for r in rows:
        bs = r.get("builds") or {}
        combined = sum((b.get("pss_kb") or 0) for b in bs.values())
        if combined > node_combined_peak:
            node_combined_peak = combined
            node_combined_workers_at_peak = sum((b.get("active_workers") or 0) for b in bs.values())
        for bid, b in bs.items():
            s = builds.setdefault(bid, {"build_id": bid, "node": label, "first_ts": r["ts"], "last_ts": r["ts"], "samples": 0,
                                        "peak_pss_kb": 0, "peak_rss_kb": 0, "peak_active_workers": 0, "main_pss_kb_at_peak": None,
                                        "workers_at_peak": 0, "per_worker_pss_kb_samples": [], "mem_available_min_kb": None,
                                        "overlapped_with": set(), "combined_peak_pss_kb": 0, "pss_known": 0, "procs_total": 0})
            s["last_ts"] = r["ts"]
            s["samples"] += 1
            s["pss_known"] += b.get("pss_known") or 0
            s["procs_total"] += b.get("procs") or 0
            pss = b.get("pss_kb") or 0
            if pss > s["peak_pss_kb"]:
                s["peak_pss_kb"] = pss
                s["main_pss_kb_at_peak"] = b.get("main_pss_kb")
                s["workers_at_peak"] = b.get("active_workers") or 0
            s["peak_rss_kb"] = max(s["peak_rss_kb"], b.get("rss_kb") or 0)
            s["peak_active_workers"] = max(s["peak_active_workers"], b.get("active_workers") or 0)
            w = b.get("active_workers") or 0
            if w > 0 and b.get("main_pss_kb") is not None:
                s["per_worker_pss_kb_samples"].append((pss - (b.get("main_pss_kb") or 0)) / float(w))
            ma = r.get("mem_available_kb")
            if ma is not None:
                s["mem_available_min_kb"] = ma if s["mem_available_min_kb"] is None else min(s["mem_available_min_kb"], ma)
            others = [o for o in bs if o != bid]
            if others:
                s["overlapped_with"].update(others)
                s["combined_peak_pss_kb"] = max(s["combined_peak_pss_kb"], combined)
    out = []
    for bid, s in builds.items():
        before = [r.get("mem_available_kb") for r in rows if s["first_ts"] - 60 <= r["ts"] < s["first_ts"] and r.get("mem_available_kb") is not None]
        swap_before = [r.get("swap_free_kb") for r in rows if s["first_ts"] - 60 <= r["ts"] < s["first_ts"] and r.get("swap_free_kb") is not None]
        swap_in = [r.get("swap_free_kb") for r in rows if s["first_ts"] <= r["ts"] <= s["last_ts"] and r.get("swap_free_kb") is not None]
        pw = s["per_worker_pss_kb_samples"]
        main_pss = s["main_pss_kb_at_peak"]
        wk = s["workers_at_peak"]
        rec = {
            "build_id": bid, "node": s["node"], "first_ts": s["first_ts"], "last_ts": s["last_ts"],
            "duration_s": round(s["last_ts"] - s["first_ts"], 1), "samples": s["samples"],
            "peak_pss_mb": _mb(s["peak_pss_kb"]), "peak_rss_mb": _mb(s["peak_rss_kb"]),
            "peak_active_workers": s["peak_active_workers"], "workers_at_peak": wk,
            "main_pss_mb_at_peak": _mb(main_pss),
            "per_worker_pss_mb_at_peak": (round((s["peak_pss_kb"] - (main_pss or 0)) / wk / 1024.0, 1) if wk and main_pss is not None else None),
            "per_worker_pss_mb_max": (_mb(max(pw)) if pw else None),
            "per_worker_pss_mb_median": (_mb(statistics.median(pw)) if pw else None),
            "mem_available_min_mb": _mb(s["mem_available_min_kb"]),
            "mem_available_drop_mb": (_mb(max(before) - s["mem_available_min_kb"]) if before and s["mem_available_min_kb"] is not None else None),
            "swap_delta_mb": (_mb(min(swap_before) - min(swap_in)) if swap_before and swap_in else None),
            "overlapped_with": sorted(s["overlapped_with"]), "combined_peak_pss_mb": _mb(s["combined_peak_pss_kb"]) if s["overlapped_with"] else None,
            "pss_known_ratio": (round(s["pss_known"] / float(s["procs_total"]), 3) if s["procs_total"] else None),
        }
        out.append(rec)
    return {"node": label, "samples": len(rows), "mem_total_mb": _mb(mem_total), "mem_available_min_mb": _mb(mem_min),
            "combined_peak_pss_mb": _mb(node_combined_peak), "combined_workers_at_peak": node_combined_workers_at_peak,
            "builds": sorted(out, key=lambda x: x["first_ts"])}


def to_markdown(reports: list) -> str:
    lines = ["| 빌드(SE_BUILD_ID) | 노드 | 구간 s | 샘플 | peak PSS MB | peak RSS MB | worker 최대/peak 시 | main PSS MB | worker당 PSS MB(peak/최대/중앙) | MemAvail 최소 MB(하락) | swap Δ MB | 겹침 | 겹친 합 PSS MB | PSS 확보율 |",
             "|---|---|---:|---:|---:|---:|---|---:|---|---|---:|---|---:|---:|"]
    for rep in reports:
        for b in rep["builds"]:
            lines.append("| {bid} | {node} | {dur} | {n} | {pss} | {rss} | {wmax}/{wpk} | {main} | {pwp}/{pwm}/{pwmed} | {ma}({drop}) | {sw} | {ov} | {cmb} | {kr} |".format(
                bid=b["build_id"], node=b["node"], dur=b["duration_s"], n=b["samples"], pss=b["peak_pss_mb"], rss=b["peak_rss_mb"],
                wmax=b["peak_active_workers"], wpk=b["workers_at_peak"], main=b["main_pss_mb_at_peak"], pwp=b["per_worker_pss_mb_at_peak"],
                pwm=b["per_worker_pss_mb_max"], pwmed=b["per_worker_pss_mb_median"], ma=b["mem_available_min_mb"], drop=b["mem_available_drop_mb"],
                sw=b["swap_delta_mb"], ov=",".join(b["overlapped_with"]) or "-", cmb=b["combined_peak_pss_mb"] if b["combined_peak_pss_mb"] is not None else "-",
                kr=b["pss_known_ratio"]))
        lines.append("| (노드 {node}) | | | {n} | 모든 빌드 합 최대 {cmb} MB (worker 합 {w}) | | | | | MemTotal {mt} · 최소 {mn} | | | | |".format(
            node=rep["node"], n=rep["samples"], cmb=rep["combined_peak_pss_mb"], w=rep["combined_workers_at_peak"], mt=rep["mem_total_mb"], mn=rep["mem_available_min_mb"]))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--samples", action="append", required=True)
    ap.add_argument("--label", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--md", default="")
    a = ap.parse_args(argv)
    reports = []
    for i, path in enumerate(a.samples):
        label = a.label[i] if i < len(a.label) else Path(path).stem
        reports.append(summarise(load_samples(path), label))
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(reports, fh, ensure_ascii=False, indent=1)
    md = to_markdown(reports)
    if a.md:
        with open(a.md, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(md)
    sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
