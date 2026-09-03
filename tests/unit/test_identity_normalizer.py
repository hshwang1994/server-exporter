"""identity_normalizer 필터 — 채널 간 식별자 표기 정규화 (2026-09-03 전수 검수 B-06/B-24/B-26).

입력값은 전부 실장비 캡처(baseline / tests/reference) 에서 그대로 가져왔다.
같은 장비가 채널마다 다른 표기로 나오던 값이 한 형식으로 모이는지 잠근다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))

from identity_normalizer import (  # noqa: E402
    FilterModule,
    normalize_mac,
    normalize_uuid,
    normalize_wwn,
    uuid_byteswap,
    uuid_equal,
)


# ── MAC ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("00-50-56-84-C9-5F", "00:50:56:84:c9:5f"),   # Windows Get-NetAdapter (baseline windows_2022)
        ("00:50:56:84:8b:b9", "00:50:56:84:8b:b9"),   # Linux sysfs (baseline ubuntu) — 불변
        ("00:27:E3:6C:A6:60", "00:27:e3:6c:a6:60"),   # Redfish 대문자 (cisco baseline)
        ("0050.5684.c95f", "00:50:56:84:c9:5f"),      # Cisco dotted
        ("005056 84c95f", "00:50:56:84:c9:5f"),
        (" 00-50-56-84-C9-5F ", "00:50:56:84:c9:5f"),
    ],
)
def test_mac_normalized_to_lower_colon(raw, expected):
    assert normalize_mac(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "00:00:00:00:00:00", "00-00-00-00-00-00"])
def test_mac_empty_or_zero_is_null(raw):
    assert normalize_mac(raw) is None


def test_mac_unexpected_length_kept_lowercase_not_fabricated():
    assert normalize_mac("00:50:56") == "00:50:56"
    assert normalize_mac("N/A") == "n/a"


# ── WWN ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0x20000027e36ca66e", "20:00:00:27:e3:6c:a6:6e"),          # Linux /sys/class/fc_host port_name
        ("20:00:00:27:E3:6C:A6:6E", "20:00:00:27:e3:6c:a6:6e"),     # ESXi vmhba port_wwn (esxi baseline)
        ("20:00:00:24:ff:8b:1a:01", "20:00:00:24:ff:8b:1a:01"),     # Redfish (csus mock) — 불변
        ("20000027E36CA66E", "20:00:00:27:e3:6c:a6:6e"),            # Windows raw hex
    ],
)
def test_wwn_normalized_to_lower_colon(raw, expected):
    assert normalize_wwn(raw) == expected


def test_wwn_empty_or_zero_is_null():
    assert normalize_wwn(None) is None
    assert normalize_wwn("") is None
    assert normalize_wwn("0x0000000000000000") is None


def test_wwn_unexpected_length_kept_lowercase():
    assert normalize_wwn("eui.0025385a91b1c5d2") == "eui.0025385a91b1c5d2"


# ── UUID ────────────────────────────────────────────────────────────────────
def test_uuid_windows_uppercase_lowercased():
    # baseline windows_2022 correlation.system_uuid
    assert normalize_uuid("40A20442-5C1D-C963-F60B-5FB47298D7DD") == "40a20442-5c1d-c963-f60b-5fb47298d7dd"


def test_uuid_braces_and_no_dash_accepted():
    assert normalize_uuid("{40A20442-5C1D-C963-F60B-5FB47298D7DD}") == "40a20442-5c1d-c963-f60b-5fb47298d7dd"
    assert normalize_uuid("40a204425c1dc963f60b5fb47298d7dd") == "40a20442-5c1d-c963-f60b-5fb47298d7dd"


@pytest.mark.parametrize(
    "raw",
    [None, "", "00000000-0000-0000-0000-000000000000", "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"],
)
def test_uuid_sentinel_is_null(raw):
    assert normalize_uuid(raw) is None


def test_uuid_unexpected_shape_kept_lowercase():
    assert normalize_uuid("NA") == "na"


def test_uuid_same_box_redfish_vs_esxi_matches_via_byteswap():
    """같은 물리 장비 Cisco C220 (serial FCH2116V1V0):
    cisco_baseline hardware.uuid vs esxi_baseline hardware.uuid — 앞 3 필드 바이트 순서만 다르다."""
    redfish = "B190019F-56CE-4ED4-A1DD-6571DAAEDAD7"
    esxi = "9f0190b1-ce56-d44e-a1dd-6571daaedad7"
    assert normalize_uuid(redfish) != normalize_uuid(esxi)
    assert uuid_byteswap(redfish) == normalize_uuid(esxi)
    assert uuid_equal(redfish, esxi) is True
    assert uuid_equal(esxi, redfish) is True


def test_uuid_equal_same_order_and_case_insensitive():
    assert uuid_equal("40A20442-5C1D-C963-F60B-5FB47298D7DD", "40a20442-5c1d-c963-f60b-5fb47298d7dd")


def test_uuid_equal_null_never_matches():
    assert uuid_equal(None, "40a20442-5c1d-c963-f60b-5fb47298d7dd") is False
    assert uuid_equal("00000000-0000-0000-0000-000000000000", "00000000-0000-0000-0000-000000000000") is False


def test_byteswap_is_involution():
    u = "9f0190b1-ce56-d44e-a1dd-6571daaedad7"
    assert uuid_byteswap(uuid_byteswap(u)) == u


def test_filter_module_exposes_all():
    names = set(FilterModule().filters())
    assert {"normalize_mac", "normalize_wwn", "normalize_uuid", "uuid_byteswap", "uuid_equal"} <= names
