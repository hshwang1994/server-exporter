"""Redfish 파싱 엔진 fault-injection 회귀 (mutation 기반).

목적:
    record/replay 공용 모듈은 정상 응답을 golden 으로 고정만 했다. 본 테스트는
    그 recording 을 **변형**(mutation.py)해 redfish_gather.py 엔진에 신뢰 불가 입력을 주입하고,
    엔진이 **크래시 없이 graceful degrade** 함을 증명한다 — 시뮬레이터/mock 으로 gathering
    로직을 실제로 견고하게 만드는 도구.

구성:
    - pointer 헬퍼 단위 검증 (RFC-6901)
    - transparency: no-op mutation == golden (레이어 투명성 — golden 불간섭 불변식 증명)
    - identity: mutate_recording 후 원본 recording 불변
    - assert_graceful: 모든 변형 결과의 공통 불변식 (예외 0 + envelope shape + status enum)
    - single-node graceful degradation: 단일 노드 수집 경로(gather_processors/memory 등)가
      오염 입력에서 섹션을 비우/실패시킬 뿐 크래시하지 않음을 고정

오프라인 보장: recording 변형은 전부 메모리에서, 네트워크 호출 0 (conftest hermetic 가드 적용).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import emulator_harness as H
import mutation as M

rg = H.rg
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "redfish"


# ---------------------------------------------------------------------------
# fixture 수집 (golden 동반 hpe_emulator_* — test_hpe_emulator_replay 와 동일 규칙)
# ---------------------------------------------------------------------------
def _discover():
    dirs = []
    for d in sorted(FIXTURE_ROOT.glob("hpe_emulator_*")):
        if (d / "recording.json").is_file() and (d / "expected_output.json").is_file():
            dirs.append(d)
    return dirs


CASES = _discover()
CASE_IDS = [d.name for d in CASES]
# 알려진 path 가 풍부한 기준 fixture (단일 노드 타깃 변형용).
PRIMARY = "hpe_emulator_dl360"


def _load(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _json_norm(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False, sort_keys=True))


def _recording(name: str):
    return _load(FIXTURE_ROOT / name / "recording.json")


def _run(recording, mutations):
    get_i, noauth_i, realm_i = M.make_mutated_replayer(recording, mutations)
    return H.run_gather(get_i, noauth_i, realm_impl=realm_i)


# ---------------------------------------------------------------------------
# 공통 불변식
# ---------------------------------------------------------------------------
def assert_graceful(result):
    """모든 변형 입력에서 보장돼야 하는 최소 불변식.

    1. 예외 미발생 — 이 줄에 도달했다는 것 자체가 run_gather 가 raise 안 했다는 뜻.
    2. envelope shape 온전 — GOLDEN_KEYS 전부 존재 + 컨테이너 타입 정상.
    3. 종료 status 가 알려진 값 (crash sentinel 아님).
    4. 섹션이 unsupported/failed 로 이중 분류되지 않음.
    """
    for key in H.GOLDEN_KEYS:
        assert key in result, f"envelope 키 누락: {key}"
    assert isinstance(result["data"], dict)
    assert isinstance(result["collected"], list)
    assert isinstance(result["failed_sections"], list)
    assert isinstance(result["unsupported_sections"], list)
    assert result["status"] in ("success", "partial", "failed"), result["status"]
    assert not (set(result["unsupported_sections"]) & set(result["failed_sections"])), \
        "섹션이 unsupported∩failed 이중 분류"


# ---------------------------------------------------------------------------
# 1) RFC-6901 pointer 헬퍼 단위 검증
# ---------------------------------------------------------------------------
def test_pointer_get_set_delete_roundtrip():
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}, "x~y": 9, "p/q": 8}
    assert M._pointer_get(data, "/a/b/0/c") == 1
    assert M._pointer_get(data, "/a/b/1/c") == 2
    # RFC-6901 escaping: ~0 == '~', ~1 == '/'
    assert M._pointer_get(data, "/x~0y") == 9
    assert M._pointer_get(data, "/p~1q") == 8
    # set
    M._pointer_set(data, "/a/b/0/c", 99)
    assert data["a"]["b"][0]["c"] == 99
    # delete
    M._pointer_delete(data, "/a/b/1/c")
    assert "c" not in data["a"]["b"][1]
    # 빈 pointer = 전체 치환
    assert M._pointer_set({"q": 1}, "", {"r": 2}) == {"r": 2}


def test_mutation_unknown_target_raises():
    """존재하지 않는 path 타깃은 조용한 no-op 이 아니라 명확한 실패 (거짓 green 방지)."""
    rec = {"get::Systems/1": [200, {"X": 1}, None]}
    with pytest.raises(KeyError):
        M.mutate_recording(rec, [{"op": "null_field", "channel": "get",
                                   "path": "Nope/1", "pointer": "/X"}])


# ---------------------------------------------------------------------------
# 2) transparency — no-op mutation == golden (golden 불간섭 불변식)
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.skipif(not CASES, reason="hpe_emulator_* fixture 없음")
@pytest.mark.parametrize("case_dir", CASES, ids=CASE_IDS)
def test_noop_mutation_matches_golden(case_dir):
    """빈 mutation 리스트 → golden 과 byte 동치. mutation 레이어가 투명함을 증명."""
    recording = _load(case_dir / "recording.json")
    golden = _load(case_dir / "expected_output.json")
    result = _run(recording, [])
    for key in H.GOLDEN_KEYS:
        assert _json_norm(result[key]) == golden[key], (
            f"{case_dir.name}: no-op 변형이 golden 을 바꿈 (레이어 비투명) — '{key}'"
        )


# ---------------------------------------------------------------------------
# 3) identity — 원본 recording 불변 (불변식 2)
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.skipif(not CASES, reason="hpe_emulator_* fixture 없음")
def test_mutate_recording_does_not_touch_original():
    recording = _recording(PRIMARY)
    snapshot = json.dumps(recording, sort_keys=True, ensure_ascii=False)
    M.mutate_recording(recording, [
        {"op": "set_value", "channel": "get",
         "path": "Systems/1/Processors/1", "pointer": "/TotalCores", "value": "X"},
        {"op": "drop_collection", "channel": "get", "path": "Systems/1/Memory"},
        {"op": "http_status", "channel": "get", "path": "Systems/1/Storage", "status": 500},
    ])
    assert json.dumps(recording, sort_keys=True, ensure_ascii=False) == snapshot, \
        "mutate_recording 이 원본을 변경함 (deep-copy 위반)"


# ---------------------------------------------------------------------------
# 4) single-node graceful degradation (기준 fixture dl360, 알려진 path)
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.skipif(PRIMARY not in CASE_IDS, reason=f"{PRIMARY} fixture 없음")
class TestSingleNodeDegradation:
    """단일 노드 수집 경로가 오염 입력에서 crash 없이 degrade 하는지 (회귀 안전망)."""

    def setup_method(self):
        self.rec = _recording(PRIMARY)

    def test_processor_wrong_type_total_cores(self):
        """CPU TotalCores 가 문자열 → gather_processors(_safe_int) 가 graceful."""
        result = _run(self.rec, [{"op": "set_type", "channel": "get",
                                  "path": "Systems/1/Processors/1",
                                  "pointer": "/TotalCores", "to": "string"}])
        assert_graceful(result)

    def test_processor_null_model(self):
        result = _run(self.rec, [{"op": "null_field", "channel": "get",
                                  "path": "Systems/1/Processors/1", "pointer": "/Model"}])
        assert_graceful(result)

    def test_memory_collection_dropped(self):
        """Memory Members 가 빈 컬렉션 → memory 섹션 degrade, crash 없음."""
        result = _run(self.rec, [{"op": "drop_collection", "channel": "get",
                                  "path": "Systems/1/Memory"}])
        assert_graceful(result)

    def test_memory_collection_http_500(self):
        """Memory 컬렉션 5xx → 섹션 실패로 분류되고 envelope 온전."""
        result = _run(self.rec, [{"op": "http_status", "channel": "get",
                                  "path": "Systems/1/Memory", "status": 500}])
        assert_graceful(result)

    def test_processors_member_null_injected(self):
        """Processors Members 에 [null, ...] → 첫 멤버 None 안전 처리."""
        result = _run(self.rec, [{"op": "inject_member_null", "channel": "get",
                                  "path": "Systems/1/Processors"}])
        assert_graceful(result)


# ---------------------------------------------------------------------------
# 5) @odata.id 오염 / 수집 중 5xx (silent-loss 가드)
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.skipif(PRIMARY not in CASE_IDS, reason=f"{PRIMARY} fixture 없음")
class TestSilentLoss:
    """비-str @odata.id, 부분 5xx 등 — crash 없이 degrade."""

    def setup_method(self):
        self.rec = _recording(PRIMARY)

    # 정상 dl360 firmware 멤버 수 (1개 멤버 오염이 전체를 날리지 않음을 검증할 기준).
    _FW_FLOOR = 20  # 정상 23 — 1개 오염돼도 나머지는 보존돼야 (>= 20)

    def test_firmware_member_corrupt_odata_id(self):
        """firmware Member 의 @odata.id 가 비-str(dict) → 1개 오염이 섹션 전체 손실 유발 금지.

        가드 전: _p(dict)(uri.lstrip) AttributeError → 섹션 runner 가 catch → firmware
        섹션 **전체**(23건) 가 failed 로 날아감(silent total-section loss). 가드 후: 오염
        멤버만 건너뛰고 나머지는 수집.
        """
        result = _run(self.rec, [{"op": "corrupt_odata_id", "channel": "get",
                                  "path": "UpdateService/FirmwareInventory",
                                  "pointer": "/Members/0/@odata.id"}])
        assert_graceful(result)
        fw = result["data"].get("firmware") or []
        assert len(fw) >= self._FW_FLOOR, (
            f"1개 멤버 @odata.id 오염이 firmware 섹션 전체 손실 유발 (len={len(fw)})"
        )

    def test_firmware_member_numeric_odata_id(self):
        """@odata.id 가 숫자(int) 인 변종 → 역시 섹션 보존."""
        result = _run(self.rec, [{"op": "set_value", "channel": "get",
                                  "path": "UpdateService/FirmwareInventory",
                                  "pointer": "/Members/0/@odata.id", "value": 12345}])
        assert_graceful(result)
        fw = result["data"].get("firmware") or []
        assert len(fw) >= self._FW_FLOOR, f"숫자 @odata.id 오염이 firmware 전체 손실 (len={len(fw)})"

    def test_storage_collection_http_500_not_silent_success(self):
        """Storage 컬렉션 5xx → 섹션이 silent success 로 위장되지 않음 (degradation-lock).

        storage 가 collected 로 분류되면 data.storage 가 실제 내용을 가져야 하고,
        실패면 failed/unsupported 로 가야 한다 — 빈 채로 success 위장 금지.
        """
        result = _run(self.rec, [{"op": "http_status", "channel": "get",
                                  "path": "Systems/1/Storage", "status": 500}])
        assert_graceful(result)
        # storage 가 '성공 수집' 으로 남았다면 실제 controllers 데이터가 있어야 함
        if "storage" in result["collected"]:
            storage = result["data"].get("storage") or {}
            assert storage.get("controllers"), \
                "storage 5xx 인데 collected 로 분류 + 내용 비어있음 (silent success 위장)"


# ---------------------------------------------------------------------------
# 6) 무경계 collection 순회 상한 (DoS / huge-payload)
# ---------------------------------------------------------------------------
@pytest.mark.integration
@pytest.mark.skipif(PRIMARY not in CASE_IDS, reason=f"{PRIMARY} fixture 없음")
class TestBounds:
    """수천 멤버 collection → 멤버당 _get N회로 hang. 상한으로 절단됨을 검증."""

    def setup_method(self):
        self.rec = _recording(PRIMARY)

    def test_firmware_huge_member_list_capped(self):
        """firmware Members 5000개 주입 → 상한 이하로 절단 (무경계 순회 hang 방어).

        가드 전: 5000 멤버 전부 순회(멤버당 _get) → firmware 5000건. 가드 후: cap 이하.
        """
        cap = rg.MAX_COLLECTION_MEMBERS
        result = _run(self.rec, [{"op": "inject_huge_list", "channel": "get",
                                  "path": "UpdateService/FirmwareInventory",
                                  "pointer": "/Members", "count": cap + 4000}])
        assert_graceful(result)
        fw = result["data"].get("firmware") or []
        assert len(fw) <= cap, f"firmware 무경계 순회 미차단 (len={len(fw)} > cap={cap})"

    def test_wellformed_firmware_not_truncated(self):
        """정상 23 멤버는 절단되지 않음 (상한이 정상 입력을 건드리지 않음 — golden 불변)."""
        result = _run(self.rec, [])
        fw = result["data"].get("firmware") or []
        assert 0 < len(fw) <= rg.MAX_COLLECTION_MEMBERS
