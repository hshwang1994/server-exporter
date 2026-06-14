#!/usr/bin/env python3
"""JEDEC manufacturer ID mapper for memory module identification.

Linux dmidecode -t memory emits Manufacturer in raw JEDEC format like
'00AD063200AD' (bank 0, ID 0xAD = SK hynix). This filter normalizes those
hex IDs to human-readable vendor names per JEP106 standard.

Fixes ticket B23/B71/B90 (Cisco Redfish CIMC also returns raw JEDEC like '0xCE00').

Usage in Ansible:
    {{ slot.manufacturer | jedec_to_vendor }}
"""
from __future__ import annotations

import re

# JEDEC JEP106 manufacturer IDs (selected — common DRAM vendors).
# Format: bank-1 digits ignored (single byte ID, MSB is parity bit, 7-bit ID).
# Source: https://www.jedec.org/standards-documents/docs/jep-106ab (public)
JEDEC_MAP = {
    # Bank 0 (no continuation byte) - 7-bit ID
    "01": "AMD",
    "04": "Fujitsu",
    "07": "Hitachi",
    "0B": "Intel",
    "1F": "Atmel",
    "2C": "Micron Technology",
    "AD": "SK hynix",
    "CE": "Samsung",
    # Bank 1
    "98": "Kingston",
    "B3": "IDT",
    "BA": "PNY Electronics",
    # Common variants emitted by dmidecode
    "0x2C": "Micron Technology",
    "0xAD": "SK hynix",
    "0xCE": "Samsung",
    "0x98": "Kingston",
    # Cisco CIMC variants (rule 96 external contract)
    "0xCE00": "Samsung",
    "0xAD00": "SK hynix",
    "0x2C00": "Micron Technology",
}

# Pattern matchers
HEX_PATTERN = re.compile(r"^[0-9A-Fa-f]{2,}$")  # Round 15: {4,}→{2,} — bare 2-char ID('AD'/'CE') 정규화 (len<4 → id_byte=s[:2], 직접 lookup 도달)
PREFIX_HEX_PATTERN = re.compile(r"^0x([0-9A-Fa-f]{2,})$", re.IGNORECASE)


# 2026-04-30 추가: vendor 이름 변형 → canonical name (cross-vendor consistency).
# BMC마다 같은 제조사를 다른 표기로 노출 (Dell="Hynix Semiconductor", Linux="SK hynix").
VENDOR_NAME_NORMALIZATION = {
    # SK hynix variants
    "hynix": "SK hynix",
    "hynix semiconductor": "SK hynix",
    "sk hynix": "SK hynix",
    "skhynix": "SK hynix",
    # Samsung
    "samsung electronics": "Samsung",
    "samsung electronic": "Samsung",
    # Micron
    "micron": "Micron Technology",
    "micron technology": "Micron Technology",
    # Kingston
    "kingston technology": "Kingston",
}


def _canonicalize_vendor_name(name):
    """Map vendor-name variants to a canonical form (e.g. 'Hynix Semiconductor' -> 'SK hynix')."""
    if not name:
        return name
    key = name.strip().lower()
    return VENDOR_NAME_NORMALIZATION.get(key, name)


def jedec_to_vendor(value):
    """Normalize a JEDEC manufacturer ID hex string to vendor name.

    Handles formats:
      - "00AD063200AD" -> "SK hynix" (Linux dmidecode raw)
      - "0xCE00"       -> "Samsung"   (Cisco Redfish CIMC)
      - "Samsung"      -> "Samsung"   (already normalized — pass through)
      - "Hynix Semiconductor" -> "SK hynix" (canonical normalization)
      - None / ""      -> None
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("unknown", "not specified", "none"):
        return None

    # 0x prefixed hex (Cisco CIMC: 0xCE00) — check FIRST before the vendor-name heuristic,
    # because '0x' contains 'x' which would otherwise trigger the heuristic.
    m = PREFIX_HEX_PATTERN.match(s)
    if m:
        hex_part = m.group(1).upper()
        # Try direct lookup first (full hex)
        if "0x" + hex_part in JEDEC_MAP:
            return JEDEC_MAP["0x" + hex_part]
        # Try first 2 chars
        if hex_part[:2] in JEDEC_MAP:
            return JEDEC_MAP[hex_part[:2]]
        return s  # Unknown — return raw

    # Already a recognizable vendor name (contains non-hex alpha or whitespace)
    # e.g. "Samsung", "Hynix Semiconductor", "VMware Virtual RAM"
    if any(c.isalpha() and c not in "ABCDEFabcdef" for c in s) or " " in s:
        return _canonicalize_vendor_name(s)

    # Plain hex (Linux dmidecode: 00AD063200AD)
    if HEX_PATTERN.match(s):
        # JEDEC: continuation count (00) + 1 byte ID + extra bytes (sometimes mfg-specific tail)
        # Take chars 2-4 (1 byte after the bank count) as the ID byte
        id_byte = s[2:4].upper() if len(s) >= 4 else s[:2].upper()
        if id_byte in JEDEC_MAP:
            return JEDEC_MAP[id_byte]
        # Try first 2 chars (some BMCs return ID directly without bank prefix)
        if s[:2].upper() in JEDEC_MAP:
            return JEDEC_MAP[s[:2].upper()]
        return s  # Unknown — return raw for traceability

    return _canonicalize_vendor_name(s)


class FilterModule:
    """Ansible filter plugin entrypoint."""

    def filters(self):
        return {
            "jedec_to_vendor": jedec_to_vendor,
        }
