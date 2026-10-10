"""LX-F12 (2026-10-10) — DMI/SMBIOS 자리표시자 집합은 한 곳(identity_normalizer.DMI_SENTINELS)이고 세 채널이 같은 뜻으로 쓴다.

- dmi_sentinel_null 필터: 종전 Linux/Windows 인라인 목록의 합집합 + 'N/A'(Redfish) — 대소문자 · 공백 무시, 자리표시자는 None.
- normalize_uuid: SMBIOS 공장 기본값 03000200-0400-0500-0006-000700080009(및 바이트 순서 반전형)는 all-0/all-f 처럼 None.
- Redfish 모듈의 _SERIAL_SENTINELS_UPPER 는 같은 집합의 복제본이다 (drift guard).
- Linux / Windows / ESXi 의 실제 템플릿이 그 필터를 쓴다 — 인라인 목록은 남아 있지 않다.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")
from jinja2.nativetypes import NativeEnvironment  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from identity_normalizer import DMI_SENTINELS, dmi_sentinel_null, is_dmi_sentinel, normalize_uuid  # noqa: E402
from linux_raw_harness import SYSTEM_YML, ansible_env, render_tree, set_fact_args  # noqa: E402


@pytest.mark.parametrize("raw,kind", [
    ("To Be Filled By O.E.M.", "serial"), ("to be filled by o.e.m.", "serial"), ("  NA ", "serial"), ("N/A", "serial"), ("None", "serial"),
    ("Not Specified", "serial"), ("System Serial Number", "serial"), ("Default string", "serial"), ("0", "serial"), ("00000000", "serial"),
    ("", "serial"), (None, "serial"), ("System manufacturer", "vendor"), ("System Product Name", "model"), ("Default string", "bios"),
    ("NA", "uuid"), ("03000200-0400-0500-0006-000700080009", "uuid"), ("00020003-0004-0005-0006-000700080009", "uuid"),
    ("00000000-0000-0000-0000-000000000000", "uuid"), ("FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF", "uuid"),
])
def test_sentinels_become_null(raw, kind):
    assert is_dmi_sentinel(raw, kind) is True and dmi_sentinel_null(raw, kind) is None


@pytest.mark.parametrize("raw,kind,expected", [
    (" GSBPK54 ", "serial", "GSBPK54"), ("VMware-42 04 a2 40 1d 5c 63 c9-f6 0b 5f b4 72 98 d7 dd", "serial", "VMware-42 04 a2 40 1d 5c 63 c9-f6 0b 5f b4 72 98 d7 dd"),
    ("Dell Inc.", "vendor", "Dell Inc."), ("PowerEdge R760", "model", "PowerEdge R760"), ("2.3.5", "bios", "2.3.5"),
    ("4c4c4544-0053-4210-8050-c7c04f4b3534", "uuid", "4c4c4544-0053-4210-8050-c7c04f4b3534"),
    ("System Serial Number", "vendor", "System Serial Number"),   # 다른 종류의 자리표시자는 그 종류에서만 (값을 지어내지 않는다)
])
def test_real_values_pass_through_trimmed(raw, kind, expected):
    assert dmi_sentinel_null(raw, kind) == expected


def test_unknown_kind_is_an_error():
    with pytest.raises(ValueError):
        dmi_sentinel_null("x", "asset")


def test_normalize_uuid_treats_smbios_factory_default_as_null():
    assert normalize_uuid("03000200-0400-0500-0006-000700080009") is None
    assert normalize_uuid("{00020003-0004-0005-0006-000700080009}") is None
    assert normalize_uuid("4C4C4544-0053-4210-8050-C7C04F4B3534") == "4c4c4544-0053-4210-8050-c7c04f4b3534"


def test_sets_are_the_documented_union_of_the_former_inline_lists():
    former_serial = {"", "na", "none", "not specified", "to be filled by o.e.m.", "system serial number", "default string", "0", "00000000"}
    assert DMI_SENTINELS["serial"] == former_serial | {"n/a"}
    assert DMI_SENTINELS["uuid"] >= {"", "na", "none", "not specified"}
    assert "system manufacturer" in DMI_SENTINELS["vendor"] and "system product name" in DMI_SENTINELS["model"]


# ── Redfish mirror ──────────────────────────────────────────────────────────────────────────────────────────────
def _redfish_module():
    if "ansible.module_utils.basic" not in sys.modules:
        mock_basic = types.ModuleType("ansible.module_utils.basic")
        mock_basic.AnsibleModule = type("AnsibleModule", (), {})
        sys.modules.setdefault("ansible", types.ModuleType("ansible"))
        sys.modules.setdefault("ansible.module_utils", types.ModuleType("ansible.module_utils"))
        sys.modules["ansible.module_utils.basic"] = mock_basic
    spec = importlib.util.spec_from_file_location("redfish_gather_sentinel_guard", str(REPO / "redfish-gather" / "library" / "redfish_gather.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_redfish_serial_sentinels_mirror_the_shared_set():
    mirror = {x.lower() for x in _redfish_module()._SERIAL_SENTINELS_UPPER}
    assert mirror | {""} == DMI_SENTINELS["serial"], "redfish_gather._SERIAL_SENTINELS_UPPER 와 identity_normalizer.DMI_SENTINELS['serial'] 이 다르다"


# ── 세 채널의 실제 템플릿 ──────────────────────────────────────────────────────────────────────────────────────────
def _set_fact_strings(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("ansible.builtin.set_fact", "set_fact") and isinstance(v, dict):
                yield from (s for s in v.values() if isinstance(s, str))
            else:
                yield from _set_fact_strings(v)
    elif isinstance(node, list):
        for item in node:
            yield from _set_fact_strings(item)


def test_no_inline_identity_sentinel_lists_remain_in_jinja_templates():
    """식별자(serial/uuid/vendor/model/bios) 자리표시자 목록은 Jinja 템플릿 안에 다시 쓰지 않는다 — 필터 하나를 쓴다.

    범위 밖(의도): PowerShell 본문의 목록(Windows 는 cmdlet 쪽에서 1차로 거른다 — 다른 런타임) 과
    gather_memory.yml 의 DIMM 제조사 자리표시자('NO DIMM' 등 — 식별자가 아니라 메모리 모듈 필드).
    """
    offenders = []
    for yml in list((REPO / "os-gather" / "tasks").rglob("*.yml")) + list((REPO / "esxi-gather" / "tasks").rglob("*.yml")):
        if yml.name == "gather_memory.yml":
            continue
        for tpl in _set_fact_strings(yaml.safe_load(yml.read_text(encoding="utf-8"))):
            if "To Be Filled By O.E.M." in tpl or "System Serial Number" in tpl:
                offenders.append(str(yml.relative_to(REPO)))
                break
    assert offenders == [], offenders


def test_linux_raw_identity_templates_use_the_shared_filter():
    env = ansible_env()
    args = set_fact_args(SYSTEM_YML, "set raw-derived variables")
    raw = {"DMI_PRODUCT_SERIAL": "To Be Filled By O.E.M.", "DMI_PRODUCT_UUID": "03000200-0400-0500-0006-000700080009",
           "DMI_SYS_VENDOR": "System manufacturer", "DMI_PRODUCT_NAME": " PowerEdge R760 ", "DMI_BIOS_VERSION": "Default string"}
    out = {k: render_tree(env, args[k], {"_l_raw_sys": raw}) for k in ("_l_raw_serial", "_l_raw_uuid", "_l_raw_vendor", "_l_raw_model", "_l_raw_bios_version")}
    assert out == {"_l_raw_serial": None, "_l_raw_uuid": None, "_l_raw_vendor": None, "_l_raw_model": "PowerEdge R760", "_l_raw_bios_version": None}
    hw = set_fact_args(SYSTEM_YML, "resolve hardware identity")
    ctx = {"ansible_system_vendor": "System manufacturer", "_l_raw_vendor": "Dell Inc.", "ansible_product_name": "Not Specified", "_l_raw_model": None,
           "ansible_bios_version": "2.3.5", "_l_raw_bios_version": "9.9.9"}
    assert render_tree(env, hw["_l_hw_vendor"], ctx) == "Dell Inc."        # setup 값이 자리표시자 → raw 값
    assert render_tree(env, hw["_l_hw_model"], ctx) is None
    assert render_tree(env, hw["_l_hw_bios_version"], ctx) == "2.3.5"
    setup = set_fact_args(SYSTEM_YML, "check setup fact identifiers")
    assert render_tree(env, setup["_l_serial_from_setup"], {"ansible_product_serial": "System Serial Number"}) is None
    assert render_tree(env, setup["_l_serial_from_setup"], {"ansible_product_serial": "GSBPK54"}) == "GSBPK54"
    assert render_tree(env, setup["_l_uuid_from_setup"], {"ansible_product_uuid": "NA"}) is None


def _windows_identity(ctx):
    env = NativeEnvironment()
    env.filters.update({"dmi_sentinel_null": dmi_sentinel_null, "normalize_uuid": normalize_uuid})
    tasks = yaml.safe_load((REPO / "os-gather" / "tasks" / "windows" / "gather_system.yml").read_text(encoding="utf-8"))
    args = next(t for t in tasks if isinstance(t, dict) and t.get("name") == "windows | system | resolve identifiers")["ansible.builtin.set_fact"]
    return {k: env.from_string(v).render(**ctx) for k, v in args.items()}


def test_windows_identity_templates_use_the_shared_filter():
    out = _windows_identity({"ansible_product_serial": "To Be Filled By O.E.M.", "ansible_product_uuid": "03000200-0400-0500-0006-000700080009"})
    assert out == {"_w_serial_val": None, "_w_uuid_val": None}
    out = _windows_identity({"ansible_product_serial": " VMware-42 04 ", "ansible_product_uuid": "{40A20442-5C1D-C963-F60B-5FB47298D7DD}"})
    assert out == {"_w_serial_val": "VMware-42 04", "_w_uuid_val": "40a20442-5c1d-c963-f60b-5fb47298d7dd"}


def test_esxi_identity_templates_null_the_na_placeholder():
    env = NativeEnvironment()
    env.filters.update({"dmi_sentinel_null": dmi_sentinel_null, "normalize_uuid": normalize_uuid})
    tasks = yaml.safe_load((REPO / "esxi-gather" / "tasks" / "normalize_system.yml").read_text(encoding="utf-8"))
    frag = next(t for t in tasks if isinstance(t, dict) and "_data_fragment" in (t.get("ansible.builtin.set_fact") or {}))["ansible.builtin.set_fact"]["_data_fragment"]
    facts = {"ansible_product_serial": "NA", "ansible_system_vendor": "VMware, Inc.", "ansible_product_name": "VMware Virtual Platform",
             "ansible_bios_version": "Not Specified", "ansible_uuid": "564d1234-0000-0000-0000-000000000000"}
    sys_serial = env.from_string(frag["system"]["serial_number"]).render(_e_raw_facts=facts)
    hw = {k: env.from_string(frag["hardware"][k]).render(_e_raw_facts=facts) for k in ("vendor", "model", "serial", "bios_version")}
    assert sys_serial is None and hw == {"vendor": "VMware, Inc.", "model": "VMware Virtual Platform", "serial": None, "bios_version": None}
    real = env.from_string(frag["hardware"]["serial"]).render(_e_raw_facts={"ansible_product_serial": "VMware-56 4d 12 34"})
    assert real == "VMware-56 4d 12 34"
