"""ESXi 9.x adapter — 선택 계약 고정.

배경. `adapters/esxi/` 에 `^6\\.` `^7\\.` `^8\\.` 만 있어서 ESXi 9.0.0 호스트 5대가
전부 `esxi_generic` 으로 떨어졌다 (2026-08-13 실측, lab 10.100.64.91~95).
네 adapter 의 `sections_supported` 가 같아 수집 항목 손실은 없었고 `meta.adapter_id`
문자열만 사실과 달랐다.

이 테스트가 고정하는 것은 두 가지다.

1. **버전이 들어오면 세대별로 갈린다.** `9.0.0` → `esxi_9x`.
2. **버전을 못 얻으면 `esxi_8x` 가 유지된다.** 이건 tie-break 에 기대는 계약이라
   따로 못 박는다 — `esxi_9x` 의 priority 를 `esxi_8x`(100)보다 높이면 이 계약이
   깨진다. 인증 실패로 `ansible_distribution_version` 을 못 얻은 상황에서 최신
   세대를 단정하지 않겠다는 뜻이라 값이 아니라 의도를 지켜야 한다.
   (`tests/unit/test_adapter_selection_facts_r17.py` 의 같은 assert 를 보강한다.)
"""
from __future__ import annotations

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
ESXI_DIR = REPO / "adapters" / "esxi"


def _load():
    out = []
    for path in sorted(ESXI_DIR.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out.append((path.name, data))
    return out


def _rank(facts: dict):
    """adapter_loader.run() 과 같은 순서로 후보를 매긴다.

    파일명 오름차순 스캔 + `sort(reverse=True)` 의 안정성이 tie-break 다
    (`lookup_plugins/adapter_loader.py:253`). 동률일 때 어느 쪽이 이기는지가
    이 테스트의 관심사라 그 순서를 그대로 재현해야 한다.
    """
    matched = [
        (adapter_score(d, facts, ALIASES), d.get("adapter_id", name))
        for name, d in _load()
        if adapter_matches(d, facts, ALIASES)
    ]
    matched = [m for m in matched if m[0] > -9999]
    matched.sort(key=lambda x: x[0], reverse=True)
    return matched


def _select(facts: dict) -> str:
    r = _rank(facts)
    return r[0][1] if r else "(none)"


def test_esxi_9x_adapter_exists():
    assert (ESXI_DIR / "esxi_9x.yml").is_file()


@pytest.mark.parametrize("version,expected", [
    ("9.0.0", "esxi_9x"),
    ("9.0", "esxi_9x"),
    ("9.1.0", "esxi_9x"),
])
def test_esxi_9x_selected_for_9_series(version, expected):
    assert _select({"version": version}) == expected


def test_esxi_9x_does_not_steal_other_generations():
    """9x 추가가 기존 세대 판정을 건드리지 않는다."""
    assert _select({"version": "8.0 U2"}) == "esxi_8x"
    assert _select({"version": "7.0.3"}) == "esxi_7x"
    assert _select({"version": "6.7.0"}) == "esxi_6x"


def test_esxi_8x_disqualified_on_9_series():
    """9.0.0 이면 esxi_8x 는 후보에서 빠진다 — 동률이어도 판정이 갈리는 이유."""
    ids = [i for _, i in _rank({"version": "9.0.0"})]
    assert "esxi_8x" not in ids
    assert ids[0] == "esxi_9x"


def test_empty_version_keeps_esxi_8x():
    """버전을 못 얻으면 최신 세대를 단정하지 않는다.

    `esxi_9x.priority` 를 100 초과로 올리면 여기서 깨진다. 그게 이 테스트의 목적이다.
    """
    assert _select({}) == "esxi_8x"


def test_esxi_9x_priority_not_above_8x():
    """의도를 값으로도 못 박는다 — tie-break 에만 기대지 않는다."""
    by_id = {d["adapter_id"]: d for _, d in _load()}
    assert by_id["esxi_9x"]["priority"] <= by_id["esxi_8x"]["priority"]


def test_esxi_9x_sections_match_siblings():
    """세대 adapter 는 지원 섹션이 같아야 한다 — 9x 만 다르면 수집 결과가 갈린다."""
    by_id = {d["adapter_id"]: d for _, d in _load()}
    ref = by_id["esxi_8x"]["capabilities"]["sections_supported"]
    for aid in ("esxi_6x", "esxi_7x", "esxi_9x", "esxi_generic"):
        assert by_id[aid]["capabilities"]["sections_supported"] == ref, aid
