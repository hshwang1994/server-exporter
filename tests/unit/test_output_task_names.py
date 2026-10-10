"""콜백이 완전일치로 잡는 태스크 이름 — `OUTPUT` · `CHECKPOINT` · `ADDON_START` · `ADDON_DONE` (rule 20 R3).

2026-10-10 변이 시험 M1: os-gather/site.yml 의 OUTPUT 태스크 하나를 "OUTPUT: 결과 출력" 으로 바꿔도 오프라인 gate(ci_gate) 가 전부 통과했다.
이름이 어긋나면 json_only 가 그 play 의 결과를 내보내지 않아 호출자가 그 대상의 결과를 받지 못한다(Layer A 가 OUTPUT_BUILD_FAILED 로 채운다).
여기서는 세 site.yml 과 Add-on 태스크 파일의 이름을 콜백 기본값과 같은 리터럴로 고정한다 — 이름은 다른 구성요소(콜백)가 소비하는 문자열이다."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SITES = {"os": REPO / "os-gather/site.yml", "esxi": REPO / "esxi-gather/site.yml", "redfish": REPO / "redfish-gather/site.yml"}
CALLBACK = (REPO / "callback_plugins/json_only.py").read_text(encoding="utf-8")
# json_only 기본값 (환경변수로 바꿀 수 있지만 저장소 어디서도 바꾸지 않는다 — env_guard.sh 가 오히려 지운다)
OUTPUT_TASK = re.search(r"os\.getenv\('ANSIBLE_JSON_OUTPUT_TASK', '([^']+)'\)", CALLBACK).group(1)
CHECKPOINT_TASK = re.search(r"os\.getenv\('ANSIBLE_JSON_CHECKPOINT_TASK', '([^']+)'\)", CALLBACK).group(1)
# 채널별 OUTPUT 태스크 수 — os 는 감지실패 play + linux always + windows always, esxi · redfish 는 always 하나
EXPECTED_OUTPUT_COUNT = {"os": 3, "esxi": 1, "redfish": 1}
EXPECTED_CHECKPOINT_COUNT = {"os": 2, "esxi": 1, "redfish": 1}


def _task_names(node, out: list):
    """play / block / always / rescue / tasks / pre_tasks / post_tasks 를 재귀로 훑어 task 이름을 모은다."""
    if isinstance(node, list):
        for item in node:
            _task_names(item, out)
    elif isinstance(node, dict):
        if "name" in node and any(k in node for k in ("debug", "ansible.builtin.debug", "set_fact", "ansible.builtin.set_fact",
                                                       "include_tasks", "ansible.builtin.include_tasks", "import_tasks", "block",
                                                       "shell", "command", "raw", "fail", "meta", "ansible.builtin.meta")):
            out.append(str(node["name"]))
        for key in ("tasks", "pre_tasks", "post_tasks", "block", "always", "rescue"):
            if key in node:
                _task_names(node[key], out)


def names_of(path: Path) -> list:
    out: list = []
    _task_names(yaml.safe_load(path.read_text(encoding="utf-8")), out)
    return out


def test_callback_defaults_are_the_literals_the_playbooks_use():
    assert (OUTPUT_TASK, CHECKPOINT_TASK) == ("OUTPUT", "CHECKPOINT")
    assert "ANSIBLE_JSON_OUTPUT_TASK" in (REPO / "scripts/env_guard.sh").read_text(encoding="utf-8"), "env_guard 가 재정의를 지워 기본값이 보장된다"


@pytest.mark.parametrize("channel", sorted(SITES))
def test_output_and_checkpoint_tasks_are_named_exactly(channel):
    names = names_of(SITES[channel])
    assert names.count(OUTPUT_TASK) == EXPECTED_OUTPUT_COUNT[channel], (channel, [n for n in names if "OUTPUT" in n.upper()])
    assert names.count(CHECKPOINT_TASK) == EXPECTED_CHECKPOINT_COUNT[channel], (channel, [n for n in names if "CHECKPOINT" in n.upper()])
    # 비슷하게 시작하는 변형("OUTPUT: …", "Output", "CHECKPOINT ") 은 콜백이 잡지 못한다 — 하나도 없어야 한다
    for n in names:
        head = n.strip().split(" ")[0].rstrip(":").upper()
        if head in ("OUTPUT", "CHECKPOINT"):
            assert n in (OUTPUT_TASK, CHECKPOINT_TASK), (channel, n)


def test_addon_marker_tasks_are_named_exactly():
    names = names_of(REPO / "common/tasks/addon/run_addon.yml")
    assert names.count("ADDON_START") == 1 and names.count("ADDON_DONE") == 1, names
    assert "'ADDON_START'" in CALLBACK and "'ADDON_DONE'" in CALLBACK
