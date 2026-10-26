# 최종 요약 — Redfish 2차 Mock 11대 전수 분석 Round (2026-10-26, 분석 단계)

> 메인 Claude Fable 5.1 (`claude-fable-5-1`, effort=max) + 분석 작업자 6개(같은 모델·effort, 각자 격리 worktree). 제품 소스·ADR·기존 테스트·Mock 원본 변경 **0**. JSON 결과 스키마 변경 제안 **0**.
> 구현은 별도 세션(Fable 5.1 / max) — `docs/ai/tickets/2026-10-26-redfish-mock2-fix-plan/INDEX.md`.

## 1. 11대 처리 상태

| 서버 | 미러 상태 | 아카이브 대조 | Tier 1 실제 playbook | Tier 2 모듈 재생 | 분석 커버리지(12영역) |
|---|---|---|---|---|---|
| csus3200_01 | INCOMPLETE(장비 500·timeout 6건, 수집 경로 밖) | 누락 0·차이 0 | success · adapter hpe_csus_3200 · 요청 200 | success | 12/12 판정(ISSUE 8 · PASS 3 · N/A 0) |
| csus3200_02 | INCOMPLETE(9건) | 누락 0·차이 0 | success · 요청 148 | success | 12/12 |
| csus3200_03 | INCOMPLETE(6건) | 누락 0·차이 0 | success · 요청 184 | success | 12/12 |
| dl380_gen12_01 | COMPLETE | 누락 0·차이 0 | success · adapter hpe_ilo7 · 요청 156 | success | 12/12 |
| dl380_gen12_02 | COMPLETE | 누락 0·차이 0 | success · 요청 147 | success | 12/12 |
| dl380_gen12_03 | COMPLETE(호스트 전원 Off 스냅샷) | 누락 0·차이 0 | success · 요청 84 | success | 12/12 |
| dl380_gen12_04 | COMPLETE | 누락 0·차이 0 | success · 요청 147 | success | 12/12 |
| sr650_v4_01 | INCOMPLETE(License 템플릿 경로 500 1건) | 누락 0·차이 0 | success · adapter **xcc3→lenovo_bmc 강등** · 요청 112 | success | 12/12 |
| sr650_v4_02 | INCOMPLETE(1건) | 누락 0·차이 0 | success · 강등 · 요청 129 | success | 12/12 |
| sr650_v4_03 | INCOMPLETE(1건) | 누락 0·차이 0 | success · 강등 · 요청 163 | success | 12/12 |
| sr650_v4_04 | INCOMPLETE(1건) | 누락 0·차이 0 | success · 강등 · 요청 117 | success | 12/12 |

- 11대 × 12 영역 = **132칸 전부 판정**: ISSUE 75 · PASS 49 · NOT_APPLICABLE 8(DL380/SR650 의 `multi_node` — adapter 가 layout 을 주지 않음) · MOCK_LIMITATION 0(영역 단위; 필드 단위 한계는 각 보고서 표) · NOT_CHECKED 0. 칸별 근거 `coverage/coverage-132.md`.
- 1차 미러 7대(다른 장비)도 Tier 1/2 전부 success. 1차 축약 golden 과 전체 미러 재생 차이는 `bios` 1건(golden 이 `gather_bios` 이전)뿐, CSUS 는 adapter 모드에서 차이 0.
- INCOMPLETE 는 폴더 부재가 아니라 장비가 5xx/무응답을 준 리소스가 있었다는 뜻이며 모두 Gathering 이 읽지 않는 경로다(`inventory/INVENTORY.md`).

## 2. 기능별 결함 건수 (보고서 §4 기계 추출, `coverage/issues_raw.md`)

| 보고서 | 영역 | HIGH | MED | LOW | 비고 |
|---|---|---|---|---|---|
| 01 | system · hardware · multi_node | 1 | 2 | 8 | HIGH: adapter 재선택 강등(확정) |
| 02 | cpu · memory | 1 | 4 | 7(+관찰 1) | HIGH: HT 비활성 `logical_threads` 2배(추정) |
| 03 | network · storage | 0 | 2 | 8 | XCC3 FC 포트 혼입, 전원 Off 호스트 |
| 04 | firmware · bios | 0 | 5 | 11 | category 규칙 3건, Pending 슬롯, 테스트 격리 결함 |
| 05 | thermal · power | 0 | 4 | 8 | Absent 센서 0 °C, AC 입력 없는 PSU, 전원 Off |
| 06 | bmc (+users 관찰) | 0 | 1 | 9 | account family 가 adapter 이름 의존 |
| 합계 | 12 영역 | **2** | **18** | **51** (+1) | 총 72건, 중복 3쌍 표시 |

## 3. 원인별 묶음 (ISSUES.md §2, 우선순위 순)

| 순위 | 클러스터 | 한 줄 | 수정 위치(공통 우선) |
|---|---|---|---|
| 1 | C1 adapter 선택·재선택 | model 일치 + firmware 불일치를 실격으로 보는 공통 규칙 + 재선택 facts 가 `Manager.FirmwareVersion` 만 씀 → Lenovo 5/5 범용 adapter 로 강등 | `module_utils/adapter_common.py`, `reselect_adapter.yml`, `lenovo_xcc3.yml` 패턴 |
| 2 | C3 CPU 논리 스레드 | LPC·ΣTotalThreads 모두 HT 를 반영하지 않는 펌웨어(XCC 2.97·RMC 1.77.30) — HT Disabled 5대에서 2배; ADR-2026-10-18/19 전제 붕괴 | `normalize_standard.yml` cpu, `_normalize_cpu_raw`, BIOS HT 속성(이미 수집) — **OS 실측 후** |
| 3 | C2 전원 Off 호스트 | 200 + placeholder 를 success 로 — Storage 0·빈 DIMM 16·PSU Absent 0.00·센서 0 | `gather_memory/power/thermal/storage` 공통 PowerState notice + placeholder → null |
| 4 | C9 firmware category | 이름 토큰 사슬 — UEFI·MegaRAID·백플레인·비디오 오분류 | `normalize_standard.yml` `_rf_firmware_categorized` + 구조 신호 |
| 5 | C4 Lenovo XCC3 모양 | FC 포트가 EthernetInterfaces 로, 빈 `-Pending` 슬롯 상시, 속도 1024 배수 | 주소 형식·구조 신호 기반 제외(벤더 분기 없음) |
| 6 | C10 전원·온도 의미 | Absent 센서 0 °C 포함, AC 입력 없는 PSU 원인 미표기 | `gather_thermal/power` State 필터 + notice |
| 7 | C7 테스트·재생 | `install_fakes` 미복원(tests/unit 19 failed), 2차 모양 fixture 부재, normalize 층 재생 불가 | `replay_full_mirror.py` 복원, 2차 축약 fixture, Tier 1 재생 편입 결정 |
| 8 | C5 CSUS/RMC | 집합 섀시 고정 경로 404 11개, DIMM 속도 I/O 클럭, mock baseline | 섀시 링크 gating, 계약 명시, baseline 교체 결정 |
| 9 | C6 계약·사전 drift | 선언·미발행/미등재/서술 오류(health rollup) | 문서·사전 묶음 + Additive 폴백 2건 |
| 10 | C8 기존 필드 보강 | link/speed·mtu·wwn·bios_date·rank·캐시 | 요청 추가 0~최소 |
| 11 | C11 bmc·diagnosis | account family 가 adapter 이름 의존, `auth_success` 무조건 true, NIC 선택 순서 의존 | `resolve_account_family` 장비 값 우선 등 |

## 4. 예상 위험

- **C1 수정은 adapter 선택 전체에 닿는다** — 18 label + 기존 단위 매트릭스 22건 전수 회귀 없이는 적용 금지(CLAUDE.md §5). Dell R740 1차 선택(`idrac10`, priority 독식)도 같은 규칙의 산물이라 규칙 B 가 Dell 을 바꾸지 않는지 고정 테스트 필요.
- **C3 는 '추정'** — OS/ESXi 실측 없이 코어 수로 바꾸면 반대 방향 오류 가능. 실측 전 적용 금지.
- **golden 갱신**(`real_hpe_dl380` temps, `real_lenovo_sr650` -Pending, 1차 bios None)은 rule 21 R3 사용자 승인 사항.
- **전원 Off 인과는 가설**(iLO 7 1대) — 다른 벤더의 전원 Off 모양 미확인.
- **재생 한계**(`baseline/README.md`): 401/403·계정 복구·timeout·익명 범위·미기록 경로는 실장비 없이 '확정' 불가. CSUS 고정 경로 11개의 실장비 응답 불명(링크 gating 으로 의존 소멸 가능).
- production 승격·main 병합은 이번 Round 범위 밖(분석 브랜치는 main 미병합).

## 5. 미해결 · 증거 부족

- HT Disabled 5대(csus3200_02, dl380_gen12_03, sr650_v4_01/02/04)의 OS/ESXi 논리 CPU 실측.
- dl380_gen12_03 전원 On 후 재수집(전원 Off 인과 확정), XCC/iDRAC 전원 Off 모양.
- Superdome Flex 플래그 복제의 타당성(실측 0), `hardware.uuid` 바이트 순서 vs OS(같은 장비 캡처 없음).
- Lenovo 실장비의 익명 `Systems/1` 허용 여부(1차 선택 facts 가 채워질 가능성), DL380/SR650 의 `WWW-Authenticate` realm.
- 페이지네이션·멤버 5xx·BIOS 실패 분기·IB·NVMe-only·다중 섀시 소유는 18 label 에 표본 없음(합성 테스트만).

## 6. 사용자 승인이 필요한 사항 (ISSUES.md §7 — 구현 전)

1. C3 HT 규칙 적용 전 OS/ESXi 실측 확보 및 `processor_summary_logical_count` 플래그 처분.
2. `cpu.manufacturer`: 구현 vs 사전 정정 / `cpu.architecture` 표기.
3. CSUS DIMM 속도: 계약 명시만 vs `Oem.Hpe.Label` 기반 MT/s 보정.
4. Redfish `data.system.hostname/fqdn` 과 `sections.system=not_supported` 정합, CSUS `HostOS` 활용.
5. CSUS baseline·계약 예시를 실 캡처로 교체(어느 캡처).
6. composition count 0 → null.
7. firmware category enum 확장(`hba`) 여부.
8. Tier 1 미러 재생 HTTPS 서버·2차 축약 fixture(`real_*`)의 저장소 편입.
9. golden 갱신 범위.
10. `data.users` 를 BMC 계정으로 채울지(기본: 유지).
11. 분석 브랜치 `docs/redfish-mock2-audit-20261026` 의 main 병합 방식(squash, rule 93 R2)과 시점.

## 7. 경로·커밋

| 항목 | 위치 |
|---|---|
| Mock 아카이브(main) | `tests/reference/redfish/mock2/` — main `7c22ca4a`(아카이브) · `e8b5ae9b`(fingerprint), origin/internal main 동일 |
| 분석 통합 브랜치 | `docs/redfish-mock2-audit-20261026` (main `e8b5ae9b` 기준, 분석 산출물만) |
| 인벤토리·baseline·도구 | `db33e804`, `0eac6bf1` |
| 보고서 cherry-pick | 02 `3695e9b7` · 03 `f66e9f1d` · 01 `6fe1f9e8` · 04 `da7fba18` · 05 `c7053ce7` · 06 `a75c4ef4` (각 작업자 worktree 브랜치의 보고서 2파일 커밋만) |
| 통합 산출물 | 이 디렉터리의 `ISSUES.md` · `coverage/` · `SUMMARY.md` · `docs/ai/tickets/2026-10-26-redfish-mock2-fix-plan/INDEX.md` (마지막 커밋 — `git log --oneline -1` 로 확인) |
| 외부(읽기 전용) | 원본 `C:\github\서버mock데이터\{1차,2차}`, 추출본 `C:\github\ClovirONE\mock2-audit-20261026\extract\`, WSL `/root/se_mirrors`, `/root/se_mirror_tls`, `~/.se_vault_pass`(WSL 600 사본 — 정리 여부 사용자 결정) |

## 8. 수행하지 않은 것 (명시)

- 제품 소스·ADR·기존 테스트·Mock 원본 수정, 실장비 접속, production 승격, main 병합, 새 의존성 설치.
- `tests/unit` 전체 실패 19건의 수정(원인 특정만), golden 갱신, baseline 교체.
- 분석용 worktree·임시 브랜치는 6개 보고서 취합·132칸 확인 뒤 정리했다(사용자 브랜치·다른 세션 작업 미접촉). 추출본·WSL 사본은 삭제하지 않았다.
