"""Cross-channel regression test fixtures.

Loads all 8 baseline JSONs (5 redfish vendors + 3 OS variants) and exposes
them as a unified collection, so tests can validate cross-channel envelope
consistency (rule 13 R5 — 13 fields fixed across channels).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = PROJECT_ROOT / "schema" / "baseline_v1"


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# Baseline registry: (label, target_type, expected_collection_method, file_name)
BASELINE_REGISTRY: list[tuple[str, str, str, str]] = [
    ("dell_redfish", "redfish", "redfish_api", "dell_baseline.json"),
    ("hpe_redfish", "redfish", "redfish_api", "hpe_baseline.json"),
    ("lenovo_redfish", "redfish", "redfish_api", "lenovo_baseline.json"),
    ("cisco_redfish", "redfish", "redfish_api", "cisco_baseline.json"),
    # 2026-10-27 (사용자 FIX 5): CSUS 3200 은 용인 2차 Mock csus3200_01(RMC 1.77.30) 을 HTTPS 미러 재생 + 실제
    #   playbook 으로 수집한 실측 봉투다 (2026-05-29 ~ 2026-10-27 의 합성 MOCK 교체). 출처·수정 2곳은
    #   diagnosis.details.baseline_origin. 구조 가드: tests/regression/test_csus_mock_consistency.py
    ("hpe_csus_3200_redfish", "redfish", "redfish_api", "hpe_csus_3200_baseline.json"),
    ("ubuntu_os", "os", "agent", "ubuntu_baseline.json"),
    ("windows_os", "os", "agent", "windows_baseline.json"),
    ("rhel810_raw_fallback_os", "os", "agent",
     "rhel810_raw_fallback_baseline.json"),
    ("esxi_cisco", "esxi", "vsphere_api", "esxi_baseline.json"),
]


@pytest.fixture(
    params=BASELINE_REGISTRY,
    ids=[entry[0] for entry in BASELINE_REGISTRY],
)
def baseline_envelope(request) -> dict:
    """Yields each baseline envelope dict in turn (parametrized)."""
    label, target_type, collection_method, file_name = request.param
    path = BASELINE_DIR / file_name
    if not path.exists():
        pytest.skip(f"baseline missing: {file_name}")
    envelope = _load_json(path)
    envelope["__label"] = label
    envelope["__expected_target_type"] = target_type
    envelope["__expected_collection_method"] = collection_method
    return envelope


@pytest.fixture
def all_baselines() -> Iterator[dict]:
    """Yields all baseline envelopes (non-parametrized, for aggregate checks)."""
    out: list[dict] = []
    for label, target_type, collection_method, file_name in BASELINE_REGISTRY:
        path = BASELINE_DIR / file_name
        if not path.exists():
            continue
        env = _load_json(path)
        env["__label"] = label
        env["__expected_target_type"] = target_type
        env["__expected_collection_method"] = collection_method
        out.append(env)
    return out
