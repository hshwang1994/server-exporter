"""scripts/bootstrap_vault_encrypt.sh — 현재 vault 배치(전역 standard + <loc>/{os,esxi,redfish})를 재귀로 찾고, 0건이면 실패한다 (2026-10-11).

종전 스크립트는 삭제된 flat 경로 8개만 보고 모두 "파일 없음" 으로 건너뛴 뒤 성공을 보고했다 — 운영자 문서(01-jenkins-master 7절)가 안내하는 첫 암호화가
실제로는 아무것도 하지 않았다. 여기서는 가짜 `ansible-vault`(PATH 앞)로 호출 인자만 기록해 어떤 파일을 암호화하려 했는지 본다.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "bootstrap_vault_encrypt.sh"
BASH = shutil.which("bash")
# source_text: 이 스크립트는 운영자 도구라 production_manifest.yml 이 runtime tree 에서 제외한다(excluded) — prodgen G14 overlay 에는 없으므로
# 거기서는 돌지 않는다(CI #44 2026-10-11 에서 FileNotFoundError 로 확인). 개발 tree(ci_gate · 로컬)에서만 실행한다.
pytestmark = [pytest.mark.source_text, pytest.mark.skipif(BASH is None, reason="bash 가 없다")]


def _fake_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "bootstrap_vault_encrypt.sh")
    (root / ".vault_pass").write_text("x\n", encoding="utf-8")
    os.chmod(root / ".vault_pass", 0o600)
    for rel, body in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    av = fake_bin / "ansible-vault"
    av.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\" >> \"$FAKE_AV_LOG\"\n", encoding="utf-8")
    av.chmod(av.stat().st_mode | stat.S_IEXEC)
    return root


def _run(root: Path, tmp_path: Path):
    log = tmp_path / "av.log"
    env = {**os.environ, "PATH": str(tmp_path / "bin") + os.pathsep + os.environ.get("PATH", ""), "FAKE_AV_LOG": str(log), "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([BASH, str(root / "scripts" / "bootstrap_vault_encrypt.sh")], cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    calls = log.read_text(encoding="utf-8").split("\n") if log.exists() else []
    return r, calls


def test_recurses_current_layout_and_skips_encrypted_and_lab_file(tmp_path):
    root = _fake_repo(tmp_path, {
        "vault/common/redfish/standard.yml": "accounts: []\n",
        "vault/git/os/linux.yml": "accounts: []\n",
        "vault/git/redfish/dell.yml": "$ANSIBLE_VAULT;1.1;AES256\n6162\n",
        "vault/.lab-credentials.yml": "plain: true\n",
        "vault/README.md": "# vault\n",
    })
    r, calls = _run(root, tmp_path)
    assert r.returncode == 0, r.stderr
    encrypted = [c for c in calls if c.endswith(".yml")]
    assert sorted(Path(c).as_posix().split("/vault/", 1)[1] for c in encrypted) == ["common/redfish/standard.yml", "git/os/linux.yml"]
    assert "이미 암호화" in r.stdout and "git/redfish/dell.yml" in r.stdout


def test_zero_vault_files_is_an_error(tmp_path):
    root = _fake_repo(tmp_path, {"vault/README.md": "# vault\n"})
    r, calls = _run(root, tmp_path)
    assert r.returncode == 1 and "암호화할" in r.stderr and not calls
