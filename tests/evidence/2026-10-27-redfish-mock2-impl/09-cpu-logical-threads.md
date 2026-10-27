# 09 — WP9 (FIX 1): Redfish `cpu.logical_threads` 키 제거 (02-cpu-001 HIGH · 02-cpu-002 · 02-cpu-006)

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027`. **사용자 결정(지시서 2 FIX 1)**: Redfish 출력에서 `data.cpu.logical_threads` 키를 **완전히 제거**한다 — 이번 Round 의 유일한 명시적 스키마 예외(비-Additive). `sockets` · `cores_physical` 유지, HT 추정(코어×2) 금지, OS/ESXi 채널은 손대지 않는다. 플래그 `processor_summary_logical_count` 는 소비처가 없어 함께 삭제.
- 근거(2026-10-26 분석 · 2차 실측): HT 비활성 5대(BIOS `HThread`/`ProcHyperthreading` Disabled)에서 BMC 의 `ProcessorSummary.LogicalProcessorCount` · `Processor.TotalThreads` 가 코어의 2배(지원 수)로 나왔다(02-cpu-001). 같은 RMC 계보에서도 1.75.108 은 LogicalProcessorCount 가 코어 수, 1.77.30 은 스레드 수(02-cpu-002), CIMC 4.1 은 TotalThreads 가 코어 수(2026-10-18 X3) — 펌웨어 값만으로 HT 상태를 확정할 수 없다. `TotalEnabledCores` 는 18대 전부 `TotalCores` 와 같아 영향 0(02-cpu-006 — 관찰 유지).

## 1. 변경

| 층 | 변경 |
|---|---|
| normalize (`redfish-gather/tasks/normalize_standard.yml`) | cpu 블록 `logical_threads` 식(X3 · A-2 규칙) 삭제 → 키 자체가 없다. 주석에 정책 근거 |
| 모듈 (`redfish_gather.py::_normalize_cpu_raw`) | `logical_threads` 반환 삭제 → `multi_node.partitions[].cpu` 도 같은 정책. 모듈 raw `system.cpu_summary.logical_processor_count` 는 BMC 원값(GOLDEN_KEYS `data.system`)으로 유지 — 스레드 수가 아니라고 계약 §9 · EXTERNAL_CONTRACTS 에 명시 |
| adapter | `hpe_csus_3200.yml` · `hpe_superdome_flex.yml` 의 `processor_summary_logical_count: cores` 삭제(주석에 이력) · `cisco_cimc.yml` Q6 주석 정정 |
| 사전 | `cpu.logical_threads` 신규 등재 channel **[os, esxi]**(must) · `cpu.summary` help 정정 · `schema/fields/common.yml` → `os.yml`/`esxi.yml` 이동 |
| 계약 · 예시 | `03-fields.md` 6.2 메모(FIX 1 근거) · `schema/examples/redfish_success.json` 키 삭제(+`manufacturer`) · `schema/output_examples/redfish_{cisco_cimc,dell_idrac9,hpe_csus_3200(×4 — partitions 포함),hpe_ilo6,lenovo_xcc}.jsonc` 키 삭제(+top-level `manufacturer` 예시) · `docs/develop/05-field-mapping.md` · `docs/ai/contracts/serial-number.md` 키 목록 |
| baseline (rule 21 R1 명시 예외 = 사용자 FIX 1) | `schema/baseline_v1/{dell,hpe,lenovo,cisco}_baseline.json` `data.cpu.logical_threads` 라인 삭제(24 · 128 · 128 · 44), `hpe_csus_3200_baseline.json`(합성, FIX 5 교체 전) 4곳(448). 다른 값 불변 — `golden-changes.md` G-17 |
| golden | CSUS 4세트 `multi_node.partitions[0].cpu.logical_threads` 제거(64 · 128 · 224 · 128 → 없음) — G-16, 15 fixture 재생으로 그 1경로뿐임을 확인, 요청 예산 불변 |
| OS/ESXi | 변경 0 — `os-gather`/`esxi-gather` 코드 · baseline(`ubuntu` · `windows*` · `rhel810_raw` · `esxi`) 의 `logical_threads` 그대로(e2e/regression 1094 PASS) |

## 2. 테스트 재작성 (실측 12 FAIL + 18 ERROR 대상 전수)

| 파일 | 변경 |
|---|---|
| `tests/unit/test_cross_channel_value_fixes.py` | X3 2건 + 플래그 선언 테스트 → `test_redfish_cpu_fragment_has_no_logical_threads_and_keeps_sockets_cores`(키 부재 + sockets/cores 렌더 불변 + BUG-13 요약 폴백) · `test_no_adapter_declares_the_removed_cores_flag`(재도입 방지) |
| `tests/integration/test_redfish_csus_single_server_render.py` | `test_logical_threads_use_per_processor_sum_for_rmc` → `test_redfish_cpu_has_no_logical_threads_key`(top-level · partitions 키 부재, raw `logical_processor_count == 32` 보존, `cores_physical == 32`) |
| `tests/regression/test_cross_channel_same_server.py`(pair fixture 18 ERROR 원인) | 렌더 dict 에서 `logical_threads` · `has_lpc` 제거, `test_logical_threads_match_…` → `test_redfish_side_has_no_logical_threads`(OS/ESXi 쪽 값은 그대로) · 머리말 정정 |
| `tests/integration/test_redfish_normalize_robustness.py` · `tests/unit/test_hpe_csus_multi_node.py` | `out["logical_threads"]` 단언 → 키 부재 |
| `tests/unit/test_field_dictionary_channel_emit.py` | 사전 channel [os, esxi] · Redfish 블록 키 부재 · OS(Linux/Windows)·ESXi 블록 키 존재 · "redfish 선언 cpu 키 전부 발행" |

- 세 층 단언: 단위(normalize 식 렌더 · 모듈 `_normalize_cpu_raw`) · 계약(사전 channel · schema/fields) · 최종 봉투(Tier 1 18 label — 아래).

## 3. Tier 0

- 묶음 실행 281 passed(FIX 1/2 대상 13 파일) · `tests/integration -m "not live"` **497 passed** · `tests/e2e tests/regression` **1094 passed** · unit 전체 **5127 passed · 33 skipped · 0 failed**(23분 5초) · WSL `ansible-playbook --syntax-check` 3채널 PASS · 엔진 23 passed · `validate_field_dictionary.py` PASS · `output_schema_drift_check.py` 정합.

## 4. Tier 1 after (18 label, `tier1-after-WP9/` ↔ `tier1-after-WP7/`, `_allow.json` 4항목)

- 18/18 rc 0 · success · errors 0, 요청 집합 불변. `_diff_vs_after_wp7.md`: 허용목록 밖 차이 0.
- `data.cpu.logical_threads` **18 label 전부 키 소멸**(종전 값: CSUS 128/224/128 · DL380 Gen12 128 ×4 · SR650 V4 128 ×4 · 1차 Dell 96 · CSUS 64/64/128/128 · DL380 96 · SR650 64). CSUS 7 label 의 `multi_node.partitions[0].cpu.logical_threads` 도 소멸.
- 같은 봉투에서 `sockets` · `cores_physical` · `model` · `max_speed_mhz` · `turbo_max_mhz` · `architecture` 불변, `manufacturer` 추가(08 문서). `status` · `sections.cpu` 18 label `success` 그대로. INV-5 0 · 개수 정합 18 PASS(WP7 과 같음).

## 5. 처분

| 이슈 | 처분 |
|---|---|
| 02-cpu-001 (HIGH, 추정) | FIXED — 정책으로 제외(값을 고친 것이 아니라 키를 없앰; OS 실측 대조는 하지 않았다 — Portal 은 OS/ESXi 값을 쓴다) |
| 02-cpu-002 | DOC_CORRECTED (RMC 1.75 vs 1.77 의미 차이는 EXTERNAL_CONTRACTS 2026-10-27 행; 코드는 더 이상 그 값을 소비하지 않는다) |
| 02-cpu-006 | OBSERVATION_ONLY (`TotalEnabledCores` 18대 == `TotalCores` — 장착→활성 의미 변경은 FIX 1 범위 밖) |
| 02-cpu-005 | OBSERVATION_ONLY (partitions[].cpu 에 `turbo_max_mhz` 없음 — `multi_node` 는 그대로, 2026-10-19 사용자 결정 범위) |
