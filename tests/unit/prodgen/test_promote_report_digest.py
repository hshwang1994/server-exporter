"""prodgen promote — a reused verify report is re-digested after the mutable gates run again (2026-10-10 PG-01).

The trailer `Verify-Report-SHA256` names the report the promotion used. When a COMPLETE_PASS report is reused, G18/G20 (and the
environment-dependent gates when the environment is not verified) are re-run and merged into the report body — the digest in the
trailer must describe that merged body, not the file that was handed in (its digest describes a body that no longer exists)."""
from __future__ import annotations

import json

import pytest

from scripts.ai.prodgen import DEPLOY_REMOTES
from scripts.ai.prodgen.build import build
from scripts.ai.prodgen.gitstore import GitStore
from scripts.ai.prodgen.promote import promote
from scripts.ai.prodgen.strip.psstrip import PowerShellParser
from scripts.ai.prodgen.verify import canonical_digest, report_digest_ok, run_gates

from .test_promotion_cycle import BOTH, PROD, _ci, _evidence, _git, world  # noqa: F401

_needs_ps = pytest.mark.skipif(not PowerShellParser().available, reason="PowerShell 파서 없음 — 생성(build)이 class B 로 막힌다")


@_needs_ps
def test_reused_report_digest_in_trailer_is_recomputed_over_the_merged_report(world):
    repo, store, B = world["repo"], world["store"], world["B"]
    X = _git(repo, "rev-parse", "main")
    tree = world["tmp"] / "tree_report"
    assert build(str(repo), X, str(tree), world["man"], live_checkers=True).ok
    report = run_gates(str(repo), str(tree), world["man"], skip_live=False, bootstrap_baseline=B, production_ref=PROD, remotes=list(DEPLOY_REMOTES))
    assert report.verdict == "COMPLETE_PASS", report.summary()
    rep_path = world["tmp"] / "verify_report.json"
    payload = report.to_dict()
    rep_path.write_text(json.dumps(payload), encoding="utf-8")
    assert report_digest_ok(payload)

    res = promote(str(repo), X, world["man"], dry_run=False, skip_live=False, push_remote=BOTH, bootstrap_baseline=B,
                  verify_report=str(rep_path), e2e_evidence=_evidence(X, world), ci_stage_results=_ci(X, world))
    assert res["ok"], res
    vr = res["verify_report"]
    assert vr["reused"] and vr["report_sha256_file"] == payload["report_sha256"]
    msg = store.commit_message(res["commit"])
    trailers = GitStore.parse_trailers(msg)
    assert trailers["Gates-Rerun"], "G18/G20 are always re-run on a reused report"
    assert trailers["Verify-Report-SHA256"] == vr["report_sha256_used"]
    assert vr["report_sha256_used"] != payload["report_sha256"], "the merged body differs from the handed-in file, so must its digest"


def test_canonical_digest_is_order_independent_and_excludes_itself():
    a = {"gates": [{"id": "G01", "status": "PASS"}], "verdict": "COMPLETE_PASS"}
    b = {"verdict": "COMPLETE_PASS", "gates": [{"status": "PASS", "id": "G01"}]}
    assert canonical_digest(a) == canonical_digest(b)
    a2 = dict(a, report_sha256=canonical_digest(a))
    assert report_digest_ok(a2)
