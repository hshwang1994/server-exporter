# -*- coding: utf-8 -*-
"""A/B/C 독립 Summary 비교기 (2026-10-29, stdlib 만).

A = 미러 원천 JSON 에서 문서 규칙(docs/contract/03-fields.md 2026-10-29 노트)으로 직접 계산한 값
B = 봉투 상세(data.<section> 의 목록 · top-level 값)    C = 봉투 Summary(data.<section>.summary · multi_node.summary)
수집 코드(redfish_gather.py · normalize_standard.yml) · 재생 도구(replay_full_mirror · mirror_policy — RG 를 import 한다) ·
감사자 도구를 import 하지 않는다. 미러는 이 파일의 읽기 함수로만 연다.

판정: PASS(규칙대로 일치) · CM(문서화된 차이 — 규칙 id 를 적는다) · FAIL(설명 없는 불일치) ·
      MOCK_LIMITATION(A 를 계산할 원천이 미러에 없음 — 정확성의 근거로 세지 않는다).
같은 입력이면 출력 바이트가 같다(정렬 · 시각 없음).

사용: python -I -X utf8 -B summary_abc.py <envelope root> <out.json> <out.md> label=<mirror dir> ...
"""
import json
import sys
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path

GIB = 1 << 30


def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _norm(uri):
    u = (uri or "").split("?")[0].split("#")[0]
    return u.rstrip("/") or "/"


class Mirror:
    """URI -> 본문. _fsmap.json 이 있으면 그 표, 없으면 디렉터리 경로와 본문 @odata.id 로 색인."""

    def __init__(self, root):
        self.root = Path(root)
        self.idx, self.recorded = {}, {}
        fs = _load(self.root / "_fsmap.json")
        if isinstance(fs, dict) and isinstance(fs.get("paths"), dict):
            for path, ent in fs["paths"].items():
                if isinstance(ent, dict) and ent.get("type", "json") == "json":
                    self.idx[_norm(path)] = self.root / ent["dir"]
        else:
            for f in sorted(self.root.rglob("index.json")):
                d = f.parent
                self.idx.setdefault(_norm("/" + d.relative_to(self.root).as_posix()), d)
                b = _load(f)
                if isinstance(b, dict) and isinstance(b.get("@odata.id"), str):
                    self.idx.setdefault(_norm(b["@odata.id"]), d)
        man = _load(self.root / "_manifest.json") or {}
        for k in ("absent", "failed"):
            for e in man.get(k) or []:
                if isinstance(e, dict) and e.get("path"):
                    self.recorded[_norm(e["path"])] = e.get("status")

    def get(self, uri):
        """-> ('ok', body) | ('recorded', status) | ('missing', None)."""
        u = _norm(uri)
        d = self.idx.get(u)
        if d is not None:
            h = _load(d / "headers.json") or {}
            st = h.get("_status") if isinstance(h, dict) else None
            if isinstance(st, int) and not 200 <= st < 300:
                return "recorded", st
            b = _load(d / "index.json")
            if isinstance(b, dict):
                return "ok", b
        if u in self.recorded:
            return "recorded", self.recorded[u]
        return "missing", None

    def members(self, uri):
        """컬렉션 멤버 본문. -> (state, [(uri, state, body)]) ; state ok|recorded|missing."""
        st, coll = self.get(uri)
        if st != "ok":
            return st, []
        out = []
        for m in coll.get("Members") or []:
            mu = m.get("@odata.id") if isinstance(m, dict) else None
            if not mu:
                out.append((None, "missing", None))
                continue
            s, b = self.get(mu)
            out.append((mu, s, b))
        return "ok", out


def _link(body, key):
    v = (body or {}).get(key)
    return v.get("@odata.id") if isinstance(v, dict) else None


def _state(b):
    return ((b or {}).get("Status") or {}).get("State")


def _health(b):
    return ((b or {}).get("Status") or {}).get("Health")


def _int_pos(v):
    try:
        i = int(v)
    except (TypeError, ValueError):
        return None
    return i if i > 0 else None


def _round_half_even(v):
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not d.is_finite():
        return None
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def _hexmac(m):
    return "".join(ch for ch in str(m or "").upper() if ch in "0123456789ABCDEF")


# ── A 계산 (원천) ──────────────────────────────────────────────────────────────
def a_system(mr):
    st, sr = mr.get("/redfish/v1")
    st, mems = mr.members(_link(sr, "Systems"))
    sys_uri, s_state, sysb = mems[0] if mems else (None, "missing", None)
    return sr or {}, sys_uri, sysb if s_state == "ok" else None


def a_cpu(mr, sys_uri, sysb):
    st, mems = mr.members(sys_uri + "/Processors")
    if st != "ok":
        return {"_lim": "Processors " + st}
    cpus = [b for _u, s, b in mems if s == "ok" and (b.get("ProcessorType") in (None, "CPU")) and _state(b) != "Absent"]
    unread = sum(1 for _u, s, _b in mems if s != "ok")
    cores = [_int_pos(b.get("TotalCores")) for b in cpus]
    ps = (sysb or {}).get("ProcessorSummary") or {}
    cnt, cc = _int_pos(ps.get("Count")), _int_pos(ps.get("CoreCount"))
    known, unknown = sum(c for c in cores if c), sum(1 for c in cores if not c) + unread
    if not unread and cpus and None not in cores:
        total = sum(cores)
    elif cc and (cnt is None or cnt >= len(cpus) + unread) and cc >= known + unknown:
        total = cc
    else:
        total = None
    sockets = len(cpus) if not unread else (cnt if cnt and cnt >= len(cpus) + unread else None)
    mfr = {}
    for b in cpus:
        mfr.setdefault(b.get("Model"), b.get("Manufacturer"))
    return {"sockets": sockets, "cores_physical": total, "mfr_by_model": mfr}


def canon_mfr(raw):
    """FIX 2 표(문서 6.1): intel → Intel · amd|advanced micro devices → AMD · 그 밖 원문 · 없으면 null."""
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).strip()
    lo = s.lower()
    return "Intel" if "intel" in lo else ("AMD" if ("amd" in lo or "advanced micro devices" in lo) else s)


def a_memory(mr, sys_uri, sysb):
    st, mems = mr.members(sys_uri + "/Memory")
    if st != "ok":
        return {"_lim": "Memory " + st}
    inst, unread = [], 0
    for _u, s, b in mems:
        if s != "ok":
            unread += 1
            continue
        if _state(b) == "Absent":
            continue
        if (b.get("Status") is None and not b.get("CapacityMiB")
                and not (b.get("Manufacturer") or b.get("PartNumber") or b.get("SerialNumber"))):
            continue  # C2 빈 슬롯(문서 6.2)
        inst.append(b)
    caps = [_int_pos(b.get("CapacityMiB")) for b in inst]
    known = sum(c for c in caps if c)
    g = _int_pos(((sysb or {}).get("MemorySummary") or {}).get("TotalSystemMemoryGiB"))
    complete = not unread and None not in caps
    g_ok = g and ((g * 1024 > known) if (None in caps) else (g * 1024 >= known))
    total_mb = known if complete else (g * 1024 if g_ok else None)
    grand = (sum(_round_half_even(c / 1024) for c in caps) if complete else (g if g_ok else None))
    if complete and not inst:
        total_mb, grand = (g * 1024, g) if g else (None, None)
    return {"total_mb": total_mb, "grand_total_gb": grand, "dimms": len(inst)}


def a_storage(mr, sys_uri, sysb):
    """SA-07 · SA-12: Storage 가 가리키는 드라이브 ∪ 섀시가 광고한 Drives 컬렉션 · Links.Drives. URI → Serial 순 중복 제거, Absent 제외."""
    sources, incomplete, lim = 0, False, []
    seen, drives = set(), []
    chassis = [c.get("@odata.id") for c in ((sysb or {}).get("Links") or {}).get("Chassis") or [] if isinstance(c, dict)]
    st, smems = mr.members(sys_uri + "/Storage") if _link(sysb, "Storage") else ("missing", [])
    if st == "ok":
        for _u, s, sb in smems:
            if s != "ok":
                incomplete = True
                continue
            if isinstance(sb.get("Drives"), list):
                sources += 1
                for d in sb["Drives"]:
                    du = d.get("@odata.id") if isinstance(d, dict) else None
                    if du and _norm(du) not in seen:
                        seen.add(_norm(du))
                        drives.append(du)
            for e in ((sb.get("Links") or {}).get("Enclosures") or []):
                if isinstance(e, dict) and e.get("@odata.id") not in chassis:
                    chassis.append(e.get("@odata.id"))
    elif st == "missing" and _link(sysb, "Storage"):
        lim.append("Storage collection not in mirror")
    storage_uris = set(seen)
    for cu in chassis:
        cs, cb = mr.get(cu)
        if cs != "ok":
            continue
        cand = []
        dl = _link(cb, "Drives")
        if dl:
            ds, dmems = mr.members(dl)
            if ds == "ok":
                sources += 1
                cand += [u for u, _s, _b in dmems if u]
            elif ds == "missing":
                lim.append("%s not in mirror" % dl)
        ld = (cb.get("Links") or {}).get("Drives")
        if isinstance(ld, list):
            sources += 1
            cand += [d.get("@odata.id") for d in ld if isinstance(d, dict) and d.get("@odata.id")]
        for du in cand:
            if _norm(du) not in seen:
                seen.add(_norm(du))
                drives.append(du)
    disks, serials, caps = [], set(), []
    for du in drives:
        s, b = mr.get(du)
        if s != "ok":
            incomplete = True
            continue
        if _state(b) == "Absent":
            continue
        sn = (b.get("SerialNumber") or "").strip()
        if _norm(du) not in storage_uris and sn and sn in serials:
            continue
        if sn:
            serials.add(sn)
        disks.append(du)
        cb_ = b.get("CapacityBytes")
        caps.append(int(cb_) // GIB if isinstance(cb_, (int, float)) and cb_ > 0 else None)
    if lim:
        return {"_lim": "; ".join(lim), "count": len(disks)}
    if incomplete or None in caps:
        grand = None
    elif disks:
        grand = sum(caps)
    else:
        grand = 0 if sources else None
    return {"count": len(disks), "grand_total_gb": grand}


def a_power(mr, sys_uri, sysb, sr):
    chassis = [c.get("@odata.id") for c in ((sysb or {}).get("Links") or {}).get("Chassis") or [] if isinstance(c, dict)]
    for cu in chassis:
        cs, cb = mr.get(cu)
        if cs == "ok" and (_link(cb, "Power") or _link(cb, "PowerSubsystem")):
            break
    else:
        return {"_lim": "no chassis with Power/PowerSubsystem"}
    psus, consumed, src = [], None, None
    if _link(cb, "Power"):
        ps, pb = mr.get(_link(cb, "Power"))
        if ps != "ok":
            return {"_lim": "Power " + ps}
        psus = [p for p in pb.get("PowerSupplies") or [] if isinstance(p, dict)]
        pc = (pb.get("PowerControl") or [{}])[0]
        consumed, src = _round_half_even(pc.get("PowerConsumedWatts")), "PowerControl"
        caps_f = [_int_pos(p.get("PowerCapacityWatts")) or _int_pos(((p.get("InputRanges") or [{}])[0]).get("OutputWattage")) for p in psus]
    else:
        ss, sb = mr.get(_link(cb, "PowerSubsystem"))
        ms, mems = mr.members(_link(sb, "PowerSupplies")) if ss == "ok" else (ss, [])
        if ms != "ok":
            return {"_lim": "PowerSupplies " + ms}
        psus = [b for _u, s, b in mems if s == "ok"]
        caps_f = [_int_pos(p.get("PowerCapacityWatts")) for p in psus]
        es, eb = mr.get(_link(cb, "EnvironmentMetrics")) if _link(cb, "EnvironmentMetrics") else ("missing", None)
        if es == "ok" and isinstance(eb.get("PowerWatts"), dict):
            consumed, src = _round_half_even(eb["PowerWatts"].get("Reading")), "EnvironmentMetrics"
        if consumed is None:
            rid = "Chassis%s_TotalPowerConsumedWatts" % (cb.get("Id") or "")
            ts, tb = mr.get("/redfish/v1/TelemetryService/MetricReports/" + rid)
            if ts == "ok" and tb.get("MetricValues"):
                consumed, src = _round_half_even(tb["MetricValues"][0].get("MetricValue")), "Telemetry"
    inst = [(p, c) for p, c in zip(psus, caps_f) if _state(p) != "Absent"]
    hs = [_health(p) for p, _c in inst]
    if not inst:
        roll = None
    elif "Critical" in hs:
        roll = "Critical"
    elif "Warning" in hs:
        roll = "Warning"
    elif "OK" in hs:
        roll = "OK"
    else:
        roll = "Unknown"
    known = [c for _p, c in inst if c]
    return {"chassis": cu, "psu_count": len(inst), "total_capacity_w": sum(known) if known else None,
            "health_rollup": roll, "consumed_watts": consumed, "consumed_source": src}


def a_multi_node(mr, sr):
    out = {}
    for key, link in (("partition_count", "Systems"), ("manager_count", "Managers"), ("chassis_count", "Chassis")):
        st, mems = mr.members(_link(sr, link))
        out[key] = len(mems) if st == "ok" and all(s == "ok" for _u, s, _b in mems) else None
    cl = _link(sr, "CompositionService")
    if cl:
        cs, cb = mr.get(cl)
        st, mems = mr.members(_link(cb, "ResourceBlocks")) if cs == "ok" and _link(cb, "ResourceBlocks") else ("missing", [])
        out["resource_block_count"] = len(mems) if st == "ok" else None
    else:
        out["resource_block_count"] = None
    fl = _link(sr, "Fabrics")
    fabrics = {}
    if fl:
        st, mems = mr.members(fl)
        out["fabric_count"] = len(mems) if st == "ok" and all(s == "ok" for _u, s, _b in mems) else None
        for _u, s, fb in mems:
            if s != "ok":
                continue
            ent = {}
            for k, link in (("switch_count", "Switches"), ("endpoint_count", "Endpoints")):
                lu = _link(fb, link)
                if not lu:
                    ent[k] = None
                    continue
                st2, m2 = mr.members(lu)
                ent[k] = len(m2) if st2 == "ok" else None
            fabrics[fb.get("Id")] = ent
    else:
        out["fabric_count"] = None
    out["fabrics"] = fabrics
    return out


LINK_UP = {"linkup", "up", "connected"}
LINK_DOWN = {"linkdown", "down", "nolink", "disconnected", "disabled", "inactive", "offline"}


def a_link(raw):
    """SA-09 일반 NIC · 포트 매핑(문서 6.4): Starting · Training · Enabled · Active · 미인식 → unknown."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    return "up" if s in LINK_UP else ("down" if s in LINK_DOWN else "unknown")


def a_nics(mr, sys_uri):
    st, mems = mr.members(sys_uri + "/EthernetInterfaces")
    if st != "ok":
        return {"_lim": "EthernetInterfaces " + st}
    out = {}
    for _u, s, b in mems:
        if s != "ok" or len(_hexmac(b.get("MACAddress") or b.get("PermanentMACAddress"))) == 16:
            continue  # 8옥텟 주소 = FC WWPN(문서 6.4 C4) — 서버 NIC 아님
        out[b.get("Id")] = {"raw_link": b.get("LinkStatus"), "speed": b.get("SpeedMbps")}
    return {"nics": out}


# ── 판정 ───────────────────────────────────────────────────────────────────────
def verdict(rows, label, field, a, b, rule, cm=None, lim=None):
    if lim:
        rows.append({"label": label, "field": field, "verdict": "MOCK_LIMITATION", "A": None, "B": b, "rule": rule, "note": lim})
    elif a == b:
        rows.append({"label": label, "field": field, "verdict": "PASS", "A": a, "B": b, "rule": rule})
    elif cm:
        rows.append({"label": label, "field": field, "verdict": "CM", "A": a, "B": b, "rule": rule, "note": cm})
    else:
        rows.append({"label": label, "field": field, "verdict": "FAIL", "A": a, "B": b, "rule": rule})


def compare_hw(label, mr, sys_uri, sysb, cpu, mem, sto, rows, scope=""):
    """cpu · memory · storage — top-level 과 파티션(SA-03: 같은 규칙, 그 파티션 System 범위) 공용."""
    ac = a_cpu(mr, sys_uri, sysb)
    for f in ("sockets", "cores_physical"):
        verdict(rows, label, scope + "cpu.%s A↔B" % f, ac.get(f), cpu.get(f), "R-CPU sockets/cores (6.1 SA-04)", lim=ac.get("_lim"))
    gs = (cpu.get("summary") or {}).get("groups") or []
    gt = [g.get("total_cores") for g in gs]
    for g in gs:
        verdict(rows, label, scope + "cpu group %s manufacturer A↔C" % g.get("model"),
                canon_mfr((ac.get("mfr_by_model") or {}).get(g.get("model"))), g.get("manufacturer"), "FIX 2 표 (6.1 · 파티션 SA-03)", lim=ac.get("_lim"))
    verdict(rows, label, scope + "cpu Σgroups.sockets B↔C", cpu.get("sockets"), sum(g.get("sockets") or 0 for g in gs), "R-CPU-3")
    verdict(rows, label, scope + "cpu Σgroups.total_cores B↔C", cpu.get("cores_physical"),
            None if (not gt or None in gt) else sum(gt), "R-CPU-3")
    # Memory
    am = a_memory(mr, sys_uri, sysb)
    ms = mem.get("summary") or {}
    verdict(rows, label, scope + "memory.total_mb A↔B", am.get("total_mb"), mem.get("total_mb"), "R-MEM-1 (6.2 SA-05)", lim=am.get("_lim"))
    verdict(rows, label, scope + "memory.installed_mb B↔B", mem.get("total_mb"), mem.get("installed_mb"), "total_basis physical_installed")
    verdict(rows, label, scope + "memory.grand_total_gb A↔C", am.get("grand_total_gb"), ms.get("grand_total_gb"), "R-MEM-2 half-even", lim=am.get("_lim"))
    gsum = sum(g.get("group_total_gb") or 0 for g in ms.get("groups") or [])
    verdict(rows, label, scope + "memory Σgroups B↔C", ms.get("grand_total_gb"), gsum if ms.get("groups") else None, "R-MEM-3",
            cm=("SA-05: MemorySummary 사용 시 grand ≠ Σgroups" if ms.get("grand_total_gb") is not None else None))
    # Storage
    ast = a_storage(mr, sys_uri, sysb)
    ss = sto.get("summary") or {}
    pdisks = sto.get("physical_disks") or []
    verdict(rows, label, scope + "storage disk count A↔B", ast.get("count"), len(pdisks), "R-STO-1 (6.3 SA-12)", lim=ast.get("_lim"))
    verdict(rows, label, scope + "storage.grand_total_gb A↔C", ast.get("grand_total_gb"), ss.get("grand_total_gb"), "R-STO-2 (6.3 SA-07, floor)", lim=ast.get("_lim"))
    caps = [(p.get("total_mb") // 1024) if isinstance(p.get("total_mb"), int) else None for p in pdisks]
    verdict(rows, label, scope + "storage Σdisks B↔C", ss.get("grand_total_gb"),
            (sum(caps) if pdisks and None not in caps else ss.get("grand_total_gb") if not pdisks else None), "R-STO-3 floor(total_mb/1024)")
    verdict(rows, label, scope + "storage Σgroups.quantity B↔C", len(pdisks), sum(g.get("quantity") or 0 for g in ss.get("groups") or []), "R-STO-3")


def compare(label, mdir, env, rows):
    mr = Mirror(mdir)
    sr, sys_uri, sysb = a_system(mr)
    d = env.get("data") or {}
    cpu, mem, sto, net, pwr = (d.get(k) or {} for k in ("cpu", "memory", "storage", "network", "power"))
    compare_hw(label, mr, sys_uri, sysb, cpu, mem, sto, rows)
    # Network
    an = a_nics(mr, sys_uri)
    ifs = net.get("interfaces") or []
    nsu = net.get("summary") or {}
    verdict(rows, label, "network interface count A↔B", len(an.get("nics") or {}), len(ifs), "R-NET-1 (6.4 C4)", lim=an.get("_lim"))
    verdict(rows, label, "network.port_count B↔C", len(ifs), nsu.get("port_count"), "R-NET-2")
    verdict(rows, label, "network Σgroups.quantity B↔C", len(ifs), sum(g.get("quantity") or 0 for g in nsu.get("groups") or []), "R-NET-3")
    verdict(rows, label, "network Σlink_up_count B↔C", sum(1 for i in ifs if i.get("link_status") == "up"),
            sum(g.get("link_up_count") or 0 for g in nsu.get("groups") or []), "R-NET-3")
    pri = [i for i in ifs if i.get("is_primary") is True]
    verdict(rows, label, "network.primary_speed_mbps B↔C", (pri[0].get("speed_mbps") or None) if pri else None,
            nsu.get("primary_speed_mbps"), "R-NET-4 (SA-10)")
    verdict(rows, label, "network group speed 0 없음 C", 0, sum(1 for g in nsu.get("groups") or [] if g.get("speed_mbps") == 0), "R-NET-5 (SA-08)")
    for nid, nv in sorted((an.get("nics") or {}).items()):
        bi = [i for i in ifs if i.get("id") == nid]
        if not bi:
            continue
        al, bl = a_link(nv["raw_link"]), bi[0].get("link_status")
        if al is None:
            verdict(rows, label, "NIC %s link A↔B" % nid, "unknown", bl, "R-NET-6 (SA-09)",
                    cm=("F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충" if bl in ("up", "down") else None))
        else:
            verdict(rows, label, "NIC %s link A↔B" % nid, al, bl, "R-NET-6 (SA-09)")
    # Power
    ap = a_power(mr, sys_uri, sysb, sr)
    ps = pwr.get("summary") or {}
    for f in ("psu_count", "total_capacity_w", "health_rollup", "consumed_watts"):
        verdict(rows, label, "power.summary.%s A↔C" % f, ap.get(f), ps.get(f), "R-PWR (6.5 SA-06 · SA-17)", lim=ap.get("_lim"))
    verdict(rows, label, "power consumed B↔C", (pwr.get("power_control") or {}).get("power_consumed_watts"), ps.get("consumed_watts"), "R-PWR-5")
    # multi_node
    mn = d.get("multi_node")
    if mn:
        amn = a_multi_node(mr, sr)
        msum = mn.get("summary") or {}
        for f in ("partition_count", "manager_count", "chassis_count", "resource_block_count", "fabric_count"):
            verdict(rows, label, "multi_node.summary.%s A↔C" % f, amn.get(f), msum.get(f), "R-MN (9 SA-01 · SA-02)")
        for p in mn.get("partitions") or []:
            su = p.get("system_uri")
            st_, pb = mr.get(su) if su else ("missing", None)
            if st_ != "ok":
                rows.append({"label": label, "field": "partition %s" % p.get("id"), "verdict": "MOCK_LIMITATION", "A": None, "B": None,
                             "rule": "SA-03", "note": "partition System %s" % st_})
                continue
            compare_hw(label, mr, su, pb, p.get("cpu") or {}, p.get("memory") or {}, p.get("storage") or {}, rows,
                       scope="partition %s " % p.get("id"))
            verdict(rows, label, "partition %s network.summary 미계산" % p.get("id"), {"groups": []},
                    (p.get("network") or {}).get("summary"), "SA-03: 파티션 network summary 는 계산하지 않음(문서 9)")
        for fb in mn.get("fabrics") or []:
            for f in ("switch_count", "endpoint_count"):
                verdict(rows, label, "fabric %s.%s A↔B" % (fb.get("id"), f), (amn["fabrics"].get(fb.get("id")) or {}).get(f), fb.get(f), "R-MN (SA-01)")


def main():
    env_root, out_json, out_md = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    rows = []
    for arg in sorted(sys.argv[4:]):
        label, mdir = arg.split("=", 1)
        env = _load(env_root / label / "gather_output.json")
        env = env[0] if isinstance(env, list) else env
        compare(label, mdir, env, rows)
    tally = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    out_json.write_text(json.dumps({"tally": tally, "rows": rows}, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    md = ["# A/B/C 독립 Summary 비교", "", "| 판정 | 건수 |", "|---|---|"] + ["| %s | %d |" % (k, tally[k]) for k in sorted(tally)]
    md += ["", "## PASS 이외", "", "| label | field | 판정 | A | B/C | 규칙 · 비고 |", "|---|---|---|---|---|---|"]
    for r in rows:
        if r["verdict"] != "PASS":
            md.append("| %s | %s | %s | %s | %s | %s %s |" % (r["label"], r["field"], r["verdict"], json.dumps(r["A"], ensure_ascii=False),
                                                         json.dumps(r["B"], ensure_ascii=False), r["rule"], r.get("note", "")))
    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(tally, sort_keys=True))


if __name__ == "__main__":
    main()
