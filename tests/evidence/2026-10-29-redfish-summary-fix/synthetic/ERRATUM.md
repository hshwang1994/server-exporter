# 합성 미러 판정 정오표 (2026-10-29)

- 작성: AI(Claude) · 2026-10-29. 대상은 `expected.json`(사전 등록, sha256 `88e1b69a37682a407083524cf21c1f07e7e76eb6841a4fd7807fea59f6e3cc35`)과 그 판정 `results.md` · `results.json` 이다.
- `expected.json` 은 실행 뒤에 고치지 않았다(파일 `_doc` 의 약속). 등록 판정은 그대로 둔다: **head 9건 중 PASS 7 · FAIL 2**.

## 1. FAIL 2건의 원인 — 기대값 경로 이름 오기

| case | 실패한 단정 | 허용 목록 밖으로 나온 경로 |
|---|---|---|
| `syn_g12_03_on` | 수정 전 미러 출력 대비 차이 ⊆ `['data.system.power_state', 'diagnosis.details.notices']` | `data.hardware.power_state` |
| `syn_r1csus01_off` | 수정 전 미러 출력 대비 차이 ⊆ `['data.system.power_state', 'data.multi_node.partitions[0].system.power_state', 'diagnosis.details.notices']` | `data.hardware.power_state` |

- 두 사례의 edit 은 `Systems/*` 의 `PowerState` 하나뿐이다. 이 값은 봉투의 `data.hardware.power_state` 로 나간다(`schema/field_dictionary.yml` 의 `hardware.power_state` 항목).
- 봉투의 `data.system` 에는 `power_state` 키가 없다. 수정 전과 합성 봉투 4개를 직접 확인했다(`dl380_gen12_03` · `r1_HPE_CSUS3200_01` · `syn_g12_03_on` · `syn_r1csus01_off`).
- 그래서 등록한 허용 목록은 전원 상태가 바뀌는 어떤 구현에서도 통과할 수 없었다. 기대값을 적을 때 필드 이름을 잘못 쓴 것이다. 코드 결함이 아니다.
- 같은 두 사례의 값 단정은 등록 기준으로 모두 PASS 다.
  - `syn_g12_03_on`: 디스크 0, `grand_total_gb` null, `health_rollup` null, 전원 Off notice 없음.
  - `syn_r1csus01_off`: 디스크 0, `grand_total_gb` 0, 전원 Off notice 있음.
- base 쪽 같은 단정도 같은 이유로 FAIL 이다. 그래서 `results.md` 의 "base 에서 결함 재현" 열이 두 사례에서 "아니오" 로 나온다.

## 2. 사후 점검 (실행 뒤 작성 — 사전 등록 아님)

- `expected_posthoc.json` = `expected.json` 에서 문자열 `"data.system.power_state"` 2곳만 `"data.hardware.power_state"` 로 바꾼 사본이다. 다른 바이트는 같다.
  - 만든 방법: 바이트 치환이며 치환 횟수 2를 확인했다. `diff expected.json expected_posthoc.json` 은 199행과 215행 두 줄만 다르다.
  - sha256 `b10221c0de6b6108cd7f2fddb2361c7dd38346ddfdb8bfcf8a9e17208960a612`
- 결과 `results_posthoc.md` · `results_posthoc.json`: **head 9/9 PASS** · base 9/9 결함 재현.
- 사후 점검이므로 사전 등록 PASS 로 세지 않는다. 보고는 "등록 기준 7/9 PASS. FAIL 2는 기대값 경로 오기이며, 그 경로만 고친 사후 점검은 9/9" 로 한다.

## 3. 실제 차이 (두 사례 · 수정 전 미러 출력 대비, meta 시각 제외)

| case | 코드 | 차이 경로 | 내용 |
|---|---|---|---|
| `syn_g12_03_on` | HEAD | `data.hardware.power_state` · `notices[1]` · `notices[2]` | 전원 Off notice(system)가 빠져 storage null notice 가 `[1]` 로 당겨졌다. `grand_total_gb` null · `health_rollup` null 은 그대로다. storage notice "드라이브 목록 원천 … 하나도 읽지 못함" 도 남아 있다(등록 단정 밖 — 관찰) |
| `syn_g12_03_on` | base | `data.hardware.power_state` · `notices[1]` | 전원 Off notice 만 빠짐. `grand_total_gb` 0 그대로(결함: 원천 없음을 0으로) |
| `syn_r1csus01_off` | HEAD · base | `data.hardware.power_state` · `partitions[0].system.power_state` · `notices[3]` | 전원 Off notice 추가. `grand_total_gb` 0 그대로(확인한 0) |

- 결론(SA-07): storage `grand_total_gb` 의 null/0 판정은 전원 상태와 독립이다. 전원 Off notice 만 전원 상태를 따른다.
- `syn_r1csus01_off` 는 대조군이다. base 도 0 이 맞는 입력이므로 "결함 재현" 이 아니라 "HEAD · base 같음" 으로 읽는다.

## 4. 기준 출력

- `--head-ref` 는 HEAD 코드로 돌린 수정 전 미러 출력이다. 이 폴더 상위의 `tier1-after/`(build `sa-after-866d28d8`)와 같다.
- `--base-ref` 는 `104bcaf0` 으로 돌린 수정 전 미러 출력이다. 이것은 `tests/evidence/2026-10-28-redfish-mock2-review-fix/tier1-A` 와 내용 차이 0이다(`../tier1/base_equiv.md`). base-ref 를 tier1-A 로 바꿔 다시 판정해도 `results.json` 과 같았다.
