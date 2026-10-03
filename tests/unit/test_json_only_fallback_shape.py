"""json_only 보충 envelope 의 shape 가 rescue 경로(build_failed_output.yml)·site.yml always 와 같은지 (2026-10-03, Plan §7-7 / N2).

종전에는 콜백이 보충한 envelope 만 `hostname=<IP>`, `sections/meta/correlation/data = {}` 였다 — 실패 종류에 따라
호출자가 세 가지 모양을 봤다. 여기서는
  1. json_only 안의 정본 복제표(_CHANNEL_SECTIONS · _META_KEYS · _CORRELATION_KEYS · _DATA_SKELETON)가 YAML 정본과
     같은지 (drift 가드 — 정본: common/vars/supported_sections.yml, build_meta.yml, build_correlation.yml, init_fragments.yml)
  2. `_build_fallback_envelope` / `_minimal_envelope` 가 hostname=null, 11 섹션, meta 6 키, correlation 4 키, data 뼈대를 내는지
를 고정한다. Ansible 은 실행하지 않는다.
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "callback_plugins"))

try:                                          # ansible 이 있으면 실물 기반 클래스를 쓴다
    import ansible.plugins.callback  # noqa: F401
except ImportError:                           # 없으면 최소 대역
    _cb = types.ModuleType("ansible.plugins.callback")

    class _CallbackBase:                      # noqa: D401
        def __init__(self, *_a, **_k):
            pass

    _cb.CallbackBase = _CallbackBase
    _plugins = sys.modules.setdefault("ansible.plugins", types.ModuleType("ansible.plugins"))
    _plugins.callback = _cb
    sys.modules.setdefault("ansible", types.ModuleType("ansible")).plugins = _plugins
    sys.modules["ansible.plugins.callback"] = _cb

import json_only  # noqa: E402

NORM = REPO / "common" / "tasks" / "normalize"
ALL = ["system", "hardware", "bmc", "cpu", "memory", "storage", "network", "firmware", "users", "power", "thermal"]


def _set_fact(path, var):
    for t in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        sf = (t or {}).get("ansible.builtin.set_fact") or (t or {}).get("set_fact") or {}
        if var in sf:
            return sf[var]
    raise AssertionError(f"{path.name}: set_fact {var} 없음")


# ── 1. 정본 복제표 drift ──────────────────────────────────────────────────

def test_channel_sections_match_supported_sections_yml():
    cfg = yaml.safe_load((REPO / "common" / "vars" / "supported_sections.yml").read_text(encoding="utf-8"))
    assert list(json_only._ALL_SECTIONS) == cfg["all_sections"] == ALL
    for ch, secs in cfg["channel_sections"].items():
        assert list(json_only._CHANNEL_SECTIONS[ch]) == secs, ch
    assert set(json_only._CHANNEL_SECTIONS) == set(cfg["channel_sections"])


def test_meta_and_correlation_keys_match_builders():
    assert list(json_only._META_KEYS) == list(_set_fact(NORM / "build_meta.yml", "_meta"))
    assert list(json_only._CORRELATION_KEYS) == list(_set_fact(NORM / "build_correlation.yml", "_correlation"))


def _key_paths(node, prefix=""):
    out = set()
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{prefix}.{k}" if prefix else k
            out.add(p)
            out |= _key_paths(v, p)
    return out


def test_data_skeleton_matches_init_fragments():
    skeleton = _set_fact(NORM / "init_fragments.yml", "_merged_data")
    assert list(json_only._DATA_SKELETON) == list(skeleton), "최상위 키 순서까지 같다"
    assert _key_paths(json_only._DATA_SKELETON) == _key_paths(skeleton)
    assert json_only._DATA_SKELETON == skeleton


def test_redfish_always_block_uses_the_same_shape():
    """redfish-gather/site.yml always OUTPUT 기본값도 같은 표를 쓴다 (os/esxi 는 test_always_fallback_envelope 가 검사)."""
    text = (REPO / "redfish-gather" / "site.yml").read_text(encoding="utf-8")
    m = re.search(r"'sections': (\{[^}]*\}),\s*'diagnosis'", text)
    assert m, "always OUTPUT 의 sections 기본값 미발견"
    sections = yaml.safe_load(m.group(1).replace("'", '"'))
    expected = json_only._failed_shape("redfish", "x")["sections"]
    assert sections == expected, "redfish always sections 가 json_only/supported_sections 와 다르다"
    assert "'hostname': none," in text and "'hostname': _rf_ip" not in text


# ── 2. 보충 envelope shape ───────────────────────────────────────────────

def _fresh():
    cb = json_only.CallbackModule()
    return cb


def test_minimal_envelope_has_full_failed_shape():
    cb = _fresh()
    cb._playbook_channel = "redfish"
    env = cb._minimal_envelope("10.0.0.7")
    assert list(env) == ["schema_version", "target_type", "collection_method", "ip", "hostname", "vendor", "status",
                         "sections", "diagnosis", "meta", "correlation", "errors", "data"]
    assert env["ip"] == "10.0.0.7" and env["hostname"] is None
    assert list(env["sections"]) == ALL and env["sections"]["users"] == "not_supported"
    assert env["sections"]["power"] == "failed" and env["sections"]["thermal"] == "failed"
    assert set(env["meta"]) == set(json_only._META_KEYS) and set(env["meta"].values()) == {None}
    assert env["correlation"] == {"serial_number": None, "system_uuid": None, "bmc_ip": "10.0.0.7", "host_ip": "10.0.0.7"}
    assert env["data"] == json_only._DATA_SKELETON and env["data"] is not json_only._DATA_SKELETON


def test_fallback_envelope_has_full_failed_shape_and_null_hostname():
    cb = _fresh()
    cb._playbook_channel = "os"
    ctx = cb._ctx("h1")
    ctx["ip"] = "10.0.0.8"
    env = cb._build_fallback_envelope("h1", ctx)
    assert env["ip"] == "10.0.0.8" and env["hostname"] is None, "hostname 을 IP 로 대체하지 않는다"
    assert list(env["sections"]) == ALL
    assert env["sections"]["users"] == "failed" and env["sections"]["bmc"] == "not_supported"
    assert set(env["meta"]) == set(json_only._META_KEYS)
    assert env["correlation"]["host_ip"] == "10.0.0.8" and env["correlation"]["bmc_ip"] is None
    assert env["data"] == json_only._DATA_SKELETON
    assert env["diagnosis"]["failure_stage"] == "fallback" and env["diagnosis"]["failure_code"] == "OUTPUT_BUILD_FAILED"


def test_fallback_data_objects_are_not_shared_between_hosts():
    cb = _fresh()
    cb._playbook_channel = "esxi"
    a = cb._minimal_envelope("10.0.0.1")
    b = cb._minimal_envelope("10.0.0.2")
    a["data"]["storage"]["filesystems"].append("x")
    assert b["data"]["storage"]["filesystems"] == [] and json_only._DATA_SKELETON["storage"]["filesystems"] == []
