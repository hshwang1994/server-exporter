# EXTERNAL_CONTRACTS — server-exporter

> 외부 시스템 (Redfish / IPMI / SSH / WinRM / vSphere) 계약 카탈로그. rule 28 #11 측정 대상 (TTL 90일). rule 96 origin 주석 정본.

## 일자: 2026-08-12 — Dell iDRAC 비밀번호 정책 실측 (git 10.100.15.34 / 10.100.15.27)

> 정본: `tests/evidence/2026-08-12-git-location-live-verification.md` §4
> 대상: iDRAC9 / 16G Monolithic / FW **7.10.70.00** / Redfish 1.20.1 /
>       `#AccountService.v1_15_1.AccountService`

Redfish 표준 AccountService (읽기 전용 실측):

```text
MinPasswordLength = 0        MaxPasswordLength = 127
AccountLockoutThreshold = 0  AccountLockoutDuration = 0  CounterResetAfter = 0
AuthFailureLoggingThreshold = 2   LocalAccountAuth = Fallback
SupportedAccountTypes    = Redfish, SNMP, OEM, HostConsole, ManagerConsole,
                           IPMI, KVMIP, VirtualMedia, WebUI
SupportedOEMAccountTypes = IPMI, SOL, WSMAN, UI, Racadm
Roles                    = Administrator, Operator, ReadOnly, None
ETag                     = AccountService / 각 ManagerAccount 모두 제공
```

OEM 보안 Attribute (`/redfish/v1/Managers/iDRAC.Embedded.1/Attributes`):

```text
Security.1.MinimumPasswordScore     = Weak Protection     ← 유일하게 활성인 제약
Security.1.PasswordMinimumLength    = 0
Security.1.PasswordRequireUpperCase = Disabled
Security.1.PasswordRequireNumbers   = Disabled
Security.1.PasswordRequireSymbols   = Disabled
Security.1.PasswordRequireRegex     = (빈 문자열)
IPBlocking.1.BlockEnable = Enabled  FailCount = 3  FailWindow = 60  PenaltyTime = 60
```

Attribute Registry (`/redfish/v1/Registries/ManagerAttributeRegistry`) 정의:

```text
Security.1.MinimumPasswordScore : Enumeration ['0','1','2','3']
    HelpText "Password must have this minimum strength score."
Security.1.PasswordMinimumLength: Integer, LowerBound 0, UpperBound 20
```

**핵심 계약 사실**: Dell 의 `Security Strengthen Policy` 거부는 길이/문자종류/정규식
**규칙이 아니라 강도 점수** 검사에서 나올 수 있다. 규칙 property 가 전부 비활성인데도
쓰기가 거부되는 상태를 실측했다. 점수 산출 알고리즘과 사전 검증 endpoint 는 노출되지 않는다.

⇒ 코드가 `MinPasswordLength`/`MaxPasswordLength` 만 보고 "정책 호환" 이라고 단정하면 안 된다.
   현재 구현은 그 값을 `within_declared_bounds` 로만 남기고 **차단하지 않으며**, 실제 거부는
   쓰기 응답(`@Message.ExtendedInfo`)으로 확정한다 — 이번 실측이 그 설계를 뒷받침한다.

Password History 전용 property 는 이 펌웨어의 Attribute 목록에 **존재하지 않는다**.

## 일자: 2026-08-12 — 9 Vendor 계정 Write 계약 origin (공식 조사 반영)

> 정본 매트릭스: Vendor × Family 매트릭스
> 아래는 `redfish_gather._ACCOUNT_FAMILIES` 각 항목의 근거 출처다 (rule 96 R1).

| Family | 계약 | origin |
|---|---|---|
| `dell_slot_patch` | 빈 slot PATCH, slot 1 = IPMI anonymous 예약 | dell.com/.../idrac8_2.70.70.70_ug/configuring-local-users |
| `dell_idrac10_slot_patch` | slot 1 + slot 2(default root) 예약, Local User 32 | dell.com/.../idrac10_1.20.xx_ug/configuring-local-users |
| (Dell 공통) | iDRAC10 IP Blocking FailCount 3 / FailWindow 60s / Penalty 60s | dell.com/.../idrac10_1.xx_scg/network-security-configuration |
| (Dell 공통) | iDRAC9 Password Strength Policy (4.40.00.00+) | dell.com/.../idrac9_7.xx_ug/password-strength-policy |
| `hpe_ilo4` | OEM namespace `Oem/Hp`, Password/UserName max 39 | hewlettpackard.github.io/ilo-rest-api-docs/ilo4/ |
| `hpe_ilo5plus` | RoleId(Administrator/Operator/ReadOnly) + Oem/Hpe/Privileges | servermanagementportal.ext.hpe.com/docs/redfishservices/ilos/supplementdocuments/managingusers |
| (generic) | CSUS 3200 RMC — Account 는 username path, POST create 는 목차만 확인 | support.hpe.com/.../sd00002765en_us (Configuring RMC user accounts / PATCH update) |
| (generic) | Superdome Flex 280 RMC — 30 users, password 6~40 class 기반 min | support.hpe.com/.../a00108548en_us (Setting up users from CLI) |
| `lenovo_purley_slot_patch` | Intel Purley = pre-populated slot, 빈 UserName 이 빈 slot, PATCH create | pubs.lenovo.com/xcc-restapi/create_an_account_intel_p_based_patch |
| `lenovo_collection_post` | Whitley/AMD = Collection POST; TSM 은 PasswordChangeRequired 미지정 시 default **true** | pubs.lenovo.com/xcc-restapi/create_an_account_post, pubs.lenovo.com/tsm/post_create_new_account |
| `lenovo_xcc_accounttypes` | XCC2/XCC3 AccountTypes(Redfish/SNMP/ManagerConsole/IPMI/WebUI), XCC3 은 `HostBootStrap` 제외 | pubs.lenovo.com/xcc2-restapi/create_an_account_post, pubs.lenovo.com/xcc3-restapi/resource_account_service_accounts |
| `cisco_cimc_collection_post_id` | IMC 4.1~6.0 = Collection POST + body `Id` + RoleId `admin` | cisco.com/.../b_Cisco_IMC_REST_API_guide_4_1 + 사이트 실측 10.100.15.2 (201) |
| `cisco_bmc_dynamic` | 최신 Cisco BMC = Collection POST, RoleId **`Administrator`**, Id 는 BMC 할당 | cisco.com/.../b_cisco-bmc-rest-api-guide (1.0/2.0/4.0) |
| (미채택) | Cisco IMC 3.x = `POST /Accounts/<ID>` (instance) — 근거 부족으로 generic 유지 | cisco.com/.../b_Cisco_IMC_REST_API_guide_301 |
| `supermicro_legacy` | X10+/H11+ Redfish, `POST /AccountService/Accounts`, Role Administrator/Operator/ReadOnly | supermicro.com/manuals/other/redfish-ref-guide-html/.../account-service.htm |
| `supermicro_split_account` | Gen13 01.05.xx+ / Gen14 01.02.xx.xx+ / NVIDIA Superchip 01.04.xx+ 부터 IPMI·Redfish 계정 분리, AccountTypes 기본 Redfish | supermicro.com/en/support/manuals/product/software/redfish-user-guide/Content/general-content/accounts.htm |
| `inspur_m6` | Collection POST(`Id` optional), **HTTP 200 + `Oem.Public.Status == 0`**, PATCH 는 `If-Match` 요구, MinPasswordLength 8~16 설정 가능 | 浪潮英信服务器 Redfish用户手册 V1.2 §4.1~4.7 |
| `huawei_ibmc` | Collection POST + Instance PATCH (2019 MM920 / 2025 Kunpeng 양쪽 공식), Roles + PrivilegeMap 제공 | Huawei EDOC1100372764, EDOC1100105860 |
| (Huawei 미해결) | Local User 별 **Redfish Login Interface** 가 꺼져 있을 수 있음 — 자동 활성화 방법 미확보 | Huawei iBMC User Guide — Setting the User Interfaces for Logging to iBMC |
| (Huawei 공통) | lockout: 5회 연속 실패 -> 5분 자동 잠금 | Huawei iBMC User Guide — Accessing the iBMC CLI |
| `generic_collection_post` | Fujitsu S4/S5/S6, Quanta 전 세대, X-Series, IMM2, X9, Inspur M5/M7, HPE RMC — **공식 Write 계약 미확보** | 근거 없음이 곧 기록이다 (매트릭스 2.6 / 2.9 절) |

### Password Policy 교집합 위험 (신규 기록)

```text
Cisco IMC Strong Password 활성  ->  max 14
Inspur MinPasswordLength        ->  고객이 최대 16 까지 설정 가능
```

두 정책을 동시에 만족하는 단일 비밀번호가 **존재하지 않을 수 있다.** 코드 버그가 아니라
제품 Contract 결정 사항이다 (매트릭스 4절).

## 일자: 2026-08-03 (감사) — **조립 경로 17곳 전수 목록 + 세대 이동 위험도**

> 배경: iDRAC8 사고의 본질은 "리소스 위치가 세대별로 다를 수 있는데 우리는 경로를 **문자열로 조립**한다"
> 는 것이다. 링크(`@odata.id`)를 따라가면 세대 무관하지만, 현 코드는 대부분 조립한다.
> 아래는 `redfish_gather.py` 의 조립 지점 **전수**와 각각의 fallback 유무다.

| 부모 | 조립 경로 | fallback | 세대 이동 위험 |
|---|---|---|---|
| ServiceRoot | `/redfish/v1/` | — | 없음 (표준 진입점) |
| ServiceRoot | `AccountService` | — | 낮음 (ServiceRoot 링크와 관례 일치) |
| ServiceRoot | `TelemetryService/MetricReports` | — | 낮음 |
| Systems | `Processors` / `Memory` / `EthernetInterfaces` | — | **미지** (링크 추적 아님) |
| Systems | `Storage` → `SimpleStorage` → `SmartStorage`(HPE OEM) | **있음 (3단)** | 낮음 |
| Systems | `NetworkAdapters` | **2순위 fallback (2026-08-03 신설)** | 해소 |
| Chassis | `NetworkAdapters` (1순위) | ↑ 와 쌍 | 해소 |
| Chassis | `Power` ↔ `PowerSubsystem` | **있음** | 낮음 |
| Chassis | `Thermal` ↔ `ThermalSubsystem` | **있음** | 낮음 |
| Chassis | `Sensors` / `EnvironmentMetrics` | — (보조) | 낮음 (부재 시 graceful) |

**실측 대조 (2026-08-03)**: 보유 replay fixture **10종 전수**(Dell iDRAC9 / HPE iLO5·iLO6·Gen12 /
HPE CSUS 3200 / Lenovo XCC3 / DMTF 표준 mockup)에서 **부모가 노출한 링크 ↔ 우리가 조립한 경로
불일치 0건**. → 보유 세대에서는 조립이 안전하다.

**남은 위험**: **미보유 세대**. iDRAC8 이 정확히 그 사례였고 fixture 가 없어 사이트가 먼저 발견했다.
자동 가드로 `tests/integration/test_port_classification_invariants.py::test_constructed_paths_match_exposed_links`
신설 — 새 미러를 fixture 로 넣는 순간 자동 대조된다(미보유 세대 캡처 시 즉시 효력).

**근본 대책 (별도 cycle 권장)**: 조립 대신 **부모의 `@odata.id` 링크 추적**. 다만 현 함수 시그니처가
부모 응답을 갖고 있지 않아(`gather_processors(bmc_ip, system_uri, ...)`) ComputerSystem/Chassis 를
한 번 받아 하위로 전달하는 구조 변경이 필요 → 전 섹션 영향, 별도 cycle.

## 일자: 2026-08-03 (Dell — **NetworkAdapters 의 부모 리소스가 세대별로 다름**)

> **가장 중요한 계약 항목**: 같은 리소스가 iDRAC8(13G)은 `Systems` 밑, iDRAC9(14G+)은 `Chassis` 밑.

| 세대 | 장비 | NetworkAdapters URI | 근거 |
|---|---|---|---|
| **iDRAC8 (13G)** | PowerEdge R630/R730/M630 등 | `/redfish/v1/**Systems**/System.Embedded.1/NetworkAdapters[/<id>]` | 벤더 공식 iDRAC8 Redfish API Guide 2.70.70.70 (Collection / Instance 양쪽) |
| **iDRAC9 (14G+)** | PowerEdge R740 등 | `/redfish/v1/**Chassis**/System.Embedded.1/NetworkAdapters[/<id>]` | 내부 실측 — `tests/fixtures/redfish/real_dell_r740/recording.json` = 200 |

**사이트 사고 (Jenkins DAY_1/git/소연등록redfish #1)**:

| 항목 | 값 |
|---|---|
| 대상 | PowerEdge **R630** 8대 (10.50.11.51~54, .151~154), BMC model `13G Monolithic` |
| iDRAC 펌웨어 | 2.75.100.75 / 2.80.80.80 / 2.85.85.85 / 2.86.86.86 → **iDRAC8** |
| RedfishVersion | 1.4.0 |
| 증상 | `GET Chassis/System.Embedded.1/NetworkAdapters` → **HTTP 400 Bad Request** |
| 결론 | **장비 미지원 아님.** iDRAC8 은 이 리소스를 `Systems` 밑에 둔다 — 수집 측 경로 오류 |

**오판 기록 (rule 96 R4 — drift 추적)**: 최초 조사에서 "R740 미러의 동일 URL 이 200" 을 근거로
"장비/펌웨어 미지원" 이라 결론내고 400 을 unsupported 로 분류했으나, **R740 은 14G/iDRAC9 로 세대가 달랐다**.
세대가 다른 장비를 대조군으로 삼은 추론 결함. 같은 날 정정.

- server-exporter 적용: `gather_network_adapters_chassis` 수집 경로 후보 2종(Chassis 1순위 → Systems fallback,
  Additive) + `_extended_info`(DSP0266 `error.@Message.ExtendedInfo` 보존). 400→unsupported 분류는 **철회**.
  상세 `docs/reference/decision-log.md` 2026-08-03 정정 절.
- source (rule 96 R1-A):
  - https://www.dell.com/support/manuals/en-us/poweredge-r730/idrac8_redfishapiguide_2.70.70.70/networkadapter-collection (확인 2026-08-03)
  - https://www.dell.com/support/manuals/en-us/poweredge-r730/idrac8_redfishapiguide_2.70.70.70/networkadapter-instance (확인 2026-08-03)
  - 내부 실측: `tests/fixtures/redfish/real_dell_r740` (iDRAC9 = Chassis 경로 200)
- **미확정**: iDRAC8 이 Chassis 경로에 404 가 아니라 400 을 주는 이유(벤더 구현 특성). fallback 으로 무해화됨.

## 일자: 2026-06-09 (cycle csus-model-completion — CSUS 3200 모델 5종 신 계약 — ADR-2026-06-09)

> CSUS 3200 Redfish 모델 검수 → 누락 5종 수집 추가. 표준 DMTF DSP0266 리소스 (lab 부재 — 사이트 실측 정정 의무 C9~C14).

| 신 계약 (Redfish 리소스) | 사용 필드 | 출처 | 사이트 실측 |
|---|---|---|---|
| `Systems/{id}.Boot` | `BootOrder[]` / `BootSourceOverrideEnabled/Target/Mode` / `BootNext` / `UefiTargetBootSourceOverride` | DMTF ComputerSystem.Boot | C13 (BootOrder 실 표현 — BootString vs BootOption ref) |
| `Chassis/{id}/Thermal` (+ `/ThermalSubsystem` fallback) | `Temperatures[]` (ReadingCelsius/Status/UpperThresholdCritical) / `Fans[]` (Reading\|ReadingRPM/ReadingUnits/Status); ThermalSubsystem: `ThermalMetrics.TemperatureReadingsCelsius[]` + `Fans` 컬렉션(`SpeedPercent.Reading`) | DMTF Thermal.v1 + ThermalSubsystem.v1 (2020.4) | C11 (sensor 명 / 펌웨어 분기) |
| `Managers/{id}/LogServices` | LogServiceCollection.Members → `Id/Name/OverWritePolicy/ServiceEnabled/LogEntryType/DateTime` | DMTF LogServiceCollection / LogService | C12 (실 ID IML/IEL 추정) |
| `CompositionService` + `ResourceBlocks` | `ServiceEnabled/Status` ; ResourceBlock `Id/ResourceBlockType[]/Status/CompositionStatus.CompositionState/Processors[]/Memory[]/Links.Chassis[]/Links.ComputerSystems[]` | DMTF CompositionService/ResourceBlock + HPE CSUS Admin Guide (nPartition=ResourceBlock 조합, 각 RB↔chassis) | C9 (RB↔chassis 매핑 실측) |
| `Fabrics` + `Fabrics/{id}` (FlexGrid) | Fabric `Id/FabricType/Status` ; `Switches` 컬렉션 → Switch `SwitchType/Status` ; `Endpoints` 컬렉션 → Endpoint `EndpointProtocol/Status` (Links/Zones 미사용) | DMTF Fabric/Switch/Endpoint + HPE CSUS architecture (NUMAlink) | C10 (FabricType NUMAlink 표기 — DMTF enum 부재로 placeholder PCIe) |

### server-exporter 적용 (cycle 2026-06-09)
- `redfish_gather.py` — `gather_boot` / `gather_thermal`(+`_gather_thermal_subsystem`) / `gather_manager_logs` / `gather_composition_service` / `gather_fabrics`(+`_gather_fabric_members`) 신설 (Additive, stdlib only). `_collect_multi_node_topology` 에 composition/fabrics + summary 카운트.
- envelope: `data.multi_node.{partitions[].boot, chassis[].thermal, managers[].log_services, composition, fabrics}` + `summary.{resource_block_count, fabric_count}`. ServiceRoot 링크 부재 시 graceful (composition/fabrics=null, boot/thermal={}, log_services=[]).

## 일자: 2026-06-08 (DMTF Published Mockups — DSP2043 오프라인 회귀 reference)

> DMTF 공식 Redfish **Mockup Bundle (DSP2043, BSD-3-Clause)** — `@odata.id` 경로별 index.json 트리.
> DSP8010(스키마, 위 항목)과 별개로 **표준 준수 GET 응답 예시**. `redfish_gather.py` 의 표준(OEM 미사용)
> 추출 경로를 오프라인 회귀로 보호하는 fixture 출처. **dmtf.org 직접 다운로드는 차단(403)** — GitHub
> 미러 `DMTF/Redfish-Mockup-Server`(public-rackmount1 번들) 사용.

| mockup | DMTF dev hub | 우리 fixture | exercise 하는 코드 경로 |
|---|---|---|---|
| `public-rackmount1` | https://redfish.dmtf.org/redfish/mockups/v1/1819 | `tests/fixtures/redfish/dmtf_rackmount1/` | vendor=unknown 표준 경로 / OEM 미추출 / legacy Power / **SimpleStorage fallback** / absent NetworkAdapters→unsupported(graceful) |
| `public-bladed` | .../1820 | (미편입 — 번들 차단 + 본 하네스 multi_node 미활성) | (NEXT_ACTIONS 후보) |
| `public-rackmount1+localstorage` | .../1821 | (미편입 — 번들 차단) | modern Storage/Drives/Volumes(현 fixture 미커버) — NEXT_ACTIONS 후보 |

- 출처/라이선스: DSP2043 (v2021.4 기준) — BSD-3-Clause. mirror: https://github.com/DMTF/Redfish-Mockup-Server
- 변환: `tests/integration/convert_dmtf_mockup.py` (index.json 트리 → recording.json). 재생: `tests/integration/test_dmtf_mockup_replay.py`.
- 경계 (rule 21 R1 / rule 25 R7-B): mockup != 실장비. baseline 승격 금지 — fixture only("DMTF-mockup-derived").
- DMTF 미수집 리소스(Thermal/ThermalSubsystem/Cables/CXL/Fabrics/Telemetry — 1828/1835/1839/1840)는 신규 섹션 = schema 버전 변경(rule 13 R3) → NEXT_ACTIONS Tier B 후보.

## 일자: 2026-06-08 (cycle audit-cleanup — DMTF DSP8010 2026.1 공식 스키마 대조)

> 사용자가 DMTF 공식 Redfish 스키마 번들 **DSP8010 2026.1** (release 2026-04-02, 최신) 다운로드.
> 이를 정본 reference 로 `redfish_gather.py` 의 enum / 필드명 / path 를 전수 대조(audit-first).
> 우리가 실제 참조하는 28 리소스 json-schema 만 `schema/redfish_dmtf_2026.1/` 에 subset vendoring
> (전체 14k 파일 아님 — 런타임 import 안 함, 순수 reference). 출처: `schema/redfish_dmtf_2026.1/README.md`.

### DMTF DSP8010 2026.1 대조 결과 — 10 항목 (9 MATCH + 1 GAP 보정)

| # | 대상 (redfish_gather.py) | DMTF 정본 (vendored) | 결과 |
|---|---|---|---|
| 1 | `_VOLUMETYPE_RAID_MAP` (:1850) | `Volume.json` VolumeType(deprecated) + RAIDType enum | MATCH — 5값 매핑 정확, RawDevice 의도적 제외(raid_level=None) 정확, RAIDType 17값 raw passthrough |
| 2 | `_normalize_link_status` (:1192) | `Port.v1_19_0` LinkStatus = [LinkUp,Starting,Training,LinkDown,NoLink] | **GAP→FIX** — 표준 전이상태 Starting/Training 미처리(raw 통과) → 기존 비작동 매핑과 일관되게 'down' 추가 |
| 3 | `_classify_port_protocol` (:2206) | `NetworkDeviceFunction.v1_11_1` NetDevFuncType = [Disabled,Ethernet,FibreChannel,iSCSI,FibreChannelOverEthernet,InfiniBand] | MATCH — FC/FCoE/IB/Ethernet 분류 정확. iSCSI/Disabled 는 FC/IB 아니므로 미분류(None) 의도적 |
| 4 | `_normalize_role_id` (:1121) | `Role.json` 표준 RoleId(Administrator/Operator/ReadOnly) + vendor 변형 | MATCH — 표준 3 + 9 vendor 변형 매핑, 미지값 raw 보존(Additive) |
| 5 | Processor 필드 (:1646) | `Processor.v1_23_0` ProcessorType/Architecture/InstructionSet | MATCH — raw passthrough (정규화 없음). 신값(Partition/OEM/RISC-V) 자동 수용 |
| 6 | Memory 필드 (:1700) | `Memory.v1_24_0` MemoryDeviceType/BaseModuleType/ErrorCorrection | MATCH — raw passthrough. DDR5/HBM3E 등 신값 자동 수용 |
| 7 | Drive 필드 (:1824) | `Drive.v1_22_0` MediaType=[HDD,SSD,SMR]/Protocol | MATCH — raw passthrough. SMR 신값 자동 수용 |
| 8 | Status.State 필터 (:1636,1689) | `Resource.json` State enum (Absent/Disabled 포함 13값) | MATCH — Absent/Disabled skip 가 표준 enum 과 일치 |
| 9 | `_chassis_kind` ChassisType (:834) | `Chassis.v1_28_0` ChassisType (24값) | MATCH — multi-chassis kind 판정 목적의 부분집합 사용(의도적), 그 외 None |
| 10 | Power/PowerSubsystem (:2557) | `Power.json`/`PowerSubsystem.json`/`EnvironmentMetrics.json` props | MATCH — PowerControl/PowerSupplies/Voltages/PowerWatts 필드명 정확 |

> 범위 외: `_normalize_jedec`(:303)는 JEDEC JEP106 출처(DMTF 아님) — 대조 대상 아님.

### 보정 (Additive only — rule 96 R1-B / rule 92 R2)

- `_normalize_link_status`: down 버킷에 `'starting'`, `'training'` 추가 (DMTF Port.LinkStatus 표준 전이 상태).
  envelope shape / 기존 매핑 변경 0. fixture/baseline 에 해당 값 0건 → 회귀 출력 불변(검증됨).
  회귀 테스트 `tests/unit/test_redfish_pure_helpers.py` 6건 추가. → `CONVENTION_DRIFT.md` DRIFT 참조.

### 갱신 trigger (TTL 90일)

DMTF DSP8010 2026.2+ release / 사이트 펌웨어 schema 변경 관측 / 신규 vendor·세대 추가.

---

## 일자: 2026-05-12 (cycle hpe-csus-rmc-multi-node — RMC 멀티-노드 토폴로지 web sources 보강)

> 사용자 명시 (2026-05-12): "HPE Compute Scale-up Server(CSUS) 3200 ... RMC(Rack Management Controller)를 통해 수행된다 ... CSUS 지원하는 방식을 모두 의심해야해. 다만문제는 테스트해볼 장비가 없어서 web을 통해서 확인할 수 밖에 없다는거야."
> ADR-2026-05-12 / `data.multi_node` Additive 컨테이너 / 8 결정.

### HPE RMC — 사용자 제시 URL + WebSearch 권위 인용 (8건)

| # | URL | 영역 | 확인일 | 인용 |
|---|---|---|---|---|
| 1 | https://support.hpe.com/hpesc/public/docDisplay?docId=sd00002765en_us&docLocale=en_US | HPE Compute Scale-up Server 3200 Administration Guide (사용자 제시) | 2026-05-12 | WebFetch 본문 미수신 (SPA / 인증) — WebSearch 가 해당 URL 을 "CSUS 3200 Administration Guide" 로 식별. RMC API endpoint 정본 reference. |
| 2 | https://servermanagementportal.ext.hpe.com/docs/concepts/gettingstarted | HPE Server Management Portal (Redfish 표준 reference) | 2026-05-12 | ServiceRoot: `{"Product": "...", "Vendor": "HPE", "RedfishVersion": "1.x"}`. Base URL `https://{ip}/redfish/v1/`. Session API `/redfish/v1/SessionService/Sessions`. Headers `X-Auth-Token` / `Authorization`. RMC 전용 multi-Manager 노출 / nPar Systems ID 패턴 미문서화. |
| 3 | https://www.hpe.com/psnow/doc/a50009596enw | CSUS 3200 architecture and RAS | 2026-05-11 | "built on the proven HPE Superdome Flex architecture". RMC + PDHC + RMP 명시. |
| 4 | https://cdrdv2-public.intel.com/792357/FAQ%20-%20HPE%20Compute%20Scale-up%20Server%203200.pdf | CSUS 3200 FAQ | 2026-05-11 | "Redfish interface from the RMC enables the HPE tools to manage the system". 표준 RESTful API over HTTPS. |
| 5 | (WebSearch 인용 / scribd) | CSUS 3200 Overview / Technical White Paper | 2026-05-12 | "Because HPE has been working with the industry on the Redfish standard since its inception, it already supports large, partitionable systems managed by a single aggregated controller like HPE Compute Scale-up Server 3200 RMC". "supports full nPar (Partitioning). An nPartition is a set of HPE Compute Scale-up Server chassis defined to work together to form a single computer system". |
| 6 | https://community.hpe.com/t5/servers-general/impossible-to-get-redfish-answer-from-superdome-flex-rmc/td-p/7200359 | HPE community 위험 신호 | 2026-05-12 | 사용자 보고: ServiceRoot 호출 시 "Error getting service root, aborting". HPE Pro 근본 원인 미확정 — reference doc a00119177en_us 만 제시. → 사이트 RMC Redfish 비활성화 / 라이선스 부재 가능성. 본 server-exporter `diagnosis.details.rmc_activation_check` 메타로 진단 hint. |
| 7 | https://itpfdoc.hitachi.co.jp/manuals/rv3000/hard/SDF/Server/SDF280/P06150-401a.pdf | HPE Superdome Flex Server Admin Guide P06150-401a | 2026-05-12 | WebFetch PDF binary 디코딩 실패 — Hitachi-hosted Superdome Flex 280 Admin Guide. lab 도입 시 본 PDF text 추출 + 정정 의무. |
| 8 | https://github.com/HewlettPackard/sdflexutils | sdflexutils 1.5.1 (Partition0 명시) | 2026-05-12 | Systems ID 패턴 `/redfish/v1/Systems/Partition<N>` 명시. mock fixture 합성 base. |

### 외부 계약 추정 (lab 부재 — 사이트 실측 시 정정)

| 항목 | 추정 | 근거 | 정정 의무 |
|---|---|---|---|
| ServiceRoot.Product | "Compute Scale-up Server 3200" (CSUS) / "Superdome Flex" (Flex 280) | sdflexutils + Superdome Flex Admin Guide | NEXT_ACTIONS C5 |
| Managers Member IDs | RMC / PDHC0 / PDHC1 / Bay1.iLO5 | Superdome Flex Admin Guide + sdflexutils GitHub README | NEXT_ACTIONS C6 |
| Systems Member IDs | Partition0 / Partition1 / Partition2 | sdflexutils 1.5.1 | NEXT_ACTIONS C6 |
| Chassis Member IDs | Base / Expansion1 / Expansion2 (최대 4) | HPE psnow doc/a50009596enw + DMTF Chassis v1.20 | NEXT_ACTIONS C6 |
| Oem.Hpe.PartitionInfo schema | `{PartitionId, PartitionName, NumNodes, NumSockets, ...}` | sdflex-ironic-driver wiki + sdflexutils 1.5.1 | NEXT_ACTIONS C7 |
| RMC firmware 형식 | `^[34]\.[0-9]+\..*` (CSUS RMC 3.x/4.x) / `^[23]\.[0-9]+\..*` (Superdome Flex RMC 2.x/3.x) | adapter origin 추정 | NEXT_ACTIONS C8 |
| RMC 활성화 요구 | Subscription License + RMC Web GUI enable | community 7200359 + `docs/reference/compatibility-matrix.md` | NEXT_ACTIONS C8 |

### server-exporter 적용 (cycle 2026-05-12)

- `redfish-gather/library/redfish_gather.py` — `_resolve_all_member_uris` / `gather_*_multi` / `_collect_multi_node_topology` / `_classify_rmc_label` 신설 (Additive). `gather_bmc` 에 `manager_layout` 옵션 인자.
- `data.multi_node` Additive envelope 컨테이너 — `enabled` / `layout` / `summary` / `partitions[]` / `managers[]` / `chassis[]`.
- `diagnosis.details.multi_node_layout` + `rmc_activation_check` Additive 메타.
- adapter `vendor_notes.manager_layout` 정의 vendor 만 활성 — 기타 13 vendor 영향 0 (Additive only).
- mock fixture `tests/fixtures/redfish/hpe_csus_3200/` 7 파일 합성 (3-partition × 4-manager × 3-chassis).

---

## 일자: 2026-05-11 (cycle adapter-selection-review — Supermicro AST2500/AST2600 firmware 형식 web sources)

> 사용자 명시 검증 요청 ("어떤 adapter 를 쓸지 결정하는 단계 문제 발생 이력 — 지금 잘 돼있나") 후속.
> Phase 2 (firmware_patterns 추가) 는 **보류** — lab 부재 + web sources 가설 부정확 위험. NEXT_ACTIONS 등재.

### Supermicro X11~X14 BMC firmware 형식 — web sources 7건

| # | source URL | 영역 | 확인일 |
|---|---|---|---|
| 1 | https://www.supermicro.com/manuals/other/RedfishUserGuide.pdf | Supermicro Redfish User Guide 6.1 — X12+ Redfish 표준 명시 | 2026-05-11 |
| 2 | https://www.supermicro.com/manuals/superserver/IPMI/IPMI_Users_Guide_X11.pdf | X11 IPMI Users Guide — AST2500 BMC firmware 패턴 | 2026-05-11 |
| 3 | https://www.supermicro.com/manuals/other/BMC_Users_Guide_X12_H12.pdf | BMC Users Guide X12/H12 1.0a — AST2600 BMC | 2026-05-11 |
| 4 | https://www.supermicro.com/manuals/other/BMC_IPMI_X13_H13_B13.pdf | BMC IPMI X13/H13/B13 Manual 1.0b — AST2600 동일 | 2026-05-11 |
| 5 | https://www.supermicro.com/manuals/other/BMC_IPMI_X14_H14.pdf | BMC IPMI X14/H14 Manual 1.1 — AST2600 + Redfish 1.21.0 / schema bundle 2024.3 | 2026-05-11 |
| 6 | https://ftp.abacus.cz/support/FW/MB/SUPERMICRO/IPMI/X12_AST2600_ROT-5101_beta/ReleaseNote-X12_64M_ROT_AST26_0103.txt | X12 AST2600 ROT release note — firmware "01.03.03" 사례 명시 | 2026-05-11 |
| 7 | https://www.supermicro.com/manuals/other/redfish-ref-guide-html/Content/general-content/firmware-inventory-update-service.htm | Firmware Inventory and Update Service 명세 | 2026-05-11 |

### 외부 계약 추정 (lab 부재 — 사이트 실측 시 정정 의무)

| 영역 | 추정 (web sources 기반) | 근거 |
|---|---|---|
| X11/H11 BMC chip | AST2500 | source 2 |
| X12+ (X12/H12/X13/H13/B13/X14/H14) BMC chip | AST2600 | source 3, 4, 5 |
| X11 firmware 형식 | 3-part `X.YY.ZZ` (예: `1.73.10`) 또는 2-part `X.YY` 구펌웨어 | source 2 |
| X12+ firmware 형식 | 3-part `0?1.YY.ZZ` (예: `01.03.03`) | source 6 (release note 직접 명시) |
| Manufacturer string | "Supermicro" / "Super Micro Computer, Inc." | 기존 adapter (X11~X14) 동일 |
| Manager URI | `/redfish/v1/Managers/1` | source 1, 5 |
| OEM namespace | `Oem.Supermicro` | source 1 |

### Phase 2 (firmware_patterns 추가) 보류 결정 근거 (cycle 2026-05-11)

본 cycle 검증 결과 firmware_patterns 추가는 다음 위험으로 보류:

1. **AST2500 vs AST2600 firmware 형식 거의 동일** — `X.YY.ZZ` vs `0X.YY.ZZ` 차이만으로는 generation 분리 정확도 약함 (X11 firmware "1.73.10" 가 X12 패턴 `^0?1\.[0-9]+\.[0-9]+` 에도 매칭)
2. **사이트 실 firmware 와 web sources 가설 차이 위험** — 미스매치 시 `match_score=-9999` (`module_utils/adapter_common.py:267`) → graceful fallback `supermicro_bmc` (priority 10) 로 떨어짐 → 잘못된 generation adapter 선택보다는 안전하지만, 잘 매칭하면 +25 보너스 + specificity +20 점수 향상 효과 있음
3. **lab 부재 영역 — rule 96 R1-A** — 실측 fixture 없이 정규식 가설은 위험 부담 큼

→ NEXT_ACTIONS 등재. 사이트 도입 후 `capture-site-fixture` skill 로 실 firmware 캡처 + 패턴 보정 별도 cycle.

### 외부 계약 변동 trigger

- Supermicro 신 generation 출시 (X15+ — H15+) — 본 카탈로그 갱신
- AST2700 (차세대 BMC chip) 도입 — firmware 형식 변경 가능성
- 사이트 실측 응답이 추정값과 다를 경우 (rule 25 R7-A-1 — 사용자 실측 > spec)

### 적용 위치

- `adapters/redfish/supermicro_x{11,12,13,14}.yml` — origin 주석 갱신 (X12 만 본 cycle 갱신, 나머지 3개는 Phase 2 진입 시)
- `adapters/redfish/supermicro_bmc.yml` — generic fallback (priority 10) 영향 0
- `tests/unit/test_supermicro_adapter_selection.py` (신규) — 회귀 차단

---

## 일자: 2026-05-11 (cycle hpe-csus-add — HPE Compute Scale-up Server 3200 web sources 등재)

> 사용자 명시 (2026-05-11): "hpe csus 장비도 개더링이 필요하다."
> Worker: AI 단일 세션. lab 부재 + web sources only (rule 96 R1-A).

### HPE Compute Scale-up Server 3200 (CSUS 3200) — web sources 7건

| # | source URL | 영역 | 확인일 |
|---|---|---|---|
| 1 | https://cdrdv2-public.intel.com/792357/FAQ%20-%20HPE%20Compute%20Scale-up%20Server%203200.pdf | RMC + 표준 Redfish API 명시 (HPE CSUS 3200 FAQ) | 2026-05-11 |
| 2 | https://www.hpe.com/psnow/doc/a50009596enw | "built on the proven HPE Superdome Flex architecture" — 아키텍처 + RAS 강조 | 2026-05-11 |
| 3 | https://buy.hpe.com/us/en/compute/mission-critical-x86-servers/compute-scale-up-servers/compute-scale-up-servers/hpe-compute-scale-up-server-3200/p/1014774076 | HPE store 제품 페이지 — 4-socket / DDR5 / Xeon SP 사양 | 2026-05-11 |
| 4 | https://servermanagementportal.ext.hpe.com/ | HPE Server Management Portal — RMC Redfish API 표준 reference | 2026-05-11 |
| 5 | https://support.hpe.com/hpesc/public/docDisplay?docId=sd00001798en_us | HPE Support — CSUS 3200 + Superdome Flex 공통 support 영역 | 2026-05-11 |
| 6 | https://redfish.dmtf.org/schemas/DSP0266_1.15.0.html | Redfish DMTF Specification v1.15 — 표준 schema | 2026-05-11 |
| 7 | https://hewlettpackard.github.io/ilo-rest-api-docs/ilo5/ | iLO 5 API Reference — Oem.Hpe namespace reference (Superdome / CSUS 공유) | 2026-05-11 |

### 외부 계약 추정 (lab 부재 — 사이트 실측 시 정정 의무)

| 영역 | 추정 | 근거 |
|---|---|---|
| Manufacturer string | "HPE" / "Hewlett Packard Enterprise" | HPE 표준 (다른 HPE adapter 동일) |
| Model string | "Compute Scale-up Server 3200" / "HPE Compute Scale-up Server 3200" / "CSUS 3200" | HPE 공식 제품명 (web sources 1, 3) |
| Manager type | RMC (Rack Management Controller) | web sources 1, 4 |
| Systems id pattern | "Partition0" / "Partition*" | Superdome Flex 상속 (web sources 2 + sdflexutils 실측 — Superdome Flex 와 동일 아키텍처) |
| RMC firmware version | 3.x ~ 4.x | Superdome Flex 2.x/3.x 후속 (lab 실측 시 정정) |
| Oem.Hpe.PartitionInfo | Systems 영역 | Superdome Flex 상속 (강한 추정 — HPE 공식 architecture 일치) |
| Oem.Hpe.FlexNodeInfo | Chassis 영역 | Superdome Flex 상속 (lab 실측 시 정정) |
| Oem.Hpe.GlobalConfiguration | Systems/Managers 영역 | Superdome Flex 상속 (lab 실측 시 정정) |

### 외부 계약 변동 trigger

- HPE RMC firmware 4.x / 5.x upgrade
- HPE 제품 모델명 표기 변경 (예: "Compute Scale-up Server 3200" → "ProLiant Compute Scale-up 3200")
- DMTF Redfish PowerSubsystem / Storage schema 신 버전 도입
- 사이트 실측 응답이 추정값과 다를 경우 (rule 25 R7-A-1 — 사용자 실측 > spec)

### 적용 위치

- `adapters/redfish/hpe_csus_3200.yml` (origin 주석 7 source URL)
- `redfish-gather/tasks/vendors/hpe/{collect,normalize}_oem.yml` (regex 확장 + source URL 갱신)

---

## 일자: 2026-05-06 (M-D2 — COMPATIBILITY-MATRIX Gap 7 / BLOCK 6 web 검증)

> 사용자 명시 (2026-05-06): "지금 추가한 코드 및 현재돼있는 코드가 지금 프로젝트에 지원하는 모든 밴더 모든 세대 모든 장비에도 지원해야해."
> Worker: Session-5. M-D1 매트릭스 240 cell 중 Gap (7) + BLOCK (6) cell 만 web 검색 보강. OK★ 167 cell 은 adapter origin 주석에 web sources 이미 보유.

### M-D1 Gap cell 별 web sources (M-D3 W1~W6 입력)

#### W1: Dell iDRAC 8 power 활성화 (1 cell)

- **현재**: `dell_idrac8.yml:18-27` capabilities.sections_supported 에 `power` 누락
- **검증 결과**: Dell iDRAC 8 (firmware 2.x/3.x) 가 PowerSubsystem 지원 — 사이트 실측 (Round 11 의 iDRAC 9 동일 path) + cycle 2026-05-01 PowerSubsystem fallback 코드 적용
- **fallback path**: `Chassis/{id}/PowerSubsystem` (DMTF v1.8+) → fallback `Chassis/{id}/Power` (legacy)
- **sources**:
  - https://developer.dell.com/apis/2978/versions/12.x/iDRAC-Redfish-API.json — PowerSubsystem 지원 (iDRAC 5.x+ 표준 명시)
  - https://redfish.dmtf.org/schemas/v1/Power.v1_8_0.json — PowerSubsystem 표준 (2020.4)
  - cycle 2026-05-01 fallback 코드 (redfish_gather.py `_gather_power_subsystem`)
- **확인 일자**: 2026-05-06

#### W2: HPE iLO 4 storage 활성화 (1 cell)

- **현재**: `hpe_ilo4.yml:18-26` capabilities.sections_supported 에 `storage` 누락
- **검증 결과**: HPE iLO 4 (firmware 2.x) 는 SimpleStorage 표준 지원. /Systems/1/Storage 가 부분 지원
- **fallback path**: `Systems/{id}/Storage` (DMTF 표준) → fallback `Systems/{id}/SimpleStorage` (Redfish 1.0/1.1)
- **sources**:
  - https://hewlettpackard.github.io/ilo-rest-api-docs/ilo4/#systems-storage — iLO 4 SimpleStorage 표준
  - https://redfish.dmtf.org/schemas/v1/SimpleStorage.v1_3_0.json — DMTF SimpleStorage spec
  - cycle 2026-05-01 fallback 코드 (A1 SimpleStorage)
- **확인 일자**: 2026-05-06

#### W3: HPE iLO 4 power 활성화 (1 cell)

- **현재**: `hpe_ilo4.yml:18-26` capabilities 에 `power` 누락
- **검증 결과**: iLO 4 가 Chassis/{id}/Power 표준 지원 (PowerSubsystem 미지원, Redfish 1.0)
- **fallback path**: `Chassis/{id}/PowerSubsystem` → fallback `Chassis/{id}/Power` (cycle 2026-05-01 A2)
- **sources**:
  - https://hewlettpackard.github.io/ilo-rest-api-docs/ilo4/#chassis-power — iLO 4 Power 표준
  - cycle 2026-05-01 fallback 코드 (A2 PowerSubsystem)
- **확인 일자**: 2026-05-06

#### W4: Lenovo IMM2 storage 활성화 (1 cell)

- **현재**: `lenovo_imm2.yml:22-30` capabilities 에 `storage` 누락
- **검증 결과**: Lenovo IMM2 (System x M5 펌웨어 1.x~2.x) 는 SimpleStorage 표준 지원
- **fallback path**: A1 SimpleStorage 동일 (W2 HPE iLO 4 와 같은 fallback)
- **sources**:
  - https://pubs.lenovo.com/imm2/storage_resources — IMM2 Storage 표준
  - https://github.com/Lenovo/lenovo-redfish-tool — Lenovo 공식 Redfish CLI
  - cycle 2026-05-01 fallback 코드 (A1)
- **확인 일자**: 2026-05-06

#### W5: Lenovo IMM2 power 활성화 (1 cell)

- **현재**: `lenovo_imm2.yml:22-30` capabilities 에 `power` 누락
- **검증 결과**: IMM2 가 Chassis/{id}/Power 표준 지원 (PowerSubsystem 미지원)
- **fallback path**: A2 PowerSubsystem 동일 (W3)
- **sources**:
  - https://pubs.lenovo.com/imm2/power_resources — IMM2 Power 표준
  - cycle 2026-05-01 fallback 코드 (A2)
- **확인 일자**: 2026-05-06

#### W6: 4 신규 vendor `users` capability 정정 (4 cell)

- **현재**: `huawei_ibmc.yml:48` / `inspur_isbmc.yml:46` / `fujitsu_irmc.yml:48` / `quanta_qct_bmc.yml:50` 의 capabilities.sections_supported 에 `users` 명시
- **검증 결과**: `schema/sections.yml` 의 `users` 섹션 channels = `[os]` — Redfish 채널 미해당. drift (CONVENTION_DRIFT 후보)
- **fix path**: 4 adapter 의 capabilities.sections_supported 에서 `users` 라인 제거
- **sources**: `schema/sections.yml:N` — sections.yml 정본 (channels 정의)
- **확인 일자**: 2026-05-06

### M-D1 BLOCK cell (Supermicro X9 — 6 cell)

#### Supermicro X9 (system / hardware / bmc / cpu / memory / network) — 6 cell

- **현재**: `supermicro_x9.yml:18-25` capabilities.sections_supported 명시 (storage / firmware / power 미명시)
- **차단 사유**:
  - lab fixture 0 (`tests/baseline_v1/` 부재 + `tests/fixtures/redfish/supermicro/X9` 부재)
  - Redfish 1.0/1.1 spec 자체 부분 지원 — 응답 schema 가 vendor 마다 표준 일탈 가능
  - X9 generation 출하 종료 (Supermicro X10/X11 부터 표준 호환성 향상)
- **해소 조건**:
  - lab 도입 (capture-site-fixture skill) 또는 사이트 fixture
  - 우선 낮음 (P3)
- **sources**:
  - https://www.supermicro.com/manuals/superserver/uniprocessor/X9.cfm — X9 manuals (legacy)
  - cycle 2026-05-01 정적 분석 — supermicro_x9.yml 명시 capabilities 만 cover
- **확인 일자**: 2026-05-06

### 추가 cell 정밀 검증 (P1.1 — 신규 4 vendor 36 cell)

> 4 신규 vendor 의 OK★ 36 cell 은 cycle 2026-05-01 phase 2 adapter 추가 시 web sources 4종 origin 주석 보유. 본 ticket 추가 검증:

| vendor | sections | 검증 결과 |
|---|---|---|
| Huawei iBMC | 9 sections (users 제외) | Manager URI `/Managers/iBMC` 사이트 실측 시 정정 가능. 표준 9 sections 호환 (web sources) |
| Inspur iSBMC | 9 sections | OCP Rack-Manager 표준 호환. 표준 9 sections |
| Fujitsu iRMC | 9 sections | iRMC S5/S6 표준. PRIMERGY M5/M6/M7 호환 |
| Quanta QCT BMC | 9 sections | OpenBMC bmcweb 표준. 표준 9 sections |

→ 추가 web sources 부족 영역 0건. cycle 2026-05-01 phase 2 origin 주석 충분. 사이트 fixture 도입 시 OK 격상.

### M-D3 입력 (W1~W6 작업 분류)

| 작업 | 영향 cell | 코드 변경 | 회귀 영역 |
|---|---|---|---|
| W1 | dell_idrac8 power | `+ power` 1 줄 추가 | dell baseline 회귀 |
| W2 | hpe_ilo4 storage | `+ storage` 1 줄 추가 | hpe baseline 회귀 |
| W3 | hpe_ilo4 power | `+ power` 1 줄 추가 | hpe baseline 회귀 |
| W4 | lenovo_imm2 storage | `+ storage` 1 줄 추가 | lenovo baseline 회귀 |
| W5 | lenovo_imm2 power | `+ power` 1 줄 추가 | lenovo baseline 회귀 |
| W6 | 4 신규 vendor users 제거 | `- users` 4 곳 제거 | sections.yml channels 검증 |

→ **Additive only (rule 92 R2)** — W1~W5 는 기존 fallback 코드 활용으로 capabilities 1 라인 추가만. W6 은 drift 정정 (sections.yml 정본 우선).

### 외부 계약 변동 trigger

- DMTF Redfish v1.16+ 에서 SimpleStorage deprecation 정식 발표 시
- vendor 가 firmware upgrade 로 PowerSubsystem 신schema 도입 시
- Supermicro X9 lab 도입 시 BLOCK 해제 가능

### sources 종합 (rule 96 R1-A)

#### vendor docs (5)
- https://developer.dell.com/apis/2978/versions/12.x/iDRAC-Redfish-API.json — Dell iDRAC PowerSubsystem
- https://hewlettpackard.github.io/ilo-rest-api-docs/ilo4/ — HPE iLO 4 SimpleStorage / Power
- https://pubs.lenovo.com/imm2/ — Lenovo IMM2 Storage / Power
- https://www.supermicro.com/manuals/superserver/uniprocessor/X9.cfm — Supermicro X9 (legacy)
- https://github.com/Lenovo/lenovo-redfish-tool — Lenovo Redfish CLI

#### DMTF (2)
- https://redfish.dmtf.org/schemas/v1/Power.v1_8_0.json — PowerSubsystem 신 schema (2020.4)
- https://redfish.dmtf.org/schemas/v1/SimpleStorage.v1_3_0.json — SimpleStorage spec

#### server-exporter 정본 (3)
- `redfish-gather/library/redfish_gather.py` `_gather_power_subsystem` (cycle 2026-05-01 A2 fallback)
- `redfish-gather/library/redfish_gather.py` `_gather_simple_storage` (cycle 2026-05-01 A1 fallback)
- `schema/sections.yml` (channels 정의 정본 — W6)

---

## 일자: 2026-05-06 (M-E1 — HPE Superdome 시리즈 web 검색 + adapter spec 도출)

> 사용자 명시 (2026-05-06): "superdome 하드웨어도 벤더 추가해줘. 추가하고 web 검색 다해서 여기 개더링프로젝트에 추가해줘."
> Worker: Session-E1 (web-evidence-collector / opus). Lab: 부재 — web sources 14건 (rule 96 R1-A). 사이트 실측 시 정정 가능 (rule 25 R7-A-1).

### HPE Superdome 시리즈 매트릭스

| 모델 | 출시 | 아키텍처 | management | Redfish | server-exporter adapter |
|---|---|---|---|---|---|
| Superdome Flex 280 | 2020+ | x86 (Intel Xeon SP) | RMC + iLO 5 (per node) | YES (RMC host, 표준) | M-E2 신규 `hpe_superdome_flex.yml` (priority=95) |
| Superdome Flex | 2017+ | x86 (Intel Xeon SP) | eRMC/RMC + iLO 5 (per compute module) | YES (RMC host, 표준) | M-E2 동일 adapter cover |
| Superdome 2 | 2010~2017 | Itanium / IA-64 | OA (Onboard Administrator) | NO (legacy) | `redfish_generic.yml` fallback |
| Superdome X | 2014~ | x86 (Xeon E7) | iLO 4 + OA | 부분 (iLO 4) | `hpe_ilo4.yml` (priority=50) fallback |
| Integrity Superdome | ~2010 | Itanium | OA only | NO | `redfish_generic.yml` (N/A) |

### Superdome Flex Redfish endpoint 매트릭스

| Endpoint | 일반 iLO 5 (ProLiant) | Superdome Flex | 시그니처 / 비고 |
|---|---|---|---|
| ServiceRoot | `/redfish/v1/` | `/redfish/v1/` (RMC host) | RMC IP = redfish_address |
| Systems collection | `/redfish/v1/Systems/1` (단일) | `/redfish/v1/Systems/Partition0`, `Partition1`, ... | **Multi-partition (nPAR)** — sdflexutils 실측 |
| Chassis | `/redfish/v1/Chassis/1` | `/redfish/v1/Chassis/<chassis_id>` | Base + Expansion (최대 8 chassis) |
| Managers | `/redfish/v1/Managers/1` | `/redfish/v1/Managers/<RMC_id>` + per-node iLO 5 | **Dual-manager** — RMC primary |
| FirmwareInventory | 표준 | 표준 + complex/nPar firmware bundles | sdflex-ironic-driver wiki 명시 |
| OEM 키 | `Oem.Hpe` | `Oem.Hpe` | HPE 표준 namespace 재사용 |

### Manufacturer / Vendor 시그니처 (추정 — lab 부재)

| 위치 | 값 | 근거 |
|---|---|---|
| ServiceRoot.Vendor (v1.5+ 표준) | `"HPE"` (추정 — 일반 iLO 5 동일) | sdflexutils PyPI 표기 |
| ServiceRoot.Product (v1.3+ 표준) | `"iLO 5"` 또는 `"Superdome Flex"` (RMC 응답 시) | 펌웨어 별 차이 — 사이트 실측 시 확정 |
| Chassis.Manufacturer | `"HPE"` 또는 `"Hewlett Packard Enterprise"` | sdflexutils 명시 |

→ 기존 `common/vars/vendor_aliases.yml` HPE 매핑 (`["HPE", "Hewlett Packard Enterprise", "Hewlett-Packard", "HP"]`) 으로 정규화 정상 동작 예상. 별도 alias 추가 불필요.

### M-E1 결론

- **결정 (F)**: **(a) HPE sub-line** — `adapters/redfish/hpe_superdome_flex.yml` 신규 (priority=95, iLO 5 90 < Superdome Flex 95 < iLO 6 100)
- **별도 vendor 거절 사유**: Manufacturer string 충돌 + vendor_aliases 정규화 모호 (rule 12 R1 위반 위험)
- **OEM 재사용**: `redfish-gather/tasks/vendors/hpe/` 그대로 (Oem.Hpe 동일 namespace)
- **vault 재사용**: `vault/<loc>/redfish/hpe.yml` 그대로 (별도 vault 불필요)
- **한계**: Multi-partition 시 첫 partition (`Partition0`) 만 수집. 전체 partition 수집은 별도 cycle (server-exporter 현재 Systems Members[0] 단일 진입 패턴).

### 외부 계약 변동 trigger

- HPE 가 Superdome Flex 후속 모델 출시 시 (Superdome Flex Gen11 등 — 향후)
- Superdome Flex 의 ServiceRoot.Vendor / Product 값이 펌웨어 별 차이 사이트 실측 발견 시
- nPAR / Partition 전용 OEM extension (Oem.Hpe.Partition*) 키 식별 시

### sources (rule 96 R1-A — 14건)

#### vendor docs (6)
- https://support.hpe.com/hpesc/public/docDisplay?docId=a00119177en_us — Remote management with Redfish (Superdome Flex)
- https://support.hpe.com/hpesc/public/docDisplay?docId=sf000075513en_us — Superdome Flex Redfish API
- https://hewlettpackard.github.io/ilo-rest-api-docs/ilo5/ — iLO 5 API reference
- https://www.hpe.com/us/en/collaterals/collateral.a00026242enw.html — Superdome Flex QuickSpecs
- https://itpfdoc.hitachi.co.jp/manuals/rv3000/hard/SDF/Server/SDF280/P06150-401a.pdf — Admin Guide PDF
- https://servermanagementportal.ext.hpe.com/docs/concepts/gettingstarted — HPE Server Management Portal

#### DMTF (2)
- https://redfish.dmtf.org/schemas/DSP0266_1.15.0.html — Specification v1.15
- http://redfish.dmtf.org/schemas/DSP0266_1.5.0.html — Specification v1.5 (Vendor 표준화 시점)

#### GitHub / Community (6)
- https://github.com/HewlettPackard/sdflexutils — HPE 공식 라이브러리
- https://github.com/HewlettPackard/sdflex-ironic-driver — OpenStack Ironic driver
- https://github.com/HewlettPackard/sdflex-ironic-driver/wiki — Wiki (Partition0 명시)
- https://pypi.org/project/sdflexutils/ — sdflexutils 1.5.1 (2022-11-29)
- https://thelinuxcluster.com/2020/05/06/upgrading-firmware-for-super-dome-flex/ — RMC firmware 3.10.164 release
- https://github.com/HewlettPackard/ilo-rest-api-docs/blob/master/source/includes/_ilo5_adaptation.md — iLO 5 adaptation

---

## 일자: 2026-05-06 (F50 phase 3 — 전 vendor 호환성 매트릭스 + Dell BMC OEM 추출)

### AccountService POST/PATCH vendor 매트릭스 (web sources + 사이트 실측)

> 사용자 지적: "되는데 안된다고 적혀있어서 안되는게 더 있는지 확인". 전 9 vendor 점검.

| Vendor | 패턴 | 비고 | source |
|---|---|---|---|
| Dell iDRAC | PATCH-only (slot 1-17) | POST 미지원, slot 1 anonymous | dell.com manageraccount + 사이트 실측 |
| HPE iLO | 표준 POST + Oem.Hpe.Privileges retry | RoleId 충분 | servermanagementportal.ext.hpe.com |
| Lenovo XCC | 표준 POST + PasswordChangeRequired retry | XCC 권한 분리 (note 1) | pubs.lenovo.com/xcc-restapi |
| Supermicro | 표준 POST | password complexity 엄격 | supermicro.com Redfish User Guide |
| Cisco CIMC | POST with `Id` (1-15) | RoleId enum: admin/user/readonly/SNMPOnly | cisco.com REST API guide + 실측 |
| Huawei iBMC | 표준 POST | OEM extension 가능 | support.huawei.com creating-a-user |
| Inspur ISBMC | 표준 POST | OCP Rack-Manager 참여 | github.com/opencomputeproject/Rack-Manager |
| Fujitsu iRMC | 표준 POST | PRIMERGY 표준 | github.com/fujitsu/iRMCtools |
| Quanta QCT | 표준 POST | knusbaum.org "tested on Quanta" | knusbaum.org Redfish Idiosyncrasies |

> note 1: Lenovo XCC 의 Administrator role 이라도 OemPrivileges (Supervisor) 미부여 시
> /Managers AccessDenied 발생 가능. ManagerAccount level OemPrivileges PATCH 거부됨
> (`PropertyUnknown` — Role level 만 정의). 운영 시 USERID 우회 또는 별도 권한 부여.

### "되는데 안 된다고 분류" 정정 매트릭스

| 케이스 | 이전 분류 | 정정 후 | 영향 |
|---|---|---|---|
| Cisco AccountService POST | not_supported | 지원 (Id + RoleId enum) | F50 phase 1 코드 fix |
| Dell Manager.Oem.Dell.DelliDRACCard | gather_bmc 미추출 | oem.idrac_* 4 필드 emit | F50 phase 3 코드 fix |
| 신규 vendor 4종 표준 POST | unverified | 표준 POST 가정 명시 | adapter metadata |

### Dell Manager.Oem.Dell.DelliDRACCard 구조 (사이트 실측 10.100.15.27 iDRAC9 7.10.70.00)

```json
{
  "@odata.type": "#DellManager.v1_4_0.DellManager",
  "DelliDRACCard": {
    "@odata.type": "#DelliDRACCard.v1_1_0.DelliDRACCard",
    "IPMIVersion": "2.0",
    "LastSystemInventoryTime": "2025-12-07T10:47:13+00:00",
    "LastUpdateTime": "2026-05-06T08:18:46+00:00",
    "URLString": "https://10.100.15.27:443"
  },
  "RemoteSystemLogs": {...}
}
```

server-exporter envelope: `data.bmc.oem.{idrac_ipmi_version, idrac_last_inventory_time, idrac_last_update_time, idrac_url}`

---

## 일자: 2026-05-06 (F50 — Cisco CIMC AccountService 표준 지원 확인 + infraops 통일)

### Cisco CIMC AccountService 사이트 실측 (10.100.15.2, AccountService.v1_6_0)

> source: 사이트 실측. 이전 cycle 의 'not_supported' 결론 정정 — Members=1 만 보고 잘못 분류했었음.

| 동작 | 결과 | 시그니처 |
|---|---|---|
| GET /AccountService | 200 + AccountService.v1_6_0 | 표준 |
| GET /Accounts | 200 + Members 1 (admin) | 표준 |
| POST /Accounts (표준 body) | HTTP 400 | 'Id' 필드 1-15 필수 (vendor-specific) |
| POST /Accounts (Id='2' + RoleId='Administrator') | HTTP 400 | 'Administrator' Cisco enum 거부 |
| POST /Accounts (Id='2' + RoleId='admin') | **HTTP 201** | 정상 생성 |
| auth as new infraops/__REDACTED__Infra | HTTP 200 | 인증 통과 |
| GET /AccountService/Roles | 200 + admin/user/readonly/SNMPOnly | Cisco enum |

### F50 server-exporter 대응

- vendor='cisco' 분기에 `Id` 필드 자동 추가 (slot 2-15 빈 Id 자동 검색)
- RoleId mapping: Administrator → admin / Operator → user / ReadOnly → readonly
- 이전 not_supported early-return 제거

### infraops 공통계정 password 통일 (사용자 명시)

5 vault 모두 `__REDACTED__Infra` (15자, Dell Strengthen Policy 호환):
- vault/<loc>/redfish/dell.yml (cycle 2026-05-06 1차 갱신)
- vault/<loc>/redfish/hpe.yml (cycle 2026-05-06 2차)
- vault/<loc>/redfish/lenovo.yml (cycle 2026-05-06 2차)
- vault/<loc>/redfish/cisco.yml (cycle 2026-05-06 2차)
- vault/<loc>/redfish/supermicro.yml (cycle 2026-05-06 2차)

5 BMC 모두 infraops/__REDACTED__Infra HTTP 200 검증 완료.

---

## 일자: 2026-05-06 (F49 — Dell iDRAC9 AccountService PATCH 동작 매트릭스 추가)

### Dell iDRAC9 AccountService 사이트 실측 (10.100.15.27 / 10.100.15.31, 펌웨어 7.10.70.00)

> source: 사이트 실측 (rule 25 R7-A-1 사용자 실측 우선) + Dell SWC0296 응답 코드 + Security Strengthen Policy.

| 동작 | 결과 | 시그니처 |
|---|---|---|
| GET /AccountService | 200 + 16 슬롯 collection | 표준 |
| GET /AccountService/Accounts/1 | UserName='', Enabled=false, RoleId='None' | **anonymous reserved slot** |
| GET /AccountService/Accounts/2 | UserName='root', Enabled=true | 기본 admin |
| PATCH /Accounts/1 (UserName, Password) | HTTP 400 AccessDenied | slot 1 PATCH 거부 |
| PATCH /Accounts/3 (UserName + Password 동시) | HTTP 200 OK | UserName set 됨 |
| PATCH /Accounts/3 (Password=10자) | HTTP 200 OK + **silent fail** | password 미적용 (인증 401) |
| PATCH /Accounts/3 (Password=15자) | HTTP 200 OK + 정상 | Security Strengthen Policy 통과 |
| PATCH /Accounts/3 (RoleId only, 빈 슬롯) | HTTP 400 SWC0296 | "user name or password is blank" |
| PATCH /Accounts/3 (Enabled+RoleId, password 미적용 상태) | HTTP 400 SWC0296 | password silent fail 의 후속 시그널 |

### F49 server-exporter 대응

- `account_service_find_empty_slot()` 에 `skip_slot_ids={'1'}` 적용 (Dell 한정)
- Dell PATCH 후 `_get('Systems', target_user, target_pass)` 로 실 인증 verify
- silent fail 감지 시 다음 빈 슬롯으로 자동 fallback (최대 3 슬롯)
- vault `__REDACTED__` (10자) → `__REDACTED__Infra` (15자) 강화

### 외부 계약 변동 trigger

- Dell iDRAC 펌웨어 8.x 출시 시 Security Strengthen Policy 변경 가능
- HPE iLO 7 / Lenovo XCC4 출시 시 password policy 표준화 가능

---

## 일자: 2026-04-30 (vendor detection robustness — Lenovo XCC2/XCC3 namespace prefix + BMC product hints + TLS legacy 호환) / 2026-04-30 (probe HTTP status_code 정합 매트릭스 추가) / 2026-04-28 (cycle-006 + full-sweep)

## ServiceRoot vendor detection — DMTF 표준 + vendor 동작 (2026-04-30 추가)

> 출처: [DSP0266 v1.15.0](https://redfish.dmtf.org/schemas/DSP0266_1.15.0.html), [DSP2046](https://www.dmtf.org/sites/default/files/standards/documents/DSP2046_2022.3.html), HPE/Lenovo/Dell/Cisco vendor 공식 문서.

### DMTF Redfish ServiceRoot 표준 필드 (top-level)
- `Vendor` 필드: ServiceRoot **v1.5.0+** 부터 표준 (str)
- `Product` 필드: ServiceRoot **v1.3.0+** 부터 표준 (str)
- `Manufacturer`는 ServiceRoot에 **없음** — Chassis/Managers/System 리소스에 표준
- `Oem` 객체: 표준 (vendor namespace 규약은 reverse-DNS 권장이지만 단순 vendor명도 허용)
- 무인증 접근 의무: `Services shall not require authentication to retrieve the service root and /redfish resources`

### Vendor별 ServiceRoot 동작 매트릭스

| Vendor | Oem 키 | Product 시그니처 | Vendor 필드 | Name 필드 | 비고 |
|---|---|---|---|---|---|
| Dell iDRAC9 5.x+ | `Oem.Dell` | "Integrated Dell Remote Access Controller" | "Dell Inc." (펌웨어별) | "Root Service" | v1.3+ ServiceRoot |
| HPE iLO5/6 | `Oem.Hpe` | "iLO 5" / "ProLiant" | "HPE" (iLO5 2.x+) | "Root Service" | iLO4는 `Oem.Hp` (legacy) |
| Lenovo XCC | `Oem.Lenovo` | "XClarity Controller" | "Lenovo" (펌웨어별) | "Root Service" | 표준 |
| Lenovo XCC2/XCC3 | **`Oem.Lenovo_xxx`** (namespace prefix) | "XClarity Controller" / "ThinkSystem" | 펌웨어별 | "Root Service" | namespace prefix 펌웨어 多 |
| Supermicro AMI MegaRAC | `Oem.Supermicro` 또는 부재 | "AMI MegaRAC SP" | 펌웨어별 | 펌웨어별 | X11/X12 펌웨어별 차이 |
| Cisco CIMC | Oem 부재인 펌웨어 多 | "Cisco UCS" / "CIMC" | 펌웨어별 | **"Cisco RESTful Root Service"** | Name 의존 |

### 구버전 펌웨어 (ServiceRoot v1.0~1.4)

- `Vendor` / `Product` 표준 필드 자체 부재
- 매칭 가능 단서: `Oem` 키, `Name` 필드, Manufacturer (Chassis/Managers fallback)
- 영향 BMC: 구 iDRAC7/8 펌웨어, iLO 4, IMM2

### server-exporter 매칭 알고리즘 (`redfish_gather._detect_vendor_from_service_root`)

1. **Oem 정확 매칭** — `Oem.{vendor}` 키 정확 매칭 (vendor_aliases.yml + _FALLBACK_VENDOR_MAP)
2. **Oem namespace prefix** — `{alias}_xxx` / `{alias}.xxx` (cycle 2026-04-30 추가, Lenovo XCC2/XCC3 호환)
3. **Vendor 필드 정확 매칭** (v1.5+ 표준)
4. **Product 필드 부분 일치** + `_BMC_PRODUCT_HINTS` (idrac/ilo/proliant/xclarity/thinksystem/xcc/imm2/megarac/cimc/ucs)
5. **Name 필드 부분 일치** + `_BMC_PRODUCT_HINTS` (Cisco "Cisco RESTful Root Service" catch)
6. 모두 fail → `None` (호출자가 unknown 처리)

### 적용 완료 (cycle 2026-04-30)

- **G1**: Oem 정확 매칭 + namespace prefix 매칭 (`Lenovo_xxx`, `Hpe_iLO` 등 호환)
- **G2**: `_BMC_PRODUCT_HINTS` 도입 — Product/Name 필드에 idrac/ilo/proliant/xclarity/thinksystem/xcc/imm2/megarac/cimc/ucs 매칭
- **G3**: ServiceRoot vendor=unknown 시 Chassis → Managers → Systems 의 Manufacturer fallback 순회
- **G4**: TLS legacy renegotiation + `DEFAULT@SECLEVEL=0` (verify=False 한정)
- **G5**: probe_redfish — payload=None (URLError/timeout/SSLError) 시 1초 backoff + 1회 retry
- **G6**: 401/403 응답의 `WWW-Authenticate: Basic realm="..."` 헤더에서 vendor hint (마지막 fallback)
- **G7**: Vendor 필드 — 정확 매칭 (원형 + trailing dot 제거 두 형식) + substring 매칭으로 보강 (`Dell Inc.`, `Cisco Systems Inc.` 등)

## TLS handshake 호환성 (2026-04-30 추가)

> 출처: Python 3.12 changelog (OpenSSL 3.x), CVE-2023-0286 / CVE-2009-3555 컨텍스트.

### 문제

- Python 3.12 + OpenSSL 3.x default `ssl.create_default_context()`:
  - TLS 1.2 미만 / weak cipher / legacy renegotiation **차단**
  - 구 BMC (HPE iLO4, Lenovo IMM2, 일부 iDRAC7/8 펌웨어) handshake 실패
  - precheck Stage 3 → URLError → "Redfish 미지원" 오판정 (curl `-k`는 통과)

### 해결 (cycle 2026-04-30)

`precheck_bundle._build_ssl_context` + `redfish_gather._ctx` 둘 다 verify=False 시:

```python
if hasattr(ssl, 'OP_LEGACY_SERVER_CONNECT'):
    ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
try:
    ctx.set_ciphers('DEFAULT@SECLEVEL=0')
except ssl.SSLError:
    pass
```

- 적용 영역: **verify=False 한정** (사내 BMC self-signed 망)
- 보안 trade-off: verify=True (운영 외 환경 — 본 시스템에선 미사용) 시 영향 없음
- curl `-k` 와 동등한 관용성

## HTTP status_code → protocol_supported 정합 매트릭스 (2026-04-30 추가)

> precheck Stage 3 (probe_*) 및 본 수집 endpoint 호출 시 의미. 200 외 응답이 모두 fail 이 아니라는 외부 계약. 본 매트릭스는 5 commits (c23d185f / 31178f8c / a60e42b5 / 6ea2c292 / 9d5c957b) 의 root reference.

> **[WARN] 2026-08-10 정정 — precheck Stage 3 는 더 이상 status 로 판정하지 않는다.**
> 아래 세 매트릭스는 **본 수집(gather) 단계의 status 해석**으로만 유효하다. Protocol Probe
> (precheck Stage 3)는 status whitelist 를 전부 제거하고 **응답 본문의 구조**로 판정한다.
>
> | 채널 | 현재 판정 근거 | 도입 |
> |---|---|---|
> | Redfish | `/redfish/v1/` 본문이 ServiceRoot 인가 (`@odata.type` `#ServiceRoot.` + `@odata.id` + `RedfishVersion`) | Phase 4-A |
> | vSphere | `/sdk` 에 vim25 `RetrieveServiceContent` POST → `RetrieveServiceContentResponse`/`about`(apiType·apiVersion), 또는 `urn:vim25`·`urn:internalvim25` Fault | Phase 4-B |
> | WinRM | `/wsman` 에 WS-Management Identify POST → `IdentifyResponse` 네임스페이스 검증 | Phase 3-B |
>
> `requires_auth_at_root` probe fact 는 Redfish(4-A)·vSphere(4-B)에서 모두 제거됐다.
> HTTP 401/403 은 어느 채널에서도 `auth_success` 를 바꾸지 않는다.

### Redfish ServiceRoot (`GET /redfish/v1/`)

| status_code | 의미 | server-exporter 처리 | 발생 BMC 예시 |
|---|---|---|---|
| 200 | 정상 무인증 응답 (표준) | protocol_supported=True, JSON 추출 | Dell iDRAC 9 5.x+, HPE iLO5 표준, Lenovo XCC, Supermicro |
| 401 | 인증 필요 (보안 강화 펌웨어) | protocol_supported=True, requires_auth_at_root=true | HPE iLO5/6 일부 펌웨어, Lenovo XCC 일부 |
| 403 | IP 화이트리스트 / 권한 부족 | protocol_supported=True, requires_auth_at_root=true | 관리망 제한 환경 |
| 404 | path 자체 없음 = 진짜 미지원 | protocol_supported=False | Redfish 미지원 BMC |
| 500 | BMC 내부 오류 (응답 깨짐) | protocol_supported=False | 펌웨어 버그 |
| 503 | 일시 과부하 / 부팅 직후 | protocol_supported=True (재시도 가능) | BMC 재시작 직후 / 일시 과부하 |
| timeout | 응답 무 | protocol_supported=False | 네트워크 / BMC 다운 |
| SSL fail | TLS 호환성 | protocol_supported=False | 구형 BMC TLS 1.0만 |

### vSphere `/sdk` — **Phase 4-B(2026-08-10) 이후 계약**

precheck Stage 3 는 `POST https://{ip}:443/sdk` 로 vim25 `RetrieveServiceContent` 를 보낸다
(비인증). `GET /sdk` 의 status whitelist(200/301/302/401/403/404/405/500/503)는 **제거**됐다.

| 요청 요소 | 값 | 근거 |
|---|---|---|
| Method / Path | `POST /sdk` | pyVmomi `SoapStubAdapter` 기본 path |
| Body | `<RetrieveServiceContent xmlns="urn:vim25"><_this versionId="6.0" type="ServiceInstance">ServiceInstance</_this></RetrieveServiceContent>` | 설치본 pyVmomi 9.x `SerializeRequest` 결과와 **바이트 동일** |
| Content-Type | `text/xml; charset=UTF-8` (SOAP 1.1) | pyVmomi `InvokeMethod` 헤더 |
| SOAPAction | `"urn:vim25/6.0"` | 〃 / govc `GOVC_VIM_VERSION` 기본값 6.0 |
| 인증 | **없음** — `RetrieveServiceContent` privId = `System.Anonymous` | pyVmomi typeinfo 실측 + Broadcom vSphere WS API 문서 |
| Retry | 없음 (요청 1회) | Phase 4-B 에서 추가하지 않음 |

| 응답 | protocol_supported | 비고 |
|---|---|---|
| `{urn:vim25}RetrieveServiceContentResponse` → `returnval` → `about`(apiType·apiVersion 존재) | **true** | 정상 경로. `about` 은 API 2.0 부터 ServiceContent 필수 필드 |
| SOAP Fault + detail 요소가 `urn:vim25` / `urn:internalvim25` | **true** | vSphere 자신이 만든 구조화 Fault = endpoint 존재 증거 |
| 일반 HTML / JSON / XML / 일반 SOAP / 일반 SOAP Fault | **false** | status 와 무관 |
| HTTP 200/301/302/401/403/404/405/500/503 **만** | **false** | status 는 Evidence 이지 Protocol Identity 가 아님 |
| timeout / TLS fail / 본문 없음 | **false** | 원본 오류를 `errors[].detail` 로 보존 |

`auth_success` 는 어떤 응답에서도 바뀌지 않는다(`null` 유지). 자격 확인은
`esxi-gather/tasks/try_credentials.yml` 이 계속 담당한다.

> ESXi 는 standalone host agent 라 `about.apiType = HostAgent`, vCenter 는 `VirtualCenter` 다.
> 본 Probe 가 증명하는 것은 "vSphere Web Services API 존재" 이며, 대상이 standalone ESXi 인지는
> `vmware_host_facts`(esxi_hostname 미지정) 호출 계약이 계속 강제한다.

### WinRM `/wsman` (`GET https://{ip}:5986/wsman`)

| status_code | 의미 | server-exporter 처리 |
|---|---|---|
| 200 | 정상 응답 | OK |
| 401 | 인증 필요 (WinRM 표준) | OK |
| 403 | SPN 불일치 / 잠긴 계정 | OK (서비스 살아있음) |
| 405 | GET 메서드 미지원 (정상 — POST(SOAP) 본 수집) | OK |
| 503 | IIS 재시작 중 | OK (재시도) |
| 404 / connection refused | 진짜 WinRM 미지원 | fail |

### Storage Controllers fetch (`GET /redfish/v1/Systems/<id>/Storage/<sid>/Controllers`)

본 endpoint 는 인증 후 호출. 401/403/503 은 권한 부족 / 일시 상태 → controller_fetch_status 메타 + errors[] 누적 (a60e42b5 fix). 빈 dict 만 반환하지 않음.

### timeout 정책

| 단계 | 기본값 | 비고 |
|---|---|---|
| precheck Stage 1+2 (TCP) | 3.0s | 빠른 차단 |
| precheck Stage 3 (protocol) | **15.0s** (이전 6.0s) | 노후 BMC 응답 시간 대응 (31178f8c) |
| precheck Stage 4 (auth) | 8.0s | |
| 본 수집 (redfish_gather) | 30s | site.yml `_rf_timeout` |

### 위 매트릭스의 운영 의미

이전 구현 (2026-04-30 이전)은 200 외 응답을 모두 fail로 분류 → 인증 강화 BMC / vCenter SSO / 일시 과부하 환경에서 false negative 빈발. 본 매트릭스가 정본.

## Redfish API

### ServiceRoot 진입

| Endpoint | 용도 | 인증 |
|---|---|---|
| GET /redfish/v1/ | ServiceRoot (Manufacturer 추출) | 무인증 |

### 핵심 Resource

| Path 패턴 | 섹션 매핑 | 비고 |
|---|---|---|
| /redfish/v1/Chassis | hardware (vendor / model / serial) | OEM 별로 path 차이 |
| /redfish/v1/Systems | system / cpu / memory | summary fields |
| /redfish/v1/Systems/<id>/Storage | storage (controllers) | iDRAC9 5.x+ 표준 |
| /redfish/v1/Systems/<id>/Storage/<sid>/Drives | storage (drives) | NAA id |
| /redfish/v1/Systems/<id>/Storage/<sid>/Volumes | storage (volumes) | iDRAC9 5.x+ 표준, 구 펌웨어는 OEM only |
| /redfish/v1/Managers | bmc | iDRAC / iLO / XCC / CIMC |
| /redfish/v1/UpdateService/FirmwareInventory | firmware | 멤버 list |
| /redfish/v1/AccountService/Accounts | users (BMC accounts) | |
| /redfish/v1/Chassis/<id>/Power | power (PSU) | |

### Vendor별 OEM path

| Vendor | OEM 경로 |
|---|---|
| Dell | /redfish/v1/Dell/... (DellSystem 등) |
| HPE | Oem.Hp.Links.SmartStorage |
| Lenovo | 표준에 가까움 |
| Supermicro | AMI MegaRAC 기반, 표준에 가까움 |
| Cisco | UCS RAID controller OEM |

### 갱신 trigger (rule 28 #11)

- TTL 90일
- 펌웨어 업그레이드 (BMC 운영자 통보)
- BMC API path 변경 발견 (probe 결과)

## SSH (Linux gather)

- 라이브러리: paramiko (Ansible 내부)
- 인증: SSH key 또는 password (vault/<loc>/os/linux.yml)
- privilege: become_method=sudo
- Linux 2-tier: Python 3.9+ → setup/shell, 그 외 → raw

## WinRM (Windows gather)

- 라이브러리: pywinrm 0.5.0
- 인증: NTLM (도메인) / Basic (로컬, HTTPS)
- Port: 5985 (HTTP) / 5986 (HTTPS)
- Vault: vault/<loc>/os/windows.yml

## vSphere API (ESXi gather)

- 라이브러리: pyvmomi 9.0.0 + community.vmware 6.2.0
- 인증: vault/<loc>/esxi.yml (root or SSO)
- 버전 지원: 6.x / 7.x / 8.x (adapters/esxi/*.yml 분기)
- pyvmomi 호환 매트릭스: 4 버전 backward (8.0.0 → 5.x ~ 8.x)

## IPMI

- 현재 server-exporter 미사용
- 향후 Redfish 미지원 BMC fallback 검토

## callback URL

- Method: POST
- 무결성 (rule 31): 공백 / 후행 슬래시 방어 (commit 4ccc1d7)
- payload: callback_plugins/json_only.py JSON envelope (6 필드)
- 재시도: Jenkins post stage 일부

## drift 발견 시 (rule 96 R4)

3 곳 기록:
1. 본 문서 (EXTERNAL_CONTRACTS.md)
2. `FAILURE_PATTERNS.md` — `external-contract-drift` / `external-contract-unverified`
3. `CONVENTION_DRIFT.md` — DRIFT-NNN
4. 해당 adapter / 상수 origin 주석

## redfish_gather.py 실측 endpoint / field (2026-04-27 cycle-003)

`redfish-gather/library/redfish_gather.py` 실 사용 path / field:

### Endpoint 진입 순서

1. `/redfish/v1/` (ServiceRoot) — 무인증, Manufacturer 추출
2. ServiceRoot에서 `Systems`.`@odata.id` link 따라가기
3. ServiceRoot에서 `Managers`.`@odata.id`
4. ServiceRoot에서 `Chassis`.`@odata.id`
5. Systems members[0] `@odata.id` → System 본체
6. System.`EthernetInterfaces`.`@odata.id` → 각 NIC member
7. System.`Storage`.`@odata.id` → controllers / Drives / Volumes
8. Manager.`Oem.Dell.DellManager` 등 vendor OEM (분기)

### 핵심 field (모든 vendor 공통 / dot path)

| Field | 위치 | server-exporter section |
|---|---|---|
| `Manufacturer` | ServiceRoot / System / Drive / Controller / Memory / NIC | meta.vendor (정규화) + 각 섹션 vendor |
| `Model` | System / Drive / Memory / NIC | hardware / storage / memory / network |
| `SerialNumber` | System / Chassis | hardware |
| `BiosVersion` | System | hardware / firmware |
| `BIOSReleaseDate` | System | firmware |
| `ProcessorSummary.{Count, Model, ...}` | System | cpu |
| `MemorySummary.TotalSystemMemoryGiB` | System | memory |
| `EthernetInterfaces` | System | network |
| `Storage` | System | storage |
| `Drives` | Storage/{id}/Drives | storage.physical_disks |
| `Volumes` | Storage/{id}/Volumes | storage.logical_volumes |
| `CapacityBytes` / `CapacityMiB` | Drive / Volume | storage 크기 |
| `Status.{State, Health, HealthRollup}` | 모든 resource | 헬스 모니터링 |
| `Power.PowerSupplies[]` | Chassis/{id}/Power | power |
| `AverageConsumedWatts` | Power | power.consumption |
| `UpdateService/FirmwareInventory/Members[]` | UpdateService | firmware |
| `AccountService/Accounts/Members[]` | AccountService | users (BMC accounts) |

### Vendor OEM 분기 (실측)

```python
# redfish_gather.py에서 발견:
'Dell' / 'DellSystem' / 'DellVolume'  # Dell OEM
# (HPE / Lenovo / Supermicro / Cisco는 OEM 별도 처리 — adapter YAML)
```

## 실 lab 발견 — 비표준 BMC (2026-04-29 cycle-015)

cycle-015 첫 연결성 검증에서 사용자 라벨 vs 실 Manufacturer drift 1건 (DRIFT-011):

### ~~TA-UNODE-G1 RedfishVersion 1.2.0 (10.100.15.2)~~ — RESOLVED

- ~~사용자 라벨: cisco~~
- ~~실 응답: `Product='TA-UNODE-G1', RedfishVersion=1.2.0`~~
- **resolved (cycle-015)**: 사내 lab 부재 확인 → 제거. OPS-13 closed.
- 보존 이유: 표준 Cisco UCS 응답과 다른 형식 reference

### Cisco BMC 일시 장애

- 10.100.15.1 → 503 Service Unavailable
- 10.100.15.3 → timeout 5s
- 다음 일과시간 재확인 (OPS-11)

## DMTF Redfish spec 연도별 매트릭스 (F80 cycle 2026-05-01)

> 사용자 명시 (rule 96 R1-A — lab 부재 영역 web sources 4종 1개 이상). 본 매트릭스는 server-exporter 가 의존하는 외부 계약 중 DMTF 표준 진화 추적용. raw passthrough 정책 → spec 변경에 직접 영향 작음. 단 신 endpoint 추가 시 호환성 fallback 필요.

### Spec release timeline

| 연도 | Spec | 주요 변경 | server-exporter 영향 |
|---|---|---|---|
| 2018 | 1.5.0 (DSP0266) | ServiceRoot.Vendor 표준화 | adapter match 기반 |
| 2020.4 | (DSP8010) | PowerSubsystem / ThermalSubsystem 신 endpoint | F81 — power fallback 적용 (cycle 2026-05-01 A2) |
| 2024.1 | DSP8010_2024.1 | 4 신 schema, 29 update | 영향 작음 (raw passthrough) |
| 2024.4 | DSP8010_2024.4 | StorageMetrics, CDU Controls, 20 update | 영향 작음 |
| 2025.1 | DSP8010_2025.1 | 8 신 schema, 36 update, IIoT | 영향 작음 |
| 2025.2 | DSP8010_2025.2 | 추가 Update | 영향 작음 |
| 2025.4 | DSP8010_2025.4 | 최신 (2025-Q4) | 영향 작음 |

### 주요 spec sources (rule 96 R1-A)

- [DSP0266 v1.6.1](http://redfish.dmtf.org/schemas/DSP0266_1.6.1.html) — Specification
- [DSP2046 2025.1 Resource Guide](https://www.dmtf.org/sites/default/files/standards/documents/DSP2046_2025.1.pdf)
- [DSP8010 2025.2 Schema Bundle](https://redfish.dmtf.org/schemas/v1/DSP8010_2025.2.pdf)
- [DSP2064 1.1.0 Vendor Spec](https://www.dmtf.org/sites/default/files/standards/documents/DSP2064_1.1.0.pdf)
- [DSP2060 User Guide](https://www.dmtf.org/sites/default/files/standards/documents/DSP2060_1.0.0.pdf)
- [Redfish Release 2025.4](https://www.dmtf.org/content/redfish-release-20254-now-available-0)
- [Redfish Release 2025.2](https://www.dmtf.org/content/redfish-release-20252-now-available)
- [Redfish Release 2025.1](https://www.dmtf.org/content/redfish-release-20251-now-available)
- [Redfish Release 2024.4](https://www.dmtf.org/content/redfish-release-20244-now-available)
- [Redfish Release 2024.1](https://www.dmtf.org/content/redfish-release-20241-now-available)

### Vendor BMC schema bundle 매트릭스

| Vendor / Generation | Redfish version | Schema bundle | server-exporter adapter |
|---|---|---|---|
| Dell iDRAC 9 (4.x~7.x) | 1.20.1 | 2024.x | dell_idrac9.yml (priority=100) |
| Dell iDRAC 10 (1.x — Gen17 PowerEdge) | 1.21.0+ (가정) | 2024.x+ | dell_idrac10.yml (priority=120, F41 cycle 2026-05-01 신규) |
| HPE iLO 5 (Gen10/10+) | 1.13.0~1.16.0 | 8010_2022.x | hpe_ilo5.yml (priority=80) |
| HPE iLO 6 (Gen11) | 1.20.0 | 8010_2024.1 | hpe_ilo6.yml (priority=100) |
| HPE iLO 7 (Gen12) | 1.21.0+ | 8010_2024.x+ | hpe_ilo7.yml (priority=120, F47 cycle 2026-05-01 신규) |
| Lenovo XCC1 (V1) | 1.13.0+ | bundle 2022.x | lenovo_xcc.yml (priority=100, F56에서 V2/V3 좁힘) |
| Lenovo XCC2 (V2/V3) | 1.20.0 | bundle 2023.3 | lenovo_xcc.yml |
| Lenovo XCC3 (V4 — OpenBMC) | 1.17.0 | bundle 2024.3 | lenovo_xcc3.yml (priority=120, F55 cycle 2026-05-01 신규) |
| Supermicro X11 (AST2500) | 1.13.0+ | bundle 2022.x | supermicro_x11.yml (priority=100) |
| Supermicro X12/H12 (AST2600) | 1.17.0+ | bundle 2023.x | supermicro_x12.yml (priority=90, F61 cycle 2026-05-01 신규) |
| Supermicro X13/H13/B13 (AST2600 + Eagle) | 1.18.0+ | bundle 2024.x | supermicro_x13.yml (priority=100, F61 신규) |
| Supermicro X14/H14 | 1.21.0 | bundle 2024.3 | supermicro_x14.yml (priority=110, F61 신규) |
| Cisco CIMC M4 (4.1.x — lab) | 1.2.0 (구) | 미명시 | cisco_cimc.yml (priority=100) |
| Cisco CIMC M5 (4.3(2.x) — EOL) | 1.5+ | bundle 2020.x | cisco_cimc.yml |
| Cisco CIMC M6/M7 (5.x/6.x) | 1.13+ | bundle 2022.x+ | cisco_cimc.yml |
| Cisco CIMC M8 (4.3(6.x)+) | 1.17+ | bundle 2024.x | cisco_cimc.yml |
| Cisco UCS X-Series (X210c/X410c) standalone | 1.13+ | bundle 2022.x+ | cisco_ucs_xseries.yml (priority=110, F69 cycle 2026-05-01 신규) |
| Cisco UCS X-Series IMM 모드 | (Intersight cloud) | (별도 채널) | server-exporter 범위 외 |

### Endpoint 호환성 추적 (server-exporter 적용 호환 fallback)

| Endpoint | DMTF spec since | 호환성 fallback 적용 | 영향 BMC |
|---|---|---|---|
| /Storage Volumes | Redfish 1.0 (필요 1.5+) | A1 — SimpleStorage fallback | 구 iDRAC8 / 구 iLO4 / 구 IMM2 |
| /Chassis/{id}/PowerSubsystem | Redfish 2020.4 | A2 — Power fallback (gather_power_subsystem) | iDRAC9 / 신 iLO6+ / XCC3 |
| /Chassis/{id}/ThermalSubsystem | Redfish 2020.4 | (thermal 섹션 진입 시 — F81 보류) | 향후 thermal cycle 진입 시 |
| NetworkAdapters/Ports vs NetworkPorts | Redfish 1.6 (Ports) | F48 — Ports/NetworkPorts 둘 다 | iLO 6+ / Gen11+ deprecated NetworkPorts |
| /UpdateService/FirmwareInventory/{id} | Redfish 1.0 | (gather_firmware 자동 cover) | 모든 vendor |
| EnvironmentMetrics (Power/Thermal) | Redfish 2020.4 | F5 — power EnvironmentMetrics fallback | Gen11+ / 신 iDRAC9 7.x |
| /AccountService Members 미지원 | (vendor 차이) | F13 — Cisco CIMC not_supported 분류 | Cisco CIMC 4.1.x |
| OEM Action (SystemErase / ClearCMOS) | spec OEM | server-exporter 미사용 (read-only, F87) | — |

### TLS / cipher 호환 (F84 cycle 2026-05-01)

- minimum_version = TLSv1_2 (DMTF DSP0266 §10.2 + iLO 7 / Gen11 deprecated TLS 1.0/1.1)
- maximum_version = TLSv1_3 (Gen11+ / XCC3+ / X14+)
- SECLEVEL=0 (verify=False) — iLO 4 / IMM2 / 구 iDRAC 호환
- OP_LEGACY_SERVER_CONNECT (verify=False) — OpenSSL 3.x renegotiation 호환

### Read-only 보장 (F83/F87 cycle 2026-05-01)

- redfish_gather.py 는 GET only (모듈 docstring 명시)
- _post() / _patch() 는 P2 AccountService 한정 사용 (dryrun=true 기본)
- ETag / If-Match 헤더 미사용 → bmcweb #262 If-Match crash 회피
- DELETE / OEM Action 절대 호출 안 함

## 보안 advisory 등재 (F91/F125 cycle 2026-05-01 — 10R extended audit)

> 사용자 명시 (rule 96 R1-A — web sources). server-exporter 는 read-only / GET only → 직접 코드 영향은 없으나 운영 정책 / 자격증명 회전 의사결정 reference.

### F91 — CVE-2024-54085 (AMI MegaRAC BMC SPx)

- **CVSS**: 10.0 (Critical) — Authentication Bypass
- **영향 vendor**: AMI MegaRAC SPx 사용 BMC (Supermicro / 일부 Lenovo / 일부 Tyan)
- **server-exporter 영향**: 0 (read-only). 단 운영 정책 — 패치 안 된 BMC 자격증명은 회전 권장
- **대응**: 운영팀 BMC 펌웨어 업그레이드 권장 (server-exporter 자체 fix 불필요)
- **source**: AMI advisory 2025-03 / NIST NVD CVE-2024-54085

### F97 — SSL Unexpected EOF retry (Dell iDRAC issue #18)

- **증상**: Dell iDRAC9 일부 펌웨어 SSL Unexpected EOF (3-way handshake 직후)
- **server-exporter 영향**: 1회 fail → graceful degradation status=failed
- **대응**: F84 의 SSLContext min/max version + SECLEVEL=0 fallback 으로 일부 회피
- **추가 검증 권장**: 사이트 사고 시 1회 retry 도입 (현재 미구현 — 추적만)

### F104 — Session lockout 회피 (X-Auth-Token 도입 시)

- **증상**: BMC session pool 한계 도달 → 잠금
- **server-exporter 현재**: Basic Auth (단발성 collection 후 즉시 종료) → session 누수 불가
- **F33 ticket 대비** (X-Auth-Token 도입 시): DELETE session 보장 (graceful logout)
- **대응**: 현재 Basic Auth 유지 (rule 92 R2 — 사고 신호 없으면 변경 자제)

### F125 — Cisco CIMC < 4.x advisory

- **증상**: CIMC 3.x 이하 펌웨어 매우 제한적 Redfish (1.0.x)
- **server-exporter 적용**: cisco_cimc.yml firmware_patterns "^[4-6]\\." 로 4.x 이상만. cisco_bmc.yml (priority=10) 가 3.x 이하 fallback cover.
- **404 → 'not_supported' 분류**: 이미 cycle 2026-05-01 (I4) 적용

### F126 — Cisco/Dell DIMM error 정보 vendor 차이

- **증상**: DIMM error reporting 형식이 vendor 별 다름 (Cisco CIMC = Health 만, Dell = ECC count + correctable/uncorrectable 분리, HPE = AdvancedECC 등)
- **server-exporter 영향**: 현재 Health 만 raw passthrough → 호출자 시스템이 vendor 별 해석 책임
- **대응**: 호환성 영역 외 (새 데이터 — 별도 cycle)

## 일자: 2026-05-11 (cycle 2026-05-07 Phase 3 M-K2 — 9 vendor × N gen × source URL 매트릭스)

> Phase 3 M-K2 — cycle 2026-05-07-all-vendor-coverage 의 9 vendor 통합 매트릭스.
> Worker: W5 (Phase 3). 30 adapter origin 주석 일관성 (M-K1) 결과 통합. rule 96 R1+R1-A+R4+R5.

### 사이트 검증 4 vendor × 1 generation (cycle 2026-05-06 commit `0a485823`)

| vendor | generation | 사이트 BMC | 검증 commit | source URL | DSP0268 |
|---|---|---|---|---|---|
| Dell | iDRAC10 | 5대 (10.100.15.27/28/31/33/34) | `0a485823` | https://developer.dell.com/apis/2978/versions/ | v1.13+ |
| HPE | iLO7 | 1대 (10.50.11.231) | `0a485823` | https://hewlettpackard.github.io/ilo-rest-api-docs/ | v1.13+ |
| Lenovo | XCC3 | 1대 (10.50.11.232) | `0a485823` | https://lenovopress.lenovo.com/ + Lenovo XCC3 Redfish docs | v1.13+ |
| Cisco | UCS X-series | 1대 (10.100.15.2) | `0a485823` | https://www.cisco.com/c/en/us/td/docs/unified_computing/ucs/x/ + Intersight Managed Mode | v1.13+ |

### 9 vendor × N generation 매트릭스 (cycle 2026-05-07 종료 시점)

#### Dell iDRAC (5 adapter)

| generation | 펌웨어 매트릭스 | source URL | DSP0268 | lab |
|---|---|---|---|---|
| iDRAC7 (legacy) | 1.30+ ~ 2.x | https://developer.dell.com/apis/2978/ (archive) | v1.0+ | 부재 |
| iDRAC8 | 2.30+ ~ 4.x | https://developer.dell.com/apis/2978/ + cycle 2026-05-06 M-D3 W1 PowerSubsystem fallback | v1.4+ | 부재 |
| iDRAC9 | 3.x ~ 7.x | https://developer.dell.com/apis/2978/versions/3/docs/ | v1.6+ ~ v1.13+ | 부재 |
| iDRAC10 | 6.x+ (Gen17) | https://developer.dell.com/apis/2978/versions/ | v1.13+ | **PASS** |

#### HPE iLO + Superdome (6 adapter)

| generation | 펌웨어 | source | DSP0268 | lab |
|---|---|---|---|---|
| iLO (legacy 1/2/3) | — | HPE archive + IPMI fallback 별도 | 미지원 또는 v1.0 부분 | 부재 |
| iLO4 | 2.50+ | https://hewlettpackard.github.io/ilo-rest-api-docs/ilo4/ | v1.0+ | 부재 |
| iLO5 | 1.40+ | https://hewlettpackard.github.io/ilo-rest-api-docs/ilo5/ | v1.4+ | 부재 |
| iLO6 | 1.20+ (Gen11) | https://hewlettpackard.github.io/ilo-rest-api-docs/ilo6/ | v1.10+ | Round 11 부분 (DL380 Gen11 + 사이트 Gen12) |
| iLO7 | 1.00+ (Gen12) | (사이트 검증 commit `0a485823`) | v1.13+ | **PASS** |
| Superdome Flex | RMC 2.x ~ 3.x + iLO5 dual-manager | https://github.com/HewlettPackard/sdflexutils + HPE Superdome admin guide | v1.6+ | 부재 |

#### Lenovo BMC/IMM/XCC (4 adapter)

| generation | 펌웨어 | source | DSP0268 | lab |
|---|---|---|---|---|
| BMC (IBM legacy) | — | IBM xSeries archive | 미지원 | 부재 |
| IMM2 | 1.x ~ 2.x | https://pubs.lenovo.com/imm2/ + cycle 2026-05-06 M-D3 W4 SimpleStorage fallback | v1.0+ ~ v1.1 | 부재 |
| XCC + XCC2 | 1.x ~ 2.x | https://lenovopress.lenovo.com/.../xcc-redfish | v1.4+ ~ v1.10+ | 부재 |
| XCC3 | 1.17+ | (사이트 검증 commit `0a485823`) — Accept-only header 정책 (rule 25 R7-A-1) | v1.13+ | **PASS** |

#### Cisco UCS / CIMC (3 adapter)

| generation | 펌웨어 | source | DSP0268 | lab |
|---|---|---|---|---|
| BMC (legacy) | — | UCS C-series archive + xml-api fallback | 미지원 또는 v1.0 부분 | 부재 |
| CIMC C-series + S-series + B-series | 4.x ~ 6.x | https://www.cisco.com/c/en/us/td/docs/unified_computing/ucs/c/sw/api/ + F125 advisory (3.x 이하 cisco_bmc fallback) | v1.6+ ~ v1.10+ | 부재 (M4 lab tested 10.100.15.2) |
| UCS X-series (standalone CIMC) | (사이트 검증) | https://www.cisco.com/c/en/us/td/docs/unified_computing/ucs/x/ + Intersight Managed Mode docs | v1.13+ | **PASS** |
| UCS X-series (Intersight IMM 모드) | — | Intersight cloud (별도 채널 / 별도 cycle) | — | (server-exporter 범위 외) |

#### Supermicro BMC (7 adapter — X10 신설 후)

| generation | 펌웨어 | source | DSP0268 | lab |
|---|---|---|---|---|
| BMC (legacy) | — | https://www.supermicro.com/manuals/superserver/IPMI/ | v1.0+ | 부재 |
| X9 | 1.x ~ 3.x | https://www.supermicro.com/manuals/other/RedfishUserGuide.pdf + X9 IPMI legacy | v1.0 | 부재 |
| X10 | 1.x ~ 3.x (M-B1 cycle 2026-05-07 신설) | 위 동일 + AST2400 | v1.0+ | 부재 |
| X11 + H11 (AMD) | 1.x ~ 3.x | 위 동일 + AST2500 | v1.4+ | 부재 |
| X12 + H12 | 1.x+ | https://www.supermicro.com/manuals/other/RedfishUserGuide.pdf + AST2600 (Whitley/Tatlow) | v1.6+ | 부재 |
| X13 + H13 + B13 | 1.x+ | https://www.supermicro.com/manuals/other/BMC_IPMI_X13_H13_B13.pdf | v1.8+ | 부재 |
| X14 + H14 | 1.x+ (Redfish 1.21.0) | https://www.supermicro.com/manuals/other/BMC_IPMI_X14_H14.pdf | v1.10+ ~ v1.13+ | 부재 |
| ARS (ARM, 선택) | 1.x+ | https://www.supermicro.com/manuals/other/ + ARM specific notes | v1.10+ | 부재 |

#### Huawei iBMC (1 adapter)

| generation | 펌웨어 | source | DSP0268 | lab |
|---|---|---|---|---|
| iBMC 1.x ~ 5.x + Atlas | 다양 | https://support.huawei.com/enterprise/en/doc/EDOC1000163550/ + https://github.com/Huawei/Huawei-iBMC-Cmdlets | v1.0+ ~ v1.13+ | 부재 (cycle 2026-05-01 사용자 명시) |

#### Inspur ISBMC (1 adapter)

| generation | 펌웨어 | source | DSP0268 | lab |
|---|---|---|---|---|
| ISBMC (NF/TS 시리즈) | 1.x+ | https://www.inspur.com/eportal/ + manualzz NF5280M5 9.14 Redfish | v1.0+ | 부재 (cycle 2026-05-01 사용자 명시) |

#### Fujitsu iRMC (1 adapter)

| generation | 펌웨어 | source | DSP0268 | lab |
|---|---|---|---|---|
| iRMC S2 | — | https://support.ts.fujitsu.com/ (legacy archive) | 미지원 또는 v1.0 부분 | 부재 |
| iRMC S4 | 9.x+ | https://github.com/fujitsu/iRMCtools + iRMC-REST-API | v1.0+ ~ v1.4+ | 부재 |
| iRMC S5 | 1.x+ | https://manualzz.com/doc/37690590/irmc-restful-api-v5.0 (PRIMERGY iRMC S5 RESTful API Spec) | v1.6+ | 부재 |
| iRMC S6 | 1.x+ | https://support.ts.fujitsu.com/IndexDownload.asp (S6 User Guide) | v1.10+ | 부재 |

#### Quanta QCT (1 adapter)

| generation | 펌웨어 | source | DSP0268 | lab |
|---|---|---|---|---|
| QCT BMC (OpenBMC bmcweb) — S/D/T/J series | 다양 | https://www.qct.io/product/ + https://catalog.redhat.com/ + https://bmc-toolbox.github.io/ (multi-vendor abstraction) | v1.4+ ~ v1.10+ | 부재 |

### OEM namespace mapping (M-I3 + M-J1 통합 매트릭스)

| vendor | namespace 우선 | namespace fallback | 정본 위치 |
|---|---|---|---|
| Dell | `Oem.Dell` | (없음) | redfish_gather.py `_OEM_NAMESPACE_FALLBACK_CHAIN` |
| HPE | `Oem.Hpe` | `Oem.Hp` (iLO4 legacy) | 동상 |
| Lenovo | `Oem.Lenovo` | (없음) | 동상 |
| Cisco | `Oem.Cisco` | `Oem.Cisco_RackUnit` | 동상 + redfish-gather/tasks/vendors/cisco/ (M-J1 신설) |
| Supermicro | `Oem.Supermicro` | (없음) | 동상 |
| Huawei | `Oem.Huawei` | (없음) | 동상 + redfish-gather/tasks/vendors/huawei/ |
| Inspur | `Oem.Inspur` | `Oem.Inspur_System` | 동상 + redfish-gather/tasks/vendors/inspur/ |
| Fujitsu | `Oem.ts_fujitsu` | `Oem.Fujitsu` | 동상 + redfish-gather/tasks/vendors/fujitsu/ |
| Quanta | `Oem.Quanta_Computer_Inc` | `Oem.QCT` | 동상 + redfish-gather/tasks/vendors/quanta/ |

### DMTF Redfish 표준 reference

| 영역 | spec |
|---|---|
| Data Model | DSP0268 (v1.0 ~ v1.13+) |
| Resource & Schema Guide | DSP2046 |
| Schema Bundle | DSP8010 |
| AccountService | https://redfish.dmtf.org/schemas/v1/AccountService.json |
| PowerSubsystem | https://redfish.dmtf.org/schemas/v1/PowerSubsystem.json (v1.8+ ~ v1.13+) |
| Storage | https://redfish.dmtf.org/schemas/v1/Storage.json |
| SimpleStorage (legacy) | https://redfish.dmtf.org/schemas/v1/SimpleStorage.v1_3_0.json |
| Power (legacy) | https://redfish.dmtf.org/schemas/v1/Power.v1_8_0.json |

### 갱신 정책 (rule 96 R5)

- 펌웨어 업그레이드 / 신규 vendor 도입 시 본 매트릭스 갱신 의무 (cycle 단위)
- 6개월 주기 origin URL dead link 검증
- DRIFT 발견 시 (origin 주석 ↔ 실 응답 차이) FAILURE_PATTERNS.md + CONVENTION_DRIFT.md 동반 기록
- 사이트 검증 (PASS) row 갱신은 별도 cycle (capture-site-fixture skill 결과 반영)

### cycle 2026-05-07 산출 영향

| 항목 | 변경 |
|---|---|
| adapter (Redfish) | 28 → 30 (+supermicro_x10 / +supermicro_ars) |
| vendor OEM tasks | 4 → 9 (+cisco/huawei/inspur/fujitsu/quanta) |
| OEM namespace mapping | 9 vendor 통합 매트릭스 (M-I3 helper + M-J1 Cisco vendor task) |
| origin 주석 일관성 | 30/30 PASS (M-K1 verify_adapter_origin_check.py --all --redfish-only) |
| EXTERNAL_CONTRACTS row | 30+ row (9 vendor × N generation) |
| schema/sections.yml + field_dictionary.yml | 변경 0 (Q7 — schema 변경 0) |

## 정본 reference

- `redfish-gather/library/redfish_gather.py` (정본 — 약 350줄, stdlib only)
- 외부 API 공식 문서
- 외부 API 공식 문서 (stdlib vs library 비교)
- 외부 API 공식 문서 (5 vendor BMC)
- `docs/ai/references/winrm/pywinrm.md`
- 외부 API 공식 문서
- `docs/ai/references/vmware/community-vmware-modules.md`
- `.claude/ai-context/external/integration.md`

---

## 2026-08-12 (2차) — 실장비 통제 실험으로 확정한 벤더 쓰기 계약

정본: `tests/evidence/2026-08-12-standard-password-convergence.md`

### HPE iLO — `Password` 는 반드시 **단독 PATCH** (실측 확정)

- 대상: `10.50.11.231` / iLO 6 / ProLiant DL380 Gen11 / Redfish 1.20.0 /
  `#AccountService.v1_15_0` / `#ManagerAccount.v1_12_1`
- source: 사이트 실측 (통제 실험). 벤더 문서에 이 동작에 대한 기술 없음.

| PATCH 본문 | 응답 |
|---|---|
| `{Password:<길이위반>}` | HTTP **400** `iLO.2.36.InvalidPasswordLength` |
| `{Password:<길이위반>, Enabled, RoleId}` | HTTP **200** `Base.1.19.AccountModified` |
| `{Enabled, RoleId}` (Password 없음) | HTTP **200** `Base.1.19.AccountModified` |
| `{Password, Enabled, Locked, RoleId}` | HTTP **400** `iLO.2.36.PropertyNotWritableOrUnknown ['Locked']` |
| `{Password}` (정상 값) | HTTP **200** → 표준 자격 재인증 성공 |

- **계약 1**: iLO 는 `Password` 가 다른 속성과 함께 오면 **검사도 적용도 하지 않고 버린다.**
  같은 잘못된 값이 단독일 때는 400 으로 걸리고 묶이면 200 으로 통과한다.
- **계약 2**: `Base.1.19.AccountModified` 는 **비밀번호 적용의 증거가 아니다.** 아무 속성도
  바뀌지 않는 본문도 같은 메시지를 준다. 응답만으로는 성공과 구분할 수 없다
  → 재인증 검증이 유일한 판정 수단이다.
- **계약 3**: `Locked` 는 iLO ManagerAccount 에 **존재하지 않는 속성**이라 실으면 요청
  전체가 400 이 된다 (부분 적용 아님).
- 반영: `_ACCOUNT_FAMILIES['hpe_ilo5plus'].isolated_write_patch = True`, `evidence: proven`.
- **iLO4 는 미확인** (lab 부재) — 근거 없는 vendor 예외를 넣지 않기 위해 종전 동작 유지.

### HPE iLO — 인증 실패 패널티를 장비가 선언한다

```
Oem.Hpe.AuthFailuresBeforeDelay     = 1
Oem.Hpe.AuthFailureDelayTimeSeconds = 10
Oem.Hpe.AuthFailureLoggingThreshold = 3
Oem.Hpe.EnforcePasswordComplexity   = False
MinPasswordLength                   = 8
```

**첫 실패 직후부터** 그 계정의 인증이 10초간 막힌다. 표준 인증 1회 실패 후 복구하는
흐름에서는 패널티가 이미 켜져 있으므로, 고정 6초 안의 재인증은 비밀번호를 옳게 썼어도
전부 401 이다. → 재인증 확인 간격을 장비 선언값에서 끌어온다(`account_verify_delays`).
표준 AccountService 에는 해당 항목이 없어 벤더가 Oem 에 둔다. 코드는 **namespace 이름을
보지 않고 키 이름(`AuthFailureDelayTimeSeconds`)으로만** 읽는다 (rule 12 R1).

### Dell iDRAC — 선언된 규칙만으로 비밀번호 수용 여부를 알 수 없다

- 대상: `10.100.15.34` / iDRAC9 / PowerEdge R760 (16G) / FW `7.10.70.00` / Redfish 1.20.1
- 읽을 수 있는 정책은 전부 허용적이었다: `MinPasswordLength=0`, `MaxPasswordLength=127`,
  `Security.1.PasswordRequire*` 전부 Disabled, Regex 빈 값.
- 그럼에도 특정 값이 "Security Strengthen Policy" 를 이유로 거부됐다. 활성 제약은
  `Security.1.MinimumPasswordScore = "Weak Protection"` 하나뿐이며, Dell 은 그 점수
  산출 알고리즘도 사전 검증 endpoint 도 노출하지 않는다.
- 회전된 값은 수용됐다(1·2차 실행 표준 인증 성공). **즉 값에 따라 재발할 수 있다.**
- 계약: Dell 대상 비밀번호는 선언된 규칙 통과만으로 안전하다고 볼 수 없고, 거부는
  **쓰기 응답으로만** 확정된다.

### Cisco CIMC — Roles 어휘가 RoleId 계약이다 (재확인)

- 대상: `10.100.15.2` / TA-UNODE-G1 / `#AccountService.v1_6_0` / Redfish 1.2.0
- `Roles`: `admin` / `user` / `readonly` / `SNMPOnly` — **`Administrator` 없음**
- `MinPasswordLength=1`, `MaxPasswordLength=20`, ETag 미제공, `Locked` 속성 없음
- Adapter 가 `redfish_cisco_ucs_xseries` 로 오선택돼도 Family/RoleId 는 이 어휘로
  옳게 결정된다 (`cisco_cimc_collection_post_id` / `admin`). 회귀 테스트 3건으로 고정.

### Lenovo XCC — `Locked` 는 노출하지만 read-only

- 대상: `10.50.11.232` / XCC / `#AccountService.v1_10_0` / Redfish 1.15.0
- `Locked=false` 를 **노출은 하지만** PATCH 로 설정하면 거부된다.
  `MaxPasswordLength=32`, ETag 제공(strong).
- 비밀번호를 다른 속성과 함께 보내는 것은 정상 동작한다 (HPE 와 반대) — 오히려 단독
  PATCH 는 과거 권한 cache 손상 사례가 있어 묶어서 보낸다.


---

## 2026-08-13 — 9 Vendor Account Write Contract (Delta Research 반영)

정본: `docs/ai/contracts/redfish-account-write.md`,
`tests/evidence/2026-08-13-account-write-contract-alignment.md`

### Firmware / Advisory

| Vendor | 계약 | 출처 |
|---|---|---|
| HPE | UserAccount PATCH 가 일부 파라미터를 무시. 영향 iLO6 1.73/1.74 · iLO7 1.19/1.20, **해결 iLO6 1.75+ / iLO7 1.21+** | Customer Advisory `a00159600en_us` (2026-05-12) |
| HPE | `PasswordChangeRequired` = Read Only (iLO5/6/7), `AccountTypes` = Read Only (iLO6 1.64+/iLO7), `Locked` 는 ManagerAccount schema 에 없음 | servermanagementportal.ext.hpe.com iLO5/6/7 Resource Definitions |
| Dell | `SYS474` = 비밀번호 정책 거부. `MessageArgs=[]`, `RelatedProperties=["#/Password"]`, `Severity=Warning`, **HTTP 200 + Success 메시지와 함께 온다** | Dell Error and Event Message Guide + 실측 10.100.15.34 |
| Dell | `HTTPBasicAuth` 기본값이 iDRAC9 7.30.10.50 / iDRAC10 1.30.10.50 부터 `Unadvertised` | Dell KB 000437501 |
| Dell | iDRAC9 = 16 users(ID 1 예약) / iDRAC10 = 32 users(ID 1·2 예약) | idrac9/idrac10 User Guide |
| Lenovo | XCC1 Purley = 빈 slot PATCH / Whitley·AMD·XCC2·XCC3·TSM = Collection POST | pubs.lenovo.com xcc-restapi |
| Lenovo | **XCC3 공식 Create/Update Property 목록에 `PasswordChangeRequired` 가 없다** (XCC2 는 있다) | pubs.lenovo.com xcc3-restapi |
| Lenovo | `Locked` 는 XCC1/2/3 에서 GET 에만 존재(Update 목록 없음), **TSM 은 writable** | pubs.lenovo.com xcc/tsm |
| Lenovo | `HostBootstrapAccount` = DMTF ManagerAccount 표준 Property. **실미러 10.50.11.232 에 존재** | `schema/redfish_dmtf_2026.1/ManagerAccount.v1_14_1.json`, `tests/reference/redfish/lenovo/10_50_11_232` |
| Cisco | IMC 3.x = `POST /Accounts/<ID>`(Instance) / 4.1+ = `POST /Accounts` + body `Id` | cisco.com IMC REST API Guide 3.x / 4.1 |
| Cisco | BMC 1.1 = `Locked` **writable**, `PasswordChangeRequired` **read-only(기존 계정)**, `AccountTypes` read-only | cisco.com BMC REST API Guide 1.1 |
| Supermicro | 최신 Add Account = **`POST /redfish/v1/AccountService`** (Accounts Collection 아님) | Redfish 1.22.2-00.04 User Manual |
| Supermicro | IPMI/Redfish 계정 분리 경계 = Gen13 `01.05.xx+` / Gen14 `01.02.xx.xx+` / NVIDIA Superchip `01.04.xx+` | 동 매뉴얼 Accounts |
| Inspur | M6 Create = POST Collection(**If-Match 없음**) / Repair = PATCH Instance + `GET ETag` → `If-Match` | 浪潮英信服务器 Redfish用户手册 V1.2 §4.4/§4.6 |
| Inspur | 성공 판정 = HTTP 200 **AND** `Oem.Public.Status == 0` | 동 매뉴얼 |
| Huawei | ManagerAccount `UserName/Password/RoleId/**Locked**/Enabled` 가 GET/PATCH. `PasswordChangeRequired`/`AccountTypes` 는 공식 table 에 없음 | EDOC1100372764 Kunpeng iBMC Redfish |
| Huawei | Local User 마다 Login Interface(Web/SNMP/IPMI/SSH/SFTP/Local/**Redfish**)를 개별로 켜고 끈다 | "Setting the User Interfaces for Logging to iBMC" |
| Fujitsu | `RedfishAdmin`/`RedfishOperator`/`RedfishReadOnly` 는 Fujitsu Role 체계이며 **`ManagerAccount.RoleId` literal 이라는 근거는 없다** | SVS_LdapDeployer |
| Quanta | upstream bmcweb 은 `Redfish` 와 `WebUI` 를 결합해 매핑 — 한쪽만 보내면 `StrictAccountTypes` 오류 | github.com/openbmc/bmcweb account_service.hpp |
| Quanta | D43K=Redfish v1.1 / D54U·S24P=v1.11 / S45Z 등 Xeon 6=Inhouse OpenBMC. **AST2600 만으로 OpenBMC 판정 금지** | qct.io 제품자료 |

### 공통 금지 (5개 문서 이상이 명시)

```text
- PasswordChangeRequired 를 덧붙여 재시도하는 generic fallback
- 거부된 속성을 빼고 다시 쓰는 사다리
- 두 Create URI 를 순차로 시도하는 fallback
- HTTP 2xx 만으로 convergence 성공 처리
- 한 Vendor/Family 의 실측을 다른 Vendor 의 기본 동작으로 일반화
```

## 2026-10-04 — dmidecode 3.6 Size 단위 IEC 접두어 (external-contract-drift, RHEL 10.2 실측)

- 계약: `dmidecode -t memory` Type 17 `Size:` / Type 16 `Maximum Capacity:` 단위 표기.
- 종전(≤ 3.5): `kB` / `MB` / `GB` / `TB` (2.x 는 `kB`). **3.6(RHEL 10.2 `.37/.38` 실측, main #20)**: `KiB` / `MiB` / `GiB` / `TiB` — 예 `Size: 4 GiB`, `Maximum Capacity: 5 GiB`.
- 영향: `os-gather/tasks/linux/gather_system.yml` 공유 DMI collector 의 두 단위 환산이 0 을 내 DIMM 전부 누락 · `total_basis=os_visible`. Windows(WMI) · ESXi(vSphere) 무관.
- 조치: 환산이 `kib/mib/gib/tib` 를 받는다(2026-10-04). regression `tests/unit/test_linux_memory_parser.py::test_dmidecode_36_iec_units_are_parsed`. 다른 dmidecode 필드(Speed `MT/s`, Current/Max Speed `MHz`)는 3.6 에서도 같다(실측 raw_head · DMI_CUR_MHZ 정상).
- 출처: 실측 raw(`tests/evidence/2026-10-04-review-c1-c6.md` §5-4). dmidecode 3.6 릴리스 노트(IEC 단위 전환) 는 web 확인이 필요하면 추가한다 — 판정은 실측으로 끝났다.
- 미검증: dmidecode 3.6 의 `kiB` 대소문자(`KiB`) — 파서는 `tolower` 비교라 무관.
- **정정 2026-10-05**: IEC 표기는 "3.6" 이 아니라 upstream 커밋 **"dmidecode: Use binary unit prefixes"(2025-04-24)** 에서 왔다 — 3.6 릴리스(2024-04-24) **이후**다(source: https://cgit.git.savannah.nongnu.org/cgit/dmidecode.git/log/?qt=grep&q=unit, 확인 2026-10-05; 같은 로그에 "Fix unit of starting and ending addresses"(2025-04-24) · "dmioem: Display drive capacity in power-of-10 units"(2025-05-12)). upstream NEWS(mirror) 에는 이 변경 항목이 없다. 저장소 실캡처 `tests/reference/os/rhel960/10_100_64_165/cmd_dmidecode_memory.txt` (`# dmidecode 3.6`, RHEL 9.6)은 `Size: 8 GB`(SI)다. 따라서 "RHEL 10.2 가 싣는 dmidecode 빌드(버전 표기는 raw_head 에 없었다)가 이 upstream 변경을 포함한다" 가 정확한 서술이고, 영향 범위는 "dmidecode ≥ 3.6" 이 아니라 **그 커밋을 포함한 빌드**(upstream 3.7 이후 또는 배포판 backport)다. 파서는 두 단위계를 모두 환산하므로 조치·결론(DIMM 해결)은 그대로다.
