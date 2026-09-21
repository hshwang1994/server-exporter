"""filter_plugins/failure_reason.py — 사용자 문구 카탈로그 선택 필터 (2026-09-21).

rescue 4곳과 빌더가 이 필터 하나로 문장을 고른다. 여기서는 필터 자체의 규칙과,
같은 규칙을 복제한 callback(json_only._display_location / _reason)이 같은 결과를
내는지를 고정한다. 문장 **내용**의 계약은 tests/e2e/test_errors_message_contract.py 가 본다.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


frf = _load("se_failure_reason_filter_unit", REPO / "filter_plugins" / "failure_reason.py")

try:                                          # ansible 이 있으면 실물 기반 클래스를 쓴다
    import ansible.plugins.callback  # noqa: F401
except ImportError:                           # 없으면 최소 대역
    _cb = types.ModuleType("ansible.plugins.callback")

    class _CallbackBase:
        def __init__(self, *_a, **_k):
            pass

    _cb.CallbackBase = _CallbackBase
    _plugins = sys.modules.setdefault("ansible.plugins", types.ModuleType("ansible.plugins"))
    _plugins.callback = _cb
    sys.modules.setdefault("ansible", types.ModuleType("ansible")).plugins = _plugins
    sys.modules["ansible.plugins.callback"] = _cb

sys.path.insert(0, str(REPO / "callback_plugins"))
import json_only  # noqa: E402

CATALOG = yaml.safe_load(
    (REPO / "common" / "vars" / "failure_reasons.yml").read_text(encoding="utf-8"))["_fr_catalog"]


def test_channel_sentence_is_preferred():
    assert frf.failure_reason(CATALOG, "port_refused", "esxi") == CATALOG["port_refused"]["esxi"]


def test_missing_channel_falls_back_to_default():
    # target_unreachable 은 채널 문장이 없다 → default
    for channel in ("os", "esxi", "redfish", None, ""):
        assert frf.failure_reason(CATALOG, "target_unreachable", channel) == \
            CATALOG["target_unreachable"]["default"]


def test_unknown_key_raises_instead_of_empty_sentence():
    """빈 문장으로 조용히 넘어가지 않는다 — Portal 사유 칸이 비는 것보다 fallback 이 낫다."""
    with pytest.raises(KeyError):
        frf.failure_reason(CATALOG, "no_such_key", "os")


def test_entry_without_default_raises_for_other_channel():
    # auth_rejected 는 redfish 문장만 있다 (OS / ESXi 는 거부를 확정할 근거가 없다)
    assert frf.failure_reason(CATALOG, "auth_rejected", "redfish")
    with pytest.raises(KeyError):
        frf.failure_reason(CATALOG, "auth_rejected", "os")


@pytest.mark.parametrize("raw,shown", [
    ("ic", "ic"),
    ("  seoul-dc1  ", "seoul-dc1"),
    ("", "미지정"),
    (None, "미지정"),
    ("   ", "미지정"),
    ("{{ x }}", "x"),
    ("a b/c", "abc"),
    ("x" * 60, "x" * 40),
])
def test_location_display_rule(raw, shown):
    assert frf.display_location(raw) == shown
    # callback 복제본도 같은 결과를 낸다
    assert json_only._display_location(raw) == shown


def test_loc_placeholder_is_replaced():
    text = frf.failure_reason(CATALOG, "loc_vault_unreadable", None, "ic")
    assert text == "해당 위치(ic)의 Vault를 읽을 수 없습니다."


@pytest.mark.parametrize("key", sorted(json_only._FAILURE_REASON_CATALOG))
@pytest.mark.parametrize("channel", ["os", "esxi", "redfish", None])
def test_callback_reason_matches_filter(key, channel):
    """callback 의 _reason() 과 필터가 같은 (키, 채널, 위치) 에서 같은 문장을 낸다."""
    try:
        expected = frf.failure_reason(CATALOG, key, channel, "ic")
    except KeyError:
        pytest.skip("정본에도 해당 채널 문장이 없다")
    assert json_only._reason(key, channel, "ic") == expected


def test_filter_is_registered_under_the_template_name():
    assert frf.FilterModule().filters()["failure_reason"] is frf.failure_reason
