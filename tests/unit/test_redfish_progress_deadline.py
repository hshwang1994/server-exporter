"""F12 (2026-10-05): Redfish 모듈의 진행 기반 마감 — 새 응답이 계속 오면 수집을 이어가고, 응답이 끊기면 멈춘다.

종전에는 `deadline`(540 s)이 진행과 상관없이 모듈 호출 전체를 잘랐다. 지금은 절대 상한(`deadline`, 운영값 1200)과 함께 '새 응답(2xx)
없이 지난 시간' 상한(`idle_deadline`, 운영값 120)을 둔다. 시간은 축소한 가짜 시계로 확인한다 (실제 소켓 · 실제 대기 없음).
heartbeat 는 정체 감시(scripts/gather_watch.py)가 한 태스크 안의 긴 수집을 진행으로 보게 하는 파일이다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.test_redfish_phase3_contracts import rg  # noqa: E402 - ansible 대역을 포함한 모듈 적재 재사용

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def clock(monkeypatch):
    c = {"t": 1000.0}
    monkeypatch.setattr(rg.time, "monotonic", lambda: c["t"])
    rg._reset_notices()
    yield c
    rg._set_deadline(0, 0)
    rg._set_heartbeat("", "")
    rg._reset_response_cache(enabled=False)


def test_idle_limit_trims_the_socket_timeout_then_stops(clock):
    rg._set_deadline(1200, 120)
    clock["t"] += 100
    assert rg._effective_timeout(30) == 20, "남은 idle 20 s 로 소켓 timeout 을 줄인다"
    clock["t"] += 21
    with pytest.raises(rg._DeadlineExceeded):
        rg._effective_timeout(30)
    assert rg.deadline_exceeded() and rg.deadline_kind() == "idle"
    assert any("새 응답 없이 120s" in n["message"] for n in rg.notices())


def test_new_responses_reset_the_idle_clock(clock):
    rg._set_deadline(1200, 120)
    for _ in range(10):
        clock["t"] += 100
        rg._mark_progress()
        assert rg._effective_timeout(30) == 30
    assert clock["t"] - 1000 == 1000 and not rg.deadline_exceeded(), "응답이 이어지면 종전 540 s 를 훨씬 넘어서도 계속한다"


def test_absolute_cap_still_applies_with_steady_progress(clock):
    rg._set_deadline(1200, 120)
    clock["t"] += 1199
    rg._mark_progress()
    assert rg._effective_timeout(30) == 1, "절대 상한까지 남은 1 s"
    clock["t"] += 2
    with pytest.raises(rg._DeadlineExceeded):
        rg._effective_timeout(30)
    assert rg.deadline_kind() == "absolute"


def _fake_impl(monkeypatch, clock, seconds, ok=True):
    """실제 _get_impl 처럼 요청 전에 기한을 확인하고(넘었으면 보내지 않는다), 요청 하나에 seconds 를 쓴다."""
    def impl(bmc, path, user, pw, timeout, verify):
        try:
            rg._effective_timeout(timeout)
        except rg._DeadlineExceeded as e:
            return 0, {}, str(e)
        clock["t"] += seconds
        if ok:
            rg._mark_progress()
            return 200, {"@odata.id": path}, None
        return 0, {}, "Timeout after %ss" % seconds
    monkeypatch.setattr(rg, "_get_impl", impl)


def _collect(n):
    sent = 0
    for i in range(n):
        st, _, err = rg._get("192.0.2.1", f"Systems/{i}", "u", "p", 30, False)
        if err and "Deadline exceeded" in err:
            break
        sent += 1
    return sent


def test_scaled_slow_but_steady_bmc_is_collected_past_the_old_deadline(monkeypatch, clock):
    """축소 시험: 페이지당 5 s, 20 페이지 = 100 s. 종전 방식(절대 60 s · idle 없음)은 12 페이지에서 잘리고, 지금(절대 120 · idle 20)은 다 받는다."""
    rg._reset_response_cache(enabled=False)
    _fake_impl(monkeypatch, clock, 5)
    rg._set_deadline(60, 0)
    old_way = _collect(20)
    rg._set_deadline(120, 20)
    new_way = _collect(20)
    assert old_way == 12 and new_way == 20


def test_scaled_silent_bmc_is_stopped_by_the_idle_limit(monkeypatch, clock):
    """응답이 오지 않는 BMC: 요청마다 10 s 를 쓰고 실패 — 새 응답 없이 20 s 가 지나면 남은 요청을 보내지 않는다 (절대 상한 1200 까지 끌지 않는다)."""
    rg._reset_response_cache(enabled=False)
    _fake_impl(monkeypatch, clock, 10, ok=False)
    rg._set_deadline(1200, 20)
    assert _collect(50) == 2 and rg.deadline_kind() == "idle" and clock["t"] - 1000 == 20


def test_heartbeat_is_written_on_progress_at_most_every_five_seconds(tmp_path, clock):
    rg._set_heartbeat(str(tmp_path), "192.0.2.1")
    beat = tmp_path / "redfish-192.0.2.1"
    rg._mark_progress()
    first = beat.read_text(encoding="utf-8")
    beat.write_text("sentinel", encoding="utf-8")
    clock["t"] += 3
    rg._mark_progress()
    assert beat.read_text(encoding="utf-8") == "sentinel", "5 s 안에는 다시 쓰지 않는다"
    clock["t"] += 3
    rg._mark_progress()
    assert beat.read_text(encoding="utf-8") != "sentinel" and first.strip().isdigit()


def test_heartbeat_off_without_progress_dir(tmp_path, clock):
    rg._set_heartbeat("", "192.0.2.1")
    rg._mark_progress()
    assert list(tmp_path.iterdir()) == []


def test_module_parameters_are_wired():
    text = (REPO / "redfish-gather" / "library" / "redfish_gather.py").read_text(encoding="utf-8")
    assert "idle_deadline   = dict(type='int',  default=0)" in text and "progress_dir    = dict(type='str',  default='')" in text
    assert "_set_deadline(p.get('deadline'), p.get('idle_deadline'))" in text and "_set_heartbeat(p.get('progress_dir'), bmc_ip)" in text
    assert text.count("deadline_kind=deadline_kind()") == 2
