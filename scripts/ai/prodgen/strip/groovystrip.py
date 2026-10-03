"""Groovy (Jenkinsfile) stripper.

String/GString/triple/slashy-aware tokenizer removes // and /* */ comments; shell text
inside sh ''' ... ''' / sh \"\"\" ... \"\"\" blocks gets the shell rules (shebang kept).
Ambiguity (division vs slashy, dollar-slashy strings, comments inside ${ }) -> class B.
Verification: re-tokenization of the output has zero comments and the non-comment
token sequence equals the original's (shell-string bodies compared post-strip).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..common import ClassB, Preserved, ProdgenError, StripResult, sha256_text, split_lines_keep_final
from ..editlog import Edit, EditEngine
from . import shellstrip

KEYWORDS_BEFORE_SLASHY = {"return", "in", "case", "assert", "throw", "println", "print", "def", "else", "if",
                          "while", "for", "switch", "new", "as", "instanceof", "not"}
_CODE_TOKEN = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*|\d[\w.]*|\S")
_SHELL_PREFIX = re.compile(r"(?:\bsh\s*\(?\s*|script\s*:\s*)$")
RULE_SHEBANG = shellstrip.RULE_SHEBANG


@dataclass
class Tok:
    kind: str       # code | string | slashy | comment_line | comment_block | newline
    text: str
    start: int
    end: int
    line: int       # 0-based start line
    is_shell: bool = False
    quote: str = ""


class Ambiguous(Exception):
    def __init__(self, line: int, reason: str):
        super().__init__(reason)
        self.line = line
        self.reason = reason


def tokenize(text: str) -> list:
    toks = []
    i, n, line = 0, len(text), 0
    code_start = None

    def flush_code(upto):
        nonlocal code_start
        if code_start is not None and upto > code_start:
            toks.append(Tok("code", text[code_start:upto], code_start, upto, text.count("\n", 0, code_start)))
        code_start = None

    def prev_significant():
        if code_start is not None:
            pending = text[code_start:i].rstrip()
            if pending:
                m = list(_CODE_TOKEN.finditer(pending))
                return ("code", m[-1].group(0)) if m else None
        for t in reversed(toks):
            if t.kind == "newline":
                return t
            if t.kind in ("comment_line", "comment_block"):
                continue
            if t.kind == "code":
                stripped = t.text.rstrip()
                if not stripped:
                    continue
                m = list(_CODE_TOKEN.finditer(stripped))
                return ("code", m[-1].group(0)) if m else None
            return (t.kind, t.text)
        return None

    while i < n:
        c = text[i]
        if c == "\n":
            flush_code(i)
            toks.append(Tok("newline", "\n", i, i + 1, line))
            line += 1
            i += 1
            continue
        if text.startswith("//", i):
            flush_code(i)
            j = text.find("\n", i)
            j = n if j == -1 else j
            toks.append(Tok("comment_line", text[i:j], i, j, line))
            i = j
            continue
        if text.startswith("/*", i):
            flush_code(i)
            j = text.find("*/", i + 2)
            if j == -1:
                raise Ambiguous(line, "groovy: unterminated block comment")
            toks.append(Tok("comment_block", text[i:j + 2], i, j + 2, line))
            line += text.count("\n", i, j + 2)
            i = j + 2
            continue
        if text.startswith("$/", i):
            raise Ambiguous(line, "groovy: dollar-slashy string unsupported")
        if c in "'\"":
            flush_code(i)
            triple = text.startswith(c * 3, i)
            quote = c * 3 if triple else c
            j, nl = _scan_string(text, i + len(quote), quote, line)
            toks.append(Tok("string", text[i:j], i, j, line, quote=quote))
            line += nl
            i = j
            continue
        if c == "/":
            prev = prev_significant()
            division = False
            if prev is not None and prev != "newline" and isinstance(prev, tuple):
                kind, ptext = prev
                if kind in ("string", "slashy"):
                    division = True
                elif kind == "code":
                    if ptext in KEYWORDS_BEFORE_SLASHY:
                        division = False
                    elif re.match(r"[A-Za-z_$0-9]", ptext) or ptext in (")", "]"):
                        division = True
                    elif ptext == "}":
                        raise Ambiguous(line, "groovy: '/' after '}' is ambiguous (division vs slashy)")
                    else:
                        division = False
            elif isinstance(prev, Tok) and prev.kind == "newline":
                raise Ambiguous(line, "groovy: '/' at statement start is ambiguous")
            if division:
                if code_start is None:
                    code_start = i
                i += 1
                continue
            flush_code(i)
            j = i + 1
            while j < n and text[j] != "/":
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "\n":
                    raise Ambiguous(line, "groovy: multi-line slashy string is ambiguous")
                j += 1
            if j >= n:
                raise Ambiguous(line, "groovy: unterminated slashy string")
            toks.append(Tok("slashy", text[i:j + 1], i, j + 1, line))
            i = j + 1
            continue
        if code_start is None:
            code_start = i
        i += 1
    flush_code(n)
    _mark_shell_strings(text, toks)
    return toks


def _scan_string(text: str, i: int, quote: str, line: int):
    """Return (index_after_closing_quote, newlines_consumed). Handles escapes and ${ }."""
    n = len(text)
    nl = 0
    gstring = quote[0] == '"'
    while i < n:
        c = text[i]
        if c == "\\":
            if i + 1 < n and text[i + 1] == "\n":
                nl += 1
            i += 2
            continue
        if text.startswith(quote, i):
            return i + len(quote), nl
        if c == "\n":
            if len(quote) == 1:
                raise Ambiguous(line, "groovy: newline inside a single-line string")
            nl += 1
            i += 1
            continue
        if gstring and c == "$" and i + 1 < n and text[i + 1] == "{":
            depth = 1
            j = i + 2
            while j < n and depth > 0:
                cj = text[j]
                if cj in "'\"":
                    q = cj * 3 if text.startswith(cj * 3, j) else cj
                    j, sub_nl = _scan_string(text, j + len(q), q, line)
                    nl += sub_nl
                    continue
                if text.startswith("//", j) or text.startswith("/*", j):
                    raise Ambiguous(line, "groovy: comment inside ${ } interpolation unsupported")
                if cj == "{":
                    depth += 1
                elif cj == "}":
                    depth -= 1
                elif cj == "\n":
                    nl += 1
                j += 1
            if depth != 0:
                raise Ambiguous(line, "groovy: unterminated ${ } interpolation")
            i = j
            continue
        i += 1
    raise Ambiguous(line, "groovy: unterminated string literal")


def _mark_shell_strings(text: str, toks: list) -> None:
    for idx, t in enumerate(toks):
        if t.kind != "string" or len(t.quote) != 3:
            continue
        body = t.text[3:-3]
        prefix = ""
        for p in reversed(toks[:idx]):
            if p.kind in ("comment_line", "comment_block"):
                continue
            if p.kind == "newline":
                break
            prefix = p.text + prefix
            if p.kind != "code":
                break
        if body.lstrip().startswith("#!") or _SHELL_PREFIX.search(prefix.rstrip()):
            t.is_shell = True


def significant(toks: list, string_override=None) -> list:
    """Token sequence for equality: strings as units, code split into lexical tokens,
    NL runs collapsed and leading/trailing NLs dropped (statement separators only)."""
    out = []
    for t in toks:
        if t.kind in ("comment_line", "comment_block"):
            continue
        if t.kind == "newline":
            if not out or out[-1] == ("NL", ""):
                continue
            out.append(("NL", ""))
        elif t.kind == "code":
            for m in _CODE_TOKEN.finditer(t.text):
                out.append(("code", m.group(0)))
        else:
            text = t.text
            if string_override and t.start in string_override:
                text = string_override[t.start]
            out.append((t.kind, text))
    while out and out[-1] == ("NL", ""):
        out.pop()
    return out


# ── shell bodies inside Groovy strings ───────────────────────────────────────
_GROOVY_ESCAPES = {"$": "$", "\\": "\\", '"': '"', "'": "'"}
_INTERP_RE = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
PLACEHOLDER = "__groovy__"


def render_shell_line(line: str, gstring: bool):
    """One Groovy string-body line -> (rendered_line, colmap) or None.

    colmap[k] is the body column where rendered column k starts (len(rendered)+1 entries).
    Escapes that would change the line structure (\\n, \\t, \\uXXXX, line continuation) -> None.
    """
    out, colmap = [], []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "\\":
            if i + 1 >= n:
                return None                 # backslash-newline continuation joins lines
            nxt = line[i + 1]
            if nxt in _GROOVY_ESCAPES:
                out.append(_GROOVY_ESCAPES[nxt])
                colmap.append(i)
                i += 2
                continue
            return None
        if gstring and c == "$":
            m = _INTERP_RE.match(line, i)
            if m:
                for ch in PLACEHOLDER:
                    out.append(ch)
                    colmap.append(i)
                i = m.end()
                continue
        out.append(c)
        colmap.append(i)
        i += 1
    colmap.append(n)
    return "".join(out), colmap


def render_shell_body(body: str, gstring: bool):
    """Groovy string body -> representative shell text (line structure preserved) or None."""
    rendered = []
    for line in body.split("\n"):
        r = render_shell_line(line, gstring)
        if r is None:
            return None
        rendered.append(r[0])
    return "\n".join(rendered)


class GroovyStripper:
    def __init__(self, text: str, path: str, ctx):
        self.text = text
        self.path = path
        self.ctx = ctx
        self.result = StripResult(output=text)

    def _b(self, line0: int, reason: str, lines):
        self.result.class_b.append(ClassB(line0 + 1, reason, sha256_text(lines[line0]) if line0 < len(lines) else ""))

    def run(self) -> StripResult:
        text = self.text
        lines, _ = split_lines_keep_final(text)
        try:
            toks = tokenize(text)
        except Ambiguous as exc:
            self._b(exc.line, exc.reason, lines)
            return self.result
        edits = []
        full = trailing = 0
        for t in toks:
            if t.kind == "comment_line":
                col = t.start - (text.rfind("\n", 0, t.start) + 1)
                if lines[t.line][:col].strip() == "":
                    edits.append(Edit("delete_line", t.line, rule="groovy.comment"))
                    full += 1
                else:
                    edits.append(Edit("truncate", t.line, col=col, rule="groovy.comment.trailing"))
                    trailing += 1
            elif t.kind == "comment_block":
                l1 = t.line
                l2 = l1 + t.text.count("\n")
                c1 = t.start - (text.rfind("\n", 0, t.start) + 1)
                c2 = t.end - (text.rfind("\n", 0, t.end) + 1)
                if lines[l1][:c1].strip() == "" and lines[l2][c2:].strip() == "":
                    edits.append(Edit("delete_line", l1, l2, rule="groovy.comment.block"))
                    full += l2 - l1 + 1
                else:
                    left_ws = lines[l1][:c1].endswith((" ", "\t"))
                    right_ws = lines[l2][c2:].startswith((" ", "\t"))
                    end = c2
                    if left_ws and right_ws:
                        while end < len(lines[l2]) and lines[l2][end] in " \t":
                            end += 1
                    filler = "" if (left_ws or right_ws) else " "
                    edits.append(Edit("replace_span", l1, l2, c1, end, filler, rule="groovy.comment.block.inline"))
                    trailing += 1
        # shell blocks
        overrides = {}
        shell_pairs = []
        preserved_src = []          # (source line, rule) — mapped to output lines after the edits
        shell_full = shell_trailing = 0
        for t in toks:
            if t.kind != "string" or not t.is_shell:
                continue
            body = t.text[3:-3]
            gstring = t.quote[0] == '"'
            rendered = render_shell_body(body, gstring)
            if rendered is None:
                self._b(t.line, "groovy: shell block contains escapes that change line structure", lines)
                continue
            comments, uncertain = shellstrip.detect(rendered)
            for ln, reason in uncertain:
                self._b(t.line + ln, reason, lines)
            if uncertain:
                continue
            body_lines = body.split("\n")
            rendered_lines = rendered.split("\n")
            if len(body_lines) != len(rendered_lines):
                self._b(t.line, "groovy: shell rendering changed the line count", lines)
                continue
            new_body = list(body_lines)
            new_rendered = list(rendered_lines)
            block_edits = []
            used = []
            ok = True
            for c in comments:
                if c.line == 0 and c.col == 0 and c.text.startswith("#!"):
                    preserved_src.append((t.line, RULE_SHEBANG))
                    continue
                src_line = t.line + c.line
                src_text = lines[src_line]
                # the comment must live on a line fully inside the literal (not the opening/closing line)
                if c.line == 0 or c.line == len(body_lines) - 1:
                    self._b(src_line, "groovy: shell comment on the literal's opening/closing line", lines)
                    ok = False
                    break
                body_line = body_lines[c.line]
                if body_line != src_text:
                    self._b(src_line, "groovy: shell block line does not map 1:1 to the source line", lines)
                    ok = False
                    break
                _r, colmap = render_shell_line(body_line, gstring)
                body_col = 0 if c.full_line else colmap[c.col]
                comment_src = body_line[body_col:]
                if "$" in comment_src or "\\" in comment_src:
                    self._b(src_line, "groovy: shell comment text contains interpolation/escapes", lines)
                    ok = False
                    break
                if c.full_line:
                    block_edits.append(Edit("delete_line", src_line, rule="shell.comment"))
                    new_body[c.line] = None
                    new_rendered[c.line] = None
                else:
                    block_edits.append(Edit("truncate", src_line, col=body_col, rule="shell.comment.trailing"))
                    new_body[c.line] = body_line[:body_col].rstrip(" \t")
                    new_rendered[c.line] = rendered_lines[c.line][:c.col].rstrip(" \t")
                used.append(c)
            if not ok or not used:
                continue
            nb = "\n".join(l for l in new_body if l is not None)
            nr = "\n".join(l for l in new_rendered if l is not None)
            a, b = shellstrip.shlex_tokens(rendered), shellstrip.shlex_tokens(nr)
            if a is None or b is None or a != b:
                self._b(t.line, "groovy: shell lexer disagreement (shlex)", lines)
                continue
            left, unc = shellstrip.detect(nr)
            left = [c for c in left if not (c.line == 0 and c.col == 0 and c.text.startswith("#!"))]
            if left or unc:
                self._b(t.line, "groovy: residual shell comments in block", lines)
                continue
            shell_pairs.append((t, rendered, nr, block_edits, used, nb))
        checker = getattr(self.ctx, "shell_checker", None)
        if shell_pairs:
            if checker is not None and checker.available:
                texts = []
                for _t, r, nr, _e, _u, _nb in shell_pairs:
                    texts += [r, nr]
                rcs = checker.check(texts)
                survivors = []
                for idx, pair in enumerate(shell_pairs):
                    if rcs[2 * idx] != rcs[2 * idx + 1]:
                        self._b(pair[0].line, f"groovy: shell parity failed {rcs[2 * idx]} -> {rcs[2 * idx + 1]}", lines)
                    else:
                        survivors.append(pair)
                shell_pairs = survivors
                self.result.notes.append(f"shell syntax parity checked for {len(shell_pairs)} sh block(s)")
            else:
                self.result.notes.append("shell syntax parity (bash -n / sh -n) skipped: no checker available")
        for t, _r, _nr, block_edits, used, nb in shell_pairs:
            edits += block_edits
            overrides[t.start] = t.quote + nb + t.quote
            shell_full += sum(1 for c in used if c.full_line)
            shell_trailing += sum(1 for c in used if not c.full_line)
        if self.result.class_b and not edits:
            return self.result
        engine = EditEngine(text)
        output = engine.apply(edits)
        try:
            out_toks = tokenize(output)
        except Ambiguous as exc:
            raise ProdgenError(f"{self.path}: stripped Groovy is ambiguous: {exc.reason}")
        if any(t.kind in ("comment_line", "comment_block") for t in out_toks):
            raise ProdgenError(f"{self.path}: comments remain after Groovy stripping")
        if significant(toks, overrides) != significant(out_toks):
            raise ProdgenError(f"{self.path}: Groovy token sequence changed by comment removal")
        line_map = engine.line_map(edits)
        for src_line, rule in preserved_src:
            self.result.preserved.append(Preserved(line_map[src_line] + 1, rule, sha256_text(lines[src_line])))
        self.result.output = output
        self.result.removed_full_lines = full + shell_full
        self.result.removed_trailing = trailing + shell_trailing
        self.result.counters = {"groovy_full": full, "groovy_trailing": trailing,
                                "shell_full": shell_full, "shell_trailing": shell_trailing}
        return self.result


def strip(text: str, path: str, ctx) -> StripResult:
    return GroovyStripper(text, path, ctx).run()


def residual(text: str, ctx=None) -> list:
    out = []
    try:
        toks = tokenize(text)
    except Ambiguous as exc:
        return [(exc.line + 1, None)]
    for t in toks:
        if t.kind in ("comment_line", "comment_block"):
            out.append((t.line + 1, None))
        elif t.kind == "string" and t.is_shell:
            body = t.text[3:-3]
            rendered = render_shell_body(body, t.quote[0] == '"')
            if rendered is None:
                out.append((t.line + 1, None))
                continue
            comments, uncertain = shellstrip.detect(rendered)
            for c in comments:
                if c.line == 0 and c.col == 0 and c.text.startswith("#!"):
                    out.append((t.line + 1, RULE_SHEBANG))
                else:
                    out.append((t.line + c.line + 1, None))
            for ln, _r in uncertain:
                out.append((t.line + ln + 1, None))
    return sorted(out)
