"""prodgen command line: build | verify | drift-check | promote | restore."""
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
    results = run_gates(repo, args.tree, args.manifest or default_manifest_path(repo),
                        skip_live=args.skip_live, only=args.only, netrc=args.netrc,
                        jenkins_url=args.jenkins_url)
    _emit(results.to_dict(), args.json)
    eprint(results.summary())
    return 0 if results.ok else 1


def cmd_drift(args) -> int:
    from .drift import drift_check
    repo = _repo_root(args)
    res = drift_check(repo, args.production, args.manifest or default_manifest_path(repo))
    _emit(res, args.json)
    return 0 if res.get("ok") else 1


def cmd_promote(args) -> int:
    from .promote import promote
    repo = _repo_root(args)
    res = promote(repo, args.sha, args.manifest or default_manifest_path(repo), dry_run=args.dry_run,
                  ci_build=args.ci_build, production_ref=args.production_ref, push_remote=args.push_remote,
                  skip_live=args.skip_live)
    _emit(res, args.json)
    return 0 if res.get("ok") else 1


def cmd_restore(args) -> int:
    from .promote import restore
    repo = _repo_root(args)
    res = restore(repo, args.to, dry_run=args.dry_run, production_ref=args.production_ref,
                  push_remote=args.push_remote)
    _emit(res, args.json)
    return 0 if res.get("ok") else 1


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

    v = sub.add_parser("verify", help="run gates G01-G17 on a generated tree")
    v.add_argument("--tree", required=True)
    v.add_argument("--skip-live", action="store_true", help="skip WSL / Jenkins / pytest gates")
    v.add_argument("--only", help="comma-separated gate ids to run (e.g. G01,G08)")
    v.add_argument("--netrc", help="netrc file for the Jenkins linter (G13); never printed")
    v.add_argument("--jenkins-url", default="https://jenkins-prod.gooddi.lab")
    v.set_defaults(func=cmd_verify)

    d = sub.add_parser("drift-check", help="compare a production ref with its provenance / a regeneration")
    d.add_argument("--production", required=True, help="ref or SHA of the production commit")
    d.set_defaults(func=cmd_drift)

    p = sub.add_parser("promote", help="build + gates + plumbing commit onto the production ref")
    p.add_argument("--sha", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--ci-build", default="")
    p.add_argument("--production-ref", default="refs/heads/production")
    p.add_argument("--push-remote", default="", help="remote to push the production ref to (not in dry-run)")
    p.add_argument("--skip-live", action="store_true")
    p.set_defaults(func=cmd_promote)

    r = sub.add_parser("restore", help="move production to a previous production commit's tree (new commit, no rewrite)")
    r.add_argument("--to", required=True)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--production-ref", default="refs/heads/production")
    r.add_argument("--push-remote", default="")
    r.set_defaults(func=cmd_restore)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except ProdgenError as exc:
        eprint(f"[prodgen] ERROR: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
