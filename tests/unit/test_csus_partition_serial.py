"""HPE CSUS 3200 nPartition 시리얼 접미사 정규화 (OS 채널) — 2026-08-27.

배경
----
HPE Compute Scale-up Server 3200 은 nPartition(nPar) 장비다. OS 안에서 읽는 SMBIOS
Type 1 System Serial 에 파티션 번호가 접미사로 붙는다.

    물리 장비 시리얼                    : SGHD3TLNDD
    Partition0 의 OS DMI product_serial : SGHD3TLNDD-000

자산 관리 시스템은 물리 장비 시리얼로 서버를 관리하므로, 접미사가 붙은 채로 내보내면
같은 서버가 서로 다른 시리얼로 판정된다. OS 채널에서만 접미사를 뗀다.

이 테스트가 지키는 것
--------------------
1. 정규화가 **CSUS 3200 + `-<숫자 3자리>` 접미사** 일 때만 일어난다.
2. 그 외 모든 서버(일반 HPE ProLiant / Dell / Lenovo / 하이픈 포함 정상 시리얼)는
   값이 **글자 그대로** 유지된다.
3. 필터 안의 vendor alias / model pattern 미러가 저장소 정본과 drift 하지 않는다.
4. 실제 task YAML 의 set_fact 템플릿(= 와이어링)이 위 규칙대로 렌더된다.
5. 실 목데이터(2026-06-15 사이트 실 4노드 미러 캡처)의 값으로 SGHD3TLNDD-000 →
   SGHD3TLNDD 가 성립한다.

정본
----
    filter_plugins/serial_normalizer.py
    os-gather/tasks/linux/gather_system.yml
    os-gather/tasks/windows/gather_system.yml
    os-gather/tasks/windows/gather_hardware.yml
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
sys.path.insert(0, str(REPO / "module_utils"))

from serial_normalizer import (  # noqa: E402
    CSUS3200_MODEL_PATTERNS,
    CSUS3200_VENDOR_ALIASES,
    FilterModule,
    is_csus_3200,
    normalize_os_serial,
)

CSUS_MODEL = "Compute Scale-up Server 3200"
CSUS_MODEL_VARIANT = "Compute Scale-up Server 3200, 4S XNC Base Chassis"


# ── A. 요구 케이스 6종 ────────────────────────────────────────────────────────


def test_case1_csus_partition_000_suffix_removed():
    """케이스 1: HPE / CSUS 3200 / SGHD3TLNDD-000 → SGHD3TLNDD."""
    assert normalize_os_serial("SGHD3TLNDD-000", "HPE", CSUS_MODEL) == "SGHD3TLNDD"


def test_case2_csus_partition_001_suffix_removed():
    """케이스 2: 파티션 번호가 000 이 아니어도 동일하게 제거."""
    assert normalize_os_serial("SGHD3TLNDD-001", "HPE", CSUS_MODEL) == "SGHD3TLNDD"


def test_case3_generic_hpe_proliant_unchanged():
    """케이스 3: 일반 HPE ProLiant — 변경 금지."""
    assert normalize_os_serial("CZ12345678", "HPE", "ProLiant DL380 Gen11") == "CZ12345678"


def test_case4_generic_hpe_with_hyphen_serial_unchanged():
    """케이스 4: 일반 HPE 서버의 시리얼에 하이픈이 정상적으로 있는 경우 — 변경 금지.

    `-123` 은 접미사 패턴과 형태가 같지만 model 이 CSUS 가 아니므로 손대지 않는다.
    (단순 split('-')[0] 이었다면 'ABC' 로 잘렸을 값)
    """
    assert normalize_os_serial("ABC-123", "HPE", "ProLiant DL360 Gen10") == "ABC-123"


def test_case5_other_vendor_with_suffix_unchanged():
    """케이스 5: 다른 vendor — 접미사 형태여도 변경 금지."""
    assert normalize_os_serial("ABCDEF-000", "Dell", "PowerEdge R760") == "ABCDEF-000"
    assert normalize_os_serial("ABCDEF-000", "Dell Inc.", "PowerEdge R760") == "ABCDEF-000"


def test_case6_csus_with_non_partition_suffix_unchanged():
    """케이스 6: CSUS 지만 접미사가 파티션 형식이 아니면 변경 금지."""
    assert normalize_os_serial("SGHD3TLNDD-ABC", "HPE", CSUS_MODEL) == "SGHD3TLNDD-ABC"


# ── B. vendor 축 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "vendor",
    ["HPE", "hpe", " HPE ", "Hewlett Packard Enterprise", "Hewlett-Packard", "HP"],
)
def test_hpe_alias_variants_are_recognized(vendor):
    assert normalize_os_serial("SGHD3TLNDD-000", vendor, CSUS_MODEL) == "SGHD3TLNDD"


@pytest.mark.parametrize(
    "vendor",
    ["Dell Inc.", "Lenovo", "Supermicro", "Cisco Systems Inc", "VMware, Inc.", "", None],
)
def test_non_hpe_vendor_never_normalized(vendor):
    """CSUS model 문자열이 와도 vendor 가 HPE 계열이 아니면 손대지 않는다."""
    assert normalize_os_serial("SGHD3TLNDD-000", vendor, CSUS_MODEL) == "SGHD3TLNDD-000"


def test_vendor_substring_does_not_match():
    """부분 문자열로 vendor 를 판정하지 않는다 (완전 일치)."""
    assert normalize_os_serial("SGHD3TLNDD-000", "SHPEX", CSUS_MODEL) == "SGHD3TLNDD-000"


# ── C. model 축 ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model",
    [
        "Compute Scale-up Server 3200",
        "Compute Scale-up Server 3200, 4S XNC Base Chassis",
        "HPE Compute Scale-up Server 3200",
        "compute scale-up server 3200",
        "CSUS 3200",
    ],
)
def test_csus_model_variants_are_recognized(model):
    assert normalize_os_serial("SGHD3TLNDD-000", "HPE", model) == "SGHD3TLNDD"


@pytest.mark.parametrize(
    "model",
    [
        "ProLiant DL380 Gen11",
        "ProLiant DL360 Gen10 Plus",
        "Superdome Flex 280",  # 다른 scale-up 라인 — 이번 범위 아님
        "Compute Scale-up Server 3000",  # 3200 아님
        "",
        None,
    ],
)
def test_non_csus_model_never_normalized(model):
    assert normalize_os_serial("SGHD3TLNDD-000", "HPE", model) == "SGHD3TLNDD-000"


def test_model_missing_is_fail_safe():
    """vendor 만 있고 model 을 못 읽으면 정규화하지 않는다."""
    assert normalize_os_serial("SGHD3TLNDD-000", "HPE") == "SGHD3TLNDD-000"


# ── D. 접미사 패턴 경계 ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "serial,expected",
    [
        ("SGHD3TLNDD-000", "SGHD3TLNDD"),
        ("SGHD3TLNDD-999", "SGHD3TLNDD"),
        ("SGHD3TLNDD-00", "SGHD3TLNDD-00"),  # 2자리 — 대상 아님
        ("SGHD3TLNDD-0000", "SGHD3TLNDD-0000"),  # 4자리 — 대상 아님
        ("SGHD3TLNDD-000-000", "SGHD3TLNDD-000"),  # 마지막 한 덩어리만
        ("SGHD3TLNDD000", "SGHD3TLNDD000"),  # 하이픈 없음
        ("SGHD3TLNDD-000 ", "SGHD3TLNDD"),  # 후행 공백
        ("-000", "-000"),  # base 없음 — 전체 삭제 금지
        ("SGHD3TLNDD-00A", "SGHD3TLNDD-00A"),
        ("SGHD3TLNDD-000A", "SGHD3TLNDD-000A"),
    ],
)
def test_suffix_pattern_boundaries(serial, expected):
    assert normalize_os_serial(serial, "HPE", CSUS_MODEL) == expected


def test_normalize_is_idempotent_for_partition_serial():
    once = normalize_os_serial("SGHD3TLNDD-000", "HPE", CSUS_MODEL)
    twice = normalize_os_serial(once, "HPE", CSUS_MODEL)
    assert once == twice == "SGHD3TLNDD"


# ── E. 입력 방어 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("serial", [None, 123456, ["SGHD3TLNDD-000"], {"a": 1}, True])
def test_non_string_serial_passthrough(serial):
    """None / 비-str 은 타입을 바꾸지 않고 그대로 통과."""
    assert normalize_os_serial(serial, "HPE", CSUS_MODEL) is serial


@pytest.mark.parametrize("serial", ["", "   "])
def test_blank_serial_passthrough(serial):
    assert normalize_os_serial(serial, "HPE", CSUS_MODEL) == serial


def test_non_csus_value_is_returned_byte_identical():
    """정규화 대상이 아니면 trim 조차 하지 않는다 (기존 서버 무영향 보장)."""
    raw = "  CZ12345678  "
    assert normalize_os_serial(raw, "HPE", "ProLiant DL380 Gen11") == raw


def test_filter_is_registered():
    assert "normalize_os_serial" in FilterModule().filters()


# ── F. 미러 drift 가드 ───────────────────────────────────────────────────────


def _vendor_aliases_yaml():
    data = yaml.safe_load((REPO / "common" / "vars" / "vendor_aliases.yml").read_text(encoding="utf-8"))
    return data["vendor_aliases"]


def test_vendor_alias_mirror_matches_vendor_aliases_yml():
    """필터의 HPE alias 미러가 vendor_aliases.yml :: vendor_aliases.hpe 와 일치."""
    canonical = {a.strip().lower() for a in _vendor_aliases_yaml()["hpe"]}
    assert CSUS3200_VENDOR_ALIASES == canonical, (
        "vendor_aliases.yml 의 hpe alias 가 바뀌었다 — "
        "filter_plugins/serial_normalizer.py :: CSUS3200_VENDOR_ALIASES 동반 갱신 필요"
    )


def test_every_hpe_alias_is_accepted_by_filter():
    for alias in _vendor_aliases_yaml()["hpe"]:
        assert is_csus_3200(alias, CSUS_MODEL), f"alias 미인식: {alias!r}"


def test_model_pattern_mirror_matches_adapter_yaml():
    """필터의 model pattern 미러가 adapters/redfish/hpe_csus_3200.yml 정본과 일치."""
    adapter = yaml.safe_load(
        (REPO / "adapters" / "redfish" / "hpe_csus_3200.yml").read_text(encoding="utf-8")
    )
    assert tuple(adapter["match"]["model_patterns"]) == CSUS3200_MODEL_PATTERNS, (
        "adapter 의 model_patterns 가 바뀌었다 — "
        "filter_plugins/serial_normalizer.py :: CSUS3200_MODEL_PATTERNS 동반 갱신 필요"
    )


def test_model_matching_semantics_equal_adapter_common():
    """모델 매칭 규칙이 adapter 선택기(pattern_match_any)와 동일해야 한다."""
    from adapter_common import pattern_match_any  # noqa: WPS433 — 테스트 전용 런타임 import

    samples = [
        CSUS_MODEL,
        CSUS_MODEL_VARIANT,
        "HPE Compute Scale-up Server 3200",
        "compute scale-up server 3200",
        "CSUS 3200",
        "ProLiant DL380 Gen11",
        "PowerEdge R760",
        "Superdome Flex 280",
        "",
    ]
    for model in samples:
        assert is_csus_3200("HPE", model) == bool(
            pattern_match_any(list(CSUS3200_MODEL_PATTERNS), model)
        ), f"매칭 규칙 불일치: {model!r}"


# ── G. 실제 task YAML 와이어링 렌더 ──────────────────────────────────────────

LINUX_SYS = REPO / "os-gather" / "tasks" / "linux" / "gather_system.yml"
WIN_SYS = REPO / "os-gather" / "tasks" / "windows" / "gather_system.yml"
WIN_HW = REPO / "os-gather" / "tasks" / "windows" / "gather_hardware.yml"


def _env():
    env = Environment()  # noqa: S701 — 테스트 전용 (autoescape 불필요)
    env.filters["normalize_os_serial"] = normalize_os_serial
    return env


def _find_task(path: Path, name_sub: str) -> dict:
    for task in yaml.safe_load(path.read_text(encoding="utf-8")):
        if not isinstance(task, dict):
            continue
        if name_sub in str(task.get("name", "")) and "ansible.builtin.set_fact" in task:
            return task
    raise AssertionError(f"{path.name} 에서 set_fact task '{name_sub}' 미발견")


def _render_str(env, template: str, ctx: dict):
    out = env.from_string(template).render(**ctx).strip()
    try:
        return ast.literal_eval(out)
    except (ValueError, SyntaxError):
        return out


def _render(task: dict, key: str, ctx: dict):
    """task-level vars 를 먼저 풀고 set_fact 값을 렌더한다 (Ansible 평가 순서와 동일)."""
    env = _env()
    local = dict(ctx)
    for name, template in (task.get("vars") or {}).items():
        local[name] = _render_str(env, template, local)
    return _render_str(env, task["ansible.builtin.set_fact"][key], local)


@pytest.fixture(scope="module")
def linux_serial_task():
    return _find_task(LINUX_SYS, "normalize serial")


@pytest.fixture(scope="module")
def windows_serial_task():
    return _find_task(WIN_SYS, "normalize serial")


@pytest.fixture(scope="module")
def windows_hw_serial_task():
    return _find_task(WIN_HW, "normalize serial")


def test_windows_hardware_fragment_uses_normalized_serial():
    """data.hardware.serial 이 정규화 task 결과를 그대로 쓰는지 (와이어링 끊김 방지)."""
    fragment = _find_task(WIN_HW, "hardware | build fragment")["ansible.builtin.set_fact"]
    assert "_w_hw_serial" in fragment["_data_fragment"]["hardware"]["serial"]


@pytest.mark.parametrize(
    "ctx,expected",
    [
        # Python 경로 (setup fact) — CSUS 3200
        (
            {
                "_l_serial_val": "SGHD3TLNDD-000",
                "ansible_system_vendor": "HPE",
                "ansible_product_name": CSUS_MODEL,
            },
            "SGHD3TLNDD",
        ),
        # raw fallback 경로 (sysfs 직접 read) — CSUS 3200
        (
            {
                "_l_serial_val": "SGHD3TLNDD-001",
                "_l_raw_vendor": "HPE",
                "_l_raw_model": CSUS_MODEL_VARIANT,
            },
            "SGHD3TLNDD",
        ),
        # 일반 HPE ProLiant
        (
            {
                "_l_serial_val": "CZ12345678",
                "ansible_system_vendor": "HPE",
                "ansible_product_name": "ProLiant DL380 Gen11",
            },
            "CZ12345678",
        ),
        # 하이픈 포함 정상 시리얼
        (
            {
                "_l_serial_val": "ABC-123",
                "ansible_system_vendor": "HPE",
                "ansible_product_name": "ProLiant DL360 Gen10",
            },
            "ABC-123",
        ),
        # Dell
        (
            {
                "_l_serial_val": "ABCDEF-000",
                "ansible_system_vendor": "Dell Inc.",
                "ansible_product_name": "PowerEdge R760",
            },
            "ABCDEF-000",
        ),
        # 시리얼 미확보 (권한 부족 등)
        (
            {
                "_l_serial_val": None,
                "ansible_system_vendor": "HPE",
                "ansible_product_name": CSUS_MODEL,
            },
            None,
        ),
        # vendor / model 둘 다 미확보 — 변수 자체가 undefined
        ({"_l_serial_val": "SGHD3TLNDD-000"}, "SGHD3TLNDD-000"),
    ],
)
def test_linux_task_wiring(linux_serial_task, ctx, expected):
    assert _render(linux_serial_task, "_l_serial_val", ctx) == expected


@pytest.mark.parametrize(
    "ctx,expected",
    [
        (
            {
                "_w_serial_val": "SGHD3TLNDD-000",
                "_w_hosting": {"Manufacturer": "HPE", "Model": CSUS_MODEL},
            },
            "SGHD3TLNDD",
        ),
        (
            {
                "_w_serial_val": "CZ12345678",
                "_w_hosting": {"Manufacturer": "HPE", "Model": "ProLiant DL380 Gen11"},
            },
            "CZ12345678",
        ),
        (
            {
                "_w_serial_val": "ABCDEF-000",
                "_w_hosting": {"Manufacturer": "Dell Inc.", "Model": "PowerEdge R760"},
            },
            "ABCDEF-000",
        ),
        # Win32_ComputerSystem 조회 실패 → _w_hosting = {}
        ({"_w_serial_val": "SGHD3TLNDD-000", "_w_hosting": {}}, "SGHD3TLNDD-000"),
        (
            {
                "_w_serial_val": None,
                "_w_hosting": {"Manufacturer": "HPE", "Model": CSUS_MODEL},
            },
            None,
        ),
    ],
)
def test_windows_system_task_wiring(windows_serial_task, ctx, expected):
    assert _render(windows_serial_task, "_w_serial_val", ctx) == expected


@pytest.mark.parametrize(
    "ctx,expected",
    [
        # BIOS 시리얼이 있으면 그 값을 정규화
        (
            {
                "_w_hw_data": {
                    "bios_serial": "SGHD3TLNDD-000",
                    "vendor": "HPE",
                    "model": CSUS_MODEL,
                },
                "_w_serial_val": "SGHD3TLNDD",
            },
            "SGHD3TLNDD",
        ),
        # BIOS 시리얼 없음 → gather_system 의 (이미 정규화된) 값으로 폴백
        (
            {
                "_w_hw_data": {"bios_serial": None, "vendor": "HPE", "model": CSUS_MODEL},
                "_w_serial_val": "SGHD3TLNDD",
            },
            "SGHD3TLNDD",
        ),
        # 일반 HPE — 무변경
        (
            {
                "_w_hw_data": {
                    "bios_serial": "CZ12345678",
                    "vendor": "HPE",
                    "model": "ProLiant DL380 Gen11",
                },
                "_w_serial_val": "CZ12345678",
            },
            "CZ12345678",
        ),
        # 하이픈 포함 정상 시리얼 — 무변경
        (
            {
                "_w_hw_data": {
                    "bios_serial": "ABC-123",
                    "vendor": "HPE",
                    "model": "ProLiant DL360 Gen10",
                },
                "_w_serial_val": "ABC-123",
            },
            "ABC-123",
        ),
        # Dell — 무변경
        (
            {
                "_w_hw_data": {
                    "bios_serial": "ABCDEF-000",
                    "vendor": "Dell Inc.",
                    "model": "PowerEdge R760",
                },
                "_w_serial_val": "ABCDEF-000",
            },
            "ABCDEF-000",
        ),
        # 둘 다 없음
        ({"_w_hw_data": {}, "_w_serial_val": None}, None),
    ],
)
def test_windows_hardware_task_wiring(windows_hw_serial_task, ctx, expected):
    assert _render(windows_hw_serial_task, "_w_hw_serial", ctx) == expected


def test_windows_hardware_does_not_double_normalize(windows_hw_serial_task):
    """폴백값(_w_serial_val)은 이미 정규화된 값이라 다시 자르면 안 된다.

    'AB-123-000' 은 gather_system 에서 한 번 잘려 'AB-123' 이 된다. 이 값이
    gather_hardware 에서 또 잘리면 'AB' 가 된다 — 그 이중 적용을 막는다.
    """
    ctx = {
        "_w_hw_data": {"bios_serial": None, "vendor": "HPE", "model": CSUS_MODEL},
        "_w_serial_val": "AB-123",
    }
    assert _render(windows_hw_serial_task, "_w_hw_serial", ctx) == "AB-123"


# ── H. 실 목데이터 근거 ──────────────────────────────────────────────────────

RECORDING = REPO / "tests" / "fixtures" / "redfish" / "real_hpe_csus3200" / "recording.json"


@pytest.fixture(scope="module")
def csus_mock():
    """2026-06-15 사이트 실 4노드 미러 캡처에서 vendor / model / serial 을 뽑는다."""
    data = json.loads(RECORDING.read_text(encoding="utf-8"))

    def body(key):
        entry = data[key]
        return entry[1] if isinstance(entry, list) else entry

    system = body("get::Systems/Partition0")
    chassis = body("get::Chassis/r001u01")
    return {
        "partition_serial": system["SerialNumber"],
        "system_type": system["SystemType"],
        "vendor": chassis["Manufacturer"],
        "model": chassis["Model"],
        "chassis_serial": chassis["SerialNumber"],
    }


def test_mock_data_shape_is_still_what_we_assumed(csus_mock):
    """목데이터가 바뀌면 이 정규화의 전제도 다시 봐야 한다."""
    assert csus_mock["partition_serial"] == "SGHD3TLNDD-000"
    assert csus_mock["system_type"] == "PhysicallyPartitioned"
    assert csus_mock["vendor"] == "HPE"
    assert csus_mock["model"] == "Compute Scale-up Server 3200, 4S XNC Base Chassis"
    assert csus_mock["chassis_serial"] == "SGHD3TLNDD"


def test_mock_partition_serial_normalizes_to_physical_serial(csus_mock):
    """실 목데이터: Partition0 시리얼을 정규화하면 물리 Chassis 시리얼과 같아진다."""
    assert (
        normalize_os_serial(
            csus_mock["partition_serial"], csus_mock["vendor"], csus_mock["model"]
        )
        == csus_mock["chassis_serial"]
    )


def test_mock_wiring_end_to_end(linux_serial_task, csus_mock):
    """실 목데이터 값을 Linux task 템플릿에 그대로 넣어도 물리 시리얼이 나온다."""
    rendered = _render(
        linux_serial_task,
        "_l_serial_val",
        {
            "_l_serial_val": csus_mock["partition_serial"],
            "ansible_system_vendor": csus_mock["vendor"],
            "ansible_product_name": csus_mock["model"],
        },
    )
    assert rendered == csus_mock["chassis_serial"] == "SGHD3TLNDD"
