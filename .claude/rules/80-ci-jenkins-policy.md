# CI / Jenkins 정책

## 적용 대상
- `Jenkinsfile_portal` (수집 파이프라인 정본 — 2026-09-28 부터 하나뿐), `scripts/activate_ansible_venv.sh`
- `ansible.cfg`
- Jenkins Job 등록 (`docs/operate/03-job-registration.md`)
- callback URL endpoint 구성

## 현재 관찰된 현실

- Jenkins pipeline: `Jenkinsfile_portal` 하나. 비운영 `Jenkinsfile`(pytest 회귀 게이트) · `Jenkinsfile_portal_test` · `test_sj`(portal 사본)는 2026-09-28 에 삭제됐다
  (사용자 결정). pytest 회귀는 커밋 전 로컬 검증이다
- 외부 CI 시스템 미사용 (Jenkins 단독)
- Stage: Validate(agent 없음) / Resolve Location(agent 없음, `readTrusted`) / Gather(agent) / Validate Schema(agent) / Callback(controller) — 2026-10-03 순서·노드 변경
- Agent 의 Ansible venv 는 `scripts/activate_ansible_venv.sh` 가 고른다 (`SE_ANSIBLE_VENV` → PATH 의
  `ansible-playbook` → `/app/ansible-env` → `/opt/ansible-env` → 실패). Jenkinsfile 에 venv 절대경로를 적지 않는다

## 목표 규칙

### R1. Stage 의무

`Jenkinsfile_portal` 은 다음 Stage 를 유지한다:

| Stage | 노드 | 책임 | FAIL 게이트 |
|---|---|---|---|
| 0. Validate | agent 없음 | 입력값 (target_type / inventory_json / callbackUrl / deploymentEnvironmentId) 형식 검증 → 접수 manifest `env.SE_MANIFEST_JSON` | YES |
| 1. Resolve Location | agent 없음 | `readYaml text: readTrusted('common/vars/locations.yml')` 로 `loc` 검증 → `agent_label` (컨트롤러 전체 checkout 금지 — main 2분 초과 사고) | YES |
| 2. Gather | agent (stage 합산 상한 115 min) | `gather_manifest.json` 기록 → (전역 `ADDON_REPO_URL` 이 있으면 Add-on 체크아웃 · 검사 — R1-B) → venv 활성화 → `scripts/gather_budget.sh` 로 예산 재계산(ansible 직전) → `timeout --signal=INT --kill-after=90 <예산> ansible-playbook … -f <forks>` (검증 파라미터 `redfishAccountDryrun`/`gatherBudgetForceSec` 는 기본값이면 영향 없음) → rc → outcome → post{always} Layer A(`scripts/finalize_gather_output.py`) + `archiveArtifacts` + `stash(allowEmpty)` + 조건부 `deleteDir` | Add-on 못 받으면 UNSTABLE + Add-on 없이 수집; ansible rc 는 outcome 으로 기록 (stage 를 끊지 않는다) |
| 3. (pipeline `post { always }`) 마무리 | controller, `timeout(720 s){ node('built-in') }` | 입력 회수(unstash → unarchive) → Layer A 결과 우선 / Groovy 최소 보충 → 접수 수 == 결과 수 → 호출자 통보 (`httpRequest`, rule 31 무결성, 남은 예산 안 ≤3회) → `callback_body.json` 보존 | NO (UNSTABLE) |

- **2026-10-03 (Phase 4)**: `Validate Schema`(FAIL 게이트) · `Callback` stage 는 삭제됐다. field_dictionary 정합은 `scripts/ai/ci_gate.sh`
  (커밋 전 · CI 진입점) 가 맡는다 — 수집 Job 에서 정적 검사로 **결과 전달을 막지 않는다**. 결과 전달은 stage 가 아니라 pipeline
  `post { always }` 다 (stage 실패 · agent 대기 초과 · 1회 Abort 뒤에도 실행 경로가 있다). 요청 1 = 결과 1 은 Layer A/B 가 맞춘다.
- **Forbidden**: 수집 Job 에 정적 FAIL 게이트 stage 재도입, Callback 을 stage 로 되돌리기(끊긴 빌드에서 전달이 사라진다),
  `timeout` 없이 ansible 실행, 예산 계산을 node 진입 시점 값으로 집행하기(ansible 직전 재계산이 계약 — Astra 3차 acceptance).

### R1-A. venv 선택 규칙 (2026-09-28)

- **Default**: Gather(수집 · Layer A 마무리)는 `. "${WORKSPACE}/scripts/activate_ansible_venv.sh" || exit 1` 한 줄로 venv 를 고른다.
  순서 `SE_ANSIBLE_VENV` → PATH 의 `ansible-playbook` 실경로 옆 `activate` → `/app/ansible-env` → `/opt/ansible-env` → 실패.
- **Forbidden**: Jenkinsfile · Job 사본 · 운영 스크립트에 venv 절대경로(`. /opt/ansible-env/bin/activate` 류)를 직접 적기,
  activate 실패 뒤 시스템 python 으로 조용히 진행하기 (`set -e` 없는 `sh` 블록에서 activate 만 부르는 형태)
- **Why**: 설치 자동화 Runner(`/app`)와 직접 구축 Agent(`/opt`)가 공존하고 배치는 또 바뀔 수 있다. 근거
  `docs/reference/decision-log.md` 2026-09-28, 검증 `tests/unit/test_activate_ansible_venv.py`

### R1-B. Add-on 빌드별 체크아웃 (2026-09-29)

- **Default**: Add-on 은 Jenkins 전역 환경변수 `ADDON_REPO_URL` 하나로 켠다. Gather 가 빌드마다
  `bash scripts/addon_checkout.sh <URL> <ref> ${WORKSPACE}/addon` 으로 받고 `addon/tools/check_layout.py --targets <서버 종류>`
  로 검사한 뒤 **ansible `sh` 만** `withEnv(["ADDON_DIR=…"])` 로 감싼다. 실패는 `unstable("[addon] unavailable: …")` 이고
  Add-on 없이 수집한다 (host 별 `errors[]` 없음). 이 빌드의 서버 종류를 Add-on 이 지원하지 않으면(esxi · redfish, rc 3) 켜지 않는다.
- **Allowed**: `ADDON_REPO_REF`(브랜치 · `refs/tags/<태그>` · 40자 해시) · `ADDON_REPO_CREDENTIALS_ID`(usernamePassword +
  `GIT_ASKPASS`) · `ADDON_REPO_SSL_VERIFY`(기본 `false` — `-c http.sslVerify=false` 를 그 git 명령에만).
- **Forbidden**: `ADDON_DIR` 을 stage/pipeline `environment{}` 나 노드 환경변수에 두기, 배포 Job · `ADDON_HOME` · 라벨 기준 배치
  부활, `GIT_SSL_NO_VERIFY` 전역 · `git config --global` · Runner CA 설치를 전제하기, Add-on 실패로 `error`(빌드 중단),
  `git clone --branch`(커밋 해시 불가), 짧은 해시 허용, Add-on 선택에 `loc` · 라벨 · Runner 이름 사용.
- **Why**: 스케줄링(`loc`)과 availability 를 분리해야 Runner 수 · 라벨 · 재설치와 무관해진다. 근거
  `docs/ai/decisions/ADR-2026-09-29-addon-per-build-checkout.md`, 검증 `tests/unit/test_jenkinsfile_portal_addon.py` ·
  `tests/unit/test_addon_checkout.py`.

상세: `docs/ai/catalogs/JENKINS_PIPELINES.md`.

### R2. cron 변경 사용자 승인

- **Default**: cron 표현식 변경은 사용자 명시 승인 (rule 92 R5와 동일 정신)
- **Forbidden**: AI가 임의로 cron 변경 (운영 영향 큼)

`pre_commit_jenkinsfile_guard.py`가 advisory.

### R3. agent-master 망 분리

- Callback 단계 → master (`Jenkinsfile_portal`)
- gather (ansible-playbook) → agent 실행

### R4. 빌드 실패 분석

- **Default**: 실패 시 `investigate-ci-failure` skill로 console log 분석
- **재시도**: 실패가 일시적 (네트워크 / 외부 시스템 timeout)이면 재시도. 코드/설정 문제면 fix 후 재실행

### R5. 단계적 적용

- 운영 배포 시간대 외
- 일부 loc만 먼저 (현재 단일 loc 운영이면 적용 안 함)
- callback URL 무결성 (rule 31)

### R6. 모니터링

- 첫 cron 실행 결과 모니터링
- Jenkins 빌드 시간 / 성공률 baseline 대비

## 금지 패턴

- Stage 일부 skip — R1 / venv 절대경로 하드코딩 — R1-A
- AI 임의 cron 변경 — R2
- agent에서 Ingest / Callback 실행 — R3
- 빌드 실패 후 분석 없이 재시도 반복 — R4

## 리뷰 포인트

- [ ] Jenkinsfile 변경이 R1 Stage 구조 유지, venv 절대경로 0건 (R1-A)
- [ ] cron 변경 사용자 승인
- [ ] agent-master 망 분리 준수

## 관련

- rule: `31-integration-callback`, `92-dependency-and-regression-gate`
- skill: `scheduler-change-playbook`, `investigate-ci-failure`
- agent: `refactor-worker`, `jenkinsfile-engineer`, `ci-failure-investigator`
- 정본: `docs/operate/01-jenkins-master.md`, `docs/operate/03-job-registration.md`, `docs/operate/04-pipeline-runtime.md`
