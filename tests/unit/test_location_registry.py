"""Location registry (`common/vars/locations.yml`) 스키마 회귀 (2026-08-12).

이 파일이 지키는 것:
    - Location ID 가 vault 경로 조각으로 **그대로** 쓰이므로 경로 안전해야 한다
    - `agent_label` 이 필수다 (Jenkins 'Resolve Location' stage 가 읽는다)
    - Location 문자열이 registry 밖(코드)에 하드코딩되지 않는다

`ic/chj/yi` 같은 **값 자체를 단언하지 않는다** — Location 추가가 코드 수정 0줄이어야
하는데, 테스트가 값을 고정하면 그 약속이 깨진다. 검증하는 것은 구조뿐이다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "common" / "vars" / "locations.yml"

PATH_SAFE = re.compile(r"\A[a-z0-9_-]+\Z")


@pytest.fixture(scope="module")
def registry() -> dict:
    assert REGISTRY.is_file(), f"Location registry 부재: {REGISTRY}"
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    assert isinstance(data, dict), "locations.yml 최상위가 매핑이 아니다"
    return data


def test_top_level_key(registry):
    assert "locations" in registry, "'locations' 최상위 키가 없다"
    assert isinstance(registry["locations"], dict)
    assert registry["locations"], "Location 이 하나도 없다 — 전 대상이 실패한다"


def test_location_ids_are_path_safe(registry):
    """ID 가 곧 `vault/<id>/...` 경로 조각이다. `..` / `/` / 공백이 들어오면 안 된다."""
    for loc_id in registry["locations"]:
        assert isinstance(loc_id, str), f"비-문자열 Location ID: {loc_id!r}"
        assert PATH_SAFE.match(loc_id), (
            f"Location ID {loc_id!r} 가 경로 조각으로 안전하지 않다 ([a-z0-9_-]+ 만 허용)"
        )


def test_agent_label_present(registry):
    for loc_id, entry in registry["locations"].items():
        assert isinstance(entry, dict), f"{loc_id}: 항목이 매핑이 아니다"
        label = entry.get("agent_label")
        assert label, f"{loc_id}: agent_label 누락 — Jenkins 가 노드를 고를 수 없다"
        assert isinstance(label, str) and label.strip() == label


def test_no_duplicate_agent_labels(registry):
    """두 Location 이 같은 agent 를 가리키면 Credential 격리가 물리적으로 흐려진다."""
    labels = [e["agent_label"] for e in registry["locations"].values()]
    dupes = {x for x in labels if labels.count(x) > 1}
    assert not dupes, f"agent_label 중복: {sorted(dupes)}"


def _strip_comments(text: str) -> str:
    """줄 주석을 제거한다. 주석 속 예시는 라우팅에 영향을 주지 않으므로 검사 대상이 아니다."""
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # 인라인 주석 — 따옴표 안의 '#' 는 흔치 않으므로 보수적으로 첫 ' #' 만 자른다
        idx = line.find(" #")
        out.append(line[:idx] if idx >= 0 else line)
    return "\n".join(out)


def test_registry_is_the_only_place_locations_are_named(registry):
    """Location 문자열이 실행 코드에 하드코딩되지 않았는지 (코드 수정 없는 확장 보장).

    검사 대상은 실제 선택/라우팅 코드뿐이다. 주석 / 문서 / 테스트 / Jenkins 파라미터
    description 은 제외한다 — 설명 목적의 등장은 동작을 바꾸지 않는다.
    """
    targets = [
        REPO / "module_utils" / "credential_common.py",
        REPO / "lookup_plugins" / "credential_resolver.py",
        REPO / "common" / "tasks" / "credential" / "resolve_and_load.yml",
        REPO / "os-gather" / "site.yml",
        REPO / "esxi-gather" / "site.yml",
        REPO / "redfish-gather" / "site.yml",
    ]
    loc_ids = list(registry["locations"].keys())
    for path in targets:
        if not path.is_file():
            continue
        text = _strip_comments(path.read_text(encoding="utf-8"))
        for loc_id in loc_ids:
            # 단어 경계로 찾는다 — 'ic' 가 'basic' 안에서 걸리면 안 된다.
            hits = re.findall(rf"(?<![a-z0-9_]){re.escape(loc_id)}(?![a-z0-9_])", text)
            assert not hits, (
                f"{path.relative_to(REPO)} 에 Location ID {loc_id!r} 하드코딩 "
                f"({len(hits)}건) — registry 밖에서 Location 을 알면 안 된다"
            )


def test_no_secret_material_in_registry():
    """registry 는 평문이다. 자격증명이 섞여 들어오면 안 된다."""
    text = REGISTRY.read_text(encoding="utf-8").lower()
    for word in ("password", "passwd", "secret", "token", "api_key"):
        assert word not in text, f"locations.yml 에 {word!r} 등장 — Secret 은 vault 에만"


def test_registry_is_plaintext_not_vault():
    """Jenkins controller 가 vault 키 없이 읽어야 하므로 암호화하면 안 된다."""
    head = REGISTRY.read_text(encoding="utf-8")[:64]
    assert not head.startswith("$ANSIBLE_VAULT"), (
        "locations.yml 이 암호화되면 Jenkins 'Resolve Location' stage 가 읽을 수 없다"
    )
