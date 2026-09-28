# Output Schema / Fields / Baseline 정합

## 적용 대상
- `schema/sections.yml`, `schema/field_dictionary.yml`, `schema/fields/**`, `schema/baseline_v1/**`, `schema/examples/**`
- `common/tasks/normalize/build_*.yml`
- `callback_plugins/json_only.py`

## 현재 관찰된 현실

- 11 sections (system / hardware / bmc / cpu / memory / storage / network / firmware / users / power / thermal)
- field_dictionary.yml: 항목마다 `priority` 가 must / nice / skip 중 하나다 (개수는 세지 않는다 — rule 00 의 세는 명령 참조).
  **런타임 코드는 이 파일을 읽지 않는다** — 테스트·CI·훅 전용이다
- baseline_v1: vendor별 회귀 기준선
- Jenkins Stage 3 (Validate Schema) 가 FAIL 게이트, Stage 4 는 Callback (`Jenkinsfile_portal` 하나 — 정본은 rule 80 R1).
  pytest 회귀(tests/e2e · tests/regression)는 2026-09-28 부터 Jenkins 단계가 아니라 커밋 전 로컬 검증이다
- DB schema 없음 — 본 출력 schema가 동등 역할

## 목표 규칙

### R1. 3종 동반 갱신

- **Default**: schema 변경은 다음 3종 동시 갱신:
  1. `schema/sections.yml` (섹션 list)
  2. `schema/field_dictionary.yml` (필드 정의)
  3. `schema/baseline_v1/{vendor}_baseline.json` (영향 vendor 전수)
- **Allowed**: 1 vendor만 영향 받는 vendor-specific 필드는 그 vendor baseline만 갱신
- **Forbidden**: sections.yml만 수정하고 field_dictionary 미갱신, 또는 그 반대
- **Why**: 한쪽만 수정하면 Jenkins Stage 3 (정합 검증) FAIL

### R2. Must 필드는 모든 vendor

- **Default**: field_dictionary.yml의 Must 분류 필드는 모든 vendor baseline에 존재해야 함
- **Allowed**: vendor-specific 필드는 Nice
- **Forbidden**: 새 필드를 Must로 분류하면서 일부 vendor baseline 누락
- **Why**: Must는 호출자가 모든 응답에서 보장 받는 필드. 누락 시 호출자 시스템 파싱 실패 가능

### R3. Schema 버전 사용자 확인

- **Default**: sections.yml + field_dictionary.yml 버전 변경은 사용자 명시 확인 (rule 92 R5와 동일 정신)
- **Forbidden**: AI가 임의로 버전 번호 결정
- **Why**: 다른 작업자/세션에서 같은 버전 사용 가능 → 충돌

### R4. Baseline 갱신 절차

- **Default**: `update-vendor-baseline` skill 사용. 실장비 검증 후 baseline 갱신:
  1. probe_redfish.py로 실장비 응답 수집
  2. 정규화된 결과를 baseline_v1/{vendor}_baseline.json에 저장
  3. tests/evidence/<날짜>-<vendor>.md에 검증 환경 기록
  4. Round 검증 docs/reference/decision-log.md에 추가
- **Forbidden**: AI가 임의로 baseline 수정 (실측 없이)
- **Why**: baseline은 회귀 기준선. 실측 없는 수정은 회귀를 무력화

### R5. JSON envelope 13 필드 (`common/tasks/normalize/build_output.yml` 정본)

- **Default**: 출력 envelope은 정확히 13 필드 (작성 순서):
  ```
  target_type, collection_method, ip, hostname, vendor,
  status, sections, diagnosis, meta, correlation, errors, data,
  schema_version (inject 후)
  ```
- **Forbidden**: envelope 필드 추가/삭제 (호출자 호환성 깨짐). 정본은 `build_output.yml`이며, baseline + examples 모두 동일 13 필드 보장.
- **Why**: rule 31 callback URL 무결성 + 호출자 시스템 계약. 분석 카테고리(status/sections/data/errors/meta/diagnosis)는 핵심 6 분류이고, 추가 7 필드(target_type/collection_method/ip/hostname/vendor/correlation/schema_version)는 라우팅·식별·버전 추적 메타.

### R6. Build_*.yml 빌더 패턴 일관성

- **Default**: 새 builder 추가 시 기존 패턴 따름:
  - 입력: fragment 변수 (`_data_fragment` 등)
  - 출력: 누적 변수 (`_collected_data` 등) 또는 최종 envelope 필드
  - set_fact로만 변수 생성 (다른 task의 결과를 직접 참조 안 함)
- **Forbidden**: 빌더 안에서 외부 시스템 호출 (gather에서 이미 끝남)

### R7. envelope 정본 변경 시 `docs/contract/03-fields.md` 갱신 의무

- **Default**: 다음 정본 변경 시 `docs/contract/03-fields.md` 동기화 갱신 의무 (cycle 2026-05-06 M-G2 추가)
  - `common/tasks/normalize/build_output.yml` (envelope 13 필드 정본)
  - `schema/sections.yml` (섹션 정의)
  - `schema/field_dictionary.yml` (Must/Nice/Skip 분류)
  - `common/tasks/normalize/build_status.yml` (status 판정 규칙 — M-A3 정본)
- **Allowed**: 변경이 cosmetic (주석 / 들여쓰기) 시 `docs/contract/03-fields.md` 갱신 skip 가능. 단 commit 메시지 명시 ("`docs/contract/03-fields.md` 동기화 불필요 — cosmetic only")
- **Forbidden**: envelope 13 필드 / 섹션 목록 / field_dictionary 의 의미 변경 + `docs/contract/03-fields.md` 갱신 누락
- **Why**: 호출자 시스템이 `docs/contract/03-fields.md` 을 정본 reference 로 사용. 정본 코드 변경 시 `docs/contract/03-fields.md` stale → 호출자 파싱 오류 + 사용자 의심 (cycle 2026-05-06 M-A 사용자 질문 — "errors success 모순" 의심 발생)
- **재검토**: `docs/contract/03-fields.md` 자동 동기화 hook (`pre_commit_docs20_sync_check.py`) 도입 시 advisory → blocking 격상

### R8. status 판정 로직 변경 시 시나리오 매트릭스 동반 갱신

- **Default**: 다음 정본 변경 시 status 4 시나리오 매트릭스 (A/B/C/D) 동반 갱신 의무 (cycle 2026-05-06-post M-A 학습 형식화)
  - `common/tasks/normalize/build_status.yml` (판정 로직 정본)
  - `common/tasks/normalize/build_sections.yml` (섹션 status 입력)
  - `common/tasks/normalize/build_errors.yml` (errors[] 분리 영역)
- **시나리오 매트릭스 정본** (변경 시 동반 갱신 위치):
  - `common/tasks/normalize/build_status.yml` 본문 주석 (24~31 line, 4 시나리오 표)
  - `docs/contract/03-fields.md` (호출자 reference)
  - `docs/reference/decision-log.md` (의사결정 trace)
  - `tests/` mock fixture (시나리오 B 재현 — M-A3 commit `78611714` 회귀 13건)
- **Allowed**: 4 시나리오 결과가 변경되지 않는 cosmetic 변경 (주석 다듬기 / 들여쓰기) 시 매트릭스 갱신 skip 가능. 단 commit 메시지 명시 ("status 매트릭스 영향 없음 — cosmetic only")
- **Forbidden**:
  - 4 시나리오 매트릭스 의미 변경 (A/B/C/D enum 값 / overall status 결과) + `docs/reference/decision-log.md` + `docs/contract/03-fields.md` + 회귀 fixture 동반 갱신 누락
  - severity (warning / error) 도입 시 envelope shape 변경 영향 무시 (rule 22 R7 + rule 13 R5 + rule 96 R1-B)
  - status_rules.yml DEAD CODE 활성화 (build_status.yml 인라인 Jinja2 ↔ status_rules.yml 동기화 의무 발생) + 사용자 명시 승인 누락
- **Why**: status 판정은 envelope 호출자 계약의 핵심. M-A 학습 (cycle 2026-05-06) — 사용자 의심 "errors 있는데 success 모순" 발생 → 시나리오 B 가 의도된 동작임을 코드 주석 + `docs/reference/decision-log.md` + `docs/contract/03-fields.md` + mock fixture 4 곳에 명시한 후 사용자 신뢰 회복. 매트릭스 분산 갱신은 향후 동일 의심 재발 차단
- **검증 절차**: `verify-status-logic` skill 로 A/B/C/D 시나리오 매트릭스를 확인한다.
- **재검토**: status 로직 자동 동기화 hook (`pre_commit_status_logic_check.py`) 이 blocking 으로 격상될 때

## 금지 패턴

- 3종 중 일부만 갱신 — R1
- Must 필드 vendor 누락 — R2
- AI 임의 schema 버전 — R3
- 실측 없이 baseline 수정 — R4
- envelope 13 필드 변경 — R5
- 빌더에서 외부 호출 — R6
- envelope 정본 변경 + `docs/contract/03-fields.md` 갱신 누락 — R7
- status 판정 로직 변경 + 4 시나리오 매트릭스 갱신 누락 — R8

## 리뷰 포인트

- [ ] sections.yml + field_dictionary.yml + baseline 3종 동반 갱신
- [ ] 새 Must 필드가 모든 vendor에 존재
- [ ] schema 버전 사용자 승인
- [ ] baseline 갱신이 실측 기반인가 (evidence 첨부)
- [ ] envelope 13 필드 유지
- [ ] envelope 정본 변경 시 `docs/contract/03-fields.md` 동기화 (R7)
- [ ] status 로직 변경 시 4 시나리오 매트릭스 동반 갱신 (R8)

## 테스트 포인트

- `python scripts/ai/hooks/output_schema_drift_check.py` (exit 0)
- Jenkins Stage 3 (Validate Schema) 통과
- 로컬 pytest 회귀 통과 (`pytest tests/e2e tests/regression`)
- 영향 vendor baseline 회귀

## 관련

- rule: `20-output-json-callback`, `21-output-baseline-fixtures`, `22-fragment-philosophy`
- skill: `update-output-schema-evidence`, `update-vendor-baseline`, `plan-schema-change`, `verify-json-output`
- agent: `schema-reviewer`, `schema-migration-worker`, `refactor-worker`, `qa-regression-worker`
- 정본: `docs/contract/02-output-envelope.md`, `docs/develop/05-field-mapping.md`
