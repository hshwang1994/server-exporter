"""Jenkinsfile_portal — 접수 manifest · 운영 파라미터 · 보존의 텍스트 계약 (2026-10-03 Phase 1.5/4, 2026-10-05 8차 R1, 2026-10-06 9차 개정).

무엇이 고정되나:
  1. stage 순서 입력 확인 → 실행 위치 확인 → 서버 정보 수집. 앞 둘은 agent 없이 돈다 (workspace 없음 → writeFile 금지).
  2. 접수 manifest: 입력 확인이 env.SE_MANIFEST_JSON(JSON 문자열)으로 만들고 수집의 첫 시도(seAttemptBody)가 node 를 얻은 뒤
     gather_manifest.json 으로 파일화한다 — 수집 실행(scripts/run_gather.sh)보다 먼저. 이어서 하는 시도는 다시 쓰지 않는다.
  3. 운영 파라미터는 7개뿐이다(8차 R1): loc · target_type · inventory_json · deploymentEnvironmentId · eventUuid · callbackUrl · verbosity.
     시험 전용 파라미터(redfishAccountDryrun · gatherBudgetForceSec)와 그 배선(-e _rf_account_service_dryrun · SE_FORCE_SEC · 빌드 이름의
     [시험: …])은 운영 코드에 없다. 계정 쓰기 모의와 강제 중단 시험은 main 의 시험 경로가 같은 운영 코드를 실행해 확인한다.
  4. 결과 보존(9차): 마지막 시도가 결과 정리 → 정리 → 보관 → 전달 → (보존 확인 뒤) 작업 폴더 삭제를 한다. 실행 기반 장애로
     다시 시도하기 전에는 원본 결과만 전달(stash)하고 작업 폴더는 그대로 둔다.
  5. inventory_json 의 구조 오류(배열 아님 · 원소가 객체 아님)는 NPE 대신 명확한 오류 — 새 거부는 없다.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
JENKINSFILE = REPO_ROOT / "Jenkinsfile_portal"
TEXT = JENKINSFILE.read_text(encoding="utf-8")
RUN_GATHER = (REPO_ROOT / "scripts" / "run_gather.sh").read_text(encoding="utf-8")
GATHER_STATE = (REPO_ROOT / "scripts" / "gather_state.py").read_text(encoding="utf-8")
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
    nxt = re.search(r"\n(?:@NonCPS\n)?(?:def |Map |String |boolean |long |List |pipeline \{)", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


VALIDATE = _stage("입력 확인")
RESOLVE = _stage("실행 위치 확인")
GATHER = _stage("서버 정보 수집")
BODY = _method("def seAttemptBody")
PREP = _method("def sePrepareWorkspace")
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


def test_manifest_is_env_json_in_validate_and_a_file_at_the_first_attempt():
    assert "env.SE_MANIFEST_JSON = groovy.json.JsonOutput.toJson([" in VALIDATE
    for key in ("schema : 1", "build  : [job: env.JOB_NAME, number: env.BUILD_NUMBER, url: env.BUILD_URL, nonce: env.SE_BUILD_NONCE]",
                "channel: params.target_type.trim()", "ips    : acceptedIps"):
        assert key in VALIDATE, key
    # FL-F06 (2026-10-10): 빌드 인스턴스 표식은 접수 때 한 번 만든다 — manifest 와 작업 폴더 소유 기록이 같은 값을 들고, envelope 에는 들어가지 않는다
    assert 'env.SE_BUILD_NONCE = "${env.BUILD_TAG}-${seNowMs()}".toString()' in VALIDATE
    assert VALIDATE.index("env.SE_BUILD_NONCE =") < VALIDATE.index("env.SE_MANIFEST_JSON =")
    assert TEXT.count("SE_BUILD_NONCE =") == 1
    assert TEXT.count("SE_MANIFEST_JSON =") == 1, "manifest 를 만드는 곳은 입력 확인 한 곳"
    marker = "writeFile(file: 'gather_manifest.json', text: (env.SE_MANIFEST_JSON ?: '') + '\\n', encoding: 'UTF-8')"
    assert TEXT.count(marker) == 1 and marker in PREP, "첫 준비(sePrepareWorkspace)가 쓴다"
    assert BODY.index("sePrepareWorkspace(targetType, null)") < BODY.index(RUN_CALL), "manifest 파일화는 수집보다 먼저"
    # 10차 R3: 이어서 하는 시도는 접수 목록 파일만 없을 때 이 빌드의 접수 원본으로 다시 쓴다(결과 파일은 그대로) — 원본이 이 빌드의 것이 아니면 재개 불가
    restore = BODY[BODY.index("if (!fileExists('gather_manifest.json')) {"):BODY.index("seLog(\"[수집] 같은 Runner")]
    assert "seManifestIsThisBuild(env.SE_MANIFEST_JSON ?: '')" in restore and "outcome: 'resume_impossible'" in restore
    assert "writeFile(file: 'gather_manifest.json', text: env.SE_MANIFEST_JSON + '\\n', encoding: 'UTF-8')" in restore
    assert "rm -rf" not in restore, "복원할 때 결과 파일을 지우지 않는다"
    check = _method("boolean seManifestIsThisBuild")
    assert '"${m.build?.job}" == "${env.JOB_NAME}"' in check and '"${m.build?.number}" == "${env.BUILD_NUMBER}"' in check
    assert "seSameBuildNonce(m.build?.nonce)" in check, "접수 원본 복원도 같은 빌드 인스턴스인지 본다 (FL-F06)"


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


def test_run_gather_receives_only_the_accumulated_limit():
    """9차 — 파이프라인은 누적 최대(6시간)만 넘긴다. 이번 시도의 한계(최대 − 누적 실제 수집 시간)는 Runner 의 실행 기록이 정한다."""
    seg = BODY[BODY.index(RUN_CALL):]
    seg = seg[: seg.index("\n")]
    assert '"${C.GATHER_MAX}"' in seg and "\"${lostPrev ? 'true' : 'false'}\"" in seg, seg
    assert "exec.limit" not in TEXT and "exec.forks" not in TEXT, "남은 빌드 시간으로 한계를 줄이던 계산은 없다"
    assert 'timeout --signal=INT --kill-after=90 "$LIMIT"' in RUN_GATHER
    assert 'gather_state.py" begin' in RUN_GATHER and 'gather_state.py" end' in RUN_GATHER
    assert "limit = max(0, int(gather_max) - used)" in GATHER_STATE
    assert "timed_out = rc in (124, 137) and exec_sec >= int(limit or 0)" in GATHER_STATE, "한계 도달은 실제 실행 시간으로 확인한다"


def test_last_attempt_preserves_output_before_deleting_the_workspace():
    assert BODY.rstrip().endswith("sePreserveGatherOutput()\n}"), "마지막 시도의 끝은 보존이다"
    post = _method("def sePreserveGatherOutput")
    archive = post.index("archiveArtifacts(artifacts: archiveList.join(','), allowEmptyArchive: false")
    stash = re.search(r"^\s*stash\(name: 'gather-output'", post, re.M).start()
    delete = post.index("deleteDir()")
    assert archive < stash < delete, "archive → stash → deleteDir"
    assert "allowEmpty: true" in post
    snap = _method("def seSnapshotGatherOutput")
    assert "stash(name: 'gather-output'" in snap and "deleteDir" not in snap and "archiveArtifacts" not in snap, \
        "다시 시도하기 전에는 원본만 넘긴다 — 작업 폴더는 다음 시도가 쓴다"
    assert len(re.findall(r"^\s*stash\(", TEXT, re.M)) == 2, "stash 는 마지막 보존 · 중간 보존 두 곳"
    assert "unstash 'gather-output'" in TEXT, "결과 확인 단계가 같은 stash 를 회수한다"
    assert "post {" not in GATHER.split("\n    post {")[0], "수집 단계에는 post 가 없다 — 보존은 시도 안에서 한다(Runner 가 없을 때 post 가 node 를 기다리지 않게)"


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
