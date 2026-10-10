# server-exporter 종합 audit (2026-05-29 audit-cleanup cycle)

> 8-auditor 병렬 전수조사 + web 검증. 브랜치 `refactor/audit-cleanup-20260529`.
> 본 문서 = **적용 완료** 요약 + **lab/ansible 검증 필요로 미적용한 권고 backlog**.
> 미적용 사유 분류: `[ANSIBLE]` (본 환경에 ansible 없음 — syntax/런타임 검증 불가), `[LAB]` (실장비 필요), `[AUTH]` (인증 동작 변경 — 사용자 "특히 인증" 주의), `[CONTRACT]` (호출자 계약/스키마).

---

## 0. 적용 완료 (이 cycle, 검증됨)

| # | 작업 | 검증 |
|---|---|---|
| stale 26곳 | redfish 3430→3812 / field_dict 74·65→83 / pytest 148→699 / adapter 41·30→42·31 / README 28→31 / test 41·365→42·375 | grep 0 잔존 |
| dead code | `pre_edit_guard.py`(broken+unwired) + `collect.yml`/`normalize_sections.yml`(deprecated shim) 삭제, `build_errors_from_diagnosis` 필터·`import os` 제거 | pytest 699 + py_compile |
| redfish dedup | `_ne`/`_ne_p` 중복 stripping 로직 3→1 (`_strip_or_none` 위임) | pytest 699 |
| docs 정리 | 완료-cycle 덤프 164 삭제 + 26 archive + dangling ref 26 수정 | harness 일관성 PASS |
| CSUS 정직성 | mock baseline registry 라벨 `_MOCK` 태그 + "정식 지원"→"lab 부재 미검증" + self-consistency 가드 테스트 4 신설 | regression 151 PASS |
| 보안 런북 | `docs/ai/policy/SECRET-ROTATION-RUNBOOK.md` (문서화만 — 사용자 결정) | — |
| redfish perf (CQ-02) | SSL context `verify_ssl` 별 1회 빌드 후 재사용 (`_CTX_CACHE`) — host당 30~150 재생성 제거. 동작 동일 | pytest 703 + py_compile |

> **Round 2 검증 노트 (WSL ansible core 2.16 확보 후 재검증)**:
> - **EX-01 (`gather_cpu.yml` `\| float` raise) = 오탐**. WSL ansible 실측: `'abc' \| float` → `0.0` (raise 안 함), `\| int` → `0`. Jinja2/Ansible 필터가 이미 default 반환 → 기존 코드(`if not max_mhz_int` fallback)로 graceful. **변경 불필요** (auditor 오진단 — empirical 반증).
> - redfish-gather/site.yml `--syntax-check` **PASS** (shim 삭제 후 regression 0). os/esxi 는 parse-time vault decrypt 로 WSL(무vault) 미검증 — 운영 Jenkins 정상.

> `registry.yml` 은 2026-10-11 삭제됐다 — 2026-10-10 감사에서 읽는 코드 · 시험이 없음을 확인했다(위 "테스트가 소비" 는 그 사이에 사실이 아니게 됐다).

---

## 1. [AUTH] 인증 동작 권고 — 운영 lockout 위험 (사용자 "특히 인증" 영역)

> 모두 인증 흐름 변경 → 실장비/ansible 검증 필수. 본 환경 미적용.

### A1. BMC 계정 lockout 위험 — `detect_vendor` 의 선(先)인증 4-GET  `[AUTH][LAB]`
- 위치: `redfish-gather/library/redfish_gather.py` `detect_vendor` (Systems coll + first member + Managers + Chassis ≈ 4 authed GET) → `collect_standard.yml:52-60` 가 **모든 vault 계정**을 순회.
- 위험: 잘못된/회전된 자격 1개당 ~4 인증 시도. HPE iLO 는 3 fail 에 lockout(escalating delay, web 확인) < 4 GET. 5-계정 vault → ~20 fail/host. 잘못된 vendor→잘못된 vault profile 시 체계적 lockout → 옳은 자격까지 차단.
- 권고: detect 단계에서 **단일 인증 probe** 후 401 이면 즉시 그 계정 abort (4-GET 전에). per-host 401 카운터로 vendor 임계치 근접 시 추가 계정 시도 중단. `try_one_account.yml` 의 5s backoff 는 계정 *사이* 만 — 한 시도 내 다중 GET 에는 미적용.
- 검증: lab BMC 1대로 잘못된 자격 주입 → lockout 발생 전 abort 확인.

### A2. OS 다중 자격 루프 — backoff/lockout 가드 부재  `[AUTH][LAB]`
- 위치: `os-gather/tasks/try_one_credential.yml:33-46` (win_ping/raw, sleep 없음), `try_credentials.yml:34-42` (전 `_os_accounts` 순회). Redfish 와 달리 backoff 0.
- 위험: stale 자격 → 반복 WinRM 인증 실패 → **AD 계정 lockout** (도메인 전체 영향). 
- 권고: Redfish 와 동일 5s backoff + max 시도 cap. Windows 는 순회 전 단일 probe.

### A3. account_service `dryrun=false` 기본값 — read job 이 BMC 계정 변경  `[AUTH][LAB]`
- 위치: `redfish-gather/tasks/account_service.yml:42-43` `_rf_account_service_dryrun | default(false)`; recovery 자격 성공 시 `site.yml:117-121` 가 호출 → `redfish_gather.py:3446-3485` 가 DELETE+POST.
- 위험: recovery fallback 한 수집 job 이 BMC 계정을 **변경**. DELETE 성공 + POST 실패 시 BMC 에 admin 계정 0 → write-side 장애.
- 권고: 기본 `dryrun=true`, 명시 opt-in 시만 provision. DELETE 전 POST 검증(transactional). ADR-2026-04-30 이 dryrun=false 를 "사용자 승인"으로 기록 — 재검토 권고.

### A4. vault 로드 실패가 무인증 수집으로 silent fallback  `[ANSIBLE]`
- 위치: `redfish-gather/tasks/load_vault.yml:29-36,49-60` `failed_when: false` → `_rf_accounts=[]` → `collect_standard.yml:28` 빈자격 시도. 신호는 debug 한 줄뿐.
- 위험: 잘못된 vault profile(파일 누락) → 0 계정 → 무인증 수집 → "auth failed" envelope 인데 근본원인(vault 미로드) 미표시 → 운영 진단 불가.
- 권고(additive, envelope shape 변경 0): profile 기대했는데 `_rf_accounts==[]` 면 `errors[]`/`diagnosis.details` 에 vault 경로+사유 구조화 추가.
  ```yaml
  - name: "redfish | vault 미로드 진단"
    ansible.builtin.set_fact:
      _rf_vault_missing_err:
        section: diagnosis
        message: "vault profile '{{ _rf_vault_profile }}' load 실패 — 무인증 진행"
    when: _rf_vault_profile | default('') != '' and (_rf_accounts | default([]) | length) == 0
  ```
  (정확 통합 지점은 build_errors 흐름 — ansible 실행 환경에서 검증 후 적용)

---

## 2. [PERF] 성능 권고 (실장비 round-trip 비용)

### P1. CSUS/Superdome 대표 partition 2회 fetch  `[LAB][CONTRACT]`
- 위치: `redfish_gather.py` `main()` L3785 `_collect_all_sections(system_uri)` + L3794 `_collect_multi_node_topology()` 의 `gather_systems_multi` 가 첫 멤버(대표) 섹션을 재수집.
- 비용: DIMM/drive 많은 RMC 에서 +50~200 HTTP round-trip/host → throttle/timeout 위험.
- 권고: `manager_layout` 설정 시 대표 멤버는 single-node 경로 skip 또는 memoize. (CSUS 계약 회귀 필요 — mock baseline + lab.)

### P2. network-adapters N+1 + firmware fetch-then-discard  `[LAB]`
- `gather_network_adapters_chassis` (L2278): adapter당 `1 + A·(2+P+F)` GET. firmware (L2454): Dell `Previous-`/`N/A` 컴포넌트를 **fetch 후 버림** (+50~150 낭비 GET).
- 권고: firmware `Previous-` 는 member URI 마지막 segment 로 fetch **전** 필터. BMC 지원 시 `$expand` 로 member fetch 통합 (펌웨어별 지원 상이 — adapter capability gate, rule 96).

### P3. SSL 컨텍스트 매 HTTP 호출마다 재생성  → **[적용됨 cycle 2026-05-29 CQ-02]**
- `_ctx(verify_ssl)` (L82-115) 가 `create_default_context()`+`set_ciphers` 를 호출당 실행 (30~150회/host).
- **적용**: `_CTX_CACHE = {}` module-global + `verify_ssl(bool)` 별 1회 빌드 후 재사용. SSLContext 다중연결 재사용은 Python 표준. 동작 동일 (pytest 703 PASS). Ansible module = host당 단일 subprocess → thread-safety 무관.

---

## 3. [REFACTOR] 코드 품질 backlog (`redfish_gather.py` 3812줄)

| ID | 항목 | 위치 | 사유 |
|---|---|---|---|
| R-1 | `account_service_provision` 381줄 (live BMC write 경로) → 3 전략(`_provision_patch_slot`/`_post_standard`/`_post_id_role_remap`)로 분할. `_ACCOUNT_CREATE_STRATEGY` dict 가 이미 분기 명명 | L3313-3693 | `[AUTH]` write 경로 — 신중 |
| R-2 | `_get/_post/_patch/_delete` 4중 예외-tail + 헤더 3중 중복 → `_request` core 1개. Lenovo User-Agent hotfix 가 `_get` 에만 있어 verb 간 drift | L121-223 | `[AUTH]` HTTP core |
| R-3 | status 게이트가 `'HTTP 401' in detail` **문자열 매칭** (L3186, `_compute_final_status`) — `_get` 가 이미 반환하는 숫자 코드 대신. 메시지 포맷 변경에 취약 (rule 13 R8) | L3168-3195 | `[CONTRACT]` status 로직 — verify-status-logic 필요 |
| ~~R-4~~ | 매직넘버 상수화 + `raid_map` module-level | 산재 | **[DONE] 2026-06-08 재확인** — `BYTES_PER_GB_DECIMAL`/`BYTES_PER_MIB`/`MIB_PER_GIB`/`MBPS_PER_GBPS`(L52-55) + `_VOLUMETYPE_RAID_MAP`(L1856) 이미 module-const |
| R-5 | 21개 함수 >50줄 (`gather_network_adapters_chassis` 176, `gather_bmc` 147, `gather_system` 117 …) — GET+normalize 분리 (rule 10 R3) | — | 점진 |

> stdlib-only 는 **CLEAN 확인** (json/socket/sys/traceback + AnsibleModule 만). 위반 0.

### CSUS per-partition normalize 중복  `[LAB][CONTRACT]` (CS-3)
- `_normalize_storage_raw`/`_normalize_network_raw`/`_normalize_cpu_raw`/`_normalize_memory_raw` (L2816~2948) 가 top-level `normalize_standard.yml` 의 grouping/summary 로직을 **Python 으로 재구현** (~210줄 평행 경로). drift 가드 테스트 없음.
- 권고: lab 검증 전까지 per-partition 을 raw passthrough 로 단순화 **또는** 같은 raw fixture 를 두 경로(ansible/python)에 통과시켜 동등성 parity 테스트 추가. (envelope shape 자체는 정상 — `multi_node` Additive, 타 벤더 null gate 확인됨.)
- **[PARTIAL] 2026-06-08** — Python 측 drift 가드 추가: `tests/unit/test_partition_normalize_grouping.py` (17 함수/29 케이스). 기존 `test_hpe_csus_multi_node.py` 의 동질 happy-path 가 못 잡던 **grouping 키 판별**(storage cap|media|protocol|model / memory cap|type|speed|mfr|part / cpu model)을 이질 입력으로 고정 + zero-skip / dedup-collapse / gateway dedup / 0.0.0.0 필터 커버. **ansible↔python full parity 는 미해결**(ansible-playbook CLI 부재) — fixture 두 경로 통과 비교는 Jenkins Agent 에서 후속. raw passthrough 단순화는 미채택(현 canonical shape 가 호출자 계약 — rule 13).

---

## 4. [ARCH] 아키텍처 권고

| ID | 항목 | 위치 | 비고 |
|---|---|---|---|
| AR-1 | **esxi vendor 정규화가 substring fallback 누락** → `"Dell Inc"`(마침표 없음) 가 redfish 는 'dell' 로 정규화되나 esxi 는 raw 패스스루. `vendor` envelope 필드 divergence (실제 버그) | `esxi-gather/site.yml:162-175` (인라인 Jinja2) | **[PARTIAL] 2026-06-08** — redfish reference 단위 테스트 고정(`tests/unit/test_vendor_normalize_aliases.py` 16). esxi YAML 수정 recipe = NEXT_ACTIONS §0.8 (Jenkins Agent — ansible CLI Windows 미동작 + `[ANSIBLE]` defer) |
| ~~AR-2~~ | JEDEC 제조사 테이블 2곳 (`filter_plugins/jedec_mapper.py` ↔ `redfish_gather.py:266 _JEDEC_VENDORS`) — memory `manufacturer` drift 위험 | — | **[DONE] 2026-06-04** — `tests/unit/test_jedec_drift_guard.py`(5 test: 공유 byte 값 일치 + VENDOR_NAME_NORMALIZATION mirror + 방향성). 통합 대신 drift 가드(rule 10 R2 self-contained 보존, 통합은 stdlib-only 모듈 충돌로 미채택). 2026-06-08 재확인 |
| AR-3 | `adapters/registry.yml` 을 loader 는 안 읽고 test 만 소비 — CLAUDE.md 가 "master index"로 기술 → 오해 소지 | — | loader 가 소비하게 하거나 문서에서 "test manifest"로 명확화 (삭제 금지 — test 의존) | (2026-10-11: 파일 삭제로 종결 — 읽는 코드 · 시험 없음 확인)
| AR-4 | `build_output.yml` 이름 충돌 (`common/.../build_output.yml` 정본 ↔ `os-gather/.../build_output.yml` orchestrator). os 만 wrapper 파일, esxi/redfish 는 site.yml 인라인 — 비일관 | — | `[ANSIBLE]` rename(`build_chain.yml`) 권고 |
| AR-5 | `try_credentials.yml` os/esxi 구조 중복 → `common/` 파라미터화 | — | `[AUTH]` 신중 |
| AR-6 | vendor `normalize_oem.yml`(cisco/huawei/inspur) debug 가 legacy `_collected_data`(현 `_merged_data`) 참조 — 항상 false dead debug | — | `[ANSIBLE]` debug-only, 무해. 정리 시 빈 파일 parse 주의 |

> **건전성 확인**: common→channel 단방향·비순환, fragment 단일 mutation 지점, vendor 경계 fenced — 핵심 계층 건전. cruft 는 가장자리(dead config/stale debug)에 국한.

---

## 5. [LAB] 실장비/사이트 fixture 대기 (기존 NEXT_ACTIONS 와 연동)
- CSUS 3200 / Superdome Flex 실 RMC fixture (C1) → mock baseline 교체 + per-partition 검증 (CS-3)
- FC HBA / InfiniBand 보유 사이트 (storage.hbas / storage.infiniband — 코드 real, lab 하드웨어 부재로 empty)
- network.adapters/ports/driver_map redfish/os baseline 재캡처 (코드 추가 후 baseline stale — DRIFT-A false flag 해소)
- Windows `system.runtime` baseline 재캡처 (Linux 는 채움, Windows baseline stale)

## 관련
- 보안: `docs/ai/policy/SECRET-ROTATION-RUNBOOK.md`
- 결정: `docs/ai/decisions/ADR-2026-05-29-audit-cleanup.md`
- 정본: `docs/ai/NEXT_ACTIONS.md`, `docs/ai/CURRENT_STATE.md`
