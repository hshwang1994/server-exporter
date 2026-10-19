# 2026-10-19 — HPE CSUS 3200 단일 서버 정합 · 수집 범위 감사 · 3채널 summary 결함 — 증거

> 정본 결정: `docs/ai/decisions/ADR-2026-10-19-csus-single-server-and-summary-fixes.md`. 계약: `docs/contract/03-fields.md` 6.1 · 6.2 · 6.3 · 6.3.2 · 6.4 · 6.5 · 6.7 · 8 · FAQ.
> 실장비 아님 — CSUS 는 lab 에 없다. 아래 CSUS 값은 **실장비 전수 미러(RMC 1.75.108, 4노드) 재생**과 `normalize_standard.yml` 의 **실제 ansible-core 템플러 렌더**다.
> OS · ESXi 변경은 합성 입력 단위 시험까지이고 Jenkins main Job 매트릭스(실장비)는 아직 돌리지 않았다(NEXT_ACTIONS).

## 1. 무엇을 확인하려 했나

- 사용자(2026-10-19): CSUS 3200 은 사이트 협약상 파티션 1개 → 다른 x86 서버와 같은 JSON, Partition0 = 서버, 시리얼은 `-000` 을 뗀 물리 시리얼 유지.
  보고 증상 "디스크 구성·합계가 보이는 CSUS 는 hbas 가 없고, 디스크가 없는 CSUS 는 hbas 가 보인다"(운영 중인 서로 다른 두 장비, JSON 반출 불가). 그 밖의 CSUS 버그와 전 장비 summary 버그.
- 이어진 질문 — "특정 것만 수집해서 빠지는 것 아닌가", "다른 채널도 아는 것만 부르는 것 아닌가, 전체 mock · 전체 API 를 대조하나".

## 2. 방법

| 단계 | 도구 | 입력 |
|---|---|---|
| 모듈 재생 | `tests/redfish-probe/replay_full_mirror.py --layout rmc_primary --firmware-scope complex_only` | `C:\github\서버mock데이터\HPE_CSUS3200\{01,02,03,04}`(RMC 가 노출한 전 리소스 미러 — node01 490 · node02 493 · node03 637 · node04 636 파일) |
| normalize 렌더 | 스크래치 `render_csus_normalize.py` — `tests/e2e/test_diagnosis_template_ansible_render.py` 의 `_templar`/`_trust` 로 `normalize_standard.yml` → `merge_fragment.yml` → `build_correlation.yml` 을 실제 Templar 로 평가 | 위 재생 산출 + `adapters/redfish/hpe_csus_3200.yml` |
| 노출 vs 요청 대조 | `scripts/ai/redfish_coverage_diff.py`(이 세션 스크래치 → 정식 스크립트) | 위 미러 + 저장소 안 전수 크롤 `tests/reference/redfish/{dell,hpe,lenovo,cisco}/` |
| 녹화본 회귀 | `tests/integration/test_real_capture_replay.py` · `test_request_budget.py` · 신규 `test_redfish_csus_single_server_render.py` | `tests/fixtures/redfish/real_hpe_csus3200/`(미러 01 재캡처) + Dell/HPE/Lenovo 녹화본 |

## 3. 실 4노드 — 고치기 전 / 고친 뒤 (현재 main 라이브러리 + 이 변경)

| 항목 | node01 (SGHD3TLNDD) | node02 (SGHD3VFL1S) | node03 (SGHD3QHLDT) | node04 (SGHD3QHLN3) |
|---|---|---|---|---|
| `hardware.serial` · `correlation.serial_number` | `SGHD3TLNDD` (불변) | `SGHD3VFL1S` | `SGHD3QHLDT` | `SGHD3QHLN3` |
| `hardware.part_number` (A-7) | null → **`R9N70A`** | 〃 | 〃 | 〃 |
| `cpu.logical_threads` (A-2) | 32 → **64** (4소켓 × 8코어 × HT) | 32 → **64** | 64 → **128** | 64 → **128** |
| `cpu.summary.groups[0].cores_per_socket` (B-11) | 8 (불변 — 동질 CPU) | 8 | 16 | 16 |
| `storage.physical_disks` / `summary` | 0 / `grand_total_gb 0` (불변) | 0 | 2 (SAS SSD 1490 GB) / 2980 (불변) | 2 / 2980 |
| `storage.controllers` (A-6 · A-8) | 1("Npar 0 Storage", 모델 null) → **0** | 1 → **0** | 1(모델 null) → **1 `HPE SR3258p-16i/e PCIe4 Controller` · Adaptec · fw `03.01.44.040-0`** | 〃 |
| `storage.hbas` | 4 (불변) | 4 | 8 | 8 |
| `network.adapters` / `interfaces` | 2(FC 카드만) / 0 (불변) | 2 / 0 | 8(Mellanox 4 + FC 4) / 8 | 8 / 8 |
| `network.summary.adapter_count` (A-4) | 2 → **0** | 2 → **0** | 8 → **4** | 8 → **4** |
| `power.summary.total_capacity_w` / `consumed_capacity_pct` (A-3) | 0 / 0 → **null / null** (`capacity_unknown_count 4`, `consumed_watts 591`) | → null / null (600 W) | → null / null (1000 W) | → null / null (945 W) |
| `firmware[]` (A-9) | 2 → **6** (ComplexFW · Partition0_FW + PSU 4) | 2 → 6 | 2 → **15** (+ PCIe 장치 9 · PSU 4; `PCIeDevice.3` = storage_controller) | 2 → 15 |
| `multi_node` | 유지 (사용자 결정) · `partitions[0].system.serial` `-000` 원문 | 〃 | 〃 | 〃 |
| 요청 수 (GET) | 134 → 141 (+7: `Chassis/r001u01/Drives` 1 · `PCIeDevices` 컬렉션 1 · 미캐시 장치 5) | +7 | 205 → 207 distinct / 210 GET | 〃 |
| sections / errors | 전부 success · errors 0 (불변) | 〃 | 〃 | 〃 |

**보고된 "디스크 ↔ hbas 상호배제" 는 4노드 어디서도 재현되지 않았다** — node03/04 는 디스크 2 와 hbas 8 이, node01/02 는 디스크 0 과 hbas 4 가 함께 나온다(고치기 전 코드도 같다).
사이트의 두 장비는 이 4대와 다른 장비이고 JSON 을 받을 수 없으므로 코드로는 (a) 카드 수집 경로 1개 추가(A-5), (b) 빈 결과 사유 notice, (c) 장비 JSON 에서 읽을 체크리스트(`03-fields.md` 6.3.2 끝)로 대응한다.

## 4. 결함 근거 (미러 원문)

| # | 결함 | 미러 근거 |
|---|---|---|
| A-2 | `ProcessorSummary.LogicalProcessorCount` 가 코어 수 | node01 `Systems/Partition0`: `ProcessorSummary {Count 4, LogicalProcessorCount 32}`; `Processors/*`: `TotalCores 8 · TotalThreads 16` × 4; `Bios.Attributes.HThread: Enabled`. node03: 64 / 16·32 × 4. 2026-10-18 X3 규칙(LogicalProcessorCount 우선)이 이 펌웨어에서 과소집계 → adapter `processor_summary_logical_count: cores` 로 가른다 |
| A-3 | PSU 용량 전부 미제공 | `Chassis/r001u01/Power.PowerSupplies[0..3]` 에 `PowerCapacityWatts` 없음(`Version`, `Model`, `Status` 만). 종전 summary 는 `total_capacity_w 0 · consumed_capacity_pct 0` |
| A-4 | FC 카드가 `adapter_count` 에 들어감 | node01 `NetworkAdapters` = `PCIeCard10` · `PCIeCard13`(둘 다 `HPE SN1100Q 16Gb 2P FC HBA`, 포트 전부 FibreChannel) → 종전 adapter_count 2 |
| A-6 | 빈 Storage 컨테이너 | node01 `Systems/Partition0/Storage/1`: `Name "Npar 0 Storage"`, `StorageControllers` 없음, `Drives []`, `Volumes` 없음 |
| A-7 | PartNumber 위치 | `Systems/Partition0` 에 `PartNumber` 없음, `Chassis/r001u01.PartNumber "R9N70A"` |
| A-8 | RAID 컨트롤러 정체 위치 | node03 `Storage/1` 에 `StorageControllers` 없음 · `Drives` 2; `Chassis/r001u01/PCIeDevices/3`: Model `HPE SR3258p-16i/e PCIe4 Controller` · Manufacturer `Adaptec` · FirmwareVersion `03.01.44.040-0` · `Slot.Location.PartLocation.ServiceLabel rack1/chassis_u1/cpu0/io_slot3`; 드라이브 `PhysicalLocation.PartLocation.ServiceLabel rack1/chassis_u1/cpu0/io_slot3/box1/drive_bay1` ⊂ 슬롯 라벨 |
| A-9 | FirmwareInventory 범위 | `UpdateService/FirmwareInventory` 멤버 2 (`ComplexFW` · `Partition0_FW`); NIC/HBA/RAID 펌웨어는 `PCIeDevices/*.FirmwareVersion`(Mellanox `26.46.3048` · SN1100Q `9.15.05 (d0d5)` · RAID `03.01.44.040-0`), PSU 는 `PowerSupplies[].Version` 에만 |
| A-10 | 섀시 Drives 컬렉션 | `Chassis/r001u01/Drives` 존재(node03 멤버 2 = Storage/1.Drives 와 같음, node01 빈 목록) — 다른 매핑이면 Storage 경로만으로 누락 가능 → 드라이브 0건일 때만 폴백 |
| A-11 | 2섀시 이상 | 4노드는 `Links.Chassis` 1개(r001u01) — 다중 섀시 응답 없음, 합성 시험만 |
| A-5 | NetworkInterfaces 링크 | node01 `Systems/Partition0/NetworkInterfaces/NetworkIfPCIeCard10.Links.NetworkAdapter → Chassis/r001u01/NetworkAdapters/PCIeCard10` — 섀시 경로가 비거나 404 일 때의 대안 경로 |

## 5. 수집 범위 감사 ("노출 vs 요청") — 저장소 기록상 첫 전수 대조

| 원천 | 노출(200) | 요청 | 미요청 중 인벤토리성 (이번 처리) |
|---|---|---|---|
| CSUS node03 미러 (RMC 1.75.108) | 637 | 205 → 207 distinct (210 GET) | `Chassis/PCIeDevices`(+멤버) → A-8/A-9 읽음 · `Chassis/Drives` → A-10 조건부 · `Systems/NetworkInterfaces` → A-5 조건부 · 2번째 이후 섀시 Power/Thermal → A-11. 나머지 441 = Sensor 72 · SubProcessors 64 · UPI/패브릭/RMC Port 57 · JsonSchema 28 · Task 20 · ActionInfo 19 · LogEntry 11 · Assembly 10 … (비인벤토리) |
| Dell R740 외부 미러 `C:\github\서버mock데이터\DELL_R740` | 6014 | 137 | PCIe 트리 · NetworkInterfaces (전 벤더 공통 미요청 — 조건부 경로로 들어갔다) |
| HPE DL380 외부 미러 | 2022 | 131 | 〃 + `HpeServerDevice`/`HpeServerPciDevice`/`HpeServerPCISlot` OEM 인벤토리(결정 항목) |
| Lenovo SR650 외부 미러 | 2898 | 123 | 〃 + 드라이브 백플레인 Chassis · `LenovoSlot` |
| 저장소 크롤 `tests/reference/redfish/dell/10_100_15_27` | 2338 | 72 | `DellNIC` · `DellMemory` · `DellProcessor` · `DellController` · `DellPhysicalDisk` · `DellSlot 50` 등 OEM 상세(결정 항목) |
| 저장소 크롤 hpe/10_50_11_231 · lenovo/10_50_11_232 · cisco/10_100_15_2 | 2447 · 2748 · 683 | 130 · 103 · 84 | 허용 목록 사유 참조 |
| ESXi `tests/reference/esxi/*/pyvmomi_host_dump.json` (3 호스트) | 속성 그룹 78 | 35 | `runtime.healthSystemRuntime`(온도 28 · 팬 12 · 전력 12 센서 · CPU/메모리 상태) · `hardware_systemInfo.otherIdentifyingInfo` · `storage_device[].localDisk` 등 43 그룹 허용 목록(사유 포함) |
| Linux `tests/reference/os/*/cmd_*.txt` (명령 덤프 108종) | 108 | 48 | `ipmitool sensor/fru/sel` · `lshw` · `smartctl` · `storcli` · `nvme` · `multipath` … 60 명령 허용 목록(사유 포함) |

- 상시 회귀: `tests/regression/test_redfish_coverage_audit.py` · `test_esxi_property_coverage.py` · `test_os_command_coverage.py` — 허용 목록(`tests/reference/*/coverage_allowlist.yml`, 항목마다 사유)에 없는 미요청 인벤토리가 생기면 실패. 24 passed.
- 새 데이터 원천(ESXi 센서 → power/thermal · Linux iSCSI 이니시에이터 · RAID 뒤 PD 벤더 CLI · OS ipmitool · HPE/Dell/Lenovo OEM 인벤토리 · PCIeFunction/PCIeSlots)은 구현하지 않고 **결정 항목**으로 NEXT_ACTIONS 에 뒀다 — `sections` 가 바뀌거나 전제(root · 벤더 CLI)가 있는 것들이다.

## 6. OS · ESXi summary 결함 (B) — 수정과 시험

| # | 결함 | 수정 위치 | 시험 |
|---|---|---|---|
| B-1 | Linux `memory.summary.grand_total_gb` 모르면 0 / Redfish 0 | `os-gather/tasks/linux/gather_memory.yml` · `normalize_standard.yml _rf_summary_memory` | `tests/unit/test_os_summary_memory_null_total.py` · `test_redfish_csus_single_server.py` |
| B-2 | Linux VLAN 하위 IF · bond slave · bridge/team member 가 summary 에 중복 | `gather_network.yml` summary 를 토폴로지 정규화 뒤로 이동 | `tests/unit/test_os_summary_network_groups.py` |
| B-3 | speed 미보고 포트가 OS/ESXi summary 에서 사라짐 | Linux · Windows `gather_network.yml`, ESXi `collect_network_extended.yml` — `speed_mbps null` 그룹 | 〃 · `tests/unit/test_esxi_network_summary_down_ports.py` |
| B-4 | ESXi `physical_disks[].protocol` 항상 null | `esxi-gather/library/esxi_disks.py` `_LUN_PROTOCOL_BY_CONTROLLER` | `tests/unit/test_esxi_disks_protocol.py` |
| B-5 | ESXi vmnic `link_type` null | `collect_network_extended.yml` → `ethernet` | `test_esxi_network_summary_down_ports.py` |
| B-6 | ESXi datastore `freeSpace None` → 0 → usage 100% | `esxi-gather/tasks/normalize_storage.yml` | `tests/unit/test_esxi_datastore_free_none.py` |
| B-7 | ESXi 텍스트 폴백 KB/PB/Bytes 를 GB 로 읽음 | 〃 단위표 B/KB/MB/GB/TB/PB(IEC 포함) | 〃 |
| B-8 | ESXi hostname 이 IPv4 첫 옥텟 | `esxi-gather/tasks/normalize_system.yml` IPv4 꼴 → null | `tests/unit/test_esxi_hostname_ip_guard.py` |
| B-9 | Linux zram/nbd/drbd/ram/fd 가 디스크 | `gather_storage.yml` `_l_stor_pseudo_disk_re`(JSON · TXT 두 경로) | `tests/unit/test_os_storage_pseudo_devices.py` |
| B-10 | DIMM ≤ 512 MiB 가 `unit_capacity_gb 0` 그룹 | Linux · Windows `gather_memory.yml`, Redfish `_rf_summary_memory` — `cap_gb > 0` | `test_os_summary_memory_null_total.py` · Redfish 단위 |
| B-11 | Redfish `cores_per_socket` 첫 소켓 값 | `_rf_summary_cpu` → `total_cores // sockets` | `test_redfish_csus_single_server.py` |
| B-12 | ESXi 깨진 WWN 검사가 hbas 밖 vmhba 까지 | `collect_network_extended.yml` — 남긴 hbas 만 | `tests/unit/test_esxi_hba_bad_wwn_scope.py` |
| A-1 | ESXi 시리얼 `-NNN` · Superdome Flex 패턴 | `normalize_system.yml` 2곳 · `filter_plugins/serial_normalizer.py` | `tests/unit/test_esxi_serial_npar.py` · `test_csus_partition_serial.py` · `test_gather_identity_render.py` |

## 7. 검증 (이 PC Windows Python 3.13.15 · WSL ansible-core 2.20.7)

| 구분 | 결과 |
|---|---|
| 통합 `tests/integration -m "not live"` | 366 passed, 6 skipped, 1 deselected (신규 `test_redfish_csus_single_server_render.py` 포함) |
| Redfish 관련 단위 선택 실행(`-k redfish or csus or network_summary or power_summary …`) | 1788 passed, 4 skipped |
| OS 신규 3파일 · ESXi 신규 6파일 · 범위 감사 3파일 | 39 passed · 77 passed · 24 passed |
| `ansible-playbook --syntax-check` 3채널 (WSL) | os · esxi · redfish 통과 |
| 정적 검사 | `verify_vendor_boundary.py` 통과(Jinja 주석의 벤더 이름 2건을 고친 뒤) · `verify_harness_consistency.py` 통과 · `check_project_map_drift.py` 일치 · `output_schema_drift_check.py` 통과(fd_paths 206) · `validate_field_dictionary.py` PASS |
| golden · 예산 | `real_hpe_csus3200` 재캡처(미러 01): `system.part_number` null → `R9N70A`, `firmware` 2 → 6, 요청 134 → 141(`request_budget.json` `path_set_delta.added` 7건 + `added_reason`), `meta.json` `firmware_inventory_scope: complex_only`. Dell/HPE/Lenovo 녹화본 골든 · 예산 불변 |
| 전체 pytest(unit · e2e · regression) | TEST_HISTORY 2026-10-19 (두 번째 절) |

## 8. 실장비에서만 확인 가능한 것 (미검증)

- CSUS: 사이트 두 장비의 "디스크 ↔ hbas" 증상(체크리스트로 사용자 확인) · A-5/A-8/A-10 이 실제로 발동하는 응답 · 2섀시 이상 구성(A-11) · Superdome Flex 의 시리얼 패턴 · `processor_summary_logical_count` · `firmware_inventory_scope`(CSUS 와 같다고 본 사용자 지시).
- OS/ESXi: B-1~B-12 는 합성 입력 시험까지. Jenkins main Job 매트릭스(S1~S4 · E2E-D · E2E-E)로 ESXi summary 의 `speed_mbps null` 그룹 · `protocol` 채움 · Linux VLAN 제외가 실호스트에서 기대대로 나오는지 확인한 뒤 승격.
