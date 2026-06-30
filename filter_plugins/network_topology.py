#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# network_topology.py — Linux 네트워크 토폴로지(bond/vlan/bridge/team) 필터 플러그인
#
# os-gather/tasks/linux/gather_network.yml 의 python_ok / raw fallback 두 경로가 공통으로
# 호출한다. controller 측에서 실행되므로 stdlib 만 사용 (원격 Python 불필요 — raw 경로 호환).
#
# 입력: collector 가 emit 한 '|' 구분 라인 목록 (BOND/BSLAVE/SLSTATE/SLMETA/VLANIF/BRIDGE/TEAM)
#       + 기존 네트워크 수집 로직이 만든 base interfaces 리스트.
# 출력: 기존 구조와 호환되는 하위 필드 추가 (Additive only — rule 96 R1-B).
#         data.network.bonds[]    : bond master + slave 토폴로지 (신규)
#         data.network.bridges[]  : bridge + member (신규)
#         data.network.teams[]    : Linux teamd 팀 (신규, Windows 와 키 일관)
#         interfaces[] 에 bond_role/bond_master/bond_mode/active_slave/slave_state/vlan_* 추가
#
# 설계 원칙:
#   - 여러 소스(sysfs/proc/ip)를 병합하되 우선순위 명확화 — 일부 소스 부재해도 graceful.
#   - 모든 파싱은 방어적 (필드 수 부족/빈 값/예상外 형식 → 해당 항목만 skip, 전체 불멈춤).
#   - 새 dict 만 생성 (입력 mutation 금지 — immutability).

from __future__ import annotations

import json as _json


def _aslist(value):
    """PowerShell ConvertTo-Json 은 1원소 배열을 스칼라로 직렬화 → str/list 모두 list 로."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_int(value):
    """문자열/숫자 → int 또는 None (빈 값·비숫자 방어)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # 음수(-1=speed unknown) 및 비숫자 방어
    try:
        n = int(s)
    except (ValueError, TypeError):
        return None
    return n


def _clean(value):
    """빈 문자열/공백 → None."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _norm_link(operstate, mii_status):
    """operstate/mii_status → canonical up/down/unknown (rule: link_status enum 통일)."""
    for v in (operstate, mii_status):
        if v is None:
            continue
        s = str(v).strip().lower()
        if s in ("up", "linkup", "active"):
            return "up"
        if s in ("down", "linkdown", "lowerlayerdown", "notpresent", "not present"):
            return "down"
    return "unknown"


def _split_line(line):
    """'|' 구분 라인 → (tag, parts). 비문자/빈 라인은 (None, [])."""
    if not isinstance(line, str):
        return None, []
    s = line.strip()
    if not s or "|" not in s:
        return None, []
    parts = s.split("|")
    return parts[0], parts


def parse_linux_net_topology(lines):
    """collector 출력 라인 → {'bonds':[...], 'bridges':[...], 'teams':[...]}.

    bonds[] 각 항목은 slaves[] 를 포함한다. 입력이 비거나 None 이면 빈 구조 반환.
    """
    if not lines:
        return {"bonds": [], "bridges": [], "teams": [], "vlans": []}

    bonds = {}        # name -> bond dict (slaves 채우기 전)
    bond_order = []   # 발견 순서 보존
    bslave = {}       # slave name -> {bond,state,mii,perm,speed,lfc}
    slstate = {}      # slave name -> state (ip -d link, 전 모드 권위)
    slmeta = {}       # slave name -> {master,mtu,operstate,speed,perm}
    bridges = {}
    bridge_order = []
    teams = {}
    team_order = []
    vlans = {}        # name -> {parent, vlan_id}
    vlan_order = []

    for line in lines:
        tag, parts = _split_line(line)
        if tag == "BOND" and len(parts) >= 10:
            name = _clean(parts[1])
            if not name:
                continue
            if name not in bonds:
                bond_order.append(name)
            bonds[name] = {
                "name": name,
                "mode": _clean(parts[2]),
                "active_slave": _clean(parts[3]),
                "miimon": _to_int(parts[4]),
                "lacp_rate": _clean(parts[5]),
                "xmit_hash_policy": _clean(parts[6]),
                "primary": _clean(parts[7]),
                "ad_select": _clean(parts[8]),
                "_slave_names": [s for s in parts[9].split() if s],
            }
        elif tag == "BSLAVE" and len(parts) >= 8:
            sl = _clean(parts[2])
            if not sl:
                continue
            bslave[sl] = {
                "bond": _clean(parts[1]),
                "state": _clean(parts[3]),
                "mii": _clean(parts[4]),
                "perm": _clean(parts[5]),
                "speed": parts[6],
                "lfc": parts[7],
            }
        elif tag == "SLSTATE" and len(parts) >= 3:
            sl = _clean(parts[1])
            if sl:
                slstate[sl] = _clean(parts[2])
        elif tag == "SLMETA" and len(parts) >= 7:
            sl = _clean(parts[2])
            if sl:
                slmeta[sl] = {
                    "master": _clean(parts[1]),
                    "mtu": parts[3],
                    "operstate": _clean(parts[4]),
                    "speed": parts[5],
                    "perm": _clean(parts[6]),
                }
        elif tag == "VLANIF" and len(parts) >= 4:
            n = _clean(parts[1])
            if n and n not in vlans:
                vlan_order.append(n)
            if n:
                vlans[n] = {"name": n, "parent": _clean(parts[2]),
                            "vlan_id": _to_int(parts[3])}
        elif tag == "BRIDGE" and len(parts) >= 2:
            br = _clean(parts[1])
            if not br:
                continue
            members = [m for m in (parts[2].split() if len(parts) >= 3 else []) if m]
            if br not in bridges:
                bridge_order.append(br)
            bridges[br] = members
        elif tag == "TEAM" and len(parts) >= 2:
            t = _clean(parts[1])
            if not t:
                continue
            mode = _clean(parts[2]) if len(parts) >= 3 else None
            members = [m for m in (parts[3].split() if len(parts) >= 4 else []) if m]
            if t not in teams:
                team_order.append(t)
            teams[t] = {"name": t, "mode": mode, "members": members}

    def _slave_names_for(bond_name, declared):
        """sysfs slaves 우선, 없으면 SLMETA master 역참조 (proc/sysfs 부분 부재 방어)."""
        if declared:
            return list(declared)
        return [s for s, m in slmeta.items() if m.get("master") == bond_name]

    def _build_slave(name, bond_name):
        meta = slmeta.get(name, {})
        bs = bslave.get(name, {})
        speed = _to_int(meta.get("speed"))
        if speed is None:
            speed = _to_int(bs.get("speed"))
        perm = meta.get("perm") or bs.get("perm")
        state = slstate.get(name) or bs.get("state")
        return {
            "name": name,
            "state": state,
            "mii_status": bs.get("mii"),
            "perm_hwaddr": perm,
            "speed_mbps": speed,
            "link_failure_count": _to_int(bs.get("lfc")),
            "mtu": _to_int(meta.get("mtu")),
            "link_status": _norm_link(meta.get("operstate"), bs.get("mii")),
            "bond": bond_name,
        }

    bonds_out = []
    for name in bond_order:
        b = bonds[name]
        slave_names = _slave_names_for(name, b.pop("_slave_names"))
        b["slaves"] = [_build_slave(s, name) for s in slave_names]
        b["addresses"] = []  # enrich 단계에서 bond iface IP 주입
        bonds_out.append(b)

    bridges_out = [{"name": n, "members": bridges[n]} for n in bridge_order]
    teams_out = [teams[n] for n in team_order]
    vlans_out = [vlans[n] for n in vlan_order]
    return {"bonds": bonds_out, "bridges": bridges_out, "teams": teams_out,
            "vlans": vlans_out}


def enrich_linux_interfaces(interfaces, topology):
    """base interfaces + topology → enriched interfaces (Additive, 새 리스트 반환).

    - bond master(기존/신규)에 bond_role/bond_mode/active_slave/bond_slaves 추가
    - slave 물리 NIC 를 interfaces 에 추가 (addresses=[], bond_master/slave_state)
    - IP 없는 bond master 도 추가 (예: VLAN 부모 전용 bond)
    - 기존 일반 NIC dict 는 불변 (키 추가 없음)
    """
    base = list(interfaces or [])
    bonds = (topology or {}).get("bonds") or []
    vlans = {v["name"]: v for v in ((topology or {}).get("vlans") or [])}
    bond_by_name = {b["name"]: b for b in bonds}
    slave_owner = {}      # slave name -> bond name
    slave_detail = {}     # slave name -> slave dict
    for b in bonds:
        for sl in b.get("slaves", []):
            slave_owner[sl["name"]] = b["name"]
            slave_detail[sl["name"]] = sl

    out = []
    present = set()
    for iface in base:
        new = dict(iface)
        name = new.get("name")
        present.add(name)
        if name in bond_by_name:
            b = bond_by_name[name]
            new["bond_role"] = "master"
            new["bond_mode"] = b.get("mode")
            new["active_slave"] = b.get("active_slave")
            new["bond_slaves"] = [s["name"] for s in b.get("slaves", [])]
        if name in vlans:
            new["vlan_id"] = vlans[name].get("vlan_id")
            new["vlan_parent"] = vlans[name].get("parent")
        out.append(new)

    # IP 없는 bond master 추가 (base 에 없을 때만)
    for b in bonds:
        if b["name"] in present:
            continue
        out.append({
            "id": b["name"], "name": b["name"], "kind": "os_nic",
            "mac": None, "mtu": None, "speed_mbps": None,
            "link_status": "unknown", "is_primary": False, "addresses": [],
            "bond_role": "master", "bond_mode": b.get("mode"),
            "active_slave": b.get("active_slave"),
            "bond_slaves": [s["name"] for s in b.get("slaves", [])],
        })
        present.add(b["name"])

    # slave 물리 NIC 추가 (base 에 없을 때) — 이미 있으면 enrich
    for name, owner in slave_owner.items():
        sl = slave_detail[name]
        if name in present:
            for new in out:
                if new.get("name") == name:
                    new["bond_role"] = "slave"
                    new["bond_master"] = owner
                    new["slave_state"] = sl.get("state")
            continue
        out.append({
            "id": name, "name": name, "kind": "os_nic",
            "mac": sl.get("perm_hwaddr"), "mtu": sl.get("mtu"),
            "speed_mbps": sl.get("speed_mbps"),
            "link_status": sl.get("link_status") or "unknown",
            "is_primary": False, "addresses": [],
            "bond_role": "slave", "bond_master": owner,
            "slave_state": sl.get("state"),
        })
        present.add(name)

    # IP 없는 VLAN 인터페이스 추가 (base 에 없을 때만 — 보통 VLAN 이 IP 보유해 이미 존재)
    for name, v in vlans.items():
        if name in present:
            continue
        out.append({
            "id": name, "name": name, "kind": "os_nic",
            "mac": None, "mtu": None, "speed_mbps": None,
            "link_status": "unknown", "is_primary": False, "addresses": [],
            "vlan_id": v.get("vlan_id"), "vlan_parent": v.get("parent"),
        })
        present.add(name)

    return out


def build_linux_network(interfaces, lines):
    """단일 진입점: base interfaces + collector 라인 → {interfaces, bonds, bridges, teams}.

    bonds[].addresses 에는 해당 bond iface 의 IP 를 주입한다 (master IP 위치 명시).
    """
    topo = parse_linux_net_topology(lines)
    addr_by_name = {}
    for iface in (interfaces or []):
        addr_by_name[iface.get("name")] = iface.get("addresses") or []
    bonds = []
    for b in topo["bonds"]:
        nb = dict(b)
        nb["addresses"] = list(addr_by_name.get(b["name"], []))
        bonds.append(nb)
    topo_for_enrich = {"bonds": bonds, "bridges": topo["bridges"],
                       "teams": topo["teams"], "vlans": topo.get("vlans", [])}
    enriched = enrich_linux_interfaces(interfaces, topo_for_enrich)
    return {
        "interfaces": enriched,
        "bonds": bonds,
        "bridges": topo["bridges"],
        "teams": topo["teams"],
    }


# =============================================================================
# Per-address 수집 (bond alias / secondary IP 포함) — Linux 공통, 다중 소스 3-tier
# =============================================================================
# collector(gather_network.yml _l_net_collector)가 emit 한 주소 라인을 파싱한다.
# 우선순위: ADDRJSON| (ip -j addr show, 1순위 — 가장 견고) >
#           ADDRO|     (ip -o addr show, 2순위) >
#           ADDRIFC|   (ifconfig -a,    3순위, net-tools 부재 환경 폴백)
# nmcli / ifcfg 파일에 의존하지 않는다 (NetworkManager 부재·배포판 차이에 강건).
#
# 산출 주소 레코드는 기존 5 키(family/address/prefix_length/subnet_mask/gateway)를
# 유지하고 다음을 *추가*한다 (Additive — rule 96 R1-B):
#   scope            : global/link/host/site (없으면 None)
#   label            : ip 의 주소 label (alias 면 'bond1:1' 등, 없으면 부모 ifname)
#   parent_interface : 이 주소가 실제 바인딩된 인터페이스(=ip 의 dev)
#   is_alias         : label 이 parent_interface 와 다르면 True (예: bond1:1)
#   is_secondary     : 커널 secondary 플래그(같은 서브넷 2번째+ IPv4). 없으면 False
#
# bond alias(bond1:1)는 새 인터페이스가 아니라 parent bond 의 추가 IP 이므로,
# 별도 interfaces[] 항목을 만들지 않고 parent 의 addresses[] 에 append 한다.

_ADDR_NEW_KEYS = ("scope", "label", "parent_interface", "is_alias", "is_secondary")
# ip -o addr show 의 flag 토큰(주소 label 후보에서 제외)
_IP_O_FLAGS = frozenset({
    "brd", "scope", "secondary", "primary", "dynamic", "mngtmpaddr",
    "noprefixroute", "tentative", "deprecated", "temporary", "home",
    "nodad", "optimistic", "stable-privacy", "valid_lft", "preferred_lft",
    "forever", "global", "link", "host", "site", "nowait",
})


def _prefix_to_mask(prefixlen):
    """IPv4 prefix length → dotted subnet mask ('255.255.255.0'). 범위 밖이면 None."""
    p = _to_int(prefixlen)
    if p is None or p < 0 or p > 32:
        return None
    bits = (0xFFFFFFFF << (32 - p)) & 0xFFFFFFFF if p > 0 else 0
    return ".".join(str((bits >> (8 * (3 - i))) & 0xFF) for i in range(4))


def _mask_to_prefix(mask):
    """dotted subnet mask → prefix length(int). 비정상 입력은 None (ifconfig 폴백용)."""
    if not mask:
        return None
    try:
        return sum(bin(int(o)).count("1") for o in str(mask).split("."))
    except (ValueError, TypeError):
        return None


def _norm_family(fam):
    """'inet'/'inet6' → 'ipv4'/'ipv6' (기존 출력 컨벤션 유지)."""
    f = (fam or "").strip().lower()
    if f in ("inet", "ipv4"):
        return "ipv4"
    if f in ("inet6", "ipv6"):
        return "ipv6"
    return f or None


def _addr_record(ifname, family, address, prefixlen, scope, label, secondary):
    """단일 주소 레코드 생성 (기존 5 키 + 신규 5 키). 입력 mutation 없음."""
    fam = _norm_family(family)
    lbl = _clean(label) or ifname
    return {
        "family": fam,
        "address": address,
        "prefix_length": _to_int(prefixlen),
        "subnet_mask": _prefix_to_mask(prefixlen) if fam == "ipv4" else None,
        "gateway": None,
        "scope": _clean(scope),
        "label": lbl,
        "parent_interface": ifname,
        "is_alias": bool(_clean(label)) and _clean(label) != ifname,
        "is_secondary": bool(secondary),
    }


def _parse_addr_json(flat):
    """ip -j addr show (compact JSON 한 줄) → {ifname: [addr_record]}."""
    out = {}
    try:
        data = _json.loads(flat)
    except (ValueError, TypeError):
        return out
    if not isinstance(data, list):
        return out
    for link in data:
        if not isinstance(link, dict):
            continue
        ifname = _clean(link.get("ifname"))
        if not ifname:
            continue
        for a in link.get("addr_info") or []:
            if not isinstance(a, dict):
                continue
            local = _clean(a.get("local"))
            if not local:
                continue
            out.setdefault(ifname, []).append(_addr_record(
                ifname, a.get("family"), local, a.get("prefixlen"),
                a.get("scope"), a.get("label"), a.get("secondary", False),
            ))
    return out


def _parse_addr_o(lines):
    """ip -o addr show 라인 → {ifname: [addr_record]} (2순위 폴백).

    형식: '<idx>: <dev>  <fam> <cidr> [brd B] scope <s> [secondary] [<label>]\\ ...'
    label 은 '\\' 앞 마지막 토큰 — primary 면 dev, alias 면 'dev:N'.
    """
    out = {}
    for raw in lines:
        if not isinstance(raw, str):
            continue
        head = raw.split("\\", 1)[0]
        toks = head.split()
        if len(toks) < 4:
            continue
        dev = toks[1]
        fam = toks[2]
        if fam not in ("inet", "inet6"):
            continue
        cidr = toks[3]
        address, _, plen = cidr.partition("/")
        rest = toks[4:]
        scope = None
        secondary = False
        i = 0
        while i < len(rest):
            if rest[i] == "scope" and i + 1 < len(rest):
                scope = rest[i + 1]
                i += 2
                continue
            if rest[i] == "secondary":
                secondary = True
            i += 1
        label = None
        if rest:
            last = rest[-1]
            if last == dev or (":" in last and "/" not in last
                               and last not in _IP_O_FLAGS):
                label = last
        out.setdefault(dev, []).append(
            _addr_record(dev, fam, address, plen or None, scope, label, secondary))
    return out


def _parse_addr_ifconfig(lines):
    """ifconfig -a 라인 → {ifname: [addr_record]} (3순위 폴백, net-tools).

    stanza 헤더 '<label>: flags=...' 의 label(예: bond1:1)에서 부모 dev 추출.
    """
    out = {}
    cur_label = None
    cur_dev = None
    for raw in lines:
        if not isinstance(raw, str) or not raw:
            continue
        if not raw[0].isspace() and "flags=" in raw:
            hdr = raw.split()[0].rstrip(":")
            cur_label = hdr
            cur_dev = hdr.split(":")[0]
            continue
        if cur_dev is None:
            continue
        s = raw.strip()
        if s.startswith("inet6 "):
            parts = s.split()
            address = parts[1] if len(parts) > 1 else None
            if not address:
                continue
            plen = None
            scope = "global"
            for j, t in enumerate(parts):
                if t == "prefixlen" and j + 1 < len(parts):
                    plen = parts[j + 1]
            low = s.lower()
            if "<link>" in low or "scopeid 0x20" in low:
                scope = "link"
            elif "<host>" in low or "scopeid 0x10" in low:
                scope = "host"
            out.setdefault(cur_dev, []).append(
                _addr_record(cur_dev, "inet6", address, plen, scope, None, False))
        elif s.startswith("inet "):
            parts = s.split()
            address = parts[1] if len(parts) > 1 else None
            if not address:
                continue
            mask = None
            for j, t in enumerate(parts):
                if t == "netmask" and j + 1 < len(parts):
                    mask = parts[j + 1]
            label = cur_label if cur_label != cur_dev else None
            out.setdefault(cur_dev, []).append(_addr_record(
                cur_dev, "inet", address, _mask_to_prefix(mask), "global", label, False))
    return out


def parse_linux_addresses(lines):
    """collector 라인 → {ifname: [addr_record]}. ADDRJSON > ADDRO > ADDRIFC 우선.

    입력이 비거나 주소 라인이 없으면 {} 반환 (호출측 merge 가 default 키만 부여).
    """
    if not lines:
        return {}
    json_blobs, o_lines, ifc_lines = [], [], []
    for ln in lines:
        if not isinstance(ln, str):
            continue
        if ln.startswith("ADDRJSON|"):
            json_blobs.append(ln[len("ADDRJSON|"):])
        elif ln.startswith("ADDRO|"):
            o_lines.append(ln[len("ADDRO|"):])
        elif ln.startswith("ADDRIFC|"):
            ifc_lines.append(ln[len("ADDRIFC|"):])
    for blob in json_blobs:
        m = _parse_addr_json(blob)
        if m:
            return m
    if o_lines:
        m = _parse_addr_o(o_lines)
        if m:
            return m
    if ifc_lines:
        return _parse_addr_ifconfig(ifc_lines)
    return {}


def merge_linux_addresses(interfaces, lines):
    """base interfaces + collector 라인 → addresses[] 에 alias/secondary 병합 (새 리스트).

    - 기존 주소: (family,address) 일치 시 신규 5 키로 enrich (기존 값 보존, gateway 유지)
    - collector 에만 있는 주소(=alias 등): parent 인터페이스 addresses[] 에 append
    - collector 데이터가 없는 주소: 신규 5 키를 안전한 default 로 부여 (Additive 일관성)
    - bond master 의 addresses 에 alias 가 들어가면 build_linux_network 가 자동으로
      bonds[].addresses 로 mirror (bond master ↔ bonds[] 일관성 자동 보장)
    """
    addr_map = parse_linux_addresses(lines)
    out = []
    for iface in interfaces or []:
        new = dict(iface)
        name = new.get("name")
        collected = addr_map.get(name, [])
        col_by_key = {}
        for c in collected:
            col_by_key.setdefault((c["family"], c["address"]), c)
        seen = set()
        merged = []
        for a in (new.get("addresses") or []):
            ea = dict(a)
            key = (ea.get("family"), ea.get("address"))
            seen.add(key)
            c = col_by_key.get(key)
            if c is not None:
                if not ea.get("scope") and c.get("scope") is not None:
                    ea["scope"] = c.get("scope")
                elif "scope" not in ea:
                    ea["scope"] = c.get("scope")
                ea["label"] = c.get("label")
                ea["parent_interface"] = c.get("parent_interface")
                ea["is_alias"] = c.get("is_alias")
                ea["is_secondary"] = c.get("is_secondary")
            else:
                ea.setdefault("scope", None)
                ea["label"] = name
                ea["parent_interface"] = name
                ea["is_alias"] = False
                ea.setdefault("is_secondary", False)
            merged.append(ea)
        for c in collected:
            key = (c["family"], c["address"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(c))
        new["addresses"] = merged
        out.append(new)
    return out


# =============================================================================
# Windows teaming (LBFO / Switch Embedded Teaming) — gather_network.yml(windows)
# =============================================================================
# PowerShell 이 emit 한 'TAG {json}' 라인 파싱:
#   LBFOTEAM   : Get-NetLbfoTeam (name/teaming_mode/load_balancing/lacp_timer/status/members)
#   LBFOMEMBER : Get-NetLbfoTeamMember (name/team/admin_mode/...)
#   SETTEAM    : Get-NetSwitchTeam (name/members)
#   SETMEMBER  : Get-NetSwitchTeamMember (name/team)
#   WADP       : Get-NetAdapter 보조 맵 (name -> mac/status/speed_mbps)


def _wjson(line, tag):
    """'TAG {json}' 라인에서 tag 일치 시 json dict 반환, 아니면 None."""
    if not isinstance(line, str):
        return None
    s = line.strip()
    prefix = tag + " "
    if not s.startswith(prefix):
        return None
    try:
        obj = _json.loads(s[len(prefix):])
    except (ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _member_name(value):
    """member 항목이 문자열/딕셔너리 어느 쪽이든 이름 추출."""
    if isinstance(value, dict):
        return _clean(value.get("name") or value.get("Name"))
    return _clean(value)


def parse_windows_teams(lines):
    """LBFO + SET 팀 파싱 → teams[] (members 포함). 입력 비면 []."""
    if not lines:
        return []
    lbfo, lbfo_order, lbfo_mem = {}, [], {}
    setn, set_order, set_mem = {}, [], {}
    adp = {}
    for ln in lines:
        d = _wjson(ln, "LBFOTEAM")
        if d:
            name = _clean(d.get("name"))
            if name:
                if name not in lbfo:
                    lbfo_order.append(name)
                lbfo[name] = d
            continue
        d = _wjson(ln, "LBFOMEMBER")
        if d:
            nm = _clean(d.get("name"))
            if nm:
                lbfo_mem[nm] = d
            continue
        d = _wjson(ln, "SETTEAM")
        if d:
            name = _clean(d.get("name"))
            if name:
                if name not in setn:
                    set_order.append(name)
                setn[name] = d
            continue
        d = _wjson(ln, "SETMEMBER")
        if d:
            nm = _clean(d.get("name"))
            if nm:
                set_mem[nm] = d
            continue
        d = _wjson(ln, "WADP")
        if d:
            nm = _clean(d.get("name"))
            if nm:
                adp[nm] = d

    def _members(names, memmap):
        out = []
        for raw in _aslist(names):
            n = _member_name(raw)
            if not n:
                continue
            m = memmap.get(n, {})
            a = adp.get(n, {})
            out.append({
                "name": n,
                "mac": _clean(a.get("mac")) or _clean(m.get("mac")),
                "admin_mode": _clean(m.get("admin_mode")),
                "status": _clean(a.get("status")) or _clean(m.get("status")),
                "speed_mbps": _to_int(a.get("speed_mbps")),
            })
        return out

    teams = []
    for name in lbfo_order:
        d = lbfo[name]
        teams.append({
            "name": name,
            "team_type": "lbfo",
            "teaming_mode": _clean(d.get("teaming_mode")),
            "load_balancing": _clean(d.get("load_balancing")),
            "lacp_timer": _clean(d.get("lacp_timer")),
            "status": _clean(d.get("status")),
            "members": _members(d.get("members"), lbfo_mem),
        })
    for name in set_order:
        d = setn[name]
        teams.append({
            "name": name,
            "team_type": "set",
            "teaming_mode": None,
            "load_balancing": None,
            "lacp_timer": None,
            "status": _clean(d.get("status")),
            "members": _members(d.get("members"), set_mem),
        })
    return teams


def parse_windows_team_nics(lines):
    """LBFOTEAMNIC 라인 → 팀 VLAN tNIC 목록 [{name, team, vlan_id}].

    팀 위 VLAN(예: 'LabTeam1 - VLAN 100')은 Linux 의 bond0.100 에 대응한다.
    default tNIC(VlanID 없음 = 팀 자체)는 vlan_id=None 으로 들어와 enrich 시 무시된다.
    """
    out = []
    for ln in (lines or []):
        d = _wjson(ln, "LBFOTEAMNIC")
        if not d:
            continue
        name = _clean(d.get("name"))
        if not name:
            continue
        out.append({
            "name": name,
            "team": _clean(d.get("team")),
            "vlan_id": _to_int(d.get("vlan_id")),
        })
    return out


def enrich_windows_interfaces(interfaces, teams, team_nics=None):
    """base interfaces + teams → enriched (team_role/team_master 추가, member NIC 추가).

    team_nics(LBFOTEAMNIC) 가 주어지면 팀 위 VLAN tNIC 인터페이스에 vlan_id/vlan_parent 를
    추가한다 (Linux bond0.100 의 vlan_id/vlan_parent 와 동일 키 — 채널 일관, Additive).
    """
    base = list(interfaces or [])
    teams = teams or []
    team_by_name = {t["name"]: t for t in teams}
    member_owner, member_detail = {}, {}
    for t in teams:
        for m in t.get("members", []):
            member_owner[m["name"]] = t["name"]
            member_detail[m["name"]] = m
    # VLAN tNIC 만 (vlan_id 보유). default tNIC(=팀 자체, vlan_id None)는 제외.
    vlan_by_name = {}
    for tn in (team_nics or []):
        if tn.get("vlan_id") is not None:
            vlan_by_name[tn["name"]] = tn

    out, present = [], set()
    for iface in base:
        new = dict(iface)
        name = new.get("name")
        present.add(name)
        if name in team_by_name:
            t = team_by_name[name]
            new["team_role"] = "master"
            new["team_type"] = t.get("team_type")
            new["teaming_mode"] = t.get("teaming_mode")
            new["team_members"] = [m["name"] for m in t.get("members", [])]
        if name in vlan_by_name:
            tn = vlan_by_name[name]
            new["vlan_id"] = tn.get("vlan_id")
            new["vlan_parent"] = tn.get("team")
        out.append(new)

    for name, owner in member_owner.items():
        m = member_detail[name]
        if name in present:
            for new in out:
                if new.get("name") == name:
                    new["team_role"] = "member"
                    new["team_master"] = owner
            continue
        out.append({
            "id": name, "name": name, "kind": "os_nic",
            "mac": m.get("mac"), "mtu": None, "speed_mbps": m.get("speed_mbps"),
            "link_status": _norm_link(None, m.get("status")),
            "is_primary": False, "addresses": [],
            "team_role": "member", "team_master": owner,
        })
        present.add(name)
    return out


def _ipv4_net_key(address, prefix_length):
    """IPv4 address + prefix → (network_int, prefix) 키. 비정상 입력은 None.

    같은 서브넷 판정용 (is_secondary 파생). prefix 0/범위밖/비-IPv4 는 None.
    """
    p = _to_int(prefix_length)
    if p is None or p < 1 or p > 32:
        return None
    try:
        octs = [int(o) for o in str(address).split(".")]
    except (ValueError, TypeError):
        return None
    if len(octs) != 4 or any(o < 0 or o > 255 for o in octs):
        return None
    ipint = (octs[0] << 24) | (octs[1] << 16) | (octs[2] << 8) | octs[3]
    mask = (0xFFFFFFFF << (32 - p)) & 0xFFFFFFFF
    return (ipint & mask, p)


def _addr_scope(family, address):
    """family/address → scope(global/link/host). Windows best-effort (커널 scope API 부재)."""
    fam = _norm_family(family)
    a = (address or "").lower()
    if fam == "ipv6":
        if a.startswith("fe80"):
            return "link"
        if a == "::1":
            return "host"
        return "global"
    if a.startswith("127."):
        return "host"
    if a.startswith("169.254."):
        return "link"
    return "global"


def enrich_windows_addresses(interfaces):
    """Windows addresses[] 에 Linux 와 동일한 5키를 Additive 부여 (channel:[os] parity 완성).

    - parent_interface / label = 인터페이스명 (Windows 는 'bond1:1' 같은 alias 라벨 부재)
    - is_alias = 항상 False (Windows 는 라벨 개념 없음 — 날조 금지)
    - scope = best-effort 파생 (커널 scope API 부재)
    - is_secondary = 같은 인터페이스+같은 family+같은 서브넷의 2번째+ IPv4 → True.
      Linux 커널 secondary 플래그(같은 서브넷 2번째+ IPv4)와 동일 의미를 controller-side 로
      모사 (best-effort). 첫 주소는 False. IPv6/다른 서브넷은 False (Linux 동작 일치).
    입력 mutation 없음 (새 dict/list 반환 — immutability).
    """
    out = []
    for iface in interfaces or []:
        new = dict(iface)
        name = new.get("name")
        seen_nets = {}  # (network_int, prefix) -> 등장 횟수 (IPv4 only)
        merged = []
        for a in (new.get("addresses") or []):
            ea = dict(a)
            fam = ea.get("family")
            if ea.get("scope") is None:
                ea["scope"] = _addr_scope(fam, ea.get("address"))
            ea["label"] = name
            ea["parent_interface"] = name
            ea["is_alias"] = False
            sec = False
            if _norm_family(fam) == "ipv4":
                key = _ipv4_net_key(ea.get("address"), ea.get("prefix_length"))
                if key is not None:
                    sec = seen_nets.get(key, 0) >= 1
                    seen_nets[key] = seen_nets.get(key, 0) + 1
            ea["is_secondary"] = sec
            merged.append(ea)
        new["addresses"] = merged
        out.append(new)
    return out


def build_windows_network(interfaces, lines):
    """단일 진입점: base interfaces + PS 라인 → {interfaces, teams, bonds, bridges}.

    bonds/bridges 는 Windows 에 없지만 3채널 키 일관성 위해 빈 [] 노출.
    팀 위 VLAN tNIC(LBFOTEAMNIC)은 interfaces[] 에 vlan_id/vlan_parent 로 enrich (Linux 일관).
    addresses[] 는 Linux 와 동일한 5키(scope/label/parent_interface/is_alias/is_secondary) 부여.
    """
    teams = parse_windows_teams(lines)
    team_nics = parse_windows_team_nics(lines)
    enriched = enrich_windows_interfaces(interfaces, teams, team_nics)
    enriched = enrich_windows_addresses(enriched)
    return {"interfaces": enriched, "teams": teams, "bonds": [], "bridges": []}


class FilterModule:
    """Ansible filter plugin entrypoint."""

    def filters(self):
        return {
            "parse_linux_net_topology": parse_linux_net_topology,
            "enrich_linux_interfaces": enrich_linux_interfaces,
            "build_linux_network": build_linux_network,
            "parse_linux_addresses": parse_linux_addresses,
            "merge_linux_addresses": merge_linux_addresses,
            "parse_windows_teams": parse_windows_teams,
            "parse_windows_team_nics": parse_windows_team_nics,
            "enrich_windows_interfaces": enrich_windows_interfaces,
            "enrich_windows_addresses": enrich_windows_addresses,
            "build_windows_network": build_windows_network,
        }
