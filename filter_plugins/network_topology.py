#!/usr/bin/env python3

from __future__ import annotations

import json as _json


def _aslist(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _to_int(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        n = int(s)
    except (ValueError, TypeError):
        return None
    return n


def _clean(value):
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _norm_link(operstate, mii_status):
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
    if not isinstance(line, str):
        return None, []
    s = line.strip()
    if not s or "|" not in s:
        return None, []
    parts = s.split("|")
    return parts[0], parts


def parse_linux_net_topology(lines):
    if not lines:
        return {"bonds": [], "bridges": [], "teams": [], "vlans": []}

    bonds = {}
    bond_order = []
    bslave = {}
    slstate = {}
    slmeta = {}
    bridges = {}
    bridge_order = []
    teams = {}
    team_order = []
    vlans = {}
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
        b["addresses"] = []
        bonds_out.append(b)

    bridges_out = [{"name": n, "members": bridges[n]} for n in bridge_order]
    teams_out = [teams[n] for n in team_order]
    vlans_out = [vlans[n] for n in vlan_order]
    return {"bonds": bonds_out, "bridges": bridges_out, "teams": teams_out,
            "vlans": vlans_out}


def enrich_linux_interfaces(interfaces, topology):
    base = list(interfaces or [])
    bonds = (topology or {}).get("bonds") or []
    vlans = {v["name"]: v for v in ((topology or {}).get("vlans") or [])}
    bond_by_name = {b["name"]: b for b in bonds}
    slave_owner = {}
    slave_detail = {}
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



_ADDR_NEW_KEYS = ("scope", "label", "parent_interface", "is_alias", "is_secondary")
_IP_O_FLAGS = frozenset({
    "brd", "scope", "secondary", "primary", "dynamic", "mngtmpaddr",
    "noprefixroute", "tentative", "deprecated", "temporary", "home",
    "nodad", "optimistic", "stable-privacy", "valid_lft", "preferred_lft",
    "forever", "global", "link", "host", "site", "nowait",
})


def _prefix_to_mask(prefixlen):
    p = _to_int(prefixlen)
    if p is None or p < 0 or p > 32:
        return None
    bits = (0xFFFFFFFF << (32 - p)) & 0xFFFFFFFF if p > 0 else 0
    return ".".join(str((bits >> (8 * (3 - i))) & 0xFF) for i in range(4))


def _mask_to_prefix(mask):
    if not mask:
        return None
    try:
        return sum(bin(int(o)).count("1") for o in str(mask).split("."))
    except (ValueError, TypeError):
        return None


def _norm_family(fam):
    f = (fam or "").strip().lower()
    if f in ("inet", "ipv4"):
        return "ipv4"
    if f in ("inet6", "ipv6"):
        return "ipv6"
    return f or None


def _addr_record(ifname, family, address, prefixlen, scope, label, secondary):
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




def _wjson(line, tag):
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
    if isinstance(value, dict):
        return _clean(value.get("name") or value.get("Name"))
    return _clean(value)


def parse_windows_teams(lines):
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
    base = list(interfaces or [])
    teams = teams or []
    team_by_name = {t["name"]: t for t in teams}
    member_owner, member_detail = {}, {}
    for t in teams:
        for m in t.get("members", []):
            member_owner[m["name"]] = t["name"]
            member_detail[m["name"]] = m
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
    out = []
    for iface in interfaces or []:
        new = dict(iface)
        name = new.get("name")
        seen_nets = {}
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
    teams = parse_windows_teams(lines)
    team_nics = parse_windows_team_nics(lines)
    enriched = enrich_windows_interfaces(interfaces, teams, team_nics)
    enriched = enrich_windows_addresses(enriched)
    return {"interfaces": enriched, "teams": teams, "bonds": [], "bridges": []}


class FilterModule:

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
