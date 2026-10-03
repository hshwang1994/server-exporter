"""GitStore.commit_tree must not depend on who runs it (2026-10-04, CI #3: Runner without user.name/user.email → "Author identity unknown").

The fallback identity is used only when neither the GIT_AUTHOR_*/GIT_COMMITTER_* environment nor git config names one; an explicit
`env_identity` always wins. git config isolation: GIT_CONFIG_GLOBAL → empty file, GIT_CONFIG_NOSYSTEM=1 (git ≥ 2.32).
"""
from __future__ import annotations

import subprocess

import pytest

from scripts.ai.prodgen.gitstore import GitStore

_IDENTITY_VARS = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL")


def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    for v in _IDENTITY_VARS:
        monkeypatch.delenv(v, raising=False)
    empty = tmp_path / "gitconfig.empty"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    store = GitStore(str(repo))
    blob = store.hash_object(b"x\n", write=True)
    tree = store.build_tree([("100644", blob, "x.txt")], write=True)
    return repo, store, tree


def test_fallback_identity_when_git_knows_none(isolated_repo):
    repo, store, tree = isolated_repo
    assert store.identity_env() == GitStore.FALLBACK_IDENTITY
    sha = store.commit_tree(tree, [], "no identity configured\n")
    assert len(sha) == 40
    assert _git(repo, "log", "-1", "--format=%an <%ae>|%cn <%ce>", sha) == "prodgen <prodgen@clovirone.local>|prodgen <prodgen@clovirone.local>"


def test_configured_identity_is_kept(isolated_repo):
    repo, store, tree = isolated_repo
    _git(repo, "config", "user.name", "Site Operator")
    _git(repo, "config", "user.email", "ops@example.invalid")
    assert store.identity_env() == {}
    sha = store.commit_tree(tree, [], "configured identity\n")
    assert _git(repo, "log", "-1", "--format=%an <%ae>", sha) == "Site Operator <ops@example.invalid>"


def test_explicit_env_identity_wins(isolated_repo):
    repo, store, tree = isolated_repo
    ident = {"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.invalid", "GIT_COMMITTER_NAME": "C", "GIT_COMMITTER_EMAIL": "c@example.invalid"}
    sha = store.commit_tree(tree, [], "explicit identity\n", env_identity=ident)
    assert _git(repo, "log", "-1", "--format=%an|%cn", sha) == "A|C"


def test_environment_identity_is_respected(isolated_repo, monkeypatch):
    repo, store, tree = isolated_repo
    for k, v in {"GIT_AUTHOR_NAME": "Env", "GIT_AUTHOR_EMAIL": "env@example.invalid",
                 "GIT_COMMITTER_NAME": "Env", "GIT_COMMITTER_EMAIL": "env@example.invalid"}.items():
        monkeypatch.setenv(k, v)
    assert store.identity_env() == {}
    sha = store.commit_tree(tree, [], "env identity\n")
    assert _git(repo, "log", "-1", "--format=%an", sha) == "Env"
