# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function
__metaclass__ = type


def build_diagnosis(precheck_result, channel, adapter_id=None):
    if not isinstance(precheck_result, dict):
        precheck_result = {}

    details = {
        "channel": channel,
        "adapter_candidate": adapter_id,
        "checked_ports": precheck_result.get("checked_ports", []),
    }

    if channel == "os":
        details["detected_os"] = precheck_result.get("detected_os")
        details["detected_port"] = precheck_result.get("detected_port")

    selected_port = precheck_result.get("selected_port")
    if selected_port:
        details["selected_port"] = selected_port

    probe_facts = precheck_result.get("probe_facts", {})
    if isinstance(probe_facts, dict) and probe_facts:
        details.update(probe_facts)

    return {
        "reachable": precheck_result.get("reachable"),
        "port_open": precheck_result.get("port_open"),
        "protocol_supported": precheck_result.get("protocol_supported"),
        "auth_success": precheck_result.get("auth_success"),
        "failure_stage": precheck_result.get("failure_stage"),
        "failure_code": precheck_result.get("failure_code"),
        "failure_reason": precheck_result.get("failure_reason"),
        "details": details,
    }


class FilterModule(object):

    def filters(self):
        return {
            "build_diagnosis": build_diagnosis,
        }
