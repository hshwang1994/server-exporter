# synthetic_ib_mode — [WARN] 합성 데이터 (실장비 아님, baseline 승격 금지)

InfiniBand **모드**로 설정된 VPI 카드의 Redfish 응답을 재현한다. 실장비 IB 모드 BMC 캡처도, 공개 Redfish mockup 도
없어서(2026-10-17 조사) DMTF 스키마에 맞춰 손으로 구성했다. `storage.infiniband[]` 판정·GUID·속도·상태 경로를
실장비 없이 재생하기 위한 것이며, 이 결과로 `schema/baseline_v1/` 를 만들지 않는다.

## 출처 · 파생

- 원본: `tests/fixtures/redfish/hpe_emulator_dl380a/recording.json` (HPE iLO 에뮬레이터 캡처 — 에뮬레이터이지 실장비가 아니다).
  그 카드 `DE081000`(`HPE InfiniBand NDR200/Ethernet 200GbE 2-port QSFP112 PCIe5 x16 MCX755106AC-HEAT Adapter`)은 원본에서
  Ethernet 모드(`NetDevFuncType: Ethernet`, `LinkNetworkTechnology: Ethernet`)다.
- 편집한 리소스는 4개뿐이고 나머지 102개 응답은 원본과 바이트 단위로 같다 (재생 테스트가 그 사실을 고정한다):

| 리소스 | 변경 (DMTF 근거) |
|---|---|
| `NetworkDeviceFunctions/0`, `/1` | `NetDevFuncType: InfiniBand` (NetworkDeviceFunction.v1_11_1 "configured capability") · `Ethernet` 블록 제거 · `InfiniBand` 블록 = `NodeGUID`/`PermanentNodeGUID` `58a2:e103:0003:96f2`(HCA 당 1개 — 원본은 기능마다 달랐다, 합성 결정), `PortGUID`/`PermanentPortGUID` `…96f2`(기능 0) / `…96f3`(기능 1), `MTUSize 4096` |
| `Ports/0` | `LinkNetworkTechnology: InfiniBand` (Port.v1_19_0 "current link network technology"), `LinkStatus: LinkUp`, `CurrentSpeedGbps: 200.0`, `Ethernet` 블록 제거, `InfiniBand: {AssociatedNodeGUIDs [96f2], AssociatedPortGUIDs [96f2], AssociatedSystemGUIDs [96f2]}`, `LinkConfiguration[].LinkNetworkTechnology: InfiniBand` |
| `Ports/1` | 위와 같되 `LinkStatus: LinkDown`, `CurrentSpeedGbps: 0.0`, `AssociatedPortGUIDs [96f3]` |

`NetDevFuncCapabilities: [Ethernet, InfiniBand]` 는 원본 그대로 남겼다 — 지원 가능 목록은 판정 근거가 아니라는 점을 같이
확인하기 위해서다. `PortProtocol` 은 원본처럼 없다. `meta.json` · `request_budget.json` 은 두지 않는다 (`real_*` 전용).

## expected_network_adapters.json — 손으로 정한 기대값 (코드 출력 스냅샷이 아님)

`data.network_adapters` 만 적는다 (다른 섹션은 원본 golden 과 같아야 한다 — 재생 테스트가 비교).

- `adapters[0]`: 원본 golden 과 같되 `mac: null` (IB 포트에는 MAC 이 없고, 포트 주소를 MAC 으로 접지 않는다),
  `speed_mbps: 200000` (첫 활성 포트 200 Gbps), `link_status: up`, `port_count: 2`.
- `ports[]`: 두 포트 모두 `port_type: InfiniBand`. 포트 0 `link_status up`, `current_link_speed_mbps 200000`;
  포트 1 `link_status down`(network.ports 는 종전 `_normalize_link_status` — LinkDown → down), `current_link_speed_mbps null`
  (CurrentSpeedGbps 0 = 링크 없음). `associated_address null`(이더넷 MAC · FC WWN 블록이 없다). `physical_port_number null`
  (원본에도 PhysicalPortNumber 가 없다). `link_state Enabled`, `health OK`, `name Port`.
- `fc_hbas: []`.
- `infiniband[]`: 포트당 1개 = 2개. 공통 키 `adapter, port, node_guid, port_guid, link_status, rate, rate_gbps, model, vendor,
  firmware, source` + 호환 키 `adapter_model`.
  - 포트 0: `node_guid 58a2:e103:0003:96f2`, `port_guid 58a2:e103:0003:96f2` (연결된 기능 0 의 값), `link_status up`,
    `rate null`(Redfish 에 문자열 원천 없음 — 합성하지 않는다), `rate_gbps 200`(up 일 때만, 정수는 int), `vendor MLNX`(카드
    Manufacturer 원문), `firmware 28.43.1014`(Controllers[0].FirmwarePackageVersion), `model` = `adapter_model` = 카드 Model.
  - 포트 1: `port_guid 58a2:e103:0003:96f3`(기능 1), `link_status down`, `rate_gbps null`.

## 검증 층위

정적(스키마 형식) + 모의 실행(이 recording 재생) 까지다. **실장비 검증은 하지 않았다** — IB 모드 BMC 가 실제로 어떤
Port/NDF 조합을 주는지는 확인된 바 없다(2026-10-17 조사: NVIDIA BlueField BMC 샘플도 Ethernet, Lenovo XCC2 문서 샘플도 Ethernet).
실장비를 확보하면 `tests/integration/capture_mirror_fixture.py` 로 `real_*` 캡처를 만들고 이 합성 fixture 와 대조한다.
