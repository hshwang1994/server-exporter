---
name: add-vendor-no-lab
description: lab 부재 vendor 추가 (web sources 의무). cycle 2026-05-06 학습 — 4 신규 vendor (Huawei/Inspur/Fujitsu/Quanta) + Superdome Flex 의 lab 부재 web sources 패턴 라이브러리화. 사용자가 "Huawei iBMC 추가", "lab 없는 vendor 어떻게?", "vendor 추가" 등 요청 시 + lab 부재 명시 시. - rule 50 R2 9단계 + rule 96 R1-A web sources 의무 + vault SKIP 사용자 명시 승인
---

# add-vendor-no-lab

## 목적

lab 부재 vendor 추가 자동화 — rule 50 R2 9단계 + rule 96 R1-A (web sources 의무). cycle 2026-05-01 / 2026-05-06 학습.

server-exporter lab 은 일부 vendor / 펌웨어만 보유 (Dell / HPE / Lenovo / Supermicro / Cisco). 신규 vendor (Huawei / Inspur / Fujitsu / Quanta / Superdome Flex 등) 는 lab 없이 web sources 로 추가.

## 호출 시점

- 사용자 요청: "Huawei vendor 추가", "Inspur 추가", "Superdome Flex 분류"
- lab 부재 명시 (docs/ai/catalogs/LAB_INVENTORY.md 의 부재 영역)
- 호출자 신규 운영 vendor

## 입력

- vendor 명 (예: huawei / inspur / fujitsu / quanta / hpe_superdome_flex)
- 분류 (a) 별도 vendor / (b) 기존 vendor 의 sub-line
- 사용자 명시 승인 (vault SKIP 또는 vault 생성)

## 9단계 절차 (rule 50 R2 + R1-A 보강)

### 1. vendor_aliases.yml 매핑 추가

```yaml
# common/vars/vendor_aliases.yml
huawei:
  - "Huawei"
  - "Huawei Technologies"
```

### 2. adapter YAML 생성 (`adapters/redfish/{vendor}_*.yml`)

코드가 읽는 필드는 `adapter_id` · `priority` · `match` · `capabilities.sections_supported`(+ redfish `vendor_notes.manager_layout`)다 (rule 12 R4, 2026-10-10 정정).
`collect` · `normalize` · `credentials` · `graceful_degradation` 절은 기록용(코드가 읽지 않음) — 기존 adapter 와 모양을 맞춰 적는다:

```yaml
# adapters/redfish/huawei_ibmc.yml
# source: https://support.huawei.com/.../iBMC_Redfish_API_v1.30.pdf (확인 YYYY-MM-DD)
# source: https://redfish.dmtf.org/schemas/v1/...
# lab: 부재 — 사용자 결정 시 lab 도입 cycle 별도
priority: 70
specificity: 5
match:
  manufacturer: ["Huawei", "Huawei Technologies"]
capabilities:
  storage: standard
  power: standard
collect:
  strategy: standard_only
normalize:
  fragments_path: ...
```

→ **rule 96 R1-A 의무**: web sources 4종 중 1개 이상 origin 주석 (vendor docs / DMTF spec / GitHub issue / 사용자 사이트 실측). lab 부재 시 web sources 0건 금지.

### 3. (선택) OEM 확장 — 라이브러리 `_extract_oem_*`

OEM 분기 필요한 경우만. 없으면 standard_only.

### 4. vault/<loc>/redfish/<vendor>.yml 생성 (또는 SKIP — 사용자 명시 승인)

```bash
ansible-vault create vault/<loc>/redfish/huawei.yml
# accounts list 입력 (rotate-vault skill / `docs/operate/05-vault.md` 참조)
```

→ **사용자 명시 승인**: lab 부재 vendor 의 vault 는 사용자 결정. 본 cycle 2026-05-01 시점 4 vendor (Huawei/Inspur/Fujitsu/Quanta) 는 vault SKIP (사용자 명시 승인 — placeholder 만 추가).

### 5. baseline JSON (`schema/baseline_v1/{vendor}_baseline.json`)

- lab 도입 후 추가 (실장비 검증 후 — rule 13 R4)
- lab 부재 cycle 에서는 baseline SKIP (NEXT_ACTIONS.md 등재)

### 6. ai-context (`.claude/ai-context/vendors/{vendor}.md`)

vendor 컨텍스트 자동 로드 (작업 파일이 `adapters/redfish/{vendor}_*.yml` 일 때):

```markdown
# ai-context/vendors/huawei

## BMC: iBMC
## 펌웨어 지원: ...
## OEM namespace: Oem.Huawei
## 알려진 사고: ...
## sources (rule 96 R1-A):
- vendor docs: ...
- DMTF: ...
```

### 7. policy/vendor-boundary-map.yaml 갱신

`.claude/policy/vendor-boundary-map.yaml` 에 vendor 추가:

```yaml
vendors:
  - dell
  - hpe
  - lenovo
  - supermicro
  - cisco
  - huawei
  - inspur
  - fujitsu
  - quanta
```

### 8. docs/reference/live-validation.md 갱신

```markdown
## Round N (YYYY-MM-DD) — Huawei iBMC 추가
- 분류: 별도 vendor (lab 부재 web sources)
- adapter: huawei_ibmc.yml priority=70
- vault: SKIP (사용자 명시 승인)
- 사이트 실측: 보류 (lab 도입 후 Round N+1)
- web sources: huawei.com / DMTF Power.v1_8_0
```

### 9. docs/reference/decision-log.md 추가

```markdown
## YYYY-MM-DD — Huawei vendor 추가 (lab 부재 web sources)
- 분류 (a) vs (b): 별도 vendor (a)
- vault SKIP: 사용자 명시 승인 (cycle YYYY-MM-DD)
- web sources: ...
- NEXT_ACTIONS: lab 도입 후 baseline 회귀
```

## 회귀 검증 (lab 부재 한계 보완)

lab 없으므로 다음으로 회귀 대체:

| 검증 | 명령 |
|---|---|
| Adapter YAML 파싱 | `ansible-playbook --syntax-check redfish-gather/site.yml` |
| Adapter 점수 | `score-adapter-match` skill (mock manufacturer) |
| Vendor 경계 | `python scripts/ai/verify_vendor_boundary.py` |
| Mock fixture | `tests/fixtures/redfish/{vendor}_*.json` (web sources 응답 시뮬) |
| Harness 일관성 | `python scripts/ai/verify_harness_consistency.py` |

→ pytest 회귀 N건 추가 (mock fixture 기반 시나리오 — vendor adapter 매칭 / score / capabilities / OEM 분기).

## 사용자 결정 trigger (Phase 2 의무)

다음 발생 시 사용자 명시 승인:
- vault 생성 vs SKIP
- 분류 (별도 vendor vs 기존 vendor sub-line)
- priority 충돌 시 (같은 vendor 내 generation 역전)
- adapter score 다른 adapter 와 동률 → tie-break 결정

## 학습 누적

### cycle 2026-05-01 — 4 신규 vendor 추가 (vault SKIP)
- F44 huawei_ibmc / F45 inspur_isbmc / F46 fujitsu_irmc / F47 quanta_qct_bmc
- 모두 lab 부재 → web sources 의무 (rule 96 R1-A 신설)
- vault SKIP — 사용자 명시 승인 (placeholder 만)

### cycle 2026-05-06 — Superdome Flex (lab 부재 sub-line)
- M-E1 분류: HPE sub-line vs 별도 vendor → HPE sub-line (사용자 결정)
- adapter hpe_superdome_flex.yml priority=95 (sub-line 의 모델별 specificity)
- web sources 14건 명시
- mock fixture 13건 회귀

## 관련

- rule 50 R2 (vendor 추가 9단계)
- rule 96 R1-A (web sources 의무 — lab 부재 영역)
- rule 96 R1-B (envelope shape 보존)
- rule 27 R6 (vault 자동 반영 — vault 생성 시)
- skill: add-new-vendor (lab 보유 시), web-evidence-fetch (web sources 자동 수집), score-adapter-match (점수 디버깅), rotate-vault (vault 생성 절차)
- agent: vendor-onboarding-worker, adapter-author, web-evidence-collector, lab-tracker
- hook: post_merge_incoming_review (vendor 추가 검증)
- 정본: docs/operate/05-vault.md (vault 생성), docs/reference/live-validation.md (Round 검증), docs/develop/04-add-vendor.md (gather 추가 일반)
