# schema/output_examples: 호출자용 출력 예시 (한글 주석본)

실장비 수집 결과에 한글 주석을 단 호출자와 운영자용 참고 자료입니다. 각 파일은 실장비 응답을 그대로 쓰고, JSON 키마다 주석을 달았습니다. 같은 키가 여러 곳에 나오면 첫 등장에만 주석이 있습니다.

## 다른 폴더와의 차이

| 디렉터리 | 용도 | 누가 쓰나 |
|---|---|---|
| `schema/baseline_v1/` | 회귀 기준선 (시험 입력) | 자동 회귀 |
| `schema/output_examples/` | 한글 주석을 단 실장비 예시 | 사람 |
| `schema/examples/` | 시나리오별(success, partial, failed, not_supported) 예시. 한 대 기준의 모의 데이터 | 호출자 (시나리오 설명) |

## 파일

### OS 채널 (`target_type: os`, `collection_method: agent`)

| 파일 | 대상 | 특이사항 |
|---|---|---|
| `os_linux_rhel810_raw_fallback.jsonc` | RHEL 8.10 | Python 3.6이라 raw 경로로 수집한 결과 |
| `os_linux_ubuntu2404.jsonc` | Ubuntu 24.04 | Debian 계열 |
| `os_linux_baremetal_dell.jsonc` | Dell 물리 서버 위 Linux | DMI 제조사로 `vendor: dell` |
| `os_windows2022.jsonc` | Windows Server 2022 | WinRM HTTP (5985) |

### ESXi 채널 (`target_type: esxi`, `collection_method: vsphere_api`)

| 파일 | 대상 |
|---|---|
| `esxi_vmware.jsonc` | VMware ESXi 7.0.3 (Cisco UCS) |

### Redfish 채널 (`target_type: redfish`, `collection_method: redfish_api`)

| 파일 | 대상 | 비고 |
|---|---|---|
| `redfish_dell_idrac9.jsonc` | Dell PowerEdge R760 (iDRAC 9) | 캡처 당시 `meta.adapter_id`는 `redfish_dell_idrac10`입니다. 현재 코드는 `redfish_dell_idrac9`를 고릅니다 |
| `redfish_hpe_ilo6.jsonc` | HPE ProLiant DL380 Gen11 (iLO 6 v1.73) | 캡처 당시 `meta.adapter_id`는 `redfish_hpe_ilo7`입니다. 현재 코드는 `redfish_hpe_ilo6`를 고릅니다 |
| `redfish_hpe_csus_3200.jsonc` | HPE Compute Scale-up Server 3200 | 실장비 없이 벤더 문서와 DMTF 스키마로 합성한 예시. `data.multi_node` 활성 |
| `redfish_lenovo_xcc.jsonc` | Lenovo ThinkSystem SR650 V2 (XCC 5.70) | 캡처 당시 `meta.adapter_id`는 `redfish_lenovo_xcc3`입니다. 현재 코드는 `redfish_lenovo_xcc`를 고릅니다 |
| `redfish_cisco_cimc.jsonc` | Cisco UCS C220 M4 (CIMC 4.1(2g)) | 캡처 당시 `meta.adapter_id`는 `redfish_cisco_ucs_xseries`입니다. 현재 코드는 `redfish_cisco_cimc`를 고릅니다 |
| `redfish_failed.jsonc` | Redfish 서비스가 꺼진 Cisco BMC | `status: failed` 사례. 443은 열렸지만 서비스 루트가 503 |

어댑터 선택 결과는 2026-05-07 캡처 이후 바뀌었고, 예시의 `meta.adapter_id`는 캡처 당시 값입니다. 값(data)은 어댑터와 무관하게 같은 수집 경로의 결과입니다. 현재 선택 결과는 `docs/reference/live-validation.md`의 명부 기록에 있습니다.

## 봉투 13 필드 (모든 파일 공통)

```text
target_type, collection_method, ip, hostname, vendor,
status, sections, diagnosis, meta, correlation,
errors, data, schema_version
```

필드 설명은 `schema/field_dictionary.yml`과 `docs/contract/03-fields.md`에 있습니다.

## JSONC 주석 규칙

- `// ...` 단일 행 주석
- 같은 봉투 안에서 같은 키가 여러 계층에 나오면 첫 등장에만 주석
- 주석을 지우면 유효한 JSON이어야 합니다

## 출처

- 캡처 일시: 2026-05-07 (`tests/evidence/2026-05-07-real-gather.md`)
- 캡처 환경: 사내 Jenkins Runner, ansible-core 2.20.3, Python 3.12 venv

## 호출자 사용 가이드

1. 봉투 13 필드는 고정입니다.
2. `status`로 1차 분기합니다 (success, partial, failed).
3. `sections.<섹션>`으로 2차 분기합니다 (success, failed, not_supported).
4. `errors[]`가 있어도 `status`가 `success`일 수 있습니다. 안내 수준의 항목입니다.
5. `data.<섹션>`의 채널별 필드는 이 예시를 참고합니다.
