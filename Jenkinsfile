// =============================================================================
// server-exporter / Jenkinsfile  v3
//
// 호출자 → Jenkins → Ansible gather → 결과 stdout JSON
//
// 지원 gather 종류 (target_type):
//   os      → os-gather/site.yml     (Linux/Windows 자동 감지)
//   esxi    → esxi-gather/site.yml
//   redfish → redfish-gather/site.yml
//
// 파라미터:
//   loc             : 슬레이브 로케이션 Labels (ich|chj|yi)
//   target_type     : 수집 대상 종류 (os|esxi|redfish)
//   inventory_json  : 호출자가 전달하는 호스트 배열 JSON
//                     IP 필드: os/esxi → service_ip, redfish → bmc_ip (fallback: ip)
//
// 출력:
//   표준 JSON schema v1 (stdout) — json_only callback 필터
//   archiveArtifacts: gather_output*.log,results*.json (allowEmptyArchive)
//     — 이 파이프라인은 ANSIBLE_JSON_OUTPUT_FILE 을 set 하지 않으므로
//       실제로는 stdout JSON 만 산출되고 위 artifact 는 비어있을 수 있음.
//
// 실패 처리:
//   Validate 단계 실패 → 즉시 종료
//   Ansible 실패 → partial result JSON 포함하여 계속
// =============================================================================

pipeline {

    agent { label "${params.loc}" }

    parameters {
        // 호출자가 전달하는 값
        string(
            name        : 'loc',
            defaultValue: '',
            description : '슬레이브 로케이션 Labels (ich | chj | yi)'
        )
        choice(
            name        : 'target_type',
            choices     : ['os', 'esxi', 'redfish'],
            description : '수집 대상 종류'
        )
        text(
            name        : 'inventory_json',
            defaultValue: '''[
  {
    "service_ip": ""
  }
]''',
            description : '호출자가 전달하는 타겟 호스트 JSON 배열 (os/esxi: service_ip, redfish: bmc_ip)'
        )
    }

    environment {
        INVENTORY_JSON          = "${params.inventory_json}"
        REPO_ROOT               = "${WORKSPACE}"
        ANSIBLE_CONFIG          = "${WORKSPACE}/ansible.cfg"
        // __pycache__ 권한 충돌 차단 — 외부 root 진입 흔적으로 .pyc 가 root 소유로 굳을 경우
        // jenkins user 가 갱신 못 해 plugin path 로드 실패 (errno 13). bytecode 캐시 자체를 끔.
        PYTHONDONTWRITEBYTECODE = '1'
    }

    options {
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '100'))
        ansiColor('xterm')
    }

    stages {

        // ── 1. 파라미터 검증 ──────────────────────────────────────────────────
        // production-audit (2026-04-29): per-stage timeout 추가 — 한 stage가 30분 글로벌 타임아웃을 독차지하는 사고 방지
        stage('Validate') {
            options { timeout(time: 2, unit: 'MINUTES') }
            steps {
                script {

                    // loc 필수
                    if (!params.loc?.trim()) {
                        error "[Validate] 필수 파라미터 누락: loc"
                    }

                    // target_type 범위 검증
                    def allowed = ['os', 'esxi', 'redfish']
                    if (!allowed.contains(params.target_type?.trim())) {
                        error "[Validate] target_type 값 오류: '${params.target_type}' — 허용값: ${allowed}"
                    }

                    // inventory_json 파싱 검증
                    if (!params.inventory_json?.trim()) {
                        error "[Validate] inventory_json 이 비어있습니다"
                    }

                    def hosts
                    try {
                        hosts = readJSON text: params.inventory_json
                    } catch (groovy.json.JsonException e) {
                        error "[Validate] inventory_json JSON 파싱 실패: ${e.message}"
                    }

                    if (!hosts || hosts.size() == 0) {
                        error "[Validate] inventory_json 배열이 비어있습니다"
                    }

                    // 각 호스트 IP 필드 검증 (target_type 기반 fallback)
                    def primaryKey = (params.target_type == 'redfish') ? 'bmc_ip' : 'service_ip'
                    hosts.eachWithIndex { host, idx ->
                        def ipVal = host[primaryKey]?.trim() ?: host['ip']?.trim()
                        if (!ipVal) {
                            error "[Validate] inventory_json[${idx}] '${primaryKey}' 또는 'ip' 필드 누락: ${host}"
                        }
                    }

                    // redfish 는 vendor 필드 권장 (없어도 진행)
                    if (params.target_type == 'redfish') {
                        def missing = hosts.findAll { !it.vendor?.trim() }
                        if (missing) {
                            echo "[Validate] WARNING: redfish 항목 중 vendor 필드 미지정 (${missing.size()}개) — 자동 감지 시도"
                        }
                    }

                    echo "[Validate] OK — target_type=${params.target_type}, hosts=${hosts.size()}개, loc=${params.loc}"
                }
            }
        }

        // ── 2. Ansible 실행 ───────────────────────────────────────────────────
        // P0: vault password 는 Jenkins credentials store 의 Secret File 에 등록
        //     credentialsId='server-gather-vault-password' (사용자 결정 cycle-012)
        //     등록 절차는 docs/operate/01-jenkins-master.md 참고.
        stage('Gather') {
            options { timeout(time: 20, unit: 'MINUTES') }
            steps {
                script {
                    // target_type 별 playbook 경로 결정
                    def playbookMap = [
                        'os'     : "${WORKSPACE}/os-gather/site.yml",
                        'esxi'   : "${WORKSPACE}/esxi-gather/site.yml",
                        'redfish': "${WORKSPACE}/redfish-gather/site.yml",
                    ]
                    def inventoryMap = [
                        'os'     : "${WORKSPACE}/os-gather/inventory.sh",
                        'esxi'   : "${WORKSPACE}/esxi-gather/inventory.sh",
                        'redfish': "${WORKSPACE}/redfish-gather/inventory.sh",
                    ]

                    def playbook  = playbookMap[params.target_type]
                    def inventory = inventoryMap[params.target_type]

                    echo "[Gather] playbook=${playbook}"

                    // Ansible 실패 시 unstable 처리 (partial result JSON 포함)
                    // catchError 로 감싸서 post 단계까지 진행
                    // Secret Text 방식 사용 (Secret File trailing newline 문제 회피)
                    catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                        withCredentials([
                            string(
                                credentialsId: 'server-gather-vault-password',
                                variable     : 'VAULT_PASSWORD',
                            ),
                        ]) {
                            def vaultPassFile = "${env.WORKSPACE}/.vault_pass_tmp"
                            try {
                                // sh printf 로 password 파일 작성 — writeFile 의 자동 newline 추가 회피.
                                // inventory.sh 실행권한 보장 — agent 체크아웃이 exec bit 미보존 시
                                // ansible script 인벤토리 플러그인이 "Unable to parse as inventory source" 로 거부됨.
                                // (git mode 100755 이나 일부 체크아웃 환경에서 644 로 풀림 — 2026-06-04 진단)
                                sh """
                                    printf '%s' "\${VAULT_PASSWORD}" > "${vaultPassFile}"
                                    chmod 600 "${vaultPassFile}"
                                    chmod +x "${inventory}"
                                """
                                // 2026-08-12: Credential 선택이 Location 축을 갖게 되면서
                                //   se_location extra-var 가 없으면 어떤 vault 도 열리지 않는다.
                                //   이 파이프라인은 운영 대상이 아니고 삭제 예정이지만(E2E Regression
                                //   게이트 이관 방안 확정 전까지 보류), 남아 있는 동안 깨진 상태로
                                //   두지 않기 위해 최소 전달만 추가한다.
                                //   주의: 이 파일은 pipeline top-level `agent { label "${params.loc}" }`
                                //   구조라 Jenkinsfile_portal 의 'Resolve Location' 처럼 **agent 할당
                                //   이전에** 미등록 Location 을 걸러낼 수 없다. 잘못된 loc 은 여전히
                                //   노드 대기로 나타난다. 운영 경로는 Jenkinsfile_portal 이다.
                                ansiblePlaybook(
                                    playbook    : playbook,
                                    inventory   : inventory,
                                    installation: 'ansible',
                                    colorized   : true,
                                    extras      : "--vault-password-file=\"${vaultPassFile}\" -e se_location=\"${params.loc}\"",
                                )
                            } finally {
                                sh "rm -f \"${vaultPassFile}\" || true"
                            }
                        }
                    }
                }
            }
        }

        // ── 3. Schema Validator ─────────────────────────────────────────────────
        // field_dictionary.yml 정합성 검증
        // Build #7-9 연속 PASS 확인 → FAIL 게이트 상향
        stage('Validate Schema') {
            options { timeout(time: 2, unit: 'MINUTES') }
            steps {
                sh '''#!/bin/bash
                    set +x
                    cd "${WORKSPACE}"
                    . /opt/ansible-env/bin/activate
                    python3 tests/validate_field_dictionary.py
                '''
            }
        }

        // ── 4. E2E Regression ─────────────────────────────────────────────────
        // production-audit (2026-04-29): tests/e2e 가 없으면 환경 구성 오류로 간주, when fileExists 제거 → 디렉터리 부재 시 stage 강제 실패
        // baseline/fixture 기반 필드 회귀 검증
        stage('E2E Regression') {
            options { timeout(time: 5, unit: 'MINUTES') }
            steps {
                sh '''#!/bin/bash
                    set +x
                    cd "${WORKSPACE}"
                    if [ ! -d tests/e2e ]; then
                        echo "[E2E] tests/e2e 디렉터리 부재 — 환경 구성 오류"
                        exit 1
                    fi
                    . /opt/ansible-env/bin/activate
                    # E2E baseline 회귀 (필수)
                    python3 -m pytest tests/e2e/ -v --tb=short
                    RC_E2E=$?
                    # HPE 에뮬레이터 오프라인 회귀 하네스 (별도 invocation).
                    #   - 에뮬레이터 불필요 (fixture 커밋됨, 완전 오프라인). live 스모크는
                    #     -m "not live" 로 제외 (SE_EMULATOR_LIVE 미설정 시 어차피 self-skip).
                    #   - tests/e2e 와 tests/integration 둘 다 top-level 'conftest' module 을
                    #     써서 멀티-디렉터리 단일 pytest 호출 시 ImportError → 별도 호출 필수.
                    RC_INT=0
                    if [ -d tests/integration ]; then
                        python3 -m pytest tests/integration/ -m "not live" -v --tb=short
                        RC_INT=$?
                    fi
                    # 둘 다 실행 후(전체 진단 확보) 하나라도 실패하면 stage 실패.
                    [ $RC_E2E -eq 0 ] && [ $RC_INT -eq 0 ]
                '''
            }
        }
    }

    // ── post 처리 ─────────────────────────────────────────────────────────────
    post {
        always {
            script {
                def result = currentBuild.currentResult
                echo "[Post] 빌드 결과: ${result}"
                // json_only callback 이 stdout 에 JSON 을 출력하므로
                // 호출자는 Jenkins console log 에서 JSON 라인을 파싱한다.
            }
            // production-audit (2026-04-29): 결과 보존 — console log 외 fallback artifact
            archiveArtifacts(
                artifacts: 'gather_output*.log,results*.json',
                allowEmptyArchive: true,
                fingerprint: false
            )
        }
        success {
            echo "[Post] gather 완료 — 결과 반환"
        }
        failure {
            echo "[Post] gather 실패 — 에러 상태 반환 (partial result 포함 가능)"
        }
    }
}
