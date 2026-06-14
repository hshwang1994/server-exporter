"""M-A7 후속 회귀 — adapter `recovery_accounts.vault_label` ↔ vendor 별 허용 label set 정합.

배경 (cycle 2026-05-11 M-A7, commit `a82afc4b`):
  M-A1~A6 (cycle 2026-05-11) 에서 9 vendor recovery 자격 매트릭스 정착 후
  M-A7 에서 29 adapter (`redfish_generic` 제외) 의 `recovery_accounts.vault_label`
  을 vault 실 label 와 1:1 정합시킴. 본 회귀 테스트는 향후 adapter 추가/수정 시
  drift 차단.

검증 항목 (정본 = `docs/21_vault-operations.md` §6.5):
  1. 각 adapter (29) 의 `recovery_accounts` 가 비어있지 않음
  2. 각 `vault_label` 이 vendor 별 허용 set 에 포함
  3. 각 entry 에 `role: recovery` 명시
  4. vendor 는 파일명 prefix 또는 `credentials.profile` 기반

원칙 준수:
  - rule 13 R5 (envelope 정본) — 본 회귀는 정적 검증, envelope shape 변경 0
  - rule 22 (Fragment) — 본 회귀는 adapter declare 만 검증, gather 코드 영향 0
  - rule 92 R2 (Additive only) — 신규 회귀 1 파일 추가, 기존 회귀 변경 0
  - rule 96 R1-B — 호출자 시스템 파싱 변경 0
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ADAPTERS_DIR = REPO / "adapters" / "redfish"

# 정본 = docs/21_vault-operations.md §6.5 (cycle 2026-05-11 M-A7)
VENDOR_ALLOWED_LABELS: dict[str, frozenset[str]] = {
    "dell": frozenset({
        "dell_fallback_1",
        "dell_fallback_2",
        "dell_current",
        "lab_dell_root",
    }),
    "hpe": frozenset({
        "hpe_fallback",
        "hpe_current",
        "hpe_factory",
    }),
    "lenovo": frozenset({
        "lenovo_fallback",
        "lenovo_current",
        "lenovo_factory",
    }),
    "supermicro": frozenset({
        "supermicro_factory",
    }),
    "cisco": frozenset({
        "cisco_current",
        "cisco_factory",
    }),
    "huawei": frozenset({
        "huawei_factory",
    }),
    "inspur": frozenset({
        "inspur_factory",
    }),
    "fujitsu": frozenset({
        "fujitsu_factory",
    }),
    "quanta": frozenset({
        "quanta_factory",
    }),
}

# 파일명 prefix → vendor canonical 매핑 (rule 12 R1 Allowed — set membership 패턴)
PREFIX_TO_VENDOR: dict[str, str] = {
    "dell_": "dell",
    "hpe_": "hpe",
    "lenovo_": "lenovo",
    "supermicro_": "supermicro",
    "cisco_": "cisco",
    "huawei_": "huawei",
    "inspur_": "inspur",
    "fujitsu_": "fujitsu",
    "quanta_": "quanta",
}

# generic fallback — recovery_accounts 가 빈 list. 본 회귀 대상 제외.
EXCLUDED_ADAPTERS: frozenset[str] = frozenset({"redfish_generic.yml"})


def _load_adapter(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _detect_vendor(path: Path, doc: dict) -> str:
    """파일명 prefix 우선 → credentials.profile fallback."""
    name = path.name
    for prefix, vendor in PREFIX_TO_VENDOR.items():
        if name.startswith(prefix):
            return vendor
    profile = (doc.get("credentials") or {}).get("profile") or ""
    return profile.strip().lower()


def _all_redfish_adapters() -> list[Path]:
    return sorted(p for p in ADAPTERS_DIR.glob("*.yml") if p.name not in EXCLUDED_ADAPTERS)


# ── 메타 검증 ────────────────────────────────────────────────────────────────


def test_adapter_directory_has_expected_count() -> None:
    """30 adapter (generic 제외) 가 존재. drift 감지 — adapter 추가/삭제 시 회귀 알림.

    cycle 2026-05-11 hpe-csus-add: 29 → 30 (hpe_csus_3200 신설).
    """
    adapters = _all_redfish_adapters()
    assert len(adapters) == 30, (
        f"adapters/redfish/ 비-generic adapter 개수 drift: {len(adapters)} (기대 30). "
        f"adapter 추가/삭제 시 본 테스트 + docs/21 §6.5 + CLAUDE.md 카운트 동반 갱신."
    )


def test_vendor_allowed_labels_matrix_covers_9_vendors() -> None:
    """vendor 별 허용 label set 정본이 9 vendor 모두 포함."""
    assert set(VENDOR_ALLOWED_LABELS.keys()) == {
        "dell", "hpe", "lenovo", "supermicro", "cisco",
        "huawei", "inspur", "fujitsu", "quanta",
    }


# ── 본 검증: 29 adapter × parametrize ────────────────────────────────────────


@pytest.mark.parametrize("adapter_path", _all_redfish_adapters(), ids=lambda p: p.name)
def test_adapter_recovery_accounts_non_empty(adapter_path: Path) -> None:
    """각 adapter 의 `recovery_accounts` 가 비어있지 않음 (generic 제외)."""
    doc = _load_adapter(adapter_path)
    creds = doc.get("credentials") or {}
    recovery = creds.get("recovery_accounts")
    assert isinstance(recovery, list), (
        f"{adapter_path.name}: credentials.recovery_accounts 가 list 아님 (got {type(recovery).__name__})"
    )
    assert len(recovery) >= 1, (
        f"{adapter_path.name}: recovery_accounts 가 비어있음. M-A7 정합 (cycle 2026-05-11) 위반."
    )


@pytest.mark.parametrize("adapter_path", _all_redfish_adapters(), ids=lambda p: p.name)
def test_adapter_recovery_labels_in_vendor_allowed_set(adapter_path: Path) -> None:
    """각 `vault_label` 이 vendor 별 허용 set (docs/21 §6.5) 에 포함."""
    doc = _load_adapter(adapter_path)
    vendor = _detect_vendor(adapter_path, doc)
    assert vendor in VENDOR_ALLOWED_LABELS, (
        f"{adapter_path.name}: vendor 감지 실패 (got '{vendor}'). "
        f"파일명 prefix 또는 credentials.profile 확인 필요."
    )
    allowed = VENDOR_ALLOWED_LABELS[vendor]
    recovery = (doc.get("credentials") or {}).get("recovery_accounts") or []
    for entry in recovery:
        label = entry.get("vault_label")
        assert label in allowed, (
            f"{adapter_path.name}: vault_label '{label}' 이 {vendor} 허용 set {sorted(allowed)} 외. "
            f"vault/redfish/{vendor}.yml accounts label 와 정합 필요 (docs/21 §6.5)."
        )


@pytest.mark.parametrize("adapter_path", _all_redfish_adapters(), ids=lambda p: p.name)
def test_adapter_recovery_role_is_recovery(adapter_path: Path) -> None:
    """각 entry 에 `role: recovery` 명시."""
    doc = _load_adapter(adapter_path)
    recovery = (doc.get("credentials") or {}).get("recovery_accounts") or []
    for entry in recovery:
        assert entry.get("role") == "recovery", (
            f"{adapter_path.name}: entry {entry} 의 role 이 'recovery' 아님. "
            f"account_service.yml chain 진입 조건 위반."
        )


# ── generic fallback 회귀 ────────────────────────────────────────────────────


def test_redfish_generic_recovery_accounts_empty() -> None:
    """generic fallback (`redfish_generic.yml`) 은 vendor 미상이므로 빈 list 유지."""
    path = ADAPTERS_DIR / "redfish_generic.yml"
    doc = _load_adapter(path)
    creds = doc.get("credentials") or {}
    recovery = creds.get("recovery_accounts")
    assert recovery == [], (
        f"redfish_generic.yml: recovery_accounts 가 [] 아님 (got {recovery!r}). "
        f"generic fallback 은 vendor 미상이므로 비워둠 (docs/21 §6.5)."
    )
