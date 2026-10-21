# tests/: 시험, fixture, 검증 기록

이 디렉터리는 개발 저장소(`main`) 전용입니다. 배포본(production 브랜치)에는 들어가지 않고, CI의 Gate 단계와 생성 tree 검증이 여기의 시험을 실행합니다.

## 디렉터리

| 위치 | 역할 |
|---|---|
| `unit/` | 단위 시험. 필터, 모듈, Jinja 렌더, 파이프라인 파일의 글자 계약 |
| `e2e/` | 채널별 봉투와 기준선(`schema/baseline_v1/`) 대조 |
| `regression/` | 채널 간 봉투 일관성, 13 필드, 벤더 표시값 |
| `integration/` | fixture 재생 (DMTF 표준 mockup, HPE 에뮬레이터, 실장비 캡처), Add-on hook 실제 playbook 실행. `live` 표식이 있는 시험은 실장비가 필요합니다 |
| `redfish-probe/` | 실장비 probe 도구 (pytest 아님). `redfish_full_mirror.py`는 운영망 원본 캡처용, `mirror_many.sh`는 여러 대 병렬 실행용 (`docs/develop/08-onsite-capture.md`) |
| `fixtures/` | 시험 입력. Redfish 원본 응답, OS와 ESXi 합성 응답, 결과 정리 corpus, 입력 검증 사례 |
| `scripts/` | 보조 도구. `conditional_review.py`(조건식 검토), `finalize_corpus_check.py`(결과 정리 corpus 대조), `junit_evidence_check.py`(CI JUnit 대조), `os_esxi_verify.sh`와 `diag_esxi_raw.yml`(실장비 수동 확인) |
| `inventory/` | 보조 검증 장비 인벤토리 정책 (`inventory/README.md`) |
| `evidence/` | 실장비 검증과 결함 수정의 기록 |
| `jenkins/` | CI가 쓰는 Jenkins 하네스 (개발 저장소 전용) |
| `reference/` | 실장비 원본 응답 참조 자료 (개발 저장소 전용) |
| `validate_field_dictionary.py` | `schema/sections.yml`과 `schema/field_dictionary.yml` 정합 검사 |
| `secret_guard.py`, `precheck_stub.py` | 비밀값 검사 보조, 사전 진단 stub |

기준선 JSON의 정본은 `tests/`가 아니라 `schema/baseline_v1/`입니다.

## 자주 쓰는 명령

```bash
# 저장소 루트
python -m pytest tests/unit tests/e2e tests/regression -q    # 단위, 종단, 회귀
python -m pytest tests/integration -q -m "not live"          # fixture 재생 (Ansible 이 있는 Linux 또는 WSL)
python -m pytest tests/ -q                                   # 전체
python tests/validate_field_dictionary.py                    # 섹션과 필드 사전 정합
python tests/redfish-probe/probe_redfish.py --vendor dell    # 실장비 probe (pytest 아님)
```

`pytest.ini`의 표식(`source_text`, `integration`, `live`)으로 골라 실행할 수 있습니다.

## 회귀 보호 영역

| 영역 | 위치 |
|---|---|
| 봉투 13 필드 | `regression/test_cross_channel_consistency.py` |
| hostname이 IP로 대체되지 않음 | `regression/test_cross_channel_consistency.py` |
| 벤더 표시값 | `regression/test_cross_channel_consistency.py` |
| status와 sections 값 | `regression/test_cross_channel_consistency.py` |
| 진단 4단계 키 | `regression/test_cross_channel_consistency.py` |
| Linux raw 경로 (RHEL 8.10) | `e2e/test_os_output.py` |
| 어댑터 세대 토큰과 채널 섹션 | `unit/test_adapter_generation_tokens.py`, `unit/test_adapter_capabilities_channel_sections.py` |
| Redfish 403과 Power, Thermal 404 분류 | `unit/test_redfish_status_after_authenticated_403.py`, `unit/test_redfish_power_thermal_absent_not_supported.py` |
| Jenkins 파이프라인의 중단 판정과 보존 | `unit/test_jenkinsfile_portal_audit_2026_10_12.py`, `unit/test_jenkinsfile_portal_finalize.py` |

## 새 fixture

실장비 응답을 캡처해 `fixtures/redfish/<이름>/`에 두고 그 디렉터리의 README에 장비, 펌웨어, 캡처 날짜와 방법을 적습니다. 실장비가 없는 벤더는 벤더 문서 기준 합성 응답임을 README에 명시합니다. 캡처 절차는 `docs/develop/08-onsite-capture.md`에 있습니다.

## 관련 문서

- `docs/reference/live-validation.md`: 실장비 검증
- `docs/reference/compatibility-matrix.md`: 호환성 매트릭스
- `docs/develop/06-debugging.md`: 디버깅 진입점
