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
| `addonRef` | 선택 (기본 비움) | 이 빌드에서만 쓸 Add-on 브랜치 · `refs/tags/<태그>` · 40자 커밋 해시. 비우면 전역 `ADDON_REPO_REF`(기본 `main`). Add-on 이 켜져 있지 않으면 무시된다 (Portal 은 보내지 않는다) |

---

## Add-on (고객별 추가 수집)

수집 Job 자체가 빌드마다 Add-on 저장소를 받아 간다 — 배포 Job · Agent 배치 · 노드 환경변수가 없고, Runner 를 늘리거나
다시 설치해도 할 일이 없다. 켜는 방법은 Jenkins 관리 → System → Global properties → Environment variables 에 전역
변수를 등록하는 것이다.

| 변수 | 필수 | 기본값 | 의미 |
|---|---|---|---|
| `ADDON_REPO_URL` | 켤 때 필수 | (없음 = 꺼짐) | Add-on 저장소 URL — `https://10.100.64.156/root/clovirone-server-gathering-addon.git` (GitLab 프로젝트 이름이 `clovirone-server-gathering-addon` 이고 코드 · 문서에서는 `clovirone-gathering-addon` 으로 부른다 — 같은 것) |
| `ADDON_REPO_REF` | 선택 | `main` | 브랜치 · `refs/tags/<태그>` · 40자 커밋 해시 |
| `ADDON_REPO_CREDENTIALS_ID` | 선택 | 없음 (익명) | 비공개 저장소일 때 Jenkins credential ID (Username with password — 사용자 이름 + 토큰) |
| `ADDON_REPO_SSL_VERIFY` | 선택 | `false` | Add-on 을 받는 git 명령의 TLS 인증서 검증. 기본은 검증하지 않아 자체 서명 인증서의 내부 GitLab 도 Runner 에 CA 를 설치하지 않고 된다. 정식 인증서 환경에서 검증하려면 `true` |

- 변수가 없으면 수집 결과는 Add-on 도입 전과 같다. 지우면 다음 빌드부터 꺼진다.
- 저장소를 받지 못하거나 Add-on 파일 검사에 실패하면 그 빌드는 Add-on 없이 수집하고 UNSTABLE 로 표시된다
  (콘솔 `[addon] unavailable: …`). 서버별 결과에는 아무 알림도 남지 않는다.
- 동작 흐름: [04-pipeline-runtime.md](04-pipeline-runtime.md) 3절. hook 계약: [../develop/07-addon-hook.md](../develop/07-addon-hook.md).
  설정 방법(현장용): Add-on 저장소 README.

### Add-on 전용 Job 은 두지 않는다

Add-on 을 실장비로 확인할 때도 이 수집 Job 을 `addonRef=<브랜치>` 로 실행한다 (절차: Add-on 저장소
`docs/development.md`). 옛 Job `형섭/clovirone-gathering-addon-e2e`(Add-on `tests/e2e/Jenkinsfile`)와
`형섭/clovirone-gathering-addon-deploy`(Add-on `deploy/Jenkinsfile`)는 Add-on 저장소에 그 파일이 더는 없으므로 지운다.

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
| 빌드가 UNSTABLE 이고 콘솔에 `[addon] unavailable: …` | Add-on 저장소를 받지 못했거나 파일 검사에 실패했다 — 전역 `ADDON_REPO_URL` / `ADDON_REPO_REF` / credential 값과 그 위 `[addon]` 줄. 기본 수집은 정상이다 |
| RBAC 권한이 적용되지 않음 | Job 이름이 `server-exporter.gather` 같은 패턴과 일치하는지 확인 |
