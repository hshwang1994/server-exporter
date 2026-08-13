"""Regression for F49 — multi-vendor account_provision 호환성 강화 (cycle 2026-05-01).

배경:
  사용자 보고 — 'redfish 공통계정 생성이 안 된다'.
  실측 (10.100.15.27 Dell, 10.100.15.31 Dell, 10.50.11.231 HPE, 10.50.11.232 Lenovo,
        10.100.15.2 Cisco) 결과:
    - HPE/Lenovo: 이미 'infraops' primary 존재 → recovery 진입 안 됨 (정상)
    - Cisco: AccountService 표준 미지원 (not_supported — F13 이미 처리)
    - Dell: vault에 root username 4개 (서로 다른 password). try_one_account.yml 가
            label 까지 promote 안 함 → account_service.yml 의 vault re-lookup 이
            username 만으로 검색 → 첫 root entry (잘못된 password) 잡음 → 401.

본 테스트:
  1. account_service_provision body retry — POST 1차 400 시 PasswordChangeRequired:false
     추가 후 retry (Lenovo XCC password policy)
  2. account_service_provision body retry — HPE 1차+2차 400/405 시 Oem.Hpe.Privileges
     추가 후 3차 retry
  3. supermicro 일반 vendor: 1차 성공 시 retry 없이 바로 종료
"""
from __future__ import annotations

import sys

import pytest
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

# ansible stub
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



def _fake_acct_get_empty(bmc_ip, u, p, t, v):
    """기존 사용자 없음 (post_new 분기로 라우팅)."""
    return {}, [], []


def test_provision_lenovo_sends_password_change_required_on_first_post(monkeypatch):
    """Lenovo 는 **처음부터** PasswordChangeRequired:false 를 실어 보낸다.

    2026-08-12 변경: 종전에는 표준 body 로 POST 하고 400/405 를 받으면 그때
    PasswordChangeRequired 를 붙여 다시 POST 했다(= 실패 후 다른 payload 로 재시도).
    Lenovo 공식 문서는 이 속성을 create payload 로 정의하고 TSM 은 미지정 시
    default true 라 생성 직후 접근이 막힌다. 그래서 Family 가 확정되면 한 번에 보낸다.
    source: pubs.lenovo.com/xcc-restapi/create_an_account_post,
            pubs.lenovo.com/tsm/post_create_new_account
    """
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/3"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip="10.50.11.232", vendor="lenovo",
        current_username="USERID", current_password="<recovery-pass>",
        target_username="infraops", target_password="<target-pass>",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out["recovered"] is True
    assert out["method"] == "post_new"
    assert out["family"] == "lenovo_collection_post"
    assert len(call_log) == 1, "쓰기를 두 번 보내면 안 된다 (Write fallback 금지)"
    assert call_log[0].get("PasswordChangeRequired") is False


def test_provision_hpe_ilo5plus_posts_roleid_only_once(monkeypatch):
    """iLO5+ 는 RoleId 만으로 충분하다 — 실패해도 다른 payload 로 다시 쓰지 않는다.

    2026-08-12 변경: 종전 3단 retry 사다리(표준 → PasswordChangeRequired → Oem.Hpe)를
    제거했다. 9 Vendor 공식 조사가 공통으로 금지한 '무작위 Write fallback' 이다.
    source: servermanagementportal.ext.hpe.com/docs/redfishservices/ilos/supplementdocuments/managingusers
    """
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        return 400, {}, "HTTP 400: Bad Request"

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip="10.50.11.231", vendor="hpe",
        current_username="admin", current_password="<recovery-pass>",
        target_username="infraops", target_password="<target-pass>",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out["recovered"] is False
    assert out["family"] == "hpe_ilo5plus"
    assert len(call_log) == 1, "실패 후 다른 payload 로 다시 쓰면 안 된다"
    assert "Oem" not in call_log[0]


def test_provision_hpe_ilo4_uses_hp_namespace_not_hpe(monkeypatch):
    """iLO4 의 공식 OEM namespace 는 `Hpe` 가 아니라 `Hp` 다.

    종전 코드는 3차 retry 에서 `Oem.Hpe.Privileges` 만 보냈다 — iLO4 에는 맞지 않는다.
    source: hewlettpackard.github.io/ilo-rest-api-docs/ilo4/ (Oem/Hp/Privileges)
    """
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/5"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip="10.50.11.231", vendor="hpe",
        current_username="admin", current_password="<recovery-pass>",
        target_username="infraops", target_password="<target-pass>",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
        adapter_id="redfish_hpe_ilo4",
    )
    assert out["family"] == "hpe_ilo4"
    assert len(call_log) == 1
    assert "Hp" in call_log[0]["Oem"], "iLO4 에 Hpe namespace 를 보내면 안 된다"
    assert "Hpe" not in call_log[0]["Oem"]
    assert "Privileges" in call_log[0]["Oem"]["Hp"]


def test_provision_supermicro_first_attempt_success_no_retry(monkeypatch):
    """vendor='supermicro' + 1차 성공 → retry 없이 바로 종료."""
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

    call_count = {"n": 0}

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_count["n"] += 1
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/2"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip="10.0.0.5", vendor="supermicro",
        current_username="ADMIN", current_password="ADMIN",
        target_username="infraops", target_password="<target-pass>",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out["recovered"] is True
    assert out["method"] == "post_new"
    assert call_count["n"] == 1


def test_provision_lenovo_500_no_retry(monkeypatch):
    """vendor='lenovo' + 1차 POST 500 → 400/405 가 아니므로 retry 없음. recovered=False."""
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        return 500, {}, "HTTP 500: Internal Server Error"

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip="10.50.11.232", vendor="lenovo",
        current_username="USERID", current_password="<recovery-pass>",
        target_username="infraops", target_password="<target-pass>",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out["recovered"] is False
    # 1번만 호출 (500 은 retry 트리거 아님)
    assert len(call_log) == 1
    # 사용자 문장에는 URI/HTTP 를 넣지 않는다 — 기술 증거는 detail 에 둔다 (rule 10).
    joined = " ".join(f'{e.get("message", "")} {e.get("detail", "")}' for e in out["errors"])
    assert "AccountService/Accounts" in joined
    assert "HTTP 500" in joined


def test_provision_dell_skip_reserved_slot1_and_retry(monkeypatch):
    """vendor='dell' + slot 1 (anonymous reserved) skip + slot 3 PATCH 200 + verify 200.

    사이트 실측 (10.100.15.27): slot 1 = UserName='', Enabled=false, PATCH HTTP 400 AccessDenied.
    """
    accounts = [
        {'slot_uri': '/redfish/v1/AccountService/Accounts/1',
         'id': '1', 'username': '', 'role_id': 'None', 'enabled': False},
        {'slot_uri': '/redfish/v1/AccountService/Accounts/2',
         'id': '2', 'username': 'root', 'role_id': 'Administrator', 'enabled': True},
        {'slot_uri': '/redfish/v1/AccountService/Accounts/3',
         'id': '3', 'username': '', 'role_id': 'None', 'enabled': False},
        {'slot_uri': '/redfish/v1/AccountService/Accounts/4',
         'id': '4', 'username': '', 'role_id': 'None', 'enabled': False},
    ]

    def fake_acct_get(bmc_ip, u, p, t, v):
        return {}, accounts, []

    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(fake_acct_get))

    patched_slots = []

    def fake_patch(bmc_ip, path, body, u, p, t, v):
        patched_slots.append(path)
        if "/Accounts/3" in path:
            return 200, {}, None
        return 400, {}, "HTTP 400: AccessDenied"

    monkeypatch.setattr(rg, "_patch", fake_patch)

    # F49 추가: verify _get mock — 새 자격증명으로 실 인증 시도, 200 반환
    monkeypatch.setattr(rg, "_get", lambda *a, **kw: (200, {}, None))

    out = rg.account_service_provision(
        bmc_ip="10.100.15.27", vendor="dell",
        current_username="root", current_password="<recovery-pass>",
        target_username="infraops", target_password="<target-pass>",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    # slot 1 은 skip 됐으므로 PATCH 호출 안 일어남
    assert "/Accounts/1" not in " ".join(patched_slots)
    # slot 3 에서 성공
    assert out["recovered"] is True
    assert out["method"] == "patch_empty_slot"
    assert out["slot_uri"] == "/redfish/v1/AccountService/Accounts/3"


def test_provision_lenovo_patch_silent_fail_delete_repost_fallback(monkeypatch):
    """F50 phase 4 (cycle 2026-05-06): Lenovo PATCH 200 + verify 401 (권한 cache 손상)
    → DELETE + POST 재생성 fallback. 사이트 실측 (10.50.11.232 XCC SR650).

    2026-08-11 (Phase 6-B §11) 기대값 변경: 이 fallback 은 기존 계정을 **지우므로**
    기본값이 off 로 바뀌었다. 사이트 실측이 증명한 동작 자체는 그대로이므로,
    운영자가 명시적으로 켜는 경우(allow_delete_recreate=True)를 그대로 고정한다.
    기본값(off) 경로는 바로 아래 test_...default_does_not_delete 가 따로 고정한다.
    """
    accounts = [
        {'slot_uri': '/redfish/v1/AccountService/Accounts/4',
         'id': '4', 'username': 'infraops', 'role_id': 'Administrator', 'enabled': True},
    ]

    def fake_acct_get(bmc_ip, u, p, t, v):
        return {}, accounts, []

    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(fake_acct_get))
    monkeypatch.setattr(rg, "_patch", lambda *a, **kw: (200, {}, None))
    deleted = []
    posted = []

    # 권한 cache 손상 시뮬: 재생성 전에는 401, DELETE+POST 로 다시 만든 뒤에는 200.
    # 2026-08-12: 재생성 경로도 반드시 재인증까지 확인한다 (audit H-1) — 그래서
    #   "지우고 다시 만들면 된다" 를 표현하려면 재생성 후 인증이 되어야 한다.
    monkeypatch.setattr(rg, "_get",
                        lambda *a, **kw: (200, {}, None) if posted else (401, {}, "HTTP 401"))

    def fake_delete(bmc_ip, path, u, p, t, v):
        deleted.append(path)
        return 204, {}, None

    def fake_post(bmc_ip, path, body, u, p, t, v):
        posted.append(dict(body))
        return 201, {'@odata.id': '/redfish/v1/AccountService/Accounts/4'}, None

    monkeypatch.setattr(rg, "_delete", fake_delete)
    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip='10.50.11.232', vendor='lenovo',
        current_username='USERID', current_password='<recovery-pass>',
        target_username='infraops', target_password='<target-pass>',
        target_role='Administrator',
        timeout=30, verify_ssl=False, dryrun=False,
        allow_delete_recreate=True,
    )
    # PATCH 1회 + verify _get + DELETE + POST 재생성 → recovered=True, method='delete_repost'
    assert len(deleted) == 1
    assert len(posted) == 1
    assert posted[0]['UserName'] == 'infraops'
    assert out['recovered'] is True
    assert out['method'] == 'delete_repost'
    msgs = ' '.join(e.get('message', '') for e in out['errors'])
    assert '권한 cache 손상' in msgs


def test_provision_lenovo_patch_verify_fail_default_does_not_delete(monkeypatch):
    """Phase 6-B §11: 기본값(allow_delete_recreate 미지정)에서는 기존 계정을 지우지 않는다.

    비밀번호 동기화 뒤 인증 확인이 안 되는 신호는 (a) 권한 cache 손상 과
    (b) BMC 비밀번호 정책으로 적용이 안 된 silent fail 을 구분하지 못한다.
    (b) 에서 지우면 정상 운영 중이던 계정을 잃고, DELETE 성공 후 POST 실패 시
    관리자 계정이 0 개가 된다 (docs/ai/AUDIT-2026-05-29.md A3).
    """
    accounts = [
        {'slot_uri': '/redfish/v1/AccountService/Accounts/4',
         'id': '4', 'username': 'infraops', 'role_id': 'Administrator', 'enabled': True},
    ]
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(lambda *a, **k: ({}, accounts, [])))
    monkeypatch.setattr(rg, "_patch", lambda *a, **kw: (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda *a, **kw: (401, {}, "HTTP 401"))
    deleted, posted = [], []
    monkeypatch.setattr(rg, "_delete", lambda *a, **k: (deleted.append(a), (204, {}, None))[1])
    monkeypatch.setattr(rg, "_post", lambda *a, **k: (posted.append(a), (201, {}, None))[1])

    out = rg.account_service_provision(
        bmc_ip='10.50.11.232', vendor='lenovo',
        current_username='USERID', current_password='<recovery-pass>',
        target_username='infraops', target_password='<target-pass>',
        target_role='Administrator',
        timeout=30, verify_ssl=False, dryrun=False,
    )

    assert deleted == [], "기본값에서 DELETE 를 보내면 안 된다"
    assert posted == [], "DELETE 를 안 했으므로 재생성 POST 도 없어야 한다"
    assert out['recovered'] is False
    assert out['method'] == 'patch_existing'
    assert out['action'] == 'password_sync'
    assert out['verification'] == 'failed'


def test_provision_dell_patch_silent_fail_no_delete_fallback(monkeypatch):
    """F50 phase 4: Dell PATCH-only (POST 미지원) → DELETE+POST fallback 미지원.
    PATCH 200 후 verify 401 시 errors[] 만 emit, recovered=False."""
    accounts = [
        {'slot_uri': '/redfish/v1/AccountService/Accounts/3',
         'id': '3', 'username': 'infraops', 'role_id': 'Administrator', 'enabled': True},
    ]
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(lambda *a, **k: ({}, accounts, [])))
    monkeypatch.setattr(rg, "_patch", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (401, {}, "HTTP 401"))
    deleted_calls = []
    monkeypatch.setattr(rg, "_delete", lambda *a, **k: (deleted_calls.append(a), (204, {}, None))[1])

    out = rg.account_service_provision(
        bmc_ip='10.100.15.27', vendor='dell',
        current_username='root', current_password='<recovery-pass>',
        target_username='infraops', target_password='<target-pass>',
        target_role='Administrator',
        timeout=30, verify_ssl=False, dryrun=False,
        # Phase 6-B §11: fallback 기본값이 off 로 바뀌었다. 이 테스트가 고정하려는 것은
        # "fallback 을 켜도 Dell 은 PATCH-only 라 DELETE 를 안 한다" 이므로 명시적으로 켜둔다.
        allow_delete_recreate=True,
    )
    # Dell 분기: DELETE 호출 안 됨
    assert len(deleted_calls) == 0
    assert out['recovered'] is False
    msgs = ' '.join(e.get('message', '') for e in out['errors'])
    assert 'Dell iDRAC PATCH-only' in msgs


def test_provision_dell_silent_fail_stops_at_one_slot(monkeypatch):
    """PATCH 200 인데 그 자격으로 인증이 안 되면 **거기서 멈춘다** (슬롯 순회 금지).

    2026-08-12 변경 (lockout 예산): 종전에는 빈 슬롯을 최대 3개까지 돌며 같은 비밀번호로
    다시 쓰고 매번 3회씩 검증해, 표준 계정에 실패 인증을 최대 9회 / 약 20초에 발생시켰다.
    Dell IP Blocking 기본값은 60초 창에서 3회다(FailCount=3 / FailWindow=60 / PenaltyTime=60).
    슬롯을 바꿔 다시 쓰는 것은 '다른 방식으로 또 써 본다' 와 같은 종류의 시도이기도 하다.
    source: dell.com/.../idrac10_1.xx_scg/network-security-configuration
    """
    accounts = [
        {'slot_uri': '/redfish/v1/AccountService/Accounts/1',
         'id': '1', 'username': '', 'role_id': 'None', 'enabled': False},
        {'slot_uri': '/redfish/v1/AccountService/Accounts/3',
         'id': '3', 'username': '', 'role_id': 'None', 'enabled': False},
        {'slot_uri': '/redfish/v1/AccountService/Accounts/4',
         'id': '4', 'username': '', 'role_id': 'None', 'enabled': False},
    ]

    def fake_acct_get(bmc_ip, u, p, t, v):
        return {}, accounts, []

    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(fake_acct_get))
    patched = []

    def fake_patch(bmc_ip, path, body, u, p, t, v):
        patched.append((path, dict(body)))
        return 200, {}, None

    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", lambda *a, **kw: (401, {}, "HTTP 401: Unauthorized"))

    out = rg.account_service_provision(
        bmc_ip="10.100.15.27", vendor="dell",
        current_username="root", current_password="<recovery-pass>",
        target_username="infraops", target_password="<target-pass>",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out["recovered"] is False
    assert out["verification"] == "failed"
    # 계정 생성 쓰기는 **한 슬롯에만** 나갔다 (그 뒤 PATCH 는 되돌리기 cleanup 1회).
    create_writes = [p for p, b in patched if b.get("UserName") == "infraops"]
    assert create_writes == ["AccountService/Accounts/3"]   # _p() 가 /redfish/v1 접두사를 뗀다
    cleanup = [b for p, b in patched if b.get("UserName") == ""]
    assert len(cleanup) == 1, "실패한 슬롯을 되돌리지 않았다"
    # 표준 계정에 대한 실패 인증은 ACCOUNT_VERIFY_DELAYS 횟수를 넘지 않는다.
    assert out["auth_budget"].get("infraops") == len(rg.ACCOUNT_VERIFY_DELAYS)
    msgs = " ".join(f'{e.get("message", "")} {e.get("detail", "")}' for e in out["errors"])
    assert "암호 정책" in msgs or "verify HTTP" in msgs


def test_provision_dell_no_empty_slots_after_skip(monkeypatch):
    """vendor='dell' + slot 1 skip 후 다른 모든 slot 사용중 → '빈 슬롯 없음' 에러."""
    accounts = [
        {'slot_uri': '/redfish/v1/AccountService/Accounts/1',
         'id': '1', 'username': '', 'role_id': 'None', 'enabled': False},
        {'slot_uri': '/redfish/v1/AccountService/Accounts/2',
         'id': '2', 'username': 'root', 'role_id': 'Administrator', 'enabled': True},
        {'slot_uri': '/redfish/v1/AccountService/Accounts/3',
         'id': '3', 'username': 'admin2', 'role_id': 'Administrator', 'enabled': True},
    ]

    def fake_acct_get(bmc_ip, u, p, t, v):
        return {}, accounts, []

    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(fake_acct_get))

    out = rg.account_service_provision(
        bmc_ip="10.100.15.27", vendor="dell",
        current_username="root", current_password="<recovery-pass>",
        target_username="infraops", target_password="<target-pass>",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=True,
    )
    assert out["recovered"] is False
    msgs = [e.get("message", "") for e in out["errors"]]
    assert any("빈 계정 슬롯이 없어" in m for m in msgs)


def test_unverified_family_writes_once_and_never_retries(monkeypatch):
    """공식 Write 계약을 확보하지 못한 Family 도 **한 번만 쓴다.**

    2026-08-12 (rev.2) 반전. 종전 이 테스트는 "UNVERIFIED Family 는 400/405 뒤
    `PasswordChangeRequired:false` 를 덧붙여 한 번 더 POST 한다" 를 고정하고 있었다.
    그런데 그 Family 에 속한 Vendor 들(Fujitsu / Quanta / Cisco X-Series / Lenovo IMM2 /
    Supermicro X9 / Inspur M5·M7 / HPE RMC)이 공식 조사에서 **하나같이 바로 그 재시도를
    금지**했다.
        05 §19/§39-D, 06 §17/§31-F, 07 §17/§40-E, 08 §17/§32-C, 09 §19/§45-D

    UNVERIFIED 의 뜻은 "여러 번 시도해 본다" 가 아니다:
        read-only discovery → 완전 열거 → **한 번의 결정적 쓰기** → 재조회 → 재인증
    계약을 모르면 추측하지 말고 한 번 쓰고 결과를 그대로 보고한다.
    """
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        # 종전이라면 2차 요청에서 성공했을 응답. 이제 2차 요청 자체가 없어야 한다.
        if "PasswordChangeRequired" in body:
            return 200, {"@odata.id": "/redfish/v1/AccountService/Accounts/4"}, None
        return 405, {}, "HTTP 405: Method Not Allowed"

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip="10.0.0.9", vendor="fujitsu",
        current_username="admin", current_password="<recovery-pass>",
        target_username="infraops", target_password="<target-pass>",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out["family"] == "generic_collection_post"
    assert out["evidence"] == "unverified"
    assert len(call_log) == 1, "UNVERIFIED Family 가 추측성 2차 Write 를 했다"
    assert "PasswordChangeRequired" not in call_log[0], \
        "계약 근거가 없는 속성을 추측해서 보냈다"
    # 한 번의 쓰기가 거부됐으므로 실패다. 성공으로 둔갑시키지 않는다.
    assert out["recovered"] is False
    assert out["write_accepted"] is False
