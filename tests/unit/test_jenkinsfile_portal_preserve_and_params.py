"""Jenkinsfile_portal — 2026-10-03 Phase 1.5/4 의 텍스트 계약 (접수 manifest · 검증 파라미터 · 보존).

무엇이 고정되나:
  1. stage 순서 Validate → Resolve Location → Gather. Validate · Resolve Location 은 agent 없이 돈다 (workspace 없음 → writeFile 금지).
  2. 접수 manifest: Validate 가 env.SE_MANIFEST_JSON(JSON 문자열)으로 만들고 Gather 가 node 진입 직후
     gather_manifest.json 으로 파일화한다 — ansible-playbook 보다 먼저.
  3. 검증용 파라미터 둘: redfishAccountDryrun(기본 false → -e _rf_account_service_dryrun=true 는 true 일 때만),
     gatherBudgetForceSec(기본 '' → 값이 있을 때만 SE_FORCE_SEC 로 예산 스크립트에 전달; 남은 시간을 넘지 못한다).
  4. Gather post{always}: Layer A → archiveArtifacts → stash(allowEmpty) → deleteDir(보존 확인 뒤) 순. steps 안의 stash 는 없다.
  5. inventory_json 의 구조 오류(배열 아님 · 원소가 객체 아님)는 NPE 대신 명확한 오류 — 새 거부는 없다.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
JENKINSFILE = REPO_ROOT / "Jenkinsfile_portal"
TEXT = JENKINSFILE.read_text(encoding="utf-8")


def _stage(name: str) -> str:
    start = TEXT.index(f"stage('{name}')")
    nxt = re.search(r"\n        stage\('", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


def _params() -> str:
    start = TEXT.index("    parameters {")
    return TEXT[start: TEXT.index("    environment {", start)]


VALIDATE = _stage("Validate")
RESOLVE = _stage("Resolve Location")
GATHER = _stage("Gather")
PARAMS = _params()


def test_stage_order_validate_then_resolve_then_gather():
    order = [TEXT.index(f"stage('{n}')") for n in ("Validate", "Resolve Location", "Gather")]
    assert order == sorted(order), "구조가 틀린 요청은 노드를 고르기 전에 끝낸다"


def test_validate_and_resolve_run_without_agent_or_workspace():
    for name, stage in (("Validate", VALIDATE), ("Resolve Location", RESOLVE)):
        assert "agent {" not in stage, name
        assert "writeFile(" not in stage, f"{name} 에는 workspace 가 없다"
        assert "deleteDir(" not in stage, name
        assert "skipDefaultCheckout" not in stage, name
        assert "timeout(time: 2, unit: 'MINUTES')" in stage, name


def test_resolve_reads_registry_with_read_trusted_only():
    assert "readYaml text: seTrusted('common/vars/locations.yml')" in RESOLVE, "readTrusted 는 seTrusted(식별 echo)를 지난다"
    assert "readTrusted(" not in RESOLVE
    assert "checkout scm" not in RESOLVE and "checkout(" not in RESOLVE and "readYaml file:" not in RESOLVE


def test_manifest_is_env_json_in_validate_and_a_file_at_gather_entry():
    assert "env.SE_MANIFEST_JSON = groovy.json.JsonOutput.toJson([" in VALIDATE
    for key in ("schema : 1", "build  : [job: env.JOB_NAME, number: env.BUILD_NUMBER, url: env.BUILD_URL]",
                "channel: params.target_type.trim()", "ips    : acceptedIps"):
        assert key in VALIDATE, key
    assert TEXT.count("SE_MANIFEST_JSON =") == 1, "manifest 를 만드는 곳은 Validate 한 곳"
    write = GATHER.index("writeFile(file: 'gather_manifest.json', text: (env.SE_MANIFEST_JSON ?: '') + '\\n', encoding: 'UTF-8')")
    assert write < GATHER.index("ansible-playbook "), "manifest 파일화는 수집보다 먼저"
    assert write > GATHER.index("steps {"), "node 를 얻은 뒤(steps 안)에 쓴다"


def test_verification_params_default_to_production_behaviour():
    assert re.search(r"booleanParam\(\s*name\s*:\s*'redfishAccountDryrun',\s*defaultValue:\s*false", PARAMS)
    assert re.search(r"string\(\s*name\s*:\s*'gatherBudgetForceSec',\s*defaultValue:\s*''", PARAMS)


def test_dryrun_flag_is_passed_only_when_the_param_is_true():
    assert 'if [ "${params.redfishAccountDryrun}" = "true" ]; then' in GATHER
    assert TEXT.count("EXTRA_ARGS+=(-e _rf_account_service_dryrun=true)") == 1, "넘기는 곳은 guard 안 한 곳"
    assert TEXT.count("-e _rf_account_service_dryrun=true") == 2, "shell 의 guard 안 1곳 + 파라미터 설명 1곳 외에는 없다"
    guard = GATHER.index('if [ "${params.redfishAccountDryrun}" = "true" ]; then')
    assert guard < GATHER.index("EXTRA_ARGS+=(-e _rf_account_service_dryrun=true)")


def test_budget_force_goes_through_the_budget_script_only():
    assert "budgetForce ==~ /\\d+/" in GATHER, "정수(초)만 받는다"
    # 2026-10-05 (F12): 강제값은 파라미터에서만 — 비어 있어도 SE_FORCE_SEC= 를 명시해 상위 환경 값을 덮는다 (tests/unit/test_env_guard.py)
    assert "SE_FORCE_SEC=${budgetForce} " in GATHER
    assert "SE_GATHER_BUDGET_FORCE_SEC" not in TEXT, "강제값이 timeout 에 직접 들어가지 않는다 — 스크립트가 남은 시간으로 자른다"
    assert 'timeout --signal=INT --kill-after=90 "\\${SE_GATHER_BUDGET_SEC}"' in GATHER
    assert 'echo "\\$rc" > "\\${WORKSPACE}/gather_rc.txt"' in GATHER
    assert "-eq 124" in GATHER and "-eq 137" in GATHER, "timeout 의 rc 를 콘솔에 남긴다"


def _method(name: str) -> str:
    start = TEXT.index(f"{name}(")
    start = TEXT.rfind("\n", 0, start) + 1
    nxt = re.search(r"\n(?:@NonCPS\n)?(?:def |Map |String |boolean |long |pipeline \{)", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


def test_gather_post_preserves_output_before_deleting_the_workspace():
    assert "sePreserveGatherOutput()" in GATHER[GATHER.index("post {"):], "Gather post{always} 는 보존 helper 를 부른다 (R7)"
    post = _method("def sePreserveGatherOutput")
    archive = post.index("archiveArtifacts(artifacts: 'gather_output.json,gather_manifest.json,gather_rc.txt")
    stash = re.search(r"^\s*stash\($", post, re.M).start()
    delete = post.index("deleteDir()")
    assert archive < stash < delete, "archive → stash → deleteDir"
    assert "allowEmpty : true" in post
    assert len(re.findall(r"^\s*stash\($", TEXT, re.M)) == 1, "steps 안의 stash 는 없다 — 보존은 post{always} 한 곳"
    assert "unstash 'gather-output'" in TEXT, "finalizer 가 같은 stash 를 회수한다"


def test_inventory_shape_errors_are_explicit_without_new_rejections():
    # 2026-10-03 main #2 실측: `new JsonSlurperClassic()` 은 Jenkins sandbox 가 거부해 Validate 가 끝났다(접수 manifest 없음 → Callback 0건).
    #   파서는 sandbox 가 허용하는 readJSON(returnPojo) 하나다. 승인(In-process Script Approval)을 전제하는 API 는 운영 파이프라인에 두지 않는다.
    assert "hosts = readJSON(text: params.inventory_json, returnPojo: true)" in VALIDATE
    assert "JsonSlurperClassic" not in TEXT, "sandbox 가 거부하는 생성자 — 운영 파이프라인에 두지 않는다"
    parse = VALIDATE[VALIDATE.index("hosts = readJSON("):]
    assert "catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)" in parse[:600], "파싱 실패 처리는 interruption 을 삼키지 않는다"
    # 2026-10-05 (F03): 원소 규칙은 inventory.sh 와 같은 함수 seAcceptTargets 로 옮겼다 (tests/unit/test_input_acceptance_parity.py)
    assert "seAcceptTargets(hosts, params.target_type.trim())" in VALIDATE
    assert "inventory_json 은 JSON 배열이어야 합니다" in TEXT
    assert "은 객체여야 합니다" in TEXT
    for forbidden in ("SE_MAX_HOSTS", "eventUuid 형식", "제어문자"):
        assert forbidden not in TEXT, f"새 거부 규칙({forbidden})은 별도 계약 결정(Q2) 전에는 없다"


def test_file_has_lf_line_endings():
    assert b"\r\n" not in JENKINSFILE.read_bytes()
