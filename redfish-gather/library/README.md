# redfish-gather/library/ — Redfish API 엔진 (stdlib only)

> 약 4,500 줄 (2026-06 기준) 단일 Python 모듈. urllib / ssl / json 만 사용 (rule 10 R2 — 외부 라이브러리 금지).

## 파일

- `redfish_gather.py` — 단일 모듈, 약 4,500 줄 (2026-06 기준)

## 함수 인덱스 (호출 endpoint 별)

> 위치는 모듈이 커지면서 변하므로 함수명으로 grep 한다 (예: `grep -n 'def gather_power' redfish_gather.py`).

| 함수 | 호출 endpoint |
|---|---|
| `_detect_vendor_from_service_root` | GET `/redfish/v1/` (ServiceRoot 무인증) |
| `_extract_oem_hpe / dell / lenovo / supermicro / cisco` | (helper — vendor 별 OEM 추출) |
| `gather_system` | GET `/redfish/v1/Systems/{id}` + Bios |
| `gather_bmc` | GET `/redfish/v1/Managers/{id}` + EthernetInterfaces |
| `gather_processors` | GET `/redfish/v1/Systems/{id}/Processors` (collection + N) |
| `gather_memory` | GET `/redfish/v1/Systems/{id}/Memory` (collection + N) |
| `gather_storage` | GET `/redfish/v1/Systems/{id}/Storage` + Volumes + Drives |
| `gather_network` | GET `/redfish/v1/Systems/{id}/EthernetInterfaces` |
| `gather_network_adapters_chassis` | GET `/redfish/v1/Chassis/{id}/NetworkAdapters` + NetworkPorts |
| `gather_firmware` | GET `/redfish/v1/UpdateService/FirmwareInventory` |
| `gather_power` | GET `/redfish/v1/Chassis/{id}/Power` 또는 PowerSubsystem |

각 함수 docstring 에 endpoint 명시 (cycle 2026-05-07 보강).

## vendor 분기 정본 위치 (rule 12 R1 Allowed 영역)

| 위치 | 분기 | 근거 |
|---|---|---|
| `_OEM_EXTRACTORS` | vendor → OEM extractor 함수 매핑 | Redfish API spec 자체가 vendor namespace 정의 (`Oem.Hpe`, `Oem.Dell`...) |
| `_FALLBACK_VENDOR_MAP` | vendor_aliases.yml load 실패 시 fallback | rule 12 R1 Allowed |
| `_detect_vendor_from_service_root` | vendor 시그니처 매핑 (product / manufacturer 문자열 → vendor) | BMC product name 으로 vendor 추론 |
| `bmc_names` dict | BMC 표시명 매핑 (dell→iDRAC) | UI / 메시지용 |
| `_ACCOUNT_CREATE_STRATEGY` | vendor → 계정 생성 strategy (cycle 2026-05-07 추가) | AccountService PATCH/POST 차이 |
| `account_service_provision()` 본문 | inline if/elif vendor 분기 | 사이트 실측 + 펌웨어 별 사고 매트릭스 |

이 외 영역 (common / 3-channel) 의 vendor 하드코딩 금지 (rule 12 R1).
검증: `python 내부 검증 스크립트`.

## 외부 의존성 정책 (rule 10 R2)

| 카테고리 | 사용 가능 |
|---|---|
| stdlib | urllib / ssl / json / socket / time / re / sys / os / typing |
| 외부 라이브러리 | **금지** (requests / urllib3 / paramiko 등 추가 안 함) |

이유: Agent 환경에 라이브러리 누락 발생 시 핵심 수집 자체 실패. stdlib 만으로 robustness 확보.

## 디버깅 진입점

| 사고 | 확인 |
|---|---|
| Redfish endpoint 응답 파싱 실패 | `gather_*` 함수 + `tests/redfish-probe/probe_redfish.py` |
| vendor 잘못 감지됨 | `_detect_vendor_from_service_root` + `_FALLBACK_VENDOR_MAP` |
| OEM 데이터 누락 | `_OEM_EXTRACTORS` + adapter `tasks/vendors/{vendor}/normalize_oem.yml` |
| AccountService 분기 | `_ACCOUNT_CREATE_STRATEGY` + `account_service_provision` |

## 관련 문서

- `docs/develop/03-adapter-system.md` — Adapter 시스템 + priority 정책 (cycle 2026-05-07 보강)
- `docs/reference/live-validation.md` — 실장비 검증
- `docs/develop/04-add-vendor.md` 절차 B — 신 vendor / 새 세대 추가 (cycle 2026-05-07 보강)
- `docs/reference/compatibility-matrix.md` — vendor × generation × section
- `docs/develop/06-debugging.md` — 디버깅 매트릭스 (cycle 2026-05-07 신설)
