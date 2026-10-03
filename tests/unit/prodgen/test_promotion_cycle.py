"""prodgen promotion cycle B → P1 → R → P2 on a throw-away repo with two bare remotes (2026-10-04, Astra 3차 §7 · §8, 4차 §3).

Covers (none of this touches the real repository's refs or remotes):
  - LEGACY first production: refused without --bootstrap-baseline; accepted only with the exact sha; P1 carries
    Bootstrap-Baseline / Bootstrap-Baseline-Tree (git tree OID) and both remotes == local == P1.
  - restore to the legacy baseline B (only with --bootstrap-baseline B and only because P1 recorded it): R's tree OID == B's,
    classify_production(R) == RESTORED_BASELINE, both remotes moved.
  - re-promotion P2 after R: parent R, baseline B, ancestry checked against P1's main (not B).
  - refusals: arbitrary legacy restore, wrong baseline, non-monotonic candidate, remotes disagreeing, verify PARTIAL, missing E2E evidence,
    --skip-live without --dry-run, race (remote moved between baseline and publish → partial_push, local unchanged).
  - push-sync: lagging remote fast-forwarded; divergence refused.
Live gates (WSL/Jenkins/pytest/G19) are stubbed to PASS so the real G18/G20/state/publish logic is what runs here.
"""
from __future__ import annotations

import json

import pytest

from scripts.ai.prodgen import PROVENANCE_FILE
from scripts.ai.prodgen.common import ProdgenError
from scripts.ai.prodgen.drift import classify_production, drift_check
from scripts.ai.prodgen.evidence import REQUIRED_HARNESS, REQUIRED_MAIN, canonical_digest
from scripts.ai.prodgen.gitstore import GitStore
from scripts.ai.prodgen.promote import _publish, promote, push_sync, remote_baseline, restore
from scripts.ai.prodgen.strip.psstrip import PowerShellParser
from scripts.ai.prodgen.verify import GateResult, gates_live, gates_promotion

from .test_pipeline_tmp_repo import FILES, MANIFEST, _git  # noqa: F401  (same throw-away repository shape)

_needs_ps = pytest.mark.skipif(not PowerShellParser().available, reason="PowerShell 파서 없음 — 생성(build)이 class B 로 막힌다")
PROD = "refs/heads/production"


@pytest.fixture
def world(tmp_path, monkeypatch):
    """repo with main, two bare remotes (origin/internal), a legacy production commit B pushed everywhere."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    for rel, content in FILES.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8"))
    (repo / "production_manifest.yml").write_bytes(MANIFEST.encode("utf-8"))
    _git(repo, "add", "-A")
    _git(repo, "update-index", "--chmod=+x", "app/run.sh")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    for name in ("origin", "internal"):
        bare = tmp_path / f"{name}.git"
        _git(tmp_path, "init", "-q", "--bare", str(bare))
        _git(repo, "remote", "add", name, str(bare))
    # legacy production B: a root commit with a plain file and no provenance — built with plumbing (the worktree stays on main)
    store = GitStore(str(repo))
    blob = store.hash_object(b"legacy production\n", write=True)
    tree = store.build_tree([("100644", blob, "legacy.txt")], write=True)
    B = store.commit_tree(tree, [], "legacy production\n")
    store.update_ref(PROD, B)
    for name in ("origin", "internal"):
        _git(repo, "push", "-q", name, "main", PROD)
    # stub the live gates (WSL / Jenkins / pytest / G19) — G18/G20 and the plumbing stay real
    monkeypatch.setattr(gates_live, "g11_syntax_check", lambda ctx: GateResult("G11", "PASS", ["stub"]))
    monkeypatch.setattr(gates_live, "g12_config_dump", lambda ctx: GateResult("G12", "PASS", ["stub"]))
    monkeypatch.setattr(gates_live, "g13_jenkins_linter", lambda ctx, netrc=None, jenkins_url="": GateResult("G13", "PASS", ["stub"], {"jenkins_version": "stub"}))
    monkeypatch.setattr(gates_live, "g14_tests_overlay", lambda ctx: GateResult("G14", "PASS", ["stub"]))
    monkeypatch.setattr(gates_live, "g15_module_smoke", lambda ctx: GateResult("G15", "PASS", ["stub"]))
    monkeypatch.setattr(gates_promotion, "g19_customer_main_form", lambda ctx: GateResult("G19", "PASS", ["stub"]))
    return {"repo": repo, "store": store, "B": B, "man": str(repo / "production_manifest.yml"), "tmp": tmp_path}


def _evidence(main_sha: str, tmp_path, fail: str | None = None):
    items = []
    for sc in REQUIRED_MAIN:
        items.append({"scenario": sc, "job": "clovirone-cicd/clovirone-server-gather-main", "build": 1, "result": "SUCCESS",
                      "checkout_sha": main_sha, "expected": "SUCCESS", "pass": sc != fail})
    for sc in REQUIRED_HARNESS:
        items.append({"scenario": sc, "job": "clovirone-cicd/clovirone-server-gather-harness", "build": 1, "harness_verdict": "PASS",
                      "checkout_sha": main_sha, "expected": "PASS", "pass": sc != fail})
    ev = {"collected_at": "2026-10-04T00:00:00+00:00", "jenkins_url": "https://x", "items": items}
    ev["evidence_sha256"] = canonical_digest(ev)
    p = tmp_path / f"evidence_{main_sha[:8]}_{fail or 'ok'}.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    return str(p)


def _remote_prod(repo, name):
    out = _git(repo, "ls-remote", name, PROD)
    return out.split()[0] if out else None


@_needs_ps
def test_full_cycle_bootstrap_restore_repromote(world):
    repo, store, B, man = world["repo"], world["store"], world["B"], world["man"]
    X = _git(repo, "rev-parse", "main")
    ev = _evidence(X, world["tmp"])
    # ① legacy without baseline → refused at state (dry-run shows it, real run refuses)
    res = promote(str(repo), X, man, dry_run=False, skip_live=False, push_remote="origin,internal", e2e_evidence=ev)
    assert not res["ok"] and res["stage"] in ("verify", "state"), res
    assert _remote_prod(repo, "origin") == B and store.rev_parse(PROD) == B, "nothing moved"
    # ② wrong baseline → refused
    other = _git(repo, "rev-parse", "main")
    res = promote(str(repo), X, man, dry_run=False, skip_live=False, push_remote="origin,internal", e2e_evidence=ev, bootstrap_baseline=other)
    assert not res["ok"]
    # ③ bootstrap with the exact legacy sha → P1
    res = promote(str(repo), X, man, dry_run=False, skip_live=False, push_remote="origin,internal", e2e_evidence=ev, bootstrap_baseline=B, ci_build="unit")
    assert res["ok"], res
    P1 = store.rev_parse(PROD)
    assert res["commit"] == P1 and store.commit_parents(P1) == [B]
    tr = GitStore.parse_trailers(store.commit_message(P1))
    assert tr["Bootstrap-Baseline"] == B and tr["Bootstrap-Baseline-Tree"] == store.commit_tree_sha(B)
    assert tr["Main-SHA"] == X and tr["Verdict"] == "COMPLETE_PASS" and "G20:PASS" in tr["Gates"] and tr["E2E-Evidence-SHA256"]
    assert _remote_prod(repo, "origin") == P1 and _remote_prod(repo, "internal") == P1
    assert res["publish"]["local_updated"] and len(res["publish"]["done"]) == 2
    assert classify_production(store, P1)["state"] == "PROVENANCE"
    # ④ arbitrary legacy restore refused; restore to B only with --bootstrap-baseline B → R
    with pytest.raises(ProdgenError):
        restore(str(repo), B, dry_run=False, push_remote="origin,internal")
    with pytest.raises(ProdgenError):
        restore(str(repo), B, dry_run=False, push_remote="origin,internal", bootstrap_baseline=X)
    done = restore(str(repo), B, dry_run=False, push_remote="origin,internal", bootstrap_baseline=B)
    assert done["ok"] and done["kind"] == "legacy_baseline"
    R = store.rev_parse(PROD)
    assert store.commit_tree_sha(R) == store.commit_tree_sha(B) and store.commit_parents(R) == [P1]
    rt = GitStore.parse_trailers(store.commit_message(R))
    assert rt["Restore-Of"] == B and rt["Restore-From"] == P1 and rt["Bootstrap-Baseline"] == B
    st = classify_production(store, R)
    assert st["state"] == "RESTORED_BASELINE" and st["ok"] and st["previous_generated"] == P1 and st["previous_generated_main_sha"] == X
    assert _remote_prod(repo, "origin") == R and _remote_prod(repo, "internal") == R
    d = drift_check(str(repo), PROD, man)
    assert d["mode"] == "RESTORED_BASELINE" and d["ok"]
    # ⑤ re-promotion P2 from a descendant of X: parent R, no bootstrap flag needed
    (repo / "cfg.ini").write_bytes(b"[defaults]\nforks = 7\n")
    _git(repo, "commit", "-qam", "forks")
    X2 = _git(repo, "rev-parse", "main")
    res2 = promote(str(repo), X2, man, dry_run=False, skip_live=False, push_remote="origin,internal", e2e_evidence=_evidence(X2, world["tmp"]))
    assert res2["ok"], res2
    P2 = store.rev_parse(PROD)
    assert store.commit_parents(P2) == [R] and GitStore.parse_trailers(store.commit_message(P2))["Bootstrap-Baseline"] == B
    assert _remote_prod(repo, "origin") == P2 == _remote_prod(repo, "internal")
    # ⑥ non-monotonic candidate (a commit beside main that does not descend from X2) → G20 FAIL → refused
    side = store.commit_tree(store.commit_tree_sha(X), [X], "side\n")
    res3 = promote(str(repo), side, man, dry_run=False, skip_live=False, push_remote="origin,internal", e2e_evidence=_evidence(side, world["tmp"]))
    assert not res3["ok"] and res3["stage"] == "verify" and any(gid == "G20" for gid, _ in res3["gate_details"]), res3
    assert store.rev_parse(PROD) == P2, "refusal moves nothing"


@_needs_ps
def test_refusals_evidence_skiplive_remotes_and_race(world):
    repo, store, B, man = world["repo"], world["store"], world["B"], world["man"]
    X = _git(repo, "rev-parse", "main")
    # --skip-live only with --dry-run
    with pytest.raises(ProdgenError):
        promote(str(repo), X, man, dry_run=False, skip_live=True, push_remote="origin,internal", bootstrap_baseline=B)
    # dry-run preview with PARTIAL gates is allowed (shows the commit) but says so
    pre = promote(str(repo), X, man, dry_run=True, skip_live=True, push_remote="origin,internal", bootstrap_baseline=B)
    assert pre["ok"] and pre["gates"]["verdict"] == "PARTIAL" and "preview_only" in pre and "commit" not in pre
    assert store.rev_parse(PROD) == B
    # missing E2E evidence → refused (real run)
    res = promote(str(repo), X, man, dry_run=False, skip_live=False, push_remote="origin,internal", bootstrap_baseline=B)
    assert not res["ok"] and res["stage"] == "e2e", res
    # a failing required scenario → refused
    bad = _evidence(X, world["tmp"], fail="S3")
    res = promote(str(repo), X, man, dry_run=False, skip_live=False, push_remote="origin,internal", bootstrap_baseline=B, e2e_evidence=bad)
    assert not res["ok"] and res["stage"] == "e2e" and any("S3" in p for p in res["e2e"]["problems"]), res
    # evidence for another SHA → refused
    other_ev = _evidence("0" * 40, world["tmp"])
    res = promote(str(repo), X, man, dry_run=False, skip_live=False, push_remote="origin,internal", bootstrap_baseline=B, e2e_evidence=other_ev)
    assert not res["ok"] and res["stage"] == "e2e", res
    assert store.rev_parse(PROD) == B and _remote_prod(repo, "origin") == B, "refusals change no ref"
    # remotes disagree → refused before any object is written
    moved = store.commit_tree(store.build_tree([("100644", store.hash_object(b"moved\\n", write=True), "legacy.txt")], write=True), [B], "moved on internal\n")
    _git(repo, "push", "-q", "internal", f"{moved}:{PROD}")
    ok_ev = _evidence(X, world["tmp"])
    res = promote(str(repo), X, man, dry_run=False, skip_live=False, push_remote="origin,internal", bootstrap_baseline=B, e2e_evidence=ok_ev)
    assert not res["ok"], res
    with pytest.raises(ProdgenError):
        remote_baseline(store, PROD, ["origin", "internal"])
    # push-sync: origin=B, internal=moved(B+1) → fast-forward origin and the local ref to moved (no force)
    sync = push_sync(str(repo), PROD, ["origin", "internal"], dry_run=False)
    assert sync["ok"] and _remote_prod(repo, "origin") == moved == _remote_prod(repo, "internal") == store.rev_parse(PROD)
    # race: baseline computed (expected=moved), origin moves before publish → pre-check fails, nothing moved locally
    expected = store.rev_parse(PROD)
    raced = store.commit_tree(store.build_tree([("100644", store.hash_object(b"raced\\n", write=True), "legacy.txt")], write=True), [expected], "raced\n")
    _git(repo, "push", "-q", "origin", f"{raced}:{PROD}")
    new = store.commit_tree(store.commit_tree_sha(expected), [expected], "candidate\n\nX: y\n")
    pub = _publish(store, PROD, new, expected, ["origin", "internal"])
    assert pub["failed"] and pub["failed"][0]["remote"] == "origin" and pub["failed"][0]["stage"] == "pre-check"
    assert not pub["local_updated"] and store.rev_parse(PROD) == expected
    # true divergence: internal gets a *different* child of moved → no single descendant → push-sync refuses, no force
    other = store.commit_tree(store.build_tree([("100644", store.hash_object(b"other\\n", write=True), "legacy.txt")], write=True), [expected], "other on internal\n")
    _git(repo, "push", "-q", "internal", f"{other}:{PROD}")
    div = push_sync(str(repo), PROD, ["origin", "internal"], dry_run=False)
    assert not div["ok"] and "divergence" in div["refused"]
    assert _remote_prod(repo, "origin") == raced and _remote_prod(repo, "internal") == other, "refusal moves nothing"


def test_legacy_state_and_drift_without_bootstrap(world):
    repo, store, B, man = world["repo"], world["store"], world["B"], world["man"]
    st = classify_production(store, B)
    assert st["state"] == "LEGACY" and not st["ok"]
    assert classify_production(store, B, bootstrap_baseline=B)["ok"]
    assert not classify_production(store, B, bootstrap_baseline=_git(repo, "rev-parse", "main"))["ok"]
    d = drift_check(str(repo), PROD, man)
    assert d["mode"] == "LEGACY" and not d["ok"], "legacy is never ok by default (3차 §7)"
    assert drift_check(str(repo), PROD, man, bootstrap_baseline=B)["ok"]


def test_fake_restore_trailer_is_not_a_restored_baseline(world):
    """A trailer alone must not pass: tree OID must equal the baseline's and a generated P1 must have recorded it."""
    repo, store, B = world["repo"], world["store"], world["B"]
    fake = store.commit_tree(store.commit_tree_sha(_git(repo, "rev-parse", "main")), [B],
                             f"fake\n\nRestore-Of: {B}\nBootstrap-Baseline: {B}\n")
    st = classify_production(store, fake)
    assert st["state"] == "UNVERIFIED" and not st["ok"] and any("tree OID" in r for r in st["reasons"])
