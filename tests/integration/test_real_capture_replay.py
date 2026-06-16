"""실장비 4대 전수 미러 → 오프라인 회귀 테스트 (real_* fixture).

목적 (rule 40 / rule 21 R1):
    실 Dell R740 / HPE DL380 / HPE CSUS3200 / Lenovo SR650 의 전수 Redfish 미러를
    오프라인(에뮬레이터/실장비 없이) 재생해 redfish_gather.py 의 파싱/정규화를
    **실장비 기준**으로 결정적 회귀 검증한다. emulator/mock 보다 강한 ground truth.

    golden = tests/fixtures/redfish/real_*/expected_output.json (모듈 GOLDEN_KEYS snapshot).
    의도된 변경 시 capture_mirror_fixture.py 로 재생성.

오프라인 보장: recording.json 만 사용 — 네트워크 0 (conftest hermetic 가드 + harness seam).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import emulator_harness as H

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "redfish"


def _discover():
    dirs = []
    for d in sorted(FIXTURE_ROOT.glob("real_*")):
        if (d / "recording.json").is_file() and (d / "expected_output.json").is_file():
            dirs.append(d)
    return dirs


CASES = _discover()
CASE_IDS = [d.name for d in CASES]


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _json_norm(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False, sort_keys=True))


def _layout(case_dir: Path):
    mp = case_dir / "meta.json"
    if mp.is_file():
        return _load(mp).get("manager_layout")
    return None


@pytest.fixture(params=CASES, ids=CASE_IDS)
def replay_case(request):
    case_dir = request.param
    recording = _load(case_dir / "recording.json")
    golden = _load(case_dir / "expected_output.json")
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    result = H.run_gather(
        get_impl, noauth_impl, realm_impl=realm_impl,
        manager_layout=_layout(case_dir),
    )
    return result, golden, case_dir


@pytest.mark.integration
@pytest.mark.skipif(not CASES, reason="real_* fixture 없음 (capture_mirror_fixture.py 미수행)")
class TestRealCaptureReplay:
    """실장비 4대 캡처 기반 오프라인 회귀."""

    def test_golden_match(self, replay_case):
        """모듈 gather 산출이 golden 과 strict 일치 (핵심 회귀 게이트)."""
        result, golden, case_dir = replay_case
        for key in H.GOLDEN_KEYS:
            assert _json_norm(result[key]) == golden[key], (
                f"{case_dir.name}: golden mismatch on '{key}' — redfish_gather.py "
                f"파싱이 바뀌었거나 회귀. 의도된 변경이면 capture_mirror_fixture.py 로 재생성."
            )

    def test_status_success(self, replay_case):
        """4대 모두 status=success (수집 정상)."""
        result, _golden, case_dir = replay_case
        assert result["status"] == "success", (
            f"{case_dir.name}: status={result['status']} failed={result.get('failed_sections')}"
        )

    def test_core_sections_present(self, replay_case):
        """핵심 섹션(system/processors/memory/bmc/power/thermal) 존재 + 비어있지 않음."""
        result, _golden, case_dir = replay_case
        data = result["data"]
        for section in ("system", "processors", "memory", "bmc", "power", "thermal"):
            assert section in data and data[section], (
                f"{case_dir.name}: data.{section} 누락/비어있음"
            )

    def test_hostname_not_ip(self, replay_case):
        """2026-06-16 정책: data.system.hostname 이 ip 와 같으면 안 됨 (null 허용).

        모듈 산출 data.system.hostname 은 System.HostName(빈값→None 정규화). IP fallback 은
        build_output 층(여기 미포함)이지만, 모듈 단계에서 hostname 에 IP 가 새지 않음을 보장.
        """
        result, _golden, case_dir = replay_case
        hostname = (result["data"].get("system") or {}).get("hostname")
        assert hostname != "10.0.0.1", (
            f"{case_dir.name}: data.system.hostname 이 replay bmc_ip 와 동일 — IP 누수"
        )


@pytest.mark.integration
def test_four_real_captures_present():
    """실장비 4대 캡처가 모두 존재 (회귀 early warning)."""
    assert len(CASES) >= 4, (
        f"real_* fixture {len(CASES)}개 < 4 (present: {CASE_IDS})"
    )
