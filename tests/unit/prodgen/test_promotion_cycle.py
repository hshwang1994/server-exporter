"""prodgen promotion cycle B → P1 → R → P2 (and B → P1 → P2 → R → P3) on a throw-away repo with two bare remotes
(2026-10-04, Astra 3차 §7 · §8, 4차 §3, 검토 C2 · C4).

Covers (none of this touches the real repository's refs or remotes):
  - LEGACY first production: refused without --bootstrap-baseline; accepted only with the exact sha; P1 carries
    Bootstrap-Baseline / Bootstrap-Baseline-Tree (git tree OID) and both remotes == local == P1.
  - restore to the legacy baseline B (only with --bootstrap-baseline B and only because a generated commit recorded it): R's tree
    OID == B's, classify_production(R) == RESTORED_BASELINE, both remotes moved.
  - re-promotion P2 after R: parent R, baseline B, ancestry checked against the latest generated main (not B).
  - C2: B → P1 → P2 (normal promotion, baseline inherited) → restore(B) found through the history → P3 with parent R.
  - C4: deploy policy — a real promotion/restore with fewer or other remotes is refused before anything is written; CI stage
    evidence (ci_stage_results.json) for the same SHA with every required stage PASS is a precondition; G20 without remotes is PARTIAL.
  - refusals: arbitrary legacy restore, wrong baseline, non-monotonic candidate, remotes disagreeing, verify PARTIAL, missing /
    failing / foreign-SHA / missing-tree E2E evidence, --skip-live without --dry-run, race (remote moved between baseline and
    publish → partial_push, local unchanged).
  - push-sync: lagging remote fast-forwarded; divergence refused.
  - remote target refs (2026-11-02, 사용자 결정): GitHub `origin` carries production on refs/heads/production next to its
    development main; the customer-form GitLab `internal` carries it on refs/heads/main, its only branch. promote/restore/push-sync
    keep that layout, and a push URL shared by the two remotes is refused before anything is written.
Live gates (WSL/Jenkins/pytest/G19) are stubbed to PASS so the real G18/G20/state/publish logic is what runs here.
"""
from __future__ import annotations

import json

import pytest

from scripts.ai.prodgen import DEPLOY_REMOTES, DEPLOY_TARGET_REFS, PROVENANCE_FILE, REQUIRED_CI_STAGES, remote_ref
from scripts.ai.prodgen.build import build
from scripts.ai.prodgen.common import ProdgenError
from scripts.ai.prodgen.drift import baseline_record, classify_production, drift_check
from scripts.ai.prodgen.evidence import REQUIRED_HARNESS, REQUIRED_HARNESS_TREE, REQUIRED_MAIN, canonical_digest
from scripts.ai.prodgen.gitstore import GitStore
from scripts.ai.prodgen.promote import _publish, _repo_key, promote, push_sync, remote_baseline, restore
from scripts.ai.prodgen.strip.psstrip import PowerShellParser
from scripts.ai.prodgen.verify import GateResult, gates_live, gates_promotion, run_gates

from .test_pipeline_tmp_repo import FILES, MANIFEST, _git, _make_run_sh_executable  # noqa: F401  (same throw-away repository shape)

_needs_ps = pytest.mark.skipif(not PowerShellParser().available, reason="PowerShell 파서 없음 — 생성(build)이 class B 로 막힌다")
PROD = "refs/heads/production"
BOTH = ",".join(DEPLOY_REMOTES)
# remote → the ref it carries production on (2026-11-02, 사용자 결정) — written out here so the test pins the contract
TARGET = {"origin": PROD, "internal": "refs/heads/main"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """repo with main, two bare remotes and a legacy production commit B: origin (GitHub form — development main +
    production B) and internal (customer-form GitLab — its only branch main = B)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    for rel, content in FILES.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8"))
    (repo / "production_manifest.yml").write_bytes(MANIFEST.encode("utf-8"))
    _make_run_sh_executable(repo)          # 2026-10-28 (CI G2): 디스크 실행 비트 — fileMode=true 에서 commit -a 가 644 로 되돌리지 않게
    _git(repo, "add", "-A")
    _git(repo, "update-index", "--chmod=+x", "app/run.sh")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    for name in DEPLOY_REMOTES:
        bare = tmp_path / f"{name}.git"
        _git(tmp_path, "init", "-q", "--bare", str(bare))
        _git(repo, "remote", "add", name, str(bare))
    # legacy production B: a root commit with a plain file and no provenance — built with plumbing (the worktree stays on main)
    store = GitStore(str(repo))
    blob = store.hash_object(b"legacy production\n", write=True)
    tree = store.build_tree([("100644", blob, "legacy.txt")], write=True)
    B = store.commit_tree(tree, [], "legacy production\n")
    store.update_ref(PROD, B)
    _git(repo, "push", "-q", "origin", "main", PROD)                       # GitHub: development main + production
    _git(repo, "push", "-q", "internal", f"{B}:{TARGET['internal']}")      # customer-form GitLab: only main (= production)
    # stub the live gates (WSL / Jenkins / pytest / G19) — G18/G20 and the plumbing stay real
    monkeypatch.setattr(gates_live, "g11_syntax_check", lambda ctx: GateResult("G11", "PASS", ["stub"]))
    monkeypatch.setattr(gates_live, "g12_config_dump", lambda ctx: GateResult("G12", "PASS", ["stub"]))
    monkeypatch.setattr(gates_live, "g13_jenkins_linter", lambda ctx, netrc=None, jenkins_url="": GateResult("G13", "PASS", ["stub"], {"jenkins_version": "stub"}))
    monkeypatch.setattr(gates_live, "g14_tests_overlay", lambda ctx: GateResult("G14", "PASS", ["stub"]))
    monkeypatch.setattr(gates_live, "g15_module_smoke", lambda ctx: GateResult("G15", "PASS", ["stub"]))
    monkeypatch.setattr(gates_promotion, "g19_customer_main_form", lambda ctx: GateResult("G19", "PASS", ["stub"]))
    return {"repo": repo, "store": store, "B": B, "man": str(repo / "production_manifest.yml"), "tmp": tmp_path}


def _tree_hash(world, sha: str) -> str:
    out = world["tmp"] / f"tree_{sha[:8]}"
    if not out.exists():
        rep = build(str(world["repo"]), sha, str(out), world["man"], live_checkers=True)
        assert rep.ok, rep.class_b
    with open(out / PROVENANCE_FILE, encoding="utf-8") as fh:
        return json.load(fh)["tree_hash"]


def _evidence(main_sha: str, world, fail: str | None = None, tree_hash: str | None = None, tree_items: bool = True):
    tree_hash = tree_hash or _tree_hash(world, main_sha)
    items = []
    for sc in REQUIRED_MAIN:
        items.append({"scenario": sc, "kind": "main", "job": "clovirone-cicd/clovirone-server-gather-main", "build": 1, "result": "SUCCESS",
                      "checkout_sha": main_sha, "checks": [{"name": "contract", "ok": True}], "pass": sc != fail})
    for sc in REQUIRED_HARNESS:
        items.append({"scenario": sc, "kind": "harness", "job": "clovirone-cicd/clovirone-server-gather-harness", "build": 1, "harness_verdict": "PASS",
                      "checkout_sha": main_sha, "functions_src": "checkout", "functions_sha256": "f" * 64, "checks": [{"name": "verdict", "ok": True}],
                      "pass": sc != fail})
    if tree_items:
        for sc in REQUIRED_HARNESS_TREE:
            items.append({"scenario": sc, "kind": "harness", "job": "clovirone-cicd/clovirone-server-gather-harness", "build": 2, "harness_verdict": "PASS",
                          "checkout_sha": main_sha, "functions_src": "artifact", "source_sha256": "a" * 64, "provenance_tree_hash": tree_hash,
                          "checks": [{"name": "verdict", "ok": True}], "pass": sc != fail})
    ev = {"collected_at": "2026-10-04T00:00:00+00:00", "jenkins_url": "https://x", "items": items}
    ev["evidence_sha256"] = canonical_digest(ev)
    p = world["tmp"] / f"evidence_{main_sha[:8]}_{fail or 'ok'}_{tree_hash[:8] if tree_items else 'notree'}.json"
    p.write_text(json.dumps(ev), encoding="utf-8")
    return str(p)


def _ci(main_sha: str, world, bad: str | None = None, build_url: str = "https://jenkins.invalid/job/ci/9/"):
    stages = {k: ("FAIL" if k == bad else "PASS") for k in REQUIRED_CI_STAGES}
    stages["PROMOTE"] = "not_run"
    p = world["tmp"] / f"ci_{main_sha[:8]}_{bad or 'ok'}.json"
    p.write_text(json.dumps({"main_sha": main_sha, "build_url": build_url, "result": "SUCCESS", "stages": stages}), encoding="utf-8")
    return str(p)


def _remote_prod(repo, name):
    """production as `name` carries it — on its own target ref (GitHub production · customer-form GitLab main)."""
    out = _git(repo, "ls-remote", name, TARGET[name])
    return out.split()[0] if out else None


def _branches(repo, name):
    """{branch ref: sha} of every branch on `name` — the customer-form check (GitLab has nothing but main)."""
    out = _git(repo, "ls-remote", name)
    return {ref: sha for sha, ref in (line.split() for line in out.splitlines() if line.strip()) if ref.startswith("refs/heads/")}


def _promote(world, sha, **kw):
    kw.setdefault("dry_run", False)
    kw.setdefault("skip_live", False)
    kw.setdefault("push_remote", BOTH)
    if "e2e_evidence" not in kw:          # not setdefault: the default must not be built (and its file written) when a caller passes one
        kw["e2e_evidence"] = _evidence(sha, world)
    if "ci_stage_results" not in kw:
        kw["ci_stage_results"] = _ci(sha, world)
    return promote(str(world["repo"]), sha, world["man"], **kw)


@_needs_ps
def test_full_cycle_bootstrap_restore_repromote(world):
    repo, store, B, man = world["repo"], world["store"], world["B"], world["man"]
    X = _git(repo, "rev-parse", "main")
    # ① legacy without baseline → refused at state (dry-run shows it, real run refuses)
    res = _promote(world, X)
    assert not res["ok"] and res["stage"] in ("verify", "state"), res
    assert _remote_prod(repo, "origin") == B and store.rev_parse(PROD) == B, "nothing moved"
    # ② wrong baseline → refused
    res = _promote(world, X, bootstrap_baseline=X)
    assert not res["ok"]
    # ③ bootstrap with the exact legacy sha → P1
    res = _promote(world, X, bootstrap_baseline=B, ci_build="unit")
    assert res["ok"], res
    P1 = store.rev_parse(PROD)
    assert res["commit"] == P1 and store.commit_parents(P1) == [B]
    tr = GitStore.parse_trailers(store.commit_message(P1))
    assert tr["Bootstrap-Baseline"] == B and tr["Bootstrap-Baseline-Tree"] == store.commit_tree_sha(B)
    assert tr["Main-SHA"] == X and tr["Verdict"] == "COMPLETE_PASS" and "G20:PASS" in tr["Gates"] and tr["E2E-Evidence-SHA256"]
    assert tr["CI-Stages"] == "verified"
    assert _remote_prod(repo, "origin") == P1 and _remote_prod(repo, "internal") == P1
    assert res["publish"]["local_updated"] and len(res["publish"]["done"]) == 2
    assert res["remote_refs"] == TARGET and [d["ref"] for d in res["publish"]["done"]] == [TARGET["origin"], TARGET["internal"]]
    assert _branches(repo, "internal") == {TARGET["internal"]: P1}, "customer-form GitLab: only main, carrying production"
    assert _branches(repo, "origin") == {"refs/heads/main": X, PROD: P1}, "GitHub keeps its development main next to production"
    assert classify_production(store, P1)["state"] == "PROVENANCE"
    # ④ arbitrary legacy restore refused; restore to B only with --bootstrap-baseline B → R
    with pytest.raises(ProdgenError):
        restore(str(repo), B, dry_run=False, push_remote=BOTH)
    with pytest.raises(ProdgenError):
        restore(str(repo), B, dry_run=False, push_remote=BOTH, bootstrap_baseline=X)
    done = restore(str(repo), B, dry_run=False, push_remote=BOTH, bootstrap_baseline=B)
    assert done["ok"] and done["kind"] == "legacy_baseline"
    R = store.rev_parse(PROD)
    assert store.commit_tree_sha(R) == store.commit_tree_sha(B) and store.commit_parents(R) == [P1]
    rt = GitStore.parse_trailers(store.commit_message(R))
    assert rt["Restore-Of"] == B and rt["Restore-From"] == P1 and rt["Baseline-Recorded-By"] == P1 and rt["Bootstrap-Baseline"] == B
    st = classify_production(store, R)
    assert st["state"] == "RESTORED_BASELINE" and st["ok"] and st["previous_generated"] == P1 and st["previous_generated_main_sha"] == X
    assert _remote_prod(repo, "origin") == R and _remote_prod(repo, "internal") == R
    assert _branches(repo, "internal") == {TARGET["internal"]: R} and done["remote_refs"] == TARGET
    d = drift_check(str(repo), PROD, man)
    assert d["mode"] == "RESTORED_BASELINE" and d["ok"]
    # ⑤ re-promotion P2 from a descendant of X: parent R, no bootstrap flag needed
    (repo / "cfg.ini").write_bytes(b"[defaults]\nforks = 7\n")
    _git(repo, "commit", "-qam", "forks")
    X2 = _git(repo, "rev-parse", "main")
    res2 = _promote(world, X2)
    assert res2["ok"], res2
    P2 = store.rev_parse(PROD)
    assert store.commit_parents(P2) == [R] and GitStore.parse_trailers(store.commit_message(P2))["Bootstrap-Baseline"] == B
    assert _remote_prod(repo, "origin") == P2 == _remote_prod(repo, "internal")
    assert _branches(repo, "internal") == {TARGET["internal"]: P2} and _branches(repo, "origin")["refs/heads/main"] == X
    # ⑥ non-monotonic candidate (a commit beside main that does not descend from X2) → G20 FAIL → refused
    side = store.commit_tree(store.commit_tree_sha(X), [X], "side\n")
    res3 = _promote(world, side)
    assert not res3["ok"] and res3["stage"] == "verify" and any(gid == "G20" for gid, _ in res3["gate_details"]), res3
    assert store.rev_parse(PROD) == P2, "refusal moves nothing"


@_needs_ps
def test_restore_to_baseline_after_a_second_normal_promotion(world):
    """검토 C2: B → P1 → P2(normal) → restore(B) → P3. The nearest generated commit (P2) is not the one that *first* recorded
    the baseline; the record must be found through the history (and is inherited by P2), ancestry is judged from P2's main."""
    repo, store, B = world["repo"], world["store"], world["B"]
    X = _git(repo, "rev-parse", "main")
    assert _promote(world, X, bootstrap_baseline=B)["ok"]
    P1 = store.rev_parse(PROD)
    (repo / "cfg.ini").write_bytes(b"[defaults]\nforks = 9\n")
    _git(repo, "commit", "-qam", "forks 9")
    X2 = _git(repo, "rev-parse", "main")
    assert _promote(world, X2)["ok"]
    P2 = store.rev_parse(PROD)
    tr2 = GitStore.parse_trailers(store.commit_message(P2))
    assert store.commit_parents(P2) == [P1] and tr2["Bootstrap-Baseline"] == B and tr2["Bootstrap-Baseline-Tree"] == store.commit_tree_sha(B), "baseline inherited"
    rec, _, _ = baseline_record(store, P2, B)
    assert rec == P2, "the inherited record on the nearest generated commit is found first"
    # restore(B) dry-run and real — refused without the baseline argument, accepted with it
    with pytest.raises(ProdgenError):
        restore(str(repo), B, dry_run=True, push_remote=BOTH)
    pre = restore(str(repo), B, dry_run=True, push_remote=BOTH, bootstrap_baseline=B)
    assert pre["ok"] and pre["kind"] == "legacy_baseline" and store.rev_parse(PROD) == P2
    done = restore(str(repo), B, dry_run=False, push_remote=BOTH, bootstrap_baseline=B)
    assert done["ok"], done
    R = store.rev_parse(PROD)
    rt = GitStore.parse_trailers(store.commit_message(R))
    assert store.commit_tree_sha(R) == store.commit_tree_sha(B) and store.commit_parents(R) == [P2]
    assert rt["Restore-From"] == P2 and rt["Baseline-Recorded-By"] == P2 and rt["Bootstrap-Baseline"] == B
    assert _remote_prod(repo, "origin") == R == _remote_prod(repo, "internal")
    st = classify_production(store, R)
    assert st["state"] == "RESTORED_BASELINE" and st["ok"] and st["previous_generated"] == P2 and st["previous_generated_main_sha"] == X2
    # ancestry for P3 is judged against P2's main (X2): X (older) is refused, a descendant of X2 is accepted
    older = _promote(world, X)
    assert not older["ok"] and older["stage"] == "verify" and any(gid == "G20" for gid, _ in older["gate_details"]), older
    assert store.rev_parse(PROD) == R
    (repo / "cfg.ini").write_bytes(b"[defaults]\nforks = 11\n")
    _git(repo, "commit", "-qam", "forks 11")
    X3 = _git(repo, "rev-parse", "main")
    res3 = _promote(world, X3)
    assert res3["ok"], res3
    P3 = store.rev_parse(PROD)
    assert store.commit_parents(P3) == [R] and GitStore.parse_trailers(store.commit_message(P3))["Bootstrap-Baseline"] == B
    assert _remote_prod(repo, "origin") == P3 == _remote_prod(repo, "internal") == store.rev_parse(PROD)
    # a commit that only *claims* the baseline (no generated record in its history) is still refused as a restore target
    with pytest.raises(ProdgenError):
        restore(str(repo), X, dry_run=True, push_remote=BOTH, bootstrap_baseline=X)


@_needs_ps
def test_deploy_policy_and_ci_stage_evidence(world):
    """검토 C4: remotes dropped or narrowed → refused before any object is written; CI stage evidence is a precondition."""
    repo, store, B = world["repo"], world["store"], world["B"]
    X = _git(repo, "rev-parse", "main")
    for remotes in ("", "origin", "internal", "origin,other"):
        res = _promote(world, X, bootstrap_baseline=B, push_remote=remotes)
        assert not res["ok"] and res["stage"] == "policy" and "build" not in res, (remotes, res)
    assert store.rev_parse(PROD) == B and _remote_prod(repo, "origin") == B == _remote_prod(repo, "internal")
    # dry-run may use any remote set (preview only)
    pre = promote(str(repo), X, world["man"], dry_run=True, skip_live=False, push_remote="origin", bootstrap_baseline=B,
                  e2e_evidence=_evidence(X, world), ci_stage_results=_ci(X, world))
    assert pre["ok"] and pre["deploy_policy"]["ok"] and "commit" not in pre
    # CI stage evidence: missing → refused; a FAIL stage → refused; another SHA → refused
    res = promote(str(repo), X, world["man"], dry_run=False, skip_live=False, push_remote=BOTH, bootstrap_baseline=B, e2e_evidence=_evidence(X, world))
    assert not res["ok"] and res["stage"] == "ci", res
    res = _promote(world, X, bootstrap_baseline=B, ci_stage_results=_ci(X, world, bad="HARNESS_TREE"))
    assert not res["ok"] and res["stage"] == "ci" and "HARNESS_TREE=FAIL" in res["ci_stages"]["problems"][0], res
    res = _promote(world, X, bootstrap_baseline=B, ci_stage_results=_ci("0" * 40, world))
    assert not res["ok"] and res["stage"] == "ci", res
    assert store.rev_parse(PROD) == B, "refusals change no ref"
    # restore with one remote → refused (would leave the other remote behind); zero remotes = local-only with warning stays allowed
    assert _promote(world, X, bootstrap_baseline=B)["ok"]
    with pytest.raises(ProdgenError):
        restore(str(repo), B, dry_run=False, push_remote="origin", bootstrap_baseline=B)
    assert _remote_prod(repo, "origin") == _remote_prod(repo, "internal") == store.rev_parse(PROD)


@_needs_ps
def test_g20_without_remotes_is_partial_not_pass(world):
    repo = world["repo"]
    X = _git(repo, "rev-parse", "main")
    out = world["tmp"] / "tree_g20"
    build(str(repo), X, str(out), world["man"], live_checkers=True)
    rep = run_gates(str(repo), str(out), world["man"], remotes=[], bootstrap_baseline=world["B"])
    g20 = [r for r in rep.results if r.id == "G20"][0]
    assert g20.status == "PASS" and g20.partial and not g20.data["remotes_checked"] and not g20.data["deploy_set_complete"]
    assert rep.verdict == "PARTIAL" and any(m.startswith("G20: partial") for m in rep.mandatory_missing)
    rep2 = run_gates(str(repo), str(out), world["man"], remotes=["origin"], bootstrap_baseline=world["B"])
    g20b = [r for r in rep2.results if r.id == "G20"][0]
    assert g20b.status == "PASS" and not g20b.partial and g20b.data["remotes_checked"] == ["origin"] and not g20b.data["deploy_set_complete"]
    rep3 = run_gates(str(repo), str(out), world["man"], remotes=list(DEPLOY_REMOTES), bootstrap_baseline=world["B"])
    assert [r for r in rep3.results if r.id == "G20"][0].data["deploy_set_complete"]


@_needs_ps
def test_shared_push_url_across_target_refs_is_refused_before_writing(world):
    """2026-11-02: `origin` used to carry the GitLab repository (remote `internal`) as a second push URL (dual push, the
    2026-10-04 P1 configuration). With GitLab in customer form the two remotes carry production on different refs, so that URL
    would create `production` on GitLab. promote / restore / push-sync refuse it before anything is written (a dry-run shows
    it) and go through again once the extra push URL is removed."""
    repo, store, B = world["repo"], world["store"], world["B"]
    origin_url, internal_url = _git(repo, "remote", "get-url", "origin"), _git(repo, "remote", "get-url", "internal")
    _git(repo, "remote", "set-url", "--add", "--push", "origin", origin_url)
    _git(repo, "remote", "set-url", "--add", "--push", "origin", internal_url)
    X = _git(repo, "rev-parse", "main")
    res = _promote(world, X, bootstrap_baseline=B)
    assert not res["ok"] and res["stage"] == "policy" and "build" not in res, res
    assert "remove the extra push URL" in res["refused"] and f"internal → {TARGET['internal']}" in res["refused"], res["refused"]
    pre = promote(str(repo), X, world["man"], dry_run=True, skip_live=True, push_remote=BOTH, bootstrap_baseline=B)
    assert pre["deploy_policy"]["preview_refusals"] and "commit" not in pre, pre["deploy_policy"]
    with pytest.raises(ProdgenError, match="push target of origin and internal"):
        restore(str(repo), B, dry_run=False, push_remote=BOTH, bootstrap_baseline=B)
    with pytest.raises(ProdgenError, match="push-sync refused"):
        push_sync(str(repo), PROD, list(DEPLOY_REMOTES), dry_run=False)
    assert push_sync(str(repo), PROD, list(DEPLOY_REMOTES), dry_run=True)["preview_refusals"]
    assert store.rev_parse(PROD) == B and _branches(repo, "internal") == {TARGET["internal"]: B}, "nothing written, no production on GitLab"
    # the extra push URL removed → the same promotion goes through; GitLab still has nothing but main
    _git(repo, "config", "--unset-all", "remote.origin.pushurl")
    res = _promote(world, X, bootstrap_baseline=B)
    assert res["ok"], res.get("refused")
    P1 = res["commit"]
    assert "shared_push_urls" not in res["publish"] and _branches(repo, "internal") == {TARGET["internal"]: P1}
    # a remote already holding exactly the new commit on its own target ref is an idempotent success, not partial_push
    new = store.commit_tree(store.commit_tree_sha(P1), [P1], "candidate\n\nX: y\n")
    _git(repo, "push", "-q", "internal", f"{new}:{TARGET['internal']}")
    pub = _publish(store, PROD, new, P1, list(DEPLOY_REMOTES))
    assert [d["remote"] for d in pub["done"]] == ["origin", "internal"] and not pub["failed"] and pub["local_updated"], pub
    assert pub["done"][1]["ref"] == TARGET["internal"] and pub["done"][1]["protection"] == "already at the new commit (idempotent)"
    assert _remote_prod(repo, "origin") == new == _remote_prod(repo, "internal") == store.rev_parse(PROD)
    # a remote that moved to something ELSE is still a pre-check failure (the idempotent branch only accepts the new commit)
    other = store.commit_tree(store.build_tree([("100644", store.hash_object(b"other\n", write=True), "legacy.txt")], write=True), [new], "other\n")
    _git(repo, "push", "-q", "internal", f"{other}:{TARGET['internal']}")
    newer = store.commit_tree(store.commit_tree_sha(new), [new], "candidate 2\n\nX: z\n")
    pub2 = _publish(store, PROD, newer, new, ["internal"])
    assert pub2["failed"] and pub2["failed"][0]["stage"] == "pre-check" and pub2["failed"][0]["ref"] == TARGET["internal"]
    assert not pub2["local_updated"] and store.rev_parse(PROD) == new


@_needs_ps
def test_refusals_evidence_skiplive_remotes_and_race(world):
    repo, store, B, man = world["repo"], world["store"], world["B"], world["man"]
    X = _git(repo, "rev-parse", "main")
    # --skip-live only with --dry-run
    with pytest.raises(ProdgenError):
        promote(str(repo), X, man, dry_run=False, skip_live=True, push_remote=BOTH, bootstrap_baseline=B)
    # dry-run preview with PARTIAL gates is allowed (shows the commit) but says so
    pre = promote(str(repo), X, man, dry_run=True, skip_live=True, push_remote=BOTH, bootstrap_baseline=B)
    assert pre["ok"] and pre["gates"]["verdict"] == "PARTIAL" and "preview_only" in pre and "commit" not in pre
    assert store.rev_parse(PROD) == B
    # missing E2E evidence → refused (real run)
    res = promote(str(repo), X, man, dry_run=False, skip_live=False, push_remote=BOTH, bootstrap_baseline=B, ci_stage_results=_ci(X, world))
    assert not res["ok"] and res["stage"] == "e2e", res
    # a failing required scenario → refused
    res = _promote(world, X, bootstrap_baseline=B, e2e_evidence=_evidence(X, world, fail="S3"))
    assert not res["ok"] and res["stage"] == "e2e" and any("S3" in p for p in res["e2e"]["problems"]), res
    # evidence for another SHA → refused
    res = _promote(world, X, bootstrap_baseline=B, e2e_evidence=_evidence("0" * 40, world, tree_hash="0" * 64))
    assert not res["ok"] and res["stage"] == "e2e", res
    # generated-tree Harness evidence missing → refused (main-function evidence does not stand in for it)
    res = _promote(world, X, bootstrap_baseline=B, e2e_evidence=_evidence(X, world, tree_items=False))
    assert not res["ok"] and res["stage"] == "e2e" and any("generated-tree" in p for p in res["e2e"]["problems"]), res
    # generated-tree evidence for another tree → refused
    res = _promote(world, X, bootstrap_baseline=B, e2e_evidence=_evidence(X, world, tree_hash="e" * 64))
    assert not res["ok"] and res["stage"] == "e2e" and any("tree" in p for p in res["e2e"]["problems"]), res
    assert store.rev_parse(PROD) == B and _remote_prod(repo, "origin") == B, "refusals change no ref"
    # remotes disagree → refused before any object is written
    moved = store.commit_tree(store.build_tree([("100644", store.hash_object(b"moved\\n", write=True), "legacy.txt")], write=True), [B], "moved on internal\n")
    _git(repo, "push", "-q", "internal", f"{moved}:{TARGET['internal']}")
    res = _promote(world, X, bootstrap_baseline=B)
    assert not res["ok"], res
    with pytest.raises(ProdgenError):
        remote_baseline(store, PROD, list(DEPLOY_REMOTES))
    # push-sync: origin=B, internal=moved(B+1) → fast-forward origin and the local ref to moved (no force)
    sync = push_sync(str(repo), PROD, list(DEPLOY_REMOTES), dry_run=False)
    assert sync["ok"] and _remote_prod(repo, "origin") == moved == _remote_prod(repo, "internal") == store.rev_parse(PROD)
    assert sync["remote_refs"] == TARGET and _branches(repo, "internal") == {TARGET["internal"]: moved}, "GitLab stays customer-form"
    # race: baseline computed (expected=moved), origin moves before publish → pre-check fails, nothing moved locally
    expected = store.rev_parse(PROD)
    raced = store.commit_tree(store.build_tree([("100644", store.hash_object(b"raced\\n", write=True), "legacy.txt")], write=True), [expected], "raced\n")
    _git(repo, "push", "-q", "origin", f"{raced}:{PROD}")
    new = store.commit_tree(store.commit_tree_sha(expected), [expected], "candidate\n\nX: y\n")
    pub = _publish(store, PROD, new, expected, list(DEPLOY_REMOTES))
    assert pub["failed"] and pub["failed"][0]["remote"] == "origin" and pub["failed"][0]["stage"] == "pre-check"
    assert not pub["local_updated"] and store.rev_parse(PROD) == expected
    # true divergence: internal gets a *different* child of moved → no single descendant → push-sync refuses, no force
    other = store.commit_tree(store.build_tree([("100644", store.hash_object(b"other\\n", write=True), "legacy.txt")], write=True), [expected], "other on internal\n")
    _git(repo, "push", "-q", "internal", f"{other}:{TARGET['internal']}")
    div = push_sync(str(repo), PROD, list(DEPLOY_REMOTES), dry_run=False)
    assert not div["ok"] and "divergence" in div["refused"]
    assert _remote_prod(repo, "origin") == raced and _remote_prod(repo, "internal") == other, "refusal moves nothing"


def test_remote_ref_contract():
    """2026-11-02 (사용자 결정): GitHub `origin` carries production on refs/heads/production, the customer-form GitLab `internal`
    on refs/heads/main. A non-default --production-ref is never mapped — a trial ref must not land on the customer `main`."""
    assert DEPLOY_TARGET_REFS == TARGET and set(DEPLOY_TARGET_REFS) == set(DEPLOY_REMOTES)
    assert {r: remote_ref(r) for r in DEPLOY_REMOTES} == TARGET and remote_ref("other") == PROD
    assert remote_ref("internal", "refs/heads/prod-trial") == "refs/heads/prod-trial" == remote_ref("origin", "refs/heads/prod-trial")


def test_repo_key_treats_one_repository_as_one_push_target():
    """http/https, credentials, port, `.git` and a trailing slash do not make the GitLab project a different push target."""
    gitlab = _repo_key("https://10.100.64.156/root/server-expoter.git")
    assert gitlab == "10.100.64.156/root/server-expoter"
    for same in ("http://10.100.64.156/root/server-expoter.git", "https://user@10.100.64.156:443/root/server-expoter/",
                 "ssh://git@10.100.64.156:2222/root/server-expoter.git", "git@10.100.64.156:root/server-expoter.git"):
        assert _repo_key(same) == gitlab, same
    github = _repo_key("git@github.com:hshwang1994/server-exporter.git")
    assert github == _repo_key("https://GitHub.com/hshwang1994/server-exporter") != gitlab
    assert "user" not in _repo_key("https://user:secret@10.100.64.156/root/server-expoter.git"), "no credential in the key"


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
    # an exact-tree restore commit whose history holds no generated record is UNVERIFIED as well
    fake2 = store.commit_tree(store.commit_tree_sha(B), [B], f"fake restore\n\nRestore-Of: {B}\nBootstrap-Baseline: {B}\n")
    st2 = classify_production(store, fake2)
    assert st2["state"] == "UNVERIFIED" and any("no generated production" in r for r in st2["reasons"])
    assert baseline_record(store, fake2, B) == (None, None, None)
