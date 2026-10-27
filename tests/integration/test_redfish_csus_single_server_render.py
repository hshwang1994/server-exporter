"""CSUS 3200 단일 서버 정합 — 실장비 캡처(real_hpe_csus3200, node01 · SAN boot) 재생 + normalize_standard 렌더 (2026-10-19).

사용자 요구: CSUS 도 다른 x86 서버와 같은 JSON 형태, Partition0 = 서버, 시리얼은 `-000` 을 뗀 물리 시리얼.
실 4노드 전수 미러 재검수(tests/evidence/2026-10-19-csus-single-server-summary-audit.md)에서 고친 값을 실 녹화본으로 고정한다.
네트워크 0. 사이트 재수집 확인은 사용자 몫(CSUS lab 부재).
"""
from __future__ import annotations

import sys
from pathlib import Path

import re

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

from test_redfish_hostname_policy_replay import _replay, _set_fact

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from identity_normalizer import normalize_uuid, uuid_byteswap  # noqa: E402
from serial_normalizer import normalize_os_serial  # noqa: E402

ADAPTER = yaml.safe_load((REPO / "adapters" / "redfish" / "hpe_csus_3200.yml").read_text(encoding="utf-8"))


def _env():
    env = NativeEnvironment()
    env.filters.update({"normalize_os_serial": normalize_os_serial, "normalize_uuid": normalize_uuid, "uuid_byteswap": uuid_byteswap,
                        "regex_replace": lambda v, pat, rep="", *a, **k: re.sub(pat, rep, str(v))})   # ansible 필터 최소 대역
    return env


def _render(expr, **ctx):
    return _env().from_string(expr).render(**ctx)


@pytest.fixture(scope="module")
def csus():
    return _replay("real_hpe_csus3200")


@pytest.mark.integration
class TestCsusSingleServer:
    def test_serial_and_part_number_from_partition_and_chassis(self, csus):
        frag = _set_fact("build standard fragment")["_data_fragment"]
        sysd = csus["data"]["system"]
        assert sysd["serial"] == "SGHD3TLNDD-000", "모듈 원본은 파티션 시리얼 그대로"
        assert _render(frag["hardware"]["serial"], _rf_d_system=sysd) == "SGHD3TLNDD"
        assert sysd["part_number"] == "R9N70A", "Partition0 에 없는 PartNumber 는 섀시(r001u01) 값 (A-7)"
        assert csus["multi_node"]["partitions"][0]["system"]["serial"] == "SGHD3TLNDD-000", "multi_node 는 그대로 (사용자 결정 2026-10-19)"

    def test_redfish_cpu_has_no_logical_threads_key(self, csus):
        """2026-10-27 FIX 1: BMC 스레드 수(RMC 1.75 는 LogicalProcessorCount 가 코어 수 32, 1.77 은 스레드 수)는 OS 와 같은 값을 보장하지 못해
        Redfish 는 cpu.logical_threads 를 내지 않는다 — top-level 과 multi_node.partitions[].cpu 둘 다. 모듈 raw 요약값은 BMC 원값으로 남는다."""
        frag = _set_fact("build standard fragment")["_data_fragment"]
        assert "logical_threads" not in frag["cpu"]
        assert "manufacturer" in frag["cpu"], "FIX 2 — Processor.Manufacturer 정규화 발행"
        assert csus["data"]["system"]["cpu_summary"]["logical_processor_count"] == 32, "RMC 1.75.108 fixture — raw 는 그대로 보존"
        assert "logical_threads" not in csus["multi_node"]["partitions"][0]["cpu"]
        assert csus["multi_node"]["partitions"][0]["cpu"]["cores_physical"] == 32

    def test_power_summary_has_no_fabricated_zero(self, csus):
        s = _render(_set_fact("compute group summaries")["_rf_power_summary"], _rf_d_power=csus["data"]["power"])
        assert s["psu_count"] == 4 and s["capacity_unknown_count"] == 4
        assert s["total_capacity_w"] is None and s["consumed_capacity_pct"] is None
        assert s["consumed_watts"] == 591

    def test_network_summary_does_not_count_fc_hba_cards(self, csus):
        netad = csus["data"]["network_adapters"]
        assert len(netad["fc_hbas"]) == 4 and len(netad["adapters"]) == 2, "HBA 4 · FC 카드 2 (불변)"
        s = _render(_set_fact("compute group summaries")["_rf_summary_network"], _rf_d_netad=netad, _rf_norm_interfaces=[])
        assert s["adapter_count"] == 0 and s["port_count"] == 0

    def test_empty_storage_container_dropped_and_firmware_supplemented(self, csus):
        ctrls = _render(_set_fact("controllers")["_rf_norm_controllers"], _rf_d_storage=csus["data"]["storage"])
        assert ctrls == [], "node01 'Npar 0 Storage' 는 모델 · 드라이브 · 볼륨이 없는 빈 컨테이너 (A-6)"
        fw_ids = [f["id"] for f in csus["data"]["firmware"]]
        assert fw_ids[:2] == ["ComplexFW", "Partition0_FW"]
        assert fw_ids[2:] == ["PowerSupply.0", "PowerSupply.1", "PowerSupply.2", "PowerSupply.3"], \
            "node01 PCIe 장치(FC HBA)는 FirmwareVersion 이 없어 PSU 만 보충된다 (A-9)"


@pytest.mark.integration
@pytest.mark.parametrize("case", ["real_dell_r740", "real_hpe_dl380", "real_lenovo_sr650"])
def test_other_vendors_power_and_adapter_count_unchanged_semantics(case):
    """정보를 주는 벤더는 null 규칙 · FC 제외 규칙이 값을 바꾸지 않는다 (용량 있음 · FC 카드만 빠짐)."""
    result = _replay(case)
    power = result["data"]["power"]
    s = _render(_set_fact("compute group summaries")["_rf_power_summary"], _rf_d_power=power)
    assert s["total_capacity_w"] == sum(p["power_capacity_w"] for p in power["power_supplies"] if p.get("power_capacity_w") is not None)
    netad = result["data"]["network_adapters"]
    fc_only = {h["adapter_id"] for h in netad["fc_hbas"]} - {p["adapter_id"] for p in netad["ports"] if p.get("port_type") == "Ethernet"}
    s = _render(_set_fact("compute group summaries")["_rf_summary_network"], _rf_d_netad=netad, _rf_norm_interfaces=[])
    assert s["adapter_count"] == len(netad["adapters"]) - len(fc_only)
