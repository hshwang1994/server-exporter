import pytest

from scripts.ai.prodgen.common import ProdgenError
from scripts.ai.prodgen.editlog import Edit, EditEngine, count_removed


def test_delete_truncate_and_span_edits_apply_bottom_up():
    src = "a\n# full\nb = 1  # trailing\nc {# x #} d\ne\n"
    edits = [
        Edit("delete_line", 1, rule="t"),
        Edit("truncate", 2, col=6, rule="t"),
        Edit("remove_span", 3, 3, 2, 9, rule="t"),
    ]
    out = EditEngine(src).apply(edits)
    assert out == "a\nb = 1\nc  d\ne\n"
    assert count_removed(edits) == (1, 1, 1)


def test_replace_span_multi_line_to_pass():
    src = 'def f():\n    """doc\n    more"""\n'
    out = EditEngine(src).apply([Edit("replace_span", 1, 2, 0, 11, "    pass", rule="t")])
    assert out == "def f():\n    pass\n"


def test_final_newline_presence_follows_the_source():
    assert EditEngine("a\n# c").apply([Edit("delete_line", 1)]) == "a"
    assert EditEngine("a\n# c\n").apply([Edit("delete_line", 1)]) == "a\n"
    assert EditEngine("a\nb").apply([]) == "a\nb"


def test_overlapping_deletions_rejected():
    with pytest.raises(ProdgenError):
        EditEngine("a\nb\n").apply([Edit("delete_line", 0), Edit("delete_line", 0)])


def test_out_of_range_rejected():
    with pytest.raises(ProdgenError):
        EditEngine("a\n").apply([Edit("delete_line", 3)])
    with pytest.raises(ProdgenError):
        EditEngine("ab\n").apply([Edit("truncate", 0, col=5)])


def test_truncate_strips_trailing_whitespace_only_before_cut():
    assert EditEngine("x = 1    # c\n").apply([Edit("truncate", 0, col=9)]) == "x = 1\n"


def test_diff_shape_detects_insertions(monkeypatch):
    engine = EditEngine("a\nb\n")
    # Fabricate a corrupt expectation to prove the invariant trips on inserts.
    monkeypatch.setattr(engine, "_expected_lines", lambda edits: ["a", "b", "c"])
    with pytest.raises(ProdgenError):
        engine.apply([])
