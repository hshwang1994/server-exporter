#!/usr/bin/env python3
"""디스크·FC 포트 개수 정합 판별기 (2026-10-27, 사용자 3차 지시 — "실제 수집 가능한 장치가 조용히 누락되면 PASS 로 처리하지 않는다").

gather 코드와 **독립된 단순 규칙**으로 원본 Redfish(recording.json 또는 전수 미러 트리)에 노출된 장치 수를 세고,
수집 산출(모듈 golden/재생 결과 또는 최종 envelope)의 개수와 대조한다. `status: success` 는 보지 않는다.

노출 수 (원본):
- 디스크: `.../Drives/<id>` 본문(Storage/*/Drives, Chassis/*/Drives). SimpleStorage `Devices[]` 는 Drive 리소스가 하나도 없을 때만(같은 디스크의 단순화 보기).
    present         = CapacityBytes > 0 ∧ Status.State != Absent ∧ 이름에 'empty' 없음
    absent_empty_bay = 그 밖(State Absent · CapacityBytes 0/없음 · Empty Bay)
    같은 드라이브가 두 경로(Storage 와 Chassis)로 보이면 SerialNumber 로 1개로 센다(present_raw 는 중복 포함 수).
- FC 포트: `.../NetworkAdapters/<a>/(Ports|NetworkPorts)/<p>` 본문에 FC 신호가 있으면 FC(같은 adapter·같은 Id 가 두 컬렉션에 있으면 1개) —
    LinkNetworkTechnology/ActiveLinkTechnology == FibreChannel · PortProtocol ∈ {FC, FCP, FCoE} · `FibreChannel` 블록(dict) ·
    8옥텟 주소(WWPN) · 또는 그 포트를 가리키는 NDF 의 NetDevFuncType/NetDevFuncCapabilities 가 FibreChannel.
    **NDF 컬렉션이 비어 있어도 Port 신호만으로 센다**(Lenovo XCC3 사례). 포트 링크가 없는 FC NDF 는 고아(orphan)로 따로 센다.
- 참고: 호스트 `Systems/*/EthernetInterfaces/*` 중 8옥텟 MAC(XCC3 가 FC 포트를 Ethernet 으로 노출) 수, System PowerState,
  Storage 컬렉션 멤버 수.

수집 수 (산출):
- 모듈 산출(expected_output.json / tier2 *.module.json): data.storage.controllers[].drives (+ 중복 포함), data.network_adapters.fc_hbas
- 최종 envelope(gather_output.json 의 마지막 줄): data.storage.physical_disks, data.storage.hbas

판정: collected == present → PASS. collected == present_raw(> present) → PASS(DEDUP_SAME_DRIVE). present == 0 ∧ collected == 0 → PASS
      (PowerState Off ∧ Storage 멤버 0 이면 POWER_OFF_NOT_EXPOSED 를 참고로 적는다). 그 밖은 UNEXPLAINED (누락 또는 조작) → 종료 코드 1.

사용:
  python tests/scripts/inventory_parity.py --recording tests/fixtures/redfish/real_hpe_dl380/recording.json \
      --module-json tests/fixtures/redfish/real_hpe_dl380/expected_output.json
  python tests/scripts/inventory_parity.py --mirror <mirror dir> --envelope-json <tier1>/gather_output.json [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_DRIVE_RE = re.compile(r"(?:^|/)Drives/[^/]+$")
_PORT_RE = re.compile(r"NetworkAdapters/[^/]+/(?:Ports|NetworkPorts)/[^/]+$")
_NDF_RE = re.compile(r"NetworkAdapters/[^/]+/NetworkDeviceFunctions/[^/]+$")
_HOST_NIC_RE = re.compile(r"^Systems/[^/]+/EthernetInterfaces/[^/]+$")
_SYSTEM_RE = re.compile(r"^Systems/[^/]+$")
_STORAGE_COLL_RE = re.compile(r"^Systems/[^/]+/Storage$")
_SIMPLE_RE = re.compile(r"^Systems/[^/]+/SimpleStorage/[^/]+$")
_WWN8 = re.compile(r"^(?:[0-9A-Fa-f]{2}[:\-]){7}[0-9A-Fa-f]{2}$|^[0-9A-Fa-f]{16}$")


def _norm_path(p: str) -> str:
    p = str(p or "")
    p = re.sub(r"^https?://[^/]+", "", p)
    p = re.sub(r"^/?redfish/v1/?", "", p)
    return p.strip("/")


def load_bodies_from_recording(path: Path) -> dict:
    rec = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for k, v in rec.items():
        if not k.startswith("get::") or not isinstance(v, list) or len(v) < 2:
            continue
        st, body = v[0], v[1]
        if isinstance(st, int) and 200 <= st < 300 and isinstance(body, dict):
            out[_norm_path(k[5:])] = body
    return out


def load_bodies_from_mirror(mirror_dir: Path) -> dict:
    sys.path.insert(0, str(REPO / "tests" / "redfish-probe"))
    import replay_full_mirror as rfm  # noqa: E402
    rmap, root, _stats = rfm.build_response_map(mirror_dir)
    out = {}
    for k, (st, body, _err) in rmap.items():
        if isinstance(st, int) and 200 <= st < 300 and isinstance(body, dict):
            out[_norm_path(k)] = body
    if isinstance(root, dict):
        out[""] = root
    return out


def _state(body):
    st = body.get("Status")
    return (st.get("State") if isinstance(st, dict) else None) or None


def _is_wwn8(s):
    return isinstance(s, str) and bool(_WWN8.match(s.strip()))


def _port_is_fc(body: dict) -> bool:
    for key in ("LinkNetworkTechnology", "ActiveLinkTechnology"):
        if str(body.get(key) or "").lower() == "fibrechannel":
            return True
    if str(body.get("PortProtocol") or "").upper() in {"FC", "FCP", "FCOE"}:
        return True
    if isinstance(body.get("FibreChannel"), dict):
        return True
    addrs = []
    addrs += list(body.get("AssociatedNetworkAddresses") or [])
    fc = body.get("FibreChannel") if isinstance(body.get("FibreChannel"), dict) else {}
    addrs += list(fc.get("AssociatedWorldWideNames") or [])
    eth = body.get("Ethernet") if isinstance(body.get("Ethernet"), dict) else {}
    addrs += list(eth.get("AssociatedMACAddresses") or [])
    return any(_is_wwn8(a) for a in addrs)


def _ndf_is_fc(body: dict) -> bool:
    if str(body.get("NetDevFuncType") or "").lower() == "fibrechannel":
        return True
    caps = body.get("NetDevFuncCapabilities") or []
    if any(str(c).lower() == "fibrechannel" for c in caps):
        return True
    fc = body.get("FibreChannel")
    if isinstance(fc, dict) and (fc.get("WWPN") or fc.get("PermanentWWPN")):
        return True
    return False


def _ndf_port_links(body: dict):
    links = body.get("Links") if isinstance(body.get("Links"), dict) else {}
    out = []
    ppa = links.get("PhysicalPortAssignment")
    if isinstance(ppa, dict) and ppa.get("@odata.id"):
        out.append(_norm_path(ppa["@odata.id"]))
    for x in links.get("AssignablePhysicalPorts") or []:
        if isinstance(x, dict) and x.get("@odata.id"):
            out.append(_norm_path(x["@odata.id"]))
    pn = links.get("PhysicalNetworkPortAssignment")
    if isinstance(pn, dict) and pn.get("@odata.id"):
        out.append(_norm_path(pn["@odata.id"]))
    return out


def exposure(bodies: dict) -> dict:
    """원본 노출 수."""
    drives_present, drives_absent = [], []
    serial_seen = {}
    for path, body in bodies.items():
        if not _DRIVE_RE.search(path):
            continue
        cap = body.get("CapacityBytes")
        try:
            cap = int(cap) if cap is not None else 0
        except (TypeError, ValueError):
            cap = 0
        name = str(body.get("Name") or "")
        state = _state(body)
        present = cap > 0 and str(state or "").lower() != "absent" and "empty" not in name.lower()
        rec = {"path": path, "serial": (body.get("SerialNumber") or "").strip() or None, "capacity_bytes": cap,
               "state": state, "name": name}
        (drives_present if present else drives_absent).append(rec)
    # SimpleStorage Devices — Storage/*/Drives 가 하나도 없을 때만 센다. SimpleStorage 는 같은 물리 디스크의 단순화된
    # 보기(DMTF SimpleStorage: "simple storage subsystem" 의 Devices[])라 Drive 리소스와 함께 있으면 같은 디스크의 두 번째
    # 노출이다 (2026-10-27 r1_DELL_R740_01: RAID.Slot.6-1 의 Devices[0..3] = Drives/Disk.Bay.0..3, SerialNumber 없음).
    simple_storage_used = False
    for path, body in bodies.items():
        if not _SIMPLE_RE.match(path):
            continue
        if drives_present or drives_absent:
            continue
        simple_storage_used = True
        for i, dev in enumerate(body.get("Devices") or []):
            if not isinstance(dev, dict):
                continue
            cap = dev.get("CapacityBytes")
            try:
                cap = int(cap) if cap is not None else 0
            except (TypeError, ValueError):
                cap = 0
            state = (dev.get("Status") or {}).get("State") if isinstance(dev.get("Status"), dict) else None
            present = cap > 0 and str(state or "").lower() != "absent"
            rec = {"path": f"{path}#Devices[{i}]", "serial": None, "capacity_bytes": cap, "state": state,
                   "name": str(dev.get("Name") or "")}
            (drives_present if present else drives_absent).append(rec)
    # 같은 드라이브 두 경로 → serial 로 1개
    dedup = {}
    for d in drives_present:
        key = ("serial", d["serial"]) if d["serial"] else ("path", d["path"])
        dedup.setdefault(key, d)
    # FC ports — 같은 adapter 의 같은 포트 Id 가 Ports/ 와 NetworkPorts/(구 스키마) 두 컬렉션에 모두 있으면 1개다
    # (2026-10-27 r1_DELL_R740_01: FC.Slot.1-1 이 NetworkPorts(ActiveLinkTechnology) 와 Ports(LinkNetworkTechnology) 양쪽에).
    # 대표 경로는 Ports/ 를 우선하고, FC 판정은 두 본문 중 하나라도 FC 신호가 있으면 FC 다.
    fc_ports, eth_ports = set(), set()
    port_bodies = {p: b for p, b in bodies.items() if _PORT_RE.search(p)}
    canon_of = {}
    groups = {}
    for p in sorted(port_bodies, key=lambda x: (x.rsplit("/", 2)[0], x.rsplit("/", 1)[1], 0 if "/Ports/" in x else 1)):
        key = (p.rsplit("/", 2)[0], p.rsplit("/", 1)[1])
        groups.setdefault(key, []).append(p)
    for key, paths in groups.items():
        canon = paths[0]
        for p in paths:
            canon_of[p] = canon
        (fc_ports if any(_port_is_fc(port_bodies[p]) for p in paths) else eth_ports).add(canon)
    orphan_fc_ndf = []
    pending_ndf = []
    for p, b in bodies.items():
        if not _NDF_RE.search(p) or not _ndf_is_fc(b):
            continue
        links = [canon_of[l] for l in _ndf_port_links(b) if l in canon_of]
        if links:
            for l in links:
                fc_ports.add(l)
                eth_ports.discard(l)
        else:
            pending_ndf.append(p)
    # 포트 링크가 없는 FC NDF: 같은 adapter 에 FC 포트가 하나도 없을 때만 고아(orphan)로 센다 — CSUS RMC 는 NDF 에 Links 가
    # 없지만 같은 adapter 의 같은 Id 포트(PCIeCard10Port1)가 FC 포트로 있다(1 NDF : 1 Port). 같은 adapter 에 FC 포트가 있으면
    # 그 NDF 는 그 포트의 기능 설명이지 별도 장치가 아니다.
    fc_adapters = {p.rsplit("/", 2)[0] for p in fc_ports}
    for p in pending_ndf:
        adapter = p.rsplit("/", 2)[0]
        if adapter not in fc_adapters:
            orphan_fc_ndf.append(p)
    host_fc_in_eth = sorted(p for p, b in bodies.items() if _HOST_NIC_RE.match(p) and _is_wwn8(b.get("MACAddress")))
    power = {p: b.get("PowerState") for p, b in bodies.items() if _SYSTEM_RE.match(p)}
    storage_members = {p: len(b.get("Members") or []) for p, b in bodies.items() if _STORAGE_COLL_RE.match(p)}
    return {
        "disks_present": len(dedup), "disks_present_raw": len(drives_present), "disks_absent_empty_bay": len(drives_absent),
        "disk_paths_present": sorted(d["path"] for d in drives_present), "simple_storage_used": simple_storage_used,
        "fc_ports": len(fc_ports), "fc_port_paths": sorted(fc_ports), "ethernet_ports": len(eth_ports),
        "orphan_fc_ndf": sorted(orphan_fc_ndf), "host_fc_in_ethernet": host_fc_in_eth,
        "power_state": power, "storage_collection_members": storage_members,
    }


def collected_from_module(doc: dict) -> dict:
    data = doc.get("data") if isinstance(doc.get("data"), dict) else doc
    st = data.get("storage") if isinstance(data.get("storage"), dict) else {}
    drives = [d for c in (st.get("controllers") or []) if isinstance(c, dict) for d in (c.get("drives") or [])]
    serials = {(d.get("serial") or "").strip() or d.get("id") for d in drives if isinstance(d, dict)}
    na = data.get("network_adapters") if isinstance(data.get("network_adapters"), dict) else {}
    return {"disks": len(drives), "disks_unique": len(serials), "fc_hbas": len(na.get("fc_hbas") or []),
            "fc_ports": sum(1 for p in (na.get("ports") or []) if str(p.get("port_type") or "").lower() == "fibrechannel"),
            "layer": "module"}


def collected_from_envelope(env: dict) -> dict:
    data = env.get("data") if isinstance(env.get("data"), dict) else {}
    st = data.get("storage") if isinstance(data.get("storage"), dict) else {}
    net = data.get("network") if isinstance(data.get("network"), dict) else {}
    disks = st.get("physical_disks") or []
    return {"disks": len(disks), "disks_unique": len(disks), "fc_hbas": len(st.get("hbas") or []),
            "fc_ports": sum(1 for p in (net.get("ports") or []) if str(p.get("port_type") or "").lower() == "fibrechannel"),
            "layer": "envelope"}


def classify(exp: dict, col: dict) -> dict:
    notes, unexplained = [], []
    present, raw = exp["disks_present"], exp["disks_present_raw"]
    cd = col["disks"]
    if cd == present:
        notes.append("DISKS_MATCH")
    elif cd == raw and raw > present:
        notes.append("DEDUP_SAME_DRIVE")
    elif cd == col.get("disks_unique") == present:
        notes.append("DISKS_MATCH_UNIQUE")
    else:
        unexplained.append(f"disks: exposed present {present} (raw {raw}) vs collected {cd}")
    if present == 0 and cd == 0:
        off = any(str(v).lower() == "off" for v in exp["power_state"].values())
        if off and all(n == 0 for n in exp["storage_collection_members"].values()):
            notes.append("POWER_OFF_NOT_EXPOSED")
        else:
            notes.append("NO_DISK_EXPOSED")
    fc = exp["fc_ports"] + len(exp["orphan_fc_ndf"])
    if col["fc_hbas"] == fc:
        notes.append("FC_MATCH")
    else:
        unexplained.append(f"fc: exposed ports {exp['fc_ports']} (+orphan ndf {len(exp['orphan_fc_ndf'])}) vs collected hbas {col['fc_hbas']}")
    if fc == 0 and col["fc_hbas"] == 0:
        notes.append("NO_FC_EXPOSED")
    if exp["host_fc_in_ethernet"]:
        notes.append(f"FC_IN_HOST_ETHERNET:{len(exp['host_fc_in_ethernet'])}")
    return {"pass": not unexplained, "notes": notes, "unexplained": unexplained}


def _last_envelope(path: Path):
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return json.loads(lines[-1]) if lines else {}


def run(recording=None, mirror=None, module_json=None, envelope_json=None, module_doc=None):
    bodies = load_bodies_from_recording(Path(recording)) if recording else load_bodies_from_mirror(Path(mirror))
    exp = exposure(bodies)
    if module_doc is not None:
        col = collected_from_module(module_doc)
    elif module_json:
        col = collected_from_module(json.loads(Path(module_json).read_text(encoding="utf-8")))
    elif envelope_json:
        col = collected_from_envelope(_last_envelope(Path(envelope_json)))
    else:
        col = None
    res = {"exposure": exp, "collected": col}
    if col is not None:
        res["verdict"] = classify(exp, col)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--recording")
    src.add_argument("--mirror")
    out = ap.add_mutually_exclusive_group()
    out.add_argument("--module-json")
    out.add_argument("--envelope-json")
    ap.add_argument("--json", default=None, help="결과 JSON 저장 경로")
    ap.add_argument("--label", default=None)
    a = ap.parse_args()
    res = run(recording=a.recording, mirror=a.mirror, module_json=a.module_json, envelope_json=a.envelope_json)
    res["label"] = a.label or Path(a.recording or a.mirror).name
    e, c, v = res["exposure"], res.get("collected"), res.get("verdict")
    line = (f"{res['label']}: disks present {e['disks_present']} (raw {e['disks_present_raw']}, absent/empty {e['disks_absent_empty_bay']}) "
            f"fc_ports {e['fc_ports']} (orphan ndf {len(e['orphan_fc_ndf'])}, fc-in-eth {len(e['host_fc_in_ethernet'])})")
    if c:
        line += f" | collected disks {c['disks']} hbas {c['fc_hbas']} [{c['layer']}]"
    if v:
        line += f" | {'PASS' if v['pass'] else 'FAIL'} {','.join(v['notes'])}"
        for u in v["unexplained"]:
            line += f"\n  UNEXPLAINED: {u}"
    print(line)
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if (v is None or v["pass"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
