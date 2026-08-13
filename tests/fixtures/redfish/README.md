# tests/fixtures/redfish

Redfish 채널 fixture. BMC 가 실제로 돌려준 JSON 응답을 그대로 저장해서 mock 회귀
입력으로 쓴다. 실장비 없이도 adapter 선택과 normalize 를 돌려 보라고 모아 둔다.

같은 vendor 라도 펌웨어 세대가 다르면 응답 형태가 달라진다. 그래서 디렉터리도 대체로
`<vendor>` 또는 `<vendor>_<BMC 세대>` 로 나뉜다 (예: `cisco_cimc_v2` ~ `v4`).

| 디렉터리 | JSON | 출처 README |
|---|---|---|
| `cisco/` | 27 | 없음 |
| `cisco_bmc/` | 0 | 있음 |
| `cisco_cimc_v2/` | 2 | 있음 |
| `cisco_cimc_v3/` | 2 | 있음 |
| `cisco_cimc_v4/` | 2 | 있음 |
| `dell/` | 55 | 없음 |
| `dell_idrac/` | 2 | 있음 |
| `dell_idrac8/` | 2 | 있음 |
| `dell_idrac9/` | 2 | 있음 |
| `dell_r760/` | 27 | 없음 |
| `dmtf_rackmount1/` | 2 | 있음 |
| `fujitsu_irmc_s5/` | 11 | 있음 |
| `fujitsu_irmc_s6/` | 11 | 있음 |
| `hpe/` | 50 | 없음 |
| `hpe_csus_3200/` | 36 | 있음 |
| `hpe_emulator_dl325_gen10plus_fc/` | 2 | 있음 |
| `hpe_emulator_dl360/` | 2 | 있음 |
| `hpe_emulator_dl365_gen10plus/` | 2 | 있음 |
| `hpe_emulator_dl380a/` | 2 | 있음 |
| `hpe_emulator_dl380a_gen12/` | 2 | 있음 |
| `hpe_ilo/` | 0 | 있음 |
| `hpe_ilo4/` | 2 | 있음 |
| `hpe_ilo5/` | 2 | 있음 |
| `hpe_ilo6/` | 2 | 있음 |
| `hpe_ilo6_v1_73/` | 3 | 없음 |
| `hpe_superdome_flex/` | 11 | 있음 |
| `huawei_atlas/` | 4 | 있음 |
| `huawei_ibmc_v2/` | 12 | 있음 |
| `huawei_ibmc_v4/` | 5 | 있음 |
| `inspur_isbmc/` | 12 | 있음 |
| `lenovo/` | 47 | 없음 |
| `lenovo_bmc/` | 0 | 있음 |
| `lenovo_imm2/` | 2 | 있음 |
| `lenovo_xcc/` | 2 | 있음 |
| `quanta_qct/` | 11 | 있음 |
| `real_dell_r740/` | 3 | 있음 |
| `real_hpe_csus3200/` | 3 | 있음 |
| `real_hpe_dl380/` | 3 | 있음 |
| `real_lenovo_sr650/` | 3 | 있음 |
| `supermicro_x10/` | 12 | 있음 |
| `supermicro_x12/` | 12 | 있음 |
| `supermicro_x14/` | 12 | 있음 |

루트 직속 JSON 0건은 특정 vendor 에 매이지 않는 표준·경계 케이스다.

## 새 fixture 를 넣을 때

1. 어느 장비에서 떴는지 적는다 — vendor, 모델, 펌웨어 버전, 수집 날짜, 명령
2. 자격증명·시리얼 등 민감값이 남아 있지 않은지 본다
   (`scripts/ai/verify_no_plaintext_secret.py` 가 커밋을 막는다)
3. 해당 디렉터리 README 에 한 줄 추가 (rule 21 R2 — 출처 불명 fixture 금지)
4. fixture 를 **고치는** 경우에는 영향 vendor baseline 회귀를 돌린다 (rule 21 R3)

출처를 안 적으면 나중에 외부 계약이 바뀌었을 때 이 응답이 언제 기준인지 알 수 없다.
그러면 회귀 판정을 못 한다.
