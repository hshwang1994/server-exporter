import ast

import pytest

from scripts.ai.prodgen.strip import pystrip

SRC = '''#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""Module docstring."""
from __future__ import annotations
import re  # trailing

DOCUMENTATION = r"""
options: {}
"""
RETURN = """x"""
EXAMPLES = """y"""


class K:
    """Class doc."""

    def only_doc(self):
        """Only a docstring body."""

    def f(self, x):
        """Doc."""
        # comment line
        return x  # type: ignore


def g():
    # noqa
    pass
'''


def _no_comments(text):
    import io, tokenize
    toks = [t for t in tokenize.generate_tokens(io.StringIO(text).readline) if t.type == tokenize.COMMENT]
    return [(t.start[0], t.string) for t in toks]


def test_library_drops_all_doc_assigns_and_docstrings():
    res = pystrip.strip(SRC, "library")
    assert not res.class_b
    out = res.output
    assert "DOCUMENTATION" not in out and "RETURN" not in out and "EXAMPLES" not in out
    assert "Module docstring" not in out and "Class doc" not in out
    assert "    def only_doc(self):\n        pass\n" in out
    assert _no_comments(out) == [(1, "#!/usr/bin/python3")], "UTF-8 선언은 Python 3 기본값이라 실행에 필요 없다 (D13)"
    assert [p.rule for p in res.preserved] == ["python.shebang"]
    compile(out, "<t>", "exec")
    for node in ast.walk(ast.parse(out)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            assert ast.get_docstring(node) is None


def test_plugin_keeps_documentation_drops_return_examples():
    res = pystrip.strip(SRC, "plugin")
    assert "DOCUMENTATION = r" in res.output
    assert "RETURN" not in res.output and "EXAMPLES" not in res.output


def test_script_keeps_all_assigns():
    res = pystrip.strip(SRC, "script")
    assert "RETURN = " in res.output and "DOCUMENTATION = " in res.output


def test_doc_runtime_usage_is_class_b_without_override():
    src = '"""Doc first line.\nmore"""\nimport argparse\np = argparse.ArgumentParser(description=__doc__.split("\\n")[0])\n'
    res = pystrip.strip(src, "script")
    assert res.class_b and "__doc__" in res.class_b[0].reason
    assert res.output == src


def test_doc_runtime_override_preserves_module_docstring_only():
    src = '"""Doc first line.\nmore"""\nimport argparse\n\ndef f():\n    """inner"""\n    return __doc__\n'
    res = pystrip.strip(src, "script", doc_runtime="preserve_module_docstring")
    assert not res.class_b
    assert res.output.startswith('"""Doc first line.\nmore"""\n')
    assert "inner" not in res.output
    assert {p.rule for p in res.preserved} == {"python.module_docstring_runtime_referenced"}
    assert [p.line for p in res.preserved] == [1, 2]


def test_comment_only_lines_inside_expressions_are_removed():
    src = "x = [\n    # c\n    1,\n]\n"
    res = pystrip.strip(src, "script")
    assert res.output == "x = [\n    1,\n]\n"
    assert res.removed_full_lines == 1


def test_docstring_sharing_line_with_code_is_class_b():
    src = 'def f():\n    """doc"""; return 1\n'
    res = pystrip.strip(src, "script")
    assert res.class_b


def test_residual_reports_remaining_comments_and_rules():
    stripped = pystrip.strip(SRC, "library").output
    assert pystrip.residual(stripped, "library") == [(1, "python.shebang")]
    assert (3, None) in pystrip.residual("x = 1\ny = 2\n# left\n", "script")



@pytest.mark.parametrize("cookie", ["# -*- coding: utf-8 -*-", "# coding=utf8", "# vim: set fileencoding=UTF-8 :", "# -*- coding: utf_8 -*-"])
def test_utf8_coding_declarations_are_removed(cookie):
    """2026-10-06 (D13): Python 3 의 기본 원본 인코딩은 UTF-8 이다(PEP 3120) — 그 선언은 실행에 필요 없는 설명이라 지운다."""
    src = "#!/usr/bin/env python3\n" + cookie + "\nx = '한글'\n"
    res = pystrip.strip(src, "script")
    assert res.output == "#!/usr/bin/env python3\nx = '한글'\n" and not res.class_b
    assert [p.rule for p in res.preserved] == ["python.shebang"]
    assert pystrip.residual(res.output, "script") == [(1, "python.shebang")]


@pytest.mark.parametrize("cookie", ["# -*- coding: latin-1 -*-", "# coding: euc-kr", "# -*- coding: utf-8-sig -*-", "# coding: no-such-codec"])
def test_other_coding_declarations_are_kept(cookie):
    """다른(또는 모르는) 인코딩 선언은 원본을 읽는 방법을 바꾸므로 실행에 필요하다 — 남긴다."""
    src = "#!/usr/bin/env python3\n" + cookie + "\nx = 1  # trailing\n"
    res = pystrip.strip(src, "script")
    assert res.output == "#!/usr/bin/env python3\n" + cookie + "\nx = 1\n"
    assert [p.rule for p in res.preserved] == ["python.shebang", "python.coding_declaration"]


def test_a_coding_text_below_line_two_is_an_ordinary_comment():
    src = "x = 1\ny = 2\n# -*- coding: latin-1 -*-\n"
    res = pystrip.strip(src, "script")
    assert res.output == "x = 1\ny = 2\n" and res.preserved == []
