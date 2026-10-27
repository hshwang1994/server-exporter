# 11 — WP11 (C11): bmc · diagnosis · FIX 10 (06-bmc-001 · 002 · 003 · 004 · 005 · 006 · 007 · 009 · 010 · FIX 10)

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027`. 원칙: 벤더 이름 분기 없음 — 세대는 장비 값(`Manager.Model`), 집합 관리자는 DMTF `ManagerType` enum, 쓰기 범위는 장비 선언(`@Redfish.WriteableProperties`), iLO 시간대는 OEM 링크(`Oem.Hpe.Links.DateTimeService`)의 존재로만 가른다. 추가 HTTP 요청은 Plan 대로 iLO `Managers/1/DateTime` 1건(`TimeZoneName` 이 없을 때만).
- 06-bmc-008(테스트 seam 복원)은 WP1 에서 끝났다. 06-bmc-004 · 007 · 009 는 WP8 사전 정정에 들어갔고 여기서 실측으로 보강·정정했다(04 의 WP8 문구 "UTC Z(iLO 7 · XCC 3)" 는 틀렸다 — 아래 §4).

## 1. 규칙 · 구현

| 이슈 | 규칙 | 구현 | 18 label 영향 |
|---|---|---|---|
| 06-bmc-001 | 복구 Family 의 Lenovo 세대는 장비가 준 `Manager.Model`("XClarity Controller" 뒤 숫자)이 1순위 — 3 이상 → `lenovo_xcc3_accounttypes`, 숫자 없음 → XCC2 계열, 모델이 없을 때만 adapter hint(무인증 1차 선택값) | `resolve_account_family` Lenovo 분기에 (0) 단계 추가, `reasons` 에 모델·hint 를 함께 기록(hint 는 참고) | Tier 1 은 표준 계정 1차 인증 성공이라 reconcile 미진입 — 값 변화 0. 실장비 401 → 복구 경로는 재생으로 확정 불가(MOCK_LIMITATION) |
| 06-bmc-002 | 장비가 `@Redfish.WriteableProperties` 를 선언하면 repair PATCH 는 그 밖 속성을 보내지 않는다(쓰기 **전에** 확정 — 추측성 재시도 아님, vendor 이름 분기 없음) | `account_service_discover` accounts[].`writable` 보존 · `account_service_provision` repair 본문에서 선언 밖 키 제거 + `out.write_demoted_by_device` | 값 변화 0(reconcile 미진입). RMC 실측 7/7 `["Password"]` → RoleId drift 가 있어도 Password 만 쓴다. 선언에 Password 가 없으면 본문이 빌 수 있는데 이는 종전에도 Password 가 writable 아닌 Family 에서 가능했던 경로이고 최종 판정은 재조회·재인증 게이트다(관찰 — 실측 장비 없음) |
| 06-bmc-003 | `TimeZoneName` 이 없고 `Oem.Hpe.Links.DateTimeService` 가 있으면 1회 GET → `TimeZone.Value`(없으면 `Name`); 실패·404 는 조용히 null | `gather_bmc` HPE OEM 블록 | iLO 7 5 label `bmc.timezone` null → `JST-9:00` ×4 · `GMT-0`(1차), 요청 +1 `Managers/1/DateTime`; RMC(`TimeZoneName` 있음) · XCC · iDRAC 미발동 |
| 06-bmc-005 | `ip`/`mac_address`/`dns_name` 은 같은 NIC: ① 대상 IP 보유 → ② `Links.HostInterface` 없음 ∧ `InterfaceEnabled` ≠ false → ③ 첫 NIC(종전) | `gather_bmc` NIC 루프를 후보 수집 + 선택으로 분리 | 18 label 값 불변(전용 관리 NIC 이 첫 멤버). iLO 7 USB 가상 NIC(16.1.15.1 · `Links.HostInterface`)이 앞에 와도 ② 가 거른다(합성) |
| 06-bmc-006 | layout 이 없어도 `ManagerType` ∈ {RackManager, EnclosureManager} 면 Manager `Id`(짧은 토큰) 또는 ManagerType 을 이름으로 | `gather_bmc` rmc_label 폴백 | 18 label 불변(CSUS 는 adapter layout 경로). plain 재생(layout 없음) CSUS 가 `iLO` → `RMC` |
| 06-bmc-010 | 익명(빈 자격) 수집 성공은 인증 성공 관측이 아니다 → `auth_success` null(CLAUDE.md §9) | `site.yml` 성공 경로: `_rf_used_account.role == anonymous` → null, 그 밖 true | 18 label true 그대로(전부 primary) |
| FIX 10 | `data.users` 는 OS 계정 의미 — BMC 계정으로 채우지 않는다 | 변경 0 + 고정 테스트 | 불변 |

## 2. 테스트 (Tier 0)

- 신규 `tests/unit/test_redfish_bmc_diagnosis_wp11.py` **29건**: Lenovo Family 세대(모델 × hint 매트릭스 · 결정성 · 참조 미러 XCC(2) 는 hint xcc3 여도 XCC2 계열) · discovery `writable` 보존 · repair 강등 3분기 · iLO timezone(이름 있음/없음 · 링크 없음 · 리소스 404) · NIC 선택(순서 뒤집기 · HostInterface · 대상 IP 우선 · 다른 벤더 불변) · `bmc.name` 폴백(합성 RackManager · CSUS plain 재생 `RMC`) · site.yml 익명 → `auth_success` null 배선 · `data.users` 불변.
- `tests/unit/test_account_hpe_rmc_enabled.py`: 라우터 계정 본문을 실측 RMC shape(`@Redfish.WriteableProperties ["Password"]` · `Enabled true` · `Locked false` · `AccountTypes ["Redfish"]`)로 — 14건 PASS.
- 묶음: `tests/integration -m "not live"` **497 passed** · `tests/e2e tests/regression` **1094 passed** · unit 전체 **5226 passed, 33 skipped, 114 warnings** · WSL syntax 3채널 · 엔진 23 · `validate_field_dictionary.py` PASS(262) · drift 정합 · 사전·계약 테스트 24건(문서 패치 뒤 재실행).

## 3. Golden · 사전 · 문서

- G-24: DL380 5세트 recording 에 `Managers/1/DateTime` 추가(전수 미러 원천), golden `data.bmc.timezone`, 예산 +1(`added_reason`). 그 밖 fixture 불변(HPE 에뮬레이터 5세트는 replay-miss 404 → null 유지, golden 불변).
- 사전 help: `bmc.timezone`(원천 순서) · `bmc.ip`/`mac_address`/`dns_name`(선택 규칙) · `bmc.name`(집합 관리자 폴백) · `bmc.datetime`(XCC 3 는 오프셋 포함 — WP8 문구 정정) · `diagnosis.auth_success`(익명 null) · `diagnosis.details.account_service`(`write_demoted_by_device`). 03-fields §5(익명) · 6.6(선택 규칙 · 이름 · 시간대 · datetime 표기). EXTERNAL_CONTRACTS 2026-10-27 행 4건(iLO DateTime · XCC Manager.Model 세대 · RMC WriteableProperties · iLO EthernetInterfaces 순서). ADR-2026-05-12 결정 1 보강.

## 4. Tier 1 after (18 label, `tier1-after-WP11/` ↔ `tier1-after-WP10/`, `_allow.json` 2항목)

- 18/18 rc 0 · success · errors 0 (build `mirror-replay-wp11-after`). `_diff_vs_after_wp10.md`: 바뀐 경로는 iLO 7 5 label 의 `data.bmc.timezone` 1건씩(설명됨 5 · **미설명 0**), 요청 집합은 같은 5 label 에 `Managers/1/DateTime` +1(distinct 152→153 · 143→144 · 80→81 · 143→144 · 131→132) · 그 밖 13 label 변경 0 · 요청 +0/-0.
- `bmc.name` 18 label 불변(RMC ×7 · iLO ×5 · XCC ×5 · iDRAC ×1), `bmc.ip`/`mac_address`/`dns_name` 불변, `diagnosis.auth_success` 18 true.
- `bmc.datetime` 표기 실측: iLO 7 `…Z`(+`datetime_offset +09:00`), XCC 3 `…+09:00`, RMC `…+09:00`(2차) / `…+00:00`(1차 01·02), iDRAC `…-05:00`, 1차 XCC `…+00:00` — 06-bmc-004 서술 근거(XCC 3 는 Z 가 아니다).
- INV-5 위반 0 · interfaces 수 불변. 디스크·FC 포트 개수 정합 18/18 PASS · UNEXPLAINED 0.

## 5. 처분

| 이슈 | 처분 |
|---|---|
| 06-bmc-001 | FIXED (Manager.Model 1순위) + MOCK_LIMITATION (실장비 401 → 복구 경로 재생 불가) |
| 06-bmc-002 | FIXED |
| 06-bmc-003 | FIXED |
| 06-bmc-004 | DOC_CORRECTED (WP8 `bmc.datetime` help → WP11 실측 정정 · 03-fields 6.6) |
| 06-bmc-005 | FIXED (값 불변 — 규칙을 컬렉션 순서 비의존으로) |
| 06-bmc-006 | FIXED |
| 06-bmc-007 | DOC_CORRECTED (WP8 `diagnosis.details` Redfish 키 · `account_service {}` + WP11 `write_demoted_by_device`) |
| 06-bmc-008 | FIXED (WP1 — seam 복원) |
| 06-bmc-009 | DOC_CORRECTED (WP8 `bmc.uuid` help) |
| 06-bmc-010 | FIXED (합성 익명 성공 재생 테스트) |
| FIX 10 | VALIDATED_EXISTING (`data.users` 불변 + 고정 테스트) |
