"""golden 재생의 replay-miss 경로를 대장으로 고정한다 (2026-10-29 SA-12, 사용자 의견 — Mock 에 없는 경로의 404 와 실제 404 를 가른다).

SA-12(섀시 드라이브 합집합)는 Storage 의 Links.Enclosures 섀시 본문과 섀시가 광고한 Drives 컬렉션을 새로 GET 한다. golden recording 은
그 전에 만들어져 이 경로가 없고, 재생기는 표식 있는 404(emulator_harness._REPLAY_MISS)를 돌려준다. 그래서 golden 이 바뀌지 않는 것은
"장비가 404 를 줬을 때의 동작" 의 검증이 아니다 — MOCK_LIMITATION 이다. 이 시험은:
  - 사례마다 실제 replay-miss 집합 == 대장(pre_existing ∪ sa12) — 대장에 없는 새 미기록 GET 이 생기면 실패한다(조용히 404 로 재생되지 않게).
  - 대장의 sa12 항목은 모두 MOCK_LIMITATION 이고, 실응답 확인은 Tier 1 미러 관측(tier1)으로만 적혀 있다.
대장: tests/evidence/2026-10-29-redfish-summary-fix/replay_miss_ledger.json (기준 104bcaf0 · 측정 866d28d8 의 실측에서 만들었다).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import emulator_harness as H

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "redfish"
LEDGER_PATH = REPO / "tests" / "evidence" / "2026-10-29-redfish-summary-fix" / "replay_miss_ledger.json"
CASES = [d for d in sorted(FIX.iterdir()) if (d / "recording.json").is_file() and (d / "expected_output.json").is_file()]


def _ledger():
    if not LEDGER_PATH.is_file():
        pytest.skip("replay-miss 대장 없음 (tests/evidence 를 뺀 tree)")
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _misses(case_dir):
    rec = json.loads((case_dir / "recording.json").read_text(encoding="utf-8"))
    meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8")) if (case_dir / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    get_miss, noauth_miss = set(), set()

    def gw(bmc_ip, path, u, p, t, v):
        out = g(bmc_ip, path, u, p, t, v)
        if f"get::{path}" not in rec:
            assert out == H._REPLAY_MISS     # recording 에 없는 경로는 표식 있는 404 로만 재생된다
            get_miss.add(path)
        return out

    def nw(bmc_ip, path, t, v):
        if f"noauth::{path}" not in rec:
            noauth_miss.add(path)
        return n(bmc_ip, path, t, v)

    H.run_gather(gw, nw, realm_impl=r, manager_layout=meta.get("manager_layout"), firmware_scope=meta.get("firmware_inventory_scope"))
    return get_miss, noauth_miss


def test_ledger_covers_exactly_the_recorded_golden_cases():
    assert sorted(_ledger()["cases"]) == [d.name for d in CASES]


@pytest.mark.integration
@pytest.mark.parametrize("case_dir", CASES, ids=[d.name for d in CASES])
def test_replay_miss_paths_match_ledger(case_dir):
    entry = _ledger()["cases"][case_dir.name]
    get_miss, noauth_miss = _misses(case_dir)
    expected = set(entry["pre_existing"]) | {x["path"] for x in entry["sa12"]}
    assert not noauth_miss, sorted(noauth_miss)
    assert sorted(get_miss - expected) == [], "대장에 없는 새 미기록 GET — recording 에 없는 경로가 404 로 재생된다"
    assert sorted(expected - get_miss) == [], "대장의 경로를 더 이상 요청하지 않는다 — 대장을 사유와 함께 갱신"


def test_sa12_entries_are_mock_limitations_with_tier1_observation():
    for name, entry in _ledger()["cases"].items():
        for x in entry["sa12"]:
            assert x["pytest"] == "MOCK_LIMITATION", (name, x["path"])
            t1 = x["tier1"]
            assert t1["class"] in ("MIRROR_REAL", "NO_MIRROR"), (name, x["path"])
            if t1["class"] == "MIRROR_REAL":
                assert t1["label"] and t1["status"] == [200] and t1["note"] == ["tree"], (name, x["path"])
            else:
                assert t1["label"] is None and "미검증" in t1["detail"], (name, x["path"])
            assert x["path"].startswith("Chassis/"), (name, x["path"])   # SA-12 가 새로 부르는 것은 섀시 본문 · 섀시 Drives 뿐
