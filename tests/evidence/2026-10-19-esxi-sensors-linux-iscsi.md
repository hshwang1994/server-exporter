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

### 5.1 main Job 매트릭스 — main `447b6af7`(`clovirone-cicd/clovirone-server-gather-main` #709~#719, 2026-10-19)

투입은 2026-10-19 첫 라운드(#689~#699)와 같은 입력(eventUuid 만 `…h0NN`), 스크래치 `matrix_runner.py`(netrc 경로 인자, 값 비출력)로 사용자가 `!` 실행 — 이 세션의 자동 모드 분류기가
브라우저의 `buildWithParameters` POST 를 거부해 AI 가 직접 투입하지 못했다. T5 는 콘솔 `정보 수집을 시작합니다` 관측 +10초 stop. 11건 전부 기대 결과, checkout `447b6af7`(E2E-A2 는 fail-closed 라 없음;
tip 관측 before 1792417503 · after 1792418013 · `447b6af7` 불변).

| 시나리오 | 빌드 | 결과 | 소요 | 확인한 값 |
|---|---|---|---|---|
| S1 | #709 | SUCCESS | 84초 | Linux 3 |
| S2 | #710 | SUCCESS | 119초 | 혼합 5 |
| S3 | #711 | SUCCESS | 151초 | Linux 11 — 전부 success · errors 0 · `hbas []`(iSCSI 세션 없음 → iSCSI 0, 예상대로) · `memory.summary.grand_total_gb` 8/8/8/8/4/4/256/128/4/8/8 · **`network.summary.groups` 에 `speed_mbps null` 그룹**(.95: `10000×2 up1` + `null×2 up0`, .96: `10000×1` + `null×3` + `1000×1` — 둘째 라운드 B-3 실측) |
| S4 | #712 | SUCCESS | 148초 | Windows .120 — `system.version 2022-21H2` · hbas [] · errors 0 |
| T2 | #713 | SUCCESS | 85초 | TEST-NET 빠른 실패 |
| T6 | #714 | UNSTABLE | 123초 | Callback 닫힌 포트(계약값) |
| E2E-A | #715 | UNSTABLE | 123초 | loc=cj smoke |
| E2E-A2 | #716 | FAILURE | 30초 | loc=chj fail-closed |
| **E2E-D** | **#717** | SUCCESS | 100초 | **ESXi 6대 전부 `sections.power = success` · `sections.thermal = success` · errors 0.** Cisco TA-UNODE-G1 ×3(.1 .2 .3): PSU 2(`Power Supply 1/2`) · `power_consumed_watts` 448/424/400 · `total_capacity_w null` · `health_rollup OK` · 온도 28 · 팬 12 · physical_disks 2 · logical_volumes 2(RAID LUN, protocol null) · esxi01 hbas `iSCSI:up` 1 · esxi02 FC `down/down` 2. Dell PowerEdge R760 ×3(.91 .92 .93): PSU 2 · **`power_consumed_watts null`**(PSU 가 아닌 Watts 센서가 1개가 아님 — 규칙대로 추정 안 함) · 온도 5/4/4 · 팬 7 · physical_disks 1 **`protocol NVMe`**(둘째 라운드 B-4 실측). 전 6대 `network.summary.groups` 에 `null~ethernet` 다운 포트 그룹 + `link_type ethernet`(B-3/B-5 실측) |
| E2E-E | #718 | SUCCESS | 425초 | Redfish 7 — Dell ×5 `psu 1 · total_capacity_w 800 · consumed_capacity_pct 30.5~39.8 · adapter_count 2(.34 는 3) · controllers 4 · logical_threads 48 · part_number 0024FGA04`, Lenovo `psu 2 · 750 · 29.3 · adapter_count 1 · lt 128 · SB27A75070`, Cisco .2 `psu 2 · 1540 · 27.0 · adapter_count 0 · controllers 2 · hbas 4 · lt 44 · part_number null`(adapter_count 0 은 UCS VIC 1225 ×2 의 NetworkPorts 4개가 전부 FibreChannel 이라 둘째 라운드 A-4 규칙으로 빠진 것 — 호스트 EthernetInterfaces 6개는 `port_count 6` 으로 남는다; VIC 처럼 FC 포트만 노출하는 통합 카드의 뜻은 검토 항목). errors 0 — 둘째 라운드 A-3(용량 있는 벤더는 값 유지) · A-4 · A-7(part_number 가 이미 있는 벤더 불변) 실측 |
| T5 | #719 | ABORTED | 63초 | `lastBuiltRevision 447b6af7`(증거 결속) |

### 5.2 CI #65 · 승격 `d464de4b`

- **CI** `clovirone-cicd/clovirone-server-gather-ci` #65 — `PROMOTE=true · PROMOTE_SHA=447b6af7 · PROMOTE_DRY_RUN=false`, `E2E_MAIN_ENTRIES` 11건(#709~#719), `E2E_TIP_OBSERVATIONS_JSON`(E2E-A2 #716, before 1792417503 · after 1792418013, `447b6af7` 불변).
  SUCCESS 62분 · 12 stage 전부 SUCCESS(Checkout · Toolchain · Gate 7분 · Finalize Corpus · Time Limits Self-test · Prodgen Build · Prodgen Drift · Prodgen Verify 10분 · Harness Driver 29분 · Harness(prodtree) 13분 · Evidence Aggregate · Prodgen Promote) ·
  집계 verdict **COMPLETE_PASS**(main `447b6af7`) · `prodgen_promote.json` `e2e.ok=true` · `ci_stages.ok=true` · Promote 는 종전과 같이 Jenkins 측 GitLab push 자격 부재로 dry-run(원격 변경 0).
- **승격(실제)** — 작업 PC, 스크래치 `promote_ci65.py`(사용자 `!` 실행 — CI 산출물 3개 netrc 로 내려받기 → `prodgen promote --sha 447b6af7 --verify-report … --e2e-evidence … --ci-stage-results … --push-remote origin,internal`, 자격 파일 경로만 인자 · 값 비출력).
  → **production `d464de4b785a1c1a4b738c347578933d2c742ab6`**(parent `027409f4` · Main-SHA `447b6af7` · Tree-Hash `487fa962…` · 197 파일 · Verdict COMPLETE_PASS · Gates G01~G20 PASS · Gates-Rerun G11 G12 G13 G14 G15 G18 G19 G20(G19 실장비 3채널 포함) · Gates-Reused G01~G10 G16 G17 ·
  CI-Build #65 · CI-Stages verified · Generated-At 2026-10-19T22:31:05Z). publish origin "accepted by remote" · internal "already at the new commit (shared push URL)" · 로컬 ref 갱신. **github · gitlab · 로컬 `production` 모두 `d464de4b`**, `drift-check` PROVENANCE(main `447b6af7`).

### 5.3 production `d464de4b` canary (production Job `clovirone-cicd/clovirone-server-gather` #314~#317, 2026-10-20 — 스크래치 `canary_runner.py`, 사용자 `!` 실행)

| 빌드 | 채널 | 결과 | 확인 (checkout 전부 `d464de4b` · 결과 수 == 접수 수 · errors 0 · 13키) |
|---|---|---|---|
| #314 | ESXi 6 (.1 .2 .3 .91 .92 .93) | SUCCESS 82초 | 6/6 success · **`sections.power/thermal` 전부 success**. Cisco TA-UNODE-G1 ×3(adapter esxi_7x): PSU 2 · 소비전력 384/432/400 W · 온도 28 · 팬 12 · esxi01 iSCSI up · esxi02 FC down/down · RAID LUN protocol null. Dell R760 ×3(adapter **esxi_9x**): PSU 2 · 소비전력 null(PSU 외 Watts 센서 1개 규칙) · 온도 5/4/4 · 팬 7 · physical_disks protocol NVMe |
| #315 | Redfish 7 | SUCCESS 393초 | 7/7 success · Dell ×5 `total_capacity_w 800 · pct 29.9~40.9 · adapter_count 2(.34 는 3) · controllers 4 · lt 48 · part_number 0024FGA04` · Lenovo `750 · 33.1 · 1 · 1 · 128 · SB27A75070` · Cisco .2 `1540 · 26.5 · adapter_count 0 · ctrl 2 · lt 44` — 매트릭스 #718 과 같은 값(소비전력만 시각차) |
| #316 | OS 11 | SUCCESS 126초 | 11/11 success · hbas 0(iSCSI 세션 없음) · `memory.summary.grand_total_gb` 8/8/8/8/4/4/256/128/4/8/8 · .95 `speed_mbps null` 그룹 2 · .96 null 그룹 3(다운 포트 실측) · RHEL 9.6/9.2/10.2 · Ubuntu 24.04 |
| #317 | Windows 1 (.120) | SUCCESS 135초 | 1/1 success · `system.version 2022-21H2` · hbas 0 · memGB 8 · 네트워크 그룹 20000×2 · 10000×2 |

### 5.4 `schema/baseline_v1/esxi_baseline.json` 실측 갱신 (rule 13 R4)

canary #314 의 esxi02(10.100.64.2, ESXi 7.x → adapter `esxi_7x`) 봉투 그대로. 종전 baseline(adapter `esxi_generic`, `sections` 10개 · `power` not_supported · `thermal` 키 없음)을 교체 —
`sections.power/thermal success`, `data.power`(PSU 2 · 432 W · summary) · `data.thermal`(온도 28 · 팬 12), 그 사이의 다른 라운드 변경(hbas link_status · logical_volumes · network.summary 다운 포트 그룹 · link_type ethernet)도 함께 실측값이 됐다.
`tests/e2e/test_esxi_output.py::test_adapter_id` 기대값 `esxi_generic` → `esxi_7x`.
