"""prodgen — production tree generator (Plan Phase 7a).

Reads a fixed git SHA from the object store only, emits a runtime-only tree with
explanatory comments removed, and verifies the result with fail-closed gates.
"""
GENERATOR_VERSION = "1.0.0"
RULES_VERSION = "2026.10.03"
PROVENANCE_FILE = ".production-provenance.json"
PRODUCTION_REF = "refs/heads/production"
# deployment policy (2026-10-04, 검토 C4): a real promotion/restore publishes to **both** remotes or to none. CI (`se-gitlab-push`)
# and the session CLI (git credential helper / askpass) are two ways to hold the credentials — the remote *set* is the policy.
DEPLOY_REMOTES = ("origin", "internal")
# 2026-11-02 (사용자 결정): the in-house GitLab (`internal`) is customer-form — its only branch is `main` and it carries the production
# commit (no development main, no `production` branch there). GitHub (`origin`) keeps `main` (development) and `production`.
# A promotion writes the same commit to each remote's own ref; the local ref stays refs/heads/production.
DEPLOY_TARGET_REFS = {"origin": PRODUCTION_REF, "internal": "refs/heads/main"}
# CI stages whose PASS is a precondition of a real promotion (ci_stage_results.json) — same list as Jenkinsfile_ci Promote
REQUIRED_CI_STAGES = ("GATE", "CORPUS", "BUDGET", "HARNESS_MAIN", "PRODGEN_BUILD", "HARNESS_TREE", "PRODGEN_DRIFT", "PRODGEN_VERIFY", "EVIDENCE")


def remote_ref(remote: str, production_ref: str = PRODUCTION_REF) -> str:
    """The ref on `remote` that carries production. Only the default production ref is mapped per deploy remote (GitLab
    `internal` → refs/heads/main); any other --production-ref is used unchanged on every remote, so a trial ref never lands on
    the customer-form `main`."""
    if production_ref == PRODUCTION_REF:
        return DEPLOY_TARGET_REFS.get(remote, production_ref)
    return production_ref
