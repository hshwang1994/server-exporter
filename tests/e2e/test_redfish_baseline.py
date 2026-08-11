"""RF-01~03: Redfish 채널 baseline 핵심 필드 회귀 검증.

검증 수준:
  1. 공통 JSON 구조 (최상위 키, schema_version, meta.adapter_id)
  2. 필수 섹션 존재 (sections에 선언된 supported/collected)
  3. 핵심 필드 존재 (채널별 CRITICAL_FIELDS)
  4. adapter_id 기대값 일치
"""

import pytest

from conftest import (
    assert_array_element_fields,
    assert_channel_critical_fields,
    assert_common_structure,
    assert_hardware_oem_is_object,
    load_json,
    PROJECT_ROOT,
    REDFISH_ARRAY_FIELDS,
    REDFISH_CRITICAL,
    REDFISH_FIELD_MAP,
)


class TestDellBaseline:
    """RF-01: Dell iDRAC9 baseline 검증."""

    def test_common_structure(self, dell_baseline):
        assert_common_structure(dell_baseline)

    def test_adapter_id(self, dell_baseline):
        assert dell_baseline["meta"]["adapter_id"] == "redfish_dell_idrac9"

    def test_critical_fields(self, dell_baseline):
        assert_channel_critical_fields(
            dell_baseline, REDFISH_CRITICAL, REDFISH_FIELD_MAP
        )

    def test_sections_collected(self, dell_baseline):
        """수집된 섹션이 하나 이상 있는지 확인."""
        sections = dell_baseline.get("sections", {})
        collected = [k for k, v in sections.items() if v == "success"]
        assert len(collected) > 0, "수집된 섹션이 없음"

    def test_hardware_oem_is_object(self, dell_baseline):
        assert_hardware_oem_is_object(dell_baseline)

    def test_array_element_fields(self, dell_baseline):
        assert_array_element_fields(
            dell_baseline, REDFISH_ARRAY_FIELDS, "dell_baseline"
        )


class TestHpeBaseline:
    """RF-02: HPE iLO5 baseline 검증."""

    def test_common_structure(self, hpe_baseline):
        assert_common_structure(hpe_baseline)

    def test_adapter_id(self, hpe_baseline):
        assert hpe_baseline["meta"]["adapter_id"] == "redfish_hpe_ilo5"

    def test_critical_fields(self, hpe_baseline):
        assert_channel_critical_fields(
            hpe_baseline, REDFISH_CRITICAL, REDFISH_FIELD_MAP
        )

    def test_sections_collected(self, hpe_baseline):
        sections = hpe_baseline.get("sections", {})
        collected = [k for k, v in sections.items() if v == "success"]
        assert len(collected) > 0, "수집된 섹션이 없음"

    def test_hardware_oem_is_object(self, hpe_baseline):
        assert_hardware_oem_is_object(hpe_baseline)

    def test_array_element_fields(self, hpe_baseline):
        assert_array_element_fields(
            hpe_baseline, REDFISH_ARRAY_FIELDS, "hpe_baseline"
        )


class TestLenovoBaseline:
    """RF-03: Lenovo XCC baseline 검증."""

    def test_common_structure(self, lenovo_baseline):
        assert_common_structure(lenovo_baseline)

    def test_adapter_id(self, lenovo_baseline):
        assert lenovo_baseline["meta"]["adapter_id"] == "redfish_lenovo_xcc"

    def test_critical_fields(self, lenovo_baseline):
        assert_channel_critical_fields(
            lenovo_baseline, REDFISH_CRITICAL, REDFISH_FIELD_MAP
        )

    def test_sections_collected(self, lenovo_baseline):
        sections = lenovo_baseline.get("sections", {})
        collected = [k for k, v in sections.items() if v == "success"]
        assert len(collected) > 0, "수집된 섹션이 없음"

    def test_hardware_oem_is_object(self, lenovo_baseline):
        assert_hardware_oem_is_object(lenovo_baseline)

    def test_array_element_fields(self, lenovo_baseline):
        assert_array_element_fields(
            lenovo_baseline, REDFISH_ARRAY_FIELDS, "lenovo_baseline"
        )


class TestDellR760Output:
    """Dell R760 output fixture (baseline과 별도 장비) 검증."""

    def test_common_structure(self, dell_r760_output):
        assert_common_structure(dell_r760_output)

    def test_adapter_id(self, dell_r760_output):
        assert dell_r760_output["meta"]["adapter_id"] == "redfish_dell_idrac9"

    def test_critical_fields(self, dell_r760_output):
        assert_channel_critical_fields(
            dell_r760_output, REDFISH_CRITICAL, REDFISH_FIELD_MAP
        )

    def test_hardware_oem_is_object(self, dell_r760_output):
        assert_hardware_oem_is_object(dell_r760_output)

    def test_array_element_fields(self, dell_r760_output):
        assert_array_element_fields(
            dell_r760_output, REDFISH_ARRAY_FIELDS, "dell_r760_output"
        )


class TestDellServiceTagIsRepresentativeSerial:
    """Dell 1차 교정 (2026-08-11): 최종 envelope 의 서버 대표 시리얼 = Dell Service Tag.

    사용자 지시 — data.hardware.serial 와 correlation.serial_number 가 둘 다
    ServiceRoot.Oem.Dell.ServiceTag 와 같은지 최종 JSON 기준으로 확인한다.
    기대값은 하드코딩하지 않고 대응하는 raw fixture 의 ServiceRoot 에서 읽어 비교한다.
    """

    @staticmethod
    def _service_tag(raw_fixture_dir):
        root = load_json(
            PROJECT_ROOT / "tests" / "fixtures" / "redfish" / raw_fixture_dir
            / "service_root.json"
        )
        tag = ((root.get("Oem") or {}).get("Dell") or {}).get("ServiceTag")
        assert tag, "%s/service_root.json 에 Oem.Dell.ServiceTag 없음" % raw_fixture_dir
        return tag

    @pytest.mark.parametrize(
        "envelope_name,raw_fixture_dir",
        [("dell_baseline", "dell"), ("dell_r760_output", "dell_r760")],
    )
    def test_both_serial_fields_equal_service_tag(
        self, request, envelope_name, raw_fixture_dir
    ):
        envelope = request.getfixturevalue(envelope_name)
        expected = self._service_tag(raw_fixture_dir)
        hardware_serial = envelope["data"]["hardware"]["serial"]
        correlation_serial = envelope["correlation"]["serial_number"]
        assert hardware_serial == expected, (
            "%s: data.hardware.serial 이 Service Tag 와 다름" % envelope_name
        )
        assert correlation_serial == expected, (
            "%s: correlation.serial_number 가 Service Tag 와 다름" % envelope_name
        )
        assert hardware_serial == correlation_serial

    @pytest.mark.parametrize(
        "envelope_name", ["dell_baseline", "dell_r760_output"]
    )
    def test_board_serial_is_not_the_representative_serial(
        self, request, envelope_name
    ):
        """보드 제조 시리얼(`CNIVC…`)이 대표 시리얼 자리에 남아 있지 않다."""
        envelope = request.getfixturevalue(envelope_name)
        for path, value in (
            ("data.hardware.serial", envelope["data"]["hardware"]["serial"]),
            ("correlation.serial_number", envelope["correlation"]["serial_number"]),
        ):
            assert not str(value).startswith("CNIVC"), (
                "%s: %s 에 보드 제조 시리얼이 남아 있음 (%r)"
                % (envelope_name, path, value)
            )
