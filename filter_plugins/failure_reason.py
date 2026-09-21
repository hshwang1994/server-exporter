# -*- coding: utf-8 -*-
# ==============================================================================
# failure_reason.py — 사용자 문구 카탈로그에서 문장 하나를 고르는 필터
# ==============================================================================
# 카탈로그 정본은 common/vars/failure_reasons.yml 의 `_fr_catalog` 다. 이 필터는 문장을
# 갖고 있지 않고, 호출부가 넘긴 카탈로그에서 (키, 채널) 로 고른 뒤 `{loc}` 만 치환한다.
#
# 사용법 (Ansible task):
#   failure_reason: "{{ _fr_catalog | failure_reason('auth_unconfirmed', 'os', se_location | default('')) }}"
#
# 왜 필터인가 (2026-09-21):
#   문장 선택이 code 하나에서 (code, 대상 종류, 세부 사유) 로 바뀌면서 rescue 4곳 +
#   빌더 2곳이 같은 "채널이 없으면 default, {loc} 치환" 을 반복하게 됐다. Jinja 로 여섯 번
#   복제하면 한 곳만 어긋나도 그 경로의 envelope 이 fallback 으로 떨어진다.
#
# 같은 규칙의 Python 복제본:
#   common/library/precheck_bundle.py  _render_reason()
#   callback_plugins/json_only.py      _render_reason()
#   셋의 동작이 같은지는 tests/unit/test_failure_reason_filter.py 가 검사한다.
# ==============================================================================

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import re

# 문장에 들어가는 loc 표시값. 등록된 loc 는 [a-z0-9_-] 라 그대로 나오고, 미등록 입력값은
# 문장을 깨뜨리지 않는 문자만 남긴다 (Portal Grid 에 그대로 보이는 값이다).
_LOC_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_LOC_MAX_LEN = 40
_LOC_EMPTY = "미지정"


def display_location(loc):
    """se_location → 문장에 넣을 표시값. 비거나 안전한 문자가 하나도 없으면 '미지정'."""
    if loc is None:
        return _LOC_EMPTY
    text = _LOC_UNSAFE.sub("", str(loc).strip())[:_LOC_MAX_LEN]
    return text or _LOC_EMPTY


def failure_reason(catalog, key, channel=None, loc=None):
    """카탈로그 → 문장 하나.

    채널 문장이 없으면 default 를 쓴다. 키 자체가 없거나 default 도 없으면 **예외를 낸다** —
    조용히 빈 문장을 내면 Portal 실패 사유 칸이 비는데, 그보다는 rescue 가 실패해 always 의
    fallback 문장으로 떨어지는 편이 원인 추적이 쉽다. 누락은 계약 테스트가 먼저 잡는다.
    """
    if not isinstance(catalog, dict) or key not in catalog:
        raise KeyError("failure_reason: 카탈로그에 없는 키 {0!r}".format(key))
    entry = catalog[key]
    if not isinstance(entry, dict):
        raise KeyError("failure_reason: {0!r} 항목이 채널 매핑이 아님".format(key))
    text = entry.get(channel) if channel else None
    if text is None:
        text = entry.get("default")
    if text is None:
        raise KeyError(
            "failure_reason: {0!r} 에 채널 {1!r} 문장도 default 문장도 없음".format(key, channel))
    return str(text).replace("{loc}", display_location(loc))


class FilterModule(object):
    """Ansible filter plugin for failure_reason catalog lookup"""

    def filters(self):
        return {
            "failure_reason": failure_reason,
        }
