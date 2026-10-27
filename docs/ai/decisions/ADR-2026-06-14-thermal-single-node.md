# ADR-2026-06-14 — thermal 단일노드 수집 + thermal 섹션 신설 (Track 4)

- 상태: Accepted
- 일시: 2026-06-14
- 브랜치: feature/r740-audit-fixes
- 관련: ADR-2026-06-09-csus-model-completion (thermal 을 multi-chassis 전용으로 도입), rule 22 R2(7단계), rule 13 R5/R7

## 컨텍스트 (Why)

`gather_thermal` / `_gather_thermal_subsystem` 는 cycle 2026-06-09 에 구현됐으나 호출처가
`gather_chassis_multi`(multi_node, HPE CSUS/Superdome) **단 1곳**이었다. 단일노드(Dell/HPE/Lenovo
일반 fleet)는 `/Chassis/{id}/Thermal` 에 온도 센서·팬을 노출함에도 수집되지 않아 envelope 에 부재했다.

DELL R740 실 미러 검수(2026-06-14)에서 raw `/Chassis/System.Embedded.1/Thermal` 이 fan 6(5640~5880 RPM)
+ temp 4(CPU1 47°C / CPU2 42°C / Inlet 13°C / Exhaust 24°C)를 노출하나 envelope 미수집임을 확인(EXC-1).
schema 에 thermal 섹션이 없어 "거짓"은 아니나(설계 범위), 호출자가 온도/팬을 못 받는 한계.

## 결정 (What)

단일노드 dispatch(`_collect_all_sections`)에 `gather_thermal` 배선 + **새 schema 섹션 `thermal`** 신설.

- module: `_collect_all_sections` 에 `'thermal': _run('thermal', gather_thermal, …)` 추가 (gather_power 패턴).
- schema: `sections.yml` thermal(channels=[redfish], empty_value={temperatures:[],fans:[]}) +
  `field_dictionary.yml` thermal.temperatures[]/fans[] 7 entry + `supported_sections.yml`.
- normalize: `normalize_standard.yml` data.thermal passthrough(빈 dict 도 통일 shape) + _sections 매핑.
- envelope shape: 13 필드 불변(thermal 은 `data`/`sections` 내부 — rule 13 R5 Additive).
- 검증: replay(Dell temps 4 / fans 6 실값) + emulator/dmtf golden 6건 thermal-only 재생성(anti-laundering
  guard) + drift(sections=11) + validator + jinja compile + pytest 1097.

## 결과 (Impact)

- **Additive**: 기존 13 envelope 필드 / 10 섹션 path 변경 0. 미지원 벤더는 빈 `{temperatures:[],fans:[]}`.
- **channels=[redfish]**: os/esxi 는 thermal 미수집(향후 channel 확장 여지 — esxi 호스트 thermal 별도).
- **잔여(lab)**: redfish baseline(dell/hpe/lenovo/cisco/csus)에 thermal 섹션 부재 → 실장비 full 재캡처 필요
  (baseline 은 내 미러와 다른 device — 미러 thermal 직접 주입 금지, rule 13 R4). `docs/reference/compatibility-matrix.md` compatibility-matrix
  thermal 열 추가도 per-vendor 실측 후.
- drift check 는 baseline 의 섹션 누락을 informational 처리 → 미수집 baseline 으로도 offline gate 통과.

## 대안 비교 (Considered)

1. **(채택) 새 thermal 섹션**: 깔끔한 분리, 호출자 명시적. 단 전 baseline 재캡처 필요.
2. **data.power.fans/temperatures 병합**: 섹션 추가 회피하나 power 의미 확장 → 호출자 계약(power=PSU/전력)
   오염. 기각.
3. **단일노드 미수집 유지(설계 범위)**: 변경 0이나 호출자 온도/팬 영구 부재. 검수 EXC-1 미해결. 기각.

## 2026-10-27 정정 기록 (2차 Mock 실측 — 05-thermal-001/005)

- "미지원 벤더는 빈 `{temperatures:[],fans:[]}`" 문구: 2026-10-12 부터 Thermal · ThermalSubsystem 둘 다 404 면 `sections.thermal = not_supported` 다(`test_redfish_power_thermal_absent_not_supported.py`).
  2026-10-27 부터 섀시 본문에 두 링크가 없으면 요청 없이 같은 분류다. `_collect_all_sections` docstring 도 같이 정정했다.
- 센서 의미 보강(2026-10-27): `Status.State Absent` 센서 · 팬은 항목에서 제외하고 건수 notice 만 남긴다(iLO 7 미장착 슬롯 0 °C); `Enabled` 가 아니면 reading 은 null(전원 Off `UnavailableOffline`);
  음수 reading 은 스로틀 마진 센서(Lenovo DTS TMargin · CSUS THROT_OFFSET)라 그대로 보존한다 — 계약 6.7.
