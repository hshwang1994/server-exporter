| label | tag | status | fixture | GOLDEN_KEYS 차이(golden) | 키 전부 차이(이전 Tier 2) | 예시 |
|---|---|---|---|---|---|---|
| csus3200_01 | adapter | success | `real_hpe_csus3200_01` | 0 | 4 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete`, `multi_node.fabrics[0].endpoint_count` |
| csus3200_02 | adapter | success | `real_hpe_csus3200_02` | 0 | 6 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete`, `data.power.power_control.power_consumed_watts` |
| csus3200_03 | adapter | success | `real_hpe_csus3200_03` | 0 | 4 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete`, `multi_node.fabrics[0].endpoint_count` |
| dl380_gen12_01 | plain | success | `real_hpe_dl380_gen12_01` | 0 | 2 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete` |
| dl380_gen12_02 | plain | success | `real_hpe_dl380_gen12_02` | 0 | 2 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete` |
| dl380_gen12_03 | plain | success | `real_hpe_dl380_gen12_03` | 0 | 2 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete` |
| dl380_gen12_04 | plain | success | `real_hpe_dl380_gen12_04` | 0 | 2 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete` |
| r1_DELL_R740_01 | plain | success | `real_dell_r740` | 0 | 2 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete` |
| r1_HPE_CSUS3200_01 | adapter | success | `real_hpe_csus3200` | 0 | 6 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete`, `data.power.power_control.power_consumed_watts` |
| r1_HPE_CSUS3200_02 | adapter | success | (fixture 없음) | - | 4 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete`, `multi_node.fabrics[0].endpoint_count` |
| r1_HPE_CSUS3200_03 | adapter | success | (fixture 없음) | - | 4 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete`, `multi_node.fabrics[0].endpoint_count` |
| r1_HPE_CSUS3200_04 | adapter | success | (fixture 없음) | - | 6 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete`, `data.power.power_control.power_consumed_watts` |
| r1_HPE_DL380_01 | plain | success | `real_hpe_dl380` | 0 | 2 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete` |
| r1_Lenovo_SR650_01 | plain | success | `real_lenovo_sr650` | 0 | 2 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete` |
| sr650_v4_01 | plain | success | `real_lenovo_sr650_v4_01` | 0 | 2 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete` |
| sr650_v4_02 | plain | success | `real_lenovo_sr650_v4_02` | 0 | 2 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete` |
| sr650_v4_03 | plain | success | `real_lenovo_sr650_v4_03` | 0 | 2 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete` |
| sr650_v4_04 | plain | success | `real_lenovo_sr650_v4_04` | 0 | 2 | `aux.storage_inventory.enumerated`, `aux.storage_inventory.incomplete` |

- module.json 18개 · golden 비교 15 label · GOLDEN_KEYS = ['vendor', 'status', 'collected', 'failed_sections', 'unsupported_sections', 'data', 'multi_node', 'probe_facts', 'error_count']
- 총 차이 경로: golden 0 · 이전 Tier 2(`tests/evidence/2026-10-28-redfish-mock2-review-fix/tier2-A`) 56
