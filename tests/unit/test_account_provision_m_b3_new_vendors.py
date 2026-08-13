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

import pytest
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

# 2026-08-12: provision 이 account_service_get → account_service_discover 로 옮겨졌다.
# 기존 3-tuple fake 를 discovery dict 로 감싸는 공용 seam (tests/unit/account_seam.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from account_seam import as_discovery as _as_discovery_raw  # noqa: E402


def _as_discovery(fn, **overrides):
    return _as_discovery_raw(fn, rg, **overrides)


@pytest.fixture(autouse=True)
def _default_write_verify_seam(monkeypatch):
    """2026-08-12 (audit H-1): 이제 **모든** 계정 쓰기 경로가 재조회 + 표준 자격 재인증을
    수행한다. 종전 POST 경로는 2xx 만으로 성공을 보고했다.

    그래서 쓰기 seam 만 stub 하던 테스트가 실제 네트워크로 나가게 된다. 여기서 기본
    검증 seam 을 성공으로 깔아 둔다. 개별 테스트가 다시 setattr 하면 그쪽이 이긴다.
    """
    monkeypatch.setattr(rg, "_get", lambda *a, **k: (200, {}, None))
    monkeypatch.setattr(rg, "_get_response_etag", lambda *a, **k: None)
    monkeypatch.setattr(rg.time, "sleep", lambda *_: None)



def _fake_acct_get_empty(bmc_ip, u, p, t, v):
    """기존 사용자 없음 — 신규 생성 분기로 라우팅."""
    return {}, [], []


# ── Huawei iBMC: fall-through 표준 POST 정상 ─────────────────────────────────


def test_m_b3_huawei_ibmc_post_200_standard(monkeypatch):
    """vendor='huawei' (fall-through) + 표준 POST 201 → 정상 생성."""
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/3"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.1", "huawei",
        "admin", "current_pass",
        "infraops", "<target-pass>", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["recovered"] is True, "Huawei fall-through 정상 생성 실패"
    assert out["method"] == "post_new", f"method='post_new' 기대. 실제: {out['method']}"
    assert len(call_log) == 1, "1차 POST 만 호출 — Lenovo retry 진입 X"
    assert call_log[0]["UserName"] == "infraops"
    assert call_log[0]["RoleId"] == "Administrator"


# ── Inspur ISBMC: 1차 400 → Lenovo retry 활용 ────────────────────────────────


def test_m_b3_inspur_post_400_writes_once_and_fails(monkeypatch):
    """vendor='inspur' 이지만 M6 근거가 없으면 generic — POST 400 에서 **끝난다.**

    2026-08-12 (rev.2) 반전. 종전에는 400 뒤 `PasswordChangeRequired:false` 를 덧붙여
    다시 POST 했다. Inspur 공식 조사(06 §17)는 그 재시도를 명시적으로 금지한다 —
    M6 공식 Create payload 에 `PasswordChangeRequired` 자체가 없다. 그리고 여기 도달하는
    Inspur 는 M5/M7 처럼 **계약을 확보하지 못한** 쪽이라 더더욱 추측하면 안 된다.
    """
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

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
        "infraops", "<target-pass>", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["method"] == "post_new"
    assert len(call_log) == 1, "추측성 2차 Write 가 발생했다"
    assert "PasswordChangeRequired" not in call_log[0]
    assert out["recovered"] is False
    assert out["write_accepted"] is False


# ── Fujitsu iRMC: PRIMERGY 표준 POST ─────────────────────────────────────────


def test_m_b3_fujitsu_irmc_post_200_standard(monkeypatch):
    """vendor='fujitsu' (fall-through) + 표준 POST 200 → 정상 (iRMC S5/S6 표준)."""
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

    def fake_post(bmc_ip, path, body, u, p, t, v):
        return 200, {"@odata.id": "/redfish/v1/AccountService/Accounts/5"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.3", "fujitsu",
        "admin", "current_pass",
        "infraops", "<target-pass>", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["recovered"] is True, "Fujitsu fall-through 표준 POST 실패"
    assert out["method"] == "post_new"


# ── Quanta QCT BMC: OpenBMC bmcweb 표준 ──────────────────────────────────────


def test_m_b3_quanta_qct_bmc_post_201_openbmc(monkeypatch):
    """vendor='quanta' (fall-through) + OpenBMC bmcweb POST 201 → 정상."""
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

    def fake_post(bmc_ip, path, body, u, p, t, v):
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/6"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.4", "quanta",
        "admin", "current_pass",
        "infraops", "<target-pass>", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["recovered"] is True, "Quanta OpenBMC 표준 POST 실패"
    assert out["method"] == "post_new"


# ── HPE Superdome Flex: vendor='hpe' fall-through (RMC level) ───────────────


def test_m_b3_hpe_superdome_flex_post_200_rmc(monkeypatch):
    """vendor='hpe' (Superdome Flex sub-line) — 표준 POST 200 → 정상 (RMC AccountService)."""
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

    def fake_post(bmc_ip, path, body, u, p, t, v):
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/7"}, None

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.5", "hpe",  # Superdome Flex 도 vendor='hpe' (sub-line)
        "admin", "current_pass",
        "infraops", "<target-pass>", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["recovered"] is True, "Superdome Flex (HPE sub-line) RMC POST 실패"
    assert out["method"] == "post_new"


# ── 신규 vendor: HPE retry 미진입 (vendor != hpe) ────────────────────────────


def test_m_b3_huawei_post_400_writes_once_and_sends_no_guessed_property(monkeypatch):
    """Huawei 는 실패해도 다른 payload 로 다시 쓰지 않고, 미지원 속성을 추측해 보내지 않는다.

    2026-08-12 변경: 종전에는 400/405 를 받으면 `PasswordChangeRequired:false` 를 붙여
    다시 POST 했다. Huawei 공식 AccountService 자료(Kunpeng iBMC / MM920)에는 이 속성이
    ManagerAccount 표준 속성으로 확인되지 않는다 — 지원 근거 없는 속성을 재시도 수단으로
    끼워 넣는 것은 추측 Write 다.
    source: Huawei EDOC1100372764 (Kunpeng iBMC Redfish Interface, AccountService)
    """
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_empty))

    call_log = []

    def fake_post(bmc_ip, path, body, u, p, t, v):
        call_log.append(dict(body))
        return 400, {}, "HTTP 400: Bad Request"

    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.6", "huawei",
        "admin", "current_pass",
        "infraops", "<target-pass>", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
    )

    assert out["family"] == "huawei_ibmc"
    assert out["recovered"] is False
    assert len(call_log) == 1, "실패 후 다른 payload 로 다시 썼다 (Write fallback 금지)"
    assert "PasswordChangeRequired" not in call_log[0]


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
    """vendor='huawei' + PATCH 200 + verify 401 → DELETE+POST fallback (vendor != dell).

    2026-08-11 (Phase 6-B §11) 기대값 변경: 이 fallback 은 기존 계정을 지우므로 기본값이
    off 가 됐다. vendor 분기 자체는 그대로이므로 명시적 opt-in 으로 고정한다.
    """
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_with_existing))

    def fake_patch(bmc_ip, path, body, u, p, t, v):
        return 200, {}, None

    reposted = []

    def fake_get(bmc_ip, path, u, p, t, v):
        # 권한 cache 손상 시뮬: 재생성 전 표준 자격 인증은 401, 재생성 뒤에는 200.
        # 2026-08-12: 재생성 경로도 재조회 + 재인증까지 확인한다 (audit H-1).
        if "Systems" in path:
            return (200, {}, None) if reposted else (401, {}, "Unauthorized")
        return 200, {}, None

    def fake_delete(bmc_ip, path, u, p, t, v):
        return 204, {}, None

    def fake_post(bmc_ip, path, body, u, p, t, v):
        reposted.append(path)
        return 201, {"@odata.id": "/redfish/v1/AccountService/Accounts/4"}, None

    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", fake_get)
    monkeypatch.setattr(rg, "_delete", fake_delete)
    monkeypatch.setattr(rg, "_post", fake_post)

    out = rg.account_service_provision(
        "10.99.99.7", "huawei",
        "admin", "<recovery-pass>",
        "infraops", "<target-pass>", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
        allow_delete_recreate=True,
    )

    # vendor='huawei' != 'dell' → DELETE+POST 재생성 fallback 진입
    assert out["recovered"] is True, "Huawei verify-fallback (DELETE+POST) 실패"
    assert out["method"] == "delete_repost", f"method='delete_repost' 기대. 실제: {out['method']}"


def test_m_b3_dell_patch_verify_401_no_fallback(monkeypatch):
    """vendor='dell' + PATCH 200 + verify 401 → fallback 불가 (PATCH-only) → recovered=False."""
    monkeypatch.setattr(rg, "account_service_discover", _as_discovery(_fake_acct_get_with_existing))

    def fake_patch(bmc_ip, path, body, u, p, t, v):
        return 200, {}, None

    def fake_get(bmc_ip, path, u, p, t, v):
        return 401, {}, "Unauthorized"

    monkeypatch.setattr(rg, "_patch", fake_patch)
    monkeypatch.setattr(rg, "_get", fake_get)

    out = rg.account_service_provision(
        "10.99.99.8", "dell",
        "admin", "<recovery-pass>",
        "infraops", "<target-pass>", "Administrator",
        timeout=10, verify_ssl=False, dryrun=False,
        # Phase 6-B §11: fallback 기본값 off. 이 테스트는 "켜도 Dell 은 안 지운다" 를 고정한다.
        allow_delete_recreate=True,
    )

    # vendor='dell' → PATCH-only, fallback 불가
    assert out["recovered"] is False, "Dell PATCH-only — fallback 진입하면 안 됨"
    # errors[] 에 권한 cache 손상 또는 PATCH 실패 메시지 명시 (Security Strengthen Policy 등)
    error_messages = " ".join(e.get("message", "") for e in out["errors"])
    assert any(token in error_messages for token in [
        "PATCH-only", "권한 cache", "verify HTTP 401",
        "Security Strengthen", "fallback", "PATCH"
    ]), f"errors[] 에 PATCH 실패 / 권한 손상 메시지 부재. 실제: {error_messages[:300]}"
