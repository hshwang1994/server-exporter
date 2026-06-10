"""redfish Round 16 robustness/correctness 회귀.

  - gather_power: PowerControl 자체가 비-list 컨테이너(dict/int)일 때 crash 없이
    PSU 보존 (Round 3 #0 은 list-with-bad-element 만 커버, 컨테이너 타입은 미커버).
  - 멀티노드 멤버 순회(_capped) DoS 상한 적용 — managers/partitions/chassis.
"""
from __future__ import annotations

import emulator_harness as H

rg = H.rg


def _fake_get(tree):
    def fake(bmc_ip, path, username, password, timeout, verify_ssl):
        return (200, tree[path], None) if path in tree else (404, {}, "HTTP 404: Not Found")
    return fake


# ── gather_power: PowerControl 비-list 컨테이너 방어 ──
def test_gather_power_powercontrol_as_dict(monkeypatch):
    # 표준은 array 지만 오염/비-표준 펌웨어가 단일 dict 반환 → 가드 전 pc_list[0] KeyError(0).
    monkeypatch.setattr(rg, "_get", _fake_get({
        "Chassis/1/Power": {
            "PowerSupplies": [{"Name": "PS1", "PowerCapacityWatts": 750}],
            "PowerControl": {"PowerConsumedWatts": 200},  # 비-list (dict)
        },
    }))
    result, errs = rg.gather_power("1.2.3.4", "/redfish/v1/Chassis/1", "u", "p", 5, False)
    assert isinstance(result, dict)
    # 이미 수집한 PSU 는 섹션 유실 없이 보존
    assert len(result.get("power_supplies", [])) == 1
    assert result["power_supplies"][0]["power_capacity_w"] == 750
    # 비-list PowerControl 은 안전하게 무시
    assert result.get("power_control") is None


def test_gather_power_powercontrol_as_int(monkeypatch):
    # int 오염 → 가드 전 pc_list[0] TypeError('int' object is not subscriptable).
    monkeypatch.setattr(rg, "_get", _fake_get({
        "Chassis/1/Power": {
            "PowerSupplies": [{"Name": "PS1", "PowerCapacityWatts": 500}],
            "PowerControl": 12345,  # 비-list (int)
        },
    }))
    result, errs = rg.gather_power("1.2.3.4", "/redfish/v1/Chassis/1", "u", "p", 5, False)
    assert isinstance(result, dict)
    assert len(result.get("power_supplies", [])) == 1


def test_gather_power_powercontrol_normal_list_unchanged(monkeypatch):
    # 정상 list-of-dict 동작 불변 (회귀 방어).
    monkeypatch.setattr(rg, "_get", _fake_get({
        "Chassis/1/Power": {
            "PowerSupplies": [{"Name": "PS1", "PowerCapacityWatts": 750}],
            "PowerControl": [{"PowerConsumedWatts": 210, "PowerCapacityWatts": 1500}],
        },
    }))
    result, errs = rg.gather_power("1.2.3.4", "/redfish/v1/Chassis/1", "u", "p", 5, False)
    assert result["power_control"]["power_consumed_watts"] == 210
    assert result["power_control"]["power_capacity_watts"] == 1500


# ── 멀티노드 멤버 순회 _capped DoS 상한 ──
def _members(n):
    return [{"id": str(i), "uri": "/redfish/v1/X/%d" % i} for i in range(1, n + 1)]


def test_gather_systems_multi_capped(monkeypatch):
    monkeypatch.setattr(rg, "MAX_COLLECTION_MEMBERS", 2)
    monkeypatch.setattr(rg, "_resolve_all_member_uris",
                        lambda *a, **k: (_members(3), 200, None))
    monkeypatch.setattr(rg, "_get", _fake_get({}))  # 모든 GET 404 → 섹션 graceful empty
    out = rg.gather_systems_multi("1.2.3.4", "/redfish/v1/Systems", "dell", "u", "p", 5, False)
    assert len(out["partitions"]) == 2  # 상한 절단
    assert any("상한" in (e.get("message") or "") for e in out["errors"])


def test_gather_chassis_multi_capped(monkeypatch):
    monkeypatch.setattr(rg, "MAX_COLLECTION_MEMBERS", 2)
    monkeypatch.setattr(rg, "_resolve_all_member_uris",
                        lambda *a, **k: (_members(5), 200, None))
    monkeypatch.setattr(rg, "_get", _fake_get({}))
    out = rg.gather_chassis_multi("1.2.3.4", "/redfish/v1/Chassis", "u", "p", 5, False)
    assert len(out["chassis"]) == 2
    assert any("상한" in (e.get("message") or "") for e in out["errors"])


def test_gather_managers_multi_capped(monkeypatch):
    monkeypatch.setattr(rg, "MAX_COLLECTION_MEMBERS", 2)
    monkeypatch.setattr(rg, "_resolve_all_member_uris",
                        lambda *a, **k: (_members(4), 200, None))
    monkeypatch.setattr(rg, "_get", _fake_get({}))
    out = rg.gather_managers_multi("1.2.3.4", "/redfish/v1/Managers", "hpe", "u", "p", 5, False,
                                   manager_layout="rmc_primary")
    assert len(out["managers"]) == 2
    assert any("상한" in (e.get("message") or "") for e in out["errors"])
