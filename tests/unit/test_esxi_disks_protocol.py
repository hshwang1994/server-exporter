"""esxi_disks.py _build_disks — physical_disks[].protocol 을 LUN 이 붙은 어댑터 종류로 (2026-10-19 B-4).

종전에는 'protocol': None 고정이었다. _lun_controller_map(hs) 가 이미 LUN 마다 (어댑터 device, controller_type) 을 주므로 그 종류를
field_dictionary enum(storage.physical_disks[].protocol) · Linux(lsblk TRAN) · Windows(BusType) 와 같은 표기로 옮긴다 — FC 는 'FibreChannel'.
RAID 뒤 LUN 은 논리 볼륨이라 매체 프로토콜을 모른다 → None (Linux 도 RAID 가상 디스크는 null). 어댑터를 못 맞추거나 종류 미상 → None.
media_type 규칙(2026-10-18 X7)은 그대로다.

test_esxi_raid_lun_logical_volumes 의 SimpleNamespace 대역을 그대로 쓴다 (pyvmomi 없음 · 실장비 미검증).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from tests.unit.test_esxi_raid_lun_logical_volumes import (
    FC_KEY, FC_LUN, RAID_KEY, RAID_LUN, SATA_KEY, SATA_LUN, BlockHba, FakeDisk, FibreChannelHba, PcieHba, SerialAttachedHba,
    _content, _host, _host_with_pci, _module, _standard_host, _topology,
)

yaml = pytest.importorskip("yaml")
REPO = Path(__file__).resolve().parents[2]


class InternetScsiHba(BlockHba):
    """HostInternetScsiHba 대역 — 소프트웨어/하드웨어 iSCSI 어댑터."""


def _protocols(host):
    return {d["id"]: d["protocol"] for d in _module()._build_disks(_content([host]))}


def test_standard_host_maps_sata_fc_and_leaves_raid_lun_null():
    disks = {d["id"]: d for d in _module()._build_disks(_content([_standard_host()]))}
    assert disks[SATA_LUN.canonicalName]["protocol"] == "SATA"
    assert disks[FC_LUN.canonicalName]["protocol"] == "FibreChannel", "enum 표기 — Linux(lsblk fc) · Windows(BusType) 와 같다"
    assert disks[RAID_LUN.canonicalName]["protocol"] is None, "RAID 뒤 LUN 은 논리 볼륨 — 매체 프로토콜을 모른다"
    # media_type 규칙(X7)은 그대로
    assert (disks[RAID_LUN.canonicalName]["media_type"], disks[SATA_LUN.canonicalName]["media_type"], disks[FC_LUN.canonicalName]["media_type"]) == (None, "SSD", "HDD")


def test_sas_nvme_and_iscsi_adapters_map_to_their_protocols():
    sas_key, nvme_key, iscsi_key = "key-vim.host.SerialAttachedHba-vmhba3", "key-vim.host.PcieHba-vmhba5", "key-vim.host.InternetScsiHba-vmhba64"
    sas_lun = FakeDisk("key-vim.host.ScsiDisk-sas", "naa.5000c500a1b2c3d4", model="ST4000NM", vendor="SEAGATE", ssd=False)
    nvme_lun = FakeDisk("key-vim.host.ScsiDisk-nvme", "t10.NVMe____Dell_Ent_NVMe", model="Dell Ent NVMe", vendor="NVMe", ssd=True)
    iscsi_lun = FakeDisk("key-vim.host.ScsiDisk-iscsi", "naa.6000eb3a0b1c2d3e", model="iSCSI Disk", vendor="LIO-ORG", ssd=False)
    hbas = [SerialAttachedHba(sas_key, "vmhba3", "lsi_msgpt3", "SAS3008"), PcieHba(nvme_key, "vmhba5", "nvme_pcie", "NVMe"),
            InternetScsiHba(iscsi_key, "vmhba64", "iscsi_vmk", "iSCSI Software Adapter")]
    host = _host([sas_lun, nvme_lun, iscsi_lun], hbas, _topology({sas_key: [sas_lun.key], nvme_key: [nvme_lun.key], iscsi_key: [iscsi_lun.key]}))
    assert _protocols(host) == {sas_lun.canonicalName: "SAS", nvme_lun.canonicalName: "NVMe", iscsi_lun.canonicalName: "iSCSI"}


def test_lun_without_topology_or_with_unknown_adapter_kind_stays_null():
    """어댑터를 못 맞추면(topology 없음) 또는 종류를 모르면(unknown driver BlockHba) 추측하지 않는다."""
    no_topo = _host([SATA_LUN], [BlockHba(SATA_KEY, "vmhba0", "vmw_ahci", "SATA")], None)
    assert _protocols(no_topo) == {SATA_LUN.canonicalName: None}
    unknown_key = "key-vim.host.BlockHba-vmhba7"
    unknown = _host([SATA_LUN], [BlockHba(unknown_key, "vmhba7", "some_unknown_drv", "Mystery")], _topology({unknown_key: [SATA_LUN.key]}))
    assert _protocols(unknown) == {SATA_LUN.canonicalName: None}
    assert _module()._build_disks(_content([no_topo]))[0]["media_type"] == "SSD", "media_type 규칙은 그대로"


def test_dual_use_driver_follows_pci_class_like_controllers_do():
    """bcm_mpi3(PERC H965i, HBA·RAID 겸용): PCI class 0x0104 → RAID → None, 0x0107 → SAS → 'SAS' — controllers[] 와 같은 판정."""
    perc_key = "key-vim.host.SerialAttachedHba-vmhba1"
    hba = SerialAttachedHba(perc_key, "vmhba1", "bcm_mpi3", "PERC H965i Front")
    topo = _topology({perc_key: [RAID_LUN.key]})
    raid = _host_with_pci([RAID_LUN], [hba], topo, [NS(id="0000:18:00.0", vendorName="Broadcom / LSI", classId=0x0104)])
    sas = _host_with_pci([RAID_LUN], [hba], topo, [NS(id="0000:18:00.0", vendorName="Broadcom / LSI", classId=0x0107)])
    assert _protocols(raid) == {RAID_LUN.canonicalName: None}
    assert _protocols(sas) == {RAID_LUN.canonicalName: "SAS"}


def test_protocol_values_are_inside_the_field_dictionary_enum():
    """계약 가드: 모듈이 낼 수 있는 protocol 값은 모두 storage.physical_disks[].protocol enum 안 — 'FC' 같은 enum 밖 표기는 쓰지 않는다."""
    fd = yaml.safe_load((REPO / "schema" / "field_dictionary.yml").read_text(encoding="utf-8"))["fields"]
    enum = set(fd["storage.physical_disks[].protocol"]["enum"])
    m = _module()
    assert set(m._LUN_PROTOCOL_BY_CONTROLLER.values()) <= enum, sorted(set(m._LUN_PROTOCOL_BY_CONTROLLER.values()) - enum)
    assert "RAID" not in m._LUN_PROTOCOL_BY_CONTROLLER, "RAID 뒤 LUN 은 None (사용자 결정 — Linux 와 같다)"
    assert set(m._LUN_PROTOCOL_BY_CONTROLLER) == {"FC", "iSCSI", "SAS", "NVMe", "SATA"}, "_controller_type 이 내는 종류(RAID 제외) 전부"


def test_disk_entry_keys_are_unchanged():
    """Additive: physical_disks[] 항목의 키 집합은 그대로 — 값만 채운다."""
    disk = _module()._build_disks(_content([_standard_host()]))[0]
    assert set(disk) == {"id", "device", "model", "serial", "wwn", "total_mb", "media_type", "protocol", "health"}


def test_summary_groups_now_split_by_protocol_like_the_os_channel():
    """normalize_storage.yml 의 _e_stor_summary 는 protocol 을 그룹 키에 넣는다 — 값이 채워지면 FC/SATA LUN 이 다른 그룹이 된다."""
    import sys
    sys.path.insert(0, str(REPO / "tests" / "unit"))
    from linux_raw_harness import ansible_env, render_tree  # noqa: PLC0415

    tpl = next(t for t in yaml.safe_load((REPO / "esxi-gather" / "tasks" / "normalize_storage.yml").read_text(encoding="utf-8"))
               if isinstance(t, dict) and "_e_stor_summary" in (t.get("ansible.builtin.set_fact") or {}))["ansible.builtin.set_fact"]["_e_stor_summary"]
    disks = [{"total_mb": 1048576, "media_type": "HDD", "protocol": "FibreChannel", "model": "HITACHI OPEN-V"},
             {"total_mb": 1048576, "media_type": "HDD", "protocol": "SATA", "model": "HITACHI OPEN-V"}]
    out = render_tree(ansible_env(), tpl, {"_e_raw_disks": disks})
    assert [g["protocol"] for g in out["groups"]] == ["FibreChannel", "SATA"] and out["grand_total_gb"] == 2048
