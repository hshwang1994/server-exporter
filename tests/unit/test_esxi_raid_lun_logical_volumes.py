"""esxi_disks.py — RAID 컨트롤러 뒤의 LUN 은 media_type null + logical_volumes[] (2026-10-18 X6/X7, 사용자 결정 2026-10-18).

종전: ESXi physical_disks 는 vSphere 가 노출하는 LUN(RAID 논리 볼륨 포함) 이고 media_type 은 ScsiDisk.ssd 플래그를 그대로 썼다 —
실측 esxi02 의 SSD RAID5 LUN 이 HDD 로 나왔고(X7), RAID 뒤 LUN 이 논리 볼륨이라는 사실은 어디에도 없었다(X6: Redfish 는 logical_volumes 3,
ESXi 0). LUN ↔ 어댑터는 storageDevice.scsiTopology 로 맞추고 어댑터 종류는 _controller_type(드라이버 계열) 로 본다 — 모델 문자열로 추정하지 않는다.
pyvmomi 없이 SimpleNamespace 로 HostSystem 을 흉내 낸다 (실장비 미검증 — topology 모양은 vSphere API HostScsiTopology 정의).
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace as NS

from tests.unit.test_esxi_section_errors import _load_module


class FakeDisk:
    """vim.host.ScsiDisk 대역."""

    def __init__(self, key, cn, *, model, vendor, ssd, blocks=1_000_000, display=None):
        self.key, self.canonicalName, self.model, self.vendor, self.ssd = key, cn, model, vendor, ssd
        self.capacity = NS(block=blocks, blockSize=512)
        self.displayName = display
        self.alternateName = []
        self.serialNumber = None


class BlockHba:
    def __init__(self, key, device, driver, model):
        self.key, self.device, self.driver, self.model, self.pci = key, device, driver, model, "0000:18:00.0"


class FibreChannelHba(BlockHba):
    pass


class SerialAttachedHba(BlockHba):
    """HostSerialAttachedHba 대역 — ESXi 7 은 MegaRAID(lsi_mr3)·PERC H965i(bcm_mpi3)를 이 클래스로 노출한다 (실측 2026-10-18 Jenkins #647)."""


class PcieHba(BlockHba):
    """HostPcieHba 대역 — NVMe 어댑터(nvme_pcie)."""


def _module():
    m = _load_module()
    m = importlib.reload(m)
    m.vim = NS(HostSystem=object, host=NS(ScsiDisk=FakeDisk))
    return m


def _content(hosts):
    view = NS(view=hosts, Destroy=lambda: None)
    return NS(viewManager=NS(CreateContainerView=lambda root, types, rec: view), rootFolder=None)


def _topology(mapping):
    """{adapter key: [lun keys]} → HostScsiTopology 모양."""
    return NS(adapter=[NS(adapter=ak, target=[NS(lun=[NS(scsiLun=lk, lun=i) for i, lk in enumerate(luns)])]) for ak, luns in mapping.items()])


RAID_KEY = "key-vim.host.BlockHba-vmhba1"
SATA_KEY = "key-vim.host.BlockHba-vmhba0"
FC_KEY = "key-vim.host.FibreChannelHba-vmhba2"
RAID_LUN = FakeDisk("key-vim.host.ScsiDisk-0200a", "naa.6d0946600f5b3b002a1c2d3e4f5a6b7c", model="PERC H740P Adp", vendor="DELL", ssd=False,
                    blocks=3_750_000_000, display="Local DELL Disk (naa.6d0946600f5b3b002a1c2d3e4f5a6b7c)")
SATA_LUN = FakeDisk("key-vim.host.ScsiDisk-0200b", "t10.ATA_____SAMSUNG_MZ7LH480", model="SAMSUNG MZ7LH480", vendor="ATA", ssd=True)
FC_LUN = FakeDisk("key-vim.host.ScsiDisk-0200c", "naa.60060e80072a5e0000302a5e00000001", model="OPEN-V", vendor="HITACHI", ssd=False)


def _host(disks, hbas, topo):
    return NS(name="esxi01", configManager=NS(storageSystem=NS(storageDeviceInfo=NS(scsiLun=disks))),
              config=NS(storageDevice=NS(hostBusAdapter=hbas, scsiTopology=topo)), hardware=NS(pciDevice=[]))


def _standard_host():
    hbas = [BlockHba(SATA_KEY, "vmhba0", "vmw_ahci", "Lewisburg SATA"), BlockHba(RAID_KEY, "vmhba1", "lsi_mr3", "PERC H740P"),
            FibreChannelHba(FC_KEY, "vmhba2", "lpfc", "Emulex LPe32002")]
    topo = _topology({RAID_KEY: [RAID_LUN.key], SATA_KEY: [SATA_LUN.key], FC_KEY: [FC_LUN.key]})
    return _host([RAID_LUN, SATA_LUN, FC_LUN], hbas, topo)


def test_raid_lun_media_type_is_null_and_other_disks_keep_the_ssd_flag():
    m = _module()
    disks = {d["id"]: d for d in m._build_disks(_content([_standard_host()]))}
    assert disks[RAID_LUN.canonicalName]["media_type"] is None, "RAID 컨트롤러 보고값(ssd=False)은 매체가 아니다"
    assert disks[SATA_LUN.canonicalName]["media_type"] == "SSD"
    assert disks[FC_LUN.canonicalName]["media_type"] == "HDD"
    assert len(disks) == 3, "physical_disks 는 그대로(Additive) — RAID LUN 도 남는다"


def test_raid_lun_is_also_a_logical_volume_with_redfish_keys():
    m = _module()
    vols = m._build_logical_volumes(_content([_standard_host()]))
    assert vols == [{"id": RAID_LUN.canonicalName, "name": "Local DELL Disk (naa.6d0946600f5b3b002a1c2d3e4f5a6b7c)", "controller_id": "vmhba1",
                     "member_drive_ids": [], "raid_level": None, "total_mb": int(3_750_000_000 * 512 / 1048576), "health": None, "state": None,
                     "boot_volume": None}]
    controllers = {c["id"]: c for c in m._build_controllers(_content([_standard_host()]))}
    assert controllers[vols[0]["controller_id"]]["controller_type"] == "RAID", "controller_id 는 controllers[].id 와 맞는다"


def test_without_topology_nothing_changes_and_no_volumes():
    m = _module()
    host = _host([RAID_LUN, SATA_LUN], [BlockHba(RAID_KEY, "vmhba1", "lsi_mr3", "PERC")], None)
    disks = {d["id"]: d for d in m._build_disks(_content([host]))}
    assert disks[RAID_LUN.canonicalName]["media_type"] == "HDD", "어댑터를 못 맞추면 종전 규칙(ssd 플래그)"
    assert m._build_logical_volumes(_content([host])) == []


def test_topology_pointing_at_unknown_adapter_or_lun_is_ignored():
    m = _module()
    topo = _topology({"key-vim.host.BlockHba-vmhba9": [RAID_LUN.key], RAID_KEY: ["key-vim.host.ScsiDisk-nonexistent"]})
    host = _host([RAID_LUN], [BlockHba(RAID_KEY, "vmhba1", "lsi_mr3", "PERC")], topo)
    assert m._lun_controller_map(host) == {"key-vim.host.ScsiDisk-nonexistent": ("vmhba1", "RAID")}
    assert m._build_logical_volumes(_content([host])) == []


def test_broken_topology_object_does_not_break_disk_collection():
    m = _module()
    host = _host([SATA_LUN], [BlockHba(SATA_KEY, "vmhba0", "vmw_ahci", "SATA")], NS(adapter="not-a-list"))
    assert m._lun_controller_map(host) == {}
    assert [d["media_type"] for d in m._build_disks(_content([host]))] == ["SSD"]


def _host_with_pci(disks, hbas, topo, pci):
    h = _host(disks, hbas, topo)
    h.hardware = NS(pciDevice=pci)
    return h


MEGARAID_KEY = "key-vim.host.SerialAttachedHba-vmhba4"
PERC_KEY = "key-vim.host.SerialAttachedHba-vmhba1"


def test_real_esxi7_megaraid_is_serial_attached_hba_but_still_raid():
    """esxi02 실측(2026-10-18 #647): MegaRAID SAS Invader(lsi_mr3) 가 HostSerialAttachedHba 로 와도 RAID — 드라이버 계열이 어댑터 종류보다 앞.

    종전 순서(SerialAttached → 'SAS' 선판정)에서는 'SAS' 가 되어 X6/X7 이 실장비에서 한 번도 발동하지 않았다.
    """
    m = _module()
    hba = SerialAttachedHba(MEGARAID_KEY, "vmhba4", "lsi_mr3", "MegaRAID SAS Invader Controller")
    host = _host([RAID_LUN], [hba], _topology({MEGARAID_KEY: [RAID_LUN.key]}))   # pciDevice 비어 있음 — class 없이도
    assert m._controller_type("HostSerialAttachedHba", "lsi_mr3") == "RAID"
    assert [c["controller_type"] for c in m._build_controllers(_content([host]))] == ["RAID"]
    assert m._build_disks(_content([host]))[0]["media_type"] is None
    assert [v["controller_id"] for v in m._build_logical_volumes(_content([host]))] == ["vmhba4"]


def test_dual_use_driver_is_decided_by_pci_class():
    """PERC H965i(bcm_mpi3, esxi .91 실측): 드라이버는 HBA·RAID 겸용 → HostPciDevice.classId 0x0104 가 RAID 를 가른다; 0x0107 이면 SAS."""
    m = _module()
    hba = SerialAttachedHba(PERC_KEY, "vmhba1", "bcm_mpi3", "PERC H965i Front")
    topo = _topology({PERC_KEY: [RAID_LUN.key]})
    raid = _host_with_pci([RAID_LUN], [hba], topo, [NS(id="0000:18:00.0", vendorName="Broadcom / LSI", classId=0x0104)])
    assert [(c["controller_type"], c["controller_manufacturer"]) for c in m._build_controllers(_content([raid]))] == [("RAID", "Broadcom / LSI")]
    assert m._build_disks(_content([raid]))[0]["media_type"] is None
    assert len(m._build_logical_volumes(_content([raid]))) == 1
    sas = _host_with_pci([RAID_LUN], [hba], topo, [NS(id="0000:18:00.0", vendorName="Broadcom / LSI", classId=0x0107)])
    assert [c["controller_type"] for c in m._build_controllers(_content([sas]))] == ["SAS"]
    assert m._build_disks(_content([sas]))[0]["media_type"] == "HDD", "RAID 가 아니면 종전 규칙(ssd 플래그)"
    assert m._build_logical_volumes(_content([sas])) == []


def test_pci_class_fills_nvme_and_tolerates_bad_values():
    m = _module()
    assert m._controller_type("HostPcieHba", "nvme_pcie") == "NVMe"
    assert m._controller_type("HostPcieHba", None, 0x0108) == "NVMe"
    assert m._controller_type("HostPcieHba", None) is None
    assert m._controller_type("HostBlockHba", "some_unknown_drv", "0x0106") is None, "int() 실패한 class 는 판정에서 빠진다"
    assert m._controller_type("HostBlockHba", "some_unknown_drv", "262") == "SATA", "숫자 문자열(0x0106)은 받는다"
    assert m._controller_type("HostSerialAttachedHba", "bcm_mpi3", 0x10104) == "RAID", "short 범위 밖 비트는 버린다"
    assert m._pci_maps(NS(hardware=None)) == ({}, {}), "pciDevice 를 못 읽어도 빈 맵 — 수집을 막지 않는다"
    broken = NS(hardware=NS(pciDevice=[NS(id="0000:18:00.0", vendorName=" X ", classId="bad"), NS(id=None, classId=1)]))
    assert m._pci_maps(broken) == ({"0000:18:00.0": "X"}, {})


def test_volume_name_falls_back_to_vendor_model_then_canonical_name():
    m = _module()
    lun = FakeDisk("key-vim.host.ScsiDisk-0200d", "naa.600508b1001c0000", model="LOGICAL VOLUME", vendor="HP", ssd=None, display=None)
    host = _host([lun], [BlockHba(RAID_KEY, "vmhba1", "smartpqi", "Smart Array")], _topology({RAID_KEY: [lun.key]}))
    vols = m._build_logical_volumes(_content([host]))
    assert vols[0]["name"] == "HP LOGICAL VOLUME" and vols[0]["controller_id"] == "vmhba1"
    lun2 = FakeDisk("key-vim.host.ScsiDisk-0200e", "naa.600508b1001c0001", model="", vendor="", ssd=None, display="")
    host2 = _host([lun2], [BlockHba(RAID_KEY, "vmhba1", "smartpqi", "Smart Array")], _topology({RAID_KEY: [lun2.key]}))
    assert m._build_logical_volumes(_content([host2]))[0]["name"] == "naa.600508b1001c0001"
