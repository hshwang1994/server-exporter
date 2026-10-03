"""Jinja comment ({# ... #}) handling and AST comparison.

ASTs are compared after merging adjacent TemplateData nodes (the lexer drops
comments, which otherwise splits literal text into two nodes). Equality is checked
under trim_blocks=True (what Ansible's templar uses, lstrip_blocks=False) and, when
the policy demands it, under trim_blocks=False as well.
"""
from __future__ import annotations

import re

import jinja2
from jinja2 import nodes

EXTENSIONS = ["jinja2.ext.do", "jinja2.ext.loopcontrols"]
_COMMENT_RE = re.compile(r"\{#")


class _Permissive(dict):
    """Filter/test registry that yields an identity callable for unknown names."""

    def get(self, key, default=None):
        return dict.get(self, key, _identity)

    def __getitem__(self, key):
        return dict.get(self, key, _identity)

    def __contains__(self, key):
        return True


def _identity(value, *args, **kwargs):
    return value


class _PlaceholderUndefined(jinja2.ChainableUndefined):
    """Renders every undefined value as a neutral identifier token."""

    def __str__(self):
        return "__jinja_value__"

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False

    def __len__(self):
        return 0

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __div__ = __rdiv__ = \
        __truediv__ = __rtruediv__ = __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = \
        __pos__ = __neg__ = __lt__ = __le__ = __gt__ = __ge__ = __int__ = __float__ = \
        __complex__ = __pow__ = __rpow__ = lambda self, *a, **k: self

    def __eq__(self, other):
        return False

    def __ne__(self, other):
        return True

    def __hash__(self):
        return id(type(self))


def environment(trim_blocks: bool, render: bool = False) -> jinja2.Environment:
    env = jinja2.Environment(trim_blocks=trim_blocks, lstrip_blocks=False, extensions=EXTENSIONS,
                             undefined=_PlaceholderUndefined if render else jinja2.Undefined)
    if render:
        env.filters = _Permissive(env.filters)
        env.tests = _Permissive(env.tests)
    return env


def _merge_template_data(node):
    for field, value in list(node.iter_fields()):
        if isinstance(value, list):
            merged = []
            for item in value:
                if isinstance(item, nodes.Node):
                    _merge_template_data(item)
                if (isinstance(item, nodes.TemplateData) and merged
                        and isinstance(merged[-1], nodes.TemplateData)):
                    merged[-1] = nodes.TemplateData(merged[-1].data + item.data, lineno=merged[-1].lineno)
                    continue
                if isinstance(item, nodes.TemplateData) and item.data == "":
                    continue
                merged.append(item)
            setattr(node, field, merged)
        elif isinstance(value, nodes.Node):
            _merge_template_data(value)
    return node


def normalized_ast(source: str, trim_blocks: bool):
    env = environment(trim_blocks)
    return _merge_template_data(env.parse(source))


def ast_equal(a: str, b: str, trim_blocks: bool) -> bool:
    return normalized_ast(a, trim_blocks) == normalized_ast(b, trim_blocks)


def parses(source: str) -> bool:
    try:
        environment(True).parse(source)
        return True
    except jinja2.TemplateSyntaxError:
        return False


def find_comment_spans(text: str) -> list:
    """[(start, end)] of {# ... #} comments in template data (not inside {{ }} / {% %} / raw)."""
    spans = []
    i, n = 0, len(text)
    while i < n:
        j_var = text.find("{{", i)
        j_blk = text.find("{%", i)
        j_cmt = text.find("{#", i)
        cands = [j for j in (j_var, j_blk, j_cmt) if j != -1]
        if not cands:
            break
        j = min(cands)
        if j == j_cmt:
            end = text.find("#}", j + 2)
            if end == -1:
                return None
            spans.append((j, end + 2))
            i = end + 2
            continue
        closer = "}}" if j == j_var else "%}"
        k = _skip_tag(text, j + 2, closer)
        if k is None:
            return None
        if j == j_blk:
            inner = text[j + 2:k - 2].strip().strip("-+").strip()
            if inner == "raw" or inner.startswith("raw "):
                e = re.compile(r"\{%-?\s*endraw\s*-?%\}").search(text, k)
                if not e:
                    return None
                k = e.end()
        i = k
    return spans


def _skip_tag(text: str, i: int, closer: str):
    """Skip to the end of a {{ }} / {% %} tag, honouring string literals. Returns index after closer."""
    n = len(text)
    while i < n:
        c = text[i]
        if c in "'\"":
            q = c
            i += 1
            while i < n and text[i] != q:
                if text[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if text.startswith(closer, i):
            return i + 2
        i += 1
    return None


def has_statements(text: str) -> bool:
    return "{%" in text


def render_placeholders(text: str):
    """Replace {{ ... }} expressions line-by-line with a neutral identifier. None if not possible."""
    if has_statements(text) or "{#" in text:
        return None
    out_lines = []
    for line in text.split("\n"):
        pos = 0
        new = ""
        while True:
            j = line.find("{{", pos)
            if j == -1:
                new += line[pos:]
                break
            k = _skip_tag(line, j + 2, "}}")
            if k is None:
                return None          # expression spans lines
            new += line[pos:j] + "__jinja_value__"
            pos = k
        out_lines.append(new)
    return "\n".join(out_lines)
