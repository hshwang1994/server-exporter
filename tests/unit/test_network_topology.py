"""network_topology 필터 플러그인 단위 테스트 (cycle 2026-06-15 OS bond/team 보강).

filter_plugins/network_topology.py 의 Linux bond/vlan/bridge + Windows teaming 파싱·정규화를
요구 시나리오 전수로 검증한다. 실장비(RHEL 8.10 raw / RHEL 9.6 python) 캡처 fixture 포함.

커버 시나리오:
  bond 없음 / bond 1개 / bond 여러개 / active-backup / 802.3ad / bond 아래 VLAN /
  slave-only+bond IP / /proc 없음 / sysfs-only / nmcli 없음 / NetworkManager 없음 /
  raw 일부 실패 / 빈 출력 / 예상外 형식 / Windows 팀 없음 / LBFO / SET
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "filter_plugins"))

from network_topology import (  # noqa: E402
    parse_linux_net_topology,
    build_linux_network,
    enrich_linux_interfaces,
    parse_linux_addresses,
    merge_linux_addresses,
    parse_windows_teams,
    parse_windows_team_nics,
    enrich_windows_addresses,
    build_windows_network,
)

FIX = REPO / "tests" / "fixtures" / "os" / "net"


def _topo_lines(name: str) -> list[str]:
    return [ln for ln in (FIX / name).read_text(encoding="utf-8").splitlines() if ln.strip()]


def _addr_line(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8").strip()


def _iface(name, ip=None, mac=None, speed=10000):
    addrs = []
    if ip:
        addrs = [{"family": "ipv4", "address": ip, "prefix_length": 24,
                  "subnet_mask": "255.255.255.0", "gateway": None}]
    return {"id": name, "name": name, "kind": "os_nic", "mac": mac, "mtu": 1500,
            "speed_mbps": speed, "link_status": "up", "is_primary": False, "addresses": addrs}


# ---------------------------------------------------------------------------
# 1. bond 없음
# ---------------------------------------------------------------------------
def test_no_bond_empty_topology():
    topo = parse_linux_net_topology([])
    assert topo == {"bonds": [], "bridges": [], "teams": [], "vlans": []}
    base = [_iface("ens192", "10.0.0.1", "aa:bb:cc:00:00:01")]
    net = build_linux_network(base, [])
    assert net["bonds"] == [] and net["bridges"] == [] and net["teams"] == []
    # 기존 인터페이스 불변 (Additive — bond 관련 키 미추가)
    assert net["interfaces"] == base
    assert "bond_role" not in net["interfaces"][0]


# ---------------------------------------------------------------------------
# 2. bond 1개 (active-backup)
# ---------------------------------------------------------------------------
ONE_BOND = [
    "BOND|bond0|active-backup|eth0|100|slow|layer2|eth0|stable|eth0 eth1",
    "BSLAVE|bond0|eth0|active|up|00:11:22:33:44:00|10000|0",
    "BSLAVE|bond0|eth1|backup|up|00:11:22:33:44:01|10000|2",
    "SLSTATE|eth0|active",
    "SLSTATE|eth1|backup",
    "SLMETA|bond0|eth0|1500|up|10000|00:11:22:33:44:00",
    "SLMETA|bond0|eth1|1500|up|10000|00:11:22:33:44:01",
]


def test_one_bond_active_backup():
    topo = parse_linux_net_topology(ONE_BOND)
    assert len(topo["bonds"]) == 1
    b = topo["bonds"][0]
    assert b["name"] == "bond0"
    assert b["mode"] == "active-backup"
    assert b["active_slave"] == "eth0"
    assert b["miimon"] == 100
    assert b["lacp_rate"] == "slow"
    assert b["xmit_hash_policy"] == "layer2"
    assert [s["name"] for s in b["slaves"]] == ["eth0", "eth1"]
    assert b["slaves"][0]["state"] == "active"
    assert b["slaves"][1]["state"] == "backup"
    assert b["slaves"][1]["link_failure_count"] == 2
    assert b["slaves"][0]["perm_hwaddr"] == "00:11:22:33:44:00"


def test_one_bond_enrich_adds_slaves_and_marks_master():
    base = [_iface("bond0", "10.0.0.5", "00:11:22:33:44:00")]
    net = build_linux_network(base, ONE_BOND)
    names = [i["name"] for i in net["interfaces"]]
    assert names == ["bond0", "eth0", "eth1"]
    master = net["interfaces"][0]
    assert master["bond_role"] == "master"
    assert master["bond_mode"] == "active-backup"
    assert master["active_slave"] == "eth0"
    assert master["bond_slaves"] == ["eth0", "eth1"]
    # slave NIC: IP 없음, perm MAC, bond_master/slave_state
    eth0 = net["interfaces"][1]
    assert eth0["bond_role"] == "slave"
    assert eth0["bond_master"] == "bond0"
    assert eth0["slave_state"] == "active"
    assert eth0["addresses"] == []
    assert eth0["mac"] == "00:11:22:33:44:00"
    # bond[].addresses 에 master IP 주입
    assert net["bonds"][0]["addresses"][0]["address"] == "10.0.0.5"


# ---------------------------------------------------------------------------
# 3. bond 여러 개
# ---------------------------------------------------------------------------
def test_multiple_bonds():
    lines = [
        "BOND|bond0|active-backup|eth0|100|slow|layer2|eth0|stable|eth0 eth1",
        "BOND|bond1|802.3ad|eth2|100|fast|layer3+4||stable|eth2 eth3",
        "SLSTATE|eth0|active", "SLSTATE|eth1|backup",
        "SLSTATE|eth2|active", "SLSTATE|eth3|active",
        "SLMETA|bond0|eth0|1500|up|10000|aa:00", "SLMETA|bond0|eth1|1500|up|10000|aa:01",
        "SLMETA|bond1|eth2|9000|up|25000|aa:02", "SLMETA|bond1|eth3|9000|up|25000|aa:03",
    ]
    topo = parse_linux_net_topology(lines)
    assert [b["name"] for b in topo["bonds"]] == ["bond0", "bond1"]
    assert topo["bonds"][1]["mode"] == "802.3ad"
    assert topo["bonds"][1]["slaves"][0]["mtu"] == 9000
    assert topo["bonds"][1]["slaves"][0]["speed_mbps"] == 25000


# ---------------------------------------------------------------------------
# 5. 802.3ad (LACP) — 모든 slave active, lacp_rate/xmit 반영
# ---------------------------------------------------------------------------
def test_lacp_8023ad_all_slaves_active():
    lines = [
        "BOND|bond0|802.3ad||100|fast|layer3+4||stable|eth0 eth1",
        "SLSTATE|eth0|active", "SLSTATE|eth1|active",
        "SLMETA|bond0|eth0|1500|up|10000|aa:00", "SLMETA|bond0|eth1|1500|up|10000|aa:01",
    ]
    b = parse_linux_net_topology(lines)["bonds"][0]
    assert b["mode"] == "802.3ad"
    assert b["lacp_rate"] == "fast"
    assert b["xmit_hash_policy"] == "layer3+4"
    assert all(s["state"] == "active" for s in b["slaves"])  # LACP 는 모두 active


# ---------------------------------------------------------------------------
# 6. bond 아래 VLAN
# ---------------------------------------------------------------------------
def test_vlan_on_bond():
    lines = ONE_BOND + ["VLANIF|bond0.100|bond0|100"]
    # bond0 는 IP 없음(VLAN 부모), bond0.100 이 IP 보유
    base = [_iface("bond0.100", "10.0.100.5", "00:11:22:33:44:00")]
    net = build_linux_network(base, lines)
    names = [i["name"] for i in net["interfaces"]]
    assert "bond0.100" in names  # VLAN iface 유지
    assert "bond0" in names      # IP 없는 bond master 추가됨
    vlan = next(i for i in net["interfaces"] if i["name"] == "bond0.100")
    assert vlan["vlan_id"] == 100
    assert vlan["vlan_parent"] == "bond0"
    master = next(i for i in net["interfaces"] if i["name"] == "bond0")
    assert master["bond_role"] == "master"
    assert master["addresses"] == []  # bond 자체 IP 없음


# ---------------------------------------------------------------------------
# 7. slave NIC만 있고 bond에 IP가 있는 구조 (실장비 형태)
# ---------------------------------------------------------------------------
def test_slave_only_bond_has_ip():
    base = [_iface("bond0", "10.0.0.9", "aa:00")]  # 물리 slave 는 base 에 없음
    net = build_linux_network(base, ONE_BOND)
    bond_if = next(i for i in net["interfaces"] if i["name"] == "bond0")
    assert bond_if["addresses"][0]["address"] == "10.0.0.9"
    slaves = [i for i in net["interfaces"] if i.get("bond_role") == "slave"]
    assert {s["name"] for s in slaves} == {"eth0", "eth1"}
    assert all(s["addresses"] == [] for s in slaves)  # 물리 NIC IP 없음


# ---------------------------------------------------------------------------
# 8. /proc/net/bonding 없음 (BSLAVE 부재) — sysfs + ip 로 복원
# ---------------------------------------------------------------------------
def test_no_proc_net_bonding():
    lines = [
        "BOND|bond0|active-backup|eth0|100|slow|layer2|eth0|stable|eth0 eth1",
        "SLSTATE|eth0|active", "SLSTATE|eth1|backup",
        "SLMETA|bond0|eth0|1500|up|10000|aa:00", "SLMETA|bond0|eth1|1500|up|10000|aa:01",
    ]
    b = parse_linux_net_topology(lines)["bonds"][0]
    assert [s["name"] for s in b["slaves"]] == ["eth0", "eth1"]
    assert b["slaves"][0]["state"] == "active"      # SLSTATE 로 복원
    assert b["slaves"][0]["speed_mbps"] == 10000    # SLMETA 로 복원
    assert b["slaves"][0]["link_failure_count"] is None  # proc 부재 → None (날조 안 함)


# ---------------------------------------------------------------------------
# 9. /sys/class/net 정보만 있는 구조 (BSLAVE + SLSTATE 부재)
# ---------------------------------------------------------------------------
def test_sysfs_only():
    lines = [
        "BOND|bond0|balance-rr|eth0|100|slow|layer2||stable|eth0 eth1",
        "SLMETA|bond0|eth0|1500|up|10000|aa:00", "SLMETA|bond0|eth1|1500|down|10000|aa:01",
    ]
    b = parse_linux_net_topology(lines)["bonds"][0]
    assert b["mode"] == "balance-rr"
    assert [s["name"] for s in b["slaves"]] == ["eth0", "eth1"]
    assert b["slaves"][0]["link_status"] == "up"     # operstate from SLMETA
    assert b["slaves"][1]["link_status"] == "down"
    assert b["slaves"][0]["state"] is None           # SLSTATE/proc 부재 → None


def test_sysfs_only_slave_backref_when_no_slaves_field():
    # BOND 의 slaves 필드가 비어도 SLMETA master 역참조로 복원
    lines = [
        "BOND|bond0|active-backup|eth0|100|slow|layer2|eth0|stable|",
        "SLMETA|bond0|eth0|1500|up|10000|aa:00", "SLMETA|bond0|eth1|1500|up|10000|aa:01",
    ]
    b = parse_linux_net_topology(lines)["bonds"][0]
    assert {s["name"] for s in b["slaves"]} == {"eth0", "eth1"}


# ---------------------------------------------------------------------------
# 10/11. nmcli 없음 / NetworkManager 없음 — collector 는 sysfs/proc/ip 만 사용
# ---------------------------------------------------------------------------
def test_no_nmcli_no_networkmanager_still_parses():
    # collector 출력에는 nmcli/NM 유래 라인이 전혀 없음 → 영향 없음을 명시 검증
    b = parse_linux_net_topology(ONE_BOND)["bonds"][0]
    assert b["name"] == "bond0" and len(b["slaves"]) == 2


# ---------------------------------------------------------------------------
# 12. raw 명령 일부 실패 (일부 라인 누락) — 가능한 값만 수집, 멈추지 않음
# ---------------------------------------------------------------------------
def test_partial_command_failure():
    # SLMETA 전부 실패(sysfs read 실패) + BSLAVE 일부만 성공
    lines = [
        "BOND|bond0|active-backup|eth0|100|slow|layer2|eth0|stable|eth0 eth1",
        "BSLAVE|bond0|eth0|active|up|00:11:22:33:44:00|10000|0",
        # eth1 BSLAVE/SLMETA/SLSTATE 전부 실패
        "SLSTATE|eth0|active",
    ]
    b = parse_linux_net_topology(lines)["bonds"][0]
    assert [s["name"] for s in b["slaves"]] == ["eth0", "eth1"]  # slaves 필드로 둘 다 인식
    assert b["slaves"][0]["speed_mbps"] == 10000
    assert b["slaves"][1]["speed_mbps"] is None   # 데이터 없는 slave 는 None (graceful)
    assert b["slaves"][1]["state"] is None


# ---------------------------------------------------------------------------
# 13. 빈 출력
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("empty", [None, [], [""], ["   ", "\n"]])
def test_empty_output(empty):
    assert parse_linux_net_topology(empty) == {"bonds": [], "bridges": [], "teams": [], "vlans": []}
    net = build_linux_network([_iface("eth0", "10.0.0.1", "aa")], empty)
    assert net["bonds"] == [] and net["interfaces"][0]["name"] == "eth0"


# ---------------------------------------------------------------------------
# 14. 예상과 다른 출력 형식 (malformed) — valid 만 파싱, 나머지 skip
# ---------------------------------------------------------------------------
def test_unexpected_format_is_robust():
    lines = [
        "GARBAGE LINE NO DELIM",
        "BOND|bond0",                    # 필드 부족 → skip
        "BOND||active-backup|||||||",    # 빈 name → skip
        "BOND|bond0|active-backup|eth0|100|slow|layer2|eth0|stable|eth0 eth1",  # valid
        "BSLAVE|bond0",                  # 필드 부족 → skip
        "SLSTATE|eth0",                  # 필드 부족 → skip
        "RANDOM|x|y|z",                  # 미지 태그 → skip
        "",
        "SLMETA|bond0|eth0|notanint|up|notanint|aa:00",  # 숫자 아님 → mtu/speed None
    ]
    topo = parse_linux_net_topology(lines)
    assert len(topo["bonds"]) == 1
    b = topo["bonds"][0]
    assert b["name"] == "bond0"
    eth0 = next(s for s in b["slaves"] if s["name"] == "eth0")
    assert eth0["mtu"] is None and eth0["speed_mbps"] is None  # 비숫자 방어


def test_miimon_nonnumeric_is_none():
    lines = ["BOND|bond0|active-backup|eth0|notnum|slow|layer2|eth0|stable|eth0"]
    assert parse_linux_net_topology(lines)["bonds"][0]["miimon"] is None


# ---------------------------------------------------------------------------
# bridge
# ---------------------------------------------------------------------------
def test_bridge_with_members():
    lines = ["BRIDGE|br0|eth5 eth6", "BRIDGE|virbr0|"]
    topo = parse_linux_net_topology(lines)
    assert topo["bridges"] == [{"name": "br0", "members": ["eth5", "eth6"]},
                               {"name": "virbr0", "members": []}]


# ---------------------------------------------------------------------------
# Linux teamd
# ---------------------------------------------------------------------------
def test_linux_teamd():
    lines = ["TEAM|team0|activebackup|eth7 eth8"]
    topo = parse_linux_net_topology(lines)
    assert topo["teams"] == [{"name": "team0", "mode": "activebackup",
                              "members": ["eth7", "eth8"]}]


# ---------------------------------------------------------------------------
# 실장비 fixture: RHEL 8.10 raw / RHEL 9.6 python (동일 토폴로지)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture", ["rhel810_bond_topo.txt", "rhel96_bond_topo.txt"])
def test_real_host_capture(fixture):
    topo = parse_linux_net_topology(_topo_lines(fixture))
    assert [b["name"] for b in topo["bonds"]] == ["bond1", "bond2"]
    b1 = topo["bonds"][0]
    assert b1["mode"] == "active-backup"
    assert b1["active_slave"] == "ens161"
    assert b1["miimon"] == 100
    assert [s["name"] for s in b1["slaves"]] == ["ens161", "ens193"]
    assert b1["slaves"][0]["state"] == "active"
    assert b1["slaves"][1]["state"] == "backup"
    assert b1["slaves"][0]["speed_mbps"] == 10000


def test_real_rhel810_full_network_matches_expected():
    """RHEL 8.10 raw-path 실 캡처 → build_linux_network → 기대 data.network 일치."""
    lines = _topo_lines("rhel810_bond_topo.txt")
    base = [
        _iface("ens192", "10.100.64.161", "00:50:56:84:00:b4"),
        _iface("ens224", "10.100.64.162", "00:50:56:84:2a:2a"),
        _iface("bond1", "10.100.64.169", "00:50:56:84:57:81"),
        _iface("bond2", "10.100.64.170", "00:50:56:84:bf:36"),
    ]
    net = build_linux_network(base, lines)
    # bond master IP + slave 무IP 구조
    bond1 = next(b for b in net["bonds"] if b["name"] == "bond1")
    assert bond1["addresses"][0]["address"] == "10.100.64.169"
    slaves = {i["name"]: i for i in net["interfaces"] if i.get("bond_role") == "slave"}
    assert set(slaves) == {"ens161", "ens193", "ens225", "ens256"}
    assert slaves["ens161"]["bond_master"] == "bond1"
    assert slaves["ens161"]["slave_state"] == "active"
    assert slaves["ens161"]["addresses"] == []
    assert net["bridges"] == [{"name": "virbr0", "members": []}]


# ===========================================================================
# Windows teaming
# ===========================================================================
# 15. Windows Teaming 없음
def test_windows_no_team():
    assert parse_windows_teams([]) == []
    base = [_iface("Ethernet0", "10.0.0.2", "00-11-22-33-44-55")]
    net = build_windows_network(base, ["WADP {\"name\":\"Ethernet0\",\"mac\":\"00-11-22-33-44-55\",\"status\":\"Up\",\"speed_mbps\":10000}"])
    assert net["teams"] == [] and net["bonds"] == [] and net["bridges"] == []
    iface = net["interfaces"][0]
    assert iface["name"] == "Ethernet0"
    assert "team_role" not in iface  # 비teamed → 팀 키 미추가 (interface-level 불변)
    # addresses 는 5키 Additive enrich (값 보존, parity 완성)
    a = iface["addresses"][0]
    assert a["address"] == "10.0.0.2"
    assert a["is_alias"] is False and a["is_secondary"] is False
    assert a["parent_interface"] == "Ethernet0" and a["scope"] == "global"


# 16. Windows LBFO Teaming
LBFO_LINES = [
    'WADP {"name":"Ethernet","mac":"00-11-22-33-44-00","status":"Up","speed_mbps":10000}',
    'WADP {"name":"Ethernet 2","mac":"00-11-22-33-44-01","status":"Up","speed_mbps":10000}',
    'WADP {"name":"Team1","mac":"00-11-22-33-44-00","status":"Up","speed_mbps":20000}',
    'LBFOTEAM {"name":"Team1","teaming_mode":"Lacp","load_balancing":"Dynamic","lacp_timer":"Fast","status":"Up","members":["Ethernet","Ethernet 2"]}',
    'LBFOMEMBER {"name":"Ethernet","team":"Team1","admin_mode":"Active"}',
    'LBFOMEMBER {"name":"Ethernet 2","team":"Team1","admin_mode":"Active"}',
]


def test_windows_lbfo_team():
    teams = parse_windows_teams(LBFO_LINES)
    assert len(teams) == 1
    t = teams[0]
    assert t["name"] == "Team1"
    assert t["team_type"] == "lbfo"
    assert t["teaming_mode"] == "Lacp"
    assert t["load_balancing"] == "Dynamic"
    assert t["lacp_timer"] == "Fast"
    assert [m["name"] for m in t["members"]] == ["Ethernet", "Ethernet 2"]
    assert t["members"][0]["mac"] == "00-11-22-33-44-00"
    assert t["members"][0]["admin_mode"] == "Active"
    assert t["members"][0]["speed_mbps"] == 10000


def test_windows_lbfo_enrich_interfaces():
    # team NIC(Team1) 는 IP 보유(base), member 는 IP 없음(추가됨)
    base = [_iface("Team1", "10.0.0.10", "00-11-22-33-44-00")]
    net = build_windows_network(base, LBFO_LINES)
    names = {i["name"] for i in net["interfaces"]}
    assert names == {"Team1", "Ethernet", "Ethernet 2"}
    master = next(i for i in net["interfaces"] if i["name"] == "Team1")
    assert master["team_role"] == "master"
    assert master["team_type"] == "lbfo"
    assert master["team_members"] == ["Ethernet", "Ethernet 2"]
    mem = next(i for i in net["interfaces"] if i["name"] == "Ethernet")
    assert mem["team_role"] == "member"
    assert mem["team_master"] == "Team1"
    assert mem["addresses"] == []


def test_windows_lbfo_single_member_scalar_json():
    # ConvertTo-Json 은 1원소 배열을 스칼라로 직렬화 — _aslist 가 처리
    lines = [
        'LBFOTEAM {"name":"T2","teaming_mode":"SwitchIndependent","load_balancing":"Dynamic","lacp_timer":null,"status":"Up","members":"NIC1"}',
        'WADP {"name":"NIC1","mac":"aa-bb","status":"Up","speed_mbps":1000}',
    ]
    t = parse_windows_teams(lines)[0]
    assert [m["name"] for m in t["members"]] == ["NIC1"]
    assert t["lacp_timer"] is None


# 17. Windows Switch Embedded Teaming (SET)
def test_windows_set_team():
    lines = [
        'WADP {"name":"NIC1","mac":"aa-01","status":"Up","speed_mbps":25000}',
        'WADP {"name":"NIC2","mac":"aa-02","status":"Up","speed_mbps":25000}',
        'SETTEAM {"name":"SETSwitch","members":["NIC1","NIC2"]}',
        'SETMEMBER {"name":"NIC1","team":"SETSwitch"}',
        'SETMEMBER {"name":"NIC2","team":"SETSwitch"}',
    ]
    teams = parse_windows_teams(lines)
    assert len(teams) == 1
    t = teams[0]
    assert t["team_type"] == "set"
    assert t["teaming_mode"] is None
    assert [m["name"] for m in t["members"]] == ["NIC1", "NIC2"]
    assert t["members"][0]["speed_mbps"] == 25000


def test_windows_mixed_lbfo_set_and_plain():
    lines = LBFO_LINES + [
        'WADP {"name":"NIC9","mac":"aa-09","status":"Up","speed_mbps":25000}',
        'SETTEAM {"name":"SET1","members":"NIC9"}',
    ]
    base = [_iface("Team1", "10.0.0.10", "00-11-22-33-44-00"),
            _iface("Plain0", "10.0.0.20", "00-11-22-33-44-99")]
    net = build_windows_network(base, lines)
    assert {t["name"] for t in net["teams"]} == {"Team1", "SET1"}
    plain = next(i for i in net["interfaces"] if i["name"] == "Plain0")
    assert "team_role" not in plain  # 비teamed NIC 불변


def test_windows_malformed_lines_robust():
    lines = [
        "GARBAGE",
        'LBFOTEAM {bad json}',
        'LBFOTEAM {"name":"","members":[]}',  # 빈 name → skip
        'LBFOTEAM {"name":"OK","teaming_mode":"Static","status":"Up","members":[]}',
    ]
    teams = parse_windows_teams(lines)
    assert [t["name"] for t in teams] == ["OK"]
    assert teams[0]["members"] == []


# ---------------------------------------------------------------------------
# 19. Windows 주소 5키 parity (scope/label/parent_interface/is_alias/is_secondary)
#     channel:[os] 인데 Linux 만 구현됐던 갭 완성. 실장비 캡처: site 10.100.64.120 Ethernet4
#     (192.168.50.40 + .41, 같은 /24) → 2번째가 is_secondary, is_alias 는 항상 False.
# ---------------------------------------------------------------------------
def _wifc(name, ips, prefix=24):
    """ips = [ip,...] (같은 prefix). Windows base 5키 주소."""
    addrs = [{"family": "ipv4", "address": ip, "prefix_length": prefix,
              "subnet_mask": "255.255.255.0", "gateway": None} for ip in ips]
    return {"id": name, "name": name, "kind": "os_nic", "mac": None, "mtu": 1500,
            "speed_mbps": 10000, "link_status": "up", "is_primary": False, "addresses": addrs}


def test_windows_addr_secondary_same_subnet():
    # Ethernet4: 같은 /24 두 IP → 2번째만 is_secondary
    out = enrich_windows_addresses([_wifc("Ethernet4", ["192.168.50.40", "192.168.50.41"])])
    addrs = out[0]["addresses"]
    assert addrs[0]["is_secondary"] is False
    assert addrs[1]["is_secondary"] is True
    # 공통: is_alias 항상 False, label/parent = iface, scope global
    for a in addrs:
        assert a["is_alias"] is False
        assert a["label"] == "Ethernet4" and a["parent_interface"] == "Ethernet4"
        assert a["scope"] == "global"


def test_windows_addr_single_ip_not_secondary():
    out = enrich_windows_addresses([_wifc("Ethernet0", ["10.100.64.120"])])
    a = out[0]["addresses"][0]
    assert a["is_secondary"] is False and a["is_alias"] is False


def test_windows_addr_different_subnet_not_secondary():
    # 다른 서브넷 두 IP → 둘 다 secondary 아님 (Linux 동작 일치)
    out = enrich_windows_addresses([_wifc("EthX", ["10.0.1.5", "10.0.2.5"])])
    addrs = out[0]["addresses"]
    assert addrs[0]["is_secondary"] is False and addrs[1]["is_secondary"] is False


def test_windows_addr_empty_addresses_noop():
    # member NIC (addresses=[]) → 에러 없이 빈 list 유지
    out = enrich_windows_addresses([{"name": "Ethernet2", "kind": "os_nic", "addresses": []}])
    assert out[0]["addresses"] == []


def test_windows_addr_end_to_end_via_build():
    # build_windows_network 통과 시 5키가 모두 부여되는지 (팀 master 도)
    base = [_wifc("Team1", ["10.0.0.10"])]
    net = build_windows_network(base, LBFO_LINES)
    a = next(i for i in net["interfaces"] if i["name"] == "Team1")["addresses"][0]
    for k in ("scope", "label", "parent_interface", "is_alias", "is_secondary"):
        assert k in a
    assert a["is_alias"] is False and a["parent_interface"] == "Team1"


def test_windows_addr_does_not_mutate_input():
    base = [_wifc("Ethernet4", ["192.168.50.40", "192.168.50.41"])]
    snap = json.loads(json.dumps(base))
    enrich_windows_addresses(base)
    assert base == snap  # 원본 불변


# ---------------------------------------------------------------------------
# enrich 입력 mutation 금지 (immutability)
# ---------------------------------------------------------------------------
def test_enrich_does_not_mutate_input():
    base = [_iface("bond0", "10.0.0.5", "aa")]
    snapshot = json.loads(json.dumps(base))
    build_linux_network(base, ONE_BOND)
    assert base == snapshot  # 원본 불변


# ---------------------------------------------------------------------------
# 커버리지 보강 (리뷰 지적 — enrich 분기)
# ---------------------------------------------------------------------------
def test_enrich_existing_slave_in_base_keeps_ip():
    """드문 경우: slave 가 IP 를 가져 base 에 이미 존재 → enrich 하되 IP 보존(faithful)."""
    base = [
        _iface("bond0", "10.0.0.5", "aa:00"),
        _iface("eth0", "10.0.0.99", "00:11:22:33:44:00"),  # slave 인데 IP 보유(이례적)
    ]
    net = build_linux_network(base, ONE_BOND)
    eth0 = next(i for i in net["interfaces"] if i["name"] == "eth0")
    assert eth0["bond_role"] == "slave"
    assert eth0["bond_master"] == "bond0"
    assert eth0["slave_state"] == "active"
    # 이미 IP 가 있으면 날조 제거 안 함 — 실제값 보존
    assert eth0["addresses"][0]["address"] == "10.0.0.99"
    # 중복 추가되지 않음 (eth0 단 1개)
    assert [i["name"] for i in net["interfaces"]].count("eth0") == 1


def test_vlan_without_ip_synthesized():
    """VLAN 이 topology 에는 있으나 base 에 없을 때(IP 없음) → 인터페이스로 추가."""
    lines = ["VLANIF|eth0.50|eth0|50"]
    base = [_iface("eth0", "10.0.0.1", "aa")]   # eth0.50 은 base 에 없음
    net = build_linux_network(base, lines)
    vlan = next((i for i in net["interfaces"] if i["name"] == "eth0.50"), None)
    assert vlan is not None
    assert vlan["vlan_id"] == 50
    assert vlan["vlan_parent"] == "eth0"
    assert vlan["addresses"] == []
    assert vlan["mac"] is None


# 18. Windows 팀 위 VLAN tNIC (LBFOTEAMNIC) — Linux bond0.100 대응
#     실장비 캡처: site 10.100.64.120 (LabTeam1 + 'LabTeam1 - VLAN 100' VlanID=100)
LBFO_VLAN_LINES = LBFO_LINES + [
    'LBFOTEAMNIC {"name":"Team1","team":"Team1","vlan_id":null,"default":true}',
    'LBFOTEAMNIC {"name":"Team1 - VLAN 100","team":"Team1","vlan_id":100,"default":false}',
]


def test_windows_parse_team_nics():
    nics = parse_windows_team_nics(LBFO_VLAN_LINES)
    # default tNIC + VLAN tNIC 둘 다 파싱 (enrich 단계에서 vlan_id 유무로 분기)
    assert {n["name"] for n in nics} == {"Team1", "Team1 - VLAN 100"}
    vlan = next(n for n in nics if n["name"] == "Team1 - VLAN 100")
    assert vlan["vlan_id"] == 100 and vlan["team"] == "Team1"
    default = next(n for n in nics if n["name"] == "Team1")
    assert default["vlan_id"] is None  # default tNIC = 팀 자체 (VLAN 아님)


def test_windows_team_vlan_enriches_interface():
    # 'Team1 - VLAN 100' 가 자체 IP 보유한 별도 인터페이스 (Multiplexor #2)
    base = [
        _iface("Team1", "10.0.0.10", "00-11-22-33-44-00", speed=20000),
        _iface("Team1 - VLAN 100", "10.0.100.10", "00-11-22-33-44-00", speed=20000),
    ]
    net = build_windows_network(base, LBFO_VLAN_LINES)
    by = {i["name"]: i for i in net["interfaces"]}
    # 팀 master 는 team_role master, VLAN 키 없음
    assert by["Team1"]["team_role"] == "master"
    assert "vlan_id" not in by["Team1"]
    # VLAN tNIC: vlan_id/vlan_parent enrich (Linux bond0.100 일관)
    assert by["Team1 - VLAN 100"]["vlan_id"] == 100
    assert by["Team1 - VLAN 100"]["vlan_parent"] == "Team1"
    # VLAN tNIC 는 team master/member 아님 (자체 역할 없음)
    assert "team_role" not in by["Team1 - VLAN 100"]
    # 자체 IP 보존
    assert by["Team1 - VLAN 100"]["addresses"][0]["address"] == "10.0.100.10"


def test_windows_no_team_nic_lines_is_additive_only():
    """LBFOTEAMNIC 라인 없는 호스트(구 동작): vlan_id/vlan_parent 키 미추가 (back-compat)."""
    base = [_iface("Team1", "10.0.0.10", "00-11-22-33-44-00")]
    net = build_windows_network(base, LBFO_LINES)  # LBFOTEAMNIC 없음
    master = next(i for i in net["interfaces"] if i["name"] == "Team1")
    assert "vlan_id" not in master and "vlan_parent" not in master


def test_windows_member_already_in_base():
    """드문 경우: 팀 member 가 base 에 이미 존재 → enrich (team_role=member)."""
    base = [
        _iface("Team1", "10.0.0.10", "00-11-22-33-44-00"),
        _iface("Ethernet", "10.0.0.50", "00-11-22-33-44-00"),  # member 인데 base 에 존재
    ]
    net = build_windows_network(base, LBFO_LINES)
    mem = next(i for i in net["interfaces"] if i["name"] == "Ethernet")
    assert mem["team_role"] == "member"
    assert mem["team_master"] == "Team1"
    assert mem["addresses"][0]["address"] == "10.0.0.50"  # 기존 IP 보존
    assert [i["name"] for i in net["interfaces"]].count("Ethernet") == 1


def test_perm_hwaddr_precedence_slmeta_then_bslave():
    """perm_hwaddr 우선순위: SLMETA(sysfs) → BSLAVE(proc) fallback (SLMETA 빈값 시)."""
    # SLMETA perm 빈값, BSLAVE perm 있음 → BSLAVE 사용
    lines = [
        "BOND|bond0|active-backup|eth0|100|slow|layer2|eth0|stable|eth0",
        "BSLAVE|bond0|eth0|active|up|00:11:22:33:44:AA|10000|0",
        "SLMETA|bond0|eth0|1500|up|10000|",   # perm 빈값
    ]
    b = parse_linux_net_topology(lines)["bonds"][0]
    assert b["slaves"][0]["perm_hwaddr"] == "00:11:22:33:44:AA"  # BSLAVE fallback


# ---------------------------------------------------------------------------
# 실커널 검증 (RHEL 8.10 dummy 인터페이스, SSH NIC 미접촉·검증후 삭제)
# ---------------------------------------------------------------------------
# /sys/class/net/<bond>/bonding/mode 실제 파일값 (mode 이름 + 숫자 인덱스).
# collector 가 awk '{print $1}' 로 첫 토큰 추출 → filter 는 그 값을 받는다.
REAL_MODE_FILES = [
    ("balance-rr", "balance-rr 0"), ("active-backup", "active-backup 1"),
    ("balance-xor", "balance-xor 2"), ("broadcast", "broadcast 3"),
    ("802.3ad", "802.3ad 4"), ("balance-tlb", "balance-tlb 5"),
    ("balance-alb", "balance-alb 6"),
]


@pytest.mark.parametrize("expected,mode_file", REAL_MODE_FILES)
def test_real_kernel_all_bond_modes(expected, mode_file):
    """7개 bond 모드 전부 실커널 mode 파일값 → 정확한 mode 이름 파싱 (실장비 확인)."""
    emitted = mode_file.split()[0]   # collector awk '{print $1}'
    assert emitted == expected
    line = "BOND|btest|%s|bd0|0|slow|layer2||stable|bd0 bd1" % emitted
    b = parse_linux_net_topology([line])["bonds"][0]
    assert b["mode"] == expected


def test_real_kernel_vlan_on_bond_fixture():
    """실커널 VLAN-on-bond 캡처: VLAN→bond 부모 연결 + bond IP / VLAN IP / slave 무IP.

    실장비(RHEL 8.10)에서 /proc/net/vlan/config 가 Permission denied 였으나 ip -d link
    소스로 VLANIF 정상 emit (다중소스 graceful). slave speed 는 dummy 라 'Unknown'→None.
    """
    lines = _topo_lines("bond_vlan_realkernel_topo.txt")
    base = [
        {"id": "btest", "name": "btest", "kind": "os_nic", "mac": None, "mtu": 1500,
         "speed_mbps": None, "link_status": "up", "is_primary": False,
         "addresses": [{"family": "ipv4", "address": "192.0.2.10", "prefix_length": 24,
                        "subnet_mask": "255.255.255.0", "gateway": None}]},
        {"id": "bvlan100", "name": "bvlan100", "kind": "os_nic", "mac": None, "mtu": 1500,
         "speed_mbps": None, "link_status": "up", "is_primary": False,
         "addresses": [{"family": "ipv4", "address": "198.51.100.10", "prefix_length": 24,
                        "subnet_mask": "255.255.255.0", "gateway": None}]},
    ]
    net = build_linux_network(base, lines)
    by = {i["name"]: i for i in net["interfaces"]}
    # VLAN: bond 부모 연결 + 자체 IP 유지
    assert by["bvlan100"]["vlan_id"] == 100
    assert by["bvlan100"]["vlan_parent"] == "btest"
    assert by["bvlan100"]["addresses"][0]["address"] == "198.51.100.10"
    # bond master: IP 보유
    assert by["btest"]["bond_role"] == "master"
    assert by["btest"]["addresses"][0]["address"] == "192.0.2.10"
    # 물리 slave: IP 없음, speed Unknown→None (실커널 graceful)
    for sl in ("bd0", "bd1"):
        assert by[sl]["bond_role"] == "slave"
        assert by[sl]["addresses"] == []
        assert by[sl]["speed_mbps"] is None


def test_rhel96_expected_fixture_python_path_topology():
    """RHEL 9.6 python 경로 실 캡처 기반 기대 fixture 의 bond 토폴로지 회귀 고정."""
    net = json.loads((FIX / "rhel96_bond_network.expected.json").read_text(encoding="utf-8"))
    assert [b["name"] for b in net["bonds"]] == ["bond1", "bond2"]
    b1 = next(b for b in net["bonds"] if b["name"] == "bond1")
    assert b1["mode"] == "active-backup"
    assert b1["active_slave"] == "ens161"
    assert b1["addresses"][0]["address"] == "10.100.64.167"  # bond 에 IP (primary)
    # bond alias(bond1:1) 가 parent addresses[] 에 병합 (python 경로, server 165)
    assert b1["addresses"][1]["address"] == "10.100.10.102"
    assert b1["addresses"][1]["label"] == "bond1:1" and b1["addresses"][1]["is_alias"] is True
    by_name = {i["name"]: i for i in net["interfaces"]}
    assert "bond1:1" not in by_name  # alias 는 별도 인터페이스 아님
    for sl in ("ens161", "ens193", "ens225", "ens256"):
        assert by_name[sl]["bond_role"] == "slave"
        assert by_name[sl]["addresses"] == []
    assert by_name["bond1"]["bond_role"] == "master"
    assert by_name["bond1"]["addresses"][1]["address"] == "10.100.10.102"  # iface ↔ bond 일관
    assert "bond_role" not in by_name["ens192"]  # 일반 NIC 불변


# ===========================================================================
# bond alias / secondary IP 수집 (parse_linux_addresses + merge_linux_addresses)
# 실장비 캡처: 10.100.64.161(RHEL 8.10) / 10.100.64.165(RHEL 9.6) bond1:1/bond2:1
# ===========================================================================
def _base_bond(name, ip, gw=None):
    return {"id": name, "name": name, "kind": "os_nic", "mac": "00:50:56:84:57:81",
            "mtu": 1500, "speed_mbps": 10000, "link_status": "up", "is_primary": False,
            "addresses": [{"family": "ipv4", "address": ip, "prefix_length": 24,
                           "subnet_mask": "255.255.255.0", "gateway": gw}]}


@pytest.mark.parametrize("fixture,bond1_primary,bond1_alias,bond2_alias", [
    ("rhel810_addr.txt", "10.100.64.169", "10.100.10.100", "10.100.10.101"),
    ("rhel96_addr.txt", "10.100.64.167", "10.100.10.102", "10.100.10.103"),
])
def test_parse_addresses_json_real_capture(fixture, bond1_primary, bond1_alias, bond2_alias):
    """ip -j addr show 실 캡처 → bond master primary + alias(bond1:1) 정확 파싱."""
    amap = parse_linux_addresses([_addr_line(fixture)])
    b1 = amap["bond1"]
    assert [a["address"] for a in b1] == [bond1_primary, bond1_alias]
    primary, alias = b1
    assert primary["label"] == "bond1" and primary["is_alias"] is False
    assert primary["scope"] == "global" and primary["family"] == "ipv4"
    assert alias["label"] == "bond1:1" and alias["is_alias"] is True
    assert alias["parent_interface"] == "bond1" and alias["scope"] == "global"
    assert alias["prefix_length"] == 24 and alias["subnet_mask"] == "255.255.255.0"
    assert alias["is_secondary"] is False  # 다른 서브넷 alias → 커널 secondary 아님
    assert amap["bond2"][1]["address"] == bond2_alias
    # IPv6 link-local 도 수집 (label 없음 → 부모 ifname, is_alias False)
    v6 = [a for a in amap["ens192"] if a["family"] == "ipv6"]
    assert v6 and v6[0]["scope"] == "link" and v6[0]["is_alias"] is False


def test_parse_addresses_tier2_ip_o():
    """2순위 ip -o addr show 라인 파싱 — label '\\' 앞 마지막 토큰."""
    lines = [
        r"ADDRO|9: bond1    inet 10.100.64.169/24 brd 10.100.64.255 scope global noprefixroute bond1\       valid_lft forever preferred_lft forever",
        r"ADDRO|9: bond1    inet 10.100.10.100/24 scope global bond1:1\       valid_lft forever preferred_lft forever",
        r"ADDRO|2: ens192    inet6 fe80::250:56ff:fe84:b4/64 scope link noprefixroute \       valid_lft forever",
    ]
    amap = parse_linux_addresses(lines)
    assert [a["address"] for a in amap["bond1"]] == ["10.100.64.169", "10.100.10.100"]
    assert amap["bond1"][0]["is_alias"] is False and amap["bond1"][1]["is_alias"] is True
    assert amap["bond1"][1]["label"] == "bond1:1"
    assert amap["ens192"][0]["family"] == "ipv6" and amap["ens192"][0]["scope"] == "link"


def test_parse_addresses_tier3_ifconfig():
    """3순위 ifconfig -a (net-tools) — alias 는 'bond1:1:' stanza 헤더."""
    lines = [
        "ADDRIFC|bond1: flags=5187<UP,BROADCAST,RUNNING,MASTER,MULTICAST>  mtu 1500",
        "ADDRIFC|        inet 10.100.64.169  netmask 255.255.255.0  broadcast 10.100.64.255",
        "ADDRIFC|bond1:1: flags=5187<UP,BROADCAST,RUNNING,MASTER,MULTICAST>  mtu 1500",
        "ADDRIFC|        inet 10.100.10.100  netmask 255.255.255.0  broadcast 0.0.0.0",
    ]
    amap = parse_linux_addresses(lines)
    assert [a["address"] for a in amap["bond1"]] == ["10.100.64.169", "10.100.10.100"]
    alias = amap["bond1"][1]
    assert alias["label"] == "bond1:1" and alias["is_alias"] is True
    assert alias["prefix_length"] == 24 and alias["subnet_mask"] == "255.255.255.0"


def test_parse_addresses_json_beats_ip_o():
    """ADDRJSON(1순위) 이 ADDRO(2순위) 보다 우선."""
    lines = [
        r"ADDRO|9: bond1    inet 10.0.0.1/24 scope global bond1\  valid_lft forever",
        'ADDRJSON|[{"ifindex":9,"ifname":"bond1","addr_info":[{"family":"inet","local":"10.9.9.9","prefixlen":24,"scope":"global","label":"bond1"}]}]',
    ]
    amap = parse_linux_addresses(lines)
    assert amap["bond1"][0]["address"] == "10.9.9.9"  # JSON 우선


@pytest.mark.parametrize("empty", [None, [], [""], ["BOND|bond0|x"], ["ADDRJSON|"]])
def test_parse_addresses_empty_or_garbage(empty):
    assert parse_linux_addresses(empty) == {}


def test_merge_appends_alias_to_parent_bond():
    """merge: bond master 의 alias 를 parent addresses[] 에 append (신규 iface 아님)."""
    base = [_base_bond("bond1", "10.100.64.169")]
    merged = merge_linux_addresses(base, [_addr_line("rhel810_addr.txt")])
    assert [i["name"] for i in merged] == ["bond1"]  # 인터페이스 수 불변 (alias 별도 생성 X)
    addrs = merged[0]["addresses"]
    assert [a["address"] for a in addrs] == ["10.100.64.169", "10.100.10.100"]
    assert addrs[0]["is_alias"] is False and addrs[1]["is_alias"] is True
    assert addrs[1]["label"] == "bond1:1" and addrs[1]["parent_interface"] == "bond1"


def test_merge_preserves_existing_gateway_alias_gateway_none():
    """merge: 기존 primary 의 gateway 보존, alias 는 gateway None."""
    base = [_base_bond("bond1", "10.100.64.169", gw="10.100.64.254")]
    merged = merge_linux_addresses(base, [_addr_line("rhel810_addr.txt")])
    addrs = merged[0]["addresses"]
    assert addrs[0]["gateway"] == "10.100.64.254"  # primary gateway 보존
    assert addrs[1]["gateway"] is None             # alias gateway 없음


def test_merge_no_addr_lines_is_additive_only():
    """alias 없는 서버(=ADDR 라인 없음): 신규 키만 부여, 주소 수/값 불변 (back-compat)."""
    base = [_base_bond("bond1", "10.100.64.169", gw="10.100.64.254")]
    merged = merge_linux_addresses(base, ["BOND|bond1|active-backup|ens161|100|slow|layer2|ens161|stable|ens161 ens193"])
    addrs = merged[0]["addresses"]
    assert len(addrs) == 1                          # 신규 주소 추가 없음
    assert addrs[0]["address"] == "10.100.64.169"
    assert addrs[0]["gateway"] == "10.100.64.254"   # 기존 값 보존
    assert addrs[0]["is_alias"] is False and addrs[0]["label"] == "bond1"  # 신규 키 default
    assert addrs[0]["parent_interface"] == "bond1" and addrs[0]["is_secondary"] is False


def test_merge_full_chain_mirrors_alias_to_bonds_and_keeps_slaves_empty():
    """merge → build: alias 가 bonds[].addresses 로 mirror, slave 는 IP 없음 유지."""
    base = [_base_bond("bond1", "10.100.64.169")]
    topo = ["BOND|bond1|active-backup|ens161|100|slow|layer2|ens161|stable|ens161 ens193",
            "SLSTATE|ens161|active", "SLSTATE|ens193|backup",
            "SLMETA|bond1|ens161|1500|up|10000|aa:00", "SLMETA|bond1|ens193|1500|up|10000|aa:01"]
    lines = topo + [_addr_line("rhel810_addr.txt")]
    net = build_linux_network(merge_linux_addresses(base, lines), lines)
    bond = net["bonds"][0]
    assert [a["address"] for a in bond["addresses"]] == ["10.100.64.169", "10.100.10.100"]
    assert bond["addresses"][1]["is_alias"] is True
    assert bond["mode"] == "active-backup" and bond["active_slave"] == "ens161"  # 메타 불변
    slaves = [i for i in net["interfaces"] if i.get("bond_role") == "slave"]
    assert all(s["addresses"] == [] for s in slaves)  # slave 물리 NIC IP 없음 유지


def test_merge_does_not_mutate_input():
    """merge 입력 mutation 금지 (immutability)."""
    base = [_base_bond("bond1", "10.100.64.169", gw="10.100.64.254")]
    snapshot = json.loads(json.dumps(base))
    merge_linux_addresses(base, [_addr_line("rhel810_addr.txt")])
    assert base == snapshot
