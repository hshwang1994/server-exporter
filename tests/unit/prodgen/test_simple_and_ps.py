import pytest

from scripts.ai.prodgen.common import ProdgenError
from scripts.ai.prodgen.strip import psstrip, simplestrip


def test_ini_full_line_comments_removed_and_values_equal():
    src = "# top\n[defaults]\n; semi\nforks = 20   \nkey = a # not inline comment\n\n[x]\n#c\ny=1\n"
    res = simplestrip.strip_ini(src, "<t>")
    assert res.output == "[defaults]\nforks = 20   \nkey = a # not inline comment\n\n[x]\ny=1\n"
    assert res.removed_full_lines == 3
    assert simplestrip.residual_ini(res.output) == []


def test_gitmeta_only_first_column_hash_is_comment():
    src = "# c\n*.sh text eol=lf\n  # pattern-ish, kept\n\\#literal\n"
    res = simplestrip.strip_gitmeta(src, "<t>")
    assert res.output == "*.sh text eol=lf\n  # pattern-ish, kept\n\\#literal\n"


def test_vault_header_and_payload_checks():
    good = b"$ANSIBLE_VAULT;1.1;AES256\n6162636465\n"
    assert simplestrip.check_vault(good, "v") == []
    assert simplestrip.check_vault(b"plain: text\n", "v")
    assert simplestrip.check_vault(b"$ANSIBLE_VAULT;1.1;AES256\nnot hex!\n", "v")
    res = simplestrip.strip_vault(good, "v")
    assert not res.class_b


def test_powershell_lexer_cases():
    text = ('#requires -Version 5\n'
            "$a = 'it''s # not' + \"x # not $(1 # sub) y\"\n"
            '@"\n# inside here-string\n"@\n'
            "Write-Host a#b   # real trailing\n"
            "# full\n")
    comments, uncertain = psstrip.detect(text)
    assert [(c.line, c.full_line, c.text) for c in comments] == [
        (0, True, "#requires -Version 5"), (5, False, "# real trailing"), (6, True, "# full")]
    assert uncertain == [(1, "powershell: '#' inside a subexpression")]
    edits, preserved, class_b, used = psstrip.plan_edits(text)
    assert preserved == [(0, "powershell.requires")]
    assert len(used) == 2 and class_b == [(1, "powershell: '#' inside a subexpression")]


def test_powershell_block_comment_is_unsupported():
    comments, uncertain = psstrip.detect("<# block #>\nGet-Volume\n")
    assert comments == [] and uncertain and "block comment" in uncertain[0][1]


def test_collapse_newlines_drops_edges_and_runs():
    toks = [("NewLine", "\n"), ("A", "a"), ("NewLine", "\n"), ("NewLine", "\n"), ("B", "b"), ("NewLine", "\n")]
    assert psstrip.collapse_newlines(toks) == [("A", "a"), ("NewLine", "\n"), ("B", "b")]


@pytest.mark.skipif(not psstrip.PowerShellParser().available, reason="no PowerShell parser on this host")
def test_real_parser_streams_equal_after_comment_removal():
    parser = psstrip.PowerShellParser()
    a, b = parser.tokens(["# c\n$x = 1 # t\n# d\n", "$x = 1\n"])
    assert psstrip.streams_equal(a, b)
    a, b = parser.tokens(["$x = 1\n", "$x = 2\n"])
    assert not psstrip.streams_equal(a, b)
