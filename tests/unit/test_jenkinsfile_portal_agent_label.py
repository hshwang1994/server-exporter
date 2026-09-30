"""Jenkinsfile_portal 의 노드 선택 계약 (텍스트) — 2026-09-30.

노드는 Location 라벨(common/vars/locations.yml 의 agent_label)과 target_type 의 능력 라벨을 모두 가진 것만 고른다.
  - Resolve Location 이 두 값을 && 로 이어 SE_AGENT_LABEL 하나를 만들고, agent 를 쓰는 세 stage 가 그 값을 그대로 읽는다
  - 능력 라벨: os → linux && windows (한 inventory 에 Linux · Windows 가 섞인다), esxi → esxi, redfish → redfish
  - target_type 허용값 검사가 라벨을 만들기 전에 있다
  - 맞는 온라인 노드가 없으면 nodesByLabel 로 즉시 error (executor 를 기다리며 멈추지 않는다)
  - Location 값 자체는 Jenkinsfile 에 없다 (registry 가 정본)
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


def test_missing_node_fails_fast_instead_of_waiting_for_an_executor():
    assert "def nodes = nodesByLabel(label: env.SE_AGENT_LABEL)" in RESOLVE
    assert re.search(r"if \(!nodes\) \{\s*error \"\[Resolve Location\] 라벨 '\$\{env\.SE_AGENT_LABEL\}' 을 모두 가진 온라인 노드가 없습니다", RESOLVE)
    assert "(nodes: ${nodes.join(', ')})" in RESOLVE, "고른 노드를 콘솔에 남긴다"


def test_every_agent_stage_reads_the_same_label():
    for name in ("Validate", "Gather", "Validate Schema"):
        stage = _stage(name)
        assert 'label "${env.SE_AGENT_LABEL}"' in stage, name
        assert "label 'built-in'" not in stage, f"{name} 은 컨트롤러에서 돌지 않는다"
    for name in ("Resolve Location", "Callback"):
        assert "label 'built-in'" in _stage(name), f"{name} 은 컨트롤러 stage"
    assert re.search(r"\bnode\(", TEXT) is None, "스크립트형 node(...) 로 라벨을 따로 정하는 곳이 없다"


def test_location_values_are_not_hardcoded_in_the_pipeline():
    registry = yaml.safe_load((REPO_ROOT / "common" / "vars" / "locations.yml").read_text(encoding="utf-8"))
    for loc_id, entry in registry["locations"].items():
        assert not re.search(rf"label [\"']{re.escape(entry['agent_label'])}[\"']", TEXT), loc_id
    assert "readYaml file: 'common/vars/locations.yml'" in RESOLVE
