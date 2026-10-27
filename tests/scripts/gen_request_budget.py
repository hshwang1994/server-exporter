#!/usr/bin/env python3
"""real_* fixture 의 request_budget.json 생성기 (2026-10-27, WP1(b)).

tests/integration/test_request_budget.py 의 집계(_replay_counts: in-process 재생, 캐시 뒤, noauth 포함)와 같은 방법으로
현재 코드가 그 recording 을 재생할 때 보내는 HTTP 요청 다중집합을 세어 request_budget.json 을 쓴다.
- 새 fixture: baseline_http_calls == http_calls_budget == sum(expected), path_set_delta 비어 있음.
- 기존 fixture 갱신(--update): 종전 파일의 baseline_http_calls 를 유지하고 removed/added 를 계산해 적는다. added 가 있으면
  --added-reason 이 필수다(test_budget_file_is_self_consistent).
사용: python tests/scripts/gen_request_budget.py <fixture_dir> [--update] [--added-reason "..."] [--note "..."]
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "integration"))
import emulator_harness as H  # noqa: E402


def replay_counts(case_dir: Path):
    rec = json.loads((case_dir / "recording.json").read_text(encoding="utf-8"))
    meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8")) if (case_dir / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    calls = collections.Counter()

    def gw(bmc_ip, path, u, p, t, v):
        calls[path] += 1
        return g(bmc_ip, path, u, p, t, v)

    def nw(bmc_ip, path, t, v):
        calls["noauth::" + path] += 1
        return n(bmc_ip, path, t, v)

    H.run_gather(gw, nw, realm_impl=r, manager_layout=meta.get("manager_layout"),
                 firmware_scope=meta.get("firmware_inventory_scope"))
    return calls


def _sha():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO), capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture_dir")
    ap.add_argument("--update", action="store_true", help="기존 request_budget.json 의 baseline 을 유지하고 delta 를 계산")
    ap.add_argument("--added-reason", default=None)
    ap.add_argument("--note", default=None)
    a = ap.parse_args()
    case = Path(a.fixture_dir)
    calls = replay_counts(case)
    expected = sorted(f"{p} x{c}" for p, c in calls.items())
    total = sum(calls.values())
    out = case / "request_budget.json"
    today = _dt.date.today().isoformat()
    if a.update and out.is_file():
        old = json.loads(out.read_text(encoding="utf-8"))
        old_counts = collections.Counter()
        for e in old["expected_http_calls"]:
            p, c = e.rsplit(" x", 1)
            old_counts[p] = int(c)
        removed = sorted(f"{p} x{old_counts[p] - calls.get(p, 0)}" for p in old_counts if old_counts[p] > calls.get(p, 0))
        added = sorted(f"{p} x{calls[p] - old_counts.get(p, 0)}" for p in calls if calls[p] > old_counts.get(p, 0))
        # delta 는 baseline(최초 파일의 baseline_http_calls) 대비 누적이어야 self-consistent 하다
        base_total = int(old["baseline_http_calls"])
        prev_removed = list(old.get("path_set_delta", {}).get("removed", []))
        prev_added = list(old.get("path_set_delta", {}).get("added", []))
        budget = {"generated": today, "baseline_sha": old.get("baseline_sha", _sha()),
                  "baseline_http_calls": base_total, "http_calls_budget": total,
                  "note": a.note or old.get("note", ""),
                  "path_set_delta": {"removed": prev_removed + removed, "added": prev_added + added},
                  "expected_http_calls": expected}
        if (prev_added or added):
            reason = a.added_reason or old.get("added_reason")
            if not (isinstance(reason, str) and reason.strip()):
                print("[FAIL] 요청이 추가됐으면 --added-reason 이 필요하다", file=sys.stderr)
                return 2
            budget["added_reason"] = reason
        # 자기 일관성 검사 (test_budget_file_is_self_consistent 와 같은 식)
        rem = sum(int(e.rsplit(" x", 1)[1]) for e in budget["path_set_delta"]["removed"])
        add = sum(int(e.rsplit(" x", 1)[1]) for e in budget["path_set_delta"]["added"])
        if base_total - total != rem - add:
            print(f"[FAIL] delta 불일치: baseline {base_total} - total {total} != removed {rem} - added {add}", file=sys.stderr)
            return 3
    else:
        budget = {"generated": today, "baseline_sha": _sha(), "baseline_http_calls": total, "http_calls_budget": total,
                  "note": a.note or ("2026-10-27 WP1(b): 2차 전수 미러 축약 fixture 의 최초 예산 — expected_http_calls 는 현재 코드의 "
                                     "HTTP 요청 다중집합(캐시 hit 제외, noauth 포함). 바뀌면 사유와 함께 갱신(암묵적 감소·증가 모두 FAIL)."),
                  "path_set_delta": {"removed": [], "added": []},
                  "expected_http_calls": expected}
    out.write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] {case.name}: total={total} distinct={len(calls)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
