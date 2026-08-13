"""계정 쓰기 계약 불변식 — 이 파일이 깨지면 계약이 깨진 것이다.

`docs/ai/REDFISH_ACCOUNT_WRITE_CONTRACT_IMPLEMENTATION_PLAN_2026-08-12.md` §12.2 의
안전 불변식을 **Family 표 전수**에 대해 한 번에 검사한다. 개별 시나리오 테스트가
빠뜨리는 것은 "새로 추가한 Family 가 규칙을 어기는 경우" 인데, 그건 시나리오를 하나
더 쓰는 걸로는 못 막는다. 표 자체를 검사해야 막힌다.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
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
from tests.unit.account_seam import as_discovery  # noqa: E402

TARGET = "infraops"
ALL_FAMILIES = sorted(rg._ACCOUNT_FAMILIES)
PROPS = ("Password", "RoleId", "Enabled", "Locked",
         "PasswordChangeRequired", "AccountTypes")
STATES = {"writable", "read_only", "verify_only", "unsupported", "unverified"}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)


# ── Property Contract 전수 ───────────────────────────────────────────────────

@pytest.mark.parametrize("family_id", ALL_FAMILIES)
def test_every_family_declares_every_property_in_a_known_state(family_id):
    """모든 Family × 6 Property × 2 Operation 이 5-상태 중 하나로 확정된다."""
    fam = rg.account_family(family_id)
    for prop in PROPS:
        for op in ("create", "repair"):
            state = rg.account_prop_contract(fam, prop, op)
            assert state in STATES, f"{family_id}.{prop}.{op} = {state!r}"


@pytest.mark.parametrize("family_id", ALL_FAMILIES)
def test_write_gate_allows_only_writable(family_id):
    """`writable` 이 아닌 상태는 어느 것도 쓰기를 허용하지 않는다.

    특히 `unverified` 는 "일단 보내 보고 거부되면 뺀다" 가 아니라 **보내지 않는다** 는 뜻이다.
    """
    fam = rg.account_family(family_id)
    for prop in PROPS:
        for op in ("create", "repair"):
            state = rg.account_prop_contract(fam, prop, op)
            assert rg.account_prop_writable(fam, prop, op) is (state == "writable")


def test_unknown_property_defaults_to_unverified():
    """표에 없는 Property 는 writable 로 가정하지 않는다."""
    fam = rg.account_family("generic_collection_post")
    assert rg.account_prop_contract(fam, "SomeNewVendorProperty", "repair") == "unverified"
    assert rg.account_prop_writable(fam, "SomeNewVendorProperty", "repair") is False


@pytest.mark.parametrize("family_id", ALL_FAMILIES)
def test_create_payload_never_carries_a_non_writable_property(family_id):
    """생성 payload 에 계약이 허락하지 않은 속성이 실리지 않는다."""
    fam = rg.account_family(family_id)
    body = rg.build_create_payload(fam, TARGET, "<tgt>", "Administrator", explicit_id="9")
    for prop in PROPS:
        if prop in body and not rg.account_prop_writable(fam, prop, "create"):
            pytest.fail(f"{family_id}: create payload 에 {prop} 가 실렸다 "
                        f"({rg.account_prop_contract(fam, prop, 'create')})")


# ── UNVERIFIED Family 규칙 ───────────────────────────────────────────────────

UNVERIFIED = [f for f in ALL_FAMILIES if rg.account_family(f)["evidence"] == "unverified"]


@pytest.mark.parametrize("family_id", UNVERIFIED)
def test_unverified_family_never_inherits_the_full_body_exception(family_id):
    """근거를 확보하지 못한 Family 는 full body 예외를 상속하지 않는다."""
    assert rg.account_family(family_id)["full_body_patch"] is False


@pytest.mark.parametrize("family_id", UNVERIFIED)
def test_unverified_family_declares_no_optional_write(family_id):
    """계약 미확보 Family 는 Locked / PCR / AccountTypes 를 쓰지 않는다."""
    fam = rg.account_family(family_id)
    for prop in ("Locked", "PasswordChangeRequired", "AccountTypes"):
        assert rg.account_prop_writable(fam, prop, "repair") is False
        assert rg.account_prop_writable(fam, prop, "create") is False


@pytest.mark.parametrize("family_id", UNVERIFIED)
def test_unverified_family_sends_no_guessed_account_types(family_id):
    """`AccountTypes=["Redfish"]` 를 근거 없이 넣지 않는다.

    upstream OpenBMC 는 Redfish 와 WebUI 를 함께 요구하므로 한쪽만 보내면
    `StrictAccountTypes` 오류가 난다 (09 §9). 최소권한처럼 보이는 값이 오히려 무효다.
    """
    assert rg.account_family(family_id)["account_types"] is None


# ── full_body_patch 예외 범위 ────────────────────────────────────────────────

FULL_BODY = [f for f in ALL_FAMILIES if rg.account_family(f)["full_body_patch"]]


def test_full_body_exception_is_scoped_to_families_with_live_evidence():
    """full body 예외는 실측 근거가 있는 Family 에만 있다.

    한 Family 의 실측을 Vendor 전체나 다른 Vendor 의 기본 동작으로 일반화하지 않는다.
    현재 근거: Lenovo XCC(10.50.11.232) 비밀번호 단독 PATCH 시 권한 cache 손상.
    """
    assert FULL_BODY == ["lenovo_xcc2_accounttypes", "lenovo_xcc3_accounttypes"], \
        f"full_body_patch 예외가 번졌거나 사라졌다: {FULL_BODY}"


@pytest.mark.parametrize("family_id", FULL_BODY)
def test_full_body_family_still_respects_the_property_contract(family_id):
    """full body 는 "전부 보내라" 가 아니다 — 계약이 막은 속성은 여전히 안 나간다."""
    fam = rg.account_family(family_id)
    assert rg.account_prop_writable(fam, "Locked", "repair") is False


# ── If-Match / Create URI ────────────────────────────────────────────────────

@pytest.mark.parametrize("family_id", ALL_FAMILIES)
def test_if_match_is_never_required_on_create(family_id):
    """어떤 Family 도 Create 에 If-Match 를 요구하지 않는다.

    Inspur M6 의 공식 계약은 Create = POST Collection(If-Match 없음),
    Repair = PATCH Instance + If-Match 다 (06 §5/§11).
    """
    assert rg.account_if_match(rg.account_family(family_id), "create") is False


@pytest.mark.parametrize("family_id", ALL_FAMILIES)
def test_create_uri_kind_is_known(family_id):
    kind = rg.account_family(family_id)["create_uri"]
    assert kind in ("accounts_collection", "account_service_root", "account_instance")


def test_create_target_uri_never_mixes_the_two_supermicro_contracts():
    """한 Family 는 **하나의** Create URI 만 만들어 낸다 — 갈아타는 경로가 없다."""
    disc = {"service_uri": "AccountService", "accounts_uri": "AccountService/Accounts"}
    collection = rg.account_family("supermicro_legacy")
    assert rg._create_target_uri(collection, disc) == "AccountService/Accounts"
    root = dict(rg.account_family("supermicro_split_account"),
                create_uri="account_service_root")
    assert rg._create_target_uri(root, disc) == "AccountService"


# ── 계정 상태 판정 ───────────────────────────────────────────────────────────

def _disc(accounts, enumeration=None):
    return {"service_uri": "AccountService", "accounts_uri": "AccountService/Accounts",
            "roles_uri": None, "service": {}, "policy": rg._account_policy_of(None),
            "role_ids": [], "accounts": list(accounts),
            "member_total": len(accounts), "member_read": len(accounts),
            "enumeration": enumeration or rg.ENUM_COMPLETE, "manager": None,
            "errors": [], "auth_status": 200, "service_root": None}


def _acct(**kw):
    base = {"slot_uri": "/x/1", "id": "1", "username": TARGET, "role_id": "Administrator",
            "enabled": True, "has_username_key": True}
    base.update(kw)
    return base


@pytest.mark.parametrize("enumeration", [rg.ENUM_INCOMPLETE, rg.ENUM_FAILED])
def test_absent_is_never_claimed_without_complete_enumeration(enumeration):
    state, _ = rg.account_presence(_disc([], enumeration), TARGET)
    assert state == rg.PRESENCE_UNKNOWN


def test_protected_account_never_becomes_present_or_absent():
    state, _ = rg.account_presence(_disc([_acct(host_bootstrap=True)]), TARGET)
    assert state == rg.PRESENCE_PROTECTED_CONFLICT


# ── 쓰기 0 이어야 하는 상태 전수 ─────────────────────────────────────────────

NO_WRITE_CASES = {
    "unknown_enumeration": _disc([], rg.ENUM_INCOMPLETE),
    "ambiguous": _disc([_acct(id="1", slot_uri="/x/1"), _acct(id="2", slot_uri="/x/2")]),
    "protected": _disc([_acct(host_bootstrap=True)]),
}


@pytest.mark.parametrize("case", sorted(NO_WRITE_CASES))
def test_states_that_must_never_write(monkeypatch, case):
    """UNKNOWN / ambiguous / protected 에서는 어떤 HTTP 쓰기도 나가지 않는다."""
    writes = []
    monkeypatch.setattr(rg, "account_service_discover",
                        lambda *a, **k: NO_WRITE_CASES[case])
    for verb in ("_patch", "_post", "_delete"):
        monkeypatch.setattr(rg, verb,
                            lambda *a, _v=verb, **k: writes.append(_v) or (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (200, {}, None))

    out = rg.account_service_provision(
        "10.0.0.1", "lenovo", "rec", "<rec>", TARGET, "<tgt>",
        "Administrator", 5, False, dryrun=False)

    assert writes == [], f"{case}: 쓰기가 발생했다 {writes}"
    assert out["recovered"] is False


@pytest.mark.parametrize("vendor", ["dell", "hpe", "lenovo", "cisco", "supermicro",
                                    "huawei", "inspur", "fujitsu", "quanta"])
def test_dry_run_writes_nothing_for_every_vendor(monkeypatch, vendor):
    """Check Mode / dry-run 에서는 전 Vendor 쓰기 0."""
    writes = []
    monkeypatch.setattr(rg, "account_service_discover",
                        lambda *a, **k: _disc([_acct()]))
    for verb in ("_patch", "_post", "_delete"):
        monkeypatch.setattr(rg, verb,
                            lambda *a, _v=verb, **k: writes.append(_v) or (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (200, {}, None))

    out = rg.account_service_provision(
        "10.0.0.1", vendor, "rec", "<rec>", TARGET, "<tgt>",
        "Administrator", 5, False, dryrun=True)

    assert writes == [], f"{vendor}: dry-run 인데 쓰기가 나갔다"
    assert out["verification"] == "skipped"
    assert out["recovered"] is False


@pytest.mark.parametrize("vendor", ["dell", "hpe", "lenovo", "cisco", "supermicro",
                                    "huawei", "inspur", "fujitsu", "quanta"])
def test_recovered_is_never_true_without_a_fresh_standard_auth(monkeypatch, vendor):
    """표준 자격 재인증이 실패하면 어떤 Vendor 도 recovered=true 가 되지 않는다."""
    monkeypatch.setattr(rg, "account_service_discover",
                        lambda *a, **k: _disc([_acct()]))
    monkeypatch.setattr(rg, "_patch", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg, "_post", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda b, path, *a, **k:
                        (401, {}, "HTTP 401") if str(path).endswith("Systems")
                        else (200, {"UserName": TARGET, "Enabled": True}, None))

    out = rg.account_service_provision(
        "10.0.0.1", vendor, "rec", "<rec>", TARGET, "<tgt>",
        "Administrator", 5, False, dryrun=False)

    assert out["recovered"] is False
    assert out["verification"] != "verified"


@pytest.mark.parametrize("vendor", ["dell", "hpe", "lenovo", "cisco", "supermicro",
                                    "huawei", "inspur", "fujitsu", "quanta"])
def test_recovery_credential_failure_writes_nothing(monkeypatch, vendor):
    """복구 자격이 인증되지 않으면 어떤 쓰기도 하지 않는다."""
    writes = []
    failed = _disc([], rg.ENUM_FAILED)
    failed["service"] = None
    monkeypatch.setattr(rg, "account_service_discover", lambda *a, **k: failed)
    for verb in ("_patch", "_post", "_delete"):
        monkeypatch.setattr(rg, verb,
                            lambda *a, _v=verb, **k: writes.append(_v) or (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (401, {}, "HTTP 401"))

    out = rg.account_service_provision(
        "10.0.0.1", vendor, "rec", "<rec>", TARGET, "<tgt>",
        "Administrator", 5, False, dryrun=False)

    assert writes == []
    assert out["auth_ok"] is False
    assert out["recovered"] is False


# ── Secret 비노출 ────────────────────────────────────────────────────────────

def test_provision_result_never_contains_the_target_password(monkeypatch):
    monkeypatch.setattr(rg, "account_service_discover",
                        lambda *a, **k: _disc([_acct()]))
    monkeypatch.setattr(rg, "_patch", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (200, {}, None))
    secret = "S3cret-Do-Not-Leak"
    out = rg.account_service_provision(
        "10.0.0.1", "lenovo", "rec", "RecoverySecret", TARGET, secret,
        "Administrator", 5, False, dryrun=False)
    blob = repr(out)
    assert secret not in blob
    assert "RecoverySecret" not in blob
