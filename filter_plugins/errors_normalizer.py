# -*- coding: utf-8 -*-
# ==============================================================================
# errors_normalizer.py — errors[] 정규화 필터 플러그인 (2026-08-12 신설)
# ==============================================================================
# 왜 필터인가
# -----------
# 종전에는 같은 정규화 Jinja 가 세 곳에 통째로 복제돼 있었다:
#   common/tasks/normalize/merge_fragment.yml  (_all_errors 누적)
#   common/tasks/normalize/build_errors.yml    (_norm_errors 최종)
#   tests/unit/test_errors_normalize.py        (테스트가 원문을 다시 복제)
# 한쪽만 고치면 누적 단계와 최종 단계가 갈라진다(M5). Ansible 태스크는 값을 반환하지
# 못해 include_tasks 로는 공유가 안 되므로, 값을 반환하는 유일한 수단인 filter plugin
# 으로 한 곳에 모은다. (선례: filter_plugins/diagnosis_mapper.build_diagnosis —
# ansible.cfg:16 filter_plugins, :44 jinja2_native=True 로 list/dict 반환 보존)
#
# 계약 (2026-08-12 확정)
# ----------------------
#   section : 비지 않은 문자열. 없거나 공백/비-문자열이면 'unknown'.
#   message : **항상 비지 않은 문자열**. null / '' / 키 부재 / 비-문자열이면 고정 문장으로
#             대체하고 원본은 detail 로 내린다. 파이썬 dict repr 이 사용자 문장 자리에
#             들어가는 일이 없어야 한다 (H10 / N90~N93).
#   detail  : 문자열 또는 null. dict 는 'k=v; k=v' 로 평탄화한다 (M12 / N34 / N53).
#             기술 근거(포트 / HTTP status / URI / 예외 / rc / stderr)는 여기에만 둔다.
#   drop    : string / mapping 이 아닌 원소를 조용히 버리지 않는다 (N18 / N94).
#             None 과 공백-only 문자열만 버린다 (정보량 0).
#   멱등    : 결과를 다시 넣어도 같은 결과가 나온다 (merge 단계와 build 단계에서 두 번
#             통과하므로 필수).
#
# 사용법 (Ansible task):
#   _all_errors:  "{{ (_all_errors | default([])) + (_errors_fragment | default([]) | normalize_errors) }}"
#   _norm_errors: "{{ _all_errors | default([]) | normalize_errors }}"
# ==============================================================================

from __future__ import absolute_import, division, print_function

__metaclass__ = type

try:                                             # pragma: no cover - py3 전용 경로
    from collections.abc import Mapping
except ImportError:                              # pragma: no cover
    from collections import Mapping

# message 를 만들 수 없을 때 쓰는 고정 문장.
# 사용자 문구 규칙(포트 / HTTP status / 내부 용어 / 긴 대시 금지)을 지키고,
# 완결된 한국어 문장이며 조치를 포함한다.
FALLBACK_MESSAGE = "서버 정보 수집 중 오류가 발생했습니다. 대상 상태와 수집 로그를 확인하세요."

# 원본을 detail 에 남길 때 붙이는 접두사.
RAW_PREFIX = "원본 오류 기록: "

# detail 문자열 상한. BMC 가 수십 건을 반환해도 envelope 이 비대해지지 않게 한다.
MAX_DETAIL_LEN = 2000

DEFAULT_SECTION = "unknown"


def _text(value):
    """어떤 값이든 사람이 읽을 문자열로. bytes 는 utf-8 로 복원 시도."""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", "replace")
        except Exception:                        # pragma: no cover - 방어
            return repr(value)
    return "%s" % (value,)


def _flatten_mapping(value):
    """{'status_code': 401, 'rc': 1} → 'status_code=401; rc=1'."""
    return "; ".join("%s=%s" % (_text(k), _text(v)) for k, v in value.items())


def _clean_str(value):
    """문자열이고 공백이 아니면 trim 한 값, 아니면 None."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _detail_text(value):
    """detail 원본 → 문자열 또는 None (타입 통일 — M12)."""
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
        # 사용자 문장을 만들 수 없다. 고정 문장으로 대체하되 원본은 버리지 않는다.
        message = FALLBACK_MESSAGE
        detail_parts.append(RAW_PREFIX + _text(dict(item)))
    section = _clean_str(item.get("section")) or DEFAULT_SECTION
    return _entry(section, message, _join_detail(detail_parts))


def _as_sequence(value):
    """최상위 입력을 순회 가능한 list 로 정규화 (character iteration 차단).

    Jinja2 의 `for e in <string>` 은 char 단위로 iterate 한다. 예전 회귀에서
    errors 가 ['[', ']', '\\n', '}', '}'] 로 분해된 원인이라 명시적으로 wrap 한다.
    """
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
        # int / float 등 비-iterable — 담을 정보가 없다.
        return []


def normalize_errors(value):
    """errors 원본 → [{'section','message','detail'}] 표준 리스트. 멱등."""
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
        # string 도 mapping 도 아닌 원소 — 조용히 버리지 않는다.
        out.append(_entry(DEFAULT_SECTION, FALLBACK_MESSAGE,
                          _join_detail([RAW_PREFIX + _text(item)])))
    return out


class FilterModule(object):
    """Ansible filter plugin for errors[] normalization"""

    def filters(self):
        return {
            "normalize_errors": normalize_errors,
        }
