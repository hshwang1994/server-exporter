"""Offline gates: G01-G07, G09, G10, G16, G17."""
from __future__ import annotations

import difflib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

from .. import PROVENANCE_FILE
from ..build import FAILURE_FILE, classify_tree, build
from ..common import ProdgenError, check_lf_utf8, sha256_bytes, sha256_text, split_lines_keep_final, to_posix
from ..gitstore import GitStore
from ..manifest import Manifest
from ..provenance import hash_tree_dir
from ..strip import StripContext, residual_scan, strip_file
from ..strip.simplestrip import check_vault
from . import GateResult


def list_tree_files(tree_dir: str) -> dict:
    files = {}
    for dirpath, dirs, names in os.walk(tree_dir):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for name in sorted(names):
            full = os.path.join(dirpath, name)
            rel = to_posix(os.path.relpath(full, tree_dir))
            files[rel] = full
    return files


def load_context(repo_root: str, tree_dir: str, manifest_path: str) -> dict:
    ctx = {"repo_root": os.path.abspath(repo_root), "tree_dir": tree_dir, "manifest_path": manifest_path}
    if not os.path.isdir(tree_dir):
        ctx["fatal"] = f"tree directory does not exist: {tree_dir}"
        return ctx
    files = list_tree_files(tree_dir)
    if FAILURE_FILE in files:
        with open(files[FAILURE_FILE], encoding="utf-8") as fh:
            failure = json.load(fh)
        n = len(failure.get("class_b", []))
        ctx["fatal"] = f"tree carries {FAILURE_FILE}: {n} class-B item(s) remain — no provenance, promotion blocked"
        return ctx
    if PROVENANCE_FILE not in files:
        ctx["fatal"] = f"tree has no {PROVENANCE_FILE}"
        return ctx
    with open(files[PROVENANCE_FILE], encoding="utf-8") as fh:
        prov = json.load(fh)
    ctx["prov"] = prov
    ctx["files"] = {k: v for k, v in files.items() if k != PROVENANCE_FILE}
    try:
        ctx["manifest"] = Manifest.load(manifest_path)
        ctx["store"] = GitStore(repo_root)
    except ProdgenError as exc:
        ctx["fatal"] = str(exc)
        return ctx
    ctx["strip_ctx"] = StripContext.build(ctx["manifest"].policy, live_checkers=True)
    return ctx


def _entry_for(ctx, path):
    for e in ctx["manifest"].include:
        if e.matches(path):
            return e
    return None


# ── G01-G03 ──────────────────────────────────────────────────────────────────
def g01_g03_allowlist(ctx) -> list:
    manifest, store, prov = ctx["manifest"], ctx["store"], ctx["prov"]
    entries = store.ls_tree(prov["main_sha"])
    classified = classify_tree(manifest, entries)
    cls = classified["cls"]
    tree_set = set(ctx["files"])
    allow_set = set(cls.included)
    g01, g02, g03 = [], [], []
    for err in classified["errors"]:
        (g02 if err.startswith("G02") else g03 if err.startswith("G03") else g01).append(err)
    missing = sorted(allow_set - tree_set)
    extra = sorted(tree_set - allow_set)
    if missing:
        g01.append(f"allowlisted but absent from tree: {missing[:10]}{' ...' if len(missing) > 10 else ''}")
    if extra:
        g01.append(f"present in tree but not allowlisted: {extra[:10]}{' ...' if len(extra) > 10 else ''}")
    prov_set = set(prov.get("files", {}))
    if prov_set != tree_set:
        g01.append(f"provenance file set != tree file set (diff {len(prov_set ^ tree_set)})")
    if sha256_text(manifest.raw_text) != prov.get("manifest_sha256"):
        g01.append("manifest changed since the tree was generated (manifest_sha256 mismatch)")
    for p in sorted(tree_set):
        hits = manifest.is_forbidden(p)
        if hits:
            g03.append(f"forbidden path in tree: {p} ({hits})")
    data = {"tree_files": len(tree_set), "allowlisted": len(allow_set), "ignored": len(cls.ignored),
            "excluded": len(cls.excluded)}
    return [GateResult("G01", "FAIL" if g01 else "PASS", g01, data),
            GateResult("G02", "FAIL" if g02 else "PASS", g02),
            GateResult("G03", "FAIL" if g03 else "PASS", g03)]


# ── G04 ──────────────────────────────────────────────────────────────────────
def g04_encoding(ctx) -> GateResult:
    problems = []
    store, prov = ctx["store"], ctx["prov"]
    for rel, full in sorted(ctx["files"].items()):
        rec = prov["files"].get(rel)
        with open(full, "rb") as fh:
            data = fh.read()
        if rec and rec.get("language") == "vault":
            continue
        problems += check_lf_utf8(data, rel)
        if rec:
            src = store.cat_blob(rec["source_blob"])
            if bool(src.endswith(b"\n")) != bool(data.endswith(b"\n")):
                problems.append(f"{rel}: trailing newline presence differs from source")
    return GateResult("G04", "FAIL" if problems else "PASS", problems, {"files": len(ctx["files"])})


# ── G05 / G06 ────────────────────────────────────────────────────────────────
def g05_reverify(ctx) -> GateResult:
    problems, checked = [], 0
    store, prov, sctx = ctx["store"], ctx["prov"], ctx["strip_ctx"]
    for rel, full in sorted(ctx["files"].items()):
        rec = prov["files"].get(rel)
        if not rec:
            problems.append(f"{rel}: not in provenance")
            continue
        entry = _entry_for(ctx, rel)
        if entry is None:
            problems.append(f"{rel}: no manifest entry")
            continue
        src = store.cat_blob(rec["source_blob"])
        if sha256_bytes(src) != rec["source_sha256"]:
            problems.append(f"{rel}: source blob hash mismatch")
            continue
        try:
            res = strip_file(entry.language, src, rel, entry, sctx)
        except ProdgenError as exc:
            problems.append(f"{rel}: re-strip failed: {exc}")
            continue
        if res.class_b:
            problems.append(f"{rel}: re-strip produced class B ({res.class_b[0].reason})")
            continue
        out = src if entry.language == "vault" else res.output.encode("utf-8")
        with open(full, "rb") as fh:
            data = fh.read()
        if out != data:
            problems.append(f"{rel}: re-strip output differs from tree file")
            continue
        if sha256_bytes(data) != rec["sha256"]:
            problems.append(f"{rel}: tree file hash != provenance sha256")
        checked += 1
    return GateResult("G05", "FAIL" if problems else "PASS", problems, {"files_reverified": checked})


def g06_diff_shape(ctx) -> GateResult:
    """Independent check: source -> output line diff has no inserts; replaces never grow."""
    problems, checked = [], 0
    store, prov = ctx["store"], ctx["prov"]
    for rel, full in sorted(ctx["files"].items()):
        rec = prov["files"].get(rel)
        if not rec or rec.get("language") == "vault":
            continue
        src = store.cat_blob(rec["source_blob"]).decode("utf-8")
        with open(full, "rb") as fh:
            out = fh.read().decode("utf-8")
        a, _ = split_lines_keep_final(src)
        b, _ = split_lines_keep_final(out)
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "insert":
                problems.append(f"{rel}: inserted lines at output {j1 + 1}-{j2}")
            elif tag == "replace":
                if (j2 - j1) > (i2 - i1):
                    problems.append(f"{rel}: replace grew at source {i1 + 1}-{i2}")
                for new in b[j1:j2]:
                    if new.strip() == "pass":
                        continue
                    if not any(_derivable(old, new) for old in a[i1:i2]):
                        problems.append(f"{rel}: output line not derivable from a source line near {i1 + 1}")
                        break
        checked += 1
    return GateResult("G06", "FAIL" if problems else "PASS", problems, {"files_checked": checked})


def _derivable(old: str, new: str) -> bool:
    """new is old with one or more contiguous spans removed (subsequence with a prefix kept)."""
    if not new.strip():
        return True
    if old.startswith(new.rstrip()):
        return True
    it = iter(old)
    return all(ch in it for ch in new)


# ── G07 ──────────────────────────────────────────────────────────────────────
def g07_residual(ctx) -> GateResult:
    problems, scanned, preserved_total = [], 0, 0
    prov, sctx = ctx["prov"], ctx["strip_ctx"]
    for rel, full in sorted(ctx["files"].items()):
        rec = prov["files"].get(rel)
        entry = _entry_for(ctx, rel)
        if not rec or entry is None:
            continue
        with open(full, "rb") as fh:
            data = fh.read()
        try:
            found = residual_scan(entry.language, data, rel, entry, sctx)
        except ProdgenError as exc:
            problems.append(f"{rel}: residual scan error: {exc}")
            continue
        preserved = {(p["line"], p["rule"]): p["text_sha256"] for p in rec.get("preserved", [])}
        lines, _ = split_lines_keep_final(data.decode("utf-8")) if entry.language != "vault" else ([], False)
        seen = set()
        for line, rule in found:
            if rule is None:
                problems.append(f"{rel}:{line}: comment-like text without an A-rule")
                continue
            key = (line, rule)
            if key not in preserved:
                problems.append(f"{rel}:{line}: {rule} not recorded in provenance preserved[] (output line)")
                continue
            seen.add(key)
            if line - 1 >= len(lines) or sha256_text(lines[line - 1]) != preserved[key]:
                problems.append(f"{rel}:{line}: preserved text hash mismatch for {rule}")
        for key in sorted(set(preserved) - seen):
            if key[1] != "python.module_docstring_runtime_referenced":
                problems.append(f"{rel}:{key[0]}: provenance preserves {key[1]} but the residual scan found nothing there")
        preserved_total += len(preserved)
        scanned += 1
    return GateResult("G07", "FAIL" if problems else "PASS", problems,
                      {"files_scanned": scanned, "preserved_entries": preserved_total})


# ── G09 ──────────────────────────────────────────────────────────────────────
def g09_modes(ctx) -> GateResult:
    problems = []
    prov, store = ctx["prov"], ctx["store"]
    src_modes = {e.path: e.mode for e in store.ls_tree(prov["main_sha"])}
    exec_count = 0
    for rel in sorted(ctx["files"]):
        rec = prov["files"].get(rel)
        entry = _entry_for(ctx, rel)
        if not rec or entry is None:
            continue
        if rec["mode"] != entry.mode:
            problems.append(f"{rel}: provenance mode {rec['mode']} != manifest {entry.mode}")
        if src_modes.get(rel) != entry.mode:
            problems.append(f"{rel}: source git mode {src_modes.get(rel)} != manifest {entry.mode}")
        if rec["mode"] == "100755":
            exec_count += 1
            with open(ctx["files"][rel], "rb") as fh:
                first = fh.readline()
            if not first.startswith(b"#!"):
                problems.append(f"{rel}: executable without shebang")
        if os.name != "nt":
            is_exec = os.access(ctx["files"][rel], os.X_OK)
            if is_exec != (rec["mode"] == "100755"):
                problems.append(f"{rel}: filesystem exec bit {is_exec} != mode {rec['mode']}")
    data = {"executables": exec_count, "fs_exec_bits_checked": os.name != "nt"}
    return GateResult("G09", "FAIL" if problems else "PASS", problems, data)


# ── G10 ──────────────────────────────────────────────────────────────────────
def _load_secret_scanner(repo_root: str):
    """The digest scanner lives next to prodgen; fall back to prodgen's own repository."""
    prodgen_repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))  # verify/prodgen/ai/scripts -> repo
    path = None
    for root in (repo_root, prodgen_repo):
        cand = os.path.join(root, "scripts", "ai", "verify_no_plaintext_secret.py")
        if os.path.isfile(cand) and os.path.isfile(os.path.join(root, "tests", "secret_guard.py")):
            path = cand
            break
    if path is None:
        return None
    spec = importlib.util.spec_from_file_location("prodgen_secret_scanner", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        return None
    return mod


def g10_vault_and_secrets(ctx) -> GateResult:
    problems, info = [], {}
    prov = ctx["prov"]
    vault_count = 0
    for rel, full in sorted(ctx["files"].items()):
        rec = prov["files"].get(rel)
        if rec and rec.get("language") == "vault":
            vault_count += 1
            with open(full, "rb") as fh:
                problems += check_vault(fh.read(), rel)
    info["vault_files"] = vault_count
    scanner = _load_secret_scanner(ctx["repo_root"])
    if scanner is None:
        problems.append("secret scanner scripts/ai/verify_no_plaintext_secret.py (tests/secret_guard.py) unavailable")
        return GateResult("G10", "FAIL", problems, info)
    hits = {}
    scanned = 0
    for rel, full in sorted(ctx["files"].items()):
        rec = prov["files"].get(rel)
        if rec and rec.get("language") == "vault":
            continue
        with open(full, "rb") as fh:
            text = fh.read().decode("utf-8", "replace")
        scanned += 1
        for run in scanner._RUN.findall(text):
            size = len(run)
            starts = scanner._candidate_starts(run)
            for length in scanner._LENGTHS:
                if length > size:
                    continue
                for i in starts:
                    if i + length > size:
                        continue
                    d = scanner._digest8(run[i:i + length])
                    if d in scanner.KNOWN_SECRET_DIGESTS:
                        hits.setdefault(d, set()).add(rel)
                d = scanner._digest8(run[size - length:])
                if d in scanner.KNOWN_SECRET_DIGESTS:
                    hits.setdefault(d, set()).add(rel)
    for d, rels in sorted(hits.items()):
        problems.append(f"known secret digest {d} found in {sorted(rels)[:5]}")
    info["files_scanned"] = scanned
    info["digests_known"] = len(scanner.KNOWN_SECRET_DIGESTS)
    return GateResult("G10", "FAIL" if problems else "PASS", problems, info)


# ── G16 ──────────────────────────────────────────────────────────────────────
def g16_inventory(ctx) -> GateResult:
    problems, compared = [], 0
    store, prov = ctx["store"], ctx["prov"]
    py = sys.executable
    for rel in sorted(ctx["files"]):
        if not rel.endswith("/inventory.sh"):
            continue
        rec = prov["files"][rel]
        src = store.cat_blob(rec["source_blob"])
        with tempfile.TemporaryDirectory(prefix="prodgen-inv-") as td:
            orig = os.path.join(td, "orig_inventory.py")
            with open(orig, "wb") as fh:
                fh.write(src)
            for key in ("service_ip", "bmc_ip", "ip"):
                env = dict(os.environ, INVENTORY_JSON=json.dumps([{key: "192.0.2.1", "extra": "{{ x }}"}, {key: "192.0.2.2"}]),
                           PYTHONIOENCODING="utf-8")
                for argv in (["--list"], ["--host", "192.0.2.1"], ["--host", "bad"], []):
                    outs = []
                    for script in (orig, ctx["files"][rel]):
                        p = subprocess.run([py, script, *argv], capture_output=True, env=env, cwd=td)
                        outs.append((p.returncode, p.stdout, p.stderr))
                    compared += 1
                    if outs[0] != outs[1]:
                        problems.append(f"{rel}: output differs for {argv} key={key}")
            env = dict(os.environ, INVENTORY_JSON="", PYTHONIOENCODING="utf-8")
            outs = []
            for script in (orig, ctx["files"][rel]):
                p = subprocess.run([py, script, "--list"], capture_output=True, env=env, cwd=td)
                outs.append((p.returncode, p.stdout, p.stderr))
            compared += 1
            if outs[0] != outs[1]:
                problems.append(f"{rel}: output differs for empty INVENTORY_JSON")
    return GateResult("G16", "FAIL" if problems else "PASS", problems, {"invocations_compared": compared})


# ── G17 ──────────────────────────────────────────────────────────────────────
def g17_determinism(ctx) -> GateResult:
    prov = ctx["prov"]
    with tempfile.TemporaryDirectory(prefix="prodgen-det-") as td:
        out2 = os.path.join(td, "tree")
        report = build(ctx["repo_root"], prov["main_sha"], out2, ctx["manifest_path"], live_checkers=True)
        problems = []
        if not report.provenance_written:
            problems.append("second build did not produce provenance (class B?)")
            return GateResult("G17", "FAIL", problems)
        h1, _ = hash_tree_dir(ctx["tree_dir"])
        h2, _ = hash_tree_dir(out2)
        if h1 != h2:
            problems.append(f"tree hash differs: {h1} != {h2}")
        with open(os.path.join(ctx["tree_dir"], PROVENANCE_FILE), "rb") as fh:
            p1 = fh.read()
        with open(os.path.join(out2, PROVENANCE_FILE), "rb") as fh:
            p2 = fh.read()
        if p1 != p2:
            problems.append("provenance JSON differs between builds")
        if prov["tree_hash"] != h1:
            problems.append(f"recorded tree_hash {prov['tree_hash']} != recomputed {h1}")
    return GateResult("G17", "FAIL" if problems else "PASS", problems, {"tree_hash": h1})
