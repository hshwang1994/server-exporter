# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import re

_LOC_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_LOC_MAX_LEN = 40
_LOC_EMPTY = "미지정"


def display_location(loc):
    if loc is None:
        return _LOC_EMPTY
    text = _LOC_UNSAFE.sub("", str(loc).strip())[:_LOC_MAX_LEN]
    return text or _LOC_EMPTY


def failure_reason(catalog, key, channel=None, loc=None):
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

    def filters(self):
        return {
            "failure_reason": failure_reason,
        }
