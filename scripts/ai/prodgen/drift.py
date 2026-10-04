"""`prodgen drift-check --production <ref> [--bootstrap-baseline <sha>]` and production *state* classification.

States (2026-10-04, Astra 3차 §7 — implemented and tested separately):
  LEGACY             : no provenance, no restore trailers (pre-prodgen production, e.g. 4ce90a00). ok only when the caller
                       names exactly this SHA as the bootstrap baseline (`--bootstrap-baseline <sha>` == ref). Never ok by default.
  PROVENANCE         : `.production-provenance.json` present -> checks C (tree hash), D (trailers), A1 (recorded generator),
                       A2 (migration preview with the current generator).
  RESTORED_BASELINE  : no provenance but the commit is a `prodgen restore` of the legacy baseline B: trailers Restore-Of/Bootstrap-Baseline,
                       tree OID == B's tree OID, B is an ancestor, and a generated production P1 (with provenance and the same
                       Bootstrap-Baseline trailer) is in the history. Re-promotion is allowed with parent R and baseline B.
  UNVERIFIED         : anything else (trailer without the tree equality, foreign tree) -> refuse.

A trailer alone never passes: RESTORED_BASELINE additionally requires the exact tree OID of B and P1 in the history.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile

from . import PROVENANCE_FILE
from .build import build
from .common import ProdgenError, sha256_bytes
from .gitstore import GitStore
from .manifest import Manifest
from .provenance import tree_hash


def _ref_files(store: GitStore, sha: str) -> dict:
    files = {}
    for e in store.ls_tree(sha):
        if e.path == PROVENANCE_FILE or e.otype != "blob":
            continue
        files[e.path] = (e.mode, sha256_bytes(store.cat_blob(e.sha)))
    return files


def is_ancestor(store: GitStore, ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=store.repo_root, capture_output=True)
    return proc.returncode == 0


def first_prodgen_commit(store: GitStore, head: str, limit: int = 200):
    """Walk first-parent history from head; return (sha, provenance dict, trailers) of the **nearest** commit with provenance
    (= the latest generated production — used for G20 ancestry). Despite the name it is not the oldest one; to find the commit
    that *recorded* a bootstrap baseline use `baseline_record` (검토 C2: the nearest generated commit P2 normally carries no
    Bootstrap-Baseline trailer, so a restore to B after B → P1 → P2 must look past P2)."""
    out = store.run(["rev-list", "--first-parent", f"--max-count={limit}", head], text=True).split()
    for sha in out:
        prov_bytes = store.cat_path(sha, PROVENANCE_FILE)
        if prov_bytes is not None:
            try:
                return sha, json.loads(prov_bytes.decode("utf-8")), GitStore.parse_trailers(store.commit_message(sha))
            except ValueError:
                continue
    return None, None, None


latest_prodgen_commit = first_prodgen_commit


def baseline_record(store: GitStore, head: str, baseline_sha: str, limit: int = 500):
    """Walk first-parent history from head; return (sha, provenance dict, trailers) of the nearest generated commit whose
    trailers record `baseline_sha` as the bootstrap baseline (`Bootstrap-Baseline`, and `Bootstrap-Baseline-Tree` == the
    baseline's tree OID when present). None when no commit in the history recorded it (→ an arbitrary legacy restore is refused)."""
    try:
        want_tree = store.commit_tree_sha(baseline_sha)
    except ProdgenError:
        return None, None, None
    out = store.run(["rev-list", "--first-parent", f"--max-count={limit}", head], text=True).split()
    for sha in out:
        trailers = GitStore.parse_trailers(store.commit_message(sha))
        if trailers.get("Bootstrap-Baseline") != baseline_sha:
            continue
        if trailers.get("Bootstrap-Baseline-Tree") and trailers["Bootstrap-Baseline-Tree"] != want_tree:
            continue
        prov_bytes = store.cat_path(sha, PROVENANCE_FILE)
        if prov_bytes is None:
            continue          # a restore commit also carries the trailer but is not the *generated* record
        try:
            return sha, json.loads(prov_bytes.decode("utf-8")), trailers
        except ValueError:
            continue
    return None, None, None


def classify_production(store: GitStore, sha: str, bootstrap_baseline: str | None = None) -> dict:
    """State of a production commit. `bootstrap_baseline` (SHA or ref) is the only thing that makes LEGACY acceptable."""
    info = {"sha": sha, "state": "UNVERIFIED", "ok": False, "tree_oid": store.commit_tree_sha(sha)}
    prov_bytes = store.cat_path(sha, PROVENANCE_FILE)
    trailers = GitStore.parse_trailers(store.commit_message(sha))
    info["trailers"] = {k: trailers[k] for k in sorted(trailers)}
    if prov_bytes is not None:
        prov = json.loads(prov_bytes.decode("utf-8"))
        info.update({"state": "PROVENANCE", "ok": True, "main_sha": prov.get("main_sha"), "tree_hash": prov.get("tree_hash"),
                     "bootstrap_baseline": trailers.get("Bootstrap-Baseline")})
        return info
    if "Restore-Of" in trailers:
        base = trailers.get("Bootstrap-Baseline") or trailers.get("Restore-Of")
        reasons = []
        try:
            base_sha = store.rev_parse(base)
        except ProdgenError:
            base_sha = None
            reasons.append(f"baseline {base} is not a commit in this repository")
        if base_sha:
            if store.commit_tree_sha(base_sha) != info["tree_oid"]:
                reasons.append("tree OID differs from the baseline's tree (not an exact legacy restore)")
            if not is_ancestor(store, base_sha, sha):
                reasons.append("baseline is not an ancestor of this commit")
            # the *latest* generated production decides ancestry (G20); the commit that *recorded* the baseline may be older (C2)
            p_latest, p_latest_prov, _ = first_prodgen_commit(store, sha)
            rec, _rec_prov, _rec_tr = baseline_record(store, sha, base_sha)
            if p_latest is None:
                reasons.append("no generated production (provenance) in the history")
            elif rec is None:
                reasons.append(f"no generated production in the history recorded this baseline ({base_sha[:12]})")
            else:
                info["previous_generated"] = p_latest
                info["previous_generated_main_sha"] = (p_latest_prov or {}).get("main_sha")
                info["baseline_recorded_by"] = rec
        info["baseline"] = base_sha or base
        if reasons:
            info["reasons"] = reasons
            return info
        info.update({"state": "RESTORED_BASELINE", "ok": True})
        return info
    # legacy: no provenance, no restore trailers
    info["state"] = "LEGACY"
    if bootstrap_baseline:
        try:
            bb = store.rev_parse(bootstrap_baseline)
        except ProdgenError:
            bb = None
        info["bootstrap_baseline_given"] = bootstrap_baseline
        if bb == sha:
            info["ok"] = True
            info["note"] = "legacy production accepted as the explicit bootstrap baseline"
        else:
            info["reasons"] = [f"--bootstrap-baseline {bootstrap_baseline} does not name the current production {sha[:12]}"]
    else:
        info["reasons"] = ["legacy production (no provenance): a normal promotion refuses it — pass --bootstrap-baseline <this sha> for the first promotion"]
    return info


def previous_generated_main(store: GitStore, production_sha: str | None):
    """Main SHA that produced the last generated production reachable from `production_sha` (for G20 ancestry). None if none."""
    if not production_sha:
        return None, None
    p1, prov, _ = first_prodgen_commit(store, production_sha)
    if p1 is None:
        return None, None
    return p1, (prov or {}).get("main_sha")


def export_tar(store: GitStore, treeish: str, paths: list) -> bytes:
    """Byte-exact `git archive` of `paths` at `treeish`. `git archive` applies core.autocrlf/core.eol like a checkout — on a Windows clone
    with autocrlf=true the exported production_manifest.yml came out CRLF and the manifest loader refused it, so the A1 check FAILED on the
    promoting workstation while passing in CI (GP-45, 2026-10-05). Blobs are LF in the index; export them as they are."""
    return store.run(["-c", "core.autocrlf=false", "-c", "core.eol=lf", "archive", "--format=tar", treeish, "--", *paths])


def drift_check(repo_root: str, production_ref: str, manifest_path: str, bootstrap_baseline: str | None = None) -> dict:
    store = GitStore(repo_root)
    sha = store.rev_parse(production_ref)
    result = {"production": sha, "ref": production_ref, "checks": {}, "ok": False}
    state = classify_production(store, sha, bootstrap_baseline)
    result["state"] = state
    result["mode"] = state["state"]
    if state["state"] != "PROVENANCE":
        if state["state"] == "LEGACY":
            manifest = Manifest.load(manifest_path)
            paths = [e.path for e in store.ls_tree(sha)]
            forbidden = sorted(p for p in paths if manifest.is_forbidden(p))
            cls = manifest.classify(paths)
            result["checks"]["legacy"] = {
                "files": len(paths), "forbidden_in_production": len(forbidden), "forbidden_sample": forbidden[:20],
                "would_be_included": len(cls.included), "not_allowlisted": len(paths) - len(cls.included),
                "note": "no provenance: production predates prodgen; checks C/D/A1 are not applicable",
            }
        result["ok"] = bool(state["ok"])
        return result

    prov_bytes = store.cat_path(sha, PROVENANCE_FILE)
    prov = json.loads(prov_bytes.decode("utf-8"))
    result["main_sha"] = prov.get("main_sha")

    # C — tree hash from the ref's blobs
    files = _ref_files(store, sha)
    recomputed = tree_hash(files)
    result["checks"]["C_tree_hash"] = {"recorded": prov.get("tree_hash"), "recomputed": recomputed,
                                       "ok": recomputed == prov.get("tree_hash"),
                                       "files_in_ref": len(files), "files_in_provenance": len(prov.get("files", {}))}

    # D — trailers
    trailers = GitStore.parse_trailers(store.commit_message(sha))
    expected = {"Main-SHA": prov.get("main_sha"), "Tree-Hash": prov.get("tree_hash"),
                "Generator-Version": prov.get("generator_version"), "Rules-Version": prov.get("rules_version")}
    mism = {k: (trailers.get(k), v) for k, v in expected.items() if trailers.get(k) != v}
    result["checks"]["D_trailers"] = {"ok": not mism, "mismatch": mism, "present": sorted(trailers)}

    # A1 — recorded generator from main history
    a1 = {"ok": None}
    main_sha = prov.get("main_sha")
    if store.cat_path(main_sha, "scripts/ai/prodgen/__init__.py") is None:
        a1["status"] = "unavailable: generator not committed at main_sha"
    else:
        with tempfile.TemporaryDirectory(prefix="prodgen-a1-") as td:
            gen_root = os.path.join(td, "gen")
            os.makedirs(gen_root)
            archive = export_tar(store, main_sha, ["scripts/ai/prodgen", "production_manifest.yml"])
            with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
                tf.extractall(gen_root)
            out = os.path.join(td, "tree")
            cmd = [sys.executable, "-m", "scripts.ai.prodgen", "--repo", store.repo_root,
                   "--manifest", os.path.join(gen_root, "production_manifest.yml"), "--json",
                   "build", "--sha", main_sha, "--out", out]
            proc = subprocess.run(cmd, cwd=gen_root, capture_output=True, text=True, encoding="utf-8", errors="replace")
            a1["rc"] = proc.returncode
            prov_path = os.path.join(out, PROVENANCE_FILE)
            if os.path.isfile(prov_path):
                with open(prov_path, encoding="utf-8") as fh:
                    regen = json.load(fh)
                a1["tree_hash"] = regen.get("tree_hash")
                a1["ok"] = regen.get("tree_hash") == prov.get("tree_hash")
                a1["status"] = "regenerated with recorded generator"
            else:
                a1["ok"] = False
                a1["status"] = "recorded generator did not produce provenance: " + proc.stderr.strip()[-300:]
    result["checks"]["A1_recorded_generator"] = a1

    # A2 — migration preview with the current generator
    a2 = {}
    with tempfile.TemporaryDirectory(prefix="prodgen-a2-") as td:
        out = os.path.join(td, "tree")
        try:
            report = build(repo_root, main_sha, out, manifest_path, live_checkers=True)
            a2["build_ok"] = report.ok
            a2["tree_hash"] = report.tree_hash
            a2["same_tree"] = report.tree_hash == prov.get("tree_hash")
            if report.provenance_written:
                with open(os.path.join(out, PROVENANCE_FILE), encoding="utf-8") as fh:
                    cur = json.load(fh)
                cur_files = {p: (r["mode"], r["sha256"]) for p, r in cur["files"].items()}
                a2["added"] = sorted(set(cur_files) - set(files))
                a2["removed"] = sorted(set(files) - set(cur_files))
                a2["changed"] = sorted(p for p in set(files) & set(cur_files) if files[p] != cur_files[p])
            else:
                a2["class_b"] = [{"path": p, "line": l, "reason": r} for p, l, r in report.class_b]
        except ProdgenError as exc:
            a2["error"] = str(exc)
    result["checks"]["A2_migration_preview"] = a2
    result["ok"] = bool(result["checks"]["C_tree_hash"]["ok"] and result["checks"]["D_trailers"]["ok"]
                        and a1.get("ok") in (True, None))
    return result
