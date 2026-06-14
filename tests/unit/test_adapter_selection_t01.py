"""
T-01 (cycle 2026-05-11) adapter selection 회귀 — HPE DL380 Gen11 (iLO 6) 가
hpe_ilo7 Gen12-only adapter 로 오선택되는 사고 차단.

본 테스트는 다음 시나리오 매트릭스를 검증:

| # | facts | expected adapter | 비고 |
|---|---|---|---|
| 1 | HPE / model=ProLiant DL380 Gen11 / firmware=1.73           | redfish_hpe_ilo6   | T-01 fix 핵심 |
| 2 | HPE / model=ProLiant DL380 Gen11 / firmware=iLO 6 v1.73    | redfish_hpe_ilo6   | manager_type 동시 |
| 3 | HPE / model=ProLiant DL380 Gen12 / firmware=1.12.00        | redfish_hpe_ilo7   | Gen12 회귀 |
| 4 | HPE / model=ProLiant DL380 Gen12 / firmware=1.16           | redfish_hpe_ilo7   | 2-part firmware (1387b505 회귀) |
| 5 | HPE / model='' / firmware=''                                | redfish_hpe_ilo7   | (현재 동작 — fallback 안 됐을 때) |
| 6 | HPE / model=ProLiant DL380 Gen10 / firmware=2.50           | redfish_hpe_ilo5   | iLO 5 회귀 |
| 7 | Dell / model='' / firmware=''                               | redfish_dell_idrac10 | priority 최상위 |
| 8 | Lenovo / model='' / firmware=''                             | redfish_lenovo_xcc3 | priority 최상위 |
| 9 | Cisco / model='UCS-X' / firmware=''                         | redfish_cisco_ucs_xseries | model 매치 |

조건 #5 (현재 동작) 가 통과해도 무방 — 본 fix 의 핵심은 #1/#2 (probe_facts 제공 시).
#3/#4 (Gen12) 와 #6/#7/#8/#9 (타 vendor) 는 영향 없음을 확인.
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
        # T-01 fix 핵심 — DL380 Gen11 + iLO 6
        ("hpe_gen11_ilo6_short", {"vendor": "HPE", "model": "ProLiant DL380 Gen11", "firmware": "1.73"}, "redfish_hpe_ilo6"),
        ("hpe_gen11_ilo6_full",  {"vendor": "HPE", "model": "ProLiant DL380 Gen11", "firmware": "iLO 6 v1.73"}, "redfish_hpe_ilo6"),
        # Gen12 회귀 (오선택 시도 검증 — 정상 매칭 유지)
        ("hpe_gen12_ilo7_3part", {"vendor": "HPE", "model": "ProLiant DL380 Gen12", "firmware": "1.12.00"}, "redfish_hpe_ilo7"),
        ("hpe_gen12_ilo7_2part", {"vendor": "HPE", "model": "ProLiant DL380 Gen12", "firmware": "1.16"}, "redfish_hpe_ilo7"),
        # iLO 5 (Gen10)
        ("hpe_gen10_ilo5",       {"vendor": "HPE", "model": "ProLiant DL380 Gen10", "firmware": "2.50"}, "redfish_hpe_ilo5"),
        # 타 vendor 영향 없음
        ("dell_empty",   {"vendor": "Dell", "model": "", "firmware": ""}, "redfish_dell_idrac10"),
        ("lenovo_empty", {"vendor": "Lenovo", "model": "", "firmware": ""}, "redfish_lenovo_xcc3"),
        ("cisco_ucsx",   {"vendor": "Cisco", "model": "UCS-X 9508", "firmware": ""}, "redfish_cisco_ucs_xseries"),
    ],
)
def test_adapter_selection_t01(case_id: str, facts: dict, expected_adapter: str) -> None:
    """probe_facts 로 정확한 adapter 선택 + 타 vendor 회귀 0."""
    selected, score = _select_adapter(facts)
    assert selected == expected_adapter, (
        f"case={case_id} facts={facts}\n"
        f"  expected: {expected_adapter}\n"
        f"  selected: {selected} (score={score})"
    )


def test_hpe_gen11_pre_fix_misselect() -> None:
    """현재 동작 검증 — facts empty 시 hpe_ilo7 가 잘못 선택됨 (T-01 사고 재현).

    본 테스트는 fix 의 **필요성** 증명 — empty facts 로는 hpe_ilo7 priority=120 가
    hpe_ilo6 priority=100 를 이김. probe_facts 가 model/firmware 채우면 hpe_ilo7
    의 model_patterns Gen12-only 가 disqualify 시켜 hpe_ilo6 선택 (위 test_adapter_selection_t01
    의 hpe_gen11_ilo6_* 케이스).
    """
    selected, _ = _select_adapter({"vendor": "HPE", "model": "", "firmware": ""})
    # 본 사고는 hpe_ilo7 priority 우선 — fix 후에도 facts empty 면 동일.
    # 정상 동작: detect_vendor.yml 의 probe_facts fallback 으로 facts 채워짐 → 위 매트릭스 통과.
    assert selected == "redfish_hpe_ilo7", (
        f"empty facts 일 때 priority 가장 높은 hpe_ilo7 선택 — 사고 재현 확인. selected={selected}"
    )
