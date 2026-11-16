# Redfish 표준 수집 계정 — 최종 호환성 매트릭스

작성일: 2026-08-12
기준 Commit: `5e72ac05` (변경 전) → 본 cycle 변경 후
입력: 9 Vendor 공식조사 문서 9건 + AS-IS 전수조사(정리됨) + 현재 HEAD 코드 실측

---

## 0-A. 2026-08-13 갱신 — 9 Vendor 조사 반영 구현 완료

정본: `tests/evidence/2026-08-13-account-write-contract-alignment.md`
계획: `docs/ai/contracts/redfish-account-write.md`

9 Vendor Delta 조사 결과를 코드 계약으로 반영했다. Evidence 등급 축을 상태와 분리한다.

| Evidence | 의미 |
|---|---|
| `LIVE-PROVEN` | 이 저장소 실장비에서 직접 재현 |
| `ADVISORY-DERIVED` | Vendor 공식 Advisory 가 defect 를 확인했으나 우리 payload 조합은 미검증 |
| `DOCUMENTED` | 공식 문서로 계약 확인, Live Write 없음 |
| `UNVERIFIED` | 공식 Write 계약 미확보 — 한 번의 결정적 쓰기만 하고 지원한다고 말하지 않는다 |

`LIVE-PROVEN` 과 `ADVISORY-DERIVED` 를 합치는 것은 절대 금지다.

### 새 판정 축 4종

| 축 | 뜻 |
|---|---|
| Property Contract | Family × Operation 별 `writable / read_only / verify_only / unsupported / unverified`. **표에 없는 Property 기본값은 `unverified` 이고 자동으로 쓰지 않는다.** |
| Create URI 종류 | `accounts_collection` / `account_service_root` / `account_instance`. Accounts **열거** URI 와 다른 개념이며 실패해도 갈아타지 않는다 |
| Operation 단위 If-Match | Inspur M6 = Create 없음 / Repair 있음 |
| Workaround Basis | `live_proven` / `advisory_derived` / `safety_strategy` (HPE) |

### HPE — Family 는 하나, 근거는 Firmware 별

쓰기 동작은 iLO5/6/7 전부 Password 단독 PATCH 로 같다(HPE 공식 지원 동작 + 저장소 안전 전략).
갈리는 것은 그 선택의 근거 수준이다.

| Firmware | Workaround Basis | Evidence | Firmware Risk |
|---|---|---|---|
| iLO6 **1.73** | `live_proven` | **LIVE-PROVEN** | a00159600en_us |
| iLO6 1.74 | `advisory_derived` | ADVISORY-DERIVED | a00159600en_us |
| iLO7 1.19 / 1.20 | `advisory_derived` | ADVISORY-DERIVED | a00159600en_us |
| iLO6 1.75+ / iLO7 1.21+ | `safety_strategy` | DOCUMENTED | **Advisory fixed** |
| iLO5 전체 / Firmware 판독 불가 | `safety_strategy` | DOCUMENTED | 해당 없음 |
| iLO4 | — (Oem/Hp) | DOCUMENTED | 해당 없음 |

`safety_strategy` / `advisory_derived` 를 Vendor mandatory 또는 LIVE-PROVEN 으로 표기하는 것은 금지다.

### Family 표 변화

| 종전 | 현재 | 이유 |
|---|---|---|
| `lenovo_xcc_accounttypes` | `lenovo_xcc2_accounttypes` + `lenovo_xcc3_accounttypes` | XCC3 공식 목록에 `PasswordChangeRequired` 가 없다 (03 §11.3) |
| — | `cisco_cimc3_instance_post` | IMC 3.x 는 Instance URI POST (04 §4.2) |
| — | `qct_legacy_redfish` / `qct_modern_redfish` / `qct_inhouse_openbmc` | 경계 기록용. **동작은 generic 과 동일**, AccountTypes 미전송 (09 §9/§44) |
| `_ACCOUNT_CREATE_STRATEGY` (vendor→method) | 제거 | Family 표와 다른 답을 담은 죽은 정본 |

### 제거한 재시도

`PasswordChangeRequired` 추가 후 2차 POST, 거부 속성 drop 후 재PATCH. 둘 다 제거했다.
허용되는 다중 쓰기는 ETag 412 재시도(동일 URI·동일 payload)와
Family 가 쓰기 전에 확정한 sequence(HPE) 뿐이다.

### 보호 계정

`HostBootstrapAccount == true` (DMTF ManagerAccount 표준 Property, 실미러 10.50.11.232 에 존재)
를 근거로 `protected` 분류한다. XCC3 전용 개념이 아니다. 열거·진단에는 남기고 Create/Repair
후보에서만 제외한다. 표준 계정 이름이 겹치면 `protected_conflict` → **Write 0**.

`reserved_slot_ids` 는 "여기에 만들지 마라" 이지 "여기 있는 계정은 못 고친다" 가 아니다.
두 축을 섞으면 안 된다.

### 2026-08-13 실장비 재검증

| 대상 | Check Mode | 1차 | 2차 | Account Write |
|---|---|---|---|---|
| Dell iDRAC9 10.100.15.34 | success | success 9/11 | success 9/11 | **0 / 0 / 0** |
| HPE iLO6 10.50.11.231 | success | success 9/11 | success 9/11 | **0 / 0 / 0** |
| Lenovo XCC 10.50.11.232 | success | success 9/11 | success 9/11 | **0 / 0 / 0** |
| Cisco CIMC 10.100.15.2 | success | success 9/11 | success 9/11 | **0 / 0 / 0** |

4대 전부 `used_role=primary` / `credential_scope=common/redfish/standard`.
Create / Repair 는 이번에도 조건이 발생하지 않아 미증명이다. 4대 모두 표준 계정이
이미 정상이다. 조건을 만들려면 운영 계정을 지워야 해서 하지 않았다.

---

## 0. 이 문서를 읽는 법

### 상태 표기

| 상태 | 의미 |
|---|---|
| `PROVEN` | **실장비에서** Create 또는 Repair → 표준 재인증 → 표준 계정 수집 → 2차 실행 Write 0 까지 확인됨 |
| `PARTIAL` | 공식 문서 또는 실장비 미러로 계약이 확인됐고 코드가 그에 맞게 동작하지만, 실장비 Write E2E 는 미확인 |
| `UNVERIFIED` | 공식 Write 계약을 확보하지 못했다. 현행 generic 경로를 **유지**하되 지원한다고 말하지 않는다 |
| `MISSING` | 해당 Family 를 위한 Strategy 자체가 없다 |
| `BROKEN` | 코드가 공식 계약과 어긋나 있다 |
| `HOLD` | 코드 문제가 아니라 운영 결정이 선행돼야 한다 |

### 2026-08-12 갱신 — git Location 실장비 검증 반영

정본: `tests/evidence/2026-08-12-git-location-live-verification.md`

lab 접근이 가능해져 git Location 4대에서 실제 수집을 수행했다. 그 결과 아래 3 Family 의
Case A(표준 인증 성공 → Account Write 0 → 표준 계정 수집)만 `PROVEN` 으로 올린다.
검증된 것은 정확히 그 Model + Firmware 범위다. **Create / Repair 는 여전히 미증명**이다.

| Family | 검증 대상 | Firmware | 증명된 것 |
|---|---|---|---|
| `lenovo_xcc_accounttypes` | XClarity Controller (10.50.11.232) | `AFBT58B 5.70 2025-08-11` | Case A + 2차 실행 Write 0 |
| `hpe_ilo5plus` | ProLiant DL380 Gen11 / iLO 6 (10.50.11.231) | `iLO 6 v1.73` | Case A |
| `cisco_cimc_collection_post_id` | TA-UNODE-G1 / CIMC (10.100.15.2) | `4.1(2g)` | Case A + 2차 실행 Write 0 + **Roles 어휘 기반 Family/RoleId 판정** |

Dell 은 유일하게 reconcile 조건이 발생했고(표준 401 + 계정 present) Repair 경로가 설계대로
전부 동작했지만 **비밀번호가 iDRAC Security Strengthen Policy 에 거부**되어 `HOLD` 를 유지한다.

Create 경로는 어떤 Family 에서도 실행되지 않았다. git 4대 모두 표준 계정이 이미 존재해
`presence=absent` 조건이 아예 생기지 않았다. 조건을 만들려면 계정을 지워야 하므로
거기까지는 하지 않았다.

### 2026-08-12 (2차) 갱신 — Global Standard Password 회전 + Repair 실증

정본: `tests/evidence/2026-08-12-standard-password-convergence.md`

전역 표준 계정 비밀번호를 교체하고 git Location 4대에 수렴시켰다. 그 과정에서
Repair 경로가 실장비에서 처음으로 완주했다. HPE 에서는 벤더 쓰기 계약 결함이 드러나
수정했다. Dell HOLD 는 **CLOSED** 다.

| 대상 | 1차 | Repair 실행 | 2차 | 판정 |
|---|---|---|---|---|
| Lenovo XCC (10.50.11.232) | 표준 401 → recovery 인증 → `present` → `patch_existing` | `write_accepted=true`, **`verification=verified`**, 표준 재인증 성공 | Write 0 | **Case B PROVEN** |
| HPE iLO6 (10.50.11.231) | 표준 401 → recovery 인증 → `present` → `patch_existing` | 쓰기는 수락됐으나 **비밀번호가 적용되지 않음** (아래 결함) | 수정 후 Write 0 | Case A PROVEN / Repair 는 코드 수정 + 실측 근거 |
| Cisco CIMC (10.100.15.2) | 표준 인증 성공 | 불필요 | Write 0 | **Case A PROVEN** |
| Dell iDRAC9 (10.100.15.34) | 표준 인증 성공 | 불필요 | Write 0 | **Case A PROVEN — HOLD CLOSED** |

#### HPE iLO — Password 는 반드시 단독 PATCH (실측 확정, 2026-08-12)

`10.50.11.231` / iLO 6 / ProLiant DL380 Gen11 / Redfish 1.20.0 에서 같은 계정·같은 값으로
통제 실험한 결과:

| PATCH 본문 | 응답 |
|---|---|
| `{Password:<길이위반>}` | HTTP **400** `iLO.2.36.InvalidPasswordLength` |
| `{Password:<길이위반>, Enabled, RoleId}` | HTTP **200** `Base.1.19.AccountModified` |
| `{Enabled, RoleId}` (Password 없음) | HTTP **200** `Base.1.19.AccountModified` |
| `{Password, Enabled, Locked, RoleId}` | HTTP **400** `iLO.2.36.PropertyNotWritableOrUnknown ['Locked']` |
| `{Password}` (정상 값) | HTTP **200** → 표준 자격 재인증 **성공** |

→ iLO 는 `Password` 가 다른 속성과 함께 오면 검사도 적용도 하지 않고 버린다. 그런데
응답은 성공과 동일하다 (아무것도 바뀌지 않는 본문도 `AccountModified` 를 준다). 응답만으로는
절대 구분할 수 없으므로 **Family 가 쓰기 전에** 방식을 정해야 한다.
반영: `_ACCOUNT_FAMILIES['hpe_ilo5plus'].isolated_write_patch = True`, `evidence: proven`.

부수 결함 2건도 같은 실측에서 확정해 고쳤다.
- `Locked: false` 를 무조건 실었다. 잠기지 않은 계정에는 no-op 인데 iLO 는 본문 전체를
  400 으로 거부한다(속성 자체가 없음). Lenovo XCC 는 read-only 로 거부한다. 이제 **실제로
  잠겨 있을 때만** 싣는다 → 실측 4대 모두 쓰기 1회 감소.
- 재인증 확인 간격이 고정 `(0,1,5)`=6초였다. iLO 는 `AuthFailureDelayTimeSeconds=10` /
  `AuthFailuresBeforeDelay=1` 을 스스로 선언한다. 즉 표준 인증이 한 번 실패한 뒤의
  재인증은 비밀번호를 옳게 써도 6초 안에는 전부 401 이다. 이제 장비가 선언한 값에서
  간격을 끌어온다(`account_verify_delays`, 상한 45초).

#### Dell 세대 판정 — adapter hint 단독 결정 제거 (2026-08-12)

`10.100.15.34` 는 실제로 iDRAC9 / PowerEdge R760 / FW 7.10.70.00 인데 Family 가
`dell_idrac10_slot_patch` 로 잡혔다. 원인은 두 겹이다.

1. Adapter 선택이 무인증 probe 단계라 `model` / `firmware` fact 가 비어 있다. 빈 fact 는
   실격이 아니라 skip 이라 priority 만으로 결정된다 (`dell_idrac10` 120 > `dell_idrac9` 100).
   실측 점수: 빈 fact 에서 idrac10 120520 > idrac9 100320. fact 가 차면 idrac10/idrac8 은
   `-9999` 로 실격되고 idrac9 가 100345 로 옳게 이긴다.
2. `resolve_account_family` 가 그 `adapter_id` 를 그대로 세대 근거로 썼다. 나머지 한쪽인
   `Manager.Model` 은 Dell 에서 `<NN>G Monolithic` 형태라 `idrac10` 이 들어갈 수 없는
   죽은 조건이었다 → **adapter hint 단독으로** Family 가 결정됐다.

이 오판은 이름에서 끝나지 않는다. 두 Family 는 `reserved_slot_ids` 가 `{1}` vs `{1,2}` 로 달라
**빈 슬롯이 2번일 때 PATCH 대상 URI 가 갈린다.** 이번 장비에서 차이가 보이지 않은 것은
slot 2 를 `root` 가 쓰고 있었기 때문이다. 두 Family 의 동작이 같아서가 아니다.

조치: 세대 근거를 Firmware major(iDRAC9 = 4~7.x, iDRAC10 = 1.x)로 바꾸고 Model 은 보조,
hint 는 근거가 없을 때만 쓰도록 되돌렸다. 회귀 테스트 4건 추가.
**Adapter 오선택 자체(1번)는 남아 있다.** 인증 후 adapter 재선택이 필요한 별도 변경이라
이번 cycle 범위 밖이며 `docs/ai/NEXT_ACTIONS.md` 에 등재돼 있다.

**[2026-11-16 — 세대가 생성 방식을 가른다 (DRIFT-034)]** 사이트 iDRAC10 에서 slot PATCH 생성이
"빈 계정 슬롯이 없어" 로 쓰기 전에 실패했다. Dell 공식 계약은 iDRAC10 = Collection POST 다(사용자가
`collection_post` 로 바꾸자 성공). iDRAC10 Family 를 `dell_idrac10_collection_post` 로 바꾸면서 판별도 다시 짰다.
2026-08-12 판별은 Firmware 4~7 만 iDRAC9 로 보고 **그 밖(iDRAC8 2.x · 초기 iDRAC9 3.x · Manager 미확인)은 hint 로** 넘겼다.
Dell hint 는 늘 idrac10 이므로, 생성 방식이 갈린 지금 그 누수는 지원하지 않는 POST 1회가 된다(R630 13G/2.86 · R740 14G/3.36 재생으로 확인).
새 순서: ① Manager.Model `<NN>G`(12~16 = slot · 17+ = POST — Dell 공식 스크립트 기준) 또는 Model 의 `idrac10`
→ ② Firmware major(1 = POST · 2~7 = slot) → ③ 계정 목록 모양(빈 slot 미리 깔림 = slot) → ④ hint → 근거 0 이면 slot.
운영에서는 `main()` 이 복구 자격으로 Manager URI 를 찾아 넘기므로 Model · Firmware 가 보통 있다.
시험: `tests/unit/test_account_create_method_by_generation.py`.

### 이번 cycle 에서 실제로 낮아진 불확실성

`tests/reference/redfish/**` 의 실장비 미러(Dell 5호스트 / HPE 1 / Lenovo 1 / Cisco 1)를
읽는 회귀 테스트가 종전 0건이었다(audit D-8). 이번에 `tests/integration/test_account_reconcile_replay.py`
로 연결해 **읽기 단계**(Capability Discovery / 계정 존재 판정 / Family 선택)를 실제 응답으로
검증한다. 미러에는 쓰기 응답이 없으므로 쓰기 동작은 여전히 미검증이다.

---

## 1. 전 Vendor 공통 계약 (이번 cycle 확정)

```text
Global Standard Gathering Account = 전역 1개   (vault/common/redfish/standard.yml)
Recovery Account                  = Location × Vendor (vault/<loc>/redfish/<vendor>.yml)
최종 Gathering                    = 반드시 Standard Account
정상 상태 재실행                   = AccountService Write 0건
```

성공 판정:

```text
쓰기 수락(벤더 계약 기준)  →  계정 리소스 재조회  →  상태 확인
  →  Global Standard Credential 재인증  →  표준 계정으로 실제 Gathering
```

`HTTP 2xx` 하나로 성공이라 하지 않는다. `verification='none'` 상태의 쓰기는 성공이 아니다.

### 공통 Capability Discovery (읽기 전용, 쓰기 전 필수)

`redfish_gather.account_service_discover()` 가 수집하는 것:

| 항목 | 용도 |
|---|---|
| ServiceRoot `AccountService.@odata.id` | 실제 AccountService URI (하드코딩 대체) |
| `Accounts.@odata.id` / `Roles.@odata.id` | 실제 컬렉션 URI (쓰기 대상 URI 정본) |
| `Members` + `Members@odata.count` | 열거 완결성 판정 |
| ManagerAccount 별 `Id/UserName/RoleId/Enabled/Locked/AccountTypes/PasswordChangeRequired/@odata.type` | 존재 판정 + 상태 수렴 + Family 근거 |
| `MinPasswordLength / MaxPasswordLength` | 정책 진단(차단 아님) |
| `AccountLockoutThreshold / Duration / CounterResetAfter` | lockout 예산 진단 |
| `SupportedAccountTypes` | 계정 분리 세대 판정 |
| Roles Collection member Id | **RoleId 문자열을 추측하지 않기 위한 정본** |
| Manager `FirmwareVersion / Model / ManagerType` | Firmware 경계 Family 판정 |

열거 상태는 3-상태다: `complete` / `incomplete` / `failed`.
계정 존재는 4-상태다: `present` / `absent` / `unknown` / `ambiguous`.
`unknown` 에서는 Account Write 0건이다.

---

## 2. Vendor × Family 매트릭스

### 2.1 Dell

| 항목 | iDRAC7 / iDRAC8 | iDRAC9 | iDRAC10 |
|---|---|---|---|
| AccountService URI | Manager-scoped (`/Managers/<id>/AccountService`) | 세대별 상이 — 실측 `.34` 는 root-scoped | root-scoped 관측 |
| 코드의 URI 결정 | **ServiceRoot 링크 추종** (하드코딩 제거) | 동일 | 동일 |
| Accounts URI | `AccountService.Accounts.@odata.id` | 동일 | 동일 |
| Create | 빈 slot PATCH | 빈 slot PATCH | **Collection POST** (`AccountService/Accounts`, Id 없음 — 2026-11-16 정정) |
| Update | ManagerAccount PATCH | 동일 | 동일 |
| Reserved slot | ID 1 (IPMI anonymous) | ID 1 | **ID 1 + ID 2 (default root)** |
| RoleId | Roles Collection 에서 선택 | 동일 | 동일 |
| AccountTypes | 미요구 | 미요구 | 실미러에 존재 — 읽기만 |
| Password | 문서상 max 20 | <4.00 20 / 4~6.x 40 / ≥7.00 127 + Strength Policy | Strength Policy |
| Lockout | IP Blocking | IP Blocking | FailCount 3 / FailWindow 60s / Penalty 60s |
| ETag | 미사용 | 미사용 | 미사용 |
| Write 성공 계약 | 2xx **AND** 본문 거부 없음 | 동일 | **200 + 본문 read-only 거부** 를 실패로 처리 |
| Repository Strategy | `dell_slot_patch` | `dell_slot_patch` | `dell_idrac10_collection_post` (종전 `dell_idrac10_slot_patch`) |
| Fixture Evidence | 없음 | 실미러 `10_100_15_27/28/31/33/34` | **없음** (아래 정정) |
| Live Evidence | 없음 | **2026-08-12 git: 10.100.15.34 / FW 7.10.70.00 — Repair 경로 전 단계 동작, 비밀번호만 거부. 계정 상태 변화 0** | **사용자 사이트 보고 2026-11-16** — slot PATCH 는 "빈 계정 슬롯이 없어" 로 쓰기 전 실패, Collection POST 로 생성 · 재인증 성공 (원본 envelope · Accounts 미캡처). lab 대상 부재 (`.34` 는 iDRAC9) |
| Status | `UNVERIFIED` | **`HOLD`** (Repair 경로 검증됨 / 비밀번호 정책 미해소) | `PARTIAL` (공식 문서 + 사이트 보고 1건) |
| Remaining Gap | iDRAC7/8 실미러 부재 | Create 실장비 미검증 | Accounts 원본 캡처(동적 모델 추정 확정) · 생성 응답(201 본문 · Location) 형태 |

**[정정 2026-08-13] 저장소에 iDRAC10 실미러는 없다.**
종전 표는 `10_100_15_34` 를 iDRAC10 Fixture Evidence 로 적었으나 그 미러는
`FirmwareVersion=7.10.70.00` / `Model=16G Monolithic` 즉 iDRAC9 다
(`LAB_INVENTORY.md` 2026-08-12 정정과 실장비 재검증이 모두 같은 결론). iDRAC10 행의
근거는 공식 문서뿐이며 Fixture / Live 모두 없다.

**`.34` HOLD 사유** — 종전 제목은 "iDRAC10 HOLD" 였지만 관측 장비 `.34` 는 iDRAC9 다(당시 Family 오판으로 iDRAC10 Family 가 잡혔다 —
위 [정정 2026-08-13] 과 같은 이유, 2026-11-16 제목 정정) (`tests/evidence/2026-08-12-redfish-standard-account-separation.md` §6.1):
장비가 돌려준 문장 그대로 —
`The property Locked is a read only property and cannot be assigned a value.` (1차, 코드로 해결됨)
`Unable to set the password because the password entered does not comply to the Security Strengthen Policy standards.` (2차, 운영 결정 필요)

코드는 두 층 모두 정확히 관측하고 진단한다. 남은 것은 비밀번호 값 또는 장비 정책 중
어느 쪽을 맞출지의 결정이다. 그것은 이 작업의 범위가 아니다.

### 2.2 HPE

| 항목 | iLO4 | iLO5 / 6 / 7 | CSUS 3200 RMC | Superdome Flex 280 RMC |
|---|---|---|---|---|
| OEM namespace | **`Oem/Hp`** | `Oem/Hpe` | RMC 별도 | RMC 별도 |
| Create | Collection POST + `Oem.Hp.Privileges` | Collection POST (RoleId) | POST 지원은 목차로 확인, **payload 미확보** | 상세 미확보 |
| Update | ManagerAccount PATCH | 동일 | Password PATCH 확인 | 미확보 |
| RoleId | OEM Privilege 중심 | Administrator/Operator/ReadOnly | Administrator/Operator/ReadOnly/CustomCli | Administrator/Operator/ReadOnly |
| AccountTypes | 없음 | iLO6 1.64+ / iLO7 지원 | 미확인 | 미확인 |
| Password | max 39 | max 39 (+ iLO7 EnforcePasswordComplexity) | 6~64, 기본 min 10 | 6~40, class 수에 따라 min 변동 |
| Lockout | — | AccountLockoutThreshold/Duration/CounterResetAfter | AccountLockoutDuration PATCH 가능 | 미확인 |
| Repository Strategy | `hpe_ilo4` | `hpe_ilo5plus` | `generic_collection_post` | `generic_collection_post` |
| Fixture Evidence | 없음 | 실미러 `10_50_11_231` (iLO6) + 에뮬레이터 | fixture 만 (mock) | fixture 만 (mock) |
| Live Evidence | 없음 | **2026-08-12 git: 10.50.11.231 DL380 Gen11 / iLO 6 v1.73 — Case A PROVEN** | 없음 | 없음 |
| Status | `PARTIAL` | **`PROVEN` (Case A만)** / Create·Repair `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` |
| Remaining Gap | iLO4 실장비/미러 부재 | Create 실장비 미검증 | RMC ServiceRoot 실미러 + create payload | 동일 |

이번 변경의 핵심: CSUS / Superdome 은 iLO 로 처리하지 않는다. adapter hint 가
`csus` / `superdome` 이면 iLO payload(`Oem.Hpe.Privileges`)를 쓰지 않고 generic 으로 남긴다.

### 2.3 Lenovo

| 항목 | IMM2 | XCC1 Purley | XCC1 Whitley / AMD | XCC2 | XCC3 | TSM |
|---|---|---|---|---|---|---|
| Create | **미확인** | 빈 slot **PATCH** (1~12 pre-populated) | Collection POST | Collection POST | Collection POST | Collection POST |
| Update | 미확인 | Slot PATCH | Slot PATCH | Slot PATCH | Slot PATCH | Instance PATCH |
| PasswordChangeRequired | 미확인 | **미제공** | 지원 | 지원 | Resource 에는 존재 | **미지정 시 default true** |
| AccountTypes | 미확인 | 없음 | 없음 | Redfish/SNMP/ManagerConsole/IPMI/WebUI | 동일 | 미확인 |
| Reserved | 미확인 | — | — | — | `HostBootStrap` | ID 1~4 (HostAutoFW/HostAutoOS 등) |
| Password | 미확인 | API 8~20 (UI 문서는 32) | 동일 | API max 255 / UI 8~32 | API max 255 / CLI 8~32 | 8~20 |
| Repository Strategy | `generic_collection_post` | `lenovo_purley_slot_patch` | `lenovo_collection_post` | `lenovo_xcc_accounttypes` | `lenovo_xcc_accounttypes` | `lenovo_collection_post` |
| Family 판정 근거 | adapter hint | **pre-populated 빈 slot 관측** (Manager.Model 이 숫자 없는 XCC 1세대여도 — 2026-11-16, 2026-10-27 회귀 정정) | dynamic members | Manager.Model `… Controller 2` / 숫자 없음 + 동적 목록 · 없으면 hint `xcc2` | Manager.Model `… Controller 3` · 없으면 hint `xcc3` | (TSM 전용 hint 없음 — POST + PCR=false 로 공통) |
| Fixture Evidence | 없음 | 없음 | 실미러 `10_50_11_232` (XCC 1.15) | 없음 | 없음 | 없음 |
| Live Evidence | 없음 | 없음 | 없음 | **2026-08-12 git: 10.50.11.232 FW AFBT58B 5.70 — Case A PROVEN + 2차 Write 0** | 동일 Family 판정 | 없음 |
| Status | `UNVERIFIED` | `PARTIAL` | `PARTIAL` | **`PROVEN` (Case A만)** | `PARTIAL` | `PARTIAL` |
| Remaining Gap | Redfish AccountService 지원 근거 자체가 없음 | Purley 실미러 | Create 실장비 | XCC2 실미러 | XCC3 실미러 | TSM 실미러 + 특수 ID 보호 실측 |

핵심 변경: **Purley 를 Collection POST 로 만들던 것을 빈 slot PATCH 로 바로잡았다.**
판정은 이름이 아니라 관측(pre-populated 빈 slot 존재)으로 한다.
그리고 Lenovo POST 는 처음부터 `PasswordChangeRequired:false` 를 실어 보낸다. TSM 이
미지정 시 `true` 로 만들어 생성 직후 접근이 막히기 때문이다.

### 2.4 Cisco

| 항목 | IMC 3.x | IMC 4.1 / 4.2 / 6.0 | BMC 1.x / 2.0 / 4.0 | UCS X-Series |
|---|---|---|---|---|
| Create | `POST /Accounts/<ID>` (instance) | `POST /Accounts` + body `Id` | `POST /Accounts` (Id 는 BMC 할당) | **미확인** |
| RoleId | `admin` | `admin` | `Administrator` | 미확인 |
| Account Id semantics | numeric slot | numeric slot | username 기반 또는 자동 numeric | 미확인 |
| AccountTypes | — | 6.0 노출 | 노출 | 미확인 |
| PasswordChangeRequired | 세대별 | 6.0 지원 | 4.0 은 생성 후 `true` | 미확인 |
| Password | max 20 (Strong 시 8~14) | 동일 | 8~20 | 미확인 |
| ETag | — | — | 4.0 은 `@odata.etag` 노출, PATCH 예에 `If-Match: *` | 미확인 |
| Repository Strategy | `generic_collection_post` | `cisco_cimc_collection_post_id` | `cisco_bmc_dynamic` | `generic_collection_post` |
| Family 판정 근거 | — | **Roles 어휘에 `admin`** | **Roles 어휘에 `Administrator`** | 근거 없음 → generic |
| Fixture Evidence | 없음 | 실미러 `10_100_15_2` (CIMC v1_6_0) | 없음 | 없음 |
| Live Evidence | 없음 | **2026-08-12 git: 10.100.15.2 CIMC 4.1(2g) — Case A PROVEN + 2차 Write 0 + Roles 어휘로 Family/RoleId 판정 확인** (2026-05-06 Create 201 실측도 유효) | 없음 | 없음 |
| Status | `UNVERIFIED` | **`PROVEN` (Case A만)** / Create 는 2026-05-06 실측 기준 `PARTIAL` | `PARTIAL` | `UNVERIFIED` |
| Remaining Gap | instance POST 실측 | 현 Family 코드로 재실측 | 실미러 + RoleId 실측 | AccountService 계약 자체 |

핵심 변경: **전 Cisco 에 `Administrator→admin` remap + Id 2..15 스캔을 적용하던 것을 끊었다.**
`admin` 은 IMC 의 어휘이고 최신 Cisco BMC 는 `Administrator` 를 쓴다. 이제 RoleId 는
Roles Collection 이 실제로 노출한 값에서 고른다. Id 는 Family 가 요구할 때만 보낸다.

### 2.5 Supermicro

| 항목 | X9 | X10 / X11 / H11 | X12 / H12 | X13·H13 (<01.05) | X13 01.05+ / X14 01.02+ / NVIDIA Superchip 01.04+ |
|---|---|---|---|---|---|
| Redfish 지원 | **공식 범위 밖** | 지원 | 지원 (Reference Guide 적용 시작) | 지원 | 지원 |
| Create | 미확인 | `/AccountService/Accounts` POST | 동일 | 동일 | 최신 매뉴얼은 `/AccountService` POST 도 문서화 |
| AccountTypes | 미확인 | 공유 계정 | 세부 확인 필요 | 분리 전 | **IPMI / Redfish 분리** — Redfish 필요 |
| RoleId | 미확인 | Administrator/Operator/ReadOnly | 동일 | 동일 | 동일 |
| Repository Strategy | `generic_collection_post` | `supermicro_legacy` | `supermicro_legacy` | `supermicro_legacy` | `supermicro_split_account` |
| Family 판정 근거 | — | — | — | Firmware < 경계 | **AccountTypes 관측 또는 SupportedAccountTypes 또는 Firmware ≥ 경계** |
| Fixture Evidence | 없음 | fixture `supermicro_x10` (mock) | fixture `supermicro_x12` (mock) | 없음 | fixture `supermicro_x14` (mock) |
| Live Evidence | 없음 (lab 0대) | 없음 | 없음 | 없음 | 없음 |
| Status | `UNVERIFIED` | `UNVERIFIED` | `PARTIAL` | `UNVERIFIED` | `PARTIAL` |
| Remaining Gap | Redfish 지원 여부 자체 | 실미러 | 실미러 | Firmware 경계 실측 | `/AccountService` POST 가 어느 Firmware 부터인지 |

**Create URI 는 아직 `/AccountService/Accounts` 를 쓴다.** 최신 매뉴얼의 `/AccountService` POST 는
어느 Firmware 부터 실제 동작하는지 확인하지 못했다. 두 경로에 순차로 써 보는 것은 금지된
Write fallback 이다. 실미러 확보 후 Family 를 하나 더 나눈다.

### 2.6 Fujitsu iRMC

| 항목 | S4 | S5 | S6 |
|---|---|---|---|
| Redfish API 존재 | 공식 확인 | 공식 확인 (3.39~3.60P) | 공식 확인 (1.15S / 2.72S) |
| Create Method | **미확보** | **미확보** | **미확보** |
| Redfish Role | `RedfishAdmin` / `RedfishOperator` / `RedfishReadOnly` 체계 존재 | 동일 | 동일 |
| Repository Strategy | `generic_collection_post` (현행 유지) | 동일 | 동일 |
| Fixture Evidence | 없음 | fixture `fujitsu_irmc_s5` (mock) | fixture `fujitsu_irmc_s6` (mock) |
| Status | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` |
| Remaining Gap | iRMC RESTful API Specification pack 원문 + 실미러 | 동일 | 동일 |

`RoleId=Administrator` 가 Fujitsu 에서 맞는지 확정되지 않았다. 다만 이번 변경으로 RoleId 는
Roles Collection 에 `Administrator` 가 없고 `RedfishAdmin` 이 있으면 **대소문자 무시 일치**로
넘어가지는 않는다(다른 이름이므로). 이 부분은 실미러 확보 후 Family 를 추가해야 한다.

### 2.7 Huawei iBMC

| 항목 | V3 / V5 / Kunpeng / MM920·MM921 |
|---|---|
| Create | `POST /redfish/v1/AccountService/Accounts` — 2019 MM920 문서와 2025 Kunpeng 문서 양쪽 공식 |
| Update | ManagerAccount PATCH (`UserName/Password/RoleId/Locked/Enabled`) |
| RoleId | Roles Collection + PrivilegeMap 제공 → **실제 값에서 선택** |
| AccountTypes | 표준 속성으로 확인되지 않음 → **보내지 않는다** |
| PasswordChangeRequired | 표준 속성으로 확인되지 않음 → **보내지 않는다** (종전 retry payload 제거) |
| Password | Complexity 활성 시 8~20, username/역순 금지, weak dictionary |
| Lockout | 5회 연속 실패 → 5분 잠금 |
| Redfish Login Interface | **Local User 별로 Redfish 가 빠져 있을 수 있다** |
| Repository Strategy | `huawei_ibmc` |
| Fixture Evidence | fixture `huawei_ibmc_v2` (mock) |
| Status | `PARTIAL` |
| Remaining Gap | **Redfish Login Interface 를 Redfish API 로 켜는 OEM field/action 미확보** + 실미러 |

Login Interface 는 이번에 구현하지 않았다. 그것을 켜는 OEM 필드나 Action 이 공식 자료에서
확인되지 않았다. 추측해서 쓰는 것은 금지 사항이다. 대신 계정이 있고 권한도 맞는데 인증이
안 되는 상태가 `post_write_state` 와 `errors[].detail` 로 드러나므로 운영자가 이 원인을
식별할 수 있다.

### 2.8 Inspur

| 항목 | M5 | M6 / ISBMC Whitley | M7 |
|---|---|---|---|
| Create | 미확인 | `POST /AccountService/Accounts`, `Id` optional (생략 시 자동 할당) | 미확인 |
| Update | 미확인 | `PATCH /AccountService/Accounts/<id>` + **`If-Match` 공식 요구** | 미확인 |
| Write 성공 계약 | 미확인 | **HTTP 200 + `Oem.Public.Status == 0`** | 미확인 |
| RoleId | 미확인 | Administrator/Operator/User/Noaccess/OEM1~4 | 미확인 |
| Password | 미확인 | max 20, MinPasswordLength **고객이 8~16 으로 설정 가능** | 미확인 |
| Lockout | 미확인 | Threshold 0~5 / Duration 5~60분 | 미확인 |
| Repository Strategy | `generic_collection_post` | `inspur_m6` | `generic_collection_post` |
| Fixture Evidence | 없음 | fixture `inspur_isbmc` (mock) | 없음 |
| Status | `UNVERIFIED` | `PARTIAL` | `UNVERIFIED` |
| Remaining Gap | 공식 자료 | 실미러 + ETag 실동작 + Status error code 전체 목록 | 공식 자료 |

### 2.9 Quanta / QCT

| 항목 | Legacy (Redfish v1.1) | Modern (Redfish v1.11) | Inhouse OpenBMC (Xeon 6) |
|---|---|---|---|
| Redfish 존재 | 공식 확인 | 공식 확인 | 공식 확인 |
| Create / Update | **미확인** | **미확인** | upstream bmcweb 구조가 후보이나 QCT Firmware 미확인 |
| AccountTypes | 미확인 | 미확인 | upstream 에는 존재 |
| Repository Strategy | `generic_collection_post` | `generic_collection_post` | `generic_collection_post` |
| Fixture Evidence | 없음 | 없음 | fixture `quanta_qct` (mock) |
| Status | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` |
| Remaining Gap | 실미러 3 Family 전부 | 동일 | upstream ≠ QCT custom build |

---

## 3. 요약 매트릭스

| Vendor | Family 수 | PROVEN Case A | PROVEN Case B (Repair) | PARTIAL | UNVERIFIED | HOLD |
|---|---:|---:|---:|---:|---:|---:|
| Dell | 3 | **1 (iDRAC9)** | 0 | 0 | 2 (iDRAC7/8, iDRAC10) | 0 |
| HPE | 4 | **1 (iLO5+)** | 0 | 1 (iLO4) | 2 (CSUS, Superdome) | 0 |
| Lenovo | 6 | **1 (XCC2/3)** | **1 (XCC2/3)** | 4 | 1 (IMM2) | 0 |
| Cisco | 4 | **1 (IMC 4.x/6.0)** | 0 | 1 | 2 (IMC 3.x, X-Series) | 0 |
| Supermicro | 5 | 0 | 0 | 2 | 3 | 0 |
| Fujitsu | 3 | 0 | 0 | 0 | 3 | 0 |
| Huawei | 1 | 0 | 0 | 1 | 0 | 0 |
| Inspur | 3 | 0 | 0 | 1 (M6) | 2 | 0 |
| Quanta | 3 | 0 | 0 | 0 | 3 | 0 |
| **합계** | **32** | **4** | **1** | **9** | **18** | **0** |

- **Case A** = 표준 인증 성공 → Account Write 0 → 표준 계정 수집. 4 Family 가 1·2차 실행
  모두에서 증명됐다 (검증된 Model + Firmware 범위 한정).
- **Case B (Repair)** = 표준 401 → recovery 인증 → 계정 존재 확인 → `patch_existing` →
  계정 재조회 → **표준 자격 재인증 성공** → 표준 계정 수집. `lenovo_xcc_accounttypes`
  1건이 실장비에서 완주했다 (2026-08-12). Repair 가 실장비로 증명된 것은 이번이 처음이다.
- **Dell HOLD 는 CLOSED.** 종전 HOLD 사유는 "표준 비밀번호가 iDRAC Security Strengthen
  Policy 에 거부됨" 이었다. 회전된 비밀번호로 1·2차 모두 표준 인증 성공 + Write 0 이므로
  더는 막혀 있지 않다. 다만 거부 사실 자체는 유효한 관측이다. 회전 전 값은 읽을 수
  있는 규칙(길이/문자군/Regex)을 전부 만족하는데도 거부됐다. 활성 제약은
  `Security.1.MinimumPasswordScore` 뿐이었다. 값에 따라 재발할 수 있으므로
  "Dell 은 선언된 규칙만으로 수용 여부를 판단할 수 없다" 는 계약으로 남긴다.

**Account Create 경로는 여전히 어느 Family 에서도 실장비로 증명되지 않았다.**
git 4대 모두 표준 계정이 이미 존재해 `presence=absent` 조건 자체가 성립하지 않았다.
그 조건을 만들려면 운영 계정을 지워야 해서 손대지 않았다 (사용자 지시 §9).

---

## 4. Global Standard Password 정책 — 구조적 충돌

9 Vendor 조사에서 확인된 길이 상한(가장 보수적):

| 근거 | 상한 / 하한 |
|---|---|
| Dell iDRAC7/8, iDRAC9 <4.00 | max 20 |
| Lenovo XCC Redfish AccountService, TSM | max 20 |
| Cisco IMC | max 20 |
| Huawei iBMC (Complexity 활성) | 8~20 |
| Inspur M6 | max 20 |
| **Cisco IMC Strong Password Policy 활성** | **8~14** |
| **Inspur MinPasswordLength (고객 설정 가능)** | **최대 16 까지 상향 가능** |

[WARN] **교집합이 빌 수 있다.** 어떤 사이트가 Cisco Strong Password(max 14)와 Inspur
MinPasswordLength=16 을 동시에 운영하면, 두 정책을 모두 만족하는 단일 비밀번호가
수학적으로 존재하지 않는다. 이것은 제품 Contract 의 문제다. 코드 버그가 아니다.

현재 Dell HOLD 도 같은 종류다. 코드가 아니라 값과 정책의 문제다.

### 이번 cycle 의 처리 (사용자 결정 2026-08-12)

**차단하지 않는다.** 장비가 선언한 `MinPasswordLength` / `MaxPasswordLength` 를 읽어
진단(`diagnosis.details.account_service.policy`)에 남긴다. 범위를 벗어나면 경고를
`errors[]` 에 적은 뒤 쓰기는 그대로 시도한다. 거부되면 장비가 준 문장
(`write_response_info`, `vendor_status`)으로 원인을 확정한다.

비밀번호 길이 자체는 남기지 않는다. `within_declared_bounds` boolean 만 기록한다.

### 남은 아키텍처 결정 (운영/아키텍트 몫)

```text
A. 지원 대상 BMC Password Policy 범위를 제품 사전조건으로 정의
B. 비호환을 감지하면 운영 승인 하에서만 BMC Policy 를 표준화
C. "모든 Vendor 동일 Password 1개" 정책 자체를 재검토
D. 상호 모순되는 Security Policy 조합을 지원 Matrix 에서 명시적으로 제외
```

---

## 5. Lockout 안전성

| Vendor | 공식 기준 | 종전 코드 | 현재 코드 |
|---|---|---|---|
| Dell iDRAC10 | IP Blocking FailCount 3 / FailWindow 60s / Penalty 60s | 후보 간 5초 | **401 일 때 65초**(설정 가능), transport 오류는 5초 |
| HPE iLO | Threshold 3 | 동일 | 동일 |
| Lenovo XCC | 기본 5회 / 60분 | 동일 | 동일 |
| Huawei iBMC | 5회 → 5분 잠금 | 동일 | 동일 |
| Inspur | Retry 0~5 / Lock 5~60분 | 동일 | 동일 |

쓰기측 축소 (사용자 결정 = "쓰기측 축소 + 후보루프 backoff 확대"):

| 항목 | 종전 | 현재 |
|---|---|---|
| Dell 빈 슬롯 생성 시도 | 최대 3 슬롯 | **1 슬롯** |
| 표준 계정 실패 인증 / run (Dell 생성 경로) | **최대 9회 / 약 20초** | **최대 3회** |
| POST 생성 요청 수 (근거 있는 Family) | 최대 3회 (payload 사다리) | **1회** |
| POST 생성 요청 수 (UNVERIFIED Family) | 최대 3회 | **최대 2회** (현행 유지 결정 — HPE 전용 3차만 제거) |
| username 별 실패 인증 카운터 | 없음 | `diagnosis.details.account_service.auth_budget` |

BMC 의 Lockout 정책 자체는 변경하지 않는다. 읽기만 한다.

---

## 6. 현재 Repository Strategy 구현 지점

| 대상 | 위치 |
|---|---|
| Capability Discovery | `redfish_gather.account_service_discover()` |
| 존재 3-상태 판정 | `redfish_gather.account_presence()` |
| Family 표 | `redfish_gather._ACCOUNT_FAMILIES` |
| Family 선택 | `redfish_gather.resolve_account_family()` |
| RoleId 선택 | `redfish_gather.choose_role_id()` |
| 쓰기 성공 해석 | `redfish_gather.interpret_write_response()` |
| 생성 payload | `redfish_gather.build_create_payload()` |
| 쓰기 후 상태 확인 | `redfish_gather._confirm_account_state()` |
| 쓰기 대상 URI | `redfish_gather._accounts_write_uri()` (discovery 결과) |
| 진입 게이트 | `redfish-gather/site.yml:148-153` (401 전용, 변경 없음) |
| 성공 판정 게이트 | `redfish-gather/tasks/account_service.yml` (`verification == 'verified'`) |
| 진단 노출 | `diagnosis.details.account_service` (Additive — envelope 13 필드 불변) |

---

## 7. 남은 Gap (우선순위)

### 운영 결정 필요

1. **Dell 표준 비밀번호 vs iDRAC Security Strengthen Policy** (E-6) — 해소 전까지 Dell 은 `HOLD`
2. **Global Password 정책 교집합** — §4 의 A/B/C/D 중 선택
3. `_rf_account_service_dryrun` 항구 정책 여부 (현재 운영 Job 에 override 없음 = 게이트가 열리면 실쓰기)

### 실장비 / 실미러 필요 (lab 부재)

| 우선순위 | 대상 | 얻는 것 |
|---|---|---|
| HIGH | Dell iDRAC7/8 read-only 미러 | Manager-scoped AccountService 실증 |
| HIGH | Lenovo Purley 미러 | pre-populated slot 판정 실증 |
| HIGH | Cisco 최신 BMC 미러 | `Administrator` RoleId + Id semantics 실증 |
| MED | Supermicro X13/X14 미러 (분리 전후 Firmware 각 1) | 계정 분리 경계 실증 |
| MED | Inspur M6 미러 + ETag/If-Match 실동작 | OEM Status / ETag 계약 실증 |
| MED | Huawei 미러 + Redfish Login Interface 상태 | Login Interface 복구 방법 |
| LOW | Fujitsu API Pack 원문 | S4/S5/S6 Create 계약 |
| LOW | Quanta 3 Family 미러 | Legacy/Modern/OpenBMC 구분 |

### 코드에 남긴 것 (의도적)

- UNVERIFIED Family 의 generic POST 경로와 400/405 retry — **현행 유지** (사용자 결정)
- Huawei Redfish Login Interface 자동 활성화 — OEM 계약 미확보로 미구현
- Supermicro `/AccountService` POST — Firmware 경계 미확보로 미도입
- `empty_accounts` → `CREDENTIAL_SET_UNAVAILABLE` (audit H-5) — Portal 사용자 문장이
  5번→4번으로 바뀌므로 Consumer 결정 필요. 보고만 하고 변경하지 않았다.
