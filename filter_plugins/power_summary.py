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
