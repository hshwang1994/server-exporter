"""자격 후보는 명시 거부일 때만 다음으로 넘어간다 · 대상 측 일시 장애는 실패 사유를 바꾸지 않는다 (2026-10-06, 9차 W05 · W06).

무엇을 고정하나
  - Redfish 표준 후보: 다음 후보로는 구조화된 401 일 때만 넘어간다. 통신 오류(first_auth_status 없음) · 5xx · 403 · 인증 통과 뒤
    수집 실패면 남은 후보에 자격을 보내지 않는다. 거부 뒤 간격(65초)만 남고 통신 오류용 짧은 간격은 없다.
  - Redfish 복구(계정 쓰기) 진입: "primary 하나라도 401" 이 아니라 "시도한 표준 후보 전원 401(primary 포함)" — rescue 의
    인증 거부 판정과 같은 기준. 실제 Jinja2 로 표현식을 평가한다.
  - OS(SSH · WinRM) · ESXi(vSphere): 실패 뒤 고른 관리 포트에 TCP 연결을 1회 다시 확인하고, 연결되지 않으면 남은 후보를 보내지
    않는다. 오류 문자열로 거부를 추측하지 않는다(CLAUDE.md §8).
  - Redfish 저장장치 Controllers 의 하위 401/403 은 host 를 failed 로 끌어내리지 않는다(섹션 failed · host partial · 데이터 유지).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402


def _tasks(rel):
    doc = yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))
    out = []

    def walk(items):
        for t in items or []:
            out.append(t)
            for k in ("block", "rescue", "always"):
                if k in t:
                    walk(t[k])
    walk(doc)
    return out


def _task(rel, name_part):
    hits = [t for t in _tasks(rel) if name_part in str(t.get("name", ""))]
    assert len(hits) == 1, (rel, name_part, [t.get("name") for t in hits])
    return hits[0]


def _render_bool(expr: str, **ctx) -> bool:
    env = jinja2.Environment()
    env.filters["bool"] = lambda v: v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
    return env.from_string(expr).render(**ctx).strip() == "True"


@pytest.mark.parametrize("rel,flag,stop_name", [
    ("os-gather/tasks/try_one_credential.yml", "_os_cred_stopped", "stop candidates when the port does not connect"),
    ("esxi-gather/tasks/try_one_credential.yml", "_e_cred_stopped", "stop candidates when the port does not connect"),
    ("redfish-gather/tasks/try_one_account.yml", "_rf_candidates_stopped", "stop candidates unless explicitly rejected"),
    ("redfish-gather/tasks/account_service_try_one.yml", "_rf_acct_stopped", "stop recovery candidates unless explicitly rejected"),
])
def test_stop_flag_guards_the_included_block_and_is_set_last(rel, flag, stop_name):
    """include_tasks 의 loop when 은 반복을 시작하기 전에 한꺼번에 평가된다(2026-10-06 WSL ansible-core 2.20.7 실측: loop when 만 두면
    2번째 후보도 실행됐다). 그래서 중단 표식은 포함된 파일의 block 조건이 본다. 표식을 켜는 순간 같은 block 의 남은 태스크도 건너뛰므로
    그 태스크는 block 의 마지막이다(실패 근거 기록 · 로그 · 간격이 먼저 끝난다)."""
    doc = yaml.safe_load((REPO / rel).read_text(encoding="utf-8"))
    outer = doc[-1]
    assert f"not ({flag} | default(false) | bool)" in outer["when"], outer["when"]
    assert stop_name in outer["block"][-1]["name"], [t["name"] for t in outer["block"]][-3:]


# ── Redfish 표준 후보 ────────────────────────────────────────────────────────────────────────────────

def test_redfish_candidates_stop_unless_the_attempt_was_explicitly_rejected():
    stop = _task("redfish-gather/tasks/try_one_account.yml", "stop candidates unless explicitly rejected")
    assert stop["ansible.builtin.set_fact"] == {"_rf_candidates_stopped": True}
    assert "not (_rf_attempt_ok | bool)" in stop["when"]
    assert any("first_auth_status | default(none)) != 401" in w for w in stop["when"]), stop["when"]
    loop = _task("redfish-gather/tasks/collect_standard.yml", "try accounts in order")
    assert "not (_rf_candidates_stopped | default(false) | bool)" in loop["when"]
    init = _task("redfish-gather/tasks/collect_standard.yml", "init attempt state")
    assert init["ansible.builtin.set_fact"]["_rf_candidates_stopped"] is False, "Phase 마다 새로 센다"
    backoff = _task("redfish-gather/tasks/try_one_account.yml", "backoff on failure")
    assert any("first_auth_status | default(none)) == 401" in w for w in backoff["when"]), "거부 뒤에만 간격 — 다음 후보가 없으면 기다리지 않는다"
    assert "_rf_transport_backoff_seconds" not in backoff["ansible.builtin.command"]


@pytest.mark.parametrize("observations,rejected", [
    ([{"role": "primary", "status": 401}], True),
    ([{"role": "primary", "status": 401}, {"role": "secondary", "status": 401}], True),
    ([{"role": "primary", "status": 401}, {"role": "secondary", "status": None}], False),   # 두 번째 후보는 통신 오류
    ([{"role": "primary", "status": 401}, {"role": "secondary", "status": 503}], False),
    ([{"role": "primary", "status": 403}], False),
    ([{"role": "primary", "status": None}], False),
    ([{"role": "secondary", "status": 401}], False),                                         # primary 를 시도하지 않았다
    ([], False),
])
def test_recovery_entry_requires_every_tried_standard_candidate_to_be_rejected(observations, rejected):
    fact = _task("redfish-gather/tasks/collect_standard.yml", "primary 자격 거부 판정")["ansible.builtin.set_fact"]["_rf_primary_auth_rejected"]
    assert _render_bool(fact, _rf_auth_observations=observations) is rejected, (observations, fact)


# ── OS · ESXi ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("prefix,probe_ok,stopped,port_expr", [
    ("os-gather", "_os_probe_ok", "_os_cred_stopped", "(ansible_port | default(22 if _os_type == 'linux' else 5985)) | int"),
    ("esxi-gather", "_e_probe_ok", "_e_cred_stopped", None),
])
def test_os_and_esxi_stop_sending_credentials_when_the_port_does_not_connect(prefix, probe_ok, stopped, port_expr):
    one = f"{prefix}/tasks/try_one_credential.yml"
    recheck = _task(one, "recheck management port after failure")
    assert recheck["when"] == f"not ({probe_ok} | bool)"
    wf = recheck["ansible.builtin.wait_for"]
    assert wf["state"] == "started" and "10" in str(wf["timeout"])
    if port_expr:
        assert port_expr in wf["port"] and recheck.get("delegate_to") == "localhost"
    else:
        assert wf["port"] == 443 and "delegate_to" not in recheck, "ESXi Play 는 connection: local"
    assert recheck["failed_when"] is False and recheck["changed_when"] is False
    stop = _task(one, "stop candidates when the port does not connect")
    assert stop["ansible.builtin.set_fact"] == {stopped: True}
    assert any("state | default('')) != 'started'" in w for w in stop["when"])
    loop = _task(f"{prefix}/tasks/try_credentials.yml", "iterate candidates")
    assert f"not ({stopped} | default(false) | bool)" in loop["when"]
    assert _task(f"{prefix}/tasks/try_credentials.yml", "init")["ansible.builtin.set_fact"][stopped] is False
    text = (REPO / one).read_text(encoding="utf-8")
    for guess in ("'Authentication' in", "'denied' in", "msg is search", "stderr is search"):
        assert guess not in text, "오류 문자열로 거부를 추측하지 않는다"


# ── Redfish 저장장치 하위 리소스 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fail_at", ["collection", "member"])
@pytest.mark.parametrize("status", [401, 403])
def test_storage_controller_sub_resource_denial_keeps_the_host_partial(monkeypatch, fail_at, status):
    sdata = {"Id": "RAID.1", "Controllers": {"@odata.id": "/redfish/v1/Systems/1/Storage/RAID.1/Controllers"}}

    def fake_get(bmc_ip, path, u, p, t, v, *a, **k):
        if path.endswith("Controllers"):
            if fail_at == "collection":
                return status, {}, f"HTTP {status}: Forbidden"
            return 200, {"Members": [{"@odata.id": "/redfish/v1/Systems/1/Storage/RAID.1/Controllers/0"}]}, None
        return status, {}, f"HTTP {status}: Forbidden"

    monkeypatch.setattr(rg, "_get", fake_get)
    info, errs = rg._extract_storage_controller_info(sdata, "10.0.0.1", "u", "p", 5, False)
    assert info == {"controller_fetch_status": status} and len(errs) == 1
    assert errs[0]["code"] == rg._CODE_NON_BLOCKING_SUBRESOURCE and f"HTTP {status}" in errs[0]["message"]
    final, clean = rg._compute_final_status(["system", "storage"], ["storage"], errs)
    assert final == "partial" and clean == ["system"], "확보한 다른 섹션은 그대로, host 는 partial"
    # 같은 401 이 비차단 code 없이(컬렉션 · 앵커 수준) 오면 종전대로 failed — 자격 오류 신호는 그대로다
    anchor = [rg._err("storage", f"Storage 컬렉션 실패: HTTP {status}: Forbidden")]
    assert rg._compute_final_status(["system", "storage"], ["storage"], anchor)[0] == "failed"
