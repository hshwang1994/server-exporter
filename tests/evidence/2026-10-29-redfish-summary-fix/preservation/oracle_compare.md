# 판별기 ↔ 봉투 대조

- 판별기: `C:/github/ClovirONE/se-indep-20261027/out/oracle/oracle.json` · 봉투: `C:/Users/hshwa/AppData/Local/Temp/claude/C--github-ClovirONE-clovirone-server-gathering/02a5d5b7-d6b8-44e6-a90d-053073c90f95/scratchpad/tier1_after`

## csus3200_01 — 불일치 4

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 4 | 4 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 32 | 32 | = | 판별기 전체 슬롯 32 · 상태 {'Enabled': 32} |
| memory.total_mb | 1048576 | 1048576 | = |  |
| memory.speeds | ["3200"] | ["3200"] | = |  |
| storage.disks | 4 | 4 | = | 판별기 present 4 · absent 0 · links 4 · simple 0 · dup {} |
| storage.disk_serials | ["S6GRNA0L100299", "S6GRNA0L100303", "S7R1NE0YB01181", "S7R1NE0YB01191"] | ["S6GRNA0L100299", "S6GRNA0L100303", "S7R1NE0YB01181", "S7R1NE0YB01191"] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 4 | 4 | = | FC 카드 2 · FC 전용 2 |
| storage.hba_wwpn | ["51:40:2e:c0:17:28:d0:a4", "51:40:2e:c0:17:28:d0:a6", "51:40:2e:c0:17:28:d1:b8", "51:40:2e:c0:17:28:d1:ba"] | ["51:40:2e:c0:17:28:d0:a4", "51:40:2e:c0:17:28:d0:a6", "51:40:2e:c0:17:28:d1:b8", "51:40:2e:c0:17:28:d1:ba"] | = |  |
| storage.hba_adapters | ["PCIeCard11", "PCIeCard14"] | ["PCIeCard11", "PCIeCard14"] | = |  |
| storage.hba_link_status(set) | ["down"] | ["down"] | = | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 8 | 8 | = | 판별기 System EthernetInterfaces 8 · 8옥텟 0 · HostIF류 0 · 봉투 kind ['server_nic'] |
| network.adapters | 5 | 6 | **≠** | 판별기 카드 전체 7(FC 2) · System 경로 0 |
| network.ports(eth) | 12 | 12 | = | 봉투 port_type ['Ethernet', 'FibreChannel'] |
| power.psu | 4 | 4 | = | 판별기 Absent 0 · 입력0 [] |
| thermal.temps | 63 | 63 | = | 판별기 전체 63 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 10 | 10 | = | 판별기 전체 10 · Absent 0 · 비-Enabled 0 |
| firmware.count | 2 | 13 | **≠** | 판별기 FirmwareInventory 2 · Disabled∧무버전 0 · 봉투 category ['nic', 'other', 'psu', 'storage_controller'] |
| bmc.model∈managers | true | true | = | 봉투 'Compute Scale-up Server 3200, 4S XNC Base Chassis' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.77.30-20260911_061319' |
| hardware.model | null | "Compute Scale-up Server 3200" | **≠** |  |

## csus3200_02 — 불일치 5

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 4 | 4 | = |  |
| cpu.cores_total | 112 | 112 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 16 | 16 | = | 판별기 전체 슬롯 16 · 상태 {'Enabled': 16} |
| memory.total_mb | 524288 | 524288 | = |  |
| memory.speeds | ["3200"] | ["3200"] | = |  |
| storage.disks | 4 | 4 | = | 판별기 present 4 · absent 0 · links 4 · simple 0 · dup {} |
| storage.disk_serials | ["S6GRNE0L100110", "S6GRNE0L100111", "S6GRNE0L100112", "S6GRNE0L100113"] | ["S6GRNE0L100110", "S6GRNE0L100111", "S6GRNE0L100112", "S6GRNE0L100113"] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 0 | 0 | = | FC 카드 0 · FC 전용 0 |
| storage.hba_wwpn | [] | [] | = |  |
| storage.hba_adapters | [] | [] | = |  |
| storage.hba_link_status(set) | [] | [] | = | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 4 | 4 | = | 판별기 System EthernetInterfaces 4 · 8옥텟 0 · HostIF류 0 · 봉투 kind ['server_nic'] |
| network.adapters | 3 | 2 | **≠** | 판별기 카드 전체 3(FC 0) · System 경로 0 |
| network.ports(eth) | 8 | 4 | **≠** | 봉투 port_type ['Ethernet'] |
| power.psu | 4 | 4 | = | 판별기 Absent 0 · 입력0 [] |
| thermal.temps | 47 | 47 | = | 판별기 전체 47 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 10 | 10 | = | 판별기 전체 10 · Absent 0 · 비-Enabled 0 |
| firmware.count | 2 | 9 | **≠** | 판별기 FirmwareInventory 2 · Disabled∧무버전 0 · 봉투 category ['nic', 'other', 'psu', 'storage_controller'] |
| bmc.model∈managers | true | true | = | 봉투 'Compute Scale-up Server 3200, 4S XNC Base Chassis' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.77.30-20260911_061319' |
| hardware.model | null | "Compute Scale-up Server 3200" | **≠** |  |

## csus3200_03 — 불일치 4

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 4 | 4 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 16 | 16 | = | 판별기 전체 슬롯 16 · 상태 {'Enabled': 16} |
| memory.total_mb | 524288 | 524288 | = |  |
| memory.speeds | ["3200"] | ["3200"] | = |  |
| storage.disks | 4 | 4 | = | 판별기 present 4 · absent 0 · links 4 · simple 0 · dup {} |
| storage.disk_serials | ["S7R1NE0YB01170", "S7R1NE0YB01171", "S7R1NE0YB01172", "S7R1NE0YB01173"] | ["S7R1NE0YB01170", "S7R1NE0YB01171", "S7R1NE0YB01172", "S7R1NE0YB01173"] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 4 | 4 | = | FC 카드 2 · FC 전용 2 |
| storage.hba_wwpn | ["51:40:2e:c0:18:1c:28:cc", "51:40:2e:c0:18:1c:28:ce", "51:40:2e:c0:18:1c:28:d4", "51:40:2e:c0:18:1c:28:d6"] | ["51:40:2e:c0:18:1c:28:cc", "51:40:2e:c0:18:1c:28:ce", "51:40:2e:c0:18:1c:28:d4", "51:40:2e:c0:18:1c:28:d6"] | = |  |
| storage.hba_adapters | ["PCIeCard11", "PCIeCard14"] | ["PCIeCard11", "PCIeCard14"] | = |  |
| storage.hba_link_status(set) | ["down"] | ["down"] | = | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 8 | 8 | = | 판별기 System EthernetInterfaces 8 · 8옥텟 0 · HostIF류 0 · 봉투 kind ['server_nic'] |
| network.adapters | 5 | 6 | **≠** | 판별기 카드 전체 7(FC 2) · System 경로 0 |
| network.ports(eth) | 12 | 12 | = | 봉투 port_type ['Ethernet', 'FibreChannel'] |
| power.psu | 4 | 4 | = | 판별기 Absent 0 · 입력0 [] |
| thermal.temps | 47 | 47 | = | 판별기 전체 47 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 10 | 10 | = | 판별기 전체 10 · Absent 0 · 비-Enabled 0 |
| firmware.count | 2 | 13 | **≠** | 판별기 FirmwareInventory 2 · Disabled∧무버전 0 · 봉투 category ['nic', 'other', 'psu', 'storage_controller'] |
| bmc.model∈managers | true | true | = | 봉투 'Compute Scale-up Server 3200, 4S XNC Base Chassis' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.77.30-20260911_061319' |
| hardware.model | null | "Compute Scale-up Server 3200" | **≠** |  |

## dl380_gen12_01 — 불일치 4

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 2 | 2 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 16 | 16 | = | 판별기 전체 슬롯 32 · 상태 {'Enabled': 16, 'Absent': 16} |
| memory.total_mb | 1572864 | 1572864 | = |  |
| memory.speeds | ["6400"] | ["6400"] | = |  |
| storage.disks | 2 | 2 | = | 판별기 present 2 · absent 6 · links 8 · simple 0 · dup {} |
| storage.disk_serials | ["S7R1NE0YB01553", "S7R1NE0YB01554"] | ["S7R1NE0YB01553", "S7R1NE0YB01554"] | = |  |
| storage.disk_wwn_count | 2 | 2 | = |  |
| storage.hbas | 4 | 4 | = | FC 카드 2 · FC 전용 2 |
| storage.hba_wwpn | ["51:40:2e:c0:20:91:1f:2c", "51:40:2e:c0:20:91:1f:2e", "51:40:2e:c0:20:91:20:28", "51:40:2e:c0:20:91:20:2a"] | ["51:40:2e:c0:20:91:1f:2c", "51:40:2e:c0:20:91:1f:2e", "51:40:2e:c0:20:91:20:28", "51:40:2e:c0:20:91:20:2a"] | = |  |
| storage.hba_adapters | ["DE040000", "DE043000"] | ["DE040000", "DE043000"] | = |  |
| storage.hba_link_status(set) | ["linkdown", "linkup"] | ["down", "up"] | **≠** | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 10 | 10 | = | 판별기 System EthernetInterfaces 10 · 8옥텟 0 · HostIF류 0 · 봉투 kind ['server_nic'] |
| network.adapters | 5 | 7 | **≠** | 판별기 카드 전체 7(FC 2) · System 경로 0 |
| network.ports(eth) | 10 | 14 | **≠** | 봉투 port_type ['Ethernet', 'FibreChannel'] |
| power.psu | 2 | 2 | = | 판별기 Absent 0 · 입력0 ['HpeServerPowerSupply:LineInputVoltage'] |
| thermal.temps | 49 | 49 | = | 판별기 전체 56 · Absent 7 · 비-Enabled 0 |
| thermal.fans | 6 | 6 | = | 판별기 전체 6 · Absent 0 · 비-Enabled 0 |
| firmware.count | 25 | 25 | = | 판별기 FirmwareInventory 25 · Disabled∧무버전 0 · 봉투 category ['backplane', 'bios', 'bmc', 'cpld', 'drive', 'nic', 'other', 'psu', 'storage_controller', 'tpm'] |
| bmc.model∈managers | true | true | = | 봉투 'iLO 7' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.24.00 Aug 01 2026' |
| hardware.model | "HPE ProLiant Compute DL380 Gen12" | "HPE ProLiant Compute DL380 Gen12" | = |  |

## dl380_gen12_02 — 불일치 4

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 2 | 2 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 8 | 8 | = | 판별기 전체 슬롯 32 · 상태 {'Absent': 24, 'Enabled': 8} |
| memory.total_mb | 262144 | 262144 | = |  |
| memory.speeds | ["6400"] | ["6400"] | = |  |
| storage.disks | 4 | 4 | = | 판별기 present 4 · absent 4 · links 8 · simple 0 · dup {} |
| storage.disk_serials | ["S6GRNN0Y801909", "S6GRNN0Y801910", "S7R1NE0YB01615", "S7R1NE0YB01713"] | ["S6GRNN0Y801909", "S6GRNN0Y801910", "S7R1NE0YB01615", "S7R1NE0YB01713"] | = |  |
| storage.disk_wwn_count | 4 | 4 | = |  |
| storage.hbas | 4 | 4 | = | FC 카드 2 · FC 전용 2 |
| storage.hba_wwpn | ["51:40:2e:c0:20:91:1c:dc", "51:40:2e:c0:20:91:1c:de", "51:40:2e:c0:20:91:1c:e0", "51:40:2e:c0:20:91:1c:e2"] | ["51:40:2e:c0:20:91:1c:dc", "51:40:2e:c0:20:91:1c:de", "51:40:2e:c0:20:91:1c:e0", "51:40:2e:c0:20:91:1c:e2"] | = |  |
| storage.hba_adapters | ["DE041000", "DE044000"] | ["DE041000", "DE044000"] | = |  |
| storage.hba_link_status(set) | ["linkdown"] | ["down"] | **≠** | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 8 | 8 | = | 판별기 System EthernetInterfaces 8 · 8옥텟 0 · HostIF류 0 · 봉투 kind ['server_nic'] |
| network.adapters | 4 | 6 | **≠** | 판별기 카드 전체 6(FC 2) · System 경로 0 |
| network.ports(eth) | 8 | 12 | **≠** | 봉투 port_type ['Ethernet', 'FibreChannel'] |
| power.psu | 2 | 2 | = | 판별기 Absent 0 · 입력0 ['HpeServerPowerSupply:LineInputVoltage'] |
| thermal.temps | 36 | 36 | = | 판별기 전체 44 · Absent 8 · 비-Enabled 0 |
| thermal.fans | 6 | 6 | = | 판별기 전체 6 · Absent 0 · 비-Enabled 0 |
| firmware.count | 25 | 25 | = | 판별기 FirmwareInventory 25 · Disabled∧무버전 0 · 봉투 category ['backplane', 'bios', 'bmc', 'cpld', 'drive', 'nic', 'other', 'psu', 'storage_controller', 'tpm'] |
| bmc.model∈managers | true | true | = | 봉투 'iLO 7' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.24.00 Aug 01 2026' |
| hardware.model | "HPE ProLiant Compute DL380 Gen12" | "HPE ProLiant Compute DL380 Gen12" | = |  |

## dl380_gen12_03 — 불일치 1

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 2 | 2 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 16 | 16 | = | 판별기 전체 슬롯 32 · 상태 {'Enabled': 16, 'None': 16} |
| memory.total_mb | 524288 | 524288 | = |  |
| memory.speeds | ["6400"] | ["6400"] | = |  |
| storage.disks | 0 | 0 | = | 판별기 present 0 · absent 0 · links 0 · simple 0 · dup {} |
| storage.disk_serials | [] | [] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 0 | 0 | = | FC 카드 0 · FC 전용 0 |
| storage.hba_wwpn | [] | [] | = |  |
| storage.hba_adapters | [] | [] | = |  |
| storage.hba_link_status(set) | [] | [] | = | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 4 | 4 | = | 판별기 System EthernetInterfaces 4 · 8옥텟 0 · HostIF류 0 · 봉투 kind ['server_nic'] |
| network.adapters | 2 | 2 | = | 판별기 카드 전체 2(FC 0) · System 경로 0 |
| network.ports(eth) | 4 | 4 | = | 봉투 port_type ['Ethernet'] |
| power.psu | 2 | 2 | = | 판별기 Absent 2 · 입력0 ['HpeServerPowerSupply:LineInputVoltage', 'HpeServerPowerSupply:LineInputVoltage'] |
| thermal.temps | 42 | 42 | = | 판별기 전체 42 · Absent 0 · 비-Enabled 42 |
| thermal.fans | 6 | 6 | = | 판별기 전체 6 · Absent 0 · 비-Enabled 6 |
| firmware.count | 13 | 13 | = | 판별기 FirmwareInventory 13 · Disabled∧무버전 0 · 봉투 category ['bios', 'bmc', 'cpld', 'nic', 'other', 'tpm'] |
| bmc.model∈managers | true | true | = | 봉투 'iLO 7' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.24.00 Aug 01 2026' |
| hardware.model | "HPE ProLiant Compute DL380 Gen12" | "HPE ProLiant Compute DL380 Gen12" | = |  |

## dl380_gen12_04 — 불일치 4

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 2 | 2 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 8 | 8 | = | 판별기 전체 슬롯 32 · 상태 {'Absent': 24, 'Enabled': 8} |
| memory.total_mb | 262144 | 262144 | = |  |
| memory.speeds | ["6400"] | ["6400"] | = |  |
| storage.disks | 4 | 4 | = | 판별기 present 4 · absent 4 · links 8 · simple 0 · dup {} |
| storage.disk_serials | ["S6GRNN0Y804559", "S6GRNN0Y804714", "S6GRNN0Y804715", "S6GRNN0Y804725"] | ["S6GRNN0Y804559", "S6GRNN0Y804714", "S6GRNN0Y804715", "S6GRNN0Y804725"] | = |  |
| storage.disk_wwn_count | 4 | 4 | = |  |
| storage.hbas | 4 | 4 | = | FC 카드 2 · FC 전용 2 |
| storage.hba_wwpn | ["51:40:2e:c0:20:90:9e:58", "51:40:2e:c0:20:90:9e:5a", "51:40:2e:c0:20:90:9e:d8", "51:40:2e:c0:20:90:9e:da"] | ["51:40:2e:c0:20:90:9e:58", "51:40:2e:c0:20:90:9e:5a", "51:40:2e:c0:20:90:9e:d8", "51:40:2e:c0:20:90:9e:da"] | = |  |
| storage.hba_adapters | ["DE040000", "DE043000"] | ["DE040000", "DE043000"] | = |  |
| storage.hba_link_status(set) | ["linkdown", "linkup"] | ["down", "up"] | **≠** | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 8 | 8 | = | 판별기 System EthernetInterfaces 8 · 8옥텟 0 · HostIF류 0 · 봉투 kind ['server_nic'] |
| network.adapters | 4 | 6 | **≠** | 판별기 카드 전체 6(FC 2) · System 경로 0 |
| network.ports(eth) | 8 | 12 | **≠** | 봉투 port_type ['Ethernet', 'FibreChannel'] |
| power.psu | 2 | 2 | = | 판별기 Absent 0 · 입력0 ['HpeServerPowerSupply:LineInputVoltage'] |
| thermal.temps | 46 | 46 | = | 판별기 전체 54 · Absent 8 · 비-Enabled 0 |
| thermal.fans | 6 | 6 | = | 판별기 전체 6 · Absent 0 · 비-Enabled 0 |
| firmware.count | 25 | 25 | = | 판별기 FirmwareInventory 25 · Disabled∧무버전 0 · 봉투 category ['backplane', 'bios', 'bmc', 'cpld', 'drive', 'nic', 'other', 'psu', 'storage_controller', 'tpm'] |
| bmc.model∈managers | true | true | = | 봉투 'iLO 7' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.24.00 Aug 01 2026' |
| hardware.model | "HPE ProLiant Compute DL380 Gen12" | "HPE ProLiant Compute DL380 Gen12" | = |  |

## sr650_v4_01 — 불일치 2

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 2 | 2 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 2 | 2 | = | 판별기 전체 슬롯 32 · 상태 {'Absent': 30, 'Enabled': 2} |
| memory.total_mb | 131072 | 131072 | = |  |
| memory.speeds | ["6400"] | ["6400"] | = |  |
| storage.disks | 4 | 4 | = | 판별기 present 4 · absent 0 · links 4 · simple 0 · dup {} |
| storage.disk_serials | ["Y620001H", "Y62000AK", "Y62000G6", "Y62000GF"] | ["Y620001H", "Y62000AK", "Y62000G6", "Y62000GF"] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 0 | 0 | = | FC 카드 0 · FC 전용 0 |
| storage.hba_wwpn | [] | [] | = |  |
| storage.hba_adapters | [] | [] | = |  |
| storage.hba_link_status(set) | [] | [] | = | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 4 | 5 | **≠** | 판별기 System EthernetInterfaces 5 · 8옥텟 0 · HostIF류 1 · 봉투 kind ['server_nic'] |
| network.adapters | 2 | 2 | = | 판별기 카드 전체 2(FC 0) · System 경로 0 |
| network.ports(eth) | 4 | 4 | = | 봉투 port_type ['Ethernet'] |
| power.psu | 2 | 2 | = | 판별기 Absent 0 · 입력0 ['PSU1:PowerInputWatts'] |
| thermal.temps | 8 | 8 | = | 판별기 전체 8 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 6 | 6 | = | 판별기 전체 6 · Absent 0 · 비-Enabled 0 |
| firmware.count | 24 | 24 | = | 판별기 FirmwareInventory 28 · Disabled∧무버전 4 · 봉투 category ['backplane', 'bios', 'bmc', 'cpld', 'drive', 'driver_pack', 'nic', 'other', 'psu', 'storage_controller'] |
| bmc.model∈managers | true | true | = | 봉투 'Lenovo XClarity Controller 3' |
| bmc.firmware∈managers | true | true | = | 봉투 'IHX438R 2.97 20260910' |
| hardware.model | "ThinkSystem SR650 V4" | "ThinkSystem SR650 V4" | = |  |

## sr650_v4_02 — 불일치 5

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 2 | 2 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 2 | 2 | = | 판별기 전체 슬롯 32 · 상태 {'Absent': 30, 'Enabled': 2} |
| memory.total_mb | 131072 | 131072 | = |  |
| memory.speeds | ["6400"] | ["6400"] | = |  |
| storage.disks | 4 | 4 | = | 판별기 present 4 · absent 0 · links 4 · simple 0 · dup {} |
| storage.disk_serials | ["Y6200017", "Y62000AE", "Y62000G3", "Y62000GA"] | ["Y6200017", "Y62000AE", "Y62000G3", "Y62000GA"] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 4 | 4 | = | FC 카드 2 · FC 전용 2 |
| storage.hba_wwpn | ["21:00:f4:c7:aa:a4:6f:fe", "21:00:f4:c7:aa:a4:6f:ff", "21:00:f4:c7:aa:a4:70:1a", "21:00:f4:c7:aa:a4:70:1b"] | ["21:00:f4:c7:aa:a4:6f:fe", "21:00:f4:c7:aa:a4:6f:ff", "21:00:f4:c7:aa:a4:70:1a", "21:00:f4:c7:aa:a4:70:1b"] | = |  |
| storage.hba_adapters | ["slot5_0x4c0000", "slot8_0xc90000"] | ["slot5_0x4c0000", "slot8_0xc90000"] | = |  |
| storage.hba_link_status(set) | ["linkdown"] | ["down"] | **≠** | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 4 | 5 | **≠** | 판별기 System EthernetInterfaces 9 · 8옥텟 4 · HostIF류 1 · 봉투 kind ['server_nic'] |
| network.adapters | 2 | 4 | **≠** | 판별기 카드 전체 4(FC 2) · System 경로 0 |
| network.ports(eth) | 4 | 8 | **≠** | 봉투 port_type ['Ethernet', 'FibreChannel'] |
| power.psu | 2 | 2 | = | 판별기 Absent 0 · 입력0 ['PSU1:PowerInputWatts'] |
| thermal.temps | 8 | 8 | = | 판별기 전체 8 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 6 | 6 | = | 판별기 전체 6 · Absent 0 · 비-Enabled 0 |
| firmware.count | 26 | 26 | = | 판별기 FirmwareInventory 30 · Disabled∧무버전 4 · 봉투 category ['backplane', 'bios', 'bmc', 'cpld', 'drive', 'driver_pack', 'nic', 'other', 'psu', 'storage_controller'] |
| bmc.model∈managers | true | true | = | 봉투 'Lenovo XClarity Controller 3' |
| bmc.firmware∈managers | true | true | = | 봉투 'IHX438R 2.97 20260910' |
| hardware.model | "ThinkSystem SR650 V4" | "ThinkSystem SR650 V4" | = |  |

## sr650_v4_03 — 불일치 5

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 2 | 2 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 16 | 16 | = | 판별기 전체 슬롯 32 · 상태 {'Absent': 16, 'Enabled': 16} |
| memory.total_mb | 1048576 | 1048576 | = |  |
| memory.speeds | ["6400"] | ["6400"] | = |  |
| storage.disks | 2 | 2 | = | 판별기 present 2 · absent 0 · links 2 · simple 0 · dup {} |
| storage.disk_serials | ["Y63000BY", "Y63000CA"] | ["Y63000BY", "Y63000CA"] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 4 | 4 | = | FC 카드 2 · FC 전용 2 |
| storage.hba_wwpn | ["21:00:f4:c7:aa:a4:76:42", "21:00:f4:c7:aa:a4:76:43", "21:00:f4:c7:aa:a4:7f:ba", "21:00:f4:c7:aa:a4:7f:bb"] | ["21:00:f4:c7:aa:a4:76:42", "21:00:f4:c7:aa:a4:76:43", "21:00:f4:c7:aa:a4:7f:ba", "21:00:f4:c7:aa:a4:7f:bb"] | = |  |
| storage.hba_adapters | ["slot5_0x4c0000", "slot6_0xa70000"] | ["slot5_0x4c0000", "slot6_0xa70000"] | = |  |
| storage.hba_link_status(set) | ["linkdown", "linkup"] | ["down", "up"] | **≠** | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 10 | 11 | **≠** | 판별기 System EthernetInterfaces 15 · 8옥텟 4 · HostIF류 1 · 봉투 kind ['server_nic'] |
| network.adapters | 5 | 7 | **≠** | 판별기 카드 전체 7(FC 2) · System 경로 0 |
| network.ports(eth) | 10 | 14 | **≠** | 봉투 port_type ['Ethernet', 'FibreChannel'] |
| power.psu | 2 | 2 | = | 판별기 Absent 0 · 입력0 ['PSU1:PowerInputWatts'] |
| thermal.temps | 22 | 22 | = | 판별기 전체 22 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 6 | 6 | = | 판별기 전체 6 · Absent 0 · 비-Enabled 0 |
| firmware.count | 36 | 36 | = | 판별기 FirmwareInventory 40 · Disabled∧무버전 4 · 봉투 category ['backplane', 'bios', 'bmc', 'cpld', 'drive', 'driver_pack', 'nic', 'other', 'psu', 'storage_controller'] |
| bmc.model∈managers | true | true | = | 봉투 'Lenovo XClarity Controller 3' |
| bmc.firmware∈managers | true | true | = | 봉투 'IHX438R 2.97 20260910' |
| hardware.model | "ThinkSystem SR650 V4" | "ThinkSystem SR650 V4" | = |  |

## sr650_v4_04 — 불일치 2

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 2 | 2 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 8 | 8 | = | 판별기 전체 슬롯 32 · 상태 {'Absent': 24, 'Enabled': 8} |
| memory.total_mb | 262144 | 262144 | = |  |
| memory.speeds | ["6400"] | ["6400"] | = |  |
| storage.disks | 6 | 6 | = | 판별기 present 6 · absent 0 · links 6 · simple 0 · dup {} |
| storage.disk_serials | ["W61000T4", "W61000VZ", "W610012P", "W610013Z", "Y63001CN", "Y63001CX"] | ["W61000T4", "W61000VZ", "W610012P", "W610013Z", "Y63001CN", "Y63001CX"] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 0 | 0 | = | FC 카드 0 · FC 전용 0 |
| storage.hba_wwpn | [] | [] | = |  |
| storage.hba_adapters | [] | [] | = |  |
| storage.hba_link_status(set) | [] | [] | = | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 4 | 5 | **≠** | 판별기 System EthernetInterfaces 5 · 8옥텟 0 · HostIF류 1 · 봉투 kind ['server_nic'] |
| network.adapters | 2 | 2 | = | 판별기 카드 전체 2(FC 0) · System 경로 0 |
| network.ports(eth) | 4 | 4 | = | 봉투 port_type ['Ethernet'] |
| power.psu | 2 | 2 | = | 판별기 Absent 0 · 입력0 ['PSU1:PowerInputWatts'] |
| thermal.temps | 14 | 14 | = | 판별기 전체 14 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 6 | 6 | = | 판별기 전체 6 · Absent 0 · 비-Enabled 0 |
| firmware.count | 26 | 26 | = | 판별기 FirmwareInventory 30 · Disabled∧무버전 4 · 봉투 category ['backplane', 'bios', 'bmc', 'cpld', 'drive', 'driver_pack', 'nic', 'other', 'psu', 'storage_controller'] |
| bmc.model∈managers | true | true | = | 봉투 'Lenovo XClarity Controller 3' |
| bmc.firmware∈managers | true | true | = | 봉투 'IHX438R 2.97 20260910' |
| hardware.model | "ThinkSystem SR650 V4" | "ThinkSystem SR650 V4" | = |  |

## r1_DELL_R740_01 — 불일치 5

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 2 | 2 | = |  |
| cpu.cores_total | 48 | 48 | = |  |
| cpu.manufacturer | ["Intel"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 8 | 8 | = | 판별기 전체 슬롯 8 · 상태 {'Enabled': 8} |
| memory.total_mb | 262144 | 262144 | = |  |
| memory.speeds | ["2933"] | ["2933"] | = |  |
| storage.disks | 4 | 4 | = | 판별기 present 4 · absent 0 · links 4 · simple 5 · dup {} |
| storage.disk_serials | ["WFK4Z9HB", "WFK4ZB44", "WFK4ZB6D", "WFK4ZF7P"] | ["WFK4Z9HB", "WFK4ZB44", "WFK4ZB6D", "WFK4ZF7P"] | = |  |
| storage.disk_wwn_count | 4 | 4 | = |  |
| storage.hbas | 4 | 4 | = | FC 카드 2 · FC 전용 2 |
| storage.hba_wwpn | ["21:00:34:80:0d:6c:2a:4c", "21:00:34:80:0d:6c:2a:4d", "21:00:34:80:0d:6c:2b:e2", "21:00:34:80:0d:6c:2b:e3"] | ["21:00:34:80:0d:6c:2a:4c", "21:00:34:80:0d:6c:2a:4d", "21:00:34:80:0d:6c:2b:e2", "21:00:34:80:0d:6c:2b:e3"] | = |  |
| storage.hba_adapters | ["FC.Slot.1", "FC.Slot.7"] | ["FC.Slot.1", "FC.Slot.7"] | = |  |
| storage.hba_link_status(set) | ["linkdown"] | ["down"] | **≠** | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 12 | 12 | = | 판별기 System EthernetInterfaces 12 · 8옥텟 0 · HostIF류 0 · 봉투 kind ['server_nic'] |
| network.adapters | 5 | 7 | **≠** | 판별기 카드 전체 7(FC 2) · System 경로 0 |
| network.ports(eth) | 12 | 16 | **≠** | 봉투 port_type ['Ethernet', 'FibreChannel'] |
| power.psu | 2 | 2 | = | 판별기 Absent 0 · 입력0 [] |
| thermal.temps | 4 | 4 | = | 판별기 전체 4 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 6 | 6 | = | 판별기 전체 6 · Absent 0 · 비-Enabled 0 |
| firmware.count | 62 | 32 | **≠** | 판별기 FirmwareInventory 62 · Disabled∧무버전 0 · 봉투 category ['backplane', 'bios', 'bmc', 'cpld', 'diagnostic', 'drive', 'driver_pack', 'lifecycle', 'nic', 'other', 'psu', 'service_module', 'storage_contro |
| bmc.model∈managers | true | true | = | 봉투 '14G Monolithic' |
| bmc.firmware∈managers | true | true | = | 봉투 '7.00.00.184' |
| hardware.model | "PowerEdge R740" | "PowerEdge R740" | = |  |

## r1_HPE_CSUS3200_01 — 불일치 4

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 4 | 4 | = |  |
| cpu.cores_total | 32 | 32 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 16 | 16 | = | 판별기 전체 슬롯 16 · 상태 {'Enabled': 16} |
| memory.total_mb | 524288 | 524288 | = |  |
| memory.speeds | ["2400"] | ["2400"] | = |  |
| storage.disks | 0 | 0 | = | 판별기 present 0 · absent 0 · links 0 · simple 0 · dup {} |
| storage.disk_serials | [] | [] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 4 | 4 | = | FC 카드 2 · FC 전용 2 |
| storage.hba_wwpn | ["51:40:2e:c0:20:82:c2:2c", "51:40:2e:c0:20:82:c2:2e", "51:40:2e:c0:20:82:c2:94", "51:40:2e:c0:20:82:c2:96"] | ["51:40:2e:c0:20:82:c2:2c", "51:40:2e:c0:20:82:c2:2e", "51:40:2e:c0:20:82:c2:94", "51:40:2e:c0:20:82:c2:96"] | = |  |
| storage.hba_adapters | ["PCIeCard10", "PCIeCard15"] | ["PCIeCard10", "PCIeCard15"] | = |  |
| storage.hba_link_status(set) | ["down"] | ["down"] | = | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 0 | 0 | = | 판별기 System EthernetInterfaces 0 · 8옥텟 0 · HostIF류 0 · 봉투 kind [] |
| network.adapters | 1 | 2 | **≠** | 판별기 카드 전체 3(FC 2) · System 경로 0 |
| network.ports(eth) | 4 | 4 | = | 봉투 port_type ['FibreChannel'] |
| power.psu | 4 | 4 | = | 판별기 Absent 0 · 입력0 [] |
| thermal.temps | 47 | 47 | = | 판별기 전체 47 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 10 | 10 | = | 판별기 전체 10 · Absent 0 · 비-Enabled 0 |
| firmware.count | 2 | 6 | **≠** | 판별기 FirmwareInventory 2 · Disabled∧무버전 0 · 봉투 category ['other', 'psu'] |
| bmc.model∈managers | true | true | = | 봉투 'Compute Scale-up Server 3200, 4S XNC Base Chassis' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.75.108-20260408_164726' |
| hardware.model | null | "Compute Scale-up Server 3200" | **≠** |  |

## r1_HPE_CSUS3200_02 — 불일치 4

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 4 | 4 | = |  |
| cpu.cores_total | 32 | 32 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 16 | 16 | = | 판별기 전체 슬롯 16 · 상태 {'Enabled': 16} |
| memory.total_mb | 524288 | 524288 | = |  |
| memory.speeds | ["2400"] | ["2400"] | = |  |
| storage.disks | 0 | 0 | = | 판별기 present 0 · absent 0 · links 0 · simple 0 · dup {} |
| storage.disk_serials | [] | [] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 4 | 4 | = | FC 카드 2 · FC 전용 2 |
| storage.hba_wwpn | ["51:40:2e:c0:20:82:ec:10", "51:40:2e:c0:20:82:ec:12", "51:40:2e:c0:20:82:ec:4c", "51:40:2e:c0:20:82:ec:4e"] | ["51:40:2e:c0:20:82:ec:10", "51:40:2e:c0:20:82:ec:12", "51:40:2e:c0:20:82:ec:4c", "51:40:2e:c0:20:82:ec:4e"] | = |  |
| storage.hba_adapters | ["PCIeCard10", "PCIeCard15"] | ["PCIeCard10", "PCIeCard15"] | = |  |
| storage.hba_link_status(set) | ["down"] | ["down"] | = | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 0 | 0 | = | 판별기 System EthernetInterfaces 0 · 8옥텟 0 · HostIF류 0 · 봉투 kind [] |
| network.adapters | 1 | 2 | **≠** | 판별기 카드 전체 3(FC 2) · System 경로 0 |
| network.ports(eth) | 4 | 4 | = | 봉투 port_type ['FibreChannel'] |
| power.psu | 4 | 4 | = | 판별기 Absent 0 · 입력0 [] |
| thermal.temps | 47 | 47 | = | 판별기 전체 47 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 10 | 10 | = | 판별기 전체 10 · Absent 0 · 비-Enabled 0 |
| firmware.count | 2 | 6 | **≠** | 판별기 FirmwareInventory 2 · Disabled∧무버전 0 · 봉투 category ['other', 'psu'] |
| bmc.model∈managers | true | true | = | 봉투 'Compute Scale-up Server 3200, 4S XNC Base Chassis' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.75.108-20260408_164726' |
| hardware.model | null | "Compute Scale-up Server 3200" | **≠** |  |

## r1_HPE_CSUS3200_03 — 불일치 5

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 4 | 4 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 32 | 32 | = | 판별기 전체 슬롯 32 · 상태 {'Enabled': 32} |
| memory.total_mb | 1048576 | 1048576 | = |  |
| memory.speeds | ["2400"] | ["2400"] | = |  |
| storage.disks | 2 | 2 | = | 판별기 present 2 · absent 0 · links 2 · simple 0 · dup {} |
| storage.disk_serials | ["YFN0A0SP0T83", "YFN0A0SR0T83"] | ["YFN0A0SP0T83", "YFN0A0SR0T83"] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 8 | 8 | = | FC 카드 4 · FC 전용 4 |
| storage.hba_wwpn | ["51:40:2e:c0:20:82:eb:e8", "51:40:2e:c0:20:82:eb:ea", "51:40:2e:c0:20:82:ec:00", "51:40:2e:c0:20:82:ec:02", "51:40:2e:c0:20:82:ec:18", "51:40:2e:c0:20:82:ec:1a | ["51:40:2e:c0:20:82:eb:e8", "51:40:2e:c0:20:82:eb:ea", "51:40:2e:c0:20:82:ec:00", "51:40:2e:c0:20:82:ec:02", "51:40:2e:c0:20:82:ec:18", "51:40:2e:c0:20:82:ec:1a | = |  |
| storage.hba_adapters | ["PCIeCard10", "PCIeCard15", "PCIeCard2", "PCIeCard7"] | ["PCIeCard10", "PCIeCard15", "PCIeCard2", "PCIeCard7"] | = |  |
| storage.hba_link_status(set) | ["down"] | ["down"] | = | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 8 | 8 | = | 판별기 System EthernetInterfaces 8 · 8옥텟 0 · HostIF류 0 · 봉투 kind ['server_nic'] |
| network.adapters | 5 | 8 | **≠** | 판별기 카드 전체 9(FC 4) · System 경로 0 |
| network.ports(eth) | 12 | 16 | **≠** | 봉투 port_type ['Ethernet', 'FibreChannel'] |
| power.psu | 4 | 4 | = | 판별기 Absent 0 · 입력0 [] |
| thermal.temps | 63 | 63 | = | 판별기 전체 63 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 10 | 10 | = | 판별기 전체 10 · Absent 0 · 비-Enabled 0 |
| firmware.count | 2 | 15 | **≠** | 판별기 FirmwareInventory 2 · Disabled∧무버전 0 · 봉투 category ['nic', 'other', 'psu', 'storage_controller'] |
| bmc.model∈managers | true | true | = | 봉투 'Compute Scale-up Server 3200, 4S XNC Base Chassis' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.75.108-20260408_164726' |
| hardware.model | null | "Compute Scale-up Server 3200" | **≠** |  |

## r1_HPE_CSUS3200_04 — 불일치 5

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 4 | 4 | = |  |
| cpu.cores_total | 64 | 64 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 32 | 32 | = | 판별기 전체 슬롯 32 · 상태 {'Enabled': 32} |
| memory.total_mb | 1048576 | 1048576 | = |  |
| memory.speeds | ["2400"] | ["2400"] | = |  |
| storage.disks | 2 | 2 | = | 판별기 present 2 · absent 0 · links 2 · simple 0 · dup {} |
| storage.disk_serials | ["YFN0A0CM0T83", "YFN0A0D30T83"] | ["YFN0A0CM0T83", "YFN0A0D30T83"] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 8 | 8 | = | FC 카드 4 · FC 전용 4 |
| storage.hba_wwpn | ["51:40:2e:c0:20:82:eb:cc", "51:40:2e:c0:20:82:eb:ce", "51:40:2e:c0:20:82:ec:54", "51:40:2e:c0:20:82:ec:56", "51:40:2e:c0:20:82:ec:58", "51:40:2e:c0:20:82:ec:5a | ["51:40:2e:c0:20:82:eb:cc", "51:40:2e:c0:20:82:eb:ce", "51:40:2e:c0:20:82:ec:54", "51:40:2e:c0:20:82:ec:56", "51:40:2e:c0:20:82:ec:58", "51:40:2e:c0:20:82:ec:5a | = |  |
| storage.hba_adapters | ["PCIeCard10", "PCIeCard15", "PCIeCard2", "PCIeCard7"] | ["PCIeCard10", "PCIeCard15", "PCIeCard2", "PCIeCard7"] | = |  |
| storage.hba_link_status(set) | ["down"] | ["down"] | = | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 8 | 8 | = | 판별기 System EthernetInterfaces 8 · 8옥텟 0 · HostIF류 0 · 봉투 kind ['server_nic'] |
| network.adapters | 5 | 8 | **≠** | 판별기 카드 전체 9(FC 4) · System 경로 0 |
| network.ports(eth) | 12 | 16 | **≠** | 봉투 port_type ['Ethernet', 'FibreChannel'] |
| power.psu | 4 | 4 | = | 판별기 Absent 0 · 입력0 [] |
| thermal.temps | 63 | 63 | = | 판별기 전체 63 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 10 | 10 | = | 판별기 전체 10 · Absent 0 · 비-Enabled 0 |
| firmware.count | 2 | 15 | **≠** | 판별기 FirmwareInventory 2 · Disabled∧무버전 0 · 봉투 category ['nic', 'other', 'psu', 'storage_controller'] |
| bmc.model∈managers | true | true | = | 봉투 'Compute Scale-up Server 3200, 4S XNC Base Chassis' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.75.108-20260408_164726' |
| hardware.model | null | "Compute Scale-up Server 3200" | **≠** |  |

## r1_HPE_DL380_01 — 불일치 4

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 2 | 2 | = |  |
| cpu.cores_total | 48 | 48 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 16 | 16 | = | 판별기 전체 슬롯 32 · 상태 {'Enabled': 16, 'Absent': 16} |
| memory.total_mb | 1048576 | 1048576 | = |  |
| memory.speeds | ["6400"] | ["6400"] | = |  |
| storage.disks | 2 | 2 | = | 판별기 present 2 · absent 6 · links 8 · simple 0 · dup {} |
| storage.disk_serials | ["S6GRNC0YA00941", "S6GRNC0YA01310"] | ["S6GRNC0YA00941", "S6GRNC0YA01310"] | = |  |
| storage.disk_wwn_count | 2 | 2 | = |  |
| storage.hbas | 4 | 4 | = | FC 카드 2 · FC 전용 2 |
| storage.hba_wwpn | ["51:40:2e:c0:20:8f:39:30", "51:40:2e:c0:20:8f:39:32", "51:40:2e:c0:20:8f:3b:dc", "51:40:2e:c0:20:8f:3b:de"] | ["51:40:2e:c0:20:8f:39:30", "51:40:2e:c0:20:8f:39:32", "51:40:2e:c0:20:8f:3b:dc", "51:40:2e:c0:20:8f:3b:de"] | = |  |
| storage.hba_adapters | ["DE041000", "DE044000"] | ["DE041000", "DE044000"] | = |  |
| storage.hba_link_status(set) | ["linkdown"] | ["down"] | **≠** | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 6 | 6 | = | 판별기 System EthernetInterfaces 6 · 8옥텟 0 · HostIF류 0 · 봉투 kind ['server_nic'] |
| network.adapters | 3 | 5 | **≠** | 판별기 카드 전체 5(FC 2) · System 경로 0 |
| network.ports(eth) | 6 | 10 | **≠** | 봉투 port_type ['Ethernet', 'FibreChannel'] |
| power.psu | 2 | 2 | = | 판별기 Absent 0 · 입력0 [] |
| thermal.temps | 43 | 43 | = | 판별기 전체 52 · Absent 9 · 비-Enabled 0 |
| thermal.fans | 6 | 6 | = | 판별기 전체 6 · Absent 0 · 비-Enabled 0 |
| firmware.count | 22 | 22 | = | 판별기 FirmwareInventory 22 · Disabled∧무버전 0 · 봉투 category ['backplane', 'bios', 'bmc', 'cpld', 'drive', 'nic', 'other', 'psu', 'storage_controller', 'tpm'] |
| bmc.model∈managers | true | true | = | 봉투 'iLO 7' |
| bmc.firmware∈managers | true | true | = | 봉투 '1.20.00 Feb 12 2026' |
| hardware.model | "HPE ProLiant Compute DL380 Gen12" | "HPE ProLiant Compute DL380 Gen12" | = |  |

## r1_Lenovo_SR650_01 — 불일치 2

| 항목 | 판별기 | 봉투 | 같음 | 비고 |
|---|---|---|---|---|
| cpu.sockets | 2 | 2 | = |  |
| cpu.cores_total | 32 | 32 | = |  |
| cpu.manufacturer | ["Intel(R) Corporation"] | "Intel" | **≠** | 원문→정규화 비교는 사람이 |
| memory.slots(populated) | 16 | 16 | = | 판별기 전체 슬롯 32 · 상태 {'Absent': 16, 'Enabled': 16} |
| memory.total_mb | 1048576 | 1048576 | = |  |
| memory.speeds | ["6400"] | ["6400"] | = |  |
| storage.disks | 4 | 4 | = | 판별기 present 4 · absent 0 · links 4 · simple 0 · dup {} |
| storage.disk_serials | ["0024081W0ZUH", "0024081W0ZUK", "S76TNA0X602703", "S76TNA0X602704"] | ["0024081W0ZUH", "0024081W0ZUK", "S76TNA0X602703", "S76TNA0X602704"] | = |  |
| storage.disk_wwn_count | 0 | 0 | = |  |
| storage.hbas | 0 | 0 | = | FC 카드 0 · FC 전용 0 |
| storage.hba_wwpn | [] | [] | = |  |
| storage.hba_adapters | [] | [] | = |  |
| storage.hba_link_status(set) | [] | [] | = | 포트 LinkStatus 원값 → 봉투 enum 매핑은 사람이 |
| network.if_eight_octet | 0 | 0 | = |  |
| network.if_has_wwpn | 0 | 0 | = |  |
| network.interfaces | 12 | 13 | **≠** | 판별기 System EthernetInterfaces 13 · 8옥텟 0 · HostIF류 1 · 봉투 kind ['server_nic'] |
| network.adapters | 3 | 3 | = | 판별기 카드 전체 3(FC 0) · System 경로 0 |
| network.ports(eth) | 12 | 12 | = | 봉투 port_type ['Ethernet'] |
| power.psu | 2 | 2 | = | 판별기 Absent 0 · 입력0 [] |
| thermal.temps | 22 | 22 | = | 판별기 전체 22 · Absent 0 · 비-Enabled 0 |
| thermal.fans | 12 | 12 | = | 판별기 전체 12 · Absent 0 · 비-Enabled 0 |
| firmware.count | 24 | 24 | = | 판별기 FirmwareInventory 26 · Disabled∧무버전 2 · 봉투 category ['backplane', 'bios', 'bmc', 'cpld', 'drive', 'driver_pack', 'nic', 'other', 'psu', 'storage_controller'] |
| bmc.model∈managers | true | true | = | 봉투 'Lenovo Xclarity Controller 3' |
| bmc.firmware∈managers | true | true | = | 봉투 'IHX414J 1.22 20250402' |
| hardware.model | "ThinkSystem SR650 V4" | "ThinkSystem SR650 V4" | = |  |

