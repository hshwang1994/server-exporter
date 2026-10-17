# ADR-2026-10-17 — `storage.infiniband[]` 는 "현재 InfiniBand 모드로 확인된 포트" 만 담는다 (4채널)

- 상태: Accepted (코드 · 자동 시험 완료, 실장비 미검증 — lab 에 IB 없음)
- 일시: 2026-10-17
- 결정 주체: 사용자(hshwang1994) — 지시서(2026-10-17) · 세 결정(Windows `system.version` 현행 유지 · windows_2022 baseline IB 만 정정 · CSUS 시리얼 범위). AI(Claude) — 조사 · 설계 결정(아래 2절) · 구현 · 검증
- 관련 rule: 10 R1 · R4, 12 R1, 13 R1 · R7, 21 R1 · R2, 22 R1, 25 R7-B, 92 R2, 96 R1 · R1-A · R4, 70 R1 · R8
- 관련 결정: 2026-05-29 HBA/IB 전 채널 통일(ADR-2026-05-29-hba-ib-csus) · 2026-06-08 DSP8010 대조 · 2026-08-03 FCoE CNA 오분류 · 2026-10-15 Redfish HBA 누락 보완
- 정본 문서: `docs/contract/03-fields.md` 6.3.1 · 6.3.3 · `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` 2026-10-17 · `tests/evidence/2026-10-17-infiniband-synthetic-verification.md`

## 1. 컨텍스트 (Why)

사용자 질문("OS 수집의 storage 아래 infiniband 는 무슨 값이고 결과 JSON 이 어떻게 나오나")에서 시작해 4경로를 대조한 결과, 어느 경로도
"IB 를 지원할 수 있는 카드" 와 "지금 IB 모드로 동작하는 포트" 를 구분하지 않았다.

| 경로 | 결함 |
|---|---|
| Linux | `/sys/class/infiniband` 에 등록된 장치를 전부 담았다. 그 디렉터리에는 RoCE(mlx5 이더넷 모드) · iWARP 장치도 들어가고 `rate` 도 IB 식(4X EDR)으로 찍힌다. `"2.5 Gb/sec"` → `25`, `ACTIVE_DEFER` → `up`, `hca_type` 접두 `MT` → `"Mellanox"` 추정 |
| Windows | PnP 서비스명 폴백이 장치 상태 `OK` 를 링크 `up` 으로 적었고(속도 없음), 2026-06-22 사이트 캡처에서 NIC 팀 멀티플렉서 3건을 Mellanox IB 로 기록했다. `note` 에 내부 규칙 번호 |
| Redfish | DMTF 에 없는 속성 `NetworkDeviceTechnology` 를 읽었고(열거형 이름), `Port.InfiniBand` 블록 존재만으로 IB, 포트 링크 기술이 Ethernet 이어도 기능이 InfiniBand 면 IB 우선, 포트에 연결되지 않은 기능을 `port=<기능 Id>` 로 항목화, GUID 배열 `[0]` 무조건 사용 |
| ESXi | vmnic 드라이버명이 `nmlx`/`mlx` 면 IB 항목 — 네이티브 nmlx5 는 Ethernet 전용이라 이더넷 NIC 오탐 |

실장비 결과는 전부 `[]` 여서 운영 영향은 없었지만, 호출자가 받을 항목의 뜻(포트 단위 · 현재 모드)이 문서와 달랐고 lab 에 IB 가 없어 자동 검증도 없었다.

## 2. 결정 (What)

1. **항목 1개 = 현재 InfiniBand 모드로 확인된 포트 1개.** 판정 근거는 채널이 주는 "현재 모드" 속성뿐이다.
   - Linux: `ports/<n>/link_layer == InfiniBand` (kernel sysfs ABI · `sysfs.c link_layer_show`). `node_type` 은 mlx5 가 RoCE 도 `CA` 라 쓰지 않는다.
   - Windows: `NdisPhysicalMedium 11`(Infiniband) 또는 표시값 `Infiniband`; 2차로 `Get-NetAdapterRdma` 의 `RdmaTechnology == InfiniBand`(NDK 열거값 — iWARP/RoCE 제외). RDMA Enabled · PnP 서비스명 · `VEN_15B3` 는 근거가 아니다.
   - Redfish: `_ib_decision` — 포트 현재 모드(`Port.LinkNetworkTechnology` / `NetworkPort.ActiveLinkTechnology` / `Port.PortProtocol`) 와 연결 기능의 `NetDevFuncType`. 둘이 충돌하면 IB 로 확정하지 않고 `diagnosis.details.notices` 1건. `NetDevFuncCapabilities` · `Port.InfiniBand` 블록 존재 · GUID 존재 · 카드 이름은 근거가 아니다. 포트에 연결되지 않은 IB 기능은 항목이 아니다(부모 IB 포트의 빈 GUID 만 채움).
   - ESXi: 수집하지 않는다(항상 `[]`). 원천이 없다 — NVIDIA 인박스 드라이버 Ethernet 전용 · IB 는 SR-IOV/passthrough 로 VM 에만 · IB 모드 카드는 PCI `Infiniband controller` 로만(Broadcom KB 381748).
2. **값 규칙(공통)**: `rate` = 원천 속도 문자열 원문(없음/0 이면 null, Redfish 는 항상 null — 합성 금지). `rate_gbps` = `link_status == up` 일 때만 숫자(정수 int · 소수 보존). 커널 `rate_show` 는 DOWN 포트에도 SDR 기본값을 찍고 Redfish 는 down 시 0 을 주므로 그 값을 현재 속도로 쓰지 않는다.
   `link_status`: 명확한 활성 → `up`, 명확한 DOWN → `down`, 중간 상태(INIT/ARMED/ACTIVE_DEFER · Starting/Training) · 없음 · Disabled/Not Present → `unknown`. Redfish `network.ports[].link_status` 는 종전 규칙(협상 중 = down) 유지 — 호출자 계약.
   GUID 는 소문자 `xxxx:xxxx:xxxx:xxxx`(`normalize_ib_guid` 필터 + `redfish_gather._normalize_ib_guid`, drift guard). 형식 오류 · all-zero → null. Linux `port_guid` = `gids/0` 하위 64비트(RFC 4392, rdma-core umad.c). Redfish 는 연결 기능 값의 합의 → `Port.InfiniBand.Associated*GUIDs` 는 distinct 1개일 때만.
   `vendor`/`model`: Linux 는 `lspci`(pci.ids) 이름, 없으면 vendor null · model `hca_type`; Windows `DriverProvider` · 어댑터 설명; Redfish `Manufacturer` · `Model`. 추정 금지.
   Windows `port` = null(물리 포트 번호 표준 API 없음), `node_guid`/`port_guid`/`firmware` = null. `note` 유지하되 내부 규칙 번호 없음.
3. **공통 키 11개**(`adapter port node_guid port_guid link_status rate rate_gbps model vendor firmware source`) + Redfish 호환 키 `adapter_model`(=`model` 추가) + Windows `note`. 기존 키 삭제 · 개명 없음. `schema/field_dictionary.yml` 에 7 항목 추가(additive).
4. **검증 전략(실장비 없음)**: 공식 자료 대조(정적) + 합성 데이터로 production 경로 모의 실행(Linux 실제 `sh` · Windows 실제 powershell.exe · Redfish route-dict + 합성 recording 재생 · ESXi Jinja 렌더) + 4채널 공통 계약 검사기(`assert_ib_entry_canonical`). 기대값은 코드 출력 스냅샷이 아니라 규칙에서 따로 정했다. 실장비 검증은 하지 않았고 그렇게 보고하지 않는다.
5. **baseline**: `windows_2022_baseline.json` 의 `data.storage.infiniband` 만 `[]` 로(사용자 결정) — 같은 호스트 2026-09-03 실측 근거, 원본 캡처 evidence 보존. 2026-05-29 이전 캡처(키 자체 없음)는 손대지 않는다.
6. **범위 밖**: ESXi PCI classId 기반 "컨트롤러 존재" 표시(모듈 변경 + 새 필드), Windows 20바이트 IPoIB 주소에서 port_guid 도출(실측 미확인), 벤더 도구(`mlx5cmd`) 사용 — NEXT_ACTIONS.

## 3. 결과 (Impact)

- 봉투 13필드 · 섹션 · status 판정 · `failure_code` 변경 0. `data.storage.infiniband[]` 의 **값 의미**가 바뀐다 — 실사용 결과는 전부 `[]` 라 실제 값 변화 0.
  바뀌는 의미: Linux `rate_gbps`(비-up 시 null) · `ACTIVE_DEFER`→unknown · `vendor`(추정 제거), Windows `port`(null) · `note` 문구, Redfish `model` 키 추가 · 고아 기능 항목 없음, ESXi 항상 `[]`.
- Redfish 실측 녹화본 10종 golden · 요청 집합 · notice 0 — 변경 0 (`tests/integration` 재생 전수). FC/Ethernet 분류 경로는 IB 신호가 없는 장비에서 닿지 않는다.
- Linux 원격 실행은 raw task 1개 그대로(장치당 `lspci` 1회 추가 — 같은 raw 안). Windows win_shell 11개 그대로(`Get-NetAdapter` 1회).
- 새 파일: `tests/unit/test_windows_infiniband_detection.py` · `test_redfish_infiniband_classification.py` · `test_esxi_infiniband_not_inferred.py` · `tests/integration/test_synthetic_ib_replay.py` · `tests/fixtures/redfish/synthetic_ib_mode/`(합성, baseline 승격 금지).
- 문서: `03-fields.md` 6.3.1 · 6.3.3 · FAQ, `05-field-mapping.md`, `EXTERNAL_CONTRACTS.md` 2026-10-17, ticket `EXTERNAL-CONTRACTS.md` §2-4 추기, DRIFT-028, evidence.

## 4. 대안 비교 (Considered)

| 대안 | 기각 이유 |
|---|---|
| Linux: PCI 클래스(0x0207)나 `node_type` 으로 판정 | mlx5 는 RoCE 도 `node_type: CA`; PCI 클래스는 VPI 카드의 포트별 모드를 말하지 않는다. `link_layer` 가 포트 단위 현재 모드다 |
| Linux: `vendor` 를 PCI vendor ID 표로 매핑 | 새 표(벤더 지식) 추가. `lspci`(pci.ids) 이름을 쓰면 표 없이 같은 정보 — gather_network 이 이미 쓰는 방식 |
| Linux: DOWN 포트의 `rate_gbps` 도 숫자로 | 커널 값은 기본 SDR 이지 협상 속도가 아니다(sysfs.c 에 DOWN 특수처리 없음) — "현재 속도" 의미 위반 |
| Windows: PnP 폴백 유지하되 조건 강화 | 폴백은 링크 상태 · 속도를 줄 수 없다(장치 상태 ≠ 링크). IPoIB 어댑터는 1차 조회(-IncludeHidden)에 이미 보인다 |
| Windows: `mlx5cmd -stat` 로 link_layer 확인 | 벤더 도구 의존성 추가 — 운영 환경에 강제 금지(지시서 4.3) |
| Redfish: 충돌 시 포트 링크 기술 우선(종전은 기능 우선) | 어느 쪽이 정본인지 스키마가 정하지 않는다 — 임의 선택 대신 미확정 + notice(지시서 5.2) |
| Redfish: IB 항목 link_status 도 종전 공유 매핑(Starting/Training = down) | 중간 상태를 DOWN 으로 확정하지 않는다는 원칙(지시서 2.3). `network.ports[]` 는 호출자 계약이라 그대로 두고 IB 항목만 분리 — 문서화 |
| Redfish: `adapter_model` 을 `model` 로 개명 | 기존 키 삭제 금지 — `model` 을 같은 값으로 추가 |
| ESXi: PCI classId 0x0207 로 "IB 컨트롤러 존재" 항목 | 컨트롤러 ≠ 포트. 포트 상태 · GUID · 속도를 줄 수 없고 모듈 변경 + 새 필드가 필요 — 보류 |
| 합성 fixture 의 expected_output.json 을 현재 출력으로 스냅샷 | 코드 출력을 기대값으로 삼으면 검증이 아니다 — 규칙에서 손으로 정한 `expected_network_adapters.json` |
| windows_2022 baseline 유지 + 테스트 예외 목록 | 사용자가 정정을 골랐다(2026-09-03 실측 근거, 원본 캡처 보존) |

## 5. 검증

- 정적: 공식 자료 대조(kernel ABI · sysfs.c · ib_verbs.h · rdma-core umad.c · RFC 4392 / MSFT_NetAdapter ValueMap · NDK · NetAdapter.Types.ps1xml · WinOF-2 RN / DMTF Port.v1_19_0 · NetworkPort.v1_4_3 · NetworkDeviceFunction.v1_11_1 / NVIDIA ESXi RN · Broadcom KB 381748 · pyVmomi). YAML parse · py_compile.
- 모의 실행: 시나리오 1~28(지시서 8.4) ↔ 테스트 매핑은 계획 문서 §6 · evidence §5. 전체 suite 결과는 `docs/ai/catalogs/TEST_HISTORY.md` 2026-10-17.
- 실장비: **미수행**. 실장비에서만 확인 가능한 항목은 evidence §1 과 `docs/ai/NEXT_ACTIONS.md` §2.4.
