# 04 — WP4 (C9, FIX 7): firmware[].category — 구조 근거 1순위 + 검증된 토큰 사슬 (04-firmware-001~005 · 008)

- 날짜: 2026-10-27 · 브랜치 `fix/redfish-mock2-20261027`. FIX 7: category enum 을 늘리지 않는다(`hba` 금지) — FC HBA 는 일관되게 `other`. 근거가 부족하면 `other` 유지.
- 사용자 2차 검토 반영: 이름/토큰만으로 BIOS 로 분류하지 않고 Redfish 관계·리소스 의미를 먼저 본다; 근거 부족은 `other`; 전 category 긍정·부정 테스트.

## 1. 구조 근거(2026-10-27 Mock 실측)와 규칙

| 원천 | 실측 | 규칙 |
|---|---|---|
| `Systems/<id>/Bios.Links.ActiveSoftwareImage` | Lenovo → `FirmwareInventory/UEFI`; Dell → `Installed-159-2.26.1__BIOS.Setup.1-1`; HPE iLO 7 · CSUS RMC: 없음 | → **bios** |
| `Managers/<id>.Links.ActiveSoftwareImage` | Lenovo → `BMC-Primary`; Dell → `Installed-25227-7.00.00.184__iDRAC.Embedded.1-1`; HPE · CSUS: 없음 | → **bmc** |
| 멤버 `RelatedItem` 이 `…/Bios` | Lenovo `UEFI`·`UEFI-Pending` | → **bios** |
| 멤버 `RelatedItem → Managers/<id>` | Lenovo `BMC-Primary`·`BMC-Backup`·`BMC-Primary-Pending` **과 `HPM-FPGA`·`HPM-FPGA-Pending`** | **bmc 근거로 쓰지 않는다** (FPGA 가 같은 링크를 가짐 — 음성 테스트) |
| CSUS `ComplexFW` / `Partition0_FW` | RelatedItem → `Chassis/RackGroup` / `Systems/Partition0`, ActiveSoftwareImage 없음 | 구조 근거 없음 → **other 유지** (Description 산문은 근거가 아니다) |

- 모듈(`redfish_gather.py`): `gather_bios`·`gather_bmc`·`gather_firmware` 가 **이미 받은 응답**에서 링크를 읽어(요청 0) `_collect_all_sections(aux_out)` 가 `firmware_links = {firmware[].id: {bios|bmc}}` 를 조립, `main()` 이 모듈 최상위 `firmware_links` 로 내보낸다(`data` 밖 → GOLDEN_KEYS·envelope 키 불변, 15 fixture golden 차이 0). Dell 은 ActiveSoftwareImage(`Installed-…`)와 first-seen `Current-…` 를 dedup key 로 대조(04-firmware-008).
- normalize(`_rf_firmware_categorized`, 단일 if/elif 사슬, regex 없음): 1순위 `links.bios/bmc` → 2순위 토큰 `diagnostic` → `bios|system rom|uefi` → `cpld|programmable logic|fpga` → `tpm` → `usc|lifecycle` → `driver` → `ubm|bc bp` → `disk` → `backplane` → `raid|perc|megaraid` → `drive|nvme|ssd|hdd|boss` → `service` → `idrac|ilo|xcc|cimc|bmc` → FC HBA 토큰(**other**) → `video|graphics`(**other**) → 3순위 같은 봉투 `storage.controllers[].controller_model` 과 이름 일치(storage_controller) → `nic|ethernet|broadcom|mellanox|gbe` → `psu|power supply` → `controller`(폴백). 토큰 추가 근거는 normalize 주석에 적었다(실측 이름: HPE PLD/Embedded Video Controller/SN1610Q, Lenovo UEFI/HPM-FPGA/QLE2772, Dell QLogic).

## 2. 테스트

- 기존 `tests/unit/test_firmware_category.py`(Dell 13 · CSUS 2 · HPE 7 · Broadcom RAID/NIC 3 · drive) 전부 통과 — 기대값 변경 0 (CSUS `other` 유지 포함).
- 신규 `tests/unit/test_firmware_category_structure.py`: enum 14값 각각 긍정 ≥1(총 39) · 부정 ≥1(총 19, 실제 도착 category 도 고정) — 전부 실 미러 이름; 구조 근거가 토큰보다 우선; 컨트롤러 조인은 같은 봉투의 controller_model 과 일치할 때만; `_firmware_links_by_id` 의 Dell dedup key 대조·빈 입력.
- 모듈 `firmware_links` 실녹화 확인: Lenovo `{BMC-Primary: bmc, UEFI: bios, UEFI-Pending: bios}` · Dell `{Current-159-…BIOS…: bios, Installed-25227-…iDRAC…: bmc}` · HPE · CSUS `{}`.
- 단위 subset(dryrun·phase3·CSUS·audit·category·bios·power-off) 369 passed · `tests/integration -m "not live"` 496 passed · `tests/e2e tests/regression` 1094 passed(`tier0/*_after_wp4.log`).

## 3. 18 label 전후 매트릭스 (Tier 1 before ↔ after-WP4, `04-firmware-category-matrix.md`)

- 18 label 항목 수 합 = 변화 **61건**, 다른 키는 변화 0 (`04-firmware-category-matrix.md` 에 id·name·before→after 전수).
  - **Lenovo 5 label**(v4 ×4: 6건씩 · 1차 r1: 8건): `UEFI`·`UEFI-Pending` other → **bios**(구조 근거), `HPM-FPGA`(·`-Pending`)·`SCM-FPGA` other → **cpld**,
    `Drive_Backplane_…_PSoC_0xBB`(·`-Pending`) drive → **backplane**, 1차의 `ThinkSystem M.2 RAID B540p-2HS … Enablement Kit` other → storage_controller(raid 토큰).
  - **HPE 5 label**(gen12_01 6 · 02/04 5 · 03 4 · 1차 5): `System/PCIe Riser N Programmable Logic Device` other → **cpld**, `HPE MR416i-o Gen11`/`MR408i-o Gen11` other → **storage_controller**(controller_model 조인; 전원 Off gen12_03 은 Storage 0 이라 조인 대상 없음 → other 유지), `Embedded Video Controller` storage_controller → **other**.
  - **Dell 1 label**: `QLogic QLE2692 16Gbps Dual Port Fibre Channel Controller` ×4 storage_controller → **other**(FC HBA 일관, FIX 7).
  - **CSUS 7 label**: 변화 **0** — `ComplexFW`·`Partition0_FW`·PCIe 보충(MLX nic · SR3258p storage_controller · SN1100Q FC HBA other · CRPS psu) 전부 종전과 같다.

## 4. Tier 1 after (18 label, `tier1-after-WP4/` ↔ `tier1-after-WP2/`, 허용목록 = WP3 + `data.firmware[*].category`)

- 18/18 rc 0 · success · errors 0, 요청 집합 18 label 전부 불변(+0/-0). `_diff_vs_after_wp2.md`: **허용목록 밖 차이 0** — 설명된 변화는 WP3(DL380 5 label) + `data.firmware[*].category` 61건뿐. CSUS 7 label 바이트 동일.
- `firmware_links` 는 모듈 최상위 키라 최종 봉투 13 필드에 나타나지 않는다(envelope 키 불변).

## 5. 처분

| 이슈 | 처분 | 근거 |
|---|---|---|
| 04-firmware-001 (Lenovo `UEFI` other · CSUS `Partition0_FW` other) | **FIXED**(Lenovo — Bios.Links.ActiveSoftwareImage/RelatedItem 구조 근거로 bios) + **VALIDATED_EXISTING**(CSUS — 구조 근거 없음, `other` 유지가 맞다; 사용자 2차 검토) | 1절, 매트릭스 |
| 04-firmware-002 (HPE RAID 컨트롤러 other · Embedded Video Controller 가 storage_controller) | **FIXED** | controller_model 조인 → storage_controller, video/graphics → other |
| 04-firmware-003 (Lenovo 백플레인 PSoC 가 drive) | **FIXED** | 사슬 순서 disk > backplane > raid > drive |
| 04-firmware-004 (FC HBA 분류 벤더 간 불일치) | **FIXED** | FC HBA 토큰 → other (FIX 7, enum 불변) — Dell/HPE/Lenovo/CSUS 일관 |
| 04-firmware-005 (CPLD/FPGA 잔여 other · nvme 토큰 오분류) | **FIXED** | programmable logic/fpga → cpld; raid 가 nvme 보다 먼저 |
| 04-firmware-008 (Dell first-seen dedup 접두사 혼재) | **FIXED** | ActiveSoftwareImage(`Installed-…`) ↔ first-seen(`Current-…`) dedup key 대조 |
| 04-firmware-009 / 010 | OBSERVATION_ONLY | 전원 Off raw `updateable` · Lenovo 버전 표기 2종 — 변경 없음 |
| 04-firmware-006 | → WP5 | Disabled·Version 없는 -Pending 제외 |
| 04-firmware-007 / 011 / 012 | → WP8 (DOC_CORRECTED) | 사전 `updateable boolean|null` · CSUS bios/bmc 항목 없음 각주 · `data.firmware` 절 + category help |
