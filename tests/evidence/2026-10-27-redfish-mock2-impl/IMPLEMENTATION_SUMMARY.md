# 구현 요약 — Redfish 2차 Mock 11대 Gathering 구현·회귀 Round (지시서 2, 2026-10-27)

> 상태: **구현 완료 · 독립 검증 전.** 이 문서는 구현 세션(Fable 5.1 / effort=max)의 자기 보고다. 독립 검증 세션의 PASS 가 있기 전에는 "완료" 가 아니라 "독립 검증 대기" 다. `main` 병합 · `production` 승격은 하지 않았고(FIX 11), 실장비 접속도 없었다.

## 1. 범위·브랜치

- 입력: 2026-10-26 분석 Round 73건(`tests/evidence/2026-10-26-redfish-mock2-audit/ISSUES.md`) + 사용자 FIX 1~11 + 2·3차 검토(03-storage-004 A안 · WP2 opt-in 규칙 · WP4 구조 근거 · FC HBA 3중 조건 + RAID 음성 · 디스크/FC 개수 정합 회귀).
- 브랜치 `fix/redfish-mock2-20261027`(분기 `b8985826` = 분석 브랜치 HEAD). WP0~WP12 직렬, WP 마다 `feat:` / `test:` / `docs:` 커밋 분리, 매 WP 뒤 push. 커밋 목록은 `git log --oneline b8985826..HEAD`(WP12 전 46개 — `ISSUE_DISPOSITION.md` 머리말에 WP 별 SHA).
- 변경 경로: Redfish gathering(`redfish-gather/**`, `module_utils/adapter_common.py`, `adapters/redfish/{lenovo_xcc3,hpe_csus_3200,hpe_superdome_flex,cisco_cimc}.yml`), 스키마·계약(`schema/field_dictionary.yml` 208 → 262 항목, `schema/fields/*.yml`, `schema/sections.yml` 주석, examples · output_examples, baseline 5종), `tests/**`, `docs/**`. **OS/ESXi 채널 · `common/tasks` · `callback_plugins` · `Jenkinsfile*` · `vault/` 변경 0**(`git diff --stat b8985826..HEAD -- os-gather esxi-gather common/tasks callback_plugins Jenkinsfile_portal vault` 비어 있음).

## 2. WP 별 결과

| WP | 내용 | 주요 변경 | evidence |
|---|---|---|---|
| WP0 | 기준선 재측정 · 티켓 정정표 | Tier 0 4종 재실행 · 19건 쌍 실행 bisect(단일 원인) · INDEX.md FIX 정정표 | 00 |
| WP1 | 테스트 격리 · 2차 fixture 11세트 · Tier 1 도구 편입(FIX 8) · 1차 bios(FIX 9) · Tier 1/2 기준선 · 개수 정합 회귀(사용자 3차 지시) | `installed_fakes` + 루트 conftest 가드(04-test-001) · `tests/fixtures/redfish/real_*_{01..04}` · `tests/redfish-probe/mirror_replay/` · `tests/scripts/inventory_parity.py` + `test_inventory_count_parity.py` | 00 · 01 · inventory-parity-before |
| WP2 | Lenovo XCC3 재선택(C1 HIGH) | opt-in `match.bmc_model_patterns`(facts `bmc_model`), `lenovo_xcc3.yml` firmware 토큰 제거 — 31 adapter × 기존 facts 점수 동일 증명 | 02 (+scores before/after json) |
| WP3 | 전원 Off 호스트 · 빈 슬롯 · 거짓 센서(C2) | PowerState out-param → notice · 빈 DIMM 제외 · Absent PSU null · 비-Enabled 센서 reading null | 03 |
| WP4 | firmware category(C9, FIX 7) | `firmware_links`(Bios/Manager ActiveSoftwareImage · RelatedItem /Bios) 1순위 + 검증 토큰 + 컨트롤러 조인, FC HBA → other, 14값 긍정·부정 전수 | 04 · 04-matrix |
| WP5 | XCC3 응답 모양(C4) | FC-in-EthernetInterfaces normalize 제외 + INV-5 · 빈 -Pending 제외 · PSU strip · locator ServiceLabel · oem 2키 | 05 |
| WP6 | 전원·온도 의미(C10) | Absent 센서·팬 제외 + 건수 notice · PSU 입력 0 관측 notice · 소비전력 폴백 순서 · ThermalSubsystem 보강 | 06 |
| WP7 | CSUS 섀시 gating · composition null(FIX 6) · FC HBA 카드 조건 notice(결정 11 A안) · FIX 3 문서 | 섀시 본문 링크 gating(요청 -14) · 3중 조건 notice(RAID/NIC/미선언/LinkStatus 음성) · adapter `pcie_port_link_condition_registries: [H3Alert]` | 07 |
| WP8 | 계약·사전 정정(C6) + FIX 2/4 | `cpu.manufacturer` 발행 · `hardware.health` Rollup 폴백 · 사전 +53 · 03-fields 전면 · ADR 6건 append · EXTERNAL_CONTRACTS · DRIFT-031 | 08 |
| WP9 | FIX 1 | Redfish `data.cpu.logical_threads` 키 제거(top + partitions), 플래그 제거, baseline 4종 키 삭제, 테스트 30건 재작성 | 09 |
| WP10 | 기존 필드 보강(C8, 요청 0) | ports 0 → null · NDF MTU · IPv6 · wwn · OEM 캐시 · rank · bios_date 폴백 | 10 |
| WP11 | bmc · diagnosis(C11) · FIX 10 | iLO DateTimeService 시간대(+1 GET) · NIC 선택 규칙 · RackManager 이름 · Lenovo Family 세대 Manager.Model · WriteableProperties 강등 · 익명 auth null · users 불변 | 11 |
| FIX 5 | CSUS 실측 baseline 교체(WP11 뒤) | `hpe_csus_3200_baseline.json` ← csus3200_01 Tier 1 봉투(수정 2곳), registry · 가드 테스트 · 03-fields §9 재작성 | 07 FIX 5 절 · G-25 |
| WP12 | 마무리 | `ISSUE_DISPOSITION.md`(73건) · `coverage-132-after.md` · `inventory-parity.md` · 이 문서 · `INDEPENDENT_REVIEW_HANDOFF.md` · 카탈로그 갱신 · 최종 Tier 1/2 | 이 디렉터리 |

## 3. 최종 검증 결과 (구현 세션 자기 측정 — 독립 검증 대상)

| 층 | 결과 | 로그 |
|---|---|---|
| `pytest tests/unit` 전체 | **5226 passed · 33 skipped · 0 failed**(WP11 뒤; FIX 5 는 regression/e2e/integration 영역) | `tier0/pytest_unit_after_wp11.log` |
| `pytest tests/integration -m "not live"` | **497 passed · 6 skipped**(FIX 5 뒤) | `tier0/pytest_integration_notlive_after_fix5.log` |
| `pytest tests/e2e tests/regression` | **1098 passed · 12 skipped · 5 xfailed**(FIX 5 뒤) | `tier0/pytest_e2e_regression_after_fix5.log` |
| WSL 엔진 2파일 · `ansible-playbook --syntax-check` 3채널 | 23 passed · 3/3 OK(WP11 뒤) | `tier0/` |
| 게이트 | `validate_field_dictionary.py` PASS(262) · `output_schema_drift_check.py` 정합 · `verify_vendor_boundary.py` 통과(WP12 에서 WP10 의 `Oem.Hpe.Label` 접근 1줄 `# nosec rule12-r1` 표기 누락을 잡아 `b31d131d` 로 보강 — 동작 변경 0) · `verify_harness_consistency.py` 통과 · `envelope_change_check.py` advisory(기존 diagnosis 키 오경보 외 0) | — |
| Tier 1 최종(실제 `ansible-playbook` + HTTPS 미러, 18 label) | **18/18 rc 0 · success · errors 0**, `tier1-after-WP11` 대비 **봉투·요청 집합 차이 0**(`tier1-final/_diff_vs_after_wp11.md`, 허용목록 비움) | `tier1-final/` |
| Tier 2 최종(`tier2_replay.py`, 18 label) | 18/18 success · golden 보유 15 label GOLDEN_KEYS 차이 0 | `tier2-final/_vs_golden.md` |
| 개수 정합(디스크·FC 포트) | 18/18 PASS · UNEXPLAINED 0 | `inventory-parity.md` |
| INV-5(interfaces 에 FC/8옥텟 주소 없음) | 위반 0 · interfaces 수 불변(WP5 이후) | `tier1-final` |
| 132칸 재판정 | **PASS 120 · ISSUE 2 · MOCK_LIMITATION 2 · N/A 8**(ISSUE 2 = dl380_gen12_03 storage/firmware — 03-storage-001 (b) HOLD 의 같은 원인; MOCK 2 = csus3200_01/03 storage 포트 단위 링크) | `coverage-132-after.md` |

## 4. 호출자가 볼 변화 (envelope)

- **유일한 비-Additive**: Redfish `data.cpu.logical_threads` 키 소멸(top + `multi_node.partitions[].cpu`; OS/ESXi 는 그대로 — FIX 1). `schema/examples` · `output_examples` · baseline 4종에서도 제거.
- 값이 채워지는 기존 키: `cpu.manufacturer`(FIX 2) · `hardware.bios_date`(Lenovo) · `bmc.timezone`(iLO 7) · `network.interfaces[].mtu` · `memory.slots[].rank_count`(CSUS) · `hardware.oem.machine_type/led_indicator`(Lenovo) · `hardware.health`(Rollup 폴백 — 18 label 값 불변).
- 새 키(원천이 있을 때만 모듈이 내고 최종 JSON 은 항상 키): `storage.physical_disks[].wwn` · `cpu.summary.groups[].l2_cache_kb/l3_cache_kb` · `network.interfaces[].addresses[]` family ipv6(실측 0건).
- 항목 수·값 변화: 빈 DIMM 제외(dl380_gen12_03 32 → 16) · Absent 센서 제외(DL380 4 label) · 비-Enabled 센서 reading null · Absent PSU capacity/firmware null · 빈 `-Pending` firmware 제외(Lenovo) · XCC3 FC 주소 NIC 제외(interfaces 9 → 5 등) · ports `CurrentLinkSpeedMbps 0` → null(Dell) · firmware category 재분류(Lenovo UEFI → bios · PSoC → backplane · HPM/SCM-FPGA/PLD → cpld · HPE MR4xxi → storage_controller · Embedded Video → other · FC HBA → other) · CSUS composition count 0 → null · PSU model 공백 제거 · locator `"23"` → `"DIMM 23"`.
- 메타·진단: Lenovo XCC3 `meta.adapter_id = redfish_lenovo_xcc3`, notice 추가(전원 Off · 제외 건수 · 입력 0 관측 · bios_date 폴백 · FC HBA 카드 조건), `auth_success` 는 익명 수집 성공 시 null(18 label 은 true), `diagnosis.details.account_service.write_demoted_by_device`(복구 경로에서만).
- 요청: CSUS 7 label -14(링크 없는 섀시 Power/Thermal 404 제거), iLO 7 5 label +1(`Managers/1/DateTime`), 그 밖 불변. `status` · `sections` 판정 18 label 불변.

## 5. 처분 집계 · 남은 것

- 73건: FIXED 43 · DOC_CORRECTED 19 · OBSERVATION_ONLY 11(+ 병기 MOCK_LIMITATION 2 · VALIDATED_EXISTING 1 · **HOLD 1 = 03-storage-001 (b) controllers 보강 — 사용자 결정**). 전부 `ISSUE_DISPOSITION.md`.
- 실장비 미검증: 전부 Mock 재생(HTTPS 미러 + 실제 playbook)이다. 실장비에서만 확인되는 것 — CSUS FC 포트 단위 링크(03-storage-004), Lenovo 복구 경로(401 → Family 세대, 06-bmc-001), RMC `@Redfish.WriteableProperties` repair 거동(06-bmc-002), iLO DateTime 실시간 값, 전원 Off 인과(C2).
- 하지 않은 것: `main` 병합 · `production` 승격 · 실장비 접속 · 새 의존성 · `schema/output_examples/redfish_hpe_csus_3200.jsonc` 실측 구조 재작성(주석 예시 유지, OBSERVATION) · PCIeFunctions 로 controllers 보강(HOLD).
- 다음: 새 Fable 세션 독립 검증(`INDEPENDENT_REVIEW_HANDOFF.md`) → 사용자 승인 → `main` 병합 방식 결정 → `prodgen` 승격.
