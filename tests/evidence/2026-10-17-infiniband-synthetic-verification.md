# 2026-10-17 — InfiniBand 수집 전면 검증 (합성 데이터 모의 실행 · 실장비 아님)

> 대상: `data.storage.infiniband[]` 4경로 (OS Linux · OS Windows · Redfish · ESXi) + CSUS 3200 Redfish 시리얼 접미사.
> 근거 결정: `docs/ai/decisions/ADR-2026-10-17-infiniband-port-decision.md`. 계획: 사용자 지시서 2026-10-17.

## 1. 검증 층위 — 무엇을 했고 무엇을 하지 않았나

| 층위 | 내용 | 결과 |
|---|---|---|
| 정적 | 공식 스키마·문서 대조 (kernel sysfs ABI · sysfs.c · rdma-core umad.c · RFC 4392 / Microsoft MSFT_NetAdapter ValueMap · NDK · NVIDIA WinOF-2 RN / DMTF Port.v1_19_0 · NetworkPort.v1_4_3 · NetworkDeviceFunction.v1_11_1 / NVIDIA ESXi 드라이버 RN · Broadcom KB 381748 · pyVmomi 타입) + 코드·YAML 파싱·컴파일 | [PASS] |
| 모의 실행 | Linux: 합성 sysfs 트리를 실제 `sh` 로 실행 + production Jinja 렌더 / Windows: 가짜 cmdlet 위에서 production win_shell 을 실제 powershell.exe 로 실행 + Jinja 렌더 / Redfish: DMTF 모양 합성 리소스 route-dict + 합성 recording(`synthetic_ib_mode`) 전체 경로 재생 / ESXi: production set_fact + 공통 merge/build 렌더 | [PASS] |
| 실장비 | **수행하지 않음** — lab 에 IB 장비·IB 모드 BMC·IB 사용 OS/ESXi 가 없다 | [SKIP] |

실장비에서만 확인할 수 있는 것(미확인으로 남김): mlx5 IB 포트 DOWN 시 실제 `rate` 문자열 · 실제 `hca_type`/`board_id` 값 · lspci 장치명 표기 /
WinOF-2 IPoIB 어댑터의 `NdisMedium` · `PhysicalMediaType`(WS2022/2025) · `RdmaTechnology` · `InterfaceDescription` /
실 BMC 의 IB 모드 Port·NetworkDeviceFunction 페이로드(공개 mockup 0건) / CSUS OS 측 DMI 시리얼 표기.

## 2. 확정한 판별 기준 (코드 주석의 origin 과 같다)

- Linux: `ports/<n>/link_layer == InfiniBand` 인 포트만. RoCE/iWARP 는 `Ethernet`. `node_type` 은 mlx5 가 RoCE 도 `CA` 라 근거 아님.
  `rate_gbps` 는 `state` ACTIVE 일 때만(커널 `rate_show` 는 DOWN 포트에도 SDR 기본값). GUID 는 `normalize_ib_guid`, `port_guid` = `gids/0` 하위 64비트.
  vendor/model 은 `lspci -mm -s <PCI_SLOT_NAME>`(pci.ids), 없으면 vendor null / model=`hca_type`.
- Windows: `NdisPhysicalMedium 11` 또는 표시값 `Infiniband`; 2차 `Get-NetAdapterRdma` `RdmaTechnology == InfiniBand`(iWARP/RoCE 제외);
  팀 멀티플렉서(`Multiplexor`/`MS_IMPLAT`) 제외; PnP 서비스명 폴백 삭제. 속도 `ReceiveLinkSpeed`(bps). `port`/GUID/펌웨어 null.
- Redfish: `_ib_decision` — 포트 현재 모드(`LinkNetworkTechnology`/`ActiveLinkTechnology`/`PortProtocol`) + 연결 기능 `NetDevFuncType`;
  충돌은 IB 확정 안 함 + notice. GUID 는 기능 값 합의 → `Port.InfiniBand` 배열(distinct 1개). 고아 기능은 항목 아님.
- ESXi: 수집하지 않음(항상 `[]`) — 네이티브 nmlx5 는 Ethernet 전용, IB 모드 카드는 vmnic 없이 PCI 컨트롤러로만.

## 3. baseline 정정 — `schema/baseline_v1/windows_2022_baseline.json`

- 정정: `data.storage.infiniband` 3건 → `[]`. 다른 필드는 손대지 않았다.
- 원본 3건은 2026-06-22 캡처(`tests/evidence/2026-06-22-windows-120-envelope.json`, 보존)의 NIC 팀 멀티플렉서
  (`Microsoft Network Adapter Multiplexor Driver`, HWID `COMPOSITEBUS\MS_IMPLAT_MP`)가 PnP 서비스명 폴백 `^(mlx|ibal|nd)` 의 `nd` 에
  걸려 Mellanox IB 로 기록된 오탐이다 (`tests/evidence/2026-06-26-windows-net-ib-driver-team-vlan.md` §1 에 원인·수정 기록).
- 근거 실측: 같은 호스트 10.100.64.120 의 2026-09-03 수집 `tests/evidence/2026-09-03-live/build192_win2022_10.100.64.120.json`
  (고친 코드) = `"infiniband": []`. 회귀 registry(`tests/regression/conftest.py`)에는 이 파일이 없고 e2e 는 구조만 검사하므로
  테스트 결과는 바뀌지 않는다 — 사람이 결과 예시로 읽을 때의 오해를 없애는 정정이다.

## 4. 합성 fixture

- `tests/fixtures/redfish/synthetic_ib_mode/` — `hpe_emulator_dl380a` recording 에서 카드 `DE081000` 의 4개 리소스만 IB 모드로 편집
  (README 에 편집 내용과 기대값 도출 근거). 기대값 `expected_network_adapters.json` 은 손으로 썼고 실제 재생 결과와 일치했다.
  baseline 으로 승격하지 않는다.
- Linux/Windows/Redfish 단위 테스트의 입력도 전부 합성이다 (각 파일 docstring 에 출처·근거).

## 5. 실행한 테스트 (이 PC, Windows 11 / Python 3.13 / powershell.exe 5.1 — 2026-10-17)

| 묶음 | 결과 |
|---|---|
| `tests/unit/test_linux_hba_ib_markers.py` + `test_identity_normalizer.py` | 39 passed |
| `tests/e2e/test_linux_raw_scripts_shim.py` | 11 passed |
| `tests/unit/test_windows_infiniband_detection.py` (실제 PowerShell 포함) | 28 passed |
| Windows 가드 (`test_windows_call_consolidation_render/static`, `test_windows_storage_enum_render`) | 149 passed |
| Windows PowerShell 통합 storage 부분 | 34 passed |
| Redfish 재생·예산·불변식 (`hpe_emulator`/`real_capture`/`dmtf`/`port_classification`/`request_budget`/`hba_coverage`/`round3`) | 133 passed, 3 skipped |
| Redfish 단위 (`test_redfish_infiniband_classification.py` 65 + 기존 7 파일) | 254 passed |
| `tests/integration/test_synthetic_ib_replay.py` + 불변식(새 폴더 포함) | 43 passed |
| ESXi (`test_esxi_infiniband_not_inferred.py` + 기존 3 파일) | 89 passed |
| 전체 `tests/unit tests/e2e tests/regression` (`30a92443`) | 5,376 passed · 41 skipped · 7 xfailed · 0 failed (21분 34초) |
| `tests/integration -m "not live"` | 349 passed · 6 skipped |
| 3채널 `ansible-playbook --syntax-check` (WSL ansible-core 2.20.7) | os · esxi · redfish PASS |

실장비 실행은 하지 않았다(1절). 전체 결과는 `docs/ai/catalogs/TEST_HISTORY.md` 2026-10-17 항목에 기록한다.
