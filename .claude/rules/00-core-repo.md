# 저장소 전체 공통 규칙

## 규칙 표기 구조

본 rule의 각 항목은 **Default / Allowed / Forbidden + Why + 재검토 조건** 3단 구조.

## 적용 대상
- `**/*` (저장소 전체)

## 현재 관찰된 현실

- 3-channel 통합 수집 시스템 (os-gather + esxi-gather + redfish-gather)
- Ansible 2.20.3 + Python 3.12.3 + Java 21 (Jenkins Agent)
- 멀티벤더 9종 (Dell / HPE / Lenovo / Supermicro / Cisco + Huawei / Inspur / Fujitsu / Quanta — 후 4종 lab 부재)
- Schema 11 sections (`system hardware bmc cpu memory storage network firmware users power thermal`)
- Jenkins pipeline: `Jenkinsfile_portal` 하나 (2026-09-28 에 비운영 `Jenkinsfile` · `Jenkinsfile_portal_test` · `test_sj` 는 삭제됐다).
  `Jenkinsfile_portal_Byid` 는 portal 의 동기화된 사본이다(`inventory_json` 기본값 1줄만 다름, 2026-10-09 ADR — 시험이 동기화를 강제).
  cron·trigger 없음. grafana 파이프라인은 존재하지 않는다. Agent venv 는 `scripts/activate_ansible_venv.sh` 가 고른다

> **세어 놓은 수는 적지 않는다.** adapter·fixture·baseline·테스트 개수, 파일 줄 수는
> 하나만 늘어도 그 수를 든 문서가 전부 동시에 틀린다. 실제로 `field_dictionary` 항목 수가
> 저장소 안에서 다섯 가지 값(83 / 134 / 168 / 173 / 실제)으로 갈렸다. 필요하면 그때 센다.
>
> ```bash
> ls adapters/redfish/*.yml adapters/os/*.yml adapters/esxi/*.yml | wc -l   # adapter
> grep -c '^\s*priority:' schema/field_dictionary.yml                       # field dictionary
> ls schema/baseline_v1/*.json | wc -l                                      # baseline
> find tests/fixtures -type f | wc -l                                       # fixture
> python -m pytest tests/ --collect-only -q | tail -1                       # 테스트
> ```
- 운영: 단일 main + feature/* 브랜치
- 정본: REQUIREMENTS.md / README.md / `docs/` 문서

## 목표 규칙

### 빌드 / 실행 명령

```bash
# Syntax check (각 채널)
ansible-playbook --syntax-check os-gather/site.yml
ansible-playbook --syntax-check esxi-gather/site.yml
ansible-playbook --syntax-check redfish-gather/site.yml

# 테스트
pytest tests/ -v
python tests/redfish-probe/probe_redfish.py --vendor dell   # 실장비 probe (pytest 아님)

# Schema 검증 (Jenkins Stage 3와 동일)
python tests/scripts/conditional_review.py

# 하네스 검증
python scripts/ai/verify_harness_consistency.py
python scripts/ai/verify_vendor_boundary.py
python scripts/ai/check_project_map_drift.py
```

### 모듈 / 채널 계층

```
호출자 (Jenkins Job)
  ↓
ansible.cfg + Jenkinsfile_portal (+ scripts/activate_ansible_venv.sh 가 Agent venv 선택)
  ↓
3-channel:
  ├── os-gather/site.yml (4-Play: 포트감지 → 감지실패 OUTPUT → Linux → Windows)
  ├── esxi-gather/site.yml (1-Play, community.vmware)
  └── redfish-gather/site.yml (precheck → detect vendor → 자격증명 해석 → vault → adapter → collect → normalize)
  ↓
Adapter (vendor 자동 감지)
  ↓ adapters/{redfish,os,esxi}/{vendor}_*.yml
common/ (precheck, normalize, build_*)
  ↓
callback_plugins/json_only.py → JSON envelope
```

### 증거 문서 갱신

- 코드 변경 → `docs/ai/CURRENT_STATE.md` 갱신
- 테스트 수행 → `docs/ai/catalogs/TEST_HISTORY.md` 기록
- 구조 변경 → `docs/ai/catalogs/PROJECT_MAP.md` + `python scripts/ai/check_project_map_drift.py --update`
- drift 발견 → `docs/ai/catalogs/CONVENTION_DRIFT.md`
- Round 검증 결과 → `tests/evidence/<날짜>-<주제>.md` + `docs/reference/decision-log.md`

### Rule 번호 선택 가이드

신규 rule 추가 시 아래 십의 자리 범위에서 선택. 같은 자리의 1의 자리 중 빈 번호 선택 가능.

| 범위 | 주제 | 현재 사용 | 빈 자리 |
|------|------|---------|--------|
| `00` | 저장소 전체 공통 | 00 | 01~09 |
| `10-19` | Gather (3-channel) | 10 core / 11 gather-output-boundary / 12 adapter-vendor-boundary / 13 output-schema-fields | 14~19 |
| `20-29` | 출력 + 통신 + 게이트 | 20 output-json-callback / 21 output-baseline-fixtures / 22 fragment-philosophy / 23 communication / 24 completion / 25 parallel / 26 multi-session / 27 precheck-guard / 28 empirical | 29 |
| `30-39` | 외부 시스템 통합 | 30 redfish-vmware-os / 31 callback | 32~39 |
| `40-49` | QA + 시각화 | 40 qa-pytest-baseline / 41 mermaid | 42~49 |
| `50-59` | 벤더 / 어댑터 정책 | 50 vendor-adapter-policy | 51~59 |
| `60-69` | 보안·시크릿 | 60 security-and-secrets | 61~69 |
| `70-79` | 문서·증거 정책 | 70 docs-and-evidence | 71~79 |
| `80-89` | CI / Jenkins | 80 ci-jenkins | 81~89 |
| `90-99` | 커밋·게이트 | 90 commit-convention / 91 task-impact-gate / 92 dependency-regression / 93 branch-merge / 95 production-critical / 96 external-contract / 97 incoming-merge | 94, 98, 99 |

**선택 절차**:
1. 위 표에서 주제에 맞는 십의 자리 선정
2. 같은 자리의 빈 번호 선택
3. `.claude/rules/NN-<kebab-case-slug>.md` 생성
4. `.claude/policy/surface-counts.yaml`의 `rules` 카운트 갱신
5. 본문에서 관련 skill / agent 를 `.claude/...` 경로로 참조 — `verify_harness_consistency.py` 가 그 경로의 실존을 검사한다

**Forbidden**: 위 표에 없는 십의 자리 신설. 새 주제군은 먼저 표 갱신 + 사용자 승인 PR.

## 금지 패턴

- **문서 갱신 없이 코드만 변경** — 근거: 작업 이력과 컨벤션 위반을 추적할 수 없어 향후 유지보수자가 변경 의도 파악 불가
- **테스트 없이 기능 추가** — 근거: 회귀 테스트 부재로 기존 기능 오동작 여부 검증 불가
- **타 프로젝트 잔재 어휘 사용** — Java/Spring Boot/MyBatis/FTL/Vue/jQuery/Gradle/MariaDB/Flyway/Spock/Playwright/Bitbucket Pipelines는 server-exporter 본문에 등장하면 안 됨 (`verify_harness_consistency.py` 검출). **예외 (Allowed)**: 본 rule 본문 (정의 목적 인용)

## 보호 경로 (참고용 — 정책 강제 해제됨)

> 2026-04-28 cycle-011: 사용자 명시 결정 — 정책 **강제**가 해제됐다. 본 절은 *권장 작업 영역 분류*로만 의미가 있다.
> PreToolUse Edit guard 와 `pre_commit_policy.py` 는 제거됐다. `.claude/policy/protected-paths.yaml` 은
> **파일로 남아 있다** — 스스로 DEPRECATED 라 적고 있고, `validate_claude_structure.py` 가 존재만 확인한다.

- **권장 신중**: `.git/, vault/**, *.log, *.env, *.pem, *.key`
- **권장 사용자 승인**: `ansible.cfg, Jenkinsfile*, schema/sections.yml, schema/field_dictionary.yml, schema/baseline_v1/**`
- **벤더 경계**: `adapters/**, redfish-gather/library/**, common/library/**, common/vars/vendor_aliases.yml`
- **문서 기준선**: `CLAUDE.md, REQUIREMENTS.md, README.md, `docs/` 문서, .claude/{rules,policy,skills,agents,ai-context,templates}/`

세부 정책 강제는 **삭제됨** (`ADR-2026-04-28-security-policy-removal.md` 참조).

## 리뷰 포인트

- 변경된 채널/모듈의 계층 위치 확인
- 보호 경로 변경 여부 + 사용자 승인 기록
- 증거 문서 갱신 여부
- 타 프로젝트 잔재 어휘 0건

## 테스트 포인트

- `ansible-playbook --syntax-check` 통과
- `pytest tests/` 통과
- 변경 영역 baseline 회귀 통과
- `verify_harness_consistency.py` 통과

## 관련 문서

- skills: `update-evidence-docs`, `investigate-ci-failure`, `task-impact-preview`
- agents: `ci-failure-investigator`, `change-impact-analyst`
- docs: `docs/develop/01-gather-structure.md`, `docs/ai/catalogs/PROJECT_MAP.md`
