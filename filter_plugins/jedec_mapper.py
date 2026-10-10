#!/usr/bin/env python3
"""JEDEC manufacturer ID mapper for memory module identification.

Linux dmidecode -t memory emits Manufacturer in raw JEDEC format like
'00AD063200AD' (continuation count 0, ID 0xAD = SK hynix). Cisco CIMC emits '0xCE00'
(ID 0xCE, then the continuation count). This filter normalizes those hex IDs to
human-readable vendor names per JEP106.

D-10 (2026-10-10): the table is keyed by **(bank, 7-bit ID)** — bank = number of
continuation codes (0x7F bytes). The same 7-bit ID means a different vendor in another
bank (0x18: bank 1 = Kingston; bank 0 = Toshiba/Kioxia), so a byte-only table mislabels.
The parity bit (MSB) is stripped: 'CE' and '4E' are both Samsung.

Sources (rule 96 origin): JEP106BE via the jep106 crate table
(https://docs.rs/crate/jep106/latest/source/src/codes.rs, read 2026-10-10 — bank 0: 0x01 AMD,
0x04 Fujitsu[RAMXEED], 0x07 Hitachi, 0x09 Intel, 0x0B Intersil, 0x1F Atmel, 0x2C Micron,
0x2D SK Hynix, 0x33 IDT, 0x4E Samsung; bank 1: 0x18 Kingston, 0x3A PNY Technologies),
lshw src/core/jedec.cc ("7F98" Kingston, "98"/"8098" Toshiba),
Linux include/linux/mtd/cfi.h (CFI_MFR_INTEL 0x0089, CFI_MFR_ATMEL 0x001F, CFI_MFR_MICRON 0x002C,
CFI_MFR_HYUNDAI 0x00AD — parity-coded bank 0 IDs). The pre-audit entry "0B": Intel was wrong
(0x0B is Intersil; Intel is 0x89 with parity / 0x09 7-bit).

Mirror: redfish-gather/library/redfish_gather.py :: _JEDEC_VENDORS / _normalize_jedec (stdlib only).
tests/unit/test_jedec_drift_guard.py keeps the two identical.

Usage in Ansible:
    {{ slot.manufacturer | jedec_to_vendor }}
"""
from __future__ import annotations

import re

# (bank, 7-bit ID) → vendor. Only DRAM-module relevant vendors — unknown codes pass through raw (traceability).
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

# Round 15: {4,}→{2,} — bare 2-char ID('AD'/'CE') 정규화. D-10: 짝수 길이 hex 바이트열.
HEX_PATTERN = re.compile(r"^[0-9A-Fa-f]{2,}$")
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


def jedec_lookup(hex_text, id_first=False):
    """Resolve a raw JEDEC hex byte string to (vendor, bank, id7) or None.

    hex_text: hex bytes without '0x'. Layouts:
      - continuation style  '7F98'          → leading 0x7F bytes = bank, next byte = ID
      - count-first (dmidecode) '00AD0632…' / '80AD…' / '0198' → first byte & 0x7F = bank, second byte = ID
      - ID-first (Cisco CIMC, id_first=True) 'CE00' → first byte = ID, second byte & 0x7F = bank
      - a single byte 'AD' → bank unknown: bank 0 first, then bank 1 (DRAM module makers such as Kingston/PNY sit in bank 1)
    """
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
    """Normalize a JEDEC manufacturer ID hex string to vendor name.

    Handles formats:
      - "00AD063200AD" -> "SK hynix" (Linux dmidecode raw; bank byte first)
      - "0xCE00"       -> "Samsung"   (Cisco Redfish CIMC; ID first)
      - "7F98"         -> "Kingston"  (SPD/lshw continuation style)
      - "Samsung"      -> "Samsung"   (already normalized — pass through)
      - "Hynix Semiconductor" -> "SK hynix" (canonical normalization)
      - None / ""      -> None
      - unknown hex    -> raw string (traceability)
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
        hit = jedec_lookup(m.group(1).upper(), id_first=True)
        return hit[0] if hit else s

    # Already a recognizable vendor name (contains non-hex alpha or whitespace)
    # e.g. "Samsung", "Hynix Semiconductor", "VMware Virtual RAM"
    if any(c.isalpha() and c not in "ABCDEFabcdef" for c in s) or " " in s:
        return _canonicalize_vendor_name(s)

    # Plain hex (Linux dmidecode: 00AD063200AD / bare AD)
    if HEX_PATTERN.match(s):
        hit = jedec_lookup(s.upper())
        return hit[0] if hit else s  # Unknown — return raw for traceability

    return _canonicalize_vendor_name(s)


class FilterModule:
    """Ansible filter plugin entrypoint."""

    def filters(self):
        return {
            "jedec_to_vendor": jedec_to_vendor,
        }
