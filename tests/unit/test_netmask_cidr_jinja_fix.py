"""Netmask → CIDR 변환 Jinja2 namespace fix 회귀 (cycle 2026-05-07-post).

기존 버그 (gather_network.yml:99 / esxi normalize_network.yml:67):
  - `{% set val = octet | int %}` 가 outer for(octet) iteration 안에서 set
  - 그러나 inner for(bit) 안의 `{% set val = val - bit %}` 가 inner-for 다음
    iteration 에 propagate 안 됨 (Jinja2 default for-scope)
  - /24, /16, /8, /0 같은 all-1 octet mask 는 우연히 정상 (모든 bit 트리거)
  - /23, /30, /22 같은 비표준 mask 는 잘못 계산 (비-FF octet 의 bit 모두 트리거)

Fix: val 을 namespace(val=0) 에 포함 → set ns.val = ns.val - bit

본 테스트는 Python 으로 동일 알고리즘 두 버전 (broken / fixed) 을 재현하고,
다양한 mask 에 대해 fixed 만 정답 반환함을 검증. Jinja2 코드 자체 검증은
별도 ansible playbook 시뮬레이션 필요.
"""
from __future__ import annotations

import pytest


def netmask_to_cidr_broken(nm: str) -> int:
    """기존 버그 algorithm — inner for set 미전파."""
    bits = 0
    for octet_str in nm.split('.'):
        val = int(octet_str)  # outer for iteration scope
        for bit in [128, 64, 32, 16, 8, 4, 2, 1]:
            if val >= bit:
                bits += 1
                # val = val - bit 가 다음 inner iteration 에 미반영 (Jinja2 버그)
                # Python 으로는 정상 동작하므로 의도적으로 누락
        # 즉 outer for 의 val 을 inner for 가 자기 iteration 결과로 update 안 함
    return bits


def netmask_to_cidr_fixed(nm: str) -> int:
    """Fix algorithm — namespace val (Jinja namespace 등가)."""
    bits = 0
    val = 0
    for octet_str in nm.split('.'):
        val = int(octet_str)
        for bit in [128, 64, 32, 16, 8, 4, 2, 1]:
            if val >= bit:
                bits += 1
                val = val - bit
    return bits


@pytest.mark.parametrize(
    "netmask,expected_cidr",
    [
        ("255.255.255.255", 32),
        ("255.255.255.0", 24),    # /24 (most common)
        ("255.255.0.0", 16),
        ("255.0.0.0", 8),
        ("0.0.0.0", 0),
        ("255.255.254.0", 23),    # /23 (non-trivial)
        ("255.255.252.0", 22),    # /22
        ("255.255.255.192", 26),
        ("255.255.255.240", 28),
        ("255.255.255.252", 30),  # /30 (point-to-point)
        ("255.255.255.248", 29),
        ("128.0.0.0", 1),         # /1 (extreme)
        ("192.0.0.0", 2),
        ("224.0.0.0", 3),
    ],
)
def test_fixed_algorithm_correct(netmask: str, expected_cidr: int) -> None:
    """Fixed algorithm 이 모든 mask 에 대해 정답 반환."""
    assert netmask_to_cidr_fixed(netmask) == expected_cidr, (
        f"{netmask}: expected /{expected_cidr}, "
        f"got /{netmask_to_cidr_fixed(netmask)}"
    )


@pytest.mark.parametrize(
    "netmask,broken_result,correct_cidr",
    [
        ("255.255.254.0", 24, 23),   # /23 → /24 잘못 계산
        ("255.255.255.252", 32, 30), # /30 → /32 잘못 계산
        ("255.255.255.192", 32, 26), # /26 → /32 잘못 계산
        ("128.0.0.0", 8, 1),         # /1 → /8 잘못 계산
    ],
)
def test_broken_algorithm_demonstrates_bug(
    netmask: str, broken_result: int, correct_cidr: int
) -> None:
    """기존 버그 algorithm 이 비표준 mask 잘못 계산함을 명시 — 회귀 차단."""
    actual = netmask_to_cidr_broken(netmask)
    assert actual == broken_result, (
        f"broken algorithm 동작 변경됨? {netmask}: 예상 /{broken_result}, 실제 /{actual}"
    )
    assert actual != correct_cidr, (
        f"우연히 정답 반환? {netmask}: 정답 /{correct_cidr}, broken /{actual}"
    )


def test_common_24_works_in_both() -> None:
    """가장 흔한 /24 는 두 algorithm 모두 정상 (회귀 사고가 늦게 발견된 이유)."""
    assert netmask_to_cidr_broken("255.255.255.0") == 24
    assert netmask_to_cidr_fixed("255.255.255.0") == 24
