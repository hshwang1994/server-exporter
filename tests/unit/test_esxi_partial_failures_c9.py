"""ESXi 확장 수집 · runtime 부분 실패의 근거 (2026-10-10 C9).

종전 결함(검수 재현 — 실제 YAML set_fact + 공통 merge/build_*):
  모듈 조회에 failed_when: false 가 있어 실패해도 block rescue 로 가지 않았고, fragment 는 vmhba(HBA) · NTP 조회 실패(NoPermission)를
  빈 목록 · null 로만 남겼다 — "HBA 미설치" 와 "HBA 조회 실패", "NTP 미설정" 과 "NTP 조회 실패" 를 구분할 수 없었다.
수정: 실패 = **예상 결과 키 부재**(msg 가 비어도 실패, msg 는 원인 설명). 유효한 결과 키의 빈 mapping/list 는 정상(오류 없음).
섹션 상태 · 이미 확보한 데이터는 그대로 두고 errors[] 에 섹션별 1건을 남긴다(success + errors 허용 계약).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "unit"))
sys.path.insert(0, str(REPO / "filter_plugins"))

from errors_normalizer import normalize_errors  # noqa: E402
from identity_normalizer import normalize_mac, normalize_uuid, normalize_wwn  # noqa: E402
from linux_raw_harness import ansible_env, render_tree  # noqa: E402

EXT = REPO / "esxi-gather" / "tasks" / "collect_network_extended.yml"
RUNTIME = REPO / "esxi-gather" / "tasks" / "collect_runtime.yml"
BASE_SECTIONS = ["system", "hardware", "cpu", "memory", "storage", "network"]
NET_TEXT = "네트워크 정보 중 일부를 수집하지 못했습니다. 대상 상태와 수집 로그를 확인하세요."
STOR_TEXT = "스토리지 정보 중 일부를 수집하지 못했습니다. 대상 상태와 수집 로그를 확인하세요."


def _env():
    env = ansible_env()
    env.filters.update({"normalize_mac": normalize_mac, "normalize_uuid": normalize_uuid, "normalize_wwn": normalize_wwn,
                        "normalize_errors": normalize_errors, "union": lambda a, b: list(dict.fromkeys(list(a) + list(b)))})
    env.tests["failed"] = lambda x: bool((x or {}).get("failed", False))
    return env


def _facts(path, ctx, only_block=False):
    env = _env()
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if only_block:
        doc = doc[0]["block"]
    for task in doc:
        if "ansible.builtin.set_fact" in task:
            ctx.update({k: render_tree(env, v, ctx) for k, v in task["ansible.builtin.set_fact"].items()})
    return ctx


def _final(frag):
    ctx = {"_all_sec_supported": list(BASE_SECTIONS), "_all_sec_collected": list(BASE_SECTIONS), "_all_sec_failed": [],
           "_all_sec_unsupported": [], "_all_errors": [], **frag}
    for name in ("merge_fragment", "build_sections", "build_status", "build_errors"):
        _facts(REPO / "common" / "tasks" / "normalize" / f"{name}.yml", ctx)
    return ctx


OK_VMNIC = {"failed": False, "hosts_vmnics_info": {"esxi01": {"vmnic_details": [{"device": "vmnic0", "status": "connected", "actual_speed": 10000}]}}}
OK_VMHBA = {"failed": False, "hosts_vmhbas_info": {"esxi01": {"vmhba_details": [{"device": "vmhba2", "type": "Fibre Channel", "driver": "lpfc",
                                                                               "port_wwn": "21:00:00:24:ff:01:02:03"}]}}}
OK_VSW = {"failed": False, "hosts_vswitch_info": {"esxi01": {"vSwitch0": {"num_ports": 128, "mtu": 1500, "pnics": ["vmnic0"]}}}}
OK_PG = {"failed": False, "hosts_portgroup_info": {"esxi01": [{"portgroup": "VM Network", "vswitch": "vSwitch0"}]}}


def _ext(**mods):
    ctx = {"_e_ip": "192.0.2.1", "_e_hostname": "esxi01", "_e_raw_host": {},
           "_e_vmnic": OK_VMNIC, "_e_vmhba": OK_VMHBA, "_e_vswitch": OK_VSW, "_e_portgroup": OK_PG}
    ctx.update(mods)
    return _facts(EXT, ctx, only_block=True)


def test_extended_all_modules_ok_records_nothing():
    ctx = _ext()
    assert ctx["_errors_fragment"] == [] and len(ctx["_e_ext_hbas"]) == 1


def test_vmhba_query_failure_is_recorded_under_storage_and_other_data_stays():
    """감사 재현: vmhba NoPermission · 결과 키 없음, 다른 NIC/vSwitch 조회는 성공."""
    ctx = _ext(_e_vmhba={"failed": False, "msg": "NoPermission: Permission to perform this operation was denied."})
    assert ctx["_e_ext_hbas"] == [] and len(ctx["_e_ext_adapters"]) == 1
    errs = ctx["_errors_fragment"]
    assert errs == [{"section": "storage", "message": STOR_TEXT,
                     "detail": "scope=vmhba; cause=module_failed; msg=NoPermission: Permission to perform this operation was denied."}]
    final = _final(ctx)
    assert final["_norm_sections"]["storage"] == "success" and final["_norm_sections"]["network"] == "success"
    assert final["_out_status"] == "success" and [e["section"] for e in final["_norm_errors"]] == ["storage"]


def test_missing_result_key_is_a_failure_even_without_msg():
    ctx = _ext(_e_vmhba={"failed": False})
    assert ctx["_errors_fragment"] == [{"section": "storage", "message": STOR_TEXT, "detail": "scope=vmhba; cause=module_failed; msg=none"}]


@pytest.mark.parametrize("vmhba", [
    {"failed": False, "hosts_vmhbas_info": {}},
    {"failed": False, "hosts_vmhbas_info": {"esxi01": {"vmhba_details": []}}},
], ids=["empty_mapping", "no_hba"])
def test_valid_empty_hba_result_is_not_an_error(vmhba):
    ctx = _ext(_e_vmhba=vmhba)
    assert ctx["_errors_fragment"] == [] and ctx["_e_ext_hbas"] == []


def test_several_network_module_failures_are_one_network_entry():
    ctx = _ext(_e_vmnic={"failed": False, "msg": "vmnic query timed out\nretry later"}, _e_portgroup={"failed": False})
    errs = ctx["_errors_fragment"]
    assert errs == [{"section": "network", "message": NET_TEXT,
                     "detail": "scope=vmnic,portgroup; cause=module_failed; msg=vmnic query timed out retry later"}]


def test_long_module_message_is_cut_to_160_characters():
    ctx = _ext(_e_vswitch={"failed": False, "msg": "x" * 500})
    assert ctx["_errors_fragment"][0]["detail"] == "scope=vswitch; cause=module_failed; msg=" + "x" * 160


# ── runtime: NTP · firewall · service ───────────────────────────────────────────────────────────────────────

OK_NTP = {"failed": False, "hosts_ntp_info": {"esxi01": [{"time_zone_name": "UTC", "ntp_servers": ["10.0.0.1"]}]}}
OK_FW = {"failed": False, "hosts_firewall_info": {"esxi01": [{"enabled": True}]}}
OK_SVC = {"failed": False, "host_service_info": {"esxi01": [{"key": "ntpd", "running": True}]}}
RT_PARTIAL = "서버 기본 정보 중 운영 환경 정보 일부를 수집하지 못했습니다. 대상 상태와 수집 로그를 확인하세요."
RT_ALL = "서버 기본 정보 중 운영 환경 정보를 수집하지 못했습니다. 대상 상태와 수집 로그를 확인하세요."


def _rt(**mods):
    ctx = {"_e_hostname": "esxi01", "_e_ntp_result": OK_NTP, "_e_firewall_result": OK_FW, "_e_service_result": OK_SVC}
    ctx.update(mods)
    return _facts(RUNTIME, ctx)


def test_runtime_all_ok_records_nothing():
    ctx = _rt()
    assert ctx["_errors_fragment"] == [] and ctx["_e_runtime_timezone"] == "UTC"


def test_ntp_query_failure_is_recorded_and_other_runtime_data_stays():
    """감사 재현: NTP NoPermission, firewall/service 조회는 성공."""
    ctx = _rt(_e_ntp_result={"failed": False, "msg": "NoPermission"})
    assert ctx["_e_runtime_timezone"] is None and ctx["_e_runtime_ntp_servers"] == []
    assert ctx["_e_runtime_firewall_state"] == "active"
    assert ctx["_errors_fragment"] == [{"section": "system", "message": RT_PARTIAL, "detail": "scope=ntp; cause=module_failed; msg=NoPermission"}]
    final = _final(ctx)
    assert final["_norm_sections"]["system"] == "success" and final["_out_status"] == "success"
    assert [e["section"] for e in final["_norm_errors"]] == ["system"]


def test_ntp_not_configured_is_not_an_error():
    ctx = _rt(_e_ntp_result={"failed": False, "hosts_ntp_info": {"esxi01": []}})
    assert ctx["_errors_fragment"] == [] and ctx["_e_runtime_ntp_servers"] == []


def test_runtime_partial_failure_without_msg():
    ctx = _rt(_e_ntp_result={"failed": False}, _e_service_result={"failed": False, "msg": "service query denied"})
    assert ctx["_errors_fragment"] == [{"section": "system", "message": RT_PARTIAL,
                                        "detail": "scope=ntp,service; cause=module_failed; msg=service query denied"}]


def test_all_runtime_modules_failed_keeps_the_existing_sentence():
    ctx = _rt(_e_ntp_result={"failed": False, "msg": "NoPermission"}, _e_firewall_result={"failed": False}, _e_service_result={"failed": False})
    assert ctx["_errors_fragment"] == [{"section": "system", "message": RT_ALL,
                                        "detail": "scope=timezone,ntp,firewall; cause=all_modules_failed; msg=NoPermission"}]
