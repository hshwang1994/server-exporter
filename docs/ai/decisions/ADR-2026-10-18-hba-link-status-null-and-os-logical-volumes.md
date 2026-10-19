# ADR-2026-10-18 — `storage.hbas[].link_status` 는 up/down + null · OS/ESXi 도 RAID 뒤 디스크를 `logical_volumes` 에 싣는다

- 상태: Accepted (사용자 결정 2026-10-17 · 2026-10-18) — **결정 1(미확정 → null) 과 결정 2 의 ESXi 부분(같은 (wwpn, wwnn) 1건) 은 2026-10-19 사용자 재결정으로 폐기**
  → `ADR-2026-10-19-hba-link-status-two-values-esxi-raw-and-windows-version.md`. 결정 2 의 Linux NPIV 제외 · Redfish 기능당 1건, 결정 3~5 는 그대로 유효.
- 범위: 4채널 `storage.hbas[]` · `storage.logical_volumes[]` · `storage.physical_disks[].media_type`(ESXi) · 채널 간 정합(`hardware.uuid` · `cpu.max_speed_mhz` · `cpu.turbo_max_mhz` · `cpu.logical_threads` · `network.adapters[].model`)
- 정본: `docs/contract/03-fields.md` 6.3.0b · 6.3.1 · 6.3.2 · `schema/field_dictionary.yml` · `tests/evidence/2026-10-18-hba-four-channel-and-cross-channel-audit.md`

## 컨텍스트 (Why)

- 사용자가 "논리(OS/ESXi) 와 물리(Redfish) HBA 값·개수가 다르다", "CSUS 는 전부 unknown", "HBA 누락이 있어 임시 hotfix 를 했다" 고 보고했다. 조사 결과 (1) ESXi 7 FC-NVMe 가 포트당 vmhba 2개를 같은 WWPN 으로 보여
  ESXi 가 Redfish 의 2배로 나왔고, (2) 네 채널 모두 `link_status` 3값(`unknown` 포함)에 매핑이 제각각이었고, (3) HPE CSUS 3200 RMC(1.75.108)는 FC Port 리소스에 링크 상태 속성 자체가 없어 Redfish 로는 수집할 수 없었다.
- 처음 안(2026-10-17 사용자 지시 "모르면 down")은 CSUS 를 항상 down 으로 보여 상시 거짓 경보가 된다 — 사용자가 재검토 뒤 "확인되지 않은 상태를 임의로 down 처리하지 말라" 고 바꿨다.
- 같은 물리 서버 2쌍을 두 채널로 맞대어 보니 같은 뜻인데 다른 값(uuid 바이트 순서 · 정격 클럭 vs 터보 · 스레드 수 · NIC 모델)과 뜻이 달라 다른 값(카드 vs PCI 기능 개수 등)이 섞여 있었다. RAID 논리 볼륨은 Redfish 만 냈다.

## 결정 (What)

1. `storage.hbas[].link_status` 의 문자열은 `up` · `down` 둘뿐이다. **장비가 링크 상태 속성을 주지 않으면 `null`** — 기존 계약의 "미노출 → null"(`link_speed_gbps` · `wwnn`) 과 같은 규칙. `unknown` 문자열은 폐지한다.
   채널별 매핑은 사전 `storage.hbas[].link_status` 가 정본이다(Redfish LinkStatus 없음 → null + notice; Linux port_state 완전일치; Windows OperationalStatus → PortState → null; ESXi status). `storage.infiniband[].link_status` 는 그대로(요청 없음).
2. 항목 1개 = 물리 FC 포트 1개 — Linux 는 NPIV 가상 포트 제외, ESXi 는 같은 (wwpn, wwnn) 1건, Redfish 는 기능당 1건(FibreChannel 블록 포트 + 짝 없는 고아 중복 제거).
3. Redfish `wwpn` 은 기능의 WWPN → 없으면 포트 FC 주소 목록에서 알려진 WWNN 을 뺀 유일값(구 NetworkPort 주소는 쓰지 않음) → 못 정하면 null + notice. 행은 항상 남는다. 운영의 임시 조치(wwpn = 포트 주소)는 이 규칙으로 대체한다.
4. 같은 뜻인데 다른 값은 고친다: Cisco CIMC `System.UUID` 바이트 순서(adapter `vendor_notes.uuid_byte_order: smbios_raw` → normalize 스왑), Redfish `cpu.max_speed_mhz` = 정격(BaseSpeedMHz → Oem.Hpe.RatedSpeedMHz → 브랜드 → OperatingSpeedMHz → Oem.Lenovo.CurrentClockSpeedMHz),
   `cpu.turbo_max_mhz` = MaxSpeedMHz(Redfish 추가), `cpu.logical_threads` 는 ProcessorSummary.LogicalProcessorCount 우선, NetworkAdapter Model 은 FirmwareInventory 이름 폴백. 뜻이 달라 다른 값은 문서에 채널별 기준만 적는다.
5. OS/ESXi 는 RAID 컨트롤러 뒤 디스크를 `storage.logical_volumes[]` 에도 싣는다(physical_disks 유지 · member_drive_ids [] · raid_level null). ESXi RAID 뒤 LUN 의 `media_type` 은 null.

## 결과 (Impact)

- envelope 13 필드 · `sections` · `status` 불변. 호출자가 볼 변화: `link_status` 가 `null` 일 수 있음(`unknown` 사라짐), Redfish `cpu.max_speed_mhz` 가 터보에서 정격으로, `cpu.turbo_max_mhz` 가 Redfish 에도, OS/ESXi `logical_volumes` 가 채워짐,
  Cisco Redfish `hardware.uuid` 표기가 OS/ESXi 와 같아짐. 전부 사전 안의 변경(키 추가 0)이고 Portal 안내는 NEXT_ACTIONS.
- CSUS 3200 은 Redfish 에서 `link_status: null` + notice 로 나오고 Portal 이 wwpn 으로 OS 값을 조인해 보인다. HPE 에 FC `Port.LinkStatus` 미제공을 문의한다.
- 교차 회귀 `tests/regression/test_cross_channel_same_server.py` 가 같은 서버 2쌍에서 serial · uuid · 소켓/코어 · 정격 · 터보 · 스레드 · hbas WWPN 부분집합 · link_status 값을 고정한다.

## 대안 비교 (Considered)

| 대안 | 평가 |
|---|---|
| 2값(모르면 down) | CSUS 가 항상 down — 장애 예측이 아니라 상시 거짓 경보. 폐기(사용자 재결정) |
| `unknown` 유지 | Portal 이 "링크 장애 아님" 을 따로 해석해야 하고 다른 미노출 필드(null)와 규칙이 다르다. 폐기 |
| CSUS PCIe 장치 `H3Alert.1.7.LinkUp` 을 up 신호로 | 슬롯 PCIe 링크(RAID 컨트롤러에도 있음) — FC 케이블이 빠져도 LinkUp. 폐기 |
| 판정 함수에 링크 기술을 넣어 FC 판정 | 2026-10-15 에 폐기한 원안 — 짝 없는 기능 구조에서 같은 포트가 두 번 나온다. 포트 루프의 조건부 규칙 + 고아 가드로 처리 |
| RAID LUN 을 physical_disks 에서 빼고 logical_volumes 로 옮김 | 호출자 파싱 변경(Additive 위반). physical_disks 유지 + logical_volumes 추가로 |
| Redfish `cpu.max_speed_mhz` 를 그대로 두고 문서만 | 사전 정의(정격)와 다른 값이 그대로 — 같은 뜻 다른 값은 버그(사용자 결정) |
