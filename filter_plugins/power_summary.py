# -*- coding: utf-8 -*-
"""power.summary 공통 필터 (2026-10-19 — ADR-2026-10-19-esxi-sensors-and-linux-iscsi).

redfish-gather/tasks/normalize_standard.yml 의 `_rf_power_summary` Jinja 식과 같은 규칙을 Python 으로 둔 것이다. ESXi 채널
(esxi-gather/tasks/normalize_power_thermal.yml)이 쓴다. Redfish 쪽 Jinja 는 그대로이고 tests/unit/test_esxi_sensors.py 가 두 구현이
같은 입력에 같은 값을 내는지 대조한다 (한쪽만 바꾸면 그 시험이 막는다).

규칙 (2026-10-10 D-07 · 2026-10-19 A-3):
  - State=Absent 슬롯은 설치된 PSU 가 아니다 — 수 · 용량 합 · 상태 집계에서 뺀다 (목록 power_supplies 에는 남는다).
  - 용량을 아는 PSU 가 하나도 없으면 total_capacity_w 는 None (0 은 "용량 0 W" 라는 거짓 값). 일부만 알면 부분 합.
  - consumed_capacity_pct 는 용량 합 > 0 이고 소비전력을 알 때만 (소수 1자리).
  - redundant 는 설치 PSU 수 >= 2 (수량이지 이중화 정책이 아니다).
"""
from __future__ import absolute_import, division, print_function
__metaclass__ = type


def _low(value):
    return str(value).strip().lower() if value is not None else ''


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def power_summary(power):
    """{'power_supplies': [...], 'power_control': {...}} → summary dict (키 · 규칙은 _rf_power_summary 와 같다)."""
    power = power if isinstance(power, dict) else {}
    psu_total = psu_active = cap_total = critical = warning = ok = unknown_health = cap_unknown = 0
    for psu in (power.get('power_supplies') or []):
        if not isinstance(psu, dict):
            continue
        state = _low(psu.get('state'))
        if state == 'absent':
            continue
        psu_total += 1
        if state == 'enabled':
            psu_active += 1
        health = _low(psu.get('health'))
        if health == 'critical':
            critical += 1
        elif health == 'warning':
            warning += 1
        elif health == 'ok':
            ok += 1
        else:
            unknown_health += 1
        cap = psu.get('power_capacity_w')
        if cap is None:
            cap_unknown += 1
        else:
            cap_total += (_as_int(cap) or 0)
    cap_known = (psu_total - cap_unknown) > 0
    control = power.get('power_control')
    consumed = control.get('power_consumed_watts') if isinstance(control, dict) else None
    pct = None
    if cap_known and cap_total > 0 and consumed is not None:
        consumed_int = _as_int(consumed)
        if consumed_int is not None:
            pct = round(consumed_int * 100 / cap_total, 1)
    rollup = 'Critical' if critical > 0 else ('Warning' if warning > 0 else ('OK' if ok > 0 else 'Unknown'))
    return {
        'psu_count': psu_total,
        'psu_active': psu_active,
        'redundant': psu_total >= 2,
        'total_capacity_w': cap_total if cap_known else None,
        'capacity_unknown_count': cap_unknown,
        'critical_count': critical,
        'warning_count': warning,
        'ok_count': ok,
        'unknown_health_count': unknown_health,
        'health_rollup': rollup,
        'consumed_watts': consumed,
        'consumed_capacity_pct': pct,
    }


class FilterModule(object):
    def filters(self):
        return {'power_summary': power_summary}
