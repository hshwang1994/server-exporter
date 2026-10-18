# 2026-10-18 — HBA 4채널 전수 점검 · `link_status` up/down/null · 채널 간 값 정합 · RAID 논리 볼륨

> 누가: 사용자 조사 요청 → AI 조사 · 구현 · 검증. 언제: 2026-10-17 조사, 2026-10-18 구현. 어디서: Redfish `redfish-gather/library/redfish_gather.py` ·
> `redfish-gather/tasks/normalize_standard.yml`, Linux `os-gather/tasks/linux/gather_hba_ib.yml` · `gather_storage.yml`, Windows `os-gather/tasks/windows/gather_storage.yml`,
> ESXi `esxi-gather/tasks/collect_network_extended.yml` · `esxi-gather/library/esxi_disks.py`, 공통 `filter_plugins/identity_normalizer.py`, adapter `adapters/redfish/cisco_cimc.yml`, 사전 `schema/field_dictionary.yml`.
> 무엇: `storage.hbas[]` 가 네 채널에서 조용히 비거나 틀리던 경로를 고치고, `link_status` 를 up/down/null 로, 같은 물리 서버의 두 채널이 같아야 할 값(uuid · 정격 클럭 · 스레드 · NIC 모델)을 맞췄다.
> 왜: 사용자 질문 — "HBA 를 어떻게 가져오나 · 예외처리 · 버그", "논리/물리 HBA 가 다르다(ESXi 8 vs Redfish 4)", "CSUS 가 전부 unknown", "HBA 누락 + 임시 hotfix", "채널마다 다른 값 전수조사".
> 실장비: **없음** — 전부 녹화본 재생 · 합성 입력 · 실측 크롤/live envelope 대조다. 실장비 확인 항목은 7절.

## 1. 결정 (사용자)

| 결정 | 날짜 | 내용 |
|---|---|---|
| D1 | 2026-10-17 | 4채널 모두 보완 · F3b(카드별 예외 격리) 포함 · Windows PortSpeed 64 이상 매핑 추가 · ESXi speed 자릿수 정규화 지금 적용 |
| D2 | 2026-10-18 | `storage.hbas[].link_status` 문자열은 `up` · `down` 둘뿐. **장비가 링크 상태 속성을 주지 않으면 `null`** — 확인되지 않은 상태를 down 으로 적지 않는다. `unknown` 폐지 |
| D3 | 2026-10-18 | 뜻이 달라서 다른 값은 기록만, 같은 뜻인데 다른 값은 고친다 |
| D4 | 2026-10-18 | RAID LUN 은 `logical_volumes` 에도 싣는다(physical_disks 유지) |
| D5 | 2026-10-18 | Portal 은 wwpn null 행도 표시한다 — 누락은 수집 쪽. 누락 장비 벤더는 미확정(Lenovo 로 전해 들었으나 불확실) |

## 2. 재현한 결함과 수정 (채널별)

### 2.1 Redfish (`redfish_gather.py`, 녹화본 변형 재현)

| # | 조건 → 종전 결과 | 수정 |
|---|---|---|
| F1 | iDRAC8 형 짝 없는 FC 기능(`<PortId>-1`) — 부모 포트 Up · 16000 Mbps 를 버리고 unknown/None | 이름으로 찾은 부모 포트의 `LinkStatus` · 속도 상속. F1b: 기능의 포트 링크 두 종류(NetworkPorts/Ports) 모두 색인 |
| F2 | FC 링크 기술 포트에 `Ethernet` 블록만(FibreChannel 블록 없음) + 기능 404 → Ethernet 오분류 → HBA 0 · 오류 0 · success | 판정 함수: 링크 기술 FC 포트의 Ethernet 블록은 Ethernet 근거 아님(None). WWPN 은 포트 주소 배제 규칙으로 |
| F3a | 포트 `Id` 정수 + 짝 없는 기능 → `startswith` TypeError → 섹션 전체 None | `_id_text` 로 문자열 연산 통일(출력 `port_id` 는 raw) |
| F3b | 카드 1장의 예외가 섹션 전체를 지움 | `_collect_one_network_adapter` 추출 · 예외 시 그 카드 부분 항목 롤백 + 비차단 errors[] 1건 |
| F4 | 이름 · 컨트롤러 근거 없는 카드가 FC 기능을 가져도 조용히 제외 | 최상위 기능 링크가 있으면 1회 읽어 기능 ≥1 이면 유지(+notice), 목록 재사용(요청 증가 0) |
| F5 | 1순위 404 + Systems 500 → 404-only 로 둔갑 | 미지원 분류 유지 + notice 문장에 `(다른 경로 실패: …)` |
| F7 | 카드 목록 200 + 카드 GET 전부 404 → 흔적 없이 미지원 | notice `목록 N건 중 읽은 카드 0건(404 M건)` |
| F8 | 한 경로 200 빈 목록이면 다른 경로의 5xx/timeout 이 묻힘 | 404 아닌 실패는 비차단 errors[] |
| — | FibreChannel 블록 포트 + `<PortId>-n` 고아 → 같은 포트 HBA 2건(포트 쪽 wwpn null) | 포트에 붙은 기능이 없고 고아가 있으면 고아 경로만 HBA 를 낸다(lt_fc 가드 일반화) |
| — | 기능에 WWPN 없음 → null(2026-10-15) / 운영 임시 조치는 포트 주소(Dell = WWNN) | `_derive_port_wwpn`: 포트 FC 주소 목록(신 `AssociatedWorldWideNames` · FC 링크 기술 포트의 Ethernet 8옥텟 값)에서 알려진 WWNN 을 뺀 유일값, 구 `AssociatedNetworkAddresses` 는 쓰지 않음, 못 정하면 null + notice |
| — | `link_status` 3값 | `_hba_link_status`: 키 없음 → None + notice `링크 상태 미제공`, 그 밖 up/down |

녹화본 10종 old/new 비교: 요청 다중집합 동일, 산출 차이는 CSUS `fc_hbas[].link_status` unknown → null + notice 2건(의도)과 2.5절 X2 만.

### 2.2 Linux (`gather_hba_ib.yml` · `gather_storage.yml`, 커널 소스 대조 · 합성 sysfs)

| # | 결함 | 수정 |
|---|---|---|
| L1 | `driver` 를 `device/driver` 에서 읽음 — Scsi_Host 장치에는 driver 링크가 없어 실장비 항상 null(합성 시험이 가렸다) | `scsi_host/<host>/proc_name` → PCI 부모 `device/../driver` → 종전 경로 |
| L2 | lpfc 속성명(`modelname` · `fwrev`) 미대응 → 모델/펌웨어 null | qla2xxx · lpfc · bfa 이름 모두 후보(빈 값이면 다음) |
| L3 | `manufacturer` 속성이 FC 드라이버에 없어 vendor 항상 null | PCI uevent `PCI_SLOT_NAME` → `lspci -mm` 제조사/장치명 폴백(자리표시자 제외) |
| L4 | raw rc≠0 무시 → 빈 출력 = "HBA 없음" | storage errors[] 1건(cause=command_failed, rc · stderr) |
| L5 | 값 안의 `\|` 가 필드를 밀어냄 | `tr -d '\|\r\n'` |
| L7 | NPIV 가상 포트를 물리 포트처럼 셈 · FCoE 미구분 | `port_type` 에 NPIV 면 제외 · 드라이버 fcoe/bnx2fc/qedf → FCoE(fnic 은 FC — ESXi/CIMC 와 같은 값) |
| L8 | WWN `0x0` → "0" 문자열 | `normalize_wwn` all-zero(길이 무관) → null |
| — | link_status 부분 문자열 3값 | `port_state` 완전일치: Online·Marginal → up / Offline·Linkdown·Error·Blocked·Bypassed·Loopback·Diagnostics → down / 그 밖·없음 → null |
| X6 | RAID VD 가 physical_disks 에만 | raw `DISKPCI\|<dev>\|<pci>`(`/sys/block` 실경로의 마지막 PCI 주소) + CTRL RAID 클래스 → `logical_volumes[]`(controller_id = PCI) |

### 2.3 Windows (`gather_storage.yml`, 가짜 cmdlet + 실제 powershell.exe)

| # | 결함 | 수정 |
|---|---|---|
| W1 | 빈 catch — 접근 거부 · 제공자 오류가 "HBA 없음" 과 글자까지 같은 출력(rc 0) | `$ErrorActionPreference Stop` + 구성요소(initiator_ports · adapter_attrs · port_attrs)별 `{scope, ok, absent, type, code, error}`. absent(cmdlet 없음 · InvalidNamespace/InvalidClass/NotSupported)는 환경, 그 밖은 storage errors[] 1건(부분 결과 유지) |
| W2 | stdout 이 JSON 이 아니면 `from_json` 예외 → 파일에 block/rescue 가 없어 play rescue 로 다른 섹션까지 소실(Bug B) | rc≠0 또는 `{…}` 모양 아니면 from_json 생략 + storage errors[] 1건(command_failed). IB 스크립트도 같은 가드 |
| W4 | PortSpeed 64 이상 null | 64=32G · 128=20G · 256=40G · 0x200=50G · 0x400=100G · 0x800=25G · 0x1000=64G · 0x2000=128G(T11/SNIA · Linux FC transport 비트, 사용자 결정 — Windows 실장비 미확인) |
| W5 | PortState 미사용 | OperationalStatus 1/없음이면 PortState(2 → up, 3~8 → down) 보강 |
| — | link_status 3값 | 2 → up / 3~8 → down / 그 밖 → PortState → null |
| X6 | BusType RAID 디스크가 physical_disks 에만 | `protocol == 'RAID'` → `logical_volumes[]`(controller_id null) |

### 2.4 ESXi (`collect_network_extended.yml` · `esxi_disks.py`, 모듈 결과 합성)

| # | 결함 | 수정 |
|---|---|---|
| E7 | 하드웨어 iSCSI 클래스 `InternetScsiHba` 에 'iscsi' 부분 문자열 없음 → 조용히 제외 | `'iscsi' in type or 'internetscsi' in type`(공백 제거) |
| E4 | FCoE 를 FibreChannel 로 | 클래스 `FibreChannelOverEthernet*` 또는 FCoE 드라이버(qlnativefcoe · brcmfcoe · qfle3f · bnx2fc · qedf) → FCoE |
| E1/E2 | `speed` 를 Gbps 로 가정(API 는 bps) · down 링크 0 | ≥1e6 → /1e9, ≥1e3 → /1e3, 그 밖 그대로; 0/없음 → null(단위는 실장비 미검증) |
| — | ESXi 7 FC-NVMe 쌍둥이 vmhba 2건 → "ESXi 8 vs Redfish 4" | 같은 (wwpn, wwnn) 1건(첫 vmhba) |
| E8 | 모듈의 깨진 WWN(홀수 자릿수 · int64 음수) 통과 | 8옥텟 colon-hex 아니면 null + storage errors[] 1건(원문 detail). `normalize_wwn` 은 `-` 접두를 다시 묶지 않음 |
| E6 | `location` 'PCI' · `bus` -1 자리표시자 | null |
| E3 | rescue 가 network 오류만 | storage 1건 추가 |
| — | link_status 3값 | online → up / offline → down / unbound·unknown·없음 → null |
| X7/X6 | RAID 뒤 LUN 의 `media_type` 이 컨트롤러 보고값(SSD RAID5 → HDD) · 논리 볼륨 0 | `scsiTopology` 로 LUN ↔ 어댑터 → RAID 면 media null + `logical_volumes[]`(controller_id = vmhba) |

### 2.5 채널 간 값 (같은 물리 서버 2쌍: Cisco C220 FCH2116V1V0 Redfish .2 ↔ esxi02 / Dell R760 GSBPK54 Redfish .34 ↔ r760-6 Linux)

| # | 항목 | 판정 · 조치 |
|---|---|---|
| X1 | `hardware.uuid` Cisco `b190019f-56ce-4ed4-…` vs ESXi `9f0190b1-ce56-d44e-…` | 버그 — CIMC 는 SMBIOS 원시 바이트 순서. adapter `cisco_cimc.yml` `vendor_notes.uuid_byte_order: smbios_raw` → normalize `uuid_byteswap`. Dell 은 원래 같다(.34 `4c4c4544-…` = Linux) |
| X2 | `cpu.max_speed_mhz` Redfish 4000 vs OS 2400/2195 | 버그 — MaxSpeedMHz 는 터보. 정격 원천 순서(BaseSpeedMHz → Oem.Hpe.RatedSpeedMHz → 브랜드 "@ N.NNGHz" → OperatingSpeedMHz → Oem.Lenovo.CurrentClockSpeedMHz), MaxSpeedMHz → `cpu.turbo_max_mhz`(Redfish 추가). 녹화본 10종 전수 확인 |
| X3 | `cpu.logical_threads` Cisco 44 vs ESXi 88 | CIMC 4.1 TotalThreads = 코어 수(펌웨어). `ProcessorSummary.LogicalProcessorCount` 있으면 우선(Dell 48 ✓) — CIMC 는 없어 44 유지(기록) |
| X9 | Dell `NIC.Embedded.1` model null vs Linux 'NetXtreme BCM5720' | FirmwareInventory 이름(FQDD 하위 매칭, MAC 접미 제거) 폴백 |
| X6/X7 | RAID LUN | D4 — 2.2~2.4 |
| X8 · X5 · X12 · X14 · X15 · X17 | 카드 vs PCI 기능 개수 · DIMM locator 표기 · fqdn(resolver 아님) · NIC 펌웨어 표기 · vendor 표기 · 메모리 total 기준 | 뜻이 다름 — 기록만(03-fields) |
| X10 · X11 | lab Cisco hbas 4 vs 2 · link 시점 차 | 사실(CIMC vHBA 정의 vs OS 열거) — 교차 회귀는 "OS ⊆ Redfish" |
| X4 · X13 · X16 | DIMM speed 원천 시점 · bios_date 미제공 · baseline 대문자 WWPN | 재검증/제약/재캡처(NEXT_ACTIONS) |
| 터보 | Dell Redfish 4000 vs Linux 4100 | 같은 뜻 — BMC 스펙값 vs MSR 값(5% 허용, 기록) |

## 3. CSUS 3200 재조사 (사용자 지시 5항목 — 코드 변경 0)

원본 완전 크롤(`HPE_CSUS3200` node01~04, RMC 1.75.108 · Redfish 1.19.0, discovered = fetched_ok, 2,264 문서) + 저장소 녹화본 + 미러 대조.
FC 포트 24개 리소스 키 = `FibreChannel.AssociatedWorldWideNames` · `Id` · `Name` — `LinkStatus` · `Status` 없음(RMC 자기 포트 `Rmp/Ports/*` 에는 있음). 24개 WWPN/WWNN 문자열은 자기 NDF · Port 외 어디에도 없음.
HPE OEM(`Oem.Hpe`)은 NetworkAdapter · Port · NDF 에 없음. `DCD_FCHBA_LINK_*` · `FCHBA` · `LINK_UP/DOWN` 0건, 알림 이력 리소스 없음(LogServices 7종은 디버그 · 설정 · FabricTest, EventService 는 구독 전용).
PCIe 장치 `H3Alert.1.7.LinkUp` 은 RAID 컨트롤러 포함 9개 장치 전부에 있어 슬롯 PCIe 링크다 — FC 링크로 쓰면 항상 up 이 되어 장애를 가린다.
**결론: 이 펌웨어로는 Redfish 로 FC 링크 상태를 수집할 수 없다 → `null` + notice, Portal 은 wwpn 으로 OS 값 조인.** DCD 인벤토리가 있는 node03·04 만 NDF WWNN 노출.

## 4. 검증

- 수치: `docs/ai/catalogs/TEST_HISTORY.md` 2026-10-18. 3채널 `ansible-playbook --syntax-check` 통과(WSL ansible-core 2.20.7). 정적 검사 통과(vendor boundary · schema drift · field dictionary · harness consistency).
- 신규/갱신 시험 목록은 TEST_HISTORY 같은 절. 교차 회귀 `tests/regression/test_cross_channel_same_server.py`: 2쌍 × (serial · uuid · vendor/소켓/코어 · 정격 1% · 터보 5% · 스레드 · hbas WWPN 부분집합 · link_status 값).
- golden 10종 재생성: 차이는 `processors[].speed_mhz`(정격) · `max_speed_mhz`(추가) · CSUS 파티션 cpu 만. 요청 예산 · 다른 키 동일.

## 5. 실장비(Jenkins main Job) 검증과 승격

사용자 승인(2026-10-18, Jenkins 직접 조작 포함)으로 Chrome 의 Jenkins UI 에서 매트릭스를 돌렸다. 자격 값은 파일에 적지 않는다.

### 5.1 1차 — main `b0817907` (Job `clovirone-cicd/clovirone-server-gather-main` #639~#651, checkout SHA 확인)

| 시나리오 | 빌드 | 결과 | 비고 |
|---|---|---|---|
| S1 | #639 | SUCCESS | Linux VM 3대 (.162 .163 .156) |
| S2 | #640 | SUCCESS | 혼합 배치 |
| S3 | #641 | SUCCESS | Linux 10대+ (베어메탈 r760-6 .96 포함) |
| S4 | #642 | SUCCESS | Windows .120 |
| T2 | #643 | SUCCESS | 빠른 실패 |
| T6 | #644 | UNSTABLE | Callback 실패(계약값) |
| E2E-A | #645 | UNSTABLE | cj routing smoke |
| E2E-A2 | #646 | FAILURE | 폐기 Location fail-closed(계약값) |
| E2E-D | #647 | SUCCESS | ESXi 5대 (.1 .2 .3 .91 .92) |
| E2E-E | #648 | SUCCESS | Redfish 7대 (Cisco .2 · Dell .27 .28 .31 .33 .34 · Lenovo 10.50.11.232) |
| T5 | #651 | ABORTED | 사용자 중단 — `[finalize] outcome=aborted`. #649 · #650 은 중단 시점을 놓친 무효 시도(SUCCESS) |

envelope(`gather_final.jsonl`) 대조:

- Redfish 7대 전부 `success` · errors 0. Cisco .2: `hardware.uuid` 9f0190b1-… (ESXi .2 와 같음 — X1 교정 확인), 정격 2200(브랜드) · 터보 4000 · 스레드 44(CIMC TotalThreads — ESXi 88, 문서대로 다름),
  hbas 4(…6e up · …6f up · …8f up · …90 down), logical_volumes 2(RAID5 · RAID0). Dell ×5: 정격 2400 · 터보 4000 · `NIC.Embedded.1` 모델을 펌웨어 이름(BCM5720)으로 채움(notice 1, X9) · logical_volumes 1~3.
  Lenovo: 정격 2000 · 터보 3200 · lv 2.
- Linux r760-6 .96: 소켓/코어/스레드 2/24/48 · 정격 2400(Redfish .34 와 같음, X2) · 터보 4100(Redfish MaxSpeedMHz 4000 — cpufreq vs BMC 스펙값, 교차 회귀 5% 허용 안) · uuid 4c4c4544… 같음 ·
  `logical_volumes` 2(/dev/sda 10.98TB · /dev/sdb 1.7TB, controller 0000:52:00.0 PERC H965i) — Redfish .34 의 3개 중 PERC 2개와 대응(BOSS-N1 VD 는 NVMe 클래스라 OS 에서는 제외, 문서대로) · hbas [] (FC 카드 없음).
- Windows .120(VM): success · hbas [] · lv [].
- ESXi 5대 success. esxi02 .2 hbas 2(FC down · down, WWPN …6e · …6f ⊆ Redfish 4) — **Redfish 는 같은 두 포트를 up** 으로 보고(연속 빌드, 수분 간격): CIMC `Port.LinkStatus` 는 vHBA/업링크 링크,
  ESXi `HostBusAdapter.status` 는 어댑터(패브릭 로그인) 상태 → 뜻이 다른 값(§2.5 X11 의 "시점 차" 추정은 틀렸다 — 계약 문서에 채널별 기준으로 적음). .1 은 소프트웨어 iSCSI 어댑터 1(up).
- **결함 발견**: esxi02(MegaRAID SAS Invader, `lsi_mr3`) · .91/.92(PERC H965i, `bcm_mpi3`) 의 `controllers[].controller_type` 이 `SAS` → RAID 뒤 LUN 이 `logical_volumes` 0건, `media_type` HDD 그대로(X6/X7 미발동).
  .91 BOSS-N1(`nvme_pcie`) 은 `null`. 원인: `_controller_type` 이 `SerialAttached → SAS` 를 드라이버 확인보다 먼저 돌려보냈고(ESXi 7 은 MegaRAID 를 `HostSerialAttachedHba` 로 노출), `bcm_mpi3` 는 HBA·RAID 겸용이라 드라이버로 못 가른다.
  수정: `HostPciDevice.classId` 0x0104(RAID, Linux lspci 와 같은 신호) 1차 → RAID 드라이버 계열 → SerialAttached=SAS → nvme(BlockHba/PcieHba) → class 폴백. `FAILURE_PATTERNS.md` 2026-10-18 항목.

### 5.2 2차 — 수정 commit 이후 (아래에 기록)


## 6. 변경 범위 (Additive)

envelope 13 필드 · `sections` · `status` 불변. 새 top-level 키 0. 사전 안의 변경: `storage.hbas[].link_status` type `string|null` enum up/down, `cpu.turbo_max_mhz` channel +redfish, `storage.logical_volumes[]`(+9 subkey) channel +os/esxi.
모듈 내부 raw 키 추가: `processors[].max_speed_mhz`, `esxi_disks` 결과 `logical_volumes`, Windows HBA 스크립트 `components`, Linux raw `DISKPCI\|` · FC 15필드(앞 11 불변).

## 7. 실장비에서만 확인 가능 (미검증)

FC 링크 up 장비(전 채널 up · speed), Linux/Windows FC 호스트(lpfc 속성 · proc_name · PortSpeed 64+ · MSFC absent/실패 분류), 하드웨어 iSCSI, ESXi FC-NVMe 쌍둥이 · `speed` 단위 · FCoE 클래스 문자열,
CSUS null + Portal 조인, 사이트 "HBA 누락" 장비 경로(F1~F8 중 어느 것인지), Cisco 다른 세대/X-Series UUID 순서, Linux 실 sysfs 링크 모양 시험(Windows 에서 skip — Linux 에서 돈다).
