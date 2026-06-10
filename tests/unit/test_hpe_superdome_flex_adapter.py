"""회귀 — HPE Superdome Flex / Flex 280 adapter (lab 부재).

web 검색 (14 sources) + adapter 추가.

검증 항목:
1. adapter YAML 4 필수 키 + priority=101 (iLO 6(100) catch-all 위, iLO 7(120) 아래)
2. match.model_patterns 에 Superdome Flex 280 / Superdome Flex 패턴 포함
3. match.vendor = HPE (sub-line 결정)
4. capabilities.sections_supported 9 sections (system/hardware/bmc/cpu/memory/storage/network/firmware/power)
5. capabilities.sections_supported 에 users 미포함 (sections.yml channels=[os] 정합)
6. credentials.profile = "hpe" (vault 재사용)
7. collect.oem_tasks = HPE 공유 (Oem.Hpe namespace)
8. _BMC_PRODUCT_HINTS 에 'superdome' 시그니처 → 'hpe' 정규화
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402

ADAPTER_PATH = REPO / "adapters" / "redfish" / "hpe_superdome_flex.yml"
SECTIONS_YML = REPO / "schema" / "sections.yml"


# ── adapter YAML 4 필수 키 + priority ────────────────────────────────────────


def test_adapter_yaml_exists() -> None:
    """hpe_superdome_flex.yml 파일 존재."""
    assert ADAPTER_PATH.exists(), f"{ADAPTER_PATH} 부재 — adapter 미작성"


def test_adapter_required_keys() -> None:
    """match / capabilities / collect / normalize 4 필수 키."""
    d = yaml.safe_load(ADAPTER_PATH.read_text(encoding="utf-8"))
    for key in ("match", "capabilities", "collect", "normalize"):
        assert key in d, f"hpe_superdome_flex: 필수 키 '{key}' 부재"


def test_priority_above_ilo6_below_ilo7() -> None:
    """priority=101 — iLO 6 (100) < Superdome Flex (101) < iLO 7 (120). priority 일관성.

    구 95 → 101 상향.
    이유: hpe_ilo6 (100) 은 model_patterns 부재라 절대 실격되지 않아, 구 95 Superdome 이
    모델("Superdome Flex")을 매치해도 priority 로 패배 → 사이트에서 vendor=hp 오선택.
    scale-up 2 종(CSUS 102 / Superdome 101)을 iLO 6(100) 위로 올려 모델 매치 우선권 부여.
    정상 ProLiant 는 scale-up model_patterns 미매치 → 실격되어 iLO 5/6/7 자동 선택 (무회귀).
    """
    d = yaml.safe_load(ADAPTER_PATH.read_text(encoding="utf-8"))
    assert d.get("priority") == 101, (
        "Superdome Flex priority=101 (iLO 6(100) 위, iLO 7(120) 아래)."
    )


# ── match 검증 ───────────────────────────────────────────────────────────────


def test_match_vendor_is_hpe_sub_line() -> None:
    """match.vendor = HPE (sub-line 결정)."""
    d = yaml.safe_load(ADAPTER_PATH.read_text(encoding="utf-8"))
    vendors = d["match"]["vendor"]
    assert "HPE" in vendors, "match.vendor 에 'HPE' 부재"
    assert "Hewlett Packard Enterprise" in vendors, "match.vendor 에 풀네임 부재"


def test_match_model_patterns_superdome_flex() -> None:
    """match.model_patterns 에 Superdome Flex 280 / Superdome Flex 패턴."""
    d = yaml.safe_load(ADAPTER_PATH.read_text(encoding="utf-8"))
    patterns = d["match"]["model_patterns"]
    pattern_str = "\n".join(patterns)
    assert "Superdome Flex 280" in pattern_str, "model_patterns 에 'Superdome Flex 280' 부재"
    assert "Superdome Flex" in pattern_str, "model_patterns 에 'Superdome Flex' 부재"


# ── capabilities 검증 (users 미포함) ───────────────────────────────


def test_capabilities_9_sections_no_users() -> None:
    """capabilities.sections_supported 9 sections — users 미포함 (sections.yml channels=[os] 정합)."""
    d = yaml.safe_load(ADAPTER_PATH.read_text(encoding="utf-8"))
    sections = d["capabilities"]["sections_supported"]
    expected_9 = {"system", "hardware", "bmc", "cpu", "memory",
                  "storage", "network", "firmware", "power"}
    assert set(sections) == expected_9, (
        f"capabilities.sections_supported 9 sections 일치 필요. "
        f"실제: {sorted(sections)}, 기대: {sorted(expected_9)}"
    )
    assert "users" not in sections, (
        "users 섹션은 sections.yml channels=[os] — Redfish 채널 미해당"
    )


# ── credentials / collect (HPE 재사용) ──────────────────────────────────────


def test_credentials_profile_hpe() -> None:
    """credentials.profile = 'hpe' — vault/redfish/hpe.yml 재사용 (별도 vault 불필요)."""
    d = yaml.safe_load(ADAPTER_PATH.read_text(encoding="utf-8"))
    assert d["credentials"]["profile"] == "hpe", (
        "HPE sub-line 결정. vault profile=hpe 재사용"
    )


def test_collect_oem_reuses_hpe() -> None:
    """collect.oem_tasks 가 HPE 기존 OEM tasks 재사용 (Oem.Hpe namespace 동일)."""
    d = yaml.safe_load(ADAPTER_PATH.read_text(encoding="utf-8"))
    oem_path = d["collect"]["oem_tasks"]
    assert "vendors/hpe/" in oem_path, (
        f"collect.oem_tasks 가 HPE OEM 재사용해야 함. 실제: {oem_path}"
    )


# ── _BMC_PRODUCT_HINTS Superdome 시그니처 ────────────────────────────────────


def test_bmc_product_hints_superdome_added() -> None:
    """_BMC_PRODUCT_HINTS 에 superdome 시그니처 → 'hpe' 정규화."""
    hints = rg._BMC_PRODUCT_HINTS
    assert hints.get("superdome") == "hpe", (
        "_BMC_PRODUCT_HINTS: 'superdome' → 'hpe' 매핑 부재"
    )
    assert hints.get("superdome flex") == "hpe", (
        "_BMC_PRODUCT_HINTS: 'superdome flex' → 'hpe' 매핑 부재"
    )


# ── adapter origin 주석 (web sources 14건) ───────────────────


def test_adapter_has_origin_metadata() -> None:
    """adapter YAML 에 origin metadata 주석 + web sources 명시."""
    content = ADAPTER_PATH.read_text(encoding="utf-8")
    assert "Origin metadata" in content, "Origin metadata 주석 부재"
    assert "Last sync" in content, "Last sync 일자 명시 부재"
    assert "Lab: 부재" in content or "lab 부재" in content.lower(), (
        "lab 부재 명시 부재"
    )
    # 최소 web sources 5건 명시 (실제 14건 sources)
    source_count = content.count("source:")
    assert source_count >= 5, (
        f"web sources 5건 이상 명시 권장 (14건). 실제: {source_count}"
    )


# ── sections.yml channels 정합 ────────────────────────────────────


def test_sections_yml_users_redfish_misalign() -> None:
    """sections.yml 의 users channels 가 Redfish 채널 미포함 — Superdome Flex 도 동일 정합."""
    d = yaml.safe_load(SECTIONS_YML.read_text(encoding="utf-8"))
    sections = d.get("sections", {})
    users_section = sections.get("users")
    assert users_section is not None, "sections.yml 에 'users' 섹션 부재"
    channels = users_section.get("channels", [])
    assert "redfish" not in channels, (
        f"sections.yml: users channels 에 'redfish' 포함되면 안 됨. 실제: {channels}"
    )
    assert "os" in channels, f"sections.yml: users channels 에 'os' 포함 필요. 실제: {channels}"
