# Fragment 철학 (server-exporter 핵심 규칙)

> server-exporter의 모든 gather 작업의 가장 근본 원칙. 위반 시 회귀 / 누락 / 오염이 동시에 발생.

## 규칙 표기 구조

본 rule의 각 항목은 **Default / Allowed / Forbidden + Why + 재검토 조건** 3단 구조.

## 적용 대상

- `os-gather/**`, `esxi-gather/**`, `redfish-gather/**`
- `common/tasks/normalize/**`
- `common/library/**`, `redfish-gather/library/**`

## 현재 관찰된 현실

- 3-channel 통합 수집 시스템 (os/esxi/redfish)
- 각 gather가 자기 fragment만 만들고, common builder가 누적 병합
- 새 섹션/채널 추가 시 build_output.yml 전체 수정 필요 없음 — site.yml에 include_tasks 한 줄만
- Fragment 변수 침범으로 인한 사고 사전 차단

## 목표 규칙

### R1. 자기 fragment만 만든다 (가장 중요)

- **Default**: 각 gather는 다음 다섯 fragment 변수만 set_fact:
  - `_data_fragment` — 섹션별 raw 데이터 dict (예: `{ cpu: {...}, memory: {...} }`)
  - `_sections_supported_fragment` — 이 gather가 지원하는 섹션 list (예: `['cpu', 'memory']`)
  - `_sections_collected_fragment` — 이 gather가 수집 성공한 섹션 list
  - `_sections_failed_fragment` — 이 gather가 수집 실패한 섹션 list
  - `_errors_fragment` — 자기 수집 중 발생한 errors list
- **Forbidden**: 다른 gather의 fragment 변수를 자기 영역 외 값으로 set_fact (예: cpu gather가 memory section을 fragment list에 추가)
- **Forbidden**: 누적 변수 (`_collected_data`, `_supported_sections`, `_collected_sections`, `_failed_sections`, `_collected_errors`)를 직접 수정 (이건 merge_fragment.yml만 관리)
- **Why**: 다른 gather의 fragment를 수정하면 누가 어떤 데이터를 만들었는지 추적 불가 + 누락/덮어쓰기 발생. 회귀 사고 1순위 원인.
- **재검토**: Fragment 추상화가 더 강한 메커니즘으로 대체될 때 (예: per-channel namespace 강제)

#### Bad vs Good

```yaml
# [NG] — 누적 변수 직접 수정 (금지)
- name: 누적 변수 직접 수정
  set_fact:
    _collected_data: "{{ _collected_data | combine({'memory': ...}) }}"  # [NG] merge_fragment.yml 영역

# [NG] — 다른 gather의 섹션을 자기 fragment에 포함 (금지)
- name: cpu gather 안에서 memory 섹션 추가
  set_fact:
    _sections_collected_fragment: ['cpu', 'memory']  # [NG] memory는 다른 gather 영역

# [OK] — 자신의 fragment만
- name: CPU 섹션 수집
  set_fact:
    _data_fragment:
      cpu: { model: "...", cores: ... }
    _sections_supported_fragment: ['cpu']
    _sections_collected_fragment: ['cpu']
    _sections_failed_fragment: []
```

### R2. 새 섹션 추가는 정확히 7단계

- **Default** (rule 22 (fragment-philosophy) "Fragment 추가 체크리스트" + 본 rule):
  1. `gather_<section>.yml` 또는 `collect_<section>.yml` 작성 (raw 수집)
  2. Fragment 변수 set_fact (5 공통 변수: `_data_fragment`, `_sections_supported_fragment`, `_sections_collected_fragment`, `_sections_failed_fragment`, `_errors_fragment`)
  3. `normalize_<section>.yml` 또는 `common/tasks/normalize/build_<section>.yml` 작성
  4. `merge_fragment.yml` 호출 확인 (각 gather 후)
  5. `common/vars/supported_sections.yml` 업데이트
  6. `schema/sections.yml` + `schema/fields/*.yml` 추가
  7. Baseline JSON 예시 추가 + 문서 갱신
- **Forbidden**: 위 7단계 중 일부 skip하고 PR 제출
- **Why**: 일부 단계 누락 시 Jenkins Stage 3 (Validate Schema) 또는 로컬 pytest 회귀(tests/e2e) FAIL

### R3. merge_fragment.yml 호출 보장

- **Default**: 각 gather 끝에 반드시 호출
  ```yaml
  - include_tasks: "{{ playbook_dir }}/common/tasks/normalize/merge_fragment.yml"
  ```
- **Forbidden**: 호출 누락 (fragment가 누적 변수에 합쳐지지 않음 → 출력에서 섹션 누락)
- **Why**: merge_fragment가 fragment → 누적 변수 병합 엔진. 호출 안 하면 fragment가 다음 gather 시작 시 덮어쓰여 사라짐

### R4. Vendor-specific 로직은 adapter YAML

- **Default**: vendor별 분기는 `adapters/{channel}/{vendor}_*.yml` 또는 Redfish 라이브러리의 OEM 추출 분기. gather 코드는 vendor-agnostic
- **Forbidden**: gather 코드에 `if vendor == "Dell"` 분기
- **Why**: rule 12 R1과 동일. fragment 철학의 vendor 차원

### R5. Common builder 침범 금지

- **Default**: `common/tasks/normalize/build_*.yml` (5종 빌더)는 fragment 변수 → 누적 변수 → envelope 필드 변환 전담. gather에서 builder 결과를 직접 수정 안 함
- **Forbidden**: gather에서 envelope 필드 (`status`, `data`, `meta` 등) 직접 set_fact
- **Why**: 빌더가 일관 패턴으로 조립. gather가 침범하면 envelope 일관성 깨짐

### R6. 새 gather 추가 전 기존 패턴 조사

- **Default**: 새 gather (예: 새 섹션 또는 새 채널) 추가 전 기존 gather 코드 조사 의무. rule 22 (fragment-philosophy) "새 gather 템플릿" + 가장 비슷한 기존 gather를 reference로
- **Forbidden**: 백지 상태에서 새 gather 작성 (fragment 변수 명명 / merge 호출 / vendor 분기 패턴 일탈 위험)

### R7. fragment 변수 명명 규칙

- **Default**: 모든 gather가 동일한 5 변수 이름 사용 (변수 자체는 공통, **값**으로 자기 섹션을 채운다):
  - `_data_fragment` — 섹션별 raw 데이터 dict
  - `_sections_supported_fragment` — 지원 섹션 list
  - `_sections_collected_fragment` — 수집 성공 섹션 list
  - `_sections_failed_fragment` — 수집 실패 섹션 list
  - `_errors_fragment` — error 발생 list
  - 모두 `_` prefix (외부 노출 방지, rule 11 R2)
- **Forbidden**: 변수 이름에 섹션명 prefix/suffix 추가 (예: `_sections_cpu_collected_fragment` 같은 변수 자체 분기)
- **Why**: merge_fragment.yml은 5 공통 변수 이름을 가정해 union 누적. 변수 이름이 섹션별로 갈리면 merge 자체 실패

### R8. Fragment 변수 타입

- **Default**:
  - `_data_fragment`: dict (key=section name, value=raw data)
  - `_sections_supported_fragment`: list of strings (이 gather가 지원하는 섹션 이름)
  - `_sections_collected_fragment`: list of strings (수집 성공한 섹션 이름)
  - `_sections_failed_fragment`: list of strings (수집 실패한 섹션 이름)
  - `_errors_fragment`: list of dicts (error records)
- **Forbidden**: 타입 일탈 (예: `_data_fragment`를 list로)
- **Why**: merge_fragment.yml이 타입 가정으로 병합 — 일탈 시 병합 실패

### R9. Self-test (validate-fragment-philosophy skill)

- **Default**: 새 gather 추가 후 `validate-fragment-philosophy` skill 실행
- **검사 항목**:
  - 자기 fragment만 만드는가
  - 다른 gather fragment 침범 없는가
  - merge_fragment.yml 호출 있는가
  - fragment 변수 명명 규칙 준수
  - `_` prefix 적용

## 금지 패턴

- 다른 gather의 fragment를 set_fact로 수정 — R1
- 누적 변수 (`_collected_data` 등) 직접 수정 — R1
- 7단계 일부 skip — R2
- merge_fragment.yml 호출 누락 — R3
- gather 코드에 vendor 하드코딩 — R4
- gather에서 envelope 필드 직접 set_fact — R5
- 백지에서 새 gather 작성 (기존 패턴 조사 없이) — R6
- fragment 변수 명명 일탈 — R7
- fragment 변수 타입 일탈 — R8

## 리뷰 포인트

- [ ] 각 gather가 자기 fragment만 만드는가 (R1)
- [ ] 새 섹션 추가가 7단계 모두 거쳤는가 (R2)
- [ ] merge_fragment.yml 호출이 각 gather 후 존재 (R3)
- [ ] gather 코드에 vendor 하드코딩 없음 (R4)
- [ ] gather에서 envelope 필드 set_fact 없음 (R5)
- [ ] 새 gather 작성 시 기존 패턴 reference 명시 (R6)
- [ ] 변수 명명 / 타입 규칙 (R7-R8)
- [ ] validate-fragment-philosophy skill 통과 (R9)

## 테스트 포인트

- `validate-fragment-philosophy` skill (의심 패턴 자동 스캔)
- `ansible-playbook --syntax-check` 통과
- Fragment 침범 / 누락 회귀: 변경된 채널 + 영향 vendor baseline 전수
- `verify_harness_consistency.py` 통과

## 관련

- rule: `10-gather-core`, `11-gather-output-boundary`, `12-adapter-vendor-boundary`, `13-output-schema-fields`
- skill: `validate-fragment-philosophy`, `task-impact-preview`, `add-new-vendor`
- agent: `fragment-engineer`, `refactor-worker`, `adapter-author`
- 정본: `.claude/rules/22-fragment-philosophy.md` + `docs/develop/02-normalize-flow.md`
- 정본: `docs/develop/01-gather-structure.md`, `docs/develop/02-normalize-flow.md`

## 승인 기록

| 일시 | 승인자 | 대상 | 비고 |
|---|---|---|---|
| 2026-04-27 | hshwang1994 | 본 rule 신설 (server-exporter 풀스펙 포팅) | 가장 핵심 규칙으로 rule 22 슬롯 배정 |
