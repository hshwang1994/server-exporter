# 수정 전 기준선 (baseline) — 2026-10-26, main `e8b5ae9b` (코드는 `e0a4f143` 과 동일)

세 층으로 기록했다. 어느 층도 코드를 고치지 않았고, 설정을 손으로 주입하지 않았다(Tier 1 의 `manager_layout`/`firmware_inventory_scope` 는 실제 adapter 가 고른 값).

| 층 | 무엇을 돌렸나 | 산출 |
|---|---|---|
| Tier 0 | 기존 pytest 회귀(변경 0) — Windows Python 3.13.15 + WSL(엔진 테스트) | `tier0/*.log` |
| Tier 1 | **실제 Gathering 경로**: `redfish-gather/site.yml` 을 실제 ansible-playbook(WSL Ubuntu, ansible-core 2.20.7)으로 실행. precheck → detect_vendor → 실제 vault → `adapter_loader` 1차 선택 → 빈 자격 시도 → 표준 계정 수집(모듈 `main()`, `_SERIAL_RESOLVERS` 포함) → `reselect_adapter` → `normalize_standard` → `build_*` → `json_only` 콜백. BMC 는 미러 재생 HTTPS 서버(`../tools/mirror_https_server.py`, 127.0.0.1:443)가 대신한다 | `tier1/<label>/gather_output.json`(최종 envelope), `server_access.jsonl`(gather 가 실제 보낸 요청: 경로·상태·인증 구분), `requested_keys.json`, `gather_progress.jsonl`, `run_meta.json`, `_summary.json` |
| Tier 2 | 모듈 수준 재생: `replay_full_mirror.build_response_map` + `emulator_harness.run_gather`(테스트와 같은 엔진). `plain`=adapter 값 없이, `adapter`=CSUS 에 `rmc_primary`/`complex_only`(Tier 1 이 실제로 고른 값과 같다) | `tier2/<label>.{plain,adapter}.module.json`(GOLDEN_KEYS), `_golden_compare.*.json`, `_summary.*.json` |
| 보조 | 노출 vs 요청 커버리지(`scripts/ai/redfish_coverage_diff.py`), 오프라인 adapter 1차 선택 점수(`tests/redfish-probe/verify_adapter_selection.py` 로직) | `coverage/<label>.{json,txt}`, `adapter_selection_*.{txt,json}` |

label: 2차는 서버 이름, 1차는 `r1_DELL_R740_01`, `r1_HPE_CSUS3200_01..04`, `r1_HPE_DL380_01`, `r1_Lenovo_SR650_01`.

## Tier 1 결과 (18/18 playbook rc=0, status=success, errors=0) — 상세 `baseline_summary.md`

| label | vendor | adapter 1차 선택 → 최종(`meta.adapter_id`) | 요청 수 / distinct | hostname 출처 | multi_node |
|---|---|---|---|---|---|
| csus3200_01..03 | hpCsus | redfish_hpe_csus_3200 (변경 없음) | 200/193 · 148/141 · 184/177 | bmc_first(RMC) | partitions 1 · managers 1 · chassis 3 · composition 5 · fabrics 1 |
| dl380_gen12_01..04 | hp | redfish_hpe_ilo7 (변경 없음) | 156/152 · 147/143 · 84/80 · 147/143 | — | - |
| sr650_v4_01..04 | lenovo | **redfish_lenovo_xcc3 → redfish_lenovo_bmc** (로그인 후 재선택이 범용 adapter 로 내려감) | 112/108 · 129/125 · 163/159 · 117/113 | — | - |
| r1_DELL_R740_01 | dell | **redfish_dell_idrac10 → redfish_dell_idrac9** (1차 선택은 priority 만으로 idrac10, 재선택이 바로잡음) | 141/137 | — | - |
| r1_HPE_CSUS3200_01..04 | hpCsus | redfish_hpe_csus_3200 | 145/138 · 145/138 · 214/207 · 214/207 | bmc_first(RMC) | 위와 같음 |
| r1_HPE_DL380_01 | hp | redfish_hpe_ilo7 | 135/131 | — | - |
| r1_Lenovo_SR650_01 | lenovo | **redfish_lenovo_xcc3 → redfish_lenovo_bmc** | 127/123 | — | - |

- 요청 수는 재생 서버 접근 로그 기준(무인증 root 3회 + 빈 자격 시도의 401 2회 포함). `requested_keys.json` 의 `distinct_keys` 가 "코드가 요청한 경로 집합" 정본이다.
- CSUS 3대·1차 CSUS 는 미러에 없는 경로 11개를 요청했다(`Chassis/Rack1|RackGroup/{Power,Thermal,PowerSubsystem,ThermalSubsystem}`, `Chassis/r001u01/{EnvironmentMetrics,Power,Thermal}`) — 재생 서버는 404 를 돌려줬다. 실장비 응답은 미러에 없어 **검증 불가**(크롤러는 링크를 따라가므로 장비가 링크하지 않은 고정 경로다).

## Tier 2 결과

- `plain`(adapter 값 없음) 18/18 status=success, 10 섹션 수집, error 0, multi_node None. `adapter`(CSUS 7대) 도 success, multi_node 수집.
- 1차 7대 ↔ 저장소 golden(`tests/fixtures/redfish/real_*/expected_output.json`):
  - Dell R740 / DL380 / SR650: 차이 **1건** — `data.bios.current.attributes` 가 golden 은 None, 재생은 값 있음 (golden 이 `gather_bios` 도입 전 recording 이라 Bios 를 담지 않음 = 축약 fixture 의 replay-miss). 그 밖은 동일.
  - CSUS `01`: `adapter` 모드에서 **차이 0** (plain 모드 차이 3건은 layout 미적용에 따른 당연한 차이).
- 추출본(zip) 재생 = 원본 폴더 재생 11/11 동일 (`_run_plain_extract.log` 는 scratchpad 에만).

## Tier 0 결과 (변경 0, Windows)

| 실행 | 결과 |
|---|---|
| `pytest tests/integration -m "not live"` | 366 passed, 6 skipped, 1 deselected (`tier0/pytest_integration_notlive_windows.log`) |
| WSL(Ubuntu) `test_build_output_no_data_playbook.py` + `test_addon_hook_playbook.py` (Windows 에서는 skip 되는 엔진 테스트) | 23 passed (`tier0/pytest_engine_wsl.log`) |
| `pytest tests/unit tests/e2e tests/regression` 를 **한 프로세스**로 | 36 failed, 5930 passed, 45 skipped, 6 xfailed (`tier0/pytest_unit_e2e_regression.log`). 실패 36건 중 표본 8건은 단독 실행 시 통과 → 모듈 전역 상태(캐시·인증 관측·재생 seam) 오염으로 보이는 **테스트 격리 결함 후보**(ISSUES 에 기록). 프로젝트 문서의 실행 단위는 `tests/e2e tests/regression` 과 `tests/unit` 분리 |
| `pytest tests/e2e tests/regression` (분리 실행, 프로젝트 문서의 실행 단위) | **1094 passed, 12 skipped, 6 xfailed** (73.6 s) — TEST_HISTORY 2026-10-22 기록과 같다 (`tier0/pytest_e2e_regression.log`) |
| `pytest tests/unit` (분리 실행) | **19 failed, 4853 passed, 33 skipped** (24.8 min, `tier0/pytest_unit.log`). 실패 19건은 `test_redfish_audit_2026_10_10.py`(3) · `test_redfish_bios_current.py`(8) · `test_redfish_phase3_contracts.py`(6) · `test_redfish_redirect_boundary.py`(1) · `test_sanitize_mirror.py`(1) — 표본 단독 실행은 통과. 쌍 실행으로 재현: `pytest tests/unit/test_full_mirror_dryrun.py tests/unit/test_redfish_bios_current.py` → 8 failed (`test_mirror_replay_tools.py`·`test_csus_fixture_replay.py` 와의 쌍은 통과) — `test_full_mirror_dryrun.py` 가 남기는 전역 상태(모듈 seam/캐시)가 뒤 테스트를 오염시키는 **테스트 격리 결함**(순서 의존). ISSUES 에 기록, 수정은 하지 않음 |

## 검증 한계 (재생이 흉내 내지 못한 것 — 이슈가 아니라 미확정)

1. 익명 허용 범위: 재생 서버는 ServiceRoot(`/redfish/v1`), `odata`, `$metadata`, `/redfish` 만 무인증 200, 나머지는 401. 실장비의 익명 허용 집합은 미러에 없다.
2. 인증: Basic 에 사용자 이름만 있으면 통과(비밀번호 검증 없음). 401/403 분기, 계정 잠금, 복구 경로(`account_service.yml`)는 재현되지 않았다.
3. 무응답(timeout) 리소스는 "응답 없이 연결 종료"로 근사 — 실제 timeout(1800 s 대기)과 다르다. gather 는 해당 경로를 요청하지 않아 이번 결과에는 영향 없음.
4. 미러에 없는 경로는 404 — 실장비가 다른 상태/본문을 줄 수 있다(위 CSUS 11개 경로).
5. 응답 헤더: 2xx 는 기록된 `headers.json` 을 돌려주지만 401 본문·`WWW-Authenticate`(manifest `realm` 이 없는 DL380/SR650) 는 실장비와 다를 수 있다.
6. 1차 v1 미러: 비-2xx 상태가 기록되지 않아 404 로만 재생.
7. 엔진 버전: WSL ansible-core 2.20.7 vs 운영 Agent 2.20.3. `scripts/run_gather.sh` 의 작업 폴더 잠금·`gather_state.py` 재개·FORKS 계산은 거치지 않았다(ansible-playbook 인자·환경은 같다).
8. precheck 의 ICMP/TCP 는 127.0.0.1 대상 — 네트워크 경로 판정은 검증 대상이 아니다.
9. `correlation.bmc_ip` 는 미러 안의 BMC NIC 주소(원 장비 IP)로 채워진다 — 재생 대상 주소(127.0.0.1)와 다르므로 `ip`/`correlation.bmc_ip` 비교 시 유의.
