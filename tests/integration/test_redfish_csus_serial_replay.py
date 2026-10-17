"""CSUS 3200 Redfish `hardware.serial` nPartition 접미사 — 실장비 캡처 재생 (2026-10-17 사용자 결정).

실 미러 캡처(real_hpe_csus3200, 2026-06 사이트)의 `Systems/Partition0.SerialNumber` 는 `SGHD3TLNDD-000` 이다. 모듈은 그 원문을
`data.system.serial` 에 그대로 두고(골든 불변), `normalize_standard.yml` 의 `hardware.serial` 식이 OS 채널과 같은
`normalize_os_serial` 필터(HPE alias · CSUS 3200 모델 · `-NNN` 세 조건)로 접미사를 뗀다 → `SGHD3TLNDD`. `correlation.serial_number` 는
`build_correlation.yml` 이 `hardware.serial` 을 복사한다. `multi_node.partitions[].system.serial` 은 원문(-000). 다른 실 캡처
(Dell R740 · HPE DL380 · Lenovo SR650)는 값이 바뀌지 않는다. 네트워크 0. 실장비 재수집 확인은 사이트 몫(CSUS lab 부재).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

from test_redfish_hostname_policy_replay import _replay, _set_fact

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from serial_normalizer import normalize_os_serial  # noqa: E402

CORRELATION = REPO / "common" / "tasks" / "normalize" / "build_correlation.yml"


def _env():
    env = NativeEnvironment()
    env.filters["normalize_os_serial"] = normalize_os_serial
    return env


def _hardware_serial(result):
    frag = _set_fact("build standard fragment")["_data_fragment"]
    return _env().from_string(frag["hardware"]["serial"]).render(_rf_d_system=result["data"]["system"])


def _correlation_serial_expr():
    for t in yaml.safe_load(CORRELATION.read_text(encoding="utf-8")):
        sf = t.get("ansible.builtin.set_fact") if isinstance(t, dict) else None
        if isinstance(sf, dict):
            for k, v in sf.items():
                if isinstance(v, dict) and "serial_number" in v:
                    return v["serial_number"]
                if isinstance(v, str) and "serial_number" in k:
                    return v
    raise AssertionError("build_correlation.yml 의 serial_number 식 미발견")


@pytest.mark.integration
class TestCsusSerialReplay:
    def test_csus_capture_hardware_serial_loses_npar_suffix(self):
        result = _replay("real_hpe_csus3200")
        assert result["data"]["system"]["serial"] == "SGHD3TLNDD-000", "모듈 원본은 그대로 (골든 불변)"
        assert _hardware_serial(result) == "SGHD3TLNDD"
        assert result["multi_node"]["partitions"][0]["system"]["serial"] == "SGHD3TLNDD-000", "파티션 원본 유지"
        assert result["data"]["bmc"]["serial"] == "SGHD3TLNDD"

    def test_correlation_follows_hardware_serial(self):
        """build_correlation.yml 은 hardware.serial 을 먼저 보므로 접미사 없는 값이 correlation 으로 간다."""
        expr = _correlation_serial_expr()
        env = NativeEnvironment()
        merged = {"hardware": {"serial": "SGHD3TLNDD"}, "system": {}}
        assert env.from_string(expr).render(_merged_data=merged, _collected_data=merged) == "SGHD3TLNDD"


@pytest.mark.integration
@pytest.mark.parametrize("case", ["real_dell_r740", "real_hpe_dl380", "real_lenovo_sr650"])
def test_other_vendors_hardware_serial_unchanged(case):
    result = _replay(case)
    assert _hardware_serial(result) == result["data"]["system"]["serial"]
