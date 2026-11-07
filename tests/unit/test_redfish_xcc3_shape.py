"""Lenovo XCC3 응답 모양 (2026-10-27, C4 — 03-network-001/002 · 04-firmware-006 · 05-power-003 · 02-memory-003 · hardware.oem).

실측(용인 2차 SR650 V4 ×4 + 1차 SR650 V4, DL380 Gen12, CSUS)으로 다음을 고정한다.
  (a) 호스트 EthernetInterfaces 중 FC/IB 포트 주소(8옥텟 또는 network_adapters.ports 의 FC/IB 주소)는 network.interfaces 에서 제외하고
      normalize notice 1건을 남긴다. 모듈 raw(data.network)·ports[]·hbas[] 개수는 바뀌지 않는다 (사용자 3차 지시 (iii)).
  (b) Status.State=Disabled 이고 Version 이 빈 '-Pending' 펌웨어는 제외 + notice, Version 이 있으면 pending:true 보존.
  (c) PSU 문자열 strip · DIMM locator DeviceLocator → ServiceLabel → Slot ·
      Lenovo hardware.oem machine_type/led_indicator 를 System.SubModel/IndicatorLED 로.
  (d) 03-network-002 (2026-10-28 독립 검증 F-01 정정): link 가 unknown 인 NIC 은 NIC speed 와 무관하게, MAC 이 같은 Ethernet 포트
      전부가 같은 값일 때만 그 link 로 보충한다(그 NIC 의 speed 가 null 이면 speed 도). 종전 'unknown ∧ speed null' 은 XCC3 NIC 을 놓쳤다.
      본딩 영구 주소 NIC(sr650_v4_02 NIC6 · _04 NIC4)은 포트 쪽 주소가 없어 unknown 으로 남는다 — 미해결, 추측하지 않는다.
  (i) XCC3 는 NetworkDeviceFunctions 컬렉션이 200·0건이어도 Port 신호로 FC 포트 4건이 hbas·ports 에 수집된다 (사용자 3차 지시).
  (ii) 디스크·FC 가 없는 장비는 physical_disks/hbas 가 정확히 [] 이고 placeholder 가 없다.
기대값은 손으로 적었다.
"""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "tests" / "integration"))
sys.path.insert(0, str(REPO / "tests" / "scripts"))

_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402
import emulator_harness as H  # noqa: E402
import inventory_parity as IP  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "redfish"
NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"


def _set_fact(task_name, key):
    for t in yaml.safe_load(NORM.read_text(encoding="utf-8")):
        if isinstance(t, dict) and t.get("name") == task_name:
            return t["ansible.builtin.set_fact"][key]
    raise AssertionError(task_name)


BUNDLE_TPL = _set_fact("redfish | normalize_standard | interfaces (bundle)", "_rf_norm_interfaces_bundle")
NOTICE_TPL = _set_fact("redfish | normalize_standard | interfaces", "_rf_norm_notices")


def _render(tpl, **ctx):
    return NativeEnvironment().from_string(tpl).render(**ctx)


def _golden(name):
    return json.loads((FIX / name / "expected_output.json").read_text(encoding="utf-8"))


def _replay(name):
    case = FIX / name
    rec = json.loads((case / "recording.json").read_text(encoding="utf-8"))
    meta = json.loads((case / "meta.json").read_text(encoding="utf-8")) if (case / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    res = H.run_gather(g, n, realm_impl=r, manager_layout=meta.get("manager_layout"), firmware_scope=meta.get("firmware_inventory_scope"))
    return res, [x["message"] for x in rg.notices()]


# ── (a) FC/IB 주소 EthernetInterfaces 제외 — normalize 층, 모듈 raw 불변 ──────────────────────────────────────────────────

def _bundle_for(name):
    g = _golden(name)["data"]
    return _render(BUNDLE_TPL, _rf_d_network=g["network"], _rf_d_netad=g["network_adapters"]), g


def test_xcc3_fc_in_host_ethernet_is_excluded_from_interfaces_only():
    b, g = _bundle_for("real_lenovo_sr650_v4_02")
    assert len(g["network"]) == 9 and b["fc_excluded"] == 4 and len(b["interfaces"]) == 5
    macs = [i["mac"] for i in b["interfaces"]]
    assert all(len(m.replace(":", "")) == 12 for m in macs)                          # 남은 것은 전부 6옥텟
    assert "21:00:f4:c7:aa:a4:6f:fe" not in macs                                      # = hbas[0].wwpn
    # 모듈 raw·ports·hbas 는 그대로 (사용자 3차 지시 (iii)): 제외는 interfaces 만
    assert len(g["network_adapters"]["fc_hbas"]) == 4
    assert sum(1 for p in g["network_adapters"]["ports"] if p["port_type"] == "FibreChannel") == 4
    notices = _render(NOTICE_TPL, _rf_norm_interfaces_bundle=b)
    assert len(notices) == 1 and notices[0]["section"] == "network" and "4건" in notices[0]["message"]


@pytest.mark.parametrize("name,ifaces,fc_hbas", [
    ("real_lenovo_sr650_v4_03", 15 - 4, 4),
    ("real_lenovo_sr650_v4_01", 5, 0),                 # FC 없음 → 제외 0
    ("real_hpe_dl380_gen12_01", 10, 4),               # iLO 7: FC 포트는 EthernetInterfaces 에 없다 → 제외 0
    ("real_hpe_csus3200_01", 8, 4),
    ("real_dell_r740", 12, 4),                       # Dell: 호스트 EthernetInterfaces 12 (FC 포트는 NetworkAdapters 에만)
])
def test_exclusion_only_touches_hosts_that_expose_fc_as_ethernet(name, ifaces, fc_hbas):
    b, g = _bundle_for(name)
    assert len(b["interfaces"]) == ifaces and len(g["network_adapters"]["fc_hbas"]) == fc_hbas
    assert b["fc_excluded"] == len(g["network"]) - ifaces
    notices = _render(NOTICE_TPL, _rf_norm_interfaces_bundle=b)
    assert (len(notices) == 1) == (b["fc_excluded"] > 0)                          # 제외가 있을 때만 notice 1건


def test_exclusion_rule_uses_address_length_and_fc_ib_port_addresses():
    netad = {"ports": [
        {"adapter_id": "a", "port_id": "1", "port_type": "FibreChannel", "associated_address": "21:00:00:11:22:33:44:55", "link_status": "down"},
        {"adapter_id": "b", "port_id": "1", "port_type": "InfiniBand", "associated_address": "00:11:22:33:44:55", "link_status": "up"},
        {"adapter_id": "c", "port_id": "1", "port_type": "Ethernet", "associated_address": "aa:bb:cc:dd:ee:01", "link_status": "up", "current_link_speed_mbps": 25000},
    ], "adapters": [], "fc_hbas": [], "infiniband": []}
    network = [
        {"id": "NIC1", "name": "eth", "mac": "aa:bb:cc:dd:ee:01", "link_status": None, "speed_mbps": None, "ipv4": []},     # unknown+null → 포트로 보충
        {"id": "NIC2", "name": "eth", "mac": "aa:bb:cc:dd:ee:02", "link_status": None, "speed_mbps": None, "ipv4": []},     # 포트 없음 → 그대로
        {"id": "NIC3", "name": "fc", "mac": "21:00:00:11:22:33:44:55", "link_status": None, "speed_mbps": 0, "ipv4": []},    # 8옥텟 → 제외
        {"id": "NIC4", "name": "ib", "mac": "00:11:22:33:44:55", "link_status": None, "speed_mbps": 0, "ipv4": []},         # IB 포트 주소와 같음 → 제외
        {"id": "NIC5", "name": "eth", "mac": "aa:bb:cc:dd:ee:03", "link_status": "LinkUp", "speed_mbps": 1000, "ipv4": []},  # 값이 있으면 보충 안 함
    ]
    b = _render(BUNDLE_TPL, _rf_d_network=network, _rf_d_netad=netad)
    out = {i["id"]: i for i in b["interfaces"]}
    assert sorted(out) == ["NIC1", "NIC2", "NIC5"] and b["fc_excluded"] == 2
    assert out["NIC1"]["link_status"] == "up" and out["NIC1"]["speed_mbps"] == 25000
    assert out["NIC2"]["link_status"] == "unknown" and out["NIC2"]["speed_mbps"] is None
    assert out["NIC5"]["link_status"] == "linkup" and out["NIC5"]["speed_mbps"] == 1000
    assert out["NIC5"]["is_primary"] is False and out["NIC1"]["is_primary"] is True   # IPv4 없음 → 첫 up NIC fallback


# ── (d) 03-network-002 — 같은 MAC 포트로 link 보충: NIC speed 와 무관, 포트 전부 일치할 때만 ──────────────────────────────────────

SUMMARY_TPL = _set_fact("redfish | normalize_standard | compute group summaries", "_rf_summary_network")


def _eth_port(aid, pid, mac, link, speed):
    return {"adapter_id": aid, "port_id": pid, "port_type": "Ethernet", "associated_address": mac,
            "link_status": link, "current_link_speed_mbps": speed}


def _nic(nid, mac, link="unknown", speed=None):
    return {"id": nid, "name": nid, "mac": mac, "link_status": link, "speed_mbps": speed, "ipv4": []}


def _ifaces(network, ports):
    netad = {"ports": ports, "adapters": [], "fc_hbas": [], "infiniband": []}
    return {i["id"]: i for i in _render(BUNDLE_TPL, _rf_d_network=network, _rf_d_netad=netad)["interfaces"]}


def test_link_fill_does_not_depend_on_nic_speed():
    # XCC3 실측 모양: 호스트 NIC 에 LinkStatus 가 없고 SpeedMbps 25600/0 이 있다 — 종전 조건(speed null)은 이 NIC 을 놓쳤다
    out = _ifaces([_nic("NIC2", "aa:bb:cc:00:00:01", speed=25600), _nic("NIC1", "aa:bb:cc:00:00:02", speed=0)],
                  [_eth_port("slot13", "1", "aa:bb:cc:00:00:01", "up", 25000), _eth_port("slot13", "2", "aa:bb:cc:00:00:02", "down", None)])
    assert (out["NIC2"]["link_status"], out["NIC2"]["speed_mbps"]) == ("up", 25600)         # speed 는 NIC 값(포트 25000 아님)
    assert (out["NIC1"]["link_status"], out["NIC1"]["speed_mbps"]) == ("down", 0)


@pytest.mark.parametrize("links,expected", [
    (("up", "up"), "up"),
    (("down", "down"), "down"),
    (("up", "down"), "unknown"),          # 포트끼리 다르면 보충하지 않는다
    (("up", "unknown"), "unknown"),
    (("up", None), "unknown"),
])
def test_link_fill_uses_every_same_mac_port_and_requires_agreement(links, expected):
    # 본딩 실측(sr650_v4_02/04 NIC2): 같은 MAC 이 두 포트의 AssociatedMACAddresses[0] 에 있다. 종전에는 뒤 포트가 앞 포트를 덮었다
    ports = [_eth_port("slot13", "1", "aa:bb:cc:00:00:01", links[0], 25000), _eth_port("slot14", "1", "aa:bb:cc:00:00:01", links[1], 25000)]
    assert _ifaces([_nic("NIC2", "aa:bb:cc:00:00:01", speed=25600)], ports)["NIC2"]["link_status"] == expected


@pytest.mark.parametrize("speeds,expected", [
    ((25000, 25000), 25000),
    ((25000, None), None),               # 포트끼리 다르면 null 유지
    ((25000, 10000), None),
    ((None, None), None),
])
def test_speed_fill_needs_null_nic_speed_and_agreeing_ports(speeds, expected):
    ports = [_eth_port("a", "1", "aa:bb:cc:00:00:01", "up", speeds[0]), _eth_port("b", "1", "aa:bb:cc:00:00:01", "up", speeds[1])]
    out = _ifaces([_nic("NIC1", "aa:bb:cc:00:00:01")], ports)
    assert (out["NIC1"]["link_status"], out["NIC1"]["speed_mbps"]) == ("up", expected)


def test_link_fill_never_overwrites_nic_values_and_never_defaults_to_down():
    ports = [_eth_port("a", "1", "aa:bb:cc:00:00:01", "up", 25000), _eth_port("a", "2", "aa:bb:cc:00:00:02", "up", 25000)]
    out = _ifaces([
        _nic("NIC1", "aa:bb:cc:00:00:01", link="LinkDown"),            # NIC 자체 link 가 있으면 그대로 — speed 도 건드리지 않는다
        _nic("NIC2", "aa:bb:cc:00:00:02", link="up"),                  # iLO 실측 모양(link up · speed null) — speed 보충 안 함
        _nic("NIC3", "aa:bb:cc:00:00:03"),                             # 같은 MAC 포트 없음
    ], ports)
    assert (out["NIC1"]["link_status"], out["NIC1"]["speed_mbps"]) == ("linkdown", None)
    assert (out["NIC2"]["link_status"], out["NIC2"]["speed_mbps"]) == ("up", None)
    assert (out["NIC3"]["link_status"], out["NIC3"]["speed_mbps"]) == ("unknown", None)  # HBA 의 down 정책을 쓰지 않는다


# 원천: 같은 MAC 의 Chassis/1/NetworkAdapters/<id>/Ports/<n>.LinkStatus (호스트 NIC 원문 Systems/1/EthernetInterfaces/NICn 에는 LinkStatus 가 없다)
XCC3_LINKS = {
    "real_lenovo_sr650_v4_01": ({"ToManager": "unknown", "NIC1": "down", "NIC2": "up", "NIC3": "down", "NIC4": "up"}, "NIC2"),
    "real_lenovo_sr650_v4_02": ({"ToManager": "unknown", "NIC1": "down", "NIC2": "up", "NIC5": "down", "NIC6": "unknown"}, "NIC2"),
    "real_lenovo_sr650_v4_03": ({"ToManager": "unknown", **{f"NIC{i}": "up" for i in (1, 2, 3, 4, 9, 10, 11, 12, 13, 14)}}, "NIC1"),
    "real_lenovo_sr650_v4_04": ({"ToManager": "unknown", "NIC1": "down", "NIC2": "up", "NIC3": "down", "NIC4": "unknown"}, "NIC2"),
}


@pytest.mark.parametrize("name", sorted(XCC3_LINKS))
def test_xcc3_fixture_links_come_from_same_mac_ports(name):
    links, primary = XCC3_LINKS[name]
    b, g = _bundle_for(name)
    out = {i["id"]: i for i in b["interfaces"]}
    raw = {n["id"]: n for n in g["network"]}
    assert all(raw[k]["link_status"] == "unknown" for k in out)                     # 모듈 값은 전부 unknown
    assert {k: v["link_status"] for k, v in out.items()} == links
    assert [k for k, v in out.items() if v["is_primary"]] == [primary]
    assert all(out[k]["speed_mbps"] == raw[k]["speed_mbps"] for k in out)          # speed 는 NIC 값 그대로


@pytest.mark.parametrize("name,nic", [("real_lenovo_sr650_v4_02", "NIC6"), ("real_lenovo_sr650_v4_04", "NIC4")])
def test_bonded_permanent_mac_nic_stays_unknown(name, nic):
    # 미해결(2026-10-28 HOLD): 이 NIC 의 MAC 은 slot14 Ports/1 의 AssociatedMACAddresses[1](영구 주소)에만 있고 모듈은 [0] 만 내보낸다.
    # NIC 의 SpeedMbps 25600 으로 링크를 추측하지 않는다.
    b, g = _bundle_for(name)
    raw = {n["id"]: n for n in g["network"]}
    port_addrs = {(p.get("associated_address") or "").lower() for p in g["network_adapters"]["ports"]}
    assert raw[nic]["speed_mbps"] == 25600 and raw[nic]["mac"].lower() not in port_addrs
    assert {i["id"]: i["link_status"] for i in b["interfaces"]}[nic] == "unknown"


# 종전 보충 결과(DL380 3 label 16건, 전부 down)는 그대로이고, link 가 이미 있는 iLO NIC 의 speed(null)는 건드리지 않는다
DL380_FILLED = {
    "real_hpe_dl380": {"14", "141", "142", "206"},
    "real_hpe_dl380_gen12_01": {"77", "141", "142", "270", "334", "461"},
    "real_hpe_dl380_gen12_02": {"13", "14", "142", "205", "206", "334"},
}


@pytest.mark.parametrize("name", sorted(DL380_FILLED))
def test_dl380_fill_result_is_unchanged(name):
    b, g = _bundle_for(name)
    raw = {n["id"]: n for n in g["network"]}
    out = {i["id"]: i for i in b["interfaces"]}
    filled = {k for k, v in out.items() if raw[k]["link_status"] == "unknown" and v["link_status"] != "unknown"}
    assert filled == DL380_FILLED[name] and {out[k]["link_status"] for k in filled} == {"down"}
    assert all(v["speed_mbps"] == raw[k]["speed_mbps"] for k, v in out.items())


@pytest.mark.parametrize("name,unknown", [
    # 2026-10-29 SA-13 정정 — 종전 설명 "같은 MAC 포트 없음" · "포트 0" 은 틀렸다. 같은 MAC 을 첫 주소로 가진 포트가 NIC 마다 있지만
    # 그 포트 본문에 LinkStatus 키가 없어(recording 실측) 포트도 unknown 이다 — 채울 값이 없다(기대값은 종전 그대로).
    ("real_hpe_csus3200_01", 8), ("real_hpe_csus3200_02", 4), ("real_hpe_csus3200_03", 8),   # 같은 MAC 포트 있음 · 포트 LinkStatus 없음
    ("real_hpe_dl380_gen12_03", 4),                                                          # 전원 Off — Ethernet 포트 4개 · 전부 LinkStatus 없음
    ("real_lenovo_sr650", 1),                                                                # ToManager
    ("real_hpe_dl380_gen12_04", 0), ("real_dell_r740", 0),
])
def test_hosts_without_port_link_signal_keep_unknown(name, unknown):
    b, _ = _bundle_for(name)
    assert sum(1 for i in b["interfaces"] if i["link_status"] == "unknown") == unknown


def _summary(name, interfaces):
    env = NativeEnvironment()
    env.filters["regex_replace"] = lambda s, pat, rep="": re.sub(pat, rep, "" if s is None else str(s))
    g = _golden(name)      # 모듈 출력 그대로가 _rf_raw_collect — collected 로 port_count · adapter_count 의 null/정수를 가른다 (2026-10-29)
    return env.from_string(SUMMARY_TPL).render(_rf_d_netad=g["data"]["network_adapters"], _rf_norm_interfaces=interfaces, _rf_raw_collect=g)


# 2026-10-29 (SA-08, 사용자 결정): Summary 그룹 키의 speed 0 은 null — link down NIC 의 원본 0(interfaces[].speed_mbps)은 그대로 둔다.
@pytest.mark.parametrize("name,groups", [
    ("real_lenovo_sr650_v4_01", [(None, 1, 0), (None, 2, 0), (25600, 2, 2)]),
    ("real_lenovo_sr650_v4_02", [(None, 1, 0), (None, 2, 0), (25600, 1, 1), (25600, 1, 0)]),   # 마지막 그룹 = NIC6 (unknown)
    ("real_lenovo_sr650_v4_03", [(None, 1, 0), (25600, 4, 4), (25600, 6, 6)]),
    ("real_lenovo_sr650_v4_04", [(None, 1, 0), (None, 2, 0), (25600, 1, 1), (25600, 1, 0)]),   # 마지막 그룹 = NIC4 (unknown)
])
def test_xcc3_network_summary_counts_filled_links(name, groups):
    b, _ = _bundle_for(name)
    s = _summary(name, b["interfaces"])
    assert [(x["speed_mbps"], x["quantity"], x["link_up_count"]) for x in s["groups"]] == groups
    assert s["primary_speed_mbps"] == 25600
    zero = [i for i in b["interfaces"] if i["speed_mbps"] == 0]
    assert len(zero) == (0 if name == "real_lenovo_sr650_v4_03" else 2)          # 상세의 원본 0 은 남는다
    assert {i["link_status"] for i in zero} <= {"down"}


# ── (i)(ii) 사용자 3차 지시 — XCC3 FC 포트 수집 · 장치 없는 장비의 빈 목록 ──────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["real_lenovo_sr650_v4_02", "real_lenovo_sr650_v4_03"])
def test_xcc3_collects_fc_ports_even_with_empty_ndf_collection(name):
    rec = json.loads((FIX / name / "recording.json").read_text(encoding="utf-8"))
    res, _ = _replay(name)
    # FC 카드(hbas 의 adapter_id)의 NetworkDeviceFunctions 컬렉션은 200 이지만 0건이다 — NIC 카드(E810)는 NDF 가 있다
    fc_adapters = {h["adapter_id"] for h in res["data"]["network_adapters"]["fc_hbas"]}
    assert fc_adapters
    for aid in fc_adapters:
        key = f"get::Chassis/1/NetworkAdapters/{aid}/NetworkDeviceFunctions"
        assert rec[key][0] == 200 and (rec[key][1].get("Members@odata.count") or len(rec[key][1].get("Members") or [])) == 0, aid
    assert len(res["data"]["network_adapters"]["fc_hbas"]) == 4
    assert sum(1 for p in res["data"]["network_adapters"]["ports"] if p["port_type"] == "FibreChannel") == 4
    parity = IP.run(recording=str(FIX / name / "recording.json"), module_doc=res)
    assert parity["verdict"]["pass"] and parity["exposure"]["fc_ports"] == 4


@pytest.mark.parametrize("name,disks,hbas", [
    ("real_hpe_csus3200_02", 4, 0),      # FC 카드 없음
    ("real_hpe_dl380_gen12_03", 0, 0),   # 전원 Off — Storage 0
    ("real_hpe_csus3200", 0, 4),         # 1차 CSUS 01 — 디스크 미노출
    ("real_lenovo_sr650_v4_01", 4, 0),
])
def test_absent_devices_give_exact_empty_lists_not_placeholders(name, disks, hbas):
    res, _ = _replay(name)
    drives = [d for c in res["data"]["storage"]["controllers"] for d in (c.get("drives") or [])]
    assert len(drives) == disks and len(res["data"]["network_adapters"]["fc_hbas"]) == hbas
    assert all(d.get("id") or d.get("serial") for d in drives)
    parity = IP.run(recording=str(FIX / name / "recording.json"), module_doc=res)
    assert parity["verdict"]["pass"]


# ── (b) Disabled · Version 없는 -Pending 제외 ───────────────────────────────────────────────────────────────────────────────

def _routed(routes, calls):
    def fake(bmc_ip, path, *a, **kw):
        calls.append(path)
        return routes.get(path, (404, {}, "HTTP 404: Not Found"))
    return fake


def test_disabled_pending_without_version_is_dropped_with_notice(monkeypatch):
    coll = {"Members": [{"@odata.id": f"/redfish/v1/UpdateService/FirmwareInventory/{i}"} for i in ("UEFI", "UEFI-Pending", "BMC-Pending-Staged")]}
    routes = {
        "UpdateService/FirmwareInventory": (200, coll, None),
        "UpdateService/FirmwareInventory/UEFI": (200, {"Id": "UEFI", "Name": "Firmware:UEFI", "Version": "20L-1.50", "Status": {"State": "Enabled"}}, None),
        "UpdateService/FirmwareInventory/UEFI-Pending": (200, {"Id": "UEFI-Pending", "Name": "Firmware:UEFI", "Version": "", "Status": {"State": "Disabled"}}, None),
        "UpdateService/FirmwareInventory/BMC-Pending-Staged": (200, {"Id": "BMC-Pending-Staged", "Name": "Firmware:BMC", "Version": "38R-2.98", "Status": {"State": "Disabled"}}, None),
    }
    calls = []
    rg._reset_notices()
    monkeypatch.setattr(rg, "_get", _routed(routes, calls))
    fw, errs = rg.gather_firmware("10.0.0.1", "u", "p", 30, False)
    ids = {f["id"]: f for f in fw}
    assert sorted(ids) == ["BMC-Pending-Staged", "UEFI"] and errs == []
    assert ids["BMC-Pending-Staged"]["pending"] is True and ids["BMC-Pending-Staged"]["version"] == "38R-2.98"
    assert [n["message"] for n in rg.notices() if "UEFI-Pending" in n["message"]] == ["UEFI-Pending: Disabled · Version 없음(예정된 업데이트 없음) — 목록에서 제외"]


def test_xcc3_recording_drops_the_four_empty_pending_slots():
    res, notices = _replay("real_lenovo_sr650_v4_01")
    fw = res["data"]["firmware"]
    assert len(fw) == 24 and not [f for f in fw if f["id"].endswith("-Pending")]
    assert all(f["version"] for f in fw)
    assert sum(1 for m in notices if "Disabled · Version 없음" in m) == 4


# ── (c) PSU strip · locator 순서 · Lenovo oem ─────────────────────────────────────────────────────────────────────────────

def test_psu_strings_are_stripped_in_both_power_paths():
    res, _ = _replay("real_lenovo_sr650_v4_01")
    assert [p["model"] for p in res["data"]["power"]["power_supplies"]] == ["CRPS1300D5", "CRPS1300D5"]
    res2, _ = _replay("real_hpe_csus3200_01")                                        # PowerSubsystem 경로 — 값 불변(공백 없음)
    assert all(p["model"] == p["model"].strip() for p in res2["data"]["power"]["power_supplies"] if p["model"])


@pytest.mark.parametrize("body,expected", [
    ({"DeviceLocator": "DIMM_A1", "MemoryLocation": {"Slot": 0}, "Location": {"PartLocation": {"ServiceLabel": "ignored"}}}, "DIMM_A1"),
    ({"MemoryLocation": {"Slot": 23}, "Location": {"PartLocation": {"ServiceLabel": "DIMM 23"}}}, "DIMM 23"),      # Lenovo XCC3 실측
    ({"MemoryLocation": {"Slot": 0}, "Location": {"PartLocation": {"ServiceLabel": "rack1/chassis_u1/cpu0/dimmA0"}}}, "rack1/chassis_u1/cpu0/dimmA0"),  # CSUS
    ({"MemoryLocation": {"Slot": 32}}, "32"),                                                                            # ServiceLabel 없음 → str(Slot)
    ({}, None),
])
def test_memory_locator_prefers_device_locator_then_service_label_then_slot(monkeypatch, body, expected):
    member = dict({"Id": "M", "Name": "DIMM", "CapacityMiB": 16384, "Status": {"State": "Enabled"}}, **body)
    routes = {"Systems/1/Memory": (200, {"Members": [{"@odata.id": "/redfish/v1/Systems/1/Memory/M"}]}, None),
              "Systems/1/Memory/M": (200, member, None)}
    monkeypatch.setattr(rg, "_get", _routed(routes, []))
    out, _ = rg.gather_memory("10.0.0.1", "/redfish/v1/Systems/1", "u", "p", 30, False)
    assert out["slots"][0]["locator"] == expected


def test_lenovo_oem_fills_machine_type_and_led_from_system_when_chassis_lacks_them():
    sys_body = {"Model": "ThinkSystem SR650 V4", "SubModel": "7DGD", "IndicatorLED": "Off", "Oem": {"Lenovo": {"SystemStatus": "OSBooted"}}}
    oem = rg._extract_oem_lenovo(sys_body, chassis_data={"Oem": {"Lenovo": {"ProductName": "ThinkSystem SR650 V4"}}})
    assert oem["machine_type"] == "7DGD" and oem["led_indicator"] == "Off" and oem["product_name"] == "ThinkSystem SR650 V4"
    # chassis OEM 이 주면(XCC1/2) 그 값이 먼저다
    oem2 = rg._extract_oem_lenovo(sys_body, chassis_data={"Oem": {"Lenovo": {"MachineType": "7X06", "LEDIndicators": ["X"]}}})
    assert oem2["machine_type"] == "7X06" and oem2["led_indicator"] == ["X"]
    assert rg._extract_oem_lenovo({"Model": "M"})["machine_type"] is None


def test_xcc3_recording_oem_has_machine_type_and_led():
    res, _ = _replay("real_lenovo_sr650_v4_01")
    oem = res["data"]["system"]["oem"]
    assert oem["machine_type"] == "7DGD" and oem["led_indicator"] == "Off" and oem["system_status"] == "OSBooted"
