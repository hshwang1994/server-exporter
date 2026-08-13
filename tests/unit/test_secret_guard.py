"""누출 가드 자체의 회귀 — 평문을 저장하지 않고도 자격증명 노출을 잡는가.

배경 (2026-08-12): 누출 방지 테스트들이 검사 대상인 **진짜 비밀번호를 소스에 그대로**
적어 두고 있었다. 저장소 전수 조사에서 실 자격증명 10 종이 tracked file 391 개에
평문으로 있었고, 그중 8 개가 그 가드 파일들이었다. 값 대신 sha256 앞 8자리로 대조하는
방식으로 바꿨으므로, 그 방식이 실제로 동작하는지를 여기서 고정한다.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

import secret_guard as sg  # noqa: E402


def _dg(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:8]


@pytest.fixture()
def synthetic(monkeypatch):
    """실제 자격증명을 쓰지 않고 가드 동작만 확인하기 위한 합성 표."""
    fake = "SynthSecret#42"
    monkeypatch.setattr(sg, "KNOWN_SECRET_DIGESTS", frozenset({_dg(fake)}))
    monkeypatch.setattr(sg, "_LENGTHS", (len(fake),))
    return fake


def test_clean_text_reports_nothing(synthetic):
    assert sg.find_known_secrets("") == set()
    assert sg.find_known_secrets("status=success ip=10.0.0.1") == set()


def test_bare_token_is_detected(synthetic):
    assert sg.find_known_secrets(synthetic) == {_dg(synthetic)}


@pytest.mark.parametrize("template", [
    'password={v}',
    '"password": "{v}"',
    'echo {v} | sudo -S dmidecode',
    'fact_caching_connection = host:6379:0:{v}',
    'https://user:{v}@10.0.0.1/redfish/v1/',
    '앞말 {v} 뒷말',
    '{v}Infra',          # 접미사가 붙은 형태
    'prefix-{v}',        # 접두사가 붙은 형태
])
def test_detected_in_realistic_carriers(synthetic, template):
    text = template.format(v=synthetic)
    assert sg.find_known_secrets(text) == {_dg(synthetic)}, template


def test_failure_message_never_prints_the_value(synthetic):
    with pytest.raises(AssertionError) as err:
        sg.assert_no_secret(f"password={synthetic}", "테스트 대상")
    msg = str(err.value)
    assert synthetic not in msg, "실패 메시지에 평문이 찍혔다"
    assert _dg(synthetic) in msg, "어떤 값인지 digest 로도 알 수 없다"


def test_canary_is_detected():
    with pytest.raises(AssertionError):
        sg.assert_no_secret(f"detail: {sg.CANARY_PASSWORD}")
    sg.assert_no_secret("detail: HTTP 401 Unauthorized")


# ── 실제 표에 대한 계약 ───────────────────────────────────────────────────────
def test_table_carries_no_plaintext():
    """가드 파일 자체에 평문 자격증명이 없어야 한다 (이 파일이 생긴 이유)."""
    src = (REPO / "tests" / "secret_guard.py").read_text(encoding="utf-8")
    for digest in sg.KNOWN_SECRET_DIGESTS:
        assert len(digest) == 8 and all(c in "0123456789abcdef" for c in digest)
    # 가드 파일을 가드 자신으로 검사한다 — 알려진 자격증명이 들어 있으면 안 된다.
    assert sg.find_known_secrets(src) == set(), "가드 파일에 평문 자격증명이 있다"


def test_trivial_vendor_defaults_are_not_in_the_table():
    """`admin` / `password` 같은 공개 기본값을 넣으면 가드가 무의미해진다.

    이 저장소에서 각각 627 / 433 개 파일에 등장한다 — 넣는 순간 모든 산출물이
    '누출' 로 잡혀 가드를 꺼 버리게 된다. 공개 기본값은 `docs/operate/05-vault.md` 의 벤더 표로 관리한다.
    """
    for trivial in ("admin", "ADMIN", "password", "Password", "root",
                    "calvin", "Admin@9000", "USERID"):
        assert _dg(trivial) not in sg.KNOWN_SECRET_DIGESTS, trivial


def test_known_table_is_not_empty():
    assert len(sg.KNOWN_SECRET_DIGESTS) >= 10
    assert sg._LENGTHS and all(isinstance(n, int) and n > 0 for n in sg._LENGTHS)


def test_generic_patterns_catch_unknown_credentials():
    """표에 없는 새 자격증명도 구조로 잡힌다."""
    hits = [p for p in sg.GENERIC_SECRET_PATTERNS if p.search('password="Wholly-New-Value"')]
    assert hits, "password=<값> 형태를 잡는 일반 패턴이 없다"
    hits = [p for p in sg.GENERIC_SECRET_PATTERNS
            if p.search("https://svc:BrandNewPass@10.0.0.1/x")]
    assert hits, "URL 매립 자격증명을 잡는 패턴이 없다"
