"""Redfish adapter capabilities ↔ 채널 섹션 정합 (2026-10-12).

재현한 결함: 성공 경로(normalize_standard.yml)는 Redfish 지원 섹션을 9개(hardware … thermal — system 은 BMC 가 OS 를 모르므로 not_supported)로
내는데, rescue 경로는 adapter 의 `capabilities.sections_supported` 를 썼고 그 목록은 30개 모두 `system` 을 포함하고 `thermal` 을 빠뜨렸다.
그래서 같은 BMC 가 성공 경로에서는 system=not_supported, 실패 경로에서는 system=failed · thermal=not_supported 로 나왔다.

고친 규칙: adapter capabilities 는 성공 경로가 지원할 수 있는 섹션의 부분집합이며 `system` 을 넣지 않고, power 를 지원하면 thermal 도 지원한다.
rescue 기본값 · always fallback 도 같은 규칙이다.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SUCCESS_PATH_SUPPORTED = {"hardware", "bmc", "cpu", "memory", "storage", "network", "firmware", "power", "thermal"}


def _adapters():
    for path in sorted((REPO / "adapters" / "redfish").glob("*.yml")):
        yield path.name, yaml.safe_load(path.read_text(encoding="utf-8"))


def test_normalize_standard_supported_list_is_the_reference():
    text = (REPO / "redfish-gather" / "tasks" / "normalize_standard.yml").read_text(encoding="utf-8")
    m = re.search(r"_sections_supported_fragment: >-\s*\n\s*\{\{\s*\[([^\]]+)\]", text)
    assert m, "normalize_standard.yml 의 지원 섹션 목록을 찾지 못함"
    listed = {s.strip().strip("'\"") for s in m.group(1).split(",")}
    assert listed == SUCCESS_PATH_SUPPORTED


def test_every_adapter_capability_is_a_subset_without_system():
    for name, d in _adapters():
        caps = set(d["capabilities"]["sections_supported"])
        assert "system" not in caps, f"{name}: system 은 Redfish 성공 경로가 지원하지 않는 섹션이다"
        assert "users" not in caps, name
        assert caps <= SUCCESS_PATH_SUPPORTED, f"{name}: {sorted(caps - SUCCESS_PATH_SUPPORTED)}"
        assert ("thermal" in caps) == ("power" in caps), f"{name}: power 와 thermal 은 같은 Chassis 리소스에서 온다"


def test_rescue_default_and_always_fallback_follow_the_same_rule():
    site = (REPO / "redfish-gather" / "site.yml").read_text(encoding="utf-8")
    m = re.search(r"_fail_sec_supported:.*?default\(\[([^\]]+)\]\)", site, re.S)
    assert m
    default = {s.strip().strip("'\"") for s in m.group(1).replace("\n", "").split(",")}
    assert default == SUCCESS_PATH_SUPPORTED
    # always(최후 fallback) 블록은 json_only 의 합성 실패 shape 와 같은 표를 쓴다 — test_json_only_fallback_shape 가 둘을 맞춘다
    assert "'sections': {'system': 'failed', 'hardware': 'failed'" in site
