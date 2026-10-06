"""Python stripper: tokenize-located comments + AST-located docstrings.

Verification (all must hold, otherwise ProdgenError / class B):
  * compile(output) succeeds
  * ast.dump(independent NodeTransformer(original)) == ast.dump(output)
  * tokenize(output) has no COMMENT tokens other than the preserved ones
  * ast.get_docstring(node) is None for every node (unless the manifest keeps the
    module docstring because the code reads __doc__ at runtime)
  * __doc__ / inspect.getdoc usage without a manifest override -> class B
"""
from __future__ import annotations

import ast
import codecs
import io
import re
import tokenize

from ..common import ClassB, Preserved, ProdgenError, StripResult, sha256_text, split_lines_keep_final
from ..editlog import Edit, EditEngine

DOC_ASSIGNS_LIBRARY = frozenset({"DOCUMENTATION", "RETURN", "EXAMPLES", "ANSIBLE_METADATA"})
DOC_ASSIGNS_PLUGIN = frozenset({"RETURN", "EXAMPLES"})
CODING_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")



def _keeps_source_encoding(line: str) -> bool:
    """A coding declaration is runtime-required only when it names an encoding other than UTF-8 (2026-10-06, D13).

    Python 3 reads source as UTF-8 by default (PEP 3120), so `# -*- coding: utf-8 -*-` changes nothing and is removed like any
    other comment. Any other (or unknown) encoding is kept — removing it would change how the file is decoded.
    """
    m = CODING_RE.match(line)
    if not m or not line.lstrip().startswith("#"):
        return False
    try:
        return codecs.lookup(m.group(1)).name != "utf-8"
    except LookupError:
        return True


RULE_SHEBANG = "python.shebang"
RULE_CODING = "python.coding_declaration"
RULE_MODULE_DOC_RUNTIME = "python.module_docstring_runtime_referenced"


def drop_set_for(kind: str) -> frozenset:
    if kind == "library":
        return DOC_ASSIGNS_LIBRARY
    if kind == "plugin":
        return DOC_ASSIGNS_PLUGIN
    return frozenset()


def _is_docstring_stmt(stmt) -> bool:
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str))


def _is_drop_assign(stmt, drop: frozenset) -> bool:
    return (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id in drop
            and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str))


class _ReferenceTransformer(ast.NodeTransformer):
    """Independent reference: remove docstrings (+ drop assigns at module level)."""

    def __init__(self, drop: frozenset, keep_module_doc: bool):
        self.drop = drop
        self.keep_module_doc = keep_module_doc

    def _strip_body(self, node, is_module):
        body = list(node.body)
        if body and _is_docstring_stmt(body[0]) and not (is_module and self.keep_module_doc):
            body = body[1:]
        if is_module:
            body = [s for s in body if not _is_drop_assign(s, self.drop)]
        if not body:
            body = [ast.Pass()]
        node.body = body
        return node

    def visit_Module(self, node):
        self.generic_visit(node)
        return self._strip_body(node, True)

    def visit_ClassDef(self, node):
        self.generic_visit(node)
        return self._strip_body(node, False)

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        return self._strip_body(node, False)

    def visit_AsyncFunctionDef(self, node):
        self.generic_visit(node)
        return self._strip_body(node, False)


def doc_runtime_usage(tree) -> list:
    """Lines where __doc__ or inspect.getdoc is referenced by the code."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in ("__doc__", "getdoc"):
            hits.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr in ("__doc__", "getdoc"):
            hits.append(node.lineno)
    return sorted(set(hits))


def _comment_tokens(text: str):
    toks = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            toks.append(tok)
    return toks


def detect(text: str, python_kind: str, doc_runtime=None) -> dict:
    """Locate everything the stripper would act on. Used by strip() and by the residual scan."""
    tree = ast.parse(text)
    lines, _ = split_lines_keep_final(text)
    drop = drop_set_for(python_kind)
    usage = doc_runtime_usage(tree)
    keep_module_doc = bool(usage) and doc_runtime == "preserve_module_docstring"
    stmts = []     # (node_kind, stmt, replace_with_pass)

    def collect(node, is_module):
        body = list(node.body)
        removed = []
        if body and _is_docstring_stmt(body[0]) and not (is_module and keep_module_doc):
            removed.append(("docstring", body[0]))
        if is_module:
            removed += [("assign", s) for s in body if _is_drop_assign(s, drop)]
        remaining = len(body) - len(removed)
        for idx, (kind, s) in enumerate(removed):
            stmts.append((kind, s, remaining == 0 and idx == 0))

    for node in ast.walk(tree):
        if isinstance(node, ast.Module):
            collect(node, True)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            collect(node, False)

    comments = []
    preserved = []
    for tok in _comment_tokens(text):
        row, col = tok.start
        if row == 1 and col == 0 and tok.string.startswith("#!"):
            preserved.append((row - 1, RULE_SHEBANG))
            continue
        if row <= 2 and _keeps_source_encoding(lines[row - 1]):
            preserved.append((row - 1, RULE_CODING))
            continue
        comments.append((row - 1, col, tok.string))
    module_doc_lines = []
    if keep_module_doc and tree.body and _is_docstring_stmt(tree.body[0]):
        s = tree.body[0]
        module_doc_lines = list(range(s.lineno - 1, s.end_lineno))
    return {
        "tree": tree, "stmts": stmts, "comments": comments, "preserved": preserved,
        "doc_usage": usage, "keep_module_doc": keep_module_doc, "drop": drop,
        "module_doc_lines": module_doc_lines,
    }


def strip(text: str, python_kind: str, doc_runtime=None, path: str = "<python>") -> StripResult:
    info = detect(text, python_kind, doc_runtime)
    lines, _ = split_lines_keep_final(text)
    result = StripResult(output=text)

    if info["doc_usage"] and not info["keep_module_doc"]:
        for ln in info["doc_usage"]:
            result.class_b.append(ClassB(ln, "python.__doc__/getdoc referenced at runtime; "
                                         "manifest override doc_runtime=preserve_module_docstring required",
                                         sha256_text(lines[ln - 1])))
        return result

    edits = []
    consumed = set()
    for kind, stmt, with_pass in info["stmts"]:
        first, last = stmt.lineno - 1, stmt.end_lineno - 1
        prefix = lines[first][:stmt.col_offset]
        suffix = lines[last][stmt.end_col_offset:]
        if prefix.strip() != "" or not (suffix.strip() == "" or suffix.lstrip().startswith("#")):
            result.class_b.append(ClassB(first + 1, f"python.{kind} shares its line with other code",
                                         sha256_text(lines[first])))
            continue
        consumed.update(range(first, last + 1))
        if with_pass:
            edits.append(Edit("replace_span", first, last, 0, len(lines[last]), prefix + "pass",
                              f"python.{kind}.pass"))
        else:
            edits.append(Edit("delete_line", first, last, rule=f"python.{kind}"))
    doc_lines = sum(e.end_line - e.line + 1 for e in edits)

    full = trailing = 0
    for row, col, _s in info["comments"]:
        if row in consumed:
            continue
        if lines[row][:col].strip() == "":
            edits.append(Edit("delete_line", row, rule="python.comment"))
            full += 1
        else:
            edits.append(Edit("truncate", row, col=col, rule="python.comment.trailing"))
            trailing += 1

    if result.class_b:
        return result

    engine = EditEngine(text)
    output = engine.apply(edits)
    _verify(text, output, info, path)

    result.output = output
    result.removed_full_lines = full
    result.removed_trailing = trailing
    result.counters = {"docstring_lines": doc_lines, "comment_lines": full, "trailing_comments": trailing}
    out_lines, _ = split_lines_keep_final(output)
    line_map = engine.line_map(edits)
    for row, rule in info["preserved"]:
        result.preserved.append(Preserved(line_map[row] + 1, rule, sha256_text(lines[row])))
    if info["keep_module_doc"]:
        out_info = detect(output, python_kind, doc_runtime)
        for row in out_info["module_doc_lines"]:
            result.preserved.append(Preserved(row + 1, RULE_MODULE_DOC_RUNTIME, sha256_text(out_lines[row])))
        result.notes.append("module docstring preserved: __doc__ is read at runtime (manifest doc_runtime override)")
    return result


def _verify(text: str, output: str, info: dict, path: str) -> None:
    try:
        compile(output, path, "exec")
    except SyntaxError as exc:
        raise ProdgenError(f"{path}: stripped python does not compile: {exc}")
    ref = _ReferenceTransformer(info["drop"], info["keep_module_doc"]).visit(ast.parse(text))
    got = ast.parse(output)
    if ast.dump(ref) != ast.dump(got):
        raise ProdgenError(f"{path}: AST mismatch between reference transformer and stripped output")
    remaining = _comment_tokens(output)
    allowed = len(info["preserved"])
    if len(remaining) != allowed:
        raise ProdgenError(f"{path}: {len(remaining)} comment tokens remain (expected {allowed})")
    for tok in remaining:
        row, col = tok.start
        ok = (row == 1 and col == 0 and tok.string.startswith("#!")) or (row <= 2 and _keeps_source_encoding(tok.line))
        if not ok:
            raise ProdgenError(f"{path}: unexpected residual comment at line {row}")
    for node in ast.walk(got):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node, clean=False) is not None:
                if isinstance(node, ast.Module) and info["keep_module_doc"]:
                    continue
                raise ProdgenError(f"{path}: docstring remains on {type(node).__name__} at line {getattr(node, 'lineno', 1)}")


def residual(text: str, python_kind: str, doc_runtime=None) -> list:
    """Comment-like text left in a stripped file: [(line_1based, rule_or_None)]."""
    info = detect(text, python_kind, doc_runtime)
    out = [(row + 1, None) for row, _c, _s in info["comments"]]
    out += [(row + 1, rule) for row, rule in info["preserved"]]
    for kind, stmt, _ in info["stmts"]:
        out.append((stmt.lineno, None))
    for row in info["module_doc_lines"]:
        out.append((row + 1, RULE_MODULE_DOC_RUNTIME))
    return sorted(out)
