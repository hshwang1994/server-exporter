# ADR-2026-10-29 — Redfish Summary null 규칙 (미제공 · 확정 불가 = null, 확인한 0 = 0, 부분 합 ≠ 전체 합)

- 상태: Accepted (사용자 결정 2026-10-29 · Plan 승인 · 2026-11-01 용량 미상 디스크 결정 추가). 구현 브랜치 `fix/redfish-mock2-summary-20261028`(분기 `104bcaf0`) — main 미병합, 독립 재검증 · 병합 승인 대기
- 범위: Redfish summary 전 구간(top-level · `multi_node.partitions[]` · `multi_node` 개수) · ESXi `power.summary.health_rollup`(SA-06 하나). OS 변경 0
- 폐기 · 개정하는 결정:
  - 2026-06-08 `_normalize_link_status` 의 "Starting · Training → down"(코드 docstring 의 결정) → 일반 NIC · 포트는 unknown + notice(SA-09).
    HBA(`storage.hbas[]`)는 종전대로 down — `_HBA_LINK_DOWN_VALUES` 로 고정해 일반 매핑 변경이 번지지 않게 했다.
  - 2026-10-19 A-10 "Storage 에 드라이브 0건일 때만 섀시 `Drives` 폴백"(ADR-2026-10-19-csus-single-server-and-summary-fixes) → 섀시가 광고한 `Drives` 컬렉션 · `Links.Drives` 를 늘 합집합(SA-12).
  - cycle-016 Phase M `network.summary.primary_speed_mbps` = "첫 link up NIC 의 속도" → `is_primary` NIC 의 속도(SA-10).
  - Redfish 전력 측정값의 `int()` 절삭 → half-even 정수 반올림(SA-17). 정격(capacity)은 그대로.
- 정본: `schema/field_dictionary.yml` 머리 메모(2026-10-29) · `docs/contract/03-fields.md` · `tests/evidence/2026-10-29-redfish-summary-fix/SUMMARY_FIX_HANDOFF.md`

## 컨텍스트 (Why)

- 독립 Summary 감사(`C:\github\ClovirONE\se-indep-20261028\SUMMARY_AUDIT_REPORT.md`, 기준 `104bcaf0`, 저장소 밖 · 읽기 전용)가 1,670건을 판정했다:
  PASS 1,402 · CONTRACT_MISMATCH 168 · FAIL 7 · HOLD 8 · MOCK_LIMITATION 85.
- 공통 원인은 두 가지다. (1) 원천이 주지 않은 값을 0 으로 적었다(fabric endpoint 개수 · 개수 필드 · NIC 속도 0 · storage 합계 0). (2) 일부만 확인한 합을 전체 합으로 적었다(CPU 코어 · DIMM · 파티션 사본).
- FAIL 7 은 SA-01 한 유형이 CSUS 7대에서 관측된 것이다. 나머지 실결함 5유형(SA-02 · 03f · 04 · 05 · 19)은 18대 미러에서 발동하지 않았고 합성 미러 · 함수 단위로 확인했다. CM 168 은 13유형이다.
- 사용자 지시서(2026-10-29): null 은 미제공 · 확정 불가, 0 은 확인한 0, 부분 합은 전체 합이 아니다. 코드 오류를 문서만 바꿔 끝내지 않고, 정상 수집값을 문서에 맞추려 바꾸지 않는다.

## 결정 (What)

공통 원칙: null = 원천이 주지 않음 · 확정 불가, 0 = 확인한 0, 부분 합은 전체 합으로 쓰지 않는다. 추정값을 만들지 않는다. BMC 요약값(ProcessorSummary · MemorySummary)은 같은 System 범위에서 검사를 통과할 때만 쓴다.
예외 1건: storage 합계에서 용량 미상 디스크는 합에서 빼고, 확인한 디스크의 합은 그대로 낸다(2026-11-01 사용자 결정 — 표 마지막 행).

| 항목 | 결정 | 결정 주체 |
|---|---|---|
| SA-01 · 02 개수 | 원천 컬렉션을 끝까지 읽었을 때만 정수(빈 컬렉션 200 → 0). 링크 없음 · 404 · 실패 · 멤버 일부 실패는 null. 목록은 읽은 멤버만 담고 `[]` 를 유지한다 | 사용자(목록 `[]` 유지) |
| SA-03 파티션 | top-level 과 같은 의미 · 단위 · 예외를 적용한다(함수는 공유하지 않음). 제조사는 FIX 2 표. 파티션 network summary 는 계산하지 않고 `{groups: []}` | 지시서 기본 방향 · Plan |
| SA-04 · 05 | 부분 합 대신 검사를 통과한 ProcessorSummary · MemorySummary, 그것도 없으면 null + notice | 지시서 기본 방향 |
| SA-06 | 설치 PSU 0 → `health_rollup` null. PSU 는 있는데 상태를 모두 모르면 'Unknown'. Redfish · ESXi 함께 | 사용자 |
| SA-07 | `storage.summary.grand_total_gb` 는 드라이브 목록 원천의 구조로 판정한다. 원천을 하나 이상 읽었고 모두 비었고 실패가 없으면 0, 원천 없음 · 실패 · 일부 실패면 null. 전원 상태는 쓰지 않는다 | 사용자(Plan 반려 의견) |
| SA-08 | Summary 그룹 키의 속도 0 → null. 상세 `interfaces[].speed_mbps` 원본 0 은 유지 | 사용자 |
| SA-09 | 일반 NIC · 포트의 Starting · Training(DMTF 전이 상태) · Enabled · Active · 미인식 값 → unknown + notice. HBA 의 값과 notice 는 바꾸지 않는다 | 사용자(Plan 반려 의견) |
| SA-10 | `primary_speed_mbps` = `is_primary` NIC 의 속도. 0 · null · 대표 NIC 없음 → null | 지시서 기본 방향 |
| SA-11 | storage GiB 내림 유지(3채널), memory half-even 유지 — 문서화 | 사용자 |
| SA-12 | Storage 가 가리킨 드라이브 ∪ 섀시가 광고한 `Drives` 컬렉션 · `Links.Drives`. 중복은 `@odata.id` → SerialNumber 순으로 제거. 광고한 링크만 GET. 선택 링크의 404 는 미제공. 검증에서는 404 출처를 셋(미러 실응답 · 기록된 실 404 · Mock 미포함 = MOCK_LIMITATION)으로 나눈다 | 지시서 SA-12 문단 · 사용자(404 출처 구분) |
| SA-17 | 전력 측정값(소비 · min/avg/max · PSU 입출력)은 `_safe_round_int`(half-even), 정격은 그대로 | 사용자 |
| SA-19 | EnvironmentMetrics `PowerWatts.ReadingRangeMin/Max`(측정 가능 범위)를 min/max 소비전력으로 쓰지 않는다 | 지시서 기본 방향(DMTF Sensor 정의) |
| SA-13 · 15 · 16 · 18 | 주석 · 시험 설명 · 사전 · 계약 문장만 정정(출력 0) | — |
| 용량 미상 디스크(2026-11-01) | `storage.summary.grand_total_gb`(파티션 포함, 3채널)는 용량을 확인한 디스크의 합이다. 용량 미상 디스크(`total_mb` null · 0)는 그룹 · 합에서 빼고, 그 때문에 합을 null 로 만들지 않는다. "실제 전체 용량보다 작을 수 있다" 는 한계를 `docs/contract/03-fields.md` 6.3 에 적는다. 드라이브 목록 미완결(SA-07)의 null 은 그대로다. 코드 · 시험 변경 0 | 사용자(a안) |

## 결과 (Impact)

- 출력: 18대 Tier 1 차이 34건(SA-01 7 · SA-03 7 · SA-17 9 · SA-08 7 · SA-06 1 · SA-07 3)이고 전부 허용 목록에 있다. envelope 13 필드 · `schema_version` · `failure_*` 는 그대로이고 키 추가 · 삭제는 0 — 값이 null 로 나오는 조건만 넓어졌다(키 목록은 handoff 3.4절).
- 요청: 새 GET 14 경로(전부 미러 실응답). golden 4세트 12경로 · CSUS baseline 1 · `request_budget.json` 8건을 근거 대장과 함께 갱신했다.
- 호출자: Portal 등 소비자가 새 null 을 처리하는지 운영 담당자 확인이 필요하다.
- 검증: 이 구현 세션의 자기 측정이다. 실장비 0건, 공식 Runner NOT_RUN, 독립 재검증 대기.
- 남은 것: HOLD 3건 · SA-12/07/09/17 실장비 확인 · `psu_count` 신호 · OS/ESXi storage 정책 · S22 — `docs/ai/NEXT_ACTIONS.md` 2026-10-29 절.

## 대안 비교 (Considered)

| 항목 | 대안 | 채택하지 않은 이유 |
|---|---|---|
| SA-01 | 개수 · 목록 모두 null(감사 권장 A) | 목록 `[]` 는 "읽은 멤버" 라는 뜻이 이미 분명하고 소비자 파싱을 바꾸지 않는다 — 사용자 결정 |
| SA-03 | top-level 과 같은 함수 공유(감사 권장 A) | 파티션 raw 와 top-level 입력 모양이 달라 공유하면 변경 범위가 커진다. 같은 규칙을 적용하고 제조사 표는 drift 시험으로 대조한다 |
| SA-07 | 전원 Off 면 null | 전원 상태로는 "디스크 0개 확인" 과 "수집하지 못함" 을 가를 수 없다 — 사용자 반려 의견 |
| SA-08 | 상세 · Summary 모두 null(감사 권장) | 상세는 원본 보존 원칙(03-fields NIC 원본 0) — 사용자 결정 |
| SA-09 | HBA 까지 같은 매핑(감사 권장) | HBA up/down 두 값 계약(2026-10-19 · 2026-10-28 Q1) 유지 — 지시서 · 사용자 의견 |
| SA-11 | half-even(감사 권장) | 3채널 storage 구현 5벌이 내림이라 값 변화 없이 문서화한다 — 사용자 결정 |
| SA-12 | 문서 정합 먼저, 합집합은 실장비 확인 뒤(감사 권장) | 지시서가 "실제 결함이면 문서 정정만으로 완료 처리하지 않는다" 고 했다. 합집합을 구현하고 실장비 확인을 후속으로 남겼다 |
| SA-17 | 절삭 유지 · 소수 자리 유지 | integer 타입을 유지하면서 반올림 — 사용자 결정 |
| 용량 미상 디스크 | 하나라도 있으면 합계 null + notice(SA-04 · 05 와 같은 방식) | 일부 디스크의 용량을 모른다는 이유로 확인한 디스크의 합까지 버리게 된다 — 사용자 결정(2026-11-01). AI 검토 메모: SimpleStorage 경로는 빈 슬롯(Absent)을 거르지 않아 null 규칙이 빈 슬롯에서도 발동할 위험이 있었다 |
