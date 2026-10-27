# Golden 정정 원장 (FIX 9 — 검증된 항목만, before/after·원천·원인)

> `tests/fixtures/redfish/real_*/expected_output.json`(모듈 산출 GOLDEN_KEYS) 과 `schema/baseline_v1/*.json` 에 손댄 모든 항목을
> 여기 적는다. 전면 재생성 금지 — 각 행은 원천 경로와 원인이 있어야 한다. 2026-10-27 WP1 부터 누적.

| # | WP | fixture / baseline | 경로 | before | after | 원천 | 원인 |
|---|---|---|---|---|---|---|---|
| G-01 | WP1(d) | `real_dell_r740` | `data.bios.current.attributes` | `null` | dict 380 keys | 1차 전수 미러 `DELL_R740/01/redfish/v1/Systems/System.Embedded.1/Bios/index.json`(_status 200, `#Bios.v1_2_0.Bios`) → recording `get::Systems/System.Embedded.1/Bios` 추가 | replay-miss: gather 는 `Bios.@odata.id` 를 1회 요청(예산 `Systems/System.Embedded.1/Bios x1`)하지만 축약 recording 에 응답이 없어 404 → null. 요청 수 불변 |
| G-02 | WP1(d) | `real_hpe_dl380` | `data.bios.current.attributes` | `null` | dict 292 keys | 1차 전수 미러 `HPE_DL380/01/redfish/v1/Systems/1/bios/index.json`(_status 200, `#Bios.v1_2_3.Bios`, 링크 소문자 `/redfish/v1/systems/1/bios`) → recording `get::systems/1/bios` 추가 | 같음(예산 `systems/1/bios x1`) |
| G-03 | WP1(d) | `real_lenovo_sr650` | `data.bios.current.attributes` | `null` | dict 1223 keys | 1차 전수 미러 `Lenovo_SR650/01/redfish/v1/Systems/1/Bios/index.json`(_status 200, `#Bios.v1_2_0.Bios`) → recording `get::Systems/1/Bios` 추가 | 같음(예산 `Systems/1/Bios x1`) |

- G-01~03 검증: 추가 전후 모듈 산출을 전체 평탄 비교 → 차이는 `data.bios` 뿐(각 N+1 경로). `test_real_capture_replay`·`test_request_budget`·`test_inventory_count_parity`(해당 3세트 + 2차) PASS. `request_budget.json` 3종 불변.
- 1차 `real_hpe_csus3200` 은 recording 에 `get::Systems/Partition0/Bios` 가 이미 있어 변경 없음.

### WP3 (C2 — 전원 Off 호스트 · 빈 DIMM 슬롯 · Absent PSU placeholder · 비-Enabled 센서) — 2026-10-27

| # | WP | fixture / baseline | 경로 | before | after | 원천 | 원인 |
|---|---|---|---|---|---|---|---|
| G-04 | WP3 | `real_hpe_dl380_gen12_03` | `data.memory.slots[]` | 32 항목(빈 슬롯 16 포함: `capacity_mb 0`, 제조사/부품/시리얼 null) | **16 항목**(장착 DIMM 만), `total_mib` 524288 불변 | recording `Systems/1/Memory/proc1dimm11` 등 16건: `Status` 없음 · `CapacityMiB: 0` · Manufacturer/PartNumber/SerialNumber null(DeviceLocator 만) | 빈 슬롯은 DIMM 이 아니다 → 제외 + notice "빈 DIMM 슬롯 16개 제외 (…)" |
| G-05 | WP3 | `real_hpe_dl380_gen12_03` | `data.power.power_supplies[0..1].{power_capacity_w, firmware_version}` | `0`, `"0.00"` ×2 | `null`, `null` ×2 (`state: Absent` · `health: Warning` 유지) | recording `Chassis/1/Power.PowerSupplies[]`: `Status.State Absent`, `PowerCapacityWatts 0`, `FirmwareVersion "0.00"` | 미장착 슬롯의 0 W·"0.00" 은 값이 아니라 placeholder. `power_control.power_capacity_watts 1600` 은 BMC 가 준 값이라 불변 |
| G-06 | WP3 | `real_hpe_dl380_gen12_03` | `data.thermal.temperatures[0..41].reading_celsius` · `fans[0..5].reading` | 전부 `0` | 전부 `null` (`state: UnavailableOffline` · `upper_critical` 유지) | recording `Chassis/1/Thermal`: 42 센서·6 팬 전부 `Status.State UnavailableOffline`, reading 0 (호스트 PowerState Off) | Enabled 가 아닌 센서의 0 은 측정값이 아니다 → null. 전원 Off 는 notice 1건 |
| G-07 | WP3 | `real_hpe_dl380_gen12_01` / `_02` / `_04` | `data.thermal.temperatures[*].reading_celsius` (State Absent 항목만) | `0` ×7 / ×8 / ×8 | `null` ×7 / ×8 / ×8 (Enabled 센서 49/36/46 건 값 불변) | recording `Chassis/1/Thermal` Temperatures `Status.State Absent`, `ReadingCelsius 0` | 미장착 슬롯 센서의 0 °C 는 placeholder (WP6 에서 Absent 항목 자체를 제외) |
| G-08 | WP3 | `real_hpe_dl380` (1차) | `data.thermal.temperatures[*].reading_celsius` (State Absent 9건) | `0` ×9 | `null` ×9 (Enabled 43 건 불변) | 같음 (1차 iLO 7 1.20.00) | 같음 |

- G-04~G-08 검증: 15 real_* fixture 전부 재생해 평탄 비교 — 바뀐 경로가 위 다섯 fixture 의 위 경로뿐임을 확인한 뒤 썼다(CSUS 4 · Lenovo 5 · Dell 1 = 차이 0; CSUS ThermalMetrics 는 Status 가 없어 규칙이 닿지 않는다). 요청 예산 불변.

### WP5 (C4 — Lenovo XCC3 응답 모양) — 2026-10-27

| # | WP | fixture / baseline | 경로 | before | after | 원천 | 원인 |
|---|---|---|---|---|---|---|---|
| G-09 | WP5 | `real_lenovo_sr650`(1차) · `real_lenovo_sr650_v4_01..04` | `data.firmware[]` | 26 · 28 · 30 · 40 · 30 항목 (`-Pending` 빈 슬롯 2 · 4 · 4 · 4 · 4 — `version null`, `pending true`) | **24 · 24 · 26 · 36 · 26** 항목 (빈 슬롯 제외, 그 밖 항목 값 불변 — 인덱스만 이동) | recording `UpdateService/FirmwareInventory/{BMC-Primary,UEFI,HPM-FPGA,Drive_Backplane_…_PSoC}-Pending`: `Status.State Disabled` · `Version ""` | 예정된 업데이트가 없는 스테이징 자리(placeholder) → 제외 + notice "Disabled · Version 없음(예정된 업데이트 없음) — 목록에서 제외" (04-firmware-006). Version 이 있는 pending 은 보존 |
| G-10 | WP5 | `real_lenovo_sr650` · `_v4_01..04` | `data.memory.slots[*].locator` (16 · 2 · 2 · 16 · 8 건) | `"32"`, `"23"` … (MemoryLocation.Slot 문자열) | `"DIMM 32"`, `"DIMM 23"` … (`Location.PartLocation.ServiceLabel`) | recording `Systems/1/Memory/<n>`: `DeviceLocator null`, `ServiceLabel "DIMM 23"`, `MemoryLocation.Slot 23` | 순서 DeviceLocator → ServiceLabel → str(Slot) (02-memory-003). Dell/iLO(DeviceLocator)·CSUS(Slot 0 → ServiceLabel) 불변 |
| G-11 | WP5 | `real_lenovo_sr650_v4_01..04` | `data.power.power_supplies[0..1].model` | `"CRPS1300D5    "` | `"CRPS1300D5"` | recording `Chassis/1/Power.PowerSupplies[].Model` 패딩 공백 | 문자열 strip (05-power-003). 1차 `FSP006-EL0G` 는 공백이 없어 불변 |
| G-12 | WP5 | `real_lenovo_sr650` · `_v4_01..04` | `data.system.oem.machine_type` · `led_indicator` | `null` · `null` | `"7DGD"` · `"Off"` | recording `Systems/1.SubModel "7DGD"` · `IndicatorLED "Off"` (Chassis.Oem.Lenovo 에 MachineType/LEDIndicators 없음) | chassis OEM 이 비면 System 값으로 채움(원천 있는 2키). 다른 oem 키는 그대로(null 유지 — 원천 없음) |

- G-09~G-12 검증: 15 fixture 전부 재생 → 바뀐 경로는 Lenovo 5세트의 위 네 묶음뿐(CSUS 4 · DL380 5 · Dell 1 차이 0). 요청 예산 불변. 호스트 EthernetInterfaces 의 FC 제외(03-network-001)는 normalize 층이라 모듈 golden 에 없다 — Tier 1 봉투(`tier1-after-WP5/`)와 INV-5 로 확인.
| G-13 | WP5 | `dmtf_rackmount1`(DMTF 공개 mockup, baseline 아님) | `data.memory.slots[0..2].locator` | `"1"`, `"2"`, `"3"` (Slot) | `"DIMM 1"`, `"DIMM 2"`, `"DIMM 3"` | recording `Systems/437XR1138R2/Memory/DIMM1..3`: `DeviceLocator` 없음, `Location.PartLocation.ServiceLabel "DIMM n"`, `MemoryLocation.Slot n` | G-10 과 같은 규칙(ServiceLabel 우선) — 표준 mockup 도 같은 순서를 따른다 |

### WP6 (C10 — 전원·온도 의미) — 2026-10-27

| # | WP | fixture / baseline | 경로 | before | after | 원천 | 원인 |
|---|---|---|---|---|---|---|---|
| G-14 | WP6 | `real_hpe_dl380`(1차) · `real_hpe_dl380_gen12_01/02/04` | `data.thermal.temperatures[]` | 52 · 56 · 44 · 54 항목 (State Absent 9 · 7 · 8 · 8 건은 WP3 이후 `reading_celsius null`) | **43 · 49 · 36 · 46** 항목 (Absent 항목 제외, 그 밖 항목 값 불변 — 인덱스 이동) | recording `Chassis/1/Thermal.Temperatures[]` `Status.State Absent` (iLO 7 미장착 슬롯 센서, `ReadingCelsius 0`) | 미장착 슬롯 센서는 항목이 아니다 → 제외 + notice "Absent 센서 N건 제외 (온도 N · 팬 0) — 미장착 슬롯" (05-thermal-001). gen12_03(UnavailableOffline) · CSUS(Status 없음) · Lenovo · Dell 불변 |

- G-14 검증: 15 fixture 전부 재생 → 바뀐 경로는 DL380 4세트의 `data.thermal.temperatures[*]` 뿐. 요청 예산 불변. PSU 입력 0 관측·소비전력 폴백 순서·ThermalSubsystem 폴백은 모듈 golden 을 바꾸지 않는다(notice 는 GOLDEN_KEYS 밖, 18 label 에서 폴백 미발동).

### WP7 (C5 — CSUS 섀시 링크 gating · composition · FC HBA 카드 조건) — 2026-10-27

| # | WP | fixture / baseline | 경로 | before | after | 원천 | 원인 |
|---|---|---|---|---|---|---|---|
| G-15 | WP7 | `real_hpe_csus3200`(1차) · `real_hpe_csus3200_01/02/03` | `multi_node.composition.resource_blocks[0].processor_count` · `memory_count` | `0` · `0` | `null` · `null` | recording `CompositionService/ResourceBlocks/r001u01`: 본문에 `Processors`/`Memory` 키 자체가 없음(키 목록 `CompositionStatus · ComputerSystems · Links · ResourceBlockType · Status …`) | 원천 배열이 없으면 세지 않는다 — 0 은 "장착 0" 이 아니라 "집계 원천 없음" (FIX 6). 다른 composition 키 불변 |

- G-15 검증: 15 real_* fixture 전부 재생(`test_real_capture_replay` · `test_request_budget`) → 바뀐 golden 은 CSUS 4세트의 위 두 경로뿐(DL380 5 · Lenovo 5 · Dell 1 차이 0). 요청 예산은 CSUS 4세트만 **-11 distinct / -14 total**(`request_budget.json` `path_set_delta.removed` 11 경로 · note 기재): RackGroup/Rack1 의 `Power·PowerSubsystem·Thermal·ThermalSubsystem`(8, 종전 404) + r001u01 의 `Power·Thermal·EnvironmentMetrics`(각 ×2 — system 경로·chassis_multi 경로, 종전 404) — 섀시 본문에 그 navigation property 가 없어 요청하지 않는다. 추가 요청 0. FC HBA 카드 조건은 notice 라 golden 밖.

### WP9 (FIX 1 — Redfish `cpu.logical_threads` 제거) — 2026-10-27

| # | WP | fixture / baseline | 경로 | before | after | 원천 | 원인 |
|---|---|---|---|---|---|---|---|
| G-16 | WP9 | `real_hpe_csus3200`(1차) · `real_hpe_csus3200_01/02/03` | `multi_node.partitions[0].cpu.logical_threads` | `64` · `128` · `224` · `128` | **키 없음** | — (모듈 `_normalize_cpu_raw` 가 더 이상 내지 않는다) | 사용자 FIX 1: BMC 스레드 수(RMC 1.75 코어 수 · 1.77 스레드 수, HT 비활성 시 코어 2배)는 OS 와 같은 값을 보장하지 못한다 — top-level `cpu` 와 같은 정책. 다른 partition cpu 키 불변 |
| G-17 | WP9 | `schema/baseline_v1/{dell,hpe,lenovo,cisco}_baseline.json` · `hpe_csus_3200_baseline.json`(합성 — FIX 5 교체 전) | `data.cpu.logical_threads`(CSUS 는 `multi_node.partitions[*].cpu.logical_threads` 3곳 포함) | `24` · `128` · `128` · `44` · `448`×4 | **키 없음** | — | rule 21 R1 의 명시 예외 = 사용자 FIX 1(실측 baseline 의 키 삭제만, 다른 값 불변). `manufacturer` 는 실측 캡처가 아니라 baseline 에 넣지 않았다(값 날조 금지) |

- G-16/G-17 검증: 15 real_* fixture 재생 → 바뀐 golden 경로는 CSUS 4세트의 위 1경로뿐(요청 예산 불변 — `test_request_budget` 15/15). 비-CSUS 11 fixture 는 `multi_node: null` 이라 차이 0.
  모듈 top-level `data.cpu` 는 GOLDEN_KEYS 안이지만 `logical_threads`/`manufacturer` 는 normalize 층 키라 golden 에 없다 — Tier 1 봉투(`tier1-after-WP9/`)로 확인. `schema/examples/redfish_success.json` ·
  `schema/output_examples/redfish_*.jsonc`(5) 도 같은 키 제거 + `manufacturer` 예시 추가(예시는 설명용이라 표에 두지 않는다).

### WP10 (C8 — 기존 필드 보강, 요청 0) — 2026-10-27

| # | WP | fixture / baseline | 경로 | before | after | 원천 | 원인 |
|---|---|---|---|---|---|---|---|
| G-18 | WP10 | `real_dell_r740` · `hpe_emulator_dl365_gen10plus` | `data.network_adapters.ports[*].current_link_speed_mbps` (R740 10건 · 에뮬레이터 2건) | `0` | `null` | recording `NetworkPorts/*.CurrentLinkSpeedMbps 0` · `LinkStatus Down` | 0 Mbps 는 협상값이 아니라 링크 없음 — Gbps 쪽(SCHEMA-02)과 같은 null (03-network-004). 양수 포트 · adapters[].speed_mbps 불변 |
| G-19 | WP10 | `real_dell_r740`(4) · `real_hpe_dl380`(2) · `real_hpe_dl380_gen12_01/02/04`(2 · 4 · 4) · `hpe_emulator_dl325_gen10plus_fc`(2) · `dl360`(2) · `dl365_gen10plus`(2) · `dl380a`(7) · `dl380a_gen12`(6) | `data.storage.controllers[*].drives[*].wwn` | 키 없음 | `naa.<hex>`(소문자) | recording `Drives/*.Identifiers[] {DurableNameFormat NAA, DurableName}` (실측 iDRAC9 `5000c5009a22d3ad` · iLO 7 `50000F0075A05AF1`) | 03-storage-003 — 원천이 있을 때만 새 키. Lenovo · CSUS(Identifiers 없음)는 키 없음 → 최종 JSON 은 null |
| G-20 | WP10 | 실측 15세트 전부 + 에뮬레이터 5 | `data.processors[*].l2_cache_kb` · `l3_cache_kb` | 키 없음 | iLO 7 6737P `65536`/`147456` · XCC 3 6737P 동일 · 1차 XCC 6724P `32768`/`73728` · iDRAC9 `24576`/`36608` · RMC L3 만(`45 MB → 46080` · `75 MB → 76800` · `22.50 MB → 23040`) | `Processor.Oem.Hpe.Cache[]{Name,InstalledSizeKB}` · `Oem.Lenovo.CacheInfo[]{CacheLevel,InstalledSizeKByte}` · `Oem.Dell.DellProcessor.Cache{N}Level/Cache{N}InstalledSizeKB` · `Oem.Hpe.L3CacheSize` 문자열 | 소켓당 캐시 — OEM 네임스페이스 존재로 가르는 라이브러리 OEM 분기(새 키, 원천 있을 때만). normalize 가 `cpu.summary.groups[].l2/l3_cache_kb` 로 싣는다(사전 channel redfish 추가) |
| G-21 | WP10 | `real_hpe_csus3200`(16) · `_01`(32) · `_02`(16) · `_03`(16) | `data.memory.slots[*].rank_count` · `multi_node.partitions[0].memory.slots[*].rank_count` | `null` | `1` | recording `Memory/*.Oem.Hpe.Label "32GB 1Rx4 PC5-6400B-RC1"`(`RankCount` 키 없음) | 02-memory-004 — DMTF RankCount 가 없을 때만 HPE Label `<n>Rx<m>` 의 n. RankCount 보유 벤더 불변 |
| G-22 | WP10 | `real_lenovo_sr650`(1차) · `real_lenovo_sr650_v4_01/02/03/04` | `data.system.bios_date` | `null` | `2025-03-15` · `2026-05-11` · `2026-05-11` · `2026-06-22` · `2026-05-11` | recording `UpdateService/FirmwareInventory/UEFI.ReleaseDate` + `Systems/1/Bios.Links.ActiveSoftwareImage → …/UEFI` · `RelatedItem → /Systems/1/Bios`(구조 근거) | 01-hardware-004 ≡ 04-bios-001 — System · OEM 에 날짜가 없을 때만 구조 근거로 잡힌 항목의 ReleaseDate(연도 0000 자리표시자 제외). iLO(OEM 날짜) · iDRAC(OEM, FirmwareInventory 날짜와 같음) · CSUS(근거 없음) 불변 + notice 1건 |
| G-23 | WP10 | `dmtf_rackmount1`(DMTF 공개 mockup, 4건) · `hpe_emulator_dl325_gen10plus_fc`(2건) | `data.network[*].ipv6[]` | 키 없음 | `[{address, prefix_length, address_origin}]` | mockup `Systems/437XR1138R2/EthernetInterfaces/*.IPv6Addresses` (`fe80::…`) · 에뮬레이터 동일 | 03-network-006 — 값이 있을 때만 `ipv6` 키(실측 18대는 전부 빈 목록이라 불변). normalize 가 `interfaces[].addresses[]` family ipv6 로 싣는다 |

- G-18~G-23 검증: `expected_output.json` + `recording.json` 이 있는 fixture 21세트 전부 재생해 평탄 비교 — 바뀐 경로가 위 6 묶음뿐(요청 예산 15/15 불변, 에뮬레이터 요청 집합 불변). 모듈 raw 호스트 NIC `mtu` 는 그대로(NDF MTU 는 data 밖 aux `ndf_mtu_by_mac` → normalize 층이 `interfaces[].mtu` 를 채움 — golden 밖, Tier 1 로 확인).

### WP11 (C11 — bmc · diagnosis) — 2026-10-27

| # | WP | fixture / baseline | 경로 | before | after | 원천 | 원인 |
|---|---|---|---|---|---|---|---|
| G-24 | WP11 | `real_hpe_dl380`(1차) · `real_hpe_dl380_gen12_01/02/03/04` | `data.bmc.timezone` | `null` | `GMT-0` · `JST-9:00` ×4 | 전수 미러 `Managers/1/DateTime`(`#HpeiLODateTime.v2_1_0`, `TimeZone {Index, Name, UtcOffset, Value}`) 를 recording 에 **추가**(`get::Managers/1/DateTime`, 1차 `C:\github\서버mock데이터\1차\HPE_DL380\01`, 2차 extract) — Manager 본문은 `TimeZoneName` 없음 · `Oem.Hpe.Links.DateTimeService` 링크 | 06-bmc-003 — 링크가 있고 TimeZoneName 이 없을 때만 +1 GET, `TimeZone.Value`(POSIX 꼴 — iDRAC `CST6CDT` 와 같은 계열) → 없으면 `Name`. 요청 예산 5세트 +1(`added_reason`), 그 밖 10 fixture 불변 |

- G-24 검증: 21 fixture 재생 → 바뀐 golden 은 DL380 5세트의 `data.bmc.timezone` 뿐. HPE 에뮬레이터 5세트는 같은 링크가 있어 GET 1회가 더 나가지만 recording 에 리소스가 없어(replay-miss 404) null 그대로 — golden 불변(예산 파일 없음). 06-bmc-005(NIC 선택) · 06-bmc-006(이름 폴백) · 06-bmc-001(family) · 06-bmc-002(writable) · 06-bmc-010(auth_success) 은 모듈 golden 을 바꾸지 않는다(18 label 값 불변 — Tier 1 로 확인).
