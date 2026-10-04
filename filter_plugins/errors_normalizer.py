# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

__metaclass__ = type

try:
    from collections.abc import Mapping
except ImportError:
    from collections import Mapping

FALLBACK_MESSAGE = "서버 정보 수집 중 오류가 발생했습니다. 대상 상태와 수집 로그를 확인하세요."

RAW_PREFIX = "원본 오류 기록: "

MAX_DETAIL_LEN = 2000

DEFAULT_SECTION = "unknown"


def _text(value):
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", "replace")
        except Exception:
            return repr(value)
    return "%s" % (value,)


def _flatten_mapping(value):
    return "; ".join("%s=%s" % (_text(k), _text(v)) for k, v in value.items())


def _clean_str(value):
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _detail_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        return _clean_str(value)
    if isinstance(value, Mapping):
        return _flatten_mapping(value) if len(value) else None
    if isinstance(value, bytes):
        return _clean_str(_text(value))
    return _text(value)


def _join_detail(parts):
    parts = [p for p in parts if p]
    if not parts:
        return None
    joined = " | ".join(parts)
    if len(joined) > MAX_DETAIL_LEN:
        joined = joined[:MAX_DETAIL_LEN]
    return joined


def _entry(section, message, detail):
    return {"section": section, "message": message, "detail": detail}


def _from_mapping(item):
    detail_parts = [_detail_text(item.get("detail"))]
    message = _clean_str(item.get("message"))
    if message is None:
        message = FALLBACK_MESSAGE
        detail_parts.append(RAW_PREFIX + _text(dict(item)))
    section = _clean_str(item.get("section")) or DEFAULT_SECTION
    return _entry(section, message, _join_detail(detail_parts))


def _as_sequence(value):
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        cleaned = _clean_str(_text(value))
        return [cleaned] if cleaned else []
    if isinstance(value, Mapping):
        return [value]
    try:
        return list(value)
    except TypeError:
        return []


def normalize_errors(value):
    out = []
    for item in _as_sequence(value):
        if item is None:
            continue
        if isinstance(item, (str, bytes)):
            message = _clean_str(_text(item))
            if message:
                out.append(_entry(DEFAULT_SECTION, message, None))
            continue
        if isinstance(item, Mapping):
            out.append(_from_mapping(item))
            continue
        out.append(_entry(DEFAULT_SECTION, FALLBACK_MESSAGE,
                          _join_detail([RAW_PREFIX + _text(item)])))
    return out


class FilterModule(object):

    def filters(self):
        return {
            "normalize_errors": normalize_errors,
        }
