# -*- coding: utf-8 -*-
# ==============================================================================
# vendor_normalizer.py — canonical vendor 정규화 필터 플러그인
# ==============================================================================
# `module_utils/adapter_common.normalize_vendor` 를 Jinja2 에서 쓸 수 있게 노출한다.
#
# 존재 이유 (Location + Vendor Credential Resolver 선행 필수조건):
#   Vault 경로가 vendor 에서 파생되므로(vault/<loc>/redfish/<vendor>.yml) 정규화
#   결과가 구현마다 다르면 곧 **Credential 오선택**이다. 종전에는 정규화 구현이 3개였다:
#     1. redfish-gather/library/redfish_gather.py `_normalize_vendor_from_aliases`
#     2. redfish-gather/tasks/detect_vendor.yml 의 인라인 Jinja2  ← 본 필터로 대체
#     3. module_utils/adapter_common.py `normalize_vendor`        ← 알고리즘 정본
#   본 필터가 2번을 3번으로 흡수해 구현을 2개로 줄인다.
#   1번은 rule 10 R2(핵심 library stdlib 우선) + rule 15(보호 경로) 때문에 남기고,
#   `tests/unit/test_vendor_normalizer_sot.py` 가 세 결과의 동치를 상시 검증한다.
#
# 사용법 (Ansible task):
#   - set_fact:
#       _rf_detected_vendor: "{{ raw | canonical_vendor(_va.vendor_aliases) }}"
#
# `normalize_vendor` 와의 차이 — 미매치 시 반환값:
#   normalize_vendor : 원문 소문자를 그대로 돌려준다 (adapter match 용).
#   canonical_vendor : 'unknown' 을 돌려준다 (경로/자격 선택 용).
#   후자가 필요한 이유 — 등록되지 않은 문자열이 vault 경로 조각이 되면 안 된다.
# ==============================================================================

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import sys

UNKNOWN_VENDOR = "unknown"


def _import_normalize_vendor():
    """module_utils/adapter_common.normalize_vendor 를 가져온다.

    탐색 순서:
      1. 이 파일 기준 상대 경로 (filter_plugins/ → ../module_utils/) — 저장소 표준 배치
      2. REPO_ROOT 환경변수

    두 경로 모두 실패하면 ImportError 를 그대로 올린다. 조용히 대체 알고리즘으로
    폴백하지 않는다 — 정규화가 갈리는 것이 이 파일이 막으려는 바로 그 사고다.
    """
    candidates = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.normpath(os.path.join(here, "..", "module_utils")))
    except NameError:  # pragma: no cover — __file__ 부재 환경
        pass
    repo_root = os.environ.get("REPO_ROOT", "")
    if repo_root:
        candidates.append(os.path.join(repo_root, "module_utils"))

    for path in candidates:
        if path and os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)

    from adapter_common import normalize_vendor  # noqa: WPS433 (runtime path import)

    return normalize_vendor


def canonical_vendor(raw_vendor, aliases=None, unknown=UNKNOWN_VENDOR):
    """원시 벤더 문자열 → canonical vendor 키, 미상이면 `unknown`.

    Args:
        raw_vendor: Redfish Manufacturer 등 원시 문자열 (None / 비-str 허용)
        aliases:    vendor_aliases.yml 의 `vendor_aliases` dict
                    ({canonical: [alias, ...]} 역형 / 평탄형 둘 다 허용)
        unknown:    미상일 때 반환할 값

    Returns:
        str: `aliases` 의 canonical 키 중 하나, 또는 `unknown`.
             **반환값은 반드시 등록된 canonical 집합 안에 있다** — 이 보장이
             vault 경로 주입을 구조적으로 막는다.
    """
    if not aliases:
        return unknown

    canonical_keys = _canonical_key_set(aliases)
    if not canonical_keys:
        return unknown

    normalize_vendor = _import_normalize_vendor()
    result = normalize_vendor(raw_vendor, aliases)
    if result and result in canonical_keys:
        return result
    return unknown


def _canonical_key_set(aliases):
    """aliases 에서 canonical 키 집합을 추출한다 (역형 / 평탄형 모두 지원)."""
    if not isinstance(aliases, dict):
        return set()
    sample = next(iter(aliases.values()), None)
    if isinstance(sample, list):
        # 역형 {canonical: [alias, ...]} — 키가 곧 canonical
        return {k for k in aliases.keys() if isinstance(k, str)}
    # 평탄형 {alias: canonical} — 값이 canonical
    return {v for v in aliases.values() if isinstance(v, str)}


class FilterModule(object):
    """Ansible filter plugin — canonical vendor 정규화"""

    def filters(self):
        return {
            "canonical_vendor": canonical_vendor,
        }
