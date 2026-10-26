# 04. firmware / bios — 2차 Redfish Mock 11대 분석 (2026-10-26)
모델: claude-fable-5-1 (Claude Fable 5.1, effort=max) / worktree: `C:/github/ClovirONE/clovirone-server-gathering/.claude/worktrees/agent-af23d814fb6c3f098` / 브랜치: `worktree-agent-af23d814fb6c3f098` (main `e8b5ae9b` 기준, 제품 코드 변경 0)

담당 필드: `data.firmware[]` (`id, name, version, updateable, component, pending, category` — Tier 1 envelope 의 실제 키 7개) 와 `sections.firmware`,
`data.bios` (`bios.current.attributes` — `bios.current` 의 다른 키는 없음), `data.hardware.bios_version/bios_date` 와 `data.bmc.firmware_version` 의 `firmware[]` 대조.
근거 우선순위: 11대 Mock 추출본(`C:/github/ClovirONE/mock2-audit-20261026/extract/<server>/`) + 1차 7대 미러(`C:/github/서버mock데이터/1차/`) 실제 응답 > Tier 1 envelope(`EVID/baseline/tier1/<label>/gather_output.json`) > Tier 2 모듈 출력 > 코드/ADR/계약.
기계 판독용 표: `04-firmware-bios.coverage.json` (18 label × `firmware` 10 필드 · `bios` 9 필드, `_area` 포함).

## 1. 요약
- 이슈 16건 — **HIGH 0 / MED 5 / LOW 11**. 11대(+1차 7대) 전부에서 `firmware[]` 의 `id/name/version/updateable/component` 는 raw `UpdateService/FirmwareInventory/*` 와 1:1 로 맞고(불일치 0건, 누락·중복 0건), `bios.current.attributes` 는 raw `Attributes` 와 키·값·JSON 자료형까지 동일하며 이름순이다(18/18). 문제는 **`category` 추론 규칙**과 **Lenovo `pending` 의 뜻**, 그리고 **테스트 격리**에서 난다.
- [ISSUE] MED `04-firmware-001`: Lenovo 의 BIOS 항목(`UEFI`, Name `Firmware:UEFI`, `RelatedItem → Systems/1/Bios`, `Bios.Links.ActiveSoftwareImage` 가 가리킴)이 `category: other` 다 — 5대(2차 4 + 1차 1) 어느 Lenovo 도 `bios` 항목이 없다. CSUS 의 `Partition0_FW`(Description "Partition-specific firmware, such as BIOS/UEFI") 도 `other` (7대).
- [ISSUE] MED `04-firmware-002`: HPE RAID 컨트롤러 `HPE MR416i-o Gen11`/`MR408i-o Gen11` 이 `other` 인데 `Embedded Video Controller` 가 `storage_controller` 다 — 2026-10-19 A-9 가 넣은 `'controller'` 포괄 토큰의 부작용 (DL380 Gen12 4대 + 1차 1대).
- [ISSUE] MED `04-firmware-003`: Lenovo 드라이브 백플레인 익스팬더 `Drive_Backplane_<FRU>_PSoC_0xBB`(Name `Firmware-PSoC:0xBB`) 가 `drive` 다 — `'drive'` 토큰이 `'backplane'` 보다 먼저 평가된다 (5대, -Pending 쌍 포함 서버당 2건).
- [ISSUE] MED `04-firmware-006`: Lenovo XCC 가 항상 노출하는 `*-Pending` 스테이징 슬롯(`Version ""`/null · `Status.State Disabled` · `ReleaseDate null`)이 `pending: true, version: null` 항목으로 나간다 — 2차 4대 각 4건, 1차 2건. 실제 보류 이미지가 없는데 "적용 보류" 로 읽힌다(계약 문구 "pending=true + version=null 은 정상(의도된 보류)" 가 이 상태를 가린다).
- [ISSUE] MED `04-test-001`: Tier 0 의 `test_redfish_bios_current.py` 8건 실패는 bios 수집 코드 문제가 아니라 `tests/redfish-probe/replay_full_mirror.py::install_fakes` 가 `rg._get`/`rg._get_noauth` 모듈 전역을 **복원 없이** 바꾸는 데서 온다 — `test_full_mirror_dryrun.py::test_v2_tree_is_consumed_by_replay_and_convert` 가 `rep.run()` 으로 그것을 호출하면 이후 `_get_impl` seam 을 쓰는 테스트(`emulator_harness.run_gather`, `monkeypatch.setattr(rg, "_get_impl", …)`) 가 가짜 `_get` 에 가려진다. 쌍 실행으로 8 failed 재현, 단독 78 passed.
- 그 밖 LOW: FC HBA 분류가 벤더 간 다름(Dell 만 storage_controller) · CPLD/FPGA 잔여 `other` · CSUS 보충 항목 `updateable null` · Dell first-seen dedup 의 접두사 혼재 · 전원 Off 스냅샷의 `updateable` 변동 · Lenovo 버전 표기 차이 · CSUS `bios_version == bmc.firmware_version`(번들) · 계약 문서에 `firmware[]` 절 부재 · Lenovo `bios_date` null(원천 있음) · BIOS 속성에 식별 정보 포함(계약대로) · CSUS `Bios/Settings` 의 실제 보류 차이 2건(계약 밖).
- 11대 한 줄: CSUS 3대 firmware ISSUE(category · updateable null) / bios PASS(76건 동일, `bios_date` 원천 없음); DL380 Gen12 4대 firmware ISSUE(category) / bios PASS(03 의 275건 · 13건은 전원 Off + 장착 차이이고 파서 문제 아님); SR650 V4 4대 firmware ISSUE(category · pending) / bios ISSUE(`bios_date` null · bios 항목 없음, attributes 자체는 PASS). 1차 7대도 같은 패턴(Dell 은 category LOW 만).
- 02 보고서 전제 검증: HT 속성은 18대 전부 `bios.current.attributes` 에 있고 문자열 `Enabled`/`Disabled` 다(§3 bios 표 · §6). pending(`Bios/Settings`·`Bios/Pending`) 값도 current 와 같다.

## 2. 필드별 수집 흐름 (진입 → 요청 경로/폴백 → 파서 → 정규화 → 출력)
공통 진입: `redfish-gather/library/redfish_gather.py` `main()` → `_collect_all_sections()`(`:6539`) 가 `_run('firmware', gather_firmware, bmc_ip, *creds)`(`:6587`) 로 firmware 섹션을 수집하고, 10개 섹션이 끝난 뒤 adapter `vendor_notes.firmware_inventory_scope == 'complex_only'` 면 `_supplement_firmware_from_pcie_psu`(`:6603-6605`) 로 PCIe/PSU 펌웨어를 덧붙인다. BIOS 는 `_run` 밖에서 `gather_bios(bmc_ip, bios_link, *creds)`(`:6607-6609`) 로 1회 수집해 `sections['bios']` 에 담는다(collected/failed/unsupported 에 넣지 않음). 18 label 모두 `server_access.jsonl` 기준 `UpdateService/FirmwareInventory` 1회 + 멤버 GET(2/25/13/28~40/32/22/26회) + `Systems/<id>/Bios` 1회, 전부 `(200,'basic')` — 404/401 0건.

| 출력 필드 | 요청 경로 | 파서(모듈) | 정규화(`redfish-gather/tasks/normalize_standard.yml`) | 비고 |
|---|---|---|---|---|
| `firmware[]` 목록 | 고정 경로 `UpdateService/FirmwareInventory`(`:5023`, `UpdateService` 본문은 읽지 않음) → `_collection_members`(`:1225`, nextLink 64p/1024 멤버) → 멤버별 GET(inline `Name`/`Version` 이 없을 때만 `:5056-5058`) | `gather_firmware` `:5003-5101`: pass 1 에서 URI tail/inline Id 로 `_fw_dedup_key`(`:4989`, `Installed-/Current-/Available-/Rollback-` 접두사 제거) 그룹 → `Previous-` 는 GET 도 안 함(`:5041`) → 그룹당 첫 멤버(실패 시 대체 1회) → `Version` 이 `N/A`/빈 문자열이면 제외(pending 은 null 유지 `:5080-5085`) → `SoftwareId "null"` → None(`:5087-5089`) → 실제 Id 로 2차 dedup(`:5091-5094`) | `_rf_d_firmware` 그대로(`:13`) → `_rf_firmware_categorized`(`:401-432`) 가 `category` 를 붙여 `data.firmware`(`:682`) | 항목 키 `id/name/version/updateable/component/pending` 은 모듈이, `category` 는 normalize 가 만든다 |
| `firmware[].id` | — | `Id` → 없으면 URI tail (`:5074-5075`) | — | Dell 은 first-seen 으로 `Current-`/`Installed-` 중 Members 순서상 앞의 것(04-firmware-008) |
| `firmware[].version` | — | `Version` (`:5079-5085`) | — | `""`/`N/A` 은 pending 이 아니면 제외 + notice(RD-FW2); pending 이면 null |
| `firmware[].updateable` | — | `Updateable` 그대로 (`:5099`) | — | 보충 항목은 None(`:6445`,`:6462`) — 04-firmware-007 |
| `firmware[].component` | — | `SoftwareId` 또는 id (`:5100`) | — | 보충 항목은 슬롯 `ServiceLabel`/PSU 이름 |
| `firmware[].pending` | — | `_is_pending_fw_id`(`:4999`, id 에 `pending` 포함) | — | `Status.State`·`Version ""` 는 보지 않음 — 04-firmware-006 |
| `firmware[].category` | — | — | id·name 소문자 substring 사슬 `bios/system rom → cpld → tpm → diagnostic → usc/lifecycle → driver → ubm/bc bp → disk/drive/nvme/ssd/hdd/boss → backplane → service → idrac/ilo/xcc/cimc/bmc → raid/perc/megaraid → nic/ethernet/broadcom/mellanox/gbe → psu/power supply → controller → other` | `Description`·`RelatedItem`·`Oem.Hpe.DeviceContext`·`SoftwareId` 접두(Lenovo `UEFI-`/`BMC-`/`DISK-`/`POWER-`/`STOREXP-`)는 쓰지 않음 — 04-firmware-001~005 |
| CSUS 보충 (A-9) | `Chassis/<System.Links.Chassis[]>` → `PCIeDevices` 컬렉션 → 멤버(캐시 공유, `_pcie_devices_for_chassis` `:3515`) ; PSU 는 power 섹션 결과 재사용 | `_supplement_firmware_from_pcie_psu` `:6421-6469`: `FirmwareVersion` 있는 장치만 `PCIeDevice.<Id>`(name=Model, component=Slot ServiceLabel), `firmware_version` 있는 PSU 만 `PowerSupply.<idx>`; 기존 id 는 건너뜀; notice 1건 | 위와 같은 category 규칙 | adapter 값이 없는 벤더는 호출되지 않음 |
| `sections.firmware` | — | `_make_section_runner`(`:5645`): 오류 전부 404 + 빈 결과일 때만 unsupported | `_sections_*_fragment`(`:702-735`, `_rf_aux_sections` 는 `['network_adapters']` 뿐 `:514`) | 18/18 `success` |
| `bios.current.attributes` | `gather_system` 이 ComputerSystem 응답의 `Bios.@odata.id` 를 `bios_link` 에 기록(`:2574-2576`) → `gather_bios`(`:2721`) 가 그 링크 그대로 1회 GET(`_p()` 는 접두 제거·후행 `/` 만 `:690`) | 404 → notice / 그 밖 오류 → `errors[]`(`code=_CODE_BIOS_NON_BLOCKING` `:824`) / 최상위 `@odata.type` 이 `#Bios.` 로 시작하지 않으면 notice(`:2719`,`:2768-2772`) / `Attributes` 를 Key 이름순으로 재구성(`:2789`) | `bios: "{{ _rf_raw_collect.data.bios \| default(none) }}"`(`:701`) 단일 표현식 | `Settings`/`Pending`/`AttributeRegistry`/`Oem` 미요청(18/18 확인) ; `_compute_final_status` 가 bios 오류를 제외(`:6637`) |
| `hardware.bios_version` | `Systems/<id>` 본문 | `BiosVersion`(`:2633`, 빈 문자열 → None) | `:588` | 18/18 raw 와 동일 |
| `hardware.bios_date` | 같은 본문의 OEM | HPE `Oem.Hpe.Bios.Current.Date`(`:2126-2129`) / Dell `Oem.Dell.DellSystem.BIOSReleaseDate`(`:2155-2160`) → `_hoist_oem_extras`(`:2305-2325`) 가 `_normalize_bios_date`(`:2442`) 로 ISO | `:594` (hoisted 값 → Dell legacy `oem.bios_release_date`) | Lenovo/CSUS 는 OEM 추출기에 날짜 키가 없어 null — 04-bios-001 |
| `bmc.firmware_version` | `Managers/<첫 멤버>` 본문 | `gather_bmc`(`:2802`) `FirmwareVersion` | — | `firmware[]` 의 BMC 항목이 아닌 Manager 보고 값(계약 6.6) |

Tier 1 ↔ Tier 2 대조: 18 label 모두 Tier 2 `plain` 의 `data.firmware` id 목록이 Tier 1 과 같다(CSUS 는 보충이 없는 `plain` 이 2건, `adapter` 모드가 Tier 1 과 동일 13/9/13 · 1차 6/6/15/15). Tier 2 모듈 항목에는 `category` 가 없다(normalize 층 생성) — 층 분리가 의도대로다.

## 3. 11대 × 필드 검증 상태 표
근거는 `04-firmware-bios.coverage.json` 에 서버·필드별 문장으로 있다. 표기: P=PASS, I=ISSUE(괄호는 이슈 ID 번호), N/A=NOT_APPLICABLE.

### firmware
| label | sections | 개수(raw→출력) | id | name | version | updateable | component | pending | category | A-9 보충 |
|---|---|---|---|---|---|---|---|---|---|---|
| csus3200_01 | P success | P 2→13(+PCIe 7·PSU 4) | P | P | P | I(007) null 11 | P | P 0건 | I(001·004·011) other 4 | P |
| csus3200_02 | P | P 2→9(+3·4) | P | P | P | I(007) | P | P | I(001·011) other 2 | P |
| csus3200_03 | P | P 2→13(+7·4) | P | P | P | I(007) | P | P | I(001·004·011) other 4 | P |
| dl380_gen12_01 | P | P 25→25 | P | P | P | P True/False | P | P | I(002·004·005) other 10 | N/A |
| dl380_gen12_02 | P | P 25→25 | P | P | P | P | P | P | I(002·004·005) other 9 | N/A |
| dl380_gen12_03 | P | P 13→13 (전원 Off — 04-firmware-009) | P | P | P | P (PCIe False) | P | P | I(002·005) other 7 | N/A |
| dl380_gen12_04 | P | P 25→25 | P | P | P | P | P | P | I(002·004·005) other 9 | N/A |
| sr650_v4_01 | P | P 28→28 | P | P | P null 4(-Pending) | P | P | I(006) true 4 | I(001·003·005) other 6 | N/A |
| sr650_v4_02 | P | P 30→30 | P | P | P null 4 | P | P | I(006) | I(001·003·004·005) other 8 | N/A |
| sr650_v4_03 | P | P 40→40 | P | P | P null 4 | P | P | I(006) | I(001·003·004·005) other 8 | N/A |
| sr650_v4_04 | P | P 30→30 | P | P | P null 4 | P | P | I(006) | I(001·003·005) other 6 | N/A |
| r1_DELL_R740_01 | P | P 62→32(dedup 19·Previous 11) | P (접두 혼재 008) | P | P | P True | P | P | I(004) other 1 | N/A |
| r1_HPE_CSUS3200_01 | P | P 2→6(+0·4) | P | P | P | I(007) | P | P | I(001·011) other 2 | P |
| r1_HPE_CSUS3200_02 | P | P 2→6(+0·4) | P | P | P | I(007) | P | P | I(001·011) other 2 | P |
| r1_HPE_CSUS3200_03 | P | P 2→15(+9·4) | P | P | P | I(007) | P | P | I(001·004·011) other 6 | P |
| r1_HPE_CSUS3200_04 | P | P 2→15(+9·4) | P | P | P | I(007) | P | P | I(001·004·011) other 6 | P |
| r1_HPE_DL380_01 | P | P 22→22 | P | P | P | P | P | P | I(002·004·005) other 9 | N/A |
| r1_Lenovo_SR650_01 | P | P 26→26 | P | P | P null 2 | P | P | I(006) true 2 | I(001·003·005) other 7 | N/A |

### bios
| label | attributes 내용(raw==T1) | 키 정렬 | 구조/격리 | 링크·요청 | HT 속성(값) | bios_version | bios_date | bmc.fw ↔ fw[bmc] | bios_version ↔ fw[bios] |
|---|---|---|---|---|---|---|---|---|---|
| csus3200_01 | P 76==76 | P | P | P `Systems/Partition0/Bios` 1회, `Bios/Settings` 미요청 | P `HThread`=Enabled | P (RMC 번들 버전) | N/A 원천 없음 | N/A bmc 항목 없음(Manager==ComplexFW) | I(011) bios 항목 없음 |
| csus3200_02 | P 76 | P | P | P | P `HThread`=Disabled | P | N/A | N/A | I(011) |
| csus3200_03 | P 76 | P | P | P | P `HThread`=Enabled | P | N/A | N/A | I(011) |
| dl380_gen12_01 | P 311 | P | P | P `systems/1/bios`(소문자 그대로) 1회, `bios/settings`·`bios/oem/hpe/*` 미요청 | P `ProcHyperthreading`=Enabled | P `U68 v1.82 (06/26/2026)` | P 2026-06-26 | P `1.24.00 Aug 01 2026` | P `System ROM` 동일 |
| dl380_gen12_02 | P 301 | P | P | P | P Enabled | P `U68 v1.90 (08/20/2026)` | P 2026-08-20 | P | P |
| dl380_gen12_03 | P 275 | P | P | P | P Disabled | P v1.82 | P 2026-06-26 | P | P |
| dl380_gen12_04 | P 297 | P | P | P | P Enabled | P v1.82 | P 2026-06-26 | P | P |
| sr650_v4_01 | P 778 (str 666·bool 28·int 68·null 16) | P | P | P `Systems/1/Bios` 1회, `Bios/Pending`·`ChangePasswordActionInfo` 미요청 | P `Processors_Hyper_Threading`=Disabled | P `IHE120L` | I(bios-001) null | P 표기 차이(010) | I(001) UEFI 가 other |
| sr650_v4_02 | P 1116 | P | P | P | P Disabled | P `IHE120L` | I(bios-001) | P | I(001) |
| sr650_v4_03 | P 1299 | P | P | P | P Enabled | P `IHE120P` | I(bios-001) | P | I(001) |
| sr650_v4_04 | P 778 | P | P | P | P Disabled | P `IHE120L` | I(bios-001) | P | I(001) |
| r1_DELL_R740_01 | P 380 | P | P | P `Systems/System.Embedded.1/Bios` 1회, `Bios/Settings` 미요청 | P `LogicalProc`=Enabled | P `2.26.1` | P 2026-01-28 | P `7.00.00.184` | P `BIOS` 동일 |
| r1_HPE_CSUS3200_01..04 | P 75 | P | P | P | P `HThread`=Enabled ×4 | P (RMC 1.75.108 번들) | N/A | N/A | I(011) |
| r1_HPE_DL380_01 | P 292 | P | P | P 소문자 링크 | P Enabled | P `U68 v1.46 (08/08/2025)` | P 2025-08-08 | P `1.20.00 Feb 12 2026` | P |
| r1_Lenovo_SR650_01 | P 1223 | P | P | P | P Enabled | P `IHE110U` | I(bios-001) | P 표기 차이 | I(001) |

BIOS 속성 수가 같은 모델에서 다른 이유(브리프 4번, 전부 raw 로 확정): Lenovo 는 장착 어댑터별 설정 키가 속성에 들어간다 — sr650_v4_02 는 QLogic QLE2772 FC HBA 2장 분 `QLogicQLE2772FCAdapter__Slot5/8…` 336키가 더 있고(778→1116), sr650_v4_03 은 Intel E810 PCIe NIC 3장 + FC 2장 + `BootOrder_NetworkPriority_9..20` 로 1299 (01 에만 있는 `IntelE810…Slot13…` 90키는 02/03 에서 다른 슬롯 키로 대체). 1차 SR650(1223) 은 Broadcom NIC 설정 507키. HPE 는 `PciSlotN*`/`SlotN(Nic|Storage)Boot*` 가 장착 슬롯만큼 생기고(01 311 ⊃ 04 297 ⊃ 03 275 — 03 은 PCIe 장치 4장), 02 는 BIOS v1.90 레지스트리(`BiosAttributeRegistryU68.v1_1_90`) 가 `MemIntegrity`·`PcieResizableBar*`·`AutoEnrollPolicy` 를 더하고 슬롯 키를 빼서 301. CSUS 76 은 `Systems/Partition0/Bios`(Name "nPartition 0 BIOS attributes", nPartition 수준이지 complex 수준이 아님) 이고 1차 75 와의 차이는 RMC 1.77.30 레지스트리 `BiosAttributes.v9.60.1` 의 `IpxeBootOrder` 1키다. `AttributeRegistry` 식별자·`@Redfish.Settings`·`Bios/Settings` 값은 `bios.current` 에 표현할 자리가 없다(계약 밖 — §5 관찰).

## 4. 이슈 목록

### 04-firmware-001 — Lenovo BIOS(`UEFI`) · CSUS `Partition0_FW` 가 `category: other`
- 심각도: **MED**. 확실성: **확정**.
- 대상: sr650_v4_01..04, r1_Lenovo_SR650_01 (UEFI · UEFI-Pending); csus3200_01..03, r1_HPE_CSUS3200_01..04 (Partition0_FW, ComplexFW).
- 필드: `firmware[].category` (Lenovo/CSUS 에 `bios` 항목 0건 → `hardware.bios_version ↔ firmware[]` 대조 불가).
- 근거: `redfish/v1/UpdateService/FirmwareInventory/UEFI/index.json` — `Name "Firmware:UEFI"`, `SoftwareId "UEFI-IHE1-6"`, `RelatedItem [/redfish/v1/Systems/1/Bios]`, `Version "20L-1.50"`(03 은 `20P-1.51`); `Systems/1/Bios.Links.ActiveSoftwareImage → …/FirmwareInventory/UEFI`. CSUS `FirmwareInventory/Partition0_FW` — `Name "Npar 0 Current Firmware"`, `Description "Partition-specific firmware, such as BIOS/UEFI, currently in use for npar 0."`, `RelatedItem [/redfish/v1/Systems/Partition0]`; `ComplexFW` — `Description "Firmware on the RMPs and PDHCs…"`, `RelatedItem [/redfish/v1/Chassis/RackGroup]`.
- 코드: `redfish-gather/tasks/normalize_standard.yml:409` (`'bios' in lid or 'system rom' in lid` 만 bios); `tests/unit/test_firmware_category.py:80-84` 는 CSUS 두 번들이 `other` 인 것을 "무영향" 으로 고정.
- 실제 출력 / 기대: `{"id":"UEFI","name":"Firmware:UEFI","category":"other"}` / `category: "bios"`; `Partition0_FW` → `bios`, `ComplexFW` → `bmc`(RMP/PDHC 관리 펌웨어) 가 자연스러움.
- 원인(확정): 토큰 사슬에 `uefi` 가 없고, DMTF 가 주는 구조 신호(`RelatedItem` 이 `…/Bios` 를 가리킴, `Bios.Links.ActiveSoftwareImage`) 와 `Description` 을 쓰지 않는다.
- 영향: Lenovo 5대·CSUS 7대에서 "BIOS 펌웨어 항목" 을 category 로 고르는 소비자는 0건을 본다. Dell/HPE 와 결과 형태가 다르다.
- 수정 제안(공통 로직, 기존 필드): (1) 토큰 사슬 첫 분기에 `uefi` 추가(`'bios' in lid or 'system rom' in lid or 'uefi' in lid`) — Dell `Dell 64 Bit uEFI Diagnostics` 는 `diagnostic` 이 먼저 와야 하므로 `diagnostic` 분기를 `bios` 앞으로 올리거나 `uefi` 를 `diagnostic` 뒤에 둔다. (2) 모듈이 `RelatedItem` 의 마지막 경로 토큰이 `Bios` 인 항목을 알 수 있으므로(이미 GET 한 본문) normalize 가 쓰도록 모듈 항목 키를 늘리지 않고 — 키 추가는 금지이므로 — 모듈 `gather_firmware` 가 `name` 을 바꾸지 않는 선에서 분류만 Python 으로 옮기는 안은 별도 결정. 가장 작은 변경은 (1) + CSUS 는 `Description` 의 `BIOS/UEFI` 토큰을 `name` 대신 보는 것이 아니라 id `Partition<N>_FW`(nPar 펌웨어) 패턴을 `bios` 로 두는 것(형식이 RMC 1.75/1.77 동일).
- 회귀 테스트 제안: `tests/unit/test_firmware_category.py` 에 Lenovo 실 id/name 5종(UEFI → bios, BMC-Primary → bmc, HPM-FPGA → cpld(04-firmware-005 채택 시), drive_bay_0 → drive, Drive_Backplane_…PSoC → backplane) 과 CSUS 2종 기대값 갱신; Dell `uEFI Diagnostics` 가 여전히 `diagnostic` 인지 고정.
- ADR 영향: 없음(ADR-2026-10-19 A-9 는 보충 범위만 결정). 문서: `schema/field_dictionary.yml` `firmware[].category` help, `tests/unit/test_firmware_category.py:80-84` 문구.

### 04-firmware-002 — HPE RAID 컨트롤러 `other`, `Embedded Video Controller` 가 `storage_controller`
- 심각도: **MED**. 확실성: **확정**.
- 대상: dl380_gen12_01..04, r1_HPE_DL380_01 (`HPE MR416i-o Gen11` ×4 · `HPE MR408i-o Gen11` ×1 → other; `Embedded Video Controller` ×5 → storage_controller).
- 필드: `firmware[].category`.
- 근거: `FirmwareInventory/13`(01) `Name "HPE MR416i-o Gen11"`, `Oem.Hpe.DeviceContext "OCP Slot A"`, `DeviceSlotLocation "Slot=14"`; `FirmwareInventory/21`(01) `Name "Embedded Video Controller"`, `DeviceContext "Embedded Device"`. 같은 장비의 `Systems/1/Storage/*` `StorageControllers[0].Model "HPE MR416i-o Gen11"`, `FirmwareVersion "52.36.3-6584"` 가 `data.storage.controllers[].controller_firmware` 에 이미 있다(값 일치).
- 코드: `normalize_standard.yml:421-428` (`raid/perc/megaraid` 토큰 없음 → `nic` 토큰 없음 → … → `'controller' in lid` 포괄 `:428`). 2026-10-19 A-9 가 CSUS `HPE SR3258p-16i/e PCIe4 Controller` 를 위해 추가한 분기(`tests/unit/test_redfish_csus_single_server.py:364-370`).
- 실제 출력 / 기대: `MR416i-o` → `other` / `storage_controller`; `Embedded Video Controller` → `storage_controller` / `other`.
- 원인(확정): HPE 의 MegaRAID 계열 이름 `MRnnni-o` 에 `raid` 토큰이 없고, 포괄 토큰 `controller` 는 비디오·관리 컨트롤러 이름까지 잡는다.
- 영향: HPE 5대 모두 `storage_controller` 가 비디오 컨트롤러 1건으로 나가고 진짜 RAID 는 `other` 다 — 분류로 집계하는 소비자가 오판.
- 수정 제안: `controller` 포괄 분기 앞에 `'video' in lid or 'graphics' in lid` → `other`(또는 enum 에 맞춰 제외) 를 두고, `' mr' + 숫자 + 'i-'` 같은 HPE 이름 패턴 대신 **같은 장비의 `data.storage.controllers[].controller_model` 과 이름이 같으면 storage_controller** 로 묶는 교차 참조(벤더 이름 아님, 같은 envelope 의 다른 섹션 값) 를 권장 — CSUS A-8 이 쓰는 위치 포함 관계와 같은 사고방식. 최소안은 `'video'` 제외 + `' mr4'`/`' sr9'` 같은 접두 토큰(HPE 제품군 명칭, 벤더 분기 아님) 추가.
- 회귀 테스트: `test_firmware_category.py` HPE 케이스에 `("13","HPE MR416i-o Gen11","storage_controller")`, `("21","Embedded Video Controller","other")`, CSUS `("PCIeDevice.3","HPE SR3258p-16i/e PCIe4 Controller","storage_controller")` 불변 고정.
- ADR 영향: ADR-2026-10-19 A-9 의 "`controller` 토큰" 결정에 부작용 기록(정정 제안: 비디오 제외). 문서: `schema/field_dictionary.yml:1156-1161`, `docs/ai/catalogs/EXTERNAL_CONTRACTS.md:15`.

### 04-firmware-003 — Lenovo 드라이브 백플레인 PSoC 가 `drive`
- 심각도: **MED**. 확실성: **확정**.
- 대상: sr650_v4_01..04 (`Drive_Backplane_<FRU>_PSoC_0xBB` + `…-Pending` 2건씩), r1_Lenovo_SR650_01 (`Drive_Backplane_<FRU>_PSoC_0xBB` ×2, `…_0xBA` ×1).
- 필드: `firmware[].category` (서버당 drive 집계가 +2).
- 근거: `FirmwareInventory/Drive_Backplane_…_PSoC_0xBB/index.json` — `Name "Firmware-PSoC:0xBB"`, `SoftwareId "STOREXP-BB-10"`(storage expander), `RelatedItem [/redfish/v1/Chassis/Drive_Backplane_<FRU>]`; 드라이브 항목은 `drive_bay_N`, `SoftwareId "DISK-…"`.
- 코드: `normalize_standard.yml:417` (`'disk' in lid or 'drive' in lid …` 가 `:418` `'backplane'` 보다 앞). 2026-06-14 FW-CAT 재정렬이 Dell `Disk.Bay…` 를 위해 `disk > backplane` 으로 둔 결과.
- 실제 출력 / 기대: `drive` / `backplane`.
- 원인(확정): id 에 `Drive_Backplane` 이 들어 있어 `drive` 가 먼저 걸린다.
- 영향: Lenovo drive 수가 실제 드라이브 수 + 백플레인 2 (sr650_v4_01: 4 → 6, 1차: 4 → 8).
- 수정 제안: `backplane` 토큰을 `drive` 앞으로 옮기되 Dell `Disk N in Backplane 1 of RAID Controller` 가 `drive` 로 남도록 "`disk` 토큰이 있으면 drive 우선, 없고 `backplane` 이면 backplane" 2단으로 한다(`'disk' in lid → drive` / `elif 'backplane' in lid → backplane` / `elif 'drive'…`). Dell 백플레인 `RAID.Backplane.Firmware.1`(Name "Backplane 1") 은 그대로 backplane.
- 회귀 테스트: `test_firmware_category.py` 에 Lenovo PSoC 2종(backplane) + Dell `Disk 0 in Backplane 1 …`(drive) 유지 케이스.
- ADR 영향: 없음. `tests/evidence/2026-06-14`(FW-CAT) 정렬 근거에 Lenovo 사례 추가.

### 04-firmware-004 — FC HBA 분류가 벤더 간 다르다 (Dell 만 `storage_controller`)
- 심각도: **LOW**. 확실성: **확정**.
- 대상: r1_DELL_R740_01 (`QLogic QLE2692 16Gbps Dual Port Fibre Channel Controller` ×4 → storage_controller) vs dl380_gen12_01/02/04 · r1_HPE_DL380_01 (`HPE SN1610Q 32Gb 2p FC HBA` → other), sr650_v4_02/03 (`QLogic QLE2772 32Gb 2-Port PCIe Fibre Channel Adapter` → other), csus3200_01/03 · r1_HPE_CSUS3200_03/04 (`HPE SN1100Q 16Gb 2p FC HBA` → other).
- 필드: `firmware[].category`.
- 코드: `normalize_standard.yml:421-428` (`controller` 포괄 토큰이 Dell 이름에만 걸림). `schema/field_dictionary.yml:1159` 는 "FC HBA 는 enum 에 없어 other" 라고 적는다.
- 실제/기대: 같은 장치 종류가 이름 어휘에 따라 `storage_controller`/`other` 로 갈린다 / 벤더 무관 한 값.
- 원인(확정): 분류가 이름 토큰에만 의존.
- 영향: 벤더 간 집계 비교 불가(계약상 enum 확장은 별도 결정).
- 수정 제안: enum 을 늘리지 않는 범위에서 `fibre channel`/`fc hba`/`hba` 토큰을 `controller` 앞에서 잡아 **일관되게 other** 로 두거나(현 계약 문구와 일치), enum 확장(`hba`)은 계약 결정 사항으로 분리. 어느 쪽이든 Dell 케이스를 테스트로 고정.
- 회귀 테스트: 4벤더 FC HBA 이름 4종이 같은 값인지.
- ADR 영향: 없음. 문서: field_dictionary help 문구("Dell 은 storage_controller" 현실 반영 또는 코드 정정).

### 04-firmware-005 — CPLD/FPGA 등 잔여 `other` 와 `nvme` 토큰 오분류
- 심각도: **LOW**. 확실성: **확정**.
- 대상: HPE 5대 — `System Programmable Logic Device`, `PCIe Riser 1/2/3 Programmable Logic Device`(CPLD) → other; Lenovo 5대 — `HPM-FPGA`(+Pending), `SCM-FPGA`(1차), `LXPM`, `LXUM` → other; r1_Lenovo_SR650_01 — `ThinkSystem M.2 RAID B540p-2HS SATA/NVMe Enablement Kit`(RAID 컨트롤러) → `drive`(`'nvme'` 가 `'raid'` 보다 앞), `Bundle.Current`(펌웨어 번들) → other; HPE `Intelligent Platform Abstraction Data`/`Intelligent Provisioning`/`HPE Smart Storage Energy Pack` 과 Dell `OS COLLECTOR` 는 enum 에 해당 범주가 없어 `other` 가 맞다(관찰).
- 필드: `firmware[].category`.
- 코드: `normalize_standard.yml:410`(`cpld` 토큰만), `:417`(`nvme` 토큰이 `raid` 앞).
- 실제/기대: `Programmable Logic Device`/`FPGA` → other / `cpld`; M.2 RAID 키트 → drive / storage_controller.
- 수정 제안: `cpld` 분기에 `programmable logic`·`fpga` 토큰 추가; `nvme`/`ssd` 보다 `raid` 를 먼저 보되 Dell `Disk.Bay…RAID.Slot` 은 `disk` 가 더 앞이라 불변(04-firmware-003 의 2단 규칙과 함께 설계).
- 회귀 테스트: 위 이름 6종.
- ADR 영향: 없음.

### 04-firmware-006 — Lenovo `*-Pending` 빈 스테이징 슬롯이 `pending: true` 항목으로 나간다
- 심각도: **MED**. 확실성: 빈 슬롯인 점은 **확정**(5대 전부 `Version ""`/null, `Status.State "Disabled"`, `ReleaseDate null`), 실제 보류 이미지가 있을 때의 응답은 **검증불가**(11대 중 사례 없음).
- 대상: sr650_v4_01..04 (각 `BMC-Primary-Pending`, `HPM-FPGA-Pending`, `UEFI-Pending`, `Drive_Backplane_…_PSoC_0xBB-Pending` 4건), r1_Lenovo_SR650_01 (`BMC-Primary-Pending`, `UEFI-Pending` 2건).
- 필드: `firmware[].pending`, `firmware[].version`(null), 개수.
- 근거: `FirmwareInventory/UEFI-Pending/index.json` — `Version ""`, `Status {"Health":"OK","State":"Disabled"}`, `ReleaseDate null`, `Updateable true`; 활성 항목 `UEFI` 는 `State "Enabled"`. `BMC-Backup.Oem.Lenovo.PendingVersion ""`.
- 코드: `redfish_gather.py:4999` (`_is_pending_fw_id` — id 에 `pending`), `:5080-5085` (pending 이면 빈 Version 을 null 로 보존), `schema/field_dictionary.yml:1170-1177` ("pending=true + version=null 은 정상(의도된 보류)").
- 실제 출력 / 기대: `{"id":"UEFI-Pending","version":null,"pending":true}` / 보류 이미지가 없으면 항목을 내지 않거나(`Previous-` 와 같은 취급) `pending` 이 "보류 이미지 있음" 일 때만 true.
- 원인(확정): XCC 는 보류 여부와 무관하게 `-Pending` 슬롯 리소스를 항상 노출하고, 코드는 id 문자열만 본다.
- 영향: Lenovo 전 서버에 "적용 보류 펌웨어 4건" 이 상시 표시되고 firmware 개수가 부풀며(28 중 4), `version null` 이 "데이터 누락" 과 구분되지 않는다(사전 문구가 두 경우를 같은 말로 설명).
- 수정 제안(공통 로직): pending 항목의 **구조 신호**로 판정 — `Status.State == "Disabled"` 이고 `Version` 이 비면 "보류 이미지 없음" 으로 보고 항목을 제외하거나(가장 작은 출력 변화) notice 1건을 남긴다; `Version` 이 있으면 종전대로 `pending: true`. 벤더 이름은 보지 않는다. 사전 help 를 "pending=true 는 보류 이미지가 있을 때" 로 정정.
- 회귀 테스트: 빈 슬롯(Version "", State Disabled) → 제외/notice, 채워진 슬롯(Version "X", State Enabled|Disabled) → pending true 2분기; 1차 `real_lenovo_sr650` 골든(26건 중 2건 -Pending) 갱신.
- ADR 영향: 없음(2026-06-15 "Lenovo XCC pending fw" 결정은 빈 슬롯 사례를 전제로 하지 않았다). 문서: field_dictionary `firmware[].pending`.

### 04-firmware-007 — CSUS 보충 항목의 `updateable` 이 null (사전 type boolean)
- 심각도: **LOW**. 확실성: **확정**.
- 대상: csus3200_01..03, r1_HPE_CSUS3200_01..04 (`PCIeDevice.*` · `PowerSupply.*` 전부).
- 필드: `firmware[].updateable` (`schema/field_dictionary.yml:1680` `type: "boolean"`, priority skip).
- 근거: `Chassis/r001u01/PCIeDevices/1` 키 `[FirmwareVersion, Manufacturer, Model, Name, Oem, PartNumber, SKU, SerialNumber, Slot, Status]` — `Updateable` 없음; PSU 도 없음.
- 코드: `redfish_gather.py:6442`, `:6459` (`'updateable': None`).
- 실제/기대: null / 원천이 없으므로 null 이 정직하다 — 사전 type 을 `boolean|null` 로 맞추는 쪽이 옳다.
- 수정 제안: 사전 type 정정(코드 불변). 회귀: `test_field_dictionary_*` 의 type 검사에 null 허용.
- ADR 영향: ADR-2026-10-19 A-9 문서에 "보충 항목 updateable null" 명시.

### 04-firmware-008 — Dell first-seen dedup 의 접두사 혼재 (관찰)
- 심각도: **LOW**. 확실성: **확정**.
- 대상: r1_DELL_R740_01 (출력 32 = `Current-` 19 + `Installed-` 13).
- 필드: `firmware[].id`.
- 근거: Members 순서가 `Current-…` 19건이 먼저, `Installed-…` 가 뒤 → `Installed-`/`Current-` 쌍 19개는 `Current-` 가 남고, 쌍이 없는 13개(PSU·디스크·iDRAC·CPLD·LC 등)는 `Installed-`. `Systems/System.Embedded.1/Bios.Links.ActiveSoftwareImage` 는 탈락한 `Installed-159-2.26.1__BIOS.Setup.1-1` 을, `Managers/iDRAC.Embedded.1.Links.ActiveSoftwareImage` 는 남은 `Installed-25227-…` 를 가리킨다.
- 코드: `redfish_gather.py:5030-5060` (first-seen, 2026-10-03 C6 결정).
- 영향: 값(version)은 같아 데이터 손실은 없지만 id 가 Members 순서에 의존한다 — iDRAC 이 순서를 바꾸면 같은 장비의 id 가 바뀔 수 있다(가설). `ActiveSoftwareImage` 로 BIOS/BMC 항목을 찾는 개선(§5) 을 하려면 dedup 전 쌍 전체에서 찾아야 한다.
- 수정 제안: 없음(C6 결정 유지). §5 개선 시 `ActiveSoftwareImage` 매칭을 `_fw_dedup_key` 기준으로 한다.

### 04-firmware-009 — 전원 Off 스냅샷(dl380_gen12_03)의 13건은 raw 그대로, `updateable` 이 전원 상태를 따른다
- 심각도: **LOW**. 확실성: raw 일치는 **확정**, 전원 Off 인과는 **추정**.
- 대상: dl380_gen12_03 (`Systems/1.PowerState "Off"`, `Oem.Hpe.PostState "PowerOff"`, `Status.State "Disabled"`).
- 필드: `firmware[]` 개수(13 vs 다른 3대 25), `updateable`.
- 근거: `UpdateService/FirmwareInventory` Members 13 == 출력 13 (파서 누락 0). 01 에 있고 03 에 없는 이름: `Power Supply Firmware` ×2(03 의 `Chassis/1/Power.PowerSupplies[].State "Absent"`, `FirmwareVersion "0.00"`), `1.60TB 22.5G SAS SSD` ×2·`UBM6 BC BP` ×2(03 은 `Storage` 드라이브 0), `HPE SN1610Q FC HBA` ×2(03 은 `PCIeDevices` 4장 — 장착 차이), `PCIe Riser 3 PLD`. 03 의 `iLO 7`·`System ROM` 은 `Status.State "InTest"`, PCIe 항목 `Updateable false`(01 은 true).
- 코드: 해당 없음(raw 충실).
- 영향: 전원 Off 서버는 firmware 목록이 짧고 `updateable` 이 false 로 나온다 — 소비자가 "업데이트 불가" 로 읽지 않도록 `hardware.power_state` 와 함께 해석해야 한다(02-memory-001 과 같은 뿌리).
- 수정 제안: 없음(기존 필드로 표현할 상태가 없다). 문서에 "전원 Off 시 iLO 가 PSU/드라이브/백플레인 펌웨어를 열거하지 않고 Updateable 을 false 로 낸다(실측 1대)" 기록.

### 04-firmware-010 — Lenovo 버전 표기가 두 가지 (관찰)
- 심각도: **LOW**. 확실성: **확정**.
- 대상: sr650_v4_01..04, r1_Lenovo_SR650_01.
- 필드: `hardware.bios_version`(`IHE120L`/`IHE120P`/`IHE110U` = `System.BiosVersion`) vs `firmware[]` UEFI `version`(`20L-1.50`/`20P-1.51`/`10U-1.20`); `bmc.firmware_version`(`IHX438R 2.97 20260910` = `Manager.FirmwareVersion`) vs `BMC-Primary.version`(`38R-2.97`).
- 근거: 같은 빌드의 두 표기(빌드 ID 7자 ↔ 끝 3자 + 버전). 계약(6.6, field_dictionary `hardware.bios_version`) 대로 원천이 다르므로 값이 다른 것이 맞다.
- 영향: Portal 에서 두 값을 대조하면 "불일치" 로 보인다. 수정 제안: 없음(원천 보존). 문서에 표기 관계를 적는다.

### 04-firmware-011 — CSUS `hardware.bios_version == bmc.firmware_version`(complex 번들) · bios/bmc 항목 없음
- 심각도: **LOW**. 확실성: **확정**.
- 대상: csus3200_01..03, r1_HPE_CSUS3200_01..04.
- 필드: `hardware.bios_version`, `bmc.firmware_version`, `firmware[].category`.
- 근거: `Systems/Partition0.BiosVersion` = `Managers/RMC.FirmwareVersion` = `FirmwareInventory/ComplexFW.Version` = `Partition0_FW.Version` = `1.77.30-20260911_061319`(1차 `1.75.108-…`). RMC 는 BIOS 를 번들 버전으로만 보고한다(실 BIOS 빌드 문자열 없음).
- 코드: `redfish_gather.py:2633`(BiosVersion 그대로), `gather_bmc`(Manager.FirmwareVersion).
- 영향: CSUS 에서 "BIOS 버전" 과 "BMC 버전" 이 같은 문자열 — 장비 사실이라 값은 맞다. `firmware[]` 에 `bios`/`bmc` 범주가 없어 다른 벤더와 집계 형태가 다르다(04-firmware-001).
- 수정 제안: 04-firmware-001 의 `Partition<N>_FW → bios` 와 함께 `ComplexFW → bmc`(Description "Firmware on the RMPs and PDHCs") 를 둘지 결정. 문서(`docs/contract/03-fields.md` 9절) 에 "CSUS 는 번들 버전" 명시.

### 04-firmware-012 — 계약 문서에 `data.firmware` 절이 없고 category help 가 실제와 다르다
- 심각도: **LOW**. 확실성: **확정**.
- 대상: 전 벤더(문서).
- 근거: `docs/contract/03-fields.md` 는 1절 예시 1줄(`:61`)과 3절 표(`:147`)뿐 6.x 절이 없다(6.1~6.8 에 firmware 없음). `schema/field_dictionary.yml:1157` "FC HBA 는 enum 에 없어 other" 는 Dell 에 맞지 않는다(04-firmware-004); `firmware[].pending` help 는 빈 슬롯을 설명하지 않는다(04-firmware-006).
- 수정 제안: 6.9 `data.firmware` 절 신설(항목 키 7개, Dell dedup/Previous 제외, Lenovo -Pending, CSUS 보충, 전원 Off 거동, category 규칙 요약). 회귀: 문서 drift 검사 대상 추가 여부는 하네스 결정.

### 04-bios-001 — Lenovo `hardware.bios_date` null, 원천은 `FirmwareInventory/UEFI.ReleaseDate`
- 심각도: **LOW**(nice 필드). 확실성: 원천 존재는 **확정**, "ReleaseDate = BIOS 릴리스 날짜" 의미는 **추정**(Lenovo UEFI 빌드 공개일로 보이나 사양 미확인).
- 대상: sr650_v4_01..04 (`2026-05-11T00:00:00Z` ×3, 03 `2026-06-22T00:00:00Z`), r1_Lenovo_SR650_01 (`2025-03-15T00:00:00Z`).
- 필드: `hardware.bios_date`.
- 근거: `Systems/1` 과 `Oem.Lenovo` 에 날짜 키 없음(`_extract_oem_lenovo` `:2242-2270` 도 날짜를 뽑지 않음); `FirmwareInventory/UEFI` 는 `ReleaseDate` 보유, `RelatedItem → /Systems/1/Bios`, `Systems/1/Bios.Links.ActiveSoftwareImage → …/UEFI`(DMTF Bios v1.1+ 표준 링크). Dell 도 같은 링크가 있고 `BIOS` 항목 `ReleaseDate 2026-01-28` 이 OEM `BIOSReleaseDate` 와 같다(교차 검증). HPE 는 `ReleaseDate "0000-01-01T00:00:00Z"` 자리표시자라 쓸 수 없다(04-firmware-012 관찰, `_normalize_bios_date` 는 연도 0 을 ISO 로 못 만들어 raw 보존).
- 코드: `redfish_gather.py:2634-2636`(bios_date None), `_hoist_oem_extras :2305`.
- 실제/기대: null / `2026-05-11`.
- 수정 제안(공통 로직, 요청 0 추가): OEM 날짜가 없을 때 — firmware 섹션이 이미 받은 항목 중 `RelatedItem` 이 System 의 `Bios` 링크(`bios_link.link`) 와 같은(또는 `Bios.Links.ActiveSoftwareImage` 가 가리키는) 항목의 `ReleaseDate` 를 `_normalize_bios_date` 로 넣는다. 연도 `0000` 은 absent 로 본다. 벤더 이름 분기 없음. Dell/HPE 는 OEM 값이 먼저라 불변.
- 회귀 테스트: Lenovo 축약 fixture(UEFI ReleaseDate) → `2026-05-11`; HPE `0000-01-01` → null 유지; Dell OEM 우선 유지.
- ADR 영향: 없음. field_dictionary `hardware.bios_date` help 에 원천 2순위 추가.

### 04-bios-002 — `bios.current.attributes` 에 식별·네트워크 정보가 그대로 들어간다 (계약대로, 관찰)
- 심각도: **LOW**. 확실성: **확정**.
- 대상: 18대 전부. HPE: `SerialNumber`, `ServerName`(FQDN), `ServerAssetTag`, `ProductId`; Lenovo: `NetworkBootSettings_MACAddress_N`, 어댑터별 `…_MACAddress`, FC `…_Drive0WWPN`/`LUN`, `PasswordRuleandPolicy_*`(정책값); Dell: `SystemManufacturer`/`SystemServiceTag` 류; CSUS: `Ipv4PxeServerAddress`, `UrlBootFile`.
- 필드: `bios.current.attributes` (계약 6.8 "필터·마스킹 없음", 2026-09-15 결정).
- 영향: 결과 JSON 에 호스트명·시리얼·MAC·WWPN 이 BIOS 속성 경로로 한 번 더 실린다 — 저장/전송 정책이 `hardware.serial` 등과 같은 수준으로 다뤄야 한다. 2차 Mock 은 치환 도구로 호스트명이 바뀐 상태라 이 보고서에는 값을 싣지 않았다.
- 수정 제안: 없음(스키마·계약 고정). 문서 6.8 에 "포함 가능한 식별 정보 종류" 1줄.

### 04-bios-003 — CSUS `Bios/Settings` 에 실제 보류 차이 2건 + 주석 키 (계약 밖, 관찰)
- 심각도: **LOW**. 확실성: **확정**.
- 대상: csus3200_01..03, r1_HPE_CSUS3200_01..04 (7대 동일).
- 근거: `Systems/Partition0/Bios/Settings.Attributes` 77키 = current 76 + `@Redfish.WriteableProperties`(쓰기 가능 키 목록이 Attributes 안에 주석 키로 들어옴); 값 차이 `XncDataForwarding` Enabled→Auto, `MemPprType` HardPpr→Auto (7대 전부 같은 두 키 — 기본값 표시일 가능성, 가설). DL380 4대·1차 1대 `bios/settings` 는 current 와 차이 0, Lenovo 5대 `Bios/Pending` 차이 0, Dell `Bios/Settings.Attributes {}`.
- 영향: 없음(수집 안 함이 계약). `bios.current` 안에 pending 을 넣을 자리가 없어 확장 제안 없음.

### 04-test-001 — Tier 0 순서 의존 실패: `replay_full_mirror.install_fakes` 가 `rg._get` 을 복원 없이 교체
- 심각도: **MED**(회귀 신뢰도). 확실성: **확정**(재현).
- 대상: `tests/unit/test_redfish_bios_current.py` 8건(`test_bios_response_does_not_change_auth_evidence`, `test_real_recording_*` 7건) — 제품 코드 결함 아님.
- 근거(재현, 이 worktree, Windows Python 3.13):
  - `pytest tests/unit/test_full_mirror_dryrun.py::test_v2_tree_is_consumed_by_replay_and_convert tests/unit/test_redfish_bios_current.py` → **8 failed, 71 passed** (실패 목록이 `tier0/pytest_unit.log` 의 8건과 같다; 첫 실패 `calls[0]` IndexError — `_get_impl` 이 한 번도 호출되지 않음).
  - `pytest tests/unit/test_redfish_bios_current.py` 단독 → **78 passed**.
- 코드: `tests/redfish-probe/replay_full_mirror.py:294-308` `install_fakes` — `rg._get = fake_get`, `rg._get_noauth = fake_get_noauth` (옛 seam, 복원 없음; `tests/unit/test_mirror_replay_tools.py:61` 도 "install_fakes 는 되돌릴 수 없다" 고 적음); `:311-313` `run()` 이 호출; `tests/unit/test_full_mirror_dryrun.py:990-1001` 이 `rep.run(Path(out), manager_layout="rmc_primary")` 호출. 반면 `tests/integration/emulator_harness.py:90-93,203` 과 bios 테스트는 2026-10-03 P2 seam `rg._get_impl` 을 바꾼다 — `_get` 자체가 가짜로 바뀌어 있으면 `_get_impl` 은 도달하지 못한다.
- 영향: 한 프로세스 실행에서 뒤에 오는 `_get_impl` seam 테스트가 CSUS 합성 응답 맵을 보게 된다. 같은 로그의 `test_redfish_audit_2026_10_10.py`(3) · `test_redfish_phase3_contracts.py`(6) · `test_redfish_redirect_boundary.py`(1) · `test_sanitize_mirror.py`(1) 도 같은 원인일 가능성이 크다(가설 — 각각 쌍 실행 미수행).
- 수정 제안(테스트 도구만): `install_fakes` 를 `_get_impl`/`_get_noauth` seam 으로 옮기고 이전 값을 돌려주는 컨텍스트 매니저(또는 `run()` 의 `finally` 복원) 로 바꾼다; 또는 해당 테스트가 `monkeypatch.setattr(rg, "_get", …)` 로 감싼다. 제품 코드 변경 없음.
- 회귀 테스트: 쌍 실행(`test_full_mirror_dryrun.py` → `test_redfish_bios_current.py`) 이 통과하는지; `rg._get is rg_original_get` 를 세션 종료 fixture 로 검사.
- ADR 영향: 없음. 문서: `docs/ai/catalogs/TEST_HISTORY.md` 의 "분리 실행 단위" 설명에 원인 기재.

## 5. 미추적 Redfish 정보 (기존 필드로 표현 가능한 것만 개선안; 계약 밖은 관찰)
| 정보 | 어디에 있나 (11대 실측) | 기존 필드로의 개선안 / 관찰 |
|---|---|---|
| BIOS 펌웨어 항목의 구조적 식별 | Lenovo·Dell `Systems/<id>/Bios.Links.ActiveSoftwareImage` → FirmwareInventory 항목; Lenovo `RelatedItem → …/Bios`; HPE·CSUS 는 링크 없음 | `firmware[].category = bios` 판정의 1순위 신호로 쓰면 이름 토큰 의존을 줄인다(04-firmware-001). 요청 0 추가(Bios 본문은 이미 받는다) |
| BMC 펌웨어 항목의 구조적 식별 | Lenovo·Dell `Managers/<id>.Links.ActiveSoftwareImage`(`BMC-Primary`, `Installed-25227-…iDRAC`); Lenovo `RelatedItem → /Managers/1` | `category = bmc` 1순위 신호 — 단 Dell 은 dedup 전 쌍(`Installed-/Current-`) 기준 매칭(04-firmware-008) |
| BIOS 릴리스 날짜 | Lenovo UEFI `ReleaseDate`; Dell 전 항목 `ReleaseDate`(BIOS 는 OEM 값과 일치); HPE 전 항목 `0000-01-01T00:00:00Z`(자리표시자); CSUS 없음 | `hardware.bios_date` 2순위 원천(04-bios-001) |
| 보류 이미지 유무 | Lenovo `-Pending` 항목 `Status.State`/`Version`; HPE `UpdateService/UpdateTaskQueue`(5대 모두 멤버 0) · `InstallSets`(각 1) · `ComponentRepository`(3~9 — `/fwrepo/*` 바이너리 이미지 보유) | `firmware[].pending` 판정 보강(04-firmware-006). HPE 큐/저장소는 계약 밖 — 관찰만 |
| CSUS 보충 항목의 `updateable` | PCIeDevice/PowerSupply 에 `Updateable` 없음 | 원천 없음 — null 유지, 사전 type 정정(04-firmware-007) |
| HPE 항목 위치 | `Oem.Hpe.DeviceContext`("PCI-E Slot 1", "Bay 1", "Slot=14:Port=2:Box=3:Bay=1"), `DeviceInstance`(PciRoot 경로), `DeviceClass` UUID | `component` 는 계약상 SoftwareId(must) 라 바꾸지 않음 — 관찰. 같은 슬롯 라벨이 `network.adapters[]`/`storage` 와 대조 가능 |
| 드라이브 펌웨어 | HPE·Lenovo·Dell: FirmwareInventory 에 드라이브 항목 있음(`drive_bay_N`, `1.60TB 22.5G SAS SSD`, `Disk.Bay…`); CSUS: `Drives/*.Revision` 만(4대 ×4 드라이브, firmware[] 에 없음) | CSUS 에서 A-9 보충 범위를 드라이브 `Revision` 까지 넓힐 수 있으나(`PCIeDevice.`/`PowerSupply.` 와 같은 `Drive.<Id>` 항목) — 다른 벤더는 중복이 되므로 `complex_only` 장비에 한정; 결정 항목(관찰) |
| 네트워크 카드 펌웨어 | 전 벤더 `network.adapters[].firmware_version` 와 firmware[] 값이 일치(HPE `237.1.148.0`, Lenovo `5.00 (0x80021D15)`, Dell `21.40.25.31`, CSUS PCIe `26.48.1000`) | 이미 표현됨 — 문제 없음 확인 |
| HPE `SoftwareInventory` | 5대 모두 컬렉션은 있으나 멤버 0 | 미요청으로 잃는 정보 없음(관찰) |
| HPE `Oem.Hpe.Bios.{Backup,Bootblock}` · `UefiClass` | Backup/Bootblock `{}`(빈 객체), `UefiClass 3` | 계약 밖(관찰) |
| Lenovo `Bios.Oem.Lenovo` | `IsUefiAdminPasswordSet false`, `IsUefiPowerOnPasswordSet false`, `SettingsLockdown false`(2차만), `UEFIVariablesRO false` | 계약 밖(관찰) |
| Dell `Bios.ResetBiosToDefaultsPending` · HPE `Bios.Actions.#Bios.ChangePassword` | 1차 Dell `false`; HPE Actions 2종 | 계약 밖(관찰) |
| `AttributeRegistry` 본문 | `Registries/BiosAttributeRegistryU68.v1_1_82|90`, `BiosAttributes.v9.60.1`, `BiosAttributeRegistry.1.0.0` (전부 `exists_untouched`) | 계약이 명시적으로 미수집 — 관찰 |
| `SecureBoot`·`BootOptions` | 11대 전부 존재·미요청(`Systems/<id>/SecureBoot`, `BootOptions/*` HPE 12~23 · Lenovo 5 · CSUS 2) | 계약 밖(관찰) |
| Lenovo `Bundle.Current`(펌웨어 번들, 1차만) · `UpdateService.Oem.Lenovo.BundleRepoAvailableSpaceInKB` | 2차 4대에는 `Bundle.Current` 항목 없음 | 관찰 |

## 6. ADR·문서·테스트 교차 검증 (모순/정정 제안)
| 문서/결정 | 당시 가정 | 새 증거(2차) | 정정 제안 |
|---|---|---|---|
| ADR-2026-10-19 A-9 "RMC FirmwareInventory 는 complex/nPar 번들 2건뿐 → `complex_only` 보충" | RMC 1.75.108 4노드 | RMC 1.77.30 3대도 2건(`ComplexFW`·`Partition0_FW`) + PCIe 7/3/7 장치 전부 `FirmwareVersion` 보유 → 13/9/13. 1차 01/02 가 6건이었던 것은 PCIe 장치 `FirmwareVersion null`(Model 도 일부 null) 때문 | 결정 유지(확정). 설명에 "1차 node01/02 PCIe 펌웨어 부재는 장비 응답" 과 "보충 항목 updateable null"(04-firmware-007) 추가 |
| ADR-2026-10-19 A-9 "`controller` 토큰 → storage_controller" | CSUS `HPE SR3258p-16i/e PCIe4 Controller` | HPE `Embedded Video Controller` 가 storage_controller, `HPE MR416i-o Gen11` 은 other | 토큰 규칙 정정(04-firmware-002) |
| 2026-06-14 FW-CAT 재정렬 "`disk > backplane`" | Dell `Disk.Bay…RAID.Slot` | Lenovo `Drive_Backplane_…PSoC` → drive | 2단 규칙(04-firmware-003) |
| 2026-06-15 SCHEMA-07 "`System ROM` → bios" | HPE | HPE 5대 정상; Lenovo `UEFI`·CSUS `Partition0_FW` 는 여전히 other | `uefi` 토큰·nPar 패턴 추가(04-firmware-001) |
| 2026-06-15 CSUS-R9 "PSU `firmware_version` = FirmwareVersion or Version" | RMC 1.75 | 1.77.30 도 `FirmwareVersion` 부재·`Version "Release -0005"` | 유지 |
| `schema/field_dictionary.yml:1170-1177` "pending=true + version=null 은 정상(의도된 보류)" | Lenovo pending fw 존재 | 5대 전부 빈 스테이징 슬롯(`Version ""`, `State Disabled`) | 문구 정정 + 판정 보강(04-firmware-006) |
| `schema/field_dictionary.yml:1159` "FC HBA 는 enum 에 없어 other" | HPE/CSUS | Dell FC HBA 는 storage_controller | 코드 또는 문구 정정(04-firmware-004) |
| `schema/field_dictionary.yml:1680` `firmware[].updateable` type boolean | 표준 항목만 | CSUS 보충 항목 null | `boolean|null`(04-firmware-007) |
| `docs/contract/03-fields.md` 6.8 "Bios 하위 리소스 미수집·Current 만" | — | 18/18 요청 로그로 확인(하위 요청 0) | 유지. CSUS Settings 의 실제 보류 차이는 관찰로 기록(04-bios-003) |
| `docs/contract/03-fields.md` 6.6 "`bmc.firmware_version` 은 Manager 보고 값(FirmwareInventory 아님)" | — | HPE/Dell 은 두 값 동일, Lenovo 는 표기 차이, CSUS 는 번들로 동일 | 유지 + 표기 관계 1줄(04-firmware-010/011) |
| `docs/ai/catalogs/EXTERNAL_CONTRACTS.md:15,55` | RMC 1.75 FirmwareInventory 2건 / Dell Id 형식 | 2차 동일 | "RMC 1.77.30 동일" 추기 |
| `tests/unit/test_firmware_category.py:80-84` CSUS 두 번들 `other` 고정 | 무영향 확인 목적 | 04-firmware-001 채택 시 기대값 변경 | 테스트 갱신 |
| `tests/unit/test_redfish_phase2_contracts.py` C6 "R740 멤버 GET 62 → 32" | 1차 실미러 | Tier 1 `server_access` 멤버 GET 32회 확인 | 유지(PASS) |
| `tests/integration/test_bios_real_capture_replay.py` (Dell R760 ×5 · DL380 Gen11 · SR650 V2 · CIMC) | 4 벤더 실캡처 | 2차 세대(iLO 7 · XCC3 · RMC 1.77) 실응답으로도 attributes 18/18 동일 — 코드 변경 없이 통과 | 2차 zip(`tests/reference/redfish/mock2`) 를 쓰는 재생 케이스는 아직 없음(§7) |
| `tests/evidence/2026-10-26-redfish-mock2-audit/baseline/README.md` Tier 0 "테스트 격리 결함 후보" | 원인 미특정 | `install_fakes` 의 `rg._get` 영구 교체 | 04-test-001 로 확정 |
| 02 보고서 02-cpu-001 전제(HT 속성 존재) | 추정 | 18/18 존재·문자열·pending 동일 | 전제 성립 |

02 보고서용 HT 속성 표(현재값 = pending 값):

| label | 키 | 값 |
|---|---|---|
| csus3200_01 / 02 / 03 | `HThread` | Enabled / **Disabled** / Enabled |
| dl380_gen12_01 / 02 / 03 / 04 | `ProcHyperthreading` | Enabled / Enabled / **Disabled** / Enabled |
| sr650_v4_01 / 02 / 03 / 04 | `Processors_Hyper_Threading` | **Disabled** / **Disabled** / Enabled / **Disabled** |
| r1_DELL_R740_01 | `LogicalProc` | Enabled |
| r1_HPE_CSUS3200_01..04 | `HThread` | Enabled ×4 |
| r1_HPE_DL380_01 | `ProcHyperthreading` | Enabled |
| r1_Lenovo_SR650_01 | `Processors_Hyper_Threading` | Enabled |

## 7. Replay·테스트 허점 (숨겨지는 오류, 과도한 default/stub, 미커버 경로)
1. **seam 이중화**: `replay_full_mirror.install_fakes` 는 `_get` seam, `emulator_harness.run_gather` 는 `_get_impl` seam 을 쓴다. 전자가 복원 없이 남아 후자를 가린다(04-test-001). `test_mirror_replay_tools.py` 는 이를 알고 자체 fixture 로 피하지만 `test_full_mirror_dryrun.py:990` 은 `rep.run()` 을 그대로 부른다.
2. **category 는 어떤 재생 층에서도 검증되지 않는다** — Tier 2/골든/`emulator_harness` 는 모듈 출력(7키 중 6키)까지만이고 `category` 는 Ansible normalize 에서 생긴다. `test_firmware_category.py` 가 Jinja 블록을 추출해 돌리지만 Lenovo·CSUS 실 이름은 2종만, HPE 는 7종만 고정 — 04-firmware-001~005 는 전부 그 사각지대. Tier 1(실 ansible) 만이 잡았다.
3. **Lenovo `-Pending` 빈 슬롯** — 1차 골든 `real_lenovo_sr650` 이 `pending: true, version: null` 2건을 "정상" 으로 고정해 04-firmware-006 을 반증하지 못한다.
4. **FirmwareInventory 페이지네이션 미발동** — 18 label 모두 단일 페이지(`Members@odata.count` == 수집 수, `nextLink` 없음) → `_collection_walk` 의 nextLink/상한/count 불일치 notice 경로는 Mock 으로 검증되지 않음(MOCK_LIMITATION; 단위 테스트는 있음).
5. **멤버 GET 실패·대체 멤버·stub 금지 경로 미발동** — 18 label 모든 멤버 GET 이 200(C6 의 500 → 대체 fallback 은 합성 테스트만).
6. **BIOS 실패 분기 미발동** — 18/18 `Bios` 200. 404/401/403/5xx/비표준 `@odata.type`/`Attributes` 부재 분기는 `test_redfish_bios_current.py` 합성 케이스만 — 그리고 그 파일이 04-test-001 에 걸려 있다.
7. **`gather_bios` 의 `_get` 캐시 의존** — bios 요청이 1회인 것은 `server_access.jsonl` 로 확인했지만, 캐시가 꺼진 경로(precheck 모드 등)는 이 분석 범위 밖.
8. **2차 zip 미사용** — `tests/reference/redfish/mock2/*.zip` 을 읽는 pytest 가 아직 없다(`grep -rln mock2 tests/` → README/INDEX 만). iLO 7 · XCC3 · RMC 1.77 세대의 firmware/bios 회귀는 이번 Tier 1/2 수동 재생이 유일하다.
9. 재생 한계(`EVID/baseline/README.md` 1~9) 중 firmware/bios 에 닿는 것은 없다 — 모든 요청이 미러 안에 있고 200 이었다. DL380 의 소문자 `systems/1/bios` 는 재생 서버·인벤토리 키가 대소문자를 구분하므로 "실장비가 대소문자 무시로 응답하는지" 는 Mock 으로 알 수 없지만, 크롤러가 실장비에서 그 경로로 200 을 받았으므로(인벤토리 `exists`) 코드가 링크 그대로 요청하는 현 동작은 안전하다.

## 8. 1차 7대 및 기존 모델 영향
- 1차 7대 Tier 1: Dell 32(접두 혼재, category 13종 정상·FC HBA storage_controller), CSUS 01/02 6(PCIe 펌웨어 부재 → PSU 4 만 보충), CSUS 03/04 15, DL380 22(2차와 같은 오분류 9건), SR650 26(`UEFI` other, PSoC → drive ×3, -Pending 2건). 1차 골든(`tests/fixtures/redfish/real_*/expected_output.json`) ↔ Tier 2 모듈 출력은 bios 외 동일(README) — 즉 골든은 04-firmware-001/003/006 의 현재 동작을 고정하고 있어 채택 시 갱신 대상.
- 04-firmware-001/002/003/005 의 토큰 변경은 Dell 1차 13종 케이스(`test_firmware_category.py`)가 전부 불변이어야 한다 — 제안 규칙(`diagnostic` 먼저 → `bios/system rom/uefi/Partition<N>_FW` → `cpld/programmable logic/fpga` → … → `disk` → `backplane` → `raid` → `drive/nvme/…` → … → `fibre channel/fc hba` 는 other → `video` 제외 → `controller`) 을 Python 으로 옮겨 18 label 전수 재분류한 dry-run(SCRATCH `proposed_rule.py`): 기존 테스트 케이스 23종(Dell 13 · HPE 7 · RD-FW1 3 · CSUS A-9 2) 깨짐 0; 바뀌는 항목은 HPE 서버당 5~6건(PLD 3~4 → cpld, MR4xxi-o → storage_controller, Embedded Video Controller → other), Lenovo 6~8건(UEFI(+Pending) → bios, HPM/SCM-FPGA → cpld, PSoC → backplane, 1차 M.2 RAID 키트 → storage_controller), CSUS 2건(Partition0_FW → bios, ComplexFW → bmc), Dell 은 FC HBA 일관화(04-firmware-004 채택 시)에서만 QLogic 4건이 storage_controller → other 로 바뀐다 — 그 선택을 빼면 Dell 결과 불변.
- Cisco CIMC 4.1(`schema/baseline_v1/cisco_baseline.json` firmware 항목 0, 2026-04-29 "N/A" 필터) · Supermicro 등 lab 부재 벤더: 토큰 추가는 이름에 해당 토큰이 있을 때만 작용하므로 영향 추정 불가(합성 테스트로만).
- `hpe_csus_3200_baseline.json` 의 firmware 9건(bmc 2 · tpm · psu · other · nic · drive · cpld · bios)은 합성 mock 기반이라 실 RMC(2건 + 보충)와 다르다 — 실측 교체 대상(NEXT_ACTIONS 기존 항목).
- Superdome Flex adapter(`hpe_superdome_flex.yml`) 의 `firmware_inventory_scope: complex_only` 는 실측 0건 — CSUS 결과로 유추만 가능.

## 9. 검증 한계 (재생 한계·Mock 한계·미확인)
- 전원 Off 가 firmware 13건·BIOS 275건의 원인인지, 장착 차이인지는 dl380_gen12_03 1대 스냅샷으로 분리할 수 없다(PCIe 장치 4장은 장착 차이로 확정, PSU/드라이브 항목 부재는 전원 Off 추정).
- Lenovo 에 실제 보류 이미지가 있을 때 `-Pending` 항목이 어떻게 바뀌는지(Version/State) 미관측 — 04-firmware-006 의 "채워진 슬롯" 분기는 검증불가.
- `firmware[]` 의 `updateable` 이 전원 On 으로 돌아오면 true 가 되는지 미관측(가설).
- Lenovo UEFI `ReleaseDate` 의 정확한 의미(빌드일 vs 공개일)는 사양 미확인(04-bios-001 추정).
- FirmwareInventory 다중 페이지·멤버 GET 실패·BIOS 조회 실패·비표준 Bios type 은 11대에서 발생하지 않아 Mock 으로 검증 불가(합성 테스트만).
- DL380 소문자 Bios 링크의 실장비 대소문자 처리(대문자 요청 시 응답)는 미러에 없다 — 현재 코드는 링크 그대로 요청하므로 영향 없음.
- 1차 v1 미러는 비-2xx 를 기록하지 않아(README 6) 1차 label 의 firmware/bios 실패 분기는 재생할 수 없다(해당 요청은 전부 2xx 라 결과 영향 없음).
- Tier 0 의 다른 11건 실패(`test_redfish_audit_2026_10_10` 등)가 같은 원인인지는 쌍 실행하지 않았다(가설).

## 10. 탐색 경로 기록 (무엇을 어떻게 봤는지 — 문제 없음도 기록)
- 코드: `redfish-gather/library/redfish_gather.py` (`_fill_adapter_models_from_firmware :769`, `_p :690`, `_CODE_BIOS_NON_BLOCKING :824`, `_collection_members/_capped :1225-1270`, `_extract_oem_hpe :2093`, `_extract_oem_dell :2147`, `_extract_oem_lenovo :2242`, `_hoist_oem_extras :2305`, `_normalize_bios_date :2442`, `gather_system :2552-2715`, `gather_bios :2721-2799`, `_pcie_devices_for_chassis :3515`, `_FW_STATUS_PREFIXES/_fw_dedup_key/_is_pending_fw_id/gather_firmware :4986-5101`, `_make_section_runner :5645`, `_supplement_firmware_from_pcie_psu :6421`, `_collect_all_sections :6539-6610`, `_compute_final_status :6613`, `main() firmware_inventory_scope :9120-9122, :9290`), `redfish-gather/tasks/normalize_standard.yml` (`:13`, `:393-432`, `:486-500`, `:514`, `:588-594`, `:682`, `:701-735`), `common/tasks/normalize/*.yml`(bios 키 없음 — 실패 envelope 에 bios 부재 계약과 일치), `callback_plugins/json_only.py:78-96`(섹션 목록·빈값에 bios 없음), `adapters/redfish/hpe_csus_3200.yml` 전문, `tests/integration/emulator_harness.py:63-206`, `tests/redfish-probe/replay_full_mirror.py:281-360`, `tests/unit/test_redfish_bios_current.py` 전문, `tests/unit/test_full_mirror_dryrun.py:1-260, 986-1003, 1430-1450`, `tests/unit/test_firmware_category.py` 전문, `tests/unit/test_redfish_phase2_contracts.py` C6, `tests/unit/test_redfish_csus_single_server.py` A-9 · category 템플릿, `tests/integration/test_bios_real_capture_replay.py:1-60`, `tests/integration/test_request_budget.py`, `test_real_capture_replay.py`.
- 계약·문서: `schema/sections.yml` firmware, `schema/field_dictionary.yml` (`:33-40`, `:429-440`, `:1146-1185`, `:1292-1305`, `:1680-1690`, `:2493-2550`), `docs/contract/03-fields.md` (`:56-75`, `:134-170`, `:998-1120`), `docs/develop/05-field-mapping.md` firmware 행, `docs/ai/catalogs/EXTERNAL_CONTRACTS.md:11-15,55`, ADR-2026-10-19 A-9, `tests/evidence/2026-06-15-hpe-csus3200-mirror-audit.md`(CSUS-R9/R16), `tests/evidence/2026-10-19-csus-single-server-summary-audit.md`(A-9 행), `schema/baseline_v1/*.json` category 값(`grep -o '"category": "[a-z_]*"'`), 02 보고서 §1·§4·§6.
- 데이터(스크립트는 SCRATCH `w04_firmware_bios/{common,fw_raw_vs_tier1,bios_raw_vs_tier1,untouched_fw,detail_queries,other_items,misc_queries,bios_diff,quick_check,proposed_rule,coverage_gen}.py`, 저장소 밖): 18 label 의 `UpdateService`·`FirmwareInventory` 컬렉션(Members 수·count·nextLink·inline 키)과 멤버 전문(Id/Name/Version/Updateable/SoftwareId/Status/ReleaseDate/RelatedItem/Oem) → Tier 1 `data.firmware` 와 id 기준 자동 대조(누락·추가·필드 불일치 0, Dell dedup 쌍 19 전수 확인), category Jinja 규칙의 Python 복제로 18 label 재분류(복제 ≡ Tier 1, 불일치 0) 및 `other` 전수 열거; `SoftwareInventory`(HPE 0 멤버), HPE `UpdateService/{UpdateTaskQueue,InstallSets,ComponentRepository,RunningSoftwareInventory,MaintenanceWindows}`, `/fwrepo/*` raw, Lenovo `UpdateService.Oem.Lenovo`, CSUS `UpdateService`·`Managers/RMC`·`Chassis/r001u01`·`Partition0` OEM; 18 label `Systems/<첫 멤버>.Bios.@odata.id` → Bios 본문(`@odata.type`, `AttributeRegistry`, `@Redfish.Settings`, `Links`, `Oem`, `Actions`, Attributes 자료형 분포) ↔ Tier 1 `data.bios` 키·값·타입·정렬 전수 비교(차이 0, no_log 마스킹 흔적 0), `Bios/Settings`·`Bios/Pending`·`SD`·`Oem` 존재와 current 와의 diff, HT 속성·pending 값, 같은 모델 간 속성 키 차이의 접두 집계; `hardware.bios_version/bios_date`·`bmc.firmware_version` ↔ `System.BiosVersion`·OEM 날짜·`Managers/*.FirmwareVersion`·firmware[] bios/bmc 항목; `PCIeDevices/*.FirmwareVersion`·`Drives/*.Revision`·`StorageControllers[].FirmwareVersion`·`NetworkAdapters.Controllers[].FirmwarePackageVersion`·PSU `FirmwareVersion/Version` 이 firmware[] 와 다른 섹션(`storage.controllers`, `network.adapters`, `storage.hbas`, `power.power_supplies`)에 표현되는지; `EVID/inventory/<server>.jsonl` 의 UpdateService/Bios/SecureBoot/BootOptions 분류 집계; `server_access.jsonl` 의 UpdateService·Bios 요청(경로·상태·인증) 18 label; Tier 2 `plain`/`adapter` 모듈 `data.firmware` id 목록 ↔ Tier 1.
- 테스트 실행(이 worktree, 읽기 전용·캐시 비활성 `-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`): 쌍 실행 8 failed/71 passed, 단독 78 passed(§4 04-test-001).
- 문제 없음도 확인한 것: `sections.firmware` 18/18 success, 요청 경로·횟수·상태(FirmwareInventory 1 + 멤버 N + Bios 1, 전부 200 basic), Dell `Previous-` 11건 GET 0회, `N/A`/빈 Version 제외 0건 발동(해당 항목 없음), `SoftwareId "null"` 0건, 후행 `/` id 0건, 멤버 GET 실패 0건, CSUS 보충의 id 중복 0·notice 1건·Tier 2 adapter 모드와 동일, BIOS 키 순서·자료형(`str/int/bool/null`)·개수 보존 18/18, Bios 하위 리소스 미요청 18/18, DL380 소문자 링크 그대로 요청, BIOS 오류·notice 0건, HPE `bios_date` MM/DD/YYYY → ISO 와 System ROM 괄호 날짜 일치, Dell `bios_date` == FirmwareInventory BIOS `ReleaseDate`, HPE/Dell `bmc.firmware_version` == firmware[] bmc 항목, `network.adapters[].firmware_version`/`storage.controllers[].controller_firmware`/`power_supplies[].firmware_version` 이 firmware[] 와 값 일치(다른 영역 교차).
- 수치 측정 명령: `grep -c '"category"' schema/baseline_v1/*.json`, `grep -rln mock2 tests/`, `python -I -X utf8 <SCRATCH>/w04_firmware_bios/*.py`(Mock 추출본·Tier 1·Tier 2 경로는 `common.py` 상수).
- 비밀정보 점검: 보고서·coverage JSON 에 IP·호스트명·계정·시리얼·MAC·WWPN 을 싣지 않았다(펌웨어 ID·버전·BIOS 속성 이름·슬롯 라벨만). coverage JSON 의 IPv4 패턴 검사 hit 는 Dell iDRAC 버전 문자열(`7.00.00.184`) 1건뿐.
