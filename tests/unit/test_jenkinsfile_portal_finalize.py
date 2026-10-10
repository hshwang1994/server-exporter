"""Jenkinsfile_portal — 결과 보존 · 결과 확인 · Portal 전송 · 시간 한계의 텍스트 계약 (2026-10-03 Phase 4, 2026-10-05 8차, 2026-10-06 9차 개정).

고정하는 것
  1. 구조: stage 는 입력 확인 → 실행 위치 확인 → 서버 정보 수집 셋뿐(문서의 Validate / Resolve Location / Gather). 전송은 pipeline post{always}
     안의 '결과 확인 및 전송' 단계가 한 번 부른다. 결과 확인은 seWithNode('built-in'){ timeout(1시간){ dir('fin-<빌드>'){…} } } 하나다.
  2. 시간 한계(9차): 빌드 전체 · 수집 단계 timeout 은 없다. 실행 기반(Runner · 결과 처리 노드) 대기 합 72시간, 실제 수집 누적 6시간
     (scripts/gather_state.py 가 시도마다 남은 한계를 정한다), 시도 하나의 실행 한계(node 를 얻은 뒤), 결과 확인 및 전송 1시간(노드를 얻은 뒤).
     단계 안의 짧은 제한(Tier 2 · 정체 감시)은 없다.
  3. 보존: 마지막 시도가 결과 정리 → 오래된 작업 폴더 정리 → 보관(지금 있는 파일을 이름으로, 빈 보관 불가) → 전달 →
     (이 빌드의 접수 목록 + 결과 파일을 보관했을 때만) 작업 폴더 삭제. 실행 기반 장애로 다시 시도하기 전에는 원본만 전달한다.
  4. 회수(C1 2026-10-10): 매체마다 격리 폴더(rec-<진입>/stash · archive). 마지막 보존의 전달이 확인되고 정리 결과가 완결이면 stash, 아니면
     빌드에 저장된 파일도 받아 두 후보를 같은 검문으로 평가해 고른다. 정리 결과(Layer A, exit 0/2) 우선, 없으면 보충 조립(Layer B).
  5. Portal 전송(8차 R2): 남은 시간 기반, 2xx 성공, 408/429 외 4xx 중단, 시작한 시도만 시각과 함께 기록, 취소된 빌드 1회.
  6. 등록된 Runner 없음: 실행 위치 확인이 outcome=config_error 를 적고 FAILURE — 결과 확인이 접수 목록으로 보충 + 전송한다.
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
    start = TEXT.index(name if name.endswith("(") else f"{name}(")
    start = TEXT.rfind("\n", 0, start) + 1
    nxt = re.search(r"\n(?:@NonCPS\n)?(?:def |Map |String |boolean |long |List |pipeline \{)", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


GATHER = _stage("서버 정보 수집")
BODY = _method("def seAttemptBody")
ATTEMPT = _method("def seAttempt(")
STAGE_FN = _method("def seGatherStage")
LOOP = _method("def seGatherLoop")
WITH_NODE = _method("def seWithNode")
ADDON = _method("String seAddonPrepare")
RESOLVE = _stage("실행 위치 확인")
VALIDATE = _stage("입력 확인")
FINALIZE = _method("def seFinalizeAndCallback")
FIN_IN = _method("def seFinalizeIn")
REC_STASH = _method("Map seRecoverStash")
REC_ARCH = _method("Map seRecoverArchive")
EVAL = _method("Map seEvalCandidate")
CHOOSE = _method("String seChooseMedium")
FIN_LIB = _method("def seFinLib")
CALLBACK = _method("def seCallback")
PRESERVE = _method("def sePreserveGatherOutput")
PREP = _method("def sePrepareWorkspace")
READ = _method("Map seReadJsonFile")
LIB = (REPO / "scripts/jenkins/se_finalize.groovy").read_text(encoding="utf-8")
POST = TEXT[TEXT.index("    post {\n        always {"):]


def test_only_three_stages_and_no_callback_or_schema_stage():
    stages = re.findall(r"\n        stage\('([^']+)'\)", TEXT)
    assert stages == ["입력 확인", "실행 위치 확인", "서버 정보 수집"]
    assert "Validate Schema" not in TEXT and "stage('Callback')" not in TEXT
    # 결과 전송은 stage 가 아니라 post{always} 안의 표시 단계다 — 끊긴 빌드에서도 실행되고, 한 번만 돈다
    assert "stage('결과 확인 및 전송') {\n                            fin = seFinalizeAndCallback()\n                        }" in POST
    # 10차 R1: 결과 확인이 중단돼도 빌드 끝 요약을 남긴다
    assert POST.index("try {") < POST.index("stage('결과 확인 및 전송')") < POST.index("} finally {") < POST.index("seBuildSummary(fin)")
    assert len(re.findall(r"(?<!def )seFinalizeAndCallback\(\)", TEXT)) == 1, "호출은 post 한 곳(정의 제외)"
    assert "seBuildSummary(fin)" in POST
    for cond in ("success {", "unstable {", "failure {", "aborted {"):
        assert cond not in POST, f"{cond} — 결과별 마지막 줄은 seBuildSummary 가 낸다"


def test_finalizer_waits_for_the_builtin_node_then_one_limit_in_a_per_build_folder():
    """9차 W07 · 8차 R8 · 10차 R1: 결과 처리 노드(built-in)도 실행 기반이다 — 이 빌드의 실행 기반 대기 합(72시간) 안에서 Jenkins queue 로 기다리고
    (취소된 빌드는 ABORT_NODE_WAIT 합까지만), 노드를 얻은 뒤부터 FINALIZER(1시간, 재진입 합) 하나로 감싼다. 작업 위치는 빌드마다 따로(fin-<빌드 번호>).
    실행 기반 오류로 끊기면(agent_lost) 같은 빌드 안에서 노드를 다시 기다려 이어서 처리한다 — 종전에는 결과 없이 SUCCESS 로 끝날 수 있었다."""
    assert "Map r = seWithNode('built-in', infra, fs.entries ? '결과 처리 노드 복구 대기' : '결과 처리 노드', backdate, cap, { Map rr ->" in FINALIZE
    assert "boolean aborted = (currentBuild.result == 'ABORTED')" in FINALIZE
    assert "while (fs.result == null) {" in FINALIZE
    assert FINALIZE.index("seWithNode('built-in'") < FINALIZE.index("timeout(time: Math.max(1L, (long) (leftMs / 1000L)), unit: 'SECONDS') {") < FINALIZE.index('dir("fin-${env.BUILD_NUMBER}")')
    assert "long tInMs = seNowMs()" in FINALIZE and FINALIZE.index("long tInMs = seNowMs()") < FINALIZE.index("timeout(time: Math.max(1L"), "노드를 기다린 시간은 넣지 않는다"
    assert "seCleanOldFinalizerDirs(C)" in FINALIZE and FINALIZE.index("seCleanOldFinalizerDirs(C)") < FINALIZE.index('dir("fin-')
    assert "fs.result = seFinalizeIn(C, manifestJson, ips, outcome, tPostMs, tIn, tIn + (long) (leftMs / 1000L), infra, fs)" in FINALIZE
    # 재진입: 감지 시각부터 다시 기다린다(앞당기지 않는다). 같은 단계에서 진척 없이 반복되면 쉰다(대기 합에 넣는다). 취소는 삼키지 않는다
    lost = FINALIZE[FINALIZE.index("if (r.state != 'agent_lost') { stop = 'unknown'; break }"):]
    assert "waitFrom = lostAt" in lost and "fs.lost << [at: seIsoUtc(lostAt), error: r.error, mark: fs.mark]" in lost
    assert "seInfraPause(infra, backoff," in lost and "lastMark == fs.mark" in lost
    assert "if (r.state == 'expired') { stop = 'expired'; break }" in FINALIZE
    abort = FINALIZE[FINALIZE.index("} catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie) {"):]
    assert "seCbState(fs.cb)" in abort and "throw fie" in abort
    assert "return seFinalizeIncomplete(C, fs, ips, stop)" in FINALIZE and "return null" in FINALIZE, "null 은 접수되지 않은 요청에만"
    # 끝내 처리하지 못했을 때: 보내지 못했으면 FAILURE, 보냈지만 마무리만 못 했으면 UNSTABLE — 보존 위치를 적는다
    inc = _method("Map seFinalizeIncomplete")
    assert "currentBuild.result = 'FAILURE'" in inc and "unstable(" in inc and "'finalize_node_unavailable'" in inc and "stash" in inc
    assert "incomplete: true" in inc and "callback_body.json" in inc
    # 결과 확인 진입 때 Job 작업 폴더를 통째로 지우던 deleteDir 는 없다 — 지우는 것은 보관을 확인한 이 빌드의 폴더뿐
    assert "deleteDir()" not in FINALIZE
    assert FIN_IN.count("deleteDir()") == 1 and "if (finalArchived) {\n        deleteDir()" in FIN_IN


def test_finalizer_reentry_does_not_resend_a_confirmed_delivery_or_restart_the_attempt_count():
    """10차 R1: 전송 기록(fs.cb)은 재진입해도 이어진다. 2xx 를 받은 전송은 다시 보내지 않고, 확인하지 못한 전송은 남은 횟수만 쓴다."""
    seg = FIN_IN[FIN_IN.index("Map cb = (fs.cb instanceof Map) ? fs.cb : [:]"):FIN_IN.index("boolean delivered = (cb.delivered == true)")]
    assert "if (cb.delivered == true) {" in seg and "다시 보내지 않습니다" in seg and "seCallback(body, deadline, C, cb)" in seg
    # 10차 마무리 4.1: 확정 거부(refused)도 재진입 사이에 유지하고 다시 보내지 않는다 (408 · 429 는 재시도 대상이라 제외)
    assert "} else if (cb.refused == true) {" in seg and "Portal이 요청을 거부했습니다(HTTP ${cb.http_code}). 다시 보내지 않습니다." in seg
    assert "if (!(state.tries instanceof List)) { state.tries = [] }" in CALLBACK and "int done = (state.tries as List).size()" in CALLBACK
    assert "state.refused = (state.refused == true)" in CALLBACK, "refused 를 진입 사이에 유지한다"
    assert "boolean resolved = (state.delivered == true) || (state.refused == true)" in CALLBACK
    assert "for (int attempt = done + 1; !resolved && attempt <= maxAttempts; attempt++) {" in CALLBACK
    assert "state.refused = true" in CALLBACK, "결정적 4xx 에서 refused 를 세운다"
    assert "state.tries = []\n" not in CALLBACK, "앞 진입의 시도 기록을 지우지 않는다"
    assert "finalize: [entries: fs.entries, exec_sec_before: (long) ((fs.exec_ms as long) / 1000L), limit_left_sec: deadline - tIn, lost: fs.lost]" in FIN_IN
    summary = _method("def seBuildSummary")
    text = _method("String seSummaryText")
    # 접수 전에 끝난 요청과 결과 확인이 중단된 접수 요청을 구분한다(10차 R1) — 접수된 요청을 "접수 전" 으로 적지 않는다
    assert "manifest: ((env.SE_MANIFEST_JSON ?: '').trim() != '')" in summary
    assert "rows << ((v.manifest == true) ? '결과 확인: 마치지 못해 결과 요약이 없습니다.' : 'Portal 전송: 접수 전에 끝나 보낸 결과가 없습니다.')" in text
    # 전송을 확인하지 못한 요청을 "끝났다" 로 적지 않는다 — 전송 행은 기록대로(응답 · 거부 · 확인 못함 · 시작 안 함)
    assert "send = (fin.attempted == true) ? '확인하지 못함' : '시작하지 않음'" in text
    assert 'send = "거부됨, HTTP ${fin.http_code}".toString()' in text
    assert "수집과 결과 전송이 끝났습니다" not in TEXT


def test_no_inner_step_limits_and_no_tier2():
    """8차 R3: 단계마다 두던 30 · 60 · 120초 제한, Tier 2(SE_FINALIZER_BOUNDED + 승인 4 서명), 정체 감시는 없다.
    9차: 빌드 전체 12시간 · 수집 단계 39000초 한계도 없다 — 기다리는 동안 빌드를 끊지 않는다."""
    for gone in ("seBounded", "SE_FINALIZER_BOUNDED", "seEnclosingIds", "seIsOwnTimeout", "PRESERVE_STEP", "ASSEMBLE_MIN", "FINALIZER_TOTAL",
                 "CALLBACK_ATTEMPT", "ABORT_ATTEMPT", "gather_watch", "SE_GATHER_WATCH", "SE_PROGRESS_DIR", "gather_heartbeat", "timeout 120 python3",
                 "timeout(time: 12, unit: 'HOURS')", "39000", "C.BUILD", "C.STAGE", "SE_STAGE_START_EPOCH", "SE_BUILD_START_EPOCH"):
        assert gone not in TEXT, gone
    assert TEXT.count("timeout(time:") == 4, "입력 확인 5분 · 실행 위치 확인 5분 · 시도 하나의 실행 한계 · 결과 확인 1시간"
    assert "timeout(time: limitSec, unit: 'SECONDS') {" in ATTEMPT
    assert "long limitSec = (C.GATHER_MAX as long) + (C.KILL_AFTER as long) + (C.ATTEMPT_MARGIN as long)" in ATTEMPT


def test_time_limits_count_execution_and_waiting_separately():
    """9차: 기다린 시간은 실행 한계에 넣지 않는다. 대기는 빌드 하나의 합으로 세고(다시 시도해도 처음부터 세지 않는다), 수집은 누적 실제 실행 시간으로 센다."""
    # 10차 마무리 1: pipeline-level options 블록 자체를 두지 않는다(빈 블록은 선언형 린터 오류 · G13). buildDiscarder/보관 지정 없음.
    assert "\n    options {" not in TEXT, "pipeline-level options 블록 없음 (stage-level options 는 더 깊은 들여쓰기)"
    assert "buildDiscarder(" not in TEXT and "logRotator(" not in TEXT
    assert "unit: 'HOURS'" not in TEXT, "빌드 전체 timeout 없음"
    assert VALIDATE.count("options { timeout(time: 5, unit: 'MINUTES') }") == 1
    assert RESOLVE.count("options { timeout(time: 5, unit: 'MINUTES') }") == 1
    assert "options {" not in GATHER.split("\n    post {")[0] and "agent {" not in GATHER.split("\n    post {")[0]
    consts = dict(re.findall(r"^\s+([A-Z_]+)\s*:\s*(\d+),", _method("Map seConstants"), re.M))
    assert int(consts["INFRA_WAIT"]) == 72 * 3600 and int(consts["GATHER_MAX"]) == 6 * 3600 and int(consts["FINALIZER"]) == 3600
    assert "OFFLINE_GRACE" not in consts, "10차: 끊김 대기를 Jenkins 처리 유예로 앞당기지 않는다 — 확인된 감지 시각부터 센다"
    assert int(consts["MAX_BUILD"]) == int(consts["INFRA_WAIT"]) + int(consts["GATHER_MAX"]) + int(consts["FINALIZER"]) + 3 * 3600
    assert int(consts["PORTAL_WAIT"]) == 600 and int(consts["PORTAL_ATTEMPTS"]) == 3
    for gone in ("BUILD", "STAGE", "PRE"):
        assert gone not in consts, gone
    # 대기 합은 빌드 하나에 하나 — env 로 단계와 post 가 같은 기록을 이어 쓴다
    assert "env.SE_INFRA_JSON = groovy.json.JsonOutput.toJson(infra)" in _method("def seInfraSave")
    assert "return seInfraNew(C.INFRA_WAIT as long)" in _method("def seInfraLoad")
    left = _method("long seInfraLeftSec")
    assert "(infra.budget_sec as long) - (infra.used_sec as long) - waited" in left
    close = _method("def seInfraClose")
    assert "infra.used_sec = (infra.used_sec as long) + sec" in close and "if (ep == null || ep.closed == true) { return }" in close


def test_retention_policy():
    # 10차 마무리 1: 로그·빌드 기록 보관(buildDiscarder/logRotator)은 Jenkinsfile 이 지정하지 않는다 — Jenkins 전역 설정으로 관리한다.
    #   (주석은 production 트리에서 strip 되므로 주석 문자열을 단언하지 않는다 — 코드에 보관 지시어가 없음만 확인.)
    assert "buildDiscarder(" not in TEXT and "logRotator(" not in TEXT


def test_finalizer_recovers_inputs_in_order_and_prefers_layer_a():
    assert "unstash 'gather-output'" in REC_STASH and "unarchive mapping: [(f): f]" in REC_ARCH
    i_stash = FIN_IN.index("seRecoverStash(")
    i_arch = FIN_IN.index("seRecoverArchive(")
    i_choose = FIN_IN.index("seChooseMedium(stEval, arEval, finalStashed)")
    assert i_stash < i_arch < i_choose
    assert "JENKINS_HOME" not in TEXT, "archive 는 unarchive step 으로만 회수한다"
    assert "rep.exit_code in [0, 2]" in EVAL, "Layer A 결과(exit 0/2) 우선"
    assert EVAL.index("rep.exit_code in [0, 2]") < EVAL.index("seReconcileRaw(manifestJson"), "정리 결과 → 보충 조립 순서"
    assert "layerA=${layerA}" in FIN_IN and "source=${source}" in FIN_IN


def test_finalizer_handles_no_manifest_and_builds_contract_body():
    assert "접수된 요청이 없어 Portal로 보낼 결과가 없습니다" in FINALIZE and "return null" in FINALIZE
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
    assert GATHER.count("seTimestamped {") - POST.count("seTimestamped {") == 1, "수집 단계 본문 (마지막 stage 라 _stage 가 pipeline post 까지 잡는다)"


def test_business_events_carry_time_in_the_line_body():
    """8차 R2: 수집 시작 · 끝(scripts/run_gather.sh), 결과 보존 결과, Portal 시도 시작 · 응답 · 실패 · 대기 · 최종 상태, 미시도, 결과 확인 시작은 본문에 시각이 있다.
    2026-10-09: 결과 보존은 끝(결과)만 적는다 — 시작 시각은 바로 앞 수집 끝 줄과 같아 반복이었다."""
    log = _method("def seLog")
    assert 'echo "[${seShowTime(seNowMs())}] ${line}"' in log
    assert 'seLog("[결과 보존] ${sePreserveText(archived, stashed, manifestOk, hasResult)}")' in PRESERVE
    for marker in ("번째 전송을 시작합니다", "응답을 받았습니다", "번째 전송에 실패했습니다", "초 후", "전송을 시작하지 않았습니다",
                   "전송을 확인하지 못했습니다", "Portal이 요청을 거부했습니다"):
        assert re.search(r"seLog\(\"\[Portal 전송\][^\n]*" + re.escape(marker), CALLBACK), marker
    assert 'seLog("[결과 확인] 접수 ${ips.size()}대의 결과를 확인합니다.")' in FINALIZE
    assert re.search(r"seLog\(\"\[수집\] 중단됨:", BODY) and re.search(r"seLog\(\"\[수집\] 중단됨:", STAGE_FN), "중단도 시각과 함께"
    assert 'seLog("[입력 확인] 요청을 접수했습니다.' in VALIDATE
    # 9차: 기다림 · 끊김 · 이어서 수집 · 재개 불가도 시각과 함께
    assert re.search(r"seLog\(\"\[실행 대기\]", _method("def seQueueTimer"))
    assert re.search(r"seLog\(\"\[수집\] \$\{where\}에서", LOOP) and re.search(r"seLog\(\"\[수집\] 이어서 수집할 Runner", LOOP)
    assert re.search(r"seLog\(\"\[수집\] 같은 Runner", BODY) and re.search(r"seLog\(\"\[수집\] 이번 수집 시도가 끝났습니다", BODY)


def test_callback_rules_and_attempt_records():
    assert "if (left < (C.PORTAL_MIN as long)) {" in CALLBACK and "state.reason = 'no_time'" in CALLBACK
    assert "int t = (int) Math.min((long) C.PORTAL_WAIT, left - 10L)" in CALLBACK
    assert "code ==~ /2\\d\\d/" in CALLBACK and "!(code in ['408', '429'])" in CALLBACK, "결정적 4xx 는 중단, 408/429 는 재시도"
    assert "aborted ? 1 : (C.PORTAL_ATTEMPTS as int)" in CALLBACK
    # 2026-10-05 사용자 결정: 2xx 수신까지가 계약 — 응답 본문은 읽지도 기록하지도 않는다. 2xx 를 저장 완료라고 쓰지 않는다
    assert "quiet: true" in CALLBACK and "consoleLogResponseBody: false" in CALLBACK and "resp.content" not in CALLBACK
    # 2xx 는 응답을 받았다는 사실(상태 코드 · 걸린 시간)만 적는다 — 저장 · 반영 완료로 쓰지 않는다
    assert 'seLog("[Portal 전송] HTTP ${code} 응답을 받았습니다. 소요 시간 ${took}.")' in CALLBACK
    assert "저장 완료" not in TEXT and "반영 완료" not in TEXT
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
    # 10차 마무리 4.2: 응답 확인 전 중단(interrupted)도 수신 불명 → uncertain. 그 뒤 재진입에서 4xx(refused)를 받아도 앞 전송이 전달됐을 수 있어 uncertain 이다.
    assert "if (t.outcome == 'interrupted' || (t.outcome == 'failed' && (t.http_code == null || \"${t.http_code}\" == '408'))) { unknownReceipt = true }" in CALLBACK
    assert "state.receipt = state.delivered ? 'delivered' : (!state.attempted ? 'not_attempted' : (unknownReceipt ? 'uncertain' : 'not_delivered'))" in CALLBACK
    assert "refused: (cb.refused == true)" in _method("Map seCallbackRecord"), "요약 기록에 refused 를 남긴다"


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


def test_gather_runs_through_run_gather_with_the_accumulated_limit():
    """9차: 한계 계산(scripts/gather_budget.sh · 남은 빌드 시간 · 가용 메모리)은 없다. 파이프라인은 누적 최대(6시간)만 넘기고,
    이번 시도의 한계 · 남은 대상 · 동시 실행 수는 Runner 의 실행 기록(scripts/gather_state.py)이 정한다."""
    assert ('bash "\\${WORKSPACE}/scripts/run_gather.sh" "${playbook}" "${inventory}" "${env.SE_LOCATION}" "${addonDir ? \'true\' : \'false\'}" '
            '"${C.GATHER_MAX}" "${lostPrev ? \'true\' : \'false\'}"') in BODY
    assert BODY.index("String addonDir = seAddonPrepare(targetType, st)") < BODY.index("scripts/run_gather.sh")
    assert not re.search(r'ansible-playbook\s+"', TEXT) and "timeout --signal" not in TEXT, "ansible-playbook 실행 · 한계 집행은 run_gather.sh 한 곳"
    for gone in ("gather_budget.sh", "SE_MEM_AVAILABLE_MB", "not_started_budget", "not_started_memory", "mem_cap", "mem_guard", "[Budget]",
                 "SE_FORCE_SEC", "build_limit", "stage_limit", "exec.start"):
        assert gone not in TEXT, gone
    # 처음 시도: 저장소 받기 → 소유 기록(prepared: false) → 지난 결과 정리 → 접수 목록 → 소유 기록(prepared: true). 이어서 하는 시도는
    #   저장소를 다시 받지 않고 revision 을 대조한다(10차 R3: 준비가 중간에 끊긴 같은 빌드는 남은 준비만 마친다)
    order = [PREP.index(k) for k in ("checkout(scm)", "seWriteOwner(false, [:])", "sh label: '이전 실행의 결과 파일 정리'",
                                      "writeFile(file: 'gather_manifest.json'", "seWriteOwner(true, [:])")]
    assert order == sorted(order)
    assert "commit = (scmVars?.GIT_COMMIT ?: '').toString()" in PREP and "env.SE_WS_COMMIT = commit" in PREP
    assert "if (head && head == own.commit.toString()) { commit = head; reused = true }" in PREP, "같은 빌드의 준비를 이어 갈 때 받은 revision 이 그대로면 다시 받지 않는다"
    assert "sePrepareWorkspace(targetType, null)" in BODY and "sePrepareWorkspace(targetType, own)" in BODY
    assert "} else if (own.prepared == false && st.gather_started != true) {" in BODY
    resume = BODY[BODY.index("} else {", BODY.index("} else if (own.prepared == false")):BODY.index("String addonDir = seAddonPrepare")]
    assert "checkout" not in resume and "git rev-parse HEAD" in resume and "head != own.commit.toString()" in resume
    assert TEXT.count("checkout(scm)") == 1
    # 기술 기록 한 줄 — 증거 수집기가 수집 단계가 Runner 위에서 돌았는지 본다(종전 [Budget] exec)
    assert 'echo "[기술 기록] 수집 시도 n=${cls.attempt ?: \'-\'} node=${env.NODE_NAME} rc=${rc} state=${s}' in BODY


def test_attempt_state_to_outcome_uses_the_run_record():
    """8차 R7 · 9차: 종료 코드만으로 원인을 단정하지 않는다 — scripts/gather_state.py classify 가 실제 실행 시간(한계 도달) · OOM 근거 ·
    부팅 기록으로 판정하고, 파이프라인은 그 판정을 outcome 으로 옮긴다(seOutcomeFromState). Harness 도 같은 함수를 부른다."""
    fn = _method("Map seOutcomeFromState")
    assert "if (state == 'completed') { return [outcome: 'completed', limit_reason: ''] }" in fn
    assert "if (state == 'gather_limit') { return [outcome: (\"${rc}\" == '137' ? 'timeout_killed' : 'timeout'), limit_reason: 'gather_limit'] }" in fn
    assert "['prep_failed', 'process_lost', 'aborted', 'failed_run', 'resume_impossible', 'attempt_limit']" in fn
    assert "    return [outcome: 'interrupted_unknown', limit_reason: '']\n}" in fn
    assert "Map cls = seClassifyAttempt()" in BODY and "Map oc = seOutcomeFromState(s, cls.rc)" in BODY
    assert "env.SE_GATHER_OUTCOME = oc.outcome" in BODY and "env.SE_GATHER_LIMIT_REASON = oc.limit_reason" in BODY
    assert "if (s == 'not_started') { s = (rc in [90, 91]) ? 'prep_failed' : 'failed_run' }" in BODY
    infra = BODY[BODY.index("if (s in ['runner_oom', 'runner_restart', 'agent_disconnect', 'running']) {"):BODY.index("Map oc = seOutcomeFromState")]
    assert "seSnapshotGatherOutput()" in infra and "return" in infra and "sePreserveGatherOutput" not in infra, \
        "실행 기반 장애면 원본만 넘기고 다시 시도한다 — 작업 폴더를 지우지 않는다"
    classify = _method("Map seClassifyAttempt")
    assert "python3 scripts/gather_state.py classify --ws" in classify and "label: '수집 시도 판정'" in classify
    assert "env.SE_GATHER_OUTCOME = 'interrupted_unknown'" in STAGE_FN
    harness = (Path(__file__).resolve().parents[2] / "tests" / "jenkins" / "harness" / "Jenkinsfile_harness").read_text(encoding="utf-8")
    assert "lib.seGatherStage(" in harness, "Harness 가 운영 함수 seGatherStage 를 그대로 실행한다"


def test_retry_rules_infra_only_with_backoff_and_pinned_runner():
    """9차: 다시 시도는 실행 기반 장애(Runner 연결 끊김 · 근거 있는 OOM · 재부팅)뿐이다. 진척 없이 반복되면 5분부터 두 배씩 쉬고,
    수집을 시작한 뒤에는 그 Runner 로만 다시 시도한다. 대상 측 장애 · 사용자 취소 · 원인 미확인 종료는 다시 시도하지 않는다."""
    assert "if (s in ['runner_oom', 'runner_restart', 'agent_disconnect', 'running']) {" in LOOP
    assert ("st.backoff = ((st.backoff as long) > 0L) ? Math.min((st.backoff as long) * 2L, C.BACKOFF_MAX as long) : Math.min(300L, C.BACKOFF_MAX as long)"
            in LOOP), "5분부터 두 배씩, 상한은 BACKOFF_MAX(시험 상수도 그대로 따른다)"
    assert "if (((last.progress ?: 0) as int) > 0) {\n                st.backoff = 0L" in LOOP, "진척이 있으면 바로 다시 시도한다"
    assert "seInfraPause(infra, st.backoff as long," in LOOP
    assert "if (r.state == 'agent_lost') {" in LOOP and "st.wait_from_ms = lostAt" in LOOP and "OFFLINE_GRACE" not in TEXT
    assert "long backdate = st.wait_from_ms ? Math.max(0L, (long) ((seNowMs() - (st.wait_from_ms as long)) / 1000L)) : 0L" in LOOP, \
        "대기는 확인된 감지 시각부터 센다 — 즉시 난 읽기 오류 · controller 재시작을 5분 기다린 것으로 적지 않는다"
    assert "Jenkins 가 ${seDuration" not in LOOP and "기다린 뒤 알렸습니다" not in TEXT
    assert "st.agent_lost_prev = (st.gather_started == true)" in LOOP
    assert "if (r.state == 'expired') {" in LOOP and "st.outcome = 'infra_wait_expired'" in LOOP and "st.limit_reason = 'infra_wait'" in LOOP
    assert "process_lost" not in LOOP, "원인 미확인 종료는 다시 시도하지 않는다"
    # retry(agent()) 는 Runner 연결 끊김을 아는 방법일 뿐이다 — 두 번째 호출은 일을 하지 않고 표식만 남긴다
    assert "retry(count: 2, conditions: [agent(), nonresumable()]) {" in WITH_NODE
    assert "if ((r.calls as int) > 1) {\n                        r.state = 'agent_lost'\n                        r.lost_at_ms = seNowMs()\n                        return" in WITH_NODE
    assert "} catch (Throwable t) {" in WITH_NODE and "throw t" in WITH_NODE, "오류 종류만 남기고 다시 던진다 — 판정은 retry 조건이 한다"
    assert "failFast: true" in WITH_NODE and "'대기 한도': {\n                seQueueTimer(r, infra, ep, capSec)" in WITH_NODE
    timer = _method("def seQueueTimer")
    assert "nap = Math.min(nap * 2L, 300L)" in timer and "long nap = 5L" in timer, "즉시 반복 조회 없이 5초부터 5분까지 늘린다"
    assert "error(" in timer and timer.index("r.state = 'expired'") < timer.index("error("), "표식을 먼저 남기고 요청을 거둔다"
    assert "seNowMs() - lastNote >= 1800000L" in timer, "30분마다 상태 줄"


def test_interruptions_are_recorded_and_rethrown_not_swallowed():
    i_catch = BODY.index("} catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie) {")
    after = BODY[i_catch:]
    after = after[: after.index("\n    }\n")]
    # 끊김 · 취소 구분: Runner 가 오프라인이면 Jenkins 가 끊긴 Runner 의 step 을 끝낸 것 — 폴더를 건드리지 않고 다시 던진다
    assert after.index("if (!nodesByLabel(label: env.NODE_NAME)) {") < after.index("env.SE_GATHER_OUTCOME = 'aborted'")
    lost = after[after.index("if (!nodesByLabel(label: env.NODE_NAME)) {"):after.index("env.SE_GATHER_OUTCOME = 'aborted'")]
    assert "throw fie" in lost and "sePreserveGatherOutput" not in lost and "seSnapshotGatherOutput" not in lost
    user = after[after.index("env.SE_GATHER_OUTCOME = 'aborted'"):]
    assert "env.SE_GATHER_INTERRUPTION = 'user_or_other'" in user and user.rstrip().endswith("throw fie")
    assert "cls.state == 'running'" in user and "seSnapshotGatherOutput()" in user and "sePreserveGatherOutput()" in user, \
        "수집 프로세스가 아직 돌면 폴더를 지우지 않는다"
    assert "catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie2) {\n            throw fie2" in user
    stage = STAGE_FN[STAGE_FN.index("} catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie) {"):]
    assert "env.SE_GATHER_INTERRUPTION = 'user_or_other'" in stage and "throw fie" in stage
    with_node = WITH_NODE[WITH_NODE.index("} catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie) {"):]
    assert "if (r.state == 'expired') { return r }" in with_node and "seInfraClose(infra, ep, seNowMs(), 'interrupted')" in with_node
    assert "throw fie" in with_node
    attempt = ATTEMPT[ATTEMPT.index("} catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie) {"):]
    assert "if (seNowMs() - t0 < (limitSec - 10L) * 1000L) { throw fie }" in attempt, "시도 한계가 아니면 그대로 다시 던진다"
    assert "catchError(" not in TEXT, "node 안의 중단을 삼키는 catchError 는 없다"
    canon = _method("def seLoadCanon")
    assert canon.index("FlowInterruptedException fie") < canon.index("catch (Exception e)")
    fetch = ADDON[ADDON.index("def fetchAddon"):ADDON.index("if (!problem)")]
    assert fetch.index("FlowInterruptedException fie") < fetch.index("catch (Exception e)")


def test_gather_post_preserves_then_deletes_only_when_required_files_were_archived():
    """8차 R8: 보관 성공은 예외가 없었다는 뜻만이 아니다 — 지금 있는 파일을 이름으로 지정하고 빈 보관을 실패로 둔다.
    이 빌드의 접수 목록과 결과 파일을 보관했을 때만 작업 폴더(와 그 @tmp)를 지운다. 9차: 마지막 시도의 끝이 보존이다."""
    assert BODY.rstrip().endswith("sePreserveGatherOutput()\n}")
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
    assert "결과 보존을 확인하지 못해 작업 폴더를 지우지 않고 남겼습니다" in PRESERVE
    for name in ("gather_final.jsonl", "gather_finalize_report.json", "gather_progress.jsonl", "gather_run.json", "workspace_cleanup.json"):
        assert f"'{name}'" in PRESERVE, name
    assert "timeout" not in PRESERVE.lower().replace("timeout_killed", ""), "결과 보존에 단계 제한이 없다"


def test_preserve_steps_are_independent():
    assert PRESERVE.count("catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)") >= 5
    assert PRESERVE.count("throw fie") >= 5
    for flag in ("SE_PRESERVE_ARCHIVED", "SE_PRESERVE_STASHED", "SE_PRESERVE_MANIFEST", "SE_PRESERVE_HASRESULT", "SE_PRESERVE_LAYER_A"):
        assert f"env.{flag}" in PRESERVE, flag
    assert "결과를 보존하지 못했습니다. 빌드 기록 저장과 다음 단계 전달이 모두 실패했습니다." in PRESERVE
    assert "preserve: [layerA: env.SE_PRESERVE_LAYER_A" in FIN_IN
    assert TEXT.count("deleteDir()") == 4, "preserve 의 작업 폴더 · @tmp, 결과 확인 폴더, controller 정리의 오래된 폴더"


def test_workspace_markers_and_cleanup_wiring():
    """8차 R8: 작업 폴더 소유 기록(.se_workspace.json)을 수집 단계 첫 동작으로 쓰고, 보존 뒤 끝 시각 · 보존 여부로 다시 쓴다.
    정리는 scripts/workspace_cleanup.py(Runner) 와 seCleanOldFinalizerDirs(controller, pipeline step 만) — 사용자 입력은 없다."""
    assert PREP.index("seWriteOwner(false, [:])") < PREP.index("sh label: '이전 실행의 결과 파일 정리'")
    assert "ended_epoch: seNowSec(), preserved: preserved" in PRESERVE
    clean = _method("def seCleanOldWorkspaces")
    assert "python3 scripts/workspace_cleanup.py --current" in clean and "--keep-days ${C.KEEP_DAYS} --every-sec 86400" in clean
    assert "--build-limit-sec ${C.MAX_BUILD}" in clean, "끝 기록 없는 폴더는 최대 빌드 수명(72 + 6 + 1 + 3시간) 동안 실행 중으로 본다"
    # 이어서 하는 시도는 소유 기록으로 이 빌드의 폴더인지 확인한다 — 없으면 전체를 다시 수집하지 않고 재개 불가
    assert "boolean mine = (own != null && \"${own.job}\" == \"${env.JOB_NAME}\" && \"${own.build}\" == \"${env.BUILD_NUMBER}\")" in BODY
    gone = BODY[BODY.index("if (!mine) {"):BODY.index("sePrepareWorkspace(targetType, null)")]
    assert "if (st.gather_started == true) {" in gone and "outcome: 'resume_impossible'" in gone and "return" in gone
    assert "exit 0" in clean and "returnStatus: true" in clean, "정리 실패가 빌드 결과를 바꾸지 않는다"
    fin = _method("def seCleanOldFinalizerDirs")
    assert "findFiles(glob: 'fin-*/.se_fin.json')" in fin and "if (info.archived == true) {" in fin and "kept << d" in fin
    assert "now - ended < (C.KEEP_DAYS as long) * 86400L" in fin and "if (d == mine" in fin
    assert "sh(" not in fin and "python" not in fin, "controller 에 Python 을 요구하지 않는다"


def test_finalizer_validates_lines_and_records_damage():
    helper = _method("Map seFilterEnvelopeLines")
    assert "new groovy.json.JsonSlurper()" in helper and "missing" in helper
    assert "seEnvelopeShapeReason(obj, channel, accepted) != null" in helper and "keys13" not in helper
    assert EVAL.count("seFilterEnvelopeLines(") == 3, "Layer A 결과 · Layer B 결과 · raw — 셋 다 같은 검문(후보마다)"
    assert "seFilterEnvelopeLines(" not in FIN_IN, "줄 집합은 후보 평가(seEvalCandidate) 한 곳에서만 만든다"
    assert "ev.layerA = 'report_unreadable'" in EVAL and "ev.layerA = 'incomplete'" in EVAL
    i_read = EVAL.index("readJSON file: 'gather_finalize_report.json'")
    seg = EVAL[i_read: i_read + 1800]
    assert "catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)" in seg
    assert "ev.unrecovered = picked.missing" in EVAL
    for key in ("unrecovered: unrecovered", "damage: damage", "by_origin: (report.by_origin ?: null)",
                "recovery_limited: (layerB == 'unavailable' && lineCount != accepted)"):
        assert key in FIN_IN, key


def test_no_registered_runner_is_a_config_error_and_results_are_still_sent():
    """9차 W01: 등록된 Runner 가 없으면 설정 오류로 FAILURE. 접수 목록이 있으므로 post 의 결과 확인이 대상마다 실패 결과를 보낸다.
    등록된 Runner 가 지금 연결이 끊겼거나 바쁜 것은 오류가 아니다 — 수집 단계가 기다린다(no_agent 로 건너뛰지 않는다)."""
    check = _method("Map seCheckRunners")
    assert "seCheckRunners(env.SE_AGENT_LABEL)" in RESOLVE
    assert "env.SE_GATHER_OUTCOME = 'config_error'" in check and "error(\"[실행 위치] 라벨" in check
    assert "'config_error': '실행 위치 설정 오류(등록된 Runner 없음)'" in TEXT
    assert "when {" not in TEXT and "no_agent'" not in TEXT
    assert "String outcome = env.SE_GATHER_OUTCOME ?: 'interrupted_unknown'" in FINALIZE


def test_portal_loads_layer_b_library_instead_of_defining_it():
    for sig in ("Map seFallbackCanon()", "String seJsonString(", "Map seReconcileRaw("):
        assert sig not in TEXT, f"Jenkinsfile_portal 에 {sig} 사본이 있다 — 정본은 se_finalize.groovy"
    assert "seTrusted('scripts/jenkins/se_finalize.groovy')" in TEXT and "return load('se_finalize.groovy')" in TEXT
    assert FINALIZE.index("seWithNode('built-in'") < FINALIZE.index("seFinalizeIn(")
    assert "lib.seReconcileRaw(manifestJson, outText, cpText, box.canon, outcome)" in EVAL
    # 후보가 둘이어도 한 진입에서 한 번만 읽는다(라이브러리 파일은 결과 확인 폴더에 쓴다 — 회수 폴더가 아니다)
    assert "box.lib = seLoadFinalizeLib()" in FIN_LIB and "box.canon = (box.lib != null) ? seLoadCanon(box.lib) : null" in FIN_LIB
    assert "if (box.tried != true) {" in FIN_LIB
    assert EVAL.index("dir(cdir) {") < EVAL.index("def lib = seFinLib(box)"), "보충 조립은 회수 폴더 밖에서"
    assert "ev.layerB = 'unavailable'" in EVAL and "layerB == 'unavailable'" in FIN_IN
    assert "FlowInterruptedException fie" in TEXT[TEXT.index("def seLoadFinalizeLib()"):TEXT.index("def seLoadCanon(")]


def test_groovy_fallback_canon_matches_yaml_and_layer_a():
    canon = LIB[LIB.index("Map seFallbackCanon()"):LIB.index("String seJsonString")]
    fr = yaml.safe_load((REPO / "common/vars/failure_reasons.yml").read_text(encoding="utf-8"))
    assert f"reason  : '{fr['_fr_catalog']['output_build_failed']['default']}'" in canon
    assert f"infraReason: '{fr['_fr_catalog']['infra_unavailable']['default']}'" in canon
    assert "if (fr?._fr_catalog?.infra_unavailable?.default) { canon.infraReason = fr._fr_catalog.infra_unavailable.default }" in TEXT
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
    genv = _method("List seGatherEnv")
    for var in ("ANSIBLE_JSON_MANIFEST_FILE", "ANSIBLE_JSON_PROGRESS_FILE", "ANSIBLE_JSON_CHECKPOINT_FILE", "ANSIBLE_JSON_OUTPUT_FILE",
                "SE_AUTH_EVIDENCE_DIR", "ANSIBLE_CONFIG", "REPO_ROOT"):
        assert f"\"{var}=${{w}}/" in genv or f"\"{var}=${{w}}\"" in genv, var
    assert "withEnv(seGatherEnv()) {" in ATTEMPT, "시도마다 그 작업 폴더 기준으로 만든다"


def test_file_has_lf_line_endings():
    assert b"\r\n" not in JENKINSFILE.read_bytes()


def test_recovery_source_is_the_medium_and_unarchive_is_per_file():
    """C1 (2026-10-10): source = 고른 회수 매체. 매체마다 격리 폴더에 받고(섞지 않는다), archive 는 파일별로 받는다.
    unstash 가 예외면 그 폴더를 쓰지 않는다. 고르는 근거는 파일 존재가 아니라 평가 결과(결과가 있는 대상 수 · 정리 결과 완결)다."""
    assert 'String rd = "rec-${fs.entries}"' in FIN_IN
    assert 'Map stashC = seRecoverStash("${rd}/stash")' in FIN_IN and 'archC = seRecoverArchive("${rd}/archive", recoverFiles)' in FIN_IN
    assert "dir(sdir) { unstash 'gather-output' }\n        r.ok = true" in REC_STASH, "unstash 가 끝나야 그 폴더를 쓴다"
    per_file = REC_ARCH[REC_ARCH.index("for (String f in files)"):]
    assert "unarchive mapping: [(f): f]" in per_file and "FlowInterruptedException fie" in per_file and "throw fie" in per_file
    assert "r.missing << " in per_file
    # 평가: 결과 파일이 있는 후보만 고른다. 결과가 있는 대상(real) → 정리 결과 완결 → 마지막 보존 전달 표식(있으면 stash, 없으면 archive)
    assert "ev.has = hasFinal || hasOut || hasCp" in EVAL and "if (!ev.has) { return ev }" in EVAL
    assert "ev.real = Math.max(0, ((bo.output ?: 0) as int) + ((bo.checkpoint ?: 0) as int) - gateDropped)" in EVAL
    assert "if (rs != ra) { return (rs > ra) ? 'stash' : 'archive' }" in CHOOSE
    assert "return finalStashed ? 'stash' : 'archive'" in CHOOSE
    assert CHOOSE.index("if (rs != ra)") < CHOOSE.index("st.complete == true") < CHOOSE.index("return finalStashed")
    # 빠른 길: 마지막 보존의 전달이 확인되고 그 정리 결과가 완결이면 archive 를 조회하지 않는다
    assert "boolean fast = finalStashed && stEval != null && stEval.complete == true" in FIN_IN
    assert FIN_IN.index("boolean fast =") < FIN_IN.index("if (!fast) {") < FIN_IN.index("seRecoverArchive(")
    assert "boolean finalStashed = (env.SE_FINAL_STASHED == 'true')" in FIN_IN
    assert "recovery: [final_stashed: finalStashed, fast_path: fast, chosen: source," in FIN_IN


def test_final_stash_flag_is_set_only_after_the_final_stash_succeeds():
    """C1: 마지막 보존의 stash 직전에 표식을 지우고 성공 직후에만 세운다. 중간 보존(snapshot)과 수집 단계 시작은 표식을 지운다."""
    seg = PRESERVE[PRESERVE.index("env.SE_FINAL_STASHED = ''"):]
    assert seg.index("env.SE_FINAL_STASHED = ''") < seg.index("stash(name: 'gather-output'") < seg.index("stashed = true") \
        < seg.index("env.SE_FINAL_STASHED = 'true'") < seg.index("} catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)")
    snap = _method("def seSnapshotGatherOutput")
    assert snap.index("env.SE_FINAL_STASHED = ''") < snap.index("stash(name: 'gather-output'")
    assert "env.SE_FINAL_STASHED = 'true'" not in snap
    assert "env.SE_FINAL_PRESERVED = ''\n    env.SE_FINAL_STASHED = ''" in STAGE_FN


def test_finalizer_archives_result_files_from_the_chosen_input_only_when_present():
    """C1: 요약 · 본문은 결과 확인 폴더에서, 정리 결과 파일은 고른 입력 폴더에 **있을 때만** 보관한다. 둘을 따로 기록하고 보관 완료는 수행한 보관이 모두
    성공했을 때다. 결과 파일 링크는 실제로 보관한 것만."""
    seg = FIN_IN[FIN_IN.index("fs.mark = 'archive'"):FIN_IN.index("// UNSTABLE 은 한 번만")]
    assert "for (String f in ['callback_body.json', 'finalize_summary.json'])" in seg
    assert "dir(ev.dir) {" in seg and "for (String f in ['gather_final.jsonl', 'gather_finalize_report.json'])" in seg
    assert "if (resultFiles) {" in seg, "정리 결과 파일이 없으면 두 번째 보관을 부르지 않는다"
    assert "boolean finalArchived = bodyArchived && resultArchive != 'failed'" in seg
    assert "if (resultArchive == 'ok' && resultFiles.contains('gather_final.jsonl')) { files << ['서버별 수집 결과', 'gather_final.jsonl'] }" in seg
    assert "archive_body_summary: bodyArchived, archive_results: resultArchive" in FIN_IN


def test_every_shell_step_has_a_label():
    calls = [m.group(0).lstrip(" \t=(:") for m in re.finditer(r"(?:^|[\s=(:])sh(?=[( ])[^\n]*", TEXT, re.M)]
    steps = [c for c in calls if ("script:" in c or c.startswith('sh "') or c.startswith("sh '") or c.startswith('sh """'))]
    assert steps, "sh step 이 없다"
    unlabeled = [c[:80] for c in steps if "label:" not in c]
    assert unlabeled == [], unlabeled
    for label in ("수집 결과 정리", "오래된 작업 폴더 정리", "이전 실행의 결과 파일 정리", "추가 수집(Add-on) 저장소 받기",
                  "추가 수집(Add-on) 파일 검사", "추가 수집(Add-on) revision", "저장소 revision 확인", "수집 시도 판정", "서버 정보 수집 (ansible-playbook)"):
        assert f"label: '{label}'" in TEXT, label
    assert "Layer A)" not in TEXT, "사람이 보는 이름에 내부 용어를 쓰지 않는다"


def test_summary_records_status_counts_times_limits_and_warnings():
    assert "status_counts: [success: (statusCounts.success ?: 0), partial: (statusCounts.partial ?: 0)," in FIN_IN
    assert "failed: (statusCounts.failed ?: 0), missing: Math.max(0, accepted - lineCount)]" in FIN_IN
    for key in ("times: [build_started_at:", "gather_started_at: (env.SE_GATHER_STARTED_AT ?: null)", "finalize_started_at: seIsoUtc(tPostMs)",
                "finalize_node_acquired_at: seIsoUtc(tIn * 1000L)",
                "limits: [infra_wait_sec: C.INFRA_WAIT, gather_max_sec: C.GATHER_MAX, finalizer_sec: C.FINALIZER",
                "gather_limit_source: (env.SE_GATHER_LIMIT_SOURCE ?: null)", "gather_run: run",
                "infra: [budget_sec: infra.budget_sec, used_sec: infra.used_sec, expired: (infra.expired == true), episodes: (infra.episodes ?: [])]",
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
    # 확정된 집계는 그 자리에서 한 줄로 남긴다 — 뒤 단계가 끊겨 요약이 비어도 대수가 남는다
    assert 'echo "[결과] 성공 ${sc.success}대, 부분 성공 ${sc.partial}대, 실패 ${sc.failed}대' in FIN_IN
    i_arch = FIN_IN.index("archiveArtifacts artifacts: finalFiles.join(','), allowEmptyArchive: false")
    i_links = FIN_IN.index('echo "[결과 파일] ${f[0]}: ${base ? base + \'artifact/\' + f[1] : f[1]}"')
    i_del = FIN_IN.rindex("deleteDir()")
    assert i_arch < i_links < i_del, "보관한 뒤에 링크하고, 링크한 뒤에 지운다"
    summary_fn = _method("def seBuildSummary")
    text_fn = _method("String seSummaryText")
    assert "currentBuild.currentResult" in summary_fn and "'ABORTED': '중단'" in summary_fn and "echo seSummaryText([" in summary_fn
    assert "durationString" not in summary_fn and "took: took" in summary_fn and "seDuration((v.took ?: 0) as long)" in text_fn
    assert "send = \"HTTP ${fin.http_code}, 응답 시각 ${fin.delivered_show ?: '-'}\".toString()" in text_fn, "2xx 는 상태 코드와 응답 시각만"
    assert "확인할 것:" not in TEXT and "warnings.join(" not in summary_fn + text_fn, "운영자 요약에 내부 코드값을 나열하지 않는다"


def test_timeout_end_is_explained_with_limit_runtime_counts_preservation_and_delivery():
    """8차 R7: 'rc=124 outcome=timeout' 만 남기지 않는다 — 어떤 한계였는지, 얼마나 실행했는지, 끝난 · 끝나지 않은 대상 수, 보존 결과.
    전송 결과는 바로 앞 [Portal 전송] 줄과 빌드 끝 [요약] 이 적는다(2026-10-09 — 같은 단계에서 다시 쓰지 않는다)."""
    explain = _method("def seExplainGatherEnd")
    assert "if (outcome == 'completed') { return }" in explain
    for part in ("seLimitText('gather_limit')", "run?.exec_used_sec", "결과가 확정된 대상: ${done}대", "마치지 못한 대상: ${partialCp + filled}대",
                 "결과 보존: ${preserve}", "outcome == 'infra_wait_expired'", "outcome == 'resume_impossible'"):
        assert part in explain, part
    assert "Portal 전송: ${send}" not in explain
    assert "seExplainGatherEnd(C, outcome, summary, bo, kept, filled, delivered, cb)" in FIN_IN


def test_build_name_marks_count_only():
    assert 'currentBuild.displayName = "#${env.BUILD_NUMBER} ${params.target_type.trim()} ${acceptedIps.size()}대"' in VALIDATE
    assert "[시험:" not in TEXT and "testTags" not in TEXT
    # 빌드 설명은 실행 기반을 기다리는 동안만 쓰고(무엇을 · 얼마나 기다리는지), 대기가 끝나면 지운다
    users = [m.start() for m in re.finditer(r"currentBuild\.description", TEXT)]
    timer, close = _method("def seQueueTimer"), _method("def seInfraClose")
    assert len(users) == 2 and "currentBuild.description = \"실행 대기:" in timer and "currentBuild.description = null" in close


def test_callback_url_with_credentials_is_refused_without_echoing_it():
    i_cred = VALIDATE.index("if (cbUrl ==~ /(?is)^[a-z][a-z0-9+.-]*:\\/\\/[^\\/?#]*@.*/) {")
    assert i_cred < VALIDATE.index("cbUrl.startsWith('http://')") < VALIDATE.index('결과를 보낼 주소: ${cbUrl}')
    line = VALIDATE[i_cred: VALIDATE.index("\n", VALIDATE.index("error ", i_cred))]
    assert "${cbUrl}" not in line and "params.callbackUrl" not in line
    pat = re.compile(r"(?is)^[a-z][a-z0-9+.-]*://[^/?#]*@.*")
    for bad in ("http://u:p@portal:8080", "HTTPS://user@portal/x", "http://u:p@h\n/x", "ftp://a:b@h"):
        assert pat.match(bad), bad
    for ok in ("http://portal.example.com", "https://portal:8443/api?mail=a@b", "http://10.0.0.1:8080/p#x@y"):
        assert not pat.match(ok), ok


def test_operator_lines_are_plain_sentences():
    """8차 R7: 사람이 읽는 줄(echo · seLog · error · unstable 문자열)에 긴 대시 · 가운데점 · 화살표 · 상자 선을 쓰지 않는다(코드 주석은 무관).
    2026-10-09: 문장 helper 가 변수로 조립하는 한글 문자열도 같은 규칙을 지킨다(줄 끝 주석은 제외)."""
    bad = []
    for no, line in enumerate(TEXT.split("\n"), 1):
        code = line.strip()
        if code.startswith("//"):
            continue
        m = re.search(r"\b(echo|seLog|error|unstable)\s*\(?\s*(['\"])", line)
        if m and re.search(r"[—·→─]", line[m.start():]):
            bad.append((no, code[:100]))
        body = line if line.find(" // ") < 0 else line[:line.find(" // ")]
        q = re.search(r"['\"]", body)
        if q and re.search(r"[가-힣]", body) and re.search(r"[—·→─]", body[q.start():]):
            bad.append((no, code[:100]))
    assert bad == [], bad
    assert "'interrupted_unknown': '수집 단계를 마치지 못함']" in TEXT
    # 요청 도구는 연결 실패 · 응답 시간 초과도 408 로 표시한다 — Portal 이 408 을 돌려줬다고 쓰지 않고 도구 상태로 적는다
    assert "code == '408'" in CALLBACK and "전송 도구 상태: 408" in CALLBACK


def test_gather_end_does_not_call_a_missing_preservation_a_failure():
    """2026-10-06 (main #252 관측): 실행 위치 확인에서 거부돼 수집 단계가 돌지 않은 빌드는 보존 기록이 없다 — "결과 보존: 실패" 로 적지 않는다."""
    fn = TEXT[TEXT.index("def seExplainGatherEnd("):]
    fn = fn[:fn.index("\n}\n") + 3]
    assert "String archivedFlag = (summary.preserve?.archived ?: '').toString()" in fn
    assert "(archivedFlag == 'true') ? '완료'" in fn and "'빌드 기록 저장은 실패했고 전달된 결과로 처리했습니다.'" in fn
    # 9차 (2026-10-06 se-probe L5 · L6 · L8 관측): 보존 기록이 없을 때 수집이 돌았는지 · 넘겨 둔 결과가 있는지로 나눈다
    i_none = fn.index("} else if (!(env.SE_GATHER_STARTED_AT ?: '')) {")
    i_stash = fn.index("} else if (summary.preserve?.stashed == 'true') {")
    assert fn.index("if (archivedFlag in ['true', 'false']) {") < i_none < i_stash
    assert "'수집 단계가 실행되지 않아 보존할 결과가 없습니다.'" in fn[i_none:i_stash]
    assert "'마지막 보존 전에 끝나 앞서 넘겨 둔 결과로 처리했습니다.'" in fn[i_stash:]
    assert "'수집은 했지만 Runner에서 결과를 넘겨받지 못했습니다(이 빌드에 남은 결과 없음).'" in fn[i_stash:]
    # 2026-10-09 (main #356 · #367 관측): 수집을 시작하지 않은 빌드는 머리 문장이 그 사실을 말하고 같은 뜻의 '수집 시간' 행을 되풀이하지 않는다
    assert "why = (outcome == 'config_error') ? '등록된 Runner가 없어 수집을 시작하지 못했습니다' : '수집을 시작하기 전에 빌드가 끝났습니다'" in fn
    assert "(whyNotStarted ? '' : \"\\n  수집 시간: ${ran}\")" in fn


def test_abort_between_attempts_says_handed_results_only_when_there_are_some():
    # 9차 (2026-10-06 se-probe L6): 같은 Runner 를 기다리던 중 취소 — 넘겨 둔 결과(stash)가 없으면 "넘겨 둔 결과로 전송" 이라고 적지 않는다
    stage = TEXT[TEXT.index("def seGatherStage(Map C) {"):]
    stage = stage[:stage.index("\n}\n")]
    assert "String handed = (env.SE_PRESERVE_STASHED == 'true') ? '앞 시도에서 넘겨 둔 결과로 Portal 전송을 시도합니다.' :" in stage
    assert "(st.gather_started ? 'Runner에서 넘겨받은 결과가 없어 접수된 대상마다 실패 결과를 보냅니다.' : '수집을 시작하기 전이라 접수된 대상마다 실패 결과를 보냅니다.')" in stage
    assert "seLog(\"[수집] 중단됨: 사용자가 빌드를 취소했습니다.\\n  \" + handed)" in stage


def test_aborted_gather_still_reports_its_runtime():
    """2026-10-06 (main #245 관측) · 9차: 취소로 끊긴 수집도 실행 시간을 남긴다 — run_gather.sh 가 취소 신호에서 끝 기록을 쓰고(gather_state end),
    취소 경로는 그 기록(gather_run.json)을 읽어 넘긴다. 결과 확인은 env 로 받지 못했으면 회수한 gather_run.json 을 읽는다.
    수집을 시작하지 않은 빌드(실행 위치 확인 실패)는 "수집을 시작하지 않았습니다"."""
    user = BODY[BODY.index("env.SE_GATHER_OUTCOME = 'aborted'"):]
    assert "Map run = seReadGatherRun()" in user and "env.SE_GATHER_RUN = run ? groovy.json.JsonOutput.toJson(run) : ''" in user
    assert "String runDir = ev.dir ?: (stashC.ok ? stashC.dir : ((archC?.got) ? archC.dir : null))" in FIN_IN
    assert "if (fileExists('gather_run.json')) { run = readJSON(file: 'gather_run.json', returnPojo: true) as Map }" in FIN_IN
    assert "'gather_run.json']" in FIN_IN, "보관본에서도 실행 기록을 회수한다"
    rg = (REPO / "scripts" / "run_gather.sh").read_text(encoding="utf-8")
    assert "trap 'se_on_signal 143' TERM" in rg and 'gather_state.py" end --ws "$WS" --rc "$1"' in rg
    fn = TEXT[TEXT.index("def seExplainGatherEnd("):]
    fn = fn[:fn.index("\n}\n") + 3]
    assert "String ranSec = (run?.exec_used_sec != null) ? run.exec_used_sec.toString() : ((run?.ran_sec != null) ? run.ran_sec.toString() : '')" in fn
    assert "'수집을 시작하지 않았습니다.'" in fn and "(env.SE_GATHER_STARTED_AT ?: '')" in fn


def test_spent_wait_budget_still_takes_a_node_that_is_free_now():
    # 2026-10-06 9차: Runner 를 기다리다 한도를 다 쓴 빌드도 결과 처리 노드(built-in)를 얻어 끝나지 않은 대상의 실패 결과를 보낸다.
    #   한도가 0 일 때 첫 반복에서 바로 거두면 node 요청이 queue 에서 배정되기 전에 취소돼 아무것도 보내지 못했다 — 첫 조회(5초) 뒤에 판단한다
    timer = _method("def seQueueTimer")
    assert "boolean firstLook = true" in timer
    assert "if (left <= 0L && !firstLook) {" in timer
    assert "sleep(time: (left > 0L) ? Math.max(1L, Math.min(nap, left)) : nap, unit: 'SECONDS')" in timer
    assert timer.index("sleep(time:") < timer.index("firstLook = false") < timer.index("if (r.state != 'waiting') { break }")


def test_record_files_propagate_read_errors_and_only_parse_errors_are_corrupt():
    """10차 R2(GP-61): 소유 기록 · 수집 실행 기록 · Add-on 결정 파일의 읽기 예외를 '기록 없음' 으로 바꾸지 않는다. 읽기(readFile)는 감싸지 않아
    실행 기반 예외가 원래 형태로 상위 retry(agent(), nonresumable())로 가고, 읽은 문자열의 JSON 해석 오류만 corrupt 다."""
    assert "Map seReadOwner()" not in TEXT, "읽기 예외를 null 로 바꾸던 함수는 없다"
    read_stmt = "String text = readFile(file: path, encoding: 'UTF-8')"
    assert READ.index("if (!fileExists(path)) { return [state: 'absent'] }") < READ.index(read_stmt) < READ.index("try {")
    assert "catch (Exception e) {\n        return [state: 'corrupt', problem: e.getClass().simpleName]" in READ
    assert "Map rec = seReadJsonFile('.se_workspace.json')" in BODY
    assert "Map rec = seReadJsonFile('gather_run.json')" in _method("Map seReadGatherRun")
    gone = BODY[BODY.index("if (!mine) {"):BODY.index("sePrepareWorkspace(targetType, null)")]
    assert "(rec.state == 'absent')" in gone and "(rec.state == 'corrupt')" in gone, "재개 불가 문구는 없음 · 해석 불가 · 다른 빌드를 구분한다"


def test_final_preservation_marker_stops_retrying_after_results_were_handed_over():
    """10차 N1: 마지막 보존이 보관(archive) 또는 전달(stash) 중 하나라도 마치면 표식을 남긴다. 그 뒤 실행 기반 오류로 끊기면 다시 수집하지 않고
    직전 판정으로 끝낸다. 표식 전에 끊기면 같은 작업 폴더에서 보존만 다시 한다(preserve_only). 다시 쓰는 소유 기록은 commit · prepared 를 유지한다."""
    assert "if (archived || stashed) { env.SE_FINAL_PRESERVED = 'true' }" in PRESERVE
    assert PRESERVE.index("env.SE_FINAL_PRESERVED = 'true'") < PRESERVE.index("seWriteOwner(true, [ended_epoch: seNowSec(), preserved: preserved") < PRESERVE.index("deleteDir()")
    assert "env.SE_FINAL_PRESERVED = ''" in STAGE_FN
    lost = LOOP[LOOP.index("if (r.state == 'agent_lost') {"):]
    assert "if (st.final == true && (env.SE_FINAL_PRESERVED ?: '') == 'true') {" in lost and "break" in lost
    assert "if (st.final == true) { st.preserve_only = true }" in lost
    main_branch = "    if (!mine) {\n        if (st.gather_started == true) {"
    assert "if (st.preserve_only == true) {" in BODY and BODY.index("if (st.preserve_only == true) {") < BODY.index(main_branch)
    only = BODY[BODY.index("if (st.preserve_only == true) {"):BODY.index(main_branch)]
    assert "sePreserveGatherOutput()" in only and "run_gather" not in only, "보존만 다시 한다 — 다시 수집하지 않는다"
    assert BODY.index("st.final = true") < BODY.rindex("sePreserveGatherOutput()")
    assert "st.final = true" in ATTEMPT, "시도 실행 한계로 끝난 시도도 마지막이다"
    writer = _method("def seWriteOwner")
    assert "commit: (env.SE_WS_COMMIT ?: '')" in writer and "prepared: prepared" in writer and "rec.putAll(extra)" in writer


def test_user_abort_is_recorded_as_aborted_in_the_run_record():
    """10차 R5: 파이프라인이 사용자 취소로 확인한 시도는 실행 기록에서도 aborted 로 확정한다(같은 때의 OOM 은 관측으로만 남는다)."""
    mark = _method("def seMarkUserAbort")
    assert "gather_state.py classify --ws \"${WORKSPACE}\" --user-abort" in mark and "returnStatus: true" in mark
    user = BODY[BODY.index("env.SE_GATHER_OUTCOME = 'aborted'"):]
    assert "if (cls.state != 'running') { seMarkUserAbort() }" in user
