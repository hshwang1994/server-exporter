"""Adapter 세대 식별 — 펌웨어 문자열의 세대 토큰은 단어 경계로만 맞는다 (2026-10-12).

재현한 결함:
  - `iLO.*6` 이 "iLO 5 v2.65" 에 맞았다('.*' 가 "5 v2." 를 건너 '6' 에 닿는다) → iLO 5 장비가 hpe_ilo6(priority 100) 으로 선택됐다.
  - `dell_idrac8` 의 `^3\\.` 가 iDRAC9 초기 펌웨어(3.x)를 가로챘다 (iDRAC8 은 2.x 만이다).
  - lenovo_xcc 의 glob 식(`USX*` 등)이 정규식으로 해석돼 "US" 가 든 어떤 문자열에도 맞았다.

고친 규칙: 세대 토큰은 `iLO\\s*6\\b` 처럼 단어 경계로, iDRAC8/9 의 주 버전 경계는 2.x / 3.x~7.x, glob 식은 접두 정규식(`^USX`).
기존에 맞게 선택되던 사례(T-01 · reselect · Supermicro 시험)는 그대로 통과해야 한다 — 그 시험들은 별도 파일에 있다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "module_utils"))

from adapter_common import adapter_matches, adapter_score, load_vendor_aliases  # noqa: E402

ALIASES = load_vendor_aliases(str(REPO_ROOT / "common" / "vars" / "vendor_aliases.yml"))


def _adapters():
    out = []
    for path in sorted((REPO_ROOT / "adapters" / "redfish").glob("*.yml")):
        d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        d["_filename"] = path.name
        out.append(d)
    return out


def _select(facts):
    matched = []
    for a in _adapters():
        if adapter_matches(a, facts, ALIASES):
            s = adapter_score(a, facts, ALIASES)
            if s > -9999:
                matched.append((s, a.get("adapter_id")))
    assert matched, facts
    matched.sort(reverse=True)
    return matched[0][1]


@pytest.mark.parametrize("facts,expected", [
    # 오탐 제거 — 세대 토큰이 있는 문자열은 그 세대로만
    ({"vendor": "HPE", "model": "ProLiant DL380 Gen10", "firmware": "iLO 5 v2.65"}, "redfish_hpe_ilo5"),
    ({"vendor": "Hewlett Packard Enterprise", "model": "ProLiant DL360 Gen10 Plus", "firmware": "iLO 5 v2.72"}, "redfish_hpe_ilo5"),
    ({"vendor": "HPE", "model": "ProLiant DL360 Gen9", "firmware": "iLO 4 v2.78"}, "redfish_hpe_ilo4"),
    ({"vendor": "HPE", "model": "ProLiant DL380 Gen11", "firmware": "iLO 6 v1.73"}, "redfish_hpe_ilo6"),
    # Dell — iDRAC9 초기 펌웨어 3.x 는 iDRAC9 다 (종전 idrac8 의 ^3\\. 가 가로챘다)
    ({"vendor": "Dell Inc.", "model": "PowerEdge R740", "firmware": "3.21.21.21"}, "redfish_dell_idrac9"),
    ({"vendor": "Dell Inc.", "model": "PowerEdge R730", "firmware": "2.86.86.86"}, "redfish_dell_idrac8"),
    ({"vendor": "Dell Inc.", "model": "PowerEdge R760", "firmware": "7.10.70.00"}, "redfish_dell_idrac9"),
    # Lenovo — XCC2 펌웨어에 숫자 3 이 있어도 XCC3 가 아니다; 접두 식은 접두에만
    ({"vendor": "Lenovo", "model": "ThinkSystem SR650 V3", "firmware": "XCC2 v3.10"}, "redfish_lenovo_xcc"),
    ({"vendor": "Lenovo", "model": "ThinkSystem SR650 V2", "firmware": "AFBT58B-5.70"}, "redfish_lenovo_xcc"),
    ({"vendor": "Lenovo", "model": "ThinkSystem SR650 V4", "firmware": "XCC3 1.20"}, "redfish_lenovo_xcc3"),
    ({"vendor": "Lenovo", "model": "System x3650 M5", "firmware": "IMM2 TCOO54D 1.50"}, "redfish_lenovo_imm2"),
])
def test_generation_token_selects_the_right_generation(facts, expected):
    assert _select(facts) == expected


@pytest.mark.parametrize("facts,expected", [
    # 종전에 맞게 선택되던 사례 — 바뀌지 않는다 (숫자만 있는 펌웨어는 model 과 함께 종전 규칙대로)
    ({"vendor": "HPE", "model": "ProLiant DL380 Gen11", "firmware": "1.73"}, "redfish_hpe_ilo6"),
    ({"vendor": "HPE", "model": "ProLiant DL380 Gen10", "firmware": "2.50"}, "redfish_hpe_ilo5"),
    ({"vendor": "HPE", "model": "ProLiant DL380 Gen12", "firmware": "1.12.00"}, "redfish_hpe_ilo7"),
    ({"vendor": "HPE", "model": "", "firmware": ""}, "redfish_hpe_ilo7"),
    ({"vendor": "Dell", "model": "", "firmware": ""}, "redfish_dell_idrac10"),
    ({"vendor": "Lenovo", "model": "", "firmware": ""}, "redfish_lenovo_xcc3"),
    ({"vendor": "Supermicro", "model": "X12SPL-F", "firmware": "01.03.03"}, "redfish_supermicro_x12"),
])
def test_existing_selections_are_unchanged(facts, expected):
    assert _select(facts) == expected


def test_generic_and_vendor_fallback_paths_still_exist():
    ids = {a.get("adapter_id"): a for a in _adapters()}
    assert ids["redfish_generic"].get("generic") is True and not ids["redfish_generic"].get("match")
    for fallback in ("redfish_hpe_ilo", "redfish_dell_idrac", "redfish_lenovo_bmc", "redfish_supermicro_bmc", "redfish_cisco_bmc"):
        assert ids[fallback]["priority"] == 10 and set(ids[fallback]["match"]) == {"vendor"}, fallback
    # vendor 만 알고 모델 · 펌웨어가 어느 세대 패턴에도 맞지 않으면 vendor fallback 으로 떨어진다 (지원 범위가 줄지 않았다)
    assert _select({"vendor": "HPE", "model": "ProLiant DL380 G7", "firmware": "iLO 3 v1.95"}) == "redfish_hpe_ilo"
    assert _select({"vendor": "Dell Inc.", "model": "PowerEdge R720", "firmware": "1.66.65"}) == "redfish_dell_idrac"


def test_patterns_do_not_use_glob_syntax():
    import re
    for a in _adapters():
        for key in ("firmware_patterns", "model_patterns"):
            for pat in (a.get("match") or {}).get(key, []) or []:
                re.compile(pat)
                assert not re.fullmatch(r"[A-Za-z0-9]+\*", pat), f"{a['_filename']}: glob 식 {pat!r}"
