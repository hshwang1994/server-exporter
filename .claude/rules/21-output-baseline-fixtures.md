---
paths:
  - "tests/fixtures/**"
  - "schema/baseline_v1/**"
  - "tests/evidence/**"
---
# Baseline / Fixtures 보호

## 적용 대상
- `tests/fixtures/**`
- `schema/baseline_v1/**` (정본 — vendor별 회귀 기준선)
- `tests/evidence/**`

## 목표 규칙

### R1. Baseline 갱신은 실측 기반

- **Default**: baseline은 실장비 검증 결과만. AI 임의 수정 금지 (rule 13 R4와 동일)
- **Forbidden**: AI가 baseline JSON을 직접 편집 (실측 evidence 없이)
- **Why**: baseline은 회귀 기준선. 임의 수정은 회귀 의미 상실

### R2. Fixture 출처 기록

- **Default**: 새 fixture 추가 시 tests/evidence/<날짜>-<vendor>-<펌웨어>.md에 출처 기록 (실 vendor / 펌웨어 / 수집 명령)
- **Forbidden**: 출처 불명한 fixture 추가
- **Why**: fixture는 mock 회귀 입력. 출처 모르면 향후 외부 계약 변경 시 추적 불가

### R3. Fixture 변경 시 baseline 회귀

- **Default**: fixture 변경은 영향 vendor baseline 전수 회귀 후
- **Forbidden**: fixture만 변경하고 baseline 회귀 skip

### R4. Evidence 보존

- **Default**: tests/evidence/ 안의 Round 검증 결과는 archive 대상. 1회성 보고서가 아니라 향후 vendor/펌웨어 변경 시 비교 자산
- **Forbidden**: Round 검증 결과 삭제 (rule 70 보존 판정)

## 금지 패턴

- AI 임의 baseline 편집 — R1
- 출처 불명 fixture — R2
- fixture 변경 + baseline 회귀 skip — R3
- evidence 삭제 — R4

## 리뷰 포인트

- [ ] baseline 변경이 evidence 첨부됐는가
- [ ] fixture 출처 명시
- [ ] baseline 회귀 통과
- [ ] evidence 보존

## 관련

- rule: `13-output-schema-fields`, `40-qa-pytest-baseline`, `70-docs-and-evidence-policy`
- skill: `update-vendor-baseline`, `probe-redfish-vendor`, `prepare-regression-check`
- agent: `qa-regression-worker`
- 정본: `docs/reference/live-validation.md`
