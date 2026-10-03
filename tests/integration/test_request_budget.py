"""Redfish 요청 수 gate — real_* fixture 재생의 HTTP 요청 다중집합을 고정한다 (2026-10-03, Plan §8-1 · §10-1).

tests/fixtures/redfish/real_*/request_budget.json 의 `expected_http_calls` 는 현재 코드가 그 recording 을 재생할 때 실제로
보내는 HTTP 요청(캐시 hit 제외, noauth 포함)의 다중집합이다. 경로 집합이 바뀌면 — 줄어도, 늘어도 — 이 테스트가 막는다.
의도된 변경(페이지네이션 추가 GET, 상세 GET, 중복 제거)은 fixture 를 사유와 함께 갱신한다 (scratch 생성기: 변경 전 SHA 와 비교).
`http_calls_budget` 은 총 요청 상한이다. golden(expected_output.json) strict 일치는 test_real_capture_replay 가 따로 보장하므로
여기서는 "요청이 줄었는데 데이터도 줄었다" 가 숨을 수 없다 (coverage 는 golden 동치가 더 강한 조건).
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

import emulator_harness as H

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "redfish"
CASES = [d for d in sorted(FIXTURE_ROOT.glob("real_*"))
         if (d / "recording.json").is_file() and (d / "request_budget.json").is_file()]


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _replay_counts(case_dir: Path):
    rec = _load(case_dir / "recording.json")
    layout = _load(case_dir / "meta.json").get("manager_layout") if (case_dir / "meta.json").is_file() else None
    g, n, r = H.make_replayer(rec)
    calls = collections.Counter()

    def gw(bmc_ip, path, u, p, t, v):
        calls[path] += 1
        return g(bmc_ip, path, u, p, t, v)

    def nw(bmc_ip, path, t, v):
        calls["noauth::" + path] += 1
        return n(bmc_ip, path, t, v)

    H.run_gather(gw, nw, realm_impl=r, manager_layout=layout)
    return calls


@pytest.mark.integration
@pytest.mark.skipif(not CASES, reason="request_budget.json 있는 real_* fixture 없음")
@pytest.mark.parametrize("case_dir", CASES, ids=[d.name for d in CASES])
def test_http_calls_match_expected_multiset_and_budget(case_dir):
    budget = _load(case_dir / "request_budget.json")
    calls = _replay_counts(case_dir)
    actual = sorted(f"{p} x{c}" for p, c in calls.items())
    expected = sorted(budget["expected_http_calls"])
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        pytest.fail(
            f"{case_dir.name}: HTTP 요청 집합이 fixture 와 다르다 — 의도된 변경이면 request_budget.json 을 사유와 함께 갱신.\n"
            f"  없어진 요청 {len(missing)}: {missing[:8]}\n  새 요청 {len(extra)}: {extra[:8]}")
    assert sum(calls.values()) <= budget["http_calls_budget"], f"{case_dir.name}: 요청 수 {sum(calls.values())} > budget {budget['http_calls_budget']}"


@pytest.mark.integration
@pytest.mark.skipif(not CASES, reason="fixture 없음")
@pytest.mark.parametrize("case_dir", CASES, ids=[d.name for d in CASES])
def test_budget_file_is_self_consistent(case_dir):
    budget = _load(case_dir / "request_budget.json")
    total = sum(int(e.rsplit(" x", 1)[1]) for e in budget["expected_http_calls"])
    assert total == budget["http_calls_budget"], "expected_http_calls 합 == http_calls_budget"
    assert budget["baseline_http_calls"] - total == (
        sum(int(e.rsplit(" x", 1)[1]) for e in budget["path_set_delta"]["removed"])
        - sum(int(e.rsplit(" x", 1)[1]) for e in budget["path_set_delta"]["added"])), "delta 가 baseline 과 현재의 차이를 설명한다"
    assert budget["path_set_delta"]["added"] == [], "2026-10-03 Phase 3 는 요청을 추가하지 않는다 (추가가 생기면 사유를 적고 이 단언을 갱신)"
