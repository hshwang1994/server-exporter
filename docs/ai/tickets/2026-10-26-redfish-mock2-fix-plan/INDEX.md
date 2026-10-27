# Handoff — Redfish 2차 Mock 11대 분석 결과 구현 계획 (Fable 5.1 / effort=max 구현 세션용)

> **2026-10-27 구현 완료 — 독립 검증 대기.** 이 티켓의 WP1~WP11 은 지시서 2 의 WP0~WP12 + FIX 5 로 구현됐다(브랜치 `fix/redfish-mock2-20261027`, 제품 코드 마지막 커밋 `b31d131d`). 결과·처분·핸드오프: `tests/evidence/2026-10-27-redfish-mock2-impl/{IMPLEMENTATION_SUMMARY,ISSUE_DISPOSITION,INDEPENDENT_REVIEW_HANDOFF}.md`. `main` 병합·`production` 승격은 독립 검증 PASS + 사용자 승인 뒤.
>
> 2026-10-26 분석 Round(`tests/evidence/2026-10-26-redfish-mock2-audit/`)의 결론을 **구현 세션**이 그대로 집어들 수 있게 적은 cold-start 티켓이다.
> 분석 단계에서는 제품 소스·ADR·기존 테스트·Mock 을 한 글자도 바꾸지 않았다. 여기 적힌 수정은 전부 **제안**이며, 구현은 사용자가 별도 지시서로 시작한다.
> 모델 정책(사용자 2026-10-26): 구현·회귀 검증·최종 독립 검증 모두 **Fable 5.1 / effort=max**. 종전 "Opus 5.5 구현 계획" 표현은 쓰지 않는다.
>
> **2026-10-27 사용자 지시서 2 정정(구현 세션, Fable 5.1 / max)** — 이 티켓의 제안 중 아래 항목은 사용자 FIX 1~11 과 2·3차 검토로 **대체**됐다. 구현 정본은 승인된 실행 Plan 과 `tests/evidence/2026-10-27-redfish-mock2-impl/` 이다. §1~§6 원문은 분석 시점 기록으로 보존한다(수정하지 않음).
>
> | 티켓 원문 | 정정(2026-10-27) |
> |---|---|
> | §2 "묶음마다 branch 1개(`fix/mock2-<묶음>`)" | 단일 통합 브랜치 `fix/redfish-mock2-20261027`(분석 브랜치 HEAD `b8985826` 분기), WP 직렬·WP별 코드/테스트/문서 커밋(FIX 11). `main` 병합·`production` 승격은 독립 검증 세션 뒤 별도 승인 |
> | §2 "답이 없는 항목(…)은 [HOLD]" · §3 4행 "사용자 결정 11건 [HOLD]" | 결정 1~10 = FIX 1~10 확정, 결정 11 = A안 확정 → HOLD 0건(03-storage-001 (b) controllers 보강만 HOLD) |
> | §3 3행 "HT Disabled 5대 OS/ESXi 실측 [HOLD]" · WP9 "ThreadingEnabled → BIOS HT → logical_threads 계산" | **폐기** — FIX 1: Redfish `data.cpu.logical_threads` 키를 최종 출력에서 제거(결과 스키마 유일 예외), HT 추정 로직 신설 금지, OS/ESXi 불변 |
> | §3 5·6행 golden 갱신·Tier 1 도구 편입 [HOLD] | FIX 8(HTTPS 재생 서버·Tier 1 도구·2차 11대 축약 fixture 를 `tests/` 편입) · FIX 9(검증된 golden 만 항목별 근거로 정정) |
> | WP2 "규칙 B — 모델 일치 adapter 는 펌웨어 불일치로 실격시키지 않음" | opt-in 매치 키 `bmc_model_patterns`(원천 `Manager.Model`)로 대체 — 선언하지 않은 adapter 의 점수 불변, 다른 제조사 선택 변화 0 을 회귀로 증명 |
> | WP4 "`uefi` 토큰·`Partition<N>_FW` → bios" | 구조 근거(`Bios/Manager.Links.ActiveSoftwareImage`, `RelatedItem→…/Bios`) 1순위, 근거 없는 CSUS 번들(`Partition0_FW`·`ComplexFW`)은 `other` 유지, enum 확장 없음(FIX 7), 전 category 긍정·부정 테스트 |
> | WP7 03-storage-004 "결정 11 매핑 정책대로" | A안: 값 불변(Port `LinkStatus` 있으면 사용, 없으면 `down`), 카드 조건(`LinkUp/LinkDown`+Timestamp)은 3중 판별(FC HBA 장치·NetworkAdapter→PCIeDevice 링크·adapter 선언 등록부) 통과 시 기존 notice 참고 기록만, 요청/필드 추가 0, `LogService/Oem/Iel` 미사용 |
> | WP8 "`cpu.manufacturer` 구현 vs 사전 정정(결정 2)" | FIX 2: 구현(`Processor.Manufacturer` → Intel/AMD 정규화) |
> | WP7 "composition 0 → null(결정 6)" · "baseline 교체(결정 5)" · "DIMM 속도(결정 3)" | FIX 6 null · FIX 5 2차 csus3200_01 실측 envelope 로 교체 · FIX 3 `OperatingSpeedMhz` 원값 유지(계약 문서) |
> | WP11 "`data.users`(결정 10)" · §3 "sections.system(결정 4)" | FIX 10 `data.users` 불변 · FIX 4 `sections.system = not_supported` 유지 + hostname/fqdn 각주 |
> | §5 "최종 독립 검증 = 구현에 관여하지 않은 세션" | 유지 — 구현 세션은 push 뒤 멈추고 새 Fable 세션이 Tier 0/1/2 를 직접 재실행 |

---

## 1. 컨텍스트 (분석 세션 종료 시점)

- **분석 통합 브랜치**: `docs/redfish-mock2-audit-20261026` (main `e8b5ae9b` 위에 분석 산출물만 쌓음 — 제품 코드 diff 0). Mock 아카이브는 main `7c22ca4a`(`tests/reference/redfish/mock2/`).
- **근거 자료**: 11대 자원 인벤토리(`…/inventory/`), 수정 전 기준선 Tier 0/1/2(`…/baseline/`), 영역별 보고서 6개(`…/analysis/01~06`), 132칸 판정표(`…/coverage/`), 통합 이슈(`…/ISSUES.md`), 요약(`…/SUMMARY.md`).
- **검증 기준**: Mock 실측이 근거, 코드·테스트·ADR 은 교차 검증 대상. **JSON 결과 스키마(키·타입·계층)는 바꾸지 않는다.** 서버별 하드코딩 금지. 벤더 분기는 응답 차이가 실측으로 입증된 곳만(adapter YAML 또는 라이브러리 OEM 추출 분기).
- **수정 전 기준선**(바뀌면 안 되는 것·바뀌어야 하는 것의 기준): Tier 1 = 실제 `ansible-playbook` 경로 18대 envelope(`baseline/tier1/<label>/gather_output.json`), Tier 2 = 모듈 재생 18대, Tier 0 = `tests/e2e tests/regression` 1094 passed / `tests/integration -m "not live"` 366 passed / WSL 엔진 23 passed / `tests/unit` 전체 19 failed(순서 의존, 04-test-001).

---

## 2. 다음 첫 지시 (cold-start prompt)

```
Redfish 2차 Mock 분석 결과 구현 cycle 진입 — Fable 5.1 / effort=max.

먼저 읽을 것 (순서대로):
1. tests/evidence/2026-10-26-redfish-mock2-audit/SUMMARY.md
2. tests/evidence/2026-10-26-redfish-mock2-audit/ISSUES.md  (클러스터 C1~C11, 우선순위, 사용자 결정 항목 §7)
3. tests/evidence/2026-10-26-redfish-mock2-audit/baseline/README.md  (기준선과 재생 한계)
4. docs/ai/tickets/2026-10-26-redfish-mock2-fix-plan/INDEX.md  (이 티켓의 §4 작업 묶음 순서·완료 조건)
5. 각 작업 묶음에 해당하는 analysis/0N-*.md 의 §4 이슈 본문(파일:라인·수정 제안·회귀 테스트 제안)

진입 조건:
- 사용자 결정 항목(ISSUES.md §7)의 답을 받은 것만 구현한다. 답이 없는 항목(C3 HT 규칙, cpu.manufacturer, DIMM 속도 보정, baseline 교체, enum 확장, users, CSUS HBA 카드 조건 매핑 — 결정 11)은 건너뛰고 티켓에 [HOLD] 로 남긴다.
- 작업 묶음 순서는 §4. 묶음마다 branch 1개(`fix/mock2-<묶음>`), 커밋은 rule 90, 코드와 문서는 별도 커밋.
- 모든 변경은 Additive(rule 92 R2): 기존 path 유지, envelope 13 필드·data.<section>.<field> 모양 변경 0, `scripts/ai/hooks/envelope_change_check.py` 통과.
- 묶음마다 §5 의 3단 검증(구현 → 회귀 → 최종 독립 검증)을 마친 뒤 다음 묶음으로.

재생·회귀 도구:
- Tier 2(모듈): SE_REPO_ROOT=<repo> python tests/evidence/2026-10-26-redfish-mock2-audit/tools/tier2_replay.py <out> <label>=<mirror_dir> ... [--layout rmc_primary --firmware-scope complex_only] --tag <tag>
- Tier 1(실제 playbook): tools/gen_cert.sh → tools/extract_mirrors.sh → MSYS_NO_PATHCONV=1 python tools/run_tier1.py <label>=/root/se_mirrors/<server> ... --loc yi  (WSL root 배포판 + WSL Ubuntu ansible-core 2.20.7; 자세한 절차 baseline/README.md)
- 미러는 tests/reference/redfish/mock2/*.zip (11대) + 외부 C:\github\서버mock데이터\1차 (7대, 읽기 전용).
```

---

## 3. 의존성 / 전제 조건

| # | 조건 | 상태 |
|---|---|---|
| 1 | 2차 Mock 11대 zip 이 main 에 있음 | [OK] `7c22ca4a` |
| 2 | 수정 전 기준선(Tier 0/1/2) 기록 | [OK] 분석 브랜치 `baseline/` |
| 3 | HT Disabled 5대의 OS/ESXi 논리 CPU 실측 (C3 확정용) | [HOLD] 사용자/현장 몫 — 없으면 C3 는 '추정' 상태로 보류 |
| 4 | 사용자 결정 11건(ISSUES.md §7) | [HOLD] |
| 5 | golden 갱신 승인(rule 21 R3: `real_hpe_dl380` temps, `real_lenovo_sr650` -Pending, 1차 bios None) | [HOLD] — 묶음 WP1 에서 요청 |
| 6 | Tier 1 재생 서버·2차 축약 fixture 의 저장소 편입 여부 | [HOLD] — WP1 전제 |
| 7 | 실장비 접속 | 불필요(전 묶음 오프라인 검증). 단 C2 전원 Off 인과·C3 기대값은 실장비/OS 실측이 있어야 '확정' |

---

## 4. 작업 묶음 (순서 = 우선순위; 공통 로직 → 기능별)

각 묶음: **범위 / 파일·함수 / 변경 예상 규모 / JSON 계약 영향 / 모델별 예외 근거 / 회귀 기대값 / 완료 조건**. 이슈 ID 는 ISSUES.md.

### WP1. 테스트·재생 기반 정비 (C7 — 다른 묶음의 회귀가 의존)
- 범위: (a) `04-test-001` — `tests/redfish-probe/replay_full_mirror.py::install_fakes`/`run()` 을 `_get_impl`/`_get_noauth` seam + 복원(`finally` 또는 컨텍스트 매니저)으로 바꿔 순서 의존 제거. (b) 2차 11대 축약 recording fixture 생성(`tests/integration/capture_mirror_fixture.py <mock2 추출>/<server> <name> [--layout rmc_primary --firmware-scope complex_only]`) — 이름은 `real_*` 로 두어 golden/budget/invariant 테스트에 자동 등록(의도), `meta.json`·README·`request_budget.json`·`tests/evidence/<날짜>-<vendor>-<펌웨어>.md` 출처 기록(rule 21 R2). golden 은 **수정 전** 값으로 먼저 고정(기준선 역할), 뒤 묶음에서 의도된 차이만 갱신. (c) 사용자 결정 6 에 따라 `tools/mirror_https_server.py`·`run_tier1.py` 를 `tests/` 로 편입(또는 scratch 유지).
- 파일: `tests/redfish-probe/replay_full_mirror.py`, `tests/unit/test_full_mirror_dryrun.py`(필요 시 fixture 감싸기), `tests/fixtures/redfish/real_<11>/`, `tests/evidence/`. 제품 코드 변경 0.
- 규모: 테스트 도구 1파일 + fixture 11세트(≈3~5 MB).
- 계약 영향: 없음.
- 회귀 기대값: `pytest tests/unit` 전체 **0 failed**(현재 19); 쌍 실행(`test_full_mirror_dryrun.py` → `test_redfish_bios_current.py`) 통과; 신규 11 golden 이 Tier 2 adapter/plain 모드 출력과 1:1(`_golden_compare` 차이 0); `test_request_budget.py` 가 11대 요청 수(Tier 1 `requested_keys.json` distinct 수 ±0)를 고정.
- 완료 조건: 위 기대값 + `tests/e2e tests/regression` 1094 불변 + `tests/integration -m "not live"` 366+신규.

### WP2. adapter 선택·재선택 규칙 (C1, HIGH)
- 범위: `01-adapter-001` 규칙 B — `module_utils/adapter_common.py::adapter_matches`(:183-189)·`adapter_match_score`(:291-300): model_patterns 가 있고 model fact 가 일치한 adapter 는 firmware 불일치를 실격(-9999)이 아니라 firmware 보너스(+25) 미획득으로만 처리. `adapters/redfish/lenovo_xcc3.yml` firmware_patterns 에 실측 형식(`^IHX4`, `XCC\s*3`) 추가 + origin 주석(rule 96 R1: 2차 미러 `Managers/1.FirmwareVersion`). (검토) `redfish-gather/tasks/reselect_adapter.yml` facts 에 `data.bmc.model` 보조 신호 — 코드가 읽는 키가 늘어나므로 adapter_common 변경과 함께 설계.
- 파일: `module_utils/adapter_common.py`, `adapters/redfish/lenovo_xcc3.yml`, (`reselect_adapter.yml`), `tests/unit/test_adapter_generation_tokens.py`(가공 "XCC3 1.20" → 실측 문자열), 신규 `tests/unit/test_adapter_reselect_real_facts.py`(18 label 실제 인증 후 facts 매트릭스), `docs/ai/catalogs/VENDOR_ADAPTERS.md:72,212`, `docs/develop/03-adapter-system.md` 점수 설명.
- 규모: 함수 2곳 ±20줄, adapter 1, 테스트 2, 문서 2.
- 계약 영향: 없음(`meta.adapter_id` 값만 바뀜 — Lenovo 5건 `redfish_lenovo_bmc` → `redfish_lenovo_xcc3`).
- 모델별 예외 근거: 없음(공통 규칙). Dell R740 재선택 결과 `redfish_dell_idrac9` 불변이어야 함(01 보고서 시뮬레이션: Lenovo 5건 외 전부 불변).
- 회귀 기대값: Tier 1 18 label 중 `meta.adapter_id` 변경은 sr650_v4_01..04·r1_Lenovo_SR650_01 의 5건만(`redfish_lenovo_xcc3`), `diagnosis.details.adapter_first_pass` 는 그 5건에서 null(1차=최종); 기존 단위 매트릭스 22건 불변; `tests/integration/test_redfish_hostname_policy_replay.py` 통과; `python scripts/ai/verify_vendor_boundary.py` exit 0.
- 완료 조건: 위 + CLAUDE.md §5 "선택 로직 변경 시 기존 선택 결과 전체 Regression" 기록(`tests/evidence/<날짜>-adapter-reselect.md`).

### WP3. 전원 Off 호스트 공통 처리 (C2, MED ×4)
- 범위: `redfish_gather.py` — `gather_system` 이 읽은 `System.PowerState`(캐시, 추가 요청 0)를 섹션들이 참조: (a) Off 면 `_notice(...)` 공통 한 문장(섹션 'system' 또는 각 섹션 1회 — 중복 금지), (b) `gather_memory`(:3085) 빈 슬롯 판정에 "`Status` 키 없음 + `CapacityMiB` 0/None + Manufacturer·PartNumber·SerialNumber 모두 비어 있음 → 제외 + notice 건수" 추가(`02-memory-001`), (c) PSU `State == Absent` 의 `power_capacity_w 0` → null, `firmware_version "0.00"`/"" → null(`05-power-001`, A-3 확장), (d) 센서 `Status.State != Enabled` 면 `reading_celsius`/`reading` null, 상태값 유지(`05-thermal-002`), (e) `gather_storage` Storage 멤버 0 + PowerState Off → notice(`03-storage-001`; 선택: PCIeFunctions `DeviceClass MassStorageController` 로 controllers[] 보강은 사용자 결정 후).
- 파일: `redfish-gather/library/redfish_gather.py`(`gather_memory`, `gather_power`/`_gather_power_subsystem`, `gather_thermal`/`_gather_thermal_subsystem`, `gather_storage`, `gather_network_adapters_chassis`), 계약 `docs/contract/03-fields.md` 6.2/6.3/6.5/6.7 문장, `tests/unit/test_redfish_phase2_contracts.py`(C5 옆 2건), 신규 전원 Off 테스트.
- 규모: 함수 5곳 각 ±10~20줄, notice 1종.
- 계약 영향: 없음(값이 0/"0.00" → null 로, slots 길이 변화, notice 추가 — 모두 기존 키).
- 모델별 예외 근거: 없음(구조 신호만). HPE `Oem.Hpe.DIMMStatus "NotPresent"` 를 보조 신호로 쓸 수 있으나 `"Other"` 는 쓰지 않는다(02 보고서).
- 회귀 기대값: dl380_gen12_03 — `memory.slots` 32→16, PSU 2건 `power_capacity_w null`·`firmware_version null`, temps 42건·fans 6건 reading null(state 유지), notice ≥1, `status success`·`sections` 불변; 전원 On 17 label — 변화 0(바이트 동일).
- 완료 조건: 위 + golden(신규 2차 fixture) 갱신 diff 가 정확히 dl380_gen12_03 범위.

### WP4. `firmware[].category` 규칙 (C9, MED ×3)
- 범위: `normalize_standard.yml` `_rf_firmware_categorized` Jinja 토큰 사슬 재설계(04 보고서 §4 제안): `diagnostic` → `disk`(drive) → `backplane` → `video|graphics`(other) → `raid|mr\d{3}i`?(storage_controller — HPE MegaRAID 이름 패턴은 **같은 장비 `storage.controllers[].controller_model` 과 이름 일치** 교차 신호로 대체) → `uefi|bios|system rom`(bios) → `programmable logic|fpga|cpld`(cpld) → … 기존 순서. 구조 신호 1순위: `Systems/<id>/Bios.Links.ActiveSoftwareImage`·`RelatedItem→…/Bios` ⇒ bios, `Managers/<id>.Links.ActiveSoftwareImage` ⇒ bmc(모듈이 `gather_firmware` 에서 링크 id 를 내부 키로 전달해야 하면 모듈 변경 포함).
- 파일: `redfish-gather/tasks/normalize_standard.yml`, (`redfish_gather.py::gather_firmware` 링크 id 보존), `tests/unit/test_firmware_category.py`(4벤더 실측 이름 매트릭스), `schema/field_dictionary.yml` category help, `docs/ai/catalogs/EXTERNAL_CONTRACTS.md:15`.
- 규모: Jinja 블록 1 + 테스트 매트릭스 ≈30 케이스.
- 계약 영향: 없음(enum 값 내 재분류; enum 확장 `hba` 는 사용자 결정 7 전까지 하지 않음 — FC HBA 는 벤더 무관 `other` 로 통일).
- 모델별 예외 근거: 없음.
- 회귀 기대값: Lenovo `UEFI`→bios, `Drive_Backplane…PSoC`→backplane, `HPM-FPGA`→cpld; HPE `MR416i-o`→storage_controller, `Embedded Video Controller`→other, `Programmable Logic Device`→cpld; CSUS `Partition0_FW`→bios; Dell 기존 케이스(`Disk 0 in Backplane…`→drive, `uEFI Diagnostics`→diagnostic, QLE2692→통일값) 테스트로 고정. 다른 필드 바이트 불변.
- 완료 조건: 위 + 18 label Tier 1 category 분포 표를 evidence 로.

### WP5. Lenovo XCC3 응답 모양 (C4, MED ×2 + LOW)
- 범위: (a) `03-network-001` — `gather_network`/`normalize_standard.yml interfaces`: 주소가 `ports[]` 의 FC/IB 포트 주소와 같거나 16-hex(8옥텟)인 항목을 `interfaces[]` 에서 제외 + notice; `tests/integration/test_port_classification_invariants.py` 에 INV-5(interfaces 주소 ∉ FC/IB 포트 주소) 추가. (b) `04-firmware-006` — `gather_firmware`: `Status.State == Disabled` 이고 `Version` 빈 항목(보류 이미지 없음)은 제외 + notice 1건; `Version` 있으면 종전 `pending: true`. (c) LOW: `05-power-003` PSU model `strip()`; `03-network-003` 호스트 NIC 속도는 `ports[]` join 값 우선(1024 배수 휴리스틱 단독 금지); `03-network-005` `ToManager` 는 `interfaces[].kind` 기존 값으로 구분 가능하면 유지, `summary.port_count` 에서 제외 여부는 계약 확인; `02-memory-003` locator `ServiceLabel` 우선; `01-hardware-005` Lenovo `hardware.oem` 매핑은 원천 있는 키만.
- 파일: `redfish_gather.py`(`gather_network`, `gather_firmware`, `_extract_oem_lenovo`, PSU 파서), `normalize_standard.yml`, `tests/unit/test_network_adapters_*.py`, `test_fc_*.py`, 신규 sr650_v4_02/03 fixture 케이스.
- 규모: 함수 4곳 ±10~15줄.
- 계약 영향: 없음(항목 수·값 정리). golden `real_lenovo_sr650` 의 -Pending 2건 제거는 **사용자 승인(결정 9)** 후.
- 모델별 예외 근거: 없음 — 전부 구조·형식 신호(벤더 이름 분기 금지). `03-network-003` 만 "Lenovo 펌웨어가 1024 배수" 라는 실측이 있으나 수정은 join 우선 규칙으로 벤더 무관하게.
- 회귀 기대값: sr650_v4_02 interfaces 9→5, sr650_v4_03 15→11, `summary.port_count` 동일하게, groups 에 `fibrechannel` 0; Lenovo 5 label firmware 항목 -4/-2(빈 Pending), `pending:true` 0건; 나머지 13 label 변화 0.
- 완료 조건: 위 + INV-5 전 fixture/baseline 통과.

### WP6. 전원·온도 값 의미 (C10, MED ×2)
- 범위: `05-thermal-001` — legacy Thermal/ThermalSubsystem 공통으로 `Status.State == Absent` 센서·팬 제외(+notice 건수); `05-power-002` — PSU 입력 0 W(`LineInputVoltage 0`/`PowerInputWatts 0`/`Metrics.InputPowerWatts 0`, 키가 있을 때만) notice "AC 입력 없음 — health Critical 은 입력 손실"(벤더 분기 없음) + 계약 문장; `power_capacity_watts`·소비전력 폴백 정의는 문서(C6).
- 파일: `redfish_gather.py`(`gather_thermal`, `_gather_thermal_subsystem`, `gather_power`, `_gather_power_subsystem`), `docs/contract/03-fields.md` 6.5/6.7, `tests/unit/test_power_summary_b58_b59.py`(원인 notice 단언 추가), 신규 fixture 케이스.
- 규모: 함수 4곳 ±10줄.
- 계약 영향: 없음(항목 제외·notice). golden `real_hpe_dl380` temps 52→43 은 사용자 승인(결정 9) 후.
- 회귀 기대값: dl380_gen12_01/02/04 temps 56/44/54 → 49/36/46(Absent 7/8/8 제외), 1차 DL380 52→43; XCC3/iDRAC9/CSUS temps 불변; PSU notice: dl380_gen12_01/02/04 PSU#2·sr650_v4_01..04 PSU1 각 1건, 1차 7대 0건.
- 완료 조건: 위 + ESXi 채널 의미("목록에 있음 = 장착·측정") 와의 정합을 계약 문장으로.

### WP7. CSUS 3200 / RMC 섀시 순회·composition (C5 중 코드 부분)
- 범위: `01-multi_node-006` ≡ `05-power-004` — `_collect_multi_node_topology`/`gather_chassis_multi`·`_gather_power_for_system`·`_gather_thermal_for_system` 의 섀시 Power/Thermal 요청을 Chassis 본문의 navigation property 유무로 gating(링크 없으면 요청 0, notice 유지) — 404 재요청(캐시 미적중) 3경로 2회 해소; `01-multi_node-007` composition `processor_count/memory_count` 원천 배열 없으면 null(사용자 결정 6); `02-cpu-005` partition cpu 모양은 결정 후; `03-storage-004`(2026-10-27 추가, `analysis/07-main-addendum-csus-hba-link.md`) — adapter `hpe_csus_3200.yml` vendor_notes 에 카드 조건 등록부 접두(`H3Alert`) 선언 → 카드 루프(`redfish_gather.py:4454-4830`, `Controllers[0].Links.PCIeDevices[]` 응답 재사용 — 추가 요청 0)에서 `PCIeDevices.Status.Conditions[].MessageId` `<prefix>.LinkUp/LinkDown`(+Timestamp) 추출 → Port `LinkStatus` 없을 때 `_hba_link_status` 폴백은 **사용자 결정 11** 의 (a)/(b) 대로, notice 에 카드 조건·시각 기록. 공통 코드에 vendor 이름 분기 금지(플래그 값으로만).
- 파일: `redfish_gather.py`(:6337 이하 multi-node, :6472/:6516 power/thermal per system; 03-storage-004 는 :4454-4830 카드 루프·`_hba_link_status` :4114 호출부), `adapters/redfish/hpe_csus_3200.yml`(03-storage-004 플래그), `tests/unit/test_hpe_csus_multi_node.py`, `test_csus_*`, 2차 CSUS fixture 케이스.
- 규모: 함수 3곳 ±15줄.
- 계약 영향: 없음. DL380/SR650 은 legacy 경로 링크가 실재해 요청 집합 변화 0 이어야 함.
- 모델별 예외 근거: 없음(링크 존재 여부라는 구조 신호).
- 회귀 기대값: csus3200_01..03·1차 CSUS 4대 Tier 1 요청 수 -11(distinct)·-14(총), `multi_node`·`power`·`thermal` 값 불변; DL380/SR650 요청 집합 바이트 동일. 03-storage-004: csus3200_01/03·1차 CSUS 4대 recording 에서 카드 조건 LinkUp 추출 고정(LinkDown·조건 없음은 합성 변형 — 실측 대체 아님 명시), 값 변화는 결정 11 에 따름, DL380/SR650/Dell golden 바이트 동일.
- 완료 조건: 위 + ADR-2026-06-09 가정 정정 기록(ADR 원문 수정 여부는 사용자 결정).

### WP8. 계약·사전·문서 drift 묶음 (C6 + 각 보고서 §6, 스키마 변경 없음)
- 범위: `01-hardware-002`(문서 정정 + `Status.Health` null 시 `HealthRollup` 폴백 Additive), `02-cpu-003`(결정 2 에 따라 구현 또는 사전 정정), `02-cpu-007`·`05-power-006`·`03-storage-002`·`03-storage-003`(사전 등재/channel 정정), `01-correlation-010`(`correlation.bmc_ip` 정의), `05-power-005`·`05-power-007`(정의 문장), `04-firmware-012`(`data.firmware` 절 신설·category help), `05-thermal-005`, `01-system-009`, `04-firmware-011`, `sections.yml network.empty_value` OS 전용 키 각주. ADR 정정은 ISSUES.md §5 표 — ADR 원문 수정은 사용자 결정(결정 없으면 `docs/reference/decision-log.md` 에 정정 기록만).
- 파일: `docs/contract/03-fields.md`, `schema/field_dictionary.yml`(값·help·channel 만 — `pre_commit_docs20_sync_check` 때문에 `03-fields.md` 와 같은 커밋), `docs/ai/catalogs/EXTERNAL_CONTRACTS.md`, `docs/ai/catalogs/VENDOR_ADAPTERS.md`, `redfish_gather.py:2626`(폴백 1줄), `normalize_standard.yml`(cpu.manufacturer 결정 시).
- 규모: 문서 다수, 코드 ≤2곳.
- 계약 영향: 사전 항목 추가·help 정정은 "계약 서술 정확화" 로 분류(필드 추가 아님). `pre_commit_additive_only_check.py` 가 `field_dictionary.yml` 삭제 라인을 막으므로 항목 삭제 대신 channel 수정.
- 회귀 기대값: `python tests/validate_field_dictionary.py`·`scripts/ai/hooks/output_schema_drift_check.py` 통과, `tests/unit/test_field_dictionary_channel_emit.py` 확장 통과.
- 완료 조건: 위 + `docs/ai/catalogs/CONVENTION_DRIFT.md` 에 DRIFT 번호 등재.

### WP9. CPU 논리 스레드 HT 규칙 (C3, HIGH — **사용자 결정 1 이후**)
- 범위: `02-cpu-001`/`002` — `cpu_summary`(:2643-2654)에 `ProcessorSummary.ThreadingEnabled` 수집, `normalize_standard.yml` cpu 블록(:615-628)과 `_normalize_cpu_raw`(:5910-5949)에 (1) `ThreadingEnabled` → (2) adapter `vendor_notes.bios_hyperthreading_attribute` 가 가리키는 BIOS 속성 값(`Disabled`) → `logical_threads = cores_physical` → (3) 종전. `processor_summary_logical_count` 플래그 의미 재정의/제거, `hpe_superdome_flex.yml` 복제 플래그 실측 0 표기.
- 파일: `redfish_gather.py`, `normalize_standard.yml`, `adapters/redfish/{hpe_ilo7,hpe_csus_3200,lenovo_xcc3,dell_idrac9}.yml`(속성 키 이름 — 값으로 가르고 벤더 이름으로 가르지 않음), `tests/unit/test_cross_channel_value_fixes.py`(3분기), `tests/integration/test_redfish_csus_single_server_render.py`(csus3200_02 224→112), ADR 정정 기록.
- 계약 영향: 없음(값만).
- 회귀 기대값: HT Disabled 5대 `logical_threads` = cores(csus3200_02 112, dl380_gen12_03 64, sr650_v4_01/02/04 64), Enabled 13 label 불변, Dell `ThreadingEnabled true` 불변; 사용자 OS 실측과 일치해야 완료.
- 완료 조건: OS/ESXi 실측 대조 통과 + ADR-2026-10-18/19 정정 반영.

### WP10. 기존 필드 보강 (C8, LOW — 마지막)
- 범위: `03-network-002`(ports join 으로 link/speed 보완), `03-network-007`(mtu ← NDF MTUSize), `03-network-004`(0/null 통일), `03-network-006`(IPv6 — 표본 없음, 합성 테스트), `03-storage-003`(wwn ← NAA, 사전 channel), `01-hardware-004`≡`04-bios-001`(Lenovo bios_date ← UEFI ReleaseDate, HPE 자리표시자 필터), `02-memory-004`(rank_count ← Label), 02 §5 L2/L3 캐시.
- 계약 영향: 없음(기존 키 채움). 요청 추가 0(이미 받는 응답) 또는 최소.
- 회귀 기대값: 각 항목의 before/after 를 2차 fixture 로 고정; `test_request_budget.py` 요청 수 변화는 명시적으로 갱신.

### WP11. bmc · diagnosis (C11, MED 1 + LOW)
- 범위: `06-bmc-001` — `resolve_account_family`(`redfish_gather.py` :7521-7640) Lenovo 분기가 세대를 adapter 이름 hint(`'xcc3' in hint`)로만 가르는 것을 **장비 값 우선**(`Manager.Model` "XClarity Controller 3"/`ManagerType`)으로(Dell 분기와 같은 패턴; 기존 OEM 분기 안에서, 벤더 이름 신규 분기 금지). `06-bmc-010` — 성공 경로의 `auth_success: true` 를 실제 자격 인증 때만(익명 수집 성공은 null — CLAUDE.md §9). `06-bmc-005` — `gather_bmc` NIC 선택은 대상 IP 와 일치하는 NIC 우선, 없으면 종전(컬렉션 순서). `06-bmc-006` — `bmc.name` 은 장비 값(`ManagerType`/`Id`) 폴백. `06-bmc-003` — iLO 7 `bmc.timezone` ← `Managers/1/DateTime.TimeZone`(+1 GET, Additive). `06-bmc-002` — RMC `@Redfish.WriteableProperties` 를 계정 쓰기 계약에 반영(vendor-agnostic; `test_account_hpe_rmc_enabled.py` fixture 전제 갱신). 문서 `06-bmc-004/007/009` 는 WP8 묶음.
- 주의(06 교차 이슈 1): 복구가 받는 hint 는 **1차 선택 adapter** 라 WP2(재선택 규칙)는 Family 판정에 영향이 없다 — WP11 은 WP2 와 독립.
- 파일: `redfish-gather/library/redfish_gather.py`(`resolve_account_family`, `gather_bmc`, `_compute_final_status`/diagnosis 조립), `redfish-gather/tasks/normalize_standard.yml`(bmc.name), `tests/unit/test_account_family_and_write_contract.py`, `test_account_hpe_rmc_enabled.py`, 신규 Lenovo XCC3 합성 401 경로 테스트.
- 규모: 함수 4곳 ±10~20줄.
- 계약 영향: 없음(`auth_success` 의미 정확화는 CLAUDE.md §9 와 일치; `data.users` 는 변경하지 않음 — 결정 10).
- 모델별 예외 근거: 없음(장비 값 우선).
- 회귀 기대값: Lenovo 5 label 합성 401 경로에서 Family = XCC3; 11대 Tier 1 `bmc.*` 바이트 불변(ip 선택 규칙 변경 후 11/11 동일), iLO 7 4대 `bmc.timezone` 값 고정(`Asia/Seoul` 류 raw 값), `diagnosis.auth_success` 는 18 label 그대로 true(표준 계정 인증 경로).
- 완료 조건: 위 + 재생 한계(401 미재현) 명시 — 실장비 복구 경로는 "검증 불가" 로 남긴다.

---

## 5. 검증 3단 (모두 Fable 5.1 / max)

| 단 | 누가 | 무엇 | 통과 기준 |
|---|---|---|---|
| 구현 검증 | 구현 세션 | 묶음별 단위/통합 테스트 + Tier 2 18 label 재생 | 묶음의 회귀 기대값(§4) 정확히 일치, 그 밖 label 바이트 동일 |
| 회귀 검증 | 별도 세션(같은 브랜치 체크아웃) | `pytest tests/e2e tests/regression`(1094+), `tests/integration -m "not live"`(366+신규), `tests/unit`(0 failed — WP1 뒤), WSL 엔진 23, `scripts/ai/ci_gate.sh`, `ansible-playbook --syntax-check` 3채널, `verify_vendor_boundary.py`, `envelope_change_check.py`, `output_schema_drift_check.py` | 전부 PASS, 고정 수치는 그 시점 실행 결과로 다시 센다 |
| 최종 독립 검증 | 구현에 관여하지 않은 세션 | Tier 1(실제 playbook + 미러 재생) 18 label 재실행 → 수정 전 기준선과 diff 를 ISSUES 의 기대 변화와 1:1 대조, 예상 밖 diff 0 | 예상 밖 diff 0, 132칸 판정표 ISSUE 칸이 해당 묶음에서 PASS 로 바뀜 |

주의: 재생 한계(`baseline/README.md`)는 구현 뒤에도 같다 — 401/403·timeout·익명 범위·전원 Off 인과·HT 기대값은 실장비/OS 실측 없이는 '확정' 이라 쓰지 않는다. production 승격은 main Job 성공 + prodgen gate 뒤에만(rule 93 R2 예외 2).

---

## 6. 참고

- 분석 보고서: `tests/evidence/2026-10-26-redfish-mock2-audit/analysis/01~06`
- 통합 이슈·클러스터·사용자 결정: `tests/evidence/2026-10-26-redfish-mock2-audit/ISSUES.md`
- 기준선·재생 도구·한계: `tests/evidence/2026-10-26-redfish-mock2-audit/baseline/README.md`, `tools/`
- Mock: `tests/reference/redfish/mock2/README.md`
- 규칙: CLAUDE.md §4·§5·§11·§15·§16, rule 12(adapter 경계)·21(fixture/golden)·22(fragment)·92(Additive)·96(origin 주석)
