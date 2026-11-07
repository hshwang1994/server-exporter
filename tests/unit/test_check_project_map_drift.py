"""scripts/ai/check_project_map_drift.py 지문 결정성 (2026-10-28, 독립 검증 F-10).

지문은 git index 경로 목록의 해시다. 종전에는 `git ls-files` 출력을 text 모드 + 실행자의 core.quotepath 로 받아 한글 경로가 있는
디렉터리(tests)의 지문이 quotepath 설정에 따라 갈렸고, quotepath=false 에 cp949 콘솔이면 출력 해석이 실패했다. 임시 저장소에서
(1) quotepath 설정 (2) Python 텍스트 인코딩 모드(-X utf8=0/1)를 바꿔도 지문 · 결과 코드가 같은지, (3) --update 가 index 에 없는
파일을 지문에 넣지 않고 경고만 하는지 본다.
"""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.source_text   # scripts/ai · git index 를 읽는다 — G14 overlay 제외

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ai" / "check_project_map_drift.py"
KO = "tests/한글_경로/보고서.md"


def _load():
    spec = importlib.util.spec_from_file_location("check_project_map_drift", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def _run(repo, utf8_mode, *extra):
    return subprocess.run([sys.executable, "-X", f"utf8={utf8_mode}", str(SCRIPT), "--repo-root", str(repo), *extra],
                          capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    for rel in ("tests/a.py", KO, "schema/x.yml"):
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x\n")
    _git(r, "add", "-A")
    return r


def test_fingerprint_hashes_real_paths_regardless_of_quotepath(repo):
    mod = _load()
    expected = hashlib.sha1("".join(f"{p}\n" for p in sorted(["tests/a.py", KO])).encode("utf-8")).hexdigest()[:12]
    seen = {}
    for qp in ("true", "false"):
        _git(repo, "config", "core.quotepath", qp)
        seen[qp] = mod.fingerprint_dir(repo, "tests")
    assert seen == {"true": expected, "false": expected}


@pytest.mark.parametrize("utf8_mode", ["0", "1"])
def test_update_then_check_is_rc0_under_any_text_encoding(repo, utf8_mode):
    _git(repo, "config", "core.quotepath", "false")      # 종전 코드가 cp949 해석에서 깨지던 조합
    up = _run(repo, utf8_mode, "--update")
    assert up.returncode == 0, (up.stdout, up.stderr)
    chk = _run(repo, utf8_mode)
    assert chk.returncode == 0, (chk.stdout, chk.stderr)
    fp = (repo / ".claude" / "policy" / "project-map-fingerprint.yaml").read_text(encoding="utf-8")
    assert f"tests: {_load().fingerprint_dir(repo, 'tests')}" in fp.splitlines()


def test_update_warns_about_files_missing_from_the_index(repo):
    (repo / "tests" / "not_added.py").write_bytes(b"y\n")
    before = _load().fingerprint_dir(repo, "tests")
    up = _run(repo, "1", "--update")
    assert up.returncode == 0, (up.stdout, up.stderr)
    out = up.stdout.decode("utf-8")
    assert "[WARN] index 에 없는 파일 1개" in out and "tests/not_added.py" in out, out
    assert _load().fingerprint_dir(repo, "tests") == before          # 지문은 index 기준 — 알리기만 하고 넣지 않는다
