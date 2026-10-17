"""ESXi `storage.hbas[]` 정규화 (2026-10-18 HBA 전수 점검) — collect_network_extended.yml 의 실제 set_fact 를 렌더한다.

종전 결함 (코드 정독 + 모듈 RETURN 계약 — lab 에 FC 링크 up · FC-NVMe · 하드웨어 iSCSI · FCoE 가 없어 합성 입력으로 재현):
  - 하드웨어 iSCSI 클래스 'InternetScsiHba' 에 'iscsi' 부분 문자열이 없어 조용히 빠졌다.
  - FCoE 를 FibreChannel 로 적었다 (Redfish 는 FCoE).
  - link_status 가 up/down/unknown 3값이었고, unbound/unknown/없음이 'unknown' 문자열이었다 → null (사용자 결정 2026-10-18).
  - speed 를 Gbps 로 가정했다 (vSphere API 문서는 bits per second) → 자릿수 정규화, 0 → null.
  - 같은 WWPN 의 vmhba 둘(ESXi 7 FC-NVMe 쌍둥이)이 2건으로 나와 "ESXi 8 vs Redfish 4" 가 났다 → (wwpn, wwnn) 1건.
  - 모듈의 깨진 WWN 문자열(홀수 자릿수 · int64 음수) 이 그대로 나갔다 → null + storage errors[] 1건(원문은 detail).
  - location 'PCI' / bus -1 자리표시자가 값으로 나갔다 → null.
  - rescue 가 network 오류만 남겨 hbas [] 가 "HBA 없음" 과 같았다 → storage 1건 추가.
실장비 검증 아님 — 하네스는 test_esxi_partial_failures_c9 의 것(실제 YAML set_fact + jinja2 NativeEnvironment).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "unit"))
sys.path.insert(0, str(REPO / "filter_plugins"))

from linux_raw_harness import assert_user_sentence, render_tree  # noqa: E402
from test_esxi_partial_failures_c9 import EXT, STOR_TEXT, _env, _ext  # noqa: E402

FC_UP = {"device": "vmhba2", "type": "Fibre Channel", "driver": "lpfc", "model": "Emulex LPe32002-M2 2-Port 32Gb FC", "status": "online",
         "location": "0000:5e:00.0", "bus": 94, "port_wwn": "10:00:00:90:FA:1B:2C:3D", "node_wwn": "20:00:00:90:FA:1B:2C:3D", "speed": 16}
FC_PORT2 = dict(FC_UP, device="vmhba3", location="0000:5e:00.1", port_wwn="10:00:00:90:FA:1B:2C:3E", node_wwn="20:00:00:90:FA:1B:2C:3E")


def _vmhba(details):
    return {"failed": False, "hosts_vmhbas_info": {"esxi01": {"vmhba_details": details}}}


def _hbas(details, **mods):
    ctx = _ext(_e_vmhba=_vmhba(details), **mods)
    return ctx["_e_ext_hbas"], ctx


def _storage_errors(ctx):
    return [e for e in ctx["_errors_fragment"] if e["section"] == "storage"]


def test_fc_online_entry_shape_is_the_canonical_one():
    hbas, ctx = _hbas([FC_UP])
    assert hbas == [{"name": "vmhba2", "driver": "lpfc", "model": "Emulex LPe32002-M2 2-Port 32Gb FC", "vendor": None, "firmware": None,
                     "adapter_type": "Fibre Channel", "link_status": "up", "wwpn": "10:00:00:90:fa:1b:2c:3d", "wwnn": "20:00:00:90:fa:1b:2c:3d",
                     "link_speed_gbps": 16, "port_type": "FibreChannel", "pci": "0000:5e:00.0", "bus": 94, "source": "esxi"}]
    assert ctx["_errors_fragment"] == [] and ctx["_sections_collected_fragment"] == ["network", "storage"]
    from tests.regression.test_hba_ib_canonical import HBA_REQUIRED_KEYS  # noqa: PLC0415
    assert set(HBA_REQUIRED_KEYS) <= set(hbas[0])


@pytest.mark.parametrize("status, link", [("online", "up"), ("offline", "down"), ("unbound", None), ("unknown", None), (None, None), ("", None)])
def test_link_status_is_up_down_or_null(status, link):
    """vSphere HostHostBusAdapter.status 는 online · offline · unbound · unknown — 확인되지 않은 상태는 down 이 아니라 null."""
    d = dict(FC_UP)
    if status is None:
        d.pop("status")
    else:
        d["status"] = status
    hbas, _ = _hbas([d])
    assert hbas[0]["link_status"] == link


@pytest.mark.parametrize("speed, gbps", [(16, 16), (16000, 16), (16000000000, 16), (8000000000, 8), (32000, 32), (2500, 2.5),
                                         (0, None), (None, None), ("16", None)])
def test_speed_is_normalized_by_magnitude(speed, gbps):
    """bps(≥1e6) → /1e9, Mbps(≥1e3) → /1e3, 그 밖 Gbps 그대로. 0(링크 다운)·없음·문자열 → null."""
    d = dict(FC_UP)
    if speed is None:
        d.pop("speed")
    else:
        d["speed"] = speed
    hbas, _ = _hbas([d])
    assert hbas[0]["link_speed_gbps"] == gbps
    if gbps is not None and gbps == int(gbps):
        assert isinstance(hbas[0]["link_speed_gbps"], int)


def test_hardware_iscsi_class_name_is_iscsi():
    d = {"device": "vmhba64", "type": "InternetScsiHba", "driver": "qfle3i", "model": "QLogic 57810 10GbE iSCSI", "status": "online"}
    hbas, _ = _hbas([d])
    assert [(h["name"], h["port_type"], h["wwpn"], h["link_speed_gbps"]) for h in hbas] == [("vmhba64", "iSCSI", None, None)]


def test_software_iscsi_is_still_iscsi():
    d = {"device": "vmhba65", "type": "iSCSI", "driver": "iscsi_vmk", "model": "iSCSI Software Adapter", "status": "online"}
    hbas, _ = _hbas([d])
    assert [(h["name"], h["port_type"]) for h in hbas] == [("vmhba65", "iSCSI")]


@pytest.mark.parametrize("d", [
    {"device": "vmhba33", "type": "Fibre Channel over Ethernet", "driver": "qfle3f", "model": "QLogic 57810 FCoE", "status": "online",
     "port_wwn": "20:00:00:0e:1e:09:30:01", "node_wwn": "10:00:00:0e:1e:09:30:01", "speed": 10},
    {"device": "vmhba34", "type": "FibreChannelOverEthernetHba", "driver": "brcmfcoe", "status": "online",
     "port_wwn": "20:00:00:0e:1e:09:30:02", "node_wwn": "10:00:00:0e:1e:09:30:02"},
    {"device": "vmhba35", "type": "Fibre Channel", "driver": "bnx2fc", "status": "online",
     "port_wwn": "20:00:00:0e:1e:09:30:03", "node_wwn": "10:00:00:0e:1e:09:30:03"},
])
def test_fcoe_class_or_driver_is_fcoe(d):
    hbas, _ = _hbas([d])
    assert len(hbas) == 1 and hbas[0]["port_type"] == "FCoE" and hbas[0]["wwpn"] == d["port_wwn"]


def test_fnic_driver_is_fibre_channel():
    """Cisco VIC fnic/nfnic 는 FC HBA 로 본다 — OS · CIMC 와 같은 값."""
    d = dict(FC_UP, device="vmhba1", driver="nfnic", type="Fibre Channel", model="Cisco VIC FCoE HBA Driver")
    hbas, _ = _hbas([d])
    assert hbas[0]["port_type"] == "FibreChannel"


def test_sas_raid_nvme_controllers_are_not_hbas():
    details = [{"device": "vmhba0", "type": "Block Adapter", "driver": drv, "model": m, "status": "unknown"}
               for drv, m in (("vmw_ahci", "Lewisburg SATA AHCI Controller"), ("lsi_mr3", "PERC H740P"), ("nvme_pcie", "NVMe SSD Controller"),
                              ("smartpqi", "Smart Array P408i-a"))]
    hbas, ctx = _hbas(details)
    assert hbas == [] and ctx["_errors_fragment"] == [] and ctx["_sections_collected_fragment"] == ["network"]


def test_fc_nvme_twin_vmhba_is_collapsed_to_one_entry():
    """ESXi 7 FC-NVMe: 포트당 SCSI vmhba + NVMe vmhba 가 같은 WWPN/WWNN 으로 보인다 — 1 항목 = 물리 포트 1개. 첫 vmhba 를 남긴다."""
    twins = [FC_UP, dict(FC_UP, device="vmhba64"), FC_PORT2, dict(FC_PORT2, device="vmhba65")]
    hbas, ctx = _hbas(twins)
    assert [h["name"] for h in hbas] == ["vmhba2", "vmhba3"]
    assert ctx["_errors_fragment"] == []


def test_distinct_ports_of_the_same_card_are_both_kept():
    hbas, _ = _hbas([FC_UP, FC_PORT2])
    assert [h["wwpn"] for h in hbas] == ["10:00:00:90:fa:1b:2c:3d", "10:00:00:90:fa:1b:2c:3e"]


def test_same_wwpn_with_different_wwnn_is_not_collapsed():
    other = dict(FC_UP, device="vmhba9", node_wwn="20:00:00:90:FA:1B:2C:99")
    hbas, _ = _hbas([FC_UP, other])
    assert len(hbas) == 2


def test_entries_without_wwpn_are_never_collapsed():
    a = {"device": "vmhba64", "type": "iSCSI", "driver": "iscsi_vmk", "status": "online"}
    b = {"device": "vmhba65", "type": "iSCSI", "driver": "iscsi_vmk", "status": "online"}
    hbas, _ = _hbas([a, b])
    assert [h["name"] for h in hbas] == ["vmhba64", "vmhba65"]


def test_malformed_wwn_is_nulled_and_recorded_once():
    """모듈의 WWN 문자열 변환은 홀수 자릿수 · int64 음수에서 깨진 값을 낸다 — 값은 null, 원문은 storage errors[] 1건의 detail."""
    d = dict(FC_UP, port_wwn="-3f:ff:ff:6f:05:e4:d3:c3", node_wwn="20:00:00:90:fa:1b:2c:3")
    hbas, ctx = _hbas([d, FC_PORT2])
    assert hbas[0]["wwpn"] is None and hbas[0]["wwnn"] is None and hbas[0]["name"] == "vmhba2", "행은 남는다"
    assert hbas[1]["wwpn"] == "10:00:00:90:fa:1b:2c:3e"
    errs = _storage_errors(ctx)
    assert len(errs) == 1 and errs[0]["message"] == STOR_TEXT
    assert "cause=malformed_wwn" in errs[0]["detail"] and "count=2" in errs[0]["detail"]
    assert "vmhba2:port_wwn=-3f:ff:ff:6f:05:e4:d3:c3" in errs[0]["detail"] and "vmhba2:node_wwn=20:00:00:90:fa:1b:2c:3" in errs[0]["detail"]
    assert ctx["_sections_collected_fragment"] == ["network", "storage"], "섹션 상태는 그대로 (success + errors)"


def test_well_formed_wwns_record_nothing():
    _, ctx = _hbas([FC_UP, FC_PORT2])
    assert _storage_errors(ctx) == [] and ctx["_e_ext_hba_bad_wwn"] == []


@pytest.mark.parametrize("location, bus, pci, bus_out", [("PCI", -1, None, None), ("N/A", None, None, None), ("", 0, None, 0),
                                                         ("0000:5e:00.0", 94, "0000:5e:00.0", 94)])
def test_placeholder_location_and_bus_are_null(location, bus, pci, bus_out):
    d = dict(FC_UP, location=location)
    if bus is None:
        d.pop("bus")
    else:
        d["bus"] = bus
    hbas, _ = _hbas([d])
    assert (hbas[0]["pci"], hbas[0]["bus"]) == (pci, bus_out)


def test_vmhba_module_failure_and_malformed_wwn_are_separate_errors():
    """모듈 실패(결과 키 없음)는 종전 C9 경로 — 이 경우 bad_wwn 은 비어 있어 1건만 남는다."""
    ctx = _ext(_e_vmhba={"failed": False, "msg": "NoPermission"})
    assert ctx["_e_ext_hbas"] == [] and ctx["_e_ext_hba_bad_wwn"] == []
    assert [e["detail"] for e in _storage_errors(ctx)] == ["scope=vmhba; cause=module_failed; msg=NoPermission"]


def _rescue_errors(failed_msg):
    env = _env()
    doc = yaml.safe_load(EXT.read_text(encoding="utf-8"))
    rescue = doc[0]["rescue"]
    frag = next(t for t in rescue if "ansible.builtin.set_fact" in t)["ansible.builtin.set_fact"]
    ctx = {"ansible_failed_result": {"msg": failed_msg}}
    return render_tree(env, frag["_errors_fragment"], ctx), render_tree(env, frag["_data_fragment"], ctx)


def test_rescue_records_a_storage_error_as_well_as_network():
    """확장 수집 블록이 통째로 실패하면 hbas [] 의 이유도 남아야 한다 — 종전엔 network 1건만."""
    errors, data = _rescue_errors("vmhba module crashed")
    assert [e["section"] for e in errors] == ["network", "storage"]
    stor = errors[1]
    assert stor["detail"] == "scope=vmhba; cause=task_failed; msg=vmhba module crashed"
    assert_user_sentence(stor["message"], "esxi extended rescue storage")
    for token in ("vmhba", "best-effort", "skip"):
        assert token not in stor["message"]
    assert data["storage"]["hbas"] == [] and data["storage"]["infiniband"] == []


def test_rescue_storage_detail_without_message_says_none():
    errors, _ = _rescue_errors("")
    assert errors[1]["detail"] == "scope=vmhba; cause=task_failed; msg=none"
