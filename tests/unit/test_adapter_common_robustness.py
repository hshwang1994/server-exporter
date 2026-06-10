"""adapter_common fault-injection 회귀.

배경: adapter 선택은 벤더 자동 감지의 핵심. probe_facts(외부 BMC ServiceRoot 유래)나
내부 adapter YAML 의 오염 값이 loader 전체를 죽이거나 잘못된 매칭을 유발할 수 있다.
confirmed:
  - #4 normalize_vendor: 비-str vendor(BMC Manufacturer=숫자) → .strip() AttributeError
  - #3 pattern_match_any: 비-str pattern → re.search/.lower() crash
  - #5 adapter_score: priority='high' → int() ValueError (loader 전체 실패)
  - #18 adapter_matches: distribution/version_patterns 있는데 facts 빈 값 → 무조건 disqualify
    (model/firmware 는 빈 값 통과인데 distro/version 만 불일치 — 일관성 위반)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "module_utils"))

from adapter_common import (  # noqa: E402
    adapter_match_score,
    adapter_matches,
    adapter_score,
    adapter_specificity,
    normalize_vendor,
    pattern_match_any,
)


# #4 — normalize_vendor 비-str
def test_normalize_vendor_non_str_does_not_crash():
    """BMC Manufacturer 가 숫자(JSON 오염) → .strip() AttributeError 방어."""
    assert normalize_vendor(12345) is not None  # 가드 전: AttributeError
    assert normalize_vendor(["Dell"]) is not None
    # 정상 입력 불변
    assert normalize_vendor("Dell Inc.", {"dell inc.": "dell"}) == "dell"


# #3 — pattern_match_any 비-str pattern
def test_pattern_match_any_non_str_pattern_does_not_crash():
    """adapter YAML model_patterns 에 비-str 원소 → re.search/.lower() crash 방어."""
    assert pattern_match_any([123, None, "PowerEdge"], "PowerEdge R760") is True  # 가드 전: crash
    assert pattern_match_any([123, None], "PowerEdge R760") is False
    # 정상 입력 불변
    assert pattern_match_any(["R7[0-9]0"], "PowerEdge R760") is True


# #5 — adapter_score priority 비-숫자
def test_adapter_score_non_numeric_priority_does_not_crash():
    """adapter YAML priority='high'/'1.5' → int() ValueError 로 loader 전체 죽던 것 방어."""
    s = adapter_score({"priority": "high", "match": {}}, {"vendor": "dell"})  # 가드 전: ValueError
    assert isinstance(s, int)
    # 정상 int priority 불변 (generic match, priority=10 → 10*1000)
    assert adapter_score({"priority": 10, "match": {}}, {"vendor": "dell"}) == 10 * 1000


# #18 — adapter_matches distro/version 빈 값 일관성
def test_adapter_matches_empty_distro_passes_like_model():
    """distribution_patterns 있고 facts.distribution='' → model/firmware 처럼 통과해야 함."""
    adapter = {"match": {"distribution_patterns": ["rhel.*"]}}
    # 빈 distribution = 정보 없음 → disqualify 아님 (model/firmware 와 동일 정책)
    assert adapter_matches(adapter, {"distribution": ""}) is True  # 가드 전: False
    # 정보 있는데 불일치하면 여전히 disqualify
    assert adapter_matches(adapter, {"distribution": "ubuntu"}) is False
    # 일치하면 통과
    assert adapter_matches(adapter, {"distribution": "rhel9"}) is True


def test_adapter_matches_empty_version_passes_like_model():
    adapter = {"match": {"version_patterns": ["9\\..*"]}}
    assert adapter_matches(adapter, {"version": ""}) is True  # 가드 전: False
    assert adapter_matches(adapter, {"version": "8.10"}) is False


# Round 9 #2 — whitespace-only vendor → None (empty-string substring 오탐 방지)
def test_normalize_vendor_whitespace_only_returns_none():
    assert normalize_vendor("   ") is None  # 가드 전: '' 가 모든 alias 에 substring 매칭
    assert normalize_vendor("\t\n ") is None
    assert normalize_vendor("Dell Inc.", {"dell inc.": "dell"}) == "dell"  # 정상 불변


# Round 12 — adapter_common string-method/scalar sweep
def test_adapter_matches_non_str_os_type():
    """os_type 가 비-str(int) → os_type.lower() AttributeError 방어."""
    adapter = {"match": {"os_type": 123}}
    assert adapter_matches(adapter, {"detected_os": "linux"}) in (True, False)  # 가드 전: int.lower


def test_adapter_matches_scalar_vendor():
    """vendor 가 scalar str(YAML 오타) → char 순회 방지."""
    adapter = {"match": {"vendor": "dell"}}  # list 아님
    assert adapter_matches(adapter, {"vendor": "Dell Inc."}, {"dell inc.": "dell", "dell": "dell"}) is True


def test_pattern_match_any_scalar_pattern():
    """patterns 가 scalar str → 단일 패턴으로 처리(char 순회 아님)."""
    assert pattern_match_any("R7[0-9]0", "PowerEdge R760") is True  # 가드 전: 'R'/'7'/'[' char 순회
    assert pattern_match_any("Xyz", "PowerEdge R760") is False


# Round 16 — 빈 'match:'(YAML null) → match=None 시 .get() AttributeError 로 lookup 전체 abort 방어
def test_null_match_does_not_crash_scoring():
    """adapter YAML 에 'match:' 만 쓰고 본문 누락 시 yaml.safe_load → {'match': None}.
    adapter_specificity / adapter_match_score 가 None.get() AttributeError 로 죽으면
    adapter_loader._match_and_score 가 매칭된 정상 adapter 까지 버리고 전체 gather 실패."""
    broken = {"match": None, "priority": 50, "adapter_id": "broken"}
    facts = {"vendor": "dell", "model": "PowerEdge R760"}
    # 셋 다 crash 없이 — generic(match 없음) 과 동일 취급
    assert adapter_matches(broken, facts) is True  # 가드 전: (specificity 경유 아님) — matches 는 본래 OK
    assert adapter_specificity(broken) == 0       # 가드 전: AttributeError
    assert adapter_match_score(broken, facts) == 0  # 가드 전: AttributeError
    assert adapter_score(broken, facts) == 50 * 1000  # priority 만 반영
    # 정상 adapter 점수 불변 (회귀 방어)
    good = {"match": {"vendor": ["dell"], "model_patterns": ["PowerEdge R7.*"]}, "priority": 100}
    assert adapter_score(good, facts) == 100 * 1000 + 30 * 10 + 45  # priority + spec(10+20) + match(20+25)


# Round 17 #1 — 비-dict match(list/scalar YAML 오타) → match=[...]/str/int 이면 'or {}' 가
# truthy 라 그대로 통과 → 다음 줄 match.get() AttributeError 로 lookup 전체 abort 방어
@pytest.mark.parametrize("bad_match", [
    [{"vendor": "dell"}],   # list (들여쓰기 오타: 'match:\n  - vendor: dell')
    "dell",                 # scalar str
    5,                      # scalar int
    ("x",),                 # tuple
])
def test_non_dict_match_does_not_crash_scoring(bad_match):
    facts = {"vendor": "dell", "model": "PowerEdge R760"}
    a = {"match": bad_match, "priority": 50, "adapter_id": "broken"}
    # 비-dict match 는 {} 로 강제 → generic(조건 없음) 과 동일 취급, crash 없음
    assert adapter_matches(a, facts) is True       # 가드 전: 'list/str/int' object has no attribute 'get'
    assert adapter_specificity(a) == 0             # 가드 전: AttributeError
    assert adapter_match_score(a, facts) == 0      # 가드 전: AttributeError
    assert adapter_score(a, facts) == 50 * 1000    # priority 만 반영


# Round 17 #5 — normalize_vendor substring fallback 오탐 차단
# (짧은 alias 'hp' 가 'HPC Systems' 를 hpe 로 / 역방향 'Computer' 가 'Super Micro Computer' 로)
_R17_ALIASES = {
    "dell": ["Dell", "Dell Inc.", "Dell EMC"],
    "hpe": ["HPE", "Hewlett Packard Enterprise", "HP Enterprise", "HP", "Hp"],
    "lenovo": ["Lenovo", "IBM"],
    "supermicro": ["Supermicro", "Super Micro Computer", "SMCI"],
    "cisco": ["Cisco Systems", "Cisco"],
    "quanta": ["Quanta Computer", "QCT"],
}


def test_normalize_vendor_short_alias_no_false_positive():
    """'HPC Systems Inc.' 는 2-char 'hp' substring 으로 hpe 오분류되면 안 됨 → unknown(raw) 으로 수렴."""
    out = normalize_vendor("HPC Systems Inc.", _R17_ALIASES)
    assert out != "hpe"                 # 가드 전: 'hp' in 'hpc...' → hpe
    assert out == "hpc systems inc."    # 미매칭 → raw(소문자) 패스스루


def test_normalize_vendor_short_alias_whole_word_preserved():
    """'HP rackmount server' 의 'hp' 는 whole-word 토큰 → hpe 보존 (회귀 방어)."""
    assert normalize_vendor("HP rackmount server", _R17_ALIASES) == "hpe"


def test_normalize_vendor_reverse_direction_removed():
    """역방향(v in alias) 제거: 'Computer' 단독이 'Super Micro Computer'/'Quanta Computer' 로 오분류 안 됨."""
    out = normalize_vendor("Computer", _R17_ALIASES)
    assert out not in ("supermicro", "quanta")
    assert out == "computer"


def test_normalize_vendor_legit_substring_preserved():
    """정상 substring 수렴 불변 (forward, len>=3)."""
    assert normalize_vendor("Dell Inc", _R17_ALIASES) == "dell"            # 마침표 없음
    assert normalize_vendor("Super Micro Computer X11", _R17_ALIASES) == "supermicro"
    assert normalize_vendor("Hewlett Packard Enterprise Co", _R17_ALIASES) == "hpe"
    # 정확/토큰 매칭 불변
    assert normalize_vendor("HP Enterprise", _R17_ALIASES) == "hpe"        # 정확 alias
    assert normalize_vendor("HP", _R17_ALIASES) == "hpe"                   # 정확 alias(2-char)
