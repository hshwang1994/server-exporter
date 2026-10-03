"""`prodgen drift-check --production <ref>`.

LEGACY : the ref carries no provenance (pre-prodgen production) -> informational listing.
C      : recompute the tree hash from the ref's blobs and compare with the provenance.
D      : commit trailers == provenance fields.
A1     : regenerate with the generator recorded in main history (scripts/ai/prodgen at main_sha).
A2     : migration preview — build from main_sha with the current generator and diff.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


def drift_check(repo_root: str, production_ref: str, manifest_path: str) -> dict:
    store = GitStore(repo_root)
    sha = store.rev_parse(production_ref)
    result = {"production": sha, "ref": production_ref, "checks": {}, "ok": False}
    prov_bytes = store.cat_path(sha, PROVENANCE_FILE)
    entries = store.ls_tree(sha)
    if prov_bytes is None:
        manifest = Manifest.load(manifest_path)
        paths = [e.path for e in entries]
        forbidden = sorted(p for p in paths if manifest.is_forbidden(p))
        cls = manifest.classify(paths)
        result["mode"] = "LEGACY"
        result["checks"]["legacy"] = {
            "files": len(paths), "forbidden_in_production": len(forbidden), "forbidden_sample": forbidden[:20],
            "would_be_included": len(cls.included), "not_allowlisted": len(paths) - len(cls.included),
            "note": "no provenance: production predates prodgen; checks C/D/A1 are not applicable",
        }
        result["ok"] = True
        return result

    prov = json.loads(prov_bytes.decode("utf-8"))
    result["mode"] = "PROVENANCE"
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
            archive = store.run(["archive", "--format=tar", main_sha, "--", "scripts/ai/prodgen", "production_manifest.yml"])
            import tarfile, io
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
