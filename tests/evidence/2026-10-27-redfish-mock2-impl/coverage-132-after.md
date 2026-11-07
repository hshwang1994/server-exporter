# 132칸 재판정 (2026-10-27, 최종 Tier 1 봉투 기준)

- 입력: `tests/evidence/2026-10-27-redfish-mock2-impl/tier1-final`(18 label 중 2차 11대) · 분석 Round `coverage/coverage-132.json`(ISSUE 77 · PASS 47 · N/A 8). 칸마다 명시한 검사를 최종 봉투 값으로 실행했고(아래 근거), 재생으로 확정할 수 없는 칸은 PASS 로 올리지 않았다(MOCK_LIMITATION). 사용자 결정이 남은 칸은 ISSUE 로 둔다.
- 집계(after): **PASS 120 · ISSUE 2 · MOCK_LIMITATION 2 · NOT_APPLICABLE 8** / 총 132. 표의 `A→B` 는 분석 Round 판정 → 재판정.
- OBSERVATION_ONLY 처분(계약대로 · 변경 제안 없음)만 남은 칸은 PASS 로 적는다 — 해당 ID 는 `ISSUE_DISPOSITION.md` 에 근거가 있다.
- **2026-10-28 재대조**: 새 Tier 1 봉투(`../2026-10-28-redfish-mock2-review-fix/tier1-A`)로 칸 검사를 다시 계산했다(`../2026-10-28-redfish-mock2-review-fix/cell_check.md`). 판정 수는 그대로이고 근거 문장 13칸을 고쳤다(맨 아래 표).

| server | cpu | system | network | storage | memory | firmware | bios | thermal | hardware | bmc | power | multi_node |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| csus3200_01 | PASS | ISSUE→PASS | PASS | ISSUE→MOCK_LIMITATION | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | PASS | PASS | ISSUE→PASS | PASS | ISSUE→PASS |
| csus3200_02 | ISSUE→PASS | ISSUE→PASS | PASS | PASS | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | PASS | PASS | ISSUE→PASS | PASS | ISSUE→PASS |
| csus3200_03 | PASS | ISSUE→PASS | PASS | ISSUE→MOCK_LIMITATION | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | PASS | PASS | ISSUE→PASS | PASS | ISSUE→PASS |
| dl380_gen12_01 | PASS | ISSUE→PASS | PASS | PASS | PASS | ISSUE→PASS | PASS | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | NOT_APPLICABLE |
| dl380_gen12_02 | PASS | ISSUE→PASS | PASS | PASS | PASS | ISSUE→PASS | PASS | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | NOT_APPLICABLE |
| dl380_gen12_03 | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | ISSUE | ISSUE→PASS | ISSUE | PASS | ISSUE→PASS | PASS | ISSUE→PASS | ISSUE→PASS | NOT_APPLICABLE |
| dl380_gen12_04 | PASS | ISSUE→PASS | PASS | PASS | PASS | ISSUE→PASS | PASS | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | NOT_APPLICABLE |
| sr650_v4_01 | ISSUE→PASS | ISSUE→PASS | PASS | PASS | PASS | ISSUE→PASS | ISSUE→PASS | PASS | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | NOT_APPLICABLE |
| sr650_v4_02 | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | PASS | PASS | ISSUE→PASS | ISSUE→PASS | PASS | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | NOT_APPLICABLE |
| sr650_v4_03 | PASS | ISSUE→PASS | ISSUE→PASS | PASS | PASS | ISSUE→PASS | ISSUE→PASS | PASS | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | NOT_APPLICABLE |
| sr650_v4_04 | ISSUE→PASS | ISSUE→PASS | PASS | PASS | PASS | ISSUE→PASS | ISSUE→PASS | PASS | ISSUE→PASS | ISSUE→PASS | ISSUE→PASS | NOT_APPLICABLE |

## 칸별 근거 (재판정 검사 결과)

### cpu
- **csus3200_01** [PASS→PASS] (종전 PASS 유지) logical_threads 키 없음(FIX 1) · manufacturer='Intel'(FIX 2) · sockets=4 cores=64
- **csus3200_02** [ISSUE→PASS] logical_threads 키 없음(FIX 1) · manufacturer='Intel'(FIX 2) · sockets=4 cores=112
- **csus3200_03** [PASS→PASS] (종전 PASS 유지) logical_threads 키 없음(FIX 1) · manufacturer='Intel'(FIX 2) · sockets=4 cores=64
- **dl380_gen12_01** [PASS→PASS] (종전 PASS 유지) logical_threads 키 없음(FIX 1) · manufacturer='Intel'(FIX 2) · sockets=2 cores=64
- **dl380_gen12_02** [PASS→PASS] (종전 PASS 유지) logical_threads 키 없음(FIX 1) · manufacturer='Intel'(FIX 2) · sockets=2 cores=64
- **dl380_gen12_03** [ISSUE→PASS] logical_threads 키 없음(FIX 1) · manufacturer='Intel'(FIX 2) · sockets=2 cores=64
- **dl380_gen12_04** [PASS→PASS] (종전 PASS 유지) logical_threads 키 없음(FIX 1) · manufacturer='Intel'(FIX 2) · sockets=2 cores=64
- **sr650_v4_01** [ISSUE→PASS] logical_threads 키 없음(FIX 1) · manufacturer='Intel'(FIX 2) · sockets=2 cores=64
- **sr650_v4_02** [ISSUE→PASS] logical_threads 키 없음(FIX 1) · manufacturer='Intel'(FIX 2) · sockets=2 cores=64
- **sr650_v4_03** [PASS→PASS] (종전 PASS 유지) logical_threads 키 없음(FIX 1) · manufacturer='Intel'(FIX 2) · sockets=2 cores=64
- **sr650_v4_04** [ISSUE→PASS] logical_threads 키 없음(FIX 1) · manufacturer='Intel'(FIX 2) · sockets=2 cores=64

### system
- **csus3200_01** [ISSUE→PASS] sections.system=not_supported · data.system.hostname='yicdspdb01' (FIX 4 — not_supported 유지 + 원천(RMC 이름 정책) 있을 때만 hostname 발행, HostOS 승격 없음; 01-hardware-002 health 는 hardware 칸)
- **csus3200_02** [ISSUE→PASS] sections.system=not_supported · data.system.hostname='yicgsfabap01' (FIX 4 — not_supported 유지 + 원천(RMC 이름 정책) 있을 때만 hostname 발행, HostOS 승격 없음; 01-hardware-002 health 는 hardware 칸)
- **csus3200_03** [ISSUE→PASS] sections.system=not_supported · data.system.hostname='yicgsfabdb01' (FIX 4 — not_supported 유지 + 원천(RMC 이름 정책) 있을 때만 hostname 발행, HostOS 승격 없음; 01-hardware-002 health 는 hardware 칸)
- **dl380_gen12_01** [ISSUE→PASS] sections.system=not_supported · data.system.hostname='yicesxmgmt05' (FIX 4 — not_supported 유지 + 원천(ComputerSystem `HostName`) 있을 때만 hostname 발행, HostOS 승격 없음; 01-hardware-002 health 는 hardware 칸)
- **dl380_gen12_02** [ISSUE→PASS] sections.system=not_supported · data.system.hostname=None (FIX 4 — not_supported 유지 + 원천(ComputerSystem `HostName`) 있을 때만 hostname 발행, HostOS 승격 없음; 01-hardware-002 health 는 hardware 칸)
- **dl380_gen12_03** [ISSUE→PASS] sections.system=not_supported · data.system.hostname=None (FIX 4 — not_supported 유지 + 원천(ComputerSystem `HostName`) 있을 때만 hostname 발행, HostOS 승격 없음; 01-hardware-002 health 는 hardware 칸)
- **dl380_gen12_04** [ISSUE→PASS] sections.system=not_supported · data.system.hostname=None (FIX 4 — not_supported 유지 + 원천(ComputerSystem `HostName`) 있을 때만 hostname 발행, HostOS 승격 없음; 01-hardware-002 health 는 hardware 칸)
- **sr650_v4_01** [ISSUE→PASS] sections.system=not_supported · data.system.hostname=None (FIX 4 — not_supported 유지 + 원천(ComputerSystem `HostName`) 있을 때만 hostname 발행, HostOS 승격 없음; 01-hardware-002 health 는 hardware 칸)
- **sr650_v4_02** [ISSUE→PASS] sections.system=not_supported · data.system.hostname=None (FIX 4 — not_supported 유지 + 원천(ComputerSystem `HostName`) 있을 때만 hostname 발행, HostOS 승격 없음; 01-hardware-002 health 는 hardware 칸)
- **sr650_v4_03** [ISSUE→PASS] sections.system=not_supported · data.system.hostname=None (FIX 4 — not_supported 유지 + 원천(ComputerSystem `HostName`) 있을 때만 hostname 발행, HostOS 승격 없음; 01-hardware-002 health 는 hardware 칸)
- **sr650_v4_04** [ISSUE→PASS] sections.system=not_supported · data.system.hostname=None (FIX 4 — not_supported 유지 + 원천(ComputerSystem `HostName`) 있을 때만 hostname 발행, HostOS 승격 없음; 01-hardware-002 health 는 hardware 칸)

### network
- **csus3200_01** [PASS→PASS] (종전 PASS 유지) interfaces 8 · FC/8옥텟 주소 혼입 0 (INV-5) · port_count=8
- **csus3200_02** [PASS→PASS] (종전 PASS 유지) interfaces 4 · FC/8옥텟 주소 혼입 0 (INV-5) · port_count=4
- **csus3200_03** [PASS→PASS] (종전 PASS 유지) interfaces 8 · FC/8옥텟 주소 혼입 0 (INV-5) · port_count=8
- **dl380_gen12_01** [PASS→PASS] (종전 PASS 유지) interfaces 10 · FC/8옥텟 주소 혼입 0 (INV-5) · port_count=10
- **dl380_gen12_02** [PASS→PASS] (종전 PASS 유지) interfaces 8 · FC/8옥텟 주소 혼입 0 (INV-5) · port_count=8
- **dl380_gen12_03** [ISSUE→PASS] 전원 Off notice 에 '네트워크' 포함(2026-10-28 R3 `ac368a4b` — 새 Tier 1 봉투) · interfaces 4(link unknown) · adapters 2 · ports 4 — network 값은 before = after, 칸 근거는 notice 문구 (03-storage-001 (a); 2026-10-28 근거 교체)
- **dl380_gen12_04** [PASS→PASS] (종전 PASS 유지) interfaces 8 · FC/8옥텟 주소 혼입 0 (INV-5) · port_count=8
- **sr650_v4_01** [PASS→PASS] (종전 PASS 유지) interfaces 5 · FC/8옥텟 주소 혼입 0 (INV-5) · port_count=5 · link 보충 4건(03-network-002, 2026-10-28 — 칸 판정 기준 밖)
- **sr650_v4_02** [ISSUE→PASS] interfaces 5 · FC/8옥텟 주소 혼입 0 (INV-5) · port_count=5 · link 보충 3건(03-network-002, 2026-10-28 — 칸 판정 기준 밖) · 링크 미확정 1 NIC 잔여(NIC6 — 03-network-002 HOLD)
- **sr650_v4_03** [ISSUE→PASS] interfaces 11 · FC/8옥텟 주소 혼입 0 (INV-5) · port_count=11 · link 보충 10건(03-network-002, 2026-10-28 — 칸 판정 기준 밖)
- **sr650_v4_04** [PASS→PASS] (종전 PASS 유지) interfaces 5 · FC/8옥텟 주소 혼입 0 (INV-5) · port_count=5 · link 보충 3건(03-network-002, 2026-10-28 — 칸 판정 기준 밖) · 링크 미확정 1 NIC 잔여(NIC4 — 03-network-002 HOLD)

### storage
- **csus3200_01** [ISSUE→MOCK_LIMITATION] hbas 4 link_status down True · 카드 조건 notice 2건(A안, 값 불변) — 포트 단위 링크는 RMC 가 주지 않아 재생으로 확정 불가
- **csus3200_02** [PASS→PASS] (종전 PASS 유지) FC HBA 없음(hbas 0 · 노출 0, 개수 정합) · disks=4
- **csus3200_03** [ISSUE→MOCK_LIMITATION] hbas 4 link_status down True · 카드 조건 notice 2건(A안, 값 불변) — 포트 단위 링크는 RMC 가 주지 않아 재생으로 확정 불가
- **dl380_gen12_01** [PASS→PASS] (종전 PASS 유지) disks=2 hbas=4
- **dl380_gen12_02** [PASS→PASS] (종전 PASS 유지) disks=4 hbas=4
- **dl380_gen12_03** [ISSUE→ISSUE] 03-storage-001 (b) controllers 보강 HOLD(사용자 결정) — (a) 전원 Off notice 있음, storage 컬렉션 0건은 placeholder 없이 0 유지(disks=0)
- **dl380_gen12_04** [PASS→PASS] (종전 PASS 유지) disks=4 hbas=4
- **sr650_v4_01** [PASS→PASS] (종전 PASS 유지) disks=4 hbas=0
- **sr650_v4_02** [PASS→PASS] (종전 PASS 유지) disks=4 hbas=4
- **sr650_v4_03** [PASS→PASS] (종전 PASS 유지) disks=2 hbas=4
- **sr650_v4_04** [PASS→PASS] (종전 PASS 유지) disks=6 hbas=0

### memory
- **csus3200_01** [ISSUE→PASS] slots 32 rank_count=[1] (02-memory-004) · speed_mhz 원값 보존(FIX 3 문서) · total_basis 관찰
- **csus3200_02** [ISSUE→PASS] slots 16 rank_count=[1] (02-memory-004) · speed_mhz 원값 보존(FIX 3 문서) · total_basis 관찰
- **csus3200_03** [ISSUE→PASS] slots 16 rank_count=[1] (02-memory-004) · speed_mhz 원값 보존(FIX 3 문서) · total_basis 관찰
- **dl380_gen12_01** [PASS→PASS] (종전 PASS 유지) slots 16
- **dl380_gen12_02** [PASS→PASS] (종전 PASS 유지) slots 8
- **dl380_gen12_03** [ISSUE→PASS] slots 16 (빈 슬롯 제외, 종전 32) · 빈 placeholder 0 (02-memory-001)
- **dl380_gen12_04** [PASS→PASS] (종전 PASS 유지) slots 8
- **sr650_v4_01** [PASS→PASS] (종전 PASS 유지) slots 2
- **sr650_v4_02** [PASS→PASS] (종전 PASS 유지) slots 2
- **sr650_v4_03** [PASS→PASS] (종전 PASS 유지) slots 16
- **sr650_v4_04** [PASS→PASS] (종전 PASS 유지) slots 8

### firmware
- **csus3200_01** [ISSUE→PASS] Partition0_FW/ComplexFW category=['other', 'other'] (구조 근거 없음 → other 유지, VALIDATED) · updateable null 허용(사전 boolean|null)
- **csus3200_02** [ISSUE→PASS] Partition0_FW/ComplexFW category=['other', 'other'] (구조 근거 없음 → other 유지, VALIDATED) · updateable null 허용(사전 boolean|null)
- **csus3200_03** [ISSUE→PASS] Partition0_FW/ComplexFW category=['other', 'other'] (구조 근거 없음 → other 유지, VALIDATED) · updateable null 허용(사전 boolean|null)
- **dl380_gen12_01** [ISSUE→PASS] MR4xxi category=['storage_controller'] · Embedded Video Controller category=['other'] (04-firmware-002)
- **dl380_gen12_02** [ISSUE→PASS] MR4xxi category=['storage_controller'] · Embedded Video Controller category=['other'] (04-firmware-002)
- **dl380_gen12_03** [ISSUE→ISSUE] MR4xxi category=['other'] · Embedded Video Controller category=['other'] (04-firmware-002) — 전원 Off 호스트는 Storage 0건이라 controller 조인 근거가 없어 other(controllers=0; 03-storage-001 (b) HOLD 와 같은 원인)
- **dl380_gen12_04** [ISSUE→PASS] MR4xxi category=['storage_controller'] · Embedded Video Controller category=['other'] (04-firmware-002)
- **sr650_v4_01** [ISSUE→PASS] UEFI category=['bios'] · PSoC=['backplane'] · 빈 -Pending 0 (04-firmware-001/003/006) · firmware 24
- **sr650_v4_02** [ISSUE→PASS] UEFI category=['bios'] · PSoC=['backplane'] · 빈 -Pending 0 (04-firmware-001/003/006) · firmware 26
- **sr650_v4_03** [ISSUE→PASS] UEFI category=['bios'] · PSoC=['backplane'] · 빈 -Pending 0 (04-firmware-001/003/006) · firmware 36
- **sr650_v4_04** [ISSUE→PASS] UEFI category=['bios'] · PSoC=['backplane'] · 빈 -Pending 0 (04-firmware-001/003/006) · firmware 26

### bios
- **csus3200_01** [ISSUE→PASS] bios_version=1.77.30-20260911_061319 == bmc.firmware_version=1.77.30-20260911_061319 (complex 번들, 04-firmware-011 문서) · UEFI 항목 category other(VALIDATED)
- **csus3200_02** [ISSUE→PASS] bios_version=1.77.30-20260911_061319 == bmc.firmware_version=1.77.30-20260911_061319 (complex 번들, 04-firmware-011 문서) · UEFI 항목 category other(VALIDATED)
- **csus3200_03** [ISSUE→PASS] bios_version=1.77.30-20260911_061319 == bmc.firmware_version=1.77.30-20260911_061319 (complex 번들, 04-firmware-011 문서) · UEFI 항목 category other(VALIDATED)
- **dl380_gen12_01** [PASS→PASS] (종전 PASS 유지) bios_version=U68 v1.82 (06/26/2026)
- **dl380_gen12_02** [PASS→PASS] (종전 PASS 유지) bios_version=U68 v1.90 (08/20/2026)
- **dl380_gen12_03** [PASS→PASS] (종전 PASS 유지) bios_version=U68 v1.82 (06/26/2026)
- **dl380_gen12_04** [PASS→PASS] (종전 PASS 유지) bios_version=U68 v1.82 (06/26/2026)
- **sr650_v4_01** [ISSUE→PASS] bios_date=2026-05-11 (FirmwareInventory UEFI ReleaseDate 폴백, 01-hardware-004≡04-bios-001)
- **sr650_v4_02** [ISSUE→PASS] bios_date=2026-05-11 (FirmwareInventory UEFI ReleaseDate 폴백, 01-hardware-004≡04-bios-001)
- **sr650_v4_03** [ISSUE→PASS] bios_date=2026-06-22 (FirmwareInventory UEFI ReleaseDate 폴백, 01-hardware-004≡04-bios-001)
- **sr650_v4_04** [ISSUE→PASS] bios_date=2026-05-11 (FirmwareInventory UEFI ReleaseDate 폴백, 01-hardware-004≡04-bios-001)

### thermal
- **csus3200_01** [PASS→PASS] (종전 PASS 유지) temps 63 · Absent 항목 0 · 비-Enabled 0°C 0 (05-thermal-001) · notice 0
- **csus3200_02** [PASS→PASS] (종전 PASS 유지) temps 47 · Absent 항목 0 · 비-Enabled 0°C 0 (05-thermal-001) · notice 0
- **csus3200_03** [PASS→PASS] (종전 PASS 유지) temps 47 · Absent 항목 0 · 비-Enabled 0°C 0 (05-thermal-001) · notice 0
- **dl380_gen12_01** [ISSUE→PASS] temps 49 · Absent 항목 0 · 비-Enabled 0°C 0 (05-thermal-001) · notice 1
- **dl380_gen12_02** [ISSUE→PASS] temps 36 · Absent 항목 0 · 비-Enabled 0°C 0 (05-thermal-001) · notice 1
- **dl380_gen12_03** [ISSUE→PASS] temps 42 비-Enabled reading null True · Absent 0 (05-thermal-002)
- **dl380_gen12_04** [ISSUE→PASS] temps 46 · Absent 항목 0 · 비-Enabled 0°C 0 (05-thermal-001) · notice 1
- **sr650_v4_01** [PASS→PASS] (종전 PASS 유지) temps 8 · Absent 항목 0 · 비-Enabled 0°C 0 (05-thermal-001) · notice 0
- **sr650_v4_02** [PASS→PASS] (종전 PASS 유지) temps 8 · Absent 항목 0 · 비-Enabled 0°C 0 (05-thermal-001) · notice 0
- **sr650_v4_03** [PASS→PASS] (종전 PASS 유지) temps 22 · Absent 항목 0 · 비-Enabled 0°C 0 (05-thermal-001) · notice 0
- **sr650_v4_04** [PASS→PASS] (종전 PASS 유지) temps 14 · Absent 항목 0 · 비-Enabled 0°C 0 (05-thermal-001) · notice 0

### hardware
- **csus3200_01** [PASS→PASS] (종전 PASS 유지) health='OK' = Status.Health 원값(Rollup 폴백은 null 일 때만, 01-hardware-002)
- **csus3200_02** [PASS→PASS] (종전 PASS 유지) health='OK' = Status.Health 원값(Rollup 폴백은 null 일 때만, 01-hardware-002)
- **csus3200_03** [PASS→PASS] (종전 PASS 유지) health='OK' = Status.Health 원값(Rollup 폴백은 null 일 때만, 01-hardware-002)
- **dl380_gen12_01** [ISSUE→PASS] health='Warning' = Status.Health 원값(Rollup 폴백은 null 일 때만, 01-hardware-002)
- **dl380_gen12_02** [ISSUE→PASS] health='Warning' = Status.Health 원값(Rollup 폴백은 null 일 때만, 01-hardware-002)
- **dl380_gen12_03** [PASS→PASS] (종전 PASS 유지) health='Warning' = Status.Health 원값(Rollup 폴백은 null 일 때만, 01-hardware-002)
- **dl380_gen12_04** [ISSUE→PASS] health='Warning' = Status.Health 원값(Rollup 폴백은 null 일 때만, 01-hardware-002)
- **sr650_v4_01** [ISSUE→PASS] bios_date=2026-05-11 · oem.machine_type='7DGD' led_indicator='Off' (01-hardware-004/005) · adapter=redfish_lenovo_xcc3
- **sr650_v4_02** [ISSUE→PASS] bios_date=2026-05-11 · oem.machine_type='7DGD' led_indicator='Off' (01-hardware-004/005) · adapter=redfish_lenovo_xcc3
- **sr650_v4_03** [ISSUE→PASS] bios_date=2026-06-22 · oem.machine_type='7DGD' led_indicator='Off' (01-hardware-004/005) · adapter=redfish_lenovo_xcc3
- **sr650_v4_04** [ISSUE→PASS] bios_date=2026-05-11 · oem.machine_type='7DGD' led_indicator='Off' (01-hardware-004/005) · adapter=redfish_lenovo_xcc3

### bmc
- **csus3200_01** [ISSUE→PASS] name='RMC' (06-bmc-006; layout 없는 재생도 RMC) · uuid=None 문서 정정(06-bmc-009)
- **csus3200_02** [ISSUE→PASS] name='RMC' (06-bmc-006; layout 없는 재생도 RMC) · uuid=None 문서 정정(06-bmc-009)
- **csus3200_03** [ISSUE→PASS] name='RMC' (06-bmc-006; layout 없는 재생도 RMC) · uuid=None 문서 정정(06-bmc-009)
- **dl380_gen12_01** [ISSUE→PASS] timezone='JST-9:00' (06-bmc-003 DateTimeService) · datetime=2026-10-22T06:15:43Z offset=+09:00 (06-bmc-004 문서) · ip=11.65.23.95 (06-bmc-005 값 불변)
- **dl380_gen12_02** [ISSUE→PASS] timezone='JST-9:00' (06-bmc-003 DateTimeService) · datetime=2026-10-22T06:27:39Z offset=+09:00 (06-bmc-004 문서) · ip=11.65.23.201 (06-bmc-005 값 불변)
- **dl380_gen12_03** [ISSUE→PASS] timezone='JST-9:00' (06-bmc-003 DateTimeService) · datetime=2026-10-22T06:41:28Z offset=+09:00 (06-bmc-004 문서) · ip=11.65.23.55 (06-bmc-005 값 불변)
- **dl380_gen12_04** [ISSUE→PASS] timezone='JST-9:00' (06-bmc-003 DateTimeService) · datetime=2026-10-22T06:38:01Z offset=+09:00 (06-bmc-004 문서) · ip=11.65.23.52 (06-bmc-005 값 불변)
- **sr650_v4_01** [ISSUE→PASS] meta.adapter_id=redfish_lenovo_xcc3 (01-adapter-001 재선택) · name=XCC
- **sr650_v4_02** [ISSUE→PASS] meta.adapter_id=redfish_lenovo_xcc3 (01-adapter-001 재선택) · name=XCC
- **sr650_v4_03** [ISSUE→PASS] meta.adapter_id=redfish_lenovo_xcc3 (01-adapter-001 재선택) · name=XCC
- **sr650_v4_04** [ISSUE→PASS] meta.adapter_id=redfish_lenovo_xcc3 (01-adapter-001 재선택) · name=XCC

### power
- **csus3200_01** [PASS→PASS] (종전 PASS 유지) PSU 4 · model 패딩 0 (05-power-003) · 입력 0 관측 notice 0건 (05-power-002) · power_capacity_watts 정의 문서(05-power-005)
- **csus3200_02** [PASS→PASS] (종전 PASS 유지) PSU 4 · model 패딩 0 (05-power-003) · 입력 0 관측 notice 0건 (05-power-002) · power_capacity_watts 정의 문서(05-power-005)
- **csus3200_03** [PASS→PASS] (종전 PASS 유지) PSU 4 · model 패딩 0 (05-power-003) · 입력 0 관측 notice 0건 (05-power-002) · power_capacity_watts 정의 문서(05-power-005)
- **dl380_gen12_01** [ISSUE→PASS] PSU 2 · model 패딩 0 (05-power-003) · 입력 0 관측 notice 1건 (05-power-002) · power_capacity_watts 정의 문서(05-power-005)
- **dl380_gen12_02** [ISSUE→PASS] PSU 2 · model 패딩 0 (05-power-003) · 입력 0 관측 notice 1건 (05-power-002) · power_capacity_watts 정의 문서(05-power-005)
- **dl380_gen12_03** [ISSUE→PASS] PSU 2 (Absent 2) · Absent 의 capacity/firmware null True (05-power-001)
- **dl380_gen12_04** [ISSUE→PASS] PSU 2 · model 패딩 0 (05-power-003) · 입력 0 관측 notice 1건 (05-power-002) · power_capacity_watts 정의 문서(05-power-005)
- **sr650_v4_01** [ISSUE→PASS] PSU 2 · model 패딩 0 (05-power-003) · 입력 0 관측 notice 1건 (05-power-002) · power_capacity_watts 정의 문서(05-power-005)
- **sr650_v4_02** [ISSUE→PASS] PSU 2 · model 패딩 0 (05-power-003) · 입력 0 관측 notice 1건 (05-power-002) · power_capacity_watts 정의 문서(05-power-005)
- **sr650_v4_03** [ISSUE→PASS] PSU 2 · model 패딩 0 (05-power-003) · 입력 0 관측 notice 1건 (05-power-002) · power_capacity_watts 정의 문서(05-power-005)
- **sr650_v4_04** [ISSUE→PASS] PSU 2 · model 패딩 0 (05-power-003) · 입력 0 관측 notice 1건 (05-power-002) · power_capacity_watts 정의 문서(05-power-005)

### multi_node
- **csus3200_01** [ISSUE→PASS] composition count null True (FIX 6) · 링크 없는 섀시 경로 요청 0 (01-multi_node-006) · layout=rmc_primary · baseline 실측 교체(FIX 5, 01-multi_node-003)
- **csus3200_02** [ISSUE→PASS] composition count null True (FIX 6) · 링크 없는 섀시 경로 요청 0 (01-multi_node-006) · layout=rmc_primary · baseline 실측 교체(FIX 5, 01-multi_node-003)
- **csus3200_03** [ISSUE→PASS] composition count null True (FIX 6) · 링크 없는 섀시 경로 요청 0 (01-multi_node-006) · layout=rmc_primary · baseline 실측 교체(FIX 5, 01-multi_node-003)

## 2026-10-28 정정 (독립 검증 F-03 · §9 [WARN] · F-01)

| 칸 | 이전 근거 | 새 근거 | 판정 |
|---|---|---|---|
| dl380_gen12_01 system | 원천(RMC 이름 정책) | 원천(ComputerSystem `HostName`) — CSUS 칸 문구가 복사돼 있었다 | PASS (불변) |
| dl380_gen12_02 system | 원천(RMC 이름 정책) | 원천(ComputerSystem `HostName`) — CSUS 칸 문구가 복사돼 있었다 | PASS (불변) |
| dl380_gen12_03 system | 원천(RMC 이름 정책) | 원천(ComputerSystem `HostName`) — CSUS 칸 문구가 복사돼 있었다 | PASS (불변) |
| dl380_gen12_04 system | 원천(RMC 이름 정책) | 원천(ComputerSystem `HostName`) — CSUS 칸 문구가 복사돼 있었다 | PASS (불변) |
| sr650_v4_01 system | 원천(RMC 이름 정책) | 원천(ComputerSystem `HostName`) — CSUS 칸 문구가 복사돼 있었다 | PASS (불변) |
| sr650_v4_02 system | 원천(RMC 이름 정책) | 원천(ComputerSystem `HostName`) — CSUS 칸 문구가 복사돼 있었다 | PASS (불변) |
| sr650_v4_03 system | 원천(RMC 이름 정책) | 원천(ComputerSystem `HostName`) — CSUS 칸 문구가 복사돼 있었다 | PASS (불변) |
| sr650_v4_04 system | 원천(RMC 이름 정책) | 원천(ComputerSystem `HostName`) — CSUS 칸 문구가 복사돼 있었다 | PASS (불변) |
| dl380_gen12_03 network | 전원 Off notice 있음 · interfaces 4 | notice 에 '네트워크' 포함(새 Tier 1) · network 값 before = after | PASS (불변) |
| sr650_v4_01 network | (링크 값 언급 없음) | link 보충 4건(03-network-002, 2026-10-28 — 칸 판정 기준 밖) | PASS (불변) |
| sr650_v4_02 network | (링크 값 언급 없음) | link 보충 3건(03-network-002, 2026-10-28 — 칸 판정 기준 밖) · 링크 미확정 1 NIC 잔여(NIC6 — 03-network-002 HOLD) | PASS (불변) |
| sr650_v4_03 network | (링크 값 언급 없음) | link 보충 10건(03-network-002, 2026-10-28 — 칸 판정 기준 밖) | PASS (불변) |
| sr650_v4_04 network | (링크 값 언급 없음) | link 보충 3건(03-network-002, 2026-10-28 — 칸 판정 기준 밖) · 링크 미확정 1 NIC 잔여(NIC4 — 03-network-002 HOLD) | PASS (불변) |
