"""CSUS 미러의 PCIeDevice 카드 단위 링크 조건(`Status.Conditions[].MessageId` = `H3Alert.<ver>.LinkUp|LinkDown`)을 센다 (2026-10-28 — stdlib, 읽기 전용).

구현 측 evidence 07 · 처분 03-storage-004 의 "59 카드 조건" 을 미러 원문으로 다시 센다(독립 검증 부록 A: 실측 49).
미러 트리의 `index.json` 본문만 읽는다 — 같은 `@odata.id` 는 1번만 센다. 카드 종류(FC/NIC/RAID 등)는 가리지 않는다(evidence 07 과 같은 기준).

사용: python -I -X utf8 csus_card_conditions.py <label>=<mirror_dir> [...] --out <md>
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

LINK = re.compile(r"^H3Alert\.[0-9.]+\.(LinkUp|LinkDown)$")


def scan(root: Path):
    seen, cards = set(), []
    for fp in sorted(root.rglob("index.json")):
        try:
            body = json.loads(fp.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(body, dict) or not str(body.get("@odata.type", "")).startswith("#PCIeDevice."):
            continue
        oid = str(body.get("@odata.id") or fp.parent.as_posix()).rstrip("/").lower()
        if oid in seen:
            continue
        seen.add(oid)
        conds = [c.get("MessageId") for c in ((body.get("Status") or {}).get("Conditions") or []) if isinstance(c, dict)]
        links = [m for m in conds if isinstance(m, str) and LINK.match(m)]
        if links:
            cards.append((body.get("@odata.id"), body.get("Name"), links))
    return len(seen), cards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    md = ["| label | PCIeDevice 수 | 링크 조건 카드 수 | LinkUp | LinkDown |", "|---|---|---|---|---|"]
    total = Counter()
    detail = []
    for t in a.targets:
        label, _, d = t.partition("=")
        n, cards = scan(Path(d))
        c = Counter(m.rsplit(".", 1)[-1] for _, _, links in cards for m in links)
        total.update({"cards": len(cards), **c})
        md.append(f"| {label} | {n} | {len(cards)} | {c['LinkUp']} | {c['LinkDown']} |")
        detail += [f"- {label} `{oid}` {name}: {', '.join(links)}" for oid, name, links in cards]
    md.append(f"| 합 | | {total['cards']} | {total['LinkUp']} | {total['LinkDown']} |")
    Path(a.out).write_text("\n".join(md + ["", "## 카드 목록", ""] + detail) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
