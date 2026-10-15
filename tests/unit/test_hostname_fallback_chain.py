"""hostname fallback chain 회귀 (2026-06-16 정책).

build_output.yml 의 hostname 해석 우선순위를 잠근다:
    System.HostName(OS) → system.fqdn → BMC NetworkProtocol.HostName → null

핵심 불변식:
  - IP 는 어느 단계에도 들어가지 않는다 (이전 ip-fallback 폐지).
  - System 출처 있으면 hostname_source='system', 없고 BMC 있으면 'bmc', 둘 다 없으면 'none'.
  - Cisco CIMC 처럼 System 없음 + BMC NetworkProtocol.HostName=null → hostname=null (graceful).

build_output.yml 의 실제 Jinja2 표현식을 추출해 렌더링 — 정본과 테스트가 분리되지 않도록.
(Ansible 미실행 환경에서 build_output 의 hostname 로직만 결정적 회귀.)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

jinja2 = pytest.importorskip("jinja2")

REPO = Path(__file__).resolve().parents[2]
BUILD_OUTPUT = REPO / "common" / "tasks" / "normalize" / "build_output.yml"


def _extract_expressions():
    text = BUILD_OUTPUT.read_text(encoding="utf-8")
    h = re.search(r"_out_hostname:\s*>-\n(.*?)\n\s*_out_hostname_source:", text, re.S)
    s = re.search(r"_out_hostname_source:\s*>-\n(.*?)\n\n- name:", text, re.S)
    assert h and s, "build_output.yml 에서 _out_hostname / _out_hostname_source 표현식 추출 실패"
    return h.group(1).strip(), s.group(1).strip()


_HOST_EXPR, _SRC_EXPR = _extract_expressions()
_ENV = jinja2.Environment()
_T_HOST = _ENV.from_string(_HOST_EXPR)
_T_SRC = _ENV.from_string(_SRC_EXPR)


def _resolve(system_fqdn, bmc_network_hostname):
    md = {"system": {"fqdn": system_fqdn}, "bmc": {"network_hostname": bmc_network_hostname}}
    host = _T_HOST.render(_merged_data=md).strip()
    host = None if host == "None" else host
    source = _T_SRC.render(_merged_data=md).strip()
    return host, source


# (system.fqdn, bmc.network_hostname, expected_hostname, expected_source)
CASES = [
    ("DELL01", "iDRAC-J0KV603", "DELL01", "system"),            # System 우선
    (None, "ILOSGHD3KHHRP", "ILOSGHD3KHHRP", "bmc"),            # System 없음 → BMC
    (None, "XCC-7DGD-J902E57T", "XCC-7DGD-J902E57T", "bmc"),    # Lenovo XCC
    (None, "RMC7CA62A413692", "RMC7CA62A413692", "bmc"),       # CSUS RMC
    ("m10mesdb11", "M10MESDB11-RMC", "m10mesdb11", "system"),  # 둘 다 있으면 System
    ("C220-FCH2116V1V0", None, "C220-FCH2116V1V0", "system"),  # Cisco: System 보유
    (None, None, None, "none"),                                # Cisco형: 둘 다 없음 → null
    ("", "", None, "none"),                                     # 빈문자열 → null 정규화
    ("", "iLOABC", "iLOABC", "bmc"),                           # System 빈값 → BMC
]


@pytest.mark.parametrize("sys_fqdn,bmc_h,exp_host,exp_src", CASES,
                         ids=[c[2] or "null" for c in CASES])
def test_hostname_chain(sys_fqdn, bmc_h, exp_host, exp_src):
    host, source = _resolve(sys_fqdn, bmc_h)
    assert host == exp_host, f"hostname {host!r} != 기대 {exp_host!r} (sys={sys_fqdn!r} bmc={bmc_h!r})"
    assert source == exp_src, f"source {source!r} != 기대 {exp_src!r}"


def test_hostname_never_ip():
    """어떤 입력에도 hostname 에 IP 가 새지 않는다 (이전 ip-fallback 회귀 차단).

    build_output 의 hostname 표현식은 _merged_data 만 본다 — _out_ip 를 참조하지 않으므로
    구조적으로 IP 가 들어갈 수 없다. 표현식 본문에 _out_ip 가 없음을 직접 검증한다.
    """
    assert "_out_ip" not in _HOST_EXPR, (
        "hostname 표현식이 _out_ip 를 참조 — ip-fallback 잔재 (정책 위반)"
    )
    # System/BMC 둘 다 없을 때 ip 형태 문자열이 아니라 null 이어야 함
    host, source = _resolve(None, None)
    assert host is None and source == "none"
