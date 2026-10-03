"""redfish_gather.py — 2026-10-03 Phase 3 성능 계약 (P1 detect 모드 · P2 응답 캐시 · deadline · 응답 크기 상한).

무엇을 고정하나
  - P2 캐시: 같은 (username, path) 의 200 dict 응답은 한 호출 안에서 네트워크 1회. hit 는 deep copy(aliasing 금지).
    401/비-dict/디코드 실패는 캐시하지 않음. 다른 username 은 다른 key. 쓰기 뒤 무효화. 꺼져 있으면 종전과 같음.
  - P2 deadline: 남은 시간으로 소켓 timeout 을 줄이고, 다 쓰면 요청을 보내지 않고 `(0, {}, 'Deadline exceeded: request skipped')`
    + notice 1회. 기본 0 = 끔.
  - P2 응답 상한: 본문이 MAX_BODY_BYTES 를 넘으면 status 는 보존하고 body 는 버린다 (err 문자열).
  - P1 detect 모드: ServiceRoot/컬렉션 식별 + System/Manager 각 1 GET 만 — 같은 recording 의 gather 모드보다 요청이 한 자릿수.
"""
from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pytest

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

BMC = "10.0.0.5"
CREDS = ("u", "p", 5, False)


@pytest.fixture(autouse=True)
def _clean_state():
    rg._reset_response_cache(enabled=False)
    rg._set_deadline(0)
    rg._reset_notices()
    yield
    rg._reset_response_cache(enabled=False)
    rg._set_deadline(0)


def _impl(table, calls):
    def impl(bmc_ip, path, username, password, timeout, verify_ssl):
        calls.append((username, path))
        return table.get(path, (404, {}, "HTTP 404: Not Found"))
    return impl


# ───────────────────────────── P2: cache ─────────────────────────────

def test_cache_serves_repeat_reads_with_deep_copies(monkeypatch):
    calls = []
    monkeypatch.setattr(rg, "_get_impl", _impl({"Systems/1": (200, {"Id": "1", "Links": {"Chassis": [{"@odata.id": "/x"}]}}, None)}, calls))
    rg._reset_response_cache(enabled=True)
    st1, d1, e1 = rg._get(BMC, "Systems/1", *CREDS)
    st2, d2, e2 = rg._get(BMC, "Systems/1", *CREDS)
    assert (st1, e1) == (200, None) and d1 == d2 and d1 is not d2
    assert d1["Links"] is not d2["Links"], "deep copy — 중첩 객체도 공유하지 않는다"
    d2["Links"]["Chassis"].append("mutated")
    st3, d3, _ = rg._get(BMC, "Systems/1", *CREDS)
    assert d3["Links"]["Chassis"] == [{"@odata.id": "/x"}], "hit 를 고쳐도 캐시 원본은 바뀌지 않는다"
    assert len(calls) == 1 and rg.cache_stats() == {"hits": 2, "misses": 1, "entries": 1}


def test_cache_is_keyed_by_username_and_skips_non_200_or_non_dict(monkeypatch):
    calls = []
    table = {"Systems": (401, {}, "HTTP 401: Unauthorized"), "Managers": (200, ["not", "dict"], None), "Chassis": (200, {"ok": 1}, None)}
    monkeypatch.setattr(rg, "_get_impl", _impl(table, calls))
    rg._reset_response_cache(enabled=True)
    rg._get(BMC, "Systems", *CREDS); rg._get(BMC, "Systems", *CREDS)
    rg._get(BMC, "Managers", *CREDS); rg._get(BMC, "Managers", *CREDS)
    rg._get(BMC, "Chassis", "u", "p", 5, False); rg._get(BMC, "Chassis", "other", "p", 5, False)
    assert calls.count(("u", "Systems")) == 2, "401 은 캐시하지 않는다"
    assert calls.count(("u", "Managers")) == 2, "비-dict 는 캐시하지 않는다"
    assert calls.count(("u", "Chassis")) == 1 and calls.count(("other", "Chassis")) == 1, "username 이 다르면 다른 key"


def test_cache_disabled_by_default_and_invalidated_on_write(monkeypatch):
    calls = []
    monkeypatch.setattr(rg, "_get_impl", _impl({"Systems/1": (200, {"Id": "1"}, None)}, calls))
    rg._get(BMC, "Systems/1", *CREDS); rg._get(BMC, "Systems/1", *CREDS)
    assert len(calls) == 2, "기본은 꺼짐 — 종전과 같다"
    rg._reset_response_cache(enabled=True)
    rg._get(BMC, "Systems/1", *CREDS); rg._get(BMC, "Systems/1", *CREDS)
    assert len(calls) == 3
    rg._invalidate_response_cache()
    rg._get(BMC, "Systems/1", *CREDS)
    assert len(calls) == 4, "쓰기 뒤 무효화 → 다시 BMC 에서"


def test_write_helpers_invalidate_cache(monkeypatch):
    class _Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(rg.urlreq, "urlopen", lambda req, context=None, timeout=None: _Resp(b"{}"))
    rg._reset_response_cache(enabled=True)
    rg._RESPONSE_CACHE[("u", "Systems")] = (200, {"x": 1}, None)
    rg._post(BMC, "AccountService/Accounts", {"UserName": "a"}, *CREDS)
    assert rg._RESPONSE_CACHE == {}


# ───────────────────────────── P2: deadline ─────────────────────────────

def test_deadline_shrinks_timeout_and_skips_when_exhausted(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(rg.time, "monotonic", lambda: now[0])
    rg._set_deadline(10)
    assert rg._effective_timeout(30) == 10
    now[0] += 7
    assert rg._effective_timeout(30) == 3
    now[0] += 5
    with pytest.raises(rg._DeadlineExceeded):
        rg._effective_timeout(30)
    with pytest.raises(rg._DeadlineExceeded):
        rg._effective_timeout(30)
    assert rg.deadline_exceeded() is True
    assert len([n for n in rg.notices() if "deadline" in n["message"]]) == 1, "notice 는 1회"


def test_requests_are_skipped_without_network_after_deadline(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise AssertionError("deadline 뒤에는 urlopen 을 부르면 안 된다")

    monkeypatch.setattr(rg.urlreq, "urlopen", boom)
    now = [0.0]
    monkeypatch.setattr(rg.time, "monotonic", lambda: now[0])
    rg._set_deadline(1)
    now[0] = 5.0
    assert rg._get_impl(BMC, "Systems", *CREDS) == (0, {}, "Deadline exceeded: request skipped")
    assert rg._get_noauth(BMC, "", 5, False) == (0, {}, "Deadline exceeded: request skipped")
    assert rg._post(BMC, "AccountService/Accounts", {}, *CREDS) == (0, {}, "Deadline exceeded: request skipped")
    assert rg._probe_realm_hint(BMC, 5, False) is None
    assert calls == []


def test_deadline_off_keeps_timeout():
    rg._set_deadline(0)
    assert rg._effective_timeout(30) == 30 and rg._deadline_remaining() is None


# ───────────────────────────── P2: body cap ─────────────────────────────

def test_oversized_body_keeps_status_and_drops_body(monkeypatch):
    class _Resp:
        status = 200

        def __init__(self, size):
            self._buf = io.BytesIO(b"x" * size)

        def read(self, n=-1):
            return self._buf.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(rg.urlreq, "urlopen", lambda req, context=None, timeout=None: _Resp(rg.MAX_BODY_BYTES + 10))
    st, data, err = rg._get_impl(BMC, "UpdateService/FirmwareInventory", *CREDS)
    assert st == 200 and data == {} and "body too large" in err
    monkeypatch.setattr(rg.urlreq, "urlopen", lambda req, context=None, timeout=None: _Resp(10))
    st, data, err = rg._get_impl(BMC, "x", *CREDS)
    assert st == 200 and "body not JSON" in err, "상한 안의 비-JSON 은 종전 동작"


# ───────────────────────────── P1: detect mode ─────────────────────────────

class _Exit(Exception):
    def __init__(self, payload):
        super().__init__("exit")
        self.payload = payload


def _fake_module(params):
    class _M:
        def __init__(self, argument_spec=None, supports_check_mode=False):
            self.params = dict(params)
            self.check_mode = False
            for k, spec in (argument_spec or {}).items():
                self.params.setdefault(k, spec.get("default"))

        def exit_json(self, **kw):
            raise _Exit(kw)

        def fail_json(self, **kw):
            raise AssertionError(kw)
    return _M


R740 = REPO / "tests" / "fixtures" / "redfish" / "real_dell_r740"


@pytest.mark.skipif(not (R740 / "recording.json").is_file(), reason="real_dell_r740 fixture 없음")
def test_detect_mode_uses_an_order_of_magnitude_fewer_requests_than_gather(monkeypatch):
    rec = json.loads((R740 / "recording.json").read_text(encoding="utf-8"))
    get_table = {k[len("get::"):]: tuple(v) for k, v in rec.items() if k.startswith("get::")}
    noauth_table = {k[len("noauth::"):]: tuple(v) for k, v in rec.items() if k.startswith("noauth::")}
    calls = []
    monkeypatch.setattr(rg, "_get_impl", _impl(get_table, calls))
    monkeypatch.setattr(rg, "_get_noauth", lambda bmc_ip, path, timeout, verify_ssl: (calls.append(("noauth", path)) or noauth_table.get(path, (404, {}, "HTTP 404"))))
    monkeypatch.setattr(rg, "_probe_realm_hint", lambda *a, **k: rec.get("realm::") or None)

    def run(mode):
        calls.clear()
        monkeypatch.setattr(rg, "AnsibleModule", _fake_module({"bmc_ip": BMC, "username": "u", "password": "p", "mode": mode}))
        with pytest.raises(_Exit) as ei:
            rg.main()
        return ei.value.payload, len(calls)

    detect, n_detect = run("detect")
    gather, n_gather = run("gather")
    assert detect["mode"] == "detect" and detect["vendor"] == gather["vendor"] == "dell"
    assert detect["data"]["system"]["model"] and detect["data"]["bmc"]["firmware_version"]
    assert set(detect) >= {"vendor", "data", "probe_facts", "errors", "notices", "auth_evidence", "status"}
    assert n_detect <= 10 < n_gather, f"detect {n_detect} vs gather {n_gather}"


def test_gather_mode_result_exposes_cache_stats_and_deadline_flag(monkeypatch):
    rec = json.loads((R740 / "recording.json").read_text(encoding="utf-8")) if (R740 / "recording.json").is_file() else None
    if rec is None:
        pytest.skip("fixture 없음")
    get_table = {k[len("get::"):]: tuple(v) for k, v in rec.items() if k.startswith("get::")}
    noauth_table = {k[len("noauth::"):]: tuple(v) for k, v in rec.items() if k.startswith("noauth::")}
    monkeypatch.setattr(rg, "_get_impl", _impl(get_table, []))
    monkeypatch.setattr(rg, "_get_noauth", lambda bmc_ip, path, timeout, verify_ssl: noauth_table.get(path, (404, {}, "HTTP 404")))
    monkeypatch.setattr(rg, "_probe_realm_hint", lambda *a, **k: None)
    monkeypatch.setattr(rg, "AnsibleModule", _fake_module({"bmc_ip": BMC, "username": "u", "password": "p"}))
    with pytest.raises(_Exit) as ei:
        rg.main()
    out = ei.value.payload
    assert out["deadline_exceeded"] is False
    assert out["cache"]["hits"] >= 1 and out["cache"]["misses"] >= 1, "R740 도 Systems/System.Embedded.1 재조회 1건이 hit 로 바뀐다"
