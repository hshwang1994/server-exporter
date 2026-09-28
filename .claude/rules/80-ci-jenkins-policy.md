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
- Stage: Resolve Location(controller) / Validate(agent) / Gather(agent) / Validate Schema(agent) / Callback(controller)
- Agent 의 Ansible venv 는 `scripts/activate_ansible_venv.sh` 가 고른다 (`SE_ANSIBLE_VENV` → PATH 의
  `ansible-playbook` → `/app/ansible-env` → `/opt/ansible-env` → 실패). Jenkinsfile 에 venv 절대경로를 적지 않는다

## 목표 규칙

### R1. Stage 의무

`Jenkinsfile_portal` 은 다음 Stage 를 유지한다:

| Stage | 노드 | 책임 | FAIL 게이트 |
|---|---|---|---|
| 0. Resolve Location | controller (`built-in`) | `common/vars/locations.yml` 로 `loc` 검증 → `agent_label` | YES |
| 1. Validate | agent | 입력값 (target_type / inventory_json / callbackUrl / deploymentEnvironmentId) 형식 검증 | YES |
| 2. Gather | agent | venv 활성화 → ansible-playbook 실행 (해당 채널 site.yml) → `gather_output.json` stash | ansible 실패 UNSTABLE, 출력 0바이트 FAILURE |
| 3. Validate Schema | agent | venv 활성화 → field_dictionary 정합 (`tests/validate_field_dictionary.py`) | YES |
| 4. Callback | controller | 호출자 통보 (`httpRequest`, rule 31 무결성) | NO (UNSTABLE) |

### R1-A. venv 선택 규칙 (2026-09-28)

- **Default**: Gather · Validate Schema 는 `. "${WORKSPACE}/scripts/activate_ansible_venv.sh" || exit 1` 한 줄로 venv 를 고른다.
  순서 `SE_ANSIBLE_VENV` → PATH 의 `ansible-playbook` 실경로 옆 `activate` → `/app/ansible-env` → `/opt/ansible-env` → 실패.
- **Forbidden**: Jenkinsfile · Job 사본 · 운영 스크립트에 venv 절대경로(`. /opt/ansible-env/bin/activate` 류)를 직접 적기,
  activate 실패 뒤 시스템 python 으로 조용히 진행하기 (`set -e` 없는 `sh` 블록에서 activate 만 부르는 형태)
- **Why**: 설치 자동화 Runner(`/app`)와 직접 구축 Agent(`/opt`)가 공존하고 배치는 또 바뀔 수 있다. 근거
  `docs/reference/decision-log.md` 2026-09-28, 검증 `tests/unit/test_activate_ansible_venv.py`

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
