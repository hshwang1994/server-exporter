# 04. Jenkins Job 등록

> **이 문서는** server-exporter 의 3 채널 (OS / ESXi / Redfish) 수집 Job 을 Jenkins 에 등록할 때 참고한다.
> Job 이름 규칙, SCM 연결, target_type 파라미터 매핑까지 다룬다.
> 신규 Jenkins 환경을 구축한 직후, 또는 새 채널이 추가됐을 때 들어와 본다.

경로: Jenkins → New Item → Pipeline 선택

---

## Job 네이밍 규칙

RBAC Pattern 과 일치해야 권한이 자동 적용된다.

```text
{프로젝트명}.{작업명}
```

**수집 파이프라인 예시:**

- `server-exporter.os-gather`
- `server-exporter.esxi-gather`
- `server-exporter.redfish-gather`

**인프라 자동화 예시:**

- `infra-automation.{작업명}.{타입}` (예: `infra-automation.load-test.linux`)

---

## Pipeline SCM 설정

경로: Job 설정 → Pipeline 섹션

| 항목 | 값 |
|------|----|
| Definition | Pipeline script from SCM |
| SCM | Git |
| Credentials | `gitlab-credentials` |
| Branch | `*/main` |

### 수집 파이프라인 Script Path

수집 파이프라인은 루트의 `Jenkinsfile` 을 쓴다. 3개 gather Job 모두 이 `Jenkinsfile` 을 Script Path 로 사용하고
`target_type` 파라미터로 gather 종류를 구분한다. (루트에는 호출자 통보용 `Jenkinsfile_portal` 도 있으나 별도 callback 파이프라인이다 — docs/17 참조.)

| Job 이름 | Script Path | target_type 기본값 |
|----------|-------------|-------------------|
| `{프로젝트명}.os-gather` | `Jenkinsfile` | `os` |
| `{프로젝트명}.esxi-gather` | `Jenkinsfile` | `esxi` |
| `{프로젝트명}.redfish-gather` | `Jenkinsfile` | `redfish` |

> Script Path 는 모두 `Jenkinsfile` 이다. 각 gather 디렉토리에는 별도 `Jenkinsfile` 이 없다.

### 인프라 자동화 Script Path (참고)

| Script Path | 설명 |
|-------------|------|
| `load-test/Jenkinsfile` | 부하 테스트 |
| `day1/{작업명}/{타입}/Jenkinsfile` | Day-1 작업 |
| `day2/{작업명}/{타입}/Jenkinsfile` | Day-2 작업 |

> 인프라 자동화 프로젝트는 별도 저장소에서 관리합니다.

---

## Job 별 파라미터 (호출자 입력)

3개 server-exporter Job 모두 동일한 파라미터 3종을 받습니다.

| 파라미터 | 필수 | 설명 |
|---------|------|------|
| `loc` | 필수 | 어느 사이트 Agent 에서 실행할지 (`ic` / `chj` / `yi`) |
| `target_type` | 자동 (Job 별 기본값) | `os` / `esxi` / `redfish` |
| `inventory_json` | 필수 | 대상 IP 배열 (os/esxi: `service_ip`, redfish: `bmc_ip`). 형식은 [../contract/01-input.md](../contract/01-input.md) 참조 |

`target_type` 의 기본값은 각 Job 의 Configure 화면에서 지정한다 (esxi-gather Job 은 `esxi`, redfish-gather Job 은 `redfish`).
`Jenkinsfile` 의 choice 파라미터 자체에는 기본값이 없어 파이프라인 기본은 첫 항목 `os` 다. 그래서 esxi/redfish Job 은 Configure 에서 기본값을 바꿔 둬야 호출자가 매번 보내지 않아도 된다.

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 호출자 입력 형식 자세히 | [../contract/01-input.md](../contract/01-input.md) |
| 파이프라인 4-Stage 동작 이해 | [04-pipeline-runtime.md](04-pipeline-runtime.md) |
| Job 동작 검증 | [../reference/live-validation.md](../reference/live-validation.md) |

## 자주 막히는 곳

| 증상 | 원인 / 해결 |
|------|------------|
| Job 빌드 시 "Workspace not found" | Pipeline SCM 설정에서 Branch 가 `*/main` 인지 확인 |
| RBAC 권한이 적용되지 않음 | Job 이름이 `server-exporter.os-gather` 같은 패턴과 일치하는지 확인 |
| 같은 Jenkinsfile 인데 동작이 다름 | 각 Job 의 `target_type` 기본값이 다르기 때문에 정상 |
