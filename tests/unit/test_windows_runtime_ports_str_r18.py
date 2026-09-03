"""Round 18 (R18-2) — windows system.runtime.listening_ports str[] 계약.

2026-09-03 부터 Windows system.runtime 의 단일 구현은 gather_runtime.yml 이다 (gather_system 의
이중 구현 제거 — B-31). listening_ports 가 int[](Get-NetTCPConnection LocalPort)로 새지 않도록
문자열로 바꾸는지 gather_runtime.yml 의 **실제 Jinja2 표현식**을 추출·렌더링해 검증.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RT_YML = REPO / "os-gather" / "tasks" / "windows" / "gather_runtime.yml"


def _ports_expr() -> str:
    for t in yaml.safe_load(RT_YML.read_text(encoding="utf-8")):
        if not isinstance(t, dict):
            continue
        for sub in (t.get("block") or []):
            sf = sub.get("ansible.builtin.set_fact") if isinstance(sub, dict) else None
            frag = (sf or {}).get("_data_fragment")
            if isinstance(frag, dict):
                rt = (frag.get("system") or {}).get("runtime") or {}
                if isinstance(rt, dict) and "listening_ports" in rt:
                    return rt["listening_ports"]
    raise AssertionError("windows gather_runtime runtime.listening_ports expr not found")


def _render(ports):
    out = NativeEnvironment().from_string(_ports_expr()).render(_w_rt_ports_list=ports)
    if isinstance(out, str):
        out = ast.literal_eval(out.strip())
    return out


def test_windows_listening_ports_int_to_str():
    out = _render([22, 53, 3389])     # Get-NetTCPConnection LocalPort = int
    assert out == ["22", "53", "3389"]
    assert all(isinstance(p, str) for p in out)


def test_windows_listening_ports_empty():
    assert _render([]) == []
