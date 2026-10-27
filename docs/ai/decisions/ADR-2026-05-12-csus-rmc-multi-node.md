# ADR-2026-05-12-csus-rmc-multi-node

## 상태
Accepted (2026-05-12)

## 컨텍스트 (Why)

### 사용자 명시 (2026-05-12)

> "HPE Compute Scale-up Server(CSUS) 3200 및 관련 시스템에서 Redfish API를 사용한 통신은 RMC(Rack Management Controller)를 통해 수행된다는 정보를 받았어 ... 우리 프로젝트가 CSUS장비의 개더링을 어떻게 하는지 분석하고, CSUS장비도 개더링할 수 있도록 계획해야할 듯 해. 지금 CSUS 장비를 개더링하는 방식은 이방식이 아닌것같아서 CSUS 지원하는 방식을 모두 의심해야해. 다만문제는 테스트해볼 장비가 없어서 web을 통해서 확인할 수 밖에 없다는거야."

AskUserQuestion 응답 4결정 (2026-05-12):

| 항목 | 결정 |
|---|---|
| 수집 범위 | 전 Partition / 전 Manager / 전 Chassis (대형 변경) |
| URL 활용 | WebFetch + WebSearch 권위 인용으로 EXTERNAL_CONTRACTS 보강 |
| BMC 라벨 | RMC 분리 — adapter capability 기반 분기 (Additive) |
| 사이트 실측 | 없음 — web sources only |

### 발견된 결함 (실측)

cycle 2026-05-11 에 `hpe_csus_3200.yml` (priority=96) + `hpe_superdome_flex.yml` (priority=95) 어댑터가 web sources 기반으로 추가되었으나, **하부 라이브러리 `redfish-gather/library/redfish_gather.py` 가 단일 노드 가정** 으로 동작:

| 결함 | 위치 | 영향 |
|---|---|---|
| Members[0] 만 추출 | `_resolve_first_member_uri` (line 714-729) | Partition1~N / per-chassis PDHC / Bay iLO5 / Expansion Chassis 모두 누락 |
| 단일 manager_uri / system_uri 인자 | `gather_bmc` (line 1290) / `gather_system` (line 1173) | 멀티 노드 dispatch 불가 |
| BMC 라벨 통일 매핑 | `bmc_names['hpe'] = 'iLO'` (line 1308-1312) | RMC primary 시스템이 `bmc.name = 'iLO'` 로 잘못 출력 |
| RMC 비활성화 graceful fail 부재 | `_fetch_service_root` (line ~660) | HPE community 7200359 사례 — "Error getting service root, aborting" 진단 메시지 없음 |

### 외부 계약 근거 (rule 96 R1-A web sources)

HPE 공식 인용 (WebSearch 2026-05-12):
> "Because HPE has been working with the industry on the Redfish standard since its inception, it already **supports large, partitionable systems managed by a single aggregated controller like HPE Compute Scale-up Server 3200 RMC**."
>
> "supports full nPar (Partitioning). An **nPartition is a set of HPE Compute Scale-up Server chassis defined to work together to form a single computer system**."

근거 sources (7건 중 핵심):
- `https://support.hpe.com/hpesc/public/docDisplay?docId=sd00002765en_us&docLocale=en_US` — HPE Compute Scale-up Server 3200 Administration Guide (사용자 제시 URL)
- `https://servermanagementportal.ext.hpe.com/docs/concepts/gettingstarted` — RMC Redfish API standard
- `https://github.com/HewlettPackard/sdflexutils` — Superdome Flex 후속, Partition0 명시
- `https://community.hpe.com/.../impossible-to-get-redfish-answer-from-superdome-flex-rmc/td-p/7200359` — RMC 비활성화 risk signal
- `https://redfish.dmtf.org/schemas/DSP0266_1.15.0.html` — DMTF Redfish v1.15

### 측정 부재

cycle 2026-05-12 시점 — `redfish_gather.py` 의 단일 노드 가정이 13 vendor (HPE / Dell / Lenovo / Cisco / Supermicro / Huawei / Inspur / Fujitsu / Quanta) 모두 적용. CSUS 3200 / Superdome Flex 만 멀티 노드 토폴로지이지만 단일 path 만 수집됨 — drift 가시화 catalog 부재.

## 결정 (What)

8 결정 (`C:\Users\hshwa\.claude\plans\hpe-compute-scale-up-server-csus-spicy-newell.md` Phase 0~7):

### 결정 1: envelope 표현 — Option C (`data.multi_node` Additive 컨테이너)

```yaml
data:
  system: {...}        # 기존 — Partition0 representative (변경 0)
  bmc: {...}           # 기존 — RMC manager (변경 0, bmc.name 만 RMC/iLO 분기)
  ...                  # cpu/memory/storage/network/firmware/hardware/power 기존 8 path 변경 0
  multi_node:          # 신규 (Additive — manager_layout 미정의 vendor 는 null)
    enabled: true
    layout: "rmc_primary"
    summary:
      partition_count: 3
      manager_count: 4
      chassis_count: 3
      representative_partition: "Partition0"
    partitions: [...]  # list per-partition
    managers: [...]    # list per-manager
    chassis: [...]     # list per-chassis
```

**근거**: rule 13 R5 envelope 13 필드 고정 + rule 92 R2 Additive only. 신 키 1곳에 집중되어 drift scan 1 pass + 기존 호출자 (Jenkins 콜백 / 포털) 영향 0.

### 결정 2: 코드 리팩토링 — 변형 1 (`gather_*_multi()` 함수 신설, 기존 보존)

- `_resolve_all_member_uris` 신설 (line 730 직후, Additive)
- `gather_systems_multi` / `gather_managers_multi` / `gather_chassis_multi` 신설
- 기존 `_resolve_first_member_uri` / `gather_system` / `gather_bmc` 변경 0

**근거**: rule 92 R2 Additive only + rule 95 R1 #11 production 위험. 13 vendor 회귀 영향 0. 기존 함수 deprecation 시 단계적 전환 (별도 cycle).

### 결정 3: RMC 라벨 — adapter capability 기반 분기

- adapter `vendor_notes.manager_layout` (`rmc_primary` / `rmc_primary_ilo_secondary`) 을 `redfish_gather.py` 까지 전달
- `_classify_rmc_label(manager_uri, manager_id, manager_layout)` 신설 — substring 매칭 (`rmc` → `RMC`, `pdhc` → `PDHC`, `ilo` → `iLO`)
- `gather_bmc` 에 `manager_layout=None` 옵션 인자 추가 (None 일 때 기존 동작 100% 보존)

**근거**: rule 12 R1 BMC 표시명 매핑 인가 영역 (line 1308 이미 `nosec rule12-r1`). 다른 12 vendor 의 `manager_layout=None` → 기존 `bmc_names[vendor]` path 그대로.

### 결정 4: precheck graceful fail — `diagnosis.details.rmc_activation_check` Additive + `docs/reference/compatibility-matrix.md` 신규

- ServiceRoot 401/404/connection refused → `errors[0].message`: "ServiceRoot 응답 실패 — RMC Redfish API 활성화 미상 (HPE community 7200359 참조)"
- `diagnosis.details.rmc_activation_check` (true/false/null) + `diagnosis.details.multi_node_layout` (string/null) Additive
- `docs/operate/06-rmc-activation.md` 신규 — HPE RMC Redfish 활성화 절차 + community 트러블슈팅

**근거**: HPE community 7200359 위험 신호 대응. diagnosis.details 영역은 freeform dict — Additive 안전.

### 결정 5: mock fixture 합성 — 3-partition × 4-manager × 3-chassis

`tests/fixtures/redfish/hpe_csus_3200/` 17 fixture 합성:
- `service_root.json` (Product="Compute Scale-up Server 3200", Vendor="HPE")
- `managers_collection.json` (Members[4]: RMC / PDHC0 / PDHC1 / Bay1.iLO5)
- `systems_collection.json` (Members[3]: Partition0 / Partition1 / Partition2)
- `chassis_collection.json` (Members[3]: Base / Expansion1 / Expansion2)
- per-manager / per-system / per-chassis 11 파일
- `README.md` — 합성 출처 매핑 (sdflexutils + DMTF v1.15 + iLO5 API ref 3-source cross-check) + lab 부재 명시

`tests/fixtures/redfish/hpe_superdome_flex/` Partition1/2 + Expansion 보강.

**근거**: rule 96 R1-A web sources 4종 의무. lab 부재 합성 정당화.

### 결정 6: baseline — `tests/expected/` 별도 경로 + `schema/baseline_v1/` mock-derived 양쪽 채택

> **갱신 (2026-05-12 사용자 명시 승인)**: 본 결정은 두 차례 진행됨.
>
> **Q6 초기 결정 (2026-05-12 plan 단계)**: `tests/expected/redfish/hpe_csus_3200/mock_v1.json` 별도 경로만. `schema/baseline_v1/hpe_csus_3200_baseline.json` 은 lab 도입 cycle 까지 미작성.
>
> **Q6 갱신 결정 (2026-05-12 사용자 명시 — "스키마 디렉터리에 추가")**: 양쪽 모두 채택:
> - `tests/expected/redfish/hpe_csus_3200/mock_v1.json` 유지 (fixture-derived expected, pytest 회귀 reference)
> - `schema/baseline_v1/hpe_csus_3200_baseline.json` **추가** (mock-derived marker — `diagnosis.details.baseline_origin` 필드 + `schema/baseline_v1/README.md` mock-derived 정책 절 신설)
> - `schema/output_examples/redfish_hpe_csus_3200.jsonc` **추가** (한글 주석 호출자 reference, 헤더 "Lab 부재 — Mock 합성" 명시)

**갱신 근거**:
- rule 13 R4 (baseline 실측 보호) 경자적 해석 — mock-derived marker 명시 시 baseline_v1 영역 허용 (정책 신설 절: `schema/baseline_v1/README.md` "mock-derived baseline 정책" 절).
- 호출자 시스템 / 운영자 reference 가치 — mock fixture envelope shape 직접 확인 가능 (한글 주석본).
- 미래 lab 도입 cycle (NEXT_ACTIONS C2) 에서 실측 baseline 으로 in-place 교체 의무 (mock-derived marker → 실측 marker 전환).

**잔여 위험 (HIGH)**:
- mock-derived baseline 이 실측 baseline 으로 잘못 인용 — `diagnosis.details.baseline_origin` 필드 + README 정책 절로 진단 가시화. 자동 검사 hook 도입은 NEXT_ACTIONS (미래 작업).

### 결정 7: 기존 baseline 9종 `data.multi_node: null` derived 추가

- 13 vendor baseline 모두 `data.multi_node: null` (Additive)
- `scripts/ai/inject_summary_to_baselines.py` 패턴 (cycle 2026-05-11 F2 선례) 재사용

**근거**: rule 13 R4 의 derived 적용 — manager_layout 미정의 vendor 는 항상 null 보장 (실측 없이 안전한 default).

### 결정 8: NEXT_ACTIONS C1~C8 등재 (rule 50 R2 단계 10 / rule 96 R1-C)

C1: 사이트 fixture 캡처 (CSUS 3200 + Superdome Flex 각 1대)
C2: baseline JSON 추가 (lab 도입 후)
C3: lab 도입 cycle (`hpe-csus-rmc-lab-validation`)
C4: vault 분리 결정 (사용자 명시)
C5: ServiceRoot.Product 실측 — 정확한 model 문자열
C6: Managers / Systems / Chassis Member 개수 + ID 패턴 실측
C7: Oem.Hpe.PartitionInfo / FlexNodeInfo / GlobalConfiguration schema 실측
C8: RMC 활성화 / Subscription License 펌웨어 요구 실측

## 결과 (Impact)

### 정합성 검증

- **rule 13 R5 envelope shape 보존**: envelope 13 필드 변경 없음 (`data.multi_node` 는 `data` 내부 신 키) [PASS]
- **rule 13 R7 `docs/contract/03-fields.md` 동기화**: Phase 4 SUB-4.4 적용 [PASS]
- **rule 22 Fragment 철학**: 자기 fragment 만 / 5 공통 변수 / merge_fragment 호출 보장 [PASS]
- **rule 12 R1 vendor 경계**: `_classify_rmc_label` substring 매칭 — `bmc_names` 매핑 line 1308 `nosec rule12-r1` 인가 영역 확장 [PASS]
- **rule 50 R2 단계 10 (lab 부재)**: NEXT_ACTIONS C1~C8 등재 [PASS]
- **rule 70 R8 ADR 의무**:
  - Trigger 2 (정책/표준 신설) — `data.multi_node` 신 envelope path = schema 의미 확장 [TRIGGERED]
  - Trigger 3 (보호 경로 정책 변경) — `redfish_gather.py` 단일 노드 가정 → 멀티 노드 = 13 vendor 영향 위험 영역 [TRIGGERED]
  - 본 ADR 작성 [PASS]
- **rule 92 R2 Additive only**: 기존 path 변경 0 / 신 path 추가만 [PASS]
- **rule 95 R1 #11 외부 계약 drift**: web sources 7건 origin 주석 + NEXT_ACTIONS 실측 후 정정 의무 [PASS]
- **rule 96 R1-A web sources**: 7 sources (vendor 공식 / DMTF / GitHub / community) cross-check [PASS]
- **rule 96 R1-B envelope 13 필드 / `data.<section>.<field>` 보존**: 기존 9 section path 변경 0 / `data.multi_node` 는 신 키 (호환성 cycle 외 별도 cycle) [PASS]
- **rule 96 R1-C NEXT_ACTIONS 자동 등록**: C1~C8 등재 [PASS]

### 회귀 검증 (Phase 7 SUB-7.1~7.8)

본 ADR 시점 (Phase 0) — 검증 결과 미반영. Phase 7 완료 후 본 절 갱신 의무.

### 영향 vendor 매트릭스

| Vendor | 영향 |
|---|---|
| HPE CSUS 3200 / Superdome Flex | `data.multi_node` 활성 (manager_layout 정의) — multi-node 수집 |
| HPE iLO 4/5/6/7 (ProLiant) | `data.multi_node: null` (manager_layout 미정의) — 기존 path 변경 0 |
| Dell / Cisco / Lenovo / Supermicro / Huawei / Inspur / Fujitsu / Quanta | `data.multi_node: null` — 기존 path 변경 0 |

## 대안 비교 (Considered)

### envelope 표현 (결정 1)

| 옵션 | 호환성 | rule 92 R2 | drift scan | 거절 사유 |
|---|---|---|---|---|
| A. `data.<section>.partitions[]` (per-section sub-field 산재) | 100% | OK | 9 section × N partition 분산 — drift scan 어려움 | 데이터 검색 9곳 분산 |
| B. `data.<section>` → list 전환 | **0%** (호출자 폭파) | **위반** | extreme | 절대 채택 불가 |
| **C. `data.multi_node` 단일 컨테이너 + 기존 path 보존** | **100%** | **OK** | 1곳 집중 | **채택** |
| D. Partition0 만 + `diagnosis.details.additional_partitions` 메타 | 100% | OK | LOW | 사용자 결정 "전 Partition 수집" 위반 |

### 코드 리팩토링 (결정 2)

| 변형 | 호환성 | 거절 사유 |
|---|---|---|
| **1. multi 함수 신설 + 기존 보존** | **100%** | **채택** |
| 2. 기존 함수에 `multi=True` 옵션 + 내부 분기 | 100% | 분기 복잡도 + 단위 테스트 부담 |
| 3. 단일 노드 함수 deprecation + 일괄 전환 | 0% (13 vendor 회귀) | rule 92 R2 / rule 95 R1 #11 위반 — 절대 채택 불가 |

### RMC 라벨 (결정 3)

| 옵션 | 거절 사유 |
|---|---|
| iLO 유지 (변경 0) | 사용자 결정 "RMC 분리" 위반 |
| `bmc.manager_type` 신 보조 필드 추가 | envelope `data.<section>.<field>` 추가 — rule 96 R1-B 위반 (별도 cycle 의무) |
| **adapter capability 기반 분기** | **채택** — Additive |

### baseline (결정 6)

| 옵션 | 거절 사유 |
|---|---|
| `schema/baseline_v1/hpe_csus_3200_baseline.json` 합성 추가 | rule 13 R4 실측 baseline 보호 위반 |
| **`tests/expected/` 별도 경로** | **채택** — fixture-derived expected 명확 분리 |

## Rollback

본 cycle 실패 시 rollback 절차:

1. **Git revert** — Phase 0~7 commit 모두 revert
2. **NEXT_ACTIONS C1~C8 보존** — lab 도입 cycle 정보 유지
3. **adapter 어댑터 (hpe_csus_3200 / hpe_superdome_flex) 유지** — cycle 2026-05-11 결과 그대로 (단, `vendor_notes.multi_node_support` Additive 추가는 revert)
4. **fixtures / expected / unit tests 보존** — lab 도입 cycle 재사용

Rollback trigger:
- pytest 회귀 5건 이상 FAIL
- `pre_commit_additive_only_check.py` blocking 통과 불가
- 사용자 명시 보류

## NEXT_ACTIONS (C1~C8 — rule 50 R2 단계 10 / 96 R1-C)

`docs/ai/NEXT_ACTIONS.md` Phase 6 SUB-6.5 에 등재:

| # | 항목 | 책임 / 상태 |
|---|---|---|
| C1 | 사이트 fixture 캡처 (CSUS 3200 + Superdome Flex) | `capture-site-fixture` skill / PENDING (lab 부재) |
| C2 | baseline JSON 추가 — `schema/baseline_v1/hpe_csus_3200_baseline.json` / `hpe_superdome_flex_baseline.json` | C1 완료 후 / PENDING |
| C3 | lab 도입 cycle `hpe-csus-rmc-lab-validation` round | C1+C2 완료 후 / PENDING |
| C4 | vault 분리 결정 (`vault/<loc>/redfish/hpe_csus.yml`) | 사용자 명시 승인 / PENDING |
| C5 | ServiceRoot.Product 실측 — 정확한 model 문자열 | C1 / PENDING |
| C6 | Managers / Systems / Chassis Member 개수 + ID 패턴 실측 | C1 / PENDING |
| C7 | Oem.Hpe.PartitionInfo / FlexNodeInfo / GlobalConfiguration schema 실측 | C1 / PENDING |
| C8 | RMC 활성화 / Subscription License 펌웨어 요구 실측 | C1 + C4 / PENDING |

## 관련

- plan: `C:\Users\hshwa\.claude\plans\hpe-compute-scale-up-server-csus-spicy-newell.md`
- rule: `13-output-schema-fields` (R5/R7), `22-fragment-philosophy`, `12-adapter-vendor-boundary` (R1), `50-vendor-adapter-policy` (R2 단계 10), `70-docs-and-evidence-policy` (R8), `92-dependency-and-regression-gate` (R2), `95-production-code-critical-review` (R1 #11), `96-external-contract-integrity` (R1-A / R1-B / R1-C)
- skill: `add-new-vendor`, `add-vendor-no-lab`, `capture-site-fixture`, `web-evidence-fetch`, `update-output-schema-evidence`, `verify-json-output`
- agent: `adapter-author`, `fragment-engineer`, `schema-reviewer`, `vendor-boundary-guardian`, `web-evidence-collector`
- ADR 선례:
  - `ADR-2026-04-28-rule12-oem-namespace-exception.md` (rule 12 R1 Allowed 영역)
  - `ADR-2026-05-06-rule13-r7-docs20-sync.md` (envelope 정본 변경 시 `docs/contract/03-fields.md` 동기화)
  - `ADR-2026-05-11-field-channel-declaration-refinement.md` (field_dictionary 분류 / channel 정밀화)
- cycle 선례: cycle 2026-05-11 hpe-csus-add (어댑터 신설), cycle 2026-05-06 M-E2 (hpe_superdome_flex 신설)
- web sources (rule 96 R1-A): `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` HPE 절 (Phase 6 SUB-6.2 보강)

## 승인 기록

| 일시 | 승인자 | 대상 | 비고 |
|---|---|---|---|
| 2026-05-12 | hshwang1994 | 본 ADR / 8 결정 / 4 사용자 답변 / ExitPlanMode 승인 | plan 파일 + AskUserQuestion 4 답변 + ExitPlanMode 한 번에 승인 |

## 2026-10-27 정정 기록 (2차 Mock 실측 · 지시서 2 FIX 5/6)

- **결정 6(baseline) 이행 상태**: `schema/baseline_v1/hpe_csus_3200_baseline.json` 은 2026-10-27 현재도 mock-derived 합성본이다(ADR 의 "lab 도입 시 실측 교체 의무" 미이행 — 2차 분석 01-multi_node-003).
  사용자 FIX 5(2026-10-27): 2차 Mock csus3200_01 의 Tier 1 실 봉투로 in-place 교체하고 소비 테스트를 같은 커밋에서 재작성한다 — 구현 Round WP11(bmc/diagnosis) 뒤 실행 예정(이 기록 시점에는 미실행).
  2026-10-27 FIX 1 로 그 합성본의 `cpu.logical_threads`(4곳)만 먼저 제거했다.
- **외부 계약 추정 정정**: ResourceBlock `Processors[]/Memory[]` 는 실 RMC 에 없다(composition count 는 null — FIX 6). RMC `OperatingSpeedMhz` 는 I/O 클럭(3200, PC5-6400B) 이다(FIX 3 — 원값 보존, 계약 6.2).
  `ProcessorSummary.LogicalProcessorCount` 의 뜻은 펌웨어 버전(1.75 코어 수 · 1.77 스레드 수)에 따라 달라 Redfish 는 `cpu.logical_threads` 를 내지 않는다(FIX 1).
- **결정 1 보강(bmc.name, 2026-10-27 06-bmc-006)**: `manager_layout` 이 없어도 `ManagerType RackManager`/`EnclosureManager` 면 Manager `Id`(`RMC`) 또는 ManagerType 라벨을 쓴다 —
  결함표 3행("RMC primary 가 `bmc.name='iLO'`")이 adapter 선택 결과에만 묶여 있던 것을 장비 값으로도 막는다(plain 재생 `RMC`). RMC 계정 `@Redfish.WriteableProperties`(06-bmc-002) 는 EXTERNAL_CONTRACTS 2026-10-27.
