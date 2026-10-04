# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import re

_NON_HEX_RE = re.compile(r"[^0-9a-f]")


def _clean(value):
    if value is None:
        return None
    s = str(value).strip().lower()
    return s or None


def _hex_only(s):
    return _NON_HEX_RE.sub("", s)


def _group(hexs, width=2, sep=":"):
    return sep.join(hexs[i:i + width] for i in range(0, len(hexs), width))


def normalize_mac(value):
    s = _clean(value)
    if s is None:
        return None
    hexs = _hex_only(s)
    if len(hexs) != 12:
        return s
    if hexs == "0" * 12:
        return None
    return _group(hexs)


def normalize_wwn(value):
    s = _clean(value)
    if s is None:
        return None
    if s.startswith("0x"):
        s = s[2:]
    hexs = _hex_only(s)
    if len(hexs) != 16:
        return s
    if hexs == "0" * 16:
        return None
    return _group(hexs)


def normalize_uuid(value):
    s = _clean(value)
    if s is None:
        return None
    s = s.strip("{}")
    hexs = _hex_only(s)
    if len(hexs) != 32:
        return s or None
    if hexs == "0" * 32 or hexs == "f" * 32:
        return None
    return "%s-%s-%s-%s-%s" % (hexs[0:8], hexs[8:12], hexs[12:16], hexs[16:20], hexs[20:32])


def uuid_byteswap(value):
    n = normalize_uuid(value)
    if n is None or len(n) != 36:
        return n
    a, b, c, d, e = n.split("-")

    def _rev(h):
        return "".join(h[i:i + 2] for i in range(len(h) - 2, -1, -2))

    return "%s-%s-%s-%s-%s" % (_rev(a), _rev(b), _rev(c), d, e)


def uuid_equal(left, right):
    a = normalize_uuid(left)
    b = normalize_uuid(right)
    if a is None or b is None:
        return False
    return a == b or uuid_byteswap(a) == b


class FilterModule(object):

    def filters(self):
        return {
            "normalize_mac": normalize_mac,
            "normalize_wwn": normalize_wwn,
            "normalize_uuid": normalize_uuid,
            "uuid_byteswap": uuid_byteswap,
            "uuid_equal": uuid_equal,
        }
