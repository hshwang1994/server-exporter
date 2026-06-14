"""Regression for merge_fragment / build_errors errors normalization.

배경: errors 항목이 ['[', ']', '\\n', '}', '}'] 5개 character 로 분해 보고된
회귀 사고. root cause 는 os-gather/tasks/linux/gather_system.yml:344-352 의
`>-` block scalar 끝에 잉여 `}}` 두 글자 — Jinja expression 결과 list 가
string 으로 coerce 된 뒤 `\\n}}` 가 concat 되어 `_errors_fragment` 가 list 가
아닌 string ('[...]\\n}}') 으로 들어감. merge_fragment 의 `for e in <string>`
가 character 단위로 iterate 하면서 각 char 를 errors[].message 로 wrap.

본 테스트는 merge_fragment + build_errors 가 string / dict / None 입력에
대해 character iteration 을 차단하고 list of normalized dicts 를 반환하는지
검증한다.
"""
from __future__ import annotations

import json
import jinja2

ENV = jinja2.Environment(trim_blocks=False, lstrip_blocks=False)

# merge_fragment.yml 의 _all_errors expression 을 추출. 변수 이름만 단순화.
MERGE_TPL = ENV.from_string("""
{%- set out = (prev_all | default([])) | list -%}
{%- set ef_raw = ef | default([]) -%}
{%- if ef_raw is string -%}
  {%- set ef = [{'section':'unknown','message':ef_raw,'detail':none}] if (ef_raw | trim | length > 0) else [] -%}
{%- elif ef_raw is mapping -%}
  {%- set ef = [ef_raw] -%}
{%- elif ef_raw is iterable -%}
  {%- set ef = ef_raw -%}
{%- else -%}
  {%- set ef = [] -%}
{%- endif -%}
{%- for e in ef -%}
  {%- if e is string -%}
    {%- if e | trim | length > 0 -%}
      {%- set _ = out.append({'section':'unknown','message':e,'detail':none}) -%}
    {%- endif -%}
  {%- elif e is mapping -%}
    {%- set _ = out.append({
      'section': e.section | default('unknown'),
      'message': e.message | default(e | string),
      'detail':  e.detail  | default(none)
    }) -%}
  {%- endif -%}
{%- endfor -%}
{{ out | tojson }}
""")


def _merge(ef, prev_all=None):
    # production (Ansible) 에서 _all_errors 는 init_fragments.yml 에 의해 [] 로
    # 초기화되므로 None 이 될 일 없음. 표준 Jinja2 의 default filter 는 None 에
    # default 적용 안 하므로 (Ansible 확장 default 와 차이), 테스트 helper 에서 [] 로 정규화.
    if prev_all is None:
        prev_all = []
    return json.loads(MERGE_TPL.render(ef=ef, prev_all=prev_all))


def test_string_input_wrapped_as_single_error():
    """회귀 차단: string `"[]\\n}}"` 입력 시 char-iterate 안 하고 단일 error 로 wrap."""
    out = _merge("[]\n}}")
    assert len(out) == 1
    assert out[0]["section"] == "unknown"
    assert out[0]["message"] == "[]\n}}"
    assert out[0]["detail"] is None


def test_string_blank_input_returns_empty():
    """공백/빈 문자열 입력 → 빈 list."""
    assert _merge("") == []
    assert _merge("   ") == []
    assert _merge("\n\n") == []


def test_char_list_keeps_meaningful_chars_drops_whitespace():
    """사용자 보고 케이스: ['[', ']', '\\n', '}', '}'] char list 입력 시
    whitespace char 는 trim 으로 drop, 의미있는 char 는 wrap 보존."""
    out = _merge(["[", "]", "\n", "}", "}"])
    msgs = [e["message"] for e in out]
    assert "\n" not in msgs  # whitespace skip
    assert msgs == ["[", "]", "}", "}"]
    for e in out:
        assert e["section"] == "unknown"
        assert e["detail"] is None


def test_normal_list_of_dicts():
    out = _merge([
        {"section": "storage", "message": "Drive 실패", "detail": {"status_code": 503}},
        {"section": "network", "message": "NIC timeout"},
    ])
    assert len(out) == 2
    assert out[0]["section"] == "storage"
    assert out[0]["detail"] == {"status_code": 503}
    assert out[1]["section"] == "network"
    assert out[1]["detail"] is None


def test_single_dict_input_wrapped():
    """dict 단일 입력 → list 로 wrap."""
    out = _merge({"section": "bmc", "message": "auth fail"})
    assert len(out) == 1
    assert out[0]["section"] == "bmc"
    assert out[0]["message"] == "auth fail"


def test_none_returns_empty():
    assert _merge(None) == []


def test_int_returns_empty():
    """int / float / 비-iterable → 빈 list (defensive)."""
    assert _merge(42) == []


def test_mixed_list_strings_and_dicts():
    out = _merge([
        "raw error string",
        {"section": "cpu", "message": "throttle", "detail": None},
        "",  # 빈 string skip
        "  ",  # whitespace skip
        {"section": "memory", "message": "ECC error"},
    ])
    sections = [e["section"] for e in out]
    assert sections == ["unknown", "cpu", "memory"]
    assert out[0]["message"] == "raw error string"


def test_accumulates_with_prev_all():
    """이전 누적 + 신규 fragment 동시."""
    prev = [{"section": "system", "message": "first", "detail": None}]
    out = _merge([{"section": "cpu", "message": "second"}], prev_all=prev)
    assert len(out) == 2
    assert out[0]["message"] == "first"
    assert out[1]["message"] == "second"


def test_dict_missing_keys_get_defaults():
    """dict 입력에 section/message 누락 → 'unknown' default."""
    out = _merge([{"detail": "raw stderr"}])
    assert len(out) == 1
    assert out[0]["section"] == "unknown"
    assert out[0]["detail"] == "raw stderr"
