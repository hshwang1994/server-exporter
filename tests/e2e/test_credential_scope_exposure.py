"""`diagnosis.details.credential_scope` 의 3채널 전면 노출 회귀 (2026-08-12).

왜 필요한가:
    Credential 이 Location 축을 갖게 되면서 "이 결과는 **어떤** 자격증명 세트로 만들어졌나"
    가 진단의 핵심 정보가 됐다. 실패 경로에만 넣으면 "성공한 대상과 실패한 대상이 같은
    세트를 썼는가" 를 비교할 수 없어 원인 범위를 좁히지 못한다.

    실제로 최초 구현에서 **OS 성공 경로 2곳이 누락**됐다 (Redfish / ESXi 는 반영됨).
    구현 시점의 눈으로는 잘 안 보이는 종류의 누락이라 테스트로 고정한다.

검증 대상 8곳 = 3채널 × (성공 / 실패) + OS 는 linux / windows 두 Play:
    os      성공 linux / 성공 windows / rescue linux / rescue windows
    esxi    성공 / rescue
    redfish 성공 / rescue

**제외**: precheck 단계의 `_diagnosis` (자격 해석 이전이라 scope 가 아직 없다) 와
`always` 블록의 OUTPUT_BUILD_FAILED fallback envelope (변수 자체가 없을 수 있다).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

# (파일, 태스크 이름 조각) — production 파일에서 그대로 찾는다
DIAGNOSIS_SITES: list[tuple[str, str]] = [
    ("os-gather/site.yml", "linux | build diagnosis (success path)"),
    ("os-gather/site.yml", "windows | build diagnosis (success path)"),
    ("os-gather/site.yml", "linux | rescue | Portal 표시용 diagnosis 보장"),
    ("os-gather/site.yml", "windows | rescue | Portal 표시용 diagnosis 보장"),
    ("esxi-gather/site.yml", "esxi | enrich diagnosis with adapter"),
    ("esxi-gather/site.yml", "esxi | rescue | Portal 표시용 failure_reason 보장"),
    # redfish 성공 경로의 _diagnosis 는 "set output meta" 태스크 안에서 combine 된다
    ("redfish-gather/site.yml", "redfish | set output meta"),
    ("redfish-gather/site.yml", "redfish | rescue | Portal 표시용 failure_reason 보장"),
]


def _iter_tasks(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _iter_tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("block", "rescue", "always", "tasks"):
            if key in node:
                yield from _iter_tasks(node[key])


def _tasks_of(relpath: str) -> list[dict[str, Any]]:
    doc = list(yaml.safe_load_all((REPO / relpath).read_text(encoding="utf-8")))[0]
    return list(_iter_tasks(doc))


def _diagnosis_payload(relpath: str, name_part: str) -> str:
    """해당 태스크의 `_diagnosis` set_fact 값을 문자열로 돌려준다.

    성공 경로는 리터럴 dict, 실패 경로는 Jinja 문자열이라 형태가 다르다.
    둘 다 문자열화해서 키 존재만 본다.
    """
    for task in _tasks_of(relpath):
        if name_part in (task.get("name") or ""):
            facts = task.get("ansible.builtin.set_fact") or {}
            if "_diagnosis" in facts:
                return str(facts["_diagnosis"])
    raise AssertionError(f"{relpath} 에서 {name_part!r} 의 _diagnosis 를 찾지 못했다")


@pytest.mark.parametrize("relpath,name_part", DIAGNOSIS_SITES,
                         ids=[f"{p.split('/')[0]}:{n[:38]}" for p, n in DIAGNOSIS_SITES])
def test_credential_scope_present(relpath, name_part):
    payload = _diagnosis_payload(relpath, name_part)
    assert "credential_scope" in payload, (
        f"{relpath} / {name_part!r} 의 diagnosis.details 에 credential_scope 누락 — "
        "어떤 자격증명 세트를 썼는지 결과만 보고 알 수 없게 된다"
    )


@pytest.mark.parametrize("relpath,name_part", DIAGNOSIS_SITES,
                         ids=[f"{p.split('/')[0]}:{n[:38]}" for p, n in DIAGNOSIS_SITES])
def test_credential_scope_is_null_not_empty_string(relpath, name_part):
    """미결정 시 `''` 가 아니라 null 이어야 한다.

    빈 문자열은 소비자 입장에서 "scope 가 있는데 이름이 비었다" 로 읽힌다.
    `(_cred_scope | default('')) or none` 관용구로 통일한다.
    """
    payload = _diagnosis_payload(relpath, name_part)
    idx = payload.find("credential_scope")
    window = payload[idx: idx + 120]
    assert "or none" in window, (
        f"{relpath} / {name_part!r}: credential_scope 가 null 로 떨어지지 않는다 — {window!r}"
    )


def test_credential_scope_never_carries_secret_material():
    """scope 표현식이 vault 내용을 참조하지 않는지 (정적).

    `_cred_scope` 는 resolver 가 만든 경로 문자열이다. 실수로 `_cred_accounts` 나
    `_cred_vault_data` 를 섞으면 그 순간 Secret 이 envelope 으로 나간다.
    """
    for relpath, name_part in DIAGNOSIS_SITES:
        payload = _diagnosis_payload(relpath, name_part)
        idx = payload.find("credential_scope")
        window = payload[idx: idx + 120]
        for forbidden in ("_cred_accounts", "_cred_vault_data", "password", "username"):
            assert forbidden not in window, (
                f"{relpath} / {name_part!r}: credential_scope 식에 {forbidden!r} 가 섞였다"
            )


def test_all_three_channels_are_covered():
    """채널 하나가 통째로 빠지는 것을 막는다 (목록 자체의 회귀 방어)."""
    channels = {p.split("/")[0] for p, _ in DIAGNOSIS_SITES}
    assert channels == {"os-gather", "esxi-gather", "redfish-gather"}


def test_success_and_failure_paths_both_covered():
    """성공 경로만, 또는 실패 경로만 덮는 상태를 막는다."""
    rescue = [n for _, n in DIAGNOSIS_SITES if "rescue" in n]
    success = [n for _, n in DIAGNOSIS_SITES if "rescue" not in n]
    assert len(rescue) >= 3, "실패 경로가 3채널 미만"
    assert len(success) >= 3, "성공 경로가 3채널 미만"


def test_field_dictionary_registers_the_field():
    """envelope 에 나가는 필드는 field_dictionary 에 등록돼 있어야 한다 (rule 13)."""
    fd = yaml.safe_load(
        (REPO / "schema" / "field_dictionary.yml").read_text(encoding="utf-8")
    )
    fields = fd.get("fields", fd)
    entry = fields.get("diagnosis.details.credential_scope")
    assert entry is not None, "diagnosis.details.credential_scope 미등록"
    assert entry["type"] == "string|null"
    assert set(entry["channel"]) == {"redfish", "os", "esxi"}
