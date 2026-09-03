# TEST_HISTORY — server-exporter

## 2026-09-03 — reachable ICMP OR 판정 회귀 (오프라인)

> 정본: `docs/ai/decisions/ADR-2026-09-03-icmp-or-reachability.md`

| 항목 | 결과 |
|---|---|
| `pytest tests/ --ignore=tests/e2e_browser` (전수) | **3312 passed**, 10 skipped, 7 xfailed |
| `pytest tests/unit/test_precheck_icmp_reachability.py` (신설) | 24 passed — OR 판정 / Gate 아님(TCP 응답 시 ICMP 미호출) / RST·DNS 경로 skip / 예산 1회 / 전용 code 금지 / envelope shape 불변 |
| 변경 전 기준선 대비 | 3269 → 3312 (+43: ICMP 24 + 채널별 OR 케이스 + 문장 매핑) |
| `python scripts/ai/hooks/output_schema_drift_check.py` | exit 0 — sections=11 fd_paths=192 |
| `python scripts/ai/verify_harness_consistency.py` | 통과 (rules 28 / skills 47 / agents 47 / policies 7) |
| `python scripts/ai/check_project_map_drift.py` | fingerprint 일치 |
| `python scripts/ai/verify_vendor_boundary.py` | exit 0 (기존 advisory 2건 — 본 변경과 무관) |
| `python -m py_compile common/library/precheck_bundle.py` | OK |
| YAML parse (`run_precheck.yml`, 3 channel `site.yml`, `field_dictionary.yml`, `failure_reasons.yml`) | OK |
| `ansible-playbook --syntax-check` | **로컬 미실행 — 환경 제약** (Windows 개발 PC 의 ansible CLI 가 `OSError WinError 87` 로 기동 불가). Jinja2 인라인 템플릿 컴파일은 `tests/e2e/test_section_message_contract.py` 가 대체 검증 |
| 실장비 (러너 10.100.64.154 직접 실행) | **4/4 확인** — 증거 `tests/evidence/2026-09-03-icmp-reachability-live.md` |
| RE-1 `ping` 가용성 | `cap_net_raw=ep` 로 비특권 동작. `ping_group_range = 1 0` → **비특권 ICMP 소켓 방식이었으면 실패**했을 조건 (구현 선택 실측 확인) |
| RE-2 ICMP만 응답 (redfish/.145, 관리 443 DROP) | `reachable=true` / `stage=port` / `TCP_CONNECT_FAILED` / 2번 문장. 종전이면 1번 문장이 나갔을 상황 |
| RE-2 TCP·ICMP 무응답 (os/.163) | `TARGET_UNREACHABLE` / 1번 문장(종전과 동일) / `detail` 에 `icmp: 응답 없음 (rc=1)` |
| RE-2 ICMP 차단 + TCP 정상 (os/.120 Windows) | precheck 정상 통과 (`reachable/port/protocol` 전부 true) — **Gate 아님 실측 확인** |
| RE-3 dead host 예산 | ICMP on 8.62·8.75s ↔ off 7.69·7.50s → **+1.0~1.1초/대** (설계값 일치) |
| Jenkins 파이프라인 `clovirone-server-gather` #200 (`os`: .163/.145/.120) | UNSTABLE(더미 callback — 의도) / 체크아웃 `1fd9fa6d` / envelope 3건: `.163` = `TARGET_UNREACHABLE`, `.145` `.120` = **`success`** (vault 자격증명까지 태운 실수집). `.120` 은 ICMP 차단 장비의 정상 수집 — Gate 아님 end-to-end 증거 |
| Jenkins 파이프라인 #201 (`redfish`: .145) | UNSTABLE(더미 callback) / 체크아웃 `1fd9fa6d` / `reachable=true` + `stage=port` + `TCP_CONNECT_FAILED` + 2번 문장. Stage 전량(Resolve Location→Validate→Gather→Validate Schema→Callback) 실행 |

## 2026-09-03 — 실장비 검증 (Jenkins `clovirone-server-gather` #190~#196, 운영 파이프라인 Jenkinsfile_portal)

> 증거: `tests/evidence/2026-09-03-os-esxi-live-verification.md` + 원본 envelope `tests/evidence/2026-09-03-live/*.json`

| 빌드 | 커밋 | 대상 | 결과 |
|---|---|---|---|
| #190 | `1fb2ae16` | os ×4: RHEL 8.10(raw fallback) / RHEL 9.6 / Dell R760 베어메탈 Ubuntu 24.04 / Windows Server 2022 | 4/4 success. 계약 점검 이슈 4건(Windows 팀 멤버 MAC 대시, IPv6 `%zone`, R760 정격 클럭 null, ESXi 값 2건) |
| #191 | `1fb2ae16` | esxi: 10.100.64.1 (7.0.3) | success, 이슈 0 (정격 2194 절삭·vmk0 down 지적) |
| #192 / #193 | `0076ca67` | os: R760 + Windows / esxi: 10.100.64.1 | 전부 success, 이슈 0 — 4건 정정 확인 |
| #194 | `0076ca67` | os ×3: .163(무응답) / .167 / .169 | .163 실패 envelope 이 새 계약대로(hostname null, 11 섹션, 표준 문장). .167/.169 는 .165/.161 VM 의 bond IP (lab 목록 오류). VM turbo 2093<2200 발견 → `d38bc31b` |
| #195 | `0076ca67` | esxi: 10.100.64.2 (esxi02, baseline 대상 장비) | success, 이슈 0. FC WWPN 소문자 colon, HBA vendor, UUID ↔ Redfish `uuid_equal` 일치 |
| #196 | `d38bc31b` | os: .161 raw VM + .96 R760 (turbo 가드 재검증) | 2/2 success, 이슈 0 — VM turbo `null`, R760 2400/4100 |
| #197 | `43a9f155` | os: .156(Ubuntu 24.04 VM) + .163 | .156 success (VMware SMBIOS `Max Speed 30000` 이 turbo 로 실림 → `549f84ff`), .163 무응답 |
| #198 | `43a9f155` | os: 10.100.64.145 (RHEL 9.6 VM, 사용자 지정) | success, 이슈 0 |
| #199 | `549f84ff` | os: .156 + .145 (SMBIOS 클럭 범위 가드 재검증) | 2/2 success, 이슈 0 — .156 turbo `null` |
| `pytest tests/ --ignore=tests/e2e_browser` (d38bc31b) | — | — | **3269 passed, 10 skipped, 7 xfailed (2026-09-03, d38bc31b)** |
| Jenkins Stage 3 (Validate Schema) | — | 7 빌드 | 전부 통과 (WARN 은 예시 미포함 advisory) |
| Stage 4 Callback | — | 7 빌드 | 더미 URL(192.0.2.1) → 408 → **UNSTABLE 은 의도된 결과** (rule 31 R2) |

**Jenkins 체크아웃 SHA 확인**: 각 빌드 콘솔의 Gather stage `Checking out Revision` = 대상 커밋 (rule 14). Agent `jenkins-agent-ops`, ansible-core 2.20.3.

## 2026-09-03 — OS(Linux/Windows) / ESXi 게더링 전수 검수 후속 (37건 정정) 회귀

| 항목 | 결과 |
|---|---|
| `pytest tests/ --ignore=tests/e2e_browser` (전수) | **3265 passed**, 10 skipped, 7 xfailed (변경 전 기준선 2873 passed → 신규 테스트 7 파일 반영) |
| `pytest tests/unit` | 2222 passed |
| `pytest tests/regression` | 169 passed, 7 xfailed |
| `pytest tests/e2e` | 631 passed, 6 skipped |
| `pytest tests/integration -m "not live"` | 243 passed, 3 skipped |
| 신규 테스트 | `test_identity_normalizer.py`(30) / `test_gather_identity_render.py`(21) / `test_always_fallback_envelope.py`(3) / `test_failed_output_partial_and_hostname.py`(6) / `test_field_dictionary_channel_emit.py`(8) / `test_cross_channel_uuid_equal.py`(2) / `test_esxi_disks_host_info.py`(4) |
| 갱신 테스트 | `test_os_network_render.py`(raw 단일 구현 + normalize_mac) / `test_esxi_section_errors.py`(host_info 스텁, 인터페이스 컨텍스트, 섹션 failed 케이스) / `test_windows_runtime_ports_str_r18.py`(gather_runtime 정본) / `test_windows_firewall_state_r19.py`(빈 프로필 = null) / `test_envelope_failure_modes.py`(hostname null 허용 + `hostname != ip`) |
| `tests/validate_field_dictionary.py` | RESULT: PASS (8/8 — 신규 3 path 는 예시 미포함 WARN) |
| `output_schema_drift_check` | exit 0 (sections=11 / fd_paths=192) |
| `envelope_change_check` | advisory 1건 — `diagnosis.auth_success` 후보(기존 사전 항목, 이번 변경 무관). envelope 13 필드 무변경 |
| `pre_commit_jinja_compile_check --all --blocking` / `pre_commit_jinja_namespace_check` / `pre_commit_fragment_skeleton_sync` | 전부 exit 0 |
| `pre_commit_placeholder_fallback_check --all` (신규 advisory) | self-test PASS, 저장소 전수 0건 |
| `verify_harness_consistency` | exit 0 (rules 28 / skills 47 / agents 47 / policies 7) |
| `verify_vendor_boundary` | exit 2 — **기준선과 동일** 2건(`redfish_gather.py` iLO/XCC), OS/ESXi 신규 위반 0 |
| YAML parse / `py_compile` | 변경 YAML 45종 + `esxi_disks.py` + `identity_normalizer.py` OK |
| `ansible-playbook --syntax-check` | **미실행 — 환경 제약** (Windows 세션 ansible-core 2.21.3 CLI 진입부 `os.get_blocking` 예외). YAML parse + 저장소 전수 Jinja compile + 표현식 렌더 테스트로 대체 |
| **실장비** | **미실행** — Linux(python/raw) / Windows / ESXi / R760 bare-metal 재수집 0건. baseline 10건 미재생성 (NEXT_ACTIONS GA-1 / GA-2) |

값 대조 근거: `tests/reference/os/{rhel-baremetal,win2022,rhel810,ubuntu2404}` 캡처와
`tests/reference/esxi/10_100_64_1/pyvmomi_host_dump.json` (cpuMhz=2195 / dnsConfig.hostName=esxi01 /
vnic ipRouteSpec.defaultGateway=10.100.64.254) 을 렌더 테스트 입력으로 썼다.

## 2026-08-27 — OS 채널 CSUS 3200 nPartition 시리얼 접미사 정규화 회귀

| 항목 | 결과 |
|---|---|
| `pytest tests/unit` | **2131 passed**, 1 skipped (종전 2130 → +1 파일 79건 중 기존 중복 제외) |
| 신규 테스트 파일 | `tests/unit/test_csus_partition_serial.py` — **79 passed** |
| `pytest tests/regression` | 169 passed, 7 xfailed |
| `pytest tests/e2e` | 558 passed, 28 skipped |
| `pytest tests/integration -m "not live"` | 243 passed, 3 skipped |
| Jinja 렌더 회귀 | 신규 task 3종을 `NativeEnvironment`(= `jinja2_native=True` 등가)로 렌더해 **값 + 타입** 확인. 비-CSUS 입력은 변경 전후 결과가 전부 동일 (숫자 시리얼의 int 변환은 `resolve identifiers` 단계에서 이미 발생하는 기존 동작) |
| `output_schema_drift_check` / `envelope_change_check` / `pre_commit_additive_only_check` | 전부 exit 0 (envelope 13 필드 무변경) |
| `pre_commit_jinja_compile_check` / `pre_commit_jinja_namespace_check` / `pre_commit_regex_search_conditional_check` / `pre_commit_fragment_skeleton_sync` / `pre_commit_harness_drift` | 전부 exit 0 |
| `verify_harness_consistency` | exit 0 |
| `verify_vendor_boundary` | exit 2 — **기준선과 동일**. 2건 모두 `redfish-gather/library/redfish_gather.py`(iLO / XCC)로 이번 변경 이전부터 존재. os-gather 신규 위반 0건 (stash 대조 확인) |
| `validate_field_dictionary.py` | RESULT: PASS (8/8, 실패 0) |
| YAML parse / `py_compile` | 변경 YAML 3종 + `serial_normalizer.py` 전부 OK |
| `ansible-playbook --syntax-check` | **미실행 — 환경 제약** (Windows 세션에 ansible 미설치). YAML parse + 저장소 전수 Jinja compile 회귀(`test_section_message_contract`)로 대체 |
| **실장비** | **미실행** — CSUS 3200 lab 부재. OS 측 DMI 표기 실측이 후속 (NEXT_ACTIONS CSUS-OS-1) |

목데이터 근거: `tests/fixtures/redfish/real_hpe_csus3200/recording.json`
(`Systems/Partition0.SerialNumber="SGHD3TLNDD-000"` / `Chassis/r001u01` =
`HPE` + `"Compute Scale-up Server 3200, 4S XNC Base Chassis"` + `"SGHD3TLNDD"`)
→ 정규화 결과가 물리 Chassis 시리얼과 일치함을 테스트가 직접 대조한다.

## 2026-08-14 — Location ID `ich` → `ic` 개명 회귀

| 항목 | 결과 |
|---|---|
| `pytest tests/` | **3062 passed**, 10 skipped, 7 xfailed |
| Location 직접 영향 4 파일 | `test_credential_resolver` / `test_location_registry` / `test_redfish_standard_recovery_contract` / `test_vault_check_no_secret_output` + `test_failure_code_contract` = 194 passed |
| `vault_decrypt_check.py --layout-only` | `ic: 12/12` / `chj: 12/12` / `yi: 12/12` / `git: 12/12` |
| `output_schema_drift_check` | exit 0 (sections=11 fd_paths=176) |
| `verify_harness_consistency` | exit 0 |
| YAML parse / `py_compile` | locations.yml / field_dictionary.yml / credential task 2종 / `credential_common.py` 전부 OK |
| `ansible-playbook --syntax-check` | **미실행 — 환경 제약** (Windows 세션에 ansible 미설치). 변경분이 주석뿐이라 YAML parse 로 대체 |
| **실장비** | **미실행** — Jenkins 노드 label 재설정(LOC-1) 전까지 `loc=ic` 잡이 Agent 를 못 잡는다 |

## 2026-08-13 — 계정 쓰기 계약 정합 (9 Vendor 조사 반영)

| 항목 | 결과 |
|---|---|
| `pytest tests/` | **3063 passed**, 10 skipped, 7 xfailed (종전 2843 → +220) |
| 신규 테스트 파일 | `test_account_no_write_fallback.py`(27) / `test_account_diagnosis_axes.py`(15) / `test_account_write_contract_invariants.py`(146) |
| 반전 테스트 | `test_unverified_family_keeps_the_legacy_post_retry` → `..._writes_once_and_never_retries`, `test_m_b3_inspur_isbmc_post_400_then_retry` → `..._writes_once_and_fails` (제거 대상 동작을 고정하고 있었다) |
| `ansible-playbook --syntax-check` ×3 | PASS (WSL ansible-core 2.20.7) |
| `output_schema_drift_check` / `verify_vendor_boundary` / `verify_harness_consistency` / `verify_no_plaintext_secret` / `check_project_map_drift` | 전부 exit 0 |
| baseline / replay / envelope 회귀 | 385 passed |
| e2e | 590 passed |
| **실장비** git 4대 × (Check Mode + 1차 + 2차) | 전부 `success` / `used_role=primary` / **Account Write 0** |

정본: `tests/evidence/2026-08-13-account-write-contract-alignment.md`

미증명 유지: Account CREATE 는 조건이 발생하지 않았다. 4대 모두 표준 계정이 정상이었다.
Supermicro / Huawei / Inspur / Fujitsu / Quanta 는 실장비 0대.


> 테스트 실행 / Round 검증 / Baseline 갱신 이력 (append-only, rule 70).

## 2026-08-12 (q) — Vault 갱신 후 전량 회귀 + git 실장비 검증

- **정적 회귀**: unit 1792 / regression 169 (+7 xfailed) / e2e 590 (+6 skipped) /
  integration(not live) 243 (+3 skipped) = **2794 passed**, 실패 0.
  Vault 값 변경이 코드 회귀를 유발하지 않음을 확인했다.
- **py_compile**: `redfish_gather.py`, `precheck_bundle.py`, `credential_common.py`,
  `credential_resolver.py`, `credential_accounts.py` 전부 OK.
- **ansible syntax-check** (WSL ansible-core 2.20.7): os / esxi / redfish 전부 exit=0.
- **Gate**: verify_vendor_boundary 0 / verify_harness_consistency 0 /
  output_schema_drift_check 0 / validate_field_dictionary PASS /
  **vault_decrypt_check 전량 통과(exit=0)**.
- **실장비 7대상 (git Location)**: production 과 동일한 ansible-playbook 을 호출했다.
  성공 6 / HOLD 1(Dell). Redfish 3대는 `credential_scope=common/redfish/standard` +
  used_role=primary + **Account Write 0**, Lenovo·Cisco 는 **2차 실행 Write 0** 까지 확인.
- **read-only Redfish probe**: Dell 2대(.34/.27), Lenovo, HPE, Cisco 에서 ServiceRoot /
  Manager / AccountService / Roles / Accounts / OEM Attributes / Attribute Registry 를
  쓰기 0건으로 수집했다. Dell 비밀번호 정책을 규명한 근거다.
- 정본: `tests/evidence/2026-08-12-git-location-live-verification.md`

## 2026-08-12 (p) — Redfish 계정 Reconcile Family Strategy 회귀

- **기준선(변경 전 직접 측정)**: unit+regression 1907 passed / 7 xfailed (66.55s),
  e2e 587 passed / 6 skipped (13.07s), integration(not live) 200 passed / 3 skipped (1.71s)
  = **2694 passed**.
- **변경 후**: unit+regression 1961 (18.05s), e2e 590 (12.46s),
  integration 243 (2.75s) = **2794 passed**, 실패 0.
- **신규 파일**
  - `tests/unit/test_account_capability_and_presence.py` (20). 3-상태 열거 / 4-상태 존재 판정 /
    ServiceRoot 링크 추종 / 정책 파싱, 그리고 **부분 조회 실패 시 Write 0건** 회귀(C-1).
  - `tests/unit/test_account_family_and_write_contract.py` (33). Family 결정성, Dell iDRAC10
    reserved slot 2, Cisco Roles 어휘 기반 판정, Lenovo Purley slot PATCH, Supermicro
    Firmware 경계, Inspur OEM Status/ETag, 검증 의무화, check_mode, lockout 예산,
    상태 수렴(Disabled/Locked/Role/PasswordChangeRequired/AccountTypes).
  - `tests/integration/account_replay.py` + `tests/integration/test_account_reconcile_replay.py` (43)
    로 **실장비 미러 재생** (Dell 5호스트 / HPE 1 / Lenovo 1 / Cisco 1). 감사 D-8 해소.
  - `tests/unit/account_seam.py` 는 기존 3-tuple fake 를 discovery dict 로 감싸는 공용 seam 이다.
- **갱신 파일**: 계정 관련 unit 5종 + e2e 2종. seam 이동(`account_service_get` ->
  `account_service_discover`)과 의도된 동작 변경(POST 사다리 제거 / 검증 의무화 /
  `verification='none'` 불인정 / backoff 조건화)을 반영.
- **부수 효과**: 계정 테스트에 `time.sleep` monkeypatch autouse fixture 를 넣어 audit M-9 을
  해소했다. 8개 테스트가 각 6초씩 블로킹하던 건이다. unit+regression 수트가 **66.55s -> 18.05s**.
- **Ansible syntax-check** (WSL Ubuntu, ansible-core 2.20.7): os/esxi/redfish 전부 exit=0.
- **게이트**: verify_vendor_boundary exit=0 (신규 Family 표 13라인 `# nosec rule12-r1` 표기 후),
  verify_harness_consistency exit=0, output_schema_drift_check exit=0,
  validate_field_dictionary PASS, vault_decrypt_check --layout-only exit=0.
- **실장비 0건.** `ansible-playbook` 실행 0건, Account Write 0건.

## 2026-08-11 (o) — Dell 대표 시리얼 교정 회귀 (ServiceRoot Service Tag)

- **신규**: `tests/unit/test_dell_service_tag_serial.py` 41건.
  ServiceTag 정상 + System 정상(fixture `dell` / `dell_r760` / `real_dell_r740`) /
  ServiceTag 정상 + System 수집 실패(→ partial+null 금지) / ServiceTag 없음 4종 /
  invalid 10종(`NA` `N/A` `None` `Not Specified` `To Be Filled By O.E.M.`
  `System Serial Number` `0` `00000000` `""` 공백).
  **폴백 금지 실증** 14케이스에서는 결과에 `SerialNumber`·`SKU`·`ChassisServiceTag`·`NodeID` 가
  0회 등장한다. 무인증↔인증 ServiceRoot 노출 차이와 재조회 횟수도 확인.
  **serial null 0건 불변식** / 비-Dell 무회귀.
- **신규**: `tests/e2e/test_redfish_baseline.py::TestDellServiceTagIsRepresentativeSerial`.
  최종 envelope 의 `data.hardware.serial` == `correlation.serial_number` ==
  raw fixture `Oem.Dell.ServiceTag` 를 비교한다. 기대값은 하드코딩하지 않고 fixture 에서 읽는다.
- **기준선 갱신 (Dell 3종만, 전부 재생 산출값)**:
  `real_dell_r740/expected_output.json` `CNIVC0098G0600`→`J0KV603` ·
  `dell_r760_output.json` `CNIVC004950455`→`64CXJ54` ·
  `schema/baseline_v1/dell_baseline.json` `CNIVC009CP0282`→`2BJ8033`.
  비-Dell baseline 9종 + 실미러 골든 3종(HPE/Lenovo/CSUS) **무변경 통과**.
- **실장비 대조 7대**: reference 미러 5대 + fixture 2대 전부 `Oem.Dell.ServiceTag` 가 있고
  `SerialNumber` 와 상이. R760-6 은 Redfish `GSBPK54` == Linux SMBIOS Type 1 `GSBPK54`.
- **결과**: unit 1186 passed / e2e 416 passed·6 skipped / integration 200 passed·3 skipped /
  regression 169 passed·7 xfailed. `validate_field_dictionary` / `verify_vendor_boundary` /
  `verify_harness_consistency` PASS.
- **실 Jenkins 실행 (2026-08-11 사후)**, job `clovirone-server-gather`:
  - **#188** `target_type=redfish`, BMC 10.100.15.27 / 10.100.15.34 → 각각
    `hardware.serial` = `correlation.serial_number` = `64CXJ54` / `GSBPK54`,
    status=success, errors 0, envelope 13필드 일치, Stage 3 Validate Schema PASS,
    콘솔 전체 `CNIVC` 0회.
  - **#189** `target_type=os`, 10.100.64.96 (위 .34 의 짝) → `correlation.serial_number=GSBPK54`.
  - 동일 `system_uuid` 위에서 두 채널 serial **SAME** (교정 전 DIFFERENT).
  - 두 빌드 `UNSTABLE` 은 미라우팅 콜백(`192.0.2.1`) timeout 때문이며 수집과는 무관하다 (rule 31 R2).
- 증거: `tests/evidence/2026-08-11-dell-serial-service-tag.md`.

## 2026-08-11 (m) — 실환경 검증 (Phase 6-A)

- **실장비 실측** (lab 네트워크 직접 도달):
  - ESXi 3대(10.100.64.1/2/3, 전부 7.0.3 build-20842708) 에서 `/sdk` POST wire 응답 확인.
    `versionId=6.0` 수락 / HTTP 200 / `RetrieveServiceContentResponse` /
    `about.apiType=HostAgent` / `apiVersion=7.0.3.0` / `parse_service_content` True.
  - BMC 11대 중 9대는 `probe_redfish` OK. **무인증 ServiceRoot 401/403 = 0대**.
    cisco .1 은 502/503 으로 흔들려 테스트 flaky 위험. cisco .3 다운.
  - OS 7대 중 Linux 5대는 SSH identification 확인(`SSH-2.0-OpenSSH_8.0/8.7/9.6p1`).
    rhel920 .163 은 전 포트 timeout 이며 `TCP_CONNECT_FAILED` 의 실제 사례다.
  - Windows 1대는 수정 전 401 실패, **수정 후 200 + IdentifyResponse 확인**.
- **Linux 실제 Ansible CLI**: `ansible-playbook --syntax-check` 3 채널 exit 0
  (WSL Ubuntu 24.04.3 / ansible-core 2.20.7 / vault 암호 적용). **최초 실제 통과**.
- **신규**: `tests/unit/test_soap_header_case_preserved.py` 15건.
  `http.client` 를 seam 으로 잡아 헤더 이름 정규화 재발을 차단한다.
  `WSMANIDENTIFY` / `SOAPAction` / `Content-Type` 보존, 요청 shape 불변,
  http/https 분기, 비-2xx status 보존, timeout·refused 분류, max_bytes, 민감정보 미포함,
  실장비 응답 그대로를 넣은 `probe_os` 통합 확인.
- **전체 회귀**: `pytest tests/` → **1775 passed, 11 skipped, 7 xfailed**
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0,
  field_dictionary PASS, `schema/` 무변경.
- **수행 시간 실측**: ESXi probe 0.06~0.11s / Redfish probe 0.13~1.20s(죽은 호스트 31.1s) /
  Linux precheck 4.06~4.09s / Windows precheck 0.19s(수정 후) / OS 전 포트 실패 6.03s /
  전체 playbook: ESXi 25.1s, Redfish 133.3s, Linux 29.7s.

## 2026-08-11 (l) — Portal Grid 실패 사유 + 자격 실패 분류 검증 (Phase 5-A)

- **신규**: `tests/e2e/test_failure_reason_case_matrix.py` 27건
  - 18 Case 를 최종 diagnosis 까지 렌더 (precheck 6건은 `run_module()` 실제 실행,
    rescue 12건은 site.yml `_diagnosis` 템플릿 추출 렌더)
  - **§29 단계 진행 관계 Contract**: 문장이 주장하는 앞 단계 성공을 Machine Diagnosis 로
    증명 (`관리 연결은 확인되었지만`→port_open / `<서비스>는 확인되었지만`→protocol_supported /
    `접속은 확인되었지만`→auth_success). 문구와 Boolean 이 어긋나면 실패
  - reachable 단계가 "통신은 되지만" 을, port 단계가 "서버는 응답하지만" 을 쓰지 않는지
  - `정보 수집 후` 는 수집 성공이 관측된 경로에서만
  - 18 Case 전수 민감정보 미노출
- **신규**: `tests/e2e/test_credential_probe_classification.py` 13건. 4 채널 자격 probe
  파일이 문자열 파싱으로 인증 실패를 확정하지 않는지, `auth_success` 를 분산 판정하지 않는지,
  **인증 시도 횟수 / retry / lockout backoff 가 그대로인지**, 403 을 거부로 만들지 않는지
- **신규**: `tests/unit/test_redfish_auth_evidence.py` 14건. `auth_evidence` 가
  자격증명 요청의 첫 정수 status 만 기록 / 무인증 요청 미기록 / status=0 미기록 /
  첫 관측 고정 / 반환값 불변 / invocation 단위 초기화 / 자격증명 미포함 / 문자열 미수용
- **갱신**: `test_failure_reason_contract.py` 에 §26·§27 단언 추가
  (관리 포트 `22/443/5985/5986` 금지, HTTP status 금지, timeout 초 금지,
  내부 기술 용어 14종 금지). OS 포트 실패 검증은 precheck 실제 실행 기반으로 교체했고,
  삭제한 PLAY 1.5 덮어쓰기 태스크가 되살아나면 실패하는 가드를 넣었다
- **갱신**: `test_esxi_precheck_contract.py` / `test_os_candidate_search.py` /
  `test_os_precheck_polling.py` / `test_failure_code_contract.py` 를 새 문구 계약으로
- **동기화**: `schema/examples/redfish_{failed,not_supported}.json`,
  `schema/output_examples/redfish_failed.jsonc`, `docs/contract/03-fields.md` 예시 문구
- **전체 회귀**: `pytest tests/` → **1731 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3(output_schema_drift) PASS / unit 1063 / e2e 299 /
  integration 200 / regression 169 / field_dictionary PASS
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **정적**: py_compile 2파일 / YAML 78파일 파싱 / Jinja2 문자열 스칼라 893개 컴파일 0오류
- **보정 회귀 (2026-08-11)**: `tests/e2e/test_redfish_multi_credential_auth.py` 29건
  - 사용자 지정 8 조합(401+401 / timeout+401 / 401+timeout / 403+401 / 401+403 /
    transport+401 / 401+성공 / 단일 401) → **1번과 8번만 false, 나머지 전부 null**
  - 경계: 후보 0개 / 관측 누락 / 관측 초과 / 비-401 혼입 10종 / 후보 1·2·3·5개 전부 401
  - `first_auth_status` 가 첫 인증 응답임을 고정 (200 뒤의 401 은 승격 안 됨),
    무인증 요청은 기록 안 됨, 집계에 문자열 파싱 없음
  - 판정식은 **실제 Jinja2 `select('equalto', 401)`** 로도 동일 결과 교차 확인
- **전체 회귀 (보정 후)**: `pytest tests/` → **1760 passed, 11 skipped, 7 xfailed**
  (unit 1063 / e2e 328 / integration 200 / regression 169)
- **미실행**: `ansible-playbook --syntax-check`. Windows 개발 환경에 `ansible-playbook` 이
  없다. 성공으로 표기하지 않는다.

## 2026-08-10 (k) — ESXi vim25 SOAP 판정 검증 (Phase 4-B)

- **신규 fixture**: `tests/fixtures/esxi/` (README 에 출처 기록, rule 21 R2)
  - `lab/esxi_7_0_3_service_content.xml` 은 lab ESXi 3대(10.100.64.1/2/3, 모두
    ESXi 7.0.3 build-20842708, `apiType=HostAgent` / `apiVersion=7.0.3.0`)의 실측
    AboutInfo(`tests/reference/esxi/*/pyvmomi_host_dump.json` → `config_product`)를
    pyVmomi 직렬화기로 감싼 것이다. 생성 후 pyVmomi `SoapResponseDeserializer` 로 되읽어
    `vim.ServiceInstanceContent` 복원까지 확인.
  - `synthetic/` 에는 ESXi 6.0 / 6.7 / 8.0 / vCenter 8.0 ServiceContent(합성) +
    vim25 Fault 2종 + 일반 SOAP Fault 1종(음성 표본).
  - **wire capture 아님** — 해당 버전을 "검증 완료" 로 표기하지 않는다.
- **재작성**: `tests/unit/test_precheck_probe_esxi.py` 54건
  - 요청 검증: `POST /sdk` / `RetrieveServiceContent` 본문 / SOAP 1.1 Content-Type /
    `SOAPAction: "urn:vim25/6.0"` / ServiceContent 전용 본문 상한 / **자격증명 미전송** /
    TLS 정책 유지 / **retry 없음(요청 1회)**
  - Positive: lab ServiceContent / 버전 4종 fixture / 네임스페이스 접두사 변형 /
    비-200 이어도 본문이 ServiceContent 면 통과 / vim25·internalvim25 Fault 2종
  - **False Positive 13 본문 + HTTP status 단독 9종 전부 거부**: 일반 HTML / 일반 JSON /
    일반 XML / 빈 SOAP Envelope / 다른 SOAP 서비스 Response / 일반 SOAP Fault / 잘린 XML /
    vSphere 문자열만 있는 XML / 다른 vim25 응답(LoginResponse) / about 없음 /
    apiType 없음 / apiVersion 공백 / 네임스페이스 없는 Response /
    **HTTP 200·301·302·401·403·404·405·500·503 단독**
  - Evidence 위생: 실패 사유에 raw SOAP 덤프 금지 / 본문 상한 초과 거부
- **신규**: `tests/unit/test_esxi_precheck_contract.py` 14건. `run_module()` 전 경로에서
  Diagnosis 계약을 고정한다. protocol_supported / `auth_success` 항상 `null`(401·403 포함) /
  `protocol` + `PROTOCOL_CHECK_FAILED` / Phase 1 failure_reason 문구 / probe_facts 키 집합
  불변 / TCP 실패 시 Probe 미전송 / timeout 전달 / 민감정보 미노출
- **수정**: `test_os_candidate_search.py`·`test_os_precheck_integration.py` 의 esxi 회귀
  케이스에 `http_post_soap` stub 추가, `test_failure_reason_contract.py` 의 `_run_precheck`
  가 두 seam 을 함께 대체하도록 보정(+ stale 주석 정정).
- **전체 회귀**: `pytest tests/` → **1676 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3(output_schema_drift) PASS / unit 1049 / e2e 258 /
  integration 200 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **OS / Redfish 회귀 0**: `probe_os` / `ssh_banner_check` / `parse_identify_response` /
  `probe_redfish` / `parse_service_root` / `http_get` 전부 미변경. 공통 `http_post_soap` 는
  인자만 추가했고 **기본값이 종전과 같아** WinRM Identify 동작 불변.
- **미실행**: `ansible-playbook --syntax-check`. Windows 개발 환경에는 `ansible-playbook` 이
  없다. POSIX 전용 `os.get_blocking` 에 의존하기 때문이다. 성공으로 표기하지 않는다.
  대안으로 YAML 파싱 28파일 + Jinja2 문자열 스칼라 239개 컴파일 0오류 확인.

## 2026-08-10 (j) — Redfish ServiceRoot 판정 검증 (Phase 4-A)

- **신규**: `tests/unit/test_redfish_service_root_fixtures.py` 40건.
  저장소의 ServiceRoot 응답을 **전수** 판정한다.
  - `service_root.json` 28개 (cisco 4 / dell 5 / fujitsu 2 / hpe 6 / huawei 3 /
    inspur 1 / lenovo 3 / quanta 1 / supermicro 3) → **전부 PASS**
  - `recording.json` 의 비인증 `noauth::` 10개 (DMTF 표준 mockup 1 + HPE 에뮬레이터 5 +
    실장비 캡처 4: dell_r740 / hpe_csus3200 / hpe_dl380 / lenovo_sr650) → **전부 PASS**
  - fixture 개수 감소 감시 + "ServiceRoot 에서 비-200 을 반환하는 캡처가 생기면 실패" 가드
- **재작성**: `tests/unit/test_precheck_probe_redfish.py`.
  - Positive: ServiceRoot 인정 / trailing slash 2종 / RedfishVersion 4종 /
    ServiceRoot 스키마 버전 3종 / 자격증명 미전송 / verify=False 유지
  - **False Positive 17조합 전부 거부**: HTML(JSON 아님) / 빈 JSON / 일반 JSON /
    Redfish 무관 OData JSON / JSON Array / JSON 문자열 / @odata.type 없는 유사 JSON /
    @odata.id 불일치 / RedfishVersion 빈 문자열 / RedfishVersion 부재 /
    **HTTP 401·403·404·405·406·500·503 단독**
  - retry 정책 불변 확인 3건 (payload=None 만 재시도 / HTTP 응답 시 재시도 없음 /
    200 이지만 ServiceRoot 아닐 때도 재시도 없음), evidence 길이 제한
- **수정**: 다른 테스트의 ServiceRoot stub 4곳을 유효 shape 로 교체.
  `test_precheck_robustness.py` 의 비-dict JSON 케이스는 "crash 안 함 + ok=True" 에서
  "crash 안 함 + Redfish 아님으로 거부" 로 기대값 갱신.
- **전체 회귀**: `pytest tests/` → **1631 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3 PASS / e2e 258 / integration 200 / unit 1001 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **OS / ESXi**: `probe_os` / `probe_esxi` / 후보 탐색 / 포트 폴링 미변경.
  `http_get` 도 미변경(Phase 3-B 에서 추가한 headers 키 그대로). 두 채널 회귀 0.
- **schema/**: 파일 변경 0
- **환경 제약**: `ansible-playbook --syntax-check` **미실행**. Windows 에서는
  `os.get_blocking` 이 POSIX 전용이다. 대신 YAML 파싱 5종과 Jinja2 166 표현식을
  전수 컴파일해 실패 0.
- **실장비 미검증 영역**: ServiceRoot 에서 인증을 요구하는 펌웨어. 저장소에 캡처가 없어
  제거된 401/403 예외가 실제로 필요한지 확인할 수 없다. 해당 장비를 만나면
  PROTOCOL_CHECK_FAILED 로 차단된다.

## 2026-08-10 (i) — WinRM WS-Management Identify 판정 검증 (Phase 3-B 최종)

- **재작성**: `tests/unit/test_precheck_probe_os.py` 30건.
  - Positive: 5985 / 5986 정상 IdentifyResponse, 네임스페이스 표기 변형 2종,
    Identify 요청 형식(SOAP POST + `WSMANIDENTIFY: unauthenticated` + `/wsman` + verify=False)
  - **False Positive 11조합 전부 거부**: 단순 200(일반 웹서버 HTML) / 401 / 403 / 404 /
    405 / 500 / 일반 XML / 다른 네임스페이스의 IdentifyResponse / ProtocolVersion 없음 /
    ProtocolVersion 이 WS-Management 아님 / 잘린 IdentifyResponse
  - **헤더 heuristic 제거 확인**: `_looks_like_wsman` 부재 + Microsoft-HTTPAPI/401 거부
  - **비-Windows WS-Man 장비**(Openwsman) 를 Windows 로 판정하지 않음
  - XML 폭탄 방어(64KB 상한) / TLS handshake 실패 / timeout / 자격증명 미전송
- **SSH**: 구현 변경 없음. 기존 23건 중 SSH 관련 테스트 그대로 통과
  (identification 2종 / 선행 추가 줄 / SMTP 배너 거부 / 무응답 / 알 수 없는 protoversion / 읽기 상한).
- **Timeout 최악 계산**: 죽은 호스트 6초(Phase 3-A 대비 불변) / 정상 Windows 7초 /
  정상 Linux 11초 / 전 포트 열림 + 프로토콜 전멸 21초.
- **전체 회귀**: `pytest tests/` → **1566 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3 PASS / e2e 258 / integration 200 / unit 936 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **Redfish/ESXi**: `http_get` 미변경(새 `http_post_soap` 분리) → 두 채널 소비 경로 영향 0.
  regression 169 · integration 200 · baseline 10 통과.
- **schema/**: 파일 변경 0
- **환경 제약**: Windows 개발 환경이라 `ansible-playbook --syntax-check` 는 **미실행**
  (`os.get_blocking` 이 POSIX 전용). 대체 수단은 YAML 파싱 5종 + Jinja2 166 표현식
  전수 컴파일이며 실패 0.
- **한계 (보고 대상)**: lab 에 Windows WinRM 실장비가 없어 IdentifyResponse 는 **규격 기반**이며
  실측 캡처가 아니다. 네임스페이스 표기(http/https, .xsd 유무)를 4가지 허용해 방어했으나
  실장비 확보 시 실제 응답으로 재확인이 필요하다.
- **SSH 읽기 상한은 정책값**: 8줄 / 2048바이트. RFC 4253 은 선행 줄 상한을 정하지 않으며
  OpenSSH banner(/etc/issue.net)는 통상 3~10줄이다. 매우 긴 banner 를 쓰는 사이트에서는
  identification 을 놓칠 수 있어 상한 조정이 필요할 수 있다.

## 2026-08-10 (h) — OS Protocol 판정 강화 검증 (Phase 3-B)

- **신규**: `tests/unit/test_os_candidate_search.py` 24건. run_module 을 실제로 돌려
  후보 탐색 전 경로를 검증한다.
  - Case 1~4 정상 판정(5986 / 5985 / 22) + scheme + checked_ports
  - Case 12 열린 포트는 있으나 프로토콜 전멸 → `protocol` + `PROTOCOL_CHECK_FAILED`,
    `port_open=true` / `protocol_supported=false` / `detected_os=None`
  - Case 13 앞 후보 실패 후 뒤 후보 성공 → 전체 성공
  - Case 11 TCP 전멸 4조합 → Phase 3-A 매핑 유지, 프로토콜 probe 미호출
  - Case 16 auth_success 는 어떤 경우에도 null
  - Case 14 checked_ports 5조합 (중복 없음)
  - 폴링 인자 보존 (포트별 예산 2초 / poll 1초 / 순서)
  - Case 18 redfish/esxi 는 후보 탐색을 타지 않음 + probe_protocol=false 경로 잔존 확인
- **재작성**: `tests/unit/test_precheck_probe_os.py` 23건. 종전 상태 코드 whitelist
  테스트(200/401/403/405/503 → WinRM)를 폐기하고 헤더 근거 기반으로 교체.
  - **False Positive 8조합**: nginx/Apache 의 200 / 404 / 403 / 405 / 503 /
    `Basic realm="Restricted"` 401 / 헤더 없음 → **전부 거부**
  - WSMAN realm / Microsoft-HTTPAPI + 인증요구 → 인정
  - SSH: 정상 identification 2종 / 선행 추가 줄 3줄 후 identification / SMTP 배너 거부 /
    무응답 거부 / 알 수 없는 protoversion 거부 / 읽기 상한 확인
  - `/wsman` 기본 경로 + `verify=False` 확인, probe 가 자격증명 미전송 확인
- **PLAY 1 → PLAY 1.5 시뮬레이션**: 9 시나리오를 실제 템플릿으로 렌더.
  OS 판정 / scheme / protocol_supported / stage / code / auth / checked_ports / reason 전부 기대 일치.
- **전체 회귀**: `pytest tests/` → **1559 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3 PASS / e2e 258 / integration 200 / unit 929 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **Baseline / schema**: 파일 변경 0
- **환경 제약**: `ansible-playbook --syntax-check` 는 **미실행** 이다. Windows 이고
  `os.get_blocking` 이 POSIX 전용이다. 갈음한 확인은 YAML 파싱 5종, Jinja2 166 표현식
  전수 컴파일 실패 0.
- **구현 한계 (보고 대상)**: 자격증명 없이 WS-Management handshake 를 완결할 수 없어 WinRM
  판정은 **헤더 근거 기반**이다. (2) `Server=Microsoft-HTTPAPI + 인증요구` 는 결정적 증거가
  아니라 강한 정황이다. 완전한 판정은 Credential Probe 영역이며 이번 범위 밖이다.

## 2026-08-10 (g) — Phase 3-A 보정 검증 (폴링 복원 / 문구 정정)

- **신규**: `tests/unit/test_os_precheck_polling.py` 21건.
  실제 시간 기반 소켓 상태 전환을 만들 수 없어 **결정적 mock clock** 사용
  (`pb.time.monotonic` / `pb.time.sleep` 대체 → 실제 대기 0초).
  - **핵심 회귀 Case**: t=0 에 닫혀 있고 t=1.0 에 기동되는 서비스 →
    폴링(예산 2초, sleep 1) 으로 **2회째 시도에서 성공**. 대조군(단일 시도)은 실패.
  - 예산 초과 대기 없음(clock <= 2.0) / 시도별 타임아웃 = `min(5, ceil(남은))` = [2, 1]
  - timeout 실패는 1회로 끝남(wait_for 와 동일) / refused 후 예산 내 성공
  - 여러 시도의 kind 종합 우선순위 4조합
  - checked_ports 중복 없음 / 첫 성공에서 중단
  - **DNS 규칙**: 주소 시도 실패는 timeout kind, getaddrinfo 실패만 DNS kind /
    복수 주소 중 하나 실패해도 다른 주소 성공이 우선
  - **§9 채널 보호**: redfish/esxi 는 `(443, 3.0)` 단일 시도 유지, stage/code/checked_ports 불변
  - os-gather/run_precheck 배선 검증 + RST 문구에 "서버는 응답하지만" 부재 확인
- **수정**: 공유 테스트 하네스 2곳에 `port_poll_interval` 파라미터 추가,
  RST 문구 기대값 갱신.
- **전체 회귀**: `pytest tests/` → **1519 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3 PASS / e2e 258 / integration 200 / unit 889 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel exit 0
- **Baseline**: 10건 변경 없음
- **환경 제약**: `ansible-playbook --syntax-check` **미실행** (Windows, `os.get_blocking` POSIX 전용).
  대체 확인으로 YAML 파싱 5종, Jinja2 165 표현식 전수 컴파일 실패 0.
- **wait_for 실측 근거**: `ansible/modules/wait_for.py` argument_spec
  (`timeout=300`, `connect_timeout=5`, `sleep=1`, `delay=0`) + started 분기 폴링 루프 :619-628.

## 2026-08-10 (f) — OS 공통 Precheck 통합 검증 (Phase 3-A)

- **신규**: `tests/unit/test_os_precheck_integration.py` 18건. `run_module()` 을 실제로
  돌려 포트별 결과를 주입한다. 네트워크는 0.
  - Case 1~3 포트 우선순위 + OS Type + scheme + checked_ports
  - Case 4~7 전 포트 timeout / 전 포트 refused / 혼합 4조합 / DNS 실패
  - Case 8~9 IPv6 → IPv4 graceful degradation (주소군 순서)
  - 포트 점검 단계는 auth_success 를 만들지 않음 / 프로토콜을 확인했다고 위장하지 않음
  - 타임아웃 2초가 실제 전달되는지(모듈 기본 3.0 이 조용히 적용되지 않는지) / 포트당 재시도 없음
  - Case 18 민감정보 비노출
  - **Cross-channel**: redfish/esxi 는 probe_protocol 기본 true 로 Stage 3 유지,
    checked_ports=[443] 불변
- **수정**: `test_precheck_detail_propagation.py` 의 포트 순서 회귀를 공통 모듈 정본
  (`CHANNEL_DEFAULT_PORTS['os']`) 기준으로 재작성하고 `_check_ports` 실측 probed 목록 검증을
  추가했다. `test_failure_code_contract.py` 의 OS 매핑 예외 제거(해소됨) →
  code↔stage 전 채널 1:1 로 강화. `test_failure_reason_contract.py` OS 포트 전멸 3분기 검증.
- **PLAY 1 → PLAY 1.5 배선 시뮬레이션**: site.yml 템플릿을 직접 추출해 7 시나리오 렌더.
  OS 판정 / stage / code / auth / checked_ports / reason 전부 기대와 일치.
- **전체 회귀**: `pytest tests/` → **1498 passed, 11 skipped, 7 xfailed**
- **Jenkins 등가**: Stage 3 PASS / Stage 4-a 258 / Stage 4-b 200 / unit 868 / regression 169
- **하네스**: harness / boundary / output_schema_drift / envelope_change / cross_channel 전부 exit 0
- **Baseline**: 10건 shape·값 검사 통과 (변경 없음)
- **환경 제약**: `ansible-playbook --syntax-check` **미실행**. Windows 에서 Ansible CLI 진입부가
  POSIX 전용 `os.get_blocking` 을 호출한다. 대체로 YAML 파싱 5종 + Jinja2 163 표현식 전수
  컴파일 실패 0, 그리고 7 시나리오 실제 렌더까지 수행했다. lab/Jenkins 재확인 필요.
- **알려진 동작 차이 (보고 대상)**: `wait_for` 는 timeout 안에서 재시도(polling)하지만
  `tcp_check_ex` 는 포트당 1회 시도다. 부팅 중 서비스가 t=1.5s 에 열리는 경계 사례에서
  결과가 달라질 수 있다. 재시도 정책 변경은 이번 범위 밖이라 1회 시도를 채택했다.


---

> 이 아래로 60개 항목이 더 있었다. 테스트 이력은 git log 에 그대로 있으므로 여기서는 최근 12건만 유지한다.
> 과거 항목이 필요하면 `git log -p -- docs/ai/catalogs/TEST_HISTORY.md` 로 본다.
