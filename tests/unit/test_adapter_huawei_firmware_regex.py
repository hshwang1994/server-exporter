"""Huawei iBMC adapter 의 firmware_patterns 회귀 (2026-08-10).

배경 — 종전 huawei_ibmc.yml 의 firmware_patterns 는 "iBMC*1.*" 같은 **glob 문법**이었다.
adapter_common.pattern_match_any 는 re.search(정규식)를 쓰므로 이 값은
"iBM" + "C"반복 + "1" 로 해석되어, 실제 FirmwareVersion 문자열("3.01" / "iBMC 3.01" /
"5.32")이 어느 패턴에도 맞지 않았다.

adapter_match_score 는 "정보가 있는데 불일치" 를 -9999 실격으로 처리하므로
(module_utils/adapter_common.py:287-288 / :293-298), 결과적으로 huawei_ibmc 는
firmware 가 실린 모든 실장비에서 탈락하고 redfish_generic(-400)이 선택됐다.
그 여파로 huawei OEM collect/normalize 도 함께 죽어 있었다.

본 테스트는 그 회귀를 고정한다:
  1. 대표 firmware 3형식이 huawei_ibmc 를 실격시키지 않을 것
  2. 그 상태에서 실제 선택 결과가 redfish_huawei_ibmc 일 것
  3. 다른 세대/타벤더 firmware 는 여전히 분리될 것

주의: lab 부재 벤더라 실제 문자열은 미확보(rule 96 R1-A). 실장비 확보 시
tests/evidence 에 실측을 남기고 본 기대값을 실측으로 교체할 것.
"""

import glob
import os
import sys

import pytest
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "module_utils"))

from adapter_common import (  # noqa: E402
    adapter_match_score,
    adapter_matches,
    adapter_score,
    load_vendor_aliases,
)

HUAWEI_ADAPTER = os.path.join(REPO_ROOT, "adapters", "redfish", "huawei_ibmc.yml")


def _aliases():
    return load_vendor_aliases(os.path.join(REPO_ROOT, "common", "vars", "vendor_aliases.yml"))


def _huawei():
    with open(HUAWEI_ADAPTER, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _select(facts):
    """adapter_loader 와 동일한 방식으로 redfish 채널 최고점 adapter 를 고른다."""
    aliases = _aliases()
    best = None
    for path in sorted(glob.glob(os.path.join(REPO_ROOT, "adapters", "redfish", "*.yml"))):
        with open(path, encoding="utf-8") as fh:
            adapter = yaml.safe_load(fh)
        if not isinstance(adapter, dict):
            continue
        adapter["_filename"] = os.path.basename(path)
        if not adapter_matches(adapter, facts, aliases):
            continue
        score = adapter_score(adapter, facts, aliases)
        if score > -9999 and (best is None or score > best[0]):
            best = (score, adapter)
    return best


# 실장비에서 관측될 수 있는 FirmwareVersion 표기 3형식.
# (접두사 없음 / "iBMC " 접두사 / "iBMC" 붙임 — 벤더 문서·BMC 구현별 편차)
@pytest.mark.parametrize(
    "firmware",
    ["3.01", "3.01.11.24", "iBMC 3.01", "iBMC3.01", "V3.01", "5.32", "iBMC 5.32"],
)
def test_huawei_firmware_does_not_disqualify(firmware):
    """대표 firmware 표기가 -9999 실격을 유발하지 않아야 한다."""
    facts = {"vendor": "Huawei", "model": "2288H V5", "firmware": firmware}
    adapter = _huawei()
    score = adapter_match_score(adapter, facts, _aliases())
    assert score != -9999, (
        "huawei_ibmc 가 firmware=%r 로 실격됐다. firmware_patterns 가 glob 문법으로 "
        "되돌아갔을 가능성이 크다 (정규식이어야 함)." % firmware
    )
    assert adapter_matches(adapter, facts, _aliases()) is True


@pytest.mark.parametrize("firmware", ["3.01", "iBMC 3.01", "5.32"])
def test_huawei_adapter_actually_selected(firmware):
    """실격이 아닐 뿐 아니라 실제 선택 결과가 huawei adapter 여야 한다."""
    facts = {"vendor": "Huawei", "model": "2288H V5", "firmware": firmware}
    best = _select(facts)
    assert best is not None
    assert best[1]["adapter_id"] == "redfish_huawei_ibmc", (
        "firmware=%r 에서 %s 가 선택됐다 (기대: redfish_huawei_ibmc). "
        "generic(-400) 으로 떨어지면 OEM 수집까지 함께 죽는다." % (firmware, best[1]["adapter_id"])
    )


def test_huawei_firmware_patterns_are_regex_not_glob():
    """firmware_patterns 에 glob 흔적('문자 바로 뒤 *')이 없어야 한다."""
    patterns = _huawei()["match"]["firmware_patterns"]
    for pat in patterns:
        for idx, ch in enumerate(pat):
            if ch != "*" or idx == 0:
                continue
            prev = pat[idx - 1]
            assert prev in ".)]+?", (
                "firmware_patterns 에 glob 문법으로 보이는 값이 있다: %r "
                "(정규식에서 '%s*' 는 '%s 반복' 을 뜻한다)" % (pat, prev, prev)
            )


def test_huawei_normalize_oem_key_is_oem_tasks():
    """redfish-gather/site.yml:145 가 보는 키는 normalize.oem_tasks 다.

    종전 huawei/inspur adapter 는 `oem_normalize` 로 적혀 있어 해당 normalize_oem.yml
    이 영구 미실행이었다 (2026-08-10 fix).
    """
    for name in ("huawei_ibmc", "inspur_isbmc"):
        path = os.path.join(REPO_ROOT, "adapters", "redfish", "%s.yml" % name)
        with open(path, encoding="utf-8") as fh:
            adapter = yaml.safe_load(fh)
        normalize = adapter.get("normalize") or {}
        assert "oem_normalize" not in normalize, (
            "%s: `oem_normalize` 는 site.yml 이 보지 않는 키다 — `oem_tasks` 여야 한다." % name
        )
        assert normalize.get("oem_tasks"), "%s: normalize.oem_tasks 누락" % name
