"""redfish_gather.py — 2026-10-03 Phase 2 정확성 계약 (C5 · C6 · C7 · C9 · S1).

무엇을 고정하나
  - C5  `_collection_members`: Members@odata.nextLink 를 opaque URL 로 따라간다. 후속 페이지 실패 · 순환 ·
        다른 origin · 페이지 상한에서 **앞 페이지 멤버를 보존**하고 비차단 code 오류/notice 를 남긴다.
        `Members@odata.count` 불일치는 notice, 부재는 조용히.
  - C5  gather_memory: 장착 DIMM 의 CapacityMiB 가 전부 없으면 total None + 오류, 일부면 total None + notice,
        slot 은 전부 보존(과소집계 금지).
  - C6  gather_firmware: Dell 형식(Installed-/Current- 접두사) 은 GET 전에 dedup → R740 실 미러에서 멤버 GET 62 → 32,
        golden firmware 목록 불변(first-seen). 다른 version 은 둘 다 보존. 선택 멤버 500 → 대체 멤버 fallback.
        둘 다 실패 → errors(비차단) + stub 미출력. Name 만 있고 Version 없는 inline 멤버는 상세 1회 조회.
  - C7  `_normalize_wwn`: all-zero 16-hex → None (filter_plugins/identity_normalizer 와 동일).
  - S1  `_compute_final_status`: 멤버 수준(비차단 code) 401/403 은 host 를 failed 로 바꾸지 않는다 — 컬렉션/앵커
        수준 401/403 은 종전대로 failed.
  - C9  `_confirm_account_state` 가 (ok, mismatches) 를 반환한다.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

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

BMC = "10.0.0.5"
CREDS = ("u", "p", 5, False)


def _fake_get(table, calls=None):
    """path → (status, data, err) 테이블 기반 _get 대역. 기록된 경로 밖은 404."""
    def get(bmc_ip, path, username, password, timeout, verify_ssl):
        if calls is not None:
            calls.append(path)
        hit = table.get(path)
        if hit is None:
            return 404, {}, "HTTP 404: Not Found"
        return hit
    return get


# ───────────────────────────── C5: nextLink ─────────────────────────────

@pytest.mark.parametrize("link,expected", [
    ("/redfish/v1/Systems/1/Memory?$skip=2", "Systems/1/Memory?$skip=2"),
    ("?$skip=2", "Systems/1/Memory?$skip=2"),
    (f"https://{BMC}/redfish/v1/Systems/1/Memory?$skip=2&$top=2", "Systems/1/Memory?$skip=2&$top=2"),
    ("https://evil.example/redfish/v1/Systems/1/Memory?$skip=2", None),   # 다른 origin → 자격증명 전달 금지
    ("/other/path", None),                                                  # service root 밖
    ("", None),
    (None, None),
])
def test_nextlink_is_resolved_as_opaque_url(link, expected):
    assert rg._nextlink_path(BMC, "Systems/1/Memory", link) == expected


def _coll(members, nxt=None, count=None):
    d = {"Members": [{"@odata.id": f"/redfish/v1/Systems/1/Memory/{m}"} for m in members]}
    if nxt:
        d["Members@odata.nextLink"] = nxt
    if count is not None:
        d["Members@odata.count"] = count
    return 200, d, None


def test_collection_members_follows_pages_and_keeps_order(monkeypatch):
    table = {
        "Systems/1/Memory?$skip=2": _coll(["c", "d"], nxt="/redfish/v1/Systems/1/Memory?$skip=4"),
        "Systems/1/Memory?$skip=4": _coll(["e"]),
    }
    calls = []
    monkeypatch.setattr(rg, "_get", _fake_get(table, calls))
    rg._reset_notices()
    first = _coll(["a", "b"], nxt="?$skip=2", count=5)[1]
    errors = []
    out = rg._collection_members(BMC, "Systems/1/Memory", first, *CREDS, "memory", errors)
    assert [m["@odata.id"].rsplit("/", 1)[-1] for m in out] == ["a", "b", "c", "d", "e"]
    assert calls == ["Systems/1/Memory?$skip=2", "Systems/1/Memory?$skip=4"]
    assert errors == [] and rg.notices() == []


def test_collection_members_without_nextlink_is_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(rg, "_get", _fake_get({}, calls))
    rg._reset_notices()
    first = _coll(["a", "b"])[1]
    out = rg._collection_members(BMC, "Systems/1/Memory", first, *CREDS, "memory", [])
    assert len(out) == 2 and calls == [] and rg.notices() == []


def test_later_page_failure_keeps_first_page_and_reports_non_blocking(monkeypatch):
    table = {"Systems/1/Memory?$skip=2": (500, {}, "HTTP 500: Internal Server Error")}
    monkeypatch.setattr(rg, "_get", _fake_get(table))
    errors = []
    out = rg._collection_members(BMC, "Systems/1/Memory", _coll(["a", "b"], nxt="?$skip=2")[1], *CREDS, "memory", errors)
    assert len(out) == 2, "앞 페이지 멤버 보존"
    assert len(errors) == 1 and errors[0]["code"] == rg._CODE_NON_BLOCKING_SUBRESOURCE
    assert "다음 페이지 실패" in errors[0]["message"]
    # 섹션 오류지만 host 판정은 뒤집지 않는다 (S1) — 다른 섹션이 깨끗하면 partial
    assert rg._compute_final_status(["system", "memory"], ["memory"], errors)[0] == "partial"


def test_cycle_and_foreign_origin_stop_without_requests(monkeypatch):
    calls = []
    table = {"Systems/1/Memory?$skip=2": _coll(["c"], nxt="/redfish/v1/Systems/1/Memory?$skip=2")}
    monkeypatch.setattr(rg, "_get", _fake_get(table, calls))
    errors = []
    out = rg._collection_members(BMC, "Systems/1/Memory", _coll(["a"], nxt="?$skip=2")[1], *CREDS, "memory", errors)
    assert [m["@odata.id"].rsplit("/", 1)[-1] for m in out] == ["a", "c"]
    assert calls == ["Systems/1/Memory?$skip=2"], "순환 링크는 다시 요청하지 않는다"
    assert any("순환" in e["message"] for e in errors)

    calls.clear()
    errors = []
    first = _coll(["a"], nxt="https://evil.example/redfish/v1/Systems/1/Memory?$skip=1")[1]
    out = rg._collection_members(BMC, "Systems/1/Memory", first, *CREDS, "memory", errors)
    assert len(out) == 1 and calls == []
    assert any("따라갈 수 없음" in e["message"] for e in errors)


def test_count_mismatch_is_a_notice_and_absence_is_silent(monkeypatch):
    monkeypatch.setattr(rg, "_get", _fake_get({}))
    rg._reset_notices()
    rg._collection_members(BMC, "Systems/1/Memory", _coll(["a", "b"], count=3)[1], *CREDS, "memory", [])
    assert any("Members@odata.count 3 != 수집 2" in n["message"] for n in rg.notices())
    rg._reset_notices()
    rg._collection_members(BMC, "Systems/1/Memory", _coll(["a", "b"])[1], *CREDS, "memory", [])
    assert rg.notices() == []


def test_errors_none_callers_fall_back_to_notices(monkeypatch):
    monkeypatch.setattr(rg, "_get", _fake_get({"Chassis/1/Sensors?$skip=1": (503, {}, "HTTP 503")}))
    rg._reset_notices()
    first = {"Members": [{"@odata.id": "/redfish/v1/Chassis/1/Sensors/fan1"}],
             "Members@odata.nextLink": "/redfish/v1/Chassis/1/Sensors?$skip=1"}
    out = rg._collection_members(BMC, "Chassis/1/Sensors", first, *CREDS, "thermal", None)
    assert len(out) == 1 and any("다음 페이지 실패" in n["message"] for n in rg.notices())


# ───────────────────────────── C5: memory capacity unknown ─────────────────────────────

def _dimm(id_, cap):
    d = {"Id": id_, "Status": {"State": "Enabled"}, "MemoryDeviceType": "DDR5"}
    if cap is not None:
        d["CapacityMiB"] = cap
    return 200, d, None


def test_memory_all_capacity_unknown_gives_none_total_and_error(monkeypatch):
    table = {
        "Systems/1/Memory": _coll(["DIMM1", "DIMM2"]),
        "Systems/1/Memory/DIMM1": _dimm("DIMM1", None),
        "Systems/1/Memory/DIMM2": _dimm("DIMM2", None),
    }
    monkeypatch.setattr(rg, "_get", _fake_get(table))
    rg._reset_notices()
    out, errors = rg.gather_memory(BMC, "/redfish/v1/Systems/1", *CREDS)
    assert out["total_mib"] is None and len(out["slots"]) == 2
    assert [s["capacity_mb"] for s in out["slots"]] == [None, None]
    assert len(errors) == 1 and errors[0]["code"] == rg._CODE_NON_BLOCKING_SUBRESOURCE


def test_memory_partial_capacity_unknown_gives_none_total_and_notice(monkeypatch):
    table = {
        "Systems/1/Memory": _coll(["DIMM1", "DIMM2"]),
        "Systems/1/Memory/DIMM1": _dimm("DIMM1", 16384),
        "Systems/1/Memory/DIMM2": _dimm("DIMM2", None),
    }
    monkeypatch.setattr(rg, "_get", _fake_get(table))
    rg._reset_notices()
    out, errors = rg.gather_memory(BMC, "/redfish/v1/Systems/1", *CREDS)
    assert out["total_mib"] is None, "부재 DIMM 을 빼고 더한 값을 합계로 내지 않는다"
    assert [s["capacity_mb"] for s in out["slots"]] == [16384, None]
    assert errors == [] and any("CapacityMiB 부재 DIMM 1/2" in n["message"] for n in rg.notices())


def test_memory_all_known_unchanged(monkeypatch):
    table = {
        "Systems/1/Memory": _coll(["DIMM1", "DIMM2"]),
        "Systems/1/Memory/DIMM1": _dimm("DIMM1", 16384),
        "Systems/1/Memory/DIMM2": _dimm("DIMM2", 16384),
    }
    monkeypatch.setattr(rg, "_get", _fake_get(table))
    rg._reset_notices()
    out, errors = rg.gather_memory(BMC, "/redfish/v1/Systems/1", *CREDS)
    assert out["total_mib"] == 32768 and errors == [] and rg.notices() == []


def test_partition_memory_falls_back_to_its_own_system_summary_only():
    raw_mem = {"total_mib": None, "slots": []}
    own = {"memory_summary": {"total_gib": 512}}
    assert rg._normalize_memory_raw(raw_mem, own)["total_mb"] == 512 * 1024
    assert rg._normalize_memory_raw(raw_mem, None)["total_mb"] is None
    assert rg._normalize_memory_raw({"total_mib": 1024, "slots": []}, own)["total_mb"] == 1024


# ───────────────────────────── C6: firmware ─────────────────────────────

R740 = REPO / "tests" / "fixtures" / "redfish" / "real_dell_r740"


@pytest.mark.skipif(not (R740 / "recording.json").is_file(), reason="real_dell_r740 fixture 없음")
def test_firmware_dell_dedup_before_get_halves_member_gets_and_keeps_golden(monkeypatch):
    rec = json.loads((R740 / "recording.json").read_text(encoding="utf-8"))
    golden = json.loads((R740 / "expected_output.json").read_text(encoding="utf-8"))["data"]["firmware"]
    table = {k[len("get::"):]: tuple(v) for k, v in rec.items() if k.startswith("get::")}
    calls = []
    monkeypatch.setattr(rg, "_get", _fake_get(table, calls))
    fw, errors = rg.gather_firmware(BMC, *CREDS)
    member_gets = [c for c in calls if c.startswith("UpdateService/FirmwareInventory/")]
    assert len(member_gets) == 32, f"R740: 멤버 GET 62 → 32 (19 Installed/Current 쌍 + Previous 11 제외), 실제 {len(member_gets)}"
    assert errors == []
    norm = lambda rows: json.loads(json.dumps(rows, sort_keys=True))  # noqa: E731
    assert norm(fw) == norm(golden), "first-seen 규칙이라 golden firmware 목록(id 포함)이 그대로다"


def _fw_coll(ids):
    return 200, {"Members": [{"@odata.id": f"/redfish/v1/UpdateService/FirmwareInventory/{i}"} for i in ids]}, None


def _fw(id_, version, name="X"):
    return 200, {"Id": id_, "Name": name, "Version": version, "SoftwareId": id_.split("-")[1] if "-" in id_ else id_}, None


def test_firmware_different_versions_are_both_kept(monkeypatch):
    table = {
        "UpdateService/FirmwareInventory": _fw_coll(["Installed-100-1.0__NIC.1", "Current-100-2.0__NIC.1"]),
        "UpdateService/FirmwareInventory/Installed-100-1.0__NIC.1": _fw("Installed-100-1.0__NIC.1", "1.0"),
        "UpdateService/FirmwareInventory/Current-100-2.0__NIC.1": _fw("Current-100-2.0__NIC.1", "2.0"),
    }
    monkeypatch.setattr(rg, "_get", _fake_get(table))
    fw, errors = rg.gather_firmware(BMC, *CREDS)
    assert [f["version"] for f in fw] == ["1.0", "2.0"] and errors == []


def test_firmware_alternate_member_fallback_and_no_stub_on_total_failure(monkeypatch):
    calls = []
    table = {
        "UpdateService/FirmwareInventory": _fw_coll(["Current-100-1.0__A", "Installed-100-1.0__A", "Installed-200-3.0__B"]),
        "UpdateService/FirmwareInventory/Current-100-1.0__A": (500, {}, "HTTP 500: Internal Server Error"),
        "UpdateService/FirmwareInventory/Installed-100-1.0__A": _fw("Installed-100-1.0__A", "1.0", "A"),
        "UpdateService/FirmwareInventory/Installed-200-3.0__B": (500, {}, "HTTP 500: Internal Server Error"),
    }
    monkeypatch.setattr(rg, "_get", _fake_get(table, calls))
    fw, errors = rg.gather_firmware(BMC, *CREDS)
    assert [f["id"] for f in fw] == ["Installed-100-1.0__A"], "같은 key 의 대체 멤버로 복구, 실패 key 는 stub 없이 제외"
    assert len(errors) == 1 and errors[0]["code"] == rg._CODE_NON_BLOCKING_SUBRESOURCE
    assert "Installed-200-3.0__B" in errors[0]["message"]
    assert rg._compute_final_status(["system", "firmware"], ["firmware"], errors)[0] == "partial"


def test_firmware_name_only_inline_member_fetches_detail_once(monkeypatch):
    calls = []
    table = {
        "UpdateService/FirmwareInventory": (200, {"Members": [
            {"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/1", "Id": "1", "Name": "BMC"},
            {"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/2", "Id": "2", "Name": "BIOS", "Version": "U30 v2.0"},
        ]}, None),
        "UpdateService/FirmwareInventory/1": _fw("1", "2.70", "BMC"),
    }
    monkeypatch.setattr(rg, "_get", _fake_get(table, calls))
    fw, errors = rg.gather_firmware(BMC, *CREDS)
    assert calls.count("UpdateService/FirmwareInventory/1") == 1, "Version 없는 inline 멤버만 상세 1회"
    assert "UpdateService/FirmwareInventory/2" not in calls
    assert {f["id"]: f["version"] for f in fw} == {"1": "2.70", "2": "U30 v2.0"} and errors == []


def test_firmware_previous_members_are_not_fetched(monkeypatch):
    calls = []
    table = {
        "UpdateService/FirmwareInventory": _fw_coll(["Previous-100-0.9__A", "Installed-100-1.0__A"]),
        "UpdateService/FirmwareInventory/Installed-100-1.0__A": _fw("Installed-100-1.0__A", "1.0"),
    }
    monkeypatch.setattr(rg, "_get", _fake_get(table, calls))
    fw, _ = rg.gather_firmware(BMC, *CREDS)
    assert "UpdateService/FirmwareInventory/Previous-100-0.9__A" not in calls
    assert [f["id"] for f in fw] == ["Installed-100-1.0__A"]


# ───────────────────────────── C7: WWN ─────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("0000000000000000", None),
    ("00:00:00:00:00:00:00:00", None),
    ("0x2000002724ABCDEF", "20:00:00:27:24:ab:cd:ef"),
    ("20:00:00:27:e3:6c:a6:6e", "20:00:00:27:e3:6c:a6:6e"),
    (None, None),
])
def test_normalize_wwn_all_zero_is_none(raw, expected):
    assert rg._normalize_wwn(raw) == expected


# ───────────────────────────── S1: final status ─────────────────────────────

def test_member_level_403_does_not_force_host_failed():
    errs = [rg._err("network_adapters", "NetworkDeviceFunction /x 실패: HTTP 403: Forbidden",
                    code=rg._CODE_NON_BLOCKING_SUBRESOURCE)]
    assert rg._compute_final_status(["system", "network_adapters"], ["network_adapters"], errs)[0] == "partial"


def test_collection_level_401_still_forces_failed():
    errs = [rg._err("memory", "Memory 컬렉션 실패: HTTP 401: Unauthorized")]
    assert rg._compute_final_status(["system", "memory"], ["memory"], errs)[0] == "failed"


# ───────────────────────────── C9: confirm account state ─────────────────────────────

def _family():
    return {"account_types_required": ["Redfish"]}


def test_confirm_account_state_returns_ok_and_mismatches(monkeypatch):
    out = {"errors": []}
    good = (200, {"UserName": "infraops", "Enabled": True, "RoleId": "Administrator",
                  "AccountTypes": ["Redfish", "WebUI"], "PasswordChangeRequired": False}, None)
    monkeypatch.setattr(rg, "_get", _fake_get({"AccountService/Accounts/3": good}))
    ok, mm = rg._confirm_account_state(BMC, "/redfish/v1/AccountService/Accounts/3", "infraops", _family(), *CREDS, out)
    assert ok is True and mm == [] and out["errors"] == []

    out = {"errors": []}
    bad = (200, {"UserName": "infraops", "Enabled": False, "AccountTypes": ["WebUI"], "PasswordChangeRequired": True}, None)
    monkeypatch.setattr(rg, "_get", _fake_get({"AccountService/Accounts/3": bad}))
    ok, mm = rg._confirm_account_state(BMC, "/redfish/v1/AccountService/Accounts/3", "infraops", _family(), *CREDS, out)
    assert ok is False and {"Enabled=false", "PasswordChangeRequired=true"} <= set(mm)
    assert any(m.startswith("AccountTypes=") for m in mm) and len(out["errors"]) == 1

    out = {"errors": []}
    monkeypatch.setattr(rg, "_get", _fake_get({}))
    ok, mm = rg._confirm_account_state(BMC, "/redfish/v1/AccountService/Accounts/3", "infraops", _family(), *CREDS, out)
    assert ok is None and mm == [] and len(out["errors"]) == 1, "다시 읽지 못하면 판정 보류(None) + 오류 1건"
    assert rg._confirm_account_state(BMC, None, "infraops", _family(), *CREDS, {"errors": []}) == (None, [])


def test_recovery_sites_gate_on_state(monkeypatch):
    """4 호출부 모두 (ok, mismatches) 를 받아 state_ok is not False 로 recovered 를 묶는다 (텍스트 계약)."""
    src = (REPO / "redfish-gather" / "library" / "redfish_gather.py").read_text(encoding="utf-8")
    assert src.count("_confirm_account_state(") == 5, "정의 1 + 호출 4"
    assert src.count("state_ok is not False") + src.count("state_ok_r is not False") == 4
    assert src.count("'state_mismatch'") >= 3
