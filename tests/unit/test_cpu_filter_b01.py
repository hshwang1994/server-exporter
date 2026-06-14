"""Unit test for B01 — Redfish /Systems/.../Processors/ has CPU + GPU mix.

Validates the Jinja filter logic in:
  redfish-gather/tasks/normalize_standard.yml :: _rf_d_cpus + _rf_summary_cpu

Mirrors the Jinja2 logic in Python and asserts:
  - GPU/Accelerator entries are excluded from cpu groups
  - cpu.sockets reflects only CPU count (not CPU+GPU)
  - Legacy BMC with ProcessorType=None still classified as CPU (compat)
"""
from __future__ import annotations

import pytest


def filter_cpus(procs: list[dict]) -> list[dict]:
    """Mirror of `_rf_d_cpus` filter (B01 fix)."""
    out = []
    for p in procs:
        ptype = (p.get("processor_type") or "").strip().upper()
        if ptype == "CPU" or ptype == "":
            out.append(p)
    return out


def build_cpu_summary(cpus: list[dict]) -> dict:
    """Mirror of `_rf_summary_cpu` builder."""
    groups = []
    seen = {}
    for p in cpus:
        m = p.get("model") or "unknown"
        if m in seen:
            idx = seen[m]
            groups[idx]["sockets"] += 1
            groups[idx]["total_cores"] += int(p.get("total_cores") or 0)
        else:
            seen[m] = len(groups)
            groups.append({
                "model": m,
                "manufacturer": p.get("manufacturer"),
                "max_speed_mhz": p.get("speed_mhz"),
                "architecture": p.get("architecture") or p.get("instruction_set"),
                "sockets": 1,
                "cores_per_socket": int(p.get("total_cores") or 0),
                "total_cores": int(p.get("total_cores") or 0),
            })
    return {"groups": groups}


def test_b01_excludes_gpu_from_cpu_summary():
    """Dell r760-1 had Tesla T4 + 2× Intel Xeon Silver 4510. GPU must be excluded."""
    procs = [
        {"id": "Procs.Socket.1", "model": "Tesla T4", "manufacturer": "NVIDIA Corporation",
         "total_cores": 0, "total_threads": 0, "processor_type": "GPU"},
        {"id": "CPU.Socket.1", "model": "INTEL(R) XEON(R) SILVER 4510",
         "manufacturer": "Intel", "total_cores": 12, "total_threads": 24,
         "speed_mhz": 4100, "processor_type": "CPU"},
        {"id": "CPU.Socket.2", "model": "INTEL(R) XEON(R) SILVER 4510",
         "manufacturer": "Intel", "total_cores": 12, "total_threads": 24,
         "speed_mhz": 4100, "processor_type": "CPU"},
    ]
    cpus = filter_cpus(procs)
    assert len(cpus) == 2
    assert all(c["processor_type"] == "CPU" for c in cpus)
    summary = build_cpu_summary(cpus)
    assert len(summary["groups"]) == 1
    assert summary["groups"][0]["model"] == "INTEL(R) XEON(R) SILVER 4510"
    assert summary["groups"][0]["sockets"] == 2
    assert summary["groups"][0]["total_cores"] == 24


def test_b01_legacy_no_processor_type_still_counts():
    """Older BMC may not return ProcessorType — empty string treated as CPU (compat)."""
    procs = [
        {"id": "P0", "model": "Old Xeon", "total_cores": 8, "processor_type": ""},
        {"id": "P1", "model": "Old Xeon", "total_cores": 8},  # missing entirely
    ]
    cpus = filter_cpus(procs)
    assert len(cpus) == 2
    summary = build_cpu_summary(cpus)
    assert summary["groups"][0]["sockets"] == 2


def test_b01_excludes_accelerator_fpga_dsp():
    """Other non-CPU types (Accelerator, FPGA, DSP) also excluded."""
    procs = [
        {"id": "C1", "model": "EPYC 9354", "total_cores": 32, "processor_type": "CPU"},
        {"id": "FPGA1", "model": "Xilinx Alveo", "processor_type": "FPGA"},
        {"id": "DSP1", "model": "TI DSP", "processor_type": "DSP"},
        {"id": "ACC1", "model": "AI Accelerator", "processor_type": "Accelerator"},
    ]
    cpus = filter_cpus(procs)
    assert [c["id"] for c in cpus] == ["C1"]
    summary = build_cpu_summary(cpus)
    assert summary["groups"][0]["model"] == "EPYC 9354"
    assert summary["groups"][0]["sockets"] == 1


def test_b01_only_gpu_yields_empty_cpu_summary():
    """Edge: only GPUs present (no CPU) — summary.groups should be empty."""
    procs = [
        {"id": "GPU1", "model": "A100", "processor_type": "GPU"},
        {"id": "GPU2", "model": "H100", "processor_type": "GPU"},
    ]
    cpus = filter_cpus(procs)
    assert cpus == []
    summary = build_cpu_summary(cpus)
    assert summary["groups"] == []
