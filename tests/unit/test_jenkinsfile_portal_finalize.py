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

import pytest
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
    assert "[Callback] [OK] HTTP ${code}" in CALLBACK and "response=${msg.length() > 200 ? msg.substring(0, 200) : msg}" in CALLBACK, "2xx 는 HTTP 응답 증거 — 응답 본문 앞부분을 남긴다(저장 증거 아님)"
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
    # R6: stage 기준점은 agent 를 얻기 전(Resolve Location 끝) — nodesByLabel 뒤, Gather 앞. node 진입 시각은 Gather 첫 statement.
    assert "env.SE_STAGE_START_EPOCH = \"${seNowSec()}\"" in RESOLVE and RESOLVE.index("nodesByLabel(") < RESOLVE.index("env.SE_STAGE_START_EPOCH =")
    assert "env.SE_STAGE_START_EPOCH = \"${seNowSec()}\"" not in GATHER, "Gather 안에서 기준점을 다시 찍지 않는다(대기 시간이 사라진다)"
    assert "env.SE_NODE_ENTER_EPOCH = \"${seNowSec()}\"" in GATHER and GATHER.index("env.SE_NODE_ENTER_EPOCH") < GATHER.index("writeFile(file: 'gather_manifest.json'")
    for field in ("pre=${", "wait_checkout=${", "prep=${"):
        assert GATHER.count(field) == 2, f"{field} est·exec 두 로그 모두"
    assert "wait=${" not in GATHER, "wait_checkout 은 순수 agent 대기가 아니다 — 이름으로 분명히 한다"
    assert "env.SE_BUILD_START_EPOCH = " in _stage("Validate")


def test_rc_to_outcome_mapping():
    for rc, outcome in (("[0, 2, 4, 8]", "completed"), ("124", "timeout"), ("137", "timeout_killed"), ("90", "prep_failed")):
        assert f"env.SE_GATHER_OUTCOME = '{outcome}'" in GATHER, outcome
        assert rc in GATHER
    assert "env.SE_GATHER_OUTCOME = 'interrupted_unknown'" in GATHER, "아무 분기도 못 타면 중단으로 남긴다"
    # 3차 §4-2 / §6: 취소·timeout 은 원인을 기록하고 재전파, 메모리 부족은 시간 부족과 다른 사유
    assert "env.SE_GATHER_OUTCOME = 'aborted'" in GATHER and "env.SE_GATHER_OUTCOME = 'not_started_memory'" in GATHER
    assert "if (exec.reason == 'not_started_memory')" in GATHER and "Runner 가용 메모리 부족" in GATHER


def test_interruptions_are_recorded_and_rethrown_not_swallowed():
    """3차 §4-2: catchError 기본값은 수동 중단·timeout 도 삼킨다 → catchInterruptions: false. Gather 의 interruption 경계는 outcome 을 적고
    다시 던진다. seLoadCanon · Add-on checkout 의 일반 catch 도 interruption 을 먼저 재전파한다."""
    assert "catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE', catchInterruptions: false)" in GATHER
    assert "catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {" not in GATHER
    i_abort = GATHER.index("env.SE_GATHER_OUTCOME = 'aborted'")
    before = GATHER[max(0, i_abort - 600): i_abort]
    after = GATHER[i_abort: i_abort + 400]
    assert "catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)" in before, "interruption 경계의 catch 안에서 기록한다"
    assert "throw fie" in after, "기록 뒤 재전파"
    canon = _method("def seLoadCanon")
    assert canon.index("FlowInterruptedException fie") < canon.index("catch (Exception e)"), "정본 읽기 실패 catch 가 interruption 을 삼키지 않는다"
    addon = GATHER[GATHER.index("def fetchAddon"):GATHER.index("if (!problem)")]
    assert addon.index("FlowInterruptedException fie") < addon.index("catch (Exception e)")


def test_bounded_recovery_is_opt_in_and_identity_based():
    """3차 §4-1: 원인 클래스·경과 시간으로 판정하지 않는다. nodeId 가 우리 timeout step 과 같을 때만 지역 처리, 식별 불가는 재전파.
    sandbox 기본값(2026-10-03 lab 실측)은 getCauses/getNodeId/getEnclosingBlocks/getId 를 모두 거부하므로 기본은 꺼져 있다."""
    bounded = _method("boolean seBounded")
    assert "env.SE_FINALIZER_BOUNDED" in bounded and "body()\n        return true" in bounded, "기본 off = 종전 동작"
    assert "getContext(org.jenkinsci.plugins.workflow.graph.FlowNode)" in bounded and "seEnclosingIds(n, 2)" in bounded
    assert "if (ownIds && seIsOwnTimeout(fie, ownIds))" in bounded and "        throw fie\n    }\n}\n" in bounded, "식별되지 않으면 재전파"
    own = _method("boolean seIsOwnTimeout")
    assert "ExceededTimeout" in own and "ownIds.contains(c.getNodeId()?.toString())" in own and "return false" in own
    assert "currentTimeMillis" not in own and "currentTimeMillis" not in bounded, "경과 시간 판정 없음"
    for call in ("seBounded(C.RECOVER, 'unstash')", "seBounded(C.RECOVER, 'unarchive')", "seBounded(C.ASSEMBLE, 'assemble')",
                 "seBounded(C.ASSEMBLE_MIN, 'assemble_min')"):
        assert call in FINALIZE, call
    assert "leftForLib > (C.ASSEMBLE + C.CALLBACK_MIN)" in FINALIZE, "Tier 1: 조립 뒤 Callback 최소 시간이 남을 때만 적재"
    # 2026-10-04 최종 지시 §4: 조립 상한은 Layer A 결과 읽기·검문 → Layer B 적재·조립 → raw 검문을 **모두** 감싼다; 초과 뒤 최소 경로는 ASSEMBLE_MIN
    i_bound = FINALIZE.index("seBounded(C.ASSEMBLE, 'assemble')")
    assert i_bound < FINALIZE.index("readJSON file: 'gather_finalize_report.json'") < FINALIZE.index("seLoadFinalizeLib()") < FINALIZE.index("layerB = 'unavailable'") < FINALIZE.index("if (!assembled)")
    assert FINALIZE.index("if (!assembled)") < FINALIZE.index("seBounded(C.ASSEMBLE_MIN, 'assemble_min')") < FINALIZE.index("int accepted = ips.size()")
    assert "damage << 'assemble_timeout'" in FINALIZE and "damage << 'assemble_min_timeout'" in FINALIZE and "layerA = 'timeout'" in FINALIZE
    for key in ("PRESERVE_STEP    : 30", "ASSEMBLE_MIN     : 20", "RECOVER          : 30", "ASSEMBLE         : 60"):
        assert key in TEXT, key
    # 보존 단계도 같은 상한 helper — archive · stash 각각 (합 60 = gather_budget.sh POST_SEC 의 ARCHIVE_STASH 60)
    assert "seBounded(C.PRESERVE_STEP, 'archive')" in PRESERVE and "seBounded(C.PRESERVE_STEP, 'stash')" in PRESERVE
    assert "Map C = seConstants()" in PRESERVE
    assert "|| exit 90" in GATHER, "venv 실패 = prep_failed"
    assert "gather_output.json 미생성/0바이트" not in TEXT, "0바이트는 FAILURE 로 끊지 않고 finalizer 가 보충한다"


@pytest.mark.source_text
def test_bounded_recovery_approval_signatures_are_documented_in_comments():
    """승인 후보 4 시그니처는 **코드 주석**에 남긴다 — 생성 production tree 에는 주석이 없으므로 G14 overlay 에서는 제외(source_text; CI #3 G14 실패 원인)."""
    for sig in ("FlowInterruptedException getCauses", "ExceededTimeout getNodeId", "FlowNode getEnclosingBlocks", "FlowNode getId"):
        assert sig in TEXT, f"승인 시그니처 목록을 코드 주석에 남긴다: {sig}"


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
    assert post.index("archiveArtifacts(") < post.index("archived = done") < re.search(r"^\s*stash\($", post, re.M).start() < post.index("stashed = done")
    assert post.count("seBounded(C.PRESERVE_STEP, ") == 2, "archive · stash 각각 Tier 2 상한(기본 off = 상한 없음)"
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
    assert FINALIZE.count("seFilterEnvelopeLines(") == 3, "Layer A 결과 · raw fallback · 조립 상한 초과 뒤 최소 경로 — 셋 다 같은 검문"
    assert "layerA = 'report_unreadable'" in FINALIZE and "layerA = 'incomplete'" in FINALIZE
    i_read = FINALIZE.index("readJSON file: 'gather_finalize_report.json'")
    seg = FINALIZE[i_read: i_read + 1800]
    assert "catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)" in seg, "파싱 실패 복구와 interruption 재전파를 분리"
    assert "unrecovered = picked.missing" in FINALIZE
    for key in ("unrecovered: unrecovered", "damage: damage", "by_origin: (report.by_origin ?: null)",
                "recovery_limited: (layerB == 'unavailable' && lineCount != accepted)"):
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
    assert "seTrusted('scripts/jenkins/se_finalize.groovy')" in TEXT and "return load('se_finalize.groovy')" in TEXT
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


def test_trusted_reads_are_identified_in_the_console():
    """2026-10-04 최종 지시 §5: 모든 readTrusted 는 seTrusted() 를 지나 `[Trusted] <path> len=N jhash=H` 를 남긴다 — 빌드가 실제로 읽은 정본
    내용을 후보 revision 과 대조하기 위한 식별값(Java String.hashCode; sandbox 는 digest API 를 허용하지 않는다). 추가 checkout · 도구 의존 없음."""
    assert TEXT.count("readTrusted(") == 1 and "String text = readTrusted(path)" in TEXT, "readTrusted 호출은 seTrusted 안 한 곳"
    assert TEXT.count("seTrusted('") == 4, "locations.yml · se_finalize.groovy · failure_reasons.yml · supported_sections.yml"
    assert 'echo "[Trusted] ${path} len=${text.length()} jhash=${text.hashCode()}"' in TEXT
    assert "MessageDigest.getInstance" not in TEXT and "java.util.zip.CRC32" not in TEXT, "sandbox 비허용 API 를 운영 파이프라인에 두지 않는다(주석 언급은 무방)"
    assert "checkout scm" not in _stage("Resolve Location") and "checkout(" not in _method("String seTrusted")


def test_progress_and_checkpoint_env_wired_for_json_only():
    for var in ("ANSIBLE_JSON_MANIFEST_FILE", "ANSIBLE_JSON_PROGRESS_FILE", "ANSIBLE_JSON_CHECKPOINT_FILE"):
        assert var in GATHER, var


def test_file_has_lf_line_endings():
    assert b"\r\n" not in JENKINSFILE.read_bytes()

def test_recovery_source_is_the_medium_and_unarchive_is_per_file():
    """Harness #30/#34 (2026-10-04): 한 mapping 에 없는 파일이 섞이면 unarchive 가 통째로 실패해 꺼낸 파일이 source 에 반영되지 않았고,
    checkpoint 만 돌려받은 경우(Layer A 실패)도 source 가 none 이었다. source = 회수 매체, by_origin = 데이터 출처."""
    assert "for (String f in recoverFiles)" in FINALIZE and "unarchive mapping: [(f): f]" in FINALIZE, "파일별 unarchive"
    assert FINALIZE.count("fileExists('gather_checkpoint.jsonl')) { source = 'stash' }") == 1
    assert FINALIZE.count("fileExists('gather_checkpoint.jsonl')) { source = 'archive' }") == 1
    per_file = FINALIZE[FINALIZE.index("for (String f in recoverFiles)"):FINALIZE.index("source = 'archive'")]
    assert "FlowInterruptedException fie" in per_file and "throw fie" in per_file, "파일별 catch 도 interruption 은 재전파"
