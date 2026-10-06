
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


import os
import sys

import yaml

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

LOCATIONS_RELPATH = ("common", "vars", "locations.yml")
VENDOR_ALIASES_RELPATH = ("common", "vars", "vendor_aliases.yml")


def _resolve_repo_root(kwargs, variables):
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
    module_utils_path = os.path.join(repo_root, "module_utils")
    if module_utils_path not in sys.path:
        sys.path.insert(0, module_utils_path)
    try:
        from credential_common import (
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
    if value is None:
        return ""
    return str(value).strip().lower()


def _read_yaml_mapping(path, top_key, what):
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
        result["known_locations"] = sorted(locations.keys())
        return [result]
