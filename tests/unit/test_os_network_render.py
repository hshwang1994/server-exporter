"""os-gather/tasks/linux/gather_network.yml 의 *실제* set_fact 템플릿 렌더 회귀.

raw fallback 경로의 실제 Jinja2 템플릿 체인을 추출해, 실장비(RHEL 8.10) 에서 캡처한
raw stdout fixture 로 렌더 → 최종 data.network 가 기대 fixture 와 일치하는지 검증한다.
필터+YAML 와이어링 회귀를 SSH 없이 CI 에서 잡는다 (test_network_summary_join_at1.py 패턴).
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import yaml
from jinja2 import Environment

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))
from network_topology import build_linux_network  # noqa: E402

NET_YML = REPO / "os-gather" / "tasks" / "linux" / "gather_network.yml"
FIX = REPO / "tests" / "fixtures" / "os" / "net"


def _combine(d, other, recursive=False):
    r = dict(d or {})
    r.update(other or {})
    return r


def _regex_replace(value, pattern, repl="", *_a, **_k):
    return re.sub(pattern, repl, str(value))


def _env():
    env = Environment()  # noqa: S701 — 테스트 전용
    env.filters["combine"] = _combine
    env.filters["regex_replace"] = _regex_replace
    env.filters["build_linux_network"] = build_linux_network
    return env


def _tasks():
    return yaml.safe_load(NET_YML.read_text(encoding="utf-8"))


def _raw_block(tasks):
    for t in tasks:
        if "block" in t and "!= 'python_ok'" in str(t.get("when", "")):
            return t["block"]
    raise AssertionError("raw fallback block 미발견")


def _setfact(block, name_sub):
    for t in block:
        if name_sub in t.get("name", "") and "ansible.builtin.set_fact" in t:
            return t["ansible.builtin.set_fact"]
    raise AssertionError(f"set_fact '{name_sub}' 미발견")


def _render(env, tmpl, ctx):
    out = env.from_string(tmpl).render(**ctx).strip()
    if out == "":
        return ""
    try:
        return ast.literal_eval(out)
    except (ValueError, SyntaxError):
        return out


def _render_raw_path(stdout_text: str) -> dict:
    """raw fallback 경로의 실제 템플릿 체인을 렌더해 data.network 반환."""
    tasks = _tasks()
    block = _raw_block(tasks)
    env = _env()
    lines = stdout_text.splitlines()
    ctx = {"_l_net_raw": {"stdout": stdout_text, "stdout_lines": lines, "stderr": "", "rc": 0}}

    parse_sf = _setfact(block, "parse raw")
    for var in ["_l_raw_dns", "_l_raw_gw", "_l_raw_gw_dev", "_l_raw_ipv6_by_dev",
                "_l_raw_adapters", "_l_raw_ifaces"]:
        ctx[var] = _render(env, parse_sf[var], ctx)
    ctx["_l_norm_interfaces_raw"] = _render(
        env, _setfact(block, "raw mark primary")["_l_norm_interfaces_raw"], ctx)
    ctx["_l_net_topo_raw"] = _render(
        env, _setfact(block, "normalize topology (raw)")["_l_net_topo_raw"], ctx)
    ctx["_l_net_summary_r"] = _render(
        env, _setfact(block, "compute summary groups (raw)")["_l_net_summary_r"], ctx)
    net_tmpl = _setfact(block, "build fragment (raw)")["_data_fragment"]["network"]
    return {k: (_render(env, v, ctx) if isinstance(v, str) else v) for k, v in net_tmpl.items()}


def test_raw_path_yaml_render_has_bonds():
    """실제 YAML 템플릿 → 실장비 raw stdout → bond 토폴로지가 최종 data.network 에 존재."""
    stdout = (FIX / "rhel810_rawpath_stdout.txt").read_text(encoding="utf-8")
    net = _render_raw_path(stdout)

    # bond 2개 + 메타데이터
    assert [b["name"] for b in net["bonds"]] == ["bond1", "bond2"]
    b1 = next(b for b in net["bonds"] if b["name"] == "bond1")
    assert b1["mode"] == "active-backup"
    assert b1["active_slave"] == "ens161"
    assert b1["miimon"] == 100
    assert b1["xmit_hash_policy"] == "layer2"
    assert [s["name"] for s in b1["slaves"]] == ["ens161", "ens193"]
    assert b1["slaves"][0]["state"] == "active"
    assert b1["addresses"][0]["address"] == "10.100.64.169"  # bond 에 IP

    # 물리 slave 가 interfaces 에 IP 없이 존재
    by_name = {i["name"]: i for i in net["interfaces"]}
    for sl in ("ens161", "ens193", "ens225", "ens256"):
        assert by_name[sl]["bond_role"] == "slave"
        assert by_name[sl]["addresses"] == []
    # bond master 는 IP 보유
    assert by_name["bond1"]["bond_role"] == "master"
    assert by_name["bond1"]["addresses"][0]["address"] == "10.100.64.169"
    # 일반 NIC 는 bond_role 키 없음 (Additive)
    assert "bond_role" not in by_name["ens192"]
    # 13 필드 호환: 기존 키 유지
    assert set(["dns_servers", "default_gateways", "interfaces", "adapters",
                "ports", "summary"]).issubset(net.keys())


def test_raw_path_matches_committed_expected():
    """raw 경로 렌더 결과가 커밋된 기대 fixture 와 정확히 일치 (회귀 고정)."""
    import json
    stdout = (FIX / "rhel810_rawpath_stdout.txt").read_text(encoding="utf-8")
    net = _render_raw_path(stdout)
    expected = json.loads((FIX / "rhel810_bond_network.expected.json").read_text(encoding="utf-8"))
    assert net == expected


def _collector_fact(tasks):
    for t in tasks:
        sf = t.get("ansible.builtin.set_fact") or {}
        if "_l_net_collector" in sf:
            return sf["_l_net_collector"]
    raise AssertionError("_l_net_collector 미발견")


def test_collector_injects_into_raw_and_shell_without_jinja_collision():
    """리뷰 지적 검증: collector(awk {print}/{gsub} 포함)를 raw/shell 에 {{ }} 주입해도
    Jinja2 가 awk 중괄호를 델리미터로 오인하지 않음 (ansible 템플릿 동작 모사)."""
    tasks = _tasks()
    collector = _collector_fact(tasks)
    env = _env()

    # raw fallback 명령
    block = _raw_block(tasks)
    raw_cmd = next(t["ansible.builtin.raw"] for t in block if "raw gather" in t.get("name", ""))
    rendered = env.from_string(raw_cmd).render(_l_net_collector=collector)
    assert "BOND|" in rendered           # collector 본문 주입됨
    assert "{print" in rendered          # awk 중괄호 보존
    assert "gsub(" in rendered
    assert "{{" not in rendered          # 잔여 미해결 템플릿 없음

    # python_ok shell 명령
    for t in tasks:
        if "block" in t and "== 'python_ok'" in str(t.get("when", "")):
            sh = next(s["ansible.builtin.shell"] for s in t["block"]
                      if "topology (shell)" in s.get("name", ""))
            out = env.from_string(sh).render(_l_net_collector=collector)
            assert "BOND|" in out and "{{" not in out
            break
