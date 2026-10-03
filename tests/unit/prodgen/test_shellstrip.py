from scripts.ai.prodgen.strip import shellstrip


def _comment_lines(text):
    comments, uncertain = shellstrip.detect(text)
    return [(c.line, c.full_line) for c in comments], uncertain


def test_plain_comments_full_and_trailing():
    lines, unc = _comment_lines("#!/bin/sh\n# full\necho a # trailing\necho b\n")
    assert lines == [(0, True), (1, True), (2, False)]
    assert unc == []


def test_hash_inside_quotes_and_expansions_is_not_a_comment():
    text = "echo '# not' \"# not\" ${#x} $# a#b\nx=${y#pre}\nawk '{ # awk\n}' file\n"
    lines, unc = _comment_lines(text)
    assert lines == [] and unc == []


def test_heredoc_body_is_data():
    text = "cat <<EOF\n# inside heredoc\nEOF\n# after\n"
    lines, unc = _comment_lines(text)
    assert lines == [(3, True)] and unc == []


def test_comment_after_backslash_continuation_is_uncertain():
    text = "echo a \\\n# looks like a comment\necho c\n"
    lines, unc = _comment_lines(text)
    assert lines == []
    assert unc and "continuation" in unc[0][1]


def test_hash_inside_command_substitution_is_uncertain():
    lines, unc = _comment_lines("x=$(echo a # b)\n")
    assert lines == [] and unc


def test_strip_text_removes_and_verifies_with_shlex():
    text = "#!/bin/bash\n# c1\nset -u\nx=1  # c2\necho \"$x\"\n"
    res = shellstrip.strip_text(text)
    assert not res.class_b
    assert res.output == "#!/bin/bash\nset -u\nx=1\necho \"$x\"\n"
    assert res.removed_full_lines == 1 and res.removed_trailing == 1
    assert [p.rule for p in res.preserved] == ["shell.shebang"]
    assert shellstrip.residual(res.output) == [(1, "shell.shebang")]


def test_shlex_tokens_equal_after_strip_for_posix_sample():
    text = "if [ -n \"$a\" ]; then\n  # note\n  echo \"${a}\" | tr -d ' '  # trim\nfi\n"
    res = shellstrip.strip_text(text)
    assert shellstrip.shlex_tokens(text) == shellstrip.shlex_tokens(res.output)
    assert "# note" not in res.output and "# trim" not in res.output
