"""8차 R3 · R4 (2026-10-05): Redfish 모듈의 요청 시간 — 모듈 호출 마감과 진행 표시를 없애고, 연결 수립과 응답 대기를 나눴다.

종전에는 모듈 호출 전체에 절대 마감(1200 s, detect 90 s · 계정 180 s)과 '새 응답 없이' 마감(120 s)이 있었고, 그 진행 판정이
JSON 해석보다 먼저 일어나 잘못된 HTML 200 응답도 진행으로 셌다(Astra 로컬 재현). 정상적으로 오래 걸리는 수집을 진행과 무관하게 잘랐다.
지금은 요청마다 연결 수립(CONNECT_TIMEOUT_SEC 60)과 응답 읽기 대기(모듈 timeout — 운영값 _rf_timeout 1800)만 있다.
배치 전체는 수집 실행 한계(최대 6시간, scripts/run_gather.sh)와 사용자 취소가 멈춘다.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
import yaml

from tests.unit.test_redfish_phase3_contracts import rg  # noqa: E402 - ansible 대역을 포함한 모듈 적재 재사용

REPO = Path(__file__).resolve().parents[2]
MODULE_TEXT = (REPO / "redfish-gather" / "library" / "redfish_gather.py").read_text(encoding="utf-8")


def test_module_deadline_and_progress_machinery_is_gone():
    for name in ("_set_deadline", "_DeadlineExceeded", "_effective_timeout", "_mark_progress", "_set_heartbeat", "deadline_kind",
                 "deadline_exceeded", "HEARTBEAT_EVERY_SEC"):
        assert not hasattr(rg, name), name
    for text in ("idle_deadline", "progress_dir", "deadline        = dict(", "Deadline exceeded"):
        assert text not in MODULE_TEXT, text


def test_yaml_no_longer_passes_deadlines_and_waits_for_slow_responses():
    site = yaml.safe_load((REPO / "redfish-gather" / "site.yml").read_text(encoding="utf-8"))
    play_vars = site[0]["vars"]
    assert play_vars["_rf_timeout"] == 1800, "느린 BMC 의 정상 응답을 기다린다(읽기 한 번마다의 대기)"
    for gone in ("_rf_deadline", "_rf_idle_deadline", "_rf_task_timeout", "_rf_detect_deadline", "_rf_account_deadline"):
        assert gone not in play_vars, gone
    for rel in ("collect_standard.yml", "try_one_account.yml", "detect_vendor.yml", "account_service_try_one.yml"):
        text = (REPO / "redfish-gather" / "tasks" / rel).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(deadline|idle_deadline|progress_dir):", text, re.M), rel
        assert not re.search(r"^\s*timeout:\s*\"\{\{ _rf_\w*task_timeout", text, re.M), f"{rel}: task 단위 제한이 없다"
        assert '"{{ _rf_timeout' in text, f"{rel}: 응답 대기는 _rf_timeout 하나"


def test_connection_uses_the_connect_limit_and_reads_use_the_response_wait(monkeypatch):
    """연결(TCP + TLS) 단계에는 CONNECT_TIMEOUT_SEC, 연결 뒤 소켓에는 호출자의 응답 대기를 건다 — 네트워크 없이 확인한다."""
    seen = {}

    class FakeSock:
        def settimeout(self, v):
            seen.setdefault("settimeout", []).append(v)

        def setsockopt(self, *a):
            pass

        def close(self):
            pass

    def fake_create_connection(addr, timeout=None, source_address=None, *a, **kw):
        seen["connect_timeout"] = timeout
        return FakeSock()

    class FakeContext:
        check_hostname = False

        def wrap_socket(self, sock, server_hostname=None):
            seen["handshake_timeout_at_wrap"] = seen.get("connect_timeout")
            return sock

    monkeypatch.setattr(rg.http_client.socket, "create_connection", fake_create_connection)
    conn = rg._SplitTimeoutHTTPSConnection("192.0.2.1", 443, timeout=1800, context=FakeContext())
    conn.connect()
    assert seen["connect_timeout"] == rg.CONNECT_TIMEOUT_SEC == 60
    assert seen["settimeout"][-1] == 1800, "연결 뒤 읽기는 응답 대기 값"
    assert conn.timeout == 1800, "연결 객체의 timeout 은 원래 값으로 돌려 놓는다"
    conn2 = rg._SplitTimeoutHTTPSConnection("192.0.2.1", 443, timeout=20, context=FakeContext())
    conn2.connect()
    assert seen["connect_timeout"] == 20, "응답 대기가 연결 상한보다 짧으면 그 값을 그대로 쓴다"


def test_operational_opener_uses_the_split_handler(monkeypatch):
    monkeypatch.setattr(rg, "_OPENERS", {})
    built = {}
    real_build = rg.urlreq.build_opener

    def spy(*handlers):
        built["handlers"] = handlers
        return real_build(*handlers)

    monkeypatch.setattr(rg.urlreq, "build_opener", spy)
    monkeypatch.setattr(rg.urlreq, "urlopen", rg._STDLIB_URLOPEN)

    class StopHere(Exception):
        pass

    def fake_open(self, req, data=None, timeout=None):
        built["timeout"] = timeout
        raise StopHere()

    monkeypatch.setattr(rg.urlreq.OpenerDirector, "open", fake_open)
    with pytest.raises(StopHere):
        rg._urlopen(rg.urlreq.Request("https://192.0.2.1/redfish/v1/"), False, 1800)
    kinds = [type(h).__name__ for h in built["handlers"]]
    assert "_SplitTimeoutHTTPSHandler" in kinds and "_SameOriginRedirect" in kinds
    assert built["timeout"] == 1800


def test_html_200_is_still_an_error_and_counts_as_nothing(monkeypatch):
    """R4: HTTP 200 + HTML 본문은 'body not JSON' 오류다. 진행 표시가 없어져 이 응답이 무언가를 늘리지도 않는다."""

    class Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(rg.urlreq, "urlopen", lambda req, context=None, timeout=None: Resp(b"<html><head id='j_idt2'></head></html>"))
    status, data, err = rg._get_impl("192.0.2.1", "Systems", "u", "p", 1800, False)
    assert status == 200 and data == {} and err == "HTTP 200: body not JSON"
