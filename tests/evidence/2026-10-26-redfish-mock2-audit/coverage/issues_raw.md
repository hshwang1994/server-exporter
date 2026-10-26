| ID | 심각도 | 확실성 | 제목 | 보고서:행 |
|---|---|---|---|---|
| 01-adapter-001 | HIGH | 확정 | Lenovo XCC3 로그인 후 adapter 재선택이 범용 `redfish_lenovo_bmc` 로 강등 | 01-system-hardware-multi-node.md:93 |
| 02-cpu-001 | HIGH | 추정 | HT 비활성 장비에서 `cpu.logical_threads` 가 코어의 2배 | 02-cpu-memory.md:78 |
| 01-hardware-002 | MED | 확정 | `hardware.health` 출처(`Status.Health`)와 사전·계약의 "BMC rollup" 설명 불일치 — iLO 7 에서 OEM 집계와 갈림 | 01-system-hardware-multi-node.md:108 |
| 01-multi_node-003 | MED | 확정 | CSUS mock 기반 baseline·계약 예시가 실 7대와 다름 (ADR-2026-05-12 결정 6 의 교체 의무 미이행) | 01-system-hardware-multi-node.md:120 |
| 02-cpu-002 | MED | 확정 | ADR-2026-10-19 A-2 전제(RMC `LogicalProcessorCount` = 코어 수)가 RMC 1.77.30 에서 불성립 | 02-cpu-memory.md:95 |
| 02-cpu-003 | MED | 확정 | `cpu.manufacturer` 사전 선언·Redfish 미발행, `groups[].manufacturer` 비정규화 | 02-cpu-memory.md:108 |
| 02-memory-001 | MED | 확정 | dl380_gen12_03: `Status` 없는 빈 슬롯 16개가 `memory.slots[]` 에 포함 | 02-cpu-memory.md:138 |
| 02-memory-002 | MED | - | CSUS `slots[].speed_mhz`/`summary.groups[].speed_mhz` 가 실클럭(MHz), 다른 벤더는 MT/s | 02-cpu-memory.md:151 |
| 03-network-001 | MED | 확정 | Lenovo XCC3 가 FC HBA 포트를 호스트 `EthernetInterfaces` 로 노출 → `network.interfaces[]`/`summary` 에 FC 포트가 섞임 | 03-network-storage.md:82 |
| 03-storage-001 | MED | - | 전원 Off 호스트(dl380_gen12_03): Storage 컬렉션 0건·NIC 정보 축약인데 envelope 의 storage/network 에 아무 신호가 없다 | 03-network-storage.md:96 |
| 04-firmware-001 | MED | 확정 | Lenovo BIOS(`UEFI`) · CSUS `Partition0_FW` 가 `category: other` | 04-firmware-bios.md:89 |
| 04-firmware-002 | MED | 확정 | HPE RAID 컨트롤러 `other`, `Embedded Video Controller` 가 `storage_controller` | 04-firmware-bios.md:102 |
| 04-firmware-003 | MED | 확정 | Lenovo 드라이브 백플레인 PSoC 가 `drive` | 04-firmware-bios.md:115 |
| 04-firmware-006 | MED | - | Lenovo `*-Pending` 빈 스테이징 슬롯이 `pending: true` 항목으로 나간다 | 04-firmware-bios.md:150 |
| 04-test-001 | MED | 확정 | Tier 0 순서 의존 실패: `replay_full_mirror.install_fakes` 가 `rg._get` 을 복원 없이 교체 | 04-firmware-bios.md:237 |
| 05-power-001 | MED | - | 전원 Off 호스트(dl380_gen12_03): PSU 2개가 `Absent · 0 W · fw "0.00"` placeholder 로 "PSU 0개" 가 된다 | 05-thermal-power.md:108 |
| 05-power-002 | MED | - | AC 입력 없는 PSU: 벤더별 State 가 달라 `psu_active` 가 갈리고 원인이 봉투에 없다 | 05-thermal-power.md:121 |
| 05-thermal-001 | MED | 확정 | iLO legacy Thermal 의 `Absent` 슬롯 센서가 0 °C 로 `temperatures[]` 에 들어간다 | 05-thermal-power.md:171 |
| 05-thermal-002 | MED | - | 전원 Off 호스트(dl380_gen12_03): 온도 42건·팬 6건이 `UnavailableOffline` + 0 으로 "정상 수집" 된다 | 05-thermal-power.md:183 |
| 06-bmc-001 | MED | - | 복구 Family hint 가 "1차 선택 adapter_id" 라 Lenovo 세대 판정이 장비 값(Manager.Model)이 아니라 adapter 이름에 의존 | 06-bmc.md:105 |
| 01-adapter-011 | LOW | 확정 | 문서·시험이 Lenovo XCC3 adapter 를 "사이트 검증 PASS" 로 기록 — 1차 선택만 검증됐고 재선택은 미검증; HPE 펌웨어 패턴 가상 공백 | 01-system-hardware-multi-node.md:181 |
| 01-correlation-010 | LOW | 확정 | `correlation.bmc_ip` 정의 문서화 — "BMC 가 보고한 첫 IPv4 NIC" 이며 대상 IP 와 다를 수 있음 | 01-system-hardware-multi-node.md:176 |
| 01-hardware-004 | LOW | 확정 | Lenovo XCC3 `bios_date` null — `UpdateService/FirmwareInventory/UEFI.ReleaseDate` 가 있음 | 01-system-hardware-multi-node.md:131 |
| 01-hardware-005 | LOW | - | Lenovo `hardware.oem` 9키 중 7키가 모든 Lenovo 캡처에서 null — 원천 키가 존재하지 않는 매핑 | 01-system-hardware-multi-node.md:140 |
| 01-multi_node-006 | LOW | - | CSUS 고정 경로 404 요청 11개(14건) — Chassis navigation property 를 보지 않는 Power/Thermal 탐색 | 01-system-hardware-multi-node.md:149 |
| 01-multi_node-007 | LOW | 확정 | `composition.resource_blocks[].processor_count/memory_count = 0` — 원천 배열이 없을 때 0 은 거짓 값 | 01-system-hardware-multi-node.md:158 |
| 01-system-008 | LOW | 확정 | `sections.system = not_supported` 인데 `data.system.hostname/fqdn` 은 내보냄 — 계약 정합 결정 필요 (CSUS 는 HostOS 로 더 채울 수 있음) | 01-system-hardware-multi-node.md:163 |
| 01-system-009 | LOW | 확정 | ADR-2026-10-15 재검증 — "RMC 이름 = 서버 이름" 은 2차 3대에서 성립하지만 `hostname_source=system` 의미는 여전히 어긋남 | 01-system-hardware-multi-node.md:169 |
| 02-cpu-004 | LOW | 확정 | `cpu.architecture` 가 Redfish `x86` vs OS/ESXi `x86_64` | 02-cpu-memory.md:120 |
| 02-cpu-005 | LOW | 확정 | `multi_node.partitions[].cpu` 에 `turbo_max_mhz` 없음 (CSUS 7대) | 02-cpu-memory.md:125 |
| 02-cpu-006 | LOW | 확정 | `cores_physical` 가 `TotalCores`(장착) 합, `TotalEnabledCores` 미사용 | 02-cpu-memory.md:130 |
| 02-cpu-007 | LOW | 확정 | `field_dictionary.yml` 에 `cpu.logical_threads` · `cpu.sockets` · `cpu.model` 항목 없음 | 02-cpu-memory.md:134 |
| 02-memory-003 | LOW | 확정 | Lenovo `slots[].locator` 가 `MemoryLocation.Slot` 문자열(`"32"`), `ServiceLabel "DIMM 32"` 미사용 | 02-cpu-memory.md:163 |
| 02-memory-004 | LOW | 확정 | CSUS `rank_count`/`error_correction` null (raw 키 없음) — OEM Label 로 rank 보충 가능 | 02-cpu-memory.md:172 |
| 02-memory-005 | LOW | 확정 | `memory.summary.groups` 가 part_number 전체 문자열로 묶여 같은 모델이 접미사로 분리 (관찰) | 02-cpu-memory.md:177 |
| 03-network-002 | LOW | 확정 | 호스트 NIC 에 LinkStatus/SpeedMbps 가 없을 때 같은 MAC 의 `ports[]` 값을 쓰지 않아 `interfaces[].link_status='unknown'`·`speed_mbps=null` 로 남음 | 03-network-storage.md:110 |
| 03-network-003 | LOW | - | Lenovo XCC3 호스트 NIC `SpeedMbps` 가 Gbps×1024(25600/32768)라 같은 봉투의 `ports[].current_link_speed_mbps`(25000/32000)와 다르다 | 03-network-storage.md:120 |
| 03-network-004 | LOW | 확정 | `_normalize_port_speed` 가 `CurrentLinkSpeedMbps: 0` 은 0 으로 두고 `CurrentSpeedGbps: 0` 은 null 로 바꿔 링크 없는 포트 표기가 벤더별로 갈린다 | 03-network-storage.md:127 |
| 03-network-005 | LOW | 확정 | Lenovo `ToManager`(Redfish Host Interface USB NIC)가 `interfaces[]`·`summary.port_count` 에 서버 NIC 로 센다 | 03-network-storage.md:133 |
| 03-network-006 | LOW | - | `gather_network` 가 `IPv6Addresses` 를 읽지 않아 `addresses[]` 에 family ipv6 가 절대 없다 | 03-network-storage.md:138 |
| 03-network-007 | LOW | 확정 | `interfaces[].mtu` 가 18대 전부 null — 호스트 NIC 에 MTUSize 가 없고 Lenovo 는 NDF `Ethernet.MTUSize`(1500) 에만 있다 | 03-network-storage.md:142 |
| 03-storage-002 | LOW | 확정 | `schema/field_dictionary.yml` 의 `storage.controllers[].driver` 가 channel `redfish` 를 포함하지만 Redfish 는 그 키를 내지 않는다 | 03-network-storage.md:146 |
| 03-storage-003 | LOW | 확정 | `physical_disks[].wwn` 을 Redfish `Drive.Identifiers`(NAA) 로 채울 수 있는데 사전이 channel os/esxi 로 묶여 있어 비어 있다 | 03-network-storage.md:150 |
| 04-bios-001 | LOW | - | Lenovo `hardware.bios_date` null, 원천은 `FirmwareInventory/UEFI.ReleaseDate` | 04-firmware-bios.md:213 |
| 04-bios-002 | LOW | 확정 | `bios.current.attributes` 에 식별·네트워크 정보가 그대로 들어간다 (계약대로, 관찰) | 04-firmware-bios.md:224 |
| 04-bios-003 | LOW | 확정 | CSUS `Bios/Settings` 에 실제 보류 차이 2건 + 주석 키 (계약 밖, 관찰) | 04-firmware-bios.md:231 |
| 04-firmware-004 | LOW | 확정 | FC HBA 분류가 벤더 간 다르다 (Dell 만 `storage_controller`) | 04-firmware-bios.md:128 |
| 04-firmware-005 | LOW | 확정 | CPLD/FPGA 등 잔여 `other` 와 `nvme` 토큰 오분류 | 04-firmware-bios.md:140 |
| 04-firmware-007 | LOW | 확정 | CSUS 보충 항목의 `updateable` 이 null (사전 type boolean) | 04-firmware-bios.md:163 |
| 04-firmware-008 | LOW | 확정 | Dell first-seen dedup 의 접두사 혼재 (관찰) | 04-firmware-bios.md:173 |
| 04-firmware-009 | LOW | - | 전원 Off 스냅샷(dl380_gen12_03)의 13건은 raw 그대로, `updateable` 이 전원 상태를 따른다 | 04-firmware-bios.md:182 |
| 04-firmware-010 | LOW | 확정 | Lenovo 버전 표기가 두 가지 (관찰) | 04-firmware-bios.md:191 |
| 04-firmware-011 | LOW | 확정 | CSUS `hardware.bios_version == bmc.firmware_version`(complex 번들) · bios/bmc 항목 없음 | 04-firmware-bios.md:198 |
| 04-firmware-012 | LOW | 확정 | 계약 문서에 `data.firmware` 절이 없고 category help 가 실제와 다르다 | 04-firmware-bios.md:207 |
| 05-power-003 | LOW | 확정 | Lenovo XCC3 PSU `model` 의 패딩 공백이 그대로 나간다 | 05-thermal-power.md:134 |
| 05-power-004 | LOW | - | CSUS multi_node 섀시 순회가 링크 없는 경로 11건을 요청하고 404 를 재요청한다 | 05-thermal-power.md:143 |
| 05-power-005 | LOW | 확정 | `power_control.power_capacity_watts` 의 뜻이 벤더·경로별로 다른데 사전 정의가 없다 | 05-thermal-power.md:153 |
| 05-power-006 | LOW | 확정 | `schema/field_dictionary.yml` 에 power/thermal 하위 키가 8개뿐이다 | 05-thermal-power.md:160 |
| 05-power-007 | LOW | - | CSUS 소비전력 폴백 사슬의 정의 불일치: Telemetry = DC 출력 합, 최종 폴백 = AC 입력 합 | 05-thermal-power.md:164 |
| 05-thermal-003 | LOW | - | 신 schema(ThermalSubsystem) 경로의 잠재 공백 3종: 2차 raw 로 확인, 18대에선 미발동 | 05-thermal-power.md:195 |
| 05-thermal-004 | LOW | 확정 | 음수 "온도" 항목: Lenovo `CPUn DTS TMargin`, CSUS `P*_THROT_OFFSET` | 05-thermal-power.md:204 |
| 05-thermal-005 | LOW | 확정 | 문서·주석 drift 3건 | 05-thermal-power.md:210 |
| 06-bmc-002 | LOW | - | RMC 가 선언한 `@Redfish.WriteableProperties`(계정: `["Password"]`) 를 쓰기 계약에 쓰지 않음 — 2026-10-14 hotfix 의 미확인 항목("RMC 계정이 `Enabled` 를 GET 에서 노출하는가")은 7/7 미러로 답이 나옴 | 06-bmc.md:118 |
| 06-bmc-003 | LOW | 확정 | HPE iLO 7 `bmc.timezone` null — `Managers/1/DateTime`(`Oem.Hpe.Links.DateTimeService`) 에 `TimeZone {Name, Value, UtcOffset}` 가 있음 | 06-bmc.md:127 |
| 06-bmc-004 | LOW | 확정 | `bmc.datetime` 표기가 벤더마다 다름(iLO: UTC `Z` + `datetime_offset` 분리 / XCC·RMC·iDRAC: 로컬시에 오프셋 포함) — 사전 문구 "datetime_offset 와 함께 해석" 이 모호 | 06-bmc.md:134 |
| 06-bmc-005 | LOW | 확정 | `bmc.ip/mac_address/dns_name` 선택 규칙이 EthernetInterfaces 컬렉션 순서에 의존("IPv4 가 있는 첫 NIC") — iLO 7 의 USB 가상 NIC(`16.1.15.1`)이 뒤에 있어 우연히 안전 | 06-bmc.md:141 |
| 06-bmc-006 | LOW | 확정 | `bmc.name` 이 adapter `manager_layout` 에만 의존 — CSUS 가 layout 없이 수집되면 `iLO`(장비 값 `ManagerType: RackManager`, `Id: RMC` 를 쓰지 않음) | 06-bmc.md:148 |
| 06-bmc-007 | LOW | 확정 | `diagnosis.details` 의 Redfish 전용 키가 계약 문서·baseline 에 없고 `account_service` 의 미진입 shape(`{}`)가 정의돼 있지 않음 | 06-bmc.md:153 |
| 06-bmc-008 | LOW | - | `replay_full_mirror.install_fakes` 가 `redfish_gather._get`/`_get_noauth` 를 영구 교체하고 되돌리지 않음 — Tier 0 `test_redfish_multi_credential_auth.py` 순서 의존 실패 2건의 원인(제품 영 | 06-bmc.md:158 |
| 06-bmc-009 | LOW | 확정 | 사전 `bmc.uuid` 설명이 "Manager.UUID/ServiceIdentification" 인데 코드는 `UUID` 만 읽고 RMC 의 `ServiceIdentification` 은 UUID 가 아니다 | 06-bmc.md:165 |
| 06-bmc-010 | LOW | 확정 | 성공 경로의 `auth_success: true` 가 무조건이라 익명 수집(vendor 미식별 장비, `used_role: anonymous`) 성공도 "실제 인증 성공" 으로 보고된다 — 11대 해당 없음(코드 경로) | 06-bmc.md:169 |
| 02-memory-006 | ? | - | `total_basis` 상수 `physical_installed` (관찰) | 02-cpu-memory.md:182 |
