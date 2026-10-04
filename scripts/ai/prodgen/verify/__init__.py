"""Gate runner: G01-G20 over a generated tree, with a three-valued verdict.

Verdict (2026-10-04, Astra 2~4차 R1 · §8-3):
  FAIL          — any gate FAIL.
  PARTIAL       — a mandatory gate is absent from the report (--only), SKIP (--skip-live, no netrc, no WSL, no vault password) or
                  reports an inner partial (e.g. G14: a mandatory test group executed nothing). Not a pass.
  COMPLETE_PASS — every mandatory gate ran and passed. The only verdict `promote` accepts.

The report carries a *binding* (what was verified: main_sha · main_tree · tree_hash · generator_hash · manifest_sha256 ·
gate statuses · verify_mode · netrc_used · bootstrap_baseline) plus *environment identifiers* (python · ansible · platform ·
host · pwsh/groovy presence · jenkins version) so a consumer can decide what may be reused: code/tree-only gates when the
binding matches, environment-dependent gates (G11 G12 G13 G14 G15 G19) only when the environment identifiers match too,
mutable-state gates (G18 G20) never — they are re-run at promote time. `report_sha256` is a tamper/mix-up detector over the
canonical JSON without that field; it is not proof of execution — `source` names where the report was produced.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field

from ..common import ProdgenError, is_windows

GATE_NAMES = {
    "G01": "allowlist integrity", "G02": "unclassified runtime files", "G03": "forbidden paths",
    "G04": "UTF-8 / LF / trailing newline", "G05": "per-file semantic re-verification",
    "G06": "diff-shape invariant", "G07": "residual comment scan", "G08": "dependency closure",
    "G09": "modes / exec bits", "G10": "vault header + plaintext secret scan",
    "G11": "ansible-playbook --syntax-check (WSL)", "G12": "ansible-config dump equality (WSL)",
    "G13": "Jenkins declarative linter", "G14": "tests overlay (pytest) + mandatory test groups", "G15": "custom module execution smoke (WSL)",
    "G16": "inventory.sh --list/--host equality", "G17": "determinism (second build)",
    "G18": "production drift / state (LEGACY · PROVENANCE · RESTORED_BASELINE)",
    "G19": "customer-main-form clean checkout: 3-channel playbook execution", "G20": "ancestry + remote baseline equality",
}
MANDATORY_GATES = tuple(f"G{i:02d}" for i in range(1, 21))
# environment-dependent gates: reusable only when the environment identifiers match (4차 §4 — by the tools they actually call)
ENV_DEPENDENT_GATES = {"G11", "G12", "G13", "G14", "G15", "G19"}
# mutable-state gates: never reused, re-run right before promotion
MUTABLE_GATES = {"G18", "G20"}
LIVE_GATES = {"G11", "G12", "G13", "G14", "G15", "G19"}
# identifiers compared before reusing an environment-dependent gate. An *unknown* value on either side is not a match (검토 C3):
#   G11/G12/G15/G19 → python · platform · ansible (runtime · version · installed collections), G13 → jenkins_version,
#   prodgen build → pwsh/groovy **versions** (presence alone does not identify the toolchain)
ENV_COMPARE_KEYS = ("python", "platform", "ansible_runtime", "ansible_version", "collections_sha256", "pwsh", "groovy", "jenkins_version")
UNKNOWN_VALUES = (None, "", "unknown")


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

    @property
    def partial(self) -> bool:
        """PASS at the top level but a required inner check did not execute (e.g. G14 mandatory test groups)."""
        return bool(self.data.get("partial"))


def canonical_digest(payload: dict) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class GateReport:
    tree: str
    results: list = field(default_factory=list)
    verify_mode: str = "full"                    # full | skip_live | only:<ids>
    netrc_used: bool = False
    bootstrap_baseline: dict | None = None       # {"sha":..., "tree_oid":...} | None
    binding: dict = field(default_factory=dict)
    environment: dict = field(default_factory=dict)
    source: dict = field(default_factory=dict)   # {"kind": "local"|"ci", "host":..., "build_url":...}
    e2e_evidence: dict | None = None             # filled by `evidence-aggregate`

    # ── judgement ─────────────────────────────────────────────────────────────
    @property
    def statuses(self) -> dict:
        return {r.id: r.status for r in self.results}

    @property
    def mandatory_missing(self) -> list:
        out = []
        st = self.statuses
        for gid in MANDATORY_GATES:
            if gid not in st:
                out.append(f"{gid}: not run")
            elif st[gid] == "SKIP":
                out.append(f"{gid}: SKIP")
        for r in self.results:
            if r.status == "PASS" and r.partial:
                out.append(f"{r.id}: partial — {r.data.get('partial_reason', 'required inner checks did not execute')}")
        return out

    @property
    def verdict(self) -> str:
        if any(r.status == "FAIL" for r in self.results):
            return "FAIL"
        if self.mandatory_missing:
            return "PARTIAL"
        return "COMPLETE_PASS"

    @property
    def ok(self) -> bool:
        return self.verdict == "COMPLETE_PASS"

    def add(self, r: GateResult) -> None:
        self.results.append(r)

    def summary(self) -> str:
        lines = [f"[prodgen verify] tree={self.tree} mode={self.verify_mode}"]
        for r in self.results:
            flag = " (partial)" if r.partial else ""
            lines.append(f"  {r.id} {r.status:4s} {r.name}{flag} ({r.seconds:.1f}s)")
            for d in r.details[:12]:
                lines.append(f"       - {d}")
            if len(r.details) > 12:
                lines.append(f"       - ... {len(r.details) - 12} more")
        for m in self.mandatory_missing:
            lines.append(f"  !! {m}")
        lines.append(f"[prodgen verify] {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        payload = {
            "tree": self.tree, "verdict": self.verdict, "ok": self.ok,
            "verify_mode": self.verify_mode, "netrc_used": self.netrc_used,
            "mandatory_missing": self.mandatory_missing,
            "binding": self.binding, "environment": self.environment, "source": self.source,
            "bootstrap_baseline": self.bootstrap_baseline,
            "gates": [{"id": r.id, "name": r.name, "status": r.status, "partial": r.partial, "seconds": round(r.seconds, 2),
                       "details": r.details, "data": r.data} for r in self.results],
            "e2e_evidence": self.e2e_evidence,
        }
        payload["report_sha256"] = canonical_digest(payload)
        return payload


def report_digest_ok(payload: dict) -> bool:
    """Recompute `report_sha256` over everything else (sidecar-equivalent). False = tampered, mixed up or hand-edited."""
    if not isinstance(payload, dict) or "report_sha256" not in payload:
        return False
    body = {k: v for k, v in payload.items() if k != "report_sha256"}
    return canonical_digest(body) == payload["report_sha256"]


# ── environment identifiers ────────────────────────────────────────────────────
def _probe(cmd: list, timeout: int = 20) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return (proc.stdout or proc.stderr).strip().splitlines()[0] if (proc.stdout or proc.stderr).strip() else ""
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return ""


def probe_jenkins_version(jenkins_url: str | None, netrc: str | None) -> str:
    """`X-Jenkins` response header of GET /api/json (the pipeline-model-converter response does not carry it — GP-29)."""
    curl = shutil.which("curl")
    if not curl or not jenkins_url or not netrc or not os.path.isfile(netrc):
        return ""
    try:
        proc = subprocess.run([curl, "-skI", "--netrc-file", netrc, "--max-time", "30", jenkins_url.rstrip("/") + "/api/json"],
                              capture_output=True, text=True, timeout=40, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in (proc.stdout or "").splitlines():
        if line.lower().startswith("x-jenkins:"):
            return line.split(":", 1)[1].strip()
    return ""


def _tool_version(cmd: list) -> str:
    out = _probe(cmd)
    return out if out else "absent"


def _collections_digest(prefix: list) -> tuple:
    """sha256 over the sorted `name:version` list of installed Ansible collections (G11/G12/G15/G19 depend on them)."""
    try:
        proc = subprocess.run(prefix + ["ansible-galaxy collection list --format json 2>/dev/null"], capture_output=True, text=True,
                              timeout=90, encoding="utf-8", errors="replace")
        data = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return "", 0
    pairs = sorted(f"{name}:{info.get('version')}" for path in data.values() for name, info in (path or {}).items())
    if not pairs:
        return "", 0
    return hashlib.sha256("\n".join(pairs).encode("utf-8")).hexdigest(), len(pairs)


def collect_environment(jenkins_version: str | None = None, *, netrc: str | None = None, jenkins_url: str | None = None) -> dict:
    """Identifiers of the environment the gates ran in. Compared by `environment_compatible` before reusing env-dependent gates.
    Unknown values stay empty — the comparison treats them as *not verified*, never as a match."""
    pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
    ps_cmd = ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"]
    if pwsh:
        pwsh_version = _tool_version([pwsh] + ps_cmd)
    elif shutil.which("powershell.exe"):
        pwsh_version = _tool_version(["powershell.exe"] + ps_cmd)
    else:
        pwsh_version = "absent"
    env = {
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "host": socket.gethostname(),
        "pwsh": pwsh_version,
        "groovy": _tool_version(["groovy", "--version"]) if shutil.which("groovy") else "absent",
    }
    if is_windows() and shutil.which("wsl.exe"):
        prefix = ["wsl.exe", "-e", "bash", "-lc"]
        env["ansible_runtime"] = "wsl"
    else:
        prefix = ["bash", "-lc"]
        env["ansible_runtime"] = "native"
    env["ansible_version"] = _probe(prefix + ["ansible --version 2>/dev/null | head -1"])
    env["collections_sha256"], env["collections_count"] = _collections_digest(prefix)
    env["jenkins_version"] = jenkins_version or probe_jenkins_version(jenkins_url, netrc) or ""
    return env


def environment_compatible(recorded: dict, current: dict, keys=ENV_COMPARE_KEYS) -> tuple:
    """Same environment for the env-dependent gates? Unknown on either side → not verified → not compatible (검토 C3)."""
    problems = []
    for key in keys:
        a, b = (recorded or {}).get(key), (current or {}).get(key)
        if a in UNKNOWN_VALUES or b in UNKNOWN_VALUES:
            problems.append(f"{key}: not verified (recorded {a!r}, current {b!r})")
        elif a != b:
            problems.append(f"{key}: recorded {a!r} != current {b!r}")
    return (not problems), problems


# ── runner ─────────────────────────────────────────────────────────────────────
def run_gates(repo_root: str, tree_dir: str, manifest_path: str, *, skip_live: bool = False, only=None,
              netrc=None, jenkins_url: str = "https://jenkins-prod.gooddi.lab",
              bootstrap_baseline: str | None = None, production_ref: str = "refs/heads/production",
              remotes=None, vault_password_file: str | None = None, main_ref: str | None = None,
              source: dict | None = None) -> GateReport:
    from . import depclosure, gates_live, gates_promotion, gates_static
    tree_dir = os.path.abspath(tree_dir)
    wanted = set(x.strip().upper() for x in only.split(",")) if only else None
    report = GateReport(tree=tree_dir, netrc_used=bool(netrc and os.path.isfile(netrc)))
    report.verify_mode = "only:" + ",".join(sorted(wanted)) if wanted else ("skip_live" if skip_live else "full")
    report.source = source or {"kind": "local", "host": socket.gethostname()}
    ctx = gates_static.load_context(repo_root, tree_dir, manifest_path)
    if ctx.get("fatal"):
        report.add(GateResult("G00", "FAIL", [ctx["fatal"]]))
        return report
    ctx["promotion"] = {"production_ref": production_ref, "remotes": list(remotes or []), "bootstrap_baseline": bootstrap_baseline,
                        "vault_password_file": vault_password_file, "main_ref": main_ref}

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
        ("G18", gates_promotion.g18_drift), ("G19", gates_promotion.g19_customer_main_form),
        ("G20", gates_promotion.g20_ancestry_and_remotes),
    ]
    jenkins_version = None
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
            if r.id == "G13":
                jenkins_version = r.data.get("jenkins_version") or jenkins_version
            report.add(r)
    report.environment = collect_environment(jenkins_version, netrc=netrc, jenkins_url=jenkins_url)
    prov = ctx["prov"]
    bb = None
    if bootstrap_baseline:
        try:
            store = ctx["store"]
            sha = store.rev_parse(bootstrap_baseline)
            bb = {"sha": sha, "tree_oid": store.commit_tree_sha(sha)}
        except ProdgenError as exc:
            bb = {"sha": bootstrap_baseline, "error": str(exc)}
    report.bootstrap_baseline = bb
    report.binding = {
        "main_sha": prov.get("main_sha"), "main_tree": prov.get("main_tree"), "tree_hash": prov.get("tree_hash"),
        "generator_version": prov.get("generator_version"), "generator_hash": prov.get("generator_hash"),
        "rules_version": prov.get("rules_version"), "manifest_sha256": prov.get("manifest_sha256"),
        "gates": [{"id": r.id, "status": r.status, "partial": r.partial} for r in report.results],
        "verify_mode": report.verify_mode, "netrc_used": report.netrc_used, "bootstrap_baseline": bb,
    }
    return report
