"""Redfish 상태 판정 — 인증을 통과한 뒤의 하위 리소스 403 은 섹션 실패(partial)다 (2026-10-12).

재현한 결함: `_compute_final_status` 가 어느 섹션 오류든 'HTTP 403' 문자열이 있으면 host 전체를 failed 로 돌렸다.
try_one_account.yml 은 status=failed 를 보고 데이터를 승격하지 않고(첫 인증 응답이 401 이 아니라 다음 후보도 시도하지 않음),
site.yml 이 수집 실패로 중단해 **이미 수집한 모든 섹션을 버렸다**. 사용자 문장은 "인증은 성공했지만 정보를 가져오지 못했습니다" 였다.

고친 규칙:
  - 자격을 실은 첫 응답(auth_evidence.first_auth_status)이 2xx 면 인증은 통과한 것 → 하위 리소스 403 은 그 섹션만 failed (host 는 partial)
  - 401 은 세션 만료 · 잠금처럼 인증이 뒤집힌 신호 → 종전대로 failed
  - first_auth_status 가 없거나 2xx 가 아니면 종전 문자열 규칙(401/403 → failed) 그대로 (자격 순서 사고 방지 규칙 보존)
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

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

FORBIDDEN_STORAGE = {"section": "storage", "message": "Storage 컬렉션 실패: HTTP 403: Forbidden",
                     "detail": "HTTP 403: Forbidden"}
UNAUTHORIZED_BMC = {"section": "bmc", "message": "BMC 수집 실패", "detail": "HTTP 401: Unauthorized"}


def test_403_after_authenticated_first_response_is_partial_not_failed():
    """재현: 첫 인증 200 + storage 403 → 종전 failed(데이터 폐기) → 이제 partial(수집한 섹션 유지)."""
    status, clean = rg._compute_final_status(["system", "cpu", "memory", "storage"], ["storage"],
                                              [FORBIDDEN_STORAGE], first_auth_status=200)
    assert status == "partial"
    assert clean == ["system", "cpu", "memory"]


def test_403_without_structured_auth_evidence_keeps_legacy_failed():
    """first_auth_status 가 없으면(옛 호출자 · 모듈 밖) 종전 규칙 — 자격 순서 사고 방지 규칙은 그대로다."""
    status, _ = rg._compute_final_status(["system", "cpu"], ["storage"], [FORBIDDEN_STORAGE])
    assert status == "failed"
    status, _ = rg._compute_final_status(["system", "cpu"], ["storage"], [FORBIDDEN_STORAGE], first_auth_status=None)
    assert status == "failed"


def test_403_when_first_response_was_not_2xx_keeps_failed():
    for first in (401, 403, 500):
        status, _ = rg._compute_final_status(["system"], ["storage"], [FORBIDDEN_STORAGE], first_auth_status=first)
        assert status == "failed", first


def test_401_anywhere_still_forces_failed_even_after_authenticated_first_response():
    status, _ = rg._compute_final_status(["system", "cpu"], ["bmc"], [UNAUTHORIZED_BMC], first_auth_status=200)
    assert status == "failed"


def test_main_passes_first_auth_status_to_the_final_status():
    """main() 은 구조화된 첫 인증 응답을 넘긴다 — 문자열 규칙만으로 판정하는 옛 호출로 되돌아가지 않는다."""
    import inspect
    src = inspect.getsource(rg.main)
    assert "first_auth_status=auth_evidence().get('first_auth_status')" in src
