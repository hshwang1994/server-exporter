# 통합 이슈 목록 — Redfish 2차 Mock 11대 전수 분석 (2026-10-26)

보고서 6개(`analysis/01~06`)의 §4 이슈를 기계 추출(`tools/extract_issues.py`)해 ID·심각도·확실성을 그대로 두고, 메인이 공통 원인별 클러스터(C1~C11)와 처리 유형을 붙였다. 합계 72건 — HIGH 2 · MED 18 · LOW 51 · 미분류 1. 같은 원인의 중복은 §4 에 표시했고 ID 는 삭제하지 않았다(보고서 추적성). 심각도·확실성은 작업자 판정이며 메인이 표본을 Mock 원본·Tier 1 봉투로 재검증한 항목은 '메인 검증' 열에 적었다.

처리 유형: `code-common` 공통 로직 수정 / `code-oem` OEM 분기·adapter 수정 / `category` 펌웨어 분류 규칙 / `docs` 문서·사전 정정(스키마 변경 아님) / `test` 테스트·재생 도구 / `decision` 사용자 결정 필요 / `observe` 관찰(변경 제안 없음).

## 1. 우선순위 요약

| 순위 | 클러스터 | 핵심 이슈 | 유형 | 비고 |
|---|---|---|---|---|
| 1 | C1 adapter 재선택 규칙 | 01-adapter-001 HIGH(확정) | code-common | Lenovo 5/5 재현, 수정 시 전체 adapter 선택 회귀 필수 |
| 2 | C3 CPU 논리 스레드 | 02-cpu-001 HIGH(추정) + 02-cpu-002 MED | code-common + ADR 정정 | OS/ESXi 실측으로 기대값 확정 후 적용(사용자 결정) |
| 3 | C2 전원 Off 호스트 | 03-storage-001·02-memory-001·05-power-001·05-thermal-002 MED | code-common | 공통 notice + placeholder 정리, Additive |
| 4 | C9 firmware category | 04-firmware-001/002/003 MED | category | 토큰 순서 재설계 + 구조 신호 |
| 5 | C4 Lenovo XCC3 모양 | 03-network-001·04-firmware-006 MED | code-common | 주소 형식·구조 신호 기반, vendor 분기 없음 |
| 6 | C10 전원·온도 의미 | 05-thermal-001·05-power-002 MED | code-common | Absent 제외, 입력 0 W notice, golden 갱신 |
| 7 | C7 테스트·재생 | 04-test-001 MED + 구조적 공백 | test | install_fakes 복원, 2차 fixture, Tier 1 재생 편입 결정 |
| 8 | C5 CSUS/RMC | 02-memory-002·01-multi_node-003 MED | decision/docs/test | 섀시 링크 gating(코드), 속도 단위·baseline 교체(결정) |
| 9 | C6 계약·사전 drift | 01-hardware-002·02-cpu-003 MED | docs(+Additive 2건) | 한 묶음으로 처리 |
| 10 | C8 기존 필드 보강 | LOW 다수 | code-common | C1~C5 뒤 |
| 11 | C11 bmc/users | 06 보고서 | — | 취합 후 갱신 |

## 2. 공통 원인 클러스터 (원인 → 증상 → 영향 → 수정 위치 → 회귀)

### C1. adapter 선택·재선택 공통 규칙

이슈: `01-adapter-001`(HIGH), `01-adapter-011`(LOW)

- **공통 원인**: `module_utils/adapter_common.py` 의 실격 규칙 — model_patterns 가 맞아도 firmware_patterns 가 알려진 firmware 와 어긋나면 -9999 로 실격(`adapter_matches` :183-189, `adapter_match_score` :291-300). 재선택 facts(`redfish-gather/tasks/reselect_adapter.yml` :39-48)는 `Manager.FirmwareVersion` 하나만 쓰는데, XCC3 의 그 값(`IHX438R 2.97 20260910`)에는 세대 토큰이 없다(토큰은 `Manager.Model` "XClarity Controller 3").
- **개별 증상**: Lenovo SR650 V4 4대 + 1차 SR650 → `meta.adapter_id = redfish_lenovo_bmc`(priority 10), `adapter_first_pass = redfish_lenovo_xcc3`(의미 역전). Dell R740 은 1차 선택이 priority 만으로 `dell_idrac10` 이 됐다가 재선택이 `^[3-7]\.` 로 바로잡는 "같은 규칙의 성공 사례". 복구(`account_service.yml`)가 받는 hint 는 재선택 강등값이 아니라 **1차 선택값**(표준 401 이면 재선택이 facts 없음으로 건너뛰고 2회차 재선택은 복구 뒤 — 06 보고서 교차 이슈 1)이므로 규칙 B 는 복구 Family 에 영향이 없다. 복구 쪽 진짜 결함은 06-bmc-001(C11).
- **영향 서버/필드**: sr650_v4_01..04, r1_Lenovo_SR650_01 — `meta.adapter_id`, `diagnosis.details.adapter_candidate/adapter_first_pass`; 향후 `lenovo_xcc3.yml` 의 `vendor_notes` 가 조용히 무시되는 잠복 결함(현재 데이터 영향 0).
- **권장 수정 위치**: (1) `adapter_common.py` — model_patterns 가 있고 model fact 가 일치한 adapter 는 firmware 불일치를 보너스 상실(+25 미획득)로만 취급(규칙 B), (2) `reselect_adapter.yml` facts 에 BMC 모델 문자열(`data.bmc.model`)을 보조 신호로 넣을지 검토(스키마 무관), (3) `adapters/redfish/lenovo_xcc3.yml` firmware_patterns 를 실측 문자열 형식(`IHX4…`/`XCC 3`)으로 보강 + origin 주석, (4) 문서·시험 정정(`tests/unit/test_adapter_generation_tokens.py` 가공 펌웨어 "XCC3 1.20" → 실측, `docs/ai/catalogs/VENDOR_ADAPTERS.md`).
- **회귀 검증**: 18 label 실제 인증 후 facts 로 선택 결과 전수 고정(Lenovo 5건만 xcc3 로 바뀌고 나머지 불변 — 01 보고서 시뮬레이션), 기존 단위 매트릭스 22건 불변, CLAUDE.md §5 "선택 로직 변경 시 전체 Regression".

### C2. 전원 Off 호스트 거동 (dl380_gen12_03 가 드러낸 공통 신호)

이슈: `02-memory-001`(MED), `03-storage-001`(MED), `05-power-001`(MED), `05-thermal-002`(MED), `04-firmware-009`(LOW)

- **공통 원인**: 호스트 전원 Off(`System.PowerState Off`, `Oem.Hpe.PostState PowerOff`)인 iLO 7 은 Storage 컬렉션 0건, 빈 DIMM 을 `Status` 없이(`CapacityMiB 0`, `DIMMStatus Other`), PSU 를 `Absent/0 W/"0.00"`, 온도·팬을 `UnavailableOffline/0` 으로, 펌웨어 항목을 13건(PSU `0.00`, 드라이브·백플레인 부재)으로 노출한다. 수집기는 `200 + placeholder` 를 정상 수집(success)으로 두고 어디에도 신호를 남기지 않는다.
- **개별 증상**: 03-storage-001(디스크 0·컨트롤러 0, 그런데 PCIeDevices 에 MR416i-o RAID 존재), 02-memory-001(slots 32 중 16 공란), 05-power-001(PSU 0개·fw 0.00), 05-thermal-002(온도 42건 0 °C·팬 6건 0 %), 04-firmware-009(관찰: 13건은 raw 그대로).
- **영향**: dl380_gen12_03 1대(2차). 전원 Off 인 어떤 장비든 재현 가능(가설 — 동일 모델 3대 대조가 근거; 다른 벤더 미확인).
- **권장 수정 위치(공통, Additive)**: `gather_system` 이 이미 캐시한 `System.PowerState` 를 각 섹션이 참조해 (a) Off 면 `diagnosis.details.notices` 에 공통 한 문장("호스트 전원 Off — 저장/메모리/전원/온도 인벤토리가 비어 있거나 placeholder 일 수 있음"), (b) `gather_memory` 빈 슬롯 판정에 "Status 부재 + 용량 0 + 식별 정보 없음 → 제외" 추가, (c) PSU `State Absent` 의 `power_capacity_w 0`·`firmware_version "0.00"` → null(A-3 "0 은 거짓 값" 확장), (d) 센서 `Status.State != Enabled` 면 `reading` null(값 생성 없음). 선택: PCIeFunctions `DeviceClass MassStorageController` 로 controllers[] 보강(03). 스키마 변경 없음.
- **회귀 검증**: dl380_gen12_03 축약 recording(전원 Off) + dl380_gen12_01(On) 쌍으로 notice 유무·슬롯 16·PSU null·센서 null 고정.

### C3. CPU 논리 스레드 의미 (HT 비활성 과대집계, ADR 전제 붕괴)

이슈: `02-cpu-001`(HIGH), `02-cpu-002`(MED), `02-cpu-006`(LOW)

- **공통 원인**: `cpu.logical_threads` 가 `ProcessorSummary.LogicalProcessorCount`(LPC) 또는 Σ`Processor.TotalThreads` 중 하나를 고를 뿐 HT 상태 원천을 보지 않는다(`normalize_standard.yml` :615-628, `_normalize_cpu_raw` :5910-5949). XCC 2.97·RMC 1.77.30 의 LPC 는 Σ`TotalThreads`(용량) 와 같아 HT Disabled 를 반영하지 않는다.
- **개별 증상**: 02-cpu-001(HIGH, **추정** — OS 실측 없음): csus3200_02 224(코어 112), dl380_gen12_03·sr650_v4_01/02/04 128(코어 64); 02-cpu-002(MED 확정): ADR-2026-10-19 A-2 전제 "RMC LPC = 코어 수" 는 RMC 1.75.108 한정, 1.77.30 은 Σthreads → adapter `processor_summary_logical_count: cores` 의 설명·테스트 문구가 사실과 다름; 02-cpu-006(LOW 잠재): `TotalEnabledCores` 미사용.
- **근거 보강**: 04 보고서 — HT 속성(`HThread`/`ProcHyperthreading`/`Processors_Hyper_Threading`/`LogicalProc`)이 18/18 `bios.current.attributes` 에 문자열 `Enabled/Disabled` 로 존재(pending 값도 같음) → 이미 수집 중인 응답으로 판정 가능.
- **권장 수정 위치(공통)**: `cpu_summary`(`redfish_gather.py` :2643-2654)에 DMTF `ProcessorSummary.ThreadingEnabled` 수집 → `normalize_standard.yml` cpu 블록에서 (1) `ThreadingEnabled` 가 있으면 그것, (2) 없으면 adapter `vendor_notes` 가 지정한 BIOS 속성 키의 **값**(`Disabled`)으로 `logical_threads = cores_physical`, (3) 둘 다 없으면 종전. partition 경로(`_normalize_cpu_raw`)도 같은 규칙. 플래그 `processor_summary_logical_count` 는 의미 재정의 또는 제거 검토. **OS/ESXi 실측(5대)으로 "기대 = 코어 수" 를 확정한 뒤 적용**(사용자 결정 항목).
- **ADR 정정**: ADR-2026-10-18 X3("LPC 있으면 정본"), ADR-2026-10-19 결정 3·A-2·대안 비교; `docs/contract/03-fields.md:552-554`, `schema/field_dictionary.yml:1699-1707`, `docs/ai/catalogs/EXTERNAL_CONTRACTS.md:11,54`; `tests/integration/test_redfish_csus_single_server_render.py:54-60` 문구.
- **회귀 검증**: `tests/unit/test_cross_channel_value_fixes.py` 3분기(Disabled→cores / Enabled→종전 / 속성 없음→종전), csus3200_02 케이스(224→112), Dell `ThreadingEnabled true` 불변.

### C4. Lenovo XCC3(IHX438R 2.97) 응답 모양

이슈: `03-network-001`(MED), `04-firmware-006`(MED), `01-hardware-005`(LOW), `02-memory-003`(LOW), `03-network-003`(LOW), `03-network-005`(LOW), `04-firmware-010`(LOW), `05-power-003`(LOW)

- **공통 원인**: XCC3 가 (a) FC HBA 포트를 호스트 `EthernetInterfaces` 로 노출(MAC 8옥텟 = WWPN), (b) 호스트 NIC `SpeedMbps` 를 Gbps×1024 로, (c) `ToManager` USB NIC 를 호스트 NIC 로, (d) 보류 이미지가 없어도 `*-Pending` 펌웨어 슬롯을 항상 노출(`Version ""`, `State Disabled`), (e) PSU `Model` 에 패딩 공백, (f) DIMM `MemoryLocation.Slot` 숫자 문자열, (g) `TrustedModules null`·`LastResetTime` 등 OEM 키 부재를 보인다. 코드는 주소 형식·구조 신호를 보지 않고 id/이름 문자열에 의존한다.
- **개별 증상**: 03-network-001(MED): interfaces 15/9 에 FC 4 포함, `summary.port_count`·groups(`fibrechannel`) 오염, `interfaces[].mac` 형식 위반; 04-firmware-006(MED): 서버당 `pending:true, version:null` 4건 상시; 03-network-003/005, 02-memory-003, 05-power-003, 01-hardware-005(LOW).
- **권장 수정 위치(공통, vendor 분기 없음)**: `gather_network`/`normalize_standard.yml interfaces` — 주소가 `ports[]` 의 FC/IB 포트 주소와 같거나 16-hex 인 항목 제외 + notice(INV-5 불변식 추가); `gather_firmware` — `Status.State == Disabled` 이고 `Version` 빈 항목은 "보류 이미지 없음" 으로 제외/notice; `_normalize_port_speed` — 1024 배수 표기 보정은 **ports[] 와의 join 값 우선**으로(숫자 휴리스틱 단독 금지); PSU model `strip()`; DIMM locator 는 `ServiceLabel` 우선 순서 재검토; `hardware.oem` Lenovo 키는 원천 있는 것(`SubModel`→machine_type, `IndicatorLED`→led_indicator)만 매핑.
- **회귀 검증**: sr650_v4_02/03 축약 recording(FC-in-EthernetInterfaces), sr650_v4_01(Pending 슬롯), 1차 `real_lenovo_sr650` golden 갱신(26건 중 2건 -Pending).

### C5. HPE Compute Scale-up Server 3200 / RMC 1.77.30

이슈: `01-multi_node-003`(MED), `02-memory-002`(MED), `01-multi_node-006`(LOW), `01-multi_node-007`(LOW), `01-system-008`(LOW), `01-system-009`(LOW), `02-cpu-005`(LOW), `04-bios-003`(LOW), `04-firmware-007`(LOW), `04-firmware-011`(LOW), `05-power-004`(LOW), `05-power-007`(LOW)

- **공통 원인**: RMC 의 Redfish 모델이 표준과 다른 곳 — DIMM `OperatingSpeedMhz` 가 I/O 클럭(3200, Label `PC5-6400B`), 집합 섀시(RackGroup/Rack1)에는 Power/Thermal 리소스가 없고 r001u01 만 PowerSubsystem/ThermalSubsystem(legacy `Power`/`Thermal` 404), `LogicalProcessorCount` 의미가 펌웨어 버전(1.75.108 코어 / 1.77.30 스레드)에 따라 다름, FirmwareInventory 가 complex 번들 2건(`Partition0_FW`·`ComplexFW` → category other), `Bios` 는 Partition0 수준(76 속성), `multi_node.composition` 의 count 가 원천 배열 없이 0.
- **개별 증상**: 02-memory-002(MED), 01-multi_node-003(MED: baseline/계약 예시가 mock 구조), 01-multi_node-006 ≡ 05-power-004(LOW: 고정 경로 404 11개·14건, r001u01 3경로 2회 — `_get` 은 200 만 캐시), 01-multi_node-007, 02-cpu-005, 01-system-008/009, 05-power-007, 04-firmware-011, 04-firmware-007, 04-bios-003.
- **권장 수정 위치**: (1) 섀시 순회는 Chassis 본문의 navigation property(`Power`/`Thermal`/`PowerSubsystem`/`ThermalSubsystem`/`EnvironmentMetrics` 링크 키)가 있을 때만 요청(공통 로직; DL380/SR650 은 legacy 경로가 실재해 영향 0) — 404 재요청도 사라짐, (2) `OperatingSpeedMhz` 는 계약에 "HPE H3(RMC) 는 I/O 클럭" 명시(+선택: `Oem.Hpe.Label` 의 `PC5-NNNN` 이 있고 ×2 와 같을 때만 MT/s 보정 — 숫자만 보고 ×2 금지), (3) `composition.*_count` 는 원천 없으면 null(사용자 결정), (4) baseline `hpe_csus_3200_baseline.json` 과 `03-fields.md §9` 예시를 실 캡처로 교체(ADR-2026-05-12 결정 6 이행 — 사용자 결정), (5) category 규칙은 C9.
- **회귀 검증**: 2차 CSUS 3대 + 1차 4대 recording 으로 요청 집합(고정 경로 0건)·multi_node 구조·DIMM 속도·category 고정.

### C6. 계약·사전(field_dictionary)·문서 drift (스키마 변경 아님)

이슈: `01-hardware-002`(MED), `02-cpu-003`(MED), `01-correlation-010`(LOW), `02-cpu-004`(LOW), `02-cpu-007`(LOW), `02-memory-005`(LOW), `03-storage-002`(LOW), `04-bios-002`(LOW), `04-firmware-008`(LOW), `04-firmware-012`(LOW), `05-power-005`(LOW), `05-power-006`(LOW), `05-thermal-005`(LOW), `02-memory-006`(?)

- **공통 원인**: `schema/field_dictionary.yml` 과 `docs/contract/03-fields.md` 가 구현과 어긋난 채 유지됨 — 선언됐는데 미발행(`cpu.manufacturer` redfish, `storage.controllers[].driver` redfish), 미등재(`cpu.logical_threads/sockets/model`, power/thermal 하위 키 30여 개), 서술 오류(`hardware.health` "BMC rollup" vs 실제 `Status.Health`; "PSU 한 대 fault → Critical" 이 iLO 7 에서 거짓), 정의 부재(`power_capacity_watts` 벤더별 의미, `correlation.bmc_ip`), `data.firmware` 절 부재·category help 불일치, `sections.yml network.empty_value` 의 bonds/bridges/teams(OS 전용 키).
- **개별 증상**: 01-hardware-002(MED), 02-cpu-003(MED), 02-cpu-004/007, 03-storage-002, 01-correlation-010, 05-power-005/006, 05-thermal-005, 04-firmware-012, 04-bios-002(관찰), 02-memory-005/006(관찰), 04-firmware-008(관찰).
- **권장 수정 위치**: 문서·사전 정정 묶음 1건(스키마 키 변경 없음) + Additive 코드 2건: `hardware.health` 는 `Status.Health` null 일 때만 `HealthRollup` 폴백(memory/cpu summary 와 같은 패턴), `cpu.manufacturer` 는 사전대로 발행(`Intel(R) Corporation`→`Intel` OS 와 같은 정규화) **또는** 사전에서 redfish 채널 제거 — 둘 중 하나(사용자 결정).
- **회귀 검증**: `tests/unit/test_field_dictionary_channel_emit.py` 에 "redfish 로 선언된 키는 normalize_standard 가 발행" 검사 확장.

### C7. 테스트·재생(Replay) 허점

이슈: `04-test-001`(MED), `06-bmc-008`(LOW)

- **확정 결함(04-test-001, MED)**: `tests/redfish-probe/replay_full_mirror.py::install_fakes` 가 `rg._get`/`rg._get_noauth` 를 복원 없이 교체 → 같은 프로세스 뒤의 `_get_impl` seam 테스트가 가려짐. `tests/unit` 전체 실행 19 failed(Windows), 폴루터 `test_full_mirror_dryrun.py::test_v2_tree_is_consumed_by_replay_and_convert` 1개 + `test_redfish_bios_current.py` 쌍으로 8 failed 재현(메인·04 각각). 수정은 테스트 도구만(컨텍스트 매니저/`finally` 복원 또는 `_get_impl` seam 통일).
- **구조적 공백**: (1) 1차 축약 fixture(`real_*`)는 "코드가 그때 요청한 경로" 만 담아 새 요청(예: `gather_bios`)이 replay-miss 404 가 된다 — golden 이 `bios None` 을 고정; (2) 2차의 새 모양(XCC3 FC-in-EthernetInterfaces, 전원 Off 호스트, iLO 7 FC Port `FibreChannel:{}`+Ethernet WWPN, RMC 1.77.30 LPC, iLO Absent 온도 슬롯, AC 입력 없는 PSU, XCC3 PowerControl 3건)에 fixture 가 없다; (3) `firmware[].category`·adapter 재선택·`hostname_priority`·serial `-NNN`·uuid 소문자 등 **Ansible normalize 층**은 Tier 2(모듈 재생)로 검증 불가 — 이번 Round 의 Tier 1(실제 playbook + 미러 HTTPS 재생 서버)만 봤다; (4) `_make_section_runner` 는 "200 + placeholder" 를 success 로 둬 C2·C10 류는 어떤 재생으로도 실패로 안 잡힌다; (5) `hpe_csus_3200_baseline.json` 이 mock-derived 라 실 구조 회귀가 baseline 으로 잡히지 않는다; (6) 교차채널 HT 검출 쌍(HPE/Lenovo/CSUS 의 OS 실측)이 없다; (7) 페이지네이션·멤버 5xx·BIOS 실패 분기는 18 label 에서 미발동(합성 테스트만).
- **권장**: 2차 zip 11대에서 `capture_mirror_fixture.py` 로 축약 recording 을 만들어(이름 `real_*` 는 자동 등록되므로 의도적으로) golden 을 **구현 전·후 2단계**로 관리; Tier 1 재생 서버(`tools/`)의 저장소 편입 여부는 사용자 결정 항목.

### C8. 기존 필드로 채울 수 있는 미추적 정보 (계약 안, 요청 추가 0 또는 최소)

이슈: `01-hardware-004`(LOW), `02-memory-004`(LOW), `03-network-002`(LOW), `03-network-004`(LOW), `03-network-006`(LOW), `03-network-007`(LOW), `03-storage-003`(LOW), `04-bios-001`(LOW)

- 03-network-002: 호스트 NIC 에 LinkStatus/SpeedMbps 가 없을 때 같은 MAC 의 `ports[]` 값으로 `interfaces[].link_status/speed_mbps` 보완(Lenovo 4·HPE 4·CSUS 3). 03-network-007: `interfaces[].mtu` 를 NDF `Ethernet.MTUSize` 로. 03-network-004: `CurrentLinkSpeedMbps 0` 의 0/null 표기 통일. 03-network-006: `IPv6Addresses` 수집(표본 없음). 03-storage-003: `physical_disks[].wwn` 을 `Drive.Identifiers`(NAA)로(사전 channel 갱신). 01-hardware-004 ≡ 04-bios-001: Lenovo `bios_date` 를 `FirmwareInventory/UEFI.ReleaseDate`(또는 `Bios.Links.ActiveSoftwareImage`)로 — HPE `0000-01-01` 자리표시자는 필터. 02-memory-004: CSUS `rank_count` 를 `Oem.Hpe.Label` `1Rx4` 로. 02 §5: CPU L2/L3 캐시를 OEM 키로 `cpu.summary.groups[].l2_cache_kb/l3_cache_kb` 에.
- 모두 기존 키 범위. 우선순위는 LOW — C1~C5 뒤에.

### C9. `firmware[].category` 분류 규칙 (`normalize_standard.yml` `_rf_firmware_categorized` 토큰 사슬)

이슈: `04-firmware-001`(MED), `04-firmware-002`(MED), `04-firmware-003`(MED), `04-firmware-004`(LOW), `04-firmware-005`(LOW)

- **공통 원인**: 이름/id 토큰 사슬에만 의존 — `uefi` 토큰 없음(Lenovo UEFI·CSUS `Partition0_FW` → other), 포괄 `controller` 토큰이 비디오 컨트롤러를 storage_controller 로, HPE `MRnnni-o`(MegaRAID) 에 `raid` 없음 → other, `Drive_Backplane…PSoC` 가 `drive` 선점, FC HBA 가 Dell 만 storage_controller, CPLD/FPGA `Programmable Logic Device` → other, M.2 RAID 키트 `nvme` → drive.
- **개별 증상**: 04-firmware-001/002/003(MED), 04-firmware-004/005(LOW). 영향: Lenovo 5·HPE 5·CSUS 7 대의 category 집계 왜곡.
- **권장 수정 위치(공통)**: 토큰 순서 재설계(`disk`→drive / `backplane`→backplane / `video|graphics`→other 를 `controller` 앞 / `uefi`→bios(단 `diagnostic` 우선) / `programmable logic|fpga`→cpld / `raid`→storage_controller 를 `nvme` 앞) + **구조 신호 우선**(`Systems/<id>/Bios.Links.ActiveSoftwareImage`·`RelatedItem→…/Bios` ⇒ bios, `Managers/<id>.Links.ActiveSoftwareImage` ⇒ bmc, 같은 장비 `storage.controllers[].controller_model` 과 이름 일치 ⇒ storage_controller). enum 확장(`hba`)은 계약 결정 사항으로 분리.
- **회귀 검증**: `tests/unit/test_firmware_category.py` 에 4벤더 실측 이름 매트릭스(04 보고서 §4 표) 추가, Dell 기존 케이스 불변.

### C10. 전원·온도 값의 의미 (Absent/UnavailableOffline/AC 입력 없음)

이슈: `05-power-002`(MED), `05-thermal-001`(MED), `05-thermal-003`(LOW), `05-thermal-004`(LOW)

- **공통 원인**: 센서·PSU 의 `Status.State` 를 보지 않고 값을 그대로 싣는다 — iLO legacy Thermal 의 `Absent` 슬롯이 0 °C 로 `temperatures[]` 에(05-thermal-001 MED, golden `real_hpe_dl380` 이 이를 고정), AC 입력 없는 PSU 가 iLO 는 `UnavailableOffline`·XCC3 는 `Enabled` 로 와 `psu_active` 가 벤더별로 갈리고 원인(`ACPowerLost`/`LineInputVoltage 0`/`PowerInputWatts 0`)이 봉투에 없다(05-power-002 MED, 2차 7/8대).
- **권장 수정 위치(공통)**: `gather_thermal`/`_gather_thermal_subsystem` 에서 `State == Absent` 제외(+notice 건수), `State != Enabled` 면 reading null(C2 와 같은 규칙); PSU 입력 0 W 는 notice 한 줄("AC 입력 없음 — health Critical 은 입력 손실") + 계약 문장. `power_capacity_watts` 벤더별 정의·소비전력 폴백 정의(DC 출력 합 vs AC 입력 합)는 문서(C6).
- **회귀 검증**: dl380_gen12_01(Absent 7, ACPowerLost PSU), sr650_v4_01(입력 0 W PSU) recording; golden `real_hpe_dl380` temps 52→43 갱신.

### C11. bmc · diagnosis · users (06 보고서)

이슈: `06-bmc-001`(MED), `06-bmc-002`(LOW), `06-bmc-003`(LOW), `06-bmc-004`(LOW), `06-bmc-005`(LOW), `06-bmc-006`(LOW), `06-bmc-007`(LOW), `06-bmc-009`(LOW), `06-bmc-010`(LOW)

- **실측 결과**: `data.bmc` 20키 18/18 raw 와 일치(06 보고서 자동 대조 `DIFFS: NONE`), `dns_servers=[]` 11/11 은 원천 부재(결함 아님 — 03 교차 이슈 종결), `default_gateways` = BMC NIC gateway, `bmc.ip == correlation.bmc_ip == 수집 당시 BMC IP` 11/11(메인 재현). diagnosis 5키·credential 2축·auth 메타·`account_service {}` 전수 대조.
- **공통 원인/증상**: (1) `resolve_account_family`(`redfish_gather.py` :7521-7640) Lenovo 분기가 세대를 **adapter 이름 hint**(`'xcc3' in hint`)로만 가르고 이미 읽어 둔 `Manager.Model`("Lenovo XClarity Controller 3")을 쓰지 않는다 — Dell 분기는 "장비 값 우선"(06-bmc-001 MED; 재생은 401 을 재현하지 못해 코드+raw 판정). (2) 성공 경로 `auth_success: true` 가 무조건이라 익명 수집 성공(`used_role: anonymous`)도 "실제 인증 성공" 으로 보인다(06-bmc-010; CLAUDE.md §9 의미와 어긋남). (3) `bmc.ip/mac_address/dns_name` 이 EthernetInterfaces 컬렉션 순서("IPv4 있는 첫 NIC")에 의존 — iLO 7 USB 가상 NIC(16.1.15.1)가 뒤라 우연히 안전(06-bmc-005). (4) `bmc.name` 이 adapter `manager_layout` 에만 의존, 장비 값(`ManagerType RackManager`, `Id RMC`) 미사용(06-bmc-006). (5) iLO 7 `bmc.timezone` null — `Managers/1/DateTime.TimeZone` 으로 채울 수 있음(+1 GET, 06-bmc-003). (6) RMC 계정 리소스가 `@Redfish.WriteableProperties: ["Password"]`·`Enabled/Locked` 를 노출 — 2026-10-14 hotfix 의 미확인 항목 답 확정, `test_account_hpe_rmc_enabled.py` fixture 전제와 불일치(06-bmc-002). (7) 문서: `bmc.datetime` 벤더별 표기(06-bmc-004), Redfish 전용 `diagnosis.details` 키·`account_service {}` 의미 미정의(06-bmc-007), `bmc.uuid` 사전 설명(06-bmc-009).
- **users**: 18대 `AccountService/Accounts`·`Roles`·정책 관찰 표만 — `data.users` 는 OS 계정 의미라 BMC 계정으로 채우는 것은 계약·의미 변경(사용자 결정 10).
- **권장 수정 위치**: `resolve_account_family` Lenovo 분기에 `Manager.Model`/`ManagerType` 장비 값 우선(Dell 과 같은 패턴, 벤더 이름 분기가 아니라 이미 있는 OEM 분기 안), `_compute_final_status`/diagnosis 빌더에서 `auth_success` 는 실제 자격으로 인증했을 때만 true(익명 성공은 null), `gather_bmc` NIC 선택은 대상 IP 와 일치하는 NIC 우선(없으면 종전), `bmc.name` 은 장비 값 폴백, iLO DateTime 추가 GET(Additive). 문서 3건은 C6 묶음과 함께.
- **회귀 검증**: Lenovo 5 label `account_family` 판정이 `Manager.Model` 기준으로 XCC3(합성 401 경로 테스트), 11대 `bmc.*` 바이트 불변(ip 선택 규칙 변경 후에도 11/11 동일), iLO 7 timezone 값 고정.

## 3. 전체 이슈 표 (심각도 → ID 순)

| ID | 심각도 | 확실성 | 클러스터 | 유형 | 제목 | 출처(보고서:행) | 메인 검증 |
|---|---|---|---|---|---|---|---|
| 01-adapter-001 | HIGH | 확정 | C1 | code-common | Lenovo XCC3 로그인 후 adapter 재선택이 범용 `redfish_lenovo_bmc` 로 강등 | 01-system-hardware-multi-node.md:93 | 메인 재현: facts fw 'IHX438R 2.97 20260910' 가 xcc3 `XCC\s*3\b`·xcc 패턴 모두 불일치 → -9999, lenovo_bmc 만 잔존 (Tier 1 5/5) |
| 02-cpu-001 | HIGH | 추정 | C3 | code-common | HT 비활성 장비에서 `cpu.logical_threads` 가 코어의 2배 | 02-cpu-memory.md:78 | 메인 재현: csus3200_02 LPC 224 = ΣTotalThreads, BIOS HThread Disabled; 04 보고서가 18/18 HT 속성 존재 확인. OS 실측 없음 → 추정 유지 |
| 01-hardware-002 | MED | 확정 | C6 | docs | `hardware.health` 출처(`Status.Health`)와 사전·계약의 "BMC rollup" 설명 불일치 — iLO 7 에서 OEM 집계와 갈림 | 01-system-hardware-multi-node.md:108 | 메인 재현: dl380_gen12_01 Status.Health Warning vs Oem.Hpe.AggregateHealthStatus.AggregateServerHealth Critical(PowerSupplies Critical) |
| 01-multi_node-003 | MED | 확정 | C5 | test | CSUS mock 기반 baseline·계약 예시가 실 7대와 다름 (ADR-2026-05-12 결정 6 의 교체 의무 미이행) | 01-system-hardware-multi-node.md:120 | - |
| 02-cpu-002 | MED | 확정 | C3 | docs | ADR-2026-10-19 A-2 전제(RMC `LogicalProcessorCount` = 코어 수)가 RMC 1.77.30 에서 불성립 | 02-cpu-memory.md:95 | 메인 재현: 2차 RMC 1.77.30 LPC == ΣTotalThreads |
| 02-cpu-003 | MED | 확정 | C6 | code-common | `cpu.manufacturer` 사전 선언·Redfish 미발행, `groups[].manufacturer` 비정규화 | 02-cpu-memory.md:108 | - |
| 02-memory-001 | MED | 확정 | C2 | code-common | dl380_gen12_03: `Status` 없는 빈 슬롯 16개가 `memory.slots[]` 에 포함 | 02-cpu-memory.md:138 | 메인 재현: Memory 32 중 Status 없음 16·CapacityMiB 0 16 → slots 32 |
| 02-memory-002 | MED | - | C5 | decision | CSUS `slots[].speed_mhz`/`summary.groups[].speed_mhz` 가 실클럭(MHz), 다른 벤더는 MT/s | 02-cpu-memory.md:151 | 메인 재현: CSUS OperatingSpeedMhz 3200(Label PC5-6400B) vs iLO/XCC 6400 |
| 03-network-001 | MED | 확정 | C4 | code-common | Lenovo XCC3 가 FC HBA 포트를 호스트 `EthernetInterfaces` 로 노출 → `network.interfaces[]`/`summary` 에 FC 포트가 섞임 | 03-network-storage.md:82 | 메인 재현: sr650_v4_02 EthernetInterfaces NIC3/4/7/8 MAC 8옥텟, envelope interfaces 9 중 FC 4 |
| 03-storage-001 | MED | - | C2 | code-common | 전원 Off 호스트(dl380_gen12_03): Storage 컬렉션 0건·NIC 정보 축약인데 envelope 의 storage/network 에 아무 신호가 없다 | 03-network-storage.md:96 | 메인 재현: dl380_gen12_03 Storage Members 0, PCIeDevices/276 = HPE MR416i-o Gen11 |
| 04-firmware-001 | MED | 확정 | C9 | category | Lenovo BIOS(`UEFI`) · CSUS `Partition0_FW` 가 `category: other` | 04-firmware-bios.md:89 | - |
| 04-firmware-002 | MED | 확정 | C9 | category | HPE RAID 컨트롤러 `other`, `Embedded Video Controller` 가 `storage_controller` | 04-firmware-bios.md:102 | 메인 재현: dl380_gen12_01 firmware[] MR416i-o → other, Embedded Video Controller → storage_controller |
| 04-firmware-003 | MED | 확정 | C9 | category | Lenovo 드라이브 백플레인 PSoC 가 `drive` | 04-firmware-bios.md:115 | - |
| 04-firmware-006 | MED | - | C4 | code-common | Lenovo `*-Pending` 빈 스테이징 슬롯이 `pending: true` 항목으로 나간다 | 04-firmware-bios.md:150 | - |
| 04-test-001 | MED | 확정 | C7 | test | Tier 0 순서 의존 실패: `replay_full_mirror.install_fakes` 가 `rg._get` 을 복원 없이 교체 | 04-firmware-bios.md:237 | 메인 재현: test_v2_tree_is_consumed_by_replay_and_convert + test_redfish_bios_current.py 쌍 → 8 failed |
| 05-power-001 | MED | - | C2 | code-common | 전원 Off 호스트(dl380_gen12_03): PSU 2개가 `Absent · 0 W · fw "0.00"` placeholder 로 "PSU 0개" 가 된다 | 05-thermal-power.md:108 | 메인 재현: PSU 2 Absent, fw '0.00' 그대로, psu_count 0 |
| 05-power-002 | MED | - | C10 | code-common | AC 입력 없는 PSU: 벤더별 State 가 달라 `psu_active` 가 갈리고 원인이 봉투에 없다 | 05-thermal-power.md:121 | - |
| 05-thermal-001 | MED | 확정 | C10 | code-common | iLO legacy Thermal 의 `Absent` 슬롯 센서가 0 °C 로 `temperatures[]` 에 들어간다 | 05-thermal-power.md:171 | 메인 재현: dl380_gen12_01 temps 56 중 reading 0 = 9, raw Absent 7 |
| 05-thermal-002 | MED | - | C2 | code-common | 전원 Off 호스트(dl380_gen12_03): 온도 42건·팬 6건이 `UnavailableOffline` + 0 으로 "정상 수집" 된다 | 05-thermal-power.md:183 | - |
| 06-bmc-001 | MED | - | C11 | code-common | 복구 Family hint 가 "1차 선택 adapter_id" 라 Lenovo 세대 판정이 장비 값(Manager.Model)이 아니라 adapter 이름에 의존 | 06-bmc.md:105 | 메인 확인: resolve_account_family Lenovo 분기 :7623-7628 이 `'xcc3' in hint`(adapter 이름)로 세대를 가름; 06 교차 이슈 1 — 복구 hint 는 1차 선택값이라 01-adapter-001 규칙 B 와 무관 |
| 01-adapter-011 | LOW | 확정 | C1 | docs | 문서·시험이 Lenovo XCC3 adapter 를 "사이트 검증 PASS" 로 기록 — 1차 선택만 검증됐고 재선택은 미검증; HPE 펌웨어 패턴 가상 공백 | 01-system-hardware-multi-node.md:181 | - |
| 01-correlation-010 | LOW | 확정 | C6 | docs | `correlation.bmc_ip` 정의 문서화 — "BMC 가 보고한 첫 IPv4 NIC" 이며 대상 IP 와 다를 수 있음 | 01-system-hardware-multi-node.md:176 | 메인 관찰: correlation.bmc_ip 가 미러 BMC NIC 주소(원 장비 IP) |
| 01-hardware-004 | LOW | 확정 | C8 | code-common | Lenovo XCC3 `bios_date` null — `UpdateService/FirmwareInventory/UEFI.ReleaseDate` 가 있음 | 01-system-hardware-multi-node.md:131 | - |
| 01-hardware-005 | LOW | - | C4 | code-oem | Lenovo `hardware.oem` 9키 중 7키가 모든 Lenovo 캡처에서 null — 원천 키가 존재하지 않는 매핑 | 01-system-hardware-multi-node.md:140 | - |
| 01-multi_node-006 | LOW | - | C5 | code-common | CSUS 고정 경로 404 요청 11개(14건) — Chassis navigation property 를 보지 않는 Power/Thermal 탐색 | 01-system-hardware-multi-node.md:149 | 메인 재현: 접근 로그 RackGroup/Rack1 8건 404 + r001u01 Power/Thermal/EnvironmentMetrics 각 2회 |
| 01-multi_node-007 | LOW | 확정 | C5 | code-common | `composition.resource_blocks[].processor_count/memory_count = 0` — 원천 배열이 없을 때 0 은 거짓 값 | 01-system-hardware-multi-node.md:158 | - |
| 01-system-008 | LOW | 확정 | C5 | decision | `sections.system = not_supported` 인데 `data.system.hostname/fqdn` 은 내보냄 — 계약 정합 결정 필요 (CSUS 는 HostOS 로 더 채울 수 있음) | 01-system-hardware-multi-node.md:163 | - |
| 01-system-009 | LOW | 확정 | C5 | docs | ADR-2026-10-15 재검증 — "RMC 이름 = 서버 이름" 은 2차 3대에서 성립하지만 `hostname_source=system` 의미는 여전히 어긋남 | 01-system-hardware-multi-node.md:169 | - |
| 02-cpu-004 | LOW | 확정 | C6 | decision | `cpu.architecture` 가 Redfish `x86` vs OS/ESXi `x86_64` | 02-cpu-memory.md:120 | - |
| 02-cpu-005 | LOW | 확정 | C5 | decision | `multi_node.partitions[].cpu` 에 `turbo_max_mhz` 없음 (CSUS 7대) | 02-cpu-memory.md:125 | - |
| 02-cpu-006 | LOW | 확정 | C3 | observe | `cores_physical` 가 `TotalCores`(장착) 합, `TotalEnabledCores` 미사용 | 02-cpu-memory.md:130 | - |
| 02-cpu-007 | LOW | 확정 | C6 | docs | `field_dictionary.yml` 에 `cpu.logical_threads` · `cpu.sockets` · `cpu.model` 항목 없음 | 02-cpu-memory.md:134 | - |
| 02-memory-003 | LOW | 확정 | C4 | code-common | Lenovo `slots[].locator` 가 `MemoryLocation.Slot` 문자열(`"32"`), `ServiceLabel "DIMM 32"` 미사용 | 02-cpu-memory.md:163 | - |
| 02-memory-004 | LOW | 확정 | C8 | code-oem | CSUS `rank_count`/`error_correction` null (raw 키 없음) — OEM Label 로 rank 보충 가능 | 02-cpu-memory.md:172 | - |
| 02-memory-005 | LOW | 확정 | C6 | observe | `memory.summary.groups` 가 part_number 전체 문자열로 묶여 같은 모델이 접미사로 분리 (관찰) | 02-cpu-memory.md:177 | - |
| 03-network-002 | LOW | 확정 | C8 | code-common | 호스트 NIC 에 LinkStatus/SpeedMbps 가 없을 때 같은 MAC 의 `ports[]` 값을 쓰지 않아 `interfaces[].link_status='unknown'`·`speed_mbps=null` 로 남음 | 03-network-storage.md:110 | - |
| 03-network-003 | LOW | - | C4 | code-common | Lenovo XCC3 호스트 NIC `SpeedMbps` 가 Gbps×1024(25600/32768)라 같은 봉투의 `ports[].current_link_speed_mbps`(25000/32000)와 다르다 | 03-network-storage.md:120 | - |
| 03-network-004 | LOW | 확정 | C8 | code-common | `_normalize_port_speed` 가 `CurrentLinkSpeedMbps: 0` 은 0 으로 두고 `CurrentSpeedGbps: 0` 은 null 로 바꿔 링크 없는 포트 표기가 벤더별로 갈린다 | 03-network-storage.md:127 | - |
| 03-network-005 | LOW | 확정 | C4 | code-common | Lenovo `ToManager`(Redfish Host Interface USB NIC)가 `interfaces[]`·`summary.port_count` 에 서버 NIC 로 센다 | 03-network-storage.md:133 | - |
| 03-network-006 | LOW | - | C8 | code-common | `gather_network` 가 `IPv6Addresses` 를 읽지 않아 `addresses[]` 에 family ipv6 가 절대 없다 | 03-network-storage.md:138 | - |
| 03-network-007 | LOW | 확정 | C8 | code-common | `interfaces[].mtu` 가 18대 전부 null — 호스트 NIC 에 MTUSize 가 없고 Lenovo 는 NDF `Ethernet.MTUSize`(1500) 에만 있다 | 03-network-storage.md:142 | - |
| 03-storage-002 | LOW | 확정 | C6 | docs | `schema/field_dictionary.yml` 의 `storage.controllers[].driver` 가 channel `redfish` 를 포함하지만 Redfish 는 그 키를 내지 않는다 | 03-network-storage.md:146 | - |
| 03-storage-003 | LOW | 확정 | C8 | docs | `physical_disks[].wwn` 을 Redfish `Drive.Identifiers`(NAA) 로 채울 수 있는데 사전이 channel os/esxi 로 묶여 있어 비어 있다 | 03-network-storage.md:150 | - |
| 04-bios-001 | LOW | - | C8 | code-common | Lenovo `hardware.bios_date` null, 원천은 `FirmwareInventory/UEFI.ReleaseDate` | 04-firmware-bios.md:213 | 01-hardware-004 와 같은 내용(중복) |
| 04-bios-002 | LOW | 확정 | C6 | observe | `bios.current.attributes` 에 식별·네트워크 정보가 그대로 들어간다 (계약대로, 관찰) | 04-firmware-bios.md:224 | - |
| 04-bios-003 | LOW | 확정 | C5 | observe | CSUS `Bios/Settings` 에 실제 보류 차이 2건 + 주석 키 (계약 밖, 관찰) | 04-firmware-bios.md:231 | - |
| 04-firmware-004 | LOW | 확정 | C9 | category | FC HBA 분류가 벤더 간 다르다 (Dell 만 `storage_controller`) | 04-firmware-bios.md:128 | - |
| 04-firmware-005 | LOW | 확정 | C9 | category | CPLD/FPGA 등 잔여 `other` 와 `nvme` 토큰 오분류 | 04-firmware-bios.md:140 | - |
| 04-firmware-007 | LOW | 확정 | C5 | docs | CSUS 보충 항목의 `updateable` 이 null (사전 type boolean) | 04-firmware-bios.md:163 | - |
| 04-firmware-008 | LOW | 확정 | C6 | observe | Dell first-seen dedup 의 접두사 혼재 (관찰) | 04-firmware-bios.md:173 | - |
| 04-firmware-009 | LOW | - | C2 | observe | 전원 Off 스냅샷(dl380_gen12_03)의 13건은 raw 그대로, `updateable` 이 전원 상태를 따른다 | 04-firmware-bios.md:182 | - |
| 04-firmware-010 | LOW | 확정 | C4 | observe | Lenovo 버전 표기가 두 가지 (관찰) | 04-firmware-bios.md:191 | - |
| 04-firmware-011 | LOW | 확정 | C5 | docs | CSUS `hardware.bios_version == bmc.firmware_version`(complex 번들) · bios/bmc 항목 없음 | 04-firmware-bios.md:198 | - |
| 04-firmware-012 | LOW | 확정 | C6 | docs | 계약 문서에 `data.firmware` 절이 없고 category help 가 실제와 다르다 | 04-firmware-bios.md:207 | - |
| 05-power-003 | LOW | 확정 | C4 | code-common | Lenovo XCC3 PSU `model` 의 패딩 공백이 그대로 나간다 | 05-thermal-power.md:134 | - |
| 05-power-004 | LOW | - | C5 | code-common | CSUS multi_node 섀시 순회가 링크 없는 경로 11건을 요청하고 404 를 재요청한다 | 05-thermal-power.md:143 | 01-multi_node-006 과 같은 원인(중복) |
| 05-power-005 | LOW | 확정 | C6 | docs | `power_control.power_capacity_watts` 의 뜻이 벤더·경로별로 다른데 사전 정의가 없다 | 05-thermal-power.md:153 | - |
| 05-power-006 | LOW | 확정 | C6 | docs | `schema/field_dictionary.yml` 에 power/thermal 하위 키가 8개뿐이다 | 05-thermal-power.md:160 | - |
| 05-power-007 | LOW | - | C5 | docs | CSUS 소비전력 폴백 사슬의 정의 불일치: Telemetry = DC 출력 합, 최종 폴백 = AC 입력 합 | 05-thermal-power.md:164 | - |
| 05-thermal-003 | LOW | - | C10 | code-common | 신 schema(ThermalSubsystem) 경로의 잠재 공백 3종: 2차 raw 로 확인, 18대에선 미발동 | 05-thermal-power.md:195 | - |
| 05-thermal-004 | LOW | 확정 | C10 | observe | 음수 "온도" 항목: Lenovo `CPUn DTS TMargin`, CSUS `P*_THROT_OFFSET` | 05-thermal-power.md:204 | - |
| 05-thermal-005 | LOW | 확정 | C6 | docs | 문서·주석 drift 3건 | 05-thermal-power.md:210 | - |
| 06-bmc-002 | LOW | - | C11 | code-common | RMC 가 선언한 `@Redfish.WriteableProperties`(계정: `["Password"]`) 를 쓰기 계약에 쓰지 않음 — 2026-10-14 hotfix 의 미확인 항목("RMC 계정이 `Enabled` 를 GET 에서 노출하는가")은 7/7 미러로 답이 나옴 | 06-bmc.md:118 | - |
| 06-bmc-003 | LOW | 확정 | C11 | code-common | HPE iLO 7 `bmc.timezone` null — `Managers/1/DateTime`(`Oem.Hpe.Links.DateTimeService`) 에 `TimeZone {Name, Value, UtcOffset}` 가 있음 | 06-bmc.md:127 | - |
| 06-bmc-004 | LOW | 확정 | C11 | docs | `bmc.datetime` 표기가 벤더마다 다름(iLO: UTC `Z` + `datetime_offset` 분리 / XCC·RMC·iDRAC: 로컬시에 오프셋 포함) — 사전 문구 "datetime_offset 와 함께 해석" 이 모호 | 06-bmc.md:134 | - |
| 06-bmc-005 | LOW | 확정 | C11 | code-common | `bmc.ip/mac_address/dns_name` 선택 규칙이 EthernetInterfaces 컬렉션 순서에 의존("IPv4 가 있는 첫 NIC") — iLO 7 의 USB 가상 NIC(`16.1.15.1`)이 뒤에 있어 우연히 안전 | 06-bmc.md:141 | 메인 재현: 11/11 bmc.ip == correlation.bmc_ip == _manifest.host (현재 컬렉션 순서로 우연히 안전) |
| 06-bmc-006 | LOW | 확정 | C11 | code-common | `bmc.name` 이 adapter `manager_layout` 에만 의존 — CSUS 가 layout 없이 수집되면 `iLO`(장비 값 `ManagerType: RackManager`, `Id: RMC` 를 쓰지 않음) | 06-bmc.md:148 | - |
| 06-bmc-007 | LOW | 확정 | C11 | docs | `diagnosis.details` 의 Redfish 전용 키가 계약 문서·baseline 에 없고 `account_service` 의 미진입 shape(`{}`)가 정의돼 있지 않음 | 06-bmc.md:153 | - |
| 06-bmc-008 | LOW | - | C7 | test | `replay_full_mirror.install_fakes` 가 `redfish_gather._get`/`_get_noauth` 를 영구 교체하고 되돌리지 않음 — Tier 0 `test_redfish_multi_credential_auth.py` 순서 의존 실패 2건의 원인(제품 영 | 06-bmc.md:158 | 04-test-001 과 같은 원인(중복) |
| 06-bmc-009 | LOW | 확정 | C11 | docs | 사전 `bmc.uuid` 설명이 "Manager.UUID/ServiceIdentification" 인데 코드는 `UUID` 만 읽고 RMC 의 `ServiceIdentification` 은 UUID 가 아니다 | 06-bmc.md:165 | - |
| 06-bmc-010 | LOW | 확정 | C11 | code-common | 성공 경로의 `auth_success: true` 가 무조건이라 익명 수집(vendor 미식별 장비, `used_role: anonymous`) 성공도 "실제 인증 성공" 으로 보고된다 — 11대 해당 없음(코드 경로) | 06-bmc.md:169 | - |
| 02-memory-006 | ? | - | C6 | observe | `total_basis` 상수 `physical_installed` (관찰) | 02-cpu-memory.md:182 | - |

## 4. 중복·충돌 조정

- `01-multi_node-006` ≡ `05-power-004`: 같은 원인(섀시 순회 고정 경로·404 재요청) — C5 한 항목으로 수정, 두 ID 유지.
- `01-hardware-004` ≡ `04-bios-001`: Lenovo `bios_date` ← UEFI ReleaseDate — C8 한 항목.
- `02-memory-001`·`03-storage-001`·`05-power-001`·`05-thermal-002`·`04-firmware-009`: 같은 뿌리(전원 Off) — C2 의 공통 notice 한 문장 + 섹션별 placeholder 정리로 함께 처리.
- `01-hardware-002` 와 `05-thermal-005`(b)·05 교차 이슈 1: 같은 문서 오류(`hardware.health` rollup 서술) — C6 한 항목.
- `02-cpu-001` 과 `02-cpu-002`·`04` 교차 이슈 1: 같은 규칙 변경(HT 원천) — C3 에서 함께; `processor_summary_logical_count` 플래그의 운명은 그 규칙 설계에 종속.
- `03-network-001` 과 `04-firmware-004`(FC HBA 분류): 다른 층(네트워크 vs 펌웨어 category)이라 분리 유지.
- 충돌: `02-cpu-003` 은 '구현' 과 '사전에서 redfish 제거' 두 길 — 사용자 결정. `02-memory-002` 는 '계약 명시만' 과 'Label 기반 보정' 두 길 — 사용자 결정. `01-system-008` 은 `sections.system = not_supported` 인데 hostname/fqdn 발행 — 계약 결정.

## 5. ADR·정본 문서 정정 제안 (이번 단계에서는 수정하지 않음)

| 문서 | 현재 결정/문구 | 11대 실측 | 정정 제안 | 이슈 |
|---|---|---|---|---|
| ADR-2026-10-19-csus-single-server-and-summary-fixes 결정 3·A-2·대안 비교 | RMC `LogicalProcessorCount` = 코어 수 → adapter `cores` 플래그로 Σ 우선; `max(LPC,Σ)` 는 HT 비활성 과대집계라 기각 | RMC 1.77.30 은 LPC == Σthreads; csus3200_02 HT Disabled 인데 Σ=224 → 채택안도 과대집계 | 전제를 '펌웨어별 의미 다름' 으로 정정, HT 원천 규칙(C3) 반영 | 02-cpu-001/002 |
| ADR-2026-10-18 X3 | `ProcessorSummary.LogicalProcessorCount` 있으면 정본 | XCC 2.97 LPC 가 HT 를 반영하지 않음 | 'LPC 는 펌웨어에 따라 용량일 수 있다' 로 정정 | 02-cpu-001 |
| ADR-2026-05-12-csus-rmc-multi-node 결정 6 | 사이트 fixture 캡처 후 실측 baseline 교체 의무 | baseline·`03-fields.md §9` 예시가 여전히 mock(3 partition/4 manager/PCIe fabric) | 실 캡처(1차 01 또는 2차 01)로 교체 — 사용자 결정 | 01-multi_node-003 |
| ADR-2026-06-09-csus-model-completion | 각 chassis 는 Power 와 Thermal 리소스를 둔다 | 1.75.108·1.77.30 모두 r001u01 만 PowerSubsystem/ThermalSubsystem, 집합 섀시는 없음(재생 404) | 가정 정정 + 링크 gating | 01-multi_node-006, 05-power-004 |
| ADR-2026-10-19 A-9 (`controller` 토큰) | 포괄 토큰으로 storage_controller | 비디오 컨트롤러 포함, MegaRAID 누락 | 부작용 기록 + 토큰 재설계 | 04-firmware-002 |
| ADR-2026-10-15-csus-hostname-rmc-first | RMC 이름 = 서버 이름, `hostname_source=system` | 2차 3대 성립; `hostname_source` 의미 불일치만 | 문서 보강(모순 없음) | 01-system-009 |
| ADR-2026-05-29 / 2026-10-17 / 2026-10-18·19(hba link) | FC/IB 분류·link up/down 2값 | 2차 11대에서 분류 정확·IB 오탐 0·2값 준수 | 유지(검증됨) | 03 §6 |
| ADR-2026-06-04(vendor display)·(csus priority 102) | hp/hpCsus, CSUS 102 | 11대 일관, 재선택에서도 유지 | 유지 | 01 §6 |
| ADR-2026-06-14-thermal-single-node | 미지원 벤더 빈 {} | 18/18 수집됨; Absent/UnavailableOffline 규칙 부재 | 03-fields 6.7 규칙 추가 | 05-thermal-001/002 |
| `docs/contract/03-fields.md` 6.1·6.5 | `hardware.health` 는 BMC rollup, PSU 1대 fault → Critical | `Status.Health`(리소스) 이며 iLO 7 은 PSU Critical 인데 Warning | 서술 정정 + rollup 은 OEM 집계로 안내 | 01-hardware-002 |
| `docs/contract/03-fields.md` 6.2·6.3·6.4·6.7, `schema/field_dictionary.yml`, `EXTERNAL_CONTRACTS.md:11,54,15` | (각 보고서 §6 표) | (각 보고서 §6 표) | C6 문서 묶음 | 02/03/04/05 §6 |
| `docs/ai/catalogs/VENDOR_ADAPTERS.md:72,212`, `adapters/redfish/lenovo_xcc3.yml` 주석 | XCC3 사이트 검증 PASS | 1차 선택만 검증, 재선택은 강등 | 정정 | 01-adapter-011 |

## 6. 미확정·검증 불가 (실장비·OS 실측 또는 사용자 결정 필요)

- 02-cpu-001 의 '기대 = 코어 수' — HT Disabled 5대(csus3200_02, dl380_gen12_03, sr650_v4_01/02/04)의 OS/ESXi 논리 CPU 실측이 없다.
- 전원 Off 인과(C2) — iLO 7 1대 대조 기반 가설; XCC/iDRAC 의 전원 Off 모양 미확인. dl380_gen12_03 전원 On 후 재수집으로 확정.
- CSUS 집합 섀시 고정 경로 11개의 실장비 응답(미러에 없음, 재생 404) — 링크 gating 적용 시 의존 소멸.
- 재생 한계(`baseline/README.md` 1~9): 익명 허용 범위, 비밀번호 검증·401/403·계정 복구, timeout, 미기록 경로, v1 비-2xx, WWW-Authenticate, Ansible 2.20.7 vs 2.20.3.
- 1차 축약 fixture 의 Lenovo `-Pending`·DL380 Absent 0 °C 는 golden 이 '정상' 으로 고정 — 수정 시 golden 갱신 필요(사용자 승인, rule 21 R3).
- Superdome Flex(`hpe_superdome_flex.yml`) 는 실측 0 — CSUS 플래그 복제의 타당성 미확인.
- `hardware.uuid` 바이트 순서 vs OS/ESXi 같은 장비 캡처 없음(MOCK_LIMITATION).

## 7. 사용자 결정 항목

1. C3 적용 전 OS/ESXi 실측 확보 여부(5대) 및 `processor_summary_logical_count` 플래그 처분.
2. `02-cpu-003` cpu.manufacturer: 구현 vs 사전 정정. `02-cpu-004` architecture 표기 통일 여부.
3. `02-memory-002` DIMM 속도: 계약 명시만 vs Label 기반 MT/s 보정.
4. `01-system-008` Redfish `data.system.hostname/fqdn` 발행과 `sections.system=not_supported` 의 정합; CSUS `HostOS` 활용 여부.
5. `01-multi_node-003` CSUS baseline·계약 예시를 실 캡처로 교체(어느 캡처로).
6. `01-multi_node-007` composition count 0 → null.
7. `04-firmware-004` FC HBA category enum 확장(`hba`) 여부 — enum 확장은 계약 변경.
8. Tier 1 미러 재생 HTTPS 서버·2차 축약 fixture(`real_*` 자동 등록)의 저장소 편입.
9. golden 갱신 범위(`real_hpe_dl380` temps 52→43, `real_lenovo_sr650` -Pending 2건, 1차 bios None).
10. `data.users` 를 BMC 계정으로 채울지(계약·의미 변경 — 06 보고서 관찰, 기본은 유지).
