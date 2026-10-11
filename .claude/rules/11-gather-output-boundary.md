---
paths:
  - "os-gather/**"
  - "esxi-gather/**"
  - "redfish-gather/**"
  - "common/tasks/normalize/**"
---
# Gather ↔ Output 경계

## 적용 대상
- `os-gather/**`, `esxi-gather/**`, `redfish-gather/**`
- `common/tasks/normalize/**`

## 목표 규칙

### R1. gather → builder 직접 수정 금지

- **Default**: gather는 자기 fragment 변수만 set_fact. `_collected_data`, `_supported_sections`, `_collected_errors` 같은 누적 변수는 `merge_fragment.yml`이 관리 — gather에서 직접 수정 금지
- **Forbidden**: gather에서 `set_fact: _collected_data: ...` 직접 수정
- **Why**: builder가 일관 패턴으로 누적 → gather가 침범하면 누적 결과 오염
- **재검토**: builder 패턴 추상화 강화 시

### R2. fragment 변수 prefix `_`

- **Default**: 모든 fragment 변수는 `_` prefix (Ansible 외부 노출 안 함)
- **Forbidden**: `data_fragment` 같은 prefix 없는 변수 (Ansible inventory hostvars로 노출되어 다른 host에 영향 가능)
- **Why**: Ansible 변수 스코프 안전

### R3. include_tasks vs import_tasks

- **Default**: gather entry는 `include_tasks` (런타임 평가) 사용. precheck에서 vendor가 결정된 후 동적 include
- **Allowed**: 모든 host에 항상 적용되는 init은 `import_tasks` 가능
- **Forbidden**: vendor-specific tasks를 `import_tasks`로 강제 로드 (다른 vendor에서 실패)

### R4. merge_fragment.yml 호출 보장

- **Default**: 각 gather 후 반드시 `include_tasks: "{{ playbook_dir }}/common/tasks/normalize/merge_fragment.yml"` 호출
- **Forbidden**: merge_fragment.yml 호출 없이 다음 단계 진행
- **Why**: 호출 누락 시 fragment가 누적 변수에 합쳐지지 않음 → 출력에서 해당 섹션 누락

## 금지 패턴

- gather에서 누적 변수 직접 수정 — R1
- prefix 없는 fragment 변수 — R2
- 동적 vendor를 import_tasks로 강제 — R3
- merge_fragment.yml 누락 — R4

## 리뷰 포인트

- [ ] 누적 변수에 gather가 손대지 않는가
- [ ] fragment 변수 모두 `_` prefix
- [ ] merge_fragment.yml 호출이 각 gather 후 존재
- [ ] include_tasks vs import_tasks 적절성

## 관련

- rule: `10-gather-core`, `22-fragment-philosophy`
- skill: `validate-fragment-philosophy`
- agent: `fragment-engineer`
- 정본: `docs/develop/02-normalize-flow.md`
