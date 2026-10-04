"""Jenkinsfile_ci · scripts/jenkins/se_finalize.groovy — main 전용 CI 의 텍스트 계약 (2026-10-03 Phase 6 → 2026-10-04 Astra R3 반영).

고정하는 것
  1. se_finalize.groovy 가 Layer B 순수 함수의 유일한 정본이다(Jenkinsfile_portal 은 load). 순수 함수만, 마지막 `return this`, sandbox 허용 파서.
  2. Jenkinsfile_ci 는 declarative · agent linux · disableConcurrentBuilds + timeout · 트리거 없음(수동 기본 — rule 80 R2) ·
     stage 12개 순서(dependency: Harness(main) → Prodgen Build → Harness(prodtree) → Drift → Verify → Evidence → Promote) · env.MAIN_SHA 고정.
  3. 자격증명은 **Prodgen Verify**(린터 토큰 · vault 암호 — G13/G19)와 **Evidence Aggregate**(Jenkins 읽기 토큰)와 **Prodgen Promote**(git push)
     안에서만 바인딩한다. vault 암호는 mktemp 0600 파일 → --vault-password-file → trap 으로 지운다. echo/set -x 로 새지 않는다.
  4. Promote 는 `branch` 조건을 쓰지 않는다(일반 Pipeline). PROMOTE 기본 false · PROMOTE_DRY_RUN 기본 true · BOOTSTRAP_BASELINE 기본 빈 값 ·
     필수 stage 결과(ci_stage_results) · SHA 4값 일치 · 보고서 COMPLETE_PASS · GitLab 자격 없으면 dry-run 만(GitHub 만 먼저 바꾸지 않는다).
  5. Jenkinsfile_ci 자체는 ansible-playbook 을 직접 부르지 않고(G19 는 prodgen 안에서), Callback(httpRequest) 도 보내지 않는다.
  6. venv 절대경로 없음(rule 80 R1-A) · LF · 임베디드 bash 블록 parse.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.source_text   # 저장소 메타(.claude · scripts/ai · Jenkinsfile_ci · git)를 읽는다 — G14 overlay 제외

REPO = Path(__file__).resolve().parents[2]
CI_PATH = REPO / "Jenkinsfile_ci"
LIB_PATH = REPO / "scripts" / "jenkins" / "se_finalize.groovy"
PORTAL_PATH = REPO / "Jenkinsfile_portal"
if not CI_PATH.is_file():      # production 생성 tree(G14 overlay)에는 Jenkinsfile_ci 가 없다(main 전용)
    pytest.skip("Jenkinsfile_ci 없음 — main 전용 CI 파일", allow_module_level=True)
CI = CI_PATH.read_text(encoding="utf-8")
LIB = LIB_PATH.read_text(encoding="utf-8")
PORTAL = PORTAL_PATH.read_text(encoding="utf-8")

SIGNATURES = (
    "Map seFallbackCanon()",
    "String seJsonString(Object value)",
    "Map seReconcileRaw(String manifestJson, String outputText, String checkpointText, Map canon, String outcome)",
)
STAGES = ["Checkout", "Toolchain", "Gate", "Finalize Corpus", "Budget Self-test", "Harness Driver", "Prodgen Build",
          "Harness (prodtree)", "Prodgen Drift", "Prodgen Verify", "Evidence Aggregate", "Prodgen Promote"]
CREDENTIAL_STAGES = {"Prodgen Verify", "Evidence Aggregate", "Prodgen Promote"}


def _code(text: str) -> str:
    """`//` 줄/후행 주석을 지운 코드만. 금지 토큰(pollSCM · echo · sh …)을 '설명하는 주석'에 걸리지 않게 한다."""
    out = []
    for line in text.split("\n"):
        i = line.find("//")
        while i != -1 and i > 0 and line[i - 1] == ":":  # `://` 보호
            i = line.find("//", i + 2)
        out.append(line[:i] if i != -1 else line)
    return "\n".join(out)


def _block(text: str, signature: str) -> str:
    i = text.index(signature)
    start = text.rfind("@NonCPS\n", 0, i)
    assert start != -1 and text[start:i] == "@NonCPS\n", f"{signature}: @NonCPS 가 바로 위에 없다"
    end = text.index("\n}\n", i) + 3
    return text[start:end]


def _stage(name: str) -> str:
    start = CI.index(f"stage('{name}')")
    nxt = re.search(r"\n        stage\('", CI[start + 1:])
    return CI[start: start + 1 + nxt.start()] if nxt else CI[start: CI.index("\n    post {", start)]


# ── 1. Layer B 함수 정본 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("signature", SIGNATURES)
def test_layer_b_function_lives_only_in_the_library(signature):
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
    code = _code(LIB)
    for token in ("readTrusted", "readYaml", "readJSON", "readFile", "writeFile", "fileExists", "echo ", "sh(", "sh ", "httpRequest",
                  "node(", "unstash", "archiveArtifacts", "params.", "currentBuild", "pipeline {", "stage("):
        assert token not in code, f"순수 함수 파일에 {token!r} 가 있다"
    assert "new groovy.json.JsonSlurper()" in code and "JsonSlurperClassic" not in LIB, "sandbox 허용 파서만 (2026-10-03 실측)"


def test_library_fallback_canon_still_matches_catalog_and_layer_a():
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
    opts = CI[CI.index("    options {"):CI.index("    parameters {")]
    assert "disableConcurrentBuilds()" in opts
    assert "timeout(time: 150, unit: 'MINUTES')" in opts
    assert "skipDefaultCheckout(true)" in opts, "Checkout stage 가 유일한 checkout"
    assert "label 'esxi'" not in CI and "'linux && windows'" not in CI, "Runner 라벨은 linux 하나"


def test_ci_stage_order_follows_dependencies():
    assert re.findall(r"\n        stage\('([^']+)'\)", CI) == STAGES
    order = [CI.index(f"stage('{n}')") for n in ("Harness Driver", "Prodgen Build", "Harness (prodtree)", "Prodgen Drift", "Prodgen Verify", "Evidence Aggregate", "Prodgen Promote")]
    assert order == sorted(order), "생성 tree 를 쓰는 단계는 Build 뒤 (4차 §2)"
    assert "when { expression { env.CI_STAGE_PRODGEN_BUILD == 'PASS' } }" in _stage("Harness (prodtree)")
    assert "when { expression { env.CI_STAGE_PRODGEN_BUILD == 'PASS' } }" in _stage("Prodgen Verify")


def test_ci_has_no_triggers_or_cron():
    code = _code(CI)
    assert "triggers {" not in code and "triggers{" not in code
    assert "cron(" not in code and "pollSCM" not in code and "upstream(" not in code
    assert not re.search(r"['\"]H\s+\*", code), "cron 표현식 흔적"


def test_ci_parameters_default_to_no_promotion():
    params = CI[CI.index("    parameters {"):CI.index("    environment {")]
    assert re.search(r"booleanParam\(name: 'PROMOTE', defaultValue: false", params)
    assert re.search(r"booleanParam\(name: 'PROMOTE_DRY_RUN', defaultValue: true", params)
    assert re.search(r"string\(name: 'BOOTSTRAP_BASELINE', defaultValue: ''", params)
    assert re.search(r"string\(name: 'PROMOTE_SHA', defaultValue: ''", params)
    for p in ("HARNESS_SCENARIOS", "HARNESS_TREE_SCENARIOS", "E2E_MAIN_ENTRIES"):
        assert f"name: '{p}'" in params, p


def test_ci_checkout_fixes_main_sha_from_git_commit():
    s = _stage("Checkout")
    assert "def scmVars = checkout scm" in s
    assert "env.MAIN_SHA = (scmVars?.GIT_COMMIT ?: '').toString()" in s
    assert "git rev-parse HEAD" in s
    assert "*/main" in s, "main 전용은 Job 의 Branch Specifier 로 — 주석으로 남긴다"


def test_ci_toolchain_reports_tools_and_bootstraps_pwsh_user_level():
    s = _stage("Toolchain")
    assert '. "${WORKSPACE}/scripts/activate_ansible_venv.sh"' in s
    assert "set -eo pipefail" in s
    for tool in ("python3 --version", "import yaml", "pytest --version", "ansible-playbook --version", "git --version"):
        assert tool in s, tool
    assert 'eval "$(bash scripts/ai/prodgen/ci_pwsh_bootstrap.sh --env)"' in s, "pwsh 는 사용자 권한 bootstrap (시스템 변경 없음)"
    assert "pwsh=absent" in s and "tee toolchain.txt" in s
    boot = (REPO / "scripts/ai/prodgen/ci_pwsh_bootstrap.sh").read_text(encoding="utf-8")
    assert "sudo" not in boot and "yum " not in boot and "dnf " not in boot and "apt" not in boot, "패키지 설치·root 없이 tar.gz 를 $HOME 아래에"
    assert "$HOME/.local/powershell" in boot and "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1" in boot


def test_ci_gate_exit_code_semantics_and_stage_result_recording():
    s = _stage("Gate")
    assert "bash scripts/ai/ci_gate.sh 2>&1 | tee ci_gate.log" in s
    assert 'exit "${PIPESTATUS[0]}"' in s
    assert "if (rc == 0)" in s and "else if (rc == 2)" in s
    assert "unstable(\"[Gate] PARTIAL" in s
    assert "catchError(buildResult: 'FAILURE', stageResult: 'FAILURE')" in s and 'error "[Gate] FAIL rc=${rc}' in s
    for v in ("env.CI_STAGE_GATE = 'PASS'", "env.CI_STAGE_GATE = 'PARTIAL'", "env.CI_STAGE_GATE = 'FAIL'"):
        assert v in s, v


def test_ci_corpus_runs_python_side_then_groovy_side_via_load():
    s = _stage("Finalize Corpus")
    assert "python3 tests/scripts/finalize_corpus_check.py --report-json finalize_corpus_python.json" in s
    assert "def lib = load 'scripts/jenkins/se_finalize.groovy'" in s
    assert "findFiles(glob: 'tests/fixtures/finalize_corpus/*/gather_manifest.json')" in s
    assert "lib.seFallbackCanon()" in s and "lib.seReconcileRaw(manifestJson, outText, cpText, canon, outcome)" in s
    assert "seCorpusCompare(caseName, res," in s and "finalize_corpus_groovy.json" in s
    assert "env.CI_STAGE_CORPUS = corpusOk ? 'PASS' : 'FAIL'" in s
    assert "seLoadCanon" not in CI and "readTrusted" not in CI


def test_ci_corpus_compare_uses_sandbox_parser():
    helper = CI[CI.index("List seCorpusCompare("):CI.index("\ndef seRunHarness(")]
    assert CI[CI.rfind("@NonCPS", 0, CI.index("List seCorpusCompare(")):].startswith("@NonCPS\nList seCorpusCompare(")
    for origin in ("'output'", "'checkpoint'", "'synthetic'"):
        assert f"origin == {origin}" in helper, origin
    assert "new groovy.json.JsonSlurper()" in helper and "JsonSlurperClassic" not in CI, "양쪽 JSON 을 같은(sandbox 허용) 파서로 읽는다"
    assert "corrupt_lines" in helper and "truncated_tail" in helper and "by_origin" in helper


def test_ci_harness_driver_calls_the_separate_harness_job_per_scenario():
    helper = CI[CI.index("def seRunHarness("):CI.index("\npipeline {")]
    assert "build(job: 'clovirone-cicd/clovirone-server-gather-harness', wait: true, propagate: false" in helper, "별도 Job → 교착 없음, 시나리오당 빌드 1개"
    assert "string(name: 'SCENARIO', value: s)" in helper and "string(name: 'MAIN_SHA', value: env.MAIN_SHA)" in helper
    main = _stage("Harness Driver")
    assert "seRunHarness('checkout'" in main and "harness_main_results.json" in main and "env.CI_STAGE_HARNESS_MAIN" in main
    tree = _stage("Harness (prodtree)")
    assert "seRunHarness('artifact'" in tree and "ARTIFACT_BASE_URL" in tree and "EXPECTED_SHA256: env.PRODTREE_PORTAL_SHA256" in tree
    assert "harness_tree_results.json" in tree


def test_ci_prodgen_build_archives_the_tree_of_this_build():
    s = _stage("Prodgen Build")
    assert 'python3 -m scripts.ai.prodgen --json build --sha "${MAIN_SHA}" --out "${WORKSPACE}/prodtree"' in s
    assert "tar -czf prodtree.tar.gz -C prodtree ." in s and "sha256sum prodtree/Jenkinsfile_portal" in s
    assert "archiveArtifacts(artifacts: 'prodgen_build.json,prodtree.tar.gz,prodtree_portal.sha256'" in s, "생성 tree 는 이 빌드의 artifact (경로 전달·이전 빌드 재사용 없음)"
    assert "env.PRODTREE_PORTAL_SHA256" in s and 'eval "$(bash scripts/ai/prodgen/ci_pwsh_bootstrap.sh --env)"' in s


def test_ci_drift_and_verify_use_the_single_bootstrap_syntax():
    d = _stage("Prodgen Drift")
    assert "drift-check --production refs/remotes/origin/production" in d
    assert '--bootstrap-baseline "${BOOTSTRAP_BASELINE}"' in d and "--allow-legacy" not in CI and "--bootstrap " not in CI
    v = _stage("Prodgen Verify")
    assert '--bootstrap-baseline "\\${BOOTSTRAP_BASELINE}"' in v
    assert "--report-out prodgen_verify_report.json" in v and "--remote origin" in v and "--source-build-url" in v


def test_credentials_are_bound_only_in_verify_evidence_and_promote():
    for name in STAGES:
        s = _stage(name)
        has = "withCredentials(" in s or "credentialsId" in s
        if name in CREDENTIAL_STAGES:
            assert has, f"{name}: 자격증명 바인딩이 있어야 한다"
        else:
            assert not has, f"{name}: 자격증명을 바인딩하면 안 된다"
    v = _stage("Prodgen Verify")
    assert "string(credentialsId: 'server-gather-vault-password', variable: 'VAULT_PASSWORD')" in v
    assert "VAULT_TMP=\"\\$(mktemp)\"; chmod 600 \"\\$VAULT_TMP\"" in v and "--vault-password-file \"\\$VAULT_TMP\"" in v
    assert "trap 'rm -f \"\\$NETRC_TMP\" \"\\$VAULT_TMP\"' EXIT" in v, "임시 파일은 trap 으로 지운다"
    assert "set +x" in v and "echo \"\\${VAULT_PASSWORD}" not in v and 'echo "${VAULT_PASSWORD}' not in CI
    assert CI.count("VAULT_PASSWORD") <= 6, "vault 암호 변수는 Verify · Promote 블록의 바인딩·printf 외에 등장하지 않는다 (2026-10-04 2차: Promote 도 G19 재실행용으로 바인딩)"
    p = _stage("Prodgen Promote")
    assert "string(credentialsId: 'server-gather-vault-password', variable: 'VAULT_PASSWORD')" in p and "CRED_ARGS+=(--netrc" in p
    assert "--vault-password-file \"\\$VAULT_TMP\"" in p and "trap 'rm -f \"\\$NETRC_TMP\" \"\\$VAULT_TMP\"' EXIT" in p
    for token in ("ansible-playbook \"", "httpRequest", "callbackUrl", "inventory_json"):
        assert token not in _code(CI), f"CI 는 수집도 Callback 도 하지 않는다: {token}"


def test_promote_enforces_the_six_conditions_without_branch_when():
    p = _stage("Prodgen Promote")
    assert "when { expression { params.PROMOTE } }" in p and "branch '" not in p and "branch(" not in p, "일반 Pipeline — branch 조건 금지"
    assert "List required = ['GATE', 'CORPUS', 'BUDGET', 'HARNESS_MAIN', 'PRODGEN_BUILD', 'HARNESS_TREE', 'PRODGEN_DRIFT', 'PRODGEN_VERIFY', 'EVIDENCE']" in p
    assert "원격 변경 0" in p
    assert "want == env.MAIN_SHA && env.MAIN_SHA == head && report.binding?.main_sha == head" in p, "SHA 4값 일치"
    assert "report.verdict != 'COMPLETE_PASS'" in p
    assert "boolean dryRun = params.PROMOTE_DRY_RUN || !haveGitlab" in p, "GitLab 자격 없으면 dry-run 만 — GitHub 만 먼저 바꾸지 않는다"
    assert "--verify-report prodgen_verify_report.aggregated.json --e2e-evidence e2e_evidence.json" in p
    assert "git_askpass.sh" in p and "http.https://10.100.64.156/.sslVerify" in p and "GIT_SSL_NO_VERIFY" not in CI
    assert "withCredentials([usernamePassword(credentialsId: 'hshwang token'" in p


def test_post_writes_stage_results_and_archives_reports():
    post = CI[CI.rindex("    post {"):]
    assert "ci_stage_results.json" in post and "prodgen_verify_report.json" in post and "e2e_evidence.json" in post and "prodgen_promote.json" in post
    assert "allowEmptyArchive: true" in post


def test_ci_has_no_venv_absolute_paths():
    for bad in ("/opt/ansible-env", "/app/ansible-env", "bin/activate\""):
        assert bad not in CI, bad
    assert CI.count('. "${WORKSPACE}/scripts/activate_ansible_venv.sh"') + CI.count('. "\\${WORKSPACE}/scripts/activate_ansible_venv.sh"') >= 8, "모든 sh 블록이 같은 venv 선택 규칙을 쓴다"


@pytest.mark.parametrize("path", [CI_PATH, LIB_PATH, REPO / "tests" / "scripts" / "finalize_corpus_check.py",
                                  REPO / "scripts" / "ai" / "prodgen" / "ci_pwsh_bootstrap.sh", REPO / "scripts" / "ai" / "prodgen" / "git_askpass.sh"])
def test_lf_line_endings(path):
    assert b"\r\n" not in path.read_bytes(), f"{path.name}: CRLF — Linux 에이전트의 #!/bin/bash 블록이 깨진다"


BASH = shutil.which("bash")


@pytest.mark.skipif(BASH is None, reason="bash 없음")
def test_embedded_bash_blocks_parse(tmp_path):
    blocks = re.findall(r"'''(#!/bin/bash\n.*?)'''", CI, re.S)
    assert len(blocks) == 7, "Toolchain · Gate · Corpus(Python) · Budget · Prodgen Build · Prodgen Drift · Evidence 일곱 블록 (Verify·Promote 는 GString 블록)"
    gstrings = re.findall(r'"""(#!/bin/bash\n.*?)"""', CI, re.S)
    assert len(gstrings) == 2, "Prodgen Verify · Prodgen Promote"
    for n, block in enumerate(blocks + [g.replace("\\$", "$").replace("\\\\", "\\") for g in gstrings]):
        f = tmp_path / f"block_{n}.sh"
        f.write_bytes(block.encode("utf-8"))
        try:
            r = subprocess.run([BASH, "-n", str(f)], capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            pytest.fail(f"block {n}: bash -n 가 30s 안에 끝나지 않음")
        assert r.returncode == 0, f"block {n}: {r.stderr}"

def test_no_loop_variable_shadows_the_implicit_closure_parameter():
    """CI #2 (2026-10-04) died at compile time: `for (def it in …)` inside a closure — "The current scope already contains a variable of the name it"."""
    assert re.search(r"for \(\s*(def|\w+)\s+it\s+in", CI) is None
    assert re.search(r"\(\s*it\s+in\s", CI) is None



# ── 2026-10-04 검토 C4 · C5 · C6 ────────────────────────────────────────────────────
def test_verify_block_decrypts_every_vault_file_with_the_same_binding_and_prints_no_secret():
    """검토 C6: G19 의 TEST-NET 실행은 credential 을 열지 않는다 — 같은 바인딩으로 vault_decrypt_check.py 가 실제 복호화 증거를 만든다."""
    v = _stage("Prodgen Verify")
    assert 'python3 scripts/ai/vault_decrypt_check.py --password-file "\\$VAULT_TMP" > vault_decrypt_check.txt' in v
    assert "vault_decrypt_rc.txt" in v and "env.CI_STAGE_VAULT_DECRYPT" in v
    assert "--layout-only" not in v, "layout 만 보는 검사는 복호화 증거가 아니다"
    assert "cat vault_decrypt_check.txt" not in CI and "SE_VAULT_PASSWORD" not in CI
    post = CI[CI.rindex("    post {"):]
    assert "vault_decrypt_check.txt" in post


def test_promote_passes_the_stage_results_to_prodgen_and_the_cli_consumes_them():
    """검토 C4: CLI promote 가 CI 와 같은 stage 증거를 소비한다 — Promote 는 호출 전에 ci_stage_results.json 을 쓰고 --ci-stage-results 로 넘긴다."""
    p = _stage("Prodgen Promote")
    assert "seWriteStageResults()" in p and "--ci-stage-results ci_stage_results.json" in p
    assert p.index("seWriteStageResults()") < p.index("prodgen promote"), "stage 결과 파일을 먼저 쓴다"
    helper = CI[CI.index("def seWriteStageResults("):CI.index("\npipeline {")]
    for k in ("GATE", "CORPUS", "BUDGET", "HARNESS_MAIN", "HARNESS_BOUNDED", "PRODGEN_BUILD", "HARNESS_TREE", "PRODGEN_DRIFT", "PRODGEN_VERIFY", "VAULT_DECRYPT", "EVIDENCE", "PROMOTE"):
        assert f"'{k}'" in helper, k
    from scripts.ai.prodgen import REQUIRED_CI_STAGES
    required = re.search(r"List required = \[([^\]]+)\]", p).group(1)
    assert [x.strip().strip("'") for x in required.split(",")] == list(REQUIRED_CI_STAGES), "CI 와 CLI 의 필수 stage 목록은 하나다"


def test_harness_driver_compares_each_scenario_with_its_expected_jenkins_result_and_runs_bounded_separately():
    """검토 C1 · C5: user_abort 는 ABORTED 가 기대값이다; Tier 2 는 BOUNDED=true 로 따로 돌리고 HARNESS_BOUNDED 에 기록한다(승격 조건 아님)."""
    helper = CI[CI.index("def seRunHarness("):CI.index("\ndef seWriteStageResults(")]
    assert "readJSON(file: 'tests/jenkins/harness/scenarios.json'" in helper and "jenkins_result" in helper
    assert "boolean ok = (b.result == expected)" in helper and "booleanParam(name: k, value: (v.toString() == 'true'))" in helper
    main = _stage("Harness Driver")
    assert "results.findAll { !it.ok }" in main and "results.findAll { it.result != 'SUCCESS' }" not in main
    assert "seRunHarness('checkout', bounded, [BOUNDED: 'true'])" in main and "harness_bounded_results.json" in main
    assert "env.CI_STAGE_HARNESS_BOUNDED" in main
    params = CI[CI.index("    parameters {"):CI.index("    environment {")]
    assert "name: 'HARNESS_BOUNDED_SCENARIOS'" in params
    default_main = re.search(r"string\(name: 'HARNESS_SCENARIOS', defaultValue: '([^']+)'", params).group(1).split(",")
    from scripts.ai.prodgen.evidence import REQUIRED_HARNESS, REQUIRED_HARNESS_BOUNDED, REQUIRED_HARNESS_TREE
    assert set(default_main) == set(REQUIRED_HARNESS), "CI 기본 목록 == 승격이 요구하는 main-function Harness 집합"
    default_tree = re.search(r"string\(name: 'HARNESS_TREE_SCENARIOS', defaultValue: '([^']+)'", params).group(1).split(",")
    assert set(default_tree) == set(REQUIRED_HARNESS_TREE)
    default_bounded = re.search(r"string\(name: 'HARNESS_BOUNDED_SCENARIOS', defaultValue: '([^']+)'", params).group(1).split(",")
    assert set(default_bounded) == set(REQUIRED_HARNESS_BOUNDED)
    assert "HARNESS_BOUNDED" not in re.search(r"List required = \[([^\]]+)\]", _stage("Prodgen Promote")).group(1), "Tier 2 는 승격 조건이 아니다(승인 전)"


def test_toolchain_reports_esxi_prerequisites_without_adding_the_label():
    s = _stage("Toolchain")
    assert "import pyVmomi" in s and "community[.]vmware" in s and "pyvmomi=absent" in s
    assert "label 'esxi'" not in CI
