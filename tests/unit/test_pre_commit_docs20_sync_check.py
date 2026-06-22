"""rule 13 R7 — pre_commit_docs20_sync_check hook 회귀.

본 회귀는 ``scripts/ai/hooks/pre_commit_docs20_sync_check.py`` 의 검출 로직
(``detect_violation``) 을 직접 검증한다. git index 모킹은 하지 않고 함수 단위 시험.

reference:
    - rule 13 R7 (envelope 정본 변경 시 docs/20 동기화 의무)
    - scripts/ai/hooks/pre_commit_docs20_sync_check.py (자체 ``--self-test`` 도 동일 케이스 보유)
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK_PATH = REPO / "scripts" / "ai" / "hooks" / "pre_commit_docs20_sync_check.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location(
        "pre_commit_docs20_sync_check", HOOK_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def hook_mod():
    return _load_hook_module()


def test_canonical_files_constant(hook_mod) -> None:
    """rule 13 R7 정본 4종이 정확히 등록됐는지 확인."""
    expected = {
        "common/tasks/normalize/build_output.yml",
        "common/tasks/normalize/build_status.yml",
        "schema/sections.yml",
        "schema/field_dictionary.yml",
    }
    assert set(hook_mod.CANONICAL_FILES) == expected
    assert hook_mod.DOCS20_PATH == "docs/20_json-schema-fields.md"


def test_canonical_files_actually_exist(hook_mod) -> None:
    """정본 4종 + docs/20 이 저장소에 실재하는지 (rule 13 R7 정합성)."""
    for f in hook_mod.CANONICAL_FILES:
        assert (REPO / f).is_file(), f"정본 파일 부재: {f}"
    assert (REPO / hook_mod.DOCS20_PATH).is_file()


def test_violation_canonical_only(hook_mod) -> None:
    """정본 1개만 변경 + docs/20 미변경 → 위반 1건."""
    violations = hook_mod.detect_violation(
        ["common/tasks/normalize/build_output.yml"]
    )
    assert violations == ["common/tasks/normalize/build_output.yml"]


def test_pass_when_docs20_also_staged(hook_mod) -> None:
    """정본 + docs/20 동반 staged → 통과."""
    violations = hook_mod.detect_violation(
        [
            "schema/sections.yml",
            "schema/field_dictionary.yml",
            "docs/20_json-schema-fields.md",
        ]
    )
    assert violations == []


def test_pass_when_only_non_canonical(hook_mod) -> None:
    """정본 외 파일만 변경 → 통과."""
    violations = hook_mod.detect_violation(
        ["adapters/redfish/dell_idrac9.yml", "tests/unit/test_foo.py"]
    )
    assert violations == []


def test_pass_when_empty(hook_mod) -> None:
    """staged 비어있음 → 통과."""
    assert hook_mod.detect_violation([]) == []


def test_windows_path_normalization(hook_mod) -> None:
    """Windows backslash path 도 정규화 후 매칭."""
    violations = hook_mod.detect_violation(
        [r"common\tasks\normalize\build_status.yml"]
    )
    assert violations == ["common/tasks/normalize/build_status.yml"]


def test_violation_all_four_canonical(hook_mod) -> None:
    """정본 4종 모두 변경 + docs/20 미변경 → 위반 4건."""
    staged = list(hook_mod.CANONICAL_FILES)
    violations = hook_mod.detect_violation(staged)
    assert sorted(violations) == sorted(hook_mod.CANONICAL_FILES)


def test_skip_env_var_returns_zero(hook_mod, monkeypatch) -> None:
    """DOCS20_SYNC_SKIP=1 시 main() 0 반환 (advisory)."""
    monkeypatch.setenv("DOCS20_SYNC_SKIP", "1")
    monkeypatch.setattr(sys, "argv", ["pre_commit_docs20_sync_check.py"])
    assert hook_mod.main() == 0


def test_skip_cosmetic_env_returns_zero(hook_mod, monkeypatch) -> None:
    """DOCS20_SYNC_SKIP_COSMETIC=1 시 main() 0 반환 (rule 13 R7 Allowed)."""
    monkeypatch.delenv("DOCS20_SYNC_SKIP", raising=False)
    monkeypatch.setenv("DOCS20_SYNC_SKIP_COSMETIC", "1")
    monkeypatch.setattr(sys, "argv", ["pre_commit_docs20_sync_check.py"])
    assert hook_mod.main() == 0


def test_self_test_subprocess_passes() -> None:
    """``--self-test`` 6 케이스 전체 PASS (exit 0)."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH), "--self-test"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env=env,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, (
        f"self-test FAIL: stdout={result.stdout} stderr={result.stderr}"
    )
    assert "FAIL" not in result.stdout, result.stdout
    assert result.stdout.count("PASS") == 6
