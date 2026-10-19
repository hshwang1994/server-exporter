# ADR-2026-10-19 — HPE CSUS 3200 단일 서버 정합 · 수집 범위 보완 · 3채널 summary 결함 정비

- 상태: Accepted (사용자 결정 2026-10-19)
- 범위: Redfish(HPE CSUS 3200 · Superdome Flex adapter, 전 벤더 summary 식) · OS(Linux/Windows summary) · ESXi(summary · 시리얼 · hostname · datastore) · 수집 범위 감사 시험 3종
- 폐기 · 개정하는 결정: 2026-10-17 "CSUS 시리얼 접미사 제거는 OS · Redfish 만(ESXi 제외) · CSUS 3200 만(Superdome Flex 제외)" → ESXi 와 Superdome Flex 로 확장.
  2026-10-18 X3 "ProcessorSummary.LogicalProcessorCount 가 있으면 정본" → adapter 가 "코어 수" 라고 밝힌 펌웨어는 per-processor 합이 정본.
- 정본: `docs/contract/03-fields.md` 6.1 · 6.2 · 6.3 · 6.3.2 · 6.4 · 6.5 · 6.7 · FAQ, `schema/field_dictionary.yml`, `docs/develop/05-field-mapping.md`,
  `tests/evidence/2026-10-19-csus-single-server-summary-audit.md`, `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` 2026-10-19

## 컨텍스트 (Why)

- 사용자(2026-10-19): CSUS 3200 은 사이트 협약상 파티션 1개만 쓰므로 **다른 x86 서버와 같은 JSON 형태**로, Partition0 = 서버로 취급해야 한다. 시리얼은 `-000`(nPar 접미사)을
  뗀 물리 시리얼을 유지한다. 보고된 증상 "디스크 구성·합계가 보이는 CSUS 는 hbas 가 없고, 디스크가 없는 CSUS 는 hbas 가 보인다"(운영 중인 서로 다른 두 장비, JSON 반출 불가).
  이어 "다른 채널도 **아는 것만 불러서** 빠지는 것 아닌가 — 전체 mock · 전체 API 를 대조하고 있나" 라는 질문.
- 실 4노드 전수 미러(`C:\github\서버mock데이터\HPE_CSUS3200\01~04`, RMC 1.75.108) 를 현재 코드로 재생 + `normalize_standard.yml` 을 실제 ansible-core 템플러로 렌더한 결과:
  디스크(node03/04 SAS SSD 2)와 HBA(8)는 **함께** 나온다 — 보고된 상호배제는 4노드로 재현되지 않았다. 대신 다음이 확정됐다.
  1. `power.summary.total_capacity_w = 0` · `consumed_capacity_pct = 0` — PSU 4개 전부 용량 미제공인데 0(거짓 값).
  2. `network.summary.adapter_count` 가 FC HBA 카드를 셈(node01: NIC 0장인데 2).
  3. `cpu.logical_threads` 32/64 — RMC `ProcessorSummary.LogicalProcessorCount` 는 **코어 수**(Bios `HThread: Enabled`, `TotalThreads == 2×TotalCores`)인데 X3 규칙이 그 값을 우선.
     같은 봉투의 `multi_node.partitions[0].cpu.logical_threads`(합산 64/128)와도 불일치.
  4. node01/02 `storage.controllers[0]` = "Npar 0 Storage" — 모델 · 드라이브 · 볼륨 전무한 빈 컨테이너.
  5. `hardware.part_number` null — Partition0 에 없고 Chassis(`R9N70A`)에만 있다.
  6. 수집 범위: RMC 가 노출한 637개 리소스 중 205개만 요청. 안 읽는 인벤토리 — `Chassis/PCIeDevices`(RAID 컨트롤러 정체 · NIC/HBA/RAID 펌웨어는 여기에만), `Chassis/Drives` 컬렉션,
     `Systems/NetworkInterfaces`, 2번째 이후 섀시의 Power/Thermal. Dell R740(6014/137) · HPE DL380(2022/131) · Lenovo SR650(2898/123) 도 PCIe 트리 · NetworkInterfaces 는 전 벤더 공통 미요청.
     ESXi 는 `runtime.healthSystemRuntime`(센서 126) 미사용, Linux 는 명령 덤프 108종 중 ipmitool · lshw · smartctl · storcli 파서 없음. 저장소 기록상 "노출 vs 수집" 전수 대조는 이번이 처음.
- OS/ESXi summary 조사(서브에이전트 3건, 파일:라인 확인): Linux 메모리 총량 모르면 0, Linux VLAN 하위 IF 중복 집계, OS/ESXi 가 speed 미보고 포트를 summary 에서 빼서 `link_up_count==quantity`
  항상 성립, ESXi `physical_disks[].protocol` 항상 null, ESXi datastore `freeSpace=None` → 0 → usage 100%, ESXi 텍스트 폴백 KB/PB 오독, ESXi hostname 이 IP 첫 옥텟, Linux zram/nbd 가 디스크로 집계,
  DIMM<512MiB 가 0 GB 그룹, `cores_per_socket` 뜻이 채널마다 다름.

## 결정 (What)

1. **`data.multi_node` 는 그대로 둔다** (사용자 결정 — 삭제 · 내부 시리얼 변경 없음. `partitions[].system.serial` 은 2026-10-17 대로 원문).
2. **`-NNN` 접미사 제거를 ESXi 채널과 Superdome Flex 모델에도 적용**한다 (`filter_plugins/serial_normalizer.py` — Superdome 패턴은 adapter 미러, ESXi `normalize_system.yml` 두 자리).
   세 조건(HPE alias · CSUS 3200/Superdome Flex 모델 · `-[0-9]{3}$`)이 전부 맞을 때만 동작한다 — 다른 서버는 바뀌지 않는다.
3. **adapter `vendor_notes.processor_summary_logical_count: cores`**(CSUS 3200 · Superdome Flex) — `cpu.logical_threads` 는 per-processor `TotalThreads` 합을 우선. 다른 adapter 는 X3 그대로.
   값으로 가르고 vendor 이름으로 가르지 않는다(rule 12). Superdome 은 같은 RMC 계보 + 사용자 지시(실측 시 정정).
4. **`power.summary`**: 용량을 아는 PSU 가 0개면 `total_capacity_w: null`, `consumed_capacity_pct` 는 total/consumed 를 모르면 null (전 벤더, 0 은 거짓 값). `redundant` 는 종전(설치 수 ≥ 2).
5. **`network.summary.adapter_count`**: 포트가 전부 FC/FCoE/IB 인 카드는 세지 않는다(그 카드는 `storage.hbas`/`infiniband` 로 요약). 포트 정보가 없는 카드는 센다. `network.adapters[]` 목록은 그대로.
6. **Redfish 수집 범위 보완 — 전부 "정보가 없을 때만" 발동**(정보를 주는 벤더는 요청 · 골든 불변):
   A-5 섀시 NetworkAdapters 가 404 · 빈 목록이면 `Systems/{id}/NetworkInterfaces` → `Links.NetworkAdapter` 로 카드를 찾는다(DMTF 표준 링크) · A-7 System 에 PartNumber/SKU 가 없으면 섀시 값 ·
   A-8 StorageControllers 없는 Storage 멤버는 드라이브 위치(ServiceLabel) ⊂ PCIe 슬롯 위치인 `PCIeDevice` 를 컨트롤러로 식별(후보 1개일 때만, 위치 포함 관계만 — 모델 이름 추정 금지) ·
   A-9 adapter `firmware_inventory_scope: complex_only` 면 PCIe 장치 · PSU 펌웨어를 `firmware[]` 에 보충 · A-10 Storage 에 드라이브 0건이면 섀시 `Drives` 컬렉션 폴백 ·
   A-11 System 이 연결한 섀시가 2개 이상이면 Power/Thermal 합산(소비·용량은 전 섀시 값이 있을 때만 합, min/avg/max 는 null).
7. **빈 Storage 컨테이너 제거(A-6)**: 컨트롤러 정체 · 드라이브 · 볼륨이 전부 없는 멤버는 `controllers[]` 에서 뺀다(normalize). `physical_disks` · `logical_volumes` 영향 없음.
8. **3채널 summary 결함(B-1~B-12)**: 메모리 총량 모르면 null(Redfish 는 `total_mb` 폴백) · Linux VLAN/멤버 제외 · OS/ESXi speed 미보고 포트도 `speed_mbps: null` 그룹으로 집계 · ESXi `protocol` 을 LUN 어댑터
   종류로(RAID 뒤 LUN 은 null) · ESXi vmnic `link_type: ethernet` · ESXi datastore `freeSpace None` → null · 텍스트 단위표(B/KB/MB/GB/TB/PB) · ESXi hostname IPv4 꼴 → null · Linux zram/nbd/drbd/ram/fd 제외 ·
   `cap_gb > 0` 가드 · Redfish `cores_per_socket = total_cores // sockets` · ESXi 깨진 WWN 검사는 hbas 에 남는 vmhba 만.
9. **"노출 vs 수집" 범위 감사 상시화(C-1~C-3)**: Redfish(저장소 안 전수 크롤 4벤더) · ESXi(pyvmomi 덤프) · OS(명령 덤프) 각각 허용 목록(사유 포함)에 없는 미요청 인벤토리가 생기면 실패하는 회귀 시험.
   새 데이터 원천(ESXi 센서 → power/thermal · Linux iSCSI 이니시에이터 · RAID 뒤 물리 디스크 CLI · OS ipmitool)은 **결정 항목**으로 NEXT_ACTIONS 에 둔다(이번에 구현하지 않는다).

## 결과 (Impact)

- envelope 13 필드 · `sections` · `status` 판정 불변(Additive — 값만). 호출자가 볼 변화: 전 벤더 `power.summary.total_capacity_w/consumed_capacity_pct` 0 → null(용량 미제공 장비),
  `network.summary.adapter_count` 감소(FC 카드 보유 장비), OS/ESXi `network.summary.groups` 에 `speed_mbps: null` 그룹 추가, ESXi `physical_disks[].protocol` 채움, Linux `memory.summary.grand_total_gb` 0 → null.
- CSUS(실 4노드 재생): `cpu.logical_threads` 32→64 · 64→128, `hardware.part_number` null → `R9N70A`, node01/02 `controllers` [] , node03/04 `controllers[0]` = `HPE SR3258p-16i/e PCIe4 Controller`(Adaptec · fw 03.01.44.040-0),
  `firmware[]` 2건 → 6(node01: +PSU 4) / 15(node03: +PCIe 9 · PSU 4), `adapter_count` 2→0 · 8→4, hbas 4 · 8 불변. 요청 수 node01 134 → 141(+7: Drives 1 · PCIeDevices 컬렉션 1 · 미캐시 장치 5), node03 +2.
  ESXi/Superdome 시리얼 접미사 제거.
- 보고된 "디스크 ↔ HBA 상호배제" 는 코드로 재현되지 않았다 → 수집 경로 1개 추가(A-5) + 빈 결과 사유(notice) + 사이트에서 장비 JSON 을 직접 읽는 체크리스트(NEXT_ACTIONS)로 대응.
- 거짓 값 위험: Superdome Flex 패턴 · 플래그는 실측 없이 CSUS 와 같다고 본 것(사용자 지시) — Superdome 실측 시 정정.

## 대안 비교 (Considered)

| 대안 | 평가 |
|---|---|
| `data.multi_node` 를 null 로(다른 x86 과 같은 모양) | 사용자가 "지금 그대로 유지" 선택 — 중복 정보지만 소비자 영향 불확실 |
| `logical_threads = max(LogicalProcessorCount, ΣTotalThreads)` | HT 비활성 장비에서 TotalThreads(지원 수)가 과대집계 → adapter 플래그(펌웨어 사실)로 가른다 |
| 컨트롤러 정체를 모델 문자열("Controller"/"RAID")로 추정 | 벤더/모델 이름 추정 금지(rule 12) — 드라이브 위치 ⊂ 슬롯 위치의 포함 관계만 쓴다 |
| PCIe 펌웨어 보충을 전 벤더에 | Dell/iLO 는 FirmwareInventory 가 이미 담아 중복 — adapter 범위 선언(complex_only)이 있는 장비만 |
| ESXi 센서로 power/thermal 즉시 구현 | `sections.power/thermal` not_supported → success 는 호출자 계약 변화 → 결정 항목으로 등재 |
