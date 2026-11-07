# 07. 메인 추가 검증 (2026-10-27) — CSUS 3200 FC HBA 링크 상태의 유추 원천

> 작성: 메인 Claude Fable 5.1 (`claude-fable-5-1`, effort=max). 계기: 사용자 질문 2026-10-27 "FC Port 리소스 말고 어느 곳에서나 절대 찾을 수 없나, 유추할 수 있는 어떤 값도".
> 결론: **있다.** FC Port 리소스에는 링크 키가 없지만, 같은 카드의 `Chassis/r001u01/PCIeDevices/{N}` 의 `Status.Conditions[]` 에 HPE 등록부 `H3Alert.1.8.LinkUp` / `LinkDown`(정의: "external Ethernet or Fibre Channel HBA port link") 이 **카드(슬롯) 단위**로 실려 있고(1차 4대·2차 3대 전부), 2차 `LogService/Oem/Iel` 에는 `DCD_FCHBA_LINK_UP/DOWN` 이벤트가 슬롯 단위로 남는다. 작업자 03 보고서(§6 181행)와 ISSUES.md 는 Port 리소스에서 조사를 멈춰 이 원천을 놓쳤다 → 이슈 `03-storage-004`(MED) 추가, 사용자 결정 11 신설.

## 1. 조사 범위·방법 (읽기 전용)

| 항목 | 내용 |
|---|---|
| 대상 미러 | 2차 `csus3200_01/02/03`(RMC 1.77.30, 추출본) + 1차 `HPE_CSUS3200/01~04`(RMC 1.75.108, 외부 원본) |
| 방법 1 — WWN 역추적 | FC NDF/Port 의 WWNN·WWPN·AssociatedWorldWideNames 8값을 정규화(구분자 제거)해 미러의 **모든 파일**(json·txt·xml·bin·npar·gz 포함, 2차 4,068/3,974/3,998 파일)에서 검색 |
| 방법 2 — 어휘 스캔 | `LinkStatus/LinkState/PortLinkStatus/FabricName/NumberDiscoveredRemotePorts/FibreChannelId/PortState/FLOGI/PLOGI/SFP/transceiver/optic/Rx·Tx power/PortMetrics/link up·down/NoLink` 등 전 파일 대소문자 무시 |
| 방법 3 — 구조 확인 | FC 카드 NetworkAdapter/Controllers/NDF/Port 전체 본문, 연결된 PCIeDevice·PCIeFunction, Systems Boot/BootOptions, Chassis Sensors·Thermal/PowerSubsystem, Fabrics, TelemetryService MetricReports, `Systems/*/NetworkInterfaces`, LogServices Entries, manifest(absent/not_gettable/device_error/skipped/non_json), `_fsmap`/`_links` |
| 도구 | scratchpad `linkscan/{scan_csus_link,structure_csus,candidates_csus,infer_all_csus}.py`(저장소 밖, `python -I`), Tier 1 봉투 `baseline/tier1/csus3200_0{1,3}/gather_output.json` |

## 2. 찾은 것

### 2.1 원천 A — `PCIeDevices/{N}.Status.Conditions[]` 의 `H3Alert.1.8.LinkUp` / `LinkDown` (카드 단위, 7대 전부)

등록부 `RegistryStore/Registries/en/H3Alert.json`(2차 미러에 수록, `Registries/H3Alert` → `H3Alert.1.8`, OwningEntity HPE):

| MessageId | Description | Message | Severity | Resolution |
|---|---|---|---|---|
| `H3Alert.1.8.LinkUp` | An Ethernet or Fibre Channel Host Bus Adapter (HBA) port link on a PCIe device is operational. | `%1 has an operational external Ethernet or Fibre Channel Host Bus Adapter (HBA) port link.` | OK | (없음) |
| `H3Alert.1.8.LinkDown` | An Ethernet or Fibre Channel Host Bus Adapter (HBA) port link on a PCIe device has gone down. | `%1 has lost connection on its external Ethernet or Fibre Channel Host Bus Adapter (HBA) port link.` | Warning | Check cable and the connection to the external switch. |

PCIe 자체 링크는 별도 메시지(`PcieLinkTrainingOk` "The PCIe card link is now ready", `PcieLinkDegraded`)다 — `LinkUp/LinkDown` 은 **외부 포트 링크** 를 뜻한다. `ServiceConditions/AcquitActionInfo` 의 허용 값에도 `LinkDown` 이 있어 RMC 가 리소스 조건으로 LinkDown 을 올리는 설계임을 보여 준다.

실측(`%1` = `Slot.Location.PartLocation.ServiceLabel`, 예 `rack1/chassis_u1/cpu2/io_slot11`):

| 미러 | FC 카드(PCIeDevices) | 조건 | Timestamp |
|---|---|---|---|
| csus3200_01 | 11 (HPE SN1100Q 16Gb 2p FC HBA) | LinkUp OK | 2026-10-16T01:06:26Z |
| csus3200_01 | 14 (SN1100Q) | LinkUp OK | 2026-10-21T01:16:06Z |
| csus3200_03 | 11 (SN1100Q) | LinkUp OK | 2026-10-21T01:17:17Z |
| csus3200_03 | 14 (SN1100Q) | LinkUp OK | 2026-10-21T01:17:18Z |
| csus3200_02 | FC 카드 없음 (Ethernet 1·9, RAID 3) | LinkUp OK (3장 전부) | 2026-10-17T01:42:56Z |
| 1차 01/02 | 10·15 (SN1100Q) | LinkUp OK | 2026-05-07 |
| 1차 03/04 | 2·7·10·15 (SN1100Q) | LinkUp OK | 2026-05-07 / 2026-06-11 |

- 7개 미러 × 모든 PCIe 카드 = **59 관측 전부 `LinkUp`(OK), `LinkDown` 0건.** Mellanox 10/25GbE NIC 와 Adaptec RAID(`SR3258p-16i/e`)에도 같은 `LinkUp` 이 붙어 있다 — 결선되지 않은 카드가 `LinkDown` 또는 조건 없음으로 나오는지는 Mock 으로 **확인하지 못했다**(판별력 미검증).
- 카드 단위라 2포트 카드의 포트별 상태는 알 수 없다(문구 "an operational … port link" = 포트 1개 이상).
- `PCIeFunctions/NetworkDevice` 는 `Status {State Enabled, Health OK}` 만(링크 아님). NetworkAdapter·NDF·Port 에는 `Status` 조차 없다.

### 2.2 원천 B — `LogService/Oem/Iel`(2차만, 5,000행 창) 의 `DCD_FCHBA_LINK_UP` / `DCD_FCHBA_LINK_DOWN`

행 키 `index/date/time/type/source/partition/severity/level/data/eventId/keyword/details`. csus3200_03 (창 2026-10-19 05:45:33Z ~ 2026-10-21 15:02:41Z):

| date | time | keyword | severity | type | details |
|---|---|---|---|---|---|
| 2026-10-21 | 01:16:57Z | DCD_FCHBA_LINK_DOWN | *CRIT | OS | [rack1/chassis_u1/cpu2/io_slot11] |
| 2026-10-21 | 01:17:07Z | DCD_FCHBA_LINK_DOWN | *CRIT | OS | [rack1/chassis_u1/cpu3/io_slot14] |
| 2026-10-21 | 01:17:17Z | DCD_FCHBA_LINK_UP | Info | OS | [rack1/chassis_u1/cpu2/io_slot11] |
| 2026-10-21 | 01:17:18Z | DCD_FCHBA_LINK_UP | Info | OS | [rack1/chassis_u1/cpu3/io_slot14] |

- **교차 증거**: 이 UP 이벤트 시각이 원천 A 의 `PCIeDevices/11` Timestamp `2026-10-21T01:17:17Z`, `/14` `01:17:18Z` 와 **초 단위로 일치** → 조건 A 는 FC HBA 포트 링크 전이를 반영하고 Timestamp 는 마지막 전이 시각이다.
- `type: OS` — 호스트 쪽 에이전트가 올린 이벤트(DCD). 호스트가 꺼져 있거나 에이전트가 없으면 갱신되지 않을 수 있다(Timestamp 로 오래됨을 볼 수 있다).
- csus3200_01 의 Iel 창은 2026-10-21 08:18:17Z 부터라 `/14` 의 01:16:06Z 전이가 창 밖 → FCHBA 이벤트 0건. csus3200_02 는 FC 카드가 없어 0건. 1차 미러는 `LogService` 를 크롤하지 않았다. 창 의존이라 **수집 원천으로는 부적합**, 원천 A 의 교차 검증용이다.

## 3. 찾지 못한 것 (CSUS 7대 공통)

| 후보 | 결과 |
|---|---|
| WWN 값이 NetworkAdapters 밖에 등장 | 0 파일 (Boot·Log·OEM·FRU 어디에도 없음) |
| Port 표준 키 `LinkStatus/LinkState/CurrentSpeedGbps/Status/Metrics`, `FibreChannel.FabricName/NumberDiscoveredRemotePorts/PortConnectionType` | 없음 — Port 는 `FibreChannel.AssociatedWorldWideNames/Id/Name` 뿐 |
| NDF `FibreChannel.FibreChannelId`(fabric 할당 FC_ID)·`BootTargets`, NDF `Status/NetDevFuncType` | 없음 — `PermanentWWNN/PermanentWWPN/WWNN/WWPN`·`Links.PCIeFunction`·`NetDevFuncCapabilities` 뿐 |
| `Ports/*/Metrics`, `NetworkAdapters/*/Metrics`, `Systems/*/NetworkInterfaces` | 없음(링크·fsmap 모두 부재) |
| TelemetryService | MetricReportDefinitions 5 = CPU/메모리 사용률·섀시 전력뿐 |
| Fabrics | `FlexGrid`(HARP 인터커넥트) 뿐, FC 패브릭 아님 |
| Chassis Sensors 88 | 슬롯·광모듈 센서 없음(`PCIE_RISER0~3_TEMP` 라이저 온도만) |
| Systems Boot/BootOptions | BootOptions 2건, FC/WWN/SAN 언급 0 |
| LogServices Entries 12, Audit raw.txt 11,547~18,230줄, FabricTest 로그 5 | 링크·FC 언급 0 (FabricTest 는 FlexGrid 하드웨어 점검 스크립트 출력) |
| `RawFruData/PCIE_SLOT11|14/raw.bin`, `NparConfig` npar/bin | 카드 식별 문자열(`HPE SN1100Q 16Gb 2P FC HBA`, 일련번호·PN)만 — 상태 정보 없음 |
| 링크 어휘를 가진 리소스 | `NetworkAdapters/Rmp/Ports/*`·`Managers/RMC/EthernetInterfaces/*`(RMC 자기 관리 포트, `LinkStatus LinkUp/NoLink`) 와 `PCIeDevices/*`(원천 A) 뿐 |

## 4. 코드 현황 (수정 없음, 위치만)

- `PCIeDevices/11`·`/14` 는 **이미 수집 중에 요청한다** — Tier 1 csus3200_01 `server_access.jsonl` 요청 200건 중 각 1회(어댑터 펌웨어 보강 `redfish_gather.py:4475-4486` CSUS-R16, 섀시 PCIe 식별 `_chassis_pcie_devices` :3516-3556). 추가 요청 0 으로 조건을 읽을 수 있다.
- 그러나 `Status.Conditions` 를 읽는 코드가 **0곳**(`grep -n Conditions redfish_gather.py` 0건). `_chassis_pcie_devices` 는 `Status.Health` 만 담는다.
- `_hba_link_status(pdata)` :4114-4126 은 Port 본문의 `LinkStatus` 키만 보고 없으면 `'down'`, `_hba_link_missing` → notice(:4812). 호출부 :4682(포트) · :4781(고아 기능) · :4747(port-less).
- `LogService/Oem/Iel` 은 요청하지 않는다(요청 추가 필요 + 5,000행 창 → 원천으로 비권장).
- 벤더 경계(CLAUDE.md §5): `H3Alert.` 접두는 HPE H3(CSUS/RMC) 전용 OEM 등록부 → adapter `hpe_csus_3200.yml` vendor_notes 플래그 + 라이브러리 OEM 추출 분기에 두고 공통 코드는 플래그 값으로만 가른다. 포트에 `LinkStatus` 가 있는 벤더(DL380 Gen12·SR650 V4·1차 Dell)는 영향 0 이어야 한다.

## 5. ADR·보고서 영향

| 문서 | 현재 문구 | 실측 | 정정 제안 |
|---|---|---|---|
| ADR-2026-10-18 11행 | "HPE CSUS 3200 RMC(1.75.108)는 FC Port 리소스에 링크 상태 속성 자체가 없어 Redfish 로는 수집할 수 없었다" | Port 에는 없지만 같은 카드 `PCIeDevices` 조건(카드 단위)이 1.75.108·1.77.30 모두 있다 | "포트 단위 속성은 없고 카드 단위 조건(H3Alert LinkUp/LinkDown)만 있다" 로 |
| ADR-2026-10-18 29행 | "HPE 에 FC `Port.LinkStatus` 미제공을 문의한다" | 미해결(1.77.30 도 Port 키 없음) | 유지 + 문의 내용에 "카드 단위 조건만 제공" 추가 |
| ADR-2026-10-19 결정 1·25행 | `_hba_link_status` 는 Port `LinkStatus` 만; 키 없음 → down + notice | 값 규칙(up/down 둘뿐)은 불변 | 결정 11 에 따라 "카드 단위 조건을 폴백으로 쓸지" 를 덧붙임 |
| 03 보고서 §6 181행 | "CSUS 2차도 FC Port 키가 FibreChannel/Id/Name 뿐 → down + notice. 일치" | Port 범위에서만 맞음 | 본 addendum 이 보완 — 보고서 원문은 작업자 산출물이라 수정하지 않음 |
| coverage-132 csus3200_01·03 storage | PASS(hbas PASS) | hbas ISSUE | ISSUE 로 갱신(03-storage-004) |

## 6. 이슈 `03-storage-004` (MED — 원천 확정 · 포트 매핑 추정)

- **증상**: CSUS 3200 의 `storage.hbas[].link_status` 가 항상 `down`(notice "링크 상태 미제공") — 그러나 카드 단위 외부 포트 링크 조건(`LinkUp`, 마지막 전이 2026-10-21T01:17:17Z 등)이 이미 수집한 `PCIeDevices` 응답에 있다. 소비자에게 "미제공" 과 "down" 이 값에서 같고, 카드가 보고한 Up 정보가 버려진다.
- **영향**: CSUS 전 장비(2차 2대·1차 4대의 FC HBA 4~8포트), 1.75.108·1.77.30 공통. 다른 벤더 영향 0.
- **수정 위치(제안)**: `adapters/redfish/hpe_csus_3200.yml` vendor_notes 플래그(예: 카드 조건 등록부 접두 선언) → `redfish_gather.py` 카드 루프(:4454~, `Controllers[0].Links.PCIeDevices[]` 응답 재사용)에서 `Status.Conditions[].MessageId` 가 `<prefix>.LinkUp/LinkDown` 인 항목을 카드 상태(+Timestamp)로 추출 → `_hba_link_status` 호출부에서 Port `LinkStatus` 없을 때만 폴백(결정 11 의 매핑 정책대로) + notice 문구에 카드 조건·시각 기록. `_hba_link_missing` 분류(미제공/미확정)에 "카드 단위 조건으로 대체" 한 종류 추가.
- **계약 영향**: 없음(값은 up/down, notice 는 `diagnosis.details.notices` 문장).
- **회귀**: 2차 csus3200_01/03 + 1차 4대 recording 으로 카드 조건 추출 고정; DL380/SR650/Dell golden 바이트 동일; 변형(LinkDown 조건·조건 없음·Timestamp 없음) 케이스 합성 — 합성은 실측 대체가 아님을 fixture 메타에 명시(rule 25 R7-A-1).

## 7. 사용자 결정 11 — 카드 단위 조건을 포트 값에 어떻게 반영할지

| 안 | 내용 | 위험 |
|---|---|---|
| (a) | 값은 지금처럼 `down` 유지, notice 문구에 카드 조건(LinkUp/LinkDown)과 Timestamp 를 덧붙임 | 값은 계속 실제와 다를 수 있음(소비자가 notice 를 읽어야 함) |
| (b) | 카드 `LinkUp` → 그 카드 포트 전부 `up`, `LinkDown`/조건 없음 → `down`, notice "카드 단위 신호" | 1포트만 결선된 카드의 나머지 포트가 거짓 `up` |
| (c) | 실장비에서 미결선 카드/포트의 조건 거동(LinkDown 이 실제로 뜨는지, 포트 1개만 결선 시 LinkUp 인지)을 확인한 뒤 (a)/(b) 결정 | Mock 59 관측 전부 LinkUp 이라 판별력 미검증 — 확인 전 (b) 는 추정 적용 |

제가(AI) **초안 제안**: (c) 확인 전까지 (a) 를 구현(요청 추가 0, 계약 불변), 확인 결과에 따라 (b) 로 확장. 결정은 사용자 몫이다.

## 8. 분석 누락 기록

작업자 03 과 메인 교차 검증 모두 "표준 Port 리소스에 키가 없다 → 미제공" 에서 멈췄다. 같은 신호가 **OEM 조건(`Status.Conditions`)·OEM 로그** 에 있는지 전수 스캔하지 않았다 → `docs/ai/catalogs/FAILURE_PATTERNS.md` 2026-10-27 항목. 재발 방지: "미제공" 판정 전에 (1) 값 역추적(WWN·MAC·시리얼), (2) 리소스 어휘 전수 스캔, (3) `Status.Conditions`·OEM 로그·등록부 메시지 정의 확인을 거친다.

## 부록 — 재현

```bash
# 2차 추출본·1차 원본 전수 스캔 (읽기 전용, 저장소 밖 스크립트)
PYTHONUTF8=1 python -I <scratchpad>/linkscan/infer_all_csus.py \
  C:/github/ClovirONE/mock2-audit-20261026/extract/csus3200_01 ... "C:/github/서버mock데이터/1차/HPE_CSUS3200/01" ...
# 등록부 정의
python -c "import json; m=json.load(open('<extract>/csus3200_01/redfish/v1/RegistryStore/Registries/en/H3Alert.json/index.json', encoding='utf-8'))['Messages']; print(m['LinkUp'], m['LinkDown'])"
# Tier 1 이 PCIeDevices 를 이미 요청했는지
grep -o '"/redfish/v1/Chassis/r001u01/PCIeDevices/1[14]"' baseline/tier1/csus3200_01/server_access.jsonl | sort | uniq -c
```
