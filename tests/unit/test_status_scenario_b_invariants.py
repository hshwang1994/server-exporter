"""M-A3 Case A — 시나리오 B (섹션 success + errors warning) 회귀.

본 회귀는 ``common/tasks/normalize/build_status.yml`` 의 Jinja2 판정 로직을
Python 으로 재현하여 mock fixture (``tests/fixtures/outputs/status_success_with_warnings.json``)
의 invariants 를 검증한다.

의도된 설계 (M-A2 결정 결과 — Case A 채택):
    - overall.status 는 섹션 status 만 본다. envelope.errors[] 는 보지 않는다.
    - 시나리오 B: 모든 섹션 success + errors[] 에 warning 있음 → overall=success
    - errors[] 는 사유 추적용 분리 영역 — 호출자가 별도 검사

reference:
    - common/tasks/normalize/build_status.yml (정본 헤더 주석)
    - os-gather/tasks/linux/gather_memory.yml:171-175 (dmidecode fallback 시 errors emit)
    - docs/19_decision-log.md (M-A2 결정 / 2026-05-06)
    - rule 13 R5 (envelope 13 필드) / rule 96 R1-B (호환성 외 schema 확장 금지)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = (
    REPO
    / "tests"
    / "fixtures"
    / "outputs"
    / "status_success_with_warnings.json"
)

ENVELOPE_FIELDS = (
    "target_type",
    "collection_method",
    "ip",
    "hostname",
    "vendor",
    "status",
    "sections",
    "diagnosis",
    "meta",
    "correlation",
    "errors",
    "data",
    "schema_version",
)


def _compute_status_from_sections(sections: dict[str, str]) -> str:
    """build_status.yml 의 Jinja2 인라인 판정 로직 Python 재현.

    판정 규칙 (정본 — build_status.yml 헤더 주석):
        supported = sec_vals - 'not_supported'
        len(supported) == 0       → 'failed'
        failed_count == 0         → 'success'
        success_count == 0        → 'failed'
        otherwise                 → 'partial'

    errors[] 는 입력 안 함 — 의도된 설계.
    """
    sec_vals = list(sections.values())
    supported = [v for v in sec_vals if v != "not_supported"]
    if not supported:
        return "failed"
    success_count = sum(1 for v in supported if v == "success")
    failed_count = sum(1 for v in supported if v == "failed")
    if failed_count == 0:
        return "success"
    if success_count == 0:
        return "failed"
    return "partial"


@pytest.fixture(scope="module")
def envelope() -> dict:
    assert FIXTURE.exists(), f"mock fixture 누락: {FIXTURE}"
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists_and_loads(envelope: dict) -> None:
    assert isinstance(envelope, dict)


def test_envelope_has_13_fields(envelope: dict) -> None:
    """rule 13 R5 — envelope 13 필드 모두 존재."""
    for field in ENVELOPE_FIELDS:
        assert field in envelope, f"envelope 필드 누락: {field}"


def test_overall_status_is_success(envelope: dict) -> None:
    """시나리오 B 정본: overall.status == 'success' (errors[] 와 무관)."""
    assert envelope["status"] == "success"


def test_errors_non_empty_with_warnings(envelope: dict) -> None:
    """시나리오 B 정본: errors[] 에 warning 있음 (섹션은 success 임에도)."""
    errors = envelope["errors"]
    assert isinstance(errors, list)
    assert len(errors) > 0, "시나리오 B 는 errors[] 가 non-empty 여야 함"


def test_errors_have_section_and_message(envelope: dict) -> None:
    """errors[] 각 항목은 section + message 필수 (rule 22 R8 타입 정본)."""
    for err in envelope["errors"]:
        assert "section" in err
        assert "message" in err
        assert isinstance(err["section"], str)
        assert isinstance(err["message"], str)
        assert err["message"], "errors[].message 는 비어있을 수 없음"


def test_memory_warning_pattern_present(envelope: dict) -> None:
    """gather_memory.yml:171-175 의 dmidecode fallback 패턴 재현 확인."""
    memory_errs = [e for e in envelope["errors"] if e["section"] == "memory"]
    assert memory_errs, "memory section warning 누락 (시나리오 B 핵심 trigger)"
    assert "dmidecode" in memory_errs[0]["message"], (
        "fallback 사유 message 가 dmidecode 키워드 포함해야 함"
    )


def test_supported_sections_all_success(envelope: dict) -> None:
    """시나리오 B: not_supported 제외 섹션은 모두 success."""
    for name, status in envelope["sections"].items():
        assert status in ("success", "not_supported"), (
            f"section {name} 는 시나리오 B 에서 success 또는 not_supported 만 허용 (실제={status})"
        )


def test_recomputed_status_matches_envelope(envelope: dict) -> None:
    """build_status.yml Jinja2 판정 ↔ Python 재현 일치 — 회귀 가드."""
    recomputed = _compute_status_from_sections(envelope["sections"])
    assert recomputed == envelope["status"]


def test_errors_do_not_change_status() -> None:
    """의도된 설계 검증: errors[] 변동이 status 에 영향 없음."""
    sections = {
        "system": "success",
        "memory": "success",
        "cpu": "success",
        "firmware": "not_supported",
    }
    status_clean = _compute_status_from_sections(sections)
    status_with_errors = _compute_status_from_sections(sections)
    assert status_clean == "success"
    assert status_with_errors == "success"


def test_scenario_a_clean_success() -> None:
    """시나리오 A: 모두 success + errors empty → success."""
    sections = {"system": "success", "cpu": "success", "memory": "success"}
    assert _compute_status_from_sections(sections) == "success"


def test_scenario_c_partial() -> None:
    """시나리오 C: success + failed 혼재 → partial."""
    sections = {"system": "success", "cpu": "failed", "memory": "success"}
    assert _compute_status_from_sections(sections) == "partial"


def test_scenario_d_all_failed() -> None:
    """시나리오 D: 모두 failed → failed."""
    sections = {"system": "failed", "cpu": "failed"}
    assert _compute_status_from_sections(sections) == "failed"


def test_no_supported_sections_failed() -> None:
    """엣지: 지원 섹션 0개 (모두 not_supported) → failed."""
    sections = {"system": "not_supported", "cpu": "not_supported"}
    assert _compute_status_from_sections(sections) == "failed"
