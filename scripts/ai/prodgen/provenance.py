"""Deterministic provenance: tree hash, generator/rules hash, per-file records."""
from __future__ import annotations

import hashlib
import json
import os

from . import GENERATOR_VERSION, PROVENANCE_FILE, RULES_VERSION
from .common import sha256_bytes, to_posix


def generator_hash(prodgen_dir: str) -> str:
    """sha256 over the generator's own source files (sorted, LF-normalised)."""
    h = hashlib.sha256()
    for root, dirs, files in os.walk(prodgen_dir):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith((".pyc", ".pyo")):
                continue
            rel = to_posix(os.path.relpath(os.path.join(root, name), prodgen_dir))
            with open(os.path.join(root, name), "rb") as fh:
                data = fh.read().replace(b"\r\n", b"\n")
            h.update(rel.encode("utf-8") + b"\0" + sha256_bytes(data).encode("ascii") + b"\n")
    return h.hexdigest()


def tree_hash(files: dict) -> str:
    """files: path -> (mode, sha256hex). Excludes the provenance file."""
    h = hashlib.sha256()
    for path in sorted(files):
        if path == PROVENANCE_FILE:
            continue
        mode, digest = files[path]
        h.update(f"{mode} {digest} {path}\n".encode("utf-8"))
    return h.hexdigest()


def build_provenance(*, main_sha: str, main_tree: str, manifest_hash: str, gen_hash: str,
                     file_records: dict, excluded: dict, ignored: list, policy: dict) -> dict:
    files = {p: (r["mode"], r["sha256"]) for p, r in file_records.items()}
    return {
        "schema": 1,
        "generator_version": GENERATOR_VERSION,
        "rules_version": RULES_VERSION,
        "generator_hash": gen_hash,
        "manifest_sha256": manifest_hash,
        "main_sha": main_sha,
        "main_tree": main_tree,
        "tree_hash": tree_hash(files),
        "policy": {k: policy[k] for k in sorted(policy)},
        "files": {p: file_records[p] for p in sorted(file_records)},
        "excluded": {p: excluded[p] for p in sorted(excluded)},
        "ignored": sorted(ignored),
    }


def dumps(prov: dict) -> str:
    return json.dumps(prov, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def loads(text: str) -> dict:
    return json.loads(text)


def hash_tree_dir(root: str) -> tuple:
    """Walk a generated tree dir -> (tree_hash, {path: (mode, sha256)}) using recorded modes if present."""
    prov_path = os.path.join(root, PROVENANCE_FILE)
    modes = {}
    if os.path.isfile(prov_path):
        with open(prov_path, encoding="utf-8") as fh:
            prov = json.load(fh)
        modes = {p: r["mode"] for p, r in prov.get("files", {}).items()}
    files = {}
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for name in sorted(names):
            full = os.path.join(dirpath, name)
            rel = to_posix(os.path.relpath(full, root))
            if rel == PROVENANCE_FILE:
                continue
            with open(full, "rb") as fh:
                digest = sha256_bytes(fh.read())
            files[rel] = (modes.get(rel, "100644"), digest)
    return tree_hash(files), files
