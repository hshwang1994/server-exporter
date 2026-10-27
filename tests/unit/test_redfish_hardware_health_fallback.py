"""hardware.health 원천 — System.Status.Health 가 없을 때만 HealthRollup (2026-10-27, 2차 Mock 01-hardware-002).

실측: iLO 7 gen12 Health Warning / HealthRollup Warning(PSU Critical 인데 Warning — Critical 은 Oem AggregateServerHealth 에만),
1차 SR650 Health Warning / HealthRollup OK(리소스 자체 값 유지), XCC 3 V4 Health Critical(HealthRollup 없음). 18 label 전부 Health 가 있어 값 불변.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

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


def _fake_get(system_data):
    def fake_get(bmc_ip, path, username, password, timeout, verify_ssl):
        return 200, system_data, None
    return fake_get


@pytest.mark.parametrize("status, expected", [
    ({"Health": "Warning", "HealthRollup": "Warning"}, "Warning"),   # iLO 7 gen12_01/02/04 실측
    ({"Health": "Warning", "HealthRollup": "OK"}, "Warning"),        # 1차 SR650 실측 — 리소스 자체 값 유지
    ({"Health": "Critical"}, "Critical"),                            # XCC 3 V4 (HealthRollup 없음)
    ({"Health": "OK", "HealthRollup": "Critical"}, "OK"),            # 합성 — Health 가 있으면 Rollup 으로 바꾸지 않는다
    ({"HealthRollup": "OK"}, "OK"),                                  # 합성 — Health 없음 → 폴백
    ({"Health": None, "HealthRollup": "Warning"}, "Warning"),        # 합성 — null → 폴백
    ({"Health": "", "HealthRollup": "Warning"}, "Warning"),          # 합성 — 빈 문자열 → 폴백
    ({}, None),
])
def test_system_health_falls_back_to_rollup_only_when_health_is_missing(monkeypatch, status, expected):
    monkeypatch.setattr(rg, "_get", _fake_get({"Manufacturer": "X", "Model": "Y", "SerialNumber": "S", "UUID": "u", "Status": status}))
    res, errs = rg.gather_system("1.2.3.4", "/redfish/v1/Systems/1", "hpe", "u", "p", 5, False)
    assert res["health"] == expected
