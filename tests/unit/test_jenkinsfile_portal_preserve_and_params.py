"""Jenkinsfile_portal — 접수 manifest · 운영 파라미터 · 보존의 텍스트 계약 (2026-10-03 Phase 1.5/4, 2026-10-05 8차 R1 개정).

무엇이 고정되나:
  1. stage 순서 입력 확인 → 실행 위치 확인 → 서버 정보 수집. 앞 둘은 agent 없이 돈다 (workspace 없음 → writeFile 금지).
  2. 접수 manifest: 입력 확인이 env.SE_MANIFEST_JSON(JSON 문자열)으로 만들고 수집 단계가 node 진입 직후
     gather_manifest.json 으로 파일화한다 — 수집 실행(scripts/run_gather.sh)보다 먼저.
  3. 운영 파라미터는 7개뿐이다(8차 R1): loc · target_type · inventory_json · deploymentEnvironmentId · eventUuid · callbackUrl · verbosity.
     시험 전용 파라미터(redfishAccountDryrun · gatherBudgetForceSec)와 그 배선(-e _rf_account_service_dryrun · SE_FORCE_SEC · 빌드 이름의
     [시험: …])은 운영 코드에 없다. 계정 쓰기 모의와 강제 중단 시험은 main 의 시험 경로가 같은 운영 코드를 실행해 확인한다.
  4. 수집 단계 post{always}: 결과 정리 → 정리 → 보관 → 전달 → (보존 확인 뒤) 작업 폴더 삭제. steps 안의 stash 는 없다.
  5. inventory_json 의 구조 오류(배열 아님 · 원소가 객체 아님)는 NPE 대신 명확한 오류 — 새 거부는 없다.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
JENKINSFILE = REPO_ROOT / "Jenkinsfile_portal"
TEXT = JENKINSFILE.read_text(encoding="utf-8")
RUN_GATHER = (REPO_ROOT / "scripts" / "run_gather.sh").read_text(encoding="utf-8")
RUN_CALL = r'bash "\${WORKSPACE}/scripts/run_gather.sh"'


def _stage(name: str) -> str:
    start = TEXT.index(f"stage('{name}')")
    nxt = re.search(r"\n        stage\('", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


def _params() -> str:
    start = TEXT.index("    parameters {")
    return TEXT[start: TEXT.index("    environment {", start)]


def _method(name: str) -> str:
    start = TEXT.index(f"{name}(")
    start = TEXT.rfind("\n", 0, start) + 1
    nxt = re.search(r"\n(?:@NonCPS\n)?(?:def |Map |String |boolean |long |pipeline \{)", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


VALIDATE = _stage("입력 확인")
RESOLVE = _stage("실행 위치 확인")
GATHER = _stage("서버 정보 수집")
PARAMS = _params()
OPERATIONAL_PARAMS = ["loc", "target_type", "inventory_json", "deploymentEnvironmentId", "eventUuid", "callbackUrl", "verbosity"]


def test_stage_order_validate_then_resolve_then_gather():
    order = [TEXT.index(f"stage('{n}')") for n in ("입력 확인", "실행 위치 확인", "서버 정보 수집")]
    assert order == sorted(order), "구조가 틀린 요청은 노드를 고르기 전에 끝낸다"


def test_validate_and_resolve_run_without_agent_or_workspace():
    for name, stage in (("입력 확인", VALIDATE), ("실행 위치 확인", RESOLVE)):
        assert "agent {" not in stage, name
        assert "writeFile(" not in stage, f"{name} 에는 workspace 가 없다"
        assert "deleteDir(" not in stage, name
        assert "skipDefaultCheckout" not in stage, name
        assert "timeout(time: 5, unit: 'MINUTES')" in stage, name


def test_resolve_reads_registry_with_read_trusted_only():
    assert "readYaml text: seTrusted('common/vars/locations.yml')" in RESOLVE
    assert "readTrusted(" not in RESOLVE
    assert "checkout scm" not in RESOLVE and "checkout(" not in RESOLVE and "readYaml file:" not in RESOLVE


def test_manifest_is_env_json_in_validate_and_a_file_at_gather_entry():
    assert "env.SE_MANIFEST_JSON = groovy.json.JsonOutput.toJson([" in VALIDATE
    for key in ("schema : 1", "build  : [job: env.JOB_NAME, number: env.BUILD_NUMBER, url: env.BUILD_URL]",
                "channel: params.target_type.trim()", "ips    : acceptedIps"):
        assert key in VALIDATE, key
    assert TEXT.count("SE_MANIFEST_JSON =") == 1, "manifest 를 만드는 곳은 입력 확인 한 곳"
    write = GATHER.index("writeFile(file: 'gather_manifest.json', text: (env.SE_MANIFEST_JSON ?: '') + '\\n', encoding: 'UTF-8')")
    assert write < GATHER.index(RUN_CALL), "manifest 파일화는 수집보다 먼저"
    assert write > GATHER.index("steps {"), "node 를 얻은 뒤(steps 안)에 쓴다"


def test_only_operational_parameters_are_declared():
    """8차 R1 — 운영 Job 의 입력은 Portal 호출 계약의 7개뿐이다."""
    names = re.findall(r"name\s*:\s*'([^']+)'", PARAMS)
    assert names == OPERATIONAL_PARAMS
    assert "booleanParam(" not in PARAMS


def test_removed_test_parameters_and_their_wiring_are_gone():
    """시험 전용 기능을 이름만 바꿔 남기지 않는다 — 운영 코드 어디에도 그 배선이 없다."""
    for gone in ("redfishAccountDryrun", "gatherBudgetForceSec", "_rf_account_service_dryrun", "SE_FORCE_SEC", "budgetForce",
                 "EXTRA_ARGS", "[시험:", "testTags", "limit_source=forced", "'forced'"):
        assert gone not in TEXT, gone
    for gone in ("_rf_account_service_dryrun", "SE_FORCE_SEC", "EXTRA_ARGS"):
        assert gone not in RUN_GATHER, gone
    # 예전 이름으로 값이 들어와도 읽는 곳이 없다 — params.<이름> · env.<이름> 모두
    assert not re.search(r"params\.(redfishAccountDryrun|gatherBudgetForceSec)|env\.(redfishAccountDryrun|gatherBudgetForceSec)", TEXT)


def test_run_gather_receives_only_the_computed_limit():
    seg = GATHER[GATHER.index(RUN_CALL):]
    seg = seg[: seg.index("\n")]
    assert '"${exec.limit}"' in seg and '"${exec.forks}"' in seg, "한계는 바로 앞에서 계산한 값뿐"
    assert 'timeout --signal=INT --kill-after=90 "$LIMIT"' in RUN_GATHER
    assert 'echo "$rc" > "$WS/gather_rc.txt"' in RUN_GATHER
    assert '"timed_out":%s' in RUN_GATHER and '[ "$ran" -ge "$LIMIT" ]' in RUN_GATHER, "한계 도달은 실제 실행 시간으로 확인한다"


def test_gather_post_preserves_output_before_deleting_the_workspace():
    assert "sePreserveGatherOutput()" in GATHER[GATHER.index("post {"):], "수집 단계 post{always} 는 보존 helper 를 부른다 (R7)"
    post = _method("def sePreserveGatherOutput")
    archive = post.index("archiveArtifacts(artifacts: archiveList.join(','), allowEmptyArchive: false")
    stash = re.search(r"^\s*stash\(name: 'gather-output'", post, re.M).start()
    delete = post.index("deleteDir()")
    assert archive < stash < delete, "archive → stash → deleteDir"
    assert "allowEmpty: true" in post
    assert len(re.findall(r"^\s*stash\(", TEXT, re.M)) == 1, "steps 안의 stash 는 없다 — 보존은 post{always} 한 곳"
    assert "unstash 'gather-output'" in TEXT, "결과 확인 단계가 같은 stash 를 회수한다"


def test_inventory_shape_errors_are_explicit_without_new_rejections():
    assert "hosts = readJSON(text: params.inventory_json, returnPojo: true)" in VALIDATE
    assert "JsonSlurperClassic" not in TEXT
    parse = VALIDATE[VALIDATE.index("hosts = readJSON("):]
    assert "catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException fie)" in parse[:600]
    assert "seAcceptTargets(hosts, params.target_type.trim())" in VALIDATE
    assert "inventory_json 은 JSON 배열이어야 합니다" in TEXT
    assert "은 객체여야 합니다" in TEXT
    for forbidden in ("SE_MAX_HOSTS", "eventUuid 형식", "제어문자"):
        assert forbidden not in TEXT, f"새 거부 규칙({forbidden})은 별도 계약 결정(Q2) 전에는 없다"


def test_file_has_lf_line_endings():
    assert b"\r\n" not in JENKINSFILE.read_bytes()
