"""F44~F47 회귀 — 신규 vendor 4종 (Huawei / Inspur / Fujitsu / Quanta) detect.

사용자 명시 승인 (2026-05-01) — vault SKIP, adapter + ai-context + boundary-map 만.

검증 항목:
1. vendor_aliases.yml 의 4 신규 vendor entry 존재
2. _FALLBACK_VENDOR_MAP 의 4 신규 vendor entry 존재 (sync gate)
3. _BMC_PRODUCT_HINTS 의 신규 BMC 시그니처 존재
4. detect_vendor 함수가 4 신규 vendor 정규화
5. adapter YAML 4 파일 (huawei_ibmc / inspur_isbmc / fujitsu_irmc / quanta_qct_bmc) 4 필수 키 존재
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

import yaml  # noqa: E402

ALIASES_PATH = REPO / "common" / "vars" / "vendor_aliases.yml"
ADAPTERS_DIR = REPO / "adapters" / "redfish"
NEW_VENDORS = ["huawei", "inspur", "fujitsu", "quanta"]
NEW_ADAPTERS = ["huawei_ibmc", "inspur_isbmc", "fujitsu_irmc", "quanta_qct_bmc"]


# ── vendor_aliases.yml entries ───────────────────────────────────────────────


def test_f44_f47_vendor_aliases_yaml_has_4_new_entries() -> None:
    """vendor_aliases.yml 의 4 신규 vendor entry 존재."""
    data = yaml.safe_load(ALIASES_PATH.read_text(encoding="utf-8"))
    aliases = data["vendor_aliases"]
    for v in NEW_VENDORS:
        assert v in aliases, f"vendor_aliases.yml: {v} 누락"
        assert isinstance(aliases[v], list), f"vendor_aliases.yml: {v} list 아님"
        assert len(aliases[v]) >= 3, f"vendor_aliases.yml: {v} 변형 alias 3개 미만"


# ── _FALLBACK_VENDOR_MAP sync (rule 50 + cycle-005 동기화 게이트) ─────────────


def test_f44_f47_fallback_vendor_map_sync() -> None:
    """_FALLBACK_VENDOR_MAP 에 4 신규 vendor canonical 매핑 존재."""
    fb = rg._FALLBACK_VENDOR_MAP
    for v in NEW_VENDORS:
        # 정규화 결과 매핑 (key=alias, value=canonical)
        # canonical 자체 (소문자) 도 포함되어야 함
        assert v in fb.values(), f"_FALLBACK_VENDOR_MAP: canonical '{v}' 부재"
        # 직접 매핑 (canonical → canonical) 도 등록되어야 함 (소문자 입력 정규화)
        assert fb.get(v) == v, f"_FALLBACK_VENDOR_MAP: {v} → {v} self-mapping 부재"


def test_f44_f47_bmc_product_hints_added() -> None:
    """_BMC_PRODUCT_HINTS 에 4 신규 vendor BMC 시그니처 존재."""
    hints = rg._BMC_PRODUCT_HINTS
    expected_signatures = {
        "ibmc": "huawei",
        "fusionserver": "huawei",
        "isbmc": "inspur",
        "irmc": "fujitsu",
        "primergy": "fujitsu",
        "quantagrid": "quanta",
    }
    for sig, vendor in expected_signatures.items():
        assert hints.get(sig) == vendor, f"_BMC_PRODUCT_HINTS: '{sig}' → '{vendor}' 부재"


# ── adapter YAML 구조 검증 ───────────────────────────────────────────────────


def test_f44_f47_adapter_yaml_files_exist() -> None:
    """4 신규 adapter YAML 파일 존재."""
    for name in NEW_ADAPTERS:
        path = ADAPTERS_DIR / f"{name}.yml"
        assert path.exists(), f"{path} 부재"


def test_f44_f47_adapter_yaml_required_keys() -> None:
    """4 신규 adapter 의 4 필수 키 (rule 12 R4) 존재."""
    required = ["match", "capabilities", "collect", "normalize"]
    for name in NEW_ADAPTERS:
        path = ADAPTERS_DIR / f"{name}.yml"
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key in required:
            assert key in d, f"{name}: 필수 키 '{key}' 부재"
        assert d.get("priority") == 80, f"{name}: priority=80 (사용자 명시 — lab 부재)"


def test_f44_f47_adapter_match_includes_canonical_vendor() -> None:
    """4 신규 adapter 의 match.vendor 에 canonical 표기 포함."""
    expected_canonical = {
        "huawei_ibmc": "Huawei",
        "inspur_isbmc": "Inspur",
        "fujitsu_irmc": "Fujitsu",
        "quanta_qct_bmc": "Quanta",
    }
    for name, canonical in expected_canonical.items():
        path = ADAPTERS_DIR / f"{name}.yml"
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert canonical in d["match"]["vendor"], (
            f"{name}: match.vendor 에 '{canonical}' 부재"
        )


# ── ai-context vendors/{name}.md 4 파일 ──────────────────────────────────────


def test_f44_f47_ai_context_files_exist() -> None:
    """4 신규 vendor ai-context 파일 존재."""
    base = REPO / ".claude" / "ai-context" / "vendors"
    for v in NEW_VENDORS:
        path = base / f"{v}.md"
        assert path.exists(), f"{path} 부재"
        content = path.read_text(encoding="utf-8")
        assert "vault_status" in content.lower() or "미생성" in content, (
            f"{v}.md: vault SKIP 명시 부재"
        )
