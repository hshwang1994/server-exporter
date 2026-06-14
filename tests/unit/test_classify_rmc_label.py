"""ADR-2026-05-12 회귀 — `_classify_rmc_label` / `_classify_manager_role` /
`_classify_chassis_kind` 단위 테스트 (cycle 2026-05-12).

HPE CSUS 3200 / Superdome Flex RMC primary 시스템에서 Manager / Chassis 라벨 분기:
  - RMC (Rack Management Controller) → 'RMC' / role='primary'
  - PDHC (per-chassis controller) → 'PDHC' / role='secondary'
  - per-node iLO 5 → 'iLO' / role='secondary'
  - Chassis Base / Expansion / Compute Module 구분

검증 항목:
1. manager_layout=None → 기존 동작 (None 반환 — 호출자 bmc_names fallback)
2. ID substring 'rmc' → 'RMC' / role='primary'
3. ID substring 'pdhc' → 'PDHC' / role='secondary'
4. ID substring 'ilo' → 'iLO' / role='secondary'
5. layout default fallback (Manager ID 매칭 안 됨) → 'RMC' (rmc_primary)
6. Chassis kind 분류 — base / expansion / compute_module / ChassisType fallback
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

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


# ── _classify_rmc_label ──────────────────────────────────────────────────────


def test_classify_rmc_label_none_layout_returns_none() -> None:
    """manager_layout=None 시 None 반환 (기존 동작 보존 — bmc_names fallback)."""
    assert rg._classify_rmc_label("/redfish/v1/Managers/RMC", "RMC", None) is None
    assert rg._classify_rmc_label("/redfish/v1/Managers/1", "1", None) is None


def test_classify_rmc_label_id_substring_rmc() -> None:
    """ID 또는 URI 의 'rmc' substring → 'RMC'."""
    assert rg._classify_rmc_label(
        "/redfish/v1/Managers/RMC", "RMC", "rmc_primary"
    ) == "RMC"
    assert rg._classify_rmc_label(
        "/redfish/v1/Managers/rmc1", "rmc1", "rmc_primary_ilo_secondary"
    ) == "RMC"


def test_classify_rmc_label_id_substring_pdhc() -> None:
    """ID substring 'pdhc' → 'PDHC' (HPE per-chassis controller)."""
    assert rg._classify_rmc_label(
        "/redfish/v1/Managers/PDHC0", "PDHC0", "rmc_primary"
    ) == "PDHC"


def test_classify_rmc_label_id_substring_ilo() -> None:
    """ID substring 'ilo' → 'iLO' (per-node iLO 5)."""
    assert rg._classify_rmc_label(
        "/redfish/v1/Managers/Bay1.iLO5", "Bay1.iLO5", "rmc_primary_ilo_secondary"
    ) == "iLO"


def test_classify_rmc_label_layout_default_rmc_primary() -> None:
    """ID 매칭 실패 + layout='rmc_primary' → 'RMC' (default first manager)."""
    assert rg._classify_rmc_label(
        "/redfish/v1/Managers/1", "1", "rmc_primary"
    ) == "RMC"


def test_classify_rmc_label_unknown_layout_returns_none() -> None:
    """알려지지 않은 layout (예: 'foo_layout') + ID 매칭 실패 시 None."""
    assert rg._classify_rmc_label(
        "/redfish/v1/Managers/1", "1", "foo_layout"
    ) is None


# ── _classify_manager_role ───────────────────────────────────────────────────


def test_classify_manager_role_none_layout_returns_none() -> None:
    """manager_layout=None 시 None."""
    assert rg._classify_manager_role(
        "/redfish/v1/Managers/RMC", "RMC", None
    ) is None


def test_classify_manager_role_rmc_is_primary() -> None:
    """ID 'RMC' substring → role='primary'."""
    assert rg._classify_manager_role(
        "/redfish/v1/Managers/RMC", "RMC", "rmc_primary"
    ) == "primary"


def test_classify_manager_role_pdhc_is_secondary() -> None:
    """ID 'PDHC' substring + rmc_primary → role='secondary'."""
    assert rg._classify_manager_role(
        "/redfish/v1/Managers/PDHC0", "PDHC0", "rmc_primary"
    ) == "secondary"


def test_classify_manager_role_ilo_is_secondary() -> None:
    """ID 'iLO' substring + rmc_primary_ilo_secondary → role='secondary'."""
    assert rg._classify_manager_role(
        "/redfish/v1/Managers/Bay1.iLO5", "Bay1.iLO5", "rmc_primary_ilo_secondary"
    ) == "secondary"


# ── _classify_chassis_kind ───────────────────────────────────────────────────


def test_classify_chassis_kind_base() -> None:
    """ID 'Base' substring → 'base'."""
    assert rg._classify_chassis_kind(
        "/redfish/v1/Chassis/Base", "Base", {}
    ) == "base"


def test_classify_chassis_kind_expansion() -> None:
    """ID 'Expansion' substring → 'expansion'."""
    assert rg._classify_chassis_kind(
        "/redfish/v1/Chassis/Expansion1", "Expansion1", {}
    ) == "expansion"


def test_classify_chassis_kind_compute_module() -> None:
    """ID 'compute' substring → 'compute_module'."""
    assert rg._classify_chassis_kind(
        "/redfish/v1/Chassis/compute1", "compute1", {}
    ) == "compute_module"


def test_classify_chassis_kind_chassis_type_fallback() -> None:
    """ID 매칭 실패 시 ChassisType 표준 fallback (Enclosure → 'enclosure')."""
    assert rg._classify_chassis_kind(
        "/redfish/v1/Chassis/1", "1",
        {"ChassisType": "Enclosure"},
    ) == "enclosure"


def test_classify_chassis_kind_unknown_returns_none() -> None:
    """ID 매칭 실패 + ChassisType 미정의 → None."""
    assert rg._classify_chassis_kind(
        "/redfish/v1/Chassis/1", "1", {}
    ) is None
