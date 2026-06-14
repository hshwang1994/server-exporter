"""JEDEC 두 테이블 drift 가드 (AR-2, cycle 2026-06-04).

server-exporter 는 JEDEC JEP106 제조사 ID → DRAM vendor 이름 매핑을 두 곳에 둔다:
  TABLE A: filter_plugins/jedec_mapper.py        :: JEDEC_MAP        (OS-gather / Jinja 필터 경로)
  TABLE B: redfish-gather/library/redfish_gather.py :: _JEDEC_VENDORS (Redfish 경로, stdlib-only)

추가로 vendor 이름 canonical 정규화 테이블(VENDOR_NAME_NORMALIZATION)도 같은 두 파일에
mirror 되어 있어 동일한 cross-channel 위험이 있다 — test_vendor_name_normalization_mirrors 로 보호.

두 경로가 같은 JEDEC byte 를 **다른 vendor 이름**으로 해석하면 통합 envelope 의
`data.memory[].manufacturer` 가 채널별로 divergence (rule 13 cross-channel 정합 위반).
본 테스트는 그 drift 만 잡고, 두 테이블이 **scope/표현**(A 는 '0x'·4자리 alias row 보유)에서
정당하게 다른 것은 허용한다.

정규화 규칙 (각 런타임이 자기 테이블을 INDEX 하는 byte 키 도출과 동일):
  raw key → 선행 '0x'/'0X' 제거 → 앞 2 hex 문자 → upper
  (A: full '0x'+hex 우선 후 [:2] / B: '0x' strip 후 [:2] — 둘 다 byte 로 수렴)
  주의: 입력 ACCEPTANCE 경계는 A(bare hex ≥4자 — HEX_PATTERN) ↔ B(≥2자) 로 다르나,
  이는 테이블 VALUE drift 가 아니라 입력 수용 차이 (실 채널 입력 = dmidecode '00AD..' / CIMC '0xCE00').
  본 가드의 범위 = 테이블 byte 키의 vendor 값 cross-channel 일치 (입력→출력 full parity 아님).

불변식:
  1. 각 테이블 내부 self-consistency — 같은 byte 로 정규화되는 alias row 가 충돌 값 금지
  2. (HARD) 공유 byte 키의 vendor 값 동일 — 채널 간 manufacturer 일치 보장
  3. (방향성) B(Redfish) 정규화 키 ⊆ A(OS+CIMC) 정규화 키 — B 에만 있는 byte 는
     OS-gather 가 못 풀어 silent fail → 미러링 누락 신호
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


def _norm_byte(key: str) -> str:
    """raw JEDEC key → canonical 1-byte hex (선행 0x 제거 + 앞 2자 + upper)."""
    k = key
    if k.lower().startswith("0x"):
        k = k[2:]
    return k[:2].upper()


def _normalized_table(raw: dict) -> dict:
    """raw dict → {byte: vendor}. 내부 alias 충돌 시 AssertionError (불변식 1)."""
    out: dict = {}
    for k, v in raw.items():
        b = _norm_byte(k)
        if b in out and out[b] != v:
            pytest.fail(
                f"테이블 내부 self-collision: byte '{b}' 가 "
                f"'{out[b]}' 와 '{v}' 두 값으로 매핑 (alias row 불일치)"
            )
        out[b] = v
    return out


@pytest.fixture(scope="module")
def table_a() -> dict:
    return _load_jedec_map()


@pytest.fixture(scope="module")
def table_b() -> dict:
    return _load_jedec_vendors()


def test_table_a_internally_consistent(table_a):
    """불변식 1: JEDEC_MAP 의 '0x'/4자리 alias row 가 base byte 와 충돌하지 않음."""
    norm = _normalized_table(table_a)
    assert norm, "JEDEC_MAP 정규화 결과가 비어 있음"


def test_table_b_internally_consistent(table_b):
    """불변식 1: _JEDEC_VENDORS 내부 충돌 없음."""
    norm = _normalized_table(table_b)
    assert norm, "_JEDEC_VENDORS 정규화 결과가 비어 있음"


def test_shared_keys_agree(table_a, table_b):
    """불변식 2 (HARD): 공유 byte 키의 vendor 값이 두 테이블에서 동일.

    이게 깨지면 같은 메모리 모듈이 OS-gather 채널과 Redfish 채널에서
    다른 manufacturer 로 출력된다 (cross-channel divergence).
    """
    na, nb = _normalized_table(table_a), _normalized_table(table_b)
    shared = set(na) & set(nb)
    assert shared, "두 테이블에 공유 byte 키가 없음 (정규화 오류 의심)"
    mismatches = {b: (na[b], nb[b]) for b in shared if na[b] != nb[b]}
    assert not mismatches, (
        f"JEDEC vendor drift — 공유 byte 가 채널별로 다른 vendor: {mismatches}. "
        f"jedec_mapper.py 와 redfish_gather._JEDEC_VENDORS 를 동기화하라 (rule 13 cross-channel)."
    )


def test_redfish_keys_subset_of_filter(table_a, table_b):
    """불변식 3 (방향성): B(Redfish) 정규화 키 ⊆ A(OS+CIMC) 정규화 키.

    A 가 더 넓은 경로(OS dmidecode + Cisco CIMC)라 superset 이어야 한다.
    B 에만 새 byte 가 생기면 OS-gather 가 그 ID 를 못 풀어 raw 노출 → 미러링 누락 신호.
    """
    na, nb = _normalized_table(table_a), _normalized_table(table_b)
    only_in_b = set(nb) - set(na)
    assert not only_in_b, (
        f"_JEDEC_VENDORS 에만 있는 byte: {sorted(only_in_b)} — "
        f"filter_plugins/jedec_mapper.py JEDEC_MAP 에 미러링하라 (OS-gather 채널 누락 방지)."
    )


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
