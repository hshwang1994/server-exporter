"""Redfish `LinkStatus` 값 분포를 센다 (2026-10-28 — stdlib, 읽기 전용).

HBA 링크 up 값을 표준 값으로 한정한 변경(02-hba-link-policy.md)의 출력 영향을 확인한다:
`Enabled` · `Active` · `Connected` 가 실제 `LinkStatus` 값으로 나오는지.

- 키가 정확히 `LinkStatus` 인 값만 링크 값으로 센다(재귀). 상위 `@odata.type` 형식별로 나눈다.
- 키가 `..._LinkStatus` 로 끝나는 값(BIOS 속성)은 Redfish 링크 키가 아니므로 따로 센다.
- 같은 `@odata.id` 본문은 1번만 센다(미러: label 안, fixture: 파일 안).
- fixture 의 `expected_output.json`(골든 — 수집기 출력)은 원문이 아니므로 세지 않는다.

사용: python -I -X utf8 -B linkstatus_values.py --fixtures <tests/fixtures> [<label>=<mirror_dir> ...] --out <md>
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


class Tally:
    def __init__(self):
        self.exact = Counter()
        self.by_type = defaultdict(Counter)
        self.suffix = Counter()

    def walk(self, node, seen, otype=None):
        """seen: 이 범위(미러 label · fixture 파일)에서 이미 센 본문의 `@odata.id` — 펼쳐진 하위 본문도 1번만."""
        if isinstance(node, dict):
            oid = node.get("@odata.id")
            if isinstance(oid, str) and "@odata.type" in node:
                key = oid.rstrip("/").lower()
                if key in seen:
                    return
                seen.add(key)
            t = node.get("@odata.type") if isinstance(node.get("@odata.type"), str) else otype
            for k, v in node.items():
                if k == "LinkStatus" and not isinstance(v, (dict, list)):
                    val = "null" if v is None else str(v)
                    self.exact[val] += 1
                    self.by_type[val][(t or "-").lstrip("#").split(".")[0]] += 1
                elif isinstance(k, str) and k.endswith("_LinkStatus") and not isinstance(v, (dict, list)):
                    self.suffix["null" if v is None else str(v)] += 1
                else:
                    self.walk(v, seen, t)
        elif isinstance(node, list):
            for x in node:
                self.walk(x, seen, otype)


def scan_mirror(root: Path, tally: Tally):
    seen = set()
    for fp in sorted(root.rglob("index.json")):
        try:
            body = json.loads(fp.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(body, dict):
            continue
        if not body.get("@odata.id") or "@odata.type" not in body:
            body = {"@odata.id": fp.parent.as_posix(), "@odata.type": "#-", "_": body}
        tally.walk(body, seen)


def scan_fixtures(root: Path, tally: Tally):
    for fp in sorted(root.rglob("*.json")):
        if fp.name == "expected_output.json":
            continue
        try:
            text = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "LinkStatus" not in text:
            continue
        try:
            data = json.loads(text)
        except ValueError:
            continue
        tally.walk(data, set())


def table(title, tally: Tally):
    md = [f"## {title}", "", "| `LinkStatus` 값 | 수 | 상위 리소스 형식 |", "|---|---|---|"]
    for v, n in tally.exact.most_common():
        md.append(f"| {v} | {n} | " + ", ".join(f"{t} {c}" for t, c in tally.by_type[v].most_common()) + " |")
    hit = {v: tally.exact.get(v, 0) for v in ("Enabled", "Active", "Connected")}
    md += ["", "- `Enabled` · `Active` · `Connected`: " + " · ".join(f"{k} {n}" for k, n in hit.items()),
           "- 키가 `..._LinkStatus` 로 끝남(BIOS 속성 — 링크 키 아님): "
           + (", ".join(f"{v} {n}" for v, n in tally.suffix.most_common()) or "없음"), ""]
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mirrors", nargs="*")
    ap.add_argument("--fixtures")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    md = ["# Redfish `LinkStatus` 값 분포", ""]
    if a.mirrors:
        t = Tally()
        for m in a.mirrors:
            _label, _, d = m.partition("=")
            scan_mirror(Path(d), t)
        md += table(f"미러 원문 {len(a.mirrors)} label", t)
    if a.fixtures:
        t = Tally()
        scan_fixtures(Path(a.fixtures), t)
        md += table("저장소 fixture (골든 제외)", t)
    Path(a.out).write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
