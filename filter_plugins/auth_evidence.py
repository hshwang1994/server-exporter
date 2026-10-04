# -*- coding: utf-8 -*-
from __future__ import annotations

import json


def parse_auth_evidence(raw, expect=None):
    out = {
        'valid': False, 'reason': 'missing', 'first_auth_status': None, 'auth_mode': None,
        'credentialed': False, 'label': None, 'role': None, 'last_request': None,
        'requests_sent': None, 'attempt_id': None,
    }
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return out
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            out['reason'] = 'corrupt'
            return out
    if not isinstance(data, dict):
        out['reason'] = 'corrupt'
        return out
    if data.get('schema') != 1:
        out['reason'] = 'schema'
        return out
    expect = expect if isinstance(expect, dict) else {}
    for key in ('build_id', 'event_uuid', 'ip', 'attempt_id'):
        want = expect.get(key)
        if want is None or want == '':
            continue
        if str(data.get(key, '')) != str(want):
            out['reason'] = 'mismatch:' + key
            out['attempt_id'] = data.get('attempt_id')
            return out
    status = data.get('first_auth_status')
    if not isinstance(status, int) or isinstance(status, bool) or status <= 0:
        status = None
    mode = data.get('auth_mode')
    out.update({
        'valid': True, 'reason': 'ok', 'first_auth_status': status,
        'auth_mode': mode if mode in ('credentialed', 'anonymous') else None,
        'credentialed': mode == 'credentialed',
        'label': data.get('label'), 'role': data.get('role'),
        'last_request': data.get('last_request'),
        'requests_sent': data.get('requests_sent') if isinstance(data.get('requests_sent'), int) else None,
        'attempt_id': data.get('attempt_id'),
    })
    return out


class FilterModule(object):
    def filters(self):
        return {'parse_auth_evidence': parse_auth_evidence}
