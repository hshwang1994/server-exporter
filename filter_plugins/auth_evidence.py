# -*- coding: utf-8 -*-
"""Redfish 인증 증거 파일(attempt 단위) 해석 — Plan §6-3 D7 (2026-10-03).

redfish_gather 모듈은 시도(attempt)마다 `<evidence_dir>/<ip>/<attempt_id>.json` 을 **시작 즉시** 만들고, 자격을 실은
첫 응답을 받는 순간 `first_auth_status` 를 채운다. task timeout(backstop)으로 모듈이 끊겨 `register` 가 없을 때 rescue 는
**현재 attempt 의 파일만** 읽어 세 경우(401 / 200 뒤 정지 / 증거 없음)를 가른다. 이 필터는 그 파일 내용을 안전하게
해석한다 — 손상 · 부재 · 식별자 불일치는 전부 "증거 없음" 이고 예외를 내지 않는다 (rescue 가 또 실패하면 host 의 봉투가
fallback 으로 떨어진다).

valid=True 의 조건: JSON 객체 · schema 1 · build_id/event_uuid/ip/attempt_id 가 기대값과 일치. 다른 attempt 의 파일은 이력일 뿐
현재 시도를 분류하지 않는다. anonymous(빈 자격) 응답 200 은 그 자격의 인증 성공이 아니므로 `credentialed` 가 False 다.
"""
from __future__ import annotations

import json


def parse_auth_evidence(raw, expect=None):
    """raw(str|None) → dict. 항상 같은 키를 돌려준다 (Jinja 쪽 분기가 단순해진다)."""
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
