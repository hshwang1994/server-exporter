"""Redfish task timeout(backstop) 뒤 인증 3분류 — rescue 렌더 (Plan §6-3 D7 · Astra 3차 acceptance, 2026-10-03).

모듈이 task `timeout` 으로 끊기면 register 가 없다. rescue 는 **현재 attempt 의 증거 파일만** 읽어
    ① 자격 401            → 관측에 넣어 기존 "표준 후보 전원 401" 규칙으로 rejected / unknown (auth 단계, 기존대로)
    ② 자격 2xx 뒤 정지    → passed: gather / GATHER_FAILED / auth_success true / gather_after_auth
    ③ 증거 없음 · null · 익명 · 식별자 불일치 → stopped_before_auth: gather / GATHER_FAILED / auth_success null / gather_internal
로 가른다. 과거 attempt 의 401 은 현재 시도를 분류하지 않고, 복구 계정 시도(account-*)의 정지는 표준 관측을 건드리지 않는다.
표준 계정 시도가 timeout 으로 끝나면 recovery 에 들어가지 않는다 (rescue 안에 recovery 가 없다 — 구조 단언).

렌더는 tests/e2e/test_failure_reason_contract.py 의 NativeEnvironment 를 그대로 쓰고, 증거 파일 해석은
filter_plugins/auth_evidence.py 의 실제 함수로 한다 (lookup 만 테스트가 대신한다 — 파일 I/O 는 unit 테스트가 덮는다).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.e2e.test_failure_reason_contract import (  # noqa: E402
    _env, _task_by_name, _render_diagnosis, fr, FAILURE_REASONS, _RF_OUTCOME_TASK, _RF_DIAG_TASK,
)

REPO = Path(__file__).resolve().parents[2]
SITE = "redfish-gather/site.yml"
_BACKSTOP_TASK = "redfish | rescue | backstop 관측 반영"
_EVIDENCE_TASK = "redfish | rescue | backstop 증거 (현재 attempt 파일만)"
_REJECT_TASK = "redfish | rescue | 인증 거부 실증 판정"

_spec = importlib.util.spec_from_file_location("auth_evidence_filter", REPO / "filter_plugins" / "auth_evidence.py")
_filt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_filt)
parse_auth_evidence = _filt.parse_auth_evidence

IP = "192.0.2.60"
IDS = {"build_id": "jenkins-main-12", "event_uuid": "evt-1"}
_PRECHECK_OK = {"reachable": True, "port_open": True, "protocol_supported": True, "auth_success": None,
                "failure_stage": None, "failure_code": None, "failure_reason": None, "details": {"channel": "redfish"}}


def _file(attempt_id, status, auth_mode="credentialed", label="standard", role="primary", **over):
    data = {"schema": 1, **IDS, "ip": IP, "attempt_id": attempt_id, "label": label, "role": role,
            "auth_mode": auth_mode, "first_auth_status": status, "first_auth_at": None, "started_at": "t",
            "updated_at": "t", "requests_sent": 4, "last_request": "Systems/System.Embedded.1"}
    data.update(over)
    return json.dumps(data)


def _render_set_fact(task_name: str, ctx: dict[str, Any]) -> dict[str, Any]:
    sf = _task_by_name(SITE, task_name)["ansible.builtin.set_fact"]
    env = _env()
    out = {}
    for key, tpl in sf.items():
        val = env.from_string(tpl).render(**{**FAILURE_REASONS, **ctx, **out})
        out[key] = val.strip() if isinstance(val, str) else val
    return out


def _classify(current_attempt: str | None, raw_file: str | None, *, prior_obs=(), prior_statuses=(),
              standard_accounts=1, collect_ok=False, expect_attempt_id=None):
    """rescue 순서대로: (증거 해석) → backstop 관측 반영 → 거부 판정 → outcome → diagnosis."""
    ctx: dict[str, Any] = {
        "_rf_ip": IP, "_rf_collect_ok": collect_ok,
        "_rf_auth_observations": list(prior_obs), "_rf_auth_statuses": list(prior_statuses),
        "_rf_failed_attempt_notes": [], "_rf_standard_accounts": [{} for _ in range(standard_accounts)],
        "_rf_attempt_id": current_attempt or "", "_diagnosis": dict(_PRECHECK_OK),
    }
    if current_attempt:
        ctx["_rf_backstop_evidence"] = parse_auth_evidence(
            raw_file, {**IDS, "ip": IP, "attempt_id": expect_attempt_id or current_attempt})
        ctx.update(_render_set_fact(_BACKSTOP_TASK, ctx))
    ctx.update(_render_set_fact(_REJECT_TASK, ctx))
    # rescue 와 같은 순서: 관측 확정(_rf_auth_outcome) → diagnosis 4필드 파생 (tests/e2e/test_failure_reason_contract.py 와 동일 렌더)
    tpl = _task_by_name(SITE, _RF_OUTCOME_TASK)["ansible.builtin.set_fact"]["_rf_auth_outcome"]
    ctx["_rf_auth_outcome"] = str(_env().from_string(tpl).render(**{**FAILURE_REASONS, **ctx})).strip()
    diag = _render_diagnosis(SITE, _RF_DIAG_TASK, ctx)
    return ctx, diag


def _assert_outcome(diag, stage, code, auth, key, label=""):
    assert diag["failure_stage"] == stage, label
    assert diag["failure_code"] == code, label
    assert diag["auth_success"] is auth, label
    assert diag["failure_reason"] == fr(key, "redfish"), label


# ── 세 경우 ─────────────────────────────────────────────────────────────────
def test_current_attempt_401_feeds_the_existing_rejected_rule():
    ctx, diag = _classify("collect-1-1", _file("collect-1-1", 401))
    assert ctx["_rf_backstop_class"] == "auth_rejected"
    assert ctx["_rf_auth_statuses"] == [401] and ctx["_rf_auth_observations"][-1]["status"] == 401
    assert ctx["_rf_auth_rejected"] is True, "표준 후보 1벌이 401 → 기존 규칙으로 rejected"
    _assert_outcome(diag, "auth", "AUTH_PROBE_FAILED", False, "auth_rejected")
    assert "status=task_timeout first_auth=401" in ctx["_rf_failed_attempt_notes"][-1]


def test_current_attempt_200_then_stop_is_gather_failed_with_auth_true():
    ctx, diag = _classify("collect-1-1", _file("collect-1-1", 200))
    assert ctx["_rf_backstop_class"] == "auth_passed"
    _assert_outcome(diag, "gather", "GATHER_FAILED", True, "gather_after_auth")
    note = ctx["_rf_failed_attempt_notes"][-1]
    assert "task timeout after auth" in note and "last_request=Systems/System.Embedded.1" in note


@pytest.mark.parametrize("raw,why", [
    (None, "missing"),
    (_file("collect-1-1", None), "ok"),                          # 시작은 했지만 자격 응답 전 정지
    (_file("collect-1-1", 200, auth_mode="anonymous"), "ok"),    # 익명 200 은 인증 성공이 아니다
    ("{broken", "corrupt"),
], ids=["no-file", "status-null", "anonymous-200", "corrupt"])
def test_no_credentialed_evidence_is_stopped_before_auth(raw, why):
    ctx, diag = _classify("collect-1-1", raw)
    assert ctx["_rf_backstop_class"] == "before_auth"
    assert ctx["_rf_auth_statuses"] == [] and ctx["_rf_auth_observations"] == [], "증거 없음은 관측이 아니다"
    assert ctx["_rf_auth_outcome"] == "stopped_before_auth"
    _assert_outcome(diag, "gather", "GATHER_FAILED", None, "gather_internal")
    assert f"task timeout before auth evidence ({why})" in ctx["_rf_failed_attempt_notes"][-1]


# ── 격리: 다른 attempt · 식별자 불일치 ────────────────────────────────────────
def test_stale_401_of_another_attempt_does_not_classify_the_current_one():
    """현재 attempt 는 collect-1-2 인데 디스크에는 collect-1-1 의 401 만 있다 → 증거 없음."""
    ctx, diag = _classify("collect-1-2", _file("collect-1-1", 401))
    assert ctx["_rf_backstop_evidence"]["reason"] == "mismatch:attempt_id"
    assert ctx["_rf_auth_outcome"] == "stopped_before_auth"
    _assert_outcome(diag, "gather", "GATHER_FAILED", None, "gather_internal")


@pytest.mark.parametrize("key,value", [("build_id", "jenkins-main-11"), ("event_uuid", "evt-0"), ("ip", "192.0.2.61")])
def test_identifier_mismatch_is_no_evidence(key, value):
    ctx, diag = _classify("collect-1-1", _file("collect-1-1", 401, **{key: value}))
    assert ctx["_rf_backstop_evidence"]["valid"] is False and ctx["_rf_backstop_evidence"]["reason"] == f"mismatch:{key}"
    _assert_outcome(diag, "gather", "GATHER_FAILED", None, "gather_internal")


# ── 후보 교체 ────────────────────────────────────────────────────────────────
def test_a_401_then_b_200_then_stop_is_passed():
    prior = [{"role": "primary", "label": "A", "status": 401}]
    ctx, diag = _classify("collect-2-2", _file("collect-2-2", 200, label="B", role="secondary"),
                          prior_obs=prior, prior_statuses=[401], standard_accounts=2)
    assert [o["status"] for o in ctx["_rf_auth_observations"]] == [401, 200]
    _assert_outcome(diag, "gather", "GATHER_FAILED", True, "gather_after_auth")


def test_a_401_then_b_stops_before_answering_is_stopped_before_auth():
    """B 기준 ③ — A 의 401 은 이력(관측 리스트 · notes)에만 남고 host 진단을 정하지 않는다."""
    prior = [{"role": "primary", "label": "A", "status": 401}]
    ctx, diag = _classify("collect-2-2", _file("collect-2-2", None, label="B", role="secondary"),
                          prior_obs=prior, prior_statuses=[401], standard_accounts=2)
    assert ctx["_rf_auth_rejected"] is False, "표준 후보 2 중 1 만 401 — 전원 401 이 아니다"
    assert ctx["_rf_auth_outcome"] == "stopped_before_auth"
    _assert_outcome(diag, "gather", "GATHER_FAILED", None, "gather_internal")
    assert ctx["_rf_auth_observations"] == prior


def test_a_401_then_b_401_then_stop_is_rejected():
    prior = [{"role": "primary", "label": "A", "status": 401}]
    ctx, diag = _classify("collect-2-2", _file("collect-2-2", 401, label="B", role="secondary"),
                          prior_obs=prior, prior_statuses=[401], standard_accounts=2)
    assert ctx["_rf_auth_rejected"] is True
    _assert_outcome(diag, "auth", "AUTH_PROBE_FAILED", False, "auth_rejected")


# ── 복구 시도 정지 · 성공 증거 우선 ─────────────────────────────────────────────
def test_recovery_attempt_stop_keeps_the_standard_rejection():
    prior = [{"role": "primary", "label": "std", "status": 401}]
    ctx, diag = _classify("account-1-3", _file("account-1-3", 200, label="rec", role="recovery"),
                          prior_obs=prior, prior_statuses=[401], standard_accounts=1)
    assert ctx["_rf_backstop_class"] == "recovery_stopped"
    assert ctx["_rf_auth_observations"] == prior and ctx["_rf_auth_statuses"] == [401], "복구 시도는 표준 관측을 바꾸지 않는다"
    _assert_outcome(diag, "auth", "AUTH_PROBE_FAILED", False, "auth_rejected")


def test_existing_success_evidence_is_never_overridden_by_a_stopped_attempt():
    """Phase 1 수집이 성공(_rf_collect_ok)했다면 뒤 시도의 정지가 그 사실을 지우지 않는다."""
    ctx, diag = _classify("collect-1-2", None, collect_ok=True)
    _assert_outcome(diag, "gather", "GATHER_FAILED", True, "gather_after_auth")


def test_without_in_flight_attempt_nothing_changes():
    ctx, diag = _classify(None, None)
    assert "_rf_backstop_class" not in ctx
    _assert_outcome(diag, "gather", "GATHER_FAILED", None, "gather_internal")   # 기존 not_attempted 경로


# ── 구조 단언 ────────────────────────────────────────────────────────────────
def _walk(tasks, section="tasks"):
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        yield t, section
        for k in ("block", "rescue", "always"):
            if isinstance(t.get(k), list):
                yield from _walk(t[k], k if k != "block" else section)


def test_rescue_reads_only_the_current_attempt_file_and_never_runs_recovery():
    doc = yaml.safe_load((REPO / SITE).read_text(encoding="utf-8"))
    names_in_rescue, includes_in_rescue = [], []
    for play in doc:
        for t, section in _walk(play.get("tasks")):
            if section == "rescue":
                names_in_rescue.append(t.get("name"))
                inc = t.get("ansible.builtin.include_tasks") or t.get("include_tasks")
                if inc:
                    includes_in_rescue.append(inc.get("file", inc) if isinstance(inc, dict) else inc)
    assert _EVIDENCE_TASK in names_in_rescue and _BACKSTOP_TASK in names_in_rescue
    assert names_in_rescue.index(_BACKSTOP_TASK) < names_in_rescue.index(_REJECT_TASK), "관측 반영은 거부 판정보다 앞"
    assert not any("account_service" in str(i) for i in includes_in_rescue), "rescue 는 recovery 를 돌리지 않는다"
    ev = _task_by_name(SITE, _EVIDENCE_TASK)
    tpl = ev["ansible.builtin.set_fact"]["_rf_backstop_evidence"]
    assert "_rf_attempt_id ~ '.json'" in tpl and "errors='ignore'" in tpl and "parse_auth_evidence(" in tpl
    assert ev["when"] == "(_rf_attempt_id | default('')) != ''"


def test_attempt_ids_are_marked_before_and_cleared_after_each_module_call():
    for rel, mark, clear, prefix in [
        ("redfish-gather/tasks/try_one_account.yml", "redfish | try_account | mark attempt in flight",
         "redfish | try_account | record auth evidence", "collect-"),
        ("redfish-gather/tasks/collect_standard.yml", "redfish | collect_standard | mark anonymous attempt in flight",
         "redfish | collect_standard | set ok (empty creds)", "anonymous-"),
        ("redfish-gather/tasks/account_service_try_one.yml", "redfish | account_service | mark recovery attempt in flight",
         "redfish | account_service | evaluate recovery auth", "account-"),
    ]:
        doc = yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))
        tasks = {t.get("name"): t for t, _ in _walk(doc)}
        assert tasks[mark]["ansible.builtin.set_fact"]["_rf_attempt_id"].startswith(prefix), rel
        assert tasks[clear]["ansible.builtin.set_fact"]["_rf_attempt_id"] == "", rel
        names = [t.get("name") for t, _ in _walk(doc)]
        module_task = next(n for n in names if n and (n.endswith("| attempt") or n.endswith("| invoke")
                                                      or n.endswith("empty-credential attempt")))
        assert names.index(mark) < names.index(module_task) < names.index(clear), rel
        attempt = tasks[module_task]["redfish_gather"]["attempt"]
        assert set(attempt) == {"evidence_dir", "id", "build_id", "event_uuid", "label", "role"}, rel
        assert attempt["id"] == "{{ _rf_attempt_id }}", rel
        for key in ("username", "password"):
            assert key not in attempt, "증거 파일 인자에 자격을 싣지 않는다"
