"""Linux users — 명령 부재(not_supported)와 실행 실패(failed + errors 1건)를 가른다 (2026-10-12).

재현한 결함: raw 실행이 어떻게 끝났든 계정 목록이 비면 not_supported 로 분류하고 errors[] 를 남기지 않았다.
연결 끊김 · 셸 오류 · getent 가 결과를 내지 못한 경우가 "지원하지 않는다" 로 가려졐다.

고친 규칙: raw 스크립트가 GETENT=present|absent 표식을 남긴다.
  - 계정 1건 이상 → collected
  - GETENT=absent → not_supported, errors 없음 (종전 F23 규칙은 명령 부재에만 남는다)
  - 그 밖(명령은 있는데 결과 없음 · rc≠0 · 표식 없음) → failed + errors 1건(detail 의 cause 로 no_output / command_failed 구분)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.unit.linux_raw_harness import LINUX_TASKS, assert_user_sentence, iter_tasks, load_tasks, run_task_file  # noqa: E402

USERS_YML = LINUX_TASKS / "gather_users.yml"
USERS_MESSAGE = "사용자 계정 목록 수집에 실패한 항목이 있습니다. 대상 상태와 수집 로그를 확인하세요."


def _register(lines, rc=0):
    return {"rc": rc, "stdout": "\n".join(lines), "stdout_lines": list(lines), "stderr": ""}


def _run(lines, rc=0):
    return run_task_file(USERS_YML, registers={"_l_users_raw_result": _register(lines, rc)}).ctx


def test_raw_script_emits_the_getent_marker():
    raw = next(t for t in iter_tasks(load_tasks(USERS_YML)) if "ansible.builtin.raw" in t)["ansible.builtin.raw"]
    assert 'echo "GETENT=present"' in raw and 'echo "GETENT=absent"' in raw
    assert raw.index("GETENT=") < raw.index("PASSWD_START")


def test_accounts_present_is_collected():
    ctx = _run(["GETENT=present", "PASSWD_START", "root:x:0:0:root:/root:/bin/bash", "PASSWD_END",
                "GROUP_START", "root:x:0:", "GROUP_END", "LASTLOG_START", "root:null", "LASTLOG_END"])
    assert ctx["_sections_collected_fragment"] == ["users"]
    assert ctx["_sections_failed_fragment"] == [] and ctx["_sections_unsupported_fragment"] == []
    assert ctx["_errors_fragment"] == []
    assert ctx["_data_fragment"]["users"][0]["name"] == "root"


def test_getent_absent_is_not_supported_without_error_noise():
    ctx = _run(["GETENT=absent", "PASSWD_START", "PASSWD_END", "GROUP_START", "GROUP_END", "LASTLOG_START", "LASTLOG_END"])
    assert ctx["_sections_unsupported_fragment"] == ["users"]
    assert ctx["_sections_collected_fragment"] == [] and ctx["_sections_failed_fragment"] == []
    assert ctx["_errors_fragment"] == []


def test_getent_present_but_no_output_is_a_failure_with_one_error():
    ctx = _run(["GETENT=present", "PASSWD_START", "PASSWD_END", "GROUP_START", "GROUP_END", "LASTLOG_START", "LASTLOG_END"])
    assert ctx["_sections_failed_fragment"] == ["users"]
    assert ctx["_sections_unsupported_fragment"] == [] and ctx["_sections_collected_fragment"] == []
    errors = ctx["_errors_fragment"]
    assert len(errors) == 1 and errors[0]["section"] == "users" and errors[0]["message"] == USERS_MESSAGE
    assert "cause=no_output" in errors[0]["detail"]
    assert_user_sentence(errors[0]["message"], "users")


def test_raw_command_failure_is_a_failure_not_unsupported():
    """연결이 끊겨 표식도 못 남기고 rc≠0 으로 끝난 경우 — 종전에는 not_supported 였다."""
    ctx = _run(["GETENT=present"], rc=1)
    assert ctx["_sections_failed_fragment"] == ["users"]
    assert ctx["_sections_unsupported_fragment"] == []
    errors = ctx["_errors_fragment"]
    assert len(errors) == 1 and "cause=command_failed" in errors[0]["detail"] and "rc=1" in errors[0]["detail"]
