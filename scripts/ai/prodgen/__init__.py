"""prodgen — production tree generator (Plan Phase 7a).

Reads a fixed git SHA from the object store only, emits a runtime-only tree with
explanatory comments removed, and verifies the result with fail-closed gates.
"""
GENERATOR_VERSION = "1.0.0"
RULES_VERSION = "2026.10.03"
PROVENANCE_FILE = ".production-provenance.json"
# deployment policy (2026-10-04, 검토 C4): a real promotion/restore publishes to **both** remotes or to none. CI (`se-gitlab-push`)
# and the session CLI (git credential helper / askpass) are two ways to hold the credentials — the remote *set* is the policy.
DEPLOY_REMOTES = ("origin", "internal")
# CI stages whose PASS is a precondition of a real promotion (ci_stage_results.json) — same list as Jenkinsfile_ci Promote
REQUIRED_CI_STAGES = ("GATE", "CORPUS", "BUDGET", "HARNESS_MAIN", "PRODGEN_BUILD", "HARNESS_TREE", "PRODGEN_DRIFT", "PRODGEN_VERIFY", "EVIDENCE")
