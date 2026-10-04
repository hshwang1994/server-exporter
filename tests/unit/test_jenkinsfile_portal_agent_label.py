"""Jenkinsfile_portal 의 노드 선택 계약 (텍스트) — 2026-09-30, 2026-10-03 갱신.

노드는 Location 라벨(common/vars/locations.yml 의 agent_label)과 target_type 의 능력 라벨을 모두 가진 것만 고른다.
  - Resolve Location 이 두 값을 && 로 이어 SE_AGENT_LABEL 하나를 만들고, agent 를 쓰는 유일한 stage(Gather)가 그 값을 읽는다
  - 능력 라벨: os → linux && windows (한 inventory 에 Linux · Windows 가 섞인다), esxi → esxi, redfish → redfish
  - target_type 허용값 검사가 라벨을 만들기 전에 있다
  - 맞는 온라인 노드가 없으면 nodesByLabel 로 즉시 알고 **접수 후 실행 실패**로 처리한다(Gather skip, finalizer 가 Callback) —
    executor 를 기다리며 멈추지 않고, 접수된 요청을 빌드 실패로만 끝내지도 않는다 (2026-10-03 Plan §6-5)
  - Location 값 자체는 Jenkinsfile 에 없다 (registry 가 정본)
  - Validate 와 Resolve Location 은 agent 없이 돈다 — Resolve Location 은 readTrusted 로 registry 파일 하나만 읽는다
    (종전 built-in 전체 checkout 이 main 에서 2분 제한을 넘기던 문제)
  - 컨트롤러 노드는 pipeline post{always} 의 finalizer 가 `node('built-in')` 한 곳에서만 잡는다 (Callback stage 없음)
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TEXT = (REPO_ROOT / "Jenkinsfile_portal").read_text(encoding="utf-8")


def _stage(name: str) -> str:
    start = TEXT.index(f"stage('{name}')")
    nxt = re.search(r"\n        stage\('", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


RESOLVE = _stage("Resolve Location")


def test_label_is_location_label_and_target_capability():
    assert "def targetLabels = ['os': 'linux && windows', 'esxi': 'esxi', 'redfish': 'redfish']" in RESOLVE
    assert 'env.SE_AGENT_LABEL = "${entry.agent_label.trim()} && (${targetLabels[targetType]})"' in RESOLVE
    assert TEXT.count("SE_AGENT_LABEL =") == 1, "라벨을 정하는 곳은 Resolve Location 한 곳"


def test_target_type_is_checked_before_the_label_is_built():
    check = RESOLVE.index("if (!targetLabels.containsKey(targetType))")
    assert check < RESOLVE.index("env.SE_AGENT_LABEL ="), "허용값 밖의 target_type 이 '노드 없음' 으로 보이지 않게 먼저 거른다"
    assert "target_type 값 오류" in RESOLVE


def test_missing_node_is_detected_immediately_and_handled_as_accepted_failure():
    assert "def nodes = nodesByLabel(label: env.SE_AGENT_LABEL)" in RESOLVE
    assert "if (!nodes) {" in RESOLVE and "env.SE_GATHER_OUTCOME = 'no_agent'" in RESOLVE
    assert "을 모두 가진 온라인 노드가 없습니다" in RESOLVE, "원인과 조치를 콘솔에 남긴다"
    assert "(nodes: ${nodes.join(', ')})" in RESOLVE, "고른 노드를 콘솔에 남긴다"


def test_only_gather_uses_the_agent_label():
    gather = _stage("Gather")
    assert 'label "${env.SE_AGENT_LABEL}"' in gather
    assert "label 'built-in'" not in gather, "Gather 는 컨트롤러에서 돌지 않는다"
    for name in ("Validate", "Resolve Location"):
        assert "agent {" not in _stage(name), f"{name} 은 agent 없이 돈다 (workspace 불필요)"
    assert "agent { label 'built-in' }" not in TEXT, "컨트롤러 stage 는 없다 — finalizer 가 post 에서 node 를 잡는다"
    assert len(re.findall(r"\bnode\(", TEXT)) == 1 and "node('built-in')" in TEXT, "스크립트형 node 는 finalizer 의 built-in 한 곳"


def test_location_values_are_not_hardcoded_in_the_pipeline():
    registry = yaml.safe_load((REPO_ROOT / "common" / "vars" / "locations.yml").read_text(encoding="utf-8"))
    for loc_id, entry in registry["locations"].items():
        assert not re.search(rf"label [\"']{re.escape(entry['agent_label'])}[\"']", TEXT), loc_id
    assert "readYaml text: seTrusted('common/vars/locations.yml')" in RESOLVE, (
        "registry 는 readTrusted 로 파일 하나만 읽는다 — 컨트롤러 전체 checkout 금지 (main 2분 초과 사고)"
    )
    assert "readYaml file:" not in RESOLVE
