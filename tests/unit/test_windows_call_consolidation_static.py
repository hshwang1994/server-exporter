"""P4 (2026-10-03) — Windows 원격 호출 통합 정적 게이트.

호스트마다 도는 win_shell 은 정확히 11 개다 (+ win_ping + setup = WinRM 왕복 13 회, 종전 20 + 2 = 22 회).

    파일                    | 섹션      | win_shell (태스크 이름)
    ------------------------+-----------+------------------------------------------------------------------
    gather_cpu.yml          | cpu       | 1. windows | cpu | collect Win32_Processor 상세
    gather_hardware.yml     | hardware  | 2. windows | hardware | Win32_ComputerSystem + Win32_BIOS
    gather_memory.yml       | memory    | 3. windows | memory | Win32_PhysicalMemory (total + slots)
    gather_network.yml      | network   | 4. windows | network | snapshot (routes + adapters + addresses + dns)
    gather_network.yml      | network   | 5. windows | network | teaming (LBFO + SET)
    gather_runtime.yml      | system    | 6. windows | runtime | timezone + NTP + firewall + ports + pagefile
    gather_storage.yml      | storage   | 7. windows | storage | volumes + physical disks
    gather_storage.yml      | storage   | 8. windows | storage | initiator ports + HBA attrs
    gather_storage.yml      | storage   | 9. windows | storage | infiniband adapters (best-effort)
    gather_system.yml       | system    | 10. windows | system | os version + hosting detection
    gather_users.yml        | users     | 11. windows | users | collect

합친 스크립트 5 개(3 / 4 / 6 / 7 / 10) 는 JSON 문서 1개를 낸다. 구성요소마다 { ok, error, rows, data } 이고,
본문 종료 오류는 Invoke-SeComponent 의 try/catch 가 그 구성요소에만 남긴다. 값 동일성은
test_windows_call_consolidation_render.py (렌더) / _powershell.py (실행) 가 본다.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
WIN = REPO / "os-gather" / "tasks" / "windows"

EXPECTED_WIN_SHELL = {
    "gather_cpu.yml": ["windows | cpu | collect Win32_Processor 상세"],
    "gather_hardware.yml": ["windows | hardware | Win32_ComputerSystem + Win32_BIOS"],
    "gather_memory.yml": ["windows | memory | Win32_PhysicalMemory (total + slots)"],
    "gather_network.yml": ["windows | network | snapshot (routes + adapters + addresses + dns)",
                           "windows | network | teaming (LBFO + SET)"],
    "gather_runtime.yml": ["windows | runtime | timezone + NTP + firewall + ports + pagefile"],
    "gather_storage.yml": ["windows | storage | volumes + physical disks",
                           "windows | storage | initiator ports + HBA attrs",
                           "windows | storage | infiniband adapters (best-effort)"],
    "gather_system.yml": ["windows | system | os version + hosting detection"],
    "gather_users.yml": ["windows | users | collect"],
}
# 합친 스크립트 → 문서 항목 (실행 순서). read_* = 공용 조회 (실패를 자기 ok / error 에 남기고, 쓰는 구성요소는
# 종전 스크립트처럼 빈 값으로 계속 간다). 나머지 = 종전 호출 하나에 대응하는 구성요소 (split 태스크가 읽는다).
MERGED = {
    "gather_memory.yml": ("windows | memory | Win32_PhysicalMemory (total + slots)",
                          ["read_physical_memory", "total", "slots"]),
    "gather_system.yml": ("windows | system | os version + hosting detection",
                          ["read_operating_system", "read_computer_system", "os", "hosting"]),
    "gather_network.yml": ("windows | network | snapshot (routes + adapters + addresses + dns)",
                           ["read_routes", "read_adapters", "read_dns", "meta", "interfaces", "driver_map",
                            "adapters"]),
    "gather_runtime.yml": ("windows | runtime | timezone + NTP + firewall + ports + pagefile",
                           ["ntp", "firewall", "ports", "pagefile"]),
    "gather_storage.yml": ("windows | storage | volumes + physical disks",
                           ["volumes", "read_disk_drives", "disks"]),
}


def _components(file: str) -> list[str]:
    return [n for n in MERGED[file][1] if not n.startswith("read_")]
FRAGMENT_VARS = {"_data_fragment", "_sections_supported_fragment", "_sections_collected_fragment",
                 "_sections_failed_fragment", "_errors_fragment",
                 "_sections_unsupported_fragment"}   # users (cycle 2026-05-01, merge_fragment 가 받는다)
ACCUMULATED_VARS = {"_merged_data", "_all_sec_supported", "_all_sec_collected", "_all_sec_failed",
                    "_all_sec_unsupported", "_all_errors", "_collected_data", "_supported_sections",
                    "_collected_sections", "_failed_sections", "_collected_errors"}

# win_shell 은 스크립트를 `powershell.exe -noninteractive -encodedcommand <UTF-16LE base64>` 로 넘긴다
# (ansible.windows win_shell.ps1). CreateProcess 명령줄 한도는 32,767 자다. 통합 전 physical disks 스크립트
# 하나가 이미 28,159 자였다 — 합치면서 넘지 않도록 여유를 둔다.
CREATEPROCESS_LIMIT = 32767
COMMAND_LINE_BUDGET = 30000
_WIN_SHELL_PREFIX = "[Console]::InputEncoding = New-Object Text.UTF8Encoding `$false; "
_EXE = '"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -noninteractive -encodedcommand '


def _tasks(path: Path) -> list[dict]:
    out = []
    for t in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        if not isinstance(t, dict):
            continue
        out.append(t)
        for key in ("block", "rescue", "always"):
            out.extend(s for s in (t.get(key) or []) if isinstance(s, dict))
    return out


def _win_shells() -> dict[str, list[dict]]:
    return {p.name: [t for t in _tasks(p) if "ansible.windows.win_shell" in t]
            for p in sorted(WIN.glob("*.yml"))}


def _code(script: str) -> str:
    """PowerShell 주석 줄을 뺀 본문."""
    return "\n".join(ln for ln in script.splitlines() if not ln.lstrip().startswith("#"))


def _script(file: str, name: str) -> str:
    return next(t["ansible.windows.win_shell"] for t in _win_shells()[file] if t["name"] == name)


# ═══════════════════════════════════════════════════════════════════════════
def test_windows_channel_runs_exactly_11_win_shell_tasks():
    shells = _win_shells()
    assert {f: [t["name"] for t in ts] for f, ts in shells.items()} == EXPECTED_WIN_SHELL
    assert sum(len(ts) for ts in shells.values()) == 11


def test_win32_computersystem_is_read_by_at_most_two_scripts():
    """종전 3 회(system os version / system hosting / hardware) → system 1 + hardware 1."""
    readers = [(f, t["name"]) for f, ts in _win_shells().items() for t in ts
               if re.search(r"Win32_ComputerSystem\b", _code(t["ansible.windows.win_shell"]))]
    assert len(readers) <= 2, readers
    assert {f for f, _ in readers} == {"gather_system.yml", "gather_hardware.yml"}
    system = _code(_script("gather_system.yml", MERGED["gather_system.yml"][0]))
    assert len(re.findall(r"Get-CimInstance\s+Win32_ComputerSystem\b", system)) == 1
    memory = _code(_script("gather_memory.yml", MERGED["gather_memory.yml"][0]))
    assert "Win32_ComputerSystem" not in memory


@pytest.mark.parametrize("file,task", [(f, t["name"]) for f, ts in _win_shells().items() for t in ts])
def test_encoded_command_line_stays_under_createprocess_limit(file, task):
    script = _script(file, task).strip()
    encoded = base64.b64encode((_WIN_SHELL_PREFIX + script).encode("utf-16-le")).decode("ascii")
    length = len(_EXE) + len(encoded)
    assert length < COMMAND_LINE_BUDGET < CREATEPROCESS_LIMIT, \
        f"{file} / {task}: 명령줄 {length} 자 — 주석을 스크립트 밖(YAML) 으로 옮기거나 나눠라"


@pytest.mark.parametrize("file", list(MERGED))
def test_merged_script_shape(file):
    name, order = MERGED[file]
    script = _script(file, name)
    code = _code(script)
    # 구성요소 helper: try/catch 로 그 구성요소에만 ok=false + error 를 남긴다 (스크립트는 계속)
    helper = re.search(r"function Invoke-SeComponent\(.*?\n\}", code, re.S)
    assert helper, "Invoke-SeComponent 정의가 없다"
    body = helper.group(0)
    assert "try { $null = & $Body $c }" in body and "catch { $c.ok = $false" in body
    assert "ok = $true; error = $null; rows = (New-Object System.Collections.ArrayList); data = $null" in body
    # 모든 항목이 helper 를 거친다 (공용 조회 read_* 는 쓰는 구성요소보다 먼저)
    assert re.findall(r"Invoke-SeComponent \$doc '([a-z_]+)'", code) == order
    # 문서 하나 — 충분한 깊이 + 압축. 종전 줄 단위 출력(| ConvertTo-Json -Compress) 은 남지 않는다
    outs = re.findall(r"ConvertTo-Json -Depth (\d+) -Compress", code)
    assert outs and all(int(d) >= 6 for d in outs)
    assert "$doc | ConvertTo-Json -Depth" in code
    assert not re.search(r"\}\s*\|\s*ConvertTo-Json -Compress", code), "구성요소 행을 줄 단위로 출력하고 있다"
    # 원소 1개 배열이 객체로 접히지 않게 rows 는 ArrayList 에 담는다
    assert "[void]$c.rows.Add(" in code or file == "gather_system.yml"
    # 다른 태스크 결과를 Jinja 로 끼워 넣지 않는다 (종전 interfaces 스크립트는 meta 값을 받았다)
    assert "{{" not in script and "{%" not in script


def test_network_snapshot_reads_each_source_once():
    code = _code(_script("gather_network.yml", MERGED["gather_network.yml"][0]))
    assert "Get-NetAdapter -InterfaceIndex" not in code, "주소마다 Get-NetAdapter 를 다시 부른다"
    assert len(re.findall(r"\bGet-NetRoute\b", code)) == 1
    assert "-DestinationPrefix '0.0.0.0/0','::/0'" in code
    assert len(re.findall(r"\bGet-NetIPAddress\b", code)) == 1
    assert len(re.findall(r"\bGet-DnsClientServerAddress\b", code)) == 1
    assert len(re.findall(r"\bGet-NetAdapterHardwareInfo\b", code)) == 1
    # 전체 목록 1회 (InterfaceIndex 색인) + 공급자 질의 옵션 Physical 1회
    calls = re.findall(r"\bGet-NetAdapter\b(?!HardwareInfo)([^\n|)]*)", code)
    assert sorted(c.strip() for c in calls) == ["-ErrorAction SilentlyContinue", "-Physical"]
    assert "$naByIdx[[string]$addr.InterfaceIndex]" in code


def test_memory_reads_physical_memory_once_and_keeps_total_expression():
    code = _code(_script("gather_memory.yml", MERGED["gather_memory.yml"][0]))
    assert len(re.findall(r"Get-CimInstance\s+Win32_PhysicalMemory\b", code)) == 1
    # total = 종전 식 그대로 (Capacity 합 → MB 반올림). slots 행을 다시 더하지 않는다.
    assert "[math]::Round(($mem | Measure-Object -Property Capacity -Sum).Sum / 1MB, 0)" in code


def test_runtime_failure_modes_match_old_per_call_scripts():
    """종전 rc≠0 판정이 구성요소 ok=false 로 이어진다: pagefile -ErrorAction Stop / 마지막 문장의 조회."""
    code = _code(_script("gather_runtime.yml", MERGED["gather_runtime.yml"][0]))
    assert "@(Get-CimInstance Win32_PageFileUsage -ErrorAction Stop)" in code
    assert "Get-NetFirewallProfile | ForEach-Object" in code
    assert "Get-NetTCPConnection -State Listen" in code


@pytest.mark.parametrize("file", list(MERGED))
def test_split_document_task_follows_parse_and_rebuilds_register_shape(file):
    name = MERGED[file][0]
    components = _components(file)
    tasks = _tasks(WIN / file)
    names = [t.get("name") for t in tasks]
    section = name.split(" | ")[1]
    i = names.index(name)
    assert names[i + 1] == f"windows | {section} | parse document"
    assert names[i + 2] == f"windows | {section} | split document"
    split = tasks[i + 2]
    assert split.get("no_log") is True and tasks[i + 1].get("no_log") is True
    for key, tmpl in split["ansible.builtin.set_fact"].items():
        assert key.startswith("_w_") and key.endswith(("_raw", "_ntp", "_fw", "_ports", "_pagefile")), key
        assert "'stdout'" in tmpl and "'stdout_lines'" in tmpl and "'rc'" in tmpl, key
        # 구성요소 이름이 문서 키로 쓰인다
        assert any(f"d.get('{c}')" in tmpl for c in components), key


def test_every_win_shell_is_quiet_and_never_fails_the_play():
    for file, tasks in _win_shells().items():
        for t in tasks:
            assert t.get("no_log") is True, (file, t["name"])
            assert t.get("changed_when") is False, (file, t["name"])
            assert t.get("failed_when") is False, (file, t["name"])
            assert t.get("register"), (file, t["name"])


def test_fragment_philosophy_in_windows_tasks():
    """자기 fragment 변수만 set_fact 하고 누적 변수는 건드리지 않는다. 섹션마다 merge_fragment 를 부른다."""
    for path in sorted(WIN.glob("*.yml")):
        tasks = _tasks(path)
        for t in tasks:
            sf = t.get("ansible.builtin.set_fact") or {}
            for key in sf:
                assert key not in ACCUMULATED_VARS, (path.name, t.get("name"), key)
                if key.endswith("_fragment"):
                    assert key in FRAGMENT_VARS, (path.name, t.get("name"), key)
                assert key.startswith("_"), (path.name, key)
        includes = [t for t in tasks if "ansible.builtin.include_tasks" in t]
        assert includes and "merge_fragment.yml" in str(includes[-1]["ansible.builtin.include_tasks"]), path.name


def test_no_regex_in_when_conditions():
    """rule 95 R1 #12 — regex_* 를 when 에 쓰면 None 가드가 필요하다. Windows 태스크에는 그런 조건이 없다."""
    for path in sorted(WIN.glob("*.yml")):
        for t in _tasks(path):
            when = t.get("when")
            if when is None:
                continue
            assert "regex_" not in str(when), (path.name, t.get("name"))
