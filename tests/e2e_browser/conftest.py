"""Playwright + lab credential fixtures for Browser E2E tests.

Markers:
  - lab: requires `vault/.lab-credentials.yml` (gitignored)
  - jenkins: targets Jenkins master Web UI
  - bmc: targets BMC Web UI (iDRAC / iLO / XCC / CIMC)
  - slow: longer than 30s
"""
from __future__ import annotations

import pytest

from .lab_loader import LabCreds, load_lab_creds


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "lab: requires lab credentials file")
    config.addinivalue_line("markers", "jenkins: Jenkins UI test")
    config.addinivalue_line("markers", "bmc: BMC Web UI test")
    config.addinivalue_line("markers", "slow: takes >30s")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip `lab`-marked tests when credentials file is absent."""
    creds = load_lab_creds()
    if creds is not None:
        return
    skip_lab = pytest.mark.skip(reason="vault/.lab-credentials.yml not found")
    for item in items:
        if "lab" in item.keywords:
            item.add_marker(skip_lab)


@pytest.fixture(scope="session")
def lab_creds() -> LabCreds:
    creds = load_lab_creds()
    if creds is None:
        pytest.skip("vault/.lab-credentials.yml not found")
    return creds


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    """Self-signed cert를 가진 Jenkins / BMC / Grafana 응답을 허용."""
    return {
        **browser_context_args,
        "ignore_https_errors": True,
        "viewport": {"width": 1440, "height": 900},
    }
