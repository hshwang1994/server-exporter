# schema/: 출력 계약 정본

호출자 시스템과의 봉투 계약을 코드와 따로 보존하는 디렉터리입니다. 운영 코드는 이 디렉터리를 읽지 않고, 시험과 CI 검사가 코드 출력과 대조합니다. 배포본(production 브랜치)에는 들어가지 않습니다.

## 디렉터리와 파일

| 위치 | 역할 |
|---|---|
| `sections.yml` | 섹션 11종 정의 (`system`, `hardware`, `bmc`, `cpu`, `memory`, `storage`, `network`, `firmware`, `users`, `power`, `thermal`)와 채널, 빈 값 |
| `field_dictionary.yml` | 필드 사전. 항목마다 자료형, enum, 우선순위(`must`, `nice`, `skip`), 채널, 설명 |
| `fields/` | 섹션별 필드 상세 (sections.yml 보조) |
| `baseline_v1/` | 실장비 회귀 기준선 JSON (`baseline_v1/README.md`) |
| `examples/` | 시나리오별(success, partial, failed, not_supported) 예시 JSON |
| `output_examples/` | 실장비 결과에 한글 주석을 단 호출자용 예시 (`.jsonc`) |
| `redfish_dmtf_2026.1/` | DMTF Redfish 스키마 참조 사본 (enum, 필드명 대조용) |

필드 수는 세지 않고 필요할 때 셉니다.

```bash
grep -c '^\s*priority:' schema/field_dictionary.yml
```

## 바꿀 때 함께 갱신할 것

| 변경 | 함께 갱신 |
|---|---|
| 섹션 추가, 삭제 | `sections.yml`, `field_dictionary.yml`, `common/vars/supported_sections.yml`, 영향 채널 어댑터의 `capabilities.sections_supported`, 영향 벤더 `baseline_v1/*.json`, `docs/contract/03-fields.md` |
| 필드 추가, 의미 변경 | `field_dictionary.yml`, 영향 벤더 `baseline_v1/*.json`, `docs/contract/03-fields.md` |
| 봉투 최상위 필드 | 변경하지 않습니다. 13 필드는 호출자 계약입니다 (`common/tasks/normalize/build_output.yml`이 정본) |

기준선 JSON은 실장비 수집 결과로만 만듭니다. 손으로 고치지 않습니다.

## 검증

```bash
# 저장소 루트
python tests/validate_field_dictionary.py        # sections.yml 과 field_dictionary.yml 정합
python -m pytest tests/e2e tests/regression -q   # 기준선 회귀와 채널 간 봉투 일관성
```

CI(`Jenkinsfile_ci`)의 Gate 단계가 같은 검사를 실행합니다.

## 봉투 13 필드

```text
target_type, collection_method, ip, hostname, vendor,
status, sections, diagnosis, meta, correlation, errors, data,
schema_version
```

정본은 `common/tasks/normalize/build_output.yml`, 설명은 `docs/contract/03-fields.md`입니다.

## 관련 문서

- `docs/contract/02-output-envelope.md`: 봉투 모양
- `docs/contract/03-fields.md`: 필드 사전
- `docs/develop/05-field-mapping.md`: 원본에서 필드까지의 매핑
- `docs/reference/compatibility-matrix.md`: 벤더 × 세대 × 섹션
- `docs/reference/live-validation.md`: 실장비 검증
