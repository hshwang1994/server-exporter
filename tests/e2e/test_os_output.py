"""OS-01, OS-04: OS 채널 baseline 핵심 필드 회귀 검증.

검증 수준:
  1. 공통 JSON 구조 (최상위 키, schema_version, meta.adapter_id)
  2. 필수 섹션 존재
  3. 핵심 필드 존재 (OS 채널 기준)
  4. adapter_id 기대값 일치
"""

from conftest import (
    assert_array_element_fields,
    assert_channel_critical_fields,
    assert_common_structure,
    assert_correlation_fields,
    assert_correlation_host_ip,
    OS_ARRAY_FIELDS,
    OS_CRITICAL,
    OS_FIELD_MAP,
)


class TestUbuntuBaseline:
    """OS-01: Linux (Ubuntu) baseline 검증."""

    def test_common_structure(self, ubuntu_baseline):
        assert_common_structure(ubuntu_baseline)

    def test_adapter_id(self, ubuntu_baseline):
        assert ubuntu_baseline["meta"]["adapter_id"] == "os_linux_generic"

    def test_critical_fields(self, ubuntu_baseline):
        assert_channel_critical_fields(
            ubuntu_baseline, OS_CRITICAL, OS_FIELD_MAP
        )

    def test_sections_collected(self, ubuntu_baseline):
        """수집된 섹션이 하나 이상 있는지 확인."""
        sections = ubuntu_baseline.get("sections", {})
        collected = [k for k, v in sections.items() if v == "success"]
        assert len(collected) > 0, "수집된 섹션이 없음"
        assert "system" in collected, "system 섹션 미수집"

    def test_correlation(self, ubuntu_baseline):
        assert_correlation_fields(ubuntu_baseline)

    def test_correlation_host_ip(self, ubuntu_baseline):
        assert_correlation_host_ip(ubuntu_baseline)

    def test_array_element_fields(self, ubuntu_baseline):
        assert_array_element_fields(
            ubuntu_baseline, OS_ARRAY_FIELDS, "ubuntu_baseline"
        )


class TestWindowsBaseline:
    """OS-04: Windows baseline 검증."""

    def test_common_structure(self, windows_baseline):
        assert_common_structure(windows_baseline)

    def test_adapter_id(self, windows_baseline):
        assert windows_baseline["meta"]["adapter_id"] == "os_windows_generic"

    def test_critical_fields(self, windows_baseline):
        assert_channel_critical_fields(
            windows_baseline, OS_CRITICAL, OS_FIELD_MAP
        )

    def test_sections_collected(self, windows_baseline):
        sections = windows_baseline.get("sections", {})
        collected = [k for k, v in sections.items() if v == "success"]
        assert len(collected) > 0, "수집된 섹션이 없음"
        assert "system" in collected, "system 섹션 미수집"

    def test_correlation(self, windows_baseline):
        """Windows는 correlation.system_uuid가 null일 수 있음 — 키 존재만 확인."""
        assert_correlation_fields(windows_baseline)

    def test_correlation_host_ip(self, windows_baseline):
        assert_correlation_host_ip(windows_baseline)

    def test_array_element_fields(self, windows_baseline):
        assert_array_element_fields(
            windows_baseline, OS_ARRAY_FIELDS, "windows_baseline"
        )


class TestRhel810RawFallback:
    """OS-RHEL810: Linux raw_fallback (Python <3.9) baseline 검증.

    production-audit (2026-04-29): RHEL 8.10 py3.6 환경의 raw fallback path 회귀.
    cycle-016 build #49 evidence 기반.
    """

    def test_common_structure(self, rhel810_raw_fallback_baseline):
        assert_common_structure(rhel810_raw_fallback_baseline)

    def test_gather_mode_raw_only(self, rhel810_raw_fallback_baseline):
        """raw_fallback mode 진입 검증 — diagnosis.details.gather_mode == 'raw_only'."""
        details = (
            rhel810_raw_fallback_baseline.get("diagnosis", {}).get("details", {})
        )
        assert details.get("gather_mode") == "raw_only", (
            f"gather_mode 'raw_only' 아님: {details.get('gather_mode')}"
        )
        assert details.get("python_version"), "python_version 누락"

    def test_critical_fields(self, rhel810_raw_fallback_baseline):
        assert_channel_critical_fields(
            rhel810_raw_fallback_baseline, OS_CRITICAL, OS_FIELD_MAP
        )

    def test_sections_collected(self, rhel810_raw_fallback_baseline):
        sections = rhel810_raw_fallback_baseline.get("sections", {})
        collected = [k for k, v in sections.items() if v == "success"]
        assert "system" in collected, "system 섹션 미수집"
        assert "memory" in collected, "memory 섹션 미수집 (raw fallback)"
        assert "storage" in collected, "storage 섹션 미수집 (raw fallback)"
        assert "network" in collected, "network 섹션 미수집 (raw fallback)"

    def test_memory_basis_physical(self, rhel810_raw_fallback_baseline):
        """raw fallback에서도 dmidecode 가능 시 physical_installed basis 인지."""
        memory = rhel810_raw_fallback_baseline["data"]["memory"]
        # raw fallback은 dmidecode 가능 시 physical_installed, 아니면 os_visible
        assert memory["total_basis"] in ("physical_installed", "os_visible"), (
            f"unexpected total_basis: {memory['total_basis']}"
        )

    def test_correlation(self, rhel810_raw_fallback_baseline):
        assert_correlation_fields(rhel810_raw_fallback_baseline)

    def test_correlation_host_ip(self, rhel810_raw_fallback_baseline):
        assert_correlation_host_ip(rhel810_raw_fallback_baseline)

    def test_array_element_fields(self, rhel810_raw_fallback_baseline):
        assert_array_element_fields(
            rhel810_raw_fallback_baseline,
            OS_ARRAY_FIELDS,
            "rhel810_raw_fallback_baseline",
        )
