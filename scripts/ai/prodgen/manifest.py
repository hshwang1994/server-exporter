"""production_manifest.yml loading, allowlist expansion and classification."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

from .common import PathMatcher, ProdgenError

LANGUAGES = {"groovy", "ini", "python", "yaml", "vault", "shell", "gitmeta", "text"}
PYTHON_KINDS = {"plugin", "library", "script", "inventory"}


@dataclass
class IncludeEntry:
    pattern: str
    language: str
    mode: str
    optional: bool = False
    shebang: str = None
    python_kind: str = None
    doc_runtime: str = None       # e.g. "preserve_module_docstring"
    note: str = ""
    matcher: PathMatcher = field(default=None, repr=False)

    def matches(self, path: str) -> bool:
        return self.matcher.matches(path)


@dataclass
class Classification:
    included: dict            # path -> IncludeEntry
    ignored: list             # paths
    excluded: dict            # path -> reason
    unclassified: list        # paths under runtime roots with no rule
    ambiguous: dict           # path -> [patterns]
    stale_entries: list       # include patterns with no match (and not optional)
    forbidden_hits: dict      # included path -> [forbidden patterns]


class Manifest:
    def __init__(self, data: dict, source_path: str, raw_text: str = ""):
        self.source_path = source_path
        self.raw_text = raw_text
        self.data = data
        if not isinstance(data, dict):
            raise ProdgenError("manifest: top level must be a mapping")
        if data.get("version") != 1:
            raise ProdgenError("manifest: unsupported version (expected 1)")
        self.production_branch = data.get("production_branch", "production")
        self.main_branch = data.get("main_branch", "main")
        self.runtime_roots = list(data.get("runtime_roots") or [])
        self.policy = dict(data.get("policy") or {})
        self.toolchain = dict(data.get("toolchain") or {})
        self.include = [self._entry(raw) for raw in (data.get("include") or [])]
        self.excluded = []
        for raw in data.get("excluded") or []:
            pattern = raw.get("path") or raw.get("glob")
            if not pattern:
                raise ProdgenError("manifest: excluded entry needs path or glob")
            if not raw.get("reason"):
                raise ProdgenError(f"manifest: excluded entry {pattern} needs a reason")
            self.excluded.append((pattern, raw["reason"]))
        self.ignore = list(data.get("ignore") or [])
        self.forbidden = list(data.get("forbidden") or [])
        self._ignore_m = PathMatcher(self.ignore)
        self._forbidden_m = PathMatcher(self.forbidden)
        self._excluded_m = [(PathMatcher([p]), reason, p) for p, reason in self.excluded]

    @staticmethod
    def _entry(raw: dict) -> IncludeEntry:
        pattern = raw.get("path") or raw.get("glob")
        if not pattern:
            raise ProdgenError(f"manifest: include entry needs path or glob: {raw}")
        language = raw.get("language")
        if language not in LANGUAGES:
            raise ProdgenError(f"manifest: include {pattern}: language must be one of {sorted(LANGUAGES)}")
        mode = str(raw.get("mode") or "")
        if mode not in {"100644", "100755"}:
            raise ProdgenError(f"manifest: include {pattern}: mode must be 100644 or 100755")
        python_kind = raw.get("python_kind")
        if language == "python" and python_kind not in PYTHON_KINDS:
            raise ProdgenError(f"manifest: include {pattern}: python entries need python_kind in {sorted(PYTHON_KINDS)}")
        return IncludeEntry(
            pattern=pattern, language=language, mode=mode,
            optional=bool(raw.get("optional", False)),
            shebang=raw.get("shebang"), python_kind=python_kind,
            doc_runtime=raw.get("doc_runtime"), note=raw.get("note", ""),
            matcher=PathMatcher([pattern]),
        )

    @classmethod
    def load(cls, path: str) -> "Manifest":
        with open(path, "rb") as fh:
            raw = fh.read()
        if b"\r" in raw:
            raise ProdgenError("manifest: CRLF line endings are not allowed")
        text = raw.decode("utf-8")
        return cls(yaml.safe_load(text), path, text)

    @classmethod
    def load_from_text(cls, text: str, source_path: str = "<text>") -> "Manifest":
        return cls(yaml.safe_load(text), source_path, text)

    # ── classification ───────────────────────────────────────────────────────
    def under_runtime_root(self, path: str) -> bool:
        for root in self.runtime_roots:
            if path == root or path.startswith(root.rstrip("/") + "/"):
                return True
        return False

    def is_forbidden(self, path: str) -> list:
        return self._forbidden_m.matching_patterns(path)

    def classify(self, paths: list) -> Classification:
        included, ignored, excluded, unclassified, ambiguous, forbidden_hits = {}, [], {}, [], {}, {}
        hit_counts = {e.pattern: 0 for e in self.include}
        for path in sorted(paths):
            matches = [e for e in self.include if e.matches(path)]
            excl = [(reason, pat) for m, reason, pat in self._excluded_m if m.matches(path)]
            ign = self._ignore_m.matches(path)
            kinds = int(bool(matches)) + int(bool(excl)) + int(ign)
            if len(matches) > 1 or kinds > 1:
                ambiguous[path] = [e.pattern for e in matches] + [pat for _, pat in excl] + (["<ignore>"] if ign else [])
                continue
            if matches:
                entry = matches[0]
                hit_counts[entry.pattern] += 1
                included[path] = entry
                fb = self.is_forbidden(path)
                if fb:
                    forbidden_hits[path] = fb
            elif excl:
                excluded[path] = excl[0][0]
            elif ign:
                ignored.append(path)
            elif self.under_runtime_root(path):
                unclassified.append(path)
        stale = [e.pattern for e in self.include if hit_counts[e.pattern] == 0 and not e.optional]
        return Classification(included, ignored, excluded, unclassified, ambiguous, stale, forbidden_hits)


def default_manifest_path(repo_root: str) -> str:
    return os.path.join(repo_root, "production_manifest.yml")
