"""DMTF 표준 mockup(DSP2043) record/replay 오프라인 회귀 테스트.

목적:
    redfish_gather.py 의 **표준(vendor-agnostic, OEM 미사용) 추출 경로** 를 결정적으로
    회귀 검증한다. 기존 hpe_emulator_* 는 전부 vendor=hpe(Oem.Hpe 경로), baseline 5종도
    벤더 특화 — OEM 확장이 전혀 없는 순수 DMTF 표준 서버는 오프라인 회귀가 없었다.

    DMTF 공식 mockup(BSD-3, 가공의 Manufacturer="Contoso" 등)을 오프라인 재생해
    "벤더 미매치 → 표준 경로 + graceful degradation(legacy Power / SimpleStorage
    fallback / absent NetworkAdapters)" 을 회귀한다. vendor=unknown 이 기대값이며,
    그 자체가 표준 경로를 탔다는 증거다.

    **mockup != 실장비.** golden 은 schema/baseline_v1/ 실측 baseline 이 아니라
    tests/fixtures/redfish/dmtf_*/expected_output.json (DMTF-mockup-derived).

오프라인 보장: recording.json 만 사용 — 네트워크 호출 0 (conftest hermetic 가드 + replay
realm seam). 정적 mockup 은 vendor=unknown 이라 G6 realm probe 에 도달하지만, replayer 의
realm_impl(None) 이 seam 우회 urlopen 을 막는다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import emulator_harness as H

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "redfish"


def _discover():
    """dmtf_* fixture 디렉터리(recording + golden 동반) 수집."""
    dirs = []
    for d in sorted(FIXTURE_ROOT.glob("dmtf_*")):
        if (d / "recording.json").is_file() and (d / "expected_output.json").is_file():
            dirs.append(d)
    return dirs


CASES = _discover()
CASE_IDS = [d.name for d in CASES]


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _json_norm(obj):
    """tuple→list 등 JSON 왕복 정규화 — golden(json.load) 과 동일 타입으로 비교."""
    return json.loads(json.dumps(obj, ensure_ascii=False, sort_keys=True))


@pytest.fixture(params=CASES, ids=CASE_IDS)
def replay_case(request):
    """각 DMTF mockup fixture 를 오프라인 재생해 (result, golden, dir) 반환."""
    case_dir = request.param
    recording = _load(case_dir / "recording.json")
    golden = _load(case_dir / "expected_output.json")

    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    result = H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl)
    return result, golden, case_dir


@pytest.mark.integration
@pytest.mark.skipif(not CASES, reason="dmtf_* fixture 없음 (convert_dmtf_mockup.py 미수행)")
class TestDmtfMockupReplay:
    """DMTF 표준 mockup 기반 오프라인 회귀 (표준/generic 추출 경로 보호)."""

    def test_golden_match(self, replay_case):
        """모듈 gather 산출이 golden 과 strict 일치 (핵심 회귀 게이트).

        redfish_gather.py 의 표준 경로 파싱이 바뀌면 본 테스트가 어떤 필드가 어떻게
        변했는지 드러낸다. 의도된 변경이면 convert_dmtf_mockup.py 로 golden 재생성.
        """
        result, golden, case_dir = replay_case
        for key in H.GOLDEN_KEYS:
            assert _json_norm(result[key]) == golden[key], (
                f"{case_dir.name}: golden mismatch on '{key}' — 표준 경로 파싱 회귀. "
                f"의도된 변경이면 convert_dmtf_mockup.py 로 golden 재생성."
            )

    def test_vendor_matches_golden(self, replay_case):
        """벤더 감지 == golden(벤더 중립 — HPE 클래스의 hardcoded 'hpe' 와 분리)."""
        result, golden, case_dir = replay_case
        assert result["vendor"] == golden["vendor"], (
            f"{case_dir.name}: vendor={result['vendor']!r} != golden {golden['vendor']!r}"
        )

    def test_standard_path_no_oem(self, replay_case):
        """표준(OEM 미사용) 추출 경로를 탔음을 검증 — 본 fixture 의 존재 이유.

        DMTF 표준 mockup 의 Manufacturer 는 vendor_aliases 미매치(예: "Contoso") →
        vendor=unknown → OEM 추출 분기 미진입. data.system.oem 은 빈 dict 여야 한다
        (가공의 Oem.Contoso/Chipwise 가 추출되면 표준 경로가 아니라 회귀).
        """
        result, _golden, case_dir = replay_case
        assert result["vendor"] == "unknown", (
            f"{case_dir.name}: 표준 mockup 인데 vendor={result['vendor']!r} (alias 오매치?)"
        )
        sys_oem = (result["data"].get("system") or {}).get("oem")
        assert sys_oem in ({}, None), (
            f"{case_dir.name}: 표준 경로인데 system.oem 추출됨={sys_oem!r} (OEM 분기 오진입)"
        )

    def test_core_sections_collected(self, replay_case):
        """핵심 섹션 수집 — status success/partial + system/processors/memory/bmc 존재."""
        result, _golden, case_dir = replay_case
        assert result["status"] in ("success", "partial"), (
            f"{case_dir.name}: status={result['status']}"
        )
        data = result["data"]
        for section in ("system", "processors", "memory", "bmc"):
            assert section in data and data[section], (
                f"{case_dir.name}: data.{section} 누락/비어있음"
            )

    def test_system_identity_parsed(self, replay_case):
        """ComputerSystem 표준 식별 필드 파싱 — manufacturer/model/serial/uuid."""
        result, _golden, case_dir = replay_case
        sysd = result["data"].get("system") or {}
        for field in ("manufacturer", "model", "serial", "uuid"):
            assert sysd.get(field), f"{case_dir.name}: system.{field} 미파싱"

    def test_simplestorage_fallback_parsed(self, replay_case):
        """SimpleStorage fallback 파싱 정상 — data.storage 가 있으면 controller/drive 추출.

        주의: redfish_gather 는 modern Storage 부재 시 SimpleStorage fallback
        을 쓰며, 이때 'Storage 미지원, SimpleStorage fallback 사용' notice 를 errors[] 에
        남겨 storage 를 failed 로 분류한다(데이터는 정상). 이는 HPE iLO4 SmartStorage
        fallback 과 동일한 **기존 엔진 동작**이다. 분류 개선(fallback 성공 시 failed→
        degraded)은 status 의미론 변경이라 별도 후속 작업 후보. 본 테스트는 분류와 무관하게
        **파싱 정확성(positive invariant)** 만 검증한다 — 현재 동작 freeze 가 아님.
        """
        result, _golden, case_dir = replay_case
        storage = result["data"].get("storage") or {}
        controllers = storage.get("controllers") or []
        if not controllers:
            pytest.skip(f"{case_dir.name}: storage 데이터 없음")
        drives = controllers[0].get("drives") or []
        assert drives, f"{case_dir.name}: storage controller drive 미파싱"
        assert any(d.get("capacity_bytes") for d in drives), (
            f"{case_dir.name}: 어떤 drive 도 capacity_bytes 미파싱"
        )

    def test_absent_resource_graceful(self, replay_case):
        """graceful degradation + replay 404 fidelity 검증.

        Chassis 에 NetworkAdapters 가 없는 표준 서버는 실 BMC 가 404 를 주고, 엔진은
        이를 unsupported(capability 미지원)로 분류해야 한다. replayer 의 _REPLAY_MISS 가
        실 404("HTTP 404...")를 모사하므로, absent endpoint 가 failed 로 오분류되면 안 된다
        (replay 인공물 회귀 방어). 즉 unsupported 로 분류된 섹션은 failed 에 없어야 한다.
        """
        result, _golden, case_dir = replay_case
        overlap = set(result["unsupported_sections"]) & set(result["failed_sections"])
        assert not overlap, (
            f"{case_dir.name}: 동일 섹션이 unsupported+failed 중복 분류={overlap}"
        )
        # absent NetworkAdapters 는 failed 가 아니라 unsupported 여야 한다(404 fidelity).
        if not (result["data"].get("network_adapters") or {}).get("adapters"):
            assert "network_adapters" not in result["failed_sections"], (
                f"{case_dir.name}: absent NetworkAdapters 가 failed 로 오분류 "
                f"(replay 404 fidelity / _REPLAY_MISS 회귀)"
            )


@pytest.mark.integration
def test_at_least_one_dmtf_fixture_present():
    """DMTF fixture 누락 회귀 방지 — 최소 1 개 dmtf_* fixture 존재."""
    assert CASES, (
        "dmtf_* fixture 가 0 개. convert_dmtf_mockup.py 로 변환 필요."
    )
