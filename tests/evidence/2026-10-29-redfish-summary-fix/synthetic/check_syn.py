# -*- coding: utf-8 -*-
"""Tier 1 합성 미러 판정 (2026-10-29) — expected.json(사전 등록) 대 실제 봉투.

수집 코드(redfish_gather.py · normalize_standard.yml)를 import 하지 않는다. 봉투 JSON · 미러 접근 로그만 읽는다.

사용:
  python -I -X utf8 -B check_syn.py <expected.json> --head <head out root> --base <base out root>
         --head-ref <수정 전 미러 · HEAD 코드 out root> --base-ref <수정 전 미러 · base 코드 out root>
         --out-md <md> --out-json <json>
판정: 각 단정 PASS/FAIL. head 단정이 하나라도 FAIL 이면 그 case 는 FAIL(base 단정은 결함 재현 여부 — 판정과 분리해 보고).
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

VOLATILE_PREFIXES = ("meta.started_at", "meta.finished_at", "meta.duration_ms")  # diff_tier1.py 와 같다
MIRROR_REAL_NOTES = {"tree", "tree-empty", "manifest", "raw"}
_SEG = re.compile(r"([^.\[\]]+)|\[(\d+)\]|\[([^\]=]+)=([^\]]*)\]")


def load_env(root, label):
    p = Path(root) / label / "gather_output.json"
    env = json.loads(p.read_text(encoding="utf-8"))
    return env[0] if isinstance(env, list) else env


def resolve(env, path):
    """'a.b[0].c' · 'a.b[k=v].c' · 'len(a.b)' -> (found, value)."""
    want_len = path.startswith("len(") and path.endswith(")")
    if want_len:
        path = path[4:-1]
    cur = env
    for m in _SEG.finditer(path):
        key, idx, sk, sv = m.groups()
        if key is not None:
            if not isinstance(cur, dict) or key not in cur:
                return False, None
            cur = cur[key]
        elif idx is not None:
            i = int(idx)
            if not isinstance(cur, list) or i >= len(cur):
                return False, None
            cur = cur[i]
        else:
            if not isinstance(cur, list):
                return False, None
            hits = [x for x in cur if isinstance(x, dict) and str(x.get(sk)) == sv]
            if len(hits) != 1:
                return False, ("selector hits=%d" % len(hits))
            cur = hits[0]
    if want_len:
        return (True, len(cur)) if isinstance(cur, (list, dict)) else (False, None)
    return True, cur


def canon(v):
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def check_assert(env, a):
    found, val = resolve(env, a["path"])
    if not found:
        return "FAIL", "path not found (%s)" % (val,)
    if "eq" in a:
        ok = canon(val) == canon(a["eq"])
    else:
        ok = sorted(canon(x) for x in (val or [])) == sorted(canon(x) for x in a["eq_sorted"])
    return ("PASS" if ok else "FAIL"), canon(val)


def notices(env):
    return ((env.get("diagnosis") or {}).get("details") or {}).get("notices") or []


def check_notice(env, n, absent=False):
    subs = n["contains"] if isinstance(n["contains"], list) else [n["contains"]]
    hits = [x for x in notices(env) if x.get("section") == n["section"]
            and all(s in (x.get("message") or "") for s in subs)]
    if absent:
        return ("PASS" if not hits else "FAIL"), "%d hit(s)" % len(hits)
    return ("PASS" if hits else "FAIL"), (hits[0]["message"] if hits else "no matching notice")


def access(root, label):
    out = {}
    p = Path(root) / label / "server_access.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out.setdefault(r.get("k"), set()).add(r.get("n"))
    return out


def flatten(o, p="", out=None):
    out = {} if out is None else out
    if isinstance(o, dict):
        if not o:
            out[p] = "{}"
        for k in sorted(o):
            flatten(o[k], "%s.%s" % (p, k) if p else k, out)
    elif isinstance(o, list):
        if not o:
            out[p] = "[]"
        for i, v in enumerate(o):
            flatten(v, "%s[%d]" % (p, i), out)
    else:
        out[p] = canon(o)
    return out


def diff_paths(a, b):
    fa, fb = flatten(a), flatten(b)
    return sorted(k for k in set(fa) | set(fb)
                  if fa.get(k) != fb.get(k) and not k.startswith(VOLATILE_PREFIXES))


def _allowed(path, prefixes):
    return any(path == p or path.startswith(p + ".") or path.startswith(p + "[") for p in prefixes)


def run_case(name, c, roots):
    res = {"case": name, "sa": c["sa"], "base_label": c["base_label"], "head": [], "base": [], "extra": []}
    he, be = load_env(roots.head, name), load_env(roots.base, name)
    for a in c.get("head", []):
        v, got = check_assert(he, a)
        res["head"].append({"check": a["path"], "verdict": v, "expected": a.get("eq", a.get("eq_sorted")), "got": got})
    for n in c.get("head_notices", []):
        v, got = check_notice(he, n)
        res["head"].append({"check": "notice[%s] ⊇ %s" % (n["section"], n["contains"]), "verdict": v, "got": got})
    for n in c.get("head_notices_absent", []):
        v, got = check_notice(he, n, absent=True)
        res["head"].append({"check": "no notice[%s] ~ %s" % (n["section"], n["contains"]), "verdict": v, "got": got})
    acc = access(roots.head, name)
    for k in c.get("head_requests_absent", []):
        res["head"].append({"check": "no GET %s" % k, "verdict": "PASS" if k not in acc else "FAIL", "got": sorted(acc.get(k, []))})
    for k in c.get("head_requests_present", []):
        res["head"].append({"check": "GET %s" % k, "verdict": "PASS" if k in acc else "FAIL", "got": sorted(acc.get(k, []))})
    for k in c.get("head_requests_present_tree", []):
        notes = acc.get(k, set())
        ok = bool(notes) and notes <= MIRROR_REAL_NOTES
        res["head"].append({"check": "GET %s (미러 실응답)" % k, "verdict": "PASS" if ok else "FAIL", "got": sorted(notes)})
    href = load_env(roots.head_ref, c["base_label"])
    for p in c.get("head_same_as_unmodified", []):
        fa, va = resolve(he, p)
        fb, vb = resolve(href, p)
        ok = fa and fb and canon(va) == canon(vb)
        res["head"].append({"check": "%s == 수정 전 미러 출력" % p, "verdict": "PASS" if ok else "FAIL", "got": "same" if ok else "differs"})
    if "only_diffs_vs_unmodified" in c:
        allow = c["only_diffs_vs_unmodified"]
        for side, env, ref in (("head", he, href), ("base", be, load_env(roots.base_ref, c["base_label"]))):
            d = diff_paths(ref, env)
            bad = [p for p in d if not _allowed(p, allow)]
            res[side].append({"check": "수정 전 미러 출력 대비 차이 ⊆ %s" % allow, "verdict": "PASS" if not bad else "FAIL",
                              "got": {"diff_paths": d, "outside_allow": bad}})
    for a in c.get("base", []):
        v, got = check_assert(be, a)
        res["base"].append({"check": a["path"], "verdict": v, "expected": a.get("eq", a.get("eq_sorted")), "got": got})
    for n in c.get("base_notices_absent", []):
        v, got = check_notice(be, n, absent=True)
        res["base"].append({"check": "no notice[%s] ~ %s" % (n["section"], n["contains"]), "verdict": v, "got": got})
    res["extra"] = [{"status_head": he.get("status"), "status_base": be.get("status"),
                     "errors_head": len(he.get("errors") or []), "errors_base": len(be.get("errors") or [])}]
    res["verdict"] = "PASS" if all(x["verdict"] == "PASS" for x in res["head"]) else "FAIL"
    res["defect_reproduced_on_base"] = all(x["verdict"] == "PASS" for x in res["base"])
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("expected")
    for k in ("head", "base", "head-ref", "base-ref", "out-md", "out-json"):
        ap.add_argument("--" + k, required=True)
    roots = ap.parse_args()
    exp_bytes = Path(roots.expected).read_bytes()
    exp = json.loads(exp_bytes.decode("utf-8"))
    results = [run_case(n, exp["cases"][n], roots) for n in sorted(exp["cases"])]
    doc = {"expected_sha256": hashlib.sha256(exp_bytes).hexdigest(), "results": results}
    Path(roots.out_json).write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# Tier 1 합성 미러 판정", "", "expected.json sha256 `%s`" % doc["expected_sha256"], "",
             "| case | SA | head 판정 | base 에서 결함 재현 | status head/base |", "|---|---|---|---|---|"]
    for r in results:
        x = r["extra"][0]
        lines.append("| %s | %s | %s | %s | %s / %s |" % (r["case"], " · ".join(r["sa"]), r["verdict"],
                     "예" if r["defect_reproduced_on_base"] else "아니오", x["status_head"], x["status_base"]))
    for r in results:
        lines += ["", "## %s (%s)" % (r["case"], r["base_label"])]
        for side in ("head", "base"):
            for x in r[side]:
                got = x.get("got")
                got = got if isinstance(got, str) else canon(got)
                lines.append("- [%s] %s `%s` → %s" % (side, x["verdict"], x["check"], got[:300]))
    Path(roots.out_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    bad = [r["case"] for r in results if r["verdict"] != "PASS"]
    print("cases=%d head_fail=%s" % (len(results), bad or 0))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
