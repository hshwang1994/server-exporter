"""Dell 서버 대표 시리얼 = ServiceRoot.Oem.Dell.ServiceTag (2026-08-11 Dell 1차 교정).

사용자 결정 (2026-08-11):
  - Dell 대표 시리얼 원천은 ServiceRoot.Oem.Dell.ServiceTag **단 하나**.
  - ComputerSystem.SerialNumber / System.SKU / DellSystem.ChassisServiceTag /
    DellSystem.NodeID / BIOS SystemServiceTag 로 **폴백하지 않는다**.
  - 확보 못 하면 기존 failure contract 로 **수집을 실패**시킨다 (신규 failure code 금지).

배경: Dell iDRAC 의 ComputerSystem.SerialNumber 는 보드 제조 시리얼(`CNIVC…`)이라
SMBIOS Type 1 System Serial 과 다르다. 동일 R760 실측에서 Redfish=CNIVC0048R0159,
Linux(/sys/class/dmi/id/product_serial)=GSBPK54 로 채널 간 매칭이 깨졌다
(docs/ai/contracts/serial-number.md §19).

실행 층: 대표 시리얼 확정/차단은 main() 층 책임이라 `emulator_harness.run_gather`
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

SERVICE_TAG = "GSBPK54"


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


def _run_fake(bmc, vendor_user="u"):
    return H.run_gather(bmc.get, bmc.noauth, realm_impl=lambda *a, **k: None,
                        user=vendor_user)


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
    return H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl), service_root


def _serial_of(result):
    return ((result.get("data") or {}).get("system") or {}).get("serial")


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


def test_real_dell_r740_mirror_uses_service_tag():
    """실장비 미러(real_dell_r740) 재생 — 보드 시리얼이 아니라 Service Tag."""
    base = FIXTURE_ROOT / "real_dell_r740"
    with open(base / "recording.json", encoding="utf-8") as fh:
        recording = json.load(fh)
    with open(base / "meta.json", encoding="utf-8") as fh:
        layout = json.load(fh).get("manager_layout")
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    result = H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl,
                          manager_layout=layout)
    expected = rg._safe(recording["noauth::"][1], "Oem", "Dell", "ServiceTag")
    assert _serial_of(result) == expected
    assert _serial_of(result) != recording["get::Systems/System.Embedded.1"][1]["SerialNumber"]


# ── 4. ServiceTag 정상 + System 수집 실패 ────────────────────────────────────

def test_system_section_failure_is_not_returned_as_normal_result():
    """ServiceTag 는 정상인데 System GET 이 실패하면 partial+serial=null 로 내보내지 않는다.

    다른 섹션(processors)은 성공하므로 가드가 없으면 status=partial 이 되고
    data.system 이 {} 라 hardware.serial 이 null 인 '정상' envelope 이 만들어진다.
    """
    root = _service_root()
    bmc = _FakeBmc(noauth_root=root, auth_root=root, system_status=500)
    result = _run_fake(bmc)
    assert result["status"] == "failed"
    assert result["data"] == {}
    assert result["error_count"] >= 1


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


@pytest.mark.parametrize("case", sorted(MISSING_ROOTS))
def test_missing_service_tag_fails_collection(case):
    root = MISSING_ROOTS[case]
    bmc = _FakeBmc(noauth_root=root, auth_root=root)
    result = _run_fake(bmc)
    # vendor 가 dell 로 식별돼야 이 테스트가 의미를 갖는다 (vacuous pass 차단).
    assert result["vendor"] == "dell"
    assert result["status"] == "failed"
    assert result["data"] == {}
    assert result["error_count"] >= 1


@pytest.mark.parametrize("bad", INVALID_TAGS)
def test_invalid_service_tag_fails_collection(bad):
    root = _service_root(bad)
    bmc = _FakeBmc(noauth_root=root, auth_root=root)
    result = _run_fake(bmc)
    assert result["vendor"] == "dell"
    assert result["status"] == "failed"
    assert result["data"] == {}
    assert result["error_count"] >= 1


# ── 7. 폴백 금지 실증 ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "root",
    [MISSING_ROOTS[k] for k in sorted(MISSING_ROOTS)] + [_service_root(b) for b in INVALID_TAGS],
)
def test_never_falls_back_to_other_serial_candidates(root):
    """Service Tag 를 못 얻은 결과 어디에도 다른 시리얼 후보가 등장하지 않는다.

    System 응답에는 SerialNumber / SKU / ChassisServiceTag / NodeID 가 모두 정상 존재한다.
    """
    bmc = _FakeBmc(noauth_root=root, auth_root=root)
    result = _run_fake(bmc)
    assert result["vendor"] == "dell"
    blob = json.dumps(result, ensure_ascii=False)
    for decoy in (DECOY_SERIAL, DECOY_SKU, DECOY_CHASSIS_TAG, DECOY_NODE_ID):
        assert decoy not in blob, "폴백 금지 위반 — %s 가 결과에 등장" % decoy


# ── 8~10. 무인증/인증 ServiceRoot 노출 차이 ──────────────────────────────────

def _root_without_oem():
    return {k: v for k, v in _service_root().items() if k != "Oem"}


def test_service_tag_recovered_from_authenticated_service_root():
    """무인증 ServiceRoot 는 200 이지만 OEM 블록이 없고, 인증 응답에만 ServiceTag 가 있는 경우.

    _fetch_service_root 는 무인증 200 이면 인증 GET 을 하지 않으므로, 재조회가 없으면
    정상 장비를 '' Service Tag 없음'' 으로 오판한다.
    """
    bmc = _FakeBmc(noauth_root=_root_without_oem(), auth_root=_service_root())
    result = _run_fake(bmc)
    assert result["status"] != "failed"
    assert _serial_of(result) == SERVICE_TAG
    assert bmc.auth_root_gets == 1, "인증 ServiceRoot 재조회는 정확히 1회"


def test_service_tag_absent_in_both_roots_still_fails():
    bmc = _FakeBmc(noauth_root=_root_without_oem(), auth_root=_root_without_oem())
    result = _run_fake(bmc)
    assert result["status"] == "failed"
    assert bmc.auth_root_gets == 1, "재조회 후에도 없으면 더 시도하지 않는다"


def test_no_extra_service_root_fetch_when_noauth_already_has_tag():
    """정상 경로(무인증에 이미 태그 존재)에서는 추가 인증 ServiceRoot GET 0회."""
    root = _service_root()
    bmc = _FakeBmc(noauth_root=root, auth_root=root)
    result = _run_fake(bmc)
    assert _serial_of(result) == SERVICE_TAG
    assert bmc.auth_root_gets == 0


def test_no_refetch_without_credentials():
    """자격증명이 없으면 재조회하지 않는다 (무인증 probe 경로 보호)."""
    bmc = _FakeBmc(noauth_root=_root_without_oem(), auth_root=_service_root())
    result = H.run_gather(bmc.get, bmc.noauth, realm_impl=lambda *a, **k: None, user="")
    assert result["status"] == "failed"
    assert bmc.auth_root_gets == 0


# ── 11. 불변식 — 정상 결과에 Dell serial null 0건 ────────────────────────────

def _all_dell_results():
    """이 파일이 다루는 모든 Dell 실행 경로의 결과를 모은다."""
    results = []
    for name in ("dell", "dell_r760"):
        results.append(_run_dir(name)[0])
    variants = (
        [_service_root()]
        + [MISSING_ROOTS[k] for k in sorted(MISSING_ROOTS)]
        + [_service_root(b) for b in INVALID_TAGS]
        + [_root_without_oem()]
    )
    for root in variants:
        for system_status in (200, 500):
            bmc = _FakeBmc(noauth_root=root, auth_root=root, system_status=system_status)
            results.append(_run_fake(bmc))
    bmc = _FakeBmc(noauth_root=_root_without_oem(), auth_root=_service_root())
    results.append(_run_fake(bmc))
    return results


def test_dell_serial_is_never_null_in_a_non_failed_result():
    """Dell 계약 불변식 — status 가 failed 가 아니면 대표 시리얼이 반드시 채워져 있다."""
    offenders = []
    for result in _all_dell_results():
        if result["status"] == "failed":
            continue
        serial = _serial_of(result)
        if not (isinstance(serial, str) and serial.strip()):
            offenders.append((result["status"], serial))
    assert not offenders, "정상 결과인데 Dell serial 이 비었다: %r" % (offenders,)


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
