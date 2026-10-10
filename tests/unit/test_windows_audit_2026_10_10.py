"""2026-10-10 감사 — Windows 채널 결함 고정 (plan §4.6). 운영 스크립트를 가짜 cmdlet 위에서 실제 powershell.exe 로 돌린다.

WIN-02    fec0:0:0:ffff::1~3 은 이름 서버가 아니다 — Windows IPv6 스택이 넣어 두는 site-local 자리표시자다.
WIN-11/12 IPv6 주소의 기본 경로 귀속은 ::/0 경로의 인터페이스다. 종전에는 IPv4 기본 경로 인터페이스(def4)로 판정해
          IPv4·IPv6 기본 경로가 다른 NIC 에 있으면 IPv6 게이트웨이가 엉뚱한 주소에 붙었다.
WIN-DM    driver_map 은 모든 어댑터다(Disconnected 포함) — Linux 와 같다. 종전에는 Up/Connected 만 담았다.
D-02      hosting_type: HypervisorPresent=True + Hyper-V 역할 없음이라도 VBS(Device Guard) 가 Running(2) 이면 baremetal
          (VBS 를 켠 물리 Windows 는 HypervisorPresent 가 True 다). VBS 꺼짐 · 조회 실패는 종전 규칙(virtual).
D-03      방화벽 프로필은 ActiveStore(GPO 적용 뒤 유효 정책)를 읽는다.
WIN-13    hardware: CIM 호출마다 격리 — 하나가 실패해도 섹션은 나머지로 만들어지고 errors[] 1건이 남는다.
WIN-21    cpu: 일부 소켓에 NumberOfCores/NumberOfLogicalProcessors 가 없으면 cores/logical 은 null + errors[] 1건 — 부분합을
          전체처럼 내지 않는다.
D-08      디스크 크기는 MSFT_PhysicalDisk.Size 우선, 없을 때만 Win32_DiskDrive.Size(기하값 계산 — 실제보다 작다).

powershell.exe 가 없는 플랫폼에서는 실행 시험을 건너뛴다(정적 계약은 어디서나 본다).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("yaml")
pytest.importorskip("jinja2")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_windows_call_consolidation_powershell as PS  # noqa: E402
from test_windows_call_consolidation_render import MERGED_TASK, new_text, run_chain  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
WIN = REPO / "os-gather" / "tasks" / "windows"
needs_powershell = pytest.mark.skipif(PS.POWERSHELL is None, reason="powershell.exe 가 필요하다(Windows 호스트)")


def _section(section, fixture, facts=None):
    shell = PS.PsShell(section, fixture)
    frag, ctx = run_chain(new_text(section), dict(facts or {}), shell)
    doc = json.loads([ln for ln in shell.results[MERGED_TASK[section]]["stdout_lines"] if ln.strip()][0])
    return frag, ctx, doc, shell


class _CimShell:
    """합치지 않은 단일 스크립트(hardware · cpu)용 — Get-CimInstance 가짜 cmdlet 만 올린다."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.results = {}

    def __call__(self, task_name, script):
        hit = PS.run_encoded(PS._HEADER + PS._SHADOWS["Get-CimInstance"] + "\n" + PS.compact(script), self.fixture)
        self.results[task_name] = hit
        return {k: hit[k] for k in ("stdout", "stdout_lines", "rc")}


def _single(section, fixture, facts=None):
    shell = _CimShell(fixture)
    frag, ctx = run_chain(new_text(section), dict(facts or {}), shell)
    res = next(iter(shell.results.values()))
    assert res["rc"] == 0, res["stderr"][-1500:]
    return frag, ctx, json.loads(res["stdout"].strip())


# ═══════════════════════════════════════════════════════════════════════════
# 정적 계약 (모든 플랫폼)
# ═══════════════════════════════════════════════════════════════════════════
def test_static_contracts():
    net = (WIN / "gather_network.yml").read_text(encoding="utf-8")
    assert "Where-Object { $_ -notmatch '^fec0:0:0:ffff::[1-3]$' }" in net, "WIN-02: fec0 자리표시자 필터"
    assert "$primary_idx6 = $def6.InterfaceIndex" in net and "$pidx    = if ($fam -eq 'ipv6') { $primary_idx6 } else { $primary_idx }" in net, "WIN-11/12"
    assert "$na | Where-Object { $_.Status -eq 'Up' -or $_.MediaConnectionState -eq 'Connected' } | ForEach-Object {" not in net, "WIN-DM: 상태로 거르지 않는다"
    rt = (WIN / "gather_runtime.yml").read_text(encoding="utf-8")
    assert "Get-NetFirewallProfile -PolicyStore ActiveStore" in rt, "D-03"
    sysd = (WIN / "gather_system.yml").read_text(encoding="utf-8")
    assert "Win32_DeviceGuard" in sysd and "{{ 'baremetal' if vbs == '2' else 'virtual' }}" in sysd, "D-02"
    hw = (WIN / "gather_hardware.yml").read_text(encoding="utf-8")
    for cls in ("Win32_ComputerSystem", "Win32_ComputerSystemProduct", "Win32_BIOS", "Win32_SystemEnclosure"):
        assert f"Get-CimInstance {cls} -ErrorAction SilentlyContinue -ErrorVariable" in hw, f"WIN-13: {cls} 격리"
    cpu = (WIN / "gather_cpu.yml").read_text(encoding="utf-8")
    assert "counts_incomplete" in cpu and "$coreMissing -eq 0 -and" in cpu and "$logMissing -eq 0 -and" in cpu, "WIN-21"
    st = (WIN / "gather_storage.yml").read_text(encoding="utf-8")
    assert "total  = $(if ($pdSize) { [uint64]$pdSize } else { $_.Size })" in st, "D-08"


# ═══════════════════════════════════════════════════════════════════════════
# WIN-02 · WIN-11/12 · WIN-DM — network
# ═══════════════════════════════════════════════════════════════════════════
@needs_powershell
def test_dns_drops_ipv6_site_local_placeholders_and_keeps_real_servers():
    fx = copy.deepcopy(PS.NET_TEAM)
    fx["dns"] = [{"InterfaceAlias": "Ethernet0", "ServerAddresses": ["10.0.0.53", "fec0:0:0:ffff::1", "fec0:0:0:ffff::2",
                                                                      "fec0:0:0:ffff::3", "2001:4860:4860::8888"]},
                 {"InterfaceAlias": "Team1", "ServerAddresses": ["fec0:0:0:ffff::1"]}]
    frag, _ctx, doc, _shell = _section("network", fx)
    assert doc["meta"]["data"]["dns"] == ["10.0.0.53", "2001:4860:4860::8888"]
    assert frag["_data_fragment"]["network"]["dns_servers"] == ["10.0.0.53", "2001:4860:4860::8888"]


def _addr(frag, iface, family):
    i = next(x for x in frag["_data_fragment"]["network"]["interfaces"] if x["name"] == iface)
    return next(a for a in (i.get("addresses") or []) if a["family"] == family)


@needs_powershell
def test_ipv6_gateway_is_attributed_to_the_ipv6_default_route_interface():
    fx = copy.deepcopy(PS.NET_TEAM)
    # IPv4 기본 경로 = Ethernet0(idx 4), IPv6 기본 경로 = Team1(idx 11) — 서로 다른 NIC
    fx["routes"] = [{"DestinationPrefix": "0.0.0.0/0", "NextHop": "10.0.0.1", "RouteMetric": 0, "InterfaceIndex": 4},
                    {"DestinationPrefix": "::/0", "NextHop": "fe80::1", "RouteMetric": 256, "InterfaceIndex": 11}]
    fx["addresses"] = [PS._ip("10.0.0.15", 4, "Ethernet0", "IPv4", 24), PS._ip("2001:db8::15", 4, "Ethernet0", "IPv6", 64),
                       PS._ip("172.16.5.10", 11, "Team1", "IPv4", 22), PS._ip("2001:db8:1::10", 11, "Team1", "IPv6", 64)]
    frag, _ctx, doc, _shell = _section("network", fx)
    assert doc["meta"]["data"]["gw"] == "10.0.0.1" and doc["meta"]["data"]["gw6"] == "fe80::1"
    assert _addr(frag, "Ethernet0", "ipv4")["gateway"] == "10.0.0.1"
    assert not _addr(frag, "Ethernet0", "ipv6")["gateway"], "IPv6 게이트웨이가 IPv4 기본 경로 NIC 에 붙었다 (WIN-11/12)"
    assert _addr(frag, "Team1", "ipv6")["gateway"] == "fe80::1"
    assert not _addr(frag, "Team1", "ipv4")["gateway"]
    assert sorted((g["family"], g["address"]) for g in frag["_data_fragment"]["network"]["default_gateways"]) == \
        [("ipv4", "10.0.0.1"), ("ipv6", "fe80::1")]


@needs_powershell
def test_without_ipv6_default_route_no_ipv6_address_claims_a_gateway():
    fx = copy.deepcopy(PS.NET_TEAM)
    fx["routes"] = [{"DestinationPrefix": "0.0.0.0/0", "NextHop": "10.0.0.1", "RouteMetric": 0, "InterfaceIndex": 4}]
    fx["addresses"] = [PS._ip("10.0.0.15", 4, "Ethernet0", "IPv4", 24), PS._ip("2001:db8::15", 4, "Ethernet0", "IPv6", 64)]
    frag, _ctx, _doc, _shell = _section("network", fx)
    assert _addr(frag, "Ethernet0", "ipv4")["gateway"] == "10.0.0.1"
    assert not _addr(frag, "Ethernet0", "ipv6")["gateway"]


@needs_powershell
def test_driver_map_covers_disconnected_adapters_too():
    frag, _ctx, doc, _shell = _section("network", copy.deepcopy(PS.NET_TEAM))
    names = [r["name"] for r in doc["driver_map"]["rows"]]
    assert names == ["Ethernet0", "Ethernet1", "Ethernet2", "Ethernet3", "Team1"], names   # Ethernet3 = Disconnected, Teredo = hidden
    e3 = next(r for r in frag["_data_fragment"]["network"]["driver_map"] if r["name"] == "Ethernet3")
    assert e3["driver"] == "Intel(R) Ethernet 25G #3" and e3["driver_version"] == "1.2.3.4"


# ═══════════════════════════════════════════════════════════════════════════
# D-02 — hosting_type (VBS)
# ═══════════════════════════════════════════════════════════════════════════
def _sys_fixture(vbs_status=None, *, vbs_fail=False, vmms=None):
    fx = copy.deepcopy(PS.SYS_NORMAL)
    fx["cim"]["Win32_ComputerSystem"].update({"Model": "PowerEdge R740", "Manufacturer": "Dell Inc.", "HypervisorPresent": True})
    if vbs_status is not None:
        fx["cim"]["Win32_DeviceGuard"] = {"VirtualizationBasedSecurityStatus": vbs_status}
    if vbs_fail:
        fx.setdefault("fail", {})["Win32_DeviceGuard"] = "Win32_DeviceGuard: Invalid namespace (fixture)"
    if vmms is not None:
        fx["services"] = {"vmms": {"Status": vmms}}
    return fx


def _hosting_type(frag):
    return frag["_data_fragment"]["system"]["hosting_type"]


@needs_powershell
@pytest.mark.parametrize("vbs_status,vbs_fail,expected", [
    (2, False, "baremetal"),     # VBS Running → 물리 Windows (하이퍼바이저는 VBS 의 것)
    (0, False, "virtual"),       # VBS 꺼짐 → 종전 규칙
    (1, False, "virtual"),       # Enabled but not running → 근거 부족, 종전 규칙
    (None, False, "virtual"),    # 클래스 없음(Win32_DeviceGuard 미지원 OS)
    (None, True, "virtual"),     # 조회 실패 → 판정에 쓰지 않는다
])
def test_hosting_type_uses_vbs_only_to_rescue_physical_hosts(vbs_status, vbs_fail, expected):
    frag, ctx, doc, _shell = _section("system", _sys_fixture(vbs_status, vbs_fail=vbs_fail), PS._SYS_FACTS)
    assert doc["hosting"]["ok"] and doc["hosting"]["data"]["HypervisorPresent"] == "True"
    assert doc["hosting"]["data"]["VbsStatus"] == ("" if vbs_status is None else str(vbs_status))
    assert _hosting_type(frag) == expected


@needs_powershell
def test_hyperv_host_stays_baremetal_regardless_of_vbs():
    frag, _ctx, _doc, _shell = _section("system", _sys_fixture(0, vmms="Running"), PS._SYS_FACTS)
    assert _hosting_type(frag) == "baremetal"


# ═══════════════════════════════════════════════════════════════════════════
# D-03 — firewall ActiveStore
# ═══════════════════════════════════════════════════════════════════════════
@needs_powershell
def test_firewall_profiles_are_read_from_the_active_policy_store():
    frag, _ctx, doc, shell = _section("runtime", copy.deepcopy(PS.RT_NORMAL))
    calls = shell.results[MERGED_TASK["runtime"]]["calls"]
    assert calls.count("Get-NetFirewallProfile -PolicyStore ActiveStore") == 1 and "Get-NetFirewallProfile" not in calls
    assert doc["firewall"]["ok"] and len(doc["firewall"]["rows"]) == 3
    assert frag["_data_fragment"]["system"]["runtime"]["firewall_state"] == "active"


# ═══════════════════════════════════════════════════════════════════════════
# WIN-13 — hardware CIM 격리
# ═══════════════════════════════════════════════════════════════════════════
_HW_CIM = {"Win32_ComputerSystem": {"Manufacturer": "Dell Inc.", "Model": "PowerEdge R740", "SystemSKUNumber": "SKU=0715",
                                    "UUID": None, "PowerState": 0, "TotalPhysicalMemory": 274877906944},
           "Win32_ComputerSystemProduct": {"UUID": "4C4C4544-0051-3610-8052-B9C04F4A3732", "IdentifyingNumber": "ABC1234"},
           "Win32_BIOS": {"Manufacturer": "Dell Inc.", "SMBIOSBIOSVersion": "2.19.1", "SerialNumber": "ABC1234",
                          "ReleaseDate": "20231101000000.000000+000"},
           "Win32_SystemEnclosure": {"SMBIOSAssetTag": "No Asset Tag", "ChassisTypes": [23]}}
_HW_PARTIAL_MESSAGE = "하드웨어 정보 중 일부를 수집하지 못했습니다. 수집 계정의 권한을 확인하세요."


@needs_powershell
def test_hardware_all_calls_ok_has_no_errors():
    frag, _ctx, doc = _single("hardware", {"cim": copy.deepcopy(_HW_CIM)})
    assert doc["cim_errors"] == [] and doc["bios_version"] == "2.19.1" and doc["vendor"] == "Dell Inc."
    assert frag["_errors_fragment"] == [] and frag["_sections_collected_fragment"] == ["hardware"]


@needs_powershell
@pytest.mark.parametrize("mode", ["soft_fail", "fail"])   # 비종료 오류(실제 CIM 공급자 방식) · 종료 오류
def test_hardware_one_failed_cim_call_keeps_the_section_and_records_one_error(mode):
    cim = copy.deepcopy(_HW_CIM)
    del cim["Win32_BIOS"]
    frag, _ctx, doc = _single("hardware", {"cim": cim, mode: {"Win32_BIOS": "Win32_BIOS: Access denied (fixture)"}})
    assert doc["vendor"] == "Dell Inc." and doc["model"] == "PowerEdge R740" and doc["chassis_type"] == "Rack Mount Chassis"
    assert doc["bios_version"] is None and doc["bios_vendor"] is None
    assert len(doc["cim_errors"]) == 1 and doc["cim_errors"][0].startswith("Win32_BIOS: ")
    assert "Access denied (fixture)" in doc["cim_errors"][0], doc["cim_errors"]
    hw = frag["_data_fragment"]["hardware"]
    assert hw["vendor"] == "Dell Inc." and hw["bios_version"] is None
    assert frag["_sections_collected_fragment"] == ["hardware"] and frag["_sections_failed_fragment"] == []
    assert len(frag["_errors_fragment"]) == 1
    err = frag["_errors_fragment"][0]
    assert err["section"] == "hardware" and err["message"] == _HW_PARTIAL_MESSAGE
    assert err["detail"].startswith("source=cim; cause=call_failed; Win32_BIOS: ") and "Access denied (fixture)" in err["detail"]


@needs_powershell
def test_hardware_every_cim_call_failed_is_the_existing_section_failure_only():
    fails = {k: f"{k}: RPC server unavailable (fixture)" for k in _HW_CIM}
    frag, _ctx, doc = _single("hardware", {"cim": {}, "soft_fail": fails})
    assert len(doc["cim_errors"]) == 4
    assert frag["_sections_failed_fragment"] == ["hardware"] and frag["_sections_collected_fragment"] == []
    assert len(frag["_errors_fragment"]) == 1 and "cause=no_output" in frag["_errors_fragment"][0]["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# WIN-21 — cpu 부분합 금지
# ═══════════════════════════════════════════════════════════════════════════
def _proc(socket, cores=24, logical=48):
    p = {"Name": "Intel(R) Xeon(R) Gold 6248R CPU @ 3.00GHz", "Manufacturer": "GenuineIntel", "MaxClockSpeed": 3000,
         "L2CacheSize": 24576, "L3CacheSize": 36608, "SocketDesignation": socket}
    if cores is not None:
        p["NumberOfCores"] = cores
    if logical is not None:
        p["NumberOfLogicalProcessors"] = logical
    return p


@needs_powershell
def test_cpu_complete_counts_are_summed():
    frag, _ctx, doc = _single("cpu", {"cim": {"Win32_Processor": [_proc("CPU1"), _proc("CPU2")]}})
    assert (doc["sockets"], doc["cores"], doc["logical"], doc["counts_incomplete"]) == (2, 48, 96, False)
    cpu = frag["_data_fragment"]["cpu"]
    assert (cpu["sockets"], cpu["cores_physical"], cpu["logical_threads"]) == (2, 48, 96) and frag["_errors_fragment"] == []


@needs_powershell
def test_cpu_missing_count_on_one_socket_gives_null_total_and_one_error():
    frag, _ctx, doc = _single("cpu", {"cim": {"Win32_Processor": [_proc("CPU1"), _proc("CPU2", cores=None, logical=None)]}})
    assert doc["sockets"] == 2 and doc["cores"] is None and doc["logical"] is None and doc["counts_incomplete"] is True
    cpu = frag["_data_fragment"]["cpu"]
    assert cpu["sockets"] == 2 and cpu["cores_physical"] is None and cpu["logical_threads"] is None
    assert cpu["model"] == "Intel(R) Xeon(R) Gold 6248R CPU @ 3.00GHz"
    assert frag["_sections_collected_fragment"] == ["cpu"]
    assert len(frag["_errors_fragment"]) == 1
    err = frag["_errors_fragment"][0]
    assert err["section"] == "cpu" and err["message"] == "CPU 정보 중 일부를 수집하지 못했습니다. 대상 상태와 수집 로그를 확인하세요."
    assert "NumberOfCores_or_NumberOfLogicalProcessors_missing_on_some_sockets" in err["detail"]


@needs_powershell
def test_cpu_only_logical_missing_keeps_cores():
    frag, _ctx, doc = _single("cpu", {"cim": {"Win32_Processor": [_proc("CPU1"), _proc("CPU2", logical=None)]}})
    assert doc["cores"] == 48 and doc["logical"] is None and doc["counts_incomplete"] is True
    assert frag["_data_fragment"]["cpu"]["cores_physical"] == 48 and len(frag["_errors_fragment"]) == 1


# ═══════════════════════════════════════════════════════════════════════════
# D-08 — 디스크 크기 출처
# ═══════════════════════════════════════════════════════════════════════════
_MIB = 1048576


@needs_powershell
def test_disk_total_prefers_physical_disk_size_over_geometry_size():
    fx = copy.deepcopy(PS.STOR_SINGLE)
    fx["pdisks"][0]["Size"] = 1000204886016                       # MSFT_PhysicalDisk.Size (실제)
    fx["cim"]["Win32_DiskDrive"][0]["Size"] = 1000202273280        # Win32_DiskDrive.Size (기하값 — 작다)
    frag, _ctx, doc, _shell = _section("storage", fx)
    assert doc["disks"]["rows"][0]["total"] == 1000204886016
    assert frag["_data_fragment"]["storage"]["physical_disks"][0]["total_mb"] == 1000204886016 // _MIB


@needs_powershell
def test_disk_total_falls_back_to_win32_diskdrive_when_physical_disk_has_no_size():
    fx = copy.deepcopy(PS.STOR_SINGLE)
    fx["cim"]["Win32_DiskDrive"][0]["Size"] = 1000202273280
    frag, _ctx, doc, _shell = _section("storage", fx)
    assert "Size" not in fx["pdisks"][0]
    assert doc["disks"]["rows"][0]["total"] == 1000202273280
    assert frag["_data_fragment"]["storage"]["physical_disks"][0]["total_mb"] == 1000202273280 // _MIB
