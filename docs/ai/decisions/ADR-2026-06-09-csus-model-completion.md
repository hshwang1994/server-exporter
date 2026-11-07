# ADR-2026-06-09-csus-model-completion

## 상태
Accepted (2026-06-09)

## 컨텍스트 (Why)

### 사용자 명시 (2026-06-09)

> "지금 만들어진 HPE Compute Scale-up Server 3200 서버 개더링에대해서 [Redfish 모델] 구조와 동일한지 검수해라."
> (검수 후) "너가 판단하에 추가해야하는 것들이있다면 모두 구현해라. 현재 작업 중인 범위 안에서도 버그 및 개선 사항을 끝까지 찾아라."

### 검수 결과 (적대적 12-agent 검증 — refuted 0)

CSUS 3200 Redfish 모델(사용자 제시) 대비 구현 누락 5종 확정:

| 설명 모델 구성요소 | 구현 전 상태 |
|---|---|
| `Systems/<id>` = nPartition (model/serial/status/NIC MAC) | [OK] (gather_systems_multi) |
| **nPartition 부팅 순서 (Boot order)** | [없음] — fixture 에 `Boot` 있으나 엔진 무시 |
| `Chassis/<id>` 물리 + **Power** | [OK] |
| **Chassis Thermal** | [없음] — gather_thermal 함수 부재 |
| **CompositionService + ResourceBlocks** | [없음] — 전 계층 0건 |
| **Fabrics + FlexGrid (NUMAlink)** | [없음] — 전 계층 0건 |
| `Managers/<id>` = RMC (RMC/PDHC/iLO 라벨) | [OK] |
| **Manager Services/Logs (LogServices)** | [없음] — gather_bmc core 필드만 |

추가로 검수 중 발견된 연결-영역 버그 1건:
- `gather_chassis_multi` 가 chassis GET 실패 시 `continue` 로 멤버를 **drop** → `chassis_count` 가 collection 멤버 수보다 작게 under-report. `gather_systems_multi` / `gather_managers_multi` 는 append-on-fail 인데 chassis 만 불일치.

## 결정 (What)

### 결정 1: 누락 5종을 `data.multi_node` 내부 Additive 신 키로 구현

`redfish-gather/library/redfish_gather.py` 신 함수 (stdlib only — rule 10):

| 함수 | 출력 위치 | 출처 (rule 96 R1-A) |
|---|---|---|
| `gather_boot` | `multi_node.partitions[].boot` | DMTF ComputerSystem.Boot |
| `gather_thermal` + `_gather_thermal_subsystem` | `multi_node.chassis[].thermal` | DMTF Thermal.v1 + ThermalSubsystem (2020.4) fallback |
| `gather_manager_logs` | `multi_node.managers[].log_services` | DMTF LogServiceCollection |
| `gather_composition_service` | `multi_node.composition` | DMTF CompositionService/ResourceBlock + HPE CSUS 3200 Admin Guide |
| `gather_fabrics` + `_gather_fabric_members` | `multi_node.fabrics` | DMTF Fabric/Switch/Endpoint |

`_collect_multi_node_topology` 에 composition/fabrics 수집 + `summary.resource_block_count` / `summary.fabric_count` 추가.

**근거**: envelope 13 필드 / 기존 9 section path 변경 0 (rule 13 R5 / 92 R2 / 96 R1-B). `data.multi_node` 는 `manager_layout` 정의 vendor (CSUS 3200 / Superdome Flex) 만 non-null → 13 vendor 영향 0. ServiceRoot 에 링크 부재 시 graceful (composition/fabrics=null, boot/thermal={}, log_services=[]).

### 결정 2: `gather_chassis_multi` append-on-fail (일관성 fix)

chassis GET 실패 시 `continue` (drop) → `cdata = {}` 후 멤버 노출. gather_systems_multi / gather_managers_multi 와 일관. 비-dict 응답 방어 추가.

**근거**: 멀티-노드 3 collector 의 실패-경로 일관성 + `chassis_count` 가 collection 멤버 수를 정확히 반영. happy path (전 chassis 200) 변경 0 — baseline / 기존 테스트 무영향.

### 결정 3: 보조 정보 GET 실패는 silent (중복 error noise 차단)

`gather_boot` / `gather_manager_logs` 가 system/manager 를 재-GET 하는데 (gather_system/gather_bmc 가 이미 GET), 실패 시 중복 error 를 emit 하면 status 오분류 위험. 1차 리소스 GET 실패는 silent ([] / {}) 처리 — gather_system/gather_bmc 가 이미 errors[] 보고. 2차 실패 (LogServices 컬렉션 fetch 등)는 error 유지.

**근거**: status 계산 정확성 + error noise 최소화 (self-review 발견).

### 결정 4: mock fixture + baseline + 회귀 테스트 (lab 부재)

- fixture: `tests/fixtures/redfish/hpe_csus_3200/` 신 14 파일 (thermal / logservices+2 / compositionservice + resourceblocks + 3 blocks / fabrics + flexgrid + switches+2 + endpoints+2 / expansion chassis+thermal). service_root 에 Fabrics + CompositionService 링크 추가.
- baseline: `schema/baseline_v1/hpe_csus_3200_baseline.json` 에 5종 신 키 Additive 추가 (mock — 실측 아님, rule 25 R7-B).
- 테스트: `test_csus_extended_topology.py` (16) + `test_csus_fixture_replay.py` (7) 신설.

**근거**: rule 96 R1-A web sources + rule 21 R1 fixture 회귀 + rule 13 R7 `docs/contract/03-fields.md` 동기화.

## 결과 (Impact)

### 정합성 검증

- **rule 13 R5 envelope 13 필드**: 변경 0 — 신 데이터 전부 `data.multi_node` 내부 [PASS]
- **rule 13 R7 `docs/contract/03-fields.md` 동기화**: 7-bis 절 + "확장 컴포넌트" 표 갱신 [PASS]
- **rule 22 Fragment 철학**: normalize_standard.yml multi_node wholesale passthrough — task 변경 0 [PASS]
- **rule 92 R2 Additive only**: 기존 path 변경 0 / 신 key 추가만 (gather_chassis_multi 는 실패-경로만 변경) [PASS]
- **rule 96 R1-A web sources**: DMTF DSP0266 + HPE CSUS 3200 Admin Guide + Superdome Flex 상속 origin 주석 [PASS]
- **rule 12 R1 vendor 경계**: 신 함수 vendor-agnostic (표준 Redfish 리소스) — verify_vendor_boundary 통과 [PASS]
- **rule 10 stdlib only**: 신 import 0 [PASS]

### 회귀 검증

- 신 CSUS 테스트: 38 PASS (16 extended + 7 replay + 15 기존)
- 전체: pytest 996 passed / 6 skipped / 2 failed (2 = `tests/e2e_browser` live-Jenkins 네트워크 timeout — 본 변경과 무관, 환경 의존)
- output_schema_drift_check: 정합 (sections=10, 신 canonical section 0)
- verify_vendor_boundary / verify_harness_consistency: PASS

### 영향 vendor 매트릭스

| Vendor | 영향 |
|---|---|
| HPE CSUS 3200 (`rmc_primary`) | 5종 신 컴포넌트 활성 |
| HPE Superdome Flex (`rmc_primary_ilo_secondary`) | 동일 — ServiceRoot 링크 노출 시 활성 |
| HPE iLO 4~7 / Dell / Cisco / Lenovo / Supermicro / Huawei / Inspur / Fujitsu / Quanta | `data.multi_node = null` — 변경 0 |

## 대안 비교 (Considered)

| 영역 | 대안 | 거절 사유 |
|---|---|---|
| Boot 위치 | `data.system.boot` (전 vendor) | 9 baseline + emulator golden 5 + field_dictionary 변경 → blast radius 大. multi_node 내부 채택 |
| Composition/Fabrics 범위 | 전 vendor 수집 | 범위 외 + 13 vendor 회귀 위험. CSUS 한정 (manager_layout gate) 채택 |
| boot/logs GET | gather_system/gather_bmc 가 raw 반환하도록 refactor | 단일 노드 path + 13 vendor signature 변경 위험. 별도 GET (silent on fail) 채택 — 약간의 중복 round-trip 비용 (NEXT_ACTIONS 최적화 후보) |
| Fabric type | NUMAlink enum 강제 | DMTF Fabric.FabricType enum 에 NUMAlink 부재 → placeholder (PCIe) + 사이트 실측 정정 |

## Rollback

1. `git revert` (본 cycle commit)
2. fixture/baseline 신 키 제거 + 테스트 2 파일 삭제
3. adapter vendor_notes 신 플래그 / diagnosis message revert

Rollback trigger: pytest 회귀 5건+ / 사용자 명시 보류.

## NEXT_ACTIONS (lab 도입 후 — rule 50 R2 단계 10 / 96 R1-C)

| # | 항목 |
|---|---|
| C9 | CompositionService/ResourceBlock 실 schema 실측 (RB↔chassis 매핑 / Processors·Memory 표현) |
| C10 | Fabrics/FlexGrid 실 FabricType / Switch SwitchType / Endpoint EndpointProtocol (NUMAlink 표기) |
| C11 | Chassis Thermal 실 sensor 명 / ThermalSubsystem vs Thermal 펌웨어 분기 |
| C12 | RMC LogServices 실 ID (IML/IEL 추정) / OverWritePolicy |
| C13 | per-partition Boot.BootOrder 실 표현 (BootString vs BootOption ref) |
| C14 | (최적화) gather_boot / gather_manager_logs 재-GET 제거 — gather_system/gather_bmc raw 재사용 |

## 검수 후속 fix (적대적 review 4 loop — 본 cycle 내)

구현 후 적대적 multi-agent review 4 loop (≈30 agent) 로 자기검증. genuine production 버그는 수렴(6→5→1→2, 마지막 2건은 동일 root). 전부 fix + 회귀 테스트:

| Loop | 확정 | fix |
|---|---|---|
| 1 (15 agent) | 6 LOW/MED | chassis append-on-fail 시 doomed Power/Thermal sub-GET 차단 / composition enabled malformed-200 → None / boot·logs 1차 GET 실패 silent / replay 멤버 fixture 보강 + 단언 / mock_v1 stale·orphan 정정 |
| 2 (8 agent) | 5 LOW | baseline Expansion2 power null→populate / jsonc Expansion1·2 thermal + secondary manager log_services / _gather_thermal_subsystem·_gather_power_subsystem `_capped` / composition count 가정 주석 |
| 3 (5 agent) | 1 LOW (genuine) | `_classify_rmc_label` layout-default 'RMC' → 첫 Manager 한정 (`is_first`) — 다중 RMC 오라벨 + name/role 모순 차단 |
| 4 (5 agent) | 2 (genuine, 동일 root) | name(body Id) vs role(URI segment) **id source 분리** → 동일 id(`m['id']`) 사용으로 통일. `name=='RMC' ⇔ role=='primary'` 구조적 보장 |

검증 (각 loop 후): pytest 1005 passed / 5 skipped (e2e_browser 2 = live-Jenkins 무관) + output_schema_drift / vendor_boundary / harness gate PASS.

## 관련

- 검수 워크플로: 6 컴포넌트 × (verify + adversarial refute) — refuted 0
- rule: `10`, `12 R1`, `13 R5/R7`, `22`, `25 R7-A-1/R7-B`, `50 R2`, `70 R8`, `92 R2`, `95 R1`, `96 R1-A/R1-B/R1-C`
- ADR 선례: `ADR-2026-05-12-csus-rmc-multi-node.md` (data.multi_node 컨테이너 신설)
- 코드: `redfish-gather/library/redfish_gather.py` (gather_thermal/_gather_thermal_subsystem/gather_boot/gather_manager_logs/gather_composition_service/gather_fabrics/_gather_fabric_members)
- 정본: `docs/contract/03-fields.md` 7-bis, `docs/operate/06-rmc-activation.md`
- 테스트: `tests/unit/test_csus_extended_topology.py`, `tests/unit/test_csus_fixture_replay.py`

## 승인 기록

| 일시 | 승인자 | 대상 | 비고 |
|---|---|---|---|
| 2026-06-09 | hshwang1994 | 누락분 5종 구현 + 연결 영역 버그/개선 ("너가 판단하에 추가해야하는 것들이있다면 모두 구현해라") | 검수 → 구현 일괄 승인 |

## 2026-10-27 정정 기록 (2차 Mock 실측 — 섀시 Power/Thermal 가정 · composition count)

- 검수표 "`Chassis/<id>` 물리 + Power [OK]" 와 `gather_chassis_multi` 의 고정 경로(`Power`/`PowerSubsystem`/`Thermal`/`ThermalSubsystem`) 요청은 **집합 섀시(RackGroup · Rack1)에는 성립하지 않는다**
  — 실측 CSUS 3200 RMC 7대 모두 그 두 섀시 본문에 navigation property 가 없고 요청은 404 였다(노드 섀시 r001u01 은 `PowerSubsystem`/`ThermalSubsystem` 만). 2026-10-27 부터 섀시 본문의 링크가
  있을 때만 요청한다(링크 없음 = 404 와 같은 미지원 분류 · 요청 0). 본문을 모르면 종전 순서(C11 폴백)다.
- `CompositionService/ResourceBlocks` 의 `Processors[]/Memory[]` 는 실 RMC 가 노출하지 않는다 — `resource_block_count` · `composition_state` · `chassis[]` · `computer_systems[]` 는 실측과 맞고
  `processor_count/memory_count` 는 null 로 낸다(FIX 6, 종전 0 날조). `Fabrics` FlexGrid 는 실측 switch 2 · endpoint 0, `fabric_type null`.
- C9~C14 중 C9(RB↔chassis 1:1) · C11(ThermalSubsystem 경로) 은 2차 실측으로 확인, C10(NUMAlink enum) 은 그대로 미해결. 근거: `tests/evidence/2026-10-27-redfish-mock2-impl/07-csus-chassis-fc.md`.
