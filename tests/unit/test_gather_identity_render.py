"""OS(Linux/Windows) / ESXi / Redfish 식별 필드 — production Jinja2 표현식 렌더 회귀 (2026-09-03, Redfish 2026-10-15).

전수 검수(B-01/B-02/B-03/B-08/B-10/B-32/B-34)에서 확정한 계약을 **실제 task YAML 의 표현식**으로
고정한다. 합성 fixture 가 아니라 gather 파일에서 템플릿을 추출해 렌더한다.

계약
----
- system.hostname = 짧은 호스트명(첫 라벨), system.fqdn = hostname + 설정 도메인, 도메인 없으면 null.
  IP / inventory_hostname 대체 금지.
- Redfish 는 원천 순서를 adapter `vendor_notes.hostname_priority` 로 정한다 — 키 없음: System.HostName,
  `bmc_first`(HPE CSUS 3200, 사용자 정책 2026-10-15): BMC NetworkProtocol 이름 → 없을 때만 System.HostName.
- Windows kernel 은 "None" 문자열이 아니라 null, version 은 DisplayVersion → Version 순.
- hosting_type 은 OEM 제조사 목록 없이 판정 (HypervisorPresent + Hyper-V 역할).
- ESXi cpu.max_speed_mhz 는 cpuInfo.hz(정격) 우선, uptime 0 은 null, architecture 는 CPU 제조사로 추론.
- Windows runtime ntp_*/swap_* 은 조회 실패 시 null (false / 0 단정 금지).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from identity_normalizer import dmi_sentinel_null, normalize_mac, normalize_uuid  # noqa: E402

LINUX_SYS = REPO / "os-gather" / "tasks" / "linux" / "gather_system.yml"
WIN_SYS = REPO / "os-gather" / "tasks" / "windows" / "gather_system.yml"
WIN_RT = REPO / "os-gather" / "tasks" / "windows" / "gather_runtime.yml"
ESXI_SYS = REPO / "esxi-gather" / "tasks" / "normalize_system.yml"


def _regex_search(value, pattern, *groups, **_kw):
    """ansible.builtin.regex_search 최소 호환 — '\\1' 인자가 있으면 그룹 list 반환."""
    m = re.search(pattern, str(value))
    if not m:
        return None
    if groups:
        return [m.group(int(g.lstrip("\\"))) for g in groups]
    return m.group(0)


def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _combine(d, other, recursive=False):
    r = dict(d or {})
    r.update(other or {})
    return r


def _env():
    from serial_normalizer import normalize_os_serial   # filter_plugins (sys.path) — Redfish hardware.serial 도 2026-10-17 부터 쓴다

    env = NativeEnvironment()
    env.filters["regex_search"] = _regex_search
    env.filters["bool"] = _bool
    env.filters["combine"] = _combine
    env.filters["normalize_uuid"] = normalize_uuid
    env.filters["normalize_mac"] = normalize_mac
    env.filters["dmi_sentinel_null"] = dmi_sentinel_null
    env.filters["normalize_os_serial"] = normalize_os_serial
    env.filters["from_json"] = json.loads
    return env


def _tasks(path: Path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for t in doc:
        if not isinstance(t, dict):
            continue
        out.append(t)
        for sub in (t.get("block") or []):
            if isinstance(sub, dict):
                out.append(sub)
    return out


def _task(path: Path, name_sub: str) -> dict:
    for t in _tasks(path):
        if name_sub in str(t.get("name", "")) and "ansible.builtin.set_fact" in t:
            return t
    raise AssertionError(f"{path.name}: set_fact task '{name_sub}' 미발견")


def _render(tmpl, ctx):
    if not isinstance(tmpl, str):
        return tmpl
    return _env().from_string(tmpl).render(**ctx)


# ═══════════════════════════════════════════════════════════════════════════
# Linux — hostname / fqdn
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def linux_host_task():
    return _task(LINUX_SYS, "resolve hostname / fqdn")["ansible.builtin.set_fact"]


@pytest.mark.parametrize("ctx,short,fqdn", [
    # R760 bare-metal 참조 캡처: nodename 만 있고 도메인 없음 → fqdn null (IP 아님)
    ({"ansible_nodename": "r760-6", "ansible_domain": "", "_l_fb": {}}, "r760-6", None),
    # 같은 VM 을 python / raw 어느 경로로 봐도 같은 값 (종전: 'localhost.localdomain' vs 'localhost')
    ({"ansible_nodename": "localhost.localdomain", "_l_fb": {}}, "localhost", "localhost.localdomain"),
    ({"_l_fb": {"NODENAME": "localhost.localdomain", "DOMAIN": ""}}, "localhost", "localhost.localdomain"),
    # 도메인은 설정값(hostname -d / ansible_domain) 에서
    ({"ansible_nodename": "web01", "ansible_domain": "corp.example.com", "_l_fb": {}}, "web01", "web01.corp.example.com"),
    ({"_l_fb": {"NODENAME": "db01", "DOMAIN": "lab"}}, "db01", "db01.lab"),
    # 아무것도 없으면 둘 다 null — inventory_hostname(IP) 로 채우지 않는다
    ({"_l_fb": {}, "inventory_hostname": "10.100.64.161"}, None, None),
])
def test_linux_hostname_and_fqdn(linux_host_task, ctx, short, fqdn):
    got_short = _render(linux_host_task["_l_hostname_short"], ctx)
    got_fqdn = _render(linux_host_task["_l_fqdn"], ctx)
    assert got_short == short
    assert got_fqdn == fqdn
    assert got_short != "10.100.64.161" and got_fqdn != "10.100.64.161"


# ═══════════════════════════════════════════════════════════════════════════
# Windows — hostname / fqdn / kernel / version / architecture / uptime / hosting_type
# ═══════════════════════════════════════════════════════════════════════════
def _win_system_fragment() -> dict:
    return _task(WIN_SYS, "windows | system | build fragment")["ansible.builtin.set_fact"]["_data_fragment"]["system"]


def _win_resolve(ctx: dict) -> dict:
    sf = _task(WIN_SYS, "resolve hostname + status")["ansible.builtin.set_fact"]
    out = dict(ctx)
    out["_w_hostname_short"] = _render(sf["_w_hostname_short"], out)
    out["_w_domain"] = _render(sf["_w_domain"], out)
    out["_w_sys_ok"] = _render(sf["_w_sys_ok"], out)
    return out


def test_windows_identity_from_reference_capture():
    """win2022 참조 캡처(horizon-cs.gooddi.lab) 값으로 렌더."""
    ctx = _win_resolve({
        "_w_os_data": {"caption": "Microsoft Windows Server 2022 Standard Evaluation",
                       "hostname": "horizon-cs", "domain": "gooddi.lab", "build": "20348",
                       "rel_id": "21H2", "version": "10.0.20348", "arch": "64-bit", "uptime": 600},
        "ansible_hostname": "horizon-cs", "ansible_fqdn": "horizon-cs.gooddi.lab",
        "ansible_architecture": "64-bit", "ansible_architecture2": "x86_64",
        "ansible_uptime_seconds": 574,
    })
    frag = _win_system_fragment()
    assert ctx["_w_hostname_short"] == "horizon-cs"
    assert _render(frag["hostname"], ctx) == "horizon-cs"
    assert _render(frag["fqdn"], ctx) == "horizon-cs.gooddi.lab"
    # NativeEnvironment 는 단일 숫자 문자열을 literal_eval 한다 — 값 계약만 본다 (production 은 `| string` 로 문자열 고정)
    assert str(_render(frag["kernel"], ctx)) == "20348"
    assert _render(frag["version"], ctx) == "21H2"
    assert _render(frag["architecture"], ctx) == "x86_64"
    assert _render(frag["uptime_seconds"], ctx) == 574
    assert ctx["_w_sys_ok"] is True


def test_windows_identity_nulls_are_null_not_placeholders():
    """B-34: build null → kernel null ("None" 문자열 금지), rel_id null → Version 사용, 도메인 없음 → fqdn null."""
    ctx = _win_resolve({
        "_w_os_data": {"caption": "Microsoft Windows Server 2019 Standard", "hostname": "WIN-1",
                       "domain": None, "build": None, "rel_id": None, "version": "10.0.17763", "arch": "64-bit"},
        "ansible_hostname": "WIN-1", "ansible_fqdn": "WIN-1", "ansible_architecture": "64-bit",
    })
    frag = _win_system_fragment()
    assert _render(frag["hostname"], ctx) == "WIN-1"
    assert _render(frag["fqdn"], ctx) is None
    assert _render(frag["kernel"], ctx) is None
    assert _render(frag["version"], ctx) == "10.0.17763"
    assert _render(frag["architecture"], ctx) == "x86_64"
    assert _render(frag["uptime_seconds"], ctx) is None


def test_windows_arm64_is_not_reported_as_x86_64():
    ctx = _win_resolve({"_w_os_data": {"caption": "Windows", "hostname": "ARM1", "arch": "ARM 64-bit Processor"},
                        "ansible_architecture": "ARM 64-bit Processor"})
    assert _render(_win_system_fragment()["architecture"], ctx) == "aarch64"


@pytest.mark.parametrize("hosting,expected", [
    ({"Model": "VMware Virtual Platform", "Manufacturer": "VMware, Inc.", "HypervisorPresent": "True", "HyperVRole": "False"}, "virtual"),
    ({"Model": "Virtual Machine", "Manufacturer": "Microsoft Corporation", "HypervisorPresent": "True", "HyperVRole": "False"}, "virtual"),
    # OEM 목록에 없는 제조사 / 마침표 없는 표기도 HypervisorPresent=False 면 물리 서버
    ({"Model": "Some Rack Server", "Manufacturer": "Contoso Inc", "HypervisorPresent": "False", "HyperVRole": "False"}, "baremetal"),
    # Hyper-V 호스트: HypervisorPresent=True 이지만 역할이 켜져 있으면 물리 (종전: unknown)
    ({"Model": "Some Rack Server", "Manufacturer": "Contoso Inc", "HypervisorPresent": "True", "HyperVRole": "True"}, "baremetal"),
    # 하이퍼바이저 위인데 VM 신호 문자열이 없는 게스트
    ({"Model": "Standard PC (Q35 + ICH9, 2009)", "Manufacturer": "QEMU", "HypervisorPresent": "True", "HyperVRole": "False"}, "virtual"),
    ({}, "unknown"),
])
def test_windows_hosting_type_without_oem_list(hosting, expected):
    tmpl = _task(WIN_SYS, "determine hosting_type")["ansible.builtin.set_fact"]["_w_hosting_type"]
    assert _render(tmpl, {"_w_hosting": hosting}) == expected


# ═══════════════════════════════════════════════════════════════════════════
# Windows runtime — tri-state (조회 실패 = null)
# ═══════════════════════════════════════════════════════════════════════════
def _win_runtime() -> dict:
    return _task(WIN_RT, "windows | runtime | merge fragment")["ansible.builtin.set_fact"]["_data_fragment"]["system"]["runtime"]


def test_windows_runtime_tristate():
    rt = _win_runtime()
    ok = {"_w_rt_ntp_obj": {"w32time_running": True, "synced": True}, "_w_rt_fw_list": [{"enabled": True}],
          "_w_rt_pagefile_ok": True, "_w_rt_pagefile_list": [{"size_mb": 4096, "used_mb": 100}]}
    assert _render(rt["ntp_active"], ok) is True
    assert _render(rt["ntp_synchronized"], ok) is True
    assert _render(rt["swap_total_mb"], ok) == 4096
    assert _render(rt["swap_used_mb"], ok) == 100
    assert _render(rt["swap_free_mb"], ok) == 3996

    failed = {"_w_rt_ntp_obj": {}, "_w_rt_fw_list": [], "_w_rt_pagefile_ok": False, "_w_rt_pagefile_list": []}
    assert _render(rt["ntp_active"], failed) is None
    assert _render(rt["ntp_synchronized"], failed) is None
    assert _render(rt["firewall_state"], failed) is None
    assert _render(rt["swap_total_mb"], failed) is None
    assert _render(rt["swap_used_mb"], failed) is None
    assert _render(rt["swap_free_mb"], failed) is None

    local_clock = {"_w_rt_ntp_obj": {"w32time_running": False, "synced": False}}
    assert _render(rt["ntp_active"], local_clock) is False
    assert _render(rt["ntp_synchronized"], local_clock) is False


def test_windows_runtime_single_implementation():
    """B-31: gather_system 은 더 이상 system.runtime 을 만들지 않는다 (이중 구현 → 덮어쓰기 재발 방지)."""
    frag = _win_system_fragment()
    assert "runtime" not in frag
    rescue = next(t for t in yaml.safe_load(WIN_RT.read_text(encoding="utf-8")) if isinstance(t, dict) and t.get("rescue"))
    rt = rescue["rescue"][0]["ansible.builtin.set_fact"]["_data_fragment"]["system"]["runtime"]
    assert set(rt) >= {"timezone", "ntp_active", "ntp_synchronized", "firewall_tool", "firewall_state",
                       "listening_ports", "swap_total_mb", "swap_used_mb", "swap_free_mb"}
    assert rt["ntp_active"] is None and rt["swap_total_mb"] is None and rt["firewall_state"] is None


# ═══════════════════════════════════════════════════════════════════════════
# ESXi — hostname / fqdn / cpu base clock / uptime / architecture
# ═══════════════════════════════════════════════════════════════════════════
def _esxi_resolve(ctx: dict) -> dict:
    out = dict(ctx)
    ident = _task(ESXI_SYS, "derive identity")["ansible.builtin.set_fact"]
    out["_e_sys_short"] = _render(ident["_e_sys_short"], out)
    out["_e_sys_domain"] = _render(ident["_e_sys_domain"], out)
    cpu = _task(ESXI_SYS, "derive cpu/uptime")["ansible.builtin.set_fact"]
    for key in ("_e_sys_fqdn", "_e_cpu_manufacturer", "_e_cpu_base_mhz", "_e_arch", "_e_uptime"):
        out[key] = _render(cpu[key], out)
    return out


BRAND = "Intel(R) Xeon(R) CPU E5-2699 v4 @ 2.20GHz"


def test_esxi_identity_from_host_info():
    """참조 pyvmomi dump(esxi01, cpuMhz=2195, domainName='') 와 같은 입력."""
    ctx = _esxi_resolve({
        "_e_raw_host": {"hostname": "esxi01", "domain_name": None, "cpu_mhz": 2195, "cpu_vendor": "intel", "uptime_seconds": 12345},
        "_e_raw_facts": {"ansible_hostname": "esxi01", "ansible_processor": BRAND},
        "_e_raw_dns": {},
    })
    assert ctx["_e_sys_short"] == "esxi01"
    assert ctx["_e_sys_domain"] is None
    assert ctx["_e_sys_fqdn"] is None
    assert ctx["_e_cpu_base_mhz"] == 2195          # 종전: 브랜드 문자열 2200
    assert ctx["_e_arch"] == "x86_64"
    assert ctx["_e_uptime"] == 12345
    assert ctx["_e_cpu_manufacturer"] == "Intel"


def test_esxi_identity_fallbacks_when_host_info_missing():
    """host_info 부재 → dns_info 도메인 / 브랜드 문자열 / uptime 0 은 null."""
    ctx = _esxi_resolve({
        "_e_raw_host": {},
        "_e_raw_facts": {"ansible_hostname": "esxi02", "ansible_processor": BRAND, "ansible_uptime": 0},
        "_e_raw_dns": {"esxi02": {"domain_name": "lab.local", "ip_address": ["10.0.0.53"]}},
    })
    assert ctx["_e_sys_short"] == "esxi02"
    assert ctx["_e_sys_domain"] == "lab.local"
    assert ctx["_e_sys_fqdn"] == "esxi02.lab.local"
    assert ctx["_e_cpu_base_mhz"] == 2200
    assert ctx["_e_uptime"] is None
    assert ctx["_e_arch"] == "x86_64"


def test_esxi_identity_all_missing_is_null_not_ip():
    ctx = _esxi_resolve({"_e_raw_host": {}, "_e_raw_facts": {}, "_e_raw_dns": {}, "_e_ip": "10.100.64.1"})
    assert ctx["_e_sys_short"] is None and ctx["_e_sys_fqdn"] is None
    assert ctx["_e_cpu_base_mhz"] is None and ctx["_e_arch"] is None and ctx["_e_uptime"] is None


def test_esxi_hosting_type_is_hypervisor_and_runtime_keys_seeded():
    frag = _task(ESXI_SYS, "esxi | normalize system | build fragment")["ansible.builtin.set_fact"]["_data_fragment"]
    assert frag["system"]["hosting_type"] == "hypervisor"
    assert frag["cpu"]["turbo_max_mhz"] is None
    assert frag["system"]["runtime"]["ntp_synchronized"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Linux cpu — 터보가 정격보다 낮으면 null (실측 build #194: VMware SMBIOS Max Speed 2093 < 2200)
# ═══════════════════════════════════════════════════════════════════════════
LINUX_CPU = REPO / "os-gather" / "tasks" / "linux" / "gather_cpu.yml"


@pytest.mark.parametrize("base,turbo,expected", [
    (2400, 4100, 4100),   # R760 실측: 정격 2400 / 터보 4100
    (2200, 2093, None),   # VM 실측: SMBIOS Max Speed 가 정격보다 낮음 → 값 아님
    (None, 3000, 3000),   # 정격을 모르면 터보는 그대로
    (2200, None, None),
])
def test_linux_turbo_below_base_is_null(base, turbo, expected):
    frag = _task(LINUX_CPU, "linux | cpu | build fragment")["ansible.builtin.set_fact"]["_data_fragment"]["cpu"]
    ctx = {"_l_cpu_base_mhz": base, "_l_cpu_turbo_mhz": turbo, "_l_cpu_model": "x", "_l_cpu_sockets": 1,
           "_l_cpu_cps": 1, "_l_cpu_manufacturer": "Intel", "_l_cpu_l2_kb": None, "_l_cpu_l3_kb": None}
    assert _render(frag["turbo_max_mhz"], ctx) == expected
    groups = _render(frag["summary"], ctx)["groups"]
    assert groups[0]["turbo_max_mhz"] == expected


def _regex_replace(value, pattern, repl="", *_a, **_k):
    return re.sub(pattern, repl, str(value))


@pytest.mark.parametrize("dmi_lines,base,turbo", [
    (["DMI_CUR_MHZ=2400", "DMI_MAX_MHZ=4100"], 2400, 4100),   # R760 실측
    (["DMI_CUR_MHZ=2200", "DMI_MAX_MHZ=30000"], 2200, None),  # VMware 가상 SMBIOS 자리표시자 (build #197)
    (["DMI_CUR_MHZ=0", "DMI_MAX_MHZ=0"], None, None),
    ([], None, None),
])
def test_linux_smbios_clock_fallback_plausibility(dmi_lines, base, turbo):
    """cpufreq·브랜드 문자열이 없을 때 SMBIOS Current/Max Speed 를 쓰되 100~10000 MHz 만 인정한다."""
    sf = _task(LINUX_CPU, "linux | cpu | compute")["ansible.builtin.set_fact"]
    env = _env()
    env.filters["regex_replace"] = _regex_replace
    ctx = {"_l_cpu_parsed": {"CPU_MODEL": "INTEL(R) XEON(R) SILVER 4510"}, "_l_cpu_dmi_raw": {"stdout_lines": dmi_lines}}
    assert env.from_string(sf["_l_cpu_base_mhz"]).render(**ctx) == base
    assert env.from_string(sf["_l_cpu_turbo_mhz"]).render(**ctx) == turbo


# ═══════════════════════════════════════════════════════════════════════════
# 실장비 검증(2026-09-03, Jenkins #190~#199)에서만 드러난 항목의 회귀 잠금
# ═══════════════════════════════════════════════════════════════════════════
WIN_NET = REPO / "os-gather" / "tasks" / "windows" / "gather_network.yml"
ESXI_NET = REPO / "esxi-gather" / "tasks" / "normalize_network.yml"


def test_windows_team_member_mac_is_normalized_at_source():
    """L2 (build #190): 팀 멤버 NIC 는 팀 토폴로지 보강(WADP 보조 맵)의 MAC 이 그대로 나간다 —
    PowerShell emit 에서 소문자 colon 으로 맞춰야 interfaces[] / teams[].members[] 가 정규형이 된다."""
    teaming = next(t for t in _tasks(WIN_NET) if "teaming (LBFO + SET)" in str(t.get("name", "")))
    ps = teaming["ansible.windows.win_shell"]
    wadp = next(line for line in ps.splitlines() if "Emit 'WADP'" in line or ("mac=" in line and "MacAddress" in line))
    body = ps[ps.index("Emit 'WADP'"):ps.index("status=[string]$a.Status")]
    assert ".Replace('-',':').ToLower()" in body, "WADP 보조 맵의 MAC 이 다시 원문(대시·대문자)으로 나간다 (build #190 회귀)"
    # interfaces[] 본류도 normalize_mac 을 통과한다
    norm = _task(WIN_NET, "windows | network | normalize interfaces")["ansible.builtin.set_fact"]["_w_norm_interfaces"]
    assert "| normalize_mac" in norm


def test_windows_ipv6_zone_index_is_stripped():
    """L3 (build #190): Windows link-local 은 `fe80::…%<ifindex>` 로 온다 — 주소 값에서 zone 을 뗀다."""
    tmpl = _task(WIN_NET, "windows | network | normalize interfaces")["ansible.builtin.set_fact"]["_w_norm_interfaces"]
    lines = [
        json.dumps({"id": "Ethernet0", "name": "Ethernet0", "description": "vmxnet3 Ethernet Adapter #6",
                    "interface_index": 9, "mac": "00-50-56-84-CB-C9", "mtu": 1500, "speed_mbps": 10000, "status": "Up",
                    "is_primary": True, "family": "ipv6", "address": "fe80::3bfa:737e:b64b:84d5%9", "prefix": 64, "gateway": None}),
        json.dumps({"id": "Ethernet0", "name": "Ethernet0", "description": "vmxnet3 Ethernet Adapter #6",
                    "interface_index": 9, "mac": "00-50-56-84-CB-C9", "mtu": 1500, "speed_mbps": 10000, "status": "Up",
                    "is_primary": True, "family": "ipv4", "address": "10.100.64.120", "prefix": 24, "gateway": "10.100.64.254"}),
    ]
    out = _render(tmpl, {"_w_iface_raw": {"stdout_lines": lines}})
    assert len(out) == 1
    iface = out[0]
    assert iface["mac"] == "00:50:56:84:cb:c9"
    assert iface["id"] == "Ethernet0" and iface["description"] == "vmxnet3 Ethernet Adapter #6"
    assert [a["family"] for a in iface["addresses"]] == ["ipv4", "ipv6"]          # IPv4 먼저
    v6 = iface["addresses"][1]
    assert v6["address"] == "fe80::3bfa:737e:b64b:84d5" and "%" not in v6["address"]
    assert v6["scope"] == "link" and v6["prefix_length"] == 64
    assert iface["addresses"][0]["gateway"] == "10.100.64.254" and iface["addresses"][0]["subnet_mask"] == "255.255.255.0"


def test_esxi_management_vmk_link_status_from_connection_evidence():
    """L4 (build #191): vmware_host_facts 는 vmk 링크 상태를 주지 않는다 — 수집에 쓴 IP 를 가진 vmk 는 up,
    나머지는 unknown (down 으로 단정하지 않는다). is_primary 는 게이트웨이 서브넷으로 판정."""
    tmpl = _task(ESXI_NET, "esxi | normalize network | build interfaces")["ansible.builtin.set_fact"]["_e_norm_interfaces"]
    ctx = {
        "_e_raw_facts": {
            "ansible_interfaces": ["vmk0", "vmk1"],
            "ansible_vmk0": {"ipv4": {"address": "10.100.64.1", "netmask": "255.255.255.0"}, "macaddress": "70:DF:2F:66:F7:D6", "mtu": 1500},
            "ansible_vmk1": {"ipv4": {"address": "192.168.10.5", "netmask": "255.255.255.0"}, "macaddress": "00:50:56:aa:bb:cc", "mtu": 9000},
        },
        "_e_ip": "10.100.64.1", "_e_default_gw": "10.100.64.254", "_e_default_gw6": None, "_e_gw_device": None,
        "_e_raw_host": {"vnics": [{"device": "vmk0", "ipv6": [{"address": "fe80::72df:2fff:fe66:f7d6", "prefix_length": 64}]}]},
    }
    out = {i["name"]: i for i in _render(tmpl, ctx)}
    assert out["vmk0"]["link_status"] == "up" and out["vmk0"]["is_primary"] is True
    assert out["vmk0"]["mac"] == "70:df:2f:66:f7:d6"
    assert out["vmk0"]["addresses"][0]["gateway"] == "10.100.64.254"
    assert out["vmk0"]["addresses"][1]["family"] == "ipv6" and out["vmk0"]["addresses"][1]["scope"] == "link"
    assert out["vmk1"]["link_status"] == "unknown" and out["vmk1"]["is_primary"] is False
    assert out["vmk1"]["addresses"][0]["gateway"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Redfish — hostname / fqdn (2026-10-15). 원천 순서는 adapter vendor_notes.hostname_priority
# ═══════════════════════════════════════════════════════════════════════════
REDFISH_NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
CSUS_ADAPTER = {"adapter_id": "redfish_hpe_csus_3200", "vendor_notes": {"hostname_priority": "bmc_first"}}
PLAIN_ADAPTER = {"adapter_id": "redfish_dell_idrac9", "vendor_notes": {}}


def _redfish_identity(sys_hostname, bmc, adapter):
    """normalize_standard.yml 의 두 태스크를 순서대로 렌더 → (system.hostname, system.fqdn)."""
    ctx = {"_rf_d_system": {"hostname": sys_hostname}, "_rf_d_bmc": bmc, "_selected_adapter": adapter}
    src = _task(REDFISH_NORM, "system hostname source")["ansible.builtin.set_fact"]
    ctx["_rf_sys_hostname_raw"] = _render(src["_rf_sys_hostname_raw"], ctx)
    ident = _task(REDFISH_NORM, "system hostname / fqdn")["ansible.builtin.set_fact"]
    return _render(ident["_rf_sys_hostname_short"], ctx), _render(ident["_rf_sys_fqdn"], ctx)


@pytest.mark.parametrize("sys_h,bmc_h,short,fqdn", [
    # adapter 키가 없으면 System.HostName 만 본다 — BMC 이름 대체는 종전처럼 build_output 체인 몫
    (None, "RMC7CA62A413692", None, None),
    ("DELL01", "iDRAC-J0KV603", "DELL01", None),                          # Dell R740 실측 — 도메인 없음 → fqdn null
    ("r760-1.gooddi.lab", None, "r760-1", "r760-1.gooddi.lab"),            # Dell R760 실측(tests/reference) — 도메인 포함
    ("test0004.hynix.com", None, "test0004", "test0004.hynix.com"),        # HPE iLO6 실측(tests/reference)
    ("", "ILOSGHD3KHHRP", None, None),                                     # HPE DL380 실측 — 빈 문자열
    ("   ", None, None, None),
    (" web01 ", None, "web01", None),
    (123, None, None, None),                                               # 비문자열은 없는 값
    ({"x": 1}, None, None, None),
    ("host.", None, "host", None),                                         # 도메인부가 비면 fqdn null
])
def test_redfish_hostname_default_order(sys_h, bmc_h, short, fqdn):
    assert _redfish_identity(sys_h, {"network_hostname": bmc_h}, PLAIN_ADAPTER) == (short, fqdn)


@pytest.mark.parametrize("sys_h,bmc_h,short,fqdn", [
    ("svu703327-net7", "ycgsfaibap01", "ycgsfaibap01", None),             # 사용자 사이트 실측 (2026-10-15)
    ("svu703327-net7", "ycgsfaibap01.corp.example", "ycgsfaibap01", "ycgsfaibap01.corp.example"),  # RMC FQDN → 짧은 이름 + fqdn
    ("svu703327-net7", None, "svu703327-net7", None),                      # RMC 이름 없음 → Partition 대체
    ("svu703327-net7", "  ", "svu703327-net7", None),
    (None, "RMC7CA62A413692", "RMC7CA62A413692", None),                    # 2026-06 캡처 node01 (Partition null)
    ("m10mesdb11", "M10MESDB11-RMC", "M10MESDB11-RMC", None),              # 2026-06 캡처 node03 — Partition 값이 있어도 RMC 우선
    (None, None, None, None),
])
def test_redfish_hostname_csus_bmc_first(sys_h, bmc_h, short, fqdn):
    assert _redfish_identity(sys_h, {"network_hostname": bmc_h}, CSUS_ADAPTER) == (short, fqdn)


@pytest.mark.parametrize("value,expected", [
    ("bmc_first", "ycgsfaibap01"), ("BMC_FIRST", "ycgsfaibap01"),
    ("system_first", "svu703327-net7"), ("unknown", "svu703327-net7"), (None, "svu703327-net7"), ("", "svu703327-net7"),
])
def test_redfish_hostname_priority_values(value, expected):
    adapter = {"adapter_id": "x", "vendor_notes": {"hostname_priority": value}}
    assert _redfish_identity("svu703327-net7", {"network_hostname": "ycgsfaibap01"}, adapter)[0] == expected


def test_redfish_hostname_bmc_first_without_bmc_section():
    """bmc 수집 실패(`_rf_d_bmc` = None) · adapter 미선택이어도 깨지지 않고 Partition 이름으로 간다."""
    assert _redfish_identity("svu703327-net7", None, CSUS_ADAPTER) == ("svu703327-net7", None)
    assert _redfish_identity("svu703327-net7", {"network_hostname": "ycgsfaibap01"}, {}) == ("svu703327-net7", None)


def test_redfish_fragment_wiring():
    """요구 3 · 4 · 5: system.hostname/fqdn 은 정한 값, bmc 와 multi_node 는 원본 통과."""
    frag = _task(REDFISH_NORM, "build standard fragment")["ansible.builtin.set_fact"]["_data_fragment"]
    assert frag["system"]["hostname"] == "{{ _rf_sys_hostname_short | default(none) }}"
    assert frag["system"]["fqdn"] == "{{ _rf_sys_fqdn | default(none) }}"
    assert frag["bmc"] == "{{ _rf_d_bmc_clean }}"
    assert frag["multi_node"] == "{{ _rf_raw_collect.multi_node | default(none) }}"


# ═══════════════════════════════════════════════════════════════════════════
# Redfish — hardware.serial nPartition 접미사 (2026-10-17 사용자 결정, CSUS 3200 만 — OS 채널과 같은 필터 · 같은 세 조건)
# ═══════════════════════════════════════════════════════════════════════════
def _redfish_hardware_serial(system):
    frag = _task(REDFISH_NORM, "build standard fragment")["ansible.builtin.set_fact"]["_data_fragment"]
    return _render(frag["hardware"]["serial"], {"_rf_d_system": system})


@pytest.mark.parametrize("system,expected", [
    # real_hpe_csus3200 모듈 golden 의 data.system 값 (manufacturer HPE · model Compute Scale-up Server 3200 · serial SGHD3TLNDD-000)
    ({"manufacturer": "HPE", "model": "Compute Scale-up Server 3200", "serial": "SGHD3TLNDD-000"}, "SGHD3TLNDD"),
    ({"manufacturer": "HPE", "model": "Compute Scale-up Server 3200", "serial": "SGHD3TLNDD-001"}, "SGHD3TLNDD"),
    ({"manufacturer": "Hewlett Packard Enterprise", "model": "HPE Compute Scale-up Server 3200", "serial": "SGHD3TLNDD-002"}, "SGHD3TLNDD"),
    ({"manufacturer": "HPE", "model": "ProLiant DL380 Gen11", "serial": "CZ12345678-000"}, "CZ12345678-000"),   # ProLiant — 원문
    ({"manufacturer": "HPE", "model": "Superdome Flex 280", "serial": "SGH0000000-000"}, "SGH0000000-000"),    # Superdome Flex — 결정 범위 밖
    ({"manufacturer": "Dell Inc.", "model": "PowerEdge R760", "serial": "ABCDEF-000"}, "ABCDEF-000"),
    ({"manufacturer": "Lenovo", "model": "ThinkSystem SR650", "serial": "J902E57T"}, "J902E57T"),
    ({"model": "Compute Scale-up Server 3200", "serial": "SGHD3TLNDD-000"}, "SGHD3TLNDD-000"),                 # manufacturer 없음 → fail-safe
    ({"manufacturer": "HPE", "serial": "SGHD3TLNDD-000"}, "SGHD3TLNDD-000"),                                    # model 없음 → fail-safe
    ({"manufacturer": "HPE", "model": "Compute Scale-up Server 3200", "serial": "SGHD3TLNDD-ABC"}, "SGHD3TLNDD-ABC"),
    ({"manufacturer": "HPE", "model": "Compute Scale-up Server 3200", "serial": None}, None),
    ({"manufacturer": "HPE", "model": "Compute Scale-up Server 3200"}, None),
])
def test_redfish_hardware_serial_strips_csus_npar_suffix_only(system, expected):
    assert _redfish_hardware_serial(system) == expected


def test_redfish_hardware_serial_uses_the_os_filter():
    frag = _task(REDFISH_NORM, "build standard fragment")["ansible.builtin.set_fact"]["_data_fragment"]
    assert "normalize_os_serial(" in frag["hardware"]["serial"], "OS 채널과 같은 필터 하나로 — 별도 규칙을 두지 않는다"
    assert frag["multi_node"] == "{{ _rf_raw_collect.multi_node | default(none) }}", "파티션 원본은 그대로"
