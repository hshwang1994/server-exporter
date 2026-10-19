"""Linux iSCSI 이니시에이터 → storage.hbas[] (2026-10-19, 사용자 승인 — ADR-2026-10-19-esxi-sensors-and-linux-iscsi).

os-gather/tasks/linux/gather_hba_ib.yml 의 raw 가 /sys/class/iscsi_host 를 읽어 ISCSI| 줄을 내고, 파서가 (driver, iqn, hwaddress, netdev) 로
묶어 hbas[] 항목 1건(port_type iSCSI · iqn · session_count · link up/down)을 만든다. 합성 sysfs 트리를 실제 sh 로 실행한다
(test_linux_hba_ib_markers 의 샌드박스 · 렌더 하네스 재사용). 실장비 미검증 — lab 호스트에는 iSCSI 세션이 없다.

입력 모양의 근거: kernel drivers/scsi/scsi_transport_iscsi.c — iscsi_host 클래스 속성(initiatorname · ipaddress · hwaddress · netdev · port_state ·
port_speed; 미설정 값은 "<empty>"), iscsi_session 의 state(LOGGED_IN · FAILED · FREE) · targetname · initiatorname. 소프트웨어 iSCSI(iscsi_tcp)는
세션마다 Scsi_Host 가 생긴다(libiscsi — host 속성은 "<empty>", IQN 은 세션에만).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests.unit.linux_raw_harness import Sandbox  # noqa: E402
from test_linux_hba_ib_markers import (  # noqa: E402
    _attr, build_sysfs, err_paths, lspci_calls, lspci_shim, render, run_all,
)
from tests.regression.test_hba_ib_canonical import HBA_REQUIRED_KEYS, VALID_PORT_TYPES  # noqa: E402

INITIATOR = "iqn.1994-05.com.redhat:3f1c2a9b7e0d"
TARGET_A = "iqn.2010-01.com.example:storage.tgt-a"
TARGET_B = "iqn.2010-01.com.example:storage.tgt-b"
SW_HOST_ATTRS = {"initiatorname": "<empty>", "ipaddress": "<empty>", "hwaddress": "<empty>", "netdev": "<empty>",
                 "port_state": "Unknown!", "port_speed": "Unknown!"}
HW_PCI = "0000:3b:00.1"
HW_UEVENT = f"DRIVER=bnx2i\nPCI_SLOT_NAME={HW_PCI}\n"
HW_LSPCI = '3b:00.1 "Ethernet controller" "Broadcom Inc. and subsidiaries" "NetXtreme II BCM57810 10 Gigabit Ethernet" "Dell" "Device 1f5f"'
HW_HOST_ATTRS = {"initiatorname": INITIATOR, "ipaddress": "10.20.30.41", "hwaddress": "00:10:18:AA:BB:CC", "netdev": "eth2",
                 "port_state": "LINK UP", "port_speed": "10 Gbps"}


@pytest.fixture
def sbx(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path / "sbx", hide=("lspci",))


def add_iscsi_host(root: Path, name: str, *, attrs: dict, proc_name: str | None = "iscsi_tcp",
                   sessions: dict[str, dict[str, str]] | None = None, uevent: str | None = None,
                   unreadable: tuple[str, ...] = ()) -> Path:
    """/sys/class/iscsi_host/<name> 하나 — 평면 모양: <host>/<attr>, <host>/device/scsi_host/<name>/proc_name,
    <host>/device/<session>/iscsi_session/<session>/<attr>, <host>/uevent (= <host>/device/../uevent)."""
    host = root / "iscsi_host" / name
    host.mkdir(parents=True, exist_ok=True)
    for key, value in attrs.items():
        _attr(host / key, value, f"iscsi:{key}" in unreadable)
    if proc_name:
        _attr(host / "device" / "scsi_host" / name / "proc_name", proc_name, False)
    for sid, sattrs in (sessions or {}).items():
        for key, value in sattrs.items():
            _attr(host / "device" / sid / "iscsi_session" / sid / key, value, f"iscsi:session:{key}" in unreadable)
    if uevent is not None:
        _attr(host / "uevent", uevent, False)
    return host


def iscsi_rows(results):
    return results["_l_hba_raw"].rows("ISCSI")


def hbas_of(run):
    return run.ctx["_data_fragment"]["storage"]["hbas"]


def test_software_iscsi_sessions_collapse_into_one_initiator_entry(sbx):
    lspci_shim(sbx)
    root = build_sysfs(sbx)   # FC host1 + IB mlx5_0 그대로
    add_iscsi_host(root, "host3", attrs=SW_HOST_ATTRS,
                   sessions={"session1": {"state": "LOGGED_IN", "targetname": TARGET_A, "initiatorname": INITIATOR}})
    add_iscsi_host(root, "host4", attrs=SW_HOST_ATTRS,
                   sessions={"session2": {"state": "LOGGED_IN", "targetname": TARGET_B, "initiatorname": INITIATOR}})
    results = run_all(sbx, root)
    assert err_paths(results["_l_hba_raw"]) == []
    rows = iscsi_rows(results)
    assert len(rows) == 2 and {r[0] for r in rows} == {"host3", "host4"}
    assert all(r[1] == INITIATOR for r in rows), "host 의 initiatorname 이 <empty> 면 세션의 initiatorname 으로 보충"
    assert all(r[7] == "iscsi_tcp" and r[8] == "1" and r[9] == "1" for r in rows), "ISCSI|host|iqn|ip|hw|netdev|port_state|port_speed|driver|sessions|logged_in|pci|pvn|pdv"
    run = render(results)
    hbas = hbas_of(run)
    assert [h["port_type"] for h in hbas] == ["FibreChannel", "iSCSI"], "FC 항목 뒤에 iSCSI 1건 — 세션 2개가 1 이니시에이터로 묶인다"
    e = hbas[1]
    assert e == {"host": "host3", "iqn": INITIATOR, "wwpn": None, "wwnn": None, "model": None, "vendor": None, "driver": "iscsi_tcp",
                 "firmware": None, "link_status": "up", "link_speed_gbps": None, "port_type": "iSCSI", "ip_address": None,
                 "mac_address": None, "netdev": None, "session_count": 2, "source": "os"}
    for k in HBA_REQUIRED_KEYS:
        assert k in e
    assert e["port_type"] in VALID_PORT_TYPES
    assert run.ctx["_errors_fragment"] == [] and "storage" in run.ctx["_sections_collected_fragment"]


def test_hardware_offload_port_is_one_entry_with_pci_names_and_speed(sbx):
    calls = lspci_shim(sbx, {f"-mm -s {HW_PCI}": HW_LSPCI})
    root = build_sysfs(sbx, fc=False, ib=False)
    add_iscsi_host(root, "host5", attrs=HW_HOST_ATTRS, proc_name="bnx2i", uevent=HW_UEVENT)
    results = run_all(sbx, root)
    row = iscsi_rows(results)[0]
    assert row[:8] == ["host5", INITIATOR, "10.20.30.41", "00:10:18:AA:BB:CC", "eth2", "LINK UP", "10 Gbps", "bnx2i"]
    assert row[8:10] == ["0", "0"] and row[10] == HW_PCI
    run = render(results)
    e = hbas_of(run)[0]
    assert e["iqn"] == INITIATOR and e["driver"] == "bnx2i" and e["link_status"] == "up" and e["link_speed_gbps"] == 10
    assert e["model"] == "NetXtreme II BCM57810 10 Gigabit Ethernet" and e["vendor"] == "Broadcom Inc. and subsidiaries"
    assert e["mac_address"] == "00:10:18:aa:bb:cc" and e["netdev"] == "eth2" and e["ip_address"] == "10.20.30.41"
    assert e["session_count"] == 0
    assert lspci_calls(calls) == [f"-mm -s {HW_PCI}"], "lspci 는 host 당 1회"
    assert "storage" in run.ctx["_sections_collected_fragment"], "FC · IB 없이 iSCSI 만 있어도 storage 는 collected (network 는 NIC driver map 몫)"


def test_link_down_without_logged_in_session_is_down(sbx):
    root = build_sysfs(sbx, fc=False, ib=False)
    add_iscsi_host(root, "host5", attrs=dict(HW_HOST_ATTRS, port_state="LINK DOWN"), proc_name="bnx2i",
                   sessions={"session7": {"state": "FAILED", "targetname": TARGET_A, "initiatorname": INITIATOR}})
    run = render(run_all(sbx, root))
    e = hbas_of(run)[0]
    assert e["link_status"] == "down" and e["session_count"] == 1


def test_two_offload_ports_stay_separate_by_hwaddress(sbx):
    root = build_sysfs(sbx, fc=False, ib=False)
    add_iscsi_host(root, "host5", attrs=HW_HOST_ATTRS, proc_name="bnx2i")
    add_iscsi_host(root, "host6", attrs=dict(HW_HOST_ATTRS, hwaddress="00:10:18:aa:bb:cd", netdev="eth3", port_state="LINK DOWN"), proc_name="bnx2i")
    hbas = hbas_of(render(run_all(sbx, root)))
    assert [(h["host"], h["mac_address"], h["link_status"]) for h in hbas] == [("host5", "00:10:18:aa:bb:cc", "up"), ("host6", "00:10:18:aa:bb:cd", "down")]


def test_unreadable_initiatorname_leaves_err_marker_and_one_storage_error(sbx):
    root = build_sysfs(sbx, fc=False, ib=False)
    add_iscsi_host(root, "host5", attrs=HW_HOST_ATTRS, proc_name="bnx2i", unreadable=("iscsi:initiatorname",))
    results = run_all(sbx, root)
    host = sbx.p(root / "iscsi_host" / "host5")
    assert err_paths(results["_l_hba_raw"]) == [f"{host}/initiatorname"]
    run = render(results)
    e = hbas_of(run)[0]
    assert e["iqn"] is None and e["link_status"] == "up", "읽지 못한 속성만 비고 항목은 남는다"
    errs = run.ctx["_errors_fragment"]
    assert len(errs) == 1 and errs[0]["section"] == "storage"
    assert "scope=iscsi_host;" in errs[0]["detail"] and "cause=attribute_unreadable" in errs[0]["detail"]


def test_no_iscsi_class_leaves_fc_and_ib_unchanged(sbx):
    lspci_shim(sbx)
    results = run_all(sbx, build_sysfs(sbx))
    assert iscsi_rows(results) == []
    run = render(results)
    assert run.ctx["_l_iscsi_list"] == [] and [h["port_type"] for h in hbas_of(run)] == ["FibreChannel"]


def test_task_text_scopes_mention_iscsi_host():
    text = (Path(__file__).resolve().parents[2] / "os-gather" / "tasks" / "linux" / "gather_hba_ib.yml").read_text(encoding="utf-8")
    assert "scope=fc_host,iscsi_host,infiniband; cause=command_failed" in text
    assert "scope=fc_host,iscsi_host,infiniband,nic_driver_map" in text
    assert "/sys/class/iscsi_host" in text and "iscsiadm" not in text.split("ansible.builtin.raw: |")[1].split("register:")[0].replace("# ", "").replace("iscsiadm 과", ""), \
        "raw 는 iscsiadm 을 부르지 않는다 (sysfs 만)"
