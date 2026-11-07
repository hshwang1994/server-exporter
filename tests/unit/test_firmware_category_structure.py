"""firmware[].category — 구조 근거 1순위 + 검증된 토큰 사슬 + 컨트롤러 조인 (2026-10-27, C9 FIX 7 — 04-firmware-001~005/008).

normalize_standard.yml 의 `_rf_firmware_categorized` 분기 블록을 test_firmware_category.py 와 같은 방법으로 발췌해 jinja2 로 렌더한다.
enum 14값 각각에 긍정 ≥1 · 부정 ≥1 — 이름은 전부 실 미러(Dell R740 · HPE DL380 Gen12 · Lenovo SR650 V4 · HPE CSUS 3200)의 것이다.
FIX 7: enum 을 늘리지 않는다 — FC HBA 는 other. 근거가 없는 CSUS 번들(ComplexFW / Partition0_FW)은 other 유지.
기대값은 손으로 적었다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment

REPO = Path(__file__).resolve().parents[2]
NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))


def _template() -> str:
    tasks = yaml.safe_load(NORM.read_text(encoding="utf-8"))
    raw = next(sf["_rf_firmware_categorized"] for t in tasks if isinstance(t, dict)
               for sf in [t.get("set_fact") or t.get("ansible.builtin.set_fact") or {}] if "_rf_firmware_categorized" in sf)
    start = raw.index("{%- set fid")
    end = raw.index("{%- endif -%}") + len("{%- endif -%}")
    return raw[start:end] + "{{ cat }}"


_render = Environment().from_string(_template())


def cat(fw_id, name, links=None, controllers=()):
    """links: {'bios': True} / {'bmc': True} — 모듈 firmware_links[fw_id]. controllers: 같은 봉투 storage.controllers[].controller_model."""
    return _render.render(fw={"id": fw_id, "name": name}, _rf_fw_links=({fw_id: links} if links else {}),
                          ctrl_models=[c.lower().strip() for c in controllers])


# (category, fw_id, name, links, controllers)
POSITIVE = [
    ("bios", "UEFI", "Firmware:UEFI", {"bios": True}, ()),                                   # Lenovo — 구조 근거(Bios.Links.ActiveSoftwareImage)
    ("bios", "2", "System ROM", None, ()),                                                     # HPE — 토큰
    ("bios", "Current-159-2.26.1__BIOS.Setup.1-1", "BIOS", {"bios": True}, ()),                # Dell — 구조 근거(dedup key 로 대조)
    ("bios", "UEFI-Pending", "Firmware:UEFI", None, ()),                                       # Lenovo — 토큰 'uefi'
    ("bmc", "BMC-Primary", "Firmware:BMC", {"bmc": True}, ()),                                 # Lenovo — 구조 근거(Manager.Links.ActiveSoftwareImage)
    ("bmc", "Installed-25227-7.00.00.184__iDRAC.Embedded.1-1", "Integrated Dell Remote Access Controller", None, ()),
    ("bmc", "1", "iLO 7", None, ()),
    ("storage_controller", "15", "HPE MR416i-o Gen11", None, ("HPE MR416i-o Gen11",)),       # HPE — storage.controllers 조인
    ("storage_controller", "Current-104893-51.16.0-5150__RAID.Slot.6-1", "PERC H740P Adapter", None, ()),
    ("storage_controller", "PCIeDevice_slot5_0x4c0000.Bundle", "Firmware:DEVICE-ThinkSystem RAID 940-16i 8GB Flash PCIe Gen4 12Gb Adapter", None, ()),
    ("storage_controller", "pcie_3", "HPE SR3258p-16i/e PCIe4 Controller", None, ("HPE SR3258p-16i/e PCIe4 Controller",)),   # CSUS — 조인
    ("backplane", "Drive_Backplane_STA7B78555_L3HF5BC007P_PSoC_0xBB", "Firmware-PSoC:0xBB", None, ()),   # Lenovo — id 의 backplane (drive_ 보다 먼저)
    ("backplane", "Current-104102-2.41__RAID.Backplane.Firmware.1", "Backplane 1", None, ()),
    ("backplane", "21", "8 SFF 24G x1NVMe/SAS UBM6 BC BP", None, ()),
    ("cpld", "4", "System Programmable Logic Device", None, ()),                               # HPE PLD
    ("cpld", "HPM-FPGA", "Firmware:HPM-FPGA", None, ()),                                       # Lenovo FPGA (RelatedItem→Managers/1 은 근거 아님)
    ("cpld", "Installed-27763-1.1.4__CPLD.Embedded.1", "System CPLD", None, ()),
    ("drive", "drive_bay_0", "Firmware:Drive-MZILG1T6HCJR-V7", None, ()),
    ("drive", "19", "1.60TB 22.5G SAS SSD", None, ()),
    ("drive", "Installed-106441-ST33__Disk.Bay.0:Enclosure.Internal.0-1:RAID.Slot.6-1", "Disk 0 in Backplane 1 of RAID Controller in Slot 6", None, ()),
    ("nic", "PCIeDevice_slot13_0x170000.1", "Firmware:DEVICE-Intel(R) E810-DA2 10/25GbE SFP28 2-Port OCP Ethernet Adapter", None, ()),
    ("nic", "13", "Broadcom P225p NetXtreme-E Dual-port 10Gb/25Gb Ethernet PCIe Adapter - NIC", None, ()),
    ("nic", "pcie_1", "MLX MCX631102 10/25GbE 2p SFP28 Adptr", None, ()),                      # CSUS 'gbe'
    ("psu", "POWER-PSU1", "POWER-PSU1", None, ()),
    ("psu", "6", "Power Supply Firmware", None, ()),
    ("psu", "psu0", "CRPS: Common Redundant Power Supply", None, ()),
    ("tpm", "11", "TPM Firmware", None, ()),
    ("lifecycle", "Installed-28897-7.00.00.184__USC.Embedded.1:LC.Embedded.1", "Lifecycle Controller", None, ()),
    ("driver_pack", "LXPMWindowsDriver", "Firmware:LXPM-WindowsDrivers", None, ()),
    ("driver_pack", "Installed-18981-19.04.05__DriverPack.Embedded.1:LC.Embedded.1", "Dell OS Driver Pack, 19.04.05, A00", None, ()),
    ("service_module", "Installed-104684-3.4.0__ServiceModule.Embedded.1", "iDRAC Service Module Embedded Package, v3.4.0, A00", None, ()),
    ("diagnostic", "Installed-25806-4301A34__Diagnostics.Embedded.1:LC.Embedded.1", "Dell 64 Bit uEFI Diagnostics, version 4301, 4301A34, 4301.35", None, ()),
    ("other", "ComplexFW", "Complex Firmware", None, ()),                                       # CSUS — RelatedItem Chassis, 구조 근거 없음
    ("other", "Partition0_FW", "Npar 0 Current Firmware", None, ()),                           # CSUS — RelatedItem System, 구조 근거 없음
    ("other", "16", "HPE SN1610Q 32Gb 2p FC HBA", None, ()),                                   # FC HBA → other (FIX 7)
    ("other", "PCIeDevice_slot14_0xb80000.1", "Firmware:DEVICE-QLogic QLE2772 32Gb 2-Port PCIe Fibre Channel Adapter", None, ()),
    ("other", "pcie_11", "HPE SN1100Q 16Gb 2p FC HBA", None, ()),
    ("other", "18", "Embedded Video Controller", None, ()),                                    # 'controller' 폴백 전에 other
    ("other", "LXPM", "Firmware:LXPM", None, ()),
    ("other", "3", "Intelligent Platform Abstraction Data", None, ()),
]


@pytest.mark.parametrize("expected,fw_id,name,links,controllers", POSITIVE, ids=[f"{c}:{n[:28]}" for c, _, n, _, _ in POSITIVE])
def test_each_category_has_real_positive_cases(expected, fw_id, name, links, controllers):
    assert cat(fw_id, name, links, controllers) == expected


# 부정: 이 이름이 그 category 로 가면 안 된다 (실제로 어디로 가는지도 고정)
NEGATIVE = [
    ("bios", "Installed-25806-4301A34__Diagnostics.Embedded.1:LC.Embedded.1", "Dell 64 Bit uEFI Diagnostics, version 4301, 4301A34, 4301.35", None, (), "diagnostic"),
    ("bios", "Partition0_FW", "Npar 0 Current Firmware", None, (), "other"),
    ("bmc", "HPM-FPGA", "Firmware:HPM-FPGA", None, (), "cpld"),
    ("bmc", "ComplexFW", "Complex Firmware", None, (), "other"),
    ("storage_controller", "18", "Embedded Video Controller", None, (), "other"),
    ("storage_controller", "16", "HPE SN1610Q 32Gb 2p FC HBA", None, (), "other"),
    ("storage_controller", "PCIeDevice_slot14_0xb80000.1", "Firmware:DEVICE-QLogic QLE2772 32Gb 2-Port PCIe Fibre Channel Adapter", None, (), "other"),
    ("backplane", "Installed-106441-ST33__Disk.Bay.3:Enclosure.Internal.0-1:RAID.Slot.6-1", "Disk 3 in Backplane 1 of RAID Controller in Slot 6", None, (), "drive"),
    ("cpld", "PCIeDevice_slot13_0x170000.Bundle", "Firmware:DEVICE-Intel(R) E810-DA2 10/25GbE SFP28 2-Port OCP Ethernet Adapter", None, (), "nic"),
    ("drive", "21", "8 SFF 24G x1NVMe/SAS UBM6 BC BP", None, (), "backplane"),
    ("drive", "Drive_Backplane_STA7B78555_L3HF5BC007P_PSoC_0xBB", "Firmware-PSoC:0xBB", None, (), "backplane"),
    ("nic", "Installed-110-7.26.0__RAID.Slot.1-1", "Broadcom MegaRAID SAS 9460-8i Adapter", None, (), "storage_controller"),
    ("psu", "LXUM", "Firmware:LXUM", None, (), "other"),
    ("tpm", "2", "System ROM", None, (), "bios"),
    ("lifecycle", "Installed-104684-3.4.0__ServiceModule.Embedded.1", "iDRAC Service Module Embedded Package, v3.4.0, A00", None, (), "service_module"),
    ("driver_pack", "drive_bay_1", "Firmware:Drive-MZILG1T6HCJR-V7", None, (), "drive"),
    ("service_module", "Installed-28897-7.00.00.184__USC.Embedded.1:LC.Embedded.1", "Lifecycle Controller", None, (), "lifecycle"),
    ("diagnostic", "UEFI", "Firmware:UEFI", {"bios": True}, (), "bios"),
    ("other", "15", "HPE MR416i-o Gen11", None, ("HPE MR416i-o Gen11",), "storage_controller"),
]


@pytest.mark.parametrize("not_expected,fw_id,name,links,controllers,actual", NEGATIVE, ids=[f"not-{c}:{n[:24]}" for c, _, n, _, _, _ in NEGATIVE])
def test_each_category_has_real_negative_cases(not_expected, fw_id, name, links, controllers, actual):
    got = cat(fw_id, name, links, controllers)
    assert got != not_expected and got == actual


def test_structural_evidence_beats_tokens():
    assert cat("Firmware:X", "Firmware:X", {"bios": True}) == "bios"
    assert cat("Firmware:X", "Firmware:X", {"bmc": True}) == "bmc"
    assert cat("Installed-1__NIC.Slot.1", "Broadcom NetXtreme Gigabit Ethernet", {"bios": True}) == "bios"   # 근거가 있으면 토큰보다 우선
    assert cat("Firmware:X", "Firmware:X") == "other"                                                  # 근거도 토큰도 없음


def test_controller_join_only_when_name_matches_a_storage_controller_model():
    assert cat("15", "HPE MR416i-o Gen11", None, ("HPE MR416i-o Gen11",)) == "storage_controller"
    assert cat("15", "HPE MR416i-o Gen11", None, ("hpe mr416i-o gen11 ",)) == "storage_controller"     # 대소문자·공백 무시
    assert cat("15", "HPE MR416i-o Gen11", None, ()) == "other"                                       # 조인 대상이 없으면 근거 없음 → other
    assert cat("15", "HPE MR416i-o Gen11", None, ("HPE NS204i-u Gen11 Boot Controller",)) == "other"


def test_module_builds_links_by_final_firmware_id_using_dedup_key():
    """Dell: ActiveSoftwareImage 가 'Installed-…' 를 가리키고 firmware[] 에는 first-seen 'Current-…' 가 남는다 (04-firmware-008)."""
    import types
    stub = types.ModuleType("ansible.module_utils.basic"); stub.AnsibleModule = object
    mu = types.ModuleType("ansible.module_utils"); mu.basic = stub
    an = types.ModuleType("ansible"); an.module_utils = mu
    sys.modules.setdefault("ansible", an); sys.modules.setdefault("ansible.module_utils", mu); sys.modules.setdefault("ansible.module_utils.basic", stub)
    import redfish_gather as rg
    fw = [{"id": "Current-159-2.26.1__BIOS.Setup.1-1"}, {"id": "Installed-25227-7.00.00.184__iDRAC.Embedded.1-1"}, {"id": "UEFI"}, {"id": "HPM-FPGA"}]
    out = rg._firmware_links_by_id(
        fw, {"UEFI": {"bios": True}},
        "/redfish/v1/UpdateService/FirmwareInventory/Installed-159-2.26.1__BIOS.Setup.1-1",
        "/redfish/v1/UpdateService/FirmwareInventory/Installed-25227-7.00.00.184__iDRAC.Embedded.1-1")
    assert out == {"Current-159-2.26.1__BIOS.Setup.1-1": {"bios": True},
                   "Installed-25227-7.00.00.184__iDRAC.Embedded.1-1": {"bmc": True},
                   "UEFI": {"bios": True}}
    assert rg._firmware_links_by_id(fw, {}, None, None) == {}
    assert rg._firmware_links_by_id(None, {"UEFI": {"bios": True}}, "", "x/") == {}
