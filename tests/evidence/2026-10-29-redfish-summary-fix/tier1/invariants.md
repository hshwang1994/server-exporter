# Tier 1 불변 항목 · 남은 미확정 값 — `<scratch>/tier1_after`

- 기준: `<scratch>/tier1_base`

| label | status | HBA 수 | HBA link 값 | 링크 notice | 전원 Off notice | logical_threads | 기준과 HBA 같음 | link unknown interfaces |
|---|---|---|---|---|---|---|---|---|
| csus3200_01 | success | 4 | down | 2 | 0 | 0 | 같음 | PCIeCard1Eth0 f4:20:4d:f6:5e:92; PCIeCard1Eth1 f4:20:4d:f6:5e:93; PCIeCard9Eth0 f4:20:4d:f6:5e:ba; PCIeCard9Eth1 f4:20:4d:f6:5e:bb; PCIeCard8Eth0 f4:20:4d:f6:83:5e; PCIeCard8Eth1 f4:20:4d:f6:83:5f; PCIeCard16Eth0 84:eb:0c:3e:3c:9c; PCIeCard16Eth1 84:eb:0c:3e:3c:9d |
| csus3200_02 | success | 0 | - | 0 | 0 | 0 | 같음 | PCIeCard1Eth0 f4:20:4d:f6:5d:aa; PCIeCard1Eth1 f4:20:4d:f6:5d:ab; PCIeCard9Eth0 f4:20:4d:f6:5e:26; PCIeCard9Eth1 f4:20:4d:f6:5e:27 |
| csus3200_03 | success | 4 | down | 2 | 0 | 0 | 같음 | PCIeCard1Eth0 f4:20:4d:f6:85:86; PCIeCard1Eth1 f4:20:4d:f6:85:87; PCIeCard9Eth0 f4:20:4d:f6:85:56; PCIeCard9Eth1 f4:20:4d:f6:85:57; PCIeCard16Eth0 f4:20:4d:f6:84:b2; PCIeCard16Eth1 f4:20:4d:f6:84:b3; PCIeCard8Eth0 f4:20:4d:f6:5c:fa; PCIeCard8Eth1 f4:20:4d:f6:5c:fb |
| dl380_gen12_01 | success | 4 | down, up | 0 | 0 | 0 | 같음 | - |
| dl380_gen12_02 | success | 4 | down | 0 | 0 | 0 | 같음 | - |
| dl380_gen12_03 | success | 0 | - | 0 | 1 | 0 | 같음 | 77 74:10:e0:02:65:50; 78 74:10:e0:02:65:51; 269 74:10:e0:02:69:70; 270 74:10:e0:02:69:71 |
|  | 전원 Off 문구 | | | | `호스트 전원 Off 관측 — 저장/네트워크/메모리/전원/온도 인벤토리가 비어 있거나 placeholder 일 수 있음` | | | |
| dl380_gen12_04 | success | 4 | down, up | 0 | 0 | 0 | 같음 | - |
| r1_DELL_R740_01 | success | 4 | down | 0 | 0 | 0 | 같음 | - |
| r1_HPE_CSUS3200_01 | success | 4 | down | 2 | 0 | 0 | 같음 | - |
| r1_HPE_CSUS3200_02 | success | 4 | down | 2 | 0 | 0 | 같음 | - |
| r1_HPE_CSUS3200_03 | success | 8 | down | 4 | 0 | 0 | 같음 | PCIeCard1Eth0 60:5e:65:21:6e:d4; PCIeCard1Eth1 60:5e:65:21:6e:d5; PCIeCard5Eth0 60:5e:65:21:6d:f0; PCIeCard5Eth1 60:5e:65:21:6d:f1; PCIeCard9Eth0 60:5e:65:21:6e:0c; PCIeCard9Eth1 60:5e:65:21:6e:0d; PCIeCard13Eth0 60:5e:65:21:7d:6c; PCIeCard13Eth1 60:5e:65:21:7d:6d |
| r1_HPE_CSUS3200_04 | success | 8 | down | 4 | 0 | 0 | 같음 | PCIeCard1Eth0 60:5e:65:21:73:08; PCIeCard1Eth1 60:5e:65:21:73:09; PCIeCard5Eth0 60:5e:65:21:50:d8; PCIeCard5Eth1 60:5e:65:21:50:d9; PCIeCard9Eth0 60:5e:65:21:72:68; PCIeCard9Eth1 60:5e:65:21:72:69; PCIeCard13Eth0 60:5e:65:21:7d:9c; PCIeCard13Eth1 60:5e:65:21:7d:9d |
| r1_HPE_DL380_01 | success | 4 | down | 0 | 0 | 0 | 같음 | - |
| r1_Lenovo_SR650_01 | success | 0 | - | 0 | 0 | 0 | 같음 | ToManager c4:ef:bb:1d:43:46 |
| sr650_v4_01 | success | 0 | - | 0 | 0 | 0 | 같음 | ToManager 18:3d:2d:a5:cf:b8 |
| sr650_v4_02 | success | 4 | down | 0 | 0 | 0 | 같음 | ToManager 18:3d:2d:a5:ca:d6; NIC6 ec:e7:a7:22:61:80 |
| sr650_v4_03 | success | 4 | down, up | 0 | 0 | 0 | 같음 | ToManager 18:3d:2d:a5:d1:ac |
| sr650_v4_04 | success | 0 | - | 0 | 0 | 0 | 같음 | ToManager 18:3d:2d:a5:ee:e4; NIC4 ec:e7:a7:22:4b:5c |

- 위반: 0건
