"""Regression for F5 — PowerSubsystem fallback에 EnvironmentMetrics 통합 (cycle 2026-05-01).

배경: DMTF 2020.4 schema 분리로 PowerControl 같은 system-level metric 이
PowerSubsystem 본체가 아닌 /Chassis/{id}/EnvironmentMetrics 의 PowerWatts 로 이동.
신 펌웨어 (HPE iLO 6 / Lenovo XCC2-3 / Dell iDRAC9 5.x+ / Supermicro X14+) 가
/Power 404 → /PowerSubsystem fallback 시 power_consumed_watts/min/max 가 None
으로 비어있던 문제.

본 테스트:
  - PowerSubsystem fetch 후 EnvironmentMetrics 응답이 200 일 때 power_control 채움
  - EnvironmentMetrics 404 시 power_capacity_watts (PSU 합산) 만 유지, 나머지 None
  - PSU 자체 부재 시 power_control = None (이전 동작 유지 — Additive only)
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

# ansible stub (Windows dev / import 안전)
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402


def _make_get_mock(routes: dict):
    """_get(bmc_ip, path, ...) → routes 사전 매핑.

    routes key: path 의 마지막 segment (e.g. 'PowerSubsystem', 'EnvironmentMetrics').
    routes value: (status, json_data) tuple. 미매칭 path → (404, {}).
    """
    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        for needle, resp in routes.items():
            if needle in path:
                status, data = resp
                return status, data, None
        return 404, {}, None
    return fake_get


def test_power_subsystem_with_environment_metrics(monkeypatch):
    """PowerSubsystem 200 + EnvironmentMetrics 200 → power_consumed_watts 채움."""
    routes = {
        'PowerSubsystem/PowerSupplies/0': (200, {
            'Name': 'PSU0',
            'Model': 'DPS-800',
            'PowerCapacityWatts': 800,
            'Status': {'Health': 'OK', 'State': 'Enabled'},
        }),
        'PowerSubsystem/PowerSupplies': (200, {
            'Members': [{'@odata.id': '/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies/0'}],
        }),
        'PowerSubsystem': (200, {
            'PowerSupplies': {'@odata.id': '/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies'},
        }),
        'EnvironmentMetrics': (200, {
            'PowerWatts': {'Reading': 412, 'ReadingRangeMin': 350, 'ReadingRangeMax': 480},
        }),
    }
    monkeypatch.setattr(rg, '_get', _make_get_mock(routes))

    data, errs = rg._gather_power_subsystem(
        '10.0.0.1', '/redfish/v1/Chassis/1', 'u', 'p', 30, False,
    )
    assert errs == []
    assert data['power_supplies'][0]['power_capacity_w'] == 800
    pc = data['power_control']
    assert pc['power_consumed_watts'] == 412
    assert pc['min_consumed_watts'] == 350
    assert pc['max_consumed_watts'] == 480
    assert pc['power_capacity_watts'] == 800   # PSU 합산
    assert pc['interval_in_min'] is None       # EnvironmentMetrics 표준에 없음
    assert pc['avg_consumed_watts'] is None    # EnvironmentMetrics 표준에 없음


def test_power_subsystem_environment_metrics_404(monkeypatch):
    """PowerSubsystem 200 + EnvironmentMetrics 404 → consumed=None, capacity 만 유지."""
    routes = {
        'PowerSubsystem/PowerSupplies/0': (200, {
            'PowerCapacityWatts': 750,
            'Status': {'Health': 'OK', 'State': 'Enabled'},
        }),
        'PowerSubsystem/PowerSupplies': (200, {
            'Members': [{'@odata.id': '/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies/0'}],
        }),
        'PowerSubsystem': (200, {
            'PowerSupplies': {'@odata.id': '/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies'},
        }),
        # EnvironmentMetrics 미매칭 → 404
    }
    monkeypatch.setattr(rg, '_get', _make_get_mock(routes))

    data, errs = rg._gather_power_subsystem(
        '10.0.0.1', '/redfish/v1/Chassis/1', 'u', 'p', 30, False,
    )
    assert errs == []
    pc = data['power_control']
    assert pc['power_consumed_watts'] is None  # EnvironmentMetrics 부재
    assert pc['power_capacity_watts'] == 750   # PSU 합산은 정상
    assert pc['min_consumed_watts'] is None
    assert pc['max_consumed_watts'] is None


def test_power_subsystem_no_psu_returns_none_control(monkeypatch):
    """PSU collection link 없음 → power_control = None (Additive only — 기존 동작)."""
    routes = {
        'PowerSubsystem': (200, {}),  # PowerSupplies link 없음
    }
    monkeypatch.setattr(rg, '_get', _make_get_mock(routes))

    data, errs = rg._gather_power_subsystem(
        '10.0.0.1', '/redfish/v1/Chassis/1', 'u', 'p', 30, False,
    )
    assert errs == []
    assert data['power_supplies'] == []
    assert data['power_control'] is None   # PSU 0개 → control 자체 None


def test_power_subsystem_environment_metrics_partial_reading(monkeypatch):
    """EnvironmentMetrics.PowerWatts.Reading 만 응답 (min/max 부재) — 이거만 채움."""
    routes = {
        'PowerSubsystem/PowerSupplies/0': (200, {
            'PowerCapacityWatts': 1100,
            'Status': {'Health': 'OK', 'State': 'Enabled'},
        }),
        'PowerSubsystem/PowerSupplies': (200, {
            'Members': [{'@odata.id': '/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies/0'}],
        }),
        'PowerSubsystem': (200, {
            'PowerSupplies': {'@odata.id': '/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies'},
        }),
        'EnvironmentMetrics': (200, {
            'PowerWatts': {'Reading': 525},  # min/max 미응답
        }),
    }
    monkeypatch.setattr(rg, '_get', _make_get_mock(routes))

    data, _ = rg._gather_power_subsystem(
        '10.0.0.1', '/redfish/v1/Chassis/1', 'u', 'p', 30, False,
    )
    pc = data['power_control']
    assert pc['power_consumed_watts'] == 525
    assert pc['min_consumed_watts'] is None
    assert pc['max_consumed_watts'] is None


def test_power_subsystem_environment_metrics_non_dict_powerwatts(monkeypatch):
    """EnvironmentMetrics.PowerWatts 가 dict 가 아닌 (잘못된 응답) → 무시, 기존 None 유지."""
    routes = {
        'PowerSubsystem/PowerSupplies/0': (200, {
            'PowerCapacityWatts': 600,
            'Status': {'Health': 'OK', 'State': 'Enabled'},
        }),
        'PowerSubsystem/PowerSupplies': (200, {
            'Members': [{'@odata.id': '/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies/0'}],
        }),
        'PowerSubsystem': (200, {
            'PowerSupplies': {'@odata.id': '/redfish/v1/Chassis/1/PowerSubsystem/PowerSupplies'},
        }),
        'EnvironmentMetrics': (200, {
            'PowerWatts': 'invalid-non-dict',  # 비표준 응답
        }),
    }
    monkeypatch.setattr(rg, '_get', _make_get_mock(routes))

    data, _ = rg._gather_power_subsystem(
        '10.0.0.1', '/redfish/v1/Chassis/1', 'u', 'p', 30, False,
    )
    pc = data['power_control']
    assert pc['power_consumed_watts'] is None  # 잘못된 응답 → 무시
    assert pc['power_capacity_watts'] == 600   # PSU 합산은 정상
