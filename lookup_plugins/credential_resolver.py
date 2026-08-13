# -*- coding: utf-8 -*-
# ==============================================================================
# credential_resolver.py — Credential scope 결정 Lookup Plugin
# ==============================================================================
# `module_utils/credential_common.resolve_credential_scope` 의 얇은 껍데기다.
# registry 두 개(locations.yml / vendor_aliases.yml)를 읽어 순수 함수에 넘긴다.
# 판정 로직은 여기 없다 — 그래야 단위테스트가 Ansible 없이 돈다.
#
# 사용법 (Ansible task):
#   - set_fact:
#       _cred_resolved: >-
#         {{ lookup('credential_resolver',
#                   location=se_location,
#                   target_type='redfish',
#                   vendor=_rf_detected_vendor,
#                   repo_root=lookup('env','REPO_ROOT')) }}
#
# 반환값에 **Secret 이 없다** — scope / 상대경로 / 판정근거뿐이다.
# ==============================================================================

__metaclass__ = type

DOCUMENTATION = r"""
---
name: credential_resolver
author: server-exporter
short_description: Location 기반 Credential scope 결정
description:
  - (location, target_type, 최소 식별정보) 로 Credential 범위를 정한다.
  - vault 상대경로를 반환하며 Secret 은 반환하지 않는다.
  - 다른 Location / Vendor 로 fallback 하지 않는다.
options:
  location:
    description: Location ID (se_location extra-var)
    required: true
  target_type:
    description: os | esxi | redfish
    required: true
  os_type:
    description: linux | windows (target_type=os 일 때만)
    required: false
  vendor:
    description: canonical vendor (target_type=redfish 일 때만)
    required: false
  repo_root:
    description: 프로젝트 루트 경로
    required: false
"""

RETURN = r"""
_raw:
  description: credential_scope / vault_relpath / selection_basis / reason 를 담은 dict 1개
  type: list
  elements: dict
"""

import os
import sys

import yaml

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

LOCATIONS_RELPATH = ("common", "vars", "locations.yml")
VENDOR_ALIASES_RELPATH = ("common", "vars", "vendor_aliases.yml")


def _resolve_repo_root(kwargs, variables):
    """repo_root 결정 — kwargs / 환경변수 / Ansible variables 순 (adapter_loader 와 동일)."""
    repo_root = kwargs.get("repo_root", "") or os.environ.get("REPO_ROOT", "")
    if not repo_root and variables:
        repo_root = variables.get("REPO_ROOT", "")
    if not repo_root:
        raise AnsibleError(
            "credential_resolver: REPO_ROOT를 결정할 수 없습니다. "
            "repo_root 파라미터 또는 REPO_ROOT 환경변수를 설정하세요."
        )
    return repo_root


def _import_credential_common(repo_root):
    """module_utils/credential_common 을 import 한다."""
    module_utils_path = os.path.join(repo_root, "module_utils")
    if module_utils_path not in sys.path:
        sys.path.insert(0, module_utils_path)
    try:
        from credential_common import (  # noqa: WPS433
            resolve_credential_scope,
            resolve_redfish_credentials,
        )
    except ImportError:
        raise AnsibleError(
            "credential_resolver: module_utils/credential_common.py를 "
            "import할 수 없습니다. REPO_ROOT={0}".format(repo_root)
        )
    return resolve_credential_scope, resolve_redfish_credentials


def _clean_str(value):
    """target_type 분기용 최소 정규화 — 판정 로직은 순수 함수 쪽에 있다."""
    if value is None:
        return ""
    return str(value).strip().lower()


def _read_yaml_mapping(path, top_key, what):
    """registry YAML 의 최상위 매핑을 읽는다.

    로드 실패를 조용히 빈 dict 로 넘기지 않는다 — registry 가 안 읽히면
    모든 Location 이 미등록으로 보여 전 대상이 실패하는데, 그 원인이
    "Location 오타" 로 오인되면 진단이 크게 어긋난다.
    """
    if not os.path.isfile(path):
        raise AnsibleError(
            "credential_resolver: {0} 파일을 찾을 수 없습니다: {1}".format(what, path)
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (IOError, OSError, yaml.YAMLError) as exc:
        raise AnsibleError(
            "credential_resolver: {0} 로드 실패 ({1}): {2}".format(what, path, exc)
        )
    mapping = data.get(top_key, {})
    if not isinstance(mapping, dict) or not mapping:
        raise AnsibleError(
            "credential_resolver: {0} 의 '{1}' 항목이 비어 있습니다: {2}".format(
                what, top_key, path
            )
        )
    return mapping


class LookupModule(LookupBase):
    """Credential scope 결정 — Secret 을 다루지 않는다."""

    def run(self, terms, variables=None, **kwargs):
        repo_root = _resolve_repo_root(kwargs, variables)
        resolve_scope, resolve_redfish = _import_credential_common(repo_root)

        locations = _read_yaml_mapping(
            os.path.join(repo_root, *LOCATIONS_RELPATH), "locations", "locations.yml"
        )
        vendor_aliases = _read_yaml_mapping(
            os.path.join(repo_root, *VENDOR_ALIASES_RELPATH),
            "vendor_aliases",
            "vendor_aliases.yml",
        )

        # Redfish 는 표준(전역) / 복구(location+vendor) 두 scope 를 함께 돌려준다.
        # 두 축의 의미가 달라 한 필드에 담으면 반드시 섞인다 — 필드부터 나눈다.
        if _clean_str(kwargs.get("target_type")) == "redfish":
            result = resolve_redfish(
                location=kwargs.get("location"),
                known_locations=locations.keys(),
                known_vendors=vendor_aliases.keys(),
                vendor=kwargs.get("vendor"),
            )
        else:
            result = resolve_scope(
                location=kwargs.get("location"),
                target_type=kwargs.get("target_type"),
                known_locations=locations.keys(),
                known_vendors=vendor_aliases.keys(),
                os_type=kwargs.get("os_type"),
                vendor=kwargs.get("vendor"),
            )
        # 미등록 Location 진단에 쓰라고 허용 목록을 함께 준다. Secret 이 아니다.
        result["known_locations"] = sorted(locations.keys())
        return [result]
