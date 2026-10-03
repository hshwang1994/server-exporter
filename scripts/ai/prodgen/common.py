"""Shared helpers: errors, hashing, class-B bookkeeping, path utilities."""
from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Iterable


class ProdgenError(Exception):
    """Fatal, fail-closed error (bad manifest, git failure, invariant violation)."""


@dataclass
class Preserved:
    line: int          # 1-based line number in the OUTPUT file
    rule: str          # class-A rule id (e.g. python.shebang)
    text_sha256: str   # sha256 of the preserved line text (never the text itself)


@dataclass
class ClassB:
    line: int          # 1-based line number in the SOURCE file (0 = whole file)
    reason: str        # why the stripper could not prove the removal safe
    text_sha256: str = ""


@dataclass
class StripResult:
    output: str
    removed_full_lines: int = 0
    removed_trailing: int = 0
    preserved: list = field(default_factory=list)   # list[Preserved]
    class_b: list = field(default_factory=list)     # list[ClassB]
    notes: list = field(default_factory=list)       # free-form, deterministic strings
    counters: dict = field(default_factory=dict)    # per-language deterministic counters

    @property
    def blocked(self) -> bool:
        return bool(self.class_b)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_lines_keep_final(text: str):
    """Split on LF only. Returns (lines_without_newline, had_final_newline)."""
    if text == "":
        return [], False
    had_final = text.endswith("\n")
    body = text[:-1] if had_final else text
    return body.split("\n"), had_final


def join_lines(lines, had_final: bool) -> str:
    out = "\n".join(lines)
    if had_final:
        out += "\n"
    return out


def check_lf_utf8(data: bytes, path: str) -> list:
    """Return a list of G04-style problems for the given bytes (empty = ok)."""
    problems = []
    if data.startswith(b"\xef\xbb\xbf"):
        problems.append(f"{path}: UTF-8 BOM present")
    if b"\r" in data:
        problems.append(f"{path}: CR byte present (expected LF-only)")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        problems.append(f"{path}: not valid UTF-8 ({exc})")
    return problems


_BRACE_RE = re.compile(r"\{([^{}]*)\}")


def expand_braces(pattern: str) -> list:
    """Expand {a,b} alternations (one level at a time, left to right)."""
    m = _BRACE_RE.search(pattern)
    if not m:
        return [pattern]
    out = []
    for alt in m.group(1).split(","):
        out.extend(expand_braces(pattern[:m.start()] + alt + pattern[m.end():]))
    return out


def _glob_to_regex(pattern: str) -> str:
    """Translate a path glob (with ** , *, ?) to a regex. '/'-separated, full match."""
    i, n = 0, len(pattern)
    out = []
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i:i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern[i:i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return "^" + "".join(out) + "$"


class PathMatcher:
    """Deterministic glob matcher over repo-relative POSIX paths."""

    def __init__(self, patterns: Iterable[str]):
        self._regexes = []
        for p in patterns:
            for e in expand_braces(p):
                self._regexes.append((e, re.compile(_glob_to_regex(e))))

    def matches(self, path: str) -> bool:
        return any(r.match(path) for _, r in self._regexes)

    def matching_patterns(self, path: str) -> list:
        return [e for e, r in self._regexes if r.match(path)]


def to_posix(path: str) -> str:
    return path.replace("\\", "/")


def is_windows() -> bool:
    return os.name == "nt"


def eprint(*args):
    print(*args, file=sys.stderr)
