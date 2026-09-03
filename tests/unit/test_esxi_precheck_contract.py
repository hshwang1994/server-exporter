"""Phase 4-B: ESXi 채널 precheck 전체 경로의 Diagnosis Contract 고정.

`probe_esxi` 단위 판정은 `test_precheck_probe_esxi.py` 가 본다. 이 파일은 그 결과가
`run_module()` 을 지나 **Diagnosis 필드**로 어떻게 나오는지를 고정한다 —
Phase 1~4-A 에서 확정한 계약이 이번 변경으로 흔들리지 않는지가 관심사다.

  - `reachable` / `port_open` : TCP 단계 의미 불변
  - `protocol_supported`      : 실제 vim25 응답을 확인한 경우에만 true
  - `auth_success`            : Protocol Probe 는 자격증명을 안 보내므로 **항상 None**
                                (HTTP 401/403 을 받아도 False 로 만들지 않는다)
  - `failure_stage` / `failure_code` : protocol / PROTOCOL_CHECK_FAILED
  - `failure_reason`          : Phase 1 문구 그대로

네트워크 0 — `tcp_check_ex` / `http_post_soap` 를 monkeypatch 한다.
"""
from __future__ import annotations

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

from tests.precheck_stub import ICMP_REPLY, ICMP_SILENT, silence_icmp  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "esxi"
LAB_SERVICE_CONTENT = (FIXTURES / "lab" / "esxi_7_0_3_service_content.xml").read_bytes()

# Phase 6-B (2026-08-11): 사용자 확정 문구 표준 3번. 채널 이름(vSphere API)을 문장에서 뺐다
# — 사용자는 채널을 고르지 않고 IP 만 넘기므로 조치에 도움이 되지 않는다. 채널 근거는
# errors[].detail 과 envelope 의 target_type 이 유지한다. 정본은 precheck_bundle 상수다.
ESXI_PROTOCOL_REASON = pb.REASON_PROTOCOL_UNCONFIRMED


class _ExitJson(Exception):
    def __init__(self, result):
        super().__init__("exit")
        self.result = result


def run_esxi(monkeypatch, *, tcp_ok=True, post=None, timeout_protocol=30.0,
             icmp=ICMP_SILENT):
    # 2026-09-03: TCP 전멸 시에만 소비되는 ICMP 확인 결과를 주입한다 (실 ping 금지).
    silence_icmp(monkeypatch, pb, icmp)
    monkeypatch.setattr(
        pb, "tcp_check_ex",
        lambda *_a, **_k: (True, None, None) if tcp_ok
        else (False, "연결 시간 초과 (timeout=3.0s)", pb.TCP_FAIL_TIMEOUT))
    if post is not None:
        monkeypatch.setattr(pb, "http_post_soap", post)

    class _Fake:
        params = dict(host="192.0.2.10", channel="esxi", ports=[], timeout_port=3.0,
                      timeout_protocol=timeout_protocol, timeout_auth=8.0,
                      username=None, password=None, verify_ssl=False,
                      probe_protocol=True, port_poll_interval=0.0,
                      icmp_probe=True, timeout_icmp=1.0)

        def exit_json(self, **kw):
            raise _ExitJson(kw)

    monkeypatch.setattr(pb, "AnsibleModule", lambda **_kw: _Fake())
    with pytest.raises(_ExitJson) as exc:
        pb.run_module()
    return exc.value.result


def _post(ok, err, status, body):
    def fake(url, body_, timeout, verify=False, extra_headers=None,
             content_type=None, max_bytes=None):
        payload = None if status is None else {"status_code": status, "body": body}
        return ok, err, payload
    return fake


# ═══════════════════════════════════════════════════════════════════════════
# 성공 경로
# ═══════════════════════════════════════════════════════════════════════════
def test_service_content_makes_protocol_supported(monkeypatch):
    result = run_esxi(monkeypatch, post=_post(True, None, 200, LAB_SERVICE_CONTENT))
    assert result["reachable"] is True
    assert result["port_open"] is True
    assert result["protocol_supported"] is True
    assert result["protocol_checked"] is True
    assert result["auth_success"] is None, "Protocol Probe 는 인증을 관측하지 않는다"
    assert result["failure_stage"] is None
    assert result["failure_code"] is None
    assert result["failure_reason"] is None
    assert result["checked_ports"] == [443]
    assert result["selected_port"] == 443


def test_success_probe_facts_shape_unchanged(monkeypatch):
    """§21 — diagnosis.details 로 나가는 키 집합을 늘리지 않는다 (baseline 정합)."""
    result = run_esxi(monkeypatch, post=_post(True, None, 200, LAB_SERVICE_CONTENT))
    assert set(result["probe_facts"]) == {"vsphere_endpoint"}


# ═══════════════════════════════════════════════════════════════════════════
# 실패 경로 — 일반 HTTPS / 일반 SOAP
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,status,body", [
    ("일반 HTTPS 200", 200, b"<html><body>nginx</body></html>"),
    ("일반 JSON 200", 200, b'{"ok":true}'),
    ("일반 SOAP 200", 200,
     b'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
     b'<soapenv:Body><PingResponse xmlns="http://example.invalid/x"/></soapenv:Body>'
     b"</soapenv:Envelope>"),
    ("404", 404, b"<html>not found</html>"),
    ("500", 500, b"<html>error</html>"),
    ("503", 503, b""),
])
def test_non_vsphere_response_is_protocol_failure(monkeypatch, label, status, body):
    ok = status == 200
    err = None if ok else "HTTP {0}".format(status)
    result = run_esxi(monkeypatch, post=_post(ok, err, status, body))
    assert result["reachable"] is True, label
    assert result["port_open"] is True, label
    assert result["protocol_supported"] is False, label
    assert result["failure_stage"] == "protocol", label
    assert result["failure_code"] == "PROTOCOL_CHECK_FAILED", label
    assert result["failure_reason"] == ESXI_PROTOCOL_REASON, label
    assert result["auth_success"] is None, label
    assert result["detail"], "실패 근거(Evidence)가 비어 있으면 안 된다"


@pytest.mark.parametrize("status", [401, 403])
def test_auth_status_never_sets_auth_success(monkeypatch, status):
    """§9 — 401/403 을 받았다는 이유로 auth_success=false 를 만들지 않는다."""
    result = run_esxi(
        monkeypatch,
        post=_post(False, "HTTP {0}".format(status), status, b"<html>denied</html>"))
    assert result["auth_success"] is None
    assert result["failure_stage"] == "protocol"
    assert result["failure_code"] == "PROTOCOL_CHECK_FAILED"
    assert "HTTP {0}".format(status) in result["detail"]


def test_structured_vsphere_fault_passes_protocol_stage(monkeypatch):
    raw = (FIXTURES / "synthetic" / "vsphere_fault_vim25.xml").read_bytes()
    result = run_esxi(monkeypatch, post=_post(False, "HTTP 500", 500, raw))
    assert result["protocol_supported"] is True
    assert result["failure_stage"] is None
    assert result["auth_success"] is None
    assert result["probe_facts"]["root_status_code"] == 500


# ═══════════════════════════════════════════════════════════════════════════
# TCP 단계 회귀 — Phase 2/3 매핑이 그대로여야 한다
# ═══════════════════════════════════════════════════════════════════════════
def test_tcp_failure_mapping_unchanged(monkeypatch):
    calls = {"n": 0}

    def never(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("TCP 실패 시 Protocol Probe 를 보내면 안 된다")

    result = run_esxi(monkeypatch, tcp_ok=False, post=never)
    assert calls["n"] == 0
    assert result["reachable"] is False
    assert result["port_open"] is False
    assert result["protocol_supported"] is False
    assert result["failure_stage"] == "reachable"
    # 2026-09-03: TCP·ICMP 모두 무응답 → TARGET_UNREACHABLE (종전 TCP_CONNECT_FAILED).
    assert result["failure_code"] == "TARGET_UNREACHABLE"
    assert result["auth_success"] is None


def test_tcp_failure_with_icmp_reply_stops_at_port_stage(monkeypatch):
    """2026-09-03: ICMP 가 답해도 프로토콜 probe 로 넘어가지는 않는다.

    도달이 확인됐을 뿐 관리 포트(443)는 열지 못했으므로 vSphere SOAP 을 보낼 소켓이 없다.
    실패 단계만 reachable → port 로 내려간다.
    """
    calls = {"n": 0}

    def never(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("포트를 열지 못했는데 Protocol Probe 를 보내면 안 된다")

    result = run_esxi(monkeypatch, tcp_ok=False, post=never, icmp=ICMP_REPLY)
    assert calls["n"] == 0
    assert result["reachable"] is True
    assert result["port_open"] is False
    assert result["protocol_supported"] is False
    assert result["failure_stage"] == "port"
    assert result["failure_code"] == "TCP_CONNECT_FAILED"
    assert result["auth_success"] is None


def test_protocol_timeout_is_passed_through(monkeypatch):
    """§13 — 호출부가 준 protocol timeout 을 그대로 쓴다 (esxi-gather 는 30초)."""
    seen = {}

    def fake(url, body, timeout, verify=False, extra_headers=None,
             content_type=None, max_bytes=None):
        seen["timeout"] = timeout
        return True, None, {"status_code": 200, "body": LAB_SERVICE_CONTENT}

    run_esxi(monkeypatch, post=fake, timeout_protocol=30.0)
    assert seen["timeout"] == 30.0


def test_no_credentials_leak_in_result(monkeypatch):
    result = run_esxi(
        monkeypatch, post=_post(True, None, 200, b"<html>nope</html>"))
    blob = " ".join(str(v) for v in result.values())
    for secret in ("password", "Passw0rd", "Authorization", "Cookie", "Basic "):
        assert secret not in blob, "민감정보 노출: {0}".format(secret)
