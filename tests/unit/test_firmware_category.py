#!/usr/bin/env python3
"""firmware[].category 분류 (normalize_standard.yml `_rf_firmware_categorized`) 회귀 테스트.

normalize 계층은 Ansible Jinja2 라 평소 오프라인 pytest 에서 실행되지 않는다. 본 테스트는
normalize_standard.yml 에서 **실제** category 분류 Jinja 블록을 추출해 jinja2 로 렌더링,
DELL R740 실 firmware id/name 에 대해 올바른 category 가 나오는지 검증한다.

배경(cycle 2026-06-14 DELL R740 FW-CAT): elif 첫매치 우선 + 광범위 substring('raid'/'drive')이
물리디스크(Disk.Bay…RAID.Slot)/backplane/driverpack 를 선점하던 오분류를 specific-before-broad
재정렬로 정정. 본 테스트가 그 정렬을 고정한다.
"""
import re
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment

REPO = Path(__file__).resolve().parents[2]
NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"


def _extract_category_template() -> str:
    """normalize_standard.yml 의 set_fact `_rf_firmware_categorized` Jinja 문자열 추출.

    YAML 파싱으로 실제 값을 꺼내 per-firmware 렌더 가능한 단일 firmware 템플릿으로 변환한다
    (out/for-loop 래퍼는 제거하고 cat 산출부만 사용 — 분기 로직 자체를 테스트)."""
    tasks = yaml.safe_load(NORM.read_text(encoding="utf-8"))
    raw = None
    for t in tasks:
        if not isinstance(t, dict):
            continue
        sf = t.get("set_fact") or t.get("ansible.builtin.set_fact")
        if isinstance(sf, dict) and "_rf_firmware_categorized" in sf:
            raw = sf["_rf_firmware_categorized"]
            break
    assert raw, "_rf_firmware_categorized set_fact not found"
    # lid 정의 + cat 분기만 발췌, 단일 fw 입력으로 cat 출력
    body = raw
    # for/out 래퍼 제거: 'set lid' 부터 'endif' 까지
    start = body.index("{%- set fid")
    end = body.index("{%- endif -%}") + len("{%- endif -%}")
    inner = body[start:end]
    return inner + "{{ cat }}"


TEMPLATE = _extract_category_template()
_render = Environment().from_string(TEMPLATE)


def cat(fw_id, name):
    return _render.render(fw={"id": fw_id, "name": name})


# DELL R740 실 미러 firmware (id, name, expected_category) — 정정 대상 + 정상 대표 표본
DELL_CASES = [
    ("Current-104102-2.41__RAID.Backplane.Firmware.1", "Backplane 1", "backplane"),
    ("Installed-106441-ST33__Disk.Bay.0:Enclosure.Internal.0-1:RAID.Slot.6-1",
     "Disk 0 in Backplane 1 of RAID Controller in Slot 6", "drive"),
    ("Installed-106441-ST33__Disk.Bay.3:Enclosure.Internal.0-1:RAID.Slot.6-1",
     "Disk 3 in Backplane 1 of RAID Controller in Slot 6", "drive"),
    ("Installed-18981-19.04.05__DriverPack.Embedded.1:LC.Embedded.1",
     "Dell OS Driver Pack, 19.04.05, A00", "driver_pack"),
    ("Installed-104684-3.4.0__ServiceModule.Embedded.1",
     "iDRAC Service Module Embedded Package, v3.4.0, A00", "service_module"),
    ("Current-104893-51.16.0-5150__RAID.Slot.6-1", "PERC H740P Adapter", "storage_controller"),
    ("Current-159-2.26.1__BIOS.Setup.1-1", "BIOS", "bios"),
    ("Installed-25227-7.00.00.184__iDRAC.Embedded.1-1",
     "Integrated Dell Remote Access Controller", "bmc"),
    ("Current-27481-23.61.3__NIC.Integrated.1-1-1",
     "Broadcom NetXtreme Gigabit Ethernet (BCM5720) - 20:04:0F:FB:11:64", "nic"),
    ("Installed-101097-00.1B.53__PSU.Slot.1", "Power Supply.Slot.1", "psu"),
    ("Installed-27763-1.1.4__CPLD.Embedded.1", "System CPLD", "cpld"),
    ("Installed-28897-7.00.00.184__USC.Embedded.1:LC.Embedded.1", "Lifecycle Controller", "lifecycle"),
    ("Installed-25806-4301A34__Diagnostics.Embedded.1:LC.Embedded.1",
     "Dell 64 Bit uEFI Diagnostics, version 4301, 4301A34, 4301.35", "diagnostic"),
]

# 실 CSUS mirror firmware — 무영향(other) 확인 (reorder 가 비-Dell 출력 안 바꿈)
CSUS_REAL_CASES = [
    ("ComplexFW", "Complex Firmware", "other"),
    ("Partition0_FW", "Npar 0 Current Firmware", "other"),
]

# HPE DL380 Gen12 실 미러 firmware (cycle 2026-06-15 SCHEMA-07 정정 대상 + 무영향 표본)
HPE_DL380_CASES = [
    # 정정: UBM 백플레인이 'nvme' substring 으로 drive 오분류되던 것 → backplane
    ("21", "8 SFF 24G x1NVMe/SAS UBM3 BC BP", "backplane"),
    ("22", "8 SFF 24G x1NVMe/SAS UBM3 BC BP", "backplane"),
    # 정정: HPE BIOS 'System ROM' 이 'other' → bios
    ("2", "System ROM", "bios"),
    # 무영향(over-reach 검증): 실 SAS SSD 는 여전히 drive (ubm/bc bp 없음)
    ("19", "1.60TB 22.5G SAS SSD", "drive"),
    ("1", "iLO 7", "bmc"),
    ("13", "Broadcom P225p NetXtreme-E Dual-port 10Gb/25Gb Ethernet PCIe Adapter - NIC", "nic"),
    ("11", "TPM Firmware", "tpm"),
]


@pytest.mark.parametrize("fw_id,name,expected", HPE_DL380_CASES)
def test_hpe_dl380_firmware_category(fw_id, name, expected):
    assert cat(fw_id, name) == expected, f"{name!r} -> {cat(fw_id, name)} (expected {expected})"


@pytest.mark.parametrize("fw_id,name,expected", DELL_CASES)
def test_dell_firmware_category(fw_id, name, expected):
    assert cat(fw_id, name) == expected, f"{name!r} -> {cat(fw_id, name)} (expected {expected})"


@pytest.mark.parametrize("fw_id,name,expected", CSUS_REAL_CASES)
def test_csus_firmware_category_unchanged(fw_id, name, expected):
    assert cat(fw_id, name) == expected


def test_drive_not_mislabeled_storage_controller():
    """Disk.Bay 물리디스크 firmware 는 storage_controller 가 아니라 drive."""
    c = cat("Installed-106441-ST33__Disk.Bay.1:Enclosure.Internal.0-1:RAID.Slot.6-1",
            "Disk 1 in Backplane 1 of RAID Controller in Slot 6")
    assert c == "drive" and c != "storage_controller"
