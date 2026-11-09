# ADR 2026-11-09 — Serial Number 필수 규칙(시나리오 E)을 ESXi · Redfish 로 넓히고 공통 규칙 하나로 합친다

- 상태: Accepted
- 결정: 사용자 (2026-11-09 대화 — 범위 "Redfish + ESXi" · Dell "이번에 함께 통일" · "공통 규칙 1개" · "3채널 중복 제거" · Redfish/ESXi 문장 지정 ·
  OS sudo 문장 제안 · 계획 승인)
- 작성: AI (Claude Code)
- 관련: CLAUDE.md §4 (본문 의미 변경 → 본 ADR, rule 70 R8), rule 13 R8 (status 시나리오 매트릭스 동반 갱신), rule 96 R1-B (envelope shape 보존),
  rule 12 (vendor 경계 — 규칙에 vendor 분기 없음, Dell 처리는 Redfish 라이브러리 안), `ADR-2026-09-21-failure-reason-catalog.md` (문장 키 집합은 사용자 확정)
- 뒤집는 결정: `ADR-2026-10-13-sudo-vault-fallback-and-serial-required.md` 결정 4 의 "OS 채널만" 범위와, 다른 실패 사유가 있을 때 Serial 오류 행을 뒤에
  붙이던 코드 동작 · 2026-08-11 "Dell 은 Service Tag 를 못 얻으면 모듈이 수집을 실패시킨다"

## 컨텍스트 (Why)

1. 2026-10-13 부터 OS 채널은 Serial Number 가 없는 host 를 `failed` 로 낸다 — Portal 이 Serial 로 자산을 맞춘다. ESXi 에는 같은 규칙이 없었고,
   Redfish 는 Dell 만 모듈 안에서 Service Tag 가 없으면 `failed` · `data: {}` 로 끝냈다. 수집한 데이터를 버렸고 문장도 Serial 문장이 아니었다
   (`gather_after_auth`). 사용자는 Redfish 도 Serial 이 null 이면 같은 처리를 요구했다.
2. OS 규칙은 다른 실패 사유가 이미 있는 결과(성공 섹션 0개 · 인증 뒤 rescue)에서 대표 문장과 같은 문장의 행을 하나 더 붙였다 — Portal Grid 에
   같은 문장이 두 줄 보인다. Dell 을 그대로 통일하면 Service Tag 사유가 "서버 기본 정보" 실패 행이 되어 Serial 행과 같은 사건을 두 번 말한다.
3. Redfish `hardware.serial` 은 자리표시자 집합(`dmi_sentinel_null`)을 거치지 않아 `N/A` 같은 값이 남았다. 규칙만 넓히면 그런 host 가 통과한다.
4. OS 문장 하나("…OS 계정의 권한 및 서버의 Serial Number 제공 여부를 확인하세요.")는 가장 흔한 원인인 Linux sudo 실패에 구체 조치를 주지 않았다.
   사용자는 "수집 계정에 NOPASSWD 가 있어야 하고, 없으면 Vault 의 sudo 비밀번호가 맞는지 확인" 안내를 제안했다. 그 안내는 Windows(sudo 가 없다)와
   sudo 는 됐는데 읽기 실패 · 대상이 주지 않음 같은 원인에는 틀린 안내다.
5. 기록된 결과(Redfish success/partial 531건 · ESXi success 13건)는 모두 Serial 이 있다 — 상태가 바뀔 host 는 0 이다 (2026-11-09 실측).

## 결정 (What)

1. 판정 · 봉투 수정은 공통 규칙 하나 `common/tasks/normalize/require_serial.yml` 이다. 채널은 원인 판정과 대상 조건만 넘긴다.
   - OS: `os-gather/tasks/normalize/require_serial.yml` — 식별자 진단 토큰 + sudo 결과로 원인과 문장 키를 정한다.
   - Redfish: `redfish-gather/tasks/require_serial.yml` — BMC 를 실제로 읽은 결과만 대상이다(표준 수집 성공 또는 `diagnosis.auth_success: true`).
   - ESXi: `esxi-gather/site.yml` 이 직접 부른다(일반 원인 규칙 — rescue 는 인증 · facts 를 확인했을 때만 stage 가 gather 다).
   - 호출 위치는 3채널 모두 build_output(정상) · build_failed_output(rescue) 뒤, `schema_version` 주입 · CHECKPOINT 앞이다.
2. 발동: Serial(`correlation.serial_number` → `hardware.serial` → `system.serial_number`, 자리표시자는 null)이 null AND `failure_stage` ∈ {null, gather}
   AND 채널 대상 조건. 사전 점검 · 인증 실패와 Redfish 계정 요청 전 중단(`gather_internal`)은 건드리지 않는다.
3. 다른 실패 사유가 없으면 `failure_stage: gather` · `GATHER_FAILED` · 채널 Serial 문장이 대표 사유이고 `errors[0]` 에 그 문장의 행이 온다.
   있으면 사유 · stage · code · `errors[]` 를 그대로 두고 `status: failed` 와 `diagnosis.details.serial_number` 만 남긴다 — 행을 더하지 않는다(3채널).
4. 원인(`diagnosis.details.serial_number.cause`): OS 6값(`privilege_unavailable` · `read_failed` · `not_provided` · `facts_failed` · `not_collected` ·
   `unknown`), ESXi · Redfish 2값(`hardware` 섹션이 success 면 `not_provided`, 아니면 `not_collected`).
5. 문장(`common/vars/failure_reasons.yml`): `serial_missing.redfish` · `serial_missing.esxi` 는 사용자 문구 그대로, `serial_missing.os` 는 첫 문장만 맞춘
   일반 문장, 새 키 `serial_missing_sudo.os` 는 Linux + `privilege_unavailable` 전용이다. **새 키는 사용자 확정 사항이다** — 키 집합을 고정한 시험
   (`tests/e2e/test_errors_message_contract.py` `_EXPECTED_KEYS`)에 2026-11-09 계획 승인으로 더했다. `_fr_code_keys.GATHER_FAILED` 에도 더했고
   `failure_code` 는 그대로다. Grid 계약 시험은 Redfish 문장의 대상 종류 어휘로 'BMC' 를 인정한다.
6. Redfish `hardware.serial` 은 `dmi_sentinel_null('serial')` 다음 `normalize_os_serial` 이다(ESXi 와 같은 순서).
7. Dell(`redfish-gather/library/redfish_gather.py` main): Service Tag 를 얻지 못하면 `_notice('system', 사유)` 1건만 남기고 수집을 계속한다. 대표 시리얼은
   None 이다(보드 시리얼 폴백 금지 — 2026-08-11 결정 유지). system 섹션이 없으면 실을 자리가 없을 뿐 오류 행을 더하지 않는다. resolver 순서와 인증
   ServiceRoot 재조회 1회는 그대로다.

## 결과 (Impact)

- envelope 13 필드 · `failure_code` · `failure_stage` enum · schema version 변경 없음. `diagnosis.details.serial_number` 는 2026-10-13 부터 있던 키이고
  이제 ESXi · Redfish 에서도 나온다(`schema/field_dictionary.yml` channel 갱신).
- 바뀌는 결과:
  1. Serial 이 없는 ESXi · Redfish host → `failed` (기록상 0대).
  2. 다른 실패 사유가 이미 있는 OS 결과 → `errors[]` 가 1행 준다. status · 문장 · details 는 같다.
  3. Serial 이 대표 사유인 OS 결과 → `failure_reason` · `errors[0].message` 만 원인별 새 문장.
  4. Dell Service Tag 없음 → 여전히 `failed` 지만 `data` · `sections` 가 실리고, 대표 문장이 Redfish Serial 문장이다.
- Portal: 새 필드는 없지만 Redfish · ESXi 결과가 시나리오 E 모양(`status: failed` + `sections.*: success`)으로 올 수 있다 — Portal 담당자 안내가
  필요하다(사용자 몫).

## 대안 비교 (Considered)

| 대안 | 판단 |
|---|---|
| 채널마다 규칙 복제 | 기각 — 중복 제거 같은 수정이 한 채널에만 들어간다 |
| 다른 사유가 있어도 Serial 행 추가 (종전 OS) | 기각 — Grid 에 같은 문장이 두 줄 보인다 |
| Dell 은 모듈 실패 유지 | 기각 — 데이터를 버리고, 문장이 Serial 문장이 아니다 |
| Dell Service Tag 사유를 `errors[]` 행으로 | 기각 — "서버 기본 정보" 문장이 Serial 행과 같은 사건을 다시 말하고, 정상 섹션을 실패처럼 보이게 한다 |
| Serial 전용 `failure_code` | 기각 — Stable code 변경은 Consumer · Schema 영향 확인이 필요하고, `GATHER_FAILED` + cause 로 원인을 가를 수 있다 |
| OS 문장 하나에 sudo 안내 | 기각 — Windows · 다른 원인에 틀린 안내다 |
| Redfish 도 stage 만 보고 대상 조건 없음 | 기각 — 계정 요청 전 중단도 stage 가 gather 라, BMC 를 읽지 않았는데 Serial 을 "확인하지 못했다" 고 말하게 된다 |

## 미확인 (실장비)

- Serial 을 주지 않는 실제 Redfish · ESXi 장비는 없다. 누락 분기는 미러 재생(사본에서 `SerialNumber` · System 응답 · Dell Service Tag 를 지움)과
  단위 · 통합 시험으로만 확인했다.
