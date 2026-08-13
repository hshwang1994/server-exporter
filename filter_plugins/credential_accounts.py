# -*- coding: utf-8 -*-
# ==============================================================================
# credential_accounts.py — vault 내용 → 인증 후보 list 필터
# ==============================================================================
# `module_utils/credential_common.normalize_accounts` 를 Jinja2 에 노출한다.
#
# 왜 Jinja2 인라인으로 쓰지 않는가:
#   같은 정규화를 3채널(OS / ESXi / Redfish)이 쓴다. 인라인으로 복제하면 구현이
#   채널 수만큼 늘고, **후보 순서 보존** 같은 계약을 각각 따로 지켜야 한다.
#   여기서는 구현 1개 + 단위테스트 1벌로 끝낸다.
#
# 순서 계약 (절대 위반 금지):
#   vault `accounts` 배열 순서 = 인증 시도 순서. 이 필터는 재정렬하지 않는다.
#   role 기반 정렬은 별도 후속 과제이며, 선행 조건은 암호화 vault 의 실제 배열 순서
#   실측이다 (정렬을 먼저 넣으면 인증 순서가 바뀌고 Redfish reconcile 진입 조건까지
#   흔들릴 수 있다).
#
# 사용법 (Ansible task):
#   - set_fact:
#       _cred_accounts: "{{ _cred_vault_data | credential_accounts }}"
#     no_log: true      ← 결과에 password 가 들어 있다. 반드시 붙인다.
# ==============================================================================

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import sys


def _import_credential_common():
    """module_utils/credential_common 의 함수들을 가져온다.

    탐색 순서: 이 파일 기준 상대 경로 → REPO_ROOT 환경변수.
    실패 시 조용히 대체 구현으로 폴백하지 않는다 (정규화가 갈리는 것을 막는 게 목적).
    """
    candidates = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.normpath(os.path.join(here, "..", "module_utils")))
    except NameError:  # pragma: no cover — __file__ 부재 환경
        pass
    repo_root = os.environ.get("REPO_ROOT", "")
    if repo_root:
        candidates.append(os.path.join(repo_root, "module_utils"))

    for path in candidates:
        if path and os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

    import credential_common  # noqa: WPS433

    return credential_common


def credential_accounts(vault_data):
    """vault dict → 인증 후보 list (순서 보존).

    Args:
        vault_data: include_vars 로 로드한 vault 내용 (dict). 비어 있거나
                    dict 가 아니면 빈 list.

    Returns:
        list[dict] — username / password / label / role. **입력 순서 그대로.**
    """
    return _import_credential_common().normalize_accounts(vault_data)


def credential_standard_accounts(vault_data):
    """표준 vault dict → 표준 수집 후보 (role=primary 만, 순서 보존)."""
    return _import_credential_common().standard_accounts_of(vault_data)


def credential_recovery_accounts(vault_data):
    """Recovery vault dict → 복구 후보 (role=primary 제외, 순서 보존)."""
    return _import_credential_common().recovery_accounts_of(vault_data)


def credential_redfish_candidates(standard_accounts, recovery_accounts):
    """Redfish 인증 후보 = 표준 먼저 + recovery (각 배열 내부 순서 보존)."""
    return _import_credential_common().redfish_candidates(
        standard_accounts, recovery_accounts
    )


class FilterModule(object):
    """Ansible filter plugin — credential accounts 정규화"""

    def filters(self):
        return {
            "credential_accounts": credential_accounts,
            "credential_standard_accounts": credential_standard_accounts,
            "credential_recovery_accounts": credential_recovery_accounts,
            "credential_redfish_candidates": credential_redfish_candidates,
        }
