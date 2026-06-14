"""data skeleton 3-파일 동기화 가드 (rule 13 R1 / build_*.yml 정합).

배경 (audit 2026-06-09):
    빈 data 뼈대(skeleton)가 세 파일에 **수동 복제**되어 있다 (각 파일 상단 주석이 명시):
      - common/tasks/normalize/init_fragments.yml      (_merged_data)
      - common/tasks/normalize/build_empty_data.yml    (_norm_empty_data)
      - common/tasks/normalize/build_failed_output.yml (data fallback default)
    한 파일만 고치고 나머지를 빠뜨리면 실패 envelope 의 data shape 가 어긋나 Jenkins
    Stage 3 (Validate Schema) FAIL — 운영 중에야 발견된다. 본 테스트는 그 drift 를
    **커밋 전 pytest** 로 잡는다 (사람 주석 의존 → 자동 가드 격상).

검증 가능 (rule 24 R1): 순수 PyYAML 파싱 — ansible-playbook 불필요.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

NORM = Path(__file__).resolve().parents[2] / "common" / "tasks" / "normalize"


def _load_tasks(name):
    with open(NORM / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _set_fact_value(tasks, var):
    """task 목록에서 set_fact 의 <var> 값을 찾아 반환 (정의 위치 무관)."""
    for t in tasks or []:
        sf = t.get("ansible.builtin.set_fact") or t.get("set_fact") or {}
        if var in sf:
            return sf[var]
    raise AssertionError(f"set_fact 에 {var} 없음")


def _key_paths(node, prefix=""):
    """dict 의 모든 키 경로 집합 (중첩 포함). list/scalar 는 leaf."""
    paths = set()
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{prefix}.{k}" if prefix else k
            paths.add(p)
            paths |= _key_paths(v, p)
    return paths


def test_init_and_empty_skeletons_identical():
    """init_fragments._merged_data == build_empty_data._norm_empty_data (구조 동일)."""
    merged = _set_fact_value(_load_tasks("init_fragments.yml"), "_merged_data")
    empty = _set_fact_value(_load_tasks("build_empty_data.yml"), "_norm_empty_data")
    mp, ep = _key_paths(merged), _key_paths(empty)
    assert mp == ep, (
        "init_fragments._merged_data 와 build_empty_data._norm_empty_data 의 data skeleton 불일치.\n"
        f"  init 에만: {sorted(mp - ep)}\n  empty 에만: {sorted(ep - mp)}\n"
        "→ 세 파일 모두 동기화 필요 (각 파일 상단 주석 참조)."
    )


def test_failed_output_fallback_has_all_skeleton_keys():
    """build_failed_output 의 data fallback default 가 skeleton 의 모든 leaf 키를 포함.

    build_failed_output 의 data 는 Jinja2 식 안에 임베드돼 정밀 dict 파싱이 어렵다 →
    canonical skeleton(_merged_data)의 각 키가 raw 텍스트의 default 블록에 등장하는지
    검사(드롭된 섹션/하위키 검출). substring 매칭이라 보수적이지만 drift 의 주된 형태
    (섹션/하위키 누락)는 잡는다.
    """
    merged = _set_fact_value(_load_tasks("init_fragments.yml"), "_merged_data")
    raw = (NORM / "build_failed_output.yml").read_text(encoding="utf-8")
    # data fallback default 블록만 한정 (다른 곳의 우연 매칭 배제).
    anchor = "'data': _merged_data | default({"
    assert anchor in raw, "build_failed_output 의 data fallback default 앵커 변경됨 — 테스트 갱신 필요"
    block = raw[raw.index(anchor):]
    # 모든 leaf 키 이름이 default 블록에 존재해야 함.
    leaf_keys = {p.split(".")[-1] for p in _key_paths(merged)}
    missing = sorted(k for k in leaf_keys if f"'{k}'" not in block and f'"{k}"' not in block)
    assert not missing, (
        f"build_failed_output data fallback 에 skeleton 키 누락: {missing}\n"
        "→ init_fragments / build_empty_data 와 동기화 필요."
    )
