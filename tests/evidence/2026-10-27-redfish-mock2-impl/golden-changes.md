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
