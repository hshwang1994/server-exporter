# Redfish Account Write Contract — 구현 계획 (2026-08-12, rev.2)

> **입력**: 9 Vendor Account Write Contract Delta Research 9건 (2026-08-12)
> + AS-IS 전수조사(정리됨)
> + Vendor × Family 매트릭스
> + 현재 HEAD(`26394474`) 및 워킹트리 코드 실측
>
> **rev.2 변경 사유**: 사용자 검토 지시 10건 반영. 기존 설계 방향은 유지하고 해당 항목만 수정했다.
> rev.1 → rev.2 수정 요약과 자체 모순 검사 결과는 **§13** 에 있다.
>
> **상태**: 계획 단계. **이 문서 작성 시점의 코드 변경 0건** — 수행한 것은
> Read / Grep / `git diff` / `pytest --collect-only` 뿐이다.
> 실행 순서는 §4(Phases)와 §11(Execution Checklist)을 따른다. **P0 이 시작 지점이다.**

---

## Context — 왜 이 작업을 하는가

2026-08-12 에 9개 Vendor 의 **Account Write Contract Delta 조사**가 완료됐다. 조사가 공통으로
지적한 것은 하나다: **Vendor 이름 하나에 Write 규칙 하나를 부여하면 안 된다.** 같은 Vendor 안에서도
Create Method, RoleId 어휘, Account ID 의미, Property 쓰기 가능 여부, 성공 판정이 Family/Firmware 별로 갈린다.

직전 cycle(`5e411bc3` + 현재 워킹트리)에서 저장소는 이미 **Capability Discovery + Family Strategy**
구조를 도입했고, 실장비 4대에서 Case A / Case B 를 증명했다. 따라서 이번 작업은 새 프레임워크 도입이
아니라 **이미 있는 Family 표와 Write 경로를 9개 조사 결과와 대조해 남은 충돌·과일반화·미구현을
좁히는 것**이다.

변경하지 않는 계약:

```text
Global Standard Gathering Account = 전역 1개 (vault/common/redfish/standard.yml, role: primary)
Recovery Account                  = Location × Vendor (vault/<loc>/redfish/<vendor>.yml, role: recovery)
Recovery 는 최종 Gathering 에 절대 사용하지 않는다 — Standard 를 Create/Repair 하는 수단일 뿐이다.
최종 Gathering 은 반드시 Standard Account 로 수행한다.

성공 = Standard exists AND enabled AND role/privilege correct AND Redfish access correct
       AND Standard authenticates AND required resources accessible
       AND final Gathering uses Standard AND Gathering succeeds

2차 실행 = Standard Auth 성공 → Account Write 0 → Standard Gathering 성공
```

---

# 1. Current State Summary

## 1.1 실측 기준

| 항목 | 값 |
|---|---|
| Branch / HEAD | `main` / `26394474` + 워킹트리 미커밋 (계정 관련 3파일 + 신규 테스트/Evidence) |
| Redfish 라이브러리 | `redfish-gather/library/redfish_gather.py` **6,498줄** |
| Redfish Adapter | `adapters/redfish/*.yml` **31개** |
| pytest 수집 | **2,860건**, 계정 관련 **257건** |
| 계정 unit test | `tests/unit/` 9파일 + seam(`account_seam.py`). 최대: `test_redfish_standard_recovery_contract.py`(47) / `test_account_family_and_write_contract.py`(40) / `test_account_reconcile_entry_gate.py`(39) |
| 계정 replay test | `tests/integration/test_account_reconcile_replay.py`(43) + `account_replay.py` — **읽기 단계만** 재생 |
| 실장비 미러 | `tests/reference/redfish/**` — Dell 5 / HPE 1 / Lenovo 1 / Cisco 1. **iDRAC10 미러는 없다**(`10_100_15_34` 는 iDRAC9) |
| mock account fixture | `tests/fixtures/redfish/<vendor>/account_service.json` **9건 — 전부 lab 부재 vendor 용 web-sources mock** |

## 1.2 이미 구현되어 있는 것 (조사 결과와 **일치**)

정본은 `redfish-gather/library/redfish_gather.py` (별도 표기 없으면).

| # | 구현 | 위치 | 대응 조사 |
|---|---|---|---|
| A1 | **Capability Discovery(읽기 전용)** — ServiceRoot→AccountService→Accounts→Members, Roles, Manager Firmware/Model, Password/Lockout 정책, SupportedAccountTypes | `account_service_discover()` :4895 | 9문서 공통 |
| A2 | **열거 3-상태 + 존재 4-상태**, **UNKNOWN Write 0** | :4790, :4795, `account_presence()` :5034, 소비 :5787-5802 | 전 문서 |
| A3 | **Family Strategy Matrix + 결정적 선택** | :5061, :5076, `resolve_account_family()` :5180 | 전 문서 |
| A4 | **RoleId 를 장비 Roles Collection 에서 선택** (Cisco 전역 remap 제거) | `choose_role_id()` :5327 | 04 §26, 07 §8, 08 §10 |
| A5 | **쓰기 URI 를 discovery 결과에서** | `_accounts_write_uri()` :5369 | 05 §34, 02 §6 |
| A6 | **HTTP 2xx ≠ 성공** — 본문 read-only 거부 + Inspur `Oem.Public.Status` | `interpret_write_response()` :5347 | 01 §13, 02 §10, 03 §18, 06 §7 |
| A7 | **쓰기 후 계정 재조회** | `_confirm_account_state()` :5380 | 04 §30, 05 §38, 07 §36 |
| A8 | **모든 쓰기 경로가 Fresh Standard Auth 수행** | :5657, :5976/:6182/:6279 | 전 문서 |
| A9 | **Ansible 게이트 = `verification == 'verified'`** | `tasks/account_service.yml:204-207` | audit H-1/D-3 |
| A10 | **`Locked` 는 실제 잠김일 때만** | :5863-5864 | 01 §9, 02 §8, 03 §14, 05 §20, 06 §16 |
| A11 | **`PasswordChangeRequired` 는 장비가 `true` 로 노출할 때만** | :5860-5861 | 01 §10, 06 §17 (G-09 로 추가 보강) |
| A12 | **If-Match 는 Inspur M6 Repair PATCH 에서만**, 412 시 ETag 재획득 후 **동일 URI·동일 payload 1회만** 재시도. **Create POST 에는 걸리지 않는다 — 이것이 M6 공식 계약과 정확히 일치한다** | `etag_required` :5135 / Repair :5865-5871 / 412 :5891-5900 / Create 는 미적용 :6160,:6221 | 06 §5·§11·§29 |
| A13 | **Dell 세대는 Firmware major 로 판정** (adapter hint 단독 결정 제거) | :5220-5233 | 02 §18 — R760 오분류 **해소됨** |
| A14 | **Dell iDRAC10 예약 slot {1,2} / iDRAC9 {1}** | :5080-5083 | 02 §16/§17 |
| A15 | **Dell 생성 시도 3슬롯 → 1슬롯** | :6156-6163 | 02 §19 |
| A16 | **재인증 간격을 장비 선언 패널티에서 산출** | `account_verify_delays()` :468, `_oem_num` :4848 | 01 §12 |
| A17 | **`--check` 실쓰기 결함 해소** | :6355-6363 | audit H-2 |
| A18 | **동일 username 다중 slot → `ambiguous`, Write 0** | :5774-5785 | 전 문서 |
| A19 | **Password 정책은 읽기만** (`within_declared_bounds`, 길이 미기록) | :5729-5755 | 사용자 결정 |
| A20 | **HPE CSUS/Superdome 을 iLO 로 처리하지 않음** | :5276-5278 | 01 §16/§21 |
| A21 | **X-Series / IMM2 / X9 / M5·M7 을 generic 유지** | :5257, :5269, :5305, :5316 | 04 §24, 03 §4, 05 §32, 06 §24 |
| A22 | **Recovery 로 수집하는 경로 부재** | `site.yml:134`, `:198` | 사용자 핵심 Contract |
| A23 | **Standard 는 전역 상수 경로 1개** | `module_utils/credential_common.py:54-55` | 사용자 핵심 Contract |
| A24 | **실장비 미러 replay 회귀** | `tests/integration/test_account_reconcile_replay.py` | audit D-8 |
| A25 | **정상 재실행 Write 0** | `site.yml:148-153`, `collect_standard.yml:126-132` | Second Run Write 0 |
| A26 | **HPE iLO Password 단독 PATCH + drift 만 후속 PATCH** | :5124, :5878-5886, :5945-5963 | 01 §15 — **동작 유지, Evidence 표기만 교정**(G-01) |
| A27 | **Cisco 명시 Id 범위** `id_range:(2,16)` = half-open → 후보 **2..15**, 진단 문자열도 `2-15`. **자체 정합** | :5087, :6134-6144 | 04 §5 (ID 1 예약, 1–15) |

## 1.3 실장비 검증 현황

| Vendor | 장비 | Firmware | 증명된 것 |
|---|---|---|---|
| Lenovo XCC | 10.50.11.232 | `AFBT58B 5.70` | **Case A + Case B(Repair 완주) + 2차 Write 0** |
| HPE iLO6 | 10.50.11.231 (DL380 Gen11) | `iLO 6 v1.73` | Case A + Password 단독 PATCH 통제 실험 |
| Cisco CIMC | 10.100.15.2 | `4.1(2g)` | Case A + 2차 Write 0 + Roles 어휘 Family 판정 |
| Dell iDRAC9 | 10.100.15.34 (R760) | `7.10.70.00` | Case A + 2차 Write 0 (HOLD CLOSED) |

**Create 경로는 어떤 Family 에서도 실장비 미증명.** Supermicro / Huawei / Inspur / Fujitsu / Quanta 는 실장비 0대.

---

# 2. Gap Matrix

등급: `CONFLICT` 코드가 조사 계약과 어긋남 / `PARTIAL` 부분 구현 / `MISSING` 미구현 / `REPRESENTATION` 동작은 맞고 표현이 부족 / `LABEL` Evidence 표기 과도

| ID | 항목 | 현재 구현 | 조사 Contract | 차이 | 수정 | 위험도 | Evidence |
|---|---|---|---|---|---|---|---|
| **G-01** | HPE Evidence 표기 과도 (`LABEL`) | `hpe_ilo5plus` 하나가 iLO5/6/7 전 Firmware 를 덮고 `evidence:'proven'` (:5124) | 01 §1-4/§4.1/§14/§17: LIVE-PROVEN 은 **iLO6 1.73 뿐**. Advisory `a00159600en_us` = iLO6 1.73/1.74 + iLO7 1.19/1.20. **iLO6 1.75+/iLO7 1.21+ 는 수정판**. iLO5 근거 없음 | **동작은 유지해도 된다**(사용자 확정). 문제는 `proven` 라벨이 전 Firmware 로 번진 것 | **YES — Family 분할 없이 Firmware Evidence metadata 분리** | **HIGH** | LIVE-PROVEN(1.73) / OFFICIAL ADVISORY(1.74,1.19,1.20) / 근거없음(iLO5,1.75+,1.21+) |
| **G-02** | UNVERIFIED Family 의 Write fallback 사다리 (`CONFLICT`) | `generic_collection_post.legacy_post_retry=True` → POST 400/405 시 `PasswordChangeRequired:false` 추가 **2차 POST** (:6232-6248) | 05 §19/§39-D, 06 §17/§31-F, 07 §17/§40-E, 08 §17/§32-C, 09 §19/§45-D 가 **모두 금지**. 사용자 지시 F | 대상: Fujitsu, Quanta, Cisco IMC3.x·X-Series, Lenovo IMM2, Supermicro X9, Inspur M5/M7, HPE RMC, 미식별 vendor | **YES (제거)** | **HIGH** | 5문서 OFFICIAL + 사용자 확정(D-1) |
| **G-03** | Dell 본문 거부 판정 범위 (`CONFLICT`) | `rejected_patch_properties()` 는 read-only 문장 + 4종 MessageId 의 `MessageArgs` 만 (:519-563) | 02 §11/§12/§21: `SYS474` 는 `MessageArgs=[]`, `RelatedProperties=["#/Password"]`, `Severity=Warning` | 정책 거부에서 `write_accepted=True` 오판. Fresh Auth 가 실패는 잡지만 **원인 귀속이 틀림** | **YES** | **HIGH** | LIVE-PROVEN + Dell Error Message Guide |
| **G-04** | Create URI 축 부재 (`MISSING`) | `_accounts_write_uri()` 는 항상 `accounts_uri` (:5369) | 05 §1/§9/§34: 최신 Supermicro 공식 Create = **`POST /redfish/v1/AccountService`**. 04 §4.2: CIMC 3.x = **`POST /Accounts/<ID>`** | Create URI 종류를 표현할 수 없음. **두 URI 를 fallback 으로 시도하는 것은 절대 금지**이므로 Family 가 하나를 고르는 축이 필요 | **YES** — Supermicro 는 §3.5 결정 규칙으로 **조건부 실적용** | **HIGH** | OFFICIAL |
| **G-05** | Huawei Redfish Login Interface (`MISSING`) | 읽지 않음 | 07 §10/§11/§12/§40-G: Local User 별 `Redfish` Interface 가 꺼져 있으면 계정·권한·비밀번호가 정상이어도 인증 실패. **AccountTypes 보다 중요한 Huawei 고유 축** | Password drift 로 오진 | **YES (읽기·진단만. repair payload 근거 없음 → 구현 안 함)** | **MED-HIGH** | OFFICIAL(존재) / repair UNVERIFIED |
| **G-06** | Lenovo XCC2 ↔ XCC3 Family 혼합 (`CONFLICT`) | `lenovo_xcc_accounttypes` 하나가 XCC2·XCC3 를 덮고 `password_change_required:False` 를 **양쪽 Create 에 전송** (:5105) | 03 §11.3/§15: XCC3 공식 Create/Update Property 목록에 `PasswordChangeRequired` **없음**. XCC2 는 지원 | XCC3 Create 가 미지원 속성 포함 | **YES (Family 분할)** | **MED** | OFFICIAL |
| **G-07** | 보호 계정 판정 축이 틀림 (`CONFLICT`) | `reserved_slot_ids: ('HostBootStrap',)` — **slot id 문자열 매칭**이고 `slot_patch` 경로에서만 소비(:6119). `lenovo_xcc_accounttypes` 는 `collection_post` 라 **죽은 값**. 열거/존재/ambiguous 층에는 없음 | 03 §11.1/§24 + **실측**: `HostBootstrapAccount` 는 DMTF 표준 ManagerAccount Property(`schema/redfish_dmtf_2026.1/ManagerAccount.v1_14_1.json:323`)이고, **실미러 `tests/reference/redfish/lenovo/10_50_11_232/redfish_v1_accountservice_accounts_{1,2,3}.json` 에 `"HostBootstrapAccount": false` 로 실제 존재**한다. 즉 XCC3 전용 개념이 아니다 | 보호가 실제로 걸리지 않고, 축(slot id)도 틀렸다 | **YES — Resource Property 기반 `normal`/`protected` 분류로 교체** | **MED-HIGH** | OFFICIAL + **실미러 실측** |
| **G-08** | Family 별 Property 쓰기 계약이 데이터가 아님 (`MISSING`) | `Locked`/`PCR`/`AccountTypes` 판단이 provision 본문 inline 조건에 분산 (:5853-5864) | 사용자 지시 A + 7 | 표현 수단 부재 → 신규 Family 마다 본문 조건이 늘어남 | **YES** (`props` 필드) | **MED** | 사용자 지시 |
| **G-09** | read-only Family 에도 `PasswordChangeRequired` 전송 (`CONFLICT`) | 장비가 `true` 로 노출하면 무조건 body 에 추가 (:5860) | 01 §10(HPE read-only), 04 §10.3(Cisco BMC 1.1 existing read-only), 09 §19(upstream OpenBMC PATCH 미지원), 02 §9, 05 §19, 07 §17, 08 §17 | 해당 Family 에서 PATCH 전체 거부 | **YES — `props` 로 gate. 처음부터 보내지 않는다.** ~~droppable 목록 추가~~ **철회**(사용자 지시 3) | **MED** | OFFICIAL ×6 |
| **G-10** | Repair PATCH 가 drift 없는 `Enabled`/`RoleId` 도 항상 전송 (`PARTIAL`) | `body_full` 고정 (:5843-5850) | 02 §7.2/§20, 03 §17, 04 §8/§29, 05 §37, 06 §30, 07 §16/§38 | 불필요 Write 표면 + read-only 거부 유발 | **YES** — 단 **Lenovo XCC 반례 보존**(password 단독 PATCH 시 권한 cache 손상, 사이트 실측) → `full_body_patch` opt-out | **MED** | 권장=6문서 / 반례=LIVE-PROVEN |
| **G-11** | AccountTypes 를 쓰는 Family 에서만 검증 (`PARTIAL`) | `_confirm_account_state()` 는 `family.account_types` 있을 때만 비교(:5417). 존재 판정은 username 만 | 01 §11(HPE verify-only), 04 §16, 05 §35(`AccountTypes=["IPMI"]` 면 Redfish 표준계정으로 healthy 아님) | 쓰지 않는 Family 는 Redfish 접근권을 검증조차 안 함 | **YES** (`account_types_required` 를 write 축과 분리) | **MED** | OFFICIAL ×3 |
| **G-12** | Global Password 정책 충돌의 명시 상태 부재 (`MISSING`) | `within_declared_bounds` + 경고 (:5731-5755) | 사용자 지시 E/8 + 04 §21 + 06 §20 | 기계판독 신호 없음 | **YES — 진단만.** 차단·완화·자동회전 **없음** | **MED** | OFFICIAL ×2 |
| **G-13** | Auth Budget 기록만, 집행 없음 (`PARTIAL`) | 카운트만 (:5650) | 02 §22/§23(`AccountLockoutThreshold=0` 이어도 Dell IP Blocking 별도), 03 §22, 04 §22, 06 §21, 07 §25-26 | 상한 초과해도 안 멈춤 | **YES** (**retry 증가 금지**, 초과 시 중단 + 진단) | **MED** | OFFICIAL ×5 |
| **G-14** | Cisco IMC 3.x Family 부재 (`MISSING`) | generic 으로 접힘 (:5257) | 04 §4.2/§25.1: `POST /Accounts/<ID>` instance POST + `admin` | G-04 축이 생기면 데이터 추가 | **YES** (G-04 이후) | **LOW-MED** | OFFICIAL |
| **G-15** | Quanta 단일 Family (`LABEL`) | `generic_collection_post` 1개 | 09 §44/§50-2: Legacy v1.1 / Modern v1.11 / Inhouse OpenBMC **3분할**. AST2600 만으로 OpenBMC 판정 금지. QCT Inhouse ≠ upstream master | 동작 변화 없음, 경계·근거 미기록 | **YES** (데이터/Matrix, 동작 동일) | **LOW-MED** | QCT-OFFICIAL |
| **G-16** | StrictAccountTypes 위험 | Quanta 계열에 AccountTypes **미전송**(안전) | 09 §9/§10: upstream 은 `Redfish`+`WebUI` 결합. 한쪽만 보내면 `StrictAccountTypes` 오류 | 현재 안전. 향후 `["Redfish"]` 추가 시 즉시 결함 | **NO (금지 규칙을 테스트로 고정)** | **LOW** | UPSTREAM-OFFICIAL |
| **G-17** | 미지원 RoleId 를 조용히 전송 (`PARTIAL`) | `choose_role_id()` 마지막에 `mapped or target_role` (:5344) | 08 §9/§10/§29: Fujitsu `RedfishAdmin` ↔ `ManagerAccount.RoleId` literal 혼동 금지 | 사실이 진단에 안 남음 | **YES (진단만)** | **LOW** | OFFICIAL |
| **G-18** | HTTPBasicAuth / AuthMethods 미수집 (`MISSING`) | 없음 | 02 §24(iDRAC9 7.30.10.50+/iDRAC10 1.30.10.50+ 기본 `Unadvertised`), 03 §23(XCC3), 09 §23 | `Disabled` 를 잘못된 비밀번호로 오진 가능 (client 는 이미 선제 `Authorization` 전송이라 `Unadvertised` 자체는 호환) | **YES (읽기·진단만. 자동 enable 금지)** | **LOW** | OFFICIAL ×3 |
| **G-19** | Supermicro NVIDIA Superchip 경계 미모델 (`MISSING`) | `x13`/`x14` hint 만 분기 (:5299) | 05 §31: Superchip **BMC FW 01.04.xx+** 도 분리 경계 | `supermicro_ars` 계열이 legacy 로 접힘 | **YES** | **LOW** | OFFICIAL |
| **G-20** | Lenovo Purley 판정 휴리스틱 오탐 여지 + hint 우선순위 역전 (`PARTIAL`) | `_has_prepopulated_slots()`(:5156) + `'xcc3'/'xcc2' in hint` 를 **capability 보다 먼저** 검사(:5262) | 03 §7/§8/§9: **Purley 만** empty-slot PATCH. Whitley/AMD 는 POST. 그리고 Cisco 분기는 capability-first 인데 Lenovo 만 hint-first (NEXT_ACTIONS PWC-7) | Whitley 오라우팅 가능 + Vendor 간 계약 불일치 | **YES** (capability-first 로 정렬 + 부정 신호) | **MED** | OFFICIAL |
| **G-21** | 죽은 `_ACCOUNT_CREATE_STRATEGY` (`REPRESENTATION`) | 소비자 0건 (:4748-4769) | audit L-1 | Family 표와 **모순되는** vendor→method 표 병존 (`cisco → post_id_role_remap` 무조건) | **YES (제거)** | **LOW** | 저장소 실측 |
| **G-22** | ETag 계약이 Family 단위 boolean (`REPRESENTATION`) | `etag_required: True/False` 하나. 소비는 Repair 경로에만 (:5866, :5891) → **현재 동작은 M6 공식 계약과 정확히 일치** | 06 §5/§11/§29: Create = **POST Collection (If-Match 없음)**, Repair = **PATCH Instance + GET ETag → If-Match** | **동작 결함 없음.** 이름이 `etag_required` 라 Create 에도 적용해야 하는 것처럼 읽힌다 | **YES — Operation 단위 표현으로 교체 (동작 변화 0)** | **LOW** | OFFICIAL |
| **G-23** | ~~Cisco id_range off-by-one~~ | ~~`(2,16)` → 2..15~~ | — | **삭제.** 실측 결과 half-open 규약이고 진단 문자열(`id_range={lo}-{hi-1}`)도 `2-15` 로 정확하다. Cisco 문서(ID 1 예약, 1–15)와 정합 | **NO — 근거 없는 수정 금지** | — | 저장소 실측 (§1.2 A27) |
| **G-24** | `isolated_write_patch` 가 defaults 에 없음 (`REPRESENTATION`) | `hpe_ilo5plus` 에만 존재, `.get()` 으로 읽음 | 일관성 | 다른 모든 플래그는 defaults 에 선언 | **YES** | **LOW** | 저장소 실측 |
| **G-25** | 문서 ↔ 실측 drift 3건 | ① Matrix §2.1 이 iDRAC10 Fixture Evidence 를 실미러 `10_100_15_34` 로 적었으나 그 미러는 **FW 7.10.70.00 / 16G Monolithic = iDRAC9**. iDRAC10 미러는 저장소에 **없다** ② `NEXT_ACTIONS.md:75` "어떤 Family 도 PROVEN 아님" stale ③ `docs/operate/05-vault.md:362-365,:379-381` 이 2026-08-12 이전 진입 조건·`dryrun` 기본값 서술 | 실측 | 다음 작업자가 잘못된 근거로 판단 | **YES (문서 교정)** | **MED** | 저장소 실측 |
| **G-26** | 운영 Job 에 dryrun override 없음 | `Jenkinsfile_portal:219` override 부재 → 401 게이트가 열리면 운영 실쓰기 | ACC-D3 | — | **NO — 현행 유지 확정**(사용자 D-4). 본 계획의 실장비 검증은 Check Mode 우선 | **MED** | 저장소 실측 |

## 2.1 조사 결과와 **충돌하지 않음이 확인된** 항목 (수정 불요)

- Dell: `Locked` generic write 없음 / Firmware major 세대 판정 / iDRAC10 예약 {1,2} / 200+본문거부 처리(G-03 범위 한정)
- HPE: PCR generic retry 없음 / AccountTypes PATCH 없음 / CSUS·Superdome 분리 / AuthFailureDelay 반영
- Lenovo: Purley empty-slot PATCH 존재 / XCC `Locked` generic write 없음 / Create 시 `PasswordChangeRequired:false`(TSM default true 대응) / **204 no-body 성공 인정**(:5354)
- Cisco: 전역 `Administrator→admin` remap 제거 / `2..15` 전역 스캔 제거 / **Create 후 응답 `@odata.id` 를 맹신하지 않고 Collection 재열거 + username exact match**(:6263-6273) / **id_range 정합**(A27)
- Supermicro: 두 Create URI 를 fallback 으로 연속 시도하지 않음 / X9 generic 유지
- **Inspur: Create POST 에 If-Match 없음 + Repair PATCH 에 If-Match 있음 + 412 시 동일 URI·동일 payload·새 ETag 1회 — 공식 계약과 정확히 일치**
- Huawei: Collection POST + Instance PATCH / `Locked` 는 실제 잠김일 때만(제거하지 않음) / AccountTypes 미전송
- Fujitsu·Quanta: UNVERIFIED 유지 (단 G-02 fallback 은 제거)
- 전 Vendor: Check Mode Write 0 / UNKNOWN Write 0 / Recovery 최종 수집 0 / Fresh Auth 없는 `recovered=true` 0

---

# 3. Architecture Decision

## 3.1 원칙 — 새 Framework 를 만들지 않는다

현재 구조는 축을 대부분 갖고 있다. 부족한 것은 **표현력 4개**뿐이며, 전부 같은 dict 에 필드를 더한다.

## 3.2 Property Contract — `props` (G-08 / G-09 / G-11 / 사용자 지시 7)

```python
'props': {
    'Password':               {'create': 'writable',    'repair': 'writable'},
    'RoleId':                 {'create': 'writable',    'repair': 'writable'},
    'Enabled':                {'create': 'writable',    'repair': 'writable'},
    'Locked':                 {'create': 'unsupported', 'repair': 'read_only'},
    'PasswordChangeRequired': {'create': 'unsupported', 'repair': 'read_only'},
    'AccountTypes':           {'create': 'unsupported', 'repair': 'verify_only'},
}
```

값 5종과 소비 규칙:

| 값 | Create body | Repair body | 검증 |
|---|---|---|---|
| `writable` | 필요 시 포함 | **drift 시에만** 포함 | 대조 |
| `read_only` | 제외 | 제외 | 대조 |
| `verify_only` | 제외 | 제외 | **대조(필수)** |
| `unsupported` | 제외 | 제외 | 대조 안 함 |
| `unverified` | 제외 | 제외 | 관측만 기록 |

**최종 기본값 = `unverified`** (사용자 지시 7). `writable` 이 아니다. `unverified` Property 는 **자동 Write 하지 않는다.**

- **P1**: 회귀 0 을 위해 legacy-compatible default 를 임시 사용한다(현행 동작과 동일).
- **P2 완료 시점**: Write 가 가능한 **모든 Family** 가 위 6개 Property 를 **명시적으로** 선언해야 하고,
  전역 기본값은 `unverified` 로 전환한다. 이 전환이 P2 의 의도된 행동 변화이며 테스트로 고정한다.

## 3.3 Create URI 종류 — `create_uri` (G-04 / 사용자 지시 4)

```python
'create_uri': 'accounts_collection'   # 기본. discovery.accounts_uri (현행)
            | 'account_service_root'  # 최신 Supermicro (POST /redfish/v1/AccountService)
            | 'account_instance'      # Cisco IMC 3.x (POST /Accounts/<ID>)
```

**Accounts discovery URI 와 Create URI 는 개념적으로 분리**한다(사용자 지시 B).
`_accounts_write_uri(discovery)` → `_create_target_uri(family, discovery, explicit_id)`.

**절대 금지**: `/Accounts` POST 실패 → `/AccountService` POST, 또는 그 반대. 어느 방향의 Write fallback도 만들지 않는다.

## 3.4 ETag 계약 — Operation 단위 (G-22 / 사용자 지시 2)

Family 공통 boolean 하나를 Operation 단위로 바꾼다. **동작 변화 0** — 현재도 Repair 에만 적용된다.

```python
'if_match': {'create': False, 'repair': False}   # _ACCOUNT_FAMILY_DEFAULTS
# inspur_m6:
'if_match': {'create': False, 'repair': True}
```

- **Inspur M6 Create = `POST /AccountService/Accounts`, If-Match 없음.** (06 §5/§28)
- **Inspur M6 Repair = `PATCH /AccountService/Accounts/<id>` + `GET ETag` → `If-Match`.** (06 §11/§29)
- **412 재시도 = 동일 URI + 동일 Payload + 새 ETag, 1회만.** (06 §12)
- `create_if_match` 가 필요한 Family 가 나타나기 전까지 `create` 는 어디서도 `True` 가 아니다.

## 3.5 Supermicro Create URI 결정 규칙 (사용자 지시 4)

공식 최신 매뉴얼은 Add Account 를 `POST /redfish/v1/AccountService` 로 명시하고, **같은 문서**가
계정 분리 Firmware 경계(Gen13 `01.05.xx+`, Gen14 `01.02.xx.xx+`, NVIDIA Superchip `01.04.xx+`)를 명시한다.

**결정 규칙 (추측 금지):**

```text
IF  Generation 이 장비가 준 값(Manager.Model / System Model / FirmwareVersion)으로 확정되고
AND 그 Generation 의 Firmware 경계를 실제 FirmwareVersion 이 충족한다
THEN create_uri = 'account_service_root'      # documented latest contract
     evidence   = 'documented'
     create_uri_basis = 'generation+firmware'

ELSE create_uri = 'accounts_collection'       # 구 Reference Guide 계약 하나만 사용
     evidence   = 'unverified'
     create_uri_basis = 'unverified_single_strategy'
     → UNVERIFIED one-shot 정책: 한 번만 쓰고 fallback 없음
```

**Generation 근거는 adapter hint 단독으로 삼지 않는다.** Dell iDRAC10 오분류와 같은 실패 유형이기
때문이다(무인증 probe 단계에서 fact 가 비어 priority 로 결정됨). 그래서 `account_service_discover()`
가 인증 후 Manager 를 읽는 것처럼 **System Model 도 읽어** Generation 근거를 장비에서 확보한다.
확보하지 못하면 위 ELSE 로 간다.

두 URI 를 순차 시도하는 경로는 **어느 분기에서도 만들지 않는다.**

## 3.6 보호 계정 분류 (G-07 / 사용자 지시 5)

`reserved_slot_ids` 문자열 매칭을 **Resource Property 기반 분류**로 교체한다.

```text
account.kind = 'normal' | 'protected'

protected 판정 근거 (우선순위):
  1. HostBootstrapAccount == true                 ← 가장 우선. DMTF 표준 Property.
     (schema/redfish_dmtf_2026.1/ManagerAccount.v1_14_1.json:323,
      실미러 tests/reference/redfish/lenovo/10_50_11_232/..._accounts_{1,2,3}.json 에 실제 존재)
  2. Family 공식 reserved ID  (Dell slot 1 / iDRAC10 slot 1·2, TSM IPMI ID 1 등)  ← 보조
```

- **protected Resource 를 열거 결과에서 제거하지 않는다.** 조회·진단에는 그대로 남긴다.
- **Create / Repair candidate 에서만 제외**한다 (빈 slot 후보, 명시 Id 후보 모두).
- **Standard username 이 protected Resource 와 충돌하면** `protected_conflict` → **Write 0**.
  (username 이 같은데 그 계정이 protected 라면 자동 처리 대상이 아니다. `ambiguous` 와 같은 층의 무진행 종료.)
- `HostBootstrapAccount` 는 **XCC3 전용이 아니다** — XCC2 및 실측 XCC 미러에도 존재한다.

## 3.7 HPE Firmware Evidence 분리 (G-01 / 사용자 지시 1)

**Family 를 과도하게 쪼개지 않는다.** `hpe_ilo5plus` 하나를 유지하고 `isolated_write_patch: True` 도 유지한다.
(iLO5/6/7 에서 Password 단독 PATCH 는 HPE 공식 지원 동작이고, Repository 안전 전략으로 허용됨 — D-2 확정)

대신 **Firmware Evidence / Workaround metadata 를 분리**한다. Family 선택 결과에 붙는 부가 정보다.

```python
# hpe_isolation_evidence(firmware_version) -> (isolation_basis, evidence, advisory)
iLO6 1.73              -> ('live_proven',      'proven',     'a00159600en_us')
iLO6 1.74              -> ('advisory_derived', 'documented', 'a00159600en_us')
iLO7 1.19 / 1.20       -> ('advisory_derived', 'documented', 'a00159600en_us')
iLO5 (any)             -> ('safety_strategy',  'documented', None)
iLO6 >= 1.75           -> ('safety_strategy',  'documented', None)   # Advisory fixed
iLO7 >= 1.21           -> ('safety_strategy',  'documented', None)   # Advisory fixed
Firmware 판독 불가      -> ('safety_strategy',  'documented', None)   # 보수적: 과대주장 금지
```

의미:

| basis | 뜻 |
|---|---|
| `live_proven` | 현재 프로젝트 실장비에서 Password isolation 필요성이 직접 재현됨 |
| `advisory_derived` | HPE 공식 Advisory 가 **Firmware defect 를 확인**했으나, exact password isolation 필요성은 Advisory 가 명시한 조건과 다름 |
| `safety_strategy` | Vendor 필수 계약이 아니라 **Repository 안전 전략**. Password 단독 PATCH 는 HPE 공식 지원 동작이므로 계속 사용하되 `proven` 으로 표기하지 않음 |

**어떤 경우에도 `safety_strategy` / `advisory_derived` 를 `Vendor mandatory` 또는 `LIVE-PROVEN` 으로 표기하지 않는다.**
iLO 세대·버전은 HPE `FirmwareVersion` 문자열(`iLO 6 v1.73` 형태)과 `Manager.Model` 에서 얻는다.

## 3.8 다중 Write 가 허용되는 두 경우 (사용자 지시 3) — 그 외는 전부 금지

```text
[A] ETag 412 concurrency retry
      동일 URI + 동일 Payload + 새 ETag,  정확히 1회

[B] Family/Firmware Contract 에 사전 정의된 deterministic sequence
      예: HPE isolated password PATCH  →  실제 drift 가 있는 attribute 만 후속 PATCH
      (쓰기 전에 Family 가 확정한 순서다. 응답을 보고 방식을 바꾸는 것이 아니다.)
```

**금지 (blind fallback)**:

- `PasswordChangeRequired` 를 먼저 보내고 `PropertyNotWritable` 응답 후 제거해서 다시 Write — **새로 만들지 않는다**
- 기존 `Locked/Enabled/RoleId` drop-and-retry 사다리(:5906-5923) — **제거한다.**
  `props` 가 채워지면 read_only/unsupported/unverified Property 는 애초에 전송되지 않으므로 이 경로는 도달 불가가 된다.
- 다른 URI / 다른 Method / 다른 Slot / 다른 payload 로의 재시도

**예상하지 못한 Property rejection 이 발생하면**: 해당 run 은 실패로 확정하고,
`write_rejections` + `post_write_state` 를 기록한다. **추측성 두 번째 Write 를 하지 않는다.**

## 3.9 Write Convergence 단계 (사용자 지시 C)

| 단계 | 표현 |
|---|---|
| transport accepted | `write_http_status` (신규) |
| property accepted | `write_accepted` + `write_rejections[]` (G-03) |
| resource state converged | `post_write_state` (기존) |
| credential fresh-auth verified | `verification == 'verified'` (기존) |
| required resource access verified | `verify_resource` (신규 — 현재 `GET /Systems` 사실 명시) |
| gathering verified | Ansible Phase 3 재수집 (`site.yml:191-198`) |

## 3.10 Family 분할 원칙

**Firmware/공식 계약이 실제로 갈리는 곳만** 나눈다.

```text
hpe_ilo5plus            → 유지 (분할 없음). Firmware Evidence metadata 로 구분  ← §3.7
lenovo_xcc_accounttypes → lenovo_xcc2_accounttypes (PCR writable)
                          lenovo_xcc3_accounttypes (PCR 미지원)
generic_collection_post → 유지 (legacy_post_retry 제거)
                          + qct_legacy / qct_modern / qct_inhouse_openbmc (동작 동일, 라벨)
                          + cisco_cimc3_instance_post
supermicro_split_account→ 유지 + create_uri 조건부 결정 (§3.5)
```

---

# 4. Implementation Phases

총 **7 Phase**.

| Phase | 내용 | 코드 변경 | 선행 |
|---|---|---|---|
| **P0** | baseline 검증 → baseline commit → 본 문서 저장소 기록 (§11 순서 준수) | 없음 | — |
| **P1** | 표현력 도입 (`props` / `create_uri` / `if_match` / convergence 필드 / G-24). **legacy-compatible default 로 행동 변화 0** | 구조 | P0 |
| **P2** | 계약 충돌 교정: G-02, G-03, G-09, G-10, G-11 + **`props` 기본값을 `unverified` 로 전환** + **drop-retry 사다리 제거** | 동작 | P1 |
| **P3** | HPE Firmware Evidence metadata 분리 (G-01) — **Family 분할 없음, 동작 변화 없음** | 라벨/진단 | P1 |
| **P4** | Family 세분화: G-06, G-07, G-14, G-15, G-19, G-20 + Supermicro create_uri 결정(§3.5) | 데이터 위주 | P1, P3 |
| **P5** | 진단 축: G-05, G-12, G-13, G-17, G-18 | 동작(읽기/진단) | P2 |
| **P6** | 테스트 전면 (§7) + 정적검증 + 회귀 | 테스트 | P2~P5 |
| **P7** | 문서/Matrix/Evidence 갱신 (G-25 포함) + 실장비 검증 (§8) | 문서 | P6 |

**Phase 합격 조건**: 각 Phase 종료 시 `pytest tests/ -q` 전량 PASS + replay 회귀 PASS.
**P1 은 행동 변화 0 이 합격 조건**(순수 표현력 도입).

---

# 5. File Change Plan

## 5.1 `redfish-gather/library/redfish_gather.py`

| # | 대상 (현재 위치) | 변경 | 이유 | 영향 |
|---|---|---|---|---|
| F-01 | `_ACCOUNT_PROP_DEFAULTS` **신규** (:5061 인접) | 6 Property × create/repair. **P1=legacy-compatible, P2=`unverified`** | 지시 7 / G-08 | P1 0, P2 의도된 변화 |
| F-02 | `account_prop_contract(family, prop, op)` **신규** | 5-상태 조회 | G-08 | 없음 |
| F-03 | `_ACCOUNT_FAMILY_DEFAULTS` :5061 | `props`, `create_uri`, `if_match`, `account_types_required`, `full_body_patch`, `isolated_write_patch:False` 추가 | G-04/08/11/22/24 | 기본값=현행 |
| F-04 | `_ACCOUNT_FAMILIES` :5076-5145 | Family 별 `props` / `if_match` / `create_uri` 채움 + Lenovo XCC2·XCC3 분할 + Cisco IMC3.x + QCT 3분할 + Supermicro Superchip 경계 + **`legacy_post_retry` 제거** | G-02/06/14/15/19/22 | **핵심** |
| F-05 | `resolve_account_family()` :5180-5324 | (a) Lenovo **capability-first 로 정렬** + Purley 부정 신호 (b) Cisco IMC3.x (c) Supermicro Generation 근거를 장비값 우선 (d) Quanta 3분할 | G-06/14/15/19/20 | Family 결과 변화 → replay 회귀 필수 |
| F-06 | `hpe_isolation_evidence(firmware, model)` **신규** + HPE 분기 :5275-5288 | Family 는 그대로, `isolation_basis` / `evidence` / `advisory` 만 산출 | **G-01** | **동작 0, 라벨만** |
| F-07 | `rejected_patch_properties()` :519 → **`write_rejections(body)`** (기존 함수는 wrapper 유지) | `RelatedProperties`(`#/Password`→`Password`) + `Severity` + 정책 거부 MessageId 를 읽어 `{property, kind, message_id, severity}` 반환. `kind ∈ {read_only, value_rejected, policy_rejected}` | **G-03** | Dell SYS474 정확 판정 |
| F-08 | `interpret_write_response()` :5347 | `write_rejections()` 사용. **모든 kind 가 즉시 실패**(재시도 없음) | G-03 / 지시 3 | drop-retry 제거와 정합 |
| F-09 | **~~`ACCOUNT_OPTIONAL_PATCH_PROPS` 에 PCR 추가~~ 철회** + `droppable` 사다리 :5906-5923 **제거** | `props` 가 애초에 안 보내므로 도달 불가. 지시 3 의 "generic payload fallback 금지" | **G-09 / 지시 3** | **blind fallback 0** |
| F-10 | `_accounts_write_uri()` :5369 → **`_create_target_uri(family, discovery, explicit_id)`** | `create_uri` 3종. 기본값 현행 동일 | G-04 | 없음(기본) |
| F-11 | `account_service_provision()` body 조립 :5843-5886 | `props` 기반 **drift-only**. `full_body_patch=True`(Lenovo XCC)는 현행 full body 유지 | G-08/09/10 | **Lenovo 반례 보존 필수** |
| F-12 | `_confirm_account_state()` :5380-5426 | `verify_only` / `account_types_required` 항상 대조. AccountTypes 에 Redfish 부재 시 명시 오류 | G-11 | 검증 강화(쓰기 0) |
| F-13 | `account_service_discover()` :4895-5031 | (a) **`HostBootstrapAccount` 수집** (b) `HTTPBasicAuth` + `Oem.*.AuthMethods` (c) ManagerAccount `Oem` 축약 보존(Huawei Login Interface) (d) **System Model 읽기**(Supermicro Generation 근거) | G-05/07/18 + §3.5 | 읽기만 |
| F-14 | `account_presence()` :5034-5048 + 후보 선정 :6119-6146 | `kind='protected'` 를 **candidate 에서만 제외**(열거·진단 유지). username 충돌 시 `protected_conflict` → Write 0 | **G-07 / 지시 5** | 보호 강화 |
| F-15 | `choose_role_id()` :5327-5344 | 선택값이 `discovery.role_ids` 에 없으면 `role_id_unsupported` 표시(반환값 유지) | G-17 | 진단만 |
| F-16 | provision 정책부 :5729-5755 | `policy_conflict` 구조 노출(수학적 불일치 별도 표시). **쓰기는 현행대로 1회 시도** | G-12 / 지시 8 | 진단만 |
| F-17 | `_verify_standard_credential()` :5657-5668 | 예산 상한 초과 시 **중단**(retry 증가 아님) + `auth_budget_exhausted` | G-13 | 실패 경로 단축 |
| F-18 | `_ACCOUNT_CREATE_STRATEGY` :4748, `_account_create_method_for_vendor()` :4761 | 제거 | G-21 | 소비자 0건 |
| F-19 | provision out dict :5608-5644 | `write_http_status`, `write_rejections`, `verify_resource`, `policy_conflict`, `protected_conflict`, `login_interface`, `auth_methods`, `role_id_unsupported`, `isolation_basis`, `firmware_advisory`, `create_uri_basis` 추가 | 지시 C | **`diagnosis.details.account_service` 하위 — envelope 13 필드 불변** |
| F-20 | Create 경로 :6160(`_patch` 직접) / :6221(`_post`) | `if_match['create']` 를 **읽되 현재 모든 Family 가 `False`** 라 헤더 미전송. `_patch_account` wrapper 로 통일해 기존 seam 보존 | **G-22 / 지시 2** | **동작 변화 0** |

**Cisco `id_range` 는 변경하지 않는다** (G-23 삭제, §1.2 A27).

## 5.2 `redfish-gather/tasks/account_service.yml`

| # | 변경 | 이유 |
|---|---|---|
| F-21 | `_rf_account_service_meta` 에 F-19 신규 필드 노출 (기존 `default(none)` 패턴) | 진단 가시화 |
| F-22 | 성공 게이트 `:204-207` **변경 없음** | 이미 정합 |
| F-23 | `account_service_try_one.yml:32` `target_role: "Administrator"` **변경 없음** — `choose_role_id()` 가 장비 지원 목록에서 고르므로 이 값은 "요청 의도". 미지원 시 진단(F-15) | G-17 |

## 5.3 `adapters/redfish/*.yml` (origin 주석, rule 96 R1)

| # | 대상 | 내용 |
|---|---|---|
| F-24 | `hpe_ilo5/6/7.yml` | Advisory `a00159600en_us` + 영향(1.73/1.74/1.19/1.20) / 수정(1.75+/1.21+) 기록 |
| F-25 | `lenovo_xcc.yml` / `lenovo_xcc3.yml` | XCC2·XCC3 Create Property 차이 + **`HostBootstrapAccount` 가 XCC2 에도 존재** |
| F-26 | `supermicro_x13/x14/ars.yml` | 계정 분리 Firmware 경계 (01.05 / 01.02 / 01.04) |
| F-27 | `quanta_qct_bmc.yml` | Legacy / Modern / Inhouse OpenBMC 구분 근거 |
| F-28 | `cisco_cimc.yml` | IMC 3.x instance POST vs 4.1+ collection POST |

## 5.4 문서

Vendor × Family 매트릭스, `CURRENT_STATE.md`,
`NEXT_ACTIONS.md`, `catalogs/EXTERNAL_CONTRACTS.md`, `catalogs/TEST_HISTORY.md`,
`catalogs/LAB_PENDING_MATRIX.md`, `docs/reference/decision-log.md`, `docs/operate/05-vault.md`,
`docs/ai/decisions/ADR-2026-08-13-account-write-contract-alignment.md`(신규, rule 70 R8 trigger 1),
계정 쓰기 계약 정합 검증 기록 (`docs/ai/CURRENT_STATE.md` 2026-08-13 절)

---

# 6. Vendor / Family Plan

[OK] 완료(변경 불요) / 🔧 수정 / ➕ 추가 / [HOLD] UNVERIFIED 유지

## 6.1 HPE

| Family | 조치 | 내용 |
|---|---|---|
| `hpe_ilo4` | [OK] | `Oem/Hp` namespace, `documented` |
| `hpe_ilo5plus` | 🔧 **라벨만** | **분할하지 않는다.** `isolated_write_patch: True` **유지**(iLO5/6/7 전체 — Repository 안전 전략, HPE 공식 지원 동작). `props`: PCR `read_only`, AccountTypes `verify_only`(iLO6 1.64+/iLO7), Locked `unsupported` |
| — Firmware Evidence | ➕ | iLO6 1.73 → `live_proven`/`proven`/advisory · iLO6 1.74 → `advisory_derived`/`documented`/advisory · iLO7 1.19·1.20 → `advisory_derived`/`documented`/advisory · **iLO5 / iLO6 1.75+ / iLO7 1.21+ → `safety_strategy`/`documented`/None** |
| `hpe_rmc`(CSUS 3200/Superdome Flex) | ➕ **신설 2026-10-14 (hotfix)** | 사이트 CSUS 3200 실측: Accounts POST 의 `Enabled` → `Base.1.17.PropertyUnknown` 으로 요청 전체 거부(generic 기본 계약이 보내던 속성). `props.Enabled` create `unsupported` / repair `unverified`, 나머지 기본. evidence `unverified`(공식 RMC 계정 계약 미확보 — DOCUMENT-GAP, 사이트 실측이 1차 근거). 종전 `generic`(CSUS/Superdome) [HOLD] 01 §16/§21 을 대체. `tests/evidence/2026-10-14-hpe-rmc-account-create-enabled-rejected.md` |

**Vendor mandatory 로 표기하지 않는다.** Password-only PATCH 는 HPE 공식 문서가 지원하는 동작이며,
"반드시 단독이어야 한다"는 공식 계약이 아니다(01 §15).

## 6.2 Dell

| Family | 조치 | 내용 |
|---|---|---|
| `dell_slot_patch` (iDRAC7/8/9) | [OK] + 🔧 props | Locked `read_only`, PCR `unsupported`, AccountTypes `verify_only` |
| `dell_idrac10_slot_patch` | [OK] + 🔧 props | 예약 slot {1,2} 유지 |
| 전 Dell | 🔧 **G-03** | `SYS474` / `RelatedProperties` / `Severity` 해석 |
| 전 Dell | 🔧 **G-13** | `AccountLockoutThreshold=0` 이어도 IP Blocking 별도 예산 |
| Basic Auth | 🔧 **G-18** | client 는 이미 선제 `Authorization` 전송 → `Unadvertised` 호환. 상태만 기록, `Disabled` 진단 분리 |
| 세대 오분류 | [OK] **해소됨** | Firmware major 판정 |

## 6.3 Lenovo

| Family | 조치 | 내용 |
|---|---|---|
| `lenovo_purley_slot_patch` | 🔧 **G-20** | capability-first 정렬 + 부정 신호(hint xcc2/xcc3/whitley/amd → Purley 아님). PCR `unsupported` |
| `lenovo_collection_post` (Whitley/AMD/TSM) | 🔧 props | PCR `writable`, Locked: XCC1 `read_only` / **TSM `writable`**. 204 no-body [OK] |
| `lenovo_xcc_accounttypes` | 🔧 **분할** | ↓ |
| ➕ `lenovo_xcc2_accounttypes` | ➕ | AccountTypes `writable`, PCR `writable` |
| ➕ `lenovo_xcc3_accounttypes` | ➕ | AccountTypes `writable`, **PCR `unsupported`** |
| `generic`(IMM2) | [HOLD] | 03 §4 |
| 보호 계정 | 🔧 **G-07** | `reserved_slot_ids:('HostBootStrap',)` 제거 → **`HostBootstrapAccount == true` Resource Property 를 최우선 근거**로 `protected` 분류. **XCC2 에도 존재**. 조회·진단 유지, candidate 에서만 제외. username 충돌 시 `protected_conflict` → Write 0. TSM IPMI ID 1 은 Family 보조 근거 |
| `full_body_patch` | [OK] 유지 | XCC 권한 cache 손상 사이트 실측 반례 보존 (G-10) |

## 6.4 Cisco

| Family | 조치 | 내용 |
|---|---|---|
| ➕ `cisco_cimc3_instance_post` | ➕ | `create_uri: account_instance`, RoleId `admin` (G-14) |
| `cisco_cimc_collection_post_id` | [OK] | `admin` + 명시 Id. **`id_range:(2,16)` half-open = 2..15 정합 — 변경 없음**(G-23 삭제) |
| `cisco_bmc_dynamic` | 🔧 props | **PCR `read_only`(existing)**, AccountTypes `verify_only`, Locked `writable` |
| `generic`(X-Series) | [HOLD] | 04 §24 |
| Create 후 확정 | [OK] | Collection 재열거 + username exact match (:6263-6273) |

## 6.5 Supermicro

| Family | 조치 | 내용 |
|---|---|---|
| `supermicro_legacy` | [OK] + 🔧 props | `create_uri: accounts_collection`. Existing Password Repair 는 `unverified` 표기 |
| `supermicro_split_account` | 🔧 **§3.5 결정 규칙** | Generation+Firmware 를 **장비값**으로 확정하면 `create_uri = account_service_root` **실적용**(evidence `documented`). 확정 불가면 `accounts_collection` 하나만 사용 + `unverified` + one-shot. **양방향 Write fallback 절대 금지** |
| Superchip 경계 | ➕ **G-19** | `_fw_at_least(firmware, 1, 4)` |
| Presence | 🔧 **G-11** | username 존재만으로 healthy 금지 — AccountTypes 에 Redfish 포함 확인 |
| `generic`(X9) | [HOLD] | 05 §32 |

## 6.6 Inspur

| Family | 조치 | 내용 |
|---|---|---|
| `inspur_m6` | [OK] **동작 유지** | Create = **POST Collection, If-Match 없음**. Repair = **PATCH Instance + GET ETag → If-Match**. 412 → 동일 URI·동일 payload·새 ETag **1회**. `Oem.Public.Status==0`. **이미 공식 계약과 일치** |
| `inspur_m6` 표현 | 🔧 **G-22** | `etag_required` boolean → `if_match: {'create': False, 'repair': True}` (동작 변화 0) |
| `inspur_m6` props | 🔧 | PCR `unverified`, Locked `unverified`, AccountTypes `unverified` (06 §16/§17/§18) |
| `generic`(M5/M7) | [HOLD] | 06 §24/§25 |

## 6.7 Huawei

| 항목 | 조치 | 내용 |
|---|---|---|
| `huawei_ibmc` | [OK] | Collection POST + Instance PATCH |
| Locked | [OK] | **제거하지 않는다.** `writable` 표기 + 실제 `locked=true` 일 때만 전송 |
| Redfish Login Interface | ➕ **G-05** | **읽기·진단만.** `login_interface` 로 관측값 보존, "계정 정상인데 표준 인증 실패" 시 원인 후보 노출. **repair OEM payload 는 근거 없어 구현하지 않는다**(07 §12/§37) |
| AccountTypes / PCR | [OK] | 미전송 유지 |

## 6.8 Fujitsu

| 항목 | 조치 | 내용 |
|---|---|---|
| `generic_collection_post` (S4/S5/S6) | 🔧 **G-02** | `legacy_post_retry` 제거 → one deterministic write / no fallback |
| RoleId | 🔧 **G-17** | `RedfishAdmin` ↔ `ManagerAccount.RoleId` literal 혼동 금지. 미지원 시 진단 |
| Locked/Enabled/PCR/AccountTypes/ETag | [HOLD] | 전부 `unverified` → **자동 Write 0** |
| 구현 vs 조사 분리 | 📋 | **구현**: fallback 제거 + RoleId 진단 + Generation/Firmware 근거 보존. **조사**: 2026 `iRMC RESTful API Specification pack`(13.15MB) 원문 + PRIMERGY read-only mirror. 확보 전 Family 추가 없음 |

## 6.9 Quanta / QCT

| Family | 조치 | 내용 |
|---|---|---|
| ➕ `qct_legacy_redfish` / `qct_modern_redfish` / `qct_inhouse_openbmc` | ➕ 라벨 | 동작 = 현행 generic. **AST2600 만으로 OpenBMC 판정 금지. QCT Inhouse ≠ upstream master** |
| AccountTypes | [OK] **금지 고정** | `["Redfish"]` generic 전송 금지(StrictAccountTypes). 현재 미전송을 **테스트로 고정** |
| PCR | 🔧 **G-02** | generic retry 제거 |
| Locked / ETag | [HOLD] | `unverified` — generic 적용 금지 |
| Auth 진단 | ➕ **G-18** | `HTTPBasicAuth` / `Oem.OpenBMC.AuthMethods` 읽기 |

---

# 7. Test Plan

## 7.1 Unit

| 대상 | 파일 | 검증 |
|---|---|---|
| Property Contract | ➕ `test_account_property_contract.py` | 6 Property × 5-상태 × create/repair. **read_only/unsupported/unverified 는 body 에 절대 미포함**. **기본값이 `unverified`(P2 이후)** |
| **Blind fallback 0** | ➕ `test_account_no_write_fallback.py` | 어떤 Family·어떤 응답에서도 **2차 Write 0**. 허용 예외는 (A) ETag 412 1회 (B) HPE isolated sequence 뿐. `_post`/`_patch` seam 호출 횟수 assert |
| **기존 테스트 반전** | 🔧 `test_account_provision_f49_vendor_compat.py` | `test_unverified_family_keeps_the_legacy_post_retry` 가 **제거 대상 동작을 고정** → "재시도 0건" 으로 반전. **이 테스트를 두면 G-02 적용 불가** |
| drop-retry 제거 | 🔧 동 파일 | `Locked/Enabled/RoleId` drop-and-retry 경로 부재 확인 |
| Family 선택 | 🔧 `test_account_family_and_write_contract.py` | Lenovo capability-first / XCC2·XCC3 / Purley 부정 신호 / Cisco IMC3.x / Supermicro Superchip / QCT 3분할. **결정성(동일 입력→동일 Family)** |
| HPE Evidence | 🔧 `test_account_password_isolation_and_verify_pacing.py` | **Family 는 하나로 유지**되고 `isolation_basis`/`evidence`/`advisory` 만 Firmware 별로 갈린다: 1.73→live_proven/proven · 1.74·1.19·1.20→advisory_derived/documented · iLO5·1.75+·1.21+·판독불가→safety_strategy/documented. **`proven` 이 전 Firmware 로 번지지 않음** |
| Inspur ETag | ➕ | **Create POST 요청에 `If-Match` 헤더 부재** / Repair PATCH 에 존재 / 412 → 동일 URI·동일 payload·새 ETag 1회 |
| Write 응답 해석 | 🔧 | Dell `SYS474`(RelatedProperties `#/Password`, Severity Warning) → `write_accepted=False`, **재시도 0**. Dell `PropertyNotWritable` → 실패(재시도 0). Inspur `Status!=0` → 실패. `204` → 성공 |
| Create URI | ➕ | 3종 각각 **정확히 1개 URI 에만** 요청. **`/Accounts` ↔ `/AccountService` 교차 시도 0** |
| Supermicro create_uri 결정 | ➕ | Generation+Firmware 확정 시 `account_service_root` / 미확정 시 `accounts_collection`+`unverified`. **어느 쪽도 fallback 없음** |
| 보호 계정 | 🔧 `test_account_capability_and_presence.py` | `HostBootstrapAccount==true` → `protected`. **열거/진단에는 남고 candidate 에서만 제외**. username 충돌 → `protected_conflict` + Write 0. **protected 가 ABSENT 로 오판되지 않음** |
| Auth budget | ➕ | 초과 시 **중단**(retry 증가 아님) |
| POLICY_CONFLICT | ➕ | 수학적 불일치 진단 + **쓰기 1회는 그대로 시도** + 자동 완화/회전 0 |
| Huawei Login Interface | ➕ | 관측·진단만, **repair 쓰기 0** |
| Secret 누출 | 🔧 | 신규 필드 전부 |

## 7.2 Integration — Fixture Replay

- 🔧 `test_account_reconcile_replay.py` — 실미러 8호스트로 Discovery→presence→Family→예상 payload 재생, Family 결과 **golden 고정**
- ➕ Lenovo 실미러의 `HostBootstrapAccount` 필드를 protected 분류 회귀에 사용 (합성 아님)
- ➕ 쓰기 응답 fixture: Dell SYS474 / Dell PropertyNotWritable / Inspur OEM Status / TSM 204 / HPE AccountModified (실측 문장 기반)
- ➕ 9 Vendor Family 최소 세트 mock (`account_service.json`/`accounts.json`/`roles.json`/`manager.json`) — 출처 주석 의무(rule 21 R2)

## 7.3 Regression

`pytest tests/ -q` 전량 (기준 2,860) / `output_schema_drift_check.py`(envelope 13 필드 불변) /
`verify_vendor_boundary.py` / `verify_harness_consistency.py` / `ansible-playbook --syntax-check` ×3 /
`py_compile` / baseline 회귀

## 7.4 Check Mode

`dryrun=True` / `module.check_mode=True` 각각에서 `_post`/`_patch` 호출 **0건**, `verification='skipped'`, `recovered=False`

## 7.5 Failure Case

| 시나리오 | 기대 |
|---|---|
| Accounts 403/500/timeout/링크 부재 | `presence=unknown` → **Write 0** |
| 일부 member GET 실패 | `enumeration != complete` → **Write 0** |
| 동일 username 다중 slot | `ambiguous` → **Write 0** |
| **Standard username 이 protected Resource** | **`protected_conflict` → Write 0** |
| Recovery 인증 실패 | `auth_ok=False` → **Write 0** |
| 쓰기 2xx + 본문 거부 | `write_accepted=False` → **즉시 실패, 재시도 0** |
| **예상 못한 Property rejection** | **실패 확정 + `write_rejections`·`post_write_state` 기록, 두 번째 Write 0** |
| 쓰기 수락 + Fresh Auth 실패 | `verification=failed`, delete/recreate 미수행 |
| 예약/protected slot 만 비어 있음 | Create 미수행 + 명시 오류 |

## 7.6 Second Run Write 0

표준 인증 성공 → 게이트 skip → `AccountService` 요청 0 / `_post`·`_patch` 0 을 **Ansible 템플릿 렌더 + 모듈 seam 양쪽**에서 고정

---

# 8. Live Validation Plan

## 8.1 실장비 보유 (git Location)

| Vendor | 장비 | Firmware | 검증 가능 | 검증 불가 |
|---|---|---|---|---|
| **Dell** | 10.100.15.34 R760 iDRAC9 | 7.10.70.00 | Case A 회귀 / `dell_slot_patch` 확정 / `write_rejections` 해석 / 2차 Write 0 | Create / iDRAC10 / 7.30+ Basic Auth |
| **HPE** | 10.50.11.231 DL380 Gen11 iLO6 | v1.73 | Case A 회귀 / **`isolation_basis=live_proven` + `evidence=proven` 이 이 Firmware 에만** / AuthFailureDelay pacing | iLO5 / 1.75+ / iLO7 / Create |
| **Lenovo** | 10.50.11.232 XCC | AFBT58B 5.70 | Case A + **Case B 회귀** / XCC2·XCC3 중 어느 Family 로 확정되는지 / **`HostBootstrapAccount` protected 분류 실측** / `full_body_patch` 반례 보존 | Purley / TSM / IMM2 / Create |
| **Cisco** | 10.100.15.2 CIMC | 4.1(2g) | Case A 회귀 / Roles 어휘 Family 판정 / RoleId `admin` | IMC 3.x / 최신 BMC / X-Series / Create |

## 8.2 검증 절차 (운영 계정 삭제 없음)

```text
1. Read-only Capability Mirror 갱신 (tests/reference/redfish/**) — Secret 제거
2. Check Mode 실행 (Write 0 확인)  →  Family / presence / protected / 예상 payload 산출
3. 1차 정상 실행  →  Case A
4. 2차 실행       →  Write 0 재확인
5. (Repair 조건이 자연 발생한 경우에만) Case B 관측
```

**금지**: 정상 Standard 삭제 / Recovery·Admin 삭제 / Slot 확보용 삭제 / Password·Lockout 정책 완화 /
Basic Auth 자동 enable / 운영 계정 Password 임의 변경 / Global Standard Password 자동 변경·회전.

## 8.3 실장비 없음 — UNVERIFIED 유지

Supermicro / Huawei / Inspur / Fujitsu / Quanta — mock fixture + 공식 문서만.
Supermicro `/AccountService` POST 는 **§3.5 결정 규칙**으로만 적용. Huawei Login Interface 는 읽기 진단만.
Fujitsu 는 API Pack 원문 확보 전 Family 추가 없음.

## 8.4 조사 필요 대상 (구현 대상과 분리)

| 우선순위 | 대상 | 얻는 것 |
|---|---|---|
| HIGH | Fujitsu `iRMC RESTful API Specification pack` 원문 | S4/S5/S6 Method Table |
| HIGH | Supermicro Generation 판별 가능한 실미러 (분리 전후 각 1) | `create_uri` 결정 근거 |
| HIGH | Huawei Redfish Login Interface OEM field/action | repair payload (확보 전 구현 금지) |
| MED | Lenovo Purley / XCC2 / XCC3 / TSM mirror | Family 분할 + protected 실증 |
| MED | Cisco 최신 BMC mirror | `Administrator` RoleId + Id semantics |
| MED | Inspur M6 mirror + `Oem.Public.Status` 전체 code | 성공/실패 판정 완결 |
| **MED** | **Cisco IMC allowable Account Id 범위 공식 근거** | **G-23 확정 (근거 없이 수정 금지)** |
| LOW | QCT 3 Family mirror / Dell iDRAC7·8 mirror | 경계 실증 |

---

# 9. Compatibility Matrix Update Plan

## 9.1 상태 + 근거 축 분리

| 열 | 값 |
|---|---|
| `Status` | `PROVEN / PARTIAL / UNVERIFIED / MISSING / BROKEN / HOLD` (기존) |
| `Evidence` | `LIVE-PROVEN / OFFICIAL / ADVISORY-DERIVED / DOCUMENTED / UPSTREAM-REFERENCE / UNVERIFIED / DOCUMENT-CONFLICT / DOCUMENT-GAP` |
| `Firmware Risk` | Advisory ID + 영향/수정 버전 |
| `Workaround Basis` | `live_proven / advisory_derived / safety_strategy` (HPE 등) |

**`LIVE-PROVEN` 과 `ADVISORY-DERIVED` 를 절대 합치지 않는다**(01 §4.1).

## 9.2 HPE 행 예 (Family 는 하나, Firmware 로 행 분리)

| Family | Firmware | Write 동작 | Workaround Basis | Status | Evidence | Firmware Risk |
|---|---|---|---|---|---|---|
| `hpe_ilo5plus` | iLO5 전체 | Password 단독 PATCH | **safety_strategy** | UNVERIFIED(Create) | DOCUMENTED | — |
| `hpe_ilo5plus` | **iLO6 1.73** | Password 단독 PATCH | **live_proven** | **PROVEN(Case A)** | **LIVE-PROVEN** | a00159600en_us |
| `hpe_ilo5plus` | iLO6 1.74 | Password 단독 PATCH | **advisory_derived** | PARTIAL | **ADVISORY-DERIVED** | a00159600en_us |
| `hpe_ilo5plus` | iLO6 1.75+ | Password 단독 PATCH | **safety_strategy** | UNVERIFIED | DOCUMENTED | **fixed** |
| `hpe_ilo5plus` | iLO7 1.19/1.20 | Password 단독 PATCH | **advisory_derived** | UNVERIFIED | ADVISORY-DERIVED | a00159600en_us |
| `hpe_ilo5plus` | iLO7 1.21+ | Password 단독 PATCH | **safety_strategy** | UNVERIFIED | DOCUMENTED | **fixed** |
| `hpe_ilo4` | 전체 | POST + `Oem/Hp` | — | PARTIAL | DOCUMENTED | — |
| `hpe_rmc`(CSUS 3200/Superdome Flex) | RMC 1.75.108 (Redfish 1.19) | Collection POST **Enabled 미전송** | — | UNVERIFIED(Create 수락 미확정) | **SITE-OBSERVED(거부)** + DOCUMENT-GAP | 2026-10-14 hotfix |

동일 방식으로 Dell / Lenovo / Cisco / Supermicro / Inspur / Huawei / Quanta 를 채운다.

## 9.3 G-25 drift 교정 3건

1. **Matrix §2.1 "iDRAC10 Fixture Evidence = 실미러 `10_100_15_34`" 삭제** — 그 미러는 FW 7.10.70.00 / 16G Monolithic = **iDRAC9**. iDRAC10 미러는 저장소에 없다.
2. `NEXT_ACTIONS.md:75` "어떤 Family 도 PROVEN 아님" stale 교정 + ACC-D1 ↔ GIT-1 정합.
3. `docs/operate/05-vault.md:362-365, :379-381` 진입 조건 / `dryrun` 기본값 교정.

## 9.4 Property Contract 표 반영

`props` 데이터를 문서 표로 내보내 **코드 ↔ 문서 drift 를 구조적으로 차단**한다(선택: `scripts/ai/` export helper).

---

# 10. Risk / Rollback

| # | 위험 | 영향 | 완화 |
|---|---|---|---|
| R-1 | Family 분할/정렬이 실장비 4대의 Family 판정을 바꿈 | PROVEN 무효화 | replay golden 고정. P1 행동 변화 0. 분할 후 4대 재실행 |
| R-2 | drift-only PATCH 가 Lenovo XCC 권한 cache 손상 재발 | Repair 회귀 | `full_body_patch: True` 명시 유지 + 테스트 고정 |
| R-3 | `legacy_post_retry` 제거로 기존 2차 POST 성공 장비가 실패 | UNVERIFIED Create 실패 | 해당 경로는 **실장비 성공 증거 0건**(mock 만). 실패해도 `verification=failed` 로 정확히 보고되고 계정 상태 변화 없음 |
| R-4 | **drop-retry 사다리 제거**로 기존 `Locked` 거부 장비가 실패 | Repair 회귀 | `Locked` 는 이미 "실제 잠김일 때만" 전송으로 좁혀졌고(A10), `props` 가 read_only Family 에서 아예 제외한다 → 트리거 소멸. 실미러 4대 회귀로 확인 |
| R-5 | `write_rejections` 확장이 정보성 메시지를 거부로 오판 | 정상 쓰기 실패 처리 | MessageId 화이트리스트 + `RelatedProperties` 가 **요청한 Property 를 실제로 가리킬 때만**. 모든 Warning 을 실패로 보지 않음(02 §12) |
| R-6 | 신규 진단 필드가 envelope 계약 변경 | Consumer 파싱 오류 | 전부 `diagnosis.details.account_service` 하위(Additive) + drift check |
| R-7 | Auth budget 집행이 정상 검증을 조기 중단 | 성공을 실패로 보고 | 상한을 장비 선언값 기반으로 산출, 기본은 현행 schedule 이상. 초과 시에만 중단 + 명시 진단 |
| R-8 | `props` 기본값 `unverified` 전환으로 기존 Write 가 줄어듦 | 일부 Family 의 속성 수렴 실패 | **의도된 변화**. P2 에서 Write 가능한 모든 Family 에 6 Property 를 명시 선언한 뒤 전환. 미선언 Family 는 애초에 UNVERIFIED |
| R-9 | 미커밋 워킹트리와 충돌 | 작업 유실 | **P0 에서 검증 후 baseline commit**(§11 순서) |
| R-10 | 기존 테스트가 제거 대상 동작을 고정 | G-02 적용 불가 | P2 에서 `test_unverified_family_keeps_the_legacy_post_retry` 반전 + ADR 근거 기록 |
| R-11 | `protected` 분류가 정상 계정을 제외 | Repair 불가 | 근거는 `HostBootstrapAccount==true` 뿐(추론 아님). 실미러 3계정이 전부 `false` 라 회귀로 확인 가능 |
| R-12 | 운영 Job 은 게이트가 열리면 실쓰기 | 의도치 않은 운영 Write | 실장비 검증은 **Check Mode 우선**. D-4 확정으로 운영 Job 변경 없음 |

## 10.1 Rollback

| 상황 | 복구 |
|---|---|
| Account Write 회귀 | ① `-e _rf_account_service_dryrun=true` → 즉시 Write 0 ② Family 를 `generic_collection_post` 로 되돌림(데이터 1줄) ③ commit revert |
| 계정 상태 오변경 | 모든 쓰기는 **Standard Account 1개(target_username)** 에만 국한. Recovery/Admin/기타는 어떤 경로에서도 쓰기 대상 아님. Recovery 자격으로 원복 가능 |
| Family 오분류 | Create 는 **예약/protected 제외 + 빈 slot 1개**만 대상, 실패 시 cleanup PATCH 로 되돌림(:6202-6214). Repair 는 **exact member URI** 만 |
| 최악 | Recovery Account(Location×Vendor)로 접근 유지. Recovery 는 삭제·변경 대상이 아니다 |

**되돌릴 수 없는 작업은 계획에 없다.** DELETE 는 `allow_delete_recreate` opt-in 뿐이고 운영 playbook 이
이 인자를 넘기지 않는다(테스트 고정).

---

# 11. Execution Checklist

```text
[ P0 ] baseline 검증 → baseline commit  (순서 엄수 — 바로 commit 하지 않는다)
  [ ] git diff 검토 (redfish_gather.py / account_service.yml / dell_idrac9.yml + 신규 테스트/Evidence)
  [ ] 계정 unit test:  pytest tests/unit -k "account or credential" -q
  [ ] 계정 integration: pytest tests/integration/test_account_reconcile_replay.py -q
  [ ] full pytest:      pytest tests/ -q
  [ ] static gates:     output_schema_drift_check / verify_vendor_boundary / verify_harness_consistency
  [ ] syntax:           ansible-playbook --syntax-check ×3 + py_compile
  [ ] 위 전부 PASS 확인  ← 하나라도 FAIL 이면 commit 하지 않고 원인부터 해결
  [ ] baseline commit
  [ ] 본 문서를 docs/ai/contracts/redfish-account-write.md 로 기록
  [ ] task-impact-preview 5섹션 (rule 91 R1)

[ P1 ] 표현력 도입 — 행동 변화 0
  [ ] _ACCOUNT_PROP_DEFAULTS + account_prop_contract()  (P1 은 legacy-compatible default)
  [ ] defaults 에 props / create_uri / if_match / account_types_required /
      full_body_patch / isolated_write_patch(False) 추가
  [ ] _create_target_uri() 도입 (기본값 = 현행 accounts_uri)
  [ ] etag_required → if_match{create,repair} 치환 (create 는 전 Family False)
  [ ] out dict 신규 필드 + account_service.yml 노출
  [ ] pytest 전량 PASS + replay PASS  ← **행동 변화 0 확인**

[ P2 ] 계약 충돌 교정
  [ ] G-02 legacy_post_retry 제거
  [ ]   └ test_unverified_family_keeps_the_legacy_post_retry 반전 (R-10)
  [ ] G-03 write_rejections() (RelatedProperties / Severity / policy_rejected)
  [ ] 지시 3: drop-and-retry 사다리 제거 (generic payload fallback 신설 금지)
  [ ] G-09 PCR 을 props 로 gate — **처음부터 보내지 않는다** (droppable 추가 철회)
  [ ] G-10 drift-only 조립 (+ Lenovo full_body_patch 반례 보존)
  [ ] G-11 account_types_required 검증 분리 + Supermicro presence
  [ ] props 전역 기본값을 unverified 로 전환 + Write 가능 Family 6 Property 명시 선언
  [ ] pytest 전량 PASS

[ P3 ] HPE Firmware Evidence 분리 — Family 분할 없음
  [ ] hpe_isolation_evidence(firmware, model) 추가
  [ ] isolation_basis / evidence / firmware_advisory 산출 + 진단 노출
  [ ] isolated_write_patch 동작 유지 확인 (전 iLO5/6/7)
  [ ] adapters hpe_ilo5/6/7 origin 주석 (a00159600en_us)
  [ ] iLO6 1.73 실장비 회귀 (Case A + evidence=proven 이 이 Firmware 에만)

[ P4 ] Family 세분화
  [ ] G-06 lenovo_xcc2 / lenovo_xcc3 분할
  [ ] G-07 HostBootstrapAccount 기반 protected 분류 (열거 유지 / candidate 제외 / protected_conflict)
  [ ] G-20 Lenovo capability-first 정렬 + Purley 부정 신호
  [ ] G-14 cisco_cimc3_instance_post
  [ ] G-15 qct 3분할 (동작 동일)
  [ ] G-19 Supermicro Superchip 경계
  [ ] §3.5 Supermicro create_uri 결정 규칙 (장비값 Generation 근거 확보 포함)
  [ ] G-21 죽은 _ACCOUNT_CREATE_STRATEGY 제거
  [ ] Cisco id_range 는 변경하지 않는다 (G-23 삭제)
  [ ] adapters origin 주석 5건

[ P5 ] 진단 축
  [ ] G-05 Huawei Redfish Login Interface 관측 (쓰기 0)
  [ ] G-12 policy_conflict 노출 (차단·완화·회전 0)
  [ ] G-13 auth budget 집행 (retry 증가 금지)
  [ ] G-17 RoleId 미지원 진단
  [ ] G-18 HTTPBasicAuth / AuthMethods 관측

[ P6 ] 검증
  [ ] pytest tests/ -q 전량 PASS
  [ ] Check Mode Write 0 / Second Run Write 0 / blind write fallback 0
  [ ] protected_conflict Write 0 / unverified Property 자동 Write 0
  [ ] static gates + syntax ×3 + baseline 회귀
  [ ] Secret 누출 0 (신규 필드 포함)

[ P7 ] 문서 + 실장비
  [ ] Compatibility Matrix (Family × Firmware × Evidence × Workaround Basis)
  [ ] G-25 drift 교정 3건
  [ ] ADR 작성 (rule 70 R8)
  [ ] EXTERNAL_CONTRACTS / LAB_PENDING_MATRIX / CURRENT_STATE / NEXT_ACTIONS / TEST_HISTORY / `docs/operate/05-vault.md`
  [ ] git Location 4대 재실행 (Check Mode 먼저 → Case A + 2차 Write 0)
  [ ] 계약 정합 검증 기록 — CURRENT_STATE 2026-08-13 절
  [ ] commit + push (rule 93) + production 승격 판단
```

---

# 12. Definition of Done

## 12.1 계약 정합

- [ ] 9 Vendor 조사와 코드 Contract 가 **충돌하지 않는다** (Gap Matrix **25건** 처리 — G-23 은 삭제)
- [ ] Property semantics 를 Vendor 전체에 잘못 일반화하지 않는다 (`props` = Family × Operation)
- [ ] Strategy 선택이 **Family / Firmware / Actual Capability** 기반 (adapter hint 는 마지막)
- [ ] **HPE broad rule 이 Evidence 로 번지지 않는다** — iLO5 / iLO6 1.73 / 1.74 / 1.75+ / iLO7 1.19·1.20 / 1.21+ 가 `isolation_basis` 로 구분되고, `safety_strategy` 는 Vendor mandatory 또는 LIVE-PROVEN 으로 표기되지 않는다
- [ ] Dell iDRAC9 ↔ iDRAC10 Family 가 실제로 구분된다
- [ ] Cisco CIMC ↔ 최신 BMC 가 하나의 Strategy 로 묶여 있지 않다
- [ ] **Supermicro Accounts discovery URI 와 Create URI 가 같은 개념으로 묶여 있지 않고, 최신·legacy URI 를 혼용하지 않는다**
- [ ] Lenovo Family 별 Locked / PCR / AccountTypes 계약이 분리돼 있다
- [ ] **`HostBootstrapAccount` 기반 protected 분류가 동작하고 XCC3 전용으로 취급하지 않는다**
- [ ] Huawei `Locked` 가 제거되지 않았고 실제 `locked=true` 일 때만 쓰인다
- [ ] Quanta 에 `AccountTypes=["Redfish"]` / PCR generic retry / generic ETag 가 **없다**
- [ ] **Inspur Create POST 에 If-Match 없음 / Repair PATCH 에 If-Match 있음**
- [ ] Family 표와 모순되는 `vendor → create method` 표가 병존하지 않는다
- [ ] 문서(Matrix / NEXT_ACTIONS / `docs/operate/05-vault.md`)가 실측과 어긋나지 않는다

## 12.2 안전 불변식 (테스트로 고정)

- [ ] **UNKNOWN Enumeration Write 0**
- [ ] **Check Mode Write 0**
- [ ] **blind write fallback 0** — 허용 예외는 (A) ETag 412 동일 URI·동일 payload 1회 (B) Family 사전 정의 deterministic sequence(HPE isolated) 뿐
- [ ] **PasswordChangeRequired generic retry 0**
- [ ] **unverified Property 자동 Write 0**
- [ ] **protected_conflict → Write 0** / protected 가 ABSENT 로 오판되지 않음
- [ ] **Recovery 가 final Gathering 에 사용되는 경우 0**
- [ ] **HTTP 2xx 만으로 convergence success 처리 0**
- [ ] **Fresh Standard Auth 없는 `recovered=true` 0**
- [ ] **Second Run Write 0**
- [ ] **Cisco ID 범위 추측 수정 0**
- [ ] 기존 Recovery/Admin 삭제 0 / Slot 확보 삭제 0 / Password·Lockout 정책 완화 0 / Basic Auth 자동 enable 0 / Global Standard Password 자동 변경·회전 0

## 12.3 회귀 / 품질

- [ ] 기존 non-Redfish Gathering(OS / ESXi) 회귀 없음
- [ ] envelope 13 필드 불변 (신규는 전부 `diagnosis.details.account_service` 하위)
- [ ] `pytest tests/ -q` 전량 PASS
- [ ] static gates exit 0 / `--syntax-check` ×3 PASS
- [ ] Credential / Secret 로그 노출 없음

## 12.4 문서

- [ ] Matrix 가 `LIVE-PROVEN / OFFICIAL / ADVISORY-DERIVED / DOCUMENTED / UNVERIFIED` 와 Firmware-specific risk 를 **분리** 표기
- [ ] 실장비 검증 Vendor 와 미검증 Vendor 구분
- [ ] "구현 대상" 과 "조사 필요 대상" 분리
- [ ] ADR + Evidence 기록 완료

---

# 13. rev.2 자체 모순 검사

| # | 명제 | 계획 내 근거 | 판정 |
|---|---|---|---|
| 1 | UNVERIFIED blind write fallback 0 | G-02 제거(F-04) + F-09 사다리 제거 + §3.8 + 7.1 `test_account_no_write_fallback` | **정합** |
| 2 | PasswordChangeRequired generic retry 0 | G-02 제거 + G-09 를 `props` gate 로 전환하고 **droppable 추가 철회**(F-09) | **정합** — rev.1 의 F-08 ↔ G-02 모순 제거됨 |
| 3 | HPE deterministic isolated sequence 는 fallback 과 구분 | §3.8 [B] 에 명시. 쓰기 **전에** Family 가 확정하는 순서이며 응답을 보고 방식을 바꾸지 않음 | **정합** |
| 4 | Inspur Create POST 에 If-Match 없음 | §3.4 `if_match:{'create':False}` / F-20 / 6.6 / 7.1 Inspur ETag 테스트 | **정합** — rev.1 의 "Create·Repair 양쪽" 문구 삭제됨 |
| 5 | Inspur Repair PATCH 에 If-Match 있음 | §3.4 `{'repair':True}` / A12 / 6.6 | **정합** |
| 6 | Supermicro 최신·legacy Create URI 혼용 없음 | §3.5 결정 규칙(IF/ELSE 단일 선택) + §3.3 금지 + 7.1 create_uri 테스트 | **정합** |
| 7 | protected account 가 ABSENT 로 오판되지 않음 | §3.6(열거 유지, candidate 만 제외) + F-14 + 7.1/7.5 protected 테스트 | **정합** — 단순 제거 방식 철회됨 |
| 8 | unverified Property 자동 Write 0 | §3.2 최종 기본값 `unverified` + 소비 규칙 표 + P2 전환 + 7.1 | **정합** |
| 9 | Cisco ID 범위 추측 수정 0 | G-23 삭제 + A27 실측 + 6.4 "변경 없음" + §8.4 조사 항목으로 이관 | **정합** |
| 10 | HTTP 2xx 만으로 convergence success 0 | A6/A8/A9 + §3.9 6단계 + G-03 | **정합** |
| 11 | Fresh Standard Auth 없는 `recovered=true` 0 | A8/A9 + §3.9 | **정합** |
| 12 | Check Mode Write 0 | A17 + 7.4 | **정합** |
| 13 | Second Run Write 0 | A25 + 7.6 | **정합** |
| 14 | HPE 동작은 유지, Evidence 만 구분 | §3.7 (Family 분할 없음, metadata 분리) + 6.1 + 9.2 | **정합** — rev.1 의 4-Family 분할 철회됨 |
| 15 | P1 행동 변화 0 ↔ props 기본값 `unverified` | §3.2 에서 P1=legacy-compatible / P2=전환으로 **단계 분리**. R-8 에 의도된 변화로 기록 | **정합** |
| 16 | drop-retry 제거 ↔ Lenovo `Locked` 거부 실측 | A10 이 이미 `Locked` 를 조건부 전송으로 좁혔고, `props` 가 read_only Family 에서 제외 → 트리거 소멸. R-4 에 기록 | **정합** |
| 17 | drift-only ↔ Lenovo 권한 cache 손상 실측 | `full_body_patch: True` opt-out 유지(G-10 / 6.3 / R-2) | **정합** |

**검출된 모순 0건.** rev.1 대비 해소된 모순: F-08 ↔ G-02(항목 2), Inspur Create If-Match(항목 4),
protected 단순 제거(항목 7), HPE 과분할(항목 14).

---

## 부록 A — 검증 명령

```bash
python -m pytest tests/ -q
python -m pytest tests/unit -k "account or credential" -q
python -m pytest tests/integration/test_account_reconcile_replay.py -q
python scripts/ai/hooks/output_schema_drift_check.py
python scripts/ai/verify_vendor_boundary.py
python scripts/ai/verify_harness_consistency.py
ansible-playbook --syntax-check redfish-gather/site.yml
python -m py_compile redfish-gather/library/redfish_gather.py
```

## 부록 B — 남은 D-item (사용자 판단 필요)

rev.1 의 D-1 / D-2 / D-4 / D-5 는 **사용자 지시 10 으로 전부 확정**됐다. D-3(Supermicro)는
§3.5 결정 규칙으로 기술적 판단이 되어 D-item 이 아니다. 남는 것은 다음 2건이며 **둘 다 본 계획의
코드 범위 밖**이다.

| # | 결정 | 왜 사용자 판단인가 | 상태 |
|---|---|---|---|
| **D-A** | **Global Standard Password 정책 교집합** — Matrix §4 의 A/B/C/D 중 선택 (지원 대상 BMC Password Policy 를 제품 사전조건으로 정의 / 운영 승인 하 BMC Policy 표준화 / "모든 Vendor 동일 Password 1개" 재검토 / 모순 조합을 지원 Matrix 에서 제외) | Cisco Strong(max 14) ↔ Inspur MinPasswordLength(최대 16) 교집합이 **수학적으로 빌 수 있다**. 코드로 해결할 문제가 아니라 제품 Contract 결정. 본 계획은 **진단만** 한다(G-12) | 미결 (기존 ACC-D2) |
| **D-B** | **audit H-5** — `empty_accounts` 를 `GATHER_FAILED` 대신 `CREDENTIAL_SET_UNAVAILABLE` 로 보고할 것인가 | Portal 사용자 Message 가 5번 문장 → 4번 문장으로 바뀐다. **Consumer 영향 결정** | 미결 (기존 ACC-D4) |

확정된 항목(재확인 불요): **D-1** `legacy_post_retry` 제거 / **D-2** HPE Password-only PATCH 동작 유지 +
Evidence 만 Firmware 별 구분 / **D-4** real-write default 현행 유지·Check Mode Write 0·Jenkins 운영 정책 변경 범위 밖 /
**D-5** Global Password 자동 변경·회전 없음, 진단 + 실제 Write Response 판정.

## 부록 C — 참조 정본

| 구분 | 경로 |
|---|---|
| 구현 정본 | `redfish-gather/library/redfish_gather.py` (Family 표 :5076 / 선택 :5180 / provision :5548) |
| Ansible | `redfish-gather/tasks/account_service.yml`, `account_service_try_one.yml`, `site.yml:148-153` |
| Credential | `module_utils/credential_common.py:54-55`, `common/tasks/credential/` |
| AS-IS 감사 | AS-IS 전수조사(정리됨) |
| 호환성 Matrix | Vendor × Family 매트릭스 |
| 실장비 Evidence | `tests/evidence/2026-08-12-{git-location-live-verification,standard-password-convergence,redfish-standard-account-separation}.md` |
| 실미러 | `tests/reference/redfish/**` (Lenovo `HostBootstrapAccount` 실측 포함) |
| DMTF 스키마 | `schema/redfish_dmtf_2026.1/ManagerAccount.v1_14_1.json:323` (`HostBootstrapAccount`) |
| 조사 문서 9건 | `C:\Users\hshwa\Downloads\redfish계정변경\0{1..9}_*_DELTA_RESEARCH_2026-08-12.md` |
