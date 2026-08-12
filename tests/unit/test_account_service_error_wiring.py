"""Redfish 표준 관리 계정 처리 실패가 결과에 남는지 (C3 / N49 / N71) — 2026-08-12 신설.

배경
----
`redfish-gather/tasks/account_service.yml` 에는 `errors` 라는 문자열이 **0건**이었다.
모듈(`redfish_gather.py`)은 25개 지점에서 `result['errors']` 에 사유를 채워 돌려주는데
(중복 슬롯 / 계정 잠금 / 계정 비활성 / PATCH 실패 / password sync 후 재인증 실패 /
DELETE+POST 재생성 실패 / 빈 슬롯 없음 / AccountService 미지원 …), 태스크가 meta 8키만 읽고
나머지를 전부 버렸다. 결과: 표준 계정 복구가 왜 안 됐는지 Portal 에 **0건**.

**계정 잠금은 재시도할수록 악화되는데** 사용자는 "자격증명과 계정 권한을 확인하세요" 만
안내받아 재시도를 반복하게 됐다.

본 테스트가 고정하는 것
-----------------------
1. 실패 판정이 dryrun / 성공 retry 를 실패로 세지 않는다.
2. 사용자 문장에 Slot URI / HTTP status / 내부 slot id / 영문 vendor enum 이 없다.
3. 모듈 원문이 detail 로 보존되고, account_service 항목만 취해 vendor_detect 중복을 만들지 않는다.
4. fragment 를 만든 뒤 반드시 merge_fragment 를 호출한다 (rule 22 R3 — 호출 누락 시 조용히 사라짐).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.e2e.test_failure_reason_contract import (
    _assert_grid_ready,
    _env,
    _iter_tasks,
)

REPO = Path(__file__).resolve().parents[2]
TASKS = list(yaml.safe_load_all(
    (REPO / "redfish-gather/tasks/account_service.yml").read_text(encoding="utf-8")))[0]
SECTION_MESSAGES: dict[str, Any] = yaml.safe_load(
    (REPO / "common/vars/section_messages.yml").read_text(encoding="utf-8"))


def _set_fact(key, needs_str=True):
    for task in _iter_tasks(TASKS):
        sf = task.get("ansible.builtin.set_fact") or {}
        if key in sf:
            value = sf[key]
            if needs_str and not isinstance(value, str):
                continue
            return value
    raise AssertionError(f"account_service.yml 에서 {key} 를 찾지 못함")


def _error_entry():
    """조건부 message 를 가진 `_errors_fragment` 원소 (실패 보고용)."""
    for task in _iter_tasks(TASKS):
        frag = (task.get("ansible.builtin.set_fact") or {}).get("_errors_fragment")
        if isinstance(frag, list) and frag and "{%" in str(frag[0].get("message", "")):
            return frag[0]
    raise AssertionError("account_service.yml 에서 조건부 error fragment 를 찾지 못함")


_FAILED_TPL = _set_fact("_rf_acct_failed")
_ENTRY = _error_entry()


def _failed(meta) -> bool:
    return bool(_env().from_string(_FAILED_TPL).render(_rf_account_service_meta=meta))


def _message(meta) -> str:
    return _env().from_string(_ENTRY["message"]).render(
        _rf_account_service_meta=meta, **SECTION_MESSAGES)


def _detail(errors) -> Any:
    return _env().from_string(_ENTRY["detail"]).render(
        _rf_acct_result={"account_service": {"errors": errors}})


def _meta(**kw):
    base = {"attempted": True, "recovered": False, "method": "noop", "action": "none",
            "account_existed": False, "verification": "none", "dryrun": False,
            "slot_uri": None, "vendor": "dell"}
    base.update(kw)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# 실패 판정 — 성공과 시뮬레이션을 실패로 세지 않는다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("meta,expected,why", [
    (_meta(recovered=True, verification="verified", action="password_sync"), False,
     "복구 성공 + 재인증 확인"),
    (_meta(recovered=True, verification="none", action="create"), False,
     "복구 성공 (verify 대상 아님)"),
    (_meta(dryrun=True, verification="skipped"), False,
     "dryrun 은 의도적으로 아무것도 고치지 않는다 — 실패가 아니다"),
    (_meta(dryrun=True, recovered=True, verification="skipped"), False, "dryrun"),
    (_meta(action="ambiguous", method="ambiguous"), True, "중복 슬롯으로 자동 처리 중단"),
    (_meta(method="not_supported"), True, "AccountService 미지원"),
    (_meta(verification="failed", action="create", method="post_new"), True, "재인증 실패"),
    (_meta(recovered=True, verification="failed"), True, "복구했다지만 확인 실패"),
])
def test_failure_judgment(meta, expected, why):
    assert _failed(meta) is expected, f"{why}: {meta}"


def test_dryrun_never_reports_failure():
    """2026-08-11 lab 실측(Dell 10.100.15.28)이 정확히 이 상태였다 — 거짓 오류 방지."""
    for verification in ("skipped", "none", "failed"):
        assert _failed(_meta(dryrun=True, verification=verification)) is False, verification


# ═══════════════════════════════════════════════════════════════════════════
# 사용자 문장 품질
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("meta,label", [
    (_meta(action="ambiguous", method="ambiguous"), "ambiguous"),
    (_meta(method="not_supported"), "not_supported"),
    (_meta(verification="failed"), "generic"),
])
def test_message_is_grid_ready(meta, label):
    message = _message(meta)
    _assert_grid_ready(message, f"account_service/{label}")
    for banned in ("slot", "Slot", "/redfish/", "HTTP", "Administrator",
                   "PATCH", "POST", "DELETE", "iDRAC", "CIMC", "vault"):
        assert banned not in message, f"[{label}] 내부 어휘 {banned!r}: {message!r}"


def test_message_branches_are_distinct():
    """원인별로 실제로 다른 문장이 나온다 (3분기가 무의미해지지 않게)."""
    seen = {
        _message(_meta(action="ambiguous", method="ambiguous")),
        _message(_meta(method="not_supported")),
        _message(_meta(verification="failed")),
    }
    assert len(seen) == 3


# ═══════════════════════════════════════════════════════════════════════════
# detail — 모듈 원문 보존 + vendor_detect 중복 제거
# ═══════════════════════════════════════════════════════════════════════════
_MODULE_ERRORS = [
    {"section": "vendor_detect", "message": "ServiceRoot 실패: timeout"},
    {"section": "account_service", "message": "대상 계정이 잠금 상태입니다. 비밀번호 불일치가 아니라 계정 잠금이 원인일 수 있습니다.",
     "detail": "slot=3 Locked=true"},
    {"section": "account_service", "message": "PATCH 기존 사용자 실패 (slot=3)", "detail": "HTTP 400"},
]


def test_detail_preserves_module_evidence():
    detail = _detail(_MODULE_ERRORS)
    assert isinstance(detail, str) and detail.strip()
    assert "계정 잠금" in detail
    assert "slot=3 Locked=true" in detail
    assert "HTTP 400" in detail


def test_detail_excludes_vendor_detect_duplicates():
    """모듈이 앞에 붙이는 vendor_detect errors 는 본 수집 경로와 중복이라 제외한다 (NEW-3)."""
    assert "ServiceRoot 실패" not in _detail(_MODULE_ERRORS)


def test_detail_is_null_when_module_gave_nothing():
    assert _detail([]) is None


def test_detail_is_capped():
    many = [{"section": "account_service", "message": "가" * 200, "detail": "나" * 200}
            for _ in range(20)]
    assert len(_detail(many)) <= 1000


# ═══════════════════════════════════════════════════════════════════════════
# rule 22 R3 — fragment 를 만들면 반드시 merge_fragment 를 부른다
# ═══════════════════════════════════════════════════════════════════════════
def test_every_error_fragment_is_followed_by_merge():
    """호출을 빠뜨리면 다음 태스크가 fragment 를 덮어써 **조용히 사라진다**."""
    flat = list(_iter_tasks(TASKS))
    frag_idx = [i for i, t in enumerate(flat)
                if (t.get("ansible.builtin.set_fact") or {}).get("_errors_fragment")]
    assert frag_idx, "error fragment 를 만드는 태스크가 없다"
    for i in frag_idx:
        tail = flat[i + 1:i + 4]
        merged = any("merge_fragment.yml" in str(t.get("ansible.builtin.include_tasks", ""))
                     for t in tail)
        assert merged, (
            f"{flat[i].get('name')!r} 직후에 merge_fragment 호출이 없다 — errors 가 사라진다"
        )


def test_standard_account_username_is_not_hardcoded():
    """표준 계정은 vault profile 의 role=primary 이지 특정 username 문자열이 아니다 (CLAUDE.md §8)."""
    source = (REPO / "redfish-gather/tasks/account_service.yml").read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "infraops" not in line, f"표준 계정 username 하드코딩: {line!r}"
