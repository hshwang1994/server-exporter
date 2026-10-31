"""Scratch: mutation checks for SA fixes in the module, normalize_standard.yml and the ESXi power filter. Run from the repo root.

Same method as mutate.py — each mutation reverts one fix by an exactly-once string replace in one file, runs the given pytest
files in a fresh process, and restores the file bytes (hash-verified). Killed = pytest exits non-zero. The last pytest summary
line is printed so a mutation that breaks parsing (everything erroring) is visible as such.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

NL = "\n"
RG = "redfish-gather/library/redfish_gather.py"
NS = "redfish-gather/tasks/normalize_standard.yml"
PS = "filter_plugins/power_summary.py"
T_NULL = "tests/unit/test_redfish_summary_null_rules.py"
T_SA01 = "tests/unit/test_multi_node_counts_sa01.py"
T_SA03 = "tests/unit/test_partition_summary_rules_sa03.py"

MUTATIONS = [
    # ── module ──
    ("SA-05 module: unread DIMM keeps the partial sum", RG,
     "    if unread or not walk.get('complete'):",
     "    if False:",
     [T_NULL]),
    ("SA-01 fabric endpoint_count back to len([])", RG,
     "'endpoint_count': (len(endpoints) if endpoints_ok else None),",
     "'endpoint_count': len(endpoints),",
     [T_SA01]),
    ("SA-02 fabric_count back to 0 when not confirmed", RG,
     "'fabric_count':              (len(fabrics) if isinstance(fabrics, list) and fab_state.get('complete') else None),",
     "'fabric_count':              (len(fabrics) if isinstance(fabrics, list) else 0),",
     [T_SA01]),
    ("SA-01 manager_count without the completeness check", RG,
     "'manager_count':             (len(managers) if mgr_result.get('complete') else None),",
     "'manager_count':             len(managers),",
     [T_SA01]),
    ("SA-03 partition CPU manufacturer not canonicalised", RG,
     "    for tokens, name in _CPU_MFR_CANON:",
     "    for tokens, name in ():",
     [T_SA03]),
    ("SA-03 partition DIMM GiB floored again", RG,
     "        cap_gb = int(round(cap_mb / MIB_PER_GIB)) if cap_mb > 0 else 0",
     "        cap_gb = cap_mb // MIB_PER_GIB if cap_mb > 0 else 0",
     [T_SA03]),
    ("SA-03 partition MemorySummary used without the check", RG,
     "    trusted_gib = ms_gib if ms_ok else None",
     "    trusted_gib = ms_gib",
     [T_SA03]),
    ("SA-19 EnvironmentMetrics ReadingRange back into min/max", RG,
     "                    power_control['power_consumed_watts'] = pc_consumed" + NL
     + "        # interval_in_min / avg_consumed_watts: EnvironmentMetrics 표준에 없음 — None 유지",
     "                    power_control['power_consumed_watts'] = pc_consumed" + NL
     + "                power_control['min_consumed_watts'] = _safe_int(pw.get('ReadingRangeMin'))" + NL
     + "                power_control['max_consumed_watts'] = _safe_int(pw.get('ReadingRangeMax'))" + NL
     + "        # interval_in_min / avg_consumed_watts: EnvironmentMetrics 표준에 없음 — None 유지",
     ["tests/unit/test_power_environment_metrics_f5.py"]),
    # ── normalize_standard.yml ──
    ("SA-04 cores_physical uses the partial core sum", NS,
     "'cores': (ns.known if _cores_ok else (_cc if _cc_ok else none))",
     "'cores': ns.known",
     [T_NULL]),
    ("SA-04 sockets uses the partial list length", NS,
     "'sockets': (_n if _list_ok else (_cnt if (_cnt is not none and _cnt_ok) else none)),",
     "'sockets': _n,",
     [T_NULL]),
    ("SA-04 group total_cores is a partial sum", NS,
     "{%- set _new_total = none if ns.unk.get(idx, false) else (ns.groups[idx].total_cores + cores) -%}",
     "{%- set _new_total = (ns.groups[idx].total_cores or 0) + (cores or 0) -%}",
     [T_NULL]),
    ("SA-05 memory grand uses the partial DIMM sum", NS,
     "if _rf_mem_basis.complete else _rf_mem_basis.summary_gib)} }}",
     "if true else _rf_mem_basis.summary_gib)} }}",
     [T_NULL]),
    ("SA-05 MemorySummary used without the check", NS,
     "{%- set _g_ok = (_g > 0) and (((_g * 1024) > ns.known) if ns.unknown > 0 else ((_g * 1024) >= ns.known)) -%}",
     "{%- set _g_ok = (_g > 0) -%}",
     [T_NULL]),
    ("SA-07 storage grand sums regardless of the drive-list basis", NS,
     "(ns.total if _rf_storage_basis.countable else none)",
     "ns.total",
     [T_NULL]),
    ("SA-07 empty but never-enumerated storage counts as 0", NS,
     "'countable': _attempted and _enum and (not _incomplete)",
     "'countable': _attempted and (not _incomplete)",
     [T_NULL]),
    ("SA-08 group key keeps speed 0", NS,
     "{%- set gsp = none if (sp is not none and sp == 0) else sp -%}",
     "{%- set gsp = sp -%}",
     [T_NULL, "tests/unit/test_redfish_xcc3_shape.py"]),
    ("SA-10 primary speed back to the first link-up NIC", NS,
     "{%- if ((n.is_primary | default(false)) is sameas true) and ns.primary_sp is none and sp -%}",
     "{%- if link_up and ns.primary_sp is none and sp -%}",
     [T_NULL]),
    ("SA-01 adapter_count 0 when network_adapters not read", NS,
     "'adapter_count': (ns.adapter_count if 'network_adapters' in _col else none),",
     "'adapter_count': ns.adapter_count,",
     [T_NULL]),
    ("SA-01 port_count 0 when network not read", NS,
     "'port_count': (((_rf_norm_interfaces | default([])) | length) if 'network' in _col else none),",
     "'port_count': ((_rf_norm_interfaces | default([])) | length),",
     [T_NULL]),
    ("SA-06 Redfish rollup 'Unknown' with no installed PSU", NS,
     "'health_rollup': (none if ns.psu_total == 0 else (",
     "'health_rollup': (none if false else (",
     ["tests/unit/test_power_summary_b58_b59.py"]),
    # ── ESXi filter ──
    ("SA-06 ESXi rollup 'Unknown' with no PSU sensor", PS,
     "    if psu_total == 0:" + NL + "        rollup = None",
     "    if False:" + NL + "        rollup = None",
     ["tests/unit/test_esxi_sensors.py"]),
    # ── second batch (storage inventory flags · composition count · partition storage) ──
    ("B2 SA-07 module: unread drive member does not mark the list incomplete", RG,
     "f'Drive {d_uri} 실패: {derr or dst}', code=_CODE_NON_BLOCKING_SUBRESOURCE))" + NL + "            _inv_set(inv, 'incomplete')" + NL,
     "f'Drive {d_uri} 실패: {derr or dst}', code=_CODE_NON_BLOCKING_SUBRESOURCE))" + NL,
     [T_NULL, "tests/integration/test_chassis_drives_union_sa12.py"]),
    ("B2 SA-07 module: empty Storage Drives array is not a drive-list source", RG,
     "    if isinstance(raw, list):" + NL + "        _inv_set(inv, 'enumerated')",
     "    if isinstance(raw, list) and raw:" + NL + "        _inv_set(inv, 'enumerated')",
     [T_NULL, "tests/integration/test_chassis_drives_union_sa12.py"]),
    ("B2 SA-02 composition resource_block_count back to len()", RG,
     "'resource_block_count': (len(blocks) if rb_complete else None),",
     "'resource_block_count': len(blocks),",
     [T_SA01]),
    ("B2 SA-03 partition storage grand ignores the drive-list basis", RG,
     "    countable = enumerated and inv.get('incomplete') is not True",
     "    countable = True",
     [T_SA03]),
]
if sys.argv[1:]:
    MUTATIONS = [m for m in MUTATIONS if any(a in m[0] for a in sys.argv[1:])]

originals = {}
for _, f, _, _, _ in MUTATIONS:
    if f not in originals:
        b = Path(f).read_bytes()
        originals[f] = (b, hashlib.sha256(b).hexdigest(), (b"\r" + b"\n") in b)

results = []
try:
    for title, f, old, new, files in MUTATIONS:
        raw, _, crlf = originals[f]
        src = raw.decode("utf-8").replace("\r" + NL, NL)
        n = src.count(old)
        if n != 1:
            results.append((title, None, f"ANCHOR COUNT {n}"))
            continue
        mut = src.replace(old, new)
        if crlf:
            mut = mut.replace(NL, "\r" + NL)
        Path(f).write_bytes(mut.encode("utf-8"))
        try:
            p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header", *files],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
            last = [line for line in p.stdout.splitlines() if line.strip()][-1:]
            results.append((title, p.returncode, last[0] if last else ""))
        finally:
            Path(f).write_bytes(raw)
finally:
    for f, (raw, _, _) in originals.items():
        Path(f).write_bytes(raw)
for f, (_, h, _) in originals.items():
    assert hashlib.sha256(Path(f).read_bytes()).hexdigest() == h, ("restore failed", f)
for title, rc, last in results:
    tag = "ANCHOR?  " if rc is None else ("KILLED   " if rc != 0 else "SURVIVED ")
    print(tag + title + " :: " + last)
