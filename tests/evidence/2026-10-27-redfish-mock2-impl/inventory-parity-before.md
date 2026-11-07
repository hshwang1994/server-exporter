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
