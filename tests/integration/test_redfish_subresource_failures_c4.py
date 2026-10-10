"""Redfish 하위 리소스 조회 실패를 빈 목록으로 숨기지 않는다 (2026-10-10 C4).

종전 결함(검수 2026-10-09, 실 미러 재생 + 실패 주입):
  - NetworkAdapter 의 개별 Port 가 HTTP 503 이면 그 포트가 조용히 빠졌다(real_hpe_dl380: ports 10 → 9, errors 없음).
  - Storage 의 Volumes 컬렉션이 HTTP 503 이면 volumes 가 조용히 0 이 됐다(real_dell_r740: 1 → 0, errors 없음).
수정: 404(Volumes 미노출)만 정상 미지원으로 두고, 그 밖의 실패와 나열된 Port 의 실패는 비차단 code(_CODE_NON_BLOCKING_SUBRESOURCE)로
기록한다. storage 는 기존 section runner 로 failed(호스트 partial), network_adapters 는 보조 수집이라 network 섹션은 성공 그대로이고
errors[] 에만 남는다. code 가 있으므로 하위 403 이 로그인 전체 실패(host failed)로 읽히지 않는다.

모듈 main() 을 실 미러(recording.json) 재생으로 돌리고(네트워크 0), normalize_standard → build_sections → build_status 의 실제 식으로
최종 envelope 의 섹션 · status · errors[] 를 확인한다.
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
FIX = REPO / "tests" / "fixtures" / "redfish"
NORM_STD = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
NORM_COMMON = REPO / "common" / "tasks" / "normalize"
SM = yaml.safe_load((REPO / "common" / "vars" / "section_messages.yml").read_text(encoding="utf-8"))

rg = H.rg
HPE_PORT = "Chassis/1/NetworkAdapters/DE040000/Ports/1"
DELL_VOLUMES = "Systems/System.Embedded.1/Storage/RAID.Slot.6-1/Volumes"


class _Captured(Exception):
    def __init__(self, result):
        self.result = result


class _Module:
    def __init__(self, **kwargs):
        self.check_mode = False
        self.params = {"bmc_ip": "192.0.2.1", "username": "std", "password": "<pw>", "timeout": 30, "verify_ssl": False,
                       "mode": "gather", "manager_layout": None, "attempt": None}

    def exit_json(self, **result):
        raise _Captured(result)

    def fail_json(self, **result):
        raise AssertionError(result)


def _gather(monkeypatch, fixture, status=None, path=None, body=None):
    recording = json.loads((FIX / fixture / "recording.json").read_text(encoding="utf-8"))
    if status is not None:
        recording = copy.deepcopy(recording)
        assert ("get::" + path) in recording, path
        recording["get::" + path] = [status, body or {}, f"HTTP {status}: injected" if status else "Timeout after 30s"]
    get_impl, noauth_impl, realm_impl = H.make_replayer(recording)
    monkeypatch.setattr(rg, "_get_impl", get_impl)
    monkeypatch.setattr(rg, "_get_noauth", noauth_impl)
    if realm_impl is not None:
        monkeypatch.setattr(rg, "_probe_realm_hint", realm_impl)
    monkeypatch.setattr(rg, "AnsibleModule", _Module)
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)
    try:
        rg.main()
    except _Captured as caught:
        return caught.result
    raise AssertionError("module did not return")


def _set_fact_value(path, key):
    for t in yaml.safe_load(path.read_text(encoding="utf-8")):
        sf = t.get("ansible.builtin.set_fact") or {}
        if key in sf:
            return sf[key]
    raise AssertionError(f"{path.name}: {key}")


def _render(expr, **ctx):
    return ast.literal_eval(jinja2.Environment().from_string(expr).render(**ctx).strip())


def _envelope(result):
    """모듈 결과 → normalize_standard(섹션 · errors fragment) → build_sections → build_status."""
    common = dict(_rf_proc_map=_set_fact_value(NORM_STD, "_rf_proc_map"), _rf_aux_sections=_set_fact_value(NORM_STD, "_rf_aux_sections"))
    collected = _render(_set_fact_value(NORM_STD, "_sections_collected_fragment"), _rf_collected_raw=result["collected"], **common)
    failed = _render(_set_fact_value(NORM_STD, "_sections_failed_fragment"), _rf_failed_raw=result["failed_sections"], **common)
    unsupported = _render(_set_fact_value(NORM_STD, "_sections_unsupported_fragment"),
                          _rf_unsupported_raw=result.get("unsupported_sections", []), **common)
    supported = _render(_set_fact_value(NORM_STD, "_sections_supported_fragment"))
    sections = _render(_set_fact_value(NORM_COMMON / "build_sections.yml", "_norm_sections"),
                       _all_sec_supported=supported, _all_sec_collected=collected, _all_sec_failed=failed, _all_sec_unsupported=unsupported)
    status = jinja2.Environment().from_string(_set_fact_value(NORM_COMMON / "build_status.yml", "_out_status")).render(
        _norm_sections=sections).strip()
    errors = _render(_set_fact_value(NORM_STD, "_errors_fragment"), _rf_raw_collect=result, **SM)
    return sections, status, errors


def _coded(result, section, needle):
    return [e for e in result["errors"] if e.get("section") == section and needle in e.get("message", "")
            and e.get("code") == rg._CODE_NON_BLOCKING_SUBRESOURCE]


def test_unchanged_recordings_still_have_no_errors(monkeypatch):
    for fixture in ("real_hpe_dl380", "real_dell_r740"):
        r = _gather(monkeypatch, fixture)
        assert r["status"] == "success" and r["errors"] == [] and r["failed_sections"] == [], fixture


@pytest.mark.parametrize("status", [503, 403, 404, 0])
def test_failed_port_member_is_recorded_and_other_ports_are_kept(monkeypatch, status):
    base = _gather(monkeypatch, "real_hpe_dl380")
    r = _gather(monkeypatch, "real_hpe_dl380", status, HPE_PORT)
    assert len(r["data"]["network_adapters"]["ports"]) == len(base["data"]["network_adapters"]["ports"]) - 1
    hits = _coded(r, "network_adapters", "Ports/1 실패")
    assert len(hits) == 1, r["errors"]
    assert r["status"] == "partial", "하위 실패는 host failed 가 아니다(403 포함)"
    assert "network_adapters" in r["failed_sections"]
    sections, env_status, errors = _envelope(r)
    assert sections["network"] == "success", "보조 수집 실패로 network 섹션을 실패로 바꾸지 않는다"
    assert env_status == "success"
    net = [e for e in errors if e["section"] == "network"]
    assert len(net) == 1 and "DE040000/Ports/1" in (net[0]["detail"] or ""), errors


@pytest.mark.parametrize("status", [503, 403, 0])
def test_failed_volumes_collection_is_recorded_and_storage_is_partial(monkeypatch, status):
    base = _gather(monkeypatch, "real_dell_r740")
    r = _gather(monkeypatch, "real_dell_r740", status, DELL_VOLUMES)
    assert len(r["data"]["storage"]["volumes"]) == len(base["data"]["storage"]["volumes"]) - 1
    assert r["data"]["storage"]["controllers"] == base["data"]["storage"]["controllers"], "이미 읽은 Storage 데이터는 그대로"
    hits = _coded(r, "storage", "Volumes")
    assert len(hits) == 1, r["errors"]
    assert r["status"] == "partial" and "storage" in r["failed_sections"]
    sections, env_status, errors = _envelope(r)
    assert sections["storage"] == "failed" and env_status == "partial"
    assert any(e["section"] == "storage" and "RAID.Slot.6-1/Volumes" in (e["detail"] or "") for e in errors), errors


def test_volumes_404_stays_a_normal_unsupported_case(monkeypatch):
    r = _gather(monkeypatch, "real_dell_r740", 404, DELL_VOLUMES)
    assert r["errors"] == [] and r["status"] == "success"
    sections, env_status, _ = _envelope(r)
    assert sections["storage"] == "success" and env_status == "success"
