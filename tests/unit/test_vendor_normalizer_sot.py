"""Vendor 정규화 Source-of-Truth 통합 게이트 (2026-08-12).

배경 (Location + Vendor Credential Resolver 선행 필수조건):
    Credential Vault 경로가 `vault/<location>/redfish/<vendor>.yml` 로 vendor 에서
    파생된다. 정규화 결과가 구현마다 갈리면 그 차이가 곧 **자격증명 오선택**이고,
    이는 "다른 Vendor 의 Credential 을 시도하지 않는다" 원칙을 정면으로 깬다.

    종전 구현 3개:
      1. redfish-gather/library/redfish_gather.py `_normalize_vendor_from_aliases`
         — 무인증 probe 가 반환하는 vendor 의 정본. stdlib-only 라 남긴다 (rule 10 R2).
      2. redfish-gather/tasks/detect_vendor.yml 인라인 Jinja2
         — **제거됨**. filter_plugins/vendor_normalizer.py 로 대체.
      3. module_utils/adapter_common.py `normalize_vendor` — 알고리즘 정본.

    이 파일이 잠그는 것:
      T22  1번(라이브러리) 과 3번(필터) 의 결과가 실측 입력 전량에서 동일한가
      T23  `_FALLBACK_VENDOR_MAP` 과 vendor_aliases.yml 이 동치인가
      T24  필터 반환값이 **항상** canonical 집합 ∪ {'unknown'} 안에 있는가
           (vault 경로 조각으로 임의 문자열이 들어가는 것을 구조적으로 차단)

주의: 고정 개수를 단언하지 않는다 (CLAUDE.md §2). 집합 동치만 본다.
"""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "module_utils"))
sys.path.insert(0, str(REPO / "filter_plugins"))

# redfish_gather 는 ansible.module_utils.basic 을 import 한다 — 단위 실행용 stub.
_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402
from vendor_normalizer import canonical_vendor  # noqa: E402

ALIASES_PATH = REPO / "common" / "vars" / "vendor_aliases.yml"


def _vendor_aliases() -> dict:
    data = yaml.safe_load(ALIASES_PATH.read_text(encoding="utf-8")) or {}
    return data.get("vendor_aliases", {})


VENDOR_ALIASES = _vendor_aliases()
CANONICAL_KEYS = set(VENDOR_ALIASES.keys())


def _observed_manufacturer_strings() -> list[str]:
    """tests/fixtures/**.json 에서 관측된 Manufacturer / vendor 문자열 전수 추출.

    합성 케이스가 아니라 **실장비 / 에뮬레이터 / DMTF mockup 응답에서 실제로 나온
    문자열**이어야 동치 증명에 의미가 있다 (rule 25 R7-A-1 실측 우선).
    부품 제조사(Broadcom / Samsung 등)도 함께 걸리는데, 그것도 정규화기에 들어갈 수
    있는 입력이므로 제외하지 않는다.
    """
    patterns = (
        re.compile(r'"[Mm]anufacturer"\s*:\s*"([^"]*)"'),
        re.compile(r'"[Vv]endor"\s*:\s*"([^"]*)"'),
    )
    found: set[str] = set()
    for path in (REPO / "tests" / "fixtures").rglob("*.json"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pat in patterns:
            found.update(pat.findall(text))
    return sorted(found)


def _all_inputs() -> list[str]:
    """동치 검증 입력 = 실측 fixture 문자열 ∪ 전체 alias ∪ canonical ∪ 경계값."""
    values: set[str] = set(_observed_manufacturer_strings())
    for alias_list in VENDOR_ALIASES.values():
        values.update(a for a in alias_list if isinstance(a, str))
    values.update(CANONICAL_KEYS)
    values.update({"", "   ", "unknown", "Dell Inc", "dell inc",
                   "HPE ProLiant DL380 Gen10", "nonexistent vendor zzz"})
    return sorted(values)


ALL_INPUTS = _all_inputs()


# ── T22: 라이브러리 정규화 ↔ 필터 정규화 동치 ────────────────────────────────
def test_fixture_corpus_is_not_empty():
    """실측 입력이 0건이면 아래 동치 테스트가 공허하게 통과한다 — 그것부터 막는다."""
    observed = _observed_manufacturer_strings()
    assert observed, "tests/fixtures 에서 Manufacturer/vendor 문자열을 하나도 못 찾았다"


@pytest.mark.parametrize("raw", ALL_INPUTS)
def test_library_and_filter_agree(raw):
    """`redfish_gather` 정규화 == `canonical_vendor` 필터.

    이 동치가 깨지면, 무인증 probe 가 판정한 vendor 와 Vault 경로를 만드는 vendor 가
    달라진다 → 엉뚱한 Location/Vendor 자격증명 로드.
    """
    lib = rg._normalize_vendor_from_aliases(str(raw).strip().lower())
    flt = canonical_vendor(raw, VENDOR_ALIASES)
    assert lib == flt, (
        f"정규화 divergence: {raw!r} → library={lib!r} filter={flt!r}. "
        "Vault 경로가 vendor 에서 파생되므로 이 차이는 자격증명 오선택으로 이어진다."
    )


def test_removed_jinja_normalizer_is_gone():
    """detect_vendor.yml 에 인라인 정규화 루프가 되살아나지 않았는지 (구현 3개 회귀 방어)."""
    text = (REPO / "redfish-gather" / "tasks" / "detect_vendor.yml").read_text(encoding="utf-8")
    assert "canonical_vendor" in text, "detect_vendor.yml 이 공통 필터를 쓰지 않는다"
    assert "namespace(canon=" not in text, (
        "detect_vendor.yml 에 인라인 Jinja2 정규화가 재도입됐다 — 정규화 SoT 가 다시 갈라진다"
    )


# ── T23: _FALLBACK_VENDOR_MAP ↔ vendor_aliases.yml 동치 ──────────────────────
def test_fallback_map_matches_vendor_aliases():
    """라이브러리 내장 fallback 맵이 vendor_aliases.yml 과 동치인가.

    종전에는 주석(`동기화 필요`)과 advisory 스크립트로만 강제됐다. YAML 로드가 실패한
    환경에서는 이 맵이 정규화 정본이 되므로, 두 맵이 갈리면 환경에 따라 vendor 판정이
    달라지고 곧 Vault 경로가 달라진다.
    """
    yaml_flat = {
        alias.strip().lower(): canonical
        for canonical, alias_list in VENDOR_ALIASES.items()
        for alias in alias_list
        if isinstance(alias, str)
    }
    fallback = rg._FALLBACK_VENDOR_MAP

    only_yaml = sorted(set(yaml_flat) - set(fallback))
    only_fallback = sorted(set(fallback) - set(yaml_flat))
    conflicts = {
        k: (yaml_flat[k], fallback[k])
        for k in set(yaml_flat) & set(fallback)
        if yaml_flat[k] != fallback[k]
    }

    assert not only_yaml, f"vendor_aliases.yml 에만 있는 alias: {only_yaml}"
    assert not only_fallback, f"_FALLBACK_VENDOR_MAP 에만 있는 alias: {only_fallback}"
    assert not conflicts, f"canonical 값 충돌: {conflicts}"


# ── T24: 필터 반환값의 폐쇄성 (vault 경로 주입 차단) ─────────────────────────
@pytest.mark.parametrize("raw", ALL_INPUTS + [
    "../../etc/passwd", "dell/../hpe", "  ", None, 12345, "Contoso",
])
def test_filter_output_is_always_canonical_or_unknown(raw):
    """필터 반환값은 **항상** canonical 집합 ∪ {'unknown'}.

    이것이 `vault/<loc>/redfish/<vendor>.yml` 경로에 임의 문자열이 들어가는 것을
    구조적으로 막는 1차 방어선이다 (2차는 resolver 의 known_vendors 검증).
    """
    result = canonical_vendor(raw, VENDOR_ALIASES)
    assert result in CANONICAL_KEYS | {"unknown"}, (
        f"{raw!r} → {result!r} 는 등록된 canonical 이 아니다 — 경로 조각으로 쓸 수 없다"
    )


def test_empty_manufacturer_does_not_become_a_vendor():
    """공백-only Manufacturer 가 특정 vendor 로 확정되면 안 된다 (2026-08-12 fix 회귀 방어).

    `_normalize_vendor_from_aliases('')` 의 부분 매칭은 `'' in key` 가 항상 참이라
    dict 첫 항목의 vendor 를 반환했다. 실제 도달 경로가 있다 —
    redfish_gather.py 의 Chassis/Managers/Systems Manufacturer fallback 이
    `mfr.strip().lower()` 로 호출하므로 Manufacturer 가 "   " 이면 빈 문자열이 된다.
    """
    assert rg._normalize_vendor_from_aliases("") == "unknown"
    assert canonical_vendor("   ", VENDOR_ALIASES) == "unknown"
    assert canonical_vendor("", VENDOR_ALIASES) == "unknown"


def test_filter_without_aliases_returns_unknown():
    """aliases 미제공 시 canonical 을 지어내지 않는다."""
    assert canonical_vendor("Dell Inc.", None) == "unknown"
    assert canonical_vendor("Dell Inc.", {}) == "unknown"


def test_filter_module_registers_name():
    """Ansible 이 실제로 찾는 이름으로 등록돼 있는지."""
    from vendor_normalizer import FilterModule

    assert "canonical_vendor" in FilterModule().filters()


def test_no_secret_in_module_source():
    """정규화 경로에 자격증명 관련 어휘가 섞이지 않았는지 (경계 유지)."""
    text = (REPO / "filter_plugins" / "vendor_normalizer.py").read_text(encoding="utf-8")
    for word in ("password", "passwd", "secret"):
        assert word not in text.lower(), f"vendor_normalizer.py 에 {word!r} 등장"


def test_canonical_keys_are_path_safe():
    """canonical 키 자체가 경로 조각으로 안전한가 (vault 경로에 그대로 들어간다)."""
    for key in CANONICAL_KEYS:
        assert re.fullmatch(r"[a-z0-9_-]+", key), (
            f"canonical vendor {key!r} 가 경로에 쓰기 안전한 형식이 아니다"
        )


def test_json_serialisable_result():
    """set_fact 로 들어가므로 JSON 직렬화 가능해야 한다."""
    json.dumps({"vendor": canonical_vendor("Dell Inc.", VENDOR_ALIASES)})
