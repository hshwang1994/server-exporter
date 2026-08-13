"""Account Capability Discovery + 존재 판정 3-상태 (audit C-1 정면 회귀).

핵심 계약:
  "계정 목록을 못 읽었다" 는 "계정이 없다" 가 아니다.
  못 읽은 상태(UNKNOWN)에서는 **어떤 쓰기도 하지 않는다.**

종전 결함(2026-08-12 audit C-1): AccountService 는 읽혔지만 Accounts 컬렉션이
403/5xx/timeout 이거나 링크가 없으면 accounts=[] 가 되어 "대상 계정 없음" 으로
분류되고, 그대로 **실제 생성 POST** 가 나갔다. production 함수를 직접 실행해 증명됐다.
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

SERVICE_URI = "AccountService"
ACCOUNTS_URI = "AccountService/Accounts"

_SERVICE_BODY = {
    "@odata.id": "/redfish/v1/AccountService",
    "Accounts": {"@odata.id": "/redfish/v1/AccountService/Accounts"},
    "Roles": {"@odata.id": "/redfish/v1/AccountService/Roles"},
    "MinPasswordLength": 8,
    "MaxPasswordLength": 20,
    "AccountLockoutThreshold": 3,
    "AccountLockoutDuration": 60,
    "AccountLockoutCounterResetAfter": 60,
    "ServiceEnabled": True,
}


def _member(i, username="", **extra):
    body = {
        "Id": str(i), "UserName": username, "RoleId": "Administrator",
        "Enabled": bool(username), "Locked": False,
        "@odata.type": "#ManagerAccount.v1_9_0.ManagerAccount",
    }
    body.update(extra)
    return body


def _transport(members, *, service=_SERVICE_BODY, service_code=200,
               coll_code=200, member_codes=None, declared=None,
               roles=("Administrator", "Operator", "ReadOnly"), root=None):
    """URI → 응답 테이블을 만든 뒤 `_get` 대체 함수를 돌려준다."""
    member_codes = member_codes or {}
    coll = {
        "Members": [{"@odata.id": f"/redfish/v1/AccountService/Accounts/{m['Id']}"}
                    for m in members],
        "Members@odata.count": len(members) if declared is None else declared,
    }
    role_coll = {"Members": [{"@odata.id": f"/redfish/v1/AccountService/Roles/{r}"}
                             for r in roles]}

    def _get(bmc_ip, path, u, p, t, v):
        key = rg._p(path) if path else ""
        if key == "":
            return (200, root if root is not None else
                    {"AccountService": {"@odata.id": "/redfish/v1/AccountService"}}, None)
        if key == SERVICE_URI:
            if service_code != 200:
                return service_code, {}, f"HTTP {service_code}"
            return 200, service, None
        if key == ACCOUNTS_URI:
            if coll_code != 200:
                return coll_code, {}, f"HTTP {coll_code}"
            return 200, coll, None
        if key == "AccountService/Roles":
            return 200, role_coll, None
        if key.startswith("AccountService/Accounts/"):
            mid = key.rsplit("/", 1)[-1]
            code = member_codes.get(mid, 200)
            if code != 200:
                return code, {}, f"HTTP {code}"
            for m in members:
                if m["Id"] == mid:
                    return 200, m, None
        return 404, {}, "HTTP 404: Not Found"
    return _get


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)


# ── Discovery ────────────────────────────────────────────────────────────────
def test_discovery_follows_serviceroot_link_not_hardcoded_uri(monkeypatch):
    """AccountService URI 는 ServiceRoot 가 알려주는 링크를 따른다.

    Dell iDRAC7/8·초기 iDRAC9 공식 문서는 Manager-scoped 경로를 쓴다.
    source: dell.com/.../idrac_3.31.31.31_redfishapiguide/accountservice
    """
    scoped = "/redfish/v1/Managers/iDRAC.Embedded.1/AccountService"
    seen = []

    def _get(bmc_ip, path, u, p, t, v):
        seen.append(rg._p(path) if path else "")
        key = rg._p(path) if path else ""
        if key == "":
            return 200, {"AccountService": {"@odata.id": scoped}}, None
        if key == rg._p(scoped):
            return 200, {"Accounts": {"@odata.id": scoped + "/Accounts"}}, None
        if key == rg._p(scoped + "/Accounts"):
            return 200, {"Members": [], "Members@odata.count": 0}, None
        return 404, {}, "HTTP 404"

    monkeypatch.setattr(rg, "_get", _get)
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)
    assert d["service_uri"] == rg._p(scoped)
    assert d["accounts_uri"] == rg._p(scoped + "/Accounts")
    assert "AccountService" not in seen, "ServiceRoot 를 무시하고 표준 경로를 때려박았다"


def test_discovery_falls_back_when_serviceroot_has_no_link(monkeypatch):
    """링크가 없으면 종전 경로로 되돌아간다 (회귀 방지)."""
    monkeypatch.setattr(rg, "_get", _transport([_member(1, "root")], root={}))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)
    assert d["service_uri"] == "AccountService"
    assert d["enumeration"] == rg.ENUM_COMPLETE


def test_discovery_reads_policy_and_roles(monkeypatch):
    monkeypatch.setattr(rg, "_get", _transport([_member(1, "root")]))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)
    assert d["policy"]["min_password_length"] == 8
    assert d["policy"]["max_password_length"] == 20
    assert d["policy"]["lockout_threshold"] == 3
    assert d["role_ids"] == ["Administrator", "Operator", "ReadOnly"]


def test_policy_absent_fields_stay_none_not_zero():
    """없는 정책을 0 으로 접지 않는다 — '제한 없음' 과 '모름' 은 다른 사실이다."""
    p = rg._account_policy_of({"Accounts": {}})
    assert p["min_password_length"] is None
    assert p["lockout_threshold"] is None
    assert p["supported_account_types"] is None


def test_declared_member_count_mismatch_is_incomplete(monkeypatch):
    """Members@odata.count 보다 적게 읽혔으면 열거가 완전하지 않다."""
    monkeypatch.setattr(rg, "_get",
                        _transport([_member(1, "root")], declared=5))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)
    assert d["enumeration"] == rg.ENUM_INCOMPLETE


@pytest.mark.parametrize("kw,expected", [
    ({"service_code": 401}, rg.ENUM_FAILED),
    ({"service_code": 500}, rg.ENUM_FAILED),
    ({"coll_code": 403}, rg.ENUM_INCOMPLETE),
    ({"coll_code": 500}, rg.ENUM_INCOMPLETE),
    ({"member_codes": {"2": 403}}, rg.ENUM_INCOMPLETE),
])
def test_partial_read_never_reports_complete(monkeypatch, kw, expected):
    members = [_member(1, "root"), _member(2, "svc")]
    monkeypatch.setattr(rg, "_get", _transport(members, **kw))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)
    assert d["enumeration"] == expected


def test_missing_accounts_link_is_incomplete(monkeypatch):
    svc = dict(_SERVICE_BODY)
    svc.pop("Accounts")
    monkeypatch.setattr(rg, "_get", _transport([], service=svc))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)
    assert d["enumeration"] == rg.ENUM_INCOMPLETE
    assert d["service"] is not None, "서비스는 읽혔다 — 인증 실패로 분류하면 안 된다"


# ── 존재 판정 3-상태 ──────────────────────────────────────────────────────────
def test_presence_absent_requires_complete_enumeration():
    complete = {"accounts": [], "enumeration": rg.ENUM_COMPLETE}
    assert rg.account_presence(complete, "infraops")[0] == rg.PRESENCE_ABSENT
    for enum in (rg.ENUM_INCOMPLETE, rg.ENUM_FAILED):
        d = {"accounts": [], "enumeration": enum}
        assert rg.account_presence(d, "infraops")[0] == rg.PRESENCE_UNKNOWN


def test_presence_present_and_ambiguous():
    one = {"accounts": [{"username": "infraops", "id": "3"}],
           "enumeration": rg.ENUM_COMPLETE}
    assert rg.account_presence(one, "infraops")[0] == rg.PRESENCE_PRESENT
    two = {"accounts": [{"username": "infraops", "id": "3"},
                        {"username": "infraops", "id": "9"}],
           "enumeration": rg.ENUM_INCOMPLETE}
    # 중복은 열거가 불완전해도 확정할 수 있다 — 이미 두 개를 봤다.
    assert rg.account_presence(two, "infraops")[0] == rg.PRESENCE_AMBIGUOUS


# ── 쓰기 차단 (C-1 회귀) ─────────────────────────────────────────────────────
@pytest.mark.parametrize("kw", [
    {"coll_code": 403}, {"coll_code": 500},
    {"member_codes": {"2": 500}}, {"declared": 7},
])
def test_unknown_presence_writes_nothing(monkeypatch, kw):
    """열거가 불완전하면 POST / PATCH / DELETE 가 **한 건도** 나가지 않는다."""
    members = [_member(1, "root"), _member(2, "svc")]
    monkeypatch.setattr(rg, "_get", _transport(members, **kw))
    writes = []
    monkeypatch.setattr(rg, "_post", lambda *a, **k: writes.append("post"))
    monkeypatch.setattr(rg, "_patch", lambda *a, **k: writes.append("patch"))
    monkeypatch.setattr(rg, "_delete", lambda *a, **k: writes.append("delete"))

    out = rg.account_service_provision(
        "10.0.0.1", "dell", "rec", "<rec>", "infraops", "<tgt>",
        "Administrator", 5, False, dryrun=False,
    )
    assert writes == [], "계정 목록을 못 읽었는데 BMC 에 썼다"
    assert out["presence"] == rg.PRESENCE_UNKNOWN
    assert out["recovered"] is False
    assert out["method"] == "noop"
    joined = " ".join(f'{e.get("message")} {e.get("detail")}' for e in out["errors"])
    assert "완전히 확인하지 못해" in joined


def test_missing_accounts_link_writes_nothing(monkeypatch):
    """Accounts 링크가 없는 펌웨어에서도 생성으로 넘어가지 않는다."""
    svc = dict(_SERVICE_BODY)
    svc.pop("Accounts")
    monkeypatch.setattr(rg, "_get", _transport([], service=svc))
    writes = []
    monkeypatch.setattr(rg, "_post", lambda *a, **k: writes.append("post"))
    monkeypatch.setattr(rg, "_patch", lambda *a, **k: writes.append("patch"))
    out = rg.account_service_provision(
        "10.0.0.1", "hpe", "rec", "<rec>", "infraops", "<tgt>",
        "Administrator", 5, False, dryrun=False,
    )
    assert writes == []
    assert out["presence"] == rg.PRESENCE_UNKNOWN


def test_complete_enumeration_still_creates(monkeypatch):
    """기능을 지운 게 아니다 — 완전히 읽었고 없으면 종전대로 만든다."""
    monkeypatch.setattr(rg, "_get", _transport([_member(1, "root")]))
    posted = []
    monkeypatch.setattr(
        rg, "_post",
        lambda b, path, body, *a, **k: (posted.append((path, dict(body))),
                                        (201, {"@odata.id": "/redfish/v1/AccountService/Accounts/2"},
                                         None))[1])
    # 생성 후 재조회 + 재인증은 성공으로 둔다.
    base = _transport([_member(1, "root")])

    def _get(bmc_ip, path, u, p, t, v):
        if str(path).endswith("Systems"):
            return 200, {}, None
        if rg._p(path) == "AccountService/Accounts/2":
            return 200, _member(2, "infraops"), None
        return base(bmc_ip, path, u, p, t, v)

    monkeypatch.setattr(rg, "_get", _get)
    out = rg.account_service_provision(
        "10.0.0.1", "supermicro", "rec", "<rec>", "infraops", "<tgt>",
        "Administrator", 5, False, dryrun=False,
    )
    assert out["presence"] == rg.PRESENCE_ABSENT
    assert out["recovered"] is True
    assert out["verification"] == "verified"
    assert len(posted) == 1
    # 하드코딩이 아니라 discovery 가 준 URI 로 쓴다.
    assert posted[0][0] == "AccountService/Accounts"


def test_empty_slot_needs_seen_username_key(monkeypatch):
    """읽지 못한 계정을 빈 슬롯으로 분류하지 않는다 (audit M-1).

    `_safe` 는 키 부재 / null / 비-dict 를 전부 '' 로 접는다. 그대로 두면 조회에
    실패한 슬롯이 "비어 있다" 로 보여 남의 계정을 덮어쓸 수 있다.
    """
    seen_empty = {"id": "3", "username": "", "enabled": False, "has_username_key": True}
    unread = {"id": "4", "username": "", "enabled": False, "has_username_key": False}
    got = rg.account_service_find_all_empty_slots([unread, seen_empty])
    assert [a["id"] for a in got] == ["3"]
