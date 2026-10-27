"""기존 필드 보강 (2026-10-27, 2차 Mock C8 — 요청 추가 0):
  03-network-004 포트 0 Mbps → null · 03-network-007 NDF MTU → interfaces[].mtu(MAC join, null 일 때만, normalize 층) · 03-network-006 IPv6 addresses ·
  03-storage-003 Drive.Identifiers → physical_disks[].wwn · OEM 캐시 → processors[].l2/l3_cache_kb → cpu.summary.groups[] ·
  02-memory-004 HPE Label → rank_count · 01-hardware-004 ≡ 04-bios-001 FirmwareInventory ReleaseDate → hardware.bios_date(OEM 날짜 없을 때만).
실측 fixture(real_*) 재생 + 합성 변형. 기대값은 손으로 적었다. 새 키는 원천이 있을 때만 모듈이 낸다.
"""
from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "tests" / "integration"))

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

FIX = REPO / "tests" / "fixtures" / "redfish"
NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"


def _set_fact(task_name, key):
    for t in yaml.safe_load(NORM.read_text(encoding="utf-8")):
        if isinstance(t, dict) and t.get("name") == task_name:
            return t["ansible.builtin.set_fact"][key]
    raise AssertionError(task_name)


def _set_fact_var(key):
    for t in yaml.safe_load(NORM.read_text(encoding="utf-8")):
        sf = t.get("ansible.builtin.set_fact") if isinstance(t, dict) else None
        if isinstance(sf, dict) and key in sf:
            return sf[key]
    raise AssertionError(key)


BUNDLE_TPL = _set_fact("redfish | normalize_standard | interfaces (bundle)", "_rf_norm_interfaces_bundle")


def _render(tpl, **ctx):
    return NativeEnvironment().from_string(tpl).render(**ctx)


def _replay(name, mutate=None):
    case = FIX / name
    rec = json.loads((case / "recording.json").read_text(encoding="utf-8"))
    if mutate:
        mutate(rec)
    meta = json.loads((case / "meta.json").read_text(encoding="utf-8")) if (case / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    res = H.run_gather(g, n, realm_impl=r, manager_layout=meta.get("manager_layout"), firmware_scope=meta.get("firmware_inventory_scope"))
    return res, [x["message"] for x in rg.notices()]


# ── 03-network-004: 포트 0 Mbps 는 링크 없음 → null ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pdata, expected", [
    ({"CurrentLinkSpeedMbps": 0}, (None, None)),                       # iDRAC9 NetworkPorts down (실측 R740)
    ({"CurrentLinkSpeedMbps": 10000}, (10.0, 10000)),
    ({"CurrentSpeedGbps": 0}, (None, None)),                           # Ports (SCHEMA-02 종전 규칙)
    ({"CurrentSpeedGbps": 25}, (25, 25000)),
    ({"CurrentLinkSpeedMbps": 0, "CurrentSpeedGbps": 25}, (25, 25000)),  # 0 Mbps 는 모르는 값 — Gbps 로 역산
    ({}, (None, None)),
])
def test_port_speed_zero_mbps_is_null_like_zero_gbps(pdata, expected):
    assert rg._normalize_port_speed(pdata) == expected


def test_dell_r740_down_ports_have_null_speed_and_up_ports_keep_value():
    res, _ = _replay("real_dell_r740")
    ports = res["data"]["network_adapters"]["ports"]
    assert not [p for p in ports if p["current_link_speed_mbps"] == 0]
    downs = [p for p in ports if p["link_status"] == "down"]
    ups = [p for p in ports if p["link_status"] == "up"]
    assert len(downs) == 14 and all(p["current_link_speed_mbps"] is None for p in downs)          # Ethernet 10(0 Mbps 였음) + FC 4
    assert sum(1 for p in downs if p["port_type"] == "Ethernet") == 10
    assert ups and all(p["current_link_speed_mbps"] for p in ups)
    assert [a["speed_mbps"] for a in res["data"]["network_adapters"]["adapters"] if a["speed_mbps"]], "adapter fold-in 은 양수만 쓰므로 불변"


# ── 03-network-007: NDF Ethernet.MTUSize → interfaces[].mtu (normalize 층, MAC join) ──────────────────────────────────

def test_lenovo_ndf_mtu_goes_to_aux_and_fills_null_interface_mtu_only():
    res, _ = _replay("real_lenovo_sr650_v4_03")
    mtu_map = res["aux"]["ndf_mtu_by_mac"]
    assert len(mtu_map) == 10 and set(mtu_map.values()) == {1500}
    assert all(len(k) == 12 and k == k.upper() and ":" not in k for k in mtu_map)
    assert all(n.get("mtu") is None for n in res["data"]["network"]), "모듈 raw 호스트 NIC 은 그대로(MTUSize 없음)"
    assert "mtu" not in json.dumps(res["data"]["network_adapters"]["ports"][0]), "ports[] 에 새 키를 내지 않는다"
    b = _render(BUNDLE_TPL, _rf_d_network=res["data"]["network"], _rf_d_netad=res["data"]["network_adapters"], _rf_ndf_mtu=mtu_map)
    filled = [i for i in b["interfaces"] if i["mtu"] == 1500]
    assert filled and all(i["mtu"] in (1500, None) for i in b["interfaces"])
    for i in filled:
        assert i["mac"].upper().replace(":", "") in mtu_map
    # aux 없이 렌더하면 종전과 같다(null)
    b0 = _render(BUNDLE_TPL, _rf_d_network=res["data"]["network"], _rf_d_netad=res["data"]["network_adapters"], _rf_ndf_mtu={})
    assert all(i["mtu"] is None for i in b0["interfaces"])


def test_host_nic_mtu_wins_over_ndf_mtu():
    nic = {"id": "1", "name": "n1", "mac": "ec:e7:a7:22:59:5c", "mtu": 9000, "speed_mbps": None, "link_status": "up", "health": "OK", "ipv4": []}
    b = _render(BUNDLE_TPL, _rf_d_network=[nic], _rf_d_netad={"ports": []}, _rf_ndf_mtu={"ECE7A722595C": 1500})
    assert b["interfaces"][0]["mtu"] == 9000


@pytest.mark.parametrize("name, expected", [("real_hpe_csus3200_01", 0), ("real_dell_r740", 0), ("real_hpe_dl380_gen12_01", 10), ("real_hpe_dl380_gen12_03", 0)])
def test_ndf_mtu_aux_counts(name, expected):
    res, _ = _replay(name)
    assert len(res["aux"]["ndf_mtu_by_mac"]) == expected


# ── 03-network-006: IPv6Addresses (합성 — 실측 18대 전부 빈 목록) ────────────────────────────────────────────────────

def _add_ipv6(rec):
    for k, v in rec.items():
        if k.startswith("get::Systems/1/EthernetInterfaces/") and isinstance(v, list) and isinstance(v[1], dict) and v[1].get("MACAddress"):
            v[1]["IPv6Addresses"] = [{"Address": "fd00::10", "PrefixLength": 64, "AddressOrigin": "Static"},
                                     {"Address": "::", "PrefixLength": 0}, {"Address": "", "PrefixLength": 64}]
            return
    raise AssertionError("no host NIC")


def test_ipv6_addresses_are_emitted_only_when_present_and_rendered_as_family_ipv6():
    res, _ = _replay("real_lenovo_sr650_v4_01")
    assert all("ipv6" not in n for n in res["data"]["network"]), "원천이 없으면 키 자체가 없다(golden 불변)"
    res2, _ = _replay("real_lenovo_sr650_v4_01", mutate=_add_ipv6)
    with_v6 = [n for n in res2["data"]["network"] if n.get("ipv6")]
    assert len(with_v6) == 1 and with_v6[0]["ipv6"] == [{"address": "fd00::10", "prefix_length": 64, "address_origin": "Static"}]
    b = _render(BUNDLE_TPL, _rf_d_network=res2["data"]["network"], _rf_d_netad=res2["data"]["network_adapters"], _rf_ndf_mtu={})
    v6 = [a for i in b["interfaces"] for a in i["addresses"] if a["family"] == "ipv6"]
    assert v6 == [{"family": "ipv6", "address": "fd00::10", "prefix_length": 64, "subnet_mask": None, "gateway": None, "origin": "Static"}]
    part = rg._normalize_network_raw(res2["data"]["network"])
    assert [a for i in part["interfaces"] for a in i["addresses"] if a["family"] == "ipv6"] == v6


# ── 03-storage-003: Drive.Identifiers → wwn ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ddata, expected", [
    ({"Identifiers": [{"DurableName": "50000F0075A05AF1", "DurableNameFormat": "NAA"}]}, "naa.50000f0075a05af1"),   # iLO 7 Gen12 실측
    ({"Identifiers": [{"DurableName": "5000c5009a22d3ad", "DurableNameFormat": "NAA"}]}, "naa.5000c5009a22d3ad"),   # iDRAC9 실측
    ({"Identifiers": [{"DurableName": "naa.5000C5009A22D3AD", "DurableNameFormat": "NAA"}]}, "naa.5000c5009a22d3ad"),
    ({"Identifiers": [{"DurableName": "0x5000c5009a22d3ad", "DurableNameFormat": "NAA"}]}, "naa.5000c5009a22d3ad"),
    ({"Identifiers": [{"DurableName": "eui.0025385A91B0D8F3", "DurableNameFormat": "EUI"}]}, "eui.0025385a91b0d8f3"),
    ({"Identifiers": [{"DurableName": "Disk 1", "DurableNameFormat": "UUID"}]}, None),
    ({"Identifiers": []}, None), ({}, None), ({"Identifiers": "x"}, None),
])
def test_drive_wwn_from_identifiers(ddata, expected):
    assert rg._drive_wwn(ddata) == expected


@pytest.mark.parametrize("name, with_wwn, total", [
    ("real_hpe_dl380_gen12_02", 4, 4), ("real_hpe_dl380_gen12_01", 2, 2), ("real_hpe_dl380", 2, 2), ("real_dell_r740", 4, 4),
    ("real_lenovo_sr650_v4_04", 0, 6), ("real_hpe_csus3200_03", 0, 4),      # RMC node03: SAS SSD 4 (Identifiers 없음)
])
def test_physical_disk_wwn_key_only_when_identifiers_exist(name, with_wwn, total):
    res, _ = _replay(name)
    drives = [d for c in res["data"]["storage"]["controllers"] for d in c["drives"]]
    assert len(drives) == total
    assert sum(1 for d in drives if "wwn" in d) == with_wwn
    assert all(d["wwn"].startswith(("naa.", "eui.")) and d["wwn"] == d["wwn"].lower() for d in drives if "wwn" in d)
    norm = _render(_set_fact_var("_rf_norm_physical_disks"), _rf_d_storage=res["data"]["storage"])
    assert all("wwn" in d for d in norm), "최종 physical_disks[] 는 항상 wwn 키(값 없으면 null — OS/ESXi 와 같은 모양)"
    assert sum(1 for d in norm if d["wwn"]) == min(with_wwn, len(norm))


# ── OEM 캐시 → processors[].l2/l3_cache_kb → cpu.summary.groups[] ───────────────────────────────────────────────────

@pytest.mark.parametrize("pdata, expected", [
    ({"Oem": {"Hpe": {"Cache": [{"Name": "L1-Cache", "InstalledSizeKB": 3584}, {"Name": "L2-Cache", "InstalledSizeKB": 65536}, {"Name": "L3-Cache", "InstalledSizeKB": 147456}]}}}, (65536, 147456)),
    ({"Oem": {"Lenovo": {"CacheInfo": [{"CacheLevel": "L1", "InstalledSizeKByte": 1792}, {"CacheLevel": "L2", "InstalledSizeKByte": 32768}, {"CacheLevel": "L3", "InstalledSizeKByte": 73728}]}}}, (32768, 73728)),
    ({"Oem": {"Dell": {"DellProcessor": {"Cache1Level": "L1", "Cache1InstalledSizeKB": 1536, "Cache2Level": "L2", "Cache2InstalledSizeKB": 24576, "Cache3Level": "L3", "Cache3InstalledSizeKB": 36608}}}}, (24576, 36608)),
    ({"Oem": {"Hpe": {"L3CacheSize": "22.50 MB"}}}, (None, 23040)),        # RMC 실측 — L3 만
    ({"Oem": {"Hpe": {"L3CacheSize": "75 MB", "L2CacheSize": "2048 KB"}}}, (2048, 76800)),
    ({"Oem": {"Hpe": {"Cache": [{"Name": "L2-Cache", "InstalledSizeKB": 0}]}}}, (None, None)),   # 0 은 모르는 값
    ({"Oem": {"Hpe": {"L3CacheSize": "unknown"}}}, (None, None)),
    ({"Oem": {}}, (None, None)), ({}, (None, None)), ({"Oem": "x"}, (None, None)),
])
def test_processor_cache_kb_from_oem_namespaces(pdata, expected):
    assert rg._processor_cache_kb(pdata) == expected


@pytest.mark.parametrize("value, kb", [("22.50 MB", 23040), ("45 MB", 46080), ("1024 KB", 1024), ("1 GB", 1048576), (2048, 2048), (0, None), (True, None), ("", None), (None, None), ("x MB", None)])
def test_cache_string_kb(value, kb):
    assert rg._cache_string_kb(value) == kb


@pytest.mark.parametrize("name, l2, l3", [
    ("real_hpe_dl380_gen12_01", 65536, 147456),   # 6737P: 2 MB × 32 · 144 MB
    ("real_lenovo_sr650_v4_01", 65536, 147456),   # XCC 3 CacheInfo (6737P)
    ("real_lenovo_sr650", 32768, 73728),          # XCC 3 1차 (6724P)
    ("real_dell_r740", 24576, 36608),              # iDRAC9 DellProcessor
    ("real_hpe_csus3200_01", None, 46080),         # RMC L3 '45 MB' 만
])
def test_processors_and_groups_carry_per_socket_cache(name, l2, l3):
    res, _ = _replay(name)
    procs = res["data"]["processors"]
    assert procs and all(p.get("l3_cache_kb") == l3 for p in procs)
    assert all(p.get("l2_cache_kb") == l2 for p in procs) and (l2 is not None or all("l2_cache_kb" not in p for p in procs))
    groups = _render(_set_fact_var("_rf_summary_cpu"), _rf_d_cpus=procs)["groups"]
    assert groups and groups[0]["l2_cache_kb"] == l2 and groups[0]["l3_cache_kb"] == l3


def test_groups_cache_is_null_when_processor_has_no_cache_keys():
    groups = _render(_set_fact_var("_rf_summary_cpu"), _rf_d_cpus=[{"model": "X", "manufacturer": "Intel", "total_cores": 4}])["groups"]
    assert groups[0]["l2_cache_kb"] is None and groups[0]["l3_cache_kb"] is None


# ── 02-memory-004: RankCount 없으면 HPE OEM Label ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mdata, expected", [
    ({"RankCount": 2, "Oem": {"Hpe": {"Label": "32GB 1Rx4 PC5-6400B-RC1"}}}, 2),      # DMTF 값이 먼저
    ({"Oem": {"Hpe": {"Label": "32GB 1Rx4 PC5-6400B-RC1"}}}, 1),                      # RMC 실측
    ({"Oem": {"Hpe": {"Label": "64GB 2Rx4 PC5-5600B-R"}}}, 2),
    ({"Oem": {"Hpe": {"Label": "32GB RDIMM"}}}, None),
    ({"Oem": {"Lenovo": {"Label": "32GB 1Rx4"}}}, None),                               # HPE 네임스페이스만
    ({}, None), ({"RankCount": "x"}, None),
])
def test_memory_rank_count_fallback(mdata, expected):
    assert rg._memory_rank_count(mdata) == expected


def test_csus_dimms_get_rank_from_label_and_others_unchanged():
    res, _ = _replay("real_hpe_csus3200_01")
    slots = res["data"]["memory"]["slots"]
    assert len(slots) == 32 and all(s["rank_count"] == 1 for s in slots)
    assert all(s["rank_count"] == 1 for s in res["multi_node"]["partitions"][0]["memory"]["slots"])
    res2, _ = _replay("real_lenovo_sr650_v4_01")
    assert all(isinstance(s["rank_count"], int) for s in res2["data"]["memory"]["slots"]), "RankCount 보유 벤더는 종전 값"


# ── 01-hardware-004 ≡ 04-bios-001: FirmwareInventory ReleaseDate → bios_date ──────────────────────────────────────────

@pytest.mark.parametrize("name, expected, filled_from_fw", [
    ("real_lenovo_sr650_v4_01", "2026-05-11", True), ("real_lenovo_sr650_v4_03", "2026-06-22", True), ("real_lenovo_sr650", "2025-03-15", True),
    ("real_dell_r740", "2026-01-28", False),            # OEM BIOSReleaseDate 그대로(FirmwareInventory 날짜와 같다 — 교차 확인)
    ("real_hpe_dl380_gen12_01", "2026-06-26", False),   # OEM Bios.Current.Date 그대로(System ROM ReleaseDate 는 0000 자리표시자)
    ("real_hpe_csus3200_01", None, False),              # 구조 근거 없음 → null 유지
])
def test_bios_date_fallback_only_when_oem_has_none(name, expected, filled_from_fw):
    res, notices = _replay(name)
    assert res["data"]["system"]["bios_date"] == expected
    assert any("BIOS 날짜를 FirmwareInventory" in m for m in notices) is filled_from_fw


def test_bios_date_placeholder_year_zero_is_not_used():
    def strip_oem(rec):
        for k, v in rec.items():
            if k == "get::Systems/1" and isinstance(v, list):
                v[1].get("Oem", {}).get("Hpe", {}).pop("Bios", None)
    res, notices = _replay("real_hpe_dl380_gen12_01", mutate=strip_oem)
    assert res["data"]["system"]["bios_date"] is None and not any("BIOS 날짜를" in m for m in notices)
