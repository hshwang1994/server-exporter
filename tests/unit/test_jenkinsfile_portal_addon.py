"""Jenkinsfile_portal 의 Add-on 계약 (텍스트).

Add-on 은 Jenkins 전역 환경변수 ADDON_REPO_URL 하나로 켜고, 서버 정보 수집의 시도(seAddonPrepare)가 저장소를 받아
그 경로를 ansible 실행에만 ADDON_DIR 로 넘긴다. 여기서 고정하는 것:
  - ADDON_DIR 을 정하는 곳은 ansible 실행을 감싼 withEnv 한 곳 (${WORKSPACE}/addon). stage / pipeline environment{} 에 없다
  - ADDON_REPO_URL 이 없으면 Add-on 코드가 실행되지 않는다 (if 게이트)
  - 체크아웃은 scripts/addon_checkout.sh (fetch 흐름, retry 2회), 검사는 addon/tools/check_layout.py --targets <서버 종류>
  - 실패는 unstable("[addon] unavailable: …") — error 로 빌드를 끊지 않고, 빌드 설명(currentBuild.description)도 건드리지 않는다
  - 노드 경로 · 배포 Job · 라벨 기반 배포 · 전역 git 설정 · GIT_SSL_NO_VERIFY 의 흔적이 없다
  - Add-on ref 는 전역 ADDON_REPO_REF(없으면 main) 하나다 — 빌드마다 ref 를 바꾸는 Job 파라미터는 두지 않는다
  - (9차 W09) 결정(사용 여부 · 받은 commit · 문제)을 작업 폴더의 .se_addon.json 에 남기고, 이어서 하는 시도는 다시 받지 않고 그 결정을 쓴다
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
JENKINSFILE = REPO_ROOT / "Jenkinsfile_portal"
TEXT = JENKINSFILE.read_text(encoding="utf-8")


def _stage(name: str) -> str:
    start = TEXT.index(f"stage('{name}')")
    nxt = re.search(r"\n        stage\('", TEXT[start + 1:])
    return TEXT[start: start + 1 + nxt.start()] if nxt else TEXT[start:]


def _func(signature: str) -> str:
    start = TEXT.index(signature)
    return TEXT[start: TEXT.index("\n}\n", start) + 2]


ADDON = _func("String seAddonPrepare(String targetType, Map st) {")
BODY = _func("def seAttemptBody(Map C, Map st, Map r) {")
PREP = _func("def sePrepareWorkspace(String targetType, Map own) {")
READ = _func("Map seReadJsonFile(String path) {")
VALIDATE = _stage("입력 확인")


def test_se_addon_dir_is_set_only_for_the_ansible_run():
    hits = [m.start() for m in re.finditer(r"ADDON_DIR=", TEXT)]
    assert len(hits) == 1, "ADDON_DIR 을 정하는 곳은 한 곳"
    line = TEXT[TEXT.rfind("\n", 0, hits[0]) + 1: TEXT.find("\n", hits[0])]
    assert "withEnv(" in line and '${addonDir}' in line and "? [" in line and ": []" in line, line
    assert hits[0] > TEXT.index("def seAttemptBody(") and "run_gather.sh" in BODY[BODY.index("ADDON_DIR="):], "ansible 실행만 감싼다"
    assert 'addonDir = "${env.WORKSPACE}/addon".toString()' in ADDON
    for block in re.findall(r"environment \{[^}]*\}", TEXT):
        assert "ADDON_" not in block, "environment{} 에 두면 꺼진 빌드의 환경까지 바뀐다"


def test_everything_is_gated_on_the_global_repo_variable():
    assert "String addonRepo = (env.ADDON_REPO_URL ?: '').trim()" in ADDON
    assert "if (!addonRepo) { return '' }" in ADDON
    assert "ADDON_REPO_URL" not in VALIDATE, "Validate 는 Add-on 을 모른다 — 켜지지 않은 환경에서 파라미터 검증만"


def test_checkout_uses_the_script_with_retry_and_optional_credentials():
    assert 'bash scripts/addon_checkout.sh "${addonRepo}" "${addonRef}" "\\${WORKSPACE}/addon"' in ADDON
    assert "retry(2)" in ADDON
    assert "usernamePassword(credentialsId: addonCred" in ADDON
    assert 'GIT_ASKPASS=${env.WORKSPACE}/scripts/addon_askpass.sh' in ADDON
    assert "checkout(" not in ADDON and "GitSCM" not in ADDON, "Add-on 은 Git 플러그인이 아니라 스크립트로 받는다 (검증 해제 범위를 명령 하나로 한정)"
    assert (REPO_ROOT / "scripts" / "addon_checkout.sh").is_file()
    assert (REPO_ROOT / "scripts" / "addon_askpass.sh").is_file()


def test_ref_is_the_global_variable_or_main():
    assert "String addonRef = (env.ADDON_REPO_REF ?: '').trim() ?: 'main'" in ADDON


def test_layout_check_runs_in_the_venv_with_this_builds_targets():
    assert "['os': 'linux,windows', 'esxi': 'esxi', 'redfish': 'redfish'][targetType]" in ADDON
    check = ADDON[ADDON.index("check_layout.py addon") - 600: ADDON.index("check_layout.py addon") + 80]
    assert "activate_ansible_venv.sh" in check, "PyYAML 은 venv 에 있다"
    assert 'python3 addon/tools/check_layout.py addon --targets "${addonTargets}"' in ADDON
    assert "rc == 3" in ADDON and "실행할 추가 수집 기능이 없어 Add-on 없이 수집합니다" in ADDON, "Add-on 이 지원하지 않는 서버 종류는 켜지 않는다 (UNSTABLE 아님)"


def test_failure_marks_the_build_unstable_without_per_host_errors():
    assert 'unstable("[addon] unavailable: ${problem}")' in ADDON
    assert ADDON.count("[addon] unavailable:") >= 2, "콘솔 echo + unstable 메시지"
    assert "currentBuild.description" not in ADDON, "빌드 설명은 실행 기반 대기만 쓴다"
    assert "error " not in ADDON and "error(" not in ADDON, "Add-on 문제로 빌드를 끊지 않는다"


def test_decision_is_recorded_and_reused_by_the_next_attempt():
    """W09 — 이어서 하는 시도는 저장소를 다시 받지 않고 앞 시도의 결정(사용 여부 · commit)을 쓴다."""
    assert "Map rec = seReadJsonFile('.se_addon.json')" in ADDON and "d?.decided == true" in ADDON
    reuse = ADDON[ADDON.index("if (d?.decided == true) {"): ADDON.index("} else if (rec.state == 'corrupt'")]
    assert "return ''" in reuse and 'return "${env.WORKSPACE}/addon".toString()' in reuse
    assert "addonRef = d.commit.toString()" in reuse, "사본이 없어졌으면 같은 commit 으로 다시 받는다"
    assert "writeFile(file: '.se_addon.json'" in ADDON and "decided: true" in ADDON and "commit: commit" in ADDON
    assert ADDON.index("writeFile(file: '.se_addon.json'") < ADDON.index('unstable("[addon] unavailable:'), "결정을 먼저 남긴다"
    assert "rev-parse HEAD" in ADDON
    assert "String addonDir = seAddonPrepare(targetType, st)" in BODY
    assert ".se_addon.json" in PREP[PREP.index("이전 실행의 결과 파일 정리"):PREP.index("이전 실행의 결과 파일 정리") + 600], "새 빌드의 처음 시도는 지난 결정을 지운다"


def test_decision_read_errors_are_not_treated_as_a_missing_decision():
    """10차 R4 — 결정 파일 읽기의 예외(Runner 연결 끊김 등)를 '결정 없음' 으로 바꿔 기본 ref 를 새로 받지 않는다.
    읽기 예외는 seReadJsonFile 이 감싸지 않고 상위 retry(agent(), nonresumable())로 넘긴다. 손상(해석 불가)일 때만 결정을 다시 세운다."""
    assert "readJSON(file: '.se_addon.json'" not in ADDON and "d = null" not in ADDON
    read_stmt = "String text = readFile(file: path, encoding: 'UTF-8')"
    assert read_stmt in READ
    before = READ[:READ.index(read_stmt)]
    assert "try {" not in before, "파일 읽기는 try 밖이다 — 실행 기반 예외가 원래 형태로 위로 간다"
    assert "readJSON(text: text, returnPojo: true)" in READ and "[state: 'corrupt'" in READ and "[state: 'absent']" in READ
    corrupt = ADDON[ADDON.index("} else if (rec.state == 'corrupt'"): ADDON.index("String addonCred")]
    assert "addonRef = kept" in corrupt and "fetch = false" in corrupt, "손상: 작업 폴더의 사본 commit 으로 다시 검사한다(다른 ref 로 바꾸지 않는다)"
    assert "problem: 'decision_unreadable'" in corrupt and "unstable(" in corrupt, "사본도 없이 수집을 시작했으면 Add-on 없이 수집하고 알린다"
    assert "st.gather_started == true" in corrupt
    assert "if (fetch) {" in ADDON and ADDON.index("if (fetch) {") < ADDON.index("retry(2)")


def test_no_traces_of_node_paths_deploy_job_or_global_git_settings():
    # (SE_AGENT_LABEL 은 Resolve Location 의 정상 변수 — 배포 Job 의 파라미터 형태만 금지한다)
    for forbidden in ("/home/cloviradmin", "ADDON_HOME", "params.AGENT_LABEL", "'AGENT_LABEL'", "GIT_SSL_NO_VERIFY",
                      "git config --global", "http.sslVerify", "deploy/Jenkinsfile", "ADDON_DIR=/"):
        assert forbidden not in TEXT, forbidden


def test_no_per_build_addon_ref_parameter():
    params = TEXT[TEXT.index("parameters {"): TEXT.index("environment {")]
    assert "addonRef" not in params, "운영 Job 에 검증용 ref 파라미터를 두지 않는다"
    assert "params.addonRef" not in TEXT and "addonRef" not in VALIDATE


@pytest.mark.parametrize("stage", ["실행 위치 확인", "입력 확인"])   # 2026-10-03: Validate Schema·Callback stage 는 없다
def test_other_stages_are_untouched_by_addon(stage):
    assert "addon" not in _stage(stage).lower()


def test_file_has_lf_line_endings():
    assert b"\r\n" not in JENKINSFILE.read_bytes()
