"""Unit test for jedec_mapper filter (B23 + B71 + B90 + B91)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))

from jedec_mapper import jedec_to_vendor


def test_linux_dmidecode_sk_hynix():
    """B23: Linux dmidecode '00AD063200AD' -> 'SK hynix'."""
    assert jedec_to_vendor("00AD063200AD") == "SK hynix"


def test_linux_dmidecode_samsung():
    assert jedec_to_vendor("00CE0000") == "Samsung"


def test_linux_dmidecode_micron():
    assert jedec_to_vendor("002C0700") == "Micron Technology"


def test_cisco_cimc_prefix_hex_samsung():
    """B90: Cisco CIMC '0xCE00' -> 'Samsung'."""
    assert jedec_to_vendor("0xCE00") == "Samsung"


def test_cisco_cimc_prefix_hex_hynix():
    assert jedec_to_vendor("0xAD") == "SK hynix"


def test_already_normalized_passthrough():
    """Redfish vendors normalize already (Samsung / Micron Technology) — pass through.

    2026-04-30: Hynix variants now normalize to canonical 'SK hynix' (cross-vendor consistency).
    """
    assert jedec_to_vendor("Samsung") == "Samsung"
    assert jedec_to_vendor("Micron Technology") == "Micron Technology"
    assert jedec_to_vendor("VMware Virtual RAM") == "VMware Virtual RAM"


def test_canonical_vendor_normalization():
    """Cross-vendor consistency: Hynix variants → 'SK hynix'."""
    assert jedec_to_vendor("Hynix Semiconductor") == "SK hynix"
    assert jedec_to_vendor("Hynix") == "SK hynix"
    assert jedec_to_vendor("SK Hynix") == "SK hynix"
    # Samsung variants
    assert jedec_to_vendor("Samsung Electronics") == "Samsung"
    # Micron variants
    assert jedec_to_vendor("Micron") == "Micron Technology"


def test_none_or_empty():
    assert jedec_to_vendor(None) is None
    assert jedec_to_vendor("") is None
    assert jedec_to_vendor("Unknown") is None
    assert jedec_to_vendor("Not Specified") is None


def test_unknown_hex_returns_raw():
    """Unknown hex ID should return the raw value for traceability."""
    assert jedec_to_vendor("00FF") == "00FF"


def test_strip_whitespace():
    assert jedec_to_vendor("  00AD  ") == "SK hynix"
    assert jedec_to_vendor(" Samsung  ") == "Samsung"
