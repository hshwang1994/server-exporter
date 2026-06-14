"""
Supermicro adapter selection 회귀 (cycle 2026-05-11 adapter-selection-review).

본 테스트는 다음 시나리오 매트릭스를 검증한다:

| # | facts                                                       | expected adapter             | 비고 |
|---|---|---|---|
| 1 | Supermicro / X11 / firmware=1.73.10                         | redfish_supermicro_x11       | priority 100 |
| 2 | Supermicro / H11 / firmware=1.73                            | redfish_supermicro_x11       | H11 alias |
| 3 | Supermicro / X12 / firmware=01.03.03                        | redfish_supermicro_x12       | DRIFT-015 fix (priority 90 → 100) |
| 4 | Supermicro / H12 / firmware=01.05.10                        | redfish_supermicro_x12       | H12 alias |
| 5 | Supermicro / X13 / firmware=01.05.00                        | redfish_supermicro_x13       | priority 100 |
| 6 | Supermicro / B13 / firmware=01.06.00                        | redfish_supermicro_x13       | B13 alias |
| 7 | Supermicro / X14 / firmware=01.20.00                        | redfish_supermicro_x14       | priority 110 |
| 8 | Supermicro / X12 + ARS / firmware=''                        | redfish_supermicro_x12       | ARS 모델 (Altra Cobalt) priority 80 vs X12 100 |
| 9 | Supermicro / model='' / firmware='' (T-01 시나리오)         | redfish_supermicro_x14       | 현재 동작 — facts empty 시 priority 최상위 |
| 10 | Supermicro / model=Unknown / firmware='' (generic fallback) | redfish_supermicro_bmc       | priority 10 fallback |
| 11 | Dell / model='' / firmware='' (타 vendor 영향 0)            | redfish_dell_idrac10         | T-01 회귀 영향 0 |
| 12 | HPE / model=Gen11 / firmware=1.73 (T-01 핵심 회귀)          | redfish_hpe_ilo6             | T-01 fix 무영향 |

조건 #9 (현재 동작) 는 lab 도입 후 firmware_patterns 추가 시 (NEXT_ACTIONS) 정밀 분리 가능.
조건 #11 / #12 는 본 fix 가 HPE T-01 + Dell/Lenovo/Cisco 회귀에 영향 0 임을 확인.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "module_utils"))

from adapter_common import (  # noqa: E402
    adapter_matches,
    adapter_score,
    load_vendor_aliases,
)

ALIASES = load_vendor_aliases(str(REPO_ROOT / "common" / "vars" / "vendor_aliases.yml"))


def _load_adapters(channel: str = "redfish") -> list[dict]:
    """adapters/<channel>/*.yml 로드."""
    adapters = []
    for path in sorted((REPO_ROOT / "adapters" / channel).glob("*.yml")):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data["_filename"] = path.name
        adapters.append(data)
    return adapters


def _select_adapter(facts: dict) -> tuple[str, int]:
    """현재 facts 로 adapter_loader 시뮬레이션 → (adapter_id, score)."""
    adapters = _load_adapters("redfish")
    matched = []
    for adapter in adapters:
        if adapter_matches(adapter, facts, ALIASES):
            score = adapter_score(adapter, facts, ALIASES)
            if score > -9999:
                matched.append((score, adapter))
    if not matched:
        return ("(generic_fallback)", 0)
    matched.sort(key=lambda x: x[0], reverse=True)
    best_score, best_adapter = matched[0]
    return (best_adapter.get("adapter_id", best_adapter.get("_filename")), best_score)


@pytest.mark.parametrize(
    "case_id,facts,expected_adapter",
    [
        # X11 generation (AST2500)
        ("smc_x11_ast2500_3part", {"vendor": "Supermicro", "model": "X11DPi-NT", "firmware": "1.73.10"}, "redfish_supermicro_x11"),
        ("smc_h11_alias",          {"vendor": "Supermicro", "model": "H11SSL-i",  "firmware": "1.73"},    "redfish_supermicro_x11"),
        # X12 generation (AST2600) — DRIFT-015 fix 핵심 (priority 90 → 100)
        ("smc_x12_ast2600_3part", {"vendor": "Supermicro", "model": "X12SPL-F",  "firmware": "01.03.03"}, "redfish_supermicro_x12"),
        ("smc_h12_alias",          {"vendor": "Supermicro", "model": "H12DSi-N6", "firmware": "01.05.10"}, "redfish_supermicro_x12"),
        # X13 generation
        ("smc_x13_ast2600",       {"vendor": "Supermicro", "model": "X13SAE",    "firmware": "01.05.00"}, "redfish_supermicro_x13"),
        ("smc_b13_alias",          {"vendor": "Supermicro", "model": "B13DEE",    "firmware": "01.06.00"}, "redfish_supermicro_x13"),
        # X14 generation (AST2600 + Redfish 1.21.0)
        ("smc_x14_ast2600",       {"vendor": "Supermicro", "model": "X14DBT",    "firmware": "01.20.00"}, "redfish_supermicro_x14"),
        # ARS line (Altra/Cobalt) priority 80 vs X12 100 — X12 더 높음
        ("smc_x12_priority_over_ars", {"vendor": "Supermicro", "model": "X12SPL-F", "firmware": ""},      "redfish_supermicro_x12"),
        # T-01 시나리오 (model + firmware empty) — 현재 동작 검증
        ("smc_facts_empty_x14_priority", {"vendor": "Supermicro", "model": "", "firmware": ""},           "redfish_supermicro_x14"),
        # Generic fallback (Unknown model)
        ("smc_unknown_model",       {"vendor": "Supermicro", "model": "UnknownModel", "firmware": ""},   "redfish_supermicro_bmc"),
        # 타 vendor 영향 0 (T-01 회귀)
        ("dell_unaffected",         {"vendor": "Dell", "model": "", "firmware": ""},                     "redfish_dell_idrac10"),
        # HPE T-01 회귀 (probe_facts 시뮬레이션 — 사용자 실측 hint 채워진 케이스)
        ("hpe_t01_unaffected",      {"vendor": "HPE", "model": "ProLiant DL380 Gen11", "firmware": "1.73"}, "redfish_hpe_ilo6"),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_supermicro_adapter_selection(case_id: str, facts: dict, expected_adapter: str) -> None:
    """Supermicro X11~X14 adapter 선택 회귀 + DRIFT-015 fix 검증 + T-01/타 vendor 영향 0."""
    selected, score = _select_adapter(facts)
    assert selected == expected_adapter, (
        f"[{case_id}] facts={facts} → selected={selected} (score={score}), expected={expected_adapter}"
    )


def test_drift_015_x12_priority_consistency() -> None:
    """DRIFT-015 — X11/X12/X13 priority 모두 100 일관성. X14=110 > X11~X13=100 > generic=10."""
    adapters = {a["adapter_id"]: a for a in _load_adapters("redfish") if a.get("adapter_id", "").startswith("redfish_supermicro_")}

    assert adapters["redfish_supermicro_x11"]["priority"] == 100, "X11 priority 100 유지"
    assert adapters["redfish_supermicro_x12"]["priority"] == 100, "X12 priority 100 (DRIFT-015 fix — 이전 90 회귀 차단)"
    assert adapters["redfish_supermicro_x13"]["priority"] == 100, "X13 priority 100 유지"
    assert adapters["redfish_supermicro_x14"]["priority"] == 110, "X14 priority 110 유지 (최신 generation)"
    assert adapters["redfish_supermicro_bmc"]["priority"] == 10, "generic fallback priority 10 유지"
