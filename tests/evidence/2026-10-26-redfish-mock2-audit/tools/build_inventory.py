"""2차 Mock 11대 전수 인벤토리 (기계 판독 JSON + Markdown 요약). 원본은 읽기만 한다.
사용: python build_inventory.py <extract_root> <out_dir> [--tier1-root <dir>] [--coverage-root <dir>]
자원 단위 레코드: path(URL), dir, kind(json/raw/empty/manifest-only), status, bytes, sha256, json_ok, odata_type, odata_id,
  members, has_nextlink, links_keys, oem_keys, actions_keys, referrer(manifest), bucket(ok/absent/not_gettable/rejected/
  outside_account/device_error/excluded/skipped), requested_tier1(bool), classification.
classification: exists(2xx JSON) / not_mounted(2xx 이지만 Members 0 또는 빈 컬렉션) / not_supported(404·405·501·410) /
  collect_error(5xx·timeout·0) / rejected(400·406) / outside_account(401·403) / binary_or_non_json / link_untracked(2xx 인데 gather 미요청) / parser_gap(요청했지만 envelope 미반영 — 작업자 판단, 여기서는 표시 안 함)
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "server"))
os.environ.setdefault("SE_REPO_ROOT", r"C:\github\ClovirONE\clovirone-server-gathering")
from mirror_policy import rfm  # noqa: E402


def sha256(p: Path):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_json(p: Path):
    try:
        with open(p, encoding="utf-8") as f:
            return True, json.load(f)
    except (OSError, ValueError):
        return False, None


def classify(rec):
    st = rec.get("status")
    if rec.get("bucket") in ("excluded", "skipped"):
        return "excluded_or_skipped_policy"
    if rec["kind"] == "raw":
        return "binary_or_non_json"
    if st is None or st == 0:
        return "collect_error"
    if 200 <= st < 300:
        if rec.get("members") == 0 and rec.get("odata_type", "").endswith("Collection"):
            return "not_mounted_or_empty"
        return "exists"
    if st in (404, 405, 410, 501):
        return "not_supported"
    if st in (400, 406, 415, 422):
        return "rejected"
    if st in (401, 403):
        return "outside_account"
    if st >= 500:
        return "collect_error"
    return "other"


def inventory_server(server_dir: Path, requested: set, coverage: dict | None):
    recs = {}
    okf, fs = load_json(server_dir / "_fsmap.json")
    fsmap = (fs or {}).get("paths", {}) if okf else {}
    okl, ln = load_json(server_dir / "_links.json")
    links = (ln or {}).get("paths", {}) if okl else {}
    okm, man = load_json(server_dir / "_manifest.json")
    man = man if okm and isinstance(man, dict) else {}
    # 1) 트리 항목 (2xx + raw)
    for path, ent in fsmap.items():
        d = server_dir / ent.get("dir", "")
        rec = {"path": path, "dir": ent.get("dir"), "kind": ent.get("type"), "key": rfm._key_of(path)}
        hp = d / "headers.json"
        okh, hh = load_json(hp)
        rec["status"] = int(hh.get("_status", 200)) if okh and isinstance(hh, dict) and str(hh.get("_status", "200")).lstrip("-").isdigit() else (200 if okh else None)
        rec["content_type"] = (hh or {}).get("Content-Type") if okh else None
        ip = d / "index.json"
        if ent.get("type") == "raw":
            okj, stub = load_json(ip)
            stub = stub if isinstance(stub, dict) else {}
            rawf = d / (stub.get("_raw_file") or "raw.bin")
            rec.update({"bytes": rawf.stat().st_size if rawf.exists() else None, "sha256": sha256(rawf) if rawf.exists() else None,
                        "raw_content_type": stub.get("_content_type"), "raw_file": stub.get("_raw_file"), "json_ok": False})
        else:
            if ip.exists():
                rec["bytes"] = ip.stat().st_size
                rec["sha256"] = sha256(ip)
                okj, body = load_json(ip)
                rec["json_ok"] = bool(okj and isinstance(body, dict))
                if rec["json_ok"]:
                    rec["odata_type"] = body.get("@odata.type")
                    rec["odata_id"] = body.get("@odata.id")
                    rec["empty"] = body.get("_empty") is True
                    m = body.get("Members")
                    rec["members"] = len(m) if isinstance(m, list) else None
                    rec["members_count_declared"] = body.get("Members@odata.count") if isinstance(body.get("Members@odata.count"), int) else None
                    rec["has_nextlink"] = isinstance(body.get("Members@odata.nextLink"), str)
                    rec["links_keys"] = sorted(body["Links"].keys()) if isinstance(body.get("Links"), dict) else []
                    rec["oem_keys"] = sorted(body["Oem"].keys()) if isinstance(body.get("Oem"), dict) else []
                    rec["actions_keys"] = sorted(body["Actions"].keys()) if isinstance(body.get("Actions"), dict) else []
                    rec["top_keys"] = len(body)
            else:
                rec.update({"bytes": None, "sha256": None, "json_ok": False, "missing_file": True})
        li = links.get(path) or {}
        rec["referrer"] = li.get("referrer")
        rec["link_kind"] = li.get("kind")
        rec["refs"] = li.get("refs")
        rec["bucket"] = "ok"
        recs[path] = rec
    # 2) manifest 비-2xx / 제외 / skip 항목
    for name in ("absent", "not_gettable", "rejected", "outside_account", "device_error", "oversize", "unresolved", "excluded", "skipped"):
        for e in man.get(name) or []:
            if not isinstance(e, dict):
                continue
            path = e.get("path") or e.get("link")
            if not path or path in recs:
                if path in recs:
                    recs[path]["bucket"] = name
                continue
            st = e.get("status")
            try:
                st = int(st)
            except (TypeError, ValueError):
                st = None
            recs[path] = {"path": path, "dir": None, "kind": "manifest-only", "key": rfm._key_of(path) if isinstance(path, str) else None,
                          "status": st, "bucket": name, "referrer": e.get("referrer"), "link_kind": e.get("kind"),
                          "error": (e.get("error") or e.get("reason") or e.get("detail") or "")[:160], "cause": e.get("cause"),
                          "json_ok": False, "bytes": None}
    # 3) 요청 여부 + 분류
    for path, rec in recs.items():
        k = rec.get("key")
        rec["requested_tier1"] = (k in requested) if k is not None else False
        c = classify(rec)
        if c == "exists" and not rec["requested_tier1"]:
            c = "exists_untouched"
        rec["classification"] = c
    cov = None
    if coverage:
        cov = {"requested": coverage.get("requested"), "untouched": coverage.get("untouched"), "exposed": coverage.get("exposed")}
    summary = {
        "server": server_dir.name, "resources": len(recs),
        "by_kind": dict(Counter(r["kind"] for r in recs.values())),
        "by_bucket": dict(Counter(r["bucket"] for r in recs.values())),
        "by_status": dict(Counter(str(r.get("status")) for r in recs.values())),
        "by_classification": dict(Counter(r["classification"] for r in recs.values())),
        "json_parse_fail_2xx": sorted(p for p, r in recs.items() if r["kind"] == "json" and r.get("status") and 200 <= r["status"] < 300 and not r.get("json_ok")),
        "requested_tier1_distinct": len({r["key"] for r in recs.values() if r["requested_tier1"]}),
        "requested_but_not_in_mirror": sorted(k for k in requested if k not in {r.get("key") for r in recs.values()}),
        "odata_types_untouched": dict(Counter((r.get("odata_type") or "?").split(".")[0].lstrip("#") for r in recs.values() if r["classification"] == "exists_untouched").most_common(60)),
        "odata_types_all": dict(Counter((r.get("odata_type") or "?").split(".")[0].lstrip("#") for r in recs.values() if r.get("json_ok")).most_common(80)),
        "manifest": {k: man.get(k) for k in ("result", "exit_code", "discovered", "fetched_ok", "root_product", "root_redfish_version", "auth_mode", "incomplete_reasons", "firmware_versions")},
        "coverage_tool": cov,
    }
    return recs, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("extract_root")
    ap.add_argument("out_dir")
    ap.add_argument("--tier1-root", default=None)
    ap.add_argument("--coverage-root", default=None)
    a = ap.parse_args()
    root = Path(a.extract_root)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summaries = []
    for sdir in sorted(p for p in root.iterdir() if p.is_dir()):
        requested = set()
        if a.tier1_root:
            acc = Path(a.tier1_root) / sdir.name / "server_access.jsonl"
            if acc.exists():
                for line in acc.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        q = json.loads(line)
                        if q.get("k") is not None and q.get("k") != "/redfish":
                            requested.add(q["k"])
        coverage = None
        if a.coverage_root:
            cp = Path(a.coverage_root) / f"{sdir.name}.json"
            if cp.exists():
                okc, coverage = load_json(cp)
        t0 = time.time()
        recs, summary = inventory_server(sdir, requested, coverage)
        summary["elapsed_s"] = round(time.time() - t0, 1)
        with open(out / f"{sdir.name}.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump({"summary": summary, "resources": [recs[k] for k in sorted(recs)]}, f, ensure_ascii=False, indent=1)
        summaries.append(summary)
        print(json.dumps({k: summary[k] for k in ("server", "resources", "by_classification", "requested_tier1_distinct", "elapsed_s")}, ensure_ascii=False), flush=True)
    with open(out / "_summaries.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
