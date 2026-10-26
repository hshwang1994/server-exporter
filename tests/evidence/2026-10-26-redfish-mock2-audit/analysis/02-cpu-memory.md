# 02. cpu / memory — 2차 Redfish Mock 11대 분석 (2026-10-26)
모델: claude-fable-5-1 (Claude Fable 5.1, effort=max) / worktree: `C:/github/ClovirONE/clovirone-server-gathering/.claude/worktrees/agent-a3624a59817ca52dd` / 브랜치: `worktree-agent-a3624a59817ca52dd` (main `e8b5ae9b` 기준, 코드 변경 0)

담당 필드: `data.cpu.{architecture, cores_physical, logical_threads, max_speed_mhz, model, sockets, summary(groups[]), turbo_max_mhz}`,
`data.memory.{free_mb, installed_mb, slots[], summary(groups[], grand_total_gb), total_basis, total_mb, visible_mb}`.
근거 우선순위: 11대 Mock 추출본(`C:/github/ClovirONE/mock2-audit-20261026/extract/<server>/`) + 1차 7대 미러(`C:/github/서버mock데이터/1차/`) 의 실제 응답 > Tier 1 envelope(`EVID/baseline/tier1/<label>/gather_output.json`) > Tier 2 모듈 출력 > 코드/ADR/계약.
기계 판독용 표: `02-cpu-memory.coverage.json` (18 label × 필드, `_area` 포함).

## 1. 요약
- 이슈 12건 — **HIGH 1 / MED 4 / LOW 7**. 11대 Tier 1 의 cpu·memory 수치는 raw 와 1:1 로 맞고(소켓·코어·스레드 합·DIMM 합·MemorySummary 가 18/18 일치), 문제는 **값의 뜻**에서 난다.
- [ISSUE] HIGH `02-cpu-001`: BIOS 에서 Hyper-Threading 을 끈 5대(csus3200_02 · dl380_gen12_03 · sr650_v4_01/02/04)에서 `cpu.logical_threads` 가 코어의 2배(224 / 128 / 128 / 128 / 128)다. BMC 의 `TotalThreads` 는 "지원 스레드 수" 이고, 2차 펌웨어(XCC 2.97 · RMC 1.77.30)의 `ProcessorSummary.LogicalProcessorCount` 도 그 합과 같아서 HT 상태를 반영하지 않는다. 이미 수집하는 `data.bios.current.attributes`(`HThread` / `ProcHyperthreading` / `Processors_Hyper_Threading` / Dell `LogicalProc`) 와 DMTF `ProcessorSummary.ThreadingEnabled` 를 보지 않는다. (추정 — OS 실측 없음, BIOS 현재값·pending 값 모두 Disabled 로 확인)
- [ISSUE] MED `02-cpu-002`: ADR-2026-10-19 A-2 의 전제 "RMC 의 `LogicalProcessorCount` 는 코어 수" 는 RMC 1.75.108(1차 4대) 에서만 성립. 2차 RMC 1.77.30 3대는 `ΣTotalThreads` 와 같다(128 / 224 / 128). adapter 플래그 `processor_summary_logical_count: cores` 는 펌웨어 버전 의존이며, ADR 이 "대안 비교" 에서 우려한 "HT 비활성 장비 과대집계" 가 csus3200_02 에서 실제로 일어났다.
- [ISSUE] MED `02-cpu-003`: `schema/field_dictionary.yml` 은 `cpu.manufacturer` 를 `channel: [redfish, os, esxi]` 로 선언하는데 Redfish envelope 은 그 키를 내지 않는다(18/18, baseline 4종도 없음). `summary.groups[].manufacturer` 는 raw `"Intel(R) Corporation"`/`"Intel"` 그대로라 OS(`Intel`) 와 표기가 다르다.
- [ISSUE] MED `02-memory-001`: dl380_gen12_03(PowerState Off · System State Disabled)은 빈 슬롯 16개가 `Status` 키 없이(`CapacityMiB 0`, `Oem.Hpe.DIMMStatus "Other"`) 내려와 `State == 'Absent'` 필터를 통과 → `memory.slots[]` 32개(장착 16) 로 출력.
- [ISSUE] MED `02-memory-002`: HPE CSUS RMC 의 `Memory.OperatingSpeedMhz` 는 실클럭(2차 3200 · 1차 2400)이고 iLO/XCC/iDRAC 는 MT/s(6400 / 6400 / 2933) 라서 같은 DDR5-6400 모듈이 `slots[].speed_mhz` 3200 vs 6400 으로 갈린다(`Oem.Hpe.Label "PC5-6400B"` 가 MT/s 를 증명). 계약 6.2 "단위 변환 없음" 대로지만 채널·벤더 간 비교 불가.
- 그 밖 LOW: `architecture` 표기(`x86` vs OS `x86_64`), `multi_node.partitions[].cpu` 에 `turbo_max_mhz` 부재, `cores_physical` 가 `TotalEnabledCores` 미사용(잠재), 사전에 `cpu.logical_threads/sockets/model` 미등재, Lenovo `locator` 가 `ServiceLabel "DIMM 32"` 대신 `"32"`, CSUS `rank_count` null(OEM Label `1Rx4` 로 보충 가능), summary 그룹이 Micron 파트 접미사로 분리.
- 11대 한 줄: CSUS 3대 cpu PASS/ISSUE(02 만 HT) · memory ISSUE(속도 단위, rank); DL380 4대 cpu 01/02/04 PASS · 03 ISSUE(HT) · memory 01/02/04 PASS · 03 ISSUE(빈 슬롯); SR650 V4 4대 cpu 01/02/04 ISSUE(HT) · 03 PASS · memory PASS(locator LOW). `free_mb`/`visible_mb` 는 11대 모두 NOT_APPLICABLE(raw 에 값 없음, 계약대로 null).

## 2. 필드별 수집 흐름 (진입 → 요청 경로/폴백 → 파서 → 정규화 → 출력)
공통 진입: `redfish-gather/library/redfish_gather.py` `main()` → `_collect_all_sections()`(`:6539`) 가 `_run('processors', gather_processors, …)`(`:6583`) · `_run('memory', gather_memory, …)`(`:6584`) 를 System URI(`Systems/<첫 멤버>`: CSUS `Partition0`, iLO/XCC `1`, iDRAC `System.Embedded.1`) 에 대해 호출. `_make_section_runner`(`:5645`) 는 오류 전부 404 + 빈 결과일 때만 `unsupported`. 요청은 전부 Basic 인증 200(`server_access.jsonl` 의 `p` 에 `Processor|Memory` 포함 레코드 — 18 label 모두 `(200,'basic')` 만, 404/401 0건; CSUS 38/22/22 · iLO 36 · XCC 36 · iDRAC 12 건).

| 출력 필드 | 요청 경로 | 파서(모듈) | 정규화(`redfish-gather/tasks/normalize_standard.yml`) | 비고 |
|---|---|---|---|---|
| `cpu.sockets` | `{sys}/Processors` 컬렉션 → 멤버별 GET(`_collection_members` `:1225`, nextLink 64p/1024멤버) | `gather_processors` `:2996` — `Status.State` Absent/Disabled 제외(`:3022`), 키: id/name/model/manufacturer/socket/total_cores/total_threads/speed_mhz/max_speed_mhz/health/processor_type/architecture/instruction_set/serial/part | `_rf_d_cpus` = `ProcessorType ∈ {CPU, CORE, ''}` 필터(`:28-40`) → `sockets = len` (`:608`, 비면 `ProcessorSummary.Count`) | 18대 전부 `ProcessorType "CPU"`; CSUS `SubProcessors`(Core)·`Ports`(UPI)는 별도 컬렉션이라 미포함 |
| `cpu.cores_physical` | 위와 같음 | `TotalCores` → `total_cores` (`:3039`) | Σ`total_cores` → 0 이면 `ProcessorSummary.CoreCount` (`:612-614`) | `TotalEnabledCores`(Lenovo/Dell) · `Oem.Hpe.CoresEnabled` · `Oem.Lenovo.NumberOfEnabledCores` 미사용 |
| `cpu.logical_threads` | 위 + `{sys}` 본문의 `ProcessorSummary.LogicalProcessorCount`(`gather_system` `:2643-2654`) | `TotalThreads` → `total_threads` (`:3040`) | `:621-628`: adapter `vendor_notes.processor_summary_logical_count == 'cores'` 면 Σ`total_threads` 우선(없을 때 LPC), 아니면 LPC 우선(없으면 Σ) | BIOS HT 속성(`gather_bios` `:2721` 가 이미 수집) 미참조 — `02-cpu-001` |
| `cpu.model` | 위 | `Model` strip (`:3035`) | 첫 CPU `model`, 비면 `ProcessorSummary.Model` (`:635-637`) | 공백/상표 정리 로직 없음 — 18대 raw 가 이미 깨끗함 |
| `cpu.max_speed_mhz` | 위 | `_cpu_base_speed_mhz` `:741-767`: `BaseSpeedMHz` → `Oem.Hpe.RatedSpeedMHz` → 브랜드 `@ N.NNGHz` → `OperatingSpeedMHz` → `Oem.Lenovo.CurrentClockSpeedMHz` | 첫 CPU `speed_mhz` (`:640-641`) | CSUS Base(2900/2000/3700) · iLO Rated(2900/3000) · XCC Current(2900/3600) · iDRAC 브랜드(2400) — Intel 공개 사양 base 와 전부 일치 |
| `cpu.turbo_max_mhz` | 위 | `MaxSpeedMHz` (`:3044`) | 첫 CPU `max_speed_mhz` (`:642-643`) | 4000/3500/4100/4000/4300 — 사양 turbo 와 일치(Dell 8260 만 BMC 4000 vs 사양 3900, field_dictionary 가 이미 ±100 주석) |
| `cpu.architecture` | 위 | `ProcessorArchitecture`/`InstructionSet` (`:3047-3048`) | 첫 CPU `architecture`, 없으면 `instruction_set` (`:644-645`) | 18대 전부 `x86`(InstructionSet `x86-64` 는 쓰이지 않음) |
| `cpu.summary.groups[]` | 위 | — | `_rf_summary_cpu` `:247-274`: model 로 묶어 sockets/total_cores/`cores_per_socket = total // sockets`(B-11) + manufacturer/max_speed_mhz/architecture | `l2_cache_kb`/`l3_cache_kb` 키는 Redfish 그룹에 없음(OEM 에 값 있음 — §5) |
| `memory.slots[]` | `{sys}/Memory` 컬렉션 → 멤버별 GET | `gather_memory` `:3060-3144` — `Status.State == 'Absent'` 만 제외(`:3085`), `CapacityMiB` None 보존(MEM-01), `locator = DeviceLocator → str(Slot) if truthy → Location.PartLocation.ServiceLabel → str(Slot)`(`:3113-3116`), `speed_mhz = OperatingSpeedMhz`(`:3120`), `manufacturer = _normalize_jedec`(`:1355`, `filter_plugins/jedec_mapper.py` 와 drift guard), rank/data/bus/ECC/health | `_rf_d_memory.slots` 그대로 (`:662`) | `Status` 키 자체가 없는 슬롯은 통과 — `02-memory-001` |
| `memory.total_mb` / `installed_mb` | 위 + `MemorySummary.TotalSystemMemoryGiB` (`:2656`) | `total_mib` = Σ`CapacityMiB`(None 있으면 합계 None + notice/오류, C5) | `:650-659`: `total_mib` → 0/None 이면 `TotalSystemMemoryGiB × 1024` → null; `installed_mb` 는 같은 식 | 18/18 Σ == GiB×1024 (fallback 미발동) |
| `memory.total_basis` | — | — | `'physical_installed'` 상수 (`:655`) | fallback 경로에서도 같은 값(관찰) |
| `memory.summary` | 위 | — | `_rf_summary_memory` `:276-307`: `(GB반올림, type, speed_mhz, manufacturer, part_number)` 키로 그룹, `cap_gb > 0` 만, `grand_total_gb` 는 그룹 합 → 없으면 total_mb 원천(B-1) | part_number 전체 문자열이 키 — `02-memory-005` |
| `memory.visible_mb` / `free_mb` | — | — | `null` 상수 (`:660-661`) | raw 에 해당 값 없음(§3) |
| `multi_node.partitions[].cpu/memory` (CSUS 7대) | `gather_systems_multi` `:5993` → 같은 `gather_processors/gather_memory` | — | Python `_normalize_cpu_raw` `:5910-5949`(Σ`total_threads` 고정, `turbo_max_mhz` 없음) · `_normalize_memory_raw` `:5951-5991`(자기 partition MemorySummary 로만 fallback) | 7대 모두 top-level 과 값 동일(키만 `turbo_max_mhz` 차이 — `02-cpu-005`) |

Tier 1 envelope 의 `data.cpu`/`data.memory` 와 Tier 2 모듈 출력(`processors[]`/`memory{total_mib, slots}`)은 18 label 전부 위 식대로 대응됐다(§10 의 대조 스크립트로 Σ코어/Σ스레드/Σ용량/present 슬롯 수/MemorySummary 를 자동 비교 — FLAGS 0건).

## 3. 11대 × 필드 검증 상태 표
상태 태그: `[PASS]` 값·의미 모두 raw 와 일치 / `[ISSUE]` 이슈 ID 참조 / `[N/A]` 데이터 없음을 raw 로 확인(자동 PASS 아님) / `[LIMIT]` 재생·Mock 한계로 미확정.

### cpu
| server (fw) | sockets | cores_physical | logical_threads | max_speed_mhz | turbo_max_mhz | model / architecture | summary.groups[] | manufacturer(사전 선언) |
|---|---|---|---|---|---|---|---|---|
| csus3200_01 (RMC 1.77.30) | [PASS] 4 | [PASS] 64 | [PASS] 128 = Σ64×2, LPC 128, HThread Enabled — ADR 전제 불성립(02-cpu-002, 출력 동일) | [PASS] 2900 (BaseSpeedMHz) | [PASS] 4000 | [PASS] `Platinum 8444H Processor` / `x86` | [PASS] 1그룹 4/16/64 | [ISSUE] 02-cpu-003 키 없음 |
| csus3200_02 (RMC 1.77.30) | [PASS] 4 | [PASS] 112 | [ISSUE] 02-cpu-001: 224 인데 `HThread: Disabled`(Bios/Settings 도) → 112 기대 | [PASS] 2000 | [PASS] 3500 | [PASS] `Platinum 8450H Processor` / `x86` | [PASS] 1그룹 4/28/112 | [ISSUE] 02-cpu-003 |
| csus3200_03 (RMC 1.77.30) | [PASS] 4 | [PASS] 64 | [PASS] 128 (HThread Enabled) | [PASS] 2900 | [PASS] 4000 | [PASS] | [PASS] | [ISSUE] 02-cpu-003 |
| dl380_gen12_01 (iLO 1.24.00) | [PASS] 2 | [PASS] 64 | [PASS] 128 (LPC 없음 → Σ, ProcHyperthreading Enabled) | [PASS] 2900 (Oem.Hpe.RatedSpeedMHz) | [PASS] 4000 | [PASS] `Xeon(R) 6737P` / `x86` | [PASS] 1그룹 2/32/64 | [ISSUE] 02-cpu-003 |
| dl380_gen12_02 (iLO 1.24.00) | [PASS] 2 | [PASS] 64 | [PASS] 128 | [PASS] 2900 | [PASS] 4000 | [PASS] | [PASS] | [ISSUE] 02-cpu-003 |
| dl380_gen12_03 (iLO 1.24.00, PowerState Off) | [PASS] 2 | [PASS] 64 | [ISSUE] 02-cpu-001: 128 인데 `ProcHyperthreading: Disabled`(Bios/Settings 도) → 64 기대 | [PASS] 2900 | [PASS] 4000 | [PASS] | [PASS] | [ISSUE] 02-cpu-003 |
| dl380_gen12_04 (iLO 1.24.00) | [PASS] 2 | [PASS] 64 | [PASS] 128 | [PASS] 2900 | [PASS] 4000 | [PASS] | [PASS] | [ISSUE] 02-cpu-003 |
| sr650_v4_01 (XCC 2.97) | [PASS] 2 | [PASS] 64 (=TotalEnabledCores) | [ISSUE] 02-cpu-001: LPC 128 = Σ128 인데 `Processors_Hyper_Threading: Disabled`(Bios/Pending 도) → 64 기대 | [PASS] 2900 (Oem.Lenovo.CurrentClockSpeedMHz, 5순위) | [PASS] 4000 | [PASS] `Xeon(R) 6737P` / `x86` | [PASS] 1그룹 2/32/64 | [ISSUE] 02-cpu-003 |
| sr650_v4_02 (XCC 2.97) | [PASS] 2 | [PASS] 64 | [ISSUE] 02-cpu-001 (Disabled) | [PASS] 2900 | [PASS] 4000 | [PASS] | [PASS] | [ISSUE] 02-cpu-003 |
| sr650_v4_03 (XCC 2.97) | [PASS] 2 | [PASS] 64 | [PASS] 128 (Enabled) | [PASS] 2900 | [PASS] 4000 | [PASS] | [PASS] | [ISSUE] 02-cpu-003 |
| sr650_v4_04 (XCC 2.97) | [PASS] 2 | [PASS] 64 | [ISSUE] 02-cpu-001 (Disabled) | [PASS] 2900 | [PASS] 4000 | [PASS] | [PASS] | [ISSUE] 02-cpu-003 |

### memory
| server | total_mb / installed_mb | total_basis | slots[] | summary | free_mb / visible_mb |
|---|---|---|---|---|---|
| csus3200_01 | [PASS] 1,048,576 = Σ32×32768 = 1024 GiB×1024 | [PASS] | [ISSUE] 02-memory-002(speed 3200 = 실클럭, Label PC5-6400B) · 02-memory-004(rank/ECC null — raw 키 없음) · locator=ServiceLabel `rack1/chassis_u1/cpu0/dimmA0` 정상 · Samsung 32 | [ISSUE] groups[].speed_mhz 3200 (같은 원천) — 32GB×32=1024 정확 | [N/A] raw 에 값 없음 |
| csus3200_02 | [PASS] 524,288 (16 DIMM) | [PASS] | [ISSUE] 02-memory-002 · 004 | [ISSUE] 동일 | [N/A] |
| csus3200_03 | [PASS] 524,288 (16 DIMM) | [PASS] | [ISSUE] 02-memory-002 · 004 | [ISSUE] 동일 | [N/A] |
| dl380_gen12_01 | [PASS] 1,572,864 (16×96 GiB) = 1536 GiB | [PASS] | [PASS] present 16/32 (Absent 16 제외), Micron→`Micron Technology`, rank 2 · DW 64 · BW 80 · MultiBitECC · locator `PROC 1 DIMM n` | [PASS] 96GB×16 | [N/A] |
| dl380_gen12_02 | [PASS] 262,144 (8×32 GiB) | [PASS] | [PASS] present 8/32, Hynix→`SK hynix` | [PASS] | [N/A] |
| dl380_gen12_03 | [PASS] 524,288 (16×32 GiB; MemorySummary 512 GiB 일치) | [PASS] | [ISSUE] 02-memory-001: 32개 출력(16개는 `Status` 없음·cap 0·type/mfr/pn/serial null·`DIMMStatus Other`) | [PASS] cap 0 제외라 32GB×16 정확 | [N/A] |
| dl380_gen12_04 | [PASS] 262,144 | [PASS] | [PASS] present 8/32 | [PASS] | [N/A] |
| sr650_v4_01 | [PASS] 131,072 (2×64 GiB) | [PASS] | [ISSUE-LOW] 02-memory-003: locator `"23"`/`"32"`(Slot) — ServiceLabel `DIMM 23` 미사용; Absent 30 제외 정상; SingleBitECC · rank 2 | [PASS] 64GB×2 | [N/A] |
| sr650_v4_02 | [PASS] 131,072 | [PASS] | [ISSUE-LOW] 02-memory-003 | [PASS] | [N/A] |
| sr650_v4_03 | [PASS] 1,048,576 (16×64 GiB) | [PASS] | [ISSUE-LOW] 02-memory-003 | [PASS] 64GB×16 | [N/A] |
| sr650_v4_04 | [PASS] 262,144 (8×32 GiB) | [PASS] | [ISSUE-LOW] 02-memory-003 | [PASS] 32GB×8 이 접미사 `3SFF` 5 / `2XCC` 3 로 2그룹(02-memory-005 관찰) | [N/A] |

1차 7대: 값 수준 전부 [PASS](§8) — 단 r1_HPE_CSUS3200_01..04 는 02-memory-002(2400 = 실클럭, Label PC5-4800B)·004, r1_Lenovo_SR650_01 은 02-memory-003 에 해당. `multi_node.partitions[0].cpu/memory` 는 CSUS 7대 모두 top-level 과 값 동일(02-cpu-005 키 차이만).

## 4. 이슈 목록

### 02-cpu-001 — HT 비활성 장비에서 `cpu.logical_threads` 가 코어의 2배
- 심각도: **HIGH** (수치 자체가 틀릴 가능성; 3채널 공통 정의 "논리 프로세서 수" 와 충돌). 데이터 확실성: **추정** — BIOS 현재값과 pending 값(`Bios/Settings`·`Bios/Pending`) 모두 Disabled 로 확인했으나 OS/ESXi 실측(`/proc/cpuinfo`, `ansible_processor_vcpus`)이 Mock 에 없다.
- 대상: csus3200_02, dl380_gen12_03, sr650_v4_01, sr650_v4_02, sr650_v4_04 (5/11). 1차 7대·Dell R740 은 전부 HT Enabled 라 해당 없음.
- 필드: `data.cpu.logical_threads` (+ CSUS `data.multi_node.partitions[].cpu.logical_threads`).
- 근거(Mock 상대 경로):
  - csus3200_02: `redfish/v1/Systems/Partition0/Bios` `Attributes.HThread = "Disabled"` (`…/Bios/Settings` 도 Disabled); `…/Partition0` `ProcessorSummary.LogicalProcessorCount = 224`; `CompositionService/ResourceBlocks/r001u01/Systems/1/Processors/0..3` `TotalCores 28 · TotalThreads 56` ×4.
  - dl380_gen12_03: `Systems/1/Bios` `ProcHyperthreading = "Disabled"` (`Bios/Settings` 도); `Systems/1/Processors/1,2` `TotalCores 32 · TotalThreads 64`, `Oem.Hpe.CoresEnabled 32`; `ProcessorSummary` 에 LPC 없음.
  - sr650_v4_01/02/04: `Systems/1/Bios` `Processors_Hyper_Threading = "Disabled"` (`Bios/Pending` 도); `ProcessorSummary.LogicalProcessorCount = 128`; `Processors/1,2` `TotalCores 32 · TotalEnabledCores 32 · TotalThreads 64`.
  - 대조군: sr650_v4_03(Enabled, 128) · csus3200_01/03(Enabled, 128) · dl380 01/02/04(Enabled) · r1_DELL_R740_01(`LogicalProc Enabled`, `ProcessorSummary.ThreadingEnabled true`, LPC 96 = Σ96).
- 코드: `normalize_standard.yml:621-628`(LPC 우선 / adapter `cores` 플래그면 Σ 우선), `redfish_gather.py:3040`(`TotalThreads` 그대로), `:5910-5949` `_normalize_cpu_raw`(Σ 고정), `:2643-2654` `cpu_summary`(ThreadingEnabled 미수집), `:2721` `gather_bios`(HT 속성은 이미 `data.bios.current.attributes` 에 있음).
- 실제 출력 / 기대: 224 / 112(csus3200_02), 128 / 64(dl380_gen12_03, sr650_v4_01/02/04).
- 원인(확정 부분): DMTF `Processor.TotalThreads` 는 "이 프로세서가 지원하는 실행 스레드 수"(용량)이고, XCC 2.97·RMC 1.77.30 의 `ProcessorSummary.LogicalProcessorCount` 는 그 합과 항상 같다(HT Disabled 장비에서도 128/224). 코드는 둘 중 하나를 고를 뿐 HT 상태 원천을 보지 않는다. (가설: iDRAC 은 `ThreadingEnabled` 를 반영해 LPC 를 줄일 가능성 — Dell HT-off 실측 없음.)
- 영향: HT 를 끄는 DB/보안 워크로드 서버(2차 11대 중 5대)의 스레드 수 과대 → Portal 비교(OS/ESXi 채널은 실제 논리 CPU) 불일치, `test_cross_channel_same_server` 취지 위반. CSUS 는 `multi_node.partitions[].cpu` 도 같은 값.
- 수정 제안(기존 필드, 공통 로직): HT 상태를 알면 그것이 정본 — (1) DMTF `ProcessorSummary.ThreadingEnabled`(있으면) → (2) BIOS 속성(현재값) 중 adapter `vendor_notes` 가 지정한 키(예 `bios_hyperthreading_attribute: Processors_Hyper_Threading`, 값 `Disabled`/`Enabled` — 값으로 가르고 vendor 이름으로 가르지 않음) → Disabled 면 `logical_threads = cores_physical`, Enabled/미상이면 종전 규칙. 같은 규칙을 `_normalize_cpu_raw` 에도. Cisco CIMC 4.1 사례(ΣTotalThreads 44 = 코어, ESXi 88, HT Enabled)는 Enabled 경로라 불변.
- 회귀 테스트 제안: `tests/unit/test_cross_channel_value_fixes.py` 에 5대 축약 fixture(ProcessorSummary + Processors + Bios 속성)로 "Disabled → cores" · "Enabled → 종전" · "속성 없음 → 종전" 3분기; `tests/integration/test_redfish_csus_single_server_render.py` 에 csus3200_02 케이스(224→112); Dell `ThreadingEnabled true` 불변 케이스.
- ADR 영향: ADR-2026-10-18(X3 "LPC 있으면 정본") · ADR-2026-10-19(A-2) 정정 필요(§6). 문서: `docs/contract/03-fields.md:552-554`, `schema/field_dictionary.yml:1699-1707`, `docs/ai/catalogs/EXTERNAL_CONTRACTS.md:11,54`.

### 02-cpu-002 — ADR-2026-10-19 A-2 전제(RMC `LogicalProcessorCount` = 코어 수)가 RMC 1.77.30 에서 불성립
- 심각도: **MED** (현재 출력은 우연히 같음 — 플래그가 Σ 를 고르고 1.77.30 LPC 도 Σ). 확실성: **확정**.
- 대상: csus3200_01/02/03 (RMC `1.77.30-20260911`) vs r1_HPE_CSUS3200_01..04 (RMC `1.75.108-20260408`).
- 필드: `cpu.logical_threads`; adapter `adapters/redfish/hpe_csus_3200.yml` `vendor_notes.processor_summary_logical_count: cores`, `hpe_superdome_flex.yml:68`(실측 없이 복제).
- 근거: 1차 `Systems/Partition0.ProcessorSummary.LogicalProcessorCount` = 32/32/64/64 (= Σ`TotalCores`), 2차 = 128/224/128 (= Σ`TotalThreads`). `Managers/RMC.FirmwareVersion` 1.75.108 vs 1.77.30, `UpdateService` 번들 이름 동일(`Complex Firmware`, `Npar 0 Current Firmware`).
- 코드: `normalize_standard.yml:615-628`; `tests/integration/test_redfish_csus_single_server_render.py:54-60`(“RMC 는 코어 수를 LogicalProcessorCount 로 낸다 (실측)” 라고 단정), `tests/unit/test_cross_channel_value_fixes.py:128-151`.
- 실제/기대: 출력 128/224/128 — 02-cpu-001 반영 시 csus3200_02 는 112.
- 원인: ADR 당시 자료가 1.75.108 4노드뿐이었고 펌웨어 의존성을 가정하지 않음. "대안 비교" 에서 `max(LPC, Σ)` 를 "HT 비활성 과대집계" 이유로 기각했는데, 채택한 플래그도 같은 과대집계를 낸다(csus3200_02).
- 영향: 플래그의 설명·테스트 문구가 사실과 다름; Superdome Flex 복제 플래그는 두 펌웨어 중 어느 쪽도 실측 없음.
- 수정 제안: 02-cpu-001 의 HT 규칙이 들어가면 플래그는 "LPC 를 신뢰하지 않음(펌웨어별 의미 다름)" 으로 의미를 바꾸거나 제거 검토. 문서·테스트 문구는 "RMC 1.75.108 에서 코어 수, 1.77.30 에서 스레드 합" 으로 정정.
- 회귀 테스트: 1차·2차 CSUS fixture 쌍으로 플래그 유무와 무관하게 HT 규칙 결과가 같아지는지.
- ADR 영향: ADR-2026-10-19 결정 3·대안 비교, `EXTERNAL_CONTRACTS.md:11`, `03-fields.md:552-554`, field_dictionary `cpu.summary` help.

### 02-cpu-003 — `cpu.manufacturer` 사전 선언·Redfish 미발행, `groups[].manufacturer` 비정규화
- 심각도: **MED** (사전-구현 drift; nice 필드). 확실성: **확정**.
- 대상: 11대 + 1차 7대 전부(Redfish 채널 공통). 필드: `cpu.manufacturer`(사전 `schema/field_dictionary.yml:2709-2714` channel `[redfish, os, esxi]`), `cpu.summary.groups[].manufacturer`.
- 근거: Tier 1 `data.cpu` 키 = sockets/cores_physical/logical_threads/model/max_speed_mhz/turbo_max_mhz/architecture/summary (18/18 `manufacturer` 없음); `schema/baseline_v1/{dell,hpe,lenovo,cisco,hpe_csus_3200}_baseline.json` 도 없음; OS/ESXi baseline 은 있음(`Intel`). raw `Processor.Manufacturer`: iLO/XCC/RMC `"Intel(R) Corporation"`, iDRAC `"Intel"`, `ProcessorId.VendorId` `GenuineIntel`(Dell/RMC).
- 코드: `normalize_standard.yml:605-646`(cpu 블록에 manufacturer 없음), `:265`(groups 에 raw 그대로); OS 정규화 규칙 `os-gather/tasks/linux/gather_cpu.yml:106-112`(`GenuineIntel→Intel`, `AuthenticAMD→AMD`), `windows/gather_cpu.yml:94-98`.
- 실제/기대: 키 없음 / `"Intel"`(사전: "정규화값 (Intel / AMD)"); groups `"Intel(R) Corporation"` / `"Intel"`.
- 원인: 2026-09-03 OS/ESXi 전수 검수 때 사전에 redfish 채널을 넣었으나 normalize_standard 에 구현되지 않음(`tests/unit/test_field_dictionary_channel_emit.py` 는 cpu.manufacturer 를 검사하지 않음).
- 영향: 호출자가 사전대로 `cpu.manufacturer` 를 기대하면 Redfish 결과에서 KeyError/None; 채널 간 그룹 표기 불일치.
- 수정 제안(기존 필드): cpu 블록에 `manufacturer`(첫 CPU `manufacturer` 를 OS 와 같은 표로 정규화: `Intel`·`AMD`, 그 밖은 원문) 추가, groups 도 같은 정규화. 영향 벤더 전부(값 추가만). baseline 4종 갱신.
- 회귀 테스트: `test_field_dictionary_channel_emit.py` 에 "redfish 로 선언된 cpu.* 키가 normalize_standard cpu 블록에 존재" 검사; 렌더 테스트로 `Intel(R) Corporation → Intel`.
- ADR 영향: 없음(사전 drift). 문서: `docs/contract/03-fields.md` 6절 cpu 예시.

### 02-cpu-004 — `cpu.architecture` 가 Redfish `x86` vs OS/ESXi `x86_64`
- 심각도: **LOW** (priority skip). 확실성: **확정**(raw `ProcessorArchitecture "x86"`, `InstructionSet "x86-64"` 18/18; OS/ESXi baseline `x86_64`).
- 대상: 18대 전부. 코드: `redfish_gather.py:3047-3048`, `normalize_standard.yml:644-645`(ProcessorArchitecture 우선). 사전 `cpu.architecture` help "예: x86_64".
- 실제/기대: `x86` / 채널 공통 어휘 미정 — 결정 항목. 제안: 계약에 채널별 어휘를 적거나 `InstructionSet x86-64 → x86_64` 매핑을 채널 공통 정규화로 둔다(값 의미 불변, 표기만). 회귀: baseline 4종 `architecture`(현재 Dell/HPE/Lenovo/Cisco baseline 은 null — SCHEMA-05 이전 캡처) 갱신 필요.

### 02-cpu-005 — `multi_node.partitions[].cpu` 에 `turbo_max_mhz` 없음 (CSUS 7대)
- 심각도: **LOW** (관찰; 모양 결정 필요). 확실성: **확정**(Tier 1 7대 모두 partition cpu 키 7개, top-level 8개).
- 코드: `_normalize_cpu_raw` `:5910-5949` 가 2026-10-18 X2(`turbo_max_mhz` 추가) 를 반영하지 않음. 계약 9절은 `partitions[].cpu` 를 `{ ... }` 로만 적어 "같은 모양" 을 명시하지 않음.
- 제안: 이번 단계 규칙(신규 키 추가 금지) 상 **관찰만** — `multi_node` 내부 모양을 top-level 과 맞출지는 결정 항목(ADR-2026-10-19 "multi_node 는 그대로" 사용자 결정 범위).

### 02-cpu-006 — `cores_physical` 가 `TotalCores`(장착) 합, `TotalEnabledCores` 미사용
- 심각도: **LOW** (18대 모두 `TotalEnabledCores`/`Oem.Hpe.CoresEnabled`/`Oem.Lenovo.NumberOfEnabledCores` == `TotalCores` 라 영향 0 — 잠재). 확실성: 확정(영향 없음) / 추정(BIOS 코어 비활성 시 OS 와 어긋남).
- 코드: `redfish_gather.py:3039`. 제안: `TotalEnabledCores` 가 있고 0 보다 크면 그 값을 `total_cores` 로(OS 는 활성 코어를 센다) — 공통 로직, 값 있을 때만. 회귀: Lenovo/Dell fixture(값 동일) 불변 + 합성 케이스(Enabled < Total).

### 02-cpu-007 — `field_dictionary.yml` 에 `cpu.logical_threads` · `cpu.sockets` · `cpu.model` 항목 없음
- 심각도: **LOW** (문서). 확실성: **확정**(`grep -n "^  cpu\.\|^  \"cpu\." schema/field_dictionary.yml` → cores_physical/architecture/summary/manufacturer/max_speed_mhz/turbo_max_mhz/l2/l3 만). `cpu.summary` help 문에서만 `cpu.logical_threads` 규칙을 설명.
- 제안: 세 항목 등재(priority 는 cores_physical 과 같은 must 추정 — 사용자 결정). ADR 영향 없음.

### 02-memory-001 — dl380_gen12_03: `Status` 없는 빈 슬롯 16개가 `memory.slots[]` 에 포함
- 심각도: **MED**. 확실성: **확정**.
- 대상: dl380_gen12_03 (iLO 7 1.24.00, `Systems/1` `PowerState Off`, `Status {Health Warning, State Disabled}`, `Oem.Hpe.AggregateHealthStatus.Memory.Health Warning`). 1차·다른 DL380 3대(PowerState On)는 빈 슬롯이 `Status.State "Absent"` 로 와서 정상 제외.
- 필드: `memory.slots[]`(개수·`capacity_mb 0`·type/manufacturer/part_number/serial/speed/rank null·`health null` 16건), 2차적으로 `hardware.health`(Warning 원인 해석).
- 근거: `redfish/v1/Systems/1/Memory/proc1dimm2/index.json` — 키에 `Status` 없음, `CapacityMiB 0`, `DeviceLocator "PROC 1 DIMM 2"`, `Oem.Hpe.DIMMStatus "Other"`, `VendorID "0"`, `SerialNumber null`; 같은 슬롯이 dl380_gen12_01 에서는 `Status {"State":"Absent"}` + `DIMMStatus "NotPresent"`. 분포(03): `Status` 있음 16(Enabled) / 없음 16; `CapacityMiB` 32768×16 / 0×16.
- 코드: `redfish_gather.py:3085` (`if _safe(mdata,'Status','State') == 'Absent': continue` — 키 부재는 통과), `:3087-3096`(cap 0 은 합산 0, None 아님).
- 실제/기대: `slots` 32개(16개 공란) / 16개. `total_mb`·`summary`(cap 0 제외) 는 정확.
- 원인(확정): iLO 가 전원 꺼진 상태에서 빈 슬롯의 `Status` 를 생략하고 OEM `DIMMStatus "Other"` 를 준다(가설: SMBIOS 미갱신). 코드는 `State == 'Absent'` 만 "미장착" 으로 본다.
- 영향: HPE 전원 Off 서버에서 슬롯 수가 장착 수의 2배로 보임; 소비자가 `slots` 길이로 장착 수를 세면 오판. 다른 벤더 영향 없음(Lenovo Absent 는 Status 있음, Dell 은 present 만 노출, CSUS 는 present 만).
- 수정 제안(공통 로직, Additive): `Status` 키 자체가 없고 `CapacityMiB` 가 0/None 이며 Manufacturer·PartNumber·SerialNumber 가 전부 비어 있으면 미장착으로 간주해 제외 + notice 1건("Status 없는 빈 슬롯 N 제외"). 보조로 `Oem.Hpe.DIMMStatus ∈ {NotPresent}` 는 OEM 분기에서 제외 신호로 쓸 수 있으나 `"Other"` 는 뜻이 불명확해 식별 정보 부재 조건과 함께 써야 한다.
- 회귀 테스트: `tests/unit/test_redfish_phase2_contracts.py` C5 옆에 "Status 없음 + cap 0 + 식별 정보 없음 → 제외", "Status 없음 + cap > 0 → 보존(용량 있는 DIMM 은 숨기지 않음)" 2건; dl380_gen12_03 축약 fixture.
- ADR 영향: 없음. 계약 6.2 "빈/Absent 슬롯은 제외" 문구에 "Status 부재 + 식별 정보 부재" 를 추가.

### 02-memory-002 — CSUS `slots[].speed_mhz`/`summary.groups[].speed_mhz` 가 실클럭(MHz), 다른 벤더는 MT/s
- 심각도: **MED** (값은 raw 충실, 벤더 간 뜻이 다름). 확실성: raw **확정**, 의미 판단은 계약 결정 필요.
- 대상: csus3200_01/02/03 (3200), r1_HPE_CSUS3200_01..04 (2400). 비교군: dl380(6400) · sr650(6400) · dell(2933).
- 근거: `CompositionService/ResourceBlocks/r001u01/Systems/1/Memory/0000000101000074` `OperatingSpeedMhz 3200`, `Oem.Hpe.Label "32GB 1Rx4 PC5-6400B-RC1"`(PC5-6400 = 6400 MT/s, I/O 클럭 3200 MHz); 1차 `OperatingSpeedMhz 2400` + `Label "… PC5-4800B-RC0"`. iLO `Systems/1/Memory/proc1dimm1` `OperatingSpeedMhz 6400`, `Oem.Hpe.MaxOperatingSpeedMTs 6400`; XCC `OperatingSpeedMhz 6400`, `MemorySummary/MemoryMetrics.OperatingSpeedMHz 6400`.
- 코드: `redfish_gather.py:3120`, `normalize_standard.yml:284-294`; 계약 `docs/contract/03-fields.md:507-510` "단위 변환은 없음(MT/s 표기도 숫자 그대로)", field_dictionary `memory.slots[].speed_mhz:590-595`.
- 실제/기대: 3200 / (뜻을 MT/s 로 통일하면) 6400. 계약 문구상으로는 3200 도 "raw 그대로" 라 위반은 아님.
- 원인: DMTF `OperatingSpeedMhz` 정의("operating speed … in MHz") 를 RMC 는 클럭으로, iLO/XCC/iDRAC 는 전송률로 해석.
- 영향: 같은 모듈(PC5-6400) 이 CSUS 와 DL380 에서 2배 차이 → Portal 비교·그룹 요약 혼선; OS 채널(dmidecode `Configured Memory Speed` 는 MT/s) 과도 불일치.
- 수정 제안: (최소) 계약·EXTERNAL_CONTRACTS 에 "HPE H3(RMC) 는 실클럭" 명시. (선택, OEM 분기) `Oem.Hpe.Label` 의 `PC5-(\d{4})` 가 있고 `OperatingSpeedMhz × 2 == 그 값` 이면 MT/s 로 보정 — 라벨이 없으면 raw 유지. 숫자만 보고 ×2 하는 휴리스틱은 금지(DDR4-3200 은 3200 MT/s 가 클럭 1600).
- 회귀 테스트: CSUS fixture 2벌(1차 2400/4800B, 2차 3200/6400B) + iLO 6400 불변.
- ADR 영향: 없음. 문서 2곳 정정.

### 02-memory-003 — Lenovo `slots[].locator` 가 `MemoryLocation.Slot` 문자열(`"32"`), `ServiceLabel "DIMM 32"` 미사용
- 심각도: **LOW**. 확실성: **확정**.
- 대상: sr650_v4_01..04, r1_Lenovo_SR650_01 (XCC 1.22 · 2.97 모두).
- 근거: `Systems/1/Memory/32` — `DeviceLocator` 없음, `MemoryLocation {"Slot": 32, "Socket": 2}`, `Location.PartLocation {"LocationType":"Slot","ServiceLabel":"DIMM 32","LocationOrdinalValue":31}`, `Name "DIMM 32"`. Dell `DeviceLocator "DIMM A5"`, iLO `"PROC 1 DIMM 1"`, CSUS `ServiceLabel "rack1/…/dimmA0"` 는 사람 라벨.
- 코드: `redfish_gather.py:3113-3116`(DeviceLocator → `str(Slot)` if truthy → ServiceLabel); 결정 근거 `tests/evidence/2026-06-15-hpe-csus3200-mirror-audit.md` CSUS-R12 · LOCATOR-STR; 테스트 `tests/unit/test_csus_mirror_audit_fixes.py:384-435` 가 `"32"` 를 고정.
- 실제/기대: `"32"` / `"DIMM 32"`(사전: "물리 슬롯 위치 라벨 (예: 'DIMM A5')"). (가설) Linux dmidecode Locator 도 `DIMM 32` 꼴이라 OS 채널과도 맞을 것 — 실측 없음.
- 제안: 순서를 `DeviceLocator → Location.PartLocation.ServiceLabel → str(Slot)` 으로(DMTF: ServiceLabel 이 서비스용 라벨, Slot 은 인덱스). CSUS(Slot 0 → ServiceLabel) 불변, Dell/HPE(DeviceLocator) 불변, Lenovo 만 `"32"→"DIMM 32"`. 회귀: 위 두 테스트의 기대값 갱신 + Lenovo fixture.
- ADR 영향: 2026-06-15 evidence 의 LOCATOR-STR 결정 재검토(당시 가정 "Slot truthy 면 의미 있는 값").

### 02-memory-004 — CSUS `rank_count`/`error_correction` null (raw 키 없음) — OEM Label 로 rank 보충 가능
- 심각도: **LOW**. 확실성: **확정**(CSUS DIMM `all_keys` 에 `RankCount`/`ErrorCorrection`/`AllowedSpeedsMHz`/`VolatileSizeMiB` 없음; `ModuleManufacturerID`·`Oem.Hpe.Label "32GB 1Rx4 PC5-6400B-RC1"` 있음; `BusWidthBits 80 / DataWidthBits 64`).
- 대상: CSUS 7대. 필드: `memory.slots[].rank_count`(null → Label `1R` = 1), `error_correction`(enum 값은 알 수 없음 — BusWidth 80 > DataWidth 64 로 ECC 존재만 추론 가능, 값 지어내지 않음 → 관찰).
- 코드: `redfish_gather.py:3125`. 제안: `_extract_oem_hpe` 계열 OEM 분기에서 `Label` 의 `(\d)Rx(\d)` 로 `rank_count` 보충(라벨 있을 때만). 회귀: CSUS fixture 2벌.

### 02-memory-005 — `memory.summary.groups` 가 part_number 전체 문자열로 묶여 같은 모델이 접미사로 분리 (관찰)
- 심각도: **LOW**(관찰, 변경 제안 없음). 확실성: 확정.
- 대상: sr650_v4_04 (`MTC20F2085S1RC64BH1 3SFF` ×5 + `… 2XCC` ×3 → 2그룹), dl380 Micron `… MWFF`, sr650 `… 3SFF`. 1차 DL380 의 Samsung 14 + SK hynix 2 는 정당한 분리.
- 코드: `normalize_standard.yml:288`. 계약이 "같은 단위 용량·종류·속도·제조사·파트" 그룹이라 정의상 맞다. Micron 의 뒤 토큰은 생산 리비전/마킹이라 운영자는 같은 모델로 볼 수 있음 — 계약 결정 항목으로만 기록.

### 02-memory-006 — `total_basis` 상수 `physical_installed` (관찰)
- 18대 모두 Σ`CapacityMiB` == `TotalSystemMemoryGiB × 1024` 라 fallback 미발동. fallback 이 발동해도 `physical_installed` 로 표기되는데 `TotalSystemMemoryGiB` 는 "구성된 총 메모리" 라 뜻이 조금 다르다 — 영향 0, 기록만.

## 5. 미추적 Redfish 정보 (기존 필드로 표현 가능한 것만 개선안; 계약 밖은 관찰)
| 정보 | 어디에 있나(11대 실측) | 기존 필드 | 판단 |
|---|---|---|---|
| CPU 캐시 크기(소켓당) | iLO `Processor.Oem.Hpe.Cache[]` (`Name "L2-Cache"/"L3-Cache"`, `InstalledSizeKB` 65536 / 147456 — 6737P 사양 2 MB×32 · 144 MB 와 일치), XCC `Oem.Lenovo.CacheInfo[]` (`CacheLevel L2/L3`, `InstalledSizeKByte` 65536 / 147456), iDRAC `Oem.Dell.DellProcessor.Cache2InstalledSizeKB 24576 · Cache3InstalledSizeKB 36608`, RMC `Oem.Hpe.L3CacheSize "45 MB"/"75 MB"/"22.50 MB"`(문자열, L3 만) | `cpu.summary.groups[].l2_cache_kb` · `l3_cache_kb` (사전 channel `[os]`, "소켓당 KB") | **개선안**: OEM 추출 분기(rule 12 허용 영역)에서 KB 로 읽어 그룹에 싣고 사전 channel 에 redfish 추가. 4벤더 전부 값 있음. CSUS 는 L3 만(문자열 파싱, MB→KB). |
| HT 상태 | BIOS `HThread`/`ProcHyperthreading`/`Processors_Hyper_Threading`/`LogicalProc`(이미 `data.bios.current.attributes` 에 수집), Dell `ProcessorSummary.ThreadingEnabled` | `cpu.logical_threads` | **개선안** = 02-cpu-001 |
| 활성 코어 수 | `TotalEnabledCores`(XCC·iDRAC), `Oem.Hpe.CoresEnabled`, `Oem.Lenovo.NumberOfEnabledCores` | `cpu.cores_physical` | 02-cpu-006 |
| CPU 제조사 | `Processor.Manufacturer`, `ProcessorId.VendorId GenuineIntel` | `cpu.manufacturer`, `groups[].manufacturer` | 02-cpu-003 |
| DIMM rank | RMC `Oem.Hpe.Label "… 1Rx4 …"` | `slots[].rank_count` | 02-memory-004 |
| DIMM 정격 전송률 | RMC `Oem.Hpe.Label "PC5-6400B"`, iLO `Oem.Hpe.MaxOperatingSpeedMTs 6400`, XCC `Memory.AllowedSpeedsMHz [6400]`, `MemorySummary/MemoryMetrics.OperatingSpeedMHz 6400`(XCC, 미요청) | `slots[].speed_mhz` 는 "현재 동작 속도" | 02-memory-002 의 보정 근거로만. 정격을 담을 기존 필드 없음 → 관찰 |
| DIMM 상태 세분화 | iLO `Oem.Hpe.DIMMStatus` (`GoodInUse`/`NotPresent`/`Other`), XCC `Memory/Oem/Lenovo/DimmRecoveryReport`(미요청, Count 0), XCC `LogServices/DiagnosticLog/Entries/MemoryPredictiveFailureAnalysis`(미요청) | `slots[].health` | `Status.Health` 가 있어 중복; `Status` 없는 빈 슬롯 식별엔 02-memory-001 의 보조 신호. 그 밖은 관찰 |
| HPE 스페어 파트 번호 | iLO `Oem.Hpe.PartNumber "P69722-0B1"`, `VendorName "Micron"` | 없음(`part_number` 는 모듈 PN) | 관찰 |
| CPU 온도·전력 | XCC `Processors/{id}/ProcessorMetrics` (`TemperatureCelsius 53`, `ConsumedPowerWatt`), `ProcessorSummary/ProcessorMetrics` (`ConsumedPowerWatt 246`) — 미요청(inventory `exists_untouched`) | `data.thermal`/`data.power` 소관 | 계약 밖(센서 섹션은 별도 원천) → 관찰, 03/04 영역 작업자 참고 |
| 메모리 사용률 | CSUS `TelemetryService/MetricReports/Partition0_MemoryUtilizationPercent_*`(`MetricValues []`), iLO `MetricReports/MemoryBusUtil*`(값 "0"), XCC `Chassis/1/Sensors/utilization_HostMemoryBandwidthUtilization` | `memory.free_mb`/`visible_mb` 는 OS 전용 | 가용량이 아니라 대역폭 사용률 — 표현할 기존 필드 없음 → 관찰(`free_mb` null 유지가 맞음) |
| CSUS 코어·UPI 포트 | `…/Processors/{n}/SubProcessors/*` (`ProcessorType "Core"` 64/112/64 개, `Status.Conditions` 포함), `…/Ports/UpiPort*` 16개, `Chassis/r001u01/Processors`(같은 4 CPU 를 재참조) | 없음 | 관찰. `ProcessorType Core` 가 **별도 컬렉션** 이라 B01/F02 필터와 무관 |
| HPE `MemoryDomains` | `Systems/1/MemoryDomains` `Members []` (4대) | — | 비어 있음, 관찰 |
| Dell DIMM Metrics | r1_DELL_R740 `Memory/{id}.Metrics` 링크(미요청) | `slots[].health` 보조 | 1차 전용·미요청, 관찰 |

## 6. ADR·문서·테스트 교차 검증
| 문서/결정 | 당시 가정 | 새 증거(2차) | 정정 제안 |
|---|---|---|---|
| ADR-2026-10-18 X3 "`ProcessorSummary.LogicalProcessorCount` 있으면 정본(CIMC 4.1 은 TotalThreads 가 코어 수)" | LPC 는 실제 논리 프로세서 수 | XCC 2.97 LPC 128 = Σ`TotalThreads`, HT Disabled 3대에서도 128 → LPC 가 HT 를 반영하지 않는 펌웨어 존재 | "LPC 는 펌웨어마다 뜻이 다르다 — HT 상태(ThreadingEnabled/BIOS)가 있으면 그것이 정본" 으로 개정(02-cpu-001) |
| ADR-2026-10-19 결정 3 / A-2 "RMC LPC == 코어 수 → adapter `cores` 플래그로 Σ 우선" · 대안 비교 "`max(LPC,Σ)` 는 HT 비활성 과대집계" | 1.75.108 4노드(HT Enabled) | 1.77.30 LPC == Σ; csus3200_02 HT Disabled 인데 Σ = 224 → 채택안도 과대집계 | 플래그 근거를 펌웨어 한정으로 적고 HT 규칙으로 대체(02-cpu-002); Superdome Flex 복제 플래그는 "실측 없음" 유지 |
| `docs/contract/03-fields.md:552-554`, `schema/field_dictionary.yml:1699-1707`, `EXTERNAL_CONTRACTS.md:11,54` | 위와 같음 | 위와 같음 | 문구 정정 + "HT Disabled 장비" 사례 추가 |
| `docs/contract/03-fields.md:507-510` "`slots[].speed_mhz` 는 현재 동작 속도, 단위 변환 없음" | BMC 가 같은 단위를 쓴다 | RMC 실클럭 3200/2400 vs 타 벤더 MT/s | "HPE H3 RMC 는 I/O 클럭(MT/s 의 1/2)" 명시(02-memory-002) |
| `docs/contract/03-fields.md` 6.2 "빈/Absent 슬롯은 제외" · field_dictionary `memory.slots[]:573-581` | 빈 슬롯은 `State Absent` | iLO 전원 Off: `Status` 부재 + `DIMMStatus Other` | 제외 조건에 "Status 부재 + 용량·식별 정보 부재" 추가(02-memory-001) |
| `schema/field_dictionary.yml:2709` `cpu.manufacturer` channel `[redfish,…]` | 구현됨 | Redfish 미발행 | 구현 또는 channel 에서 redfish 제거 — 둘 중 하나(02-cpu-003) |
| `schema/field_dictionary.yml` cpu 절 | — | `cpu.logical_threads/sockets/model` 미등재 | 등재(02-cpu-007) |
| 2026-06-15 evidence CSUS-R12 / LOCATOR-STR | Slot truthy 면 의미 있는 값 | Lenovo 는 `ServiceLabel "DIMM 32"` 가 사람 라벨 | 순서 재검토(02-memory-003) |
| `tests/integration/test_redfish_csus_single_server_render.py:54-60` | "RMC 는 코어 수를 LPC 로 낸다 (실측)" | 1.77.30 반증 | 문구를 "1.75.108 fixture" 로 한정, 2차 fixture 케이스 추가 |
| `tests/unit/test_cross_channel_value_fixes.py:115-151` (X3·A-2 파라미터) | 위와 같음 | 위와 같음 | HT 규칙 3분기 추가 |
| `tests/unit/test_csus_mirror_audit_fixes.py:384-435` | LOCATOR-STR 고정 | — | 02-memory-003 채택 시 기대값 갱신 |
| `tests/unit/test_hpe_csus_multi_node.py:416` (`logical_threads == 224`, 합성 2×56×2) | Σ 고정 | HT 규칙 도입 시 partition 경로도 동일 규칙 필요 | 케이스 유지 + Disabled 케이스 추가 |
| `tests/regression/test_cross_channel_same_server.py` | Dell·Cisco 만 OS 쌍 보유 | HPE/Lenovo/CSUS 는 OS 쌍 없음 → HT 과대집계를 잡을 쌍이 없다 | 2차 5대의 OS/ESXi 실측 확보 시 쌍 추가(결정 항목) |
| 지시서 §8 명시 테스트 `test_csus_partition_serial.py` · `test_power_summary_b58_b59.py` · `test_redfish_phase3_contracts.py` | — | cpu/memory 가정 **없음**(`grep -n "cpu\|memory\|cores\|threads\|CapacityMiB"` 0건) | 해당 없음 |
| `tests/unit/test_redfish_phase2_contracts.py` C5(CapacityMiB 부재) · `test_round15_fixes.py`(Absent CPU 경고) | — | 2차에서 발동 사례 없음(모든 present DIMM 이 CapacityMiB 보유) | 유지 |

## 7. Replay·테스트 허점
1. **HT 상태를 드러낼 짝(OS/ESXi)이 없다** — Tier 1/2 는 Redfish 만 재생하므로 02-cpu-001 은 재생으로 잡히지 않는다. `test_cross_channel_same_server.py` 의 쌍은 Dell(iDRAC↔Linux)·Cisco(↔ESXi) 뿐이라 HPE/Lenovo/CSUS 의 HT 비활성 장비는 회귀 사각지대.
2. **골든이 결과를 고정한다** — 1차 `real_*` 골든(모듈 수준)과 Tier 2 는 1:1 동일(§8)이지만, 골든 자체가 1.75.108 의 LPC=코어 수 해석을 담고 있어 ADR 전제의 반증이 되지 못한다. 2차 Mock 으로 만든 골든이 없다(baseline 도 CSUS 3200 만 있고 그것은 합성 mock 기반: `architecture "x86-64"`, 448 스레드, locator `"PROC1 DIMM1"` — 실 RMC 와 다름).
3. **`Status` 부재 슬롯** — 단위 테스트는 `State Absent` 와 `CapacityMiB None` 만 다룬다(`test_redfish_phase2_contracts.py` C5). dl380_gen12_03 이 첫 실측 사례.
4. **페이지네이션 미검증** — 18대 모든 Processors/Memory 컬렉션이 단일 페이지(최대 32 멤버, `Members@odata.count` 일치)라 `_collection_members` 의 nextLink/상한 경로는 Mock 으로 검증되지 않는다(MOCK_LIMITATION; 단위 테스트는 있음 `:91-142`).
5. **ProcessorType 필터** — 18대 전부 `"CPU"`. GPU/Accelerator 혼재(B01)·`Core` 가 본 컬렉션에 섞이는 경우(F02)는 실측 0 — 합성 테스트에만 의존.
6. **Tier 1 의 Absent CPU/Disabled 경고 경로** 미발동(모든 CPU Enabled).
7. 재생 한계(`EVID/baseline/README.md` 1~9) 중 cpu/memory 에 닿는 것은 없음 — 모든 cpu/memory 요청이 미러에 있고 200 이었다(`server_access.jsonl` 집계 §2). 무인증/401/timeout 분기는 이 영역에서 실행되지 않았다.

## 8. 1차 7대 및 기존 모델 영향
- 1차 7대 Tier 1 값: Dell R740 2/48/96 · 2400/4000 · DDR4 2933 SK hynix 8 = 256 GiB; CSUS 01/02 4/32/64 · 3700/4100 · 16×32 GiB(SK hynix / Samsung); CSUS 03/04 4/64/128 · 2900/4000 · 32×32 GiB; DL380 2/48/96 · 3000/4000 · 16×64 GiB(Samsung 14 + SK hynix 2); SR650 2/32/64 · 3600/4300 · 16×64 GiB Samsung — 전부 raw Σ 와 일치, BIOS HT 전부 Enabled 라 02-cpu-001 해당 없음.
- 축약 fixture 골든(`tests/fixtures/redfish/real_*/expected_output.json`) ↔ Tier 2 r1 모듈 출력: `processors[]` · `memory{total_mib, slots}` · `system.cpu_summary` · `system.memory_summary` **4/4 동일**(bios 외 차이 0 — 골든 비교와 일치). `summary` 하위 키는 Tier 1 의 1차 라벨로 재확인: groups 1~2개, cores_per_socket/total_cores/quantity/group_total_gb/grand_total_gb 모두 일치.
- Dell iDRAC9: `ProcessorSummary.ThreadingEnabled true` + `LogicalProc Enabled` + `DellProcessor.HyperThreadingEnabled "Yes"` 가 있어 02-cpu-001 의 1순위 원천(`ThreadingEnabled`)을 그대로 쓸 수 있다(HT Off 실측은 없음). iDRAC10/Cisco/Supermicro 등 lab 부재 벤더는 영향 추정 불가.
- Cisco CIMC 4.1(baseline `cisco_baseline.json` 44 스레드, ESXi 88): HT Enabled 사례라 02-cpu-001 규칙에서 "Enabled → 종전(LPC/Σ)" 경로 → 불변.
- Lenovo 1차(XCC 1.22): `ProcessorSummary` 가 `Count/Status` 만(1차 감사 기록대로) — 2차 XCC 2.97 은 `LogicalProcessorCount`·`Model` 까지 준다. 즉 "XCC 는 LPC 미제공" 이라는 `EXTERNAL_CONTRACTS.md:54` 문구는 세대 한정.
- `schema/baseline_v1/{dell,hpe,lenovo,cisco}_baseline.json` 의 `cpu.architecture` 는 null(SCHEMA-05 이전) — 02-cpu-004 결정과 함께 갱신 대상.

## 9. 검증 한계 (재생 한계·Mock 한계·미확인)
- OS/ESXi 실측이 없어 02-cpu-001 의 "기대값(코어 수)" 은 BIOS 속성(현재값·pending 값 모두 Disabled) 기반 **추정**이다. 확정하려면 5대(csus3200_02 · dl380_gen12_03 · sr650_v4_01/02/04)의 OS `nproc`/`lscpu` 또는 ESXi `ansible_processor_vcpus` 가 필요하다.
- dl380_gen12_03 은 전원 Off 스냅샷 — 전원 On 상태에서 같은 슬롯이 `Absent` 로 바뀌는지는 미확인(가설).
- Lenovo `Oem.Lenovo.CurrentClockSpeedMHz` 를 정격으로 쓰는 것(5순위)은 2차 2900(6737P base 2.9 GHz)·1차 3600(6724P base 3.6 GHz)으로 맞았지만 "Current" 가 항상 정격인지는 보장 없음(가설: SMBIOS Type 4 Current Speed).
- 1차 v1 미러는 비-2xx 를 기록하지 않아 404 로만 재생(README 6) — cpu/memory 경로는 전부 2xx 라 영향 없음.
- 2차 CSUS 의 `Chassis/r001u01/Processors`·`SubProcessors`·`Ports`·`*Metrics` 는 미요청(인벤토리 `exists_untouched`) — 내용은 §5 표본으로만 확인.
- Superdome Flex adapter 의 `processor_summary_logical_count: cores` 는 실측 0건 — 검증 불가.

## 10. 탐색 경로 기록
- 코드: `redfish-gather/library/redfish_gather.py` (`_cpu_base_speed_mhz :741-767`, `gather_system` cpu/memory summary `:2598-2658`, `gather_processors :2996-3058`, `gather_memory :3060-3144`, `_normalize_cpu_raw :5910`, `_normalize_memory_raw :5951`, `_collect_all_sections :6539/:6583-6584`, `_normalize_jedec :1355`), `redfish-gather/tasks/normalize_standard.yml` (`:1-60`, `:240-320`, `:596-668`), `filter_plugins/jedec_mapper.py` 전문, `adapters/redfish/hpe_csus_3200.yml` 전문 + `lenovo_xcc3/lenovo_bmc/hpe_ilo7/hpe_superdome_flex.yml` vendor_notes grep, `os-gather/tasks/{linux,windows}/gather_cpu.yml` 제조사 정규화.
- 계약·문서: `schema/sections.yml` cpu/memory, `schema/field_dictionary.yml` memory 절(`:505-680`) · cpu 절(`:1130, :1644-1707, :2709-2755`) · 전체 cpu/memory 키 목록, `docs/contract/03-fields.md` `:60-92, :455-556, :1252-1320`, `docs/develop/05-field-mapping.md` cpu/memory 행, `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` 관련 행, ADR-2026-10-18/10-19, `tests/evidence/2026-10-19-csus-single-server-summary-audit.md`, `tests/evidence/2026-06-15-hpe-csus3200-mirror-audit.md`(CSUS-R12 · LOCATOR-STR · MEM-01).
- 데이터: Tier 1 18 label `gather_output.json` 의 `data.cpu`/`data.memory`/`multi_node.partitions[].cpu/memory` 전수 덤프; `requested_keys.json`·`server_access.jsonl` 의 Processor/Memory 요청 집계(18 label 전부 200/basic); 2차 11대 `_fsmap.json` 으로 `Systems/<id>` → `Processors/*`·`Memory/*` 를 따라가 ProcessorSummary/MemorySummary/per-CPU 22~27키/per-DIMM 21~41키를 추출해 Tier 1 과 자동 대조(Σ코어·Σ스레드·present 슬롯·Σ용량·MemorySummary — FLAGS 0), 1차 7대는 v1 디렉터리 경로로 같은 대조; BIOS `Attributes` 의 HT 속성(현재·pending), `Managers/*` 펌웨어 버전, dl380_gen12_03 `Systems/1` Status/PowerState/AggregateHealthStatus, 빈 슬롯 원본(03 vs 01) 전문 비교; Lenovo/HPE/Dell/CSUS 대표 1대의 CPU·DIMM `Oem` 전문; 미요청 리소스 표본(CSUS ProcessorMetrics/MemoryMetrics/Chassis Processors/SubProcessors/UpiPort/Telemetry, HPE MemoryDomains/MemoryBusUtil, XCC ProcessorMetrics/MemoryMetrics/DimmRecoveryReport/MemorySubsystemPerformance/PFA 로그/대역폭 센서); 인벤토리 `EVID/inventory/*.jsonl` 의 Processor/Memory 분류 집계; `EVID/baseline/tier2/_golden_compare.plain.json` + 골든 4종 모듈 수준 재비교; `schema/baseline_v1/*.json` cpu/memory 키.
- 테스트: `tests/unit/test_cross_channel_value_fixes.py`, `test_redfish_csus_single_server.py`, `tests/integration/test_redfish_csus_single_server_render.py`, `tests/regression/test_cross_channel_same_server.py`, `test_csus_mirror_audit_fixes.py`, `test_round15_fixes.py`, `test_redfish_phase2_contracts.py`, `test_hpe_csus_multi_node.py`, `test_field_dictionary_channel_emit.py`, 지시서 명시 3종(해당 없음 확인).
- 재생 도구: `EVID/tools/mirror_policy.py`, `tier2_replay.py` (무인증 범위·Basic 통과·hang·404 정책) — 이 영역의 요청이 전부 미러 안에 있어 재생 한계가 결과에 닿지 않음을 확인.
- 문제 없음도 확인한 것: 소켓 수(ProcessorType 전부 CPU, SubProcessors 분리), 코어·스레드 합, 정격/터보 클럭 원천과 Intel 사양 일치, DIMM 용량 합 == MemorySummary(18/18), Absent 슬롯 제외(Lenovo 30/30/16/24, HPE 16/24/24 + 1차), JEDEC/제조사 정규화(`Hynix`·`Hynix Semiconductor`→`SK hynix`, `Micron`→`Micron Technology`), locator(Dell/HPE DeviceLocator, CSUS ServiceLabel), rank/폭/ECC/health raw 일치, summary 수량·단위용량·grand_total_gb, `free_mb`/`visible_mb` 의 원천 부재, Tier 1 ↔ Tier 2 ↔ 골든 일치, 요청 수·상태코드.
- 수치 측정 명령: `grep -n "^  cpu\.\|^  \"cpu\." schema/field_dictionary.yml`(사전 cpu 항목), `python -I -c "..."` 로 `_fsmap.json`/`index.json` 을 읽는 대조 스크립트(SCRATCH `w02_cpu_memory/{dump_tier1,raw_cpu_mem,compact,oem_samples,untouched_samples}.py`, 저장소 밖 — 재현 시 §2 의 경로로 같은 결과).
- 비밀정보 점검: 본 보고서·coverage JSON 에 IP·호스트명·계정·DIMM/CPU 시리얼을 싣지 않았다(슬롯 ID·파트 번호·펌웨어 버전만).
