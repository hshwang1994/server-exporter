"""HPE iLO 에뮬레이터 record/replay 오프라인 회귀 테스트.

목적:
    HPE 공식 iLO Redfish 에뮬레이터로 캡처한 recording 을 **오프라인**(에뮬레이터
    없이) 재생해 redfish_gather.py 의 파싱/정규화 엔진을 결정적으로 회귀 검증한다.
    실장비 1 대(DL380 Gen11)뿐인 lab 부재 상황에서 iLO5/iLO6/Gen12 + HBA/FC 코드
    경로를 코드 변경 회귀로부터 보호한다.

    **에뮬레이터 != 실장비.** golden 은 schema/baseline_v1/ 실측 baseline 이 아니라
    tests/fixtures/redfish/hpe_emulator_*/expected_output.json (emulator-derived).

회귀 메커니즘:
    recording.json (입력) → 실제 detect_vendor/_collect_all_sections 구동 →
    expected_output.json (golden) 과 strict 비교. redfish_gather.py 의 파싱이
    바뀌면 본 테스트가 어떤 필드가 어떻게 변했는지 드러낸다. 의도된 변경 시
    `python tests/integration/capture_emulator.py --mockup <X>` 로 golden 재생성.

오프라인 보장: recording.json 만 사용 — 네트워크 호출 0. 에뮬레이터를 꺼도 통과.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import emulator_harness as H

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "redfish"


def _discover():
    """hpe_emulator_* fixture 디렉터리(recording + golden 동반) 수집."""
    dirs = []
    for d in sorted(FIXTURE_ROOT.glob("hpe_emulator_*")):
        if (d / "recording.json").is_file() and (d / "expected_output.json").is_file():
            dirs.append(d)
    return dirs


CASES = _discover()
CASE_IDS = [d.name for d in CASES]

# FC HBA 를 실제 보유한 fixture (실측 2026-06-08: dl325_fc=2, dl365=2, 그 외=0).
# golden 이 아니라 fixture 이름으로 keyed — golden 재생성 시 함께 비워져 방어가
# 무력화되는 것(golden-laundering)을 막는다.
FC_FIXTURES = {"hpe_emulator_dl325_gen10plus_fc", "hpe_emulator_dl365_gen10plus"}


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _json_norm(obj):
    """tuple→list 등 JSON 왕복 정규화 — golden(json.load) 과 동일 타입으로 비교."""
    return json.loads(json.dumps(obj, ensure_ascii=False, sort_keys=True))


@pytest.fixture(params=CASES, ids=CASE_IDS)
def replay_case(request):
    """각 에뮬레이터 fixture 를 오프라인 재생해 (result, golden, dir) 반환."""
    case_dir = request.param
    recording = _load(case_dir / "recording.json")
    golden = _load(case_dir / "expected_output.json")

    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    result = H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl)
    return result, golden, case_dir


@pytest.mark.integration
@pytest.mark.skipif(not CASES, reason="hpe_emulator_* fixture 없음 (capture 미수행)")
class TestHpeEmulatorReplay:
    """에뮬레이터 캡처 기반 오프라인 회귀 (캡처된 모든 BMC type parametrize)."""

    def test_golden_match(self, replay_case):
        """모듈 gather 산출이 golden 과 strict 일치 (핵심 회귀 게이트)."""
        result, golden, case_dir = replay_case
        for key in H.GOLDEN_KEYS:
            assert _json_norm(result[key]) == golden[key], (
                f"{case_dir.name}: golden mismatch on '{key}' — "
                f"redfish_gather.py 파싱이 바뀌었거나 회귀. 의도된 변경이면 "
                f"capture_emulator.py 로 golden 재생성."
            )

    def test_vendor_is_hpe(self, replay_case):
        """벤더 감지 == hpe (무인증 ServiceRoot Oem.Hpe 경로)."""
        result, _golden, case_dir = replay_case
        assert result["vendor"] == "hpe", f"{case_dir.name}: vendor={result['vendor']!r}"

    def test_collection_succeeded(self, replay_case):
        """수집 성공 — 핵심 섹션 존재(비어있지 않음) + status success/partial.

        라이브러리 data 섹션 타입: system/bmc/memory=dict, processors/network/
        firmware=list. 타입 가정 대신 "존재 + 비어있지 않음" 으로 검증.
        """
        result, _golden, case_dir = replay_case
        assert result["status"] in ("success", "partial"), (
            f"{case_dir.name}: status={result['status']}"
        )
        data = result["data"]
        for section in ("system", "processors", "memory", "bmc"):
            assert section in data and data[section], (
                f"{case_dir.name}: data.{section} 누락/비어있음"
            )

    def test_processors_parsed(self, replay_case):
        """CPU 파싱 — processors list 비어있지 않고 model 추출 (iLO5/iLO6/Gen12)."""
        result, _golden, case_dir = replay_case
        proc = result["data"].get("processors") or []
        assert isinstance(proc, list) and proc, f"{case_dir.name}: processors 비어 있음"
        assert any(c.get("model") for c in proc), (
            f"{case_dir.name}: 어떤 CPU 도 model 추출 안 됨"
        )

    def test_storage_parsed(self, replay_case):
        """스토리지 파싱 — controllers 키 존재 (HBA/FC 변형 경로 견고화)."""
        result, _golden, case_dir = replay_case
        if "storage" not in result["collected"]:
            pytest.skip(f"{case_dir.name}: storage 미수집")
        storage = result["data"].get("storage") or {}
        assert "controllers" in storage, (
            f"{case_dir.name}: storage.controllers 누락"
        )

    def test_memory_total_mib(self, replay_case):
        """메모리 총량 파싱 — total_mib > 0 (int/str cast 회귀 방어)."""
        result, _golden, case_dir = replay_case
        mem = result["data"].get("memory") or {}
        assert (mem.get("total_mib") or 0) > 0, (
            f"{case_dir.name}: memory.total_mib 미파싱(int/str cast 회귀 의심)"
        )

    def test_firmware_non_empty(self, replay_case):
        """펌웨어 인벤토리 파싱 — FirmwareInventory 비어있지 않음."""
        result, _golden, case_dir = replay_case
        if "firmware" not in result["collected"]:
            pytest.skip(f"{case_dir.name}: firmware 미수집")
        fw = result["data"].get("firmware") or []
        assert isinstance(fw, list) and fw, (
            f"{case_dir.name}: FirmwareInventory 빈 결과(엔드포인트 파싱 회귀)"
        )

    def test_bmc_firmware_version(self, replay_case):
        """BMC 펌웨어 버전 추출 — OEM 경로 (iLO5/iLO6/Gen12 표기 차이 무관).

        주의: 'iLO' 부분문자열 검사 금지 — Gen12 는 bmc.firmware_version 이
        '1.13.01 May 13 2025' 로 'iLO' 미포함. 존재만 검증.
        """
        result, _golden, case_dir = replay_case
        bmc = result["data"].get("bmc") or {}
        assert bmc.get("firmware_version"), (
            f"{case_dir.name}: bmc.firmware_version 미추출(OEM 추출 경로 회귀)"
        )

    def test_fc_hbas_present(self, replay_case):
        """FC HBA 파싱 — FC fixture(dl325_fc/dl365)에서 fc_hbas + WWPN 추출.

        dl325_gen10plus_fc/dl365_gen10plus 가 FC HBA 를 보유 — 이 fixture 의
        존재 이유(FC 경로 회귀)를 직접 검증. 그 외 fixture 는 skip.
        """
        result, _golden, case_dir = replay_case
        if case_dir.name not in FC_FIXTURES:
            pytest.skip(f"{case_dir.name}: FC HBA fixture 아님")
        fc = (result["data"].get("network_adapters") or {}).get("fc_hbas") or []
        assert fc, f"{case_dir.name}: FC HBA 파싱 회귀(fc_hbas 비어있음)"
        assert any(h.get("wwpn") for h in fc), (
            f"{case_dir.name}: FC HBA WWPN 미추출"
        )


@pytest.mark.integration
def test_at_least_one_fixture_present():
    """캡처 누락 회귀 방지 — 최소 1 개 에뮬레이터 fixture 존재."""
    assert CASES, (
        "hpe_emulator_* fixture 가 0 개. capture_emulator.py 로 캡처 필요."
    )


@pytest.mark.integration
def test_hermetic_guard_is_active():
    """conftest 의 hermetic 가드 자체 회귀 방지 — 비-live 중 실 urlopen 이 차단되는지.

    가드가 silent 하게 깨지면(예: monkeypatch 대상 오타) 오프라인 불변식이 무력화되므로,
    가드가 실제로 RuntimeError 를 던지는지 직접 검증한다.
    """
    with pytest.raises(RuntimeError, match="hermetic guard"):
        H.rg.urlreq.urlopen("https://127.0.0.1/redfish/v1/")


# ---------------------------------------------------------------------------
# (선택) 라이브 스모크 — 실행 중 에뮬레이터 필요. 기본 skip (CI 오프라인 유지).
#   활성: SE_EMULATOR_LIVE=1 (host 443 에 에뮬레이터 기동 상태)
#   override: SE_EMULATOR_IP / SE_EMULATOR_USER / SE_EMULATOR_PASS
# ---------------------------------------------------------------------------
import os  # noqa: E402


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("SE_EMULATOR_LIVE") != "1",
    reason="라이브 에뮬레이터 미지정 (SE_EMULATOR_LIVE=1 로 활성)",
)
def test_live_emulator_smoke():
    """실 에뮬레이터 end-to-end 스모크 — 실제 네트워크로 gather 후 hpe 감지."""
    result = H.run_gather(
        H._REAL_GET, H._REAL_GET_NOAUTH,
        ip=os.environ.get("SE_EMULATOR_IP", "127.0.0.1"),
        user=os.environ.get("SE_EMULATOR_USER", "root"),
        pw=os.environ.get("SE_EMULATOR_PASS", "root_password"),
    )
    assert result["vendor"] == "hpe", f"vendor={result['vendor']!r}"
    assert result["status"] in ("success", "partial"), f"status={result['status']}"
    assert result["data"].get("system"), "data.system 비어 있음"
