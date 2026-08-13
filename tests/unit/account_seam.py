"""계정 테스트 공용 seam — (service, accounts, errors) 3-tuple → discovery dict.

왜 이 파일이 있나 (2026-08-12):
  `account_service_provision()` 은 이제 `account_service_get()` 대신
  `account_service_discover()` 를 쓴다. 3-tuple 은 "계정 목록을 **완전히** 읽었는가" 를
  표현할 수 없어서, 조회 실패와 계정 부재가 구분되지 않았다(audit C-1). 그 구분이
  생성 쓰기를 허용할지 말지를 결정하므로 seam 자체가 그 정보를 실어야 한다.

  기존 테스트들이 쓰던 3-tuple fake 를 그대로 살리기 위해, 여기서 discovery dict 로
  감싼다. 의미 매핑:
      service is None            → enumeration='failed'   (인증/서비스 조회 실패)
      errors 가 비어 있지 않음     → enumeration='incomplete' (부분 조회 실패)
      그 외                       → enumeration='complete'
"""
from __future__ import annotations


def as_discovery(fn, rg, **overrides):
    """3-tuple fake 를 account_service_discover 시그니처로 변환한다."""
    def _discover(bmc_ip, username, password, timeout, verify_ssl, **kwargs):
        service, accounts, errors = fn(bmc_ip, username, password, timeout, verify_ssl)
        accounts = list(accounts or [])
        errors = list(errors or [])
        if service is None:
            enumeration = rg.ENUM_FAILED
        elif errors:
            enumeration = rg.ENUM_INCOMPLETE
        else:
            enumeration = rg.ENUM_COMPLETE
        d = {
            'service_uri':  'AccountService',
            'accounts_uri': 'AccountService/Accounts',
            'roles_uri':    None,
            'service':      service,
            'policy':       rg._account_policy_of(service),
            'role_ids':     [],
            'accounts':     accounts,
            'member_total': len(accounts),
            'member_read':  len(accounts),
            'enumeration':  enumeration,
            'manager':      None,
            'errors':       errors,
        }
        d.update(overrides)
        return d
    return _discover
