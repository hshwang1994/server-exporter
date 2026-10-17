# FIELD_USAGE_MATRIX — field × baseline 사용 실태 매트릭스

> 작성: 2026-05-11 / 측정 대상 #13 (rule 28 R1 — 신규)
> 정본: 본 매트릭스. 측정 스크립트: `scripts/ai/measure_field_usage_matrix.py` (Phase 1 도입 예정)
> TTL: 14일 / 무효화 trigger: `schema/field_dictionary.yml` 변경 / `schema/baseline_v1/*.json` 변경 / `adapters/*/*.yml` capabilities 변경

## 목적

`schema/field_dictionary.yml` 83 entries (Must 39 + Nice 38 + Skip 6) 각 필드가 9 baseline (실장비 회귀 기준선) 에서 **실제로 어떻게 채워지는가** 를 자동 측정한 매트릭스. 호출자 시스템 / 운영자 / 개발자가 어느 필드가 의미 있게 수집되는지 한눈에 파악. (2026-05-29 measure_field_usage_matrix.py 재생성)

본 매트릭스는 다음 3 분류 cycle 의 input:
1. **정말 수집 불가** (외부 시스템 spec 미제공) → `field_dictionary.yml` channel 배열 축소
2. **서버 미지원** (일부 vendor / 펌웨어 / 환경) → channel 유지 + `help_ko` 명시
3. **코드 버그** (외부 시스템 제공인데 코드 잘못) → 즉시 fix + 회귀

## 4 상태 (cell 값)

각 cell (field × baseline) 은 다음 4 상태 중 하나:

| 상태 | 의미 | 판정 근거 |
|---|---|---|
| `present` | 값 존재 (non-null) | baseline JSON leaf 가 non-null / non-empty |
| `null` | 명시적 null | baseline JSON leaf 가 `null` |
| `empty` | 빈 컨테이너 | baseline JSON leaf 가 `[]` 또는 `{}` (배열/객체 타입 한정) |
| `not_supported` | 섹션 자체 미지원 | baseline `sections.{section}=not_supported` |
| `missing` | key 자체 부재 | baseline JSON 에 path 자체가 없음 (channel 미지원) |

**판정 우선순위**: `not_supported > missing > empty > null > present`

## 분류 도출 룰

baseline 의 같은 `target_type` (channel) 그룹 안에서 cell 패턴 → 분류 도출:

| 패턴 | 분류 | 조치 |
|---|---|---|
| channel 의 모든 baseline 이 `null` / `empty` / `missing` | 1 (수집 불가) | `field_dictionary.yml` channel 배열에서 해당 channel 제거 |
| channel 의 일부 baseline `present`, 일부 `null` | 2 (서버 미지원) | channel 유지 + `help_ko` 에 채널별 동작 명시 |
| 한 baseline 만 `null` 인데 다른 baseline 은 `present` + 외부 시스템 spec 상 제공 | 3 (코드 버그) | 즉시 fix + tests/fixtures + tests/baseline 회귀 |
| `not_supported` | (분류 외) | adapter capabilities 명시. 매트릭스에서 N/A |

## Baseline 8 + Channel 매핑

| baseline 파일 | target_type | vendor | sections OK | 비고 |
|---|---|---|---|---|
| `dell_baseline.json` | redfish | dell | 8 | iDRAC9 |
| `hpe_baseline.json` | redfish | hpe | 8 | iLO6 |
| `lenovo_baseline.json` | redfish | lenovo | 8 | XCC |
| `cisco_baseline.json` | redfish | cisco | 8 | CIMC |
| `esxi_baseline.json` | esxi | cisco | 6 | ESXi 8.x on Cisco UCS |
| `rhel810_raw_fallback_baseline.json` | os | (null) | 6 | RHEL 8.10 Python 3.6 → raw fallback |
| `ubuntu_baseline.json` | os | (null) | 6 | Ubuntu LTS |
| `windows_baseline.json` | os | (null) | 6 | Windows Server (VM) |

**Channel 별 baseline 수**:
- Redfish: 4 (dell / hpe / lenovo / cisco) — supermicro 없음 (베어메탈 fixture 미보유)
- OS: 3 (rhel810_raw_fallback / ubuntu / windows)
- ESXi: 1 (esxi)

**알려진 제한** (분류 정확도 영향):
- Redfish supermicro baseline 부재 — supermicro 한정 코드 버그 검출 불가
- Windows / ESXi 가 VM 환경 — 베어메탈 한정 필드 (memory.slots / storage.physical_disks 등) 가 `[]` 로 떨어져도 분류 2 vs 3 모호. 보수적 분류 2 적용 + NEXT_ACTIONS 등재 (rule 50 R2 단계 10)

## Phase 2 사람 검토 결과 (2026-05-11)

자동 매트릭스 분류에 대한 사람 검토. 자동 결과 → 확정 분류 + 조치 매핑.

### Channel 축소 확정 (분류 1 → 본 cycle Phase 3 적용)

| Field | Channel 변경 | 근거 |
|---|---|---|
| `memory.visible_mb` | `[redfish, os, esxi]` → `[os, esxi]` | Redfish spec 미정의. 사용자 핵심 사례. help_ko 에 이미 명시. |
| `memory.installed_mb` | `[redfish, os, esxi]` → `[redfish, os]` | ESXi 는 ansible_memtotal_mb 만, installed_mb 미수집 |
| `storage.infiniband[]` | `[redfish, os, esxi]` → `[]` (또는 모두 유지하고 help 명시) | InfiniBand 환경 부재 — 모든 baseline empty. 보수적: channel 유지 + help_ko "InfiniBand 환경 한정" |
| `storage.hbas[]` | `[redfish, os, esxi]` → `[esxi]` | esxi baseline 만 present (FC HBA 환경 한정) |
| `network.adapters[]` | `[redfish, esxi]` → `[esxi]` | Redfish 4 baseline 모두 missing |
| `network.ports[]` | `[redfish]` → `[]` (또는 help_ko "구현 예정") | Redfish 4 baseline 모두 missing → 보수적: help_ko 갱신 |
| `network.driver_map[]` | `[os]` → `[]` (또는 help_ko "베어메탈 Linux 한정") | OS 3 baseline 모두 missing/empty |
| `system.runtime` | `[os]` → `[esxi]` | DRIFT-B: ESXi baseline 만 present, OS 3 baseline 모두 missing |

### Help_ko 갱신 (분류 2 — channel 유지 + vendor/환경별 동작 명시)

| Field | Channel | help_ko 갱신 내용 |
|---|---|---|
| `vendor` | 유지 | "OS 채널은 hardware 정보 미수집 시 null — 의도된 동작" 강조 |
| `hardware.sku` × redfish | 유지 | "Cisco UCS 는 sku 정의 안 됨 — null 정상" 추가 |
| `hardware.oem` × redfish | 유지 | "Cisco 는 OEM namespace 없음 — empty 정상" 추가 |
| `memory.installed_mb` × os | 유지 | "Ubuntu 는 dmidecode 권한 부족 시 null — 의도된 동작" 추가 |
| `storage.logical_volumes[].*` × redfish | 유지 | "RAID controller 없는 BMC (Lenovo SR670 mock / Cisco CIMC) 는 empty — 정상" |
| `storage.logical_volumes[].boot_volume` × redfish | 유지 | "Dell OEM DellVolume.BootVolumeSource 한정 — 다른 vendor null 정상" |
| `cpu.architecture` × {os, esxi} (현재) | 유지 | (현재 정확) |
| `diagnosis.failure_stage` × 3 channel | 유지 | "**conditional** — status=failed 시만 채워짐. success baseline 에서 null 정상" 강조 |

### 분류 3? 의심 — NEXT_ACTIONS 등재 (본 cycle 외 별도 fix)

| Field × baseline | 의심 사유 | 조치 (cycle 외) |
|---|---|---|
| `meta.duration_ms × cisco_baseline.json` | cisco 의 meta.duration_ms 가 null (started_at/finished_at 있는데 계산 누락) | cisco 실장비 baseline 재캡처 시 갱신 (rule 13 R4 실측 의무) |
| `cpu.summary × rhel810_raw_fallback_baseline.json` | RHEL raw fallback 의 cpu summary 빌더 누락 (ubuntu/windows 는 present) | os-gather/tasks/linux/gather_cpu.yml raw fallback 경로에 summary 빌더 추가 — 별도 cycle |

### 코드 버그 0건 (본 cycle 내 fix 의무 없음)

Phase 2 cycle 안에서 즉시 fix 대상 코드 버그 — **0건 확정**.
분류 3? 자동 식별 1건 (`storage.logical_volumes[].boot_volume × redfish`) 은 Dell OEM 한정 — 의도된 동작.
의심 2건 (`meta.duration_ms × cisco`, `cpu.summary × rhel810`) 은 NEXT_ACTIONS 별도 cycle 등재.

<!-- AUTO-GEN: FIELD_USAGE_MATRIX START -->

> 측정 스크립트 자동 갱신 결과 — 수동 편집 금지. 다음 측정 시 덮어씀.

# Field Usage Matrix — 측정 결과

- field_dictionary entries: 206
- baselines: 10
- 총 cells: 2060

## 4 상태 카운트 (channel × state)

| Channel | present | null | empty | not_supported | missing | total |
|---|---|---|---|---|---|---|
| redfish | 265 | 41 | 38 | 64 | 416 | 824 |
| os | 186 | 32 | 137 | 114 | 149 | 618 |
| esxi | 54 | 9 | 41 | 28 | 74 | 206 |

## 분류 1 후보 (수집 불가 — channel 제거): 159

- `errors[]` × redfish
- `errors[]` × os
- `errors[]` × esxi
- `errors[].section` × redfish
- `errors[].section` × os
- `errors[].section` × esxi
- `errors[].message` × redfish
- `errors[].message` × os
- `errors[].message` × esxi
- `diagnosis.details.notices` × redfish
- `errors[].detail` × redfish
- `errors[].detail` × os
- `errors[].detail` × esxi
- `hardware.bios_date` × redfish
- `hardware.asset_tag` × redfish
- `hardware.system_type` × redfish
- `hardware.part_number` × redfish
- `hardware.last_reset_time` × redfish
- `hardware.boot_progress` × redfish
- `hardware.tpm` × redfish
- `memory.slots[].capacity_mb` × redfish
- `memory.slots[].speed_mhz` × os
- `memory.slots[].base_module_type` × redfish
- `memory.slots[].rank_count` × redfish
- `memory.slots[].data_width_bits` × redfish
- `memory.slots[].bus_width_bits` × redfish
- `memory.slots[].error_correction` × redfish
- `memory.slots[].locator` × redfish
- `memory.slots[].locator` × os
- `memory.slots[].serial` × os
- `storage.physical_disks[].serial` × os
- `storage.physical_disks[].wwn` × os
- `storage.physical_disks[].health` × os
- `storage.physical_disks[].health` × esxi
- `storage.controllers[].driver` × redfish
- `thermal.temperatures[]` × redfish
- `thermal.temperatures[].reading_celsius` × redfish
- `thermal.temperatures[].upper_critical` × redfish
- `thermal.temperatures[].physical_context` × redfish
- `thermal.fans[]` × redfish
- `thermal.fans[].reading` × redfish
- `thermal.fans[].reading_units` × redfish
- `firmware[].category` × redfish
- `firmware[].pending` × redfish
- `bmc.state` × redfish
- `bmc.power_state` × redfish
- `bmc.uuid` × redfish
- `bmc.mac_address` × redfish
- `bmc.dns_name` × redfish
- `bmc.network_hostname` × redfish
- `bmc.datetime` × redfish
- `bmc.datetime_offset` × redfish
- `bmc.timezone` × redfish
- `bmc.last_reset_time` × redfish
- `diagnosis.failure_stage` × redfish
- `diagnosis.failure_stage` × os
- `diagnosis.failure_stage` × esxi
- `diagnosis.failure_code` × redfish
- `diagnosis.failure_code` × os
- `diagnosis.failure_code` × esxi
- `storage.physical_disks[].protocol` × os
- `storage.physical_disks[].protocol` × esxi
- `cpu.architecture` × redfish
- `network.adapters[]` × redfish
- `network.adapters[].firmware_version` × redfish
- `network.adapters[].firmware_version` × os
- `network.adapters[].firmware_version` × esxi
- `network.ports[]` × redfish
- `network.teams[]` × os
- `network.interfaces[].addresses[].scope` × esxi
- `network.interfaces[].vlan_id` × os
- `network.interfaces[].vlan_parent` × os
- `network.interfaces[].team_role` × os
- `network.interfaces[].team_master` × os
- `storage.hbas[]` × redfish
- `storage.hbas[]` × os
- `storage.infiniband[]` × redfish
- `storage.infiniband[]` × os
- `storage.infiniband[]` × esxi
- `storage.hbas[].wwpn` × redfish
- `storage.hbas[].wwpn` × os
- `storage.hbas[].wwnn` × redfish
- `storage.hbas[].wwnn` × os
- `storage.hbas[].port_type` × redfish
- `storage.hbas[].port_type` × os
- `storage.hbas[].link_status` × redfish
- `storage.hbas[].link_status` × os
- `storage.hbas[].link_speed_gbps` × redfish
- `storage.hbas[].link_speed_gbps` × os
- `storage.hbas[].link_speed_gbps` × esxi
- `storage.hbas[].source` × redfish
- `storage.hbas[].source` × os
- `storage.infiniband[].node_guid` × redfish
- `storage.infiniband[].node_guid` × os
- `storage.infiniband[].node_guid` × esxi
- `storage.infiniband[].rate` × redfish
- `storage.infiniband[].rate` × os
- `storage.infiniband[].rate` × esxi
- `storage.infiniband[].rate_gbps` × redfish
- `storage.infiniband[].rate_gbps` × os
- `storage.infiniband[].rate_gbps` × esxi
- `storage.infiniband[].source` × redfish
- `storage.infiniband[].source` × os
- `storage.infiniband[].source` × esxi
- `storage.infiniband[].adapter` × redfish
- `storage.infiniband[].adapter` × os
- `storage.infiniband[].adapter` × esxi
- `storage.infiniband[].port` × redfish
- `storage.infiniband[].port` × os
- `storage.infiniband[].port` × esxi
- `storage.infiniband[].port_guid` × redfish
- `storage.infiniband[].port_guid` × os
- `storage.infiniband[].port_guid` × esxi
- `storage.infiniband[].link_status` × redfish
- `storage.infiniband[].link_status` × os
- `storage.infiniband[].link_status` × esxi
- `storage.infiniband[].model` × redfish
- `storage.infiniband[].model` × os
- `storage.infiniband[].model` × esxi
- `storage.infiniband[].vendor` × redfish
- `storage.infiniband[].vendor` × os
- `storage.infiniband[].vendor` × esxi
- `storage.infiniband[].firmware` × redfish
- `storage.infiniband[].firmware` × os
- `storage.infiniband[].firmware` × esxi
- `multi_node` × redfish
- `multi_node.enabled` × redfish
- `multi_node.layout` × redfish
- `multi_node.summary` × redfish
- `multi_node.partitions[]` × redfish
- `multi_node.managers[]` × redfish
- `multi_node.chassis[]` × redfish
- `bios` × redfish
- `bios.current` × redfish
- `bios.current.attributes` × redfish
- `diagnosis.details.credential_scope` × redfish
- `diagnosis.details.credential_scope` × os
- `diagnosis.details.credential_scope` × esxi
- `diagnosis.details.sudo` × os
- `diagnosis.details.serial_number` × os
- `diagnosis.details.recovery_credential_scope` × redfish
- `diagnosis.details.hostname_source` × redfish
- `diagnosis.details.hostname_source` × esxi
- `diagnosis.details.multi_node_layout` × redfish
- `diagnosis.details.rmc_activation_check` × redfish
- `system.hostname` × os
- `cpu.manufacturer` × redfish
- `cpu.manufacturer` × esxi
- `cpu.max_speed_mhz` × os
- `cpu.turbo_max_mhz` × os
- `cpu.turbo_max_mhz` × esxi
- `network.interfaces[].description` × os
- `network.dns_servers` × redfish
- `network.default_gateways` × redfish
- `network.default_gateways` × esxi
- `system.runtime.firewall_state` × esxi
- `system.runtime.ntp_active` × esxi
- `system.runtime.ntp_synchronized` × esxi
- `system.runtime.ntp_servers` × esxi

## 분류 2 후보 (서버 미지원 — help_ko 명시): 37

- `hostname` × redfish
- `vendor` × os
- `hardware.sku` × redfish
- `hardware.oem` × redfish
- `memory.slots[]` × os
- `memory.slots[].capacity_mb` × os
- `memory.slots[].type` × os
- `memory.slots[].manufacturer` × os
- `memory.slots[].part_number` × os
- `storage.controllers[]` × os
- `storage.controllers[].controller_type` × os
- `storage.controllers[].driver` × os
- `storage.logical_volumes[]` × redfish
- `storage.logical_volumes[].raid_level` × redfish
- `storage.logical_volumes[].member_drive_ids` × redfish
- `storage.logical_volumes[].controller_id` × redfish
- `storage.logical_volumes[].id` × redfish
- `storage.logical_volumes[].name` × redfish
- `storage.logical_volumes[].total_mb` × redfish
- `storage.logical_volumes[].health` × redfish
- `storage.logical_volumes[].state` × redfish
- `bmc.health` × redfish
- `network.adapters[]` × os
- `network.driver_map[]` × os
- `network.interfaces[].addresses[].label` × os
- `network.interfaces[].addresses[].parent_interface` × os
- `network.interfaces[].addresses[].is_alias` × os
- `network.interfaces[].addresses[].scope` × os
- `network.interfaces[].addresses[].is_secondary` × os
- `diagnosis.details.hostname_source` × os
- `system.vendor` × os
- `cpu.manufacturer` × os
- `cpu.summary.groups[].l2_cache_kb` × os
- `cpu.summary.groups[].l3_cache_kb` × os
- `system.runtime.firewall_state` × os
- `system.runtime.ntp_active` × os
- `system.runtime.ntp_synchronized` × os

## 분류 3? 후보 (코드 버그 의심 — Phase 2 검증): 17

- `storage.logical_volumes[].boot_volume` × redfish
- `bmc.oem` × redfish
- `network.bonds[]` × os
- `network.bonds[].mode` × os
- `network.bonds[].slaves[]` × os
- `network.bridges[]` × os
- `network.interfaces[].bond_role` × os
- `network.interfaces[].bond_master` × os
- `network.interfaces[].slave_state` × os
- `network.interfaces[].bond_mode` × os
- `network.interfaces[].active_slave` × os
- `network.interfaces[].bond_slaves` × os
- `network.bonds[].addresses[].label` × os
- `network.bonds[].addresses[].parent_interface` × os
- `network.bonds[].addresses[].is_alias` × os
- `network.bonds[].addresses[].scope` × os
- `network.bonds[].addresses[].is_secondary` × os


## Drift 검출 (104 entries)

- `bios`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bios.current`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bios.current.attributes`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bmc.datetime`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bmc.datetime_offset`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bmc.dns_name`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bmc.last_reset_time`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bmc.mac_address`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bmc.network_hostname`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bmc.power_state`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bmc.state`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bmc.timezone`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `bmc.uuid`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `cpu.architecture`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `cpu.manufacturer`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `cpu.max_speed_mhz`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `cpu.turbo_max_mhz`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `diagnosis.details.credential_scope`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `diagnosis.details.hostname_source`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `diagnosis.details.multi_node_layout`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `diagnosis.details.notices`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `diagnosis.details.recovery_credential_scope`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `diagnosis.details.rmc_activation_check`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `diagnosis.details.serial_number`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `diagnosis.details.sudo`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `diagnosis.failure_code`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `diagnosis.failure_stage`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `errors[]`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `errors[].detail`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `errors[].message`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `errors[].section`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `firmware[].category`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `firmware[].pending`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `hardware.asset_tag`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `hardware.bios_date`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `hardware.boot_progress`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `hardware.last_reset_time`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `hardware.part_number`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `hardware.system_type`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `hardware.tpm`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `memory.slots[].base_module_type`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `memory.slots[].bus_width_bits`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `memory.slots[].capacity_mb`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `memory.slots[].data_width_bits`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `memory.slots[].error_correction`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `memory.slots[].locator`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `memory.slots[].rank_count`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `memory.slots[].serial`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `memory.slots[].speed_mhz`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `multi_node`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `multi_node.chassis[]`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `multi_node.enabled`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `multi_node.layout`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `multi_node.managers[]`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `multi_node.partitions[]`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `multi_node.summary`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.adapters[]`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.adapters[].firmware_version`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.default_gateways`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.dns_servers`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.interfaces[].addresses[].scope`:
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.interfaces[].description`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.interfaces[].team_master`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.interfaces[].team_role`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.interfaces[].vlan_id`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.interfaces[].vlan_parent`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.ports[]`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `network.teams[]`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.controllers[].driver`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.hbas[]`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.hbas[].link_speed_gbps`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.hbas[].link_status`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.hbas[].port_type`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.hbas[].source`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.hbas[].wwnn`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.hbas[].wwpn`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[]`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[].adapter`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[].firmware`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[].link_status`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[].model`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[].node_guid`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[].port`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[].port_guid`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[].rate`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[].rate_gbps`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[].source`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.infiniband[].vendor`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.physical_disks[].health`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.physical_disks[].protocol`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.physical_disks[].serial`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `storage.physical_disks[].wwn`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `system.hostname`:
  - DRIFT-A(os): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `system.runtime.firewall_state`:
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `system.runtime.ntp_active`:
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `system.runtime.ntp_servers`:
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `system.runtime.ntp_synchronized`:
  - DRIFT-A(esxi): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `thermal.fans[]`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `thermal.fans[].reading`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `thermal.fans[].reading_units`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `thermal.temperatures[]`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `thermal.temperatures[].physical_context`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `thermal.temperatures[].reading_celsius`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보
- `thermal.temperatures[].upper_critical`:
  - DRIFT-A(redfish): 선언했지만 모든 baseline null/missing → channel 제거 후보

## 전수 매트릭스 (65 × 8)

| Field | Channel 선언 | cisco | dell | esxi | hpe | hpe_csus_3 | lenovo | rhel810_ra | ubuntu | windows_20 | windows | 분류 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `schema_version` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `target_type` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `collection_method` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `ip` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `hostname` | redfish,os,esxi | O | O | O | n | O | O | O | O | O | O | redfish:2 |
| `vendor` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | n | os:2 |
| `meta` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `correlation` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `status` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `sections.*` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `errors[]` | redfish,os,esxi | e | e | e | e | e | e | e | e | e | e | redfish:1,os:1,esxi:1 |
| `errors[].section` | redfish,os,esxi | e | e | e | e | e | e | e | e | e | e | redfish:1,os:1,esxi:1 |
| `errors[].message` | redfish,os,esxi | e | e | e | e | e | e | e | e | e | e | redfish:1,os:1,esxi:1 |
| `diagnosis.details.notices` | redfish | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | redfish:1 |
| `errors[].detail` | redfish,os,esxi | e | e | e | e | e | e | e | e | e | e | redfish:1,os:1,esxi:1 |
| `hardware.health` | redfish | O | O | _ | O | O | O | - | - | _ | - | OK |
| `hardware.sku` | os,redfish | n | O | _ | O | O | O | - | - | n | - | redfish:2 |
| `hardware.vendor` | os,esxi,redfish | O | O | O | O | O | O | - | - | O | - | OK |
| `hardware.model` | os,esxi,redfish | O | O | O | O | O | O | - | - | O | - | OK |
| `hardware.serial` | os,esxi,redfish | O | O | O | O | O | O | - | - | O | - | OK |
| `hardware.uuid` | os,esxi,redfish | O | O | O | O | O | O | - | - | O | - | OK |
| `hardware.bios_version` | os,esxi,redfish | O | O | O | O | O | O | - | - | O | - | OK |
| `hardware.bios_date` | os,esxi,redfish | n | n | O | n | n | n | - | - | O | - | redfish:1 |
| `hardware.asset_tag` | os,redfish | _ | _ | _ | _ | O | _ | - | - | n | - | redfish:1 |
| `hardware.system_type` | redfish | _ | _ | _ | _ | O | _ | - | - | _ | - | redfish:1 |
| `hardware.part_number` | redfish | _ | _ | _ | _ | O | _ | - | - | _ | - | redfish:1 |
| `hardware.last_reset_time` | redfish | _ | _ | _ | _ | n | _ | - | - | _ | - | redfish:1 |
| `hardware.boot_progress` | redfish | _ | _ | _ | _ | O | _ | - | - | _ | - | redfish:1 |
| `hardware.tpm` | redfish | _ | _ | _ | _ | O | _ | - | - | _ | - | redfish:1 |
| `hardware.oem` | os,redfish | e | O | _ | O | e | O | - | - | e | - | redfish:2 |
| `memory.total_basis` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `memory.installed_mb` | redfish,os | O | O | _ | O | O | O | O | O | O | O | OK |
| `memory.visible_mb` | os,esxi | _ | _ | O | _ | n | _ | O | O | O | O | OK |
| `memory.total_mb` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `memory.slots[]` | redfish,os | O | O | e | O | O | O | O | O | O | e | os:2 |
| `memory.slots[].capacity_mb` | redfish,os | _ | _ | e | _ | O | _ | O | O | O | e | redfish:1,os:2 |
| `memory.slots[].speed_mhz` | redfish,os | O | O | e | O | O | O | n | n | n | e | os:1 |
| `memory.slots[].type` | redfish,os | O | O | e | O | O | O | O | O | n | e | os:2 |
| `memory.slots[].base_module_type` | redfish | _ | _ | e | _ | O | _ | _ | _ | _ | e | redfish:1 |
| `memory.slots[].manufacturer` | redfish,os | O | O | e | O | O | O | O | O | O | e | os:2 |
| `memory.slots[].part_number` | redfish,os | O | O | e | O | O | O | O | O | O | e | os:2 |
| `memory.slots[].rank_count` | redfish | _ | _ | e | _ | O | _ | _ | _ | _ | e | redfish:1 |
| `memory.slots[].data_width_bits` | redfish | _ | _ | e | _ | O | _ | _ | _ | _ | e | redfish:1 |
| `memory.slots[].bus_width_bits` | redfish | _ | _ | e | _ | O | _ | _ | _ | _ | e | redfish:1 |
| `memory.slots[].error_correction` | redfish | _ | _ | e | _ | O | _ | _ | _ | _ | e | redfish:1 |
| `memory.slots[].locator` | redfish,os | _ | _ | e | _ | O | _ | _ | _ | _ | e | redfish:1,os:1 |
| `memory.slots[].serial` | redfish,os | O | O | e | O | O | O | _ | _ | n | e | os:1 |
| `memory.slots[].health` | redfish | O | O | e | O | O | O | _ | _ | _ | e | OK |
| `storage.physical_disks[]` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `storage.physical_disks[].id` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `storage.physical_disks[].serial` | redfish,os,esxi | O | O | O | O | O | O | n | n | O | n | os:1 |
| `storage.physical_disks[].wwn` | os,esxi | _ | _ | O | _ | _ | _ | n | n | O | n | os:1 |
| `storage.physical_disks[].health` | redfish,os,esxi | O | O | n | O | O | O | n | n | O | n | os:1,esxi:1 |
| `storage.physical_disks[].predicted_life_percent` | redfish | O | O | _ | O | O | O | _ | _ | _ | _ | OK |
| `storage.physical_disks[].is_os_disk` | os | _ | _ | _ | _ | _ | _ | O | O | O | O | OK |
| `storage.controllers[]` | redfish,os,esxi | O | O | O | O | O | O | O | O | e | e | os:2 |
| `storage.controllers[].controller_type` | os,esxi | _ | _ | O | _ | _ | _ | O | O | e | e | os:2 |
| `storage.controllers[].driver` | redfish,os,esxi | _ | _ | O | _ | _ | _ | O | O | e | e | redfish:1,os:2 |
| `storage.controllers[].drives[]` | redfish | O | O | n | O | O | O | n | n | e | e | OK |
| `storage.logical_volumes[]` | redfish | O | O | e | O | O | e | e | e | e | e | redfish:2 |
| `storage.logical_volumes[].raid_level` | redfish | O | O | e | O | O | e | e | e | e | e | redfish:2 |
| `storage.logical_volumes[].member_drive_ids` | redfish | O | O | e | O | O | e | e | e | e | e | redfish:2 |
| `storage.logical_volumes[].controller_id` | redfish | O | O | e | O | O | e | e | e | e | e | redfish:2 |
| `storage.logical_volumes[].id` | redfish | O | O | e | O | O | e | e | e | e | e | redfish:2 |
| `storage.logical_volumes[].name` | redfish | O | O | e | O | O | e | e | e | e | e | redfish:2 |
| `storage.logical_volumes[].total_mb` | redfish | O | O | e | O | O | e | e | e | e | e | redfish:2 |
| `storage.logical_volumes[].health` | redfish | O | O | e | O | O | e | e | e | e | e | redfish:2 |
| `storage.logical_volumes[].state` | redfish | O | O | e | O | O | e | e | e | e | e | redfish:2 |
| `storage.logical_volumes[].boot_volume` | redfish | n | O | e | n | O | e | e | e | e | e | redfish:3? |
| `network.interfaces[].link_status` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `power.power_supplies[].state` | redfish | O | O | - | O | O | O | - | - | - | - | OK |
| `thermal.temperatures[]` | redfish | _ | _ | _ | _ | _ | _ | e | e | e | _ | redfish:1 |
| `thermal.temperatures[].reading_celsius` | redfish | _ | _ | _ | _ | _ | _ | e | e | e | _ | redfish:1 |
| `thermal.temperatures[].upper_critical` | redfish | _ | _ | _ | _ | _ | _ | e | e | e | _ | redfish:1 |
| `thermal.temperatures[].physical_context` | redfish | _ | _ | _ | _ | _ | _ | e | e | e | _ | redfish:1 |
| `thermal.fans[]` | redfish | _ | _ | _ | _ | _ | _ | e | e | e | _ | redfish:1 |
| `thermal.fans[].reading` | redfish | _ | _ | _ | _ | _ | _ | e | e | e | _ | redfish:1 |
| `thermal.fans[].reading_units` | redfish | _ | _ | _ | _ | _ | _ | e | e | e | _ | redfish:1 |
| `cpu.cores_physical` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `firmware[].category` | redfish | _ | _ | - | _ | O | _ | - | - | - | - | redfish:1 |
| `firmware[].pending` | redfish | _ | _ | - | _ | O | _ | - | - | - | - | redfish:1 |
| `firmware[].component` | redfish | O | O | - | O | O | O | - | - | - | - | OK |
| `users[]` | os | - | - | - | - | - | - | O | O | O | O | OK |
| `users[].name` | os | - | - | - | - | - | - | O | O | O | O | OK |
| `users[].uid` | os | - | - | - | - | - | - | O | O | O | O | OK |
| `users[].groups` | os | - | - | - | - | - | - | O | O | O | O | OK |
| `users[].home` | os | - | - | - | - | - | - | O | O | O | O | OK |
| `users[].last_access_time` | os | - | - | - | - | - | - | O | O | O | O | OK |
| `bmc.ip` | redfish | O | O | - | O | O | O | - | - | - | - | OK |
| `bmc.firmware_version` | redfish | O | O | - | O | O | O | - | - | - | - | OK |
| `bmc.model` | redfish | O | O | - | O | O | O | - | - | - | - | OK |
| `bmc.manager_type` | redfish | O | O | - | O | O | O | - | - | - | - | OK |
| `bmc.name` | redfish | O | O | - | O | O | O | - | - | - | - | OK |
| `bmc.health` | redfish | O | O | - | O | O | n | - | - | - | - | redfish:2 |
| `bmc.state` | redfish | _ | _ | - | _ | O | _ | - | - | - | - | redfish:1 |
| `bmc.power_state` | redfish | _ | _ | - | _ | O | _ | - | - | - | - | redfish:1 |
| `bmc.uuid` | redfish | _ | _ | - | _ | O | _ | - | - | - | - | redfish:1 |
| `bmc.mac_address` | redfish | _ | _ | - | _ | O | _ | - | - | - | - | redfish:1 |
| `bmc.dns_name` | redfish | _ | _ | - | _ | O | _ | - | - | - | - | redfish:1 |
| `bmc.network_hostname` | redfish | _ | _ | - | _ | _ | _ | - | - | - | - | redfish:1 |
| `bmc.datetime` | redfish | _ | _ | - | _ | O | _ | - | - | - | - | redfish:1 |
| `bmc.datetime_offset` | redfish | _ | _ | - | _ | O | _ | - | - | - | - | redfish:1 |
| `bmc.timezone` | redfish | _ | _ | - | _ | O | _ | - | - | - | - | redfish:1 |
| `bmc.last_reset_time` | redfish | _ | _ | - | _ | O | _ | - | - | - | - | redfish:1 |
| `bmc.oem` | redfish | e | e | - | O | O | e | - | - | - | - | redfish:3? |
| `correlation.host_ip` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `diagnosis.auth_success` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `hardware.power_state` | redfish | O | O | _ | O | O | O | - | - | _ | - | OK |
| `storage.physical_disks[].failure_predicted` | redfish | O | O | _ | O | O | O | _ | _ | _ | _ | OK |
| `network.interfaces[].kind` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `meta.duration_ms` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `diagnosis.failure_stage` | redfish,os,esxi | n | n | n | n | n | n | n | n | n | n | redfish:1,os:1,esxi:1 |
| `diagnosis.failure_code` | redfish,os,esxi | n | n | n | n | n | n | n | n | n | n | redfish:1,os:1,esxi:1 |
| `storage.physical_disks[].media_type` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `storage.physical_disks[].protocol` | redfish,os,esxi | O | O | n | O | O | O | n | n | O | n | os:1,esxi:1 |
| `cpu.architecture` | redfish,os,esxi | n | n | O | n | O | n | O | O | O | O | redfish:1 |
| `system.hosting_type` | os,esxi | - | - | O | - | - | - | O | O | O | O | OK |
| `system.uptime_seconds` | os,esxi | - | - | O | - | - | - | O | O | O | O | OK |
| `firmware[].updateable` | redfish | O | O | - | O | O | O | - | - | - | - | OK |
| `cpu.summary` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `memory.summary` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `storage.summary` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `network.summary` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `network.adapters[]` | redfish,os,esxi | _ | _ | O | _ | O | _ | O | O | e | _ | redfish:1,os:2 |
| `network.adapters[].firmware_version` | redfish,os,esxi | _ | _ | _ | _ | O | _ | n | n | e | _ | redfish:1,os:1,esxi:1 |
| `network.ports[]` | redfish | _ | _ | _ | _ | O | _ | e | e | e | _ | redfish:1 |
| `network.virtual_switches[]` | esxi | _ | _ | O | _ | _ | _ | e | e | e | _ | OK |
| `network.driver_map[]` | os | _ | _ | _ | _ | _ | _ | O | O | e | _ | os:2 |
| `network.bonds[]` | os | _ | _ | _ | _ | _ | _ | O | e | e | e | os:3? |
| `network.bonds[].mode` | os | _ | _ | _ | _ | _ | _ | O | e | e | e | os:3? |
| `network.bonds[].slaves[]` | os | _ | _ | _ | _ | _ | _ | O | e | e | e | os:3? |
| `network.teams[]` | os | _ | _ | _ | _ | _ | _ | e | e | O | e | os:1 |
| `network.bridges[]` | os | _ | _ | _ | _ | _ | _ | O | e | e | e | os:3? |
| `network.interfaces[].bond_role` | os | _ | _ | _ | _ | _ | _ | O | _ | _ | _ | os:3? |
| `network.interfaces[].bond_master` | os | _ | _ | _ | _ | _ | _ | O | _ | _ | _ | os:3? |
| `network.interfaces[].slave_state` | os | _ | _ | _ | _ | _ | _ | O | _ | _ | _ | os:3? |
| `network.interfaces[].bond_mode` | os | _ | _ | _ | _ | _ | _ | O | _ | _ | _ | os:3? |
| `network.interfaces[].active_slave` | os | _ | _ | _ | _ | _ | _ | O | _ | _ | _ | os:3? |
| `network.interfaces[].bond_slaves` | os | _ | _ | _ | _ | _ | _ | O | _ | _ | _ | os:3? |
| `network.interfaces[].addresses[].label` | os | n | n | _ | n | n | n | O | O | n | _ | os:2 |
| `network.interfaces[].addresses[].parent_interface` | os | n | n | _ | n | n | n | O | O | n | _ | os:2 |
| `network.interfaces[].addresses[].is_alias` | os | n | n | _ | n | n | n | O | O | n | _ | os:2 |
| `network.interfaces[].addresses[].scope` | os,esxi | n | n | _ | n | n | n | O | O | n | _ | os:2,esxi:1 |
| `network.interfaces[].addresses[].is_secondary` | os | n | n | _ | n | n | n | O | O | n | _ | os:2 |
| `network.bonds[].addresses[].label` | os | _ | _ | _ | _ | _ | _ | O | e | e | e | os:3? |
| `network.bonds[].addresses[].parent_interface` | os | _ | _ | _ | _ | _ | _ | O | e | e | e | os:3? |
| `network.bonds[].addresses[].is_alias` | os | _ | _ | _ | _ | _ | _ | O | e | e | e | os:3? |
| `network.bonds[].addresses[].scope` | os | _ | _ | _ | _ | _ | _ | O | e | e | e | os:3? |
| `network.bonds[].addresses[].is_secondary` | os | _ | _ | _ | _ | _ | _ | O | e | e | e | os:3? |
| `network.interfaces[].vlan_id` | os | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | os:1 |
| `network.interfaces[].vlan_parent` | os | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | os:1 |
| `network.interfaces[].team_role` | os | _ | _ | _ | _ | _ | _ | _ | _ | O | _ | os:1 |
| `network.interfaces[].team_master` | os | _ | _ | _ | _ | _ | _ | _ | _ | O | _ | os:1 |
| `storage.hbas[]` | redfish,os,esxi | _ | _ | O | _ | O | _ | e | e | e | _ | redfish:1,os:1 |
| `storage.infiniband[]` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.hbas[].wwpn` | redfish,os,esxi | _ | _ | O | _ | O | _ | e | e | e | _ | redfish:1,os:1 |
| `storage.hbas[].wwnn` | redfish,os,esxi | _ | _ | O | _ | O | _ | e | e | e | _ | redfish:1,os:1 |
| `storage.hbas[].port_type` | redfish,os,esxi | _ | _ | O | _ | O | _ | e | e | e | _ | redfish:1,os:1 |
| `storage.hbas[].link_status` | redfish,os,esxi | _ | _ | O | _ | O | _ | e | e | e | _ | redfish:1,os:1 |
| `storage.hbas[].link_speed_gbps` | redfish,os,esxi | _ | _ | n | _ | O | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.hbas[].source` | redfish,os,esxi | _ | _ | O | _ | O | _ | e | e | e | _ | redfish:1,os:1 |
| `storage.infiniband[].node_guid` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.infiniband[].rate` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.infiniband[].rate_gbps` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.infiniband[].source` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.infiniband[].adapter` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.infiniband[].port` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.infiniband[].port_guid` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.infiniband[].link_status` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.infiniband[].model` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.infiniband[].vendor` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `storage.infiniband[].firmware` | redfish,os,esxi | _ | _ | e | _ | e | _ | e | e | e | _ | redfish:1,os:1,esxi:1 |
| `system.runtime` | os,esxi | - | - | O | - | - | - | O | O | O | O | OK |
| `multi_node` | redfish | _ | _ | _ | _ | O | _ | _ | _ | _ | _ | redfish:1 |
| `multi_node.enabled` | redfish | _ | _ | _ | _ | O | _ | _ | _ | _ | _ | redfish:1 |
| `multi_node.layout` | redfish | _ | _ | _ | _ | O | _ | _ | _ | _ | _ | redfish:1 |
| `multi_node.summary` | redfish | _ | _ | _ | _ | O | _ | _ | _ | _ | _ | redfish:1 |
| `multi_node.partitions[]` | redfish | _ | _ | _ | _ | O | _ | _ | _ | _ | _ | redfish:1 |
| `multi_node.managers[]` | redfish | _ | _ | _ | _ | O | _ | _ | _ | _ | _ | redfish:1 |
| `multi_node.chassis[]` | redfish | _ | _ | _ | _ | O | _ | _ | _ | _ | _ | redfish:1 |
| `bios` | redfish | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | redfish:1 |
| `bios.current` | redfish | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | redfish:1 |
| `bios.current.attributes` | redfish | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | redfish:1 |
| `diagnosis.details.credential_scope` | redfish,os,esxi | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | redfish:1,os:1,esxi:1 |
| `diagnosis.details.sudo` | os | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | os:1 |
| `diagnosis.details.serial_number` | os | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | os:1 |
| `diagnosis.details.recovery_credential_scope` | redfish | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | redfish:1 |
| `diagnosis.details.hostname_source` | redfish,os,esxi | _ | _ | _ | _ | _ | _ | O | O | O | _ | redfish:1,os:2,esxi:1 |
| `diagnosis.details.multi_node_layout` | redfish | _ | _ | _ | _ | O | _ | _ | _ | _ | _ | redfish:1 |
| `diagnosis.details.rmc_activation_check` | redfish | _ | _ | _ | _ | O | _ | _ | _ | _ | _ | redfish:1 |
| `system.hostname` | redfish,os,esxi | - | - | O | - | - | - | _ | _ | _ | _ | os:1 |
| `system.fqdn` | redfish,os,esxi | - | - | O | - | - | - | O | O | O | O | OK |
| `system.vendor` | os | - | - | _ | - | - | - | O | O | _ | _ | os:2 |
| `cpu.manufacturer` | redfish,os,esxi | _ | _ | _ | _ | _ | _ | O | O | O | _ | redfish:1,os:2,esxi:1 |
| `cpu.max_speed_mhz` | redfish,os,esxi | O | O | O | O | O | O | n | n | O | _ | os:1 |
| `cpu.turbo_max_mhz` | os,esxi | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | os:1,esxi:1 |
| `cpu.summary.groups[].l2_cache_kb` | os | _ | _ | _ | _ | _ | _ | O | O | O | n | os:2 |
| `cpu.summary.groups[].l3_cache_kb` | os | _ | _ | _ | _ | _ | _ | O | O | O | n | os:2 |
| `network.interfaces[].description` | os | _ | _ | _ | _ | _ | _ | _ | _ | _ | _ | os:1 |
| `network.interfaces[].mac` | redfish,os,esxi | O | O | O | O | O | O | O | O | O | O | OK |
| `network.dns_servers` | redfish,os,esxi | e | e | O | e | O | e | O | O | O | O | redfish:1 |
| `network.default_gateways` | redfish,os,esxi | e | e | e | e | O | e | O | O | O | O | redfish:1,esxi:1 |
| `system.runtime.firewall_state` | os,esxi | - | - | n | - | - | - | O | O | O | n | os:2,esxi:1 |
| `system.runtime.ntp_active` | os,esxi | - | - | n | - | - | - | O | O | O | n | os:2,esxi:1 |
| `system.runtime.ntp_synchronized` | os,esxi | - | - | n | - | - | - | O | O | O | n | os:2,esxi:1 |
| `system.runtime.ntp_servers` | esxi | - | - | _ | - | - | - | _ | _ | _ | _ | esxi:1 |

**범례**: O=present / n=null / e=empty / -=not_supported / _=missing

<!-- AUTO-GEN: FIELD_USAGE_MATRIX END -->

## Phase 1 의심 후보 (수동 식별)

Phase 1 탐색 (Explore agents) 에서 식별된 15 의심 후보. Phase 1 스크립트가 매트릭스로 확정.

### Redfish (6)
- `memory.visible_mb` — 1차: 분류 1 (Redfish spec 미정의)
- `memory.free_mb` — 1차: 분류 1 (필드 자체 없음)
- `hardware.bios_date` — 1차: 분류 2 (OEM 추출 코드 있으나 모든 baseline null)
- `storage.physical_disks[].locator` — 1차: 분류 2 (Redfish 표준 미보장)
- `storage.logical_volumes[].boot_volume` — 1차: 분류 2 (Dell OEM 만)
- `bmc.oem.ilo_version` — 1차: 분류 2 (HPE 만 + null)

### OS (5)
- `Windows memory.slots` — 1차: 분류 2 확정 (VM 환경 한정 — 코드 line 17-69 정상)
- `storage.physical_disks[].health` — 1차: 분류 1 (OS SMART 제한)
- `network.link_type` — 1차: 분류 1 (NIC 트랜시버 OS 미제공)
- `cpu.l2/l3_cache_kb` (raw fallback) — 1차: 분류 2
- `memory.slots[].speed_mhz / manufacturer` (raw fallback) — 1차: 분류 2

### ESXi (4)
- `memory.installed_mb` — 1차: 분류 2 (ansible_memtotal_mb 만)
- `storage.physical_disks[]` — 1차: 분류 1 (datastore 기반)
- `storage.controllers[]` — 1차: 분류 1 (RAID 미수집)
- `network.adapters[]` — 1차: 분류 2 (collect_network_extended 옵션)

## 관련

- rule: `13-output-schema-fields` R5/R7 (envelope shape 보존 + `docs/contract/03-fields.md` 동기화)
- rule: `28-empirical-verification-lifecycle` R1 #13 (측정 대상 신규)
- rule: `92-dependency-and-regression-gate` R5 (schema 변경 사용자 명시 승인)
- rule: `96-external-contract-integrity` R1 (외부 계약 origin 주석)
- skill: `add-new-vendor` (단계 11 — 필드 분류 검증 의무화 예정 — Phase 4)
- catalog: `SCHEMA_FIELDS.md` (field_dictionary 요약)
- script: `scripts/ai/measure_field_usage_matrix.py` (Phase 1 — 자동 측정)
- ADR: `docs/ai/decisions/ADR-2026-05-11-field-channel-declaration-refinement.md` (Phase 4)
- plan: `~/.claude/plans/tranquil-wandering-lampson.md`
