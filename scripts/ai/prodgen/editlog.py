"""Common edit engine.

Every stripper emits an edit log; the engine applies it bottom-up and verifies the
diff-shape invariant: the output differs from the source only by the logged
deletions / truncations / span removals / replacements (difflib opcodes contain no
'insert', and every changed line is derivable from the log).
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from .common import ProdgenError, join_lines, split_lines_keep_final


@dataclass
class Edit:
    kind: str                 # delete_line | truncate | remove_span | replace_span
    line: int                 # 0-based start line
    end_line: int = -1        # 0-based inclusive end line (delete_line / remove_span / replace_span)
    col: int = 0              # truncate: cut col; remove_span/replace_span: start col on `line`
    end_col: int = 0          # remove_span/replace_span: end col (exclusive) on `end_line`
    text: str = ""            # replace_span replacement text (single line, no newline)
    rule: str = ""            # reason / rule id

    def __post_init__(self):
        if self.end_line < 0:
            self.end_line = self.line
        if self.end_line < self.line:
            raise ProdgenError(f"edit {self} has end_line < line")
        if "\n" in self.text:
            raise ProdgenError("replacement text must be a single line")


class EditEngine:
    def __init__(self, source: str):
        self.source = source
        self.lines, self.had_final = split_lines_keep_final(source)

    def apply(self, edits: list) -> str:
        expected = self._expected_lines(edits)
        out_lines = [l for l in expected if l is not None]
        output = join_lines(out_lines, self.had_final if out_lines else False)
        self._verify_shape(edits, expected, out_lines)
        return output

    def line_map(self, edits: list) -> dict:
        """0-based source line -> 0-based output line for every line that survives the edits."""
        mapping, out = {}, 0
        for i, line in enumerate(self._expected_lines(edits)):
            if line is not None:
                mapping[i] = out
                out += 1
        return mapping

    # ── derive the expected per-line result from the log ─────────────────────
    def _expected_lines(self, edits: list):
        n = len(self.lines)
        result = list(self.lines)      # str = kept/modified, None = deleted
        span_touched = [False] * n
        for e in sorted(edits, key=lambda e: (e.line, e.col), reverse=True):
            if e.line >= n or e.end_line >= n:
                raise ProdgenError(f"edit out of range: {e}")
            if e.kind == "delete_line":
                for i in range(e.line, e.end_line + 1):
                    if result[i] is None:
                        raise ProdgenError(f"overlapping deletions on line {i + 1}: {e}")
                    result[i] = None
            elif e.kind == "truncate":
                cur = result[e.line]
                if cur is None:
                    raise ProdgenError(f"truncate on deleted line {e.line + 1}: {e}")
                if e.col > len(cur):
                    raise ProdgenError(f"truncate col beyond line {e.line + 1}: {e}")
                result[e.line] = cur[:e.col].rstrip(" \t")
            elif e.kind in ("remove_span", "replace_span"):
                first = result[e.line]
                last = result[e.end_line]
                if first is None or last is None:
                    raise ProdgenError(f"span edit on deleted line: {e}")
                if e.line == e.end_line:
                    if e.col > e.end_col or e.end_col > len(first):
                        raise ProdgenError(f"span out of range on line {e.line + 1}: {e}")
                    new = first[:e.col] + e.text + first[e.end_col:]
                else:
                    if e.col > len(first) or e.end_col > len(last):
                        raise ProdgenError(f"span out of range: {e}")
                    new = first[:e.col] + e.text + last[e.end_col:]
                    for i in range(e.line + 1, e.end_line + 1):
                        result[i] = None
                result[e.line] = new
                span_touched[e.line] = True
            else:
                raise ProdgenError(f"unknown edit kind: {e.kind}")
        return result

    def _verify_shape(self, edits: list, expected: list, out_lines: list) -> None:
        touched = set()
        for e in edits:
            touched.update(range(e.line, e.end_line + 1))
        sm = difflib.SequenceMatcher(None, self.lines, out_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            if tag == "insert":
                raise ProdgenError(f"diff-shape violation: inserted lines at output {j1 + 1}-{j2}")
            for i in range(i1, i2):
                if i not in touched:
                    raise ProdgenError(f"diff-shape violation: source line {i + 1} changed without a logged edit")
            if tag == "replace":
                if (j2 - j1) > (i2 - i1):
                    raise ProdgenError(f"diff-shape violation: replace grew lines at source {i1 + 1}-{i2}")
                exp_block = [l for l in expected[i1:i2] if l is not None]
                if exp_block != out_lines[j1:j2]:
                    raise ProdgenError(f"diff-shape violation: replaced block mismatch at source {i1 + 1}-{i2}")
        if out_lines != [l for l in expected if l is not None]:
            raise ProdgenError("diff-shape violation: output does not equal expected lines")


def count_removed(edits: list) -> tuple:
    """(full lines deleted, trailing truncations, span edits)."""
    full = sum(e.end_line - e.line + 1 for e in edits if e.kind == "delete_line")
    trailing = sum(1 for e in edits if e.kind == "truncate")
    spans = sum(1 for e in edits if e.kind in ("remove_span", "replace_span"))
    return full, trailing, spans
