# 73건 처분표 — Redfish 2차 Mock 11대 구현 Round (지시서 2, 2026-10-27)

- 대상: `tests/evidence/2026-10-26-redfish-mock2-audit/ISSUES.md` 의 73건(HIGH 2 · MED 19 · LOW 51 · 관찰 1 — 2026-10-27 addendum 07 의 `03-storage-004` 포함). ISSUES.md 원문은 보존했고 머리말에 이 표 링크만 더했다.
- 처분 어휘(Plan §6): `FIXED` 코드 변경 + 테스트 + Tier 1 diff · `DOC_CORRECTED` 문서/사전/ADR 기록만 · `VALIDATED_EXISTING` 현 동작이 맞음을 테스트로 고정 · `OBSERVATION_ONLY` 변경 제안 없음(계약 밖·결정 없음) · `MOCK_LIMITATION` 재생으로 확정 불가 · `HOLD` 사용자 결정 필요.
- 집계(1차 처분 기준): **FIXED 43 · DOC_CORRECTED 19 · OBSERVATION_ONLY 11** = 73. 병기: MOCK_LIMITATION 2(03-storage-004 포트 단위 판별 · 06-bmc-001 실장비 복구 경로), VALIDATED_EXISTING 1(04-firmware-001 CSUS `other` 유지), **HOLD 3**(03-storage-001 (b) controllers 보강 — 사용자 결정 · 05-thermal-003 (b) Sensor 보충 미구현 · 03-network-002 잔여 2 NIC — 뒤의 둘은 2026-10-28 독립 검증 정정으로 병기). 그 밖 HOLD 0.
- **2026-10-28 정정**(독립 검증 F-01~F-09 · 부록 A, 브랜치 `fix/redfish-mock2-review-20261028`): 바뀐 행의 이전 → 새 문구는 맨 아래 '2026-10-28 정정' 표. 최상위 처분 수는 그대로다.
- 커밋(브랜치 `fix/redfish-mock2-20261027`, 분기 `b8985826`): WP1 `1ca320d0`~`541c4902` · WP2 `6b3dae27`/`11d3c633`/`6fe95536`/`8da7b77a` · WP3 `bfb82574`/`b06dc5d6`/`85176324`/`ee39da3e` · WP4 `661b0f0a`/`943ea83e`/`3812a372` · WP5 `8041d012`/`2fa1622c`/`b90d214c`/`2f0dc047`/`27e7d878` · WP6 `847d6279`/`f3d1ed0b`/`c4fc8fb8`/`c8a5b538` · WP7 `dc76863d`/`febee5c7`/`17a7ad35` · WP8+WP9 `e650cb47`/`49e0608a`/`6429ebe6` · WP10 `d9991dd4`/`d415af76`/`5536c010` · WP11 `9ecdf22a`/`1d442b86`/`3e12d5f0` · FIX 5 `a1e9c2f6`/`e1ee7bb8` · WP12(이 문서 포함)는 마지막 커밋. 근거 열의 evidence 는 이 디렉터리의 `NN-*.md`.

## C1 — Lenovo XCC3 adapter 재선택 (WP2)

| ID | 심각도 | 처분 | 근거 |
|---|---|---|---|
| 01-adapter-001 | HIGH | **FIXED** | opt-in `match.bmc_model_patterns`(facts `bmc_model` = `Manager.Model`) + `lenovo_xcc3.yml` firmware 토큰 제거 — 5 label `meta.adapter_id = redfish_lenovo_xcc3`, 13 label 바이트 동일, 31 adapter × 기존 facts 점수 동일(`02-adapter-scores-{before,after}.json` 992셀 중 5 변화 = Lenovo 5). `tests/unit/test_adapter_bmc_model_patterns.py`. evidence 02 |
| 01-adapter-011 | LOW | **DOC_CORRECTED** (+ 코드 주석) | adapter origin 주석 · `VENDOR_ADAPTERS.md` · `docs/develop/03-adapter-system.md` "1차 선택만 검증 / 재선택은 bmc_model_patterns(2026-10-27)". evidence 02 |

## C2 — 전원 Off 호스트 placeholder (WP3)

| ID | 심각도 | 처분 | 근거 |
|---|---|---|---|
| 02-memory-001 | MED | **FIXED** | `Status` 없음 ∧ `CapacityMiB` 0 ∧ 식별자 전부 빈 슬롯 제외 + notice — dl380_gen12_03 slots 32 → 16 (G-04). `tests/unit/test_redfish_power_off_host.py`. evidence 03 |
| 03-storage-001 | MED | **FIXED**(a — 전원 Off 신호 notice) + **HOLD**(b — controllers 보강) | (a) PowerState Off 관측 notice 1건(2026-10-28 F-03: 문구에 '네트워크' 추가 — 종전 문구는 network 를 빼 network 칸 근거가 되지 못했다), placeholder 미생성(Storage 0건은 그대로 0). (b) PCIeFunctions 로 controllers 를 보강하는 일은 사용자 결정 항목(Plan §6) — HOLD(2026-10-28 정정 전에는 유일한 HOLD). evidence 03 |
| 05-power-001 | MED | **FIXED** | Absent PSU 의 `power_capacity_w` 0 · `firmware_version "0.00"` → null(항목은 state Absent 로 남김), legacy 합 폴백도 Absent 제외 (G-05). evidence 03 |
| 05-thermal-002 | MED | **FIXED** | `Status.State != Enabled` 센서·팬 reading null(상태 보존) — dl380_gen12_03 temps 42 · fans 6 (G-06). evidence 03 |
| 04-firmware-009 | LOW | **OBSERVATION_ONLY** | 전원 Off 스냅샷의 `updateable` 은 raw 그대로 — 변경 없음. evidence 03/04 |

## C3 — CPU 스레드 (WP9, FIX 1)

| ID | 심각도 | 처분 | 근거 |
|---|---|---|---|
| 02-cpu-001 | HIGH(추정) | **FIXED**(정책 제외) | 사용자 FIX 1: Redfish `data.cpu.logical_threads` 키 제거(top + `multi_node.partitions[].cpu`), HT 추정 금지, OS/ESXi 불변(baseline 5종 키 존재 단언). 유일한 비-Additive 변경. 모듈 raw `cpu_summary.logical_processor_count` 는 유지(§9). evidence 09, G-16/17 |
| 02-cpu-002 | MED | **DOC_CORRECTED** | ADR-2026-10-19 A-2 전제(RMC LPC = 코어) 가 1.77 에서 불성립 — ADR append + EXTERNAL_CONTRACTS 행; 코드는 더 이상 그 값을 소비하지 않음. 2026-10-28 F-05: 1.77.30 LPC 는 HT 설정과 무관하게 ΣTotalThreads(csus3200_02 `HThread Disabled` 인데 224 = ΣTotalThreads = 2 × ΣTotalCores 112) — 종전 괄호 'HT 비활성이면 코어 수' 정정. evidence 09 |
| 02-cpu-006 | LOW | **OBSERVATION_ONLY** | `cores_physical` = `TotalCores` 합. 활성 코어 신호가 있는 11대(`TotalEnabledCores` 6 — Lenovo 5 · Dell 1, `Oem.Hpe.CoresEnabled` 5 — DL380)는 `TotalCores` 와 같고 CSUS 7대는 신호가 없다(2026-10-28 F-06 정정 — 종전 '18대 `TotalEnabledCores` 와 같음'). 장착→활성 의미 변경은 FIX 1 범위 밖. evidence 09 |

## C4 — Lenovo XCC3 응답 모양 (WP5)

| ID | 심각도 | 처분 | 근거 |
|---|---|---|---|
| 03-network-001 | MED | **FIXED** | normalize 층에서 FC/IB 포트 주소·8옥텟 MAC 을 `interfaces[]`/`summary` 에서 제외 + notice, 모듈 raw 보존; INV-5 추가(전 fixture + baseline). Lenovo 2 label(sr650_v4_02 interfaces 9→5 · _03 15→11 — 2026-10-28 정정, 종전 'Lenovo 5 label 9→5 등'). evidence 05, G-09~12 |
| 04-firmware-006 | MED | **FIXED** | `Status.State Disabled` ∧ `Version` 없음 → 제외 + notice(버전 있으면 종전 `pending: true`) — Lenovo firmware 26·28·30·40·30 → 24·24·26·36·26. evidence 05 |
| 01-hardware-005 | LOW | **FIXED**(2키 폴백) + **OBSERVATION_ONLY**(나머지) | `hardware.oem.machine_type ← System.SubModel`('7DGD') · `led_indicator ← System.IndicatorLED`('Off'); 원천이 없는 나머지 키는 null 유지(키 삭제는 Additive 위반). evidence 05 |
| 02-memory-003 | LOW | **FIXED** | locator `DeviceLocator → Location.PartLocation.ServiceLabel → str(Slot)` — `"23"` → `"DIMM 23"`. evidence 05, G-09~13 |
| 03-network-003 | LOW | **DOC_CORRECTED** | XCC 3 호스트 NIC `SpeedMbps` 는 Gbps×1024(25600), `ports[]` 는 ×1000(25000/32000) — 두 원천 모두 원문 보존, 비교는 포트 값; iDRAC 9 는 같고 iLO 7 · RMC 는 호스트 NIC 속도 자체가 없음(03-fields 6.4 (4), WP12). 2026-10-28 F-07: 종전 예시 `32768` 은 03-network-001 로 interfaces 에서 빠진 8옥텟 FC 항목 값이라 출력에 없다 — 03-fields 예시를 sr650_v4_01 `NIC2` 25600 ↔ 같은 MAC 포트 25000 으로 교체 |
| 03-network-005 | LOW | **OBSERVATION_ONLY** | `ToManager`(Host Interface USB NIC) 제외는 모듈이 `Links.HostInterface` 를 내지 않아 키 추가 없이는 불가 — 변경 0, 문서만. evidence 05 |
| 04-firmware-010 | LOW | **OBSERVATION_ONLY** | Lenovo 버전 표기 2종 — 원문 보존. evidence 04 |
| 05-power-003 | LOW | **FIXED** | PSU 문자열 `_strip_or_none`(패딩 공백 제거, 1차 golden 중립). evidence 05 |

## C5 — CSUS 섀시·multi_node·baseline (WP7 · FIX 3/5/6 · 결정 11 A안)

| ID | 심각도 | 처분 | 근거 |
|---|---|---|---|
| 01-multi_node-003 | MED | **FIXED** | FIX 5(WP11 뒤): `schema/baseline_v1/hpe_csus_3200_baseline.json` 을 2차 Mock csus3200_01 Tier 1 실 봉투로 교체(재생 주소 2곳만 BMC IP, `baseline_origin` 실측 표기), registry `hpe_csus_3200_redfish`, 가드 테스트 실 구조(1/1/3)로 재작성, 03-fields §9 예시 교체. 커밋 `a1e9c2f6`/`e1ee7bb8`, G-25. evidence 07 FIX 5 절 |
| 02-memory-002 | MED | **DOC_CORRECTED** | FIX 3: CSUS DIMM `OperatingSpeedMhz` 3200 원값 보존, 벤더별 의미(RMC I/O 클럭 · iLO/XCC/iDRAC MT/s)를 03-fields 6.2 · EXTERNAL_CONTRACTS 에 명시. evidence 07 |
| 03-storage-004 | MED | **FIXED**(A안 — 카드 조건 참고 notice) + **MOCK_LIMITATION**(포트 단위 판별) | 값 규칙 불변(Port `LinkStatus` 있으면 사용, 없으면 `down`), 3중 조건(FC 카드 · 어댑터 Links.PCIeDevices 1건 · adapter 선언 등록부 `H3Alert`)에서만 기존 notice 에 카드 조건 LinkUp(Timestamp, 카드 단위) 기재, 요청/필드 추가 0, Iel 미사용, RAID/NIC/`PcieLinkTrainingOk`/미선언/LinkStatus 보유 음성 7종. 포트 단위 링크는 RMC 가 주지 않아 재생으로 확정 불가. evidence 07 |
| 01-multi_node-006 | LOW | **FIXED** | 섀시 본문 navigation property 로 Power/Thermal GET gating — CSUS 7 label 요청 -14(404 0), 비-CSUS 요청 불변. evidence 07, G-15 |
| 01-multi_node-007 | LOW | **FIXED** | FIX 6: `composition.resource_blocks[].processor_count/memory_count` 원천 배열 없으면 null(0 날조 금지), 사전 등재. evidence 07 |
| 01-system-008 | LOW | **DOC_CORRECTED** | FIX 4: `sections.system = not_supported` 유지 + `data.system.hostname/fqdn` 발행 사유 각주(03-fields §3 · 6.x · 사전 help), HostOS 승격 안 함. evidence 08 |
| 01-system-009 | LOW | **DOC_CORRECTED** | ADR-2026-10-15 재검증 기록(`hostname_source=system` 의미) — 03-fields · ADR append. evidence 08 |
| 02-cpu-005 | LOW | **OBSERVATION_ONLY** | `partitions[].cpu` 에 `turbo_max_mhz` 없음 — 2026-10-19 사용자 결정 범위, 변경 0. evidence 09 |
| 04-bios-003 | LOW | **OBSERVATION_ONLY** | CSUS `Bios/Settings` 보류 차이 2건 + 주석 키 — 계약 밖(Plan WP12 명시). |
| 04-firmware-007 | LOW | **DOC_CORRECTED** | 사전 `firmware[].updateable` `boolean|null`. evidence 08 |
| 04-firmware-011 | LOW | **DOC_CORRECTED** | CSUS `hardware.bios_version == bmc.firmware_version`(complex 번들) · bios/bmc 항목 없음 각주(03-fields 6.9). evidence 08 |
| 05-power-004 | LOW | **FIXED** | ≡ 01-multi_node-006(링크 없는 경로 요청 0 · 404 재요청 0). evidence 07 |
| 05-power-007 | LOW | **FIXED** | 소비전력 폴백 순서 Telemetry → PSU 출력 합 → 입력 합 + 주석 정정(18 label 값 불변). evidence 06 |

## C6 — 계약·사전 drift (WP8, FIX 2/4)

| ID | 심각도 | 처분 | 근거 |
|---|---|---|---|
| 01-hardware-002 | MED | **FIXED**(Rollup 폴백) + **DOC_CORRECTED** | `hardware.health` = `Status.Health`(null 일 때만 `HealthRollup`), 18 label 값 불변, 문서 "PSU 1대 fault → Critical" 삭제. `tests/unit/test_redfish_hardware_health_fallback.py`. evidence 08 |
| 02-cpu-003 | MED | **FIXED** | FIX 2: `cpu.manufacturer` 발행(내장 Jinja, `Intel(R) Corporation → Intel` · `Advanced Micro Devices, Inc. → AMD`), groups 동일 표, 모듈 raw 보존. evidence 08 |
| 02-cpu-004 | LOW | **DOC_CORRECTED** | `cpu.architecture` 채널별 어휘(Redfish `x86` vs OS/ESXi `x86_64`) 사전 help — 표기 통일은 결정 항목. evidence 08 |
| 02-cpu-007 | LOW | **DOC_CORRECTED** | 사전 `cpu.sockets` · `cpu.model` · `cpu.logical_threads`(channel os/esxi) 등재. evidence 08 |
| 02-memory-005 | LOW | **OBSERVATION_ONLY** | `memory.summary.groups` part_number 전체 문자열 묶음 — 6.8 1줄 기재. evidence 08 |
| 02-memory-006 | 관찰 | **OBSERVATION_ONLY** | `total_basis` 상수 `physical_installed` — 6.2 기재(실측 재확인 2026-10-27). evidence 08 |
| 03-storage-002 | LOW | **DOC_CORRECTED** | 사전 `storage.controllers[].driver` channel 에서 redfish 제거. evidence 08 |
| 04-bios-002 | LOW | **OBSERVATION_ONLY** | `bios.current.attributes` 식별·네트워크 정보 그대로(계약대로) — 6.8 1줄. evidence 08 |
| 04-firmware-008 | LOW | **OBSERVATION_ONLY** | Dell first-seen dedup 접두사 혼재는 그대로(출력 불변); WP4 의 `firmware_links` 가 `Installed-/Current-` 키 쌍을 대조해 혼재를 흡수(테스트 고정). evidence 04/08 |
| 04-firmware-012 | LOW | **DOC_CORRECTED** | 03-fields 6.9 `data.firmware` 절 신설 + category help 정정. 2026-10-28 F-09: UEFI 예시 값(`"version": "IHX414J 1.22"` · `"component": "UEFI-IHX4-10"`)은 18 미러 · 봉투 어디에도 없었다(BMC 값 계열 — 1차 SR650 V4 Manager `FirmwareVersion` `IHX414J 1.22 20250402` · BMC SoftwareId `BMC-IHX4-10`) — sr650_v4_02 봉투 2항목 그대로(키 순서 포함)로 교체. evidence 08 |
| 01-correlation-010 | LOW | **DOC_CORRECTED** | `correlation.bmc_ip` 정의("BMC 가 보고한 관리 NIC IPv4 — 대상 IP 와 다를 수 있음") 사전·03-fields. 2026-10-28 F-04: 사전 · 03-fields 의 'IPv4 를 가진 첫 NIC' 를 코드대로 `data.bmc.ip`(① 대상 주소 NIC → ② HostInterface 아님 · Enabled → ③ IPv4 를 가진 첫 NIC)로, `host_ip` 는 요청 대상 주소(Manager NIC 에 없으면 bmc_ip 와 다름)로 정정. evidence 08 |
| 05-power-005 | LOW | **DOC_CORRECTED** | `power_control.power_capacity_watts` · 소비전력 정의(벤더·경로별 의미) 사전·6.5. 2026-10-28 F-08: 원천 정정 — legacy `PowerControl[0].PowerCapacityWatts` → 없으면 PSU 용량 합(Absent 제외), PowerSubsystem 경로도 PSU 용량 합, `CapacityWatts` 는 읽지 않음; iLO 7 'AC 입력 잃은 PSU 제외' 인과 삭제(벤더 정의 미확인). evidence 08 |
| 05-power-006 | LOW | **DOC_CORRECTED** | power/thermal 하위 키 등재(사전 +53). evidence 08 |
| 05-thermal-005 | LOW | **DOC_CORRECTED** | 문서·주석 drift 3건 정정. evidence 08 |

## C7 — 테스트 격리 (WP1)

| ID | 심각도 | 처분 | 근거 |
|---|---|---|---|
| 04-test-001 | MED | **FIXED** | `installed_fakes` context manager(seam 복원) + 루트 `tests/conftest.py` 누출 가드 — `tests/unit` 19 failed → 0, 한 프로세스 36 → 0, 쌍 실행 bisect 8/8. 커밋 `f3df7ac9`. evidence 00/01 |
| 06-bmc-008 | LOW | **FIXED** | ≡ 04-test-001(`_get`/`_get_noauth` 영구 교체 제거). evidence 00 |

## C8 — 기존 필드 보강 (WP10, 요청 추가 0)

| ID | 심각도 | 처분 | 근거 |
|---|---|---|---|
| 01-hardware-004 | LOW | **FIXED** | `hardware.bios_date` ← bios 링크(`Bios.Links.ActiveSoftwareImage`/`RelatedItem /Bios`)가 가리키는 FirmwareInventory `ReleaseDate`(System·OEM 날짜 없을 때만, 0000 제외) + notice — Lenovo 5 label. evidence 10, G-18~23 |
| 02-memory-004 | LOW | **FIXED** | `RankCount` 없을 때 HPE OEM `Label` `<n>Rx<m>` 의 n — CSUS 7 label `rank_count` null → 1(`error_correction` 은 관찰 유지). evidence 10 |
| 03-network-002 | LOW | **FIXED**(부분 — 2026-10-28 규칙 정정) + **HOLD**(잔여 2 NIC) | 2026-10-28 F-01: 종전 조건 `link_status unknown ∧ speed null` 은 `SpeedMbps` 가 있는 SR650 V4 NIC 을 놓쳤고(보충은 DL380 3대 16건뿐), 같은 MAC 포트가 2개면 앞 포트를 덮었다 → NIC 링크가 unknown 이면 같은 MAC 포트들의 link 가 하나로 일치할 때만 보충(speed 는 NIC 값이 null 일 때만, NIC 값은 덮지 않음, `db606f1c`). 효과(새 Tier 1): SR650 V4 20건(up 14 · down 6 — sr650_v4_01 4; sr650_v4_02 3; sr650_v4_03 10; sr650_v4_04 3) + DL380 3대 16건(종전과 같음). **HOLD**: sr650_v4_02 `NIC6` · _04 `NIC4`(본딩 영구 주소 NIC — 포트 출력 `associated_address` 에 그 MAC 이 없음)는 unknown 유지 — 해결하려면 모듈 출력 변경(별도 승인). evidence 05 · `../2026-10-28-redfish-mock2-review-fix/01-f01-nic-link-fill.md` |
| 03-network-004 | LOW | **FIXED** | `CurrentLinkSpeedMbps 0` → null(ports 전용) — r1_DELL_R740 10건. evidence 10 |
| 03-network-006 | LOW | **FIXED**(합성·DMTF mockup 검증) | `IPv6Addresses` → `addresses[]` family ipv6 — 실측 18대는 전부 비어 있음. evidence 10 |
| 03-network-007 | LOW | **FIXED** | `interfaces[].mtu` ← NDF `Ethernet.MTUSize`(MAC join, null 일 때만) — XCC 3 V4 · iLO 7 일부 1500; 사전 등재. evidence 10 |
| 03-storage-003 | LOW | **FIXED** | `physical_disks[].wwn` ← `Drive.Identifiers` NAA/EUI(`naa.<hex>` 소문자), 사전 channel redfish 추가 — iLO 7 Gen12 · iDRAC 값, XCC 3 · RMC null. evidence 10 |
| 04-bios-001 | LOW | **FIXED** | ≡ 01-hardware-004. evidence 10 |

## C9 — firmware category (WP4, FIX 7)

| ID | 심각도 | 처분 | 근거 |
|---|---|---|---|
| 04-firmware-001 | MED | **FIXED**(Lenovo `UEFI` → bios, 구조 근거) + **VALIDATED_EXISTING**(CSUS `Partition0_FW` other 유지) | `firmware_links`(ActiveSoftwareImage/RelatedItem → Bios) 1순위, CSUS 번들은 구조 링크 없어 `other`(사용자 2차 검토). `tests/unit/test_firmware_category_structure.py`(2026-10-28 정정 — 종전 표기 `test_firmware_category.py` 는 범위 diff 0) 14값 긍정·부정 전수 + 18 label 매트릭스(04-firmware-category-matrix.md). evidence 04 |
| 04-firmware-002 | MED | **FIXED** | HPE RAID 컨트롤러 `controller_model` 조인 → storage_controller, `Embedded Video Controller` → other. evidence 04 |
| 04-firmware-003 | MED | **FIXED** | 사슬 순서 disk > backplane > raid > drive — Lenovo PSoC → backplane. evidence 04 |
| 04-firmware-004 | LOW | **FIXED** | FIX 7: FC HBA 토큰 → `other`(enum 불변, 새 값 금지) — Dell QLogic 4건 포함 벤더 일관. evidence 04 |
| 04-firmware-005 | LOW | **FIXED** | programmable logic/FPGA → cpld, raid 가 nvme 보다 먼저. evidence 04 |

## C10 — 전원·온도 의미 (WP6)

| ID | 심각도 | 처분 | 근거 |
|---|---|---|---|
| 05-power-002 | MED | **FIXED**(관측 notice) | PSU 입력 0 W/0 V 관측 notice(인과 해석 없음, `psu_active` 의미 불변) — SR650 V4 4 · DL380 3 label. evidence 06 |
| 05-thermal-001 | MED | **FIXED** | WP3 reading null + WP6 `Absent` 센서·팬 제외 + 건수 notice — DL380 temps 56/44/54 → 49/36/46, 1차 52 → 43(G-14). evidence 06 |
| 05-thermal-003 | LOW | **FIXED**((a)(c) 합성 검증) + **HOLD**((b) — 2026-10-28) | (a) ThermalSubsystem 경로 `name` ← `DataSourceUri` 세그먼트, (c) `SpeedPercent.SpeedRPM` → RPM — 18 label 미발동. (b) `DataSourceUri` → Sensor GET 으로 health/state/upper_critical 보충은 구현하지 않았다(2026-10-28 F-02 — 종전 처분 · evidence 에 잔여 표기 없음). 재개 조건: Sensor 에 Status/Thresholds 값이 있는 실장비 캡처 + 요청 예산 사용자 승인(CSUS 7대 +377 GET, 미러 Sensor 377개 전부 Status · Thresholds 값 없음). evidence 06 |
| 05-thermal-004 | LOW | **OBSERVATION_ONLY** | 음수 "온도"(Lenovo `CPUn DTS TMargin` · CSUS `P*_THROT_OFFSET`) 값 보존, 6.7 각주. evidence 06 |

## C11 — bmc · diagnosis (WP11, FIX 10)

| ID | 심각도 | 처분 | 근거 |
|---|---|---|---|
| 06-bmc-001 | MED | **FIXED** + **MOCK_LIMITATION** | 복구 Family 세대 = `Manager.Model` 1순위(hint 는 모델 없을 때만) — reconcile 은 Tier 1 미진입(표준 계정 1차 인증 성공), 실장비 401 → 복구 경로는 재생으로 확정 불가. `tests/unit/test_redfish_bmc_diagnosis_wp11.py`. evidence 11 |
| 06-bmc-002 | LOW | **FIXED** | discovery `writable` ← `@Redfish.WriteableProperties`, repair PATCH 는 선언 밖 속성 제외(`write_demoted_by_device`); RMC 실측 shape 로 fixture 테스트. evidence 11 |
| 06-bmc-003 | LOW | **FIXED** | iLO `Oem.Hpe.Links.DateTimeService` 1회 GET(TimeZoneName 없을 때만) → `bmc.timezone` `JST-9:00` ×4 · `GMT-0`(요청 +1, DL380 5 label). G-24. evidence 11 |
| 06-bmc-004 | LOW | **DOC_CORRECTED** | `bmc.datetime` 표기(iLO UTC Z + offset 분리 / XCC·RMC·iDRAC 오프셋 포함) — WP8 문구의 "XCC 3 = Z" 오류를 WP11 실측으로 정정. evidence 11 |
| 06-bmc-005 | LOW | **FIXED**(값 불변) | NIC 선택 ① 대상 IP → ② 비-HostInterface·활성 → ③ 첫 NIC — 18 label 값 불변, 순서 뒤집기·USB 가상 NIC 합성 테스트. 2026-10-28 F-04: 사전 `correlation.bmc_ip` · `bmc.ip` ③ 문구와 함수 주석을 이 순서로 정정(③ = IPv4 를 가진 첫 NIC). evidence 11 |
| 06-bmc-006 | LOW | **FIXED** | layout 없어도 `ManagerType RackManager/EnclosureManager` 면 Manager `Id`/타입 라벨 — plain 재생 CSUS `iLO` → `RMC`, 18 label 불변. evidence 11 |
| 06-bmc-007 | LOW | **DOC_CORRECTED** | `diagnosis.details` Redfish 키 · `account_service {}` 의미(WP8) + `write_demoted_by_device`(WP11). evidence 08/11 |
| 06-bmc-009 | LOW | **DOC_CORRECTED** | 사전 `bmc.uuid` "ServiceIdentification 아님" 정정(WP8). evidence 08 |
| 06-bmc-010 | LOW | **FIXED** | 익명(빈 자격) 수집 성공은 `auth_success` null(site.yml); 시험은 `site.yml` · `collect_standard.yml` 의 배선 문자열 존재 확인뿐이다(렌더 · 재생 없음 — 2026-10-28 정정, 종전 '합성 배선 테스트'); 18 label true 불변. evidence 11 |

## 사용자 FIX 대응

| FIX | 처분 | 근거 |
|---|---|---|
| 1 `logical_threads` 제거 | FIXED | 02-cpu-001 (WP9) |
| 2 `cpu.manufacturer` | FIXED | 02-cpu-003 (WP8) |
| 3 CSUS DIMM 속도 원값 | DOC_CORRECTED | 02-memory-002 (WP7) |
| 4 `sections.system` 유지 | DOC_CORRECTED | 01-system-008 (WP8) |
| 5 CSUS 실측 baseline | FIXED | 01-multi_node-003 (WP11 뒤) |
| 6 composition null | FIXED | 01-multi_node-007 (WP7) |
| 7 category enum 확장 금지 | FIXED | 04-firmware-004 (WP4) |
| 8 Replay 자산 편입 | FIXED | `tests/redfish-probe/mirror_replay/` + fixture 11세트 (WP1) |
| 9 검증된 golden 만 정정 | FIXED | `golden-changes.md` G-01~G-25 |
| 10 `data.users` 불변 | VALIDATED_EXISTING | `test_redfish_users_section_is_untouched` (WP11) |
| 11 단일 브랜치·승인 게이트 | 준수 | `fix/redfish-mock2-20261027` 만, main/production 미접촉, 독립 검증 세션 요청 (WP12) |

## 2026-10-28 정정 (독립 검증 F-01~F-09 · 부록 A — 브랜치 `fix/redfish-mock2-review-20261028`)

독립 검증(`f92ebe6a` 대상, 판정 '완료 선언 안 함')의 FAIL 10건 중 처분표에 걸린 9건과 부록 A 의 수치 · 표기 오류를 고쳤다(F-10 은 하네스 지문 — 73건 밖).
최상위 처분 수(FIXED 43 · DOC_CORRECTED 19 · OBSERVATION_ONLY 11)는 그대로이고 병기 HOLD 가 1 → 3 이 됐다. 근거 · 재현: `../2026-10-28-redfish-mock2-review-fix/REVIEW_FIX_HANDOFF.md`.

| ID | 이전 | 정정 | 근거 |
|---|---|---|---|
| `03-network-002` | FIXED | FIXED(부분) + HOLD(잔여 2 NIC) | F-01 — 코드 `db606f1c`, 새 Tier 1 SR650 V4 20건 |
| `05-thermal-003` | FIXED(합성 검증) | FIXED (a)(c) + HOLD (b) | F-02 — 코드 변경 0, 미러 Sensor 377개 값 없음 |
| `03-storage-001` | (a) notice '저장/메모리/전원/온도' | (a) notice 에 '네트워크' 추가 | F-03 — 코드 `ac368a4b`, 사용자 결정 Q2 |
| `01-correlation-010` · `06-bmc-005` | 사전 'IPv4 를 가진 첫 NIC' | `data.bmc.ip`(①②③) · host_ip = 요청 대상 주소 | F-04 — 문서 `0e3bcbb3` |
| `02-cpu-002` | 'HT 비활성이면 코어 수' | HT 설정과 무관하게 ΣTotalThreads | F-05 — 미러 csus3200_02 |
| `02-cpu-006` | '18대 `TotalEnabledCores` 와 같음' | 신호 11대(6 + 5)만 같음 · CSUS 7 신호 없음 | F-06 — 미러 18대 재집계 |
| `03-network-003` | 예시 32 G = `32768` | 25600 ↔ 25000 예시 | F-07 — 문서 `0e3bcbb3` |
| `05-power-005` | 원천 `PowerSubsystem.CapacityWatts` | legacy PowerControl → PSU 용량 합 | F-08 — 문서 `0e3bcbb3` |
| `04-firmware-012` | UEFI 예시 값이 미러 · 봉투에 없음(BMC SoftwareId 계열 혼입) | sr650_v4_02 봉투 2항목 | F-09 — 문서 `0e3bcbb3` |
| `03-network-001` | 'Lenovo 5 label 9→5 등' | 'Lenovo 2 label(9→5 · 15→11)' | 부록 A |
| `04-firmware-001` | 근거 시험 `test_firmware_category.py` | `test_firmware_category_structure.py` | 부록 A |
| `06-bmc-010` | '합성 배선 테스트' | 배선 문자열 존재 시험(렌더 · 재생 없음) | 부록 A |
| `03-storage-004` | (행 변경 없음) | evidence 07 의 카드 조건 59 → 49 | 부록 A — 미러 원문 재집계 |
