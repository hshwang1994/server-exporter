# 2026-10-19 — `storage.hbas[].link_status` up/down 둘뿐 · ESXi hbas vmhba 그대로 · Windows `system.version` `연도-DisplayVersion` (긴급 반영)

> 누가: 사용자 질문·결정 → AI 구현·검증. 언제: 2026-10-19. 어디서: `redfish-gather/library/redfish_gather.py`, `os-gather/tasks/linux/gather_hba_ib.yml`,
> `os-gather/tasks/windows/gather_storage.yml` · `gather_system.yml`, `esxi-gather/tasks/collect_network_extended.yml`, `schema/field_dictionary.yml`, 계약 문서.
> 무엇: 2026-10-18 결정 두 가지(미확정 link_status → null · ESXi (wwpn, wwnn) 1건)와 2026-10-17 결정 하나(Windows version 현행 유지)를 사용자 재결정대로 뒤집었다.
> 왜: 사용자 — "unknown 제거 완료? CSUS null 말고 up 모르면 down" → "null 이더라도 down 으로 통일, up down 둘만" · "ESXi hbas 중복 제거는 없애고 있는 그대로" ·
> "Windows 빌드에 날짜(`2025-24H2`)" · "production 급함". 실장비: 이 세션의 lab 매트릭스 · canary 는 5절.
> 정본 결정: `docs/ai/decisions/ADR-2026-10-19-hba-link-status-two-values-esxi-raw-and-windows-version.md`.

## 1. 먼저 확인한 것 (변경 없음)

| 질문 | 확인 |
|---|---|
| CSUS 시리얼 `-NNN` 제거 완료? | `f30aaeaf`(2026-10-17) — Redfish `hardware.serial` 에 `normalize_os_serial`(HPE 별칭 + CSUS 3200 모델 + `-[0-9]{3}$` 세 조건). `multi_node.partitions[].system.serial` 은 원문 |
| production 반영? | production `144c295f` = main `3e1e2aba` runtime. HBA 4건(`846516e3` `ea160894` `98fd3d0d` `7f21cc7c`) · IB 4건 · 시리얼 1건 모두 조상. `git ls-remote` github · gitlab(internal) 둘 다 `144c295f`. main tip(`480aa4c3`)과 차이는 docs 7개 |
| `unknown` 제거? | `storage.hbas[].link_status` 만(2026-10-18). `storage.infiniband[]` · `network.*` 의 `unknown` 은 그대로 — 사용자가 이번에도 범위 밖으로 선택 |
| "Windows 빌드 날짜"? | 저장소에 흔적 없음 → 사용자 설명: `system.version` `24H2` → `2025-24H2` (신규 요구) |

## 2. 결정 (사용자, 2026-10-19)

| # | 결정 | 뒤집은 것 |
|---|---|---|
| D1 | `storage.hbas[].link_status` 는 항상 `up`/`down`. 미제공(키/파일 없음) · 미확정(Unknown · null 값 · unbound · 미인식)도 `down`. Redfish 는 notice 2종으로 구분 | ADR-2026-10-18 결정 1(null) — 1차 선택 "키 없음만 null" 도 같은 대화에서 폐기 |
| D2 | ESXi `storage.hbas[]` 는 모듈이 준 vmhba 그대로 전부(중복 제거 없음) | ADR-2026-10-18 결정 2 의 ESXi 부분 |
| D3 | Windows Server `system.version` = `<Caption 연도>-<DisplayVersion>` (`2025-24H2` · `2022-21H2` · `2019-1809`); 클라이언트 Windows · 폴백 값은 합성 안 함 | 2026-10-17 6항(현행 유지, 03-fields FAQ) |
| D4 | 승격은 정규 경로(매트릭스 → CI → promote → canary) | — |

## 3. 변경 (Additive — envelope 13 필드 · sections · status 불변)

| 채널 | 변경 |
|---|---|
| Redfish | `_hba_link_status` → up/down 둘뿐. 신규 `_hba_link_missing`(키 없음) · `_hba_link_unresolved`(키는 있는데 up/down 아님 → 원문). 포트 루프 · 고아 루프에서 카드당 notice `… 링크 상태 미제공, down 으로 기록` / `… 링크 상태 값 미확정, down 으로 기록`(포트=원문). 부모 없는 고아 → down + 미제공 notice |
| Linux | `port_state` Online·Marginal → up, 그 밖(없음 · 읽기 실패) → down. 읽기 실패의 errors[] attribute_unreadable 은 그대로 |
| Windows | OperationalStatus 2 → up, 3~8 → down, 1/없음은 PortState 2 만 up, 그 밖 → down. `system.version` 연도 접두(`regex_search('Server +20[0-9]{2}')` → 뒤 4자리) |
| ESXi | `status` online → up, 그 밖 → down. `_e_ext_hbas` 의 `seen`/`dkey` 중복 제거 삭제(vmhba 1개 = 1건) |
| 사전 | `storage.hbas[].link_status` type `string|null` → `string`(enum up/down 그대로), help 재작성. `storage.hbas[]` help 의 ESXi 접기 문구 삭제. `system.version` 은 사전에 항목 없음 |
| 문서 | `03-fields.md` 6.3.1 · 6.3.2 · FAQ(Windows version) · `05-field-mapping.md` · `os_windows2022.jsonc` · EXTERNAL_CONTRACTS · ADR 신규 + ADR-2026-10-18 머리말 개정 표기 · decision-log · CURRENT_STATE · NEXT_ACTIONS · DRIFT-030 · TEST_HISTORY |
| golden | `real_hpe_csus3200/expected_output.json` fc_hbas[0~3].link_status null → down. 나머지 9종 차이 0(재생 스크립트로 전수 비교) |

## 4. 검증 (실장비 아님 — 합성 입력 · 녹화본 · 렌더)

- 변경 영역 시험: ESXi `test_esxi_hba_normalize`(unbound·unknown·없음 → down, 쌍둥이 4건 전부 유지), Linux `test_linux_hba_ib_markers`(Unknown·Deleted·''·없음·읽기 실패 → down), Windows `test_windows_storage_powershell_static`(가짜 cmdlet + 실제 powershell.exe — OperationalStatus 1 · 없음 → down, 1 + PortState 2 → up) · `test_windows_storage_enum_render`,
  Redfish `test_network_adapters_absence_vs_failure`(미제공 → down + `미제공` notice · 값 null/Unknown/Weird → down + `값 미확정` notice, 둘은 섞이지 않음) · `test_fc_link_technology_hba` · `test_fc_orphan_ndf_parent_port_link` · `test_redfish_pure_helpers`(헬퍼 벡터),
  Windows version `test_gather_identity_render`(8 케이스: Server 2025/2022/2019 · Hyper-V Server · Windows 10/11 · caption 없음 · rel_id 없음), 통합 체인 비교 `test_windows_call_consolidation_render/powershell`(version 의도 변경 훅 — 종전 체인 값에 같은 변환), 공통 계약 `test_hba_ib_canonical`(up/down 만) · `test_cross_channel_same_server` · `test_field_dictionary_channel_emit`.
- 수치: `docs/ai/catalogs/TEST_HISTORY.md` 2026-10-19 (전체 unit · e2e · regression, integration not-live, 변경 영역 선택 실행).
- 정적: WSL(ansible-core 2.20.7) 3채널 `ansible-playbook --syntax-check` 통과 · `validate_field_dictionary.py` PASS · `output_schema_drift_check.py` 통과(fd_paths 206) · `verify_vendor_boundary.py` 통과 · `verify_harness_consistency.py` 통과 · `check_project_map_drift.py` 일치.
- 시험 하네스 보완(코드 아님): Windows 통합 체인 렌더 하네스에 `regex_search` 호환 필터 추가(`test_gather_identity_render` 와 같은 shim) — `gather_system.yml` 의 version 식이 쓴다.

## 5. 실장비(Jenkins main Job 매트릭스) · CI · 승격 · canary

(이 절은 매트릭스 실행 뒤 채운다 — 빌드 번호 · 결과 · envelope 대조 · CI 번호 · production SHA · canary.)

기대값: Redfish Cisco .2 hbas `up/up/up/down`(불변) · esxi02 FC 2건 `down/down`(불변 — 쌍둥이 없음) · Windows .120 `system.version == "2022-21H2"`(변경) · 전 채널 `storage.hbas[].link_status` null 0건.

## 6. 실장비에서만 확인 가능 (미검증)

Unknown · null 값 `LinkStatus` 를 주는 FC 포트(Redfish 값 미확정 notice 경로), ESXi 7 FC-NVMe 쌍둥이 2건 출력, Windows Server 2025 의 `2025-24H2`(lab 은 2022), Linux `port_state` Unknown/Deleted 실값, CSUS 3200 사이트 재수집(down + `미제공` notice · Portal 조인).
