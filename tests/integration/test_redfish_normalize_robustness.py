"""multi_node 정규화 함수 fault-injection 회귀 (crash 가드).

배경:
    redfish_gather.py 의 단일 노드 수집기는 _safe_int 로 비-숫자 캐스팅을 방어하지만,
    multi_node(HPE CSUS 3200 / Superdome Flex RMC) 전용 정규화 함수들은 bare int() / // 를
    써서 BMC 펌웨어가 capacity/cores 를 **문자열**로 반환하면 모듈 전체가 ValueError/TypeError
    로 죽는다 → envelope 자체가 안 나온다(catastrophic). 본 테스트는 그 crash 를 드러내고
    (RED), _safe_int 가드 후 graceful degrade 를 고정(GREEN)한다.

    정상(int) 입력 결과는 가드 전후 동일(_safe_int(n)==int(n)) — golden 불변.

대상 함수 (순수 함수 — 네트워크 0):
    _summarize_partition_disks / _normalize_cpu_raw / _normalize_memory_raw
"""
from __future__ import annotations

import pytest

import emulator_harness as H

rg = H.rg


# ===========================================================================
# _summarize_partition_disks — total_mb 가 문자열이면 `str // int` TypeError
# ===========================================================================
class TestSummarizePartitionDisks:
    def test_string_total_mb_does_not_crash(self):
        """BMC 가 total_mb 를 '16384'(문자열)로 → 가드 전 TypeError. 가드 후 graceful."""
        disks = [{"total_mb": "16384", "media_type": "SSD",
                  "protocol": "NVMe", "model": "MZ-X"}]
        out = rg._summarize_partition_disks(disks)  # 가드 전: TypeError
        assert isinstance(out, dict) and "groups" in out and "grand_total_gb" in out
        # '16384' MiB → 16 GiB 로 정상 해석(숫자형 문자열은 보존)
        assert out["grand_total_gb"] == 16

    def test_non_numeric_total_mb_skipped(self):
        """비-숫자 문자열은 0 으로 떨어져 그룹에서 제외 (crash 아님)."""
        disks = [{"total_mb": "N/A", "media_type": "HDD", "model": "X"}]
        out = rg._summarize_partition_disks(disks)
        assert out["groups"] == [] and out["grand_total_gb"] == 0

    def test_wellformed_int_unchanged(self):
        """정상 int 입력은 가드 전후 동일 결과 (golden 불변 보장)."""
        disks = [{"total_mb": 1024 * 1024, "media_type": "SSD",
                  "protocol": "SAS", "model": "M1"}]
        out = rg._summarize_partition_disks(disks)
        assert out["grand_total_gb"] == 1024
        assert out["groups"][0]["unit_capacity_gb"] == 1024


# ===========================================================================
# _normalize_cpu_raw — total_cores 문자열이면 int() ValueError (sum + grouping)
# ===========================================================================
class TestNormalizeCpuRaw:
    def test_string_total_cores_does_not_crash(self):
        """total_cores='eight' → 가드 전 int() ValueError(L2976 sum + L2985 grouping)."""
        procs = [{"total_cores": "eight", "total_threads": "sixteen",
                  "model": "Xeon X", "processor_type": "CPU"}]
        out = rg._normalize_cpu_raw(procs)  # 가드 전: ValueError
        assert isinstance(out, dict) and "summary" in out
        # 비-숫자 → 0 으로 합산, 소켓 수는 유지
        assert out["sockets"] == 1
        assert out["cores_physical"] is None  # 0 → None (기존 `or None` 로직)

    def test_decimal_string_cores_does_not_crash(self):
        """total_cores='12.5'(소수 문자열) → int('12.5') ValueError."""
        procs = [{"total_cores": "12.5", "model": "Y", "processor_type": "CPU"}]
        out = rg._normalize_cpu_raw(procs)
        assert out["sockets"] == 1

    def test_wellformed_int_unchanged(self):
        """정상 int → 가드 전후 동일 (12 cores / 24 threads)."""
        procs = [{"total_cores": 12, "total_threads": 24,
                  "model": "Xeon Silver 4310", "processor_type": "CPU"}]
        out = rg._normalize_cpu_raw(procs)
        assert out["cores_physical"] == 12
        assert out["logical_threads"] == 24
        assert out["summary"]["groups"][0]["total_cores"] == 12


# ===========================================================================
# _normalize_memory_raw — capacity_mb 문자열이면 int() ValueError
# ===========================================================================
class TestNormalizeMemoryRaw:
    def test_unit_suffixed_capacity_does_not_crash(self):
        """capacity_mb='8GB' → 가드 전 int('8GB') ValueError. 가드 후 슬롯 skip."""
        raw = {"total_mib": 8192,
               "slots": [{"capacity_mb": "8GB", "type": "DDR4", "speed_mhz": 3200}]}
        out = rg._normalize_memory_raw(raw)  # 가드 전: ValueError
        assert isinstance(out, dict) and "summary" in out
        assert out["summary"]["groups"] == []  # 파싱 불가 슬롯은 제외

    def test_numeric_string_capacity_preserved(self):
        """capacity_mb='16384'(숫자형 문자열) → 16 GiB 로 정상 해석."""
        raw = {"total_mib": 16384,
               "slots": [{"capacity_mb": "16384", "type": "DDR5"}]}
        out = rg._normalize_memory_raw(raw)
        assert out["summary"]["groups"][0]["unit_capacity_gb"] == 16

    def test_wellformed_int_unchanged(self):
        """정상 int → 가드 전후 동일 (32 GiB 슬롯 ×2)."""
        raw = {"total_mib": 65536, "slots": [
            {"capacity_mb": 32768, "type": "DDR5", "speed_mhz": 4800},
            {"capacity_mb": 32768, "type": "DDR5", "speed_mhz": 4800},
        ]}
        out = rg._normalize_memory_raw(raw)
        g = out["summary"]["groups"]
        assert len(g) == 1 and g[0]["unit_capacity_gb"] == 32 and g[0]["quantity"] == 2
        assert out["summary"]["grand_total_gb"] == 64
