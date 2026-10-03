# Add-on hook 엔진 테스트 fixture

`tests/integration/test_addon_hook_playbook.py` 가 쓰는 합성(synthetic) 자료다. 실장비에서 캡처한 값이
아니며 Vendor 와 무관하다.

| 경로 | 무엇 |
|---|---|
| `harness.yml` | 실제 공통 조립 코드(`init_fragments` → `merge_fragment` → `build_*` → `inject schema_version` → `CHECKPOINT` → `run_addon.yml`)와 `json_only` 콜백을 그대로 태우는 playbook. 수집 대신 고정 fragment 하나를 넣고 연결은 local 이다. 2026-10-03 D8 부터 hook 은 조립 **뒤**다 |
| `ok/` | 정상 Add-on — 결과 1개, role `filter_plugins` 사용, 호출자 metadata(`se_host_input`) 읽기 |
| `empty/` | 돌려줄 것이 없는 Add-on — 결과도 참고 문장도 돌려주지 않는다 |
| `bad_config/` | 설정을 읽지 못한 Add-on — 결과 없이 참고 문장(`_addon_errors`)만 돌려준다 |
| `fail_runtime/` | 실행 중 실패하는 Add-on — hook 의 rescue 경로 |
| `unreachable/` | 실행 도중 연결이 끊기는 Add-on — `ignore_unreachable` 가 role 안까지 이어지는지 확인 |
| `hang/` | 끝나지 않는 Add-on(`sleep 40`, control node) — `include_role apply.timeout`(테스트는 3 s)이 태스크를 끊고 rescue 로 보내는지, CHECKPOINT 의 기본 결과가 보존되는지 확인 |

각 디렉터리는 `ADDON_DIR` 로 지정하는 Ansible role 형태다 (`tasks/main.yml`).
