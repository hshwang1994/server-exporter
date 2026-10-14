"""HPE RMC(CSUS 3200 / Superdome Flex) 표준 계정 생성 — `Enabled` 를 보내지 않는다 (2026-10-14 hotfix).

사이트 실측(CSUS 3200, RMC RedfishVersion 1.19):
    표준 401 → 복구 인증 성공 → infraops 부재 → POST /AccountService/Accounts
    {UserName, Password, Enabled, RoleId}  →  HTTP 400
    Base.1.17.GeneralError | "The property Enabled is not in the list of valid properties for the resource."
    | "Remove the unknown property from the request body and resubmit the request if the operation failed."
    → write_accepted=False → 재시도 없음(계약) → 표준 계정 생성 실패 → Portal `auth_rejected`.

종전에는 HPE RMC 가 `generic_collection_post` 로 떨어져 기본 계약(Enabled create=writable)이 그 속성을 보냈다.
이 파일은 (1) RMC Family 가 Enabled 를 create/repair 어디서도 보내지 않음, (2) 사고 응답을 거부로 해석함,
(3) 계정 레코드 `enabled` 가 3-상태(True/False/None)라 속성을 노출하지 않는 장비에 repair 가 Enabled 를
보내지 않음, (4) full_body Family(Lenovo XCC2)는 종전대로 함께 싣는 것을 고정한다.
공식 RMC 계정 계약은 미확보(DOCUMENT-GAP) — UserName/Password/RoleId 수락은 실장비로만 확정된다.
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
CSUS_HINT = "redfish_hpe_csus_3200"

# 사이트 실측 응답 모양(값은 메시지 레지스트리 표준 문구 — 비밀 없음)
RMC_REJECT_BODY = {
    "error": {
        "code": "Base.1.17.GeneralError",
        "message": "A general error has occurred. See Resolution for information on how to "
                   "resolve the error, or @Message.ExtendedInfo if Resolution is not provided.",
        "@Message.ExtendedInfo": [{
            "@odata.type": "#Message.v1_1_1.Message",
            "MessageId": "Base.1.17.PropertyUnknown",
            "Message": "The property Enabled is not in the list of valid properties for the resource.",
            "MessageArgs": ["Enabled"],
            "MessageSeverity": "Warning",
            "Resolution": "Remove the unknown property from the request body and resubmit the "
                          "request if the operation failed.",
        }],
    }
}


def _as_discovery(fn, **overrides):
    return as_discovery(fn, rg, **overrides)


def _account(**kw):
    base = {
        "slot_uri": "/redfish/v1/AccountService/Accounts/3",
        "id": "3", "username": TARGET, "role_id": "Administrator",
        "enabled": True, "locked": None, "account_types": None,
        "password_change_required": None, "odata_type": "", "has_username_key": True,
    }
    base.update(kw)
    return base


def _provision(vendor, **kw):
    return rg.account_service_provision(
        "10.0.0.1", vendor, "rec", "<rec>", TARGET, "<tgt>",
        "Administrator", 5, False, dryrun=False, **kw)


def _get_router(account_body):
    """Systems(재인증) 200 · 계정 리소스 GET 은 주어진 본문 · 그 외 200 빈 dict."""
    def _get(bmc_ip, path, *a, **k):
        key = str(path)
        if key.endswith("Systems"):
            return 200, {}, None
        if "AccountService/Accounts/" in key:
            return 200, dict(account_body), None
        return 200, {}, None
    return _get


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)
    monkeypatch.setattr(rg, "_get_response_etag", lambda *a, **k: None)


# ── (1) Family 계약 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("hint", ["redfish_hpe_csus_3200", "redfish_hpe_superdome_flex"])
def test_rmc_family_never_sends_enabled(hint):
    fam, reasons = rg.resolve_account_family("hpe", {
        "service": {}, "accounts": [], "role_ids": [], "policy": rg._account_policy_of(None),
        "manager": None, "enumeration": rg.ENUM_COMPLETE, "errors": [],
    }, hint)
    assert fam["id"] == "hpe_rmc", reasons
    assert fam["evidence"] == "unverified"
    assert fam["create_method"] == "collection_post"
    assert rg.account_prop_contract(fam, "Enabled", "create") == "unsupported"
    assert rg.account_prop_contract(fam, "Enabled", "repair") == "unverified"
    body = rg.build_create_payload(fam, TARGET, "<tgt>", "Administrator")
    assert set(body) == {"UserName", "Password", "RoleId"}


# ── (2) 사고 응답은 거부다 — generic 이 보내던 Enabled 가 원인 ─────────────────

def test_incident_body_is_a_rejection_of_enabled_for_the_generic_payload():
    generic = rg.account_family("generic_collection_post")
    requested = set(rg.build_create_payload(generic, TARGET, "<tgt>", "Administrator"))
    assert "Enabled" in requested, "generic 기본 계약이 Enabled 를 보낸다 — 이 사실이 사고의 전제다"
    ok, reason = rg.interpret_write_response(generic, 400, RMC_REJECT_BODY,
                                             "HTTP 400: Bad Request", requested=requested)
    assert ok is False
    rejected = rg.write_rejections(RMC_REJECT_BODY, requested)
    assert [r["property"] for r in rejected] == ["Enabled"]
    assert rejected[0]["message_id"].endswith("PropertyUnknown")
    info = rg._extended_info(RMC_REJECT_BODY)
    assert "Enabled" in info and "Base.1.17.GeneralError" in info


# ── (3) RMC 생성: 한 번의 POST, Enabled 없음, 재조회 + 재인증까지 ───────────────

def test_rmc_create_posts_once_without_enabled_and_is_verified(monkeypatch):
    posts = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        posts.append((path, dict(body)))
        if "Enabled" in body:            # 사이트 실측 재현 — Enabled 가 실리면 RMC 는 거부한다
            return 400, RMC_REJECT_BODY, "HTTP 400: Bad Request"
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/4",
                     "UserName": TARGET, "RoleId": "Administrator"}, None

    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, [], []), role_ids=["Administrator"]))
    monkeypatch.setattr(rg, "_post", fake_post)
    # RMC 계정 리소스는 Enabled 를 노출하지 않는다 — 재조회 상태 대조가 '없는 속성' 을 틀렸다고 하면 안 된다
    monkeypatch.setattr(rg, "_get", _get_router({"UserName": TARGET, "RoleId": "Administrator"}))

    out = _provision("hpe", adapter_id=CSUS_HINT)

    assert out["family"] == "hpe_rmc"
    assert len(posts) == 1, "쓰기는 한 번이다"
    assert posts[0][0] == "AccountService/Accounts"
    assert "Enabled" not in posts[0][1]
    assert set(posts[0][1]) == {"UserName", "Password", "RoleId"}
    assert out["write_accepted"] is True
    assert out["recovered"] is True
    assert out["verification"] == "verified"
    assert out["method"] == "post_new" and out["action"] == "create"


def test_rmc_create_rejection_is_reported_without_retry(monkeypatch):
    """RMC 가 다른 이유로 거부해도 payload 를 바꿔 다시 쓰지 않는다 (계약 불변)."""
    posts = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        posts.append(dict(body))
        return 400, RMC_REJECT_BODY, "HTTP 400: Bad Request"

    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, [], [])))
    monkeypatch.setattr(rg, "_post", fake_post)
    monkeypatch.setattr(rg, "_get", _get_router({"UserName": TARGET}))

    out = _provision("hpe", adapter_id=CSUS_HINT)

    assert out["family"] == "hpe_rmc"
    assert len(posts) == 1
    assert "Enabled" not in posts[0]
    assert out["write_accepted"] is False and out["recovered"] is False
    assert out["vendor_status"] == "HTTP 400: Bad Request"
    # 우리가 보내지 않은 속성(Enabled)을 가리키는 거부는 '우리 요청의 거부' 로 세지 않는다 (requested 필터) —
    # 그래도 장비가 준 원문은 detail 로 남아 사람이 본다.
    assert out["write_rejections"] == []
    assert "Enabled" in (out["write_response_info"] or "")
    assert any("거부" in str(e.get("message", "")) for e in out["errors"])


# ── (4) repair: Enabled 는 관측 False 일 때만 ────────────────────────────────

def test_repair_skips_enabled_when_device_does_not_expose_it(monkeypatch):
    """계정 리소스에 Enabled 가 없으면(None) generic repair 도 Enabled 를 보내지 않는다."""
    patches = []

    def fake_patch(bmc_ip, path, b, u, p, t, v, extra_headers=None):
        patches.append(dict(b))
        return 200, {}, None

    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, [_account(enabled=None)], [])))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", _get_router({"UserName": TARGET, "RoleId": "Administrator"}))

    out = _provision("fujitsu")

    assert out["family"] == "generic_collection_post"
    assert len(patches) == 1
    assert "Password" in patches[0]
    assert "Enabled" not in patches[0], "노출되지 않은 속성을 추측해 보냈다"
    assert out["recovered"] is True


def test_repair_sends_enabled_when_observed_disabled(monkeypatch):
    patches = []

    def fake_patch(bmc_ip, path, b, u, p, t, v, extra_headers=None):
        patches.append(dict(b))
        return 200, {}, None

    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, [_account(enabled=False)], [])))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", _get_router({"UserName": TARGET, "Enabled": True}))

    _provision("fujitsu")

    assert len(patches) == 1
    assert patches[0].get("Enabled") is True, "비활성이 관측됐는데 켜지 않았다"


def test_rmc_repair_never_sends_enabled_even_when_disabled_is_observed(monkeypatch):
    """hpe_rmc 는 Enabled repair 가 unverified 다 — 관측값이 False 여도 보내지 않는다 (계약 미확보)."""
    patches = []

    def fake_patch(bmc_ip, path, b, u, p, t, v, extra_headers=None):
        patches.append(dict(b))
        return 200, {}, None

    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, [_account(enabled=False)], [])))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", _get_router({"UserName": TARGET}))

    out = _provision("hpe", adapter_id=CSUS_HINT)

    assert out["family"] == "hpe_rmc"
    assert len(patches) == 1
    assert "Enabled" not in patches[0]
    assert "Password" in patches[0]


def test_full_body_family_still_sends_enabled_without_drift(monkeypatch):
    """Lenovo XCC2 full_body 예외는 그대로다 — Enabled 관측값과 무관하게 함께 싣는다."""
    patches = []

    def fake_patch(bmc_ip, path, b, u, p, t, v, extra_headers=None):
        patches.append(dict(b))
        return 200, {}, None

    acct = _account(enabled=None, account_types=["Redfish", "WebUI"], host_bootstrap=False)
    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, [acct], [])))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", _get_router(
        {"UserName": TARGET, "Enabled": True, "RoleId": "Administrator",
         "AccountTypes": ["Redfish", "WebUI"]}))

    out = _provision("lenovo", adapter_id="redfish_lenovo_xcc")

    assert out["family"] == "lenovo_xcc2_accounttypes"
    assert len(patches) >= 1
    assert patches[0].get("Enabled") is True


# ── (5) discovery: enabled 3-상태 ────────────────────────────────────────────

def _transport(member):
    coll = {"Members": [{"@odata.id": f"/redfish/v1/AccountService/Accounts/{member['Id']}"}],
            "Members@odata.count": 1}
    service = {"@odata.id": "/redfish/v1/AccountService",
               "Accounts": {"@odata.id": "/redfish/v1/AccountService/Accounts"}}

    def _get(bmc_ip, path, u, p, t, v):
        key = rg._p(path) if path else ""
        if key == "":
            return 200, {"AccountService": {"@odata.id": "/redfish/v1/AccountService"}}, None
        if key == "AccountService":
            return 200, service, None
        if key == "AccountService/Accounts":
            return 200, coll, None
        if key == f"AccountService/Accounts/{member['Id']}":
            return 200, member, None
        return 404, {}, "HTTP 404: Not Found"
    return _get


@pytest.mark.parametrize("raw,expected", [
    ({}, None),                   # 속성 없음 → 모름
    ({"Enabled": True}, True),
    ({"Enabled": False}, False),
    ({"Enabled": "true"}, None),  # bool 이 아니면 모름 — 추측하지 않는다
])
def test_discovery_enabled_is_tristate(monkeypatch, raw, expected):
    member = {"Id": "3", "UserName": TARGET, "RoleId": "Administrator",
              "@odata.type": "#ManagerAccount.v1_8_0.ManagerAccount"}
    member.update(raw)
    monkeypatch.setattr(rg, "_get", _transport(member))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)
    assert d["enumeration"] == rg.ENUM_COMPLETE
    assert d["accounts"][0]["enabled"] is expected


def test_bool_or_none_helper():
    assert rg._bool_or_none(True) is True
    assert rg._bool_or_none(False) is False
    assert rg._bool_or_none(None) is None
    assert rg._bool_or_none("false") is None
    assert rg._bool_or_none(0) is None
