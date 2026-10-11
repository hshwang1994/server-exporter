---
paths:
  - "adapters/**"
  - "vault/**"
  - "common/vars/vendor_aliases.yml"
  - ".claude/ai-context/vendors/**"
  - ".claude/policy/vendor-boundary-map.yaml"
---
# Vendor / Adapter 정책

## 규칙 표기 구조

본 rule의 각 항목은 **Default / Allowed / Forbidden + Why + 재검토 조건** 3단 구조.

## 적용 대상

- 저장소 전체 (`**`) — 벤더 추가/변경 시
- `adapters/`, `vault/<loc>/redfish/`
- `common/vars/vendor_aliases.yml`

## 목표 규칙

### R1. Vendor 정규화 정본

- **Default**: vendor 정규화 정본은 `common/vars/vendor_aliases.yml`. 모든 alias 매핑은 이 파일에 등록
- **Allowed**: `_FALLBACK_VENDOR_MAP` (redfish_gather.py)는 vendor_aliases.yml 로드 실패 시 fallback. 두 위치 동기화 의무 (rule 22 R5와 같은 정신)
- **Allowed (출력 표시값 — 2026-06-04 ADR)**: 위 `normalized` 는 **내부 canonical** (adapter/vault/OEM/account 라우팅 키). 호출자에게 노출되는 envelope `vendor` 값은 `vendor_aliases.yml` 의 `vendor_output_display`(예: `hpe→hp`) + `adapter_output_display`(예: `redfish_hpe_csus_3200→hpCsus`) 로 매핑한 **표시값**. 표시값과 canonical 분리 — 표시값 변경이 라우팅에 영향 없음. 정본: `docs/ai/decisions/ADR-2026-06-04-vendor-output-display.md`
- **Forbidden**: vendor 분기 코드에서 alias 직접 비교 (`if manufacturer == "Dell Inc."`)
- **Why**: alias 변형이 펌웨어/모델별로 다양 (mark dot 누락 등). 정규화 정본 1곳에서 관리해야 신뢰
- **재검토**: BMC 표준 manufacturer 표기 합의 시

### R2. 새 vendor 추가 9단계 (+ 단계 10 — lab 부재 시)

- **Default**: 새 vendor 추가는 정확히 9단계
  1. `common/vars/vendor_aliases.yml` 매핑 추가
  2. `adapters/{redfish,os,esxi}/{vendor}_*.yml` adapter 생성 (priority/specificity/match/capabilities/collect/normalize)
  3. (선택) OEM 확장이 필요하면 라이브러리 `_extract_oem_*` 에 vendor 분기 추가
  4. `vault/<loc>/redfish/<vendor>.yml` 생성 (ansible-vault encrypt)
  5. `schema/baseline_v1/{vendor}_baseline.json` 추가 (실장비 검증 후)
  6. `.claude/ai-context/vendors/{vendor}.md` 추가
  7. `.claude/policy/vendor-boundary-map.yaml` 갱신
  8. `docs/reference/live-validation.md` Round 갱신
  9. `docs/reference/decision-log.md` 추가
- **단계 10 (lab 부재 vendor 시 의무 — cycle 2026-05-01 / 2026-05-06 학습 형식화)**:
  - lab 부재 시 (사용자 사이트 외 lab 환경에 vendor 장비 없음) 다음 trigger 발생 → NEXT_ACTIONS.md 자동 등록 의무 (rule 96 R1-C 와 연동)
    - `schema/baseline_v1/{vendor}_baseline.json` SKIP (단계 5)
    - `docs/reference/live-validation.md` Round = "lab 부재 — web sources" (단계 8)
    - `vault/<loc>/redfish/<vendor>.yml` SKIP 사용자 명시 승인 (단계 4)
  - NEXT_ACTIONS.md 등재 항목:
    1. 사이트 fixture 캡처 (capture-site-fixture skill)
    2. baseline JSON 추가 (실장비 검증 후 — rule 13 R4)
    3. lab 도입 후 별도 cycle (`{vendor} lab 검증` round)
    4. vault 결정 (사용자 명시 승인 시점)
- **Allowed**: site.yml 수정 불필요 (adapter_loader가 동적 감지). lab 부재 vendor 는 단계 10 등재로 단계 4 / 5 / 8 SKIP 승인
- **Forbidden**:
  - 9단계 일부 skip (단계 10 등재 없는 SKIP)
  - site.yml에 vendor 분기 추가
  - vendor_aliases.yml 누락 후 adapter만 추가
  - adapter 없이 OEM tasks만 추가
  - lab 부재 vendor 추가 + NEXT_ACTIONS 등재 누락 (단계 10 정본 위반)
- **Why**: cycle 2026-05-01 4 신규 vendor (Huawei/Inspur/Fujitsu/Quanta) + cycle 2026-05-06 Superdome Flex — 모두 lab 부재 → web sources 로 추가 (rule 96 R1-A). 본 단계 10 으로 lab 부재 vendor 의 후속 작업 자동 추적
- **재검토**: vendor 추가 자동화 도구 (cycle-orchestrator + add-vendor-no-lab skill) 정착 시 단계 10 자동 등재 hook 검토

### R3. Adapter 점수 일관성

- **Default**: adapter 점수 계산
  ```
  score = priority × 1000 + specificity × 10 + match_score
  ```
  같은 vendor 내:
  - generic fallback = 0~10 (예: `lenovo_bmc.yml` priority=10)
  - 기본 vendor (모델 무관) = 50
  - 세대별 (예: `dell_idrac9.yml`) = 80~100
  - 모델별 = 100 + match.model_patterns의 specificity
- **Allowed**: 같은 vendor 내 priority 동률은 specificity / match_score로 tie-break
- **Forbidden**:
  - priority 역전 (세대별 < generic)
  - 같은 vendor의 다른 generation이 동일 priority + 동일 specificity (선택 결과 불확정)
- **Why**: adapter_loader가 점수순 정렬 후 최고 점수 선택. 일관성 깨지면 어떤 adapter가 선택될지 예측 불가
- **재검토**: 점수 계산식 자체 변경 시

### R4. Branch 정책 (단순 운영)

- **Default**: branch 패턴
  | 브랜치 패턴 | 용도 |
  |---|---|
  | `main` | 운영 기준선 |
  | `feature/<name>` | 기능 추가 |
  | `fix/<name>` | 버그 수정 |
  | `vendor/<name>` | 새 벤더 추가 (예: `vendor/huawei`) |
  | `docs/<name>` | 문서 작업 |
  | `harness/<name>` | 하네스 변경 |
- **Allowed**: 사용자 명시 승인 후 main 직접 push
- **Forbidden**:
  - main 직접 commit (사용자 명시 승인 외)
  - force push (rule 93 R1)
  - `git push --all`
- **Why**: 단일 main 보호 + 변경 추적 가능
- **재검토**: develop / release branch 운영 모델 도입 시

### R5. Vendor 경계 (rule 12 연동)

- **Default**: 본 rule은 정책 수준. 코드 검증은 rule 12 (adapter-vendor-boundary)
  - common/, 3-channel 코드에 vendor 이름 하드코딩 금지
  - adapter YAML / OEM tasks 안에서만 vendor 분기
- **Allowed**: rule 12 R1 Allowed 영역 (Redfish API spec OEM namespace 등)
- **Forbidden**: rule 12 R1 위반
- **Why**: vendor 추가 시 모든 코드 위치 수정 부담을 0으로 만드는 게 본 정책의 핵심
- **재검토**: rule 12 R1 자체 변경 시

### R6. Generic fallback 의무

- **Default**: 모든 채널에 generic fallback adapter 1개 (priority=0~10)
- **Allowed**: vendor별 generic fallback (예: `lenovo_bmc.yml` priority=10) 추가
- **Forbidden**: 채널에 fallback 부재 (매치 안 되는 vendor에 대한 graceful degradation 불가)
- **Why**: 새 vendor / 알려지지 않은 펌웨어에 대해 최소한의 수집 시도 + 명확한 status="failed"
- **재검토**: 모든 vendor가 명시 adapter 보유 정책 도입 시

## 금지 패턴

- vendor_aliases 누락 후 adapter만 추가 — R2
- adapter 없이 OEM tasks만 추가 — R2
- main 직접 push (force) — R4
- common/ + 3-channel에 vendor 하드코딩 — R5 (rule 12 R1)
- 채널에 generic fallback 부재 — R6

## 리뷰 포인트

- [ ] 새 vendor 추가 시 9단계 모두
- [ ] adapter 점수 일관성 (priority 역전 없음)
- [ ] branch 패턴 준수
- [ ] generic fallback 존재
- [ ] vendor_aliases.yml ↔ _FALLBACK_VENDOR_MAP 동기화

## 테스트 포인트

- `python scripts/ai/verify_vendor_boundary.py` (rule 12 검증)
- `python scripts/ai/verify_harness_consistency.py` (alias 동기화)
- 새 vendor: `score-adapter-match` skill로 점수 디버깅

## 관련

- rule: `12-adapter-vendor-boundary`, `93-branch-merge-gate` (cycle-011: rule 60 보안 정책 해제됨)
- skill: `add-new-vendor`, `vendor-change-impact`, `score-adapter-match`
- agent: `vendor-onboarding-worker`, `vendor-boundary-guardian`
- policy: `.claude/policy/vendor-boundary-map.yaml`
- 정본: `docs/develop/04-add-vendor.md`, `docs/reference/live-validation.md`
