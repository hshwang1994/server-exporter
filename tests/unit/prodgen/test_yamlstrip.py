import textwrap

import pytest
import yaml

from scripts.ai.prodgen.strip import jinjastrip, psstrip, yamlstrip


def _strip(text, ctx):
    return yamlstrip.strip(textwrap.dedent(text), "<t>", ctx)


def test_layer1_removes_only_true_yaml_comments(ctx):
    src = '''\
    ---
    # file comment
    - name: "a # not a comment"   # trailing
      ansible.builtin.set_fact:
        x: 'q # quoted'
        y: >-
          folded # kept (data)
        z: |   # header comment
          # block data line
          echo a
      vars: {k: v}  # after flow
    '''
    res = _strip(src, ctx)
    assert not res.class_b
    out = res.output
    assert "file comment" not in out and "trailing" not in out and "header comment" not in out and "after flow" not in out
    assert "a # not a comment" in out and "q # quoted" in out and "folded # kept (data)" in out
    assert "# block data line" in out
    assert yaml.safe_load(out) == yaml.safe_load(textwrap.dedent(src))
    assert res.counters["layer1_full"] == 1 and res.counters["layer1_trailing"] == 3


def test_unsupported_yaml_features_are_class_b(ctx):
    for snippet, word in (("a: &x 1\nb: *x\n", "anchors"), ("a: !!str 1\n", "tags"),
                          ("---\na: 1\n---\nb: 2\n", "multi-document"), ("%YAML 1.2\n---\na: 1\n", "directives")):
        res = yamlstrip.strip(snippet, "<t>", ctx)
        assert res.class_b and word in res.class_b[0].reason
        assert res.output == snippet


def test_jinja_comment_in_folded_scalar_removed_with_ast_proof(ctx):
    src = '''\
    - set_fact:
        v: >-
          {%- set out = [] -%}
          {# explanatory comment
             spanning lines #}
          {%- for i in [1, 2] -%}{%- set _ = out.append(i) -%}{%- endfor -%}
          {{ out }}  {#- inline -#}
    '''
    res = _strip(src, ctx)
    assert not res.class_b
    assert "{#" not in res.output
    assert res.counters["jinja_comments"] == 2
    a = yaml.safe_load(textwrap.dedent(src))[0]["set_fact"]["v"]
    b = yaml.safe_load(res.output)[0]["set_fact"]["v"]
    assert jinjastrip.ast_equal(a, b, True) and jinjastrip.ast_equal(a, b, False)


def test_jinja_comment_that_only_verifies_under_ansible_setting(ctx, ctx_both):
    # The more-indented continuation keeps a real newline after '#}' in the folded value, so
    # trim_blocks=True (Ansible's templar) eats it while trim_blocks=False keeps it.
    src = '''\
    - set_fact:
        v: >-
          {# comment before an expression
             continued on a more-indented line #}
          {{ lookup('env', 'X') }}
    '''
    res = _strip(src, ctx)
    assert not res.class_b and res.counters["jinja_verified_ansible_only"] == 1
    res_both = _strip(src, ctx_both)
    assert res_both.class_b and "no comment-removal variant" in res_both.class_b[0].reason


def test_jinja_comment_folded_into_a_space_is_class_b(ctx):
    # Folding turns the line break after '#}' into a space the original rendering keeps.
    src = '- set_fact:\n    v: >-\n      {# c #}\n      {{ x }}\n'
    res = yamlstrip.strip(src, "<t>", ctx)
    assert res.class_b and "no comment-removal variant" in res.class_b[0].reason
    assert res.output == src


def test_jinja_comment_in_quoted_scalar_is_class_b(ctx):
    res = _strip('- set_fact:\n    v: "{# c #}{{ x }}"\n', ctx)
    assert res.class_b and "quoted" in res.class_b[0].reason


def test_shell_block_comments_removed_argv_and_folded_untouched(ctx):
    src = '''\
    - name: raw
      ansible.builtin.raw: |
        #!/bin/sh
        # full comment
        echo "# not a comment"   # trailing
        x=$#
    - name: cmd
      ansible.builtin.command: |
        echo # argv literal
    - name: folded
      ansible.builtin.shell: >
        echo a
    '''
    res = _strip(src, ctx)
    assert not res.class_b
    out = yaml.safe_load(res.output)
    raw = out[0]["ansible.builtin.raw"]
    assert raw == '#!/bin/sh\necho "# not a comment"\nx=$#\n'
    assert out[1]["ansible.builtin.command"] == "echo # argv literal\n"
    assert res.counters["shell_full"] == 1 and res.counters["shell_trailing"] == 1
    assert any(p.rule == "shell.shebang" for p in res.preserved)


def test_folded_shell_block_with_comment_is_class_b(ctx):
    src = '- shell: >\n    # comment folds into the next line\n    echo a\n'
    res = yamlstrip.strip(src, "<t>", ctx)
    assert res.class_b and "non-literal" in res.class_b[0].reason


def test_shell_block_with_jinja_expression_uses_placeholder_rendering(ctx):
    src = '''\
    - ansible.builtin.raw: |
        # comment
        echo {{ some_var | default("x") }}
    - ansible.builtin.raw: |
        # comment inside statement block
        {% if x %}echo a{% endif %}
    '''
    res = _strip(src, ctx)
    out = yaml.safe_load(res.output)
    assert out[0]["ansible.builtin.raw"] == 'echo {{ some_var | default("x") }}\n'
    assert res.class_b and "Jinja statements" in res.class_b[0].reason
    assert "# comment inside statement block" in res.output


def test_powershell_block_is_class_b_without_parser(ctx):
    src = '- ansible.windows.win_shell: |\n    # ps comment\n    Get-Volume\n'
    res = yamlstrip.strip(src, "<t>", ctx)
    assert res.class_b and "PowerShell parser" in res.class_b[0].reason
    assert res.output == src


@pytest.mark.skipif(not psstrip.PowerShellParser().available, reason="no PowerShell parser on this host")
def test_powershell_block_stripped_with_real_parser(ctx):
    ctx.ps_parser = psstrip.PowerShellParser()
    src = ('- ansible.windows.win_shell: |\n'
           '    #requires -Version 5\n'
           '    # ps comment\n'
           '    $s = "a # not" + \'b # not\'   # trailing\n'
           '    Get-Volume | Where-Object { $_.Size -gt 0 }\n')
    res = yamlstrip.strip(src, "<t>", ctx)
    assert not res.class_b
    v = yaml.safe_load(res.output)[0]["ansible.windows.win_shell"]
    assert v == '#requires -Version 5\n$s = "a # not" + \'b # not\'\nGet-Volume | Where-Object { $_.Size -gt 0 }\n'
    assert res.counters["ps_full"] == 1 and res.counters["ps_trailing"] == 1
    assert any(p.rule == "powershell.requires" for p in res.preserved)


def test_residual_scan_reports_leftovers_and_rules(ctx):
    text = '- raw: |\n    #!/bin/sh\n    echo a\n# left\n'
    assert yamlstrip.residual(text, ctx) == [(2, "shell.shebang"), (4, None)]
    assert yamlstrip.residual('- set_fact:\n    v: "{{ x }}"\n', ctx) == []


def test_script_blocks_discovers_cmd_form():
    toks = yamlstrip.scan("- shell:\n    cmd: |\n      echo a\n    chdir: /tmp\n")
    found = [(lang, k.value) for lang, k, _v in yamlstrip.script_blocks(toks)]
    assert found == [("shell", "cmd")]
