# -*- coding: utf-8 -*-
"""Fragment 덮어쓰기 / 공통 Task include 경로 회귀 테스트 (2026-08-12).

두 개의 실제 런타임 버그를 고정한다. 둘 다 pytest 로는 안 잡히고 실제
ansible-core 실행에서만 드러났던 유형이라, 코드 구조 자체를 잠근다.

BUG-1  esxi collect_runtime.yml 이 system.runtime dict 전체를 다시 만들면서
       listening_ports 를 [] 로 하드코딩 → normalize_system 이 넣어둔 실제
       수집값이 항상 덮어써졌다.
       실측(ansible-core 2.20.7 + 저장소 merge_fragment.yml):
         STEP1 lp=['22','443','902'] -> STEP2 lp=[]

BUG-2  redfish vendor OEM task 6종이 `{{ playbook_dir }}/common/...` 로 공통
       merge_fragment 를 include → playbook_dir 은 `<repo>/redfish-gather` 라
       그 경로에 common/ 이 없다. 실측: exit=2,
       "Could not find or access '<repo>/redfish-gather/common/tasks/normalize/merge_fragment.yml'"
       → OEM fragment 가 한 번도 병합되지 않았다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

# merge_fragment 는 depth 2 에서 dict 를 통째로 교체한다. 그래서 "runtime 같은
# 하위 dict 를 다시 만드는 fragment" 는 그 dict 의 모든 키를 스스로 책임져야 한다.
ESXI_RUNTIME_OWNERS = [
    REPO / "esxi-gather" / "tasks" / "normalize_system.yml",
    REPO / "esxi-gather" / "tasks" / "collect_runtime.yml",
]


def _runtime_block(path: Path) -> dict:
    """set_fact 의 _data_fragment.system.runtime 블록을 YAML 로 뽑아온다."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for task in doc or []:
        frag = (task.get("ansible.builtin.set_fact") or task.get("set_fact") or {})
        runtime = ((frag.get("_data_fragment") or {}).get("system") or {}).get("runtime")
        if isinstance(runtime, dict):
            return runtime
    return {}


def test_esxi_runtime_writers_agree_on_key_set():
    """system.runtime 을 만드는 모든 task 의 키 집합이 동일해야 한다.

    한 쪽에만 키가 있으면, 나중에 실행되는 쪽이 이겨서 그 키가 사라지거나
    (실측 STEP3 lp=MISSING) 다른 쪽 수집값을 지운다.
    """
    blocks = {p.name: _runtime_block(p) for p in ESXI_RUNTIME_OWNERS}
    for name, blk in blocks.items():
        assert blk, f"{name}: system.runtime 블록을 찾지 못했다"
    key_sets = {name: set(blk) for name, blk in blocks.items()}
    reference = next(iter(key_sets.values()))
    for name, keys in key_sets.items():
        assert keys == reference, (
            f"{name} 의 system.runtime 키 집합이 다르다. "
            f"차이={keys ^ reference} — 나중 fragment 가 앞의 값을 지운다"
        )


def test_esxi_runtime_listening_ports_not_hardcoded_empty():
    """BUG-1 회귀: listening_ports 를 빈 리터럴로 두면 실제 수집값이 사라진다."""
    for path in ESXI_RUNTIME_OWNERS:
        value = _runtime_block(path).get("listening_ports")
        assert value != [], (
            f"{path.name}: listening_ports 가 [] 하드코딩이다. "
            "이 fragment 는 system.runtime 을 통째로 교체하므로 실제 수집값이 덮어써진다"
        )
        assert isinstance(value, str) and "_e_raw_listening_ports" in value, (
            f"{path.name}: listening_ports 는 수집 원본(_e_raw_listening_ports)을 "
            f"이어받아야 한다. 현재값={value!r}"
        )


# ---------------------------------------------------------------------------
# BUG-2 — 공통 Task include 경로
# ---------------------------------------------------------------------------

# playbook_dir 은 실행된 playbook 이 있는 디렉터리(<repo>/<channel>-gather)로
# 해석된다. 저장소 공통 Task 는 항상 REPO_ROOT 기준으로 참조한다.
_BAD_INCLUDE = re.compile(r"\{\{\s*playbook_dir\s*\}\}/common/")


def _yaml_files() -> list[Path]:
    out: list[Path] = []
    for channel in ("os-gather", "esxi-gather", "redfish-gather", "common"):
        out.extend((REPO / channel).rglob("*.yml"))
    return out


def test_no_playbook_dir_reference_to_common_tasks():
    """BUG-2 회귀: playbook_dir 기준으로 common/ 을 include 하면 실행 시 파일이 없다."""
    offenders = [
        f"{p.relative_to(REPO).as_posix()}:{i}"
        for p in _yaml_files()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if _BAD_INCLUDE.search(line)
    ]
    assert not offenders, (
        "playbook_dir 기준 common/ include 발견 — 실행 시 "
        "'Could not find or access' 로 실패한다. "
        "REPO_ROOT 기준으로 통일하라: " + ", ".join(offenders)
    )


@pytest.mark.parametrize("path", sorted(_yaml_files()), ids=lambda p: p.name)
def test_every_include_target_exists_on_disk(path: Path):
    """include_tasks 의 정적 경로(변수 없는 것)는 실제로 존재해야 한다."""
    # 주석 줄은 제외한다 — 벤더 템플릿에 `# - include_tasks: ...` 예시가 들어 있다.
    text = "\n".join(
        l for l in path.read_text(encoding="utf-8").splitlines()
        if not l.lstrip().startswith("#")
    )
    for raw in re.findall(r"include_tasks:\s*(?:file:\s*)?[\"']?([^\"'\n]+)", text):
        target = raw.strip()
        if "{{" in target or not target.endswith((".yml", ".yaml")):
            continue  # 변수 포함 경로는 아래 REPO_ROOT 규칙으로 별도 검증
        assert (path.parent / target).exists(), (
            f"{path.relative_to(REPO).as_posix()}: include 대상 없음 → {target}"
        )


def test_repo_root_includes_resolve():
    """REPO_ROOT 기준 include 경로는 저장소에 실제로 존재해야 한다."""
    pattern = re.compile(
        r"lookup\(\s*['\"]env['\"]\s*,\s*['\"]REPO_ROOT['\"]\s*\)\s*\}\}/([^\"'\s]+)"
    )
    missing = [
        f"{p.relative_to(REPO).as_posix()} -> {rel}"
        for p in _yaml_files()
        for rel in pattern.findall(p.read_text(encoding="utf-8"))
        if "{{" not in rel and not (REPO / rel).exists()
    ]
    assert not missing, "REPO_ROOT 기준 include 대상 없음: " + ", ".join(missing)
