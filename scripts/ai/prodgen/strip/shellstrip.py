"""POSIX/bash shell comment detection with two independent lexers.

Lexer A (this module): quote / heredoc / $( ) / ${ } / backtick tracker.
Lexer B: shlex (posix, commenters='#') token-stream equality original vs stripped.
A comment is removed only when both agree; anything uncertain is reported as class B.
`bash -n` / `sh -n` parity (WSL or native) is a structural extra, run in batch.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from ..common import ClassB, Preserved, ProdgenError, StripResult, is_windows, sha256_text, split_lines_keep_final
from ..editlog import Edit, EditEngine

RULE_SHEBANG = "shell.shebang"
_WORD_START_PREV = set(" \t;|&(")


@dataclass
class ShellComment:
    line: int        # 0-based
    col: int         # column of '#'
    full_line: bool
    text: str


def _heredoc_delims(segment: str):
    """Return heredoc delimiters introduced in a line segment (outside quotes)."""
    out = []
    i = 0
    n = len(segment)
    while i < n:
        if segment.startswith("<<", i) and not segment.startswith("<<<", i):
            j = i + 2
            strip_tabs = False
            if j < n and segment[j] == "-":
                strip_tabs = True
                j += 1
            while j < n and segment[j] in " \t":
                j += 1
            word = ""
            if j < n and segment[j] in "'\"":
                q = segment[j]
                k = segment.find(q, j + 1)
                if k == -1:
                    return None
                word = segment[j + 1:k]
                j = k + 1
            else:
                k = j
                while k < n and segment[k] not in " \t;|&<>)":
                    if segment[k] == "\\" and k + 1 < n:
                        word += segment[k + 1]
                        k += 2
                        continue
                    word += segment[k]
                    k += 1
                j = k
            if not word:
                return None
            out.append((word, strip_tabs))
            i = j
            continue
        i += 1
    return out


def detect(text: str) -> tuple:
    """Return (comments, uncertain) where uncertain = [(line, reason)]."""
    lines, _ = split_lines_keep_final(text)
    comments = []
    uncertain = []
    stack = []            # frames: 'sq' 'dq' 'bt' 'cmd' 'param' 'arith' 'ansi'
    depth = []            # paren/brace depth per frame
    pending_heredocs = []
    heredoc_active = None  # (delim, strip_tabs)
    continuation = False   # previous line ended with an unescaped backslash at top level

    for ln, line in enumerate(lines):
        if heredoc_active is not None:
            delim, strip_tabs = heredoc_active
            probe = line.lstrip("\t") if strip_tabs else line
            if probe == delim:
                heredoc_active = None
                if pending_heredocs:
                    heredoc_active = pending_heredocs.pop(0)
            continue
        i = 0
        n = len(line)
        line_continues = False
        heredoc_scanned = False
        while i < n:
            c = line[i]
            frame = stack[-1] if stack else None
            if frame == "sq":
                if c == "'":
                    stack.pop(); depth.pop()
                i += 1
                continue
            if frame == "ansi":
                if c == "\\":
                    i += 2
                    continue
                if c == "'":
                    stack.pop(); depth.pop()
                i += 1
                continue
            if frame == "dq":
                if c == "\\":
                    i += 2
                    continue
                if c == '"':
                    stack.pop(); depth.pop()
                    i += 1
                    continue
                if c == "`":
                    stack.append("bt"); depth.append(0)
                    i += 1
                    continue
                if c == "$" and i + 1 < n and line[i + 1] == "(":
                    if line.startswith("$((", i):
                        stack.append("arith"); depth.append(2); i += 3
                    else:
                        stack.append("cmd"); depth.append(1); i += 2
                    continue
                if c == "$" and i + 1 < n and line[i + 1] == "{":
                    stack.append("param"); depth.append(1); i += 2
                    continue
                i += 1
                continue
            if frame == "bt":
                if c == "\\":
                    i += 2
                    continue
                if c == "`":
                    stack.pop(); depth.pop()
                    i += 1
                    continue
                # fall through to normal-like handling for quotes inside backticks
            # normal / cmd / param / arith / bt-inner
            if c == "\\":
                if i + 1 >= n:
                    line_continues = True
                i += 2
                continue
            if c == "'":
                stack.append("sq"); depth.append(0); i += 1
                continue
            if c == '"':
                stack.append("dq"); depth.append(0); i += 1
                continue
            if c == "$" and i + 1 < n and line[i + 1] == "'":
                stack.append("ansi"); depth.append(0); i += 2
                continue
            if c == "$" and i + 1 < n and line[i + 1] == '"':
                stack.append("dq"); depth.append(0); i += 2
                continue
            if c == "`" and frame != "bt":
                stack.append("bt"); depth.append(0); i += 1
                continue
            if c == "$" and line.startswith("$((", i):
                stack.append("arith"); depth.append(2); i += 3
                continue
            if c == "$" and i + 1 < n and line[i + 1] == "(":
                stack.append("cmd"); depth.append(1); i += 2
                continue
            if c == "$" and i + 1 < n and line[i + 1] == "{":
                stack.append("param"); depth.append(1); i += 2
                continue
            if frame in ("cmd", "arith"):
                if c == "(":
                    depth[-1] += 1
                elif c == ")":
                    depth[-1] -= 1
                    if depth[-1] == 0:
                        stack.pop(); depth.pop()
                elif c == "#" and (i == 0 or line[i - 1] in _WORD_START_PREV):
                    uncertain.append((ln, "shell: '#' inside command substitution"))
                    i = n
                    continue
                i += 1
                continue
            if frame == "param":
                if c == "{":
                    depth[-1] += 1
                elif c == "}":
                    depth[-1] -= 1
                    if depth[-1] == 0:
                        stack.pop(); depth.pop()
                i += 1
                continue
            if frame == "bt":
                i += 1
                continue
            # top level
            if c == "#" and (i == 0 or line[i - 1] in _WORD_START_PREV):
                full = line[:i].strip() == ""
                if full and continuation:
                    uncertain.append((ln, "shell: comment line follows a backslash continuation"))
                else:
                    comments.append(ShellComment(ln, i, full, line[i:]))
                i = n
                continue
            if c == "<" and line.startswith("<<", i) and not line.startswith("<<<", i) and not heredoc_scanned:
                delims = _heredoc_delims(line[i:])
                if delims is None:
                    uncertain.append((ln, "shell: unparsable heredoc introducer"))
                    i = n
                    continue
                pending_heredocs.extend(delims)
                heredoc_scanned = True
                i += 2
                continue
            i += 1
        if stack and stack[-1] in ("sq", "dq", "ansi", "bt") :
            # multi-line quoted string continues onto the next line
            continuation = False
        else:
            continuation = line_continues
        if not stack and pending_heredocs:
            heredoc_active = pending_heredocs.pop(0)
    if stack:
        uncertain.append((len(lines) - 1 if lines else 0, f"shell: unterminated {stack[-1]} construct"))
    if heredoc_active is not None:
        uncertain.append((len(lines) - 1 if lines else 0, "shell: unterminated heredoc"))
    return comments, uncertain


def shlex_tokens(text: str):
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = "#"
        return list(lex)
    except ValueError:
        return None


def plan_edits(text: str, line_offset: int = 0, keep_shebang: bool = True):
    """Compute edits (relative to `text` lines, shifted by line_offset) and preserved lines.

    Returns (edits, preserved[(line0, rule)], class_b[(line0, reason)], comments_used).
    """
    comments, uncertain = detect(text)
    lines, _ = split_lines_keep_final(text)
    edits, preserved, class_b, used = [], [], [], []
    for ln, reason in uncertain:
        class_b.append((ln, reason))
    for c in comments:
        if keep_shebang and c.line == 0 and c.col == 0 and c.text.startswith("#!"):
            preserved.append((0, RULE_SHEBANG))
            continue
        used.append(c)
        if c.full_line:
            edits.append(Edit("delete_line", c.line + line_offset, rule="shell.comment"))
        else:
            edits.append(Edit("truncate", c.line + line_offset, col=c.col, rule="shell.comment.trailing"))
    return edits, preserved, class_b, used


def strip_text(text: str, path: str = "<shell>") -> tuple:
    """Strip a standalone shell text. Returns (output, StripResult-like dict) without syntax parity."""
    edits, preserved, class_b, used = plan_edits(text)
    result = StripResult(output=text)
    lines, _ = split_lines_keep_final(text)
    for ln, reason in class_b:
        result.class_b.append(ClassB(ln + 1, reason, sha256_text(lines[ln]) if ln < len(lines) else ""))
    if result.class_b:
        return result
    output = EditEngine(text).apply(edits)
    a, b = shlex_tokens(text), shlex_tokens(output)
    if a is None or b is None:
        result.class_b.append(ClassB(0, "shell: shlex could not tokenize (lexer B unavailable for this text)"))
        result.output = text
        return result
    if a != b:
        raise ProdgenError(f"{path}: shlex token stream changed by comment removal (lexer disagreement)")
    # lexer A on the output must find nothing left
    left, unc = detect(output)
    left = [c for c in left if not (c.line == 0 and c.col == 0 and c.text.startswith("#!"))]
    if left or unc:
        raise ProdgenError(f"{path}: residual shell comments after stripping")
    result.output = output
    result.removed_full_lines = sum(1 for c in used if c.full_line)
    result.removed_trailing = sum(1 for c in used if not c.full_line)
    for ln, rule in preserved:
        result.preserved.append(Preserved(ln + 1, rule, sha256_text(lines[ln])))
    return result


def residual(text: str) -> list:
    comments, uncertain = detect(text)
    out = []
    for c in comments:
        if c.line == 0 and c.col == 0 and c.text.startswith("#!"):
            out.append((1, RULE_SHEBANG))
        else:
            out.append((c.line + 1, None))
    for ln, _reason in uncertain:
        out.append((ln + 1, None))
    return sorted(out)


# ── structural parity: bash -n / sh -n ────────────────────────────────────────
class ShellSyntaxChecker:
    """Runs `bash -n` and `sh -n` on texts, natively (Linux) or through WSL (Windows)."""

    def __init__(self):
        self.mode = None
        if not is_windows() and shutil.which("bash") and shutil.which("sh"):
            self.mode = "native"
        elif is_windows() and shutil.which("wsl.exe"):
            self.mode = "wsl"

    @property
    def available(self) -> bool:
        return self.mode is not None

    @staticmethod
    def _wsl_path(win_path: str) -> str:
        drive, rest = os.path.splitdrive(os.path.abspath(win_path))
        return "/mnt/" + drive[0].lower() + rest.replace("\\", "/")

    def check(self, texts: list) -> list:
        """Return [(rc_bash, rc_sh), ...] for each text, or None if unavailable."""
        if not self.available or not texts:
            return None if not self.available else []
        tmpdir = tempfile.mkdtemp(prefix="prodgen-sh-")
        try:
            for idx, text in enumerate(texts):
                with open(os.path.join(tmpdir, f"{idx}.sh"), "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
            script = (
                'cd "$1" && for i in $(seq 0 $(( $2 - 1 ))); do '
                'bash -n "$i.sh" >/dev/null 2>&1; rb=$?; sh -n "$i.sh" >/dev/null 2>&1; rs=$?; '
                'echo "$i $rb $rs"; done'
            )
            if self.mode == "native":
                cmd = ["bash", "-c", script, "prodgen", tmpdir, str(len(texts))]
            else:
                cmd = ["wsl.exe", "-e", "bash", "-c", script, "prodgen", self._wsl_path(tmpdir), str(len(texts))]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                raise ProdgenError(f"shell syntax checker failed: {proc.stderr.strip()[:300]}")
            out = [None] * len(texts)
            for row in proc.stdout.split("\n"):
                parts = row.split()
                if len(parts) == 3:
                    out[int(parts[0])] = (int(parts[1]), int(parts[2]))
            if any(o is None for o in out):
                raise ProdgenError("shell syntax checker returned an incomplete result")
            return out
        finally:
            for name in os.listdir(tmpdir):
                os.unlink(os.path.join(tmpdir, name))
            os.rmdir(tmpdir)
