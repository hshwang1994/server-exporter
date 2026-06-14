# schema/ — 출력 schema 정본 (DB 없는 envelope 계약)

> 호출자 시스템과의 envelope 계약. DB schema 가 없는 server-exporter 에서 본 디렉터리가 그 역할을 한다.

## 디렉터리 / 파일 역할

| 위치 | 역할 | 정본 rule |
|---|---|---|
| `sections.yml` | 11 sections 정의 (system/hardware/bmc/cpu/memory/storage/network/firmware/users/power/thermal) | rule 13 R1 |
| `field_dictionary.yml` | 134 entries (47 Must + 81 Nice + 6 Skip) — 18 section prefixes | rule 13 R1 / R5 |
| `fields/` | 섹션별 필드 상세 (선택 — sections.yml 보조) | rule 13 R1 |
| `baseline_v1/` | vendor 별 회귀 기준선 JSON (9 baseline) | rule 13 R4 / rule 21 |
| `examples/` | success/partial/failed/not_supported 케이스 예시 JSON (4) | docs/09 |
| `output_examples/` | 실 장비 개더링 한글 주석본 (11 entries — cycle 2026-05-07) | docs/09 |
| `redfish_dmtf_2026.1/` | DMTF DSP8010 2026.1 subset (28 리소스 json-schema 대조 reference) | rule 96 |

## 갱신 의무 (rule 13 R1 — 3종 동반)

schema 변경 시 다음 3종 동시 갱신:
1. `sections.yml` (섹션 list 변경 시)
2. `field_dictionary.yml` (필드 정의 변경 시)
3. `baseline_v1/{vendor}_baseline.json` (영향 vendor 전수 — rule 13 R4 실측 후만)

누락 시 Jenkins Stage 3 (Validate Schema) FAIL.

## 어느 파일을 먼저 봐야 하나

- **envelope 구조 이해**: `docs/20_json-schema-fields.md` (정본 reference)
- **섹션 추가 / 변경**: `sections.yml` 먼저, 그 다음 `field_dictionary.yml`
- **새 vendor 추가**: `baseline_v1/{vendor}_baseline.json` (실측 후) — `docs/14_add-new-gather.md` 절차 B
- **회귀 입력 / 호출자 reference**: `examples/` + `output_examples/`

## 갱신 자동 검증

| 명령 | 검증 |
|---|---|
| `python tests/validate_field_dictionary.py` | sections × field_dictionary 정합 |
| `python scripts/ai/hooks/output_schema_drift_check.py` | schema 변경 drift |
| `pytest tests/regression/` | cross-channel envelope 13 필드 (cycle 2026-05-07) |

## envelope 13 필드 (rule 13 R5)

정본: `common/tasks/normalize/build_output.yml`

```text
target_type, collection_method, ip, hostname, vendor,
status, sections, diagnosis, meta, correlation, errors, data,
schema_version
```

상세: `docs/20_json-schema-fields.md`.

## 관련 문서

- `docs/09_output-examples.md` — 출력 예시
- `docs/13_redfish-live-validation.md` — 실장비 검증 / baseline 갱신 절차
- `docs/16_os-esxi-mapping.md` — OS/ESXi 필드 매핑
- `docs/20_json-schema-fields.md` — envelope 13 필드 정본
- `docs/22_compatibility-matrix.md` — vendor × generation × section 호환성
