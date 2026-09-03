"""field_dictionary / sections.yml 선언 ↔ gather 가 실제로 내는 키 (2026-09-03).

전수 검수 C-8: "선언만 있고 안 나오는 필드 / 내는데 선언이 없는 채널" 을 잡는 장치가 없었다.
정적 대조로 최소 계약을 고정한다 — 값 계약은 test_gather_identity_render.py 가 맡는다.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
FD = yaml.safe_load((REPO / "schema" / "field_dictionary.yml").read_text(encoding="utf-8"))["fields"]
SECTIONS = yaml.safe_load((REPO / "schema" / "sections.yml").read_text(encoding="utf-8"))["sections"]
SUPPORTED = yaml.safe_load((REPO / "common" / "vars" / "supported_sections.yml").read_text(encoding="utf-8"))

LINUX_SYS = REPO / "os-gather" / "tasks" / "linux" / "gather_system.yml"
WIN_HW = REPO / "os-gather" / "tasks" / "windows" / "gather_hardware.yml"
WIN_STOR = REPO / "os-gather" / "tasks" / "windows" / "gather_storage.yml"
ESXI_SYS = REPO / "esxi-gather" / "tasks" / "normalize_system.yml"
ESXI_RT = REPO / "esxi-gather" / "tasks" / "collect_runtime.yml"

HW_KEYS = {"vendor", "model", "serial", "uuid", "bios_version", "bios_date"}


def _fragment_section(path: Path, section: str) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    tasks = []
    for t in doc:
        if isinstance(t, dict):
            tasks.append(t)
            tasks.extend(x for x in (t.get("block") or []) if isinstance(x, dict))
    for t in tasks:
        frag = (t.get("ansible.builtin.set_fact") or {}).get("_data_fragment")
        if isinstance(frag, dict) and isinstance(frag.get(section), dict):
            return frag[section]
    raise AssertionError(f"{path.name}: _data_fragment.{section} 미발견")


def test_hardware_is_declared_for_os_and_emitted_by_linux_and_windows():
    assert "os" in SECTIONS["hardware"]["channels"]
    assert "hardware" in SUPPORTED["channel_sections"]["os"]
    for adapter in sorted((REPO / "adapters" / "os").glob("*.yml")):
        caps = yaml.safe_load(adapter.read_text(encoding="utf-8"))["capabilities"]
        assert "hardware" in caps["sections_supported"], adapter.name
    for key in HW_KEYS:
        assert "os" in FD[f"hardware.{key}"]["channel"], key
    assert HW_KEYS <= set(_fragment_section(LINUX_SYS, "hardware")), "Linux 가 hardware 6 키를 내지 않는다 (B-05)"
    assert HW_KEYS <= set(_fragment_section(WIN_HW, "hardware"))


def test_system_hostname_declared_and_emitted_by_every_channel():
    for key in ("system.hostname", "system.fqdn"):
        assert set(FD[key]["channel"]) >= {"os", "esxi", "redfish"}, key
    assert {"hostname", "fqdn"} <= set(_fragment_section(LINUX_SYS, "system"))
    assert {"hostname", "fqdn"} <= set(_fragment_section(REPO / "os-gather" / "tasks" / "windows" / "gather_system.yml", "system"))
    assert {"hostname", "fqdn"} <= set(_fragment_section(ESXI_SYS, "system"))


def test_hosting_type_enum_covers_esxi_literal():
    assert "hypervisor" in FD["system.hosting_type"]["enum"]
    assert "esxi" in FD["system.hosting_type"]["channel"]
    assert _fragment_section(ESXI_SYS, "system")["hosting_type"] == "hypervisor"


def test_physical_disk_health_vocabulary_is_unified():
    assert FD["storage.physical_disks[].health"]["enum"] == ["OK", "Warning", "Critical"]
    text = WIN_STOR.read_text(encoding="utf-8")
    assert "'Healthy'   { 'OK' }" in text and "'Unhealthy' { 'Critical' }" in text
    assert "{ 'healthy' }" not in text, "Windows 가 소문자 'healthy' 를 다시 낸다 (B-18)"


def test_firewall_state_vocabulary_is_unified():
    assert FD["system.runtime.firewall_state"]["enum"] == ["active", "inactive"]
    rt = ESXI_RT.read_text(encoding="utf-8")
    assert "'active' if enabled_count > 0 else 'inactive'" in rt
    assert "'enabled' if enabled_count" not in rt


def test_cpu_speed_fields_declared_for_all_channels():
    assert set(FD["cpu.max_speed_mhz"]["channel"]) == {"redfish", "os", "esxi"}
    assert "turbo_max_mhz" in _fragment_section(REPO / "os-gather" / "tasks" / "linux" / "gather_cpu.yml", "cpu")
    assert "turbo_max_mhz" in _fragment_section(REPO / "os-gather" / "tasks" / "windows" / "gather_cpu.yml", "cpu")
    assert "turbo_max_mhz" in _fragment_section(ESXI_SYS, "cpu")


def test_no_ip_fallback_for_hostname_anywhere_in_gather_code():
    """B-01 회귀 가드: hostname 을 inventory_hostname / _ip / _e_ip 로 대체하는 표현식이 없어야 한다."""
    offenders = []
    for path in list((REPO / "os-gather").rglob("*.yml")) + list((REPO / "esxi-gather").rglob("*.yml")) \
            + list((REPO / "common" / "tasks" / "normalize").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or "esxi_hostname:" in line:
                # esxi_hostname 은 community.vmware 모듈 인자(API 조회 키) — envelope 에 나가지 않는다
                continue
            if re.search(r"'hostname':\s*(_ip|_e_ip|inventory_hostname)\b", line) \
                    or re.search(r"\b(hostname|fqdn):.*default\((_ip|_e_ip|inventory_hostname)\b", line):
                offenders.append(f"{path.relative_to(REPO)}:{i}")
    assert not offenders, "hostname/fqdn 에 IP 대체 표현식이 남아 있다: " + ", ".join(offenders)


def test_no_placeholder_zero_for_uptime_or_memory_totals():
    """B-14/B-32: uptime / total_mb 의 `default(0)` placeholder 금지."""
    offenders = []
    for path in list((REPO / "os-gather" / "tasks").rglob("*.yml")) + list((REPO / "esxi-gather" / "tasks").glob("*.yml")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if re.search(r"(uptime_seconds|total_mb|free_mb|visible_mb|installed_mb):.*default\(0\)", line):
                offenders.append(f"{path.relative_to(REPO)}:{i}")
    assert not offenders, ", ".join(offenders)
