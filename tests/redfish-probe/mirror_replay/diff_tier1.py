"""두 Tier 1 산출 트리(before/after)의 최종 봉투와 요청 집합을 label 마다 대조하고, 허용목록 밖의 차이를 찾는다.

사용: python diff_tier1.py <before_root> <after_root> [--allow allow.json] [--labels a,b] [--out report.md]
      종료 코드 1 = 허용목록으로 설명되지 않는 차이가 1건 이상.

허용목록(JSON 배열) 항목:
  {"labels": ["sr650_v4_01", ...] 또는 "*", "path_prefix": "data.cpu.logical_threads" 또는 "path_re": "^data\\.thermal\\.temperatures\\[",
   "request_prefix": "Chassis/RackGroup/" (요청 집합 차이용, 선택), "issue": "02-cpu-001", "note": "..."}
- 봉투 경로는 점 표기 + 리스트 인덱스([n])다. prefix 는 인덱스 앞까지 적으면 그 리스트 전체를 덮는다.
- 휘발 경로(meta.started_at/finished_at/duration_ms, diagnosis.details.auth.* 의 시각류)는 비교에서 뺀다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VOLATILE_PREFIXES = ("meta.started_at", "meta.finished_at", "meta.duration_ms")


def _flatten(obj, prefix="", out=None):
    if out is None:
        out = {}
    if isinstance(obj, dict):
        if not obj:
            out[prefix or "<root>"] = {}
        for k, v in obj.items():
            _flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list):
        if not obj:
            out[prefix] = []
        for i, v in enumerate(obj):
            _flatten(v, f"{prefix}[{i}]", out)
    else:
        out[prefix] = obj
    return out


def _last_envelope(path: Path):
    if not path.exists():
        return None
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except ValueError:
        return None


def _requested(path: Path):
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return set(d.get("distinct_keys") or [])


def _allowed(entry, label, path=None, request=None):
    labels = entry.get("labels", "*")
    if labels != "*" and label not in (labels or []):
        return False
    if path is not None:
        pre = entry.get("path_prefix")
        rx = entry.get("path_re")
        if pre and path.startswith(pre):
            return True
        if rx and re.search(rx, path):
            return True
        return False
    if request is not None:
        rp = entry.get("request_prefix")
        rr = entry.get("request_re")
        if rp and request.startswith(rp):
            return True
        if rr and re.search(rr, request):
            return True
    return False


def diff_label(label, before_dir: Path, after_dir: Path, allow):
    b = _last_envelope(before_dir / "gather_output.json")
    a = _last_envelope(after_dir / "gather_output.json")
    res = {"label": label, "missing": [], "explained": [], "unexplained": [], "req_added": [], "req_removed": [],
           "req_unexplained": []}
    if b is None or a is None:
        res["missing"].append("before" if b is None else "after")
        return res
    fb, fa = _flatten(b), _flatten(a)
    paths = sorted(set(fb) | set(fa))
    for p in paths:
        if p.startswith(VOLATILE_PREFIXES):
            continue
        vb, va = fb.get(p, "<absent>"), fa.get(p, "<absent>")
        if vb == va:
            continue
        hit = next((e for e in allow if _allowed(e, label, path=p)), None)
        item = {"path": p, "before": vb, "after": va}
        if hit:
            item["issue"] = hit.get("issue")
            res["explained"].append(item)
        else:
            res["unexplained"].append(item)
    rb, ra = _requested(before_dir / "requested_keys.json"), _requested(after_dir / "requested_keys.json")
    if rb is not None and ra is not None:
        for k in sorted(ra - rb):
            res["req_added"].append(k)
            if not any(_allowed(e, label, request=k) for e in allow):
                res["req_unexplained"].append("+" + k)
        for k in sorted(rb - ra):
            res["req_removed"].append(k)
            if not any(_allowed(e, label, request=k) for e in allow):
                res["req_unexplained"].append("-" + k)
    return res


def _short(v):
    s = json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= 80 else s[:77] + "..."


def render(results):
    lines = ["| label | 변경(설명됨) | 변경(미설명) | 요청 +/- | 요청 미설명 |", "|---|---|---|---|---|"]
    for r in results:
        if r["missing"]:
            lines.append(f"| {r['label']} | - | - | - | **{r['missing']} 산출 없음** |")
            continue
        lines.append(f"| {r['label']} | {len(r['explained'])} | {len(r['unexplained'])} | "
                     f"+{len(r['req_added'])}/-{len(r['req_removed'])} | {len(r['req_unexplained'])} |")
    for r in results:
        if r["unexplained"] or r["req_unexplained"]:
            lines.append(f"\n### {r['label']} — 허용목록 밖")
            for it in r["unexplained"][:200]:
                lines.append(f"- `{it['path']}`: {_short(it['before'])} -> {_short(it['after'])}")
            for k in r["req_unexplained"][:200]:
                lines.append(f"- 요청 {k}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before_root")
    ap.add_argument("after_root")
    ap.add_argument("--allow", default=None)
    ap.add_argument("--labels", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    allow = []
    if a.allow:
        allow = json.loads(Path(a.allow).read_text(encoding="utf-8"))
        assert isinstance(allow, list)
    before, after = Path(a.before_root), Path(a.after_root)
    labels = a.labels.split(",") if a.labels else sorted({p.name for p in after.iterdir() if p.is_dir()})
    results = [diff_label(lb, before / lb, after / lb, allow) for lb in labels]
    md = render(results)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
    sys.stdout.write(md)
    bad = any(r["unexplained"] or r["req_unexplained"] or r["missing"] for r in results)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
