# HPE Superdome Flex mock fixture — Gen 1/2 generic

> Lab 부재 vendor mock fixture (mission-critical).

## 메타

| 항목 | 값 |
|---|---|
| Vendor | HPE (Hewlett Packard Enterprise) |
| Model | Superdome Flex |
| BMC | RMC (Rack Management Controller) primary + per-node iLO 5 |
| Firmware | RMC 2.4.0 |
| Redfish version | 1.10.0 |
| OEM namespace | `Oem.Hpe` (iLO 시리즈 + Superdome 공통) |
| Multi-partition | YES (nPAR — 전 partition 을 data.multi_node 로 수집) |
| Lab | 부재 — web sources 기반 |

## Sources

- https://github.com/HewlettPackard/sdflexutils (RMC + Partition0 명시)
- https://github.com/HewlettPackard/sdflex-ironic-driver/wiki (nPar firmware bundles)
- https://pypi.org/project/sdflexutils/ (sdflexutils 1.5.1)
- https://support.hpe.com/hpesc/public/docDisplay (Superdome Flex Server Admin Guide)
- https://redfish.dmtf.org/schemas/DSP0266_1.15.0.html (Redfish Specification v1.15)
- https://hewlettpackard.github.io/ilo-rest-api-docs/ilo5/ (iLO 5 API reference — per-node)
- https://thelinuxcluster.com/2020/05/06/upgrading-firmware-for-super-dome-flex/ (RMC firmware 3.10.164)

## Superdome Flex 특이점 (web sources)

| 특이점 | 설명 |
|---|---|
| Multi-partition (nPAR) | Systems ID = `Partition<N>` — 전 partition 을 `data.multi_node.partitions[]` 로 수집. top-level `data.*` 섹션은 Partition0 대표 |
| Dual-manager | RMC + 각 컴퓨트 모듈 iLO 5. RMC 가 primary AccountService host |
| OEM 영역 | `Oem.Hpe.PartitionInfo` (Systems) / `Oem.Hpe.FlexNodeInfo` (Chassis) / `Oem.Hpe.GlobalConfiguration` (Systems/Managers) |
| Storage-less | Compute node 는 SmartStorage 영역 없음 (storage-less node — Storage endpoint 빈 응답) |
| nPar firmware bundles | UpdateService.FirmwareInventory 에 RMC + iLO 5 + SystemFirmware + nPar 4 entries |

## 주요 endpoint

| File | Path | 비고 |
|---|---|---|
| service_root.json | `/redfish/v1/` | `Product: Superdome Flex`, `Vendor: HPE` |
| chassis_collection.json | `/redfish/v1/Chassis` | Members 1 |
| chassis.json | `/redfish/v1/Chassis/0` | Model: Superdome Flex, `Oem.Hpe.FlexNodeInfo` |
| chassis_power.json | `/redfish/v1/Chassis/0/Power` | PSU 2개 (1600W Flex Slot Titanium) |
| systems_collection.json | `/redfish/v1/Systems` | Members 1 — `Partition0` (이 mock 은 단일 partition; 실 RMC 는 다수) |
| system.json | `/redfish/v1/Systems/Partition0` | `Oem.Hpe.PartitionInfo` + `Oem.Hpe.GlobalConfiguration` |
| managers_collection.json | `/redfish/v1/Managers` | Members 2 — RMC + iLO5_Node0 (dual-manager) |
| manager.json | `/redfish/v1/Managers/RMC` | `ManagerRole: PrimaryRMC`, `Oem.Hpe.RMCInfo` + `GlobalConfiguration` |
| firmware_inventory.json | `/redfish/v1/UpdateService/FirmwareInventory` | 4 entries (RMC + iLO5 + SystemFirmware + nPar) |

## 검증 포인트

- adapter 선택: `redfish_hpe_superdome_flex` (priority=101, model_patterns: `^Superdome Flex.*` 매칭 — iLO6 catch-all(100) 위, iLO7(120) 아래)
- OEM 추출 (collect_oem.yml when 조건 매칭):
  - `_hpe_superdome_partition` → `Oem.Hpe.PartitionInfo` (Systems)
  - `_hpe_superdome_flex_node` → `Oem.Hpe.FlexNodeInfo` (Chassis)
  - `_hpe_superdome_global` → `Oem.Hpe.GlobalConfiguration` (Systems)
- iLO 시리즈 mock (사이트 검증 iLO7 등) 미간섭 — `regex_search('(?i)Superdome|Flex')` when 조건이 매칭되지 않음
- multi-node 수집: 전 partition → `data.multi_node.partitions[]`, `representative_partition` = partitions[0]

## 변형 가능성 (사이트 도입 시 정정)

- Superdome Flex 280 series (2022+) — `Model: "Superdome Flex 280"` 별도 mock (`hpe_superdome_280/`)
- Gen 1 (2018-2020) RMC firmware 1.x vs Gen 2 (2020-2022) RMC 2.x vs 280 (2022+) RMC 3.x
- Expansion enclosure 추가 (BaseEnclosures + ExpansionEnclosures > 1) — FlexNodeInfo.NodeCount 증가
- 다중 partition 운영 (nPAR > 1) — Systems Members 다수 → 전부 `data.multi_node.partitions[]` 로 수집 (이 mock 은 1개라 degenerate case)
