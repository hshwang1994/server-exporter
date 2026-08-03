"""보조 섹션(network_adapters) 실패가 network 섹션 status 를 덮지 않는지 회귀 (cycle 2026-08-03).

배경 (사이트 실측 — Jenkins DAY_1/git/소연등록redfish #1, Dell iDRAC 8대):
    `data.network` 는 정상 수집(interfaces 4 / gateway / summary)됐는데
    `sections.network=failed` + `status=partial` 로 emit 됐다. 원인은 2단:

      1. redfish_gather 모듈이 network(주=EthernetInterfaces) 와
         network_adapters(보조=NIC 카드 모델/펌웨어) 를 별도 raw 섹션으로 보고
      2. normalize_standard.yml `_rf_proc_map` 이 둘을 같은 'network' 로 collapse
         → build_sections 우선순위(not_supported > failed > success)에서 보조 실패가 승리

    같은 URL 이 실 Dell R740 미러에서는 200 이므로 요청 형식 문제가 아니라 장비/펌웨어
    차이다. 보조 수집 실패로 주 수집 성공이 가려지면 호출자는 매번 partial 을 받는다.

    fix: 세 status fragment(collected/failed/unsupported) 모두에서 보조 섹션 제외.
         보조 실패는 errors[] 로만 보고 (시나리오 B — build_status.yml 4시나리오 매트릭스).

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


# ── B. 400 → capability 부재 분류 ────────────────────────────────────────────

def test_capability_missing_accepts_400():
    errs = [{"section": "network_adapters",
             "message": "NetworkAdapters 미지원 또는 실패: HTTP 400: Bad Request",
             "detail": None}]
    assert rg._is_capability_missing_error(errs) is True


def test_capability_missing_accepts_404_and_mixed():
    assert rg._is_capability_missing_error(
        [{"message": "x: HTTP 404: Not Found"}]) is True
    assert rg._is_capability_missing_error(
        [{"message": "a: HTTP 404: Not Found"}, {"message": "b: HTTP 400: Bad Request"}]) is True


def test_capability_missing_rejects_auth_and_5xx():
    """401/403/5xx/timeout 은 capability 부재가 아니다 — failed 로 남아야 한다."""
    for msg in ["x: HTTP 401: Unauthorized", "x: HTTP 403: Forbidden",
                "x: HTTP 500: Internal Server Error", "x: Timeout after 30s"]:
        assert rg._is_capability_missing_error([{"message": msg}]) is False


def test_404_only_helper_unchanged_by_400_extension():
    """기존 _is_404_only_error 는 400 을 받아들이면 안 된다 (back-compat)."""
    assert rg._is_404_only_error([{"message": "x: HTTP 400: Bad Request"}]) is False
    assert rg._is_404_only_error([{"detail": "HTTP 404: Not Found"}]) is True
    assert rg._is_404_only_error([]) is False


def test_runner_classifies_400_empty_as_unsupported():
    all_errors, collected, failed, unsupported = [], [], [], []
    run = rg._make_section_runner(all_errors, collected, failed, unsupported)
    empty = {"adapters": [], "ports": [], "fc_hbas": [], "infiniband": []}
    run("network_adapters", lambda: (empty, [
        {"section": "network_adapters",
         "message": "NetworkAdapters 미지원 또는 실패: HTTP 400: Bad Request"}]))
    assert unsupported == ["network_adapters"]
    assert failed == [] and collected == []
    assert all_errors == []  # errors[] 노이즈 차단


def test_runner_keeps_400_with_data_as_failed():
    """부분 수집(결과 비어있지 않음)은 unsupported 로 숨기지 않는다 — EXC-1 가드 유지."""
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


def test_network_adapters_400_records_extended_detail(monkeypatch):
    """collection GET 400 시 errors[].detail 에 BMC 확장 정보가 남아야 한다 (기존: null)."""
    body = {"error": {"code": "Base.1.12.ResourceMissingAtURI",
                      "message": "The resource at the URI was not found."}}

    def fake_get(bmc_ip, path, *a, **kw):
        return 400, body, "HTTP 400: Bad Request"

    monkeypatch.setattr(rg, "_get", fake_get)
    out, errors = rg.gather_network_adapters_chassis(
        "10.0.0.1", "/redfish/v1/Chassis/System.Embedded.1",
        "u", "p", 30, False)
    assert out == {"adapters": [], "ports": [], "fc_hbas": [], "infiniband": []}
    assert len(errors) == 1
    assert "HTTP 400" in errors[0]["message"]
    assert errors[0]["detail"] and "ResourceMissingAtURI" in errors[0]["detail"]
