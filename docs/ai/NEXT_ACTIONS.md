# server-exporter 다음 작업 (NEXT_ACTIONS)

## reachable ICMP OR 판정 후속 (2026-09-03)

> 정본: `docs/ai/decisions/ADR-2026-09-03-icmp-or-reachability.md`, rule 27 R1,
> `tests/unit/test_precheck_icmp_reachability.py`

| # | 항목 | 상태 | 내용 |
|---|---|---|---|
| RE-1 | **Jenkins Agent 의 `ping` 가용성 확인** | `[TODO / 실장비]` | controller(에이전트)에서 비특권 계정으로 `ping -c 1 -n -W 1 -w 1 <ip>` 가 rc=0 을 내는지 1회. 없거나 권한이 없으면 ICMP 근거를 못 얻어 판정이 종전(TCP 전용)과 같아진다 — 그 사실은 `errors[].detail` 의 `icmp:` 항목에 남는다. 실패 시 대안은 `SOCK_DGRAM+IPPROTO_ICMP` 2-tier 구현 (ADR 대안 F) |
| RE-2 | 방화벽 DROP 구간 실측 | `[TODO / 실장비]` | 관리 포트 TCP 가 DROP 되고 ICMP 는 열린 대상에서 `reachable=true` / `stage=port` / `TCP_CONNECT_FAILED` / 2번 문장이 나오는지 확인. 이번 변경의 목적 그 자체라 실장비 확인 전에는 "동작 확인" 이라고 말할 수 없다 |
| RE-3 | dead host 배치 wall-clock | `[TODO / 실장비]` | 무응답 대상 N대 실행에서 증가폭이 예상(+1초/대) 범위인지. 초과하면 `_precheck_timeout_icmp` 를 낮추거나 `_precheck_icmp_probe: false` 로 끈다 |
| RE-4 | **Portal 소비자 이행 안내** | `[TODO / 사용자]` | `failure_code == "TCP_CONNECT_FAILED"` 로 "대상 무응답" 을 분기하던 코드가 Portal 에 있으면 `TARGET_UNREACHABLE` 을 받도록 갱신해야 한다. 사용자 문장(`failure_reason` / `errors[].message`)은 불변이라 표시 전용 화면은 영향 없다 |

## OS / ESXi 게더링 전수 검수 후속 (2026-09-03)

> 정본: `docs/reference/decision-log.md` 2026-09-03, `tests/unit/test_gather_identity_render.py`

| # | 항목 | 상태 | 내용 |
|---|---|---|---|
| GA-1 | 실장비 재수집 + 참조 캡처 대조 | `[DONE 2026-09-03]` | Jenkins #190~#199: RHEL 8.10 raw(.161) / RHEL 9.6(.165, .145) / Ubuntu 24.04 VM(.156) / R760 베어메탈 Ubuntu(.96) / Windows 2022(.120) / ESXi 7.0.3(.1, .2) 전부 success, 이슈 0. 증거 `tests/evidence/2026-09-03-os-esxi-live-verification.md`. **미수집**: RHEL 9.2(.163 무응답), Windows .135(자격 미검증), ESXi 9.0 R760 ×5(자격 미제공). lab 에 RHEL 10 / Rocky 없음 |
| GA-2 | **baseline 갱신 여부** | `[DECISION / 사용자]` | **충돌**: `schema/baseline_v1/README.md` 는 "본 폴더 파일은 절대 in-place 로 덮어쓰지 않는다 — 새 응답은 `baseline_v2/` 로" (폴더 = 버전 스냅샷), rule 13 R4 / 21 R1 은 "실장비 검증 후 `baseline_v1/{vendor}_baseline.json` 에 저장(update-vendor-baseline)" (파일 = 살아있는 회귀 기준). git log 상 `esxi_baseline.json` 이 이미 in-place 갱신된 이력(`8aa06f18`, `82926268`)이 있어 README 원칙은 실제로 지켜지지 않았다. **제안**: rule 13 R4 를 정본으로 (CLAUDE.md §2 우선순위 — Contract/Regression > rule > README). README 는 "수동 편집 금지, 실장비 envelope 로만 교체 + evidence + decision-log, `baseline_v2/` 는 schema_version 이 바뀔 때만" 으로 문구 정정. **대응표 (최신 코드 `549f84ff` 기준 envelope)**: `rhel810_raw_fallback_baseline.json` ← `2026-09-03-live/build196_rhel810_raw_10.100.64.161.json`(.161, d38bc31b — 이후 커밋은 VM 값 불변) · `windows_2022_baseline.json` ← `build192_win2022_10.100.64.120.json`(.120, 0076ca67 — Windows 는 이후 변경 없음) · `esxi_baseline.json` ← `build195_esxi02_10.100.64.2.json`(.2, 0076ca67 — ESXi 는 이후 변경 없음) · `ubuntu_baseline.json` ← `build199_ubuntu2404_vm_10.100.64.156.json`(.156 `cicd-gitlab`, 549f84ff; 종전 baseline 호스트 `gathertest-ubuntu2404` 는 lab 에 없음). `windows_baseline.json`(Windows 10 `DESKTOP-99237QP`, 2026-04-01) 은 대상 장비 부재 — 삭제 또는 유지 결정 필요. AI 는 승인 전 baseline 을 건드리지 않았다 |
| GA-3 | ESXi `host_info` 파트 실장비 확인 | `[DONE 2026-09-03]` | esxi01/02 실측: gateway 10.100.64.254 + gatewayDevice→is_primary, pnic 제조사/모델, cpuInfo.hz 2195, uptime, dnsConfig.hostName 전부 값 확인 (#193/#195) |
| GA-4 | Windows 시리얼 디코딩 조건 실측 | `[PARTIAL]` | #192: NAA 32-hex 시리얼(`6000c295…`) 이 변조 없이 보존됨을 확인. hex 인코딩 ASCII 시리얼을 내는 실제 드라이브 케이스는 lab 에 없어 미확인 |
| GA-5 | Windows `Get-NetAdapterHardwareInfo` / `Get-PnpDevice` 권한 | `[DONE / 관리자 계정]` | #192: adapters[] 6개(PCI 주소·제조사·드라이버 버전) 수집. 비관리자 계정 케이스는 lab 계정이 관리자라 미확인 |
| GA-6 | Redfish 채널 동일 검수 | `[TODO]` | 이번 범위는 OS/ESXi. Redfish `system.hostname/fqdn` 소스, `cpu.max_speed_mhz`(MaxSpeedMHz 의미), UUID 바이트 순서(uuid_equal 로 대조 가능) 를 같은 기준으로 본다 |
| GA-7 | pre-commit placeholder 가드 승격 | `[TODO / 하네스]` | `scripts/ai/hooks/pre_commit_placeholder_fallback_check.py` 는 advisory. 사이클 1회 무위반 확인 후 blocking 검토 |
| GA-8 | lab 대상 목록 정정 | `[TODO / 운영자]` | `vault/.lab-credentials.yml`(gitignore) 의 `os_targets_linux` .167("ubuntu2404") / .169("rocky960") 는 실측상 .165 / .161 RHEL VM 의 bond1 IP 다. 실제 Ubuntu 24.04 / Rocky 9.6 호스트 IP 를 다시 받아야 GA-2 의 `ubuntu_baseline` 갱신이 가능 |

## OS 채널 CSUS 3200 시리얼 정규화 후속 (2026-08-27)

> 정본: `filter_plugins/serial_normalizer.py`, `tests/unit/test_csus_partition_serial.py`

| # | 항목 | 상태 | 내용 |
|---|---|---|---|
| CSUS-OS-1 | **CSUS 3200 의 OS 측 DMI 표기 실측** | `[PENDING / lab 부재]` | `cat /sys/class/dmi/id/{sys_vendor,product_name,product_serial}` 1회. 현재 model 패턴은 Redfish 미러 캡처 표기(`Compute Scale-up Server 3200…`)를 그대로 쓴다. DMI 표기가 다르면 `CSUS3200_MODEL_PATTERNS` 를 Additive 로 확장해야 정규화가 실제로 동작한다 (미매치 시 동작은 무해한 no-op) |
| CSUS-OS-2 | 파티션 번호 3자리 가정 확인 | `[PENDING / lab 부재]` | 접미사 패턴을 `-[0-9]{3}` 로 고정했다 (실측 `-000`). 4자리 이상을 쓰는 펌웨어가 확인되면 패턴 확장 필요 |
| CSUS-OS-3 | OS ↔ Redfish 시리얼 표기 차이 | `[INFO / 의도됨]` | 같은 장비를 OS 로 보면 `SGHD3TLNDD`, Redfish 로 보면 `SGHD3TLNDD-000`. 이번 요구 범위가 OS 채널이라 의도된 차이다. 호출자가 채널 간 매칭을 하게 되면 정책 재확인 필요 |

## Location ID `ich` → `ic` 개명 후속 (2026-08-14)

> 정본: `common/vars/locations.yml`, `vault/ic/`

| # | 항목 | 상태 | 내용 |
|---|---|---|---|
| LOC-1 | **Jenkins Agent 노드 label 재설정** | `[CRIT / 운영자]` | 저장소는 `id: ic` / `agent_label: ic` 로 바뀌었다. Jenkins 노드(10.100.64.154 / .155)의 Labels 에서 `ich` → `ic` 로 바꾸기 전까지 `loc=ic` 잡은 **Agent 를 못 잡고 무한 대기**한다. 저장소 밖 작업이라 AI 가 수행 불가 |
| LOC-2 | `loc=ich` 호출자 갱신 | `[CRIT / 운영자]` | Portal 등 호출자가 `loc: "ich"` 를 보내면 `Resolve Location` stage 가 즉시 실패한다 (registry 미등록). 호출자 측 값 교체 필요 |
| LOC-3 | `ic` Location 실장비 재검증 | `[PENDING]` | Vault 경로만 `vault/ich/` → `vault/ic/` 로 옮겼고 내용은 그대로다. 실행 검증은 LOC-1 완료 후 |

## 계정 쓰기 계약 정합 후속 (2026-08-13)

> 정본: `tests/evidence/2026-08-13-account-write-contract-alignment.md`
> ADR: `docs/ai/decisions/ADR-2026-08-13-account-write-contract-alignment.md`

### 조건 미발생 — 실장비가 있어도 지금은 못 한다

| # | 항목 | 상태 | 왜 |
|---|---|---|---|
| AWC-1 | Account **CREATE** 실장비 증명 | `[PENDING / 조건 부재]` | git 4대 모두 표준 계정이 이미 존재해 `presence=absent` 가 발생하지 않는다. 조건을 만들려면 운영 계정을 삭제해야 하므로 하지 않는다 |
| AWC-2 | Account **REPAIR** 재현 (계약 정비 후) | `[PENDING / 조건 부재]` | 표준 인증이 4대 모두 성공해 reconcile 게이트가 열리지 않는다. 비밀번호를 일부러 어긋나게 만들지 않는다 |

### 조사 필요 (구현 대상 아님)

| # | 대상 | 얻는 것 | 우선순위 |
|---|---|---|---|
| AWC-3 | Fujitsu `iRMC RESTful API Specification pack` (2026-01-13, 13.15MB) 원문 | S4/S5/S6 AccountService·ManagerAccount Method Table. 확보 전까지 Family 추가 없음 | HIGH |
| AWC-4 | Supermicro `POST /AccountService` 가 어느 Firmware 부터 유효한가 | `create_uri` 를 `account_service_root` 로 전환할 근거. 현재는 장비값으로 Generation+Firmware 를 확정했을 때만 전환 | HIGH |
| AWC-5 | Huawei Redfish Login Interface 를 켜는 OEM field/action | 자동 복구 payload. **확보 전 구현 금지** — 현재는 관측·진단만 | MED |
| AWC-6 | Cisco IMC allowable Account Id 범위 공식 근거 | `id_range` 확정. 현재 `(2,16)` half-open = 2..15 는 자체 정합이므로 **근거 없이 바꾸지 않는다** | MED |
| AWC-7 | 실장비 부재 5 Vendor 실미러 (Supermicro / Huawei / Inspur / Fujitsu / Quanta) | UNVERIFIED 를 lab 없이 낮출 유일한 수단 | MED |

### 알려진 제약

| # | 항목 | 내용 |
|---|---|---|
| AWC-8 | `scripts/ai/verify_no_plaintext_secret.py` Windows 콘솔 오류 | 기본 cp949 콘솔에서 출력 인코딩 때문에 `UnicodeEncodeError` → exit 1. 검출 결과는 정상(`PYTHONUTF8=1` 로 exit 0). 하네스 스크립트 문제이며 계정 작업 범위 밖이라 손대지 않았다 |
| AWC-9 | Adapter 세대 오선택 (기존 PWC-4) | Dell 10.100.15.34 는 iDRAC9 인데 adapter 는 `redfish_dell_idrac10` 을 고른다. **계정 경로는 Firmware major 로 판정하므로 영향받지 않지만** adapter_id 자체는 여전히 틀린다 |
| AWC-10 | `redfish_gather.py` 분량 | 6,900줄 초과. rule 10 R3 관점에서 계정 영역 분리가 맞지만 Jenkins agent import 경로가 미검증이라 별도 작업으로 남긴다 |


> **본 파일**: 진정 active PENDING 만 유지 (rule 70 R5 / R6 / R7 cycle 자문 정책).
> **lab 매트릭스**: `docs/ai/catalogs/LAB_PENDING_MATRIX.md` (8 vendor × generation × 4 column).
> **archive**: 아카이브(정리됨) (OPS-* + cycle-013/014/015/016 잔여).
> **마지막 정리**: 2026-05-29 (audit-cleanup cycle).

---

## 표준 비밀번호 회전 수렴 cycle 후속 (2026-08-12, 2차)

> 정본: `tests/evidence/2026-08-12-standard-password-convergence.md`,
> `tests/evidence/2026-08-12-plaintext-secret-sanitization.md`

| # | 항목 | 상태 | 내용 |
|---|---|---|---|
| PWC-1 | **현재 유효 자격 6종 rotation** | [CRIT / 운영 결정] | 평문은 tracked content 에서 제거했지만 **git history 와 commit 메시지(약 13개)에는 남아 있다.** 따라서 아래는 여전히 노출된 것으로 취급해야 한다: vault master(`428829ae`, git OS/ESXi/Dell recovery 겸용 — **최우선**), chj·ic·yi HPE/Lenovo recovery(`9892c533`), git HPE/Lenovo recovery(`2b3b6862`), 전 Location Cisco recovery(`9477272a`), ic·yi Dell recovery(`f28b309b`), chj·ic·yi OS(`f3e3f831`). 영향 범위는 evidence §6.2 참조. **사용자 지시 §12 로 이번 cycle 에서 rotation 하지 않았다** |
| PWC-2 | Git history purge | [HOLD / 운영 결정] | 사용자 지시 §13 이 자동 재작성을 금지했다. PWC-1 rotation 이 선행되면 history purge 없이도 위험이 크게 줄어든다. purge 를 택하면 두 remote(github/gitlab) 협업자 전원 재클론이 필요하다 |
| PWC-3 | untracked 로컬 잔여물 | [LOW / 운영자] | `.vault_pass`, `vault/.lab-credentials.yml`, `tests/reference/local/*`, `__pycache__/*.pyc` 에 값이 남아 있다. `.gitignore` 대상이라 저장소에는 없지만 작업 머신 로컬에는 있다 |
| PWC-4 | **Adapter 세대 오선택 (근본 원인)** | [MED] | Adapter 선택이 **무인증 probe** 단계라 `model`/`firmware` fact 가 비어 priority 로만 결정된다. Family 판정은 Firmware 기준으로 교정했지만 `adapter_id` 자체는 여전히 틀린다(수집 tasks 는 동일해 수집 데이터 영향 없음). 근본 해결은 **인증 후 adapter 재선택**이며 collect/normalize/vendor 표시값에 모두 영향을 주는 별도 변경이다. GIT-4 와 동일 항목 |
| PWC-5 | HPE Repair 완주 재현 | [PENDING / 조건 부재] | iLO 쓰기 결함(비밀번호 단독 PATCH)은 실장비 통제 실험으로 확정하고 고쳤으나, **수정 후 제품 경로의 Repair 완주**는 재현하지 않았다. 계정을 다시 불일치로 만들어야 하는데 조건을 인위적으로 만들지 않았다. 다음 표준 비밀번호 회전 때 자연히 검증된다 |
| PWC-6 | `hpe_ilo4` 쓰기 계약 미확인 | [LOW] | iLO5+ 는 `Password` 단독 PATCH 가 필수임을 실측했다. iLO4 는 lab 부재라 종전 동작을 유지했다(근거 없는 vendor 예외 금지). iLO4 장비 확보 시 동일 실험 필요 |
| PWC-7 | Lenovo hint 우선순위 | [LOW] | Cisco 는 capability > hint 가 지켜지지만 Lenovo 분기는 `'xcc3' in hint` 를 capability 보다 먼저 본다. 현재 사고는 없으나 Cisco 와 계약이 다르다. 정합 여부 검토 필요 |

---

## git Location 실장비 검증 후속 (2026-08-12)

> 정본: `tests/evidence/2026-08-12-git-location-live-verification.md`
>
> **2026-08-12 (2차) 갱신**: GIT-1(Dell HOLD) / GIT-6(HPE 2차 Write 0) / GIT-8(평문 노출)
> 은 아래 표 이후 상태가 바뀌었다. 위 "표준 비밀번호 회전 수렴 cycle 후속" 절이 최신이다.

| # | 항목 | 상태 | 내용 |
|---|---|---|---|
| GIT-1 | **Dell 표준 비밀번호 강도 점수 미달** | [CLOSED 2026-08-12] | `Security.1.MinimumPasswordScore="Weak Protection"` 하나만 남은 강제 조건이고 길이·문자종류·정규식은 전부 비활성이다. 비밀번호를 강도 높은 값으로 바꾸거나 해당 정책을 낮추는 **운영 결정**이 필요했다. **2026-08-12 회전된 표준 비밀번호로 1·2차 실행 모두 표준 인증 성공 + Write 0 → HOLD 해소.** BMC 정책은 건드리지 않았다. 다만 "Dell 은 선언된 규칙(길이/문자군/Regex)만으로 수용 여부를 판단할 수 없다" 는 사실은 유효하므로 향후 값 선정 시 유의 |
| GIT-2 | **Account Create 경로 실장비 미검증** | [PENDING / 조건 부재] | git 4대 모두 표준 계정이 이미 존재해 `presence=absent` 가 발생하지 않았다. 계정을 지워 조건을 만들지 않았다. 표준 계정이 없는 신규 장비 투입 시 검증 |
| GIT-3 | Inspur live 확인 | [LIVE TEST NOT AVAILABLE] | git 에 Inspur 장비 없음 + git Inspur Recovery Credential 미제공. 기존 vault 항목은 factory default placeholder. 다른 Location Credential 대체 사용 금지 |
| GIT-4 | adapter 세대 오선택 2건 | [MED] | 10.100.15.34 는 iDRAC9(FW 7.10.70.00)인데 `redfish_dell_idrac10` 선택. 10.100.15.2 는 CIMC 4.1(2g)인데 `redfish_cisco_ucs_xseries` 선택. 계정 경로는 Capability 우선 판정으로 방어되지만 adapter 선택 자체는 별도 과제 |
| GIT-5 | Dell 반복 Write 억제 | [MED] | 표준 인증이 계속 401 이면 매 실행마다 같은 PATCH 가 나간다(audit M-6, run 간 기억 없음). GIT-1 해소 전까지 Dell 대상은 dry-run 권장 |
| GIT-6 | HPE 2차 실행 Write 0 미확인 | [CLOSED 2026-08-12] | **2026-08-12 4대 전부 1·2차 Write 0 확인.** 그 과정에서 iLO 쓰기 결함(비밀번호를 다른 속성과 묶으면 조용히 버림)이 드러나 수정했다 — evidence 2026-08-12-standard-password-convergence.md §3 |
| GIT-7 | chj / ic / yi 실장비 미검증 | [PENDING] | 이번 cycle 은 사용자 지시로 **git 만** 실장비 검증했다. 나머지 3 Location 은 Vault 값만 반영 |

### GIT-8 [부분 CLOSED 2026-08-12] 저장소 평문 자격 — tracked content 정리 완료, history 잔존

2026-08-12 Vault 정리 후 tracked 파일 전수 스캔 결과. **이번 cycle 이 만든 것이 아니다**
(이번에 추가한 185 라인 중 평문 0건, 신규 문서 2종도 0건). 기존 문서·증거·캡처에 남아 있던 것이다.

| 자격 | 노출 파일 수 | 주 위치 |
|---|---:|---|
| vault 마스터 암호 (= Redis fact_caching 암호와 동일) | **373** | `tests/reference/agent/**` 289 (Jenkins agent `ansible.cfg` 덤프의 `fact_caching_connection = <host>:6379:0:<pw>`), `tests/evidence/**` 61, `docs/ai/**` 12 |
| ic·chj HPE/Lenovo 복구 | 17 | docs / evidence |
| git Lenovo·HPE 복구 | 14 | docs / evidence / ticket |
| git Cisco 복구 | 8 | LAB_INVENTORY 포함 |
| ic·yi Dell 복구 | 7 | docs / evidence |
| 전역 표준 계정 | 3 | LAB_PENDING_MATRIX 등 |
| chj·ic·yi OS | 2 | docs |

- 위 값들은 **이번에 배포한 자격과 동일**하다. 즉 저장소 읽기 권한 = 전 lab 자격 획득이다.
- 기존 `[CRIT]` 항목(본 파일 아래쪽, `docs/ai/policy/SECRET-ROTATION-RUNBOOK.md`)과 같은
  문제이며 이번 실측으로 **범위가 정량화**됐다.
- **2026-08-12 갱신: tracked content 는 전량 제거했다** (17,982 파일 전수 digest+literal 검사 0건). Secret Leak Gate `scripts/ai/verify_no_plaintext_secret.py` + `tests/secret_guard.py` 로 재발을 막는다. **남은 것은 git history 와 commit 메시지, 그리고 rotation** → 위 PWC-1 / PWC-2.
- (종전 기록) 직전 cycle 시점에는 제거하지 않았다. CLAUDE.md §12 — 사용자 요청 없이 Secret Rotation /
  Vault Rekey / Git History Cleanup 으로 범위를 확대하지 않는다. 또한 working tree 만
  지우는 것은 git 히스토리가 남아 실효가 없다.
- **결정 필요 (사용자)**: (a) 자격 회전 후 (b) 문서/캡처 평문 제거 (c) 히스토리 purge.
  특히 `tests/reference/agent/**` 의 agent `ansible.cfg` 덤프는 캡처 단계에서 마스킹해야 한다.

---

## Redfish 계정 Reconcile 후속 (2026-08-12) — Family Strategy 도입 이후

> 정본: `tests/evidence/2026-08-13-account-write-contract-alignment.md`
> 매트릭스: Vendor × Family 매트릭스
> 계획: `docs/ai/contracts/redfish-account-write.md`
>
> **[정정 2026-08-13]** 종전 이 자리의 "현재 어떤 BMC Family 도 `PROVEN` 이 아니다" 는
> stale 이었다. Case A(표준 인증 성공 → Write 0 → 표준 계정 수집)는 git 4대에서
> 반복 증명됐고 Case B(Repair 완주)는 Lenovo XCC 1건이 있다.
> **여전히 미증명인 것은 Account CREATE 다** — 어느 Family 도 실장비 Create 근거가 없다.
> 4대 모두 표준 계정이 이미 존재해 `presence=absent` 조건 자체가 발생하지 않으며,
> 조건을 만들려면 운영 계정을 지워야 하므로 하지 않는다.

### 운영 결정 필요 (사람 몫 — 코드로 풀 수 없다)

| # | 항목 | 상태 | 왜 지금 |
|---|---|---|---|
| ACC-D1 | **Dell 표준 비밀번호 vs iDRAC Security Strengthen Policy** (기존 E-6) | [HOLD] | 해소 전까지 Dell 은 표준 계정으로 수집할 수 없다. 비밀번호 값을 올릴지 장비 정책을 조정할지의 운영 결정. 코드는 원인을 정확히 진단한다 |
| ACC-D2 | **Global Standard Password 정책 교집합** | [HOLD] | Cisco Strong(max 14) 과 Inspur MinPasswordLength(최대 16) 를 동시에 만족하는 비밀번호가 **존재하지 않을 수 있다**. 매트릭스 4절 A/B/C/D 중 선택 필요 |
| ACC-D3 | `_rf_account_service_dryrun` 항구 정책 | [PENDING] | `Jenkinsfile_portal:219` 에 override 가 없고 `d3e79167` 은 어느 브랜치에도 없다(dangling). **게이트가 열리면 운영에서 실제 계정 Write 가 나간다.** 2026-08-12 사용자 결정으로 현행 유지 중 |
| ACC-D4 | audit H-5 (`empty_accounts` -> `GATHER_FAILED`) 수정 여부 | [PENDING] | 고치면 Portal 사용자 문장이 5번 -> 4번으로 바뀐다. Consumer 영향 결정 필요라 이번에 손대지 않았다 |

### 실장비 검증 (lab / 사이트 필요)

| # | 항목 | 우선순위 | 절차 |
|---|---|---|---|
| ACC-L1 | 통제된 1대 read-only Capability Probe -> dry-run -> Write -> 2차 실행 Write 0 | [HIGH] | evidence 문서 5절에 명령과 확인 필드까지 정리했다 |
| ACC-L2 | Dell iDRAC7/8 read-only 미러 캡처 | [HIGH] | Manager-scoped AccountService 실증 (현재 미러는 iDRAC9/10 만) |
| ACC-L3 | Lenovo Purley 미러 캡처 | [HIGH] | pre-populated 빈 slot 판정 실증. 현재 XCC 미러는 1호스트뿐 |
| ACC-L4 | Cisco 최신 BMC 미러 캡처 | [HIGH] | RoleId `Administrator` + Id semantics 실증 (현재 미러는 CIMC 만) |
| ACC-L5 | Supermicro X13/X14 미러 (계정 분리 전/후 Firmware 각 1) | [MED] | 분리 경계 실증 + 최신 `/AccountService` POST 도입 판단 |
| ACC-L6 | Inspur M6 미러 + ETag/If-Match 실동작 + `Oem.Public.Status` error code 목록 | [MED] | 현재 fixture 는 mock |
| ACC-L7 | Huawei 미러 + **Redfish Login Interface 활성화 방법** | [MED] | 계정이 있고 권한도 맞는데 인증이 안 되는 원인. OEM field/action 미확보로 이번에 미구현 |
| ACC-L8 | Fujitsu iRMC RESTful API Specification pack 원문 + S4/S5/S6 미러 | [LOW] | Create 계약 자체가 미확보. 현재 generic 유지 |
| ACC-L9 | Quanta 3 Family(Legacy v1.1 / Modern v1.11 / Inhouse OpenBMC) 미러 | [LOW] | upstream OpenBMC 를 QCT 계약으로 간주하면 안 된다 |
| ACC-L10 | 후보 backoff 65초가 Jenkins Gather stage 시간에 주는 영향 실측 | [LOW] | Dell 복구 후보 4개 전부 실패 시 약 3분 추가. `-e _rf_auth_backoff_seconds=<n>` 로 조절 가능 |

### 코드 후속 (근거 확보 후)

| # | 항목 | 선행 조건 |
|---|---|---|
| ACC-C1 | Cisco IMC 3.x instance POST(`POST /Accounts/<ID>`) Family 추가 | ACC-L4 또는 IMC 3.x 미러 |
| ACC-C2 | Supermicro 최신 `/AccountService` POST Family 추가 | ACC-L5 (어느 Firmware 부터인지 확정) |
| ACC-C3 | Fujitsu `RedfishAdmin` Role Family 추가 | ACC-L8 |
| ACC-C4 | Huawei Redfish Login Interface 자동 복구 | ACC-L7 |
| ACC-C5 | `account_service_provision` 분할 (`redfish_gather.py` 5,800줄 초과 — rule 10 R3) | 기존 NEXT_ACTIONS 항목과 동일. `module_utils` import 경로가 Jenkins agent 에서 동작하는지 확인이 선행 |

---

## 실환경 검증 잔여 (2026-08-12) — 이 세션에서 확인 불가

> 정본: `tests/evidence/2026-08-12-runtime-verification-and-bugfix.md` §9.

| # | 항목 | 차단 사유 | 확인 방법 |
|---|---|---|---|
| 1 | Jenkins 실제 checkout SHA | `10.100.64.153:8080` API 가 HTTP 403 — 세션에 Jenkins 자격증명 없음 | 해당 Job 의 SCM 설정(Repository/Branch)과 최근 빌드의 `GIT_COMMIT` 을 Jenkins UI 에서 확인. push 성공만으로 반영 단정 금지 (CLAUDE.md §14) |
| 2 | Redfish Account Reconciliation **실제 Write** | dry-run 만 수행. 승인/검증 정책을 세션에서 확인 불가 | 승인된 lab 대상에서 `-e _rf_account_service_dryrun=false` 로 1대 검증 후 `account_service.verification` 이 `skipped` 아닌 값인지 확인 |
| 3 | BUG-2 수정의 벤더별 실장비 확인 | HPE(7 adapter 전 세대) / Fujitsu / Huawei / Inspur / Quanta 모두 lab 부재 | 장비 확보 시 `data.*.oem` 이 채워지고 `errors[]` 의 가짜 OEM 오류가 사라지는지 확인. 메커니즘은 site.yml block/rescue 재현으로 관측 완료(errors 1→0, OEM 소실→보존) |
| 4 | `redfish-gather/tasks/vendors/cisco/collect_oem.yml` 정리 판단 | 어떤 adapter 의 `oem_tasks` 도 이 파일을 참조하지 않는다 (dead file) | Cisco adapter(`cisco_ucs_xseries` 등)에 `oem_tasks` 를 연결할지, 파일을 정리할지 사용자 결정 필요 |

## Dell 대표 시리얼 교정 후속 (2026-08-11) — lab 부재로 미검증

> 본 작업 정본: `docs/ai/contracts/serial-number.md` Part III / 커밋 `0fb63799`.
> Dell 대표 시리얼을 `ServiceRoot.Oem.Dell.ServiceTag` 단일 정본으로 바꿨고 폴백을 없앴다.
> 아래는 **실기기가 있어야만** 닫을 수 있는 항목 (rule 96 R1-C).

- [ ] **DELL-ST-1 (HIGH) iDRAC7/8 실장비 fixture 캡처** — iDRAC7/8 Redfish API Guide(2.30~2.70)
      목차에 `DellServiceRoot` 가 없다. 실제로 `Oem.Dell.ServiceTag` 를 노출하지 않는 펌웨어라면
      그 장비는 이제 **수집이 실패**한다(폴백 금지의 귀결). 12G/13G PowerEdge 1대에서
      `curl -sk -u <user>:<pass> https://<BMC>/redfish/v1/ | jq .Oem.Dell.ServiceTag` 확인 후
      `capture-site-fixture` 로 fixture 화. 미노출이면 정책 재검토 필요(사용자 결정 사항).
- [ ] **DELL-ST-2 (MED) Dell 모듈러(블레이드) 확인** — 보유 Dell 7대 전부 Monolithic 이라
      `ChassisServiceTag`(= enclosure) 대신 `ServiceRoot.ServiceTag`(= node) 를 고른 근거가
      문서(DCIM1048)뿐이고 실측이 없다. MX7000 sled / FX2 / VRTX 1대 캡처로 확정.
- [x] **DELL-ST-3 실 playbook end-to-end 대조 — 완료 (2026-08-11)**
      Jenkins `clovirone-server-gather` #188(redfish, BMC 10.100.15.27/.34) / #189(os, 10.100.64.96).
      `hardware.serial` == `correlation.serial_number` == Service Tag 확인(`64CXJ54` / `GSBPK54`),
      동일 `system_uuid` 위에서 Redfish ↔ OS **SAME**. envelope 13필드 일치 / Stage 3 PASS.
      증거: `tests/evidence/2026-08-11-dell-serial-service-tag.md` 7절.
- [ ] **DELL-ST-4 (LOW) 무인증 ServiceRoot 미노출 사례 확보** — 인증 재조회 경로는 합성 BMC 로만
      검증했다(`test_service_tag_recovered_from_authenticated_service_root`). 실제로 무인증 200 +
      OEM 미노출인 펌웨어를 만나면 fixture 로 남길 것.

## 진단(diagnosis) 개선 Phase 1-B / Phase 2 (2026-08-10) — Portal Contract 확인 대기

> 계획서: `C:/Users/hshwa/.claude/plans/precheck-snazzy-leaf.md` rev.2 (§18 Q1~Q9, §19 3목록).
> Phase 1-A 는 2026-08-10 완료 (`docs/ai/CURRENT_STATE.md` 2026-08-10 (c)).
> 아래는 **외부 JSON Contract 의미가 바뀔 수 있어** Portal 확인 없이 착수하면 안 되는 항목.
> Jenkins 는 envelope 을 파싱하지 않고 그대로 통과시키므로(`Jenkinsfile_portal:250-272`)
> 리스크는 전부 **저장소 밖 Portal API** 한 곳에 집중된다 — 코드를 볼 수 없어 추정 불가.

### 선행 질문 (사용자 / Portal 담당)

- [ ] **Q1** Portal 이 `diagnosis.auth_success` 를 읽는가? **null 을 안전 처리**하는가?
      `diagnosis` 자체가 null 인 경우를 분기 조건으로 쓰고 있는가?
- [ ] **Q2** Portal 이 `failure_stage` 로 분기하는가? 지금까지 안 나오던 `"auth"` 값 유입 영향?
- [ ] **Q3** Portal 이 알 수 없는 신규 필드(`failure_code`)를 무시하는가, 거부하는가?
- [ ] **Q4** `failure_stage` 신규 값 `"gather"` 유입 시 default 분기가 있는가?
- [ ] **Q5** `failure_code` 를 항상 emit(성공 시 null) vs 실패 시만 emit — 어느 쪽?
- [ ] **Q6** `schema/field_dictionary.yml` 수정 승인 (rule 92 R5 / 보호 경로)
- [ ] **Q7** baseline 10건에 실측 없이 shape 키 추가 승인 (rule 21 R1 예외)
- [ ] **Q9** Contract 확장 시 `schema_version` 증가 원칙이 Portal 과 합의돼 있는가?

### Phase 1-B — **완료 (2026-08-10)**

> Portal 이 `diagnosis.failure_reason` 만 사용한다는 사실이 확인되어 Q1/Q2 대기 없이 진행.
> 상세: `docs/ai/CURRENT_STATE.md` 2026-08-10 (d). 계약 테스트 `tests/e2e/test_failure_reason_contract.py`.

- [x] OS 인증 실패 / 수집 예외 시 `diagnosis: null` 제거 (linux·windows rescue 에 진단 생성)
- [x] Redfish·ESXi precheck 통과 후 실패 시 `failure_reason: null` 제거
- [x] OS 포트 전멸 `auth_success: false` → `null`
- [x] `_try_redfish_auth` 가 timeout/5xx 까지 `auth_success=false` 로 만들던 것 → **401 한정**
- [x] `failure_reason` 문구를 특수 구분자 없는 완전한 한국어 문장으로 통일
- [ ] **[남음] Portal Q1~Q2 확인** — 위 변경으로 Portal 이 받는 값이 달라진다:
      `diagnosis` 가 null 이 아니게 되고, `failure_stage` 에 `"auth"` 가 새로 유입되며,
      `auth_success` 의 `false` 가 사실상 사라진다. Portal 이 이 값들로 분기하고 있지 않은지
      확인 필요 (현재 failure_reason 만 쓴다는 전제라면 영향 없음).

### Phase 2 — **완료 (2026-08-10)**

> 상세: `docs/ai/CURRENT_STATE.md` 2026-08-10 (e). 계약 테스트 `tests/e2e/test_failure_code_contract.py`.

- [x] `failure_stage` enum 에 `gather` 추가 (실행이 중단된 단계 의미 유지)
- [x] `diagnosis.failure_code` 신설 (nullable 7종, 성공 시에도 키 존재)
- [x] TCP 실패 분류를 문자열 파싱에서 `tcp_check_ex()` 구조화 kind 로 교체
- [x] schema · baseline · examples · fixtures · hook · 문서 정합화
- [x] schema_version `"1"` 유지 (근거: `docs/contract/03-fields.md`:589` 정책 + 전례 2건)
- [ ] **[남음] Redfish HTTP 401 기반 인증 실패 세분화 (운영 경로)** — `redfish_gather.py` 의
      errors 엔트리는 `{section, message, detail}` 3키뿐이고 HTTP status 가 message 문자열
      안에만 있다(`_err():370-371`). 모듈 `exit_json` 에도 구조화된 status 필드가 없다.
      문자열 파싱을 새로 만들지 않기로 해(사용자 지시) 운영 Redfish 경로는
      `AUTH_PROBE_FAILED` + `auth_success:null` 을 유지한다. 모듈이 구조화된 status 를
      반환하도록 바꾸는 것이 선행 조건.
- [ ] **[남음] Portal Receiver strict deserialization 확인** — 저장소에서 확인 불가.
      `failure_code` 신규 키와 `failure_stage` 신규 값 `gather` 를 Portal 이 거부하지 않는지 확인.

### 별도 후속 (이번 범위 밖)

- [ ] **[LOW] OS Precheck 구조 개선** — OS 는 프로토콜을 **한 번도 독립 관측하지 않는다**
      (`wait_for` = TCP only). `probe_os()` 는 구현·단위테스트가 있으나 운영 미배선이며,
      배선 시 배너 억제 SSH 서버가 **신규 탈락**한다(`precheck_bundle.py:327-328` 자인) +
      `add_host` 의 connection/port/scheme 결정에 직결(`os-gather/site.yml:99-131`).
- [ ] **[LOW] Protocol Detection 강화** — 현재 허용 status 목록은 사이트 실측 기반 vendor
      호환 대응(HPE iLO 406 / Lenovo XCC 헤더 / ESXi `/sdk` 404·500). 본문 검증을 추가하면
      **바로 그 장비들이 False Negative** 가 된다. lab 부재 vendor 다수 → 별도 조사 선행.
- [ ] **[LOW] `try_one_credential` 실패 원인 구분** — `_os_probe_*.unreachable` /
      `_e_probe.msg` 에 구분 재료가 남아 있으나 현재 판정식이 전부 버린다.

## adapter/OEM 배선 정합 후속 (2026-08-10) — 설명자료 조사에서 파생

> 상세: `docs/ai/CURRENT_STATE.md` 2026-08-10 (b). 당시 참고한 설명자료 원본은 삭제됐다.
> 코드 fix 3종 적용 완료(pytest 1368 passed). 아래는 **승인 또는 실장비가 필요해 미착수**한 항목.

- [ ] **[MED / 승인필요] cisco OEM tasks 배선**: `redfish-gather/tasks/vendors/cisco/{collect,normalize}_oem.yml`
  이 구현돼 있으나 cisco 어댑터 3개(`cisco_bmc` / `cisco_cimc` / `cisco_ucs_xseries`) 전부
  `collect.oem_tasks` / `normalize.oem_tasks` 키가 없어 **한 번도 실행되지 않았다**.
  연결 시 `data.bmc.oem_cisco` 신설 → **envelope 변경 + `schema/baseline_v1/cisco_baseline.json`
  갱신 동반** → rule 92 R1-B(Additive 범위 밖) + rule 13 R4(baseline 은 실측 기반) 로
  **사용자 명시 승인 + 실장비 재수집이 선행돼야 함**. 승인 시 별도 cycle.
- [ ] **[MED / lab] huawei 실펌웨어 문자열 확보 후 firmware_patterns 재검증**: 2026-08-10 에
  glob→정규식 정정했으나 **lab 부재라 실제 `FirmwareVersion` 표기를 못 봤다**(rule 96 R1-A).
  현재 패턴은 `3.01` / `iBMC 3.01` / `V3.01` 3형식을 커버하는 추정값이며 회귀 12건으로 고정돼 있다.
  실장비 확보 시 실측으로 교체 + `tests/evidence/` 기록.
- [ ] **[LOW] lenovo firmware_patterns 정리**: `AFBT*` / `TAOT*` / `USX*` 도 정규식에서는
  "AFB + T반복" 으로 해석된다(huawei 와 동일 계열 위험). 의도한 입력에는 우연히 동작하나,
  `^AFBT` 형태로 정리 권장. 실장비 펌웨어 문자열 확보 후 착수.
- [ ] **[LOW] 어댑터 스키마 검증기 도입 검토**: 위 3건 모두 **adapter YAML 오타/오문법을
  아무도 검출하지 않는다**는 같은 뿌리에서 나왔다(`adapter_loader` 는 스키마 검증 없음).
  허용 키 화이트리스트 + `*_patterns` 정규식 컴파일 검사를 하는 pre-commit 훅 후보.

---

## is_os_disk 실장비 검증 (2026-07-02) — 표준 토폴로지 [DONE]

> 상세: `tests/evidence/2026-07-02-is-os-disk.md` (라이브 검증 절). Jenkins build #165(Linux 4대)/#166(Windows .120) SUCCESS + SSH/winrm ground truth 3자 일치. 배포 커밋 c4696c87.

- [x] **[DONE 2026-07-02] 실장비 is_os_disk 실측 (Linux 4대 + Windows)**: SSH/winrm 직접 + Jenkins #165/#166 envelope 교차 대조 전부 일치 (Linux OS=sda true, Windows PHYSICALDRIVE0 true). `lsblk -s` 글리프 버그 실증 + `-s -l` fix 검증.
- [x] **[DONE 2026-07-02] 실 Agent ansible 실행**: Jenkins #165/#166 4-Stage SUCCESS (syntax-check 이상 — 실 gather + schema validate + E2E 통과).
- [x] **[DONE 2026-07-02] 예외 토폴로지 loop 더미 검증**: mdraid RAID1 + LVM 2-PV(.161) 멤버 all-true, btrfs subvol(.154) `[/@]` strip — loop 파일 더미로 실장비 실증(사용자 승인, 완료 후 정리). 상세 evidence.
- [ ] **[LOW] 잔여 토폴로지 (장비 부재)**: multipath 멤버 all-true(=mdraid 동일 traversal, 고신뢰 미실측) / Windows Storage Spaces·동적미러=null / Dell BOSS-N1 실부팅(예 10.100.64.96 → nvme0n1=true) — 해당 장비 확보 시.
- [ ] **[LOW] SAN/iSCSI/NFS 루트 null 케이스 + 회귀 fixture**: 로컬 매핑 불가 시 null 실측 + 빈 osdisks fixture 추가 ('거짓 false 금지' 불변식 고정).

## NetworkAdapters 400 마스킹 fix 후속 (2026-08-03) — 사이트 재검증

> 상세: `tests/evidence/2026-08-03-network-adapters-400-masking.md` + `docs/reference/decision-log.md` 2026-08-03.
> 코드 fix 3종 적용 + pytest 1302 passed. 아래는 **이 환경에서 확인 불가**한 항목.

- [x] **[DONE 2026-08-03] 1차 재빌드 확인 (#3)**: 8대 전부 `status=success` + `sections.network=success`,
  빌드 SUCCESS. 전수 비교에서 바뀐 필드는 `sections.network` 하나뿐(부작용 0).
- [x] **[DONE 2026-08-03] 400 의 근본 사유 확정**: **장비 미지원 아님 — 수집 측 경로 오류**.
  사이트 8대는 PowerEdge R630(13G / iDRAC8)이고 벤더 공식 API 가이드상 NetworkAdapters 는
  `Systems/{id}/NetworkAdapters`. `Chassis` 만 물어봐서 400. 400→unsupported 분류는 **철회**하고
  Systems 경로 fallback 신설. `EXTERNAL_CONTRACTS.md` 2026-08-03 에 세대별 URI 표 기록.
- [x] **[DONE 2026-08-03] fallback 실효 확인 (빌드 #4)**: Dell R630 8대 전부 `adapters` 1건
  (`BRCM 10G/GbE 2+2P 57800 rNDC`, S/N·firmware·port_count 실값) + `ports` 4건 수집. MAC 이
  `network.interfaces[]` 와 일치. 빌드 SUCCESS. **목표 달성.**
- [x] **[PARTIAL 2026-08-03] FCoE CNA 오분류 1차 fix (빌드 #5)**: 8대 중 6대 `hbas=0` 해결.
  잔존 2대(.52/.152)는 NIC 펌웨어 15.20.13 이 NDF 에 MAC 파생 WWN 을 노출하는 케이스 —
  NDF↔Port join 실패(orphan)로 포트 컨텍스트 없이 분류돼 강등 fix 가 무력화됨.
- [x] **[DONE 2026-08-03] orphan NDF 부모 상속 fix 확인 (빌드 #6)**: **8/8 `hbas=0`** +
  `ports` 전부 Ethernet + 빌드 SUCCESS. 사이트 증상 전부 해소.
- [ ] **[MED] 조립 경로 → 링크 추적 전환 (근본 대책)**: `redfish_gather.py` 는 하위 컬렉션 경로를
  문자열로 조립한다(17곳 — `EXTERNAL_CONTRACTS.md` 2026-08-03 감사 표). 부모의 `@odata.id` 를
  따라가면 세대 무관해진다. 현 시그니처가 부모 응답을 안 갖고 있어 ComputerSystem/Chassis 를
  한 번 받아 하위로 전달하는 구조 변경 필요 → 전 섹션 영향, **별도 cycle**.
  (임시 안전망: `test_constructed_paths_match_exposed_links` 가 fixture 기준 자동 대조)
- [ ] **[MED / lab] `.52` / `.152` 만 orphan Ethernet 신호를 못 얻은 이유 확정**: 두 번의 원인 가설
  (WWN 미노출 / NIC 펌웨어)이 **전수 대조로 모두 반증**됐다(`.53`↔`.52` 동일 fw, 결과 상이).
  NDF raw(`NetDevFuncType` / `Links`)를 캡처해야 확정 가능 → `capture-site-fixture`.
  **동작은 이미 정상**이므로 우선순위 MED — 다만 원인 미상인 채로 두면 유사 케이스 재발 시 또 헤맨다.
- [ ] **[MED / lab] 사이트 fixture 캡처**: iDRAC8(13G) 은 lab 미보유 세대 — `capture-site-fixture` 로
  미러 확보 시 Systems-경로 토폴로지 회귀를 **합성 변조가 아닌 실 캡처**로 고정 가능
  (현재 integration 테스트는 R740 미러를 Systems 밑으로 옮긴 합성).
- [ ] **[MED] adapter 세대 오선택 (iDRAC8 → `redfish_dell_idrac10`)**: 무인증 probe 단계에 model/firmware
  가 비어 priority 최상위만 선택되는 기존 이슈가 사이트에서 실증됨(8대 전부 iDRAC8 인데 idrac10 선택).
  수집 데이터는 세대 무관 동일이라 무해하나 `diagnosis.not_supported_message` 라벨이 부정확.
  기존 항목("Dell·Lenovo 세대 adapter 가 priority 로만 선택") 과 동일 건 — 실증 사례 확보로 우선순위 상향 검토.

## OS physical_disks serial/wwn 후속 (2026-06-22)

> 상세: `docs/ai/CURRENT_STATE.md` 2026-06-22 + `tests/evidence/2026-06-22-os-disk-serial-wwn.md`.
> 코드/검증 완료(gatherOS #41/#42 SUCCESS). lab 전부 VM → 아래는 실값 확정용 후속.

- [x] **[DONE 2026-06-22] baremetal Linux 실값 검증**: 10.100.64.96(Ubuntu 24.04 baremetal) gatherOS #43 →
  SATA RAID(`0x6f4e…`) + NVMe(`eui.…`) serial/wwn 실값 emit. SSH ground truth 일치, false-null 없음.
  (선택 후속: 96 을 baremetal regression baseline 으로 추가 — 현재 ubuntu_baseline 은 VM virtio null 만.)
- [x] **[DONE 2026-06-22] Windows live 실측** (10.100.64.120, Win Server 2022): gatherOS status=success, 전 섹션 정상.
  disk **serial/wwn 실값 populate**(`6000c29...`/`6000C29...`, Get-PhysicalDisk) + health="healthy" + memory.slots 실측.
  evidence: `tests/evidence/2026-06-22-windows-120-verification.md` + envelope json.
- [x] **[DONE 2026-06-22] windows_2022 baseline 신설**: 10.100.64.120 실측으로 `windows_2022_baseline.json` +
  TestWindows2022Baseline(serial/wwn/health populate 단정) 추가. commit `ec543f9e`.
- [ ] **[LOW] windows_baseline(generic) serial/wwn 정정**: 기존 generic baseline 의 serial/wwn=null 은 부정확
  (추론값) — generic host 재캡처 시 실값 반영. (windows_2022 가 실 회귀 커버하므로 우선순위 낮음.)
- [ ] **[LOW] Windows serial 니블-swap 보정**: 현재 hex→ASCII 디코딩만, 2글자 swap 미적용(드라이브별 상이).
  실측에서 swap 필요 드라이브 확인 시 `Normalize-DiskSerial` 보강.
- [ ] **[LOW / 선택] redfish 디스크 wwn 확장**: redfish 는 현재 serial 만 emit(5 vendor baseline 실값 확인).
  `Drive.Identifiers`(NAA/EUI) 기반 wwn 추가 시 cross-channel 일관 (별도 cycle).
- [x] **[DONE 2026-06-22] ESXi 디스크 수집 신규 feature**: `esxi_disks.py`(pyvmomi) 로 physical_disks serial/wwn
  수집. gatherESXi #3 SUCCESS(esxi02 2 disks naa). commit `583dc293`/`82926268`.

## 미수집 필드 전수조사 후속 (2026-06-22)

> 상세: `2026-06-22 os-disk-serial-wwn 티켓의 AUDIT 문서 (삭제됨 — git log 참조)` (ESXi/OS 3 agent 실측 audit).

- [x] **[DONE 2026-06-22] Tier1 무의존 구현** (commit `dcdf32e8`/`8aa06f18`):
  - ESXi `storage.controllers[]`(hostBusAdapter, 5개 esxi02 실측) / Linux `storage.controllers[]`(lspci, 96 PERC H965i 실측) /
    Linux `network.adapters[].firmware_version`(ethtool, 96 tg3/bnxt_en/i40e 실측).
  - **잔여**: ESXi `listening_ports` — root 동작하나 gather(vault) 유저 firewall 권한 부족 → `[]`. **ops: vault 계정 Host.Config 읽기 권한 grant 필요**.
  - **잔여**: Linux ubuntu/rhel810 baseline 재캡처 (신규 controllers[]/adapters.firmware_version 키 — VM 값. pytest 영향 없음, 96 baremetal 검증 완료).
- [x] **[DONE 2026-06-22] Tier2 channel drift 정정** (commit `03dbebc6`): Windows `physical_disks[].health` 등록 / `memory.slots[]` channel os 추가.
- [ ] **[MED / 사용자] Tier3 의존성·섹션 결정**:
  - `physical_disks[].health`/`predicted_life_percent` — **smartmontools 설치**(rule 92 R1 의존성 승인) + VM SMART 미지원 graceful
  - `thermal` 섹션(OS sysfs hwmon[96 실측] + ESXi numericSensorInfo[실측]) — sections.yml 확장(schema 결정)
  - `power` 섹션 ESXi(numericSensorInfo PSU) — sections.yml 확장
  - OS `firmware[]`(dmidecode BIOS + ethtool/fwupd) — sections.yml 확장 + dmidecode sudo
- **불가 확정**: ESXi `logical_volumes[]`/per-DIMM 용량(BMC 영역), OS Linux/Windows `power`(PSU OS 미노출), Windows `thermal`(VM 미지원).

---

## Jenkinsfile_portal vault → Credentials 전환 후속 (2026-06-18)

> 상세: `docs/ai/CURRENT_STATE.md` 2026-06-18 항목. portal Gather 하드코딩 패스워드 제거 + Jenkins
> Credentials(`server-gather-vault-password`) 통일 (commit `fed68ef2`, main).

- [x] **[MED / 사용자] production 반영 (2026-06-22 완료)**: 사용자 승인(rule 93 R2) 후 production 에
  순수 코드만 반영 — vault→Credentials(`efdb4c28`) + Callback curl→httpRequest(`c8f901f0`). production
  `Jenkinsfile_portal` == main (diff 0), 하드코딩 평문 제거 확인, docs/ai 하네스 미유입. github+gitlab push.
  (production 커밋은 하네스 pre-commit 훅 부재로 `--no-verify` 사용 — 사용자 명시 승인 2026-06-22.)
- [ ] **[LOW / lab] 실 Jenkins 빌드 확인**: portal 파이프라인 1회 빌드로 (1) `server-gather-vault-password`
  주입 → ansible-vault 복호화, (2) Callback `httpRequest()` POST 정상 동작 확인 (로컬 환경에선 Groovy/Jenkins 미검증).

## OEM cascade graceful degradation — os/esxi 확장 + 라이브 검증 (2026-06-16)

> 상세·근거: `docs/reference/decision-log.md` 2026-06-16 항목. CSUS 실 게더링에서 HPE OEM dict conditional(Bug A)
> + `site.yml` 단일 block/rescue cascade(Bug B) 발견. Bug A 전면 수정 / Bug B 는 redfish 만 적용(사용자 승인 2026-06-16).

- [ ] **[HIGH / lab] 라이브 검증**: 실 CSUS 3200(4노드) 또는 오프라인 replay 로 게더링 재실행 → `status=success`(9 섹션) + OEM 경고 `errors[]` 확인. ansible 필요(Windows 미지원이라 정적 검증만 완료).
- [ ] **[MED] 배포 동기화 확인**: lab Jenkins 배포 코드가 본 `normalize_oem.yml`/`site.yml` 수정을 포함하는지 확인. 에러가 가리킨 `collect_oem.yml:101` 은 HEAD 에 부재 — 내부 GitLab stale 또는 다른 세션 미커밋 가능.
- [ ] **[MED] Bug B os/esxi 확장**: 동일 단일 block/rescue cascade 가 os-gather(Linux PLAY2 :266/:270, Windows PLAY3 :445/:464) / esxi-gather(:123/:136/:140) 에 존재. 보조 단계(hba_ib/runtime/network_extended/dns) local block/rescue 화. status 의미 변경 → 승인 + 전 baseline 회귀 필요.
- [ ] **[MED] 회귀 가드**: vendor OEM `when` 조건 boolean-safety lint(dict `or` 체인 / unguarded regex_search 검출) — ansible 불요 정적 검사로 재발 차단. 기존 `pre_commit_regex_search_conditional_check.py` 의 sister.
- [ ] **[LOW] collect_oem.yml dead-code 정리**: 실 CSUS OEM 은 라이브러리(`redfish_gather.py`)가 직접 수집(#HpeH3Npar/#HpeH3Chassis). `collect_oem.yml` 의 구식 PartitionInfo/FlexNodeInfo 추출 블록 제거 또는 adapter `oem_tasks` 해제(adapter 주석 71-72 기등재).

## hostname BMC fallback — baseline 갱신 + cross-vendor 실측 (2026-06-16)

> 상세: `tests/evidence/2026-06-16-real-capture-audit.md` + `docs/contract/03-fields.md` §8`. hostname 우선순위에
> BMC NetworkProtocol.HostName fallback 추가(System.HostName 부재 시). 코드는 vendor-agnostic
> graceful. 실측: Dell iDRAC9 / HPE iLO7·RMC / Lenovo XCC3 = populate, Cisco CIMC = null.

- [ ] **[MED / lab] baseline hostname BMC-fallback 값 갱신**: `hpe_baseline`(System.HostName="")·
  `lenovo_baseline`(System.HostName 부재)는 현재 `hostname=null`. 신 정책상 live 는 BMC
  NetworkProtocol.HostName(ILOSGHD3KHHRP / XCC-...) 을 줄 것. 단 baseline 원본 장비의 BMC명을
  안 갖고 있어(=내 4대 캡처와 다른 IP) 추측 금지 → lab 재수집 시 정확값 + `data.bmc.network_hostname`
  + `diagnosis.details.hostname_source` 반영. (real_* fixture 4종은 신 코드로 정확값 보유 — 회귀 커버됨.)
- [ ] **[MED / lab] cross-vendor NetworkProtocol.HostName 실측**: Supermicro / Huawei / Inspur /
  Fujitsu / Quanta + 구세대(iDRAC8 / iLO4~6 / XCC2 / CIMC v2~v3)에서 NetworkProtocol.HostName
  populate 여부 실측 미확인(lab 부재 — 부분 합성 fixture 만). 매트릭스:
  `tests/evidence/2026-06-16-hostname-source-matrix.md` (DMTF 표준 + web sources, confidence=likely).
  graceful 구현이라 동작은 안전하나 "어느 벤더가 BMC명을 주나" 의 실측 확정은 lab 후.

## thermal 섹션 baseline staleness — lab 재생성 (2026-06-16)

> 상세·근거: `tests/evidence/2026-06-16-real-capture-audit.md`. thermal 은 cycle 2026-06-14
> (Track 4)에 11번째 섹션으로 추가됐으나 `schema/baseline_v1/` 9종 전부 thermal 누락(2026-06-14
> 이전 생성). 코드는 thermal 정상 수집(real_* fixture 4종이 검증). baseline 만 뒤처짐(stale).

- [ ] **[HIGH / lab] baseline 9종 thermal 포함 재생성**: redfish 5종(dell/hpe/lenovo/cisco/csus)은
  각 원본 장비 + ansible 정규화로 `sections.thermal` + `data.thermal`(temperatures/fans) 포함 재생성.
  os/esxi 4종(ubuntu/windows/rhel810/esxi)은 thermal=`not_supported`(redfish 전용 섹션). **ansible
  필요 → lab(Jenkins 실 빌드 또는 agent)에서 수행** (rule 13 R4 실측 기반). 외부 Windows 환경은 ansible
  실행 불가.
- [ ] **[자동] 재생성 후 `KNOWN_STALE_SECTIONS` 비우기**: `tests/regression/test_cross_channel_consistency.py`
  의 `test_sections_has_all_canonical` 가 현재 9 baseline XFAIL(thermal). baseline 재생성 후 각
  baseline 이 PASS 로 전환 → 전부 PASS 되면 `KNOWN_STALE_SECTIONS = frozenset()` 로 비워 가드 완성.
- **참고**: 신규 `tests/fixtures/redfish/real_*` 4종(모듈 golden)은 thermal 포함 — thermal 수집 회귀는
  이미 커버됨. 본 항목은 **최종 envelope baseline** 의 thermal 반영(호출자 계약 reference)만 남은 것.

## OS 네트워크 본딩/티밍 수집 보강 (2026-06-15) 후속

> 상세·근거: `tests/evidence/2026-06-15-os-network-bond.md`. Linux bond 는 실장비 2대(RHEL 8.10 raw /
> RHEL 9.6 python) 검증 완료·수렴. 아래는 환경 제약으로 미수행한 후속.

- [ ] **[HIGH] Windows Teaming 실장비 검증**: LBFO(Get-NetLbfoTeam)/SET(Get-NetSwitchTeam) 수집은
  코드 + 단위테스트(realistic fixture)만 검증, 실 Windows 호스트 미제공 → 미검증. Windows Server +
  LBFO/SET 구성 호스트에서 `os-gather` 실행 후 `data.network.teams[]` + interfaces team_role 대조 필요.
- [ ] **[MED] bonded OS baseline (full envelope) 생성**: 현재 회귀는 `tests/fixtures/os/net/*` (data.network
  레벨) + 실 YAML 렌더 테스트로 고정. 전체 envelope baseline(`schema/baseline_v1/`)은 lab 호스트에 ansible
  미설치로 미생성 → Jenkins 실 빌드로 RHEL 8.10/9.6 bonded envelope 캡처 후 baseline 추가 권장(rule 13 R4).
- [x] **[LOW] 추가 bond 모드 실커널 검증 (2026-06-15 완료)**: 7개 모드 전부(balance-rr/active-backup/
  balance-xor/broadcast/802.3ad/balance-tlb/balance-alb) RHEL 8.10 dummy 인터페이스로 실커널 mode 파일값
  → 정확 파싱 확인. `test_real_kernel_all_bond_modes` 회귀 고정. (사이트 실 NIC 본딩은 사이트 존재 시 추가 권장)
- [x] **[LOW] VLAN-on-bond 실커널 검증 (2026-06-15 완료)**: bond 하위 VLAN(id/parent/IP) + 물리 slave 무IP
  실커널 캡처 → `tests/fixtures/os/net/bond_vlan_realkernel_topo.txt` + `test_real_kernel_vlan_on_bond_fixture`.
  /proc/net/vlan 권한거부 시에도 ip -d link 소스로 graceful 확인.
- [ ] **[LOW] Linux teamd 실장비 검증**: teamd 팀은 코드+단위테스트만(실커널 미검증 — teamd 데몬 구성 필요).

## Redfish adapter origin 최신화 + 세대 선택 (2026-06-15) 후속

> 상세: 본 cycle adapter origin diff + `tests/redfish-probe/verify_adapter_selection.py`. 4 device 실 미러로 adapter 선택 실측.

- [x] **adapter origin 최신화 (2026-06-15 완료)**: hpe_csus_3200 / hpe_ilo7 / lenovo_xcc3 "lab 부재/추정" → 실 캡처
  검증 승격, dell_idrac9 R740 보강, VENDOR_ADAPTERS priority(96/95→102/101)·count(83→134) 정정. 동작 로직 불변
  (선택 점수 실측 동일), pytest 1204 passed.
- [ ] **[LOW / gated] Dell·Lenovo 세대 adapter 가 priority 로만 선택 (cosmetic)**: 무인증 ServiceRoot 에 server model
  부재(Dell=BMC명 "Integrated Dell Remote Access Controller" / Lenovo=None) → facts.model·firmware 빈값 → 세대 구분
  불가, priority 최상위만 선택 (Dell→idrac10 / Lenovo→xcc3 항상, 실측 2026-06-15 R740·SR650 V4). collect/normalize
  tasks 가 세대 무관 동일(dell/lenovo OEM)이라 **수집 데이터는 정확** — `diagnosis.not_supported_message` 세대 라벨만
  부정확(cosmetic). HPE 는 `_extract_probe_facts` 가 ServiceRoot.Product/Oem.Hpe.Manager 로 model/firmware 채워
  세대 구분됨. 개선하려면 인증 후 model 재평가 또는 vendor별 ServiceRoot semantic 확장(설계 결정 — 사용자 승인). 현재 무해라 보류.

## HPE Compute Scale-up Server 3200 (CSUS 3200) 실 미러 검수 (2026-06-15) 후속

> 상세·근거: `tests/evidence/2026-06-15-hpe-csus3200-mirror-audit.md`. 라이브러리 fix **17건** 적용·수렴.
> 1차 16건(5-round) + 후속 재검수 1건(CSUS-R17, 3-round 재수렴 NEW 0). 회귀 1154 passed. 4 노드(실 RMC) raw 기준.

### 완료 (라이브러리 — 자율 수정, raw 충실 + Additive)

- [x] R1 chassis=System.Links.Chassis / FC1·FC2 FC WWPN / R3 multi_node system / R4 ilo_version / R5 chassis kind
- [x] R6 port_count / R9 PSU fw / R10·R14 power(telemetry 권위) / R11 fan RPM / R12 memory locator
- [x] R8 Ethernet 분류 / R13 FC associated_address=WWPN(전벤더) / R15 _network_meta strip / R16 adapter firmware(PCIeDevice)
- [x] **R17 (재검수 2026-06-15, 커밋 1167e01a)**: `_extract_oem_hpe` 를 OEM `@odata.type` 로 분기 — #HpeH3Npar 면 CSUS
  전용 키(product_id/console_routing/console_routing_current_boot/dcd_version/host_os_*) 추출. 구: all-null iLO 스켈레톤
  날조(missing-looks-valid) + 실 OEM drop. iLO default 불변(Additive). **SYS-OEM gated 항목 해소**. 회귀 +3.

### 잔여 — gated (보호 경로 / Ansible(Linux) / lab 실측 / envelope 계약 — 자율 미수정)

- [ ] **[HIGH] CSUS baseline 실측 교체 (BASE-01)**: `schema/baseline_v1/hpe_csus_3200_baseline.json` 이 구 MOCK
  (가상 3-partition/4-manager, 날조 PSU/WWPN/토폴로지) — 실 4노드와 전면 불일치. 라이브러리는 정상(faithful),
  회귀 기준선 무력. **Ansible control node(Linux) 필요 — 본 Windows 환경 미지원**(DL380 과 동일 제약). 실 site.yml
  실행으로 정규화 envelope 생성 후 교체 (rule 13 R4 — AI 임의 편집 금지). 교체 시 `test_csus_mock_consistency.py` MOCK 가드 동반 갱신.
- [ ] **[MED] field_dictionary drift (FD-01)**: `multi_node.partitions[].boot` / `chassis[].thermal` / `composition` /
  `fabrics` / summary 신필드(resource_block_count/fabric_count) 미문서 (엔진은 이미 emit). 보호 경로 — 사용자 승인.
- [ ] **[MED] collect_oem.yml CSUS 실 OEM 필드명 (OEM-01)**: `tasks/vendors/hpe/collect_oem.yml` 이 Superdome Flex
  추정 필드명(PartitionInfo/FlexNodeInfo)을 읽어 CSUS 실 OEM(#HpeH3Npar: ProductId/ConsoleRouting/Physloc)과 불일치
  → OEM fragment 영구 미생성(라이브러리 replay 미노출, 실 파이프라인 silent 누락). 재검수(2026-06-15) 추가 확인: 추출한
  `_hpe_superdome_*` 변수도 step 3 에서 미사용(항상 `_data_fragment:{}`) = dead/no-op. **단 무해** — 라이브러리 CSUS-R17 이
  system OEM 직접 수집. Ansible 환경 미보유로 검증 불가 → 정리(또는 CSUS-R17 정합 재작성) 권장. lab/실 raw 로 HpeH3* 필드명 확인 후 교정.
- [x] ~~**[LOW] system.oem iLO-shaped (SYS-OEM)**~~ — **해소** (재검수 CSUS-R17, 커밋 1167e01a). all-null iLO 스켈레톤 →
  #HpeH3Npar 분기로 실 OEM 추출. 4노드 raw 1:1 검증.
- [x] **R18 (재검수 2026-06-15, F2)**: `gather_chassis_multi` 에 chassis-level OEM 수집 추가 — `_extract_chassis_oem`
  (#HpeH3Chassis: oem_chassis_type/physical_location/physloc/processors_compatibility_key/processors_compatible).
  multi_node.chassis[r001u01].oem 에 노출(RackGroup/Rack/타 벤더 {} — Additive, OEM @odata.type gated, rule 12 R1).
  4노드 raw 1:1 검증 + 회귀 3. (multi_node 신필드라 field_dictionary 문서화는 FD-01 과 함께 — 아래)
- [x] **MEM-01 (재검수 2026-06-15)**: `gather_memory` `_safe(...,'CapacityMiB') or 0` → `_safe_int(_safe(...,'CapacityMiB'))`
  — CapacityMiB 부재 시 0 날조 제거(누락↔0 혼동 해소, None 보존). 실데이터 회귀 0(present DIMM 불변, present 0 도 0 보존),
  부재 케이스만 0→None. 범용(전 벤더) 코드. 회귀 2. (CSUS 미발동이나 wrong-default 안티패턴 자체 제거.)
- [ ] **[LOW] network shape (NET-SHAPE) — 재검수: 비-결함 확인**: top-level `data.network`(라이브러리 intermediate)=list 이나
  `normalize_standard.yml`(:444-445,:545-552)가 dict 로 재조립 → **호출자는 dict 수신**. replay(라이브러리 단독) 산출물을
  최종 envelope 로 오인한 finding. 코드 변경 불필요(재검수 4-round 확인). 잔존 시 doc/tooling 주석만.
- [INFO] **CSUS-NET-META-01 (round 4) — 비-결함 확정**: replay `data.bmc._network_meta`(RMC gateway, 4노드 raw 1:1)는
  replay 도구 한정 누설. 라이브러리 `gather_bmc` 정상(normalize 가 소비→default_gateways/dns_servers 생성 후 strip,
  baseline grep 0). 라이브러리 pop 시 전 벤더 회귀 → **수정 금지**. single(normalize strip) vs multi_node(라이브러리 strip,
  CSUS-R15) 비대칭은 정규화 경로 의존 의도된 설계. code/data bug 아님. (NET-SHAPE 와 동류 — replay≠production.)
- [x] ~~**[LOW] network 섹션 매핑 충돌 (NET-SEC-MAP)**~~ — **해소 2026-08-03** (사이트 Dell 8대에서 실발동).
  `_rf_aux_sections: ['network_adapters']` 도입 — 보조 섹션을 collected/failed/**unsupported** 세 fragment
  전부에서 제외해 섹션 status 를 주 수집만으로 결정. 400 도 capability 부재로 분류(+`errors[].detail` 에
  ExtendedInfo 보존). 회귀 27건 신규. 상세: `docs/reference/decision-log.md` 2026-08-03 +
  `tests/evidence/2026-08-03-network-adapters-400-masking.md`.
- [ ] **[LOW] Rmp 관리어댑터 / multi_node.chassis name / ResourceBlock count**: Rmp(관리 NIC, MAC 은 bmc.mac_address 존재)
  placeholder 필터 drop / chassis name 미emit(envelope shape) / ResourceBlock proc·mem count=0(ComputerSystem-type 충실).
- [ ] **[INFO] lab 도입 후 별도 cycle**: `hpe-csus-3200-lab-validation` round — 실 capture-site-fixture + baseline + vault 결정.

## HPE DL380 Gen12 실 미러 검수 (2026-06-15) 후속

> 상세·근거: `tests/evidence/2026-06-15-hpe-dl380-mirror-audit.md`. 라이브러리 fix 7건 적용·수렴(Round4 NEW 0)
> + 사용자 승인 후속 진행. 회귀 1123 passed.

### 완료 (사용자 승인 후 진행 — 2026-06-15)

- [x] **thermal 섹션 배선 (ATX-01/02)** — `build_sections.yml`/`build_failed_output.yml` all_sec +
  3 skeleton 에 thermal 추가 (10→11 섹션). `docs/reference/decision-log.md`·20 동반(rule 13 R8). status-scenario 회귀 5건. (commit 7be8cdc0)
- [x] **firmware category 오분류 (SCHEMA-07)** — 'System ROM'→bios + UBM 백플레인 'nvme' 선점 정정.
  + firmware[].category/pending field_dictionary 등록 (122 entries). (commit da215d68)
- [x] **cpu.architecture channel (SCHEMA-05)** — `[os,esxi]`→`[redfish,os,esxi]` + `docs/contract/03-fields.md` 동기화. (da215d68)
- [x] **hardware 12 식별필드 field_dictionary 등록 (SCH-1/2, 사용자 승인 — 핵심은 Must)** — vendor/model/
  serial/uuid/bios_version = Must (전 esxi+redfish baseline 보유 실측), 나머지 7 = Nice. (120→134 entries)
- [x] **volumes.total_mb 단위 명명 (RJ-1, 사용자 결정 — total_mb 유지)** — 키/값 유지, "값은 MiB(÷2^20)"를
  field_dictionary + `docs/contract/03-fields.md` 에 문서 명시 (rename/재계산은 계약 breaking이라 회피).

### 잔여 — 실측 필요 (자율 수정 불가)

- [ ] **[MED] HPE baseline 재캡처 (SCHEMA-01/04/06)**: hpe_baseline.json(iLO5 구캡처)에 thermal·network.
  adapters·ports·storage.hbas·multi_node + sections.thermal 누락 — 라이브러리는 정상(faithful), 회귀 커버리지 공백.
  **차단**: 본 검수 환경(Windows)은 ansible control node 미지원(`os.get_blocking` 부재 — 검증함). faithful baseline 은
  Linux control node 또는 lab Jenkins 의 실 site.yml 실행 필요 (rule 13 R4 — AI 임의 편집 금지).
  → **절차**: `_serve_fixtures_as_redfish.py` (TLS 래핑) 로 미러 서빙 → `ansible-playbook redfish-gather/site.yml`
  (REPO_ROOT + vault/<loc>/redfish/hpe.yml + inventory) → json_only 출력을 schema/baseline_v1/hpe_dl380_gen12_baseline.json
  (신 iLO7 baseline, 기존 iLO5 보존) + test_redfish_baseline.py 케이스 추가.

## Round 15 (2026-06-09 멀티에이전트 버그헌트) 후속

> 상세: `round15 bughunt 기록 (삭제됨 — git log 참조)`. 본 cycle 33 fix 적용·검증 완료.
> 아래는 **lab/실행 환경 필요로 보류**한 항목.

| 우선 | 항목 | 분류 | 결정 주체 |
|---|---|---|---|
| MED | 본 cycle os/esxi YAML + Jenkinsfile·_portal 변경 1회 실 ansible/Jenkins **smoke 검증** (본 환경 ansible/Jenkins 부재로 미실측) | `[LAB][CI]` | 사용자+lab |
| MED | windows gather_cpu/memory/network — WMI 빈 응답 시 degraded-data **warning 로깅**(섹션 collected 유지, Linux gather_memory 패턴 일관). additive, Windows lab 후 적용 | `[ANSIBLE][LAB]` | lab |

## Round 16 (2026-06-09 멀티에이전트 버그헌트 — 5 pass 수렴) 후속

> 상세: `round16 bughunt 기록 (삭제됨 — git log 참조)`. 15 fix 적용·검증 완료
> (confirmed 추이 10→1→2→2→0, pass5 CONVERGED). 아래는 lab/하네스 필요로 보류.

| 우선 | 항목 | 분류 | 결정 주체 |
|---|---|---|---|
| MED | 본 cycle os/esxi/redfish YAML 변경 1회 실 ansible-playbook **smoke 검증** (본 환경 CLI 부재 → Jinja2 렌더로만 검증) | `[ANSIBLE][LAB]` | 사용자+lab |
| LOW | vendor `tasks/vendors/*/collect_oem.yml`·`normalize_oem.yml` — 어떤 include 도 없는 **미wiring placeholder**. 내부 `when: _rf_raw_collect.systems`(모듈 미emit 키)라 wiring 시에도 dead. OEM 확장 시 모듈서 raw Oem 보존 + repoint 필요 | `[CONTRACT][LAB]` | 사용자 |
| LOW | Ansible **Jinja 템플릿 회귀 하네스** 도입 — windows cpu/storage/network null-가드 fix 는 Jinja2 직접 렌더로 검증, 영속 회귀는 baseline 의존(null-field fixture 부재) | `[QA]` | qa |

## Round 17 (2026-06-10 멀티에이전트 버그헌트) 후속

> 상세: `round17 bughunt 기록 (삭제됨 — git log 참조)`. 23 confirmed 중 18 적용·검증
> 완료(batch1/2). 아래는 **lab/실행 환경 필요로 보류**(검증 불가 → 정직 보고).

| 우선 | 항목 | 분류 | 결정 주체 |
|---|---|---|---|
| MED | **vendor OEM 추출 cluster (#13~#17)** — huawei/inspur/fujitsu/quanta/hpe-superdome `collect_oem.yml` 이 `_rf_raw_collect.systems[0]`(모듈 미emit) 또는 `data.system.Oem`(대문자, 실제는 소문자 `data.system.oem`)·`data.chassis`(미존재) 를 읽어 **항상 빈 OEM**. wiring 됨(adapter `oem_tasks`)이나 dead. graceful(crash/envelope 위반 없음). 진짜 fix = ① huawei/inspur/fujitsu/quanta 를 `_OEM_EXTRACTORS` 에 추가(라이브러리) + ② raw Oem 보존 또는 path repoint(`data.system.oem`) + ③ 사이트 fixture. 4종 lab 부재라 추출기 추가해도 검증 불가 → 사이트 fixture 선행 필요 | `[CONTRACT][LAB]` | 사용자+lab |
| MED | 본 cycle os/esxi/redfish/precheck **YAML + Jenkinsfile_portal 변경 1회 실 ansible-playbook/Jenkins smoke 검증** (본 환경 ansible/Jenkins 부재 → Jinja2 렌더 + pytest 로만 검증). 대상: gather_runtime/gather_system(#6/#7/#19/#20), esxi/os site.yml adapter 선택(#9/#10), run_precheck(#4), try_one_credential(#2/#21), Jenkinsfile_portal Stage3(#23) | `[ANSIBLE][CI][LAB]` | 사용자+lab |
| LOW | **precheck timeout 동작 변경 확인** — `_precheck_timeout`(redfish=_rf_timeout, esxi=30) 이 이제 protocol/auth 에 반영(기존 15/8 → 30). 느린 BMC false-negative 해소하나 실패 호스트 precheck 시간 증가. 운영 배치에서 허용 가능 확인 | `[LAB]` | 사용자 |
| LOW | cisco `collect_oem.yml` 도 `data.system.Oem`(대문자) 읽어 supplement dead — 단 cisco 는 `_OEM_EXTRACTORS` 라 라이브러리가 `data.system.oem`(소문자) 채움(부분 동작). lab 후 path 정정 + 회귀 | `[CONTRACT][LAB]` | lab |

### Round 18 재스캔 후속 (R17 수정 회귀검수 — 4 confirmed 중 2 적용, 2 보류)

> R18-1(회귀: _normalize_port_speed inf/nan crash) + R18-2(Windows runtime rescue clobber) 적용·검증 완료.
> 아래 2건은 LOW + 선재(pre-existing) + 실측/lab 검증 필요로 보류 (verification.md — 검증 불가 변경 자제).

| 우선 | 항목 | 분류 | 결정 주체 |
|---|---|---|---|
| LOW | **runtime dual-collector success-path clobber (R18-3)** — gather_runtime(Linux+Windows) 가 success 경로에서도 gather_system 의 더 견고한 runtime(chronyd loop / nftables / systemctl firewall / become:true)을 inferior 값으로 덮음. 선재(F5 commit f2ccea36). 근본 fix = gather_runtime 의 runtime 생산 제거(gather_system 단일 정본화) — site.yml include 제거 + 파일 삭제. 구조 변경이라 실 ansible smoke 후 적용 권장 | `[ANSIBLE][LAB]` | 사용자+lab |
| DONE | ~~**network.interfaces[].link_status enum drift (R18-4)**~~ — **해결 cycle 2026-06-14** (branch feature/r740-audit-fixes). field_dictionary enum→`up/down/unknown` 통일 + 3채널 코드 통일(os-linux/os-windows/esxi-interfaces+adapters+hbas; redfish 기존 canonical) + dell/hpe/lenovo baseline `network.interfaces[].link_status` 결정론적 마이그레이션(linkup→up 등; hpe/lenovo 미러 replay 로 코드 출력 일치 검증) + `docs/contract/03-fields.md`+`docs/contract/02-output-envelope.md`+예시/fixture. **잔여(lab)**: 전 baseline 의 link_status 외 필드 stale 가능 → 실장비 full 재캡처 권장(rule 13 R4) | `[SCHEMA][LAB]` | 사용자+lab |

## 0. 2026-05-29 audit-cleanup 후속 (전수 audit 결과 — 미적용 backlog)

> 정본: `docs/ai/contracts/account-write-vendor-compat.md` (전체 권고 + 정확 file:line + diff).

| 우선 | 항목 | 분류 | 결정 주체 |
|---|---|---|---|
| **[CRIT]** | vault 마스터 암호(`__REDACTED__`) + 자격 회전 + (선택) git 히스토리 purge | 보안 | **사용자** — `docs/ai/policy/SECRET-ROTATION-RUNBOOK.md` |
| **[HIGH]** | BMC/AD lockout 회피 (detect 선인증 4-GET / OS backoff 부재 / account_service dryrun=false) | `[AUTH][LAB]` | 사용자+lab — AUDIT §1 |
| MED | esxi vendor 정규화 substring fallback 누락 (`vendor` 필드 divergence 버그) | `[ANSIBLE]` | AUDIT §4 AR-1 |
| MED | perf: CSUS 대표 partition 2회 fetch / firmware fetch-then-discard / SSL ctx 재생성 | `[LAB]` | AUDIT §2 |
| MED | refactor: `account_service_provision` 381줄 분할 / HTTP verb 통합 / status 문자열매칭→숫자 | `[AUTH][CONTRACT]` | AUDIT §3 |
| LOW | JEDEC 테이블 단일화 / registry.yml 문서 명확화 / build_output 명명 / vendor debug dead var | `[ANSIBLE]` | AUDIT §4 |

> 본 cycle 미적용 사유: 본 환경에 **ansible-playbook CLI 부재**(playbook syntax/런타임 검증 불가) + 일부는 **실장비/인증 동작** 변경 (사용자 "운영 깨지면 안됨, 특히 인증"). ansible YAML 적용은 Jenkins agent(ansible-playbook+lab) 에서 검증 후.
>
> **2026-06-04 환경 정정**: ansible **라이브러리** 2.19.9 는 설치되어 있어 (`import ansible` OK) Python 모듈/필터/플러그인은 **pytest 로 로컬 검증 가능** (704 pass). 단 `ansible-playbook` **CLI 는 PATH 부재**(rc=127) — playbook syntax-check/런타임은 여전히 Jenkins Agent 위임. 따라서 §0 의 `[ANSIBLE]` 태그 항목(YAML/playbook 변경)은 계속 보류, Python-only 항목(R-4 등)은 본 환경에서 진행 가능.

### 0.9 (2026-06-09 견고화 사이클) merge_fragment 가드 Jenkins 통합 검증 [PENDING — Jenkins Agent]

- **항목**: `common/tasks/normalize/merge_fragment.yml` 의 data 병합 concat 분기 `is not mapping` 가드(커밋 `6378453`) — list↔dict 오염 시 `bv+fv` TypeError 를 else(fv 우선)로 graceful 강등.
- **로컬 검증 완료([OK])**: 실 YAML 식을 추출해 Jinja2 로 렌더(`tests/unit/test_merge_fragment_render.py` 5건) — 정상 list+list concat 불변 + 오염 list↔dict graceful 확인.
- **잔여(Jenkins)**: 전체 ansible set_fact 통합(실 `union` 필터 + `no_log` + 3-채널 gather 흐름)에서 회귀 0 확인. 분류 `[ANSIBLE]`. 정상 입력 결과 불변이라 위험 낮음(Additive).

### 0.11 (2026-06-09 적대적 robustness 루프 R1~R14 수렴) 잔여

> 14 라운드 수렴 완료(genuine 0). 아래는 의도적 보류:
- **[CONTRACT 결정대기]** SimpleStorage empty-bay 필터링 방향 (dmtf golden 빈베이 포함) — 사용자 설계 결정 (R1 #12).
- **[ANSIBLE/Jenkins]** OS/ESXi YAML 가드(merge_fragment list+dict / normalize_storage·system | string·default) — Jinja2 렌더 검증 완료, 전체 ansible 통합은 Jenkins Agent.
- **[INFRA]** gitlab(10.100.64.156) push — 네트워크 미도달, 연결 환경서 `git push origin main`. e2e_browser(10.100.64.152 Jenkins master)도 도달 환경 재실행.
- **[CONSISTENCY]** link_speed_gbps 채널간 타입(redfish float vs OS/ESXi int) — redfish float이 정확(fractional Gbps), CSUS mock baseline int은 실데이터로 교체 시 정정. 통일 시 OS/ESXi를 float로(int cast 제거) — 별도 cycle.

### 0.10 (2026-06-09 Round 1 멀티에이전트 hunt) 미적용/결정대기 항목

> Round 1 = 9 finder + 3-lens 적대적 검증 → 26 confirmed. 24건 수정 완료(커밋 cc39beb~0f5e45e).
> 아래 2건만 미적용:

- **[CONTRACT 결정대기] #12 SimpleStorage empty-bay 필터링**: 표준 storage 경로(`_extract_storage_drives`)는 빈 베이(cap 0/null)를 필터링하는데, SimpleStorage(`_gather_simple_storage`)는 안 함 → cross-path 불일치. **그러나** dmtf golden 이 빈 베이(SATA Bay 3, 전 필드 null)를 **포함**하고 있어 필터링 적용 시 golden 변경 + envelope 계약 변경(빈 베이 노출 여부). **방향(필터 vs null 포함)은 설계/사용자 결정 필요** — DSP2043 mockup 은 의도적으로 빈 베이를 모델링. 결정 시 golden 재생성 필요.
- **[WONTFIX] #14 PowerSubsystem watt float 보존**: EnvironmentMetrics PowerWatts.Reading 가 float(12.5W) 가능하나 `_safe_int` 가 truncate. **의도적 유지** — /Power 경로(golden)는 watt 를 int 로 emit 하므로 PowerSubsystem 도 int 로 통일해야 envelope 타입 일관(rule 13). 소수 watt 는 운영상 무의미. #21 에서 두 경로 모두 int 통일.
- **[INFO] #7 Dell PATCH 3-slot 제한**: 의도된 동작(코드 주석 'up to 3'). 버그 아님 — account_service_provision 은 빈 슬롯 최대 3개만 시도. 향후 커버리지 테스트 추가 권장(코드 변경 불요).

---

## 0.5 HP CSUS 3200 사이트 사고 후속 — Bug C 잔여 [PENDING — 실 envelope 필요]

> 2026-06-04 사이트 사고. A1/B1/B2 + cpu.model fallback 적용·검증 완료 (ADR-2026-06-04-csus-adapter-priority §8).
> web hunt 로 HPE `sdflexutils` 실 캡처 JSON 확보·검증 → Bug C 근본 원인 확정 + 대부분 기존 코드로 이미 처리됨 판명.

**확정 (web 실측 — sdflexutils root.json/system.json)**: Superdome/CSUS partition System 은 Manufacturer/Model 부재 + Processors/Memory/Storage/EthernetInterfaces drill-in **부재**, ProcessorSummary/MemorySummary 만 존재.

| 항목 | 상태 | 비고 |
|---|---|---|
| cpu.sockets/cores/threads, memory.total | [OK] 기존 BUG-13/14 fallback 으로 이미 summary 채움 | 추가 작업 불요 |
| cpu.model | [OK] 2026-06-04 fallback 추가 (normalize_standard.yml L483) | jinja2 render 검증 |
| data.multi_node (전 partition 상세) | [OK] B2 가 CSUS adapter 선택 → manager_layout → 수집 활성 (구 ilo6 오선택 시 null 이었음) | 실 장비 확인 권장 |
| **memory.slots / storage.physical_disks / network.interfaces 의 top-level 상세** | [WARN] partition System drill-in 부재라 summary 대체 불가. multi_node/Chassis 에 있을 수 있음 | **실 envelope 필요** — 사용자 newer 펌웨어가 drill-in 노출하는지 확인 |
| **실 envelope/raw JSON 1회 캡처** | trigger 충족 | 사용자 — 가장 정확. `capture-site-fixture`, sanitize 후 fixture |
| 실 baseline 교체 (현 MOCK) | 보류 (rule 96 R1-C) | 사용자 실측 후 (rule 13 R4) |
| **end-to-end 확인** (vendor=hpCsus + hardware + cpu.model + multi_node 채워짐) | [NG] 이 환경 확인 불가 | 사용자 사이트 재실행 |

> 전신(Superdome Flex 280) 캡처는 ServiceRoot.Product 부재였으나 **사용자 CSUS 는 노출** = 신 펌웨어. 사용자 장비가 정본(rule 25 R7-A-1) — 실 envelope 으로 잔여 null 필드 확정 필요.

---

## 0.7 DMTF 표준 mockup 오프라인 회귀 후속 (2026-06-08 — rackmount1 편입 후)

> 2026-06-08 DMTF `public-rackmount1`(DSP2043, BSD-3)을 표준 경로 오프라인 fixture 로 편입 완료(`tests/fixtures/redfish/dmtf_rackmount1/`). 아래는 그 후속 후보.

| # | 항목 | 분류 | trigger / 차단 | 결정 주체 |
|---|---|---|---|---|
| D1 | 2nd mockup **local-storage(1821)** 편입 — modern Storage/Drives/Volumes 표준 순수 데이터 회귀(현 fixture 는 SimpleStorage 만 커버) | `[FIXTURE]` | **DSP2043 번들 다운로드 차단**(dmtf.org 403 / Wayback 503/404). 사용자 망/수동 zip 또는 번들 미러 확보 시 `convert_dmtf_mockup.py` 로 즉시 편입 | 사용자(번들 확보) |
| D2 | 2nd mockup **bladed(1820)** 편입 | `[FIXTURE]` | 동일 번들 차단 + **본 라이브러리 하네스에서 multi_node 미활성**(manager_layout=None → `_collect_multi_node_topology`=None). 가치 재평가 필요 — 편입해도 first-member 단일 수집(rackmount 대비 한계 marginal) | 사용자 |
| D3 | **storage fallback 분류 재검토** — SimpleStorage/SmartStorage fallback 성공 시 storage 를 `failed` 대신 degraded/collected 로 분류 (FAILURE_PATTERNS 2026-06-08) | `[CONTRACT]` | status 의미론 변경(rule 13 R8 — 4-시나리오 매트릭스 + docs/19/20 + 영향 vendor fixture 동반) + 호출자 계약 영향. HPE iLO4 SmartStorage 포함 전 fallback 영향 | **사용자** — rule 13 R8 승인 필요 |
| D4 | **신규 섹션** Thermal/ThermalSubsystem(1828) / Cables(1835) / CXL(1839) / CDU(1840) — DMTF 미수집 리소스 | `[SCHEMA]` | schema 버전 변경(rule 13 R3) + 실장비 baseline + 사용자 명시 승인. mockup URL = web sources(rule 96 R1-A) | **사용자** — rule 13 R3 |

> D1/D2 진입 절차: DSP2043 zip 확보 → `public-<name>/` 추출 → `python tests/integration/convert_dmtf_mockup.py --mockup-dir <경로> --name dmtf_<name> ...` → golden 비판적 리뷰(rule 95 R3) → pytest.

---

## 0.8 AR-1 esxi vendor 정규화 substring fallback — [PARTIAL] (Jenkins Agent 후속)

> AUDIT-2026-05-29 AR-1. **실 버그**: `vendor` envelope 필드 채널 divergence.
> 2026-06-08 — redfish reference 측 단위 테스트 고정 완료(`tests/unit/test_vendor_normalize_aliases.py` 16 케이스). esxi YAML 수정은 **이 환경에서 미적용**(ansible-playbook CLI = Windows POSIX-only 미동작 / yamllint 부재 / rule §0 `[ANSIBLE]` defer 정책 / "운영 깨지면 안됨").

**근본 원인** (실측):
- redfish `_normalize_vendor_from_aliases`(:467): 정확매칭 → **substring fallback** → 'unknown'.
- esxi inline Jinja2(`esxi-gather/site.yml:162-175`): **정확매칭만**, substring 없음, default=raw.
- 결과: "Dell Inc"(마침표 없음) → redfish='dell' ↔ esxi=raw('Dell Inc'). vendor 필드 불일치.

**Jenkins Agent 적용 recipe** (택1, 적용 후 esxi baseline 회귀로 검증 — rule 40):
- **(권장) 공유 filter**: `filter_plugins/normalize_vendor.py` 신설(redfish `_normalize_vendor_from_aliases` 로직 mirror — jedec_mapper.py 패턴) → esxi `_e_vendor_normalized` 를 `{{ (_e_raw_facts.ansible_system_vendor | default('')) | trim | lower | normalize_vendor(_e_vendor_aliases_map) }}` 로 교체(14줄 fragile Jinja2 제거). + JEDEC 식 redfish↔filter parity 가드 test 추가.
- **(최소 diff) inline 확장**: 현 Jinja2 loop 뒤에 substring pass 추가(`{%- if a|lower in raw_lower or raw_lower in a|lower -%}`) + default `none`→`'unknown'`.
- **주의**: default 를 raw→'unknown' 로 바꾸면 미지 vendor 의 esxi `vendor` 값이 변함 → esxi baseline 영향 가능(VMware 는 alias 매칭이라 무영향 예상). baseline 재검증 의무.
- 기준선: redfish 동작 = `test_vendor_normalize_aliases.py`. esxi 수정 후 동일 입력 동일 canonical 이어야 함.

---

## 1. AI 환경에서 즉시 가능 — F6 OS baseline expansion (사용자 access 제공 완료)

| 항목 | 상태 | 진입 |
|---|---|---|
| rhel920 / rhel960 / rocky960 baseline 3건 신설 | **trigger 충족** (사용자 IP 제공 2026-05-11) | handoff 문서(정리됨) cold-start |

- 3 IP: 10.100.64.163 / 10.100.64.165 / 10.100.64.169
- F5 system.runtime 9 필드 빌더 실측 검증 포함
- Jenkins Agent 환경 필요 (ansible-playbook 실 수집)

---

## 2. 외부 trigger 대기 PENDING (lab / 사이트 / 운영 환경)

### 2.1 baseline 확장 (lab 도입 시)

| # | 항목 | trigger |
|---|---|---|
| F3 | Supermicro baseline | 사이트 BMC IP 확보 |
| F4 | Windows + 베어메탈 OS baseline | winrm/sudo 환경 도입 |

각 진입 시: `update-vendor-baseline` skill + rule 13 R4 절차.

### 2.2 HPE CSUS 3200 / Superdome Flex RMC (lab 부재)

- **trigger**: RMC IP 확보 + Redfish 활성화 (`docs/operate/06-rmc-activation.md` 4 절)
- **상세 8 항목 (C1~C8)**: `docs/ai/catalogs/LAB_PENDING_MATRIX.md` HPE 행
- **handoff 후보 A**: handoff 문서(정리됨) "후보 A — HPE CSUS 3200 lab 검증"
- **ADR**: `docs/ai/decisions/ADR-2026-05-12-csus-rmc-multi-node.md`, `ADR-2026-05-29-hba-ib-csus.md`
- **cycle 2026-05-29 (hba-ib-csus)**: baseline 을 전 공통 섹션 realistic mock 으로 채움 (FC HBA + RAID1 SATA + DDR5 + 3 partition canonical). 여전히 **mock** — C1 사이트 fixture 캡처 후 실 baseline 으로 교체 의무 ("검증됨" 주장 금지 — rule 25 R7-B).
- **2026-06-08 에뮬레이터 범위 명시**: HPE 공식 iLO 에뮬레이터는 **CSUS/Superdome mockup 부재** → 본 항목(CSUS/Superdome)은 에뮬레이터로 못 메움. 실장비/사이트 fixture 가 유일 경로. (에뮬레이터는 iLO5/iLO6/Gen12 ProLiant 만 — `tests/integration/test_hpe_emulator_replay.py` 오프라인 회귀로 별도 커버.)
- **cycle 2026-06-09 (ADR-2026-06-09)**: CSUS 3200 Redfish 모델 검수 → 누락 5종 (boot / thermal / log_services / composition(ResourceBlocks) / fabrics(FlexGrid)) Additive 구현 + mock fixture/baseline/테스트. 여전히 **mock** — 아래 C9~C14 사이트 실측 정정 의무 (rule 96 R1-C):
  - **C9**: CompositionService/ResourceBlock 실 schema (RB↔chassis 매핑 / Processors·Memory 표현)
  - **C10**: Fabrics/FlexGrid 실 FabricType (NUMAlink 표기) / Switch.SwitchType / Endpoint.EndpointProtocol
  - **C11**: Chassis Thermal 실 sensor 명 / `/Thermal` vs `/ThermalSubsystem` 펌웨어 분기
  - **C12**: RMC LogServices 실 ID (IML/IEL 추정) / OverWritePolicy
  - **C13**: per-partition `Boot.BootOrder` 실 표현
  - **C14**: (최적화) `gather_boot` / `gather_manager_logs` 재-GET 제거 — `gather_system`/`gather_bmc` raw 재사용 (현재 partition/manager 당 1회 추가 round-trip)

### 2.4 HBA / InfiniBand 사이트 fixture (lab 부재 — cycle 2026-05-29)

- **trigger**: FC HBA / IB HCA 보유 사이트 BMC/OS/ESXi 접근
- **항목**:
  - FC HBA 보유 Dell/HPE/Lenovo/Cisco BMC → Redfish `storage.hbas` 실측 fixture + baseline (현 4 redfish baseline 은 FC 미보유로 빈)
  - FC HBA 보유 Windows/Linux 호스트 → `Get-InitiatorPort`+`MSFC_*` / sysfs 실측 (현 ubuntu/windows/rhel baseline 빈)
  - IB HCA (Mellanox/NVIDIA) 보유 호스트 → Linux ibstat/sysfs 실측 (IB 정본 채널)
  - ESXi FC SAN 호스트 → vmhba FC speed/wwnn 실측 (현 esxi_baseline 은 offline FC 2)
- **ESXi esxcli-over-SSH fallback (D1-B 재평가)**: SSH 활성 운영·보안 결정 시 `esxcli storage san fc list` / `rdma device list` 보강
- **절차**: `capture-site-fixture` skill + rule 13 R4 (실측 baseline) + EXTERNAL-CONTRACTS 갱신

### 2.5 에뮬레이터 하네스 CI 편입 [DONE 2026-06-08 — agent 검증만 대기]

- **상태**: 사용자 승인(2026-06-08) 후 구현 완료. Jenkins Stage 4(E2E Regression)가 e2e 회귀 + `tests/integration/ -m "not live"`(HPE 에뮬레이터 오프라인 회귀)를 별도 invocation 으로 실행, 둘 중 하나라도 FAIL 시 stage 실패. 동반 갱신(`docs/operate/04-pipeline-runtime.md` / rule 80 R1-A / JENKINS_PIPELINES) 완료.
- **구현 노트**: tests/e2e 와 tests/integration 이 둘 다 top-level `conftest` module 을 써서 단일 멀티-디렉터리 호출 시 ImportError → **별도 pytest 호출 + RC 합산**으로 해결 (Jenkinsfile L217-231). integration conftest 의 전역 `sys.path.insert` 도 제거(e2e conftest shadow 방지).
- **잔여 ([WARN] AI 환경 밖)**: 실제 Jenkins agent 에서 1회 green 확인 — `/opt/ansible-env` venv 가 redfish_gather(stdlib + ansible stub) import 가능한지. 로컬에선 동일 셸 로직 시뮬레이션 PASS(e2e 157 + integration 44, FINAL_RC=0) 확인했으나 **실 agent 실행은 미확인**. 첫 빌드 모니터링 필요.

### 2.3 8 vendor × generation 후속 매트릭스

→ `docs/ai/catalogs/LAB_PENDING_MATRIX.md` 정본 참조.

진행 가능한 generation 우선:
- Dell iDRAC8 / iDRAC9 (lab 미도입)
- HPE iLO5 / iLO6 / Superdome Flex
- Lenovo IMM2 / XCC / XCC2
- Cisco CIMC M5~M8 / UCS S-series
- Supermicro 전체 generation (사이트 BMC 0대)
- Huawei / Inspur / Fujitsu / Quanta 전체 (lab 부재)

---

## 3. 운영 / 보안 추적 (사용자 결정 대기)

위 archive 의 OPS-* 잔여 항목 trigger 발생 시 archive 에서 본 파일로 복원:

| 카테고리 | 추적 위치 |
|---|---|
| 보안 회전 (__REDACTED__ / vault) | archive OPS-AUDIT-1 / OPS-DELL-VAULT-1 |
| 운영팀 결정 (vault timing / repo private / dryrun OFF) | archive OPS-3 / OPS-5 / OPS-9 |
| 실 hardware 점검 (Lenovo PSU1) | archive OPS-LENOVO-PSU1 |
| WinRM / Win Server 2022 안정성 | archive AI-22 reopen / OPS-RESIDUAL-1 |
| baseline 재수집 (HPE iLO6 / Cisco / Dell) | archive OPS-HPE-REVIEW-1/2 / OPS-CISCO-REVIEW-1/2 |

---

## 4. 정기 추적 (분기 / 연간)

| 항목 | 주기 | 정본 |
|---|---|---|
| DMTF Redfish release 매트릭스 | 분기 | `EXTERNAL_CONTRACTS.md` |
| vendor EOL / CVE / errata | 분기 | `EXTERNAL_CONTRACTS.md` |
| community.vmware collection 업그레이드 | 연간 | `REQUIREMENTS.md` |
| 펌웨어 매트릭스 drift | TTL 90일 (rule 28 R1 #11) | adapter origin 주석 |
| COMPATIBILITY-MATRIX | TTL 14일 (rule 28 R1 #12) | `COMPATIBILITY-MATRIX.md` |
| LAB_PENDING_MATRIX | TTL 14일 (rule 28 R1 #12 와 동일) | `LAB_PENDING_MATRIX.md` |

---

## 5. AI 자율 진행 가능 (lab 없이 즉시)

| 작업 | skill / agent |
|---|---|
| harness 자기개선 cycle | `/harness-cycle` (6단계 파이프라인) |
| rule 28 측정 11종 drift 검사 | `measure-reality-snapshot` skill |
| repo 정리 (죽은 코드 / 중복 / archive 후보) | `repo-hygiene-planner` agent |
| handoff 문서(정리됨) 후보 B/C/D | handoff 후보 참조 |

---

## 6. repo-hygiene 후보 (2026-06-04 스캔 — 실측 검증됨, 미적용 / 계획만)

> D 작업: read-only 스캔 + 실측 참조 카운트 검증 (rule 25 R7-A). 제거/archive 는 사용자 결정 대기 (수정 안 함).

| 우선 | 후보 | 검증 결과 | 권고 |
|---|---|---|---|
| **[HIGH]** | `scripts/ai/bug_tracker/verify_all_tickets.py` | 외부 참조 **0건**, `verify_v2.py` 로 대체 (v1 field 명명 오류 수정본) | 삭제 또는 `scripts/ai/archive/one_off/` |
| MED | `esxi-gather/tasks/normalize_sections.yml` | esxi-gather 내 include 참조 **0건**, deprecated 쉼 (의도적 no-op) | archive 또는 삭제 (rule 70 R6) |
| LOW | `scripts/ai/bug_tracker/capture_raw_redfish.py` | 참조 **2건** (문서 — 완전 dead 아님), 2026-04-29 ticket cycle one-off | archive 후보 (sister: generate_tickets/verify_v2) |
| LOW | `module_utils/adapter_common.py::_flatten_aliases` | 1회 호출 (line 79, dead 아님 — inline 후보) | 저우선 cleanup |
| 중복 | JEDEC 매핑 (`jedec_mapper.py` ↔ `_JEDEC_VENDORS`) | 2026-06-04 **drift-guard 테스트로 보호** (`test_jedec_drift_guard.py`) | 통합 대신 가드 유지 (rule 10 stdlib 제약상 통합 비용 큼) |
| 중복 | HTTP/SSL 유틸 3중 (`precheck_bundle.py` / `redfish_gather.py` / `capture_raw_redfish.py`) | `_ctx`/`_auth`/`_get` 등 재구현 | `module_utils/` 공유 모듈 통합 — 별도 cycle (rule 10 stdlib 준수 + 회귀 큼) |

---

## 2026-06-17 — OS gather 후속 (빌드 #30 SUCCESS 후)

| 우선 | 항목 | 사유 | 결정 주체 |
|---|---|---|---|
| HIGH | `vault/<loc>/os/linux.yml` primary 계정 교정 | 현재 primary=`infra/__REDACTED__` (161/165에서 인증 실패 → 매 host가 secondary fallback에 의존). 실 동작 계정은 `cloviradmin/__REDACTED__`(secondary). primary를 실 계정으로 교체하면 host당 1차 인증실패 지연 제거. 사용자가 기대한 `admin` 계정은 vault에 부재 | **사용자** (vault 보호경로 + rule 50/27, "적용하지말고" 지시) |
| MED | `json_only` unreachable/failed stderr 표면화 | 현재 OUTPUT 외 실패 전부 suppress → 사고 시 콘솔 무정보(이번 진단 난항의 근본). non-OUTPUT failed/unreachable을 stderr 구조화 출력(no_log 존중, stdout 계약 불변) | AI 가능(additive) — 승인 시 진행 |
| LOW | `accounts` 빈 배열 edge case | accounts 비면 `abort if all credentials failed` skip → 본 gather task에서 unreachable 재발 가능 | AI 가능 — 별도 검토 |

---

## 관련

- rule: `70-docs-and-evidence-policy` R5 / R6 / R7 (보존 / archive / cycle 자문)
- catalog: `LAB_PENDING_MATRIX.md`, `COMPATIBILITY-MATRIX.md`, `VENDOR_ADAPTERS.md`, `EXTERNAL_CONTRACTS.md`
- archive: 아카이브(정리됨)
- handoff: handoff 문서(정리됨) (F6), handoff 문서(정리됨) (4 후보)
- ADR: `docs/ai/decisions/ADR-2026-05-12-csus-rmc-multi-node.md`

## Linux baseline 재캡처 발견 (2026-06-22, 161/166 접속)

- [x] **[DONE] rhel810 baseline controllers/adapters 반영** (161 실측, commit `a0e29cff`).
- [ ] **[발견/사용자] ubuntu_baseline host(166) OS 변경**: 166 이 Ubuntu 24.04 → **RHEL 9.6 으로 재설치됨**.
  ubuntu_baseline 출처 호스트가 OS 가 바뀌어 166 에서 ubuntu 재캡처 불가. 다른 Ubuntu 호스트(119=virtio VM / 96=baremetal) 결정 필요.
- [ ] **[발견/설계] OS-on-VM vendor 불일치**: 실 gather 가 `vendor="vmware"`(161/120) 산출하나, 설계 의도(CANONICAL_VENDORS 주석
  "OS channel can be null vendor-agnostic") + 기존 baseline 은 `None`. → OS vendor 를 None 으로 둘지 vmware 식별 유지할지 결정.
- [ ] **[발견/cleanup] rhel810 baseline gather_mode="raw_only" 는 stale**: 코드 실 값은 `python_incompatible`
  (preflight.yml: python_ok/python_missing/python_incompatible/raw_forced — "raw_only" 부재). baseline + test 가 가짜 값 단정 중.

## OS vendor canonical 정정 + 후속 발견 (2026-06-22)

- [x] **[DONE] OS 하이퍼바이저 vendor canonical 인정**: CANONICAL_VENDORS 에 vmware/qemu/microsoft/xen 추가
  (os-gather _out_vendor 가 DMI sys_vendor 를 매핑하는 정상값). rhel810 baseline 161 full 재캡처(vendor=vmware,
  gather_mode=python_incompatible — stale raw_only/None 제거). commit `3245004a`.
- [x] **[DONE 2026-06-22] Ubuntu 어댑터 미선택 버그 수정** (commit `826c6513`): 원인=어댑터 선택이 distribution 감지 전
  실행 → ansible_distribution='' → priority 50 동률 rhel tie-break. 수정=preflight 가 /etc/os-release NAME 감지(_l_distro_name)
  → 167 실측 os_linux_ubuntu 정상. **(구)조사 메모:** 119(Ubuntu 24.04)가 `adapter_id=os_linux_rhel` 로 잡힘.
  `adapters/os/linux_ubuntu.yml`(distribution_patterns ["Ubuntu","Debian"], priority=50)가 존재하는데 미선택.
  옛 ubuntu_baseline(166)은 os_linux_generic 이었음 → **Ubuntu 가 linux_ubuntu 로 매칭된 적 없음**.
  adapter_loader 의 distribution_patterns 매칭 또는 OS distribution 값 비교 로직 조사 필요. (gather 자체는 success — adapter_id 라벨만 오선택.)
- [x] **[DONE 2026-06-22] ubuntu_baseline 167 재캡처** (commit `c90e784a`): 167(새 Ubuntu VM) os_linux_ubuntu/vendor=vmware/
  controllers/adapters 실값. test_adapter_id os_linux_generic→os_linux_ubuntu. **(구)보류 메모:** 166(원 host) 이 RHEL 9.6 로 OS 변경 + 119 는 os_linux_rhel 로 잡혀
  os_linux_generic Ubuntu 캡처 불가. 위 Ubuntu 어댑터 버그 해결 후 재캡처 가능. (현 ubuntu_baseline vendor=None 은
  canonical 유효라 회귀는 통과 — 우선순위 낮음.)

## errors[].message 계약 개선 후속 (2026-08-12)

정본 기록: `tests/evidence/2026-08-12-errors-message-contract.md`.
아래는 이번 범위에서 **의도적으로 제외**한 것들이다. 사유를 함께 남긴다.

### A. Result Delivery — 이번 범위 밖 (errors.message 품질 문제가 아니라 결과 전달 문제)

envelope 과 `errors[].message` 는 정상 생성됐는데 **Portal 이 아예 받지 못하는** 경로다.
사용자 지시(§11)에 따라 별도 Backlog 로 분리한다.

- [ ] **[Jenkins] Validate stage 실패 → Callback 미실행** — `Jenkinsfile_portal:65~108` 의 `error` step 10곳.
  Declarative stage 는 순차 실행이고 Validate 에 `catchError` 가 없어 즉시 FAILURE 로 끝난다 →
  Stage 4 'Callback' 이 실행되지 않아 Portal 수신 0건. 호출자는 Jenkins build 실패만 관측한다.
- [ ] **[Jenkins] `gather_output.json` 0바이트 → abort** — `Jenkinsfile_portal:183`.
  이 `error` 는 `catchError`(:152-177) **바깥**이라 UNSTABLE 로 흡수되지 않는다.
- [ ] **[Jenkins] Validate Schema 실패 → Callback 통째 취소** — `Jenkinsfile_portal:201-223`.
  gather 는 성공했고 message 도 이미 만들어졌는데 field_dictionary 정합 실패(help_ko 누락 등
  **errors 와 무관한 이유** 포함)로 전달이 취소된다.
- [ ] **[Jenkins] httpRequest 3회 실패 → UNSTABLE + 재전송 큐 없음** — `Jenkinsfile_portal:281,324,330`.
  `post { always { deleteDir() } }` 로 워크스페이스까지 지워져 수동 재전송도 불가.
- [ ] **[Jenkins] stage timeout ABORTED → 대체 envelope 없음** — `Jenkinsfile_portal:43,58,126,209,231`.
- [ ] **[inventory] `inventory.sh` 가 IP 검증 실패 시 `sys.exit(1)`** — play 자체가 시작되지 않아
  envelope 이 0개다 (os-gather/inventory.sh:31-33, redfish-gather/inventory.sh:32-34).

### B. status 판정이 바뀌는 변경 — 사용자 승인 필요

- [ ] **Windows partial 구조 도입** — 현재 Windows 는 `status=partial` 이 **구조적으로 발생하지 않는다**.
  8개 gather 중 6개가 `_sections_failed_fragment: []` 를 무조건 set 하고, 유일한 실패 표기였던
  `system_runtime` 은 build_sections 의 11섹션 루프에 없어 no-op 이었다(이번에 `[]` 로 정리 — 동작 불변).
  각 gather 가 원천 rc/결과로 실측 판정하게 바꾸면 지금까지 success 로 보고되던 호스트가 partial 이 된다
  → Portal 지표가 즉시 변한다. baseline 회귀 + 승인 필요.
- [ ] **OS users 섹션 unsupported 강등(N14)** — 수집 실패가 `not_supported` 로 조용히 강등된다.
  F23 결정(노이즈 차단)과 충돌해 판단 보류.
- [ ] **ESXi 확장 수집 실패 임계(NEW-1) / firewall_state null 판정(NEW-2)** — 실장비 없이 오탐 위험.
  `collect_network_extended` 4개 모듈 전부 실패, `collect_runtime` 의 firewall_state null 을
  실패로 볼지 정상 미설정으로 볼지 실 vCenter 확인 필요.

### C. 기능 버그 (message 품질과 무관 — 이번 작업에서 고치지 않음)

- [ ] **[ESXi 데이터 유실] `collect_runtime.yml:161` 의 하드코딩 `listening_ports: []`** 가
  `esxi_disks` 수집분을 덮어쓴다. `normalize_system.yml:33` 이 실값을 넣은 **뒤**
  `collect_runtime` 이 같은 `system.runtime` fragment 를 다시 만들면서 빈 list 를 싣고,
  `merge_fragment.yml` 의 dict 병합은 `[]` 도 not-none 이라 나중 값이 이긴다.
  → `data.system.runtime.listening_ports` 가 **항상 `[]`** 로 나간다.
  같은 파일이 `default_gateways` 에는 이미 "빈 list 면 키 제외" 회피를 넣어 뒀다.

### D. 실장비 검증 (AI 환경에서 불가)

- [ ] `ansible-playbook --syntax-check` 3채널 (이 환경에 ansible 미설치)
- [ ] Redfish 표준 계정 복구(P0-6) 실장비 dry-run → 실제 write 검증
- [ ] Portal 화면에서 실제 문장 확인 (partial 케이스 포함)
- [ ] `TCP_CONNECTION_REFUSED` 실환경 재현 → 2번 문장 노출 확인

### C-2. Redfish vendor OEM merge_fragment 경로 (적대적 검수 2026-08-12 발견, HIGH)

- [ ] **[기능 버그 / pre-existing] vendor OEM 6곳이 존재하지 않는 경로로 merge_fragment 를 include 한다.**
  - 위치: `redfish-gather/tasks/vendors/cisco/collect_oem.yml`, `huawei/collect_oem.yml`,
    `inspur/collect_oem.yml`, `fujitsu/normalize_oem.yml`, `hpe/normalize_oem.yml`,
    `quanta/normalize_oem.yml` — 전부 `{{ playbook_dir }}/common/tasks/normalize/merge_fragment.yml`.
  - redfish 채널의 `playbook_dir` 는 `${WORKSPACE}/redfish-gather` 이고 **`redfish-gather/common/`
    디렉터리는 존재하지 않는다** (`ls redfish-gather/` → inventory.sh / library / site.yml / tasks 뿐).
    저장소의 다른 모든 호출부는 `{{ lookup('env','REPO_ROOT') }}/common/...` 을 쓴다.
    Jenkinsfile 3종 어디에도 `ANSIBLE_PLAYBOOK_DIR` 설정이 없고 `REPO_ROOT=${WORKSPACE}` 만 있다.
  - 예상 결과: 해당 vendor 의 OEM fragment 가 **한 번도 병합되지 않고**, include 실패가 site.yml 의
    OEM rescue 로 떨어져 "일부 제조사 확장 정보를 수집하지 못했습니다" 경고만 남는다.
    (반증 근거: `os-gather/tasks/linux/gather_system.yml` 의 `{{ playbook_dir }}/tasks/linux/...` 는
     실제로 존재하는 경로라 정상 동작한다 — playbook_dir 해석 자체는 맞다.)
  - **이번 작업에서 고치지 않은 이유**: errors.message 품질이 아니라 수집 기능/데이터 변경이다.
    고치면 Cisco / Huawei / Inspur / Fujitsu / HPE / Quanta 의 `data.bmc.oem` 이 새로 채워지기
    시작하므로 baseline 회귀 + 실장비(또는 에뮬레이터) 확인이 선행돼야 한다.
  - 선행 확인: 실장비 1대에서 "지금 OEM 이 실제로 누락되고 있는지" 를 envelope 으로 확인.

### C-3. Jinja 컴파일 게이트 (2026-08-12 부분 해소)

- [x] **[DONE] pytest 로 inline Jinja 전수 컴파일** — `tests/e2e/test_section_message_contract.py::
      test_every_inline_jinja_template_compiles` 신설. 실제로 이번 작업 중 발생한 파손
      (`>-` 스칼라 안 `#` 주석 → 템플릿 전체 컴파일 불가)을 잡았다.
- [x] **[DONE] 실제 Ansible 템플릿 엔진 렌더** — `tests/e2e/test_diagnosis_template_ansible_render.py`
      신설. 순수 jinja2 로는 재현되지 않는 ansible-core 2.19+ Marker 동작을 검증한다.
      이 테스트가 `_diagnosis` 미정의 / `{}` / details 부재에서 **3채널 rescue 가 전부 죽는**
      pre-existing 버그를 찾아냈고 같은 커밋에서 고쳤다.
- [ ] **[검토] `pre_commit_jinja_compile_check.py` 를 advisory → blocking 승격** (`JINJA_COMPILE_BLOCKING=1`).
      pytest 게이트가 생겼으므로 우선순위는 낮아졌다.


---

## Location 기반 Credential Resolver — 후속 (2026-08-12, commit `70744c76`)

설계 정본: `docs/ai/contracts/vault-credential-resolver.md`
검증 증거: `tests/evidence/2026-08-12-location-credential-resolver.md`

### E. 실장비 Pilot — 2026-08-12 수행 (`d09ff344`)

증거: `tests/evidence/2026-08-12-location-vault-jenkins-pilot.md`
Job: `clovirone-server-gather-vault-pilot` (운영 Job config 복제, `Jenkinsfile_portal`).

- [x] **P1 Location vault 구성 + 복호화** — 4 Location × 12 = 48개. flat 암호문 그대로 복사
      (git index blob 48/48 원본 동일). **실제 ansible-vault 복호화 경로 검증됨** — Jenkins
      credential `server-gather-vault-password` 로 풀어 실장비 인증 성공
- [x] **P2 OS Linux / Windows** — `ic/os/linux`, `git/os/linux`, `chj/os/linux`, `chj/os/windows`
- [x] **P3 ESXi** — `yi/esxi`
- [x] **P4 Redfish** — Dell `git/redfish/dell`, Lenovo `chj|git/redfish/lenovo`, Cisco `yi/redfish/cisco`
- [x] **P5 built-in SCM checkout** — 가능. 설계 1안 성립, 2안(choice 파라미터) 불필요
- [x] **P6 미등록 Location** — 18초 FAILURE, agent 대기 없음
- [x] **P7 reconcile gate** — 경로 변경 후에도 게이트 불변 확인. dry-run 시 `verification: skipped`
- [ ] **P8 Portal 의 미지 `failure_code` 처리** — `CREDENTIAL_SET_UNAVAILABLE` 수신 시 동작 (외부 시스템)
- [ ] **P9 flat vault 제거** — **아직 아니다.** 아래 E-1~E-3 해소 후 별도 커밋.
      대상: `vault/<loc>/os/{linux,windows}.yml + vault/<loc>/esxi.yml`, `vault/<loc>/redfish/*.yml` 9개
      (`vault/.lab-credentials.yml` 제외)

#### E-1. HPE Redfish 미검증 [HOLD — 장비]

10.50.11.231 이 TCP 443 timeout (ic / yi 두 Location 각각 1회). 같은 대역
10.50.11.232(Lenovo) 는 정상 → BMC 자체 미응답. BMC 복구 후 재시도 필요.

#### E-2. Dell primary credential drift [원인 규명됨 → E-6 으로 이관]

10.100.15.34 iDRAC 에서 표준 계정 인증이 401 이고 `lab_dell_root`(recovery) 로만 붙는다.
2026-08-12 원인 규명: 표준 계정 비밀번호가 장비 **암호 정책** 을 충족하지 못해 동기화
자체가 거부된다. 조치 선택지는 **E-6** 참조.

#### E-0. 표준 계정 전역화 완료 (2026-08-12, `adc99570`)

증거: `tests/evidence/2026-08-12-redfish-standard-account-separation.md`

- [x] 표준 수집 계정 전역화 — `vault/common/redfish/standard.yml` (36벌 → 1벌)
- [x] 복구 계정 Location+Vendor 분리 — `vault/<loc>/redfish/<vendor>.yml` (recovery 만)
- [x] 최종 Gathering 은 반드시 표준 계정 — 실장비 6/6, recovery 수집 0건
- [x] Dell reconcile Root Cause 규명 (2층: `Locked` read-only 200 거부 → 암호 정책 미달)
- [x] flat vault 12개 삭제 + runtime 참조 0건
- [x] `diagnosis.details.recovery_credential_scope` 신설

#### E-6. **Dell 표준 계정 비밀번호가 장비 암호 정책 미달** [운영 결정 필요 — HIGH]

10.100.15.34 (iDRAC10) 가 표준 계정 PATCH 를 거부하며 직접 통보:
`"the password entered does not comply to the Security Strengthen Policy standards"`.

- [ ] **선택지 (a)** 표준 계정 비밀번호 강화 → 전 BMC 재동기화. 값이 바뀌면
      **모든 Location · 모든 Vendor** 에 영향 (vault/common/redfish/standard.yml 1곳 수정 +
      각 장비 반영 필요)
- [ ] **선택지 (b)** 해당 iDRAC 의 Security Strengthen Policy 완화
- 해소 전까지 Dell 은 표준 계정으로 수집할 수 없다 → 결과가 `failed` 로 나간다.
      **이관 전에는 (잘못이지만) recovery 수집으로 `success` 였으므로 Portal 표시가 달라진다.**

#### E-7. 표준 계정 **생성** 경로 실장비 미검증 [HOLD]

이번 검증 대상은 전부 표준 계정이 이미 존재했다 (`account_existed: true`).
"계정 부재 → 생성 → 재인증" 경로는 모듈 단위 테스트로만 확인했다.

#### E-3. **Pilot 중 실제 Account Write 1건 발생** [CRIT — 보고 완료]

빌드 #3 에서 Dell slot 3 에 `PATCH`(password_sync)가 실제로 나갔다. 지시 §13 은 dry-run 을
요구했는데, dry-run 변수(`_rf_account_service_dryrun`)를 **확인하기 전에** Redfish 빌드를
돌린 절차 실수다. 사후 dry-run 관측 결과 계정 슬롯은 그대로이고 인증 동작도 write 전후
동일. 상세: 위 evidence §7.

- [x] **운영에서 reconcile write 를 기본 차단할지 결정** — 2026-08-12 사용자 명시:
      **차단하지 않는다.** Account Reconcile 은 제품의 의도된 기능이다. 대신 쓰기 성공
      조건을 조였다 (write 2xx ≠ 성공, 재인증까지 확인) 와 "복구 자격 미인증 시 쓰기 0" 을
      코드로 강제했다
- [ ] **이후 Pilot / 실험성 Redfish 실행은 dry-run 강제 후 시작** (절차 고정)

#### E-4. Location 별 값 분리 미검증

이번 Pilot 은 4 Location 이 **같은 Credential** 을 가리킨 상태다. Location 마다 실제 값이
갈린 뒤 재검증 필요 (그때 flat vault 가 참조 자료로 필요할 수 있어 P9 를 앞당기지 않는다).

#### E-5. 물리 Runner 분리 미검증

`ic/chj/yi/git` 4 label 이 **단일 노드** `jenkins-agent-ops` 에 모두 붙어 있다. Location →
label → 노드 배정 경로는 검증됐지만 망 분리는 검증되지 않았다.

### F. 사용자 결정 대기

- [ ] **`Jenkinsfile` 삭제** — E2E Regression 게이트(`Jenkinsfile:208-236`, `pytest tests/e2e/` +
      `tests/integration/ -m "not live"`) 를 `Jenkinsfile_portal` 로 옮길지 / 별도 CI 로 뺄지 /
      포기할지 확정 후. 현재는 보류 상태로 두고, 남아 있는 동안 깨지지 않게
      `-e se_location` 만 최소 전달해 두었다 (agent 할당 이전 Location 검증은 top-level agent
      구조라 불가 — 운영 경로는 `Jenkinsfile_portal`).
- [ ] **`Jenkinsfile_portal_test` 삭제** — `Jenkinsfile_portal` 과 1줄(`defaultValue: 'not-json'`)
      차이뿐이라 잃는 기능이 없다. 이번에는 삭제하지 않고 portal 과 동기화만 해 두었다.
- [ ] **`scripts/ai/vault_decrypt_check.py` gitignore 해제 여부** — cycle-018 에서 gitignore 한
      사유(마스터 키 하드코딩)를 2026-08-12 에 제거했다(`SE_VAULT_PASSWORD` / `--password-file`
      로만 수령, 재발 방지 테스트 고정). 이관 runbook 이 참조하는 도구라 추적 대상으로 올릴지 결정 필요.
      현재는 부재 시 관련 테스트가 skip 되도록 처리해 뒀다.
- [ ] **role 기반 후보 정렬** — 이번에 도입하지 않았다(순서 = 시도 순서 계약 보존).
      **선행: 암호화 vault 의 실제 `accounts` 배열 순서 실측** (recovery-first 파일이 있는지)
- [ ] **Location 별 Master Password(설계 §11 B안)** — 이번 범위 제외. 도입 시 전 vault rekey 필요
- [ ] **Adapter `credentials:` 제거 (Phase B)** — 이번 범위 제외. YAML 필드는 남겨 뒀고
      production 소비 코드는 0건이다
- [ ] **OS/ESXi backoff** — 이번 범위 제외. 단 `pam_faillock`(RHEL STIG 기본 deny=3) /
      AD 계정 잠금(흔히 5회)은 **오늘 이미 존재하는 위험**이다 (이번 변경이 후보 수를 늘리지는 않았다)

### G. 이번 작업 중 발견한 pre-existing 결함 (범위 밖 — 기록만)

- [ ] **마스터 키 평문이 git history 와 워킹트리 다수 파일에 잔존** —
      `.vault_pass`, `docs/ai/archive/**`, `docs/ai/CURRENT_STATE.md` 등.
      이미 `OPS-AUDIT-1` 로 등재된 사용자 결정 사항이며, CLAUDE.md §12 에 따라
      Secret Rotation / History Cleanup 으로 범위를 넓히지 않았다.
      이번에는 내가 수정한 파일(`scripts/ai/vault_decrypt_check.py`)의 하드코딩만 제거했다.
- [ ] **`os-gather/site.yml` 의 `ansible_become_pass` play var 가 사실상 죽은 값** —
      `try_one_credential.yml` 이 host fact 으로 덮어써 vault 의 `ansible_become_password` 가
      무시되고 SSH 비밀번호가 sudo 비밀번호로 쓰인다. 동작 변경이라 이번에 섞지 않았다.
      값의 출처만 `_cred_become_password` 로 옮겨 두어, 고칠 때 값을 잃지 않게 했다.
