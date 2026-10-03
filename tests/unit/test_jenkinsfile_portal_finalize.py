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
    assert "groovy.json.JsonOutput.toJson(params.loc.trim())" in FINALIZE and "replaceAll('\\\\\\\\'" not in TEXT, "escaping 은 JsonOutput 하나"
    assert "'/api/jenkins/gather/' + params.target_type.trim()" in CALLBACK, "endpoint 계약 불변"


def test_lines_is_not_referenced_after_it_is_nulled():
    """R5 (2026-10-03 Astra 2차): body 조립 뒤 `lines = null` 로 비운 다음 `lines.size()` 를 다시 불러 정상 경로(delivered=true)에서
    NPE 가 났다. 줄 수는 줄 집합 확정 직후·첫 사용 전에 lineCount 로 한 번 읽고, 이후에는 그 값만 쓴다."""
    i_count = FINALIZE.index("int lineCount = lines.size()")
    i_warn = FINALIZE.index("[WARN] invariant 위반")
    m_null = re.search(r"^\s*lines = null\s*$", FINALIZE, re.M)   # 선언(List lines = null)이 아니라 비우는 문장
    assert m_null, "lines 를 비우는 문장이 없다"
    i_null = m_null.start()
    assert i_count < i_warn < i_null, "lineCount 는 첫 사용(WARN) 전에 선언되고 lines 는 그 뒤에 비운다"
    tail = FINALIZE[m_null.end():]
    assert not re.search(r"(?<![\w.])lines\b", tail), "lines 를 비운 뒤에는 lines 를 참조하지 않는다"
    assert "lineCount != accepted" in tail and "lines.size()" not in tail
    assert "lines: lineCount" in FINALIZE, "finalize_summary 에 실제 줄 수를 남긴다"


def test_runtime_groovy_uses_only_sandbox_whitelisted_json_parsers():
    """2026-10-03 lab Jenkins 실측(Harness sandbox probe): `new groovy.json.JsonSlurper()` · `readJSON(returnPojo)` 는 허용,
    `new groovy.json.JsonSlurperClassic()` 은 거부. 운영 Groovy(Jenkinsfile_portal · se_finalize.groovy)는 승인 없이 돌아야 한다."""
    assert "JsonSlurperClassic" not in TEXT and "JsonSlurperClassic" not in LIB
    assert "new groovy.json.JsonSlurper()" in LIB
    assert "readJSON(text: params.inventory_json, returnPojo: true)" in TEXT


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


PRESERVE = _method("def sePreserveGatherOutput")


def test_gather_post_runs_layer_a_then_preserves_then_deletes_only_when_safe():
    assert re.search(r"post \{\s*(//[^\n]*\n\s*)*always \{\s*script \{\s*sePreserveGatherOutput\(\)", GATHER), "Gather post{always} 는 helper 한 번"
    post = PRESERVE
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


def test_preserve_steps_are_independent_and_delete_only_after_archive():
    """R7 (2026-10-03 Astra 2차): archive 실패가 stash 를 막지 않는다. 각 보존 시도는 독립 try/catch 이고 interruption 은 재throw.
    workspace 는 영구 archive 성공 + 이 빌드의 manifest + 결과 파일이 있을 때만 지운다."""
    post = PRESERVE
    assert post.count("catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)") >= 4, "Layer A · archive · stash · manifest 각각"
    assert post.count("throw fie") >= 4
    assert post.index("archiveArtifacts(") < post.index("archived = true") < re.search(r"^\s*stash\($", post, re.M).start() < post.index("stashed = true")
    assert "if (archived && manifestOk && hasResult) {" in post and post.index("if (archived && manifestOk && hasResult)") < post.index("deleteDir()")
    assert "boolean hasResult = fileExists('gather_final.jsonl') || fileExists('gather_output.json')" in post
    for flag in ("SE_PRESERVE_ARCHIVED", "SE_PRESERVE_STASHED", "SE_PRESERVE_MANIFEST", "SE_PRESERVE_HASRESULT", "SE_PRESERVE_LAYER_A"):
        assert f"env.{flag}" in post, flag
    assert "결과 보존 실패(archive·stash 모두)" in post and "archive 실패 — stash 로만 전달" in post
    assert TEXT.count("deleteDir()") == 3, "finalizer 2 + preserve 1 — 다른 곳에서 workspace 를 지우지 않는다"
    assert "preserve: [layerA: env.SE_PRESERVE_LAYER_A" in FINALIZE, "finalizer 요약에 보존 결과를 남긴다"


def test_finalizer_validates_lines_and_records_damage():
    """3차 §6: 잘린 report/JSONL 이어도 Callback body 는 유효한 envelope 만 담고, 탈락 줄·미복구 host·손상 상태를 따로 기록한다."""
    assert "Map seFilterEnvelopeLines(List rawLines, String manifestJson)" in TEXT
    helper = _method("Map seFilterEnvelopeLines")
    assert "new groovy.json.JsonSlurper()" in helper and "keys13" in helper and "accepted.contains(" in helper and "missing" in helper
    assert FINALIZE.count("seFilterEnvelopeLines(") == 2, "Layer A 결과와 raw fallback 둘 다 같은 검문"
    assert "layerA = 'report_unreadable'" in FINALIZE and "layerA = 'incomplete'" in FINALIZE
    i_read = FINALIZE.index("readJSON file: 'gather_finalize_report.json'")
    seg = FINALIZE[i_read: i_read + 1800]
    assert "catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)" in seg, "파싱 실패 복구와 interruption 재전파를 분리"
    assert "unrecovered = picked.missing" in FINALIZE
    for key in ("unrecovered: unrecovered", "damage: damage", "recovery_limited: (layerB == 'unavailable' && lineCount != accepted)"):
        assert key in FINALIZE, key


def test_no_agent_is_accepted_then_failed_not_a_build_error():
    assert "env.SE_GATHER_OUTCOME = 'no_agent'" in RESOLVE
    assert "error \"[Resolve Location] 라벨" not in RESOLVE, "Runner 부재는 접수 후 실행 실패 — error 로 끊지 않는다"
    assert "when { expression { env.SE_GATHER_OUTCOME != 'no_agent' } }" in GATHER
    assert "unstable(\"[Resolve Location] 온라인 노드 없음" in RESOLVE


LIB = (REPO / "scripts/jenkins/se_finalize.groovy").read_text(encoding="utf-8")


def test_portal_loads_layer_b_library_instead_of_defining_it():
    """GP-11 (2026-10-03): Layer B 순수 함수의 정본은 scripts/jenkins/se_finalize.groovy 하나다. Jenkinsfile_portal 은 finalizer node 안에서
    readTrusted → writeFile → load 로 읽고, 실패하면 Layer B 보충 없이(raw OUTPUT 줄만) 보내며 UNSTABLE 로 남긴다."""
    for sig in ("Map seFallbackCanon()", "String seJsonString(", "Map seReconcileRaw("):
        assert sig not in TEXT, f"Jenkinsfile_portal 에 {sig} 사본이 있다 — 정본은 se_finalize.groovy"
    assert "readTrusted('scripts/jenkins/se_finalize.groovy')" in TEXT and "return load('se_finalize.groovy')" in TEXT
    assert FINALIZE.index("node('built-in')") < FINALIZE.index("seLoadFinalizeLib()"), "load 는 workspace 가 있는 node 안에서"
    assert "lib.seReconcileRaw(manifestJson, outText, cpText, seLoadCanon(lib), outcome)" in FINALIZE
    assert "layerB = 'unavailable'" in FINALIZE and "layerB == 'unavailable'" in FINALIZE, "라이브러리 부재는 숨기지 않는다 (UNSTABLE)"
    assert "FlowInterruptedException fie" in TEXT[TEXT.index("def seLoadFinalizeLib()"):TEXT.index("def seLoadCanon(")], "Abort 는 다시 던진다"


def test_groovy_fallback_canon_matches_yaml_and_layer_a():
    canon = LIB[LIB.index("Map seFallbackCanon()"):LIB.index("String seJsonString")]
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
