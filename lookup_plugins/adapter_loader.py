# -*- coding: utf-8 -*-
# ==============================================================================
# adapter_loader.py — Adapter 자동 탐색 및 선택 Lookup Plugin
# ==============================================================================
# adapters/<channel>/ 디렉토리의 YAML 파일을 스캔하고,
# probe facts와 match 조건을 비교하여 최적의 adapter를 선택합니다.
#
# 사용법 (Ansible task):
#   - set_fact:
#       _selected_adapter: >-
#         {{ lookup('adapter_loader',
#                   channel='redfish',
#                   facts=_precheck_result.probe_facts,
#                   repo_root=lookup('env','REPO_ROOT')) }}
# ==============================================================================

__metaclass__ = type

DOCUMENTATION = r"""
---
name: adapter_loader
author: server-exporter
short_description: Adapter 자동 탐색 및 선택
description:
  - adapters/<channel>/ 디렉토리의 YAML 파일을 스캔합니다.
  - 각 adapter의 match 조건을 probe facts와 비교합니다.
  - 가장 높은 점수의 adapter를 반환합니다.
options:
  channel:
    description: 수집 채널 (redfish/os/esxi)
    required: true
  facts:
    description: probe facts 딕셔너리
    required: false
    default: {}
  repo_root:
    description: 프로젝트 루트 경로
    required: false
"""

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display

import glob
import os
import yaml
import sys

display = Display()


def _resolve_repo_root(kwargs, variables):
    """repo_root 결정 — kwargs / 환경변수 / Ansible variables 순."""
    repo_root = kwargs.get("repo_root", "") or os.environ.get("REPO_ROOT", "")
    if not repo_root and variables:
        repo_root = variables.get("REPO_ROOT", "")
    if not repo_root:
        raise AnsibleError(
            "adapter_loader: REPO_ROOT를 결정할 수 없습니다. "
            "repo_root 파라미터 또는 REPO_ROOT 환경변수를 설정하세요."
        )
    return repo_root


def _import_adapter_common(repo_root):
    """module_utils 경로 추가 후 adapter_common import.

    Returns: (load_vendor_aliases, normalize_vendor, adapter_matches,
              adapter_score, adapter_specificity, adapter_match_score)
    """
    module_utils_path = os.path.join(repo_root, "module_utils")
    if module_utils_path not in sys.path:
        sys.path.insert(0, module_utils_path)
    try:
        from adapter_common import (  # noqa: WPS433 (runtime path import)
            load_vendor_aliases,
            normalize_vendor,
            adapter_matches,
            adapter_score,
            adapter_specificity,
            adapter_match_score,
        )
    except ImportError:
        raise AnsibleError(
            "adapter_loader: module_utils/adapter_common.py를 "
            "import할 수 없습니다. REPO_ROOT={0}".format(repo_root)
        )
    return (load_vendor_aliases, normalize_vendor, adapter_matches,
            adapter_score, adapter_specificity, adapter_match_score)


def _scan_adapters(adapter_dir):
    """adapter 디렉터리 스캔 → list of dict (_source_file, _filename 포함).

    glob 결과는 sorted()로 알파벳순 정렬한다 — 스캔 순서가 결정적이어야
    `_match_and_score()` 출력 list 순서가 일관된다. score 동률 시 Python
    `list.sort()`는 stable sort이므로 알파벳순 (= 파일명 순)이 tie-break이
    된다.
    """
    if not os.path.isdir(adapter_dir):
        raise AnsibleError(
            "adapter_loader: adapter 디렉토리를 찾을 수 없습니다: {0}".format(adapter_dir)
        )
    adapters = []
    for path in sorted(glob.glob(os.path.join(adapter_dir, "*.yml"))):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):  # scalar/list adapter YAML → skip (item assignment crash 방지)
                continue
            data["_source_file"] = path
            data["_filename"] = os.path.basename(path)
            adapters.append(data)
        except Exception as e:
            display.warning(
                "adapter_loader: {0} 로드 실패: {1}".format(path, str(e))
            )
    if not adapters:
        raise AnsibleError(
            "adapter_loader: {0} 디렉토리에 adapter YAML이 없습니다.".format(adapter_dir)
        )
    return adapters


def _match_and_score(adapters, facts, aliases, adapter_matches, adapter_score,
                     adapter_specificity=None, adapter_match_score=None):
    """각 adapter의 match 평가 + 점수 계산. matched=[(score, adapter), ...].

    `-vvv` 시 각 매칭 후보의 score breakdown 표시:
      score = priority × 1000 + specificity × 10 + match_score
    """
    matched = []
    rejected_with_reason: list[str] = []
    for adapter in adapters:
        adapter_id = adapter.get("adapter_id", adapter.get("_filename"))
        if adapter_matches(adapter, facts, aliases):
            score = adapter_score(adapter, facts, aliases)
            if score > -9999:
                matched.append((score, adapter))
                # score breakdown logging (debugging visibility)
                if adapter_specificity and adapter_match_score:
                    priority = adapter.get("priority", 0)  # 표시용 raw (int() 제거 — 오타 priority 가 로깅서 crash 안 나게)
                    spec = adapter_specificity(adapter)
                    msc = adapter_match_score(adapter, facts, aliases)
                    display.vvv(
                        "adapter_loader: {0} matched score={1} "
                        "(priority={2}×1000 + specificity={3}×10 + match={4})"
                        .format(adapter_id, score, priority, spec, msc)
                    )
                else:
                    display.vvv(
                        "adapter_loader: {0} matched (score={1})".format(
                            adapter_id, score
                        )
                    )
            else:
                rejected_with_reason.append(
                    "{0} (match passed but score=-9999 — firmware/model regex 충돌)".format(adapter_id)
                )
        else:
            rejected_with_reason.append(
                "{0} (match 조건 불일치)".format(adapter_id)
            )
    if rejected_with_reason:
        display.vvv(
            "adapter_loader: 후보 거부 — {0}건".format(len(rejected_with_reason))
        )
        for reason in rejected_with_reason[:10]:  # 최대 10건만
            display.vvv("  - {0}".format(reason))
    return matched


def _pick_generic_fallback(adapters):
    """generic 플래그 적용된 adapter 반환 (없으면 None)."""
    for adapter in adapters:
        if adapter.get("generic", False):
            display.v(
                "adapter_loader: generic fallback 사용: {0}".format(
                    adapter.get("adapter_id")
                )
            )
            return adapter
    return None


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        channel = kwargs.get("channel")
        if not channel:
            raise AnsibleError("adapter_loader: 'channel' 파라미터가 필요합니다.")

        facts = kwargs.get("facts", {}) or {}
        repo_root = _resolve_repo_root(kwargs, variables)
        (load_vendor_aliases, _normalize_vendor, adapter_matches,
         adapter_score, adapter_specificity, adapter_match_score) = (
            _import_adapter_common(repo_root)
        )

        aliases_path = os.path.join(repo_root, "common", "vars", "vendor_aliases.yml")
        aliases = load_vendor_aliases(aliases_path)

        adapter_dir = os.path.join(repo_root, "adapters", channel)
        adapters = _scan_adapters(adapter_dir)

        # debugging visibility — facts 입력 요약 -vvv 로그
        display.vvv(
            "adapter_loader: channel={0}, facts vendor={1}, model={2}, firmware={3}".format(
                channel,
                facts.get("vendor", "?"),
                facts.get("model", "?"),
                facts.get("firmware", "?"),
            )
        )
        display.vvv(
            "adapter_loader: scanned {0} candidates from {1}".format(
                len(adapters), adapter_dir
            )
        )

        matched = _match_and_score(
            adapters, facts, aliases, adapter_matches, adapter_score,
            adapter_specificity, adapter_match_score,
        )
        if not matched:
            fallback = _pick_generic_fallback(adapters)
            if fallback is not None:
                return [fallback]
            raise AnsibleError(
                "adapter_loader: channel={0}에 매칭되는 adapter가 없습니다. "
                "facts={1}".format(channel, facts)
            )

        # 점수순 정렬 (내림차순). Python list.sort()는 stable sort이므로
        # 동률 시 _scan_adapters()가 알파벳순 정렬해 둔 원래 순서를
        # 유지한다 — 즉 동률 tie-break는 파일명 알파벳 오름차순.
        # 동률 발생 자체가 priority/specificity 일관성 위반 신호이므로
        # 동률 발견 시 vvv 경고를 남긴다.
        matched.sort(key=lambda x: x[0], reverse=True)
        best_score, best_adapter = matched[0]

        # top 3 후보 -vvv 로그 (debugging visibility)
        display.vvv(
            "adapter_loader: top {0} candidates (score 내림차순):".format(
                min(3, len(matched))
            )
        )
        for i, (sc, ad) in enumerate(matched[:3], start=1):
            display.vvv(
                "  #{0} {1} score={2}".format(
                    i, ad.get("adapter_id", ad.get("_filename")), sc
                )
            )

        if len(matched) >= 2 and matched[0][0] == matched[1][0]:
            display.vvv(
                "adapter_loader: 점수 동률 발견 — {0}={1} vs {2}={3} "
                "(파일명 알파벳순으로 tie-break, priority/specificity 일관성 점검 권장)".format(
                    matched[0][1].get("_filename"), matched[0][0],
                    matched[1][1].get("_filename"), matched[1][0],
                )
            )

        display.v(
            "adapter_loader: 선택됨 — {0} (score={1}) [score = priority×1000 + specificity×10 + match]".format(
                best_adapter.get("adapter_id", "unknown"), best_score
            )
        )

        return [best_adapter]
