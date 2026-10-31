# A/B/C 독립 Summary 비교

| 판정 | 건수 |
|---|---|
| CM | 36 |
| FAIL | 24 |
| PASS | 642 |

## PASS 이외

| label | field | 판정 | A | B/C | 규칙 · 비고 |
|---|---|---|---|---|---|
| csus3200_01 | partition Partition0 cpu group Intel(R) Xeon(R) Platinum 8444H Processor manufacturer A↔C | FAIL | "Intel" | "Intel(R) Corporation" | FIX 2 표 (6.1 · 파티션 SA-03)  |
| csus3200_01 | fabric FlexGrid.endpoint_count A↔B | FAIL | null | 0 | R-MN (SA-01)  |
| csus3200_02 | power.summary.consumed_watts A↔C | FAIL | 816 | 815 | R-PWR (6.5 SA-06 · SA-17)  |
| csus3200_02 | partition Partition0 cpu group Intel(R) Xeon(R) Platinum 8450H Processor manufacturer A↔C | FAIL | "Intel" | "Intel(R) Corporation" | FIX 2 표 (6.1 · 파티션 SA-03)  |
| csus3200_02 | fabric FlexGrid.endpoint_count A↔B | FAIL | null | 0 | R-MN (SA-01)  |
| csus3200_03 | partition Partition0 cpu group Intel(R) Xeon(R) Platinum 8444H Processor manufacturer A↔C | FAIL | "Intel" | "Intel(R) Corporation" | FIX 2 표 (6.1 · 파티션 SA-03)  |
| csus3200_03 | fabric FlexGrid.endpoint_count A↔B | FAIL | null | 0 | R-MN (SA-01)  |
| dl380_gen12_01 | NIC 141 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_01 | NIC 142 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_01 | NIC 270 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_01 | NIC 334 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_01 | NIC 461 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_01 | NIC 77 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_02 | NIC 13 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_02 | NIC 14 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_02 | NIC 142 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_02 | NIC 205 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_02 | NIC 206 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_02 | NIC 334 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| dl380_gen12_03 | storage.grand_total_gb A↔C | FAIL | null | 0 | R-STO-2 (6.3 SA-07, floor)  |
| dl380_gen12_03 | power.summary.health_rollup A↔C | FAIL | null | "Unknown" | R-PWR (6.5 SA-06 · SA-17)  |
| r1_DELL_R740_01 | network group speed 0 없음 C | FAIL | 0 | 2 | R-NET-5 (SA-08)  |
| r1_HPE_CSUS3200_01 | power.summary.consumed_watts A↔C | FAIL | 592 | 591 | R-PWR (6.5 SA-06 · SA-17)  |
| r1_HPE_CSUS3200_01 | partition Partition0 cpu group Intel(R) Xeon(R) Gold 6434H Processor manufacturer A↔C | FAIL | "Intel" | "Intel(R) Corporation" | FIX 2 표 (6.1 · 파티션 SA-03)  |
| r1_HPE_CSUS3200_01 | fabric FlexGrid.endpoint_count A↔B | FAIL | null | 0 | R-MN (SA-01)  |
| r1_HPE_CSUS3200_02 | partition Partition0 cpu group Intel(R) Xeon(R) Gold 6434H Processor manufacturer A↔C | FAIL | "Intel" | "Intel(R) Corporation" | FIX 2 표 (6.1 · 파티션 SA-03)  |
| r1_HPE_CSUS3200_02 | fabric FlexGrid.endpoint_count A↔B | FAIL | null | 0 | R-MN (SA-01)  |
| r1_HPE_CSUS3200_03 | partition Partition0 cpu group Intel(R) Xeon(R) Platinum 8444H Processor manufacturer A↔C | FAIL | "Intel" | "Intel(R) Corporation" | FIX 2 표 (6.1 · 파티션 SA-03)  |
| r1_HPE_CSUS3200_03 | fabric FlexGrid.endpoint_count A↔B | FAIL | null | 0 | R-MN (SA-01)  |
| r1_HPE_CSUS3200_04 | power.summary.consumed_watts A↔C | FAIL | 946 | 945 | R-PWR (6.5 SA-06 · SA-17)  |
| r1_HPE_CSUS3200_04 | partition Partition0 cpu group Intel(R) Xeon(R) Platinum 8444H Processor manufacturer A↔C | FAIL | "Intel" | "Intel(R) Corporation" | FIX 2 표 (6.1 · 파티션 SA-03)  |
| r1_HPE_CSUS3200_04 | fabric FlexGrid.endpoint_count A↔B | FAIL | null | 0 | R-MN (SA-01)  |
| r1_HPE_DL380_01 | NIC 14 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| r1_HPE_DL380_01 | NIC 141 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| r1_HPE_DL380_01 | NIC 142 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| r1_HPE_DL380_01 | NIC 206 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| r1_Lenovo_SR650_01 | network group speed 0 없음 C | FAIL | 0 | 2 | R-NET-5 (SA-08)  |
| sr650_v4_01 | network group speed 0 없음 C | FAIL | 0 | 1 | R-NET-5 (SA-08)  |
| sr650_v4_01 | NIC NIC1 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_01 | NIC NIC2 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_01 | NIC NIC3 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_01 | NIC NIC4 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_02 | network group speed 0 없음 C | FAIL | 0 | 1 | R-NET-5 (SA-08)  |
| sr650_v4_02 | NIC NIC1 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_02 | NIC NIC2 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_02 | NIC NIC5 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_03 | NIC NIC1 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_03 | NIC NIC10 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_03 | NIC NIC11 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_03 | NIC NIC12 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_03 | NIC NIC13 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_03 | NIC NIC14 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_03 | NIC NIC2 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_03 | NIC NIC3 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_03 | NIC NIC4 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_03 | NIC NIC9 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_04 | network group speed 0 없음 C | FAIL | 0 | 1 | R-NET-5 (SA-08)  |
| sr650_v4_04 | NIC NIC1 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_04 | NIC NIC2 link A↔B | CM | "unknown" | "up" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
| sr650_v4_04 | NIC NIC3 link A↔B | CM | "unknown" | "down" | R-NET-6 (SA-09) F-01: NIC 원문 없음 → 같은 MAC 포트 값 보충 |
