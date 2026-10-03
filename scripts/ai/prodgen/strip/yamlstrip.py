"""YAML stripper.

Layer 1  : '#' comments outside yaml.scan token spans (verified by safe_load deep-equal
           AND compose-tree equality).
Layer 2a : Jinja {# ... #} inside scalar values (verified by normalized Jinja AST
           equality; policy decides whether trim_blocks=False must hold as well).
Layer 2b : literal block scalars under raw/shell (shell) and win_shell (PowerShell):
           full-line / trailing comments removed only when two lexers agree.
Anything outside the supported subset (anchors, aliases, tags, directives, multi-doc,
quoted Jinja-comment scalars, folded script blocks with comments, ...) is class B.
"""
from __future__ import annotations

import yaml
from yaml.tokens import (AliasToken, AnchorToken, BlockEndToken, BlockMappingStartToken, BlockSequenceStartToken,
                         DirectiveToken, DocumentEndToken, DocumentStartToken, FlowMappingStartToken,
                         FlowSequenceStartToken, FlowMappingEndToken, FlowSequenceEndToken, KeyToken,
                         ScalarToken, TagToken, ValueToken)
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from ..common import ClassB, Preserved, ProdgenError, StripResult, sha256_text, split_lines_keep_final
from ..editlog import Edit, EditEngine
from . import jinjastrip, psstrip, shellstrip

SHELL_KEYS = frozenset({"raw", "shell"})
PS_KEYS = frozenset({"win_shell"})
ARGV_KEYS = frozenset({"command", "win_command"})     # argv — no comment syntax, never touched
CMD_SUBKEYS = frozenset({"cmd", "_raw_params"})

RULE_SHELL_SHEBANG = shellstrip.RULE_SHEBANG
RULE_PS_REQUIRES = psstrip.RULE_REQUIRES


# ── scanning helpers ─────────────────────────────────────────────────────────
def scan(text: str) -> list:
    try:
        return list(yaml.scan(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise ProdgenError(f"yaml.scan failed: {exc}")


def unsupported(tokens: list) -> list:
    """Class-B reasons for YAML features outside the supported subset."""
    reasons = []
    doc_starts = 0
    for t in tokens:
        if isinstance(t, (AnchorToken, AliasToken)):
            reasons.append((t.start_mark.line, "yaml: anchors/aliases unsupported"))
        elif isinstance(t, TagToken):
            reasons.append((t.start_mark.line, "yaml: tags unsupported"))
        elif isinstance(t, DirectiveToken):
            reasons.append((t.start_mark.line, "yaml: directives unsupported"))
        elif isinstance(t, DocumentStartToken):
            doc_starts += 1
            if doc_starts > 1:
                reasons.append((t.start_mark.line, "yaml: multi-document stream unsupported"))
        elif isinstance(t, DocumentEndToken):
            reasons.append((t.start_mark.line, "yaml: explicit document end unsupported"))
    return reasons


def scalar_spans(tokens: list, text: str) -> list:
    """[(start_index, end_index, token)] — block scalars start after their header line."""
    spans = []
    for t in tokens:
        if not isinstance(t, ScalarToken):
            continue
        s, e = t.start_mark.index, t.end_mark.index
        if t.style in ("|", ">"):
            nl = text.find("\n", s)
            s = nl + 1 if (nl != -1 and nl + 1 <= e) else e
        spans.append((s, e, t))
    return spans


def _in_spans(idx: int, spans: list) -> bool:
    for s, e, _t in spans:
        if s <= idx < e:
            return True
    return False


def layer1_candidates(text: str, tokens: list) -> list:
    """[(line0, col, full_line)] for every '#' that is a YAML comment."""
    spans = scalar_spans(tokens, text)
    out = []
    line_start = 0
    for ln, line in enumerate(text.split("\n")):
        for col, ch in enumerate(line):
            if ch != "#":
                continue
            if col > 0 and line[col - 1] not in " \t":
                continue
            idx = line_start + col
            if _in_spans(idx, spans):
                continue
            out.append((ln, col, line[:col].strip() == ""))
            break           # rest of the line is the comment
        line_start += len(line) + 1
    return out


# ── compose-tree comparison ──────────────────────────────────────────────────
def compose(text: str):
    try:
        return yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        raise ProdgenError(f"yaml.compose failed: {exc}")


def trees_equal(a, b, scalar_hook=None) -> bool:
    if a is None or b is None:
        return a is b
    if type(a) is not type(b) or a.tag != b.tag:
        return False
    if isinstance(a, ScalarNode):
        if a.style != b.style:
            return False
        if a.value == b.value:
            return True
        return bool(scalar_hook and scalar_hook(a, b))
    if isinstance(a, SequenceNode):
        if a.flow_style != b.flow_style or len(a.value) != len(b.value):
            return False
        return all(trees_equal(x, y, scalar_hook) for x, y in zip(a.value, b.value))
    if isinstance(a, MappingNode):
        if a.flow_style != b.flow_style or len(a.value) != len(b.value):
            return False
        for (ka, va), (kb, vb) in zip(a.value, b.value):
            if not trees_equal(ka, kb, scalar_hook) or not trees_equal(va, vb, scalar_hook):
                return False
        return True
    return False


def _safe_load(text: str):
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProdgenError(f"yaml.safe_load failed: {exc}")


# ── script block discovery ───────────────────────────────────────────────────
def _short(key: str) -> str:
    return key.rsplit(".", 1)[-1]


def script_blocks(tokens: list):
    """Yield (language, key_token, value_token) for script module arguments.

    language: 'shell' | 'powershell' | 'argv'. Handles `key: <scalar>` and
    `key:` mapping form with `cmd:` / `_raw_params:` one level down.
    """
    n = len(tokens)
    for i, t in enumerate(tokens):
        if not isinstance(t, KeyToken) or i + 3 >= n:
            continue
        k = tokens[i + 1]
        if not isinstance(k, ScalarToken) or not isinstance(tokens[i + 2], ValueToken):
            continue
        short = _short(str(k.value))
        if short in SHELL_KEYS:
            lang = "shell"
        elif short in PS_KEYS:
            lang = "powershell"
        elif short in ARGV_KEYS:
            lang = "argv"
        else:
            continue
        v = tokens[i + 3]
        if isinstance(v, ScalarToken):
            yield lang, k, v
        elif isinstance(v, BlockMappingStartToken):
            depth = 1
            j = i + 4
            while j < n and depth > 0:
                tj = tokens[j]
                if isinstance(tj, (BlockMappingStartToken, BlockSequenceStartToken, FlowMappingStartToken, FlowSequenceStartToken)):
                    depth += 1
                elif isinstance(tj, (BlockEndToken, FlowMappingEndToken, FlowSequenceEndToken)):
                    depth -= 1
                elif depth == 1 and isinstance(tj, KeyToken) and j + 3 < n:
                    kk = tokens[j + 1]
                    if isinstance(kk, ScalarToken) and str(kk.value) in CMD_SUBKEYS \
                            and isinstance(tokens[j + 2], ValueToken) and isinstance(tokens[j + 3], ScalarToken):
                        yield lang, kk, tokens[j + 3]
                j += 1


def _block_geometry(text: str, tok: ScalarToken):
    """(first_content_line0, indent) for a literal block scalar token."""
    header_line = tok.start_mark.line
    lines = text.split("\n")
    first = header_line + 1
    indent = None
    ln = first
    while ln < len(lines) and ln <= tok.end_mark.line:
        line = lines[ln]
        if line.strip() != "":
            indent = len(line) - len(line.lstrip(" "))
            break
        ln += 1
    return first, indent


# ── main entry points ────────────────────────────────────────────────────────
class YamlStripper:
    def __init__(self, text: str, path: str, ctx):
        self.path = path
        self.ctx = ctx
        self.text = text
        self.result = StripResult(output=text)
        self.counters = {
            "layer1_full": 0, "layer1_trailing": 0,
            "jinja_comments": 0, "jinja_verified_both": 0, "jinja_verified_ansible_only": 0,
            "shell_full": 0, "shell_trailing": 0, "ps_full": 0, "ps_trailing": 0,
        }

    def _b(self, line0: int, reason: str, text_line: str = ""):
        self.result.class_b.append(ClassB(line0 + 1, reason, sha256_text(text_line) if text_line else ""))

    def run(self) -> StripResult:
        tokens = scan(self.text)
        lines, _ = split_lines_keep_final(self.text)
        for ln, reason in unsupported(tokens):
            self._b(ln, reason, lines[ln] if ln < len(lines) else "")
        if self.result.class_b:
            return self.result
        text1 = self._layer1(self.text, tokens)
        text2 = self._layer2a(text1)
        text3 = self._layer2b(text2)
        self.result.output = text3
        self.result.counters = dict(self.counters)
        self.result.removed_full_lines = (self.counters["layer1_full"] + self.counters["shell_full"]
                                          + self.counters["ps_full"])
        self.result.removed_trailing = (self.counters["layer1_trailing"] + self.counters["shell_trailing"]
                                        + self.counters["ps_trailing"])
        return self.result

    # layer 1 ----------------------------------------------------------------
    def _layer1(self, text: str, tokens: list) -> str:
        cands = layer1_candidates(text, tokens)
        if not cands:
            return text
        edits = []
        for ln, col, full in cands:
            if full:
                edits.append(Edit("delete_line", ln, rule="yaml.comment"))
                self.counters["layer1_full"] += 1
            else:
                edits.append(Edit("truncate", ln, col=col, rule="yaml.comment.trailing"))
                self.counters["layer1_trailing"] += 1
        out = EditEngine(text).apply(edits)
        if _safe_load(text) != _safe_load(out):
            raise ProdgenError(f"{self.path}: yaml.safe_load changed after layer-1 comment removal")
        if not trees_equal(compose(text), compose(out)):
            raise ProdgenError(f"{self.path}: yaml.compose tree changed after layer-1 comment removal")
        if layer1_candidates(out, scan(out)):
            raise ProdgenError(f"{self.path}: residual YAML comments after layer 1")
        return out

    # layer 2a ---------------------------------------------------------------
    def _layer2a(self, text: str) -> str:
        policy = (self.ctx.policy.get("jinja_trim_blocks") or "ansible").lower()
        progress = True
        done_values = set()
        while progress:
            progress = False
            tokens = scan(text)
            lines, _ = split_lines_keep_final(text)
            for t in tokens:
                if not isinstance(t, ScalarToken) or not isinstance(t.value, str) or "{#" not in t.value:
                    continue
                key = (t.start_mark.index, t.value)
                if key in done_values:
                    continue
                done_values.add(key)
                new_text = self._strip_scalar_jinja(text, t, lines, policy)
                if new_text is not None and new_text != text:
                    text = new_text
                    progress = True
                    break
        return text

    def _strip_scalar_jinja(self, text: str, tok: ScalarToken, lines: list, policy: str):
        line0 = tok.start_mark.line
        if tok.style in ('"', "'"):
            self._b(line0, "jinja: comment inside a quoted YAML scalar is unsupported", lines[line0])
            return None
        value_spans = jinjastrip.find_comment_spans(tok.value)
        if value_spans is None:
            self._b(line0, "jinja: unbalanced {# in scalar", lines[line0])
            return None
        if not value_spans:
            return None
        if not jinjastrip.parses(tok.value):
            self._b(line0, "jinja: scalar with {# does not parse as a template", lines[line0])
            return None
        s, e = tok.start_mark.index, tok.end_mark.index
        if tok.style in ("|", ">"):
            nl = text.find("\n", s)
            s = nl + 1
        region = text[s:e]
        src_spans = jinjastrip.find_comment_spans(region)
        if src_spans is None or len(src_spans) != len(value_spans):
            self._b(line0, "jinja: could not map comment spans from value to source", lines[line0])
            return None
        # absolute (line, col) for each span
        abs_spans = []
        for a, b in src_spans:
            abs_spans.append((self._pos(text, s + a), self._pos(text, s + b)))
        variants = [self._variant_edits(lines, abs_spans, mode) for mode in
                    ("whole_or_dash_span", "dash_span", "whole_or_plain_span", "plain_span")]
        original_value = tok.value
        for edits in variants:
            try:
                out = EditEngine(text).apply(edits)
            except ProdgenError:
                continue
            try:
                new_tree = compose(out)
            except ProdgenError:
                continue
            verdict = {"both": False, "ansible": False}

            def hook(a, b):
                if a.value != original_value or not isinstance(b.value, str):
                    return False
                try:
                    ok_t = jinjastrip.ast_equal(a.value, b.value, True)
                    ok_f = jinjastrip.ast_equal(a.value, b.value, False)
                except Exception:
                    return False
                verdict["ansible"] = ok_t
                verdict["both"] = ok_t and ok_f
                return ok_t if policy == "ansible" else (ok_t and ok_f)

            if not trees_equal(compose(text), new_tree, hook):
                continue
            n = len(abs_spans)
            self.counters["jinja_comments"] += n
            if verdict["both"]:
                self.counters["jinja_verified_both"] += n
            else:
                self.counters["jinja_verified_ansible_only"] += n
            return out
        self._b(line0, "jinja: no comment-removal variant preserves the template AST", lines[line0])
        return None

    @staticmethod
    def _pos(text: str, idx: int) -> tuple:
        line = text.count("\n", 0, idx)
        col = idx - (text.rfind("\n", 0, idx) + 1)
        return line, col

    @staticmethod
    def _variant_edits(lines: list, abs_spans: list, mode: str) -> list:
        """Edit variants for a set of Jinja comment spans.

        whole_* : delete whole lines when the comment is alone on its lines
        dash_*  : mimic Jinja whitespace control — {#- eats same-line whitespace before,
                  -#} eats same-line whitespace after
        plain_* : remove exactly the {# ... #} span
        Every variant is verified by Jinja AST equality before it is accepted.
        """
        edits = []
        whole = mode.startswith("whole")
        dash = "dash" in mode
        for (l1, c1), (l2, c2) in abs_spans:
            s1, e2 = c1, c2
            text = lines[l1][c1:] if l1 != l2 else lines[l1][c1:c2]
            if dash:
                if text.startswith("{#-"):
                    while s1 > 0 and lines[l1][s1 - 1] in " \t":
                        s1 -= 1
                if lines[l2][:c2].endswith("-#}"):
                    while e2 < len(lines[l2]) and lines[l2][e2] in " \t":
                        e2 += 1
            prefix = lines[l1][:s1]
            suffix = lines[l2][e2:]
            if whole and prefix.strip() == "" and suffix.strip() == "":
                edits.append(Edit("delete_line", l1, l2, rule="jinja.comment"))
            else:
                edits.append(Edit("remove_span", l1, l2, s1, e2, rule="jinja.comment.span"))
        return edits

    # layer 2b ---------------------------------------------------------------
    def _layer2b(self, text: str) -> str:
        tokens = scan(text)
        lines, _ = split_lines_keep_final(text)
        plans = []       # dicts: lang, tok, edits, expected_value, rendered pair, preserved
        for lang, ktok, vtok in script_blocks(tokens):
            if lang == "argv":
                continue
            value = vtok.value if isinstance(vtok.value, str) else ""
            detector = shellstrip.detect if lang == "shell" else psstrip.detect
            rendered = value
            if "{{" in value or "{%" in value or "{#" in value:
                rendered = jinjastrip.render_placeholders(value)
            if vtok.style != "|":
                if rendered is None:
                    continue
                comments, uncertain = detector(rendered)
                if comments or uncertain:
                    self._b(vtok.start_mark.line, f"{lang}: comments in a non-literal ({vtok.style or 'plain'}) script scalar", lines[vtok.start_mark.line])
                continue
            first, indent = _block_geometry(text, vtok)
            if indent is None:
                continue
            if rendered is None:
                if detector(value)[0] or detector(value)[1]:
                    self._b(vtok.start_mark.line, f"{lang}: Jinja statements / multi-line expressions in script block (no representative rendering)", lines[vtok.start_mark.line])
                continue
            if lang == "shell":
                edits_rel, preserved, class_b, used = shellstrip.plan_edits(rendered, 0)
            else:
                edits_rel, preserved, class_b, used = psstrip.plan_edits(rendered, 0)
            for ln, reason in class_b:
                self._b(first + ln, reason, lines[first + ln] if first + ln < len(lines) else "")
            if class_b or not used:
                if preserved:
                    plans.append({"lang": lang, "tok": vtok, "edits": [], "preserved": preserved, "first": first,
                                  "value": value})
                continue
            # comment text must not carry Jinja (would remove an expression evaluation)
            bad = [c for c in used if "{{" in value.split("\n")[c.line][c.col:] or "{%" in value.split("\n")[c.line][c.col:]]
            if bad:
                for c in bad:
                    self._b(first + c.line, f"{lang}: comment text contains a Jinja expression", lines[first + c.line])
                continue
            value_lines = value.split("\n")
            rendered_lines = rendered.split("\n")
            if len(value_lines) != len(rendered_lines):
                self._b(vtok.start_mark.line, f"{lang}: rendering changed the line count", lines[vtok.start_mark.line])
                continue
            new_value_lines = list(value_lines)
            new_rendered_lines = list(rendered_lines)
            edits = []
            for c in used:
                src_line = first + c.line
                if src_line >= len(lines):
                    raise ProdgenError(f"{self.path}: script block line mapping out of range")
                src = lines[src_line]
                src_indent = len(src) - len(src.lstrip(" "))
                if src_indent < indent or src[indent:] != value_lines[c.line]:
                    self._b(src_line, f"{lang}: block line does not map 1:1 to the scalar value", src)
                    edits = None
                    break
                if c.full_line:
                    edits.append(Edit("delete_line", src_line, rule=f"{lang}.comment"))
                    new_value_lines[c.line] = None
                    new_rendered_lines[c.line] = None
                else:
                    col = indent + c.col
                    edits.append(Edit("truncate", src_line, col=col, rule=f"{lang}.comment.trailing"))
                    new_value_lines[c.line] = value_lines[c.line][:c.col].rstrip(" \t")
                    new_rendered_lines[c.line] = rendered_lines[c.line][:c.col].rstrip(" \t")
            if edits is None:
                continue
            expected_value = "\n".join(l for l in new_value_lines if l is not None)
            new_rendered = "\n".join(l for l in new_rendered_lines if l is not None)
            plans.append({"lang": lang, "tok": vtok, "edits": edits, "preserved": preserved, "first": first,
                          "expected": expected_value, "rendered": rendered, "new_rendered": new_rendered,
                          "used": used, "value": value})
        plans = self._verify_blocks(plans, lines)
        edits = [e for p in plans for e in p["edits"]]
        engine = EditEngine(text)
        line_map = engine.line_map(edits)
        for p in plans:
            for ln, rule in p["preserved"]:
                src_line = p["first"] + ln
                self.result.preserved.append(Preserved(line_map[src_line] + 1, rule, sha256_text(lines[src_line])))
        if not edits:
            return text
        out = engine.apply(edits)
        expected = {p["tok"].value: p["expected"] for p in plans if p["edits"]}

        def hook(a, b):
            return a.value in expected and expected[a.value] == b.value

        if not trees_equal(compose(text), compose(out), hook):
            raise ProdgenError(f"{self.path}: compose tree changed unexpectedly after script-block stripping")
        for p in plans:
            n_full = sum(1 for c in p.get("used", []) if c.full_line)
            n_trail = sum(1 for c in p.get("used", []) if not c.full_line)
            if p["lang"] == "shell":
                self.counters["shell_full"] += n_full
                self.counters["shell_trailing"] += n_trail
            else:
                self.counters["ps_full"] += n_full
                self.counters["ps_trailing"] += n_trail
        return out

    def _verify_blocks(self, plans: list, lines: list) -> list:
        kept = []
        shell_pairs, ps_pairs = [], []
        for p in plans:
            if not p["edits"]:
                kept.append(p)
                continue
            (shell_pairs if p["lang"] == "shell" else ps_pairs).append(p)
        # shell: lexer-B (shlex) agreement + residual + structural parity
        for p in shell_pairs:
            a, b = shellstrip.shlex_tokens(p["rendered"]), shellstrip.shlex_tokens(p["new_rendered"])
            line0 = p["tok"].start_mark.line
            if a is None or b is None:
                self._b(line0, "shell: shlex could not tokenize the block (lexer B unavailable)", lines[line0])
                continue
            if a != b:
                self._b(line0, "shell: lexer disagreement (shlex token stream changed)", lines[line0])
                continue
            left, unc = shellstrip.detect(p["new_rendered"])
            left = [c for c in left if not (c.line == 0 and c.col == 0 and c.text.startswith("#!"))]
            if left or unc:
                self._b(line0, "shell: residual comments after block stripping", lines[line0])
                continue
            kept.append(p)
        checker = getattr(self.ctx, "shell_checker", None)
        shell_kept = [p for p in kept if p["edits"] and p["lang"] == "shell"]
        if shell_kept:
            if checker is not None and checker.available:
                texts = []
                for p in shell_kept:
                    texts += [p["rendered"], p["new_rendered"]]
                rcs = checker.check(texts)
                for idx, p in enumerate(shell_kept):
                    if rcs[2 * idx] != rcs[2 * idx + 1]:
                        line0 = p["tok"].start_mark.line
                        self._b(line0, f"shell: bash -n / sh -n parity failed {rcs[2 * idx]} -> {rcs[2 * idx + 1]}", lines[line0])
                        kept.remove(p)
                self.result.notes.append(f"shell syntax parity checked for {len(shell_kept)} block(s)")
            else:
                self.result.notes.append("shell syntax parity (bash -n / sh -n) skipped: no checker available")
        # powershell: real parser token streams
        if ps_pairs:
            parser = getattr(self.ctx, "ps_parser", None)
            if parser is None or not parser.available:
                for p in ps_pairs:
                    line0 = p["tok"].start_mark.line
                    self._b(line0, "powershell: no PowerShell parser available — comments stay (class B)", lines[line0])
            else:
                texts = []
                for p in ps_pairs:
                    texts += [p["value"], p["expected"]]
                streams = parser.tokens(texts)
                for idx, p in enumerate(ps_pairs):
                    line0 = p["tok"].start_mark.line
                    if not psstrip.streams_equal(streams[2 * idx], streams[2 * idx + 1]):
                        self._b(line0, "powershell: parser token stream changed by comment removal", lines[line0])
                        continue
                    kept.append(p)
        return kept


def strip(text: str, path: str, ctx) -> StripResult:
    return YamlStripper(text, path, ctx).run()


def residual(text: str, ctx=None) -> list:
    """Comment-like text in a stripped YAML file: [(line_1based, rule_or_None)]."""
    out = []
    tokens = scan(text)
    if unsupported(tokens):
        return [(ln + 1, None) for ln, _r in unsupported(tokens)]
    for ln, _col, _full in layer1_candidates(text, tokens):
        out.append((ln + 1, None))
    for t in tokens:
        if isinstance(t, ScalarToken) and isinstance(t.value, str) and "{#" in t.value:
            spans = jinjastrip.find_comment_spans(t.value)
            if spans:
                out.append((t.start_mark.line + 1, None))
    for lang, _k, vtok in script_blocks(tokens):
        if lang == "argv":
            continue
        value = vtok.value if isinstance(vtok.value, str) else ""
        rendered = value
        if "{{" in value or "{%" in value:
            rendered = jinjastrip.render_placeholders(value)
            if rendered is None:
                rendered = value
        detector = shellstrip.detect if lang == "shell" else psstrip.detect
        comments, uncertain = detector(rendered)
        first = vtok.start_mark.line + 1
        for c in comments:
            if lang == "shell" and c.line == 0 and c.col == 0 and c.text.startswith("#!"):
                out.append((first + c.line + 1, RULE_SHELL_SHEBANG))
            elif lang == "powershell" and c.text.lower().startswith("#requires"):
                out.append((first + c.line + 1, RULE_PS_REQUIRES))
            else:
                out.append((first + c.line + 1, None))
        for ln, _r in uncertain:
            out.append((first + ln + 1, None))
    return sorted(out)
