"""Redfish 2단계 adapter 선택 — 계약 고정.

배경. adapter 를 고르는 시점(`redfish-gather/site.yml`)이 **무인증 probe** 직후라
`model` / `firmware` fact 가 비어 있었다. 빈 fact 는 실격이 아니라 중립이라
(`adapter_common.adapter_match_score`) 결국 `priority` 최상위가 독식했다.
실장비에서 R760(iDRAC9 / FW 7.10.70.00)이 `redfish_dell_idrac10` 을,
TA-UNODE-G1(CIMC 4.1)이 `redfish_cisco_ucs_xseries` 를 골랐다.

같은 버그를 ESXi 는 "선택을 facts 확보 뒤로 옮겨서" 고쳤다
(`esxi-gather/site.yml`, Round 17 #9). Redfish 는 `manager_layout` 을 수집 **전에**
알아야 해서 통째로 옮기지 못하고 2단계가 됐다.

- 1차: 무인증 facts. `manager_layout` 과 수집 경로가 쓴다. **바꾸지 않는다.**
- 2차: 수집 뒤 장비가 준 model/firmware 로 다시 고른다. `meta.adapter_id`,
  `diagnosis.details.adapter_candidate`, 계정 Family hint 가 이 값을 쓴다.

이 파일이 고정하는 것은 "2차 facts 면 정답이 나온다" 와 "facts 가 비면 1차를
유지한다" 두 가지다. 1차 동작 자체는 `test_adapter_selection_t01.py` 가 따로 잡는다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "module_utils"))

from adapter_common import (  # noqa: E402
    adapter_matches,
    adapter_score,
    load_vendor_aliases,
)

ALIASES = load_vendor_aliases(str(REPO / "common" / "vars" / "vendor_aliases.yml"))
SITE = REPO / "redfish-gather" / "site.yml"


def _select(facts: dict) -> str:
    matched = []
    for path in sorted((REPO / "adapters" / "redfish").glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if adapter_matches(data, facts, ALIASES):
            sc = adapter_score(data, facts, ALIASES)
            if sc > -9999:
                matched.append((sc, data.get("adapter_id", path.name)))
    if not matched:
        return "(none)"
    matched.sort(key=lambda x: x[0], reverse=True)
    return matched[0][1]


# ── 인증 후 facts 면 정답이 나온다 (실장비 실측값 기준) ───────────────────────
@pytest.mark.parametrize("facts,expected,why", [
    ({"vendor": "Dell", "model": "PowerEdge R760", "firmware": "7.10.70.00"},
     "redfish_dell_idrac9", "lab 10.100.15.34 / .27 — FW 7.x 는 iDRAC9"),
    ({"vendor": "Dell", "model": "PowerEdge R760", "firmware": ""},
     "redfish_dell_idrac9", "model 만 있어도 idrac10 의 R4xx/R6xx/R7xx 패턴에서 실격"),
    ({"vendor": "Cisco Systems Inc.", "model": "TA-UNODE-G1", "firmware": "4.1(2g)"},
     "redfish_cisco_cimc", "lab 10.100.15.2 — cisco_cimc 가 TA-UNODE.* 를 갖고 있다"),
    ({"vendor": "HPE", "model": "ProLiant DL380 Gen11", "firmware": "1.73"},
     "redfish_hpe_ilo6", "lab 10.50.11.231 — iLO6"),
])
def test_postauth_facts_select_correct_adapter(facts, expected, why):
    assert _select(facts) == expected, why


# ── 빈 facts 는 1차 동작 그대로 (2차가 서지 않는 상황) ────────────────────────
@pytest.mark.parametrize("vendor,expected", [
    ("Dell", "redfish_dell_idrac10"),
    ("Cisco Systems Inc.", "redfish_cisco_ucs_xseries"),
    ("Lenovo", "redfish_lenovo_xcc3"),
    ("HPE", "redfish_hpe_ilo7"),
])
def test_empty_facts_unchanged(vendor, expected):
    """1차 선택은 손대지 않았다 — 빈 facts 결과가 그대로여야 한다.

    표준 수집이 실패하면(=계정 복구가 도는 상황) `_rf_raw_collect.data` 가 비어
    2차가 서지 않는다. 그때 동작이 종전과 같아야 한다는 게 이 테스트의 뜻이다.
    """
    assert _select({"vendor": vendor, "model": "", "firmware": ""}) == expected


# ── site.yml 배선 ─────────────────────────────────────────────────────────────
def _site_text() -> str:
    return SITE.read_text(encoding="utf-8")


RESELECT = REPO / "redfish-gather" / "tasks" / "reselect_adapter.yml"


def test_reselect_task_exists():
    assert RESELECT.is_file(), "재선택 태스크 파일이 없다"
    t = RESELECT.read_text(encoding="utf-8")
    assert "_rf_postauth_facts" in t, "인증 후 facts 조립이 없다"
    assert "adapter_loader" in t, "재선택 lookup 이 없다"


def test_reselect_called_after_first_collect_and_before_account_service():
    """1회차 — 수집 **뒤**여야 model/firmware 가 있고, `account_service` **앞**이어야
    계정 Family hint 가 고쳐진 adapter 를 받는다."""
    t = _site_text()
    i_collect = t.index('- name: "redfish | collect standard"')
    i_resel = t.index('- name: "redfish | reselect adapter (1차 수집 후)"')
    i_acct = t.index('- name: "redfish | account_service (recovery → standard)"')
    assert i_collect < i_resel < i_acct


def test_reselect_called_again_after_recovery_recollect():
    """2회차 — 이게 없으면 비밀번호 회전 직후 adapter_id 가 1차 값으로 남는다.

    표준 계정이 어긋나 있으면 1차 수집이 401 로 실패해 1회차 재선택이 서지 않는다.
    복구가 계정을 고친 뒤 재수집이 성공하므로 그때 다시 불러야 한다.
    2026-08-13 회전 실측에서 Dell 4대가 `redfish_dell_idrac10` 로 남아 드러난 구멍이다.
    """
    t = _site_text()
    i_recollect = t.index('- name: "redfish | re-collect with standard account (after recovery)"')
    i_resel2 = t.index('- name: "redfish | reselect adapter (복구 후 재수집 뒤)"')
    i_norm = t.index('- name: "redfish | normalize standard"')
    assert i_recollect < i_resel2 < i_norm, "2회차 재선택이 재수집 뒤 / normalize 앞에 없다"


def test_first_pass_record_survives_second_call():
    """재선택이 두 번 불려도 `_rf_adapter_first_pass` 는 최초 1차 값을 유지해야 한다."""
    t = RESELECT.read_text(encoding="utf-8")
    assert "_rf_adapter_first_pass is not defined" in t, \
        "두 번째 호출이 1차 기록을 덮어쓴다 — 추적값이 무의미해진다"


def test_first_pass_selection_untouched():
    """1차 선택은 여전히 `_rf_probe_facts` 로 한다 — 여기가 바뀌면 수집이 흔들린다."""
    t = _site_text()
    first = t.index('- name: "redfish | select adapter"')
    block = t[first:first + 400]
    assert "facts=_rf_probe_facts" in block, "1차가 probe facts 를 안 쓴다"


def test_reselect_is_guarded_by_nonempty_facts():
    """model/firmware 가 둘 다 비면 재선택하지 않는다.

    이 가드가 없으면 수집 실패 상황에서 빈 facts 로 다시 고르게 되고, 1차와
    똑같은 버그(priority 독식)가 재선택 자리에서 재현된다.
    """
    t = RESELECT.read_text(encoding="utf-8")
    i = t.index('- name: "redfish | reselect | adapter 다시 고르기"')
    body = t[i:i + 500]
    assert "when:" in body, "재선택 태스크에 when 가드가 없다"
    guard = body[body.index("when:"):body.index("ansible.builtin.set_fact")]
    assert "_rf_postauth_facts.model" in guard and "_rf_postauth_facts.firmware" in guard, \
        "빈 facts 로 재선택하면 1차와 같은 버그가 재현된다"


def test_manager_layout_still_from_first_pass():
    """`manager_layout` 은 수집 전에 필요하다 — 1차 선택 뒤에서 뽑아야 한다."""
    t = _site_text()
    i_layout = t.index("_rf_adapter_manager_layout")
    i_collect = t.index('- name: "redfish | collect standard"')
    assert i_layout < i_collect, "manager_layout 추출이 수집보다 뒤로 갔다 — 멀티노드가 죽는다"


def test_no_jinja_comment_inside_diagnosis_expression():
    """`_diagnosis` 는 통짜 Jinja 표현식이라 `#` 이 주석이 아니다.

    2026-08-13 에 여기에 `#` 주석을 넣었다가 `unexpected char '#'` 로 전 섹션이
    failed 가 됐다. 같은 실수를 막는다.
    """
    t = _site_text()
    # 값 블록은 다음 8칸 들여쓰기 줄(주석이든 태스크든)에서 끝난다.
    m = re.search(r"_diagnosis:\s*>-\n(.*?)(?=\n {8}(?:#|- ))", t, re.S)
    assert m, "_diagnosis set_fact 를 못 찾았다"
    for ln in m.group(1).splitlines():
        assert "#" not in ln, f"Jinja 표현식 안에 '#' 이 있다: {ln.strip()[:70]}"
