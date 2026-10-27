# 00 — 수정 전 기준선 재측정 (WP0) · 테스트 격리 뒤 재확인 (WP1(a)) · Tier 1/2 기준선 (WP1(e))

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027`(분기점 `b8985826` = 분석 브랜치 최종 HEAD) · 제품 코드(`redfish-gather/**`, `module_utils/**`, `adapters/**`, `schema/**`) 변경 0 상태에서 측정.
- 환경: Windows Python 3.13.15 / pytest 9.1.1; WSL `Ubuntu` ansible-core 2.20.7 · Python 3.12.3 · pytest 9.0.3(playbook·엔진 테스트); WSL `Ubuntu-24.04` root(재생 HTTPS 서버, 443).
- 목적: 분석 Round(2026-10-26)가 적은 기준선을 **같은 브랜치·같은 코드에서 다시 재어** 뒤 WP 의 expected diff 의 "before" 를 고정한다. 분석 Round 수치를 그대로 믿지 않는다(rule 28).

## 1. Tier 0 (pytest) — 수정 전

| 실행 | 결과 | 로그 | 분석 Round 기록과 |
|---|---|---|---|
| `tests/e2e tests/regression` (분리) | 1094 passed · 12 skipped · 6 xfailed, rc 0 | `tier0/pytest_e2e_regression.log` | 일치 |
| `tests/integration -m "not live"` | 366 passed · 6 skipped · 1 deselected, rc 0 | `tier0/pytest_integration_notlive.log` | 일치 |
| `tests/unit` (분리) | **19 failed** · 4853 passed · 33 skipped, rc 1 | `tier0/pytest_unit.log` | 일치 |
| 한 프로세스 `tests/unit tests/e2e tests/regression` (= `ci_gate.sh` unit 단계) | **36 failed** · 5930 passed · 45 skipped · 6 xfailed, rc 1 | `tier0/pytest_unit_e2e_regression.log` | 일치 |
| WSL 엔진 2파일 (`test_build_output_no_data_playbook.py` + `test_addon_hook_playbook.py`) | 23 passed | `tier0/pytest_engine_wsl.log` | 일치 |
| `ansible-playbook --syntax-check` 3채널 (WSL) | 3/3 OK | `tier0/syntax_check_wsl.log` | — |

- 36 failed 의 파일별 내역(한 프로세스): `tests/regression/test_cross_channel_same_server.py` 11 · `tests/unit/test_redfish_bios_current.py` 8 · `tests/unit/test_redfish_phase3_contracts.py` 6 · `tests/regression/test_redfish_coverage_audit.py` 4 · `tests/unit/test_redfish_audit_2026_10_10.py` 3 · `tests/e2e/test_redfish_multi_credential_auth.py` 2 · `tests/unit/test_redfish_redirect_boundary.py` 1 · `tests/unit/test_sanitize_mirror.py` 1 (unit 19 + e2e 2 + regression 15).

### 1.1 쌍 실행 bisect — 단일 원인 확인 (`tier0/bisect_pairs.log`)

| 파일 | 단독 | `test_full_mirror_dryrun.py::test_v2_tree_is_consumed_by_replay_and_convert` 뒤에 |
|---|---|---|
| `tests/unit/test_redfish_audit_2026_10_10.py` | 15 passed | 3 failed |
| `tests/unit/test_redfish_bios_current.py` | 78 passed | 8 failed |
| `tests/unit/test_redfish_phase3_contracts.py` | 8 passed | 6 failed |
| `tests/unit/test_redfish_redirect_boundary.py` | 17 passed | 1 failed |
| `tests/unit/test_sanitize_mirror.py` | 19 passed | 1 failed |
| `tests/e2e/test_redfish_multi_credential_auth.py` | passed | 2 failed |
| `tests/regression/test_cross_channel_same_server.py` | passed | 11 failed |
| `tests/regression/test_redfish_coverage_audit.py` | passed | 4 failed |

8 파일 전부 단독 통과 · 오염원 1개와 짝지으면 재현(합 36 = 한 프로세스 실패 수) → **원인은 `replay_full_mirror.install_fakes` 가 `rg._get`/`_get_noauth` 를 복원 없이 교체한 것 하나**(04-test-001 / 06-bmc-008). 다른 원인은 섞여 있지 않다.

### 1.2 WP1(a) 뒤 — seam 복원 + conftest 가드 (`f3df7ac9`)

| 검사 | 결과 | 로그 |
|---|---|---|
| 쌍 실행 8쌍 재실행 | **8/8 PASS** (33 · 18+1 skipped · 7 · 16 · 79 · 9 · 18 · 20 passed) | `tier0/bisect_pairs_after_wp1a.log` |
| 가드 자기 시험 `tests/unit/test_seam_leak_guard.py` (pytester subprocess) | 2 passed — 모듈 경계 누출 1건을 teardown 오류로 보고하고 되돌림 · 모듈 안 패치/복원된 패치는 보고 안 함 | — |
| 다중 디렉터리 수집(루트 `tests/conftest.py` + e2e/integration/regression conftest 공존) | 61 passed (unit+e2e+integration+regression 4파일 한 프로세스) | — |
| `tests/unit` 전체 · 한 프로세스 `unit+e2e+regression` 재실행 | §1.3 | `tier0/pytest_unit_after_wp1a.log` · `tier0/pytest_unit_e2e_regression_after_wp1a.log` |

Tier 1/2 영향 0: 둘 다 `replay_full_mirror.run()` 을 쓰지 않는다(Tier 1 은 실제 playbook + HTTPS 서버, Tier 2 는 `emulator_harness.run_gather`). `mirror_policy.py` 가 import 하는 비공개 헬퍼(`_load_entries`·`_load_fsmap`·`_restore_pages`·`_read_json`·`_key_of`·`_err_of`·`_MANIFEST_STATUS_LISTS`)는 그대로다.

### 1.3 WP1 끝 전체 재실행 (WP1(a)~(f) 전부 반영, 제품 코드 변경 0)

| 실행 | 결과 | 로그 |
|---|---|---|
| `tests/unit` (분리) | **1 failed** · 4915 passed · 33 skipped — 실패 1 = `test_redfish_bios_current.py::test_real_recording_baseline_is_a_full_success`: WP1(d)(G-01) 로 `real_dell_r740` 녹화에 Bios 본문이 생겨 "replay 404 → None" 기대값이 더는 맞지 않음(코드 결함 아님). 기대값을 "Attributes 380개·Key 이름순" 으로 갱신한 뒤 파일 단독 + 종전 오염원 쌍 실행 79 passed. **seam 누출 실패 19 → 0** | `tier0/pytest_unit_after_wp1a.log` |
| 한 프로세스 `tests/unit tests/e2e tests/regression` | **1 failed** · 6009 passed · 45 skipped · 6 xfailed — 같은 1건. **seam 누출 실패 36 → 0** | `tier0/pytest_unit_e2e_regression_after_wp1a.log` |
| `tests/e2e tests/regression` (분리) · `tests/integration -m "not live"` | §1.4 | `tier0/pytest_e2e_regression_after_wp1.log` · `tier0/pytest_integration_notlive_after_wp1.log` |
| WSL 엔진 2파일 | 23 passed | `tier0/pytest_engine_wsl_after_wp1.log` |

두 전체 실행은 WP1(d) 커밋(`ad89563a`) 뒤 시작됐고 그 fixture 변경을 가정한 시험 1건만 걸렸다 — 갱신 커밋 뒤 전체 재실행은 WP2 끝(제품 코드 첫 변경)의 전수 실행이 겸한다(수치는 거기서 다시 센다).

### 1.4 WP1 끝 e2e/regression · integration (G-01 기대값 갱신 `16485033` 뒤)

| 실행 | 결과 | 로그 |
|---|---|---|
| `tests/e2e tests/regression` (분리) | 1094 passed · 12 skipped · 6 xfailed, rc 0 (수정 전과 같음) | `tier0/pytest_e2e_regression_after_wp1.log` |
| `tests/integration -m "not live"` | **496 passed** · 6 skipped · 1 deselected, rc 0 (366 → 496: 2차 fixture 11세트 자동 등록 + 개수 정합·mirror_replay zip 재생 시험) | `tier0/pytest_integration_notlive_after_wp1.log` |

## 2. Tier 1 기준선 (WP1(e)) — 편입판 도구, 제품 코드 변경 0

- 명령: `MSYS_NO_PATHCONV=1 python tests/redfish-probe/mirror_replay/run_tier1.py <18 label=/root/se_mirrors/...> --out-root tests/evidence/2026-10-27-redfish-mock2-impl/tier1-before --server-distro Ubuntu-24.04 --playbook-distro Ubuntu --loc yi --build-id mirror-replay-wp1e-before`
- 미러: 서버 배포판 `/root/se_mirrors/{csus3200_01..03, dl380_gen12_01..04, sr650_v4_01..04}` = `tests/reference/redfish/mock2/*.zip`(01-fixtures-origin.md 1절에서 추출본·zip 동일 확인) · 1차 7대 `/root/se_mirrors/mock1/{DELL_R740/01, HPE_CSUS3200/01..04, HPE_DL380/01, Lenovo_SR650/01}`(저장소 밖 `C:\github\서버mock데이터\1차` 의 사본).
- **1차 시도 실패(도구 아님)**: Git Bash 가 `label=/root/...` 의 경로를 `C:/Program Files/Git/root/...` 로 바꿔(MSYS 경로 변환) 서버가 빈 미러(keys 0)를 띄웠고 18/18 이 `PROTOCOL_CHECK_FAILED`(ServiceRoot 404)로 끝났다. `run_tier1.py` 에 절대 경로 검증과 keys 0 중단을 넣고(`5e7a3f47`) `MSYS_NO_PATHCONV=1` 로 재실행. 1차 시도 산출은 저장소에 두지 않았다.

| label | rc | status | vendor | adapter_id | adapter_first_pass | errors | 요청(총/distinct) |
|---|---|---|---|---|---|---|---|
| csus3200_01 | 0 | success | hpCsus | redfish_hpe_csus_3200 | null | 0 | 200/193 |
| csus3200_02 | 0 | success | hpCsus | redfish_hpe_csus_3200 | null | 0 | 148/141 |
| csus3200_03 | 0 | success | hpCsus | redfish_hpe_csus_3200 | null | 0 | 184/177 |
| dl380_gen12_01 | 0 | success | hp | redfish_hpe_ilo7 | null | 0 | 156/152 |
| dl380_gen12_02 | 0 | success | hp | redfish_hpe_ilo7 | null | 0 | 147/143 |
| dl380_gen12_03 | 0 | success | hp | redfish_hpe_ilo7 | null | 0 | 84/80 |
| dl380_gen12_04 | 0 | success | hp | redfish_hpe_ilo7 | null | 0 | 147/143 |
| sr650_v4_01 | 0 | success | lenovo | **redfish_lenovo_bmc** | redfish_lenovo_xcc3 | 0 | 112/108 |
| sr650_v4_02 | 0 | success | lenovo | **redfish_lenovo_bmc** | redfish_lenovo_xcc3 | 0 | 129/125 |
| sr650_v4_03 | 0 | success | lenovo | **redfish_lenovo_bmc** | redfish_lenovo_xcc3 | 0 | 163/159 |
| sr650_v4_04 | 0 | success | lenovo | **redfish_lenovo_bmc** | redfish_lenovo_xcc3 | 0 | 117/113 |
| r1_DELL_R740_01 | 0 | success | dell | redfish_dell_idrac9 | redfish_dell_idrac10 | 0 | 141/137 |
| r1_HPE_CSUS3200_01 | 0 | success | hpCsus | redfish_hpe_csus_3200 | null | 0 | 145/138 |
| r1_HPE_CSUS3200_02 | 0 | success | hpCsus | redfish_hpe_csus_3200 | null | 0 | 145/138 |
| r1_HPE_CSUS3200_03 | 0 | success | hpCsus | redfish_hpe_csus_3200 | null | 0 | 214/207 |
| r1_HPE_CSUS3200_04 | 0 | success | hpCsus | redfish_hpe_csus_3200 | null | 0 | 214/207 |
| r1_HPE_DL380_01 | 0 | success | hp | redfish_hpe_ilo7 | null | 0 | 135/131 |
| r1_Lenovo_SR650_01 | 0 | success | lenovo | **redfish_lenovo_bmc** | redfish_lenovo_xcc3 | 0 | 127/123 |

- 18/18 rc 0 · success · errors 0. Lenovo 5 label 의 `xcc3 → lenovo_bmc` 강등(01-adapter-001)과 Dell `idrac10 → idrac9` 재선택이 기준선에 그대로 있다(WP2 대상/정상).
- **분석 Round 기준선(`tests/evidence/2026-10-26-redfish-mock2-audit/baseline/tier1`)과 대조**(`diff_tier1.py`, 휘발 `meta.started_at/finished_at/duration_ms` 제외): **18 label 전부 봉투 차이 0 · 요청 집합 차이 0** (`tier1-before/_diff_vs_analysis_baseline.md`). 편입판이 운영 호출(`redfish-gather/inventory.sh` + `bmc_ip`)로 바뀌었어도 `ip`/`correlation.host_ip`(127.0.0.1)·`correlation.bmc_ip`(미러 안 BMC NIC 주소)·`diagnosis.details` 까지 같다. 이후 모든 expected diff 의 before 는 이 산출이다.
- label 당 43~48 s(분석 Round 25~28 s) — 같은 시각에 pytest 2개가 돌고 있었다. 시간은 계약이 아니다.
- 산출 중 저장소에 둔 것: `gather_output.json`(최종 봉투) · `requested_keys.json` · `server_access.jsonl`(경로·상태·인증 구분만) · `run_meta.json` · `server_ready.json` · `server_stdout.log` · `gather_manifest.json` · `gather_progress.jsonl` · `_run.log` · `_summary.json`. 두지 않은 것(`.gitignore`): `ansible_stdout/stderr.log`·`gather_checkpoint.jsonl`(봉투 중복) · `.inventory_input.json` · `.gather_limit_hosts` · `server.pid` · `gather_auth_evidence/`. 봉투 안 `password` 토큰은 BIOS 속성 이름(`SysPassword: null`, `PasswordRuleandPolicy_*`)뿐이다.

## 3. 디스크·FC 포트 개수 정합 (WP1(f)) — Tier 1 before 18 label

`tests/scripts/inventory_parity.py`(gather 와 독립된 판별기)로 전수 미러 노출 수 vs 최종 봉투 수집 수: **18/18 PASS, UNEXPLAINED 0** (`inventory-parity-before.md`). 노출 0 장비(csus3200_02 FC 0 · dl380_gen12_03 디스크/FC 0 · r1_HPE_CSUS3200_01/02 디스크 0 · sr650_v4_01/04·r1_Lenovo FC 0)의 수집도 0. XCC3 FC 포트(sr650_v4_02/03)는 NDF 0건이어도 Port 신호로 4건 노출 = hbas 4(`FC_IN_HOST_ETHERNET:4` 는 참고).
판별기 결함 1건을 여기서 고쳤다(`579a6827`): Dell 전수 미러는 같은 디스크를 `SimpleStorage.Devices[]` 와 `Storage/*/Drives` 에, 같은 포트를 `NetworkPorts/` 와 `Ports/` 에 두 번 노출해 8/8 로 세었다(수집 4/4 가 맞음). recording 기반 15세트 테스트는 변경 전후 모두 PASS.

## 4. Tier 2 기준선 (편입판 `tier2_replay.py`, 18 label)

- 명령: `tier2_replay.py tier2-before <CSUS 7 label=<mirror>> --layout rmc_primary --firmware-scope complex_only --tag adapter` + `<나머지 11 label> --tag plain` (Windows, 네트워크 0; 2차는 `mock2-audit-20261026/extract/<server>`, 1차는 `C:\github\서버mock데이터차\<VENDOR>\<nn>`).
- 18/18 `status=success`(`tier2-before/_summary.{adapter,plain}.json`, `<label>.<tag>.module.json`).
- **전수 미러 재생 ↔ 축약 fixture golden(GOLDEN_KEYS 9키) 1:1**: fixture 가 있는 15 label 전부 **차이 경로 0**(`tier2-before/_vs_golden.md`) — 2차 11세트 golden 과 WP1(d) 뒤 1차 3세트(bios 포함)가 전수 미러 재생과 같다. fixture 없는 r1_HPE_CSUS3200_02/03/04 는 success 만 확인.
- WSL 엔진 2파일 WP1 뒤 재실행: 23 passed (`tier0/pytest_engine_wsl_after_wp1.log`).
