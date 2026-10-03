# 2026-10-03 — Phase 2 정확성·호환성 수정 (ClovirONE Gathering 작업계획 §11 Phase 2)

> 기준: main `70859e08`(Phase 1.5) 위에 적용. 오프라인(단위·렌더·재생) 검증만 — 실장비 동등성(.96/.165/.120/.1·.2/BMC)은
> 이 세션의 실행 환경이 Jenkins 빌드·VM/BMC 접근을 거부해 **미실행** (`docs/ai/NEXT_ACTIONS.md` GP-1~GP-5). 통과로 쓰지 않는다.
> 7-판정과 설계 근거는 승인 Plan §3·§7. 각 항목은 "수정 전 FAIL → 수정 후 PASS" 를 테스트로 남긴다.

## 1. Redfish 라이브러리 (`redfish-gather/library/redfish_gather.py`) — C5 · C6 · C7 · C9 · S1

| ID | 수정 | 근거 테스트 |
|---|---|---|
| C5 | `_collection_members`/`_nextlink_path` 신설 — 모든 Members 루프(processors · memory · storage drives/volumes/SmartStorage · network · BMC NIC · NDF · network adapters · ports · firmware · power PSU/telemetry · thermal fans/sensors · log services · multi-node composition/fabrics/멤버 URI)가 `Members@odata.nextLink` 를 **opaque URL** 로 따라간다(urljoin, 같은 origin 만, `$skip/$top` 계산 없음, 순환 차단, 페이지 64·멤버 1024 상한). 후속 페이지 실패·상한·다른 origin 은 **앞 페이지 멤버 보존** + 비차단 code 오류(→ 섹션 failed, status partial). `Members@odata.count` 불일치는 notice, 부재는 조용히. AccountService 컬렉션은 4-상태(unknown) 의미가 있어 이번 범위 밖 | `tests/unit/test_redfish_phase2_contracts.py` (nextLink 7 사례 · 페이지 순서 · 실패 보존 · 순환/타 origin 무요청 · count notice · errors=None 호출부 notice) |
| C5 | gather_memory: 장착 DIMM 의 `CapacityMiB` 부재 — 전부면 `total_mib=None` + 오류(비차단), 일부면 `None` + notice, slot 은 전부 보존(과소집계 금지). partition 은 **자기 System 의** MemorySummary 로만 fallback(`_normalize_memory_raw(raw, raw_sys)`) | 같은 파일 memory 4 사례 |
| C6 | gather_firmware 규칙 통일: 동일 컴포넌트·동일 version 중복(Installed-/Current-/Available-/Rollback- 접두사 차이)만 **GET 전** URI tail 로 dedup(first-seen → `firmware[].id` 불변), Previous- 는 GET 도 하지 않음, 접두사 우선순위로 version 선택 안 함, 선택 멤버 GET 실패 시 같은 key 대체 멤버 1회 fallback, 전부 실패면 비차단 오류 + stub 미출력, Name 만 있고 Version 없는 inline 멤버는 상세 1회 조회 | R740 재생: 멤버 GET **62 → 32**, golden firmware 32건 동일; 다른 version 보존 · 대체 fallback · stub 금지 · Name-only 1회 · Previous 미조회 |
| C7 | `_normalize_wwn` all-zero 16-hex → `None`(filter_plugins 와 일치); `_fetch_ndf_index` 의 404 외 실패를 비차단 오류로 가시화(종전 조용히 빈 리스트) | WWN 5 사례; NDF 는 호출부 errors 전달(코드) |
| S1 | `_CODE_NON_BLOCKING_SUBRESOURCE` — 멤버 수준 GET 실패(DIMM·CPU·NIC·drive·volume·SmartStorage controller·adapter·ports·NDF·firmware 멤버·페이지네이션)의 401/403 문자열은 `_compute_final_status` 의 host 판정에서 제외. 컬렉션/앵커 수준 401/403 은 종전대로 failed(자격 오류 → 후보 재시도 유지) | 멤버 403 → partial, 컬렉션 401 → failed |
| C9 | `_confirm_account_state` 가 `(ok, mismatches)` 반환(None=다시 읽지 못함). 4 호출부 모두 `recovered = 재인증 성공 AND ok is not False`; 재인증은 됐지만 노출 속성 불일치면 `verification='state_mismatch'`, 추가 쓰기(삭제/재생성) 없음. 쓰기 payload·401 게이트·예산 불변 | `test_confirm_account_state_returns_ok_and_mismatches`, `test_recovery_sites_gate_on_state`; 기존 `test_account_family_and_write_contract.py::test_post_write_state_mismatch_is_surfaced` 를 새 계약으로 갱신(+ 정상 일치 시 verified 회귀) |

재생 계수(`emulator_harness.run_gather`, 네트워크 0): real_dell_r740 GET **167 → 137**(firmware 멤버 62 → 32), real_hpe_csus3200 217 → 217, real_hpe_dl380 131 → 131, real_lenovo_sr650 123 → 123. golden(`tests/integration/test_real_capture_replay.py`) 4 fixture 모두 strict 일치 유지 — 경로 집합 변화는 R740 firmware 멤버 GET 감소뿐(Phase 3 의 `request_budget.json` 초기값).

## 2. 실패 envelope shape 통일 (N2 / C10) — `callback_plugins/json_only.py`, `redfish-gather/site.yml`

- 콜백 보충 envelope(`_build_fallback_envelope` · `_minimal_envelope`)과 Redfish `always` fallback 이 rescue 경로(`build_failed_output.yml`)·os/esxi always(2026-09-03) 와 같은 모양: `hostname=null`(IP 대체 금지), `sections` 11 키(채널 지원 섹션 failed, 나머지 not_supported), `meta` 6 키 null, `correlation` 4 키(host_ip, redfish 는 bmc_ip 도), `data` 는 `init_fragments` 뼈대.
- json_only 의 복제표(`_CHANNEL_SECTIONS` · `_META_KEYS` · `_CORRELATION_KEYS` · `_DATA_SKELETON`)는 `supported_sections.yml` · `build_meta.yml` · `build_correlation.yml` · `init_fragments.yml` 과 drift 테스트로 묶었다 — `tests/unit/test_json_only_fallback_shape.py`(7). `tests/unit/test_always_fallback_envelope.py` 에 redfish 채널 추가.
- N8/Q9: redfish rescue 의 `_fail_sec_supported` 기본값 8개 → 채널 지원 섹션 10개(power·thermal 포함). adapter `capabilities.sections_supported` 가 있으면 그것이 우선(불변). redfish success envelope 의 `system: not_supported` 관행은 별도 정리 항목으로 남긴다.

## 3. 공용 파일 (사전·계약 문서)

- `schema/field_dictionary.yml` 설명만(타입·enum·priority 불변): `memory.slots[].speed_mhz` OS 채널 의미(Linux Configured Memory Speed 우선, Windows ConfiguredClockSpeed 우선, 변환 없음), `storage.physical_disks[].protocol` enum 밖 값 null + storage 오류 detail, `system.runtime` 의 ESXi listening_ports 의미(방화벽 허용 규칙, 범위는 시작 port). `docs/contract/03-fields.md` §2 hostname 행·§6 머리·§6.2·§6.3 에 같은 날짜 주석(rule 13 R7).
- `tests/validate_field_dictionary.py` PASS(10 checks, 0 failed), `output_schema_drift_check.py` 정합.

## 4. OS Linux (C1 · C2 · C7-Linux) · Windows (C3 · C4 · Q6) · ESXi (C8)

### 4-1. Linux (C1 · C2 · C7) — 커밋 `4fe9712a`

- `gather_memory.yml`: `DMIDECODE_RC` · `DMIDECODE_ERR`(stderr 첫 줄) · `MEM_DEVICE_RECORDS` 마커, Size 단위 kB/KB/MB/GB/TB(대소문자 무관), 레코드 경계 = 빈 줄 또는 다음 `Handle`,
  `speed_mhz` 는 `Configured Memory Speed`(dmidecode<3.2 `Configured Clock Speed`) → `Speed`, 총량>0 & SLOT 0 → errors 1건("메모리 모듈 상세 정보를 수집하지 못했습니다…"),
  os_visible 경고 detail 에 rc/stderr. **검수 중 발견·수정**: 비루트 dmidecode 가 머리말만 찍고 rc≠0 → 종전 조건으로는 sudo 재시도가 없었다.
- `gather_storage.yml`: `|| echo '{"blockdevices":[]}'` 마스킹 제거, `LSBLK_RC`/`LSBLK_ERR`/`LSBLK_TXT|…`(레거시 열 1회 fallback)/`SYS_BLOCK_COUNT` 마커, `from_json` 을 block/rescue 로 격리,
  `_l_lsblk_info` 상태(unknown/unsupported/permission/malformed/empty/ok) → storage errors ≤1건, `df` 는 `timeout 20 true` 가 되는 환경에서 `timeout 20`. multipath 불변(R8 조건부).
- `gather_hba_ib.yml`: sysfs 속성 읽기 실패 `ERR|<path>` 마커(`rd()` helper, `device/driver` readlink 포함) → storage errors 1건(≤10 path).
- 테스트: `tests/unit/linux_raw_harness.py`(production raw 스크립트를 sandbox 에서 실행 + task 순서 재생) · `test_linux_memory_parser.py` 27 · `test_linux_storage_markers.py` 37 ·
  `test_linux_hba_ib_markers.py` 8; 수정 전 20/26/3 failed → 수정 후 전부 통과. WSL 실제 `ansible-playbook`(2.20.7, 명령 stub) 3 시나리오 통과, json_only stdout 은 OUTPUT 만.
  문장 4개는 `tests/e2e/test_section_message_contract.py` 통과(+20).
- 미실행: 실장비(구 util-linux · 권한 거부 · HBA 읽기 실패는 stub 재현), mawk 1.3.3 실물 없음.

### 4-2. Windows (C3 · C4 · Q6) — 커밋 `b935b20e`

- `gather_storage.yml`: `ConvertTo-CimCode` · `Get-DiskBusProtocol`(공식 BusType 0..19 → enum 안 값 / 밖은 null + `bus_type_raw` → storage 오류 1건) · `Get-DiskMediaType` · `Get-DiskHealth` ·
  `Get-UidFormatCode`, `-is [int]` 제거(UInt16/Int32/숫자 문자열/문자열 통합), HBA 미매칭 시 첫 어댑터 차용 금지(null), ConnectionType 1/2 숫자·문자열, OperationalStatus 값별 매핑,
  `normalize_wwn` 매칭. `gather_memory.yml`: `speed_mhz` = ConfiguredClockSpeed>0 → Speed.
- 테스트: synthetic 타입 매트릭스(UInt16/Int32/string) 렌더 + 정적 검사. 실장비 `.120` 재수집 동등성은 미실행(권한). baseline `windows_2022_baseline.json` 의 health 소문자 vs 코드 `OK` 는
  실측 뒤 결정 항목.

### 4-3. ESXi (C8 · P5) — 커밋 `6371ba57` · `954b1b0c`

- `esxi_disks.py`: 존재하지 않던 `portRange` 접근 제거 → `endPort` 읽기(범위 notice), Host 선택 규칙(view 의 HostSystem 이 1개면 그것 / 2개 이상은 안정 식별자 일치만 / 모호 시
  `part_errors['host_select']` + 빈 결과 — `hosts[0]` 금지), view 1회, `httpConnectionTimeout`(pyVmomi 9.0.0 `inspect.signature` 확인) + SmartConnect 구간 소켓 기본 timeout 복원.
- P5: `try_one_credential.yml` 성공 시 `_e_probe_facts` 보관 → `collect_facts.yml` 재사용(summary 표지 키가 있을 때만) → 모듈 실행 13→12. WSL 실제 실행(fake `vmware_host_facts`)
  4 시나리오 호출 2→1 · 2→1 · 3→2 · 1→1, `_e_raw_facts` 29 키 동일. `collect_dns` 는 `esxi_disks` 와 출력이 달라 유지(GP-13).
- 미실행: `.1/.2` 실장비(권한), vCenter(lab 부재). 발견한 위험 GP-12(`_e_probe_ok` 판정 근거).

## 5. 미실행·한계

- 실장비 동등성(Phase 2 종료 조건의 live 부분) — 권한 차단으로 미실행. 해소 뒤 `.96/.165/.145/.161/.156`(Linux) · `.120`(Windows) · `.1/.2`(ESXi) · Dell `10.100.15.27`/Cisco `10.100.15.2`(Redfish, dry-run 강제) 로 전후 동등성을 확인한다.
- AccountService 컬렉션 페이지네이션은 4-상태 판정과 얽혀 이번 범위 밖(기존 `Members@odata.count` 대조 유지).
- Windows FC HBA·SAN/multipath·vCenter 는 lab 부재로 synthetic 만.
