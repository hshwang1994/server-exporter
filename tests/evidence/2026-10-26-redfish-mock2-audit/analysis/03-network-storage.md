# 03. network / storage — 2차 Redfish Mock 11대 분석 (2026-10-26)

모델: claude-fable-5-1 / worktree: `C:/github/ClovirONE/clovirone-server-gathering/.claude/worktrees/agent-aabdeea2f07959e28` / 브랜치: `worktree-agent-aabdeea2f07959e28` (base `e8b5ae9b`)

담당 필드: `data.network.{interfaces[], adapters[], ports[], dns_servers, default_gateways, driver_map, summary, portgroups, virtual_switches}`,
`data.storage.{controllers[], physical_disks[], logical_volumes[], hbas[], infiniband[], datastores, filesystems, summary}`.
근거 우선순위: 11대 Mock raw(`C:/github/ClovirONE/mock2-audit-20261026/extract/<server>/redfish/v1/...`, 아래 `raw:` 표기) → Tier 1 envelope
(`EVID/baseline/tier1/<label>/gather_output.json`) → Tier 2 모듈 출력 → 코드/ADR/문서. 1차 7대 미러(`r1_*`)는 영향 범위 확인용.
수치는 전부 이번 측정값이며 측정 방법은 10절에 적었다. 비밀정보(계정·비밀번호)는 본 보고서에 없다. WWPN/MAC/시리얼은 장비 식별자라
비교 관계 재현에 필요한 최소한만 적고 시리얼은 앞 3~4자만 적었다.

## 1. 요약

- 이슈: **HIGH 0 / MED 2 / LOW 8** (`03-network-001`, `03-storage-001` MED; `03-network-002~007`, `03-storage-002~003` LOW; + 관찰 O-1~O-11, 5절·6절·10절). 11대 모두 Tier 1 `status=success`, `sections.network/storage=success`, errors 0.
- 11대 한 줄 상태: CSUS 3대 **PASS**(FC HBA link 는 ADR-2026-10-19 대로 항상 down — 장비가 LinkStatus 를 주지 않음) / DL380 Gen12 01·02·04 **PASS** /
  DL380 Gen12 03 **ISSUE**(호스트 전원 Off — Storage 컬렉션 0건·NIC 정보 축약인데 envelope 에 storage/network 쪽 신호 없음, `03-storage-001`) /
  SR650 V4 01·04 **PASS** / SR650 V4 02·03 **ISSUE**(XCC3 가 FC HBA 포트를 호스트 `EthernetInterfaces` 로 노출 → `network.interfaces[]`·`summary.port_count` 에 FC 포트가 섞임, `03-network-001`).
- 분류 규칙 재검증: FC 분류(ADR-2026-05-29)는 2차의 서로 다른 세 모양(HPE iLO7: NDF `NetDevFuncType=FibreChannel`+Port `LinkNetworkTechnology=FibreChannel`·`FibreChannel:{}`·`Ethernet.AssociatedMACAddresses=[WWPN]` /
  Lenovo XCC3: Port `PortProtocol=FC`+NDF 컬렉션 0건+`FibreChannel.AssociatedWorldWideNames=[WWPN]` / CSUS RMC: NDF `NetDevFuncCapabilities=[FibreChannel]`+WWPN/WWNN, Port `AssociatedWorldWideNames=[WWNN,WWPN]`)에서 모두 맞다.
  InfiniBand(ADR-2026-10-17)는 11대 어디에도 IB 신호가 없어(`NetDevFuncCapabilities` 전부 `Ethernet`/`FibreChannel`, `LinkNetworkTechnology` Ethernet/FibreChannel 뿐) 실측 검증 불가 — 오탐 0 만 확인.
  `hbas[].link_status` up/down 둘뿐(ADR-2026-10-19)은 11대 전부 지켜졌고, DL380 Gen12·SR650 V4 에서는 up/down 이 실제 링크(포트 1 up·포트 2 down 패턴)를 반영한다.
- 1차 축약 fixture(`real_*`) 와 전체 미러 재생: `EVID/baseline/tier2/_golden_compare.plain.json` 기준 network/storage 차이 0(차이는 bios 1건뿐). Tier 1 envelope 과 Tier 2 모듈 출력은 18대 모두 adapters/ports/hbas 가 바이트 단위로 같고, controllers 만 normalize 의 A-6 빈 컨테이너 제거(r1 CSUS 01/02)로 다르다.

## 2. 필드별 수집 흐름 (진입 → 요청 경로/폴백 → 파서 → 정규화 → 출력)

모듈 `redfish-gather/library/redfish_gather.py`(이하 `rg.py`), Ansible `redfish-gather/tasks/normalize_standard.yml`(이하 `ns.yml`). 섹션 dispatch 는 `rg.py:6539-6612 _collect_all_sections` — storage 에 `System.Links.Chassis` 전체(`sys_chassis_all`), network_adapters 에 1순위 섀시 + 나머지 섀시를 넘긴다.

| 출력 필드 | 진입 함수 | 요청 경로 / 폴백 | 파서 (rg.py) | 정규화 (ns.yml) |
|---|---|---|---|---|
| `network.interfaces[]` | `gather_network` rg.py:3724-3765 | `Systems/{id}/EthernetInterfaces` → 멤버 GET (폴백 없음) | Id/Name/MACAddress(소문자)/SpeedMbps/MTUSize/LinkStatus(`_normalize_link_status` 2396-2427)/Status.Health/IPv4Addresses(0.0.0.0 제외). **IPv6Addresses 는 읽지 않음** | ns.yml:65-112 `interfaces` — `addresses[]`(family ipv4 고정), `is_primary`(LinkUp+IPv4 → 없으면 첫 LinkUp), `kind: server_nic` 고정 |
| `network.adapters[]` / `ports[]` | `gather_network_adapters_chassis` rg.py:4834-4987 → `_network_adapter_sources` 4394-4447 → `_collect_one_network_adapter` 4449-4832 | (1) `Chassis/{Links.Chassis[0]}/NetworkAdapters` (2) 나머지 소유 확인 섀시 (2.5) 비었을 때만 `Systems/{id}/NetworkInterfaces`→`Links.NetworkAdapter` (3) `Systems/{id}/NetworkAdapters`. 카드마다 `Ports`(없으면 `NetworkPorts`) + `NetworkDeviceFunctions`; FirmwarePackageVersion 없으면 `Controllers[0].Links.PCIeDevices[]` 추적 | 카드: Manufacturer/Model/PartNumber/SerialNumber/fw/port_count(NetworkPortCount 합, 없으면 수집 포트 수). 포트: `_normalize_port_speed` 120-152, 분류 `_classify_port_protocol` 3991-4048 + lt_fc 규칙 + `_ib_decision` 3908-3943, 주소 = AssociatedNetworkAddresses → Ethernet.AssociatedMACAddresses → FibreChannel.AssociatedWWNs/AssociatedWorldWideNames. 카드 mac/link/speed 는 첫 활성 포트 fold-in(FC/IB 제외). Model 비면 `_fill_adapter_models_from_firmware` 768-803 | ns.yml:664-679 `network.adapters/ports` 는 모듈 값 그대로(`_rf_d_netad`). 보조 섹션이라 status 에 불참(ns.yml:514) |
| `storage.hbas[]` | 위 포트 루프 | 같음 | `_make_fc_hba` 4180-4210; wwpn = NDF `FibreChannel.WWPN/PermanentWWPN`(`_fetch_ndf_index` 4050-4112) → 없으면 `_derive_port_wwpn` 4144-4178(포트 WWN 후보에서 WWNN 배제); link = `_hba_link_status` 4114-4126 (up/down 둘뿐); speed = 포트 CurrentSpeedGbps | ns.yml:672 `hbas: _rf_d_netad.fc_hbas` 그대로 |
| `storage.infiniband[]` | 위 포트 루프 | 같음 | `_ib_decision` → `_append_ib_port` 4235-4252, GUID `_select_ib_guids` 3971-3989 | ns.yml:673 그대로 |
| `network.dns_servers` / `default_gateways` | `gather_bmc`(bmc 담당) 가 `result['_network_meta']` 로 Manager `EthernetInterfaces` 의 NameServers/StaticNameServers/IPv4 Gateway 를 모음 | `Managers/{id}/EthernetInterfaces/*` | — | ns.yml:48-62 `_rf_d_bmc_network` 추출, 114-154 — gateways = 호스트 NIC `addresses[].gateway` ∪ BMC NIC IPv4 gateway, dns = BMC NIC NameServers ∪ StaticNameServers (0.0.0.0/::/''/none 제외) |
| `network.summary` | — | — | — | ns.yml:337-371 — groups 는 `interfaces[]` 를 (speed, model, manufacturer, link_type) 로 묶고 model/manufacturer 는 adapter id-regex 또는 `ports[].associated_address` MAC join, link_type 은 같은 join 의 `ports[].port_type`; `adapter_count` 는 FC/IB 전용 카드 제외(A-4), `port_count = interfaces 수` |
| `storage.controllers[]` / `physical_disks[]` | `gather_storage` rg.py:3662-3722 | `Systems/{id}/Storage` → 멤버 → `StorageControllers`(인라인) 또는 `Controllers` 링크 → 멤버[0] (`_extract_storage_controller_info` 3181-3234) → `Drives[]` 각 GET (`_extract_storage_drives` 3236-3282: CapacityBytes 0/없음 또는 Name 에 "empty" 면 제외). Storage 비-200 → `SimpleStorage` → `SmartStorage`(HPE OEM). 정체 없는 멤버는 섀시 `PCIeDevices` 위치 포함관계로 식별(A-8, 3578-3618). 드라이브 0건이면 섀시 `Drives`(A-10, 3620-3660) | 드라이브: id/name/model/serial/manufacturer/media/protocol/capacity_bytes/health(Health→HealthRollup)/failure_predicted/predicted_life(int) | ns.yml:156-239 — controllers 는 정체·드라이브·볼륨 전무한 멤버 제거(A-6); `physical_disks` 는 name+model+serial 로 중복 제거, `total_mb = floor(bytes/2^20)`; summary ns.yml:307-326 `unit_capacity_gb = floor(total_mb/1024)` |
| `storage.logical_volumes[]` | 같음 | `Storage/{id}/Volumes` → 멤버 GET (`_extract_storage_volumes` 3284-3368; 404 만 조용) | RAIDType(없으면 Dell VolumeType 매핑), `member_drive_ids`(Links.Drives 마지막 세그먼트), JBOD 필터, Name 비면 `Volume {id}`, `total_mb = bytes//2^20`, boot_volume = BootVolume → Dell OEM → None | ns.yml:221-238 그대로 |
| `driver_map`/`portgroups`/`virtual_switches`/`datastores`/`filesystems` | — | — | — | Redfish 는 항상 `[]`(ns.yml 664-679, OS/ESXi 전용 키) |

`sections.yml` `network.empty_value` 에 있는 `bonds/bridges/teams` 키는 Redfish `data.network` 에도 `common/tasks/normalize/build_empty_data.yml` 에도 없다(관찰 O-11).

## 3. 11대 × 필드 검증 상태 표

표기: PASS / ISSUE / NOT_APPLICABLE(N/A) / MOCK_LIMITATION(MOCK) / NOT_CHECKED. "지원 데이터 없음"은 자동 PASS 가 아니라 N/A 또는 MOCK 로 적고 무엇을 확인했는지 근거를 둔다. 기계 판독본은 `03-network-storage.coverage.json`.

### 3.1 network

| server | interfaces[] | adapters[] | ports[] | dns_servers | default_gateways | summary | driver_map / portgroups / virtual_switches | 영역 종합 |
|---|---|---|---|---|---|---|---|---|
| csus3200_01 | PASS — 8 (raw `Systems/Partition0/EthernetInterfaces` 8, 멤버는 `CompositionService/ResourceBlocks/r001u01/Systems/1/EthernetInterfaces/PCIeCardNEthM`, 키 Id/MACAddress/Name 뿐 → link `unknown`·speed null·addresses [] 가 raw 그대로) | PASS — 6 (Chassis/r001u01/NetworkAdapters 7 중 `Rmp` placeholder 제외; Mellanox 4·FC 2; fw 는 `Controllers[0].Links.PCIeDevices`→`PCIeDevices/N.FirmwareVersion` '26.48.1000…'/'9.15.05 (d0d5)' — CSUS-R16 경로 발동 확인) | PASS — 12 (Ethernet 8·FibreChannel 4, 주소=Ethernet.AssociatedMACAddresses / NDF WWPN, LinkStatus 키 없음 → `unknown`) | PASS — `[]` (raw RMC NIC `1`: NameServers [], StaticNameServers [null,null,null]) | PASS — `11.65.23.1` (raw RMC NIC `1`.IPv4Addresses[0].Gateway) | PASS — groups 1(MCX631102×8, link_up 0), adapter_count 4(FC 2장 제외, A-4), port_count 8 | N/A — Redfish 는 `[]` 계약 | PASS |
| csus3200_02 | PASS — 4 (같은 모양) | PASS — 2 (Mellanox 2; FC 카드 없음 — `Chassis/r001u01/NetworkAdapters` = PCIeCard1·9·Rmp, `PCIeDevices` = 1·3·9) | PASS — 4 | PASS — `[]` | PASS — `11.65.23.1` | PASS — adapter_count 2, port_count 4 | N/A | PASS |
| csus3200_03 | PASS — 8 | PASS — 6 | PASS — 12 | PASS — `[]` | PASS — `11.65.23.1` | PASS — adapter_count 4, port_count 8 | N/A | PASS |
| dl380_gen12_01 | PASS — 10 (raw `Systems/1/EthernetInterfaces` 10: Name '' → id 사용, SpeedMbps 키는 있으나 null, LinkStatus 는 up 인 4건만 'LinkUp' 나머지 null → `unknown`; is_primary='78' 첫 LinkUp) | PASS — 7 (FC SN1610Q 2·BCM57414 5, fw FirmwarePackageVersion, mac 은 NIC 만) | PASS — 14 (FC 4: lt FibreChannel·Ethernet 블록=WWPN·`FibreChannel:{}` → FibreChannel; NIC 10 Ethernet; down 포트 speed null) | PASS — `[]` (raw Managers/1/EthernetInterfaces/1 NameServers [], StaticNameServers 0.0.0.0/:: 자리표시자, `Oem.Hpe.IPv4.DNSServers` 도 0.0.0.0) | PASS — `11.65.23.1` | PASS — groups BCM57414×10(link_up 4), adapter_count 5, port_count 10 | N/A | PASS |
| dl380_gen12_02 | PASS — 8 | PASS — 6 | PASS — 12 | PASS | PASS | PASS — adapter_count 4 | N/A | PASS |
| dl380_gen12_03 | PASS(faithful) — 4, LinkStatus 전부 null → `unknown` (raw: 호스트 PowerState Off) | PASS(faithful) — 2 (`DA000004/DA000007`: Manufacturer ''·PartNumber ''·NDF 링크 없음 → manufacturer null; Model 은 raw 에 있음) | PASS(faithful) — 4 (LinkStatus 없음·CurrentSpeedGbps 없음 → unknown/null) | PASS — `[]` | PASS — `11.65.23.1` | PASS — adapter_count 2, port_count 4, link_up 0 | N/A | **ISSUE** `03-storage-001`(교차) — 전원 Off 로 카드 정보가 축약됐는데 network 쪽 notice 없음 |
| dl380_gen12_04 | PASS — 8 (전부 LinkUp) | PASS — 6 | PASS — 12 | PASS | PASS | PASS — link_up 8 | N/A | PASS |
| sr650_v4_01 | PASS — 5 (NIC1~4 + `ToManager`; raw 호스트 NIC 에 LinkStatus 키 없음 → 전부 `unknown`, SpeedMbps 25600/0 — O-3/O-4) | PASS — 2 (E810 OCP 2, fw '5.00 (0x80021D15)') | PASS — 4 (LinkUp/LinkDown·CurrentSpeedGbps 25 → 25000/null) | PASS — `[]` (raw Managers/1/EthernetInterfaces/NIC NameServers [], StaticNameServers 자리표시자) | PASS — `11.65.23.1` | PASS — adapter_count 2, port_count 5(ToManager 포함, O-4), link_up 0(O-3) | N/A | PASS |
| sr650_v4_02 | **ISSUE** `03-network-001` — 9 중 NIC3·4·7·8 은 QLE2772 FC 포트(raw MACAddress 8옥텟 `21:00:F4:C7:AA:A4:6F:FE` 등, SpeedMbps 0) | PASS — 4 (E810 2·QLE2772 2) | PASS — 8 (FC 4: PortProtocol FC·LinkNetworkTechnology FibreChannel·`AssociatedWorldWideNames=[WWPN]`, LinkDown) | PASS | PASS | **ISSUE** `03-network-001` — port_count 9(FC 4 포함), groups 에 `link_type: fibrechannel` 4 | N/A | ISSUE |
| sr650_v4_03 | **ISSUE** `03-network-001` — 15 중 NIC5~8 FC (SpeedMbps 32768/0) | PASS — 7 (E810 OCP 2·PCIe 3·QLE2772 2) | PASS — 14 (FC 4: 포트 1 LinkUp 32 Gbps·포트 2 LinkDown) | PASS | PASS | **ISSUE** `03-network-001` — port_count 15, fibrechannel 그룹 4 | N/A | ISSUE |
| sr650_v4_04 | PASS — 5 | PASS — 2 | PASS — 4 | PASS | PASS | PASS — port_count 5 | N/A | PASS |

### 3.2 storage

| server | controllers[] | physical_disks[] | logical_volumes[] | hbas[] | infiniband[] | summary | datastores / filesystems | 영역 종합 |
|---|---|---|---|---|---|---|---|---|
| csus3200_01 | PASS — 1 (raw `Systems/Partition0/Storage/1` 'Npar 0 Storage' 는 Drives 4 만, 컨트롤러 없음 → A-8 로 `Chassis/r001u01/PCIeDevices/3` 'HPE SR3258p-16i/e PCIe4 Controller'/Adaptec/fw 03.01.50.032-0 식별 + notice) | PASS — 4 (MO001600PYHRE×2·PZWSH×2, SAS SSD, CapacityBytes 1600321314816 → total_mb 1526185, Revision 'HPD0/HPD4' 는 계약 밖) | N/A — raw Storage/1 에 `Volumes` 링크 없음(RAID 구성 비노출) → `[]` | PASS — 4 (SN1100Q ×2카드, wwpn/wwnn = NDF FibreChannel.WWPN/WWNN, fw/vendor 채움, link **down**(Port 에 LinkStatus 키 없음 — notice 2건, ADR-2026-10-19 대로)) | N/A — IB 신호 없음(NDF caps Ethernet/FibreChannel 뿐) | PASS — 1490 GiB ×4 = 5960 | N/A (`[]` 계약) | PASS |
| csus3200_02 | PASS — 1 (A-8 동일) | PASS — 4 (PZWSH×4) | N/A | PASS — 0 (FC 카드 없음: PCIeDevices 1·3·9 = Mellanox·RAID·Mellanox) | N/A | PASS — 5960 | N/A | PASS |
| csus3200_03 | PASS — 1 | PASS — 4 (PYHRE×4) | N/A | PASS — 4 (down + notice) | N/A | PASS | N/A | PASS |
| dl380_gen12_01 | PASS — 1 (`Storage/DE00B000` → `Controllers/0` 'HPE MR416i-o Gen11' fw 52.36.3-6584 SN PZDV…, CacheSummary 8192 MiB 는 계약 밖) | PASS — 2 (Drives 8 중 `64515~64520` 'Empty Bay'(State Absent, CapacityBytes 없음) 6건 필터; life 100.0 → 100, FailurePredicted false, Identifiers NAA 는 미사용 O-8) | PASS — 1 ('OS' RAID1 1525664 MiB, member ['0','1'], boot_volume null — BootVolume 키 없음) | PASS — 4 (SN1610Q ×2카드: wwpn/wwnn NDF, 포트1 up 32 Gbps·포트2 down(LinkState Disabled)) | N/A | PASS — 2980 | N/A | PASS |
| dl380_gen12_02 | PASS — 1 | PASS — 4 (Drive 0·3 은 State `StandbyOffline`·Volumes 0 — physical_disks 에는 health OK 로만 보임 O-9) | PASS — 1 ('MR Volume 239' RAID1, member ['1','2']) | PASS — 4 (전부 down) | N/A | PASS — 5960 | N/A | PASS |
| dl380_gen12_03 | **ISSUE** `03-storage-001` — `[]` (raw `Systems/1/Storage` 200·Members 0; StorageEnclosure 섀시 없음; 그러나 `Chassis/1/PCIeDevices/276` = 'HPE MR416i-o Gen11' fw 52.36.3-6584, PCIeFunctions DeviceClass MassStorageController; 호스트 PowerState Off) | **ISSUE** — 0 (실제 미장착이 아니라 전원 Off 로 인벤토리 미제공 — 가설, 4절) | ISSUE(같은 원인) — `[]` | PASS — 0 (PCIeDevices 269 Video·271/274 NIC·276 RAID — FC 카드 없음 확정) | N/A | ISSUE — 0 GB | N/A | ISSUE |
| dl380_gen12_04 | PASS — 1 | PASS — 4 | PASS — 1 ('OS' RAID1, member ['0','2']) | PASS — 4 (포트1 up ×2) | N/A | PASS — 5960 | N/A | PASS |
| sr650_v4_01 | PASS — 1 (`Storage/controller_slot5` 인라인 StorageControllers[0]: Name 'ThinkSystem RAID 940-16i 8GB Flash…' Model 'SAS3916' fw 52.36.0-6553 → name=Name, controller_model='SAS3916') | PASS — 4 (MZILG1T6HCJR-V7 SAS SSD, life 100, FailurePredicted false, EncryptionAbility SelfEncryptingDrive 는 계약 밖) | PASS — 1 ('OS' RAID1 1524925 MiB, `IsBootCapable` 키는 "부팅 가능 여부"라 boot_volume 근거 아님 O-7) | PASS — 0 (FC PCIe 없음) | N/A | PASS — 1489×4 = 5956 | N/A | PASS |
| sr650_v4_02 | PASS — 1 | PASS — 4 | PASS — 2 ('OS' + Name '' → 'Volume 238' 합성(B48)) | PASS — 4 (QLE2772 ×2: NDF 컬렉션 0건 → wwpn 은 Port `FibreChannel.AssociatedWorldWideNames` 단일값에서 도출 + notice, wwnn null(원천 없음), 전부 down) | N/A | PASS | N/A | PASS |
| sr650_v4_03 | PASS — 1 | PASS — 2 | PASS — 1 | PASS — 4 (포트1 up 32.0 Gbps·포트2 down, wwpn 도출 notice 2건) | N/A | PASS — 2978 | N/A | PASS |
| sr650_v4_04 | PASS — 1 | PASS — 6 (bay 4·5 는 Oem.Lenovo DriveStatus UnconfiguredGood, 볼륨 미소속) | PASS — 2 ('OS' 1524925 + 'Volume 238' 3051757 MiB) | PASS — 0 | N/A | PASS — 2980×4+1489×2 = 14898 | N/A | PASS |

## 4. 이슈 목록

각 항목: 심각도 / 대상 / 필드 / 근거(raw·Tier1) / 코드 / 실제·기대 / 원인(확정·가설) / 영향 / 수정 제안(기존 필드 범위) / 회귀 테스트 / ADR 영향 / 데이터 확실성.

### 03-network-001 — Lenovo XCC3 가 FC HBA 포트를 호스트 `EthernetInterfaces` 로 노출 → `network.interfaces[]`/`summary` 에 FC 포트가 섞임 (MED)

- 대상: sr650_v4_02 (NIC3·NIC4·NIC7·NIC8), sr650_v4_03 (NIC5~NIC8). 1차 7대 해당 없음(r1_Lenovo_SR650_01 은 FC 카드 없음; Dell R740·HPE 는 FC 를 EthernetInterfaces 에 넣지 않음). 기존 모델 중 XCC3 + FC HBA 조합이면 재현 가능.
- 필드: `network.interfaces[].{mac, speed_mbps, kind, link_status}`, `network.summary.{port_count, groups[].link_type}`.
- 근거: raw `extract/sr650_v4_03/redfish/v1/Systems/1/EthernetInterfaces/NIC5/index.json` = `{"Description":"External Ethernet Interface","MACAddress":"21:00:F4:C7:AA:A4:76:42","PermanentMACAddress":"21:00:F4:C7:AA:A4:76:42","SpeedMbps":32768,"Status":{"Health":"OK","State":"Enabled"}, ...}` — 같은 값이 `Chassis/1/NetworkAdapters/slot5_0x4c0000/Ports/1.FibreChannel.AssociatedWorldWideNames[0]` 이고 Tier 1 `storage.hbas[0].wwpn = 21:00:f4:c7:aa:a4:76:42`. Tier 1 `network.interfaces` 에 `{"id":"NIC5","kind":"server_nic","mac":"21:00:f4:c7:aa:a4:76:42","speed_mbps":32768,"link_status":"unknown"}` 가 들어 있고 `summary.port_count=15`, `summary.groups` 에 `{"link_type":"fibrechannel","model":"QLE2772","quantity":4}` 가 있다(요약 join 자체가 이 4건을 FC 로 안다).
- 코드: `rg.py:3724-3765 gather_network` (EthernetInterfaces 멤버를 필터 없이 NIC 로 변환), `ns.yml:65-112 interfaces`, `ns.yml:337-371 summary`(`port_count = interfaces 수`).
- 실제 출력: interfaces 15/9 (FC 4 포함), port_count 15/9, mac 에 8옥텟 WWPN. 기대: `docs/contract/03-fields.md` 6.4 "interfaces = 호스트 서버 NIC", `field_dictionary` `network.interfaces[].mac` 는 MAC — FC 포트는 `ports[]`(FibreChannel)·`hbas[]` 에만 있어야 한다. OS 채널은 FC 포트를 NIC 로 내지 않으므로 채널 간 interfaces 수도 어긋난다.
- 원인(확정): XCC3(IHX438R 2.97) 펌웨어가 FC 포트를 `EthernetInterface` 리소스로 나열한다. 코드는 주소 형식·분류를 보지 않는다.
- 영향: `summary.port_count`·`groups` 왜곡, `interfaces[].mac` 형식 위반, 교차채널 interfaces 수 불일치. status/sections 불변.
- 수정 제안(기존 필드 범위, vendor 분기 없음): (a) `ns.yml interfaces` 또는 `gather_network` 에서 주소가 `ports[]` 의 FibreChannel/FCoE/InfiniBand 포트 `associated_address` 와 같은 항목(summary 가 이미 쓰는 MAC join), 또는 MAC 이 8옥텟(16 hex)인 항목을 interfaces 에서 제외하고 `diagnosis.details.notices` 1건("호스트 EthernetInterfaces 중 FC 포트 N건 제외 — ports/hbas 참조"). (b) 대안: 유지하되 `summary.port_count`/groups 에서만 제외하고 문서화. **결정 주체: 사용자** — 제안은 (a).
- 회귀 테스트: `tests/fixtures/redfish/` 에 sr650_v4_03 축약 recording 추가 후 `interfaces` 에 16-hex 주소 0건·`port_count == 11`·`interfaces mac ∩ hbas wwpn == ∅` 고정; `tests/integration/test_port_classification_invariants.py` 에 INV-5(interfaces 주소는 FC/IB 포트 주소가 아니다)를 전 fixture/baseline 에 적용.
- ADR 영향: ADR-2026-10-19 A-4(adapter_count) 불변. 03-fields 6.4 에 "BMC 가 FC 포트를 EthernetInterfaces 로 내도 interfaces 에 넣지 않는다" 명시 필요. 2026-04-29 lenovo-critical-review 의 summary `link_type` fibrechannel 매핑은 (a) 적용 시 Redfish 에서 더 이상 발동하지 않지만 삭제 불필요.
- 확실성: 확정(raw 2대·Tier1·Tier2 일치).

### 03-storage-001 — 전원 Off 호스트(dl380_gen12_03): Storage 컬렉션 0건·NIC 정보 축약인데 envelope 의 storage/network 에 아무 신호가 없다 (MED)

- 대상: dl380_gen12_03. 1차 7대 해당 없음(전부 PowerState On). 전원이 꺼진 어느 장비든 재현 가능(iLO·XCC 공통 가능성 — 가설).
- 필드: `storage.controllers[]`(`[]`), `physical_disks[]`(0), `logical_volumes[]`, `summary.grand_total_gb`(0); `network.adapters[].manufacturer`(null), `ports[].link_status`(unknown), `interfaces[].link_status`(unknown).
- 근거: raw `Systems/1/index.json` `PowerState: "Off"`, `Oem.Hpe.PostState: "PowerOff"`, `Status.State: "Disabled"`; `Systems/1/Storage/index.json` Members `[]`(200); Chassis 컬렉션에 StorageEnclosure(`DE00B000`) 없음; `Chassis/1/PCIeDevices/276` = `{"Name":"HPE MR416i-o Gen11","Model":"P47781-B21","Manufacturer":"HPE","FirmwareVersion":"52.36.3-6584","SerialNumber":"PZDV…"}` + `PCIeFunctions/1,2.DeviceClass = MassStorageController`; NetworkAdapters 는 `DA000004/DA000007`(Manufacturer ''·NetworkDeviceFunctions 링크 없음·Ports 에 LinkStatus/CurrentSpeedGbps 없음) — 전원 On 인 01·02·04 는 같은 모델·같은 iLO 1.24.00 에서 `DE04x000` 카드에 NDF·LinkStatus·속도를 전부 준다. Tier 1: `storage.controllers=[]`, `physical_disks=[]`, `summary.grand_total_gb=0`, notices 0, errors 0, `status=success`, `sections.storage=success`; `hardware.power_state="Off"` 만 다른 섹션에 있다.
- 코드: `rg.py:3662-3722 gather_storage` — Storage 200 → `_gather_standard_storage(members=[])` → A-10 `_chassis_drives_fallback`: `Chassis/1` 에 `Drives` 링크 없음 → 빈 결과, notice 없음; SmartStorage 는 Storage 가 비-200 일 때만. `rg.py:4834-4987 gather_network_adapters_chassis` — 카드 2장이 Manufacturer 없이 Model 만으로 통과(placeholder 판정은 port_count>0 이라 정상).
- 실제: "디스크 0·컨트롤러 0·NIC 제조사 null" 이 **정상 수집(success)** 으로 나간다. 기대: 소비자가 "미장착" 과 "전원 Off 라 모름" 을 가를 수 있어야 한다(03-fields 6.3.2 가 hbas 에 대해 그렇게 한 것과 같은 원칙).
- 원인: 확정 — Storage 컬렉션이 실제로 비어 있다(파서 누락 아님). 가설 — iLO 는 호스트 POST 이후 호스트 에이전트리스 인벤토리로 Storage/Drives/NDF 를 채우므로 전원 Off 상태에서는 비어 있다(동일 모델 3대와의 대조가 근거; 실장비 전원 On 후 재수집으로 확인 필요).
- 영향: Portal 이 이 서버를 "디스크 없음·컨트롤러 없음" 으로 표시. HPE Gen12 외 벤더도 같은 모양일 수 있다(미확인).
- 수정 제안(기존 필드 범위): (a) `gather_storage`/`gather_network_adapters_chassis` 가 System 의 `PowerState`(gather_system 이 이미 읽은 캐시 응답 — 추가 요청 0)를 보고, Storage 멤버 0건·카드 정보 축약 시 `diagnosis.details.notices` 에 "System PowerState Off — 저장/네트워크 인벤토리가 비어 있을 수 있음" 을 남긴다. (b) 선택: Storage 가 200·0건일 때만 섀시 `PCIeDevices` 의 `PCIeFunctions.DeviceClass == MassStorageController` 장치를 `controllers[]` 항목(controller_model/firmware/manufacturer, drives `[]`)으로 싣는다 — A-8 과 같은 구조적 근거(모델 이름 추정 아님), 발동 조건이 "정보가 없을 때만" 이라 다른 장비 요청 수 불변(PCIeFunctions 요청만 +N). status 는 바꾸지 않는다. **결정 주체: 사용자**(notice 만 / notice+controllers).
- 회귀 테스트: mock2 dl380_gen12_03 축약 recording 으로 notice 존재·status success·controllers 기대값 고정; 전원 On 3대 recording 으로 notice 없음 고정.
- ADR 영향: ADR-2026-10-19 6항 "정보가 없을 때만 발동" 원칙의 자연스러운 확장; 03-fields 6.3 "빈 controllers 의 뜻" 표에 전원 Off 행 추가 필요.
- 확실성: 데이터 확정 / 인과는 가설.

### 03-network-002 — 호스트 NIC 에 LinkStatus/SpeedMbps 가 없을 때 같은 MAC 의 `ports[]` 값을 쓰지 않아 `interfaces[].link_status='unknown'`·`speed_mbps=null` 로 남음 (LOW, 개선)

- 대상: SR650 V4 4대(호스트 NIC 전부 LinkStatus 키 없음 — raw NIC1 키: Description/FQDN/HostName/IPv4Addresses/Id/Links/MACAddress/Name/NameServers/PermanentMACAddress/SpeedMbps/Status), DL380 Gen12 4대(LinkStatus 는 up 일 때만 'LinkUp', down 이면 null; SpeedMbps 항상 null), CSUS 3대(MAC 뿐). r1_Lenovo_SR650_01(XCC 1.22)은 호스트 NIC 에 LinkStatus 가 있었다(Tier1 link_status down/up/unknown) — XCC3 2.97 에서 사라진 펌웨어 차이.
- 근거: sr650_v4_03 Tier1 interfaces 15건 전부 `unknown`, `summary.link_up_count=0`; 같은 envelope `ports[]` 는 `slot13_0x160000/1,2 up 25000`, `slot4_0x3b0000/1,2 up` 등 14건 중 10 up. MAC 이 1:1 로 맞는다(NIC1 `ec:e7:a7:22:4d:05` = port slot13/2 주소). dl380_01: ETH 77 `LinkStatus null` ↔ port DE041000/1 `LinkDown`.
- 코드: `rg.py:3724-3765`(NIC 자체 값만), `ns.yml:65-112`(변환만), `ns.yml:337-371`(summary 는 이미 MAC join 을 한다).
- 실제/기대: 계약상 `unknown` = 미제공이라 틀린 값은 아니다. 다만 같은 봉투 안에 같은 물리 포트의 확정 값이 있다.
- 제안(기존 필드): `ns.yml interfaces` 에서 `link_status` 가 unknown 이고 `speed_mbps` 가 null 인 항목만 `ports[]` 의 같은 주소 항목으로 채운다(NIC 자체 값이 있으면 절대 덮지 않음). 부수 효과: Lenovo `summary.link_up_count` 가 0 → 실제 up 수, HPE down 포트 `unknown` → `down`.
- 회귀: sr650_v4_03 recording 으로 interfaces link_status == 대응 ports 값, NIC 자체 값 보유 fixture(r1_Lenovo·Dell)는 불변.
- ADR 영향: 03-fields 6.4 `link_status` 설명에 "포트 리소스로 보완" 1줄. 확실성: 확정.

### 03-network-003 — Lenovo XCC3 호스트 NIC `SpeedMbps` 가 Gbps×1024(25600/32768)라 같은 봉투의 `ports[].current_link_speed_mbps`(25000/32000)와 다르다 (LOW)

- 대상: SR650 V4 4대 (r1_Lenovo_SR650_01 도 25600). 근거: raw NIC1 `SpeedMbps: 25600`, port `CurrentSpeedGbps: 25.0`; FC NIC5 `32768` vs port `32.0`. Tier1 `summary.groups[].speed_mbps 25600`, `ports[].current_link_speed_mbps 25000`.
- 코드: `rg.py:3752-3760`(`speed_mbps = _safe_int(SpeedMbps)` 원문 보존), `rg.py:120-152 _normalize_port_speed`(Gbps×1000).
- 제안: 값 변조 없음(추정 금지). 03-fields 6.4 에 "Redfish interfaces[].speed_mbps 는 BMC 원문(벤더별 단위 관행 차이), ports[] 는 Gbps×1000" 명시. 02 의 보완 규칙을 적용할 때도 NIC 자체 값은 유지.
- 확실성: 값 확정, 원인(1024 배수 관행) 추정.

### 03-network-004 — `_normalize_port_speed` 가 `CurrentLinkSpeedMbps: 0` 은 0 으로 두고 `CurrentSpeedGbps: 0` 은 null 로 바꿔 링크 없는 포트 표기가 벤더별로 갈린다 (LOW)

- 대상: r1_DELL_R740_01(iDRAC9 NetworkPorts: down 포트 12건 `current_link_speed_mbps: 0`, 호스트 NIC `speed_mbps: 0`); 2차 11대는 Ports 리소스(Gbps)라 null 로 나와 영향 없음.
- 근거: Tier1 r1_DELL ports `NIC.Integrated.1-1 … mbps=0 link=down` vs dl380_01 `DE042000/1 mbps=None link=down`. 코드 `rg.py:120-152 _normalize_port_speed`(`speed_mbps = _safe_int(CurrentLinkSpeedMbps)` → 0 유지, Gbps 쪽만 truthy 분기로 0→None), 2026-06-15 SCHEMA-02 는 Gbps 쪽만 0→null.
- 제안: `_normalize_port_speed` 에서 mbps 0 도 None(ports 전용; interfaces 의 SpeedMbps 0 은 호스트 NIC 원문이라 별도 결정). 회귀: 단위 테스트(CurrentLinkSpeedMbps 0 + LinkDown → None) + `real_dell_r740` golden 갱신(ports 12건 0→null). ADR 영향: 없음(field_dictionary 'null when unlinked' 와 정합). 확실성: 확정.

### 03-network-005 — Lenovo `ToManager`(Redfish Host Interface USB NIC)가 `interfaces[]`·`summary.port_count` 에 서버 NIC 로 센다 (LOW, 관찰에 가까움)

- 대상: SR650 V4 4대, r1_Lenovo_SR650_01. 근거: raw `Systems/1/EthernetInterfaces/ToManager` `{"EthernetInterfaceType":"Physical","Description":"Host Ethernet Interface","InterfaceEnabled":false,"Status":{"State":"Disabled"},"Links":{"HostInterface":"/redfish/v1/Managers/1/HostInterfaces/1"}}`. Tier1 summary groups 에 `model null, speed null, quantity 1` 그룹.
- 계약상 호스트 EthernetInterface 이고 OS 도 usb NIC 로 보므로 결함으로 단정하지 않는다. 제안(선택): `Links.HostInterface` 가 있는 항목은 구조적 신호로 `summary` 집계에서만 제외 — 결정 주체 사용자. 확실성: 확정.

### 03-network-006 — `gather_network` 가 `IPv6Addresses` 를 읽지 않아 `addresses[]` 에 family ipv6 가 절대 없다 (LOW, NOT_CHECKED)

- 대상: 전 벤더. 근거: `rg.py:3736-3742` IPv4Addresses 만; 11대 raw 호스트 NIC 의 IPv4/IPv6 가 전부 `[]` 라 출력 차이는 없다(검증 불가). 제안: `IPv6Addresses[].Address/PrefixLength/AddressOrigin` 을 같은 `addresses[]` 모양(family ipv6, `prefix_length`)으로 — 기존 키. 회귀: IPv6 가 있는 합성 recording. ADR 영향: 03-fields 6.4 (Redfish 도 ipv6) 1줄. 확실성: 코드 확정, 효과 미검증.

### 03-network-007 — `interfaces[].mtu` 가 18대 전부 null — 호스트 NIC 에 MTUSize 가 없고 Lenovo 는 NDF `Ethernet.MTUSize`(1500) 에만 있다 (LOW)

- 근거: raw sr650_v4_03 `NetworkDeviceFunctions/0.Ethernet.MTUSize 1500`(E810), 호스트 NIC 에는 MTUSize 없음; HPE/CSUS/Dell NDF 에는 MTU 없음. 제안: `_fetch_ndf_index` 가 이미 읽는 NDF 에서 MTUSize 를 보존해 MAC join 으로 `mtu` 가 null 일 때만 채움(요청 0 증가). 확실성: 확정(Lenovo 한정 효과).

### 03-storage-002 — `schema/field_dictionary.yml` 의 `storage.controllers[].driver` 가 channel `redfish` 를 포함하지만 Redfish 는 그 키를 내지 않는다 (LOW, 사전 drift)

- 근거: Tier1 controllers 키 = id/name/health/controller_model/controller_firmware/controller_manufacturer/controller_health/drives (18대 동일); 사전 `storage.controllers[].driver | nice | string|null | [redfish, os, esxi]`. Dell OEM `DellStorageController.DriverVersion` 은 r1 에서 `""`. 제안: 사전 channel 에서 redfish 제거(문서 정정) 또는 null 로 emit — 결정 주체 사용자(소비자 shape 영향). 확실성: 확정.

### 03-storage-003 — `physical_disks[].wwn` 을 Redfish `Drive.Identifiers`(NAA) 로 채울 수 있는데 사전이 channel os/esxi 로 묶여 있어 비어 있다 (LOW, 관찰+제안)

- 근거: raw dl380_gen12_01 `Chassis/DE00B000/Drives/0.Identifiers=[{"DurableName":"50000F0005B29261","DurableNameFormat":"NAA"}]`(HPE Gen12 4대 전부; Lenovo·CSUS 는 Identifiers 없음). OS 채널 `wwn` 은 같은 NAA 다(03-fields 6.3.0) — 교차 채널 디스크 조인 키가 된다. 제안: `_extract_storage_drives` 가 Identifiers 중 NAA/EUI 를 `wwn` 으로 — 기존 필드이나 사전 channel 갱신 필요 → 결정 주체 사용자. 확실성: 확정.

## 5. 미추적 Redfish 정보 (기존 필드로 표현 가능한 것만 개선안, 계약 밖은 관찰)

커버리지 보고(`EVID/baseline/coverage/*.txt`)의 미요청 리소스 가운데 network/storage 와 관련된 것을 전수 확인했다(10절 측정 명령).

| # | 미요청 리소스(예) | 내용 | 기존 필드로 표현 가능? | 판단 |
|---|---|---|---|---|
| U-1 | `Chassis/1/NetworkAdapters/*/Ports/N/Settings`, `NetworkAdapters/*/Settings`, `NetworkDeviceFunctions/N/Settings` (HPE 18/32 "untouched Port" 의 대부분) | `@Redfish.Settings` 대기 설정 사본 | 아니오(현재값 아님) | 관찰 — 읽지 않는 것이 맞다 |
| U-2 | `Fabrics/DE00B000/Switches/1/Ports`(HPE 3대) | 저장 인클로저(UBM 백플레인) SAS 확장기 포트 | 아니오 | 관찰(계약 밖) |
| U-3 | `…/Ports/N/Metrics`(PortMetrics 10~12), `NetworkDeviceFunctions/N/Metrics`, `NetworkAdapters/*/Metrics`, `Drives/N/Metrics`, `Volumes/N/Metrics`, `StorageControllerMetrics` (HPE) | 카운터·온도·오류 통계 | 아니오(metrics 필드 없음) | 관찰(계약 밖) |
| U-4 | `Chassis/1/PCIeDevices/*` + `PCIeFunctions/*`(HPE 4대·Lenovo 4대 미요청; CSUS 는 A-8/A-9/CSUS-R16 로 요청) | `DeviceClass`(MassStorageController/NetworkController/SerialBusController), Vendor/Device ID, 카드 PartNumber/SerialNumber/FirmwareVersion | 예 — `03-storage-001` (b) 의 컨트롤러 식별 근거; NIC/HBA 의 fw·PN·SN 은 NetworkAdapter 에 이미 있어 추가 이득 없음 | 제안은 001 에 흡수 |
| U-5 | `Systems/1/PCIDevices/*`(HpeServerPciDevice, HPE OEM) | 장치 이름·버스 위치·`StructuredName` | 표준 PCIeDevices 와 중복 | 관찰 |
| U-6 | `Systems/1/NetworkInterfaces/*`(전 벤더) | `Links.NetworkAdapter` | 이미 A-5 폴백 경로(섀시 경로가 비었을 때만) | PASS(요청 0 설계 확인) |
| U-7 | `Systems/1/Storage/*/StoragePools/*`, `/redfish/v1/Storage`(Lenovo) | RAID 풀 용량/RAID 종류 | Volumes 가 같은 정보를 이미 제공 | 관찰 |
| U-8 | Lenovo Drive `Oem.Lenovo.{DriveStatus(Online/UnconfiguredGood/JBOD), POH, Temperature, TypeString, IsForeign}` / Volume `Oem.Lenovo.{AccessPolicy, CurrentWriteCachePolicy, SpanDepth}` / StorageController `Oem.Lenovo.{MaxVolumeCount, SupportCreateVolumeOnJBOD}` | 드라이브 역할·수명·온도, 볼륨 정책 | 아니오(physical_disks 에 상태/역할 키 없음) | 관찰 — `DriveStatus` 는 03-storage-007(O-9) 과 함께 계약 결정 사항 |
| U-9 | HPE/Dell/Lenovo Controller `CacheSummary{TotalCacheSizeMiB, PersistentCacheSizeMiB}`, HPE `Conditions[WriteCacheProtected]`, Dell `DellControllerBattery` | 캐시 크기·배터리/슈퍼캡 | 아니오 | 관찰(사용자 질문 "캐시/배터리 출처" 답: 노출되지만 계약 필드 없음) |
| U-10 | Drive `Revision`(HPE 'HPD0') / `FirmwareVersion`(Lenovo) | 디스크 펌웨어 | 아니오 | 관찰 |
| U-11 | `Managers/1/HostInterfaces/1/HostEthernetInterfaces`(Lenovo) | BMC 호스트 인터페이스의 USB NIC 정의 | `ToManager` 제외 판단 근거(005) | 관찰 |
| U-12 | NDF `Ethernet.MTUSize`(Lenovo) | MTU | 예 — 03-network-007 | 제안 |
| U-13 | Drive `Identifiers`(NAA) | WWN | 예 — 03-storage-003 | 제안 |
| U-14 | `Chassis/1/NetworkAdapters/4|7|3|6`(HPE 02/04, 404 로 기록) | 장비가 어딘가 링크했지만 존재하지 않는 카드 | — | 관찰 — gather 는 요청하지 않음(컬렉션 멤버가 아님) |

## 6. ADR·문서·테스트 교차 검증

| 문서 | 결정/주장 | 2차 실측 | 판정 |
|---|---|---|---|
| ADR-2026-05-29-hba-ib-csus | FC = `PortProtocol ∈ {FC,FCP,FCoE}` 또는 `NetDevFuncType ∈ {FibreChannel,FCoE}`; "CSUS baseline 이 빈 skeleton" | Lenovo: `PortProtocol: "FC"`(DMTF Protocol enum 값 'FC') 로 분류, HPE iLO7: NDF type 으로, CSUS: NDF caps+`FibreChannel` 블록으로 — 세 모양 모두 FibreChannel. CSUS 2차 3대는 storage(4 disk)·network(8/4 NIC)·hbas 가 채워진다 | 일치. "skeleton" 서술은 2026-10-19 이후 stale(ADR 수정 불필요, 역사 기록) |
| ADR-2026-10-17-infiniband-port-decision | IB 는 현재 모드 신호로만 | 11대 raw 의 Port `LinkNetworkTechnology` 는 Ethernet/FibreChannel 뿐, NDF `NetDevFuncType`/`NetDevFuncCapabilities` 에 InfiniBand 0건, `Port.InfiniBand` 블록 0건 → infiniband `[]`·notice 0 | 오탐 0 확인. 실장비 IB 검증은 여전히 없음(ADR 자체도 "실장비 미검증") |
| ADR-2026-10-18 / ADR-2026-10-19(hba link two values) | hbas link 는 up/down 둘뿐, 미제공은 down+notice; "CSUS 는 항상 down" | CSUS 2차(RMC 1.77.30, Redfish 1.19.0)도 FC Port 리소스 키가 `FibreChannel/Id/Name` 뿐 → down + notice(01·03 각 2건). DL380 Gen12(iLO7 1.24.00)·SR650 V4(XCC3 2.97) 는 LinkStatus 를 주고 포트 1 up/포트 2 down 이 실제로 갈린다 | 일치. ADR 의 "HPE 에 문의" 항목은 1.77.30 에서도 미해결 |
| ADR-2026-10-19-csus-single-server-and-summary-fixes | A-4 adapter_count FC 제외, A-6 빈 컨테이너 제거, A-8 PCIe 컨트롤러 식별, A-10 섀시 Drives 폴백 | A-4: CSUS 4/2/4, DL380 5/4/2/4, SR650 2/2/5/2 전부 FC 카드 제외 정확. A-6: r1 CSUS 01/02 의 'Npar 0 Storage' 제거(Tier2 1 → Tier1 0). A-8: 2차 CSUS 3대 notice "PCIe 장치 3(HPE SR3258p-16i/e PCIe4 Controller)" — 2차 fw 03.01.50.032-0(1차 03.01.44.040-0). A-10: 발동 0(Storage 가 드라이브 보유) | 일치 |
| `docs/contract/03-fields.md` 6.4 | interfaces = 호스트 NIC, `link_status` unknown = 미제공, Redfish dns/gateway 는 BMC NIC | 03-network-001(FC 포트 혼입)이 6.4 정의와 어긋남; dns/gateway 출처 확인(BMC NIC: HPE `Managers/1/EthernetInterfaces/1`, Lenovo `…/NIC`, CSUS `Managers/RMC/EthernetInterfaces/1`) | 정정 제안 1건(6.4 에 FC 포트 제외 규칙), 나머지 일치 |
| `docs/contract/03-fields.md` 6.3 "빈 controllers 의 뜻" | 빈 컨테이너 제거(A-6) 설명 | 전원 Off 로 비는 경우 미기술 | 03-storage-001 반영 필요 |
| `schema/field_dictionary.yml` | `storage.controllers[].driver` channel redfish; `physical_disks[].wwn` channel os/esxi | Redfish 는 driver 키를 내지 않음; wwn 은 HPE Gen12 가 NAA 를 줌 | 03-storage-002/003 |
| `schema/sections.yml` `network.empty_value` | bonds/bridges/teams 포함 | Redfish `data.network` 와 `build_empty_data.yml` 모두 그 키 없음(OS 전용) | 관찰 O-11 — 문서 정합 결정 사항(스키마 변경 아님) |
| `tests/integration/test_redfish_hba_coverage_replay.py` | r1 golden fc_hbas 불변, CSUS 는 "링크 상태 미제공" notice 2건 | Tier2 r1 재생 = golden(bios 제외), 2차 CSUS 도 같은 notice 2건 | 일치 |
| `tests/unit/test_fc_*`, `test_network_adapters_*`, `test_redfish_infiniband_classification.py`, `tests/integration/test_synthetic_ib_replay.py` | 합성/1차 모양 | 2차의 새 모양 3종(iLO7 `FibreChannel:{}`+Ethernet 블록 WWPN / XCC3 `PortProtocol FC`+NDF 0건 / 전원 Off 축약 카드)은 코드가 맞게 처리하지만 **fixture 가 없다** | 7절 |
| `tests/unit/test_network_summary_join_at1.py` | HPE iface id '205','206' MAC join | 2차 HPE id 77/78/141… 도 같은 join 으로 model/manufacturer 채움 | 일치 |
| `tests/integration/test_port_classification_invariants.py` INV-1~4 | hbas↔ports 모순 금지 | 18대 Tier1 에서 hbas 가 매핑된 포트는 전부 FibreChannel | 일치. INV-5(interfaces 주소 ≠ FC 포트 주소) 추가 제안 |

## 7. Replay·테스트 허점

- Tier 1(실제 playbook + 미러 HTTPS) 와 Tier 2(모듈 재생) 의 network/storage 산출이 18대 모두 동일(adapters/ports/hbas 바이트 동일, controllers 는 A-6 만) — 정규화 층이 모듈 값을 바꾸는 곳은 A-6 와 interfaces 변환뿐임을 확인.
- 재생이 흉내 내지 못하는 것(`EVID/baseline/README.md` 한계 1~9 외에 내 영역에서 추가): 장비의 `device_error`(CSUS `RawFruData/*` 500·Lenovo `LicenseService` 500)는 gather 가 읽지 않는 경로라 영향 없음; **Ports/NDF/Drives 멤버 수준의 5xx·timeout** 은 11대 어디에도 없어 `_CODE_NON_BLOCKING_SUBRESOURCE` 경로(멤버 실패 → 섹션 failed·host partial)는 이번 실측으로 검증되지 않음(합성 단위 테스트만).
- 1차 축약 fixture 의 replay-miss: `_golden_compare.plain.json` 상 network/storage 차이 0 → 축약이 숨긴 오류 없음(bios 는 다른 영역).
- 새 실측 모양에 fixture 가 없다(회귀 공백): (1) XCC3 FC 포트가 EthernetInterfaces 에 섞인 모양(sr650_v4_02/03), (2) 전원 Off 호스트(dl380_gen12_03: Storage 0건·DA 카드), (3) iLO7 FC Port `FibreChannel: {}` + `Ethernet.AssociatedMACAddresses=[WWPN]`(dl380 01/02/04 — `isinstance({}, dict)` 로 FC 판정되는 경로), (4) XCC3 FC Port `PortProtocol: FC` + NDF 컬렉션 200·0건(sr650_v4_02/03). `tests/reference/redfish/mock2/*.zip` 은 보관용이고 어떤 테스트도 읽지 않는다(`grep -rn mock2 tests/integration tests/unit` 0건). 제안: 네 모양을 `tests/fixtures/redfish/real_*` 식 축약 recording 으로 승격하고 기대값은 손으로 쓴다(코드 출력 스냅샷 금지, 2026-10-17 원칙).
- 과도한 default/stub: `gather_network` 의 `name = Name or Id or ''`(HPE Name '' → id) 는 적절. `physical_disks` 의 "empty" 이름 필터는 HPE 'Empty Bay' 만 걸러졌고 CapacityBytes 부재 조건이 먼저 걸려 이름 휴리스틱은 발동하지 않았다(6건 모두 CapacityBytes 없음).
- 숨겨질 수 있는 오류: `_make_section_runner` 가 "오류 전부 404 & 빈 결과" 를 unsupported 로 분류하므로 전원 Off 로 **200·0건** 인 Storage 는 collected/success 로 남는다(03-storage-001) — 재생도 실장비도 같은 결과라 테스트로 잡히지 않는다.

## 8. 1차 7대 및 기존 모델 영향

| 모델(펌웨어) | 2차와의 차이 | 영향 이슈 |
|---|---|---|
| Dell R740 (iDRAC9 7.00.00.184, 1차) | NetworkPorts(구 스키마) — down 포트 `CurrentLinkSpeedMbps 0` → `ports[].current_link_speed_mbps 0`, 호스트 NIC `SpeedMbps 0`; FC 는 EthernetInterfaces 에 없음; Storage 는 인라인 StorageControllers + Dell OEM BootVirtualDiskFQDD → boot_volume true | 03-network-004 만 해당. 001/002 비해당 |
| HPE DL380 Gen12 (iLO7 1.20.00 1차 / 1.24.00 2차) | 같은 모양(DE 카드·NAA·Empty Bay). 전원 Off 는 2차 03 만 | 03-storage-001(전원 Off 시), 002, 003(wwn), 006 |
| Lenovo SR650 V4 (XCC 1.22 1차 / XCC3 2.97 2차) | 1차는 호스트 NIC 에 LinkStatus 있음, FC 카드 없음; 2차는 LinkStatus 없음 + FC 를 EthernetInterfaces 로 노출 | 03-network-001(FC 보유 XCC3), 002, 003, 005, 007 |
| HPE CSUS 3200 (RMC 1.75.108 1차 / 1.77.30 2차) | 2차는 NDF 에 WWNN 추가, `Controllers[0].Links.PCIeDevices` 로 fw 보강, 호스트 EthernetInterfaces 멤버 존재(1차 01/02 는 0건). Storage 는 그대로 'Npar 0 Storage'(A-8 식별) | 영향 이슈 없음. hbas link 는 두 세대 모두 down(미제공) |
| 그 밖(Cisco/Supermicro/Huawei 등 lab 부재) | 미검증 | 001 의 "FC 포트를 EthernetInterfaces 로" 가 다른 BMC 에도 있을 수 있어 제안을 vendor-agnostic(주소 형식/분류 join)으로 둠 |

## 9. 검증 한계

- 재생 한계는 `EVID/baseline/README.md` 1~9 그대로(인증·익명 범위·timeout·미러 밖 404·헤더). 내 영역에서 미러 밖 요청은 0건(CSUS 11개 미스는 power/thermal).
- 11대에 없는 것: InfiniBand(모드/기능 모두), FCoE 설정 CNA, iSCSI 기능, NVMe(PCIe-only 디스크 포함), SimpleStorage 전용 장비(Dell 은 Storage 우선이라 미발동), SmartStorage(iLO7 5대 모두 `Systems/1/SmartStorage` 미노출·`Oem.Hpe.Links` 에도 없음 → 폴백 체인 3단은 iLO4 합성 fixture 로만), 호스트 NIC 의 IPv4/IPv6 주소, VLAN, 다중 섀시 소유 판정(CSUS 는 `Links.Chassis` 1개).
- 전원 Off 표본 1대(dl380_gen12_03) — 다른 벤더의 전원 Off 모양은 미확인.
- FC-in-EthernetInterfaces 표본 2대(XCC3 2.97) — 다른 XCC 버전에서의 재현 여부 미확인.
- Lenovo `SpeedMbps` 1024 배수의 원인은 추정.
- `tests/unit`/`tests/integration` 은 실행하지 않았다(보고서 외 파일 변경 0, 검증 대상은 Tier 0 로그로 갈음).

## 10. 탐색 경로 기록

- 코드: `rg.py` 함수 목록 전수(`grep -n "^def "`), 2절 표의 함수 본문, `_collect_all_sections`, `main()`; `ns.yml` 1-240·300-432·486-520·660-735; `common/tasks/normalize/build_empty_data.yml`; `schema/sections.yml`; `schema/field_dictionary.yml`(network/storage 항목 전수 dump); `docs/contract/03-fields.md` 6.3~6.4 전문; ADR 2026-05-29·10-17·10-18·10-19 ×2; evidence 2026-06-15 HPE/Lenovo, 2026-10-15/18/19.
- 데이터: 자체 스크립트(`scratchpad/w03/w03_raw_inventory.py`)로 18개 미러의 Systems(EthernetInterfaces·NetworkInterfaces·Storage·SimpleStorage·SmartStorage 경로 probe·PCIeDevices)·Chassis(NetworkAdapters→Ports/NetworkPorts/NDF/Controllers.Links.PCIeDevices, Drives, PCIeDevices→PCIeFunctions)·Managers(EthernetInterfaces·NetworkProtocol) 를 링크 추적으로 전수 적재(`_fsmap.json` 우선, 없으면 경로 조립; 1차 v1 미러는 `:` 포함 경로 7건이 디렉터리 치환으로 로더에서 MISSING — Tier1/2 재생기는 정상 복원하므로 분석에 영향 없음). Tier1 18 envelope 의 network/storage 추출(`w03_tier1.py`), Tier1↔Tier2 비교(`w03_t1_vs_t2.py`), 인벤토리 jsonl 의 `exists_untouched`/비-2xx 집계·PowerState probe(`w03_probe.py`). 모든 산출은 scratchpad 에만 있고 커밋하지 않았다.
- 요청 경로 정본: `EVID/baseline/tier1/<label>/requested_keys.json` 에서 Storage/Drives/Volumes/EthernetInterfaces/NetworkAdapters/Ports/NDF/PCIeDevices 경로 확인(dl380_03 은 `Systems/1/Storage` 1건 뿐, CSUS 는 `Chassis/r001u01/PCIeDevices/*` 7건 — A-8/A-9/CSUS-R16).
- 문제 없음도 확인한 것: MAC 소문자 정규화 18대 0건 위반; interfaces↔ports 같은 MAC 중복은 설계(호스트 뷰/카드 뷰); dns/gateway 출처 BMC NIC(HPE `Oem.Hpe.IPv4.DNSServers` 0.0.0.0 포함 전수 비어 있음); `summary.unit_capacity_gb` GiB·`total_mb` MiB·모듈 `capacity_gb` 십진 GB 의 단위 혼재는 2026-06-15 RJ-1 결정(관찰 O-10); 볼륨 `total_mb` MiB; Empty Bay 6건 필터; Lenovo 빈 Name 볼륨 'Volume 238' 합성; A-8 notice 정확; FC 분류 3모양; hbas link 2값; IB 오탐 0; adapter_count 11대 정확; port_count = interfaces 수; CSUS `Rmp` placeholder 제외; NetworkInterfaces 폴백 미발동(섀시 경로 정상); 18대 Tier1 errors 0.
- 관찰 목록(이슈 아님): O-1 CSUS 호스트 NIC 가 CompositionService ResourceBlocks 경로 · O-2 HPE 호스트 NIC Name '' → id · O-3 Lenovo 호스트 NIC LinkStatus 부재(002) · O-4 ToManager(005) · O-5 dl380_03 DA 카드(001) · O-6 Lenovo wwnn null(원천 없음) · O-7 Lenovo Volume `IsBootCapable` 는 부팅 가능 여부라 boot_volume 근거 아님 · O-8 HPE Drive NAA(003) · O-9 Drive `Status.State`(StandbyOffline/Absent)·Lenovo DriveStatus 는 physical_disks 에 표현 불가(계약 결정) · O-10 용량 단위 혼재(by-design) · O-11 `sections.yml` network.empty_value 의 bonds/bridges/teams 는 Redfish/build_empty_data 모두 없음(문서 정합).
