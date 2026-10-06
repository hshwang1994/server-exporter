
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import sys


def _import_credential_common():
    candidates = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.normpath(os.path.join(here, "..", "module_utils")))
    except NameError:
        pass
    repo_root = os.environ.get("REPO_ROOT", "")
    if repo_root:
        candidates.append(os.path.join(repo_root, "module_utils"))

    for path in candidates:
        if path and os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

    import credential_common

    return credential_common


def credential_accounts(vault_data):
    return _import_credential_common().normalize_accounts(vault_data)


def credential_standard_accounts(vault_data):
    return _import_credential_common().standard_accounts_of(vault_data)


def credential_recovery_accounts(vault_data):
    return _import_credential_common().recovery_accounts_of(vault_data)


def credential_redfish_candidates(standard_accounts, recovery_accounts):
    return _import_credential_common().redfish_candidates(
        standard_accounts, recovery_accounts
    )


class FilterModule(object):

    def filters(self):
        return {
            "credential_accounts": credential_accounts,
            "credential_standard_accounts": credential_standard_accounts,
            "credential_recovery_accounts": credential_recovery_accounts,
            "credential_redfish_candidates": credential_redfish_candidates,
        }
