# 01 — 호스트 NIC 링크를 같은 MAC 포트 값으로 보충 (F-01 · 03-network-002, 부분 해결)

- 날짜 2026-10-28 · 브랜치 `fix/redfish-mock2-review-20261028` · 코드 `db606f1c`(`redfish-gather/tasks/normalize_standard.yml` interfaces 번들 — `no_log: true` · fragment 경계 그대로).
- 판정: **부분 해결.** SR650 V4 4대에서 20건이 보충됐고, sr650_v4_02 `NIC6` · sr650_v4_04 `NIC4` 2건은 미해결(HOLD — 값 `unknown` 유지)이다(5절).
- 실장비 검증 아님 — 근거는 2차 Mock 미러(실장비 캡처본) Tier 1 재생과 합성 · fixture 렌더 시험이다.

## 1. 독립 검증이 찾은 것

`f92ebe6a` 의 처분은 FIXED 였지만 SR650 V4 4대의 호스트 NIC `link_status` 는 같은 MAC 의 포트가 LinkUp/LinkDown 인데도 전부 `unknown` 이었다. 보충은 DL380 Gen12 3대 16건에서만 일어났다.

| 원인 | 내용 |
|---|---|
| 보충 조건 | `link == 'unknown' and speed is none` — 분석 제안 문장을 그대로 옮긴 조건. SR650 V4 호스트 NIC(`Systems/1/EthernetInterfaces/NICn`)는 `LinkStatus` 키가 없고 `SpeedMbps`(25600 · 0)가 있어 조건이 거짓이었다 |
| MAC 색인 | `ns.eth_ports` 가 MAC → 포트 1개 dict 라 같은 MAC 이 포트 2개에 걸리면(sr650_v4_02 · _04 의 NIC2) 나중 포트가 앞 포트를 덮었다 |
| 놓친 이유 | 구현 · 합성 시험(speed null NIC 만 사용) · evidence 05 가 같은 조건을 따랐고, 132칸은 03-network-001 기준(interfaces 수 · FC 혼입)으로만 판정해 링크 값이 칸 통계에 드러나지 않았다 |

## 2. 규칙 (변경 전 → 후)

| | 변경 전 (`f92ebe6a`) | 변경 후 (`db606f1c`) |
|---|---|---|
| 포트 색인 | MAC → 포트 1개 | MAC → 포트 목록(같은 MAC 포트 전부) |
| link 보충 | NIC link unknown **이고 NIC speed null** 일 때 그 포트 값 | NIC link unknown 이면, 같은 MAC 포트들의 `link_status` 가 **하나의 값(up/down)으로 일치할 때만** 그 값 |
| speed 보충 | 위 조건에서 포트 속도 | 같은 분기 안에서 NIC speed 가 null 이고 포트 속도가 하나로 일치할 때만 |
| 그 밖 | — | NIC 자체 값은 덮지 않는다. 포트끼리 다르거나 짝이 없으면 `unknown` 그대로 — HBA 의 down 정책을 쓰지 않는다. 원천은 `data.network.ports[].link_status`(모듈의 네트워크 정규화 결과) |

- 대상은 전부 Ethernet NIC(6옥텟 MAC)이다. FC 8옥텟 항목은 03-network-001 이 interfaces 에서 이미 뺐다.
- `is_primary` 는 바뀐 link 에서 파생된다(첫 up NIC). `summary.groups[].link_up_count` · `summary.primary_speed_mbps` 도 interfaces 에서 파생된다.
- **계획서(2026-10-28 승인본 §5.1)와 다른 점 — speed 보충 범위**: 계획서 초안은 speed 보충을 link 분기 밖의 별도 조건(`speed is none`, 포트 속도에서 null 제외)으로 적었다.
  15 fixture golden 렌더 시뮬레이션에서 그 형태는 NIC 자체 link 가 이미 `up` 인 DL380 iLO NIC 16개에 speed 25000 을 새로 채웠다 — 계획서가 예상한 변화(speed 변화 0)에도 범위(기능 개선 제외)에도 없는 변화다.
  그래서 speed 보충은 종전처럼 link `unknown` 분기 안에 두고, 포트 속도는 null 까지 포함해 하나로 일치할 때만 쓴다. 새 Tier 1 로 다시 센 해당 NIC: dl380_gen12_01 4(Id 78 · 269 · 333 · 462) · dl380_gen12_02 2(141 · 333) · dl380_gen12_04 8 · r1_HPE_DL380_01 2(13 · 205) = 16, 전부 같은 MAC 포트 `current_link_speed_mbps` 25000 — 값은 `null` 그대로다. 채울지는 후속 결정 [INFO].

## 3. 결과 — 새 Tier 1(`tier1-A`, 18 label) 대 구현 측 `tier1-final`

`tools/tier1_explained.py` → `tier1-A/_explained_vs_final.md`: 설명된 차이 34 · 설명되지 않은 차이 0 · 요청 집합 차이 0. 허용 목록 `tier1-A/_allow.json`(3 항목).

| label | NIC | MAC | link | 원천(같은 MAC `ports[]` — adapter/port · link · 속도) | is_primary |
|---|---|---|---|---|---|
| sr650_v4_01 | NIC1 | ec:e7:a7:22:59:5d | unknown → down | slot13_0x170000/2 down | |
| sr650_v4_01 | NIC2 | ec:e7:a7:22:59:5c | unknown → up | slot13_0x170000/1 up 25000 | false → true |
| sr650_v4_01 | NIC3 | ec:e7:a7:22:5d:bd | unknown → down | slot14_0xb80000/2 down | |
| sr650_v4_01 | NIC4 | ec:e7:a7:22:5d:bc | unknown → up | slot14_0xb80000/1 up 25000 | |
| sr650_v4_02 | NIC1 | ec:e7:a7:22:5f:39 | unknown → down | slot13_0x160000/2 down | |
| sr650_v4_02 | NIC2 | ec:e7:a7:22:5f:38 | unknown → up | slot13_0x160000/1 up 25000 · slot14_0xb80000/1 up 25000(두 포트 일치) | false → true |
| sr650_v4_02 | NIC5 | ec:e7:a7:22:61:81 | unknown → down | slot14_0xb80000/2 down | |
| sr650_v4_03 | NIC1 · NIC2 | ec:e7:a7:22:4d:05 · :04 | unknown → up | slot13_0x160000/2 · /1 up 25000 | NIC1 false → true |
| sr650_v4_03 | NIC3 · NIC4 | ec:e7:a7:20:2d:6d · :6c | unknown → up | slot4_0x3b0000/2 · /1 up 25000 | |
| sr650_v4_03 | NIC9 · NIC10 | ec:e7:a7:20:26:19 · :18 | unknown → up | slot7_0x950000/2 · /1 up 25000 | |
| sr650_v4_03 | NIC11 · NIC12 | ec:e7:a7:20:33:05 · :04 | unknown → up | slot8_0xc90000/2 · /1 up 25000 | |
| sr650_v4_03 | NIC13 · NIC14 | ec:e7:a7:22:55:c5 · :c4 | unknown → up | slot14_0xb80000/2 · /1 up 25000 | |
| sr650_v4_04 | NIC1 | ec:e7:a7:22:55:39 | unknown → down | slot13_0x170000/2 down | |
| sr650_v4_04 | NIC2 | ec:e7:a7:22:55:38 | unknown → up | slot13_0x170000/1 up 25000 · slot14_0xb80000/1 up 25000(두 포트 일치) | false → true |
| sr650_v4_04 | NIC3 | ec:e7:a7:22:4b:5d | unknown → down | slot14_0xb80000/2 down | |

- 합 20건(up 14 · down 6), `is_primary` 4건 false → true, `summary.groups[].link_up_count` 0 → 2 / 1 / 4 · 6 / 1, `summary.primary_speed_mbps` null → 25600(4대).
- `speed_mbps` 변화 0 — SR650 V4 NIC 은 자체 값(25600 · 0)이 있어 덮지 않는다.
- 그 밖 14 label 값 변화 0: DL380 Gen12 3대 16건은 종전 결과와 같고, CSUS 8 · 4 · 8(2차)과 1차 CSUS 03 · 04 의 8 · 8 은 같은 MAC 포트가 없어 `unknown`, dl380_gen12_03(전원 Off)은 같은 MAC 포트 4개가 있으나 포트 link 가 `unknown` 이라 보충하지 않는다.
- 독립 검증 출력(`se-indep-20261027/out/tier1-after`, 읽기만)과도 같은 허용 목록으로 차이 34 · 미설명 0(`tier1-A/_explained_vs_indep.md`).
- HBA(`storage.hbas[]`)는 18 label 값 · 수 · 링크 notice 16건이 `tier1-final` 과 같다(`tier1-A/_invariants.md`).

## 4. 시험 (`db606f1c` — `tests/unit/test_redfish_xcc3_shape.py`)

| 시험 | 확인 |
|---|---|
| `test_link_fill_does_not_depend_on_nic_speed` | NIC `SpeedMbps 25600` + 같은 MAC 포트 LinkUp → `up`, speed 25600 유지(종전 조건이 놓친 형태) |
| `test_link_fill_uses_every_same_mac_port_and_requires_agreement` | 같은 MAC 포트 2개 일치 → 보충 / 불일치(LinkUp · LinkDown) → `unknown` |
| `test_speed_fill_needs_null_nic_speed_and_agreeing_ports` | NIC speed null + 포트 속도 일치 → 보충 / 불일치 → null |
| `test_link_fill_never_overwrites_nic_values_and_never_defaults_to_down` | NIC 자체 값 유지 · 짝 없음 → `unknown`(`down` 아님 — HBA 정책 미적용) |
| `test_xcc3_fixture_links_come_from_same_mac_ports` | fixture 4대 렌더 — 위 20건 정확값 |
| `test_bonded_permanent_mac_nic_stays_unknown` | NIC6(v4_02) · NIC4(v4_04)는 `SpeedMbps 25600` 이어도 `unknown`(속도로 링크를 추측하지 않음) |
| `test_dl380_fill_result_is_unchanged` | DL380 3 label 16건 결과 유지 |
| `test_hosts_without_port_link_signal_keep_unknown` | CSUS 등 같은 MAC 포트 없는 NIC 은 `unknown` 유지 |
| `test_xcc3_network_summary_counts_filled_links` | summary `link_up_count` · `primary_speed_mbps` |

## 5. 미해결 [HOLD] — sr650_v4_02 `NIC6` · sr650_v4_04 `NIC4` (사용자 지시 A1, 조사 2026-10-28)

포트 단위 근거가 원문에 있는지 2차 zip 새 추출본(`mock2-fix-20261028/extract`)에서 다시 확인했다.

| | sr650_v4_02 NIC6 | sr650_v4_04 NIC4 |
|---|---|---|
| 호스트 NIC `Systems/1/EthernetInterfaces/NICn` | `MACAddress` = `PermanentMACAddress` `EC:E7:A7:22:61:80`, `SpeedMbps 25600`, `LinkStatus` 키 없음, `Links` = Chassis 뿐 | `EC:E7:A7:22:4B:5C`, 나머지 같음 |
| NDF `Chassis/1/NetworkAdapters/slot14_0xb80000/NetworkDeviceFunctions/0` | `Ethernet.MACAddress EC:E7:A7:22:5F:38`(= NIC2 MAC) · `PermanentMACAddress …61:80` · `Links.PhysicalNetworkPortAssignment` → `Ports/1` | `MACAddress …55:38`(= NIC2) · `PermanentMACAddress …4B:5C` · → `Ports/1` |
| 포트 `…/slot14_0xb80000/Ports/1` | `Ethernet.AssociatedMACAddresses [5F:38, 61:80]` · `Oem.Lenovo.PermanentAddress 61:80` · `LinkStatus LinkUp` · 25.0 Gbps | `[55:38, 4B:5C]` · `4B:5C` · `LinkUp` · 25.0 Gbps |
| 모듈 출력 `data.network.ports[]` | slot14_0xb80000/1 `associated_address` = `ec:e7:a7:22:5f:38`(목록 `[0]` 만) — NIC6 MAC 이 포트 쪽에 없음 | `ec:e7:a7:22:55:38` 만 — NIC4 MAC 없음 |

- 해석: 같은 포트의 현재 주소 `[0]` 이 slot13 포트 1(= NIC2)과 같다 — 두 포트가 한 MAC 을 쓰는 본딩 구성으로 보인다(추정 — OS 쪽 미확인).
- 원문에는 표준 속성만으로 이어지는 연결(NIC `PermanentMACAddress` = NDF `PermanentMACAddress` → `PhysicalNetworkPortAssignment` → 포트 `LinkUp`, 포트 `AssociatedMACAddresses` 에도 포함)이 있다.
- 판정: 이번 범위에서 안전하게 해결할 수 없다 → **값 `unknown` 유지(추측 0)**.
  - normalize 층에 이 근거가 없다. 모듈이 포트 주소를 `AssociatedMACAddresses[0]` 하나만 내보내고 NDF 영구 주소 · 포트 연결은 내보내지 않는다.
  - 쓰려면 보호 경로 `redfish-gather/library/redfish_gather.py` 의 포트 · NDF 수집을 바꿔야 하고, 모듈 출력이 바뀐다 → golden 변경 또는 `network.ports[]` 새 키(별도 사용자 승인 대상)다.
  - 본딩에서 `[0]` 이 두 포트에 걸리는 경우의 영구 주소 조인 규칙을 18 미러 전부에서 다시 확인해야 한다.
  - NIC 자체 `SpeedMbps 25600` 은 링크 판정 필드가 아니므로 쓰지 않는다.
- 재개 조건: 모듈이 포트의 `AssociatedMACAddresses` 전체 또는 NDF `PermanentMACAddress` · `PhysicalNetworkPortAssignment` 를 내보내는 변경을 사용자가 승인 + golden 원장(G-26 이후) 기록 + 18 미러 조인 결과 대조.

## 6. 바꾸지 않은 것

- `_normalize_link_status`(모듈 네트워크 정규화) · HBA 판정 · 요청 경로(새 HTTP 요청 0) · golden · baseline · envelope 13 필드 · 키 · enum 집합.
- 호출자 영향: SR650 V4 의 `link_status` · `is_primary` · `summary` 값이 바뀐다(shape 변경 0). 사전 `network.interfaces[].link_status` · `docs/contract/03-fields.md` 6.4 · decision-log 2026-10-28 에 규칙을 적었다.
