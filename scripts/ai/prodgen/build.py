"""`prodgen build`: fixed SHA -> runtime-only, comment-stripped tree + provenance."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field

from . import PROVENANCE_FILE
from .common import ProdgenError, check_lf_utf8, sha256_bytes, sha256_text, split_lines_keep_final
from .gitstore import GitStore
from .manifest import Manifest
from .provenance import build_provenance, dumps, generator_hash
from .strip import StripContext, strip_file

PRODGEN_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass
class BuildReport:
    main_sha: str
    main_tree: str
    out_dir: str
    file_count: int = 0
    total_bytes: int = 0
    source_bytes: int = 0
    removed: dict = field(default_factory=dict)          # language -> {full, trailing}
    counters: dict = field(default_factory=dict)         # language -> aggregated counters
    preserved: dict = field(default_factory=dict)        # rule -> count
    class_b: list = field(default_factory=list)          # (path, line, reason)
    notes: list = field(default_factory=list)
    classification: dict = field(default_factory=dict)
    provenance_written: bool = False
    tree_hash: str = ""
    tools: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.class_b and not self.classification.get("errors")

    def to_dict(self) -> dict:
        return {
            "main_sha": self.main_sha, "main_tree": self.main_tree, "out_dir": self.out_dir,
            "file_count": self.file_count, "total_bytes": self.total_bytes, "source_bytes": self.source_bytes,
            "removed": self.removed, "counters": self.counters, "preserved": self.preserved,
            "class_b": [{"path": p, "line": l, "reason": r} for p, l, r in self.class_b],
            "notes": self.notes, "classification": self.classification,
            "provenance_written": self.provenance_written, "tree_hash": self.tree_hash, "tools": self.tools,
            "ok": self.ok,
        }


FAILURE_FILE = ".prodgen-failure.json"


def _prepare_out_dir(out_dir: str) -> None:
    """Create an empty output directory; only directories produced by prodgen are replaced."""
    if os.path.exists(out_dir):
        entries = os.listdir(out_dir)
        if entries and PROVENANCE_FILE not in entries and FAILURE_FILE not in entries:
            raise ProdgenError(f"refusing to replace a non-empty directory that prodgen did not produce: {out_dir}")
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)


def classify_tree(manifest: Manifest, entries: list) -> dict:
    """Allowlist expansion against a git tree listing -> dict with classification and errors."""
    paths = [e.path for e in entries]
    cls = manifest.classify(paths)
    errors = []
    if cls.ambiguous:
        for p, pats in sorted(cls.ambiguous.items()):
            errors.append(f"G01 ambiguous classification: {p} matches {pats}")
    if cls.stale_entries:
        for pat in cls.stale_entries:
            errors.append(f"G01 include entry matches nothing at this SHA: {pat}")
    if cls.unclassified:
        for p in cls.unclassified:
            errors.append(f"G02 unclassified runtime file: {p}")
    if cls.forbidden_hits:
        for p, pats in sorted(cls.forbidden_hits.items()):
            errors.append(f"G03 included path is forbidden: {p} ({pats})")
    by_path = {e.path: e for e in entries}
    for p, entry in cls.included.items():
        te = by_path[p]
        if te.otype != "blob":
            errors.append(f"G01 {p}: not a blob ({te.otype})")
        elif te.mode != entry.mode:
            errors.append(f"G09 {p}: git mode {te.mode} != manifest mode {entry.mode}")
    return {"cls": cls, "errors": errors}


def build(repo_root: str, sha: str, out_dir: str, manifest_path: str, live_checkers: bool = True,
          write_provenance_on_failure: bool = False) -> BuildReport:
    store = GitStore(repo_root)
    main_sha = store.rev_parse(sha)
    main_tree = store.commit_tree_sha(main_sha)
    manifest = Manifest.load(manifest_path)
    entries = store.ls_tree(main_sha)
    classified = classify_tree(manifest, entries)
    cls = classified["cls"]
    report = BuildReport(main_sha=main_sha, main_tree=main_tree, out_dir=os.path.abspath(out_dir))
    report.classification = {
        "included": len(cls.included), "ignored": len(cls.ignored), "excluded": len(cls.excluded),
        "unclassified": cls.unclassified, "ambiguous": cls.ambiguous, "stale": cls.stale_entries,
        "forbidden": cls.forbidden_hits, "errors": classified["errors"],
    }
    if classified["errors"]:
        return report

    ctx = StripContext.build(manifest.policy, live_checkers=live_checkers)
    report.tools = ctx.tool_summary()
    _prepare_out_dir(out_dir)
    # in-progress marker: a build that dies half-way leaves a directory prodgen may replace next time
    marker = os.path.join(out_dir, FAILURE_FILE)
    with open(marker, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"status": "in_progress", "main_sha": main_sha}, sort_keys=True) + "\n")
    by_path = {e.path: e for e in entries}
    records = {}
    for path in sorted(cls.included):
        entry = cls.included[path]
        te = by_path[path]
        data = store.cat_blob(te.sha)
        report.source_bytes += len(data)
        if entry.language != "vault":
            problems = check_lf_utf8(data, path)
            if problems:
                for pr in problems:
                    report.class_b.append((path, 0, "G04 source " + pr))
                continue
            if entry.shebang is not None:
                first = data.split(b"\n", 1)[0].decode("utf-8", "replace")
                if first != entry.shebang:
                    report.class_b.append((path, 1, f"shebang mismatch: expected {entry.shebang!r}"))
                    continue
        try:
            res = strip_file(entry.language, data, path, entry, ctx)
        except ProdgenError as exc:
            raise ProdgenError(f"{path}: {exc}")
        for b in res.class_b:
            report.class_b.append((path, b.line, b.reason))
        out_data = data if entry.language == "vault" else res.output.encode("utf-8")
        if entry.language != "vault":
            # trailing-newline presence must be preserved (G04)
            if (data.endswith(b"\n")) != (out_data.endswith(b"\n")) and out_data:
                raise ProdgenError(f"{path}: trailing newline presence changed")
        dest = os.path.join(out_dir, *path.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(out_data)
        lang = entry.language
        rem = report.removed.setdefault(lang, {"full": 0, "trailing": 0})
        rem["full"] += res.removed_full_lines
        rem["trailing"] += res.removed_trailing
        agg = report.counters.setdefault(lang, {})
        for k, v in (res.counters or {}).items():
            agg[k] = agg.get(k, 0) + v
        for p in res.preserved:
            report.preserved[p.rule] = report.preserved.get(p.rule, 0) + 1
        for n in res.notes:
            report.notes.append(f"{path}: {n}")
        records[path] = {
            "sha256": sha256_bytes(out_data),
            "source_sha256": sha256_bytes(data),
            "source_blob": te.sha,
            "language": lang,
            "python_kind": entry.python_kind,
            "mode": entry.mode,
            "bytes": len(out_data),
            "removed_lines": res.removed_full_lines,
            "removed_trailing": res.removed_trailing,
            "preserved": [{"line": p.line, "rule": p.rule, "text_sha256": p.text_sha256}
                          for p in sorted(res.preserved, key=lambda p: (p.line, p.rule, p.text_sha256))],
        }
        report.file_count += 1
        report.total_bytes += len(out_data)

    gen_hash = generator_hash(PRODGEN_DIR)
    prov = build_provenance(
        main_sha=main_sha, main_tree=main_tree, manifest_hash=sha256_text(manifest.raw_text),
        gen_hash=gen_hash, file_records=records, excluded=cls.excluded, ignored=cls.ignored,
        policy=manifest.policy,
    )
    report.tree_hash = prov["tree_hash"]
    if report.class_b and not write_provenance_on_failure:
        failure = {
            "status": "class_b_remaining",
            "main_sha": main_sha,
            "class_b": [{"path": p, "line": l, "reason": r} for p, l, r in report.class_b],
        }
        with open(os.path.join(out_dir, FAILURE_FILE), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(failure, sort_keys=True, indent=1, ensure_ascii=False) + "\n")
        return report
    with open(os.path.join(out_dir, PROVENANCE_FILE), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dumps(prov))
    os.unlink(marker)
    report.provenance_written = True
    return report
