"""진단 축 — 쓰지 않고 알려주는 것들.

계정 Reconcile 이 실패했을 때 원인을 "비밀번호가 틀렸다" 하나로 몰면, 실제 원인이
다른 곳에 있어도 계속 같은 Write 를 반복하게 된다. 이 파일은 **쓰지 않고 관측만 하는**
축들이 실제로 관측되고 진단에 남는지 고정한다.

    - Huawei  : 계정별 Redfish Login Interface (07 §10/§12) — 켜는 payload 는 미확보라 미구현
    - Dell/Lenovo/QCT : HTTPBasicAuth / Oem.*.AuthMethods (02 §24, 03 §23, 09 §23)
    - 전 Vendor : Global 표준 비밀번호 ↔ 장비 정책의 구조적 충돌 (04 §21, 06 §20)
    - 전 Vendor : 장비가 알려 준 Roles 목록에 없는 RoleId (08 §9/§29)
    - 전 Vendor : 계정 잠금 전에 재인증 확인을 멈추는 예산 (02 §22/§23)

어느 것도 **정책을 바꾸지 않는다.** Basic Auth 를 켜지도, 잠금 정책을 완화하지도,
비밀번호를 바꾸거나 회전시키지도 않는다.
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


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)


def _account(**kw):
    base = {"slot_uri": "/redfish/v1/AccountService/Accounts/3", "id": "3",
            "username": TARGET, "role_id": "Administrator", "enabled": True,
            "locked": None, "account_types": None, "password_change_required": None,
            "has_username_key": True}
    base.update(kw)
    return base


def _run(monkeypatch, vendor, accounts, service=None, role_ids=(), **kw):
    monkeypatch.setattr(rg, "account_service_discover", as_discovery(
        lambda *a, **k: (service if service is not None else {}, accounts, []),
        rg, role_ids=list(role_ids)))
    monkeypatch.setattr(rg, "_patch", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg, "_post", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda b, path, *a, **k:
                        (200, {}, None) if str(path).endswith("Systems")
                        else (200, {"UserName": TARGET, "Enabled": True}, None))
    return rg.account_service_provision(
        "10.0.0.1", vendor, "rec", "<rec>", TARGET, "<tgt>",
        "Administrator", 5, False, dryrun=False, **kw)


def _messages(out):
    return " ".join(str(e.get("message")) for e in out["errors"])


# ── Huawei: 계정별 Redfish Login Interface ───────────────────────────────────

def test_redfish_login_interface_off_is_reported_not_guessed(monkeypatch):
    """Redfish 접근이 꺼진 계정을 '비밀번호 문제' 로 오진하지 않는다.

    Huawei iBMC 는 Local User 마다 Web/SNMP/IPMI/SSH/SFTP/Local/**Redfish** 를 개별로
    켜고 끈다. 계정도 권한도 비밀번호도 맞는데 Redfish 가 꺼져 있으면 인증이 실패한다.
    **켜는 OEM payload 는 공식 자료에서 확인되지 않아 구현하지 않는다** — 관측만 한다.
    """
    acct = _account(login_interfaces=["Web", "SNMP", "IPMI", "SSH", "Local"])
    out = _run(monkeypatch, "huawei", [acct])
    assert out["login_interfaces"] == ["Web", "SNMP", "IPMI", "SSH", "Local"]
    assert "Redfish 접근" in _messages(out)


def test_redfish_login_interface_on_is_not_reported(monkeypatch):
    acct = _account(login_interfaces=["Web", "Redfish", "Local"])
    out = _run(monkeypatch, "huawei", [acct])
    assert "Redfish 접근" not in _messages(out)


def test_login_interface_absent_is_not_treated_as_off(monkeypatch):
    """속성을 주지 않는 장비를 '꺼져 있다' 로 읽지 않는다 — 모름과 꺼짐은 다르다."""
    out = _run(monkeypatch, "huawei", [_account()])
    assert out["login_interfaces"] is None
    assert "Redfish 접근" not in _messages(out)


def test_login_interface_is_read_from_any_oem_namespace():
    """OEM namespace 이름으로 분기하지 않는다 (rule 12 R1) — 키 이름만 본다."""
    for ns in ("Huawei", "Public", "Vendor_X"):
        data = {"Oem": {ns: {"LoginInterface": ["Web", "Redfish"]}}}
        assert rg._account_login_interfaces(data) == ["Web", "Redfish"]
    assert rg._account_login_interfaces({"Oem": {"X": {"Unrelated": ["a"]}}}) is None
    assert rg._account_login_interfaces({}) is None


# ── HTTPBasicAuth / AuthMethods ──────────────────────────────────────────────

def test_http_basic_auth_state_is_captured_but_never_changed(monkeypatch):
    """`Disabled` 를 '비밀번호가 틀렸다' 로 오진하지 않도록 상태를 남긴다.

    **자동으로 켜지 않는다.** 인증 방식을 바꾸는 것은 Account Reconcile 의 일이 아니다.
    """
    writes = []
    svc = {"HTTPBasicAuth": "Disabled",
           "Oem": {"OpenBMC": {"AuthMethods": {"BasicAuth": False, "SessionToken": True}}}}
    monkeypatch.setattr(rg, "account_service_discover",
                        as_discovery(lambda *a, **k: (svc, [_account()], []), rg))
    monkeypatch.setattr(rg, "_patch",
                        lambda *a, **k: writes.append("patch") or (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda b, path, *a, **k:
                        (200, {}, None) if str(path).endswith("Systems")
                        else (200, {"UserName": TARGET, "Enabled": True}, None))
    out = rg.account_service_provision(
        "10.0.0.1", "quanta", "rec", "<rec>", TARGET, "<tgt>",
        "Administrator", 5, False, dryrun=False)

    assert out["policy"]["http_basic_auth"] == "Disabled"
    assert out["policy"]["auth_methods"] == {"BasicAuth": False, "SessionToken": True}
    # 인증 방식을 되살리려는 쓰기가 있으면 안 된다 — 계정 PATCH 하나뿐.
    assert writes == ["patch"]


def test_unadvertised_is_not_confused_with_disabled():
    """`Unadvertised` 는 사용 불가가 아니다 — 이 client 는 선제 Authorization 을 보낸다."""
    policy = rg._account_policy_of({"HTTPBasicAuth": "Unadvertised"})
    assert policy["http_basic_auth"] == "Unadvertised"
    assert rg._account_policy_of({})["http_basic_auth"] is None


# ── Global Password ↔ 장비 정책 충돌 ─────────────────────────────────────────

def test_impossible_declared_range_is_reported_as_policy_conflict(monkeypatch):
    """min > max 는 어떤 비밀번호로도 만족할 수 없다 — 코드 버그가 아니라 정책 문제다."""
    svc = {"MinPasswordLength": 16, "MaxPasswordLength": 14}
    out = _run(monkeypatch, "cisco", [_account()], service=svc)
    assert out["policy_conflict"]["kind"] == "declared_range_impossible"
    assert out["policy_conflict"]["min_password_length"] == 16
    assert out["policy_conflict"]["max_password_length"] == 14


def test_password_outside_declared_range_still_attempts_one_write(monkeypatch):
    """차단하지 않는다 — 1회 쓰고 장비 응답과 Fresh Auth 로 확정한다."""
    writes = []
    svc = {"MinPasswordLength": 30, "MaxPasswordLength": 40}
    monkeypatch.setattr(rg, "account_service_discover",
                        as_discovery(lambda *a, **k: (svc, [_account()], []), rg))
    monkeypatch.setattr(rg, "_patch",
                        lambda *a, **k: writes.append(1) or (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda b, path, *a, **k:
                        (200, {}, None) if str(path).endswith("Systems")
                        else (200, {"UserName": TARGET, "Enabled": True}, None))
    out = rg.account_service_provision(
        "10.0.0.1", "lenovo", "rec", "<rec>", TARGET, "<tgt>",
        "Administrator", 5, False, dryrun=False)

    assert out["policy_conflict"]["kind"] == "password_outside_declared_range"
    assert len(writes) == 1, "정책 충돌을 이유로 반복 Write 하거나 아예 막으면 안 된다"
    assert out["recovered"] is True


def test_policy_conflict_never_records_the_password_itself(monkeypatch):
    svc = {"MinPasswordLength": 30, "MaxPasswordLength": 40}
    out = _run(monkeypatch, "lenovo", [_account()], service=svc)
    blob = str(out["policy"]) + str(out["policy_conflict"])
    assert "<tgt>" not in blob
    assert "password_length" not in blob.replace("min_password_length", "") \
        .replace("max_password_length", "")


# ── 장비가 모르는 RoleId ─────────────────────────────────────────────────────

def test_unsupported_role_id_is_reported(monkeypatch):
    """Fujitsu 는 RedfishAdmin 계열 Role 을 쓰지만 그것이 RoleId literal 이라는 근거는 없다.

    추측해서 바꾸지 않는다 — 보내되 근거가 없다는 사실을 남긴다 (08 §9/§29).
    """
    out = _run(monkeypatch, "fujitsu", [_account()],
               role_ids=["RedfishAdmin", "RedfishOperator", "RedfishReadOnly"])
    assert out["role_id_unsupported"] is True
    assert "권한 목록" in _messages(out)


def test_supported_role_id_is_not_reported(monkeypatch):
    out = _run(monkeypatch, "lenovo", [_account()],
               role_ids=["Administrator", "Operator", "ReadOnly"])
    assert out["role_id_unsupported"] is False


def test_no_role_list_means_no_claim(monkeypatch):
    """장비가 Roles 를 안 알려주면 '틀렸다' 고 하지 않는다."""
    out = _run(monkeypatch, "lenovo", [_account()], role_ids=[])
    assert out["role_id_unsupported"] is False


# ── 인증 예산 ────────────────────────────────────────────────────────────────

def test_auth_budget_comes_from_the_declared_lockout_threshold():
    """예산은 장비가 선언한 임계에서 끌어온다 — 재시도를 늘리는 값이 아니다."""
    assert rg.account_auth_budget({"lockout_threshold": 5}) == 4
    assert rg.account_auth_budget({"lockout_threshold": 3}) == 2
    assert rg.account_auth_budget({"lockout_threshold": 1}) == 1
    # 0 / 미제공을 "제한 없음" 으로 읽지 않는다 — Dell 은 0 이어도 IP Blocking 이 돈다.
    assert rg.account_auth_budget({"lockout_threshold": 0}) == rg.ACCOUNT_DEFAULT_AUTH_BUDGET
    assert rg.account_auth_budget({}) == rg.ACCOUNT_DEFAULT_AUTH_BUDGET
    assert rg.account_auth_budget(None) == rg.ACCOUNT_DEFAULT_AUTH_BUDGET


def test_verification_stops_before_locking_the_standard_account(monkeypatch):
    """예산을 넘기면서까지 확인하지 않는다 — 여기서 더 시도하면 계정이 잠긴다."""
    attempts = {"n": 0}

    def fake_get(bmc_ip, path, *a, **k):
        if str(path).endswith("Systems"):
            attempts["n"] += 1
            return 401, {}, "HTTP 401"
        return 200, {"UserName": TARGET, "Enabled": True}, None

    svc = {"AccountLockoutThreshold": 2}   # 예산 1회
    monkeypatch.setattr(rg, "account_service_discover",
                        as_discovery(lambda *a, **k: (svc, [_account()], []), rg))
    monkeypatch.setattr(rg, "_patch", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg, "_get", fake_get)

    out = rg.account_service_provision(
        "10.0.0.1", "lenovo", "rec", "<rec>", TARGET, "<tgt>",
        "Administrator", 5, False, dryrun=False)

    assert out["auth_budget_limit"] == 1
    assert attempts["n"] == 1, f"예산 1회인데 {attempts['n']}회 시도했다"
    assert out["auth_budget_exhausted"] is True
    assert out["verification"] == "failed"
    assert "잠금 한도" in _messages(out)


def test_budget_does_not_shorten_a_normal_verification(monkeypatch):
    """정책이 없으면 종전 확인 횟수를 줄이지 않는다 (회귀 방지)."""
    attempts = {"n": 0}

    def fake_get(bmc_ip, path, *a, **k):
        if str(path).endswith("Systems"):
            attempts["n"] += 1
            return 401, {}, "HTTP 401"
        return 200, {"UserName": TARGET, "Enabled": True}, None

    monkeypatch.setattr(rg, "account_service_discover",
                        as_discovery(lambda *a, **k: ({}, [_account()], []), rg))
    monkeypatch.setattr(rg, "_patch", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg, "_get", fake_get)

    rg.account_service_provision(
        "10.0.0.1", "lenovo", "rec", "<rec>", TARGET, "<tgt>",
        "Administrator", 5, False, dryrun=False)

    assert attempts["n"] == len(rg.ACCOUNT_VERIFY_DELAYS)
