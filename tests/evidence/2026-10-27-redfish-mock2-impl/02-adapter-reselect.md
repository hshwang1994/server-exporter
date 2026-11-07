# 02 — WP2: Lenovo XCC3 인증 후 재선택 강등 수정 (01-adapter-001 HIGH · 01-adapter-011) — opt-in `bmc_model_patterns`

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027` · 첫 제품 코드 변경(WP0~WP1 은 테스트 기반만).
- 결함(Tier 1 before, `00-baseline-recheck.md` §2): Lenovo SR650 V4 5 label(2차 4 + 1차 1) 이 1차 선택 `redfish_lenovo_xcc3`(priority) → 인증 후 재선택 `redfish_lenovo_bmc`(vendor 전용 fallback) 로 강등. `diagnosis.details.adapter_first_pass = redfish_lenovo_xcc3`.
- 원인: `lenovo_xcc3.yml` 의 `firmware_patterns: ["XCC\\s*3\\b"]` — 실 `Manager.FirmwareVersion`("IHX438R 2.97 20260910" ×4, "IHX414J 1.22 20250402") 에 없는 토큰. 공통 규칙 "알려진 값 불일치 = 실격" 이 정상 동작해 xcc3 가 떨어지고, `lenovo_xcc` 도 자체 firmware_patterns(XCC/^AFBT/^TAOT/^USX) 로 실격 → fallback 만 남음. adapter origin 주석의 "사이트 검증 PASS" 는 **1차 선택만** 검증한 것이었다(01-adapter-011).

## 1. 설계 — 검토한 대안과 선택 (사용자 2차 검토 2026-10-27 반영)

| 안 | 내용 | 판정 |
|---|---|---|
| B (분석 Round 제안) | 공통 규칙: 모델이 맞은 adapter 는 펌웨어 불일치로 실격시키지 않음 | **기각** — 모델·펌웨어 패턴 병존 9 adapter 전부에 걸리고, 광역 모델 패턴(lenovo_xcc `ThinkSystem.*`, huawei `RH.*` 등) lab 부재 벤더의 선택이 실측 없이 바뀐다 |
| C (데이터만) | `firmware_patterns` 에 `^IHX4` | 기각 — 펌웨어 문자열 2개에서 본 빌드 ID 접두 추정, 다음 빌드에서 재발 |
| **D (채택)** | 장비가 세대를 적는 값 `Manager.Model`("Lenovo XClarity Controller 3" / 1차 "Lenovo Xclarity Controller 3" / 1세대 참조 "Lenovo XClarity Controller")을 facts `bmc_model` 로 넘기고 adapter `match.bmc_model_patterns`(opt-in) 로 맞춘다 | 선언한 adapter 에서만 평가 → 미선언 adapter 의 코드 경로·점수 불변 |

- 의미(`model_patterns` 와 동일): facts 비어 있음 → 중립(보너스 제외), 일치 → +25(specificity +20), 알려진 값 불일치 → 실격(-9999). 점수식·동률·우선순위 체계 불변.
- 변경 파일: `module_utils/adapter_common.py`(`adapter_matches`·`adapter_specificity`·`adapter_match_score` 에 블록 1개씩 **추가**, 기존 블록 수정 0) · `redfish-gather/tasks/reselect_adapter.yml`(`_rf_postauth_facts.bmc_model` ← `data.bmc.model`) · `redfish-gather/tasks/detect_vendor.yml`(`_rf_probe_facts.bmc_model` — 무인증이면 '' → 중립, 1차 선택 불변) · `adapters/redfish/lenovo_xcc3.yml`(`firmware_patterns` 삭제 → `bmc_model_patterns: ["XClarity Controller 3\\b"]`, origin 주석에 이력) · `tests/redfish-probe/verify_adapter_selection.py`(`assemble_facts(root, bmc_model="")`) · `docs/develop/03-adapter-system.md` · `docs/ai/catalogs/VENDOR_ADAPTERS.md`. `lenovo_xcc.yml`·`lookup_plugins/adapter_loader.py` 는 손대지 않았다.
- 점수(SR650 V4 실 facts): xcc3 = 120×1000 + (vendor 10 + model 20 + bmc_model 20)×10 + (20 + 25 + 25) = **120570**; `lenovo_bmc` 10120; `lenovo_xcc` 실격(종전과 같음). 1세대 참조(V2, AFBT58B, "XClarity Controller")는 xcc3 가 model(V2)·bmc_model(숫자 없음) 둘 다로 실격 → `redfish_lenovo_xcc`(불변).

## 2. 회귀 — 미선언 adapter 영향 0 증명

- `02-adapter-scores-before.json` / `02-adapter-scores-after.json`: 31 adapter × facts 32묶음(18 label 실 facts + 1세대 참조 + 빈 facts 10 벤더 + 합성 3) = **992 셀 중 바뀐 셀 5** — 전부 `redfish_lenovo_xcc3` × Lenovo 5 label(match False → True, score None → 120570). 나머지 30 adapter × 32 facts 바이트 동일. specificity 는 xcc3 가 50 → 50(firmware 20 이 bmc_model 20 으로 자리바꿈)이라 우선순위 간격도 그대로다.
- 신규 `tests/unit/test_adapter_bmc_model_patterns.py`: 18 label 재선택 고정(Lenovo 5 → xcc3, 13 불변) · 점수 분해 · 1세대 음성 · system model 빈 값에서 bmc_model 만으로 실격 · 1차 빈 facts 불변 · 선언 adapter 3분기 · **미선언 adapter 가 bmc_model 유무에 무감(점수·match·legacy specificity 공식 동일)** · 선언 adapter 집합 = {xcc3} 고정 · Ansible facts 템플릿(reselect·detect_vendor) 렌더.
- 기존 선택 시험 전부 + 신규: `test_adapter_bmc_model_patterns` · `test_adapter_generation_tokens`(가공 "XCC3 1.20" → 실측 facts) · `test_adapter_selection_t01` · `test_redfish_adapter_reselect` · `test_adapter_scoring` · `test_adapter_common_robustness` · `test_csus_adapter_priority` · `test_supermicro_adapter_selection` · `test_adapter_selection_facts_r17` · `test_redfish_vendor_reselect_c5` · `test_adapter_huawei_firmware_regex` · `test_round15_fixes` · `tests/integration/test_redfish_hostname_policy_replay` → **258 passed**.
- `scripts/ai/verify_vendor_boundary.py` 통과 · `ansible-playbook --syntax-check` 3채널 OK(`tier0/syntax_check_wsl_after_wp2.log`) · `tests/e2e tests/regression` 1094 passed · `tests/integration -m "not live"` 496 passed(`tier0/*_after_wp2.log`) · `tests/unit` 전체 **4987 passed · 33 skipped · 0 failed**(`tier0/pytest_unit_after_wp2.log`, 22분 43초 — WP1 뒤 1 failed 였던 bios 기대값 갱신 포함).

## 3. Tier 1 after (18 label, `tier1-after-WP2/`, `diff_tier1.py` ↔ `tier1-before/`)

- 명령: WP1(e) 와 같은 18 label, `--build-id mirror-replay-wp2-after`. **18/18 rc 0 · success · errors 0**, 요청 집합 18 label 전부 불변(+0/-0).
- `_diff_vs_before.md`(허용목록 `_allow.json`): **허용목록 밖 차이 0**. 바뀐 경로는 Lenovo 5 label(sr650_v4_01..04 · r1_Lenovo_SR650_01)의 3개뿐 —
  `meta.adapter_id` redfish_lenovo_bmc → **redfish_lenovo_xcc3**, `diagnosis.details.adapter_candidate` 같은 변화, `diagnosis.details.adapter_first_pass`
  redfish_lenovo_xcc3 → null(1차·재선택이 같아져 기록하지 않음 — site.yml 규칙). 13 label(CSUS 7 · DL380 5 · Dell 1)은 봉투 바이트 동일.
- `data.*` 는 Lenovo 5 label 에서도 변화 0 — xcc3 와 lenovo_bmc 의 `capabilities.sections_supported` 가 같은 집합이라 수집·normalize 결과가 같다
  (adapter 가 바꾸는 것은 `meta.adapter_id` 와 선택 근거뿐; `vendor_notes` 는 둘 다 manager_layout 없음). compatibility-matrix(rule 28 #12)는
  capabilities 변경이 없어 해당 없음(pre-commit advisory 는 adapter 파일 변경만 보고 울린다).

## 4. 처분

| 이슈 | 처분 | 근거 |
|---|---|---|
| 01-adapter-001 (HIGH) | **FIXED** | 위 1~3절, 커밋 `6b3dae27`(feat) · `11d3c633`(test) · `6fe95536`(docs) |
| 01-adapter-011 | **DOC_CORRECTED** + FIXED | adapter origin 주석·VENDOR_ADAPTERS·03-adapter-system 에 "1차 선택만 검증 / 재선택은 bmc_model_patterns" 기록 |
| `lenovo_xcc.yml` 세대 토큰을 Manager.Model 로 옮기는 확장 | OBSERVATION_ONLY | XCC1/XCC2 실측 없음 — 바꾸지 않음 |
