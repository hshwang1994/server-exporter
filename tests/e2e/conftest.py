"""E2E 테스트 공통 설정 — baseline/fixture 로딩, 채널별 핵심 필드 정의."""

import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = PROJECT_ROOT / "schema" / "baseline_v1"
OUTPUT_DIR = PROJECT_ROOT / "tests" / "fixtures" / "outputs"

# ---------------------------------------------------------------------------
# 공통 최상위 키
# ---------------------------------------------------------------------------
COMMON_TOP_KEYS = [
    "status",
    "data",
    "sections",
    "errors",
    "meta",
    "schema_version",
]

# ---------------------------------------------------------------------------
# 채널별 핵심 필드
#   - 각 채널은 자기 채널의 필드만 검증
#   - 값이 None(null)인 경우 "키 존재"만 확인 (값 비교 안 함)
#   - P2-2 1단계: 스칼라 Must 필드 확장
# ---------------------------------------------------------------------------
REDFISH_CRITICAL = {
    "system": ["serial_number", "system_uuid", "vendor", "model"],
    "hardware": ["health", "sku", "oem"],
    "cpu": ["model", "count", "cores_physical"],
    "memory": ["total_gb", "total_basis"],
    "bmc": ["firmware_version", "ip"],
}

OS_CRITICAL = {
    "system": ["hostname", "os_type", "os_version", "hosting_type"],
    "cpu": ["model", "count", "cores_physical"],
    "memory": ["total_gb", "total_basis"],
}

ESXI_CRITICAL = {
    "system": ["hostname", "os_type"],
    "cpu": ["cores_physical"],
    "memory": ["total_basis"],
}

# ---------------------------------------------------------------------------
# Redfish 핵심 필드 → baseline JSON 실제 키 매핑
#   baseline에서 필드명이 다른 경우를 위한 매핑
#   (예: count → sockets, total_gb → total_mb, os_type → os_family,
#    os_version → version)
# ---------------------------------------------------------------------------
REDFISH_FIELD_MAP = {
    "cpu": {"count": "sockets", "model": "model", "cores_physical": "cores_physical"},
    "memory": {"total_gb": "total_mb", "total_basis": "total_basis"},
    "bmc": {"firmware_version": "firmware_version", "ip": "ip"},
    "system": {
        "serial_number": "serial_number",
        "system_uuid": "system_uuid",
        "vendor": "vendor",
        "model": "model",
    },
    "hardware": {"health": "health", "sku": "sku", "oem": "oem"},
}

OS_FIELD_MAP = {
    "system": {
        "hostname": "fqdn",
        "os_type": "os_family",
        "os_version": "version",
        "hosting_type": "hosting_type",
    },
    "cpu": {"count": "sockets", "model": "model", "cores_physical": "cores_physical"},
    "memory": {"total_gb": "total_mb", "total_basis": "total_basis"},
}

ESXI_FIELD_MAP = {
    "system": {
        "hostname": "fqdn",
        "os_type": "os_family",
    },
    "cpu": {"cores_physical": "cores_physical"},
    "memory": {"total_basis": "total_basis"},
}

# ---------------------------------------------------------------------------
# UUID 형식 패턴 (RFC 4122 hex-and-dash 형식)
# ---------------------------------------------------------------------------
UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------
def load_json(path: Path) -> dict:
    """JSON 파일을 읽어 dict로 반환."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_field(data_section: dict, logical_name: str, field_map: dict,
                  section_name: str) -> tuple:
    """논리 필드명 → 실제 키로 변환 후 (실제키, 존재여부) 반환."""
    actual_key = field_map.get(section_name, {}).get(logical_name, logical_name)
    exists = actual_key in data_section
    return actual_key, exists


# ---------------------------------------------------------------------------
# 공통 검증 함수
# ---------------------------------------------------------------------------
def assert_common_structure(output: dict):
    """공통 JSON 구조 검증: 최상위 키, schema_version, meta.adapter_id."""
    # 1) 최상위 키
    for key in COMMON_TOP_KEYS:
        assert key in output, f"최상위 키 누락: {key}"

    # 2) schema_version
    assert output["schema_version"] == "1", (
        f"schema_version 불일치: {output.get('schema_version')}"
    )

    # 3) meta.adapter_id
    meta = output.get("meta", {})
    assert meta, "meta 비어 있음"
    assert "adapter_id" in meta, "meta.adapter_id 키 누락"
    assert meta["adapter_id"], "meta.adapter_id 값이 비어 있음"


def assert_correlation_fields(output: dict):
    """CM-02: correlation 필드 검증 (fixture 수준).

    - system_uuid: 키 존재, 값이 있으면 UUID 형식 검증
    - serial_number: 키 존재만
    - 값 비교(cross-channel)는 수행하지 않음
    """
    correlation = output.get("correlation")
    if correlation is None:
        # OS 채널은 correlation이 최상위가 아닌 data.system에 있을 수 있음
        # 또는 없을 수 있음 — 키 존재 여부만 확인
        return

    assert "system_uuid" in correlation, "correlation.system_uuid 키 누락"
    assert "serial_number" in correlation, "correlation.serial_number 키 누락"

    uuid_val = correlation.get("system_uuid")
    if uuid_val is not None and uuid_val != "":
        assert UUID_PATTERN.match(str(uuid_val)), (
            f"system_uuid UUID 형식 불일치: {uuid_val}"
        )


def assert_correlation_host_ip(output: dict):
    """correlation.host_ip 존재 + 값 존재 검증.

    identity 기준이 아님 — primary key는 UUID.
    """
    correlation = output.get("correlation")
    if correlation is None:
        return
    assert "host_ip" in correlation, "correlation.host_ip 키 누락"
    assert correlation["host_ip"], "correlation.host_ip 값이 비어 있음"


def assert_hardware_oem_is_object(output: dict):
    """hardware.oem이 object(dict)인지 검증. 내부 키는 검증하지 않음."""
    data = output.get("data", {})
    hw = data.get("hardware")
    if hw is None:
        return  # hardware 섹션 없으면 건너뜀
    assert "oem" in hw, "hardware.oem 키 누락"
    assert isinstance(hw["oem"], dict), (
        f"hardware.oem이 dict가 아님: {type(hw['oem'])}"
    )


def assert_channel_critical_fields(output: dict, critical_fields: dict,
                                   field_map: dict):
    """채널별 핵심 필드 존재 검증.

    - collected 섹션에 대해서만 검증
    - 키 존재 확인 (값이 null이어도 통과)
    """
    data = output.get("data", {})
    sections = output.get("sections", {})

    # sections가 dict면 collected 목록 추출, 아니면 빈 리스트
    if isinstance(sections, dict):
        collected = []
        for sec_name, sec_status in sections.items():
            if sec_status == "success":
                collected.append(sec_name)
    else:
        collected = []

    for section_name, fields in critical_fields.items():
        if section_name not in collected:
            continue  # 미수집 섹션은 건너뜀

        section_data = data.get(section_name)
        if section_data is None:
            continue  # data에 섹션이 없으면 건너뜀

        # Redfish system은 hardware.vendor/model/serial 등으로 분산 가능
        # 실제 baseline 구조에 맞춰 검증
        for logical_field in fields:
            actual_key, exists = resolve_field(
                section_data, logical_field, field_map, section_name
            )
            # 특수 처리: redfish system 필드는 hardware에 있을 수 있음
            if not exists and section_name == "system":
                hw_data = data.get("hardware", {})
                if hw_data and actual_key in hw_data:
                    exists = True
            assert exists, (
                f"핵심 필드 누락: {section_name}.{actual_key} "
                f"(논리명: {logical_field})"
            )


# ---------------------------------------------------------------------------
# 채널별 배열 내부 필드 정의
#   - "section.array_key": 2단계 경로 → data[section][array_key]
#   - "firmware": 1단계 경로 → data[firmware] (top-level 배열, section이 아님)
#   - 배열이 비어있거나 섹션이 없으면 건너뜀 (graceful degradation)
#   - P2-2 2단계
# ---------------------------------------------------------------------------
REDFISH_ARRAY_FIELDS = {
    "storage.physical_disks": ["predicted_life_percent", "id"],
    "storage.logical_volumes": ["id", "controller_id", "member_drive_ids", "raid_level"],
    "power.power_supplies": ["state"],
    "firmware": ["component"],  # top-level 배열 (data.firmware[])
    "network.interfaces": ["link_status"],
}

OS_ARRAY_FIELDS = {
    # OS에는 predicted_life_percent / firmware / power 없음
    "network.interfaces": ["link_status"],
}

ESXI_ARRAY_FIELDS = {
    # ESXi baseline은 physical_disks 빈 배열, firmware/power 없음
    "network.interfaces": ["link_status"],
}


def assert_array_element_fields(output: dict, array_fields: dict,
                                fixture_label: str = ""):
    """배열 내부 요소별 필드 존재 검증.

    - 배열이 비어있거나 섹션이 없으면 건너뜀
    - 요소가 있으면: dict 구조 확인 → required field 존재 확인
    - fixture_label: 에러 메시지에 어떤 fixture인지 표시
    """
    data = output.get("data", {})
    prefix = f"{fixture_label}: " if fixture_label else ""

    for array_path, required_fields in array_fields.items():
        parts = array_path.split(".")
        if len(parts) == 2:
            # "section.array_key" → data[section][array_key]
            section = data.get(parts[0])
            if not isinstance(section, dict):
                continue
            arr = section.get(parts[1], [])
        elif len(parts) == 1:
            # "firmware" → data[firmware] (top-level 배열)
            arr = data.get(parts[0], [])
        else:
            continue

        if not isinstance(arr, list) or len(arr) == 0:
            continue

        for i, elem in enumerate(arr):
            assert isinstance(elem, dict), (
                f"{prefix}{array_path}[{i}]이 dict가 아님: {type(elem).__name__}"
            )
            for field in required_fields:
                assert field in elem, (
                    f"{prefix}{array_path}[{i}].{field} 키 누락"
                )


# ---------------------------------------------------------------------------
# Fixtures (pytest)
# ---------------------------------------------------------------------------
@pytest.fixture
def dell_baseline():
    return load_json(BASELINE_DIR / "dell_baseline.json")


@pytest.fixture
def hpe_baseline():
    return load_json(BASELINE_DIR / "hpe_baseline.json")


@pytest.fixture
def lenovo_baseline():
    return load_json(BASELINE_DIR / "lenovo_baseline.json")


@pytest.fixture
def ubuntu_baseline():
    return load_json(BASELINE_DIR / "ubuntu_baseline.json")


@pytest.fixture
def windows_baseline():
    return load_json(BASELINE_DIR / "windows_baseline.json")


@pytest.fixture
def esxi_baseline():
    return load_json(BASELINE_DIR / "esxi_baseline.json")


@pytest.fixture
def cisco_baseline():
    return load_json(BASELINE_DIR / "cisco_baseline.json")


@pytest.fixture
def rhel810_raw_fallback_baseline():
    # production-audit (2026-04-29): Linux raw_fallback (RHEL 8.10 py3.6) baseline
    return load_json(BASELINE_DIR / "rhel810_raw_fallback_baseline.json")


@pytest.fixture
def dell_r760_output():
    return load_json(OUTPUT_DIR / "dell_r760_output.json")
