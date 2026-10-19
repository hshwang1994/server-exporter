# 2026-10-19 — ESXi 전원·온도·팬(vSphere 하드웨어 센서) · Linux iSCSI 이니시에이터 — 증거

> 정본 결정: `docs/ai/decisions/ADR-2026-10-19-esxi-sensors-and-linux-iscsi.md`. 계약: `docs/contract/03-fields.md` 6.3.1 · 6.5 · 6.7.
> 실장비 아님 — ESXi 값은 **실 호스트 pyvmomi 덤프 3대 재생**(`tests/reference/esxi/10_100_64_{1,2,3}/pyvmomi_host_dump.json`, Cisco TA-UNODE-G1 · ESXi 7),
> Linux iSCSI 는 합성 sysfs(실제 sh 실행). 실호스트 봉투는 Jenkins ESXi 매트릭스(E2E-D)에서 확인한다 — 결과는 이 문서 5절에 덧붙인다.

## 1. 왜

사용자 승인(2026-10-19): "ESXi 전원·온도·팬 수집, Linux iSCSI HBA 수집 구현 승인 … 끝나면 production 반영까지". 두 항목은 같은 날 범위 감사(`2026-10-19-csus-single-server-summary-audit.md` 5절)가
"읽지 않는 인벤토리" 로 올린 결정 항목이다.

## 2. ESXi 센서 — 덤프 사실과 변환

| 덤프(3대 공통) | 값 | 변환 |
|---|---|---|
| `numericSensorInfo` 수 | 126 | `sensor_count` |
| sensorType temperature | 28 (`System Board 4 RISER2_OUTLETTMP` 4700 e-2 'degrees C' …) | `temperatures[]` 28 — `reading_celsius` 47, `physical_context` SystemBoard/CPU/Memory/PowerSupply, `upper_critical` null |
| sensorType fan | 12 (`Fan Device 6 FAN6_TACH2` 1410000 e-2 'RPM') | `fans[]` 12 — `reading` 14100, `reading_units` RPM |
| sensorType power | 12 — PSU1/2 × {PIN(Watts) · POUT(Watts) · IOUT(Amps) · PWRGD · STATUS(unspecified)} + `System Board 0 POWER_USAGE`(Watts) + `Power Module (DC-to-DC) 0 PS_RDNDNT_MODE` | `power_supplies[]` 2(`Power Supply 1/2`, Enabled, 용량 · 모델 null) · `power_consumed_watts` 472 / 432 / 456(10_100_64_1/2/3) · `power_sensors[]` 5 |
| voltage 33 · memory 16 · processor 15 · storage 8 · systemBoard 2 | — | 계약에 없어 내지 않는다 |
| `healthState.key` | 덤프에 `<truncated:str>`(수집기가 잘라 둔 자리) | 값 분포 **실장비 미확인** — 변환표 green/yellow/red/unknown 은 vSphere API 열거형(HostNumericSensorHealthState) |
| `hardwareStatusInfo` (memoryStatusInfo 32 · cpuStatusInfo 30) | 상태 색만 | 읽지 않는다(허용 목록 유지 — 그룹 키는 `runtime.healthSystemRuntime` 하나라 센서 소비로 함께 소비 처리) |

`power.summary`(공통 필터): `psu_count 2 · psu_active 2 · redundant true · total_capacity_w null · capacity_unknown_count 2 · consumed_watts 472 · consumed_capacity_pct null · health_rollup OK`.

## 3. Linux iSCSI — 합성 sysfs 시나리오 (실제 sh 실행, `tests/unit/test_linux_iscsi_hba.py`)

| 시나리오 | 트리 | 결과 |
|---|---|---|
| 소프트웨어 iSCSI 세션 2 | host3/host4 (initiatorname "<empty>", proc_name iscsi_tcp, 각 session LOGGED_IN, 세션 initiatorname 같은 IQN) | hbas 1건: `iqn` 보충 · `driver iscsi_tcp` · `link_status up` · `session_count 2` · wwpn/wwnn/model/vendor/speed null |
| 하드웨어 오프로드 | host5 bnx2i, hwaddress · netdev eth2 · ipaddress · port_state LINK UP · port_speed 10 Gbps · PCI uevent → lspci shim | `model` NetXtreme II BCM57810 · `vendor` Broadcom … · `link_speed_gbps 10` · `mac_address` 소문자 · `session_count 0` · lspci 1회 |
| LINK DOWN + FAILED 세션 | | `down`, session_count 1 |
| 오프로드 2포트 | hwaddress 다름 | 2건 분리 |
| initiatorname 읽기 실패 | 디렉터리로 만든 속성 | `ERR|` 1건 → storage errors[] 1건 `scope=iscsi_host; cause=attribute_unreadable`, 항목은 남고 iqn null |
| iscsi_host 클래스 없음 | | ISCSI 줄 0 · FC/IB 결과 불변 |

## 4. 검증 (실장비 아님)

| 구분 | 결과 |
|---|---|
| 신규 `tests/unit/test_esxi_sensors.py` | 32 passed (모듈 파트 · 덤프 3대 재생 · YAML 렌더 3갈래 · power_summary ↔ Redfish Jinja 7케이스 · 계약 배선) |
| 신규 `tests/unit/test_linux_iscsi_hba.py` | 7 passed (위 표) |
| 갱신 — `test_esxi_section_errors`(sensors 파트 스텁) · `test_windows_storage_enum_render`(iqn) · `test_windows_call_consolidation_render`(hbas iqn 의도 변경 등록) · `test_linux_hba_ib_markers`(sysfs 치환기) | 통과 |
| 영향 영역 | Windows storage 4파일 187 passed · 실패 봉투 모양표 3사본(json_only.py · se_finalize.groovy · supported_sections.yml) + finalize corpus 3건 재생성 뒤 `test_json_only_fallback_shape` · `test_finalize_gather_output` · `test_jenkinsfile_portal_finalize` · `test_finalize_corpus` 통과 · 단위 7분할 전부 4626 passed — TEST_HISTORY 2026-10-19 (3) |
| e2e / regression | 1093 passed, 12 skipped, 7 xfailed |
| 정적 | `output_schema_drift_check.py` 통과(fd_paths 207) · `validate_field_dictionary.py` PASS · `verify_vendor_boundary.py` 통과 · WSL `ansible-playbook --syntax-check` os · esxi 통과 |

## 5. 실장비 (Jenkins 매트릭스 · 승격)

(승격 절차 뒤 이 절에 기록 — E2E-D ESXi 6대의 `sections.power/thermal` · `data.power.summary` · `data.thermal` 수, S1~S3 Linux 호스트의 hbas(iSCSI 세션 없음 → 불변 예상).)
