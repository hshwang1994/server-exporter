"""adapter_common 점수 공식 집중 단위 테스트.

`adapter_score` 는 벤더 자동 감지의 핵심 계약:

    score = priority × 1000 + specificity × 10 + match_score

기존 test_adapter_selection_models.py / test_supermicro_adapter_selection.py 는 실 adapter
시나리오로 **선택 결과**를 검증하지만, 공식 자체의 불변(priority 우세 / 불일치 disqualify /
normalize_vendor 경계 / pattern fallback)은 직접 단위 커버가 없었다. 본 파일은 합성 입력으로
공식의 핵심 성질을 고정한다 (실 YAML 비결합 — 순수 함수).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "module_utils"))

from adapter_common import (  # noqa: E402
    adapter_match_score,
    adapter_score,
    adapter_specificity,
    normalize_vendor,
    pattern_match_any,
)

ALIASES = {"dell": "dell", "dell inc.": "dell", "hpe": "hpe",
           "hewlett packard enterprise": "hpe"}


# ── normalize_vendor ──────────────────────────────────────────────────────────

def test_normalize_vendor_exact_and_trailing_dot():
    # G7 회귀: 'Dell Inc.' (trailing dot) 정규화
    assert normalize_vendor("Dell Inc.", ALIASES) == "dell"
    assert normalize_vendor("DELL", ALIASES) == "dell"


def test_normalize_vendor_partial_match():
    # alias 가 v 에 포함되면 매칭 ('dell' in 'dell computers')
    assert normalize_vendor("Dell Computers", ALIASES) == "dell"


def test_normalize_vendor_unknown_returns_lowered():
    assert normalize_vendor("Acme Corp", ALIASES) == "acme corp"


def test_normalize_vendor_empty_and_no_aliases():
    assert normalize_vendor("", ALIASES) is None
    assert normalize_vendor(None) is None
    assert normalize_vendor("HPE", None) == "hpe"  # aliases 없으면 lower 만


# ── pattern_match_any ─────────────────────────────────────────────────────────

def test_pattern_match_any_regex_case_insensitive():
    assert pattern_match_any(["R7.*"], "PowerEdge R740") is True
    assert pattern_match_any(["dl380"], "ProLiant DL380 Gen11") is True


def test_pattern_match_any_no_match_and_empty():
    assert pattern_match_any(["R7.*"], "PowerEdge R640") is False
    assert pattern_match_any([], "anything") is False
    assert pattern_match_any(["x"], "") is False


def test_pattern_match_any_invalid_regex_falls_back_to_substring():
    # 잘못된 정규식은 re.error → 부분문자열 비교로 fallback
    assert pattern_match_any(["[unclosed"], "model [unclosed bracket") is True
    assert pattern_match_any(["[unclosed"], "no match") is False


# ── adapter_specificity ───────────────────────────────────────────────────────

def test_specificity_accumulates_conditions():
    assert adapter_specificity({"match": {}}) == 0
    assert adapter_specificity({"match": {"vendor": ["dell"]}}) == 10
    assert adapter_specificity(
        {"match": {"vendor": ["dell"], "model_patterns": ["R7.*"]}}
    ) == 30
    # vendor10 + model20 + firmware20 + version15 + distro15 + os5
    full = {"match": {"vendor": ["x"], "model_patterns": ["x"], "firmware_patterns": ["x"],
                      "version_patterns": ["x"], "distribution_patterns": ["x"], "os_type": "linux"}}
    assert adapter_specificity(full) == 85


def test_specificity_generic_penalty():
    assert adapter_specificity({"match": {}, "generic": True}) == -40
    assert adapter_specificity({"match": {"vendor": ["x"]}, "generic": True}) == -30


# ── adapter_match_score ───────────────────────────────────────────────────────

def test_match_score_vendor_bonus_and_mismatch():
    a = {"match": {"vendor": ["dell"]}}
    assert adapter_match_score(a, {"vendor": "Dell Inc."}, ALIASES) == 20
    # vendor 불일치 → disqualify
    assert adapter_match_score(a, {"vendor": "HPE"}, ALIASES) == -9999


def test_match_score_model_empty_skips_bonus_not_disqualify():
    a = {"match": {"vendor": ["dell"], "model_patterns": ["R7.*"]}}
    # model 정보 없음(빈 문자열) → 보너스만 제외, disqualify 아님 → vendor 20 만
    assert adapter_match_score(a, {"vendor": "Dell", "model": ""}, ALIASES) == 20
    # model 알려졌는데 불일치 → disqualify
    assert adapter_match_score(a, {"vendor": "Dell", "model": "PowerEdge R640"}, ALIASES) == -9999
    # model 일치 → vendor20 + model25
    assert adapter_match_score(a, {"vendor": "Dell", "model": "PowerEdge R740"}, ALIASES) == 45


def test_match_score_no_conditions_zero():
    assert adapter_match_score({"match": {}}, {"vendor": "anything"}, ALIASES) == 0


# ── adapter_score (전체 공식) ─────────────────────────────────────────────────

def test_score_formula_components():
    a = {"priority": 100, "match": {"vendor": ["dell"]}}
    # priority100*1000 + specificity(vendor=10)*10 + match(vendor=20)
    assert adapter_score(a, {"vendor": "Dell"}, ALIASES) == 100 * 1000 + 10 * 10 + 20


def test_score_priority_dominates_specificity():
    """높은 priority 가 낮은 priority+높은 specificity 를 이긴다."""
    high = {"priority": 100, "match": {"vendor": ["dell"]}}
    low_specific = {"priority": 50, "match": {
        "vendor": ["dell"], "model_patterns": ["R7.*"], "firmware_patterns": [r"5\..*"]}}
    facts = {"vendor": "Dell", "model": "PowerEdge R740", "firmware": "5.10"}
    s_high = adapter_score(high, {"vendor": "Dell"}, ALIASES)        # 100120
    s_low = adapter_score(low_specific, facts, ALIASES)              # 50000+500+70=50570
    assert s_high > s_low


def test_score_specificity_breaks_priority_tie():
    """같은 priority → specificity 높은 쪽 우세."""
    generic = {"priority": 50, "match": {"vendor": ["dell"]}}
    specific = {"priority": 50, "match": {"vendor": ["dell"], "model_patterns": ["R7.*"]}}
    facts = {"vendor": "Dell", "model": "PowerEdge R740"}
    assert adapter_score(specific, facts, ALIASES) > adapter_score(generic, facts, ALIASES)


def test_score_mismatch_disqualifies_regardless_of_priority():
    """불일치는 priority 가 아무리 높아도 -9999 (generic fallback 으로 밀려남)."""
    high_but_wrong = {"priority": 999, "match": {"vendor": ["dell"]}}
    assert adapter_score(high_but_wrong, {"vendor": "HPE"}, ALIASES) == -9999
