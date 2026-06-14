"""M-B3 회귀 — account_service_provision fall-through 패턴 (신규 4 vendor + Superdome).

cycle 2026-05-06 M-B2 매트릭스 결과 — 신규 4 vendor (Huawei/Inspur/Fujitsu/Quanta) +
HPE Superdome Flex 가 모두 redfish_gather.py:2467+ 의 fall-through 표준 POST path 로
graceful 처리되는지 정적 mock 검증.

검증 항목 (M-B2 매트릭스 row 22~25 + 9):
1. Huawei iBMC: 표준 POST 200 → 정상 생성 (fall-through standard POST path)
2. Inspur ISBMC: 표준 POST 400 → PasswordChangeRequired retry → 201 (Lenovo retry 활용)
3. Fujitsu iRMC: 표준 POST 200 → 정상 (PRIMERGY 표준)
4. Quanta QCT BMC: 표준 POST 200 → 정상 (OpenBMC bmcweb 표준)
5. HPE Superdome Flex: 표준 POST 200 → 정상 (vendor='hpe' fall-through, RMC level)

신규 vendor 의 OEM 분기 미등록 → fall-through 동작 검증.
F50 phase 4 verify-fallback (DELETE+POST 재생성) 은 vendor != dell 분기 자동 적용.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "redfish-gather" / "library"))

# ansible stub
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


def _fake_acct_get_empty(bmc_ip, u, p, t, v):
    """기존 사용자 없음 — 신규 생성 분기로 라우팅."""
    return {}, [], []


# ── Huawei iBMC: fall-through 표준 POST 정상 ─────────────────────────────────


def test_m_b3_huawei_ibmc_post_200_standard(monkeypatch):
    """vendor='huawei' (fall-through) + 표준 POST 201 → 정상 생성."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_empty)

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/3"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.1", "huawei",
        "admin", "current_pass",
        "infraops", "Passw0rd1!Infra", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["recovered"] is True, "Huawei fall-through 정상 생성 실패"
    assert out["method"] == "post_new", f"method='post_new' 기대. 실제: {out['method']}"
    assert len(call_log) == 1, "1차 POST 만 호출 — Lenovo retry 진입 X"
    assert call_log[0]["UserName"] == "infraops"
    assert call_log[0]["RoleId"] == "Administrator"


# ── Inspur ISBMC: 1차 400 → Lenovo retry 활용 ────────────────────────────────


def test_m_b3_inspur_isbmc_post_400_then_retry(monkeypatch):
    """vendor='inspur' (fall-through) + 1차 POST 400 → PasswordChangeRequired retry 201."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_empty)

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        if "PasswordChangeRequired" in body:
            return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/4"}, None
        return 400, {"error": "policy"}, "HTTP 400: Bad Request"

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.2", "inspur",
        "admin", "current_pass",
        "infraops", "Passw0rd1!Infra", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["recovered"] is True, "Inspur Lenovo-style retry 실패"
    assert out["method"] == "post_new"
    assert len(call_log) == 2, "2 회 호출 — 1차 표준 + 2차 PasswordChangeRequired"
    assert call_log[1]["PasswordChangeRequired"] is False


# ── Fujitsu iRMC: PRIMERGY 표준 POST ─────────────────────────────────────────


def test_m_b3_fujitsu_irmc_post_200_standard(monkeypatch):
    """vendor='fujitsu' (fall-through) + 표준 POST 200 → 정상 (iRMC S5/S6 표준)."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_empty)

    def fake_post(bmc_ip, path, body, u, p, t, v):
        return 200, {"@odata.id": "/redfish/v1/AccountService/Accounts/5"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.3", "fujitsu",
        "admin", "current_pass",
        "infraops", "Passw0rd1!Infra", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["recovered"] is True, "Fujitsu fall-through 표준 POST 실패"
    assert out["method"] == "post_new"


# ── Quanta QCT BMC: OpenBMC bmcweb 표준 ──────────────────────────────────────


def test_m_b3_quanta_qct_bmc_post_201_openbmc(monkeypatch):
    """vendor='quanta' (fall-through) + OpenBMC bmcweb POST 201 → 정상."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_empty)

    def fake_post(bmc_ip, path, body, u, p, t, v):
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/6"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.4", "quanta",
        "admin", "current_pass",
        "infraops", "Passw0rd1!Infra", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["recovered"] is True, "Quanta OpenBMC 표준 POST 실패"
    assert out["method"] == "post_new"


# ── HPE Superdome Flex: vendor='hpe' fall-through (RMC level) ───────────────


def test_m_b3_hpe_superdome_flex_post_200_rmc(monkeypatch):
    """vendor='hpe' (Superdome Flex sub-line) — 표준 POST 200 → 정상 (RMC AccountService)."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_empty)

    def fake_post(bmc_ip, path, body, u, p, t, v):
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/7"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.5", "hpe",  # Superdome Flex 도 vendor='hpe' (sub-line)
        "admin", "current_pass",
        "infraops", "Passw0rd1!Infra", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["recovered"] is True, "Superdome Flex (HPE sub-line) RMC POST 실패"
    assert out["method"] == "post_new"


# ── 신규 vendor: HPE retry 미진입 (vendor != hpe) ────────────────────────────


def test_m_b3_huawei_post_400_405_no_hpe_retry(monkeypatch):
    """vendor='huawei' + 1차 400 + 2차 405 (PasswordChangeRequired) → HPE Oem retry 미진입 → fail."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_empty)

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        if "PasswordChangeRequired" in body:
            return 405, {}, "HTTP 405: Method Not Allowed"
        return 400, {}, "HTTP 400: Bad Request"

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.6", "huawei",
        "admin", "current_pass",
        "infraops", "Passw0rd1!Infra", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    # vendor='huawei' != 'hpe' → HPE Oem.Hpe.Privileges 3차 retry 진입 안 함
    assert out["recovered"] is False, "HPE Oem retry 가 vendor=huawei 에 잘못 진입"
    assert len(call_log) == 2, "2 회만 호출 (1차 + Lenovo retry). HPE 3차 진입 안 함"


# ── F50 phase 4 verify-fallback: 신규 vendor 자동 적용 (vendor != dell) ─────


def _fake_acct_get_with_existing(bmc_ip, u, p, t, v):
    """기존 'infraops' 사용자 존재 — patch_existing 분기로 라우팅.

    account_service_find_user 가 acc['username'] 키 매칭 (redfish_gather.py:2122).
    """
    accounts = [{
        "id": "3",
        "slot_uri": "/redfish/v1/AccountService/Accounts/3",
        "username": "infraops",
        "role_id": "Administrator",
        "enabled": True,
    }]
    return {}, accounts, []


def test_m_b3_huawei_patch_verify_401_delete_repost_fallback(monkeypatch):
    """vendor='huawei' + PATCH 200 + verify 401 → DELETE+POST fallback 자동 진입 (vendor != dell)."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_with_existing)

    def fake_patch(bmc_ip, path, body, u, p, t, v):
        return 200, {}, None

    def fake_get(bmc_ip, path, u, p, t, v):
        if "Systems" in path:
            return 401, {}, "Unauthorized"  # verify 실패 — 권한 cache 손상 시뮬
        return 200, {}, None

    def fake_delete(bmc_ip, path, u, p, t, v):
        return 204, {}, None

    def fake_post(bmc_ip, path, body, u, p, t, v):
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/4"}, None

    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", fake_get)
    monkeypatch.setattr(rg, "_delete", fake_delete)
    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.7", "huawei",
        "admin", "current_pass",
        "infraops", "Passw0rd1!Infra", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    # vendor='huawei' != 'dell' → DELETE+POST 재생성 fallback 진입
    assert out["recovered"] is True, "Huawei verify-fallback (DELETE+POST) 실패"
    assert out["method"] == "delete_repost", f"method='delete_repost' 기대. 실제: {out['method']}"


def test_m_b3_dell_patch_verify_401_no_fallback(monkeypatch):
    """vendor='dell' + PATCH 200 + verify 401 → fallback 불가 (PATCH-only) → recovered=False."""
    monkeypatch.setattr(rg, "account_service_get", _fake_acct_get_with_existing)

    def fake_patch(bmc_ip, path, body, u, p, t, v):
        return 200, {}, None

    def fake_get(bmc_ip, path, u, p, t, v):
        return 401, {}, "Unauthorized"

    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", fake_get)

    out = rg.account_service_provision(
        "10.99.99.8", "dell",
        "admin", "current_pass",
        "infraops", "Passw0rd1!Infra", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    # vendor='dell' → PATCH-only, fallback 불가
    assert out["recovered"] is False, "Dell PATCH-only — fallback 진입하면 안 됨"
    # errors[] 에 권한 cache 손상 또는 PATCH 실패 메시지 명시 (Security Strengthen Policy 등)
    error_messages = " ".join(e.get("message", "") for e in out["errors"])
    assert any(token in error_messages for token in [
        "PATCH-only", "권한 cache", "verify HTTP 401",
        "Security Strengthen", "fallback", "PATCH"
    ]), f"errors[] 에 PATCH 실패 / 권한 손상 메시지 부재. 실제: {error_messages[:300]}"
