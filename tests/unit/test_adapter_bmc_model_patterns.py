"""adapter `match.bmc_model_patterns` — Manager.Model 로 세대를 적는 벤더의 재선택 (2026-10-27, 01-adapter-001 HIGH).

재현한 결함(2026-10-26 분석 Round · Tier 1 before 18 label): Lenovo XCC3 5대가 1차 선택에서는 `redfish_lenovo_xcc3`(priority) 였다가
인증 후 재선택에서 `redfish_lenovo_bmc`(vendor 전용 fallback) 로 강등됐다. `lenovo_xcc3.yml` 의 `firmware_patterns: ["XCC\\s*3\\b"]` 가
실 펌웨어 문자열(`IHX438R 2.97 20260910` · `IHX414J 1.22 20250402`)에 없는 토큰이라 "알려진 값 불일치 = 실격" 이 됐고, `lenovo_xcc` 도
같은 이유로 실격해 fallback 만 남았다. Lenovo 가 세대를 적는 자리는 `Manager.Model`("Lenovo XClarity Controller 3") 이다.

고친 규칙(공통 로더, opt-in): adapter 가 `match.bmc_model_patterns` 를 선언했을 때만 facts `bmc_model`(= 모듈 `data.bmc.model` ← `Manager.Model`)
을 평가한다. 의미는 `model_patterns` 와 같다 — 비어 있으면 중립, 일치 +25(specificity +20), 알려진 값 불일치는 실격.
선언하지 않은 adapter 는 코드 경로가 바뀌지 않아 점수가 같다(이 파일이 31 adapter × facts 묶음으로 증명).
기대값은 전부 손으로 적었다(코드 출력 스냅샷 아님). facts 값은 2차 Mock 11대 + 1차 7대 Tier 1/2 기준선(2026-10-27)의 모듈 산출이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "module_utils"))

from adapter_common import adapter_match_score, adapter_matches, adapter_score, adapter_specificity, load_vendor_aliases  # noqa: E402

ALIASES = load_vendor_aliases(str(REPO / "common" / "vars" / "vendor_aliases.yml"))
ADAPTER_DIR = REPO / "adapters" / "redfish"

# 인증 후 facts (모듈 산출: vendor · data.system.model · data.bmc.firmware_version · data.bmc.model) — 2026-10-27 Tier 2 before 18 label.
XCC3_FW_2ND = "IHX438R 2.97 20260910"
XCC3_FW_1ST = "IHX414J 1.22 20250402"
LABEL_FACTS = {
    "csus3200_01": {"vendor": "hpe", "model": "Compute Scale-up Server 3200", "firmware": "1.77.30-20260911_061319",
                    "bmc_model": "Compute Scale-up Server 3200, 4S XNC Base Chassis"},
    "csus3200_02": {"vendor": "hpe", "model": "Compute Scale-up Server 3200", "firmware": "1.77.30-20260911_061319",
                    "bmc_model": "Compute Scale-up Server 3200, 4S XNC Base Chassis"},
    "csus3200_03": {"vendor": "hpe", "model": "Compute Scale-up Server 3200", "firmware": "1.77.30-20260911_061319",
                    "bmc_model": "Compute Scale-up Server 3200, 4S XNC Base Chassis"},
    "dl380_gen12_01": {"vendor": "hpe", "model": "HPE ProLiant Compute DL380 Gen12", "firmware": "1.24.00 Aug 01 2026", "bmc_model": "iLO 7"},
    "dl380_gen12_02": {"vendor": "hpe", "model": "HPE ProLiant Compute DL380 Gen12", "firmware": "1.24.00 Aug 01 2026", "bmc_model": "iLO 7"},
    "dl380_gen12_03": {"vendor": "hpe", "model": "HPE ProLiant Compute DL380 Gen12", "firmware": "1.24.00 Aug 01 2026", "bmc_model": "iLO 7"},
    "dl380_gen12_04": {"vendor": "hpe", "model": "HPE ProLiant Compute DL380 Gen12", "firmware": "1.24.00 Aug 01 2026", "bmc_model": "iLO 7"},
    "sr650_v4_01": {"vendor": "lenovo", "model": "ThinkSystem SR650 V4", "firmware": XCC3_FW_2ND, "bmc_model": "Lenovo XClarity Controller 3"},
    "sr650_v4_02": {"vendor": "lenovo", "model": "ThinkSystem SR650 V4", "firmware": XCC3_FW_2ND, "bmc_model": "Lenovo XClarity Controller 3"},
    "sr650_v4_03": {"vendor": "lenovo", "model": "ThinkSystem SR650 V4", "firmware": XCC3_FW_2ND, "bmc_model": "Lenovo XClarity Controller 3"},
    "sr650_v4_04": {"vendor": "lenovo", "model": "ThinkSystem SR650 V4", "firmware": XCC3_FW_2ND, "bmc_model": "Lenovo XClarity Controller 3"},
    "r1_DELL_R740_01": {"vendor": "dell", "model": "PowerEdge R740", "firmware": "7.00.00.184", "bmc_model": "14G Monolithic"},
    "r1_HPE_CSUS3200_01": {"vendor": "hpe", "model": "Compute Scale-up Server 3200", "firmware": "1.75.108-20260408_164726",
                           "bmc_model": "Compute Scale-up Server 3200, 4S XNC Base Chassis"},
    "r1_HPE_CSUS3200_02": {"vendor": "hpe", "model": "Compute Scale-up Server 3200", "firmware": "1.75.108-20260408_164726",
                           "bmc_model": "Compute Scale-up Server 3200, 4S XNC Base Chassis"},
    "r1_HPE_CSUS3200_03": {"vendor": "hpe", "model": "Compute Scale-up Server 3200", "firmware": "1.75.108-20260408_164726",
                           "bmc_model": "Compute Scale-up Server 3200, 4S XNC Base Chassis"},
    "r1_HPE_CSUS3200_04": {"vendor": "hpe", "model": "Compute Scale-up Server 3200", "firmware": "1.75.108-20260408_164726",
                           "bmc_model": "Compute Scale-up Server 3200, 4S XNC Base Chassis"},
    "r1_HPE_DL380_01": {"vendor": "hpe", "model": "HPE ProLiant Compute DL380 Gen12", "firmware": "1.20.00 Feb 12 2026", "bmc_model": "iLO 7"},
    # 1차 SR650 V4 는 Manager.Model 의 표기가 다르다 (Xclarity — 소문자 c). IGNORECASE 로 같은 세대다.
    "r1_Lenovo_SR650_01": {"vendor": "lenovo", "model": "ThinkSystem SR650 V4", "firmware": XCC3_FW_1ST, "bmc_model": "Lenovo Xclarity Controller 3"},
}
EXPECTED = {
    **{k: "redfish_hpe_csus_3200" for k in LABEL_FACTS if "CSUS" in k.upper()},
    **{k: "redfish_hpe_ilo7" for k in LABEL_FACTS if "DL380" in k.upper()},
    "r1_DELL_R740_01": "redfish_dell_idrac9",
    **{k: "redfish_lenovo_xcc3" for k in LABEL_FACTS if "SR650" in k.upper()},
}
# 참조 XCC(1세대, ThinkSystem V2) — tests/fixtures/redfish/lenovo/{system,manager}.json 실측값
REF_XCC_V2 = {"vendor": "lenovo", "model": "ThinkSystem SR650 V2", "firmware": "AFBT58B 5.70 2025-08-11", "bmc_model": "Lenovo XClarity Controller"}


def _adapters():
    out = []
    for path in sorted(ADAPTER_DIR.glob("*.yml")):
        d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        d["_filename"] = path.name
        out.append(d)
    assert len(out) >= 20, "adapters/redfish 가 비었다"
    return out


def _ranked(facts):
    ranked = []
    for a in _adapters():
        if adapter_matches(a, facts, ALIASES):
            s = adapter_score(a, facts, ALIASES)
            if s > -9999:
                ranked.append((s, a.get("adapter_id")))
    assert ranked, facts
    return sorted(ranked, reverse=True)


def _select(facts):
    return _ranked(facts)[0][1]


def _by_id(adapter_id):
    return next(a for a in _adapters() if a.get("adapter_id") == adapter_id)


# ── 1. 18 label 재선택 고정 ────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label", sorted(LABEL_FACTS))
def test_post_auth_reselection_for_all_18_labels(label):
    assert _select(LABEL_FACTS[label]) == EXPECTED[label]


def test_lenovo_xcc3_score_breakdown_on_real_facts():
    """SR650 V4 실 facts: xcc3 = 120×1000 + (vendor 10 + model 20 + bmc_model 20)×10 + (20 + 25 + 25) = 120570."""
    a = _by_id("redfish_lenovo_xcc3")
    facts = LABEL_FACTS["sr650_v4_01"]
    assert adapter_specificity(a) == 50
    assert adapter_match_score(a, facts, ALIASES) == 70
    assert adapter_score(a, facts, ALIASES) == 120570
    # lenovo_xcc 는 자체 firmware_patterns(XCC / ^AFBT / ^TAOT / ^USX) 가 IHX… 에 맞지 않아 종전처럼 실격, lenovo_bmc 는 10120 으로 뒤
    ranked = dict((aid, s) for s, aid in _ranked(facts))
    assert "redfish_lenovo_xcc" not in ranked
    assert ranked["redfish_lenovo_bmc"] == 10120


def test_lenovo_xcc3_no_longer_declares_the_absent_firmware_token():
    """실격 원인이던 `XCC\\s*3\\b` 는 5대 어느 FirmwareVersion 에도 없다 — 선언을 지웠다(이력은 adapter origin 주석에)."""
    a = _by_id("redfish_lenovo_xcc3")
    assert "firmware_patterns" not in (a.get("match") or {})
    assert a["match"]["bmc_model_patterns"] == ["XClarity Controller 3\\b"]
    assert "ThinkSystem.*V4" in a["match"]["model_patterns"]


# ── 2. 참조 XCC(1세대) 음성 · 1차 선택 불변 ───────────────────────────────────────────────────────────────────────────────

def test_reference_xcc_v2_still_selects_lenovo_xcc():
    assert _select(REF_XCC_V2) == "redfish_lenovo_xcc"


def test_bmc_model_alone_rejects_xcc3_for_a_non_v4_bmc_when_system_model_is_empty():
    """system model 이 비어 있어도 Manager.Model 이 'XClarity Controller'(3 없음) 이면 xcc3 는 실격 — fallback 은 종전과 같다."""
    facts = dict(REF_XCC_V2, model="")
    assert not adapter_matches(_by_id("redfish_lenovo_xcc3"), facts, ALIASES)
    assert _select(facts) == "redfish_lenovo_xcc"


def test_first_pass_with_empty_facts_is_unchanged():
    """무인증 1차 facts(전부 빈 값)는 priority 로 xcc3 — bmc_model 도 비어 있어 중립."""
    assert _select({"vendor": "Lenovo", "model": "", "firmware": "", "bmc_model": ""}) == "redfish_lenovo_xcc3"
    assert _select({"vendor": "Lenovo", "model": "", "firmware": ""}) == "redfish_lenovo_xcc3"


# ── 3. 선언 adapter 의 3분기 ───────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bmc_model,matches,bonus", [
    ("", True, 0),                                   # 정보 없음 → 중립
    ("Lenovo XClarity Controller 3", True, 25),      # 일치
    ("Lenovo Xclarity Controller 3", True, 25),      # 대소문자 무시
    ("Lenovo XClarity Controller", False, None),     # 알려진 값 불일치 → 실격
    ("Lenovo XClarity Controller 2", False, None),
])
def test_declared_adapter_three_branches(bmc_model, matches, bonus):
    a = _by_id("redfish_lenovo_xcc3")
    facts = {"vendor": "Lenovo", "model": "", "firmware": "", "bmc_model": bmc_model}
    assert adapter_matches(a, facts, ALIASES) is matches
    if matches:
        assert adapter_match_score(a, facts, ALIASES) == 20 + bonus
    else:
        assert adapter_match_score(a, facts, ALIASES) == -9999


# ── 4. 선언하지 않은 adapter 는 bmc_model 에 무감하다 (다른 제조사 선택 변화 0 의 증명) ────────────────────────────────────────

def _legacy_specificity(adapter):
    """2026-10-27 이전 adapter_specificity 공식 그대로 (bmc_model_patterns 항 없음)."""
    match = adapter.get("match")
    if not isinstance(match, dict):
        match = {}
    score = 0
    if match.get("vendor"):
        score += 10
    if match.get("model_patterns"):
        score += 20
    if match.get("firmware_patterns"):
        score += 20
    if match.get("version_patterns"):
        score += 15
    if match.get("distribution_patterns"):
        score += 15
    if match.get("os_type"):
        score += 5
    if adapter.get("generic", False):
        score -= 40
    return score


FACTS_CORPUS = [dict(v) for v in LABEL_FACTS.values()] + [REF_XCC_V2] + [
    {"vendor": v, "model": "", "firmware": "", "bmc_model": ""} for v in ("HPE", "Dell", "Lenovo", "Supermicro", "Cisco", "Huawei", "Inspur", "Fujitsu", "Quanta", "unknown")
] + [
    {"vendor": "HPE", "model": "ProLiant DL380 Gen11", "firmware": "iLO 6 v1.73", "bmc_model": "iLO 6"},
    {"vendor": "Dell Inc.", "model": "PowerEdge R760", "firmware": "7.10.70.00", "bmc_model": "15G Monolithic"},
    {"vendor": "Supermicro", "model": "X12SPL-F", "firmware": "01.03.03", "bmc_model": "ASPEED"},
]


def test_only_lenovo_xcc3_declares_bmc_model_patterns():
    """선언 adapter 가 늘면 여기와 01-adapter-001 evidence 를 같이 갱신한다 — 공통 규칙이 조용히 넓어지지 않게."""
    declared = sorted(a["adapter_id"] for a in _adapters() if (a.get("match") or {}).get("bmc_model_patterns"))
    assert declared == ["redfish_lenovo_xcc3"]


@pytest.mark.parametrize("facts", FACTS_CORPUS, ids=[f"{f['vendor']}|{f['model'][:18]}|{f['bmc_model'][:14]}" for f in FACTS_CORPUS])
def test_undeclared_adapters_score_identically_with_and_without_bmc_model(facts):
    without = {k: v for k, v in facts.items() if k != "bmc_model"}
    for a in _adapters():
        if (a.get("match") or {}).get("bmc_model_patterns"):
            continue
        assert adapter_specificity(a) == _legacy_specificity(a), a["_filename"]
        assert adapter_matches(a, facts, ALIASES) == adapter_matches(a, without, ALIASES), a["_filename"]
        assert adapter_score(a, facts, ALIASES) == adapter_score(a, without, ALIASES), a["_filename"]


def test_non_lenovo_labels_rank_identically_with_and_without_bmc_model():
    for label, facts in LABEL_FACTS.items():
        if facts["vendor"] == "lenovo":
            continue
        without = {k: v for k, v in facts.items() if k != "bmc_model"}
        assert _ranked(facts) == _ranked(without), label


# ── 5. Ansible facts 조립 — reselect(인증 후)·detect_vendor(1차) 에 bmc_model 이 흐른다 ────────────────────────────────────

def _set_fact(path, name, key):
    for t in yaml.safe_load(path.read_text(encoding="utf-8")):
        if t.get("name") == name:
            return t["ansible.builtin.set_fact"][key]
    raise AssertionError(f"{path.name}: {name}")


def _render(mapping, ctx):
    env = NativeEnvironment()
    return {k: env.from_string(v).render(**ctx) for k, v in mapping.items()}


def test_post_auth_facts_carry_bmc_model_from_the_manager_model():
    tpl = _set_fact(REPO / "redfish-gather/tasks/reselect_adapter.yml", "redfish | reselect | 인증 후 facts 조립", "_rf_postauth_facts")
    raw = {"data": {"system": {"model": "ThinkSystem SR650 V4"}, "bmc": {"firmware_version": XCC3_FW_2ND, "model": "Lenovo XClarity Controller 3"}}}
    facts = _render(tpl, {"_rf_vendor": "lenovo", "_rf_probe_facts": {"vendor": "lenovo"}, "_rf_raw_collect": raw})
    assert facts == {"vendor": "lenovo", "model": "ThinkSystem SR650 V4", "firmware": XCC3_FW_2ND, "bmc_model": "Lenovo XClarity Controller 3"}
    assert _select(facts) == "redfish_lenovo_xcc3"
    # bmc 가 없거나 model 이 null 이어도 빈 문자열(중립) — 템플릿이 터지지 않는다
    for raw in ({"data": {"system": {"model": "x"}}}, {"data": {"system": {"model": "x"}, "bmc": None}}, {"data": {"system": {"model": "x"}, "bmc": {"model": None}}}):
        assert _render(tpl, {"_rf_vendor": "lenovo", "_rf_probe_facts": {}, "_rf_raw_collect": raw})["bmc_model"] == ""


def test_first_pass_probe_facts_carry_bmc_model_and_stay_empty_without_auth():
    tpl = _set_fact(REPO / "redfish-gather/tasks/detect_vendor.yml", "redfish | detect_vendor | normalize vendor", "_rf_probe_facts")
    anonymous = {"vendor": "lenovo", "data": {"bmc": None, "system": None}, "probe_facts": {}}
    facts = _render(tpl, {"_rf_probe_result": anonymous})
    assert facts["bmc_model"] == "" and facts["model"] == "" and facts["firmware"] == ""
    authed = {"vendor": "lenovo", "data": {"bmc": {"model": "Lenovo XClarity Controller 3", "firmware_version": XCC3_FW_2ND},
                                           "system": {"model": "ThinkSystem SR650 V4"}}, "probe_facts": {}}
    assert _render(tpl, {"_rf_probe_result": authed})["bmc_model"] == "Lenovo XClarity Controller 3"
