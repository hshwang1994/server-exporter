"""Redfish Accounts 다음 페이지 · 불완전 열거 중 쓰기 금지 (2026-10-10 C3).

종전 결함(검수 2026-10-09, 외부 쓰기 대역 재현):
  - Accounts 만 첫 페이지 `Members` 를 직접 돌고 `Members@odata.nextLink` 를 읽지 않았다. count 가 없으면 첫 페이지만으로
    "완결 · 부재" 가 되어, 2페이지에 있는 표준 계정과 같은 이름으로 새 POST 를 보냈다.
  - count 가 있어 불완전(incomplete)인데도 보이는 표준 계정 1개를 PRESENT 로 보고 그 슬롯에 PATCH 를 보냈다.
계약(CLAUDE.md §8): 계정 목록을 완전히 열거하지 못한 unknown 상태에서는 Account Write 0건. 동일 표준 이름이 여러 슬롯이면 임의 수정 금지.
완결된 목록에서의 기존 복구(비밀번호 동기화 · 생성)는 그대로다.

공용 순회(_collection_walk)를 Accounts 와 다른 21개 컬렉션 소비자가 함께 쓴다. 다른 소비자의 반환 멤버 · 요청 순서 · errors · notices 는
종전 구현(아래 _reference_collection_members — 2026-10-10 이전 본문 그대로)과 같아야 한다.
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

BMC = "192.0.2.1"
ACC = "/redfish/v1/AccountService/Accounts"


def _ref(i):
    return {"@odata.id": f"{ACC}/{i}"}


def _acct(i, user, role="Administrator", **extra):
    body = {"@odata.id": f"{ACC}/{i}", "@odata.type": "#ManagerAccount.v1_9_0.ManagerAccount",
            "Id": str(i), "UserName": user, "RoleId": role, "Enabled": True, "Locked": False}
    body.update(extra)
    return body


class Bmc:
    """경로 → (status, data, err) 표로 도는 가짜 BMC. 쓰기(POST/PATCH/DELETE)는 기록만 하고 정해 둔 응답을 돌려준다."""

    def __init__(self, pages, accounts, *, count=None, links=None, roles=("Administrator", "Operator", "ReadOnly"),
                 service_uri="/redfish/v1/AccountService", overrides=None):
        self.calls = []
        self.writes = []
        self.accounts = dict(accounts)
        self.acc_base = service_uri + "/Accounts"
        svc_key = rg._p(service_uri)
        acc_key = rg._p(self.acc_base)
        self.table = {
            "": (200, {"AccountService": {"@odata.id": service_uri}}, None),
            svc_key: (200, {"Accounts": {"@odata.id": self.acc_base}, "Roles": {"@odata.id": service_uri + "/Roles"}}, None),
            rg._p(service_uri + "/Roles"): (200, {"Members": [{"@odata.id": f"{service_uri}/Roles/{r}"} for r in roles]}, None),
            "Systems": (200, {"Members": []}, None),
        }
        keys = [acc_key] + [f"{acc_key}?$skip={k}" for k in range(1, len(pages))]
        for k, mem in enumerate(pages):
            body = {"Members": [(self._ref(m) if isinstance(m, int) else m) for m in mem]}
            if mem == "absent":
                body = {}
            elif mem == "not_list":
                body = {"Members": {"@odata.id": "x"}}
            if k == 0 and count is not None:
                body["Members@odata.count"] = count
            nxt = (links or {}).get(k, f"{self.acc_base}?$skip={k + 1}" if k + 1 < len(pages) else None)
            if nxt:
                body["Members@odata.nextLink"] = nxt
            self.table[keys[k]] = (200, body, None)
        self.table.update(overrides or {})
        self.post_answer = (201, {"@odata.id": f"{self.acc_base}/9"}, None)
        self.patch_answer = (200, {}, None)

    def _ref(self, i):
        return {"@odata.id": f"{self.acc_base}/{i}"}

    def get(self, bmc_ip, path, *args, **kwargs):
        self.calls.append(path)
        if path in self.table:
            return self.table[path]
        prefix = rg._p(self.acc_base) + "/"
        if path.startswith(prefix):
            body = self.accounts.get(path[len(prefix):])
            if body is not None:
                return 200, body, None
        return 404, {}, "HTTP 404: Not Found"

    def post(self, bmc_ip, path, body, *args, **kwargs):
        self.writes.append(("POST", path, dict(body)))
        code, data, err = self.post_answer
        created = (data or {}).get("@odata.id")
        if code and 200 <= code < 300 and created:
            self.accounts[created.rsplit("/", 1)[-1]] = _acct(created.rsplit("/", 1)[-1], body.get("UserName"),
                                                               role=body.get("RoleId", "Administrator"))
        return self.post_answer

    def patch(self, bmc_ip, path, body, *args, **kwargs):
        self.writes.append(("PATCH", path, dict(body)))
        return self.patch_answer

    def delete(self, bmc_ip, path, *args, **kwargs):
        self.writes.append(("DELETE", path, {}))
        return 204, {}, None


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)


def _wire(monkeypatch, bmc):
    monkeypatch.setattr(rg, "_get", bmc.get)
    monkeypatch.setattr(rg, "_post", bmc.post)
    monkeypatch.setattr(rg, "_patch", bmc.patch)
    monkeypatch.setattr(rg, "_delete", bmc.delete)


def _provision(vendor="unknown", dryrun=False):
    return rg.account_service_provision(BMC, vendor, "recovery", "<rec>", "standard", "<std>", "Administrator", 5, False,
                                        dryrun=dryrun)


# ── 완결된 다중 페이지: 기존 복구 동작 유지 ─────────────────────────────────────────────────────────────────────

def test_standard_account_on_the_next_page_is_found_and_only_that_slot_is_synced(monkeypatch):
    """count 없음 + 2페이지에 표준 계정 — 종전에는 '완결 · 부재' 로 POST(중복 생성 시도). 이제 그 슬롯만 PATCH 1건."""
    bmc = Bmc([[1], [2]], {"1": _acct(1, "recovery"), "2": _acct(2, "standard")})
    _wire(monkeypatch, bmc)
    out = _provision()
    assert "AccountService/Accounts?$skip=1" in bmc.calls, "다음 페이지를 읽었다"
    assert out["presence"] == rg.PRESENCE_PRESENT and out["method"] == "patch_existing"
    assert out["slot_uri"] == f"{ACC}/2"
    assert [(w[0], w[1]) for w in bmc.writes] == [("PATCH", "AccountService/Accounts/2")]
    assert out["recovered"] is True and out["verification"] == "verified"


def test_absent_after_reading_every_page_still_creates_once(monkeypatch):
    """count 없음이어도 끝까지 읽어 없으면 완결 · 부재 — 종전대로 생성(POST 1건)."""
    bmc = Bmc([[1], [2]], {"1": _acct(1, "recovery"), "2": _acct(2, "operator1", role="Operator")})
    _wire(monkeypatch, bmc)
    d = rg.account_service_discover(BMC, "recovery", "<rec>", 5, False)
    assert d["enumeration"] == rg.ENUM_COMPLETE and d["member_total"] == 2 and d["member_read"] == 2
    out = _provision()
    assert out["presence"] == rg.PRESENCE_ABSENT
    assert [(w[0], w[1]) for w in bmc.writes] == [("POST", "AccountService/Accounts")]
    assert out["recovered"] is True


def test_explicit_id_choice_sees_accounts_on_later_pages(monkeypatch):
    """Cisco IMC(명시 Id 필요): 2페이지의 Id 3 을 보고 4 를 고른다 — 첫 페이지만 보면 3 을 골라 기존 계정과 겹친다."""
    bmc = Bmc([[1, 2], [3]], {"1": _acct(1, "admin", role="admin"), "2": _acct(2, "recovery", role="admin"),
                              "3": _acct(3, "svc", role="user")},
              roles=("admin", "user", "readonly"))
    bmc.post_answer = (201, {"@odata.id": f"{ACC}/4"}, None)
    _wire(monkeypatch, bmc)
    out = _provision(vendor="cisco")
    posts = [w for w in bmc.writes if w[0] == "POST"]
    assert out["family"] == "cisco_cimc_collection_post_id"
    assert len(posts) == 1 and posts[0][2].get("Id") == "4"


# ── 같은 이름 · 보호 계정: 열거가 어떻든 쓰기 0 ─────────────────────────────────────────────────────────────────

def test_same_standard_name_on_two_pages_is_ambiguous_and_writes_nothing(monkeypatch):
    """검수 재현(count=2, 1페이지 standard): 2페이지까지 읽으면 같은 이름이 두 슬롯 — 자동 처리 중단."""
    bmc = Bmc([[1], [2]], {"1": _acct(1, "standard"), "2": _acct(2, "standard")}, count=2)
    _wire(monkeypatch, bmc)
    out = _provision()
    assert out["presence"] == rg.PRESENCE_AMBIGUOUS and out["method"] == "ambiguous"
    assert bmc.writes == []


def test_protected_account_with_the_standard_name_on_a_later_page_writes_nothing(monkeypatch):
    bmc = Bmc([[1], [2]], {"1": _acct(1, "recovery"), "2": _acct(2, "standard", HostBootstrapAccount=True)})
    _wire(monkeypatch, bmc)
    out = _provision()
    assert out["presence"] == rg.PRESENCE_PROTECTED_CONFLICT and bmc.writes == []


# ── 불완전 열거: 보이는 일치가 있어도 쓰기 0 ───────────────────────────────────────────────────────────────────

_INCOMPLETE = {
    "page_failure": dict(pages=[[1, 2], [3]], overrides={"AccountService/Accounts?$skip=1": (503, {}, "HTTP 503: Service Unavailable")}),
    "member_failure": dict(pages=[[1, 2], [3]], member_fail="3"),
    "cycle": dict(pages=[[1, 2], [3]], links={1: ACC}),
    "other_origin": dict(pages=[[1, 2], [3]], links={0: "https://198.51.100.9/redfish/v1/AccountService/Accounts?$skip=1"}),
    "count_mismatch": dict(pages=[[1, 2], [3]], count=5),
    "duplicate_ref": dict(pages=[[1, 2], [2, 3]]),
    "members_absent": dict(pages=[[1, 2], "absent"]),
    "members_not_list": dict(pages=[[1, 2], "not_list"]),
    "non_object_member": dict(pages=[[1, 2], [3, "oops"]]),
    "page_cap": dict(pages=[[1, 2], [3]], cap_pages=1),
}


@pytest.mark.parametrize("case", sorted(_INCOMPLETE))
def test_incomplete_enumeration_never_writes_even_with_a_visible_standard_account(monkeypatch, case):
    spec = dict(_INCOMPLETE[case])
    accounts = {"1": _acct(1, "recovery"), "2": _acct(2, "standard"), "3": _acct(3, "svc", role="Operator")}
    member_fail = spec.pop("member_fail", None)
    cap = spec.pop("cap_pages", None)
    bmc = Bmc(accounts=accounts, **spec)
    if member_fail:
        bmc.table[f"AccountService/Accounts/{member_fail}"] = (500, {}, "HTTP 500: Internal Server Error")
    if cap:
        monkeypatch.setattr(rg, "MAX_COLLECTION_PAGES", cap)
    _wire(monkeypatch, bmc)
    d = rg.account_service_discover(BMC, "recovery", "<rec>", 5, False)
    assert d["enumeration"] == rg.ENUM_INCOMPLETE, d["errors"]
    assert any("계정 목록을 완전히 읽지 못했습니다" in e["message"] for e in d["errors"])
    out = _provision()
    assert bmc.writes == [], f"{case}: 계정 목록을 끝까지 읽지 못했는데 BMC 에 썼다"
    assert out["presence"] == rg.PRESENCE_UNKNOWN and out["method"] == "noop" and out["recovered"] is False
    assert out["account_existed"] is True, "보이는 표준 계정은 존재 정보로 남긴다"
    joined = " ".join(f'{e.get("message")} {e.get("detail")}' for e in out["errors"])
    assert "완전히 확인하지 못해" in joined and "observed standard slots: 2" in joined and "no write attempted" in joined


def test_unknown_without_a_visible_match_does_not_claim_the_account_existed(monkeypatch):
    bmc = Bmc([[1], [3]], {"1": _acct(1, "recovery"), "3": _acct(3, "svc")},
              overrides={"AccountService/Accounts?$skip=1": (503, {}, "HTTP 503: Service Unavailable")})
    _wire(monkeypatch, bmc)
    out = _provision()
    assert out["presence"] == rg.PRESENCE_UNKNOWN and out["account_existed"] is False and bmc.writes == []
    assert "observed standard slots" not in " ".join(str(e.get("detail")) for e in out["errors"])


def test_next_page_404_is_incomplete_not_unsupported(monkeypatch):
    """2페이지 404 하나만 있어도 요약 오류가 함께 남아 '계정 관리 미지원' 으로 잘못 분류되지 않는다."""
    bmc = Bmc([[1], [3]], {"1": _acct(1, "recovery"), "3": _acct(3, "svc")},
              overrides={"AccountService/Accounts?$skip=1": (404, {}, "HTTP 404: Not Found")})
    _wire(monkeypatch, bmc)
    out = _provision()
    assert out["method"] == "noop" and out["presence"] == rg.PRESENCE_UNKNOWN and bmc.writes == []


def test_presence_states_for_partial_lists():
    one = {"accounts": [{"username": "standard", "id": "3"}], "enumeration": rg.ENUM_INCOMPLETE}
    state, matches = rg.account_presence(one, "standard")
    assert state == rg.PRESENCE_UNKNOWN and [m["id"] for m in matches] == ["3"]
    assert rg.account_presence({"accounts": [], "enumeration": rg.ENUM_INCOMPLETE}, "standard") == (rg.PRESENCE_UNKNOWN, [])
    two = {"accounts": [{"username": "standard", "id": "3"}, {"username": "standard", "id": "9"}], "enumeration": rg.ENUM_INCOMPLETE}
    assert rg.account_presence(two, "standard")[0] == rg.PRESENCE_AMBIGUOUS
    done = {"accounts": [{"username": "standard", "id": "3"}], "enumeration": rg.ENUM_COMPLETE}
    assert rg.account_presence(done, "standard")[0] == rg.PRESENCE_PRESENT


# ── 재열거는 ServiceRoot 를 따른다 (Manager-scoped AccountService) ─────────────────────────────────────────────────

SCOPED = "/redfish/v1/Managers/iDRAC.Embedded.1/AccountService"


def test_reenumeration_after_a_lost_create_follows_the_manager_scoped_service(monkeypatch):
    """POST 응답 유실 → 다시 열거해 생성 여부를 본다. 종전에는 AccountService 본문을 ServiceRoot 로 넘겨 표준 경로로 떨어졌다."""
    bmc = Bmc([[1]], {"1": _acct(1, "recovery")}, service_uri=SCOPED)
    created = {"done": False}

    def lost_post(bmc_ip, path, body, *args, **kwargs):
        bmc.writes.append(("POST", path, dict(body)))
        bmc.accounts["7"] = _acct(7, "standard")
        coll = bmc.table[rg._p(SCOPED + "/Accounts")][1]
        coll["Members"].append({"@odata.id": f"{SCOPED}/Accounts/7"})
        created["done"] = True
        return 0, {}, "Timeout after 5s"

    _wire(monkeypatch, bmc)
    monkeypatch.setattr(rg, "_post", lost_post)
    out = _provision()
    assert created["done"] and len([w for w in bmc.writes if w[0] == "POST"]) == 1, "응답을 잃은 생성은 다시 보내지 않는다"
    scoped_coll = rg._p(SCOPED + "/Accounts")
    assert bmc.calls.count(scoped_coll) >= 2, "처음 열거와 재열거 모두 Manager-scoped 컬렉션을 읽는다"
    assert "AccountService" not in bmc.calls, "표준 경로로 떨어지지 않는다"
    assert out["slot_uri"] == f"{SCOPED}/Accounts/7"


def test_reenumeration_when_create_response_has_no_location_follows_the_service_root(monkeypatch):
    bmc = Bmc([[1]], {"1": _acct(1, "recovery")}, service_uri=SCOPED)

    def post_without_location(bmc_ip, path, body, *args, **kwargs):
        bmc.writes.append(("POST", path, dict(body)))
        bmc.accounts["8"] = _acct(8, "standard")
        bmc.table[rg._p(SCOPED + "/Accounts")][1]["Members"].append({"@odata.id": f"{SCOPED}/Accounts/8"})
        return 201, {}, None

    _wire(monkeypatch, bmc)
    monkeypatch.setattr(rg, "_post", post_without_location)
    out = _provision()
    assert "AccountService" not in bmc.calls
    assert out["slot_uri"] == f"{SCOPED}/Accounts/8" and out["recovered"] is True


# ── 공용 순회: 다른 소비자의 동작은 종전과 같다 ────────────────────────────────────────────────────────────────────

def _reference_collection_members(bmc_ip, path, coll, username, password, timeout, verify_ssl, section, errors):
    """2026-10-10 이전 _collection_members 본문 그대로(비교 기준)."""
    members = list(rg._dicts(rg._safe(coll, 'Members')))
    first_path = rg._str(path).split('?', 1)[0]
    seen = {rg._str(path)}
    cur, cur_path, pages, truncated = coll, rg._str(path), 1, False

    def _report(msg):
        if errors is not None:
            errors.append(rg._err(section, msg, code=rg._CODE_NON_BLOCKING_SUBRESOURCE))
        else:
            rg._notice(section, msg)

    while True:
        link = rg._safe(cur, 'Members@odata.nextLink')
        if not link:
            break
        nxt = rg._nextlink_path(bmc_ip, cur_path, link)
        if nxt is None:
            _report('%s: nextLink 를 따라갈 수 없음 (다른 origin 또는 형식 오류) — 앞 페이지까지 보존' % first_path)
            truncated = True
            break
        if nxt in seen:
            _report('%s: nextLink 순환 감지 — 앞 페이지까지 보존' % first_path)
            truncated = True
            break
        if pages >= rg.MAX_COLLECTION_PAGES or len(members) >= rg.MAX_COLLECTION_MEMBERS:
            _report('%s: 페이지 %d / 멤버 %d 상한 도달 — 절단' % (first_path, pages, len(members)))
            truncated = True
            break
        st, nxt_coll, err = rg._get(bmc_ip, nxt, username, password, timeout, verify_ssl)
        if err or st != 200 or not isinstance(nxt_coll, dict):
            _report('%s: 다음 페이지 실패 (%s): %s — 앞 페이지까지 보존' % (first_path, nxt, err or st))
            truncated = True
            break
        seen.add(nxt)
        pages += 1
        cur, cur_path = nxt_coll, nxt
        members.extend(rg._dicts(rg._safe(nxt_coll, 'Members')))
    declared = rg._safe(coll, 'Members@odata.count')
    if (not truncated and isinstance(declared, int) and not isinstance(declared, bool)
            and declared != len(members)):
        rg._notice(section, '%s: Members@odata.count %d != 수집 %d' % (first_path, declared, len(members)))
    return rg._capped(members, section, errors)


M = "/redfish/v1/Systems/1/Memory"
_WRAPPER_CASES = {
    "plain": ({"Members": [{"@odata.id": f"{M}/1"}], "Members@odata.count": 1}, {}),
    "not_list": ({"Members": {"@odata.id": "x"}}, {}),
    "absent": ({"Members@odata.count": 2}, {}),
    "non_object": ({"Members": [{"@odata.id": f"{M}/1"}, "oops", 3]}, {}),
    "duplicate_refs": ({"Members": [{"@odata.id": f"{M}/1"}], "Members@odata.nextLink": f"{M}?$skip=1"},
                       {"Systems/1/Memory?$skip=1": (200, {"Members": [{"@odata.id": f"{M}/1"}]}, None)}),
    "count_mismatch": ({"Members": [{"@odata.id": f"{M}/1"}], "Members@odata.count": 4, "Members@odata.nextLink": f"{M}?$skip=1"},
                       {"Systems/1/Memory?$skip=1": (200, {"Members": [{"@odata.id": f"{M}/2"}]}, None)}),
    "page_failure": ({"Members": [{"@odata.id": f"{M}/1"}], "Members@odata.nextLink": f"{M}?$skip=1"},
                     {"Systems/1/Memory?$skip=1": (503, {}, "HTTP 503: Service Unavailable")}),
    "cycle": ({"Members": [{"@odata.id": f"{M}/1"}], "Members@odata.nextLink": M}, {}),
    "other_origin": ({"Members": [{"@odata.id": f"{M}/1"}], "Members@odata.nextLink": "https://198.51.100.9/redfish/v1/Systems/1/Memory?$skip=1"}, {}),
    "cap_boundary": ({"Members": [{"@odata.id": f"{M}/1"}], "Members@odata.nextLink": f"{M}?$skip=1"},
                     {"Systems/1/Memory?$skip=1": (200, {"Members": [{"@odata.id": f"{M}/2"}], "Members@odata.nextLink": f"{M}?$skip=2"}, None),
                      "Systems/1/Memory?$skip=2": (200, {"Members": [{"@odata.id": f"{M}/3"}]}, None)}),
}


@pytest.mark.parametrize("errors_mode", ["list", "none"])
@pytest.mark.parametrize("case", sorted(_WRAPPER_CASES))
def test_shared_walk_keeps_the_wrapper_contract_for_other_collections(monkeypatch, case, errors_mode):
    coll, table = _WRAPPER_CASES[case]
    if case == "cap_boundary":
        monkeypatch.setattr(rg, "MAX_COLLECTION_PAGES", 2)

    def run(fn):
        calls = []
        notes = []

        def get(bmc_ip, path, *a, **k):
            calls.append(path)
            return table.get(path, (404, {}, "HTTP 404: Not Found"))

        monkeypatch.setattr(rg, "_get", get)
        monkeypatch.setattr(rg, "_notice", lambda section, msg: notes.append((section, str(msg))))
        errors = [] if errors_mode == "list" else None
        members = fn(BMC, "Systems/1/Memory", coll, "u", "p", 5, False, "memory", errors)
        return members, calls, errors, notes

    assert run(rg._collection_members) == run(_reference_collection_members)
