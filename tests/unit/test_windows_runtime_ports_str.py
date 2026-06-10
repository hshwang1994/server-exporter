"""windows gather_system listening_ports str[] 계약.

gather_runtime rescue 가 {} 로 바뀌어(데이터 유실 방지) gather_system 의 runtime 이 보존될 때,
listening_ports 가 int[](Get-NetTCPConnection LocalPort)로 새지 않도록 map('string') 적용했는지
gather_system.yml 의 **실제 Jinja2 표현식**을 추출·렌더링해 검증.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SYS_YML = REPO / "os-gather" / "tasks" / "windows" / "gather_system.yml"


def _ports_expr() -> str:
    for t in yaml.safe_load(SYS_YML.read_text(encoding="utf-8")):
        if not isinstance(t, dict):
            continue
        sf = t.get("ansible.builtin.set_fact") or {}
        frag = sf.get("_data_fragment")
        if isinstance(frag, dict):
            rt = (frag.get("system") or {}).get("runtime") or {}
            if "listening_ports" in rt:
                return rt["listening_ports"]
    raise AssertionError("windows gather_system runtime.listening_ports expr not found")


def _render(ports):
    out = NativeEnvironment().from_string(_ports_expr()).render(_w_runtime={"listening_ports": ports})
    if isinstance(out, str):
        out = ast.literal_eval(out.strip())
    return out


def test_windows_listening_ports_int_to_str():
    out = _render([22, 53, 3389])     # Get-NetTCPConnection LocalPort = int
    assert out == ["22", "53", "3389"]
    assert all(isinstance(p, str) for p in out)


def test_windows_listening_ports_empty():
    assert _render([]) == []
