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
        assert ubuntu_baseline["meta"]["adapter_id"] == "os_linux_ubuntu"

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

    def test_os_disk_flag(self, ubuntu_baseline):
        """is_os_disk (2026-07-02): OS 루트 디스크가 정확히 표시되는지.

        ubuntu baseline 토폴로지: /dev/sda=true(OS 루트 LVM+/boot), /dev/sdb=false.
        """
        disks = ubuntu_baseline["data"]["storage"]["physical_disks"]
        assert disks, "physical_disks 비어있음"
        for d in disks:
            assert "is_os_disk" in d, f"is_os_disk 누락: {d.get('id')}"
            assert d["is_os_disk"] in (True, False, None), (
                f"is_os_disk 타입 위반: {d.get('id')}={d['is_os_disk']}"
            )
        by_id = {d["id"]: d["is_os_disk"] for d in disks}
        assert by_id.get("/dev/sda") is True, "OS 디스크(/dev/sda) is_os_disk != true"
        assert by_id.get("/dev/sdb") is False, "데이터 디스크(/dev/sdb) is_os_disk != false"


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


class TestWindows2022Baseline:
    """OS-WIN2022: Windows Server 2022 baseline (10.100.64.120 실측 2026-06-22).

    disk serial/wwn/health 가 실 Windows 에서 populate 되는지 회귀 고정.
    """

    def test_common_structure(self, windows_2022_baseline):
        assert_common_structure(windows_2022_baseline)

    def test_adapter_id(self, windows_2022_baseline):
        assert windows_2022_baseline["meta"]["adapter_id"] == "os_windows_2022"

    def test_critical_fields(self, windows_2022_baseline):
        assert_channel_critical_fields(
            windows_2022_baseline, OS_CRITICAL, OS_FIELD_MAP
        )

    def test_sections_collected(self, windows_2022_baseline):
        sections = windows_2022_baseline.get("sections", {})
        collected = [k for k, v in sections.items() if v == "success"]
        assert "system" in collected and "storage" in collected

    def test_correlation(self, windows_2022_baseline):
        assert_correlation_fields(windows_2022_baseline)

    def test_correlation_host_ip(self, windows_2022_baseline):
        assert_correlation_host_ip(windows_2022_baseline)

    def test_array_element_fields(self, windows_2022_baseline):
        assert_array_element_fields(
            windows_2022_baseline, OS_ARRAY_FIELDS, "windows_2022_baseline"
        )

    def test_disk_serial_wwn_populated(self, windows_2022_baseline):
        """실 Windows 디스크 serial/wwn 가 실제로 채워지는지 (placeholder null 아님)."""
        disks = windows_2022_baseline["data"]["storage"]["physical_disks"]
        assert disks, "physical_disks 비어있음"
        for d in disks:
            assert d.get("serial"), f"serial 미설정: {d.get('id')}"
            assert d.get("wwn"), f"wwn 미설정: {d.get('id')}"
            assert d.get("health") == "healthy"


class TestRhel810RawFallback:
    """OS-RHEL810: Linux raw_fallback (Python <3.9) baseline 검증.

    production-audit (2026-04-29): RHEL 8.10 py3.6 환경의 raw fallback path 회귀.
    cycle-016 build #49 evidence 기반.
    """

    def test_common_structure(self, rhel810_raw_fallback_baseline):
        assert_common_structure(rhel810_raw_fallback_baseline)

    def test_gather_mode_raw_only(self, rhel810_raw_fallback_baseline):
        """raw_fallback mode 진입 검증 — gather_mode 가 raw 경로 값(python_ok 아님).

        코드 정의값(preflight.yml): python_ok / python_missing / python_incompatible / raw_forced.
        RHEL 8.10(py3.6)은 python_incompatible 로 raw 경로 진입 (2026-06-22 161 실측 재캡처).
        """
        details = (
            rhel810_raw_fallback_baseline.get("diagnosis", {}).get("details", {})
        )
        assert details.get("gather_mode") in (
            "python_missing", "python_incompatible", "raw_forced"
        ), f"raw fallback mode 아님: {details.get('gather_mode')}"
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
