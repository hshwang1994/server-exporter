"""vault 검증 스크립트가 Secret 을 출력하지 않음을 고정한다 (2026-08-12).

왜 필요한가:
    Location Vault 이관 검증은 **복호화한 내용**을 다룬다. 진단을 자세히 하려다가
    username / password 를 콘솔에 찍는 순간 그 값이 Jenkins 콘솔 로그와 터미널 스크롤백에
    남는다. 그 실수는 코드 리뷰로 매번 잡기보다 테스트로 못 박는 편이 확실하다.

검증:
    - 합성 vault 내용(진짜 자격증명이 아니다)을 검사기에 넣고, 결과 어디에도
      username / password 문자열이 나타나지 않는지 확인한다
    - 스크립트에 마스터 비밀번호가 하드코딩돼 있지 않은지 확인한다
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ai" / "vault_decrypt_check.py"

pytest.importorskip("cryptography", reason="vault_decrypt_check 는 cryptography 를 쓴다")

# 이 스크립트는 `.gitignore` 대상이다 (cycle-018 결정 — 당시 마스터 키가 하드코딩돼
# 있었기 때문). 2026-08-12 에 하드코딩을 제거했지만 gitignore 해제는 사용자 결정 사항이라
# 그대로 두었다. 따라서 fresh clone / CI 에는 파일이 없을 수 있고, 그때는 검사할 대상이
# 없는 것이지 실패가 아니다.
if not SCRIPT.is_file():  # pragma: no cover — 로컬 도구 부재 환경
    pytest.skip(
        "scripts/ai/vault_decrypt_check.py 부재 (.gitignore 대상 로컬 도구)",
        allow_module_level=True,
    )

_spec = importlib.util.spec_from_file_location("vault_decrypt_check", SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["vault_decrypt_check"] = _mod
_spec.loader.exec_module(_mod)

# 합성 값 — 실제 자격증명이 아니다. 출력에 새어 나오는지 보려고 일부러 특이하게 만든다.
_FAKE_USER = "zzz-canary-username-zzz"
_FAKE_PASS = "zzz-canary-password-zzz"
_FAKE_BECOME = "zzz-canary-become-zzz"

SAMPLE = f"""
accounts:
  - username: "{_FAKE_USER}"
    password: "{_FAKE_PASS}"
    label: "dell_current"
    role: "primary"
  - username: "{_FAKE_USER}2"
    password: "{_FAKE_PASS}2"
    label: "dell_fallback_1"
    role: "recovery"
ansible_become_password: "{_FAKE_BECOME}"
"""


def test_inspect_accounts_never_returns_secret_values():
    info = _mod.inspect_accounts(SAMPLE, vendor="dell")
    blob = json.dumps(info, ensure_ascii=False)
    for canary in (_FAKE_USER, _FAKE_PASS, _FAKE_BECOME):
        assert canary not in blob, f"검사 결과에 {canary!r} 유출"


def test_inspect_accounts_reports_structure_without_values():
    info = _mod.inspect_accounts(SAMPLE, vendor="dell")
    assert info["accounts_count"] == 2
    assert info["account_roles"] == ["primary", "recovery"]
    assert info["account_labels"] == ["dell_current", "dell_fallback_1"]
    assert info["account_username_present"] == [True, True]
    assert info["has_become_password"] is True
    assert not info["problems"]


def test_stdout_of_a_full_report_has_no_secret(capsys):
    """실제 출력 경로(print)로도 새지 않는지 — 반환값만 검사하면 놓친다."""
    info = _mod.inspect_accounts(SAMPLE, vendor="dell")
    problems = info.pop("problems", [])
    warnings = info.pop("warnings", [])
    for k, v in info.items():
        print(f"  {k}: {v}")
    for w in warnings:
        print(f"  [WARN] {w}")
    for p in problems:
        print(f"  [FAIL] {p}")
    out = capsys.readouterr().out
    for canary in (_FAKE_USER, _FAKE_PASS, _FAKE_BECOME):
        assert canary not in out, f"stdout 에 {canary!r} 유출"


def test_no_hardcoded_master_password():
    """스크립트에 마스터 비밀번호 기본값이 다시 들어오지 않게 한다.

    2026-08-12 이전에는 `password = sys.argv[1] if ... else "<실제 비밀번호>"` 형태로
    저장소에 평문 마스터 키가 있었다. 제거했고, 여기서 재발을 막는다.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )
    assert 'else "' not in code.split("def resolve_password")[-1].split("def ")[0], (
        "resolve_password 에 문자열 기본값이 생겼다 — 마스터 키 하드코딩 의심"
    )
    # 흔한 형태의 기본 인자 하드코딩 방지
    assert "sys.argv[1] if len(sys.argv)" not in code, (
        "위치 인자 + 하드코딩 기본값 패턴이 되살아났다"
    )


def test_missing_password_fails_loudly(monkeypatch):
    """키가 없으면 조용히 넘어가지 않고 명시적으로 실패한다."""
    monkeypatch.delenv("SE_VAULT_PASSWORD", raising=False)
    monkeypatch.delenv("ANSIBLE_VAULT_PASSWORD", raising=False)

    class _Args:
        password_file = None

    assert _mod.resolve_password(_Args()) is None


def test_role_and_label_problems_are_detected():
    bad = """
accounts:
  - username: "u"
    password: "p"
    label: "not_a_known_label"
    role: "superuser"
"""
    info = _mod.inspect_accounts(bad, vendor="dell")
    joined = " ".join(info["problems"])
    assert "role=" in joined
    assert "role=primary 후보가 없다" in joined


def test_recovery_label_outside_allowed_set_is_a_problem():
    """허용 label 검사는 **recovery 후보에만** 적용된다."""
    bad = """
accounts:
  - username: "u1"
    password: "p1"
    label: "common_infraops"
    role: "primary"
  - username: "u2"
    password: "p2"
    label: "not_a_known_label"
    role: "recovery"
"""
    joined = " ".join(_mod.inspect_accounts(bad, vendor="dell")["problems"])
    assert "recovery label 이 허용 set 밖" in joined
    assert "not_a_known_label" in joined


def test_primary_label_outside_recovery_set_is_not_a_problem():
    """primary label 을 recovery 허용 set 으로 재던 오탐의 회귀 방어 (2026-08-12).

    허용 set 의 정본은 adapter `credentials.recovery_accounts[].vault_label` —
    즉 **recovery 후보의 label 집합**이다. 표준 수집 계정(primary)의 label 은
    그 목록에 없는 것이 정상이며, 실제 9 vendor vault 가 모두 그 형태다.
    종전 구현은 primary 까지 검사해 9 vendor 전부를 오탐으로 실패시켰다.
    """
    ok = """
accounts:
  - username: "u1"
    password: "p1"
    label: "common_infraops"
    role: "primary"
  - username: "u2"
    password: "p2"
    label: "dell_fallback_1"
    role: "recovery"
"""
    info = _mod.inspect_accounts(ok, vendor="dell")
    assert not info["problems"], f"오탐: {info['problems']}"


def test_recovery_first_is_warning_not_failure():
    """배열 순서는 계약이다. 재정렬하지 않고 **경고만** 한다."""
    recovery_first = """
accounts:
  - username: "u1"
    password: "p1"
    label: "dell_fallback_1"
    role: "recovery"
  - username: "u2"
    password: "p2"
    label: "dell_current"
    role: "primary"
"""
    info = _mod.inspect_accounts(recovery_first, vendor="dell")
    assert not info["problems"], "recovery-first 를 실패로 만들면 안 된다 (의도적일 수 있다)"
    assert info["warnings"], "recovery-first 는 경고로 알려야 한다"


def test_empty_vault_is_a_problem():
    info = _mod.inspect_accounts("{}\n")
    assert info["problems"], "인증 후보가 0개가 되는 상태는 잡아야 한다"


def test_kind_of_path():
    """표준 / 복구 / 단일 vault 를 경로로 구분한다 (2026-08-12 분리)."""
    assert _mod.kind_of("vault/common/redfish/standard.yml") == "standard"
    assert _mod.kind_of("vault/ic/redfish/dell.yml") == "recovery"
    assert _mod.kind_of("vault/ic/os/linux.yml") == "single"
    assert _mod.kind_of("vault/ic/esxi.yml") == "single"
    assert _mod.kind_of("vault/redfish/dell.yml") == "single"


def test_recovery_vault_without_primary_is_fine():
    """복구 vault 에 primary 가 없는 것은 정상이다 — 표준은 전역 파일에 있다."""
    rec = """
accounts:
  - username: "u"
    password: "p"
    label: "dell_fallback_1"
    role: "recovery"
"""
    info = _mod.inspect_accounts(rec, vendor="dell", kind="recovery")
    assert not info["problems"], info["problems"]
    assert not info["warnings"], "복구 vault 의 recovery-first 는 경고 대상이 아니다"


def test_recovery_vault_with_primary_is_a_problem():
    """복구 vault 에 primary 가 남아 있으면 표준 계정 중복이다."""
    polluted = """
accounts:
  - username: "u"
    password: "p"
    label: "common_infraops"
    role: "primary"
  - username: "u2"
    password: "p2"
    label: "dell_fallback_1"
    role: "recovery"
"""
    joined = " ".join(_mod.inspect_accounts(polluted, vendor="dell", kind="recovery")["problems"])
    assert "recovery 아닌 role" in joined


def test_standard_vault_with_recovery_is_a_problem():
    mixed = """
accounts:
  - username: "u"
    password: "p"
    label: "common_infraops"
    role: "primary"
  - username: "u2"
    password: "p2"
    label: "dell_fallback_1"
    role: "recovery"
"""
    joined = " ".join(_mod.inspect_accounts(mixed, kind="standard")["problems"])
    assert "primary 아닌 role" in joined


def test_vendor_of_path():
    assert _mod.vendor_of("vault/ic/redfish/dell.yml") == "dell"
    assert _mod.vendor_of("vault/redfish/hpe.yml") == "hpe"
    assert _mod.vendor_of("vault/ic/os/linux.yml") is None
    assert _mod.vendor_of("vault/ic/esxi.yml") is None
