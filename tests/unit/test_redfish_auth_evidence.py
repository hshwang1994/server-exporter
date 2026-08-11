"""Phase 5-A: redfish_gather 의 구조화 인증 관측(`auth_evidence`).

배경
----
종전에는 인증 실패 여부를 판정할 근거가 `errors[].message` 문자열밖에 없었다
(`_err()` 가 `{'section','message','detail'}` 만 만든다). 문자열 파싱으로 인증 실패를
새로 확정하는 것은 금지돼 있으므로(§18), **이미 보내고 있는 요청의 반환 status** 를
구조화해 module result 로 전달한다.

불변식
  - 새 HTTP 요청을 만들지 않는다 (인증 시도 횟수 = 계정 잠금 위험 불변)
  - 자격증명을 실은 요청(`_get`)의 **첫** status 만 기록한다
  - 무인증 요청(`_get_noauth`)은 기록하지 않는다
  - 값은 urllib 이 준 정수다 (문자열 파싱 아님)
  - 자격증명은 어디에도 남기지 않는다
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

_b = types.ModuleType("ansible.module_utils.basic")
_b.AnsibleModule = object
_m = types.ModuleType("ansible.module_utils")
_m.basic = _b
_a = types.ModuleType("ansible")
_a.module_utils = _m
sys.modules.setdefault("ansible", _a)
sys.modules.setdefault("ansible.module_utils", _m)
sys.modules.setdefault("ansible.module_utils.basic", _b)

import redfish_gather as rg  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    rg._reset_auth_observation()
    yield
    rg._reset_auth_observation()


def test_initial_state_is_unknown():
    assert rg.auth_evidence() == {"first_auth_status": None}


def test_records_first_authenticated_status(monkeypatch):
    calls = []

    def fake_impl(bmc_ip, path, username, password, timeout, verify_ssl):
        calls.append(path)
        return 401, {}, "HTTP 401: Unauthorized"

    monkeypatch.setattr(rg, "_get_impl", fake_impl)
    rg._get("192.0.2.10", "Systems", "u", "p", 5, False)

    assert rg.auth_evidence()["first_auth_status"] == 401
    assert calls == ["Systems"], "관측이 요청을 추가로 만들면 안 된다"


def test_only_first_status_is_kept(monkeypatch):
    seq = iter([401, 200, 500])
    monkeypatch.setattr(
        rg, "_get_impl",
        lambda *_a, **_k: (next(seq), {}, None))

    for _ in range(3):
        rg._get("192.0.2.10", "x", "u", "p", 5, False)

    assert rg.auth_evidence()["first_auth_status"] == 401, "첫 관측을 덮어쓰지 않는다"


def test_transport_failure_status_zero_is_not_recorded(monkeypatch):
    """연결 실패(status=0)는 인증에 대한 관측이 아니다."""
    monkeypatch.setattr(
        rg, "_get_impl",
        lambda *_a, **_k: (0, {}, "URLError: timed out"))
    rg._get("192.0.2.10", "x", "u", "p", 5, False)
    assert rg.auth_evidence()["first_auth_status"] is None


def test_unauthenticated_request_is_not_recorded(monkeypatch):
    """무인증 ServiceRoot(_get_noauth)는 자격증명 판정 근거가 아니다."""
    called = {"n": 0}

    class _Resp:
        status = 401

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_urlopen(*_a, **_k):
        called["n"] += 1
        return _Resp()

    monkeypatch.setattr(rg.urlreq, "urlopen", fake_urlopen)
    rg._get_noauth("192.0.2.10", "", 5, False)

    assert called["n"] == 1
    assert rg.auth_evidence()["first_auth_status"] is None


@pytest.mark.parametrize("status", [200, 403, 404, 500, 503])
def test_non_401_status_recorded_but_not_a_rejection(monkeypatch, status):
    """403 을 포함해 401 이 아닌 status 도 관측은 하되 거부로 해석하지 않는다.

    거부 판정(auth_success=false)은 site.yml 이 `== 401` 로만 한다.
    """
    monkeypatch.setattr(rg, "_get_impl", lambda *_a, **_k: (status, {}, None))
    rg._get("192.0.2.10", "x", "u", "p", 5, False)
    assert rg.auth_evidence()["first_auth_status"] == status
    assert rg.auth_evidence()["first_auth_status"] != 401


def test_evidence_carries_no_credentials(monkeypatch):
    monkeypatch.setattr(rg, "_get_impl", lambda *_a, **_k: (401, {}, None))
    rg._get("192.0.2.10", "Systems", "svc_admin", "Sup3rSecret!", 5, False)
    blob = str(rg.auth_evidence())
    for secret in ("svc_admin", "Sup3rSecret!", "Basic ", "Authorization"):
        assert secret not in blob, "인증 관측값에 자격증명이 섞이면 안 된다"


def test_get_still_returns_impl_result(monkeypatch):
    """관측 래퍼가 반환값을 바꾸면 안 된다 (기존 수집 의미 보존)."""
    monkeypatch.setattr(
        rg, "_get_impl",
        lambda *_a, **_k: (200, {"Members": [{"@odata.id": "/x"}]}, None))
    assert rg._get("192.0.2.10", "Systems", "u", "p", 5, False) == (
        200, {"Members": [{"@odata.id": "/x"}]}, None)


def test_observation_is_reset_per_invocation():
    rg._record_auth_status(401)
    assert rg.auth_evidence()["first_auth_status"] == 401
    rg._reset_auth_observation()
    assert rg.auth_evidence()["first_auth_status"] is None


def test_no_string_parsing_used_for_status():
    """§18 — status 는 정수 관측값이지 메시지 파싱 결과가 아니다."""
    rg._record_auth_status("HTTP 401")     # 문자열은 무시
    assert rg.auth_evidence()["first_auth_status"] is None
    rg._record_auth_status(401)
    assert rg.auth_evidence()["first_auth_status"] == 401
