# -*- coding: utf-8 -*-
"""reachable = 관리 TCP 응답 OR ICMP Echo 응답 (2026-09-03 사용자 지시).

배경
----
종전 도달성 판정은 관리 TCP 포트의 응답(연결 성공 또는 RST)만 근거로 삼았다. 그래서
**서버는 살아 있는데 방화벽이 관리 포트 TCP 를 DROP** 하는 구간이 stage=reachable 로
떨어졌고, 운영자에게는 "IP 사용 여부와 네트워크 상태를 확인하세요"(1번 문장)가 나갔다.
정작 봐야 할 곳은 방화벽인데 IP 대장을 뒤지게 만든 셈이다.

이 파일이 잠그는 계약
--------------------
  (1) TCP 응답 OR ICMP 응답 = reachable PASS
  (2) ICMP 는 **앞단 Gate 가 아니다** — TCP 가 응답하면 ICMP 는 호출조차 되지 않는다
  (3) ICMP 실패는 아무것도 실패시키지 않는다 (전용 failure_code 없음, 판정은 종전과 동일)
  (4) reachable=true 인데 관리 포트를 못 열었으면 **기존 흐름대로 port 단계 실패**
  (5) 예산: ICMP 는 "TCP 전 포트 무응답" 경로에서만, Echo 1회만 소비한다
  (6) envelope shape 불변 — ICMP 근거는 errors[].detail 로만 나간다

네트워크 0 — subprocess / socket 계층을 monkeypatch 한다 (실 ping 프로세스 금지).
"""
from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "common" / "library"))

# ansible stub (기존 precheck unit test 와 동일 패턴)
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_mu = types.ModuleType("ansible.module_utils")
_stub_mu.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_mu
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_mu)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import precheck_bundle as pb  # noqa: E402


# ---------------------------------------------------------------------------
# 하네스
# ---------------------------------------------------------------------------
class _ExitJson(Exception):
    def __init__(self, result):
        super().__init__("exit")
        self.result = result


class _FakeModule:
    def __init__(self, params):
        self.params = params

    def exit_json(self, **kw):
        raise _ExitJson(kw)


def _params(channel="redfish", **over):
    base = dict(host="192.0.2.10", channel=channel, ports=[], timeout_port=3.0,
                timeout_protocol=15.0, timeout_auth=8.0, username=None,
                password=None, verify_ssl=False, probe_protocol=True,
                port_poll_interval=0.0, icmp_probe=True, timeout_icmp=1.0)
    base.update(over)
    return base


_PING_OK_STDOUT = b"64 bytes from 192.0.2.10: icmp_seq=1 ttl=64 time=0.4 ms"


def _fake_proc(returncode=0, stdout=_PING_OK_STDOUT):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=b"")


def _run(monkeypatch, *, channel="redfish", tcp=None, icmp_calls=None,
         icmp=(False, "icmp: 응답 없음 (테스트 스텁)"), **over):
    """run_module 1회 실행. tcp=(ok, err, kind), icmp=(replied, note)."""
    tcp = tcp or (False, "연결 시간 초과 (timeout=3.0s)", pb.TCP_FAIL_TIMEOUT)
    monkeypatch.setattr(pb, "tcp_check_ex", lambda *_a, **_k: tcp)
    monkeypatch.setattr(pb, "tcp_check_budget", lambda *_a, **_k: tcp)
    monkeypatch.setattr(pb, "probe_os", lambda *_a, **_k: (True, None, {}))
    monkeypatch.setattr(
        pb, "http_get",
        lambda *_a, **_k: (True, None, {"status_code": 200, "headers": {},
                                        "json": {"@odata.id": "/redfish/v1",
                                                 "@odata.type":
                                                     "#ServiceRoot.v1_15_0.ServiceRoot",
                                                 "RedfishVersion": "1.6.0"}}))

    def _icmp(host, timeout=pb._ICMP_DEFAULT_TIMEOUT):
        if icmp_calls is not None:
            icmp_calls.append((host, timeout))
        return icmp

    monkeypatch.setattr(pb, "icmp_check", _icmp)
    monkeypatch.setattr(pb, "AnsibleModule",
                        lambda **_k: _FakeModule(_params(channel, **over)))
    with pytest.raises(_ExitJson) as exc:
        pb.run_module()
    return exc.value.result


# ===========================================================================
# A. icmp_check 자체 — 관측을 어떻게 판정하는가
# ===========================================================================
def test_icmp_reply_is_only_claimed_on_success(monkeypatch):
    monkeypatch.setattr(pb.subprocess, "run", lambda *_a, **_k: _fake_proc(0))
    replied, note = pb.icmp_check("192.0.2.10")
    assert replied is True
    assert "Echo Reply" in note


@pytest.mark.parametrize("rc", [1, 2, 68])
def test_icmp_nonzero_rc_is_no_reply_not_failure(rc, monkeypatch):
    """무응답 / 권한 부족 / 이름 해석 실패 모두 '근거 없음' 하나로만 취급한다."""
    monkeypatch.setattr(pb.subprocess, "run", lambda *_a, **_k: _fake_proc(rc))
    replied, note = pb.icmp_check("192.0.2.10")
    assert replied is False
    assert note and "icmp" in note


def test_icmp_missing_ping_binary_degrades_quietly(monkeypatch):
    """ping 이 없는 환경 — 예외로 모듈을 죽이지 않고 TCP 전용 판정으로 되돌아간다."""
    def _boom(*_a, **_k):
        raise FileNotFoundError("ping")

    monkeypatch.setattr(pb.subprocess, "run", _boom)
    replied, note = pb.icmp_check("192.0.2.10")
    assert replied is False
    assert "ping" in note


def test_icmp_subprocess_timeout_is_bounded(monkeypatch):
    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="ping", timeout=2.0)

    monkeypatch.setattr(pb.subprocess, "run", _boom)
    replied, _note = pb.icmp_check("192.0.2.10", timeout=1.0)
    assert replied is False


def test_icmp_os_error_is_swallowed(monkeypatch):
    def _boom(*_a, **_k):
        raise OSError("Permission denied")

    monkeypatch.setattr(pb.subprocess, "run", _boom)
    replied, note = pb.icmp_check("192.0.2.10")
    assert replied is False and "확인 불가" in note


def test_icmp_command_sends_exactly_one_echo(monkeypatch):
    """예산 보호 — 요청 1개, 하드 타임아웃 지정, shell 미경유."""
    seen = {}

    def _run_proc(cmd, **kw):
        seen["cmd"] = cmd
        seen["kw"] = kw
        return _fake_proc(0)

    monkeypatch.setattr(pb.subprocess, "run", _run_proc)
    pb.icmp_check("192.0.2.10", timeout=1.0)

    cmd = seen["cmd"]
    assert cmd[0] == "ping" and cmd[-1] == "192.0.2.10"
    count_flag = "-n" if sys.platform.startswith("win") else "-c"
    assert cmd[cmd.index(count_flag) + 1] == "1", "Echo 는 1회만"
    assert seen["kw"]["timeout"] == pytest.approx(1.0 + pb._ICMP_SPAWN_MARGIN)
    assert "shell" not in seen["kw"], "shell 경유 금지"


def test_windows_router_unreachable_is_not_counted_as_reply(monkeypatch):
    """Windows ping 은 중간 라우터의 'Destination host unreachable' 에도 rc=0 을 준다."""
    if not sys.platform.startswith("win"):
        pytest.skip("Windows 전용 quirk")
    monkeypatch.setattr(
        pb.subprocess, "run",
        lambda *_a, **_k: _fake_proc(
            0, b"Reply from 10.0.0.1: Destination host unreachable."))
    replied, _note = pb.icmp_check("192.0.2.10")
    assert replied is False


# ===========================================================================
# B. OR 판정 — reachable / stage / code
# ===========================================================================
@pytest.mark.parametrize("channel", ["redfish", "esxi", "os"])
def test_tcp_silent_icmp_reply_is_reachable(channel, monkeypatch):
    """(1)(4) TCP 무응답 + ICMP 응답 -> reachable=true, 실패는 port 단계."""
    r = _run(monkeypatch, channel=channel, icmp=(True, "icmp: Echo Reply 확인"))
    assert r["reachable"] is True
    assert r["port_open"] is False
    assert r["failure_stage"] == "port"
    assert r["failure_code"] == "TCP_CONNECT_FAILED"
    assert r["failure_reason"] == pb.REASON_PORT_UNREACHABLE
    assert r["auth_success"] is None, "인증을 시도하지 않았으므로 null"


@pytest.mark.parametrize("channel", ["redfish", "esxi", "os"])
def test_tcp_silent_icmp_silent_is_unreachable(channel, monkeypatch):
    """(1) 둘 다 무응답일 때만 reachable 실패."""
    r = _run(monkeypatch, channel=channel)
    assert r["reachable"] is False
    assert r["failure_stage"] == "reachable"
    assert r["failure_code"] == "TARGET_UNREACHABLE"
    assert r["failure_reason"] == pb.REASON_IP_UNCONFIRMED


def test_rst_keeps_refused_and_skips_icmp(monkeypatch):
    """(2)(5) RST 는 이미 능동 응답 — ICMP 를 호출하지 않는다 (예산 0)."""
    calls = []
    r = _run(monkeypatch, tcp=(False, "연결 거부됨 (port=443)", pb.TCP_FAIL_REFUSED),
             icmp_calls=calls)
    assert r["reachable"] is True
    assert r["failure_stage"] == "port"
    assert r["failure_code"] == "TCP_CONNECTION_REFUSED", "RST 관측을 ICMP 가 덮지 않는다"
    assert calls == [], "RST 경로에서 ICMP 를 호출하면 예산 낭비"


def test_success_path_never_probes_icmp(monkeypatch):
    """(2)(5) 정상 수집 경로의 예산 증가 0."""
    calls = []
    r = _run(monkeypatch, tcp=(True, None, None), icmp_calls=calls)
    assert r["failure_stage"] is None and r["failure_code"] is None
    assert calls == [], "TCP 가 응답하면 ICMP 는 호출조차 되지 않아야 한다"


def test_dns_failure_skips_icmp(monkeypatch):
    """보낼 주소 자체가 없으면 ICMP 도 무의미하다 — 종전 판정 유지."""
    calls = []
    r = _run(monkeypatch, tcp=(False, "DNS 해석 실패", pb.TCP_FAIL_DNS), icmp_calls=calls)
    assert r["failure_stage"] == "reachable"
    assert r["failure_code"] == "DNS_RESOLUTION_FAILED"
    assert calls == []


def test_icmp_probe_false_restores_tcp_only_behaviour(monkeypatch):
    """(3) 끄면 종전(TCP 전용)과 완전히 같은 결과."""
    calls = []
    r = _run(monkeypatch, icmp_calls=calls, icmp=(True, "icmp: Echo Reply 확인"),
             icmp_probe=False)
    assert calls == [], "icmp_probe=false 면 호출 자체가 없다"
    assert r["reachable"] is False
    assert r["failure_stage"] == "reachable"
    assert r["failure_code"] == "TARGET_UNREACHABLE"


def test_icmp_timeout_param_is_honoured(monkeypatch):
    """(5) 예산은 timeout_icmp 로만 정해진다 (포트 예산과 분리)."""
    calls = []
    _run(monkeypatch, icmp_calls=calls, timeout_icmp=0.5)
    assert calls and calls[0][1] == 0.5


def test_icmp_probed_once_per_host(monkeypatch):
    """(5) 포트가 3개인 OS 채널에서도 ICMP 는 1회뿐이다."""
    calls = []
    _run(monkeypatch, channel="os", icmp_calls=calls)
    assert len(calls) == 1, f"ICMP 호출 {len(calls)}회 — 포트마다 보내면 예산이 늘어난다"


# ===========================================================================
# C. 증거와 envelope 경계
# ===========================================================================
def test_icmp_evidence_goes_to_detail_only(monkeypatch):
    """(6) 기술 근거는 errors[].detail 로만 — 사용자 문장에는 넣지 않는다."""
    r = _run(monkeypatch, icmp=(True, "icmp: Echo Reply 확인"))
    assert "icmp" in r["detail"], "ICMP 관측 근거가 사라졌다"
    assert "port=443" in r["detail"], "포트별 사유도 함께 보존한다"
    for banned in ("icmp", "ICMP", "ping", "Echo"):
        assert banned not in r["failure_reason"], "사용자 문장에 내부 용어 금지"


def test_diagnosis_shape_unchanged(monkeypatch):
    """(6) envelope 의 diagnosis 키 집합이 늘지 않는다 (호출자 파싱 불변)."""
    sys.path.insert(0, str(REPO / "filter_plugins"))
    from diagnosis_mapper import build_diagnosis  # noqa: PLC0415

    r = _run(monkeypatch, icmp=(True, "icmp: Echo Reply 확인"))
    diag = build_diagnosis(r, "redfish")
    assert set(diag) == {
        "reachable", "port_open", "protocol_supported", "auth_success",
        "failure_stage", "failure_code", "failure_reason", "details",
    }
    assert "icmp" not in str(diag["details"]).lower(), (
        "ICMP 결과를 diagnosis.details 에 새 키로 넣지 않는다 (rule 96 R1-B)"
    )


def test_no_icmp_specific_failure_code_exists():
    """(3) ICMP 전용 code 금지 — 사용자 지시."""
    for code in pb.REASON_BY_FAILURE_CODE:
        assert "ICMP" not in code.upper(), f"ICMP 전용 failure_code 가 생겼다: {code}"
