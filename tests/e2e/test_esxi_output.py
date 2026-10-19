"""ESXi-01: ESXi 채널 baseline 전용 핵심 필드 회귀 검증.

검증 수준:
  1. 공통 JSON 구조 (최상위 키, schema_version, meta.adapter_id)
  2. 수집된 섹션 존재 (system 포함)
  3. 핵심 필드 존재 (system.fqdn, system.os_family)
  4. adapter_id == esxi_7x (2026-10-20 실측 baseline — esxi02 는 ESXi 7.x)
  5. correlation 필드 (키 존재 + UUID 형식)

baseline 필드 확인 결과:
  - system.os_family: 'VMware ESXi' (안정)
  - system.fqdn: 'esxi02' (안정)
  - correlation.system_uuid: UUID 형식 확인됨
  - correlation.serial_number: 값 존재 확인됨
"""

from conftest import (
    assert_array_element_fields,
    assert_channel_critical_fields,
    assert_common_structure,
    assert_correlation_fields,
    assert_correlation_host_ip,
    ESXI_ARRAY_FIELDS,
    ESXI_CRITICAL,
    ESXI_FIELD_MAP,
)


class TestEsxiBaseline:
    """ESXi-01: ESXi generic baseline 검증."""

    def test_common_structure(self, esxi_baseline):
        assert_common_structure(esxi_baseline)

    def test_adapter_id(self, esxi_baseline):
        # 2026-10-20: baseline 을 production d464de4b canary #314 의 esxi02(ESXi 7.x) 실측 봉투로 갱신 — adapter 는 version_patterns 로 esxi_7x
        assert esxi_baseline["meta"]["adapter_id"] == "esxi_7x"

    def test_critical_fields(self, esxi_baseline):
        assert_channel_critical_fields(
            esxi_baseline, ESXI_CRITICAL, ESXI_FIELD_MAP
        )

    def test_sections_collected(self, esxi_baseline):
        """수집된 섹션이 하나 이상, system 포함."""
        sections = esxi_baseline.get("sections", {})
        collected = [k for k, v in sections.items() if v == "success"]
        assert len(collected) > 0, "수집된 섹션이 없음"
        assert "system" in collected, "system 섹션 미수집"

    def test_correlation(self, esxi_baseline):
        assert_correlation_fields(esxi_baseline)

    def test_correlation_host_ip(self, esxi_baseline):
        assert_correlation_host_ip(esxi_baseline)

    def test_array_element_fields(self, esxi_baseline):
        assert_array_element_fields(
            esxi_baseline, ESXI_ARRAY_FIELDS, "esxi_baseline"
        )
