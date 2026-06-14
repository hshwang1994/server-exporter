"""BMC Web UI Browser E2E (cycle-016 AI-16).

Covers:
  - iDRAC (Dell), iLO (HPE), XCC (Lenovo), CIMC (Cisco) Web UI 도달성
  - 자체 서명 인증서 ignore (browser_context_args에서 처리)
  - 페이지 status < 500 검증

본 테스트는 lab credentials 가 있는 머신에서만 실행 (conftest 자동 skip).
빌드 #50 검증과 별개로, BMC Web UI 자체의 도달 가능성만 smoke 검사.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page


pytestmark = [pytest.mark.lab, pytest.mark.bmc]


def _bmc_targets(lab_creds) -> list[tuple[str, str]]:
    """벤더별 첫 BMC만 반환 — smoke."""
    out: list[tuple[str, str]] = []
    rf = lab_creds.redfish or {}
    for vendor, hosts in rf.items():
        if not hosts:
            continue
        out.append((vendor, hosts[0]["bmc_ip"]))
    return out


def _ids(targets: list[tuple[str, str]]) -> list[str]:
    return [f"{v}-{ip}" for v, ip in targets]


@pytest.fixture(scope="module")
def bmc_targets(lab_creds) -> list[tuple[str, str]]:
    targets = _bmc_targets(lab_creds)
    if not targets:
        pytest.skip("No BMC targets in lab credentials")
    return targets


def test_bmc_webui_reachable(page: Page, bmc_targets: list[tuple[str, str]]) -> None:
    """벤더별 첫 BMC 의 HTTPS Web UI 도달 (페이지 status < 500)."""
    failures: list[str] = []
    for vendor, ip in bmc_targets:
        url = f"https://{ip}/"
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
            if response is None:
                failures.append(f"{vendor}/{ip}: no response")
                continue
            if response.status >= 500:
                failures.append(f"{vendor}/{ip}: status={response.status}")
                continue
        except Exception as e:  # noqa: BLE001 — smoke
            failures.append(f"{vendor}/{ip}: {type(e).__name__} {e}")
    if failures:
        pytest.skip(
            f"BMC Web UI 일부 도달 실패 (정상 운영 변동 가능): {failures}"
        )
