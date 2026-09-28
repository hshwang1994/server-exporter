# Infra 엔지니어 역할

## 역할 설명
Jenkins 파이프라인 / Ansible 실행 환경 (Agent 노드) / Vault 시크릿 / 인프라 설정. 운영 토폴로지: agent-master 분리, loc 분리 (정본 `common/vars/locations.yml`). 프로젝트 ansible.cfg 는 `gathering = explicit` 라 fact 캐싱을 쓰지 않는다.

## 주요 영역
- `Jenkinsfile_portal`(운영, 5 stage) 하나 — 비운영 `Jenkinsfile` 과 `Jenkinsfile_portal_test` 는 2026-09-28 에 삭제됐다. Agent venv 는 `scripts/activate_ansible_venv.sh` 가 고른다
- `ansible.cfg` — Ansible 프로젝트 설정 (callback / cache / collections)
- `vault/` — `vault/<loc>/os/{linux,windows}.yml + vault/<loc>/esxi.yml` + `vault/<loc>/redfish/<vendor>.yml`
- `tools/` — 운영 도우미 스크립트
- `scripts/ai/` + `scripts/ai/hooks/` — AI 하네스 자동화 스크립트

## 로드할 ai-context 문서
1. `.claude/ai-context/infra/convention.md` — Jenkins / Agent / Vault / Redis 컨벤션
2. `.claude/ai-context/external/integration.md` — 외부 시스템 연동
3. `docs/ai/catalogs/PROJECT_MAP.md`
4. `.claude/ai-context/common/repo-facts.md`

## 정본 reference
- `docs/operate/01-jenkins-master.md` — Jenkins 설치 / 자격증명 / RBAC
- `docs/operate/02-agent-node.md` — Redis 설정
- `docs/operate/02-agent-node.md` — Agent 노드 구성 (방화벽 / 패키지 / 노드 등록)
- `docs/operate/03-job-registration.md` — Jenkins Job 등록 / 네이밍
- `docs/operate/04-pipeline-runtime.md` — Jenkins 파이프라인 런타임
- `docs/operate/08-ansible-config.md` — ansible.cfg

## 자주 사용하는 Skills
| Skill | 용도 |
|-------|------|
| `task-impact-preview` | Jenkinsfile / ansible.cfg 변경 전 영향 미리보기 |
| `scheduler-change-playbook` | Jenkins cron 변경 절차 |
| `investigate-ci-failure` | Jenkins 빌드 실패 분석 |
| `rotate-vault` | 벤더별 vault 회전 |
| `pr-review-playbook` | PR 생성 전 체크리스트 |
| `review-existing-code` | 4축 리뷰 (보안 축 강조) |

## 자주 사용하는 Agents
| Agent | 용도 |
|-------|------|
| `refactor-worker` | Jenkinsfile 리팩토링 |
| `jenkinsfile-engineer` | Jenkinsfile 보호 / 4-Stage 정합 |
| `deploy-orchestrator` | 배포 오케스트레이션 |
| `ci-failure-investigator` | Jenkins 실패 분석 |
| `release-manager` | 릴리즈 / 버전 관리 |
| `ansible-perf-investigator` | ansible 작업 시간 분석 |

(cycle-011: vault-rotator + security-reviewer agent 제거)

## 주의사항 (Critical)
- **vault/ 운영 권장**: 모든 vault 파일은 ansible-vault encrypt 권장 (cycle-011 보안 정책 해제 + cycle-012 8 vault encrypt 채택). 회전은 사용자 직접 운영.
- **Jenkinsfile cron 변경 (rule 80)**: cron 표현식 변경은 사용자 명시 승인 필수 (pre_commit_jenkinsfile_guard advisory). 4-Stage (Validate / Gather / Validate Schema / E2E Regression) 통과 의무.
- **Agent 노드 (`docs/operate/02-agent-node.md`)**: 새 loc 추가 또는 Agent 노드 변경은 Jenkins RBAC + 인벤토리 + 방화벽 동반 갱신.
- **callback URL 무결성 (rule 31)**: 호출자에게 결과 통지하는 callback URL은 공백/후행 슬래시 방어 처리 (이전 commit 4ccc1d7 fix 참조).
- **agent-master 망 분리**: Ingest 단계는 master에서 실행, gather는 agent에서 실행 (8bd80c1 / 8b2f128 commit 참조).
