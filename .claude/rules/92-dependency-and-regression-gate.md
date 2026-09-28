# 의존성 변경 및 회귀 검사 게이트

## 적용 대상
- 저장소 전체 (`**`) — 의존성 변경 / 공통 영역 변경 / 대형 기능 추가 시

## 목표 규칙

### R1. 의존성 변경 사용자 확인

- **Default**: `requirements.yml` (ansible collection) / `requirements.txt` (pip) 추가/제거/버전 변경은 **구현 전 사용자 확인** 필수
- **Allowed**: 사용자 WHY+WHAT+IMPACT 승인 기록 있으면
- **Forbidden**: convention 규칙만 근거로 의존성 제거
- **확인 절차**:
  1. 직접 사용 확인 (`grep -r "import <package>"`)
  2. Transitive 사용 확인 (`pip show <package>` + ansible collection 의존)
  3. 영향 파일 범위
  4. 사용자에게 WHY + WHAT + IMPACT 질의

### R2. Convention 위반 즉시 수정 금지 + Additive 검증 절차 (cycle 2026-05-06-post 학습 형식화)

- **Default**: convention 위반 발견해도 기존 기능 정상 동작 중이면 즉시 제거 안 함
- **Allowed**: 위반 기록 (CONVENTION_DRIFT) → 영향 분석 → 마이그레이션 계획 → 사용자 승인 → 단계적 전환
- **Forbidden**: "convention 위반이니까 즉시 제거"

#### Additive 검증 절차 (호환성 cycle 의무)

호환성 cycle (사용자 사이트 사고 → fallback 도입) 시 Additive only 원칙 (rule 96 R1-B 와 연동) 의 검증 절차:

| 단계 | 검증 항목 | 명령 / 도구 |
|---|---|---|
| 1 | envelope 13 필드 / `data.<section>.<field>` shape 변경 0 | `scripts/ai/hooks/envelope_change_check.py` |
| 2 | 기존 path 유지 (수정 안 됨) — 새 path **추가만** | `git diff` 검토 — 삭제 line 0 / 추가 line만 |
| 3 | sections / field_dictionary entries 의미 변경 0 (count-agnostic — 실측은 field_dictionary 헤더) | rule 13 R5 / R7 (`docs/contract/03-fields.md` 동기화) |
| 4 | 호출자 시스템 파싱 변경 0 | `docs/contract/03-fields.md` / baseline_v1 회귀 |
| 5 | 회귀 fixture 추가 (호환성 fix 영역만) | `tests/fixtures/` mock 추가 |

- **Forbidden** (Additive 위반):
  - 기존 path 삭제 / 리네임 (호환성 cycle 외 영역)
  - envelope shape 변경 (rule 13 R5 / rule 96 R1-B)
  - 기존 sections / field_dictionary entries 의미 변경
  - 호출자 시스템 파싱 변경 유발 (rule 96 R1-B)
- **Why**: cycle 2026-05-06 학습 — 호환성 fix 9 라인 변경 (M-D2 W1~W6) 을 Additive only 검증 후 도입 → 호출자 영향 0. 본 검증 절차 누락 시 호환성 cycle 에서 schema 확장 발생 위험 (`diagnosis.details.detail` cycle 2026-05-01 사고 사례)
- **재검토**: Additive 자동 검증 hook (`pre_commit_additive_only_check.py`) 도입 시 advisory → blocking 격상

### R3. 공통 영역 변경 회귀 체크리스트

다음 영역 변경 시 회귀 체크리스트 의무:

- 공통 fragment 영역 (`common/tasks/normalize/`)
- 공통 라이브러리 (`common/library/`, `redfish-gather/library/`)
- adapter 추가/수정
- callback (`callback_plugins/json_only.py`)
- 출력 schema (sections.yml / field_dictionary.yml)
- `Jenkinsfile_portal`, `scripts/activate_ansible_venv.sh`
- vault 회전

체크리스트:
- [ ] 영향 vendor baseline 회귀 통과
- [ ] 3-channel syntax-check 통과
- [ ] 출력 envelope 13 필드 유지
- [ ] 외부 호출 timeout 정상

### R4. 대형 기능 추가 영향도 필수

- **Default**: 새 vendor 추가 / 새 섹션 / 새 채널 같은 대형 기능 시 신규 기능 + 기존 기능 영향도 체크리스트 통과
- 기존 vendor adapter 영향
- 기존 baseline 회귀 영향
- Jenkins 4-Stage 시간 영향

### R5. Schema 버전 사용자 확인

- **Default**: `schema/sections.yml` + `schema/field_dictionary.yml` 버전 변경은 **사용자 명시 확인** 필수 (다른 작업자/세션에서 같은 버전 사용 가능 → 충돌 방지 정책)
- **Forbidden**: AI 임의로 버전 결정
- **Why**: 다른 작업자/세션에서 같은 버전 사용 가능

### R6. 비즈니스 로직 판단 근거 (코드 우선)

- **Default**: 비즈니스 로직(target_type 분기 / vendor 검증 / 섹션 가용성 등)은 소스 코드 근거
- **Forbidden**: 비개발자 서술만으로 비즈니스 로직 확정. 기존 코드와 모순 시 개발자 확인

### R7. 라이브러리 충돌 탐색

- 새 ansible collection: 기존 collection과 호환성 (community.vmware vs ansible.vmware)
- 새 pip 패키지: transitive 의존성 충돌

### R8. include_tasks 의존성 추가

- 기존 site.yml에 include_tasks 추가 시 의존 변수 / 외부 시스템 의존 명시

### R9. 회귀 검사 자동 포함

본 rule R3 + R4 + R8과 회귀 영역 정의가 겹치므로, 자동 식별 정본은 **rule 91 R7**에 위임. 본 rule은 회귀 검사 결과의 게이트(통과/차단) 책임만 보유.

### R10. 대형 기능 영향 체크리스트 선통과

- **Default**: 대형 기능 착수 전 R3 + R4 사고 실험 (시뮬레이션). 통과 가능한 설계 확인 후 착수

## 금지 패턴

- convention 맹신 의존성 제거 — R1+R2
- 신규 기능만 테스트하고 "완료" — R3+R4
- AI 임의 schema 버전 — R5
- 사용자 설명만으로 로직 확정 — R6
- 라이브러리 충돌 탐색 skip — R7
- include_tasks 의존성 검증 skip — R8
- 회귀 영역 변경 + 회귀 대상 제외 — R9
- 대형 기능 사고 실험 skip — R10

## 리뷰 포인트

- [ ] requirements 변경 사용자 승인
- [ ] convention 위반 시 마이그레이션 계획
- [ ] 공통 영역 변경 + 회귀 체크리스트
- [ ] 대형 기능 + 기존 영향
- [ ] schema 버전 사용자 확인
- [ ] include_tasks 의존성 검증

## 관련

- rule: `91-task-impact-gate`, `95-production-code-critical-review`, `97-incoming-merge-review`
- skill: `prepare-regression-check`, `vendor-change-impact`
- 정본: `.claude/rules/00-core-repo.md` (저장소 공통) + 각 영역 rule
