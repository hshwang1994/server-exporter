# -*- coding: utf-8 -*-
# ==============================================================================
# diagnosis_mapper.py — 진단 결과 변환 필터 플러그인
# ==============================================================================
# precheck_bundle 모듈의 결과를 공통 output JSON의
# diagnosis 구조(diagnosis dict)로 변환합니다. errors[] 조립은
# common/tasks/normalize/build_errors.yml 영역 (이 파일 아님).
#
# 사용법 (Ansible task):
#   - set_fact:
#       _diagnosis: "{{ precheck_result | build_diagnosis('redfish', 'dell_idrac9') }}"
# ==============================================================================

from __future__ import absolute_import, division, print_function
__metaclass__ = type


def build_diagnosis(precheck_result, channel, adapter_id=None):
    """
    precheck_bundle 결과를 공통 diagnosis 딕셔너리로 변환합니다.

    Args:
        precheck_result: precheck_bundle 모듈의 반환값
        channel: 수집 채널 (redfish/os/esxi)
        adapter_id: 선택된 adapter ID (없으면 None)

    Returns:
        diagnosis dict — output JSON의 diagnosis 필드에 들어감
    """
    # precheck_result가 None / non-dict 일 때 AttributeError 방어.
    # rescue path 또는 precheck 모듈이 raise한 경우 호출됨.
    if not isinstance(precheck_result, dict):
        precheck_result = {}

    # "신규 JSON 추가 없음 — 호환성 only" 원칙 적용.
    # detail 정보는 envelope `errors[0].detail` 에 이미 존재. diagnosis.details 에 중복 추가 안 함.
    details = {
        "channel": channel,
        "adapter_candidate": adapter_id,
        "checked_ports": precheck_result.get("checked_ports", []),
    }

    # OS 채널 추가 정보
    if channel == "os":
        details["detected_os"] = precheck_result.get("detected_os")
        details["detected_port"] = precheck_result.get("detected_port")

    # 선택된 포트
    selected_port = precheck_result.get("selected_port")
    if selected_port:
        details["selected_port"] = selected_port

    # probe_facts 병합
    probe_facts = precheck_result.get("probe_facts", {})
    # 비-dict probe_facts (손상된 캐시/외부 JSON) → details.update() ValueError 방어
    if isinstance(probe_facts, dict) and probe_facts:
        details.update(probe_facts)

    return {
        "reachable": precheck_result.get("reachable"),
        "port_open": precheck_result.get("port_open"),
        "protocol_supported": precheck_result.get("protocol_supported"),
        "auth_success": precheck_result.get("auth_success"),
        "failure_stage": precheck_result.get("failure_stage"),
        "failure_reason": precheck_result.get("failure_reason"),
        "details": details,
    }


class FilterModule(object):
    """Ansible filter plugin for diagnosis mapping"""

    def filters(self):
        return {
            "build_diagnosis": build_diagnosis,
        }
