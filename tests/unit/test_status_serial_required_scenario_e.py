"""status 시나리오 E — OS 채널 필수 식별자(Serial Number) 누락은 failed (2026-10-13 사용자 정책).

정본: os-gather/tasks/normalize/require_serial.yml (조립된 _output 후처리). build_status.yml 의 섹션 기반 판정(A/B/C/D)은 그대로이고,
E 는 그 위에 OS 채널에서만 얹힌다 — 다른 섹션의 수집 값(data) · sections · hostname · meta · correlation 은 보존한다.

무엇을 고정하나
  - Serial 이 있으면 아무것도 바꾸지 않는다. 빈 문자열 · 자리표시자는 누락이다.
  - 정상 경로(failure_reason 없음): status=failed, stage=gather, code=GATHER_FAILED, 문장=serial_missing(카탈로그), errors[0] 이 같은 문장.
  - rescue / H12 경로(failure_reason 있음): 문장 · errors[0] 은 그대로, status 만 failed, Serial 오류는 뒤에 붙는다.
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
FR = yaml.safe_load((REPO / "common" / "vars" / "failure_reasons.yml").read_text(encoding="utf-8"))
CATALOG = FR["_fr_catalog"]
SENTENCE = CATALOG["serial_missing"]["os"]
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


def run_rule(ctx: dict[str, Any]) -> dict[str, Any]:
    """require_serial.yml 을 적힌 순서대로 흉내 낸다 (task vars → when → set_fact)."""
    env = _env()
    ctx = dict(ctx)
    ctx.setdefault("_fr_catalog", CATALOG)
    for task in load_tasks(RULE):
        local = dict(ctx)
        for key, value in (task.get("vars") or {}).items():
            try:
                local[key] = render_tree(env, value, local)
            except Exception:  # noqa: BLE001 — Ansible 은 task vars 를 참조될 때 렌더한다; 못 그리는 var 는 없는 것과 같다
                pass
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
        ctx.update({k: render_tree(env, v, local) for k, v in task["ansible.builtin.set_fact"].items()})
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
    assert (diag["failure_stage"], diag["failure_code"], diag["failure_reason"]) == ("gather", "GATHER_FAILED", SENTENCE)
    assert diag["auth_success"] is True and diag["details"]["hostname_source"] == "system" and diag["details"]["auth"] == {"attempted_count": 1}
    assert diag["details"]["serial_number"] == {"present": False, "cause": "privilege_unavailable", "sudo": "denied"}
    assert out["errors"][0]["message"] == SENTENCE and out["errors"][0]["section"] == "linux_gather"
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


# ── rescue / H12 경로 ──────────────────────────────────────────────────────────────────────────────
def test_rescue_partial_becomes_failed_but_keeps_its_reason_and_first_error():
    reason = CATALOG["gather_after_auth"]["os"]
    rescue_errors = [{"section": "linux_gather", "message": reason, "detail": "[task: x] boom"}]
    env = envelope(None, status="partial", stage="gather", code="GATHER_FAILED", reason=reason, errors=rescue_errors)
    out = run_rule({"_output": env, "_os_type": "linux", "_l_id_diagnostics": DIAG_PRIV, "_l_sudo_mode": "rejected"})["_output"]
    assert out["status"] == "failed"
    assert out["diagnosis"]["failure_reason"] == reason and out["diagnosis"]["failure_code"] == "GATHER_FAILED"
    assert out["errors"][0] == normalize_errors(rescue_errors)[0]
    assert out["errors"][-1]["message"] == reason and "cause=privilege_unavailable" in out["errors"][-1]["detail"]
    assert out["diagnosis"]["details"]["serial_number"]["cause"] == "privilege_unavailable"


def test_h12_gather_no_data_keeps_its_sentence():
    reason = CATALOG["gather_no_data"]["default"]
    env = envelope(None, status="failed", stage="gather", code="GATHER_FAILED", reason=reason)
    out = run_rule({"_output": env, "_os_type": "linux"})["_output"]
    assert out["diagnosis"]["failure_reason"] == reason and out["errors"][-1]["message"] == reason


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
    assert env["diagnosis"]["failure_reason"] == SENTENCE == env["errors"][0]["message"]
    assert env["diagnosis"]["details"]["serial_number"]["present"] is False
    assert env["diagnosis"]["details"]["sudo"]["mode"] in {"denied", "rejected", "unavailable"}
    assert all(e["message"] for e in env["errors"])
    assert env["data"]["cpu"] is not None, "다른 섹션 데이터는 보존된다"
