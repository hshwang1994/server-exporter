# 디스크·FC 포트 개수 정합 — 최종 Tier 1 (18 label, 2026-10-27, build mirror-replay-final)

- 판별기: `tests/scripts/inventory_parity.py`(gather 코드와 독립 — 전수 미러 트리의 Drives/Ports/NDF 를 직접 센다) × 최종 Tier 1 봉투(`tier1-final/<label>/gather_output.json`). 노출 `present` 수 == 최종 JSON 수집 수(`storage.physical_disks` · `storage.hbas` · `network.ports` FC) 여야 PASS, 차이는 ABSENT_EMPTY_BAY / POWER_OFF_NOT_EXPOSED / DEDUP_SAME_DRIVE 로만 설명, 그 밖은 UNEXPLAINED → FAIL. 노출 0 장비는 수집 0(placeholder 0).
- 결과: **18/18 PASS · UNEXPLAINED 0**. WP1(e) 기준선(`inventory-parity-before.md`)과 같은 분류·같은 수 — 구현 Round 전체에서 디스크·FC 포트가 늘거나 빠진 label 없음(각 WP 의 Tier 1 allowlist diff 와 일치).

| label | PowerState | 디스크 노출(present/absent·빈 베이) | 디스크 수집(physical_disks) | FC 포트 노출(+orphan NDF) | FC 수집(hbas) | 판정 | 설명 |
|---|---|---|---|---|---|---|---|
| csus3200_01 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 4/0 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH |
| csus3200_02 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 4/0 | 4 | 0(+0) | 0 | PASS | DISKS_MATCH, FC_MATCH, NO_FC_EXPOSED |
| csus3200_03 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 4/0 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH |
| dl380_gen12_01 | {'Systems/1': 'On'} | 2/6 | 2 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH |
| dl380_gen12_02 | {'Systems/1': 'On'} | 4/4 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH |
| dl380_gen12_03 | {'Systems/1': 'Off'} | 0/0 | 0 | 0(+0) | 0 | PASS | DISKS_MATCH, POWER_OFF_NOT_EXPOSED, FC_MATCH, NO_FC_EXPOSED |
| dl380_gen12_04 | {'Systems/1': 'On'} | 4/4 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH |
| sr650_v4_01 | {'Systems/1': 'On'} | 4/0 | 4 | 0(+0) | 0 | PASS | DISKS_MATCH, FC_MATCH, NO_FC_EXPOSED |
| sr650_v4_02 | {'Systems/1': 'On'} | 4/0 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH, FC_IN_HOST_ETHERNET:4 |
| sr650_v4_03 | {'Systems/1': 'On'} | 2/0 | 2 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH, FC_IN_HOST_ETHERNET:4 |
| sr650_v4_04 | {'Systems/1': 'On'} | 6/0 | 6 | 0(+0) | 0 | PASS | DISKS_MATCH, FC_MATCH, NO_FC_EXPOSED |
| r1_DELL_R740_01 | {'Systems/System.Embedded.1': 'On'} | 4/0 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH |
| r1_HPE_CSUS3200_01 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 0/0 | 0 | 4(+0) | 4 | PASS | DISKS_MATCH, NO_DISK_EXPOSED, FC_MATCH |
| r1_HPE_CSUS3200_02 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 0/0 | 0 | 4(+0) | 4 | PASS | DISKS_MATCH, NO_DISK_EXPOSED, FC_MATCH |
| r1_HPE_CSUS3200_03 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 2/0 | 2 | 8(+0) | 8 | PASS | DISKS_MATCH, FC_MATCH |
| r1_HPE_CSUS3200_04 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 2/0 | 2 | 8(+0) | 8 | PASS | DISKS_MATCH, FC_MATCH |
| r1_HPE_DL380_01 | {'Systems/1': 'On'} | 2/6 | 2 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH |
| r1_Lenovo_SR650_01 | {'Systems/1': 'On'} | 4/0 | 4 | 0(+0) | 0 | PASS | DISKS_MATCH, FC_MATCH, NO_FC_EXPOSED |
