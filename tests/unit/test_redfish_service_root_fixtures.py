"""Phase 4-A: 저장소의 전 Redfish ServiceRoot fixture 가 새 판정식을 통과하는지.

Protocol Detection 강화의 가장 큰 운영 위험은 **정상 vendor 가 protocol 실패로 바뀌는
회귀**다. 저장소에 실제로 존재하는 ServiceRoot 응답을 전수로 돌려 그 회귀를 고정한다.

대상 (2026-08-10 실측 38개)
  - tests/fixtures/redfish/*/service_root.json                 28개
  - tests/fixtures/redfish/*/recording.json 의 `noauth::` 응답  10개
    (DMTF 표준 mockup 1 + HPE 에뮬레이터 5 + 실장비 캡처 4)

fixture 가 없는 vendor 는 여기서 "검증 완료" 라고 말하지 않는다 — 목록에 나타나지 않을 뿐이다.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "common" / "library"))

_b = types.ModuleType("ansible.module_utils.basic")
_b.AnsibleModule = object
_m = types.ModuleType("ansible.module_utils")
_m.basic = _b
_a = types.ModuleType("ansible")
_a.module_utils = _m
sys.modules.setdefault("ansible", _a)
sys.modules.setdefault("ansible.module_utils", _m)
sys.modules.setdefault("ansible.module_utils.basic", _b)

import precheck_bundle as pb  # noqa: E402

FIXTURE_DIR = REPO / "tests/fixtures/redfish"


def _service_root_files():
    return sorted(FIXTURE_DIR.glob("*/service_root.json"))


def _recording_files():
    return sorted(FIXTURE_DIR.glob("*/recording.json"))


def _label(path: Path) -> str:
    return path.parent.name


@pytest.mark.parametrize("path", _service_root_files(), ids=_label)
def test_vendor_service_root_fixture_accepted(path):
    """vendor ServiceRoot fixture 는 전부 Redfish 로 판정돼야 한다."""
    body = json.loads(path.read_text(encoding="utf-8"))
    ok, facts, why = pb.parse_service_root(body)
    assert ok is True, "{0} 회귀: {1}".format(_label(path), why)
    assert facts["redfish_version"], "{0}: RedfishVersion 추출 실패".format(_label(path))


@pytest.mark.parametrize("path", _recording_files(), ids=_label)
def test_unauthenticated_service_root_recording_accepted(path):
    """비인증(`noauth::`) ServiceRoot 캡처도 전부 통과해야 한다."""
    entry = json.loads(path.read_text(encoding="utf-8")).get("noauth::")
    assert isinstance(entry, list) and len(entry) >= 2, (
        "{0}: noauth:: 캡처 형식이 [status, body] 가 아니다".format(_label(path))
    )
    status, body = entry[0], entry[1]
    assert status == 200, (
        "{0}: 비인증 ServiceRoot 가 200 이 아니다 (status={1}). "
        "ServiceRoot 에서 인증을 요구하는 vendor 가 생겼다면 판정식 재검토 필요".format(
            _label(path), status)
    )
    ok, facts, why = pb.parse_service_root(body)
    assert ok is True, "{0} 회귀: {1}".format(_label(path), why)
    assert facts["redfish_version"], _label(path)


def test_fixture_coverage_is_not_silently_zero():
    """fixture 가 사라지면 '전수 통과' 가 공허해진다 — 개수 자체를 고정한다."""
    assert len(_service_root_files()) >= 28, "service_root.json fixture 수 감소"
    assert len(_recording_files()) >= 10, "recording.json fixture 수 감소"


def test_no_repo_fixture_requires_auth_at_service_root():
    """§7 근거 — 저장소 안에 ServiceRoot 에서 인증을 요구하는 캡처가 있는지.

    종전 코드는 "일부 BMC 가 무인증 ServiceRoot 에 401 을 던진다" 를 근거로 401/403 을
    성공 처리했다. 그 주장을 뒷받침하는 캡처가 실제로 생기면 이 테스트가 실패하고,
    그때 판정식을 재검토해야 한다.
    """
    non_200 = []
    for path in _recording_files():
        entry = json.loads(path.read_text(encoding="utf-8")).get("noauth::")
        if isinstance(entry, list) and entry and entry[0] != 200:
            non_200.append((_label(path), entry[0]))
    assert not non_200, (
        "ServiceRoot 에서 비-200 을 반환하는 캡처가 생겼다. "
        "Phase 4-A 판정식(본문 기반)이 이 vendor 를 차단하므로 재검토 필요: {0}".format(non_200)
    )
