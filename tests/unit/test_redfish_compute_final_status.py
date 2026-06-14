"""Regression for redfish_gather._compute_final_status.

배경 (cycle 2026-04-30): try_one_account.yml의 break 가드는
`status != 'failed'`. 이전 _compute_final_status는 1개 섹션이라도
collected에 들어가면 'partial' 반환 → 첫 자격증명 fail이어도 partial로
emit → loop break → 두 번째 자격증명으로 fallback 안 됨.

본 회귀:
  - errors[]에 'HTTP 401' / 'HTTP 403' 있으면 'failed' 강제
  - 그 외는 기존 동작 유지 (clean=[] failed, failed→partial, 깨끗→success)
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

# ansible stub (Windows dev / import 안전)
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402


def test_no_collected_returns_failed():
    status, clean = rg._compute_final_status([], [], [])
    assert status == 'failed'
    assert clean == []


def test_all_collected_returns_success():
    status, clean = rg._compute_final_status(
        ['system', 'cpu', 'memory'], [], []
    )
    assert status == 'success'
    assert clean == ['system', 'cpu', 'memory']


def test_partial_some_failed():
    status, clean = rg._compute_final_status(
        ['system', 'cpu'], ['memory'], []
    )
    assert status == 'partial'
    assert clean == ['system', 'cpu']


def test_auth_401_in_errors_forces_failed():
    """회귀: 401 자격 실패 흔적 → partial 무효화 → 'failed'.
    Dell vault accounts loop fallback 정상 동작 의존.
    """
    errors = [
        {'section': 'system', 'message': 'GET /Systems 실패',
         'detail': 'HTTP 401: Unauthorized'},
    ]
    # collected에 1개 들어왔지만 errors에 401 → 'failed'
    status, _ = rg._compute_final_status(
        ['system'], [], errors
    )
    assert status == 'failed'


def test_auth_403_in_errors_forces_failed():
    errors = [
        {'section': 'memory', 'message': 'access denied',
         'detail': 'HTTP 403: Forbidden'},
    ]
    status, _ = rg._compute_final_status(
        ['system', 'cpu'], ['memory'], errors
    )
    assert status == 'failed'


def test_non_auth_errors_keep_partial():
    """500/timeout 같은 비인증 에러는 'partial' 유지."""
    errors = [
        {'section': 'storage', 'message': 'timeout',
         'detail': 'Timeout after 30s'},
        {'section': 'network', 'message': 'HTTP 500',
         'detail': 'HTTP 500: Internal Server Error'},
    ]
    status, _ = rg._compute_final_status(
        ['system', 'cpu'], ['storage', 'network'], errors
    )
    assert status == 'partial'


def test_errors_none_default_back_compat():
    """errors=None / 미전달 시 기존 동작 (back-compat)."""
    status, _ = rg._compute_final_status(['system'], [])
    assert status == 'success'
    status, _ = rg._compute_final_status([], ['system'])
    assert status == 'failed'
