"""gather_system listening_ports 타입 계약(str[]).

field_dictionary 와 전 baseline 은 listening_ports 를 str[] (["22","53"]) 로 규정하나
gather_system 은 int 로 모았다(`s | int`) → int[] 유출 위험(특히 rescue/부분실패 경로,
gather_runtime 의 overwrite 가 일어나지 않을 때). 수치 정렬 후 map('string') 으로 str[]
변환이 적용됐는지, gather_system.yml 의 **실제 Jinja2 파서 표현식**을 렌더링해 검증한다.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SYS_YML = REPO / "os-gather" / "tasks" / "linux" / "gather_system.yml"
_PARSE_TASK = "linux | system | parse runtime"


def _parse_template() -> str:
    for t in yaml.safe_load(SYS_YML.read_text(encoding="utf-8")):
        if isinstance(t, dict) and t.get("name") == _PARSE_TASK:
            return t["ansible.builtin.set_fact"]["_l_runtime"]
    raise AssertionError(f"task {_PARSE_TASK!r} not found")


def _render(stdout_lines):
    env = NativeEnvironment()
    # `unique` 는 Ansible 필터(jinja2 builtin 아님) — order-preserving dedup 으로 대체.
    env.filters["unique"] = lambda seq: list(dict.fromkeys(seq))
    out = env.from_string(_parse_template()).render(
        _l_runtime_raw={"stdout_lines": stdout_lines}
    )
    if isinstance(out, str):
        out = ast.literal_eval(out.strip())
    return out


def test_listening_ports_emitted_as_str_numerically_sorted():
    lines = [
        "TZ=Etc/UTC", "NTPACTIVE=yes", "FW_TOOL=firewalld", "FW_STATE=active",
        "PORTS_BEGIN", "111", "22", "53", "631", "PORTS_END",
        "SWAP_TOTAL=4095", "SWAP_USED=0", "SWAP_FREE=4095",
    ]
    kv = _render(lines)
    ports = kv["PORTS"]
    assert ports == ["22", "53", "111", "631"]              # 수치 정렬 + str (가드 전: [22,53,111,631] int)
    assert all(isinstance(p, str) for p in ports)           # 계약: str[]


def test_listening_ports_empty():
    lines = ["TZ=Etc/UTC", "PORTS_BEGIN", "PORTS_END", "SWAP_TOTAL=0"]
    assert _render(lines)["PORTS"] == []


def test_listening_ports_dedup():
    lines = ["PORTS_BEGIN", "22", "22", "443", "PORTS_END"]
    assert _render(lines)["PORTS"] == ["22", "443"]
