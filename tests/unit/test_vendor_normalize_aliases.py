"""redfish `_normalize_vendor_from_aliases` 단위 회귀 (cross-channel reference).

배경:
    `vendor` envelope 필드는 채널 무관 canonical 이어야 한다. redfish 경로의
    정규화 정본은 `_normalize_vendor_from_aliases` 인데 **직접 단위 테스트가 없었다**
    (production code = bug 후보). 본 파일이 그 reference 동작을 고정한다.

    그 알고리즘 = (1) 정확 매칭 → (2) **부분(substring) 매칭** → (3) 'unknown'.
    핵심은 (2): "Dell Inc"(마침표 없음) 같은 변형도 substring 으로 'dell' 로 수렴한다.

    divergence (esxi 측 미해결 — Jenkins Agent 후속):
        `esxi-gather/site.yml` 의 inline Jinja2 정규화는 **정확 매칭만** 하고 substring
        fallback 이 없어, 같은 "Dell Inc" 가 redfish='dell' ↔ esxi=raw('Dell Inc') 로
        divergence 한다 (envelope `vendor` 필드 채널 불일치). 본 테스트는 redfish reference
        를 잠가, esxi 가 이 동작에 맞춰 고쳐질 때의 기준선이 된다 (full parity 는
        ansible-playbook 필요).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

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

_norm = rg._normalize_vendor_from_aliases


# ── 1차: 정확 매칭 (vendor_aliases.yml + _FALLBACK_VENDOR_MAP) ────────────────
@pytest.mark.parametrize("mfr_lower,canon", [
    ("dell inc.", "dell"),
    ("dell emc", "dell"),
    ("hewlett packard enterprise", "hpe"),
    ("hp", "hpe"),
    ("lenovo", "lenovo"),
    ("supermicro", "supermicro"),
])
def test_exact_alias_match(mfr_lower, canon):
    """정확 alias 키 → canonical (1차 매칭)."""
    assert _norm(mfr_lower) == canon


# ── 2차: 부분(substring) 매칭 — 핵심 (esxi 가 빠뜨린 fallback) ──────────
@pytest.mark.parametrize("mfr_lower,canon", [
    ("dell inc", "dell"),                 # 마침표 없음 — 대표 케이스
    ("dell inc. poweredge r740", "dell"), # alias superstring
    ("hpe proliant dl380", "hpe"),
    ("hewlett packard enterprise company", "hpe"),
    ("lenovo group", "lenovo"),
    ("cisco systems inc", "cisco"),
])
def test_substring_fallback_match(mfr_lower, canon):
    """부분 매칭(2차) — 변형 문자열이 canonical 로 수렴.

    이 fallback 이 redfish 에는 있고 esxi inline 에는 없다 → divergence 의 원인.
    redfish reference 가 substring 수렴함을 고정(회귀 방어 + esxi fix 기준선).
    """
    assert _norm(mfr_lower) == canon


def test_ar1_reference_case_dell_inc_no_period():
    """대표: 'dell inc'(마침표 없음) → redfish 는 'dell' 로 정규화.

    esxi inline 은 정확 매칭만 하므로 raw('dell inc') 를 그대로 반환 → vendor 필드
    채널 divergence. 본 assert 가 redfish 기준선이며, esxi 수정 후 동일 결과여야 한다.
    """
    assert _norm("dell inc") == "dell"
    assert _norm("dell inc") != "dell inc"  # raw 패스스루(esxi 현 동작)가 아님


# ── 3차: 미매칭 → 'unknown' ──────────────────────────────────────────────────
@pytest.mark.parametrize("mfr_lower", [
    "nonexistent vendor zzz",
    "qwerty123",
])
def test_unmatched_returns_unknown(mfr_lower):
    """alias/substring 어디에도 안 걸리면 'unknown' (raw 패스스루 아님)."""
    assert _norm(mfr_lower) == "unknown"


def test_known_vendors_all_canonical():
    """대표 5 vendor 의 흔한 표기가 전부 canonical 로 수렴."""
    cases = {
        "dell inc.": "dell", "hpe": "hpe", "lenovo": "lenovo",
        "supermicro": "supermicro", "cisco": "cisco",
    }
    for raw, canon in cases.items():
        assert _norm(raw) == canon, f"{raw!r} → {_norm(raw)!r} (기대 {canon!r})"
