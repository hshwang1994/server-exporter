# -*- coding: utf-8 -*-
# ==============================================================================
# serial_normalizer.py — OS 채널 시스템 시리얼 표시값 정규화 필터
# ==============================================================================
# 존재 이유
# ---------
# HPE Compute Scale-up Server 3200 (CSUS 3200) 은 nPartition(nPar) 장비다.
# OS 안에서 읽는 SMBIOS Type 1 System Serial 에는 **파티션 번호 접미사**가 붙는다.
#
#   물리 장비 시리얼                       : SGHD3TLNDD
#   Partition0 의 OS DMI product_serial    : SGHD3TLNDD-000
#
# 같은 장비의 Redfish 응답도 동일한 구조다 (2026-06-15 사이트 실 4노드 미러 캡처,
# tests/fixtures/redfish/real_hpe_csus3200/recording.json):
#
#   GET /redfish/v1/Systems/Partition0 → SerialNumber "SGHD3TLNDD-000"
#                                        SystemType   "PhysicallyPartitioned"
#   GET /redfish/v1/Chassis/r001u01    → SerialNumber "SGHD3TLNDD"
#                                        Model        "Compute Scale-up Server 3200, 4S XNC Base Chassis"
#   GET /redfish/v1/Managers/RMC       → SerialNumber "SGHD3TLNDD"
#
# 즉 `-000` 은 오염된 값이 아니라 "물리 시리얼 + nPartition 번호" 형식의 정상 값이다.
# 다만 자산 관리 시스템은 **물리 장비 시리얼**로 서버를 관리하므로, 접미사가 붙은 값을
# 그대로 내보내면 같은 서버가 서로 다른 시리얼로 판정된다.
#
# 운영 전제 (SK하이닉스): CSUS 3200 1대당 파티션 1개만 사용한다 — 물리 장비 ↔ OS 서버
# 1:1. 따라서 파티션 번호를 별도 식별자로 보존할 필요가 없다.
#
# 적용 범위
# ---------
# **OS 채널(os-gather)의 시스템 시리얼만** 대상이다. Redfish / ESXi 채널은 건드리지
# 않는다 (Redfish `data.hardware.serial` 은 `Systems/Partition0.SerialNumber` 원문 유지 —
# docs/ai/contracts/serial-number.md 29-6).
#
# 안전 장치 (셋을 **모두** 만족할 때만 접미사를 제거한다)
# ------------------------------------------------------
#   1. vendor 가 HPE 계열 alias 에 정확히 일치
#   2. model 이 CSUS 3200 model_patterns 중 하나에 매칭
#   3. 시리얼이 `-<숫자 3자리>` 로 끝남
#
# 하나라도 어긋나면 **입력을 글자 그대로 돌려준다.** 일반 HPE ProLiant / Dell / Lenovo /
# 시리얼에 하이픈이 정상적으로 들어간 장비는 값이 바뀌지 않는다.
# 단순 `split('-')[0]` 같은 광범위 절단은 쓰지 않는다.
#
# 사용법 (Ansible task)
# ---------------------
#   - set_fact:
#       _l_serial_val: "{{ _l_serial_val | normalize_os_serial(vendor, model) }}"
#
# 호출부는 vendor 이름을 알 필요가 없다 (rule 12 R1 — gather 코드 vendor-agnostic 유지).
# 벤더 지식은 이 파일 한 곳에만 있고, 아래 두 상수는 저장소 정본의 **미러**다:
#   CSUS3200_VENDOR_ALIASES ← common/vars/vendor_aliases.yml :: vendor_aliases.hpe
#   CSUS3200_MODEL_PATTERNS ← adapters/redfish/hpe_csus_3200.yml :: match.model_patterns
# 두 미러의 drift 는 tests/unit/test_csus_partition_serial.py 가 상시 검증한다
# (test_vendor_normalizer_sot.py / test_jedec_drift_guard.py 와 동일한 미러+가드 패턴).
#
# Origin (rule 96 R1 / R1-A)
#   source: tests/fixtures/redfish/real_hpe_csus3200/recording.json
#           (2026-06-15 사이트 실 4노드 read-only 미러 캡처 — 1차 권위)
#   source: adapters/redfish/hpe_csus_3200.yml (model_patterns 정본 + 그 파일의 HPE 공식 sources)
#   source: common/vars/vendor_aliases.yml (vendor alias 정본)
#   lab: 상설 lab 부재. OS(DMI) 측 CSUS 3200 캡처는 아직 없다 — Redfish 실측에서 확인된
#        모델 표기를 그대로 쓴다. 사이트 DMI product_name 이 다르면 model_patterns 를
#        Additive 로 확장한다 (미매치 시 동작은 "정규화 안 함" = 무해).
# ==============================================================================

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import re

# ── vendor alias 미러 (common/vars/vendor_aliases.yml :: vendor_aliases.hpe) ──
# 비교는 lower + 공백 정규화 후 **완전 일치**. 부분 문자열 매칭을 쓰지 않는 이유는
# 'hp' 같은 짧은 alias 가 무관한 문자열에 얹히는 것을 막기 위해서다.
CSUS3200_VENDOR_ALIASES = frozenset(
    {
        "hpe",
        "hewlett packard enterprise",
        "hewlett packard enterprise co.",
        "hewlett-packard",
        "hp enterprise",
        "hp",
    }
)

# ── model pattern 미러 (adapters/redfish/hpe_csus_3200.yml :: match.model_patterns) ──
# 매칭 의미는 adapter 와 동일하게 `re.search` + IGNORECASE
# (module_utils/adapter_common.pattern_match_any 와 같은 규칙).
# ".*Compute Scale-up Server 3200.*" 가 실측 Chassis Model
# "Compute Scale-up Server 3200, 4S XNC Base Chassis" 같은 변형까지 덮는다.
CSUS3200_MODEL_PATTERNS = (
    r"^Compute Scale-up Server 3200.*",
    r"^HPE Compute Scale-up Server.*3200.*",
    r".*Compute Scale-up Server 3200.*",
    r".*CSUS.*3200.*",
)

# ── nPartition 접미사 ────────────────────────────────────────────────────────
# `-` + 숫자 정확히 3자리 + 문자열 끝. 앞의 base 는 1자 이상이어야 한다
# (`-000` 처럼 base 가 없는 값은 정규화 대상이 아니다).
# greedy `.+` 라서 `AB-123-000` 은 마지막 한 덩어리만 떨어져 `AB-123` 이 된다.
NPARTITION_SUFFIX_RE = re.compile(r"^(?P<base>.+)-[0-9]{3}$")

_WHITESPACE_RE = re.compile(r"\s+")


def _clean(value):
    """비교용 정규화 — str 강제 + 양끝 공백 제거 + 내부 연속 공백 1칸."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return _WHITESPACE_RE.sub(" ", value).strip()


def _model_matches(model):
    """model 이 CSUS 3200 패턴 중 하나에 매칭되는지 (adapter 와 동일한 규칙)."""
    if not model:
        return False
    for pattern in CSUS3200_MODEL_PATTERNS:
        try:
            if re.search(pattern, model, re.IGNORECASE):
                return True
        except re.error:  # pragma: no cover — 상수라 발생하지 않는다
            if pattern.lower() in model.lower():
                return True
    return False


def is_csus_3200(vendor, model):
    """(vendor, model) 이 HPE Compute Scale-up Server 3200 인지 판정.

    vendor 와 model 이 **둘 다** 확인돼야 True. 한쪽이라도 비면 False 다
    (정보가 없으면 정규화하지 않는다 — fail-safe).
    """
    vendor_clean = _clean(vendor).lower()
    if vendor_clean not in CSUS3200_VENDOR_ALIASES:
        return False
    return _model_matches(_clean(model))


def normalize_os_serial(serial, vendor=None, model=None):
    """OS 가 읽은 시스템 시리얼에서 nPartition 접미사를 제거한다.

    Args:
        serial: OS 에서 수집한 시리얼 (DMI product_serial / Win32_BIOS.SerialNumber 등).
                None / 비-str 은 그대로 통과시킨다.
        vendor: 같은 수집에서 확인된 제조사 (DMI sys_vendor / Win32_ComputerSystem.Manufacturer).
        model:  같은 수집에서 확인된 모델 (DMI product_name / Win32_ComputerSystem.Model).

    Returns:
        CSUS 3200 이면서 시리얼이 `-<숫자 3자리>` 로 끝날 때만 접미사를 뗀 문자열,
        그 외에는 **입력 그대로**.

    Examples:
        >>> normalize_os_serial("SGHD3TLNDD-000", "HPE", "Compute Scale-up Server 3200")
        'SGHD3TLNDD'
        >>> normalize_os_serial("CZ12345678", "HPE", "ProLiant DL380 Gen11")
        'CZ12345678'
        >>> normalize_os_serial("ABCDEF-000", "Dell Inc.", "PowerEdge R760")
        'ABCDEF-000'
    """
    if not isinstance(serial, str):
        return serial

    stripped = serial.strip()
    if not stripped:
        return serial

    if not is_csus_3200(vendor, model):
        return serial

    matched = NPARTITION_SUFFIX_RE.match(stripped)
    if not matched:
        return serial

    return matched.group("base")


class FilterModule(object):
    """Ansible filter plugin — OS 채널 시리얼 표시값 정규화"""

    def filters(self):
        return {
            "normalize_os_serial": normalize_os_serial,
        }
