"""실장비 미러 재생 — Account Capability Discovery / 존재 판정 / Family 선택.

audit D-8: `tests/reference/redfish/**/redfish_v1_accountservice*.json` 과
`tests/fixtures/redfish/*/account_service.json` 을 읽는 테스트가 0건이었다.
lab 없이 UNVERIFIED 를 낮출 수 있는 유일한 수단이 이 미러들이다.

여기서 검증하는 것은 **읽기 단계뿐**이다. 미러에는 쓰기 응답이 없으므로 쓰기 동작을
여기서 "증명" 하지 않는다 — 그렇게 하면 다시 상상으로 만든 mock 이 된다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import account_replay as ar  # noqa: E402

rg = ar.rg
REPO = ar.REPO

pytestmark = pytest.mark.integration

_MIRROR_HOSTS = [
    (vendor, d)
    for vendor in ("dell", "hpe", "lenovo", "cisco")
    for d in ar.hosts(vendor)
]


def _ids(param):
    return f"{param[0]}/{param[1].name}"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)


@pytest.mark.skipif(not _MIRROR_HOSTS, reason="reference 미러 없음")
@pytest.mark.parametrize("param", _MIRROR_HOSTS, ids=[_ids(p) for p in _MIRROR_HOSTS])
def test_discovery_reads_real_mirror_completely(param, monkeypatch):
    """실장비 미러에서 AccountService → Accounts → 각 계정까지 **완전히** 읽는다."""
    vendor, host_dir = param
    table = ar.load_mirror(host_dir)
    monkeypatch.setattr(rg, "_get", ar.make_get(table))

    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)

    assert d["service"] is not None, f"{host_dir.name}: AccountService 를 못 읽었다"
    assert d["accounts_uri"], "Accounts 링크를 따라가지 못했다"
    assert d["enumeration"] == rg.ENUM_COMPLETE, (
        f'{host_dir.name}: 열거가 불완전하다 '
        f'(declared={d["member_total"]} read={d["member_read"]}) — '
        f'이 상태에서는 계정 부재를 확정하면 안 된다'
    )
    assert d["member_read"] == d["member_total"] > 0
    # 하드코딩이 아니라 링크를 따라갔다는 증거: 미러가 준 URI 와 일치한다.
    svc = table.get(d["service_uri"])
    assert svc and svc[1].get("Accounts", {}).get("@odata.id")


@pytest.mark.skipif(not _MIRROR_HOSTS, reason="reference 미러 없음")
@pytest.mark.parametrize("param", _MIRROR_HOSTS, ids=[_ids(p) for p in _MIRROR_HOSTS])
def test_absent_is_only_claimed_after_complete_enumeration(param, monkeypatch):
    """미러에 없는 username 은 ABSENT, 있는 username 은 PRESENT 로 판정된다."""
    vendor, host_dir = param
    table = ar.load_mirror(host_dir)
    monkeypatch.setattr(rg, "_get", ar.make_get(table))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)

    state, matches = rg.account_presence(d, "definitely_not_there_9f2a")
    assert state == rg.PRESENCE_ABSENT and matches == []

    named = [a for a in d["accounts"] if (a.get("username") or "")]
    if named:
        state2, m2 = rg.account_presence(d, named[0]["username"])
        assert state2 in (rg.PRESENCE_PRESENT, rg.PRESENCE_AMBIGUOUS)
        assert m2


@pytest.mark.skipif(not _MIRROR_HOSTS, reason="reference 미러 없음")
@pytest.mark.parametrize("param", _MIRROR_HOSTS, ids=[_ids(p) for p in _MIRROR_HOSTS])
def test_collection_read_failure_makes_presence_unknown(param, monkeypatch):
    """Accounts 컬렉션이 403 이면 계정 부재를 확정하지 않는다 (audit C-1).

    같은 미러를 쓰되 컬렉션 GET 만 403 으로 바꾼다. 종전 코드는 이 상황에서
    accounts=[] → "계정 없음" → **실제 생성 POST** 로 진행했다.
    """
    vendor, host_dir = param
    table = ar.load_mirror(host_dir)
    base_get = ar.make_get(table)
    svc = table.get("AccountService")
    accounts_uri = rg._p(svc[1]["Accounts"]["@odata.id"])

    def _get(bmc_ip, path, u, p, t, v):
        if rg._p(path) == accounts_uri:
            return 403, {}, "HTTP 403: Forbidden"
        return base_get(bmc_ip, path, u, p, t, v)

    monkeypatch.setattr(rg, "_get", _get)
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)
    assert d["enumeration"] != rg.ENUM_COMPLETE
    state, _ = rg.account_presence(d, "infraops")
    assert state == rg.PRESENCE_UNKNOWN


@pytest.mark.skipif(not _MIRROR_HOSTS, reason="reference 미러 없음")
@pytest.mark.parametrize("param", _MIRROR_HOSTS, ids=[_ids(p) for p in _MIRROR_HOSTS])
def test_family_selection_is_deterministic_on_real_mirror(param, monkeypatch):
    """같은 미러에는 항상 같은 Family 가 나온다 (Write 방식이 실행마다 달라지면 안 된다)."""
    vendor, host_dir = param
    table = ar.load_mirror(host_dir)
    monkeypatch.setattr(rg, "_get", ar.make_get(table))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)

    first, reasons = rg.resolve_account_family(vendor, d, None)
    for _ in range(3):
        again, _ = rg.resolve_account_family(vendor, d, None)
        assert again["id"] == first["id"]
    assert reasons, "Family 를 고른 근거가 남지 않았다"
    assert first["evidence"] in ("proven", "documented", "unverified")


def test_dell_mirror_selects_slot_patch_family(monkeypatch):
    """Dell 실미러는 slot PATCH Family 로 확정된다 (POST 가 아니다)."""
    dell = ar.hosts("dell")
    if not dell:
        pytest.skip("dell 미러 없음")
    table = ar.load_mirror(dell[0])
    monkeypatch.setattr(rg, "_get", ar.make_get(table))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)
    fam, _ = rg.resolve_account_family("dell", d, None)
    assert fam["create_method"] == "slot_patch"
    assert "1" in fam["reserved_slot_ids"], "IPMI anonymous 예약 슬롯을 보호하지 않는다"


def test_cisco_mirror_role_vocabulary_drives_role_id(monkeypatch):
    """Cisco RoleId 는 vendor 이름이 아니라 **장비가 지원한다고 말한 값**에서 고른다.

    같은 'cisco' 라도 IMC 는 'admin', 최신 Cisco BMC 는 'Administrator' 를 쓴다.
    고정 remap 은 한쪽을 반드시 깨뜨린다.
    source: cisco.com/.../b_Cisco_IMC_REST_API_guide_4_1 (admin),
            cisco.com/.../b_cisco-bmc-rest-api-guide (Administrator)
    """
    cisco = ar.hosts("cisco")
    if not cisco:
        pytest.skip("cisco 미러 없음")
    table = ar.load_mirror(cisco[0])
    monkeypatch.setattr(rg, "_get", ar.make_get(table))
    d = rg.account_service_discover("10.0.0.1", "u", "p", 5, False)
    fam, _ = rg.resolve_account_family("cisco", d, None)
    chosen = rg.choose_role_id(fam, "Administrator", d)
    if d["role_ids"]:
        assert chosen in d["role_ids"], (
            f"장비가 지원하지 않는 RoleId 를 골랐다: {chosen} not in {d['role_ids']}")


# ── mock fixture (lab 부재 vendor) — 정책 필드 파싱만 확인 ────────────────────
_FIXTURE_ACCOUNT_SERVICE = sorted(
    (REPO / "tests" / "fixtures" / "redfish").glob("*/account_service.json"))


@pytest.mark.skipif(not _FIXTURE_ACCOUNT_SERVICE, reason="account_service fixture 없음")
@pytest.mark.parametrize("path", _FIXTURE_ACCOUNT_SERVICE,
                         ids=[p.parent.name for p in _FIXTURE_ACCOUNT_SERVICE])
def test_policy_fields_parse_from_vendor_fixture(path):
    """lab 부재 vendor fixture 에서도 정책 필드가 계약대로 읽힌다.

    이 fixture 들은 web sources 기반 mock 이라 **동작 증명이 아니다.** 여기서 확인하는
    것은 파서가 vendor 마다 다른 필드 구성을 안전하게 다루는가 뿐이다.
    """
    body = json.loads(path.read_text(encoding="utf-8"))
    policy = rg._account_policy_of(body)
    assert set(policy) == {
        "service_enabled", "min_password_length", "max_password_length",
        "lockout_threshold", "lockout_duration", "lockout_counter_reset",
        # 2026-08-12: 장비가 Oem 에 선언하는 '인증 실패 후 지연'. 재인증 확인 간격을
        #   여기서 끌어온다 (HPE iLO 는 AuthFailureDelayTimeSeconds=10 을 선언한다).
        "auth_failure_delay_seconds", "auth_failures_before_delay",
        "supported_account_types",
        # 2026-08-12 (rev.2): 인증 방식 자체가 꺼져 있을 수 있다. Unadvertised(광고만 안 함)와
        #   Disabled(사용 불가)는 다르고, Disabled 를 '비밀번호 오류' 로 오진하면 안 된다.
        #   읽기만 한다 — 자동으로 켜지 않는다 (02 §24, 03 §23, 09 §23/§24).
        "http_basic_auth", "auth_methods",
    }
    for key in ("min_password_length", "max_password_length",
                "lockout_threshold", "lockout_duration",
                "auth_failure_delay_seconds", "auth_failures_before_delay"):
        assert policy[key] is None or isinstance(policy[key], int)
    # 없는 값을 0 으로 접지 않는다 — "정책 없음" 과 "0" 은 다른 사실이다.
    if "MinPasswordLength" not in body:
        assert policy["min_password_length"] is None
