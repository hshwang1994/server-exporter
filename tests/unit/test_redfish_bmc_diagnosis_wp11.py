"""bmc · diagnosis · users (2026-10-27, 2차 Mock C11 — 06-bmc-001/002/003/005/006/010 · FIX 10):
  06-bmc-001 Lenovo 계정 Family 는 Manager.Model(장비 값)이 세대 근거 1순위 — hint(1차 adapter_id)는 마지막.
  06-bmc-002 장비가 `@Redfish.WriteableProperties` 로 선언한 속성 밖은 repair PATCH 에 싣지 않는다(실측 HPE RMC ["Password"]).
  06-bmc-003 iLO 7 `bmc.timezone` ← Oem.Hpe.Links.DateTimeService(TimeZone.Value, +1 GET — TimeZoneName 없을 때만).
  06-bmc-005 BMC NIC 선택: 대상 IP 일치 → 비-HostInterface·활성 → 첫 NIC(종전). 06-bmc-006 bmc.name 은 ManagerType(RackManager·EnclosureManager) 폴백.
  06-bmc-010 익명 수집 성공은 auth_success null(site.yml 배선). FIX 10 data.users 는 Redfish 에서 [] · not_supported 그대로.
실측 fixture 재생 + 합성 변형 + 참조 미러(XCC `Lenovo XClarity Controller`, 10_50_11_232). 기대값은 손으로 적었다. 복구 경로 실장비 검증은 MOCK_LIMITATION.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))
sys.path.insert(0, str(REPO / "tests" / "integration"))

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
import emulator_harness as H  # noqa: E402
import account_replay as ar  # noqa: E402
from tests.unit.account_seam import as_discovery  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "redfish"
NORM = REPO / "redfish-gather" / "tasks" / "normalize_standard.yml"
SITE = REPO / "redfish-gather" / "site.yml"
LENOVO_REF = REPO / "tests" / "reference" / "redfish" / "lenovo" / "10_50_11_232"
TARGET = "infraops"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)
    monkeypatch.setattr(rg, "_get_response_etag", lambda *a, **k: None)


def _replay(name, mutate=None, ip="127.0.0.1", layout="meta"):
    case = FIX / name
    rec = json.loads((case / "recording.json").read_text(encoding="utf-8"))
    if mutate:
        mutate(rec)
    meta = json.loads((case / "meta.json").read_text(encoding="utf-8")) if (case / "meta.json").is_file() else {}
    g, n, r = H.make_replayer(rec)
    calls = []

    def gw(b, p, u, pw, t, v):
        calls.append(p)
        return g(b, p, u, pw, t, v)
    res = H.run_gather(gw, n, realm_impl=r, ip=ip, manager_layout=(meta.get("manager_layout") if layout == "meta" else layout),
                       firmware_scope=meta.get("firmware_inventory_scope"))
    return res, calls, [x["message"] for x in rg.notices()]


def _disc(accounts=None, manager=None):
    return {"service_uri": "AccountService", "accounts_uri": "AccountService/Accounts", "roles_uri": "AccountService/Roles",
            "service": {}, "policy": rg._account_policy_of(None), "role_ids": ["Administrator"], "accounts": list(accounts or []),
            "member_total": len(accounts or []), "member_read": len(accounts or []), "enumeration": rg.ENUM_COMPLETE,
            "manager": manager, "errors": [], "auth_status": 200, "service_root": None}


def _xcc_accounts(n=2):
    return [{"slot_uri": f"/redfish/v1/AccountService/Accounts/{i}", "id": str(i), "username": f"u{i}", "role_id": "Administrator",
             "enabled": True, "locked": False, "account_types": ["Redfish"], "password_change_required": None, "odata_type": "",
             "has_username_key": True, "host_bootstrap": None, "login_interfaces": None, "writable": None} for i in range(1, n + 1)]


# ── 06-bmc-001: Lenovo family — Manager.Model 우선 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model, hint, expected", [
    ("Lenovo XClarity Controller 3", "redfish_lenovo_bmc", "lenovo_xcc3_accounttypes"),      # 2차 5대 실측 모델 · 무인증 facts 가 채워져 lenovo_bmc 로 강등된 hint
    ("Lenovo Xclarity Controller 3", "redfish_lenovo_xcc", "lenovo_xcc3_accounttypes"),      # 1차 표기
    ("Lenovo XClarity Controller", "redfish_lenovo_xcc3", "lenovo_xcc2_accounttypes"),       # 참조 미러(XCC, AFBT58B 5.70) — hint 가 xcc3 라도 장비 값이 이긴다
    ("Lenovo XClarity Controller", "redfish_lenovo_xcc", "lenovo_xcc2_accounttypes"),
    (None, "redfish_lenovo_xcc3", "lenovo_xcc3_accounttypes"),                                # 모델 없음 → hint 가 세대를 말한다(종전)
    (None, "redfish_lenovo_xcc", "lenovo_xcc2_accounttypes"),
])
def test_lenovo_family_generation_comes_from_manager_model_not_adapter_hint(model, hint, expected):
    manager = {"firmware_version": "IHX414J 1.22", "model": model, "manager_type": "BMC"} if model else None
    fam, reasons = rg.resolve_account_family("lenovo", _disc(_xcc_accounts(), manager=manager), hint)
    assert fam["id"] == expected
    assert any("Manager.Model" in r for r in reasons)


def test_lenovo_family_is_deterministic_and_reasons_mention_hint_as_reference():
    manager = {"firmware_version": "IHX414J 1.22", "model": "Lenovo XClarity Controller 3", "manager_type": "BMC"}
    a = rg.resolve_account_family("lenovo", _disc(_xcc_accounts(), manager=manager), "redfish_lenovo_bmc")
    b = rg.resolve_account_family("lenovo", _disc(_xcc_accounts(), manager=manager), "redfish_lenovo_bmc")
    assert a[0]["id"] == b[0]["id"] == "lenovo_xcc3_accounttypes" and "참고" in " ".join(a[1])


def test_lenovo_reference_mirror_xcc_is_xcc2_family_even_with_xcc3_hint(monkeypatch):
    """실측 XCC(1/2) 미러 — Manager.Model 'Lenovo XClarity Controller'(숫자 없음) → PasswordChangeRequired 를 명시하는 XCC2 계약."""
    table = ar.load_mirror(LENOVO_REF)
    monkeypatch.setattr(rg, "_get", ar.make_get(table))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False, manager_uri="/redfish/v1/Managers/1")
    assert d["manager"]["model"] == "Lenovo XClarity Controller"
    fam, reasons = rg.resolve_account_family("lenovo", d, "redfish_lenovo_xcc3")
    assert fam["id"] == "lenovo_xcc2_accounttypes", reasons
    fam3, _ = rg.resolve_account_family("lenovo", dict(d, manager=dict(d["manager"], model="Lenovo XClarity Controller 3")), "redfish_lenovo_bmc")
    assert fam3["id"] == "lenovo_xcc3_accounttypes"


# ── 06-bmc-002: @Redfish.WriteableProperties ─────────────────────────────────────────────────────────────────────────

def test_discovery_keeps_device_declared_writable_list(monkeypatch):
    """실측 HPE RMC 계정 본문 모양(`@Redfish.WriteableProperties ["Password"]` · Enabled true · Locked false · AccountTypes [Redfish]) — 값은 합성."""
    svc = {"@odata.id": "/redfish/v1/AccountService", "Accounts": {"@odata.id": "/redfish/v1/AccountService/Accounts"},
           "@Redfish.WriteableProperties": ["AccountLockoutDuration", "MinPasswordLength"]}
    acct = {"@odata.id": "/redfish/v1/AccountService/Accounts/infraops", "Id": "infraops", "UserName": TARGET, "RoleId": "Administrator",
            "Enabled": True, "Locked": False, "AccountTypes": ["Redfish"], "@Redfish.WriteableProperties": ["Password"]}
    table = {"": (200, {"AccountService": {"@odata.id": "/redfish/v1/AccountService"}}), "AccountService": (200, svc),
             "AccountService/Accounts": (200, {"Members": [{"@odata.id": acct["@odata.id"]}], "Members@odata.count": 1}),
             "AccountService/Accounts/infraops": (200, acct)}
    monkeypatch.setattr(rg, "_get", ar.make_get(table))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)
    assert d["enumeration"] == rg.ENUM_COMPLETE and d["accounts"][0]["writable"] == ["Password"]
    assert d["accounts"][0]["enabled"] is True and d["accounts"][0]["locked"] is False


def _existing(**kw):
    base = {"slot_uri": "/redfish/v1/AccountService/Accounts/infraops", "id": "infraops", "username": TARGET, "role_id": "ReadOnly",
            "enabled": True, "locked": None, "account_types": None, "password_change_required": None, "odata_type": "",
            "has_username_key": True, "host_bootstrap": None, "login_interfaces": None, "writable": None}
    base.update(kw)
    return base


@pytest.mark.parametrize("writable, expected_keys, demoted", [
    (["Password"], {"Password"}, ["RoleId"]),            # RMC 실측 선언 — RoleId drift 가 있어도 Password 만
    (["Password", "RoleId"], {"Password", "RoleId"}, None),
    (None, {"Password", "RoleId"}, None),                 # 선언 없음(iLO · XCC · iDRAC) → 종전
    ([], {"Password", "RoleId"}, None),                   # 빈 선언은 '선언 없음' 으로 본다
])
def test_repair_patch_drops_properties_outside_device_declared_writable(monkeypatch, writable, expected_keys, demoted):
    patches = []

    def fake_patch(bmc_ip, path, b, u, p, t, v, extra_headers=None):
        patches.append(dict(b))
        return 200, {}, None

    def fake_discover(*a, **k):
        return _disc([_existing(writable=writable)], manager={"firmware_version": "1.75.108", "model": "RMC", "manager_type": "RackManager"})
    monkeypatch.setattr(rg, "account_service_discover", fake_discover)
    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", lambda bmc_ip, path, *a, **k: (200, {"UserName": TARGET, "RoleId": "ReadOnly", "Enabled": True}, None))
    out = rg.account_service_provision("10.0.0.1", "hpe", "rec", "<rec>", TARGET, "<tgt>", "Administrator", 5, False,
                                       dryrun=False, adapter_id="redfish_hpe_csus_3200")
    assert out["family"] == "hpe_rmc" and len(patches) >= 1
    assert set(patches[0]) == expected_keys
    assert out.get("write_demoted_by_device") == demoted if demoted else "write_demoted_by_device" not in out


# ── 06-bmc-003: iLO DateTimeService → timezone ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, tz, extra_get", [
    ("real_hpe_dl380_gen12_01", "JST-9:00", 1), ("real_hpe_dl380_gen12_03", "JST-9:00", 1), ("real_hpe_dl380", "GMT-0", 1),
    ("real_hpe_csus3200_01", "Asia/Seoul", 0),      # RMC: TimeZoneName 있음 → 추가 GET 없음
    ("real_dell_r740", "CST6CDT", 0), ("real_lenovo_sr650_v4_01", None, 0),   # XCC: 링크 없음 → null 그대로
])
def test_ilo_timezone_from_datetime_service_only_when_name_missing(name, tz, extra_get):
    res, calls, _ = _replay(name)
    assert res["data"]["bmc"]["timezone"] == tz
    assert calls.count("Managers/1/DateTime") == extra_get


def test_ilo_timezone_null_when_datetime_resource_missing_or_name_present():
    def drop(rec):
        rec.pop("get::Managers/1/DateTime", None)
    res, _, _ = _replay("real_hpe_dl380_gen12_01", mutate=drop)
    assert res["data"]["bmc"]["timezone"] is None

    def name_present(rec):
        rec["get::Managers/1"][1]["TimeZoneName"] = "Asia/Seoul"
    res2, calls, _ = _replay("real_hpe_dl380_gen12_01", mutate=name_present)
    assert res2["data"]["bmc"]["timezone"] == "Asia/Seoul" and "Managers/1/DateTime" not in calls


# ── 06-bmc-005: BMC NIC 선택 ───────────────────────────────────────────────────────────────────────────────────────────

def _reverse_members(rec):
    coll = rec["get::Managers/1/EthernetInterfaces"][1]
    coll["Members"] = list(reversed(coll["Members"]))


def test_bmc_nic_pick_ignores_member_order_and_host_interface():
    base, _, _ = _replay("real_hpe_dl380_gen12_02")
    rev, _, _ = _replay("real_hpe_dl380_gen12_02", mutate=_reverse_members)
    for k in ("ip", "mac_address", "dns_name"):
        assert rev["data"]["bmc"][k] == base["data"]["bmc"][k]
    assert base["data"]["bmc"]["ip"] == "11.65.23.201", "USB 가상 NIC 16.1.15.1(Links.HostInterface, 활성)이 앞에 와도 전용 NIC"


def test_bmc_nic_pick_prefers_the_target_address():
    res, _, _ = _replay("real_hpe_dl380_gen12_02", ip="16.1.15.1")
    assert res["data"]["bmc"]["ip"] == "16.1.15.1", "대상 IP 와 같은 주소를 가진 NIC 이 1순위"
    res2, _, _ = _replay("real_hpe_dl380_gen12_02", ip="10.9.9.9")        # NAT/VIP — 어느 NIC 에도 없음 → ②
    assert res2["data"]["bmc"]["ip"] == "11.65.23.201"


@pytest.mark.parametrize("name, ip", [("real_lenovo_sr650_v4_01", "11.65.23.87"), ("real_hpe_csus3200_01", "11.65.23.24"), ("real_dell_r740", "10.173.12.159")])
def test_bmc_nic_pick_unchanged_for_other_vendors(name, ip):
    res, _, _ = _replay(name)
    assert res["data"]["bmc"]["ip"] == ip


# ── 06-bmc-006: bmc.name ManagerType 폴백 ─────────────────────────────────────────────────────────────────────────────

def test_bmc_name_falls_back_to_manager_type_label_without_layout(monkeypatch):
    def fake_get(bmc_ip, path, *a, **k):
        if path == "Managers/RMC":
            return 200, {"Id": "RMC", "ManagerType": "RackManager", "Model": "Compute Scale-up Server 3200", "FirmwareVersion": "1.77.30"}, None
        if path == "Managers/1":
            return 200, {"Id": "1", "ManagerType": "BMC", "Model": "iLO 7", "FirmwareVersion": "1.24.00"}, None
        if path == "Managers/Enc":
            return 200, {"Id": "a-very-long-identifier-that-is-not-a-label", "ManagerType": "EnclosureManager"}, None
        return 404, {}, "HTTP 404: Not Found"
    monkeypatch.setattr(rg, "_get", fake_get)
    assert rg.gather_bmc("1.2.3.4", "/redfish/v1/Managers/RMC", "hpe", "u", "p", 5, False)[0]["name"] == "RMC"
    assert rg.gather_bmc("1.2.3.4", "/redfish/v1/Managers/1", "hpe", "u", "p", 5, False)[0]["name"] == "iLO"
    assert rg.gather_bmc("1.2.3.4", "/redfish/v1/Managers/Enc", "hpe", "u", "p", 5, False)[0]["name"] == "EnclosureManager"


def test_csus_plain_replay_names_rmc_even_without_layout():
    res, _, _ = _replay("real_hpe_csus3200_01", layout=None)
    assert res["data"]["bmc"]["name"] == "RMC"
    res2, _, _ = _replay("real_hpe_csus3200_01")
    assert res2["data"]["bmc"]["name"] == "RMC"


# ── 06-bmc-010: 익명 성공 → auth_success null (site.yml 배선) ────────────────────────────────────────────────────────

def test_site_marks_anonymous_success_as_auth_success_null():
    t = SITE.read_text(encoding="utf-8")
    i = t.index("_diagnosis: >-")
    block = t[i:i + 700]
    assert "'auth_success': (none if (((_rf_used_account | default({})).role | default('primary')) == 'anonymous') else true)" in block
    assert "'auth_success': true," not in block
    # collect_standard 가 익명 성공을 role anonymous 로 표시한다(배선 전제)
    cs = (REPO / "redfish-gather" / "tasks" / "collect_standard.yml").read_text(encoding="utf-8")
    assert 'role: "anonymous"' in cs


# ── FIX 10: data.users 불변 ──────────────────────────────────────────────────────────────────────────────────────────

def test_redfish_users_section_is_untouched():
    """Redfish 는 BMC 계정을 data.users 에 넣지 않는다 — users 는 OS 계정이다(사용자 FIX 10). AccountService 는 읽기 근거로만 쓴다."""
    found = False
    for t in yaml.safe_load(NORM.read_text(encoding="utf-8")):
        sf = t.get("ansible.builtin.set_fact") if isinstance(t, dict) else None
        if isinstance(sf, dict) and isinstance(sf.get("_data_fragment"), dict) and "hardware" in sf["_data_fragment"]:
            assert "users" not in sf["_data_fragment"], "Redfish normalize 는 users 를 내지 않는다 — 공통 builder 가 not_supported 로 [] 를 둔다"
            found = True
        if isinstance(sf, dict) and "_sections_supported_fragment" in sf:
            assert "users" not in str(sf["_sections_supported_fragment"]), "users 는 Redfish 지원 섹션이 아니다"
    assert found, "_data_fragment 미발견"
    for name in ("real_hpe_csus3200_01", "real_lenovo_sr650_v4_01", "real_dell_r740"):
        res, _, _ = _replay(name)
        assert "users" not in res["data"], "모듈은 users 를 내지 않는다(normalize 가 [] 로 고정)"
