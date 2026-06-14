# Jenkins 파이프라인 런타임

> **이 문서는** server-exporter 의 Jenkins 파이프라인이 실제로 어떤 단계로 실행되는지 그림과 표로 정리한다.
> Stage 1~4 의 의무, 각 Stage 가 실패할 때 어떻게 전파되는지, 호출자에게 어떤 형식으로 결과가 돌아가는지를 한 페이지에 모았다.
>
> Jenkinsfile 자체를 수정해야 하는 경우, 본 문서의 Stage 구조와 게이트 정책을 먼저 이해한 뒤 변경에 들어간다.

> 검증일: 2026-03-18

## 1. Jenkinsfile 분석 결과

`Jenkinsfile` 기반 — 포털 → Jenkins → Ansible → JSON stdout → 포털 파이프라인.

### 파이프라인 구조

```text
parameters (loc, target_type, inventory_json)
  → Stage 1: Validate (파라미터 검증)
  → Stage 2: Gather (Ansible 실행)
  → Stage 3: Validate Schema (field_dictionary.yml 정합성, FAIL 게이트)
  → Stage 4: E2E Regression (pytest baseline/fixture 회귀 검증, FAIL 게이트)
  → Post (결과 처리)
```

### Stage 3/4 품질 게이트

| Stage | 도구 | 게이트 | 비고 |
|-------|------|--------|------|
| Validate Schema | `python3 tests/validate_field_dictionary.py` | **FAIL** | 실패 시 빌드 FAILURE |
| E2E Regression | `pytest tests/e2e/` + `pytest tests/integration/ -m "not live"` (별도 호출, 둘 중 하나라도 FAIL 시 stage 실패) | **FAIL** | tests/e2e=baseline/fixture 회귀, tests/integration=HPE 에뮬레이터 오프라인 회귀 하네스(2026-06-08 추가, 에뮬레이터 불필요·완전 오프라인). 별도 호출 이유=양쪽이 top-level `conftest` 충돌. |

Stage 3/4는 venv Python을 사용한다 (`. /opt/ansible-env/bin/activate`).

> [!NOTE]
> 파이프라인은 두 종류다. `Jenkinsfile` 과 `Jenkinsfile_portal` 은 Stage 1~3 이 같고 Stage 4 만 다르다 — `Jenkinsfile` = E2E Regression, `Jenkinsfile_portal` = Callback(호출자 통보). 이 문서는 `Jenkinsfile` 기준이다.

## 2. Jenkins 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `loc` | string | 필수 | 슬레이브 로케이션 (ich/chj/yi) |
| `target_type` | choice | 필수 | os / esxi / redfish |
| `inventory_json` | text | 필수 | 호출자가 전달하는 호스트 JSON 배열 (os/esxi: `service_ip`, redfish: `bmc_ip`, fallback: `ip`) |

### inventory_json 형식
```jsonc
// os/esxi 는 service_ip, redfish 는 bmc_ip 키를 쓴다. 둘 다 없으면 ip 로 fallback.
[
  { "service_ip": "10.50.11.232" }
]
```

> 포털은 ip만 전달한다. 계정은 vault에서 자동 로딩된다.
> 상세 명세는 [docs/05_inventory-json-spec.md](05_inventory-json-spec.md) 참조.

## 3. 환경변수 설정

Jenkinsfile에서 자동 설정:
```groovy
environment {
    INVENTORY_JSON = "${params.inventory_json}"
    REPO_ROOT      = "${WORKSPACE}"
}
```

### 추가 필요 환경변수

| 변수 | 상태 | 필요 조치 |
|------|----------|----------|
| `ANSIBLE_CONFIG` | 미설정 | `${WORKSPACE}/ansible.cfg` 추가 권장 |
| `PYTHONPATH` | 미설정 | ansible.cfg가 module_utils 경로 처리하므로 불필요 |

## 4. Ansible 실행 방식

```groovy
ansiblePlaybook(
    playbook : "${WORKSPACE}/${target_type}-gather/site.yml",
    inventory: "${WORKSPACE}/${target_type}-gather/inventory.sh",
    colorized: true,
)
```

### 채널별 실행 경로

| target_type | playbook | inventory |
|-------------|----------|-----------|
| redfish | `redfish-gather/site.yml` | `redfish-gather/inventory.sh` |
| os | `os-gather/site.yml` | `os-gather/inventory.sh` |
| esxi | `esxi-gather/site.yml` | `esxi-gather/inventory.sh` |

## 5. Jenkins 플러그인 요구사항

| 플러그인 | 필수 | 용도 |
|---------|------|------|
| Pipeline | 필수 | Declarative Pipeline |
| AnsiColor | 필수 | `ansiColor('xterm')` |
| Ansible | 필수 | `ansiblePlaybook` step |
| Credentials Binding | 권장 | Vault 비밀번호 전달 |
| Pipeline Utility Steps | 권장 | `readJSON` 사용 |

## 6. Credentials 관리

| ID | 타입 | 용도 | 상태 (검증 시점) |
|----|------|------|-----------------|
| vault-pass | Secret file | Ansible vault 복호화 | 미등록 — 등록 필요 |
| bmc-credentials | Username/Password | BMC 인증 (선택) | 포털에서 inventory_json으로 전달 |

## 7. Jenkins Agent 요구사항

> Python / Java / Ansible / 패키지 버전 요건은 `REQUIREMENTS.md` 4절 참조.
> 설치 절차는 `docs/03_agent-setup.md` 3-5절 참조.

| 항목 | 요구사항 |
|------|---------|
| Label | `loc` 파라미터 값 (ich/chj/yi) |
| 네트워크 | BMC 대역 (10.50.x.x) 접근 가능 |
| 디스크 | workspace + ansible 로그 공간 |

## 8. 검증 시점(2026-03-18) 미완료 설정

| # | 항목 | 영향 | 우선순위 |
|---|------|------|---------|
| 1 | `ANSIBLE_CONFIG` 미설정 | ansible.cfg가 자동 인식되지 않을 수 있음 | 높음 |
| 2 | vault-pass credentials 미등록 | vault 사용 불가 | 중 |
| 3 | artifact 저장 미구현 | 결과 JSON 재취득 불가 | 낮음 |

### 권장 수정 (Jenkinsfile)

```groovy
environment {
    INVENTORY_JSON  = "${params.inventory_json}"
    REPO_ROOT       = "${WORKSPACE}"
    ANSIBLE_CONFIG  = "${WORKSPACE}/ansible.cfg"
}
```

```groovy
// artifact 저장 추가 (post 블록)
post {
    always {
        archiveArtifacts artifacts: 'results.json', allowEmptyArchive: true
    }
}
```

## 9. 실행 가능 상태 확인

| 항목 | 상태 | 비고 |
|------|------|------|
| Jenkinsfile 구조 | [OK] 정상 | 검증 완료 |
| 파라미터 검증 | [OK] 정상 | loc, target_type, inventory_json 검증 |
| ansible.cfg | [OK] 생성 완료 | 2026-03-18 생성 |
| Agent 환경 | [OK] 확인 완료 | 2026-03-27 SSH 접속 확인 (Python 3.12.3, ansible-core 2.20.3) |
| Credentials | [WARN] 미등록 | vault-pass 등록 필요 |
| 컬렉션 설치 | [OK] 확인 완료 | 2026-03-27 ansible-galaxy list 확인 |

## 10. 준비 순서

1. Jenkins agent에 Python + Ansible 설치
2. `ansible.cfg`를 repo에 포함 (완료)
3. Jenkinsfile에 `ANSIBLE_CONFIG` 환경변수 추가
4. Jenkins credentials에 vault-pass 등록
5. `ansible-galaxy collection install` 실행
6. 테스트 빌드 실행 (redfish-gather, single host)

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Jenkins Job 등록 | [04_job-registration.md](04_job-registration.md) |
| 호출자 입력 형식 | [05_inventory-json-spec.md](05_inventory-json-spec.md) |
| 실패 처리 정책 | [08_failure-handling.md](08_failure-handling.md) |
