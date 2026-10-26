# 01. system / hardware / multi_node — 2차 Redfish Mock 11대 분석 (2026-10-26)

모델: claude-fable-5-1 (Claude Fable 5.1) / worktree: `C:/github/ClovirONE/clovirone-server-gathering/.claude/worktrees/agent-a5f3005b27e1705cf` / 브랜치: `worktree-agent-a5f3005b27e1705cf` (`git rev-parse --show-toplevel` · `git branch --show-current`, 시작 시 HEAD `e8b5ae9b`)

담당 필드: `data.hardware.*`(16개) · `data.system.{hostname,fqdn}` · `data.multi_node.*` · `diagnosis.details.{multi_node_layout, rmc_activation_check, systems_uri, product, adapter_first_pass, adapter_candidate, hostname_source}` · 최상위 `hostname` · `vendor` · `correlation.{serial_number, system_uuid, bmc_ip}` · `meta.adapter_id`.
근거의 1순위는 Tier 1 envelope(`baseline/tier1/<label>/gather_output.json`)과 Mock 원본(`C:/github/ClovirONE/mock2-audit-20261026/extract/<server>/redfish/v1/...`, 1차는 `C:/github/서버mock데이터/1차/...`)이다. 기계 판독용 표는 같은 디렉터리의 `01-system-hardware-multi-node.coverage.json`(18 label × 필드, `_area_system`/`_area_hardware`/`_area_multi_node` 종합 칸 포함)이다.

## 1. 요약

- 이슈 수: **HIGH 1 / MED 2 / LOW 8** (총 11건, §4). 그 밖의 관찰(계약 밖·검증 불가)은 §5 · §9.
- 11대 상태 한 줄: **hardware 식별 필드(vendor/model/serial/uuid/sku/bios_version/power_state/system_type/part_number/asset_tag/last_reset_time/boot_progress/tpm)는 11대 전부 raw 1:1 일치** — CSUS 3대는 A1/A1b/A-7 폴백(Chassis.Manufacturer · ServiceRoot.Product · Chassis.PartNumber)과 `-000` 접미사 제거가 설계대로 동작했고, DL380 4대·SR650 4대는 System 값 그대로다. hostname 체인(System.HostName 첫 라벨 → BMC NetworkProtocol 이름)도 11대 전부 계약대로다.
- 가장 큰 결함은 **Lenovo SR650 V4 4대(+1차 1대)의 로그인 후 adapter 재선택이 `redfish_lenovo_xcc3` → `redfish_lenovo_bmc`(priority 10 범용)로 강등**되는 것이다(01-adapter-001, HIGH). 원인은 데이터가 아니라 공통 실격 규칙이다: 재선택 facts 의 `firmware` 는 `Manager.FirmwareVersion`("IHX438R 2.97 20260910")인데 Lenovo 세 adapter 의 `firmware_patterns` 가 기대하는 토큰("XCC3"/"XCC"/"IMM2")은 거기에 없고 `Manager.Model`("Lenovo XClarity Controller 3")에만 있다. `adapter_common.adapter_match_score` 는 model 이 일치해도 firmware 가 알려져 있고 불일치면 -9999 로 실격시키므로, 패턴이 없는 범용 adapter 만 남는다. 같은 규칙이 Dell R740 에서는 "정상" 으로 보이는 이유는 Dell 펌웨어 문자열("7.00.00.184")이 `dell_idrac9` 패턴(`^[3-7]\.`)과 맞기 때문이다 — 같은 메커니즘의 다른 결과이지 다른 버그가 아니다. 제안 규칙(B: model_patterns 가 일치한 adapter 는 firmware 불일치를 보너스 상실로만 취급)을 18개 label 의 실제 인증 후 facts 와 기존 단위시험 매트릭스 22건에 시뮬레이션한 결과 Lenovo 5건만 `redfish_lenovo_xcc3` 로 바뀌고 나머지는 전부 그대로였다(§4 · scratchpad `w01/sim_reselect.py`).
- MED 2건: (1) `hardware.health` 의 출처가 `Status.Health` 인데 사전·계약 문서는 "BMC rollup" 이라고 적는다 — DL380 Gen12 2대는 `Status.Health=Warning` 이면서 OEM `AggregateServerHealth=Critical`(PSU), 1차 SR650 은 `Health=Warning`/`HealthRollup=OK` 로 둘이 갈린다(01-hardware-002). (2) `schema/baseline_v1/hpe_csus_3200_baseline.json` 과 `docs/contract/03-fields.md` §9 예시가 아직 mock(3 partition/4 manager/PCIe fabric) 인데 실 CSUS 7대(1차 4 + 2차 3)는 전부 1/1/3 · fabric_type null · endpoint 0 이다(01-multi_node-003).
- multi_node(CSUS 3대 + 1차 4대): 구조(partition 1 · manager 1 · chassis 3 · resource block 1 · fabric 1) raw 일치. 미러에 없는 고정 경로 11개(요청 14건)는 `gather_chassis_multi` 가 Chassis 본문의 navigation property 를 보지 않고 `/Power`·`/Thermal`·`/EnvironmentMetrics` 를 먼저 찔러 보는 구조에서 나온다(01-multi_node-006, LOW — 실장비 응답은 검증 불가).
- ADR 재검증: ADR-2026-10-15(CSUS hostname = RMC 이름)는 2차 3대에서 RMC NetworkProtocol 이름 == Partition0.HostName 이라 모순 없음. 다만 1차 01/02 처럼 RMC 공장 기본명(`RMC7CA62A413692`)이 `hostname_source=system` 으로 나가는 의미 불일치(ADR D2 가 인정)는 그대로다(01-system-009, LOW). ADR-2026-10-19(`-NNN` 제거 · part_number 섀시 폴백)는 2차 3대에서 그대로 성립한다.

## 2. 필드별 수집 흐름 (진입 → 요청 경로/폴백 → 파서 → 정규화 → 출력)

| 출력 필드 | 모듈 진입/요청 (`redfish-gather/library/redfish_gather.py`) | 파서 | 정규화 (`redfish-gather/tasks/normalize_standard.yml` · `common/tasks/normalize/*`) | 비고 |
|---|---|---|---|---|
| `hardware.vendor` | `detect_vendor`(:1954) → `_resolve_first_member_uri(Systems)`(:1748) → `gather_system`(:2552) GET `{system_uri}` + `{Links.Chassis[0]}`(:2574-2580) | `Manufacturer` → 없으면 Chassis.Manufacturer(A1, :2673-2676) | `_rf_d_system.manufacturer`(:574) | CSUS 는 Partition0 에 Manufacturer 없음 → Chassis r001u01 "HPE" |
| `hardware.model` | 같음 | `Model` → 없으면 `product_hint`(ServiceRoot.Product, A1b :2662-2665) → Chassis.Model(:2677-2680) | :575 | CSUS "Compute Scale-up Server 3200" (Chassis 값은 "…, 4S XNC Base Chassis") |
| `hardware.serial` | `gather_system` `_ne('SerialNumber')`(:2621); Dell 은 `main()` 이 `_SERIAL_RESOLVERS['dell']`(:2237, :9230-9261)로 ServiceRoot.Oem.Dell.ServiceTag 로 덮어씀 | `_strip_or_none` | `normalize_os_serial(manufacturer, model)`(:582, `filter_plugins/serial_normalizer.py:178`) — HPE alias + CSUS/Superdome 모델 + `-NNN` 세 조건에서만 접미사 제거 | CSUS `SGHD4MGNLH-000` → `SGHD4MGNLH` (= Chassis r001u01 · RackGroup · Manager.SerialNumber) |
| `hardware.uuid` | `_ne('UUID')`(:2623) | — | `normalize_uuid`(소문자 8-4-4-4-12, `filter_plugins/identity_normalizer.py:139`) + adapter `vendor_notes.uuid_byte_order==smbios_raw` 일 때만 `uuid_byteswap`(:585-589) | HPE/Lenovo adapter 는 선언 없음 → 스왑 없음; OS 캡처 부재로 대조 불가(§9) |
| `hardware.sku` / `part_number` | `_ne('SKU')`/`_ne('PartNumber')`(:2622,:2633) → 둘 다 None 이면 Chassis `SKU`/`PartNumber`(A-7, :2684-2688) | — | :590, :598 | CSUS part_number ← Chassis "R9N70A"; DL380 은 System/Chassis 모두 PartNumber 없음 → null |
| `hardware.bios_version` / `bios_date` | `_ne('BiosVersion')`(:2630); bios_date 는 표준 키 없음 → OEM extractor 의 `_bios_date`(HPE `Oem.Hpe.Bios.Current.Date` :2129, Dell `DellSystem.BIOSReleaseDate` :2159) 를 `_hoist_oem_extras`(:2297)가 ISO 로 끌어올림 | `_normalize_bios_date`(:2442) | :591, :597 (`oem.bios_release_date` Dell 레거시 폴백) | Lenovo/CSUS 는 OEM 날짜 없음 → null |
| `hardware.power_state` / `health` / `system_type` / `asset_tag` / `last_reset_time` / `boot_progress` / `tpm` | `gather_system` :2619-2645 (`PowerState`, `Status.Health`, `SystemType`, `AssetTag`(''→null), `LastResetTime`, `BootProgress.LastState`, `TrustedModules[0]{InterfaceType,FirmwareVersion,Status.State}`) | — | :598-605 passthrough | health 는 `Status.Health` 만 (HealthRollup 미참조 — §4 01-hardware-002) |
| `hardware.oem` | `_OEM_EXTRACTORS[vendor]`(:2486) — HPE `_extract_oem_hpe`(:2093, `@odata.type` 이 `#HpeH3Npar` 면 CSUS 키 7개, 아니면 iLO 키), Lenovo `_extract_oem_lenovo`(:2242, System+Chassis Oem.Lenovo), Dell `_extract_oem_dell`(:2147) | `_hoist_oem_extras` 가 `_*` 키 제거 | :606 passthrough | Lenovo 9키 중 7키가 전 캡처 null(§4 01-hardware-005) |
| `system.hostname` / `system.fqdn` | `gather_system` `HostName`(''→None, :2585-2587); `gather_bmc`(:2801) `Manager.NetworkProtocol` FQDN→HostName(:2938-2950) → `bmc.network_hostname` | — | "system hostname source"(:526-537): adapter `vendor_notes.hostname_priority==bmc_first` 면 `bmc.network_hostname` 우선(CSUS), 아니면 System.HostName; "system hostname / fqdn"(:539-553): 첫 라벨 / 도메인 있을 때만 전체 | `sections.system` 은 `_sections_supported_fragment`(:702-703) 에 없어 항상 `not_supported` |
| 최상위 `hostname` / `hostname_source` | — | — | `common/tasks/normalize/build_output.yml:95-107`: `system.hostname → system.fqdn → bmc.network_hostname → null`, source = system/bmc/none | CSUS 는 system.hostname 에 RMC 이름이 들어가 source=system |
| 최상위 `vendor` | `detect_vendor` → `_detect_vendor_from_service_root`(:1661: Oem 키 → Vendor → Product → Name) → canonical | — | `collect_standard.yml:167-174`(`_rf_vendor`) → `site.yml:331-334` `adapter_output_display[adapter_id]` → `vendor_output_display[canonical]` → canonical | hp / hpCsus / lenovo / dell (ADR-2026-06-04) |
| `correlation.*` | — | — | `build_correlation.yml:18-42`: serial_number=hardware.serial, system_uuid=normalize_uuid(hardware.uuid), bmc_ip=`bmc.ip`(Manager EthernetInterfaces 중 IPv4 가 있는 첫 NIC, `gather_bmc:2863-2890`), host_ip=대상 IP | 재생에서는 host_ip=127.0.0.1 (README 한계 #9) |
| `meta.adapter_id` / `diagnosis.details.adapter_*` | 1차: `site.yml:110-116` `adapter_loader(facts=_rf_probe_facts)` — `detect_vendor.yml:73-91` 가 무인증 `mode=detect` 결과(`data.system.model`/`data.bmc.firmware_version`, 401 이면 빈값)와 `_extract_probe_facts`(:2032, HPE 만 ServiceRoot.Product/Oem.Hpe.Manager) 로 조립. 2차: `tasks/reselect_adapter.yml:39-70` 가 `_rf_raw_collect.data.system.model` + `data.bmc.firmware_version` 로 `adapter_loader` 재호출 | `lookup_plugins/adapter_loader.py:126-171` + `module_utils/adapter_common.py:139-214(adapter_matches), 250-334(adapter_match_score), 337-355(adapter_score)` | `build_meta.yml:65`, `site.yml:348-352`(first_pass 는 바뀐 경우만) | §4 01-adapter-001 |
| `diagnosis.details.product` / `systems_uri` | precheck `common/library/precheck_bundle.py:665-669` (ServiceRoot.Product, Systems.@odata.id 원문) | — | passthrough | DL380 은 `/redfish/v1/Systems/`(후행 슬래시) — 장비 표기 그대로 |
| `multi_node.*` | `main()`:9271-9279 → `_collect_multi_node_topology`(:6337, `manager_layout` 있을 때만) → `gather_systems_multi`(:5993, 전 Systems 멤버 × gather_system/processors/memory/storage/network/boot) · `gather_managers_multi`(:5733, 전 Managers × gather_bmc + `gather_manager_logs`:5687) · `gather_chassis_multi`(:6074, 전 Chassis × GET + `gather_power`:5305 + `gather_thermal`:5385 + `_extract_chassis_oem`:6051) · `gather_composition_service`(:6147) · `gather_fabrics`(:6279) | 각 함수 | `normalize_standard.yml:697` passthrough (`_rf_raw_collect.multi_node`) | `diagnosis.details.multi_node_layout`/`rmc_activation_check` 는 `site.yml:357-366` |

## 3. 11대 × 필드 검증 상태 표

상태: PASS = Tier 1 출력이 계약상 원천 raw 값과 일치 / ISSUE = 결함 또는 가용 데이터 미반영(이슈 ID) / NOT_APPLICABLE = 장비가 원천 자체를 노출하지 않음(자동 PASS 아님) / MOCK_LIMITATION = 재생·캡처 한계로 확정 불가. 전 필드·근거 문자열은 `01-system-hardware-multi-node.coverage.json` 에 있다(`python -c "import json;d=json.load(open('…coverage.json'));print(len(d))"` → 18 label).

### 3.1 system 영역

| 서버 | `hostname` (source) | `system.hostname` / `system.fqdn` | `sections.system` | `_area_system` |
|---|---|---|---|---|
| csus3200_01 | PASS `yicdspdb01` (system; RMC NP 이름 == Partition0.HostName) | PASS `yicdspdb01` / null | ISSUE 01-system-008 | ISSUE(LOW: 01-system-008 · 01-system-009) |
| csus3200_02 | PASS `yicgsfabap01` (system) | PASS / null | ISSUE 01-system-008 | ISSUE(LOW) |
| csus3200_03 | PASS `yicgsfabdb01` (system) | PASS / null | ISSUE 01-system-008 | ISSUE(LOW) |
| dl380_gen12_01 | PASS `yicesxmgmt05` (system; System.HostName `yicesxmgmt05.yimad.net`) | PASS `yicesxmgmt05` / `yicesxmgmt05.yimad.net` | ISSUE 01-system-008 | ISSUE(LOW) |
| dl380_gen12_02 | PASS `yicad04` (bmc; System.HostName "" → iLO NP) | PASS null / null | ISSUE 01-system-008 | ISSUE(LOW) |
| dl380_gen12_03 | PASS `yicossemul03` (bmc) | PASS null / null | ISSUE 01-system-008 | ISSUE(LOW) |
| dl380_gen12_04 | PASS `yicinposdb02` (bmc) | PASS null / null | ISSUE 01-system-008 | ISSUE(LOW) |
| sr650_v4_01 | PASS `yicad01` (bmc; System.HostName null → XCC NP) | PASS null / null | ISSUE 01-system-008 | ISSUE(LOW) |
| sr650_v4_02 | PASS `yicbringup01` (bmc) | PASS null / null | ISSUE 01-system-008 | ISSUE(LOW) |
| sr650_v4_03 | PASS `yicinfesx001` (bmc) | PASS null / null | ISSUE 01-system-008 | ISSUE(LOW) |
| sr650_v4_04 | PASS `yichtwinap09` (bmc) | PASS null / null | ISSUE 01-system-008 | ISSUE(LOW) |
| r1_DELL_R740_01 | PASS `DELL01` (system) | PASS `DELL01` / null | ISSUE 01-system-008 | ISSUE(LOW) |
| r1_HPE_CSUS3200_01/02 | PASS `RMC7CA62A413692` / `RMC7CA62A418172` (system — RMC 공장명, Partition0.HostName null) | PASS 같은 값 / null | ISSUE 01-system-008 | ISSUE(LOW: 01-system-009) |
| r1_HPE_CSUS3200_03/04 | PASS `M10MESDB11-RMC` / `M10APCDB11-RMC` (system; Partition0.HostName `m10mesdb11`/`m10apcdb11`) | PASS 같은 값 / null | ISSUE 01-system-008 | ISSUE(LOW) |
| r1_HPE_DL380_01 | PASS `ILOSGHD3KHHRP` (bmc — iLO 공장명) | PASS null / null | ISSUE 01-system-008 | ISSUE(LOW) |
| r1_Lenovo_SR650_01 | PASS `XCC-7DGD-J902E57T` (bmc — XCC 공장명) | PASS null / null | ISSUE 01-system-008 | ISSUE(LOW) |

`hostname_source` 칸은 CSUS 7대만 ISSUE(01-system-009), 나머지 PASS.

### 3.2 hardware 영역 (16 필드 + uuid 바이트 순서)

| 서버 | vendor/model/serial/uuid/sku/bios_version/power_state/system_type/asset_tag/part_number/last_reset_time/boot_progress | bios_date | health | tpm | oem | uuid 바이트 순서(OS 대조) | `_area_hardware` |
|---|---|---|---|---|---|---|---|
| csus3200_01..03 | PASS ×12 (vendor/model/part_number 는 Chassis·ServiceRoot 폴백, serial 접미사 제거) | NOT_APPLICABLE (OEM 날짜·FirmwareInventory ReleaseDate 모두 없음) | PASS OK (HealthRollup OK) | PASS TPM2_0/0x00010303/Enabled | PASS (#HpeH3Npar 7키, HostOS RHEL 9.6) | MOCK_LIMITATION | PASS |
| dl380_gen12_01 | PASS ×12 (part_number null = System/Chassis 모두 없음) | PASS 2026-06-26 (Oem.Hpe.Bios.Current.Date) | ISSUE 01-hardware-002 (Status.Health Warning, AHS Critical) | PASS TPM2_0/9.256/Enabled | PASS (iLO 키, aggregate_server_health Critical, power Critical) | MOCK_LIMITATION | ISSUE(MED 01-hardware-002) |
| dl380_gen12_02 | PASS ×12 | PASS 2026-08-20 | ISSUE 01-hardware-002 (Warning vs AHS Critical) | PASS | PASS | MOCK_LIMITATION | ISSUE(MED) |
| dl380_gen12_03 | PASS ×12 (power_state Off, boot_progress "None") | PASS 2026-06-26 | PASS Warning (HealthRollup Warning, AHS Warning) | PASS | PASS (post_state PowerOff, subsystem 일부 null) | MOCK_LIMITATION | PASS |
| dl380_gen12_04 | PASS ×12 | PASS 2026-06-26 | ISSUE 01-hardware-002 | PASS | PASS | MOCK_LIMITATION | ISSUE(MED) |
| sr650_v4_01..04 | PASS ×12 | ISSUE 01-hardware-004 (FirmwareInventory UEFI.ReleaseDate 2026-05-11 미활용) | PASS Critical (HealthRollup 없음) | NOT_APPLICABLE (TrustedModules null; Bios Attributes 에만 TPM) | ISSUE 01-hardware-005 (7키 null) | MOCK_LIMITATION | ISSUE(LOW) |
| r1_DELL_R740_01 | PASS ×12 (serial = ServiceTag J0KV603, sku 동일) | PASS 2026-01-28 | PASS OK | PASS (null/"Unknown"/Disabled — raw 그대로) | PASS (Dell 11키) | MOCK_LIMITATION | PASS |
| r1_HPE_CSUS3200_01..04 | PASS ×12 | NOT_APPLICABLE | PASS OK | PASS (01/02 StandbyOffline, 03/04 Enabled) | PASS (01/02 는 DCD/HostOS null — raw 도 없음) | MOCK_LIMITATION | PASS |
| r1_HPE_DL380_01 | PASS ×12 | PASS 2025-08-08 | PASS OK | PASS | PASS | MOCK_LIMITATION | PASS |
| r1_Lenovo_SR650_01 | PASS ×12 | ISSUE 01-hardware-004 (UEFI.ReleaseDate 2025-03-15) | ISSUE 01-hardware-002 (Health Warning / HealthRollup OK) | NOT_APPLICABLE | ISSUE 01-hardware-005 | MOCK_LIMITATION | ISSUE |

### 3.3 multi_node 영역 · 최상위 · meta/diagnosis

| 서버 | multi_node | `diagnosis.multi_node_layout` / `rmc_activation_check` | `vendor` | `correlation.{serial_number,system_uuid,bmc_ip}` | `meta.adapter_id` / `adapter_first_pass` / `adapter_candidate` | `diagnosis.systems_uri` / `product` |
|---|---|---|---|---|---|---|
| csus3200_01..03 | enabled/layout PASS · summary PASS(1/1/3/1/1) · partitions PASS · managers PASS(RMC primary, LogServices 7) · chassis ISSUE 01-multi_node-006(고정 경로 404 11개, 값은 raw 일치) · composition ISSUE 01-multi_node-007(count 0) · fabrics PASS(raw 충실) · `_area` ISSUE(LOW ×2 + MED 01-multi_node-003 baseline) | PASS rmc_primary / true | PASS hpCsus | PASS / PASS / PASS (RMC EthernetInterfaces/1) | PASS redfish_hpe_csus_3200 / null / 동일 | PASS `/redfish/v1/Systems` / `Compute Scale-up Server 3200` |
| dl380_gen12_01..04 | NOT_APPLICABLE — `hpe_ilo7.yml` 에 `manager_layout` 없음, Systems 1 · Managers 1 (Chassis 2개째 `DE00B000` 은 System 이 링크하지 않는 스토리지 인클로저) → null 정상 | PASS null / null | PASS hp | PASS / PASS / PASS (EthernetInterfaces/1) | PASS redfish_hpe_ilo7 / null / 동일 | PASS `/redfish/v1/Systems/` / `HPE ProLiant Compute DL380 Gen12` |
| sr650_v4_01..04 | NOT_APPLICABLE — `lenovo_xcc3.yml`·`lenovo_bmc.yml` 모두 `manager_layout` 없음, Systems 1 · Managers 1 → null 정상 | PASS null / null | PASS lenovo | PASS / PASS / PASS (EthernetInterfaces/NIC) | **ISSUE 01-adapter-001** redfish_lenovo_bmc / redfish_lenovo_xcc3 / redfish_lenovo_bmc | PASS `/redfish/v1/Systems` / null (ServiceRoot.Product 없음) |
| r1_DELL_R740_01 | NOT_APPLICABLE | PASS | PASS dell | PASS (bmc_ip = iDRAC NIC.1) | PASS redfish_dell_idrac9 / redfish_dell_idrac10 / redfish_dell_idrac9 (재선택이 바로잡음 — 설계대로) | PASS / `Integrated Dell Remote Access Controller` |
| r1_HPE_CSUS3200_01..04 | csus3200 과 같음 | PASS | PASS hpCsus | PASS | PASS | PASS |
| r1_HPE_DL380_01 | NOT_APPLICABLE | PASS | PASS hp | PASS | PASS redfish_hpe_ilo7 | PASS |
| r1_Lenovo_SR650_01 | NOT_APPLICABLE | PASS | PASS lenovo | PASS | **ISSUE 01-adapter-001** | PASS / null |

## 4. 이슈 목록

### 01-adapter-001 [HIGH] Lenovo XCC3 로그인 후 adapter 재선택이 범용 `redfish_lenovo_bmc` 로 강등
- 대상 서버: sr650_v4_01 · 02 · 03 · 04, r1_Lenovo_SR650_01 (Lenovo 5대 전부). Dell R740(1차)은 같은 규칙의 **정상** 사례(아래).
- 필드: `meta.adapter_id`, `diagnosis.details.adapter_candidate`, `diagnosis.details.adapter_first_pass`.
- 근거(Mock): `extract/sr650_v4_01/redfish/v1/Managers/1/index.json` → `FirmwareVersion: "IHX438R 2.97 20260910"`, `Model: "Lenovo XClarity Controller 3"`; `Systems/1/index.json` → `Model: "ThinkSystem SR650 V4"`; 1차 `Managers/1` → `"IHX414J 1.22 20250402"` / `"Lenovo Xclarity Controller 3"`. ServiceRoot(`redfish/v1/index.json`)에는 `Product`/`Oem` 이 없고 `Vendor: Lenovo`, `RedfishVersion 1.22.0`(1차 1.17.0), `UUID` 뿐이다.
- 근거(Tier 1): `tier1/sr650_v4_01/gather_output.json` `meta.adapter_id = "redfish_lenovo_bmc"`, `diagnosis.details.adapter_first_pass = "redfish_lenovo_xcc3"`; `adapter_selection_2차.json` 1차 점수 `redfish_lenovo_xcc3 120520`(facts model/firmware 빈값 → priority 결정).
- 코드: `redfish-gather/tasks/reselect_adapter.yml:39-48`(facts = `data.system.model` + `data.bmc.firmware_version`), `module_utils/adapter_common.py:183-189`(`adapter_matches`: firmware 가 알려져 있고 불일치면 False) · `:291-300`(`adapter_match_score`: 같은 조건 -9999), `adapters/redfish/lenovo_xcc3.yml` `firmware_patterns: ["XCC\\s*3\\b"]`, `lenovo_xcc.yml` `["XCC","^AFBT","^TAOT","^USX"]`, `lenovo_imm2.yml` `["IMM2"]`, `lenovo_bmc.yml`(패턴 없음, priority 10).
- 실제 출력 / 기대 출력: `redfish_lenovo_bmc` / `redfish_lenovo_xcc3`. 점수 재현(현행 규칙, `w01/sim_reselect.py`): xcc3·xcc·imm2 = -9999, lenovo_bmc = 10120, generic = -400.
- 원인(확정): 두 겹. (a) 재선택 facts 의 `firmware` 는 `Manager.FirmwareVersion` 하나인데, XCC3 의 그 값은 빌드 ID("IHX…") + 버전 + 날짜라 Lenovo adapter 가 기대하는 세대 토큰이 없다 — 세대 토큰은 `Manager.Model`("XClarity Controller 3")에 있다. (b) 공통 실격 규칙이 "model 일치 + firmware 불일치" 를 실격으로 본다. 그 결과 model 로 확정된 정답 adapter 가 지워지고 패턴 없는 fallback 만 남는다. `test_adapter_generation_tokens.py:61` 은 실재하지 않는 펌웨어 문자열 `"XCC3 1.20"` 으로 통과하고 있어 시험이 이 결함을 가리지 못했다.
- Dell R740 판정: 1차 선택 `redfish_dell_idrac10`(priority 120 독식)은 Lenovo 와 같은 "빈 facts 는 중립" 규칙의 산물이고, 재선택에서 Dell 펌웨어 "7.00.00.184" 가 `dell_idrac9` `^[3-7]\.` 과 맞아 idrac10(model 불일치 실격)을 제치고 정답이 된다. 즉 **같은 규칙의 다른 증상이 아니라 같은 규칙이 Dell 에서는 성립하는 것**이다 — Lenovo 는 펌웨어 문자열 형식이 패턴과 맞지 않아 같은 규칙이 fallback 으로 떨어진다.
- 영향 범위: (1) 소비자가 보는 `meta.adapter_id`(must)와 진단 2필드가 틀리고 `adapter_first_pass` 가 정답을 "옛 값" 으로 기록한다(의미 역전). (2) `normalize_standard.yml:529,585,624` 는 **재선택된** adapter 의 `vendor_notes`(hostname_priority/uuid_byte_order/processor_summary_logical_count)를 읽으므로, 앞으로 `lenovo_xcc3.yml` 에 어떤 vendor_notes 를 두어도 조용히 무시된다(잠복 기능 결함; 오늘은 두 Lenovo adapter 모두 코드가 읽는 키가 없어 데이터 영향 0). (3) 계정 복구 경로의 `resolve_account_family`(:7611-7640)는 `'xcc3' in hint` 로 XCC3 Family 를 가른다 — 복구는 표준 로그인 실패 시 재선택 **전**에 돌므로 실무 영향은 없지만, 재선택이 두 번 호출되는 순서(`site.yml:152, 229`)를 바꾸면 바로 드러난다. (4) 데이터(hardware/system/multi_node 값)는 두 adapter 의 `sections_supported` 가 같아 변화 없음 — Tier 1 11대 데이터 PASS 와 모순되지 않는다.
- 수정 제안(공통 로직, 우선): `adapter_common.adapter_match_score`/`adapter_matches` 에서 **model_patterns 가 있고 model fact 가 알려져 있으며 일치한 adapter 는 firmware 불일치를 실격이 아니라 +25 보너스 상실로만** 취급한다(규칙 B). model_patterns 가 없거나 model 미상/불일치면 현행 그대로. 점수식(`priority×1000 + specificity×10 + match`)은 바뀌지 않는다. 시뮬레이션(scratchpad `w01/sim_reselect.py`, 제품 코드 무수정): 18 label 인증 후 facts → Lenovo 5건만 `redfish_lenovo_xcc3`(120545 > lenovo_xcc 100545 > lenovo_bmc 10120)로 바뀌고 CSUS 7·DL380 5·Dell 1 은 동일; `test_adapter_selection_t01`·`test_adapter_generation_tokens`·`test_redfish_adapter_reselect` 매트릭스 22건 중 B 가 기대와 다른 건 0건(현행도 틀리는 가상 사례 1건 — 아래 01-adapter-011). 보조 제안(데이터, Additive): 실측 문자열에 맞춘 `lenovo_xcc3.yml` 패턴 보강은 가능하지만 세대 토큰이 FirmwareVersion 에 없어 빌드 ID 접두("^IHX")에 기대야 한다 — SR650 V4 2종 펌웨어에서만 확인된 값이라 추정이며, 규칙 B 없이는 다른 V4 모델에서 재발한다. 재선택 facts 에 `bmc.model` 을 덧붙이는 안은 Dell(`^[3-7]\.` 앞 고정 앵커)·HPE(`^\d+\.\d+\.\d+`) 패턴 때문에 반드시 **firmware 뒤에** 이어 붙여야 하고 xcc3 패턴도 "XClarity Controller 3" 로 바꿔야 하므로 B 보다 변경 면적이 크다.
- 회귀 테스트 제안: (1) 18 label 의 실제 인증 후 facts(`vendor, data.hardware.model, data.bmc.firmware_version`)를 파라미터로 한 선택 시험 — 특히 `("lenovo","ThinkSystem SR650 V4","IHX438R 2.97 20260910")`, `("lenovo","ThinkSystem SR650 V4","IHX414J 1.22 20250402")` → `redfish_lenovo_xcc3`; (2) `test_redfish_hostname_policy_replay.py::_select_adapter` 가 이미 재선택을 재현하므로 선택된 adapter_id 를 단언에 추가; (3) 불변식: 최종 adapter 가 `priority <= 10` 인데 같은 vendor 에 model_patterns 일치 adapter 가 있으면 실패.
- ADR 영향: 직접 수정 대상 ADR 없음. CLAUDE.md §5 "Adapter 선택 로직 변경 시 기존 선택 결과 전체 Regression" 적용. `docs/ai/catalogs/VENDOR_ADAPTERS.md:72,212` 와 `lenovo_xcc3.yml` "Tested against" 주석은 1차 선택만 검증한 것을 "사이트 검증 PASS" 로 적고 있어 정정 필요(01-adapter-011).
- 데이터 확실성: 확정 (Tier 1 5/5 재현, 점수 재계산 일치).

### 01-hardware-002 [MED] `hardware.health` 출처(`Status.Health`)와 사전·계약의 "BMC rollup" 설명 불일치 — iLO 7 에서 OEM 집계와 갈림
- 대상 서버: dl380_gen12_01 · 02 · 04 (Status.Health `Warning` / HealthRollup `Warning` / `Oem.Hpe.AggregateHealthStatus.AggregateServerHealth` `Critical`, PowerSupplies `Critical`), r1_Lenovo_SR650_01 (Health `Warning` / HealthRollup `OK`). 나머지 14대는 세 값이 일치하거나 HealthRollup 이 없다.
- 필드: `data.hardware.health` (`hardware.oem.aggregate_server_health` 와의 관계).
- 근거: `extract/dl380_gen12_01/redfish/v1/Systems/1/index.json` `Status: {Health: Warning, HealthRollup: Warning}`, `Oem.Hpe.AggregateHealthStatus.AggregateServerHealth: Critical`; Tier 1 `hardware.health = "Warning"`, `hardware.oem.aggregate_server_health = "Critical"`. 1차 `Lenovo_SR650/01/redfish/v1/Systems/1` `Status: {Health: Warning, HealthRollup: OK}`.
- 코드: `redfish_gather.py:2626` `'health': _safe(data, 'Status', 'Health')` (HealthRollup 폴백 없음 — 같은 함수의 memory_summary :2600-2602 · cpu_summary :2641-2642 는 Rollup 폴백 있음). 문서: `schema/field_dictionary.yml:337-357` "서버 하드웨어 전체 상태 (BMC rollup health)", `docs/contract/03-fields.md:469-487,986` "PSU 한 대만 fault 여도 hardware.health 가 Critical 로 올라간다".
- 실제 출력 / 기대 출력: Warning / (코드 계약으로는 Warning 이 맞고, 문서 계약으로는 rollup 값). DL380 Gen12 에서 PSU Critical 인데 `health=Warning` 이라 문서의 예시 문장이 iLO 7 에서는 성립하지 않는다.
- 원인(확정): 코드는 리소스 자체 health, 문서는 롤업을 서술. DMTF `Resource.Status` 에서 `Health` 는 "리소스 자체", `HealthRollup` 은 "하위 포함" 이다.
- 영향 범위: 소비자가 `hardware.health` 를 "장비 전체" 로 읽으면 PSU 장애(iLO 7 2대)를 Critical 이 아니라 Warning 으로 본다. 값 자체는 raw 충실이라 오류는 아니다.
- 수정 제안: (1) 문서 정정 — `hardware.health` = `ComputerSystem.Status.Health`(리소스 health), 장비 전체 롤업은 `Status.HealthRollup`(있을 때) 또는 벤더 OEM(`hardware.oem.aggregate_server_health`/Dell `current_rollup_status`)로 본다고 적는다. (2) Additive 폴백 — `Status.Health` 가 null 일 때만 `HealthRollup` 사용(기존 memory/cpu summary 와 같은 패턴; 18대 중 null 사례 없음이라 값 변화 0). 롤업을 우선하도록 바꾸는 것은 Lenovo 1차 사례(Warning→OK)처럼 값을 바꾸므로 사용자 결정 항목으로 둔다.
- 회귀 테스트 제안: DL380 Gen12 raw(System Status Warning/Warning, AHS Critical)로 `hardware.health == "Warning"` 과 `oem.aggregate_server_health == "Critical"` 동시 단언; Health null + HealthRollup 있는 합성 입력에서 폴백 단언.
- ADR 영향: 없음(문서 정정). 데이터 확실성: 확정.

### 01-multi_node-003 [MED] CSUS mock 기반 baseline·계약 예시가 실 7대와 다름 (ADR-2026-05-12 결정 6 의 교체 의무 미이행)
- 대상 서버: csus3200_01..03, r1_HPE_CSUS3200_01..04 (7/7 동일 구조).
- 필드: `data.multi_node.summary` · `fabrics[].fabric_type/endpoint_count` · `composition.resource_block_count` · `hostname` · `hardware.serial/sku/part_number`.
- 근거: `schema/baseline_v1/hpe_csus_3200_baseline.json` → summary `{partition 3, manager 4, chassis 3, resource_block 3}`, fabrics `fabric_type: "PCIe"`, endpoints 2, hostname `csus-p0`, serial `MOCK-CSUS-P0`, sku `P52345-B21`, `diagnosis.details.baseline_origin: "mock-derived"`; `docs/contract/03-fields.md:1236-1348` 예시(Partition0~2, PDHC0/Bay1.iLO5, Base/Expansion, PCIe). 실측 7대 Tier 1: summary `{1,1,3,1,1}`, `fabric_type null`, `endpoint_count 0`, switches `r001u01_HARP0/1`, sku null, part_number `R9N70A`.
- 코드/문서: `docs/ai/decisions/ADR-2026-05-12-csus-rmc-multi-node.md` 결정 6("C1 사이트 fixture 캡처 후 실측 baseline 으로 in-place 교체 의무"), `adapters/redfish/hpe_csus_3200.yml` 머리말 "baseline 실측 교체(Ansible 환경 필요) — NEXT_ACTIONS".
- 실제 / 기대: baseline 과 예시가 mock; 2026-06-15 이후 실 캡처 4대, 2026-10-26 추가 3대가 있으므로 교체 조건은 충족.
- 원인(확정): 실측 baseline 교체 작업 미수행. 영향: 회귀 기준선이 실장비와 다르고, 소비자 문서가 존재하지 않는 구조(PDHC/iLO manager, PCIe fabric, endpoint)를 안내한다.
- 수정 제안: 실 캡처(1차 01 또는 2차 01) 재생 envelope 으로 baseline in-place 교체 + §9 예시를 실 구조(1 partition/RMC 1/Chassis RackGroup·Rack1·r001u01/ResourceBlock r001u01/FlexGrid HARP ×2, fabric_type null)로 갱신. 스키마 변경 없음.
- 회귀 테스트 제안: baseline 의 `baseline_origin` 이 mock 이면 실 캡처가 있는 vendor 에 대해 경고/실패하는 검사.
- ADR 영향: ADR-2026-05-12 결정 6 이행 기록. 데이터 확실성: 확정.

### 01-hardware-004 [LOW] Lenovo XCC3 `bios_date` null — `UpdateService/FirmwareInventory/UEFI.ReleaseDate` 가 있음
- 대상: sr650_v4_01..04 (`2026-05-11T00:00:00Z`), r1_Lenovo_SR650_01 (`2025-03-15T00:00:00Z`). HPE 는 OEM 날짜가 이미 있고 FirmwareInventory `System ROM` ReleaseDate 는 자리표시자 `0000-01-01T00:00:00Z`; CSUS ComplexFW/Partition0_FW 는 ReleaseDate null; Dell 은 OEM 날짜 있음.
- 필드: `data.hardware.bios_date`. 코드: `gather_system:2631` (OEM hoist 전용), `gather_firmware:5003-5103`(ReleaseDate 를 담지 않음), `normalize_standard.yml:597`.
- 실제 / 기대: null / `2026-05-11`.
- 원인(확정): Lenovo OEM 에 BIOS 날짜가 없고 FirmwareInventory 의 날짜는 수집 항목이 아니다.
- 수정 제안(기존 필드, Additive, 요청 0): `gather_firmware` 가 멤버 상세의 `ReleaseDate` 를 내부 키(예: `_release_date`, `_network_meta` 처럼 normalize 전 제거)로 보존하고, `_collect_all_sections` 뒤(`_fill_adapter_models_from_firmware:768` 와 같은 자리)에서 `system.bios_date` 가 None 이면 category `bios`(normalize 의 분류 규칙과 같은 토큰: bios/uefi/system rom)인 항목의 ReleaseDate 를 `_normalize_bios_date` 로 넣는다 — 연도 `0000` 같은 자리표시자는 제외. envelope 키 추가 없음.
- 회귀: SR650 V4 재생에서 `bios_date == "2026-05-11"`, DL380 은 OEM 값 유지(`2026-06-26`), CSUS null 유지.
- ADR 영향 없음. 확실성: 확정(원천 존재), 매핑 적정성은 Lenovo 공식 문서 미확인(추정 — UEFI `20L-1.50` ↔ `BiosVersion IHE120L` 정합은 확인).

### 01-hardware-005 [LOW] Lenovo `hardware.oem` 9키 중 7키가 모든 Lenovo 캡처에서 null — 원천 키가 존재하지 않는 매핑
- 대상: sr650_v4_01..04, r1_Lenovo_SR650_01; 저장소 참조 캡처 `tests/reference/redfish/lenovo/10_50_11_232`(SR650 V2, XCC) 도 같다.
- 근거: Chassis.Oem.Lenovo 실제 키 = `BIOSVendor, BaseBoardManufacturer, FanSpeedBoost, FruPartNumber, LEDs(link), ProductName, SolutionServiceEnabled, SysEncloseSerialNum, SysEncloseVersion, SystemBoardSerialNumber, SystemEncloseManufacturer, SysvpdSettings(link)`; V2 참조는 `ProductName, FruPartNumber, SystemBoardSerialNumber`. 코드가 읽는 `FruSerialNumber, MachineType, MachineLevel, ProductId, SystemId, HealthSummary, LEDIndicators/IndicatorLED`(`_extract_oem_lenovo:2242-2268`)는 어느 캡처에도 없다.
- 실제 / 기대: `{product_name, system_status}` 만 값, 7키 null / 기존 키를 실재 원천으로 채움.
- 원인(추정): 구세대(IMM2/XCC1) 문서 기반 매핑이 XCC/XCC3 에 그대로 남음.
- 수정 제안(기존 키만, Additive): `machine_type` ← `System.SubModel`("7DGD"; V2 "7Z73" — Lenovo 는 SKU `7DGDCTO1WW` 가 MT(4) + 모델이라 SubModel = Machine Type, 추정이나 두 세대 캡처가 일치); `led_indicator` ← `System.IndicatorLED`("Off", 모듈이 이미 `led_state` 로 계산); `fru_serial` 은 `SystemBoardSerialNumber` 가 같은 뜻인지 Lenovo 문서로 확인 전까지 보류(추정). 나머지(`machine_level, product_id, system_id, health_summary`)는 원천 부재로 null 이 정직.
- 회귀: SR650 V4 재생에서 `oem.machine_type == "7DGD"`, `oem.led_indicator == "Off"`.
- ADR 영향 없음. 확실성: 원천 부재는 확정, 대체 매핑은 추정.

### 01-multi_node-006 [LOW] CSUS 고정 경로 404 요청 11개(14건) — Chassis navigation property 를 보지 않는 Power/Thermal 탐색
- 대상: csus3200_01..03, r1_HPE_CSUS3200_01..04 (7/7 동일: `server_access.jsonl` 404 라인 14, distinct 11 — `python` 집계: r001u01 `Power`·`Thermal`·`EnvironmentMetrics` 각 2회(top-level + multi_node chassis 순회; 404 는 `_get` 캐시 대상이 아님 :518-523), RackGroup/Rack1 `Power`·`PowerSubsystem`·`Thermal`·`ThermalSubsystem` 각 1회).
- 근거: `extract/csus3200_01/redfish/v1/Chassis/RackGroup/index.json` 키 = `ChassisType, Links, Manufacturer, Model, Oem, PartNumber, SerialNumber, Status`(Power/Thermal 계열 링크 없음), `Rack1` 도 없음, `r001u01` 은 `PowerSubsystem`·`ThermalSubsystem`·`Sensors` 만 있고 `Power`/`Thermal`/`EnvironmentMetrics` 없음. `_links.json`/크롤러에도 없는 경로 → 미러 404(README 한계 #4).
- 코드: `gather_chassis_multi:6111-6116` 가 모든 Chassis 멤버에 `gather_power`/`gather_thermal` 호출; `gather_power:5323-5329` 는 `/Power` 고정 경로 → 404 면 `/PowerSubsystem`(:5155); `_gather_power_subsystem:5232` 는 `/EnvironmentMetrics` 고정 경로; `gather_thermal:5403-5409` 는 `/Thermal` → `/ThermalSubsystem`(:5511). `_resolve_system_chassis_uris:1829` 는 Partition0.Links.Chassis=[r001u01] 만 돌려주므로 RackGroup/Rack1 요청은 multi_node 순회에서만 나온다(집합 섀시에 Power/Thermal 을 시도하는 구조 맞음).
- 실제 / 기대: 값은 동일({} / {}·PSU 4·temps·fans) — 요청 수만 11/193(csus3200_01 distinct) 낭비. 실장비가 미링크 경로에 404 가 아닌 다른 상태(예: 400/500)를 주면 `_is_404_only_error` 를 벗어나 errors 로 승격될 수 있다(검증 불가).
- 수정 제안(공통): `gather_power`/`gather_thermal` 에 선택 인자 `chassis_data` 를 받아(`gather_chassis_multi` 는 이미 `cdata` 를 가짐; top-level 은 `gather_system` 이 받은 chassis 본문 재사용 가능) 본문에 `Power`/`PowerSubsystem`(`Thermal`/`ThermalSubsystem`, `EnvironmentMetrics`) navigation property 가 **하나도 없으면 GET 없이 {}**, 신 링크만 있으면 레거시 GET 생략. 본문을 모르면 현행 유지(Additive).
- 회귀: CSUS 재생에서 distinct 요청 집합에 위 11개가 없고 power/thermal 값 동일; DL380/SR650(둘 다 `/Power`·`/Thermal` 존재) 요청·값 불변.
- ADR 영향 없음. 확실성: 요청 발생은 확정, 실장비 응답은 MOCK_LIMITATION.

### 01-multi_node-007 [LOW] `composition.resource_blocks[].processor_count/memory_count = 0` — 원천 배열이 없을 때 0 은 거짓 값
- 대상: CSUS 7대 전부. 근거: `extract/csus3200_01/redfish/v1/CompositionService/ResourceBlocks/r001u01/index.json` 에 `Processors`/`Memory` 키 없음(ResourceBlockType `["ComputerSystem"]`, Links.Chassis r001u01, Links.ComputerSystems Partition0). 코드 `gather_composition_service:6207-6208` `len(_dicts(...))` → 0. 실제 Partition0 은 CPU 4 소켓(상위 cpu 섹션).
- 실제 / 기대: 0 / null(모름). ADR-2026-10-19 결정 4("0 은 거짓 값") 원칙과 같다.
- 수정 제안: 키가 없거나 list 가 아니면 null(값 의미만, 키/타입 `int|null`). 계약 예시가 int 라 사용자 결정 항목. 회귀: ResourceBlock 에 배열이 없는 재생에서 null, 있는 합성 입력에서 len. 확실성: 확정.

### 01-system-008 [LOW] `sections.system = not_supported` 인데 `data.system.hostname/fqdn` 은 내보냄 — 계약 정합 결정 필요 (CSUS 는 HostOS 로 더 채울 수 있음)
- 대상: 18/18. 필드: `sections.system`, `data.system.*`.
- 근거: `normalize_standard.yml:702-703` `_sections_supported_fragment` 9개(system 제외) → `sections.system=not_supported`; 같은 파일 :555-566 이 `system.hostname/fqdn` 을 채움; `schema/field_dictionary.yml:2674-2700` 은 `system.hostname/fqdn` 을 must·redfish 로 선언; `docs/contract/03-fields.md:139` 표는 Redfish system 을 (X). CSUS 2차 3대 + 1차 03/04 의 `Systems/Partition0.Oem.Hpe.HostOS` = `{OsName: "Red Hat Enterprise Linux", OsVersion: "9.6 (Plow)" | "8.10 (Ootpa)", OsSysDescription}` 는 기존 `system.distribution`/`system.version` 에 그대로 들어갈 수 있는 값이다(현재는 `hardware.oem.host_os_*` 에만).
- 실제 / 기대: 소비자가 `sections.system` 만 보면 hostname 이 없다고 판단할 수 있다; 기대는 사용자 결정(계약 문장 정리 또는 섹션 상태 재정의).
- 원인(확정): 2026-10-15 계약 정렬이 `data.system` 키만 추가하고 섹션 상태는 손대지 않음. 영향: 문서 해석 모호. 수정 제안: 문서에 "Redfish `sections.system` 은 not_supported 이지만 `data.system.hostname/fqdn` 은 채워진다" 를 명시(§3 표 각주); HostOS → `system.distribution/version` 채움은 `sections.system` 상태(not_supported→success)가 바뀌는 호출자 계약 변화라 ADR-2026-10-19 의 ESXi power/thermal 과 같은 **결정 항목** 으로만 기록. 확실성: 확정.

### 01-system-009 [LOW] ADR-2026-10-15 재검증 — "RMC 이름 = 서버 이름" 은 2차 3대에서 성립하지만 `hostname_source=system` 의미는 여전히 어긋남
- 대상: csus3200_01..03 (RMC `NetworkProtocol.HostName` == `Partition0.HostName`: yicdspdb01 / yicgsfabap01 / yicgsfabdb01 — 결정과 무관하게 같은 값), r1_HPE_CSUS3200_03/04 (RMC `M10MESDB11-RMC` ≠ Partition `m10mesdb11`), r1_HPE_CSUS3200_01/02 (Partition null, RMC 공장명 `RMC7CA62A413692`/`…418172` 가 `system.hostname` 으로 나감).
- 근거: `extract/csus3200_0N/redfish/v1/Managers/RMC/NetworkProtocol/index.json` `HostName`, `Systems/Partition0/index.json` `HostName`; Tier 1 `diagnosis.details.hostname_source = "system"`(7/7).
- 코드/문서: `normalize_standard.yml:526-537`, `build_output.yml:102-107`, `docs/ai/decisions/ADR-2026-10-15-csus-hostname-rmc-first.md` 결정 2·3 과 결과 절 "D2 — bmc 로 표시하려면 공통 builder 에 출처 힌트를 더해야 했다 — 하지 않았다".
- 판정: 당시 가정(CSUS 1대 = RMC 1 = 파티션 1 = OS 1, 사이트가 RMC 이름을 서버 이름으로 운용)은 2차 3대로 **재확인**(RMC 이름과 OS 이름이 같음). 새 증거로 결정을 뒤집을 이유는 없다. 남는 문제는 계약 문장 "source=system 은 System/OS 이름" 이 CSUS 에서 거짓이 되는 것(1차 01/02 는 BMC 공장명인데 system).
- 정정 제안(문서): `docs/contract/03-fields.md` §8 호출자 주의에 "CSUS 3200 은 `hostname_source=system` 이어도 값이 RMC 이름(공장 기본명 가능)" 을 명시. 코드 변경은 공통 builder 에 adapter 분기를 넣게 되어 ADR 이 거절한 대안이므로 제안하지 않는다. 확실성: 확정.

### 01-correlation-010 [LOW] `correlation.bmc_ip` 정의 문서화 — "BMC 가 보고한 첫 IPv4 NIC" 이며 대상 IP 와 다를 수 있음
- 대상: 18/18 (모두 전용 관리 NIC 이 첫 멤버라 값은 적절: DL380 `EthernetInterfaces/1`, SR650 `…/NIC`(ToHost 0.0.0.0 제외), CSUS `…/1`(Aux/Mul/Partition0 IPv4 없음), Dell `NIC.1`).
- 근거: `gather_bmc:2863-2890`(첫 non-zero IPv4), `build_correlation.yml:36-39`; `docs/contract/03-fields.md:1131-1133` FAQ "Redfish 는 둘이 같은 게 정상". 재생에서는 `host_ip=127.0.0.1`(README 한계 #9).
- 실제 / 기대: 값 PASS; 문서가 "같아야 정상" 으로 읽혀 NAT/VIP 또는 공유 NIC 이 먼저 나열되는 장비에서 오해 가능. 제안: FAQ 문장을 "`bmc_ip` 는 Manager EthernetInterfaces 중 IPv4 를 가진 첫 NIC 의 주소, `host_ip` 는 요청 대상 주소 — 보통 같지만 다를 수 있다" 로. 확실성: 확정(문서).

### 01-adapter-011 [LOW] 문서·시험이 Lenovo XCC3 adapter 를 "사이트 검증 PASS" 로 기록 — 1차 선택만 검증됐고 재선택은 미검증; HPE 펌웨어 패턴 가상 공백
- 대상: Lenovo 5대 (01-adapter-001 의 문서/시험 측면), HPE(가상).
- 근거: `docs/ai/catalogs/VENDOR_ADAPTERS.md:72`("실 미러 캡처 2026-06-15 (replay 2 fix)"), `:212`("사이트 검증 adapter … lenovo_xcc3 … PASS"), `adapters/redfish/lenovo_xcc3.yml` Tested against("adapter 선택 실측 … priority 로 선택 … [정상]"), `tests/evidence/2026-06-15-lenovo-sr650-v4-audit.md`(adapter 재선택 언급 없음), `tests/unit/test_adapter_generation_tokens.py:61`(가공 펌웨어 "XCC3 1.20"), `tests/integration/test_redfish_hostname_policy_replay.py:155`(real_lenovo_sr650 재생에서 adapter 를 고르지만 hostname 만 단언). HPE: `hpe_ilo6.yml:40` `["iLO\\s*6\\b","^1\\.[5-9]"]`, `hpe_ilo4.yml:31` `["iLO\\s*4\\b","^1\\.[0-9]"]` — Gen11 + 펌웨어 "1.10"~"1.19" 가상 입력은 현행·제안 규칙 모두 `redfish_hpe_ilo4`(표본 없음, 관찰).
- 제안: 카탈로그·adapter 주석을 "1차 선택 검증, 재선택은 01-adapter-001" 로 정정; 시험은 실측 펌웨어 문자열 사용. 확실성: 확정(문서), HPE 공백은 가상.

## 5. 미추적 Redfish 정보 (기존 필드로 표현 가능한 것만 개선안 · 계약 밖은 관찰)

개선안(기존 필드):
- `hardware.bios_date` ← Lenovo FirmwareInventory UEFI `ReleaseDate` (01-hardware-004).
- `hardware.oem.machine_type` ← `System.SubModel`, `hardware.oem.led_indicator` ← `System.IndicatorLED` (01-hardware-005).
- `hardware.health` 의 폴백(`Status.Health` null 일 때 `HealthRollup`) (01-hardware-002 (2)).
- (결정 항목) `system.distribution`/`system.version` ← CSUS `Oem.Hpe.HostOS.OsName/OsVersion` (01-system-008).

관찰(계약 밖 — 확장하지 않음):
- SR650 V4 TPM: `TrustedModules` null 이지만 `Systems/1/Bios` Attributes `TrustedComputingGroup_DeviceStatus = "ST TPM2.0 Device present"`, `TrustedComputingGroup_TPMDevice = Enabled` (이미 `data.bios.current.attributes` 에 있음). `hardware.tpm` 계약 원천이 TrustedModules 라 그대로 둔다.
- CSUS `hardware.bios_version`("1.77.30-20260911_061319")은 `Managers/RMC.FirmwareVersion` 및 FirmwareInventory `ComplexFW`/`Partition0_FW` 와 같은 복합 번들 버전이다 — RMC 는 UEFI 단독 버전을 노출하지 않는다(Bios Attributes 76개에도 버전 속성 없음). raw 충실.
- CSUS 미요청 자원(인벤토리 `exists_untouched`): `Chassis/r001u01/Assembly`(메인보드/파워보드/BaseIO/HARP/QSFP-DD/백플레인의 SerialNumber·PartNumber·Model), `Chassis/r001u01/Location`(rack1/chassis_u1, Placement.Rack 1/RackOffset 1), `PhysicalSecurity.IntrusionSensor`, `TrustedComponents/{Host,RMP}`, `Managers/RMC/ServiceIdentification`(= 시리얼), `Systems/Capabilities`(ComputerSystem 타입이지만 Systems 컬렉션 멤버가 아님 — `_resolve_all_member_uris` 가 세지 않아 partition_count 에 영향 없음, 정상), `RackGroup.Oem.Hpe.ProductIds`.
- DL380 미요청: `Chassis/1/Assembly`(Computer System Chassis 시리얼 = System.SerialNumber, DC-SCM PCA 시리얼/파트), `Oem.Hpe.PCASerialNumber/PCAPartNumber`(보드 수준 — 서버 PartNumber 가 아님, 따라서 `part_number null` 이 맞다), `Oem.Hpe.ServerFQDN`(5대 전부 "" — hostname 대체 원천으로 쓸 수 없음), `Oem.Hpe.PowerOnMinutes/SystemUsage`, `ServiceRoot.Oem.Hpe.Manager[0].HostName`(무인증으로 iLO 이름을 읽을 수 있음 — 선택 facts 가 아니라 식별 힌트로만 관찰).
- SR650 V4 미요청: `Chassis/1/Oem/Lenovo/SysvpdSettings`(BaseBoardSerialNum, BaseBoardFRUNum, InServiceDate 등 VPD), `Systems/1/Oem/Lenovo/Metrics`, Chassis 하위 `Drive_Backplane_*`/`IO_Board`/`PCIe_Riser_*`(System 이 링크하지 않는 구성품 섀시 — hardware 에 영향 없음).
- Dell R740: `BootProgress.OemLastState`("No bootable devices.")는 버려지고 `LastState="OEM"` 만 남는다(계약대로); `TrustedModules[0].FirmwareVersion="Unknown"` 문자열 그대로(관찰).
- SR650 V4 ServiceRoot 로 더 얻을 수 있는 1차 facts: 없음 — `Product`/`Oem` 부재, `Vendor`/`UUID`/`RedfishVersion`(1.22.0; 1차 1.17.0)뿐. `UUID` 는 System/Manager UUID 와 같은 값. 무인증 `GET Systems/1`·`Managers/1` 은 재생에서 401(실장비 익명 허용 범위는 미러에 없음 — MOCK_LIMITATION). 따라서 Lenovo 1차 선택은 priority 로 남고, 정답은 재선택이 내야 한다(01-adapter-001).

## 6. ADR·문서·테스트 교차 검증

| 문서 | 결정/가정 | 11대(+1차) 증거 | 판정 · 정정 제안 |
|---|---|---|---|
| ADR-2026-10-15 (CSUS hostname rmc-first) | RMC 이름 = 서버 이름; `system.hostname`=RMC, source=system | 2차 3대 RMC 이름 == Partition0.HostName; 1차 03/04 는 "-RMC" 접미 차이; 1차 01/02 는 Partition null·RMC 공장명 | 모순 없음(가정 재확인). source 의미 불일치만 문서 보강(01-system-009) |
| ADR-2026-10-19 (단일 서버 정합) | `-NNN` 제거(세 조건), part_number 섀시 폴백, `multi_node` 유지 | 2차 3대 `SGHD4MG***-000` → 접미사 제거 후 Chassis·RackGroup·RMC 시리얼과 일치; part_number R9N70A; multi_node 1/1/3 | 성립. 접미사 없는 물리 시리얼은 `Chassis r001u01`/`Managers/RMC`/`RackGroup` 세 곳에 직접 있다(원천 대안 관찰) |
| ADR-2026-06-04 (vendor display) | hp / hpCsus 표시 | 4+1 hp, 3+4 hpCsus, lenovo 4+1, dell 1 — adapter_output_display 가 adapter_id 로 결정되므로 Lenovo 재선택 강등은 표시값에 영향 없음(둘 다 lenovo) | 성립 |
| ADR-2026-06-04 (CSUS adapter priority 102) | model 매치가 iLO6 catch-all 을 이김 | 재선택 facts(model CSUS, fw 1.77.30-…)에서 csus 102570 > ilo6 100345 — fw "1.77" 이 ilo6 `^1\.[5-9]` 에 걸려도 priority 로 유지 | 성립(7/7) |
| ADR-2026-05-12 (multi_node) | 결정 6: 실측 baseline 교체 의무 | baseline 은 아직 mock(3 partition/4 manager/PCIe) | 미이행(01-multi_node-003) |
| ADR-2026-06-09 (model completion: boot/thermal/log_services/composition/fabrics) | DMTF 표준 리소스 graceful | partitions[].boot ✓(BootOrder 2건), chassis[].thermal ✓(r001u01 만), managers[].log_services ✓(7개 OEM 로그), composition ✓(RB 1, count 0 — 01-multi_node-007), fabrics ✓(Switches 2, Endpoints 링크 없음, FabricType 없음) | 성립. 문서의 "fabric_type PCIe placeholder" 는 실측 null 로 정정 |
| `docs/contract/03-fields.md` 6.1 / `field_dictionary.yml` hardware.health | "BMC rollup", "PSU 1대 fault → Critical" | DL380 Gen12: Status.Health Warning, AHS Critical | 정정 필요(01-hardware-002) |
| `docs/contract/03-fields.md` §3 표 | Redfish system (X) | `data.system.hostname/fqdn` 은 채워짐 | 각주 보강(01-system-008) |
| `docs/ai/catalogs/VENDOR_ADAPTERS.md:72,212`, `lenovo_xcc3.yml` 주석 | XCC3 adapter 사이트 검증 PASS | 최종 adapter_id 는 lenovo_bmc | 정정(01-adapter-011) |
| `tests/unit/test_adapter_generation_tokens.py:61` | 펌웨어 "XCC3 1.20" 으로 xcc3 선택 | 실 펌웨어 "IHX438R 2.97 20260910" | 실측 문자열로 교체(01-adapter-001 회귀) |
| `tests/integration/test_redfish_hostname_policy_replay.py` | real_lenovo_sr650 hostname `XCC-7DGD-J902E57T`(bmc) | 1차 미러와 일치; 2차 4대는 사이트가 XCC 이름을 서버명으로 설정(공장명 아님) | 성립. adapter 단언 추가 제안 |
| `tests/fixtures/redfish/real_hpe_csus3200/expected_output.json` | 모듈 골든(serial -000 유지, hostname null) | 2차 재생 `_golden_compare` 차이 0(adapter 모드) | 성립 |

## 7. Replay·테스트 허점 (숨겨지는 오류, 과도한 default/stub, 미커버 경로)

1. **재선택 미검증**: Tier 2(모듈 재생)는 Ansible 층(`reselect_adapter.yml`·`normalize_standard.yml`)을 거치지 않아 adapter 재선택·hostname_priority·시리얼 정규화를 볼 수 없다(Tier 1 과의 차이가 정확히 그 층: serial `-000`, uuid 소문자, hostname 첫 라벨). 기존 단위시험은 가공 펌웨어 문자열("XCC3 1.20")로 통과한다. → 실제 인증 후 facts 로 된 파라미터 시험 필요(01-adapter-001).
2. **404 only 판정이 숨기는 것**: 미러에 없는 고정 경로가 404 로 재생되고 `_is_404_only_error` 가 errors 에서 지우므로, 실장비가 다른 상태를 줄 때의 동작(errors 승격 → power/thermal 섹션 failed 가능)은 재생으로 검증되지 않는다(01-multi_node-006).
3. **익명 허용 범위**: 재생은 ServiceRoot 만 무인증 200 — `mode=detect` 의 `GET Systems/1`/`Managers/1` 이 실장비에서 200 이면 1차 facts 가 채워져 Lenovo 1차 선택 결과가 달라질 수 있다(정답 쪽으로). 확정 불가.
4. **WWW-Authenticate realm**: DL380/SR650 manifest 에 realm 이 없어 `_probe_realm_hint` 경로 미검증(vendor 는 ServiceRoot.Vendor 로 이미 확정되어 영향 없음).
5. **1차 v1 미러**: 비-2xx 가 기록되지 않아 404 로만 재생 — 1차 CSUS 의 Aux NIC 등은 2차와 같이 "파일 없음=404" 로 재생됐고 bmc.ip 는 첫 NIC 이라 영향 없음.
6. **mock baseline 이 회귀 기준**: `hpe_csus_3200_baseline.json` 이 mock 이라 실 구조 회귀가 baseline 으로는 잡히지 않는다(01-multi_node-003). 1차 CSUS 축약 골든(`real_hpe_csus3200`)이 실질 기준.
7. **단위시험 격리 결함**(baseline README Tier 0: 한 프로세스 실행 시 36/19 failed, 단독 통과) — 내 영역 밖이나 adapter 선택 시험 추가 시 같은 전역 상태(모듈 seam/캐시)에 주의.

## 8. 1차 7대 및 기존 모델 영향

- **Dell R740 (1차)**: hardware 전부 PASS(serial = ServiceTag `J0KV603`, System.SerialNumber `CNIVC…` 는 보드 시리얼, bios_date OEM `01/28/2026`→`2026-01-28`, tpm raw `Unknown/Disabled`). adapter: 1차 `redfish_dell_idrac10` → 재선택 `redfish_dell_idrac9`(설계). 제안 규칙 B 에서도 동일(시뮬레이션). 표준 로그인이 401 이면 재선택이 서지 않아 계정 복구는 1차 hint(idrac10)를 받는데, `resolve_account_family` 가 Firmware major 를 우선하도록 이미 교정돼 있다(:7521-7560) — 계정 작업자 참고.
- **HPE DL380 Gen12 (1차 1대 + 2차 4대)**: 동일 adapter·동일 흐름. 1차는 iLO 공장명(`ILOSGHD3KHHRP`, source=bmc), 2차 3대는 사이트 iLO 이름(source=bmc), 2차 01 만 System.HostName 설정(source=system, fqdn 포함). health: 1차 OK/OK/OK, 2차 Warning(+AHS Critical 2대). Chassis 멤버 2개(`1`, `DE00B000`) 중 System.Links.Chassis[0]=`Chassis/1` — 영향 없음.
- **Lenovo SR650 V4 (1차 1대 + 2차 4대)**: 1차 Chassis 14개 vs 2차 4개(`Drive_Backplane_*`/`IO_Board`/`PCIe_Riser_*` 구성품 섀시 수 차이)는 `System.Links.Chassis[0]=Chassis/1` 이 같아 hardware 에 영향 없음(multi_node N/A). 펌웨어 `IHX414J 1.22` → `IHX438R 2.97`, UEFI `IHE110U` → `IHE120L/P`, RedfishVersion 1.17.0 → 1.22.0, Manager.Model 표기 `Xclarity` → `XClarity`(대소문자) — 어느 것도 재선택 강등을 바꾸지 못한다(둘 다 lenovo_bmc). health 1차 Warning/Rollup OK, 2차 Critical(Rollup 없음). part_number/FruPartNumber 보드 리비전 차이(SB27B69948/03NA960 → SB27C33739/03PV737)는 raw 반영.
- **HPE CSUS 3200 (1차 4대 + 2차 3대)**: RMC 1.75.108 → 1.77.30 에서 hardware/multi_node **shape 변화 없음**(1/1/3/1/1, 같은 OEM `#HpeH3Npar`/`#HpeH3Chassis`/`#HpeH3RackGroup`). 값 차이: `Oem.Hpe.HostOS`·`DCD.DCDVersion` 이 2차 3대 전부와 1차 03/04 에만 있음(1차 01/02 는 `DCD {}`, HostOS 없음 — 펌웨어가 아니라 OS 측 DCD 에이전트 유무로 보임, 추정), TPM state `StandbyOffline`(1차 01/02) vs `Enabled`, boot_order 3건 → 2건, chassis thermal temps 47/63(노드별), Status.Conditions 레지스트리 `H3Alert.1.7` → `1.8`. hostname: 1차 01/02 공장명 · 03/04 "-RMC" · 2차 OS 이름과 동일(01-system-009).
- **11대 외 기존 모델**: 규칙 B 는 HPE Gen11/Gen10/Gen12, Dell R760/R740, Cisco CIMC/UCS-X, Lenovo V2/V3/V4/IMM2, CSUS 의 기존 시험 매트릭스에서 선택 결과 불변(§4). `cisco_cimc.yml`(uuid_byte_order 선언)은 재선택 결과가 바뀌지 않는 한 영향 없음. Supermicro/Huawei/Inspur/Fujitsu/Quanta 는 lab 부재 — 패턴 구조(model_patterns + firmware_patterns 병존 여부)에 따라 B 의 효과가 달라질 수 있어 시뮬레이션 대상에 넣어야 한다(`ls adapters/redfish/*.yml | wc -l` → 31, 2026-10-26 측정).

## 9. 검증 한계 (재생 한계·Mock 한계·미확인)

- baseline README 한계 1~9 그대로: 익명 허용 범위·Basic 비밀번호·timeout·미러에 없는 경로 404·401 헤더·1차 비-2xx·엔진 버전·precheck 127.0.0.1·`correlation.bmc_ip`/`host_ip` 불일치.
- `hardware.uuid` 바이트 순서: 같은 11대의 OS/ESXi 캡처가 없어 HPE/Lenovo 가 SMBIOS 표기와 같은지 확인 불가(HPE UUID 는 제품번호+시리얼 ASCII 를 raw 순서로 담은 형태 — 관찰). correlation 은 `uuid_equal` 이 양쪽 순서를 대조하므로 매칭 자체는 안전.
- Lenovo 무인증 facts: 실장비 XCC3 가 Systems/Managers 를 익명 허용하는지 미러에 없음.
- CSUS 고정 경로 11개의 실장비 응답(404 여부) 미러에 없음.
- `system.fqdn` 이 CSUS/SR650/DL380(2차 02~04)에서 null 인 것은 원천에 도메인이 없어서이며 결함이 아니다(DL380 01 만 `yimad.net` 도메인).
- `oem.machine_type ← SubModel`, `fru_serial ← SystemBoardSerialNumber`, Lenovo UEFI ReleaseDate 의 의미는 Lenovo 공식 문서로 확인하지 않았다(추정 표기).

## 10. 탐색 경로 기록

- 읽은 제품 코드: `redfish-gather/library/redfish_gather.py`(함수 색인 전체, :1385-2720 벤더/식별/시스템, :2801-2993 bmc, :5003-5106 firmware, :5106-5262 power, :5305-5552 power/thermal/boot, :5687-6420 multi_node, :6539-6690 dispatch/status, :7521-7640 account family, :9086-9339 main), `module_utils/adapter_common.py`(전체), `lookup_plugins/adapter_loader.py`(전체), `redfish-gather/tasks/{reselect_adapter,detect_vendor,collect_standard,normalize_standard}.yml`(전체), `redfish-gather/site.yml`(:95-160, :300-380), `common/tasks/normalize/{build_output(:60-140),build_correlation,build_meta,resolve_vendor}.yml`, `common/library/precheck_bundle.py:655-675`, `filter_plugins/{serial_normalizer(:1-120,178),identity_normalizer(:120-215)}.py`, `adapters/redfish/{lenovo_xcc3,lenovo_xcc,lenovo_imm2,lenovo_bmc,dell_idrac9,dell_idrac10,dell_idrac8,dell_idrac,hpe_ilo7,hpe_csus_3200,hpe_superdome_flex,redfish_generic}.yml` + `hpe_ilo{4,5,6,}.yml` match 블록, `common/vars/vendor_aliases.yml`, `schema/sections.yml`, `schema/field_dictionary.yml`(:100-200, :330-500, :2674-2700), `schema/baseline_v1/hpe_csus_3200_baseline.json`.
- 문서: `docs/contract/03-fields.md`(§1-3, 6.1, FAQ, §8, §9), ADR 2026-05-12 · 06-04(2건) · 10-15 · 10-19, `docs/ai/catalogs/{VENDOR_ADAPTERS,EXTERNAL_CONTRACTS}.md`(grep), `tests/evidence/2026-06-15-lenovo-sr650-v4-audit.md`(grep).
- 시험: `tests/unit/test_redfish_adapter_reselect.py`(전체), `test_adapter_selection_t01.py`·`test_adapter_generation_tokens.py`(매트릭스), `tests/integration/test_redfish_hostname_policy_replay.py`(:1-80, lenovo 단언), `tests/fixtures/redfish/real_hpe_csus3200/expected_output.json`, `tests/reference/redfish/lenovo/10_50_11_232`(V2 chassis/system/manager).
- 증거: `baseline/{README,baseline_summary}.md`, `baseline/adapter_selection_{1차,2차}.*`, `tier1/*/gather_output.json`(18), `tier1/csus3200_0{1,2,3}/server_access.jsonl`·`requested_keys.json`, `tier2/_golden_compare.*.json` 와 18 모듈 출력(Tier 1 과 hardware/system 필드 대조 — 차이는 정규화 층의 serial/uuid/hostname 변환뿐), `inventory/INVENTORY.md` + `csus3200_01/dl380_gen12_01/sr650_v4_01.jsonl`(Systems/Chassis/Managers 미요청 자원), `tools/{mirror_policy,tier2_replay}.py`.
- Mock 원본: 2차 11대 `redfish/v1/{index, Systems/*, Managers/*(+NetworkProtocol, EthernetInterfaces/*), Chassis/*(+Assembly, Oem/Lenovo/SysvpdSettings), CompositionService/ResourceBlocks/*, Fabrics/FlexGrid(+Switches), UpdateService/FirmwareInventory/*, Systems/*/Bios}`, 1차 7대 같은 경로.
- 스크립트(scratchpad `w01/`, 제품 코드 무수정): `dump_fields.py`(18 envelope 담당 필드 추출), `table_fields.py`(서버별 표 + Tier 2 대조), `sim_reselect.py`(현행 vs 규칙 B 점수 시뮬레이션 — `module_utils/adapter_common.py` 를 import 만), `gen_coverage.py`(coverage.json 생성). 404 집계: `server_access.jsonl` 의 `s==404` 라인 수.
- 문제 없음 확인 항목: 18대 hardware 식별 12필드 raw 1:1 일치, hostname 체인 18/18 계약 일치, vendor 표시 18/18, correlation 3필드 18/18, CSUS multi_node 구조 7/7 raw 일치, Dell 대표 시리얼 ServiceTag, HPE/Dell bios_date hoist, A1/A1b/A-7 폴백 발동 조건(정상 벤더 미발동) 확인.
