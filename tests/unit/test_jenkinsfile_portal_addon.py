"""Jenkinsfile_portal 의 Add-on 계약 (텍스트).

Add-on 은 Jenkins 전역 환경변수 ADDON_REPO_URL 하나로 켜고, Gather stage 가 빌드마다 저장소를 받아
그 경로를 ansible 실행에만 ADDON_DIR 로 넘긴다. 여기서 고정하는 것:
  - ADDON_DIR 을 정하는 곳은 Gather stage 의 withEnv 한 곳 (${WORKSPACE}/addon). stage / pipeline environment{} 에 없다
  - ADDON_REPO_URL 이 없으면 Add-on 코드가 실행되지 않는다 (if 게이트)
  - 체크아웃은 scripts/addon_checkout.sh (fetch 흐름, retry 2회), 검사는 addon/tools/check_layout.py --targets <서버 종류>
  - 실패는 unstable("[addon] unavailable: …") — error 로 빌드를 끊지 않고, currentBuild.description 도 건드리지 않는다
  - 노드 경로 · 배포 Job · 라벨 기반 배포 · 전역 git 설정 · GIT_SSL_NO_VERIFY 의 흔적이 없다
  - Add-on ref 는 전역 ADDON_REPO_REF(없으면 main) 하나다 — 빌드마다 ref 를 바꾸는 Job 파라미터는 두지 않는다
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


GATHER = _stage("서버 정보 수집")
VALIDATE = _stage("입력 확인")


def test_se_addon_dir_is_set_only_for_the_ansible_run():
    hits = [m.start() for m in re.finditer(r"ADDON_DIR=", TEXT)]
    assert len(hits) == 1, "ADDON_DIR 을 정하는 곳은 한 곳"
    line = TEXT[TEXT.rfind("\n", 0, hits[0]) + 1: TEXT.find("\n", hits[0])]
    assert "withEnv(" in line and '${addonDir}' in line and "? [" in line and ": []" in line, line
    assert 'addonDir = "${env.WORKSPACE}/addon"' in GATHER
    for block in re.findall(r"environment \{[^}]*\}", TEXT):
        assert "ADDON_" not in block, "environment{} 에 두면 꺼진 빌드의 환경까지 바뀐다"


def test_everything_is_gated_on_the_global_repo_variable():
    assert "def addonRepo = (env.ADDON_REPO_URL ?: '').trim()" in GATHER
    assert "if (addonRepo) {" in GATHER
    assert "ADDON_REPO_URL" not in VALIDATE, "Validate 는 Add-on 을 모른다 — 켜지지 않은 환경에서 파라미터 검증만"


def test_checkout_uses_the_script_with_retry_and_optional_credentials():
    assert 'bash scripts/addon_checkout.sh "${addonRepo}" "${addonRef}" "\\${WORKSPACE}/addon"' in GATHER
    assert "retry(2)" in GATHER
    assert "usernamePassword(credentialsId: addonCred" in GATHER
    assert 'GIT_ASKPASS=${env.WORKSPACE}/scripts/addon_askpass.sh' in GATHER
    assert "checkout(" not in GATHER and "GitSCM" not in GATHER, "Add-on 은 Git 플러그인이 아니라 스크립트로 받는다 (검증 해제 범위를 명령 하나로 한정)"
    assert (REPO_ROOT / "scripts" / "addon_checkout.sh").is_file()
    assert (REPO_ROOT / "scripts" / "addon_askpass.sh").is_file()


def test_ref_is_the_global_variable_or_main():
    assert "def addonRef     = (env.ADDON_REPO_REF ?: '').trim() ?: 'main'" in GATHER


def test_layout_check_runs_in_the_venv_with_this_builds_targets():
    assert "['os': 'linux,windows', 'esxi': 'esxi', 'redfish': 'redfish'][params.target_type]" in GATHER
    check = GATHER[GATHER.index("check_layout.py") - 600: GATHER.index("check_layout.py") + 80]
    assert "activate_ansible_venv.sh" in check, "PyYAML 은 venv 에 있다"
    assert 'python3 addon/tools/check_layout.py addon --targets "${addonTargets}"' in GATHER
    assert "rc == 3" in GATHER and "실행할 추가 수집 기능이 없어 Add-on 없이 수집합니다" in GATHER, "Add-on 이 지원하지 않는 서버 종류는 켜지 않는다 (UNSTABLE 아님)"


def test_failure_marks_the_build_unstable_without_per_host_errors():
    assert 'unstable("[addon] unavailable: ${problem}")' in GATHER
    assert GATHER.count("[addon] unavailable:") >= 2, "콘솔 echo + unstable 메시지"
    assert "currentBuild.description" not in TEXT
    addon_block = GATHER[GATHER.index("def addonRepo"): GATHER.index("catchError(buildResult: 'UNSTABLE'")]
    assert "error " not in addon_block and "error(" not in addon_block, "Add-on 문제로 빌드를 끊지 않는다"


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
