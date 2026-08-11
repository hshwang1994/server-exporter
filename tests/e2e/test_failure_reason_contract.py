"""Portal Grid 계약: status=failed 이면 diagnosis.failure_reason 이 반드시 의미 있어야 한다.

배경 (2026-08-10 사용자 확인)
----------------------------
Portal 은 서버 등록 / Gathering 실패 시 Grid 의 "실패 사유" 칸에
**`diagnosis.failure_reason` 하나만** 표시한다. 현재 이 필드 외에는 사실상 사용하지 않는다.

따라서 `status == "failed"` 인 정상적인 수집 실패 결과라면, Portal 이 이 필드 하나만 읽어도
사용자에게 의미 있는 실패 사유가 보여야 한다. 그런데 2026-08-10 이전에는 다음 구멍이 있었다:

  - Redfish / ESXi: precheck 통과 후 실패하면 rescue 가 precheck 의 diagnosis 를 그대로 쓰는데,
    precheck 는 성공했으므로 `failure_reason` 이 **null** 이었다.
  - OS: `_diagnosis` 를 성공 경로에서만 set 해서 자격 실패 / 수집 예외 시
    `build_failed_output.yml:79` 의 `default(none)` 이 발동, **diagnosis 전체가 null** 이었다.

본 테스트는 각 채널 site.yml 에서 **실제 템플릿을 추출해 렌더**하여 그 구멍이 다시 생기지
않도록 고정한다. (합성 fixture 가 아니라 production YAML 자체를 검증한다.)

렌더 환경은 `ansible.cfg:44 jinja2_native = True` 를 반영해 NativeEnvironment 를 쓴다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Ansible 템플릿 렌더 환경 대역
# ---------------------------------------------------------------------------
class _ChainableUndefined(StrictUndefined):
    """AnsibleUndefined 와 동일하게 속성 접근을 체이닝 가능하게 만든다."""

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        return self


def _ansible_bool(value: Any) -> bool:
    """ansible.builtin `bool` 필터 대역 (plain Jinja2 에는 없다)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return bool(value)


def _ansible_combine(base: Any, *others: Any) -> dict[str, Any]:
    """ansible.builtin `combine` 필터 대역 (기본은 얕은 병합)."""
    out = dict(base or {})
    for other in others:
        out.update(other or {})
    return out


def _env() -> NativeEnvironment:
    env = NativeEnvironment(undefined=_ChainableUndefined)
    env.filters["bool"] = _ansible_bool
    env.filters["combine"] = _ansible_combine
    return env


def _plays(site: str) -> list[dict[str, Any]]:
    return list(yaml.safe_load_all((REPO / site).read_text(encoding="utf-8")))[0]


def _iter_tasks(node: Any):
    """block / rescue / always 를 포함해 모든 태스크를 평탄화."""
    if isinstance(node, list):
        for item in node:
            yield from _iter_tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always", "tasks"):
            if key in node:
                yield from _iter_tasks(node[key])


def _task_by_name(site: str, needle: str) -> dict[str, Any]:
    for play in _plays(site):
        for task in _iter_tasks(play.get("tasks", [])):
            if needle in (task.get("name") or ""):
                return task
    raise AssertionError(f"{site} 에서 태스크를 찾지 못함: {needle!r}")


def _render_diagnosis(site: str, task_name: str, ctx: dict[str, Any]) -> Any:
    """site.yml 의 _diagnosis set_fact 템플릿을 실제로 추출해 렌더."""
    tpl = _task_by_name(site, task_name)["ansible.builtin.set_fact"]["_diagnosis"]
    if not isinstance(tpl, str):     # 리터럴 dict (OS PLAY 1.5)
        return tpl
    return _env().from_string(tpl).render(**ctx)


def _render_fallback_envelopes(site: str, ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """always 블록 OUTPUT 의 `_output | default({...})` 를 _output 미정의 상태로 렌더.

    - os-gather 는 OUTPUT 태스크가 3개다 (PLAY 1.5 / linux always / windows always).
      그중 fallback envelope 을 품은 것은 `default(` 를 쓰는 always 블록 2개뿐이므로
      그것만 골라낸다. PLAY 1.5 는 `_output` 이 반드시 존재하는 경로라 대상이 아니다.
    - `| to_json` 은 직렬화 단계일 뿐이라 제거하고 dict 그대로 받는다 (구조 검증이 목적).
    """
    out: list[dict[str, Any]] = []
    for play in _plays(site):
        for task in _iter_tasks(play.get("tasks", [])):
            if (task.get("name") or "") != "OUTPUT":
                continue
            tpl = task.get("ansible.builtin.debug", {}).get("msg", "")
            if "default(" not in tpl:
                continue
            rendered = _env().from_string(re.sub(r"\|\s*to_json", "", tpl)).render(**ctx)
            assert isinstance(rendered, dict), (
                f"{site} fallback envelope 이 dict 가 아님: {type(rendered).__name__}"
            )
            out.append(rendered)
    assert out, f"{site} 에서 fallback envelope 을 찾지 못함"
    return out


# ---------------------------------------------------------------------------
# 공통 단언 — Portal Grid 에 그대로 나가는 문자열의 품질 기준
# ---------------------------------------------------------------------------
# 사용자 지시 (2026-08-10): 일반 사용자가 읽는 문구다.
#   - 긴 대시(—) / 가운데점(·) 같은 특수 구분자 금지
#   - 완전한 한국어 문장
_FORBIDDEN_SEPARATORS = ("—", "·", "–")

# 사용자에게 아무 의미 없는 내부 잡음 (Grid 에 그대로 나가면 안 됨)
_LEAKY_TOKENS = ("Traceback", "ansible_failed", "{{", "}}", "None", "null")

# 2026-08-11 (Phase 5-A) 사용자 확정 — Portal Grid 문구에서 금지되는 것들.
#   숫자 전체를 막는 일반 정규식은 쓰지 않는다(§26). 실제로 쓰는 관리 포트만 막는다.
_MANAGEMENT_PORTS = ("22", "443", "5985", "5986")
# 내부 구현 용어 / 프로토콜 저수준 용어 / 변수명
_INTERNAL_TERMS = (
    "RST", "SYN", "SOAP", "XML", "Namespace", "ServiceRoot", "ServiceContent",
    "_output", "rescue", "wait_for", "set_fact", "task:", "Exception",
    "urllib", "pyVmomi", "vim25", "Output Builder", "IdentifyResponse",
)


def _assert_no_ports(reason: str, label: str) -> None:
    """§26 — Portal Grid 문구에 관리 포트 번호가 들어가면 안 된다."""
    for port in _MANAGEMENT_PORTS:
        assert port not in reason, (
            f"[{label}] failure_reason 에 관리 포트 번호 {port} 노출 — "
            f"포트는 errors[].message / detail 에만 남긴다: {reason!r}"
        )


def _assert_no_technical_noise(reason: str, label: str) -> None:
    """§2 / §27 — HTTP status, timeout 초, 내부 기술 용어, 태스크명 금지."""
    assert not re.search(r"HTTP\s*\d{3}", reason), (
        f"[{label}] failure_reason 에 HTTP status 노출: {reason!r}")
    assert not re.search(r"\b\d+(\.\d+)?\s*(초|s\b|sec)", reason), (
        f"[{label}] failure_reason 에 timeout 초 값 노출: {reason!r}")
    for term in _INTERNAL_TERMS:
        assert term not in reason, (
            f"[{label}] failure_reason 에 내부 기술 용어 {term!r} 노출: {reason!r}")


def _assert_grid_ready(reason: Any, label: str) -> None:
    assert isinstance(reason, str), f"[{label}] failure_reason 이 문자열이 아님: {reason!r}"
    assert reason.strip(), f"[{label}] failure_reason 이 빈 문자열"
    assert len(reason.strip()) >= 10, f"[{label}] failure_reason 이 너무 짧음: {reason!r}"
    for sep in _FORBIDDEN_SEPARATORS:
        assert sep not in reason, (
            f"[{label}] failure_reason 에 특수 구분자 {sep!r} 사용 — "
            f"완전한 한국어 문장으로 작성할 것: {reason!r}"
        )
    for tok in _LEAKY_TOKENS:
        assert tok not in reason, f"[{label}] failure_reason 에 내부 잡음 {tok!r} 노출: {reason!r}"
    assert reason.strip().endswith((".", "다", "요")), (
        f"[{label}] failure_reason 이 완결된 문장이 아님: {reason!r}"
    )
    # 원문 기술 오류 통째로 싣기 금지 (errors[].detail 영역)
    assert len(reason) <= 200, f"[{label}] failure_reason 이 너무 김 ({len(reason)}자): {reason!r}"
    _assert_no_ports(reason, label)
    _assert_no_technical_noise(reason, label)


# ---------------------------------------------------------------------------
# §29 단계 진행 관계 — 문장이 주장하는 성공은 Machine Diagnosis 로 증명돼야 한다
# ---------------------------------------------------------------------------
# 왼쪽 표현이 문장에 있으면 오른쪽 관측값이 반드시 참이어야 한다.
_CLAIM_REQUIREMENTS: tuple[tuple[str, str], ...] = (
    ("관리 연결은 확인되었지만", "port_open"),
    ("SSH 서비스는 확인되었지만", "protocol_supported"),
    ("WinRM 서비스는 확인되었지만", "protocol_supported"),
    ("Redfish 서비스는 확인되었지만", "protocol_supported"),
    ("vSphere API는 확인되었지만", "protocol_supported"),
    ("관리 서비스는 확인되었지만", "protocol_supported"),
    ("접속은 확인되었지만", "auth_success"),
)


def _assert_claims_match_observation(diag: dict[str, Any], label: str) -> None:
    reason = diag.get("failure_reason") or ""
    for phrase, field in _CLAIM_REQUIREMENTS:
        if phrase in reason:
            assert diag.get(field) is True, (
                f"[{label}] 문구가 '{phrase}' 로 앞 단계 성공을 주장하는데 "
                f"diagnosis.{field}={diag.get(field)!r} — 관측과 모순"
            )


def _assert_diagnosis_shape(diag: Any, label: str) -> None:
    assert isinstance(diag, dict), f"[{label}] diagnosis 가 dict 가 아님: {type(diag).__name__}"
    for key in ("reachable", "port_open", "protocol_supported", "auth_success",
                "failure_stage", "failure_reason", "details"):
        assert key in diag, f"[{label}] diagnosis.{key} 누락 (7키 shape 깨짐)"
    assert isinstance(diag["details"], dict), f"[{label}] details 가 dict 가 아님"


# ═══════════════════════════════════════════════════════════════════════════
# Case 1~3 — precheck (reachable / port / protocol)   [Redfish · ESXi 공통 경로]
# ═══════════════════════════════════════════════════════════════════════════
import socket  # noqa: E402
import sys     # noqa: E402
import types   # noqa: E402

sys.path.insert(0, str(REPO / "common" / "library"))
_b = types.ModuleType("ansible.module_utils.basic"); _b.AnsibleModule = object
_m = types.ModuleType("ansible.module_utils"); _m.basic = _b
_a = types.ModuleType("ansible"); _a.module_utils = _m
sys.modules.setdefault("ansible", _a)
sys.modules.setdefault("ansible.module_utils", _m)
sys.modules.setdefault("ansible.module_utils.basic", _b)
import precheck_bundle as pb  # noqa: E402


class _ExitJson(Exception):
    def __init__(self, result): super().__init__("exit"); self.result = result


def _run_precheck(monkeypatch, channel: str, connect_exc=None, http=None) -> dict:
    monkeypatch.setattr(
        pb.socket, "getaddrinfo",
        lambda h, p, type=None: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (h, p))],
    )

    class _Sock:
        def settimeout(self, _t): pass
        def connect(self, _a):
            if connect_exc is not None:
                raise connect_exc
        def close(self): pass

    monkeypatch.setattr(pb.socket, "socket", lambda *_a: _Sock())
    if http is not None:
        monkeypatch.setattr(pb, "http_get", lambda *a, **k: http)
        # 2026-08-10 (Phase 4-B): esxi 는 Stage 3 에서 /sdk 로 vim25 SOAP 을 POST 한다.
        # 두 채널을 같은 seam 으로 다루기 위해 함께 대체한다 (payload=None 은 양쪽 공통).
        monkeypatch.setattr(pb, "http_post_soap", lambda *a, **k: http)

    class _Fake:
        params = dict(host="192.0.2.10", channel=channel, ports=[], timeout_port=3.0,
                      timeout_protocol=15.0, timeout_auth=8.0,
                      username=None, password=None, verify_ssl=False,
                      probe_protocol=True, port_poll_interval=0.0)
        def exit_json(self, **kw): raise _ExitJson(kw)

    monkeypatch.setattr(pb, "AnsibleModule", lambda **_kw: _Fake())
    with pytest.raises(_ExitJson) as exc:
        pb.run_module()
    return exc.value.result


@pytest.mark.parametrize("channel", ["redfish", "esxi"])
def test_case01_precheck_reachable_failure_has_reason(monkeypatch, channel):
    r = _run_precheck(monkeypatch, channel, connect_exc=socket.timeout())
    assert r["failure_stage"] == "reachable"
    _assert_grid_ready(r["failure_reason"], f"C1 reachable/{channel}")


@pytest.mark.parametrize("channel", ["redfish", "esxi"])
def test_case02_precheck_port_failure_has_reason(monkeypatch, channel):
    r = _run_precheck(monkeypatch, channel, connect_exc=ConnectionRefusedError())
    assert r["failure_stage"] == "port"
    _assert_grid_ready(r["failure_reason"], f"C2 port/{channel}")


@pytest.mark.parametrize("channel", ["redfish", "esxi"])
def test_case03_precheck_protocol_failure_has_reason(monkeypatch, channel):
    # 응답 자체가 없는 경우(payload=None)를 쓴다 — 두 채널 공통으로 프로토콜 실패가 된다.
    # (Phase 4-B 이후 esxi 는 HTTP 500 이어도 본문이 vim25 가 아니면 실패다. 종전 주석은
    #  "esxi 는 500 도 통과" 였는데 그 whitelist 는 제거됐다.)
    monkeypatch.setattr("time.sleep", lambda _s: None)   # probe_redfish 의 1초 backoff 제거
    r = _run_precheck(monkeypatch, channel,
                      http=(False, "연결 실패: TLS handshake 오류", None))
    assert r["failure_stage"] == "protocol"
    _assert_grid_ready(r["failure_reason"], f"C3 protocol/{channel}")


def test_precheck_auth_failure_only_claims_rejection_on_401(monkeypatch):
    """auth_success=false 는 401 관측 시에만. timeout/5xx 는 null 유지 (요구사항 6)."""
    for status, expect_false in ((401, True), (403, False), (500, False)):
        result = pb._init_result("redfish", [443])
        monkeypatch.setattr(
            pb, "http_get",
            lambda *a, s=status, **k: (False, f"HTTP {s}", {"status_code": s, "json": None}),
        )
        pb._try_redfish_auth("192.0.2.10", 443, "u", "p", 8.0, False, result)
        assert result["failure_stage"] == "auth"
        _assert_grid_ready(result["failure_reason"], f"auth/{status}")
        if expect_false:
            assert result["auth_success"] is False, f"HTTP {status} 는 명시적 거부"
        else:
            assert result["auth_success"] is None, (
                f"HTTP {status} 로는 인증 거부를 확정할 수 없다 (false 금지)"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Case 4 — Redfish post-precheck 실패
# ═══════════════════════════════════════════════════════════════════════════
_PRECHECK_OK_DIAG = {
    "reachable": True, "port_open": True, "protocol_supported": True,
    "auth_success": None, "failure_stage": None, "failure_reason": None,
    "details": {"channel": "redfish", "checked_ports": [443], "selected_port": 443},
}

_RF_TASK = "redfish | rescue | Portal 표시용 failure_reason 보장"


@pytest.mark.parametrize("collect_ok,label", [(False, "수집 실패"), (True, "정규화 예외")])
def test_case04_redfish_post_precheck_failure_has_reason(collect_ok, label):
    diag = _render_diagnosis("redfish-gather/site.yml", _RF_TASK,
                             {"_diagnosis": dict(_PRECHECK_OK_DIAG),
                              "_rf_collect_ok": collect_ok})
    _assert_diagnosis_shape(diag, f"C4 redfish/{label}")
    _assert_grid_ready(diag["failure_reason"], f"C4 redfish/{label}")
    # 인증 거부를 관측하지 못했으므로 false 금지
    assert diag["auth_success"] is None


def test_redfish_rescue_preserves_precheck_reason():
    """precheck 가 만든 구체적 사유를 덮어쓰지 않는다 (when 가드 의미)."""
    task = _task_by_name("redfish-gather/site.yml", _RF_TASK)
    guard = task["when"]
    ok = _env().from_string("{{ " + guard + " }}").render(
        _diagnosis={**_PRECHECK_OK_DIAG, "failure_reason": "이미 있는 사유"})
    assert ok is False, "failure_reason 이 이미 있으면 덮어쓰지 않아야 한다"


def test_redfish_rescue_survives_undefined_diagnosis():
    """precheck include 자체가 실패해 _diagnosis 가 아예 없어도 7키 shape 를 보장."""
    diag = _render_diagnosis("redfish-gather/site.yml", _RF_TASK, {"_rf_collect_ok": False})
    _assert_diagnosis_shape(diag, "C4 redfish/_diagnosis 미정의")
    _assert_grid_ready(diag["failure_reason"], "C4 redfish/_diagnosis 미정의")


# ═══════════════════════════════════════════════════════════════════════════
# Case 5·6 — ESXi 자격 전멸 / Facts 실패
# ═══════════════════════════════════════════════════════════════════════════
_ESXI_TASK = "esxi | rescue | Portal 표시용 failure_reason 보장"


@pytest.mark.parametrize("auth_ok,facts_ok,label,expect_stage,expect_auth", [
    (False, False, "C5 자격 전멸",   "auth", None),
    # Phase 2 (2026-08-10): 인증 통과 후 실패는 gather 단계로 식별된다 (종전 None)
    (True,  False, "C6 facts 실패",  "gather", True),
    (True,  True,  "C6 기타 예외",   "gather", True),
])
def test_case05_06_esxi_failure_has_reason(auth_ok, facts_ok, label, expect_stage, expect_auth):
    diag = _render_diagnosis(
        "esxi-gather/site.yml", _ESXI_TASK,
        {"_diagnosis": {**_PRECHECK_OK_DIAG, "details": {"channel": "esxi"}},
         "_e_auth_ok": auth_ok, "_e_facts_ok": facts_ok})
    _assert_diagnosis_shape(diag, label)
    _assert_grid_ready(diag["failure_reason"], label)
    assert diag["failure_stage"] == expect_stage, f"[{label}] failure_stage"
    # 요구사항 6 — 자격 probe 실패는 인증 거부 관측이 아니므로 false 금지
    assert diag["auth_success"] is expect_auth, f"[{label}] auth_success"


# ═══════════════════════════════════════════════════════════════════════════
# Case 7~10 — OS 자격 전멸 / 수집 예외 (Linux · Windows)
# ═══════════════════════════════════════════════════════════════════════════
_OS_TASKS = {
    "linux": "linux | rescue | Portal 표시용 diagnosis 보장",
    "windows": "windows | rescue | Portal 표시용 diagnosis 보장",
}


@pytest.mark.parametrize("os_type", ["linux", "windows"])
@pytest.mark.parametrize("auth_ok,label", [(False, "자격 전멸"), (True, "수집 예외")])
def test_case07_10_os_failure_has_reason(os_type, auth_ok, label):
    ctx: dict[str, Any] = {"_os_auth_ok": auth_ok, "_os_attempts_meta": {"attempted_count": 2}}
    if os_type == "windows":
        ctx["ansible_port"] = "5986"
    diag = _render_diagnosis("os-gather/site.yml", _OS_TASKS[os_type], ctx)
    tag = f"{os_type}/{label}"

    _assert_diagnosis_shape(diag, tag)
    _assert_grid_ready(diag["failure_reason"], tag)
    _assert_claims_match_observation(diag, tag)
    # PLAY 1 precheck 가 TCP 연결 성공을 실제 관측한 경로다
    assert diag["reachable"] is True and diag["port_open"] is True, tag
    # Phase 3-B 이후 PLAY 1 은 SSH identification / WinRM Identify 까지 확인해야 통과한다.
    # 즉 PLAY 2/3 에 도달했다는 것 자체가 프로토콜 관측 성공을 뜻한다 (자격 결과와 무관).
    assert diag["protocol_supported"] is True, f"[{tag}] 프로토콜은 precheck 가 이미 확인했다"
    if auth_ok:
        assert diag["auth_success"] is True, f"[{tag}] 자격 probe 통과는 관측된 사실"
        # Phase 2 (2026-08-10): enum 에 gather 가 추가되어 수집 단계 실패를 표현할 수 있다
        assert diag["failure_stage"] == "gather", f"[{tag}] 수집 단계 실패는 gather"
        assert "접속은 확인되었지만" in diag["failure_reason"], (
            f"[{tag}] 인증 성공이 관측됐으므로 그 사실을 사용자에게 알린다")
    else:
        # 요구사항 6 — 잘못된 자격 / 연결 끊김 / 제한 쉘을 구분 못 하므로 false 금지
        assert diag["auth_success"] is None, f"[{tag}] 인증 거부를 관측하지 못했다"
        assert diag["failure_stage"] == "auth", f"[{tag}] 실행이 멈춘 단계"
        assert "접속은 확인되었지만" not in diag["failure_reason"], (
            f"[{tag}] auth_success=null 인데 접속 성공을 암시하면 안 된다")
        expected_service = "SSH" if os_type == "linux" else "WinRM"
        assert f"{expected_service} 서비스는 확인되었지만" in diag["failure_reason"], tag
    assert diag["details"]["channel"] == "os"
    assert diag["details"]["detected_os"] == os_type


def test_os_rescue_windows_checked_ports_follow_actual_port():
    for port, expected in (("5986", [5986]), ("5985", [5986, 5985])):
        diag = _render_diagnosis("os-gather/site.yml", _OS_TASKS["windows"],
                                 {"_os_auth_ok": False, "ansible_port": port})
        assert diag["details"]["checked_ports"] == expected
        assert diag["details"]["selected_port"] == int(port)


# ═══════════════════════════════════════════════════════════════════════════
# Case 11 — OS 관리 포트 전체 실패 (PLAY 1.5)
# ═══════════════════════════════════════════════════════════════════════════
# Phase 5-A (2026-08-11): PLAY 1.5 의 문구 덮어쓰기 태스크를 **제거**했다. 종전 문구는
# 관리 포트 번호를 Portal Grid 에 그대로 노출했고, 전 포트 무응답을 "모두 응답이 없습니다"
# 로 단정했다. 이제 공통 precheck 가 관측 종류에 맞는 사용자 문장을 직접 만들고 PLAY 1.5 는
# 그 값을 그대로 쓴다. 따라서 아래 검증도 **모듈 실제 실행 결과**를 본다.
_OS_PORTFAIL_TASK_REMOVED = "Portal 표시용 failure_reason 을 OS 문맥으로"


def _os_portfail_diag(stage: str, code: str) -> dict[str, Any]:
    """OS 포트 전멸 경로를 precheck_bundle 로 실제 실행해 진단을 얻는다."""
    kind = {
        "TCP_CONNECT_FAILED": (False, "연결 시간 초과", pb.TCP_FAIL_TIMEOUT),
        "DNS_RESOLUTION_FAILED": (False, "DNS 해석 실패", pb.TCP_FAIL_DNS),
        "TCP_CONNECTION_REFUSED": (False, "연결 거부됨", pb.TCP_FAIL_REFUSED),
    }[code]

    import unittest.mock as _mock
    fake = _mock.patch.object(pb, "tcp_check_budget", lambda *_a, **_k: kind)

    class _Fake:
        params = dict(host="192.0.2.30", channel="os", ports=[], timeout_port=2.0,
                      timeout_protocol=5.0, timeout_auth=8.0, username=None,
                      password=None, verify_ssl=False, probe_protocol=True,
                      port_poll_interval=1.0)

        def exit_json(self, **kw):
            raise _ExitJson(kw)

    with fake, _mock.patch.object(pb, "AnsibleModule", lambda **_kw: _Fake()):
        with pytest.raises(_ExitJson) as exc:
            pb.run_module()
    raw = exc.value.result
    assert raw["failure_stage"] == stage and raw["failure_code"] == code
    return pb_build_diagnosis(raw)


def pb_build_diagnosis(raw: dict[str, Any]) -> dict[str, Any]:
    """filter_plugins/diagnosis_mapper 의 build_diagnosis 를 그대로 사용."""
    sys.path.insert(0, str(REPO / "filter_plugins"))
    from diagnosis_mapper import build_diagnosis  # noqa: E402
    return build_diagnosis(raw, "os")


def test_os_portfail_override_task_is_gone():
    """§26 — 관리 포트 번호를 Grid 에 노출하던 덮어쓰기 태스크가 다시 생기면 실패."""
    text = (REPO / "os-gather/site.yml").read_text(encoding="utf-8")
    for play in _plays("os-gather/site.yml"):
        for task in _iter_tasks(play.get("tasks", [])):
            assert _OS_PORTFAIL_TASK_REMOVED not in (task.get("name") or ""), (
                "PLAY 1.5 의 failure_reason 덮어쓰기가 되살아났다 — 포트 번호 노출 회귀 위험"
            )
    assert "SSH(22)/WinRM(5985, 5986) 관리 포트에 연결하지 못했습니다" not in text


@pytest.mark.parametrize("stage,code", [
    ("reachable", "TCP_CONNECT_FAILED"),
    ("reachable", "DNS_RESOLUTION_FAILED"),
    ("port", "TCP_CONNECTION_REFUSED"),
])
def test_case11_os_all_ports_failure_has_reason(stage, code):
    diag = _os_portfail_diag(stage, code)
    label = f"C11 OS 포트 전멸/{stage}"
    _assert_diagnosis_shape(diag, label)
    _assert_grid_ready(diag["failure_reason"], label)
    # 공통 precheck 의 관측 결과를 그대로 보존한다 (문구만 OS 문맥으로 교체)
    assert diag["failure_stage"] == stage, label
    assert diag["failure_code"] == code, label
    # 인증 코드가 아예 실행되지 않는 경로 — false 는 거짓 정보
    assert diag["auth_success"] is None, "인증을 시도하지 않았으므로 false 가 아니라 null"
    assert diag["details"]["checked_ports"] == [5986, 5985, 22]


def test_os_portfail_reason_matches_observation():
    """관측 종류마다 문구가 달라야 한다 (사실과 어긋나는 표현 금지)."""
    no_resp = _os_portfail_diag("reachable", "TCP_CONNECT_FAILED")["failure_reason"]
    refused = _os_portfail_diag("port", "TCP_CONNECTION_REFUSED")["failure_reason"]
    dns = _os_portfail_diag("reachable", "DNS_RESOLUTION_FAILED")["failure_reason"]

    # TCP 연결 미확인 — 전원이 꺼졌다거나 방화벽이 원인이라고 단정하지 않는다.
    assert no_resp == pb.REASON_TCP_UNCONFIRMED
    assert "관리 통신을 확인할 수 없습니다" in no_resp
    assert "전원" not in no_resp, "관측하지 않은 원인을 단정하지 않는다"
    # RST 는 중간 방화벽/보안 장비가 낼 수도 있어 "서버가 응답했다"고 단정하지 않는다.
    assert refused == pb.REASON_PORT_REFUSED
    assert "서버는 응답하지만" not in refused, "RST 를 서버 자체 응답으로 확정하면 안 된다"
    assert "통신은 되지만" not in refused
    # 주소 해석 실패는 패킷을 보낸 적도 없다.
    assert dns == pb.REASON_DNS_FAILED
    assert "주소를 확인할 수 없습니다" in dns
    assert len({no_resp, refused, dns}) == 3
    for reason in (no_resp, refused, dns):
        _assert_grid_ready(reason, "OS portfail")


# ═══════════════════════════════════════════════════════════════════════════
# Case 12 — Fallback (block/rescue 모두 실패 → always 블록)
# ═══════════════════════════════════════════════════════════════════════════
_FALLBACK_CTX = {
    "redfish-gather/site.yml": {"_rf_ip": "192.0.2.10", "inventory_hostname": "192.0.2.10"},
    "esxi-gather/site.yml": {"_e_ip": "192.0.2.20", "inventory_hostname": "192.0.2.20"},
    "os-gather/site.yml": {"_ip": "192.0.2.30", "inventory_hostname": "192.0.2.30"},
}


@pytest.mark.parametrize("site", list(_FALLBACK_CTX))
def test_case12_fallback_envelope_has_reason(site):
    envelopes = _render_fallback_envelopes(site, _FALLBACK_CTX[site])
    for idx, env in enumerate(envelopes):
        label = f"C12 fallback/{site}#{idx}"
        assert env["status"] == "failed", label
        _assert_diagnosis_shape(env["diagnosis"], label)
        _assert_grid_ready(env["diagnosis"]["failure_reason"], label)
        assert env["diagnosis"]["failure_stage"] == "fallback", label


# ═══════════════════════════════════════════════════════════════════════════
# 요구사항 11 — status=failed ⇒ failure_reason 이 null/빈 문자열이면 실패시킨다
# ═══════════════════════════════════════════════════════════════════════════
def _failed_envelopes() -> list[tuple[str, dict[str, Any]]]:
    """저장소가 실제로 emit 할 수 있는 failed envelope 표본을 모은다."""
    out: list[tuple[str, dict[str, Any]]] = []
    for site, ctx in _FALLBACK_CTX.items():
        for idx, env in enumerate(_render_fallback_envelopes(site, ctx)):
            out.append((f"fallback::{site}#{idx}", env))
    from tests.e2e.test_envelope_failure_modes import ENVELOPES  # noqa: PLC0415
    for name, env in ENVELOPES.items():
        out.append((f"fixture::{name}", env))
    return out


@pytest.mark.parametrize("label,envelope", _failed_envelopes(), ids=lambda v: v if isinstance(v, str) else "")
def test_failed_envelope_always_carries_failure_reason(label, envelope):
    """status=failed 인데 Portal 이 표시할 사유가 없으면 실패."""
    if envelope.get("status") != "failed":
        pytest.skip("failed 상태가 아님")
    diag = envelope.get("diagnosis")
    assert diag is not None, (
        f"[{label}] status=failed 인데 diagnosis 가 null — Portal 이 실패 사유를 표시할 수 없다"
    )
    assert isinstance(diag, dict), f"[{label}] diagnosis 가 dict 가 아님"
    reason = diag.get("failure_reason")
    assert reason is not None and str(reason).strip(), (
        f"[{label}] status=failed 인데 failure_reason 이 비어 있다 — Portal Grid 가 빈 칸이 된다"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 문체 — 사용자 노출 문자열 전반
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("site", list(_FALLBACK_CTX))
def test_user_facing_messages_use_plain_sentences(site):
    """failure_reason / 사용자 노출 msg 에 긴 대시·가운데점 금지 (2026-08-10 사용자 지시)."""
    text = (REPO / site).read_text(encoding="utf-8")
    offenders: list[str] = []
    for raw in re.findall(r"failure_reason'?\s*:\s*'([^']{5,300})'", text):
        if any(sep in raw for sep in _FORBIDDEN_SEPARATORS):
            offenders.append(raw)
    for raw in re.findall(r'failure_reason:\s+"([^"]{5,300})"', text):
        if any(sep in raw for sep in _FORBIDDEN_SEPARATORS):
            offenders.append(raw)
    assert not offenders, f"{site} failure_reason 에 특수 구분자 사용: {offenders}"


def test_precheck_bundle_reason_strings_are_plain_sentences():
    for reason in pb.CHANNEL_PROTOCOL_MESSAGES.values():
        _assert_grid_ready(reason, "CHANNEL_PROTOCOL_MESSAGES")
