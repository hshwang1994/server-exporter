"""Lab credentials loader (gitignored YAML).

server-exporter cycle-014에서 도입.
사용자가 `vault/.lab-credentials.yml` (gitignored)에 lab 자격증명 보관.
본 모듈은 그것을 dict로 로드. 미존재 시 친절한 에러 메시지.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAB_CREDS_PATH = PROJECT_ROOT / "vault" / ".lab-credentials.yml"


@dataclass(frozen=True)
class LabCreds:
    raw: dict[str, Any]

    @property
    def jenkins_masters(self) -> list[dict[str, Any]]:
        return self.raw.get("jenkins_masters", [])

    @property
    def jenkins_agents(self) -> list[dict[str, Any]]:
        return self.raw.get("jenkins_agents", [])

    @property
    def os_linux(self) -> list[dict[str, Any]]:
        return self.raw.get("os_targets_linux", [])

    @property
    def os_windows(self) -> list[dict[str, Any]]:
        return self.raw.get("os_targets_windows", [])

    @property
    def redfish(self) -> dict[str, list[dict[str, Any]]]:
        return self.raw.get("redfish_targets", {})

    @property
    def esxi(self) -> list[dict[str, Any]]:
        return self.raw.get("esxi_targets", [])


def load_lab_creds() -> LabCreds | None:
    """Load lab credentials. Returns None if file missing (CI / no lab access)."""
    if not LAB_CREDS_PATH.exists():
        return None
    with open(LAB_CREDS_PATH, encoding="utf-8") as f:
        return LabCreds(raw=yaml.safe_load(f) or {})


def require_lab_creds() -> LabCreds:
    """Load lab credentials or raise with actionable message."""
    creds = load_lab_creds()
    if creds is None:
        raise RuntimeError(
            f"Lab credentials not found: {LAB_CREDS_PATH}\n"
            "Browser E2E and live probe tests require local lab access.\n"
            "See docs/ai/catalogs/LAB_INVENTORY.md for setup."
        )
    return creds
