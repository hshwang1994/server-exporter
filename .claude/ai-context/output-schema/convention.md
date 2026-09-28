# Output-Schema Convention — server-exporter

> 출력 schema 작업 컨벤션. 정본: `schema/sections.yml`, `schema/field_dictionary.yml`, `docs/contract/02-output-envelope.md`, `docs/develop/05-field-mapping.md`.

## 1. 출력 envelope (rule 20)

callback_plugins/json_only.py가 OUTPUT 태스크에만 JSON 직렬화. 표준 13 필드:

```json
{
  "status": "success | partial | failed",
  "sections": ["system", "hardware", "cpu", ...],
  "data": { "cpu": {...}, "memory": {...}, ... },
  "errors": [...],
  "meta": { "loc": "...", "target_type": "...", "vendor": "...", ... },
  "diagnosis": {
    "precheck": { "ping": "ok", "port": "ok", "protocol": "ok", "auth": "ok" },
    "gather_mode": "python_ok | raw_forced | ...",
    "python_version": "...",
    "details": [...]
  }
}
```

## 2. Sections (11) — schema/sections.yml

| 섹션 | 용도 |
|---|---|
| `system` | 호스트 식별 (hostname, os_family, fqdn) |
| `hardware` | 모델 / 시리얼 / 메인보드 |
| `bmc` | BMC IP / 펌웨어 / 사용자 (Redfish) |
| `cpu` | 모델 / 코어 / 소켓 |
| `memory` | 용량 / DIMM list |
| `storage` | 디스크 / 컨트롤러 / 볼륨 |
| `network` | NIC / VLAN / 라우팅 |
| `firmware` | BIOS / BMC / 컴포넌트 펌웨어 |
| `users` | 시스템 계정 (Linux/Windows) |
| `power` | 전원 공급 장치 / 정책 |

새 섹션 추가는 sections.yml + field_dictionary.yml + baseline_v1 3종 동반 갱신 (rule 13).

## 3. Field Dictionary 의 Must / Nice / Skip

`schema/field_dictionary.yml` 에서 분류한다. 개수는 여기 적지 않는다 (rule 00) — 필요하면 그때 센다:
- **Must (39)**: 모든 vendor의 모든 baseline에 존재해야 함. 누락 시 schema validate FAIL (Jenkins Stage 3).
- **Nice (29)**: vendor-specific 허용. 있으면 좋고 없어도 OK.
- **Skip (6)**: 의도적 미수집 (예: 너무 큰 stack trace).

Must 갱신은 모든 vendor baseline 회귀 후에만 (rule 92 R3).

## 4. Build_*.yml 빌더 5종 (common/tasks/normalize/)

각 builder가 fragment 변수를 어떻게 누적하는지 일관 패턴:

| Builder | 입력 | 출력 |
|---|---|---|
| `init_fragments.yml` | (없음) | 누적 변수 초기화 (`_collected_data`, `_supported_sections`, `_collected_errors` = []) |
| `merge_fragment.yml` | gather가 만든 `_data_fragment` 등 | 누적 변수에 재귀 병합 |
| `build_sections.yml` | `_supported_sections` | 최종 sections list |
| `build_status.yml` | `_collected_errors`, `_supported_sections` | success / partial / failed |
| `build_errors.yml` | `_collected_errors` | 정규화된 errors list |
| `build_meta.yml` | inventory + adapter 결과 | meta dict |
| `build_correlation.yml` | host_id + run_id | correlation_id |
| `build_output.yml` | 위 모두 | 최종 envelope dict |

## 5. Baseline JSON 패턴

`schema/baseline_v1/{vendor}_baseline.json`:
- 실장비 검증 결과를 정규화한 회귀 기준선
- pytest E2E (Jenkins Stage 4)가 비교
- 새 펌웨어로 응답 변경 시 update-vendor-baseline skill로 갱신

## 6. callback_plugins/json_only.py

stdout callback. 핵심 동작:
- 일반 task 출력 무시
- task name이 "OUTPUT"으로 시작하는 경우만 JSON 직렬화
- 호출자가 stdout을 파싱하여 envelope 추출
- ansible 자체의 verbose 출력 (PLAY/TASK/OK/CHANGED)을 차단

## 7. 새 섹션/필드 추가 절차 (rule 13)

1. `schema/sections.yml`에 섹션 추가 (또는 기존 섹션에 필드 추가)
2. `schema/field_dictionary.yml`에 필드 정의 (Must/Nice/Skip 분류)
3. 영향 vendor baseline (`schema/baseline_v1/{vendor}_baseline.json`) 추가/갱신
4. `tests/fixtures/` mock 추가
5. update-output-schema-evidence skill로 정합 검증
6. Jenkins Stage 3 (Validate Schema) 통과 + 로컬 pytest 회귀 통과

## 8. 자주 호출하는 Skill / Agent

- `update-output-schema-evidence` — sections + field_dictionary + baseline 정합
- `verify-json-output` — envelope 검증
- `update-vendor-baseline` — baseline 갱신
- `plan-schema-change` — 새 섹션/필드 계획
- agent: `refactor-worker`, `schema-reviewer`
