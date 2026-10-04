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
'Resolve Location' 단계(2분 제한)가 체크아웃 도중 끊긴 적이 있다(2026-10-03 부터 이 단계는 `readTrusted` 로
파일 하나만 읽어 체크아웃을 하지 않는다 — Lightweight checkout 이 켜져 있어야 한다). 코드는 `main` 에 커밋한 뒤
`scripts/ai/promote_to_production.sh` 로 승격한다.

### Script Path

수집 파이프라인은 하나, `Jenkinsfile_portal` 이다. `target_type` 파라미터로 OS / ESXi / Redfish 를 고르므로
채널마다 Job 을 따로 만들 필요는 없다. 채널별 Job 을 두고 싶으면 같은 Script Path 로 Job 을 만들고 Configure 에서
`target_type` 기본값만 다르게 둔다.

> 예전의 비운영 `Jenkinsfile`(pytest 회귀 게이트)과 `Jenkinsfile_portal_test` 는 2026-09-28 에 삭제됐다.
> 이 두 이름을 Script Path 로 쓰는 Job 이 남아 있으면 `Jenkinsfile_portal` 로 바꾼다.

### Agent 쪽 전제

Gather 는 Agent 에서 저장소를 체크아웃한다 — Agent 에 CLI `git` 이 있어야 한다 (2026-10-03 부터 Agent 를 쓰는 stage 는 Gather 하나다).
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
| `loc` | 필수 | 어느 사이트 Agent 에서 실행할지 — `common/vars/locations.yml` 에 등록된 Location (`ic` / `cj` / `yi` / `git`) |
| `target_type` | 필수 (기본 `os`) | `os` / `esxi` / `redfish` |
| `inventory_json` | 필수 | 대상 IP 배열 (os/esxi: `service_ip`, redfish: `bmc_ip`). 형식은 [../contract/01-input.md](../contract/01-input.md) 참조 |
| `deploymentEnvironmentId` | 필수 | 포털 개발환경 ID — Callback 본문에 그대로 담긴다 |
| `eventUuid` | 선택 | 포털 이벤트 UUID — Callback 본문에 그대로 담긴다 |
| `callbackUrl` | 필수 | 결과를 POST 할 포털 주소 (`http://` 또는 `https://`, 따옴표·공백 불가). 경로 `/api/jenkins/gather/<target_type>` 이 뒤에 붙는다 |
| `verbosity` | 선택 (기본 `0`) | Ansible verbosity 0~4 |

---

## Add-on (고객별 추가 수집)

수집 Job 이 빌드마다 Add-on 저장소를 받아 간다. Agent 에 따로 둘 파일이나 노드 환경변수는 없어 Runner 를 늘리거나
다시 설치해도 할 일이 없다. 켜는 방법은 Jenkins 관리 → System → Global properties → Environment variables 에 전역
변수를 등록하는 것이다.

| 변수 | 필수 | 기본값 | 의미 |
|---|---|---|---|
| `ADDON_REPO_URL` | 켤 때 필수 | (없음 = 꺼짐) | Add-on 저장소 URL — `https://10.100.64.156/root/clovirone-server-gathering-addon.git` (문서에서는 `clovirone-gathering-addon` 으로 부른다) |
| `ADDON_REPO_REF` | 선택 | `main` | 브랜치 · `refs/tags/<태그>` · 40자 커밋 해시 |
| `ADDON_REPO_CREDENTIALS_ID` | 선택 | 없음 (익명) | 비공개 저장소일 때 Jenkins credential ID (Username with password — 사용자 이름 + 토큰) |
| `ADDON_REPO_SSL_VERIFY` | 선택 | `false` | Add-on 을 받는 git 명령의 TLS 인증서 검증. 기본은 검증하지 않아 자체 서명 인증서의 내부 GitLab 도 Runner 에 CA 를 설치하지 않고 된다. 정식 인증서 환경에서 검증하려면 `true` |

- 변수가 없으면 Add-on 을 실행하지 않는다. 지우면 다음 빌드부터 꺼진다.
- 저장소를 받지 못하거나 Add-on 파일 검사에 실패하면 그 빌드는 Add-on 없이 수집하고 UNSTABLE 로 표시된다
  (콘솔 `[addon] unavailable: …`). 서버별 결과에는 Add-on 오류가 남지 않는다.
- Add-on 변경은 Add-on 저장소 `main` 에 올리면 다음 수집부터 쓰인다 (`ADDON_REPO_REF` 가 기본값일 때).
  Add-on 전용 Job 은 없고, 실장비 확인도 이 수집 Job 의 결과로 한다.
- 동작 흐름: [04-pipeline-runtime.md](04-pipeline-runtime.md) 3절. hook 계약: [../develop/07-addon-hook.md](../develop/07-addon-hook.md).
  설정 방법(현장용): Add-on 저장소 README.

---

## CI Job (main 전용) — `clovirone-cicd/clovirone-server-gather-ci` (2026-10-04 등록)

수집 Job 에서 빠진 정적 검사(field_dictionary 정합 · pytest 회귀 · Layer A/B 동치 · 예산 공식)와 production 생성·검증(prodgen Build/Drift/Verify, Harness Job 호출, 조건부 Promote)은 이 Job 이 맡는다. 수집 · 대상 서버 접속은 없다. 자격증명은 Prodgen Verify(린터 토큰 `se-jenkins-lint` · `server-gather-vault-password`) · Evidence Aggregate(`se-jenkins-lint`) · Prodgen Promote(push 토큰)에서만 바인딩한다.

| 항목 | 값 |
|---|---|
| Job 종류 | 일반 Pipeline (Pipeline script from SCM) — Multibranch 가 아니다 |
| Repository | 수집 Job 과 같은 저장소 |
| Branch Specifier | `*/main` (main 전용 — production 에는 이 파일이 없다) |
| Script Path | `Jenkinsfile_ci` |
| Lightweight checkout | 켬 |
| 트리거 | 없음 (webhook 또는 수동; `pollSCM`/cron 은 승인 항목) |
| Agent | `linux` 라벨 Runner 1대 (venv 는 `scripts/activate_ansible_venv.sh` 가 고른다); `pwsh` 가 없으면 `scripts/ai/prodgen/ci_pwsh_bootstrap.sh` 가 사용자 권한으로 `$HOME/.local/powershell` 에 준비한다(시스템 변경 없음) |
| 파라미터 | `PROMOTE`(기본 false) · `PROMOTE_SHA` · `PROMOTE_DRY_RUN`(기본 true) · `BOOTSTRAP_BASELINE`(기본 빈 값) · `HARNESS_SCENARIOS`(18) · `HARNESS_BOUNDED_SCENARIOS`(5, Tier 2 — 승인 전 PARTIAL) · `HARNESS_TREE_SCENARIOS`(10) · `E2E_MAIN_ENTRIES` · `E2E_TIP_OBSERVATIONS_JSON`(fail-closed 빌드의 직접 revision 증거 — 트리거 측 tip 관측) |
| 폴더 credential | `se-jenkins-lint`(Username with password — Jenkins API 토큰, 린터·artifact 읽기) · `hshwang token`(GitHub push) · `se-gitlab-push`(GitLab push — 없으면 Promote 는 dry-run 까지만) |

결과: Gate 가 exit 2(건너뛴 단계 있음)면 UNSTABLE, exit 1 이면 FAILURE(뒤 stage 는 진단용으로 계속 돌지만 Promote 는 `ci_stage_results.json` 을 읽어 원격을 바꾸지 않는다). 보고서(`ci_gate.log` · corpus 비교 · 예산 self-test · `harness_*_results.json` · `prodgen_*.json` · `prodgen_verify_report(.aggregated).json`)는 artifact. stage 표 정본은 [AI 카탈로그가 아닌 이 저장소의 `Jenkinsfile_ci` 머리말 주석]이다.

같은 폴더의 **Harness Job** `clovirone-server-gather-harness`(Script Path `tests/jenkins/harness/Jenkinsfile_harness`, Branch `*/main`, 파라미터 `SCENARIO`·`MAIN_SHA`·`FUNCTIONS_SRC`·`ARTIFACT_BASE_URL`·`EXPECTED_SHA256`·`SINK_PORT`·`BOUNDED`·`LOC`·`DEPLOYMENT_ENV`)은 CI 의 Harness Driver 가 시나리오당 1빌드로 호출한다. 수집 Job 이 아니며 production 에는 없다. 정의 `jenkins/jobs/clovirone-server-gather-harness/config.xml`.

진단 Job 둘(2026-10-04, main 전용 · 읽기 전용 · production 에 없음): **`clovirone-server-gather-perf-observe`**(Script Path `tests/jenkins/harness/Jenkinsfile_perf_observe`; `NODE_NAME` 노드에서
`perf_observe.py` 가 같은 Runner 의 Gather 빌드 프로세스 트리를 `SE_BUILD_ID` 로 귀속해 PSS · 활성 worker · MemAvailable · swap 을 샘플링 — forks 메모리 상수의 실측 근거) 와
**`clovirone-server-gather-net-probe`**(Script Path `tests/jenkins/harness/Jenkinsfile_net_probe`; `TARGETS` 의 route · ICMP · 관리 TCP connect · ARP/neighbour · tracepath · Redfish ServiceRoot
무인증 GET 을 Runner 망에서 읽어 `net_probe.txt` 로 — 무응답 자산의 존재·경로 진단). 정의 `jenkins/jobs/<job>/config.xml`.

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 호출자 입력 형식 자세히 | [../contract/01-input.md](../contract/01-input.md) |
| 파이프라인 단계 동작 이해 | [04-pipeline-runtime.md](04-pipeline-runtime.md) |
| Job 동작 검증 | [../reference/live-validation.md](../reference/live-validation.md) |

## 자주 막히는 곳

| 증상 | 원인 / 해결 |
|------|------------|
| 'Resolve Location' 이 2분 제한으로 끊김 | 2026-10-03 이전 Jenkinsfile: Branch 가 `*/main` 이면 참조 데이터까지 받는다 — `*/production` 으로. 이후 Jenkinsfile: `readTrusted` 가 체크아웃을 하지 않으므로 Job 의 Lightweight checkout 이 꺼져 있는지 확인 |
| `readTrusted` 가 전체 체크아웃으로 떨어졌다는 콘솔 메시지 | Job 의 Lightweight checkout 이 꺼져 있거나 SCM 플러그인이 lightweight 를 지원하지 않는다 — Job 설정 확인 |
| `[Resolve Location] 등록되지 않은 Location` | `loc` 값이 `common/vars/locations.yml` 에 없다 |
| `[Resolve Location] 라벨 '… && (…)' 을 모두 가진 온라인 노드가 없습니다` 로 바로 실패 | `loc` 의 `agent_label` 과 `target_type` 의 능력 라벨(`os` 는 `linux`+`windows`, `esxi`, `redfish`)을 모두 가진 온라인 노드가 없다 — Manage Jenkins → Nodes 의 Labels 확인 ([02-agent-node.md](02-agent-node.md) 8절) |
| Gather 에서 `[venv] Ansible 실행환경(venv)을 찾지 못했습니다` | Agent 의 venv 가 없거나 파이프라인이 아는 경로 밖 — [02-agent-node.md](02-agent-node.md) 5절 · 9절 |
| Agent 체크아웃이 `git: command not found` 로 실패 | Agent 에 CLI `git` 이 없다 |
| 빌드가 UNSTABLE 이고 콘솔에 `[addon] unavailable: …` | Add-on 저장소를 받지 못했거나 파일 검사에 실패했다 — 전역 `ADDON_REPO_URL` / `ADDON_REPO_REF` / credential 값과 그 위 `[addon]` 줄. 기본 수집은 정상이다 |
| RBAC 권한이 적용되지 않음 | Job 이름이 `server-exporter.gather` 같은 패턴과 일치하는지 확인 |
