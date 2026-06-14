# schema/output_examples/ — 호출자용 JSON 출력 예시 (한글 주석본)

> **2026-05-07 신설** — 실 장비 개더링 결과를 JSONC (JSON with Comments) 포맷으로 정리한 호출자용 reference.

## 1. 무엇인가

server-exporter가 3-channel (os / esxi / redfish) 통합 수집 후 만들어내는 표준 JSON envelope 의 **실 장비 결과 예시**입니다. 각 파일은:
- 실 장비에서 직접 개더링한 응답을 그대로 사용 (sanitize 안 함)
- JSON 키마다 **한글 주석** 추가 (호출자 / 운영자 / 신규 작업자가 즉시 이해 가능)
- 한 파일 내에서 같은 키가 여러 곳에 등장하면 **첫 등장 시에만 주석** (예: `health` 가 `hardware.health`, `controller.health`, `drive.health` 에 등장 → `hardware.health` 만 주석)

## 2. `schema/baseline_v1/` 와의 차이

| 디렉터리 | 정본 의도 | 누가 사용 |
|---|---|---|
| `schema/baseline_v1/` | **회귀 기준선** (Jenkins Stage 4 pytest 입력 — `tests/e2e/test_redfish_baseline.py` 등) | 자동화 회귀 |
| `schema/output_examples/` | **호출자 / 운영자 reference** — 한글 주석 + 실 응답 | 사람 |
| `schema/examples/` | 시나리오 별 (success / partial / failed / not_supported) 예시 — 1대 mock 기반 | 호출자 (시나리오 설명) |

## 3. 파일 list

### OS 채널 (target_type: "os" / collection_method: "agent")

| 파일 | 대상 | 특이사항 |
|---|---|---|
| `os_linux_rhel810_raw_fallback.jsonc` | RHEL 8.10 (10.100.64.161) | **Linux 2-tier raw fallback** — Python 3.6.8 → setup 모듈 미동작 → `raw` 모듈로 대체 (cycle 2026-04-29 핵심) |
| `os_linux_ubuntu2404.jsonc` | Ubuntu 24.04 (10.100.64.167) | Debian 계열 — apt / netplan / systemd-resolved |
| `os_linux_baremetal_dell.jsonc` | RHEL 베어메탈 (10.100.64.96 / 10.100.15.33 BMC) | DMI dmidecode 로 `vendor=dell` 감지 — VM 과 다름 |
| `os_windows2022.jsonc` | Windows Server 2022 (10.100.64.135) | WinRM HTTP (5985) — winrm-cert 부재 환경 |

### ESXi 채널 (target_type: "esxi" / collection_method: "vsphere_api")

| 파일 | 대상 | 특이사항 |
|---|---|---|
| `esxi_vmware.jsonc` | VMware ESXi 7.0.3 on Cisco UCS (10.100.64.1) | community.vmware + pyvmomi |

### Redfish 채널 (target_type: "redfish" / collection_method: "redfish_api")

| 파일 | 대상 | adapter |
|---|---|---|
| `redfish_dell_idrac10.jsonc` | Dell PowerEdge R760 / iDRAC 7.10.70.00 (10.100.15.27) | `redfish_dell_idrac10` |
| `redfish_hpe_ilo6.jsonc` | HPE ProLiant DL380 Gen11 / iLO 6 v1.73 (10.50.11.231) | 캡처에는 `redfish_hpe_ilo7` 로 찍혀 있다 (cycle 2026-05-11 T-01 fix 이전 캡처). 현재 코드는 `redfish_hpe_ilo6` 를 선택한다 — 재캡처 필요 |
| **`redfish_hpe_csus_3200.jsonc`** (cycle 2026-05-12) | **HPE Compute Scale-up Server 3200 — Mock 합성 (lab 부재 / sdflexutils + DMTF v1.15 + iLO5 API ref 합성)** | `redfish_hpe_csus_3200` (priority=96 / RMC primary / data.multi_node 활성) |
| `redfish_lenovo_xcc.jsonc` | Lenovo ThinkSystem SR650 V2 / XCC AFBT58B 5.70 (10.50.11.232) | `redfish_lenovo_xcc3` |
| `redfish_cisco_cimc.jsonc` | Cisco UCS C220 M4 / CIMC 4.1(2g) (10.100.15.2) | `redfish_cisco_ucs_xseries` |
| `redfish_failed.jsonc` | Cisco UCS BMC 503 Service Unavailable (10.100.15.1) | **status=failed 사례** — protocol_supported=true 이지만 root 503 |

## 4. envelope 13 필드 (모든 파일 공통)

```text
target_type, collection_method, ip, hostname, vendor,
status, sections, diagnosis, meta, correlation,
errors, data, schema_version
```

상세 필드 설명은 [`schema/field_dictionary.yml`](../field_dictionary.yml) 참조 (Must 47 + Nice 81 + Skip 6 = 134 entries).

## 5. JSONC 주석 규칙

- `// ...` 형식 (단일 라인)
- 같은 envelope 내 **같은 키** 가 여러 hierarchy 에 등장 시 → 첫 등장에만 주석
  - 예: `name` 이 `slot.name`, `controller.name`, `drive.name`, `interface.name` 에 등장 → 가장 위 `slot.name` 만 주석
- JSON 자체는 valid 유지 (JSONC parser 또는 주석 제거 후 JSON parser 통과)

## 6. 갱신 주기

- 펌웨어 / 환경 변경 시 `update-vendor-baseline` skill 또는 본 디렉터리 직접 갱신
- Round 검증 후 (rule 40 R2) → `tests/evidence/<날짜>-<vendor>.md` 와 함께 갱신
- 6개월 동안 갱신 0건 시 stale 가능 — `EXTERNAL_CONTRACTS.md` 동기화 권장

## 7. 출처

- 캡처 일시: 2026-05-07
- 캡처 환경: Jenkins 에이전트 10.100.64.155 (Ansible 2.20.3 / Python 3.12 venv `/opt/ansible-env/`)
- 자격증명: `vault/{linux,windows,esxi}.yml` + `vault/redfish/{vendor}.yml` (cycle 2026-04-29 5 vendor 통일 — primary `infraops/Passw0rd1!Infra` + recovery)
- 스크립트: `tests/evidence/2026-05-07-real-gather.md` (캡처 절차 + 명령 기록)

## 8. 호출자 사용 가이드

호출자 시스템 (Jenkins downstream / 모니터링 / 포털) 은:
1. envelope 13 필드 fixed (rule 13 R5) — shape 변경 0
2. `status` 으로 1차 분기 (success / partial / failed)
3. `sections.<섹션>` 으로 2차 분기 (success / failed / not_supported)
4. `errors[]` 가 있어도 `status=success` 일 수 있음 (warning 수준 — rule 13 R8 시나리오 B)
5. `data.<섹션>` 의 channel-specific 필드는 본 예시 reference 사용
