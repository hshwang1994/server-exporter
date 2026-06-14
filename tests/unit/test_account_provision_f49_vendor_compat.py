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


def _fake_acct_get_empty(bmc_ip, u, p, t, v):
    """기존 사용자 없음 (post_new 분기로 라우팅)."""
    return {}, [], []


def test_provision_lenovo_400_retry_with_password_change_required(monkeypatch):
    """vendor='lenovo' + 1차 POST 400 → PasswordChangeRequired:false 추가 retry 200."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_empty)

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        if "PasswordChangeRequired" in body:
            return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/3"}, None
        return 400, {"error": "password policy"}, "HTTP 400: Bad Request"

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip="10.50.11.232", vendor="lenovo",
        current_username="USERID", current_password="VMware1!",
        target_username="infraops", target_password="Passw0rd1!",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out["recovered"] is True
    assert out["method"] == "post_new"
    # 2번 호출됐고 두 번째 호출에 PasswordChangeRequired:false 포함
    assert len(call_log) == 2
    assert "PasswordChangeRequired" not in call_log[0]
    assert call_log[1].get("PasswordChangeRequired") is False


def test_provision_hpe_third_retry_with_oem_privileges(monkeypatch):
    """vendor='hpe' + 1차 400 + 2차 (PasswordChangeRequired) 400 → Oem.Hpe.Privileges retry 201."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_empty)

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        if "Oem" in body and "Hpe" in body.get("Oem", {}):
            return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/5"}, None
        return 400, {}, "HTTP 400: Bad Request"

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip="10.50.11.231", vendor="hpe",
        current_username="admin", current_password="VMware1!",
        target_username="infraops", target_password="Passw0rd1!",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out["recovered"] is True
    assert out["method"] == "post_new"
    # 3번 호출 (base + lenovo retry + hpe oem retry)
    assert len(call_log) == 3
    assert "Oem" in call_log[2]
    assert "Hpe" in call_log[2]["Oem"]
    assert "Privileges" in call_log[2]["Oem"]["Hpe"]


def test_provision_supermicro_first_attempt_success_no_retry(monkeypatch):
    """vendor='supermicro' + 1차 성공 → retry 없이 바로 종료."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_empty)

    call_count = {"n": 0}

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_count["n"] += 1
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/2"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip="10.0.0.5", vendor="supermicro",
        current_username="ADMIN", current_password="ADMIN",
        target_username="infraops", target_password="Passw0rd1!",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out["recovered"] is True
    assert out["method"] == "post_new"
    assert call_count["n"] == 1


def test_provision_lenovo_500_no_retry(monkeypatch):
    """vendor='lenovo' + 1차 POST 500 → 400/405 가 아니므로 retry 없음. recovered=False."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_empty)

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        return 500, {}, "HTTP 500: Internal Server Error"

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip="10.50.11.232", vendor="lenovo",
        current_username="USERID", current_password="VMware1!",
        target_username="infraops", target_password="Passw0rd1!",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out["recovered"] is False
    # 1번만 호출 (500 은 retry 트리거 아님)
    assert len(call_log) == 1
    msgs = [e.get("message", "") for e in out["errors"]]
    assert any("POST /AccountService/Accounts" in m for m in msgs)


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

    monkeypatch.setattr(rg, "account_service_get", fake_acct_get)

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
        current_username="root", current_password="Goodmit0802!",
        target_username="infraops", target_password="Passw0rd1!Strong",
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
    """
    accounts = [
        {'slot_uri': '/redfish/v1/AccountService/Accounts/4',
         'id': '4', 'username': 'infraops', 'role_id': 'Administrator', 'enabled': True},
    ]

    def fake_acct_get(bmc_ip, u, p, t, v):
        return {}, accounts, []

    monkeypatch.setattr(rg, "account_service_get", fake_acct_get)
    monkeypatch.setattr(rg, "_patch", lambda *a, **kw: (200, {}, None))
    # verify 401 (권한 cache 손상 시뮬)
    monkeypatch.setattr(rg, "_get", lambda *a, **kw: (401, {}, "HTTP 401"))
    deleted = []
    posted = []

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
        current_username='USERID', current_password='VMware1!',
        target_username='infraops', target_password='Passw0rd1!Infra',
        target_role='Administrator',
        timeout=30, verify_ssl=False, dryrun=False,
    )
    # PATCH 1회 + verify _get + DELETE + POST 재생성 → recovered=True, method='delete_repost'
    assert len(deleted) == 1
    assert len(posted) == 1
    assert posted[0]['UserName'] == 'infraops'
    assert out['recovered'] is True
    assert out['method'] == 'delete_repost'
    msgs = ' '.join(e.get('message', '') for e in out['errors'])
    assert '권한 cache 손상' in msgs


def test_provision_dell_patch_silent_fail_no_delete_fallback(monkeypatch):
    """F50 phase 4: Dell PATCH-only (POST 미지원) → DELETE+POST fallback 미지원.
    PATCH 200 후 verify 401 시 errors[] 만 emit, recovered=False."""
    accounts = [
        {'slot_uri': '/redfish/v1/AccountService/Accounts/3',
         'id': '3', 'username': 'infraops', 'role_id': 'Administrator', 'enabled': True},
    ]
    monkeypatch.setattr(rg, "account_service_get", lambda *a, **k: ({}, accounts, []))
    monkeypatch.setattr(rg, "_patch", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (401, {}, "HTTP 401"))
    deleted_calls = []
    monkeypatch.setattr(rg, "_delete", lambda *a, **k: (deleted_calls.append(a), (204, {}, None))[1])

    out = rg.account_service_provision(
        bmc_ip='10.100.15.27', vendor='dell',
        current_username='root', current_password='Goodmit0802!',
        target_username='infraops', target_password='Passw0rd1!Infra',
        target_role='Administrator',
        timeout=30, verify_ssl=False, dryrun=False,
    )
    # Dell 분기: DELETE 호출 안 됨
    assert len(deleted_calls) == 0
    assert out['recovered'] is False
    msgs = ' '.join(e.get('message', '') for e in out['errors'])
    assert 'Dell iDRAC PATCH-only' in msgs


def test_provision_dell_silent_fail_verify_detects(monkeypatch):
    """vendor='dell' + PATCH 200 OK 이지만 verify 401 (silent fail) → 다음 슬롯 retry."""
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

    monkeypatch.setattr(rg, "account_service_get", fake_acct_get)
    monkeypatch.setattr(rg, "_patch", lambda *a, **kw: (200, {}, None))

    # 1차 verify (slot 3) = 401 silent fail, 2차 verify (slot 4) = 200 ok
    verify_calls = {"n": 0}

    def fake_get(bmc_ip, path, u, p, t, v):
        verify_calls["n"] += 1
        if verify_calls["n"] == 1:
            return 401, {}, "HTTP 401: Unauthorized"
        return 200, {}, None

    monkeypatch.setattr(rg, "_get", fake_get)

    out = rg.account_service_provision(
        bmc_ip="10.100.15.27", vendor="dell",
        current_username="root", current_password="Goodmit0802!",
        target_username="infraops", target_password="Passw0rd1!",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    # slot 4 에서 verify 200 → recovered=True
    assert out["recovered"] is True
    assert out["slot_uri"] == "/redfish/v1/AccountService/Accounts/4"
    # silent fail 메시지 errors[] 에 기록
    msgs = " ".join(e.get("message", "") for e in out["errors"])
    assert "silent" in msgs.lower() or "Security Strengthen Policy" in msgs or "verify HTTP" in msgs


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

    monkeypatch.setattr(rg, "account_service_get", fake_acct_get)

    out = rg.account_service_provision(
        bmc_ip="10.100.15.27", vendor="dell",
        current_username="root", current_password="Goodmit0802!",
        target_username="infraops", target_password="Passw0rd1!",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=True,
    )
    assert out["recovered"] is False
    msgs = [e.get("message", "") for e in out["errors"]]
    assert any("빈 슬롯 없음" in m for m in msgs)


def test_provision_hpe_405_lenovo_retry_succeeds(monkeypatch):
    """vendor='hpe' + 1차 405 → 2차 PasswordChangeRequired retry 201 (HPE OEM 까지 안 감)."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_empty)

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        if "PasswordChangeRequired" in body and "Oem" not in body:
            return 200, {"@odata.id": "/redfish/v1/AccountService/Accounts/4"}, None
        return 405, {}, "HTTP 405: Method Not Allowed"

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        bmc_ip="10.50.11.231", vendor="hpe",
        current_username="admin", current_password="VMware1!",
        target_username="infraops", target_password="Passw0rd1!",
        target_role="Administrator",
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out["recovered"] is True
    # 2번 호출만 (Oem retry 까지 안 감)
    assert len(call_log) == 2
