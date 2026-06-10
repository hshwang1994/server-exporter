# tests/ — 테스트 / fixture

> pytest unit + e2e + regression + 실장비 probe + 사이트 fixture + Round 검증.

## 디렉터리 역할 매트릭스

| 위치 | 역할 | 갱신 트리거 |
|---|---|---|
| `tests/unit/` | 단위 테스트 (특정 함수 / 분기 / 회귀) | 새 함수 / 버그 fix |
| `tests/e2e/` | E2E 테스트 (envelope 13 필드 검증) | 새 baseline / schema 변경 |
| `tests/regression/` | Cross-channel 회귀 | baseline 추가 / envelope 변경 |
| `tests/integration/` | 오프라인 회귀 (HPE iLO 에뮬레이터 + DMTF 표준 mockup replay + robustness round 회귀). Jenkins Stage 4 (`Jenkinsfile`) 가 `-m "not live"` 로 실행 | 펌웨어 robustness 라운드 / mutation |
| `tests/redfish-probe/` | 실장비 probe 스크립트 (probe_redfish + deep_probe) | 새 vendor / 펌웨어 |
| `tests/fixtures/` | mock 회귀 입력 (실 BMC 응답 sanitize) | 사이트 이슈 / 사이트 fixture 캡처 |
| `tests/scripts/` | 보조 검증 스크립트 (conditional_review 등) | Jenkins Stage 4 보조 |
| `tests/e2e_browser/` | BMC WebUI 브라우저 테스트 (선택) | BMC WebUI 변경 |

## baseline JSON 정본 위치

`tests/baseline_v1/` 가 아니라 **`schema/baseline_v1/`**. 본 디렉터리는 fixture (mock) 만.

## 자주 쓰는 명령

| 목적 | 명령 |
|---|---|
| 전체 회귀 | `pytest tests/` |
| Cross-channel envelope 회귀 | `pytest tests/regression/` |
| 단위 테스트만 | `pytest tests/unit/` |
| 특정 vendor probe | `python tests/redfish-probe/probe_redfish.py --vendor dell` |
| 신 펌웨어 프로파일링 | `python tests/redfish-probe/deep_probe_redfish.py --bmc-ip <ip>` |
| Jenkins Stage 3 등가 | `python tests/validate_field_dictionary.py` |

## 회귀 보호 영역

| 영역 | 위치 | 검증 항목 |
|---|---|---|
| envelope 13 필드 | `tests/regression/test_cross_channel_consistency.py::test_envelope_thirteen_fields_present` | envelope 13 필드 정본 |
| hostname fallback chain | `test_hostname_never_null` | build_output.yml fallback |
| vendor canonical | `test_vendor_canonical` | vendor 정규화 정본 |
| status enum (4 시나리오) | `test_status_enum` | status 4 시나리오 |
| sections enum | `test_sections_values_enum` | sections 정합 |
| diagnosis 4-stage | `test_diagnosis_has_4stage_keys` | 4단계 Precheck |
| Linux raw fallback (RHEL 8.10) | `tests/e2e/test_os_output.py` (rhel810_raw_fallback baseline 회귀) | Linux 2-tier raw fallback |

## 사이트 fixture 캡처

사이트 호환성 사고 시:
- `tests/fixtures/redfish/{vendor}_{firmware}/` 에 sanitize 된 raw 응답 저장
- `tests/regression/conftest.py` 의 BASELINE_REGISTRY 에 자동 추가 (실측 후)

## 관련 문서

- `docs/13_redfish-live-validation.md` — 실장비 검증 / Round
- `docs/22_compatibility-matrix.md` — 호환성 매트릭스
- `docs/23_debugging-entrypoints.md` — 디버깅 매트릭스
