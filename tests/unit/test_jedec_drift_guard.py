"""JEDEC 두 테이블 drift 가드 (AR-2, cycle 2026-06-04).

server-exporter 는 JEDEC JEP106 제조사 ID → DRAM vendor 이름 매핑을 두 곳에 둔다:
  TABLE A: filter_plugins/jedec_mapper.py        :: JEDEC_MAP        (OS-gather / Jinja 필터 경로)
  TABLE B: redfish-gather/library/redfish_gather.py :: _JEDEC_VENDORS (Redfish 경로, stdlib-only)

추가로 vendor 이름 canonical 정규화 테이블(VENDOR_NAME_NORMALIZATION)도 같은 두 파일에
mirror 되어 있어 동일한 cross-channel 위험이 있다 — test_vendor_name_normalization_mirrors 로 보호.

두 경로가 같은 JEDEC byte 를 **다른 vendor 이름**으로 해석하면 통합 envelope 의
`data.memory[].manufacturer` 가 채널별로 divergence (rule 13 cross-channel 정합 위반).
D-10 (2026-10-10): 두 테이블은 (bank, 7-bit ID) 키의 **같은 dict** 다 — alias row 가 없어졌으니 정확히 같아야 한다.
  bank = continuation(0x7F) 수, ID 는 parity 비트를 뗀 7-bit. 두 해석기(jedec_lookup / _jedec_lookup)도 같은 입력에 같은 답을 낸다.

불변식:
  1. 키 모양 — (int bank, int 0..0x7F) 만
  2. (HARD) JEDEC_MAP == _JEDEC_VENDORS
  3. 해석기 동치 — 대표 입력(dmidecode · CIMC · SPD 7F · bare · 미지) 에 두 채널이 같은 vendor
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load_jedec_map():
    """filter_plugins/jedec_mapper.py 의 JEDEC_MAP (TABLE A)."""
    sys.path.insert(0, str(REPO / "filter_plugins"))
    from jedec_mapper import JEDEC_MAP

    return JEDEC_MAP


def _load_jedec_vendors():
    """redfish_gather.py 의 _JEDEC_VENDORS (TABLE B).

    redfish_gather.py 는 top-level 에서 ansible.module_utils.basic 를 import 하므로
    최소 mock 등록 후 file-location import (test_probe_facts_extraction.py 패턴 동일).
    """
    if "ansible.module_utils.basic" not in sys.modules:
        mock_basic = types.ModuleType("ansible.module_utils.basic")
        mock_basic.AnsibleModule = type("AnsibleModule", (), {})
        sys.modules.setdefault("ansible", types.ModuleType("ansible"))
        sys.modules.setdefault("ansible.module_utils", types.ModuleType("ansible.module_utils"))
        sys.modules["ansible.module_utils.basic"] = mock_basic

    src = REPO / "redfish-gather" / "library" / "redfish_gather.py"
    spec = importlib.util.spec_from_file_location("redfish_gather_jedec_guard", str(src))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._JEDEC_VENDORS


def _load_vendor_name_norms():
    """두 VENDOR_NAME_NORMALIZATION dict 반환 (filter, redfish).

    AR-2 두 번째 중복 테이블 — vendor 이름 canonical 정규화도 두 채널에 mirror.
    """
    sys.path.insert(0, str(REPO / "filter_plugins"))
    from jedec_mapper import VENDOR_NAME_NORMALIZATION as filter_norm

    if "ansible.module_utils.basic" not in sys.modules:
        mock_basic = types.ModuleType("ansible.module_utils.basic")
        mock_basic.AnsibleModule = type("AnsibleModule", (), {})
        sys.modules.setdefault("ansible", types.ModuleType("ansible"))
        sys.modules.setdefault("ansible.module_utils", types.ModuleType("ansible.module_utils"))
        sys.modules["ansible.module_utils.basic"] = mock_basic
    src = REPO / "redfish-gather" / "library" / "redfish_gather.py"
    spec = importlib.util.spec_from_file_location("redfish_gather_vnorm_guard", str(src))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return filter_norm, mod._VENDOR_NAME_NORMALIZATION


def _assert_key_shape(table: dict) -> None:
    for k in table:
        assert isinstance(k, tuple) and len(k) == 2 and all(isinstance(x, int) for x in k), k
        assert k[0] >= 0 and 0 <= k[1] <= 0x7F, k


def _load_redfish_module():
    if "ansible.module_utils.basic" not in sys.modules:
        mock_basic = types.ModuleType("ansible.module_utils.basic")
        mock_basic.AnsibleModule = type("AnsibleModule", (), {})
        sys.modules.setdefault("ansible", types.ModuleType("ansible"))
        sys.modules.setdefault("ansible.module_utils", types.ModuleType("ansible.module_utils"))
        sys.modules["ansible.module_utils.basic"] = mock_basic
    src = REPO / "redfish-gather" / "library" / "redfish_gather.py"
    spec = importlib.util.spec_from_file_location("redfish_gather_jedec_resolver", str(src))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def table_a() -> dict:
    return _load_jedec_map()


@pytest.fixture(scope="module")
def table_b() -> dict:
    return _load_jedec_vendors()


def test_table_a_key_shape(table_a):
    """불변식 1: (bank, 7-bit ID) 키만."""
    _assert_key_shape(table_a)
    assert table_a, "JEDEC_MAP 이 비어 있음"


def test_table_b_key_shape(table_b):
    _assert_key_shape(table_b)
    assert table_b, "_JEDEC_VENDORS 가 비어 있음"


def test_tables_identical(table_a, table_b):
    """불변식 2 (HARD): 두 테이블이 같다 — 깨지면 같은 메모리 모듈이 OS 채널과 Redfish 채널에서 다른 manufacturer 로 나간다."""
    assert dict(table_a) == dict(table_b), (
        "JEDEC drift — jedec_mapper.JEDEC_MAP 과 redfish_gather._JEDEC_VENDORS 를 동기화하라 (rule 13 cross-channel)")


@pytest.mark.parametrize("raw", [
    "00AD063200AD", "80AD000080AD", "00CE0000", "002C0700", "0198", "0098", "7F98", "7FBA", "00BA",
    "AD", "CE", "4E", "89", "0B", "0x0B", "0xCE00", "0xAD00", "0x2C00", "0xBA01", "0xBA00", "00FF", "ACBE",
    "Samsung", "Hynix Semiconductor", "VMware Virtual RAM", None, "", "Unknown",
])
def test_resolvers_agree_on_representative_inputs(raw):
    """불변식 3: 두 해석기가 같은 답 — 알고리즘 복제본의 drift 를 입력 수준에서 막는다."""
    sys.path.insert(0, str(REPO / "filter_plugins"))
    from jedec_mapper import jedec_to_vendor

    assert jedec_to_vendor(raw) == _load_redfish_module()._normalize_jedec(raw), raw


@pytest.fixture(scope="module")
def vendor_name_norms():
    return _load_vendor_name_norms()


def test_vendor_name_normalization_mirrors(vendor_name_norms):
    """AR-2 두 번째 중복 테이블: vendor 이름 canonical 정규화가 두 채널에서 동일.

    `jedec_mapper.VENDOR_NAME_NORMALIZATION` (OS dmidecode 경로, _canonicalize_vendor_name)
    ↔ `redfish_gather._VENDOR_NAME_NORMALIZATION` (Redfish 경로, _canonical_vendor_name).
    JEDEC_MAP 과 달리 이 둘은 alias-row 같은 scope 차이가 없어 **정확히 mirror** 여야 한다.
    한쪽만 vendor 변형을 추가하면 같은 메모리가 채널별로 다른 manufacturer 로 정규화된다
    (cross-channel divergence, rule 13).
    """
    filter_norm, redfish_norm = vendor_name_norms
    only_filter = set(filter_norm) - set(redfish_norm)
    only_redfish = set(redfish_norm) - set(filter_norm)
    value_diff = {
        k: (filter_norm[k], redfish_norm[k])
        for k in set(filter_norm) & set(redfish_norm)
        if filter_norm[k] != redfish_norm[k]
    }
    assert not (only_filter or only_redfish or value_diff), (
        "VENDOR_NAME_NORMALIZATION 두 채널 drift — "
        f"filter-only={sorted(only_filter)} / redfish-only={sorted(only_redfish)} / "
        f"값충돌={value_diff}. jedec_mapper.py 와 redfish_gather._VENDOR_NAME_NORMALIZATION 을 "
        "동기화하라 (rule 13 cross-channel memory.manufacturer)."
    )
