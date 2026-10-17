"""redfish Round 3 robustness/correctness 회귀.

  - _as_list / _dicts 헬퍼 (비-list/비-dict 배열 방어)
  - #0 gather_power PowerControl[0] 비-dict
  - #3 _resolve_all_member_uris 비-str @odata.id skip
  - #5 _normalize_network_raw 비-list ipv4
  - #6/#8 gather_processors/gather_memory 문자열 speed → int
  - #2 _make_ib_port 비-dict InfiniBand
"""
from __future__ import annotations

import pytest

import emulator_harness as H

rg = H.rg


def _fake_get(tree):
    def fake(bmc_ip, path, username, password, timeout, verify_ssl):
        return (200, tree[path], None) if path in tree else (404, {}, "HTTP 404: Not Found")
    return fake


# ── 헬퍼 ──
def test_as_list_and_dicts_helpers():
    assert rg._as_list([1, 2]) == [1, 2]
    assert rg._as_list("str") == [] and rg._as_list(5) == [] and rg._as_list(None) == []
    assert rg._dicts([{"a": 1}, "x", 3, {"b": 2}]) == [{"a": 1}, {"b": 2}]
    assert rg._dicts("notlist") == [] and rg._dicts({"a": 1}) == []


# ── #5 _normalize_network_raw 비-list ipv4 ──
def test_normalize_network_raw_non_list_ipv4():
    out = rg._normalize_network_raw([{"id": "nic0", "ipv4": 12345}])  # 가드 전: for a in int → TypeError
    assert isinstance(out, dict) and "interfaces" in out


# ── #0 gather_power PowerControl 비-dict 원소 ──
def test_gather_power_non_dict_powercontrol(monkeypatch):
    monkeypatch.setattr(rg, "_get", _fake_get({
        "Chassis/1/Power": {"PowerControl": ["bad_string_element"]},
    }))
    result, errs = rg.gather_power("1.2.3.4", "/redfish/v1/Chassis/1", "u", "p", 5, False)  # 가드 전: AttributeError
    assert isinstance(result, dict)  # crash 없이 반환


# ── #3 _resolve_all_member_uris 비-str @odata.id ──
def test_resolve_all_non_str_odata_id(monkeypatch):
    monkeypatch.setattr(rg, "_get", _fake_get({
        "Systems": {"Members": [{"@odata.id": 12345}, {"@odata.id": "/redfish/v1/Systems/2"}]},
    }))
    members, st, err = rg._resolve_all_member_uris("1.2.3.4", "/redfish/v1/Systems", "u", "p", 5, False)
    # 비-str 은 skip, 정상 것만 (가드 전: int.rstrip AttributeError)
    assert len(members) == 1 and members[0]["id"] == "2"


# ── #6 gather_processors MaxSpeedMHz 문자열 → int ──
def test_gather_processors_string_speed_to_int(monkeypatch):
    monkeypatch.setattr(rg, "_get", _fake_get({
        "Systems/1/Processors": {"Members": [{"@odata.id": "/redfish/v1/Systems/1/Processors/1"}]},
        "Systems/1/Processors/1": {"Id": "1", "Model": "Xeon", "MaxSpeedMHz": "2400", "OperatingSpeedMHz": "2000",
                                   "TotalCores": "10", "ProcessorType": "CPU"},
    }))
    procs, errs = rg.gather_processors("1.2.3.4", "/redfish/v1/Systems/1", "u", "p", 5, False)
    # 2026-10-18 (X2): speed_mhz 는 정격(OperatingSpeedMHz 등), MaxSpeedMHz(터보) 는 max_speed_mhz — 둘 다 숫자 문자열을 int 로
    assert procs and procs[0]["speed_mhz"] == 2000 and isinstance(procs[0]["speed_mhz"], int)
    assert procs[0]["max_speed_mhz"] == 2400 and isinstance(procs[0]["max_speed_mhz"], int)
    assert procs[0]["total_cores"] == 10


# ── #2 비-dict InfiniBand 블록 방어 (2026-10-17: GUID 선택이 _select_ib_guids 로 분리됐다 — 같은 방어를 거기서 본다) ──
def test_select_ib_guids_non_dict_infiniband():
    # pdata.InfiniBand 가 문자열 → ibobj.get crash 방어
    assert rg._select_ib_guids([], {"InfiniBand": "not_a_dict"}) == (None, None)
    entry = rg._make_ib_port("A0", {"model": "IB X"}, "1", "up", 200, None, None)
    assert isinstance(entry, dict) and entry["model"] == entry["adapter_model"] == "IB X" and entry["rate"] is None
