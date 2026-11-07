# Tier 1 차이 펼침 — `<scratch>/tier1_base` → `<scratch>/tier1_after`

- 허용목록: `tests/evidence/2026-10-29-redfish-summary-fix/tier1/allow.json` (10 항목)
- 설명된 차이 34 · **설명되지 않은 차이 0** · 요청 집합 미설명 0 · 산출 없음 0

## 실행 결과 (`_summary.json`)

| label | rc | status | adapter | errors | 요청(전체/고유) | sections · 실행 필드 같음 |
|---|---|---|---|---|---|---|
| csus3200_01 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 186/182 → 187/183 | 다름: requests, requests_distinct, req_notes |
| csus3200_02 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 134/130 → 135/131 | 다름: requests, requests_distinct, req_notes |
| csus3200_03 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 170/166 → 171/167 | 다름: requests, requests_distinct, req_notes |
| dl380_gen12_01 | 0 → 0 | success → success | redfish_hpe_ilo7 | 0 → 0 | 157/153 → 159/155 | 다름: requests, requests_distinct, req_notes |
| dl380_gen12_02 | 0 → 0 | success → success | redfish_hpe_ilo7 | 0 → 0 | 148/144 → 150/146 | 다름: requests, requests_distinct, req_notes |
| dl380_gen12_03 | 0 → 0 | success → success | redfish_hpe_ilo7 | 0 → 0 | 85/81 → 85/81 | 전부 같음 |
| dl380_gen12_04 | 0 → 0 | success → success | redfish_hpe_ilo7 | 0 → 0 | 148/144 → 150/146 | 다름: requests, requests_distinct, req_notes |
| r1_DELL_R740_01 | 0 → 0 | success → success | redfish_dell_idrac9 | 0 → 0 | 141/137 → 142/138 | 다름: requests, requests_distinct, req_notes |
| r1_HPE_CSUS3200_01 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 131/127 → 131/127 | 전부 같음 |
| r1_HPE_CSUS3200_02 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 131/127 → 131/127 | 전부 같음 |
| r1_HPE_CSUS3200_03 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 200/196 → 201/197 | 다름: requests, requests_distinct, req_notes |
| r1_HPE_CSUS3200_04 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 200/196 → 201/197 | 다름: requests, requests_distinct, req_notes |
| r1_HPE_DL380_01 | 0 → 0 | success → success | redfish_hpe_ilo7 | 0 → 0 | 136/132 → 138/134 | 다름: requests, requests_distinct, req_notes |
| r1_Lenovo_SR650_01 | 0 → 0 | success → success | redfish_lenovo_xcc3 | 0 → 0 | 127/123 → 127/123 | 전부 같음 |
| sr650_v4_01 | 0 → 0 | success → success | redfish_lenovo_xcc3 | 0 → 0 | 112/108 → 112/108 | 전부 같음 |
| sr650_v4_02 | 0 → 0 | success → success | redfish_lenovo_xcc3 | 0 → 0 | 129/125 → 129/125 | 전부 같음 |
| sr650_v4_03 | 0 → 0 | success → success | redfish_lenovo_xcc3 | 0 → 0 | 163/159 → 163/159 | 전부 같음 |
| sr650_v4_04 | 0 → 0 | success → success | redfish_lenovo_xcc3 | 0 → 0 | 117/113 → 117/113 | 전부 같음 |

## 차이 종류별 집계 (경로의 인덱스를 [] 로 접음)

| 구분 | 경로 | 이전 → 새 값 | 건수 |
|---|---|---|---|
| explained | `data.multi_node.chassis[].power.power_control.power_consumed_watts` | 591 → 592 | 1 |
| explained | `data.multi_node.chassis[].power.power_control.power_consumed_watts` | 815 → 816 | 1 |
| explained | `data.multi_node.chassis[].power.power_control.power_consumed_watts` | 945 → 946 | 1 |
| explained | `data.multi_node.fabrics[].endpoint_count` | 0 → null | 7 |
| explained | `data.multi_node.partitions[].cpu.summary.groups[].manufacturer` | "Intel(R) Corporation" → "Intel" | 7 |
| explained | `data.network.summary.groups[].speed_mbps` | 0 → null | 7 |
| explained | `data.power.power_control.power_consumed_watts` | 591 → 592 | 1 |
| explained | `data.power.power_control.power_consumed_watts` | 815 → 816 | 1 |
| explained | `data.power.power_control.power_consumed_watts` | 945 → 946 | 1 |
| explained | `data.power.summary.consumed_watts` | 591 → 592 | 1 |
| explained | `data.power.summary.consumed_watts` | 815 → 816 | 1 |
| explained | `data.power.summary.consumed_watts` | 945 → 946 | 1 |
| explained | `data.power.summary.health_rollup` | "Unknown" → null | 1 |
| explained | `data.storage.summary.grand_total_gb` | 0 → null | 1 |
| explained | `diagnosis.details.notices[].message` | "<absent>" → "드라이브 목록 원천(Storage Drives · 섀시 Drives 등)을 하나도 읽지 못함 — 디스크 0개를 확인할 근거가 없음: summary.grand_total_gb = null" | 1 |
| explained | `diagnosis.details.notices[].section` | "<absent>" → "storage" | 1 |

## 차이 전수

| label | 구분 | 경로 | NIC | 이전 | 새 값 | issue |
|---|---|---|---|---|---|---|
| csus3200_01 | explained | `data.multi_node.fabrics[0].endpoint_count` |  | 0 | null | SA-01 |
| csus3200_01 | explained | `data.multi_node.partitions[0].cpu.summary.groups[0].manufacturer` |  | "Intel(R) Corporation" | "Intel" | SA-03 |
| csus3200_02 | explained | `data.multi_node.chassis[2].power.power_control.power_consumed_watts` |  | 815 | 816 | SA-17 |
| csus3200_02 | explained | `data.multi_node.fabrics[0].endpoint_count` |  | 0 | null | SA-01 |
| csus3200_02 | explained | `data.multi_node.partitions[0].cpu.summary.groups[0].manufacturer` |  | "Intel(R) Corporation" | "Intel" | SA-03 |
| csus3200_02 | explained | `data.power.power_control.power_consumed_watts` |  | 815 | 816 | SA-17 |
| csus3200_02 | explained | `data.power.summary.consumed_watts` |  | 815 | 816 | SA-17 |
| csus3200_03 | explained | `data.multi_node.fabrics[0].endpoint_count` |  | 0 | null | SA-01 |
| csus3200_03 | explained | `data.multi_node.partitions[0].cpu.summary.groups[0].manufacturer` |  | "Intel(R) Corporation" | "Intel" | SA-03 |
| dl380_gen12_03 | explained | `data.power.summary.health_rollup` |  | "Unknown" | null | SA-06 |
| dl380_gen12_03 | explained | `data.storage.summary.grand_total_gb` |  | 0 | null | SA-07 |
| dl380_gen12_03 | explained | `diagnosis.details.notices[2].message` |  | "<absent>" | "드라이브 목록 원천(Storage Drives · 섀시 Drives 등)을 하나도 읽지 못함 — 디스크 0개를 확인할 근거가 없음: summary.grand_total_gb = null" | SA-07 |
| dl380_gen12_03 | explained | `diagnosis.details.notices[2].section` |  | "<absent>" | "storage" | SA-07 |
| r1_DELL_R740_01 | explained | `data.network.summary.groups[0].speed_mbps` |  | 0 | null | SA-08 |
| r1_DELL_R740_01 | explained | `data.network.summary.groups[2].speed_mbps` |  | 0 | null | SA-08 |
| r1_HPE_CSUS3200_01 | explained | `data.multi_node.chassis[2].power.power_control.power_consumed_watts` |  | 591 | 592 | SA-17 |
| r1_HPE_CSUS3200_01 | explained | `data.multi_node.fabrics[0].endpoint_count` |  | 0 | null | SA-01 |
| r1_HPE_CSUS3200_01 | explained | `data.multi_node.partitions[0].cpu.summary.groups[0].manufacturer` |  | "Intel(R) Corporation" | "Intel" | SA-03 |
| r1_HPE_CSUS3200_01 | explained | `data.power.power_control.power_consumed_watts` |  | 591 | 592 | SA-17 |
| r1_HPE_CSUS3200_01 | explained | `data.power.summary.consumed_watts` |  | 591 | 592 | SA-17 |
| r1_HPE_CSUS3200_02 | explained | `data.multi_node.fabrics[0].endpoint_count` |  | 0 | null | SA-01 |
| r1_HPE_CSUS3200_02 | explained | `data.multi_node.partitions[0].cpu.summary.groups[0].manufacturer` |  | "Intel(R) Corporation" | "Intel" | SA-03 |
| r1_HPE_CSUS3200_03 | explained | `data.multi_node.fabrics[0].endpoint_count` |  | 0 | null | SA-01 |
| r1_HPE_CSUS3200_03 | explained | `data.multi_node.partitions[0].cpu.summary.groups[0].manufacturer` |  | "Intel(R) Corporation" | "Intel" | SA-03 |
| r1_HPE_CSUS3200_04 | explained | `data.multi_node.chassis[2].power.power_control.power_consumed_watts` |  | 945 | 946 | SA-17 |
| r1_HPE_CSUS3200_04 | explained | `data.multi_node.fabrics[0].endpoint_count` |  | 0 | null | SA-01 |
| r1_HPE_CSUS3200_04 | explained | `data.multi_node.partitions[0].cpu.summary.groups[0].manufacturer` |  | "Intel(R) Corporation" | "Intel" | SA-03 |
| r1_HPE_CSUS3200_04 | explained | `data.power.power_control.power_consumed_watts` |  | 945 | 946 | SA-17 |
| r1_HPE_CSUS3200_04 | explained | `data.power.summary.consumed_watts` |  | 945 | 946 | SA-17 |
| r1_Lenovo_SR650_01 | explained | `data.network.summary.groups[1].speed_mbps` |  | 0 | null | SA-08 |
| r1_Lenovo_SR650_01 | explained | `data.network.summary.groups[3].speed_mbps` |  | 0 | null | SA-08 |
| sr650_v4_01 | explained | `data.network.summary.groups[1].speed_mbps` |  | 0 | null | SA-08 |
| sr650_v4_02 | explained | `data.network.summary.groups[1].speed_mbps` |  | 0 | null | SA-08 |
| sr650_v4_04 | explained | `data.network.summary.groups[1].speed_mbps` |  | 0 | null | SA-08 |

- csus3200_01 요청 집합: +['Chassis/r001u01/Drives'] -[] (미설명 [])

- csus3200_02 요청 집합: +['Chassis/r001u01/Drives'] -[] (미설명 [])

- csus3200_03 요청 집합: +['Chassis/r001u01/Drives'] -[] (미설명 [])

- dl380_gen12_01 요청 집합: +['Chassis/DE00B000', 'Chassis/DE00B000/Drives'] -[] (미설명 [])

- dl380_gen12_02 요청 집합: +['Chassis/DE00B000', 'Chassis/DE00B000/Drives'] -[] (미설명 [])

- dl380_gen12_04 요청 집합: +['Chassis/DE00B000', 'Chassis/DE00B000/Drives'] -[] (미설명 [])

- r1_DELL_R740_01 요청 집합: +['Chassis/Enclosure.Internal.0-1:RAID.Slot.6-1'] -[] (미설명 [])

- r1_HPE_CSUS3200_03 요청 집합: +['Chassis/r001u01/Drives'] -[] (미설명 [])

- r1_HPE_CSUS3200_04 요청 집합: +['Chassis/r001u01/Drives'] -[] (미설명 [])

- r1_HPE_DL380_01 요청 집합: +['Chassis/DE00B000', 'Chassis/DE00B000/Drives'] -[] (미설명 [])
