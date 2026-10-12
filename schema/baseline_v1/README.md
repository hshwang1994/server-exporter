# schema/baseline_v1: 회귀 검증용 기준선

이 폴더는 서버별 "정답지"입니다. server-exporter가 정상 동작했을 때의 출력 JSON을 그대로 보존했습니다. 코드를 바꾼 뒤 이 정답지와 현재 출력을 비교하면 의도하지 않은 회귀를 바로 알 수 있습니다.

## 약속

- 이 폴더의 JSON은 수정하지 않습니다. 새 정답지가 필요하면 실장비에서 다시 수집해 별도 폴더(예: `baseline_v2/`)에 둡니다.
- 각 파일은 출력 플러그인(`callback_plugins/json_only.py`)이 낸 봉투를 그대로 저장한 것입니다.
- 식별자(serial_number, system_uuid)는 권장 운영 조건(Linux sudo, Windows 관리자) 기준으로 기록되어 있습니다.

## 파일

파일 이름은 `<벤더 또는 OS>_baseline.json`입니다. 한글 주석본은 `schema/output_examples/`에 채널과 벤더 대표로 따로 있습니다 (JSON은 주석을 허용하지 않아 `.jsonc`).

| 기준선 | 한글 주석 예시 | 채널 | 수집한 장비 |
|---|---|---|---|
| `dell_baseline.json` | `redfish_dell_idrac9.jsonc` | Redfish | Dell PowerEdge R740 (iDRAC 9, FW 4.00) |
| `hpe_baseline.json` | `redfish_hpe_ilo6.jsonc` | Redfish | HPE ProLiant DL380 Gen11 (iLO 6, FW 1.73) |
| `hpe_csus_3200_baseline.json` | `redfish_hpe_csus_3200.jsonc` | Redfish | HPE Compute Scale-up Server 3200. 실장비가 없어 벤더 문서와 DMTF 스키마로 합성한 기준선입니다 |
| `lenovo_baseline.json` | `redfish_lenovo_xcc.jsonc` | Redfish | Lenovo ThinkSystem SR650 V2 (XCC, FW 5.70) |
| `cisco_baseline.json` | `redfish_cisco_cimc.jsonc` | Redfish | Cisco UCS C220 M4 (CIMC) |
| `esxi_baseline.json` | `esxi_vmware.jsonc` | ESXi | ESXi 7.0.3 |
| `ubuntu_baseline.json` | `os_linux_ubuntu2404.jsonc` | OS (Linux) | Ubuntu 24.04 |
| `windows_baseline.json` | `os_windows2022.jsonc` | OS (Windows) | Windows 10 Home 22H2 (기준선), 주석 예시는 Windows Server 2022 |
| `rhel810_raw_fallback_baseline.json` | `os_linux_rhel810_raw_fallback.jsonc` | OS (Linux) | RHEL 8.10, Python 3.6 (raw 경로) |

주석 예시는 채널과 벤더 대표 한 대 기준이라 기준선과 장비가 정확히 같지 않을 수 있습니다.

## 합성 기준선 표시

실장비가 없는 벤더의 기준선은 합성 데이터이고 다음 두 곳에 표시합니다.

1. 위 표의 장비 칸에 "합성" 명시
2. 기준선 JSON의 `diagnosis.details.baseline_origin`에 출처와 교체 조건 명시

합성 기준선 통과는 fixture 통과이지 사이트 실측 통과가 아닙니다. 실장비 응답을 확보하면 실측 기준선으로 바꿉니다 (`docs/develop/08-onsite-capture.md`).

## 기준 시점

최초 수집일은 2026-03-23이고, `thermal` 섹션은 그 뒤에 추가되어 이 기준선들에는 `thermal` 키가 없습니다. 실장비(Dell iDRAC 9, HPE iLO 6, Lenovo XCC, Cisco CIMC)에서 `thermal: success`가 나오는 것은 production 명부 실행으로 확인했고, 기준선 재수집은 남은 작업입니다.

## 바꿀 때

1. 실장비에서 새로 수집합니다 (Jenkins Job 또는 `docs/operate/08-ansible-config.md`의 직접 실행).
2. 새 결과를 별도 폴더에 저장합니다.
3. 수집 환경과 사유를 `tests/evidence/<날짜>-<주제>.md`와 `docs/reference/decision-log.md`에 기록합니다.
4. 회귀 시험의 기준 폴더를 점진적으로 바꿉니다.

## 함께 보는 자료

| 자료 | 용도 |
|---|---|
| `tests/fixtures/` | 회귀 시험의 입력 (원본 응답) |
| `tests/evidence/` | 실장비 검증 기록 |
| `docs/contract/02-output-envelope.md` | 봉투 모양 |
| `docs/contract/03-fields.md` | 필드 사전 |
| `docs/reference/live-validation.md` | 실장비 검증 |
