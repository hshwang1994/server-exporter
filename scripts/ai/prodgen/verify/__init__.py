"""Gate runner: G01-G17 over a generated tree."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from ..common import ProdgenError

GATE_NAMES = {
    "G01": "allowlist integrity", "G02": "unclassified runtime files", "G03": "forbidden paths",
    "G04": "UTF-8 / LF / trailing newline", "G05": "per-file semantic re-verification",
    "G06": "diff-shape invariant", "G07": "residual comment scan", "G08": "dependency closure",
    "G09": "modes / exec bits", "G10": "vault header + plaintext secret scan",
    "G11": "ansible-playbook --syntax-check (WSL)", "G12": "ansible-config dump equality (WSL)",
    "G13": "Jenkins declarative linter", "G14": "tests overlay (pytest)", "G15": "module smoke (WSL)",
    "G16": "inventory.sh --list/--host equality", "G17": "determinism (second build)",
}
LIVE_GATES = {"G11", "G12", "G13", "G14", "G15"}


@dataclass
class GateResult:
    id: str
    status: str                      # PASS | FAIL | SKIP
    details: list = field(default_factory=list)
    data: dict = field(default_factory=dict)
    seconds: float = 0.0

    @property
    def name(self) -> str:
        return GATE_NAMES.get(self.id, self.id)


@dataclass
class GateReport:
    tree: str
    results: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.status != "FAIL" for r in self.results)

    def add(self, r: GateResult) -> None:
        self.results.append(r)

    def summary(self) -> str:
        lines = [f"[prodgen verify] tree={self.tree}"]
        for r in self.results:
            lines.append(f"  {r.id} {r.status:4s} {r.name} ({r.seconds:.1f}s)")
            for d in r.details[:12]:
                lines.append(f"       - {d}")
            if len(r.details) > 12:
                lines.append(f"       - ... {len(r.details) - 12} more")
        lines.append("[prodgen verify] " + ("PASS" if self.ok else "FAIL"))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "tree": self.tree, "ok": self.ok,
            "gates": [{"id": r.id, "name": r.name, "status": r.status, "seconds": round(r.seconds, 2),
                       "details": r.details, "data": r.data} for r in self.results],
        }


def run_gates(repo_root: str, tree_dir: str, manifest_path: str, *, skip_live: bool = False, only=None,
              netrc=None, jenkins_url: str = "https://jenkins-prod.gooddi.lab") -> GateReport:
    from . import depclosure, gates_live, gates_static
    tree_dir = os.path.abspath(tree_dir)
    report = GateReport(tree=tree_dir)
    wanted = set(x.strip().upper() for x in only.split(",")) if only else None
    ctx = gates_static.load_context(repo_root, tree_dir, manifest_path)
    if ctx.get("fatal"):
        report.add(GateResult("G00", "FAIL", [ctx["fatal"]]))
        return report

    gates = [
        ("G01", gates_static.g01_g03_allowlist), ("G02", None), ("G03", None),
        ("G04", gates_static.g04_encoding), ("G05", gates_static.g05_reverify),
        ("G06", gates_static.g06_diff_shape), ("G07", gates_static.g07_residual),
        ("G08", depclosure.g08_dependency_closure), ("G09", gates_static.g09_modes),
        ("G10", gates_static.g10_vault_and_secrets),
        ("G11", gates_live.g11_syntax_check), ("G12", gates_live.g12_config_dump),
        ("G13", gates_live.g13_jenkins_linter), ("G14", gates_live.g14_tests_overlay),
        ("G15", gates_live.g15_module_smoke),
        ("G16", gates_static.g16_inventory), ("G17", gates_static.g17_determinism),
    ]
    for gid, fn in gates:
        if fn is None:
            continue       # G02/G03 are produced together with G01
        ids = ["G01", "G02", "G03"] if gid == "G01" else [gid]
        if wanted and not any(i in wanted for i in ids):
            continue
        if gid in LIVE_GATES and skip_live:
            for i in ids:
                report.add(GateResult(i, "SKIP", ["--skip-live"]))
            continue
        t0 = time.time()
        try:
            out = fn(ctx, netrc=netrc, jenkins_url=jenkins_url) if gid == "G13" else fn(ctx)
        except ProdgenError as exc:
            out = [GateResult(i, "FAIL", [f"error: {exc}"]) for i in ids]
        if isinstance(out, GateResult):
            out = [out]
        for r in out:
            r.seconds = (time.time() - t0) / max(1, len(out))
            report.add(r)
    return report
