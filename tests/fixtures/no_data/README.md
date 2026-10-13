# 정상 경로 failed(성공 섹션 0개) 대표 오류 시험 fixture

`tests/integration/test_build_output_no_data_playbook.py` 가 쓰는 합성(synthetic) 자료다. 실장비에서 캡처한 값이
아니며 Vendor 와 무관하다.

| 경로 | 무엇 |
|---|---|
| `harness.yml` | 실제 공통 조립 코드(`init_fragments` → `merge_fragment` → `build_sections` → `build_status` → `build_errors` → `build_output`)와 `json_only` 콜백을 그대로 태우는 playbook. 수집 대신 고정 fragment 를 넣고 연결은 local 이다. 사례(`-e harness_case=`)는 파일 안 `_hc_cases` 에 있다 |

무엇을 보나 (2026-10-13, H12 후속): 정상 경로에서 성공 섹션이 0개라 `status=failed` 가 됐을 때 `errors[0].message` 가
`diagnosis.failure_reason`(수집된 정보가 없다는 문장)과 같은가, 섹션 오류는 뒤에 보존되는가, 상한 10 + 절단 표시가 붙는가,
채널 표시(`linux_gather` · `windows_gather` · `esxi_gather` · `redfish_gather`)가 맞는가, OS 채널에서는 그 뒤에 `require_serial.yml`
의 Serial 오류가 붙는가. `partial` 대조군은 아무것도 바뀌지 않아야 한다.
