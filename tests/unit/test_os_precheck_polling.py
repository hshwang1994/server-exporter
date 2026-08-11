"""Phase 3-A 보정: 종전 wait_for 의 "예산 안에서 반복 확인" 의미를 보존했는지 검증.

배경
----
os-gather 는 종전에 `ansible.builtin.wait_for` 로 관리 포트를 확인했다. wait_for(state=started)
는 단발 연결이 아니라 **timeout 예산 안에서 폴링**한다 (설치본 ansible 2.19.9 실측 —
`ansible/modules/wait_for.py` argument_spec `connect_timeout=5`, `sleep=1`, 본문 :619-628):

    end = start + timeout
    while now < end:
        create_connection(..., min(connect_timeout, ceil(end - now)))   # 성공 시 종료
        time.sleep(sleep)

Phase 3-A 최초 전환에서 이를 포트당 1회 시도로 바꿔, **probe 시작 시점엔 닫혀 있지만 예산
안에 기동되는 서비스**가 실패로 바뀌는 회귀가 생겼다. 본 테스트가 그 의미 보존을 고정한다.

시간 기반 소켓 상태 전환을 실제로 만들 수 없으므로 **결정적 mock clock** 을 쓴다
(`time.monotonic` / `time.sleep` 대체). 실제 대기 없이 시간이 흐르므로 테스트는 즉시 끝난다.
"""
from __future__ import annotations

import socket
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "common" / "library"))

_b = types.ModuleType("ansible.module_utils.basic")
_b.AnsibleModule = object
_m = types.ModuleType("ansible.module_utils")
_m.basic = _b
_a = types.ModuleType("ansible")
_a.module_utils = _m
sys.modules.setdefault("ansible", _a)
sys.modules.setdefault("ansible.module_utils", _m)
sys.modules.setdefault("ansible.module_utils.basic", _b)

import precheck_bundle as pb  # noqa: E402


class _ExitJson(Exception):
    def __init__(self, result):
        super().__init__("exit")
        self.result = result


class _Clock:
    """결정적 mock clock — 실제 대기 없이 시간을 흘린다."""

    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture()
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(pb.time, "monotonic", c.monotonic)
    monkeypatch.setattr(pb.time, "sleep", c.sleep)
    return c


def _late_start_tcp(clock: _Clock, open_at: float, *, fail_kind="refused", consume=0.0):
    """clock 이 open_at 을 지나면 연결 성공하는 가짜 TCP.

    consume: 시도 1회가 소비하는 시간. timeout 실패는 연결 시도 자체가 예산을 먹는다.
    """
    attempts: list[tuple[int, float, float]] = []

    def fake(host, port, timeout):
        attempts.append((port, timeout, clock.t))
        clock.advance(consume)
        if clock.t >= open_at:
            return True, None, None
        if fail_kind == "timeout":
            return False, "연결 시간 초과 (timeout={0}s)".format(timeout), pb.TCP_FAIL_TIMEOUT
        return False, "연결 거부됨 (port={0})".format(port), pb.TCP_FAIL_REFUSED

    return fake, attempts


# ═══════════════════════════════════════════════════════════════════════════
# 핵심 회귀 — 늦게 기동되는 서비스
# ═══════════════════════════════════════════════════════════════════════════
def test_service_starts_late_within_budget_succeeds(clock, monkeypatch):
    """Case 2: probe 시작 시점엔 닫혀 있으나 예산(2초) 안에 기동되는 서비스."""
    fake, attempts = _late_start_tcp(clock, open_at=1.0)
    monkeypatch.setattr(pb, "tcp_check_ex", fake)

    ok, err, kind = pb.tcp_check_budget("192.0.2.30", 5986, budget=2.0, poll_interval=1.0)

    assert ok is True, "예산 안에 열린 포트를 놓치면 기존 운영 동작 회귀"
    assert err is None and kind is None
    assert len(attempts) == 2, f"t=0 실패 → sleep(1) → t=1 성공. 실제: {attempts}"
    assert clock.t <= 2.0, "예산을 넘겨 대기하지 않는다"


def test_single_attempt_would_have_missed_late_start(clock, monkeypatch):
    """대조군 — poll_interval=0 (redfish/esxi 경로) 이면 같은 상황에서 실패한다."""
    fake, attempts = _late_start_tcp(clock, open_at=1.0)
    monkeypatch.setattr(pb, "tcp_check_ex", fake)

    ok, _err, kind = pb.tcp_check_budget("192.0.2.30", 5986, budget=2.0, poll_interval=0.0)

    assert ok is False and kind == pb.TCP_FAIL_REFUSED
    assert len(attempts) == 1, "단일 시도 경로가 유지돼야 두 채널 동작이 안 바뀐다"


def test_case08_refused_then_success_within_budget(clock, monkeypatch):
    """Case 8: 첫 시도 거부 후 같은 포트가 예산 안에 열리면 최종 성공이다."""
    fake, _attempts = _late_start_tcp(clock, open_at=1.0, fail_kind="refused")
    monkeypatch.setattr(pb, "tcp_check_ex", fake)

    ok, _err, _kind = pb.tcp_check_budget("192.0.2.30", 22, budget=2.0, poll_interval=1.0)
    assert ok is True, "중간 거부 때문에 최종 진단을 실패로 만들지 않는다"


# ═══════════════════════════════════════════════════════════════════════════
# 예산 / 시도 타임아웃이 wait_for 와 동등한지
# ═══════════════════════════════════════════════════════════════════════════
def test_budget_is_not_exceeded(clock, monkeypatch):
    """무한 재시도 금지 — 예산 안에서 끝난다."""
    fake, attempts = _late_start_tcp(clock, open_at=999.0)
    monkeypatch.setattr(pb, "tcp_check_ex", fake)

    ok, _err, kind = pb.tcp_check_budget("192.0.2.30", 5986, budget=2.0, poll_interval=1.0)

    assert ok is False and kind == pb.TCP_FAIL_REFUSED
    assert clock.t <= 2.0, f"예산 초과 대기: {clock.t}"
    assert len(attempts) == 2, f"예산 2초 / sleep 1초 → 2회. 실제: {len(attempts)}"


def test_timeout_failure_consumes_budget_like_wait_for(clock, monkeypatch):
    """timeout 실패는 연결 시도가 예산을 먹어 1회로 끝난다 (wait_for 와 동일)."""
    fake, attempts = _late_start_tcp(clock, open_at=999.0, fail_kind="timeout", consume=2.0)
    monkeypatch.setattr(pb, "tcp_check_ex", fake)

    ok, _err, kind = pb.tcp_check_budget("192.0.2.30", 5986, budget=2.0, poll_interval=1.0)

    assert ok is False and kind == pb.TCP_FAIL_TIMEOUT
    assert len(attempts) == 1, f"예산을 소모하는 실패는 재시도 여지가 없다: {attempts}"


def test_attempt_timeout_follows_wait_for_formula(clock, monkeypatch):
    """시도별 연결 타임아웃 = min(connect_timeout=5, ceil(남은 예산))."""
    fake, attempts = _late_start_tcp(clock, open_at=999.0)
    monkeypatch.setattr(pb, "tcp_check_ex", fake)

    pb.tcp_check_budget("192.0.2.30", 5986, budget=2.0, poll_interval=1.0)

    assert [t for _p, t, _at in attempts] == [2, 1], (
        f"t=0 남은 2초 → 2, t=1 남은 1초 → 1. 실제: {attempts}"
    )


def test_connect_timeout_cap_matches_wait_for_default():
    """긴 예산에서는 wait_for 의 connect_timeout=5 상한이 적용된다."""
    assert pb._WAIT_FOR_CONNECT_TIMEOUT == 5.0
    assert pb._WAIT_FOR_SLEEP == 1.0


# ═══════════════════════════════════════════════════════════════════════════
# 여러 시도의 결과 종합 (§2)
# ═══════════════════════════════════════════════════════════════════════════
def test_dominant_kind_across_attempts(clock, monkeypatch):
    """시도마다 종류가 다르면 마지막이 아니라 관측 강도로 대표를 정한다."""
    seq = iter([pb.TCP_FAIL_TIMEOUT, pb.TCP_FAIL_REFUSED, pb.TCP_FAIL_TIMEOUT])

    def fake(host, port, timeout):
        kind = next(seq, pb.TCP_FAIL_TIMEOUT)
        return False, "사유 {0}".format(kind), kind

    monkeypatch.setattr(pb, "tcp_check_ex", fake)
    ok, err, kind = pb.tcp_check_budget("192.0.2.30", 5986, budget=3.0, poll_interval=1.0)

    assert ok is False
    assert kind == pb.TCP_FAIL_REFUSED, "RST 를 한 번이라도 관측했으면 그것이 대표"
    assert "refused" in err, "대표 종류에 해당하는 증거를 남긴다"


@pytest.mark.parametrize("kinds,expected", [
    ([pb.TCP_FAIL_TIMEOUT, pb.TCP_FAIL_DNS], pb.TCP_FAIL_DNS),
    ([pb.TCP_FAIL_REFUSED, pb.TCP_FAIL_TIMEOUT], pb.TCP_FAIL_REFUSED),
    ([pb.TCP_FAIL_OTHER, pb.TCP_FAIL_TIMEOUT], pb.TCP_FAIL_TIMEOUT),
    ([pb.TCP_FAIL_OTHER], pb.TCP_FAIL_OTHER),
])
def test_dominant_kind_priority(kinds, expected):
    assert pb._dominant_kind(kinds) == expected


# ═══════════════════════════════════════════════════════════════════════════
# checked_ports 중복 없음 (§6)
# ═══════════════════════════════════════════════════════════════════════════
def test_checked_ports_has_no_duplicates(clock, monkeypatch):
    monkeypatch.setattr(
        pb, "tcp_check_ex",
        lambda h, p, t: (False, "연결 거부됨", pb.TCP_FAIL_REFUSED))

    *_rest, probed = pb._check_ports("192.0.2.30", [5986, 5985, 22], 2.0, poll_interval=1.0)

    assert probed == [5986, 5985, 22]
    assert len(probed) == len(set(probed)), "포트를 여러 번 시도해도 중복 금지"


def test_checked_ports_stops_at_first_success(clock, monkeypatch):
    fake, _a = _late_start_tcp(clock, open_at=1.0)
    monkeypatch.setattr(pb, "tcp_check_ex", fake)

    *_rest, probed = pb._check_ports("192.0.2.30", [5986, 5985, 22], 2.0, poll_interval=1.0)
    assert probed == [5986], "예산 안에 5986 이 열렸으면 나머지는 시도하지 않는다"


# ═══════════════════════════════════════════════════════════════════════════
# DNS 선정 규칙 (§3) — 구조적으로 오분류가 불가능함을 고정
# ═══════════════════════════════════════════════════════════════════════════
def test_dns_kind_only_when_resolution_itself_fails(monkeypatch):
    """일부 주소 시도 실패는 DNS 가 아니다. getaddrinfo 자체가 실패해야 DNS 다."""
    monkeypatch.setattr(
        pb.socket, "getaddrinfo",
        lambda h, p, type=None: [                      # noqa: A002
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", p)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (h, p)),
        ])

    class _Sock:
        def __init__(self, *_a):
            pass

        def settimeout(self, _t):
            pass

        def connect(self, _a):
            raise socket.timeout()

        def close(self):
            pass

    monkeypatch.setattr(pb.socket, "socket", lambda *_a: _Sock())
    _ok, _err, kind = pb.tcp_check_ex("192.0.2.30", 22, 2.0)
    assert kind == pb.TCP_FAIL_TIMEOUT, "주소 시도 실패를 DNS 실패로 만들면 안 된다"

    def _boom(*_a, **_k):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(pb.socket, "getaddrinfo", _boom)
    _ok, _err, kind = pb.tcp_check_ex("192.0.2.30", 22, 2.0)
    assert kind == pb.TCP_FAIL_DNS, "해석 자체 실패만 DNS"


def test_one_address_fails_other_succeeds(monkeypatch):
    """복수 주소: 하나가 실패해도 다른 주소로 성공하면 성공이 우선한다."""
    monkeypatch.setattr(
        pb.socket, "getaddrinfo",
        lambda h, p, type=None: [                      # noqa: A002
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", p)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (h, p)),
        ])

    class _Sock:
        def __init__(self, family, *_a):
            self.family = family

        def settimeout(self, _t):
            pass

        def connect(self, _a):
            if self.family == socket.AF_INET6:
                raise ConnectionRefusedError()

        def close(self):
            pass

    monkeypatch.setattr(pb.socket, "socket", lambda f, *_a: _Sock(f))
    ok, err, kind = pb.tcp_check_ex("192.0.2.30", 22, 2.0)
    assert ok is True and err is None and kind is None, (
        "한 주소의 거부가 전체 실패로 확정되면 안 된다"
    )


# ═══════════════════════════════════════════════════════════════════════════
# §9 기존 채널 보호 — polling 이 redfish / esxi 로 새지 않는다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("channel", ["redfish", "esxi"])
def test_other_channels_keep_single_attempt(monkeypatch, channel):
    attempts: list[tuple[int, float]] = []

    def fake(host, port, timeout):
        attempts.append((port, timeout))
        return False, "연결 거부됨", pb.TCP_FAIL_REFUSED

    monkeypatch.setattr(pb, "tcp_check_ex", fake)

    class _Fake:
        params = dict(host="192.0.2.10", channel=channel, ports=[], timeout_port=3.0,
                      timeout_protocol=15.0, timeout_auth=8.0, username=None, password=None,
                      verify_ssl=False, probe_protocol=True, port_poll_interval=0.0)

        def exit_json(self, **kw):
            raise _ExitJson(kw)

    monkeypatch.setattr(pb, "AnsibleModule", lambda **_kw: _Fake())
    with pytest.raises(_ExitJson) as exc:
        pb.run_module()

    assert attempts == [(443, 3.0)], f"{channel} 단일 시도 / timeout 3.0 유지: {attempts}"
    result = exc.value.result
    assert result["failure_stage"] == "port"
    assert result["failure_code"] == "TCP_CONNECTION_REFUSED"
    assert result["checked_ports"] == [443]


def test_os_channel_uses_polling_end_to_end(clock, monkeypatch):
    """OS 는 run_module 경로에서도 폴링이 실제로 적용된다."""
    fake, attempts = _late_start_tcp(clock, open_at=1.0)
    monkeypatch.setattr(pb, "tcp_check_ex", fake)

    class _Fake:
        params = dict(host="192.0.2.30", channel="os", ports=[], timeout_port=2.0,
                      timeout_protocol=15.0, timeout_auth=8.0, username=None, password=None,
                      verify_ssl=False, probe_protocol=False, port_poll_interval=1.0)

        def exit_json(self, **kw):
            raise _ExitJson(kw)

    monkeypatch.setattr(pb, "AnsibleModule", lambda **_kw: _Fake())
    with pytest.raises(_ExitJson) as exc:
        pb.run_module()
    result = exc.value.result

    assert result["detected_os"] == "windows" and result["selected_port"] == 5986
    assert result["checked_ports"] == [5986], "성공한 포트에서 멈춘다"
    assert result["failure_stage"] is None and result["failure_code"] is None
    assert len(attempts) == 2, "5986 을 예산 안에서 2회 시도해 성공"


# ═══════════════════════════════════════════════════════════════════════════
# 배선 — os-gather 가 폴링 간격을 실제로 넘기는가
# ═══════════════════════════════════════════════════════════════════════════
def test_os_gather_wires_poll_interval():
    text = (REPO / "os-gather/site.yml").read_text(encoding="utf-8")
    assert "_precheck_port_poll_interval" in text, "OS 가 폴링 간격을 넘기지 않으면 회귀 재발"
    assert "_probe_poll_interval | default(1)" in text, "wait_for sleep 기본값 1 을 쓴다"

    rp = (REPO / "common/tasks/precheck/run_precheck.yml").read_text(encoding="utf-8")
    assert "port_poll_interval:" in rp
    assert "default(0.0)" in rp, "미지정 시 0 = 단일 시도 (기존 두 채널 보호)"


def test_rst_reason_does_not_claim_server_responded():
    """RST 관측을 '서버가 응답했다'로 단정하지 않는다 (중간 장비가 RST 를 낼 수 있다)."""
    text = (REPO / "os-gather/site.yml").read_text(encoding="utf-8")
    assert "서버는 응답하지만" not in text, (
        "RST 는 중간 방화벽/보안 장비가 생성했을 수 있어 서버 응답으로 확정 금지"
    )
    # Phase 5-A (2026-08-11): 문구는 site.yml 이 아니라 precheck_bundle 이 만든다.
    assert "서버는 응답하지만" not in pb.REASON_PORT_REFUSED
    assert "연결 시도가 거부되었습니다" in pb.REASON_PORT_REFUSED, (
        "관측한 사실(연결 시도 거부)까지만 표현한다"
    )
    # 거부 주체를 최종 대상으로 확정하지 않는다 (중간 네트워크 장비일 수 있다)
    assert "대상 관리 서비스 연결이 거부" not in pb.REASON_PORT_REFUSED
    for banned in ("—", "·", "–"):
        assert banned not in "SSH(22)/WinRM(5985, 5986) 관리 포트에 연결하지 못했습니다."
