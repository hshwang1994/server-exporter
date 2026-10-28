"""Tier 1 두 산출 트리의 차이를 값까지 펼쳐 적는다 (2026-10-28 독립 검증 결함 정정 — stdlib).

`tests/redfish-probe/mirror_replay/diff_tier1.py` 는 label 마다 차이 개수만 낸다. 이 도구는 같은 비교 함수(`diff_label`)를 그대로
불러 허용목록으로 설명된 차이 · 설명되지 않은 차이를 경로 · 이전 값 · 새 값으로 펼치고, `_summary.json` 의 실행 결과
(playbook rc · status · sections · adapter · errors · 요청 수)를 label 마다 나란히 놓는다. 판정은 사람이 한다.

사용: python -I -X utf8 tier1_explained.py <before_root> <after_root> [--allow allow.json] --out-md <md> [--out-json <json>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tests" / "redfish-probe" / "mirror_replay"))
from diff_tier1 import _last_envelope, diff_label  # noqa: E402

RUN_KEYS = ("playbook_rc", "status", "vendor", "adapter_id", "adapter_first_pass", "sections", "errors", "failure",
            "requests", "requests_distinct", "req_notes")
IFACE = re.compile(r"^data\.network\.interfaces\[(\d+)\]\.")


def _summary(root: Path):
    p = root / "_summary.json"
    if not p.exists():
        return {}
    return {r["label"]: r for r in json.loads(p.read_text(encoding="utf-8"))}


def _j(v):
    return json.dumps(v, ensure_ascii=False, default=str)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before_root")
    ap.add_argument("after_root")
    ap.add_argument("--allow", default=None)
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--out-json", default=None)
    a = ap.parse_args()
    before, after = Path(a.before_root), Path(a.after_root)
    allow = json.loads(Path(a.allow).read_text(encoding="utf-8")) if a.allow else []
    labels = sorted({p.name for p in after.iterdir() if p.is_dir()} | {p.name for p in before.iterdir() if p.is_dir()})
    sb, sa = _summary(before), _summary(after)

    rows, runs, kinds = [], [], Counter()
    for lb in labels:
        res = diff_label(lb, before / lb, after / lb, allow)
        env_a = _last_envelope(after / lb / "gather_output.json") or {}
        ifaces = ((env_a.get("data") or {}).get("network") or {}).get("interfaces") or []
        for kind, items in (("explained", res["explained"]), ("unexplained", res["unexplained"])):
            for it in items:
                m = IFACE.match(it["path"])
                ref = ""
                if m and int(m.group(1)) < len(ifaces):
                    nic = ifaces[int(m.group(1))]
                    ref = f"{nic.get('id')} {nic.get('mac')}"
                rows.append({"label": lb, "kind": kind, "path": it["path"], "ref": ref, "before": it["before"],
                             "after": it["after"], "issue": it.get("issue")})
                leaf = re.sub(r"\[\d+\]", "[]", it["path"])
                kinds[(kind, leaf, _j(it["before"]), _j(it["after"]))] += 1
        rb, ra = sb.get(lb, {}), sa.get(lb, {})
        runs.append({"label": lb, "missing": res["missing"], "req_added": res["req_added"], "req_removed": res["req_removed"],
                     "req_unexplained": res["req_unexplained"],
                     "run_same": {k: rb.get(k) == ra.get(k) for k in RUN_KEYS},
                     "before": {k: rb.get(k) for k in RUN_KEYS}, "after": {k: ra.get(k) for k in RUN_KEYS}})

    n_unexp = sum(1 for r in rows if r["kind"] == "unexplained")
    n_req = sum(len(r["req_unexplained"]) for r in runs)
    n_miss = sum(1 for r in runs if r["missing"])
    md = [f"# Tier 1 차이 펼침 — `{before.as_posix()}` → `{after.as_posix()}`", "",
          f"- 허용목록: `{a.allow or '[] (없음 — 엄격 비교)'}` ({len(allow)} 항목)",
          f"- 설명된 차이 {len(rows) - n_unexp} · **설명되지 않은 차이 {n_unexp}** · 요청 집합 미설명 {n_req} · 산출 없음 {n_miss}", "",
          "## 실행 결과 (`_summary.json`)", "",
          "| label | rc | status | adapter | errors | 요청(전체/고유) | sections · 실행 필드 같음 |", "|---|---|---|---|---|---|---|"]
    for r in runs:
        b, x = r["before"], r["after"]
        same = "전부 같음" if all(r["run_same"].values()) else "다름: " + ", ".join(k for k, v in r["run_same"].items() if not v)
        md.append(f"| {r['label']} | {b['playbook_rc']} → {x['playbook_rc']} | {b['status']} → {x['status']} | {x['adapter_id']} | "
                  f"{b['errors']} → {x['errors']} | {b['requests']}/{b['requests_distinct']} → {x['requests']}/{x['requests_distinct']} | {same} |")
    md += ["", "## 차이 종류별 집계 (경로의 인덱스를 [] 로 접음)", "", "| 구분 | 경로 | 이전 → 새 값 | 건수 |", "|---|---|---|---|"]
    for (kind, leaf, vb, va), n in sorted(kinds.items()):
        md.append(f"| {kind} | `{leaf}` | {vb} → {va} | {n} |")
    md += ["", "## 차이 전수", "", "| label | 구분 | 경로 | NIC | 이전 | 새 값 | issue |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['label']} | {r['kind']} | `{r['path']}` | {r['ref']} | {_j(r['before'])} | {_j(r['after'])} | {r['issue'] or ''} |")
    for r in runs:
        if r["req_added"] or r["req_removed"]:
            md.append(f"\n- {r['label']} 요청 집합: +{r['req_added']} -{r['req_removed']} (미설명 {r['req_unexplained']})")
    Path(a.out_md).write_text("\n".join(md) + "\n", encoding="utf-8")
    if a.out_json:
        Path(a.out_json).write_text(json.dumps({"rows": rows, "runs": runs}, ensure_ascii=False, indent=1, default=str) + "\n",
                                    encoding="utf-8")
    print(f"explained={len(rows) - n_unexp} unexplained={n_unexp} req_unexplained={n_req} missing={n_miss}")
    return 1 if (n_unexp or n_req or n_miss) else 0


if __name__ == "__main__":
    raise SystemExit(main())
