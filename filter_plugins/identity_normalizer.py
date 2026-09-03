# -*- coding: utf-8 -*-
# ==============================================================================
# identity_normalizer.py — 채널 간 식별자 표기 정규화 필터 (MAC / WWN / UUID)
# ==============================================================================
# 존재 이유 (2026-09-03 OS/ESXi 전수 검수 B-06 / B-24 / B-26)
# ---------------------------------------------------------------
# 같은 장비를 세 채널로 수집하면 같은 식별자가 세 가지 표기로 나왔다.
#
#   MAC   Linux/ESXi `00:50:56:84:8b:b9`  vs  Windows `00-50-56-84-C9-5F`
#   WWPN  Linux `0x20000027e36ca66e`  vs  Windows `20:00:00:27:e3:6c:a6:6e`  vs  ESXi `20:00:00:27:E3:6C:A6:6E`
#   UUID  Windows `40A20442-5C1D-C963-…`(대문자)  vs  Linux/ESXi 소문자
#         Redfish `B190019F-56CE-4ED4-A1DD-…`  vs  ESXi `9f0190b1-ce56-d44e-a1dd-…` (SMBIOS 바이트 순서)
#
# field_dictionary 는 이 값들을 "cross-channel 매칭 키" 로 선언한다. 표기가 갈리면 키가
# 아니다. 여기서 한 형식으로 고정한다.
#
# 규칙 (값 형식만 바뀐다 — schema / 키 이름 무변경)
#   MAC  : 소문자, 콜론 구분 6 octet  `aa:bb:cc:dd:ee:ff`. all-zero 는 식별자가 아니므로 null.
#   WWN  : 소문자, 콜론 구분 8 octet  `20:00:00:27:e3:6c:a6:6e`. `0x` 접두 제거.
#   UUID : 소문자 8-4-4-4-12. 중괄호/대시 없는 32-hex 입력 허용. all-zero / all-f 는 null.
#   원문이 예상 길이가 아니면 **바꾸지 않고 소문자·trim 만 한다** (값을 지어내지 않는다).
#
# SMBIOS 바이트 순서
#   SMBIOS 2.6+ 의 UUID 는 앞 3 필드가 little-endian 으로 표시된다 (dmidecode / Windows WMI /
#   vSphere). BMC(Redfish) 는 벤더에 따라 network order 로 준다 (Cisco CIMC 실측). 어느 쪽이
#   "정본" 인지 문자열만 보고는 알 수 없으므로, 이 필터는 표기(대소문자·구분자)만 정규화하고
#   바이트 순서 비교는 `uuid_equal` (두 순서 모두 대조) 로 제공한다. 채널 간 매칭은 이 필터를
#   써야 한다.
#
# 사용법 (Ansible task)
#   mac:  "{{ raw_mac | normalize_mac }}"
#   wwpn: "{{ raw_wwn | normalize_wwn }}"
#   uuid: "{{ raw_uuid | normalize_uuid }}"
# ==============================================================================

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import re

_NON_HEX_RE = re.compile(r"[^0-9a-f]")


def _clean(value):
    """None / 비-문자열 방어 + trim + 소문자. 비어 있으면 None."""
    if value is None:
        return None
    s = str(value).strip().lower()
    return s or None


def _hex_only(s):
    return _NON_HEX_RE.sub("", s)


def _group(hexs, width=2, sep=":"):
    return sep.join(hexs[i:i + width] for i in range(0, len(hexs), width))


def normalize_mac(value):
    """MAC → `aa:bb:cc:dd:ee:ff`. all-zero 는 None. 12-hex 가 아니면 소문자 원문."""
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
    """WWPN/WWNN → `20:00:00:27:e3:6c:a6:6e`. 16-hex 가 아니면 소문자 원문."""
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
    """UUID → 소문자 `8-4-4-4-12`. all-zero / all-f 는 None. 32-hex 가 아니면 소문자 원문."""
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
    """앞 3 필드 바이트 순서를 뒤집은 UUID (SMBIOS little-endian ↔ network order)."""
    n = normalize_uuid(value)
    if n is None or len(n) != 36:
        return n
    a, b, c, d, e = n.split("-")

    def _rev(h):
        return "".join(h[i:i + 2] for i in range(len(h) - 2, -1, -2))

    return "%s-%s-%s-%s-%s" % (_rev(a), _rev(b), _rev(c), d, e)


def uuid_equal(left, right):
    """두 UUID 가 같은 장비를 가리키는가 — 표기 정규화 후 바이트 순서 양쪽 대조."""
    a = normalize_uuid(left)
    b = normalize_uuid(right)
    if a is None or b is None:
        return False
    return a == b or uuid_byteswap(a) == b


class FilterModule(object):
    """Ansible filter plugin — 채널 간 식별자 표기 정규화"""

    def filters(self):
        return {
            "normalize_mac": normalize_mac,
            "normalize_wwn": normalize_wwn,
            "normalize_uuid": normalize_uuid,
            "uuid_byteswap": uuid_byteswap,
            "uuid_equal": uuid_equal,
        }
