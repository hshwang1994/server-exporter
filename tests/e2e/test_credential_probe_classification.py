"""Phase 5-A: 4 채널 Credential Probe 가 관측 가능한 범위를 넘어 단정하지 않는지.

HEAD 실측 (2026-08-11) — 각 채널이 "모든 자격 후보 실패" 로 판정하는 실제 식과,
그 식이 거짓이 되는 원인:

| 채널    | 판정식                                        | 모듈 옵션                              | 구조적 구분 가능? |
|---------|-----------------------------------------------|----------------------------------------|-------------------|
| Linux   | `rc == 0 and '__auth_ok__' in stdout`         | raw + failed_when:false + ignore_unreachable | **불가** |
| Windows | `ping == 'pong'`                              | win_ping + 동일 옵션                   | **불가** |
| ESXi    | `_e_probe.ansible_facts is defined`           | vmware_host_facts + failed_when:false  | **불가** |
| Redfish | `_rf_attempt.status != 'failed'`              | redfish_gather + failed_when:false     | **가능(401 한정)** |

Linux/Windows/ESXi 는 인증 거부와 transport 실패 / 권한 부족 / 제한 쉘 / 모듈 오류를
구조적으로 구분할 필드가 없다. 남는 단서는 `msg` 문자열뿐이고 문자열 파싱은 금지(§18)다.
→ `auth_success` 는 `null` 을 유지한다.

Redfish 만 `auth_evidence.first_auth_status`(정수)로 401 을 구조적으로 확인할 수 있다.

본 테스트는 위 결론이 **코드에서 다시 어긋나지 않도록** 고정한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

PROBE_FILES = {
    "linux/windows": "os-gather/tasks/try_one_credential.yml",
    "esxi": "esxi-gather/tasks/try_one_credential.yml",
    "redfish": "redfish-gather/tasks/try_one_account.yml",
}

# §18 — 인증 실패를 새로 확정하는 데 쓰면 안 되는 문자열 판정 패턴
_STRING_PARSING_PATTERNS = (
    r"'(Permission denied|Authentication failed|InvalidLogin|Unauthorized|incorrect password)'\s+in\s",
    r'"(Permission denied|Authentication failed|InvalidLogin|Unauthorized)"\s+in\s',
    r"\.msg\s*\|\s*regex_search",
    r"stderr\s*\|\s*regex_search",
    r"search\(\s*'(auth|password|denied)",
)


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("label,rel", list(PROBE_FILES.items()), ids=list(PROBE_FILES))
def test_probe_files_do_not_parse_strings_for_auth(label, rel):
    """§18 — 메시지 substring 으로 인증 실패를 확정하지 않는다."""
    text = _text(rel)
    for pattern in _STRING_PARSING_PATTERNS:
        assert not re.search(pattern, text, re.IGNORECASE), (
            f"[{label}] 문자열 파싱으로 인증 실패를 확정하려 한다: {pattern}"
        )


@pytest.mark.parametrize("label,rel", list(PROBE_FILES.items()), ids=list(PROBE_FILES))
def test_probe_files_do_not_set_auth_success(label, rel):
    """자격 probe 파일이 auth_success 를 직접 만들지 않는다 (판정은 site.yml 단일 지점)."""
    assert "auth_success" not in _text(rel), (
        f"[{label}] auth_success 판정이 분산되면 계약이 깨진다"
    )


def test_credential_attempt_count_unchanged():
    """§16 / §32 — 인증 시도를 늘리지 않는다 (계정 잠금 위험 불변)."""
    os_text = _text("os-gather/tasks/try_one_credential.yml")
    # Linux 는 raw 1회, Windows 는 win_ping 1회. 후보당 probe 태스크는 각 1개다.
    assert os_text.count("ansible.builtin.raw:") == 1
    assert os_text.count("ansible.windows.win_ping:") == 1
    assert "retries:" not in os_text and "until:" not in os_text

    esxi_text = _text("esxi-gather/tasks/try_one_credential.yml")
    assert esxi_text.count("community.vmware.vmware_host_facts:") == 1
    assert "retries:" not in esxi_text and "until:" not in esxi_text

    rf_text = _text("redfish-gather/tasks/try_one_account.yml")
    assert rf_text.count("redfish_gather:") == 1
    assert "retries:" not in rf_text and "until:" not in rf_text
    # 계정 잠금 회피 backoff 는 그대로 유지한다.
    # 2026-08-12: 값을 고정 5초에서 "인증 거부(401) 면 길게 / transport 오류면 종전 5초" 로
    #   나눴다. Dell iDRAC10 IP Blocking 기본값(FailCount=3 / FailWindow=60s)은 5초 간격으로
    #   피할 수 없고, 반대로 timeout·TLS 실패는 실패 카운터를 올리지 않으므로 늘릴 이유가 없다.
    #   source: dell.com/.../idrac10_1.xx_scg/network-security-configuration
    assert "sleep " in rf_text, "lockout backoff 를 제거하면 안 된다"
    assert "_rf_auth_backoff_seconds" in rf_text
    assert "_rf_transport_backoff_seconds | default(5)" in rf_text, (
        "transport 오류의 종전 5초 간격이 사라졌다")


def test_no_extra_diagnostic_login_added():
    """진단 목적의 별도 로그인 태스크가 추가되지 않았는지."""
    for rel in PROBE_FILES.values():
        text = _text(rel)
        assert "diagnostic" not in text.lower()
        assert text.count("register:") <= 3, rel


def test_redfish_auth_evidence_is_structured_not_parsed():
    """§22 — Redfish 만 구조화 status 로 401 을 확인한다."""
    lib = _text("redfish-gather/library/redfish_gather.py")
    assert "def auth_evidence(" in lib
    assert "'first_auth_status'" in lib
    # 후보별 관측은 try_one_account 가 누적하고, 판정은 site.yml 한 곳에서 한다
    probe = _text("redfish-gather/tasks/try_one_account.yml")
    assert "first_auth_status" in probe and "_rf_auth_statuses" in probe
    # 2026-08-12: `[]` 리터럴 → `| default([])`. Phase 1(표준) / Phase 3(복구 후 재수집)
    #   두 번 도는데 매번 비우면 Phase 1 의 401 관측이 사라진다.
    assert "_rf_auth_statuses: \"{{ _rf_auth_statuses | default([]) }}\"" in _text(
        "redfish-gather/tasks/collect_standard.yml"
    )
    # site.yml 은 정수 비교만 한다 (문자열 검색 금지)
    site = _text("redfish-gather/site.yml")
    assert "_rf_auth_statuses" in site
    assert re.search(r"select\('equalto', 401\)", site), (
        "401 판정은 정수 비교여야 한다 (문자열 검색 금지)"
    )
    assert "'HTTP 401' in" not in site and '"HTTP 401" in' not in site


def test_http_403_is_never_treated_as_rejection():
    """§8 / §22 — 403 은 인증 이후 권한 부족일 수 있어 거부로 확정하지 않는다."""
    site = _text("redfish-gather/site.yml")
    # 주석은 제외하고 **실행되는 판정식**만 본다 (주석은 403 을 왜 안 쓰는지 설명한다).
    code_only = "\n".join(
        line for line in site.split("rescue:")[-1].splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "403" not in code_only, (
        "rescue 판정식에 403 이 등장하면 인증 거부로 오분류될 위험"
    )
    lib = _text("common/library/precheck_bundle.py")
    assert "rejected = status == 401" in lib, "Stage 4 도 401 한정이어야 한다"


def test_esxi_probe_still_uses_positive_evidence():
    """ESXi 판정식이 ansible_facts 존재(positive evidence) 기반인지 (Round 17 #2 회귀 방지)."""
    text = _text("esxi-gather/tasks/try_one_credential.yml")
    assert "_e_probe.ansible_facts is defined" in text


def test_os_probe_evaluation_shape_unchanged():
    """Linux/Windows 판정식이 그대로인지 — 이번 Phase 는 판정식을 재설계하지 않는다."""
    text = _text("os-gather/tasks/try_one_credential.yml")
    assert "__auth_ok__" in text
    assert "ping | default('') == 'pong'" in text
    assert "ignore_unreachable: true" in text


def test_probe_files_are_valid_yaml():
    for rel in PROBE_FILES.values():
        docs = list(yaml.safe_load_all(_text(rel)))
        assert docs and docs[0], rel
