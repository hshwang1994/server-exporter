"""세대별 표준 계정 **생성 방식** 계약 — Dell iDRAC10 Collection POST (2026-11-16).

무엇이 있었나
-------------
사이트 Dell iDRAC10 에서 표준 계정 생성이 쓰기 전에 실패했다:
  "빈 계정 슬롯이 없어 표준 계정을 만들 수 없습니다. 사용하지 않는 계정을 정리하세요."
iDRAC10 Family 가 iDRAC9 의 slot PATCH 를 근거 없이 물려받았기 때문이다. Dell 공식 계약은
iDRAC10(1.10.17.00~) = ManagerAccountCollection POST, iDRAC9 이하 = 미리 깔린 slot PATCH 다.
사용자가 create_method 를 collection_post 로 바꾸자 생성 · 재인증이 성공했다(사이트 실측).

긴급 조치만 정식화하면 생기는 회귀
---------------------------------
Dell 의 adapter hint 는 무인증 1차 선택이라 **늘** redfish_dell_idrac10 이다(priority 120).
종전 세대 판별은 Firmware 4~7 만 iDRAC9 로 보고 나머지는 hint 를 따랐으므로, iDRAC8(2.x — 사이트
R630 8대) · 초기 iDRAC9(3.x) · Manager 를 못 읽은 Dell 이 iDRAC10 Family 로 갔다. 그 Family 가
POST 가 되면 이 장비들은 지원하지 않는 POST 1회를 거부당한다. 그래서 세대 판별을
Manager.Model → Firmware → 계정 목록 모양 → hint 순으로 바꿨고, 이 파일이 그것을 고정한다.

같은 점검에서 찾은 Lenovo 회귀
----------------------------
2026-10-27 부터 숫자 없는 'Lenovo XClarity Controller'(XCC 1세대)를 전부 XCC2 Family(POST)로 보냈다.
XCC 1세대 Purley 는 미리 깔린 slot 12개에 PATCH 로만 만든다(Lenovo 공식). 모델 + slot 모양으로 가른다.

네트워크는 0 이다 — 쓰기 seam 4개(_get/_post/_patch/_delete)와 열거 seam 을 모두 가짜로 바꾼다.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from account_seam import as_discovery  # noqa: E402

# 렌더 하네스 재사용 (tests/e2e/test_failure_reason_contract.py — ansible.cfg jinja2_native 반영)
_spec = importlib.util.spec_from_file_location(
    "_failure_reason_contract_harness_create_method",
    REPO / "tests" / "e2e" / "test_failure_reason_contract.py",
)
_harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_harness)

# 테스트용 자리표시 값 — 실제 자격이 아니다. IP 는 문서용 대역(TEST-NET-1)이다.
_IP = "192.0.2.10"
_RECOVERY_USER = "recovery-user"
_RECOVERY_PASS = "<recovery-pass>"
_TARGET_USER = "infraops"
_TARGET_PASS = "<target-pass>"

_IDRAC10 = {"model": "17G Monolithic", "firmware_version": "1.20.55.10", "manager_type": "BMC"}
_IDRAC9_R760 = {"model": "16G Monolithic", "firmware_version": "7.10.70.00", "manager_type": "BMC"}
_IDRAC9_R740_OLD = {"model": "14G Monolithic", "firmware_version": "3.36.36.36", "manager_type": "BMC"}
_IDRAC8_R630 = {"model": "13G Monolithic", "firmware_version": "2.86.86.86", "manager_type": "BMC"}
_XCC1 = {"model": "Lenovo XClarity Controller", "firmware_version": None, "manager_type": "BMC"}


def _mgr(model=None, firmware=None):
    return {"model": model, "firmware_version": firmware, "manager_type": "BMC"}


def _slots(n, filled=()):
    """미리 깔린 slot 모델 — 빈 slot 은 UserName "" + Enabled false (iDRAC7/8/9 · Lenovo Purley)."""
    out = []
    for i in range(1, n + 1):
        name = filled[i - 1] if i <= len(filled) else ""
        out.append({"slot_uri": f"/redfish/v1/AccountService/Accounts/{i}", "id": str(i),
                    "username": name, "role_id": "Administrator" if name else "",
                    "enabled": bool(name), "has_username_key": True})
    return out


def _dynamic(*names, start=2):
    """만들어진 계정만 보이는 모델 (iDRAC10 · Lenovo Whitley/XCC2/XCC3 · 다수 vendor)."""
    return [{"slot_uri": f"/redfish/v1/AccountService/Accounts/{i}", "id": str(i),
             "username": n, "role_id": "Administrator", "enabled": True,
             "has_username_key": True}
            for i, n in enumerate(names, start=start)]


def _disc(accounts, manager=None):
    return {
        "service_uri": "AccountService", "accounts_uri": "AccountService/Accounts",
        "roles_uri": None, "service": {}, "policy": rg._account_policy_of(None),
        "role_ids": [], "accounts": list(accounts), "member_total": len(accounts),
        "member_read": len(accounts), "enumeration": rg.ENUM_COMPLETE,
        "manager": manager, "errors": [], "auth_status": 200, "service_root": None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. Family 판별 — 장비가 준 값이 hint 를 이긴다
# ═══════════════════════════════════════════════════════════════════════════
_DELL_CASES = [
    # (설명, manager, accounts, hint, 기대 Family, 기대 basis)
    ("R630 iDRAC8 13G/2.86 — hint 는 늘 idrac10", _IDRAC8_R630, _slots(16, ("", "root")),
     "redfish_dell_idrac10", "dell_slot_patch", "model"),
    ("R740 초기 iDRAC9 14G/3.36", _IDRAC9_R740_OLD, _slots(16, ("", "root")),
     "redfish_dell_idrac10", "dell_slot_patch", "model"),
    ("R760 iDRAC9 16G/7.10 (사이트 10.100.15.34 사고 장비형)", _IDRAC9_R760, _slots(16, ("", "root")),
     "redfish_dell_idrac10", "dell_slot_patch", "model"),
    ("iDRAC10 17G/1.20 — hint 가 idrac9 여도", _IDRAC10, _dynamic("root"),
     "redfish_dell_idrac9", "dell_idrac10_collection_post", "model"),
    ("iDRAC10 17G — Firmware 없음", _mgr("17G Monolithic"), _dynamic("root"),
     None, "dell_idrac10_collection_post", "model"),
    ("Model 이 iDRAC10 을 직접 말함", _mgr("iDRAC10"), _dynamic("root"),
     None, "dell_idrac10_collection_post", "model"),
    ("Model 이 Firmware 보다 먼저 (12G + 1.x — Redfish 이전 iDRAC7 펌웨어대)", _mgr("12G Monolithic", "1.66.65"),
     _slots(16, ("", "root")), "redfish_dell_idrac10", "dell_slot_patch", "model"),
    ("Firmware 만 2.x (iDRAC8)", _mgr(None, "2.86.86.86"), _slots(16, ("", "root")),
     "redfish_dell_idrac10", "dell_slot_patch", "firmware"),
    ("Firmware 만 3.x (초기 iDRAC9) — 목록 모양이 동적이어도", _mgr(None, "3.36.36.36"), _dynamic("root"),
     "redfish_dell_idrac10", "dell_slot_patch", "firmware"),
    ("Firmware 만 1.x (iDRAC10)", _mgr(None, "1.10.17.00"), _slots(16, ("", "root")),
     "redfish_dell_idrac9", "dell_idrac10_collection_post", "firmware"),
    ("Manager 없음 + 미리 깔린 slot — hint idrac10 을 이긴다", None, _slots(16, ("", "root")),
     "redfish_dell_idrac10", "dell_slot_patch", "slots"),
    ("Manager 없음 + 동적 목록 → 그때만 hint", None, _dynamic("root"),
     "redfish_dell_idrac10", "dell_idrac10_collection_post", "hint"),
    ("근거 0 → 종전 기본(iDRAC9 이하)", None, _dynamic("root"),
     None, "dell_slot_patch", "default"),
]


@pytest.mark.parametrize("label,manager,accounts,hint,want,basis", _DELL_CASES,
                         ids=[c[0] for c in _DELL_CASES])
def test_dell_family_matrix(label, manager, accounts, hint, want, basis):
    fam, reasons = rg.resolve_account_family("dell", _disc(accounts, manager), hint)
    assert fam["id"] == want, f"{label}: {reasons}"
    assert any(f"basis={basis}" in r for r in reasons), f"{label}: 근거가 안 남았다 {reasons}"
    expect_method = "collection_post" if want == "dell_idrac10_collection_post" else "slot_patch"
    assert fam["create_method"] == expect_method


def test_dell_family_is_deterministic():
    """같은 입력이면 같은 Family — 판별이 호출 순서나 상태에 기대지 않는다."""
    d = _disc(_slots(16, ("", "root")), _IDRAC8_R630)
    first = rg.resolve_account_family("dell", d, "redfish_dell_idrac10")
    for _ in range(3):
        assert rg.resolve_account_family("dell", d, "redfish_dell_idrac10") == first


_LENOVO_CASES = [
    ("XCC1 Purley — 12 slot 미리 깔림, hint 는 늘 xcc3", _XCC1, _slots(12, ("USERID",)),
     "redfish_lenovo_xcc3", "lenovo_purley_slot_patch"),
    ("XCC1 Whitley — 동적 3계정(참조 미러 10_50_11_232 모양)", _XCC1,
     _dynamic("USERID", "fwupd", "vmw-vsphere-rf", start=1), "redfish_lenovo_xcc3", "lenovo_xcc2_accounttypes"),
    ("XCC2 모델 — slot 이 보여도 XCC2", _mgr("Lenovo XClarity Controller 2"), _slots(12, ("USERID",)),
     "redfish_lenovo_xcc3", "lenovo_xcc2_accounttypes"),
    ("XCC3 모델 — slot 이 보여도 XCC3", _mgr("Lenovo XClarity Controller 3"), _slots(12, ("USERID",)),
     "redfish_lenovo_xcc3", "lenovo_xcc3_accounttypes"),
    ("Manager 없음 + 12 slot + hint 없음 → 종전대로 Purley", None, _slots(12, ("USERID",)),
     None, "lenovo_purley_slot_patch"),
]


@pytest.mark.parametrize("label,manager,accounts,hint,want", _LENOVO_CASES,
                         ids=[c[0] for c in _LENOVO_CASES])
def test_lenovo_family_matrix(label, manager, accounts, hint, want):
    fam, reasons = rg.resolve_account_family("lenovo", _disc(accounts, manager), hint)
    assert fam["id"] == want, f"{label}: {reasons}"


# ═══════════════════════════════════════════════════════════════════════════
# 2. 생성 경로 — 가짜 BMC
# ═══════════════════════════════════════════════════════════════════════════
class FakeBmc:
    """쓰기 seam 을 기록하고 정해 둔 응답만 돌려준다. 네트워크 0.

    post / patch       : 쓰기 응답 (code, body, err)
    verify             : 표준 자격 재인증(GET Systems) 응답
    state              : 쓰기 뒤 계정 리소스 재조회 응답 본문
    after_accounts     : POST 가 한 번이라도 나간 뒤의 열거 결과 (None 이면 처음과 같음)
    enum_errors        : 열거 오류 → enumeration=incomplete
    """

    def __init__(self, monkeypatch, *, accounts, manager, post=None, patch=None,
                 verify=(200, {}, None), state=None, after_accounts=None, enum_errors=()):
        self.posts: list[tuple[str, dict]] = []
        self.patches: list[tuple[str, dict]] = []
        self.deletes: list[str] = []
        self.verify_calls = 0
        self._accounts = list(accounts)
        self._after = after_accounts
        self._post = post or (201, {"@odata.id": "/redfish/v1/AccountService/Accounts/3"}, None)
        self._patch = patch or (200, {}, None)
        self._verify = verify
        self._state = state if state is not None else {
            "UserName": _TARGET_USER, "Enabled": True, "RoleId": "Administrator"}
        self._enum_errors = list(enum_errors)
        monkeypatch.setattr(rg, "account_service_discover",
                            as_discovery(self._enumerate, rg, manager=manager))
        monkeypatch.setattr(rg, "_post", self._fake_post)
        monkeypatch.setattr(rg, "_patch", self._fake_patch)
        monkeypatch.setattr(rg, "_delete", self._fake_delete)
        monkeypatch.setattr(rg, "_get", self._fake_get)
        monkeypatch.setattr(rg, "_get_response_etag", lambda *a, **k: None)
        monkeypatch.setattr(rg.time, "sleep", lambda *_: None)

    def _enumerate(self, *_a):
        accounts = self._after if (self.posts and self._after is not None) else self._accounts
        return {}, list(accounts), list(self._enum_errors)

    def _fake_post(self, bmc_ip, path, body, *_a, **_k):
        self.posts.append((path, dict(body)))
        return self._post

    def _fake_patch(self, bmc_ip, path, body, *_a, **_k):
        self.patches.append((path, dict(body)))
        return self._patch

    def _fake_delete(self, bmc_ip, path, *_a, **_k):
        self.deletes.append(path)
        return 204, {}, None

    def _fake_get(self, bmc_ip, path, *_a, **_k):
        if path == "Systems":
            self.verify_calls += 1
            return self._verify
        return 200, dict(self._state), None

    @property
    def writes(self) -> int:
        return len(self.posts) + len(self.patches) + len(self.deletes)


def _provision(vendor="dell", adapter_id="redfish_dell_idrac10", **kw):
    """운영과 같은 모양으로 부른다 — Dell 의 1차 adapter 는 늘 idrac10 이다."""
    return rg.account_service_provision(
        _IP, vendor, _RECOVERY_USER, _RECOVERY_PASS, _TARGET_USER, _TARGET_PASS,
        "Administrator", 10, False, dryrun=kw.pop("dryrun", False),
        adapter_id=adapter_id, **kw)


def _messages(out):
    return " ".join(e.get("message", "") for e in out["errors"])


# ── 2-a. iDRAC10 정상 ──────────────────────────────────────────────────────
def test_idrac10_creates_with_one_collection_post(monkeypatch):
    """사이트 조치와 같은 쓰기 — Collection POST 1회, Id 없음, PATCH 0, 재조회 + 재인증까지."""
    bmc = FakeBmc(monkeypatch, accounts=_dynamic("root"), manager=_IDRAC10)
    out = _provision()

    assert out["family"] == "dell_idrac10_collection_post"
    assert out["create_method"] == "collection_post"
    assert out["method"] == "post_new"
    assert len(bmc.posts) == 1, bmc.posts
    path, body = bmc.posts[0]
    assert path == "AccountService/Accounts"
    assert set(body) == {"UserName", "Password", "Enabled", "RoleId"}, body
    assert body["UserName"] == _TARGET_USER and body["RoleId"] == "Administrator"
    assert bmc.patches == [] and bmc.deletes == []
    assert out["slot_uri"] == "/redfish/v1/AccountService/Accounts/3"
    assert out["recovered"] is True
    assert out["verification"] == "verified"
    assert bmc.verify_calls >= 1


def test_idrac10_post_without_location_finds_account_by_re_enumeration(monkeypatch):
    """201 본문에 @odata.id 가 없으면 다시 열거해서 찾는다 — 번호를 추측하지 않는다."""
    bmc = FakeBmc(monkeypatch, accounts=_dynamic("root"), manager=_IDRAC10,
                  post=(201, {}, None), after_accounts=_dynamic("root", _TARGET_USER))
    out = _provision()

    assert len(bmc.posts) == 1
    assert out["slot_uri"] == "/redfish/v1/AccountService/Accounts/3"
    assert out["recovered"] is True and out["verification"] == "verified"


# ── 2-b. iDRAC10 실패 — 쓰기는 1회로 끝나고 Gathering 근거(recovered)는 false ─────
@pytest.mark.parametrize("post", [
    (400, {"error": {"code": "Base.1.8.GeneralError", "message": "bad request"}}, "HTTP 400: Bad Request"),
    (405, {}, "HTTP 405: Method Not Allowed"),
], ids=["400", "405"])
def test_idrac10_rejected_post_is_not_retried(monkeypatch, post):
    """거부되면 끝 — 다른 body · 다른 URI · slot PATCH 로 갈아타지 않는다 (§8 결정적 쓰기 1회)."""
    bmc = FakeBmc(monkeypatch, accounts=_dynamic("root"), manager=_IDRAC10, post=post)
    out = _provision()

    assert len(bmc.posts) == 1 and bmc.patches == [] and bmc.deletes == []
    assert out["recovered"] is False
    assert out["verification"] == "failed"
    assert "표준 계정 생성 요청이 거부됐습니다." in _messages(out)
    details = " ".join(str(e.get("detail") or "") for e in out["errors"])
    assert "family=dell_idrac10_collection_post" in details
    assert bmc.verify_calls == 0, "거부된 쓰기 뒤에 표준 자격으로 두드리지 않는다"


def test_idrac10_created_but_reauth_401_fails_without_cleanup(monkeypatch):
    """201 뒤 재인증이 401 이면 실패. POST 경로는 정리(DELETE/비우기 PATCH)를 하지 않는다."""
    bmc = FakeBmc(monkeypatch, accounts=_dynamic("root"), manager=_IDRAC10,
                  verify=(401, {}, "HTTP 401"))
    out = _provision()

    assert len(bmc.posts) == 1
    assert bmc.patches == [] and bmc.deletes == []
    assert out["recovered"] is False
    assert out["verification"] == "failed"
    assert "표준 계정을 만들었지만 그 계정으로 인증되지 않았습니다." in _messages(out)


def test_idrac10_lost_response_found_on_re_read_is_settled_without_second_post(monkeypatch):
    """응답 유실 — 다시 POST 하지 않고 다시 읽어 생겼는지 본 뒤 재인증으로 판정한다."""
    bmc = FakeBmc(monkeypatch, accounts=_dynamic("root"), manager=_IDRAC10,
                  post=(0, {}, "Response lost: RemoteDisconnected: closed"),
                  after_accounts=_dynamic("root", _TARGET_USER))
    out = _provision()

    assert len(bmc.posts) == 1, "같은 POST 를 다시 보냈다"
    assert out["write_response_lost"] is True
    assert out["recovered"] is True and out["verification"] == "verified"


def test_idrac10_lost_response_not_found_fails_without_second_post(monkeypatch):
    bmc = FakeBmc(monkeypatch, accounts=_dynamic("root"), manager=_IDRAC10,
                  post=(0, {}, "Response lost: RemoteDisconnected: closed"),
                  after_accounts=_dynamic("root"))
    out = _provision()

    assert len(bmc.posts) == 1 and bmc.patches == []
    assert out["recovered"] is False
    assert out["verification"] == "failed"
    assert "다시 읽은 계정 목록에 표준 계정이 없습니다" in _messages(out)


def test_idrac10_incomplete_enumeration_writes_nothing(monkeypatch):
    """목록을 끝까지 못 읽으면(unknown) 쓰기 0 — §8 4-상태."""
    bmc = FakeBmc(monkeypatch, accounts=_dynamic("root"), manager=_IDRAC10,
                  enum_errors=[{"section": "account_service", "message": "member read failed",
                                "detail": "HTTP 500"}])
    out = _provision()

    assert bmc.writes == 0
    assert out["presence"] == rg.PRESENCE_UNKNOWN
    assert out["recovered"] is False


def test_idrac10_existing_account_is_patched_not_posted(monkeypatch):
    """계정이 이미 있으면 비밀번호 동기화(PATCH) — 생성 방식이 POST 여도 POST 는 0."""
    bmc = FakeBmc(monkeypatch, accounts=_dynamic("root", _TARGET_USER), manager=_IDRAC10)
    out = _provision()

    assert out["method"] == "patch_existing"
    assert bmc.posts == [] and bmc.deletes == []
    assert len(bmc.patches) == 1 and bmc.patches[0][0].endswith("Accounts/3")
    assert out["recovered"] is True


def test_idrac10_dryrun_records_plan_only(monkeypatch):
    bmc = FakeBmc(monkeypatch, accounts=_dynamic("root"), manager=_IDRAC10)
    out = _provision(dryrun=True)

    assert bmc.writes == 0
    assert out["method"] == "post_new" and out["create_method"] == "collection_post"
    assert out["verification"] == "skipped"
    assert out["recovered"] is False


def test_idrac10_opt_in_recreate_stays_blocked(monkeypatch):
    """opt-in DELETE+POST 재생성도 Dell 은 막는다 — iDRAC10 은 근거 부족으로(§8 보호 정책 완화 금지)."""
    bmc = FakeBmc(monkeypatch, accounts=_dynamic("root", _TARGET_USER), manager=_IDRAC10,
                  verify=(401, {}, "HTTP 401"))
    out = _provision(allow_delete_recreate=True)

    assert bmc.deletes == [] and bmc.posts == []
    assert out["recovered"] is False
    assert "Dell iDRAC10 — DELETE+POST 재생성은 실장비 검증 전이라 하지 않습니다" in _messages(out)
    assert any(e.get("detail") == "family=dell_idrac10_collection_post" for e in out["errors"])


# ── 2-c. 회귀 — iDRAC8/9 · Lenovo Purley 는 slot PATCH 그대로 ───────────────
@pytest.mark.parametrize("manager", [_IDRAC8_R630, _IDRAC9_R740_OLD, _IDRAC9_R760],
                         ids=["idrac8-r630", "idrac9-3x", "idrac9-7x"])
def test_idrac9_and_older_still_create_by_slot_patch(monkeypatch, manager):
    """운영 hint(idrac10) 그대로 불러도 iDRAC9 이하는 빈 slot PATCH 1회 · POST 0."""
    bmc = FakeBmc(monkeypatch, accounts=_slots(16, ("", "root")), manager=manager)
    out = _provision()

    assert out["family"] == "dell_slot_patch"
    assert out["method"] == "patch_empty_slot"
    assert bmc.posts == [] and bmc.deletes == []
    assert len(bmc.patches) == 1
    path, body = bmc.patches[0]
    assert path.endswith("Accounts/3"), "slot 1(예약) · slot 2(root) 를 건너뛰어야 한다"
    assert set(body) <= {"UserName", "Password", "Enabled", "RoleId"}
    assert out["recovered"] is True and out["verification"] == "verified"


def test_idrac9_with_no_empty_slot_stops_before_any_write(monkeypatch):
    """iDRAC9 에서 slot 이 꽉 차면 종전 오류 그대로 — 쓰기 0, POST 로 바꿔 보지 않는다."""
    full = _slots(16, ("",) + tuple(f"user{i}" for i in range(2, 17)))
    bmc = FakeBmc(monkeypatch, accounts=full, manager=_IDRAC9_R760)
    out = _provision()

    assert bmc.writes == 0
    assert out["recovered"] is False
    assert "빈 계정 슬롯이 없어 표준 계정을 만들 수 없습니다." in _messages(out)


def test_lenovo_purley_creates_by_slot_patch(monkeypatch):
    """XCC 1세대 Purley — 운영 hint(xcc3) 그대로여도 slot PATCH 1회 · POST 0."""
    bmc = FakeBmc(monkeypatch, accounts=_slots(12, ("USERID",)), manager=_XCC1)
    out = _provision(vendor="lenovo", adapter_id="redfish_lenovo_xcc3")

    assert out["family"] == "lenovo_purley_slot_patch"
    assert out["method"] == "patch_empty_slot"
    assert bmc.posts == []
    assert len(bmc.patches) == 1 and bmc.patches[0][0].endswith("Accounts/2")
    assert "PasswordChangeRequired" not in bmc.patches[0][1]
    assert out["recovered"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 3. Ansible — 생성 · 동기화가 확인되지 않으면 표준 계정 재수집을 하지 않는다
# ═══════════════════════════════════════════════════════════════════════════
_PHASE3 = "redfish | re-collect with standard account (after recovery)"


def _phase3_conditions() -> list[str]:
    for play in _harness._plays("redfish-gather/site.yml"):
        for task in _harness._iter_tasks(play.get("tasks", [])):
            if (task.get("name") or "") == _PHASE3:
                return [str(c) for c in task["when"]]
    raise AssertionError(f"site.yml 에 {_PHASE3!r} 가 없다")


def _phase3_runs(ctx: dict[str, Any]) -> bool:
    env = _harness._env()
    for cond in _phase3_conditions():
        got = env.from_string("{{ (" + cond + ") }}").render(**ctx)
        assert isinstance(got, bool), (cond, got)
        if not got:
            return False
    return True


@pytest.mark.parametrize("verification", ["verified", "failed", "state_mismatch", "skipped", "none", None])
@pytest.mark.parametrize("dryrun", [True, False])
@pytest.mark.parametrize("recovered", [True, False])
@pytest.mark.parametrize("allowed", [True, False])
def test_phase3_recollect_truth_table(allowed, recovered, dryrun, verification):
    """production site.yml 의 when 을 그대로 렌더한다. 재수집은 (허용, 복구, 실쓰기, verified) 일 때만."""
    meta: dict[str, Any] = {"recovered": recovered, "dryrun": dryrun}
    if verification is not None:
        meta["verification"] = verification
    ctx = {"_rf_account_reconcile_allowed": allowed, "_rf_account_service_meta": meta}
    expected = allowed and recovered and not dryrun and verification == "verified"
    assert _phase3_runs(ctx) is expected


def test_phase3_does_not_run_without_account_meta():
    """모듈이 결과 없이 끝나 meta 가 없으면 재수집하지 않는다 → 아래 abort 가 실패 결과를 만든다."""
    assert _phase3_runs({"_rf_account_reconcile_allowed": True}) is False


@pytest.mark.parametrize("scenario,bmc_kw", [
    ("rejected", {"post": (400, {}, "HTTP 400: Bad Request")}),
    ("reauth_401", {"verify": (401, {}, "HTTP 401")}),
    ("lost_not_found", {"post": (0, {}, "Response lost: RemoteDisconnected: closed"),
                        "after_accounts": _dynamic("root")}),
])
def test_failed_idrac10_create_never_opens_phase3(monkeypatch, scenario, bmc_kw):
    """모듈 실패 결과를 Ansible 조건에 그대로 넣으면 재수집이 열리지 않는다 (모듈 ↔ site.yml 연결)."""
    FakeBmc(monkeypatch, accounts=_dynamic("root"), manager=_IDRAC10, **bmc_kw)
    out = _provision()
    meta = {"recovered": out["recovered"], "dryrun": False, "verification": out["verification"]}
    assert _phase3_runs({"_rf_account_reconcile_allowed": True,
                         "_rf_account_service_meta": meta}) is False, scenario
