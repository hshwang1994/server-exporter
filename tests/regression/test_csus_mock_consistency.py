# -*- coding: utf-8 -*-
"""
HPE CSUS 3200 mock baseline — 자기 일관성 가드 (cycle 2026-05-29 audit, CS-02).

schema/baseline_v1/hpe_csus_3200_baseline.json 은 lab 부재로 FABRICATED MOCK 이다
(rule 25 R7-B — "검증됨" 주장 금지). envelope SHAPE 회귀에는 쓰이지만 실측이 아니므로,
조작된 값들이 내부적으로 모순되거나(예: summary 카운트 ≠ 실제 list 길이) mock 표식이
사라진 채 방치되는 것을 막기 위한 가드 테스트.

실 CSUS/Superdome 장비 fixture (NEXT_ACTIONS C1) 로 교체될 때 본 테스트는
삭제 또는 실측 기준으로 갱신한다 (mock 표식 assert 가 의도적으로 실패하여 전환을 강제).
"""
import json
from pathlib import Path

import pytest

BASELINE = (
    Path(__file__).resolve().parents[2]
    / "schema" / "baseline_v1" / "hpe_csus_3200_baseline.json"
)


@pytest.fixture(scope="module")
def csus():
    with open(BASELINE, encoding="utf-8") as f:
        return json.load(f)


def _multi_node(csus):
    mn = (csus.get("data") or {}).get("multi_node")
    assert mn, "CSUS baseline 에 data.multi_node 가 없음"
    return mn


def test_summary_counts_match_lists(csus):
    """summary 의 카운트가 실제 list 길이와 일치 (조작 값 drift 방지)."""
    mn = _multi_node(csus)
    summ = mn.get("summary") or {}
    assert summ.get("partition_count") == len(mn.get("partitions") or [])
    assert summ.get("manager_count") == len(mn.get("managers") or [])
    assert summ.get("chassis_count") == len(mn.get("chassis") or [])


def test_representative_partition_is_first(csus):
    """representative_partition 표식이 partitions[0] 와 일치."""
    mn = _multi_node(csus)
    parts = mn.get("partitions") or []
    assert parts, "partitions 가 비어있음"
    rep = (mn.get("summary") or {}).get("representative_partition")
    first_id = parts[0].get("partition_id") or parts[0].get("id")
    assert rep == first_id, f"representative={rep} != partitions[0]={first_id}"


def test_multi_node_enabled_and_layout(csus):
    mn = _multi_node(csus)
    assert mn.get("enabled") is True
    assert mn.get("layout"), "multi_node.layout 누락"


def test_still_clearly_marked_mock(csus):
    """lab 부재 상태에서는 mock 표식(baseline_origin + MOCK 시리얼)이 유지돼야 함.

    실측 baseline 으로 교체되면(origin 에 'mock' 없음) 이 가드는 자동으로 skip 되어
    전환을 막지 않는다. mock 인 동안에는 진짜 데이터가 섞여 들어가는 것을 차단.
    """
    mn = _multi_node(csus)
    origin = ""
    for p in mn.get("partitions") or []:
        origin = (p.get("system") or {}).get("baseline_origin") or origin
    origin = origin or json.dumps(csus, ensure_ascii=False)
    if "mock" not in origin.lower():
        pytest.skip("실측 baseline 으로 교체됨 — mock 가드 불필요")
    serials = [
        (p.get("system") or {}).get("serial", "")
        for p in (mn.get("partitions") or [])
    ]
    assert serials and all(
        s.upper().startswith("MOCK") for s in serials
    ), f"mock baseline 인데 partition serial 이 MOCK 표식 없음: {serials}"
