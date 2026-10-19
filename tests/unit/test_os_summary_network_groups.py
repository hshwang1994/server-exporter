"""OS network.summary — 논리 NIC 1개당 1회 · speed 미확정 NIC 도 null 그룹으로 (2026-10-19, B-2 / B-3).

os-gather/tasks/{linux,windows}/gather_network.yml 의 *실제* summary 템플릿을 추출해 렌더한다
(test_network_summary_join_at1.py 패턴 — yaml.safe_load → set_fact 키 → jinja2 Environment → ast.literal_eval).

- B-2 (Linux): 토폴로지 정규화 **뒤**(_l_net_topo_raw.interfaces)를 센다. VLAN 하위 인터페이스(vlan_id) ·
  bond slave(bond_role=slave) · bridge/team member(bridges[].members / teams[].members)는 제외 —
  종전에는 정규화 전 목록(_l_norm_interfaces_raw)을 세어 eno1.100 같은 VLAN 이 부모와 함께 세어졌다.
- B-3 (Linux · Windows): speed 를 못 읽은 NIC(null / 0)도 speed_mbps=null 그룹 하나로 세고 link_up_count 를 센다.
  link_type 은 그대로 null (OS 수집은 Ethernet 임을 단정하지 못한다).
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import yaml
from jinja2 import Environment

REPO = Path(__file__).resolve().parents[2]
LINUX_NET = REPO / "os-gather" / "tasks" / "linux" / "gather_network.yml"
WINDOWS_NET = REPO / "os-gather" / "tasks" / "windows" / "gather_network.yml"
RHEL810_EXPECTED = REPO / "tests" / "fixtures" / "os" / "net" / "rhel810_bond_network.expected.json"


def _tasks(yml: Path) -> list[dict]:
    return [t for t in yaml.safe_load(yml.read_text(encoding="utf-8")) if isinstance(t, dict)]


def _set_fact(yml: Path, task_name: str, var: str) -> str:
    for t in _tasks(yml):
        if t.get("name") == task_name:
            sf = t.get("ansible.builtin.set_fact") or {}
            assert var in sf, f"{task_name}: {var} 없음"
            return sf[var]
    raise AssertionError(f"{yml.name}: task {task_name!r} 미발견")


def _render(tmpl: str, **ctx):
    env = Environment()  # noqa: S701 — 테스트 전용, autoescape 불필요
    out = env.from_string(tmpl).render(**ctx).strip()
    return ast.literal_eval(out)


def _nic(name, speed, link="up", **kw):
    d = {"id": name, "name": name, "kind": "os_nic", "mac": "aa:bb:cc:dd:ee:01", "mtu": 1500,
         "speed_mbps": speed, "link_status": link, "is_primary": False, "addresses": []}
    d.update(kw)
    return d


def _group(speed, quantity, link_up):
    return {"speed_mbps": speed, "link_type": None, "quantity": quantity, "link_up_count": link_up}


# ═══════════════════════════════════════════════════════════════════════════
# Linux — "linux | network | compute summary groups (raw)" (_l_net_summary_r)
# ═══════════════════════════════════════════════════════════════════════════
def _linux_groups(interfaces, bridges=(), teams=()):
    tmpl = _set_fact(LINUX_NET, "linux | network | compute summary groups (raw)", "_l_net_summary_r")
    topo = {"interfaces": interfaces, "bonds": [], "bridges": list(bridges), "teams": list(teams)}
    out = _render(tmpl, _l_net_topo_raw=topo)
    assert set(out) == {"groups"}, out       # 출력 모양 불변 (Additive)
    return out["groups"]


def test_linux_vlan_subinterface_and_bond_slaves_are_not_counted_twice():
    """B-2: eno1 + eno1.100(VLAN) + bond0(20G) + slave eno2/eno3 → eno1 과 bond0 만 센다."""
    ifaces = [
        _nic("eno1", 10000),
        _nic("eno1.100", 10000, vlan_id=100, vlan_parent="eno1"),
        _nic("bond0", 20000, bond_role="master", bond_mode="802.3ad", active_slave=None, bond_slaves=["eno2", "eno3"]),
        _nic("eno2", 10000, bond_role="slave", bond_master="bond0", slave_state="active"),
        _nic("eno3", 10000, bond_role="slave", bond_master="bond0", slave_state="active"),
    ]
    assert _linux_groups(ifaces) == [_group(10000, 1, 1), _group(20000, 1, 1)]


def test_linux_speedless_nic_is_a_null_group_with_link_count():
    """B-3: speed null(또는 0) NIC 는 speed_mbps=null 그룹 하나 — quantity 와 link_up_count 를 센다."""
    assert _linux_groups([_nic("eno4", None, link="down")]) == [_group(None, 1, 0)]
    ifaces = [_nic("eno4", None, link="down"), _nic("eno5", 0, link="unknown"), _nic("eno6", None, link="up"),
              _nic("eno7", 25000, link="up")]
    assert _linux_groups(ifaces) == [_group(None, 3, 1), _group(25000, 1, 1)]


def test_linux_bridge_and_team_members_are_excluded_masters_counted_once():
    """bridge/team member 는 master 집계에 들어 있다 → 제외. master 자체는 (speed 없어도) 논리 NIC 1개."""
    ifaces = [_nic("br0", None, link="up"), _nic("eno7", 10000), _nic("team0", None, link="up"), _nic("eno8", 10000)]
    bridges = [{"name": "br0", "members": ["eno7"]}]
    teams = [{"name": "team0", "mode": None, "members": ["eno8"]}]
    assert _linux_groups(ifaces, bridges=bridges, teams=teams) == [_group(None, 2, 2)]
    # member 목록이 없으면(종전 캡처 virbr0: members []) 아무것도 빠지지 않는다
    assert _linux_groups(ifaces, bridges=[{"name": "virbr0", "members": []}]) == [_group(None, 2, 2), _group(10000, 2, 2)]


def test_linux_real_baremetal_capture_counts_logical_nics_once():
    """실장비 캡처(2026-09-03 build192, Dell R760 — bond0 + bond0.64 VLAN + down NIC 3 + calico vxlan) 의 interfaces 모양.

    종전 결과 {10000: qty 3 (bond0 + bond0.64 + vxlan), 1000: qty 1} 에서 VLAN 이중 카운트가 빠지고 down NIC 3개가 null 그룹으로 보인다."""
    ifaces = [
        _nic("bond0", 10000, bond_role="master", bond_mode="802.3ad", bond_slaves=["enp190s0f0np0", "enp190s0f1np1"]),
        _nic("bond0.64", 10000, vlan_id=64, vlan_parent="bond0"),
        _nic("eno12399np0", None, link="down"),
        _nic("eno12409np1", None, link="down"),
        _nic("eno8303", 1000),
        _nic("eno8403", None, link="down"),
        _nic("vxlan.calico", 10000, link="unknown"),
        _nic("enp190s0f0np0", 10000, bond_role="slave", bond_master="bond0"),
        _nic("enp190s0f1np1", 10000, bond_role="slave", bond_master="bond0"),
    ]
    groups = _linux_groups(ifaces, bridges=[{"name": "docker0", "members": ["veth05a75d6"]}])
    assert groups == [_group(10000, 2, 1), _group(None, 3, 0), _group(1000, 1, 1)]


def test_linux_rhel810_bond_fixture_summary_is_unchanged():
    """실장비 fixture(RHEL 8.10, bond1/bond2 + 일반 NIC 2 + slave 4) — slave 제외 뒤에도 종전 summary 와 같다 (회귀 고정)."""
    expected = json.loads(RHEL810_EXPECTED.read_text(encoding="utf-8"))
    groups = _linux_groups(expected["interfaces"], bridges=expected["bridges"], teams=expected["teams"])
    assert groups == expected["summary"]["groups"] == [_group(10000, 4, 4)]


def test_linux_summary_task_runs_after_topology_normalization():
    """B-2 의 의존: summary 는 _l_net_topo_raw 를 읽으므로 "normalize topology (raw)" 뒤 · "build fragment (raw)" 앞이어야 한다."""
    names = [t.get("name") for t in _tasks(LINUX_NET)]
    i_topo = names.index("linux | network | normalize topology (raw)")
    i_sum = names.index("linux | network | compute summary groups (raw)")
    i_frag = names.index("linux | network | build fragment (raw)")
    assert i_topo < i_sum < i_frag, names
    tmpl = _set_fact(LINUX_NET, "linux | network | compute summary groups (raw)", "_l_net_summary_r")
    assert "_l_net_topo_raw" in tmpl and "_l_norm_interfaces_raw" not in tmpl


# ═══════════════════════════════════════════════════════════════════════════
# Windows — "windows | network | compute summary groups" (_w_net_summary)
# ═══════════════════════════════════════════════════════════════════════════
def _windows_groups(interfaces):
    tmpl = _set_fact(WINDOWS_NET, "windows | network | compute summary groups", "_w_net_summary")
    out = _render(tmpl, _w_net_topo={"interfaces": interfaces, "teams": []})
    assert set(out) == {"groups"}, out
    return out["groups"]


def test_windows_speedless_nic_is_a_null_group():
    """B-3: 어댑터를 못 찾은 주소(speed null · status null → link unknown) 도 null 그룹으로 센다."""
    ifaces = [_nic("Ethernet0", 10000),
              _nic("Loopback Pseudo-Interface 2", None, link="unknown", mac=None, mtu=None, description=None)]
    assert _windows_groups(ifaces) == [_group(10000, 1, 1), _group(None, 1, 0)]


def test_windows_vlan_tnic_and_team_members_still_excluded():
    """종전 제외 규칙 유지: 팀 VLAN tNIC(vlan_id) 와 팀 member 는 세지 않는다. Speed 0 인 끊긴 NIC 는 null 그룹."""
    ifaces = [
        _nic("LabTeam1", 20000, team_role="master", team_members=["Ethernet1", "Ethernet2"]),
        _nic("LabTeam1 - VLAN 100", 20000, vlan_id=100, vlan_parent="LabTeam1"),
        _nic("Ethernet1", 10000, team_role="member", team_master="LabTeam1"),
        _nic("Ethernet2", 10000, team_role="member", team_master="LabTeam1"),
        _nic("Ethernet3", 0, link="down"),
    ]
    assert _windows_groups(ifaces) == [_group(20000, 1, 1), _group(None, 1, 0)]
