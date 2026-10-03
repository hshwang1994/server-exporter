"""E2E evidence for promotion (2026-10-04, Astra 3차 §8-2 · 4차 §2).

A verify report proves gates; it does not prove the pipeline ran. Promotion additionally needs structured evidence that the
required main-Job scenarios and Harness scenarios passed **for the same main SHA**. This module
  - collects it read-only from Jenkins (build result · checkout SHA · parameters · harness_result.json verdict),
  - checks it (required scenarios present, pass, same SHA),
  - aggregates it into a verify report and recomputes the report digest (the digest is a mix-up detector, not proof).

Scenario → pass rule
  main Job scenarios (S1 S2 S3 T2 T5 T6 E2E-A E2E-A2 …): `expected_result` per entry (SUCCESS by default; T6 UNSTABLE; T5 ABORTED).
    A scenario PASS is *not* "the build was SUCCESS" — it is "the build ended as that scenario expects".
  Harness scenarios: artifact harness_result.json verdict == PASS.
Entry syntax (CLI): SCENARIO=<job path>:<build>[:<EXPECTED_RESULT>], e.g. S1=clovirone-cicd/clovirone-server-gather-main:7
  or normal_success=clovirone-cicd/clovirone-server-gather-harness:12
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess

from .common import ProdgenError
from .verify import canonical_digest, report_digest_ok

REQUIRED_MAIN = ("S1", "S2", "S3", "T2", "T5", "T6", "E2E-A", "E2E-A2")
REQUIRED_HARNESS = ("normal_success", "archive_fail", "stash_fail", "both_fail", "truncate_jsonl", "checkpoint_only_a",
                    "checkpoint_only_b", "layer_a_fail", "raw_fallback", "report_corrupt", "sink_5xx", "outer_timeout")
HARNESS_MARKER = "harness"


def _curl_json(url: str, netrc: str) -> dict:
    curl = shutil.which("curl")
    if not curl:
        raise ProdgenError("curl not available for the Jenkins read")
    proc = subprocess.run([curl, "-sk", "--netrc-file", netrc, "--max-time", "60", url], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ProdgenError(f"Jenkins read failed: {url} rc={proc.returncode}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise ProdgenError(f"Jenkins read is not JSON: {url}: {exc}") from exc


def parse_entry(entry: str) -> dict:
    if "=" not in entry or ":" not in entry.split("=", 1)[1]:
        raise ProdgenError(f"bad evidence entry {entry!r} — expected SCENARIO=job/path:build[:EXPECTED]")
    scenario, rest = entry.split("=", 1)
    parts = rest.split(":")
    job, build = parts[0], parts[1]
    expected = parts[2] if len(parts) > 2 else ("PASS" if HARNESS_MARKER in job else "SUCCESS")
    return {"scenario": scenario.strip(), "job": job.strip(), "build": int(build), "expected": expected.strip().upper()}


def collect(jenkins_url: str, netrc: str, entries: list) -> dict:
    base = jenkins_url.rstrip("/")
    items = []
    for raw in entries:
        e = parse_entry(raw) if isinstance(raw, str) else raw
        job_path = "/".join(f"job/{p}" for p in e["job"].split("/"))
        url = f"{base}/{job_path}/{e['build']}"
        info = _curl_json(f"{url}/api/json?tree=number,result,building,url,actions[lastBuiltRevision[SHA1],parameters[name,value]]", netrc)
        sha, params = None, {}
        for a in info.get("actions", []) or []:
            if a.get("lastBuiltRevision"):
                sha = a["lastBuiltRevision"].get("SHA1")
            for p in a.get("parameters", []) or []:
                params[p.get("name")] = p.get("value")
        item = {"scenario": e["scenario"], "job": e["job"], "build": e["build"], "url": info.get("url") or url,
                "result": info.get("result"), "building": info.get("building"), "checkout_sha": sha,
                "expected": e["expected"], "params": {k: params[k] for k in ("loc", "target_type", "SCENARIO", "MAIN_SHA", "FUNCTIONS_SRC") if k in params}}
        if HARNESS_MARKER in e["job"]:
            try:
                hr = _curl_json(f"{url}/artifact/harness_result.json", netrc)
                item["harness_verdict"] = hr.get("verdict")
                item["harness_problems"] = hr.get("problems", [])[:5]
                item["functions_sha256"] = (hr.get("meta") or {}).get("functions_sha256")
            except ProdgenError as exc:
                item["harness_verdict"] = None
                item["harness_problems"] = [str(exc)]
            item["pass"] = item["harness_verdict"] == e["expected"] if e["expected"] != "SUCCESS" else item["harness_verdict"] == "PASS"
        else:
            item["pass"] = (info.get("result") == e["expected"]) and not info.get("building")
        items.append(item)
    payload = {"collected_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
               "jenkins_url": base, "items": items}
    payload["evidence_sha256"] = canonical_digest(payload)
    return payload


def check_evidence(evidence: dict, main_sha: str, required_main=REQUIRED_MAIN, required_harness=REQUIRED_HARNESS) -> list:
    """Problems list (empty = ok): every required scenario present, passed, and recorded against `main_sha`."""
    problems = []
    if not isinstance(evidence, dict) or not isinstance(evidence.get("items"), list):
        return ["evidence has no items"]
    body = {k: v for k, v in evidence.items() if k != "evidence_sha256"}
    if evidence.get("evidence_sha256") and canonical_digest(body) != evidence["evidence_sha256"]:
        problems.append("evidence_sha256 does not match the evidence body")
    by = {}
    for it in evidence["items"]:
        by.setdefault(it.get("scenario"), []).append(it)
    for sc in list(required_main) + list(required_harness):
        items = by.get(sc)
        if not items:
            problems.append(f"{sc}: no evidence")
            continue
        good = [it for it in items if it.get("pass") and it.get("checkout_sha") == main_sha]
        if not good:
            why = []
            for it in items:
                why.append(f"build {it.get('build')} result={it.get('result')} harness={it.get('harness_verdict')} sha={str(it.get('checkout_sha'))[:12]}")
            problems.append(f"{sc}: no passing evidence for main {main_sha[:12]} ({'; '.join(why)[:200]})")
    return problems


def aggregate(report_path: str, evidence_paths: list, out_path: str) -> dict:
    """Merge evidence files into a verify report's e2e_evidence and recompute the report digest."""
    with open(report_path, encoding="utf-8") as fh:
        report = json.load(fh)
    if not report_digest_ok(report):
        raise ProdgenError("verify report digest mismatch — refusing to aggregate onto a tampered/hand-edited report")
    merged = {"items": [], "sources": []}
    for p in evidence_paths:
        with open(p, encoding="utf-8") as fh:
            ev = json.load(fh)
        merged["items"].extend(ev.get("items", []))
        merged["sources"].append({"path": os.path.abspath(p), "evidence_sha256": ev.get("evidence_sha256"), "collected_at": ev.get("collected_at")})
    merged["evidence_sha256"] = canonical_digest({k: v for k, v in merged.items() if k != "evidence_sha256"})
    report["e2e_evidence"] = merged
    report.pop("report_sha256", None)
    report["report_sha256"] = canonical_digest(report)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
    return {"items": len(merged["items"]), "report_sha256": report["report_sha256"], "out": out_path}
