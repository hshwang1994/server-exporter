# 02 — HBA `link_status` up 값을 표준 링크 값으로 한정 (사용자 결정 Q1, 2026-10-28)

- 날짜 2026-10-28 · 브랜치 `fix/redfish-mock2-review-20261028` · 코드 `0227e2cb`(`redfish-gather/library/redfish_gather.py` — 보호 경로, 이 계획에서 영향 확인).
- 사용자 정책(변경 없음): HBA `storage.hbas[].link_status` 는 `up` / `down` 두 값뿐이다. 근거가 불확실하면 `down`. `unknown` 복구 · 새 상태값은 만들지 않는다. CSUS A안(카드 단위 조건은 notice 참고만)은 그대로다.
- 사용자 결정(Q1 원문): "1번으로 진행하되, Enabled·Active는 표준 Port.LinkStatus에서 근거 불명인 경우에만 down fallback 처리하세요. 향후 OEM 포트별 링크 상태에서 Active가 실제 Link Up을
  의미한다는 명확한 근거가 확인되면 별도 정규화할 수 있도록 기존 조사·개선 방향을 유지하세요."

## 1. 판정 구조 (변경 전 → 후)

| 요소 | 변경 전 (`f92ebe6a`) | 변경 후 (`0227e2cb`) |
|---|---|---|
| `_hba_link_status` | 키 없음 → down. 있으면 공유 정규화 `_normalize_link_status(raw) == 'up'` 일 때 up(공유 up 집합 linkup · up · connected · enabled · active) | 키 없음 → down(그대로). 값이 문자열이고 `strip().lower()` 가 `_HBA_LINK_UP_VALUES` = {linkup, up, connected} 일 때만 up, 그 밖 down |
| `_hba_link_unresolved` | 정규화 결과가 up/down 밖이면 raw → notice "링크 상태 값 미확정, down 으로 기록" | 위 규칙 + 정규화 결과는 up 인데 HBA up 값이 아니면(Enabled · Active) raw 반환 → 같은 notice |
| `_hba_link_missing` · `_normalize_link_status`(네트워크 정규화) · A안 코드(`_pcie_port_link_condition` · 카드 조건 3중 조건) · 요청 경로 | — | 변경 0 |

- 상수 origin 주석(rule 96 R1): DMTF `Port.LinkStatus` LinkUp(Starting/Training/LinkDown/NoLink 는 up 아님) · 구 schema `NetworkPort.LinkStatus` Up · `Connected` 는 사전에 up 으로 적혀 있던 기존 값(표준 enum 밖, 18 미러 · fixture 출현 0 — 현행 유지).
- 네트워크 쪽은 바꾸지 않았다: 같은 FC 포트가 `network.ports[]` 에서는 `up`, `storage.hbas[]` 에서는 `down` 일 수 있다(BMC 가 `Enabled`/`Active` 를 보낼 때만 — 의도된 차이, 18 미러 · 저장소 fixture 출현 0).

## 2. raw 재조사 — 현재 코드가 놓친 포트 단위 Up 근거 (요구 4)

결론: 18 미러에서 "원문 포트 Up 인데 출력 down" 은 0건이다. Up 원천을 늘리는 코드는 만들지 않았다.

| label | FC 포트 원문 | 출력 | 확인한 것 |
|---|---|---|---|
| dl380_gen12_01 · _04 | `NetworkAdapters/DE040000 · DE043000/Ports/1` LinkUp(CurrentSpeedGbps 32) / `Ports/2` LinkDown | up / down | 같은 어댑터 안 포트별 독립 |
| dl380_gen12_02 · r1_HPE_DL380_01 | Ports LinkDown | down | |
| sr650_v4_02 | FC Ports 전부 LinkDown(`LinkState Enabled` · MaxSpeedGbps 32) | down | 관리 상태 `LinkState` 를 링크로 쓰지 않음 |
| sr650_v4_03 | slot5 · slot6 FC 어댑터 `Ports/1` LinkUp 32.0 / `Ports/2` LinkDown | up / down | |
| r1_DELL_R740_01 | LinkStatus Down/LinkDown + `Oem.Dell.DellFCPortMetrics.PortStatus` Down | down | OEM 값은 표준 값과 같음 — 추가 근거 아님 |
| CSUS 7(csus3200_01/03 · r1_HPE_CSUS3200_01~04 FC 보유; _02 는 FC 없음) | FC Port 키 = `FibreChannel.AssociatedWorldWideNames` · `Id` · `Name` 뿐. NDF = WWN/WWPN · `Links.PCIeFunction` · `NetDevFuncCapabilities` 뿐. `NetworkInterfaces` · `ResourceBlocks` · `Fabrics`(Rmp 관리 스위치 포트만)에도 FC 링크 없음 | down + A안 notice | 카드 조건 49건(7/3/7/7/7/9/9, 전부 LinkUp — `tools/csus_card_conditions.py`) |
| 그 밖 | sr650_v4_01/04 · csus3200_02 · r1_Lenovo_SR650_01 hbas 0, dl380_gen12_03(전원 Off) storage 0 | — | 가짜 항목 0 |

- 18 미러 전부에 없는 다른 후보: `PortConnectionType` · `FibreChannel.FibreChannelId` · `FabricName` · `NumberDiscoveredRemotePorts` · `Metrics`(PortMetrics).
- 키가 정확히 `LinkStatus` 인 값의 분포(같은 `@odata.id` 본문은 펼쳐진 하위 본문까지 1번 — `tools/linkstatus_values.py`, 결과 `linkstatus_values.md`):
  - 18 미러 원문: LinkUp 86 · LinkDown 81 · NoLink 43 · Down 14 · null 13 · Disconnected 4 · Up 2. Down · Up 은 구 schema `NetworkPort`, Disconnected 는 Dell
    `DellNetworkAttributes` 의 Ethernet NIC 속성(수집기가 읽지 않는 리소스)이다.
  - 저장소 fixture(녹화 · 단일 응답 JSON, 골든 `expected_output.json` 제외): LinkUp 123 · LinkDown 61 · null 45 · NoLink 22 · Down 16 · Up 4.
  - `Enabled` · `Active` · `Connected` 는 둘 다 0 → 이 변경의 출력 영향 0. `Connected` · `Disconnected` 는 Lenovo BIOS 속성(키가 `…_LinkStatus` 로 끝남 — Redfish 링크 키가
    아님)에만 나온다(미러 24 · 20, fixture 12 · 12).
  - 계획서(2026-10-28)에 적었던 분포 "LinkUp 244 · LinkDown 122 · NoLink 44 · Down 32 · Up 8" 은 다시 셀 때 재현되지 않았다 — 위 값으로 대체한다.
    결론(`Enabled` · `Active` · `Connected` 0)은 같다.
- 다른 환경에서 Up 을 놓칠 수 있는 경우(정책상 값은 down, 대신 notice 로 드러난다): 포트 링크를 OEM 위치에만 두는 BMC → "링크 상태 미제공" · 표준 enum 밖 표기(Enabled/Active 등) →
  "값 미확정"(raw 표기) · 부모 포트가 없는 orphan NDF → down · 전원 Off 호스트(미러 사례 없음).

## 3. HBA Up 근거로 쓰지 않는 신호 (요구 6)

| 신호 | 쓰지 않는 이유 |
|---|---|
| 컨트롤러 · 어댑터 `Status.State Enabled` · `Status.Health OK` | 장치 상태이지 링크가 아님 |
| PCIeDevice `Status.Health OK` · 카드 장착 · 슬롯 점유 | 카드 수준 |
| HBA 펌웨어 버전 · FirmwareInventory 항목 | 링크와 무관 |
| CSUS PCIeDevice `Status.Conditions` H3Alert LinkUp | 카드 수준 → A안 참고 notice 만, 포트 값으로 승격 금지 |
| RAID · NIC 카드 LinkUp 조건 | FC HBA 가 아님 |
| `Port.LinkState`(Enabled/Disabled) | 관리(admin) 상태 |
| `MaxSpeedGbps` · `CapableLinkSpeedGbps` · `CurrentSpeedGbps` 단독 | 링크 판정 필드가 아님 |
| NDF · WWPN · `AssociatedWorldWideNames` 존재 | 주소일 뿐 |
| XCC3 호스트 `EthernetInterfaces` 의 8옥텟 FC 주소 항목 | FC 포트 자체가 아님(03-network-001 이 제외) |
| OEM LogService · `Oem` · Iel 이력 | 실시간 근거가 아님 |
| LinkStatus 값 `Enabled` · `Active` | 표준 `Port.LinkStatus` enum 밖, 링크 의미 불명(사용자 결정 Q1) |

## 4. 시험 (`0227e2cb`)

| # | 사례 | 근거 종류 | 시험 |
|---|---|---|---|
| 1 · 2 · 7 | 실제 Up → up · 실제 Down → down · 같은 어댑터 포트 독립 | 미러 녹화 재생(실장비 캡처본) | `tests/integration/test_redfish_hba_coverage_replay.py::test_recorded_fc_ports_keep_their_own_link_state` — dl380_gen12_01 `DE040000/Ports/1` up · `/2` down, sr650_v4_03 slot5 · slot6 `Ports/1` up, sr650_v4_02 전부 down, r1 R740 down |
| 3 | 링크 필드 없음 → down + "링크 상태 미제공" | 재생 + 합성 | CSUS 재생(기존) · `test_synthetic_healthy_looking_fc_port_without_link_status_is_down` |
| 4 | 미인식 값 → down + "값 미확정" | 합성 | `tests/unit/test_redfish_pure_helpers.py` — `test_hba_link_status_enabled_and_active_are_down_not_up` · `test_hba_every_down_says_why`(값 목록) · `test_hba_link_unresolved_reports_enabled_and_active_as_undetermined` · `test_hba_up_values_are_standard_link_values_and_a_subset_of_the_network_up_set` |
| 5 · 6 | PCIe 카드 정상 · 카드 LinkUp 인데 포트 근거 없음 → down / RAID · NIC 카드 LinkUp 을 FC 로 오판 안 함 | CSUS 재생 + 합성 | `tests/unit/test_redfish_csus_chassis_fc.py` — `test_csus_healthy_fc_cards_without_port_link_status_stay_down` · `test_csus_raid_and_nic_card_linkup_never_becomes_an_fc_hba` · `test_synthetic_fused_card_ethernet_linkup_never_lifts_the_fc_port` |
| 7 | 다중 포트 독립(합성 4포트 혼합) | 합성 | `test_synthetic_four_fc_ports_are_judged_one_by_one` |

- 합성 시험은 docstring 에 "합성 — 실장비 Up 근거 아님" 을 적었다. 실제 Up 근거는 미러 녹화(실장비 캡처본)뿐이고 이것도 실장비 실시간 검증이 아니다.
- 기존 시험 `test_hba_link_status_is_up_only_for_an_active_link` 의 Enabled/Active 기대값은 사용자 결정에 맞춰 down 으로 바꿨다(사례 삭제 0, 사례 추가).
- 새 Tier 1(`tier1-A`): 18 label `storage.hbas[]` 값 · 수 · 링크 notice 16건 문구가 구현 측 `tier1-final` 과 같다(`tier1-A/_explained_vs_final.md` 차이 0 — HBA 경로 없음). 값 집합 ⊂ {up, down}.

## 5. 향후 OEM 포트별 정규화 (이번엔 구현하지 않음 — 조건만)

표준 `LinkStatus` 가 없거나 미확정일 때만, 벤더 OEM 의 **포트별** 필드가 실제 Link Up 을 뜻한다는 근거(벤더 공식 문서, 또는 실장비 캡처 + 같은 포트의 OS 측 상태 대조 — 예: Linux
`/sys/class/fc_host/host*/port_state` · `port_name` 과 Redfish WWPN 조인)가 확인되면 rule 12 R1 허용 영역(`_extract_oem_*` 계열)에 origin 주석과 함께 별도 정규화한다. 카드 수준 값은 대상이 아니다.
CSUS 는 실 RMC 읽기 전용 크롤(`Chassis/*/NetworkAdapters/*/Ports/*` 의 `LinkStatus` · `Metrics` · `PortConnectionType` · `FibreChannel.*`, `Fabrics/*/Switches/*/Ports`) — 새 요청이라 대상 · 요청 수를
적어 사용자 승인 후. 현재 상태는 [MOCK_LIMITATION] 유지.
