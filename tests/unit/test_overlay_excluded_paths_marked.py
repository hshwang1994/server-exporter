"""시험 파일이 production_manifest.yml 의 `excluded` 경로(runtime tree 에 없는 운영자 도구)를 이름으로 쓰면 `source_text` 표식이 있어야 한다.

prodgen G14 는 생성된 runtime tree 위에 tests/ 를 얹고 `-m "not source_text"` 로 돈다. 그 tree 에 없는 파일을 읽는 시험이 표식 없이 들어가면
개발 tree 의 Gate 에서는 통과하고 G14 에서만 FileNotFoundError 로 실패한다 — 2026-10-11 CI #44 (`test_bootstrap_vault_encrypt.py`, HC-T7).
여기서는 manifest 의 excluded 항목(`path` 정확 일치 · `glob` 의 고정 접두)을 시험 소스에서 찾고, 찾은 파일에 `pytest.mark.source_text` 가 있는지 본다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "production_manifest.yml"
pytestmark = pytest.mark.source_text   # 저장소 메타(manifest · 시험 소스)를 읽는다 — G14 overlay 제외


def _excluded_patterns() -> list[tuple[str, re.Pattern[str]]]:
    man = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    pats: list[tuple[str, re.Pattern[str]]] = []
    for entry in man.get("excluded") or []:
        if "path" in entry:
            # 경로 토큰 경계: 앞에 경로 문자가 없고(= 다른 디렉터리의 하위가 아님) 뒤에 단어 문자가 없다
            pats.append((entry["path"], re.compile(r"(?<![\w/.\-])" + re.escape(entry["path"]) + r"(?![\w\-])")))
        elif "glob" in entry:
            prefix = entry["glob"].split("*", 1)[0]
            if prefix:
                pats.append((entry["glob"], re.compile(r"(?<![\w/.\-])" + re.escape(prefix))))
    return pats


def test_manifest_has_excluded_entries():
    assert _excluded_patterns(), "production_manifest.yml 에 excluded 항목이 없다 — 이 시험의 전제가 바뀌었다"


def test_tests_naming_excluded_paths_carry_source_text_marker():
    pats = _excluded_patterns()
    me = Path(__file__).resolve()
    unmarked: dict[str, list[str]] = {}
    for f in sorted(REPO.joinpath("tests").rglob("test_*.py")):
        if f.resolve() == me:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        found = sorted({name for name, rx in pats if rx.search(text)})
        if found and "pytest.mark.source_text" not in text:
            unmarked[f.relative_to(REPO).as_posix()] = found
    assert not unmarked, (
        "runtime tree 에 없는(excluded) 경로를 쓰는 시험에 source_text 표식이 없다 — G14 overlay 에서 실패한다: " + repr(unmarked)
    )
