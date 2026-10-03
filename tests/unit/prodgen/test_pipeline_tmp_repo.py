"""End-to-end build / verify / promote / restore / drift-check against a throwaway git repo.

Never touches the real repository's refs: every ref written lives in the temporary repo.
"""
import json
import os
import pathlib
import subprocess

import pytest

from scripts.ai.prodgen import PROVENANCE_FILE
from scripts.ai.prodgen.build import FAILURE_FILE, build
from scripts.ai.prodgen.drift import drift_check
from scripts.ai.prodgen.gitstore import GitStore
from scripts.ai.prodgen.promote import promote, restore
from scripts.ai.prodgen.verify import run_gates
from scripts.ai.prodgen.strip.psstrip import PowerShellParser

# 임시 저장소에는 win_shell 블록이 있어 PowerShell 파서(pwsh / powershell.exe)가 없으면 class B 가 남아 build 가 실패한다 —
# 그 환경(예: Windows interop 이 막힌 WSL, pwsh 없는 Linux Runner)에서는 생성 전 과정을 타는 테스트만 건너뛴다 (GP-16).
_needs_ps = pytest.mark.skipif(not PowerShellParser().available,
                               reason="PowerShell 파서 없음 — prodgen 의 PowerShell 주석 제거는 pwsh/powershell.exe 가 필요하다")

MANIFEST = """\
version: 1
runtime_roots: [app, cfg.ini, vault]
include:
  - path: app/main.py
    language: python
    python_kind: script
    mode: "100644"
  - path: app/run.sh
    language: shell
    mode: "100755"
  - path: app/tasks.yml
    language: yaml
    mode: "100644"
  - path: cfg.ini
    language: ini
    mode: "100644"
  - glob: "vault/**/*.yml"
    language: vault
    mode: "100644"
excluded:
  - path: app/notes.txt
    reason: documentation only
ignore: ["**/README.md"]
forbidden: ["docs/**"]
policy: {eol: lf, powershell_strip: true, jinja_trim_blocks: ansible}
"""
FILES = {
    "app/main.py": '"""doc"""\n# c\nimport json\n\n\ndef f(x):\n    """d"""\n    return json.dumps(x)  # t\n',
    "app/run.sh": "#!/bin/bash\n# c\necho hi  # t\n",
    "app/tasks.yml": "---\n# c\n- name: t\n  ansible.builtin.raw: |\n    # sh\n    echo a\n  vars:\n    v: >-\n      {# j #}{{ x }}\n",
    "cfg.ini": "# c\n[defaults]\nforks = 5\n",
    "vault/x.yml": "$ANSIBLE_VAULT;1.1;AES256\n6162636465\n",
    "app/notes.txt": "notes\n",
    "app/README.md": "# readme\n",
    "docs/x.md": "# doc\n",
}


def _git(repo, *args, **kw):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                          cwd=repo, capture_output=True, text=True, check=True, **kw).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    for rel, content in FILES.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8"))
    (repo / "production_manifest.yml").write_bytes(MANIFEST.encode("utf-8"))
    _git(repo, "add", "-A")
    _git(repo, "update-index", "--chmod=+x", "app/run.sh")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_build_strips_and_writes_provenance(repo, tmp_path):
    sha = _git(repo, "rev-parse", "HEAD")
    out = tmp_path / "out"
    rep = build(str(repo), sha, str(out), str(repo / "production_manifest.yml"), live_checkers=False)
    assert rep.ok and rep.provenance_written
    assert rep.file_count == 5
    assert (out / "app" / "main.py").read_text() == "import json\n\n\ndef f(x):\n    return json.dumps(x)\n"
    assert (out / "app" / "run.sh").read_text() == "#!/bin/bash\necho hi\n"
    assert (out / "cfg.ini").read_text() == "[defaults]\nforks = 5\n"
    assert (out / "vault" / "x.yml").read_bytes() == FILES["vault/x.yml"].encode()
    tasks = (out / "app" / "tasks.yml").read_text()
    assert "# c" not in tasks and "# sh" not in tasks and "{# j #}" not in tasks
    prov = json.loads((out / PROVENANCE_FILE).read_text())
    assert prov["main_sha"] == sha and prov["excluded"] == {"app/notes.txt": "documentation only"}
    assert prov["files"]["app/run.sh"]["mode"] == "100755"
    assert "generated_at" not in json.dumps(prov).lower()
    # determinism
    out2 = tmp_path / "out2"
    rep2 = build(str(repo), sha, str(out2), str(repo / "production_manifest.yml"), live_checkers=False)
    assert rep2.tree_hash == rep.tree_hash
    assert (out2 / PROVENANCE_FILE).read_bytes() == (out / PROVENANCE_FILE).read_bytes()


@_needs_ps
def test_crlf_source_is_refused(repo, tmp_path):
    (repo / "cfg.ini").write_bytes(b"[defaults]\r\nforks = 7\r\n")
    _git(repo, "commit", "-qam", "crlf")
    rep = build(str(repo), "HEAD", str(tmp_path / "out"), str(repo / "production_manifest.yml"), live_checkers=False)
    assert not rep.ok and rep.class_b[0][0] == "cfg.ini" and "CR byte" in rep.class_b[0][2]


@_needs_ps
def test_class_b_blocks_provenance(repo, tmp_path):
    (repo / "app" / "tasks.yml").write_bytes(b"---\n- set_fact:\n    a: &x 1\n    b: *x\n")
    _git(repo, "commit", "-qam", "anchor")
    sha = _git(repo, "rev-parse", "HEAD")
    out = tmp_path / "out"
    rep = build(str(repo), sha, str(out), str(repo / "production_manifest.yml"), live_checkers=False)
    assert not rep.ok and not rep.provenance_written
    assert (out / FAILURE_FILE).exists() and not (out / PROVENANCE_FILE).exists()
    assert rep.class_b[0][0] == "app/tasks.yml"


def test_unclassified_runtime_file_fails_classification(repo, tmp_path):
    (repo / "app" / "extra.cfg").write_bytes(b"x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "extra")
    rep = build(str(repo), "HEAD", str(tmp_path / "out"), str(repo / "production_manifest.yml"), live_checkers=False)
    assert not rep.ok
    assert any("G02" in e and "app/extra.cfg" in e for e in rep.classification["errors"])


@_needs_ps
def test_offline_gates_pass_on_tmp_tree(repo, tmp_path):
    sha = _git(repo, "rev-parse", "HEAD")
    out = tmp_path / "out"
    build(str(repo), sha, str(out), str(repo / "production_manifest.yml"), live_checkers=False)
    report = run_gates(str(repo), str(out), str(repo / "production_manifest.yml"), skip_live=True,
                       only="G01,G02,G03,G04,G05,G06,G07,G08,G09,G10,G16")
    assert report.ok, report.summary()
    g08 = [r for r in report.results if r.id == "G08"][0]
    assert g08.data["ansible_cfg"].startswith("not allowlisted")        # cfg checks skipped, not failed
    assert g08.data["counts"]["include_tasks"] == 0 and g08.data["python_imports_checked"] == 1


@_needs_ps
def test_promote_dry_run_writes_nothing(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    res = promote(str(repo), sha, str(repo / "production_manifest.yml"), dry_run=True, skip_live=True)
    assert res["ok"] and res["dry_run"] and len(res["tree"]) == 40
    assert res["files"] == 6
    assert "Main-SHA: " + sha in res["message"] and "Previous-Production: none" in res["message"]
    assert not GitStore(str(repo)).rev_exists("refs/heads/production")
    probe = subprocess.run(["git", "cat-file", "-e", res["tree"]], cwd=repo, capture_output=True)
    assert probe.returncode != 0, "dry-run must not write the tree object"


@_needs_ps
def test_promote_restore_and_drift(repo):
    sha = _git(repo, "rev-parse", "HEAD")
    man = str(repo / "production_manifest.yml")
    res1 = promote(str(repo), sha, man, dry_run=False, skip_live=True, ci_build="unit-1")
    assert res1["ok"]
    store = GitStore(str(repo))
    prod1 = store.rev_parse("refs/heads/production")
    assert prod1 == res1["commit"]
    trailers = GitStore.parse_trailers(store.commit_message(prod1))
    assert trailers["Main-SHA"] == sha and trailers["CI-Build"] == "unit-1" and trailers["Previous-Production"] == "none"
    entries = {e.path: e for e in store.ls_tree(prod1)}
    assert set(entries) == {"app/main.py", "app/run.sh", "app/tasks.yml", "cfg.ini", "vault/x.yml", PROVENANCE_FILE}
    assert entries["app/run.sh"].mode == "100755"
    assert store.commit_parents(prod1) == []

    drift = drift_check(str(repo), "refs/heads/production", man)
    assert drift["mode"] == "PROVENANCE" and drift["ok"]
    assert drift["checks"]["C_tree_hash"]["ok"] and drift["checks"]["D_trailers"]["ok"]
    assert drift["checks"]["A1_recorded_generator"]["ok"] is None          # generator not committed there
    assert drift["checks"]["A2_migration_preview"]["same_tree"] is True

    # second promotion from a changed source chains onto the first (LF bytes: CRLF is refused by G04)
    (repo / "cfg.ini").write_bytes(b"[defaults]\nforks = 7\n")
    _git(repo, "commit", "-qam", "forks")
    sha2 = _git(repo, "rev-parse", "HEAD")
    res2 = promote(str(repo), sha2, man, dry_run=False, skip_live=True)
    prod2 = store.rev_parse("refs/heads/production")
    assert store.commit_parents(prod2) == [prod1]
    assert GitStore.parse_trailers(store.commit_message(prod2))["Previous-Production"] == prod1

    # restore to the first production tree as a new commit (no rewrite)
    plan = restore(str(repo), prod1, dry_run=True)
    assert plan["ok"] and store.rev_parse("refs/heads/production") == prod2
    done = restore(str(repo), prod1, dry_run=False)
    prod3 = store.rev_parse("refs/heads/production")
    assert done["ok"] and prod3 == done["commit"]
    assert store.commit_tree_sha(prod3) == store.commit_tree_sha(prod1)
    assert store.commit_parents(prod3) == [prod2]


def test_promote_refuses_when_build_has_class_b(repo):
    (repo / "app" / "tasks.yml").write_bytes(b"---\n- set_fact:\n    a: &x 1\n    b: *x\n")
    _git(repo, "commit", "-qam", "anchor")
    res = promote(str(repo), "HEAD", str(repo / "production_manifest.yml"), dry_run=False, skip_live=True)
    assert not res["ok"] and res["stage"] == "build"
    assert not GitStore(str(repo)).rev_exists("refs/heads/production")


def test_drift_legacy_mode_without_provenance(repo):
    _git(repo, "branch", "legacy", "HEAD")
    res = drift_check(str(repo), "legacy", str(repo / "production_manifest.yml"))
    assert res["mode"] == "LEGACY" and res["ok"]
    assert res["checks"]["legacy"]["forbidden_in_production"] == 1       # docs/x.md


def test_restore_refuses_non_prodgen_commit(repo):
    with pytest.raises(Exception):
        restore(str(repo), "HEAD", dry_run=True)
