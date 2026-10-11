---
name: add-new-vendor
description: "server-exporter에 새 벤더(예: Huawei iBMC, Inspur, Ampere)를 3단계로 추가하는 절차 안내. vendor_aliases.yml + adapters/{channel}/{vendor}_*.yml + (선택) OEM tasks + vault + baseline + ai-context + docs 동시 갱신. 사용자가 \"Huawei vendor 추가\", \"새 벤더 추가\", \"Huawei 지원하자\" 등 요청 시 자동 호출. - 새 vendor가 호출자 시스템에서 요청됨 / 펌웨어 프로파일링 후 정식 지원 / 기존 generic fallback 한계 시"
---

# add-new-vendor

## 목적

server-exporter에 새 벤더를 도입하는 일관 절차. rule 50 R2의 9단계 가이드 + rule 12 R3의 3단계 코드 변경 + rule 96 R1 origin 주석.

## 입력

- 새 vendor 이름 (예: "Huawei")
- vendor의 BMC 종류 (예: "iBMC")
- 검증 가능한 실장비 (Round 검증 가능)
- 펌웨어 시작 버전

## 출력 / 결과 (9 변경 파일)

```markdown
## 새 vendor 추가 — Huawei (iBMC)

### 1. vendor_aliases.yml — Manufacturer 정규화
common/vars/vendor_aliases.yml에 추가:
  Huawei: huawei
  Huawei Technologies: huawei
  iBMC: huawei

### 2. Adapter YAML — adapters/redfish/huawei_ibmc.yml (신규)
priority: 50
match:
  manufacturer: ["Huawei", "Huawei Technologies"]
  model_patterns: ["FusionServer*", "TaiShan*"]
  firmware_patterns: ["3.x", "5.x"]
specificity: 20
capabilities: [...]
collect:
  strategy: standard+oem
normalize:
  ...
metadata:
  vendor: huawei
  tested_against: ["3.10.x"]
  oem_path: /redfish/v1/...
  origin_check: 2026-04-27 (hshwang)

### 3. OEM 확장 (선택) — 라이브러리 `_extract_oem_*` 에 vendor 분기

### 4. Vault — vault/<loc>/redfish/huawei.yml (encrypt)
vault_redfish_username: ...
vault_redfish_password: ...

### 5. Baseline — schema/baseline_v1/<vendor>_baseline.json
실장비 검증 (probe-redfish-vendor skill) 후 갱신

### 6. ai-context — .claude/ai-context/vendors/huawei.md
벤더 식별 / OEM 특이사항 / 검증 이력

### 7. policy — .claude/policy/vendor-boundary-map.yaml
huawei 섹션 추가 (adapter list, oem_tasks, vault, aliases)

### 8. 운영 문서 — docs/reference/live-validation.md
Round X 추가 (Huawei iBMC 3.x 검증)

### 9. 의사결정 — docs/reference/decision-log.md
"Huawei vendor 추가 (2026-04-27)"
```

## 절차

1. **PO 단계** — 사용자 결정 (rule 50 R2): 우선순위 / 일정 / 실장비 확보
2. **probe** — `probe-redfish-vendor` skill로 펌웨어 프로파일링 (deep_probe_redfish.py)
3. **9 파일 변경** (위 출력 list)
4. **dry-run** — `ansible-playbook --syntax-check redfish-gather/site.yml`
5. **adapter score 디버깅** — `score-adapter-match` skill로 새 vendor adapter가 의도대로 선택되는지
6. **실장비 검증** — Round 검증 (rule 40 R2)
7. **baseline 갱신** — `update-vendor-baseline` skill
8. **필드 분류 검증** (cycle 2026-05-11 field-channel-refinement 신설):
   ```
   python scripts/ai/measure_field_usage_matrix.py --update-md
   ```
   - 새 vendor baseline 추가 후 `docs/ai/catalogs/FIELD_USAGE_MATRIX.md` 자동 갱신
   - 분류 1 후보 (모든 baseline null) 신규 발견 시 channel 정밀화 별도 cycle 검토
   - DRIFT-B 검출 시 (미선언 channel 에서 present) field_dictionary `channel:` 추가
   - 분류 3? 의심 발견 시 즉시 코드 fix (rule 95 R3 회귀 의무) 또는 NEXT_ACTIONS 등재
9. **PR 생성** — squash 머지 (rule 93 R5)
10. **REQUIREMENTS.md 갱신** — 검증 완료된 펌웨어 목록 추가

## site.yml 수정 불필요

`adapter_loader`가 동적 감지 (rule 12 R3). 새 adapter YAML 파일만 추가하면 됨.

## server-exporter 도메인 적용

- 영향 채널: 주로 redfish (os / esxi는 vendor-agnostic)
- 영향 schema: baseline_v1에 vendor JSON 추가
- 영향 vault: vault/<loc>/redfish/<vendor>.yml 신규
- 영향 정본: REQUIREMENTS.md / docs/reference/live-validation.md / docs/reference/decision-log.md

## 실패 / 오탐 처리

- 실장비 부재 → Round 검증 불가 → 일단 OEM 없이 standard_only 전략으로 부분 지원 + REQUIREMENTS.md에 "초기 지원" 표기
- 펌웨어 다양성 → 한 vendor에 여러 generation adapter (priority 차등)
- vendor가 IPMI만 지원 (Redfish 미지원) → server-exporter 현재 미지원 (향후 IPMI fallback 검토)

## 적용 rule / 관련

- **rule 12** (adapter-vendor-boundary) R3 (3단계 절차)
- **rule 50** (vendor-adapter-policy) R2 (9 파일 list)
- rule 96 R1 (origin 주석)
- (cycle-011: rule 60 해제 — vault encrypt는 cycle-012에서 운영 권장으로 채택)
- rule 40 (baseline 회귀)
- skill: `probe-redfish-vendor`, `update-vendor-baseline`, `score-adapter-match`, `vendor-change-impact`, `measure_field_usage_matrix.py` (단계 8 — 필드 분류 검증)
- agent: `vendor-onboarding-worker` (이 skill의 메인 실행자), `adapter-author`
- 정본: `docs/develop/04-add-vendor.md`, `docs/reference/live-validation.md`
- reference: 외부 API 공식 문서 (BMC 매핑)
