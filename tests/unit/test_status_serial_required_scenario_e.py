"""status 시나리오 E — OS 채널 필수 식별자(Serial Number) 누락은 failed (2026-10-13 사용자 정책).

정본: common/tasks/normalize/require_serial.yml (판정 · 봉투 수정) + os-gather/tasks/normalize/require_serial.yml (OS 원인 판정 wrapper).
조립된 _output 의 후처리다. build_status.yml 의 섹션 기반 판정(A/B/C/D)은 그대로이고,
E 는 그 위에 얹힌다 — 다른 섹션의 수집 값(data) · sections · hostname · meta · correlation 은 보존한다.

무엇을 고정하나
  - Serial 이 있으면 아무것도 바꾸지 않는다. 빈 문자열 · 자리표시자는 누락이다.
  - 정상 경로(failure_reason 없음): status=failed, stage=gather, code=GATHER_FAILED, errors[0] 이 대표 문장과 같은 문장.
    OS 문장은 원인으로 고른다 (2026-11-09 사용자 결정): Linux + privilege_unavailable → serial_missing_sudo, 그 밖 → serial_missing.
  - rescue / H12 경로(failure_reason 있음): 문장 · stage · code · errors[] 는 그대로, status 만 failed. Serial 원인은
    diagnosis.details.serial_number 에만 남는다 — 같은 문장의 행을 하나 더 붙이지 않는다 (2026-11-09 사용자 결정 4).
  - 인증 단계(auth) · 사전 점검 실패 봉투는 건드리지 않는다.
  - 원인(details.serial_number.cause)은 식별자 진단 fragment 의 토큰과 sudo 결과로만 정한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "filter_plugins")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from errors_normalizer import normalize_errors  # noqa: E402
from failure_reason import failure_reason  # noqa: E402
from tests.unit.linux_raw_harness import ansible_env, load_tasks, render_tree  # noqa: E402

RULE = REPO / "os-gather" / "tasks" / "normalize" / "require_serial.yml"
CORE = REPO / "common" / "tasks" / "normalize" / "require_serial.yml"
FR = yaml.safe_load((REPO / "common" / "vars" / "failure_reasons.yml").read_text(encoding="utf-8"))
CATALOG = FR["_fr_catalog"]
SENTENCE = CATALOG["serial_missing"]["os"]            # OS 일반 문장
SENTENCE_SUDO = CATALOG["serial_missing_sudo"]["os"]  # Linux 가 sudo 권한을 얻지 못함
FIXTURE = REPO / "tests" / "fixtures" / "outputs" / "status_failed_serial_missing.json"

ENVELOPE_FIELDS = ("target_type", "collection_method", "ip", "hostname", "vendor", "status", "sections",
                   "diagnosis", "meta", "correlation", "errors", "data", "schema_version")


def _combine(a, *others):
    out = dict(a or {})
    for b in others:
        out.update(b or {})
    return out


def _env():
    env = ansible_env()
    env.filters.update({"combine": _combine, "normalize_errors": normalize_errors, "failure_reason": failure_reason})
    return env


_REPO_ROOT_TPL = "{{ lookup('env','REPO_ROOT') }}"


def _run_tasks(env, path: Path, ctx: dict[str, Any], params: dict[str, Any]) -> None:
    """태스크 파일을 적힌 순서대로 흉내 낸다 (task vars → when → set_fact / include_tasks).

    include_tasks 의 vars 는 include 인자다 — 포함된 파일 안에서 set_fact 보다 우선한다(Ansible 변수 우선순위). 그래서 인자는
    매 태스크 문맥의 맨 위에 다시 얹는다. 경로의 REPO_ROOT 는 저장소 경로로 바꾼다.
    """
    for task in load_tasks(path):
        local = dict(ctx)
        for key, value in (task.get("vars") or {}).items():
            try:
                local[key] = render_tree(env, value, {**local, **params})
            except Exception:  # noqa: BLE001 — Ansible 은 task vars 를 참조될 때 렌더한다; 못 그리는 var 는 없는 것과 같다
                pass
        local.update(params)
        conds = task.get("when")
        ok = True
        for cond in (conds if isinstance(conds, list) else ([conds] if conds is not None else [])):
            value = env.from_string("{{ " + str(cond) + " }}").render(**local)
            assert isinstance(value, bool), (cond, value)
            if not value:
                ok = False
                break
        if not ok:
            continue
        if "ansible.builtin.include_tasks" in task:
            inc = task["ansible.builtin.include_tasks"]
            target = (inc.get("file") if isinstance(inc, dict) else inc).replace(_REPO_ROOT_TPL, str(REPO))
            inner = dict(params)
            inner.update({k: local[k] for k in (task.get("vars") or {}) if k in local})
            _run_tasks(env, Path(target), ctx, inner)
            continue
        ctx.update({k: render_tree(env, v, local) for k, v in task["ansible.builtin.set_fact"].items()})


def run_rule(ctx: dict[str, Any], rule: Path = RULE, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """채널 규칙 파일(기본 OS wrapper)을 흉내 낸다 — 공통 규칙 include 까지 따라간다."""
    env = _env()
    ctx = dict(ctx)
    ctx.setdefault("_fr_catalog", CATALOG)
    _run_tasks(env, rule, ctx, dict(params or {}))
    return ctx


def envelope(serial, *, status="success", stage=None, code=None, reason=None, errors=None, os_type="linux"):
    sections = {"system": "success", "hardware": "success", "bmc": "not_supported", "cpu": "success", "memory": "success",
                "storage": "success", "network": "success", "firmware": "not_supported", "users": "success",
                "power": "not_supported", "thermal": "not_supported"}
    return {
        "target_type": "os", "collection_method": "agent", "ip": "10.0.0.5", "hostname": "db1", "vendor": "dell",
        "status": status, "sections": sections,
        "diagnosis": {"reachable": True, "port_open": True, "protocol_supported": True, "auth_success": True,
                      "failure_stage": stage, "failure_code": code, "failure_reason": reason,
                      "details": {"channel": "os", "detected_os": os_type, "hostname_source": "system",
                                  "auth": {"attempted_count": 1}}},
        "meta": {"started_at": "t0", "finished_at": "t1", "duration_ms": 5, "adapter_id": "linux_rhel", "adapter_version": None, "ansible_version": "x"},
        "correlation": {"serial_number": serial, "system_uuid": None, "bmc_ip": None, "host_ip": "10.0.0.5"},
        "errors": list(errors or []),
        "data": {"system": {"hostname": "db1", "serial_number": serial}, "hardware": {"vendor": "Dell Inc.", "serial": serial},
                 "cpu": {"sockets": 2}, "memory": {"total_mb": 65536}},
    }


DIAG_PRIV = [{"section": "system", "message": "시스템 제조번호를 읽을 수 없습니다. 수집 계정의 권한을 확인하세요.",
              "detail": "field=serial_number; cause=insufficient_privilege; tried=dmi_sysfs,become"}]
DIAG_ABSENT = [{"section": "system", "message": "대상이 시스템 제조번호를 제공하지 않습니다.",
                "detail": "field=serial_number; cause=identifier_not_available; tried=setup_fact,dmi_direct"}]
DIAG_FACTS = [{"section": "system", "message": "시스템 제조번호를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요.",
               "detail": "field=serial_number; cause=facts_failed; tried=setup_fact; error=x"}]


# ── Serial 이 있으면 불변 ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("serial", ["VMware-42 04 6c", "GSBPK54"])
def test_present_serial_leaves_the_envelope_untouched(serial):
    env = envelope(serial)
    out = run_rule({"_output": env, "_os_type": "linux", "_l_id_diagnostics": []})["_output"]
    assert out == envelope(serial)


@pytest.mark.parametrize("serial", [None, "", "   ", "To Be Filled By O.E.M.", "System Serial Number", "NA", "0"])
def test_missing_or_placeholder_serial_fails_the_host(serial):
    env = envelope(serial)
    out = run_rule({"_output": env, "_os_type": "linux", "_l_id_diagnostics": DIAG_PRIV, "_l_sudo_mode": "denied"})["_output"]
    assert out["status"] == "failed"


# ── 정상 경로 ──────────────────────────────────────────────────────────────────────────────────────
def test_normal_path_sets_failure_fields_and_representative_error_first():
    env = envelope(None, errors=DIAG_PRIV)
    out = run_rule({"_output": env, "_os_type": "linux", "_l_id_diagnostics": DIAG_PRIV, "_l_sudo_mode": "denied",
                    "_cred_location": "git"})["_output"]
    assert out["status"] == "failed"
    diag = out["diagnosis"]
    assert (diag["failure_stage"], diag["failure_code"], diag["failure_reason"]) == ("gather", "GATHER_FAILED", SENTENCE_SUDO)
    assert diag["auth_success"] is True and diag["details"]["hostname_source"] == "system" and diag["details"]["auth"] == {"attempted_count": 1}
    assert diag["details"]["serial_number"] == {"present": False, "cause": "privilege_unavailable", "sudo": "denied"}
    assert out["errors"][0]["message"] == SENTENCE_SUDO and out["errors"][0]["section"] == "linux_gather"
    assert out["errors"][0]["detail"] == "field=serial_number; mandatory=true; cause=privilege_unavailable; evidence=insufficient_privilege; sudo=denied"
    assert out["errors"][1:] == normalize_errors(DIAG_PRIV), "기존 섹션 오류는 뒤에 그대로"
    base = envelope(None, errors=DIAG_PRIV)
    for key in ("sections", "data", "hostname", "meta", "correlation", "ip", "vendor"):
        assert out[key] == base[key], key


def test_windows_uses_its_own_section_name_and_no_sudo():
    env = envelope(None, os_type="windows", errors=DIAG_FACTS)
    out = run_rule({"_output": env, "_os_type": "windows", "_w_id_diagnostics": DIAG_FACTS, "_l_sudo_mode": "denied"})["_output"]
    assert out["errors"][0]["section"] == "windows_gather"
    assert out["diagnosis"]["details"]["serial_number"] == {"present": False, "cause": "facts_failed", "sudo": None}
    assert out["errors"][0]["detail"] == "field=serial_number; mandatory=true; cause=facts_failed; evidence=facts_failed"


@pytest.mark.parametrize("diags,sudo,expected", [
    (DIAG_PRIV, "denied", "privilege_unavailable"),
    (DIAG_PRIV, "rejected", "privilege_unavailable"),
    (DIAG_PRIV, "unavailable", "privilege_unavailable"),
    (DIAG_PRIV, "", "privilege_unavailable"),
    (DIAG_PRIV, "nopasswd", "read_failed"),
    (DIAG_PRIV, "password", "read_failed"),
    (DIAG_PRIV, "root", "read_failed"),
    (DIAG_ABSENT, "nopasswd", "not_provided"),
    (DIAG_ABSENT, "denied", "not_provided"),
    ([{"section": "system", "message": "x.", "detail": "field=system_uuid; cause=insufficient_privilege"}], "denied", "unknown"),
])
def test_cause_matrix(diags, sudo, expected):
    out = run_rule({"_output": envelope(None), "_os_type": "linux", "_l_id_diagnostics": diags, "_l_sudo_mode": sudo})["_output"]
    assert out["diagnosis"]["details"]["serial_number"]["cause"] == expected


def test_no_diagnostics_at_all_means_not_collected():
    out = run_rule({"_output": envelope(None), "_os_type": "linux"})["_output"]
    assert out["diagnosis"]["details"]["serial_number"] == {"present": False, "cause": "not_collected", "sudo": None}
    assert out["errors"][0]["detail"] == "field=serial_number; mandatory=true; cause=not_collected"


# ── OS 문장 선택 (2026-11-09 사용자 결정 7) ──────────────────────────────────────────────────────────
DIAG_UUID_ONLY = [{"section": "system", "message": "x.", "detail": "field=system_uuid; cause=insufficient_privilege"}]


@pytest.mark.parametrize("os_type,diags,sudo,cause,sentence", [
    # sudo 권한을 얻지 못했다 — Linux 에서만 sudo 안내가 맞다
    ("linux", DIAG_PRIV, "denied", "privilege_unavailable", SENTENCE_SUDO),
    ("linux", DIAG_PRIV, "rejected", "privilege_unavailable", SENTENCE_SUDO),
    ("linux", DIAG_PRIV, "unavailable", "privilege_unavailable", SENTENCE_SUDO),
    ("linux", DIAG_PRIV, "", "privilege_unavailable", SENTENCE_SUDO),
    # sudo 는 됐다 / 대상이 주지 않았다 / 단계가 돌지 않았다 / 토큰 미상 — sudo 안내는 틀리다
    ("linux", DIAG_PRIV, "root", "read_failed", SENTENCE),
    ("linux", DIAG_PRIV, "nopasswd", "read_failed", SENTENCE),
    ("linux", DIAG_PRIV, "password", "read_failed", SENTENCE),
    ("linux", DIAG_ABSENT, "denied", "not_provided", SENTENCE),
    ("linux", None, "denied", "not_collected", SENTENCE),
    ("linux", DIAG_UUID_ONLY, "denied", "unknown", SENTENCE),
    # Windows 에는 sudo 가 없다 — 권한 토큰이어도 일반 문장
    ("windows", DIAG_PRIV, "denied", "privilege_unavailable", SENTENCE),
    ("windows", DIAG_FACTS, "", "facts_failed", SENTENCE),
    ("windows", DIAG_ABSENT, "", "not_provided", SENTENCE),
])
def test_os_sentence_follows_the_cause(os_type, diags, sudo, cause, sentence):
    ctx = {"_output": envelope(None, os_type=os_type, errors=diags or []), "_os_type": os_type, "_l_sudo_mode": sudo}
    if diags is not None:
        ctx["_l_id_diagnostics" if os_type == "linux" else "_w_id_diagnostics"] = diags
    out = run_rule(ctx)["_output"]
    assert out["diagnosis"]["details"]["serial_number"]["cause"] == cause
    assert out["diagnosis"]["failure_reason"] == sentence == out["errors"][0]["message"]
    other = SENTENCE if sentence == SENTENCE_SUDO else SENTENCE_SUDO
    assert other not in [e["message"] for e in out["errors"]]


@pytest.mark.parametrize("os_type", ["LINUX", "", None])
def test_sudo_sentence_needs_os_type_exactly_linux(os_type):
    """sudo 결과는 _os_type == 'linux' 일 때만 읽는다 — 원인 판정과 문장 선택이 같은 조건을 쓴다."""
    ctx = {"_output": envelope(None, errors=DIAG_PRIV), "_l_id_diagnostics": DIAG_PRIV, "_l_sudo_mode": "denied"}
    if os_type is not None:
        ctx["_os_type"] = os_type
    out = run_rule(ctx)["_output"]
    assert out["diagnosis"]["failure_reason"] == SENTENCE


@pytest.mark.parametrize("build", ["rescue_partial", "h12"])
def test_existing_reason_keeps_both_os_sentences_out(build):
    reason, env = {"rescue_partial": _rescue_partial, "h12": _h12}[build]()
    out = run_rule({"_output": env, "_os_type": "linux", "_l_id_diagnostics": DIAG_PRIV, "_l_sudo_mode": "denied"})["_output"]
    messages = [e["message"] for e in out["errors"]] + [out["diagnosis"]["failure_reason"]]
    assert SENTENCE not in messages and SENTENCE_SUDO not in messages
    assert out["diagnosis"]["details"]["serial_number"]["cause"] == "privilege_unavailable"


# ── rescue / H12 경로 (기존 사유 있음 — 결정 4: 행을 붙이지 않는다) ──────────────────────────────────────
def _rescue_partial():
    reason = CATALOG["gather_after_auth"]["os"]
    errors = [{"section": "linux_gather", "message": reason, "detail": "[task: x] boom"}] + DIAG_PRIV
    return reason, envelope(None, status="partial", stage="gather", code="GATHER_FAILED", reason=reason, errors=errors)


def _h12():
    reason = CATALOG["gather_no_data"]["default"]
    errors = [{"section": "linux_gather", "message": reason, "detail": "success_sections=0; supported=system,cpu; failed=system,cpu"},
              {"section": "cpu", "message": "CPU 정보 수집에 실패한 항목이 있습니다. 대상 상태와 수집 로그를 확인하세요.", "detail": "e0"}]
    env = envelope(None, status="failed", stage="gather", code="GATHER_FAILED", reason=reason, errors=errors)
    env["sections"] = {k: ("failed" if v == "success" else v) for k, v in env["sections"].items()}
    return reason, env


def test_rescue_partial_becomes_failed_but_keeps_its_reason_and_errors():
    reason, env = _rescue_partial()
    out = run_rule({"_output": env, "_os_type": "linux", "_l_id_diagnostics": DIAG_PRIV, "_l_sudo_mode": "rejected"})["_output"]
    assert out["status"] == "failed"
    diag = out["diagnosis"]
    assert (diag["failure_stage"], diag["failure_code"], diag["failure_reason"]) == ("gather", "GATHER_FAILED", reason)
    assert out["errors"] == env["errors"], "기존 행 그대로 — Serial 행을 붙이지 않는다"
    assert diag["details"]["serial_number"] == {"present": False, "cause": "privilege_unavailable", "sudo": "rejected"}


def test_h12_gather_no_data_keeps_its_sentence_and_errors():
    reason, env = _h12()
    out = run_rule({"_output": env, "_os_type": "linux"})["_output"]
    assert out["status"] == "failed"
    assert out["diagnosis"]["failure_reason"] == reason
    assert out["errors"] == env["errors"]
    assert out["diagnosis"]["details"]["serial_number"] == {"present": False, "cause": "not_collected", "sudo": None}


@pytest.mark.parametrize("build", [_rescue_partial, _h12], ids=["rescue_partial", "h12"])
def test_existing_reason_is_never_repeated_and_nothing_else_moves(build):
    """사용자 지적(2026-11-09): 기존 오류와 Serial 누락이 겹칠 때 같은 문장이 두 줄이 되거나 원인을 다르게 전하지 않는다."""
    reason, env = build()
    out = run_rule({"_output": env, "_os_type": "linux", "_l_id_diagnostics": DIAG_PRIV, "_l_sudo_mode": "denied"})["_output"]
    assert [e["message"] for e in out["errors"]].count(reason) == 1
    assert out["errors"][0]["message"] == out["diagnosis"]["failure_reason"] == reason
    assert not [e for e in out["errors"] if "mandatory=true" in str(e.get("detail"))]
    for key in ("sections", "data", "hostname", "meta", "correlation", "ip", "vendor", "target_type", "collection_method"):
        assert out[key] == env[key], key
    before = {k: v for k, v in env["diagnosis"]["details"].items()}
    after = {k: v for k, v in out["diagnosis"]["details"].items() if k != "serial_number"}
    assert after == before, "details 는 serial_number 하나만 더해진다"


@pytest.mark.parametrize("stage,code,key", [
    ("auth", "CREDENTIAL_SET_UNAVAILABLE", "loc_vault_missing"),
    ("auth", "AUTH_PROBE_FAILED", "auth_unconfirmed"),
    ("port", "TCP_CONNECTION_REFUSED", "port_refused"),
])
def test_pre_gather_failures_are_left_alone(stage, code, key):
    reason = CATALOG[key].get("os") or CATALOG[key]["default"]
    env = envelope(None, status="failed", stage=stage, code=code, reason=reason,
                   errors=[{"section": "auth", "message": reason, "detail": None}])
    out = run_rule({"_output": env, "_os_type": "linux"})["_output"]
    assert out == env
    assert "serial_number" not in out["diagnosis"]["details"]


def test_rule_never_fails_without_an_output():
    assert "_output" not in run_rule({"_os_type": "linux"})
    out = run_rule({"_output": "not a mapping", "_os_type": "linux"})["_output"]
    assert out == "not a mapping"


# ── Redfish · ESXi (2026-11-09 사용자 결정 — 시나리오 E 를 3채널로) ───────────────────────────────────
REDFISH_RULE = REPO / "redfish-gather" / "tasks" / "require_serial.yml"
CHANNELS = ("redfish", "esxi")
CH_SECTIONS = {
    "redfish": {"system": "not_supported", "hardware": "success", "bmc": "success", "cpu": "success", "memory": "success",
                "storage": "success", "network": "success", "firmware": "success", "users": "not_supported",
                "power": "success", "thermal": "success"},
    "esxi": {"system": "success", "hardware": "success", "bmc": "not_supported", "cpu": "success", "memory": "success",
             "storage": "success", "network": "success", "firmware": "not_supported", "users": "not_supported",
             "power": "success", "thermal": "success"},
}
CPU_ROW = {"section": "cpu", "message": "CPU 정보 수집에 실패한 항목이 있습니다. 대상 상태와 수집 로그를 확인하세요.", "detail": "e0"}
PRESERVED = ("sections", "data", "hostname", "meta", "correlation", "ip", "vendor", "target_type", "collection_method")
NORMAL = {"redfish": {"_rf_collect_ok": True}, "esxi": {}}   # 정상 경로 — Redfish 는 수집이 성공해야 build_output 에 닿는다


def fr(key, channel):
    return failure_reason(CATALOG, key, channel, "ic")


def ch_envelope(channel, serial, **kw):
    env = envelope(serial, **kw)
    env.update({"target_type": channel, "collection_method": {"redfish": "redfish_api", "esxi": "vsphere_api"}[channel],
                "sections": dict(CH_SECTIONS[channel])})
    env["diagnosis"]["details"] = {"channel": channel, "hostname_source": "system"}
    return env


def run_channel(channel, env, **extra):
    """site.yml 이 부르는 그대로 — Redfish 는 wrapper(BMC 를 읽은 결과만), ESXi 는 공통 규칙에 _rs_channel=esxi."""
    ctx = {"_output": env, **extra}
    if channel == "redfish":
        return run_rule(ctx, rule=REDFISH_RULE)["_output"]
    return run_rule(ctx, rule=CORE, params={"_rs_channel": "esxi"})["_output"]


def _all_failed(sections):
    return {k: ("failed" if v == "success" else v) for k, v in sections.items()}


def channel_case(channel, path):
    """(env, extra) — C1 정상 · C2 hardware 실패 partial · C3 H12 · C4 인증 뒤 rescue."""
    if path == "c1":
        return ch_envelope(channel, None), dict(NORMAL[channel])
    if path == "c2":
        env = ch_envelope(channel, None, status="partial", errors=[CPU_ROW])
        env["sections"]["hardware"] = "failed"
        return env, dict(NORMAL[channel])
    if path == "c3":
        reason = fr("gather_no_data", channel)
        rep = {"section": f"{channel}_gather", "message": reason, "detail": "success_sections=0; supported=x; failed=x"}
        env = ch_envelope(channel, None, status="failed", stage="gather", code="GATHER_FAILED", reason=reason, errors=[rep, CPU_ROW])
        env["sections"] = _all_failed(env["sections"])
        return env, dict(NORMAL[channel])
    if path == "c4":
        reason = fr("gather_after_auth", channel)
        env = ch_envelope(channel, None, status="partial", stage="gather", code="GATHER_FAILED", reason=reason,
                          errors=[{"section": f"{channel}_gather", "message": reason, "detail": "[task: x] boom"}])
        return env, {}   # rescue — Redfish 는 _rf_collect_ok 없이 auth_success=true(자격 관측 passed)로만 대상이 된다
    raise ValueError(path)


@pytest.mark.parametrize("channel", CHANNELS)
def test_c1_success_without_serial_fails_with_the_channel_sentence(channel):
    env, extra = channel_case(channel, "c1")
    out = run_channel(channel, env, **extra)
    sentence = CATALOG["serial_missing"][channel]
    assert out["status"] == "failed"
    diag = out["diagnosis"]
    assert (diag["failure_stage"], diag["failure_code"], diag["failure_reason"]) == ("gather", "GATHER_FAILED", sentence)
    assert out["errors"] == normalize_errors([{"section": f"{channel}_gather", "message": sentence,
                                               "detail": "field=serial_number; mandatory=true; cause=not_provided"}])
    assert diag["details"]["serial_number"] == {"present": False, "cause": "not_provided", "sudo": None}
    for key in PRESERVED:
        assert out[key] == env[key], key


@pytest.mark.parametrize("channel", CHANNELS)
def test_c2_failed_hardware_keeps_its_own_row_after_the_serial_row(channel):
    env, extra = channel_case(channel, "c2")
    out = run_channel(channel, env, **extra)
    assert out["status"] == "failed"
    assert out["errors"][0]["message"] == CATALOG["serial_missing"][channel] == out["diagnosis"]["failure_reason"]
    assert out["errors"][0]["detail"] == "field=serial_number; mandatory=true; cause=not_collected"
    assert out["errors"][1:] == normalize_errors([CPU_ROW]), "실제 원인 행은 그대로 남는다"
    assert out["diagnosis"]["details"]["serial_number"] == {"present": False, "cause": "not_collected", "sudo": None}


@pytest.mark.parametrize("channel", CHANNELS)
@pytest.mark.parametrize("path", ["c3", "c4"])
def test_c3_c4_existing_reason_keeps_its_sentence_and_rows(channel, path):
    env, extra = channel_case(channel, path)
    if path == "c4":
        env["diagnosis"]["auth_success"] = True
    out = run_channel(channel, env, **extra)
    assert out["status"] == "failed"
    assert out["errors"] == env["errors"]
    for key in ("failure_stage", "failure_code", "failure_reason", "auth_success"):
        assert out["diagnosis"][key] == env["diagnosis"][key], key
    cause = "not_collected" if path == "c3" else "not_provided"
    assert out["diagnosis"]["details"]["serial_number"] == {"present": False, "cause": cause, "sudo": None}


@pytest.mark.parametrize("outcome_key,auth_success", [("gather_internal", None), ("gather_internal", False)])
@pytest.mark.parametrize("collect_ok", [None, False])
def test_c5_redfish_rescue_that_never_read_the_bmc_is_left_alone(outcome_key, auth_success, collect_ok):
    """stopped_before_auth · not_attempted — stage 는 gather 지만 계정 요청을 보내기 전에 멈췄다 (redfish-gather/site.yml rescue)."""
    reason = fr(outcome_key, "redfish")
    env = ch_envelope("redfish", None, status="failed", stage="gather", code="GATHER_FAILED", reason=reason,
                      errors=[{"section": "redfish_gather", "message": reason, "detail": "[task: x] boom"}])
    env["diagnosis"]["auth_success"] = auth_success
    env["sections"] = _all_failed(env["sections"])
    extra = {} if collect_ok is None else {"_rf_collect_ok": collect_ok}
    assert run_channel("redfish", env, **extra) == env


_PRE_GATHER = [
    ("auth", "AUTH_PROBE_FAILED", "auth_unconfirmed"),
    ("auth", "AUTH_PROBE_FAILED", "auth_rejected"),
    ("auth", "CREDENTIAL_SET_UNAVAILABLE", "project_vault_missing"),
    ("auth", "CREDENTIAL_SET_UNAVAILABLE", "loc_vault_missing"),
    ("port", "TCP_CONNECTION_REFUSED", "port_refused"),
    ("port", "TCP_CONNECT_FAILED", "port_silent"),
    ("reachable", "TARGET_UNREACHABLE", "target_unreachable"),
    ("protocol", "PROTOCOL_CHECK_FAILED", "protocol_unconfirmed"),
]


@pytest.mark.parametrize("channel,stage,code,key", [
    (ch, *row) for ch in CHANNELS for row in _PRE_GATHER
    if ch in CATALOG[row[2]] or "default" in CATALOG[row[2]]])   # 그 채널이 실제로 낼 수 있는 문장만
def test_c6_pre_gather_failures_are_left_alone_on_every_channel(channel, stage, code, key):
    reason = fr(key, channel)
    env = ch_envelope(channel, None, status="failed", stage=stage, code=code, reason=reason,
                      errors=[{"section": f"{channel}_gather", "message": reason, "detail": None}])
    env["sections"] = _all_failed(env["sections"])
    # Redfish 는 수집 성공 표시가 있어도 stage 조건만으로 막힌다 (ESXi 는 stage 조건이 유일한 문이다)
    assert run_channel(channel, env, **NORMAL[channel]) == env


@pytest.mark.parametrize("channel", CHANNELS)
@pytest.mark.parametrize("serial", ["GSBPK54", "VMware-42 04 6c c9", "SGHD3TLNDD", "CZ2D1F0BJT"])
def test_c7_present_serial_leaves_the_envelope_untouched(channel, serial):
    assert run_channel(channel, ch_envelope(channel, serial), **NORMAL[channel]) == ch_envelope(channel, serial)


@pytest.mark.parametrize("channel", CHANNELS)
@pytest.mark.parametrize("serial", ["N/A", "NA", "", "   ", "To Be Filled By O.E.M.", "0", "00000000"])
def test_placeholder_serial_is_missing_on_every_channel(channel, serial):
    out = run_channel(channel, ch_envelope(channel, serial), **NORMAL[channel])
    assert out["status"] == "failed" and out["diagnosis"]["failure_reason"] == CATALOG["serial_missing"][channel]


@pytest.mark.parametrize("collect_ok,auth_success,fires", [
    (True, True, True), (True, None, True), (None, True, True), (False, True, True),
    (False, None, False), (None, None, False), (False, False, False), (None, "true", False),
])
def test_redfish_rule_applies_only_when_the_bmc_was_actually_read(collect_ok, auth_success, fires):
    env = ch_envelope("redfish", None)
    env["diagnosis"]["auth_success"] = auth_success
    out = run_channel("redfish", env, **({} if collect_ok is None else {"_rf_collect_ok": collect_ok}))
    assert (out["status"] == "failed") is fires
    if not fires:
        assert out == env


@pytest.mark.parametrize("channel", CHANNELS)
def test_channels_never_borrow_each_others_sentence(channel):
    out = run_channel(channel, ch_envelope(channel, None), **NORMAL[channel])
    others = [CATALOG["serial_missing"][c] for c in ("os", "esxi", "redfish") if c != channel] + [SENTENCE_SUDO]
    shown = {e["message"] for e in out["errors"]} | {out["diagnosis"]["failure_reason"]}
    assert not (set(others) & shown), set(others) & shown


def _os_case(path):
    if path == "c1":
        return envelope(None, errors=DIAG_PRIV), {"_os_type": "linux", "_l_id_diagnostics": DIAG_PRIV, "_l_sudo_mode": "denied"}
    if path == "c2":
        env = envelope(None, status="partial", errors=DIAG_PRIV + [CPU_ROW])
        env["sections"]["cpu"] = "failed"
        return env, {"_os_type": "linux", "_l_id_diagnostics": DIAG_PRIV, "_l_sudo_mode": "rejected"}
    if path == "c3":
        return _h12()[1], {"_os_type": "linux"}
    return _rescue_partial()[1], {"_os_type": "windows", "_w_id_diagnostics": DIAG_PRIV}


@pytest.mark.parametrize("channel", ("os",) + CHANNELS)
@pytest.mark.parametrize("path", ["c1", "c2", "c3", "c4"])
def test_invariants_on_every_channel_and_path(channel, path):
    """사용자 검증 요구(2026-11-09): 중복 · 오전달 없음 — 3채널 · 4경로 공통 불변식."""
    if channel == "os":
        env, extra = _os_case(path)
        out = run_rule({"_output": env, **extra})["_output"]
    else:
        env, extra = channel_case(channel, path)
        if path == "c4":
            env["diagnosis"]["auth_success"] = True
        out = run_channel(channel, env, **extra)
    diag, had_reason = out["diagnosis"], bool((env["diagnosis"]["failure_reason"] or "").strip())
    # 1) failed 봉투의 첫 행은 대표 문장이고 stage · code · reason 이 모두 있다
    assert out["status"] == "failed"
    assert diag["failure_stage"] and diag["failure_code"] and diag["failure_reason"]
    assert out["errors"][0]["message"] == diag["failure_reason"]
    # 2) 규칙은 이미 있는 문장을 다시 넣지 않는다 — 새 행은 사유가 없던 결과의 Serial 행 1개뿐
    before = [e["message"] for e in normalize_errors(env["errors"])]
    after = [e["message"] for e in out["errors"]]
    added = list(after)
    for m in before:
        added.remove(m)
    assert added == ([] if had_reason else [diag["failure_reason"]]), added
    assert after.count(diag["failure_reason"]) == 1
    # 3) 기존 사유는 그대로 — 원인을 바꿔 말하지 않는다
    if had_reason:
        assert diag["failure_reason"] == env["diagnosis"]["failure_reason"] and out["errors"] == env["errors"]
    # 4) 수집 값 · 식별 필드는 보존
    for key in PRESERVED:
        assert out[key] == env[key], key
    assert diag["details"]["serial_number"]["present"] is False


# ── 배선: build_output.yml 의 include 경로 (2026-10-13 CI #53) ─────────────────────────────────────
def test_build_output_includes_the_rule_from_repo_root_not_playbook_dir():
    """os-gather/tasks/normalize/build_output.yml 은 다른 playbook(tests/fixtures/addon/harness.yml)도 include 한다 —
    그 안의 include 는 playbook_dir 가 아니라 REPO_ROOT 기준이어야 한다 (CI #53 Gate: add-on 통합 시험 15건 ERROR, Windows 에서는 skip 되는 시험)."""
    tasks = yaml.safe_load((REPO / "os-gather" / "tasks" / "normalize" / "build_output.yml").read_text(encoding="utf-8"))
    includes = [t["ansible.builtin.include_tasks"] for t in tasks if isinstance(t, dict) and "ansible.builtin.include_tasks" in t]
    targets = [i if isinstance(i, str) else i.get("file", "") for i in includes]
    rule = [t for t in targets if "require_serial.yml" in t]
    assert len(rule) == 1, targets
    assert "lookup('env','REPO_ROOT')" in rule[0]
    assert not [t for t in targets if "playbook_dir" in t], targets


# 공통 규칙의 입력 이름 — wrapper 도 공통 규칙도 이 이름을 set_fact 하지 않는다 (include 인자가 set_fact 보다 우선해 가려진다)
CORE_INPUTS = {"_rs_channel", "_rs_error_section", "_rs_cause", "_rs_detail_extra", "_rs_sudo", "_rs_reason_key", "_rs_eligible"}


def test_os_wrapper_includes_the_common_rule_from_repo_root():
    tasks = yaml.safe_load(RULE.read_text(encoding="utf-8"))
    incs = [t for t in tasks if isinstance(t, dict) and "ansible.builtin.include_tasks" in t]
    assert len(incs) == 1
    assert incs[0]["ansible.builtin.include_tasks"]["file"] == \
        "{{ lookup('env','REPO_ROOT') }}/common/tasks/normalize/require_serial.yml"
    assert incs[0]["vars"]["_rs_channel"] == "os"
    for path in (RULE, CORE, REDFISH_RULE):
        for t in yaml.safe_load(path.read_text(encoding="utf-8")):
            assert not (set(t.get("ansible.builtin.set_fact") or {}) & CORE_INPUTS), (path.name, t.get("name"))


def test_redfish_wrapper_includes_the_common_rule_from_repo_root():
    tasks = yaml.safe_load(REDFISH_RULE.read_text(encoding="utf-8"))
    assert len(tasks) == 1 and "ansible.builtin.include_tasks" in tasks[0]
    assert tasks[0]["ansible.builtin.include_tasks"]["file"] == \
        "{{ lookup('env','REPO_ROOT') }}/common/tasks/normalize/require_serial.yml"
    assert tasks[0]["vars"]["_rs_channel"] == "redfish" and "_rs_eligible" in tasks[0]["vars"]


def _task_lists(node):
    """playbook 안의 모든 태스크 목록(tasks · block · rescue · always) — 이웃 관계를 보려고 목록 단위로 낸다."""
    if isinstance(node, list):
        if node and all(isinstance(t, dict) for t in node):
            yield node
        for item in node:
            yield from _task_lists(item)
    elif isinstance(node, dict):
        for value in node.values():
            yield from _task_lists(value)


def _include_target(task):
    inc = task.get("ansible.builtin.include_tasks")
    return (inc.get("file") if isinstance(inc, dict) else inc) if inc else None


@pytest.mark.parametrize("channel,target,params", [
    ("redfish", "{{ lookup('env','REPO_ROOT') }}/redfish-gather/tasks/require_serial.yml", None),
    ("esxi", "{{ lookup('env','REPO_ROOT') }}/common/tasks/normalize/require_serial.yml", {"_rs_channel": "esxi"}),
])
def test_site_calls_the_rule_right_before_every_schema_version_injection(channel, target, params):
    """정상 경로 · rescue 모두 build_output / build_failed_output → require_serial → inject schema_version (→ CHECKPOINT) 순서다.

    CHECKPOINT 보다 뒤에 두면 콜백 · Layer A 가 Serial 판정 전 status 를 복원한다. REPO_ROOT 기준 경로(2026-10-13 CI #53)."""
    plays = yaml.safe_load((REPO / f"{channel}-gather" / "site.yml").read_text(encoding="utf-8"))
    hits = 0
    for tasks in _task_lists(plays):
        for i, task in enumerate(tasks):
            if not str(task.get("name", "")).endswith("inject schema_version"):
                continue
            prev, before = tasks[i - 1], tasks[i - 2]
            assert _include_target(prev) == target, (task["name"], prev.get("name"))
            assert prev.get("vars") == params, (task["name"], prev.get("vars"))
            assert (_include_target(before) or "").endswith(("/build_output.yml", "/build_failed_output.yml")), task["name"]
            hits += 1
    assert hits == 2, hits


# ── fixture (synthetic) ────────────────────────────────────────────────────────────────────────────
def _section_only_status(sections: dict[str, str]) -> str:
    supported = [v for v in sections.values() if v != "not_supported"]
    if not supported:
        return "failed"
    if not any(v == "failed" for v in supported):
        return "success"
    if not any(v == "success" for v in supported):
        return "failed"
    return "partial"


def test_fixture_documents_scenario_e():
    env = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert all(f in env for f in ENVELOPE_FIELDS)
    assert env["status"] == "failed"
    assert _section_only_status(env["sections"]) == "success", "섹션만 보면 success — E 는 섹션 규칙 위에 얹힌 유일한 예외다"
    assert env["correlation"]["serial_number"] is None
    assert env["diagnosis"]["failure_code"] == "GATHER_FAILED" and env["diagnosis"]["failure_stage"] == "gather"
    # Linux · sudo 를 얻지 못함(denied) → sudo 문장 (2026-11-09 사용자 결정 7)
    assert env["diagnosis"]["details"]["serial_number"] == {"present": False, "cause": "privilege_unavailable", "sudo": "denied"}
    assert env["diagnosis"]["failure_reason"] == SENTENCE_SUDO == env["errors"][0]["message"]
    assert env["diagnosis"]["details"]["sudo"]["mode"] in {"denied", "rejected", "unavailable"}
    assert all(e["message"] for e in env["errors"])
    assert env["data"]["cpu"] is not None, "다른 섹션 데이터는 보존된다"
