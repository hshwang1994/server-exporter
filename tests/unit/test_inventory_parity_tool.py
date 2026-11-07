"""tests/scripts/inventory_parity.py 의 노출 수 규칙 (2026-10-27, 사용자 3차 지시 — 디스크·FC 포트 개수 정합).

판별기는 gather 코드와 독립이어야 하므로 규칙을 합성 본문으로 고정한다. 실 미러에서 본 모양만 쓴다:
- Dell iDRAC9: 같은 물리 디스크가 Storage/*/Drives 와 SimpleStorage Devices[] 에, 같은 포트가 Ports/ 와 NetworkPorts/ 에 (r1_DELL_R740_01)
- CSUS RMC: NDF 에 Links 가 없고 같은 Id 의 Port 가 FC (1 NDF : 1 Port)
- iLO 7: 빈 베이 Drive(State Absent · CapacityBytes 0) · 전원 Off 로 Storage 멤버 0 (dl380_gen12_03)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "scripts"))
import inventory_parity as IP  # noqa: E402

SYS = "Systems/System.Embedded.1"
NA = "Chassis/System.Embedded.1/NetworkAdapters/FC.Slot.1"


def _drive(serial, cap=1199638052864, state="Enabled", name="Physical Disk"):
    return {"SerialNumber": serial, "CapacityBytes": cap, "Status": {"State": state}, "Name": name}


def _dell_like():
    bodies = {f"{SYS}": {"PowerState": "On"}, f"{SYS}/Storage": {"Members": [{"@odata.id": "x"}]}}
    for i in range(4):
        bodies[f"{SYS}/Storage/RAID.Slot.6-1/Drives/Disk.Bay.{i}"] = _drive(f"WFK{i}")
    bodies[f"{SYS}/SimpleStorage/RAID.Slot.6-1"] = {"Devices": [{"Name": f"Physical Disk 0:1:{i}", "CapacityBytes": 1199638052864,
                                                                  "Status": {"State": "Enabled"}} for i in range(4)]}
    for pid in ("FC.Slot.1-1", "FC.Slot.1-2"):
        bodies[f"{NA}/NetworkPorts/{pid}"] = {"Id": pid, "ActiveLinkTechnology": "FibreChannel",
                                              "AssociatedNetworkAddresses": ["20:00:34:80:0D:6C:2A:4C"]}
        bodies[f"{NA}/Ports/{pid}"] = {"Id": pid, "LinkNetworkTechnology": "FibreChannel"}
    return bodies


def test_same_disk_in_drives_and_simplestorage_counts_once():
    e = IP.exposure(_dell_like())
    assert e["disks_present"] == 4 and e["disks_present_raw"] == 4 and e["simple_storage_used"] is False


def test_simplestorage_is_used_only_when_no_drive_resource_exists():
    bodies = {f"{SYS}": {"PowerState": "On"},
              f"{SYS}/SimpleStorage/1": {"Devices": [{"Name": "d0", "CapacityBytes": 10, "Status": {"State": "Enabled"}},
                                                     {"Name": "empty", "CapacityBytes": 0, "Status": {"State": "Absent"}}]}}
    e = IP.exposure(bodies)
    assert e["disks_present"] == 1 and e["disks_absent_empty_bay"] == 1 and e["simple_storage_used"] is True


def test_same_port_in_ports_and_networkports_counts_once_and_is_fc():
    e = IP.exposure(_dell_like())
    assert e["fc_ports"] == 2 and e["ethernet_ports"] == 0
    assert all("/Ports/" in p for p in e["fc_port_paths"]), "대표 경로는 Ports/ (신 스키마)"


def test_fc_signal_on_either_duplicate_body_is_enough():
    bodies = {f"{NA}/NetworkPorts/FC.Slot.1-1": {"Id": "FC.Slot.1-1", "ActiveLinkTechnology": "FibreChannel"},
              f"{NA}/Ports/FC.Slot.1-1": {"Id": "FC.Slot.1-1"}}        # 신 스키마 본문에는 FC 신호가 없다
    e = IP.exposure(bodies)
    assert e["fc_ports"] == 1 and e["ethernet_ports"] == 0


def test_ndf_link_to_networkports_path_maps_to_the_canonical_port():
    bodies = _dell_like()
    bodies[f"{NA}/NetworkDeviceFunctions/FC.Slot.1-1"] = {"NetDevFuncType": "FibreChannel",
                                                          "Links": {"PhysicalPortAssignment": {"@odata.id": f"/redfish/v1/{NA}/NetworkPorts/FC.Slot.1-1"}}}
    e = IP.exposure(bodies)
    assert e["fc_ports"] == 2 and e["orphan_fc_ndf"] == []


def test_csus_ndf_without_links_is_not_an_orphan_when_adapter_has_fc_port():
    a = "Chassis/RackGroup/NetworkAdapters/PCIeCard10"
    bodies = {f"{a}/Ports/PCIeCard10Port1": {"Id": "PCIeCard10Port1", "LinkNetworkTechnology": "FibreChannel"},
              f"{a}/NetworkDeviceFunctions/PCIeCard10Port1": {"NetDevFuncType": "FibreChannel"}}
    e = IP.exposure(bodies)
    assert e["fc_ports"] == 1 and e["orphan_fc_ndf"] == []
    b = "Chassis/RackGroup/NetworkAdapters/PCIeCard11"
    bodies[f"{b}/NetworkDeviceFunctions/PCIeCard11Port1"] = {"NetDevFuncType": "FibreChannel"}   # 포트 본문이 없는 adapter
    e = IP.exposure(bodies)
    assert e["orphan_fc_ndf"] == [f"{b}/NetworkDeviceFunctions/PCIeCard11Port1"]


def test_absent_bay_and_power_off_are_explained_but_silent_omission_is_not():
    bodies = {"Systems/1": {"PowerState": "On"}, "Systems/1/Storage": {"Members": [{"@odata.id": "x"}]},
              "Systems/1/Storage/DE/Drives/0": _drive("S0"),
              "Systems/1/Storage/DE/Drives/1": _drive(None, cap=0, state="Absent", name="Empty bay")}
    e = IP.exposure(bodies)
    assert e["disks_present"] == 1 and e["disks_absent_empty_bay"] == 1
    assert IP.classify(e, {"disks": 1, "fc_hbas": 0})["pass"]
    v = IP.classify(e, {"disks": 0, "fc_hbas": 0})
    assert not v["pass"] and v["unexplained"] and "disks" in v["unexplained"][0]       # 수집 가능한 디스크를 빼먹으면 FAIL
    off = {"Systems/1": {"PowerState": "Off"}, "Systems/1/Storage": {"Members": []}}
    v = IP.classify(IP.exposure(off), {"disks": 0, "fc_hbas": 0})
    assert v["pass"] and "POWER_OFF_NOT_EXPOSED" in v["notes"]
    v = IP.classify(IP.exposure(off), {"disks": 2, "fc_hbas": 0})
    assert not v["pass"], "노출 0 인데 수집 2 = 조작"
