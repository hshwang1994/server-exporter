"""BIOS Current Attributes 보조 수집 회귀 (2026-09-15).

고정하는 계약
-------------
1. 성공 경로는 `data.bios.current.attributes` 하나다. 응답의 `Attributes` 객체를 그대로 담는다.
   Key·Value·JSON 자료형이 원본과 같고, 필터·이름 변환·값 변환·개수 제한이 없다.
2. Bios 리소스는 gather_system 이 이미 받은 ComputerSystem 응답의 `Bios.@odata.id` 로만 찾는다.
   ComputerSystem 재조회 없음, System ID 로 URI 를 조립하는 fallback 없음, BIOS GET 은 실행당 최대 1회.
3. BIOS 는 보조(auxiliary) 데이터다. 조회 실패는 errors[](section=bios) 또는 notice 로만 남고
   collected / failed / unsupported / 최종 status 를 바꾸지 않는다 (401·403 포함).
4. Settings / Pending / SD / AttributeRegistry / OEM 하위 리소스는 호출하지 않는다.

전부 mock 또는 녹화 재생이다. 실장비 지원 증거가 아니다
(실캡처 재생은 tests/integration/test_bios_real_capture_replay.py).
"""
from __future__ import annotations

import copy
import json
import re
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "tests" / "integration"))

# ansible stub (Windows dev / import 안전)
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402
import emulator_harness as H  # noqa: E402

CREDS = ("u", "p", 30, False)
IP = "10.0.0.1"
SYSTEM = "/redfish/v1/Systems/1"
BIOS = "/redfish/v1/Systems/1/Bios"
SYS_PATH = rg._p(SYSTEM)
BIOS_PATH = rg._p(BIOS)

# 지시서 13.1 — 모두 서로 다른 원본 값이다. 결과에서도 값과 자료형이 그대로여야 한다.
PRESERVE_SAMPLE = {
    "StringValue": "Enabled",
    "StringZero": "0",
    "IntegerZero": 0,
    "BooleanTrue": True,
    "BooleanFalse": False,
    "EmptyString": "",
    "NullValue": None,
    "LeadingZero": "00000",
    "DecimalText": "00.00",
}


@pytest.fixture(autouse=True)
def _module_state():
    """notices / 인증 관측은 모듈 전역 상태다 — 테스트 사이에 새지 않게 비운다."""
    rg._reset_notices()
    rg._reset_auth_observation()
    yield
    rg._reset_notices()
    rg._reset_auth_observation()


def _system_body(bios_link=BIOS):
    body = {
        "@odata.id": SYSTEM,
        "@odata.type": "#ComputerSystem.v1_13_0.ComputerSystem",
        "Id": "1",
        "Manufacturer": "Example",
        "Model": "Model X",
        "SerialNumber": "SN0001",
        "BiosVersion": "1.2.3",
        "PowerState": "On",
        "Status": {"Health": "OK", "State": "Enabled"},
    }
    if bios_link is not None:
        body["Bios"] = {"@odata.id": bios_link}
    return body


def _bios_body(attributes, odata_id=BIOS):
    return {
        "@odata.id": odata_id,
        "@odata.type": "#Bios.v1_2_0.Bios",
        "Id": "Bios",
        "AttributeRegistry": "BiosAttributeRegistry.1.0.0",
        "Attributes": attributes,
        # 표준 응답도 내부에는 다른 type 이 있다 — 판정은 최상위만 본다.
        "@Redfish.Settings": {
            "@odata.type": "#Settings.v1_3_0.Settings",
            "SettingsObject": {"@odata.id": odata_id + "/Settings"},
        },
        "Oem": {"Example": {"@odata.type": "#ExampleBios.v1_0_0.ExampleBios"}},
    }


def _routed_get(routes, calls):
    """_p 로 정규화된 path → (status, body, err). 없는 path 는 실 BMC 처럼 404."""
    def fake_get(bmc_ip, path, *a, **kw):
        calls.append(path)
        resp = routes.get(path, (404, {}, "HTTP 404: Not Found"))
        if isinstance(resp, BaseException):
            raise resp
        return resp
    return fake_get


def _bios_notices():
    return [n for n in rg.notices() if n["section"] == "bios"]


def _bios_requests(calls, system_path=SYS_PATH):
    """Bios 리소스와 그 하위 리소스에 나간 요청."""
    prefix = system_path.lower() + "/bios"
    return [c for c in calls if c.lower() == prefix or c.lower().startswith(prefix + "/")]


def _gather_bios(monkeypatch, bios_link, routes):
    calls = []
    monkeypatch.setattr(rg, "_get", _routed_get(routes, calls))
    out, errors = rg.gather_bios(IP, bios_link, *CREDS)
    return out, errors, calls


def _type_tree(value):
    """자료형까지 비교하기 위한 구조 (== 는 False 와 0, True 와 1 을 같게 본다)."""
    if isinstance(value, dict):
        return {k: _type_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_type_tree(v) for v in value]
    return type(value).__name__


# ═══════════════════════════════════════════════════════════════════════════
# 1. 원본 보존 (지시서 13.1 / 13.4)
# ═══════════════════════════════════════════════════════════════════════════
def test_attributes_are_the_response_object_unchanged(monkeypatch):
    source = copy.deepcopy(PRESERVE_SAMPLE)
    out, errors, calls = _gather_bios(
        monkeypatch, {"retrieved": True, "link": BIOS},
        {BIOS_PATH: (200, _bios_body(source), None)})

    attrs = out["current"]["attributes"]
    assert out == {"current": {"attributes": PRESERVE_SAMPLE}}
    assert attrs is source, "응답 Attributes 객체를 복사·재구성하지 않고 그대로 담아야 한다"
    assert list(attrs) == list(PRESERVE_SAMPLE), "Key 개수·순서가 원본과 같아야 한다"
    assert _type_tree(attrs) == _type_tree(PRESERVE_SAMPLE)
    assert errors == [] and _bios_notices() == []
    assert calls == [BIOS_PATH]
    reparsed = json.loads(json.dumps(out, ensure_ascii=False))
    assert _type_tree(reparsed) == _type_tree(out) and reparsed == out


def test_large_attributes_are_not_truncated_or_filtered(monkeypatch):
    """1,223개 이상·약 100KB — 개수·값·자료형이 그대로다. 고정 상한은 없다."""
    source = {"키 한글": "값", "Key With Space": " lead and trail ", "Key.With.Dot": "a.b",
              "Key/Slash": "x/y", "lowercase_key": "MiXeD"}
    for i in range(1400):
        key = f"Attribute_{i:04d}_" + "K" * 32
        kind = i % 7
        if kind == 0:
            value = "V" * 120 + str(i)
        elif kind == 1:
            value = i
        elif kind == 2:
            value = i % 2 == 0
        elif kind == 3:
            value = None
        elif kind == 4:
            value = ""
        elif kind == 5:
            value = f"{i:05d}"
        else:
            value = i + 0.5
        source[key] = value
    raw = json.dumps(_bios_body(source), ensure_ascii=False)
    assert len(source) >= 1223 and len(raw) >= 95_000, (len(source), len(raw))

    out, errors, _calls = _gather_bios(
        monkeypatch, {"retrieved": True, "link": BIOS},
        {BIOS_PATH: (200, json.loads(raw), None)})
    attrs = out["current"]["attributes"]

    assert errors == []
    assert len(attrs) == len(source)
    assert list(attrs) == list(source)
    assert _type_tree(attrs) == _type_tree(source) and attrs == source
    reparsed = json.loads(json.dumps(out, ensure_ascii=False))["current"]["attributes"]
    assert len(reparsed) == len(source) and _type_tree(reparsed) == _type_tree(source)
    assert reparsed == source


# ═══════════════════════════════════════════════════════════════════════════
# 2. 결정표 — 링크가 있어 GET 이 1회 나가는 경우 (D-2 #3~#13)
# ═══════════════════════════════════════════════════════════════════════════
_ERR, _NOTICE, _OK = "error", "notice", "ok"

_GET_CASES = [
    # id, 응답, 기대 attributes, 결과 종류, detail 에 남아야 할 원문
    ("timeout", (0, {}, "Timeout after 30s"), None, _ERR, "Timeout after 30s"),
    ("url-error", (0, {}, "URLError: [Errno 111] Connection refused"), None, _ERR, "URLError"),
    ("http-401", (401, {"error": {}}, "HTTP 401: Unauthorized"), None, _ERR, "HTTP 401"),
    ("http-403", (403, {"error": {}}, "HTTP 403: Forbidden"), None, _ERR, "HTTP 403"),
    ("http-400", (400, {}, "HTTP 400: Bad Request"), None, _ERR, "HTTP 400"),
    ("http-500", (500, {}, "HTTP 500: Internal Server Error"), None, _ERR, "HTTP 500"),
    ("http-204", (204, {}, None), None, _ERR, "HTTP 204"),
    ("body-not-json", (200, {}, "HTTP 200: body not JSON"), None, _ERR, "body not JSON"),
    ("json-array", (200, [1, 2], None), None, _ERR, "body type list"),
    ("json-string", (200, "text", None), None, _ERR, "body type str"),
    ("attributes-missing", (200, {"@odata.type": "#Bios.v1_0_0.Bios"}, None), None, _ERR,
     "Attributes missing"),
    ("attributes-list", (200, {"Attributes": [1]}, None), None, _ERR, "Attributes type list"),
    ("attributes-string", (200, {"Attributes": "x"}, None), None, _ERR, "Attributes type str"),
    ("attributes-null", (200, {"Attributes": None}, None), None, _ERR, "Attributes type NoneType"),
    ("http-404", (404, {}, "HTTP 404: Not Found"), None, _NOTICE, None),
    ("oem-odata-type", (200, {"@odata.type": "#OemBios.1.2.0.OemBios", "Attributes": {"A": "1"}}, None),
     None, _NOTICE, None),
    ("non-string-odata-type", (200, {"@odata.type": 7, "Attributes": {"A": "1"}}, None),
     None, _NOTICE, None),
    ("attributes-empty", (200, {"@odata.type": "#Bios.v1_0_0.Bios", "Attributes": {}}, None),
     {}, _NOTICE, None),
    ("no-odata-type", (200, {"Attributes": {"A": "1"}}, None), {"A": "1"}, _OK, None),
    ("standard", (200, _bios_body({"BootMode": "Uefi", "Count": 0}), None),
     {"BootMode": "Uefi", "Count": 0}, _OK, None),
]


@pytest.mark.parametrize("case,response,expected,kind,evidence", _GET_CASES,
                         ids=[c[0] for c in _GET_CASES])
def test_bios_get_outcome(monkeypatch, case, response, expected, kind, evidence):
    out, errors, calls = _gather_bios(
        monkeypatch, {"retrieved": True, "link": BIOS}, {BIOS_PATH: response})

    assert calls == [BIOS_PATH], "링크가 있으면 정확히 1회만 조회한다 (재시도·다른 URI 없음)"
    assert out == {"current": {"attributes": expected}}
    if expected is not None:
        assert _type_tree(out["current"]["attributes"]) == _type_tree(expected)
    if kind == _ERR:
        assert len(errors) == 1 and _bios_notices() == []
        err = errors[0]
        assert err["section"] == "bios"
        assert err["code"] == rg._CODE_BIOS_NON_BLOCKING
        assert evidence in str(err["detail"])
    elif kind == _NOTICE:
        assert errors == [] and len(_bios_notices()) == 1
    else:
        assert errors == [] and _bios_notices() == []


# ═══════════════════════════════════════════════════════════════════════════
# 3. 링크가 없으면 조회하지 않는다 — URI 조립 fallback 없음 (D-2 #1 / #2 / #14)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("bios_link", [
    {},
    {"retrieved": True, "link": None},
    {"retrieved": True, "link": ""},
    {"retrieved": True, "link": "   "},
    {"retrieved": True, "link": {"@odata.id": BIOS}},
    {"retrieved": True, "link": 5},
    None,
], ids=["not-retrieved", "link-none", "link-empty", "link-blank", "link-dict", "link-int",
        "not-a-dict"])
def test_no_request_without_a_link(monkeypatch, bios_link):
    routes = {BIOS_PATH: (200, _bios_body(dict(PRESERVE_SAMPLE)), None)}
    out, errors, calls = _gather_bios(monkeypatch, bios_link, routes)

    assert calls == [], "링크가 없으면 System ID 로 /Bios 를 조립해 부르지 않는다"
    assert out == {"current": {"attributes": None}}
    assert errors == []
    assert len(_bios_notices()) == 1


def test_link_case_is_kept_and_trailing_slash_follows_existing_p(monkeypatch):
    """대소문자는 응답 그대로 쓴다. 후행 '/' 는 기존 _p() 가 모든 링크에서 지운다."""
    link = "/redfish/v1/systems/1/bios/"
    out, errors, calls = _gather_bios(
        monkeypatch, {"retrieved": True, "link": link},
        {"systems/1/bios": (200, _bios_body({"A": "B"}, odata_id=link), None)})
    assert calls == ["systems/1/bios"]
    assert out == {"current": {"attributes": {"A": "B"}}} and errors == []


def test_internal_exception_is_absorbed(monkeypatch):
    """D-2 #15 — 예외가 모듈 밖으로 나가 다른 섹션 결과를 잃게 하지 않는다."""
    out, errors, calls = _gather_bios(
        monkeypatch, {"retrieved": True, "link": BIOS}, {BIOS_PATH: RuntimeError("boom")})

    assert calls == [BIOS_PATH]
    assert out == {"current": {"attributes": None}}
    assert len(errors) == 1
    err = errors[0]
    assert err["section"] == "bios" and err["message"] == "예외 발생"
    assert err["detail"].startswith("RuntimeError")
    assert err["code"] == rg._CODE_BIOS_NON_BLOCKING


# ═══════════════════════════════════════════════════════════════════════════
# 4. gather_system — 링크 기록은 결과와 요청을 바꾸지 않는다 (V-2)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("vendor", ["generic", "dell", "hpe", "lenovo", "cisco"])
def test_gather_system_is_identical_with_or_without_link_out(monkeypatch, vendor):
    routes = {SYS_PATH: (200, _system_body(), None)}
    calls_plain, calls_link = [], []

    monkeypatch.setattr(rg, "_get", _routed_get(routes, calls_plain))
    plain = rg.gather_system(IP, SYSTEM, vendor, *CREDS, chassis_uri="/redfish/v1/Chassis/1")
    monkeypatch.setattr(rg, "_get", _routed_get(routes, calls_link))
    link_out = {}
    with_link = rg.gather_system(IP, SYSTEM, vendor, *CREDS, chassis_uri="/redfish/v1/Chassis/1",
                                 bios_link_out=link_out)

    assert with_link == plain
    assert calls_link == calls_plain, "요청 수·순서가 같아야 한다 (ComputerSystem 재조회 없음)"
    assert calls_link.count(SYS_PATH) == 1
    assert link_out == {"retrieved": True, "link": BIOS}


def test_gather_system_without_bios_property_records_no_link(monkeypatch):
    monkeypatch.setattr(rg, "_get", _routed_get({SYS_PATH: (200, _system_body(None), None)}, []))
    link_out = {}
    rg.gather_system(IP, SYSTEM, "generic", *CREDS, bios_link_out=link_out)
    assert link_out == {"retrieved": True, "link": None}


@pytest.mark.parametrize("response", [
    (500, {}, "HTTP 500: Internal Server Error"),
    (401, {}, "HTTP 401: Unauthorized"),
    (0, {}, "Timeout after 30s"),
    (200, {}, "HTTP 200: body not JSON"),
], ids=["http-500", "http-401", "timeout", "body-not-json"])
def test_gather_system_failure_records_nothing(monkeypatch, response):
    monkeypatch.setattr(rg, "_get", _routed_get({SYS_PATH: response}, []))
    link_out = {}
    result, errors = rg.gather_system(IP, SYSTEM, "generic", *CREDS, bios_link_out=link_out)
    assert result == {} and len(errors) == 1
    assert link_out == {}


# ═══════════════════════════════════════════════════════════════════════════
# 5. 최종 status 격리 (결정 2) — _compute_final_status
# ═══════════════════════════════════════════════════════════════════════════
def _bios_error(detail):
    return rg._err("bios", "BIOS Current Attributes 조회 실패", detail,
                   code=rg._CODE_BIOS_NON_BLOCKING)


@pytest.mark.parametrize("detail", [
    "HTTP 401: Unauthorized", "HTTP 403: Forbidden", "HTTP 500: Internal Server Error",
    "Timeout after 30s", "HTTP 200: body not JSON",
])
def test_bios_error_never_changes_final_status(detail):
    collected = ["system", "processors"]
    assert rg._compute_final_status(collected, [], [_bios_error(detail)]) == ("success", collected)
    assert rg._compute_final_status(collected, ["processors"], [_bios_error(detail)]) == (
        "partial", ["system"])


@pytest.mark.parametrize("detail", ["HTTP 401: Unauthorized", "HTTP 403: Forbidden"])
def test_non_bios_auth_errors_still_fail_the_host(detail):
    collected = ["system", "processors"]
    other = rg._err("processors", "Processors 컬렉션 실패", detail)
    assert rg._compute_final_status(collected, [], [other])[0] == "failed"
    assert rg._compute_final_status(collected, [], [_bios_error(detail), other])[0] == "failed"
    # 제외 근거는 section 이름이 아니라 구조화 code 다
    uncoded = rg._err("bios", "BIOS Current Attributes 조회 실패", detail)
    assert rg._compute_final_status(collected, [], [uncoded])[0] == "failed"


# ═══════════════════════════════════════════════════════════════════════════
# 6. _collect_all_sections — 호출 범위와 섹션 격리
# ═══════════════════════════════════════════════════════════════════════════
def _collect(monkeypatch, routes, vendor="generic"):
    calls = []
    all_errors, collected, failed, unsupported = [], [], [], []
    rg._reset_notices()
    monkeypatch.setattr(rg, "_get", _routed_get(routes, calls))
    data = rg._collect_all_sections(IP, vendor, SYSTEM, None, None, *CREDS,
                                    all_errors, collected, failed, unsupported)
    status, _clean = rg._compute_final_status(collected, failed, all_errors)
    return {"data": data, "calls": calls, "errors": all_errors, "status": status,
            "collected": sorted(collected), "failed": sorted(failed),
            "unsupported": sorted(unsupported)}


def _without_bios(data):
    return {k: v for k, v in data.items() if k != "bios"}


def _forbidden_requests(calls):
    """Bios 하위 리소스(Settings / Pending / SD / Oem …)와 Registry 요청."""
    sub = SYS_PATH.lower() + "/bios/"
    return [c for c in calls if c.lower().startswith(sub) or "registr" in c.lower()]


def test_collect_requests_bios_once_and_keeps_system_request_count(monkeypatch):
    bios = (200, _bios_body(copy.deepcopy(PRESERVE_SAMPLE)), None)
    with_link = _collect(monkeypatch, {SYS_PATH: (200, _system_body(), None), BIOS_PATH: bios})
    no_link = _collect(monkeypatch, {SYS_PATH: (200, _system_body(None), None), BIOS_PATH: bios})

    assert with_link["data"]["bios"] == {"current": {"attributes": PRESERVE_SAMPLE}}
    assert _type_tree(with_link["data"]["bios"]) == _type_tree({"current": {"attributes": PRESERVE_SAMPLE}})
    assert no_link["data"]["bios"] == {"current": {"attributes": None}}

    # ComputerSystem GET 은 기존과 같은 2회 (_resolve_system_chassis_uri + gather_system)
    assert with_link["calls"].count(SYS_PATH) == no_link["calls"].count(SYS_PATH) == 2
    assert _bios_requests(with_link["calls"]) == [BIOS_PATH]
    assert _bios_requests(no_link["calls"]) == []
    # BIOS 조회 1건을 빼면 요청 순서까지 같다
    assert [c for c in with_link["calls"] if c != BIOS_PATH] == no_link["calls"]
    assert with_link["calls"][-1] == BIOS_PATH, "BIOS 는 다른 섹션 수집이 끝난 뒤 조회한다"

    for run in (with_link, no_link):
        assert _forbidden_requests(run["calls"]) == []
        assert "bios" not in run["collected"] + run["failed"] + run["unsupported"]
        assert not [e for e in run["errors"] if e.get("section") == "bios"]
    assert _without_bios(with_link["data"]) == _without_bios(no_link["data"])
    for key in ("collected", "failed", "unsupported", "status"):
        assert with_link[key] == no_link[key], key


_BIOS_FAILURES = [
    ("http-401", (401, {}, "HTTP 401: Unauthorized")),
    ("http-403", (403, {}, "HTTP 403: Forbidden")),
    ("http-500", (500, {}, "HTTP 500: Internal Server Error")),
    ("timeout", (0, {}, "Timeout after 30s")),
    ("invalid-json", (200, {}, "HTTP 200: body not JSON")),
]


@pytest.mark.parametrize("case,response", _BIOS_FAILURES, ids=[c for c, _ in _BIOS_FAILURES])
def test_collect_bios_failure_leaves_other_results_alone(monkeypatch, case, response):
    ok = _collect(monkeypatch, {SYS_PATH: (200, _system_body(), None),
                                BIOS_PATH: (200, _bios_body({"A": "B"}), None)})
    bad = _collect(monkeypatch, {SYS_PATH: (200, _system_body(), None), BIOS_PATH: response})

    assert bad["data"]["bios"] == {"current": {"attributes": None}}
    assert _without_bios(bad["data"]) == _without_bios(ok["data"])
    for key in ("collected", "failed", "unsupported", "status"):
        assert bad[key] == ok[key], key
    bios_errors = [e for e in bad["errors"] if e.get("section") == "bios"]
    assert len(bios_errors) == 1 and bios_errors[0]["code"] == rg._CODE_BIOS_NON_BLOCKING
    assert len(bad["errors"]) == len(ok["errors"]) + 1


def test_link_recorded_before_system_processing_error(monkeypatch):
    """ComputerSystem 200 뒤 가공 중 예외(_run 흡수)여도 이미 받은 링크로 BIOS 는 1회 조회된다."""
    def boom(*_a, **_k):
        raise ValueError("processing failed")

    monkeypatch.setitem(rg._OEM_EXTRACTORS, "generic", boom)
    run = _collect(monkeypatch, {SYS_PATH: (200, _system_body(), None),
                                 BIOS_PATH: (200, _bios_body({"A": "B"}), None)})

    assert "system" in run["failed"]
    assert run["data"]["bios"] == {"current": {"attributes": {"A": "B"}}}
    assert _bios_requests(run["calls"]) == [BIOS_PATH]
    assert run["calls"].count(SYS_PATH) == 2


def test_system_get_failure_skips_bios(monkeypatch):
    """D-2 #14 — ComputerSystem 을 못 받으면 BIOS 도 조회하지 않는다 (재조회·조립 없음)."""
    run = _collect(monkeypatch, {SYS_PATH: (500, {}, "HTTP 500: Internal Server Error"),
                                 BIOS_PATH: (200, _bios_body({"A": "B"}), None)})
    assert run["data"]["bios"] == {"current": {"attributes": None}}
    assert _bios_requests(run["calls"]) == []
    assert len(_bios_notices()) == 1


def test_bios_response_does_not_change_auth_evidence(monkeypatch):
    """첫 인증 응답만 기록한다 — BIOS 401 이 표준 계정 거부 판정(auth_evidence)을 만들지 않는다."""
    calls = []
    routes = {SYS_PATH: (200, _system_body(), None), BIOS_PATH: (401, {}, "HTTP 401: Unauthorized")}
    monkeypatch.setattr(rg, "_get_impl", _routed_get(routes, calls))
    all_errors, collected, failed, unsupported = [], [], [], []
    rg._collect_all_sections(IP, "generic", SYSTEM, None, None, *CREDS,
                             all_errors, collected, failed, unsupported)

    assert calls[0] == SYS_PATH and BIOS_PATH in calls
    assert rg.auth_evidence() == {"first_auth_status": 200}


_VENDORS = ["dell", "hpe", "lenovo", "cisco", "supermicro", "huawei", "inspur", "fujitsu",
            "quanta", "unknown"]


@pytest.mark.parametrize("vendor", _VENDORS)
def test_same_standard_response_gives_same_bios_for_every_vendor(monkeypatch, vendor):
    """지시서 13.3 — vendor 값이 달라도 같은 generic 경로를 탄다. 실장비 지원 증거가 아니다."""
    routes = {SYS_PATH: (200, _system_body(), None),
              BIOS_PATH: (200, _bios_body(copy.deepcopy(PRESERVE_SAMPLE)), None)}
    run = _collect(monkeypatch, routes, vendor=vendor)

    assert run["data"]["bios"] == {"current": {"attributes": PRESERVE_SAMPLE}}
    assert _type_tree(run["data"]["bios"]["current"]["attributes"]) == _type_tree(PRESERVE_SAMPLE)
    assert _bios_requests(run["calls"]) == [BIOS_PATH]
    assert not [e for e in run["errors"] if e.get("section") == "bios"]


# ═══════════════════════════════════════════════════════════════════════════
# 7. 실녹화 재생 — 다른 섹션이 모두 성공한 장비에서 BIOS 만 바꾼다 (D-2 #16)
# ═══════════════════════════════════════════════════════════════════════════
REAL_CASE = REPO / "tests" / "fixtures" / "redfish" / "real_dell_r740"
REAL_SYSTEM_KEY = "get::Systems/System.Embedded.1"
REAL_BIOS_PATH = "Systems/System.Embedded.1/Bios"
REAL_BIOS_KEY = "get::" + REAL_BIOS_PATH
_HOST_KEYS = ("vendor", "status", "collected", "failed_sections", "unsupported_sections",
              "multi_node", "probe_facts")


def _replay_real(mutate=None):
    recording = json.loads((REAL_CASE / "recording.json").read_text(encoding="utf-8"))
    if mutate:
        mutate(recording)
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    calls = []

    def counting_get(bmc_ip, path, *a, **kw):
        calls.append(path)
        return get_impl(bmc_ip, path, *a, **kw)

    meta = json.loads((REAL_CASE / "meta.json").read_text(encoding="utf-8"))
    result = H.run_gather(counting_get, noauth_impl, realm_impl=realm_impl,
                          manager_layout=meta.get("manager_layout"))
    return result, calls


@pytest.fixture(scope="module")
def real_baseline():
    if not (REAL_CASE / "recording.json").is_file():
        pytest.skip("real_dell_r740 fixture 없음")
    return _replay_real()


def test_real_recording_baseline_is_a_full_success(real_baseline):
    base, calls = real_baseline
    assert base["status"] == "success" and base["failed_sections"] == []
    assert base["error_count"] == 0
    # 녹화에는 Bios 본문이 없다 → 링크로 1회 조회 → replay 404 → notice (errors 불변)
    assert base["data"]["bios"] == {"current": {"attributes": None}}
    assert calls.count(REAL_BIOS_PATH) == 1


def test_real_recording_bios_success_adds_only_bios(real_baseline):
    base, base_calls = real_baseline
    source = copy.deepcopy(PRESERVE_SAMPLE)

    def mutate(rec):
        rec[REAL_BIOS_KEY] = [200, _bios_body(source, odata_id="/redfish/v1/" + REAL_BIOS_PATH), None]

    result, calls = _replay_real(mutate)
    assert result["data"]["bios"] == {"current": {"attributes": PRESERVE_SAMPLE}}
    assert _type_tree(result["data"]["bios"]["current"]["attributes"]) == _type_tree(PRESERVE_SAMPLE)
    for key in _HOST_KEYS:
        assert result[key] == base[key], key
    assert _without_bios(result["data"]) == _without_bios(base["data"])
    assert result["error_count"] == base["error_count"]
    assert calls == base_calls, "BIOS 성공 여부와 무관하게 요청 목록이 같다"


@pytest.mark.parametrize("case,response", _BIOS_FAILURES, ids=[c for c, _ in _BIOS_FAILURES])
def test_real_recording_bios_failure_keeps_host_result(real_baseline, case, response):
    base, base_calls = real_baseline

    def mutate(rec):
        rec[REAL_BIOS_KEY] = list(response)

    result, calls = _replay_real(mutate)
    assert result["status"] == "success"
    for key in _HOST_KEYS:
        assert result[key] == base[key], key
    assert _without_bios(result["data"]) == _without_bios(base["data"])
    assert result["data"]["bios"] == {"current": {"attributes": None}}
    assert result["error_count"] == base["error_count"] + 1
    assert calls == base_calls, "실패해도 재시도·다른 URI 요청이 없다"


def test_real_recording_without_bios_link_does_not_guess_uri(real_baseline):
    base, base_calls = real_baseline

    def mutate(rec):
        rec[REAL_SYSTEM_KEY][1].pop("Bios")
        rec[REAL_BIOS_KEY] = [200, _bios_body({"A": "B"}), None]   # 있어도 부르면 안 된다

    result, calls = _replay_real(mutate)
    assert REAL_BIOS_PATH not in calls
    assert [c for c in base_calls if c != REAL_BIOS_PATH] == calls
    assert result["data"]["bios"] == {"current": {"attributes": None}}
    for key in _HOST_KEYS:
        assert result[key] == base[key], key
    assert _without_bios(result["data"]) == _without_bios(base["data"])
    assert result["error_count"] == base["error_count"]
