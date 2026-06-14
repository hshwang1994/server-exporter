"""Regression for F23 — OS gather users 'not_supported' 점진 전환 (cycle 2026-05-01).

배경: Alpine / distroless / busybox / Server Core lockdown 등 환경에서 getent
또는 Get-LocalUser 명령 자체 부재. 이전 동작은 _sections_failed_fragment 로
분류 → errors[] noise. cycle 2026-05-01 부터 진짜 미지원 케이스를 명시적으로
'not_supported' 분류 (root 항상 존재 / win32 user 항상 존재 가정으로 빈
결과 = 진짜 미지원 신호).

본 테스트는 Linux/Windows users gather YAML 의 Jinja2 fragment 분류 로직을
Python 으로 mirror 해서 4 케이스 검증:
  - Linux Python mode: getent_passwd empty → unsupported
  - Linux Raw mode: _l_raw_passwd empty → unsupported
  - Windows: stdout empty + rc != 0 → unsupported
  - 정상 케이스 (각각): supported / collected
"""
from __future__ import annotations


def linux_python_classify(getent_passwd: dict | None) -> dict:
    """Mirror gather_users.yml Python mode build fragment 로직.

    return {'collected': list, 'failed': list, 'unsupported': list}
    """
    has = bool(getent_passwd)
    return {
        'collected': ['users'] if has else [],
        'failed': [],
        'unsupported': [] if has else ['users'],
    }


def linux_raw_classify(raw_passwd: dict | None) -> dict:
    """Mirror gather_users.yml Raw mode build fragment 로직."""
    raw_passwd = raw_passwd or {}
    has = len(raw_passwd) > 0
    return {
        'collected': ['users'] if has else [],
        'failed': [],
        'unsupported': [] if has else ['users'],
    }


def windows_classify(norm_users: list, raw_rc: int) -> dict:
    """Mirror windows/gather_users.yml build fragment 로직."""
    norm_users = norm_users or []
    has_users = len(norm_users) > 0
    rc_ok = (raw_rc == 0)
    collected = ['users'] if (has_users or rc_ok) else []
    unsupported = ['users'] if (not has_users and not rc_ok) else []
    return {
        'collected': collected,
        'failed': [],
        'unsupported': unsupported,
    }


# ── Linux Python mode ───────────────────────────────────────────────────────
def test_linux_python_normal_passwd_collected():
    """getent_passwd 정상 → collected=['users'], unsupported=[]."""
    res = linux_python_classify({'root': ('root', '0', '0', '', '/root', '/bin/bash')})
    assert res['collected'] == ['users']
    assert res['unsupported'] == []
    assert res['failed'] == []


def test_linux_python_empty_passwd_unsupported():
    """getent_passwd empty (busybox / distroless) → unsupported=['users']."""
    res = linux_python_classify({})
    assert res['collected'] == []
    assert res['unsupported'] == ['users']
    assert res['failed'] == []  # F23: failed 가 아닌 unsupported


def test_linux_python_undefined_passwd_unsupported():
    """getent_passwd undefined (모듈 자체 fail) → unsupported."""
    res = linux_python_classify(None)
    assert res['unsupported'] == ['users']
    assert res['failed'] == []


# ── Linux Raw mode ──────────────────────────────────────────────────────────
def test_linux_raw_normal_collected():
    """raw_passwd 정상 → collected."""
    res = linux_raw_classify({
        'root': ['root', '0', '0', 'root', '/root', '/bin/bash'],
    })
    assert res['collected'] == ['users']
    assert res['unsupported'] == []


def test_linux_raw_empty_unsupported():
    """raw_passwd empty (getent: command not found) → unsupported."""
    res = linux_raw_classify({})
    assert res['collected'] == []
    assert res['unsupported'] == ['users']
    assert res['failed'] == []


# ── Windows ─────────────────────────────────────────────────────────────────
def test_windows_normal_collected():
    """정상 — admin user 존재 + rc=0 → collected."""
    res = windows_classify([{'name': 'Administrator', 'uid': 'S-1-5-..'}], raw_rc=0)
    assert res['collected'] == ['users']
    assert res['unsupported'] == []


def test_windows_empty_users_rc_zero_collected():
    """rc=0 인데 list 비어있음 (모두 system filter 통과 못함) → collected (정상 0명)."""
    # 정책: rc=0 이면 명령은 동작 — 진짜 0명 (rare). collected 유지.
    res = windows_classify([], raw_rc=0)
    assert res['collected'] == ['users']
    assert res['unsupported'] == []


def test_windows_empty_users_rc_nonzero_unsupported():
    """rc != 0 + list empty (Get-LocalUser / Win32_UserAccount 둘 다 미지원) → unsupported."""
    res = windows_classify([], raw_rc=1)
    assert res['collected'] == []
    assert res['unsupported'] == ['users']
    assert res['failed'] == []


def test_windows_users_present_rc_nonzero_collected():
    """list 있으면 rc 무관 collected (raw 명령은 fail 했지만 일부 출력 파싱 성공 케이스)."""
    res = windows_classify([{'name': 'admin'}], raw_rc=1)
    assert res['collected'] == ['users']
    assert res['unsupported'] == []
