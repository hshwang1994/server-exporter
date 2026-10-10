"""별도 sudo(become) 비밀번호가 로그인 비밀번호로 덮이던 기존 결함 (2026-10-10 C10).

기존 결함(NEXT_ACTIONS · vault-credential-resolver §6.4 에 기록돼 있던 것): Vault loader 는 별도 `ansible_become_password` 를
`_cred_become_password` 로 읽지만, 후보를 적용하는 set_fact 가 `ansible_become_pass` 를 언제나 로그인 비밀번호로 다시 설정했다
(set_fact 가 play var 보다 우선) — 별도 sudo 비밀번호가 무시됐다.
수정: Linux 는 별도 become 값이 비어 있지 않으면 그 값(trim 없음), 없거나 비었으면 지금 고른 로그인 후보의 비밀번호. Windows 는 종전 그대로.
로그인 비밀번호와 sudo 비밀번호가 다른 것은 정상 구성이다. 이 시험은 정적 렌더다 — 다른 sudo 암호를 쓰는 실서버 실행이 아니다.
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
TRY = REPO / "os-gather" / "tasks" / "try_one_credential.yml"
SYSTEM = REPO / "os-gather" / "tasks" / "linux" / "gather_system.yml"


def _apply_task():
    doc = yaml.safe_load(TRY.read_text(encoding="utf-8"))
    for t in doc[0]["block"]:
        if t.get("name") == "os | try_one_credential | apply candidate to hostvars":
            return t
    raise AssertionError("apply task not found")


def _become(ctx):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return env.from_string(_apply_task()["ansible.builtin.set_fact"]["ansible_become_pass"]).render(**ctx)


PRIMARY = {"username": "infraops", "password": "login-pw-1", "label": "primary", "role": "primary"}
SECOND = {"username": "fallback", "password": "login-pw-2", "label": "secondary", "role": "secondary"}


@pytest.mark.parametrize("become,cand,expected", [
    ("sudo-pw", PRIMARY, "sudo-pw"),                  # 별도 sudo 비밀번호가 우선
    (" sudo pw ", PRIMARY, " sudo pw "),              # 값을 다듬지 않는다
    ("", PRIMARY, "login-pw-1"),                      # 빈 값 → 로그인 후보 비밀번호
    (None, PRIMARY, "login-pw-1"),                    # null → 로그인 후보 비밀번호
    ("sudo-pw", SECOND, "sudo-pw"),                   # 다음 로그인 후보로 넘어가도 별도 값이 우선
    ("", SECOND, "login-pw-2"),                       # 별도 값이 없으면 지금 고른 후보의 비밀번호
    (0, PRIMARY, "0"),                                # 따옴표 없는 숫자 값도 비어 있지 않은 값이다
])
def test_linux_become_password_prefers_a_separate_vault_value(become, cand, expected):
    assert _become({"_os_type": "linux", "_cred_become_password": become, "_try_cred": cand}) == expected


def test_linux_become_password_when_the_vault_has_no_separate_value():
    assert _become({"_os_type": "linux", "_try_cred": PRIMARY}) == "login-pw-1", "키가 없으면 로그인 후보 비밀번호(종전과 같다)"


@pytest.mark.parametrize("become", ["", "sudo-pw"])
def test_root_login_and_passwordless_sudo_paths_do_not_break(become):
    """root 로그인 · NOPASSWD sudo: sudo 는 비밀번호를 묻지 않으므로 어느 값이 넘어가도 동작이 바뀌지 않는다 — 값만 확인한다."""
    root = {"username": "root", "password": "root-pw", "label": "root", "role": "primary"}
    want = become or "root-pw"
    assert _become({"_os_type": "linux", "_cred_become_password": become, "_try_cred": root}) == want


def test_windows_keeps_the_login_password():
    assert _become({"_os_type": "windows", "_cred_become_password": "sudo-pw", "_try_cred": PRIMARY}) == "login-pw-1"


def test_candidate_task_keeps_no_log_and_login_fields():
    task = _apply_task()
    assert task.get("no_log") is True
    sf = task["ansible.builtin.set_fact"]
    assert sf["ansible_user"] == "{{ _try_cred.username | default('') }}"
    assert sf["ansible_password"] == "{{ _try_cred.password | default('') }}"


def test_dmi_reads_still_use_become():
    """DMI 공유 수집 · 직접 읽기는 그대로 become 으로 돈다(이 수정은 값만 바꾼다)."""
    tasks = yaml.safe_load(SYSTEM.read_text(encoding="utf-8"))

    def walk(node):
        if isinstance(node, list):
            for x in node:
                yield from walk(x)
        elif isinstance(node, dict):
            yield node
            for k in ("block", "rescue", "always"):
                if k in node:
                    yield from walk(node[k])

    become_tasks = [t.get("name") for t in walk(tasks) if t.get("become") is True]
    assert len(become_tasks) >= 2, become_tasks
