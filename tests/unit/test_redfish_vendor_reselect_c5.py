"""인증 후 확인한 vendor 로 adapter 를 다시 고른다 (2026-10-10 C5).

종전 결함(검수 2026-10-09 재현 — real_lenovo_sr650 + 익명 ServiceRoot 식별 정보 제거 + 무인증 401):
  무인증 probe 는 vendor 를 unknown 으로, 인증 후 수집은 Chassis Manufacturer 로 lenovo 를 확인했는데 재선택은 probe 값만 써서
  redfish_generic 을 골랐다(결과 vendor 도 null). 수정: collect_standard 의 "set vendor" 가 성공한 수집의 유효한 canonical vendor 를
  먼저 쓰고, 없거나 unknown 이면 probe 의 유효값을 쓴다. reselect 는 그 값(_rf_vendor)을 facts.vendor 로 쓴다.

이 시험은 기록 응답에 익명 제한을 적용한 재현이다 — 모든 Lenovo 장비에서 지금 일어난다는 뜻이 아니다. 식별된 장비의 결과가 바뀌지 않음은
모든 recording 에서 probe vendor == 인증 후 vendor 로 확인한다.
"""
from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "module_utils"))
sys.path.insert(0, str(REPO / "filter_plugins"))

_stub_basic = types.ModuleType("ansible.module_utils.basic")
_stub_basic.AnsibleModule = object
_stub_module_utils = types.ModuleType("ansible.module_utils")
_stub_module_utils.basic = _stub_basic
_stub_ansible = types.ModuleType("ansible")
_stub_ansible.module_utils = _stub_module_utils
sys.modules.setdefault("ansible", _stub_ansible)
sys.modules.setdefault("ansible.module_utils", _stub_module_utils)
sys.modules.setdefault("ansible.module_utils.basic", _stub_basic)

import redfish_gather as rg  # noqa: E402
from adapter_common import adapter_matches, adapter_score, load_vendor_aliases  # noqa: E402
from vendor_normalizer import canonical_vendor  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "redfish"
VA = yaml.safe_load((REPO / "common" / "vars" / "vendor_aliases.yml").read_text(encoding="utf-8"))
ALIASES = load_vendor_aliases(str(REPO / "common" / "vars" / "vendor_aliases.yml"))


def _env():
    env = NativeEnvironment()
    env.filters["canonical_vendor"] = canonical_vendor
    env.filters["bool"] = lambda v: v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes", "on")
    return env


def _set_fact(path, name, key):
    for t in yaml.safe_load(path.read_text(encoding="utf-8")):
        if t.get("name") == name:
            return t["ansible.builtin.set_fact"][key]
    raise AssertionError(f"{path.name}: {name}")


SET_VENDOR = _set_fact(REPO / "redfish-gather/tasks/collect_standard.yml", "redfish | collect_standard | set vendor", "_rf_vendor")
POSTAUTH = _set_fact(REPO / "redfish-gather/tasks/reselect_adapter.yml", "redfish | reselect | 인증 후 facts 조립", "_rf_postauth_facts")


def _rf_vendor(raw_vendor, collect_ok, detected):
    ctx = {"_rf_raw_collect": {"vendor": raw_vendor}, "_rf_collect_ok": collect_ok, "_rf_detected_vendor": detected, "_va": VA}
    return _env().from_string(SET_VENDOR).render(**ctx)


def _postauth_facts(rf_vendor, probe_vendor, raw):
    ctx = {"_rf_vendor": rf_vendor, "_rf_probe_facts": {"vendor": probe_vendor}, "_rf_raw_collect": raw}
    return {k: _env().from_string(v).render(**ctx) for k, v in POSTAUTH.items()}


def _select(facts):
    best = []
    for path in sorted((REPO / "adapters" / "redfish").glob("*.yml")):
        adapter = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if adapter_matches(adapter, facts, ALIASES):
            score = adapter_score(adapter, facts, ALIASES)
            if score > -9999:
                best.append((score, adapter.get("adapter_id")))
    return sorted(best, reverse=True)[0][1]


@pytest.mark.parametrize("raw,ok,detected,expected", [
    ("lenovo", True, "unknown", "lenovo"),                    # probe 미식별 · 인증 후 확인 → 인증 후 값
    ("Lenovo", True, "unknown", "lenovo"),                    # 원시 표기도 canonical 로
    ("unknown", True, "dell", "dell"),                        # 인증 후 미식별 → probe 유효값
    ("", True, "hpe", "hpe"),
    ("lenovo", False, "unknown", None),                       # 수집 실패면 인증 후 값을 쓰지 않는다
    ("lenovo", False, "lenovo", "lenovo"),
    ("unknown", True, "unknown", None),
    (None, True, "unknown", None),
    ("not-a-vendor", True, "unknown", None),                  # 등록되지 않은 표기는 canonical 이 아니다
])
def test_set_vendor_prefers_a_valid_post_auth_vendor(raw, ok, detected, expected):
    assert _rf_vendor(raw, ok, detected) == expected


def test_reselect_uses_rf_vendor_and_falls_back_to_the_probe_value():
    raw = {"data": {"system": {"model": "ThinkSystem SR650 V4"}, "bmc": {"firmware_version": "IHX414J 1.22"}}}
    assert _postauth_facts("lenovo", "unknown", raw)["vendor"] == "lenovo"
    assert _postauth_facts(None, "unknown", raw)["vendor"] == "unknown"
    assert _postauth_facts(None, "Dell Inc.", raw)["vendor"] == "Dell Inc."


# ── 실제 모듈: 익명 ServiceRoot 에 식별 정보가 없고 무인증 요청이 401 인 Lenovo 재현 ─────────────────────────────────

class _Captured(Exception):
    def __init__(self, result):
        self.result = result


def _module(mode):
    class _M:
        def __init__(self, **kwargs):
            self.check_mode = False
            self.params = {"bmc_ip": "192.0.2.1", "username": "" if mode == "detect" else "std", "password": "<pw>",
                           "timeout": 30, "verify_ssl": False, "mode": mode, "manager_layout": None, "attempt": None}

        def exit_json(self, **result):
            raise _Captured(result)

        def fail_json(self, **result):
            raise AssertionError(result)
    return _M


def _run(monkeypatch, recording, mode, root=None):
    def get(ip, path, user, *args, **kwargs):
        if not user:
            return 401, {}, "HTTP 401: Unauthorized"
        return tuple(recording.get("get::" + path, (404, {}, "HTTP 404: Not Found")))

    def noauth(ip, path, *args, **kwargs):
        if root is not None and path == "":
            return 200, root, None
        return tuple(recording.get("noauth::" + path, (404, {}, "HTTP 404: Not Found")))

    monkeypatch.setattr(rg, "_get", get)
    monkeypatch.setattr(rg, "_get_noauth", noauth)
    monkeypatch.setattr(rg, "_probe_realm_hint", lambda *a, **k: None)
    monkeypatch.setattr(rg, "AnsibleModule", _module(mode))
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)
    try:
        rg.main()
    except _Captured as caught:
        return caught.result
    raise AssertionError("module did not return")


def test_lenovo_identified_only_after_auth_reselects_the_lenovo_adapter(monkeypatch):
    recording = json.loads((FIX / "real_lenovo_sr650" / "recording.json").read_text(encoding="utf-8"))
    root = copy.deepcopy(recording["noauth::"][1])
    for key in ("Oem", "Vendor", "Product", "Name"):
        root.pop(key, None)
    root["Name"] = "Root Service"
    probe = _run(monkeypatch, recording, "detect", root=root)
    raw = _run(monkeypatch, recording, "gather", root=root)
    assert canonical_vendor(probe["vendor"], VA["vendor_aliases"]) == "unknown"
    assert raw["status"] == "success"
    detected = canonical_vendor(probe["vendor"], VA["vendor_aliases"])
    rf_vendor = _rf_vendor(raw["vendor"], True, detected)
    assert rf_vendor == "lenovo"
    facts = _postauth_facts(rf_vendor, probe["vendor"], raw)
    chosen = _select(facts)
    assert chosen != "redfish_generic"
    assert chosen == _select(dict(facts, vendor="lenovo")), "vendor 를 알 때와 같은 adapter"


# ── 식별된 장비는 결과가 그대로: 모든 recording 에서 probe vendor == 인증 후 vendor ───────────────────────────────

RECORDINGS = sorted(p.parent.name for p in FIX.glob("*/recording.json"))


@pytest.mark.parametrize("fixture", RECORDINGS)
def test_post_auth_vendor_never_changes_an_identified_probe_vendor(monkeypatch, fixture):
    recording = json.loads((FIX / fixture / "recording.json").read_text(encoding="utf-8"))
    probe = _run(monkeypatch, recording, "detect")
    raw = _run(monkeypatch, recording, "gather")
    pv = canonical_vendor(probe.get("vendor"), VA["vendor_aliases"])
    av = canonical_vendor(raw.get("vendor"), VA["vendor_aliases"])
    ok = raw.get("status") != "failed"
    chosen = _rf_vendor(raw.get("vendor"), ok, pv)
    if pv != "unknown":
        assert chosen == pv, f"{fixture}: probe {pv} 를 인증 후 값 {av} 가 바꿨다"
