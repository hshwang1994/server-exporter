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


# D-10 (2026-10-10): bank(continuation 수) 를 본다 — 같은 7-bit ID 가 bank 마다 다른 제조사다 (JEP106BE).
def test_bank_aware_kingston_vs_bank0():
    assert jedec_to_vendor("0198") == "Kingston"          # continuation 1 + 0x98 → bank 1 0x18 = Kingston
    assert jedec_to_vendor("7F98") == "Kingston"          # SPD/lshw 표기 (7F = continuation)
    assert jedec_to_vendor("0098") == "0098"              # bank 0 0x18(Toshiba/Kioxia) 는 DRAM 표에 없다 → 원문 (Kingston 으로 잘못 붙이지 않는다)
    assert jedec_to_vendor("98") == "Kingston"            # bank 미상(bare) → bank 0 없음 → bank 1


def test_bank_aware_pny_and_parity_stripped_ids():
    assert jedec_to_vendor("7FBA") == "PNY Technologies"
    assert jedec_to_vendor("0xBA01") == "PNY Technologies"  # CIMC 표기: ID 먼저, continuation 수 뒤
    assert jedec_to_vendor("00BA") == "00BA"                # bank 0 0x3A(Thomson CSF) 는 표에 없다 → 원문
    assert jedec_to_vendor("4E") == "Samsung" and jedec_to_vendor("CE") == "Samsung"   # parity 비트 유무 모두
    assert jedec_to_vendor("2D") == "SK hynix" and jedec_to_vendor("80AD") == "SK hynix"


def test_intel_is_0x89_not_0x0b():
    assert jedec_to_vendor("0089") == "Intel" and jedec_to_vendor("0x89") == "Intel"
    assert jedec_to_vendor("000B") == "000B"   # 0x0B 는 Intersil — 종전 표의 "0B": Intel 은 오류였다
