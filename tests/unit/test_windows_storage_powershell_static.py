"""Windows storage — gather_storage.yml 의 PowerShell 블록 정적 검사 + 실제 실행 (2026-10-03, C3/C4).

정적 검사 (모든 플랫폼)
  - `-is [int]` 형 검사가 남아 있지 않다. CIM 이 주는 UInt16 을 놓쳐 숫자 경로가 죽어 있던 원인이다.
  - BusType 숫자 표가 MSFT_PhysicalDisk ValueMap 0..19 를 **전부 명시**하고 (대응 없는 값은 $null),
    대응값이 field_dictionary 의 닫힌 protocol enum 안에 있다.
  - MediaType / HealthStatus 숫자 표가 ValueMap 과 같다.
  - HBA 템플릿에 첫 어댑터 fallback 이 없다.

실제 실행 (powershell.exe 가 있을 때만)
  win_shell 스크립트 원문 앞에 cmdlet 을 같은 이름의 함수로 가려(Get-PhysicalDisk 등) 실행하고
  출력 JSON 을 검사한다. 같은 디스크를 UInt16 / Int32 / 숫자 문자열 / 표시 문자열 네 형태로 넣는다.
  출력은 다시 gather_storage.yml 의 실제 Jinja 체인으로 렌더해 envelope 조각까지 확인한다.

값의 근거 — CIM 스키마 ValueMap (root/Microsoft/Windows/Storage, 이 저장소 개발 호스트에서
ManagementClass + UseAmendedQualifiers 로 조회, 2026-10-03) 및 Storage 모듈 Storage.types.ps1xml
(Get-PhysicalDisk 가 붙이는 표시 문자열 — BusType 4 는 "1394", 16 은 "Spaces").
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")

REPO = Path(__file__).resolve().parents[2]
STOR_YML = REPO / "os-gather" / "tasks" / "windows" / "gather_storage.yml"
FIELD_DICT = REPO / "schema" / "field_dictionary.yml"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_windows_storage_enum_render import (  # noqa: E402
    UNMAPPED_MSG,
    _evidence_120,
    run_storage,
)

DISK_TASK = "windows | storage | physical disks"
HBA_TASK = "windows | storage | initiator ports + HBA attrs"

PROTOCOL_ENUM = yaml.safe_load(FIELD_DICT.read_text(encoding="utf-8"))["fields"][
    "storage.physical_disks[].protocol"]["enum"]

# MSFT_PhysicalDisk.BusType ValueMap → 닫힌 protocol enum (대응 없는 값은 None)
BUS_TYPE_EXPECTED = {
    0: None,            # Unknown
    1: "SCSI",
    2: None,            # ATAPI
    3: None,            # ATA
    4: "1394",
    5: None,            # SSA
    6: "FibreChannel",  # Fibre Channel
    7: "USB",
    8: "RAID",
    9: "iSCSI",
    10: "SAS",
    11: "SATA",
    12: "SD",
    13: "MMC",
    14: None,           # Virtual
    15: None,           # File Backed Virtual
    16: None,           # Storage Spaces
    17: "NVMe",
    18: None,           # SCM
    19: None,           # UFS
}
# Storage.types.ps1xml 이 Get-PhysicalDisk 에 붙이는 BusType 표시 문자열
BUS_TYPE_DISPLAY = {
    0: "Unknown", 1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "1394", 5: "SSA", 6: "Fibre Channel",
    7: "USB", 8: "RAID", 9: "iSCSI", 10: "SAS", 11: "SATA", 12: "SD", 13: "MMC", 14: "Virtual",
    15: "File Backed Virtual", 16: "Spaces", 17: "NVMe", 18: "SCM", 19: "UFS",
}
MEDIA_EXPECTED = {0: None, 3: "HDD", 4: "SSD", 5: "SCM"}            # 0 Unspecified
MEDIA_DISPLAY = {0: "Unspecified", 3: "HDD", 4: "SSD", 5: "SCM"}
HEALTH_EXPECTED = {0: "OK", 1: "Warning", 2: "Critical", 5: None}   # 5 Unknown
HEALTH_DISPLAY = {0: "Healthy", 1: "Warning", 2: "Unhealthy", 5: "Unknown"}
UIF_DISPLAY = {0: "Vendor Specific", 1: "Vendor Id", 2: "EUI64", 3: "FCPH Name", 8: "SCSI Name String"}
UIF_WWN = {2, 3, 8}                                                 # EUI64 / FCPH Name / SCSI Name String


def _win_shell(task_name: str) -> str:
    for t in yaml.safe_load(STOR_YML.read_text(encoding="utf-8")):
        if isinstance(t, dict) and t.get("name") == task_name:
            return t["ansible.windows.win_shell"]
    raise AssertionError(f"win_shell 태스크 {task_name!r} 미발견")


def _function_body(script: str, name: str) -> str:
    """`function <name>(...) {` 부터 짝이 맞는 `}` 직전까지."""
    m = re.search(r"function\s+" + re.escape(name) + r"\b[^{]*\{", script)
    assert m, f"PowerShell 함수 {name} 미발견"
    depth, i = 1, m.end()
    while depth and i < len(script):
        depth += {"{": 1, "}": -1}.get(script[i], 0)
        i += 1
    return script[m.end():i - 1]


_CODE_ARM = re.compile(r"^\s*(\d+)\s*\{\s*(\$null|'([^']*)')\s*\}", re.M)
_NAME_ARM = re.compile(r"^\s*'([^']+)'\s*\{\s*'([^']*)'\s*\}", re.M)


def _code_table(body: str) -> dict[int, str | None]:
    return {int(m.group(1)): (None if m.group(2) == "$null" else m.group(3))
            for m in _CODE_ARM.finditer(body)}


# ═══════════════════════════════════════════════════════════════════════════
# 정적 검사
# ═══════════════════════════════════════════════════════════════════════════
def _code_lines(text: str) -> str:
    """주석 줄(YAML / PowerShell `#`) 을 뺀 본문 — 변경 이력 설명이 가드를 건드리지 않게."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_no_int_type_check_left():
    """`-is [int]` 는 UInt16 (CIM 원값) 을 거른다 — 숫자 경로가 실제로는 한 번도 타지 않았다."""
    assert "-is [int]" not in _code_lines(STOR_YML.read_text(encoding="utf-8"))


def test_bus_type_switch_lists_every_code_explicitly():
    table = _code_table(_function_body(_win_shell(DISK_TASK), "Get-DiskBusProtocol"))
    missing = [c for c in range(1, 20) if c not in table]
    assert not missing, f"BusType 표에 빠진 코드: {missing} (대응 없는 값도 $null 로 명시)"
    assert table == BUS_TYPE_EXPECTED
    assert {v for v in table.values() if v} <= set(PROTOCOL_ENUM)


def test_bus_type_name_table_maps_into_closed_enum():
    names = dict(_NAME_ARM.findall(_function_body(_win_shell(DISK_TASK), "Get-DiskBusProtocol")))
    assert set(names.values()) <= set(PROTOCOL_ENUM)
    for name, code in ((BUS_TYPE_DISPLAY[c], c) for c in BUS_TYPE_EXPECTED):
        if BUS_TYPE_EXPECTED[code]:
            assert names.get(name) == BUS_TYPE_EXPECTED[code], f"표시 문자열 {name!r} 미매핑"
        else:
            assert name not in names, f"enum 대응이 없는 {name!r} 를 매핑했다"
    assert names["FibreChannel"] == "FibreChannel"


def test_media_type_and_health_tables_follow_valuemap():
    script = _win_shell(DISK_TASK)
    assert _code_table(_function_body(script, "Get-DiskMediaType")) == MEDIA_EXPECTED
    assert _code_table(_function_body(script, "Get-DiskHealth")) == HEALTH_EXPECTED


def test_every_enum_read_goes_through_typed_helpers():
    script = _win_shell(DISK_TASK)
    for call in ("Get-DiskBusProtocol $", "Get-DiskMediaType $", "Get-DiskHealth $",
                 "Get-UidFormatCode $"):
        assert call in script, f"{call.strip()} 를 거치지 않는 enum 읽기가 있다"


def test_hba_template_has_no_first_adapter_fallback():
    code = _code_lines(STOR_YML.read_text(encoding="utf-8"))
    assert "adapters[0]" not in code and "adp_first" not in code


# ═══════════════════════════════════════════════════════════════════════════
# 실제 실행 — powershell.exe (Windows PowerShell 5.1: win_shell 기본 실행기)
# ═══════════════════════════════════════════════════════════════════════════
POWERSHELL = shutil.which("powershell.exe")
needs_powershell = pytest.mark.skipif(
    POWERSHELL is None,
    reason="powershell.exe 없음 — PowerShell 실행 검증은 Windows 호스트에서만 돈다 "
           "(표 내용은 위 정적 검사가 모든 플랫폼에서 확인한다)")


def _ps(v) -> str:
    """Python 값 → PowerShell 리터럴. ('uint16', 11) 같은 tuple 은 형 캐스트."""
    if v is None:
        return "$null"
    if isinstance(v, tuple):
        return f"[{v[0]}]{v[1]}"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _run_powershell(script: str, tmp_dir: Path, name: str) -> list[str]:
    path = tmp_dir / f"{name}.ps1"
    path.write_text(script, encoding="utf-8-sig")      # BOM — PS 5.1 이 UTF-8 로 읽게
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path)],
        capture_output=True, timeout=180, check=False)
    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 0, f"powershell 실패 rc={proc.returncode}\n{err}"
    assert not err.strip(), f"powershell stderr:\n{err}"
    return [line for line in out.splitlines() if line.strip()]


_DISK_PRELUDE = r"""
function Get-PhysicalDisk { $script:__pd }
function Get-Partition {
  [CmdletBinding()] param([string]$DriveLetter)
  [PSCustomObject]@{ DiskNumber = 0 }
}
function Get-CimInstance {
  [CmdletBinding()] param([Parameter(Position=0)][string]$ClassName, [string]$Namespace, [string]$Filter)
  if ($ClassName -eq 'Win32_DiskDrive') { return $script:__dd }
  throw "unexpected Get-CimInstance $ClassName"
}
"""


def _disk_script(disks: list[dict]) -> str:
    """Get-PhysicalDisk / Win32_DiskDrive 를 가린 뒤 실제 win_shell 원문을 붙인다.

    Win32_DiskDrive 열거 순서는 `dd_order` (없으면 index) 순 — 실장비처럼 1 → 0 순서도 재현한다.
    """
    pd = [f"[PSCustomObject]@{{ DeviceId='{d['index']}'; BusType={_ps(d.get('bus'))}; "
          f"MediaType={_ps(d.get('media'))}; HealthStatus={_ps(d.get('health'))}; "
          f"SerialNumber={_ps(d.get('pd_serial'))}; UniqueId={_ps(d.get('uid'))}; "
          f"UniqueIdFormat={_ps(d.get('uif'))} }}"
          for d in disks]
    dd = [f"[PSCustomObject]@{{ Index=[uint32]{d['index']}; DeviceID='\\\\.\\PHYSICALDRIVE{d['index']}'; "
          f"Model={_ps(d.get('model', 'TEST DISK'))}; Size=[uint64]{d.get('size', 1000204886016)}; "
          f"MediaType={_ps(d.get('dd_media', 'Fixed hard disk media'))}; "
          f"InterfaceType={_ps(d.get('iface', ''))}; SerialNumber={_ps(d.get('dd_serial'))} }}"
          for d in sorted(disks, key=lambda d: d.get("dd_order", d["index"]))]
    return (_DISK_PRELUDE
            + "$script:__pd = @(\n  " + ",\n  ".join(pd) + "\n)\n"
            + "$script:__dd = @(\n  " + ",\n  ".join(dd) + "\n)\n"
            + _win_shell(DISK_TASK))


def _case_disks(form: str) -> list[dict]:
    """BusType 0..19 각 1개 + InterfaceType 보조 판정 2개. MediaType / HealthStatus / UniqueIdFormat 순환."""
    media_codes, health_codes, uif_codes = list(MEDIA_EXPECTED), list(HEALTH_EXPECTED), list(UIF_DISPLAY)

    def val(code, display):
        if form == "uint16":
            return ("uint16", code)
        if form == "int32":
            return ("int", code)
        if form == "numeric_string":
            return str(code)
        return display[code]                       # display_string

    disks = []
    for i in range(20):
        m, h, u = media_codes[i % 4], health_codes[i % 4], uif_codes[i % 5]
        disks.append({"index": i, "bus": val(i, BUS_TYPE_DISPLAY), "media": val(m, MEDIA_DISPLAY),
                      "health": val(h, HEALTH_DISPLAY), "uif": val(u, UIF_DISPLAY), "uid": f"UID{i}",
                      "iface": "",
                      "expect": {"protocol": BUS_TYPE_EXPECTED[i], "media": MEDIA_EXPECTED[m],
                                 "health": HEALTH_EXPECTED[h],
                                 "wwn": f"UID{i}" if u in UIF_WWN else None,
                                 "bus_type_raw": None if BUS_TYPE_EXPECTED[i] else
                                 (BUS_TYPE_DISPLAY[i] if form == "display_string" else i)}})
    # BusType 3(ATA) 은 enum 대응이 없지만 Win32_DiskDrive.InterfaceType 'IDE' 보조 판정은 종전대로 남는다
    disks.append({"index": 20, "bus": val(3, BUS_TYPE_DISPLAY), "media": val(3, MEDIA_DISPLAY),
                  "health": val(0, HEALTH_DISPLAY), "iface": "IDE",
                  "expect": {"protocol": "IDE", "media": "HDD", "health": "OK", "wwn": None,
                             "bus_type_raw": "ATA" if form == "display_string" else 3}})
    # BusType 11(SATA) — 종전 표는 11→SCSI 였고 UInt16 이면 숫자 경로를 못 타 InterfaceType 'SCSI' 로 떨어졌다
    disks.append({"index": 21, "bus": val(11, BUS_TYPE_DISPLAY), "media": val(4, MEDIA_DISPLAY),
                  "health": val(0, HEALTH_DISPLAY), "iface": "SCSI",
                  "expect": {"protocol": "SATA", "media": "SSD", "health": "OK", "wwn": None,
                             "bus_type_raw": None}})
    return disks


_FORMS = ("uint16", "int32", "numeric_string", "display_string")


@pytest.fixture(scope="module")
def disk_runs(tmp_path_factory):
    if POWERSHELL is None:
        pytest.skip("powershell.exe 없음")
    tmp = tmp_path_factory.mktemp("win_storage_ps")
    runs = {}
    for form in _FORMS:
        disks = _case_disks(form)
        lines = _run_powershell(_disk_script(disks), tmp, form)
        runs[form] = (disks, [json.loads(line) for line in lines])
    return runs


@needs_powershell
@pytest.mark.parametrize("form", _FORMS)
def test_powershell_normalizes_every_input_form(disk_runs, form):
    disks, printed = disk_runs[form]
    by_device = {p["device"]: p for p in printed}
    assert len(printed) == len(disks)
    for d in disks:
        got = by_device[f"\\\\.\\PHYSICALDRIVE{d['index']}"]
        exp = d["expect"]
        assert got["protocol"] == exp["protocol"], (form, d["index"], got)
        assert got["media"] == exp["media"], (form, d["index"], got)
        assert got["health"] == exp["health"], (form, d["index"], got)
        assert got["wwn"] == exp["wwn"], (form, d["index"], got)
        assert got.get("bus_type_raw") == exp["bus_type_raw"], (form, d["index"], got)


@needs_powershell
@pytest.mark.parametrize("form", _FORMS)
def test_powershell_output_renders_to_one_unmapped_error(disk_runs, form):
    """PowerShell 출력 → 실제 Jinja 체인. 미분류 디스크는 protocol=null, 오류는 1건뿐."""
    disks, printed = disk_runs[form]
    out = run_storage(printed)
    protocols = {d["device"]: d["protocol"] for d in out["storage"]["physical_disks"]}
    for d in disks:
        assert protocols[f"\\\\.\\PHYSICALDRIVE{d['index']}"] == d["expect"]["protocol"]
    assert len(out["errors"]) == 1, out["errors"]
    err = out["errors"][0]
    assert err["section"] == "storage" and err["message"] == UNMAPPED_MSG
    # 대응 없는 코드가 디스크 순서대로 한 번씩. index 20 (ATA + InterfaceType 'IDE') 은 protocol 이
    # 채워졌으므로 근거에 들어가지 않는다 — 3 은 index 3 (InterfaceType 없음) 몫이다.
    raw = [BUS_TYPE_DISPLAY[c] if form == "display_string" else c
           for c in sorted(BUS_TYPE_EXPECTED) if BUS_TYPE_EXPECTED[c] is None]
    assert f"bus_type_raw=[{','.join(str(r) for r in raw)}]" in err["detail"], err["detail"]
    assert out["collected"] == ["storage"] and out["failed"] == []


@needs_powershell
def test_powershell_real_host_120_inputs_render_identically(tmp_path):
    """build192 (10.100.64.120) 과 같은 Get-PhysicalDisk 표시 문자열 입력 → 실장비 출력과 동일."""
    total = 102398 * 1048576 + 524288
    disks = [
        {"index": 0, "bus": "SAS", "media": "HDD", "health": "Healthy", "uif": "FCPH Name",
         "uid": "6000C291A8A27597A22732589449427C", "pd_serial": "6000c291a8a27597a22732589449427c",
         "model": "VMware Virtual disk SCSI Disk Device", "size": total, "iface": "SCSI", "dd_order": 1},
        {"index": 1, "bus": "SAS", "media": "HDD", "health": "Healthy", "uif": "FCPH Name",
         "uid": "6000C295C31A6C4817CC54EDFA38C1B6", "pd_serial": "6000c295c31a6c4817cc54edfa38c1b6",
         "model": "VMware Virtual disk SCSI Disk Device", "size": total, "iface": "SCSI", "dd_order": 0},
    ]
    printed = [json.loads(line) for line in _run_powershell(_disk_script(disks), tmp_path, "host120")]
    out = run_storage(printed)
    ev = _evidence_120()
    assert out["storage"]["physical_disks"] == ev["physical_disks"]
    assert out["storage"]["summary"] == ev["summary"]
    assert out["errors"] == []


_HBA_SCRIPT_PRELUDE = r"""
function Get-InitiatorPort { $script:__ports }
function Get-CimInstance {
  [CmdletBinding()] param([Parameter(Position=0)][string]$ClassName, [string]$Namespace, [string]$Filter)
  if ($ClassName -eq 'MSFC_FCAdapterHBAAttributes') { return $script:__adapters }
  if ($ClassName -eq 'MSFC_FibrePortHBAAttributes') { return $script:__pattrs }
  throw "unexpected Get-CimInstance $ClassName"
}
$script:__ports = @(
  [PSCustomObject]@{ NodeAddress='20000024FF010203'; PortAddress='21000024FF010203'; ConnectionType=[uint16]1; OperationalStatus=[uint16[]]@(2) },
  [PSCustomObject]@{ NodeAddress='20000024FF999999'; PortAddress='21000024FF999999'; ConnectionType='Fibre Channel'; OperationalStatus=[string[]]@('Link Down') },
  [PSCustomObject]@{ NodeAddress='iqn.1991-05.com.microsoft:host01'; PortAddress='ISCSI ANY PORT'; ConnectionType=[uint16]2; OperationalStatus=[uint16[]]@(2) },
  [PSCustomObject]@{ NodeAddress='5000000000000001'; PortAddress='5000000000000002'; ConnectionType=[uint16]3; OperationalStatus=[uint16[]]@(2) },
  [PSCustomObject]@{ NodeAddress='20000024FF0A0B0C'; PortAddress='21000024FF0A0B0C'; ConnectionType=[int]1; OperationalStatus=[uint16[]]@(6,7) }
)
$script:__adapters = @(
  [PSCustomObject]@{ NodeWWN=[byte[]](0x20,0x00,0x00,0x24,0xFF,0x01,0x02,0x03); Manufacturer='Acme'; Model='FC-A'; DriverName='acmefc.sys'; FirmwareVersion='9.1' }
)
$script:__pattrs = @(
  [PSCustomObject]@{ Attributes = [PSCustomObject]@{ PortSpeed=[uint32]32; PortWWN=[byte[]](0x21,0x00,0x00,0x24,0xFF,0x01,0x02,0x03); NodeWWN=[byte[]](0x20,0x00,0x00,0x24,0xFF,0x01,0x02,0x03); PortState=[uint32]2 } }
)
"""


@needs_powershell
def test_powershell_initiator_ports_render_without_adapter_leak(tmp_path):
    """숫자 ConnectionType(1/2) 포트가 살아남고, 매칭 안 된 포트는 다른 HBA 의 모델을 받지 않는다."""
    lines = _run_powershell(_HBA_SCRIPT_PRELUDE + _win_shell(HBA_TASK), tmp_path, "hba")
    assert len(lines) == 1, lines
    out = run_storage([{"device": "\\\\.\\PHYSICALDRIVE0", "model": "M", "serial": None, "wwn": None,
                        "total": 1000204886016, "media": "SSD", "protocol": "SAS", "health": "OK",
                        "is_os_disk": True, "bus_type_raw": None}],
                      hba=json.loads(lines[0]))
    got = {(h["port_type"], h["wwpn"]): h for h in out["storage"]["hbas"]}
    assert set(got) == {("FibreChannel", "21:00:00:24:ff:01:02:03"),
                        ("FibreChannel", "21:00:00:24:ff:99:99:99"),
                        ("iSCSI", None),
                        ("FibreChannel", "21:00:00:24:ff:0a:0b:0c")}, "SAS initiator 는 빠지고 나머지는 남는다"
    matched = got[("FibreChannel", "21:00:00:24:ff:01:02:03")]
    assert (matched["model"], matched["vendor"], matched["driver"], matched["firmware"]) == \
        ("FC-A", "Acme", "acmefc.sys", "9.1")
    assert matched["link_status"] == "up" and matched["link_speed_gbps"] == 16
    assert matched["connection"] == "Fibre Channel"
    for key in (("FibreChannel", "21:00:00:24:ff:99:99:99"), ("iSCSI", None),
                ("FibreChannel", "21:00:00:24:ff:0a:0b:0c")):
        h = got[key]
        assert (h["model"], h["vendor"], h["driver"], h["firmware"]) == (None, None, None, None), h
    assert got[("FibreChannel", "21:00:00:24:ff:99:99:99")]["link_status"] == "down"
    assert got[("FibreChannel", "21:00:00:24:ff:0a:0b:0c")]["link_status"] == "down"
    assert got[("iSCSI", None)]["connection"] == "iSCSI"
