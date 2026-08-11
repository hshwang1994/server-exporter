"""Portal 실패 Grid 계약 — 실제 소스는 `errors[].message` 다 (Phase 6-B / §24).

배경 (2026-08-11 사용자 확인)
----------------------------
Phase 5-A 는 `diagnosis.failure_reason` 만 정화했다. 그런데 Portal 실패 Grid 가 실제로 읽는
값은 **`errors[].message`** 다. 그 자리에는 아직 아래가 남아 있었다:

  - `[task: linux | gather cpu]` 같은 **내부 Ansible 태스크명**
  - `SSH(22), WinRM(5985, 5986)` / `Redfish API(443)` 같은 **관리 포트 번호**
  - 대상 IP, 긴 대시(—), 이중 마침표

본 테스트는 두 가지를 고정한다.

  1. `errors[].message` 도 `failure_reason` 과 **같은 품질 기준**을 통과한다
     (`_assert_grid_ready` / `_assert_no_ports` / `_assert_no_technical_noise` 재사용).
  2. `errors[].message` 와 `diagnosis.failure_reason` 이 **같은 이야기**를 한다.
     구현상 build_failed_output.yml 이 failure_reason 을 그대로 복사하므로 문자열이 동일해야 한다.

추가로 문구 정본이 두 곳(Ansible / Python)에 있으므로 drift 를 막는다:
  - `common/vars/failure_reasons.yml`      (Ansible rescue 가 참조)
  - `common/library/precheck_bundle.py`    (precheck 단계가 참조)

렌더는 합성 fixture 가 아니라 **production YAML 자체**를 추출해 수행한다.
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.e2e.test_failure_reason_contract import (
    FAILURE_REASONS,
    _assert_grid_ready,
    _assert_no_ports,
    _assert_no_technical_noise,
    _env,
    _iter_tasks,
    _plays,
    _render_diagnosis,
    _render_fallback_envelopes,
    _task_by_name,
)

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

_BUILD_FAILED = "common/tasks/normalize/build_failed_output.yml"
_ERROR_TASK = "build_failed_output | build sections (all failed)"

_RF_TASK = "redfish | rescue | Portal 표시용 failure_reason 보장"
_ESXI_TASK = "esxi | rescue | Portal 표시용 failure_reason 보장"
_OS_TASKS = {
    "linux": "linux | rescue | Portal 표시용 diagnosis 보장",
    "windows": "windows | rescue | Portal 표시용 diagnosis 보장",
}

_PRECHECK_OK = {
    "reachable": True, "port_open": True, "protocol_supported": True,
    "auth_success": None, "failure_stage": None, "failure_code": None,
    "failure_reason": None, "details": {},
}


# ---------------------------------------------------------------------------
# build_failed_output.yml 의 errors[] 템플릿을 실제로 추출해 렌더
# ---------------------------------------------------------------------------
def _error_templates() -> dict[str, str]:
    """`_norm_errors` 의 message / detail 템플릿 원문을 production YAML 에서 꺼낸다."""
    tasks = list(yaml.safe_load_all((REPO / _BUILD_FAILED).read_text(encoding="utf-8")))[0]
    for task in _iter_tasks(tasks):
        errors = task.get("ansible.builtin.set_fact", {}).get("_norm_errors")
        if errors:
            return {"message": errors[0]["message"], "detail": errors[0]["detail"]}
    raise AssertionError(f"{_BUILD_FAILED} 에서 _norm_errors 템플릿을 찾지 못함")


def _render_error(ctx: dict[str, Any]) -> dict[str, Any]:
    tpl = _error_templates()
    return {
        key: _env().from_string(text).render(**ctx)
        for key, text in tpl.items()
    }


# ---------------------------------------------------------------------------
# 실패 경로 표본 — 각 채널의 rescue 가 만든 진단 + 그 채널이 넘기는 기술 문자열
# ---------------------------------------------------------------------------
def _rf_diag(collect_ok: bool, rejected: bool) -> dict[str, Any]:
    return _render_diagnosis(
        "redfish-gather/site.yml", _RF_TASK,
        {"_diagnosis": dict(_PRECHECK_OK), "_rf_collect_ok": collect_ok,
         "_rf_auth_rejected": rejected})


def _esxi_diag(auth_ok: bool, facts_ok: bool) -> dict[str, Any]:
    return _render_diagnosis(
        "esxi-gather/site.yml", _ESXI_TASK,
        {"_diagnosis": {**_PRECHECK_OK, "details": {"channel": "esxi"}},
         "_e_auth_ok": auth_ok, "_e_facts_ok": facts_ok})


def _os_diag(os_type: str, auth_ok: bool) -> dict[str, Any]:
    ctx: dict[str, Any] = {"_os_auth_ok": auth_ok, "_os_attempts_meta": {"attempted_count": 2}}
    if os_type == "windows":
        ctx["ansible_port"] = "5986"
    return _render_diagnosis("os-gather/site.yml", _OS_TASKS[os_type], ctx)


def _precheck_diag(channel: str, stage: str) -> dict[str, Any]:
    """precheck 단계 실패 진단 — 사유 문자열은 precheck_bundle 정본을 그대로 쓴다."""
    reason = {
        "reachable": pb.REASON_IP_UNCONFIRMED,
        "port": pb.REASON_IP_UNCONFIRMED,
        "protocol": pb.CHANNEL_PROTOCOL_MESSAGES[channel],
        "auth": pb.REASON_CREDENTIAL_FAILED,
    }[stage]
    return {**_PRECHECK_OK, "failure_stage": stage, "failure_reason": reason}


# 실제 운영에서 각 경로가 넘기는 기술 문자열 (모두 detail 로 가야 한다)
_TECHNICAL = {
    "redfish": "[task: redfish | abort if collect completely failed] "
               "Redfish 정보 수집에 실패했습니다 (192.0.2.10). 시도된 계정 수 2개.",
    "esxi": "[task: esxi | abort if all credentials failed] "
            "ESXi 자격증명 후보 2개가 모두 실패했습니다.",
    "os": "[task: linux | gather cpu] Linux 수집 예외",
    "os_detect": "확인한 관리 포트: WinRM 5986, WinRM 5985, SSH 22",
}

_CASES: list[tuple[str, dict[str, Any], str, str]] = [
    # label, diagnosis, _fail_error_message, _fail_error_detail
    ("precheck/redfish/reachable", _precheck_diag("redfish", "reachable"),
     _TECHNICAL["redfish"], "port=443: 연결 시간 초과 (timeout=3.0s)"),
    ("precheck/redfish/port", _precheck_diag("redfish", "port"),
     _TECHNICAL["redfish"], "port=443: 연결 거부됨 (port=443)"),
    ("precheck/redfish/protocol", _precheck_diag("redfish", "protocol"),
     _TECHNICAL["redfish"], "HTTP 500"),
    ("precheck/esxi/protocol", _precheck_diag("esxi", "protocol"),
     _TECHNICAL["esxi"], "vim25 SOAP 응답 아님"),
    ("precheck/os/reachable", _precheck_diag("os", "reachable"),
     _TECHNICAL["os_detect"],
     "port=5986: 연결 시간 초과 (timeout=2.0s); port=5985: 연결 거부됨 (port=5985)"),
    ("precheck/redfish/auth", _precheck_diag("redfish", "auth"),
     _TECHNICAL["redfish"], "HTTP 401"),
    ("rescue/redfish/credential", _rf_diag(False, False), _TECHNICAL["redfish"], None),
    ("rescue/redfish/rejected", _rf_diag(False, True), _TECHNICAL["redfish"], None),
    ("rescue/redfish/gather", _rf_diag(True, False), _TECHNICAL["redfish"], None),
    ("rescue/esxi/credential", _esxi_diag(False, False), _TECHNICAL["esxi"], None),
    ("rescue/esxi/gather", _esxi_diag(True, False), _TECHNICAL["esxi"], None),
    ("rescue/linux/credential", _os_diag("linux", False), _TECHNICAL["os"], None),
    ("rescue/linux/gather", _os_diag("linux", True), _TECHNICAL["os"], None),
    ("rescue/windows/credential", _os_diag("windows", False), _TECHNICAL["os"], None),
    ("rescue/windows/gather", _os_diag("windows", True), _TECHNICAL["os"], None),
]

_IDS = [c[0] for c in _CASES]


def _ctx(diag, message, detail) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "_diagnosis": diag,
        "_fail_error_section": "gather",
        "_out_target_type": "os",
        "_out_ip": "192.0.2.10",
        "inventory_hostname": "192.0.2.10",
        "_fail_error_message": message,
    }
    if detail is not None:
        ctx["_fail_error_detail"] = detail
    return ctx


# ═══════════════════════════════════════════════════════════════════════════
# §24 — errors[].message 도 Portal Grid 품질 기준을 통과해야 한다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,diag,message,detail", _CASES, ids=_IDS)
def test_errors_message_is_grid_ready(label, diag, message, detail):
    rendered = _render_error(_ctx(diag, message, detail))
    _assert_grid_ready(rendered["message"], f"errors[].message {label}")


@pytest.mark.parametrize("label,diag,message,detail", _CASES, ids=_IDS)
def test_errors_message_has_no_ports_or_noise(label, diag, message, detail):
    """§25 §26 — 관리 포트 번호 / 태스크명 / IP / HTTP status 는 message 에 없다."""
    msg = _render_error(_ctx(diag, message, detail))["message"]
    tag = f"errors[].message {label}"
    _assert_no_ports(msg, tag)
    _assert_no_technical_noise(msg, tag)
    assert "[task:" not in msg, f"[{tag}] 내부 태스크명 노출: {msg!r}"
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", msg), f"[{tag}] IP 노출: {msg!r}"
    assert ".." not in msg, f"[{tag}] 이중 마침표: {msg!r}"


# ═══════════════════════════════════════════════════════════════════════════
# §24 — failure_reason 과 errors[].message 정합 (같은 단계면 같은 이야기)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,diag,message,detail", _CASES, ids=_IDS)
def test_errors_message_matches_failure_reason(label, diag, message, detail):
    rendered = _render_error(_ctx(diag, message, detail))
    assert rendered["message"] == diag["failure_reason"], (
        f"[{label}] Portal 이 읽는 errors[].message 와 diagnosis.failure_reason 이 다르다 — "
        f"사용자가 보는 문장과 시스템 문장이 갈린다"
    )


def test_errors_message_falls_back_when_reason_missing():
    """failure_reason 이 비어 있어도 message 가 빈 칸이 되지 않는다."""
    for diag in ({}, {"failure_reason": None}, {"failure_reason": "   "}, None):
        rendered = _render_error(_ctx(diag, _TECHNICAL["os"], None))
        _assert_grid_ready(rendered["message"], f"fallback/{diag!r}")
        assert "[task:" not in rendered["message"]


# ═══════════════════════════════════════════════════════════════════════════
# §34 — 기술 정보는 errors[].detail 에 그대로 보존된다
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("label,diag,message,detail", _CASES, ids=_IDS)
def test_errors_detail_preserves_technical_evidence(label, diag, message, detail):
    rendered = _render_error(_ctx(diag, message, detail))
    got = rendered["detail"]
    assert isinstance(got, str) and got.strip(), f"[{label}] detail 이 비어 있다"
    assert message in got, f"[{label}] 기술 메시지가 detail 에서 사라졌다: {got!r}"
    if detail is not None:
        assert detail in got, f"[{label}] precheck 원본 오류가 detail 에서 사라졌다: {got!r}"


def test_errors_detail_is_null_when_nothing_technical():
    rendered = _render_error({
        "_diagnosis": _precheck_diag("redfish", "protocol"),
        "_fail_error_section": "gather",
    })
    assert rendered["detail"] is None, "기술 정보가 없으면 detail 은 null 이어야 한다"


def test_errors_detail_holds_port_numbers_for_os_portfail():
    """§25 — 포트 번호는 message 가 아니라 detail 이 보존한다 (운영자용)."""
    rendered = _render_error(_ctx(
        _precheck_diag("os", "reachable"), _TECHNICAL["os_detect"],
        "port=5986: 연결 시간 초과 (timeout=2.0s); port=22: 연결 거부됨 (port=22)"))
    for port in ("5986", "5985", "22"):
        assert port in rendered["detail"], f"detail 에 포트 {port} 근거가 없다"
        assert port not in rendered["message"], "message 에 포트가 노출됐다"


# ═══════════════════════════════════════════════════════════════════════════
# fallback envelope (block/rescue 모두 실패) 도 같은 계약을 지킨다
# ═══════════════════════════════════════════════════════════════════════════
_FALLBACK_CTX = {
    "redfish-gather/site.yml": {"_rf_ip": "192.0.2.10", "inventory_hostname": "192.0.2.10"},
    "esxi-gather/site.yml": {"_e_ip": "192.0.2.20", "inventory_hostname": "192.0.2.20"},
    "os-gather/site.yml": {"_ip": "192.0.2.30", "inventory_hostname": "192.0.2.30"},
}


@pytest.mark.parametrize("site", list(_FALLBACK_CTX))
def test_fallback_envelope_message_matches_reason(site):
    for idx, env in enumerate(_render_fallback_envelopes(site, _FALLBACK_CTX[site])):
        label = f"fallback/{site}#{idx}"
        errors = env["errors"]
        assert errors, f"[{label}] fallback envelope 에 errors 가 비어 있다"
        msg = errors[0]["message"]
        _assert_grid_ready(msg, label)
        _assert_no_ports(msg, label)
        _assert_no_technical_noise(msg, label)
        assert msg == env["diagnosis"]["failure_reason"], (
            f"[{label}] fallback 도 message 와 failure_reason 이 같아야 한다"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 문구 정본 drift — Ansible YAML ↔ Python 상수
# ═══════════════════════════════════════════════════════════════════════════
_CANONICAL = {
    "_fr_ip_unconfirmed": "REASON_IP_UNCONFIRMED",
    "_fr_port_unreachable": "REASON_PORT_UNREACHABLE",
    "_fr_protocol_unconfirmed": "REASON_PROTOCOL_UNCONFIRMED",
    "_fr_credential_failed": "REASON_CREDENTIAL_FAILED",
    "_fr_gather_failed": "REASON_GATHER_FAILED",
}


@pytest.mark.parametrize("yaml_key,py_name", sorted(_CANONICAL.items()))
def test_failure_reason_sources_do_not_drift(yaml_key, py_name):
    assert FAILURE_REASONS[yaml_key] == getattr(pb, py_name), (
        f"문구 정본 drift — common/vars/failure_reasons.yml:{yaml_key} 와 "
        f"precheck_bundle.{py_name} 가 다르다"
    )


def test_failure_reasons_yaml_has_exactly_the_five_sentences():
    assert set(FAILURE_REASONS) == set(_CANONICAL), (
        "사용자 문구 표준은 5 문장이다. 추가/삭제는 사용자 확정이 필요하다."
    )
    for key, text in FAILURE_REASONS.items():
        _assert_grid_ready(text, f"failure_reasons.yml:{key}")


@pytest.mark.parametrize("key,text", sorted(FAILURE_REASONS.items()))
def test_standard_sentences_have_no_dns_guidance(key, text):
    """§25 §28 — Portal 은 IPv4 만 넘긴다. DNS / 호스트 이름 안내를 쓰지 않는다."""
    for banned in ("DNS", "호스트 이름", "도메인", "이름 확인"):
        assert banned not in text, f"[{key}] DNS 계열 안내가 남아 있다: {text!r}"


def test_precheck_bundle_emits_only_standard_sentences():
    """precheck 가 만드는 사유도 5 문장 표준 밖으로 나가지 않는다."""
    standard = set(FAILURE_REASONS.values())
    produced = set(pb.CHANNEL_PROTOCOL_MESSAGES.values()) | {
        pb.reason_for_connect_failure(None),
        pb.reason_for_connect_failure(False),
        pb.reason_for_connect_failure(True),
        pb.REASON_CREDENTIAL_FAILED,
        pb.REASON_GATHER_FAILED,
    }
    assert produced <= standard, sorted(produced - standard)


def test_presence_branch_point_exists_and_defaults_to_unconfirmed():
    """§25 §33 — IP presence 판정 결과를 받을 자리는 있고, 미확인이면 1번 문구다.

    presence probe 자체는 별도 작업 영역이므로 여기서 만들지 않는다. 현재 저장소의 모든
    호출부는 판정값이 없어 None 을 넘기고, 그때 1번 문구가 나오는 것이 계약이다.
    """
    assert pb.reason_for_connect_failure(None) == pb.REASON_IP_UNCONFIRMED
    assert pb.reason_for_connect_failure(False) == pb.REASON_IP_UNCONFIRMED
    assert pb.reason_for_connect_failure(True) == pb.REASON_PORT_UNREACHABLE


def test_site_yml_rescues_reference_shared_constants_not_literals():
    """중복 문자열 정의 금지 — rescue 는 문장을 직접 쓰지 않고 정본 변수를 참조한다."""
    targets = [
        ("redfish-gather/site.yml", _RF_TASK),
        ("esxi-gather/site.yml", _ESXI_TASK),
        ("os-gather/site.yml", _OS_TASKS["linux"]),
        ("os-gather/site.yml", _OS_TASKS["windows"]),
    ]
    for site, task_name in targets:
        tpl = _task_by_name(site, task_name)["ansible.builtin.set_fact"]["_diagnosis"]
        assert "_fr_" in tpl, f"{site}:{task_name} 이 정본 변수를 참조하지 않는다"
        for sentence in FAILURE_REASONS.values():
            assert sentence not in tpl, (
                f"{site}:{task_name} 에 문구가 하드코딩됐다 — 정본 변수를 쓸 것"
            )


@pytest.mark.parametrize("site", ["redfish-gather/site.yml", "esxi-gather/site.yml",
                                  "os-gather/site.yml"])
def test_site_yml_loads_failure_reason_vars_where_needed(site):
    """정본 변수를 쓰는 play 는 반드시 그 vars_files 를 로드한다 (미정의 변수 방지)."""
    for play in _plays(site):
        uses = "_fr_" in yaml.safe_dump(play.get("tasks", []), allow_unicode=True)
        if not uses:
            continue
        files = " ".join(play.get("vars_files", []))
        assert "common/vars/failure_reasons.yml" in files, (
            f"{site} 의 play '{play.get('name')}' 가 _fr_* 를 쓰는데 vars_files 미로드"
        )


def test_no_secrets_in_rendered_errors():
    for label, diag, message, detail in _CASES:
        blob = str(_render_error(_ctx(diag, message, detail)))
        for secret in ("password", "Passw0rd", "Authorization", "Cookie", "Basic ", "token"):
            assert secret not in blob, f"[{label}] 민감정보 노출: {secret}"
