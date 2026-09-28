# 04. Jenkins Job 등록

> **이 문서는** server-exporter 의 수집 Job 을 Jenkins 에 등록할 때 참고한다.
> Job 이름 규칙, SCM 연결(브랜치·Script Path), 파라미터까지 다룬다.
> 신규 Jenkins 환경을 구축한 직후, 또는 Job 을 옮길 때 들어와 본다.

경로: Jenkins → New Item → Pipeline 선택

---

## Job 네이밍 규칙

RBAC Pattern 과 일치해야 권한이 자동 적용된다.

```text
{프로젝트명}.{작업명}
```

**수집 파이프라인 예시:** `server-exporter.gather` (운영 lab 에서는 `clovirone-server-gather` 이름으로 등록돼 있다)

**인프라 자동화 예시:**

- `infra-automation.{작업명}.{타입}` (예: `infra-automation.load-test.linux`)

---

## Pipeline SCM 설정

경로: Job 설정 → Pipeline 섹션

| 항목 | 값 |
|------|----|
| Definition | Pipeline script from SCM |
| SCM | Git |
| Repository | 이 저장소 (GitHub 또는 사내 GitLab 미러) |
| Credentials | 저장소 읽기 권한 credential (예: `gitlab-credentials`) |
| Branch | `*/production` |
| Script Path | `Jenkinsfile_portal` |
| Lightweight checkout | 켠다 (Jenkinsfile 만 먼저 읽는다) |

### 왜 `production` 브랜치인가

`production` 은 순수 수집 코드만 있는 배포 브랜치다 (`main` 에서 `.claude/`, `docs/ai/`, `scripts/ai/`,
`tests/reference/`, `tests/evidence/` 를 뺀 것). `main` 은 참조 데이터까지 약 17k 파일이라 컨트롤러의
'Resolve Location' 단계(2분 제한)가 체크아웃 도중 끊긴 적이 있다. 코드는 `main` 에 커밋한 뒤
`scripts/ai/promote_to_production.sh` 로 승격한다.

### Script Path

수집 파이프라인은 하나, `Jenkinsfile_portal` 이다. `target_type` 파라미터로 OS / ESXi / Redfish 를 고르므로
채널마다 Job 을 따로 만들 필요는 없다. 채널별 Job 을 두고 싶으면 같은 Script Path 로 Job 을 만들고 Configure 에서
`target_type` 기본값만 다르게 둔다.

> 예전의 비운영 `Jenkinsfile`(pytest 회귀 게이트)과 `Jenkinsfile_portal_test` 는 2026-09-28 에 삭제됐다.
> 이 두 이름을 Script Path 로 쓰는 Job 이 남아 있으면 `Jenkinsfile_portal` 로 바꾼다.

### Agent 쪽 전제

Gather 와 Validate Schema 는 Agent 에서 저장소를 체크아웃한다 — Agent 에 CLI `git` 이 있어야 한다.
Ansible venv 는 파이프라인이 `scripts/activate_ansible_venv.sh` 로 찾는다 ([02-agent-node.md](02-agent-node.md) 5절·9절).

### 인프라 자동화 Script Path (참고)

| Script Path | 설명 |
|-------------|------|
| `load-test/Jenkinsfile` | 부하 테스트 |
| `day1/{작업명}/{타입}/Jenkinsfile` | Day-1 작업 |
| `day2/{작업명}/{타입}/Jenkinsfile` | Day-2 작업 |

> 인프라 자동화 프로젝트는 별도 저장소에서 관리합니다.

---

## Job 파라미터 (호출자 입력)

`Jenkinsfile_portal` 이 정의하는 파라미터다. Job 을 처음 저장하고 한 번 실행하면 Jenkins 가 파라미터 UI 를 만든다.

| 파라미터 | 필수 | 설명 |
|---------|------|------|
| `loc` | 필수 | 어느 사이트 Agent 에서 실행할지 — `common/vars/locations.yml` 에 등록된 Location (`ic` / `chj` / `yi` / `git`) |
| `target_type` | 필수 (기본 `os`) | `os` / `esxi` / `redfish` |
| `inventory_json` | 필수 | 대상 IP 배열 (os/esxi: `service_ip`, redfish: `bmc_ip`). 형식은 [../contract/01-input.md](../contract/01-input.md) 참조 |
| `deploymentEnvironmentId` | 필수 | 포털 개발환경 ID — Callback 본문에 그대로 담긴다 |
| `eventUuid` | 선택 | 포털 이벤트 UUID — Callback 본문에 그대로 담긴다 |
| `callbackUrl` | 필수 | 결과를 POST 할 포털 주소 (`http://` 또는 `https://`, 따옴표·공백 불가). 경로 `/api/jenkins/gather/<target_type>` 이 뒤에 붙는다 |
| `verbosity` | 선택 (기본 `0`) | Ansible verbosity 0~4 |

---

## Add-on Job (고객별 추가 수집)

Add-on 저장소(`https://10.100.64.156/root/clovirone-server-gathering-addon.git`, GitLab `main`)의 Jenkinsfile 2개를
"Pipeline script from SCM" 으로 등록한다. 현재는 `형섭/` 폴더에 있다 — 공용 폴더로 옮길지는 운영 결정이다.

| Job | Script Path | 용도 |
|---|---|---|
| `형섭/clovirone-gathering-addon-deploy` | `deploy/Jenkinsfile` | Add-on 을 Agent 의 `ADDON_HOME`(기본 `/home/cloviradmin/clovirone-gathering-addon`)에 배포한다. 링크 교체 방식이라 수집 중인 빌드에 영향이 없고 최근 5개 버전을 남긴다. `CHECK_RULE=true` 는 배포 확인용 rule 을 하나 더한다 |
| `형섭/clovirone-gathering-addon-e2e` | `tests/e2e/Jenkinsfile` | 실제 Agent 에서 메인 수집 + Add-on 시나리오와 hook 엔진 테스트를 돌린다. lab 대상 IP 는 Job 파라미터이고, 메인 저장소 checkout 용 credential `hshwang token` 과 `server-gather-vault-password` 를 쓴다 |

Add-on 을 켜는 노드 환경변수 `SE_ADDON_DIR` 은 [08-ansible-config.md](08-ansible-config.md) 3절.

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 호출자 입력 형식 자세히 | [../contract/01-input.md](../contract/01-input.md) |
| 파이프라인 단계 동작 이해 | [04-pipeline-runtime.md](04-pipeline-runtime.md) |
| Job 동작 검증 | [../reference/live-validation.md](../reference/live-validation.md) |

## 자주 막히는 곳

| 증상 | 원인 / 해결 |
|------|------------|
| 'Resolve Location' 이 2분 제한으로 끊김 | Branch 가 `*/main` 이면 참조 데이터까지 받는다 — `*/production` 으로 |
| `[Resolve Location] 등록되지 않은 Location` | `loc` 값이 `common/vars/locations.yml` 에 없다 |
| Validate 뒤 "실행 노드를 기다리는 중" 이 계속됨 | `loc` 의 `agent_label` 을 가진 노드가 없다 — Manage Jenkins → Nodes 의 Labels 확인 |
| Gather 에서 `[venv] Ansible 실행환경(venv)을 찾지 못했습니다` | Agent 의 venv 가 없거나 파이프라인이 아는 경로 밖 — [02-agent-node.md](02-agent-node.md) 5절 · 9절 |
| Agent 체크아웃이 `git: command not found` 로 실패 | Agent 에 CLI `git` 이 없다 |
| RBAC 권한이 적용되지 않음 | Job 이름이 `server-exporter.gather` 같은 패턴과 일치하는지 확인 |
