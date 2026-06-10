# 의사결정 로그

> **이 문서는** server-exporter 가 지금 모습이 된 "이유" 를 누적 기록한 결정 이력이다.
> 누군가 "왜 이렇게 만들었는지" 또는 "전에 다른 방식으로 한 적 있는지" 가 궁금할 때 가장 먼저 검색하는 곳이다.
>
> 검증 라운드(Round) 결과, 이슈 분석, 정책 변경 같은 큰 결정은 모두 이 문서에 시간순으로 추가된다.
> 코드만 읽고는 알 수 없는 맥락(왜 이 fallback 이 있는지 등)이 여기 있다.

> 최종 갱신: 2026-06-04

## 2026-05-29 — CSUS 3200 전 공통 섹션 수집 + HBA/InfiniBand 전 채널 (lab 부재 — web sources)

### 배경

- CSUS 3200 장비도 다른 장비처럼 공통 JSON 내용이 모두 담기도록 대대적 개편 필요. HBA / InfiniBand 도 전 서버 개더링 대상. lab 부재 → web 검색.

### 분석

- **CSUS baseline 이 빈 skeleton** — 멀티-노드 토폴로지(id) 만 채우고 per-partition cpu/memory/storage/network 는 raw/빈 + mock 미완성.
- **HBA/IB 분류가 dead-code** — Redfish `Port.PortType` 에 FC/IB 값 없음 (DMTF Port.v1_9_0). ESXi `'infiniband' in type` 도 dead. Windows FC 필터 없음 + IB hardcoded []. → "안 담긴다" 의 실제 원인.
- HBA/IB schema 는 이미 v1 존재 → 구현 + 정합 문제이지 schema 신설 아님.

### 결정 (D1/D2/D3)

- FC/IB 분류를 DMTF `PortProtocol`/`LinkNetworkTechnology`/`NetDevFuncType` 기반으로 정정 (PortType 사용 금지). WWPN/WWNN/GUID 는 NetworkDeviceFunction 에서.
- 전 채널 통일 canonical shape + `source` 필드. CSUS 전 Partition canonical 정규화 + realistic mock baseline.
- D1=ESXi API-only / D2=Linux 보강 / D3=추가만 (schema_version "1" 유지, field_dictionary 74→83).

### 영향

- 추가만 (envelope 13 필드와 기존 path 는 그대로 유지). 4 채널 gather + redfish library + field_dictionary + esxi/csus baseline + docs/20.
- esxi_baseline hbas 5→2 (FC 만 — 동일 raw 재분류, SATA AHCI/SAS RAID 제외).

### 회귀

- pytest **699 PASS / 0 FAIL** (full suite; CSUS baseline regression registry 등록 + per-partition/canonical 신규 테스트). validate_field_dictionary PASS. Windows/Linux Jinja render 테스트 PASS.
- lab 부재: mock "검증됨" 주장 금지. 사이트 fixture 캡처 후속 작업.

---

## 2026-05-12 — HPE CSUS 3200 / Superdome Flex RMC 멀티-노드 Redfish 수집 정식 지원 (lab 부재 — 별도 검증)

### 배경 (2026-05-12)

- HPE Compute Scale-up Server(CSUS) 3200 의 Redfish API 통신은 RMC(Rack Management Controller)를 통해 수행된다. CSUS 장비를 개더링할 수 있도록 계획 필요. 기존 CSUS 수집 방식이 RMC 모델과 맞지 않아 CSUS 지원 방식을 전면 재검토. 테스트 장비 부재로 web 확인.
- 결정 4건: (1) 전 Partition / Manager / Chassis 수집 (대형 변경) / (2) 권위 인용으로 외부 계약 보강 / (3) RMC 분리 — adapter capability 기반 분기 (기존 동작에 추가만) / (4) lab 부재 — 공식 문서 (web) 기반

### 컨텍스트

`hpe_csus_3200.yml` (priority=96) + `hpe_superdome_flex.yml` (priority=95) 어댑터가 web sources 기반으로 추가되었으나, **하부 라이브러리 `redfish-gather/library/redfish_gather.py` 가 단일 노드 가정**:

- `_resolve_first_member_uri` (line 714-729) — Members[0] 만 추출 → Partition1~N / per-chassis PDHC / Bay iLO5 / Expansion Chassis 누락
- `gather_bmc` (line 1290) / `gather_system` (line 1173) — 단일 manager_uri / system_uri 인자
- `bmc_names['hpe'] = 'iLO'` (line 1308) — RMC primary 시스템이 `bmc.name = 'iLO'` 로 잘못 출력
- ServiceRoot 실패 시 graceful fail 부재 — HPE community 7200359 "Error getting service root, aborting" 사례

HPE 공식 인용 (웹 검색, 2026-05-12): "supports large, partitionable systems managed by a single aggregated controller like HPE Compute Scale-up Server 3200 RMC. supports full nPar (Partitioning)."

### 결정 (8종)

1. **envelope 표현 — Option C**: `data.multi_node` 단일 컨테이너를 추가하고 기존 9 section path (`data.system`/`data.bmc`/...) 는 그대로 유지
2. **코드 리팩토링 — 변형 1**: `gather_*_multi()` 함수 신설 + 기존 함수 그대로 유지
3. **RMC 라벨**: adapter `vendor_notes.manager_layout` 을 `redfish_gather.py` 까지 전달 + `_classify_rmc_label` substring 매칭
4. **precheck graceful fail**: `diagnosis.details.rmc_activation_check` + `multi_node_layout` 추가 + `docs/22_rmc-activation-guide.md` 신규
5. **mock fixture 합성**: 3-partition × 4-manager × 3-chassis (sdflexutils + DMTF v1.15 + iLO5 API ref 3-source cross-check) + README 출처 매핑
6. **baseline 경로**: `tests/expected/redfish/hpe_csus_3200/mock_v1.json` 별도 경로 — `schema/baseline_v1/` 는 lab 도입 시까지 미작성 (실측 baseline 보호)
7. **derived 추가**: 기존 baseline 9종에 `data.multi_node: null` 추가 (summary inject 패턴 재사용)
8. **후속 검증 권장**: 사이트 fixture / baseline / lab 검증 / vault / Product 실측 / Member ID 실측 / Oem schema 실측 / 활성화 요구 실측

### 대안 거절 사유

| 대안 | 거절 사유 |
|---|---|
| `data.<section>` 을 list 로 전환 (Option B) | 호환성 0% — 호출자 (Jenkins 콜백 / 포털) 폭파 |
| 기존 `gather_*` 함수에 `multi=True` 옵션 + 내부 분기 (변형 2) | 분기 복잡도 + 단위 테스트 부담 |
| 단일 노드 함수 deprecation + 일괄 전환 (변형 3) | 13 vendor 회귀 영향. 절대 채택 불가 |
| `bmc.manager_type` 신 보조 필드 추가 | `data.<section>.<field>` 추가 — 호환성 외 별도 schema 변경 의무 |
| `schema/baseline_v1/hpe_csus_3200_baseline.json` 합성 추가 | 실측 baseline 보호 위반 |

### 갱신 (2026-05-12 — schema 디렉터리에 추가)

> 결정 번복 — `tests/expected/` 별도 경로만 → 양쪽 모두 (schema/baseline_v1/ + schema/output_examples/ + tests/expected/) 채택.

| 영역 | 변경 |
|---|---|
| `schema/baseline_v1/hpe_csus_3200_baseline.json` | **신규** — mock-derived marker (`diagnosis.details.baseline_origin` 필드 + `schema/baseline_v1/README.md` mock-derived 정책 절 신설). 9 sections + multi_node 활성 (3-partition × 4-manager × 3-chassis). |
| `schema/output_examples/redfish_hpe_csus_3200.jsonc` | **신규** — 한글 주석 호출자 reference. "Lab 부재 — Mock 합성" 헤더. envelope 13 필드 + multi_node 컨테이너 + RMC 라벨 분기 설명. |
| `schema/baseline_v1/README.md` | mock-derived baseline 정책 절 신설 — marker 3종 (README 표 / JSON baseline_origin / output_examples 헤더) + 자동 검사 hook 도입 후속 작업 표기. |
| `schema/output_examples/README.md` | Redfish 표에 CSUS 3200 행 추가 (10 → 11 entries). |

### 적용 변경

| 영역 | 변경 |
|---|---|
| `redfish-gather/library/redfish_gather.py` | `_resolve_all_member_uris` / `gather_systems_multi` / `gather_managers_multi` / `gather_chassis_multi` / `_classify_rmc_label` / `_collect_multi_node_topology` 신설 (기존 함수 유지, 추가만). `gather_bmc` 에 `manager_layout` 옵션 인자 |
| `redfish-gather/tasks/{detect_vendor,collect_standard,try_one_account,normalize_standard}.yml` | `_rf_adapter_manager_layout` fact + `manager_layout` 인자 전달 + `_data_fragment.multi_node` 조립 |
| `redfish-gather/tasks/vendors/hpe/{collect,normalize}_oem.yml` | 멀티 partition loop (`systems[0]` → 전수) |
| `adapters/redfish/hpe_csus_3200.yml` / `hpe_superdome_flex.yml` | vendor_notes 갱신 ("첫 partition 만 수집" 표현 제거, `multi_node_support: true` 추가) |
| `schema/field_dictionary.yml` | `data.multi_node.*` 8~12 nice entries 추가 |
| `schema/baseline_v1/*.json` (9종) | `data.multi_node: null` derived 추가 |
| `tests/fixtures/redfish/hpe_csus_3200/` | 신규 17 fixture (3-partition × 4-manager × 3-chassis) |
| `tests/fixtures/redfish/hpe_superdome_flex/` | Partition1/2 + Expansion 보강 |
| `tests/expected/redfish/hpe_csus_3200/mock_v1.json` | 신규 (fixture-derived expected) |
| `tests/unit/test_*.py` | 신규 3 단위 테스트 (hpe_csus_multi_node / resolve_all_members / classify_rmc_label) |
| `docs/20_json-schema-fields.md` | multi_node 절 추가 (docs/20 동기화) |
| `docs/22_rmc-activation-guide.md` | 신규 — RMC 활성화 절차 + community 7200359 트러블슈팅 |

### 검증

검증 체크리스트:
- envelope 13 필드 shape 그대로 유지
- sections 10 그대로 유지
- field_dictionary 65 → +8~12 nice entries
- 13 vendor 회귀 통과 (manager_layout 미정의 vendor 는 `data.multi_node = null` 만 추가되고 나머지는 그대로 유지)

### 관련

- 선례: 2026-05-11 hpe-csus-add (어댑터 신설), 2026-05-06 (hpe_superdome_flex 신설), 2026-05-11 (summary inject derived)
- 위험 signal: HPE community 7200359 "impossible to get redfish answer from superdome flex rmc"

---

## 2026-05-11 — Adapter 선택 단계 검증 + Supermicro X12 priority 일관성 fix

### 배경 (2026-05-11)

- 어떤 adapter 를 쓸지 결정하는 단계에서 문제 발생 이력이 있어 현재 상태 점검. 필요 시 web 검색 활용.
- 잠재 위험 2건 fix 포함 + web 검색

### 컨텍스트

HPE DL380 Gen11 → hpe_ilo7 오선택 (commit `8c0fe0f6`) + hpe_ilo7 firmware 2-part 매치 실패 (commit `1387b505`) 가 RESOLVED 되었지만 검증 차원에서 production 코드 점검 추가 수행. Supermicro X11~X14 priority 매트릭스에서 잠재 위험 2건 발견:

1. **X12 priority 90 — 역전** (X11=100, X12=90, X13=100, X14=110)
2. **X11~X14 firmware_patterns 부재** — model_patterns 만으로 매칭

Supermicro 공식 docs / DMTF web 검색 후 결정.

### 결정

#### 적용 사항

- **`adapters/redfish/supermicro_x12.yml` L27 `priority: 90 → 100`** (X11/X13 와 일관성). model_patterns 가 정확히 매칭되면 선택 결과는 동일하다. lab 부재라 사이트 동작에 영향 없음.
- origin 주석 갱신 — Last sync 2026-05-11 + 사유 + 보류분 결정 명시.

#### 보류 사항

Supermicro X11~X14 firmware_patterns 추가는 **보류**. 근거:

1. **firmware empty 시 disqualify 안 됨** (`module_utils/adapter_common.py:258-267` 점검 결과 — 안전)
2. **AST2500 (X11) vs AST2600 (X12+) firmware 형식 거의 동일** — `X.YY.ZZ` vs `0X.YY.ZZ` 만 차이. web sources 만으로 generation 분리 정확도 약함 (X11 firmware "1.73.10" 가 X12 패턴 `^0?1\.[0-9]+\.[0-9]+` 에도 매칭)
3. **lab 부재** — 실 firmware 형식 확정 전 정규식 가설은 미스매치 시 `match_score=-9999` (graceful fallback 발생, 사고 0 이지만 기능 손실) 위험

→ 보류분은 사이트 BMC IP 확보 후 실측 fixture 캡처 + 별도 작업.

### 대안 거절 사유

| 대안 | 거절 사유 |
|---|---|
| 보류분도 함께 적용 (web sources 가설 적용) | lab 부재 + AST2500/AST2600 형식 거의 동일 → 사이트 미스매치 시 graceful fallback 발생. 잘못된 generation adapter 선택보다는 안전하지만 정확도 부족. 점검 목적 (현재 상태 검토) 의 회귀 위험 회피 우선 |
| X12 priority 90 유지 (의도된 값일 수 있음) | 주석 부재 + X11/X13 와 일관성 깨짐. lab 도입 후 재검토 시 priority 90 의 의도 추적 불가. 일관성 우선 |
| X12 priority 110 (X14 와 동급) | X12 가 X14 보다 우선될 이유 없음. X14 가 최신 generation 이라 110 유지 |

### 적용 변경

| 영역 | 변경 |
|---|---|
| `adapters/redfish/supermicro_x12.yml` | priority `90 → 100` + origin 주석 갱신 |
| `tests/unit/test_supermicro_adapter_selection.py` | 신규 (12 시나리오 + priority 회귀 차단) |

### 검증

- pytest 신규 12 시나리오 + priority test PASS
- 기존 626 회귀 영향 없음 (관련 회귀 PASS)
- ansible syntax-check redfish-gather/site.yml PASS

### 관련

- `module_utils/adapter_common.py:258-287` (점수 공식)
- `lookup_plugins/adapter_loader.py:232-237` (tie-break stable sort)
- 선례: hpe-ilo7-gen12-match-fix, HPE DL380 Gen11 오선택 (commit `8c0fe0f6`)

---

## 2026-05-11 — HPE Compute Scale-up Server 3200 (CSUS 3200) adapter 추가 (lab 부재)

### 배경 (2026-05-11)
- HPE CSUS 장비 개더링 요구 발생.
- CSUS = HPE Compute Scale-up Server 3200 / lab 부재 — web sources only / BMC 정보 미상
- 결정 3종 (priority=96 / vault profile=hpe 재사용 / OEM regex 확장 — 기존 매칭에 추가만) 모두 적용

### 컨텍스트

CSUS3200 매칭 패턴이 부재하여 현재 `hpe_ilo.yml` (priority=10) generic fallback 됨 → Oem.Hpe.PartitionInfo / FlexNodeInfo / GlobalConfiguration (nPAR 정보) 수집 누락. HPE 공식 자료 명시 *"built on the proven HPE Superdome Flex architecture"* (HPE psnow doc/a50009596enw) 로 Superdome Flex 와 동일 RMC + Oem.Hpe namespace 가정 가능.

### 결정

1. **별도 adapter 파일 신설** ("새 모델 = 새 adapter") — `adapters/redfish/hpe_csus_3200.yml` 신규
2. **priority = 96** — Superdome Flex (95) 직상, iLO 6 (100) 직하. model_patterns 분리로 ProLiant 는 영향받지 않음 (점수 일관성)
3. **HPE 공통 OEM tasks 재사용** — `redfish-gather/tasks/vendors/hpe/{collect,normalize}_oem.yml` 의 model regex 확장 (기존 매칭에 추가만):
   - 기존: `(?i)Superdome|Flex`
   - 변경: `(?i)Superdome|Flex|Compute Scale-up|CSUS`
   - fragment field name (`oem_hpe_superdome`) 유지 — envelope shape 변동 없음
4. **vault profile = "hpe" 재사용** — 별도 `vault/redfish/hpe_csus.yml` 분리는 후속 등재
5. **baseline / fixture SKIP** (lab 부재). 후속 작업 4 항목 등재
6. **firmware_patterns 추정**: `^[34]\\.[0-9]+\\..*` (RMC 3.x/4.x — Superdome Flex 2.x/3.x 후속, 사이트 실측 시 정정 가능)

### 대안 거절 사유

| 대안 | 거절 사유 |
|---|---|
| Superdome Flex adapter 의 model_patterns 만 확장 | CSUS3200 은 DDR5 신라인 + RMC firmware 세대 다름. 펌웨어/모델 매트릭스 추적 흐려짐. Round 검증 후 별도 baseline 필요 |
| 새 HPE sub-vendor 신설 (`hpe_csus` 별도) | HPE 동일 vendor (Manufacturer = "HPE / Hewlett Packard Enterprise"). vendor_aliases.yml 변경 불필요. **(2026-06-04 refine: 내부 canonical 은 여전히 `hpe` 로 유지하되, 출력 표시값만 `hpCsus` 로 분기 — 본 거절 사유는 canonical 차원에서 유효)** |
| OEM tasks 별도 분리 (collect_csus_oem.yml 신설) | Oem.Hpe namespace 동일 + PartitionInfo/FlexNodeInfo 상속. 재사용이 단순하고 기존 동작을 유지하기 쉬움 |

### 적용 변경

| 영역 | 변경 |
|---|---|
| `adapters/redfish/hpe_csus_3200.yml` | 신규 (priority=96, web sources 7건 origin 주석) |
| `redfish-gather/tasks/vendors/hpe/collect_oem.yml` | model regex 확장 (기존 매칭에 추가만) + 주석 갱신 |
| `redfish-gather/tasks/vendors/hpe/normalize_oem.yml` | model regex 확장 (기존 매칭에 추가만) + 주석 갱신 |
| `docs/13_redfish-live-validation.md` | 16.3 / 16.3.1 항목 추가 |

### Web Sources (lab 부재 vendor 의무, 확인 2026-05-11)

1. [HPE CSUS 3200 FAQ](https://cdrdv2-public.intel.com/792357/FAQ%20-%20HPE%20Compute%20Scale-up%20Server%203200.pdf) — RMC + 표준 Redfish API
2. [HPE psnow architecture and RAS](https://www.hpe.com/psnow/doc/a50009596enw) — "built on the proven HPE Superdome Flex architecture"
3. [HPE store product page](https://buy.hpe.com/us/en/compute/mission-critical-x86-servers/compute-scale-up-servers/compute-scale-up-servers/hpe-compute-scale-up-server-3200/p/1014774076) — 4-socket / DDR5
4. [HPE Server Management Portal](https://servermanagementportal.ext.hpe.com/) — RMC Redfish 표준
5. [HPE Support sd00001798en_us](https://support.hpe.com/hpesc/public/docDisplay?docId=sd00001798en_us) — CSUS 3200 / Superdome Flex 공통 support
6. [Redfish DMTF DSP0266 v1.15](https://redfish.dmtf.org/schemas/DSP0266_1.15.0.html) — 표준 schema
7. [iLO 5 API Reference](https://hewlettpackard.github.io/ilo-rest-api-docs/ilo5/) — Oem.Hpe namespace reference

### 검증

- 정적: `ansible-playbook --syntax-check redfish-gather/site.yml` / yamllint
- 동적: adapter 점수 mock — CSUS 3200 / ProLiant Gen11 (회귀) / Superdome Flex 280 (회귀) 각각 올바른 adapter 선택 확인
- 회귀: HPE baseline (`hpe_baseline.json` — DL380 Gen11 iLO 6) 통과 (model_patterns 분리로 영향 없음)

---

## 2026-06-04 — 출력 envelope vendor 표시값 매핑 (hpe→hp, CSUS 3200→hpCsus)

### 결정

호출자 노출 envelope `vendor` 값을 HPE 계열 `hp`, HPE CSUS 3200 `hpCsus` 로 변경.
**Design A — 출력 라벨만 변경**: 내부 canonical `hpe` 유지(라우팅 무손상), 출력만 data-driven
표시 맵(`common/vars/vendor_aliases.yml` 의 `vendor_output_display`/`adapter_output_display`)으로 치환.

### 범위 (결정 4건)

| 항목 | 결정 |
|---|---|
| 구현 방식 | 출력 라벨만 변경 (내부 canonical 불변) |
| hpCsus 범위 | HPE Compute Scale-up Servers 패밀리 — CSUS 3200 + Superdome Flex (둘 다 RMC 관리 scale-up). 초기 "CSUS 3200 한정" → 2026-06-04 HPE 공식 분류 web 검증 후 Superdome Flex 포함 확대 |
| 채널 범위 | 3 채널 전체 (redfish/os/esxi) `hp` |
| 표기 | `hpCsus` camelCase 유지 + schema enum 변경 승인 |

### 적용 변경

- `common/vars/vendor_aliases.yml`: `vendor_output_display` / `adapter_output_display` 신규
- `redfish-gather/site.yml` / `esxi-gather/site.yml` / `os-gather/site.yml`: `_out_vendor` 표시 매핑
- `schema/field_dictionary.yml`: vendor enum `hpe`→`hp` + `hpCsus` (Stage 3 gate). `schema_version` 정수 `"1"` 유지 (shape 13필드 불변)
- `schema/baseline_v1/hpe_baseline.json`(→`hp`) / `hpe_csus_3200_baseline.json`(→`hpCsus`)
- `schema/output_examples/redfish_hpe_ilo6.jsonc`(→`hp`) / `redfish_hpe_csus_3200.jsonc`(→`hpCsus`)
- `tests/regression/test_vendor_output_display.py` (신규 D1~D6) + `test_cross_channel_consistency.py` `CANONICAL_VENDORS`
- docs: `docs/20`, `README.md`

### 검증

- pytest 748 passed / validate_field_dictionary PASS / Jinja 표시식 단위 검증 PASS
- `ansible-playbook --syntax-check`: Windows dev box ansible 부재로 미실행 (Linux Agent/CI 수행)

### 호환성 주의

envelope `vendor` 는 외부 계약. `hpe` 로 필터링하던 다운스트림 소비자는 `hp`/`hpCsus` 로 갱신 필요.
(본 변경 자체가 다운스트림 요구에서 출발.)

### lab 도입 후 후속 작업 4 항목

| # | 항목 | trigger | 책임 |
|---|---|---|---|
| 1 | 사이트 fixture 캡처 | BMC IP 확보 | 사이트 fixture 캡처 |
| 2 | baseline JSON 추가 (`schema/baseline_v1/hpe_csus_3200_baseline.json`) | 실장비 검증 후 | 실측 baseline 갱신 |
| 3 | lab 도입 검증 (`hpe-csus-3200-lab-validation` round) | 별도 round 진입 | Round 검증 + 펌웨어 매트릭스 확정 |
| 4 | vault 분리 결정 (`vault/redfish/hpe_csus.yml`) | 향후 승인 시 | 현재 hpe 재사용 — 향후 결정 시 분리 |

---

## 2026-05-11 — HPE iLO 7 Gen12 2-part firmware version 매치 보강

### 컨텍스트

직전 `hpe-csus-add` (commit `a123b1cc`) mock 검증의 부수 발견 — mock S1
시나리오에서 `facts = {vendor: HPE, model: "ProLiant DL380 Gen12", firmware: "1.10"}`
입력 시 `hpe_ilo7.yml` (priority=120) 이 매치하지 못하고 `hpe_ilo4.yml`
(priority=50) 이 선택되는 갭 재현 확인.

원인 (`module_utils/adapter_common.py` L260-267):
- `firmware_patterns` 매치 실패 + facts.firmware 비어있지 않으면 **-9999 disqualify**.
- iLO 7 기존 regex `["iLO.*7", "^\\d+\\.\\d+\\.\\d+"]` 는 3-part version 만 가정.
- 2-part "1.10" → 둘 다 매치 X → iLO 7 disqualify.
- iLO 6 `^1\.[5-9]` (한자리 minor) / iLO 5 `^2\.[0-9]` / iLO 4 `^1\.[0-9]` 중
  iLO 4 의 `^1\.[0-9]` 만 "1.1" prefix 매치 → iLO 4 유일 생존.

위험: 사이트 iLO 7 Gen12 BMC 신규 도입 시 facts.firmware 추출 path
(Manager.FirmwareVersion 만, System.FirmwareVersion 부재) 에 따라 2-part short version
보고 가능 → iLO 4 (SmartStorage legacy / Oem.Hp namespace) adapter 선택 →
Gen12 OEM 정보 (Oem.Hpe.SystemInformation 등) 수집 실패.

### 결정

1. **`hpe_ilo7.yml` L43 firmware_patterns 확장 (기존 패턴 유지, 추가만)**:
   - 기존: `["iLO.*7", "^\\d+\\.\\d+\\.\\d+"]`
   - 변경: `["iLO.*7", "^\\d+\\.\\d+\\.\\d+", "^1\\.1[0-9]"]`
   - `^1\.1[0-9]` (1.10~1.19) 명시 — 충돌 검증:
     - iLO 4 `^1\.[0-9]` (한자리 minor 1.0~1.9): 충돌 없음
     - iLO 6 `^1\.[5-9]` (한자리 minor 1.5~1.9): 충돌 없음
2. **origin 주석 보강** — mock 갭 재현 기록 + 미래 1.20+ 2-part 사이트 실측 위임 명시
3. **회귀 보존 5 시나리오 검증**:
   - S1 (1.10) → iLO 7 (fix 효과)
   - S2 (1.16.00) → iLO 7 (3-part 회귀)
   - S3 (1.73 Gen11) → iLO 6 (회귀)
   - S4 (3.10.00 CSUS) → CSUS3200 (회귀)
   - S5 (2.10.00 SDFlex) → SDFlex (회귀)

### 대안 거절 사유

| 대안 | 거절 사유 |
|---|---|
| `"^\\d+\\.\\d+(\\.\\d+)?"` (2-part + 3-part broad) | iLO 5 / iLO 6 / CSUS3200 / SDFlex 모두 1.x or 2-part 와 광범위 충돌 — priority 위계만으로 회피 가능하지만 model_patterns 누락 시 disqualify 안 됨. 명시적 `^1\.1[0-9]` 가 안전 |
| `^1\.[1-9][0-9]` (1.10~1.99 두자리 minor) | iLO 4 spec 명시 firmware 한자리 minor 만 — 그러나 실제 iLO 4 펌웨어 1.50~1.99 변형 가능성 미확인. lab 부재 — 보수적 `^1\.1[0-9]` 채택 |
| model_patterns 만으로 매치 (firmware_patterns 제거) | firmware regex 매치 실패 시 -9999 disqualify 메커니즘 회피 가능하지만 model_patterns 가 없는 iLO 4/5/6 와 동일 점수 매트릭스 — disqualify 메커니즘 자체가 안전판 |

### 적용 변경

| 영역 | 변경 |
|---|---|
| `adapters/redfish/hpe_ilo7.yml` L34-43 | firmware_patterns 확장 + 주석 보강 (3 line 추가, model_patterns 무변경) |
| `docs/19_decision-log.md` | 본 entry |

### 검증

- 정적: `python -c "import yaml; yaml.safe_load(open('adapters/redfish/hpe_ilo7.yml'))"` PASS
- 동적: mock 5 시나리오 점수 회귀 — 5/5 PASS
  - S1: iLO 7 120570 > iLO 4 50345 → iLO 7 선택 (fix 효과)
  - S2: iLO 7 120570 → iLO 7 (3-part 회귀)
  - S3: iLO 6 100345 → iLO 6 (Gen11 회귀)
  - S4: CSUS 96570 → CSUS 3200 (회귀)
  - S5: SDFlex 95570 → SDFlex 280 (회귀)
- 회귀: `pytest tests/` 590/590 PASS

### 후속 (lab 도입 후)

- iLO 7 Gen12 사이트 fixture 캡처 (`tests/fixtures/redfish/hpe_ilo7/` — facts.firmware 실측 형식 확정)
- 1.20+ 2-part 변형 발견 시 firmware_patterns 추가 정정
- 사이트 이슈 발생 시 reverse regression 검토 (사이트 실측 > spec)

---

## 2026-05-11 — Jinja2 namespace scoping 회귀 패턴

### 컨텍스트

Ansible Jinja2 `{% set var = var + ... %}` 형식의 self-reference 누적이 loop scope 안에서 의도대로 동작하지 않는 회귀가 반복 발생. per-iteration local 로 초기화되어 누적 값이 사라지는 문제.

### 검출되는 대표 회귀 패턴

| # | 위치 | 사고 | 해결 |
|---|---|---|---|
| 1 | `os-gather/tasks/linux/gather_network.yml:99` | netmask CIDR 잘못 계산 (/23, /30) | namespace fix (val → ns.val) |
| 2 | `esxi-gather/tasks/normalize_network.yml:67` | 동일 netmask 사고 | 동일 namespace fix |
| 3 | `os-gather/tasks/linux/gather_users.yml:77, 212` | groups 집계 의도 모호 | namespace 로 통일 (ns.groups) |

### 결정

- loop 안 누적 변수는 Jinja2 `namespace()` (`ns.val`) 로 통일 — per-iteration local self-reference (`{% set var = var + ... %}`) 금지
- 검출 패턴: `{% set var = var + ... %}` 같은 self-reference 누적 (per-iteration local 안전)

---

## 2026-05-11 — adapter `recovery_accounts.vault_label` ↔ vault `accounts.label` 정합

### 컨텍스트

vendor default 계정 자동 생성 path 보장 후속 검증 중 `dell_idrac10.yml` 의 declared `recovery_accounts.vault_label` (`dell_root_dellidrac1`, `dell_root_calvin`) 이 vault `dell.yml` 의 실 label (`dell_fallback_1`, `dell_fallback_2`, `dell_current`, `lab_dell_root`) 와 mismatch 발견. `account_service.yml:31-41` 의 label 우선 → username fallback chain 으로 기능 정상이지만 label 매칭 활성화 안 됨 (username fallback 으로 항상 우회). 9 vendor 전수 동일 패턴.

### 결정 (2026-05-11)

**쟁점 1: Dell/HPE/Lenovo adapter 정합 범위**
- 결정: **B. Vault 전수 declare 확장** (Dell 4 / HPE 3 / Lenovo 3 entry — vault 실 label 와 동일)
- 대안 A (최소 rename) / C (현 상태 유지 + 문서화) 거절

**쟁점 2: Supermicro/Cisco/Huawei/Inspur/Fujitsu/Quanta 6 vendor 처리**
- 결정: **A. 함께 채움** (`*_factory` 1~2 entry)
- 대안 B (별도 작업 / lab 도입 시) 거절

### 적용 변경 (29 adapter — generic 제외)

| Vendor | Adapter 수 | Before | After |
|---|---|---|---|
| Dell | 4 | 2 entry (`dell_root_dellidrac1`, `dell_root_calvin`) | 4 entry (`dell_fallback_1`, `dell_fallback_2`, `dell_current`, `lab_dell_root`) |
| HPE | 6 | 1 entry (`hp_admin_hpinvent1`) | 3 entry (`hpe_fallback`, `hpe_current`, `hpe_factory`) |
| Lenovo | 4 | 1 entry (`lenovo_userid_default`) | 3 entry (`lenovo_fallback`, `lenovo_current`, `lenovo_factory`) |
| Supermicro | 8 | `[]` | 1 entry (`supermicro_factory`) |
| Cisco | 3 | `[]` | 2 entry (`cisco_current`, `cisco_factory`) |
| Huawei | 1 | `[]` | 1 entry (`huawei_factory`) |
| Inspur | 1 | `[]` | 1 entry (`inspur_factory`) |
| Fujitsu | 1 | `[]` | 1 entry (`fujitsu_factory`) |
| Quanta | 1 | `[]` | 1 entry (`quanta_factory`) |

총 변경 line: 94 insertions / 39 deletions (29 file). vault 변경 0.

### 변경 범위

- **추가만** — adapter declare entry 를 **추가**할 뿐, 코드 로직 / collect / normalize / match 는 그대로 유지
- **envelope shape 유지** — adapter declare 텍스트만 변경. 기존 호출자 시스템의 파싱 방식은 바뀌지 않음
- **vault 자동 반영 유지** — cacheable / fact_caching / decrypt 캐시 모두 사용 안 함

### 효과

- **label 우선 매칭 활성화** — `account_service.yml:31-41` chain 의 label match (line 32-35) 가 즉시 hit → username fallback (line 37-39) 추가 시도 회피. multi-vendor 환경에서 try_one_account 시도 회수 감소 (성능 향상)
- **label mismatch 해제** — 9 vendor 전수 (Dell + HPE + Lenovo 14 adapter mismatch 해제)
- **6 vendor recovery_accounts 채움** — Supermicro/Cisco/Huawei/Inspur/Fujitsu/Quanta `[]` → 1+ entry (`*_factory`)
- **호출자 동작 유지** — envelope shape 그대로 유지

### 검증

- **pytest**: 497/497 PASS
- **`python3 tests/validate_field_dictionary.py`**: sections=10 / fd_paths=65 / fd_section_prefixes=16 — 변경 0

### 정본 reference

- `docs/21_vault-operations.md` §6.5 — 9 vendor recovery 자격 매트릭스 (line 191-208)
- `redfish-gather/tasks/account_service.yml:31-41` — label 우선 → username fallback chain
- `redfish-gather/tasks/try_one_account.yml` — 시도 체인

### 후속 (별도 작업 권장)

- **신규 회귀 테스트** — `tests/unit/test_adapter_vault_label_consistency.py` (29 adapter × declared label ∈ docs/21 §6.5 vendor 매트릭스 검증). 시간 제약으로 보류. 별도 작업
- **lab 도입 후 검증** — Huawei/Inspur/Fujitsu/Quanta + 6 generation 미검증 vendor 의 label 매칭 회귀는 lab 도입 후 후속 작업

---

## 2026-05-07 — schema/output_examples/ 신설 + baseline_v1 annotated 정리 (실 장비 개더링)

### 컨텍스트

배경 (2026-05-07):

> 실제 개더링 가능한 장비를 대상으로 개더링하고 그 값으로 JSON 출력 예시를 갱신. schema/baseline_v1 이 JSON 출력 예시 디렉터리가 아니라면 별도 디렉터리를 만들고 schema/baseline_v1 에 추가된 파일은 제거. 의도가 맞으면 갱신만. 한글 주석으로 모든 JSON 키값 설명 첨부.

직전 작업 (commit b65e162e) 이 baseline_v1 안에 한글 주석본 8개 (`*_annotated.jsonc`) 를 추가했으나, baseline_v1 정본 의도 (회귀 기준선 — Jenkins Stage 4 pytest 입력) 와 충돌. 위치 부적합 확인.

### 결정

**A. baseline_v1 != 출력 예시 → 신규 디렉터리** `schema/output_examples/` 신설.

**B. 자격증명** — 기존 vault 사용 + 평문 노출 허용.

**C. 실행 위치** — Jenkins 에이전트 10.100.64.155 SSH 접속 후 직접 ansible-playbook 실행. 결과 rsync 회수.

**D. 디렉터리 분류**:

| 디렉터리 | 정본 의도 | 누가 사용 |
|---|---|---|
| `schema/baseline_v1/` | **회귀 기준선** (Jenkins Stage 4 pytest 입력) | 자동화 회귀 |
| `schema/output_examples/` (신설) | **호출자 / 운영자 reference** — 한글 주석 + 실 응답 | 사람 |
| `schema/examples/` | 시나리오 별 예시 (success/partial/failed/not_supported) | 호출자 (시나리오 설명) |

### 산출물

- 신설: `schema/output_examples/{README.md, 10 jsonc 파일}`
- 삭제: `schema/baseline_v1/*_annotated.jsonc` 8개 (위치 부적합)
- 보존: baseline_v1 *_baseline.json 8개 / examples *.json 4개 / sections.yml / field_dictionary.yml

### 검증

- pytest 335/335 PASS
- envelope 13 필드 / sections 10 / field_dictionary 65 — 변경 없음 (추가만)
- 기존 호출자 시스템의 파싱 방식은 바뀌지 않음

### 후속

- 펌웨어 / 환경 변경 시 본 디렉터리 재 캡처 (실측 baseline 갱신 또는 직접 갱신)
- 6개월 갱신 0건 시 stale 가능 — 외부 계약 동기화 권장

---

## 2026-05-06 — status 의도 결정 (Case A 채택)

### 컨텍스트

의심 영역 (status 판정 로직):

> 개더링 상태가 success / failed / partial 3종으로 나뉘는데, 로직이 정상 작동하지 않는 것으로 보임. 부분 성공이라도 errors 에 로그가 찍히는데 success 로 빠지는 경우가 있음 — 의도된 동작인지 확인 필요.

→ 분석 결과 (commit `ba003b2f`): 시나리오 B (섹션 success + errors warning → overall=success) 는 **명백한 의도된 동작**. 코드 주석 3 위치가 명시:
- `os-gather/tasks/linux/gather_memory.yml:171-172` (dmidecode fallback 사유 추적)
- `os-gather/tasks/linux/gather_network.yml:208` (lspci stderr 권한 부족 추적)
- `esxi-gather/tasks/normalize_storage.yml:79-80` (NFS/vSAN/vVOL cap 미수집 추적)

build_status.yml 판정 로직 (정본 인라인 Jinja2): **errors[] 는 보지 않는다 / 섹션 status 만 본다**. errors[] 는 사유 추적용 분리 영역.

### 결정 (4 포인트)

결정 4 포인트 (합리적 default 채택):

| 결정 | 선택 | 근거 |
|---|---|---|
| (1) 시나리오 B 처리 | **B-1 (현재 동작 유지)** | 의도된 설계 + 기존 동작 유지 + envelope shape 보존 |
| (2) errors[] severity | **(a) 유지** | Fragment 5 변수 / 타입 + envelope 13 필드 + 3채널 27+ 위치 영향 → 별도 작업 영역 |
| (3) status_rules.yml | **(c) 유지** | DEAD CODE 명시 주석 "삭제 금지 / 향후 reserved" |
| (4) status enum | **(a) 3 enum 유지** | envelope 13 필드 정본 + 호환성 외 schema 확장 별도 작업 |

→ **Case A 채택** — 의도된 동작 명시만 (주석/문서 강화, 동작 변경 없음).

### 영향

- 코드 동작 변경: **없음**
- envelope 13 필드: **변경 없음** (보존)
- status enum: **3종 유지** (success / partial / failed)
- 9 vendor baseline 회귀: **영향 없음**
- 호출자 시스템 파싱: **영향 없음**

### 후속 작업

1. `common/tasks/normalize/build_status.yml` 헤더 주석 강화 — 시나리오 B 의도 명시 + errors[] 분리 의미 명문화 + 코드 주석 3 reference
2. `status_rules.yml` 변경 0 (DEAD CODE 명시 주석 reference 확인만)
3. mock fixture 1건 신규 — 시나리오 B 재현 (`status_success_with_warnings.json`)
4. pytest 회귀 PASS 확인
5. docs/20_json-schema-fields.md 신설 시 status 판정 규칙 절 포함 의무

### 대안 비교

- **Case B (B-2 + ?)**: errors non-empty → overall=partial. 거절 이유: 모든 vendor baseline 회귀 fail (success → partial 전환), 호출자 partial 대응 로직 추가 필요, 호환성 외 영역
- **Case C (B-3 + (b) + (b))**: 4 enum + severity 도입. 거절 이유: envelope schema 변경 (승인 필요), 3채널 27+ 위치 영향, 단순 추가 범위를 넘어섬 — 별도 작업 승인 후 진행 영역

### 참고

- envelope 13 필드 — status 필드 정본 보존
- Fragment 5 변수 / 타입 정본 — 변경 안 함
- status_rules.yml 유지 (DEAD CODE)
- 동작 변경 없이 추가만
- schema 변경 승인 필요 — Case C 거절 이유
- 호환성 외 envelope shape 변경 자제

---

## 2026-05-01 — 신규 vendor 4종 도입 (Huawei / Inspur / Fujitsu / Quanta)

### 컨텍스트
배경 (2026-05-01):
1. 신규 장비 도입 의향. 테스트할 lab 장비 부재 — vault 는 보류하고 코드 생성 작업 우선.
2. 신규 vendor 추가 승인.

승인에 따라 신규 vendor 4종 진행.

### 결정
4 vendor adapter 코드 영역 진행. **vault 단계 SKIP** (lab 부재).

### 적용 범위 (vendor 추가 절차 매핑)

| 단계 | 작업 | 상태 |
|---|---|---|
| 1. vendor_aliases.yml 매핑 | 4 vendor alias 추가 | [OK] |
| 2. adapter YAML 생성 | huawei_ibmc / inspur_isbmc / fujitsu_irmc / quanta_qct_bmc | [OK] |
| 3. (선택) OEM tasks | 부재 (standard_only — 사이트 fixture 확보 후 보강) | DEFER |
| 4. vault 생성 | vault/redfish/{vendor}.yml | **SKIP (lab 부재)** |
| 5. baseline | schema/baseline_v1/{vendor}_baseline.json | DEFER (lab 부재) |
| 6. vendor 노트 | adapter vendor_notes 4종 | [OK] |
| 7. vendor 경계 매핑 | huawei/inspur/fujitsu/quanta 추가 | [OK] |
| 8. live-validation | docs/13_redfish-live-validation.md Round 갱신 | DEFER (lab 부재) |
| 9. decision-log | 본 entry | [OK] |

### redfish_gather.py 동기화

`_FALLBACK_VENDOR_MAP` + `_BMC_PRODUCT_HINTS` + `bmc_names` dict 모두 4 vendor 추가 (vendor 경계 예외 주석 보존).

- `_FALLBACK_VENDOR_MAP`: 11 신 entry (huawei/inspur/fujitsu/quanta 변형 alias)
- `_BMC_PRODUCT_HINTS`: 7 신 entry (ibmc/fusionserver/isbmc/irmc/primergy/quantagrid/quantaplex)
- `bmc_names`: 4 신 entry (huawei→iBMC, inspur→ISBMC, fujitsu→iRMC, quanta→BMC)

### 영향
- adapter 표면: 34 → 38 (Redfish 23 → 27)
- vendor 정규화 list: 5 → 9
- vault 신규: 0 (lab 부재 SKIP)
- baseline 신규: 0 (lab 부재)
- 운영 가능 시점: lab 또는 사이트 장비 도입 + vault 생성 시

### 부재 시 동작 (graceful degradation)

- ServiceRoot 무인증 detect → vendor=huawei/inspur/fujitsu/quanta 정규화 OK
- vault 부재 → precheck auth 단계에서 status=failed (graceful degradation)
- 호출자 envelope: status=failed + errors[] = ["vault not found for vendor=<huawei|inspur|fujitsu|quanta>"]

### 사이트 도입 시 절차

1. `vault/redfish/{vendor}.yml` 생성 (ansible-vault encrypt + username/password)
2. `tests/redfish-probe/probe_redfish.py --vendor {vendor}` 실행
3. `schema/baseline_v1/{vendor}_baseline.json` 생성
4. Round 검증 기록
5. `docs/13_redfish-live-validation.md` Round 갱신
6. 사이트 fixture 캡처

### 참고

- vendor 추가 절차 (vault SKIP 적용)
- lab 부재 — web sources 4종 1개 이상 (4 vendor 모두 충족)
- vendor 경계 — _FALLBACK_VENDOR_MAP 등 예외 주석 보존

---

## Round 12 (2026-04-29) — ESXi 채널 hostname / vendor / extended modules fix

### 배경
관측: ESXi 출력 JSON 에서 `hostname=IP`, `vendor` 정규화 실패, `network.adapters / virtual_switches / storage.hbas` 빈 배열.

### 진단
agent 10.100.64.154 SSH + 진단 playbook (`tests/scripts/diag_esxi_raw.yml`) 으로 raw facts 캡처.

| BUG | 원인 |
|---|---|
| #1 hostname=IP | `normalize_system.yml` 의 `system.fqdn = _e_ip` (ansible_hostname 미사용) |
| #2 vendor 정규화 | Jinja2 loop scoping — namespace fix 잔류분 |
| #4 extended 빈 | `community.vmware 6.2.0` hosts_*_info dict key 는 hostname (IP 아님). dict list 는 `vmnic_details`/`vmhba_details` (`all` 은 string list). 매핑 키 정정: pci→location, adapter_type→type, node_wwn 등. vswitch 는 dict-of-dict |

### Fix
- `esxi-gather/site.yml` (+11 lines) — `_e_hostname` 변수 + namespace pattern
- `esxi-gather/tasks/normalize_system.yml` (+3 lines)
- `esxi-gather/tasks/collect_network_extended.yml` (+30 lines)
- `schema/baseline_v1/esxi_baseline.json` (+231 / -47, esxi02 실측 갱신)

### 검증
- 실 호스트 esxi01 + esxi02 (10.100.64.1 / .2) 본 site.yml 실행 — NIC/vSwitch/HBA 모두 정상 채워짐
- pytest 158/158 PASS, vendor 경계 / ansible-syntax-check 통과

### 잔류 (별도 작업)
- `default_gateways=[]` / `dns_servers=[]` — vmware_host_facts 미반환 / host_config_info 빈 응답 (vmware_host_dns_info 모듈 추가 필요)
- `speed_mbps` int / "N/A" string 혼재
- `cpu.architecture` / `max_speed_mhz` null (model 파싱 폴백 가능)
- `include_vars` `name:` reserved-name 경고 (호출자 동작에는 영향 없음)

---

> [!NOTE]
> 여기부터(§1~§13)는 2026-03~04 초기 검증 라운드 기록이다(번호순). 위쪽은 최근 결정부터의 날짜 역순 기록이다. 현재값은 `adapters/`, `schema/` 를 본다.

## 1. 코드 점검 1차/2차 결과 요약

### 1차 점검
- 전체 프로젝트 구조 분석
- 보안 이슈 (no_log 누락) 식별
- 기본 코드 품질 이슈 도출

### 2차 점검 (4 차수 완료)
- **1차**: power section 추가, hostname fallback 개선, int coercion regex 수정, vault 경고
- **2차**: OUTPUT default 방어, 에러 메시지 개선, no_log 정리
- **3차**: bare except → specific exceptions, no_log 제거, hostname None-safety
- **4차**: CALLBACK_NEEDS_WHITELIST → CALLBACK_NEEDS_ENABLED

총 19개 파일, ~50개 변경사항 — 모두 검증 완료.

## 2. Redfish Endpoint 선택 근거

### 코드가 호출하는 14개 엔드포인트

| # | 엔드포인트 | 선택 근거 |
|---|-----------|----------|
| 1 | Service Root | DMTF 필수. 벤더 감지 + 컬렉션 URI 확보 |
| 2 | Systems 컬렉션 | system_uri 동적 취득 |
| 3 | Systems/{id} | 서버 기본 정보 (model, serial, CPU/메모리 요약) |
| 4 | Managers/{id} | BMC 정보 (firmware version) |
| 5 | Processors 컬렉션 | CPU 상세 (모델, 코어, 스레드) |
| 6 | Processors/{pid} | 개별 CPU 정보 |
| 7 | Memory 컬렉션 | DIMM 목록 |
| 8 | Memory/{mid} | 개별 DIMM 정보 |
| 9 | Storage 컬렉션 | 스토리지 컨트롤러/드라이브 |
| 10 | Storage/{sid} | 컨트롤러 상세 + 드라이브 링크 |
| 11 | SimpleStorage (fallback) | Storage 미지원 구형 BMC 호환 |
| 12 | EthernetInterfaces 컬렉션 + 개별 | 호스트 NIC 정보 |
| 13 | FirmwareInventory 컬렉션 + 개별 | 전체 펌웨어 목록 |
| 14 | Chassis/{id}/Power | PSU 정보 |

### 미포함 엔드포인트와 제외 근거

| 엔드포인트 | 제외 근거 |
|-----------|----------|
| Chassis/{id}/Thermal | 온도/팬 정보 — 판정 시점에 normalize 스키마 미정의. 향후 추가 고려 |
| Managers/{id}/EthernetInterfaces | BMC NIC — system 레벨로 충분 |
| Bios | BIOS 설정 — BiosVersion은 System에서 이미 취득 |
| LogServices | 이벤트 로그 — 수집 범위 초과 |
| NetworkInterfaces | NIC 상세 — EthernetInterfaces로 충분 |

## 3. Adapter 설계 근거

### 왜 adapter 시스템을 사용하는가
1. **벤더별 normalize 차이**: 같은 Redfish 표준이라도 필드 존재 여부가 다름
2. **세대별 차이**: 같은 벤더라도 BMC 세대에 따라 스키마 다름 (예: HPE iLO5 vs iLO6)
3. **확장성**: 새 벤더/세대 추가 시 adapter YAML만 추가하면 됨
4. **테스트 용이**: adapter 단위로 fixture 테스트 가능

### Adapter 선택 알고리즘
- `adapter_loader.py`가 `adapters/redfish/` 디렉토리 스캔
- `match` 조건 (vendor, model_pattern 등) 비교
- 복수 매칭 시 `priority` + `specificity` 점수로 정렬
- 최고 점수 adapter 반환

## 4. Normalize 정책 근거

### null 허용 정책
실장비 검증 결과, 벤더마다 누락 필드가 다름:
- HPE: IndicatorLED, SpeedMbps, LinkStatus, ProcessorSummary.Status.Health
- Lenovo: Manager.Status.Health
- Dell: Drive.Status.Health

→ **정책**: 코드가 추출하는 모든 필드는 `_safe()` 함수로 None 반환 허용.
normalize에서 `| default(none)` 처리.

### 빈 문자열 처리
- HPE HostName = "" (빈 문자열) → normalize에서 `or _out_ip` fallback 필요
- build_output.yml에서 처리 (2차 점검에서 수정 완료)

### Storage Controllers fallback
- 판정 시점: `StorageControllers` 인라인 배열만 처리
- HPE Gen11: `Controllers` 서브링크 사용 → **fallback 추가 필요** (8절에서 구현 완료)

## 5. 실장비 검증으로 확정된 사항

| 항목 | 결정 | 근거 |
|------|------|------|
| vendor 감지 기준 | System.Manufacturer | 3사 모두 동작 확인 |
| URI 패턴 | 동적 (Members[0]) | 벤더마다 다른 ID 패턴 |
| Storage fallback | Storage 우선, SimpleStorage fallback | Lenovo/HPE는 SimpleStorage 404 |
| Basic Auth | 유지 | 3사 모두 동작 |
| Thermal 수집 | 보류 | endpoint 존재하나 normalize 스키마 미정의 |
| default_gateways | Redfish 불가 | OS 레벨 정보 — os-gather에서 수집 |

## 6. 실장비 검증으로 추정에 머무는 사항

| 항목 | 추정 내용 | 불확실 요인 |
|------|----------|------------|
| 다른 세대 URI 패턴 | 동일할 것으로 추정 | Gen10, R640 등 미검증 |
| Supermicro 호환 | 코드에 Supermicro 분기 있으나 미검증 | 장비 부재 |
| Session Auth | 동작할 것으로 추정 | Basic만 테스트 |
| HPE iLO5 차이 | iLO6과 유사할 것으로 추정 | Oem.Hpe vs Oem.Hp fallback 미검증 |
| 다중 System member | Members[0]만 사용 | 블레이드 서버 등 미검증 |

## 7. OEM 필드 보강 판정 (Round 14)

> 판정일: 2026-03-25

### 결론

**판정 시점의 수집 범위에서는 Standard Redfish로 대응 가능하다.** OEM placeholder는 향후 운영 요구 발생 시 확장한다.

수집 범위(firmware inventory + PSU health/state/metrics) 기준으로, 아래 근거 표의 모든 영역에서 standard endpoint만으로 필요 데이터를 확보할 수 있었다. OEM 추가 가치가 낮다고 판단한 근거는 아래 표 참조.

### 근거

| 영역 | Standard 수집 현황 | OEM 추가 가치 |
|------|-------------------|---------------|
| Firmware | FirmwareInventory 28+ 항목 (BIOS, BMC, RAID, NIC, PSU FW) | OEM-specific metadata (낮음) |
| Power | PSU health/state/metrics + power_control consumed watts | PSU redundancy N+1, line voltage (낮음) |
| 기타 | — | Thermal throttle history, license/warranty (범위 외) |

### OEM Framework 상태

- 4개 벤더(Dell/HPE/Lenovo/Supermicro) adapter YAML에 `oem_tasks` 경로 정의 완료
- `collect_oem.yml` / `normalize_oem.yml` placeholder 파일 존재
- **운영 요구 발생 시 placeholder만 채우면 즉시 확장 가능**

### 향후 확장 트리거

OEM 구현을 재검토해야 하는 상황:
1. 포털에서 PSU redundancy status(N+1) 표시 요구 발생
2. 벤더별 OEM-specific health code 해석 요구
3. Thermal 섹션 스키마 정의 및 수집 요구
4. 특정 벤더에서 standard endpoint로 수집 불가능한 필드 발견

## 8. 리팩토링 이력 (실장비 검증 기반, 2026-03-18)

### 완료

| 항목 | 파일 | 내용 |
|------|------|------|
| 1 | `redfish_gather.py` | HPE Storage Controllers fallback (Controllers 서브링크 드릴다운) |
| 2 | `redfish_gather.py` | gather_power() ServiceRoot 중복 호출 제거 (chassis_uri 직접 전달) |
| 3 | `hpe_ilo6.yml` | HPE iLO 6 전용 adapter 신규 생성 |
| 4 | `redfish_gather.py` | 벤더별 null 필드 경고 로깅 |
| 5 | `redfish_gather.py` | HostName 빈 문자열 → None 변환 |
| 6 | `redfish_gather.py` | MemorySummary Health → HealthRollup fallback |
| 7 | `redfish_gather.py` | IndicatorLED → LocationIndicatorActive fallback |

### 보류

| 항목 | 사유 |
|------|------|
| 단위 변환 헬퍼 통일 | 검증 시점에 코드 동작 확인됨, 우선순위 낮음 |
| Thermal 수집 추가 | normalize 스키마 미정의, 향후 요구 시 구현 |
| Supermicro/다중 System member/Session Auth/iLO5 차이 | 실장비 미보유로 검증 불가, 장비 확보 시 재검토 |

## 9. Linux Raw Fallback Round 2 검증 (2026-04-15)

### 배경

Round 1에서 Linux 2-Tier Gather (Python 감지 + Raw Fallback) 기본 구현을 완료했다. Round 2에서는 5대 서버에 대해 31개 필드 전수 비교 검증을 수행했다.

### SELinux 정규화 버그 수정

`gather_system.yml`의 raw 경로에서 `getenforce` 출력값(`Enforcing`/`Permissive`/`Disabled`)을 Ansible 컨벤션(`enabled`/`disabled`)으로 정규화하지 않는 버그를 발견하고 수정했다.

- **수정 전**: `getenforce` 출력 그대로 반환 (예: `Enforcing`)
- **수정 후**: `Enforcing`/`Permissive` → `enabled`, `Disabled` → `disabled`로 정규화

### 5대 서버 필드 전수 비교 결과

| 서버 | OS | Python | 감지 모드 | 결과 | 비고 |
|------|-----|--------|----------|------|------|
| RHEL 8.10 | RHEL 8.10 | 3.6.8 | `python_incompatible` (자동) | 31/31 MATCH | auto fallback과 forced raw 간 완전 일치 |
| RHEL 9.2 | RHEL 9.2 | 3.9+ | `python_ok` | memory 차이만 | raw 경로가 더 정밀 (아래 분석 참조) |
| RHEL 9.6 | RHEL 9.6 | 3.9+ | `python_ok` | memory 차이만 | 동일 |
| Rocky 9.6 | Rocky 9.6 | 3.9+ | `python_ok` | memory 차이만 | 동일 |
| Ubuntu 24.04 | Ubuntu 24.04 | 3.9+ | `python_ok` | selinux 1건 차이 | 허용 범위 (아래 분석 참조) |

### Memory 차이 분석 (버그 아님)

RHEL 9.x / Rocky 9.6에서 Python 경로와 raw 경로 간 memory 값 차이가 발생한다. 이는 **버그가 아니라 raw 경로가 더 정확**한 결과이다.

| 경로 | 수집 방식 | 값 (예시) | 의미 |
|------|----------|----------|------|
| Python 경로 | `ansible_memtotal_mb` (OS 보고) | 7680 MB | 커널 예약 후 OS 가시 메모리 (`os_visible`) |
| Raw 경로 | `dmidecode --type 17` (하드웨어 직접) | 8192 MB | 물리 장착 메모리 (`physical_installed`) |

→ raw 경로의 dmidecode 기반 수집이 실제 물리 메모리를 반환하므로 하드웨어 인벤토리 용도에 더 적합하다.

### Ubuntu SELinux 차이 (허용)

Ubuntu 24.04에서 `selinux` 필드 차이 1건 발생:
- Python 경로: `disabled` (Ansible이 SELinux 미설치를 disabled로 보고)
- Raw 경로: `null` (`getenforce` 명령 미설치)

→ Ubuntu는 SELinux를 기본 탑재하지 않으므로 `null` 반환이 의미적으로 정확하다. 허용 범위로 판정.

### 결론

5대 서버, 31개 필드 전수 검증 완료. Raw fallback은 Python 경로와 동등하거나 더 정밀한 결과를 제공한다. 프로덕션 적용 가능.

## 10. Network 심층 검증 (Round 3, 2026-04-15)

### 배경

Round 2 이후 Network 섹션에 대해 심층 검증을 수행했다. 가상 인터페이스 skip 패턴 확장, 다중 default route 동작 확인, primary 판단 규칙 명확화가 주요 내용이다.

### skip 패턴 확장

기존 skip 패턴(`lo`, `docker*`, `br-*`, `veth*`, `virbr*`, `vir*`)에 아래 패턴을 추가했다:

| 추가 패턴 | 대상 | 추가 근거 |
|----------|------|----------|
| `cni*` | Kubernetes CNI 인터페이스 | K8s 노드에서 불필요한 가상 인터페이스 수집 방지 |
| `flannel*` | Flannel CNI overlay | 동일 |
| `cali*` | Calico CNI | 동일 |
| `tunl*` | tunnel 인터페이스 | IPIP 터널 등 가상 인터페이스 제외 |
| `dummy*` | dummy 인터페이스 | 테스트/라우팅 용도 가상 인터페이스 제외 |
| `kube-*` | Kubernetes internal | kube-proxy 등 내부 인터페이스 제외 |

**주의**: `br0`, `bond0`, `team0`, `eth0.100`(VLAN) 등 실 네트워크 인터페이스는 skip 대상이 아니다.

### 5대 서버 다중 default route 동작 확인

5대 서버(RHEL 8.10, RHEL 9.2, RHEL 9.6, Rocky 9.6, Ubuntu 24.04)에서 다중 default route가 존재하는 경우 metric 기준 정렬 후 첫 번째만 사용하는 동작을 확인했다. Python 경로(`ansible_default_ipv4`)와 raw 경로(`ip route show default | head -1`) 모두 동일한 결과를 반환한다.

### primary 판단 규칙 명확화

| 결정 | 내용 |
|------|------|
| primary 정의 | IPv4 default route가 걸린 인터페이스 = primary |
| bond master | default route가 bond master에 걸리면 bond master가 primary |
| bridge | default route가 bridge에 걸리면 bridge가 primary |
| slave/port | IP가 없으므로 primary 불가 |
| 다중 default route | lowest metric wins (첫 번째만 사용) |

### 결론

Network 수집 정책을 문서화 완료. skip 패턴 확장으로 Kubernetes/tunnel/dummy 가상 인터페이스를 추가 제외하고, primary 판단 규칙과 다중 default route 처리를 명확화했다.

## 11. Network 복잡 토폴로지 실증 (Round 4, 2026-04-15)

### 배경

Round 3에서 skip 패턴을 확장하고 primary 판단 규칙을 명확화했다. Round 4에서는 Ubuntu 24.04에 복잡 네트워크 토폴로지를 실제 구성하여 수집 정확성을 실증했다.

### 실증 환경

Ubuntu 24.04 (10.100.64.167)에 아래 토폴로지를 구성:

| 인터페이스 | 유형 | 역할 |
|-----------|------|------|
| ens192 | 물리 NIC | primary (default route dev) |
| ens224 | 물리 NIC | 보조 NIC |
| br0 | bridge | dummy0를 slave로 포함 |
| ens192.100 | VLAN | ens192 위 VLAN 서브인터페이스 |
| dummy0 | dummy (bridge slave) | br0의 port (slave) |
| cni0 | container NIC | Kubernetes CNI |
| flannel.1 | container NIC | Flannel overlay |
| docker0_test | container NIC | Docker 테스트 bridge |
| policy routing | table 100 | `ip rule` + `ip route table 100` |

### 발견된 문제

skip 패턴(`dummy*`)이 배포 시점에 반영되지 않아 cni0, flannel.1은 skip되지 않았다 (배포 이슈). 이와 별개로, **dummy0가 bridge port(slave)임에도 수집되는 문제**를 발견했다. dummy0는 br0의 하위 포트이므로 독립 인터페이스로 수집하면 안 된다.

### 수정 내용

raw path에 bridge slave / bond slave 자동 필터를 추가했다:

- `/sys/class/net/$dev/master`가 존재하는지 확인 (slave 여부)
- slave이면서 자신이 bridge master(`/sys/class/net/$dev/bridge/` 존재)도 아니고 bond master(`/sys/class/net/$dev/bonding/` 존재)도 아닌 경우 → skip
- bridge master나 bond master는 slave이더라도 수집 (중첩 구성 대응)

### 수집 결과 비교

| 구분 | 수집된 인터페이스 | 개수 |
|------|-----------------|------|
| 수정 전 | ens192, ens224, br0, ens192.100, dummy0, cni0, flannel.1 | 7개 |
| 수정 후 | ens192, ens224, br0, ens192.100 | 4개 |

### 인터페이스별 검증

| 인터페이스 | primary | speed | IP 수집 | 판정 |
|-----------|---------|-------|--------|------|
| ens192 | true (default route dev) | 10000 | O | 정확 |
| ens224 | false | 10000 | O | 정확 |
| br0 | false | null (가상) | O | 정확 |
| ens192.100 | false | 10000 (부모 상속) | O | 정확 |
| dummy0 | — | — | — | skip (bridge slave) = 정확 |
| cni0 | — | — | — | skip (가상 NIC) = 정확 |
| flannel.1 | — | — | — | skip (가상 NIC) = 정확 |
| docker0_test | — | — | — | skip (가상 NIC) = 정확 |

### 결론

복잡 토폴로지(bridge + VLAN + container NIC + policy routing)에서 수집 정확성을 실증했다. bridge slave/bond slave 자동 필터 추가로 불필요한 하위 포트 수집이 제거되었다. 4개 인터페이스만 정확히 수집되며, primary 판단도 정확하다.

## 12. Network 운영 해석 기준 확정 + bond 실증 (Round 5, 2026-04-15)

### 배경

Round 4까지 skip 패턴, primary 판단, bridge slave 필터를 검증했다. Round 5에서는 5대 서버 명령어 존재성 매트릭스 실측과 bond 토폴로지 실증을 수행하여 운영 해석 기준을 확정했다.

### 명령어 존재성 매트릭스 실측

15개 명령 x 5대 서버(RHEL 8.10, RHEL 9.2, RHEL 9.6, Rocky 9.6, Ubuntu 24.04)에 대해 명령어 존재 여부를 실측했다.

핵심 발견:
- RHEL 9는 `resolvectl` 미설치 (systemd-resolved 패키지 미포함)
- Ubuntu는 `nmcli` 미설치 (NetworkManager 미사용)
- `ip`, `getent`, `/sys/class/net`, `/proc/*`, `/etc/os-release`는 모든 배포판에서 보장

→ 배포판 무관 소스(`ip`, sysfs, `/proc`, `/etc`) 사용 전략의 정당성을 실측으로 확인했다.

### bond 실증

Ubuntu 24.04에 bond 토폴로지를 구성하여 수집 정확성을 실증했다:

| 구성 | 내용 |
|------|------|
| bond0 | active-backup 모드, 2개 dummy slave |
| bond0.200 | VLAN-on-bond (bond0 위 VLAN 서브인터페이스) |
| br_test | bridge (테스트용) |

검증 결과:

| 항목 | 결과 |
|------|------|
| bond master 수집 | [OK] bond0 수집됨 |
| slave 제외 | [OK] dummy slave 제외됨 (master sysfs 감지) |
| VLAN-on-bond 수집 | [OK] bond0.200 수집됨 |
| bridge port 제외 | [OK] bridge 하위 port 제외됨 |

### source 우선순위 체계 확정

```text
kernel sysfs > POSIX 명령 > /proc > /etc
```

- kernel sysfs (`/sys/class/net/*`): MAC, MTU, speed, operstate, master, bridge/bonding 판정
- POSIX 명령 (`ip`): IPv4 주소, default gateway, primary 판정
- `/proc`: cpuinfo, meminfo
- `/etc`: resolv.conf (DNS), os-release (system)

### 운영 해석 정책 확정

| 항목 | 해석 |
|------|------|
| `is_primary` | IPv4 main table default route device (운영 대표 IP와 동일하지 않을 수 있음) |
| `speed=null` | kernel 미보고 (bond/bridge master, 가상 NIC) |
| `dns 127.0.0.53` | stub resolver (systemd-resolved, 실제 upstream DNS가 아님) |
| policy routing / IPv6 / VRF | 미지원 |

### 결론

명령어 매트릭스 실측으로 배포판 무관 설계를 검증하고, bond 실증으로 bond master/slave/VLAN-on-bond 수집 정확성을 확인했다. source 우선순위와 운영 해석 정책을 확정하여 수집 정책 문서에 반영했다.

---

## 다음에 읽을 문서

| 다음 작업 | 문서 |
|---|---|
| 검증 라운드 결과 누적 | [13_redfish-live-validation.md](13_redfish-live-validation.md) |
| Adapter 시스템 (점수 / 새 벤더 추가) | [10_adapter-system.md](10_adapter-system.md) |
| envelope 13 필드 의미 사전 | [20_json-schema-fields.md](20_json-schema-fields.md) |

## 본 문서를 보는 법

- 시간 역순으로 누적됩니다 (최신 결정이 위쪽).
- 각 결정은 "배경 / 분석 / 결정 / 영향 / 회귀" 5절 구조를 따릅니다.
- 결정의 "왜" 가 본문이고, "무엇을 했는지" 는 git log / commit 메시지로 보완됩니다.
