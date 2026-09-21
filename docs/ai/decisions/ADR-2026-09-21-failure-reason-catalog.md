# ADR 2026-09-21 — failure_reason 을 (code, 대상 종류, 세부 사유) 카탈로그로 고른다

- 상태: Accepted
- 결정: 사용자 (2026-09-21 대화 — 사용자가 문장 체계를 제시하고, AI 검토 후 4개 항목을 확정)
- 작성: AI (Claude Code)
- 관련: CLAUDE.md §9 §10 (본문 의미 변경 → 본 ADR, rule 70 R8), rule 13 R7 (03-fields.md 동반 갱신),
  rule 96 R1-B (envelope shape 보존), rule 95 R3 (결함 발견 → 회귀 테스트)
- 뒤집는 결정: 2026-08-11 "사용자 문장에서 채널 이름을 뺀다", 2026-08-12 "문장은 failure_code 에서만 파생한다"

## 컨텍스트 (Why)

Portal 실패 Grid 의 "실패 사유"(`diagnosis.failure_reason` = `errors[0].message`)는 관리자가
조치 방향을 정하는 유일한 문장이다. 종전에는 `failure_code` 9개가 문장 6개로 뭉쳐 있었다.

| 뭉쳐 있던 것 | 문제 |
|---|---|
| `TCP_CONNECT_FAILED` + `TCP_CONNECTION_REFUSED` → 2번 | 방화벽 차단 의심과 서비스 중지 의심이 같은 문장 |
| `CREDENTIAL_SET_UNAVAILABLE` + `AUTH_PROBE_FAILED` → 4번 | 수집 시스템 Vault 문제인데 대상 서버 계정을 보라고 안내 |
| 401 확정 + timeout/403/5xx 미확정 → 4번 | "비밀번호를 맞추면 된다" 와 "원인을 더 봐야 한다" 가 구분 안 됨 |
| 채널 이름 제거 (2026-08-11) | "관리 포트 / 관리 서비스" 가 무엇인지 알 수 없음 |

2026-08-11 에 채널 이름을 뺀 이유는 "사용자는 채널을 고르지 않고 IP 만 넘긴다" 였는데,
실제 Portal 은 `target_type` 을 골라 요청한다. 그 전제가 맞지 않았다.

검토 중 결함 2건이 드러났다 (둘 다 새 문장이 실제로 나오려면 필요한 수정이다).

1. **Redfish 시도 0회가 GATHER_FAILED 로 샘.** `_rf_auth_outcome` 의 credential 판정이
   `_cred_load_outcome`(= 표준 vault 결과)만 봤다. 표준 vault 는 전역이라 실행 위치가 미등록이어도
   `loaded` 이고, 표준 계정 0개(`empty_accounts`)는 판정 목록에 없었고, vendor 미상이면 조건 자체가
   꺼졌다. 세 경우 모두 인증을 한 번도 시도하지 않았는데 "대상 접속은 확인됐지만" 이 나갔다.
2. **복호화 실패가 계정 0개로 오분류.** `load_one.yml` 의 `include_vars` 가 `failed_when: false` 라
   결과의 failed 표시가 지워지고, `_cl_load is failed` 가 항상 거짓이었다. WSL ansible-core 2.20.7
   실측 — Vault 비밀번호 없음 / 틀린 비밀번호 모두 `is failed=False`, `_cl_included={}`.

## 결정 (What)

1. 문장 정본을 `common/vars/failure_reasons.yml` 의 `_fr_catalog[키][채널]` 로 바꾼다.
   채널 키는 `os` / `esxi` / `redfish` / `default`. 선택은 `filter_plugins/failure_reason.py`
   의 `failure_reason` 필터 한 곳에서 한다. `_fr_code_keys` 는 code 별 허용 키를 적은 계약 표다.
2. **`failure_stage` / `failure_code` 는 유지한다.** 예외는 결함 1 의 Redfish 세 경우뿐이다
   (`GATHER_FAILED`/`gather` → `CREDENTIAL_SET_UNAVAILABLE`/`auth`).
3. 문장 속 위치는 실제 `loc` 값으로 채운다 (`{loc}`, 없으면 `미지정`, 안전 문자만 40자).
4. 관측한 것만 말한다.
   - 연결 거부 문장은 주어를 쓰지 않는다 (CLAUDE.md §7 — 거부 주체 단정 금지).
   - 프로토콜 실패 문장은 "대상 종류가 틀렸다" 고 단정하지 않는다 (2026-08-13 Cisco BMC 실측:
     target_type 이 맞는데도 이 code).
   - "계정이 다르거나 권한이 없다" 는 Redfish 표준 후보 **전원** 401 일 때만 쓴다.
   - Redfish 표준 계정은 전역 Vault 이므로 "개더링 프로젝트 Vault / 개더링 표준 계정" 으로 쓴다.
5. OS/ESXi 계정 0개(`empty_accounts`)는 계정 없이 접속을 **시도한 뒤** 실패한 것이라 code 는
   `AUTH_PROBE_FAILED` 를 유지하고 문장만 "계정이 없습니다" 로 알린다 (에이전트 SSH 키 경로 보존).
6. 결함 2 는 `failed_when: false` → `ignore_errors: true` 로 고친다. 실패를 정상처럼 진행하는 것이
   아니라 바로 다음 classify 가 판정하고 호출 측 중단 게이트가 멈춘다.
7. 판정 근거가 없는 문장(OS/ESXi 계정 불일치 확인, 조회 권한 부족 확인, OS/ESXi 내부 오류)은
   이번에 넣지 않는다 (NEXT_ACTIONS).

## 결과 (Impact)

- envelope 13 필드 / diagnosis 8 키 / field_dictionary enum 변화 0 (rule 96 R1-B).
- 사용자 문장 전부 교체. 문장은 파싱 대상이 아니다(03-fields.md §5-1) — 문장 글자로 분기하는
  소비자가 있다면 영향. Portal 측 확인은 저장소 밖이라 AI 가 확인하지 못했다.
- Redfish 세 경우의 code/stage 변경 → 03-fields.md §4-1 / decision-log 에 공지.
- 복호화 실패가 이제 수집 시도 전에 멈춘다 (종전: 계정 없이 접속 시도 → 인증 실패로 보고).
- 운영 파이프라인(`Jenkinsfile_portal` Resolve Location)은 미등록 loc 를 Ansible 전에 막으므로
  `loc_unregistered` 문장은 Jenkins 밖 직접 실행에서만 나온다.
- 검증: 전체 pytest, 실제 Ansible 엔진 렌더(Templar + filter_loader), WSL 실제 플레이북 실행
  (3채널 연결 거부 + Redfish 가짜 ServiceRoot 로 rescue 경로 2건).

## 대안 비교 (Considered)

| 대안 | 채택 안 한 이유 |
|---|---|
| 6문장 표현만 다듬기 | 같은 문장에 조치가 다른 경우가 섞인 구조가 그대로 남는다 |
| auth_success 값으로 401 문장 분기 (code 유지) | 채택에 가깝게 반영 — Redfish 는 rescue 가 이미 쓰는 `_rf_auth_outcome`(rejected)로 가른다. 새 failure_code 는 만들지 않는다 |
| 새 failure_code 추가 (예: AUTH_REJECTED) | field_dictionary enum / Portal 분기 영향. 문장만으로 목적 달성 |
| OS/ESXi 거부를 오류 문자열로 감지 | CLAUDE.md §8 "문자열 Error Parsing 으로 인증 실패 추측 금지" 와 충돌 |
| 카탈로그를 런타임에 YAML 로 읽어 복제 제거 | 콜백 import 실패 시 전 대상 envelope 소실 (json_only.py 복제 이유 주석) |

## 미확인 (실장비)

- 실장비(운영 Jenkins → Portal) 에서 새 문장이 Grid 에 표시되는지는 확인하지 않았다.
- OS/ESXi 인증 실패, 수집 중 연결 끊김은 로컬 모의 실행으로만 확인했다 (단위·계약 테스트).
