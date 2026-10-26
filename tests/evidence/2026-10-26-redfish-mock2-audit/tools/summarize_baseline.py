"""Tier 0/1/2 baseline 요약 — 기계 판독 JSON + Markdown 표. Tier 1 access log 에서 요청 집합도 뽑는다."""
from __future__ import annotations
import json
import os
import sys
from collections import Counter
from pathlib import Path

SP = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
LABELS_2 = ["csus3200_01", "csus3200_02", "csus3200_03", "dl380_gen12_01", "dl380_gen12_02", "dl380_gen12_03", "dl380_gen12_04",
            "sr650_v4_01", "sr650_v4_02", "sr650_v4_03", "sr650_v4_04"]
LABELS_1 = ["r1_DELL_R740_01", "r1_HPE_CSUS3200_01", "r1_HPE_CSUS3200_02", "r1_HPE_CSUS3200_03", "r1_HPE_CSUS3200_04", "r1_HPE_DL380_01", "r1_Lenovo_SR650_01"]


def load_env(label):
    p = SP / "baseline" / "tier1" / label / "gather_output.json"
    if not p.exists():
        return None
    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(lines[-1]) if lines else None


def load_access(label):
    p = SP / "baseline" / "tier1" / label / "server_access.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_t2(label, tag):
    p = SP / "baseline" / "tier2" / f"{label}.{tag}.module.json"
    return json.load(open(p, encoding="utf-8")) if p.exists() else None


def n(x):
    if isinstance(x, (list, dict)):
        return len(x)
    return x


rows = []
for label in LABELS_2 + LABELS_1:
    env = load_env(label)
    acc = load_access(label)
    keys = sorted({a["k"] for a in acc if a.get("k") not in (None, "/redfish")})
    (SP / "baseline" / "tier1" / label).mkdir(parents=True, exist_ok=True)
    with open(SP / "baseline" / "tier1" / label / "requested_keys.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump({"distinct_keys": keys, "by_auth_status_note": dict(Counter(f"{a['a']}/{a['s']}/{a['n']}" for a in acc)),
                   "non2xx_keys": sorted({a["k"] for a in acc if not (200 <= int(a["s"]) < 300) and a.get("k") is not None})}, f, ensure_ascii=False, indent=1)
    t2p = load_t2(label, "plain")
    t2a = load_t2(label, "adapter")
    r = {"label": label}
    if env:
        d = env.get("data") or {}
        diag = env.get("diagnosis") or {}
        det = diag.get("details") or {}
        r.update({
            "t1_status": env.get("status"), "t1_vendor": env.get("vendor"), "t1_hostname": env.get("hostname"),
            "t1_adapter": (env.get("meta") or {}).get("adapter_id"), "t1_first_pass": det.get("adapter_first_pass"),
            "t1_sections": env.get("sections"), "t1_errors": len(env.get("errors") or []),
            "t1_failure": {k: diag.get(k) for k in ("failure_stage", "failure_code", "auth_success")},
            "t1_auth": det.get("auth"), "t1_layout": det.get("multi_node_layout"), "t1_hostname_source": det.get("hostname_source"),
            "t1_rmc_activation_check": det.get("rmc_activation_check"),
            "t1_requests": len(acc), "t1_distinct_keys": len(keys),
            "t1_facts": {
                "hw_vendor": (d.get("hardware") or {}).get("vendor"), "hw_model": (d.get("hardware") or {}).get("model"),
                "hw_serial": (d.get("hardware") or {}).get("serial"), "hw_uuid": (d.get("hardware") or {}).get("uuid"),
                "bmc_fw": (d.get("bmc") or {}).get("firmware_version"), "bmc_model": (d.get("bmc") or {}).get("model"), "bmc_name": (d.get("bmc") or {}).get("name"),
                "cpu_sockets": (d.get("cpu") or {}).get("sockets"), "cpu_cores": (d.get("cpu") or {}).get("cores_physical"), "cpu_threads": (d.get("cpu") or {}).get("logical_threads"),
                "mem_total_mb": (d.get("memory") or {}).get("total_mb"), "mem_slots": n((d.get("memory") or {}).get("slots")),
                "disks": n((d.get("storage") or {}).get("physical_disks")), "controllers": n((d.get("storage") or {}).get("controllers")),
                "hbas": n((d.get("storage") or {}).get("hbas")), "ib": n((d.get("storage") or {}).get("infiniband")),
                "nics": n((d.get("network") or {}).get("interfaces")), "adapters": n((d.get("network") or {}).get("adapters")), "ports": n((d.get("network") or {}).get("ports")),
                "firmware": n(d.get("firmware")), "psus": n((d.get("power") or {}).get("power_supplies")), "fans": n((d.get("thermal") or {}).get("fans")),
                "temps": n((d.get("thermal") or {}).get("temperatures")), "bios_attrs": n(((d.get("bios") or {}).get("current") or {}).get("attributes")),
                "multi_node": None if d.get("multi_node") is None else {k: n(v) for k, v in d["multi_node"].items()} if isinstance(d.get("multi_node"), dict) else "?",
            },
        })
    for tag, t2 in (("plain", t2p), ("adapter", t2a)):
        if t2:
            r[f"t2_{tag}"] = {"status": t2.get("status"), "vendor": t2.get("vendor"), "collected": t2.get("collected"), "failed": t2.get("failed_sections"),
                              "unsupported": t2.get("unsupported_sections"), "error_count": t2.get("error_count", len(t2.get("errors") or [])),
                              "multi_node": None if t2.get("multi_node") is None else "dict"}
    rows.append(r)

with open(OUT / "baseline_summary.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(rows, f, ensure_ascii=False, indent=1)

md = ["| label | Tier1 status | vendor | adapter (1차 선택 → 최종) | errors | 요청 수 / 경로 | hostname | serial | cpu s/c/t | mem MB | disks | nics/adapters/ports | fw | psu/fan/temp | bios attrs | multi_node |",
      "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    f = r.get("t1_facts") or {}
    fp = r.get("t1_first_pass")
    ad = f"{fp or '-'} → {r.get('t1_adapter')}" if fp and fp != r.get("t1_adapter") else str(r.get("t1_adapter"))
    mn = f.get("multi_node")
    mn_s = "-" if mn is None else (",".join(f"{k}:{v}" for k, v in mn.items()) if isinstance(mn, dict) else str(mn))
    md.append(f"| {r['label']} | {r.get('t1_status')} | {r.get('t1_vendor')} | {ad} | {r.get('t1_errors')} | {r.get('t1_requests')} / {r.get('t1_distinct_keys')} | {r.get('t1_hostname')} | {f.get('hw_serial')} | {f.get('cpu_sockets')}/{f.get('cpu_cores')}/{f.get('cpu_threads')} | {f.get('mem_total_mb')} | {f.get('disks')} | {f.get('nics')}/{f.get('adapters')}/{f.get('ports')} | {f.get('firmware')} | {f.get('psus')}/{f.get('fans')}/{f.get('temps')} | {f.get('bios_attrs')} | {mn_s} |")
with open(OUT / "baseline_summary.md", "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(md) + "\n")
print("\n".join(md))
