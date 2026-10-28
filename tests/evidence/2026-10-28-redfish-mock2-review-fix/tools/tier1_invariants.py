"""Tier 1 산출 트리에서 이번 정정이 바꾸지 않아야 할 값과 남은 미확정 값을 label 마다 적는다 (2026-10-28 — stdlib, 읽기 전용).

- HBA: `data.storage.hbas[]` 수 · `link_status` 값 집합(⊂ {up, down} 이어야 함) · 링크 notice("링크 상태 …") 수
- network: `link_status` 가 unknown 으로 남은 interfaces 의 id · MAC
- 전원 Off notice("호스트 전원 Off 관측 …") 수 · 문구, `data.cpu.logical_threads` 키 존재 수(0 이어야 함)
--ref 를 주면 HBA 수 · 값 · 링크 notice 문구가 기준 트리와 같은지도 적는다.

사용: python -I -X utf8 -B tier1_invariants.py <tier1_root> [--ref <tier1_root>] --out <md>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tests" / "redfish-probe" / "mirror_replay"))
from diff_tier1 import _last_envelope  # noqa: E402

POWER_OFF = "호스트 전원 Off 관측"


def facts(env):
    data = env.get("data") or {}
    hbas = ((data.get("storage") or {}).get("hbas")) or []
    notices = ((env.get("diagnosis") or {}).get("details") or {}).get("notices") or []
    msgs = [str(n.get("message", "")) if isinstance(n, dict) else str(n) for n in notices]
    ifaces = ((data.get("network") or {}).get("interfaces")) or []
    return {
        "status": env.get("status"),
        "hba_n": len(hbas),
        "hba_links": sorted({str(h.get("link_status")) for h in hbas}),
        "hba_pairs": sorted((str(h.get("id") or h.get("name")), str(h.get("link_status"))) for h in hbas),
        "link_notices": sorted(m for m in msgs if "링크 상태" in m),
        "power_off": [m for m in msgs if m.startswith(POWER_OFF)],
        "unknown": [f"{i.get('id')} {i.get('mac')}" for i in ifaces if i.get("link_status") == "unknown"],
        "logical_threads": int("logical_threads" in (data.get("cpu") or {})),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--ref")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = Path(a.root)
    labels = sorted(p.name for p in root.iterdir() if (p / "gather_output.json").exists())
    md = [f"# Tier 1 불변 항목 · 남은 미확정 값 — `{a.root}`", ""]
    if a.ref:
        md += [f"- 기준: `{a.ref}`", ""]
    md += ["| label | status | HBA 수 | HBA link 값 | 링크 notice | 전원 Off notice | logical_threads | 기준과 HBA 같음 | link unknown interfaces |",
           "|---|---|---|---|---|---|---|---|---|"]
    bad = []
    for lb in labels:
        f = facts(_last_envelope(root / lb / "gather_output.json") or {})
        same = "-"
        if a.ref:
            r = facts(_last_envelope(Path(a.ref) / lb / "gather_output.json") or {})
            same = "같음" if (f["hba_pairs"], f["link_notices"]) == (r["hba_pairs"], r["link_notices"]) else "다름"
            if same == "다름":
                bad.append(f"{lb}: HBA 값 · 링크 notice 가 기준과 다름")
        if not set(f["hba_links"]) <= {"up", "down"}:
            bad.append(f"{lb}: HBA link 값 {f['hba_links']}")
        if f["logical_threads"]:
            bad.append(f"{lb}: data.cpu.logical_threads 존재")
        md.append(f"| {lb} | {f['status']} | {f['hba_n']} | {', '.join(f['hba_links']) or '-'} | {len(f['link_notices'])} | "
                  f"{len(f['power_off'])} | {f['logical_threads']} | {same} | {'; '.join(f['unknown']) or '-'} |")
        for m in f["power_off"]:
            md.append(f"|  | 전원 Off 문구 | | | | `{m}` | | | |")
    md += ["", f"- 위반: {len(bad)}건"] + [f"  - {b}" for b in bad]
    Path(a.out).write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
