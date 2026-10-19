"""ESXi network.summary — 링크 다운 vmnic 도 센다 · link_type 'ethernet' (2026-10-19 B-3-ESXi / B-5).

종전 collect_network_extended.yml 의 _e_ext_summary 는 speed > 0 인 vmnic 만 그룹에 넣었다 — 다운 포트(actual_speed 'N/A' → null)는
summary 에서 사라져 quantity 합이 adapters 수와 달랐고 link_up_count == quantity 가 항상 참이었다. link_type 은 vmnic 이 전부 Ethernet
인데 none 이었다. 이제 속도 null/0 은 speed_mbps null 그룹(키 'None') 으로 세고 모든 그룹의 link_type 은 'ethernet' 이다.
그룹 키는 속도만이다 (모델/제조사는 넣지 않는다 — 사용자 결정).

하네스는 test_esxi_partial_failures_c9 의 것 (실제 YAML set_fact + jinja2 NativeEnvironment). 실장비 미검증.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "unit"))

from test_esxi_partial_failures_c9 import _ext  # noqa: E402

UP = {"status": "connected", "actual_speed": 10000, "actual_duplex": "Full Duplex", "driver": "ixgben", "adapter": "Intel(R) Ethernet Controller X710"}
DOWN = {"status": "disconnected", "actual_speed": "N/A", "actual_duplex": "N/A", "driver": "ixgben", "adapter": "Intel(R) Ethernet Controller X710"}


def _vmnics(*specs):
    return [dict(spec, device=f"vmnic{i}") for i, spec in enumerate(specs)]


def _summary(details):
    ctx = _ext(_e_vmnic={"failed": False, "hosts_vmnics_info": {"esxi01": {"vmnic_details": details}}})
    return ctx["_e_ext_summary"]["groups"], ctx


def test_three_up_and_three_down_vmnics_make_two_groups_in_encounter_order():
    groups, ctx = _summary(_vmnics(UP, UP, UP, DOWN, DOWN, DOWN))
    assert groups == [{"speed_mbps": 10000, "link_type": "ethernet", "quantity": 3, "link_up_count": 3},
                      {"speed_mbps": None, "link_type": "ethernet", "quantity": 3, "link_up_count": 0}]
    assert sum(g["quantity"] for g in groups) == len(ctx["_e_ext_adapters"]) == 6, "다운 포트가 summary 에서 사라지지 않는다"
    assert ctx["_data_fragment"]["network"]["summary"] == {"groups": groups}


def test_all_up_case_is_unchanged_except_link_type():
    groups, _ = _summary(_vmnics(UP, UP, UP))
    assert groups == [{"speed_mbps": 10000, "link_type": "ethernet", "quantity": 3, "link_up_count": 3}]


def test_down_first_keeps_encounter_order_null_group_first():
    groups, _ = _summary(_vmnics(DOWN, UP))
    assert [g["speed_mbps"] for g in groups] == [None, 10000]
    assert [(g["quantity"], g["link_up_count"]) for g in groups] == [(1, 0), (1, 1)]


def test_speed_zero_joins_the_null_speed_group():
    """speed 0 은 '속도 없음' 이지 0 Mbps 가 아니다 — null 그룹과 같은 그룹."""
    groups, _ = _summary(_vmnics(dict(DOWN, actual_speed=0), DOWN))
    assert groups == [{"speed_mbps": None, "link_type": "ethernet", "quantity": 2, "link_up_count": 0}]


def test_group_key_is_speed_only_not_model():
    """같은 속도의 다른 모델 NIC 는 한 그룹 — 그룹 키에 모델/제조사를 넣지 않는다."""
    other = dict(UP, adapter="Broadcom BCM57414 NetXtreme-E", driver="bnxtnet")
    groups, _ = _summary(_vmnics(UP, other))
    assert groups == [{"speed_mbps": 10000, "link_type": "ethernet", "quantity": 2, "link_up_count": 2}]


def test_different_speeds_are_separate_groups_and_up_is_counted_per_group():
    up25 = dict(UP, actual_speed=25000)
    down25_linked = dict(UP, actual_speed=25000, status="disconnected")   # 속도는 보고되는데 상태가 down 인 포트
    groups, _ = _summary(_vmnics(UP, up25, down25_linked, DOWN))
    assert groups == [{"speed_mbps": 10000, "link_type": "ethernet", "quantity": 1, "link_up_count": 1},
                      {"speed_mbps": 25000, "link_type": "ethernet", "quantity": 2, "link_up_count": 1},
                      {"speed_mbps": None, "link_type": "ethernet", "quantity": 1, "link_up_count": 0}]


def test_no_vmnics_gives_empty_groups():
    groups, _ = _summary([])
    assert groups == []


def test_every_group_declares_ethernet_and_the_group_shape_is_unchanged():
    groups, _ = _summary(_vmnics(UP, DOWN))
    assert all(set(g) == {"speed_mbps", "link_type", "quantity", "link_up_count"} for g in groups), "키 추가/삭제 없음 (Additive)"
    assert {g["link_type"] for g in groups} == {"ethernet"}
