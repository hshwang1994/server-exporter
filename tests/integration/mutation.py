"""Redfish recording 변형(fault-injection) 레이어 — 기존 replay seam 위에 한 겹.

배경:
    record/replay 공용 모듈(`emulator_harness.py`)는 **정상(well-formed)**
    에뮬레이터 응답을 golden 으로 고정(characterization)만 했다 — 버그까지 함께 고정. 본
    모듈은 그 recording 을 **변형**해 redfish_gather.py 의 파싱 엔진에 신뢰 불가/오염 입력을
    주입하고, 엔진이 **크래시 없이 graceful degrade** 하는지 증명하는 fault-injection 도구다.

    즉 "시뮬레이터/mock 으로 gathering 로직을 실제로 견고하게 만든다" — golden 고정이 아니라.

설계 불변식:
    1. **golden 불간섭**: 본 모듈은 `emulator_harness.py` 를 수정하지 않고 `make_replayer`/
       `run_gather`/`GOLDEN_KEYS` 를 그대로 재사용한다. golden 테스트와 robustness 테스트는
       read-only `run_gather` 외에 코드 경로를 공유하지 않는다.
    2. **원본 불변(immutability)**: `mutate_recording` 은 deep-copy 후 변형한다. 디스크의
       recording.json 도, 메모리의 golden recording dict 도 절대 바뀌지 않는다.
    3. **결정론(determinism)**: 모든 변형은 명시 spec 으로만 결정된다 — 난수/시각/해시시드
       의존 0. `inject_huge_list` 의 합성 멤버도 인덱스 기반으로 결정적으로 만든다.

recording 형식 (emulator_harness.make_recorder 산출):
    {"get::<path>": [status, data, err], "noauth::<path>": [status, data, err], ...}
    - <path> 는 redfish_gather._get 에 넘긴 path 인수 (예: "Systems/1/Processors/1").
    - data 는 그 응답의 raw Redfish JSON(dict). 변형은 주로 이 data 를 RFC-6901 pointer 로 타격.

mutation spec (dict) 어휘:
    공통 키: op, channel("get"|"noauth"), path(<path>). 대부분 pointer(RFC-6901, data 기준).
    | op                | 효과                                                      |
    |-------------------|----------------------------------------------------------|
    | null_field        | pointer 값을 None 으로                                    |
    | set_value         | pointer 값을 value(명시 리터럴)로                         |
    | set_type          | pointer 값을 to("string"|"int"|"float"|"list"|"dict"|    |
    |                   |   "bool")의 고정 표본으로                                 |
    | drop_field        | pointer 가 가리키는 키/원소를 삭제                        |
    | drop_collection   | pointer 리스트(기본 /Members)를 []로                      |
    | inject_member_null| pointer 리스트 맨 앞에 None 삽입 → [null, ...]            |
    | truncate_list     | pointer 리스트를 앞 n(keep)개만                           |
    | inject_huge_list  | pointer 리스트를 count 개 결정적 합성 멤버로 치환         |
    | corrupt_odata_id  | pointer(@odata.id) 값을 비-str(기본 {})로                |
    | http_status       | recording 엔트리를 [status, {}, err]로 (5xx/4xx 주입)    |

사용:
    from mutation import make_mutated_replayer
    get_i, noauth_i, realm_i = make_mutated_replayer(recording, [
        {"op": "set_value", "channel": "get",
         "path": "Systems/1/Processors/1", "pointer": "/TotalCores", "value": "eight"},
    ])
    result = emulator_harness.run_gather(get_i, noauth_i, realm_impl=realm_i)
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

import emulator_harness as H


# ---------------------------------------------------------------------------
# RFC-6901 JSON Pointer (stdlib only — redfish_gather 와 같은 무의존 원칙)
# ---------------------------------------------------------------------------
def _unescape(token: str) -> str:
    """RFC-6901: ~1 → '/', ~0 → '~' (순서 중요)."""
    return token.replace("~1", "/").replace("~0", "~")


def _split_pointer(pointer: str) -> List[str]:
    """'/Members/0/@odata.id' → ['Members', '0', '@odata.id']. '' → []."""
    if pointer in ("", "/"):
        return [] if pointer == "" else [""]
    if not pointer.startswith("/"):
        raise ValueError(f"RFC-6901 pointer 는 '/' 로 시작해야 함: {pointer!r}")
    return [_unescape(tok) for tok in pointer.split("/")[1:]]


def _descend(container: Any, token: str) -> Any:
    """한 단계 하강. list 면 정수 인덱스, dict 면 키."""
    if isinstance(container, list):
        idx = int(token)
        return container[idx]
    if isinstance(container, dict):
        return container[token]
    raise TypeError(f"pointer 하강 불가 (token={token!r}, container 타입={type(container).__name__})")


def _resolve_parent(data: Any, tokens: List[str]):
    """마지막 토큰 직전까지 하강해 (parent_container, last_token) 반환.

    tokens 가 비면 (None, None) — 전체 data 대상.
    """
    if not tokens:
        return None, None
    parent = data
    for tok in tokens[:-1]:
        parent = _descend(parent, tok)
    return parent, tokens[-1]


def _pointer_get(data: Any, pointer: str) -> Any:
    tokens = _split_pointer(pointer)
    cur = data
    for tok in tokens:
        cur = _descend(cur, tok)
    return cur


def _pointer_set(data: Any, pointer: str, value: Any) -> Any:
    """pointer 위치에 value 대입. pointer='' 면 value 자체가 새 data."""
    tokens = _split_pointer(pointer)
    if not tokens:
        return value
    parent, last = _resolve_parent(data, tokens)
    if isinstance(parent, list):
        parent[int(last)] = value
    elif isinstance(parent, dict):
        parent[last] = value
    else:
        raise TypeError(f"set 불가 (parent 타입={type(parent).__name__})")
    return data


def _pointer_delete(data: Any, pointer: str) -> Any:
    tokens = _split_pointer(pointer)
    if not tokens:
        raise ValueError("빈 pointer 는 삭제 불가")
    parent, last = _resolve_parent(data, tokens)
    if isinstance(parent, list):
        del parent[int(last)]
    elif isinstance(parent, dict):
        parent.pop(last, None)
    else:
        raise TypeError(f"delete 불가 (parent 타입={type(parent).__name__})")
    return data


# ---------------------------------------------------------------------------
# 변형 op 표본 (결정론)
# ---------------------------------------------------------------------------
# set_type 의 타입별 고정 표본 — 난수 없이 결정적.
_TYPE_SAMPLES: Dict[str, Any] = {
    "string": "16384",        # 숫자형 필드를 문자열로 (int()/// 크래시 유발 후보)
    "int": 16384,
    "float": 16384.0,
    "list": [],
    "dict": {},
    "bool": True,
    "null": None,
}


def _synthetic_member(i: int) -> Dict[str, Any]:
    """inject_huge_list 용 결정적 합성 Member (well-typed, 인덱스 기반)."""
    return {"@odata.id": f"/redfish/v1/__synthetic__/{i}"}


def _apply_one(recording: Dict[str, list], spec: Dict[str, Any]) -> None:
    """recording(이미 deep-copy 본)에 변형 1건을 in-place 적용."""
    op = spec["op"]
    channel = spec.get("channel", "get")
    path = spec["path"]
    key = f"{channel}::{path}"
    if key not in recording:
        # 조용한 no-op 은 테스트를 거짓 green 으로 만든다 — 명확히 실패시킨다.
        near = [k for k in recording if path in k][:5]
        raise KeyError(
            f"mutation target 없음: {key!r}. path 부분일치 후보: {near or '없음'}"
        )

    entry = recording[key]  # [status, data, err]

    # 엔트리 레벨 op (data pointer 무관)
    if op == "http_status":
        status = spec.get("status", 500)
        recording[key] = [status, {}, spec.get("err", f"HTTP {status}: injected")]
        return

    data = entry[1]
    pointer = spec.get("pointer", "")

    if op == "null_field":
        entry[1] = _pointer_set(data, pointer, None)
    elif op == "set_value":
        entry[1] = _pointer_set(data, pointer, spec["value"])
    elif op == "set_type":
        to = spec["to"]
        if to not in _TYPE_SAMPLES:
            raise ValueError(f"set_type to 미지원: {to!r} (허용: {sorted(_TYPE_SAMPLES)})")
        entry[1] = _pointer_set(data, pointer, copy.deepcopy(_TYPE_SAMPLES[to]))
    elif op == "drop_field":
        entry[1] = _pointer_delete(data, pointer)
    elif op == "drop_collection":
        ptr = pointer or "/Members"
        entry[1] = _pointer_set(data, ptr, [])
    elif op == "inject_member_null":
        ptr = pointer or "/Members"
        lst = _pointer_get(data, ptr)
        if not isinstance(lst, list):
            raise TypeError(f"inject_member_null 대상이 list 아님: {ptr}")
        entry[1] = _pointer_set(data, ptr, [None] + lst)
    elif op == "truncate_list":
        ptr = pointer or "/Members"
        keep = int(spec.get("keep", 0))
        lst = _pointer_get(data, ptr)
        if not isinstance(lst, list):
            raise TypeError(f"truncate_list 대상이 list 아님: {ptr}")
        entry[1] = _pointer_set(data, ptr, lst[:keep])
    elif op == "inject_huge_list":
        ptr = pointer or "/Members"
        count = int(spec.get("count", 5000))
        entry[1] = _pointer_set(data, ptr, [_synthetic_member(i) for i in range(count)])
    elif op == "corrupt_odata_id":
        # 기본: 비-str truthy(빈 dict 는 falsy 라 기존 `if not uri` 가드에 걸려 무의미 →
        # 비-falsy 값으로 가드 우회를 실증). value 로 재정의 가능.
        bad = spec.get("value", {"__corrupt__": True})
        entry[1] = _pointer_set(data, pointer, bad)
    else:
        raise ValueError(f"미지원 op: {op!r}")


def mutate_recording(recording: Dict[str, list],
                     mutations: List[Dict[str, Any]]) -> Dict[str, list]:
    """recording 을 deep-copy 한 뒤 mutations 를 순서대로 적용한 **새 dict** 반환.

    원본 recording 은 절대 변경되지 않는다 (불변식 2). mutations=[] → deep-copy 사본(동치).
    """
    mutated = copy.deepcopy(recording)
    for spec in mutations:
        _apply_one(mutated, spec)
    return mutated


def make_mutated_replayer(recording: Dict[str, list],
                          mutations: List[Dict[str, Any]]):
    """mutate_recording → emulator_harness.make_replayer 재사용.

    반환 (get_impl, noauth_impl, realm_impl) — make_replayer 와 시그니처 동일하므로
    run_gather 호출 방식이 golden 테스트와 완전히 같다 (불변식 1).
    """
    mutated = mutate_recording(recording, mutations)
    return H.make_replayer(mutated)
