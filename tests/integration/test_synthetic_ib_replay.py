"""합성 InfiniBand 모드 fixture 재생 (2026-10-17 InfiniBand 전면 검증) — 실장비 아님.

tests/fixtures/redfish/synthetic_ib_mode/ 는 hpe_emulator_dl380a 캡처에서 카드 DE081000 의 4개 리소스만 IB 모드로 편집한
합성 recording 이다 (그 README 에 편집 내용과 기대값 도출 근거). 여기서는 detect_vendor → _collect_all_sections 전체 경로를
돌려 다음을 고정한다.

  1. data.network_adapters 가 **손으로 쓴** expected_network_adapters.json 과 같다 (코드 출력 스냅샷이 아니다).
  2. 나머지 섹션 · vendor · status · collected · error_count 는 원본 에뮬레이터 golden 과 같다 (편집하지 않은 102개 응답).
  3. notices / errors 없음 — 포트와 기능의 현재 모드가 일치하는 정상 IB 카드는 충돌이 아니다.
  4. 읽는 리소스 집합이 원본과 같다 — IB 경로가 새 HTTP 요청을 만들지 않는다.

hpe_emulator_* / real_* / dmtf_* glob 은 건드리지 않는다. tests/integration/test_port_classification_invariants.py 는 폴더를
전수 스캔하므로 이 fixture 도 자동으로 불변식(INV-3: infiniband[] 항목이 매핑된 포트는 InfiniBand) 검사를 받는다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import emulator_harness as H

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "redfish"
SYNTH = FIXTURE_ROOT / "synthetic_ib_mode"
PARENT = FIXTURE_ROOT / "hpe_emulator_dl380a"
EDITED = {
    "get::Chassis/1/NetworkAdapters/DE081000/NetworkDeviceFunctions/0",
    "get::Chassis/1/NetworkAdapters/DE081000/NetworkDeviceFunctions/1",
    "get::Chassis/1/NetworkAdapters/DE081000/Ports/0",
    "get::Chassis/1/NetworkAdapters/DE081000/Ports/1",
}

pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not (SYNTH / "recording.json").is_file(), reason="synthetic_ib_mode fixture 없음")]


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _norm(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False, sort_keys=True))


def _replay(recording):
    """재생 + 읽은 경로 집합."""
    seen = set()
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)

    def tracking_get(bmc_ip, path, username, password, timeout, verify_ssl):
        seen.add(path)
        return get_impl(bmc_ip, path, username, password, timeout, verify_ssl)

    result = H.run_gather(tracking_get, noauth_impl, realm_impl=realm_impl)
    return result, seen


@pytest.fixture(scope="module")
def synth():
    rec = _load(SYNTH / "recording.json")
    result, seen = _replay(rec)
    notices = [n for n in H.rg.notices() if n["section"] == "network_adapters"]
    return {"rec": rec, "result": result, "seen": seen, "notices": notices}


@pytest.fixture(scope="module")
def parent():
    rec = _load(PARENT / "recording.json")
    result, seen = _replay(rec)
    return {"rec": rec, "result": result, "seen": seen, "golden": _load(PARENT / "expected_output.json")}


def test_only_four_resources_differ_from_parent_recording(synth, parent):
    diff = {k for k in set(synth["rec"]) | set(parent["rec"]) if synth["rec"].get(k) != parent["rec"].get(k)}
    assert diff == EDITED, diff


def test_synthetic_ib_mode_network_adapters_match_handwritten_expectation(synth):
    expected = _load(SYNTH / "expected_network_adapters.json")
    got = synth["result"]["data"]["network_adapters"]
    for key in ("adapters", "ports", "fc_hbas", "infiniband"):
        assert _norm(got[key]) == expected[key], f"network_adapters.{key} 가 손으로 정한 기대값과 다르다"
    assert set(got) == set(expected)


def test_synthetic_ib_mode_has_no_notices_or_errors(synth):
    assert synth["notices"] == []
    assert synth["result"]["error_count"] == 0
    assert synth["result"]["status"] == "success"


def test_synthetic_ib_mode_other_sections_equal_parent_emulator_golden(synth, parent):
    golden = parent["golden"]
    for key in H.GOLDEN_KEYS:
        if key == "data":
            continue
        assert _norm(synth["result"][key]) == golden[key], key
    got = {k: v for k, v in synth["result"]["data"].items() if k != "network_adapters"}
    exp = {k: v for k, v in golden["data"].items() if k != "network_adapters"}
    assert _norm(got) == exp, "IB 편집이 다른 섹션에 번졌다"


def test_synthetic_ib_mode_request_set_equals_parent(synth, parent):
    assert synth["seen"] == parent["seen"], "IB 경로가 새 HTTP 요청을 만들었다"


def test_synthetic_entries_satisfy_common_contract(synth):
    for e in synth["result"]["data"]["network_adapters"]["infiniband"]:
        assert e["source"] == "redfish" and e["link_status"] in ("up", "down", "unknown")
        assert e["rate"] is None and (e["rate_gbps"] is None or isinstance(e["rate_gbps"], (int, float)))
        for g in (e["node_guid"], e["port_guid"]):
            assert g is None or (len(g) == 19 and g == g.lower() and g.count(":") == 3)
        assert e["model"] == e["adapter_model"]
