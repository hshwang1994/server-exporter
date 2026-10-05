"""Jenkinsfile_portal — 결과 보존 · 결과 확인 · Portal 전송 · 시간 한계의 텍스트 계약 (2026-10-03 Phase 4, 2026-10-05 8차 개정).

고정하는 것
  1. 구조: stage 는 입력 확인 → 실행 위치 확인 → 서버 정보 수집 셋뿐(문서의 Validate / Resolve Location / Gather). 전송은 pipeline post{always}
     안의 '결과 확인 및 전송' 단계가 한 번 부른다. 결과 확인은 `timeout(한계){ node('built-in'){ dir('fin-<빌드>'){…} } }` 하나다.
  2. 시간 한계(8차 R3): 빌드 12시간 = 입력 확인 · 실행 위치 확인 각 5분 + 서버 정보 수집 단계 39000초 + 결과 확인 및 전송 1시간.
     실제 수집은 scripts/run_gather.sh 가 scripts/gather_budget.sh 의 한계(최대 6시간)로 실행한다. 단계 안의 짧은 제한(Tier 2 · 정체 감시)은 없다.
  3. 보존: 서버 정보 수집 post{always} 가 결과 정리 → 오래된 작업 폴더 정리 → 보관(지금 있는 파일을 이름으로, 빈 보관 불가) → 전달 →
     (이 빌드의 접수 목록 + 결과 파일을 보관했을 때만) 작업 폴더 삭제.
  4. 회수: unstash → unarchive → 접수 목록만. 정리 결과(Layer A, exit 0/2) 우선, 없으면 보충 조립(Layer B).
  5. Portal 전송(8차 R2): 남은 시간 기반, 2xx 성공, 408/429 외 4xx 중단, 시작한 시도만 시각과 함께 기록, 취소된 빌드 1회.
  6. Runner 부재: 실행 위치 확인이 error 가 아니라 outcome=no_agent → 수집 skip → 결과 확인이 접수 목록으로 보충 + 전송.
  7. Groovy 복제값(seFallbackCanon)은 정본 YAML · finalize 스크립트 상수와 같다.
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


GATHER = _stage("서버 정보 수집")
RESOLVE = _stage("실행 위치 확인")
VALIDATE = _stage("입력 확인")
FINALIZE = _method("def seFinalizeAndCallback")
FIN_IN = _method("def seFinalizeIn")
CALLBACK = _method("def seCallback")
PRESERVE = _method("def sePreserveGatherOutput")
LIB = (REPO / "scripts/jenkins/se_finalize.groovy").read_text(encoding="utf-8")
POST = TEXT[TEXT.index("    post {\n        always {"):]


def test_only_three_stages_and_no_callback_or_schema_stage():
    stages = re.findall(r"\n        stage\('([^']+)'\)", TEXT)
    assert stages == ["입력 확인", "실행 위치 확인", "서버 정보 수집"]
    assert "Validate Schema" not in TEXT and "stage('Callback')" not in TEXT
    # 결과 전송은 stage 가 아니라 post{always} 안의 표시 단계다 — 끊긴 빌드에서도 실행되고, 한 번만 돈다
    assert "stage('결과 확인 및 전송') {\n                        fin = seFinalizeAndCallback()\n                    }" in POST
    assert len(re.findall(r"(?<!def )seFinalizeAndCallback\(\)", TEXT)) == 1, "호출은 post 한 곳(정의 제외)"
    assert "seBuildSummary(fin)" in POST
    for cond in ("success {", "unstable {", "failure {", "aborted {"):
        assert cond not in POST, f"{cond} — 결과별 마지막 줄은 seBuildSummary 가 낸다"


def test_finalizer_is_one_limit_around_one_builtin_node_and_a_per_build_folder():
    """8차 R3 · R8: 결과 확인 및 전송의 한계는 하나(FINALIZER 1시간, 빌드 끝까지 남은 시간이 더 짧으면 그만큼 - 60초)이고 node 대기까지 감싼다.
    작업 위치는 빌드마다 따로(fin-<빌드 번호>) — 앞 빌드가 남긴 파일을 지우지 않는다."""
    assert len(re.findall(r"\bnode\('built-in'\)", TEXT)) == 1, "결과 확인의 node('built-in') 한 곳"
    assert "long limit = Math.max(60L, Math.min((long) C.FINALIZER, buildStart + (long) C.BUILD - tPost - 60L))" in FINALIZE
    assert "timeout(time: limit, unit: 'SECONDS') {" in FINALIZE
    assert FINALIZE.index("timeout(time: limit") < FINALIZE.index("node('built-in')") < FINALIZE.index('dir("fin-${env.BUILD_NUMBER}")')
    assert "seCleanOldFinalizerDirs(C)" in FINALIZE and FINALIZE.index("seCleanOldFinalizerDirs(C)") < FINALIZE.index('dir("fin-')
    assert "result = seFinalizeIn(C, manifestJson, ips, outcome, tPostMs, tIn, deadline)" in FINALIZE
    # 결과 확인 진입 때 Job 작업 폴더를 통째로 지우던 deleteDir 는 없다 — 지우는 것은 보관을 확인한 이 빌드의 폴더뿐
    assert "deleteDir()" not in FINALIZE
    assert FIN_IN.count("deleteDir()") == 1 and "if (finalArchived) {\n        deleteDir()" in FIN_IN


def test_no_inner_step_limits_and_no_tier2():
    """8차 R3: 단계마다 두던 30 · 60 · 120초 제한, Tier 2(SE_FINALIZER_BOUNDED + 승인 4 서명), 정체 감시는 없다."""
    for gone in ("seBounded", "SE_FINALIZER_BOUNDED", "seEnclosingIds", "seIsOwnTimeout", "PRESERVE_STEP", "ASSEMBLE_MIN", "FINALIZER_TOTAL",
                 "CALLBACK_ATTEMPT", "ABORT_ATTEMPT", "gather_watch", "SE_GATHER_WATCH", "SE_PROGRESS_DIR", "gather_heartbeat", "timeout 120 python3"):
        assert gone not in TEXT, gone
    assert TEXT.count("timeout(time:") == 5, "options 12시간 · 입력 확인 5분 · 실행 위치 확인 5분 · 수집 단계 39000초 · 결과 확인 한계"


def test_time_limits_add_up_to_the_build_limit():
    assert "timeout(time: 12, unit: 'HOURS')" in TEXT
    assert VALIDATE.count("options { timeout(time: 5, unit: 'MINUTES') }") == 1
    assert RESOLVE.count("options { timeout(time: 5, unit: 'MINUTES') }") == 1
    assert "options { timeout(time: 39000, unit: 'SECONDS') }" in GATHER
    consts = dict(re.findall(r"^\s+([A-Z_]+)\s*:\s*(\d+),", _method("Map seConstants"), re.M))
    assert int(consts["BUILD"]) == 12 * 3600
    assert int(consts["PRE"]) == 2 * 5 * 60
    assert int(consts["BUILD"]) == int(consts["PRE"]) + int(consts["STAGE"]) + int(consts["FINALIZER"]), "앞 단계가 길어도 결과 확인에 1시간이 남는다"
    assert int(consts["STAGE"]) == 39000 and int(consts["FINALIZER"]) == 3600 and int(consts["GATHER_MAX"]) == 6 * 3600
    assert int(consts["PORTAL_WAIT"]) == 600 and int(consts["PORTAL_ATTEMPTS"]) == 3


def test_retention_policy():
    assert ("buildDiscarder(logRotator(daysToKeepStr: '14', numToKeepStr: '100', artifactDaysToKeepStr: '7', artifactNumToKeepStr: '50'))"
            in TEXT)


def test_finalizer_recovers_inputs_in_order_and_prefers_layer_a():
    i_unstash = FIN_IN.index("unstash 'gather-output'")
    i_unarchive = FIN_IN.index("unarchive mapping:")
    i_layer_b = FIN_IN.index("seReconcileRaw(manifestJson")
    assert i_unstash < i_unarchive < i_layer_b
    assert "JENKINS_HOME" not in TEXT, "archive 는 unarchive step 으로만 회수한다"
    assert "rep.exit_code in [0, 2]" in FIN_IN, "Layer A 결과(exit 0/2) 우선"
    assert "layerA=${layerA}" in FIN_IN and "source=${source}" in FIN_IN


def test_finalizer_handles_no_manifest_and_builds_contract_body():
    assert "접수된 요청이 없어 Portal 로 보낼 결과가 없습니다" in FINALIZE and "return null" in FINALIZE
    for key in ('"loc":', '"deploymentEnvironmentId":', '"eventUuid":', '"gatherInfoJson":['):
        assert key in FIN_IN, key
    assert "groovy.json.JsonOutput.toJson(params.loc.trim())" in FIN_IN and "replaceAll('\\\\\\\\'" not in TEXT, "escaping 은 JsonOutput 하나"
    assert "'/api/jenkins/gather/' + params.target_type.trim()" in CALLBACK, "endpoint 계약 불변"


def test_lines_is_not_referenced_after_it_is_nulled():
    """R5 (2026-10-03): 본문 조립 뒤 `lines = null` 로 비운 다음 `lines.size()` 를 다시 부르면 정상 경로에서 NPE 가 난다."""
    i_count = FIN_IN.index("int lineCount = lines.size()")
    i_body = FIN_IN.index("lines.join(',')")
    m_null = re.search(r"^\s*lines = null\s*$", FIN_IN, re.M)
    assert m_null, "lines 를 비우는 문장이 없다"
    assert i_count < i_body < m_null.start(), "lineCount 는 본문을 만들기 전에 읽고, lines 는 본문 · 요약을 만든 뒤에 비운다"
    tail = FIN_IN[m_null.end():]
    assert not re.search(r"(?<![\w.])lines\b", tail), "lines 를 비운 뒤에는 lines 를 참조하지 않는다"
    assert "lineCount != accepted" in tail and "lines.size()" not in tail
    assert "lines: lineCount" in FIN_IN


def test_runtime_groovy_uses_only_sandbox_whitelisted_apis():
    """sandbox 허용 API 만 — JsonSlurperClassic 거부(2026-10-03 lab 실측), 시각은 Date.format(Groovy) · TimeZone.getTimeZone 만."""
    assert "JsonSlurperClassic" not in TEXT and "JsonSlurperClassic" not in LIB
    assert "new groovy.json.JsonSlurper()" in LIB
    assert "readJSON(text: params.inventory_json, returnPojo: true)" in TEXT
    show = _method("String seShowTime")
    iso = _method("String seIsoUtc")
    assert "new Date(ms).format('yyyy-MM-dd HH:mm:ss XXX')" in show and "'+00:00'" in show
    assert "new Date(ms).format(\"yyyy-MM-dd'T'HH:mm:ss.SSS'Z'\", TimeZone.getTimeZone('UTC'))" in iso
    for banned in ("SimpleDateFormat", "java.time.", "String.format(", "TimeZone.setDefault", "user.timezone"):
        assert banned not in TEXT, banned


def test_timestamper_is_optional_and_wraps_every_stage_and_post():
    """8차 R2: Timestamper 가 있으면 Job 범위로 줄 시각을 켠다. 없으면(고객사) 블록에 들어가기 전의 NoSuchMethodError 만 받아 그대로 실행한다.
    options { timestamps() } 는 플러그인이 없으면 해석 단계에서 실패하므로 쓰지 않는다."""
    ts = _method("def seTimestamped")
    assert "timestamps {" in ts and "catch (NoSuchMethodError e)" in ts and "if (entered) {" in ts and "throw e" in ts
    assert ts.index("entered = true") < ts.index("body()") < ts.index("catch (NoSuchMethodError e)")
    code_lines = [l for l in TEXT.splitlines() if not l.strip().startswith("//")]
    assert not any("timestamps()" in l for l in code_lines), "선언형 options 의 timestamps() 금지(주석 언급은 무관)"
    assert VALIDATE.count("seTimestamped {") == 1 and RESOLVE.count("seTimestamped {") == 1
    assert POST.count("seTimestamped {") == 1
    assert GATHER.count("seTimestamped {") - POST.count("seTimestamped {") == 2, "수집 단계 본문과 그 post (마지막 stage 라 _stage 가 pipeline post 까지 잡는다)"


def test_business_events_carry_time_in_the_line_body():
    """8차 R2: 수집 시작 · 끝(scripts/run_gather.sh), 결과 보존 시작 · 끝, Portal 시도 시작 · 응답 · 실패 · 대기, 미시도, 결과 확인 시작은 본문에 시각이 있다."""
    log = _method("def seLog")
    assert 'echo "[${seShowTime(seNowMs())}] ${line}"' in log
    for marker in ('seLog("[결과 보존] 시작합니다', 'seLog("[결과 보존] 끝났습니다'):
        assert marker in PRESERVE, marker
    for marker in ("번째 전송을 시작합니다", "응답을 받았습니다", "번째 전송이 실패했습니다", "초 기다린 뒤", "번째 전송을 시작하지 않았습니다"):
        assert re.search(r"seLog\(\"\[Portal 전송\][^\n]*" + re.escape(marker), CALLBACK), marker
    assert 'seLog("[결과 확인] 시작합니다' in FINALIZE
    assert re.search(r"seLog\(\"\[수집\] 중단됨:", GATHER), "중단도 시각과 함께"
    assert 'seLog("[입력 확인] 통과했습니다' in VALIDATE


def test_callback_rules_and_attempt_records():
    assert "if (left < (C.PORTAL_MIN as long)) {" in CALLBACK and "state.reason = 'no_time'" in CALLBACK
    assert "int t = (int) Math.min((long) C.PORTAL_WAIT, left - 10L)" in CALLBACK
    assert "code ==~ /2\\d\\d/" in CALLBACK and "!(code in ['408', '429'])" in CALLBACK, "결정적 4xx 는 중단, 408/429 는 재시도"
    assert "aborted ? 1 : (C.PORTAL_ATTEMPTS as int)" in CALLBACK
    # 2026-10-05 사용자 결정: 2xx 수신까지가 계약 — 응답 본문은 읽지도 기록하지도 않는다. 2xx 를 저장 완료라고 쓰지 않는다
    assert "quiet: true" in CALLBACK and "consoleLogResponseBody: false" in CALLBACK and "resp.content" not in CALLBACK
    assert "2xx 는 Portal 이 요청을 받았다는 뜻입니다" in CALLBACK and "저장 완료" not in TEXT
    # 시작한 시도만 기록한다: 시작 시각은 httpRequest 직전, 끝 · 걸린 시간은 응답(또는 예외) 뒤 — 중단(interruption)이면 끝 시각을 적지 않는다
    i_rec = CALLBACK.index("Map rec = [attempt: attempt, started_at: seIsoUtc(t0), timeout_sec: t]")
    i_http = CALLBACK.index("httpRequest(")
    i_end = CALLBACK.index("rec.ended_at = seIsoUtc(t1)")
    assert i_rec < i_http < i_end
    seg = CALLBACK[i_http:i_end]
    assert "rec.outcome = 'interrupted'" in seg and "throw fie" in seg, "중단된 시도: 응답 시각 없이 다시 던진다"
    for key in ("rec.elapsed_ms = t1 - t0", "rec.retry_wait = [started_at: seIsoUtc(seNowMs()), sec: wait]", "state.started_at = seIsoUtc(seNowMs())",
                "state.ended_at = seIsoUtc(seNowMs())", "state.attempted = (state.attempts > 0)", "rec.outcome = 'delivered'", "rec.outcome = 'refused'",
                "rec.outcome = 'failed'"):
        assert key in CALLBACK, key
    assert CALLBACK.index("if (left < (C.PORTAL_MIN as long)) {") < CALLBACK.index("Map rec = [attempt:"), "미시도에는 시도 기록(시각)을 만들지 않는다"


def test_summary_records_attempted_from_real_attempts_not_from_body():
    """8차 R2: 종전에는 남은 시간이 없어 한 번도 보내지 않았는데도 본문이 있다는 이유로 attempted=true 를 적었다."""
    record = _method("Map seCallbackRecord")
    assert "attempted: (cb.attempted == true)" in record and "tries: (cb.tries ?: [])" in record
    assert "summary.callback = seCallbackRecord(cb)" in FIN_IN
    assert "attempted: (body != null)" not in TEXT and "attempted: (cb.attempted == true)" in FIN_IN
    assert "warnings << ((cb.attempted == true) ? 'callback_failed' : 'callback_not_attempted')" in FIN_IN
    # 전송 중 중단: 그때까지의 기록을 요약에 남기고(가능하면 보관) 다시 던진다
    seg = FIN_IN[FIN_IN.index("seCallback(body, deadline, C, cb)"):FIN_IN.index("boolean delivered = (cb.delivered == true)")]
    assert "cb.interrupted = true" in seg and "summary.callback = seCallbackRecord(cb)" in seg and "throw fie" in seg


def test_gather_runs_through_run_gather_with_the_budget_limit():
    assert GATHER.count("bash scripts/gather_budget.sh") == 1, "한계는 ansible 직전에 한 번 계산한다"
    assert "label: '수집 실행 한계 계산'" in GATHER
    assert GATHER.index("ADDON_REPO_URL") < GATHER.index("label: '수집 실행 한계 계산'") < GATHER.index("scripts/run_gather.sh")
    assert ('bash "\\${WORKSPACE}/scripts/run_gather.sh" "${playbook}" "${inventory}" "${exec.forks}" "${exec.limit}" '
            '"${env.SE_LOCATION}" "${addonDir ? \'true\' : \'false\'}" "${hostCount}"') in GATHER
    assert not re.search(r'ansible-playbook\s+"', GATHER) and "timeout --signal" not in GATHER, "ansible-playbook 실행 · 한계 집행은 run_gather.sh 한 곳"
    assert "unset SE_MEM_AVAILABLE_MB" in GATHER and "SE_FORCE_SEC" not in GATHER
    assert "env.SE_GATHER_OUTCOME = 'not_started_budget'" in GATHER and "if (!exec.start)" in GATHER
    # R6: 단계 기준점은 Runner 를 얻기 전(실행 위치 확인 끝)
    assert 'env.SE_STAGE_START_EPOCH = "${seNowSec()}"' in RESOLVE and RESOLVE.index("nodesByLabel(") < RESOLVE.index("env.SE_STAGE_START_EPOCH =")
    assert 'env.SE_STAGE_START_EPOCH = "${seNowSec()}"' not in GATHER
    assert 'env.SE_NODE_ENTER_EPOCH = "${seNowSec()}"' in GATHER and GATHER.index("env.SE_NODE_ENTER_EPOCH") < GATHER.index("writeFile(file: 'gather_manifest.json'")
    for field in ("pre=${preSec}s", "wait_checkout=${waitSec}s", "prep=${prepSec}s"):
        assert GATHER.count(field) == 1, field
    assert "env.SE_BUILD_START_EPOCH = " in VALIDATE
    # 6시간을 다 주지 못하면 그 사실을 남긴다(빌드 남은 시간이 기준)
    assert "if (exec.limit_source == 'build_limit') {" in GATHER and "을 보장하지 못합니다" in GATHER


def test_rc_to_outcome_uses_the_real_timeout_record():
    """8차 R7: 종료 코드만으로 한계 도달을 단정하지 않는다 — run_gather.sh 가 실제 실행 시간으로 확인한 timed_out 과 함께 본다.
    판정은 최상위 함수 seGatherOutcome 하나 — 서버 정보 수집 단계와 Harness(gather_limit_preserve)가 같은 함수를 부른다(8차 R1)."""
    fn = TEXT[TEXT.index("@NonCPS\nMap seGatherOutcome(int rc, Map run, String limitSource) {"):]
    fn = fn[:fn.index("\n}\n") + 3]
    assert "boolean timedOut = (run != null) ? (run.timed_out == true) : (rc in [124, 137])" in fn
    assert "String reason = limitSource ?: 'gather_limit'" in fn
    for cond, outcome, reason in (("rc in [0, 2, 4, 8]", "completed", "''"), ("timedOut && rc == 124", "timeout", "reason"),
                                  ("timedOut && rc == 137", "timeout_killed", "reason"), ("rc == 90", "prep_failed", "''")):
        assert f"if ({cond}) {{ return [outcome: '{outcome}', limit_reason: {reason}] }}" in fn, outcome
    assert fn.rstrip().endswith("return [outcome: 'failed_run', limit_reason: '']\n}"), "한계 전 KILL(137)은 다른 원인 — failed_run"
    assert "Map oc = seGatherOutcome(rc as int, run, exec.limit_source?.toString())" in GATHER
    assert "env.SE_GATHER_OUTCOME = oc.outcome" in GATHER and "env.SE_GATHER_LIMIT_REASON = limitReason" in GATHER
    assert "env.SE_GATHER_OUTCOME = 'interrupted_unknown'" in GATHER
    assert "env.SE_GATHER_OUTCOME = 'aborted'" in GATHER and "env.SE_GATHER_OUTCOME = 'not_started_memory'" in GATHER
    harness = (Path(__file__).resolve().parents[2] / "tests" / "jenkins" / "harness" / "Jenkinsfile_harness").read_text(encoding="utf-8")
    assert "lib.seGatherOutcome(grc, run, 'gather_limit')" in harness


def test_interruptions_are_recorded_and_rethrown_not_swallowed():
    assert "catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE', catchInterruptions: false)" in GATHER
    i_abort = GATHER.index("env.SE_GATHER_OUTCOME = 'aborted'")
    before = GATHER[max(0, i_abort - 1200): i_abort]
    after = GATHER[i_abort: i_abort + 900]
    assert "catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)" in before
    assert "throw fie" in after and "env.SE_GATHER_INTERRUPTION = stageLimit ? 'stage_limit' : 'user_or_other'" in after
    canon = _method("def seLoadCanon")
    assert canon.index("FlowInterruptedException fie") < canon.index("catch (Exception e)")
    addon = GATHER[GATHER.index("def fetchAddon"):GATHER.index("if (!problem)")]
    assert addon.index("FlowInterruptedException fie") < addon.index("catch (Exception e)")


def test_gather_post_preserves_then_deletes_only_when_required_files_were_archived():
    """8차 R8: 보관 성공은 예외가 없었다는 뜻만이 아니다 — 지금 있는 파일을 이름으로 지정하고 빈 보관을 실패로 둔다.
    이 빌드의 접수 목록과 결과 파일을 보관했을 때만 작업 폴더(와 그 @tmp)를 지운다."""
    assert re.search(r"always \{\s*script \{\s*seTimestamped \{\s*sePreserveGatherOutput\(\)", GATHER)
    i_a = PRESERVE.index("scripts/finalize_gather_output.py")
    i_clean = PRESERVE.index("seCleanOldWorkspaces()")
    i_arch = PRESERVE.index("archiveArtifacts(")
    i_stash = re.search(r"^\s*stash\(name: 'gather-output'", PRESERVE, re.M).start()
    i_del = PRESERVE.index("deleteDir()")
    assert i_a < i_clean < i_arch < i_stash < i_del
    assert "archiveArtifacts(artifacts: archiveList.join(','), allowEmptyArchive: false, fingerprint: false)" in PRESERVE
    assert "allowEmptyArchive: true" not in PRESERVE
    assert "for (String n in names) {\n        if (fileExists(n)) { present << n }" in PRESERVE, "지금 있는 파일만 이름으로"
    assert "boolean preserved = archived && manifestOk && hasResult" in PRESERVE and "if (preserved) {\n        deleteDir()" in PRESERVE
    assert "m?.build?.number?.toString() == env.BUILD_NUMBER" in PRESERVE
    assert 'dir("${env.WORKSPACE}@tmp") { deleteDir() }' in PRESERVE
    assert "보존을 확인하지 못해 작업 폴더를 지우지 않고 남깁니다" in PRESERVE
    for name in ("gather_final.jsonl", "gather_finalize_report.json", "gather_progress.jsonl", "gather_run.json", "workspace_cleanup.json"):
        assert f"'{name}'" in PRESERVE, name
    assert "timeout" not in PRESERVE.lower().replace("timeout_killed", ""), "결과 보존에 단계 제한이 없다"


def test_preserve_steps_are_independent():
    assert PRESERVE.count("catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)") >= 5
    assert PRESERVE.count("throw fie") >= 5
    for flag in ("SE_PRESERVE_ARCHIVED", "SE_PRESERVE_STASHED", "SE_PRESERVE_MANIFEST", "SE_PRESERVE_HASRESULT", "SE_PRESERVE_LAYER_A"):
        assert f"env.{flag}" in PRESERVE, flag
    assert "결과를 보존하지 못했습니다. 보관과 전달이 모두 실패했습니다." in PRESERVE
    assert "preserve: [layerA: env.SE_PRESERVE_LAYER_A" in FIN_IN
    assert TEXT.count("deleteDir()") == 4, "preserve 의 작업 폴더 · @tmp, 결과 확인 폴더, controller 정리의 오래된 폴더"


def test_workspace_markers_and_cleanup_wiring():
    """8차 R8: 작업 폴더 소유 기록(.se_workspace.json)을 수집 단계 첫 동작으로 쓰고, 보존 뒤 끝 시각 · 보존 여부로 다시 쓴다.
    정리는 scripts/workspace_cleanup.py(Runner) 와 seCleanOldFinalizerDirs(controller, pipeline step 만) — 사용자 입력은 없다."""
    assert GATHER.index("writeFile(file: '.se_workspace.json'") < GATHER.index("sh label: '이전 실행의 결과 파일 정리'")
    assert "ended_epoch: seNowSec(), preserved: preserved" in PRESERVE
    clean = _method("def seCleanOldWorkspaces")
    assert "python3 scripts/workspace_cleanup.py --current" in clean and "--keep-days ${C.KEEP_DAYS} --every-sec 86400" in clean
    assert "exit 0" in clean and "returnStatus: true" in clean, "정리 실패가 빌드 결과를 바꾸지 않는다"
    fin = _method("def seCleanOldFinalizerDirs")
    assert "findFiles(glob: 'fin-*/.se_fin.json')" in fin and "if (info.archived == true) {" in fin and "kept << d" in fin
    assert "now - ended < (C.KEEP_DAYS as long) * 86400L" in fin and "if (d == mine" in fin
    assert "sh(" not in fin and "python" not in fin, "controller 에 Python 을 요구하지 않는다"


def test_finalizer_validates_lines_and_records_damage():
    helper = _method("Map seFilterEnvelopeLines")
    assert "new groovy.json.JsonSlurper()" in helper and "missing" in helper
    assert "seEnvelopeShapeReason(obj, channel, accepted) != null" in helper and "keys13" not in helper
    assert FIN_IN.count("seFilterEnvelopeLines(") == 3, "Layer A 결과 · Layer B 결과 · raw — 셋 다 같은 검문"
    assert "layerA = 'report_unreadable'" in FIN_IN and "layerA = 'incomplete'" in FIN_IN
    i_read = FIN_IN.index("readJSON file: 'gather_finalize_report.json'")
    seg = FIN_IN[i_read: i_read + 1800]
    assert "catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)" in seg
    assert "unrecovered = picked.missing" in FIN_IN
    for key in ("unrecovered: unrecovered", "damage: damage", "by_origin: (report.by_origin ?: null)",
                "recovery_limited: (layerB == 'unavailable' && lineCount != accepted)"):
        assert key in FIN_IN, key


def test_no_agent_is_accepted_then_failed_not_a_build_error():
    assert "env.SE_GATHER_OUTCOME = 'no_agent'" in RESOLVE
    assert "error \"[실행 위치] 라벨" not in RESOLVE
    assert "when { expression { env.SE_GATHER_OUTCOME != 'no_agent' } }" in GATHER
    assert 'unstable("[실행 위치] 온라인 노드가 없습니다' in RESOLVE


def test_portal_loads_layer_b_library_instead_of_defining_it():
    for sig in ("Map seFallbackCanon()", "String seJsonString(", "Map seReconcileRaw("):
        assert sig not in TEXT, f"Jenkinsfile_portal 에 {sig} 사본이 있다 — 정본은 se_finalize.groovy"
    assert "seTrusted('scripts/jenkins/se_finalize.groovy')" in TEXT and "return load('se_finalize.groovy')" in TEXT
    assert FINALIZE.index("node('built-in')") < FINALIZE.index("seFinalizeIn(")
    assert "lib.seReconcileRaw(manifestJson, outText, cpText, seLoadCanon(lib), outcome)" in FIN_IN
    assert "layerB = 'unavailable'" in FIN_IN and "layerB == 'unavailable'" in FIN_IN
    assert "FlowInterruptedException fie" in TEXT[TEXT.index("def seLoadFinalizeLib()"):TEXT.index("def seLoadCanon(")]


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
    assert f"emitFailed: '{emit}'" in canon


def test_trusted_reads_are_identified_in_the_console():
    assert TEXT.count("readTrusted(") == 1 and "String text = readTrusted(path)" in TEXT
    assert TEXT.count("seTrusted('") == 4, "locations.yml · se_finalize.groovy · failure_reasons.yml · supported_sections.yml"
    assert 'echo "[Trusted] ${path} len=${text.length()} jhash=${text.hashCode()}"' in TEXT
    assert "MessageDigest.getInstance" not in TEXT and "java.util.zip.CRC32" not in TEXT
    assert "checkout scm" not in RESOLVE and "checkout(" not in _method("String seTrusted")


def test_progress_and_checkpoint_env_wired_for_json_only():
    for var in ("ANSIBLE_JSON_MANIFEST_FILE", "ANSIBLE_JSON_PROGRESS_FILE", "ANSIBLE_JSON_CHECKPOINT_FILE"):
        assert var in GATHER, var


def test_file_has_lf_line_endings():
    assert b"\r\n" not in JENKINSFILE.read_bytes()


def test_recovery_source_is_the_medium_and_unarchive_is_per_file():
    assert "for (String f in recoverFiles)" in FIN_IN and "unarchive mapping: [(f): f]" in FIN_IN
    assert FIN_IN.count("fileExists('gather_checkpoint.jsonl')) { source = 'stash' }") == 1
    assert FIN_IN.count("fileExists('gather_checkpoint.jsonl')) { source = 'archive' }") == 1
    per_file = FIN_IN[FIN_IN.index("for (String f in recoverFiles)"):FIN_IN.index("source = 'archive'")]
    assert "FlowInterruptedException fie" in per_file and "throw fie" in per_file


def test_every_shell_step_has_a_label():
    calls = [m.group(0).lstrip(" \t=(:") for m in re.finditer(r"(?:^|[\s=(:])sh(?=[( ])[^\n]*", TEXT, re.M)]
    steps = [c for c in calls if ("script:" in c or c.startswith('sh "') or c.startswith("sh '") or c.startswith('sh """'))]
    assert steps, "sh step 이 없다"
    unlabeled = [c[:80] for c in steps if "label:" not in c]
    assert unlabeled == [], unlabeled
    for label in ("결과 정리 (서버마다 결과 한 줄)", "오래된 작업 폴더 정리 (하루 한 번)", "이전 실행의 결과 파일 정리", "추가 수집(Add-on) 저장소 받기",
                  "추가 수집(Add-on) 파일 검사", "수집 실행 한계 계산", "서버 정보 수집 (ansible-playbook)"):
        assert f"label: '{label}'" in TEXT, label
    assert "Layer A)" not in TEXT, "사람이 보는 이름에 내부 용어를 쓰지 않는다"


def test_summary_records_status_counts_times_limits_and_warnings():
    assert "status_counts: [success: (statusCounts.success ?: 0), partial: (statusCounts.partial ?: 0)," in FIN_IN
    assert "failed: (statusCounts.failed ?: 0), missing: Math.max(0, accepted - lineCount)]" in FIN_IN
    for key in ("times: [build_started_at:", "gather_started_at: (env.SE_GATHER_STARTED_AT ?: null)", "finalize_started_at: seIsoUtc(tPostMs)",
                "limits: [build_sec: C.BUILD", "gather_limit_source: (env.SE_GATHER_LIMIT_SOURCE ?: null)", "gather_run: run",
                "interruption: (env.SE_GATHER_INTERRUPTION ?: null)"):
        assert key in FIN_IN, key
    assert "summary.warnings = warnings" in FIN_IN
    for code in ("'callback_failed'", "'callback_not_attempted'", "'body_not_saved'", "'count_mismatch'", "'filled'", '"outcome_${outcome}"',
                 "'layer_b_unavailable'", "'preserve_failed'", "'preserve_archive_failed'"):
        assert code in FIN_IN, code
    assert 'for (String w in warnTexts) { echo "[경고] ${w}" }' in FIN_IN
    assert FIN_IN.count("unstable(") == 2, "전송 실패(또는 미시도) · 경고 중 하나만"
    assert "if (!w.startsWith('preserve_')) { finalizerWarn = true }" in FIN_IN


def test_result_lines_and_links_are_for_people():
    assert 'echo "[결과] 요청 ${accepted}대: 성공 ${sc.success}, 부분 성공 ${sc.partial}, 실패 ${sc.failed}' in FIN_IN
    i_arch = FIN_IN.index("archiveArtifacts artifacts: finalFiles.join(','), allowEmptyArchive: false")
    i_links = FIN_IN.index('echo "[결과 파일] ${f[0]}: ${base ? base + \'artifact/\' + f[1] : f[1]}"')
    i_del = FIN_IN.rindex("deleteDir()")
    assert i_arch < i_links < i_del, "보관한 뒤에 링크하고, 링크한 뒤에 지운다"
    summary_fn = _method("def seBuildSummary")
    assert "currentBuild.currentResult" in summary_fn and "'ABORTED': '중단'" in summary_fn
    assert "durationString" not in summary_fn and "seShowTime(startMs)" in summary_fn and "seDuration(took)" in summary_fn
    assert "Portal 이 요청을 받았다는 뜻입니다" in summary_fn and "delivered_show" in summary_fn


def test_timeout_end_is_explained_with_limit_runtime_counts_preservation_and_delivery():
    """8차 R7: 'rc=124 outcome=timeout' 만 남기지 않는다 — 어떤 한계였는지, 얼마나 실행했는지, 끝난 · 끝나지 않은 대상 수, 보존 · 전송 결과."""
    explain = _method("def seExplainGatherEnd")
    assert "if (outcome == 'completed') { return }" in explain
    for part in ("seLimitText(summary.limit_reason?.toString())", "run?.ran_sec", "끝난 대상 ${done}대", "끝나지 않은 대상 ${partialCp + filled}대",
                 "[수집 종료] 결과 보존:", "Portal 전송: ${send}"):
        assert part in explain, part
    assert "seExplainGatherEnd(C, outcome, summary, bo, kept, filled, delivered, cb)" in FIN_IN


def test_build_name_marks_count_only():
    assert 'currentBuild.displayName = "#${env.BUILD_NUMBER} ${params.target_type.trim()} ${acceptedIps.size()}대"' in VALIDATE
    assert "[시험:" not in TEXT and "testTags" not in TEXT
    assert "currentBuild.description" not in TEXT


def test_callback_url_with_credentials_is_refused_without_echoing_it():
    i_cred = VALIDATE.index("if (cbUrl ==~ /(?is)^[a-z][a-z0-9+.-]*:\\/\\/[^\\/?#]*@.*/) {")
    assert i_cred < VALIDATE.index("cbUrl.startsWith('http://')") < VALIDATE.index('echo "[입력 확인] 결과를 보낼 주소: ${cbUrl}"')
    line = VALIDATE[i_cred: VALIDATE.index("\n", VALIDATE.index("error ", i_cred))]
    assert "${cbUrl}" not in line and "params.callbackUrl" not in line
    pat = re.compile(r"(?is)^[a-z][a-z0-9+.-]*://[^/?#]*@.*")
    for bad in ("http://u:p@portal:8080", "HTTPS://user@portal/x", "http://u:p@h\n/x", "ftp://a:b@h"):
        assert pat.match(bad), bad
    for ok in ("http://portal.example.com", "https://portal:8443/api?mail=a@b", "http://10.0.0.1:8080/p#x@y"):
        assert not pat.match(ok), ok


def test_operator_lines_are_plain_sentences():
    """8차 R7: 사람이 읽는 줄(echo · seLog · error · unstable 문자열)에 긴 대시 · 가운데점 · 화살표 · 상자 선을 쓰지 않는다(코드 주석은 무관)."""
    bad = []
    for no, line in enumerate(TEXT.split("\n"), 1):
        code = line.strip()
        if code.startswith("//"):
            continue
        m = re.search(r"\b(echo|seLog|error|unstable)\s*\(?\s*(['\"])", line)
        if m and re.search(r"[—·→─]", line[m.start():]):
            bad.append((no, code[:100]))
    assert bad == [], bad
    assert "'interrupted_unknown': '수집 단계를 마치지 못함(" in TEXT
    assert "code == '408'" in CALLBACK and "요청 도구는 연결 실패도 408 로 표시합니다" in CALLBACK


def test_gather_end_does_not_call_a_missing_preservation_a_failure():
    """2026-10-06 (main #252 관측): 실행 위치 확인에서 거부돼 수집 단계가 돌지 않은 빌드는 보존 기록이 없다 — "결과 보존: 실패" 로 적지 않는다."""
    fn = TEXT[TEXT.index("def seExplainGatherEnd("):]
    fn = fn[:fn.index("\n}\n") + 3]
    assert "String archivedFlag = (summary.preserve?.archived ?: '').toString()" in fn
    assert "!(archivedFlag in ['true', 'false']) ? '수집 단계가 실행되지 않아 보존할 결과가 없습니다'" in fn
    assert "(archivedFlag == 'true') ? '완료'" in fn and "'보관 실패, 전달로 받음'" in fn


def test_aborted_gather_still_reports_its_runtime():
    """2026-10-06 (main #245 관측): 취소로 끊긴 수집은 실행 기록을 읽기 전이라 "실행 시간 기록 없음" 이었다 — 시작 시각(초)으로 실행 시간을 남긴다.
    수집을 시작하지 않은 빌드(실행 위치 확인 실패)는 "수집을 시작하지 않았습니다"."""
    assert 'env.SE_GATHER_STARTED_EPOCH = "${(long) (gatherStartMs / 1000L)}"' in GATHER
    assert "env.SE_GATHER_RAN_SEC = \"${Math.max(0L, seNowSec() - (env.SE_GATHER_STARTED_EPOCH as long))}\"" in GATHER
    i_catch = GATHER.index("catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)")
    assert GATHER.index("env.SE_GATHER_RAN_SEC =") > i_catch, "취소 경로에서 남긴다"
    fn = TEXT[TEXT.index("def seExplainGatherEnd("):]
    fn = fn[:fn.index("\n}\n") + 3]
    assert "String ranSec = (run?.ran_sec != null) ? run.ran_sec.toString() : (env.SE_GATHER_RAN_SEC ?: '')" in fn
    assert "'수집을 시작하지 않았습니다'" in fn

