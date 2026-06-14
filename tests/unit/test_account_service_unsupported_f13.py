"""Regression for F13/F08 — account_service_provision Cisco CIMC + 404 fallback (cycle 2026-05-01).

배경: Cisco CIMC AccountService 표준 미지원 (UCS 자체 인증). cycle 2026-04-28
P2 자동 복구 로직이 cisco vendor 시 GET 자체 실패 → noise. cycle 2026-05-01
부터 vendor='cisco' 분기에서 method='not_supported' 명시 + errors[] 한 줄.

또한 Cisco 외 vendor 도 일부 펌웨어가 AccountService 404 → _is_404_only_error
판정으로 'not_supported' graceful 분류 (Additive — 기존 cisco 분기와 별개).

본 테스트:
  - vendor='cisco' → method='not_supported', recovered=False
  - vendor='hpe' + AccountService 404 → method='not_supported'
  - vendor='hpe' + AccountService 정상 → 기존 흐름 유지 (post_new / patch_existing)
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


def test_provision_cisco_post_with_id_field_succeeds(monkeypatch):
    """F50 (cycle 2026-05-06): vendor='cisco' POST 표준 지원 확인 (사이트 실측 10.100.15.2).

    Cisco 변형:
      - POST /Accounts 가 'Id' 필드 (1-15) 필수
      - RoleId 표준 'Administrator' 거부 → 'admin'/'user'/'readonly' enum
      - 빈 Id 자동 검색 (slot 1=admin reserved, 2..15 후보)
    """
    accounts = [
        {'slot_uri': '/redfish/v1/AccountService/Accounts/1',
         'id': '1', 'username': 'admin', 'role_id': 'admin', 'enabled': True},
    ]

    def fake_acct_get(bmc_ip, u, p, t, v):
        return {}, accounts, []

    monkeypatch.setattr(rg, 'account_service_get', fake_acct_get)

    posted_bodies = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        posted_bodies.append(dict(body))
        return 201, {'@odata.id': f'/redfish/v1/AccountService/Accounts/{body.get("Id")}'}, None

    monkeypatch.setattr(rg, '_post', fake_post)

    out = rg.account_service_provision(
        bmc_ip='10.100.15.2', vendor='cisco',
        current_username='admin', current_password='Goodmit1!',
        target_username='infraops', target_password='Passw0rd1!Infra',
        target_role='Administrator',
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out['recovered'] is True
    assert out['method'] == 'post_new'
    # 1번 호출됐고 Id=2 + RoleId='admin' (Cisco enum mapping)
    assert len(posted_bodies) == 1
    assert posted_bodies[0]['Id'] == '2'
    assert posted_bodies[0]['RoleId'] == 'admin'
    assert posted_bodies[0]['UserName'] == 'infraops'


def test_provision_cisco_dryrun_no_post_call(monkeypatch):
    """vendor='cisco' + dryrun=True → POST 호출 안 함."""
    monkeypatch.setattr(rg, 'account_service_get', lambda *a, **k: ({}, [
        {'slot_uri': '/redfish/v1/AccountService/Accounts/1', 'id': '1',
         'username': 'admin', 'role_id': 'admin', 'enabled': True}
    ], []))
    posted = []
    monkeypatch.setattr(rg, '_post', lambda *a, **k: (posted.append(a), (201, {}, None))[1])

    out = rg.account_service_provision(
        bmc_ip='10.100.15.2', vendor='cisco',
        current_username='admin', current_password='Goodmit1!',
        target_username='infraops', target_password='Passw0rd1!Infra',
        target_role='Administrator',
        timeout=30, verify_ssl=False, dryrun=True,
    )
    assert out['method'] == 'post_new'
    assert out['recovered'] is False
    assert len(posted) == 0


def test_provision_cisco_no_empty_id_returns_error(monkeypatch):
    """vendor='cisco' + slot 2..15 모두 사용중 → '빈 Id 없음' 에러."""
    accounts = [
        {'slot_uri': f'/redfish/v1/AccountService/Accounts/{i}',
         'id': str(i), 'username': f'user{i}', 'role_id': 'admin', 'enabled': True}
        for i in range(1, 16)
    ]
    monkeypatch.setattr(rg, 'account_service_get', lambda *a, **k: ({}, accounts, []))

    out = rg.account_service_provision(
        bmc_ip='10.100.15.2', vendor='cisco',
        current_username='admin', current_password='Goodmit1!',
        target_username='infraops', target_password='Passw0rd1!Infra',
        target_role='Administrator',
        timeout=30, verify_ssl=False, dryrun=False,
    )
    assert out['recovered'] is False
    msgs = ' '.join(e.get('message', '') for e in out['errors'])
    assert '빈 Account Id' in msgs


def test_provision_hpe_404_returns_not_supported(monkeypatch):
    """vendor='hpe' + AccountService 404 → 'not_supported' (Cisco 외 일반 404 graceful)."""
    def fake_acct_get(bmc_ip, u, p, t, v):
        # 404 only 에러 emit
        return None, [], [
            {'section': 'account_service',
             'message': 'GET AccountService 실패',
             'detail': 'HTTP 404: Not Found'}
        ]

    monkeypatch.setattr(rg, 'account_service_get', fake_acct_get)

    out = rg.account_service_provision(
        bmc_ip='10.0.0.1', vendor='hpe',
        current_username='admin', current_password='pw',
        target_username='infraops', target_password='Top!Secret',
        target_role='Administrator',
        timeout=30, verify_ssl=False, dryrun=True,
    )
    assert out['method'] == 'not_supported'
    assert out['recovered'] is False
    msgs = [e.get('message') for e in out['errors']]
    assert any('AccountService 미지원' in m for m in msgs)


def test_provision_hpe_500_does_not_route_to_unsupported(monkeypatch):
    """vendor='hpe' + AccountService 500 → 'not_supported' 아님 (진짜 fail). errors[] 채워짐."""
    def fake_acct_get(bmc_ip, u, p, t, v):
        return None, [], [
            {'section': 'account_service',
             'message': 'GET AccountService 실패',
             'detail': 'HTTP 500: Internal Server Error'}
        ]

    monkeypatch.setattr(rg, 'account_service_get', fake_acct_get)

    out = rg.account_service_provision(
        bmc_ip='10.0.0.1', vendor='hpe',
        current_username='admin', current_password='pw',
        target_username='infraops', target_password='Top!Secret',
        target_role='Administrator',
        timeout=30, verify_ssl=False, dryrun=True,
    )
    # 500 은 not_supported 아님 — 기존 흐름 (post_new dryrun 진입)
    assert out['method'] != 'not_supported'
    # errors[] 에 500 detail 보존
    details = [e.get('detail') for e in out['errors']]
    assert any('HTTP 500' in (d or '') for d in details)


def test_provision_dell_normal_flow_unaffected(monkeypatch):
    """vendor='dell' + 정상 응답 + 빈 슬롯 있음 → patch_empty_slot dryrun 진입."""
    def fake_acct_get(bmc_ip, u, p, t, v):
        accounts = [
            {'slot_uri': '/redfish/v1/AccountService/Accounts/1',
             'id': '1', 'username': 'root', 'role_id': 'Administrator', 'enabled': True},
            {'slot_uri': '/redfish/v1/AccountService/Accounts/2',
             'id': '2', 'username': '', 'role_id': 'None', 'enabled': False},
        ]
        return {}, accounts, []

    monkeypatch.setattr(rg, 'account_service_get', fake_acct_get)

    out = rg.account_service_provision(
        bmc_ip='10.0.0.1', vendor='dell',
        current_username='root', current_password='pw',
        target_username='infraops', target_password='Top!Secret',
        target_role='Administrator',
        timeout=30, verify_ssl=False, dryrun=True,
    )
    assert out['method'] == 'patch_empty_slot'
    assert out['slot_uri'] == '/redfish/v1/AccountService/Accounts/2'
    assert out['dryrun'] is True
    assert out['recovered'] is False  # dryrun 이라 PATCH 미실행
