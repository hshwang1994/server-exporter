"""errors[] 정규화 계약 — filter_plugins/errors_normalizer.normalize_errors.

배경 1 (2026 초): errors 항목이 ['[', ']', '\\n', '}', '}'] 5개 character 로 분해 보고된
회귀 사고. root cause 는 `>-` block scalar 끝의 잉여 `}}` 로 Jinja expression 결과 list 가
string 으로 coerce 된 뒤 `for e in <string>` 가 char 단위로 iterate 한 것.

배경 2 (2026-08-12): 같은 정규화 Jinja 가 merge_fragment.yml / build_errors.yml /
이 테스트 3곳에 **통째로 복제**돼 있었다(M5). 한쪽만 고치면 누적 단계와 최종 단계가
갈라진다. 값을 반환할 수 있는 유일한 수단인 filter plugin 으로 한 곳에 모았고,
이 테스트는 이제 **production 함수를 직접 호출**한다 (사본 없음).

배경 3 (2026-08-12): 종전 dict 분기는 `e.message | default(e | string)` 이라
  - message 가 None      → null 그대로 통과
  - message 가 ''        → 빈 문자열 그대로 통과
  - message 키 자체 부재 → **파이썬 dict repr 이 사용자 문장 자리에** 노출
셋 다 막지 못했고(H10 / N90~N93), string 도 mapping 도 아닌 원소는 흔적 없이 사라졌다(N18/N94).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))

from errors_normalizer import (  # noqa: E402
    FALLBACK_MESSAGE,
    MAX_DETAIL_LEN,
    normalize_errors,
)


def _merge(value, prev_all=None):
    """merge_fragment.yml 의 누적 시맨틱(`이전 + 정규화(신규)`)을 그대로 재현."""
    return list(prev_all or []) + normalize_errors(value)


# ═══════════════════════════════════════════════════════════════════════════
# character iteration 차단 (원 회귀)
# ═══════════════════════════════════════════════════════════════════════════
def test_string_input_wrapped_as_single_error():
    out = _merge("[]\n}}")
    assert len(out) == 1
    assert out[0]["section"] == "unknown"
    assert out[0]["message"] == "[]\n}}"
    assert out[0]["detail"] is None


def test_string_blank_input_returns_empty():
    assert _merge("") == []
    assert _merge("   ") == []
    assert _merge("\n\n") == []


def test_char_list_keeps_meaningful_chars_drops_whitespace():
    out = _merge(["[", "]", "\n", "}", "}"])
    assert [e["message"] for e in out] == ["[", "]", "}", "}"]
    for e in out:
        assert e["section"] == "unknown"
        assert e["detail"] is None


def test_none_returns_empty():
    assert _merge(None) == []


def test_int_returns_empty():
    """최상위 입력이 비-iterable 스칼라면 담을 정보가 없다."""
    assert _merge(42) == []


# ═══════════════════════════════════════════════════════════════════════════
# 정상 입력
# ═══════════════════════════════════════════════════════════════════════════
def test_normal_list_of_dicts():
    out = _merge([
        {"section": "storage", "message": "Drive 실패", "detail": {"status_code": 503}},
        {"section": "network", "message": "NIC timeout"},
    ])
    assert len(out) == 2
    assert out[0]["section"] == "storage"
    # 2026-08-12: detail 타입을 string|null 로 통일한다 (M12). dict 는 평탄화.
    assert out[0]["detail"] == "status_code=503"
    assert out[1]["section"] == "network"
    assert out[1]["detail"] is None


def test_single_dict_input_wrapped():
    out = _merge({"section": "bmc", "message": "auth fail"})
    assert len(out) == 1
    assert out[0]["section"] == "bmc"
    assert out[0]["message"] == "auth fail"


def test_mixed_list_strings_and_dicts():
    out = _merge([
        "raw error string",
        {"section": "cpu", "message": "throttle", "detail": None},
        "",
        "  ",
        {"section": "memory", "message": "ECC error"},
    ])
    assert [e["section"] for e in out] == ["unknown", "cpu", "memory"]
    assert out[0]["message"] == "raw error string"


def test_accumulates_with_prev_all():
    prev = [{"section": "system", "message": "first", "detail": None}]
    out = _merge([{"section": "cpu", "message": "second"}], prev_all=prev)
    assert [e["message"] for e in out] == ["first", "second"]


# ═══════════════════════════════════════════════════════════════════════════
# H10 — message 는 항상 비지 않은 문자열이다 (사용자 문장 자리에 내부 자료구조 금지)
# ═══════════════════════════════════════════════════════════════════════════
def test_dict_without_message_never_leaks_python_repr():
    out = _merge([{"section": "cpu", "detail": "raw stderr"}])
    assert len(out) == 1
    assert out[0]["message"] == FALLBACK_MESSAGE
    assert "{" not in out[0]["message"] and "'" not in out[0]["message"]
    # 원본을 버리지는 않는다 — detail 로 내려간다
    assert "raw stderr" in out[0]["detail"]
    assert "원본 오류 기록" in out[0]["detail"]


def test_dict_with_null_or_blank_message_is_replaced():
    for bad in (None, "", "   ", 42, {"nested": 1}, ["a"]):
        out = _merge([{"section": "cpu", "message": bad}])
        assert out[0]["message"] == FALLBACK_MESSAGE, bad
        assert isinstance(out[0]["message"], str) and out[0]["message"].strip()


def test_message_is_always_non_empty_string_for_every_input_shape():
    corpus = [
        None, 42, "x", "", ["a", None, 3, {"message": None}, {"detail": "d"}],
        {"section": None, "message": None, "detail": None},
        [{"message": "ok"}], [[1, 2]], (1, 2),
    ]
    for value in corpus:
        for entry in normalize_errors(value):
            assert isinstance(entry["message"], str), (value, entry)
            assert entry["message"].strip(), (value, entry)
            assert isinstance(entry["section"], str) and entry["section"].strip()
            assert entry["detail"] is None or isinstance(entry["detail"], str)


# ═══════════════════════════════════════════════════════════════════════════
# N18 / N94 — string 도 mapping 도 아닌 원소를 조용히 버리지 않는다
# ═══════════════════════════════════════════════════════════════════════════
def test_non_string_non_mapping_elements_are_preserved_not_dropped():
    out = _merge([42, ["a"], None])
    # None 만 버린다 (담을 정보가 없다)
    assert len(out) == 2
    for entry in out:
        assert entry["message"] == FALLBACK_MESSAGE
        assert entry["detail"] and "원본 오류 기록" in entry["detail"]
    assert "42" in out[0]["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# detail 타입 계약 (M12 / N34 / N53)
# ═══════════════════════════════════════════════════════════════════════════
def test_detail_is_string_or_null_only():
    cases = [
        ({"section": "s", "message": "m", "detail": {"rc": 1, "cmd": "lspci"}}, "rc=1; cmd=lspci"),
        ({"section": "s", "message": "m", "detail": ""}, None),
        ({"section": "s", "message": "m", "detail": "  "}, None),
        ({"section": "s", "message": "m", "detail": None}, None),
        ({"section": "s", "message": "m", "detail": 503}, "503"),
        ({"section": "s", "message": "m", "detail": {}}, None),
    ]
    for src, expected in cases:
        assert normalize_errors([src])[0]["detail"] == expected, src


def test_detail_is_capped():
    out = normalize_errors([{"section": "s", "message": "m", "detail": "x" * 5000}])
    assert len(out[0]["detail"]) <= MAX_DETAIL_LEN


# ═══════════════════════════════════════════════════════════════════════════
# 멱등 — merge 단계와 build_errors 단계에서 두 번 통과한다
# ═══════════════════════════════════════════════════════════════════════════
def test_idempotent():
    corpus = [
        None, 42, "raw", ["[", "]", "\n"], {"section": "bmc", "message": "m"},
        [{"detail": "d"}], [{"section": "cpu", "message": None, "detail": {"rc": 1}}],
        [42, None, ["a"]],
    ]
    for value in corpus:
        once = normalize_errors(value)
        assert normalize_errors(once) == once, value


# ═══════════════════════════════════════════════════════════════════════════
# M5 — 정규화 사본이 다시 생기지 않는다
# ═══════════════════════════════════════════════════════════════════════════
def test_normalization_lives_in_exactly_one_place():
    """merge_fragment / build_errors 가 각자 Jinja 로 정규화를 재구현하지 않는다."""
    for rel in ("common/tasks/normalize/merge_fragment.yml",
                "common/tasks/normalize/build_errors.yml"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "normalize_errors" in text, f"{rel} 이 공용 필터를 쓰지 않는다"
        assert "e.message | default" not in text, (
            f"{rel} 에 옛 정규화 사본이 되살아났다 — 필터 한 곳만 쓴다"
        )
