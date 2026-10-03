"""Git object-store access. Never reads the working tree for content.

Reading: ls-tree / cat-file against a SHA or ref. Writing (promote/restore only):
hash-object -w --no-filters, read-tree --empty into a temporary index,
update-index --index-info, write-tree, commit-tree, update-ref.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass

from .common import ProdgenError, to_posix


@dataclass(frozen=True)
class TreeEntry:
    mode: str      # "100644" | "100755" | "120000" | "160000"
    otype: str     # "blob" | "commit"
    sha: str
    path: str      # repo-relative POSIX path


class GitStore:
    def __init__(self, repo_root: str):
        self.repo_root = os.path.abspath(repo_root)
        dot_git = os.path.join(self.repo_root, ".git")
        if not (os.path.isdir(dot_git) or os.path.isfile(dot_git)):
            raise ProdgenError(f"not a git repository: {self.repo_root}")

    # ── low level ────────────────────────────────────────────────────────────
    def run(self, args, *, check=True, input_bytes=None, env=None, text=False):
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        proc = subprocess.run(
            ["git", *args], cwd=self.repo_root, capture_output=True,
            input=input_bytes, env=full_env,
        )
        if check and proc.returncode != 0:
            err = proc.stderr.decode("utf-8", "replace").strip()
            raise ProdgenError(f"git {' '.join(args)} failed (rc={proc.returncode}): {err}")
        if text:
            return proc.stdout.decode("utf-8", "replace")
        return proc.stdout

    # ── reading ──────────────────────────────────────────────────────────────
    def rev_parse(self, rev: str) -> str:
        out = self.run(["rev-parse", "--verify", rev + "^{commit}"], text=True).strip()
        if len(out) != 40:
            raise ProdgenError(f"cannot resolve commit: {rev}")
        return out

    def rev_exists(self, rev: str) -> bool:
        proc = subprocess.run(["git", "rev-parse", "--verify", "-q", rev],
                              cwd=self.repo_root, capture_output=True)
        return proc.returncode == 0

    def commit_tree_sha(self, commit: str) -> str:
        return self.run(["rev-parse", commit + "^{tree}"], text=True).strip()

    def ls_tree(self, treeish: str) -> list:
        """All entries of a commit/tree, recursively (blobs and submodule commits)."""
        raw = self.run(["ls-tree", "-r", "-z", treeish])
        entries = []
        for rec in raw.split(b"\0"):
            if not rec:
                continue
            meta, path = rec.split(b"\t", 1)
            mode, otype, sha = meta.decode("ascii").split(" ")
            entries.append(TreeEntry(mode, otype, sha, to_posix(path.decode("utf-8"))))
        entries.sort(key=lambda e: e.path)
        return entries

    def cat_blob(self, blob_sha: str) -> bytes:
        return self.run(["cat-file", "blob", blob_sha])

    def cat_path(self, treeish: str, path: str):
        proc = subprocess.run(["git", "cat-file", "blob", f"{treeish}:{path}"],
                              cwd=self.repo_root, capture_output=True)
        if proc.returncode != 0:
            return None
        return proc.stdout

    def commit_message(self, commit: str) -> str:
        return self.run(["log", "-1", "--format=%B", commit], text=True)

    def commit_parents(self, commit: str) -> list:
        out = self.run(["log", "-1", "--format=%P", commit], text=True).strip()
        return out.split() if out else []

    @staticmethod
    def parse_trailers(message: str) -> dict:
        """Parse Key: value trailers from the last paragraph of a commit message."""
        paragraphs = [p for p in message.strip().split("\n\n") if p.strip()]
        if not paragraphs:
            return {}
        trailers = {}
        for line in paragraphs[-1].splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                if key and " " not in key:
                    trailers[key] = value.strip()
        return trailers

    # ── writing (promote / restore) ──────────────────────────────────────────
    def isolated_object_env(self, scratch_dir: str) -> dict:
        """Env that redirects object writes to scratch_dir while reading the real store (dry-run)."""
        objects = self.run(["rev-parse", "--git-path", "objects"], text=True).strip()
        if not os.path.isabs(objects):
            objects = os.path.join(self.repo_root, objects)
        return {"GIT_OBJECT_DIRECTORY": os.path.abspath(scratch_dir),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": os.path.abspath(objects)}

    def hash_object(self, data: bytes, write: bool, env=None) -> str:
        args = ["hash-object", "--no-filters", "--stdin"]
        if write:
            args.insert(1, "-w")
        return self.run(args, input_bytes=data, text=True, env=env).strip()

    def build_tree(self, files: list, write: bool, env=None) -> str:
        """files: list of (mode, blob_sha, path). Returns the tree sha.

        Uses a temporary index (GIT_INDEX_FILE) so the real index is never touched.
        With write=False the blobs may not exist; write-tree uses --missing-ok.
        """
        fd, index_path = tempfile.mkstemp(prefix="prodgen-index-")
        os.close(fd)
        os.unlink(index_path)
        env = dict(env or {}, GIT_INDEX_FILE=index_path)
        try:
            self.run(["read-tree", "--empty"], env=env)
            batch = [f"{mode} {sha}\t{path}" for mode, sha, path in sorted(files, key=lambda f: f[2])]
            payload = ("\n".join(batch) + "\n").encode("utf-8")
            self.run(["update-index", "--add", "--index-info"], env=env, input_bytes=payload)
            args = ["write-tree"]
            if not write:
                args.append("--missing-ok")
            return self.run(args, env=env, text=True).strip()
        finally:
            for suffix in ("", ".lock"):
                try:
                    os.unlink(index_path + suffix)
                except OSError:
                    pass

    # Identity used when neither the environment nor git config names one. CI Runners have no user.name/user.email
    # (CI #3 2026-10-04: "Author identity unknown" from commit-tree), and a production commit must not depend on who ran it.
    FALLBACK_IDENTITY = {"GIT_AUTHOR_NAME": "prodgen", "GIT_AUTHOR_EMAIL": "prodgen@clovirone.local",
                         "GIT_COMMITTER_NAME": "prodgen", "GIT_COMMITTER_EMAIL": "prodgen@clovirone.local"}

    def identity_env(self) -> dict:
        """Env vars that make commit-tree succeed: {} when git already knows an identity, FALLBACK_IDENTITY otherwise."""
        if os.environ.get("GIT_AUTHOR_NAME") and os.environ.get("GIT_AUTHOR_EMAIL")                 and os.environ.get("GIT_COMMITTER_NAME") and os.environ.get("GIT_COMMITTER_EMAIL"):
            return {}
        name = self.run(["config", "--get", "user.name"], check=False, text=True).strip()
        email = self.run(["config", "--get", "user.email"], check=False, text=True).strip()
        if name and email:
            return {}
        return dict(self.FALLBACK_IDENTITY)

    def commit_tree(self, tree_sha: str, parents: list, message: str, env_identity=None) -> str:
        args = ["commit-tree", tree_sha]
        for p in parents:
            args += ["-p", p]
        args += ["-m", message]
        env = dict(self.identity_env()) if env_identity is None else dict(env_identity)
        return self.run(args, text=True, env=env or None).strip()

    def update_ref(self, ref: str, new_sha: str, old_sha=None) -> None:
        args = ["update-ref", ref, new_sha]
        if old_sha:
            args.append(old_sha)
        self.run(args)
