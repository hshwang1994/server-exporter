"""mirror_replay.tier2_replay 가 저장소의 2차 Mock zip 1대를 풀어 모듈 산출을 내는지 (2026-10-27, FIX 8 편입 확인).

Tier 2 = emulator_harness.run_gather 경로(네트워크 0). 가장 작은 zip(dl380_gen12_03, 전원 Off 스냅샷)을 임시 디렉터리에 풀어
status/vendor/섹션과 개수 정합(inventory_parity)을 본다. Windows 경로 길이(최장 153자)를 넘기면 skip.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "redfish-probe"))
sys.path.insert(0, str(REPO / "tests" / "scripts"))
ZIP = REPO / "tests" / "reference" / "redfish" / "mock2" / "dl380_gen12_03.zip"


@pytest.mark.integration
@pytest.mark.skipif(not ZIP.is_file(), reason="mock2 zip 없음")
def test_tier2_replay_of_a_mock2_zip(tmp_path):
    from mirror_replay import tier2_replay as T2
    import inventory_parity as IP
    with zipfile.ZipFile(ZIP) as z:
        longest = max(len(str(tmp_path / n)) for n in z.namelist())
        if longest > 240:
            pytest.skip(f"경로 길이 {longest} > 240 (Windows MAX_PATH) — 짧은 루트에서 수동 실행")
        z.extractall(tmp_path)
    mirror_dir = tmp_path / "dl380_gen12_03"
    res, err, mirror = T2.replay_one(mirror_dir)
    assert err is None, err
    assert res["status"] == "success" and res["vendor"] == "hpe"
    assert "storage" in res["collected"] and "thermal" in res["collected"]
    assert mirror.stats["keyed"] > 1000
    # 개수 정합: 전원 Off 스냅샷은 Storage 멤버 0 → 디스크 노출 0 → 수집 0 (placeholder 금지)
    parity = IP.run(mirror=str(mirror_dir), module_doc=res)
    assert parity["verdict"]["pass"], parity["verdict"]
    assert parity["exposure"]["disks_present"] == 0 and parity["collected"]["disks"] == 0
    assert "POWER_OFF_NOT_EXPOSED" in parity["verdict"]["notes"]
    summary = json.dumps(parity["verdict"])
    assert "UNEXPLAINED" not in summary.upper() or parity["verdict"]["pass"]
