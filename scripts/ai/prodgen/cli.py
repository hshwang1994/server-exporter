"""prodgen command line: build | verify | drift-check | promote | restore | push-sync | e2e-evidence | evidence-aggregate.

CLI grammar fixed 2026-10-04 (Astra 3차 §7): bootstrap is always the value-taking `--bootstrap-baseline <sha>` on verify,
drift-check, promote and restore. There is no bare `--bootstrap`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .common import ProdgenError, eprint
from .manifest import default_manifest_path


def _repo_root(args) -> str:
    return os.path.abspath(args.repo or os.getcwd())


def cmd_build(args) -> int:
    from .build import build
    repo = _repo_root(args)
    report = build(repo, args.sha, args.out, args.manifest or default_manifest_path(repo),
                   live_checkers=not args.no_live_checkers)
    _emit(report.to_dict(), args.json)
    if not report.ok:
        eprint(f"[prodgen build] FAILED — class B remaining: {len(report.class_b)}, "
               f"classification errors: {len(report.classification.get('errors', []))}")
        return 1
    eprint(f"[prodgen build] OK — {report.file_count} files, {report.total_bytes} bytes, tree_hash={report.tree_hash}")
    return 0


def cmd_verify(args) -> int:
    from .verify import run_gates
    repo = _repo_root(args)
    source = {"kind": "ci", "build_url": args.source_build_url} if args.source_build_url else None
    results = run_gates(repo, args.tree, args.manifest or default_manifest_path(repo),
                        skip_live=args.skip_live, only=args.only, netrc=args.netrc, jenkins_url=args.jenkins_url,
                        bootstrap_baseline=args.bootstrap_baseline, production_ref=args.production_ref,
                        remotes=args.remote or [], vault_password_file=args.vault_password_file, source=source)
    payload = results.to_dict()
    if args.report_out:
        with open(args.report_out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
        with open(args.report_out + ".sha256", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload["report_sha256"] + "\n")
    _emit(payload, args.json)
    eprint(results.summary())
    return {"COMPLETE_PASS": 0, "PARTIAL": 2, "FAIL": 1}[results.verdict]


def cmd_drift(args) -> int:
    from .drift import drift_check
    repo = _repo_root(args)
    res = drift_check(repo, args.production, args.manifest or default_manifest_path(repo), bootstrap_baseline=args.bootstrap_baseline)
    _emit(res, args.json)
    return 0 if res.get("ok") else 1


def cmd_promote(args) -> int:
    from .promote import promote
    repo = _repo_root(args)
    source = {"kind": "ci", "build_url": args.source_build_url} if args.source_build_url else None
    res = promote(repo, args.sha, args.manifest or default_manifest_path(repo), dry_run=args.dry_run,
                  ci_build=args.ci_build, production_ref=args.production_ref, push_remote=args.push_remote,
                  skip_live=args.skip_live, netrc=args.netrc, verify_report=args.verify_report,
                  bootstrap_baseline=args.bootstrap_baseline, e2e_evidence=args.e2e_evidence,
                  vault_password_file=args.vault_password_file, jenkins_url=args.jenkins_url, source=source,
                  ci_stage_results=args.ci_stage_results, require_bounded=args.require_bounded)
    _emit(res, args.json)
    if not res.get("ok"):
        eprint(f"[prodgen promote] REFUSED at stage {res.get('stage')}: {res.get('refused', '')}")
    return 0 if res.get("ok") else 1


def cmd_restore(args) -> int:
    from .promote import restore
    repo = _repo_root(args)
    res = restore(repo, args.to, dry_run=args.dry_run, production_ref=args.production_ref,
                  push_remote=args.push_remote, bootstrap_baseline=args.bootstrap_baseline)
    _emit(res, args.json)
    return 0 if res.get("ok") else 1


def cmd_push_sync(args) -> int:
    from .promote import push_sync
    repo = _repo_root(args)
    res = push_sync(repo, args.production_ref, args.remote or [], dry_run=args.dry_run)
    _emit(res, args.json)
    return 0 if res.get("ok") else 1


def cmd_e2e_evidence(args) -> int:
    from .evidence import collect, load_tip_observations
    res = collect(args.jenkins_url, args.netrc, args.entry or [], tip_observations=load_tip_observations(args.tip_observations),
                  repo_root=args.repo or None)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, sort_keys=True)
    _emit({"items": len(res["items"]), "passed": sum(1 for i in res["items"] if i.get("pass")), "out": args.out,
           "evidence_sha256": res["evidence_sha256"]}, args.json)
    return 0


def cmd_evidence_aggregate(args) -> int:
    from .evidence import aggregate
    res = aggregate(args.report, args.evidence or [], args.out)
    _emit(res, args.json)
    return 0


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True, default=str))
    else:
        print(json.dumps(payload, indent=1, ensure_ascii=False, default=str))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="prodgen", description="production tree generator (runtime-only, comment-stripped)")
    ap.add_argument("--repo", help="repository root (default: cwd)")
    ap.add_argument("--manifest", help="path to production_manifest.yml")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="generate the tree from a fixed SHA")
    b.add_argument("--sha", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--no-live-checkers", action="store_true", help="skip bash -n / PowerShell parser (PowerShell comments become class B)")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("verify", help="run gates G01-G20 on a generated tree (exit 0 COMPLETE_PASS · 2 PARTIAL · 1 FAIL)")
    v.add_argument("--tree", required=True)
    v.add_argument("--skip-live", action="store_true", help="skip WSL / Jenkins / pytest / G19 gates (verdict becomes PARTIAL)")
    v.add_argument("--only", help="comma-separated gate ids to run (verdict becomes PARTIAL)")
    v.add_argument("--netrc", help="netrc file for the Jenkins linter (G13); never printed")
    v.add_argument("--jenkins-url", default="https://jenkins-prod.gooddi.lab")
    v.add_argument("--bootstrap-baseline", help="legacy production SHA accepted as the first-promotion baseline (G18/G20)")
    v.add_argument("--production-ref", default="refs/heads/production")
    v.add_argument("--remote", action="append", help="push remote to compare production with (repeatable, e.g. origin internal)")
    v.add_argument("--vault-password-file", help="vault password file for G19 (kept outside the clone, never printed)")
    v.add_argument("--report-out", help="write the report JSON (+ .sha256 sidecar) here")
    v.add_argument("--source-build-url", default="", help="CI build URL that produced this report (provenance of execution)")
    v.set_defaults(func=cmd_verify)

    d = sub.add_parser("drift-check", help="compare a production ref with its provenance / classify its state")
    d.add_argument("--production", required=True, help="ref or SHA of the production commit")
    d.add_argument("--bootstrap-baseline", help="legacy production SHA accepted as the first-promotion baseline")
    d.set_defaults(func=cmd_drift)

    p = sub.add_parser("promote", help="build + gates + evidence + plumbing commit onto the production ref + ff publish")
    p.add_argument("--sha", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--ci-build", default="")
    p.add_argument("--production-ref", default="refs/heads/production")
    p.add_argument("--push-remote", default="", help="remotes to publish to — a real promotion needs exactly origin,internal (deploy policy); ignored in dry-run")
    p.add_argument("--skip-live", action="store_true", help="only together with --dry-run")
    p.add_argument("--netrc", help="netrc file for the Jenkins linter (G13)")
    p.add_argument("--verify-report", help="reuse a COMPLETE_PASS report (binding + environment must match; G18/G20 re-run)")
    p.add_argument("--bootstrap-baseline", help="legacy production SHA for the first promotion")
    p.add_argument("--e2e-evidence", help="e2e evidence JSON (prodgen e2e-evidence) — required for a real promotion")
    p.add_argument("--ci-stage-results", help="ci_stage_results.json of the CI build for this SHA (required stages PASS) — required for a real promotion")
    p.add_argument("--vault-password-file", help="vault password file for G19")
    p.add_argument("--require-bounded", action="store_true",
                   help="require the Tier 2 bounded Harness group and CI stage HARNESS_BOUNDED — for deployments that run with "
                        "SE_FINALIZER_BOUNDED=true (the internal Jenkins since 2026-10-05); customer installs keep it off by default")
    p.add_argument("--jenkins-url", default="https://jenkins-prod.gooddi.lab")
    p.add_argument("--source-build-url", default="")
    p.set_defaults(func=cmd_promote)

    r = sub.add_parser("restore", help="move production to a previous production commit's tree (new commit, no rewrite)")
    r.add_argument("--to", required=True)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--production-ref", default="refs/heads/production")
    r.add_argument("--push-remote", default="", help="comma-separated remotes (e.g. origin,internal)")
    r.add_argument("--bootstrap-baseline", help="required when --to is the legacy baseline (must equal --to)")
    r.set_defaults(func=cmd_restore)

    s = sub.add_parser("push-sync", help="fast-forward lagging remotes and the local ref to the single descendant; divergence refused")
    s.add_argument("--production-ref", default="refs/heads/production")
    s.add_argument("--remote", action="append", required=True)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_push_sync)

    e = sub.add_parser("e2e-evidence", help="collect scenario evidence from Jenkins builds (read-only)")
    e.add_argument("--jenkins-url", default="https://jenkins-prod.gooddi.lab")
    e.add_argument("--netrc", required=True)
    e.add_argument("--entry", action="append", help="SCENARIO=job/path:build[:EXPECTED_RESULT] (repeatable)")
    e.add_argument("--tip-observations", help="JSON of trigger-side tip observations (direct binding for fail-closed builds; §5)")
    e.add_argument("--out", required=True)
    e.set_defaults(func=cmd_e2e_evidence)

    g = sub.add_parser("evidence-aggregate", help="merge e2e evidence into a verify report and recompute its digest")
    g.add_argument("--report", required=True)
    g.add_argument("--evidence", action="append", help="evidence JSON (repeatable)")
    g.add_argument("--out", required=True)
    g.set_defaults(func=cmd_evidence_aggregate)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except ProdgenError as exc:
        eprint(f"[prodgen] ERROR: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
