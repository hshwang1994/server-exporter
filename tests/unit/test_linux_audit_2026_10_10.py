"""2026-10-10 감사 — Linux 채널 결함 고정 (plan §4.5). 실제 raw 스크립트(POSIX sh 샌드박스)와 실제 set_fact 템플릿(jinja2_native)을 쓴다.

LX-F08  기본 경로를 토큰(via/dev)으로 읽는다 — ECMP(nexthop 줄) · nhid · via 없는 경로 · IPv6 (GW4|/GW6| 줄, 종전 GW=/GW_DEV= 유지).
LX-F02  기본 경로가 없는 host 의 default_gateways 는 [] 다 ('None' 문자열 아님 — WSL ansible-core 2.20.7 재현, raw/x2_lxf02_probe.txt).
LX-F10  lspci 오류는 LSPCI_ERR= 표식(stdout)으로 본다 — use_tty 로 register.stderr 는 늘 비어 있었다.
LX-F01  system raw · runtime 이 비특권/특권으로 나뉘어 become 실패가 비특권 값을 삼키지 않는다 — 식별자 진단(raw 경로) · 방화벽 errors[] 1건.
D-03    Linux firewall_state = 유효 정책 (firewalld active / ufw status / nft·iptables 입력 체인 정책 drop|reject 또는 규칙 ≥1).
LX-F04  multipath 경로 디스크는 1개로 접는다 (MPATH| 줄 또는 같은 WWN·크기) — 종전에는 경로마다 physical_disks 1개.
LX-F06  구형 lscpu(<2.34) 의 인스턴스당 캐시 값은 sysfs 인스턴스 수로 소켓당 합계를 만든다 (AMD CCX).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytest.importorskip("jinja2")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from linux_raw_harness import (  # noqa: E402
    LINUX_TASKS, NETWORK_YML, SYSTEM_YML, RunResult, Sandbox, ansible_env, iter_tasks, load_tasks, raw_script,
    render_tree, run_task_file, set_fact_args,
)
from test_os_network_render import _render_raw_path  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from identity_normalizer import normalize_mac  # noqa: E402
from network_topology import build_linux_network, merge_linux_addresses  # noqa: E402

STOR_YML = LINUX_TASKS / "gather_storage.yml"
CPU_YML = LINUX_TASKS / "gather_cpu.yml"
DIAG_YML = LINUX_TASKS / "build_identifier_diagnostics.yml"


@pytest.fixture
def sbx(tmp_path):
    return Sandbox(tmp_path)


def _network_raw() -> str:
    """network raw gather 본문 — 토폴로지 collector 주입 자리는 비운다(이 시험의 대상 밖)."""
    task = next(t for t in iter_tasks(load_tasks(NETWORK_YML))
                if "raw gather" in (t.get("name") or "") and "ansible.builtin.raw" in t)
    return task["ansible.builtin.raw"].replace("{{ _l_net_collector }}", "")


def _ip_shim(sbx: Sandbox, outputs: dict[str, str]) -> None:
    """가짜 ip: 인자 문자열 → 출력. 맞는 것이 없으면 빈 출력 rc 0 (실제 ip 처럼 조용히)."""
    body = 'case "$*" in\n'
    for args, out in outputs.items():
        path = sbx.data_file("ip_" + re.sub(r"[^A-Za-z0-9]+", "_", args) + ".txt", out)
        body += f"  '{args}') cat '{path}' ;;\n"
    body += "esac\nexit 0\n"
    sbx.shim_cmd("ip", body)


# ═══════════════════════════════════════════════════════════════════════════
# LX-F08 — raw 스크립트: 기본 경로 토큰 파싱
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("route_out,route6_out,gw4,gw6,legacy", [
    ("default via 10.0.0.1 dev eth0 proto dhcp src 10.0.0.5 metric 100\n", "", [["10.0.0.1", "eth0"]], [], ("10.0.0.1", "eth0")),
    # via 없는 점대점 경로 — 종전 awk $3 은 장치명(ppp0)을 게이트웨이로 냈다
    ("default dev ppp0 scope link\n", "", [["", "ppp0"]], [], ("", "ppp0")),
    # iproute2 nexthop 객체 — 종전 awk $3 은 nhid 값(7)을 게이트웨이로 냈다
    ("default nhid 7 via 10.0.0.1 dev eth0 proto static metric 20\n", "", [["10.0.0.1", "eth0"]], [], ("10.0.0.1", "eth0")),
    # ECMP — 종전에는 첫 줄(default proto static)만 읽어 게이트웨이가 없었다
    ("default proto static\n\tnexthop via 10.0.0.1 dev eth0 weight 1\n\tnexthop via 10.0.0.2 dev eth1 weight 1\n", "",
     [["10.0.0.1", "eth0"], ["10.0.0.2", "eth1"]], [], ("10.0.0.1", "eth0")),
    # 기본 경로 둘(metric) + IPv6
    ("default via 10.0.0.1 dev eth0 metric 100\ndefault via 10.0.1.1 dev eth1 metric 200\n",
     "default via fe80::1 dev eth0 proto ra metric 1024 expires 1795sec hoplimit 64 pref medium\n",
     [["10.0.0.1", "eth0"], ["10.0.1.1", "eth1"]], [["fe80::1", "eth0"]], ("10.0.0.1", "eth0")),
    ("", "", [], [], None),
])
def test_raw_script_emits_every_default_route_as_gw_rows(sbx, route_out, route6_out, gw4, gw6, legacy):
    _ip_shim(sbx, {"route show default": route_out, "-6 route show default": route6_out})
    res = sbx.run(_network_raw())
    assert res.rc == 0, res.stderr[-500:]
    assert res.rows("GW4") == gw4
    assert res.rows("GW6") == gw6
    if legacy is None:
        assert res.marker("GW") is None and res.marker("GW_DEV") is None
    else:
        assert (res.marker("GW"), res.marker("GW_DEV")) == legacy   # 종전 표식은 첫 IPv4 경로


# ═══════════════════════════════════════════════════════════════════════════
# LX-F10 — lspci stderr → LSPCI_ERR= 표식
# ═══════════════════════════════════════════════════════════════════════════
def test_raw_script_marks_lspci_error_on_stdout(sbx):
    _ip_shim(sbx, {})
    sbx.shim_cmd("lspci", 'echo "lspci: Unable to load libkmod resources: error -2" >&2\n'
                          'echo \'00:1f.6 "Ethernet controller" "Intel Corporation" "Ethernet Connection (7) I219-LM" -r10 "Lenovo" "Device 3301"\'\n'
                          'exit 0\n')
    res = sbx.run(_network_raw())
    assert res.rc == 0
    assert res.marker("LSPCI_ERR") == "lspci: Unable to load libkmod resources: error -2"
    assert res.rows("ADAPTER")[0][:3] == ["00:1f.6", "Intel Corporation", "Ethernet Connection (7) I219-LM"]
    assert sbx.leftover_tmp() == [], "lspci stderr 임시 파일을 지우지 않았다"


def test_raw_script_has_no_lspci_error_marker_when_lspci_is_quiet(sbx):
    _ip_shim(sbx, {})
    sbx.shim_cmd("lspci", 'exit 0\n')
    res = sbx.run(_network_raw())
    assert res.marker("LSPCI_ERR") is None


# ═══════════════════════════════════════════════════════════════════════════
# LX-F08 / LX-F02 — 템플릿 체인 (jinja2_native, StrictUndefined)
# ═══════════════════════════════════════════════════════════════════════════
def _native_chain(lines: list[str]) -> dict:
    """production set_fact 체인을 Ansible 과 같은 NativeEnvironment 로 렌더한다 — 'None' 문자열 결함(LX-F02) 이 보이는 환경."""
    env = ansible_env()
    env.filters.update({"combine": lambda d, o, **_k: {**(d or {}), **(o or {})}, "build_linux_network": build_linux_network,
                        "merge_linux_addresses": merge_linux_addresses, "normalize_mac": normalize_mac})
    reg = RunResult(0, "".join(ln + "\n" for ln in lines), "").register()
    ctx = {"_l_net_raw": reg}
    parse = set_fact_args(NETWORK_YML, "parse raw")
    for var in ("_l_raw_dns", "_l_raw_gw", "_l_raw_gw_dev", "_l_raw_gw_rows", "_l_raw_ipv6_by_dev", "_l_raw_adapters", "_l_raw_ifaces"):
        ctx[var] = render_tree(env, parse[var], ctx)
    ctx["_l_norm_interfaces_raw"] = render_tree(env, set_fact_args(NETWORK_YML, "raw mark primary")["_l_norm_interfaces_raw"], ctx)
    ctx["_l_net_topo_raw"] = render_tree(env, set_fact_args(NETWORK_YML, "normalize topology (raw)")["_l_net_topo_raw"], ctx)
    ctx["_l_net_summary_r"] = render_tree(env, set_fact_args(NETWORK_YML, "compute summary groups (raw)")["_l_net_summary_r"], ctx)
    ctx["_l_net_raw_ok"] = render_tree(env, set_fact_args(NETWORK_YML, "raw 수집 성공 판정")["_l_net_raw_ok"], ctx)
    frag = set_fact_args(NETWORK_YML, "build fragment (raw)")
    net = render_tree(env, frag["_data_fragment"]["network"], ctx)
    net["_errors"] = render_tree(env, frag["_errors_fragment"], ctx)
    return net


IF_LINES = ["NIC|eth0|virtio_net||", "NIC|eth1|virtio_net||", "DNS=10.0.0.53",
            "IF=eth0|52:54:00:12:34:56|1500|1000|up|10.0.0.5|24", "IF6=eth0|2001:db8::5|64|global",
            "IF=eth1|52:54:00:12:34:57|1500|1000|up|10.0.1.5|24", "IF6=eth1|fe80::5054:ff:fe12:3457|64|link"]


def _addr(net, iface, family):
    i = next(x for x in net["interfaces"] if x["name"] == iface)
    return next(a for a in i["addresses"] if a["family"] == family)


def test_no_default_route_renders_empty_gateways_not_the_string_none():
    net = _native_chain(IF_LINES)
    assert net["default_gateways"] == []
    assert _addr(net, "eth0", "ipv4")["gateway"] is None and _addr(net, "eth0", "ipv6")["gateway"] is None
    assert all(i["is_primary"] is False for i in net["interfaces"])
    assert net["_errors"] == []


def test_ecmp_and_ipv6_default_routes_reach_every_interface():
    lines = IF_LINES + ["GW4|10.0.0.1|eth0", "GW4|10.0.1.1|eth1", "GW=10.0.0.1", "GW_DEV=eth0", "GW6|fe80::1|eth0"]
    net = _native_chain(lines)
    assert net["default_gateways"] == [{"family": "ipv4", "address": "10.0.0.1"}, {"family": "ipv4", "address": "10.0.1.1"},
                                       {"family": "ipv6", "address": "fe80::1"}]
    assert _addr(net, "eth0", "ipv4")["gateway"] == "10.0.0.1" and _addr(net, "eth1", "ipv4")["gateway"] == "10.0.1.1"
    assert _addr(net, "eth0", "ipv6")["gateway"] == "fe80::1" and _addr(net, "eth1", "ipv6")["gateway"] is None
    assert {i["name"] for i in net["interfaces"] if i["is_primary"]} == {"eth0", "eth1"}


def test_point_to_point_default_route_marks_primary_without_an_address():
    net = _native_chain(IF_LINES + ["GW4||eth1", "GW=", "GW_DEV=eth1"])
    assert net["default_gateways"] == []
    assert _addr(net, "eth1", "ipv4")["gateway"] is None
    assert {i["name"] for i in net["interfaces"] if i["is_primary"]} == {"eth1"}


def test_legacy_gw_markers_without_rows_still_work():
    """옛 캡처(GW=/GW_DEV= 만) 도 같은 결과 — tests/fixtures/os/net 의 실장비 stdout 이 그 형식이다."""
    net = _native_chain(IF_LINES + ["GW=10.0.0.1", "GW_DEV=eth0"])
    assert net["default_gateways"] == [{"family": "ipv4", "address": "10.0.0.1"}]
    assert _addr(net, "eth0", "ipv4")["gateway"] == "10.0.0.1"
    assert next(i for i in net["interfaces"] if i["name"] == "eth0")["is_primary"] is True


def test_lspci_error_marker_becomes_one_warning_only_when_section_succeeded():
    net = _native_chain(IF_LINES + ["LSPCI_ERR=pcilib: Cannot open /sys/bus/pci/devices/0000:3b:00.0/config"])
    assert len(net["_errors"]) == 1
    err = net["_errors"][0]
    assert err["section"] == "network" and err["message"] == "네트워크 카드 상세 정보 중 일부를 수집하지 못했습니다. 수집 계정의 권한을 확인하세요."
    assert err["detail"] == "source=lspci; stderr=pcilib: Cannot open /sys/bus/pci/devices/0000:3b:00.0/config"
    # 섹션 자체가 실패면 lspci 경고는 덧붙이지 않는다 (종전과 같은 1건)
    failed = _native_chain(["LSPCI_ERR=boom"])
    assert len(failed["_errors"]) == 1 and "cause=no_interface_and_no_dns" in failed["_errors"][0]["detail"]


def test_plain_environment_render_matches_for_the_reference_capture():
    """기존 render 하네스(일반 Environment)에서도 실장비 캡처(RHEL 8.10)의 게이트웨이가 그대로다."""
    stdout = (REPO / "tests" / "fixtures" / "os" / "net" / "rhel810_rawpath_stdout.txt").read_text(encoding="utf-8")
    net = _render_raw_path(stdout)
    assert net["default_gateways"] == [{"family": "ipv4", "address": "10.100.64.254"}]   # 캡처의 GW= 값 그대로


# ═══════════════════════════════════════════════════════════════════════════
# LX-F01 — system raw 분리 · parse 병합 · 특권 실패 진단
# ═══════════════════════════════════════════════════════════════════════════
def _system_raw_tasks():
    return [t for t in iter_tasks(load_tasks(SYSTEM_YML)) if "ansible.builtin.raw" in t]


def test_system_raw_tasks_are_split_by_privilege():
    raws = {t["name"]: t for t in _system_raw_tasks()}
    unpriv = raws["linux | system | raw gather (os-release/uname/hostname/dmi)"]
    priv = raws["linux | system | raw gather (privileged dmi + dmidecode collector)"]
    assert unpriv.get("become") is None and "{{ _l_dmi_collector }}" not in unpriv["ansible.builtin.raw"]
    assert "sudo" not in unpriv["ansible.builtin.raw"], "비특권 태스크는 sudo 를 부르지 않는다"
    assert priv.get("become") is True and "{{ _l_dmi_collector }}" in priv["ansible.builtin.raw"]
    assert priv["register"] == "_l_raw_priv_result" and unpriv["register"] == "_l_raw_sys_result"
    rt = raws["linux | system | gather runtime (timezone/ntp/listen/swap)"]
    fw = raws["linux | system | gather runtime firewall (privileged)"]
    assert rt.get("become") is None and "FW_TOOL" not in rt["ansible.builtin.raw"] and rt["register"] == "_l_runtime_raw"
    assert fw.get("become") is True and fw["register"] == "_l_runtime_fw_raw"
    for t in (unpriv, priv, rt, fw):
        assert t.get("failed_when") is False and t.get("no_log") is True


def _parse_sys(unpriv_lines, priv_lines):
    env = ansible_env()
    args = set_fact_args(SYSTEM_YML, "parse raw results")
    ctx = {"_l_raw_sys_result": RunResult(0, "".join(l + "\n" for l in unpriv_lines), "").register(),
           "_l_raw_priv_result": (RunResult(0, "".join(l + "\n" for l in priv_lines), "").register() if priv_lines is not None
                                  else {"failed": False, "msg": "Incorrect sudo password"})}
    return {k: render_tree(env, v, ctx) for k, v in args.items()}


UNPRIV = ["OS_ID=rhel", "OS_VERSION=9.4", "KERNEL=5.14.0", "NODENAME=db1", "DMI_PRODUCT_SERIAL=", "DMI_PRODUCT_UUID=",
          "DMI_SYS_VENDOR=Dell Inc.", "DMI_PRODUCT_NAME=PowerEdge R760", "DMI_BIOS_VERSION=2.3.5", "DMI_BIOS_DATE=09/10/2024"]
PRIV = ["DMI_PRODUCT_SERIAL=GSBPK54", "DMI_PRODUCT_UUID=4c4c4544-0053-4210-8050-c7c04f4b3534", "DMI_SYS_VENDOR=Dell Inc.",
        "DMI_PRODUCT_NAME=PowerEdge R760", "DMI_BIOS_VERSION=2.3.5", "DMI_BIOS_DATE=09/10/2024", "DMI_MEM_BEGIN", "MEM_TOTAL_KB=1", "DMI_MEM_END"]


def test_parse_merges_privileged_values_over_unprivileged_ones():
    out = _parse_sys(UNPRIV, PRIV)
    sys_ = out["_l_raw_sys"]
    assert sys_["OS_ID"] == "rhel" and sys_["NODENAME"] == "db1"
    assert sys_["DMI_PRODUCT_SERIAL"] == "GSBPK54" and sys_["DMI_PRODUCT_UUID"] == "4c4c4544-0053-4210-8050-c7c04f4b3534"
    assert out["_l_raw_priv_failed"] is False


def test_become_failure_keeps_unprivileged_values_and_flags_privileged_failure():
    out = _parse_sys(UNPRIV, None)
    sys_ = out["_l_raw_sys"]
    assert sys_["OS_ID"] == "rhel" and sys_["DMI_SYS_VENDOR"] == "Dell Inc." and sys_["DMI_PRODUCT_SERIAL"] == ""
    assert out["_l_raw_priv_failed"] is True


def test_privileged_empty_value_does_not_erase_an_unprivileged_one():
    out = _parse_sys(UNPRIV + ["DMI_BIOS_VERSION=2.3.5"], ["DMI_PRODUCT_SERIAL=S1", "DMI_BIOS_VERSION="])
    assert out["_l_raw_sys"]["DMI_BIOS_VERSION"] == "2.3.5" and out["_l_raw_sys"]["DMI_PRODUCT_SERIAL"] == "S1"


def _diag(ctx):
    env = ansible_env()
    task = load_tasks(DIAG_YML)[0]
    dctx = dict(ctx)
    dctx.update(task.get("vars") or {})
    assert "when" not in task, "식별자 진단은 두 경로 모두 돈다 (LX-F01)"
    return render_tree(env, task["ansible.builtin.set_fact"]["_l_id_diagnostics"], dctx)


def test_raw_path_privileged_failure_yields_privilege_sentences():
    diags = _diag({"_l_python_mode": "raw_forced", "_l_serial_val": None, "_l_uuid_val": None, "_l_raw_priv_failed": True})
    assert [d["message"] for d in diags] == ["시스템 제조번호를 읽을 수 없습니다. 수집 계정의 권한을 확인하세요.",
                                             "시스템 고유 식별자를 읽을 수 없습니다. 수집 계정의 권한을 확인하세요."]
    assert all("cause=insufficient_privilege; tried=dmi_sysfs,become" in d["detail"] for d in diags)


def test_raw_path_privileged_read_without_values_yields_absent_sentences():
    diags = _diag({"_l_python_mode": "raw_forced", "_l_serial_val": None, "_l_uuid_val": "4c4c4544-0053-4210-8050-c7c04f4b3534",
                   "_l_raw_priv_failed": False})
    assert [d["message"] for d in diags] == ["대상이 시스템 제조번호를 제공하지 않습니다."]
    assert "cause=identifier_not_available" in diags[0]["detail"]


def test_raw_path_with_identifiers_has_no_diagnostics():
    assert _diag({"_l_python_mode": "raw_forced", "_l_serial_val": "S", "_l_uuid_val": "U", "_l_raw_priv_failed": False}) == []


def test_python_path_diagnostics_unchanged():
    base = {"_l_python_mode": "python_ok", "_l_serial_val": None, "_l_uuid_val": None, "_l_dmi_fallback_failed": True,
            "_l_dmi_serial_direct": {"rc": 1}, "_l_dmi_uuid_direct": {"rc": 1}}
    diags = _diag(base)
    assert [d["detail"] for d in diags] == ["field=serial_number; cause=insufficient_privilege; tried=setup_fact,dmi_direct",
                                            "field=system_uuid; cause=insufficient_privilege; tried=setup_fact,dmi_direct"]


# ═══════════════════════════════════════════════════════════════════════════
# LX-F01 / D-03 — runtime: 특권 방화벽 분리
# ═══════════════════════════════════════════════════════════════════════════
def _runtime(rt_lines, fw_lines):
    env = ansible_env()
    env.filters["unique"] = lambda seq: list(dict.fromkeys(seq))
    args = set_fact_args(SYSTEM_YML, "parse runtime")
    ctx = {"_l_runtime_raw": {"stdout_lines": rt_lines},
           "_l_runtime_fw_raw": ({"stdout_lines": fw_lines} if fw_lines is not None else {"failed": False, "msg": "Missing sudo password"})}
    out = {k: render_tree(env, v, ctx) for k, v in args.items()}
    frag = set_fact_args(SYSTEM_YML, "build fragment")
    fctx = {"_l_runtime": out["_l_runtime"], "_l_runtime_fw_failed": out["_l_runtime_fw_failed"], "_l_id_diagnostics": [],
            "_l_sys_ok": True, "_l_hw_ok": True, "_l_fb": {}, "_l_hostname_short": "h", "_l_fqdn": None, "_l_hosting_type": "baremetal",
            "_l_serial_val": "S", "_l_uuid_val": None, "_l_hw_vendor": "V", "_l_hw_model": "M", "_l_hw_bios_version": "1", "_l_hw_bios_date": None}
    env.filters["normalize_uuid"] = lambda v: v
    runtime = render_tree(env, frag["_data_fragment"]["system"]["runtime"], fctx)
    errors = render_tree(env, frag["_errors_fragment"], fctx)
    return out, runtime, errors


RT = ["TZ=Asia/Seoul", "NTPSYNC=yes", "NTPACTIVE=yes", "PORTS_BEGIN", "22", "PORTS_END", "SWAP_TOTAL=0", "SWAP_USED=0", "SWAP_FREE=0"]


def test_firewall_from_privileged_register_and_rest_from_unprivileged():
    out, runtime, errors = _runtime(RT, ["FW_TOOL=nftables", "FW_STATE=inactive"])
    assert out["_l_runtime"]["TZ"] == "Asia/Seoul" and out["_l_runtime"]["PORTS"] == ["22"]
    assert out["_l_runtime_fw_failed"] is False
    assert runtime["firewall_tool"] == "nftables" and runtime["firewall_state"] == "inactive" and runtime["timezone"] == "Asia/Seoul"
    assert errors == []


def test_firewall_privileged_failure_gives_nulls_and_one_error():
    out, runtime, errors = _runtime(RT, None)
    assert out["_l_runtime_fw_failed"] is True
    assert runtime["timezone"] == "Asia/Seoul" and runtime["listening_ports"] == ["22"]
    assert runtime["firewall_tool"] is None and runtime["firewall_state"] is None
    assert len(errors) == 1
    assert errors[0]["message"] == "서버 운영 정보 중 방화벽 상태를 수집하지 못했습니다. 수집 계정의 권한을 확인하세요."
    assert errors[0]["detail"] == "field=runtime.firewall_tool,runtime.firewall_state; cause=privileged_read_failed; tried=become"


def _fw_script() -> str:
    return raw_script(SYSTEM_YML, "gather runtime firewall (privileged)")


def _shim_fw(sbx: Sandbox, *, firewalld=None, ufw=None, nft=None, iptables=None):
    """도구 존재 여부와 출력을 shim 으로 — 없는 도구는 PATH 에 없다(command -v 실패)."""
    if firewalld is not None:
        sbx.shim_cmd("firewall-cmd", "exit 0\n")
        sbx.shim_cmd("systemctl", f'if [ "$1" = "is-active" ] && [ "$2" = "firewalld" ]; then echo {firewalld}; fi\nexit 0\n')
    else:
        sbx.shim_cmd("systemctl", "exit 3\n")
    if ufw is not None:
        sbx.shim_cmd("ufw", f'printf "%s\\n" "Status: {ufw}"\nexit 0\n')
    if nft is not None:
        path = sbx.data_file("nft.txt", nft)
        sbx.shim_cmd("nft", f"cat '{path}'\nexit 0\n")
    if iptables is not None:
        path = sbx.data_file("ipt.txt", iptables)
        sbx.shim_cmd("iptables", f"cat '{path}'\nexit 0\n")


NFT_DROP = "table inet filter {\n\tchain input {\n\t\ttype filter hook input priority filter; policy drop;\n\t\tct state established,related accept\n\t}\n}\n"
NFT_ACCEPT_RULES = "table inet filter {\n\tchain input {\n\t\ttype filter hook input priority filter; policy accept;\n\t\ttcp dport 22 accept\n\t}\n}\n"
NFT_OPEN = "table ip filter {\n\tchain INPUT {\n\t\ttype filter hook input priority filter; policy accept;\n\t}\n\tchain FORWARD {\n\t\ttype filter hook forward priority filter; policy accept;\n\t}\n}\n"


@pytest.mark.parametrize("label,kw,tool,state", [
    ("firewalld_active", dict(firewalld="active", nft=NFT_OPEN), "firewalld", "active"),
    ("ufw_active", dict(ufw="active", nft=NFT_OPEN), "ufw", "active"),
    ("ufw_inactive", dict(ufw="inactive"), "ufw", "inactive"),
    ("nft_policy_drop", dict(nft=NFT_DROP), "nftables", "active"),
    ("nft_accept_with_rules", dict(nft=NFT_ACCEPT_RULES), "nftables", "active"),
    ("nft_open", dict(nft=NFT_OPEN), "nftables", "inactive"),
    ("nft_empty_ruleset", dict(nft=""), "nftables", "inactive"),
    ("iptables_drop", dict(iptables="-P INPUT DROP\n-A INPUT -i lo -j ACCEPT\n"), "iptables", "active"),
    ("iptables_accept_rules", dict(iptables="-P INPUT ACCEPT\n-A INPUT -p tcp --dport 22 -j ACCEPT\n"), "iptables", "active"),
    # 종전 결함: 설치만 돼 있고 비어 있는 체인(-L 머리말만)도 active 였다
    ("iptables_open", dict(iptables="-P INPUT ACCEPT\n"), "iptables", "inactive"),
    ("no_tool", dict(), "", ""),
])
def test_firewall_state_is_the_effective_policy(sbx, label, kw, tool, state):
    _shim_fw(sbx, **kw)
    res = sbx.run(_fw_script())
    assert res.rc == 0, (label, res.stderr[-300:])
    assert (res.marker("FW_TOOL"), res.marker("FW_STATE")) == (tool, state), label


# ═══════════════════════════════════════════════════════════════════════════
# LX-F04 — multipath 접기
# ═══════════════════════════════════════════════════════════════════════════
def _lsblk_json(devs):
    return json.dumps({"blockdevices": devs})


def _disks(json_text, extra_lines):
    lines = ["LSBLK_BEGIN", json_text, "LSBLK_END", "LSBLK_RC=0", "LSBLK_ERR=", "SYS_BLOCK_COUNT="] + extra_lines
    reg = RunResult(0, "".join(l + "\n" for l in lines), "").register()
    run = run_task_file(STOR_YML, {"_l_stor_raw": reg}, ctx={})
    assert not run.rescued
    return run.ctx["_l_norm_physical_disks"], run.ctx["_data_fragment"]["storage"]["summary"]


SD = lambda name, serial="S1", wwn="0x600a098038303030", size=1099511627776, tran="fc": {  # noqa: E731
    "name": name, "size": size, "type": "disk", "rota": True, "model": "NETAPP LUN", "tran": tran, "serial": serial, "wwn": wwn}


def test_multipath_members_collapse_to_one_disk_named_by_the_mpath_device():
    devs = [SD("sda"), SD("sdb"), SD("sdc", serial="S2", wwn="0x600a098038303031"), SD("sdd", serial="S2", wwn="0x600a098038303031"),
            {"name": "mpatha", "size": 1099511627776, "type": "mpath", "rota": True, "model": None, "tran": None, "serial": None, "wwn": None},
            {"name": "nvme0n1", "size": 960197124096, "type": "disk", "rota": False, "model": "SAMSUNG PM9A3", "tran": "nvme", "serial": "N1", "wwn": "eui.1"}]
    disks, summary = _disks(_lsblk_json(devs), ["MPATH|mpatha|sda sdb", "MPATH|mpathb|sdc sdd", "OSDISK|/dev/sdb"])
    assert [d["device"] for d in disks] == ["/dev/mapper/mpatha", "/dev/mapper/mpathb", "/dev/nvme0n1"]
    mp = disks[0]
    assert mp["id"] == "/dev/mapper/mpatha" and mp["serial"] == "S1" and mp["wwn"] == "0x600a098038303030" and mp["protocol"] == "FibreChannel"
    assert mp["total_mb"] == 1048576 and mp["is_os_disk"] is True          # OS 루트는 경로 sdb 를 거친다
    assert disks[1]["is_os_disk"] is False and disks[2]["is_os_disk"] is False
    assert summary["grand_total_gb"] == 1024 * 2 + 894
    assert sum(g["quantity"] for g in summary["groups"]) == 3


def test_same_wwn_and_size_collapse_even_without_multipath_rows():
    devs = [SD("sda"), SD("sdb"), SD("sdc", serial="S3", wwn="0x600a098038303033")]
    disks, _ = _disks(_lsblk_json(devs), [])
    assert [d["device"] for d in disks] == ["/dev/sda", "/dev/sdc"]      # 두 경로 → 첫 경로 이름으로 1개


def test_disks_without_wwn_or_with_different_sizes_are_not_collapsed():
    devs = [SD("vda", serial=None, wwn=None, size=100, tran="virtio"), SD("vdb", serial=None, wwn=None, size=100, tran="virtio"),
            SD("sdx", wwn="0x5", size=100), SD("sdy", wwn="0x5", size=200)]
    disks, _ = _disks(_lsblk_json(devs), [])
    assert [d["device"] for d in disks] == ["/dev/vda", "/dev/vdb", "/dev/sdx", "/dev/sdy"]


def test_legacy_text_rows_collapse_by_multipath_membership():
    lines = ["LSBLK_BEGIN", "LSBLK_END", "LSBLK_RC=1", "LSBLK_ERR=lsblk: invalid option -- 'J'", "SYS_BLOCK_COUNT=",
             "LSBLK_TXT|sda|1099511627776|disk|1|NETAPP LUN", "LSBLK_TXT|sdb|1099511627776|disk|1|NETAPP LUN",
             "LSBLK_TXT|sdc|500107862016|disk|0|Samsung SSD", "MPATH|mpatha|sda sdb"]
    reg = RunResult(0, "".join(l + "\n" for l in lines), "").register()
    run = run_task_file(STOR_YML, {"_l_stor_raw": reg}, ctx={})
    assert [d["device"] for d in run.ctx["_l_norm_physical_disks"]] == ["/dev/mapper/mpatha", "/dev/sdc"]


def test_raw_script_reads_multipath_membership_from_sysfs_dm():
    script = raw_script(STOR_YML, "raw gather")
    assert "/sys/block/dm-*" in script and 'mpath-*)' in script and 'echo "MPATH|${mp_name}|' in script
    assert not re.search(r"(^|[;&|`$(]\s*)multipath\s", script, re.M), "multipath 명령(권한 필요)을 실행하지 않는다 — sysfs 만"


# ═══════════════════════════════════════════════════════════════════════════
# LX-F06 — 캐시 인스턴스 수
# ═══════════════════════════════════════════════════════════════════════════
def _cache(lines):
    run = run_task_file(CPU_YML, {"_l_cpu_raw_result": {"stdout_lines": lines, "rc": 0}}, ctx={"_l_dmi_raw": {"stdout_lines": []}})
    return run.ctx["_l_cpu_l2_kb"], run.ctx["_l_cpu_l3_kb"]


BASE = ["CPU_MODEL=AMD EPYC 7452 32-Core Processor", "CPU_VENDOR=AuthenticAMD", "CPU_ARCH=x86_64"]


def test_old_lscpu_per_instance_values_use_sysfs_instance_counts():
    # EPYC 7452 ×2 (lab 부재 — 공개 사양 재현): 소켓당 L3 128 MiB = 16 MiB × 8 CCX, L2 512 KiB × 32 코어 = 16 MiB
    l2, l3 = _cache(BASE + ["CPU_SOCKETS=2", "CPU_CPS=32", "LSCPU_VERSION=2.32", "L2_CACHE=512K", "L3_CACHE=16384K",
                            "L2_INSTANCES=64", "L3_INSTANCES=16"])
    assert (l2, l3) == (16384, 131072)


def test_old_lscpu_without_instance_markers_keeps_the_previous_assumption():
    l2, l3 = _cache(BASE + ["CPU_SOCKETS=2", "CPU_CPS=32", "LSCPU_VERSION=2.32", "L2_CACHE=512K", "L3_CACHE=16384K"])
    assert (l2, l3) == (16384, 16384)          # L3 = 소켓당 1개 가정 (종전) — AMD 에서는 틀리지만 근거가 없으면 추측하지 않는다


def test_new_lscpu_totals_ignore_instance_markers():
    l2, l3 = _cache(BASE + ["CPU_SOCKETS=2", "CPU_CPS=32", "LSCPU_VERSION=2.37", "L2_CACHE=32 MiB (64 instances)",
                            "L3_CACHE=256 MiB (16 instances)", "L2_INSTANCES=64", "L3_INSTANCES=16"])
    assert (l2, l3) == (16384, 131072)


def test_raw_script_counts_cache_instances_from_sysfs(sbx):
    script = raw_script(CPU_YML, "raw gather")
    root = sbx.root / "sysfs_cpu"
    # 2 소켓 흉내: cpu0..cpu3 — L2 는 코어마다(4개), L3 는 2 코어가 공유(2개)
    for cpu in range(4):
        for idx, (level, shared) in enumerate([("1", f"{cpu}"), ("1", f"{cpu}"), ("2", f"{cpu}"), ("3", "0-1" if cpu < 2 else "2-3")]):
            d = root / f"cpu{cpu}" / "cache" / f"index{idx}"
            sbx.write(d / "level", level + "\n", executable=False)
            sbx.write(d / "shared_cpu_list", shared + "\n", executable=False)
    sbx.shim_cmd("lscpu", "exit 127\n")
    res = sbx.run(script.replace("/sys/devices/system/cpu", sbx.p(root)))
    assert res.rc == 0, res.stderr[-300:]
    assert res.marker("L2_INSTANCES") == "4" and res.marker("L3_INSTANCES") == "2"


def test_raw_script_cache_instance_count_never_breaks_exit_code(sbx):
    """sysfs 가 없는 호스트(Windows 샌드박스)에서는 표식이 없거나 0 이고, 실제 Linux(WSL · Runner)에서는 그 호스트의 인스턴스 수가 나온다 —
    어느 쪽이든 awk 실패가 스크립트 종료 코드를 바꾸지 않는다 (LX-F06: `|| true`)."""
    sbx.shim_cmd("lscpu", "exit 127\n")
    res = sbx.run(raw_script(CPU_YML, "raw gather"))
    assert res.rc == 0
    for key in ("L2_INSTANCES", "L3_INSTANCES"):
        v = res.marker(key)
        assert v is None or v.isdigit(), (key, v)
