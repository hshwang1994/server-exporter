"""Redfish 표준/복구 계정 분리 Contract 회귀 (2026-08-12).

무엇을 지키려는가
-----------------
표준 수집 계정(Standard Gathering Account)은 **모든 Location + 모든 Vendor 공통 1개**다.
복구 계정(Recovery Account)만 (Location + Vendor) 축을 갖는다. 목적이 다르기 때문이다 —
복구 계정은 수집용이 아니라 **표준 계정을 만들거나 되살리기 위한** 계정이다.

여기서 잠그는 불변식:
    최종 Gathering 은 반드시 표준 계정으로 수행된다.
    복구 계정으로 수집한 결과가 정상 결과로 나가는 경로는 존재하지 않는다.

배경 (실제 사고): 2026-08-12 Pilot 에서 Dell 10.100.15.34 의 표준 계정이 401 인데
recovery 계정으로 9개 섹션을 수집하고 `status=success` 를 냈다. 계정 정리는 실패
(`verification=failed`) 했는데도 결과는 성공이었다. 그 경로를 구조적으로 제거한 것이
이 파일이 지키는 내용이다.
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

sys.path.insert(0, str(REPO / "module_utils"))
import credential_common as cc  # noqa: E402

# redfish_gather 모듈 로드 (ansible stub)
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_mu = types.ModuleType("ansible.module_utils")
_stub_mu.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_mu
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_mu)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)
import redfish_gather as rg  # noqa: E402

# 2026-08-12: provision 이 account_service_get → account_service_discover 로 옮겨졌다.
# 기존 3-tuple fake 를 discovery dict 로 감싸는 공용 seam (tests/unit/account_seam.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from account_seam import as_discovery as _as_discovery_raw  # noqa: E402


def _as_discovery(fn, **overrides):
    return _as_discovery_raw(fn, rg, **overrides)


@pytest.fixture(autouse=True)
def _default_write_verify_seam(monkeypatch):
    """2026-08-12 (audit H-1): 이제 **모든** 계정 쓰기 경로가 재조회 + 표준 자격 재인증을
    수행한다. 종전 POST 경로는 2xx 만으로 성공을 보고했다.

    그래서 쓰기 seam 만 stub 하던 테스트가 실제 네트워크로 나가게 된다. 여기서 기본
    검증 seam 을 성공으로 깔아 둔다. 개별 테스트가 다시 setattr 하면 그쪽이 이긴다.
    """
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg, "_get_response_etag", lambda *a, **k: None)
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)


_spec = importlib.util.spec_from_file_location(
    "_frc_harness", REPO / "tests" / "e2e" / "test_failure_reason_contract.py"
)
_harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness)
_iter_tasks = _harness._iter_tasks

LOCATIONS = ("ich", "chj", "yi", "git")
VENDORS = ("dell", "hpe", "lenovo", "cisco", "supermicro",
           "huawei", "inspur", "fujitsu", "quanta")

# 자리표시 — 실제 자격이 아니다.
_STD = {"username": "std-user", "password": "<std>", "label": "common_infraops", "role": "primary"}


def _resolve(location: str, vendor: str | None) -> dict[str, Any]:
    return cc.resolve_redfish_credentials(
        location=location, known_locations=LOCATIONS,
        known_vendors=VENDORS, vendor=vendor,
    )


def _tasks_of(relpath: str) -> list[dict[str, Any]]:
    doc = list(yaml.safe_load_all((REPO / relpath).read_text(encoding="utf-8")))[0]
    out: list[dict[str, Any]] = []
    for node in doc:
        if isinstance(node, dict) and "tasks" in node:
            out.extend(_iter_tasks(node["tasks"]))
        else:
            out.extend(_iter_tasks(node))
    return out


def _code_only(text: str) -> str:
    """주석 제외 — 주석 속 언급은 동작이 아니다."""
    keep = []
    for line in text.splitlines():
        st = line.lstrip()
        if st.startswith("#"):
            continue
        idx = line.find(" #")
        keep.append(line[:idx] if idx >= 0 else line)
    return "\n".join(keep)


# ═══════════════════════════════════════════════════════════════════════════
# 1~4. Scope 축 — 표준은 전역, 복구는 (location, vendor)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("location", LOCATIONS)
def test_1_standard_scope_is_identical_across_locations(location):
    r = _resolve(location, "dell")
    assert r["standard_credential_scope"] == "common/redfish/standard"
    assert r["standard_vault_relpath"] == "vault/common/redfish/standard.yml"
    assert location not in r["standard_vault_relpath"]


@pytest.mark.parametrize("vendor", VENDORS)
def test_2_standard_scope_is_identical_across_vendors(vendor):
    r = _resolve("ich", vendor)
    assert r["standard_credential_scope"] == "common/redfish/standard"
    assert vendor not in r["standard_vault_relpath"]


def test_3_recovery_scope_differs_per_location():
    scopes = {loc: _resolve(loc, "dell")["recovery_credential_scope"] for loc in LOCATIONS}
    assert len(set(scopes.values())) == len(LOCATIONS), f"Location 별로 갈리지 않는다: {scopes}"
    for loc, s in scopes.items():
        assert s == f"{loc}/redfish/dell"


def test_4_recovery_scope_differs_per_vendor():
    scopes = {v: _resolve("ich", v)["recovery_credential_scope"] for v in VENDORS}
    assert len(set(scopes.values())) == len(VENDORS)
    for v, s in scopes.items():
        assert s == f"ich/redfish/{v}"


def test_vendor_unresolved_keeps_standard_but_drops_recovery():
    """vendor 미식별이어도 표준 계정은 쓸 수 있다 — 전역이라 vendor 와 무관하다."""
    r = _resolve("ich", "not-a-vendor")
    assert r["standard_vault_relpath"] == "vault/common/redfish/standard.yml"
    assert r["recovery_credential_scope"] is None
    assert r["recovery_vault_relpath"] is None
    assert r["reason"] == cc.REASON_VENDOR_UNRESOLVED


def test_unknown_location_makes_no_recovery_path():
    r = _resolve("nowhere", "dell")
    assert r["recovery_vault_relpath"] is None
    assert r["reason"] == cc.REASON_UNKNOWN_LOCATION


# ═══════════════════════════════════════════════════════════════════════════
# 5~7. 후보 배열 — 표준 먼저, 복구 순서 보존
# ═══════════════════════════════════════════════════════════════════════════
_RECOVERY_VAULT = {"accounts": [
    {"username": "r1", "password": "<p1>", "label": "dell_fallback_1", "role": "recovery"},
    {"username": "r2", "password": "<p2>", "label": "dell_fallback_2", "role": "recovery"},
    {"username": "r3", "password": "<p3>", "label": "dell_current", "role": "recovery"},
    {"username": "r4", "password": "<p4>", "label": "lab_dell_root", "role": "recovery"},
]}


def test_5_merge_puts_standard_first_then_recovery():
    cand = cc.redfish_candidates(
        cc.standard_accounts_of({"accounts": [_STD]}),
        cc.recovery_accounts_of(_RECOVERY_VAULT),
    )
    assert [a["label"] for a in cand] == [
        "common_infraops", "dell_fallback_1", "dell_fallback_2", "dell_current", "lab_dell_root",
    ]


def test_6_standard_primary_is_always_candidate_zero():
    cand = cc.redfish_candidates(
        cc.standard_accounts_of({"accounts": [_STD]}),
        cc.recovery_accounts_of(_RECOVERY_VAULT),
    )
    assert cand[0]["role"] == "primary"
    assert all(a["role"] == "recovery" for a in cand[1:])


def test_7_recovery_internal_order_is_preserved():
    """배열 순서 = 시도 순서. 재정렬하면 인증 순서가 바뀌고 lockout 위험이 달라진다."""
    original = [a["label"] for a in _RECOVERY_VAULT["accounts"]]
    assert [a["label"] for a in cc.recovery_accounts_of(_RECOVERY_VAULT)] == original
    # 역순 입력도 그대로 나와야 한다 (정렬 코드가 숨어들지 않았는지)
    reversed_vault = {"accounts": list(reversed(_RECOVERY_VAULT["accounts"]))}
    assert [a["label"] for a in cc.recovery_accounts_of(reversed_vault)] == list(reversed(original))


def test_recovery_vault_primary_is_never_a_standard_candidate():
    """Location/Vendor vault 에 primary 가 남아 있어도 표준 대용으로 쓰지 않는다 (§14)."""
    polluted = {"accounts": [
        {"username": "x", "password": "<x>", "label": "leftover", "role": "primary"},
        *_RECOVERY_VAULT["accounts"],
    ]}
    rec = cc.recovery_accounts_of(polluted)
    assert all(a["role"] == "recovery" for a in rec)
    assert "leftover" not in [a["label"] for a in rec]


def test_recovery_vault_legacy_keys_are_not_promoted():
    """legacy ansible_user 는 role=primary 로 정규화된다 → 복구 후보가 되면 안 된다.

    이관 전 9개 vendor vault 는 legacy 키에 표준 계정 복제본을 갖고 있었다.
    """
    legacy_only = {"ansible_user": "u", "ansible_password": "<p>"}
    assert cc.recovery_accounts_of(legacy_only) == []
    assert len(cc.standard_accounts_of(legacy_only)) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 8~9, 13. Playbook 흐름 — 복구 계정으로 수집하지 않는다
# ═══════════════════════════════════════════════════════════════════════════
def test_8_collect_standard_is_only_ever_given_standard_accounts():
    """site.yml 이 collect_standard 에 넘기는 후보는 항상 표준 후보뿐이다."""
    givens = []
    for task in _tasks_of("redfish-gather/site.yml"):
        inc = task.get("ansible.builtin.include_tasks")
        if isinstance(inc, str) and inc.endswith("collect_standard.yml"):
            givens.append((task.get("name"), (task.get("vars") or {}).get("_rf_try_accounts")))
    assert givens, "collect_standard.yml include 를 찾지 못했다"
    for name, given in givens:
        assert given is not None, f"{name}: _rf_try_accounts 미지정 — 후보가 불명확하다"
        assert "_rf_standard_accounts" in given, f"{name}: 표준 후보가 아닌 것을 넘긴다 — {given!r}"
        assert "_rf_recovery_accounts" not in given, f"{name}: 복구 후보를 수집에 넘긴다"


def test_9_reconcile_gate_requires_standard_failure_and_401_and_recovery():
    gate = None
    for task in _tasks_of("redfish-gather/site.yml"):
        if "account_service | 진입 조건 판정" in (task.get("name") or ""):
            gate = (task.get("ansible.builtin.set_fact") or {})["_rf_account_reconcile_allowed"]
    assert gate, "진입 조건 판정 태스크를 찾지 못했다"
    assert "_rf_collect_ok" in gate
    assert "_rf_primary_auth_rejected" in gate
    assert "_rf_recovery_accounts" in gate


def test_13_final_gathering_by_recovery_is_rejected():
    """복구 계정으로 수집이 끝난 상태는 성공이 될 수 없다 (§18 FAIL 조건)."""
    guard = None
    for task in _tasks_of("redfish-gather/site.yml"):
        if "abort if final gathering not by standard account" in (task.get("name") or ""):
            guard = task
    assert guard is not None, "최종 수집 주체 검증 태스크가 없다"
    assert "ansible.builtin.fail" in guard
    assert "'recovery'" in str(guard.get("when"))


def test_account_service_never_collects():
    """복구 경로에 수집(gather) 호출이 있으면 안 된다."""
    for rel in ("redfish-gather/tasks/account_service.yml",
                "redfish-gather/tasks/account_service_try_one.yml"):
        for task in _tasks_of(rel):
            rgm = task.get("redfish_gather")
            if isinstance(rgm, dict):
                assert rgm.get("mode") == "account_provision", (
                    f"{rel}: {task.get('name')!r} 가 account_provision 이 아닌 모드로 모듈을 부른다"
                )
            inc = task.get("ansible.builtin.include_tasks")
            assert not (isinstance(inc, str) and "collect_standard" in inc), (
                f"{rel}: 복구 경로에서 수집을 부른다 — 복구 계정 수집 경로가 되살아났다"
            )


def test_recollect_requires_verified_recovery():
    """Phase 3 재수집은 recovered=true + dryrun=false 일 때만 (§9)."""
    task = None
    for t in _tasks_of("redfish-gather/site.yml"):
        if "re-collect with standard account" in (t.get("name") or ""):
            task = t
    assert task is not None, "Phase 3 재수집 태스크가 없다"
    when = " ".join(str(x) for x in (task.get("when") or []))
    assert "recovered" in when
    assert "dryrun" in when


# ═══════════════════════════════════════════════════════════════════════════
# 10~12, 20. 모듈 — 쓰기 성공 조건
# ═══════════════════════════════════════════════════════════════════════════
def _dell_accounts(existing_username=""):
    return [
        {"slot_uri": "/redfish/v1/AccountService/Accounts/1", "id": "1",
         "username": "", "role_id": "None", "enabled": False},
        {"slot_uri": "/redfish/v1/AccountService/Accounts/3", "id": "3",
         "username": existing_username, "role_id": "Administrator", "enabled": True},
    ]


def _provision(monkeypatch, accounts, patch_code=200, verify_codes=(200,),
               acct_service=None, dryrun=False, patch_body=None):
    calls = {"patch": [], "verify": 0, "reread": 0}

    def fake_acct_get(bmc_ip, u, p, t, v):
        return acct_service, accounts, []

    def fake_patch(bmc_ip, path, body, u, p, t, v):
        calls["patch"].append((path, dict(body)))
        return patch_code, (patch_body or {}), None

    def fake_get(bmc_ip, path, u, p, t, v):
        # 2026-08-12: 쓰기 뒤에는 (a) 계정 리소스 재조회 (복구 자격, slot URI) 와
        #   (b) 표준 자격 재인증 (/Systems) 이 **둘 다** 일어난다. "재인증 횟수" 는
        #   (b) 만 센다 — 그래야 lockout 예산과 같은 것을 세게 된다.
        if not str(path).endswith("Systems"):
            calls["reread"] += 1
            return 200, {"UserName": "infraops", "Enabled": True}, None
        calls["verify"] += 1
        idx = min(calls["verify"] - 1, len(verify_codes) - 1)
        code = verify_codes[idx]
        return (code, {}, None) if code == 200 else (code, {}, f"HTTP {code}")

    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(fake_acct_get))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", fake_get)
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    out = rg.account_service_provision(
        bmc_ip="10.0.0.1", vendor="dell",
        current_username="rec", current_password="<rec>",
        target_username="infraops", target_password="<tgt>",
        target_role="Administrator", timeout=5, verify_ssl=False, dryrun=dryrun,
    )
    return out, calls


def test_11_password_sync_then_reauth_success_is_recovered(monkeypatch):
    out, calls = _provision(monkeypatch, _dell_accounts("infraops"),
                            verify_codes=(200,), acct_service={})
    assert out["action"] == "password_sync"
    assert out["account_existed"] is True
    assert out["recovered"] is True
    assert out["verification"] == "verified"
    assert calls["patch"][0][0].endswith("/Accounts/3")


def test_10_create_then_reauth_success_is_recovered(monkeypatch):
    """대상 계정이 없으면 빈 슬롯에 만들고, 재인증이 되어야 복구다."""
    out, _ = _provision(monkeypatch, _dell_accounts(""), verify_codes=(200,), acct_service={})
    assert out["action"] == "create"
    assert out["account_existed"] is False
    assert out["recovered"] is True
    assert out["verification"] == "verified"


def test_12_write_2xx_but_reauth_fails_is_not_recovered(monkeypatch):
    """PATCH 2xx 는 성공이 아니다 (§9). 재인증까지 되어야 성공이다."""
    out, calls = _provision(monkeypatch, _dell_accounts("infraops"),
                            verify_codes=(401,), acct_service={})
    assert out["recovered"] is False
    assert out["verification"] == "failed"
    assert calls["verify"] == len(rg.ACCOUNT_VERIFY_DELAYS), "재인증 재시도 횟수가 다르다"


def test_20_dell_regression_write_response_is_preserved(monkeypatch):
    """2026-08-12 Dell 실사고 회귀.

    관측: PATCH 200 → 재인증 401 → verification=failed. 그런데 **왜** 적용되지 않았는지
    알 근거가 결과 어디에도 없었다. 종전 코드가 PATCH 응답 body 를 `_` 로 버렸기 때문이다.
    벤더는 2xx 응답에도 @Message.ExtendedInfo 로 거부/경고 사유를 담는다.
    """
    body = {"@Message.ExtendedInfo": [{
        "MessageId": "IDRAC.2.9.SYS416",
        "Message": "The value entered for the password does not meet the password policy.",
        "Resolution": "Enter a password that meets the policy and retry.",
    }]}
    out, _ = _provision(monkeypatch, _dell_accounts("infraops"),
                        verify_codes=(401,), acct_service={}, patch_body=body)
    assert out["verification"] == "failed"
    assert out["write_response_info"], "쓰기 응답의 확장 정보가 버려졌다"
    assert "password policy" in out["write_response_info"]
    joined = " ".join(f"{e.get('message')} {e.get('detail')}" for e in out["errors"])
    assert "password policy" in joined, "확장 정보가 errors 로 전달되지 않는다"
    assert "암호 정책" in joined, "정책 미충족 가능성 안내가 없다"


def test_provision_refuses_to_write_without_recovery_auth(monkeypatch):
    """복구 자격이 인증되지 않으면 **아무것도 쓰지 않는다** (§14).

    종전에는 AccountService GET 이 401 이어도 그대로 진행해 accounts=[] 가 되고,
    "대상 계정 없음" 으로 오인해 생성 경로로 들어갔다.
    """
    out, calls = _provision(monkeypatch, [], acct_service=None)
    assert out["auth_ok"] is False
    assert out["recovered"] is False
    assert calls["patch"] == [], "인증도 안 된 자격으로 BMC 에 썼다"
    joined = " ".join(f"{e.get('message')}" for e in out["errors"])
    assert "복구" in joined


def test_dryrun_writes_nothing(monkeypatch):
    out, calls = _provision(monkeypatch, _dell_accounts("infraops"),
                            acct_service={}, dryrun=True)
    assert out["dryrun"] is True
    assert out["verification"] == "skipped"
    assert calls["patch"] == []
    assert calls["verify"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 14~18. Scope 부재 / fallback 부재
# ═══════════════════════════════════════════════════════════════════════════
def test_14_standard_vault_missing_is_an_explicit_abort():
    """표준 계정을 못 열면 수집이 성립하지 않는다 — 조용히 진행하지 않는다."""
    task = None
    for t in _tasks_of("redfish-gather/site.yml"):
        if "abort if credential set unavailable" in (t.get("name") or ""):
            task = t
    assert task is not None
    when = str(task.get("when"))
    assert "_cred_standard_outcome" in when, "표준 기준으로 판정하지 않는다"
    assert "credential_set_missing" in when and "credential_set_undecryptable" in when


def test_14b_unknown_location_aborts_before_gathering():
    """미등록 se_location 은 표준 계정이 전역이어도 수집으로 진행되면 안 된다.

    2026-08-12 감사에서 드러난 공백: 이 gate 의 `or` 두 항 중 `_cred_standard_outcome`
    쪽만 테스트가 잡고 있었다. `_cred_reason` 항은 **미등록 Location 이 전역 표준 자격으로
    수집되는 것을 막는 유일한 런타임 가드**인데, 그 절을 지워도 전 테스트가 통과했다.
    표준 계정이 Location 을 보지 않는 전역 1벌이라 더더욱 필요한 가드다.
    """
    task = None
    for t in _tasks_of("redfish-gather/site.yml"):
        if "abort if credential set unavailable" in (t.get("name") or ""):
            task = t
    assert task is not None
    when = str(task.get("when"))
    assert "_cred_reason" in when, "unknown_location 이 gate 에 반영되지 않는다"
    assert "'resolved'" in when and "'vendor_unresolved'" in when, (
        "reason 허용목록이 없다 — 미등록 Location 이 표준 자격으로 수집될 수 있다"
    )
    assert "not in" in when, "허용목록이 아니라 부분 비교면 새 reason 이 그냥 통과한다"


def test_15_recovery_set_missing_is_recorded_not_silent():
    """복구 세트 부재는 실패 원인이 다르므로 결과에 남아야 한다 (§15)."""
    names = [t.get("name") or "" for t in _tasks_of("redfish-gather/site.yml")]
    assert any("recovery set unavailable" in n for n in names), (
        "복구 세트 부재를 결과에 남기는 태스크가 없다"
    )


@pytest.mark.parametrize("a,b", [
    (("ich", "dell"), ("chj", "dell")),   # 16: cross-location
    (("ich", "dell"), ("ich", "hpe")),    # 17: cross-vendor
])
def test_16_17_no_cross_scope_reuse(a, b):
    ra, rb = _resolve(*a), _resolve(*b)
    assert ra["recovery_vault_relpath"] != rb["recovery_vault_relpath"]
    # 한쪽 경로가 다른 쪽 결과에 등장하지 않는다 (후보 목록 같은 것이 없다)
    assert rb["recovery_vault_relpath"] not in str(ra)


def test_18_no_flat_vault_fallback_in_production_code():
    """flat 경로가 저장소에 남아 있어도 runtime 에서 참조하면 안 된다."""
    flat = ("vault/linux.yml", "vault/windows.yml", "vault/esxi.yml", "vault/redfish/")
    targets = [
        "redfish-gather/site.yml",
        "redfish-gather/tasks/load_vault.yml",
        "redfish-gather/tasks/account_service.yml",
        "redfish-gather/tasks/account_service_try_one.yml",
        "common/tasks/credential/resolve_and_load.yml",
        "common/tasks/credential/resolve_and_load_redfish.yml",
        "common/tasks/credential/load_one.yml",
        "module_utils/credential_common.py",
    ]
    for rel in targets:
        code = _code_only((REPO / rel).read_text(encoding="utf-8"))
        for f in flat:
            assert f not in code, f"{rel}: flat vault 경로 {f!r} 참조"


def test_resolver_returns_exactly_one_path_per_scope():
    """경로 후보 list 를 돌려주지 않는다 — 여러 개면 그 자체가 fallback 이다."""
    r = _resolve("ich", "dell")
    for key, value in r.items():
        assert not isinstance(value, (list, tuple)), f"{key} 가 복수 값이다: {value!r}"


# ═══════════════════════════════════════════════════════════════════════════
# 19. Secret 비노출
# ═══════════════════════════════════════════════════════════════════════════
def test_19_resolver_returns_no_secret():
    r = _resolve("ich", "dell")
    blob = repr(r).lower()
    for banned in ("password", "username", "secret"):
        assert banned not in blob, f"resolver 결과에 {banned!r}"


def test_19_recovery_task_secret_handling():
    """복구 후보를 다루는 태스크는 no_log, debug 는 label 까지만."""
    for task in _tasks_of("redfish-gather/tasks/account_service_try_one.yml"):
        name = task.get("name") or ""
        if "redfish_gather" in task or "set_fact" in str(task.keys()):
            if "log recovery attempt" in name:
                continue
        dbg = task.get("ansible.builtin.debug") or {}
        msg = dbg.get("msg", "")
        if isinstance(msg, str):
            assert ".password" not in msg and "_try_recovery.username" not in msg, (
                f"{name}: debug 에 자격 노출"
            )


def test_19_account_service_meta_has_no_secret():
    """meta 에 password / username 파생값이 들어가지 않는다."""
    for task in _tasks_of("redfish-gather/tasks/account_service.yml"):
        if "record meta" not in (task.get("name") or ""):
            continue
        meta = (task.get("ansible.builtin.set_fact") or {}).get("_rf_account_service_meta") or {}
        blob = repr(meta)
        assert "password" not in blob.lower() or "write_response" in blob
        assert "username" not in blob.lower()


def test_failed_envelope_exposes_account_service_meta():
    """복구가 실패한 결과에서도 **무엇을 시도했는지** 보여야 한다 (2026-08-12).

    최초 구현에서는 성공 경로에만 `account_service` 를 넣었다. 그런데 이 정보가 가장
    필요한 때는 **실패했을 때**다 — 복구를 시도했는지, 복구 자격으로 접속은 됐는지,
    썼는지, 확인이 됐는지가 결과에 없으면 Jenkins 콘솔을 열어야 알 수 있다.
    (콘솔은 json_only 가 OUTPUT 외 전부 억제해서 사실상 볼 수 없다.)
    """
    rescue = None
    for task in _tasks_of("redfish-gather/site.yml"):
        facts = task.get("ansible.builtin.set_fact") or {}
        tpl = facts.get("_diagnosis")
        if isinstance(tpl, str) and "failure_reason" in tpl and "AUTH_PROBE_FAILED" in tpl:
            rescue = tpl
    assert rescue, "rescue 의 _diagnosis 템플릿을 찾지 못했다"
    for key in ("credential_scope", "recovery_credential_scope", "account_service", "auth"):
        assert f"'{key}'" in rescue, f"실패 envelope details 에 {key} 누락"


# ═══════════════════════════════════════════════════════════════════════════
# Dell iDRAC10 실사고 회귀 — 200 인데 본문이 거부인 응답
# ═══════════════════════════════════════════════════════════════════════════
_IDRAC_LOCKED_REJECT = {"@Message.ExtendedInfo": [
    {"MessageId": "Base.1.12.GeneralError",
     "Message": "A general error has occurred. See Resolution for information."},
    {"MessageId": "Base.1.12.PropertyNotWritable",
     "Message": "The property Locked is a read only property and cannot be assigned a value.",
     "MessageArgs": ["Locked"],
     "Resolution": "Remove the property from the request body and retry."},
]}


def test_rejected_patch_properties_reads_the_device_words():
    assert "Locked" in rg.rejected_patch_properties(_IDRAC_LOCKED_REJECT)
    assert rg.rejected_patch_properties({}) == set()
    assert rg.rejected_patch_properties({"@Message.ExtendedInfo": []}) == set()


# Dell SYS474 — HTTP 200 + Success 메시지와 함께 오는 **비밀번호 정책 거부**.
# MessageArgs 가 비어 있고 RelatedProperties 만 대상을 가리키며 Severity 는 Warning 이다.
# 종전 parser 는 read-only 문장과 PropertyNotWritable 계열 MessageArgs 만 봐서 이것을
# 성공으로 통과시켰다 (그 뒤 재인증 401 → 원인은 추측으로 남았다).
# source: Dell Error and Event Message Guide (SYS474), 사이트 실측 10.100.15.34 (02 §11/§12)
_IDRAC_SYS474_REJECT = {"@Message.ExtendedInfo": [
    {"MessageId": "Base.1.12.Success",
     "Message": "Successfully Completed Request.",
     "Severity": "OK", "MessageArgs": []},
    {"MessageId": "IDRAC.2.9.SYS413",
     "Message": "The operation successfully completed.",
     "Severity": "OK", "MessageArgs": []},
    {"MessageId": "IDRAC.2.9.SYS474",
     "Message": ("Unable to set the password because the password entered does not "
                 "comply to the Security Strengthen Policy standards."),
     "Severity": "Warning", "MessageArgs": [],
     "RelatedProperties": ["#/Password"],
     "Resolution": "Enter a password that complies with the policy and retry."},
]}


def test_dell_never_sends_read_only_locked_even_when_account_is_locked(monkeypatch):
    """Dell 은 `Locked` 가 read-only 라 **잠긴 계정에도 보내지 않는다.**

    2026-08-12 (rev.2). 종전 이 테스트는 "Locked 를 보내고 200+본문 거부를 받으면
    Locked 만 빼고 재시도한다" 를 고정했다. 그 재시도는 "보내 보고 거부되면 뺀다" 는
    추측성 fallback 이고, 9 Vendor 조사가 공통으로 금지한 패턴이다.

    올바른 층은 **쓰기 전**이다. Dell 공식 Updatable Property 목록에 Locked 가 없고
    사이트 실측(10.100.15.34)에서도 read-only 로 거부됐으므로, Family Property Contract
    가 `Locked: repair=read_only` 로 선언한다 → 애초에 실리지 않는다 → 거부도 재시도도
    발생하지 않는다. 잠금 사실은 errors[] 로 사람에게 보고한다.
    source: 02 §8 / dell.com/.../manageraccount Updatable Properties
    """
    sent = []

    def fake_patch(bmc_ip, path, body, u, p, t, v):
        sent.append(dict(body))
        return 200, {}, None

    locked_accounts = _dell_accounts("infraops")
    locked_accounts[-1]["locked"] = True
    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, locked_accounts, [])))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    out = rg.account_service_provision(
        bmc_ip="10.0.0.1", vendor="dell",
        current_username="rec", current_password="<rec>",
        target_username="infraops", target_password="<tgt>",
        target_role="Administrator", timeout=5, verify_ssl=False, dryrun=False,
    )
    assert len(sent) == 1, "read-only 속성 때문에 쓰기를 두 번 했다"
    assert "Locked" not in sent[0], "read-only 로 선언된 속성을 보냈다"
    assert "Password" in sent[0]
    # 잠긴 사실 자체는 사람이 알아야 한다 — 조용히 넘어가지 않는다.
    joined = " ".join(str(e.get("message")) for e in out["errors"])
    assert "잠금" in joined
    assert out["recovered"] is True
    assert out["verification"] == "verified"


def test_dell_password_policy_rejection_with_200_is_a_write_failure(monkeypatch):
    """HTTP 200 + Success 메시지 + SYS474 → **쓰기 실패**. 재인증을 헛돌지 않는다.

    같은 응답에 `Base.1.12.Success` 와 `SYS413` 성공 메시지가 함께 온다. 그래서
    "성공 메시지가 있으니 성공" 도, "HTTP 200 이니 성공" 도 성립하지 않는다.
    판정 근거는 `RelatedProperties` 가 **우리가 실제로 보낸 Password** 를 가리킨다는 사실이다.
    """
    verify_calls = {"n": 0}
    writes = {"n": 0}

    def fake_get(*a, **k):
        verify_calls["n"] += 1
        return 401, {}, "HTTP 401"

    def fake_patch(*a, **k):
        writes["n"] += 1
        return 200, _IDRAC_SYS474_REJECT, None

    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, _dell_accounts("infraops"), [])))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", fake_get)
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    out = rg.account_service_provision(
        bmc_ip="10.0.0.1", vendor="dell",
        current_username="rec", current_password="<rec>",
        target_username="infraops", target_password="<tgt>",
        target_role="Administrator", timeout=5, verify_ssl=False, dryrun=False,
    )
    assert out["recovered"] is False
    assert out["write_accepted"] is False, "200 + Success 메시지에 속아 수락으로 봤다"
    assert out["write_http_status"] == 200, "transport 수락 사실은 따로 남아야 한다"
    assert writes["n"] == 1, "거부된 뒤 추측성 재시도를 했다"
    assert verify_calls["n"] == 0, "쓰기가 거부됐는데 재인증을 시도했다"
    kinds = {r["kind"] for r in out["write_rejections"]}
    props = {r["property"] for r in out["write_rejections"]}
    assert kinds == {"policy_rejected"}
    assert props == {"Password"}
    joined = " ".join(str(e.get("detail")) for e in out["errors"])
    assert "SYS474" in joined, "장비가 준 MessageId 가 진단에서 사라졌다"
