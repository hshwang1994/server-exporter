"""json_only 콜백 직렬화 robustness (Round 2 #0/#9 — rule 95 R1).

비-JSON-직렬화 객체(datetime / set / Ansible 객체)가 OUTPUT 에 섞이면 json.dumps 가
TypeError 로 콜백 전체를 죽여 OUTPUT 이 통째로 소실된다. str fallback 으로 graceful.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "callback_plugins"))

pytest.importorskip("ansible.plugins.callback", reason="ansible 미설치")
import json_only  # noqa: E402


def test_emit_non_serializable_does_not_crash():
    """set/datetime 등 비-직렬화 객체 → TypeError 로 죽지 않고 str fallback."""
    cb = json_only.CallbackModule()
    buf = io.StringIO()
    cb._emit({"x": {1, 2, 3}}, file=buf)  # set 은 json 직렬화 불가 → 가드 전 TypeError
    out = buf.getvalue().strip()
    assert out  # 무언가 출력됨 (crash 아님)


def test_emit_wellformed_dict_unchanged():
    """정상 dict 는 그대로 compact JSON (fallback 미발동)."""
    cb = json_only.CallbackModule()
    buf = io.StringIO()
    cb._emit({"status": "success", "data": {"cpu": {"cores": 8}}}, file=buf)
    parsed = json.loads(buf.getvalue().strip())
    assert parsed == {"status": "success", "data": {"cpu": {"cores": 8}}}
