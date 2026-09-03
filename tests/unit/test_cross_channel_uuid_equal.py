"""채널 간 같은 물리 장비 = 같은 식별자 (2026-09-03, B-06).

같은 Cisco C220(FCH2116V1V0) 을 Redfish 와 ESXi 로 본 baseline 이 저장소에 이미 있다.
UUID 는 SMBIOS 바이트 순서 규약 차이(앞 3그룹 반전) + 대소문자만 다르다 — `uuid_equal` 로
같은 장비임을 판정할 수 있어야 하고, serial 은 문자열이 같아야 한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from identity_normalizer import normalize_uuid, uuid_byteswap, uuid_equal  # noqa: E402

BASE = REPO / "schema" / "baseline_v1"


def _load(name: str) -> dict:
    return json.loads((BASE / name).read_text(encoding="utf-8"))


def test_same_box_redfish_vs_esxi_correlation():
    rf = _load("cisco_baseline.json")
    ex = _load("esxi_baseline.json")
    assert rf["correlation"]["serial_number"] == ex["correlation"]["serial_number"] == "FCH2116V1V0"
    a, b = rf["correlation"]["system_uuid"], ex["correlation"]["system_uuid"]
    assert normalize_uuid(a) != normalize_uuid(b), "표기 규약이 다른데 같다면 fixture 가 바뀐 것"
    assert uuid_equal(a, b), "같은 장비의 UUID 를 같다고 판정하지 못한다 (B-06)"
    assert uuid_byteswap(normalize_uuid(a)) == normalize_uuid(b)


def test_normalize_uuid_is_idempotent_on_baseline_values():
    for name in ("cisco_baseline.json", "esxi_baseline.json", "dell_baseline.json", "windows_2022_baseline.json"):
        v = _load(name)["correlation"]["system_uuid"]
        n = normalize_uuid(v)
        assert n == n.lower() and normalize_uuid(n) == n
