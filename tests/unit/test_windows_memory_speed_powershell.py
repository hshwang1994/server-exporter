"""Windows memory — slots[].speed_mhz 는 현재 동작 속도 (2026-10-03, Q6).

field_dictionary `memory.slots[].speed_mhz` = "DIMM 현재 동작 속도 (현재 클럭)".
Windows 에서 그 값은 Win32_PhysicalMemory.ConfiguredClockSpeed 다 (Speed 는 모듈 정격 최대 속도).
계약: ConfiguredClockSpeed > 0 이면 그것, 아니면 Speed (> 0), 둘 다 없으면 null.
종전에는 Speed 를 먼저 봐서 정격보다 낮게 동작하는 DIMM(2 DPC 감속 등) 이 정격 속도로 보고됐다.

정적 검사는 모든 플랫폼에서, 실제 실행은 powershell.exe 가 있을 때만 돈다
(win_shell 원문 앞에 Get-CimInstance 를 같은 이름의 함수로 가려 실행 → 출력 JSON 을
gather_memory.yml 의 실제 Jinja 템플릿으로 렌더).
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
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from jedec_mapper import jedec_to_vendor  # noqa: E402

MEM_YML = REPO / "os-gather" / "tasks" / "windows" / "gather_memory.yml"
# 2026-10-03 (P4): total + slots 가 win_shell 하나로 합쳐졌다. 슬롯 행은 그 문서의 slots 구성요소(rows) 에
# 있고, 파일의 split 태스크가 종전 `_w_mem_slots_raw.stdout_lines` (슬롯마다 JSON 한 줄) 로 되돌린다.
SLOTS_TASK = "windows | memory | Win32_PhysicalMemory (total + slots)"
PARSE_TASK = "windows | memory | parse slots + grouping"


def _tasks():
    return [t for t in yaml.safe_load(MEM_YML.read_text(encoding="utf-8")) if isinstance(t, dict)]


def _win_shell(name: str) -> str:
    for t in _tasks():
        if t.get("name") == name:
            return t["ansible.windows.win_shell"]
    raise AssertionError(f"win_shell 태스크 {name!r} 미발견")


def _render_slots(stdout_lines: list[str]) -> list[dict]:
    tmpl = next(t for t in _tasks() if t.get("name") == PARSE_TASK)["ansible.builtin.set_fact"]["_w_mem_slots"]
    env = NativeEnvironment()
    env.filters["from_json"] = json.loads
    env.filters["jedec_to_vendor"] = jedec_to_vendor
    return env.from_string(tmpl).render(_w_mem_slots_raw={"stdout_lines": stdout_lines})


def test_speed_expression_checks_configured_clock_speed_first():
    script = _win_shell(SLOTS_TASK)
    m = re.search(r"\$speedRaw\s*=\s*if\s*\((?P<first>[^)]*)\)", script)
    assert m, "$speedRaw 판정식 미발견"
    assert "ConfiguredClockSpeed" in m.group("first"), "현재 동작 속도(ConfiguredClockSpeed) 를 먼저 봐야 한다"
    assert "$_.Speed" not in m.group("first")


def test_parse_template_passes_speed_through():
    line = json.dumps({"capacity_mb": 32768, "type": "DDR4", "speed_mhz": 2933, "slot": "DIMM_A1",
                       "manufacturer": "Samsung", "part_number": "M393A4K40DB3-CWE", "serial": "1234ABCD"})
    assert _render_slots([line])[0]["speed_mhz"] == 2933


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

_MEM_PRELUDE = r"""
function Get-CimInstance {
  [CmdletBinding()] param([Parameter(Position=0)][string]$ClassName, [string]$Namespace, [string]$Filter)
  if ($ClassName -eq 'Win32_PhysicalMemory') { return $script:__mem }
  throw "unexpected Get-CimInstance $ClassName"
}
function New-Dimm($loc, $speed, $configured) {
  [PSCustomObject]@{
    DeviceLocator = $loc; Speed = $speed; ConfiguredClockSpeed = $configured
    SMBIOSMemoryType = [uint32]26; MemoryType = [uint16]0; Capacity = [uint64]34359738368
    Manufacturer = 'Samsung'; PartNumber = 'M393A4K40DB3-CWE'; SerialNumber = '1234ABCD'
  }
}
$script:__mem = @(
  (New-Dimm 'DIMM_A1' ([uint32]3200) ([uint32]2933)),
  (New-Dimm 'DIMM_A2' ([uint32]3200) ([uint32]0)),
  (New-Dimm 'DIMM_A3' $null ([uint32]4800)),
  (New-Dimm 'DIMM_A4' ([uint32]0) $null),
  (New-Dimm 'DIMM_A5' ([uint32]2666) ([uint32]2666))
)
"""
_EXPECTED = {
    "DIMM_A1": 2933,   # 정격 3200 이지만 2933 으로 동작 → 현재 동작 속도
    "DIMM_A2": 3200,   # ConfiguredClockSpeed 0 (모름) → Speed
    "DIMM_A3": 4800,   # VMware: Speed 없음, ConfiguredClockSpeed 만 있음
    "DIMM_A4": None,   # 둘 다 없음 → null
    "DIMM_A5": 2666,
}


@pytest.mark.skipif(POWERSHELL is None,
                    reason="powershell.exe 없음 — PowerShell 실행 검증은 Windows 호스트에서만 돈다 "
                           "(판정 순서는 위 정적 검사가 모든 플랫폼에서 확인한다)")
def test_powershell_speed_prefers_configured_clock_speed(tmp_path):
    path = tmp_path / "mem.ps1"
    path.write_text(_MEM_PRELUDE + _win_shell(SLOTS_TASK), encoding="utf-8-sig")
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path)],
        capture_output=True, timeout=180, check=False)
    err = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 0 and not err.strip(), err
    doc_lines = [ln for ln in proc.stdout.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    assert len(doc_lines) == 1, doc_lines
    slots = json.loads(doc_lines[0])["slots"]
    assert slots["ok"] is True and slots["error"] is None, slots
    lines = [json.dumps(row) for row in slots["rows"]]          # 종전 슬롯당 1줄과 같은 값
    printed = {json.loads(ln)["slot"]: json.loads(ln)["speed_mhz"] for ln in lines}
    assert printed == _EXPECTED
    rendered = {s["slot"]: s["speed_mhz"] for s in _render_slots(lines)}
    assert rendered == _EXPECTED
