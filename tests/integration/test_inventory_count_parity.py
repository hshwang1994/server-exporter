"""디스크·FC 포트 개수 정합 회귀 (2026-10-27, 사용자 3차 지시).

real_* fixture 마다 recording.json 에 노출된 디스크(present)·FC 포트 수를 gather 와 독립된 규칙(tests/scripts/inventory_parity.py)으로
세고, 현재 코드로 recording 을 재생한 모듈 산출의 개수와 대조한다. `status: success` 는 근거가 아니다 — 노출된 장치가 조용히
누락되거나 없는 장치가 만들어지면 FAIL. 설명되는 차이는 ABSENT_EMPTY_BAY(노출 수에서 이미 제외) · POWER_OFF_NOT_EXPOSED(노출 0) ·
DEDUP_SAME_DRIVE(같은 드라이브 두 경로) 뿐이다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import emulator_harness as H

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "scripts"))
import inventory_parity as IP  # noqa: E402

FIXTURE_ROOT = REPO / "tests" / "fixtures" / "redfish"
CASES = [d for d in sorted(FIXTURE_ROOT.glob("real_*")) if (d / "recording.json").is_file()]


def _replay(case_dir: Path):
    rec = json.loads((case_dir / "recording.json").read_text(encoding="utf-8"))
    meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8")) if (case_dir / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    return H.run_gather(g, n, realm_impl=r, manager_layout=meta.get("manager_layout"),
                        firmware_scope=meta.get("firmware_inventory_scope"))


@pytest.mark.integration
@pytest.mark.skipif(not CASES, reason="real_* fixture 없음")
@pytest.mark.parametrize("case_dir", CASES, ids=[d.name for d in CASES])
def test_collected_disk_and_fc_counts_match_exposed(case_dir):
    result = _replay(case_dir)
    res = IP.run(recording=str(case_dir / "recording.json"), module_doc=result)
    v = res["verdict"]
    assert v["pass"], (f"{case_dir.name}: 노출 수와 수집 수가 다르다 — {v['unexplained']} "
                       f"(exposure={ {k: res['exposure'][k] for k in ('disks_present', 'disks_present_raw', 'disks_absent_empty_bay', 'fc_ports', 'orphan_fc_ndf')} }, "
                       f"collected={res['collected']})")


@pytest.mark.integration
@pytest.mark.skipif(not CASES, reason="real_* fixture 없음")
@pytest.mark.parametrize("case_dir", CASES, ids=[d.name for d in CASES])
def test_no_device_is_fabricated_when_nothing_is_exposed(case_dir):
    """노출 0 인 장비(FC 카드 없음 · 전원 Off 로 Storage 0 · 디스크 미노출)는 수집도 정확히 0 — placeholder 금지."""
    result = _replay(case_dir)
    res = IP.run(recording=str(case_dir / "recording.json"), module_doc=result)
    e, c = res["exposure"], res["collected"]
    if e["disks_present"] == 0:
        assert c["disks"] == 0, f"{case_dir.name}: 디스크 노출 0 인데 {c['disks']}개 수집(조작)"
    if e["fc_ports"] + len(e["orphan_fc_ndf"]) == 0:
        assert c["fc_hbas"] == 0, f"{case_dir.name}: FC 포트 노출 0 인데 hbas {c['fc_hbas']}개 수집(조작)"
