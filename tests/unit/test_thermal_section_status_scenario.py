"""ATX-01/02 회귀 — thermal 섹션이 build_sections / skeleton 에 배선됐는지 (2026-06-15).

Track4(2026-06-14)가 thermal 을 라이브러리·supported_sections·normalize 엔 추가했으나
공통 builder(build_sections.yml all_sec) + 3 skeleton(init_fragments/build_empty_data/
build_failed_output)에는 누락 → 정상/실패 envelope 의 sections.thermal 미emit + status 미반영.
본 테스트는 (1) build_sections 가 redfish 에서 sections.thermal 을 내보내는지 실제 템플릿
렌더로, (2) 3 skeleton 에 thermal 키가 동기화됐는지 구조 파싱으로 검증.
"""
from __future__ import annotations

import ast
from pathlib import Path

import yaml
from jinja2 import Environment

NORM = Path(__file__).resolve().parents[2] / "common" / "tasks" / "normalize"


def _set_fact_value(name: str, var: str):
    tasks = yaml.safe_load((NORM / name).read_text(encoding="utf-8"))
    for t in tasks or []:
        sf = t.get("ansible.builtin.set_fact") or t.get("set_fact") or {}
        if var in sf:
            return sf[var]
    raise AssertionError(f"{name}: set_fact {var} 없음")


def _render_sections(supported, collected, failed=None, unsupported=None) -> dict:
    tmpl = Environment().from_string(_set_fact_value("build_sections.yml", "_norm_sections"))
    out = tmpl.render(_all_sec_supported=supported, _all_sec_collected=collected,
                      _all_sec_failed=failed or [], _all_sec_unsupported=unsupported or [])
    return ast.literal_eval(out.strip())


REDFISH_SUPPORTED = ["hardware", "bmc", "cpu", "memory", "storage", "network",
                     "firmware", "power", "thermal"]


def test_redfish_thermal_collected_is_success():
    """redfish 가 thermal 수집 성공 시 sections.thermal == 'success' (수정 전: 키 부재)."""
    sec = _render_sections(REDFISH_SUPPORTED, REDFISH_SUPPORTED)
    assert "thermal" in sec, "sections 에 thermal 키 부재 (build_sections all_sec 누락)"
    assert sec["thermal"] == "success"


def test_redfish_thermal_failed_propagates():
    """thermal 수집 실패 시 sections.thermal == 'failed' (overall status 에 반영되도록)."""
    sup = REDFISH_SUPPORTED
    col = [s for s in sup if s != "thermal"]
    sec = _render_sections(sup, col, failed=["thermal"])
    assert sec["thermal"] == "failed"


def test_os_channel_thermal_not_supported():
    """os/esxi(thermal 미지원)는 sections.thermal == 'not_supported' (다채널 일관)."""
    os_supported = ["system", "cpu", "memory", "storage", "network", "users"]
    sec = _render_sections(os_supported, os_supported)
    assert sec["thermal"] == "not_supported"


def test_failed_output_all_sec_has_thermal():
    """실패 fallback build_failed_output all_sec 에도 thermal 포함."""
    raw = (NORM / "build_failed_output.yml").read_text(encoding="utf-8")
    anchor = raw[raw.index("set all_sec ="):]
    block = anchor[: anchor.index("-%}")]
    assert "'thermal'" in block, "build_failed_output all_sec 에 thermal 누락"


def test_three_skeletons_have_thermal():
    """init_fragments / build_empty_data 의 _merged_data·_norm_empty_data 에 thermal 키 동기화."""
    merged = _set_fact_value("init_fragments.yml", "_merged_data")
    empty = _set_fact_value("build_empty_data.yml", "_norm_empty_data")
    assert merged.get("thermal") == {"temperatures": [], "fans": []}
    assert empty.get("thermal") == {"temperatures": [], "fans": []}
    # build_failed_output data fallback 텍스트에 thermal 키
    raw = (NORM / "build_failed_output.yml").read_text(encoding="utf-8")
    assert "'thermal'" in raw[raw.index("'data': _merged_data | default({"):]
