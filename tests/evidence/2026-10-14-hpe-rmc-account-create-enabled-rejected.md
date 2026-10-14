# HPE CSUS 3200 (RMC) — 표준 계정 생성 POST 가 `Enabled` 로 거부됨 · hotfix `hpe_rmc` (2026-10-14)

- 일자: 2026-10-14
- 보고: 사용자 사이트 운영 수집(Jenkins 수집 Job, Redfish 채널). 장비는 HPE Compute Scale-up Server 3200 (RMC).
- 수행: AI (Claude Code) — 읽기 전용 조사 → 사용자 승인 뒤 hotfix. **비밀번호 · Vault 값은 이 문서에 없다.**
- 같은 날 보고된 Lenovo 건은 결함이 아니었다 (아래 3절).

## 1. 관측 (사용자 제공 봉투 발췌)

| 항목 | 값 |
|---|---|
| `diagnosis.failure_reason` · `errors[].message` | "대상 Redfish 계정과 개더링 표준 계정이 다르거나 권한이 없습니다." (`auth_rejected` — 표준 계정 401 확정) |
| `errors[].detail` | `Systems 컬렉션 실패: HTTP 401 Unauthorized` · `primary/common_infraops: status=failed first_auth=401 …` |
| `diagnosis.details.account_service.write_response` | `Base.1.17.GeneralError` · "A general error has occurred. See Resolution for information on how to resolve the error, or @Message.ExtendedInfo if Resolution is not provided." · **"The property Enabled is not in the list of valid properties for the resource."** · "Remove the unknown property from the request body and resubmit the request if the operation failed." |

읽는 법: 표준 계정(`infraops`)이 401 → 복구 계정(`vault/<loc>/redfish/hpe.yml`, role=recovery) 인증 **성공** → AccountService 열거 → `infraops` 부재(absent) →
생성 POST → RMC 가 본문의 `Enabled` 를 미지원 속성(`PropertyUnknown`)으로 **요청 전체 거부** → 1회 결정적 쓰기 원칙(재시도 금지)에 따라 실패 → 표준 계정 생성 실패 → 수집 실패.

## 2. 원인 (코드)

- `resolve_account_family()` 는 adapter hint 에 `csus`/`superdome` 이 있으면 `generic_collection_post` 를 돌려줬다
  ("create payload 공식 근거 미확보 → generic 유지").
- generic Family 는 `_ACCOUNT_PROP_DEFAULTS` 를 그대로 쓴다 — `Enabled: {create: writable}` → `build_create_payload()` 가 `{UserName, Password, Enabled: true, RoleId}` 를 만든다.
- RMC(RedfishVersion 1.19 · Base 1.17 registry) 의 ManagerAccount POST 는 `Enabled` 를 받지 않는다 (사이트 실측). bmcweb 계열 메시지 형식.
- 공식 RMC 계정 계약 문서는 확보하지 못했다 (DOCUMENT-GAP). 2026-10-14 web 검색 4회: HPE servermanagementportal(iLO 5/6/7 AccountService 만) ·
  Lenovo/Supermicro/OpenBMC 계정 POST 문서 · `hewlettpackard/sdflexutils`(계정 API 없음) · HPE Superdome Flex Administration 안내 페이지 — RMC 전용 계정 계약 없음.
  저장소 CSUS 미러(`tests/fixtures/redfish/hpe_csus_3200/`, 2026-06-15)에도 AccountService 캡처가 없다.
  → **사용자 사이트 실측(거부 응답)이 1차 근거** (rule 25 R7-A-1).

## 3. 같은 날 Lenovo 건 — 결함 아님 (기록)

- 문장 "개더링 표준 계정으로 대상 Redfish에 인증하지 못했습니다" = `auth_unconfirmed` (첫 자격 응답이 401 도 2xx 도 아님).
- 사용자 확인: 사람이 미리 만든 `infraops` 의 **비밀번호가 만료** → BMC 가 401 아닌 응답(403 계열) → 계약(CLAUDE.md §8: 403/5xx/timeout 은 비밀번호 불일치가 아님, Account Write 0)대로 복구 미진입.
- 개선 여지(후속, 코드 미변경): 첫 자격 응답 4xx 의 `@Message.ExtendedInfo[].MessageId` 를 결과에 남겨 문장을 가르는 것(`docs/ai/NEXT_ACTIONS.md` 2026-10-14 절).
- 함께 확인한 사실: 수집 계정은 전역 `infraops` 1개(`vault/common/redfish/standard.yml`), 벤더별 파일은 복구 전용(Lenovo 4 Location `USERID`, Location 마다 비밀번호 다름 — ic=yi / cj / git).
  표준 계정 선택 경로(`credential_resolver` → `load_one.yml` → `resolve_and_load_redfish.yml` → `load_vault.yml` → `collect_standard.yml` → `try_one_account.yml`) 결함 없음.

## 4. 변경 (hotfix)

`redfish-gather/library/redfish_gather.py`
1. `_ACCOUNT_FAMILIES['hpe_rmc']` 신설 — `evidence: unverified`, `props.Enabled = {create: unsupported, repair: unverified}`. 나머지 속성은 기본(Locked/PCR/AccountTypes create unsupported · repair unverified).
2. `resolve_account_family()` HPE 분기: hint `csus`/`superdome` → `hpe_rmc`.
3. `account_service_discover()` 계정 레코드 `enabled` 를 3-상태로 (`_bool_or_none`: 속성 없음/비-bool → None). 종전 `bool(default=False)` 은 "속성 없음" 을 "비활성" 으로 만들었다.
4. 복구 PATCH: `Enabled` 는 `full_body` Family 또는 **관측 `enabled is False`** 일 때만 싣는다 (종전 `is not True` 는 None 도 보냈다 → RMC 에서 repair 도 같은 거부).
불변: 재시도 사다리 없음 · 401 게이트 · 잠금 예산 · 재조회+표준 자격 재인증 검증 · envelope 13 필드.

시험: `tests/unit/test_account_hpe_rmc_enabled.py`(신규 13) · `test_account_family_and_write_contract.py::test_hpe_rmc_is_not_treated_as_ilo`(갱신). 결과는 `docs/ai/catalogs/TEST_HISTORY.md` 2026-10-14.

## 5. 이 문서가 증명하지 않는 것

- RMC 가 `{UserName, Password, RoleId}` 를 **수락**하는지 — 실장비로만 확정된다 (production Job canary, 사용자 수행).
- RMC 계정 리소스가 `Enabled` 를 GET 에서 노출하는지 (repair 계약 `unverified` 로 둔 이유).
- Superdome Flex(CSUS 3200 의 전신) 가 같은 거부를 하는지 — 같은 RMC 계열이라 같은 Family 로 묶었지만 실측 없음.

## 6. 배포 결정

- 사용자 지시(2026-10-14): "최대한 빨리 production 반영". 이 hotfix 에 한해 rule 93 R2 예외 2 의 "같은 main SHA main Job 1회 성공" 전제를 사용자 지시로 대체하고,
  로컬 gate 통과 즉시 `prodgen promote` → 승격 직후 production Job canary(CSUS 3200 1대)로 확인한다. 결정 주체: 사용자.
