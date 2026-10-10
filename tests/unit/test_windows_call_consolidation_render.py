"""P4 (2026-10-03) — Windows 원격 호출 통합: 같은 입력이면 fragment 가 종전과 같다 (렌더 검증).

배경
----
Windows 채널은 호스트마다 win_shell 20 개를 돌렸다 (WinRM 왕복 1~3 초씩). 섹션별 호출을 PowerShell
스크립트 하나로 합쳐 11 개로 줄였다 (목록 = test_windows_call_consolidation_static.py). 합친 스크립트는
JSON 문서 1개를 내고, 문서 안의 구성요소마다 { ok, error, rows, data } 를 둔다. 각 파일의
"split document" 태스크가 그 문서를 종전 호출별 register 모양(stdout / stdout_lines / rc) 으로 되돌리고,
그 아래 정규화 · fragment 태스크는 손대지 않았다.

이 파일이 고정하는 것
--------------------
1. 종전 태스크 하나 = 새 구성요소 하나 (OLD_TO_COMPONENT). 입력 대응은
     종전 rc == 0  <=>  구성요소 ok == true      (스크립트 전체 rc 가 0 일 때)
     종전 stdout_lines (JSON 한 줄씩)  <=>  구성요소 rows
     종전 stdout (JSON 객체 / 숫자)    <=>  구성요소 data
     스크립트 전체 실패(rc=R, 출력 없음) <=>  종전 태스크 전부 rc=R, 출력 없음
   이 대응으로 같은 값을 종전 파일(PRE_P4_SHA, git) 과 새 파일에 넣고 다섯 fragment 와 중간 변수가
   모두 같은지 본다. 시나리오: 10.100.64.120 재현, NIC 2 + 팀 1, 팀 · HBA · IB 없음, 구성요소 실패
   (Get-NetFirewallProfile 예외 등), 스크립트 전체 실패.
2. 종전 파일의 set_fact 태스크(정규화 · fragment) 는 새 파일에 글자 그대로 남아 있다.
3. 새 체인만으로도 10.100.64.120 실장비 출력(tests/evidence) 을 그대로 낸다 (git 이 없어도 돈다).
4. split 태스크 자체의 계약: rc 유도 규칙, 행 1개가 객체로 접힌 경우, 구성요소 누락.

PowerShell 실행(합친 스크립트가 실제로 그 문서를 내는지, 종전 스크립트와 같은 행을 내는지) 은
test_windows_call_consolidation_powershell.py 가 맡는다. 이 파일의 하네스(run_chain 등) 를 그 파일이 쓴다.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")
from jinja2 import Environment  # noqa: E402
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
WIN = REPO / "os-gather" / "tasks" / "windows"
sys.path.insert(0, str(REPO / "filter_plugins"))
from identity_normalizer import normalize_mac, normalize_uuid, normalize_wwn  # noqa: E402
from jedec_mapper import jedec_to_vendor  # noqa: E402
from network_topology import build_windows_network  # noqa: E402
from serial_normalizer import normalize_os_serial  # noqa: E402

# 통합 직전 main (Windows 태스크 파일 = win_shell 20 개). 종전 템플릿의 기준점이다.
PRE_P4_SHA = "a38c63390d50e2caae7736bb9cd2e17f92b0e5b9"
EVIDENCE_120 = REPO / "tests" / "evidence" / "2026-09-03-live" / "build192_win2022_10.100.64.120.json"

FRAGMENT_KEYS = ("_data_fragment", "_sections_supported_fragment", "_sections_collected_fragment",
                 "_sections_failed_fragment", "_errors_fragment")

# 종전 태스크 → 새 구성요소 (이름, 종류). 종류: rows = JSON 한 줄씩 / data = JSON 객체 하나 /
#   scalar = 숫자 한 줄 (memory total) / ports = 포트 번호 한 줄씩
OLD_TO_COMPONENT = {
    "memory": {
        "windows | memory | Win32_PhysicalMemory total": ("total", "scalar"),
        "windows | memory | Win32_PhysicalMemory slots": ("slots", "rows"),
    },
    "system": {
        "windows | system | os version": ("os", "data"),
        "windows | system | hosting detection": ("hosting", "data"),
    },
    "network": {
        "windows | network | dns and gateway": ("meta", "data"),
        "windows | network | interfaces": ("interfaces", "rows"),
        "windows | network | NIC driver map (Get-NetAdapter)": ("driver_map", "rows"),
        "windows | network | physical adapters (hardware)": ("adapters", "rows"),
    },
    "runtime": {
        "windows | runtime | timezone + NTP": ("ntp", "data"),
        "windows | runtime | firewall profiles": ("firewall", "rows"),
        "windows | runtime | listening TCP ports": ("ports", "ports"),
        "windows | runtime | pagefile (swap)": ("pagefile", "rows"),
    },
    "storage": {
        "windows | storage | volumes": ("volumes", "rows"),
        "windows | storage | physical disks": ("disks", "rows"),
    },
}
MERGED_TASK = {
    "memory": "windows | memory | Win32_PhysicalMemory (total + slots)",
    "system": "windows | system | os version + hosting detection",
    "network": "windows | network | snapshot (routes + adapters + addresses + dns)",
    "runtime": "windows | runtime | timezone + NTP + firewall + ports + pagefile",
    "storage": "windows | storage | volumes + physical disks",
}
# 합치지 않고 그대로 둔 win_shell (종전 · 새 파일에 같은 이름 · 같은 스크립트)
UNCHANGED_SHELL = {
    "network": ("windows | network | teaming (LBFO + SET)",),
    "storage": ("windows | storage | initiator ports + HBA attrs",
                "windows | storage | infiniband adapters (best-effort)"),
}
# split 태스크가 만드는 register 모양 변수 / 문서 변수 — 종전 · 새 체인 비교에서 뺀다
TRANSPORT_VARS = {
    "_w_mem_doc_raw", "_w_mem_doc", "_w_mem_raw", "_w_mem_slots_raw",
    "_w_sys_doc_raw", "_w_sys_doc", "_w_os_raw", "_w_hosting_raw",
    "_w_net_doc_raw", "_w_net_doc", "_w_net_meta_raw", "_w_iface_raw", "_w_drvmap_raw", "_w_adapters_raw",
    "_w_rt_doc_raw", "_w_rt_doc", "_w_rt_ntp", "_w_rt_fw", "_w_rt_ports", "_w_rt_pagefile",
    "_w_stor_doc_raw", "_w_stor_doc", "_w_vol_raw", "_w_disk_raw",
}


# ═══════════════════════════════════════════════════════════════════════════
# Ansible 흉내 렌더 하네스
# ═══════════════════════════════════════════════════════════════════════════
def _ansible_bool(value):
    """ansible.builtin.bool 과 같은 판정."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value == 1
    return str(value).strip().lower() in ("yes", "on", "1", "true", "y", "t")


def _regex_replace(value="", pattern="", replacement="", ignorecase=False, multiline=False, count=0):
    flags = (re.I if ignorecase else 0) | (re.M if multiline else 0)
    return re.sub(pattern, replacement, str(value), count=count, flags=flags)


def _combine(*dicts, recursive=False, list_merge="replace"):
    out = {}
    for d in dicts:
        out.update(d or {})
    return out


FILTERS = {
    "from_json": json.loads,
    "to_json": json.dumps,
    "bool": _ansible_bool,
    "regex_replace": _regex_replace,
    "combine": _combine,
    "normalize_mac": normalize_mac,
    "normalize_uuid": normalize_uuid,
    "normalize_wwn": normalize_wwn,
    "jedec_to_vendor": jedec_to_vendor,
    "normalize_os_serial": normalize_os_serial,
    "build_windows_network": build_windows_network,
}
_JINJA_MARKERS = ("{{", "{%", "{#")


def _native_env() -> NativeEnvironment:
    env = NativeEnvironment()
    env.filters.update(FILTERS)
    return env


def _text_env() -> Environment:
    env = Environment()  # noqa: S701 — 테스트 전용 (PowerShell 스크립트 문자열 렌더)
    env.filters.update(FILTERS)
    return env


def render(value, ctx):
    """set_fact 값 렌더 (중첩 dict / list 포함). Jinja 표지 없는 문자열은 그대로."""
    if isinstance(value, dict):
        return {k: render(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, ctx) for v in value]
    if isinstance(value, str) and any(m in value for m in _JINJA_MARKERS):
        return _native_env().from_string(value).render(**ctx)
    return value


def iter_tasks(doc):
    for task in doc or []:
        if not isinstance(task, dict):
            continue
        if "block" in task:
            yield from iter_tasks(task["block"])
        else:
            yield task


def run_chain(yaml_text: str, ctx: dict, shell):
    """win_shell + set_fact 를 파일 순서대로 평가한다 (include_tasks = merge_fragment 는 건너뛴다).

    - win_shell: 스크립트에 Jinja 가 있으면 현재 ctx 로 렌더한 뒤 shell(task_name, script) 의 결과를
      register 이름으로 둔다 (종전 network interfaces 스크립트가 meta 값을 Jinja 로 받았다).
    - set_fact: task vars 를 먼저 풀고, 같은 태스크 안의 키끼리는 태스크 전 ctx 로 렌더한다 (Ansible 의미).
    반환: (fragment dict | None, 최종 ctx)
    """
    ctx = dict(ctx)
    frag = None
    for task in iter_tasks(yaml.safe_load(yaml_text)):
        if "ansible.windows.win_shell" in task:
            script = task["ansible.windows.win_shell"]
            if any(m in script for m in _JINJA_MARKERS):
                script = _text_env().from_string(script).render(**ctx)
            ctx[task["register"]] = shell(task["name"], script)
        elif "ansible.builtin.set_fact" in task:
            local = dict(ctx)
            for k, v in (task.get("vars") or {}).items():
                local[k] = render(v, local)
            new = {k: render(v, local) for k, v in task["ansible.builtin.set_fact"].items()}
            ctx.update(new)
            if "_data_fragment" in new:
                frag = {k: new.get(k) for k in FRAGMENT_KEYS}
    return frag, ctx


# ═══════════════════════════════════════════════════════════════════════════
# 종전 / 새 파일
# ═══════════════════════════════════════════════════════════════════════════
def new_text(section: str) -> str:
    return (WIN / f"gather_{section}.yml").read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def old_text(section: str) -> str | None:
    """통합 직전 파일 (git show PRE_P4_SHA:...). git / 커밋이 없으면 None."""
    try:
        proc = subprocess.run(
            ["git", "show", f"{PRE_P4_SHA}:os-gather/tasks/windows/gather_{section}.yml"],
            cwd=str(REPO), capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8")


def require_old(section: str) -> str:
    text = old_text(section)
    if text is None:
        pytest.skip(f"통합 직전 파일({PRE_P4_SHA[:8]}) 을 git 으로 읽을 수 없다 — 종전/새 비교는 "
                    "저장소 이력이 있는 작업 사본에서만 돈다 (새 체인 단독 검증은 그대로 돈다)")
    return text


# ═══════════════════════════════════════════════════════════════════════════
# 입력 모델 — 구성요소 결과 하나 = 종전 태스크 결과 하나
# ═══════════════════════════════════════════════════════════════════════════
def comp(*, rows=None, data=None):
    """정상 구성요소 (종전 태스크 rc=0)."""
    return {"ok": True, "error": None, "rows": list(rows or []), "data": data}


def failed(error="fixture: terminating error", *, rows=None):
    """구성요소 종료 오류. rows = 오류 전에 이미 낸 행 (종전 스크립트도 그만큼은 출력했다)."""
    return {"ok": False, "error": error, "rows": list(rows or []), "data": None}


def _lines_register(lines, rc):
    return {"stdout": "".join(ln + "\r\n" for ln in lines), "stdout_lines": list(lines), "rc": rc}


def old_registers(section: str, comps: dict, script_rc: int = 0) -> dict:
    """구성요소 결과 → 종전 태스크별 register (PowerShell -EncodedCommand 의미: 종료 오류 = rc 1)."""
    out = {}
    for task, (name, kind) in OLD_TO_COMPONENT[section].items():
        c = comps[name]
        if script_rc != 0:
            out[task] = _lines_register([], script_rc)
            continue
        rc = 0 if c["ok"] else 1
        if kind == "rows":
            out[task] = _lines_register([json.dumps(r) for r in c["rows"]], rc)
        elif kind == "ports":
            out[task] = _lines_register([str(p) for p in c["rows"]], rc)
        elif kind == "data":
            out[task] = _lines_register([json.dumps(c["data"])] if c["data"] is not None else [], rc)
        elif kind == "scalar":
            out[task] = _lines_register([str(c["data"])] if c["data"] is not None else [], rc)
        else:  # pragma: no cover
            raise AssertionError(kind)
    return out


def new_register(section: str, comps: dict, script_rc: int = 0) -> dict:
    """구성요소 결과 → 합친 스크립트의 register (JSON 문서 1줄). 스크립트 전체 실패면 출력 없음."""
    if script_rc != 0:
        return _lines_register([], script_rc)
    names = [name for name, _ in OLD_TO_COMPONENT[section].values()]
    doc = {name: comps[name] for name in names}
    return _lines_register([json.dumps(doc)], 0)


def fake_shell(section: str, which: str, comps: dict, extra: dict | None, script_rc: int):
    old = old_registers(section, comps, script_rc)
    merged = new_register(section, comps, script_rc)
    extra = extra or {}

    def shell(task_name, _script):
        if task_name in UNCHANGED_SHELL.get(section, ()):
            return copy.deepcopy(extra[task_name])
        if which == "old" and task_name in old:
            return copy.deepcopy(old[task_name])
        if which == "new" and task_name == MERGED_TASK[section]:
            return copy.deepcopy(merged)
        raise AssertionError(f"{which} {section}: 모르는 win_shell {task_name!r} — 시나리오 표를 갱신하라")
    return shell


def render_new(section, comps, facts=None, extra=None, script_rc=0):
    return run_chain(new_text(section), dict(facts or {}), fake_shell(section, "new", comps, extra, script_rc))


def render_old(section, comps, facts=None, extra=None, script_rc=0):
    return run_chain(require_old(section), dict(facts or {}),
                     fake_shell(section, "old", comps, extra, script_rc))


def shared_facts(old_ctx: dict, new_ctx: dict, facts: dict) -> list[str]:
    """두 체인이 함께 만든 중간 변수 (입력 · 전송 변수 제외)."""
    keys = (set(old_ctx) & set(new_ctx)) - set(facts) - TRANSPORT_VARS
    return sorted(k for k in keys if k.startswith("_"))


# ═══════════════════════════════════════════════════════════════════════════
# 시나리오
# ═══════════════════════════════════════════════════════════════════════════
def _evidence():
    return json.loads(EVIDENCE_120.read_text(encoding="utf-8"))["data"]


# ── memory ────────────────────────────────────────────────────────────────
def mem_120():
    """10.100.64.120 (Windows Server 2022 VM, 8 GB VMware 가상 DIMM 1개)."""
    return dict(
        comps={"total": comp(data=8192),
               "slots": comp(rows=[{"capacity_mb": 8192, "type": "DRAM", "speed_mhz": None,
                                    "slot": "RAM slot #0", "manufacturer": "VMware Virtual RAM",
                                    "part_number": "VMW-8192MB", "serial": None}])},
        facts={"ansible_memtotal_mb": 8192, "ansible_memfree_mb": 4446})


def mem_mixed_dimms():
    rows = [{"capacity_mb": 32768, "type": "DDR4", "speed_mhz": 2933, "slot": f"DIMM_A{i}",
             "manufacturer": "Samsung", "part_number": "M393A4K40DB3-CWE", "serial": f"SER{i}"} for i in range(4)]
    rows += [{"capacity_mb": 16384, "type": "DDR4", "speed_mhz": 3200, "slot": "DIMM_B0",
              "manufacturer": "00CE00B300000000", "part_number": " HMA82GR7CJR8N-XN ", "serial": None},
             {"capacity_mb": None, "type": None, "speed_mhz": None, "slot": "DIMM_B1",
              "manufacturer": None, "part_number": None, "serial": None}]
    return dict(comps={"total": comp(data=147456), "slots": comp(rows=rows)},
                facts={"ansible_memtotal_mb": 147000, "ansible_memfree_mb": 100000})


def mem_total_failed():
    """total 구성요소만 실패 → OS 가시량으로 대신하고 경고 1건 (detail rc=1 — 종전 total 태스크 rc)."""
    s = mem_120()
    s["comps"]["total"] = failed("Get-CimInstance : Access denied (fixture)")
    return s


def mem_shared_read_failed():
    """Win32_PhysicalMemory 공용 조회 실패 → 두 구성요소 모두 실패 (종전 두 태스크 모두 rc=1)."""
    return dict(comps={"total": failed("WMI unavailable (fixture)"), "slots": failed("WMI unavailable (fixture)")},
                facts={"ansible_memtotal_mb": 4096})


def mem_no_modules():
    return dict(comps={"total": comp(data=None), "slots": comp(rows=[])}, facts={"ansible_memtotal_mb": 2048})


def mem_script_failed():
    return dict(comps={"total": comp(), "slots": comp()}, facts={}, script_rc=1)


# ── system ────────────────────────────────────────────────────────────────
_SYS_FACTS_120 = {
    "ansible_product_serial": "VMware-42 04 a2 40 1d 5c 63 c9-f6 0b 5f b4 72 98 d7 dd",
    "ansible_product_uuid": "40A20442-5C1D-C963-F60B-5FB47298D7DD",
    "ansible_uptime_seconds": 6293079, "ansible_architecture2": "x86_64", "ansible_architecture": "64-bit",
    "ansible_hostname": "WIN-TP7D9J9QKCB", "ansible_fqdn": "WIN-TP7D9J9QKCB",
    "ansible_os_name": "Microsoft Windows Server 2022 Standard",
    "ansible_distribution": "Microsoft Windows Server 2022 Standard",
}


def sys_120():
    return dict(
        comps={"os": comp(data={"caption": "Microsoft Windows Server 2022 Standard", "version": "10.0.20348",
                                "build": "20348", "rel_id": "21H2", "arch": "64-bit",
                                "hostname": "WIN-TP7D9J9QKCB", "domain": None, "part_of_domain": False,
                                "uptime": 6293100}),
               "hosting": comp(data={"Model": "VMware7,1", "Manufacturer": "VMware, Inc.",
                                     "HypervisorPresent": "True", "HyperVRole": "False"})},
        facts=dict(_SYS_FACTS_120))


def sys_hyperv_host_domain():
    return dict(
        comps={"os": comp(data={"caption": "Microsoft Windows Server 2019 Datacenter", "version": "10.0.17763",
                                "build": "17763", "rel_id": "1809", "arch": "64-bit", "hostname": "HV01",
                                "domain": "corp.example.com", "part_of_domain": True, "uptime": 86400}),
               "hosting": comp(data={"Model": "Rack Server X", "Manufacturer": "Contoso Inc",
                                     "HypervisorPresent": "True", "HyperVRole": "True"})},
        facts={"ansible_product_serial": "CZ12345678", "ansible_architecture": "64-bit",
               "ansible_os_name": "Microsoft Windows Server 2019 Datacenter"})


def sys_os_failed_no_facts():
    """os 구성요소 실패 + setup fact 없음 → system 실패 1건 (detail rc=1 — 종전 os version 태스크 rc)."""
    s = sys_120()
    s["comps"]["os"] = failed("Get-CimInstance : Invalid class (fixture)")
    s["facts"] = {}
    return s


def sys_hosting_failed():
    s = sys_120()
    s["comps"]["hosting"] = failed("Win32_ComputerSystem read failed (fixture)")
    return s


def sys_script_failed():
    return dict(comps={"os": comp(), "hosting": comp()}, facts=dict(_SYS_FACTS_120), script_rc=1)


# ── network ───────────────────────────────────────────────────────────────
def _iface_row(name, idx, desc, mac, mtu, speed, address, prefix, *, primary=False, gateway=None, family="ipv4"):
    return {"id": name, "name": name, "description": desc, "interface_index": idx, "mac": mac, "mtu": mtu,
            "speed_mbps": speed, "status": "Up", "is_primary": primary, "family": family, "address": address,
            "prefix": prefix, "gateway": gateway}


def _wadp(name, mac, speed, status="Up"):
    return "WADP " + json.dumps({"name": name, "mac": mac, "status": status, "speed_mbps": speed})


def _teams_register(lines):
    return _lines_register(lines, 0)


def net_120():
    """10.100.64.120 — vmxnet3 6개, LBFO 팀 2개(LabTeam1 위 VLAN 100 tNIC), IPv4 기본 경로 1개, DNS 9개."""
    ev = _evidence()["network"]
    mux = "Microsoft Network Adapter Multiplexor Driver"
    v6 = {"LabTeam2": "fe80::aafe:dbe5:2046:3334", "LabTeam1 - VLAN 100": "fe80::8f14:1ce7:dc52:ff8d",
          "LabTeam1": "fe80::24f:9847:49f8:c735", "Ethernet0": "fe80::3bfa:737e:b64b:84d5",
          "Ethernet4": "fe80::8a37:13e2:7dc5:b957"}
    nics = [  # (name, ifindex, description, mac, mtu, speed, [ipv4...], primary)
        ("LabTeam2", 21, mux + " #3", "00-50-56-84-C9-5F", 1500, 20000, ["192.168.200.10"], False),
        ("LabTeam1 - VLAN 100", 19, mux + " #2", "00-50-56-84-B0-78", 1500, 20000, ["192.168.100.10"], False),
        ("LabTeam1", 17, mux, "00-50-56-84-B0-78", 1500, 20000, ["192.168.99.10"], False),
        ("Ethernet0", 9, "vmxnet3 Ethernet Adapter #6", "00-50-56-84-CB-C9", 1500, 10000, ["10.100.64.120"], True),
        ("Ethernet4", 12, "vmxnet3 Ethernet Adapter #3", "00-50-56-84-11-DB", 9000, 10000,
         ["192.168.50.41", "192.168.50.40"], False),
    ]
    rows = []
    for name, idx, desc, mac, mtu, speed, v4s, primary in nics:
        for a in v4s:
            rows.append(_iface_row(name, idx, desc, mac, mtu, speed, a, 24, primary=primary,
                                   gateway=("10.100.64.254" if primary else None)))
    for name, idx, desc, mac, mtu, speed, _v4s, primary in nics:
        # 종전 interfaces 스크립트: 기본 경로 NIC 의 IPv6 행 gateway = $gw6 (IPv6 기본 경로 없음 → '')
        rows.append(_iface_row(name, idx, desc, mac, mtu, speed, f"{v6[name]}%{idx}", 64, primary=primary,
                               gateway=("" if primary else None), family="ipv6"))
    drv = [{"name": d["name"], "driver": d["driver"], "driver_version": d["driver_version"],
            "vlan_id": d["vlan_id"], "bond_master": None} for d in ev["driver_map"]]
    adapters = [{"name": a["name"], "model": a["model"], "manufacturer": a["manufacturer"], "driver": a["driver"],
                 "driver_version": a["driver_version"], "mac": a["mac"].replace(":", "-").upper(),
                 "pci": a["pci"], "status": "Up", "speed_mbps": a["speed_mbps"]} for a in ev["adapters"]]
    macs = {a["name"]: a["mac"] for a in ev["adapters"]}
    team_lines = [_wadp(n, macs[n], 10000) for n in ("Ethernet0", "Ethernet1", "Ethernet2", "Ethernet3",
                                                      "Ethernet4", "Ethernet5")]
    team_lines += [_wadp("LabTeam1", "00:50:56:84:b0:78", 20000), _wadp("LabTeam2", "00:50:56:84:c9:5f", 20000),
                   _wadp("LabTeam1 - VLAN 100", "00:50:56:84:b0:78", 20000)]
    team_lines += [
        "LBFOTEAM " + json.dumps({"name": "LabTeam1", "teaming_mode": "SwitchIndependent",
                                  "load_balancing": "TransportPorts", "lacp_timer": "", "status": "Up",
                                  "members": ["Ethernet2", "Ethernet1"]}),
        "LBFOTEAM " + json.dumps({"name": "LabTeam2", "teaming_mode": "SwitchIndependent",
                                  "load_balancing": "IPAddresses", "lacp_timer": "", "status": "Up",
                                  "members": ["Ethernet3", "Ethernet5"]}),
    ]
    team_lines += ["LBFOMEMBER " + json.dumps({"name": m, "team": t, "admin_mode": "Active"})
                   for m, t in (("Ethernet2", "LabTeam1"), ("Ethernet1", "LabTeam1"),
                                ("Ethernet3", "LabTeam2"), ("Ethernet5", "LabTeam2"))]
    team_lines += [
        "LBFOTEAMNIC " + json.dumps({"name": "LabTeam1", "team": "LabTeam1", "vlan_id": None, "default": True}),
        "LBFOTEAMNIC " + json.dumps({"name": "LabTeam1 - VLAN 100", "team": "LabTeam1", "vlan_id": 100,
                                     "default": False}),
        "LBFOTEAMNIC " + json.dumps({"name": "LabTeam2", "team": "LabTeam2", "vlan_id": None, "default": True}),
    ]
    return dict(
        comps={"meta": comp(data={"gw": "10.100.64.254", "gw6": None, "dns": ev["dns_servers"]}),
               "interfaces": comp(rows=rows), "driver_map": comp(rows=drv), "adapters": comp(rows=adapters)},
        facts={}, extra={"windows | network | teaming (LBFO + SET)": _teams_register(team_lines)})


def net_two_nics_one_team():
    """물리 NIC 2개(Ethernet1/2) 를 LBFO 팀 Team1 로 묶고 Ethernet0 이 기본 경로. DNS 서버 1개."""
    rows = [
        _iface_row("Ethernet0", 4, "Intel(R) Ethernet 10G 2P X710", "A0-36-9F-00-00-01", 1500, 10000,
                   "10.0.0.15", 24, primary=True, gateway="10.0.0.1"),
        _iface_row("Team1", 11, "Microsoft Network Adapter Multiplexor Driver", "A0-36-9F-00-00-02", 9000, 50000,
                   "172.16.5.10", 22),
        _iface_row("Ethernet0", 4, "Intel(R) Ethernet 10G 2P X710", "A0-36-9F-00-00-01", 1500, 10000,
                   "2001:db8::15", 64, primary=True, gateway="fe80::1", family="ipv6"),
    ]
    drv = [{"name": n, "driver": d, "driver_version": "1.2.3.4", "vlan_id": None, "bond_master": None}
           for n, d in (("Ethernet0", "Intel(R) Ethernet 10G 2P X710"), ("Ethernet1", "Intel(R) Ethernet 25G"),
                        ("Ethernet2", "Intel(R) Ethernet 25G"),
                        ("Team1", "Microsoft Network Adapter Multiplexor Driver"))]
    adapters = [{"name": n, "model": m, "manufacturer": "Intel Corporation", "driver": m, "driver_version": "1.2.3.4",
                 "mac": mac, "pci": pci, "status": "Up", "speed_mbps": sp}
                for n, m, mac, pci, sp in (("Ethernet0", "Intel(R) Ethernet 10G 2P X710", "A0-36-9F-00-00-01",
                                            "0000:3b:00.0", 10000),
                                           ("Ethernet1", "Intel(R) Ethernet 25G", "A0-36-9F-00-00-02",
                                            "0000:5e:00.0", 25000),
                                           ("Ethernet2", "Intel(R) Ethernet 25G", "A0-36-9F-00-00-03", None, 25000))]
    team_lines = [_wadp("Ethernet0", "a0:36:9f:00:00:01", 10000), _wadp("Ethernet1", "a0:36:9f:00:00:02", 25000),
                  _wadp("Ethernet2", "a0:36:9f:00:00:03", 25000), _wadp("Team1", "a0:36:9f:00:00:02", 50000),
                  "LBFOTEAM " + json.dumps({"name": "Team1", "teaming_mode": "Lacp", "load_balancing": "Dynamic",
                                            "lacp_timer": "Fast", "status": "Up",
                                            "members": ["Ethernet1", "Ethernet2"]}),
                  "LBFOMEMBER " + json.dumps({"name": "Ethernet1", "team": "Team1", "admin_mode": "Active"}),
                  "LBFOMEMBER " + json.dumps({"name": "Ethernet2", "team": "Team1", "admin_mode": "Standby"}),
                  "LBFOTEAMNIC " + json.dumps({"name": "Team1", "team": "Team1", "vlan_id": None, "default": True})]
    return dict(
        comps={"meta": comp(data={"gw": "10.0.0.1", "gw6": "fe80::1", "dns": ["10.0.0.53"]}),
               "interfaces": comp(rows=rows), "driver_map": comp(rows=drv), "adapters": comp(rows=adapters)},
        facts={}, extra={"windows | network | teaming (LBFO + SET)": _teams_register(team_lines)})


def net_no_team():
    """팀 cmdlet 출력 없음 (팀이 없거나 cmdlet 이 없는 SKU). 기본 경로 없음 · DNS 없음 · 어댑터 없는 주소 1개."""
    rows = [_iface_row("Ethernet", 6, "Red Hat VirtIO Ethernet Adapter", "52-54-00-12-34-56", 1500, 1000,
                       "192.168.122.20", 24),
            {"id": "Loopback Pseudo-Interface 2", "name": "Loopback Pseudo-Interface 2", "description": None,
             "interface_index": 33, "mac": None, "mtu": None, "speed_mbps": None, "status": None,
             "is_primary": False, "family": "ipv4", "address": "10.255.0.1", "prefix": 32, "gateway": None}]
    return dict(
        comps={"meta": comp(data={"gw": None, "gw6": None, "dns": []}), "interfaces": comp(rows=rows),
               "driver_map": comp(rows=[{"name": "Ethernet", "driver": "Red Hat VirtIO Ethernet Adapter",
                                         "driver_version": "100.92.104.24500", "vlan_id": None, "bond_master": None}]),
               "adapters": comp(rows=[])},
        facts={}, extra={"windows | network | teaming (LBFO + SET)": _teams_register([])})


def net_interfaces_failed():
    """팀 호스트에서 interfaces 만 실패. 팀 멤버 NIC 는 팀 토폴로지 보강이 만들어 넣으므로 섹션은 수집됨으로
    남는다 (종전 동작 그대로 — 아래 비교가 고정한다). meta / driver_map / adapters / teams 는 채워진다."""
    s = net_two_nics_one_team()
    s["comps"]["interfaces"] = failed("Get-NetIPAddress : WMI provider failure (fixture)")
    return s


def net_interfaces_failed_no_team():
    """팀 없는 호스트에서 interfaces 실패 → network 실패 1건 (detail rc=1 — 종전 interfaces 태스크 rc)."""
    s = net_no_team()
    s["comps"]["interfaces"] = failed("Get-NetIPAddress : WMI provider failure (fixture)")
    return s


def net_script_failed():
    s = net_no_team()
    s["script_rc"] = 1
    return s


# ── runtime ───────────────────────────────────────────────────────────────
def _fw(name, enabled=True):
    return {"profile": name, "enabled": enabled, "default_inbound": "NotConfigured",
            "default_outbound": "NotConfigured"}


def rt_120():
    rt = _evidence()["system"]["runtime"]
    return dict(comps={
        "ntp": comp(data={"timezone": "Asia/Seoul", "timezone_raw": "Korea Standard Time", "w32time_running": True,
                          "source": "time.windows.com,0x9", "synced": True, "last_sync": None}),
        "firewall": comp(rows=[_fw("Domain"), _fw("Private"), _fw("Public")]),
        "ports": comp(rows=[int(p) for p in rt["listening_ports"]]),
        "pagefile": comp(rows=[{"name": "C:\\pagefile.sys", "size_mb": 1280, "used_mb": 527, "peak_mb": 536}]),
    }, facts={})


def rt_firewall_throws():
    """Get-NetFirewallProfile 예외 → firewall 만 ok=false. errors[] 는 종전처럼 scope=firewall 1건."""
    s = rt_120()
    s["comps"]["firewall"] = failed("Get-NetFirewallProfile : Access is denied. (fixture)")
    return s


def rt_ntp_and_pagefile_failed():
    s = rt_120()
    s["comps"]["ntp"] = failed("Get-TimeZone threw (fixture)")
    s["comps"]["pagefile"] = failed("Win32_PageFileUsage : Access denied (fixture)")
    return s


def rt_quiet_host():
    """프로필 모두 꺼짐 · 리스닝 포트 없음 · pagefile 없음 (조회는 성공) · W32Time 정지."""
    return dict(comps={
        "ntp": comp(data={"timezone": "UTC", "timezone_raw": "UTC", "w32time_running": False,
                          "source": "Local CMOS Clock", "synced": False, "last_sync": None}),
        "firewall": comp(rows=[_fw("Domain", False)]), "ports": comp(rows=[]), "pagefile": comp(rows=[]),
    }, facts={})


def rt_script_failed():
    s = rt_120()
    s["script_rc"] = 1
    return s


# ── storage ───────────────────────────────────────────────────────────────
def _volume(letter, total_mb, free_mb, fs="NTFS"):
    return {"drive": letter, "fs": fs, "total": total_mb * 1048576 + 4096, "free": free_mb * 1048576 + 1024}


_NO_HBA = {"windows | storage | initiator ports + HBA attrs":
           _lines_register([json.dumps({"ports": [], "adapters": [], "port_attrs": []})], 0),
           "windows | storage | infiniband adapters (best-effort)": _lines_register([json.dumps({"ib": []})], 0)}


def stor_120():
    from test_windows_storage_enum_render import ps_lines_like_120  # 기존 재현 입력 그대로
    return dict(comps={"volumes": comp(rows=[_volume("C", 101683, 80129), _volume("E", 102382, 102287)]),
                       "disks": comp(rows=ps_lines_like_120())},
                facts={}, extra=copy.deepcopy(_NO_HBA))


def stor_physical_mixed():
    """NVMe / SATA SSD / 미분류 BusType(Storage Spaces) — 팀 · HBA · IB 없음. FC HBA 포트 1개."""
    disks = [{"device": f"\\\\.\\PHYSICALDRIVE{i}", "model": m, "serial": s, "wwn": w, "total": t, "media": md,
              "protocol": p, "health": h, "is_os_disk": os_, "bus_type_raw": raw}
             for i, (m, s, w, t, md, p, h, os_, raw) in enumerate((
                 ("Samsung SSD 980 PRO 1TB", "S5GXNF0R123456", "eui.0025385a1234abcd", 1000204886016, "SSD", "NVMe",
                  "OK", True, None),
                 ("ST4000NM000A", "WFN0ABCD", None, 4000787030016, "HDD", "SATA", "Warning", False, None),
                 ("Microsoft Storage Space Device", None, None, 2199023255552, None, None, None, False, 16)))]
    hba = {"ports": [{"node_addr": "20:00:00:24:ff:01:02:03", "port_addr": "21:00:00:24:ff:01:02:03",
                      "conn_type": "Fibre Channel", "oper_status": "Operational"}],
           "adapters": [{"node_wwn": "20:00:00:24:ff:01:02:03", "manufacturer": "Acme", "model": "FC-A",
                         "driver": "acmefc.sys", "firmware": "9.1"}], "port_attrs": []}
    extra = copy.deepcopy(_NO_HBA)
    extra["windows | storage | initiator ports + HBA attrs"] = _lines_register([json.dumps(hba)], 0)
    return dict(comps={"volumes": comp(rows=[_volume("C", 475000, 120000), _volume("D", 3800000, 3700000, "ReFS")]),
                       "disks": comp(rows=disks)}, facts={}, extra=extra)


def stor_disks_failed_no_volumes():
    """disks 실패 + 볼륨 없음 → storage 실패 1건 (detail rc=1 — 종전 physical disks 태스크 rc)."""
    return dict(comps={"volumes": comp(rows=[]), "disks": failed("Win32_DiskDrive : RPC server unavailable (fixture)")},
                facts={}, extra=copy.deepcopy(_NO_HBA))


def stor_volumes_failed():
    s = stor_120()
    s["comps"]["volumes"] = failed("Get-Volume threw (fixture)")
    return s


def stor_script_failed():
    s = stor_120()
    s["script_rc"] = 1
    return s


SCENARIOS = {
    "memory": [mem_120, mem_mixed_dimms, mem_total_failed, mem_shared_read_failed, mem_no_modules,
               mem_script_failed],
    "system": [sys_120, sys_hyperv_host_domain, sys_os_failed_no_facts, sys_hosting_failed, sys_script_failed],
    "network": [net_120, net_two_nics_one_team, net_no_team, net_interfaces_failed, net_interfaces_failed_no_team,
                net_script_failed],
    "runtime": [rt_120, rt_firewall_throws, rt_ntp_and_pagefile_failed, rt_quiet_host, rt_script_failed],
    "storage": [stor_120, stor_physical_mixed, stor_disks_failed_no_volumes, stor_volumes_failed,
                stor_script_failed],
}
_CASES = [(section, fn) for section, fns in SCENARIOS.items() for fn in fns]


def _scenario(fn):
    s = fn()
    return s["comps"], s.get("facts") or {}, s.get("extra"), s.get("script_rc", 0)


# 2026-10-05 (최종 정비 §5 — 예외 무시 지점 감사 C-3 · C-6): 새 체인은 구성요소 실패를 errors[] 로 드러낸다. 종전 체인은 같은 입력에서
#   기록이 없었다(섹션은 OS 정보 · setup fact · 볼륨으로 성공) — 의도한 차이라 기대값에 명시한다. 그 밖의 fragment 와 중간 변수는 종전과 같아야 한다.
INTENDED_EXTRA_ERRORS = {
    ("system", "sys_hosting_failed"): [{"section": "system", "message": "서버 기본 정보 일부를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요.",
                                        "detail": "source=Win32_OperatingSystem,Win32_ComputerSystem; cause=component_failed; parts=hosting"}],
    ("system", "sys_script_failed"): [{"section": "system", "message": "서버 기본 정보 일부를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요.",
                                       "detail": "source=Win32_OperatingSystem,Win32_ComputerSystem; cause=component_failed; parts=script"}],
}
# 2026-10-05 (8차 R5): 네트워크 조회(어댑터 · 경로 · DNS · 주소)와 파일시스템(Get-Volume) 조회 실패도 기록한다 — 종전에는 빈 값이 "성공" 이었다.
#   섹션 실패 문장의 detail 에는 실패한 구성요소(parts=…)를 덧붙인다(종전 문장 · rc 는 그대로 앞에 남는다).
INTENDED_EXTRA_ERRORS.update({
    ("network", "net_interfaces_failed"): [{"section": "network", "message": "네트워크 정보 중 일부를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요.",
                                            "detail": "source=Get-NetAdapter,Get-NetRoute,Get-DnsClientServerAddress,Get-NetIPAddress; "
                                                      "cause=component_failed; parts=interfaces; interfaces=2; "
                                                      "error=interfaces: Get-NetIPAddress : WMI provider failure (fixture)"}],
    ("storage", "stor_volumes_failed"): [{"section": "storage", "message": "스토리지 정보 중 파일시스템(볼륨) 정보를 읽지 못했습니다. 대상 상태와 수집 로그를 확인하세요.",
                                          "detail": "source=Get-Volume; cause=component_failed; parts=volumes; filesystems=0; "
                                                    "error=Get-Volume threw (fixture)"}],
})
INTENDED_ERRORS_OVERRIDE = {
    ("network", "net_interfaces_failed_no_team"): [{"section": "network", "message": "네트워크 정보 수집에 실패했습니다. 대상 상태와 수집 로그를 확인하세요.",
                                                    "detail": "source=Get-NetIPAddress,Get-NetAdapter; cause=no_output; rc=1; parts=interfaces"}],
    ("network", "net_script_failed"): [{"section": "network", "message": "네트워크 정보 수집에 실패했습니다. 대상 상태와 수집 로그를 확인하세요.",
                                        "detail": "source=Get-NetIPAddress,Get-NetAdapter; cause=no_output; rc=1; parts=script"}],
}
INTENDED_CHANGED_KEYS = {("system", "windows | system | build fragment"): {"_errors_fragment"},
                         ("storage", "windows | storage | build fragment"): {"_errors_fragment"},
                         # 8차 R5: vmms 조회 실패를 "역할 없음" 으로 보지 않는다 · setup 실패를 권한 문제로 적지 않는다 · setup 실패 시 메모리 오류
                         ("system", "windows | system | determine hosting_type"): {"_w_hosting_type"},
                         ("system", "windows | system | build identifier diagnostics"): {"_w_id_diagnostics"},
                         ("memory", "windows | memory | build fragment"): {"_errors_fragment"},
                         ("network", "windows | network | build fragment"): {"_errors_fragment"}}
# 태스크 단위로 바뀐 키(set_fact 밖) — 식별자 진단의 문장 변수(vars)에 setup 실패 문장 2개를 더했다
INTENDED_CHANGED_TASK_KEYS = {("system", "windows | system | build identifier diagnostics"): {"vars"}}
# 그대로 둔 win_shell 중 의도해서 고친 줄 — 그 줄(앞부분으로 찾는다)과 PowerShell 주석 줄만 다를 수 있고 나머지 스크립트는 글자 그대로다.
#   2026-10-10 (C6): FC HBA PortSpeed 값맵 정정(4→10 · 8→4 · 16→8, 확인 못 한 64 · 128 은 null).
INTENDED_SHELL_LINES = {("storage", "windows | storage | initiator ports + HBA attrs"): ("$gbps = switch ($spd)",)}


def _shell_without(script: str, prefixes) -> list:
    """비교용 스크립트 — PowerShell 주석 줄과 의도해서 고친 줄을 뺀 나머지 줄."""
    out = []
    for line in script.splitlines():
        t = line.strip()
        if t.startswith("#") or any(t.startswith(p) for p in prefixes):
            continue
        out.append(line)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 1. 같은 입력 → 같은 fragment (종전 파일 vs 새 파일)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("section,scenario", _CASES, ids=[f"{s}-{fn.__name__}" for s, fn in _CASES])
def test_old_and_new_chains_render_identical_fragments(section, scenario):
    comps, facts, extra, rc = _scenario(scenario)
    old_frag, old_ctx = render_old(section, comps, facts, extra, rc)
    new_frag, new_ctx = render_new(section, comps, facts, extra, rc)
    assert old_frag is not None and new_frag is not None
    for key in FRAGMENT_KEYS:
        expected = old_frag[key]
        if key == "_errors_fragment":
            expected = list(expected or []) + INTENDED_EXTRA_ERRORS.get((section, scenario.__name__), [])
            expected = INTENDED_ERRORS_OVERRIDE.get((section, scenario.__name__), expected)
        assert new_frag[key] == expected, f"{section}/{scenario.__name__}: {key} 가 종전과 다르다"
    shared = shared_facts(old_ctx, new_ctx, facts)
    assert shared, "비교할 중간 변수가 없다 — 하네스가 체인을 끝까지 돌리지 못했다"
    for key in shared:
        if key in FRAGMENT_KEYS:
            continue  # 위에서 (의도한 차이를 넣어) 비교했다
        assert new_ctx[key] == old_ctx[key], f"{section}/{scenario.__name__}: 중간 변수 {key} 가 종전과 다르다"


def test_every_old_task_maps_to_exactly_one_component():
    """종전 win_shell 전부가 구성요소 하나에 대응한다 (20 = 11 + 합쳐서 사라진 9)."""
    total_old = 0
    for section in ("cpu", "hardware", "users", *OLD_TO_COMPONENT):
        text = old_text(section)
        if text is None:
            pytest.skip("git 이력 없음")
        names = [t["name"] for t in iter_tasks(yaml.safe_load(text)) if "ansible.windows.win_shell" in t]
        total_old += len(names)
        if section in OLD_TO_COMPONENT:
            expected = set(OLD_TO_COMPONENT[section]) | set(UNCHANGED_SHELL.get(section, ()))
            assert set(names) == expected, (section, names)
    assert total_old == 20


# ═══════════════════════════════════════════════════════════════════════════
# 2. 정규화 · fragment 태스크는 글자 그대로
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("section", list(OLD_TO_COMPONENT))
def test_downstream_tasks_are_unchanged(section):
    old = {t["name"]: t for t in iter_tasks(yaml.safe_load(require_old(section)))}
    new = {t["name"]: t for t in iter_tasks(yaml.safe_load(new_text(section)))}
    kept = [n for n, t in old.items()
            if "ansible.builtin.set_fact" in t or n in UNCHANGED_SHELL.get(section, ())]
    assert kept, section
    for name in kept:
        assert name in new, f"{section}: 종전 태스크 {name!r} 가 사라졌다"
        changed = INTENDED_CHANGED_KEYS.get((section, name), set())
        if changed:
            # 의도한 변경(errors[] 추가)만 허용 — 다른 키는 같고, 종전 문장은 새 식에 그대로 남는다
            nf = new[name]["ansible.builtin.set_fact"]
            of = old[name]["ansible.builtin.set_fact"]
            assert {k: v for k, v in nf.items() if k not in changed} == {k: v for k, v in of.items() if k not in changed}, name
            for k in changed:
                for msg in re.findall(r"'message':\s*'([^']+)'", of[k]):
                    assert msg in nf[k], (name, msg)
            task_changed = INTENDED_CHANGED_TASK_KEYS.get((section, name), set())
            assert ({k: v for k, v in new[name].items() if k not in ("timeout", "ansible.builtin.set_fact") and k not in task_changed}
                    == {k: v for k, v in old[name].items() if k != "ansible.builtin.set_fact" and k not in task_changed}), name
            for k in task_changed:
                assert isinstance(old[name].get(k), dict) and set(old[name][k].items()) <= set(new[name][k].items()), (name, k)
            continue
        lines = INTENDED_SHELL_LINES.get((section, name))
        if lines:
            ns, os_ = new[name]["ansible.windows.win_shell"], old[name]["ansible.windows.win_shell"]
            assert _shell_without(ns, lines) == _shell_without(os_, lines), f"{section}: {name!r} 의 의도한 줄 밖이 바뀌었다"
            assert all(any(l.strip().startswith(p) for l in ns.splitlines()) for p in lines), name
            assert ({k: v for k, v in new[name].items() if k not in ("timeout", "ansible.windows.win_shell")}
                    == {k: v for k, v in old[name].items() if k != "ansible.windows.win_shell"}), name
            continue
        # task-level `timeout`(Plan §6-3, 2026-10-03 GP-9) 은 hang 격리 키워드라 수집 내용과 무관하다 — 비교에서 뺀다
        assert {k: v for k, v in new[name].items() if k != "timeout"} == old[name], f"{section}: 종전 태스크 {name!r} 의 내용이 바뀌었다"
    # 종전 rescue (runtime) 도 그대로
    old_rescue = [t.get("rescue") for t in yaml.safe_load(require_old(section)) if isinstance(t, dict) and "rescue" in t]
    new_rescue = [t.get("rescue") for t in yaml.safe_load(new_text(section)) if isinstance(t, dict) and "rescue" in t]
    assert new_rescue == old_rescue


# ═══════════════════════════════════════════════════════════════════════════
# 3. 새 체인 단독 — 실장비 10.100.64.120 출력과 같다 (git 불필요)
# ═══════════════════════════════════════════════════════════════════════════
def test_new_chain_reproduces_120_memory():
    frag, _ = render_new("memory", **{k: v for k, v in mem_120().items()})
    assert frag["_data_fragment"]["memory"] == _evidence()["memory"]
    assert frag["_errors_fragment"] == [] and frag["_sections_collected_fragment"] == ["memory"]


def test_new_chain_reproduces_120_system():
    s = sys_120()
    frag, _ = render_new("system", s["comps"], s["facts"])
    ev = {k: v for k, v in _evidence()["system"].items() if k != "runtime"}
    got = frag["_data_fragment"]["system"]
    # NativeEnvironment 는 숫자뿐인 문자열을 숫자로 읽는다 (kernel) — 값 계약만 본다
    got = dict(got, kernel=str(got["kernel"]))
    assert got == ev
    assert frag["_errors_fragment"] == [] and frag["_sections_collected_fragment"] == ["system"]


def test_new_chain_reproduces_120_runtime():
    s = rt_120()
    frag, _ = render_new("runtime", s["comps"], s["facts"])
    assert frag["_data_fragment"]["system"]["runtime"] == _evidence()["system"]["runtime"]
    assert frag["_errors_fragment"] == []


def test_new_chain_reproduces_120_network():
    s = net_120()
    frag, _ = render_new("network", s["comps"], s["facts"], s["extra"])
    ev = _evidence()["network"]
    got = frag["_data_fragment"]["network"]
    for key in got:
        assert got[key] == ev[key], f"network.{key} 가 실장비 출력과 다르다"
    assert frag["_errors_fragment"] == [] and frag["_sections_collected_fragment"] == ["network"]


def test_new_chain_reproduces_120_storage():
    s = stor_120()
    frag, _ = render_new("storage", s["comps"], s["facts"], s["extra"])
    ev = _evidence()["storage"]
    got = frag["_data_fragment"]["storage"]
    for key in got:
        assert got[key] == ev[key], f"storage.{key} 가 실장비 출력과 다르다"
    assert frag["_errors_fragment"] == []


# ═══════════════════════════════════════════════════════════════════════════
# 4. 구성요소 실패 — 실패한 것만 실패, errors[] 는 종전 문장 · detail 그대로 (git 불필요)
# ═══════════════════════════════════════════════════════════════════════════
RUNTIME_MSG = "서버 기본 정보 중 운영 환경 정보를 수집하지 못했습니다. 대상 상태와 수집 로그를 확인하세요."


def test_firewall_component_failure_is_isolated():
    s = rt_firewall_throws()
    frag, ctx = render_new("runtime", s["comps"], s["facts"])
    rt = frag["_data_fragment"]["system"]["runtime"]
    assert rt["firewall_state"] is None and rt["firewall_profiles"] == []
    # 나머지 구성요소는 그대로 채워진다
    assert rt["timezone"] == "Asia/Seoul" and rt["ntp_synchronized"] is True
    assert rt["swap_total_mb"] == 1280 and len(rt["listening_ports"]) == 13
    assert frag["_errors_fragment"] == [{"section": "system", "message": RUNTIME_MSG,
                                         "detail": "scope=firewall; os=windows; cause=command_failed"}]
    assert frag["_sections_collected_fragment"] == ["system"]          # 시나리오 B — 섹션은 수집됨
    assert ctx["_w_rt_fw"]["rc"] == 1 and ctx["_w_rt_ntp"]["rc"] == 0


def test_all_runtime_components_fail_when_script_fails():
    s = rt_script_failed()
    frag, _ = render_new("runtime", s["comps"], s["facts"], script_rc=1)
    assert frag["_errors_fragment"][0]["detail"] == \
        "scope=timezone,ntp,firewall,listening_ports,pagefile; os=windows; cause=command_failed"
    rt = frag["_data_fragment"]["system"]["runtime"]
    assert rt["swap_total_mb"] is None and rt["timezone"] is None and rt["listening_ports"] == []


@pytest.mark.parametrize("scenario,section,detail", [
    (mem_total_failed, "memory", "source=Win32_PhysicalMemory; cause=no_output; fallback=os_visible; rc=1"),
    (mem_no_modules, "memory", "source=Win32_PhysicalMemory; cause=no_output; fallback=os_visible; rc=0"),
    (mem_script_failed, "memory", "source=Win32_PhysicalMemory,setup; cause=no_output; rc=1"),
    (sys_os_failed_no_facts, "system", "source=Win32_OperatingSystem; cause=no_output; rc=1"),
    (net_interfaces_failed_no_team, "network", "source=Get-NetIPAddress,Get-NetAdapter; cause=no_output; rc=1; parts=interfaces"),
    (stor_disks_failed_no_volumes, "storage", "source=Get-Volume,Win32_DiskDrive; cause=no_output; rc=1"),
])
def test_failure_detail_keeps_per_call_rc(scenario, section, detail):
    """detail 의 rc 는 그 구성요소가 따로 실행됐다면 냈을 값 (종전 태스크 rc 와 같다)."""
    comps, facts, extra, rc = _scenario(scenario)
    frag, _ = render_new(section, comps, facts, extra, rc)
    assert detail in [e["detail"] for e in frag["_errors_fragment"]], frag["_errors_fragment"]


def test_network_other_components_survive_interfaces_failure():
    s = net_interfaces_failed()
    frag, _ = render_new("network", s["comps"], s["facts"], s["extra"])
    net = frag["_data_fragment"]["network"]
    # 주소가 없으니 남는 인터페이스는 팀 보강이 만든 멤버 NIC 뿐이다 (종전과 같은 결과)
    assert [(i["name"], i.get("team_role")) for i in net["interfaces"]] == [("Ethernet1", "member"),
                                                                           ("Ethernet2", "member")]
    assert net["dns_servers"] == ["10.0.0.53"]                            # 원소 1개도 list
    assert [a["name"] for a in net["adapters"]] == ["Ethernet0", "Ethernet1", "Ethernet2"]
    assert {d["name"]: d["bond_master"] for d in net["driver_map"]}["Ethernet1"] == "Team1"
    assert [t["name"] for t in net["teams"]] == ["Team1"]


def test_two_nics_one_team_topology():
    s = net_two_nics_one_team()
    frag, _ = render_new("network", s["comps"], s["facts"], s["extra"])
    net = frag["_data_fragment"]["network"]
    by_name = {i["name"]: i for i in net["interfaces"]}
    assert by_name["Team1"]["team_role"] == "master" and by_name["Team1"]["team_members"] == ["Ethernet1", "Ethernet2"]
    assert by_name["Ethernet1"]["team_role"] == "member" and by_name["Ethernet2"]["team_master"] == "Team1"
    assert by_name["Ethernet0"]["is_primary"] is True
    assert net["default_gateways"] == [{"family": "ipv4", "address": "10.0.0.1"},
                                       {"family": "ipv6", "address": "fe80::1"}]
    assert [a["gateway"] for a in by_name["Ethernet0"]["addresses"]] == ["10.0.0.1", "fe80::1"]
    assert net["summary"] == {"groups": [{"speed_mbps": 10000, "link_type": None, "quantity": 1, "link_up_count": 1},
                                         {"speed_mbps": 50000, "link_type": None, "quantity": 1, "link_up_count": 1}]}


# ═══════════════════════════════════════════════════════════════════════════
# 5. split 태스크 계약
# ═══════════════════════════════════════════════════════════════════════════
def _split(section, doc_register):
    """section 파일의 parse document → split document 두 태스크만 돌린다."""
    tasks = {t["name"]: t for t in iter_tasks(yaml.safe_load(new_text(section)))}
    reg = MERGED_TASK[section]
    register = tasks[reg]["register"]
    ctx = {register: doc_register}
    for name in (f"windows | {section} | parse document", f"windows | {section} | split document"):
        sf = tasks[name]["ansible.builtin.set_fact"]
        ctx.update({k: render(v, ctx) for k, v in sf.items()})
    return ctx


@pytest.mark.parametrize("script_rc,ok,expected_rc", [(0, True, 0), (0, False, 1), (2, True, 2), (2, False, 2)])
def test_split_rc_rule(script_rc, ok, expected_rc):
    doc = {"firewall": {"ok": ok, "error": None if ok else "x", "rows": [], "data": None}}
    out = _split("runtime", {"stdout": json.dumps(doc) if script_rc == 0 else "", "rc": script_rc})
    assert out["_w_rt_fw"]["rc"] == expected_rc


def test_split_without_rc_leaves_rc_undefined():
    """register 에 rc 가 없으면 split 도 rc 를 만들지 않는다 (종전 `rc | default('none')` 의미 유지)."""
    doc = {"os": {"ok": True, "error": None, "rows": [], "data": {"caption": "x"}}}
    out = _split("system", {"stdout": json.dumps(doc)})
    assert "rc" not in out["_w_os_raw"]
    assert out["_w_os_raw"]["stdout_lines"] == [json.dumps({"caption": "x"})]


def test_split_missing_component_is_a_failed_call():
    out = _split("network", {"stdout": json.dumps({"meta": {"ok": True, "error": None, "rows": [], "data": None}}),
                             "rc": 0})
    assert out["_w_iface_raw"] == {"stdout": "", "stdout_lines": [], "rc": 1}
    assert out["_w_net_meta_raw"] == {"stdout": "", "stdout_lines": [], "rc": 0}


def test_split_wraps_single_row_object_and_drops_non_lists():
    """PS 5.1 이 원소 1개 배열을 객체로 접어도 행 1개로 본다. 문자열 / 숫자 rows 는 버린다."""
    row = {"drive": "C", "fs": "NTFS", "total": 1, "free": 1}
    doc = {"volumes": {"ok": True, "error": None, "rows": row, "data": None},
           "disks": {"ok": True, "error": None, "rows": "garbage", "data": None}}
    out = _split("storage", {"stdout": json.dumps(doc), "rc": 0})
    assert out["_w_vol_raw"]["stdout_lines"] == [json.dumps(row)]
    assert out["_w_disk_raw"]["stdout_lines"] == []


def test_split_ports_are_strings_like_the_old_lines():
    doc = {"ports": {"ok": True, "error": None, "rows": [135, 5985], "data": None}}
    out = _split("runtime", {"stdout": json.dumps(doc), "rc": 0})
    assert out["_w_rt_ports"]["stdout_lines"] == ["135", "5985"]


def test_split_memory_total_is_the_old_number_text():
    doc = {"total": {"ok": True, "error": None, "rows": [], "data": 65536}}
    out = _split("memory", {"stdout": json.dumps(doc), "rc": 0})
    assert out["_w_mem_raw"]["stdout"] == "65536"
    empty = _split("memory", {"stdout": json.dumps({"total": {"ok": True, "error": None, "rows": [], "data": None}}),
                              "rc": 0})
    assert empty["_w_mem_raw"]["stdout"] == "" and empty["_w_mem_raw"]["stdout_lines"] == []
