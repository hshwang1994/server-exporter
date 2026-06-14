"""Round 19 (R19-1) — windows gather_runtime firewall_state loop-scoping fix.

plain `{% set any_enabled %}` 가 for-loop 밖으로 전파되지 않아 firewall_state 가 모든
호스트에서 'inactive' 로 오보되던 것(보안 필드) → namespace 패턴으로 수정. gather_runtime.yml
의 **실제 Jinja2 표현식**을 추출·렌더링해 enabled 프로필이 있으면 'active' 가 나오는지 검증.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RT_YML = REPO / "os-gather" / "tasks" / "windows" / "gather_runtime.yml"


def _firewall_state_expr() -> str:
    for t in yaml.safe_load(RT_YML.read_text(encoding="utf-8")):
        # block 안의 set_fact 들을 순회
        for key in ("block",):
            for sub in (t.get(key) or []) if isinstance(t, dict) else []:
                sf = sub.get("ansible.builtin.set_fact") if isinstance(sub, dict) else None
                if isinstance(sf, dict):
                    rt = ((sf.get("_data_fragment") or {}).get("system") or {}).get("runtime") or {}
                    if isinstance(rt, dict) and "firewall_state" in rt:
                        return rt["firewall_state"]
    raise AssertionError("windows gather_runtime firewall_state expr not found")


def _render(fw_list):
    return NativeEnvironment().from_string(_firewall_state_expr()).render(_w_rt_fw_list=fw_list)


def test_firewall_state_active_when_any_profile_enabled():
    assert _render([{"enabled": True}]) == "active"                          # 가드 전: 'inactive'
    assert _render([{"enabled": False}, {"enabled": True}]) == "active"      # 가드 전: 'inactive'
    assert _render([{"enabled": True}, {"enabled": True}, {"enabled": True}]) == "active"


def test_firewall_state_inactive_when_all_disabled():
    assert _render([{"enabled": False}]) == "inactive"
    assert _render([]) == "inactive"
