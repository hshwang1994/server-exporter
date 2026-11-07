| label | Tier1 status | vendor | adapter (1차 선택 → 최종) | errors | 요청 수 / 경로 | hostname | serial | cpu s/c/t | mem MB | disks | nics/adapters/ports | fw | psu/fan/temp | bios attrs | multi_node |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| csus3200_01 | success | hpCsus | redfish_hpe_csus_3200 | 0 | 200 / 193 | yicdspdb01 | SGHD4MGNLH | 4/64/128 | 1048576 | 4 | 8/6/12 | 13 | 4/10/63 | 76 | enabled:True,layout:rmc_primary,summary:6,partitions:1,managers:1,chassis:3,composition:5,fabrics:1,errors:0 |
| csus3200_02 | success | hpCsus | redfish_hpe_csus_3200 | 0 | 148 / 141 | yicgsfabap01 | SGHD4MGJMN | 4/112/224 | 524288 | 4 | 4/2/4 | 9 | 4/10/47 | 76 | enabled:True,layout:rmc_primary,summary:6,partitions:1,managers:1,chassis:3,composition:5,fabrics:1,errors:0 |
| csus3200_03 | success | hpCsus | redfish_hpe_csus_3200 | 0 | 184 / 177 | yicgsfabdb01 | SGHD4MGRSV | 4/64/128 | 524288 | 4 | 8/6/12 | 13 | 4/10/47 | 76 | enabled:True,layout:rmc_primary,summary:6,partitions:1,managers:1,chassis:3,composition:5,fabrics:1,errors:0 |
| dl380_gen12_01 | success | hp | redfish_hpe_ilo7 | 0 | 156 / 152 | yicesxmgmt05 | SGHD48K272 | 2/64/128 | 1572864 | 2 | 10/7/14 | 25 | 2/6/56 | 311 | - |
| dl380_gen12_02 | success | hp | redfish_hpe_ilo7 | 0 | 147 / 143 | yicad04 | SGHD49KSSM | 2/64/128 | 262144 | 4 | 8/6/12 | 25 | 2/6/44 | 301 | - |
| dl380_gen12_03 | success | hp | redfish_hpe_ilo7 | 0 | 84 / 80 | yicossemul03 | SGHD49KSP1 | 2/64/128 | 524288 | 0 | 4/2/4 | 13 | 2/6/42 | 275 | - |
| dl380_gen12_04 | success | hp | redfish_hpe_ilo7 | 0 | 147 / 143 | yicinposdb02 | SGHD49KSTF | 2/64/128 | 262144 | 4 | 8/6/12 | 25 | 2/6/54 | 297 | - |
| sr650_v4_01 | success | lenovo | redfish_lenovo_xcc3 → redfish_lenovo_bmc | 0 | 112 / 108 | yicad01 | J90312WM | 2/64/128 | 131072 | 4 | 5/2/4 | 28 | 2/6/8 | 778 | - |
| sr650_v4_02 | success | lenovo | redfish_lenovo_xcc3 → redfish_lenovo_bmc | 0 | 129 / 125 | yicbringup01 | J90312WP | 2/64/128 | 131072 | 4 | 9/4/8 | 30 | 2/6/8 | 1116 | - |
| sr650_v4_03 | success | lenovo | redfish_lenovo_xcc3 → redfish_lenovo_bmc | 0 | 163 / 159 | yicinfesx001 | J9031BV4 | 2/64/128 | 1048576 | 2 | 15/7/14 | 40 | 2/6/22 | 1299 | - |
| sr650_v4_04 | success | lenovo | redfish_lenovo_xcc3 → redfish_lenovo_bmc | 0 | 117 / 113 | yichtwinap09 | J90319RE | 2/64/128 | 262144 | 6 | 5/2/4 | 30 | 2/6/14 | 778 | - |
| r1_DELL_R740_01 | success | dell | redfish_dell_idrac10 → redfish_dell_idrac9 | 0 | 141 / 137 | DELL01 | J0KV603 | 2/48/96 | 262144 | 4 | 12/7/16 | 32 | 2/6/4 | 380 | - |
| r1_HPE_CSUS3200_01 | success | hpCsus | redfish_hpe_csus_3200 | 0 | 145 / 138 | RMC7CA62A413692 | SGHD3TLNDD | 4/32/64 | 524288 | 0 | 0/2/4 | 6 | 4/10/47 | 75 | enabled:True,layout:rmc_primary,summary:6,partitions:1,managers:1,chassis:3,composition:5,fabrics:1,errors:0 |
| r1_HPE_CSUS3200_02 | success | hpCsus | redfish_hpe_csus_3200 | 0 | 145 / 138 | RMC7CA62A418172 | SGHD3VFL1S | 4/32/64 | 524288 | 0 | 0/2/4 | 6 | 4/10/47 | 75 | enabled:True,layout:rmc_primary,summary:6,partitions:1,managers:1,chassis:3,composition:5,fabrics:1,errors:0 |
| r1_HPE_CSUS3200_03 | success | hpCsus | redfish_hpe_csus_3200 | 0 | 214 / 207 | M10MESDB11-RMC | SGHD3QHLDT | 4/64/128 | 1048576 | 2 | 8/8/16 | 15 | 4/10/63 | 75 | enabled:True,layout:rmc_primary,summary:6,partitions:1,managers:1,chassis:3,composition:5,fabrics:1,errors:0 |
| r1_HPE_CSUS3200_04 | success | hpCsus | redfish_hpe_csus_3200 | 0 | 214 / 207 | M10APCDB11-RMC | SGHD3QHLN3 | 4/64/128 | 1048576 | 2 | 8/8/16 | 15 | 4/10/63 | 75 | enabled:True,layout:rmc_primary,summary:6,partitions:1,managers:1,chassis:3,composition:5,fabrics:1,errors:0 |
| r1_HPE_DL380_01 | success | hp | redfish_hpe_ilo7 | 0 | 135 / 131 | ILOSGHD3KHHRP | SGHD3KHHRP | 2/48/96 | 1048576 | 2 | 6/5/10 | 22 | 2/6/52 | 292 | - |
| r1_Lenovo_SR650_01 | success | lenovo | redfish_lenovo_xcc3 → redfish_lenovo_bmc | 0 | 127 / 123 | XCC-7DGD-J902E57T | J902E57T | 2/32/64 | 1048576 | 4 | 13/3/12 | 26 | 2/12/22 | 1223 | - |
