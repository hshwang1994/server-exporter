"""BIOS Current Attributes — 실장비 캡처 재생 (지시서 13.2, 2026-09-15).

대상: 저장소에 Current Bios 응답이 캡처된 4 Vendor
    Dell PowerEdge R760 ×5 · HPE ProLiant DL380 Gen11 · Lenovo ThinkSystem SR650 V2 ·
    Cisco CIMC 4.1(2g) 장비 1대 (Model=TA-UNODE-G1, BIOS C220M4 계열)
    (`tests/reference/redfish/<vendor>/<host>/` — main 에만 있고 production 브랜치에는 없다 → 없으면 skip)

재생 방식:
    `emulator_harness.run_gather` 로 실제 detect_vendor → _collect_all_sections → _compute_final_status
    를 돌린다. 요청된 path 의 캡처 파일만 그때그때 읽는다(미러 전체 로딩 없음). 캡처에 없는 path 는
    실 BMC 처럼 404 다.
    한계: 파일명으로 그대로 옮길 수 없는 path(예: ':' 가 들어간 Dell BOSS 드라이브 경로)는 캡처
    파일명이 달라 이 로더가 찾지 못하고 404 가 된다. 그래서 Dell 은 storage 가 partial 로 나온다.
    이 영향은 BIOS 유무를 바꾼 두 재생에 똑같이 들어가므로 아래 비교는 BIOS 차이만 본다.

확인하는 것:
    - 선택된 ComputerSystem(Systems.Members[0]) 응답의 `Bios.@odata.id` 로 1회만 조회한다
    - source `Attributes` 와 `data.bios.current.attributes` 가 값·자료형·개수까지 같고 Key 는 이름순이다
      (Dell·HPE 캡처는 장비가 이미 같은 규칙으로 정렬해 줘서 순서도 캡처와 같다. Lenovo·Cisco 는 다르다)
    - 숫자 모양 문자열은 문자열로, `null` / `""` / `0` / `false` 는 누락 없이 남는다
    - Bios 하위 리소스(Settings / Pending / SD / Oem)와 Registry 는 부르지 않는다
      (이 미러에는 그 파일들이 실제로 있어서, 잘못 부르면 응답이 돌아와 버린다)
    - Bios 캡처를 숨긴 재생과 비교해 BIOS 외 결과(status / 섹션 / 다른 data)가 같다

캡처 재생이지 운영 수집 검증이 아니다. 운영 계정 권한·다른 펌웨어는 확인하지 않는다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import emulator_harness as H

rg = H.rg

REPO = Path(__file__).resolve().parents[2]
REFERENCE = REPO / "tests" / "reference" / "redfish"

# (vendor, host, ComputerSystem 캡처, Current Bios 캡처)
CAPTURES = [
    ("dell", "10_100_15_27", "redfish_v1_systems_system.embedded.1.json",
     "redfish_v1_systems_system.embedded.1_bios.json"),
    ("dell", "10_100_15_28", "redfish_v1_systems_system.embedded.1.json",
     "redfish_v1_systems_system.embedded.1_bios.json"),
    ("dell", "10_100_15_31", "redfish_v1_systems_system.embedded.1.json",
     "redfish_v1_systems_system.embedded.1_bios.json"),
    ("dell", "10_100_15_33", "redfish_v1_systems_system.embedded.1.json",
     "redfish_v1_systems_system.embedded.1_bios.json"),
    ("dell", "10_100_15_34", "redfish_v1_systems_system.embedded.1.json",
     "redfish_v1_systems_system.embedded.1_bios.json"),
    ("hpe", "10_50_11_231", "redfish_v1_systems_1.json", "redfish_v1_systems_1_bios.json"),
    ("lenovo", "10_50_11_232", "redfish_v1_systems_1.json", "redfish_v1_systems_1_bios.json"),
    ("cisco", "10_100_15_2", "redfish_v1_systems_fch2116v1v0.json",
     "redfish_v1_systems_fch2116v1v0_bios.json"),
]

_NUMERIC_TEXT = re.compile(r"^-?\d+(\.\d+)?$")
_MISS = (404, {}, "HTTP 404: Not Found")
_FILE_CACHE: dict[Path, dict] = {}


def _read(path: Path) -> dict:
    if path not in _FILE_CACHE:
        _FILE_CACHE[path] = json.loads(path.read_text(encoding="utf-8"))
    return _FILE_CACHE[path]


class _MirrorBMC:
    """캡처 폴더를 BMC 처럼 응답한다. 파일명은 `redfish_v1_<path 소문자, '/'→'_'>.json` 규칙이다."""

    def __init__(self, host_dir: Path, hidden: tuple[str, ...] = ()):
        self.host_dir = host_dir
        self.hidden = {h.lower() for h in hidden}
        self.calls: list[str] = []

    def _lookup(self, path: str):
        key = (path or "").strip("/")
        if key.lower() in self.hidden:
            return _MISS
        name = "redfish_v1" + ("_" + key.lower().replace("/", "_") if key else "") + ".json"
        file = self.host_dir / name
        if not file.is_file():
            return _MISS
        doc = _read(file)
        meta = doc.get("_meta") or {}
        uri = (meta.get("uri") or "").strip("/")
        # 파일명 규칙이 겹치는 다른 URI 를 잘못 돌려주지 않게 원래 URI 로 한 번 더 확인한다
        if key and rg._p(uri).lower() != key.lower():
            return _MISS
        code = int(meta.get("code") or 200)
        return code, doc.get("_data"), (None if code == 200 else f"HTTP {code}")

    def get(self, bmc_ip, path, username, password, timeout, verify_ssl):
        self.calls.append(path)
        return self._lookup(path)

    def noauth(self, bmc_ip, path, timeout, verify_ssl):
        return self._lookup(path)


def _replay(host_dir: Path, hidden: tuple[str, ...] = ()):
    bmc = _MirrorBMC(host_dir, hidden)
    result = H.run_gather(bmc.get, bmc.noauth, realm_impl=lambda *a, **k: None)
    return result, bmc.calls


def _type_tree(value):
    if isinstance(value, dict):
        return {k: _type_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_type_tree(v) for v in value]
    return type(value).__name__


def _special_keys(attrs: dict) -> dict[str, list[str]]:
    """값 종류별 Key 목록. 순서는 test_attributes_equal_the_capture_exactly 가 따로 본다."""
    return {
        "null": sorted(k for k, v in attrs.items() if v is None),
        "empty": sorted(k for k, v in attrs.items() if v == "" and isinstance(v, str)),
        "zero": sorted(k for k, v in attrs.items() if v == 0 and type(v) is int),
        "false": sorted(k for k, v in attrs.items() if v is False),
        "numeric_text": sorted(k for k, v in attrs.items() if isinstance(v, str) and _NUMERIC_TEXT.match(v)),
    }


@pytest.fixture(scope="module", params=CAPTURES, ids=[f"{v}-{h}" for v, h, _, _ in CAPTURES])
def capture(request):
    vendor, host, system_file, bios_file = request.param
    host_dir = REFERENCE / vendor / host
    if not (host_dir / system_file).is_file() or not (host_dir / bios_file).is_file():
        pytest.skip(f"실캡처 없음: {vendor}/{host} (production 브랜치에는 tests/reference 가 없다)")
    system_doc = _read(host_dir / system_file)
    bios_doc = _read(host_dir / bios_file)
    link = system_doc["_data"]["Bios"]["@odata.id"]
    system_path = rg._p(system_doc["_meta"]["uri"])
    bios_path = rg._p(link)
    result, calls = _replay(host_dir)
    hidden_result, hidden_calls = _replay(host_dir, hidden=(bios_path,))
    return {
        "vendor": vendor, "host_dir": host_dir, "system_path": system_path, "link": link,
        "bios_path": bios_path, "source": bios_doc["_data"]["Attributes"],
        "source_type": bios_doc["_data"].get("@odata.type"),
        "result": result, "calls": calls,
        "hidden_result": hidden_result, "hidden_calls": hidden_calls,
    }


@pytest.mark.integration
class TestBiosRealCaptureReplay:

    def test_capture_is_a_standard_current_bios(self, capture):
        assert capture["source_type"].startswith("#Bios."), capture["source_type"]
        assert isinstance(capture["source"], dict) and capture["source"]

    def test_selected_system_bios_link_is_requested_once(self, capture):
        calls = capture["calls"]
        assert capture["system_path"] in calls, "선택된 ComputerSystem 을 수집하지 않았다"
        prefix = capture["system_path"].lower() + "/bios"
        bios_requests = [c for c in calls if c.lower() == prefix or c.lower().startswith(prefix + "/")]
        assert bios_requests == [capture["bios_path"]], bios_requests

    def test_forbidden_bios_resources_are_not_requested(self, capture):
        sub = capture["bios_path"].lower() + "/"
        forbidden = [c for c in capture["calls"] if c.lower().startswith(sub) or "registr" in c.lower()]
        assert forbidden == []

    def test_attributes_equal_the_capture_exactly(self, capture):
        source = capture["source"]
        got = capture["result"]["data"]["bios"]["current"]["attributes"]
        assert len(got) == len(source)
        assert list(got) == sorted(source)
        assert _type_tree(got) == _type_tree(source)
        assert got == source
        final = json.loads(json.dumps(capture["result"]["data"]["bios"], ensure_ascii=False))
        assert final["current"]["attributes"] == source
        assert list(final["current"]["attributes"]) == sorted(source)
        assert _type_tree(final["current"]["attributes"]) == _type_tree(source)

    def test_sorting_changes_order_only_where_the_device_did_not_sort(self, capture):
        """정렬 규칙을 고른 근거 — Dell·HPE BMC 는 이미 대소문자 구분 이름순으로 준다.

        그래서 두 Vendor 출력 순서는 정렬 전과 같고, 순서가 제각각인 Lenovo·Cisco 만 달라진다.
        """
        source = capture["source"]
        got = capture["result"]["data"]["bios"]["current"]["attributes"]
        if capture["vendor"] in ("dell", "hpe"):
            assert list(got) == list(source)
        else:
            assert list(got) != list(source)

    def test_special_values_are_kept(self, capture):
        got = capture["result"]["data"]["bios"]["current"]["attributes"]
        assert _special_keys(got) == _special_keys(capture["source"])
        for key in _special_keys(capture["source"])["numeric_text"]:
            assert isinstance(got[key], str), f"숫자 모양 문자열이 숫자로 바뀌었다: {key}"

    def test_bios_does_not_change_other_results(self, capture):
        result, hidden = capture["result"], capture["hidden_result"]
        assert hidden["data"]["bios"] == {"current": {"attributes": None}}
        for key in ("vendor", "status", "collected", "failed_sections", "unsupported_sections",
                    "multi_node", "probe_facts", "error_count"):
            assert result[key] == hidden[key], key
        assert {k: v for k, v in result["data"].items() if k != "bios"} == \
               {k: v for k, v in hidden["data"].items() if k != "bios"}
        assert capture["calls"] == capture["hidden_calls"], "BIOS 응답 유무와 무관하게 요청 목록이 같다"
        assert "bios" not in result["collected"] + result["failed_sections"] + result["unsupported_sections"]


def test_cisco_numeric_looking_strings_stay_strings():
    """Cisco 캡처는 Attribute 가 전부 문자열이다 (BaudRate "115200" 같은 숫자 모양 포함)."""
    host_dir = REFERENCE / "cisco" / "10_100_15_2"
    bios_file = host_dir / "redfish_v1_systems_fch2116v1v0_bios.json"
    if not bios_file.is_file():
        pytest.skip("Cisco 실캡처 없음")
    result, _calls = _replay(host_dir)
    got = result["data"]["bios"]["current"]["attributes"]
    assert got["BaudRate"] == "115200" and isinstance(got["BaudRate"], str)
    assert all(isinstance(v, str) for v in got.values())
