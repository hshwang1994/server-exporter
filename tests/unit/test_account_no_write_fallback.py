"""Blind write fallback 0 — 계정 쓰기는 **한 번**만 한다.

무엇을 지키려는가
-----------------
9 Vendor 공식 조사가 공통으로 금지한 것은 "실패하면 다른 payload / 다른 URI / 다른 slot 으로
다시 써 본다" 는 패턴이다. 무엇을 보낼지는 응답을 보고 정하는 것이 아니라, 쓰기 **전에**
Family Property Contract 와 Create URI 계약이 정한다.

    05 §19/§34/§39-D · 06 §17/§31-F · 07 §17/§40-E · 08 §17/§32-C/§37-13 · 09 §19/§45-D

허용되는 다중 쓰기는 정확히 두 가지뿐이고, 둘 다 **fallback 이 아니다**:

    (A) ETag 412 concurrency retry
        동일 URI + 동일 Payload + 새로 받은 ETag, 정확히 1회.
        payload 를 바꾸지 않으므로 "다른 방식으로 다시 시도" 가 아니다.

    (B) Family 가 쓰기 전에 확정한 deterministic sequence
        HPE iLO 는 Password 를 다른 속성과 묶으면 조용히 버린다(실장비 통제 실험).
        그래서 Password 단독 PATCH → 실제 drift 가 있는 속성만 후속 PATCH 순서를
        **쓰기 전에** 정한다. 응답을 보고 방식을 바꾸는 것이 아니다.

이 파일은 그 경계를 고정한다.
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


# ── Create: UNVERIFIED Family 도 한 번만 쓴다 ────────────────────────────────

@pytest.mark.parametrize("vendor", ["fujitsu", "quanta", "supermicro", "inspur"])
@pytest.mark.parametrize("code", [400, 405, 409, 500])
def test_create_writes_exactly_once_whatever_the_device_answers(monkeypatch, vendor, code):
    """생성 POST 가 어떤 코드로 거부되든 **두 번째 요청은 없다.**"""
    posts = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        posts.append((path, dict(body)))
        return code, {}, f"HTTP {code}"

    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, [], [])))
    monkeypatch.setattr(rg, "_post", fake_post)
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (401, {}, "HTTP 401"))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    out = _provision(vendor)

    assert len(posts) == 1, f"{vendor}/{code}: 추측성 2차 Write 가 발생했다"
    assert out["recovered"] is False
    # 계약 근거가 없는 속성을 "혹시 되나" 하고 덧붙이지 않는다.
    assert "PasswordChangeRequired" not in posts[0][1]
    assert "Locked" not in posts[0][1]
    assert "AccountTypes" not in posts[0][1]


def test_create_uses_one_uri_and_never_switches(monkeypatch):
    """Accounts Collection 이 거부해도 AccountService 루트로 갈아타지 않는다."""
    paths = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        paths.append(path)
        return 404, {}, "HTTP 404"

    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, [], [])))
    monkeypatch.setattr(rg, "_post", fake_post)
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (401, {}, "HTTP 401"))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    _provision("supermicro")

    assert len(paths) == 1, "Create URI 를 바꿔 가며 재시도했다"
    assert len(set(paths)) == 1


# ── Repair: 거부돼도 속성을 빼고 다시 쓰지 않는다 ────────────────────────────

_READ_ONLY_ON_ROLEID = {"@Message.ExtendedInfo": [
    {"MessageId": "Base.1.12.PropertyNotWritable",
     "Message": "The property RoleId is a read only property and cannot be assigned a value.",
     "MessageArgs": ["RoleId"], "Severity": "Warning"},
]}


@pytest.mark.parametrize("code,body", [
    (400, {}),
    (405, {}),
    (200, _READ_ONLY_ON_ROLEID),   # 2xx 인데 본문이 거부 — 종전 사다리가 켜지던 지점
])
def test_repair_never_drops_a_property_and_retries(monkeypatch, code, body):
    """거부된 속성을 빼고 다시 PATCH 하던 사다리는 제거됐다.

    RoleId 가 어긋난 계정을 쓴다 — 그래야 RoleId 가 실제로 전송되고(drift-only 기본),
    장비의 "RoleId 는 read only" 거부가 **우리가 보낸 속성**에 대한 것이 된다.
    """
    patches = []

    def fake_patch(bmc_ip, path, b, u, p, t, v, extra_headers=None):
        patches.append(dict(b))
        return code, body, (None if code == 200 else f"HTTP {code}")

    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: (
                            {}, [_account(role_id="ReadOnly")], [])))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (401, {}, "HTTP 401"))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    out = _provision("lenovo")

    assert len(patches) == 1, "거부 뒤 속성을 빼고 다시 썼다"
    assert out["write_accepted"] is False
    assert out["recovered"] is False


def test_unverified_property_is_never_written(monkeypatch):
    """계약을 확보하지 못한 속성은 상태가 어긋나 있어도 **자동으로 쓰지 않는다.**

    `generic_collection_post` 는 Locked / PasswordChangeRequired / AccountTypes 가 전부
    `unverified` 다. 계정이 잠겨 있고 PasswordChangeRequired 가 켜져 있어도 그 속성들을
    보내지 않는다 — 보내도 되는지 모르기 때문이다. 상태는 errors[] 로 보고한다.
    """
    patches = []

    def fake_patch(bmc_ip, path, b, u, p, t, v, extra_headers=None):
        patches.append(dict(b))
        return 200, {}, None

    acct = _account(locked=True, password_change_required=True,
                    account_types=["IPMI"])
    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, [acct], [])))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", lambda b, path, *a, **k:
                        (200, {}, None) if str(path).endswith("Systems")
                        else (200, {"UserName": TARGET, "Enabled": True}, None))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    out = _provision("fujitsu")

    assert len(patches) == 1
    for prop in ("Locked", "PasswordChangeRequired", "AccountTypes"):
        assert prop not in patches[0], f"계약 근거 없는 {prop} 를 자동으로 썼다"
    assert out["family"] == "generic_collection_post"
    # 상태 자체는 사람에게 보고한다 — 쓰지 않는 것과 숨기는 것은 다르다.
    joined = " ".join(str(e.get("message")) for e in out["errors"])
    assert "잠금" in joined


# ── 허용되는 예외 (A) ETag 412: 동일 URI + 동일 Payload ──────────────────────

def test_etag_412_retry_keeps_uri_and_payload_identical(monkeypatch):
    """412 재시도는 payload 를 바꾸지 않는다 — 그래서 fallback 이 아니다."""
    calls = []

    def fake_patch(bmc_ip, path, body, u, p, t, v, extra_headers=None):
        calls.append((path, dict(body), dict(extra_headers or {})))
        if len(calls) == 1:
            return 412, {}, "HTTP 412"
        return 200, {"Oem": {"Public": {"Status": 0}}}, None

    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: (
                            {"Oem": {"Public": {}}}, [_account()], [])))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get_response_etag", lambda *a, **k: 'W/"etag-1"')
    monkeypatch.setattr(rg, "_get", lambda b, path, *a, **k:
                        (200, {}, None) if str(path).endswith("Systems")
                        else (200, {"UserName": TARGET, "Enabled": True}, None))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    out = _provision("inspur")

    assert out["family"] == "inspur_m6"
    assert len(calls) == 2, "412 재시도가 사라졌다"
    assert calls[0][0] == calls[1][0], "412 재시도가 URI 를 바꿨다"
    assert calls[0][1] == calls[1][1], "412 재시도가 payload 를 바꿨다 — 그건 fallback 이다"
    assert calls[1][2].get("If-Match"), "재시도에 새 ETag 를 싣지 않았다"


def test_inspur_create_does_not_send_if_match(monkeypatch):
    """Inspur 의 If-Match 는 **Repair 전용**이다. Create(Collection POST)는 요구하지 않는다.

    source: 浪潮英信服务器 Redfish用户手册 V1.2 §4.4(Create) / §4.6(Update)
    """
    etag_calls = []
    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({"Oem": {"Public": {}}}, [], [])))
    monkeypatch.setattr(rg, "_get_response_etag",
                        lambda *a, **k: etag_calls.append(1) or 'W/"e"')
    monkeypatch.setattr(rg, "_post", lambda *a, **k: (
        200, {"Oem": {"Public": {"Status": 0}},
              "@odata.id": "/redfish/v1/AccountService/Accounts/4"}, None))
    monkeypatch.setattr(rg, "_get", lambda b, path, *a, **k:
                        (200, {}, None) if str(path).endswith("Systems")
                        else (200, {"UserName": TARGET, "Enabled": True}, None))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    out = _provision("inspur")

    assert out["family"] == "inspur_m6"
    assert rg.account_if_match(rg.account_family("inspur_m6"), "create") is False
    assert etag_calls == [], "Create 경로에서 ETag 를 받아 If-Match 를 실으려 했다"


# ── 허용되는 예외 (B) HPE deterministic sequence ─────────────────────────────

def test_hpe_isolated_sequence_is_decided_before_writing(monkeypatch):
    """HPE 의 2회 쓰기는 응답을 보고 정한 것이 아니라 **미리 정해진 순서**다.

    1회차는 Password 단독, 2회차는 실제로 달라진 속성만. 1회차가 성공해도 2회차가 나가고,
    drift 가 없으면 2회차 자체가 없다 — "실패해서 다시 시도" 와 구분되는 지점이다.
    """
    bodies = []

    def fake_patch(bmc_ip, path, body, u, p, t, v, extra_headers=None):
        bodies.append(dict(body))
        return 200, {}, None

    # RoleId 가 어긋난 계정 → 후속 PATCH 에 RoleId 만 실려야 한다.
    acct = _account(role_id="ReadOnly")
    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, [acct], [])))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", lambda b, path, *a, **k:
                        (200, {}, None) if str(path).endswith("Systems")
                        else (200, {"UserName": TARGET, "Enabled": True}, None))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    out = _provision("hpe")

    assert out["family"] == "hpe_ilo5plus"
    assert out.get("isolated_write") is True
    assert len(bodies) == 2
    assert list(bodies[0]) == ["Password"], "1회차는 Password 단독이어야 한다"
    assert "Password" not in bodies[1], "후속 PATCH 에 Password 를 다시 실었다"
    assert bodies[1].get("RoleId") == "Administrator"
    # 두 번 쓰긴 했지만 첫 쓰기가 **성공**했다 — 실패 후 재시도가 아니다.
    assert out["write_accepted"] is True


def test_hpe_no_second_write_when_nothing_else_drifted(monkeypatch):
    """drift 가 없으면 후속 PATCH 자체가 없다."""
    bodies = []

    def fake_patch(bmc_ip, path, body, u, p, t, v, extra_headers=None):
        bodies.append(dict(body))
        return 200, {}, None

    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, [_account()], [])))
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", lambda b, path, *a, **k:
                        (200, {}, None) if str(path).endswith("Systems")
                        else (200, {"UserName": TARGET, "Enabled": True}, None))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    _provision("hpe")

    assert len(bodies) == 1
    assert list(bodies[0]) == ["Password"]


# ── 보호 계정: 이름이 겹쳐도 건드리지 않는다 ─────────────────────────────────

def test_protected_account_conflict_writes_nothing(monkeypatch):
    """표준 계정 이름이 `HostBootstrapAccount` 계정과 겹치면 **쓰기 0** 이다.

    이름이 같다는 이유로 특수 계정의 비밀번호/권한을 바꾸면 호스트 부팅 경로 같은 다른
    기능이 조용히 망가진다. `ambiguous` 와 같은 층의 무진행 종료로 다룬다.
    source: 03 §11.1/§24 + DMTF ManagerAccount.HostBootstrapAccount
    """
    writes = []
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(
        lambda *a, **k: ({}, [_account(host_bootstrap=True)], [])))
    monkeypatch.setattr(rg, "_patch",
                        lambda *a, **k: writes.append("patch") or (200, {}, None))
    monkeypatch.setattr(rg, "_post",
                        lambda *a, **k: writes.append("post") or (200, {}, None))
    monkeypatch.setattr(rg, "_delete",
                        lambda *a, **k: writes.append("delete") or (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    out = _provision("lenovo", adapter_id="redfish_lenovo_xcc3")

    assert out["presence"] == rg.PRESENCE_PROTECTED_CONFLICT
    assert writes == [], f"보호 계정에 쓰기가 발생했다: {writes}"
    assert out["recovered"] is False
    assert out["account_existed"] is True
    joined = " ".join(str(e.get("message")) for e in out["errors"])
    assert "예약" in joined


def test_protected_account_is_not_offered_as_an_empty_create_slot(monkeypatch):
    """보호 계정 슬롯을 '비어 있다' 고 세어 그 위에 만들지 않는다."""
    slots = []
    for i in range(1, 5):
        slots.append(_account(slot_uri=f"/redfish/v1/AccountService/Accounts/{i}",
                              id=str(i), username="", enabled=False,
                              host_bootstrap=(i == 3)))
    patched = []
    monkeypatch.setattr(rg, "account_service_discover",
                        _as_discovery(lambda *a, **k: ({}, slots, [])))
    monkeypatch.setattr(rg, "_patch", lambda ip, path, body, *a, **k:
                        patched.append(path) or (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    out = _provision("dell")

    assert out["presence"] == rg.PRESENCE_ABSENT
    assert patched, "생성 자체가 일어나지 않았다"
    assert not any(p.endswith("/3") for p in patched), \
        "HostBootstrapAccount 슬롯에 계정을 만들었다"
    # Dell slot 1 은 Family reserved — 생성 대상에서도 빠져야 한다.
    assert not any(p.endswith("/1") for p in patched)
