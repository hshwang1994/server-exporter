"""보조 섹션(network_adapters) 실패가 network 섹션 status 를 덮지 않는지 회귀 (cycle 2026-08-03).

배경 (사이트 실측 — Jenkins DAY_1/git/소연등록redfish #1, Dell iDRAC 8대):
    `data.network` 는 정상 수집(interfaces 4 / gateway / summary)됐는데
    `sections.network=failed` + `status=partial` 로 emit 됐다. 원인은 2단:

      1. redfish_gather 모듈이 network(주=EthernetInterfaces) 와
         network_adapters(보조=NIC 카드 모델/펌웨어) 를 별도 raw 섹션으로 보고
      2. normalize_standard.yml `_rf_proc_map` 이 둘을 같은 'network' 로 collapse
         → build_sections 우선순위(not_supported > failed > success)에서 보조 실패가 승리

    보조 수집 실패로 주 수집 성공이 가려지면 호출자는 매번 partial 을 받는다.

    fix: 세 status fragment(collected/failed/unsupported) 모두에서 보조 섹션 제외.
         보조 실패는 errors[] 로만 보고 (시나리오 B — build_status.yml 4시나리오 매트릭스).

**400 의 근본 원인 (후속 조사에서 정정)**:
    처음엔 "장비 미지원"으로 보고 400 을 unsupported 로 분류했으나 **오판이었다**.
    사이트 장비는 PowerEdge R630(13G / iDRAC8 fw 2.7x~2.8x)이고, 벤더 공식 API 가이드는
    NetworkAdapters 를 `Systems/{id}/NetworkAdapters` 로 문서화한다. 즉 우리가 그 펌웨어에
    없는 Chassis 경로를 물어본 것이었다(비교 대상이던 R740 은 14G/iDRAC9 로 세대가 다름).
    → 400→unsupported 분류는 되돌리고(B절), Systems 경로 fallback 을 추가했다(D절).

검증 가능 (rule 24 R1): 실제 YAML 식 + 실제 모듈 함수를 직접 렌더/호출 — ansible CLI 불필요.
"""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

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

NORM_STD = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
BUILD_SECTIONS = REPO / "common" / "tasks" / "normalize" / "build_sections.yml"


# ── YAML 식 추출 (실제 코드) ──────────────────────────────────────────────────

def _set_fact_value(path: Path, key: str):
    for t in yaml.safe_load(path.read_text(encoding="utf-8")):
        sf = t.get("ansible.builtin.set_fact") or t.get("set_fact") or {}
        if key in sf:
            return sf[key]
    raise AssertionError(f"{path.name}: {key} set_fact 식 없음")


def _proc_map():
    return _set_fact_value(NORM_STD, "_rf_proc_map")


def _aux_sections():
    return _set_fact_value(NORM_STD, "_rf_aux_sections")


def _render_fragment(key: str, **ctx):
    """normalize_standard.yml 의 status fragment 식을 실제로 렌더."""
    expr = _set_fact_value(NORM_STD, key)
    out = jinja2.Environment().from_string(expr).render(
        _rf_proc_map=_proc_map(), _rf_aux_sections=_aux_sections(), **ctx
    )
    return ast.literal_eval(out.strip())


def _render_sections(supported, collected, failed, unsupported):
    """build_sections.yml 의 _norm_sections 식을 실제로 렌더."""
    expr = _set_fact_value(BUILD_SECTIONS, "_norm_sections")
    out = jinja2.Environment().from_string(expr).render(
        _all_sec_supported=supported, _all_sec_collected=collected,
        _all_sec_failed=failed, _all_sec_unsupported=unsupported,
    )
    return ast.literal_eval(out.strip())


SUPPORTED = ["hardware", "bmc", "cpu", "memory", "storage",
             "network", "firmware", "power", "thermal"]


# ── A. 보조 섹션 제외 ────────────────────────────────────────────────────────

def test_aux_sections_declares_network_adapters():
    """보조 섹션 정본에 network_adapters 가 등재돼 있어야 한다."""
    assert "network_adapters" in _aux_sections()


def test_aux_failure_does_not_mark_network_failed():
    """사이트 재현: network 성공 + network_adapters 실패 → failed fragment 에 network 없음."""
    failed = _render_fragment(
        "_sections_failed_fragment", _rf_failed_raw=["network_adapters"])
    assert failed == []


def test_aux_unsupported_does_not_mark_network_not_supported():
    """400→unsupported 확장 시에도 network 가 not_supported 로 덮이면 안 된다.

    unsupported 는 build_sections 최우선이라 제외 안 하면 failed 보다 더 나쁜 마스킹이 된다.
    """
    unsup = _render_fragment(
        "_sections_unsupported_fragment", _rf_unsupported_raw=["network_adapters"])
    assert unsup == []


def test_primary_network_failure_still_marks_failed():
    """주 섹션(network) 자체 실패는 그대로 failed — 보조 제외가 진짜 실패를 숨기면 안 된다."""
    failed = _render_fragment(
        "_sections_failed_fragment", _rf_failed_raw=["network", "network_adapters"])
    assert failed == ["network"]


def test_non_aux_mapping_unchanged():
    """기존 매핑(processors→cpu 등) 동작 불변 — Additive 회귀 가드."""
    collected = _render_fragment(
        "_sections_collected_fragment",
        _rf_collected_raw=["processors", "storage", "network", "system"])
    assert set(collected) == {"cpu", "storage", "network", "system", "hardware"}


def test_end_to_end_sections_network_success_on_aux_failure():
    """envelope 층 재현: 보조 실패만 있을 때 sections.network 는 success 여야 한다."""
    collected = _render_fragment(
        "_sections_collected_fragment",
        _rf_collected_raw=["network", "storage", "power", "thermal", "bmc",
                           "processors", "memory", "firmware", "hardware"])
    failed = _render_fragment(
        "_sections_failed_fragment", _rf_failed_raw=["network_adapters"])
    unsup = _render_fragment(
        "_sections_unsupported_fragment", _rf_unsupported_raw=[])
    sections = _render_sections(SUPPORTED, collected, failed, unsup)
    assert sections["network"] == "success"
    assert failed == []  # partial 유발 요인 제거 확인


# ── B. 400 은 '미지원' 이 아니다 — 은폐 금지 가드 ────────────────────────────
#
# cycle 2026-08-03 중간에 400 을 capability 부재로 분류했다가 **되돌렸다**. 사이트 Dell
# R630(iDRAC8)의 400 은 미지원이 아니라 경로 오류였기 때문(→ 아래 D 절 fallback).
# 400 을 미지원으로 분류하면 우리 쪽 버그가 not_supported 로 조용히 덮인다.

def test_400_is_not_treated_as_unsupported():
    """400 을 미지원으로 보지 않는다 — 은폐 재발 방지 가드."""
    assert rg._is_404_only_error([{"message": "x: HTTP 400: Bad Request"}]) is False
    assert not hasattr(rg, "_is_capability_missing_error"), (
        "400 을 미지원으로 분류하는 헬퍼가 되살아났다 — 근거(실측) 없이 재도입 금지")


def test_404_only_helper_semantics():
    assert rg._is_404_only_error([{"detail": "HTTP 404: Not Found"}]) is True
    assert rg._is_404_only_error([{"message": "x: 404"}]) is True
    assert rg._is_404_only_error([]) is False
    for msg in ["x: HTTP 401: Unauthorized", "x: HTTP 500: Internal Server Error",
                "x: Timeout after 30s"]:
        assert rg._is_404_only_error([{"message": msg}]) is False


def test_runner_keeps_400_empty_as_failed():
    """400 + 빈 결과라도 failed 로 남아 errors[] 에 보여야 한다 (미지원으로 숨기지 않음)."""
    all_errors, collected, failed, unsupported = [], [], [], []
    run = rg._make_section_runner(all_errors, collected, failed, unsupported)
    empty = {"adapters": [], "ports": [], "fc_hbas": [], "infiniband": []}
    run("network_adapters", lambda: (empty, [
        {"section": "network_adapters",
         "message": "NetworkAdapters 미지원 또는 실패: HTTP 400: Bad Request"}]))
    assert unsupported == []
    assert failed == ["network_adapters"]
    assert len(all_errors) == 1


def test_runner_keeps_404_empty_as_unsupported():
    """404(endpoint 부재)는 기존대로 미지원 — 회귀 가드."""
    all_errors, collected, failed, unsupported = [], [], [], []
    run = rg._make_section_runner(all_errors, collected, failed, unsupported)
    empty = {"adapters": [], "ports": [], "fc_hbas": [], "infiniband": []}
    run("network_adapters", lambda: (empty, [{"message": "x: HTTP 404: Not Found"}]))
    assert unsupported == ["network_adapters"]
    assert all_errors == []


def test_runner_keeps_400_with_data_as_failed():
    """부분 수집(결과 비어있지 않음)도 failed — EXC-1 가드 유지."""
    all_errors, collected, failed, unsupported = [], [], [], []
    run = rg._make_section_runner(all_errors, collected, failed, unsupported)
    partial = {"adapters": [{"id": "NIC.1"}], "ports": [], "fc_hbas": [], "infiniband": []}
    run("network_adapters", lambda: (partial, [{"message": "sub: HTTP 400: Bad Request"}]))
    assert unsupported == []
    assert failed == ["network_adapters"] and collected == ["network_adapters"]
    assert len(all_errors) == 1


# ── C. 확장 오류 정보 보존 ───────────────────────────────────────────────────

def test_extended_info_extracts_code_message_and_items():
    body = {"error": {
        "code": "Base.1.12.GeneralError",
        "message": "A general error has occurred.",
        "@Message.ExtendedInfo": [
            {"Message": "The resource is not supported on this platform.",
             "Resolution": "Upgrade the firmware."}]}}
    out = rg._extended_info(body)
    assert "Base.1.12.GeneralError" in out
    assert "not supported on this platform" in out
    assert "Upgrade the firmware." in out


def test_extended_info_handles_missing_error_envelope():
    """error 래퍼 없이 최상위에 ExtendedInfo 만 있는 벤더 응답도 처리."""
    out = rg._extended_info({"@Message.ExtendedInfo": [{"MessageId": "IDRAC.2.9.SWC0001"}]})
    assert out == "IDRAC.2.9.SWC0001"


@pytest.mark.parametrize("body", [None, [], "text", {}, {"error": {}}])
def test_extended_info_returns_none_when_nothing_to_say(body):
    assert rg._extended_info(body) is None


def test_extended_info_truncates():
    body = {"error": {"message": "x" * 5000}}
    assert len(rg._extended_info(body)) <= rg.MAX_EXTENDED_INFO_LEN


def test_network_adapters_all_paths_fail_records_detail(monkeypatch):
    """두 경로 모두 실패 시 errors[].detail 에 시도 경로 + BMC 확장 정보가 남아야 한다."""
    body = {"error": {"code": "Base.1.12.ResourceMissingAtURI",
                      "message": "The resource at the URI was not found."}}
    monkeypatch.setattr(rg, "_get",
                        lambda ip, path, *a, **kw: (400, body, "HTTP 400: Bad Request"))
    out, errors = rg.gather_network_adapters_chassis(
        "10.0.0.1", "/redfish/v1/Chassis/System.Embedded.1", "u", "p", 30, False,
        "/redfish/v1/Systems/System.Embedded.1")
    assert out == {"adapters": [], "ports": [], "fc_hbas": [], "infiniband": []}
    assert len(errors) == 1
    assert "HTTP 400" in errors[0]["message"]
    d = errors[0]["detail"]
    assert "Chassis/System.Embedded.1/NetworkAdapters" in d
    assert "Systems/System.Embedded.1/NetworkAdapters" in d
    assert "ResourceMissingAtURI" in d


# ── D. Systems 경로 fallback (사이트 근본원인 fix) ───────────────────────────
#
# 사이트 Dell R630(13G / iDRAC8 fw 2.7x~2.8x)은 NetworkAdapters 를 Chassis 가 아니라
# Systems 밑에 둔다 (Dell iDRAC8 Redfish API Guide 2.70.70.70). Chassis 만 물어보던 구
# 코드는 400 을 받고 NIC 카드 정보를 영구히 못 받았다.

CHASSIS = "/redfish/v1/Chassis/System.Embedded.1"
SYSTEM = "/redfish/v1/Systems/System.Embedded.1"
# _get 은 `_p()` 로 정규화된(=/redfish/v1/ 접두 제거) 경로를 받는다.
CH_NA = rg._p(CHASSIS) + "/NetworkAdapters"
SYS_NA = rg._p(SYSTEM) + "/NetworkAdapters"
NA_COLL = {"Members": [{"@odata.id": SYSTEM + "/NetworkAdapters/NIC.Integrated.1"}]}
NA_ITEM = {"Id": "NIC.Integrated.1", "Name": "Integrated NIC 1",
           "Manufacturer": "Broadcom", "Model": "BCM5720",
           "Controllers": [{"ControllerCapabilities": {"NetworkPortCount": 4},
                            "FirmwarePackageVersion": "21.80.9"}]}


def _routed_get(routes, calls):
    def fake_get(bmc_ip, path, *a, **kw):
        calls.append(path)
        if path in routes:
            return routes[path]
        return 404, {}, "HTTP 404: Not Found"
    return fake_get


def test_systems_fallback_collects_when_chassis_400(monkeypatch):
    """사이트 재현: Chassis=400 이어도 Systems 경로에서 NIC 카드를 실제로 수집한다."""
    calls = []
    routes = {
        CH_NA: (400, {}, "HTTP 400: Bad Request"),
        SYS_NA: (200, NA_COLL, None),
        rg._p(SYSTEM) + "/NetworkAdapters/NIC.Integrated.1": (200, NA_ITEM, None),
    }
    monkeypatch.setattr(rg, "_get", _routed_get(routes, calls))
    out, errors = rg.gather_network_adapters_chassis(
        "10.0.0.1", CHASSIS, "u", "p", 30, False, SYSTEM)
    assert [a["id"] for a in out["adapters"]] == ["NIC.Integrated.1"]
    assert out["adapters"][0]["model"] == "BCM5720"
    assert out["adapters"][0]["firmware_version"] == "21.80.9"
    assert out["adapters"][0]["port_count"] == 4
    assert not [e for e in errors if "미지원 또는 실패" in e["message"]]


def test_chassis_success_does_not_try_systems(monkeypatch):
    """1순위가 200 이면 2순위는 아예 시도 안 함 — 기존 장비 동작/왕복 불변 (Additive)."""
    calls = []
    routes = {
        CH_NA: (200, {"Members": []}, None),
    }
    monkeypatch.setattr(rg, "_get", _routed_get(routes, calls))
    rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, "u", "p", 30, False, SYSTEM)
    assert calls == [CH_NA]
    assert SYS_NA not in calls


def test_system_uri_absent_keeps_single_path(monkeypatch):
    """system_uri 미전달(구 호출부)이면 기존과 동일하게 Chassis 만 시도 — back-compat."""
    calls = []
    monkeypatch.setattr(rg, "_get", _routed_get({}, calls))
    out, errors = rg.gather_network_adapters_chassis(CHASSIS and "10.0.0.1", CHASSIS,
                                                    "u", "p", 30, False)
    assert calls == [CH_NA]
    assert len(errors) == 1 and "HTTP 404" in errors[0]["message"]


def test_duplicate_uri_not_requested_twice(monkeypatch):
    """chassis_uri == system_uri 인 펌웨어에서 같은 경로를 두 번 치지 않는다."""
    calls = []
    monkeypatch.setattr(rg, "_get", _routed_get({}, calls))
    rg.gather_network_adapters_chassis("10.0.0.1", CHASSIS, "u", "p", 30, False, CHASSIS)
    assert calls == [CH_NA]
