"""Tier 1 base→after 에서 새로 생긴 GET 경로마다 미러 접근 로그(server_access.jsonl)의 status · note 를 모은다 (읽기 전용)."""
import json, sys
from pathlib import Path
base, after = Path(sys.argv[1]), Path(sys.argv[2])
REAL = {"tree", "tree-empty", "manifest", "raw"}
LIMIT = {"unknown", "raw-missing", "outside-redfish-v1"}
rows = []
for lab in sorted(p.name for p in after.iterdir() if p.is_dir()):
    rb = set(json.loads((base / lab / "requested_keys.json").read_text(encoding="utf-8")).get("distinct_keys") or [])
    ra = set(json.loads((after / lab / "requested_keys.json").read_text(encoding="utf-8")).get("distinct_keys") or [])
    acc = [json.loads(l) for l in (after / lab / "server_access.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    for k in sorted(ra - rb):
        hits = [(a["s"], a["n"]) for a in acc if a.get("k") == k]
        notes = sorted({n for _, n in hits})
        sts = sorted({s for s, _ in hits})
        cls = "MIRROR_REAL" if notes and set(notes) <= REAL else ("MOCK_LIMITATION" if set(notes) & LIMIT else "?")
        rows.append({"label": lab, "path": k, "status": sts, "note": notes, "class": cls, "hits": len(hits)})
for r in rows:
    print(json.dumps(r, ensure_ascii=False))
print("classes:", {c: sum(1 for r in rows if r["class"] == c) for c in {r["class"] for r in rows}})
