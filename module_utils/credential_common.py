# -*- coding: utf-8 -*-

__metaclass__ = type

import re

TARGET_TYPES = ("os", "esxi", "redfish")

OS_TYPES = ("linux", "windows")

VAULT_ROOT = "vault"

REDFISH_STANDARD_SCOPE = "common/redfish/standard"
REDFISH_STANDARD_RELPATH = "{0}/{1}.yml".format(VAULT_ROOT, REDFISH_STANDARD_SCOPE)

ROLE_PRIMARY = "primary"

_PATH_SAFE = re.compile(r"\A[a-z0-9_-]+\Z")

REASON_RESOLVED = "resolved"
REASON_UNKNOWN_LOCATION = "unknown_location"
REASON_UNKNOWN_TARGET_TYPE = "unknown_target_type"
REASON_UNKNOWN_OS_TYPE = "unknown_os_type"
REASON_VENDOR_UNRESOLVED = "vendor_unresolved"

REASONS = (
    REASON_RESOLVED,
    REASON_UNKNOWN_LOCATION,
    REASON_UNKNOWN_TARGET_TYPE,
    REASON_UNKNOWN_OS_TYPE,
    REASON_VENDOR_UNRESOLVED,
)


def _clean(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.strip().lower()


def _fail(reason, basis):
    return {
        "credential_scope": None,
        "vault_relpath": None,
        "selection_basis": basis,
        "reason": reason,
    }


def resolve_credential_scope(
    location,
    target_type,
    known_locations,
    known_vendors=(),
    os_type=None,
    vendor=None,
):
    loc = _clean(location)
    ttype = _clean(target_type)
    ostype = _clean(os_type)
    vdr = _clean(vendor)

    basis = {"location": loc, "target_type": ttype}

    known_loc = _as_set(known_locations)
    if not loc or loc not in known_loc or not _PATH_SAFE.match(loc):
        return _fail(REASON_UNKNOWN_LOCATION, basis)

    if ttype not in TARGET_TYPES:
        return _fail(REASON_UNKNOWN_TARGET_TYPE, basis)

    if ttype == "os":
        basis["os_type"] = ostype
        if ostype not in OS_TYPES:
            return _fail(REASON_UNKNOWN_OS_TYPE, basis)
        parts = (loc, "os", ostype)

    elif ttype == "esxi":
        parts = (loc, "esxi")

    else:
        basis["vendor"] = vdr
        known_vdr = _as_set(known_vendors)
        if not vdr or vdr not in known_vdr or not _PATH_SAFE.match(vdr):
            return _fail(REASON_VENDOR_UNRESOLVED, basis)
        parts = (loc, "redfish", vdr)

    return {
        "credential_scope": "/".join(parts),
        "vault_relpath": "{0}/{1}.yml".format(VAULT_ROOT, "/".join(parts)),
        "selection_basis": basis,
        "reason": REASON_RESOLVED,
    }


def resolve_redfish_credentials(
    location,
    known_locations,
    known_vendors=(),
    vendor=None,
):
    recovery = resolve_credential_scope(
        location=location,
        target_type="redfish",
        known_locations=known_locations,
        known_vendors=known_vendors,
        vendor=vendor,
    )
    return {
        "standard_credential_scope": REDFISH_STANDARD_SCOPE,
        "standard_vault_relpath": REDFISH_STANDARD_RELPATH,
        "recovery_credential_scope": recovery["credential_scope"],
        "recovery_vault_relpath": recovery["vault_relpath"],
        "selection_basis": recovery["selection_basis"],
        "reason": recovery["reason"],
    }


def standard_accounts_of(vault_data):
    return [
        a for a in normalize_accounts(vault_data)
        if (a.get("role") or ROLE_PRIMARY) == ROLE_PRIMARY
    ]


def recovery_accounts_of(vault_data):
    return [
        a for a in normalize_accounts(vault_data)
        if (a.get("role") or ROLE_PRIMARY) != ROLE_PRIMARY
    ]


def redfish_candidates(standard_accounts, recovery_accounts):
    return list(standard_accounts or []) + list(recovery_accounts or [])


def _as_set(values):
    if not values:
        return set()
    if isinstance(values, dict):
        values = values.keys()
    return {_clean(v) for v in values if v is not None}


def normalize_accounts(vault_data, legacy_label="legacy_single"):
    if not isinstance(vault_data, dict):
        return []

    accounts = vault_data.get("accounts")
    if isinstance(accounts, list) and accounts:
        return list(accounts)

    legacy_user = vault_data.get("ansible_user") or ""
    if legacy_user:
        return [{
            "username": legacy_user,
            "password": vault_data.get("ansible_password") or "",
            "label": legacy_label,
            "role": "primary",
        }]

    return []
