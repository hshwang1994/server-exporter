"""Jenkinsfile_portal 의 노드 선택 계약 (텍스트) — 2026-09-30, 2026-10-03, 2026-10-06(9차) 갱신.

노드는 Location 라벨(common/vars/locations.yml 의 agent_label)과 target_type 의 능력 라벨을 모두 가진 것만 고른다.
  - Resolve Location 이 두 값을 && 로 이어 SE_AGENT_LABEL 하나를 만들고, 서버 정보 수집(seGatherStage)이 그 값으로 Runner 를 기다린다
  - 능력 라벨: os → linux && windows (한 inventory 에 Linux · Windows 가 섞인다), esxi → esxi, redfish → redfish
  - target_type 허용값 검사가 라벨을 만들기 전에 있다
  - (9차 W01) 등록된 Runner 를 센다(nodesByLabel offline:true). 하나도 없으면 설정 오류(config_error)로 FAILURE — 접수된 대상마다
    실패 결과는 보낸다. 등록돼 있으면 지금 연결이 끊겼거나 executor 가 모두 사용 중이어도 수집 단계가 Jenkins queue 로 기다린다.
    한 번 조회한 온라인 후보가 비었다고 수집을 건너뛰던 no_agent 는 없다
  - 수집을 시작한 뒤에는 그 Runner 이름으로만 다시 시도한다(다른 Runner 로 옮기지 않는다)
  - Location 값 자체는 Jenkinsfile 에 없다 (registry 가 정본)
  - Validate 와 Resolve Location 은 agent 없이 돈다 — Resolve Location 은 readTrusted 로 registry 파일 하나만 읽는다
    (종전 built-in 전체 checkout 이 main 에서 2분 제한을 넘기던 문제)
  - node 를 잡는 곳은 seWithNode 한 곳이다 — 수집 시도(라벨 → 고정된 Runner)와 결과 처리(built-in)가 같은 대기 규칙을 쓴다
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


def _func(signature: str) -> str:
    start = TEXT.index(signature)
    return TEXT[start: TEXT.index("\n}\n", start) + 2]


RESOLVE = _stage("실행 위치 확인")


def test_label_is_location_label_and_target_capability():
    assert "def targetLabels = ['os': 'linux && windows', 'esxi': 'esxi', 'redfish': 'redfish']" in RESOLVE
    assert 'env.SE_AGENT_LABEL = "${entry.agent_label.trim()} && (${targetLabels[targetType]})"' in RESOLVE
    assert TEXT.count("SE_AGENT_LABEL =") == 1, "라벨을 정하는 곳은 Resolve Location 한 곳"


def test_target_type_is_checked_before_the_label_is_built():
    check = RESOLVE.index("if (!targetLabels.containsKey(targetType))")
    assert check < RESOLVE.index("env.SE_AGENT_LABEL ="), "허용값 밖의 target_type 이 '노드 없음' 으로 보이지 않게 먼저 거른다"
    assert "target_type 값이 잘못됐습니다" in RESOLVE


def test_registered_runners_are_counted_and_none_is_a_config_error_not_a_skip():
    check = _func("Map seCheckRunners(String label) {")
    assert "seCheckRunners(env.SE_AGENT_LABEL)" in RESOLVE
    assert "nodesByLabel(label: label, offline: true)" in check, "등록된 Runner(오프라인 포함)를 센다"
    assert "env.SE_GATHER_OUTCOME = 'config_error'" in check and "error(" in check
    assert check.index("env.SE_GATHER_OUTCOME = 'config_error'") < check.index("error("), "결과 확인이 사유를 알도록 먼저 적는다"
    assert "Location(loc)과 Runner 라벨 설정을 확인하세요" in check, "원인과 조치를 콘솔에 남긴다"
    assert "return [registered: registered, online: online]" in check
    # 등록 · 연결된 Runner 수는 실행 위치 단계가 실행 라벨과 함께 한 블록으로 남긴다(설계 설명 없이 사실만)
    assert "등록된 Runner: ${runners.registered.size()}대" in RESOLVE and "연결된 Runner: ${runners.online.size()}대" in RESOLVE
    assert "executor" not in check, "아직 일어나지 않은 대기 정책을 매번 설명하지 않는다"
    assert "no_agent" not in TEXT.replace("no_agent 는 없앴다", ""), "온라인 후보가 없다고 수집을 건너뛰지 않는다"
    assert "when { expression" not in TEXT


def test_gather_waits_for_the_label_then_pins_the_runner():
    loop = _func("def seGatherLoop(Map C, Map st, Map infra) {")
    assert "String target = st.pinned ?: env.SE_AGENT_LABEL" in loop
    assert "nodesByLabel(label: st.pinned, offline: true)" in loop and "st.outcome = 'resume_impossible'" in loop, \
        "고정된 Runner 가 등록 해제되면 다른 Runner 로 옮기지 않고 끝낸다"
    assert "st.pinned = where" in loop and "st.pinned = r.node" in loop


def test_nodes_are_taken_in_one_place():
    gather = _stage("서버 정보 수집")
    assert "agent {" not in gather and "label " not in gather, "수집 단계는 선언형 agent 없이 seGatherStage 가 Runner 를 기다린다"
    assert "seGatherStage(seConstants())" in gather
    for name in ("입력 확인", "실행 위치 확인"):
        assert "agent {" not in _stage(name), f"{name} 은 agent 없이 돈다 (workspace 불필요)"
    assert "agent { label 'built-in' }" not in TEXT, "컨트롤러 stage 는 없다 — finalizer 가 post 에서 node 를 잡는다"
    assert len(re.findall(r"\bnode\(", TEXT)) == 1 and "node(target) {" in TEXT, "스크립트형 node 는 seWithNode 한 곳"
    assert "seWithNode('built-in'," in TEXT, "결과 처리 노드도 같은 대기 규칙(seWithNode)으로 잡는다"


def test_location_values_are_not_hardcoded_in_the_pipeline():
    registry = yaml.safe_load((REPO_ROOT / "common" / "vars" / "locations.yml").read_text(encoding="utf-8"))
    for loc_id, entry in registry["locations"].items():
        assert not re.search(rf"label [\"']{re.escape(entry['agent_label'])}[\"']", TEXT), loc_id
    assert "readYaml text: seTrusted('common/vars/locations.yml')" in RESOLVE, (
        "registry 는 readTrusted 로 파일 하나만 읽는다 — 컨트롤러 전체 checkout 금지 (main 2분 초과 사고)"
    )
    assert "readYaml file:" not in RESOLVE
