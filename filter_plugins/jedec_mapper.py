#!/usr/bin/env python3
from __future__ import annotations

import re

JEDEC_MAP = {
    (0, 0x01): "AMD",
    (0, 0x04): "Fujitsu",
    (0, 0x07): "Hitachi",
    (0, 0x09): "Intel",
    (0, 0x1F): "Atmel",
    (0, 0x2C): "Micron Technology",
    (0, 0x2D): "SK hynix",
    (0, 0x33): "IDT",
    (0, 0x4E): "Samsung",
    (1, 0x18): "Kingston",
    (1, 0x3A): "PNY Technologies",
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


def jedec_lookup(hex_text, id_first=False):
    s = hex_text.strip()
    if len(s) < 2 or len(s) % 2 or not HEX_PATTERN.match(s):
        return None
    bs = [int(s[i:i + 2], 16) for i in range(0, len(s), 2)]
    bank = None
    if bs[0] == 0x7F:
        n = 0
        while n < len(bs) and bs[n] == 0x7F:
            n += 1
        if n >= len(bs):
            return None
        bank, ident = n, bs[n]
    elif len(bs) >= 2:
        if id_first:
            ident, bank = bs[0], bs[1] & 0x7F
        else:
            bank, ident = bs[0] & 0x7F, bs[1]
    else:
        ident = bs[0]
    id7 = ident & 0x7F
    banks = (bank,) if bank is not None else (0, 1)
    for b in banks:
        name = JEDEC_MAP.get((b, id7))
        if name:
            return name, b, id7
    return None


def jedec_to_vendor(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("unknown", "not specified", "none"):
        return None

    m = PREFIX_HEX_PATTERN.match(s)
    if m:
        hit = jedec_lookup(m.group(1).upper(), id_first=True)
        return hit[0] if hit else s

    if any(c.isalpha() and c not in "ABCDEFabcdef" for c in s) or " " in s:
        return _canonicalize_vendor_name(s)

    if HEX_PATTERN.match(s):
        hit = jedec_lookup(s.upper())
        return hit[0] if hit else s

    return _canonicalize_vendor_name(s)


class FilterModule:

    def filters(self):
        return {
            "jedec_to_vendor": jedec_to_vendor,
        }
