"""Jenkinsfile_ci · scripts/jenkins/se_finalize.groovy — Phase 6 (Plan §6-4 · §9-4) 텍스트 계약 (2026-10-03).

고정하는 것
  1. se_finalize.groovy 의 세 함수(seFallbackCanon · seJsonString · seReconcileRaw)는 Jenkinsfile_portal 의 같은 이름 함수와
     `@NonCPS` 줄부터 닫는 `}` 까지 글자까지 같다. Jenkinsfile_portal 이 이 파일을 load 하도록 바뀌기(GP-11) 전까지 두 사본이
     갈리면 여기서 깨진다 — 한쪽만 고치는 일을 막는다.
  2. se_finalize.groovy 는 순수 함수만 둔다 — pipeline step · params · currentBuild 없음, 마지막 줄 `return this`.
  3. Jenkinsfile_ci 는 declarative · agent linux · disableConcurrentBuilds + timeout 90 min · 트리거 없음(cron/pollSCM — rule 80 R2) ·
     stage 5개 순서 · env.MAIN_SHA 고정 · ci_gate exit 1 → FAILURE / 2 → UNSTABLE(건너뛴 단계 echo) ·
     corpus 양쪽(Python 검사 + Groovy load/seReconcileRaw) · budget self-test · artifact 보존.
  4. venv 절대경로 없음(rule 80 R1-A) · 자격증명 없음 · LF.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CI_PATH = REPO / "Jenkinsfile_ci"
LIB_PATH = REPO / "scripts" / "jenkins" / "se_finalize.groovy"
PORTAL_PATH = REPO / "Jenkinsfile_portal"
CI = CI_PATH.read_text(encoding="utf-8")
LIB = LIB_PATH.read_text(encoding="utf-8")
PORTAL = PORTAL_PATH.read_text(encoding="utf-8")

SIGNATURES = (
    "Map seFallbackCanon()",
    "String seJsonString(Object value)",
    "Map seReconcileRaw(String manifestJson, String outputText, String checkpointText, Map canon, String outcome)",
)
STAGES = ["Checkout", "Toolchain", "Gate", "Finalize Corpus", "Budget Self-test"]


def _code(text: str) -> str:
    """`//` 줄/후행 주석을 지운 코드만. 금지 토큰(pollSCM · echo · sh …)을 '설명하는 주석'에 걸리지 않게 한다.
    이 두 groovy 파일에는 문자열 안에 `//` 가 없다(슬래시 정규식 · URL 없음)."""
    out = []
    for line in text.split("\n"):
        i = line.find("//")
        while i != -1 and i > 0 and line[i - 1] == ":":  # `://` 보호(현재는 없지만 방어)
            i = line.find("//", i + 2)
        out.append(line[:i] if i != -1 else line)
    return "\n".join(out)


def _block(text: str, signature: str) -> str:
    """`@NonCPS` 줄부터 열 0 의 닫는 `}` 까지 — 함수 본문 전체."""
    i = text.index(signature)
    start = text.rfind("@NonCPS\n", 0, i)
    assert start != -1 and text[start:i] == "@NonCPS\n", f"{signature}: @NonCPS 가 바로 위에 없다"
    end = text.index("\n}\n", i) + 3
    return text[start:end]


def _stage(name: str) -> str:
    start = CI.index(f"stage('{name}')")
    nxt = re.search(r"\n        stage\('", CI[start + 1:])
    return CI[start: start + 1 + nxt.start()] if nxt else CI[start:]


# ── 1. Layer B 함수 동일성 ────────────────────────────────────────────────────

@pytest.mark.parametrize("signature", SIGNATURES)
def test_layer_b_function_lives_only_in_the_library(signature):
    """GP-11 완료(2026-10-03): Jenkinsfile_portal 은 사본을 두지 않고 finalizer node 안에서 load 한다."""
    assert signature in LIB
    assert signature not in PORTAL, f"{signature}: Jenkinsfile_portal 에 사본이 남아 있다 — 정본은 se_finalize.groovy 하나"
    assert "readTrusted('scripts/jenkins/se_finalize.groovy')" in PORTAL and "load('se_finalize.groovy')" in PORTAL


def test_library_defines_exactly_the_three_functions_and_returns_this():
    names = re.findall(r"^(?:Map|String|List|boolean|long|def) (se\w+)\(", LIB, re.M)
    assert names == ["seFallbackCanon", "seJsonString", "seReconcileRaw"]
    assert LIB.count("@NonCPS") == 3
    assert LIB.rstrip().endswith("return this"), "load 가 메서드를 가진 객체를 돌려주려면 마지막이 return this"
    assert "import com.cloudbees.groovy.cps.NonCPS" in LIB


def test_library_is_pure_no_pipeline_steps_params_or_build_state():
    code = _code(LIB)  # 금지 토큰을 설명하는 주석이 있으므로 코드만 본다
    for token in ("readTrusted", "readYaml", "readJSON", "readFile", "writeFile", "fileExists", "echo ", "sh(", "sh ", "httpRequest",
                  "node(", "unstash", "archiveArtifacts", "params.", "currentBuild", "pipeline {", "stage("):
        assert token not in code, f"순수 함수 파일에 {token!r} 가 있다"


def test_library_fallback_canon_still_matches_catalog_and_layer_a():
    """Jenkinsfile_portal 쪽 drift 테스트(test_jenkinsfile_portal_finalize)와 같은 기준을 사본에도 건다."""
    import yaml
    fr = yaml.safe_load((REPO / "common/vars/failure_reasons.yml").read_text(encoding="utf-8"))
    assert f"reason  : '{fr['_fr_catalog']['output_build_failed']['default']}'" in LIB
    layer_a = (REPO / "scripts/finalize_gather_output.py").read_text(encoding="utf-8")
    emit = re.search(r"EMIT_FAILED = '([^']+)'", layer_a).group(1)
    assert f"emitFailed: '{emit}'" in LIB


# ── 2. Jenkinsfile_ci 구조 ───────────────────────────────────────────────────

def test_ci_is_declarative_with_linux_agent_and_required_options():
    assert "\npipeline {\n" in CI
    assert "agent { label 'linux' }" in CI
    opts = CI[CI.index("    options {"):CI.index("    environment {")]
    assert "disableConcurrentBuilds()" in opts
    assert "timeout(time: 90, unit: 'MINUTES')" in opts
    assert "skipDefaultCheckout(true)" in opts, "Checkout stage 가 유일한 checkout"
    assert "label 'esxi'" not in CI and "'linux && windows'" not in CI, "Runner 라벨은 linux 하나"


def test_ci_stage_order():
    assert re.findall(r"\n        stage\('([^']+)'\)", CI) == STAGES


def test_ci_has_no_triggers_or_cron():
    code = _code(CI)  # "cron · pollSCM 을 두지 않는다" 같은 주석이 있으므로 코드만 본다
    assert "triggers {" not in code and "triggers{" not in code
    assert "cron(" not in code and "pollSCM" not in code and "upstream(" not in code
    assert not re.search(r"['\"]H\s+\*", code), "cron 표현식 흔적"


def test_ci_checkout_fixes_main_sha_from_git_commit():
    s = _stage("Checkout")
    assert "def scmVars = checkout scm" in s
    assert "env.MAIN_SHA = (scmVars?.GIT_COMMIT ?: '').toString()" in s
    assert "git rev-parse HEAD" in s, "GIT_COMMIT 이 비면 workspace 에서 읽는다"
    assert "*/main" in s, "main 전용은 Job 의 Branch Specifier 로 — 주석으로 남긴다"


def test_ci_toolchain_uses_venv_selector_and_reports_pwsh_optionally():
    s = _stage("Toolchain")
    assert '. "${WORKSPACE}/scripts/activate_ansible_venv.sh"' in s
    assert "set -eo pipefail" in s, "venv 실패는 stage 실패 — 시스템 python 으로 조용히 진행하지 않는다"
    for tool in ("python3 --version", "import yaml", "pytest --version", "ansible-playbook --version", "git --version"):
        assert tool in s, tool
    assert "command -v pwsh" in s and "pwsh=absent (not required yet)" in s
    assert "tee toolchain.txt" in s


def test_ci_gate_exit_code_semantics():
    s = _stage("Gate")
    assert "bash scripts/ai/ci_gate.sh 2>&1 | tee ci_gate.log" in s
    assert 'exit "${PIPESTATUS[0]}"' in s, "tee 뒤에서도 ci_gate 의 종료 코드를 쓴다"
    assert "if (rc == 0)" in s and "else if (rc == 2)" in s
    assert "unstable(\"[Gate] PARTIAL" in s, "PARTIAL 은 UNSTABLE — 통과가 아니다"
    assert "it.contains('건너뜀') || it.contains('skipped')" in s, "건너뛴 단계를 콘솔에 echo"
    assert "catchError(buildResult: 'FAILURE', stageResult: 'FAILURE')" in s and 'error "[Gate] FAIL rc=${rc}' in s


def test_ci_corpus_runs_python_side_then_groovy_side_via_load():
    s = _stage("Finalize Corpus")
    assert "python3 tests/scripts/finalize_corpus_check.py --report-json finalize_corpus_python.json" in s
    assert "def lib = load 'scripts/jenkins/se_finalize.groovy'" in s
    assert "findFiles(glob: 'tests/fixtures/finalize_corpus/*/gather_manifest.json')" in s
    assert "lib.seFallbackCanon()" in s and "lib.seReconcileRaw(manifestJson, outText, cpText, canon, outcome)" in s
    for f in ("gather_output.json", "gather_checkpoint.jsonl", "outcome.txt", "expected_final.jsonl", "expected_report.json", "expected_origins.json"):
        assert f in s, f
    assert "seCorpusCompare(caseName, res," in s
    assert "finalize_corpus_groovy.json" in s
    assert s.index("finalize_corpus_check.py") < s.index("load 'scripts/jenkins/se_finalize.groovy'")
    assert "seLoadCanon" not in CI and "readTrusted" not in CI, "CI 는 workspace 가 있으니 fallback canon 자체를 검증 대상으로 쓴다"


def test_ci_corpus_compare_covers_three_origins_and_report_sets():
    helper = CI[CI.index("List seCorpusCompare("):CI.index("\npipeline {")]
    assert helper.startswith("List seCorpusCompare(String caseName, Map res, String expectedFinal, String expectedReport, String expectedOrigins, Map canon)")
    assert CI[CI.rfind("@NonCPS", 0, CI.index("List seCorpusCompare(")):].startswith("@NonCPS\nList seCorpusCompare(")
    for origin in ("'output'", "'checkpoint'", "'synthetic'"):
        assert f"origin == {origin}" in helper, origin
    assert "gotLines[i] != expLines[i]" in helper, "OUTPUT 줄은 원문 비교"
    assert "canon.emitFailed" in helper, "checkpoint 복원의 Layer B 오류 1건"
    assert "'layer_b'" in helper and "'layer_a'" in helper and "'OUTPUT_BUILD_FAILED'" in helper
    assert "corrupt_lines" in helper and "truncated_tail" in helper, "Layer A 의 손상 분류를 Layer B 의 dropped 와 합쳐 비교"
    assert "by_origin" in helper and "conflicts" in helper
    assert "JsonSlurperClassic" in helper, "양쪽 JSON 을 같은 파서로 읽는다"


def test_ci_budget_selftest_and_artifacts():
    s = _stage("Budget Self-test")
    assert "python3 -m pytest tests/unit/test_gather_budget.py -q" in s
    assert "bash scripts/gather_budget.sh" in s and '"start":true' in s
    for ch in ('"os 3"', '"esxi 50"', '"redfish 200"'):
        assert ch in s, ch
    post = CI[CI.rindex("    post {"):]
    assert "archiveArtifacts(artifacts: 'toolchain.txt,ci_gate.log,finalize_corpus_python.json,finalize_corpus_groovy.json,budget_selftest.jsonl'" in post
    assert "allowEmptyArchive: true" in post


def test_ci_has_no_venv_absolute_paths_credentials_or_gathering():
    for bad in ("/opt/ansible-env", "/app/ansible-env", "bin/activate\"", "withCredentials", "VAULT_PASSWORD", "vault-password",
                "ansible-playbook \"", "httpRequest", "callbackUrl", "inventory_json", "credentialsId"):
        assert bad not in CI, bad
    assert CI.count('. "${WORKSPACE}/scripts/activate_ansible_venv.sh"') >= 4, "모든 sh 블록이 같은 venv 선택 규칙을 쓴다"


@pytest.mark.parametrize("path", [CI_PATH, LIB_PATH, REPO / "tests" / "scripts" / "finalize_corpus_check.py"])
def test_lf_line_endings(path):
    assert b"\r\n" not in path.read_bytes(), f"{path.name}: CRLF — Linux 에이전트의 #!/bin/bash 블록이 깨진다"


BASH = shutil.which("bash")


@pytest.mark.skipif(BASH is None, reason="bash 없음")
def test_embedded_bash_blocks_parse(tmp_path):
    blocks = re.findall(r"'''(#!/bin/bash\n.*?)'''", CI, re.S)
    assert len(blocks) == 4, "Toolchain · Gate · Corpus(Python) · Budget 네 블록"
    for n, block in enumerate(blocks):
        # 파일 인자로 검사한다 — Git Bash 는 stdin 파이프로 받은 `bash -n` 이 Windows 에서 멈출 수 있다. timeout 으로 CI 가 매달리지 않게 한다.
        f = tmp_path / f"block_{n}.sh"
        f.write_bytes(block.encode("utf-8"))
        try:
            r = subprocess.run([BASH, "-n", str(f)], capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            pytest.fail(f"block {n}: bash -n 가 30s 안에 끝나지 않음")
        assert r.returncode == 0, f"block {n}: {r.stderr}"
