# CONVENTION_DRIFT — server-exporter

> 발견된 컨벤션 위반 / 임시 구현 / 외부 계약 drift 기록 (DRIFT-XXX).
> rule 92 R2 (즉시 수정 금지) — 정상 동작 중이면 마이그레이션 계획 후 단계적 정리.

## 형식

```
## DRIFT-XXX (YYYY-MM-DD)

- 발견 위치: <file:line>
- 분류: convention-violation / temporary-impl / external-contract-drift / catalog-stale
- 설명: <1-2줄>
- 영향: <범위>
- 제안: <수정 방향>
- 상태: open / planned / migrating / resolved
- 관련: rule N / skill X / agent Y
```

---

## DRIFT-024 (2026-10-10, resolved — 서술 정정)

- **발견 위치**: `.claude/rules/12-adapter-vendor-boundary.md` R4 · `.claude/skills/add-vendor-no-lab/SKILL.md` 2절 · `docs/develop/03-adapter-system.md` 4절 Step 4 · 예시 주석
- **분류**: catalog-stale (rule 본문 · 문서가 코드와 다름)
- **설명**: rule 12 R4 는 "adapter 는 `match`/`capabilities`/`collect`/`normalize` 4개 키 필수 — 누락 시 adapter_loader 파싱 실패" 라고 적었다. 코드는 다르다 —
  로더(`module_utils/adapter_common.py` · `lookup_plugins/adapter_loader.py`)가 읽는 키는 `match`(없으면 `{}`) · `adapter_id` · `priority` · `generic` 뿐이고 어떤 키도
  강제하지 않는다. 플레이북이 읽는 adapter 속성은 `adapter_id` · `capabilities.sections_supported` · `vendor_notes.manager_layout` · `version`(`build_meta.yml` → meta.adapter_version — 현 adapter 들에는 없어 null) 뿐이다(2026-10-10 grep).
  `collect.standard_tasks` · `normalize.standard_tasks` · `credentials.profile` · `graceful_degradation` 은 어떤 코드도 읽지 않는다 — 수집 · 정규화 task 경로는 site.yml 에
  고정이고 복구 vault 는 감지된 vendor 로 고른다. OS · ESXi adapter 12개는 `normalize` 키 없이 운영 중이다(`adapters/os/*.yml` · `adapters/esxi/*.yml`).
- **영향**: 규칙 · 문서만. 수집 동작 · production tree 변화 없음.
- **resolved (2026-10-10)**: rule 12 R4 를 코드대로 고쳤다(`docs/ai/decisions/ADR-2026-10-10-adapter-required-keys.md`). skill · 개발 문서 Step 4 · 예시 주석 정정.
  기록용 키(`collect` · `normalize` · `credentials` · `graceful_degradation`)를 adapter 에서 지울지는 별도 결정(지우면 runtime tree 가 바뀌어 새 후보가 필요) — NEXT_ACTIONS.
- **관련**: rule 12 R4 · rule 70 R8(ADR 트리거) · rule 96 R1

## DRIFT-023 (2026-10-10, resolved 2026-10-10 full-audit)

- **무엇**: 식별자(serial/uuid/vendor/model/bios) 자리표시자 목록이 `gather_system.yml`(Linux 6곳 · Windows 2곳) 과 `redfish_gather.py`(invalid_values) 에
  복제돼 있었고 ESXi 는 아무것도 거르지 않았다(`NA` 가 serial 로 나감). SMBIOS 공장 기본 UUID `03000200-0400-0500-0006-000700080009` 는 식별자로 통과했다.
- **해결**: `identity_normalizer.DMI_SENTINELS` + `dmi_sentinel_null(kind)` 필터 하나를 3채널 템플릿이 쓰고, Redfish(stdlib 전용)는 `_SERIAL_SENTINELS_UPPER`
  복제본을 `tests/unit/test_identity_sentinels.py` 가 drift 가드한다. 자리표시자 UUID 는 `normalize_uuid` 가 null 로.
- **관련 rule**: rule 13 cross-channel · rule 22 R5.
- **번호 메모**: 처음 DRIFT-017 로 적었다(커밋 `32d4e307` 메시지 · 대장 기록). 그 번호는 2026-06-08(DRIFT-017 audit-cleanup) 항목이 이미 쓰고 있어 2026-10-10 에 재번호했다.

## DRIFT-022 (2026-10-10, resolved 2026-10-10 full-audit)

- **무엇**: JEDEC 제조사 표가 두 곳(`filter_plugins/jedec_mapper.py` · `redfish_gather._JEDEC_VENDORS`)에 byte 전용 키로 있었고, bank(continuation 수)를
  보지 않아 bank 1 의 0x98(Kingston) 과 bank 0 의 0x98(Toshiba) 을 구분하지 못했다. `"0B": "Intel"` 항목은 JEP106 과 다르다(0x0B 는 Intersil, Intel 은 0x89/0x09).
  어느 쪽도 origin 주석(rule 96 R1)이 없었다.
- **해결**: (bank, 7-bit ID) 키 표 하나를 두 파일에 동일하게(JEP106BE — docs.rs jep106 codes.rs · lshw jedec.cc · Linux mtd/cfi.h, 확인 2026-10-10) 두고
  `tests/unit/test_jedec_drift_guard.py` 가 표 동일성 + 해석기 동치(28 입력)를 지킨다. 모르는 코드는 원문 그대로.
- **관련 rule**: rule 96 R1 · R4, rule 13 cross-channel.
- **번호 메모**: 처음 DRIFT-016 로 적었다(커밋 `32d4e307` 메시지 · 대장 기록). 그 번호는 2026-05-11(DRIFT-016 field-channel-refinement) 항목이 이미 쓰고 있어 2026-10-10 에 재번호했다.

## DRIFT-021 (2026-10-10, resolved)

- **발견 위치**: `os-gather/tasks/linux/gather_cpu.yml` 의 L2/L3 캐시 환산(종전)
- **분류**: external-contract-drift
- **설명**: lscpu 출력의 캐시 값이 합계인지 인스턴스당인지가 util-linux 버전마다 다르다 — ≤2.33 인스턴스당("256K"), 2.34~2.36 모든 인스턴스 합계(문구 없음, "48 MiB"),
  ≥2.37 합계 + "(N instances)"(util-linux `sys-utils/lscpu.c`). 종전 코드는 "(N instances)" 유무만 봐서 2.34~2.36 의 합계를 인스턴스당 값으로 보고 L2 를 코어 수만큼 또 곱했다(검수 C7).
- **영향**: Linux `cpu.summary.groups[].l2_cache_kb` · `l3_cache_kb` 값(의미는 소켓당 KB, 불변). 2.34~2.36 을 싣는 배포판에서 과대값.
- **resolved (2026-10-10 `cce90cb4`)**: 같은 raw 태스크에서 `lscpu --version` 을 읽어(`LSCPU_VERSION`) 2.34 이상 또는 문구가 있으면 합계 ÷ 소켓, 2.33 이하는 기존 규칙,
  버전 미상 + 문구 없음은 추측하지 않는다(L2 `null`, L3 는 `/proc/cpuinfo`). 회귀 `tests/unit/test_linux_cpu_cache_c7.py`(2.17 ng · 2.32 · 2.34 · 2.36 · 2.37+ · 부재 · 미상).
  2.34~2.36 실장비는 없다(재현만).
- **관련**: rule 96 R1 / R4, `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` 2026-10-10

## DRIFT-020 (2026-10-10, resolved)

- **발견 위치**: `os-gather/tasks/windows/gather_storage.yml` 의 `MSFC_FibrePortHBAAttributes.PortSpeed` 값맵(종전)
- **분류**: external-contract-drift
- **설명**: PortSpeed 는 비트 값이다 — Microsoft SDK `hbaapi.h` 정의 1=1G · 2=2G · 4=10G · 8=4G · 16=8G(`HBA_FCPHYSPEED_8GBIT`) · 32=16G(`HBA_FCPHYSPEED_16GBIT`).
  종전 표는 4 · 8 · 16 을 4 · 8 · 10 Gbps 로 바꿔 10G/4G/8G 포트를 잘못 보고했다(검수 C6).
- **영향**: Windows `storage.hbas[].link_speed_gbps`(Nice). Linux · ESXi · Redfish 무관.
- **resolved (2026-10-10 `75c55e38`)**: 공식 정의대로 고쳤다. 0 · 0x8000(미협상)은 `null`. 64 · 128 등 Windows · 벤더 HBA 인터페이스 정의를 확인하지 못한 코드는
  **미상 코드**로 `null`(근거 확인 코드와 구분해 주석 · 문서에 적음) — 다른 API(Linux `FC_PORTSPEED` 등) 표를 옮겨 오지 않았고, 오래된 헤더에 없다는 이유로 무효라 하지 않았다.
  회귀: 실제 PowerShell 로 1 · 2 · 4 · 8 · 16 · 32 · 64 · 0 · 128 · 32768.
- **관련**: rule 96 R1 / R4, source https://raw.githubusercontent.com/microsoft/win32metadata/main/generation/WinSDK/RecompiledIdlHeaders/shared/hbaapi.h (확인 2026-10-10)

## DRIFT-019 (2026-10-08)

- **발견 위치**: `Jenkinsfile_portal_Byid` (GitLab 웹 편집 `87c47f8d` · `09fb4890` → 병합 `2cd63067`)
- **분류**: convention-violation
- **설명**: rule 80 R1 · rule 00 · `JENKINS_PIPELINES.md` 는 "파이프라인은 `Jenkinsfile_portal` 하나"(2026-09-28 portal 사본 삭제)라고 적는데,
  GitLab 관리자가 main 에 `Jenkinsfile_portal` 의 통째 사본을 올렸다. 원본과 차이는 `inventory_json` 의 `defaultValue: '[{"bmc_ip":"","by_id":""}]'` 1줄.
  2,036줄 전부 CRLF 로 저장돼 `.gitattributes`(Jenkinsfile* eol=lf)와 어긋나 있던 것은 `1566454a` 에서 줄끝만 LF 로 맞췄다(줄끝 무시 diff 0).
- **영향**: 원본 수정이 사본에 따라가지 않는다(시간이 지날수록 어긋난다). production 생성 대상이 아니다(`production_manifest.yml` runtime_roots 밖) —
  Byid Job 이 production 브랜치를 checkout 하면 파일이 없다. CI 검사 · 수집 코드 영향 없음. `by_id` 는 `se_host_input` 에 보존만 되고 결과 본문에는 돌아오지 않는다.
- **제안**: 사용자 · 작성자 결정 — (a) 사본 유지 + rule 80 · 카탈로그에 공식 등재(ADR), (b) 원본에 기본값만 반영하고 사본 삭제. 결정 전에는 내용을 고치지 않는다(rule 92 R2).
- **상태**: resolved (2026-10-09 — 사용자 결정 "맞춰라": 사본 유지 · portal 과 동기화. `ADR-2026-10-09-portal-byid-copy.md`,
  `tests/unit/test_jenkinsfile_portal_byid_sync.py` 가 차이 1줄 · 위치 · 줄끝을 강제. rule 80 · rule 00 서술 정정)
- **2026-10-09 메모**: 사용자 작업지시서("로그 문구 개선")가 Byid 에도 같은 표현을 적용하라고 해서 내용을 portal 과 맞췄다(`11907cb6` · `2c6d71f3`).
  차이는 그대로 `inventory_json` 기본값 1줄이다. 사본 유지 · 삭제 결정은 여전히 열려 있다 — 결정 전까지 portal 을 고칠 때마다 같은 방식으로 맞춘다.
- **관련**: rule 80 R1 / rule 00 / rule 92 R2 / `docs/ai/catalogs/JENKINS_PIPELINES.md` / `docs/ai/NEXT_ACTIONS.md` 2026-10-08

## DRIFT-018 (2026-07-02, resolved cycle is-os-disk)

- **발견 위치**: `schema/field_dictionary.yml:33` 헤더 + 카운트 기재 12곳 (CLAUDE.md / schema/README.md / rules 00·13·23 / ai-context output-schema·common×2 / role output-schema README×3 / skills update-output-schema-evidence / PROJECT_MAP)
- **분류**: catalog-stale
- **설명**: 카운트 문서가 "Must 47 / Nice 81 / Skip 6 = 134" 로 기재됐으나 실측(YAML 파싱 + `grep -c "priority:"`)은 "Must 47 / **Nice 115** / Skip 6 = **168**". must(47)·skip(6) 은 일치, **nice 만 34 어긋남** → 2026-06-22 T1/T2 cycle(`controllers[]` 서브필드 / `memory.slots[]` 7서브필드 channel os / `physical_disks.health` 등 Nice 다수 추가)이 카운트 문서를 미갱신. DRIFT-001 / DRIFT-007 과 동종 반복.
- **영향**: 문서 간 불일치. 코드/검증 영향 없음 (`validate_field_dictionary.py` 는 동적 카운트, 하드코딩 assertion 없음 — 실측 확인).
- **제안/조치**: 전 카운트 기재를 실측(168 / Nice 115)으로 정정 (is_os_disk +1 포함). 향후 additive Nice cycle 마다 카운트 동반 갱신 (rule 13 R7 정신).
- **상태**: resolved (2026-07-02 — 13곳 정정 + is_os_disk 추가 cycle)
- **관련**: rule 13 R7 / rule 28 R1 #1 / rule 70 R8 / DRIFT-001 / DRIFT-007 / `tests/evidence/2026-07-02-is-os-disk.md`
- **감사 addendum (2026-07-02, is-os-disk-audit)**: 초기 13곳 sweep 이 놓친 추가 stale 발견·정정 — `schema/output_examples/README.md`, `docs/ai/catalogs/SCHEMA_FIELDS.md`(83 로 더 오래된 stale) + `FIELD_USAGE_MATRIX.md`(regen), `.claude/rules/92`(count-agnostic 전환), `.claude/policy/measurement-targets.yaml`, PROJECT_MAP fingerprint(--update). `docs/ai/catalogs/VENDOR_ADAPTERS.md` 는 dated cycle-log(역사적)이라 보존. 최종 실측 168/Nice 115 전 위치 동기화.

## DRIFT-017 (2026-06-08, resolved cycle audit-cleanup)

- **발견 위치**: `redfish-gather/library/redfish_gather.py:1192` `_normalize_link_status`
- **분류**: external-contract-drift
- **설명**: DMTF DSP8010 2026.1 공식 스키마 대조 결과, `Port.LinkStatus` enum 정본
  `[LinkUp, Starting, Training, LinkDown, NoLink]` 중 표준 전이 상태 `Starting`/`Training` 을
  정규화 함수가 미처리 → raw lowercase('starting'/'training') 통과. 함수 contract(up/down/unknown)
  위반(이 두 값은 vendor-specific 이 아니라 DMTF 표준이므로 raw 보존 분기에 빠지면 안 됨).
- **영향**: 네트워크 인터페이스 `link_status` 필드. BMC 가 협상 중 포트를 Starting/Training 으로
  보고하는 드문 전이 케이스에서 호출자가 미인식값 수신. fixture/baseline 에는 0건(전이 상태라 비영속).
- **제안/조치**: down 버킷에 `starting`/`training` 추가 (기존 disabled/inactive/offline 매핑과 일관 —
  비작동 상태). Additive only(rule 96 R1-B): envelope shape / 기존 매핑 불변. 회귀 테스트 6건 추가.
- **상태**: resolved (2026-06-08 — 보정 + 회귀 테스트 + EXTERNAL_CONTRACTS 등재)
- **관련**: rule 96 R1/R1-B, rule 92 R2, `schema/redfish_dmtf_2026.1/`,
  `docs/ai/catalogs/EXTERNAL_CONTRACTS.md` (DMTF DSP8010 2026.1 대조), `tests/unit/test_redfish_pure_helpers.py`

## DRIFT-016 (2026-05-11, resolved cycle field-channel-refinement)

- **발견 위치**: `schema/field_dictionary.yml` 의 다음 3 entries
  - `memory.installed_mb` (line 267-277) — channel `[redfish, os, esxi]` 선언
  - `memory.visible_mb` (line 279-288) — channel `[redfish, os, esxi]` 선언
  - `system.runtime` (line 950+) — channel `[os]` 선언
- **분류**: convention-violation (channel 선언 ↔ baseline 실측 불일치)
- **설명**: `field_dictionary.yml` 의 `channel:` 배열이 8 baseline 실측과 불일치. 사용자 명시 — "Redfish memory.visible_mb 같은 항상 null 인 필드 정리".
  - `memory.visible_mb × redfish`: Redfish API spec 미정의 (Memory.v1_*.json 에 VisibleMiB 없음) — 4 redfish baseline 모두 null
  - `memory.installed_mb × esxi`: ESXi 는 ansible_memtotal_mb 만 (DIMM slot 없음)
  - `system.runtime`: OS 채널 선언이지만 3 OS baseline 모두 missing. ESXi baseline 만 present (DRIFT-B)
- **영향**: 호출자 시스템이 channel 배열을 lookup 으로 사용 시 잘못된 가정 가능
- **제안**: channel 배열 정밀화 + help_ko 갱신 + add-new-vendor skill 에 분류 검증 단계 추가
- **상태**: resolved (cycle field-channel-refinement Phase 3 적용)
  - `memory.visible_mb` `[redfish, os, esxi]` → `[os, esxi]`
  - `memory.installed_mb` `[redfish, os, esxi]` → `[redfish, os]`
  - `system.runtime` `[os]` → `[esxi]`
- **관련**: rule 13 R7 / rule 28 R1 #13 / rule 70 R8 / rule 92 R2 / rule 96 R1-B / ADR-2026-05-11-field-channel-declaration-refinement / `docs/ai/catalogs/FIELD_USAGE_MATRIX.md` / `scripts/ai/measure_field_usage_matrix.py`

---

## DRIFT-001 (2026-04-27)

- **발견 위치**: 본 하네스 도입 시점 catalog (Plan 3) ↔ 실 코드 (`schema/field_dictionary.yml`)
- **분류**: catalog-stale
- **설명**: 하네스 도입 문서들 (`rule 13`, `Plan 1 design`, `CLAUDE.md`, 일부 catalog)에서 `Field Dictionary 28 Must`로 표기. cycle-002 분석에서 grep 카운트 기반으로 "Must 29 + Nice 8"로 정정.
- **영향**: 문서/문서 간 불일치. 실 운영에 영향 없음 (코드는 정상).
- **상태**: resolved (2026-04-27 cycle-003) — **단, 정정값 자체가 잘못됨**, DRIFT-007에서 재정정.
- **관련**: rule 13 (output-schema-fields), `docs/ai/catalogs/SCHEMA_FIELDS.md`, **DRIFT-007**

## DRIFT-002 (2026-04-27)

- **발견 위치**: 본 하네스 도입 문서 ↔ 실 Jenkinsfile* 3종
- **분류**: catalog-stale
- **설명**: 하네스 도입 문서에서 "4-Stage = Validate / Gather / Validate Schema / **E2E Regression**" 일반화 표기. 실측 결과:
  - `Jenkinsfile`: Stage 4 = E2E Regression ✓
  - `grafana 파이프라인(제거됨)`: Stage 4 = **Ingest** (Grafana 데이터 적재)
  - `Jenkinsfile_portal`: Stage 4 = **Callback** (호출자 통보)
- **영향**: 문서/문서 간 불일치. 실 운영에 영향 없음.
- **제안**: rule 80 (ci-jenkins-policy) 본문 정정 — Stage 4가 Jenkinsfile별로 다름을 명시. CLAUDE.md / design / Plan 1 동시 갱신.
- **상태**: resolved (2026-04-27 cycle-003)
- **관련**: rule 80, `docs/ai/catalogs/JENKINS_PIPELINES.md`, `docs/operate/01-jenkins-master.md`, `docs/operate/04-pipeline-runtime.md`

## DRIFT-003 (2026-04-27)

- **발견 위치**: 외부 API 공식 문서 ↔ 실 `adapters/redfish/`
- **분류**: catalog-stale
- **설명**: vendor-bmc-guides.md 작성 시 일부 adapter 이름 추정 — 실측에서 정정:
  - HPE: `hpe_synergy.yml` (없음) → 실제 `hpe_ilo4.yml`
  - Supermicro: `supermicro_x12.yml` (없음) / `supermicro_legacy.yml` (없음) → 실제 `supermicro_x11.yml` / `supermicro_x9.yml` / `supermicro_bmc.yml`
  - Lenovo: `lenovo_xcc_legacy.yml` (없음) → 실제 `lenovo_imm2.yml`
- **영향**: reference 문서 stale. VENDOR_ADAPTERS.md는 실측으로 정정됨.
- **제안**: vendor-bmc-guides.md 동기화 (다음 cycle).
- **상태**: resolved (2026-04-27 cycle-003)
- **관련**: `docs/ai/catalogs/VENDOR_ADAPTERS.md`, 외부 API 공식 문서

## DRIFT-004 (2026-04-27, resolved 2026-04-28)

- **발견 위치**: `schema/sections.yml` ↔ `schema/field_dictionary.yml`
- **분류**: convention-violation
- **설명**: cycle-004 W3-C `output_schema_drift_check.py` 정밀화 후 검출. `sections.yml`의 `users` 섹션 (channels: [os], OS gather에서 사용자 list 수집)이 `field_dictionary.yml`의 `fields:` 등록 prefix에 없음.
- **수정 (cycle-006)**: `field_dictionary.yml`에 6 항목 추가 — `users[]` (must), `users[].name` (must), `users[].uid` (must), `users[].groups` (nice), `users[].home` (nice), `users[].last_access_time` (skip).
  - 분포: Must 28→31, Nice 7→9, Skip 5→6, 총 40→46 entries
  - 영향 vendor baseline: 실측 ubuntu/windows baseline에 이미 users entries 존재 (회귀 0)
  - output_schema_drift_check.py: 정합 (sections 10 = fd_section_prefixes 10)
- **상태**: resolved (2026-04-28 cycle-006)
- **관련**: rule 13 R1 / R2, `schema/sections.yml`, `schema/field_dictionary.yml`

## DRIFT-005 (2026-04-27, resolved 2026-04-28)

- **발견 위치**: `redfish-gather/library/redfish_gather.py:103-109` ↔ `common/vars/vendor_aliases.yml`
- **분류**: convention-violation (Source-of-Truth 중복)
- **설명**: cycle-004 W2 vendor 경계 57건 분석에서 확인. `_VENDOR_ALIASES` dict (Python module)와 `vendor_aliases.yml` (Ansible) 두 곳에서 동일 매핑 정의. 신규 alias 추가 시 두 곳 동시 갱신 필요 → drift 잠재.
- **수정 (cycle-006, 옵션 (1)+(2) 조합)**:
  - (옵션 1) `_load_vendor_aliases_file()` path resolution 강화 — `SE_VENDOR_ALIASES_PATH` env / `REPO_ROOT` env / `__file__` 기반 fallback. YAML primary, dict fallback.
  - `_BUILTIN_VENDOR_MAP` → `_FALLBACK_VENDOR_MAP` 이름 변경 + 의도 주석 + 라인별 nosec rule12-r1 silence
  - (옵션 2 cycle-005 적용) `verify_harness_consistency.py` 동기화 게이트 — drift 시 advisory
- **상태**: resolved (2026-04-28 cycle-006)
- **관련**: rule 12 R1, rule 50 R2, `docs/ai/impact/2026-04-27-vendor-boundary-57.md`

## DRIFT-007 (2026-04-27, resolved 2026-04-28)

- **발견 위치**: `schema/field_dictionary.yml` 실측 ↔ cycle-003 DRIFT-001 정정값 (rule 13 / CLAUDE.md / SCHEMA_FIELDS.md)
- **분류**: catalog-stale
- **설명**: cycle-004 verifier에서 `python3 tests/validate_field_dictionary.py` 실행 결과 분포 "**Must 28 / Nice 7 / Skip 5**". cycle-003에서 정정한 "Must 29 / Nice 8" 표기와 차이. 원인: cycle-002 분석에서 `grep -cE "priority: must"` 사용 시 헤더 주석 (line 46~48 priority 설명 텍스트)이 카운트에 포함되어 +1씩 오인.
- **영향**: 운영 영향 없음 (코드 정상). 문서 정합 차이.
- **수정 (cycle-005)**:
  1. validate_field_dictionary.py + YAML 파싱 기준 실측 확정: **28 Must / 7 Nice / 5 Skip = 40 entries**
  2. CLAUDE.md / rule 13 / SCHEMA_FIELDS.md / field_dictionary.yml 헤더 / SKILL.md `update-output-schema-evidence` 일괄 정정
  3. SCHEMA_FIELDS.md 측정 명령을 grep → YAML 파싱으로 변경 (헤더 noise 제거)
  4. DRIFT-001 상태 코멘트 갱신 ("정정값 자체 잘못 — DRIFT-007에서 재정정")
- **상태**: resolved (2026-04-28 cycle-005)
- **관련**: rule 13, DRIFT-001 (cycle-003 정정 자체 stale), `tests/validate_field_dictionary.py`, cycle-002 분석 오인

## DRIFT-006 (2026-04-27, resolved 2026-04-28)

- **발견 위치**: `redfish-gather/library/redfish_gather.py:221-450, 705-706, 747` (vendor 분기 17건)
- **분류**: convention-violation
- **설명**: cycle-004 W2 vendor 경계 57건 분석에서 확인. Python module 안에 `if vendor == 'hpe':` / `oem = _safe(data, 'Oem', 'Dell', 'DellSystem')` 같은 vendor 분기 17건. rule 12 R1상 분기는 `redfish-gather/tasks/vendors/` 또는 adapter YAML capabilities에만 허용.
- **수정 (cycle-006, 옵션 (1)+(3) 조합 — 옵션 (2) 큰 리팩토링은 회귀 위험으로 회피)**:
  - (옵션 3) rule 12 R1에 **Allowed (cycle-006 추가)** 절 — redfish_gather.py의 OEM schema 추출 분기는 외부 계약 (Redfish API spec — `Oem.Hpe` / `Oem.Dell` 등 vendor namespace)에 직접 의존하므로 의도된 예외로 명시
  - (옵션 1 사전) cycle-004에서 13 adapter origin 주석 추가 시 OEM path 일부 명시 — 향후 새 vendor 추가 시 adapter origin metadata에 OEM 정보 기재
  - 17 라인 모두 `# nosec rule12-r1` 주석으로 silence (verify_vendor_boundary 도구 인식)
  - 라이브러리 vendor-agnostic 리팩토링 (옵션 2)는 영향 vendor 전부 회귀 + Round 권장이라 별도 cycle 후보로 보존
- **상태**: resolved (2026-04-28 cycle-006)
- **관련**: rule 12 R1 (Allowed 절 추가), rule 96 R1 (외부 계약), `docs/ai/impact/2026-04-27-vendor-boundary-57.md`

## DRIFT-008 (2026-04-28, resolved 2026-04-28 full-sweep)

- **발견 위치** (full-sweep, 영역 2 HIGH-2):
  - `.claude/rules/00-core-repo.md:16` — `Field Dictionary 28 Must`
  - `.claude/rules/23-communication-style.md:63` — 어휘 치환표
  - `.claude/role/output-schema/README.md:4,8,51` (3곳)
  - `.claude/ai-context/output-schema/convention.md:42,45` (2곳)
  - `.claude/ai-context/common/repo-facts.md:47`
  - `.claude/ai-context/common/coding-glossary-ko.md:16`
  - `.claude/skills/update-output-schema-evidence/SKILL.md:39`
  - `docs/ai/catalogs/PROJECT_MAP.md:34`
  - `docs/ai/catalogs/SCHEMA_FIELDS.md:23-29,38`
- **분류**: catalog-stale (cycle-006 schema users[] 6 항목 추가 후 미반영)
- **설명**: cycle-006 (2026-04-28)에서 schema users[] 섹션 6 항목 추가 + field_dictionary "31 Must / 9 Nice / 6 Skip = 46 entries" 갱신. CLAUDE.md / rule 13 본문은 갱신됐으나 위 11곳 (rule / role / ai-context / skill / catalog) 미반영. cycle-006 직후 full-sweep에서 발견.
- **수정 (full-sweep, Tier 1)**: 11곳 모두 `31 Must / 9 Nice / 6 Skip = 46 entries`로 일괄 정정
- **상태**: resolved (2026-04-28 full-sweep)
- **관련**: rule 13 R1 (3종 동반 갱신), rule 70 (catalog 갱신 trigger), full-sweep 보고서

## DRIFT-009 (2026-04-28, resolved 2026-04-28 full-sweep)

- **발견 위치**: `.claude/rules/23-communication-style.md:87,90,137` (`5체크`) ↔ `.claude/rules/24-completion-gate.md:3,53,70,85,90` + `CLAUDE.md:455` (`6 체크`)
- **분류**: convention-violation (rule 본문 모순)
- **설명**: rule 23 R4 본문이 "5체크"로 명시됐으나 정본 (rule 24 + CLAUDE.md)은 "6 체크". 사용자가 rule 23 따르면 한 항목 누락 위험.
- **수정 (full-sweep, Tier 2-A1)**: rule 23 R4 → "6체크"로 정정 (rule 24 = 정본)
- **상태**: resolved (2026-04-28 full-sweep)
- **관련**: rule 24 (정본), CLAUDE.md Step 7

## DRIFT-010 (2026-04-28, resolved 2026-04-28 full-sweep)

- **발견 위치** (full-sweep 영역 6 HIGH-1):
  - `common/tasks/normalize/init_fragments.yml:42-46`
  - `common/tasks/normalize/build_empty_data.yml:24-28`
  - `common/tasks/normalize/build_failed_output.yml:79-80`
- **분류**: convention-violation (rule 13 R5 envelope 정합 위반)
- **설명**: storage 섹션 빈값 정의 3 빌더에 `logical_volumes: []` 누락. `schema/sections.yml:51-56`은 `storage.empty_value` 명시. field_dictionary는 `storage.logical_volumes[]` 8 Must 필드 정의. 현재 baseline은 gather 코드가 채워주고 있어 우연히 통과 중. precheck 실패 또는 Redfish 외 채널이면 호출자 파싱 NG 가능.
- **수정 (full-sweep, Tier 2-D1)**: 3 빌더에 `logical_volumes: []` 추가
- **상태**: resolved (2026-04-28 full-sweep)
- **관련**: rule 13 R5, rule 22 R1 (3 파일 동기화 의무)

## DRIFT-011 (2026-04-29, open)

- **발견 위치**:
  - `inventory/lab/redfish.json:6-8` — 사용자 라벨 `_vendor: cisco` (BMC 10.100.15.1, 15.2, 15.3)
  - `tests/evidence/cycle-015/connectivity-2026-04-29.md` 5절
- **분류**: external-contract-drift (rule 96 R1)
- **설명**: cycle-015 첫 lab 권한 직후 연결성 검증에서 `GET /redfish/v1/` 무인증 응답 (rule 27 R3 1단계) 결과 사용자 라벨 vs Redfish Manufacturer 불일치 1건 발견:
  1. **10.100.15.2** (사용자: "cisco") → `Product='TA-UNODE-G1', RedfishVersion=1.2.0` — 표준 Cisco UCS Product 아님 (UCS C-series는 보통 `Product='UCS C220 M5'` 형식). TA-UNODE는 Tetration / TelePresence / 3rd party 가능성.
- **영향**: 본 실장비 회귀 진입 전 식별 필요. 현재는 이론상의 vendor 라벨 vs 실 Manufacturer drift라 baseline 갱신 시 잘못된 vendor adapter 적용 위험.
- **제안**:
  1. 호스트 물리 라벨 확인 (사용자 lab 직접 확인)
  2. `deep_probe_redfish.py`로 Manufacturer / Model / Oem namespace 상세 추출
  3. `inventory/lab/redfish.json` `_vendor` 라벨 정정
  4. `EXTERNAL_CONTRACTS.md`에 AMI Redfish 1.11.0 / TA-UNODE-G1 entry 추가
- **상태**: **resolved (cycle-015 사용자 명시 결정)** — 두 호스트 모두 사내 lab 부재 확인. `inventory/lab/redfish.json` + `vault/.lab-credentials.yml`에서 제거. OPS-12 / OPS-13 closed.
- **관련**: rule 96 R1 (외부 계약 origin 주석), rule 27 R3 (Vault 2단계 — 1단계가 본 drift 검출), rule 50 R1 (vendor 정규화 정본 vendor_aliases.yml), `tests/evidence/cycle-015/connectivity-2026-04-29.md`


## DRIFT-012 (2026-05-01, resolved cycle-017)

- **발견 위치**: `.claude/skills/cross-review-workflow.md` (단일 .md 파일 형식)
- **분류**: skill 디렉터리 형식 일관성
- **설명**: cycle 2026-05-01 중반 (commit `a1a3bf6b`) cross-review-workflow skill 을 단일 `.md` 파일로 추가. 기존 47 skill 은 모두 `<name>/SKILL.md` 디렉터리 형식. `verify_harness_consistency.py` 검증기는 디렉터리만 카운트해서 단일 파일은 누락. 일관성 깨짐.
- **resolved (cycle-017)**:
  - `.claude/skills/cross-review-workflow.md` → `.claude/skills/cross-review-workflow/SKILL.md` 디렉터리 변환
  - frontmatter (name + description) 추가
  - `verify_harness_consistency.py` 통과 (rules 28 / skills 48 / agents 59 / policies 10)
- **관련**: rule 70 R5, `verify_harness_consistency.py:138-156` (SKILL.md frontmatter name ↔ 폴더명 일치 검사)

## DRIFT-013 (2026-05-01, resolved cycle-017)

- **발견 위치**: cycle 2026-04-30 Lenovo XCC 1.17.0 reverse regression
- **분류**: 사용자 실측 vs spec drift
- **설명**: cycle 2026-04-30 첫 fix (`Accept` + `OData-Version` + `User-Agent` 추가) 가 lab 검증 OK 였으나 사이트 BMC 펌웨어 1.17.0 reject. "표준 권장 = 모든 BMC 호환" 가정 실패. 사용자 명시 hotfix ("Accept만") 적용 후 정상화.
- **resolved (cycle-017)**:
  - rule 25 R7-A-1 신설 — "사용자 실측 > spec" 본문 화
  - capture-site-fixture skill 신설 — 사이트 사고 fixture sanitize + commit
  - lab-tracker agent (opus) — lab 보유/부재 추적
  - web-evidence-collector agent (opus) + web-evidence-fetch skill — lab 부재 영역 web sources 의무 (rule 96 R1-A)
- **관련**: rule 25 R7-A-1, rule 96 R1-A, ADR-2026-05-01-harness-reinforcement

## DRIFT-014 (2026-05-11, resolved cycle hpe-ilo7-gen12-match-fix)

- **발견 위치**: `adapters/redfish/hpe_ilo7.yml` L36 ↔ 일부 Gen12 BMC firmware 보고 형식
- **분류**: external-contract-drift (rule 96 R1)
- **설명**: 직전 cycle `hpe-csus-add` mock 검증 부수 발견 — iLO 7 adapter 의 `firmware_patterns = ["iLO.*7", "^\\d+\\.\\d+\\.\\d+"]` 가 3-part version (예 "1.16.00") 만 가정. 일부 Gen12 BMC 는 facts.firmware 추출 path (Manager.FirmwareVersion 만) 에 따라 2-part short version "1.10" 만 보고 → `firmware_patterns` 매치 실패 → -9999 disqualify (`module_utils/adapter_common.py` L260-267) → iLO 7 (priority=120) 대신 iLO 4 (priority=50) 가 잘못 선택. mock S1 시나리오 재현 확인.
- **영향**:
  - Gen12 BMC 응답 path drift 시 SmartStorage legacy (iLO 4 strategy) + Oem.Hp namespace 시도 → Gen12 Oem.Hpe.* 정보 수집 실패
  - 사이트 실 BMC firmware 형식 미확정 (lab 부재 — web sources `1.16.00` / `1.12.00` 3-part 가정만 알려짐)
- **resolved (cycle hpe-ilo7-gen12-match-fix)**:
  - `hpe_ilo7.yml` firmware_patterns 확장 (Additive only, rule 92 R2): `["iLO.*7", "^\\d+\\.\\d+\\.\\d+", "^1\\.1[0-9]"]`
  - `^1\.1[0-9]` (1.10~1.19) 명시 — iLO 4 `^1\.[0-9]` / iLO 6 `^1\.[5-9]` 한자리 minor 와 충돌 0
  - mock 5 시나리오 회귀 (S1=iLO7 / S2=iLO7 / S3=iLO6 / S4=CSUS3200 / S5=SDFlex) 모두 PASS
  - `scripts/ai/verify_hpe_ilo7_fix.py` 신규 — 본 회귀 재현 도구
- **후속 (NEXT_ACTIONS, lab 도입 후)**:
  - 사이트 BMC facts.firmware 실측 형식 확정 → 1.20+ 2-part 변형 발견 시 firmware_patterns 추가 정정
  - reverse regression 검토 (rule 25 R7-A-1 — 사용자 실측 > spec)
- **관련**: rule 92 R2 (Additive only), rule 96 R1 (origin 주석), rule 25 R7-A-1, `module_utils/adapter_common.py` L260-267

## DRIFT-015 (2026-05-11, resolved cycle adapter-selection-review)

- **발견 위치**: `adapters/redfish/supermicro_x12.yml` L27 `priority: 90`
- **분류**: adapter priority 일관성 (rule 12 R2 / rule 50 R3)
- **설명**: 사용자 검증 요청 ("어떤 adapter 를 쓸지 결정하는 단계 문제 발생 이력 — 지금 잘 돼있나") rule 95 R1 자동 스캔 부수 발견. Supermicro generation 별 priority 가 `X11=100`, **`X12=90`**, `X13=100`, `X14=110` 으로 X12 만 역전. 동일 vendor (Supermicro) 내 model_patterns 분리로 동시 매칭 시나리오 없어 사고 0 이지만, lab 도입 후 facts empty 케이스 (T-01 시뮬레이션 — `model_patterns` 보너스 +25 skip) 시 X11(100) / X13(100) > X12(90) → X12 사이트가 X11 또는 X13 adapter 로 잘못 매칭 위험.
- **영향**:
  - 현재: 사고 0 (Supermicro lab 부재 + 사이트 model 정확 매칭 시 영향 없음)
  - 잠재: facts empty + model 추출 실패 시 priority tie-break 으로 잘못된 generation 선택
- **resolved (cycle adapter-selection-review)**:
  - `adapters/redfish/supermicro_x12.yml` L27 `priority: 90 → 100` (Additive only — model_patterns 매칭 정확 시 결과 동일)
  - origin 주석 갱신 — Last sync 2026-05-11 + DRIFT-015 사유 + Phase 2 (firmware_patterns) 보류 결정 명시
  - `tests/unit/test_supermicro_adapter_selection.py` 신규 (12 시나리오 회귀)
  - `test_drift_015_x12_priority_consistency` — 회귀 차단 (X11=X12=X13=100 / X14=110 / generic=10)
- **Phase 2 (firmware_patterns 추가) 보류 결정**:
  - 근거 1: `module_utils/adapter_common.py` L258-267 점검 결과 — firmware empty 시 disqualify 안 됨 (안전), 단 firmware 가 web sources 가설과 미스매치 시 -9999 (graceful fallback `supermicro_bmc` priority 10)
  - 근거 2: AST2500 (X11) vs AST2600 (X12+) firmware 형식 거의 동일 (`X.YY.ZZ` 또는 `0X.YY.ZZ`) — web sources 만으로 generation 분리 정확도 약함
  - 근거 3: lab 부재 (rule 96 R1-A) — 사이트 실 firmware 캡처 후 패턴 보정 의무
  - → NEXT_ACTIONS 등재 (capture-site-fixture skill + Supermicro lab 도입 cycle)
- **후속 (NEXT_ACTIONS, lab 도입 후)**:
  - 사이트 BMC fixture 캡처 → firmware_patterns 실측 검증 (rule 96 R1-C 항목 1)
  - baseline JSON 추가 (4 generation × 1 vendor) — rule 13 R4
  - DRIFT-015 close trigger: 사이트 검증 후 firmware_patterns 일치 confirm
- **관련**: rule 12 R2, rule 50 R3, rule 95 R1 #4 (adapter score 동률), rule 96 R1-A / R1-C, `module_utils/adapter_common.py:272-287`, `lookup_plugins/adapter_loader.py:232-237`
