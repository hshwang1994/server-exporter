"""CM-02, CM-03: 공통 출력 구조 검증.

- CM-03: schema_version == "1"
- CM-02: correlation 필드 (system_uuid, serial_number) 존재 및 형식
- 공통: 최상위 키, meta.adapter_id 존재 및 비어 있지 않음
"""

import pytest

from conftest import (
    assert_common_structure,
    assert_correlation_fields,
    BASELINE_DIR,
    load_json,
)


# ---------------------------------------------------------------------------
# 전체 baseline을 순회하며 공통 구조 검증
# ---------------------------------------------------------------------------
BASELINE_FILES = list(BASELINE_DIR.glob("*_baseline.json"))


@pytest.mark.parametrize(
    "baseline_path",
    BASELINE_FILES,
    ids=[p.stem for p in BASELINE_FILES],
)
class TestOutputSchema:
    """모든 baseline에 대해 공통 구조를 검증한다."""

    def test_common_top_keys_and_schema_version(self, baseline_path):
        """CM-03: 최상위 키 + schema_version == '1' + meta.adapter_id."""
        output = load_json(baseline_path)
        assert_common_structure(output)

    def test_correlation_fields(self, baseline_path):
        """CM-02: correlation 필드 존재 및 UUID 형식."""
        output = load_json(baseline_path)
        assert_correlation_fields(output)


# ---------------------------------------------------------------------------
# output fixture도 동일 검증
# ---------------------------------------------------------------------------
class TestOutputFixture:
    """tests/fixtures/outputs/ 파일에 대한 공통 구조 검증."""

    def test_dell_r760_common_structure(self, dell_r760_output):
        assert_common_structure(dell_r760_output)

    def test_dell_r760_correlation(self, dell_r760_output):
        assert_correlation_fields(dell_r760_output)
