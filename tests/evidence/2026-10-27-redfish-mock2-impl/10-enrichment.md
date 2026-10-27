# 10 — WP10 (C8): 기존 필드 보강 — 요청 추가 0 (01-hardware-004 ≡ 04-bios-001 · 02-memory-004 · 03-network-004 · 03-network-006 · 03-network-007 · 03-storage-003 · OEM 캐시)

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027`. 원칙: 값 채움은 기존 키에, **새 키는 원천이 있을 때만 모듈이 낸다**(golden 변경은 전부 `golden-changes.md` G-18~G-23). 요청 수 변화 0(15 fixture 예산 불변 · Tier 1 요청 집합 불변). 벤더 이름 분기 없음 — OEM 네임스페이스 키의 존재로만 가른다(라이브러리 OEM 추출 분기).
- 03-network-002(링크/속도 보충)는 WP5 에서 끝났다.

## 1. 규칙 · 구현

| 이슈 | 규칙 | 구현 | 18 label 영향 |
|---|---|---|---|
| 03-network-004 | 포트 `CurrentLinkSpeedMbps 0` 은 '0 으로 협상' 이 아니라 링크 없음 → `null`(Gbps 경로 SCHEMA-02 와 통일). 호스트 NIC `interfaces[].speed_mbps` 의 0 은 원문 그대로 | `_normalize_port_speed` | r1_DELL_R740 `network.ports[]` 10건 0 → null(down 14 중 Ethernet 10 · FC 4 는 이미 null). 2차 11대는 Ports(Gbps) 라 불변 |
| 03-network-007 | 호스트 EthernetInterface 에 `MTUSize` 가 없으면(18대 전부) 같은 MAC 의 NetworkDeviceFunction `Ethernet.MTUSize` 로 `interfaces[].mtu` 를 채운다 — normalize 층, null 일 때만 | `_fetch_ndf_index` 가 `mtu`·`macs` 보존 → `_collect_one_network_adapter(..., mtu_out)` → `_collect_all_sections` aux `ndf_mtu_by_mac`(data 밖, `firmware_links` 와 같은 패턴) → `site.yml` 모듈 결과 `_rf_raw_collect.ndf_mtu_by_mac` → `_rf_norm_interfaces_bundle` MAC join | XCC 3 V4 4대(NDF MTU 4 · 4 · 10 · 4) · iLO 7(1차 6 · gen12_01 10) 에서 MAC 이 맞는 NIC 만 1500. `ports[]` 에 새 키 없음 |
| 03-network-006 | `IPv6Addresses[]` 를 같은 `addresses[]` 모양(`family ipv6` · `prefix_length` · `origin`)으로. 모듈은 값이 있을 때만 `ipv6` 키(실측 18대 전부 빈 목록) | `gather_network` · `_normalize_network_raw`(partitions) · bundle ipv6 루프 | 18 label 불변(합성 · DMTF mockup 4건 · 에뮬레이터 2건으로 검증) |
| 03-storage-003 | `Drive.Identifiers` 의 NAA/EUI DurableName → `physical_disks[].wwn` = `naa.<hex>`/`eui.<hex>`(소문자 — ESXi canonicalName 과 같은 꼴, Linux 는 `0x` 접두). 모듈은 원천 있을 때만 키, 최종 JSON 은 항상 키(없으면 null — OS/ESXi 와 같은 모양) | `_drive_wwn` · `_extract_storage_drives` · `_rf_norm_physical_disks` · 사전 channel redfish 추가 | iLO 7 Gen12(2 · 4 · 4 · 1차 2) · iDRAC9(4) 값, XCC 3 · RMC null. 18 label 최종 JSON 에 `wwn` 키 추가 |
| OEM 캐시(02-cpu §5) | 소켓당 L2/L3 KB — iLO `Oem.Hpe.Cache[]` · XCC `Oem.Lenovo.CacheInfo[]` · iDRAC `DellProcessor.Cache{N}Level/InstalledSizeKB` · RMC `Oem.Hpe.L3CacheSize` 문자열("22.50 MB" → 23040) | `_processor_cache_kb` · `_cache_string_kb` · `gather_processors`(원천 있을 때만 키) · `_rf_summary_cpu` groups · 사전 channel redfish 추가 | 18 label `cpu.summary.groups[].l2/l3_cache_kb`: 6737P `65536`/`147456`(DL380 Gen12 · SR650 V4) · 6724P `32768`/`73728`(1차 SR650) · R740 `24576`/`36608` · CSUS L3 만(`46080`/`76800`/`23040`, L2 null) |
| 02-memory-004 | `RankCount` 가 없을 때만 HPE OEM `Label` `<n>Rx<m>` 의 n(값을 지어내지 않음 — error_correction 은 관찰 유지) | `_memory_rank_count` | CSUS 7 label `memory.slots[].rank_count`(+partitions) null → 1 |
| 01-hardware-004 ≡ 04-bios-001 | System · OEM 날짜가 없을 때만 구조 근거(`firmware_links` bios — `Bios.Links.ActiveSoftwareImage` · `RelatedItem /Bios`)로 잡힌 FirmwareInventory 항목의 `ReleaseDate`(연도 0000 제외) → `hardware.bios_date` + notice 1건 | `gather_firmware(..., dates_out)` → `_collect_all_sections` 폴백(`_fw_links_final` 재사용) | Lenovo 5 label `2026-05-11` ×3 · `2026-06-22` · `2025-03-15`; iLO(OEM 날짜) · iDRAC(OEM — FirmwareInventory 와 같음 교차 확인) · CSUS(근거 없음) 불변 |

## 2. 테스트 (Tier 0)

- 신규 `tests/unit/test_redfish_enrichment_wp10.py` **70건**: 포트 속도 6케이스 + R740 재생(down 14 전부 null · up 10000 유지 · adapter fold-in 불변), NDF MTU aux(SR650 V4 03: 10 MAC · 1500 · ports 새 키 없음 · bundle 렌더 채움/미채움 · 호스트 MTU 우선 · 4 fixture 건수), IPv6 합성(키 유무 · bundle family ipv6 · partitions), `_drive_wwn` 9케이스 + 6 fixture 키 유무/정규화 렌더, 캐시 OEM 10케이스 + 문자열 10 + 4 fixture 값 + 그룹 null, rank 7케이스 + CSUS 32 슬롯 + XCC 불변, bios_date 6 fixture + 0000 자리표시자 합성.
- `emulator_harness.run_gather` 가 `aux`(GOLDEN_KEYS 밖)를 함께 돌려준다(테스트용). golden 동일성 묶음 **454 passed** · `tests/integration -m "not live"` **497 passed**(비실측 golden 6세트 갱신 뒤) · `tests/e2e tests/regression` **1094 passed** · unit 전체 **5197 passed · 33 skipped · 0 failed**(22분 18초) · WSL syntax 3채널 · 엔진 23 · `validate_field_dictionary.py` PASS(262) · drift 정합.

## 3. Golden · 사전 · 문서

- G-18~G-23: 실측 15 + DMTF mockup 1 + HPE 에뮬레이터 5 — 평탄 비교로 바뀐 경로가 6 묶음뿐임을 확인한 뒤 썼다. 요청 예산 15/15 불변.
- 사전: `storage.physical_disks[].wwn` · `cpu.summary.groups[].l2/l3_cache_kb` channel redfish 추가(help 에 원천) · `memory.slots[].rank_count` · `hardware.bios_date` help · **`network.interfaces[].mtu` 등재**(262 항목). 03-fields 6.1(bios_date 폴백) · 6.2(캐시 · rank) · 6.3.0(wwn 행 · "redfish 는 serial 만" 정정) · 6.4(포트 0 · mtu · ipv6). EXTERNAL_CONTRACTS 2026-10-27 행 7건.

## 4. Tier 1 after (18 label, `tier1-after-WP10/` ↔ `tier1-after-WP9/`, `_allow.json` 9항목)

- 18/18 rc 0 · success · errors 0 (build `mirror-replay-wp10-after`), **요청 집합 불변**(18 label +0/-0). `_diff_vs_after_wp9.md`(허용목록 9항목): **허용목록 밖 차이 0**; 가드 항목(`network.summary` · `memory.summary`)은 한 label 도 걸리지 않았다(요약 불변).
- `interfaces[].mtu` 1500 채움: dl380_gen12_01 10/10 · r1_HPE_DL380_01 6/6 · sr650_v4_01/02/04 4/5 · sr650_v4_03 10/11; 나머지 11 label 은 NDF MTU 가 없어 null 유지(CSUS · Dell · gen12_02/03/04 · 1차 SR650).
- `network.ports[].current_link_speed_mbps`: r1_DELL_R740_01 10건 0 → null(down Ethernet), 그 밖 불변.
- `storage.physical_disks[].wwn` 키 18 label 추가 — 값: dl380_gen12_01 2/2 · _02 4/4 · _04 4/4 · r1_HPE_DL380 2/2 · r1_DELL 4/4(`naa.5000c5…`); XCC 3 · RMC 는 null(gen12_03 · 1차 CSUS 01/02 는 디스크 0).
- `cpu.summary.groups[].l2/l3_cache_kb`: DL380 Gen12 · SR650 V4 6737P `65536`/`147456`, 1차 DL380 `49152`/`147456`, 1차 SR650 6724P `32768`/`73728`, Dell `24576`/`36608`, CSUS L2 null · L3 `46080`(45 MB) · `76800`(75 MB, csus3200_02) · `23040`(22.50 MB, 1차 01/02).
- `memory.slots[].rank_count`: CSUS 7 label 전부 null → 1(32/16/16 · 16/16/32/32 슬롯; partitions 도 같음); RankCount 보유 11 label 은 2 그대로.
- `hardware.bios_date`: Lenovo 5 label null → `2026-05-11`(v4_01/02/04) · `2026-06-22`(v4_03) · `2025-03-15`(1차) + notice `BIOS 날짜를 FirmwareInventory UEFI 의 ReleaseDate 로 채움 (System · OEM 에 날짜 없음)` 1건씩; iLO · iDRAC · CSUS 불변.
- `status` · `sections` 불변. INV-5 위반 0 · interfaces 수 불변. 디스크·FC 포트 개수 정합 18/18 PASS · UNEXPLAINED 0.

## 5. 처분

| 이슈 | 처분 |
|---|---|
| 03-network-004 · 03-network-007 · 03-storage-003 · 02-memory-004 · 01-hardware-004 ≡ 04-bios-001 | FIXED |
| 03-network-006 | FIXED (합성 · DMTF mockup 검증 — 실측 18대는 IPv6 없음) |
| 02-cpu §5 캐시(이슈 ID 없음 — 관찰 표) | FIXED (Plan WP10 명시) |
| 03-network-002 | FIXED (WP5) |
