# 03 — WP3 (C2): 전원 Off 호스트 · 빈 DIMM 슬롯 · Absent PSU placeholder · 비-Enabled 센서 reading

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027`. 실측 근거: 용인 2차 Mock DL380 Gen12 #03(호스트 PowerState **Off** 스냅샷 — Storage 멤버 0 · Memory 32 멤버 중 16 빈 슬롯 · PSU 2 Absent · 온도 42·팬 6 전부 UnavailableOffline 0) 과 #01/#02/#04 + 1차 DL380(전원 On, 미장착 슬롯 센서 Absent 7/8/8/9 건 0 °C).
- 이슈(ISSUES.md C2): **03-storage-001**(전원 Off 호스트 — storage/network 무신호 · (b) controllers 보강은 HOLD) · **02-memory-001**(빈 슬롯 16) · **05-power-001**(Absent PSU 0 W·"0.00") · **05-thermal-002**(UnavailableOffline 42/6) + C10 **05-thermal-001** 의 reading 부분(Absent 센서 0 °C → null; 항목 제외는 WP6). 04-firmware-009 는 OBSERVATION. 관측만 기록하고 인과 해석은 넣지 않는다(지시서 §2).

## 1. 규칙 (모듈 `redfish_gather.py`, 요청 0 · 전역 없음)

| # | 규칙 | 구현 | 실측 근거 |
|---|---|---|---|
| (a) | 호스트 `PowerState == Off` → notice 1건 "호스트 전원 Off 관측 — 저장/네트워크/메모리/전원/온도 인벤토리가 비어 있거나 placeholder 일 수 있음"(2026-10-28 '네트워크' 추가 — 6절). 섹션 status 불변 | `gather_system` 이 ComputerSystem 응답의 PowerState 를 기존 out dict(`bios_link_out`)에 기록 → `_collect_all_sections` 끝에서 1회 | dl380_gen12_03 `Systems/1.PowerState: Off` |
| (b) | Memory 멤버가 **Status 없음 ∧ CapacityMiB 0/None ∧ Manufacturer·PartNumber·SerialNumber 전부 비어 있음** → 빈 슬롯으로 제외 + notice "빈 DIMM 슬롯 N개 제외 (…)". 값이 하나라도 있으면 종전대로 보존(0 MiB 도 보존), `State=Absent` 는 종전 분기 | `gather_memory` | dl380_gen12_03 `Memory/proc1dimm11` 등 16건(DeviceLocator 만 있음) |
| (c) | `State=Absent` PSU 의 `PowerCapacityWatts 0` → null, `FirmwareVersion ""/"0.00"` → null (state·health 유지). Absent 가 아니면 불변. legacy `/Power` 의 PSU 합 폴백도 Absent 제외(신 경로 D-07 과 같은 규칙) | `_psu_absent_placeholders_to_none` — `gather_power`(legacy) · `_gather_power_subsystem`(신) 양쪽 | dl380_gen12_03 PSU ×2 `Absent / 0 / "0.00"`; gen12_01/02/04 PSU#2 `UnavailableOffline`(Absent 아님) 은 1600/"2.00" 그대로 |
| (d) | 온도·팬에 `Status.State` 가 있고 `Enabled` 가 아니면 reading → null (state·upper_critical 유지). **Status 가 없는 센서는 그대로**(CSUS ThermalMetrics 47~63건) | `_sensor_reading_if_enabled` — legacy Thermal temps/fans · ThermalSubsystem temps/fans; CSUS-R11 RPM join 은 Enabled(또는 Status 없음) 팬에만 | dl380_gen12_03 42/6 UnavailableOffline 0; gen12_01 Absent 7 건 0; `Enabled` 인데 0 인 센서 2건은 측정값으로 보존 |
| (e) | 전원 Off 에서 Storage 멤버 0 → 별도 처리 없음, (a) 문장이 맥락을 준다. placeholder 생성 0(`controllers []`, `fc_hbas []`) | — | dl380_gen12_03 `Systems/1/Storage Members 0` |

- 바꾸지 않은 것: `PowerControl[0].PowerCapacityWatts 1600`(BMC 가 준 값), `power_consumed_watts 0`, PSU 항목 자체(Absent 2건은 목록에 남아 state 로 보인다), `memory.total_mib`(빈 슬롯은 0 이었다). PCIeFunctions 보강은 HOLD(03-storage-001 (b) — 5절과 표기 통일, 2026-10-28).

## 2. 테스트

- 신규 `tests/unit/test_redfish_power_off_host.py`(17건): gen12_03 실녹화 재생(success 유지 · notice 1 · slots 16/total 불변 · PSU null · 42/6 reading null · storage 조작 0), gen12_01(Absent 7 만 null, PSU 불변, notice 없음), CSUS/Lenovo/Dell 3세트 GOLDEN_KEYS 불변, 합성 경계(PowerState 5값 · 빈 슬롯 3신호 전부 필요 · Absent/0/"0.00" 조합 · Status 없음/Enabled 0 보존 · 헬퍼 순수성).
- 기대값 갱신 2건: `test_redfish_bios_current.py`(out dict 에 `power_state` 키 추가 — 2 시험), `test_csus_mirror_audit_fixes.py::test_memory_present_capacity_unchanged`(합성 0 MiB DIMM 에 제조사를 둬 "식별된 DIMM 의 0 보존" 의도 유지 — 빈 슬롯 규칙과 경계는 신규 파일이 고정).
- 단위(power/thermal/memory/bios/phase2/csus audit + 신규) **130 passed** · `tests/integration -m "not live"` **496 passed** · 6 skipped(`tier0/pytest_integration_notlive_after_wp3.log` — real_* 재생·요청 예산·개수 정합·포트 불변식 포함) · `tests/e2e tests/regression` **1094 passed** · 12 skipped · 6 xfailed(`tier0/pytest_e2e_regression_after_wp3.log`).

## 3. Golden (FIX 9 — `golden-changes.md` G-04~G-08)

15 real_* fixture 전부 재생 → 바뀐 경로는 DL380 5세트의 다음뿐(CSUS 4 · Lenovo 5 · Dell 1 차이 0): gen12_03 slots 32→16 · PSU 2×(cap, fw) null · 온도 42·팬 6 reading null; gen12_01/02/04 · 1차 real_hpe_dl380 의 Absent 센서 7/8/8/9 reading 0→null(Enabled 49/36/46/43 불변). 요청 예산 불변.

## 4. Tier 1 after (DL380 5 label + 대조군 csus3200_02 · sr650_v4_01 · r1_DELL_R740_01, `tier1-after-WP3/` ↔ `tier1-after-WP2/`)

- 8 label `--build-id mirror-replay-wp3-after`: **8/8 rc 0 · success · errors 0**, 요청 집합 8 label 전부 불변(+0/-0).
- `_diff_vs_after_wp2.md`(허용목록 `_allow.json`): **허용목록 밖 차이 0**. 설명된 변화 — dl380_gen12_03 437 경로(`data.memory.slots` 32→16 인덱스 이동 ·
  `power_supplies[0..1].{power_capacity_w, firmware_version}` 0/"0.00"→null · `thermal.temperatures[0..41].reading_celsius`·`fans[0..5].reading` 0→null ·
  `diagnosis.details.notices` 0→2건: memory "빈 DIMM 슬롯 16개 제외 (…)", system "호스트 전원 Off 관측 — …"); dl380_gen12_01/02/04 · r1_HPE_DL380_01 은
  Absent 센서 `reading_celsius` 7/8/8/9 경로만(0→null). 대조군 csus3200_02 · sr650_v4_01 · r1_DELL_R740_01 은 바이트 동일.
- dl380_gen12_03 최종 봉투: `status success`(sections 는 종전과 같이 system/users 만 not_supported), `power.summary.psu_count 0`(종전부터 Absent 제외),
  `power_control.power_capacity_watts 1600`(BMC 값) 불변. 모듈 golden(GOLDEN_KEYS)과 최종 봉투가 같은 규칙으로 바뀌었다.

## 5. 처분

| 이슈 | 처분 | 근거 |
|---|---|---|
| 03-storage-001 (a) 전원 Off 신호 | FIXED(notice) | (a)·(e) — storage/network 에 placeholder 를 만들지 않고 system notice 로 맥락. 2026-10-28 정정(F-03): 종전 문구는 network 를 빼 network 맥락을 주지 못했다 → '네트워크' 추가. network 값은 종전과 같다 |
| 03-storage-001 (b) controllers 보강 | **HOLD** | 사용자 결정 필요(Plan §6) |
| 02-memory-001 | FIXED | (b), G-04 |
| 05-power-001 | FIXED | (c), G-05 — PSU 항목은 남고(state Absent) placeholder 값만 null |
| 05-thermal-002 | FIXED | (d), G-06 |
| 05-thermal-001 (reading 부분) | FIXED(부분) | (d), G-07~08 — Absent 항목 제외 + 건수 notice 는 WP6 |
| 04-firmware-009 | OBSERVATION_ONLY | 전원 Off 스냅샷의 `updateable` 은 raw 그대로 — 변경 없음 |

## 6. 2026-10-28 정정 (독립 검증 F-03 · 03-storage-001 (a))

- 원 이슈는 "storage/network 신호 없음", 분석 제안 문구는 "저장/네트워크 인벤토리가 비어 있을 수 있음" 인데 notice 문구가 network 를 뺐다. 그런데 132칸 dl380_gen12_03 network 칸을
  이 notice 를 근거로 ISSUE → PASS 로 올렸다(독립 검증 FAIL). 사용자 결정(2026-10-28 Q2)으로 문구에 '네트워크' 를 넣었다(`ac368a4b`) — 조건(PowerState Off) · section `system` · 건수는 그대로.
- 새 Tier 1(`../2026-10-28-redfish-mock2-review-fix/tier1-A`) dl380_gen12_03 notice: `호스트 전원 Off 관측 — 저장/네트워크/메모리/전원/온도 인벤토리가 비어 있거나 placeholder 일 수 있음` 1건, 다른 17 label 0건.
  network 값은 before = after(`interfaces` 4 · `ports` 4 — 어댑터 DA000004 · DA000007 각 2포트, link 전부 `unknown`). 같은 MAC 포트가 있어도 포트 link 가 `unknown` 이라
  F-01 보충(03-network-002)은 일어나지 않는다.

| 위치 | 이전 | 정정 |
|---|---|---|
| 1절 (a) notice 문구 | 저장/메모리/전원/온도 | 저장/네트워크/메모리/전원/온도 |
| 1절 아래 '바꾸지 않은 것' | PCIeFunctions 보강은 OBSERVATION | HOLD(03-storage-001 (b)) |
| 5절 03-storage-001 (a) 근거 | network 맥락이 있다고 적음 | 문구 정정 뒤에야 network 맥락 — network 값 불변 |
