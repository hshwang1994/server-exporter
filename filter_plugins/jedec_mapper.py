#!/usr/bin/env python3
from __future__ import annotations

import re

JEDEC_MAP = {
    "01": "AMD",
    "04": "Fujitsu",
    "07": "Hitachi",
    "0B": "Intel",
    "1F": "Atmel",
    "2C": "Micron Technology",
    "AD": "SK hynix",
    "CE": "Samsung",
    "98": "Kingston",
    "B3": "IDT",
    "BA": "PNY Electronics",
    "0x2C": "Micron Technology",
    "0xAD": "SK hynix",
    "0xCE": "Samsung",
    "0x98": "Kingston",
    "0xCE00": "Samsung",
    "0xAD00": "SK hynix",
    "0x2C00": "Micron Technology",
}

HEX_PATTERN = re.compile(r"^[0-9A-Fa-f]{2,}$")
PREFIX_HEX_PATTERN = re.compile(r"^0x([0-9A-Fa-f]{2,})$", re.IGNORECASE)


VENDOR_NAME_NORMALIZATION = {
    "hynix": "SK hynix",
    "hynix semiconductor": "SK hynix",
    "sk hynix": "SK hynix",
    "skhynix": "SK hynix",
    "samsung electronics": "Samsung",
    "samsung electronic": "Samsung",
    "micron": "Micron Technology",
    "micron technology": "Micron Technology",
    "kingston technology": "Kingston",
}


def _canonicalize_vendor_name(name):
    if not name:
        return name
    key = name.strip().lower()
    return VENDOR_NAME_NORMALIZATION.get(key, name)


def jedec_to_vendor(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("unknown", "not specified", "none"):
        return None

    m = PREFIX_HEX_PATTERN.match(s)
    if m:
        hex_part = m.group(1).upper()
        if "0x" + hex_part in JEDEC_MAP:
            return JEDEC_MAP["0x" + hex_part]
        if hex_part[:2] in JEDEC_MAP:
            return JEDEC_MAP[hex_part[:2]]
        return s

    if any(c.isalpha() and c not in "ABCDEFabcdef" for c in s) or " " in s:
        return _canonicalize_vendor_name(s)

    if HEX_PATTERN.match(s):
        id_byte = s[2:4].upper() if len(s) >= 4 else s[:2].upper()
        if id_byte in JEDEC_MAP:
            return JEDEC_MAP[id_byte]
        if s[:2].upper() in JEDEC_MAP:
            return JEDEC_MAP[s[:2].upper()]
        return s

    return _canonicalize_vendor_name(s)


class FilterModule:

    def filters(self):
        return {
            "jedec_to_vendor": jedec_to_vendor,
        }
