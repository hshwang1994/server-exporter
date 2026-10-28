# 05 — WP5 (C4): Lenovo XCC3 응답 모양 (03-network-001/002 · 04-firmware-006 · 05-power-003 · 02-memory-003 · hardware.oem · 03-network-005)

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027`. 실측: 용인 2차 SR650 V4 ×4(XCC3 IHX438R 2.97) + 1차 SR650 V4(IHX414J 1.22). 사용자 3차 지시의 명시 회귀(i)(ii)(iii) 포함.

## 1. 규칙과 구현

| 이슈 | 규칙 | 구현 위치 | 실측 근거 |
|---|---|---|---|
| 03-network-001 | 호스트 EthernetInterfaces 중 주소가 **8옥텟**이거나 `network_adapters.ports[]` 의 **FC/IB 포트 주소와 같은** 항목은 `network.interfaces` 에서 제외 + normalize notice 1건. 모듈 raw(`data.network`)·`ports[]`·`hbas[]` 는 그대로 | `normalize_standard.yml` `_rf_norm_interfaces_bundle`(제외 수 포함) → `_rf_norm_interfaces`·`_rf_norm_notices`; `site.yml` 봉투 notices = 모듈 notices + normalize notices(2곳) | sr650_v4_02/03: NIC3/4/7/8 `21:00:f4:c7:aa:a4:6f:fe` 등 = `hbas[].wwpn`; v4_01/04·1차·HPE·CSUS·Dell 은 제외 0 |
| 03-network-002 | NIC 자체 `link_status` 가 unknown 이면 MAC 이 같은 **Ethernet 포트들**의 `link_status` 가 하나의 값(up/down)으로 일치할 때만 보충, `speed_mbps` 는 그 경우 NIC 값이 null 이고 포트 속도가 하나로 일치할 때만 보충. NIC 자체 값은 덮지 않음(**2026-10-28 정정** — 종전 규칙 `link_status unknown ∧ speed_mbps null` 은 6절) | 같은 템플릿(`eth_ports` MAC → 포트 목록 색인, 2026-10-28) | Tier 1 18 label 보충 건수는 3절 표 |
| 04-firmware-006 | `Status.State == Disabled ∧ Version 비어 있음` 인 멤버(XCC3 `-Pending` 빈 스테이징 슬롯) 제외 + notice. Version 이 있으면 종전대로 `pending: true` | `gather_firmware` | 5 label: BMC-Primary/HPM-FPGA/UEFI/PSoC `-Pending` (1차 2건, 2차 4건씩) `Disabled · Version ""` |
| 05-power-003 | PSU `model/serial/manufacturer/part_number` 양끝 공백 제거(비면 null) — legacy `/Power` · `PowerSubsystem` 양쪽 | `gather_power` · `_gather_power_subsystem` | `'CRPS1300D5    '` |
| 02-memory-003 | locator 순서 `DeviceLocator → Location.PartLocation.ServiceLabel → str(MemoryLocation.Slot)` (문자열 계약 유지) | `gather_memory` | Lenovo `ServiceLabel "DIMM 23"` vs Slot 23; Dell/iLO(DeviceLocator)·CSUS(Slot 0) 불변 |
| hardware.oem (Lenovo) | chassis OEM 에 `MachineType`/`LEDIndicators` 가 없으면 `System.SubModel`('7DGD')·`System.IndicatorLED`('Off') | `_extract_oem_lenovo` | XCC3 Chassis.Oem.Lenovo 에 두 키 없음(ProductName·FruPartNumber 등만) |
| 03-network-005 (`ToManager`) | **OBSERVATION_ONLY** — 모듈이 `Links.HostInterface` 를 내지 않아 키 추가 없이는 식별 불가 | 변경 0 | — |

- 다른 벤더 영향: 제외 규칙은 주소 형식·포트 주소 일치로만 판정(벤더 이름 분기 없음) — DL380/CSUS/Dell 의 EthernetInterfaces 는 6옥텟이라 제외 0. 보충 규칙은 NIC 링크가 unknown 인 NIC 에만(2026-10-28 정정 — 종전 'unknown∧null').
- `test_csus_mirror_audit_fixes.py` locator 기대값 2건 갱신(ServiceLabel 우선 — LOCATOR-STR 재검토: 문자열 계약은 유지, id 와의 일치는 더 이상 요구하지 않음).

## 2. 테스트

- 신규 `tests/unit/test_redfish_xcc3_shape.py`(26건): 번들 템플릿 렌더(v4_02 9→5, notice 1; v4_03 15→11; 제외 0 label 들), 주소 규칙 합성(8옥텟·IB 주소·보충 조건), **(i)** NDF 200·0건인 FC 카드에서 hbas 4·FC 포트 4(개수 정합 판별기 교차), **(ii)** 장치 없는 장비의 `[]`(csus3200_02 FC 0 · gen12_03 디스크 0 · 1차 CSUS 디스크 0), **(iii)** 제외가 ports/hbas 수를 바꾸지 않음, -Pending 2분기(실녹화 4건 제외 + 합성), PSU strip 양 경로, locator 5케이스, oem 원천.
- `test_port_classification_invariants.py` **INV-5**(baseline 전수 + 자기 시험) 추가.
- 단위·통합 묶음 470 passed(xcc3·csus audit·summary·single server·port invariants·category·power-off·bios·real capture replay·request budget·inventory parity) · `tests/integration -m "not live"` **497 passed** · 6 skipped(`tier0/pytest_integration_notlive_after_wp5b.log`; 첫 실행 `_after_wp5.log` 은 DMTF mockup golden 의 locator 3건(G-13) 때문에 1 failed → 근거 확인 뒤 갱신하고 재실행) · `tests/e2e tests/regression` **1094 passed** · 12 skipped · 6 xfailed(`tier0/pytest_e2e_regression_after_wp5.log`) · syntax-check 3/3(`tier0/syntax_check_wsl_after_wp5.log`).

## 3. Golden (FIX 9 — `golden-changes.md` G-09~G-12)

Lenovo 5세트만: firmware 26·28·30·40·30 → 24·24·26·36·26(빈 -Pending 제외), locator `"23"` → `"DIMM 23"`(16·2·2·16·8건), PSU model strip(v4 ×4), oem machine_type/led_indicator `7DGD`/`Off`. CSUS 4 · DL380 5 · Dell 1 차이 0, 요청 예산 불변.

## 4. Tier 1 after (18 label, `tier1-after-WP5/` ↔ `tier1-after-WP4/`)

- 18/18 rc 0 · success · errors 0, 요청 집합 18 label 불변. `_diff_vs_after_wp4.md`(허용목록 `_allow.json`): **허용목록 밖 차이 0**. CSUS 7 · dl380_gen12_03/04 · Dell 은 바이트 동일.
- **Lenovo 5 label**(147~279 경로): `data.firmware[]` -Pending 제외(인덱스 이동), `memory.slots[*].locator` ServiceLabel, `power_supplies[*].model` strip(v4), `hardware.oem.machine_type/led_indicator`,
  sr650_v4_02 `network.interfaces` **9→5** · v4_03 **15→11**(FC 4건 제외) + `network.summary`(port_count/groups), notices +(firmware 4·network 1).
- **03-network-002 보충**(`_inv5_and_link_fill.md`): dl380_gen12_01 NIC 6건 · gen12_02 6건 · r1_HPE_DL380_01 4건 — `link_status unknown → down`(같은 MAC 의 NetworkPort `LinkStatus`), speed 는 포트도 null 이라 그대로.
  그 밖 label 보충 0. **2026-10-28 정정(독립 검증 F-01)**: 종전 사유 '값이 이미 있거나 같은 MAC 포트 없음' 은 SR650 V4 에 대해 틀렸다 — SR650 V4 호스트 NIC 은 `LinkStatus` 가 없고
  `SpeedMbps`(25600 · 0)가 있어 종전 조건(`speed null`)이 거짓이었다. 같은 MAC 의 Ethernet 포트 `LinkStatus`(LinkUp/LinkDown)가 있는데도 보충되지 않았다(6절).
- **INV-5**(interfaces MAC 6옥텟 ∧ FC/IB 포트 주소 아님): 18 label 위반 **0** (before 는 sr650_v4_02/03 이 각 4건 위반이었다).

## 5. 처분

| 이슈 | 처분 |
|---|---|
| 03-network-001 | FIXED (normalize 제외 + notice, 모듈 raw 보존) |
| 03-network-002 | FIXED(부분 — 2026-10-28 규칙 정정 뒤 SR650 V4 20건 + DL380 3대 16건) + HOLD(잔여 2 NIC — 6절) |
| 04-firmware-006 | FIXED |
| 05-power-003 | FIXED |
| 02-memory-003 | FIXED |
| hardware.oem (Lenovo 2키) | FIXED |
| 03-network-005 | OBSERVATION_ONLY |

## 6. 2026-10-28 정정 (독립 검증 F-01 · 03-network-002)

- 독립 검증(`f92ebe6a` 대상)이 SR650 V4 4대의 NIC `link_status` 가 같은 MAC 의 포트가 `up` 인데도 전부 `unknown` 임을 찾았다(FIXED 과대 표기). 원인은 4절의 보충 조건
  `link == 'unknown' and speed is none`(분석 제안 문장을 그대로 옮김)과, `eth_ports` 가 MAC 당 포트 1개라 같은 MAC 포트 2개 중 앞 포트를 덮은 것이다.
- 정정(`db606f1c`, 브랜치 `fix/redfish-mock2-review-20261028`): NIC 자체 링크가 없을 때만 같은 MAC 포트들의 링크가 하나로 일치하면 그 값, 다르거나 짝이 없으면 `unknown` 그대로.
  NIC 자체 값은 덮지 않고 HBA 의 down 정책은 쓰지 않는다. 속도는 종전과 같은 범위(NIC 링크 unknown · NIC 속도 null · 포트 속도 일치)만 채운다.
- 결과(새 Tier 1 18 label — `../2026-10-28-redfish-mock2-review-fix/tier1-A`): SR650 V4 `interfaces[].link_status` unknown → up 14 · down 6 = 20건, `is_primary` 4건 false → true, summary `link_up_count` ·
  `primary_speed_mbps` 파생 변화. DL380 3 label 16건 · 그 밖 label 은 값 변화 0. 상세: `../2026-10-28-redfish-mock2-review-fix/01-f01-nic-link-fill.md`.
- **미해결(HOLD)**: sr650_v4_02 `NIC6` · sr650_v4_04 `NIC4` 는 본딩 영구 주소 NIC 이라 포트 출력(`associated_address` = `AssociatedMACAddresses[0]`)에 그 MAC 이 없어 `unknown` 으로 남는다.
  원문에는 NDF `PermanentMACAddress` → `PhysicalNetworkPortAssignment` → 포트 `LinkUp` 연결이 있으나 쓰려면 모듈 출력을 바꿔야 해서 별도 승인 대상이다. NIC `SpeedMbps` 로 링크를 추측하지 않는다.

| 위치 | 이전 | 정정 |
|---|---|---|
| 1절 03-network-002 규칙 | `link_status unknown ∧ speed_mbps null` 인 NIC 만 보충 | NIC 링크 unknown 이면 같은 MAC 포트들 링크 일치 시 보충, NIC 값 불변 |
| 1절 다른 벤더 영향 | 보충 규칙은 unknown∧null 인 NIC 에만 | NIC 링크가 unknown 인 NIC 에만 |
| 4절 보충 0 사유 | 값이 이미 있거나 같은 MAC 포트 없음 | SR650 V4 는 `SpeedMbps` 가 있어 종전 조건이 거짓이었음 |
| 5절 처분 | FIXED | FIXED(부분) + HOLD(잔여 2 NIC) |
