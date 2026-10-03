# 완료 판정 게이트

> AI가 "완료"를 선언하려면 6 검증 + 보고가 모두 PASS여야 한다.

## 규칙 표기 구조

본 rule의 각 항목은 **Default / Allowed / Forbidden + Why + 재검토 조건** 3단 구조.

## 적용 대상

- AI가 **"완료"**, **"끝났다"**, **"완결"** 등 종결 표현 사용 시
- 작업 종료 직전 마지막 답변

## 현재 관찰된 현실

- AI가 "자기가 한 일"만으로 완료 판단 → 검증/후속/문서 누락 사고 다수
- 사용자가 "남은 작업?" 물으면 새 작업 꺼내는 반복 패턴
- cycle-002에서 사용자 명시: "완료 선언은 6 체크리스트 통과 후만"

## 목표 규칙

### R1. 정적 검증 의무

- **Default**: 작업 종료 직전 다음 정적 검증 모두 실행
  - `ansible-playbook --syntax-check` (3-channel)
  - `pytest tests/` (변경 영역)
  - `yamllint` (편집한 YAML)
  - `python -m ast` 또는 `python -m py_compile` (편집한 Python)
- **Allowed**: 환경 제약 (Windows에서 ansible 미설치 등)으로 불가능한 항목은 "환경 제약" 명시 후 skip
- **Forbidden**: 정적 검증 1건 이상 미실행 후 "완료" 선언
- **Why**: 정적 검증 누락 시 syntax error / import error 같은 즉시 발견 가능한 버그가 commit에 포함 → CI 빌드 실패
- **재검토**: pre-commit hook이 100% 검증 강제하면 본 R1을 hook 책임으로 위임

### R2. 발견 가능한 버그 0건 의무

- **Default**: 다음 모두 PASS
  - 테스트 실패 0건 (pytest)
  - schema validate FAIL 0건 (Jenkins Stage 3 등가 — `output_schema_drift_check.py`)
  - baseline 회귀 FAIL 0건 (영향 vendor — Jenkins Stage 4 등가)
- **Allowed**: 사용자가 "회귀 skip" 명시한 경우. 단 NEXT_ACTIONS.md에 "회귀 미실행" 후속 작업 등재
- **Forbidden**: FAIL 발견 후 무시
- **Why**: 발견된 버그를 두고 "완료" 선언하면 다음 세션에서 동일 버그 재발견 + 사용자 신뢰 손상
- **재검토**: 자동 회귀 hook 도입 시

### R3. 문서 4종 갱신 의무

- **Default**: 작업 영향에 따라 다음 갱신 (rule 70 R1 매핑)
  - `docs/ai/CURRENT_STATE.md` (코드/구조/규칙 변경 시)
  - `docs/ai/catalogs/TEST_HISTORY.md` (테스트 실행 시)
  - 영향 `docs/` 문서 (정본 변경 시)
  - 영향 ADR (`docs/ai/decisions/ADR-*.md`, 결정 있을 시)
- **Allowed**: 영향 없는 항목은 skip 가능. 단 "X 영향 없음" 명시
- **Forbidden**: 코드 변경 + 문서 갱신 누락
- **Why**: 다음 세션이 진실성 있는 reference로 사용. 갱신 누락 시 stale catalog로 잘못된 판단
- **재검토**: 자동 doc-sync hook 도입 시

### R4. 후속 작업 식별 의무

- **Default**: 작업 종료 시 다음 분류
  - 후속 작업 있음 → `docs/ai/NEXT_ACTIONS.md` 갱신
  - 후속 없음 → 답변에 "후속 작업 없음" 명시
- **Allowed**: 후속이 외부 의존 (사용자 결정 / 실장비) 인 경우 표에 차단 사유 명시
- **Forbidden**: 후속 작업 묻지도 답하지도 않고 "완료" 선언
- **Why**: 사용자가 "남은 작업?" 묻기 전에 AI가 자발적으로 알려야 진짜 협업
- **재검토**: NEXT_ACTIONS 자동 갱신 hook 도입 시

### R5. Git 태그/push 완료 의무

- **Default** (rule 93 R1+R4 — 2026-05-01 + 2026-06-30 사용자 명시):
  - 태그 (해당 시): `v{영역}-{상태}-{YYYYMMDD}` 포맷
  - **현재 체크아웃된 브랜치는 자율 push** (main 포함 — origin 이 github + gitlab 동시 push)
  - 작업 종료 시 commit + push 무조건 (사용자 "보류" 명시 시 skip)
  - **순수 게더링 코드 변경 시 production 승격** — `python -m scripts.ai.prodgen promote --sha <main sha>` (2026-10-03 부터; 종전 `promote_to_production.sh` 는 shim)
    (하네스 제외 sync + github/gitlab push). **사용자 승인 불요** (2026-06-30 사용자 명시
    "production 에 넣는건 자동이여야 한다"). 완료 보고(R9)에 production 승격 여부 명시.
- **Forbidden**: force push / `--all` / 다른 브랜치 push (rule 93 R1) / 순수 코드 변경 후 production 승격 누락
- **Why**: 사용자 명시 (2026-05-01) — 작업 끝나면 자율 commit + push, github + gitlab 동기화
- **재검토**: force push 사고 발생 시 강화

### R6. Schema/Baseline 변경 시 회귀 통과 의무

- **Default**: 다음 변경 시 회귀 PASS 확인
  - `schema/sections.yml` + `field_dictionary.yml` → 영향 vendor baseline 전수
  - JSON envelope (rule 13 R5) → `verify-json-output` skill
  - Fragment (rule 22) → `validate-fragment-philosophy` skill
- **Allowed**: 변경 영역이 좁고 명백한 경우 (예: 주석만) 회귀 skip 가능. 단 이유 기록
- **Forbidden**: schema 변경 + 회귀 미실행
- **Why**: schema는 호출자 계약. 회귀 누락 시 호출자 시스템 파싱 실패
- **재검토**: schema 변경 자동 회귀 hook 도입 시

### R7. 종결어 사용 금지 (R1-R6 미통과 시)

- **Default**: R1~R6 중 하나라도 미통과 상태에서 "완료" / "끝났다" / "완결" / "다 했다" / "진짜 끝" 사용 금지
- **Allowed**: 부분 종결 표현
  - "ooo 까지 완료, △△ 남음"
  - "현재 PASS, 환경 제약으로 □□ 미실행"
  - "ooo 까지 진행, 사용자 결정 대기"
- **Forbidden**: R1~R6 미통과 + 위 종결어 사용
- **Why**: 종결어는 사용자에게 "안전하게 다음 작업으로 넘어가도 됨" 신호. 미통과 상태에서 종결어 사용은 사용자에게 잘못된 신호
- **재검토**: 종결어 자동 검출 hook 도입 시

### R8. "남은 작업?" 질문 답변 형식

- **Default**: 사용자가 "남은 작업?" 물으면 다음 3 카테고리 모두 답변
  1. AI 환경에서 아직 할 수 있는 것 (있으면 바로 제안)
  2. AI 환경에서 할 수 없는 것 (사용자/팀 몫)
  3. 의심되는 리스크
- **Allowed**: 카테고리 중 비어있는 것은 "없음" 명시
- **Forbidden**: 1 카테고리만 답변 후 종결
- **Why**: 사용자가 한 번 물었을 때 후속 작업 전체 그림을 받음. 반복 질의 줄임
- **재검토**: 후속 작업 매트릭스 자동 생성 시

### R9. 완료 보고 포맷

- **Default**: 완료 선언 시 다음 포맷
  ```
  ## [PASS] 완료 (체크리스트 6/6)

  - 정적 검증 : [결과]
  - 버그 : [0건 / 수정 commit]
  - 문서 : [4종 갱신 commit]
  - 후속 : [없음 / 티켓 list]
  - 태그 : v...
  - 회귀 : [PASS — N vendor baseline 통과]

  ## [INFO] AI 환경 외 남은 것
  - [사용자/팀 몫]
  ```
- **Allowed**: 작업이 작은 경우 (1 commit 미만) 간소화
- **Forbidden**: 체크리스트 6/6 표기 없이 종결어 사용
- **Why**: 일관 포맷으로 사용자가 빠르게 검증 가능
- **재검토**: 자동 보고 생성 hook 도입 시

## 금지 패턴

- R1~R6 중 skip 후 "완료" — R7
- "사용자/팀 몫" 라벨 남용 (AI가 할 수 있는 일 떠넘김) — R4 / R8
- 카테고리 중 1개만 답변 — R8
- 체크리스트 표기 누락 — R9

## 리뷰 포인트

- [ ] 완료 보고에 체크리스트 6/6 표기
- [ ] 종결어 사용 안 함 (미통과 상태 시)
- [ ] "남은 작업?" 답변에 3 카테고리 모두

## 관련

- rule: `23-communication-style`, `70-docs-and-evidence-policy`, `93-branch-merge-gate`
- 정본: `CLAUDE.md` §16
