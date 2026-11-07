# 07 — WP7 (C5): CSUS 섀시 링크 gating · composition count · FC HBA 카드 조건 notice · DIMM 속도 의미 (01-multi_node-006≡05-power-004 · 01-multi_node-007 · 03-storage-004 · 02-memory-002 · 01-multi_node-003)

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027`. 실측: 용인 2차 csus3200_01/02/03(RMC, 2026-10-21 캡처) + 1차 CSUS 4대(RMC 1.75.108). 사용자 결정 11 **A안**(2026-10-27 2차·3차 검토) · FIX 3 · FIX 5 · FIX 6.
- 원천(`tests/fixtures/redfish/real_hpe_csus3200_01/recording.json` 기준, 다른 6대 같음):
  - `Chassis/RackGroup`(ChassisType RackGroup) · `Chassis/Rack1`(Rack) 본문: `Power`·`PowerSubsystem`·`Thermal`·`ThermalSubsystem`·`EnvironmentMetrics` 링크 **없음** → 종전 코드는 고정 경로로 8건을 요청해 404.
    `Chassis/r001u01`(RackMount) 본문: `PowerSubsystem`·`ThermalSubsystem`·`Sensors`·`Drives`·`PCIeDevices`·`NetworkAdapters` 만 — legacy `Power`/`Thermal`·`EnvironmentMetrics` 없음 → 종전 코드는 그 셋을 system 경로·chassis_multi 경로에서 각 1회(총 6건) 요청해 404.
  - `CompositionService/ResourceBlocks/r001u01` 키 = `CompositionStatus · ComputerSystems · Id · Links · Name · ResourceBlockType · Status …` — DMTF `Processors[]`/`Memory[]` idRef 배열 **없음** → 종전 `processor_count/memory_count = 0`.
  - `Chassis/r001u01/PCIeDevices/{11,14}`(HPE SN1100Q 16Gb 2p FC HBA) `Status.Conditions[]` 11건 — `MessageId` 만(`Message` 본문 없음): `H3Alert.1.8.ResourceReallocated · ResourceReconfigured · ResourceAcquitted · LinkUp(Timestamp 2026-10-16T01:06:26Z / 14 는 2026-10-21T01:16:06Z) · PcieErrorIsolationExited · PcieCardHasCpu · PciePerformanceOk · NotBlockedByOtherDisabled · PcieLinkTrainingOk · ABMCPowerOnSuccess · ABMCReady`, `MessageArgs[0]` = 슬롯 라벨(`rack1/chassis_u1/cpu2/io_slot11`). **같은 `LinkUp` 이 RAID `PCIeDevices/3`(HPE SR3258p-16i/e) 와 Mellanox NIC(1·8·9·16) 에도 있다.**
  - `NetworkAdapters/PCIeCard{11,14}` `Controllers[0]`: `FirmwarePackageVersion` 없음 · `Links.PCIeDevices` 정확히 1건(→ PCIeDevices/11·14). NIC 카드도 같은 모양(→ 1·8·9·16). RAID 는 어떤 NetworkAdapter 도 가리키지 않는다. FC Port 리소스 키는 `FibreChannel.AssociatedWorldWideNames · Id · Name` — `LinkStatus` 없음(2026-10-19 행과 같음).
  - DIMM `…/Memory/0000000101000074`: `OperatingSpeedMhz 3200`, `Oem.Hpe.Label "32GB 1Rx4 PC5-6400B-RC1"`, PartNumber `M321R4GA0EB2-CCPKC`, DDR5 RDIMM — H3 RMC 의 값은 I/O 버스 클럭(iLO 7 · XCC 3 · iDRAC 는 MT/s).

## 1. 규칙 (모듈 · adapter · 문서)

| 이슈 | 규칙 | 구현 |
|---|---|---|
| 01-multi_node-006 ≡ 05-power-004 | 섀시 본문(`cdata`)을 받은 경로에서 **navigation property 가 있을 때만** 요청: `Power`/`PowerSubsystem`(또는 `Thermal`/`ThermalSubsystem`) 둘 다 없으면 GET 없이 `{}` + 404 와 같은 미지원 분류(`_is_404_only_error`), 신 링크만 있으면 legacy GET 생략, `EnvironmentMetrics` 링크 없으면 그 GET 도 없음. 본문을 모르면(`chassis_body=None`) 종전 순서. 벤더 이름 분기 0 | `_chassis_has_link` · `gather_power(..., chassis_body)` · `gather_thermal(..., chassis_body)` · `_gather_power_subsystem(..., chassis_body)`(EnvironmentMetrics) · `gather_chassis_multi`(cdata 전달) · `_gather_power/thermal_for_system(..., chassis_bodies)`(`gather_system` 이 받은 섀시 본문을 `bios_link` out-param 으로 재사용 — 전역 없음) |
| 01-multi_node-007 (FIX 6) | `ResourceBlock.Processors`/`Memory` 가 list 가 아니면 count 는 `null` (0 날조 금지) | `gather_composition_service` |
| 03-storage-004 (결정 11 A안 · 3차 검토 3중 판별) | 값 규칙 불변: Port `LinkStatus` 있으면 그 값, 없으면 `down`(`_hba_link_status`/`_hba_link_missing`). **카드 조건을 포트 값으로 바꾸지 않는다.** 다음 셋이 모두 성립할 때만 기존 notice `네트워크 카드 X: FC 포트 … 링크 상태 미제공, down 으로 기록 (storage.hbas link_status)` 끝에 ` — 링크 단절을 확인한 값 아님; 카드 <MessageArgs[0]> 조건 LinkUp\|LinkDown(<Timestamp>, 카드 단위)` 를 덧붙인다: (1) 이 카드에서 `hbas` 가 생성됐고(`out_fc_added` — NDF 경로·포트 경로 둘 다) 이더넷 포트 0(`eth_port_n == 0`) (2) PCIeDevice 본문이 **바로 이 어댑터**의 `Controllers[0].Links.PCIeDevices`(정확히 1건)로 CSUS-R16 경로에서 받은 응답(`r16_pcie_body` — 섀시 PCIeDevices 열거·캐시 조회 안 함 → RAID 자동 제외) (3) `MessageId` 첫 세그먼트가 adapter 선언 `pcie_port_link_condition_registries` 에 있고 마지막 세그먼트가 `LinkUp`/`LinkDown`(`PcieLinkTrainingOk` 등 제외). 추가 요청 0 · 새 JSON 필드 0 · `LogService/Oem/Iel` 미사용 | `_pcie_port_link_condition(pcie_body, registries)` · `_collect_one_network_adapter(..., pcie_link_registries)` · `gather_network_adapters_chassis(..., pcie_link_registries)` · `_collect_all_sections(..., pcie_link_registries)` · `main()` argument_spec `pcie_port_link_condition_registries`(list[str], default None) · `site.yml` `_rf_adapter_pcie_link_registries` ← `vendor_notes.pcie_port_link_condition_registries` → `collect_standard.yml`/`try_one_account.yml` 모듈 인자 · `adapters/redfish/hpe_csus_3200.yml` `pcie_port_link_condition_registries: ["H3Alert"]`(origin 주석: 등록부 1.8 정의 · Mock 경로 · 확인일) |
| 02-memory-002 (FIX 3) | 코드 0 — `slots[].speed_mhz` 는 `OperatingSpeedMhz` 원값, 보정 없음. 벤더별 의미를 계약에 명시 | `docs/contract/03-fields.md` 6.2 · `EXTERNAL_CONTRACTS.md` 2026-10-27 행 |
| 01-multi_node-003 (FIX 5) | `schema/baseline_v1/hpe_csus_3200_baseline.json` 을 실측(csus3200_01 Tier 1 봉투)으로 교체 + 소비 테스트 재작성 — **WP11 뒤 실행**(bmc/diagnosis 변경이 봉투에 들어가야 1회로 끝남) | 이 WP 에서는 변경 0(Plan §4 WP7 명시) |

## 2. 테스트 (Tier 0)

- 신규 `tests/unit/test_redfish_csus_chassis_fc.py` **18건**: 긍정 — csus3200_01(PCIeCard11 `io_slot11` 2026-10-16T01:06:26Z · PCIeCard14 `io_slot14` 2026-10-21T01:16:06Z) · csus3200_03 · 1차 CSUS 01(H3Alert.1.7) 에서 notice 끝에 카드 조건 + `hbas[].link_status` 전부 `down` 유지; 음성 — csus3200_02(FC 없음 → 문구·값 불변), 등록부 미선언(None / `OtherRegistry`), `PcieLinkTrainingOk` 만 남긴 변형, `Links.PCIeDevices` 2건 변형, RAID `PCIeDevices/3` 의 LinkUp 이 어떤 notice 에도 섞이지 않음, NIC 카드(이더넷 포트) 문구 없음, Port `LinkStatus` 보유 장비(DL380 Gen12 · SR650 V4 · Dell) 문구 없음 + GOLDEN_KEYS 데이터 동일, LinkDown + Timestamp 없음 합성(`조건 LinkDown(Timestamp 없음, 카드 단위)`, **실측 대체 아님**); gating — CSUS 고정 경로 11개 요청 소멸 · `PowerSubsystem/ThermalSubsystem` 은 요청, 합성 4분기(본문 없음/링크 없음/신 링크만/legacy 링크), 다른 벤더 요청 다중집합 == `request_budget`; composition — CSUS recording null + 합성 2분기(배열 있음 → 길이, 없음 → null); 헬퍼 단위.
  - 테스트 보조 `emulator_harness.run_gather(..., pcie_link_registries=None)`(main() 미러 인자 1개 추가) · `tier2_replay.py --pcie-link-registries`(notice 만 영향 — GOLDEN_KEYS 밖).
- 기존 묶음: `test_hpe_csus_multi_node` · `test_csus_mirror_audit_fixes` · `test_csus_fixture_replay` · `test_redfish_power_off_host` · `test_redfish_csus_single_server_render` 등 **210 passed**(integration 2종 포함) · `tests/integration -m "not live"` **497 passed** · `tests/e2e tests/regression` **1094 passed** · `tests/unit` 전체 **5118 passed · 33 skipped · 0 failed**(25분 2초) (`tier0/*_after_wp7.log`). WSL `ansible-playbook --syntax-check` 3채널 PASS · 엔진 테스트 23 passed.

## 3. Golden · 요청 예산 (FIX 9 — `golden-changes.md` G-15)

- CSUS 4세트 `multi_node.composition.resource_blocks[0].processor_count/memory_count` `0 → null`(다른 경로 차이 0, 15 fixture 재생으로 확인). 요청 예산 CSUS 4세트 **-11 distinct / -14 total**(`path_set_delta.removed` 11 경로 · note), 다른 11 fixture 불변.

## 4. Tier 1 after (18 label, `tier1-after-WP7/` ↔ `tier1-after-WP6/`, `_allow.json`)

- 18/18 rc 0 · success · errors 0 (`run_meta.json`, build `mirror-replay-wp7-after`). `_diff_vs_after_wp6.md`(허용목록 `_allow.json` 4항목): **허용목록 밖 차이 0 · 요청 미설명 0**.
- 요청 집합: CSUS 7 label 전부 **-11 distinct**(RackGroup/Rack1 `Power·PowerSubsystem·Thermal·ThermalSubsystem` 8 + r001u01 `Power·Thermal·EnvironmentMetrics` 3 — 총 -14 건: csus3200_01 200→186 · _02 148→134 · _03 184→170 · r1_01/02 145→131 · r1_03/04 214→200), 추가 0. 비-CSUS 11 label 요청 집합 불변.
- 값 변화: CSUS 7 label `data.multi_node.composition.resource_blocks[0].processor_count/memory_count` `0 → null`(FIX 6). 그 밖 `data.*` 18 label 바이트 동일(`hbas[].link_status` 는 CSUS 6 label 전부 `down` 그대로 — A안).
- notice: FC HBA 를 가진 CSUS 6 label 의 "링크 상태 미제공" notice 끝에 카드 조건이 붙었다(건수 불변 — csus3200_01 2 · _03 2 · r1_01 2 · r1_02 2 · r1_03 4 · r1_04 4 = 16건, 실측 Timestamp 그대로: 예 csus3200_01 PCIeCard11 `rack1/chassis_u1/cpu2/io_slot11` LinkUp 2026-10-16T01:06:26Z · PCIeCard14 `…/cpu3/io_slot14` 2026-10-21T01:16:06Z; 1차 01/02 PCIeCard10·15 2026-05-07, 1차 03/04 PCIeCard2·7·10·15 2026-06-11). 전부 `LinkUp`(LinkDown 0). 미러 원문의 카드 링크 조건은 49건(csus3200_01 7 · _02 3 · _03 7 · r1_01 7 · r1_02 7 · r1_03 9 · r1_04 9, 전부 LinkUp)이다 — 종전 '분석 Round 의 59 관측과 일치' 는 감사 원문 수치를 옮긴 것(2026-10-28 정정). **csus3200_02(FC 없음) notice 2건 불변**, NIC/RAID 카드 문구 0, 비-CSUS notice 불변.
- INV-5(interfaces MAC 6옥텟 ∧ FC/IB 주소 아님) 18 label 위반 0 · interfaces 수 불변. 디스크·FC 포트 개수 정합(전수 미러 노출 수 ↔ 최종 JSON) **18/18 PASS · UNEXPLAINED 0**(csus3200_02 FC 0 · dl380_gen12_03 디스크 0 · r1_CSUS 01/02 디스크 0 은 수집도 0).

## 5. 처분

| 이슈 | 처분 |
|---|---|
| 01-multi_node-006 ≡ 05-power-004 | FIXED (섀시 본문 링크 gating — CSUS 7대 요청 -14, 비-CSUS 요청 불변) |
| 01-multi_node-007 | FIXED (FIX 6 — count null) |
| 03-storage-004 | FIXED (A안 — 카드 조건 참고 notice, 값·필드·요청 불변) + MOCK_LIMITATION (포트 단위 링크는 RMC 가 주지 않아 재생으로 확정 불가; 카드 조건 49건(2026-10-28 정정 — 종전 59) 전부 LinkUp 이라 LinkDown 분기는 합성만) |
| 02-memory-002 | DOC_CORRECTED (FIX 3 — 원값 보존, 벤더 의미 계약 명시) |
| 01-multi_node-003 | HOLD→WP11 뒤 FIXED 예정 (FIX 5 — 실측 baseline 교체는 bmc/diagnosis 변경 뒤 1회) |

## FIX 5 이행 (WP11 뒤, 2026-10-27)

- `schema/baseline_v1/hpe_csus_3200_baseline.json` 을 **2차 Mock csus3200_01 의 Tier 1 실 봉투**(`tier1-after-WP11/csus3200_01/gather_output.json`, build `mirror-replay-wp11-after`, RMC 1.77.30-20260911_061319 · Redfish 1.19.0 · 캡처 2026-10-22)로 in-place 교체했다. 수정 2곳만: 재생 서버 주소 `127.0.0.1` → Manager NIC 실측 주소 `11.65.23.24`(`ip` · `correlation.host_ip`), `diagnosis.details.baseline_origin` 에 출처·재생 한계·수정 지점 기재(실측 표기). 그 밖 바이트 동일(G-25).
- 실 구조: 1 nPartition(`Partition0`, serial `SGHD4MGNLH-000`) · 1 Manager(`RMC` primary) · 3 Chassis(`RackGroup`/`Rack1`/`r001u01` — 전원·온도는 `r001u01` 만) · composition 1 block(count null — FIX 6) · fabrics FlexGrid(switch 2 · endpoint 0) · 디스크 4 · FC HBA 4 == FC 포트 4 · `sections.system not_supported` + hostname `yicdspdb01`(FIX 4) · `cpu.logical_threads` 없음(FIX 1). 종전 합성본(3 파티션 · 4 Manager · Base/Expansion · `MOCK-CSUS-P0` 시리얼 · 합성 PSU/WWPN)은 git 이력에만 남는다.
- 같은 커밋: `tests/regression/conftest.py` registry `hpe_csus_3200_redfish_MOCK` → `hpe_csus_3200_redfish`(주석 정정), `tests/regression/test_csus_mock_consistency.py` 를 실측 구조 가드(요약 카운트 == 길이 · 1/1/3 · composition/fabric 모양 · origin 실측·MOCK 시리얼 없음 · 디스크/FC 개수 정합 · FIX 1/4 계약)로 재작성(파일 이름은 이력상 유지), `test_cross_channel_consistency.py` T10 주석 · `test_hba_ib_canonical.py` 머리말(FC 2 → 4) 정정. `test_vendor_output_display.py` D3(`hpCsus`) · `tests/e2e/test_output_schema.py` · `test_failure_code_contract.py` 는 교체본으로 그대로 PASS.
- 문서: `schema/baseline_v1/README.md`(표 행 · "합성 기준선 0 개"), `docs/contract/03-fields.md` §9 예시를 실측 구조로 교체 + "Lab 부재 주의"/"현재 mock fixture" 문단 정정, 합성 fixture `tests/fixtures/redfish/hpe_csus_3200/README.md` 에 "합성 설명 모델" 명시, `docs/ai/contracts/serial-number.md`(HBA serial 실측 null · 시리얼 사례), `NEXT_ACTIONS` BASE-01 2곳 DONE, ADR-2026-05-12 결정 6 이행 기록, `LAB_PENDING_MATRIX` C2, decision-log.
- 처분: 01-multi_node-003(ADR 결정 6 미이행) → FIXED. 합성 `schema/output_examples/redfish_hpe_csus_3200.jsonc` 는 주석 예시(README: "기준선과 장비가 정확히 같지 않을 수 있다")로 두었다 — 실측 구조로 바꾸는 일은 별도(OBSERVATION).

## 2026-10-28 정정 (독립 검증 부록 A)

| 위치 | 이전 | 정정 | 근거 |
|---|---|---|---|
| 4절 notice 카드 조건 수 | 분석 Round 59 관측과 일치 | 49(7/3/7/7/7/9/9) · 전부 LinkUp | `../2026-10-28-redfish-mock2-review-fix/tools/csus_card_conditions.py` — PCIeDevice `Status.Conditions[].MessageId` `H3Alert.<ver>.LinkUp/LinkDown`, 같은 `@odata.id` 1번 |
| 5절 03-storage-004 | 59 카드 조건 | 49 | 위와 같음. A안 값 · notice 16건 · 요청은 그대로(새 Tier 1 차이 0) |
