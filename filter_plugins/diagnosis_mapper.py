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
    # production-audit (2026-04-29): precheck_result가 None / non-dict 일 때 AttributeError 방어.
    # rescue path 또는 precheck 모듈이 raise한 경우 호출됨.
    if not isinstance(precheck_result, dict):
        precheck_result = {}

    # cycle 2026-05-01: 사용자 명시 "신규 JSON 추가 없음 — 호환성 only" 원칙 적용.
    # detail 정보는 envelope `errors[0].detail` 로 전달되므로 diagnosis.details 에 중복 추가 안 함.
    # (cycle 2026-04-30에 추가됐던 'detail' 키 제거 — 호환성 영역 외)
    #
    # 2026-08-10 정정: 위 "errors[0].detail 에 이미 존재" 전제는 2026-08-10 이전까지
    # **성립하지 않았다.** errors[0].detail 을 채우는 변수(_fail_error_detail)를 set 하는
    # 코드가 저장소에 하나도 없어(build_failed_output.yml:49 가 유일한 참조처) 완전 실패
    # 경로의 detail 은 항상 null 이었다. 이제 run_precheck.yml 이 그 변수를 set 하므로
    # 전제가 실제로 성립한다. 따라서 본 함수가 detail 을 싣지 않는 것은 여전히 옳다.
    # (섹션 단위 gather 오류의 detail 은 예전부터 정상 전달됨 — build_errors.yml:43)
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
    # Round 15: 비-dict probe_facts (손상된 캐시/외부 JSON) → details.update() ValueError 방어
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
