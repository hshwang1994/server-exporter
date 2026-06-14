"""Regression for redfish_gather 404 → unsupported 분류 (cycle 2026-05-01).

배경: 일부 vendor/펌웨어가 특정 endpoint(power/network_adapters 등) 자체 미응답 (HTTP 404).
이전엔 errors[]에 'failed'로 분류되어 호출자 noise. cycle 2026-05-01 부터 404-only
errs를 unsupported list로 분리해 errors[]에서 제외 + envelope sections.{name}='not_supported'.

본 테스트:
  - _is_404_only_error() 분류 정확도
  - _make_section_runner() with unsupported list 분리 동작
  - back-compat: unsupported 인자 미전달 시 기존 동작
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


def test_is_404_only_error_detail_pattern():
    """detail에 'HTTP 404' 들어간 errors → True."""
    errs = [{'section': 'power', 'message': 'Power 정보 실패: HTTP 404',
             'detail': 'HTTP 404: Not Found'}]
    assert rg._is_404_only_error(errs) is True


def test_is_404_only_error_message_pattern():
    """message가 ': 404' 로 끝나는 errors → True (st int 그대로 emit 케이스)."""
    errs = [{'section': 'power', 'message': 'Power 정보 실패: 404',
             'detail': None}]
    assert rg._is_404_only_error(errs) is True


def test_is_404_only_error_mixed_returns_false():
    """404 + 5xx 혼재 → False (진짜 fail 포함)."""
    errs = [
        {'section': 'power', 'message': 'HTTP 404', 'detail': 'HTTP 404: Not Found'},
        {'section': 'power', 'message': 'PSU URI 실패', 'detail': 'HTTP 500: Internal Server Error'},
    ]
    assert rg._is_404_only_error(errs) is False


def test_is_404_only_error_empty_returns_false():
    """빈 errors → False (success 흔적 — unsupported 아님)."""
    assert rg._is_404_only_error([]) is False


def test_is_404_only_error_401_returns_false():
    """401 인증 fail은 unsupported 아님."""
    errs = [{'section': 'system', 'message': 'auth fail',
             'detail': 'HTTP 401: Unauthorized'}]
    assert rg._is_404_only_error(errs) is False


def test_make_section_runner_404_routes_to_unsupported():
    """404 only → unsupported list, errors[] 제외, failed 제외."""
    all_errors, collected, failed, unsupported = [], [], [], []
    _run = rg._make_section_runner(all_errors, collected, failed, unsupported)

    def fake_gather():
        return {}, [{'section': 'power', 'message': 'Power 정보 실패: HTTP 404',
                     'detail': 'HTTP 404: Not Found'}]

    val = _run('power', fake_gather)
    assert unsupported == ['power']
    assert all_errors == []      # noise 차단
    assert 'power' not in failed
    assert 'power' not in collected


def test_make_section_runner_500_routes_to_failed():
    """500 → 기존 동작 (errors[] + failed)."""
    all_errors, collected, failed, unsupported = [], [], [], []
    _run = rg._make_section_runner(all_errors, collected, failed, unsupported)

    def fake_gather():
        return {}, [{'section': 'power', 'message': 'fail',
                     'detail': 'HTTP 500: Internal Server Error'}]

    _run('power', fake_gather)
    assert unsupported == []
    assert len(all_errors) == 1
    assert 'power' in failed
    assert 'power' in collected


def test_make_section_runner_back_compat_no_unsupported():
    """unsupported 인자 미전달 시 기존 동작 (모두 failed/errors)."""
    all_errors, collected, failed = [], [], []
    _run = rg._make_section_runner(all_errors, collected, failed)  # unsupported 없음

    def fake_gather():
        return {}, [{'section': 'power', 'message': 'HTTP 404',
                     'detail': 'HTTP 404: Not Found'}]

    _run('power', fake_gather)
    # back-compat: 404도 errors / failed 로 분류
    assert len(all_errors) == 1
    assert 'power' in failed


def test_make_section_runner_success_unchanged():
    """errors 비어있고 val 있는 정상 케이스 — collected만."""
    all_errors, collected, failed, unsupported = [], [], [], []
    _run = rg._make_section_runner(all_errors, collected, failed, unsupported)

    def fake_gather():
        return {'foo': 'bar'}, []

    val = _run('storage', fake_gather)
    assert val == {'foo': 'bar'}
    assert collected == ['storage']
    assert failed == []
    assert unsupported == []
    assert all_errors == []
