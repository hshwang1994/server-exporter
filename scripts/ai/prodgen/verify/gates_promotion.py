"""Promotion gates (2026-10-04): G18 production state/drift, G19 customer-main-form execution, G20 ancestry + remote baseline.

G18  drift-check with the production *state* classification (LEGACY only ok as the explicit bootstrap baseline).
G19  the generated tree is pushed as the only branch `main` of a throw-away bare repository (no `production` ref), cloned into an empty
     directory and the three channel playbooks are executed there against controlled unreachable targets (TEST-NET) with the vault
     password formally bound (file outside the clone, removed afterwards). Verified: one envelope per host, 13 keys, channel/ip,
     failure_stage/code/reason present, no silent failure, no plaintext secret in outputs, no dev files / no dev paths in the clone.
     Scope: initial execution · precheck · failure envelope · output. It does NOT prove successful collection, credential use, vendor
     branches or parser execution — those are the main/production Job E2E (plan §5). Unreachable targets do not guarantee a
     particular failure code: the observed condition is recorded and compared with `expected_failure_code`; a mismatch is PARTIAL
     (INVALID condition), never silently PASS.
G20  all push remotes agree on refs/heads/production and equal the local ref; the new tree's main SHA descends from the main SHA of
     the previous generated production (monotonic); a legacy baseline is accepted only via --bootstrap-baseline <that sha>.
"""
from __future__ import annotations

import json
import os
import subprocess

from ..common import ProdgenError
from ..drift import classify_production, drift_check, is_ancestor, previous_generated_main
from . import GateResult
from .gates_live import _bash, _stage_tree_in_linux, _wsl_available, _wsl_path

G19_CHECKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "g19_check.py")


def ls_remote(store, remote: str, ref: str):
    """(sha | '' when the ref is absent | None on error, error text)."""
    try:
        proc = subprocess.run(["git", "ls-remote", remote, ref], cwd=store.repo_root, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if proc.returncode != 0:
        return None, proc.stderr.strip()[:200]
    return (proc.stdout.split()[0] if proc.stdout.strip() else ""), None


# ── G18 ──────────────────────────────────────────────────────────────────────────
def g18_drift(ctx) -> GateResult:
    p = ctx["promotion"]
    store = ctx["store"]
    ref = p["production_ref"]
    if not store.rev_exists(ref):
        return GateResult("G18", "PASS", [f"no local {ref} — first promotion, nothing to drift"], {"state": "NONE"})
    res = drift_check(ctx["repo_root"], ref, ctx["manifest_path"], bootstrap_baseline=p.get("bootstrap_baseline"))
    state = res.get("state", {})
    details = [f"state={state.get('state')} production={res['production'][:12]} ok={res['ok']}"] + list(state.get("reasons", []))[:5]
    for k, v in res.get("checks", {}).items():
        if isinstance(v, dict) and "ok" in v:
            details.append(f"{k}: {'ok' if v['ok'] else 'MISMATCH' if v['ok'] is False else 'n/a'}")
    data = {"state": state.get("state"), "production": res["production"], "baseline": state.get("baseline"),
            "previous_generated": state.get("previous_generated"), "checks": {k: (v.get("ok") if isinstance(v, dict) else v) for k, v in res.get("checks", {}).items()}}
    return GateResult("G18", "PASS" if res["ok"] else "FAIL", details, data)


# ── G20 ──────────────────────────────────────────────────────────────────────────
def g20_ancestry_and_remotes(ctx) -> GateResult:
    p = ctx["promotion"]
    store = ctx["store"]
    ref = p["production_ref"]
    prov = ctx["prov"]
    details, failed = [], False
    local = store.rev_parse(ref) if store.rev_exists(ref) else None
    data = {"local": local, "remotes": {}, "new_main": prov.get("main_sha")}
    remote_shas = {}
    for r in p.get("remotes") or []:
        sha, err = ls_remote(store, r, ref)
        if err is not None:
            failed = True
            details.append(f"{r}: ls-remote failed: {err}")
            data["remotes"][r] = f"error: {err}"
        else:
            remote_shas[r] = sha
            data["remotes"][r] = sha or "(absent)"
    distinct = set(remote_shas.values())
    expected_parent = local
    if len(distinct) > 1:
        failed = True
        details.append(f"remotes disagree on {ref}: {remote_shas} — run `prodgen push-sync` first")
    elif distinct:
        remote = next(iter(distinct))
        expected_parent = remote or None
        if (local or "") != (remote or ""):
            failed = True
            details.append(f"local {ref}={(local or 'absent')[:12]} != remotes {(remote or 'absent')[:12]} — fetch / push-sync first")
    from .. import DEPLOY_REMOTES
    checked = list(p.get("remotes") or [])
    data["remotes_checked"] = checked
    data["deploy_set_complete"] = set(DEPLOY_REMOTES) <= set(checked)
    if not checked:
        # 검토 C4: a G20 with no remote is not a pass — the remote baseline was not verified at all
        data["partial"] = True
        data["partial_reason"] = "no remotes given — remote baseline not verified (local ref only)"
        details.append("no remotes given — remote baseline NOT verified (partial)")
    elif not data["deploy_set_complete"]:
        details.append(f"remotes checked {checked} do not cover the deploy set {list(DEPLOY_REMOTES)} — a real promotion re-runs G20 with the full set")
    data["expected_parent"] = expected_parent

    new_main = prov.get("main_sha")
    prev_commit, prev_main = previous_generated_main(store, expected_parent)
    if expected_parent is None:
        details.append("no production anywhere — first promotion, no ancestry constraint")
    elif prev_main is None:
        st = classify_production(store, expected_parent, p.get("bootstrap_baseline"))
        data["baseline_state"] = st.get("state")
        if st["state"] == "LEGACY" and st["ok"]:
            details.append(f"legacy baseline {expected_parent[:12]} accepted via --bootstrap-baseline (no previous generated main)")
        elif st["state"] == "RESTORED_BASELINE":
            prev_commit, prev_main = st.get("previous_generated"), st.get("previous_generated_main_sha")
            details.append(f"restored baseline — previous generated main from {str(prev_commit)[:12]}")
        else:
            failed = True
            details.append(f"production state {st['state']} is not promotable: {'; '.join(st.get('reasons', []))}")
    if prev_main:
        if store.rev_exists(prev_main) and new_main and is_ancestor(store, prev_main, new_main):
            details.append(f"main {new_main[:12]} descends from previous generated main {prev_main[:12]} (monotonic)")
        else:
            failed = True
            details.append(f"main {str(new_main)[:12]} is not a descendant of previous generated main {prev_main[:12]} — non-monotonic promotion refused")
    data.update({"previous_generated": prev_commit, "previous_generated_main": prev_main})
    return GateResult("G20", "FAIL" if failed else "PASS", details, data)


# ── G19 ──────────────────────────────────────────────────────────────────────────
def g19_customer_main_form(ctx) -> GateResult:
    p = ctx["promotion"]
    if not _wsl_available():
        return GateResult("G19", "SKIP", ["no WSL / ansible-playbook available"])
    pw = p.get("vault_password_file")
    if not pw or not os.path.isfile(pw):
        return GateResult("G19", "SKIP", ["no --vault-password-file: the 3-channel execution needs the vault credential formally bound"])
    if not os.path.isfile(G19_CHECKER):
        return GateResult("G19", "FAIL", [f"checker missing: {G19_CHECKER}"])
    try:
        dest = _stage_tree_in_linux(ctx, "g19")
    except RuntimeError as exc:
        return GateResult("G19", "FAIL", [str(exc)])
    expected_code = p.get("expected_failure_code") or "TARGET_UNREACHABLE"
    work = f"{dest}-work"
    checker = _wsl_path(G19_CHECKER)
    pw_lin = _wsl_path(os.path.abspath(pw))
    # bash side: customer-form repo (main only) → clone → run checker (python3 in the Linux environment)
    script = (
        f"set -u; W='{work}'; rm -rf \"$W\" && mkdir -p \"$W/out\" && "
        f"PW=$(mktemp) && cp '{pw_lin}' \"$PW\" && chmod 600 \"$PW\" && "
        f"cp -r '{dest}' \"$W/src\" && cd \"$W/src\" && git init -q && git checkout -q -b main && git add -A && "
        f"git -c user.name=prodgen -c user.email=prodgen@invalid commit -q -m 'customer main form' && "
        f"git init -q --bare \"$W/customer.git\" && git push -q \"$W/customer.git\" main && "
        f"git clone -q -b main \"$W/customer.git\" \"$W/clone\" && "
        f"cp '{checker}' \"$W/g19_check.py\" && "
        f"python3 \"$W/g19_check.py\" --work \"$W\" --clone \"$W/clone\" --bare \"$W/customer.git\" --vault-password-file \"$PW\" "
        f"--expected-failure-code '{expected_code}' --timeout 300; rc=$?; rm -f \"$PW\"; exit $rc"
    )
    try:
        proc = _bash(script, timeout=1500)
    except subprocess.TimeoutExpired:
        return GateResult("G19", "FAIL", ["customer-form execution exceeded 1500s"])
    out = proc.stdout.strip()
    start = out.rfind("\n{")
    payload_text = out[start + 1:] if start != -1 else out
    try:
        summary = json.loads(payload_text)
    except ValueError:
        return GateResult("G19", "FAIL", [f"checker produced no JSON (rc={proc.returncode})", (proc.stderr or out)[-400:]])
    details = list(summary.get("details", []))[:20]
    data = {k: v for k, v in summary.items() if k != "details"}
    status = "FAIL" if summary.get("failed") else "PASS"
    if status == "PASS" and summary.get("condition_mismatch"):
        data["partial"] = True
        data["partial_reason"] = f"failure condition differs from expected ({expected_code}) — INVALID condition, not a pass: {summary.get('condition_mismatch')}"
    return GateResult("G19", status, details, data)
