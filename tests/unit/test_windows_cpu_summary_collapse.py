"""Windows CPU summary PS5.1 single-element-array collapse guard.

PS5.1 `ConvertTo-Json` collapses a single-element `processors` array into a dict
(object), not a list. gather_cpu.yml 의 summary 루프가 dict 를 [dict] 로 wrap 하지
않으면 for 가 dict 의 KEY(문자열)를 순회 → p.name/cores/manufacturer 가 Undefined →
summary 가 model='unknown'/cores=0 으로 corrupt (단일 소켓 = 흔한 케이스).

본 테스트는 Python mirror 가 아니라 **gather_cpu.yml 의 실제 Jinja2 표현식**을 추출해
collapse(dict) 경로를 직접 렌더링한다 — 그래야 `is mapping` 가드가 실제로 검증된다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CPU_YML = REPO / "os-gather" / "tasks" / "windows" / "gather_cpu.yml"

_SUMMARY_TASK = "windows | cpu | compute summary groups"


def _summary_template() -> str:
    tasks = yaml.safe_load(CPU_YML.read_text(encoding="utf-8"))
    for t in tasks:
        if isinstance(t, dict) and t.get("name") == _SUMMARY_TASK:
            return t["ansible.builtin.set_fact"]["_w_cpu_summary"]
    raise AssertionError(f"task {_SUMMARY_TASK!r} not found in {CPU_YML}")


def _render(cpu_data: dict):
    out = NativeEnvironment().from_string(_summary_template()).render(_w_cpu_data=cpu_data)
    if isinstance(out, str):
        out = ast.literal_eval(out.strip())
    return out


_SINGLE = {
    "model": "Intel Xeon Gold 6338",
    "name": "Intel Xeon Gold 6338",
    "manufacturer": "GenuineIntel",
    "cores": 32,
}


def test_single_socket_dict_collapse_not_corrupt():
    """PS5.1 단일 소켓: processors 가 dict(collapse) → [dict] wrap 후 정상 summary."""
    out = _render({"processors": dict(_SINGLE)})  # dict (collapsed), not list
    groups = out["groups"]
    assert len(groups) == 1
    assert groups[0]["model"] == "Intel Xeon Gold 6338"   # 가드 전: 'unknown'
    assert groups[0]["manufacturer"] == "Intel"           # 가드 전: None
    assert groups[0]["sockets"] == 1                       # 가드 전: dict key 수
    assert groups[0]["total_cores"] == 32                  # 가드 전: 0


def test_multi_socket_list_regression():
    """다중 소켓 list 정상 동작 불변 (회귀 방어)."""
    out = _render({"processors": [dict(_SINGLE), dict(_SINGLE)]})
    groups = out["groups"]
    assert len(groups) == 1            # 같은 model → 1 group
    assert groups[0]["sockets"] == 2
    assert groups[0]["total_cores"] == 64
    assert groups[0]["cores_per_socket"] == 32


def test_empty_processors():
    assert _render({"processors": []}) == {"groups": []}
    assert _render({}) == {"groups": []}
