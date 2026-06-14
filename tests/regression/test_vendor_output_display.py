"""Vendor output-display mapping regression (cycle 2026-06-04).

사용자 결정 (2026-06-04): 호출자에게 노출되는 envelope 최상위 `vendor` 값을
내부 canonical 'hpe' → 'hp' 로 치환하고, HPE Compute Scale-up Server 3200
(CSUS 3200) 은 'hpCsus' 로 노출한다.

핵심 (Design A — 출력 라벨만 변경):
  - 내부 canonical 키 'hpe' 는 유지 (adapter 선택 / vault 경로 / OEM 추출 /
    account 복구 분기는 모두 'hpe' 그대로 라우팅 — 무손상).
  - 출력 envelope 의 vendor 값만 data-driven 표시 맵
    (common/vars/vendor_aliases.yml) 으로 재매핑.
  - CSUS 3200 한정: adapter_id == 'redfish_hpe_csus_3200' → 'hpCsus'
    (Superdome Flex 등 다른 RMC-primary 장비는 'hp').

Guards:
  D1 — vendor_aliases.yml 가 표시 맵 보유 (hpe->hp, csus adapter->hpCsus)
  D2 — hpe_baseline.json envelope vendor == 'hp'
  D3 — hpe_csus_3200_baseline.json envelope vendor == 'hpCsus'
  D4 — field_dictionary vendor enum 이 hp + hpCsus 노출 + 'hpe' 미노출
  D5 — 내부 canonical 'hpe' 보존 (라우팅 무손상)
  D6 — CANONICAL_VENDORS (cross-channel 게이트) 에 hp / hpCsus 포함
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALIASES = PROJECT_ROOT / "common" / "vars" / "vendor_aliases.yml"
BASELINE_DIR = PROJECT_ROOT / "schema" / "baseline_v1"
FIELD_DICT = PROJECT_ROOT / "schema" / "field_dictionary.yml"


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_d1_display_map_present() -> None:
    """vendor_aliases.yml 가 출력 표시 맵을 보유한다 (정규화 정본 위치)."""
    data = _load_yaml(ALIASES)
    assert data.get("vendor_output_display", {}).get("hpe") == "hp"
    assert (
        data.get("adapter_output_display", {}).get("redfish_hpe_csus_3200")
        == "hpCsus"
    )


def test_d2_hpe_baseline_vendor_is_hp() -> None:
    env = _load_json(BASELINE_DIR / "hpe_baseline.json")
    assert env["vendor"] == "hp"


def test_d3_csus_baseline_vendor_is_hpcsus() -> None:
    env = _load_json(BASELINE_DIR / "hpe_csus_3200_baseline.json")
    assert env["vendor"] == "hpCsus"


def test_d4_field_dictionary_enum_exposes_display_values() -> None:
    data = _load_yaml(FIELD_DICT)
    enum = data["fields"]["vendor"]["enum"]
    assert "hp" in enum, "출력 표시값 hp 가 vendor enum 에 있어야 함"
    assert "hpCsus" in enum, "CSUS 표시값 hpCsus 가 vendor enum 에 있어야 함"
    assert "hpe" not in enum, "내부 canonical 'hpe' 는 envelope 로 노출되지 않음"


def test_d5_internal_canonical_hpe_preserved() -> None:
    """내부 라우팅 키 'hpe' 는 vendor_aliases 에 그대로 유지 (Design A)."""
    data = _load_yaml(ALIASES)
    assert "hpe" in data["vendor_aliases"], (
        "내부 canonical 'hpe' 는 adapter/vault/OEM 라우팅용으로 보존되어야 함"
    )


def test_d6_canonical_vendors_gate_allows_display_values() -> None:
    """cross-channel envelope 게이트가 hp / hpCsus 를 허용한다."""
    from tests.regression.test_cross_channel_consistency import CANONICAL_VENDORS

    assert "hp" in CANONICAL_VENDORS
    assert "hpCsus" in CANONICAL_VENDORS


def test_d7_compute_scaleup_family_maps_to_hpcsus() -> None:
    """HPE 'Compute Scale-up Servers' 패밀리 전체 → hpCsus (2026-06-04 web 검증).

    HPE 공식 분류상 CSUS 3200 + Superdome Flex 는 동일 'Compute Scale-up Servers'
    패밀리 (둘 다 RMC 관리 scale-up). CSUS 3200 은 Superdome Flex 의 successor.
    source: hpe.com/.../servers/superdome.html (페이지 제목 = "Compute Scale-up Servers"),
            support.hpe.com sd00001798en_us / hpesbhf04632 (둘을 함께 문서화).
    """
    adapter_map = _load_yaml(ALIASES).get("adapter_output_display", {})
    for adapter_id in ("redfish_hpe_csus_3200", "redfish_hpe_superdome_flex"):
        assert adapter_map.get(adapter_id) == "hpCsus", (
            f"{adapter_id} 는 Compute Scale-up 패밀리 → hpCsus 여야 함"
        )
