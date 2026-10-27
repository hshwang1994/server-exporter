# 06 — WP6 (C10): 전원·온도 의미 (05-thermal-001/003 · 05-power-002/007 · 05-thermal-004 관찰)

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027`. 실측: DL380 Gen12 #01/02/04 + 1차 DL380(미장착 슬롯 센서 `Absent` 7/8/8/9건 0 °C), gen12_01/02/04 PSU#2 `UnavailableOffline`·`LineInputVoltage 0`, SR650 V4 PSU1 `PowerInputWatts 0`(Health Critical), CSUS ThermalMetrics(Status 없음).

## 1. 규칙 (모듈, 요청 0 · 관측만)

| 이슈 | 규칙 | 구현 |
|---|---|---|
| 05-thermal-001 | `Status.State == Absent` 온도 센서/팬은 **항목을 두지 않는다** + notice 1건 "Absent 센서 N건 제외 (온도 n · 팬 m) — 미장착 슬롯". Status 없음(CSUS)·UnavailableOffline(전원 Off)은 Absent 가 아니다(WP3 규칙으로 reading null) | `_sensor_is_absent` · `_notice_absent_sensors` — legacy `/Thermal` 와 `ThermalSubsystem` 양쪽 |
| 05-power-002 | PSU 의 입력 전력/전압 **키가 있고 값이 0** 이면 관측 notice 1건 "전원 공급 장치 <Name>[<MemberId>]: 입력 전력 0 W / 입력 전압 0 V 관측". 키 없음·null 은 무시, Absent 슬롯 제외. `psu_active`·`state` 불변, "AC 입력 없음" 같은 인과는 적지 않는다(03-fields 6.5 로) | `_psu_zero_input_notice` — legacy(`LineInputVoltage`·`PowerInputWatts`) · 신 경로(`Metrics.InputPowerWatts/InputVoltage.Reading`) |
| 05-power-007 | 소비전력 폴백 순서 **EnvironmentMetrics → TelemetryService → PSU `Metrics.OutputPowerWatts` 합(DC 출력) → PSU `Metrics.InputPowerWatts` 합(AC 입력)**. "~24% 높음" 주석은 1대 1시점 비교였으므로 정의 차이만 남김 | `_gather_power_subsystem` |
| 05-thermal-003 | ThermalSubsystem: 이름 폴백 `DeviceName → Name → DataSourceUri 마지막 세그먼트`; 팬 `SpeedPercent.Reading` 없고 `SpeedPercent.SpeedRPM` 있으면 RPM. 18 label 미발동 — 합성 fixture 만 | `_gather_thermal_subsystem` |
| 05-thermal-004 | 음수 "온도"(Lenovo `CPUn DTS TMargin`, CSUS `P*_THROT_OFFSET`) — **OBSERVATION_ONLY**, 값 보존(계약 6.7 각주는 WP8) | 변경 0 |

## 2. 테스트

- 신규 `tests/unit/test_redfish_thermal_power_meaning.py`(10건): DL380 4세트 Absent 제외 건수·notice, gen12_03/CSUS 비발동, 입력 0 관측(gen12_01 0 V · sr650_v4_01 0 W · gen12_03 Absent 제외 · Dell 없음), 합성(키 유무 5케이스 · 출력/입력 합 폴백 · 0 입력 신 경로 · DataSourceUri/SpeedRPM/Absent 팬 · 헬퍼).
- WP3 시험 2건을 WP6 의미(Absent 항목 제외)로 갱신. 단위 묶음(thermal/power/xcc3/csus/multi_node/phase2) 130 passed → 재실행 28 passed(갱신 2 파일) · `tests/integration -m "not live"` **497 passed** · `tests/e2e tests/regression` **1094 passed**(`tier0/*_after_wp6.log`).

## 3. Golden (FIX 9 — `golden-changes.md` G-14)

DL380 4세트 `data.thermal.temperatures[]` 52·56·44·54 → **43·49·36·46**(Absent 항목 제외, 그 밖 값 불변). 다른 11 fixture 차이 0, 요청 예산 불변.

## 4. Tier 1 after (18 label, `tier1-after-WP6/` ↔ `tier1-after-WP5/`)

- 18/18 rc 0 · success · errors 0, 요청 집합 불변. `_diff_vs_after_wp5.md`(허용목록): **허용목록 밖 차이 0**.
- DL380 4 label(gen12_01/02/04 · 1차): `data.thermal.temperatures[]` Absent 7/8/8/9 항목 제외(인덱스 이동) + notice "Absent 센서 N건 제외 (온도 N · 팬 0) — 미장착 슬롯".
- PSU 입력 0 관측 notice: gen12_01/02/04 "전원 공급 장치 HpeServerPowerSupply[1]: 입력 전압 0 V 관측"(PSU#2 UnavailableOffline), sr650_v4_01..04 "전원 공급 장치 PSU1[0]: 입력 전력 0 W 관측"(PSU1 Health Critical). 1차 DL380·Lenovo·Dell·CSUS·gen12_03(Absent PSU) 은 없음.
- `power_control.power_consumed_watts` 18 label 전부 불변(CSUS 는 TelemetryService 값이 먼저라 출력 합 폴백 미발동: 903/815/867 · 591/600/1000/945) — 폴백 순서 변경은 값에 닿지 않았다.
- CSUS 7 · Dell · gen12_03 · r1_Lenovo 는 바이트 동일.

## 5. 처분

| 이슈 | 처분 |
|---|---|
| 05-thermal-001 | FIXED (Absent 항목 제외 + 건수 notice; WP3 의 reading null 규칙과 합쳐 완료) |
| 05-power-002 | FIXED (관측 notice — 인과 해석 없음) |
| 05-power-007 | FIXED (폴백 순서 · 주석 정정; 18 label 소비전력 값 불변) |
| 05-thermal-003 | FIXED (합성 검증 — 실장비 미발동) |
| 05-thermal-004 | OBSERVATION_ONLY |
