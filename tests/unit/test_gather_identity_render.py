"""OS(Linux/Windows) / ESXi 식별 필드 — production Jinja2 표현식 렌더 회귀 (2026-09-03).

전수 검수(B-01/B-02/B-03/B-08/B-10/B-32/B-34)에서 확정한 계약을 **실제 task YAML 의 표현식**으로
고정한다. 합성 fixture 가 아니라 gather 파일에서 템플릿을 추출해 렌더한다.

계약
----
- system.hostname = 짧은 호스트명(첫 라벨), system.fqdn = hostname + 설정 도메인, 도메인 없으면 null.
  IP / inventory_hostname 대체 금지.
- Windows kernel 은 "None" 문자열이 아니라 null, version 은 DisplayVersion → Version 순.
- hosting_type 은 OEM 제조사 목록 없이 판정 (HypervisorPresent + Hyper-V 역할).
- ESXi cpu.max_speed_mhz 는 cpuInfo.hz(정격) 우선, uptime 0 은 null, architecture 는 CPU 제조사로 추론.
- Windows runtime ntp_*/swap_* 은 조회 실패 시 null (false / 0 단정 금지).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from identity_normalizer import normalize_mac, normalize_uuid  # noqa: E402

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
    env = NativeEnvironment()
    env.filters["regex_search"] = _regex_search
    env.filters["bool"] = _bool
    env.filters["combine"] = _combine
    env.filters["normalize_uuid"] = normalize_uuid
    env.filters["normalize_mac"] = normalize_mac
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
