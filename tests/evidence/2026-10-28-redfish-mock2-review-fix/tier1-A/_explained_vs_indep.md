# Tier 1 차이 펼침 — `C:/github/ClovirONE/se-indep-20261027/out/tier1-after` → `tests/evidence/2026-10-28-redfish-mock2-review-fix/tier1-A`

- 허용목록: `tests/evidence/2026-10-28-redfish-mock2-review-fix/tier1-A/_allow.json` (3 항목)
- 설명된 차이 34 · **설명되지 않은 차이 0** · 요청 집합 미설명 0 · 산출 없음 0

## 실행 결과 (`_summary.json`)

| label | rc | status | adapter | errors | 요청(전체/고유) | sections · 실행 필드 같음 |
|---|---|---|---|---|---|---|
| csus3200_01 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 186/182 → 186/182 | 전부 같음 |
| csus3200_02 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 134/130 → 134/130 | 전부 같음 |
| csus3200_03 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 170/166 → 170/166 | 전부 같음 |
| dl380_gen12_01 | 0 → 0 | success → success | redfish_hpe_ilo7 | 0 → 0 | 157/153 → 157/153 | 전부 같음 |
| dl380_gen12_02 | 0 → 0 | success → success | redfish_hpe_ilo7 | 0 → 0 | 148/144 → 148/144 | 전부 같음 |
| dl380_gen12_03 | 0 → 0 | success → success | redfish_hpe_ilo7 | 0 → 0 | 85/81 → 85/81 | 전부 같음 |
| dl380_gen12_04 | 0 → 0 | success → success | redfish_hpe_ilo7 | 0 → 0 | 148/144 → 148/144 | 전부 같음 |
| r1_DELL_R740_01 | 0 → 0 | success → success | redfish_dell_idrac9 | 0 → 0 | 141/137 → 141/137 | 전부 같음 |
| r1_HPE_CSUS3200_01 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 131/127 → 131/127 | 전부 같음 |
| r1_HPE_CSUS3200_02 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 131/127 → 131/127 | 전부 같음 |
| r1_HPE_CSUS3200_03 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 200/196 → 200/196 | 전부 같음 |
| r1_HPE_CSUS3200_04 | 0 → 0 | success → success | redfish_hpe_csus_3200 | 0 → 0 | 200/196 → 200/196 | 전부 같음 |
| r1_HPE_DL380_01 | 0 → 0 | success → success | redfish_hpe_ilo7 | 0 → 0 | 136/132 → 136/132 | 전부 같음 |
| r1_Lenovo_SR650_01 | 0 → 0 | success → success | redfish_lenovo_xcc3 | 0 → 0 | 127/123 → 127/123 | 전부 같음 |
| sr650_v4_01 | 0 → 0 | success → success | redfish_lenovo_xcc3 | 0 → 0 | 112/108 → 112/108 | 전부 같음 |
| sr650_v4_02 | 0 → 0 | success → success | redfish_lenovo_xcc3 | 0 → 0 | 129/125 → 129/125 | 전부 같음 |
| sr650_v4_03 | 0 → 0 | success → success | redfish_lenovo_xcc3 | 0 → 0 | 163/159 → 163/159 | 전부 같음 |
| sr650_v4_04 | 0 → 0 | success → success | redfish_lenovo_xcc3 | 0 → 0 | 117/113 → 117/113 | 전부 같음 |

## 차이 종류별 집계 (경로의 인덱스를 [] 로 접음)

| 구분 | 경로 | 이전 → 새 값 | 건수 |
|---|---|---|---|
| explained | `data.network.interfaces[].is_primary` | false → true | 4 |
| explained | `data.network.interfaces[].link_status` | "unknown" → "down" | 6 |
| explained | `data.network.interfaces[].link_status` | "unknown" → "up" | 14 |
| explained | `data.network.summary.groups[].link_up_count` | 0 → 1 | 2 |
| explained | `data.network.summary.groups[].link_up_count` | 0 → 2 | 1 |
| explained | `data.network.summary.groups[].link_up_count` | 0 → 4 | 1 |
| explained | `data.network.summary.groups[].link_up_count` | 0 → 6 | 1 |
| explained | `data.network.summary.primary_speed_mbps` | null → 25600 | 4 |
| explained | `diagnosis.details.notices[].message` | "호스트 전원 Off 관측 — 저장/메모리/전원/온도 인벤토리가 비어 있거나 placeholder 일 수 있음" → "호스트 전원 Off 관측 — 저장/네트워크/메모리/전원/온도 인벤토리가 비어 있거나 placeholder 일 수 있음" | 1 |

## 차이 전수

| label | 구분 | 경로 | NIC | 이전 | 새 값 | issue |
|---|---|---|---|---|---|---|
| dl380_gen12_03 | explained | `diagnosis.details.notices[1].message` |  | "호스트 전원 Off 관측 — 저장/메모리/전원/온도 인벤토리가 비어 있거나 placeholder 일 수 있음" | "호스트 전원 Off 관측 — 저장/네트워크/메모리/전원/온도 인벤토리가 비어 있거나 placeholder 일 수 있음" | 03-storage-001 |
| sr650_v4_01 | explained | `data.network.interfaces[1].link_status` | NIC1 ec:e7:a7:22:59:5d | "unknown" | "down" | 03-network-002 |
| sr650_v4_01 | explained | `data.network.interfaces[2].is_primary` | NIC2 ec:e7:a7:22:59:5c | false | true | 03-network-002 |
| sr650_v4_01 | explained | `data.network.interfaces[2].link_status` | NIC2 ec:e7:a7:22:59:5c | "unknown" | "up" | 03-network-002 |
| sr650_v4_01 | explained | `data.network.interfaces[3].link_status` | NIC3 ec:e7:a7:22:5d:bd | "unknown" | "down" | 03-network-002 |
| sr650_v4_01 | explained | `data.network.interfaces[4].link_status` | NIC4 ec:e7:a7:22:5d:bc | "unknown" | "up" | 03-network-002 |
| sr650_v4_01 | explained | `data.network.summary.groups[2].link_up_count` |  | 0 | 2 | 03-network-002 |
| sr650_v4_01 | explained | `data.network.summary.primary_speed_mbps` |  | null | 25600 | 03-network-002 |
| sr650_v4_02 | explained | `data.network.interfaces[1].link_status` | NIC1 ec:e7:a7:22:5f:39 | "unknown" | "down" | 03-network-002 |
| sr650_v4_02 | explained | `data.network.interfaces[2].is_primary` | NIC2 ec:e7:a7:22:5f:38 | false | true | 03-network-002 |
| sr650_v4_02 | explained | `data.network.interfaces[2].link_status` | NIC2 ec:e7:a7:22:5f:38 | "unknown" | "up" | 03-network-002 |
| sr650_v4_02 | explained | `data.network.interfaces[3].link_status` | NIC5 ec:e7:a7:22:61:81 | "unknown" | "down" | 03-network-002 |
| sr650_v4_02 | explained | `data.network.summary.groups[2].link_up_count` |  | 0 | 1 | 03-network-002 |
| sr650_v4_02 | explained | `data.network.summary.primary_speed_mbps` |  | null | 25600 | 03-network-002 |
| sr650_v4_03 | explained | `data.network.interfaces[10].link_status` | NIC14 ec:e7:a7:22:55:c4 | "unknown" | "up" | 03-network-002 |
| sr650_v4_03 | explained | `data.network.interfaces[1].is_primary` | NIC1 ec:e7:a7:22:4d:05 | false | true | 03-network-002 |
| sr650_v4_03 | explained | `data.network.interfaces[1].link_status` | NIC1 ec:e7:a7:22:4d:05 | "unknown" | "up" | 03-network-002 |
| sr650_v4_03 | explained | `data.network.interfaces[2].link_status` | NIC2 ec:e7:a7:22:4d:04 | "unknown" | "up" | 03-network-002 |
| sr650_v4_03 | explained | `data.network.interfaces[3].link_status` | NIC3 ec:e7:a7:20:2d:6d | "unknown" | "up" | 03-network-002 |
| sr650_v4_03 | explained | `data.network.interfaces[4].link_status` | NIC4 ec:e7:a7:20:2d:6c | "unknown" | "up" | 03-network-002 |
| sr650_v4_03 | explained | `data.network.interfaces[5].link_status` | NIC9 ec:e7:a7:20:26:19 | "unknown" | "up" | 03-network-002 |
| sr650_v4_03 | explained | `data.network.interfaces[6].link_status` | NIC10 ec:e7:a7:20:26:18 | "unknown" | "up" | 03-network-002 |
| sr650_v4_03 | explained | `data.network.interfaces[7].link_status` | NIC11 ec:e7:a7:20:33:05 | "unknown" | "up" | 03-network-002 |
| sr650_v4_03 | explained | `data.network.interfaces[8].link_status` | NIC12 ec:e7:a7:20:33:04 | "unknown" | "up" | 03-network-002 |
| sr650_v4_03 | explained | `data.network.interfaces[9].link_status` | NIC13 ec:e7:a7:22:55:c5 | "unknown" | "up" | 03-network-002 |
| sr650_v4_03 | explained | `data.network.summary.groups[1].link_up_count` |  | 0 | 4 | 03-network-002 |
| sr650_v4_03 | explained | `data.network.summary.groups[2].link_up_count` |  | 0 | 6 | 03-network-002 |
| sr650_v4_03 | explained | `data.network.summary.primary_speed_mbps` |  | null | 25600 | 03-network-002 |
| sr650_v4_04 | explained | `data.network.interfaces[1].link_status` | NIC1 ec:e7:a7:22:55:39 | "unknown" | "down" | 03-network-002 |
| sr650_v4_04 | explained | `data.network.interfaces[2].is_primary` | NIC2 ec:e7:a7:22:55:38 | false | true | 03-network-002 |
| sr650_v4_04 | explained | `data.network.interfaces[2].link_status` | NIC2 ec:e7:a7:22:55:38 | "unknown" | "up" | 03-network-002 |
| sr650_v4_04 | explained | `data.network.interfaces[3].link_status` | NIC3 ec:e7:a7:22:4b:5d | "unknown" | "down" | 03-network-002 |
| sr650_v4_04 | explained | `data.network.summary.groups[2].link_up_count` |  | 0 | 1 | 03-network-002 |
| sr650_v4_04 | explained | `data.network.summary.primary_speed_mbps` |  | null | 25600 | 03-network-002 |
