"""Dell 서버 대표 시리얼 = ServiceRoot.Oem.Dell.ServiceTag (2026-08-11 Dell 1차 교정 · 2026-11-09 실패 판정 이관).

사용자 결정 (2026-08-11):
  - Dell 대표 시리얼 원천은 ServiceRoot.Oem.Dell.ServiceTag **단 하나**.
  - ComputerSystem.SerialNumber / System.SKU / DellSystem.ChassisServiceTag /
    DellSystem.NodeID / BIOS SystemServiceTag 로 **폴백하지 않는다**.
사용자 결정 (2026-11-09 결정 2 — 종전 "확보 못 하면 모듈이 수집을 실패시킨다(data={})" 를 대체):
  - Service Tag 를 확보하지 못해도 모듈은 수집을 버리지 않는다. 대표 시리얼은 None 이고 사유는 notice 1건이다.
    errors[] 에는 아무것도 더하지 않는다 — 더하면 "서버 기본 정보" 실패 행이 생겨 Serial 행과 같은 사건을 두 번 말한다.
  - host 를 failed 로 내는 판정은 채널 공통 필수 식별자 규칙(common/tasks/normalize/require_serial.yml — 상태 시나리오 E)이
    봉투 층에서 한다. 그 판정은 tests/unit/test_status_serial_required_scenario_e.py 와 Tier 1 미러 재생이 검증한다.

배경: Dell iDRAC 의 ComputerSystem.SerialNumber 는 보드 제조 시리얼(`CNIVC…`)이라
SMBIOS Type 1 System Serial 과 다르다. 동일 R760 실측에서 Redfish=CNIVC0048R0159,
Linux(/sys/class/dmi/id/product_serial)=GSBPK54 로 채널 간 매칭이 깨졌다
(docs/ai/contracts/serial-number.md §19).

실행 층: 대표 시리얼 확정은 main() 층 책임이라 `emulator_harness.run_gather`
(= main() gather 흐름 1:1 미러) 로 구동한다. gather_system 단독 호출은 대상이 아니다.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "integration"))

import emulator_harness as H  # noqa: E402

rg = H.rg
FIXTURE_ROOT = REPO / "tests" / "fixtures" / "redfish"

# 폴백 금지 실증용 — Dell fixture 가 실제로 갖고 있는 "다른 시리얼 후보" 값들.
DECOY_SERIAL = "CNIVC0048R0159"   # ComputerSystem.SerialNumber (보드 제조 시리얼)
DECOY_SKU = "SKU64CXJ54"          # System.SKU
DECOY_CHASSIS_TAG = "CST64CXJ54"  # Oem.Dell.DellSystem.ChassisServiceTag
DECOY_NODE_ID = "NID64CXJ54"      # Oem.Dell.DellSystem.NodeID
DECOYS = (DECOY_SERIAL, DECOY_SKU, DECOY_CHASSIS_TAG, DECOY_NODE_ID)

SERVICE_TAG = "GSBPK54"

# resolver 실패 사유에 들어 있는 원천 이름 — 대표 시리얼 notice 를 다른 system notice 와 가른다
SERIAL_NOTICE_TOKEN = "ServiceRoot.Oem.Dell.ServiceTag"


# ── 합성 Dell BMC ────────────────────────────────────────────────────────────

def _service_root(service_tag=SERVICE_TAG):
    root = {
        "@odata.id": "/redfish/v1",
        "Product": "Integrated Dell Remote Access Controller",
        "Systems": {"@odata.id": "/redfish/v1/Systems"},
        "Managers": {"@odata.id": "/redfish/v1/Managers"},
        "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
    }
    if service_tag is not _ABSENT:
        root["Oem"] = {"Dell": {"ServiceTag": service_tag}}
    return root


class _Absent(object):
    def __repr__(self):
        return "<absent>"


_ABSENT = _Absent()

_SYSTEM_BODY = {
    "@odata.id": "/redfish/v1/Systems/System.Embedded.1",
    "Manufacturer": "Dell Inc.",
    "Model": "PowerEdge R760",
    "SerialNumber": DECOY_SERIAL,
    "SKU": DECOY_SKU,
    "UUID": "4c4c4544-0053-4210-8050-c7c04f4b3534",
    "PowerState": "On",
    "Status": {"State": "Enabled", "Health": "OK"},
    "Oem": {"Dell": {"DellSystem": {
        "ChassisServiceTag": DECOY_CHASSIS_TAG,
        "NodeID": DECOY_NODE_ID,
    }}},
}


class _FakeBmc(object):
    """무인증/인증 ServiceRoot 를 따로 줄 수 있는 합성 Dell BMC.

    noauth_root / auth_root 를 분리해 "무인증 200 이지만 OEM 블록만 없음" 펌웨어를 재현한다.
    """

    def __init__(self, noauth_root, auth_root, system_status=200):
        self.noauth_root = noauth_root
        self.auth_root = auth_root
        self.system_status = system_status
        self.auth_root_gets = 0     # 인증 ServiceRoot GET 횟수 (재조회 계측)

    def get(self, ip, path, user, pw, timeout, verify_ssl):
        if path == "":
            self.auth_root_gets += 1
            if self.auth_root is None:
                return 401, {}, "HTTP 401: Unauthorized"
            return 200, copy.deepcopy(self.auth_root), None
        if path == "Systems":
            return 200, {"Members": [{"@odata.id": _SYSTEM_BODY["@odata.id"]}]}, None
        if path == "Systems/System.Embedded.1":
            if self.system_status != 200:
                return self.system_status, {}, "HTTP %d: Server Error" % self.system_status
            return 200, copy.deepcopy(_SYSTEM_BODY), None
        if path == "Systems/System.Embedded.1/Processors":
            return 200, {"Members": [{"@odata.id":
                         "/redfish/v1/Systems/System.Embedded.1/Processors/CPU.1"}]}, None
        if path == "Systems/System.Embedded.1/Processors/CPU.1":
            return 200, {"Id": "CPU.1", "Manufacturer": "Intel", "Model": "Xeon Gold",
                         "TotalCores": 16, "TotalThreads": 32, "MaxSpeedMHz": 3000,
                         "Status": {"State": "Enabled", "Health": "OK"}}, None
        if path in ("Managers", "Chassis"):
            return 200, {"Members": []}, None
        return 404, {}, "HTTP 404: Not Found"

    def noauth(self, ip, path, timeout, verify_ssl):
        if path == "":
            if self.noauth_root is None:
                return 401, {}, "HTTP 401: Unauthorized"
            return 200, copy.deepcopy(self.noauth_root), None
        return 401, {}, "HTTP 401: Unauthorized"


def _with_notices(result):
    """notices 는 모듈 전역 누적이고 run_gather 진입 시 초기화된다 — 이 실행의 notice 를 곧바로 결과에 붙여 둔다."""
    result["_notices"] = rg.notices()
    return result


def _run_fake(bmc, vendor_user="u"):
    return _with_notices(H.run_gather(bmc.get, bmc.noauth, realm_impl=lambda *a, **k: None,
                                      user=vendor_user))


# ── 실 fixture 디렉터리 재생 ─────────────────────────────────────────────────

def _recording_from_dir(name):
    """raw fixture 디렉터리(*.json) → make_replayer 호환 recording + service_root."""
    recording, service_root = {}, None
    for path in sorted((FIXTURE_ROOT / name).glob("*.json")):
        with open(path, encoding="utf-8") as fh:
            body = json.load(fh)
        oid = body.get("@odata.id")
        if not oid:
            continue
        if oid.rstrip("/") == "/redfish/v1":
            service_root = body
            continue
        recording["get::" + rg._p(oid)] = [200, body, None]
    assert service_root is not None, "%s: service_root.json 없음" % name
    recording["noauth::"] = [200, service_root, None]
    recording["get::"] = [200, service_root, None]
    return recording, service_root


def _run_dir(name):
    recording, service_root = _recording_from_dir(name)
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    return _with_notices(H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl)), service_root


def _load_r740_mirror():
    base = FIXTURE_ROOT / "real_dell_r740"
    with open(base / "recording.json", encoding="utf-8") as fh:
        recording = json.load(fh)
    with open(base / "meta.json", encoding="utf-8") as fh:
        layout = json.load(fh).get("manager_layout")
    return recording, layout


def _run_recording(recording, layout):
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    return _with_notices(H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl, manager_layout=layout))


def _serial_of(result):
    return ((result.get("data") or {}).get("system") or {}).get("serial")


def _serial_notices(result):
    return [n for n in result["_notices"] if n["section"] == "system" and SERIAL_NOTICE_TOKEN in n["message"]]


def _data_without_serial(result):
    data = copy.deepcopy(result.get("data") or {})
    system = data.get("system")
    if isinstance(system, dict):
        system.pop("serial", None)
    return data


def _paths_of(obj, needle, path=""):
    """obj 안에서 값이 needle 인 위치 목록 (JSON 경로)."""
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in _paths_of(v, needle, "%s.%s" % (path, k))]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in _paths_of(v, needle, "%s[%d]" % (path, i))]
    return [path] if obj == needle else []


def _reference(system_status=200):
    """같은 합성 BMC 에 정상 Service Tag 를 준 결과 — 비교 기준."""
    root = _service_root()
    return _run_fake(_FakeBmc(noauth_root=root, auth_root=root, system_status=system_status))


# 섹션 결과 · 오류 수 · 식별 근거 — Service Tag 유무로 달라지면 안 되는 키 (GOLDEN_KEYS 에서 data 를 뺀 것)
SAME_KEYS = tuple(k for k in H.GOLDEN_KEYS if k != "data")


def _assert_only_serial_lost(result, ref):
    """Service Tag 를 못 얻은 결과가 정상 Service Tag 결과와 대표 시리얼 하나만 다르다 (2026-11-09 결정 2)."""
    assert result["vendor"] == "dell", "vendor 가 dell 로 식별돼야 의미가 있다 (vacuous pass 차단)"
    assert result["status"] != "failed", "모듈이 수집을 버리지 않는다"
    assert _serial_of(result) is None
    for key in SAME_KEYS:
        assert result[key] == ref[key], "%s 가 정상 Service Tag 결과와 다르다 — 대표 시리얼 관련 모듈 오류 0건이어야 한다" % key
    assert _data_without_serial(result) == _data_without_serial(ref), "대표 시리얼 외 data 는 그대로"
    notes = _serial_notices(result)
    assert len(notes) == 1, "대표 시리얼 사유는 notice 정확히 1건: %r" % (notes,)
    assert _serial_notices(ref) == []


# ── 1~3. ServiceTag 정상 + System 수집 정상 ──────────────────────────────────

@pytest.mark.parametrize("fixture_name", ["dell", "dell_r760"])
def test_serial_is_service_root_service_tag(fixture_name):
    """대표 시리얼이 그 fixture 의 ServiceRoot.Oem.Dell.ServiceTag 와 문자열 일치.

    기대값을 테스트에 하드코딩하지 않고 raw fixture 에서 직접 읽어 비교한다.
    """
    result, service_root = _run_dir(fixture_name)
    expected = rg._safe(service_root, "Oem", "Dell", "ServiceTag")
    assert expected, "%s: fixture 에 ServiceTag 없음 (테스트 전제 붕괴)" % fixture_name
    assert _serial_of(result) == expected
    assert _serial_notices(result) == []


def test_real_dell_r740_mirror_uses_service_tag():
    """실장비 미러(real_dell_r740) 재생 — 보드 시리얼이 아니라 Service Tag."""
    recording, layout = _load_r740_mirror()
    result = _run_recording(recording, layout)
    expected = rg._safe(recording["noauth::"][1], "Oem", "Dell", "ServiceTag")
    assert _serial_of(result) == expected
    assert _serial_of(result) != recording["get::Systems/System.Embedded.1"][1]["SerialNumber"]


def test_real_dell_r740_mirror_without_service_tag_keeps_everything_else():
    """실장비 미러에서 ServiceRoot 의 Service Tag 만 지우면 — 대표 시리얼만 null 이 되고 나머지 결과는 원본과 같다.

    미러에는 인증 ServiceRoot(get::) 기록이 없어 재조회는 404 로 끝난다 (재조회 1회 뒤 포기).
    """
    recording, layout = _load_r740_mirror()
    ref = _run_recording(recording, layout)
    doctored = copy.deepcopy(recording)
    for key in ("noauth::", "get::"):
        if key in doctored:
            ((doctored[key][1].get("Oem") or {}).get("Dell") or {}).pop("ServiceTag", None)
    assert rg._safe(doctored["noauth::"][1], "Oem", "Dell", "ServiceTag") is None, "전제: 태그 제거"
    result = _run_recording(doctored, layout)
    assert ref["status"] == "success" and _serial_of(ref)
    _assert_only_serial_lost(result, ref)
    assert _paths_of(result, recording["get::Systems/System.Embedded.1"][1]["SerialNumber"]) == [], \
        "보드 시리얼이 결과 어디에도 없다"


# ── 4. ServiceTag 정상 + System 수집 실패 ────────────────────────────────────

def test_system_section_failure_keeps_other_sections_and_leaves_serial_null():
    """ServiceTag 는 정상인데 System GET 이 실패한 경우 (종전: data={} 로 failed — 2026-11-09 변경).

    다른 섹션(processors)은 그대로 남고 system 섹션만 실패다. 대표 시리얼을 실을 자리가 없어 null 이며,
    늘어나는 오류는 system 섹션 실패 1건뿐이다 (대표 시리얼 관련 모듈 오류 0건). host 의 failed 판정은 공통 규칙 몫이다.
    """
    ok = _reference(200)
    result = _reference(500)
    assert result["status"] != "failed"
    assert "system" in result["failed_sections"] and "system" not in result["collected"]
    assert "processors" in result["collected"]
    assert result["data"]["processors"] == ok["data"]["processors"], "다른 섹션 데이터 보존"
    assert _serial_of(result) is None
    assert result["error_count"] == ok["error_count"] + 1, "늘어난 오류는 system 섹션 실패 1건뿐"
    assert _serial_notices(result) == [], "Service Tag 는 정상이라 대표 시리얼 notice 없음"


# ── 5. ServiceTag 없음 / 6. invalid ──────────────────────────────────────────

# 주의: Oem 에 다른 벤더 alias 키(예: Hpe)를 넣으면 detect_vendor 가 그 벤더로 식별해
# Dell resolver 자체가 등록되지 않는다. "Dell 인데 Oem.Dell 만 없는" 상황을 재현하려면
# 벤더 alias 가 아닌 중립 키를 써야 한다 (vendor 는 Product 문자열로 dell 로 식별됨).
MISSING_ROOTS = {
    "oem_key_absent": {k: v for k, v in _service_root().items() if k != "Oem"},
    "oem_dell_absent": dict(_service_root(), Oem={"Contoso": {"ServiceTag": "X"}}),
    "service_tag_key_absent": dict(_service_root(), Oem={"Dell": {"IsBranded": 0}}),
    "service_tag_null": dict(_service_root(), Oem={"Dell": {"ServiceTag": None}}),
}

INVALID_TAGS = ["", "   ", "NA", "N/A", "None", "Not Specified",
                "To Be Filled By O.E.M.", "System Serial Number", "0", "00000000"]


def _root_without_oem():
    return {k: v for k, v in _service_root().items() if k != "Oem"}


# Service Tag 를 얻지 못하는 ServiceRoot 전부 (무인증 · 인증 응답이 같다)
UNRESOLVED_ROOTS = dict(
    [("missing:" + k, MISSING_ROOTS[k]) for k in sorted(MISSING_ROOTS)]
    + [("invalid:%r" % b, _service_root(b)) for b in INVALID_TAGS]
)


@pytest.mark.parametrize("system_status", [200, 500])
@pytest.mark.parametrize("case", sorted(UNRESOLVED_ROOTS))
def test_unresolved_service_tag_keeps_the_collection(case, system_status):
    """Service Tag 없음 / 무효값 — 결과는 정상 Service Tag 와 같은 섹션 결과 · 같은 data 이고 대표 시리얼만 null 이다.

    System GET 실패(500)가 겹쳐도 같다: 그 경우 기준도 System 이 실패한 정상 태그 결과다.
    """
    root = UNRESOLVED_ROOTS[case]
    result = _run_fake(_FakeBmc(noauth_root=root, auth_root=root, system_status=system_status))
    _assert_only_serial_lost(result, _reference(system_status))


# ── 7. 폴백 금지 실증 ────────────────────────────────────────────────────────

FALLBACK_CASES = dict(UNRESOLVED_ROOTS, no_oem=_root_without_oem())


@pytest.mark.parametrize("system_status", [200, 500])
@pytest.mark.parametrize("case", sorted(FALLBACK_CASES))
def test_never_falls_back_to_other_serial_candidates(case, system_status):
    """Service Tag 를 못 얻은 결과에서 다른 시리얼 후보가 대표 시리얼 자리로 올라오지 않는다.

    data 를 보존하게 된 뒤(2026-11-09)에는 SKU · ChassisServiceTag 가 자기 필드(system.sku · system.oem.chassis_service_tag)에
    정당하게 남는다 — 정상 Service Tag 결과와 **같은 자리에만** 나타나야 한다. 보드 시리얼(ComputerSystem.SerialNumber)과
    NodeID 는 정상 결과에도 어디에도 없으므로 여기서도 어디에도 없어야 한다.
    """
    root = FALLBACK_CASES[case]
    result = _run_fake(_FakeBmc(noauth_root=root, auth_root=root, system_status=system_status))
    ref = _reference(system_status)
    assert result["vendor"] == "dell"
    assert _serial_of(result) is None
    for decoy in DECOYS:
        assert _paths_of(result, decoy) == _paths_of(ref, decoy), "폴백 금지 위반 — %s 의 위치가 정상 결과와 다르다" % decoy
    assert _paths_of(ref, DECOY_SERIAL) == [] and _paths_of(ref, DECOY_NODE_ID) == [], "전제: 정상 결과에도 없다"


# ── 8~10. 무인증/인증 ServiceRoot 노출 차이 ──────────────────────────────────

def test_service_tag_recovered_from_authenticated_service_root():
    """무인증 ServiceRoot 는 200 이지만 OEM 블록이 없고, 인증 응답에만 ServiceTag 가 있는 경우.

    _fetch_service_root 는 무인증 200 이면 인증 GET 을 하지 않으므로, 재조회가 없으면
    정상 장비를 '' Service Tag 없음'' 으로 오판한다.
    """
    bmc = _FakeBmc(noauth_root=_root_without_oem(), auth_root=_service_root())
    result = _run_fake(bmc)
    assert result["status"] != "failed"
    assert _serial_of(result) == SERVICE_TAG
    assert _serial_notices(result) == []
    assert bmc.auth_root_gets == 1, "인증 ServiceRoot 재조회는 정확히 1회"


def test_service_tag_absent_in_both_roots_keeps_the_collection_after_one_refetch():
    bmc = _FakeBmc(noauth_root=_root_without_oem(), auth_root=_root_without_oem())
    result = _run_fake(bmc)
    _assert_only_serial_lost(result, _reference(200))
    assert bmc.auth_root_gets == 1, "재조회 후에도 없으면 더 시도하지 않는다"


def test_no_extra_service_root_fetch_when_noauth_already_has_tag():
    """정상 경로(무인증에 이미 태그 존재)에서는 추가 인증 ServiceRoot GET 0회."""
    root = _service_root()
    bmc = _FakeBmc(noauth_root=root, auth_root=root)
    result = _run_fake(bmc)
    assert _serial_of(result) == SERVICE_TAG
    assert bmc.auth_root_gets == 0


def test_no_refetch_without_credentials():
    """자격증명이 없으면 재조회하지 않는다 (무인증 probe 경로 보호). 대표 시리얼은 null, 수집은 남는다."""
    bmc = _FakeBmc(noauth_root=_root_without_oem(), auth_root=_service_root())
    result = _run_fake(bmc, vendor_user="")
    assert result["status"] != "failed"
    assert _serial_of(result) is None
    assert len(_serial_notices(result)) == 1
    assert bmc.auth_root_gets == 0


# ── 11. 불변식 — Dell 대표 시리얼은 Service Tag 이거나 null, null 이면 근거가 남는다 ──

def _all_dell_results():
    """이 파일이 다루는 모든 Dell 실행 경로 — (이름, 결과, 그 경로에서 얻을 수 있는 Service Tag 또는 None)."""
    out = []
    for name in ("dell", "dell_r760"):
        result, root = _run_dir(name)
        out.append((name, result, rg._safe(root, "Oem", "Dell", "ServiceTag")))
    variants = ([("tag_ok", _service_root(), SERVICE_TAG), ("no_oem", _root_without_oem(), None)]
                + [(name, root, None) for name, root in sorted(UNRESOLVED_ROOTS.items())])
    for name, root, tag in variants:
        for system_status in (200, 500):
            bmc = _FakeBmc(noauth_root=root, auth_root=root, system_status=system_status)
            out.append(("%s/system=%d" % (name, system_status), _run_fake(bmc), tag))
    bmc = _FakeBmc(noauth_root=_root_without_oem(), auth_root=_service_root())
    out.append(("tag_in_auth_root_only", _run_fake(bmc), SERVICE_TAG))
    return out


def test_dell_serial_is_service_tag_or_null_and_null_has_evidence():
    """Dell 계약 불변식 (2026-11-09 개정).

    - 어떤 경로도 수집을 버리지 않는다 (status failed · data={} 0건).
    - 대표 시리얼은 그 경로의 Service Tag 이거나 null 이다.
    - null 이면 근거가 있다: 대표 시리얼 notice(Service Tag 를 못 얻음) 또는 system 섹션 실패(실을 자리가 없음).
    종전 불변식("failed 가 아니면 serial 이 채워져 있다")은 봉투 층으로 옮겨졌다 — serial 이 null 인 host 는 공통 규칙이
    failed 로 만든다 (tests/unit/test_status_serial_required_scenario_e.py).
    """
    offenders = []
    for name, result, tag in _all_dell_results():
        serial = _serial_of(result)
        system_failed = "system" in result["failed_sections"]
        if result["status"] == "failed" or result["data"] == {}:
            offenders.append((name, "수집을 버렸다", result["status"]))
        if serial is None:
            if not (_serial_notices(result) or system_failed):
                offenders.append((name, "null 인데 근거(notice · system 실패)가 없다"))
            if tag is not None and not system_failed:
                offenders.append((name, "Service Tag 를 얻을 수 있는데 null"))
        elif serial != tag:
            offenders.append((name, "Service Tag 가 아닌 값", serial))
    assert not offenders, offenders


# ── 12. 비-Dell 무회귀 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture_name", ["hpe", "lenovo", "cisco"])
def test_non_dell_still_uses_computer_system_serial_number(fixture_name):
    """다른 벤더는 ComputerSystem.SerialNumber 를 그대로 쓴다 (원값 유지)."""
    recording, _ = _recording_from_dir(fixture_name)
    system_body = None
    for key, val in recording.items():
        body = val[1]
        if isinstance(body, dict) and str(body.get("@odata.type", "")).startswith("#ComputerSystem."):
            system_body = body
            break
    assert system_body is not None, "%s: ComputerSystem fixture 없음" % fixture_name
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    result = H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl)
    assert _serial_of(result) == system_body["SerialNumber"]


def test_non_dell_never_triggers_service_root_refetch():
    """비-Dell 은 resolver 자체가 등록되어 있지 않아 재조회 경로를 타지 않는다."""
    assert set(rg._SERIAL_RESOLVERS) == {"dell"}


# ── 13. main() 과 run_gather 미러의 동기화 ───────────────────────────────────

def test_module_main_no_longer_exits_on_unresolved_service_tag():
    """main() 이 Service Tag 를 못 얻었을 때 data={} 로 끝내던 두 경로(2026-08-11)가 없어졌는지 소스로 확인한다.

    이 파일의 시험은 run_gather(main() 1:1 미러)를 돌리므로, main() 에만 옛 _exit 가 남으면 시험은 통과하고 운영만 달라진다.
    """
    src = (REPO / "redfish-gather" / "library" / "redfish_gather.py").read_text(encoding="utf-8")
    main_src = src[src.index("\ndef main("):]
    block = main_src[main_src.index("_serial_resolver = _SERIAL_RESOLVERS.get(vendor)"):
                     main_src.index("multi_node = _collect_multi_node_topology(")]
    assert "_exit(" not in block, "대표 시리얼 처리 블록 안에 _exit 가 남아 있다"
    assert "_notice('system', _serial_err)" in block
    assert "all_errors.append" not in block, "대표 시리얼 사유를 errors[] 에 넣지 않는다"
    assert "_sys_section['serial'] = _forced_serial" in block
