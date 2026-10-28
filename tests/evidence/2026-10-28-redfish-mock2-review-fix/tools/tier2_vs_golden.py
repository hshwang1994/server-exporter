"""Tier 2 모듈 산출(`<label>.<tag>.module.json`)을 golden · 이전 Tier 2 산출과 대조한다 (2026-10-28 — stdlib).

(1) golden: `tests/fixtures/redfish/<fixture>/expected_output.json` 과 GOLDEN_KEYS(정본 `tests/integration/emulator_harness.py`)만 비교.
    label → fixture 대응은 구현 측 `tier2-final/_vs_golden.md` 표와 같다(fixture 없는 1차 CSUS 02~04 는 비교 없음).
(2) 이전 산출: 같은 이름의 module.json 을 키 전부(aux 포함) 비교 — 모듈 층 변화가 0 인지 본다.

사용: python -I -X utf8 tier2_vs_golden.py <tier2_dir> --prev <prev_tier2_dir> --out-md <md>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
os.environ.setdefault("SE_REPO_ROOT", str(REPO))
sys.path.insert(0, str(REPO / "tests" / "integration"))
from emulator_harness import GOLDEN_KEYS  # noqa: E402

FIXTURE = {
    "csus3200_01": "real_hpe_csus3200_01", "csus3200_02": "real_hpe_csus3200_02", "csus3200_03": "real_hpe_csus3200_03",
    "dl380_gen12_01": "real_hpe_dl380_gen12_01", "dl380_gen12_02": "real_hpe_dl380_gen12_02",
    "dl380_gen12_03": "real_hpe_dl380_gen12_03", "dl380_gen12_04": "real_hpe_dl380_gen12_04",
    "r1_DELL_R740_01": "real_dell_r740", "r1_HPE_CSUS3200_01": "real_hpe_csus3200",
    "r1_HPE_DL380_01": "real_hpe_dl380", "r1_Lenovo_SR650_01": "real_lenovo_sr650",
    "sr650_v4_01": "real_lenovo_sr650_v4_01", "sr650_v4_02": "real_lenovo_sr650_v4_02",
    "sr650_v4_03": "real_lenovo_sr650_v4_03", "sr650_v4_04": "real_lenovo_sr650_v4_04",
}


def _flat(o, p="", out=None):
    out = {} if out is None else out
    if isinstance(o, dict):
        if not o:
            out[p or "<root>"] = {}
        for k, v in o.items():
            _flat(v, f"{p}.{k}" if p else str(k), out)
    elif isinstance(o, list):
        if not o:
            out[p] = []
        for i, v in enumerate(o):
            _flat(v, f"{p}[{i}]", out)
    else:
        out[p] = o
    return out


def _diff(a, b):
    fa, fb = _flat(a), _flat(b)
    return sorted(p for p in set(fa) | set(fb) if fa.get(p, "<absent>") != fb.get(p, "<absent>"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tier2_dir")
    ap.add_argument("--prev", required=True)
    ap.add_argument("--out-md", required=True)
    a = ap.parse_args()
    cur, prev = Path(a.tier2_dir), Path(a.prev)
    mods = sorted(cur.glob("*.module.json"))
    md = ["| label | tag | status | fixture | GOLDEN_KEYS 차이(golden) | 키 전부 차이(이전 Tier 2) | 예시 |", "|---|---|---|---|---|---|---|"]
    tot_g = tot_p = 0
    missing_prev = []
    for m in mods:
        label, tag = m.name.split(".")[0], m.name.split(".")[1]
        res = json.loads(m.read_text(encoding="utf-8"))
        fx = FIXTURE.get(label)
        dg = "-"
        ex = []
        if fx:
            gold = json.loads((REPO / "tests" / "fixtures" / "redfish" / fx / "expected_output.json").read_text(encoding="utf-8"))
            d = _diff({k: res.get(k) for k in GOLDEN_KEYS}, {k: gold.get(k) for k in GOLDEN_KEYS})
            dg, tot_g, ex = len(d), tot_g + len(d), ex + d[:3]
        pm = prev / m.name
        if pm.exists():
            d2 = _diff(res, json.loads(pm.read_text(encoding="utf-8")))
            dp, tot_p, ex = len(d2), tot_p + len(d2), ex + d2[:3]
        else:
            dp = "(이전 없음)"
            missing_prev.append(m.name)
        md.append(f"| {label} | {tag} | {res.get('status')} | {('`' + fx + '`') if fx else '(fixture 없음)'} | {dg} | {dp} | "
                  f"{', '.join('`' + e + '`' for e in ex)} |")
    md += ["", f"- module.json {len(mods)}개 · golden 비교 {sum(1 for m in mods if m.name.split('.')[0] in FIXTURE)} label · "
               f"GOLDEN_KEYS = {list(GOLDEN_KEYS)}",
           f"- 총 차이 경로: golden {tot_g} · 이전 Tier 2(`{prev.as_posix()}`) {tot_p}" + (f" · 이전 없음 {missing_prev}" if missing_prev else "")]
    Path(a.out_md).write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"modules={len(mods)} golden_diff={tot_g} prev_diff={tot_p} missing_prev={len(missing_prev)}")
    return 1 if (tot_g or tot_p or missing_prev) else 0


if __name__ == "__main__":
    raise SystemExit(main())
