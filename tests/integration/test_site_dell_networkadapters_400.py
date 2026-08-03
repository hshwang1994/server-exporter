"""사이트 사고 재현 — Dell NetworkAdapters HTTP 400 → envelope partial (cycle 2026-08-03).

재현 대상 (실측):
    Jenkins DAY_1/git/소연등록redfish #1 — Dell iDRAC(RedfishVersion 1.4.0) 8대가 전부
        errors[]: NetworkAdapters 미지원 또는 실패: HTTP 400: Bad Request
        sections.network = failed  /  status = partial
    이면서 data.network 는 정상(interfaces 4 / default_gateways / summary.port_count 4).

    즉 보조 수집(NIC 카드 모델·펌웨어) 1건 실패가 주 수집(호스트 EthernetInterfaces) 성공을
    덮어 호출자에게 partial 을 돌려줬다.

본 테스트는 실 Dell R740 전수 미러(real_dell_r740)를 재생하되 NetworkAdapters 컬렉션
GET 만 400 으로 바꿔 사이트 조건을 만들고, 모듈 산출 → normalize fragment → build_sections
→ build_status 의 실제 식을 그대로 태워 최종 envelope status 를 검증한다.
(ansible-playbook CLI 는 이 환경에 부재 — YAML 식을 Jinja2 로 직접 렌더. rule 24 R1)

오프라인: recording.json 만 사용 — 네트워크 0.
"""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import jinja2
import pytest
import yaml

import emulator_harness as H

REPO = Path(__file__).resolve().parents[2]
CASE = REPO / "tests" / "fixtures" / "redfish" / "real_dell_r740"
NORM_STD = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
NORM_COMMON = REPO / "common" / "tasks" / "normalize"

NA_PATH = "get::Chassis/System.Embedded.1/NetworkAdapters"

# 사이트 iDRAC 이 돌려준 것과 같은 계열의 표준 오류 body (DMTF DSP0266 error 형식).
SITE_400_BODY = {
    "error": {
        "code": "Base.1.12.GeneralError",
        "message": "A general error has occurred. See ExtendedInfo for more information.",
        "@Message.ExtendedInfo": [
            {"Message": "The request is not supported on this resource.",
             "MessageId": "Base.1.12.ActionNotSupported",
             "Severity": "Critical"}],
    }
}


# ── YAML 실제 식 렌더 ────────────────────────────────────────────────────────

def _set_fact_value(path: Path, key: str):
    for t in yaml.safe_load(path.read_text(encoding="utf-8")):
        sf = t.get("ansible.builtin.set_fact") or t.get("set_fact") or {}
        if key in sf:
            return sf[key]
    raise AssertionError(f"{path.name}: {key} set_fact 식 없음")


def _render(expr, **ctx):
    return ast.literal_eval(
        jinja2.Environment().from_string(expr).render(**ctx).strip())


def _envelope_sections_and_status(result):
    """모듈 산출 → normalize_standard fragment → build_sections → build_status."""
    common = dict(
        _rf_proc_map=_set_fact_value(NORM_STD, "_rf_proc_map"),
        _rf_aux_sections=_set_fact_value(NORM_STD, "_rf_aux_sections"),
    )
    collected = _render(_set_fact_value(NORM_STD, "_sections_collected_fragment"),
                        _rf_collected_raw=result["collected"], **common)
    failed = _render(_set_fact_value(NORM_STD, "_sections_failed_fragment"),
                     _rf_failed_raw=result["failed_sections"], **common)
    unsupported = _render(_set_fact_value(NORM_STD, "_sections_unsupported_fragment"),
                          _rf_unsupported_raw=result["unsupported_sections"], **common)
    supported = _render(_set_fact_value(NORM_STD, "_sections_supported_fragment"))

    sections = _render(
        _set_fact_value(NORM_COMMON / "build_sections.yml", "_norm_sections"),
        _all_sec_supported=supported, _all_sec_collected=collected,
        _all_sec_failed=failed, _all_sec_unsupported=unsupported)
    status = jinja2.Environment().from_string(
        _set_fact_value(NORM_COMMON / "build_status.yml", "_out_status")
    ).render(_norm_sections=sections).strip()
    return sections, status


def _replay(mutate=None):
    recording = json.loads((CASE / "recording.json").read_text(encoding="utf-8"))
    if mutate:
        recording = mutate(copy.deepcopy(recording))
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    meta = json.loads((CASE / "meta.json").read_text(encoding="utf-8"))
    return H.run_gather(get_impl, noauth_impl, realm_impl=realm_impl,
                        manager_layout=meta.get("manager_layout"))


def _force_na_400(recording):
    """NetworkAdapters 컬렉션 GET 만 400 으로 — sub-member 는 요청되지 않으므로 제거."""
    for key in [k for k in recording if k.startswith(NA_PATH)]:
        del recording[key]
    recording[NA_PATH] = [400, SITE_400_BODY, "HTTP 400: Bad Request"]
    return recording


@pytest.fixture(scope="module")
def site_result():
    if not (CASE / "recording.json").is_file():
        pytest.skip("real_dell_r740 fixture 없음")
    return _replay(_force_na_400)


@pytest.mark.integration
class TestSiteDellNetworkAdapters400:

    def test_baseline_mirror_still_collects_network_adapters(self):
        """대조군: 원본 미러(200)는 여전히 NIC 카드를 수집한다 (회귀 가드)."""
        if not (CASE / "recording.json").is_file():
            pytest.skip("real_dell_r740 fixture 없음")
        result = _replay()
        assert result["data"]["network_adapters"]["adapters"], "원본 미러에서 adapters 수집 회귀"
        _, status = _envelope_sections_and_status(result)
        assert status == "success"

    def test_400_classified_as_capability_missing(self, site_result):
        """400 + 결과 완전 빈값 → unsupported 분류 (failed/errors[] 노이즈 아님)."""
        assert "network_adapters" in site_result["unsupported_sections"]
        assert "network_adapters" not in site_result["failed_sections"]

    def test_primary_network_still_collected(self, site_result):
        """주 수집(호스트 EthernetInterfaces)은 영향 없음 — 사이트 envelope 과 동일."""
        assert "network" in site_result["collected"]
        assert site_result["data"]["network"], "data.network 소실"

    def test_sections_network_success_not_masked(self, site_result):
        """핵심: 보조 실패가 sections.network 를 failed/not_supported 로 덮지 않는다."""
        sections, _ = _envelope_sections_and_status(site_result)
        assert sections["network"] == "success"

    def test_overall_status_not_partial(self, site_result):
        """사이트 증상(status=partial)이 재현되지 않아야 한다."""
        _, status = _envelope_sections_and_status(site_result)
        assert status == "success"

    def test_prefix_behavior_would_have_been_partial(self, site_result):
        """가드의 가드: 보조 제외를 빼면(=수정 전 로직) 실제로 사이트 증상이 재현된다.

        이 테스트가 없으면 위 4건이 '원래부터 통과하던' 무의미한 회귀일 수 있다.
        수정 전 로직 = network_adapters 를 network 로 collapse + 보조 제외 없음.
        """
        pmap = _set_fact_value(NORM_STD, "_rf_proc_map")
        assert pmap["network_adapters"] == "network", "collapse 전제 변경 — 본 재현 무효"

        def old_map(raw):
            out = []
            for s in raw:
                m = pmap.get(s, s)
                if m not in out:
                    out.append(m)
            return out

        supported = _render(_set_fact_value(NORM_STD, "_sections_supported_fragment"))
        sections = _render(
            _set_fact_value(NORM_COMMON / "build_sections.yml", "_norm_sections"),
            _all_sec_supported=supported,
            _all_sec_collected=old_map(site_result["collected"]),
            _all_sec_failed=old_map(site_result["failed_sections"]),
            # 수정 전에는 400 이 unsupported 가 아니라 failed 였다 — 그 조건을 명시 주입
            _all_sec_unsupported=[])
        old_sections = dict(sections)
        old_sections["network"] = "failed"  # 수정 전 모듈은 network_adapters 를 failed 로 보고
        status = jinja2.Environment().from_string(
            _set_fact_value(NORM_COMMON / "build_status.yml", "_out_status")
        ).render(_norm_sections=old_sections).strip()
        assert status == "partial", "사이트 증상 재현 실패 — 본 fixture 로는 버그를 못 잡는다"
