"""Jenkinsfile_portal — 2026-10-03 Phase 4 (Plan §6-1 ~ §6-6) finalization·예산·Callback 텍스트 계약.

고정하는 것
  1. 구조: stage 는 Validate → Resolve Location → Gather 셋뿐. Validate Schema·Callback stage 는 없다(검증은 scripts/ai/ci_gate.sh,
     전송은 pipeline post{always} 의 finalizer). finalizer 는 `timeout(FINALIZER_TOTAL){ node('built-in'){…} }` 하나 — 합산 제한.
  2. 예산: 공식은 scripts/gather_budget.sh 한 곳. Jenkinsfile 은 node 진입 시 est, ansible 직전 exec 두 번 부르고 exec 값만
     `timeout --signal=INT --kill-after=90 "$SE_GATHER_BUDGET_SEC"` 에 넣는다. start=false 면 수집을 시작하지 않는다(not_started_budget).
  3. 보존: Gather post{always} 가 Layer A → archive → stash(allowEmpty) → (manifest 가 이 빌드 것일 때만) deleteDir.
  4. 회수: finalizer 가 unstash → unarchive → manifest-only 순. Layer A 결과(exit 0/2) 우선, 없으면 Layer B 최소 경로.
  5. Callback: 남은 예산 기반 timeout, 2xx 성공, 408/429 외 4xx 중단, remaining < CALLBACK_MIN 이면 미시도 기록, ABORTED 1회.
     body 는 JsonOutput 으로 escaping (수동 replaceAll 없음). 실패/보충은 UNSTABLE.
  6. Runner 부재: Resolve Location 이 error 가 아니라 outcome=no_agent → Gather skip → finalizer 가 manifest 로 보충 + Callback.
  7. Groovy 복제값(seFallbackCanon)은 정본 YAML·finalize 스크립트 상수와 같다 (drift).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
JENKINSFILE = REPO / "Jenkinsfile_portal"
TEXT = JENKINSFILE.read_text(encoding="utf-8")


def _stage(name: str) -> str:
    start = TEXT.index(f"stage('{name}')")
    nxt = re.search(r"\n        stage\('", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


def _method(name: str) -> str:
    start = TEXT.index(f"{name}(")
    start = TEXT.rfind("\n", 0, start) + 1
    nxt = re.search(r"\n(?:@NonCPS\n)?(?:def |Map |String |boolean |long |pipeline \{)", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


GATHER = _stage("Gather")
RESOLVE = _stage("Resolve Location")
FINALIZE = _method("def seFinalizeAndCallback")
CALLBACK = _method("boolean seCallback")


def test_only_three_stages_and_no_callback_or_schema_stage():
    stages = re.findall(r"\n        stage\('([^']+)'\)", TEXT)
    assert stages == ["Validate", "Resolve Location", "Gather"]
    assert "Validate Schema" not in TEXT and "stage('Callback')" not in TEXT


def test_finalizer_is_a_single_summed_timeout_around_one_builtin_node():
    assert len(re.findall(r"\bnode\('built-in'\)", TEXT)) == 1, "finalizer 의 node('built-in') 한 곳"
    assert "timeout(time: C.FINALIZER_TOTAL, unit: 'SECONDS') {" in FINALIZE
    assert FINALIZE.index("timeout(time: C.FINALIZER_TOTAL") < FINALIZE.index("node('built-in')"), "timeout 이 node 대기까지 감싼다(합산 제한)"
    assert "FINALIZER_TOTAL  : 720" in TEXT
    assert "long finalizerDeadline = tPost + C.FINALIZER_TOTAL" in FINALIZE, "node 진입 후 남은 시간은 post 진입 시각 기준으로 다시 계산"
    assert "seFinalizeAndCallback()" in TEXT[TEXT.index("    post {\n        always {"):]


def test_finalizer_recovers_inputs_in_order_and_prefers_layer_a():
    i_unstash = FINALIZE.index("unstash 'gather-output'")
    i_unarchive = FINALIZE.index("unarchive mapping:")
    i_layer_b = FINALIZE.index("seReconcileRaw(manifestJson")
    assert i_unstash < i_unarchive < i_layer_b
    assert "$JENKINS_HOME" not in TEXT and "JENKINS_HOME" not in TEXT, "archive 는 unarchive step 으로만 회수한다"
    assert "rep.exit_code in [0, 2]" in FINALIZE, "Layer A 결과(exit 0/2) 우선"
    assert "layerA=${layerA}" in FINALIZE and "source=${source}" in FINALIZE


def test_finalizer_handles_no_manifest_and_builds_contract_body():
    assert "접수 manifest 없음" in FINALIZE and "전송할 것 없음" in FINALIZE
    for key in ('"loc":', '"deploymentEnvironmentId":', '"eventUuid":', '"gatherInfoJson":['):
        assert key in FINALIZE, key
    assert "seJsonString(" in FINALIZE and "replaceAll('\\\\\\\\'" not in TEXT, "escaping 은 JsonOutput 하나"
    assert "groovy.json.JsonOutput.toJson(value == null ? '' : value.toString())" in TEXT
    assert "'/api/jenkins/gather/' + params.target_type.trim()" in CALLBACK, "endpoint 계약 불변"


def test_callback_budget_rules():
    assert "if (remaining < C.CALLBACK_MIN)" in CALLBACK and "callback not attempted: budget" in CALLBACK
    assert "Math.min(C.CALLBACK_ATTEMPT, (int) (remaining - 10))" in CALLBACK
    assert "code ==~ /2\\d\\d/" in CALLBACK
    assert "!(code in ['408', '429'])" in CALLBACK, "결정적 4xx 는 중단, 408/429 는 재시도"
    assert "aborted ? 1 : 3" in CALLBACK and "ABORT_ATTEMPT    : 60" in TEXT
    assert "catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)" in CALLBACK, "Abort 는 삼키지 않는다"
    assert "unstable(\"[Finalize] Callback 전송 실패" in FINALIZE
    assert "filled > 0 || outcome != 'completed'" in FINALIZE


def test_budget_is_computed_by_the_script_twice_and_exec_value_is_enforced():
    assert "bash scripts/gather_budget.sh" in GATHER
    assert GATHER.count("readJSON text: sh(returnStdout: true, script: budgetScript") == 2, "node 진입 시 est + ansible 직전 exec"
    assert GATHER.index("label: 'budget estimate'") < GATHER.index("ADDON_REPO_URL") < GATHER.index("label: 'budget exec'") < GATHER.index("ansible-playbook ")
    assert 'timeout --signal=INT --kill-after=90 "\\${SE_GATHER_BUDGET_SEC}"' in GATHER
    assert '"SE_GATHER_BUDGET_SEC=${exec.budget}"' in GATHER and '-f "\\${SE_GATHER_FORKS}"' in GATHER
    assert "env.SE_GATHER_OUTCOME = 'not_started_budget'" in GATHER and "if (!exec.start)" in GATHER
    assert "SE_FORCE_SEC=${budgetForce}" in GATHER, "강제값도 스크립트를 거친다(남은 시간을 넘지 못함)"
    assert "options { timeout(time: 115, unit: 'MINUTES') }" in GATHER, "stage 합산 상한 = gather_budget.sh STAGE_LIMIT_SEC"
    assert "env.SE_STAGE_START_EPOCH = \"${seNowSec()}\"" in GATHER
    assert "env.SE_BUILD_START_EPOCH = " in _stage("Validate")


def test_rc_to_outcome_mapping():
    for rc, outcome in (("[0, 2, 4, 8]", "completed"), ("124", "timeout"), ("137", "timeout_killed"), ("90", "prep_failed")):
        assert f"env.SE_GATHER_OUTCOME = '{outcome}'" in GATHER, outcome
        assert rc in GATHER
    assert "env.SE_GATHER_OUTCOME = 'interrupted_unknown'" in GATHER, "아무 분기도 못 타면 중단으로 남긴다"
    assert "|| exit 90" in GATHER, "venv 실패 = prep_failed"
    assert "gather_output.json 미생성/0바이트" not in TEXT, "0바이트는 FAILURE 로 끊지 않고 finalizer 가 보충한다"


def test_gather_post_runs_layer_a_then_preserves_then_deletes_only_when_safe():
    post = GATHER[GATHER.index("post {"):]
    i_a = post.index("scripts/finalize_gather_output.py")
    i_arch = post.index("archiveArtifacts(")
    i_stash = re.search(r"^\s*stash\($", post, re.M).start()   # 주석의 'stash(' 가 아니라 step 호출
    i_del = post.index("deleteDir()")
    assert i_a < i_arch < i_stash < i_del
    assert "timeout 120 python3 scripts/finalize_gather_output.py" in post
    assert "allowEmpty : true" in post and "allowEmptyArchive: true" in post
    assert "gather_final.jsonl" in post and "gather_finalize_report.json" in post and "gather_progress.jsonl" in post
    assert "m?.build?.number?.toString() == env.BUILD_NUMBER" in post, "manifest 가 이 빌드 것일 때만 지운다"
    assert "workspace kept for forensics" in post


def test_no_agent_is_accepted_then_failed_not_a_build_error():
    assert "env.SE_GATHER_OUTCOME = 'no_agent'" in RESOLVE
    assert "error \"[Resolve Location] 라벨" not in RESOLVE, "Runner 부재는 접수 후 실행 실패 — error 로 끊지 않는다"
    assert "when { expression { env.SE_GATHER_OUTCOME != 'no_agent' } }" in GATHER
    assert "unstable(\"[Resolve Location] 온라인 노드 없음" in RESOLVE


def test_groovy_fallback_canon_matches_yaml_and_layer_a():
    canon = TEXT[TEXT.index("Map seFallbackCanon()"):TEXT.index("String seJsonString")]
    fr = yaml.safe_load((REPO / "common/vars/failure_reasons.yml").read_text(encoding="utf-8"))
    assert f"reason  : '{fr['_fr_catalog']['output_build_failed']['default']}'" in canon
    ss = yaml.safe_load((REPO / "common/vars/supported_sections.yml").read_text(encoding="utf-8"))
    for ch, secs in ss["channel_sections"].items():
        assert f"'{ch}'" in canon and "', '".join(secs) in canon, ch
    assert "', '".join(ss["all_sections"]) in canon
    layer_a = (REPO / "scripts/finalize_gather_output.py").read_text(encoding="utf-8")
    emit = re.search(r"EMIT_FAILED = '([^']+)'", layer_a).group(1)
    assert f"emitFailed: '{emit}'" in canon, "Layer A 와 Layer B 의 checkpoint 복원 문장은 같다"
    budget = (REPO / "scripts/gather_budget.sh").read_text(encoding="utf-8")
    assert "GLOBAL_SEC=9000" in budget and "GLOBAL           : 9000" in TEXT
    assert "STAGE_LIMIT_SEC=6900" in budget, "Gather stage 115 min 과 같다"


def test_progress_and_checkpoint_env_wired_for_json_only():
    for var in ("ANSIBLE_JSON_MANIFEST_FILE", "ANSIBLE_JSON_PROGRESS_FILE", "ANSIBLE_JSON_CHECKPOINT_FILE"):
        assert var in GATHER, var


def test_file_has_lf_line_endings():
    assert b"\r\n" not in JENKINSFILE.read_bytes()
