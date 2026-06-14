"""Round 17 #9/#10 — adapter selection facts 가 실제 generation 매칭을 가능케 하는지 검증.

#9 (esxi): site.yml 이 collect_facts 전에 facts={} 로 선택 → version_patterns(^6./^7./^8.)
   가 죽고 priority 만으로 esxi_8x 항상 선택. 수정: collect_facts 뒤로 옮겨 실제 version 전달.
#10 (windows): site.yml 이 facts.version 으로 ansible_os_product_type(=SKU 'server')를 넘겨
   version_patterns(2019/2022, 10.0.NNNNN)와 절대 안 맞아 generation adapter 가 죽고
   os_windows_generic 만 선택. 수정: ansible_kernel(빌드 10.0.20348.0)을 넘김.

본 테스트는 실제 adapters/{esxi,os}/*.yml + adapter_common 으로 선택을 시뮬레이션해,
'올바른 facts 를 넘기면 generation adapter 가 선택된다'(fix 의 전제)를 고정한다. 실제 fact
값(ansible_kernel)은 tests/reference 캡처로 grounding.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "module_utils"))

from adapter_common import (  # noqa: E402
    adapter_matches,
    adapter_score,
    load_vendor_aliases,
)

ALIASES = load_vendor_aliases(str(REPO / "common" / "vars" / "vendor_aliases.yml"))


def _select(channel: str, facts: dict) -> str:
    matched = []
    for path in sorted((REPO / "adapters" / channel).glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if adapter_matches(data, facts, ALIASES):
            sc = adapter_score(data, facts, ALIASES)
            if sc > -9999:
                matched.append((sc, data.get("adapter_id", path.name)))
    if not matched:
        return "(none)"
    matched.sort(key=lambda x: x[0], reverse=True)
    return matched[0][1]


# ── #9 ESXi: 실제 버전이 전달되면 generation 별로 올바로 선택 ──────────────────
@pytest.mark.parametrize("version,expected", [
    ("8.0.2", "esxi_8x"),
    ("8.0 U2", "esxi_8x"),
    ("7.0.3", "esxi_7x"),
    ("6.7.0", "esxi_6x"),
])
def test_esxi_version_selects_generation(version, expected):
    assert _select("esxi", {"version": version}) == expected


def test_esxi_empty_facts_was_priority_only_bug():
    """facts={} (구 동작): version 빈 값이라 전부 매칭 → priority 최상위 esxi_8x 만 선택 → 사고 재현."""
    assert _select("esxi", {}) == "esxi_8x"
    # 7.0 호스트인데도 구 코드라면 esxi_8x 로 오선택됐음을 대비 (fix 전제)
    assert _select("esxi", {"version": "7.0.3"}) != _select("esxi", {})


# ── #10 Windows: ansible_kernel(빌드)이면 generation 선택, SKU 면 generic 으로 죽음 ──
@pytest.mark.parametrize("version,expected", [
    ("10.0.20348.0", "os_windows_2022"),   # ansible_kernel (fix)
    ("10.0.17763.5122", "os_windows_2019"),
])
def test_windows_kernel_build_selects_generation(version, expected):
    assert _select("os", {"os_type": "windows", "version": version}) == expected


def test_windows_sku_product_type_was_dead_bug():
    """구 동작: facts.version=ansible_os_product_type('server') 는 non-empty 이고 어떤
    version_pattern 과도 안 맞아 generation adapter 가 -9999 로 전멸 → generic 만 남음 (사고 재현).
    (참고: '' 빈 값은 'info unavailable→pass' 정책상 disqualify 아님 → priority tie 로 2019 가 떠서
    별개 케이스. 실 호스트의 ansible_os_product_type 은 항상 'server' 등 non-empty 라 generic 으로 죽음.)"""
    assert _select("os", {"os_type": "windows", "version": "server"}) == "os_windows_generic"
    assert _select("os", {"os_type": "windows", "version": "workstation"}) == "os_windows_generic"


# ── #22 Cisco CIMC: 하이픈형 System.Model 도 매칭 ─────────────────────────────
@pytest.mark.parametrize("model", [
    "UCSC-C220-M5SX",   # cisco_cimc_v3 fixture
    "UCSC-C220-M4S",    # v2
    "UCSC-C240-M6L",    # v4
    "UCS C220 M5",      # ServiceRoot.Product 공백형도 보존
])
def test_cisco_cimc_hyphenated_model_matches(model):
    sel = _select("redfish", {"vendor": "Cisco", "model": model, "firmware": "4.2"})
    assert sel == "redfish_cisco_cimc", f"{model!r} -> {sel}"


def _load_ansible_setup(path: Path) -> dict:
    """ansible 'host | SUCCESS => { ... }' 출력에서 ansible_facts 추출."""
    raw = path.read_text(encoding="utf-8")
    brace = raw.index("{")
    return json.loads(raw[brace:]).get("ansible_facts", {})


def test_reference_capture_grounds_kernel_choice():
    """실 win2022 캡처: ansible_kernel 은 generation 패턴 매칭, os_product_type 은 미매칭(=구 버그)."""
    caps = list((REPO / "tests" / "reference" / "os" / "win2022").glob("*/setup.json"))
    if not caps:
        pytest.skip("win2022 reference capture 없음")
    af = _load_ansible_setup(caps[0])
    kernel = af.get("ansible_kernel", "")
    sku = af.get("ansible_os_product_type", "")
    # ansible_kernel 로는 generation 선택됨
    assert _select("os", {"os_type": "windows", "version": kernel}) == "os_windows_2022"
    # ansible_os_product_type(구 fact)로는 generic 으로 죽음 (사고 재현)
    assert _select("os", {"os_type": "windows", "version": sku}) == "os_windows_generic"
