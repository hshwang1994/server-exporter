"""Phase 6-B: 공통계정 자동 정리(account reconciliation)의 **진입 조건**을 고정한다.

무엇을 지키려는가
-----------------
recovery 자격으로 수집이 성공했다는 사실만으로 BMC 계정을 고치면 안 된다.
primary(공통계정) 자격이 왜 실패했는지 모르는 상태이기 때문이다. timeout / TLS 오류 /
5xx / 권한 부족(403) 은 자격증명이 틀렸다는 뜻이 아닌데, 그 상태에서 비밀번호를 덮어쓰면
멀쩡히 동작하던 공통계정을 잃는다.

그래서 진입 조건을 "primary 후보가 **401 로 명시적으로 거부**됐을 때" 하나로 좁혔다.
이 파일은 그 조건이 다시 넓어지지 않도록 A~J 열 가지 상황을 고정한다.

  A 대상 계정이 없음                  -> 생성한다
  B 자격이 맞음(primary 성공)         -> 아무것도 쓰지 않는다
  C 한 번 동기화한 다음 실행          -> 아무것도 쓰지 않는다
  D primary 가 timeout                -> 아무것도 쓰지 않는다
  E primary 가 TLS 오류               -> 아무것도 쓰지 않는다
  F primary 가 5xx                    -> 아무것도 쓰지 않는다
  G primary 가 403                    -> 아무것도 쓰지 않는다
  H primary 401 + recovery 성공       -> 여기서만 쓰기를 허용한다
  I recovery 까지 전멸                -> 아무것도 쓰지 않는다
  J 같은 username 이 여러 슬롯        -> 아무것도 쓰지 않는다

검증 방식
---------
판정 자체는 Ansible 템플릿에 있으므로 **production YAML 에서 템플릿을 그대로 뽑아 렌더**한다
(합성 fixture 가 아니다). 렌더 하네스는 tests/e2e/test_failure_reason_contract.py 의 것을
그대로 재사용한다 (ansible.cfg jinja2_native = True 반영).
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 렌더 하네스 재사용 (tests/e2e/test_failure_reason_contract.py)
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location(
    "_failure_reason_contract_harness",
    REPO / "tests" / "e2e" / "test_failure_reason_contract.py",
)
_harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness)

_env = _harness._env
_iter_tasks = _harness._iter_tasks

# ---------------------------------------------------------------------------
# redfish_gather 모듈 로드 (ansible stub)
# ---------------------------------------------------------------------------
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

# 테스트에서 쓰는 자리표시 자격 — 실제 값이 아니다.
_RECOVERY_USER = "recovery-user"
_RECOVERY_PASS = "<recovery-pass>"
_TARGET_USER = "infraops"
_TARGET_PASS = "<target-pass>"


# ---------------------------------------------------------------------------
# production YAML 에서 템플릿 추출
# ---------------------------------------------------------------------------
def _tasks_of(relpath: str) -> list[dict[str, Any]]:
    """play 파일이든 task 파일이든 모든 태스크를 평탄화해 돌려준다."""
    doc = list(yaml.safe_load_all((REPO / relpath).read_text(encoding="utf-8")))[0]
    out: list[dict[str, Any]] = []
    for node in doc:
        if isinstance(node, dict) and "tasks" in node:      # play 파일 (site.yml)
            out.extend(_iter_tasks(node["tasks"]))
        else:                                               # task 파일
            out.extend(_iter_tasks(node))
    return out


def _set_fact_template(relpath: str, task_name_part: str, key: str) -> str:
    for task in _tasks_of(relpath):
        if task_name_part in (task.get("name") or ""):
            facts = task.get("ansible.builtin.set_fact") or {}
            if key in facts:
                return facts[key]
    raise AssertionError(f"{relpath} 에서 {task_name_part!r} 의 {key!r} 템플릿을 찾지 못함")


def _render(template: str, ctx: dict[str, Any]) -> Any:
    return _env().from_string(template).render(**ctx)


# 정본 템플릿 3개 — 값이 아니라 **production 파일의 내용** 을 쓴다.
_TPL_PRIMARY_REJECTED = _set_fact_template(
    "redfish-gather/tasks/collect_standard.yml",
    "primary 자격 거부 판정", "_rf_primary_auth_rejected")
_TPL_RECONCILE_ALLOWED = _set_fact_template(
    "redfish-gather/site.yml",
    "account_service | 진입 조건 판정", "_rf_account_reconcile_allowed")
_TPL_DRYRUN_EFFECTIVE = _set_fact_template(
    "redfish-gather/tasks/account_service.yml",
    "resolve target primary account", "_rf_account_service_dryrun_effective")


def _decide(observations: list[dict[str, Any]], used_role: str, collect_ok: bool,
            dryrun_override: Any = None) -> dict[str, Any]:
    """관측 -> (primary 거부 판정, 진입 허용, 실제 쓰기 여부) 를 production 템플릿으로 계산."""
    rejected = _render(_TPL_PRIMARY_REJECTED, {"_rf_auth_observations": observations})
    allowed = _render(_TPL_RECONCILE_ALLOWED, {
        "_rf_used_account": {"role": used_role} if used_role else {},
        "_rf_collect_ok": collect_ok,
        "_rf_primary_auth_rejected": rejected,
    })
    ctx: dict[str, Any] = {"_rf_account_reconcile_allowed": allowed}
    if dryrun_override is not None:
        ctx["_rf_account_service_dryrun"] = dryrun_override
    dryrun = _render(_TPL_DRYRUN_EFFECTIVE, ctx)
    return {"rejected": rejected, "allowed": allowed, "dryrun": dryrun,
            "writes": (allowed is True and dryrun is False)}


# ---------------------------------------------------------------------------
# Case B~I — 진입 조건 (Ansible 레이어 렌더)
# ---------------------------------------------------------------------------
def test_case_b_primary_credentials_match_no_write():
    """B: 공통계정 자격이 맞으면 recovery 로 내려가지도 않는다 -> 쓰기 0."""
    r = _decide([{"role": "primary", "label": "infraops", "status": 200}],
                used_role="primary", collect_ok=True)
    assert r["rejected"] is False
    assert r["allowed"] is False
    assert r["dryrun"] is True
    assert r["writes"] is False


def test_case_c_second_run_after_sync_no_write():
    """C: 한 번 동기화한 뒤의 실행. primary 가 다시 200 이므로 또 쓰지 않는다.

    이 테스트가 막는 것: 진입 조건이 recovery 성공 여부에만 걸려 있으면 매 수집마다
    같은 PATCH 가 반복된다 (계정 잠금 정책을 건드릴 수 있다).
    """
    r = _decide([{"role": "primary", "label": "infraops", "status": 200}],
                used_role="primary", collect_ok=True)
    assert r["writes"] is False


@pytest.mark.parametrize("status,label", [
    (None, "timeout"),      # D: 응답 자체가 없음
    (None, "tls"),          # E: TLS handshake 실패 — 역시 status 없음
    (500, "5xx"),           # F: BMC 일시 장애
    (503, "5xx-503"),
    (403, "forbidden"),     # G: 인증은 통과했을 수 있고 권한만 부족
])
def test_case_d_e_f_g_non_401_primary_failure_no_write(status, label):
    """D/E/F/G: primary 실패가 401 이 아니면 원인 미확정이므로 쓰기 0."""
    r = _decide(
        [{"role": "primary", "label": "infraops", "status": status},
         {"role": "recovery", "label": label, "status": 200}],
        used_role="recovery", collect_ok=True)
    assert r["rejected"] is False, f"{label}: 401 이 아닌데 거부로 판정됨"
    assert r["allowed"] is False, f"{label}: 진입하면 안 된다"
    assert r["dryrun"] is True
    assert r["writes"] is False


def test_case_h_primary_401_and_recovery_ok_allows_write():
    """H: primary 가 401 로 명시 거부 + recovery 로 수집 성공 -> 이 경우에만 허용."""
    r = _decide(
        [{"role": "primary", "label": "infraops", "status": 401},
         {"role": "recovery", "label": "vendor-default", "status": 200}],
        used_role="recovery", collect_ok=True)
    assert r["rejected"] is True
    assert r["allowed"] is True
    assert r["dryrun"] is False, "조건이 성립했을 때는 쓰기 모드를 명시 전달해야 한다"
    assert r["writes"] is True


def test_case_i_all_candidates_rejected_no_write():
    """I: recovery 까지 전부 실패하면 수집 자체가 실패라 진입하지 않는다."""
    r = _decide(
        [{"role": "primary", "label": "infraops", "status": 401},
         {"role": "recovery", "label": "vendor-default", "status": 401}],
        used_role="", collect_ok=False)
    assert r["rejected"] is True, "primary 401 관측 자체는 사실대로 남는다"
    assert r["allowed"] is False, "수집이 실패했으면 계정을 손대지 않는다"
    assert r["writes"] is False


def test_primary_role_identified_by_role_not_index():
    """후보 순서가 바뀌어도 판정이 흔들리면 안 된다 (index 가 아니라 role 로 식별)."""
    reordered = [
        {"role": "recovery", "label": "vendor-default", "status": 401},
        {"role": "primary", "label": "infraops", "status": 401},
    ]
    assert _render(_TPL_PRIMARY_REJECTED, {"_rf_auth_observations": reordered}) is True

    only_recovery_401 = [
        {"role": "primary", "label": "infraops", "status": 200},
        {"role": "recovery", "label": "vendor-default", "status": 401},
    ]
    assert _render(_TPL_PRIMARY_REJECTED,
                   {"_rf_auth_observations": only_recovery_401}) is False, (
        "recovery 의 401 로 공통계정을 고치면 안 된다")


def test_no_observations_means_no_write():
    """관측이 하나도 없으면(빈 자격 경로 등) 진입하지 않는다."""
    assert _render(_TPL_PRIMARY_REJECTED, {"_rf_auth_observations": []}) is False


def test_status_401_compared_as_integer_not_string():
    """문자열 '401' 은 401 로 취급하지 않는다 (구조화 정수 비교만)."""
    assert _render(_TPL_PRIMARY_REJECTED, {
        "_rf_auth_observations": [{"role": "primary", "label": "x", "status": "401"}],
    }) is False


# ---------------------------------------------------------------------------
# §16 — dryrun 기본값이 "그냥 기본값이라서" 쓰기를 켜지 않는다
# ---------------------------------------------------------------------------
def test_dryrun_defaults_to_simulation_when_condition_not_met():
    """진입 조건 fact 가 없거나 false 면 시뮬레이션이다."""
    assert _render(_TPL_DRYRUN_EFFECTIVE, {}) is True
    assert _render(_TPL_DRYRUN_EFFECTIVE, {"_rf_account_reconcile_allowed": False}) is True


def test_dryrun_user_override_still_wins():
    """-e _rf_account_service_dryrun=true 는 조건이 성립해도 시뮬레이션으로 되돌린다."""
    for override in (True, "true", "yes"):
        assert _render(_TPL_DRYRUN_EFFECTIVE, {
            "_rf_account_reconcile_allowed": True,
            "_rf_account_service_dryrun": override,
        }) is True, f"override={override!r} 가 무시됨"


def test_account_service_yml_no_longer_defaults_dryrun_to_false():
    """회귀 가드: `_rf_account_service_dryrun | default(false)` 패턴이 되살아나면 실패."""
    text = (REPO / "redfish-gather/tasks/account_service.yml").read_text(encoding="utf-8")
    # 주석은 제외한다 (왜 없앴는지 설명하는 문장에 같은 표현이 나온다).
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "_rf_account_service_dryrun | default(false)" not in code, (
        "쓰기 모드가 기본값으로 켜지는 구조가 되살아났다")
    assert "_rf_account_service_dryrun_effective" in code


# ---------------------------------------------------------------------------
# Case A / J — 모듈 레이어
# ---------------------------------------------------------------------------
def _patch_transport(monkeypatch, accounts, *, patch=(200, {}, None),
                     get=(200, {}, None), post=(201, {}, None), delete=(204, {}, None)):
    calls = {"patch": [], "post": [], "delete": [], "get": []}
    monkeypatch.setattr(rg, "account_service_get", lambda *a, **k: ({}, accounts, []))
    monkeypatch.setattr(rg, "_patch",
                        lambda b, p_, body, *a, **k: (calls["patch"].append(p_), patch)[1])
    monkeypatch.setattr(rg, "_post",
                        lambda b, p_, body, *a, **k: (calls["post"].append(dict(body)), post)[1])
    monkeypatch.setattr(rg, "_delete",
                        lambda b, p_, *a, **k: (calls["delete"].append(p_), delete)[1])
    monkeypatch.setattr(rg, "_get",
                        lambda b, p_, *a, **k: (calls["get"].append(p_), get)[1])
    return calls


def test_case_a_account_missing_is_created(monkeypatch):
    """A: 대상 계정이 없으면 만든다 (기능 유지 — 조건만 좁혔지 기능을 지우지 않았다)."""
    calls = _patch_transport(
        monkeypatch, accounts=[],
        post=(201, {"@odata.id": "/redfish/v1/AccountService/Accounts/3"}, None))

    out = rg.account_service_provision(
        "10.0.0.1", "lenovo", _RECOVERY_USER, _RECOVERY_PASS,
        _TARGET_USER, _TARGET_PASS, "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["recovered"] is True
    assert out["method"] == "post_new"
    assert out["action"] == "create"
    assert out["account_existed"] is False
    assert len(calls["post"]) == 1
    assert calls["delete"] == []


def test_case_j_duplicate_username_stops_before_any_write(monkeypatch):
    """J: 같은 username 이 여러 슬롯이면 어느 쪽이 맞는지 알 수 없다 -> 쓰기 0."""
    accounts = [
        {"slot_uri": "/redfish/v1/AccountService/Accounts/2", "id": "2",
         "username": _TARGET_USER, "role_id": "Administrator", "enabled": True, "locked": False},
        {"slot_uri": "/redfish/v1/AccountService/Accounts/5", "id": "5",
         "username": _TARGET_USER, "role_id": "ReadOnly", "enabled": True, "locked": False},
    ]
    calls = _patch_transport(monkeypatch, accounts=accounts)

    out = rg.account_service_provision(
        "10.0.0.2", "lenovo", _RECOVERY_USER, _RECOVERY_PASS,
        _TARGET_USER, _TARGET_PASS, "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert calls["patch"] == [], "중복 상태에서 PATCH 를 보내면 안 된다"
    assert calls["post"] == []
    assert calls["delete"] == []
    assert out["recovered"] is False
    assert out["method"] == "ambiguous"
    assert out["action"] == "ambiguous"
    assert out["account_existed"] is True

    detail = " ".join(str(e.get("detail") or "") for e in out["errors"])
    assert "2" in detail and "5" in detail, f"중복 슬롯 목록이 없다: {detail!r}"


def test_single_match_still_syncs(monkeypatch):
    """중복 가드가 정상 단일 매칭 동작까지 막으면 안 된다."""
    accounts = [
        {"slot_uri": "/redfish/v1/AccountService/Accounts/2", "id": "2",
         "username": _TARGET_USER, "role_id": "Administrator", "enabled": True, "locked": False},
    ]
    calls = _patch_transport(monkeypatch, accounts=accounts)

    out = rg.account_service_provision(
        "10.0.0.3", "lenovo", _RECOVERY_USER, _RECOVERY_PASS,
        _TARGET_USER, _TARGET_PASS, "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert len(calls["patch"]) == 1
    assert out["recovered"] is True
    assert out["method"] == "patch_existing"
    assert out["action"] == "password_sync"
    assert out["account_existed"] is True
    assert out["verification"] == "verified"


def test_find_all_users_exact_match_only():
    accounts = [
        {"id": "1", "username": "INFRAOPS"},
        {"id": "2", "username": "infraops"},
        {"id": "3", "username": ""},
        {"id": "4", "username": "infraops"},
    ]
    assert [a["id"] for a in rg.account_service_find_all_users(accounts, "infraops")] == ["2", "4"]
    assert rg.account_service_find_all_users(accounts, "nobody") == []


def test_dryrun_does_not_write_anything(monkeypatch):
    """dryrun 이면 어떤 요청도 보내지 않고 verification 은 skipped 다."""
    accounts = [
        {"slot_uri": "/redfish/v1/AccountService/Accounts/2", "id": "2",
         "username": _TARGET_USER, "role_id": "Administrator", "enabled": True, "locked": False},
    ]
    calls = _patch_transport(monkeypatch, accounts=accounts)

    out = rg.account_service_provision(
        "10.0.0.4", "lenovo", _RECOVERY_USER, _RECOVERY_PASS,
        _TARGET_USER, _TARGET_PASS, "Administrator",
        timeout=10, verify_ssl=False, dryrun=True,
    )

    assert calls["patch"] == [] and calls["post"] == [] and calls["delete"] == []
    assert out["verification"] == "skipped"
    assert out["dryrun"] is True


# ---------------------------------------------------------------------------
# §10 — 비활성 / 잠김 계정을 단순 비밀번호 불일치와 구분해 남긴다
# ---------------------------------------------------------------------------
def test_disabled_and_locked_account_is_reported_separately(monkeypatch):
    accounts = [
        {"slot_uri": "/redfish/v1/AccountService/Accounts/2", "id": "2",
         "username": _TARGET_USER, "role_id": "Administrator",
         "enabled": False, "locked": True},
    ]
    _patch_transport(monkeypatch, accounts=accounts)

    out = rg.account_service_provision(
        "10.0.0.5", "lenovo", _RECOVERY_USER, _RECOVERY_PASS,
        _TARGET_USER, _TARGET_PASS, "Administrator",
        timeout=10, verify_ssl=False, dryrun=True,
    )

    msgs = " ".join(e.get("message", "") for e in out["errors"])
    assert "비활성" in msgs
    assert "잠금" in msgs


def test_locked_unknown_is_not_reported_as_locked(monkeypatch):
    """Locked 를 주지 않는 펌웨어(None)를 '잠기지 않음' 으로도 '잠김' 으로도 단정하지 않는다."""
    accounts = [
        {"slot_uri": "/redfish/v1/AccountService/Accounts/2", "id": "2",
         "username": _TARGET_USER, "role_id": "Administrator",
         "enabled": True, "locked": None},
    ]
    _patch_transport(monkeypatch, accounts=accounts)

    out = rg.account_service_provision(
        "10.0.0.6", "lenovo", _RECOVERY_USER, _RECOVERY_PASS,
        _TARGET_USER, _TARGET_PASS, "Administrator",
        timeout=10, verify_ssl=False, dryrun=True,
    )
    assert "잠금" not in " ".join(e.get("message", "") for e in out["errors"])


# ---------------------------------------------------------------------------
# §11 — 비밀번호 동기화 실패만으로 기존 계정을 지우지 않는다
# ---------------------------------------------------------------------------
def test_password_sync_failure_does_not_delete_existing_account(monkeypatch):
    accounts = [
        {"slot_uri": "/redfish/v1/AccountService/Accounts/2", "id": "2",
         "username": _TARGET_USER, "role_id": "Administrator", "enabled": True, "locked": False},
    ]
    calls = _patch_transport(monkeypatch, accounts=accounts,
                             get=(401, {}, "HTTP 401"))

    out = rg.account_service_provision(
        "10.0.0.7", "lenovo", _RECOVERY_USER, _RECOVERY_PASS,
        _TARGET_USER, _TARGET_PASS, "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert calls["delete"] == [], "비밀번호 동기화 실패만으로 기존 계정을 지우면 안 된다"
    assert calls["post"] == []
    assert out["recovered"] is False
    assert out["verification"] == "failed"


def test_delete_recreate_is_opt_in(monkeypatch):
    """운영자가 명시적으로 켜면 종전 DELETE+POST 복구 동작이 그대로 살아있다."""
    accounts = [
        {"slot_uri": "/redfish/v1/AccountService/Accounts/2", "id": "2",
         "username": _TARGET_USER, "role_id": "Administrator", "enabled": True, "locked": False},
    ]
    calls = _patch_transport(
        monkeypatch, accounts=accounts, get=(401, {}, "HTTP 401"),
        post=(201, {"@odata.id": "/redfish/v1/AccountService/Accounts/2"}, None))

    out = rg.account_service_provision(
        "10.0.0.8", "lenovo", _RECOVERY_USER, _RECOVERY_PASS,
        _TARGET_USER, _TARGET_PASS, "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
        allow_delete_recreate=True,
    )

    assert len(calls["delete"]) == 1
    assert out["method"] == "delete_repost"
    assert out["recovered"] is True


def test_ansible_layer_never_enables_delete_recreate():
    """account_service.yml 은 이 스위치를 켜지 않는다 (사람이 의도적으로 켜야 한다)."""
    text = (REPO / "redfish-gather/tasks/account_service.yml").read_text(encoding="utf-8")
    assert "allow_delete_recreate" not in text


# ---------------------------------------------------------------------------
# §17 — 결과 기록 (새 envelope 필드 없이 기존 details 안쪽만)
# ---------------------------------------------------------------------------
def test_meta_tracks_required_fields():
    facts = None
    for task in _tasks_of("redfish-gather/tasks/account_service.yml"):
        sf = task.get("ansible.builtin.set_fact") or {}
        meta = sf.get("_rf_account_service_meta")
        if isinstance(meta, dict) and "action" in meta:
            facts = meta
    assert facts is not None, "_rf_account_service_meta 에 action 이 없다"
    for key in ("attempted", "account_existed", "action", "verification", "vendor",
                "recovered", "method", "dryrun", "slot_uri"):
        assert key in facts, f"meta 에 {key} 누락"


def test_meta_never_carries_credentials():
    """meta 템플릿에 비밀번호/자격 변수가 새어 들어가면 안 된다."""
    for task in _tasks_of("redfish-gather/tasks/account_service.yml"):
        sf = task.get("ansible.builtin.set_fact") or {}
        meta = sf.get("_rf_account_service_meta")
        if not isinstance(meta, dict):
            continue
        blob = yaml.safe_dump(meta, allow_unicode=True)
        for banned in ("password", "_rf_acct_recovery_pass", "target_password",
                       "_rf_used_account_password"):
            assert banned not in blob, f"meta 에 {banned} 노출: {blob}"


def test_provision_result_never_contains_credentials(monkeypatch):
    """모듈 반환값(errors detail 포함)에 자격증명이 실리지 않는다."""
    accounts = [
        {"slot_uri": "/redfish/v1/AccountService/Accounts/2", "id": "2",
         "username": _TARGET_USER, "role_id": "Administrator", "enabled": False, "locked": True},
        {"slot_uri": "/redfish/v1/AccountService/Accounts/5", "id": "5",
         "username": _TARGET_USER, "role_id": "Administrator", "enabled": True, "locked": False},
    ]
    _patch_transport(monkeypatch, accounts=accounts, get=(401, {}, "HTTP 401"))

    for dryrun in (True, False):
        out = rg.account_service_provision(
            "10.0.0.9", "lenovo", _RECOVERY_USER, _RECOVERY_PASS,
            _TARGET_USER, _TARGET_PASS, "Administrator",
            timeout=10, verify_ssl=False, dryrun=dryrun,
        )
        blob = repr(out)
        assert _TARGET_PASS not in blob
        assert _RECOVERY_PASS not in blob


# ---------------------------------------------------------------------------
# Secret leakage — 자격을 다루는 태스크는 no_log 로 막혀 있어야 한다
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("relpath,task_part", [
    ("redfish-gather/tasks/try_one_account.yml", "try_account | attempt"),
    ("redfish-gather/tasks/try_one_account.yml", "try_account | promote on success"),
    ("redfish-gather/tasks/account_service.yml", "resolve target primary account"),
    ("redfish-gather/tasks/account_service.yml", "resolve recovery creds"),
    ("redfish-gather/tasks/account_service.yml", "account_service | invoke"),
    ("redfish-gather/tasks/account_service.yml", "record meta"),
    ("redfish-gather/tasks/account_service.yml", "rotate to primary creds"),
])
def test_credential_tasks_have_no_log(relpath, task_part):
    found = False
    for task in _tasks_of(relpath):
        if task_part in (task.get("name") or ""):
            found = True
            assert task.get("no_log") is True, f"{relpath} :: {task_part} 에 no_log 없음"
    assert found, f"{relpath} 에서 {task_part!r} 태스크를 찾지 못함"


def test_auth_observation_task_records_no_credentials():
    """인증 관측 누적 태스크는 role/label/status 만 담는다 (비밀번호를 담지 않는다)."""
    for task in _tasks_of("redfish-gather/tasks/try_one_account.yml"):
        if "record auth evidence" not in (task.get("name") or ""):
            continue
        tpl = (task.get("ansible.builtin.set_fact") or {}).get("_rf_auth_observations", "")
        assert "password" not in tpl
        assert "'role'" in tpl and "'status'" in tpl
        return
    raise AssertionError("record auth evidence 태스크를 찾지 못함")


def test_log_lines_do_not_print_credentials():
    """debug 로 찍는 문구에 자격 변수가 들어가지 않는다."""
    for task in _tasks_of("redfish-gather/tasks/account_service.yml"):
        msg = (task.get("ansible.builtin.debug") or {}).get("msg", "")
        if not isinstance(msg, str):
            continue
        for banned in ("target_password", "_rf_acct_recovery_pass",
                       "_rf_used_account_password", ".password"):
            assert banned not in msg, f"debug 문구에 {banned} 노출: {msg!r}"


# ---------------------------------------------------------------------------
# site.yml 배선 — 판정 fact 가 실제로 include 를 막고 있는가
# ---------------------------------------------------------------------------
def test_site_yml_gates_include_on_reconcile_fact():
    include_task = None
    for task in _tasks_of("redfish-gather/site.yml"):
        if "account_service (recovery" in (task.get("name") or ""):
            include_task = task
    assert include_task is not None, "site.yml 에서 account_service include 를 찾지 못함"
    when = include_task.get("when")
    when_text = when if isinstance(when, str) else " ".join(map(str, when or []))
    assert "_rf_account_reconcile_allowed" in when_text, (
        f"include 가 진입 조건 fact 로 막혀 있지 않다: {when!r}")


def test_collect_standard_initialises_observation_facts():
    text = (REPO / "redfish-gather/tasks/collect_standard.yml").read_text(encoding="utf-8")
    assert "_rf_auth_observations: []" in text
    assert "_rf_primary_auth_rejected: false" in text
