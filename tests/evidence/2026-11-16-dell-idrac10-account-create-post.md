# 2026-11-16 — Dell iDRAC10 표준 계정 생성 = Collection POST · Dell/Lenovo 세대 판별 정정 (검증 기록)

> 누가: 사용자 보고 · 요청(2026-11-16 대화 — 사이트 iDRAC10 생성 실패 · 긴급 조치로 성공 확인 · 원인 분석 · 정식 수정 · 다른 제조사 점검 ·
> 생성 실패 시 Gathering 차단 확인 · 시험 · 회귀) → AI 가 분석 · 구현 · 검증 · 기록. 계획은 같은 대화에서 사용자가 승인했다.
> 언제: 2026-11-16. 무엇: 코드 · 시험 커밋 `016c46ad` + 이 기록을 담은 문서 커밋. 결정 근거: `docs/reference/decision-log.md` 2026-11-16.
> **실장비 검증이 아니다.** lab 에 iDRAC10 · Lenovo Purley 가 없다. iDRAC10 Collection POST 생성의 실측은 사용자 사이트 보고 1건
> (긴급 조치 사본 — 원본 envelope · Accounts 미캡처)뿐이다. 3절 이하는 모듈 재생 · 시험이다.

## 1. 사이트 관측 (사용자 보고)

| 항목 | 내용 |
|---|---|
| 장비 | Dell iDRAC10 1대 (Manager Model · FirmwareVersion 값은 받지 못했다) |
| `errors[].message` | `표준 관리 계정을 정리하지 못했습니다. 계정 상태와 권한을 확인하세요.` |
| `errors[].detail` | `빈 계정 슬롯이 없어 표준 계정을 만들 수 없습니다. 사용하지 않는 계정을 정리하세요.` |
| 긴급 조치 | `redfish_gather.py` `_ACCOUNT_FAMILIES['dell_idrac10_slot_patch']` 의 `create_method` 를 `slot_patch` → `collection_post` (한 줄) |
| 조치 뒤 | 재시도에서 계정 생성 성공 로그 확인 |

## 2. 원인

### 2.1 확인한 사실

1. 모듈은 이 장비에 Family `dell_idrac10_slot_patch`(생성 = 미리 깔린 빈 slot 에 PATCH)를 썼다. 생성 경로는 빈 slot(UserName 키 있음 + `""` + Enabled
   false, 예약 slot {1, 2} · 보호 계정 제외)을 찾고, 없으면 **쓰기 전에** 위 detail 로 끝난다. 3절 HEAD 재생이 같은 문장 · 쓰기 0건을 낸다.
2. Dell 공식 계약: iDRAC10 은 첫 릴리스 1.10.17.00 부터 `ManagerAccountCollection` POST 로 사용자를 만든다
   (developer.dell.com iDRAC10 Redfish API "What's New"). Dell 공식 스크립트 `Invoke-CreateIdracUserPasswordREDFISH`
   (github.com/dell/iDRAC-Redfish-Scripting)는 Manager.Model 12G~16G 에 `Accounts/<id>` PATCH, 그 밖(iDRAC10)에 `AccountService/Accounts` POST(201) · DELETE(204).
3. iDRAC7/8/9 는 slot 모델이다. 저장소 iDRAC9 7.10.70.00 미러의 PrivilegeRegistry
   (`tests/reference/redfish/dell/10_100_15_27/redfish_v1_managers_idrac.embedded.1_privilegeregistry.json`)에서 `ManagerAccountCollection` 은
   GET · HEAD 만, `ManagerAccount` 는 PATCH 를 허용한다.
4. 저장소에 iDRAC10 Accounts 실측이 없다 — Dell 미러 5대는 모두 iDRAC9 R760 7.10.70.00 이다. 2026-08-12 iDRAC10 Family 를 iDRAC9 에서 갈라낼 때
   문서로 확인한 것은 예약 slot(1, 2)뿐이고, 생성 방식은 iDRAC9 의 slot PATCH 를 근거 없이 물려받았다(당시 compat matrix 의 iDRAC10 Create `UNVERIFIED`).
5. 사이트에서 생성 방식만 Collection POST 로 바꾸자 생성 · 재인증이 성공했다(사용자 보고).

### 2.2 추정 (사이트 Accounts 캡처로 확정할 것)

iDRAC10 Accounts 는 만들어진 계정만 보여 주는 동적 모델로 보인다(Local User 32, POST 생성 · DELETE 삭제). 그래서 "UserName 이 빈 미리 깔린 slot" 이 없다.
빈 항목이 있었더라도 빈 slot 판정을 통과하지 못했을 수 있다. 어느 쪽이든 slot 모델은 iDRAC10 에 맞지 않는다.

## 3. 재생 — HEAD · 긴급 조치 · 정식 수정 (네트워크 0)

- 판본: HEAD 사본은 `git show 73ef16b8:redfish-gather/library/redfish_gather.py` 와 같은 바이트(sha1 `c55b0725ac1b…`).
  긴급 조치 사본은 HEAD 와 8003행(`create_method`) 한 줄만 다르다. 정식 수정은 작업 트리(커밋 `016c46ad` 와 같은 내용).
- 입력: `account_service_provision` 을 운영과 같은 인자 모양으로 부른다(Dell 1차 adapter hint `redfish_dell_idrac10`, Lenovo `redfish_lenovo_xcc3` —
  무인증 1차 선택이라 늘 priority 최상위다). 열거 결과 · Manager 는 아래 장비 모양을 넣고, 쓰기 응답은 공식 계약대로 stub 한다 —
  slot 모델 POST 405 · PATCH 200, iDRAC10 POST 201(`@odata.id` = `Accounts/3`). 자격은 자리표시자다.
- 한계: iDRAC8/9 의 POST 405 는 2.1-2 · 3 의 문서 · 미러 근거로 둔 값이다. iDRAC8/9 실장비에 POST 를 보내 본 것은 아니다.

| 장비 모양 | 판본 | Family | method | POST | PATCH | 쓰기 대상 | recovered | 첫 오류 |
|---|---|---|---|---|---|---|---|---|
| Dell iDRAC10 17G/1.20 (동적) | HEAD | `dell_idrac10_slot_patch` | patch_empty_slot | 0 | 0 | — | False | 빈 계정 슬롯이 없어 표준 계정을 만들 수 없습니다… |
| Dell iDRAC10 17G/1.20 (동적) | 긴급 조치 | `dell_idrac10_slot_patch` | post_new | 1 | 0 | `AccountService/Accounts` | True | |
| Dell iDRAC10 17G/1.20 (동적) | 정식 수정 | `dell_idrac10_collection_post` | post_new | 1 | 0 | `AccountService/Accounts` | True | |
| Dell R760 iDRAC9 16G/7.10 | HEAD · 긴급 조치 · 정식 수정 | `dell_slot_patch` | patch_empty_slot | 0 | 1 | slot 3 | True | |
| Dell R740 iDRAC9 14G/3.36 | HEAD | `dell_idrac10_slot_patch` | patch_empty_slot | 0 | 1 | slot 3 | True | |
| Dell R740 iDRAC9 14G/3.36 | 긴급 조치 | `dell_idrac10_slot_patch` | post_new | 1 | 0 | `AccountService/Accounts` | **False** | 표준 계정 생성 요청이 거부됐습니다. |
| Dell R740 iDRAC9 14G/3.36 | 정식 수정 | `dell_slot_patch` | patch_empty_slot | 0 | 1 | slot 3 | True | |
| Dell R630 iDRAC8 13G/2.86 | HEAD | `dell_idrac10_slot_patch` | patch_empty_slot | 0 | 1 | slot 3 | True | |
| Dell R630 iDRAC8 13G/2.86 | 긴급 조치 | `dell_idrac10_slot_patch` | post_new | 1 | 0 | `AccountService/Accounts` | **False** | 표준 계정 생성 요청이 거부됐습니다. |
| Dell R630 iDRAC8 13G/2.86 | 정식 수정 | `dell_slot_patch` | patch_empty_slot | 0 | 1 | slot 3 | True | |
| Dell Manager 미확인 + 16 slot | HEAD | `dell_idrac10_slot_patch` | patch_empty_slot | 0 | 1 | slot 3 | True | |
| Dell Manager 미확인 + 16 slot | 긴급 조치 | `dell_idrac10_slot_patch` | post_new | 1 | 0 | `AccountService/Accounts` | **False** | 표준 계정 생성 요청이 거부됐습니다. |
| Dell Manager 미확인 + 16 slot | 정식 수정 | `dell_slot_patch` | patch_empty_slot | 0 | 1 | slot 3 | True | |
| Dell Manager 미확인 + 동적 | HEAD | `dell_idrac10_slot_patch` | patch_empty_slot | 0 | 0 | — | False | 빈 계정 슬롯이 없어 표준 계정을 만들 수 없습니다… |
| Dell Manager 미확인 + 동적 | 긴급 조치 · 정식 수정 | 긴급 `dell_idrac10_slot_patch` / 정식 `dell_idrac10_collection_post` | post_new | 1 | 0 | `AccountService/Accounts` | True | |
| Lenovo XCC1 Purley 12 slot | HEAD · 긴급 조치 | `lenovo_xcc2_accounttypes` | post_new | 1 | 0 | `AccountService/Accounts` | **False** | 표준 계정 생성 요청이 거부됐습니다. |
| Lenovo XCC1 Purley 12 slot | 정식 수정 | `lenovo_purley_slot_patch` | patch_empty_slot | 0 | 1 | slot 2 | True | |

읽는 법:
- HEAD 는 사이트와 같은 실패를 쓰기 0건으로 재현한다(iDRAC10 동적).
- 긴급 조치는 iDRAC10 을 고치지만, 세대 판별이 hint 로 새는 iDRAC8(2.x) · 초기 iDRAC9(3.x) · Manager 미확인 Dell 에 지원하지 않는 POST 를 1회 보낸다.
  HEAD 에서 이 장비들이 iDRAC10 Family 로 잡히고도 맞게 동작한 것은 두 Family 의 생성 방식이 같았기 때문이다.
- Lenovo Purley 는 2026-10-27 부터 HEAD 에서 이미 POST Family 로 간다(긴급 조치와 무관한 별개 회귀).
- 정식 수정은 7가지 모양 모두 해당 세대의 계약대로 쓴다.

## 4. `slot_patch` 와 `collection_post`

| 항목 | `slot_patch` | `collection_post` |
|---|---|---|
| 전제 | BMC 가 고정 계정 배열을 미리 깐다(iDRAC7/8/9 16개, Lenovo Purley 12개). 빈 자리는 UserName `""` | BMC 가 계정 리소스를 만들고 Id 를 정한다 |
| 생성 | 첫 빈 · 비예약 slot `Accounts/<id>` 에 PATCH {UserName, Password, Enabled, RoleId} | `AccountService/Accounts` 에 POST 같은 본문(Id 없음) → 201 + `@odata.id`(없으면 다시 열거해서 찾는다) |
| 빈 자리 없음 | 쓰기 전에 실패 — 이번 사이트 오류 | 해당 없음 |
| 검증 실패 시 | 그 slot 을 비우는 정리 PATCH 1회 | 정리 없음(삭제하지 않는다) |
| 공통 | 표준 계정 401 + 복구 계정 인증 성공일 때만 쓰기 · 존재 판정(있으면 비밀번호 동기화 PATCH, `unknown` 이면 쓰기 0) · 결정적 쓰기 1회(실패 뒤 다른 URI · 본문으로 재시도 없음) · 재조회 + 표준 계정 재인증 | 같음 |

기존 계정 비밀번호 동기화는 두 모델 모두 PATCH 다(표준). "PATCH 를 전부 POST 로" 바꾸지 않은 이유다 — iDRAC7/8/9 · Lenovo Purley 는 Collection POST 생성이 없다.

## 5. 변경 (커밋 `016c46ad`)

| 파일 | 변경 |
|---|---|
| `redfish-gather/library/redfish_gather.py` | Family `dell_idrac10_slot_patch` → `dell_idrac10_collection_post`(create_method `collection_post`, 본문 Id 없음, Locked · AccountTypes 는 생성 때 보내지 않음, 예약 {1, 2} 는 기록용, evidence `documented`) + origin 주석 |
| 〃 `resolve_account_family` Dell | 판별 순서 ① Manager.Model `<NN>G`(12~16 = slot · 17+ = POST) 또는 Model 의 `idrac10` → ② Firmware major(1 = POST · 2~7 = slot) → ③ 계정 목록 모양(빈 slot 미리 깔림 = slot) → ④ hint → 근거 0 이면 slot. reasons 에 `model_gen` · `fw_major` · `prepopulated` · `hint_idrac10` · `basis` |
| 〃 `resolve_account_family` Lenovo | Manager.Model 이 숫자 없는 XCC 1세대이고 빈 slot 이 미리 깔려 있으면 XCC2/3 판정보다 먼저 `lenovo_purley_slot_patch` |
| 〃 재생성(opt-in) 차단 | Dell 전 세대 차단 유지. 기술 메시지만 세대별(iDRAC7/8/9 = PATCH-only, iDRAC10 = 재생성 미검증 · 수동 복구) |
| 〃 주석 | `_delete` docstring · 헤더 매트릭스 · slot 경로 주석의 "Dell = POST/DELETE 미지원" 을 세대별로 정정 |
| `redfish-gather/site.yml` | 표준 계정 재수집(Phase 3) 조건에 `verification == 'verified'` 추가 — 오류 행 판정(`account_service.yml` 실패 판정)과 같은 조건. 현 모듈은 recovered=true 일 때 늘 verified 라 동작 변화 0(방어선) |
| `adapters/redfish/dell_idrac9.yml` | 주석 — iDRAC10 Family 이름 · 판별 순서 |
| 시험 | 새 `tests/unit/test_account_create_method_by_generation.py` · `test_account_family_and_write_contract.py` 갱신(id · 의도된 동작 변경 1건: Manager 없음 + 16 slot 이면 slot 모양이 hint 를 이긴다) · `test_redfish_standard_recovery_contract.py` 강화 |

바뀌지 않은 것: envelope 13 필드 · `failure_code` · `failure_stage` · schema version · Jenkinsfile · callback · vault · baseline · 정상 경로(표준 계정 인증 성공 → 쓰기 0).
보이는 값 하나: 복구 경로 결과의 `diagnosis.details.account_service.family` 값 `dell_idrac10_slot_patch` → `dell_idrac10_collection_post`(schema · baseline · 예시에 없음).

## 6. 다른 제조사 · 모델 점검

모듈의 Family 는 20종이다. 수정 전에는 slot PATCH 생성이 3종(Dell 2 · Lenovo Purley 1)이고 나머지 17종이 POST 였다. 수정 뒤에는 slot PATCH 2종
(`dell_slot_patch` · `lenovo_purley_slot_patch`) · POST 18종이다(Collection POST 17 · Cisco IMC 3.x 계정 번호 URI POST 1 — `cisco_cimc3_instance_post`).
Lenovo Purley 는 Family 정의가 아니라 판별이 바뀌었다(2026-10-27 부터 이 Family 에 도달하지 못했다).

| 대상 | 생성 (수정 전 → 후) | 판정 · 근거 |
|---|---|---|
| Dell iDRAC7/8/9 (≤16G, Firmware 2~7) | slot PATCH → slot PATCH | [OK] Dell 공식(Collection POST 없음) + 사이트 iDRAC9 실측. 세대 판별이 hint 로 새던 것만 고쳤다 |
| Dell iDRAC10 (17G, Firmware 1.x) | slot PATCH → **Collection POST** | [MOD] Dell 공식 + 사용자 사이트 보고 |
| Lenovo XCC1 Purley | POST(2026-10-27 회귀) → **slot PATCH** | [MOD] Lenovo 공식(pubs.lenovo.com xcc-restapi). lab 부재 |
| Lenovo XCC1 Whitley/AMD · XCC2 · XCC3 | POST → POST | [OK] Lenovo 공식 + Whitley 미러 `tests/reference/redfish/lenovo/10_50_11_232`(동적 3계정) · XCC3 사이트 |
| Lenovo IMM2 | generic POST → 같음 | [INFO] 근거 미확보, 변경 없음 |
| HPE iLO4/5/6/7 · RMC | POST → POST | [OK] |
| Supermicro · Cisco CIMC(3.x · 4.1+ · 최신 BMC) | POST(Collection · Id 포함 · 인스턴스) → 같음 | [OK] |
| Huawei · Inspur · Fujitsu · Quanta | POST → POST | [INFO] lab 부재 · unverified, 변경 없음 |

## 7. 생성 실패 시 Gathering 차단

- 생성 실패 경로(빈 slot 없음 · POST 거부 · 응답 유실 · 재인증 실패 · 상태 불일치 · 열거 불완전)는 모두 `recovered=false` 다.
- 표준 계정 재수집(Phase 3)은 `reconcile 허용 ∧ recovered ∧ verification == 'verified' ∧ ¬dryrun` 일 때만 돈다 — 렌더 진리표 48사례로 고정했다.
  재수집이 없으면 `_rf_collect_ok=false` → `abort if collect completely failed` → failed envelope(`auth` · `AUTH_PROBE_FAILED` · 계정 전용 오류 행)이다.
- 복구 계정으로 수집하는 경로는 없다. 남는 틈: 계정 모듈이 결과 없이 끝나면 계정 전용 오류 행이 빠진다(수집은 그대로 중단) — `docs/ai/NEXT_ACTIONS.md` 2026-11-16.

## 8. 시험 · 회귀

| 검사 | 결과 |
|---|---|
| 새 시험 `test_account_create_method_by_generation.py` | [PASS] 87 passed — Family 판별(Dell 13 · 결정성 1 · Lenovo 5) · iDRAC10 생성 정상 2 · 실패 · 경계 9(거부 400/405 · 재인증 401 · 응답 유실 2 · 열거 불완전 · 기존 계정 · dry-run · opt-in 재생성) · iDRAC7/8/9 · Purley 회귀 5 · Phase 3 렌더 52(진리표 48 · meta 없음 1 · 생성 실패 3) |
| 같은 시험을 HEAD 모듈에 | 26 failed · 61 passed — iDRAC10 생성 · R630 · 3.x · Manager 미확인 · Purley 사례가 HEAD 에서 실패한다(시험이 결함을 잡는다) |
| 단위 부분집합(`-k "account or family or recollect or reconcile or lenovo or dell or recovery or credential or provision"`) | [PASS] 1115 passed |
| 미러 재생 `tests/integration/test_account_reconcile_replay.py` | [PASS] 43 passed (Dell iDRAC9 미러 = `dell_slot_patch` 유지) |
| 전체 pytest(Windows, `tests/unit tests/e2e tests/regression`) | [PASS] 6887 passed · 45 skipped · 5 xfailed · 0 failed (1491.68 s) |
| `tests/integration -m "not live"`(Windows) | [PASS] 540 passed · 6 skipped · 1 deselected (33.36 s) |
| CI gate `scripts/ai/ci_gate.sh`(WSL, ext4 clone) — 3채널 syntax-check 포함 | [PASS] 실행 단계 전부 통과 — 집계는 PARTIAL(설계대로: pytest 단계만 건너뜀, pytest 는 Windows 전체 실행) · compile · field dictionary PASS · schema drift 정합(sections 11 · fd_paths 264) · vendor boundary · harness consistency 통과 · finalize corpus MATCH 20/20 · `ansible-playbook --syntax-check` 3채널 통과. 같은 clone Linux pytest: 계정 5파일 383 passed · 단위 부분집합 1115 passed. 캡처 로그에 앞 두 단계 머리말이 빠졌다 — 집계 규칙상 fail=0 이어야 PARTIAL 이라 실행 단계는 전부 통과다 |
| 정적 · 정합 | [PASS] py_compile · vendor boundary · harness consistency · output schema drift · field dictionary · project map drift |
| yamllint | [SKIP] 환경 제약 — 작업 PC · WSL 어디에도 설치돼 있지 않다(CI gate 도 실행하지 않는다). YAML parse 와 syntax-check 로 대신했다 |

## 9. 남은 것

- [HIGH / 사이트] 정식 수정 배포 뒤 같은 iDRAC10 재실행 + `AccountService/Accounts` · Manager 원본 캡처 — 2.2 추정 확정, Family evidence 상향.
  긴급 조치 사본을 쓴 곳이 있으면 정식 수정본으로 바꾼다(3절 — 긴급 조치는 iDRAC8 · 초기 iDRAC9 생성을 실패시킨다).
- [MED / lab] Lenovo Purley 실측(ACC-L3).
- [LOW / AI] 계정 모듈 비정상 종료 시 오류 행.
