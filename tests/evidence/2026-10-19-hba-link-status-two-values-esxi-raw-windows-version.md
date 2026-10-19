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

### 5.1 main Job 매트릭스 — main `27c4b393`(`clovirone-cicd/clovirone-server-gather-main` #689~#699, Chrome 의 Jenkins 세션에서 `buildWithParameters` POST, 사용자 승인 2026-10-19)

입력은 2026-10-18 4차(#678~#688)와 같은 집합(loc · target_type · inventory · callbackUrl · deploymentEnvironmentId=1), eventUuid 만 `…-20261019e0NN`. 11건 동시 투입(Jenkins 가 Runner 에 분산), T5 는 콘솔 `정보 수집을 시작합니다` 관측 +11초에 `stop`.

| 시나리오 | 빌드 | 결과 | 비고 |
|---|---|---|---|
| S1 | #689 | SUCCESS 75초 | Linux VM 3대(.162 .163 .156) |
| S2 | #690 | SUCCESS 119초 | 혼합(.132 .33 .34 + TEST-NET 2) |
| S3 | #691 | SUCCESS 150초 | Linux 11대 |
| S4 | #692 | SUCCESS 162초 | Windows .120 — **`system.version` = `2022-21H2`**(distribution `Microsoft Windows Server 2022 Standard`, kernel 20348) |
| T2 | #693 | SUCCESS 103초 | TEST-NET 2 빠른 실패 |
| T6 | #694 | UNSTABLE 133초 | Callback 닫힌 포트(계약값) |
| E2E-A | #695 | UNSTABLE 133초 | loc=cj smoke |
| E2E-A2 | #698 | FAILURE 19초 | loc=chj fail-closed — tip 관측 before 1792375982 · after 1792376105, sha `27c4b393` 불변 |
| E2E-D | #696 | SUCCESS 110초 | ESXi 6대 — esxi02 hbas 2(`vmhba2`/`vmhba3` FC **down/down**, WWPN …6e/…6f), esxi01 iSCSI `up`, RAID 뒤 logical_volumes 2(esxi01~03), link_status null 0 |
| E2E-E | #697 | SUCCESS 389초 | Redfish 7대 — Cisco .2 hbas 4 **`up/up/up/down`** · link_status null 0 · 링크 상태 notice 0(CIMC 는 LinkStatus 제공), Dell 5 · Lenovo 1 hbas [] |
| T5 | #699 | ABORTED 74초 | `[수집] 중단됨:` · outcome aborted · Portal 200 · **`lastBuiltRevision 27c4b393`**(증거 결속 OK) |

checkout 은 #698(fail-closed, 수집 단계 없음) 외 10건 전부 `27c4b393`. OS 봉투 19건(S1 · S2 · S3) + Windows 1건 + ESXi 6건 + Redfish 7건에서 `storage.hbas[].link_status` null **0건**.
lab 에는 FC-NVMe 쌍둥이 · Unknown 값 FC 포트 · Windows Server 2025 가 없어 ESXi 중복 제거 폐지 · 값 미확정 notice · `2025-24H2` 는 이번 매트릭스로 확인되지 않는다(6절).

### 5.2 CI #63 · 승격 `027409f4` · canary

- **CI** `clovirone-cicd/clovirone-server-gather-ci` #63 — `PROMOTE=true · PROMOTE_SHA=27c4b393 · PROMOTE_DRY_RUN=false`, `E2E_MAIN_ENTRIES` 11건(#689~#699), `E2E_TIP_OBSERVATIONS_JSON`(#698, before 1792375982 · after 1792376105, sha 불변).
  SUCCESS 62분 · 12 stage 전부 SUCCESS(Checkout · Toolchain · Gate · Finalize Corpus · Time Limits Self-test · Prodgen Build · Prodgen Drift · Prodgen Verify · Harness Driver · Harness(prodtree) · Evidence Aggregate · Prodgen Promote) ·
  집계 verdict **COMPLETE_PASS**(G01~G20 전부 PASS, main_sha `27c4b393`, tree `3d9c6c8c`) · `prodgen_promote.json` `e2e.ok=true` · `ci_stages.ok=true` · **Promote 는 `se-gitlab-push` 부재로 dry-run**(종전과 같음).
- **승격(실제)** — 작업 PC(`promote_ci63.sh`: CI #63 산출물 3개 netrc 로 내려받기 → `prodgen promote --sha 27c4b393 … --push-remote origin,internal`, 사용자가 `!` 로 실행 · 자격 파일은 사용자 보관 경로).
  → **production `027409f4`**(parent `144c295f` · Main-SHA `27c4b393` · Tree-Hash `3d9c6c8c…` · 195 파일 · Verdict COMPLETE_PASS · Gates G01~G20 PASS · Gates-Rerun G11 G12 G13 G14 G15 G18 G19 G20 · CI-Stages verified · Generated-At 2026-10-19T03:56:07Z).
  publish origin "accepted by remote" · internal "already at the new commit (shared push URL)" · 로컬 ref 갱신. **github · gitlab · 로컬 `production` 모두 `027409f4`.**
  (붙여넣기 줄바꿈으로 첫 시도가 끊기며 vault 비밀번호 파일이 셸에 실행돼 값이 터미널에 찍혔다 — 저장소 · 문서에는 적지 않았고, 비밀번호 교체는 사용자 결정으로 남겼다.)
- **production Job canary** `clovirone-cicd/clovirone-server-gather`(전부 checkout `027409f4`, 결과 수 == 접수 수, errors 0, 13키):

| 빌드 | 채널 | 결과 | 확인 |
|---|---|---|---|
| #310 | ESXi 6 (.1 .2 .3 .91 .92 .93) | SUCCESS 88초 | 6/6 · checkout `027409f4` · esxi02 FC 2건 `down/down`(WWPN …6e/…6f) · esxi01 iSCSI `up` · `logical_volumes` 2,2,2,0,0,0 · link_status null 0 · 13키 · Portal 2xx |
| #311 | Redfish 7 (.15.2 .27 .28 .31 .33 .34 + 10.50.11.232) | SUCCESS 403초 | 7/7 · Cisco .2 hbas 4 `up/up/up/down` · null 0 · `logical_volumes` 2,1,1,1,1,3,2 · errors 0 · Portal 2xx |
| #312 | OS 11 (.33 .34 .35 .36 .37 .38 .95 .96 .156 .162 .163) | SUCCESS 133초 | 11/11 · r760-6 `.96` `logical_volumes` 2 · hbas [] · errors 0 · Portal 2xx |
| #313 | Windows 1 (.120) | SUCCESS 144초 | 1/1 · **`system.version` = `2022-21H2`** · errors 0 · Portal 2xx |

2026-10-18 승격본(`144c295f`) 과 비교해 바뀐 값은 Windows `.120` `system.version`(`21H2` → `2022-21H2`) 뿐이다. hbas 값(esxi02 `down/down` · Cisco `up/up/up/down`)은 그대로이고 null 은 어디에도 없다.
`schema/baseline_v1/windows_2022_baseline.json` 의 `system.version` 을 이 실측(main S4 #692 · production #313)으로 `2022-21H2` 로 갱신했다(rule 13 R4).

기대값: Redfish Cisco .2 hbas `up/up/up/down`(불변) · esxi02 FC 2건 `down/down`(불변 — 쌍둥이 없음) · Windows .120 `system.version == "2022-21H2"`(변경) · 전 채널 `storage.hbas[].link_status` null 0건.

## 6. 실장비에서만 확인 가능 (미검증)

Unknown · null 값 `LinkStatus` 를 주는 FC 포트(Redfish 값 미확정 notice 경로), ESXi 7 FC-NVMe 쌍둥이 2건 출력, Windows Server 2025 의 `2025-24H2`(lab 은 2022), Linux `port_state` Unknown/Deleted 실값, CSUS 3200 사이트 재수집(down + `미제공` notice · Portal 조인).
