"""ESXi system.hostname / fqdn — IPv4 리터럴은 호스트 이름이 아니다 (2026-10-19 B-8).

종전 normalize_system.yml 은 dnsConfig.hostName 이 없으면 ansible_hostname 으로 떨어지고 첫 라벨만 잘랐다 — vmware_host_facts 가
호스트 이름 자리에 IP('10.100.64.2') 를 주면 hostname '10' · fqdn '10.100.64.2' 가 나갔다 (jinja2 native 에서는 hostname 이 int 10).
정책: IP 를 hostname 으로 쓰지 않는다 → 후보가 IPv4 꼴이면 hostname/fqdn 모두 null. dnsConfig.hostName 우선순위는 그대로다.

test_esxi_serial_npar.run_normalize_system 으로 실제 set_fact 세 task 를 순서대로 렌더한다.
"""
from __future__ import annotations

import pytest

from tests.unit.test_esxi_serial_npar import run_normalize_system


def _identity(ctx):
    sysfrag = ctx["_data_fragment"]["system"]
    return ctx["_e_sys_short"], ctx["_e_sys_domain"], ctx["_e_sys_fqdn"], sysfrag["hostname"], sysfrag["fqdn"]


@pytest.mark.parametrize("ip", ["10.100.64.2", "192.168.0.1", "1.2.3.4", " 10.100.64.2 "])
def test_ipv4_ansible_hostname_without_dnsconfig_gives_null_hostname_and_fqdn(ip):
    ctx = run_normalize_system({"ansible_hostname": ip})
    assert _identity(ctx) == (None, None, None, None, None), _identity(ctx)


def test_fqdn_style_ansible_hostname_is_split_as_before():
    ctx = run_normalize_system({"ansible_hostname": "esxi01.lab.local"})
    assert _identity(ctx) == ("esxi01", "lab.local", "esxi01.lab.local", "esxi01", "esxi01.lab.local")


def test_short_ansible_hostname_without_domain_keeps_fqdn_null():
    ctx = run_normalize_system({"ansible_hostname": "esxi02"})
    assert _identity(ctx) == ("esxi02", None, None, "esxi02", None)


def test_dnsconfig_hostname_path_is_unchanged_and_wins_over_an_ip_fallback():
    """dnsConfig.hostName / domainName 이 있으면 종전 그대로 그 값 — ansible_hostname 이 IP 라도 영향 없다."""
    ctx = run_normalize_system({"ansible_hostname": "10.100.64.2"}, raw_host={"hostname": "esxi01", "domain_name": "lab.local"})
    assert _identity(ctx) == ("esxi01", "lab.local", "esxi01.lab.local", "esxi01", "esxi01.lab.local")


def test_dnsconfig_hostname_without_domain_does_not_borrow_a_domain_from_an_ip():
    """도메인 fallback 도 IP 의 '.' 뒷부분('100.64.2')을 도메인으로 쓰지 않는다."""
    ctx = run_normalize_system({"ansible_hostname": "10.100.64.2"}, raw_host={"hostname": "esxi01"})
    assert _identity(ctx) == ("esxi01", None, None, "esxi01", None)


def test_dns_info_domain_still_applies_when_hostname_falls_back_to_a_real_name():
    ctx = run_normalize_system({"ansible_hostname": "esxi03"}, raw_dns={"esxi03": {"domain_name": "lab.local"}})
    assert _identity(ctx) == ("esxi03", "lab.local", "esxi03.lab.local", "esxi03", "esxi03.lab.local")


def test_a_name_that_merely_contains_an_ip_is_not_an_ipv4_literal():
    """글자가 섞이면 IPv4 리터럴이 아니다 — 종전 분리 규칙 그대로 (가드는 4 그룹 숫자 전체 일치에만 걸린다)."""
    ctx = run_normalize_system({"ansible_hostname": "esxi-10.100.64.2"})
    assert (ctx["_e_sys_short"], ctx["_e_sys_domain"], ctx["_e_sys_fqdn"]) == ("esxi-10", "100.64.2", "esxi-10.100.64.2")


def test_everything_missing_is_null_not_the_target_ip():
    ctx = run_normalize_system({}, raw_host={}, raw_dns={})
    assert _identity(ctx) == (None, None, None, None, None)
