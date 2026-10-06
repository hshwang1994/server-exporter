"""쓰기 응답 유실 — 같은 쓰기를 다시 보내지 않고, 다시 읽고 다시 인증해 판정한다 (2026-10-06, 9차 · 지시서 §3 · 시험 14).

무엇을 고정하나
  - 쓰기 요청을 보낸 뒤 응답을 받지 못했다(시간 초과 · 연결 끊김 · 잘린 응답 — HTTP 상태 없음). 반영됐는지 모른다.
    · 같은 쓰기 · 다른 payload · 다른 슬롯 · 삭제 후 재생성 어느 것도 다시 보내지 않는다(쓰기 1건).
    · 계정을 다시 읽고(생성이면 그 슬롯 · 목록) 표준 자격으로 다시 인증해 반영됐으면 recovered=verified, 아니면 실패로 남긴다.
    · 확정되지 않은 상태에서 슬롯을 비우는 되돌리기 PATCH 를 보내지 않는다.
  - http.client.HTTPException(잘린 응답 · 상태 줄 오류)은 예외로 모듈을 끝내지 않고 응답 유실(status 0)로 돌아온다.
    종전에는 모듈이 결과 없이 끝나 다음 복구 후보가 같은 쓰기를 다시 보낼 수 있었다.
  - 생성 뒤 인증 확인이 **확정적으로** 실패했을 때(표준 자격 401)만 만든 슬롯을 비운다. 시간 초과 · 5xx · 403 이면 비우지 않는다.
실장비 쓰기 검증이 아니다 — 모의(monkeypatch) 검증이다.
"""
from __future__ import annotations

import http.client
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
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
from tests.unit.account_seam import as_discovery  # noqa: E402

TARGET = "infraops"
LOST = (0, {}, "Response lost: IncompleteRead: IncompleteRead(10 bytes read)")


def _account(**kw):
    base = {"slot_uri": "/redfish/v1/AccountService/Accounts/3", "id": "3", "username": TARGET, "role_id": "Administrator",
            "enabled": True, "locked": None, "account_types": None, "password_change_required": None, "odata_type": "",
            "has_username_key": True}
    base.update(kw)
    return base


def _empty_slot(n):
    return _account(slot_uri=f"/redfish/v1/AccountService/Accounts/{n}", id=str(n), username="", enabled=False, role_id="None")


def _provision(vendor, **kw):
    return rg.account_service_provision("10.0.0.1", vendor, "rec", "<rec>", TARGET, "<tgt>", "Administrator", 5, False,
                                        dryrun=False, **kw)


class Calls:
    def __init__(self):
        self.writes = []

    def record(self, method):
        def _fn(bmc_ip, path, *a, **k):
            self.writes.append((method, path))
            return self.answers[method].pop(0) if isinstance(self.answers.get(method), list) else self.answers[method]
        return _fn


def _wire(monkeypatch, accounts, answers, verify_code=200, slot_get=None, rediscover=None):
    calls = Calls()
    calls.answers = answers
    discover_calls = []

    def discover(*a, **k):
        discover_calls.append(k)
        if rediscover is not None and len(discover_calls) > 1:
            return rediscover(*a, **k)
        return as_discovery(lambda *x, **y: ({}, list(accounts), []), rg)(*a, **k)

    def fake_get(bmc_ip, path, u, p, t, v, *a, **k):
        if path == "Systems":
            return (verify_code, {}, None if verify_code == 200 else f"HTTP {verify_code}")
        if slot_get is not None:
            return slot_get(path)
        return (200, {"UserName": TARGET, "Enabled": True, "RoleId": "Administrator"}, None)

    monkeypatch.setattr(rg, "account_service_discover", discover)
    monkeypatch.setattr(rg, "_patch", calls.record("PATCH"))
    monkeypatch.setattr(rg, "_post", calls.record("POST"))
    monkeypatch.setattr(rg, "_delete", calls.record("DELETE"))
    monkeypatch.setattr(rg, "_get", fake_get)
    monkeypatch.setattr(rg, "_get_response_etag", lambda *a, **k: None)
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)
    return calls, discover_calls


def test_lost_response_is_recognised_only_without_an_http_status():
    assert rg._write_outcome_unknown(*LOST[::2])
    assert rg._write_outcome_unknown(0, "Timeout after 30s") and rg._write_outcome_unknown(None, "URLError: x")
    for code, err in ((200, None), (204, None), (400, "HTTP 400: Bad Request"), (500, "HTTP 500"), (0, None)):
        assert not rg._write_outcome_unknown(code, err), (code, err)


@pytest.mark.parametrize("exc", [http.client.IncompleteRead(b"partial"), http.client.BadStatusLine("garbage"),
                                 http.client.RemoteDisconnected("closed")])
@pytest.mark.parametrize("helper", ["_post", "_patch", "_delete"])
def test_write_helpers_turn_a_broken_response_into_a_lost_response(monkeypatch, helper, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(rg, "_urlopen", boom)
    fn = getattr(rg, helper)
    args = ("10.0.0.1", "AccountService/Accounts/3") + (({"Password": "x"},) if helper != "_delete" else ()) + ("u", "p", 5, False)
    code, data, err = fn(*args)
    assert code == 0 and data == {} and err.startswith("Response lost: "), (code, err)


def test_existing_account_patch_lost_is_verified_without_writing_again(monkeypatch):
    calls, _ = _wire(monkeypatch, [_account(), _empty_slot(4)], {"PATCH": LOST}, verify_code=200)
    out = _provision("dell")
    assert [w[0] for w in calls.writes] == ["PATCH"], "응답을 잃은 PATCH 를 다시 보내지 않는다"
    assert out["recovered"] is True and out["verification"] == "verified" and out["write_response_lost"] is True
    assert out["write_accepted"] is None and out["vendor_status"] == "response_lost"


def test_existing_account_patch_lost_and_not_confirmed_fails_without_any_other_write(monkeypatch):
    calls, _ = _wire(monkeypatch, [_account()], {"PATCH": LOST}, verify_code=401)
    out = _provision("lenovo", allow_delete_recreate=True)
    assert [w[0] for w in calls.writes] == ["PATCH"], "삭제 후 재생성 · 다른 payload 로 넘어가지 않는다"
    assert out["recovered"] is False and out["verification"] == "failed"
    assert any("응답을 받지 못했고" in e["message"] for e in out["errors"])


def test_post_create_lost_is_located_by_re_enumeration_then_verified(monkeypatch):
    created = _account(slot_uri="/redfish/v1/AccountService/Accounts/7", id="7")

    def rediscover(*a, **k):
        return as_discovery(lambda *x, **y: ({}, [created], []), rg)(*a, **k)

    calls, discovers = _wire(monkeypatch, [], {"POST": LOST}, verify_code=200, rediscover=rediscover)
    out = _provision("supermicro")
    assert [w[0] for w in calls.writes] == ["POST"] and len(discovers) == 2
    assert out["recovered"] is True and out["slot_uri"] == "/redfish/v1/AccountService/Accounts/7"


@pytest.mark.parametrize("found,enumeration,needle", [
    ([], "complete", "표준 계정이 없습니다"),
    ([_account(id="7"), _account(id="8")], "complete", "여러 개"),
    ([], "incomplete", "끝까지 다시 읽지 못했습니다"),
])
def test_post_create_lost_and_not_found_is_never_posted_again(monkeypatch, found, enumeration, needle):
    def rediscover(*a, **k):
        d = as_discovery(lambda *x, **y: ({}, list(found), []), rg)(*a, **k)
        d["enumeration"] = enumeration
        return d

    calls, _ = _wire(monkeypatch, [], {"POST": LOST}, verify_code=200, rediscover=rediscover)
    out = _provision("supermicro")
    assert [w[0] for w in calls.writes] == ["POST"], "생성 요청을 다시 보내지 않는다"
    assert out["recovered"] is False and out["verification"] == "failed"
    assert any(needle in e["message"] for e in out["errors"]), out["errors"]


def test_empty_slot_create_lost_and_not_applied_sends_no_cleanup(monkeypatch):
    def slot_get(path):
        return (200, {"UserName": "", "Enabled": False}, None)       # 다시 읽은 슬롯은 그대로 비어 있다

    calls, _ = _wire(monkeypatch, [_empty_slot(3), _empty_slot(4)], {"PATCH": LOST}, verify_code=401, slot_get=slot_get)
    out = _provision("dell")
    assert [w[0] for w in calls.writes] == ["PATCH"], "다른 슬롯에 다시 쓰지 않고, 비우는 PATCH 도 보내지 않는다"
    assert out["verification"] == "failed" and out["recovered"] is False
    assert any("반영되지 않은 것으로 봅니다" in e["message"] for e in out["errors"])


def test_empty_slot_create_lost_but_applied_is_verified(monkeypatch):
    calls, _ = _wire(monkeypatch, [_empty_slot(3)], {"PATCH": LOST}, verify_code=200)
    out = _provision("dell")
    assert [w[0] for w in calls.writes] == ["PATCH"]
    assert out["recovered"] is True and out["verification"] == "verified"


@pytest.mark.parametrize("verify_code,cleanup", [(401, True), (0, False), (503, False), (403, False)])
def test_slot_cleanup_only_after_a_definitive_rejection(monkeypatch, verify_code, cleanup):
    """생성 PATCH 는 수락됐는데 표준 자격으로 인증되지 않는다 — 401 일 때만 만든 슬롯을 비운다."""
    calls, _ = _wire(monkeypatch, [_empty_slot(3)], {"PATCH": [(200, {}, None), (200, {}, None)]}, verify_code=verify_code)
    out = _provision("dell")
    patches = [w for w in calls.writes if w[0] == "PATCH"]
    assert len(patches) == (2 if cleanup else 1), calls.writes
    assert out["recovered"] is False and out["verification"] == "failed"
    if not cleanup:
        assert any("인증 확인이 확정되지 않아 만든 슬롯을 비우지 않았습니다" in e["message"] for e in out["errors"])


def test_lost_delete_stops_before_recreating(monkeypatch):
    """opt-in 삭제 후 재생성 경로 — 삭제 응답을 잃으면 다시 만들지 않는다."""
    calls, _ = _wire(monkeypatch, [_account()], {"PATCH": (200, {}, None), "DELETE": LOST}, verify_code=401)
    out = _provision("lenovo", allow_delete_recreate=True)
    assert [w[0] for w in calls.writes] == ["PATCH", "DELETE"], calls.writes
    assert out["write_response_lost"] is True and any("삭제 요청의 응답을 받지 못해" in e["message"] for e in out["errors"])


def test_recovery_candidates_do_not_follow_a_lost_or_failed_attempt():
    """yml — 복구 후보는 앞 후보가 401 로 명시 거부됐을 때만 다음으로 넘어간다(결과 없이 끝난 모듈 = 거부 아님)."""
    one = (REPO / "redfish-gather" / "tasks" / "account_service_try_one.yml").read_text(encoding="utf-8")
    svc = (REPO / "redfish-gather" / "tasks" / "account_service.yml").read_text(encoding="utf-8")
    assert "_rf_acct_attempt_rejected: >-" in one and ".auth_rejected | default(false)) | bool" in one
    assert "- not (_rf_acct_attempt_rejected | bool)" in one and "_rf_acct_stopped: true" in one
    assert "- not (_rf_acct_stopped | default(false) | bool)" in svc and "_rf_acct_stopped: false" in svc
    backoff = one[one.index("backoff on recovery auth failure"):]
    assert "- _rf_acct_attempt_rejected | bool" in backoff and "_rf_transport_backoff_seconds" not in backoff
