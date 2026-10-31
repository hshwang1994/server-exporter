# Tier 1 합성 미러 판정

expected.json sha256 `b10221c0de6b6108cd7f2fddb2361c7dd38346ddfdb8bfcf8a9e17208960a612`

| case | SA | head 판정 | base 에서 결함 재현 | status head/base |
|---|---|---|---|---|
| syn_csus_nocomp | SA-02 | PASS | 예 | success / success |
| syn_csus_nofab | SA-02 | PASS | 예 | success / success |
| syn_dell_links | SA-09 | PASS | 예 | success / success |
| syn_dell_primary | SA-10 · SA-08 | PASS | 예 | success / success |
| syn_dl380_partial_link | SA-12 | PASS | 예 | success / success |
| syn_g12_03_on | SA-07 | PASS | 예 | success / success |
| syn_g12_psub_range | SA-19 · SA-17 | PASS | 예 | success / success |
| syn_r1csus01_off | SA-07 | PASS | 예 | success / success |
| syn_v4_partial | SA-04 · SA-05 | PASS | 예 | success / success |

## syn_csus_nocomp (csus3200_01)
- [head] PASS `status` → "success"
- [head] PASS `data.multi_node.composition` → null
- [head] PASS `data.multi_node.summary.resource_block_count` → null
- [head] PASS `data.multi_node.summary.fabric_count` → 1
- [head] PASS `data.multi_node.summary.partition_count` → 1
- [head] PASS `no GET CompositionService` → []
- [base] PASS `data.multi_node.composition` → null
- [base] PASS `data.multi_node.summary.resource_block_count` → 0

## syn_csus_nofab (csus3200_01)
- [head] PASS `status` → "success"
- [head] PASS `data.multi_node.fabrics` → null
- [head] PASS `data.multi_node.summary.fabric_count` → null
- [head] PASS `data.multi_node.summary.resource_block_count` → 1
- [head] PASS `data.multi_node.summary.partition_count` → 1
- [head] PASS `data.multi_node.summary.manager_count` → 1
- [head] PASS `data.multi_node.summary.chassis_count` → 3
- [head] PASS `no GET Fabrics` → []
- [base] PASS `data.multi_node.fabrics` → null
- [base] PASS `data.multi_node.summary.fabric_count` → 0

## syn_dell_links (r1_DELL_R740_01)
- [head] PASS `status` → "success"
- [head] PASS `data.network.interfaces[id=NIC.Slot.3-1-1].link_status` → "unknown"
- [head] PASS `data.network.interfaces[id=NIC.Slot.3-1-1].speed_mbps` → 10000
- [head] PASS `data.network.ports[associated_address=b0:26:28:7f:43:20].link_status` → "unknown"
- [head] PASS `data.network.ports[associated_address=b0:26:28:7f:33:50].link_status` → "unknown"
- [head] PASS `data.network.interfaces[id=NIC.Slot.5-1-1].link_status` → "down"
- [head] PASS `data.network.summary.primary_speed_mbps` → 10000
- [head] PASS `data.network.summary.groups` → [{"link_type": "ethernet", "link_up_count": 0, "manufacturer": "Broadcom Inc. and subsidiaries", "model": "BRCM GbE 4P 5720-t rNDC", "quantity": 4, "speed_mbps": null}, {"link_type": "ethernet", "link_up_count": 1, "manufacturer": "Broadcom Inc. and subsidiaries", "model": "BRCM 10GbE 2P 57412S Adpt
- [head] PASS `notice[network] ⊇ ['NIC 링크 상태 값 미확정', 'Enabled']` → Systems/System.Embedded.1/EthernetInterfaces: NIC 링크 상태 값 미확정, unknown 으로 기록 (link_status) — NIC.Slot.3-1-1=Enabled
- [head] PASS `notice[network_adapters] ⊇ ['네트워크 포트 링크 상태 값 미확정', 'Training', 'LinkFlapping']` → 네트워크 포트 링크 상태 값 미확정, unknown 으로 기록 (network.ports link_status) — NIC.Slot.3/NIC.Slot.3-1=Training, NIC.Slot.5/NIC.Slot.5-1=LinkFlapping
- [head] PASS `data.storage.hbas == 수정 전 미러 출력` → same
- [base] PASS `data.network.interfaces[id=NIC.Slot.3-1-1].link_status` → "up"
- [base] PASS `data.network.ports[associated_address=b0:26:28:7f:43:20].link_status` → "down"
- [base] PASS `data.network.ports[associated_address=b0:26:28:7f:33:50].link_status` → "linkflapping"
- [base] PASS `no notice[network] ~ 링크 상태 값 미확정` → 0 hit(s)
- [base] PASS `no notice[network_adapters] ~ 링크 상태 값 미확정` → 0 hit(s)

## syn_dell_primary (r1_DELL_R740_01)
- [head] PASS `status` → "success"
- [head] PASS `data.network.interfaces[id=NIC.Slot.2-1-1].is_primary` → true
- [head] PASS `data.network.interfaces[id=NIC.Slot.2-1-1].speed_mbps` → 0
- [head] PASS `data.network.summary.primary_speed_mbps` → null
- [head] PASS `data.network.summary.groups` → [{"link_type": "ethernet", "link_up_count": 0, "manufacturer": "Broadcom Inc. and subsidiaries", "model": "BRCM GbE 4P 5720-t rNDC", "quantity": 4, "speed_mbps": null}, {"link_type": "ethernet", "link_up_count": 1, "manufacturer": "Broadcom Inc. and subsidiaries", "model": "BRCM 10GbE 2P 57412S Adpt
- [base] PASS `data.network.summary.primary_speed_mbps` → 10000
- [base] PASS `data.network.summary.groups` → [{"link_type": "ethernet", "link_up_count": 0, "manufacturer": "Broadcom Inc. and subsidiaries", "model": "BRCM GbE 4P 5720-t rNDC", "quantity": 4, "speed_mbps": 0}, {"link_type": "ethernet", "link_up_count": 1, "manufacturer": "Broadcom Inc. and subsidiaries", "model": "BRCM 10GbE 2P 57412S Adptr",

## syn_dl380_partial_link (dl380_gen12_02)
- [head] PASS `status` → "success"
- [head] PASS `len(data.storage.physical_disks)` → 4
- [head] PASS `data.storage.summary.grand_total_gb` → 5960
- [head] PASS `data.storage.summary.groups` → [{"group_total_gb": 2980, "media_type": "SSD", "model": "MO001600PZWSH", "protocol": "SAS", "quantity": 2, "unit_capacity_gb": 1490}, {"group_total_gb": 2980, "media_type": "SSD", "model": "MO001600PYHRE", "protocol": "SAS", "quantity": 2, "unit_capacity_gb": 1490}]
- [head] PASS `notice[storage] ⊇ ['섀시 DE00B000 의 드라이브 2건', 'Storage 가 가리키지 않아 추가']` → 섀시 DE00B000 의 드라이브 2건 — Storage 가 가리키지 않아 추가
- [head] PASS `GET Chassis/DE00B000/Drives (미러 실응답)` → ["tree"]
- [head] PASS `GET Chassis/DE00B000/Drives/2 (미러 실응답)` → ["tree"]
- [head] PASS `GET Chassis/DE00B000/Drives/3 (미러 실응답)` → ["tree"]
- [base] PASS `len(data.storage.physical_disks)` → 2
- [base] PASS `data.storage.summary.grand_total_gb` → 2980
- [base] PASS `no notice[storage] ~ Storage 가 가리키지 않아 추가` → 0 hit(s)

## syn_g12_03_on (dl380_gen12_03)
- [head] PASS `len(data.storage.physical_disks)` → 0
- [head] PASS `data.storage.summary.grand_total_gb` → null
- [head] PASS `data.power.summary.health_rollup` → null
- [head] PASS `no notice[system] ~ 호스트 전원 Off 관측` → 0 hit(s)
- [head] PASS `수정 전 미러 출력 대비 차이 ⊆ ['data.hardware.power_state', 'diagnosis.details.notices']` → {"diff_paths": ["data.hardware.power_state", "diagnosis.details.notices[1].message", "diagnosis.details.notices[1].section", "diagnosis.details.notices[2].message", "diagnosis.details.notices[2].section"], "outside_allow": []}
- [base] PASS `수정 전 미러 출력 대비 차이 ⊆ ['data.hardware.power_state', 'diagnosis.details.notices']` → {"diff_paths": ["data.hardware.power_state", "diagnosis.details.notices[1].message", "diagnosis.details.notices[1].section"], "outside_allow": []}
- [base] PASS `data.storage.summary.grand_total_gb` → 0

## syn_g12_psub_range (dl380_gen12_01)
- [head] PASS `status` → "success"
- [head] PASS `data.power.power_control.power_consumed_watts` → 522
- [head] PASS `data.power.power_control.min_consumed_watts` → null
- [head] PASS `data.power.power_control.max_consumed_watts` → null
- [head] PASS `data.power.power_control.avg_consumed_watts` → null
- [head] PASS `data.power.power_control.interval_in_min` → null
- [head] PASS `data.power.power_control.power_capacity_watts` → 3200
- [head] PASS `data.power.summary.consumed_watts` → 522
- [head] PASS `data.power.summary.consumed_capacity_pct` → 16.3
- [head] PASS `no GET Chassis/1/Power` → []
- [head] PASS `GET Chassis/1/PowerSubsystem` → ["tree"]
- [head] PASS `GET Chassis/1/EnvironmentMetrics` → ["tree"]
- [base] PASS `data.power.power_control.power_consumed_watts` → 521
- [base] PASS `data.power.power_control.min_consumed_watts` → 0
- [base] PASS `data.power.power_control.max_consumed_watts` → 2000
- [base] PASS `data.power.summary.consumed_watts` → 521

## syn_r1csus01_off (r1_HPE_CSUS3200_01)
- [head] PASS `len(data.storage.physical_disks)` → 0
- [head] PASS `data.storage.summary.grand_total_gb` → 0
- [head] PASS `notice[system] ⊇ ['호스트 전원 Off 관측']` → 호스트 전원 Off 관측 — 저장/네트워크/메모리/전원/온도 인벤토리가 비어 있거나 placeholder 일 수 있음
- [head] PASS `수정 전 미러 출력 대비 차이 ⊆ ['data.hardware.power_state', 'data.multi_node.partitions[0].system.power_state', 'diagnosis.details.notices']` → {"diff_paths": ["data.hardware.power_state", "data.multi_node.partitions[0].system.power_state", "diagnosis.details.notices[3].message", "diagnosis.details.notices[3].section"], "outside_allow": []}
- [base] PASS `수정 전 미러 출력 대비 차이 ⊆ ['data.hardware.power_state', 'data.multi_node.partitions[0].system.power_state', 'diagnosis.details.notices']` → {"diff_paths": ["data.hardware.power_state", "data.multi_node.partitions[0].system.power_state", "diagnosis.details.notices[3].message", "diagnosis.details.notices[3].section"], "outside_allow": []}
- [base] PASS `data.storage.summary.grand_total_gb` → 0

## syn_v4_partial (sr650_v4_01)
- [head] PASS `status` → "success"
- [head] PASS `data.cpu.sockets` → 2
- [head] PASS `data.cpu.cores_physical` → null
- [head] PASS `len(data.cpu.summary.groups)` → 1
- [head] PASS `data.cpu.summary.groups[0].sockets` → 2
- [head] PASS `data.cpu.summary.groups[0].total_cores` → null
- [head] PASS `data.cpu.summary.groups[0].cores_per_socket` → null
- [head] PASS `data.memory.total_mb` → 131072
- [head] PASS `data.memory.installed_mb` → 131072
- [head] PASS `data.memory.summary.grand_total_gb` → 128
- [head] PASS `data.memory.summary.groups` → [{"group_total_gb": 64, "manufacturer": "Micron Technology", "part_number": "MTC40F2046S1RC64BD2 MWFF", "quantity": 1, "speed_mhz": 6400, "type": "DDR5", "unit_capacity_gb": 64}]
- [head] PASS `notice[cpu] ⊇ ['코어 수(TotalCores) 미상 CPU 1개', '부분 합을 쓰지 않음', 'cores_physical = null']` → 코어 수(TotalCores) 미상 CPU 1개(그 모델 그룹의 total_cores · cores_per_socket = null) — 부분 합을 쓰지 않음: cores_physical = null
- [head] PASS `notice[memory] ⊇ ['CapacityMiB 미상 DIMM 1개', '부분 합을 쓰지 않음', '= MemorySummary.TotalSystemMemoryGiB 128']` → DIMM 합계를 확정하지 못함 (용량 CapacityMiB 미상 DIMM 1개) — 부분 합을 쓰지 않음: total_mb · installed_mb · summary.grand_total_gb = MemorySummary.TotalSystemMemoryGiB 128
- [head] PASS `notice[memory] ⊇ ['CapacityMiB 부재 DIMM 1/2']` → CapacityMiB 부재 DIMM 1/2 — 합계 미산출(slot 은 보존)
- [base] PASS `data.cpu.sockets` → 2
- [base] PASS `data.cpu.cores_physical` → 32
- [base] PASS `data.cpu.summary.groups[0].total_cores` → 32
- [base] PASS `data.cpu.summary.groups[0].cores_per_socket` → 16
- [base] PASS `data.memory.total_mb` → 131072
- [base] PASS `data.memory.summary.grand_total_gb` → 64
- [base] PASS `no notice[cpu] ~ 부분 합을 쓰지 않음` → 0 hit(s)
- [base] PASS `no notice[memory] ~ 부분 합을 쓰지 않음` → 0 hit(s)
