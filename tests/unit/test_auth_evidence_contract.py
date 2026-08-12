# -*- coding: utf-8 -*-
"""인증 근거(Authentication Evidence) 계약 테스트 (2026-08-12).

os-gather 의 rescue diagnosis 는 `_all_sec_collected | length > 0` 을
"원격 인증이 통과했다"는 근거로 함께 본다 (os-gather/site.yml 의 C6 주석).

그 판단이 성립하려면 **섹션이 collected 로 표시되는 유일한 경로가 원격 실행 성공**
이어야 한다. 아래 세 경로 중 하나라도 생기면 근거가 무너지고, envelope 이
"인증 성공"이라고 말하면서 실제로는 대상에 접속조차 못 한 상태가 된다.

  1. controller-side (delegate_to: localhost) task 가 collected 를 채움
  2. precheck 단계 task 가 collected 를 채움
  3. _data_fragment 가 비었는데 collected 를 채움

세 경로 모두 현재 0건이며, 본 테스트가 그 상태를 고정한다.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
LOCAL_DELEGATES = {"localhost", "127.0.0.1"}
EMPTY = (None, {}, "{}", [], "[]")


def _collected_setters(path: Path):
    """(task 이름, controller-side 여부, data_fragment 값) 목록."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError:
        return []
    found: list[tuple[str, bool, object]] = []

    def walk(tasks, delegated: bool = False):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            here = delegated or str(task.get("delegate_to", "")).strip() in LOCAL_DELEGATES
            for key in ("block", "rescue", "always"):
                if isinstance(task.get(key), list):
                    walk(task[key], here)
            sf = task.get("ansible.builtin.set_fact") or task.get("set_fact") or {}
            if not isinstance(sf, dict):
                continue
            if sf.get("_sections_collected_fragment") in EMPTY:
                continue
            found.append((task.get("name", "?"), here, sf.get("_data_fragment")))

    walk(doc)
    return found


def _os_task_files() -> list[Path]:
    return sorted((REPO / "os-gather" / "tasks").rglob("*.yml"))


def test_collected_never_set_from_controller_side():
    """경로 1: delegate_to localhost 인 task 는 원격 인증을 증명하지 못한다."""
    bad = [
        f"{p.relative_to(REPO).as_posix()} :: {name}"
        for p in _os_task_files()
        for name, delegated, _ in _collected_setters(p)
        if delegated
    ]
    assert not bad, (
        "controller 에서 실행되는 task 가 섹션을 collected 로 표시한다 — "
        "os-gather/site.yml 의 auth_success 판정 근거가 무너진다: " + ", ".join(bad)
    )


def test_collected_never_set_with_empty_data_fragment():
    """경로 3: 데이터가 없는데 collected 로 표시하면 수집 성공의 근거가 없다."""
    bad = [
        f"{p.relative_to(REPO).as_posix()} :: {name}"
        for p in _os_task_files()
        for name, _, frag in _collected_setters(p)
        if frag in EMPTY
    ]
    assert not bad, (
        "_data_fragment 가 비었는데 collected 로 표시하는 task: " + ", ".join(bad)
    )


def test_precheck_tasks_never_produce_collected_sections():
    """경로 2: precheck 는 인증 전 단계라 collected 를 만들면 안 된다."""
    bad = [
        p.relative_to(REPO).as_posix()
        for p in (REPO / "common" / "tasks").rglob("*.yml")
        if "precheck" in p.name.lower()
        and "_sections_collected_fragment" in p.read_text(encoding="utf-8")
    ]
    assert not bad, "precheck 단계가 collected 섹션을 만든다: " + ", ".join(bad)


def test_os_rescue_uses_collected_sections_as_auth_evidence():
    """근거 표현식 자체가 사라지지 않았는지 — 사라지면 C6 모순이 재발한다.

    (자격 후보 0건이면 _os_auth_ok 는 false 로 남는데, 그 상태로도 수집은
     성공할 수 있다. 그때 envelope 이 '대상에 접속할 수 없습니다' 라고 말하면
     data 에 수집 결과가 들어 있는 채로 자기모순이 된다.)
    """
    text = (REPO / "os-gather" / "site.yml").read_text(encoding="utf-8")
    occurrences = text.count("_all_sec_collected | default([]) | length) > 0")
    assert occurrences >= 2, (
        f"rescue diagnosis 의 인증 근거 표현식이 {occurrences}곳뿐이다 "
        "(linux/windows 두 PLAY 모두 필요)"
    )
