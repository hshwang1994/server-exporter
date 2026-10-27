# Golden 정정 원장 (FIX 9 — 검증된 항목만, before/after·원천·원인)

> `tests/fixtures/redfish/real_*/expected_output.json`(모듈 산출 GOLDEN_KEYS) 과 `schema/baseline_v1/*.json` 에 손댄 모든 항목을
> 여기 적는다. 전면 재생성 금지 — 각 행은 원천 경로와 원인이 있어야 한다. 2026-10-27 WP1 부터 누적.

| # | WP | fixture / baseline | 경로 | before | after | 원천 | 원인 |
|---|---|---|---|---|---|---|---|
| G-01 | WP1(d) | `real_dell_r740` | `data.bios.current.attributes` | `null` | dict 380 keys | 1차 전수 미러 `DELL_R740/01/redfish/v1/Systems/System.Embedded.1/Bios/index.json`(_status 200, `#Bios.v1_2_0.Bios`) → recording `get::Systems/System.Embedded.1/Bios` 추가 | replay-miss: gather 는 `Bios.@odata.id` 를 1회 요청(예산 `Systems/System.Embedded.1/Bios x1`)하지만 축약 recording 에 응답이 없어 404 → null. 요청 수 불변 |
| G-02 | WP1(d) | `real_hpe_dl380` | `data.bios.current.attributes` | `null` | dict 292 keys | 1차 전수 미러 `HPE_DL380/01/redfish/v1/Systems/1/bios/index.json`(_status 200, `#Bios.v1_2_3.Bios`, 링크 소문자 `/redfish/v1/systems/1/bios`) → recording `get::systems/1/bios` 추가 | 같음(예산 `systems/1/bios x1`) |
| G-03 | WP1(d) | `real_lenovo_sr650` | `data.bios.current.attributes` | `null` | dict 1223 keys | 1차 전수 미러 `Lenovo_SR650/01/redfish/v1/Systems/1/Bios/index.json`(_status 200, `#Bios.v1_2_0.Bios`) → recording `get::Systems/1/Bios` 추가 | 같음(예산 `Systems/1/Bios x1`) |

- G-01~03 검증: 추가 전후 모듈 산출을 전체 평탄 비교 → 차이는 `data.bios` 뿐(각 N+1 경로). `test_real_capture_replay`·`test_request_budget`·`test_inventory_count_parity`(해당 3세트 + 2차) PASS. `request_budget.json` 3종 불변.
- 1차 `real_hpe_csus3200` 은 recording 에 `get::Systems/Partition0/Bios` 가 이미 있어 변경 없음.
