"""Redfish power / thermal — legacy 와 신 schema 둘 다 404 면 not_supported 다 (2026-10-12).

재현한 결함: `/Power` 404 → `/PowerSubsystem` 404 (그리고 `/Thermal` 404 → `/ThermalSubsystem` 404) 에서 함수가 `({}, [])` 를 돌려줘
section runner 가 그 섹션을 **collected** 로 넣었다 → `sections.power = success` 인데 `data.power = null` 인 거짓 성공.

고친 규칙: 404 도 오류로 돌려준다. `_make_section_runner` 의 404-only 판정이 그 섹션을 unsupported 로 분류하고 errors[] 에는 남기지 않는다.
PowerSubsystem 이 200 으로 답하는 경로(신 펌웨어)는 그대로 수집된다.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

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

CREDS = ("u", "p", 5, False)


def _get_all_404(monkeypatch):
    def fake_get(bmc_ip, path, *a, **k):
        return 404, None, None
    monkeypatch.setattr(rg, "_get", fake_get)


def test_power_both_404_is_classified_not_supported(monkeypatch):
    _get_all_404(monkeypatch)
    data, errs = rg.gather_power("10.0.0.1", "/redfish/v1/Chassis/1", *CREDS)
    assert data == {}
    assert len(errs) == 1 and errs[0]["section"] == "power" and rg._is_404_only_error(errs)
    all_errors, collected, failed, unsupported = [], [], [], []
    run = rg._make_section_runner(all_errors, collected, failed, unsupported)
    run("power", rg.gather_power, "10.0.0.1", "/redfish/v1/Chassis/1", *CREDS)
    assert unsupported == ["power"]
    assert collected == [] and failed == [] and all_errors == []   # 거짓 success 도, errors[] 소음도 없다


def test_thermal_both_404_is_classified_not_supported(monkeypatch):
    _get_all_404(monkeypatch)
    all_errors, collected, failed, unsupported = [], [], [], []
    run = rg._make_section_runner(all_errors, collected, failed, unsupported)
    run("thermal", rg.gather_thermal, "10.0.0.1", "/redfish/v1/Chassis/1", *CREDS)
    assert unsupported == ["thermal"] and collected == [] and failed == [] and all_errors == []


def test_power_subsystem_transport_error_is_a_failure_not_unsupported(monkeypatch):
    """404 가 아닌 오류(연결 실패 · 5xx)는 종전대로 그 섹션 실패다 — 미지원으로 덮지 않는다."""
    def fake_get(bmc_ip, path, *a, **k):
        if path.endswith("/Power"):
            return 404, None, None
        return None, None, "connection refused"
    monkeypatch.setattr(rg, "_get", fake_get)
    all_errors, collected, failed, unsupported = [], [], [], []
    run = rg._make_section_runner(all_errors, collected, failed, unsupported)
    run("power", rg.gather_power, "10.0.0.1", "/redfish/v1/Chassis/1", *CREDS)
    assert failed == ["power"] and unsupported == [] and len(all_errors) == 1
