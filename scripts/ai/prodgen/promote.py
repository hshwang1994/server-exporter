"""`prodgen promote` / `prodgen restore` / `prodgen push-sync` via git plumbing (dry-run capable).

promote (2026-10-04, Astra 2~4차 R1 · R2 · R4 · §8 · 검토 C2~C4):
  deploy policy (a real run publishes to exactly DEPLOY_REMOTES — origin + internal; fewer or other remotes are refused)
  → build(sha) → gates (full run, or a reused COMPLETE_PASS report whose binding matches; G18/G20 are always re-run and the
  environment-dependent gates G11-G15/G19 are re-run when the environment identifiers differ or are unknown)
  → verdict must be COMPLETE_PASS → E2E evidence for the same main SHA and generated tree (required unless dry-run)
  → CI stage evidence (ci_stage_results.json: same main SHA, required stages PASS — required unless dry-run)
  → remotes agree on production and equal the local ref → production state (LEGACY only with --bootstrap-baseline <that sha>,
  PROVENANCE — inheriting the parent's Bootstrap-Baseline trailers, RESTORED_BASELINE) → blobs →
  temp index → write-tree → commit-tree -p <expected> → fast-forward invariant (new^ == expected, expected is an ancestor) →
  per-remote: pre ls-remote == expected → push (--force-with-lease as a race detector, ff enforced by the parent) → post ls-remote == new
  → local ref updated only after every remote succeeded. A failure on a later remote leaves `partial_push` for `push-sync`.
restore: a new commit whose tree is a previous production commit's tree (no history rewrite). A legacy target is allowed only when
  --bootstrap-baseline names it and the generated production in the history recorded that baseline. Same publish path.
push-sync: fast-forward lagging remotes (and the local ref) to the single descendant; divergence is refused (no retry, no force).
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import tempfile

from . import DEPLOY_REMOTES, GENERATOR_VERSION, PROVENANCE_FILE, REQUIRED_CI_STAGES, RULES_VERSION
from .build import build
from .common import ProdgenError
from .drift import baseline_record, classify_production, first_prodgen_commit, is_ancestor
from .gitstore import GitStore
from .verify import (ENV_DEPENDENT_GATES, MANDATORY_GATES, MUTABLE_GATES, GateReport, GateResult, collect_environment,
                     environment_compatible, report_digest_ok, run_gates)
from .verify.gates_promotion import g18_drift, g20_ancestry_and_remotes, ls_remote

DEFAULT_REF = "refs/heads/production"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _message(title: str, body: str, trailers: dict) -> str:
    lines = [title, "", body, ""]
    lines += [f"{k}: {v}" for k, v in trailers.items()]
    return "\n".join(lines) + "\n"


def _split_remotes(value) -> list:
    if not value:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [v for v in value if v]


def _gate_line(report_dict: dict) -> str:
    return " ".join(f"{g['id']}:{g['status']}" for g in report_dict.get("gates", []))


# ── remote baseline / publish ─────────────────────────────────────────────────────
def remote_baseline(store: GitStore, ref: str, remotes: list) -> dict:
    """Agreeing production SHA across local + remotes. Refuses divergence."""
    local = store.rev_parse(ref) if store.rev_exists(ref) else None
    shas = {}
    errors = {}
    for r in remotes:
        sha, err = ls_remote(store, r, ref)
        if err is not None:
            errors[r] = err
        else:
            shas[r] = sha or None
    if errors:
        raise ProdgenError(f"ls-remote failed: {errors}")
    distinct = set(shas.values())
    if len(distinct) > 1:
        raise ProdgenError(f"remotes disagree on {ref}: {shas} — run `prodgen push-sync` first")
    remote = next(iter(distinct)) if distinct else None
    if remotes and (local or None) != (remote or None):
        raise ProdgenError(f"local {ref}={(local or 'absent')[:12]} != remotes {(remote or 'absent')[:12]} — fetch / push-sync first")
    return {"local": local, "remotes": shas, "expected": remote if remotes else local}


def _publish(store: GitStore, ref: str, new: str, expected: str | None, remotes: list) -> dict:
    """ff-enforced publish to every remote, then the local ref. Returns {done, failed, local_updated}."""
    parents = store.commit_parents(new)
    if expected and parents != [expected]:
        raise ProdgenError(f"fast-forward invariant: {new[:12]}^ = {parents} != expected {expected[:12]}")
    if expected and not is_ancestor(store, expected, new):
        raise ProdgenError(f"fast-forward invariant: expected {expected[:12]} is not an ancestor of {new[:12]}")
    done, failed = [], []
    shared = _shared_push_urls(store, remotes)
    for r in remotes:
        pre, err = ls_remote(store, r, ref)
        if err is None and pre == new:
            # Already holds exactly the new commit: reached through another configured remote's push URL (2026-10-04 P1 —
            # `origin` carries the GitLab URL as a second push URL). Idempotent success, recorded as such; not a failure.
            done.append({"remote": r, "sha": new, "protection": "already at the new commit (reached via a shared push URL)", "shared_push_url": True})
            continue
        if err is not None or (pre or None) != (expected or None):
            failed.append({"remote": r, "stage": "pre-check", "remote_sha": pre, "error": err or "moved since baseline"})
            break
        lease = f"--force-with-lease={ref}:{expected}" if expected else f"--force-with-lease={ref}:"
        proc = subprocess.run(["git", "push", lease, r, f"{new}:{ref}"], cwd=store.repo_root, capture_output=True, text=True)
        if proc.returncode != 0:
            failed.append({"remote": r, "stage": "push", "error": proc.stderr.strip()[-300:]})
            break
        post, err = ls_remote(store, r, ref)
        if err is not None or post != new:
            failed.append({"remote": r, "stage": "post-check", "remote_sha": post, "error": err or "ref is not the pushed commit"})
            break
        done.append({"remote": r, "sha": new, "protection": "accepted by remote"})
    local_updated = False
    if remotes and not failed or not remotes:
        store.update_ref(ref, new, expected)
        local_updated = True
    out = {"done": done, "failed": failed, "local_updated": local_updated}
    if shared:
        out["shared_push_urls"] = shared
    return out


def _shared_push_urls(store: GitStore, remotes: list) -> dict:
    """{url: [remote, …]} for push URLs configured under more than one remote name (informational; such a URL is
    updated by the first remote's push and then found already-at-new by the later one)."""
    seen: dict = {}
    for r in remotes:
        proc = subprocess.run(["git", "remote", "get-url", "--push", "--all", r], cwd=store.repo_root, capture_output=True, text=True)
        for url in (proc.stdout or "").split():
            seen.setdefault(url.rstrip("/"), []).append(r)
    return {u: rs for u, rs in seen.items() if len(rs) > 1}


# ── evidence helpers ──────────────────────────────────────────────────────────────
def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _reuse_report(report_path: str, prov: dict, current_env: dict) -> tuple:
    """(report | None, fatal problems, environment problems). A COMPLETE_PASS report may be reused when: digest ok · verify_mode
    full · binding matches this build. Environment problems (identifiers differ **or are unknown on either side**, 검토 C3) are not
    fatal: the caller re-runs the environment-dependent gates. Mutable gates are always re-run by the caller."""
    rep = _load_json(report_path)
    problems = []
    if not report_digest_ok(rep):
        problems.append("report_sha256 does not match the report body (tampered, mixed up or hand-edited)")
    if rep.get("verdict") != "COMPLETE_PASS":
        problems.append(f"report verdict {rep.get('verdict')} — only COMPLETE_PASS is reusable")
    if rep.get("verify_mode") != "full":
        problems.append(f"report verify_mode {rep.get('verify_mode')} — only full runs are reusable")
    b = rep.get("binding") or {}
    for key in ("main_sha", "tree_hash", "generator_hash", "manifest_sha256"):
        if b.get(key) != prov.get(key):
            problems.append(f"binding {key}: report {str(b.get(key))[:12]} != build {str(prov.get(key))[:12]}")
    _ok_env, env_problems = environment_compatible(rep.get("environment") or {}, current_env)
    return (rep if not problems else None), problems, env_problems


def _check_e2e(evidence: dict, main_sha: str, tree_hash: str | None = None, require_bounded: bool = False) -> list:
    from .evidence import check_evidence
    return check_evidence(evidence, main_sha, tree_hash=tree_hash, require_bounded=require_bounded)


def _check_ci_stages(path: str, main_sha: str, report: dict, require_bounded: bool = False) -> list:
    """ci_stage_results.json (Jenkinsfile_ci post) — the CLI consumes the same stage evidence the CI Promote stage checks (검토 C4).
    require_bounded (2026-10-05): on a deployment that enables Tier 2 (SE_FINALIZER_BOUNDED=true) the bounded Harness stage is required too."""
    try:
        ci = _load_json(path)
    except (OSError, ValueError) as exc:
        return [f"ci stage results unreadable: {exc}"]
    problems = []
    if ci.get("main_sha") != main_sha:
        problems.append(f"ci stage results are for main {str(ci.get('main_sha'))[:12]}, not {main_sha[:12]}")
    stages = ci.get("stages") or {}
    required = REQUIRED_CI_STAGES + (("HARNESS_BOUNDED",) if require_bounded else ())
    bad = [f"{k}={stages.get(k, 'not_run')}" for k in required if stages.get(k) != "PASS"]
    if bad:
        problems.append("required CI stages not PASS: " + ", ".join(bad))
    src = (report or {}).get("source") or {}
    if src.get("kind") == "ci" and src.get("build_url") and ci.get("build_url") and src["build_url"].rstrip("/") != ci["build_url"].rstrip("/"):
        problems.append(f"verify report came from {src['build_url']} but the CI stage results from {ci['build_url']} — mixed builds")
    return problems


def _deploy_policy_problems(remotes: list, dry_run: bool) -> list:
    """A real promotion/restore publishes to exactly the deploy set. Dropping or narrowing remotes is not a way around it (검토 C4)."""
    if dry_run:
        return []
    want, got = set(DEPLOY_REMOTES), set(remotes)
    if got != want:
        return [f"--push-remote must name exactly {','.join(DEPLOY_REMOTES)} for a real promotion (got {','.join(sorted(got)) or 'none'})"]
    return []


# ── promote ───────────────────────────────────────────────────────────────────────
def promote(repo_root: str, sha: str, manifest_path: str, *, dry_run: bool = True, ci_build: str = "",
            production_ref: str = DEFAULT_REF, push_remote="", skip_live: bool = True, netrc: str | None = None,
            verify_report: str | None = None, bootstrap_baseline: str | None = None, e2e_evidence: str | None = None,
            vault_password_file: str | None = None, jenkins_url: str = "https://jenkins-prod.gooddi.lab",
            source: dict | None = None, ci_stage_results: str | None = None, require_bounded: bool = False) -> dict:
    store = GitStore(repo_root)
    main_sha = store.rev_parse(sha)
    remotes = _split_remotes(push_remote)
    result = {"main_sha": main_sha, "dry_run": dry_run, "production_ref": production_ref, "remotes": remotes, "ok": False}
    if skip_live and not dry_run:
        raise ProdgenError("--skip-live is allowed only together with --dry-run (a real promotion needs every mandatory gate)")
    policy = _deploy_policy_problems(remotes, dry_run)
    result["deploy_policy"] = {"required_remotes": list(DEPLOY_REMOTES), "ok": not policy, "problems": policy}
    if policy:
        result["stage"] = "policy"
        result["refused"] = "deploy policy: " + "; ".join(policy)
        return result

    with tempfile.TemporaryDirectory(prefix="prodgen-promote-") as td:
        out = os.path.join(td, "tree")
        report = build(repo_root, main_sha, out, manifest_path, live_checkers=True)
        result["build"] = {"ok": report.ok, "files": report.file_count, "bytes": report.total_bytes,
                           "tree_hash": report.tree_hash,
                           "class_b": [{"path": p, "line": l, "reason": r} for p, l, r in report.class_b]}
        if not report.ok:
            result["stage"] = "build"
            return result
        with open(os.path.join(out, PROVENANCE_FILE), "rb") as fh:
            prov_bytes = fh.read()
        prov = json.loads(prov_bytes.decode("utf-8"))

        # ── gates: reuse a bound COMPLETE_PASS report or run everything; G18/G20 are re-run regardless (mutable state) and the
        #    environment-dependent gates are re-run when the environment identifiers differ or are unknown (검토 C3)
        gates_dict = None
        env_rerun = False
        if verify_report:
            current_env = collect_environment(netrc=netrc, jenkins_url=jenkins_url)
            rep, problems, env_problems = _reuse_report(verify_report, prov, current_env)
            env_rerun = bool(env_problems)
            result["verify_report"] = {"path": verify_report, "reused": rep is not None, "problems": problems,
                                       "environment_problems": env_problems, "environment_rerun": env_rerun, "promote_environment": current_env}
            if rep is None:
                result["stage"] = "verify"
                result["refused"] = "verify report not reusable: " + "; ".join(problems)
                return result
            gates_dict = rep
        if gates_dict is None:
            rep_obj = run_gates(repo_root, out, manifest_path, skip_live=skip_live, netrc=netrc, jenkins_url=jenkins_url,
                                bootstrap_baseline=bootstrap_baseline, production_ref=production_ref, remotes=remotes,
                                vault_password_file=vault_password_file, source=source)
            gates_dict = rep_obj.to_dict()
        else:
            # re-run the mutable gates now (+ the environment-dependent ones when the environment is not verified) and overwrite their results
            from .verify import gates_static
            ctx = gates_static.load_context(repo_root, out, manifest_path)
            ctx["promotion"] = {"production_ref": production_ref, "remotes": remotes, "bootstrap_baseline": bootstrap_baseline,
                                "vault_password_file": vault_password_file, "main_ref": None}
            fresh = {r.id: r for r in (g18_drift(ctx), g20_ancestry_and_remotes(ctx))}
            if env_rerun:
                env_rep = run_gates(repo_root, out, manifest_path, only=",".join(sorted(ENV_DEPENDENT_GATES)), skip_live=skip_live,
                                    netrc=netrc, jenkins_url=jenkins_url, bootstrap_baseline=bootstrap_baseline,
                                    production_ref=production_ref, remotes=remotes, vault_password_file=vault_password_file, source=source)
                for r in env_rep.results:
                    fresh[r.id] = r
            gates = [g for g in gates_dict.get("gates", []) if g["id"] not in fresh]
            gates += [{"id": r.id, "name": r.name, "status": r.status, "partial": r.partial, "seconds": round(r.seconds, 2), "details": r.details, "data": r.data} for r in fresh.values()]
            gates.sort(key=lambda g: g["id"])
            gates_dict = dict(gates_dict, gates=gates)
            statuses = {g["id"]: g["status"] for g in gates}
            missing = [f"{gid}: not run" for gid in MANDATORY_GATES if gid not in statuses] + \
                      [f"{gid}: SKIP" for gid, st in statuses.items() if st == "SKIP" and gid in MANDATORY_GATES] + \
                      [f"{g['id']}: partial" for g in gates if g.get("partial")]
            verdict = "FAIL" if any(st == "FAIL" for st in statuses.values()) else ("PARTIAL" if missing else "COMPLETE_PASS")
            gates_dict.update({"verdict": verdict, "ok": verdict == "COMPLETE_PASS", "mandatory_missing": missing,
                               "gates_rerun": sorted(fresh), "gates_reused": sorted(g["id"] for g in gates if g["id"] not in fresh),
                               "environment_rerun_reason": result["verify_report"]["environment_problems"] if env_rerun else []})
        result["gates"] = {"verdict": gates_dict.get("verdict"), "mandatory_missing": gates_dict.get("mandatory_missing", []),
                           "results": [(g["id"], g["status"]) for g in gates_dict.get("gates", [])]}
        if gates_dict.get("verdict") == "FAIL" or (gates_dict.get("verdict") != "COMPLETE_PASS" and not dry_run):
            result["stage"] = "verify"
            result["gate_details"] = [(g["id"], g["details"][:5]) for g in gates_dict.get("gates", []) if g["status"] == "FAIL"]
            result["refused"] = f"verdict {gates_dict.get('verdict')} — a real promotion needs COMPLETE_PASS"
            return result
        if gates_dict.get("verdict") != "COMPLETE_PASS":
            result["preview_only"] = f"dry-run preview with verdict {gates_dict.get('verdict')} — a real promotion would be refused here"

        # ── E2E evidence (same main SHA, required scenarios PASS) — required for a real promotion
        evidence = None
        if e2e_evidence:
            evidence = _load_json(e2e_evidence)
        elif gates_dict.get("e2e_evidence"):
            evidence = gates_dict["e2e_evidence"]
        e2e_problems = (_check_e2e(evidence, main_sha, prov.get("tree_hash"), require_bounded=require_bounded) if evidence
                        else ["no E2E evidence given (--e2e-evidence or an aggregated report)"])
        result["e2e"] = {"ok": not e2e_problems, "problems": e2e_problems, "require_bounded": require_bounded}
        if e2e_problems and not dry_run:
            result["stage"] = "e2e"
            result["refused"] = "E2E evidence: " + "; ".join(e2e_problems[:5])
            return result

        # ── CI stage evidence (same candidate, required stages PASS) — required for a real promotion (검토 C4)
        ci_problems = (_check_ci_stages(ci_stage_results, main_sha, gates_dict, require_bounded=require_bounded) if ci_stage_results
                       else ["no CI stage results given (--ci-stage-results ci_stage_results.json)"])
        result["ci_stages"] = {"ok": not ci_problems, "problems": ci_problems, "path": ci_stage_results}
        if ci_problems and not dry_run:
            result["stage"] = "ci"
            result["refused"] = "CI stage evidence: " + "; ".join(ci_problems[:5])
            return result
        if ci_stage_results and not ci_build:
            try:
                ci_build = _load_json(ci_stage_results).get("build_url") or ""
            except (OSError, ValueError):
                ci_build = ""

        # ── remote baseline + production state
        base = remote_baseline(store, production_ref, remotes)
        prev = base["expected"]
        result["baseline"] = base
        state = None
        if prev:
            state = classify_production(store, prev, bootstrap_baseline)
            result["production_state"] = {k: state.get(k) for k in ("state", "ok", "reasons", "baseline", "previous_generated")}
            if not state["ok"]:
                result["stage"] = "state"
                result["refused"] = f"production state {state['state']}: " + "; ".join(state.get("reasons", []))
                return result

        # ── objects
        env = store.isolated_object_env(os.path.join(td, "objects")) if dry_run else None
        if dry_run:
            os.makedirs(os.path.join(td, "objects"), exist_ok=True)
        files = []
        for rel, rec in sorted(prov["files"].items()):
            with open(os.path.join(out, *rel.split("/")), "rb") as fh:
                data = fh.read()
            files.append((rec["mode"], store.hash_object(data, write=True, env=env), rel))
        files.append(("100644", store.hash_object(prov_bytes, write=True, env=env), PROVENANCE_FILE))
        tree = store.build_tree(files, write=True, env=env)

    trailers = {
        "Main-SHA": main_sha,
        "Tree-Hash": prov["tree_hash"],
        "Generator-Version": GENERATOR_VERSION,
        "Rules-Version": RULES_VERSION,
        "Previous-Production": prev or "none",
        "CI-Build": ci_build or "manual",
        "Verdict": gates_dict.get("verdict"),
        "Gates": " ".join(f"{g['id']}:{g['status']}" for g in gates_dict.get("gates", [])),
        "Verify-Report-SHA256": gates_dict.get("report_sha256", "n/a"),
        "Generated-At": _now(),
    }
    if state and state["state"] == "LEGACY":
        trailers["Bootstrap-Baseline"] = prev
        trailers["Bootstrap-Baseline-Tree"] = store.commit_tree_sha(prev)      # git tree OID (not provenance.tree_hash)
    elif state and state["state"] == "RESTORED_BASELINE":
        trailers["Bootstrap-Baseline"] = state.get("baseline")
        trailers["Bootstrap-Baseline-Tree"] = store.commit_tree_sha(state["baseline"])
    elif state and state["state"] == "PROVENANCE":
        # baseline inheritance (검토 C2): every generated commit after P1 keeps naming the legacy baseline it descends from, so a
        # restore to B after B → P1 → P2 finds the record on the nearest generated commit as well
        parent_trailers = GitStore.parse_trailers(store.commit_message(prev))
        for key in ("Bootstrap-Baseline", "Bootstrap-Baseline-Tree"):
            if parent_trailers.get(key):
                trailers[key] = parent_trailers[key]
    if gates_dict.get("gates_rerun"):
        trailers["Gates-Rerun"] = " ".join(gates_dict["gates_rerun"])
        trailers["Gates-Reused"] = " ".join(gates_dict.get("gates_reused", []))
    if evidence and evidence.get("evidence_sha256"):
        trailers["E2E-Evidence-SHA256"] = evidence["evidence_sha256"]
    if ci_stage_results:
        trailers["CI-Stages"] = "verified"
    message = _message(f"production: runtime tree from main {main_sha[:12]}",
                       "Generated by prodgen from a fixed main SHA (object store only); comments stripped.\n"
                       f"Verdict {gates_dict.get('verdict')} — gates actually run: {_gate_line(gates_dict)}", trailers)
    result.update({"tree": tree, "parent": prev, "message": message, "files": len(files), "stage": "commit"})
    if dry_run:
        result["ok"] = True
        result["note"] = "dry-run: no objects written, no ref updated, no push"
        return result
    commit = store.commit_tree(tree, [prev] if prev else [], message)
    result["commit"] = commit
    pub = _publish(store, production_ref, commit, prev, remotes)
    result["publish"] = pub
    if pub["failed"]:
        result["stage"] = "publish"
        result["partial_push"] = pub
        result["refused"] = "publish failed on a remote — see partial_push; recover with `prodgen push-sync` after inspecting the remote"
        return result
    result["ok"] = True
    return result


# ── restore ───────────────────────────────────────────────────────────────────────
def restore(repo_root: str, to_commit: str, *, dry_run: bool = True, production_ref: str = DEFAULT_REF,
            push_remote="", bootstrap_baseline: str | None = None) -> dict:
    store = GitStore(repo_root)
    target = store.rev_parse(to_commit)
    target_tree = store.commit_tree_sha(target)
    remotes = _split_remotes(push_remote)
    if remotes and not dry_run:
        policy = _deploy_policy_problems(remotes, dry_run)
        if policy:
            raise ProdgenError("deploy policy: " + "; ".join(policy) + " — a restore that moves one remote leaves the other behind (divergence)")
    base = remote_baseline(store, production_ref, remotes)
    prev = base["expected"]
    result = {"target": target, "target_tree_oid": target_tree, "parent": prev, "dry_run": dry_run,
              "production_ref": production_ref, "remotes": remotes, "baseline": base, "ok": False}
    if prev == target:
        result.update({"ok": True, "note": "production already points at the target"})
        return result
    prov_bytes = store.cat_path(target, PROVENANCE_FILE)
    trailers = {"Restore-Of": target, "Previous-Production": prev or "none", "Generated-At": _now()}
    if prov_bytes is not None:
        prov = json.loads(prov_bytes.decode("utf-8"))
        trailers.update({"Main-SHA": prov.get("main_sha", "unknown"), "Tree-Hash": prov.get("tree_hash", "unknown"),
                         "Generator-Version": prov.get("generator_version", "unknown"), "Rules-Version": prov.get("rules_version", "unknown")})
        body = "Restores a previous generated production tree as a new commit (no history rewrite)."
        result["kind"] = "generated"
    else:
        # legacy target: allowed only as the recorded bootstrap baseline
        if not bootstrap_baseline:
            raise ProdgenError(f"{to_commit} carries no {PROVENANCE_FILE}; a legacy tree is restorable only with --bootstrap-baseline <that sha>")
        bb = store.rev_parse(bootstrap_baseline)
        if bb != target:
            raise ProdgenError(f"--bootstrap-baseline {bootstrap_baseline} does not name the restore target {target[:12]}")
        # the record may be older than the nearest generated commit (B → P1 → P2 → restore(B), 검토 C2): search the whole history
        rec, _rec_prov, _rec_trailers = baseline_record(store, prev, target) if prev else (None, None, None)
        latest, _l_prov, _l_tr = first_prodgen_commit(store, prev) if prev else (None, None, None)
        if rec is None or latest is None:
            raise ProdgenError("the production history has no generated commit that recorded this baseline — refusing an arbitrary legacy restore")
        trailers.update({"Restore-From": latest, "Baseline-Recorded-By": rec, "Bootstrap-Baseline": target, "Bootstrap-Baseline-Tree": target_tree})
        body = "Restores the legacy baseline tree (exact tree OID) as a new commit (no history rewrite) — RESTORED_BASELINE state."
        result["kind"] = "legacy_baseline"
    message = _message(f"production: restore tree of {target[:12]}", body, trailers)
    result["message"] = message
    if dry_run:
        result["ok"] = True
        result["note"] = "dry-run: no ref updated, no push"
        return result
    commit = store.commit_tree(target_tree, [prev] if prev else [], message)
    result["commit"] = commit
    pub = _publish(store, production_ref, commit, prev, remotes)
    result["publish"] = pub
    if not remotes:
        result["warning"] = "no --push-remote: only the local ref moved — the production Job reads the remote; publish with push-sync"
    if pub["failed"]:
        result["stage"] = "publish"
        result["partial_push"] = pub
        return result
    result["ok"] = True
    return result


# ── push-sync ─────────────────────────────────────────────────────────────────────
def push_sync(repo_root: str, production_ref: str = DEFAULT_REF, remotes=(), dry_run: bool = True) -> dict:
    store = GitStore(repo_root)
    remotes = _split_remotes(remotes) if isinstance(remotes, str) else list(remotes)
    if not remotes:
        raise ProdgenError("push-sync needs at least one --remote")
    states = {"local": store.rev_parse(production_ref) if store.rev_exists(production_ref) else None}
    for r in remotes:
        sha, err = ls_remote(store, r, production_ref)
        if err is not None:
            raise ProdgenError(f"ls-remote {r} failed: {err}")
        states[r] = sha or None
        if sha:
            subprocess.run(["git", "fetch", "-q", r, production_ref], cwd=store.repo_root, capture_output=True)
    candidates = [s for s in states.values() if s]
    result = {"before": states, "ref": production_ref, "dry_run": dry_run, "ok": False}
    if not candidates:
        result.update({"ok": True, "note": "no production anywhere"})
        return result
    head = None
    for c in set(candidates):
        if all(c == o or is_ancestor(store, o, c) for o in candidates):
            head = c
            break
    if head is None:
        result["refused"] = f"divergence: no single descendant among {states} — not retrying, not forcing"
        return result
    result["head"] = head
    actions = []
    for r in remotes:
        cur = states[r]
        if cur == head:
            continue
        if dry_run:
            actions.append({"remote": r, "from": cur, "to": head, "dry_run": True})
            continue
        lease = f"--force-with-lease={production_ref}:{cur}" if cur else f"--force-with-lease={production_ref}:"
        proc = subprocess.run(["git", "push", lease, r, f"{head}:{production_ref}"], cwd=store.repo_root, capture_output=True, text=True)
        post, err = ls_remote(store, r, production_ref)
        actions.append({"remote": r, "from": cur, "to": head, "rc": proc.returncode, "post": post,
                        "error": (proc.stderr.strip()[-200:] if proc.returncode != 0 else err)})
        if proc.returncode != 0 or post != head:
            result["actions"] = actions
            result["refused"] = f"push to {r} did not land (rc={proc.returncode}, post={post})"
            return result
    if states["local"] != head and not dry_run:
        store.update_ref(production_ref, head, states["local"])
        actions.append({"local": True, "from": states["local"], "to": head})
    result["actions"] = actions
    result["ok"] = True
    return result
