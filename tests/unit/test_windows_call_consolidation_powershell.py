"""P4 (2026-10-03) — Windows 원격 호출 통합: 합친 스크립트를 powershell.exe 로 실제로 돌린다.

무엇을 보나
-----------
1. 합친 스크립트 5 개가 stdout 에 JSON 문서 **한 줄** 만 내고, 문서의 항목마다 { ok, error, rows, data } 가
   있다. 원소 1개짜리 목록(DNS 서버 1개 · 슬롯 1개 · 포트 1개 · 디스크 1개 ...) 도 배열로 남는다.
2. 구성요소 실패 격리: cmdlet 하나가 종료 오류를 내면 그 구성요소만 ok=false + error 이고 나머지는 채워진다
   (예: Get-NetFirewallProfile → firewall 만 실패). 스크립트 rc 는 0, 출력은 여전히 문서 한 줄.
3. 같은 입력 → 같은 fragment: 같은 가짜 cmdlet 위에서 **종전 스크립트**(git PRE_P4_SHA) 와 **새 스크립트** 를
   각각 돌려 그 출력으로 종전 / 새 Jinja 체인을 렌더하고, 다섯 fragment 와 중간 변수가 같은지 본다.
4. 공용 조회 횟수: 새 스크립트는 Win32_ComputerSystem · Win32_PhysicalMemory · Get-NetRoute · Get-NetIPAddress ·
   Get-NetAdapter(전체) 를 한 번씩만 부르고, 주소마다 Get-NetAdapter -InterfaceIndex 를 부르지 않는다.

어떻게 돌리나
-------------
win_shell 과 똑같이 `powershell.exe -noninteractive -encodedcommand <UTF-16LE base64>` 로 실행한다.
종전 rc 의미(마지막 문장의 종료 오류 = rc 1) 는 -File 이나 스크립트블록 실행에서는 재현되지 않는다
(-File 은 0). 명령줄 한도(32,767 자) 안에 들어가도록 가짜 cmdlet 정의 + 스크립트에서 **주석 줄과 줄 앞 공백만**
뺀다 (PowerShell 토큰은 그대로). cmdlet 은 같은 이름의 함수로 가린다 — 함수가 cmdlet 보다 먼저 찾아진다.
가짜 cmdlet 의 실패는 실제 cmdlet 처럼 $PSCmdlet.ThrowTerminatingError (문장 종료 오류) 로 낸다.

powershell.exe 가 없으면 (Linux CI 등) 이 파일 전체를 건너뛴다. 종전 스크립트 비교는 git 이력이 있어야 돈다.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_windows_call_consolidation_render import (  # noqa: E402
    FRAGMENT_KEYS,
    MERGED_TASK,
    PRE_P4_SHA,
    _evidence,
    iter_tasks,
    new_text,
    old_text,
    run_chain,
    shared_facts,
)

def _usable_powershell():
    """powershell.exe 가 PATH 에 보여도 실행이 안 되는 환경(Windows interop 이 막힌 WSL · Linux Runner)에서는 None → 실행 테스트 skip (2026-10-03)."""
    exe = shutil.which("powershell.exe")
    if not exe:
        return None
    try:
        probe = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-Command", "exit 0"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return exe if probe.returncode == 0 else None


POWERSHELL = _usable_powershell()
pytestmark = pytest.mark.skipif(
    POWERSHELL is None,
    reason="powershell.exe 없음 — 합친 스크립트 실행 검증은 Windows 호스트에서만 돈다 "
           "(렌더 동일성은 test_windows_call_consolidation_render.py 가 모든 플랫폼에서 본다)")

_WIN_SHELL_PREFIX = "[Console]::InputEncoding = New-Object Text.UTF8Encoding `$false; "
_CMDLINE_LIMIT = 32767

# 문서 항목 (실행 순서) — read_* 는 공용 조회
DOC_KEYS = {
    "memory": ["read_physical_memory", "total", "slots"],
    "system": ["read_operating_system", "read_computer_system", "os", "hosting"],
    "network": ["read_routes", "read_adapters", "read_dns", "meta", "interfaces", "driver_map", "adapters"],
    "runtime": ["ntp", "firewall", "ports", "pagefile"],
    "storage": ["volumes", "read_disk_drives", "disks"],
}

# ═══════════════════════════════════════════════════════════════════════════
# 가짜 cmdlet (섹션별로 필요한 것만 — 명령줄 길이 때문)
# ═══════════════════════════════════════════════════════════════════════════
_HEADER = r"""
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$script:__fx = @'
__FIXTURE__
'@ | ConvertFrom-Json
function __Track([string]$n) { [Console]::Error.WriteLine('SE_CALL ' + $n + ' SE_END') }
function __Err([string]$m) { New-Object System.Management.Automation.ErrorRecord ((New-Object System.Exception $m)), 'Fixture', 'NotSpecified', $null }
"""

_SHADOWS = {
    "Get-CimInstance": r"""
function Get-CimInstance {
[CmdletBinding()] param([Parameter(Position=0)][string]$ClassName, [string]$Namespace, [string]$Filter)
__Track ('Get-CimInstance ' + $ClassName)
$m = $script:__fx.fail.$ClassName; if ($m) { $PSCmdlet.ThrowTerminatingError((__Err $m)) }
$v = $script:__fx.cim.$ClassName; if ($null -ne $v) { $v }
}""",
    "Get-ItemProperty": r"""
function Get-ItemProperty {
[CmdletBinding()] param([Parameter(Position=0)][string[]]$Path)
__Track 'Get-ItemProperty'
foreach ($p in $Path) { $v = $script:__fx.registry.$p; if ($null -ne $v) { $v } else { Write-Error "Cannot find path '$p' (fixture)" } }
}""",
    "Get-Service": r"""
function Get-Service {
[CmdletBinding()] param([Parameter(Position=0)][string[]]$Name)
__Track ('Get-Service ' + $Name)
foreach ($n in $Name) { $v = $script:__fx.services.$n; if ($null -ne $v) { $v } else { Write-Error "Cannot find any service with service name '$n' (fixture)" } }
}""",
    "Get-Date": r"""
function Get-Date { [datetime]$script:__fx.now }""",
    "Get-NetRoute": r"""
function Get-NetRoute {
[CmdletBinding()] param([string[]]$DestinationPrefix)
__Track 'Get-NetRoute'
$m = $script:__fx.fail.'Get-NetRoute'; if ($m) { $PSCmdlet.ThrowTerminatingError((__Err $m)) }
foreach ($p in @($DestinationPrefix)) { if (-not @(@($script:__fx.routes) | Where-Object { $_.DestinationPrefix -eq $p }).Count) { Write-Error "no route $p (fixture)" } }
@($script:__fx.routes) | Where-Object { @($DestinationPrefix) -contains $_.DestinationPrefix }
}""",
    "Get-NetAdapter": r"""
function Get-NetAdapter {
[CmdletBinding()] param([Parameter(Position=0)][string[]]$Name, [uint32[]]$InterfaceIndex, [switch]$Physical, [switch]$IncludeHidden)
$k = 'Get-NetAdapter'; if ($Physical) { $k += ' -Physical' }; if ($IncludeHidden) { $k += ' -IncludeHidden' }
$byIdx = $PSBoundParameters.ContainsKey('InterfaceIndex')
__Track ($k + $(if ($byIdx) { ' -InterfaceIndex' } else { '' }))
$m = $script:__fx.fail.$k; if ($m) { $PSCmdlet.ThrowTerminatingError((__Err $m)) }
$r = @(@($script:__fx.adapters) | Where-Object { $IncludeHidden -or -not $_.Hidden })
if ($Physical) { $r = @($r | Where-Object { $_.ConnectorPresent }) }
if ($byIdx) { $r = @($r | Where-Object { @($InterfaceIndex) -contains [uint32]$_.InterfaceIndex }); if (-not $r.Count) { Write-Error "no adapter $InterfaceIndex (fixture)" } }
$r
}""",
    "Get-NetIPAddress": r"""
function Get-NetIPAddress {
[CmdletBinding()] param([string[]]$AddressFamily)
__Track 'Get-NetIPAddress'
$m = $script:__fx.fail.'Get-NetIPAddress'; if ($m) { $PSCmdlet.ThrowTerminatingError((__Err $m)) }
@($script:__fx.addresses) | Where-Object { -not $AddressFamily -or (@($AddressFamily) -contains $_.AddressFamily) }
}""",
    "Get-DnsClientServerAddress": r"""
function Get-DnsClientServerAddress {
[CmdletBinding()] param([string[]]$AddressFamily)
__Track 'Get-DnsClientServerAddress'
$script:__fx.dns
}""",
    "Get-NetAdapterHardwareInfo": r"""
function Get-NetAdapterHardwareInfo { [CmdletBinding()] param() __Track 'Get-NetAdapterHardwareInfo'; $script:__fx.hwinfo }""",
    "Get-PnpDevice": r"""
function Get-PnpDevice {
[CmdletBinding()] param([string]$InstanceId, [string]$Class)
__Track 'Get-PnpDevice'
if ($InstanceId) { @($script:__fx.pnp) | Where-Object { $_.InstanceId -eq $InstanceId } }
}""",
    "Teaming": r"""
function Get-NetLbfoTeam { [CmdletBinding()] param() $script:__fx.lbfo_teams }
function Get-NetLbfoTeamMember { [CmdletBinding()] param() $script:__fx.lbfo_members }
function Get-NetLbfoTeamNic { [CmdletBinding()] param() $script:__fx.lbfo_teamnics }
function Get-NetSwitchTeam { [CmdletBinding()] param() }
function Get-NetSwitchTeamMember { [CmdletBinding()] param() }""",
    "Get-TimeZone": r"""
function Get-TimeZone { [CmdletBinding()] param() __Track 'Get-TimeZone'; [PSCustomObject]@{ Id = $script:__fx.timezone } }""",
    "w32tm": r"""
function w32tm { __Track 'w32tm'; $global:LASTEXITCODE = 0; if ($args -contains '/source') { $script:__fx.w32tm_source } else { $script:__fx.w32tm_status } }""",
    "Get-NetFirewallProfile": r"""
function Get-NetFirewallProfile {
[CmdletBinding()] param()
__Track 'Get-NetFirewallProfile'
$m = $script:__fx.fail.'Get-NetFirewallProfile'; if ($m) { $PSCmdlet.ThrowTerminatingError((__Err $m)) }
$script:__fx.firewall
}""",
    "Get-NetTCPConnection": r"""
function Get-NetTCPConnection {
[CmdletBinding()] param([string]$State)
__Track 'Get-NetTCPConnection'
@($script:__fx.tcp) | Where-Object { -not $State -or $_.State -eq $State }
}""",
    "Storage": r"""
function Get-Volume { [CmdletBinding()] param() __Track 'Get-Volume'; $script:__fx.volumes }
function Get-PhysicalDisk { [CmdletBinding()] param() __Track 'Get-PhysicalDisk'; $script:__fx.pdisks }
function Get-Partition { [CmdletBinding()] param([string]$DriveLetter) [PSCustomObject]@{ DiskNumber = $script:__fx.os_disk_number } }
function Get-InitiatorPort { [CmdletBinding()] param() }
function Get-NetAdapterRdma { [CmdletBinding()] param([string]$Name) }""",
}
SECTION_SHADOWS = {
    "memory": ["Get-CimInstance"],
    "system": ["Get-CimInstance", "Get-ItemProperty", "Get-Service", "Get-Date"],
    "network": ["Get-NetRoute", "Get-NetAdapter", "Get-NetIPAddress", "Get-DnsClientServerAddress",
                "Get-NetAdapterHardwareInfo", "Get-PnpDevice", "Teaming"],
    "runtime": ["Get-TimeZone", "Get-Service", "w32tm", "Get-NetFirewallProfile", "Get-NetTCPConnection",
                "Get-CimInstance"],
    "storage": ["Storage", "Get-CimInstance", "Get-NetAdapter", "Get-PnpDevice"],
}


def prelude(section: str, fixture: dict) -> str:
    text = _HEADER.replace("__FIXTURE__", json.dumps(fixture, separators=(",", ":")))
    return text + "".join(_SHADOWS[s] for s in SECTION_SHADOWS[section]) + "\n"


def compact(script: str) -> str:
    """주석 줄 · 줄 앞 공백 제거 (PowerShell 토큰은 그대로 — here-string 이 없는 스크립트에만 쓴다)."""
    return "\n".join(ln.strip() for ln in script.splitlines() if ln.strip() and not ln.strip().startswith("#"))


def run_encoded(script: str) -> dict:
    """ansible.windows.win_shell 과 같은 호출. 반환 = win_shell register 모양 + stderr / 호출 목록."""
    command = _WIN_SHELL_PREFIX + script.strip()
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    assert len(encoded) + 80 < _CMDLINE_LIMIT, f"테스트 명령줄이 한도를 넘는다 ({len(encoded)})"
    proc = subprocess.run([POWERSHELL, "-noprofile", "-noninteractive", "-encodedcommand", encoded],
                          capture_output=True, timeout=240, check=False)
    out = proc.stdout.decode("utf-8", errors="replace").lstrip("\ufeff")
    err = proc.stderr.decode("utf-8", errors="replace")
    return {"stdout": out, "stdout_lines": out.splitlines(), "rc": proc.returncode, "stderr": err,
            "calls": re.findall(r"SE_CALL (.+?) SE_END", err)}


class PsShell:
    """run_chain 용 shell — 같은 (가짜 cmdlet, 스크립트) 는 한 번만 돌린다 (팀 · HBA · IB 처럼 바뀌지 않은 것)."""

    _cache: dict[tuple[str, str], dict] = {}
    _lock = threading.Lock()

    def __init__(self, section: str, fixture: dict):
        self.prelude = prelude(section, fixture)
        self.results: dict[str, dict] = {}

    def __call__(self, task_name: str, script: str) -> dict:
        key = (self.prelude, script)
        with self._lock:
            hit = self._cache.get(key)
        if hit is None:
            hit = run_encoded(self.prelude + compact(script))
            with self._lock:
                self._cache[key] = hit
        self.results[task_name] = hit
        return {k: hit[k] for k in ("stdout", "stdout_lines", "rc")}


# ═══════════════════════════════════════════════════════════════════════════
# 가짜 cmdlet 값 (fixture)
# ═══════════════════════════════════════════════════════════════════════════
def _dimm(loc, cap_gb, smt, configured, speed, mfr, pn, serial):
    return {"DeviceLocator": loc, "Capacity": cap_gb * 1073741824, "SMBIOSMemoryType": smt, "MemoryType": 0,
            "ConfiguredClockSpeed": configured, "Speed": speed, "Manufacturer": mfr, "PartNumber": pn,
            "SerialNumber": serial}


MEM_NORMAL = {"cim": {"Win32_PhysicalMemory": [
    _dimm("DIMM_A1", 32, 26, 2933, 3200, "Samsung", "M393A4K40DB3-CWE", "1234ABCD"),
    _dimm("DIMM_A2", 32, 26, 0, 3200, "00CE00B300000000", "M393A4K40DB3-CWE", "00000000"),
    _dimm("RAM slot #0", 8, 3, None, None, "VMware Virtual RAM", "VMW-8192MB", "00000001"),
]}}
MEM_SINGLE = {"cim": {"Win32_PhysicalMemory": [_dimm("RAM slot #0", 8, 3, None, None, "VMware Virtual RAM",
                                                     "VMW-8192MB", None)]}}
MEM_FAIL = {"cim": {}, "fail": {"Win32_PhysicalMemory": "Win32_PhysicalMemory provider failure (fixture)"}}

_CURVER = "HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion"
_TCPIP = "HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters"
SYS_NORMAL = {
    "cim": {"Win32_OperatingSystem": {"Caption": "Microsoft Windows Server 2022 Standard", "Version": "10.0.20348",
                                      "BuildNumber": "20348", "OSArchitecture": "64-bit",
                                      "LastBootUpTime": "2026-09-30T00:00:00"},
            "Win32_ComputerSystem": {"DNSHostName": "WIN-TP7D9J9QKCB", "PartOfDomain": False, "Domain": "WORKGROUP",
                                     "Model": "VMware7,1", "Manufacturer": "VMware, Inc.", "HypervisorPresent": True}},
    "registry": {_CURVER: {"DisplayVersion": "21H2", "ReleaseId": "2009"}, _TCPIP: {"Domain": "", "NV Domain": ""}},
    "services": {}, "now": "2026-10-01T00:00:00",
}
SYS_DOMAIN_HV = {
    "cim": {"Win32_OperatingSystem": {"Caption": "Microsoft Windows Server 2019 Datacenter", "Version": "10.0.17763",
                                      "BuildNumber": "17763", "OSArchitecture": "64-bit",
                                      "LastBootUpTime": "2026-09-01T12:00:00"},
            "Win32_ComputerSystem": {"DNSHostName": "HV01", "PartOfDomain": True, "Domain": "corp.example.com",
                                     "Model": "Rack Server X", "Manufacturer": "Contoso Inc",
                                     "HypervisorPresent": True}},
    "registry": {_CURVER: {"ReleaseId": "1809"}, _TCPIP: {"Domain": "", "NV Domain": "lab.local"}},
    "services": {"vmms": {"Status": "Running"}}, "now": "2026-10-01T00:00:00",
}
SYS_FAIL = dict(SYS_NORMAL, fail={"Win32_OperatingSystem": "Win32_OperatingSystem: Invalid class (fixture)"})


def _nic(name, idx, desc, mac, mtu, gbps, *, status="Up", physical=True, provider="Intel", vlan=None, pnp=None,
         hidden=False):
    """MSFT_NetAdapter 흉내. 값이 없는 속성은 아예 넣지 않는다 — PowerShell 에서 없는 속성은 $null 로 읽혀
    명시적 null 과 같고, 명령줄 길이(32,767 자) 를 아낀다."""
    nic = {"Name": name, "InterfaceIndex": idx, "InterfaceDescription": desc, "MacAddress": mac, "MtuSize": mtu,
           "Speed": gbps * 1000000000, "Status": status, "DriverDescription": desc, "DriverVersion": "1.2.3.4",
           "DriverProvider": provider, "VlanID": vlan, "PnPDeviceID": pnp, "ConnectorPresent": physical,
           "Hidden": hidden}
    return {k: v for k, v in nic.items() if v not in (None, False)}


def _ip(addr, idx, alias, family, prefix):
    return {"IPAddress": addr, "InterfaceIndex": idx, "InterfaceAlias": alias, "AddressFamily": family,
            "PrefixLength": prefix}


NET_TEAM = {
    "adapters": [
        _nic("Ethernet0", 4, "Intel(R) Ethernet 10G 2P X710", "A0-36-9F-00-00-01", 1500, 10,
             pnp="PCI\\VEN_8086&DEV_1572\\0"),
        _nic("Ethernet1", 5, "Intel(R) Ethernet 25G", "A0-36-9F-00-00-02", 1500, 25, pnp="PCI\\VEN_8086&DEV_158B\\1"),
        _nic("Ethernet2", 6, "Intel(R) Ethernet 25G #2", "A0-36-9F-00-00-03", 1500, 25),
        _nic("Ethernet3", 7, "Intel(R) Ethernet 25G #3", "A0-36-9F-00-00-04", 1500, 25, status="Disconnected"),
        _nic("Team1", 11, "Microsoft Network Adapter Multiplexor Driver", "A0-36-9F-00-00-02", 9000, 50,
             physical=False, provider="Microsoft"),
        _nic("Teredo Tunneling Pseudo-Interface", 14, "Teredo", None, 1280, 0, physical=False, hidden=True),
    ],
    "addresses": [
        _ip("10.0.0.15", 4, "Ethernet0", "IPv4", 24), _ip("172.16.5.10", 11, "Team1", "IPv4", 22),
        _ip("169.254.10.1", 7, "Ethernet3", "IPv4", 16), _ip("127.0.0.1", 1, "Loopback Pseudo-Interface 1", "IPv4", 8),
        _ip("10.99.0.1", 33, "vEthernet (internal)", "IPv4", 32),
        _ip("2001:db8::15", 4, "Ethernet0", "IPv6", 64), _ip("fe80::1234:5678:9abc:def0%11", 11, "Team1", "IPv6", 64),
        _ip("::1", 1, "Loopback Pseudo-Interface 1", "IPv6", 128),
    ],
    "routes": [
        {"DestinationPrefix": "0.0.0.0/0", "NextHop": "172.16.4.1", "RouteMetric": 256, "InterfaceIndex": 11},
        {"DestinationPrefix": "::/0", "NextHop": "fe80::1", "RouteMetric": 256, "InterfaceIndex": 4},
        {"DestinationPrefix": "0.0.0.0/0", "NextHop": "10.0.0.1", "RouteMetric": 0, "InterfaceIndex": 4},
    ],
    "dns": [{"InterfaceAlias": "Ethernet0", "ServerAddresses": ["10.0.0.53"]},
            {"InterfaceAlias": "Team1", "ServerAddresses": ["10.0.0.53"]},
            {"InterfaceAlias": "Ethernet3", "ServerAddresses": []}],
    "hwinfo": [{"Name": "Ethernet0", "Segment": 0, "Bus": 59, "Device": 0, "Function": 0},
               {"Name": "Ethernet1", "Segment": 0, "Bus": 94, "Device": 0, "Function": 1}],
    "pnp": [{"InstanceId": "PCI\\VEN_8086&DEV_1572\\0", "Manufacturer": "Intel Corporation"}],
    "lbfo_teams": [{"Name": "Team1", "TeamingMode": "Lacp", "LoadBalancingAlgorithm": "Dynamic", "LacpTimer": "Fast",
                    "Status": "Up", "Members": ["Ethernet1", "Ethernet2"]}],
    "lbfo_members": [{"Name": "Ethernet1", "Team": "Team1", "AdministrativeMode": "Active"},
                     {"Name": "Ethernet2", "Team": "Team1", "AdministrativeMode": "Standby"}],
    "lbfo_teamnics": [{"Name": "Team1", "Team": "Team1", "VlanID": None, "Default": True}],
}
NET_NO_TEAM = {
    "adapters": [_nic("Ethernet", 6, "Red Hat VirtIO Ethernet Adapter", "52-54-00-12-34-56", 1500, 1,
                      provider="Red Hat, Inc.")],
    "addresses": [_ip("192.168.122.20", 6, "Ethernet", "IPv4", 24)],
    "routes": [], "dns": [], "hwinfo": [], "pnp": [], "lbfo_teams": [], "lbfo_members": [], "lbfo_teamnics": [],
}
NET_FAIL = dict(NET_TEAM, fail={"Get-NetIPAddress": "Get-NetIPAddress: WMI provider failure (fixture)"})


def _profile(name, enabled=True):
    return {"Name": name, "Enabled": enabled, "DefaultInboundAction": "NotConfigured",
            "DefaultOutboundAction": "NotConfigured"}


RT_NORMAL = {
    "timezone": "Korea Standard Time", "services": {"W32Time": {"Status": "Running"}},
    "w32tm_source": ["time.windows.com,0x9"], "w32tm_status": ["Leap Indicator: 0(no warning)", "Stratum: 3"],
    "firewall": [_profile("Domain"), _profile("Private"), _profile("Public", False)],
    "tcp": [{"LocalPort": 445, "State": "Listen"}, {"LocalPort": 135, "State": "Listen"},
            {"LocalPort": 445, "State": "Listen"}, {"LocalPort": 5985, "State": "Listen"},
            {"LocalPort": 51000, "State": "Established"}],
    "cim": {"Win32_PageFileUsage": [{"Name": "C:\\pagefile.sys", "AllocatedBaseSize": 1280, "CurrentUsage": 527,
                                     "PeakUsage": 536}]},
}
RT_SINGLE = dict(RT_NORMAL, firewall=[_profile("Public")], tcp=[{"LocalPort": 5986, "State": "Listen"}])
RT_FAIL = dict(RT_NORMAL, fail={"Get-NetFirewallProfile": "Get-NetFirewallProfile: Access is denied. (fixture)"})

_GIB = 1048576


def _vol(letter, total_mb, free_mb, fs="NTFS"):
    return {"DriveLetter": letter, "FileSystemType": fs, "Size": total_mb * _GIB + 4096,
            "SizeRemaining": free_mb * _GIB + 1024}


_VMDK = "VMware Virtual disk SCSI Disk Device"
_VMDK_SIZE = 102398 * _GIB + 524288
STOR_120 = {
    "volumes": [_vol("C", 101683, 80129), _vol("E", 102382, 102287),
                {"DriveLetter": None, "FileSystemType": "NTFS", "Size": 529 * _GIB, "SizeRemaining": 80 * _GIB},
                _vol("F", 1000, 1000, "Unknown")],
    "pdisks": [
        {"DeviceId": "0", "BusType": "SAS", "MediaType": "HDD", "HealthStatus": "Healthy",
         "SerialNumber": "6000c291a8a27597a22732589449427c", "UniqueId": "6000C291A8A27597A22732589449427C",
         "UniqueIdFormat": "FCPH Name"},
        {"DeviceId": "1", "BusType": "SAS", "MediaType": "HDD", "HealthStatus": "Healthy",
         "SerialNumber": "6000c295c31a6c4817cc54edfa38c1b6", "UniqueId": "6000C295C31A6C4817CC54EDFA38C1B6",
         "UniqueIdFormat": "FCPH Name"}],
    "cim": {"Win32_DiskDrive": [
        {"Index": 1, "DeviceID": "\\\\.\\PHYSICALDRIVE1", "Model": _VMDK, "Size": _VMDK_SIZE,
         "MediaType": "Fixed hard disk media", "InterfaceType": "SCSI", "SerialNumber": "6000c295c31a6c4817cc54edfa38c1b6"},
        {"Index": 0, "DeviceID": "\\\\.\\PHYSICALDRIVE0", "Model": _VMDK, "Size": _VMDK_SIZE,
         "MediaType": "Fixed hard disk media", "InterfaceType": "SCSI", "SerialNumber": "6000c291a8a27597a22732589449427c"}]},
    "os_disk_number": 0, "adapters": [], "pnp": [],
}
STOR_SINGLE = {
    "volumes": [_vol("C", 475000, 120000)],
    "pdisks": [{"DeviceId": "0", "BusType": 17, "MediaType": 4, "HealthStatus": 0, "SerialNumber": "S5GXNF0R123456",
                "UniqueId": "eui.0025385A1234ABCD", "UniqueIdFormat": 2}],
    "cim": {"Win32_DiskDrive": [{"Index": 0, "DeviceID": "\\\\.\\PHYSICALDRIVE0", "Model": "Samsung SSD 980 PRO 1TB",
                                 "Size": 1000204886016, "MediaType": "Fixed hard disk media", "InterfaceType": "SCSI",
                                 "SerialNumber": "S5GXNF0R123456"}]},
    "os_disk_number": 0, "adapters": [], "pnp": [],
}
STOR_FAIL = dict(STOR_120, fail={"Win32_DiskDrive": "Win32_DiskDrive: RPC server is unavailable (fixture)"})

_SYS_FACTS = {"ansible_product_serial": "VMware-42 04 a2 40 1d 5c 63 c9-f6 0b 5f b4 72 98 d7 dd",
              "ansible_product_uuid": "40A20442-5C1D-C963-F60B-5FB47298D7DD", "ansible_uptime_seconds": 86400,
              "ansible_architecture2": "x86_64", "ansible_hostname": "WIN-TP7D9J9QKCB",
              "ansible_fqdn": "WIN-TP7D9J9QKCB", "ansible_os_name": "Microsoft Windows Server 2022 Standard",
              "ansible_distribution": "Microsoft Windows Server 2022 Standard"}

# (section, 이름) → (fixture, setup facts)
SCENARIOS = {
    ("memory", "normal"): (MEM_NORMAL, {"ansible_memtotal_mb": 73000, "ansible_memfree_mb": 1000}),
    ("memory", "single"): (MEM_SINGLE, {"ansible_memtotal_mb": 8192}),
    ("memory", "fail"): (MEM_FAIL, {"ansible_memtotal_mb": 4096}),
    ("system", "normal"): (SYS_NORMAL, _SYS_FACTS),
    ("system", "domain_hyperv_host"): (SYS_DOMAIN_HV, {"ansible_os_name": "Windows Server 2019"}),
    ("system", "fail"): (SYS_FAIL, {}),
    ("network", "two_nics_one_team"): (NET_TEAM, {}),
    ("network", "no_team"): (NET_NO_TEAM, {}),
    ("network", "fail"): (NET_FAIL, {}),
    ("runtime", "normal"): (RT_NORMAL, {}),
    ("runtime", "single"): (RT_SINGLE, {}),
    ("runtime", "fail"): (RT_FAIL, {}),
    ("storage", "host_120"): (STOR_120, {}),
    ("storage", "single"): (STOR_SINGLE, {}),
    ("storage", "fail"): (STOR_FAIL, {}),
}
FAILURES = {  # 실패 시나리오: 실패해야 하는 항목 → error 에 들어갈 fixture 문구
    "memory": {"read_physical_memory": "provider failure", "slots": "provider failure"},
    "system": {"read_operating_system": "Invalid class"},
    "network": {"interfaces": "WMI provider failure"},
    "runtime": {"firewall": "Access is denied"},
    "storage": {"read_disk_drives": "RPC server is unavailable"},
}


def _run(section, name, which):
    fixture, facts = SCENARIOS[(section, name)]
    text = new_text(section) if which == "new" else old_text(section)
    if text is None:
        return None
    shell = PsShell(section, fixture)
    frag, ctx = run_chain(text, dict(facts), shell)
    return {"frag": frag, "ctx": ctx, "facts": facts, "shell": shell}


@pytest.fixture(scope="module")
def runs():
    jobs = [(s, n, w) for (s, n) in SCENARIOS for w in ("new", "old")]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda j: _run(*j), jobs))
    return dict(zip(jobs, results))


def _doc(runs, section, name):
    res = runs[(section, name, "new")]["shell"].results[MERGED_TASK[section]]
    return res


# ═══════════════════════════════════════════════════════════════════════════
# 1. 문서 모양
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("section,name", list(SCENARIOS))
def test_merged_script_prints_one_json_document(runs, section, name):
    res = _doc(runs, section, name)
    assert res["rc"] == 0, res["stderr"][-2000:]
    lines = [ln for ln in res["stdout_lines"] if ln.strip()]
    assert len(lines) == 1, lines
    doc = json.loads(lines[0])
    assert list(doc) == DOC_KEYS[section]
    for key, item in doc.items():
        assert set(item) == {"ok", "error", "rows", "data"}, (key, item)
        assert isinstance(item["ok"], bool) and isinstance(item["rows"], list)
        assert (item["error"] is None) == item["ok"], (key, item)
    if name not in ("fail",):
        assert all(item["ok"] for item in doc.values()), doc


def test_single_element_collections_stay_arrays(runs):
    mem = json.loads(_doc(runs, "memory", "single")["stdout_lines"][0])
    assert isinstance(mem["slots"]["rows"], list) and len(mem["slots"]["rows"]) == 1
    net = json.loads(_doc(runs, "network", "two_nics_one_team")["stdout_lines"][0])
    assert net["meta"]["data"]["dns"] == ["10.0.0.53"]                 # 서버 1개도 배열
    no_team = json.loads(_doc(runs, "network", "no_team")["stdout_lines"][0])
    assert no_team["meta"]["data"]["dns"] == [] and len(no_team["interfaces"]["rows"]) == 1
    assert len(no_team["driver_map"]["rows"]) == 1 and len(no_team["adapters"]["rows"]) == 1
    rt = json.loads(_doc(runs, "runtime", "single")["stdout_lines"][0])
    assert rt["firewall"]["rows"] == [{"profile": "Public", "enabled": True, "default_inbound": "NotConfigured",
                                       "default_outbound": "NotConfigured"}]
    assert rt["ports"]["rows"] == [5986] and len(rt["pagefile"]["rows"]) == 1
    st = json.loads(_doc(runs, "storage", "single")["stdout_lines"][0])
    assert len(st["volumes"]["rows"]) == 1 and len(st["disks"]["rows"]) == 1
    assert st["disks"]["rows"][0]["protocol"] == "NVMe" and st["disks"]["rows"][0]["media"] == "SSD"


def test_null_and_missing_values_survive_as_json_null(runs):
    mem = json.loads(_doc(runs, "memory", "normal")["stdout_lines"][0])
    vm = next(r for r in mem["slots"]["rows"] if r["slot"] == "RAM slot #0")
    assert vm["speed_mhz"] is None and vm["serial"] is None and vm["type"] == "DRAM"   # 키는 남고 값만 null
    assert set(vm) == {"capacity_mb", "type", "speed_mhz", "slot", "manufacturer", "part_number", "serial"}
    sysd = json.loads(_doc(runs, "system", "normal")["stdout_lines"][0])
    assert sysd["os"]["data"]["domain"] is None and sysd["os"]["data"]["uptime"] == 86400


# ═══════════════════════════════════════════════════════════════════════════
# 2. 구성요소 실패 격리
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("section", list(FAILURES))
def test_component_failure_is_isolated(runs, section):
    res = _doc(runs, section, "fail")
    assert res["rc"] == 0, "구성요소 실패가 스크립트 전체를 멈췄다"
    doc = json.loads([ln for ln in res["stdout_lines"] if ln.strip()][0])
    expected = FAILURES[section]
    for key, item in doc.items():
        if key in expected:
            assert item["ok"] is False and expected[key] in item["error"], (key, item)
        else:
            assert item["ok"] is True and item["error"] is None, (key, item)


def test_failed_component_does_not_empty_its_neighbours(runs):
    net = json.loads(_doc(runs, "network", "fail")["stdout_lines"][0])
    assert net["interfaces"]["rows"] == []
    assert net["meta"]["data"]["gw"] == "10.0.0.1" and net["driver_map"]["rows"] and net["adapters"]["rows"]
    rt = json.loads(_doc(runs, "runtime", "fail")["stdout_lines"][0])
    assert rt["firewall"]["rows"] == [] and rt["ports"]["rows"] == [135, 445, 5985]
    assert rt["ntp"]["data"]["timezone"] == "Asia/Seoul" and rt["pagefile"]["rows"]
    frag = runs[("runtime", "fail", "new")]["frag"]
    assert frag["_errors_fragment"][0]["detail"] == "scope=firewall; os=windows; cause=command_failed"
    # 공용 조회가 실패해도 쓰는 구성요소는 종전처럼 빈 값으로 성공한다 (system: OS 정보 없이 호스트명 · 하이퍼바이저)
    sysd = json.loads(_doc(runs, "system", "fail")["stdout_lines"][0])
    assert sysd["os"]["ok"] and sysd["os"]["data"]["caption"] is None and sysd["os"]["data"]["hostname"] == "WIN-TP7D9J9QKCB"
    assert sysd["hosting"]["data"]["Manufacturer"] == "VMware, Inc."
    st = json.loads(_doc(runs, "storage", "fail")["stdout_lines"][0])
    assert len(st["volumes"]["rows"]) == 2 and st["disks"]["ok"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. 종전 스크립트 vs 새 스크립트 — 같은 가짜 cmdlet 위에서 fragment 동일
# ═══════════════════════════════════════════════════════════════════════════
# 2026-10-05 (§5 감사 C-6): 디스크 조회가 실패하고 볼륨만 읽힌 경우 새 체인은 errors[] 1건을 남긴다(종전 체인은 기록 없음 — 의도한 차이)
INTENDED_EXTRA_ERRORS_PS = {
    ("storage", "fail"): [{"section": "storage", "message": "스토리지 정보 중 물리 디스크 정보를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요.",
                          "detail": "source=Win32_DiskDrive,Get-PhysicalDisk; cause=component_failed; parts=read_disk_drives; disks=0"}],
}


@pytest.mark.parametrize("section,name", list(SCENARIOS))
def test_old_and_new_powershell_render_identical_fragments(runs, section, name):
    old = runs[(section, name, "old")]
    if old is None:
        pytest.skip(f"통합 직전 파일({PRE_P4_SHA[:8]}) 을 git 으로 읽을 수 없다")
    new = runs[(section, name, "new")]
    for key in FRAGMENT_KEYS:
        expected = old["frag"][key]
        if key == "_errors_fragment":
            expected = list(expected or []) + INTENDED_EXTRA_ERRORS_PS.get((section, name), [])
        assert new["frag"][key] == expected, f"{section}/{name}: {key} 가 종전과 다르다"
    shared = shared_facts(old["ctx"], new["ctx"], new["facts"])
    assert shared
    for key in shared:
        if key in FRAGMENT_KEYS:
            continue  # 위에서 (의도한 차이를 넣어) 비교했다
        assert new["ctx"][key] == old["ctx"][key], f"{section}/{name}: 중간 변수 {key} 가 종전과 다르다"


def test_old_scripts_really_ran_per_call(runs):
    """비교가 헛돌지 않게: 종전 체인은 호출을 따로따로 했고, 실패 시나리오에서 종전 rc 가 1 이었다."""
    old = runs[("network", "two_nics_one_team", "old")]
    if old is None:
        pytest.skip("git 이력 없음")
    assert len([t for t in iter_tasks(yaml.safe_load(old_text("network")))
                if "ansible.windows.win_shell" in t]) == len(old["shell"].results) == 5
    fw = runs[("runtime", "fail", "old")]["shell"].results["windows | runtime | firewall profiles"]
    assert fw["rc"] == 1 and fw["stdout"].strip() == ""                     # 마지막 문장의 종료 오류 → rc 1
    pf = runs[("memory", "fail", "old")]["shell"].results
    assert pf["windows | memory | Win32_PhysicalMemory total"]["rc"] == 0    # 중간 문장 → 다음 줄로
    assert pf["windows | memory | Win32_PhysicalMemory slots"]["rc"] == 1    # 마지막 문장 → rc 1


# ═══════════════════════════════════════════════════════════════════════════
# 4. 공용 조회 횟수
# ═══════════════════════════════════════════════════════════════════════════
def _calls(run, task):
    return run["shell"].results[task]["calls"]


def test_snapshot_reads_each_source_once(runs):
    calls = _calls(runs[("network", "two_nics_one_team", "new")], MERGED_TASK["network"])
    assert calls.count("Get-NetRoute") == 1
    assert calls.count("Get-NetIPAddress") == 1
    assert calls.count("Get-DnsClientServerAddress") == 1
    assert calls.count("Get-NetAdapter") == 1 and calls.count("Get-NetAdapter -Physical") == 1
    assert not [c for c in calls if "-InterfaceIndex" in c], calls
    old = runs[("network", "two_nics_one_team", "old")]
    if old is not None:
        old_calls = [c for r in old["shell"].results.values() for c in r["calls"]]
        assert old_calls.count("Get-NetRoute") == 3                       # meta 2 + interfaces 1
        assert old_calls.count("Get-NetAdapter -InterfaceIndex") == 5     # 걸러지지 않은 주소마다


def test_win32_computersystem_and_physical_memory_read_once(runs):
    sys_calls = _calls(runs[("system", "normal", "new")], MERGED_TASK["system"])
    assert sys_calls.count("Get-CimInstance Win32_ComputerSystem") == 1
    assert sys_calls.count("Get-CimInstance Win32_OperatingSystem") == 1
    mem_calls = _calls(runs[("memory", "normal", "new")], MERGED_TASK["memory"])
    assert mem_calls.count("Get-CimInstance Win32_PhysicalMemory") == 1
    assert not [c for c in mem_calls if "Win32_ComputerSystem" in c]


# ═══════════════════════════════════════════════════════════════════════════
# 5. 실제 실행 결과 → 실장비(10.100.64.120) 출력
# ═══════════════════════════════════════════════════════════════════════════
def test_storage_120_inputs_through_powershell_match_live_output(runs):
    frag = runs[("storage", "host_120", "new")]["frag"]
    got = frag["_data_fragment"]["storage"]
    ev = _evidence()["storage"]
    for key in ("physical_disks", "summary", "filesystems", "hbas", "infiniband"):
        assert got[key] == ev[key], f"storage.{key}"
    assert frag["_errors_fragment"] == [] and frag["_sections_collected_fragment"] == ["storage"]
