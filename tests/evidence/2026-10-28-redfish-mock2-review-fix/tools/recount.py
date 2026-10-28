"""73건 처분 · 132칸 판정을 원문 표에서 다시 센다 (2026-10-28 독립 검증 결함 정정 — stdlib).

- 처분: `ISSUE_DISPOSITION.md` 의 ID 행(`| 0N-<영역>-NNN | 심각도 | 처분 | 근거 |`)에서 처분 칸의 굵은 어휘(`**FIXED**` 등)를 읽는다.
  첫 어휘 = 최상위 처분, 나머지 = 병기. ID 집합이 감사 원문 `ISSUES.md` 의 ID 행과 1:1 인지 본다. 머리말 집계 문장과 맞는지 단언한다.
- 132칸: `coverage-132-after.json` 의 grid 칸 상태를 세고, 같은 파일의 `counts` · md 표(칸마다 `A→B` 의 B) · md 머리말 집계와 맞는지 본다.

사용: python -I -X utf8 recount.py <impl_evidence_dir> <audit_dir> --out <md>
종료 코드 1 = 어느 대조든 어긋남.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

VOCAB = ("FIXED", "DOC_CORRECTED", "OBSERVATION_ONLY", "VALIDATED_EXISTING", "MOCK_LIMITATION", "HOLD")
ROW = re.compile(r"^\| (\d{2}-[a-z_]+-\d{3}) \|([^|]*)\|([^|]*)\|", re.M)
BOLD = re.compile(r"\*\*(" + "|".join(VOCAB) + r")\*\*")
STATES = ("PASS", "ISSUE", "MOCK_LIMITATION", "NOT_APPLICABLE", "NOT_CHECKED")


def _num(rx, text):
    m = re.search(rx, text)
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("impl_dir")
    ap.add_argument("audit_dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    impl, audit = Path(a.impl_dir), Path(a.audit_dir)
    md, bad = [], []

    # ── 처분 73건 ──────────────────────────────────────────────────────────────
    disp = (impl / "ISSUE_DISPOSITION.md").read_text(encoding="utf-8")
    rows = ROW.findall(disp)
    ids = [r[0] for r in rows]
    audit_ids = [r[0] for r in ROW.findall((audit / "ISSUES.md").read_text(encoding="utf-8"))]
    top, sec = collections.Counter(), collections.Counter()
    sec_ids = collections.defaultdict(list)
    no_verdict = []
    for i, sev, verdict in rows:
        toks = BOLD.findall(verdict)
        if not toks:
            no_verdict.append(i)
            continue
        top[toks[0]] += 1
        for t in toks[1:]:
            sec[t] += 1
            sec_ids[t].append(i)
    dup = sorted(k for k, v in collections.Counter(ids).items() if v > 1)
    only_disp, only_audit = sorted(set(ids) - set(audit_ids)), sorted(set(audit_ids) - set(ids))
    head = next((ln for ln in disp.splitlines() if "집계(1차 처분 기준)" in ln), "")
    claim = {"FIXED": _num(r"FIXED (\d+)", head), "DOC_CORRECTED": _num(r"DOC_CORRECTED (\d+)", head),
             "OBSERVATION_ONLY": _num(r"OBSERVATION_ONLY (\d+)", head), "MOCK_LIMITATION": _num(r"MOCK_LIMITATION (\d+)", head),
             "VALIDATED_EXISTING": _num(r"VALIDATED_EXISTING (\d+)", head), "HOLD": _num(r"HOLD (\d+)", head)}
    got = {"FIXED": top["FIXED"], "DOC_CORRECTED": top["DOC_CORRECTED"], "OBSERVATION_ONLY": top["OBSERVATION_ONLY"],
           "MOCK_LIMITATION": sec["MOCK_LIMITATION"], "VALIDATED_EXISTING": sec["VALIDATED_EXISTING"], "HOLD": sec["HOLD"]}
    md += ["# 73건 처분 · 132칸 재집계", "", f"- 입력: `{(impl / 'ISSUE_DISPOSITION.md').as_posix()}` · `{(audit / 'ISSUES.md').as_posix()}` · "
           f"`{(impl / 'coverage-132-after.json').as_posix()}` · `{(impl / 'coverage-132-after.md').as_posix()}`", "",
           "## 처분", "",
           f"- ID 행 {len(ids)}개(중복 {dup or 0}) · 감사 원문 ID 행 {len(audit_ids)}개 · 처분에만 {only_disp or 0} · 원문에만 {only_audit or 0} · "
           f"처분 어휘 없는 행 {no_verdict or 0}",
           "- 최상위: " + " · ".join(f"{k} {top[k]}" for k in VOCAB if top[k]) + f" = {sum(top.values())}",
           "- 병기: " + " · ".join(f"{k} {sec[k]}({', '.join(sec_ids[k])})" for k in VOCAB if sec[k]), "",
           "| 항목 | 머리말 문장 | 표에서 센 값 | 일치 |", "|---|---|---|---|"]
    for k in claim:
        ok = claim[k] == got[k]
        md.append(f"| {k} | {claim[k]} | {got[k]} | {'[OK]' if ok else '[NG]'} |")
        if not ok:
            bad.append(f"처분 {k}: 머리말 {claim[k]} ≠ 표 {got[k]}")
    if len(ids) != 73 or dup or only_disp or only_audit or no_verdict or sum(top.values()) != 73:
        bad.append("처분 ID 집합 · 개수 불일치")

    # ── 132칸 ─────────────────────────────────────────────────────────────────
    cov = json.loads((impl / "coverage-132-after.json").read_text(encoding="utf-8"))
    grid_cnt, trans = collections.Counter(), collections.Counter()
    for sv in cov["servers"]:
        for ar in cov["areas"]:
            cell = cov["grid"][sv][ar]
            grid_cnt[cell["state"]] += 1
            trans[f"{cell['before']}→{cell['state']}"] += 1
    covmd = (impl / "coverage-132-after.md").read_text(encoding="utf-8")
    md_cnt, md_cells, mismatch = collections.Counter(), 0, []
    for ln in covmd.splitlines():
        cols = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cols) == len(cov["areas"]) + 1 and cols[0] in cov["servers"]:
            for ar, c in zip(cov["areas"], cols[1:]):
                st = c.split("→")[-1].strip()
                md_cnt[st] += 1
                md_cells += 1
                if st != cov["grid"][cols[0]][ar]["state"]:
                    mismatch.append(f"{cols[0]}.{ar}: md {st} ≠ json {cov['grid'][cols[0]][ar]['state']}")
    agg = next((ln for ln in covmd.splitlines() if ln.startswith("- 집계(after)")), "")
    md_head = {s: _num(rf"{s} (\d+)", agg) for s in ("PASS", "ISSUE", "MOCK_LIMITATION", "NOT_APPLICABLE")}
    md += ["", "## 132칸", "",
           f"- json grid {sum(grid_cnt.values())}칸: " + " · ".join(f"{s} {grid_cnt[s]}" for s in STATES if grid_cnt[s]),
           "- 전이(분석 판정→재판정): " + " · ".join(f"{k} {v}" for k, v in sorted(trans.items())),
           f"- md 표 {md_cells}칸 · json 과 다른 칸 {mismatch or 0}", "",
           "| 상태 | json grid | json counts | md 표 | md 머리말 | 일치 |", "|---|---|---|---|---|---|"]
    for s in ("PASS", "ISSUE", "MOCK_LIMITATION", "NOT_APPLICABLE"):
        vals = (grid_cnt[s], cov["counts"].get(s), md_cnt[s], md_head[s])
        ok = len(set(vals)) == 1
        md.append(f"| {s} | {vals[0]} | {vals[1]} | {vals[2]} | {vals[3]} | {'[OK]' if ok else '[NG]'} |")
        if not ok:
            bad.append(f"132칸 {s}: {vals}")
    if sum(grid_cnt.values()) != 132 or cov.get("total") != 132 or md_cells != 132 or mismatch:
        bad.append("132칸 총수 · 칸 대응 불일치")

    md += ["", "## 판정", "", ("[PASS] 모든 대조 일치" if not bad else "[FAIL] " + " / ".join(bad))]
    Path(a.out).write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[-1:]))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
