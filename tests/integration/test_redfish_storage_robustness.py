"""redfish storage 경로 fault-injection 회귀 (Round 1 #0/#1/#2/#10/11/20/#24/#25).

배경: storage 수집 경로의 crash/correctness 결함을 다수 확인:
  - #0 _extract_storage_controller_info: 비-list StorageControllers[0] crash
  - #1 _extract_storage_volumes: 비-str Links.Drives @odata.id .rstrip crash
  - #2 _normalize_storage_raw: 비-dict controller/drive .get crash
  - #10/11/20 _gather_smart_storage(iLO4): CapacityMiB 를 capacity_gb 에 그대로 넣어 ~1000x 오류
  - #24 _resolve_first_member_uri / #25 account_service_get: 비-list Members 처리
"""
from __future__ import annotations

import pytest

import emulator_harness as H

rg = H.rg


# ── #2 _normalize_storage_raw (순수 함수) — 비-dict controller/drive 방어 ──
class TestNormalizeStorageRaw:
    def test_non_dict_controller_skipped(self):
        out = rg._normalize_storage_raw({"controllers": [None, "junk", {"drives": []}]})  # 가드 전: AttributeError
        assert isinstance(out, dict) and "controllers" in out

    def test_non_dict_drive_skipped(self):
        out = rg._normalize_storage_raw({"controllers": [
            {"drives": [None, {"name": "d0", "capacity_bytes": 1073741824}]}]})
        assert isinstance(out, dict)
        # 유효 드라이브는 보존 (None 만 skip)
        phys = out.get("physical_disks") or []
        assert any(d.get("device") == "d0" for d in phys)

    def test_zero_capacity_preserved_as_zero(self):
        """capacity_bytes=0 (known-zero) → total_mb=0 (None 으로 소실 안 됨) — Round 1 #15."""
        out = rg._normalize_storage_raw({"controllers": [
            {"drives": [{"name": "z0", "capacity_bytes": 0}]}]})
        phys = out.get("physical_disks") or []
        assert phys and phys[0]["total_mb"] == 0


# ── monkeypatch _get 기반 (오프라인) ──
def _fake_get_from_tree(tree):
    def fake(bmc_ip, path, username, password, timeout, verify_ssl):
        if path in tree:
            return 200, tree[path], None
        return 404, {}, "HTTP 404: Not Found"
    return fake


# ── #24 _resolve_first_member_uri — 비-list Members ──
class TestResolveFirstMember:
    def test_members_as_dict_does_not_crash(self, monkeypatch):
        monkeypatch.setattr(rg, "_get", _fake_get_from_tree({
            "Managers": {"Members": {"not": "a list"}},  # BMC가 dict로 응답
        }))
        uri, st, err = rg._resolve_first_member_uri("1.2.3.4", "/redfish/v1/Managers", "u", "p", 5, False)  # 가드 전: TypeError
        assert uri is None and err  # graceful

    def test_members_list_unchanged(self, monkeypatch):
        monkeypatch.setattr(rg, "_get", _fake_get_from_tree({
            "Managers": {"Members": [{"@odata.id": "/redfish/v1/Managers/1"}]},
        }))
        uri, st, err = rg._resolve_first_member_uri("1.2.3.4", "/redfish/v1/Managers", "u", "p", 5, False)
        assert uri == "/redfish/v1/Managers/1" and err is None


# ── #25 account_service_get — 비-list Members ──
def test_account_service_members_as_dict_graceful(monkeypatch):
    monkeypatch.setattr(rg, "_get", _fake_get_from_tree({
        "AccountService": {"Accounts": {"@odata.id": "/redfish/v1/AccountService/Accounts"}},
        "AccountService/Accounts": {"Members": {"bad": "dict"}},
    }))
    root, accounts, errors = rg.account_service_get("1.2.3.4", "u", "p", 5, False)
    assert accounts == []  # 비-list → 빈 계정 (crash 아님)


# ── #10/11/20 _gather_smart_storage iLO4 CapacityMiB 단위 ──
def test_smart_storage_capacity_mib_unit_correct(monkeypatch):
    """CapacityMiB 만 있는 iLO4 드라이브 → capacity_gb 가 ~1000x 부풀지 않음."""
    sys_uri = "/redfish/v1/Systems/1"
    tree = {
        "Systems/1/SmartStorage": {"ArrayControllers": {"@odata.id": "/redfish/v1/Systems/1/SmartStorage/ArrayControllers"}},
        "Systems/1/SmartStorage/ArrayControllers": {"Members": [{"@odata.id": "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/0"}]},
        "Systems/1/SmartStorage/ArrayControllers/0": {"Id": "0", "Model": "Smart Array P440",
            "PhysicalDrives": {"@odata.id": "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/0/PhysicalDrives"}},
        "Systems/1/SmartStorage/ArrayControllers/0/PhysicalDrives": {"Members": [{"@odata.id": "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/0/PhysicalDrives/0"}]},
        # 1 TiB drive expressed ONLY as CapacityMiB (no CapacityGB) — iLO4 quirk
        "Systems/1/SmartStorage/ArrayControllers/0/PhysicalDrives/0": {"Id": "0", "Model": "MM1000GBKAL",
            "CapacityMiB": 1048576, "MediaType": "HDD", "InterfaceType": "SAS"},
    }
    monkeypatch.setattr(rg, "_get", _fake_get_from_tree(tree))
    controllers, _hbas, errors = rg._gather_smart_storage("1.2.3.4", sys_uri, "u", "p", 5, False)
    drives = (controllers or [{}])[0].get("drives") or []
    assert drives, "physical drive 미파싱"
    cap_gb = drives[0]["capacity_gb"]
    # 1048576 MiB = 1099.51 GB (십진). 가드 전 버그값(1048576)이면 안 됨.
    assert 1000 < cap_gb < 1200, f"capacity_gb 단위 오류: {cap_gb} (MiB를 GB로 오인)"
    assert drives[0]["capacity_bytes"] == 1048576 * 1048576


# ── #0 _extract_storage_controller_info — 비-list StorageControllers ──
def test_controller_info_non_list_storagecontrollers_does_not_crash():
    """StorageControllers 가 dict(비-list) → inline_ctrls[0] crash 방어."""
    out, errors = rg._extract_storage_controller_info(
        {"StorageControllers": {"bad": "dict"}}, "1.2.3.4", "u", "p", 5, False)  # 가드 전: KeyError
    assert isinstance(out, dict)


# ── #1 _extract_storage_volumes — Links.Drives 비-str @odata.id ──
def test_volumes_corrupt_drive_odata_id_does_not_crash(monkeypatch):
    """Links.Drives[].@odata.id 가 비-str(dict) → .rstrip AttributeError 방어."""
    tree = {
        "C/Volumes": {"Members": [{"@odata.id": "/redfish/v1/C/Volumes/1"}]},
        "C/Volumes/1": {"Id": "V1", "CapacityBytes": 1099511627776,
                        "Links": {"Drives": [{"@odata.id": {"corrupt": True}},
                                             {"@odata.id": "/redfish/v1/C/Drives/0"}]}},
    }
    monkeypatch.setattr(rg, "_get", _fake_get_from_tree(tree))
    vols, errs = rg._extract_storage_volumes(
        {"Volumes": {"@odata.id": "/redfish/v1/C/Volumes"}}, "ctrl0", "1.2.3.4", "u", "p", 5, False)  # 가드 전: AttributeError
    assert isinstance(vols, list) and vols
    # 오염 @odata.id 는 skip, 정상 것만 남음
    assert vols[0]["member_drive_ids"] == ["0"]
