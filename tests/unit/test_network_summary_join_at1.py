"""AT-1 회귀 — network.summary adapter model/manufacturer MAC-join (2026-06-15).

HPE DL380 Gen12(iLO7) 실 미러 검수: normalize_standard.yml 의 _rf_summary_network 가
host EthernetInterface.Id('13','14'…) 에서 id-regex 로 adapter id 를 도출해 adp_map
(NetworkAdapter.Id 'DE0xxxxx' 키)에서 조회 → 두 id 체계가 무관해 join 이 항상 실패,
groups[].model/manufacturer 가 ground truth(BCM57414/Broadcom) 있는데도 전부 null.

수정: port.associated_address(MAC)→소속 adapter 매핑을 추가하고 id-regex 실패 시 nic_mac
fallback. 본 테스트는 normalize_standard.yml 의 *실제* _rf_summary_network 템플릿을 추출해
DL380 미러 컨텍스트로 렌더, model/manufacturer 회복을 검증한다 (id-regex 매칭 vendor 불변).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment

REPO = Path(__file__).resolve().parents[2]
NORMALIZE = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"


def _regex_replace(value, pattern, replacement="", *_a, **_k):
    """ansible regex_replace 최소 구현 (stock Jinja2 엔진용)."""
    return re.sub(pattern, replacement, str(value))


def _extract_template(var_name: str) -> str:
    """normalize_standard.yml 의 set_fact 에서 var_name 의 Jinja 템플릿 문자열 추출."""
    tasks = yaml.safe_load(NORMALIZE.read_text(encoding="utf-8"))
    for t in tasks:
        sf = t.get("ansible.builtin.set_fact") or t.get("set_fact") or {}
        if var_name in sf:
            return sf[var_name]
    raise AssertionError(f"{var_name} set_fact 미발견")


def _render_summary(netad: dict, interfaces: list) -> dict:
    env = Environment()  # noqa: S701 — 테스트 전용, autoescape 불필요
    env.filters["regex_replace"] = _regex_replace
    tmpl = env.from_string(_extract_template("_rf_summary_network"))
    rendered = tmpl.render(_rf_d_netad=netad, _rf_norm_interfaces=interfaces)
    return ast.literal_eval(rendered.strip())


# HPE DL380 Gen12 실 미러 발췌: Broadcom BCM57414 카드 1장(3 adapter 인스턴스, 6 port).
DL380_NETAD = {
    "adapters": [
        {"id": "DE040000", "model": "BCM57414", "manufacturer": "Broadcom", "mac": "14:23:f3:b0:7a:40"},
        {"id": "DE042000", "model": "BCM57414", "manufacturer": "Broadcom", "mac": "14:23:f3:b0:62:f0"},
        {"id": "DE043000", "model": "BCM57414", "manufacturer": "Broadcom", "mac": "14:23:f3:b0:61:c0"},
    ],
    "ports": [
        {"adapter_id": "DE040000", "associated_address": "14:23:f3:b0:7a:40", "port_type": "Ethernet"},
        {"adapter_id": "DE040000", "associated_address": "14:23:f3:b0:7a:41", "port_type": "Ethernet"},
        {"adapter_id": "DE042000", "associated_address": "14:23:f3:b0:62:f0", "port_type": "Ethernet"},
        {"adapter_id": "DE042000", "associated_address": "14:23:f3:b0:62:f1", "port_type": "Ethernet"},
        {"adapter_id": "DE043000", "associated_address": "14:23:f3:b0:61:c0", "port_type": "Ethernet"},
        {"adapter_id": "DE043000", "associated_address": "14:23:f3:b0:61:c1", "port_type": "Ethernet"},
    ],
}
DL380_IFACES = [
    {"id": "13", "mac": "14:23:f3:b0:7a:40", "speed_mbps": None, "link_status": "up"},
    {"id": "14", "mac": "14:23:f3:b0:7a:41", "speed_mbps": None, "link_status": "unknown"},
    {"id": "141", "mac": "14:23:f3:b0:62:f0", "speed_mbps": None, "link_status": "unknown"},
    {"id": "142", "mac": "14:23:f3:b0:62:f1", "speed_mbps": None, "link_status": "unknown"},
    {"id": "205", "mac": "14:23:f3:b0:61:c0", "speed_mbps": None, "link_status": "up"},
    {"id": "206", "mac": "14:23:f3:b0:61:c1", "speed_mbps": None, "link_status": "unknown"},
]


def test_at1_hpe_dl380_summary_recovers_model_manufacturer():
    """6 host iface 전부 MAC-join 으로 model=BCM57414 / manufacturer=Broadcom 회복."""
    summary = _render_summary(DL380_NETAD, DL380_IFACES)
    groups = summary["groups"]
    assert groups, "groups 비어있음"
    # 모든 group 이 model/manufacturer 를 가짐 (수정 전: 전부 None)
    assert all(g["model"] == "BCM57414" for g in groups), [g["model"] for g in groups]
    assert all(g["manufacturer"] == "Broadcom" for g in groups), [g["manufacturer"] for g in groups]
    assert sum(g["quantity"] for g in groups) == 6
    assert summary["adapter_count"] == 3
    assert summary["port_count"] == 6


def test_at1_id_regex_match_still_works_when_no_mac():
    """id-regex 가 매치하는 vendor 형식(iface id 에 adapter id 내포)은 불변 (Additive 보존).

    Dell 류: EthernetInterface id 'NIC.Integrated.1-1-1' → regex strip → 'NIC.Integrated.1'
    == NetworkAdapter id. MAC 없이도 id-regex 로 join 되어야 한다."""
    netad = {
        "adapters": [{"id": "NIC.Integrated.1", "model": "BCM5720", "manufacturer": "Broadcom", "mac": None}],
        "ports": [],
    }
    ifaces = [{"id": "NIC.Integrated.1-1-1", "mac": None, "speed_mbps": 1000, "link_status": "up"}]
    summary = _render_summary(netad, ifaces)
    assert summary["groups"][0]["model"] == "BCM5720"
    assert summary["groups"][0]["manufacturer"] == "Broadcom"


def test_at1_unmatched_interface_stays_none():
    """adapter 와 MAC/id 둘 다 무관한 iface 는 model=None 유지 (날조 금지 — faithful)."""
    netad = {"adapters": [{"id": "DE040000", "model": "BCM57414", "manufacturer": "Broadcom",
                           "mac": "aa:aa:aa:aa:aa:aa"}],
             "ports": [{"adapter_id": "DE040000", "associated_address": "aa:aa:aa:aa:aa:aa",
                        "port_type": "Ethernet"}]}
    ifaces = [{"id": "99", "mac": "bb:bb:bb:bb:bb:bb", "speed_mbps": None, "link_status": "up"}]
    summary = _render_summary(netad, ifaces)
    assert summary["groups"][0]["model"] is None
    assert summary["groups"][0]["manufacturer"] is None
