"""비밀번호 단독 PATCH 계약 / Locked 조건부 전송 / 재인증 확인 간격.

배경 — 2026-08-12 git 리전 실장비 통제 실험 (HPE iLO6 / ProLiant DL380 Gen11 /
Redfish 1.20.0, 계정 /redfish/v1/AccountService/Accounts/4):

    {Password:<길이위반>}                       -> HTTP 400 iLO.2.36.InvalidPasswordLength
    {Password:<길이위반>, Enabled, RoleId}      -> HTTP 200 Base.1.19.AccountModified
    {Enabled, RoleId}          (Password 없음)  -> HTTP 200 Base.1.19.AccountModified
    {Password, Enabled, Locked, RoleId}         -> HTTP 400 iLO.2.36.PropertyNotWritableOrUnknown ['Locked']

  같은 값인데 단독으로 보내면 길이 검사에 걸리고, 다른 속성과 묶으면 통과한다.
  즉 iLO 는 Password 가 다른 속성과 함께 오면 **검사도 적용도 하지 않고 버린다.**
  그런데 응답은 200 + AccountModified 라 성공과 구분되지 않는다 — 아무 속성도 바뀌지 않는
  {Enabled, RoleId} PATCH 도 똑같은 메시지를 준다. 그래서 응답만으로는 절대 알 수 없고,
  Family 가 쓰기 **전에** 방식을 정해야 한다.

  이 결함의 관측된 결과(수정 전): PATCH 가 200 으로 수락되고 write_accepted=true 인데
  표준 자격 재인증은 계속 401 → verification=failed → 표준 Gathering 실패.
  2회 연속 실행에서 동일 재현.

두 번째 결함: 재인증 확인 간격이 장비가 선언한 인증 실패 패널티보다 짧았다.
  iLO 는 AuthFailureDelayTimeSeconds=10 / AuthFailuresBeforeDelay=1 을 선언한다.
  고정 (0,1,5)=6초 안의 재인증은 비밀번호를 옳게 썼어도 전부 401 이 된다.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

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

TARGET = "infraops"
SLOT = "/redfish/v1/AccountService/Accounts/4"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)


def _account(**over):
    a = {"slot_uri": SLOT, "id": "4", "username": TARGET, "role_id": "Administrator",
         "enabled": True, "locked": None, "account_types": None,
         "password_change_required": False, "has_username_key": True}
    a.update(over)
    return a


def _disc(accounts, role_ids=("Administrator", "Operator", "ReadOnly"), service=None,
          manager=None):
    return {
        "service_uri": "AccountService", "accounts_uri": "AccountService/Accounts",
        "roles_uri": "AccountService/Roles",
        "service": service if service is not None else {},
        "policy": rg._account_policy_of(service),
        "role_ids": list(role_ids), "accounts": list(accounts),
        "member_total": len(accounts), "member_read": len(accounts),
        "enumeration": rg.ENUM_COMPLETE, "manager": manager, "errors": [],
        "auth_status": 200,
    }


def _install(monkeypatch, accounts, service=None, role_ids=("Administrator", "Operator", "ReadOnly"),
             manager=None):
    """PATCH 본문을 기록하고, 재조회/재인증은 항상 통과시키는 seam."""
    bodies = []
    monkeypatch.setattr(rg, "account_service_discover",
                        lambda *a, **k: _disc(accounts, role_ids, service, manager))
    monkeypatch.setattr(rg, "_patch",
                        lambda ip, path, body, u, p, t, v, extra_headers=None:
                        (bodies.append(dict(body)), (200, {}, None))[1])
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (200, {"UserName": TARGET,
                                                          "RoleId": "Administrator",
                                                          "Enabled": True}, None))
    monkeypatch.setattr(rg, "_get_response_etag", lambda *a, **k: None)
    return bodies


def _provision(vendor, **kw):
    return rg.account_service_provision(
        "10.0.0.1", vendor, "rec", "<rec>", TARGET, "<tgt>",
        "Administrator", 5, False, dryrun=False, **kw)


# ── Locked 는 실제로 잠겼을 때만 보낸다 ──────────────────────────────────────
def test_locked_is_not_sent_when_account_is_not_locked(monkeypatch):
    """잠기지 않은 계정에 Locked:false 를 보내는 것은 no-op 인데 본문 전체를 죽인다.

    실측: iLO6 는 ManagerAccount 에 Locked 속성이 아예 없어 HTTP 400 으로 요청 전체를
    거부했고, Lenovo XCC 는 노출은 하되 read-only 라 거부했다. 두 경우 모두 drop 후
    retry 라는 **추가 쓰기 1회**로만 통과했다 (Lockout 예산 낭비).
    """
    bodies = _install(monkeypatch, [_account(locked=False)])
    _provision("lenovo")
    assert bodies, "PATCH 가 나가지 않았다"
    assert "Locked" not in bodies[0], f"잠기지 않았는데 Locked 를 보냈다: {bodies[0]}"


def test_locked_is_not_sent_when_device_does_not_expose_it(monkeypatch):
    bodies = _install(monkeypatch, [_account(locked=None)])
    _provision("lenovo")
    assert "Locked" not in bodies[0]


def test_locked_false_is_sent_when_account_is_actually_locked(monkeypatch):
    """잠금 해제 경로는 **Locked 가 writable 인 Family 에서** 그대로 살아 있어야 한다.

    2026-08-12 (rev.2): vendor 를 lenovo → huawei 로 바꿨다. Lenovo XCC 는 `Locked` 를
    GET 에만 노출하고 공식 Account Update 목록에는 없어(03 §14) 이제 보내지 않는다.
    Huawei 최신 iBMC 는 `Locked` 를 GET/PATCH 로 공식 정의한다(07 §5.1).
    "Locked 를 전 Vendor 에서 제거" 도 "전 Vendor 에 전송" 도 둘 다 틀렸다.
    """
    bodies = _install(monkeypatch, [_account(locked=True)])
    _provision("huawei")
    assert bodies[0].get("Locked") is False


# ── Family 계약: 비밀번호 단독 PATCH ─────────────────────────────────────────
def test_hpe_ilo5plus_writes_password_alone(monkeypatch):
    """iLO 계열은 Password 를 단독으로 써야 실제로 적용된다."""
    bodies = _install(monkeypatch, [_account()])
    out = _provision("hpe")
    assert out["family"] == "hpe_ilo5plus"
    assert out.get("isolated_write") is True
    assert set(bodies[0]) == {"Password"}, f"첫 PATCH 가 단독이 아니다: {sorted(bodies[0])}"


def test_hpe_no_followup_patch_when_nothing_else_differs(monkeypatch):
    """권한/활성이 이미 맞으면 추가 쓰기를 하지 않는다 (쓰기 1회)."""
    bodies = _install(monkeypatch, [_account(enabled=True, role_id="Administrator")])
    out = _provision("hpe")
    assert len(bodies) == 1, f"불필요한 추가 PATCH: {bodies}"
    assert out.get("followup_properties") in (None, [])


def test_hpe_followup_patch_only_carries_properties_that_differ(monkeypatch):
    bodies = _install(monkeypatch, [_account(enabled=False, role_id="ReadOnly")])
    out = _provision("hpe")
    assert set(bodies[0]) == {"Password"}
    assert len(bodies) == 2, "달라진 속성이 있는데 후속 PATCH 가 없다"
    assert set(bodies[1]) == {"Enabled", "RoleId"}
    assert out["followup_accepted"] is True
    assert out["followup_properties"] == ["Enabled", "RoleId"]


def test_lenovo_xcc_bundles_password_because_of_its_own_live_evidence(monkeypatch):
    """Lenovo XCC 사이트 실측(비밀번호 단독 PATCH 시 권한 cache 손상)을 회귀시키지 않는다.

    2026-08-12 (rev.2): 이것은 **그 Family 한정 예외**다. 기본 Repair 는 drift-only 이고,
    `full_body_patch=True` 는 LIVE 근거가 있는 Family 에만 명시한다. 실측 장비
    10.50.11.232 는 `lenovo_xcc_accounttypes` 로 판정되므로 그 Family 에만 붙어 있다.
    """
    bodies = _install(monkeypatch, [_account()])
    out = _provision("lenovo", adapter_id="redfish_lenovo_xcc3")
    assert out["family"] == "lenovo_xcc3_accounttypes"
    assert out.get("isolated_write") in (None, False)
    assert "Password" in bodies[0] and "Enabled" in bodies[0] and "RoleId" in bodies[0]


def test_full_body_exception_does_not_spread_to_other_lenovo_families(monkeypatch):
    """같은 Vendor 라도 근거가 없는 Family 는 drift-only 다.

    한 Family 의 실측을 Vendor 전체의 기본 동작으로 일반화하지 않는다.
    """
    bodies = _install(monkeypatch, [_account()])
    out = _provision("lenovo")          # adapter hint 없음 → lenovo_collection_post
    assert out["family"] == "lenovo_collection_post"
    assert list(bodies[0]) == ["Password"], \
        f"근거 없는 Family 에 full body 예외가 번졌다: {sorted(bodies[0])}"


def test_unverified_family_never_inherits_the_full_body_exception(monkeypatch):
    """UNVERIFIED Family 는 full_body_patch 예외를 상속하지 않는다."""
    bodies = _install(monkeypatch, [_account()])
    out = _provision("fujitsu")
    assert out["family"] == "generic_collection_post"
    assert out["evidence"] == "unverified"
    assert list(bodies[0]) == ["Password"]


def test_default_repair_sends_only_what_actually_drifted(monkeypatch):
    """기본 Repair 는 drift-only — 달라지지 않은 속성은 보내지 않는다."""
    bodies = _install(monkeypatch, [_account(enabled=True, role_id="Administrator")])
    _provision("lenovo")
    assert list(bodies[0]) == ["Password"]

    bodies2 = _install(monkeypatch, [_account(enabled=False, role_id="ReadOnly")])
    _provision("lenovo")
    assert set(bodies2[0]) == {"Password", "Enabled", "RoleId"}


def test_full_body_family_still_refuses_non_writable_properties(monkeypatch):
    """`full_body_patch=True` 는 "전부 보내라" 가 아니다.

    read_only / verify_only / unsupported / unverified 로 선언된 Property 는
    full_body Family 에서도 실리지 않는다. XCC 는 Locked 가 read_only 이므로
    **잠긴 계정에도** Locked 를 보내지 않는다 (03 §14).
    """
    bodies = _install(monkeypatch,
                      [_account(locked=True, password_change_required=True)])
    out = _provision("lenovo", adapter_id="redfish_lenovo_xcc3")
    assert out["family"] == "lenovo_xcc3_accounttypes"
    assert "Locked" not in bodies[0], "full_body 예외가 read_only 속성까지 실었다"
    # XCC3 는 PasswordChangeRequired 가 공식 목록에 없다 → full_body 여도 보내지 않는다.
    assert "PasswordChangeRequired" not in bodies[0], \
        "full_body 예외가 unsupported 속성까지 실었다"

    # XCC2 는 같은 속성이 공식 writable 이라 drift 가 있으면 실린다 — Family 별로 갈린다.
    bodies2 = _install(monkeypatch,
                       [_account(locked=True, password_change_required=True)])
    out2 = _provision("lenovo", adapter_id="redfish_lenovo_xcc2")
    assert out2["family"] == "lenovo_xcc2_accounttypes"
    assert bodies2[0].get("PasswordChangeRequired") is False
    assert "Locked" not in bodies2[0]


# ── 실제 iLO 의미를 재현한 수렴 테스트 ───────────────────────────────────────
def _ilo_device(monkeypatch, accounts, stored="<old>", target="<tgt>"):
    """실측한 iLO 동작을 그대로 흉내 내는 가짜 장비.

    - 본문에 Locked 가 있으면            -> 400 PropertyNotWritableOrUnknown
    - Password 가 다른 속성과 함께 오면  -> 200 AccountModified, **비밀번호는 안 바뀜**
    - Password 단독                      -> 200 AccountModified, 비밀번호 반영
    - Systems GET 은 저장된 비밀번호와 일치할 때만 200
    """
    state = {"password": stored}
    modified = {"@Message.ExtendedInfo": [{"MessageId": "Base.1.19.AccountModified"}]}
    rejected = {"error": {"@Message.ExtendedInfo": [
        {"MessageId": "iLO.2.36.PropertyNotWritableOrUnknown", "MessageArgs": ["Locked"]}]}}

    def _fake_patch(ip, path, body, u, p, t, v, extra_headers=None):
        if "Locked" in body:
            return 400, rejected, None
        if "Password" in body and len(body) == 1:
            state["password"] = body["Password"]
        return 200, modified, None

    def _fake_get(ip, path, u, p, t, v, *a, **k):
        if str(path).rstrip("/").endswith("Systems"):
            return (200, {}, None) if p == state["password"] else (401, {}, "HTTP 401")
        return 200, {"UserName": TARGET, "RoleId": "Administrator", "Enabled": True}, None

    monkeypatch.setattr(rg, "account_service_discover",
                        lambda *a, **k: _disc(accounts))
    monkeypatch.setattr(rg, "_patch", _fake_patch)
    monkeypatch.setattr(rg, "_get", _fake_get)
    monkeypatch.setattr(rg, "_get_response_etag", lambda *a, **k: None)
    return state


def test_hpe_repair_converges_against_real_ilo_semantics(monkeypatch):
    """수정 후: 표준 비밀번호가 실제로 적용되고 재인증까지 통과한다."""
    state = _ilo_device(monkeypatch, [_account()])
    out = _provision("hpe")
    assert state["password"] == "<tgt>", "비밀번호가 장비에 반영되지 않았다"
    assert out["write_accepted"] is True
    assert out["verification"] == "verified"
    assert out["recovered"] is True


def test_bundled_password_would_not_have_converged(monkeypatch):
    """회귀 방지: 묶어서 보내면 200 이 나와도 비밀번호가 안 바뀐다는 사실 자체를 고정한다."""
    state = _ilo_device(monkeypatch, [_account()])
    code, resp, err = rg._patch("10.0.0.1", SLOT,
                                {"Password": "<tgt>", "Enabled": True, "RoleId": "Administrator"},
                                "rec", "<rec>", 5, False)
    assert code == 200, "장비는 성공처럼 응답한다"
    assert rg.rejected_patch_properties(resp) == set(), "거부 신호도 없다"
    assert state["password"] == "<old>", "그런데 비밀번호는 바뀌지 않았다"


# ── 재인증 확인 간격 ─────────────────────────────────────────────────────────
def test_verify_delays_default_when_device_declares_no_penalty():
    assert rg.account_verify_delays({}) == rg.ACCOUNT_VERIFY_DELAYS
    assert rg.account_verify_delays(None) == rg.ACCOUNT_VERIFY_DELAYS
    assert rg.account_verify_delays({"auth_failure_delay_seconds": 0,
                                     "lockout_duration": 0}) == rg.ACCOUNT_VERIFY_DELAYS


def test_verify_delays_outlast_declared_auth_failure_penalty():
    """iLO 가 선언한 10초를 6초짜리 확인으로 덮으면 옳게 쓴 비밀번호도 401 이 된다."""
    delays = rg.account_verify_delays({"auth_failure_delay_seconds": 10})
    assert sum(delays) > 10, f"총 대기 {sum(delays)}s 가 선언된 패널티 10s 를 넘지 않는다"
    assert delays[:len(rg.ACCOUNT_VERIFY_DELAYS)] == rg.ACCOUNT_VERIFY_DELAYS


def test_verify_delays_use_lockout_duration_when_larger():
    delays = rg.account_verify_delays({"auth_failure_delay_seconds": 2, "lockout_duration": 20})
    assert sum(delays) > 20


def test_verify_delays_are_capped():
    delays = rg.account_verify_delays({"lockout_duration": 100000})
    assert sum(delays) <= rg.ACCOUNT_VERIFY_MAX_TOTAL_SECONDS


def test_verify_schedule_is_reported(monkeypatch):
    service = {"Oem": {"Hpe": {"AuthFailureDelayTimeSeconds": 10}}}
    _install(monkeypatch, [_account()], service=service)
    out = _provision("hpe")
    assert sum(out["verify_schedule_seconds"]) > 10
    assert out["policy"]["auth_failure_delay_seconds"] == 10


# ── Oem 패널티 읽기는 namespace 이름에 의존하지 않는다 ───────────────────────
@pytest.mark.parametrize("namespace", ["Hpe", "Hp", "Dell", "Lenovo", "Public", "SomeNewVendor"])
def test_auth_failure_delay_is_read_from_any_oem_namespace(namespace):
    """rule 12 R1: Oem namespace 이름으로 분기하지 않는다. 키 이름만 본다."""
    policy = rg._account_policy_of({"Oem": {namespace: {"AuthFailureDelayTimeSeconds": 7,
                                                       "AuthFailuresBeforeDelay": 1}}})
    assert policy["auth_failure_delay_seconds"] == 7
    assert policy["auth_failures_before_delay"] == 1


def test_auth_failure_delay_absent_stays_none():
    assert rg._account_policy_of({})["auth_failure_delay_seconds"] is None
    assert rg._account_policy_of({"Oem": {"Hpe": {}}})["auth_failure_delay_seconds"] is None
    assert rg._account_policy_of({"Oem": "not-a-dict"})["auth_failure_delay_seconds"] is None


def test_auth_failure_delay_ignores_non_integer():
    assert rg._account_policy_of(
        {"Oem": {"Hpe": {"AuthFailureDelayTimeSeconds": "10"}}}
    )["auth_failure_delay_seconds"] is None
    assert rg._account_policy_of(
        {"Oem": {"Hpe": {"AuthFailureDelayTimeSeconds": True}}}
    )["auth_failure_delay_seconds"] is None


# ── HPE Firmware 별 Evidence 구분 (2026-08-12 rev.2) ─────────────────────────
#
# 왜 필요한가:
#   `hpe_ilo5plus` 하나가 iLO5/6/7 전 Firmware 를 덮으면서 evidence='proven' 이었다.
#   실제로 재현한 것은 **iLO6 v1.73 한 버전**뿐이다. HPE Advisory a00159600en_us 는
#   iLO6 1.73/1.74 + iLO7 1.19/1.20 을 영향 버전으로, iLO6 1.75+ / iLO7 1.21+ 를
#   **해결 버전**으로 명시한다. iLO5 는 어느 쪽 근거도 없다.
#
#   쓰기 동작(Password 단독 PATCH)은 전 세대에서 그대로 둔다 — HPE 공식 문서가 지원하는
#   동작이고 저장소의 안전 전략이다. 갈리는 것은 **그 선택을 무엇으로 정당화하는가** 다.

@pytest.mark.parametrize("firmware,basis,evidence,advisory", [
    # 이 저장소 실장비에서 직접 재현한 유일한 버전
    ("iLO 6 v1.73", rg.ISOLATION_LIVE_PROVEN, "proven", rg.HPE_PATCH_ADVISORY),
    # HPE Advisory 영향 버전 — defect 는 OFFICIAL 이지만 우리 payload 조합은 미검증
    ("iLO 6 v1.74", rg.ISOLATION_ADVISORY, "documented", rg.HPE_PATCH_ADVISORY),
    ("iLO 7 v1.19", rg.ISOLATION_ADVISORY, "documented", rg.HPE_PATCH_ADVISORY),
    ("iLO 7 v1.20", rg.ISOLATION_ADVISORY, "documented", rg.HPE_PATCH_ADVISORY),
    # Advisory 해결 버전 — 구버전 결함을 가정하지 않는다
    ("iLO 6 v1.75", rg.ISOLATION_SAFETY, "documented", None),
    ("iLO 6 v2.10", rg.ISOLATION_SAFETY, "documented", None),
    ("iLO 7 v1.21", rg.ISOLATION_SAFETY, "documented", None),
    # Advisory 이전 버전 / iLO5 / 판독 불가 — 근거 없음
    ("iLO 6 v1.55", rg.ISOLATION_SAFETY, "documented", None),
    ("iLO 5 v3.09", rg.ISOLATION_SAFETY, "documented", None),
    ("", rg.ISOLATION_SAFETY, "documented", None),
    (None, rg.ISOLATION_SAFETY, "documented", None),
])
def test_hpe_isolation_evidence_is_scoped_to_firmware(firmware, basis, evidence, advisory):
    got_basis, got_evidence, got_advisory = rg.hpe_isolation_evidence(firmware)
    assert got_basis == basis
    assert got_evidence == evidence
    assert got_advisory == advisory


@pytest.mark.parametrize("firmware", ["iLO 5 v3.09", "iLO 6 v1.73", "iLO 6 v1.75",
                                      "iLO 7 v1.21", ""])
def test_hpe_write_behaviour_is_identical_across_firmware(monkeypatch, firmware):
    """Evidence 는 갈려도 **쓰기 동작은 같다** — 라벨만 정확해진 것이지 기능이 변한 게 아니다."""
    bodies = _install(monkeypatch, [_account()],
                      manager={"firmware_version": firmware})
    out = _provision("hpe")
    assert out["family"] == "hpe_ilo5plus"
    assert out["isolated_write"] is True
    assert list(bodies[0]) == ["Password"], "Firmware 에 따라 쓰기 방식이 달라졌다"


def test_hpe_proven_label_does_not_spread_beyond_the_tested_firmware(monkeypatch):
    """iLO6 v1.73 에서 얻은 `proven` 이 다른 Firmware 로 번지지 않는다."""
    _install(monkeypatch, [_account()], manager={"firmware_version": "iLO 6 v1.73"})
    proven = _provision("hpe")
    _install(monkeypatch, [_account()], manager={"firmware_version": "iLO 5 v3.09"})
    other = _provision("hpe")
    assert proven["evidence"] == "proven"
    assert proven["isolation_basis"] == rg.ISOLATION_LIVE_PROVEN
    assert other["evidence"] == "documented"
    assert other["isolation_basis"] == rg.ISOLATION_SAFETY
    assert other["firmware_advisory"] is None
