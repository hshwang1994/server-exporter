"""PowerShell comment detection (own lexer) verified by the real PowerShell parser.

The external check runs ps_tokens.ps1 with pwsh / powershell.exe:
token stream (Kind, Text) excluding Comment, with NewLine runs collapsed, must be
equal for the original and the stripped text, and the parse error count must not
change. Without a PowerShell parser every PowerShell comment stays class B.
`<# ... #>` block comments are not supported by this minimal lexer -> class B.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from dataclasses import dataclass

from ..common import ProdgenError, split_lines_keep_final
from ..editlog import Edit

RULE_REQUIRES = "powershell.requires"
_WORD_START_PREV = set(" \t;{}()|,")


@dataclass
class PsComment:
    line: int
    col: int
    full_line: bool
    text: str


def detect(text: str) -> tuple:
    """Return (comments, uncertain[(line, reason)])."""
    lines, _ = split_lines_keep_final(text)
    comments, uncertain = [], []
    stack = []      # 'sq' 'dq' 'sub' 'brace' 'here_sq' 'here_dq'
    depth = []
    for ln, line in enumerate(lines):
        frame = stack[-1] if stack else None
        if frame == "here_sq":
            if line.startswith("'@"):
                stack.pop(); depth.pop()
            continue
        if frame == "here_dq":
            if line.startswith('"@'):
                stack.pop(); depth.pop()
            continue
        i, n = 0, len(line)
        while i < n:
            c = line[i]
            frame = stack[-1] if stack else None
            if frame == "sq":
                if c == "'":
                    if i + 1 < n and line[i + 1] == "'":
                        i += 2
                        continue
                    stack.pop(); depth.pop()
                i += 1
                continue
            if frame == "dq":
                if c == "`":
                    i += 2
                    continue
                if c == '"':
                    if i + 1 < n and line[i + 1] == '"':
                        i += 2
                        continue
                    stack.pop(); depth.pop()
                    i += 1
                    continue
                if c == "$" and i + 1 < n and line[i + 1] == "(":
                    stack.append("sub"); depth.append(1); i += 2
                    continue
                if c == "$" and i + 1 < n and line[i + 1] == "{":
                    stack.append("brace"); depth.append(1); i += 2
                    continue
                i += 1
                continue
            if frame == "brace":
                if c == "}":
                    stack.pop(); depth.pop()
                i += 1
                continue
            # code context (top level or inside a $( ) subexpression)
            if c == "`":
                i += 2
                continue
            if c == "'":
                stack.append("sq"); depth.append(0); i += 1
                continue
            if c == '"':
                stack.append("dq"); depth.append(0); i += 1
                continue
            if c == "@" and i + 1 < n and line[i + 1] in "'\"" and line[i + 2:].strip() == "":
                stack.append("here_sq" if line[i + 1] == "'" else "here_dq"); depth.append(0)
                i = n
                continue
            if c == "<" and i + 1 < n and line[i + 1] == "#":
                uncertain.append((ln, "powershell: block comment <# #> not supported"))
                return comments, uncertain
            if c == "$" and i + 1 < n and line[i + 1] == "{":
                stack.append("brace"); depth.append(1); i += 2
                continue
            if frame == "sub":
                if c == "(":
                    depth[-1] += 1
                elif c == ")":
                    depth[-1] -= 1
                    if depth[-1] == 0:
                        stack.pop(); depth.pop()
                elif c == "#" and (i == 0 or line[i - 1] in _WORD_START_PREV):
                    uncertain.append((ln, "powershell: '#' inside a subexpression"))
                i += 1
                continue
            if c == "#" and (i == 0 or line[i - 1] in _WORD_START_PREV):
                comments.append(PsComment(ln, i, line[:i].strip() == "", line[i:]))
                i = n
                continue
            i += 1
    if stack:
        uncertain.append((len(lines) - 1 if lines else 0, f"powershell: unterminated {stack[-1]} construct"))
    return comments, uncertain


def plan_edits(text: str, line_offset: int = 0):
    comments, uncertain = detect(text)
    edits, preserved, class_b, used = [], [], [], []
    for ln, reason in uncertain:
        class_b.append((ln, reason))
    for c in comments:
        if c.text.lower().startswith("#requires"):
            preserved.append((c.line, RULE_REQUIRES))
            continue
        used.append(c)
        if c.full_line:
            edits.append(Edit("delete_line", c.line + line_offset, rule="powershell.comment"))
        else:
            edits.append(Edit("truncate", c.line + line_offset, col=c.col, rule="powershell.comment.trailing"))
    return edits, preserved, class_b, used


def residual(text: str) -> list:
    comments, uncertain = detect(text)
    out = []
    for c in comments:
        out.append((c.line + 1, RULE_REQUIRES if c.text.lower().startswith("#requires") else None))
    for ln, _r in uncertain:
        out.append((ln + 1, None))
    return sorted(out)


class PowerShellParser:
    """Batch token-stream extraction with the real PowerShell parser.

    The script (ps_tokens.ps1) is passed with -EncodedCommand; input and output travel
    as base64(UTF-8 JSON) over stdin/stdout, so it also works through WSL interop
    (pwsh.exe / powershell.exe reachable from Linux) without temp files or path mapping.
    """

    def __init__(self):
        self.script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ps_tokens.ps1")
        self.exe = None
        self.probe_error = None
        for name in ("pwsh", "pwsh.exe", "powershell.exe"):
            exe = shutil.which(name)
            if not exe:
                continue
            try:
                probe = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", "exit 0"],
                                       capture_output=True, timeout=120)
            except (OSError, subprocess.TimeoutExpired) as exc:     # e.g. WSL without Windows interop
                self.probe_error = f"{exe}: {exc}"
                continue
            if probe.returncode == 0:
                self.exe = exe
                break
            self.probe_error = f"{exe}: rc={probe.returncode}"

    @property
    def available(self) -> bool:
        return self.exe is not None and os.path.isfile(self.script)

    def tokens(self, texts: list) -> list:
        """Return [{'tokens': [(kind, text), ...], 'errors': n}] per input text."""
        if not self.available:
            raise ProdgenError("PowerShell parser unavailable")
        if not texts:
            return []
        with open(self.script, "rb") as fh:
            script = fh.read().decode("utf-8")
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        payload = base64.b64encode(json.dumps(list(texts), ensure_ascii=False).encode("utf-8"))
        cmd = [self.exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]
        proc = subprocess.run(cmd, input=payload, capture_output=True, timeout=900)
        if proc.returncode != 0:
            raise ProdgenError(f"PowerShell parser failed: {proc.stderr.decode('utf-8', 'replace').strip()[:400]}")
        try:
            data = json.loads(base64.b64decode(proc.stdout.strip()).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProdgenError(f"PowerShell parser returned unreadable output: {exc}")
        if isinstance(data, dict):      # single element collapses to an object
            data = [data]
        if len(data) != len(texts):
            raise ProdgenError("PowerShell parser returned an unexpected number of results")
        norm = []
        for item in data:
            toks = item.get("tokens") or []
            if toks and isinstance(toks[0], str):      # single token collapses
                toks = [toks]
            norm.append({"tokens": [tuple(t) for t in toks], "errors": int(item.get("errors") or 0)})
        return norm


def collapse_newlines(tokens: list) -> list:
    """Collapse NewLine runs and drop leading/trailing NewLines (statement separators only)."""
    out = []
    for kind, text in tokens:
        if kind == "NewLine":
            if not out or out[-1][0] == "NewLine":
                continue
        out.append((kind, text))
    while out and out[-1][0] == "NewLine":
        out.pop()
    return out


def streams_equal(a: dict, b: dict) -> bool:
    return a["errors"] == b["errors"] and collapse_newlines(a["tokens"]) == collapse_newlines(b["tokens"])
