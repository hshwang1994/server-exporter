import pytest

from scripts.ai.prodgen.strip import groovystrip

SRC = '''\
// header comment
@NonCPS
Map c() {
    /* block
       comment */
    def url = 'http://x/y/z'  // trailing
    long t = (long) (System.currentTimeMillis() / 1000L)
    if (code ==~ /2\\d\\d/) { return [a: 1 /* inline */ + 2] }
    def s = params.x.trim().replaceAll(/\\s/, '') + "${a} // not a comment"
    def r = sh(returnStatus: true, script: """#!/bin/bash
        set -e
        # shell comment line
        echo "${groovyVar}" \\${shellVar}   # trailing shell comment
        exit 0
    """)
    return r
}
'''


def test_groovy_comments_and_shell_comments_removed(ctx):
    res = groovystrip.strip(SRC, "<t>", ctx)
    assert not res.class_b, res.class_b
    out = res.output
    assert "header comment" not in out and "block\n" not in out and "trailing" not in out.split("sh(")[0]
    assert "inline" not in out
    assert "// not a comment" in out                       # inside a GString
    assert "/2\\d\\d/" in out and "/ 1000L" in out
    assert "# shell comment line" not in out
    assert 'echo "${groovyVar}" \\${shellVar}\n' in out
    # header comment (1 line) + block comment (2 lines) = 3 full lines; '// trailing' + inline block = 2
    assert res.counters == {"groovy_full": 3, "groovy_trailing": 2, "shell_full": 1, "shell_trailing": 1}
    assert [p.rule for p in res.preserved] == ["shell.shebang"]
    assert groovystrip.residual(out, ctx) == [(7, "shell.shebang")]      # 3 comment lines above were deleted


def test_dollar_slashy_and_division_after_brace_are_class_b(ctx):
    res = groovystrip.strip("def x = $/a/$\n", "<t>", ctx)
    assert res.class_b and "dollar-slashy" in res.class_b[0].reason
    res = groovystrip.strip("def y = { 1 } / 2\n", "<t>", ctx)
    assert res.class_b and "ambiguous" in res.class_b[0].reason


def test_comment_inside_interpolation_is_class_b(ctx):
    res = groovystrip.strip('def s = "${ a // b }"\n', "<t>", ctx)
    assert res.class_b


def test_shell_comment_with_interpolation_stays(ctx):
    src = 'sh """#!/bin/bash\n    # keep ${x}\n    echo a\n"""\n'
    res = groovystrip.strip(src, "<t>", ctx)
    assert res.class_b and "interpolation" in res.class_b[0].reason
    assert "# keep ${x}" in res.output


def test_token_sequence_equality_check_detects_tampering():
    toks = groovystrip.tokenize("a = 1 // c\nb = 2\n")
    assert groovystrip.significant(toks) == [("code", "a"), ("code", "="), ("code", "1"), ("NL", ""),
                                             ("code", "b"), ("code", "="), ("code", "2")]
    assert groovystrip.significant(groovystrip.tokenize("a = 1\nb = 2\n")) == groovystrip.significant(toks)
    assert groovystrip.significant(groovystrip.tokenize("a = 1\nb = 3\n")) != groovystrip.significant(toks)


def test_render_shell_body_handles_escapes_and_interpolation():
    assert groovystrip.render_shell_body('echo \\"${a}\\" \\${b} $c.d', True) == 'echo "__groovy__" ${b} __groovy__'
    assert groovystrip.render_shell_body("tab\\there", True) is None
