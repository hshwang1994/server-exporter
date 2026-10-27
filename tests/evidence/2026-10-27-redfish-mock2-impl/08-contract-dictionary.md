# 08 — WP8 (C6): 계약 · 사전 · ADR 정정 묶음 + FIX 2 `cpu.manufacturer` + FIX 4 `sections.system` + `hardware.health` 폴백 (01-hardware-002 · 02-cpu-003/004/007 · 01-correlation-010 · 03-storage-002 · 04-firmware-007/011/012 · 04-bios-002 · 05-power-005/006 · 05-thermal-005 · 01-system-008/009 · 06-bmc-007 · 02-memory-005/006 · 04-firmware-008)

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027`. 범위: 스키마 키 변경 0(FIX 1 은 09 문서) — 사전 · 계약 · 예시 · ADR 정정 + Additive 코드 2건(`cpu.manufacturer` 발행, `hardware.health` Rollup 폴백). WP9(FIX 1) 와 같은 커밋 묶음(docs20 hook — 사전 변경 커밋에 `03-fields.md` 동반).

## 1. 코드 (Additive 2건 — 제품)

| 이슈 | 규칙 | 구현 |
|---|---|---|
| 02-cpu-003 (FIX 2) | `cpu.manufacturer` = 첫 CPU `Processor.Manufacturer` 를 OS/ESXi 와 같은 표로 정규화: 소문자에 `intel` → `Intel`, `amd` 또는 `advanced micro devices` → `AMD`(DMTF mockup · iDRAC AMD 는 회사 전체 이름 `Advanced Micro Devices, Inc.` — `amd` 부분 문자열이 없다), 그 밖 원문 strip, 없으면 null. `cpu.summary.groups[].manufacturer` 도 같은 표(종전 원문 `Intel(R) Corporation`). 모듈 raw 는 그대로 | `normalize_standard.yml` cpu 블록 `manufacturer` + `_rf_summary_cpu` 루프(내장 Jinja 만, namespace 재대입 없음) |
| 01-hardware-002 | `hardware.health` = `System.Status.Health` 원값, **없을 때만**(`None`/`''`) `HealthRollup` — memory_summary · cpu_summary 와 같은 패턴. 값이 있으면 그대로(1차 SR650 Health `Warning` · Rollup `OK` → `Warning`) | `redfish_gather.py` `gather_system` result `health` |
| 05-thermal-005 (a) | `_collect_all_sections` docstring "미지원 시 {} graceful (collected)" → "둘 다 404 면 `sections.thermal = not_supported`(2026-10-12)" | docstring 만 |

- 18 label 영향: `cpu.manufacturer` 18 label 전부 `Intel`(iDRAC raw `Intel`, 그 밖 `Intel(R) Corporation`), `groups[].manufacturer` 17 label `Intel(R) Corporation → Intel`(Dell 은 이미 `Intel`). `hardware.health` 는 15 fixture · 18 label 전부 `Status.Health` 가 있어 **값 불변**(폴백 미발동 — 합성 테스트만).

## 2. 사전 (`schema/field_dictionary.yml` 247 → 261 항목 = +53 신규 · 정정 10 · 채널 제거 2 · `cpu.logical_threads` channel [os, esxi])

| 구분 | 항목 |
|---|---|
| 신규 cpu (02-cpu-007) | `cpu.sockets`(must) · `cpu.model`(must) · `cpu.logical_threads`(must, **[os, esxi]** — FIX 1) |
| 신규 power/thermal (05-power-006) 34 | `power.power_supplies[]` + 하위 8(name · model · serial · manufacturer · part_number · power_capacity_w · firmware_version · health; `state` 는 기존) · `power.power_control` + 6(power_consumed_watts must · power_capacity_watts · interval_in_min · min/avg/max_consumed_watts) · `power.summary` + 12 · `thermal.temperatures[].name/health/state` · `thermal.fans[].name/health/state` |
| 신규 correlation (01-correlation-010) | `correlation.bmc_ip`(must — "Manager EthernetInterfaces 중 IPv4 를 가진 첫 NIC, host_ip 와 다를 수 있음, OS/ESXi null") |
| 신규 multi_node (FIX 6 · 06-09 ADR) 5 | `multi_node.composition`(object\|null) · `.resource_blocks[]` · `.processor_count`/`.memory_count`(integer\|null — 원천 없으면 null) · `multi_node.fabrics`(object[]\|null); `multi_node.summary` help 에 resource_block_count · fabric_count |
| 신규 diagnosis.details (06-bmc-007) 10 | `channel` · `checked_ports` · `selected_port`(3채널) · `adapter_candidate`(3채널) · `adapter_first_pass` · `auth` · `product` · `redfish_version` · `systems_uri` · **`account_service`(`{}` = 정합 단계 미진입 — 정상 경로, 18 label 전부)** |
| 정정 | `cpu.manufacturer`(Redfish 원천 · 표) · `cpu.summary`(LPC 규칙 → FIX 1/2) · `cpu.architecture`(채널별 어휘 `x86` vs `x86_64` — 02-cpu-004, 통일은 결정 항목) · `hardware.health`(원천 `Status.Health`, "BMC rollup" 삭제, PSU 등급은 벤더 결정) · `storage.controllers[].driver`(channel redfish 제거 — 03-storage-002) · `firmware[].updateable`(`boolean\|null` — 04-firmware-007) · `firmware[].category`(구조 근거 → 토큰 → 조인, FC HBA other) · `firmware[].pending`(Disabled · Version 없음 제외) · `bmc.uuid`(ServiceIdentification 삭제) · `bmc.datetime`(오프셋/UTC 형식 · 비교 키 아님) |
| schema/fields | `common.yml` 의 `cpu.logical_threads` → `os.yml` · `esxi.yml` `cpu.extra_fields` 로 이동(문서 전용 파일 — 프로그램 소비처 0) · `redfish.yml` firmware item_fields 에 `category` · `pending` |
| sections.yml | `network.empty_value` 의 `bonds`/`bridges`/`teams` 가 OS 전용 키라는 **주석 각주**만(관찰 O-11, 스키마 변경 0) |

- 검증: `tests/validate_field_dictionary.py` PASS(261 entries · 중복 0 · ko/en 전부 · channel 유효; "schema examples 에 없음" 경고는 종전과 같은 성격) · `scripts/ai/hooks/output_schema_drift_check.py` 정합(sections 11 · prefix 19) · `envelope_change_check.py` advisory 4건은 기존 `diagnosis.auth_success`/`failure_*` 키를 사전 diff 에서 오탐한 것 — 봉투 키 변경 0, 보고 파일(gitignore 대상)은 정리.

## 3. 계약 문서 (`docs/contract/03-fields.md`)

| 절 | 변경 |
|---|---|
| §1 서사 | "PSU 1대 fault → Critical" 을 iDRAC 사례로 한정(등급은 벤더가 정함) |
| §3 표 각주 | **FIX 4 (01-system-008)**: Redfish `sections.system = not_supported` 유지 + `data.system.hostname/fqdn` 은 채워짐 — HostOS 승격 안 함 |
| §5 diagnosis | Redfish `details` 키 전체 표 + `account_service {}` 의 뜻(06-bmc-007) |
| 6.1 hardware | `health` 원천 `Status.Health`(없을 때만 Rollup) · DMTF Health/HealthRollup 차이 · iLO 7 Warning vs Oem Critical · XCC 3 Critical(01-hardware-002) |
| 6.2 memory | 2026-10-19 (3) 의 LPC 문장 → FIX 1(Redfish 미발행 · 근거) + FIX 2(manufacturer 표) + 02-cpu-004 어휘 |
| 6.5 power | "PSU 한 대 fault → Critical" 정정(05-thermal-005 b) · 입력 0 관측 notice(05-power-002) · `power_capacity_watts` 벤더별 뜻(05-power-005) · 소비전력 원천 순서(05-power-007) · 하위 키 등재(05-power-006) |
| 6.7 thermal | "빈 {} graceful" → 둘 다 404 = not_supported(05-thermal-005 a) · Absent 제외 · 상태별 reading null · 음수 reading 은 마진 센서(05-thermal-001/004) · ThermalSubsystem 이름/RPM 폴백(05-thermal-003) |
| 6.8 bios | 식별 정보 포함 가능 1줄(04-bios-002) |
| **6.9 `data.firmware` 신설** (04-firmware-012) | 키 7개 · category 규칙(구조 → 토큰 → 조인, enum 고정, FC HBA other) · pending(Disabled·Version 없음 제외) · updateable null · Dell dedup(04-firmware-008 관찰) · CSUS 보충 + `bios_version == bmc.firmware_version`(04-firmware-011) · 전원 Off |
| §7 FAQ | `bmc_ip` 정의("보통 같지만 다를 수 있다", OS/ESXi null — 01-correlation-010) |
| §8 hostname | CSUS `hostname_source=system` 이어도 RMC 이름(공장 기본명 가능) — 01-system-009 |
| §9 multi_node | FIX 6 count null(WP7 에서 반영) |

- 그 밖 문서: `docs/develop/05-field-mapping.md`(Redfish cpu 변화 1줄) · `docs/ai/contracts/serial-number.md`(data.cpu 키 목록) · `EXTERNAL_CONTRACTS.md`(LPC 행 정정 + Processor.Manufacturer · Status.Health 행 2026-10-27 절) · `CONVENTION_DRIFT.md` DRIFT-031(resolved) · `decision-log.md`(2026-10-27 절 + 색인 + 2026-10-18 표 행 정정 + 2026-10-19 표 행 각주) · `NEXT_ACTIONS.md`(3줄).

## 4. ADR 정정 기록 (원문 미수정 — 끝에 "2026-10-27 정정 기록" 절 append)

| ADR | 기록 |
|---|---|
| ADR-2026-10-18 (HBA link null · 채널 간 값) | 결정 4 의 `logical_threads` 부분 → FIX 1 로 대체; :11/:29 FC 링크 원천 문구 보강(카드 단위 `H3Alert` 조건 — 결정 11 A안; null → down 은 10-19 ADR) |
| ADR-2026-10-19 (CSUS 단일 서버 · summary) | 결정 3 · A-2 · 대안 비교 → FIX 1(플래그 삭제 · RMC 1.77 의미 변화); A-9 category/updateable; A-11 gating; 결정 4/6/7/8 유지 + FIX 6 |
| ADR-2026-06-09 (CSUS 모델 검수) | 집합 섀시 Power/Thermal 가정 → 링크 gating; ResourceBlock Processors/Memory 부재 → null; C9/C11 확인 · C10 미해결 |
| ADR-2026-05-12 (RMC 멀티노드) | 결정 6(baseline) 미이행 → FIX 5 는 WP11 뒤; 외부 계약 추정 정정(composition · DIMM 클럭 · LPC) |
| ADR-2026-06-14 (thermal 단일노드) | "빈 {}" → not_supported; Absent 제외 · reading null · 음수 마진 |
| ADR-2026-10-15 (CSUS hostname) | 2차 3대 재확인 · `hostname_source=system` 문구 · FIX 4 |

## 5. 테스트 (Tier 0)

- `tests/unit/test_cross_channel_value_fixes.py` FIX 2 4건(표 7케이스 · 키 없음 · groups 표) · `tests/unit/test_redfish_hardware_health_fallback.py` 8케이스(실측 3 + 합성 5) · `tests/unit/test_field_dictionary_channel_emit.py` +2("redfish 선언 cpu 키는 전부 발행" · `controllers[].driver` channel). 묶음 실행 **281 passed**(value_fixes 39) · integration 497 · e2e/regression 1094 · WSL syntax 3채널 · 엔진 23 · unit 전체 **5127 passed · 33 skipped · 0 failed**(23분 5초).

## 6. Tier 1 after (18 label, `tier1-after-WP9/` ↔ `tier1-after-WP7/`)

- 18/18 rc 0 · success · errors 0 (build `mirror-replay-wp9-after`), **요청 집합 불변**(18 label +0/-0). `_diff_vs_after_wp7.md`(허용목록 4항목): **허용목록 밖 차이 0**.
- `data.cpu.manufacturer` 18 label 전부 `Intel`(iDRAC raw `Intel`, 나머지 17 `Intel(R) Corporation`), `cpu.summary.groups[0].manufacturer` 17 label `Intel(R) Corporation → Intel`(Dell 불변). `sockets` · `cores_physical` 18 label 불변.
- `hardware.health` 18 label **값 불변**(OK 10 · Warning 5 · Critical 4 — 폴백 미발동). `status` · `sections` 불변. INV-5 위반 0 · interfaces 수 불변. 디스크·FC 개수 정합 18/18 PASS · UNEXPLAINED 0.

## 7. 처분

| 이슈 | 처분 |
|---|---|
| 01-hardware-002 | FIXED (Rollup 폴백 — 18 label 값 불변) + DOC_CORRECTED |
| 02-cpu-003 | FIXED (FIX 2) |
| 02-cpu-004 | DOC_CORRECTED (채널별 어휘 명시 — 표기 통일은 결정 항목) |
| 02-cpu-007 · 05-power-005 · 05-power-006 · 03-storage-002 · 04-firmware-007 · 04-firmware-011 · 04-firmware-012 · 01-correlation-010 · 05-thermal-005 · 01-system-009 · 06-bmc-007 | DOC_CORRECTED |
| 01-system-008 | DOC_CORRECTED (FIX 4 — 섹션 판정 불변) |
| 04-bios-002 · 04-firmware-008 · 02-memory-005 · 02-memory-006 | OBSERVATION_ONLY (6.8 1줄 · 6.9 1줄 기재) |
