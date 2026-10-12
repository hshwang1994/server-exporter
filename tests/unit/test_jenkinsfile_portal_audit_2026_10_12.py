"""Jenkinsfile_portal · scripts/run_gather.sh — 2026-10-12 독립 점검에서 고친 결함의 글자 계약.

재현한 결함(각 시험의 docstring)과 고친 규칙을 소스 글자로 고정한다. 하네스(tests/jenkins/harness)와 증거 수집기가 찾는 문구는 바꾸지 않았다.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEXT = (REPO / "Jenkinsfile_portal").read_text(encoding="utf-8")
RUN_GATHER = (REPO / "scripts" / "run_gather.sh").read_text(encoding="utf-8")


def _method(name: str) -> str:
    start = TEXT.index(name if name.endswith("(") else f"{name}(")
    start = TEXT.rfind("\n", 0, start) + 1
    nxt = re.search(r"\n(?:@NonCPS\n)?(?:def |Map |String |boolean |long |List |Object |pipeline \{)", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


def _stage(name: str) -> str:
    start = TEXT.index(f"stage('{name}')")
    nxt = re.search(r"\n        stage\('", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


def test_p1_attempt_asks_jenkins_classification_not_elapsed_time():
    """P1: 시도 한계의 timeout 이 ansible 셸 도중 나면 종전 catch 가 Runner 연결 상태로 '사용자 취소' 를 확정하고 보존 · 삭제한 뒤, 바깥 handler 가
    빈 폴더에서 보존을 반복했다(빈 stash 가 정상 stash 를 덮음). 지금은 Jenkins 의 분류(조건 없는 retry 의 재호출 여부)로만 가르고 보존은 한 곳에서 1회다."""
    attempt = _method("def seAttempt(")
    body = _method("def seAttemptBody")
    assert attempt.count("retry(count: 2) {") == 1 and attempt.count("timeout(time: limitSec, unit: 'SECONDS') {") == 1
    assert "seNowMs() - t0" not in attempt and "currentBuild.result" not in attempt
    assert body.count("sePreserveGatherOutput(") == 2, "본문의 보존은 preserve_only 재진입과 정상 종료 두 곳뿐"
    cut = body[body.index("} catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie) {"):]
    cut = cut[: cut.index("\n    }\n")]
    assert "sePreserveGatherOutput" not in cut and "deleteDir" not in cut and "nodesByLabel" not in cut
    interrupted = _method("def seAttemptInterrupted")
    assert "env.SE_PRESERVE_KEEP_WS = 'true'" in interrupted, "원인 미확정 중단은 보존하되 작업 폴더를 지우지 않는다"
    preserve = _method("def sePreserveGatherOutput")
    assert "def sePreserveGatherOutput() {" in preserve, "하네스 도구(build_functions.py)가 글자로 찾는 서명"
    assert "boolean keepWorkspace = ((env.SE_PRESERVE_KEEP_WS ?: '') == 'true')" in preserve
    assert "if (preserved && keepWorkspace) {" in preserve and preserve.index("if (preserved && keepWorkspace) {") < preserve.index("} else if (preserved) {\n        deleteDir()")


def test_p1_messages_do_not_assert_user_cancel():
    for phrase in ("사용자가 빌드를 취소했습니다", "'aborted': '사용자 취소로 중단'", "'사용자 취소로 '", "why = '사용자 취소로 수집을 마치지 못했습니다'"):
        assert phrase not in TEXT, phrase
    assert "[수집] 중단됨:" in TEXT, "증거 수집기(T5)가 찾는 접두사는 그대로다"
    gs = (REPO / "scripts" / "gather_state.py").read_text(encoding="utf-8")
    assert "Jenkins 사용자 취소(파이프라인 확인)" not in gs and "user_abort=True" in gs and "'--user-abort'" in gs, "코드값 · 플래그는 유지, 문장만"


def test_p2_no_empty_stash_and_snapshot_skips_when_nothing_to_hand_over():
    preserve = _method("def sePreserveGatherOutput")
    snap = _method("def seSnapshotGatherOutput")
    assert "if (stashList) {\n        try {\n            stash(name: 'gather-output', includes: stashList.join(','), allowEmpty: false)" in preserve
    assert "'gather_manifest.json'), allowEmpty: true)" not in TEXT
    assert "if (!present) {" in snap and "stash(name: 'gather-output', includes: present.join(','), allowEmpty: false)" in snap
    assert preserve.index("env.SE_FINAL_STASHED = 'true'") > preserve.index("stash(name: 'gather-output'"), "표식은 실제 stash 뒤에만"


def test_p3_prep_failure_codes_are_distinct_in_the_shell_and_mapped_in_the_pipeline():
    """P3: 재개 시도가 begin 전에 rc 90 · 91 이외로 끝나면(잠금 · 임시 파일 · 권한) classify 가 앞 시도 기록을 돌려줘 실행 기반 상태로 끝없이 반복했다.
    셸은 단계마다 종료 코드(93 · 94 · 95)와 원인 원문을 남기고, 파이프라인은 새 시도 기록이 없으면 앞 시도 상태를 쓰지 않는다."""
    assert "se_prep_fail() {" in RUN_GATHER
    for code, what in (("95", "잠금 파일"), ("93", "실행 권한"), ("94", "임시")):
        assert re.search(rf"se_prep_fail {code} \"[^\"]*{what}", RUN_GATHER), (code, what)
    assert RUN_GATHER.index("se_prep_fail 95") < RUN_GATHER.index('exec 9>>"$WS/.gather.lock"')
    assert 'chmod +x "$INVENTORY"\n' not in RUN_GATHER, "묵시적 set -e 종료(rc 1)에 맡기지 않는다"
    body = _method("def seAttemptBody")
    assert "boolean newAttempt = recordKnown && attemptsAfter > attemptsBefore" in body
    assert "if (recordKnown && !newAttempt) {" in body and "if (rc in [90, 91, 93, 94, 95]) {" in body
    assert "수집을 시작하지 못했습니다. 종료 코드 ${rc}." in body, "원인이 확인되지 않은 종료는 failed_run — OOM · 인증 · 설정으로 단정하지 않는다"
    assert "new_record=${newAttempt}" in body, "[기술 기록] 줄에 새 기록 여부가 남는다"


def test_p4_kept_uses_explicit_null_check():
    fin = _method("def seFinalizeIn")
    assert "int kept = (report.kept != null) ? (report.kept as int) : (accepted - filled)" in fin
    assert "(report.kept ?: (accepted - filled))" not in TEXT


def test_p5_prep_failed_wording_is_per_cause():
    assert "'prep_failed': '실행 준비 실패(Ansible 환경 없음)'" not in TEXT
    pf = _method("String sePrepFailText")
    assert "'90': 'Ansible 실행 환경(venv)을 찾지 못했습니다'" in pf and "'91': '실행 기록(gather_run.json)을 준비하지 못했습니다'" in pf
    body = _method("def seAttemptBody")
    assert 'unstable("[수집] 실행 준비에 실패해 이번 시도를 시작하지 못했습니다.\\n  원인: ${prepWhy ?: \'-\'}' in body


def test_p6_marker_write_failure_is_checked_with_an_existing_step_before_continuing():
    marker = _method("def seFinMarker")
    assert "writeFile(file: '.se_fin.json'" in marker
    assert "catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie) {\n        throw fie" in marker, "취소 · 한계는 즉시"
    assert "fileExists('.')" in marker, "같은 폴더의 기존 step 으로 실행 문맥을 확인한다"
    assert re.search(r"catch \(Throwable probe\) \{\s*throw e\b", marker), "확인 step 도 실패하면 원본 예외를 그대로"
    assert "fs.marker = 'failed'" in marker and "결과 처리는 계속합니다" in marker
    # 계속하는 조건은 셋 모두 — 쓰기 오류(IOException) · 내부 원인에 연결 종료 없음 · 같은 폴더의 기존 step 정상. 그 밖(하네스가 실행 기반 오류로 주입하는
    #   일반 Exception 포함)은 원본 그대로 다시 던진다 — 하네스 finalize_reentry 의 재진입 기대를 그대로 만족한다
    assert "if (!(e instanceof java.io.IOException) || seHasRemotingCause(e)) { throw e }" in marker
    cause = _method("boolean seHasRemotingCause")
    assert "c.getCause()" in cause and "hudson.remoting." in cause and "return true\n    }\n}" in cause, "확인할 수 없으면 안전한 쪽(원본 전달)"
    clean = _method("def seCleanOldFinalizerDirs")
    assert "findFiles(glob: 'fin-*/.se_fin.json')" in clean, "표식이 있는 폴더만 정리 대상이다 — 표식 없는 폴더는 지우지 않는다"


def test_p7_callback_url_rejects_query_and_fragment():
    v = _stage("입력 확인")
    assert "if (cbUrl.contains('?') || cbUrl.contains('#')) {" in v
    assert "callbackUrl에는 질의 문자열(?)이나 조각(#)을 넣을 수 없습니다" in v


def test_p8_layer_a_shell_distinguishes_missing_script_from_dropped_lines():
    preserve = _method("def sePreserveGatherOutput")
    assert "if [ ! -f scripts/finalize_gather_output.py ]; then" in preserve and "exit 3; fi" in preserve
    assert "(layerA == 3) ? ' (결과 정리 스크립트 없음)' : ''" in preserve


def test_p9_end_record_errors_reach_the_console():
    end_line = next(l for l in RUN_GATHER.splitlines() if 'gather_state.py" end --ws "$WS" --rc "$rc"' in l)
    assert "2>/dev/null" not in end_line


def test_p10_env_copy_of_the_run_record_has_no_ip_lists_but_keeps_consumer_keys():
    strip = _method("String seGatherRunForEnv")
    assert "if (!(ae.key in ['completed_ips', 'precheck_failed_ips', 'lost_ips'])) { m[ae.key] = ae.value }" in strip
    assert "out[e.key] = e.value" in strip, "그 밖의 최상위 키(rc · timed_out · limit_sec · ran_sec)는 그대로"
    assert "groovy.json.JsonOutput.toJson(run)" not in TEXT


def test_p11_synthetic_404_from_the_request_tool_is_not_a_refusal():
    """P11: http_request 1.25 는 이름 풀이 실패(UnknownHostException)를 서버 응답이 아닌 합성 404 로 돌려준다 — 종전에는 모든 404 를 Portal 의 확정 거부로 보고
    다시 보내지 않았다. 판별은 버전이 아니라 응답 형태(도구 고정 문구 + 헤더 없음)로 하고 본문은 기록하지 않는다."""
    cb = _method("def seCallback")
    helper = _method("boolean seIsSyntheticNotFound")
    assert "if (status == 404) { synthetic = seIsSyntheticNotFound(resp) }" in cb
    assert "if (code ==~ /4\\d\\d/ && !(code in ['408', '429']) && !synthetic) {" in cb
    assert "rec.transport = 'unknown_host'" in cb and "Portal 주소를 해석하지 못했습니다" in cb
    assert "'UnknownHostException as 404 Not Found'" in helper and "resp.headers" in helper
    assert "echo" not in helper and "seLog" not in helper, "본문은 비교에만 쓰고 기록하지 않는다"
    assert "resp.content" not in cb, "seCallback 자체는 본문을 읽지 않는다"
    assert "pluginVersion" not in TEXT and "getPlugin(" not in TEXT and "Jenkins.instance" not in TEXT, "플러그인 버전으로 가르지 않는다"


def test_p12_validate_parses_standard_json_only_and_returns_serializable_values():
    """P12: 입력 확인은 표준 JSON 만 받는 파서(JsonSlurper)를 쓰고, 결과는 CPS 가 직렬화할 수 있는 리터럴 컨테이너다. 거부 사유는 [error:] 로 돌려준다."""
    v = _stage("입력 확인")
    assert "Map parsedInventory = seParseJsonStrict(params.inventory_json)" in v
    assert "if (parsedInventory.error) {" in v and "def hosts = parsedInventory.value" in v
    assert not any("readJSON(" in l for l in v.splitlines() if not l.strip().startswith("//")), "입력 확인의 코드 줄에 readJSON 없음"
    parser = _method("Map seParseJsonStrict")
    plain = _method("Object seToPlainJson")
    assert "new groovy.json.JsonSlurper().parseText(t)" in parser and "return [value: seToPlainJson(v)]" in parser
    assert "[error:" in parser and "throw new" not in parser
    assert "Map m = [:]" in plain and "List l = []" in plain
    assert "JsonSlurperClassic" not in TEXT
    # 실측(2026-10-12 임시 Job): JsonSlurper 는 첫 값 뒤의 내용을 무시하고 제어 문자를 받아들인다 — 그 둘은 직접 거부한다
    assert "!t.endsWith(']')" in parser and "c < 0x20 && c != 0x09 && c != 0x0A && c != 0x0D" in parser


def test_sandbox_rejected_constructors_are_not_used():
    """main #520(2026-10-12): sandbox 가 `new java.util.ArrayList` 를 거부해 입력 확인이 실패했다(격리 driver 는 입력 확인을 거치지 않아 보지 못했다).
    Jenkinsfile 의 생성자 호출은 설치 Jenkins 에서 실행이 확인된 것(Date · JsonSlurper)만 허용한다 — 새 생성자는 실제 Job 실행으로 확인한 뒤 여기에 더한다."""
    found = sorted(set(re.findall(r"new\s+([A-Za-z_][\w.]*)\s*\(", TEXT)))
    assert set(found) <= {"Date", "groovy.json.JsonSlurper"}, found


def test_p13_running_state_does_not_claim_the_attempt_preserved_results():
    body = _method("def seAttemptBody")
    seg = body[body.index("if (s in ['runner_oom', 'runner_restart', 'agent_disconnect', 'running']) {"):body.index("Map oc = seOutcomeFromState")]
    assert "if (s == 'running') {" in seg and "이전 수집이 끝나면 남은 대상을 이어서 수집합니다" in seg
    assert "끝난 대상의 결과는 보존했고" not in seg, "보존 전에 보존 완료라고 적지 않는다"
    assert seg.index("seLog(") < seg.index("seSnapshotGatherOutput()"), "넘기는 결과는 seSnapshotGatherOutput 의 줄이 알린다"
