# 디스크 · FC 포트 개수 정합 — `tests/evidence/2026-10-28-redfish-mock2-review-fix/tier1-A`

- 판별기 `tests/scripts/inventory_parity.py` × Tier 1 봉투, label 18 · 종료 코드 0 아님 0

| label | PowerState | 디스크 노출(present/absent·빈 베이) | 디스크 수집 | FC 포트 노출(+orphan NDF) | FC 수집(hbas) | 판정 | 설명 | rc |
|---|---|---|---|---|---|---|---|---|
| csus3200_01 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 4/0 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH | rc 0 |
| csus3200_02 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 4/0 | 4 | 0(+0) | 0 | PASS | DISKS_MATCH, FC_MATCH, NO_FC_EXPOSED | rc 0 |
| csus3200_03 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 4/0 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH | rc 0 |
| dl380_gen12_01 | {'Systems/1': 'On'} | 2/6 | 2 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH | rc 0 |
| dl380_gen12_02 | {'Systems/1': 'On'} | 4/4 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH | rc 0 |
| dl380_gen12_03 | {'Systems/1': 'Off'} | 0/0 | 0 | 0(+0) | 0 | PASS | DISKS_MATCH, POWER_OFF_NOT_EXPOSED, FC_MATCH, NO_FC_EXPOSED | rc 0 |
| dl380_gen12_04 | {'Systems/1': 'On'} | 4/4 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH | rc 0 |
| sr650_v4_01 | {'Systems/1': 'On'} | 4/0 | 4 | 0(+0) | 0 | PASS | DISKS_MATCH, FC_MATCH, NO_FC_EXPOSED | rc 0 |
| sr650_v4_02 | {'Systems/1': 'On'} | 4/0 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH, FC_IN_HOST_ETHERNET:4 | rc 0 |
| sr650_v4_03 | {'Systems/1': 'On'} | 2/0 | 2 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH, FC_IN_HOST_ETHERNET:4 | rc 0 |
| sr650_v4_04 | {'Systems/1': 'On'} | 6/0 | 6 | 0(+0) | 0 | PASS | DISKS_MATCH, FC_MATCH, NO_FC_EXPOSED | rc 0 |
| r1_DELL_R740_01 | {'Systems/System.Embedded.1': 'On'} | 4/0 | 4 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH | rc 0 |
| r1_HPE_CSUS3200_01 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 0/0 | 0 | 4(+0) | 4 | PASS | DISKS_MATCH, NO_DISK_EXPOSED, FC_MATCH | rc 0 |
| r1_HPE_CSUS3200_02 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 0/0 | 0 | 4(+0) | 4 | PASS | DISKS_MATCH, NO_DISK_EXPOSED, FC_MATCH | rc 0 |
| r1_HPE_CSUS3200_03 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 2/0 | 2 | 8(+0) | 8 | PASS | DISKS_MATCH, FC_MATCH | rc 0 |
| r1_HPE_CSUS3200_04 | {'Systems/Capabilities': None, 'Systems/Partition0': 'On'} | 2/0 | 2 | 8(+0) | 8 | PASS | DISKS_MATCH, FC_MATCH | rc 0 |
| r1_HPE_DL380_01 | {'Systems/1': 'On'} | 2/6 | 2 | 4(+0) | 4 | PASS | DISKS_MATCH, FC_MATCH | rc 0 |
| r1_Lenovo_SR650_01 | {'Systems/1': 'On'} | 4/0 | 4 | 0(+0) | 0 | PASS | DISKS_MATCH, FC_MATCH, NO_FC_EXPOSED | rc 0 |
