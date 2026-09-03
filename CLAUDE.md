# Server Exporter - Claude Code Project Guide
## 1. Project
Server Exporter는 Jenkins + Ansible 기반 서버 정보 Gathering 프로젝트다. 지원 채널은 OS(Linux/Windows), ESXi, Redfish(BMC) 3개다.
호출자는 IPv4와 `target_type`을 전달하고 Jenkins가 Site/Agent를 선택한 뒤 Ansible이 수집한다. 결과는 Fragment로 생성되고 Common Normalize를 거쳐 Standard JSON Envelope로 반환된다.
핵심 목표: 반복 실행 안전성, 실패 추적성, Target별 Result 보존, Vendor/Generation 확장성, Credential/Account Write 통제, Portal Consumer 일관성.

## 2. Source of Truth
충돌 시 우선순위:
1. 현재 실제 코드
2. 현재 Contract와 Regression Test
3. Schema, Common Normalize, Callback 구현
4. 이 `CLAUDE.md`
5. README, docs, 과거 Evidence
과거 Cycle/Round, Test/Adapter/Fixture 개수, 파일 Line 수, Commit SHA, Audit 결과는 현재 사실로 고정하지 않는다.
필요 시 `REQUIREMENTS.md`, 관련 `docs/`, `.claude/rules/`, `.claude/skills/`만 읽는다.

## 3. Architecture
`Portal -> Jenkins Controller -> Site/Agent Routing -> Jenkins Agent -> Ansible -> OS|ESXi|Redfish -> Fragment -> Normalize/Merge -> JSON -> Callback/Result -> Portal`
입력 개념: `loc`=Site/Agent Routing, `target_type`=`os|esxi|redfish`, OS/ESXi=`service_ip`, Redfish=`bmc_ip`, 호환 입력=`ip`, Portal 대상 입력은 IPv4 기준.
`loc` 값으로 Credential/Vendor를 임의 분기하지 않는다. Jenkins Stage, Job 이름, Checkout SHA는 현재 Jenkinsfile과 실제 Build Log를 확인한다.
주요 위치: `os-gather/site.yml`, `esxi-gather/site.yml`, `redfish-gather/site.yml`, `common/library/precheck_bundle.py`, `common/tasks/normalize/`, `callback_plugins/json_only.py`, `lookup_plugins/adapter_loader.py`, `schema/`, `vault/`.

## 4. Fragment / Normalize
각 Gather는 자기 담당 정보만 Fragment로 만들고 누적 Result를 직접 수정하지 않는다.
공통 Fragment: `_data_fragment`, `_sections_supported_fragment`, `_sections_collected_fragment`, `_sections_failed_fragment`, `_errors_fragment`.
`merge_fragment.yml`과 Common Builder가 최종 Result를 조립한다.
금지: 다른 Gather Section 침범, 누적 변수 직접 수정, Vendor Task에서 Common Normalize 규칙 임의 변경, 새 Section 하나 때문에 전체 Output Builder 재작성.
Overall `status`는 Error 문자열 개수가 아니라 실제 Section 결과로 `success`, `partial`, `failed`를 판단한다. Partial을 임의로 Failed로 바꾸거나 대표 Failure Stage를 억지로 부여하지 않는다.

## 5. Adapter / Vendor Boundary
Vendor/Generation 차이는 Adapter를 우선 사용한다. 공통 코드에 Vendor 이름 기반 분기를 추가하지 않는다.
Vendor 차이는 Adapter YAML 또는 Redfish 라이브러리의 OEM 추출 분기에 두고 Generic fallback을 유지한다. Evidence 없는 Vendor Exception을 추가하지 않는다.
신규 Redfish Vendor/Generation 기본 확장 지점: `common/vars/vendor_aliases.yml` -> `adapters/redfish/*.yml` -> 필요 시 `redfish-gather/library/redfish_gather.py` 의 `_extract_oem_*`.
Ansible Task 층의 vendor OEM 디렉터리는 2026-08-13 에 제거됐다 (기여 0).
Adapter 선택 점수는 현재 구현 Contract인 `score = priority × 1000 + specificity × 10 + match_score`를 따른다.
Adapter 선택 로직 변경 시 기존 선택 결과 전체를 Regression으로 확인한다.
Mock/Emulator/Web Evidence와 실제 Lab 검증을 구분한다. Redfish 핵심 Library에 Third-party Python Dependency를 임의 추가하지 않는다.

## 6. Channel Flow
OS: `TCP 5986 -> TCP 5985 -> TCP 22 -> Protocol Detection -> Credential -> Gathering -> Normalize`
- Windows: WinRM WS-Man Identify
- Linux: SSH Identification
- Linux는 Remote Python 상태에 따라 Standard 또는 Raw fallback 사용
- Raw fallback은 Python 부재/비호환 환경에서도 Standard Result Contract 유지
ESXi: `TCP 443 -> vSphere RetrieveServiceContent -> Credential -> Gathering -> Normalize`
Redfish: `TCP 443 -> ServiceRoot -> Vendor Detection -> Adapter Selection -> Credential Load(Standard 전역 + Recovery Location×Vendor) -> Standard Account Auth -> Reconciliation if needed -> Standard Account Gathering -> Normalize`
Redfish Credential은 축이 2개다. **Standard Gathering Account는 전역 1벌**(`vault/common/redfish/standard.yml`)이며 Location도 Vendor도 보지 않는다. **Recovery Account만 Location×Vendor**(`vault/<loc>/redfish/<vendor>.yml`)다. Vendor 확인이 필요한 것은 Recovery 쪽이다. Vendor 미식별이어도 Standard 인증은 시도한다.

## 7. Precheck Contract
`reachable`은 **관리 TCP 응답 OR ICMP Echo 응답**이다 (2026-09-03 사용자 지시). 관리 TCP를 먼저 보고, TCP가 아무 응답도 주지 않았을 때만 ICMP Echo를 1회 확인한다.
ICMP Ping은 **Gate가 아니다.** ICMP가 차단되어 있어도 관리 포트 통신이 가능하면 Gathering은 진행한다. ICMP 무응답만으로 실패시키지 않으며 ICMP 전용 `failure_code`도 만들지 않는다. ICMP를 앞단 필수 관문으로 되돌리지 않는다.
판정: 관리 TCP 연결 성공 또는 RST 관측 -> `reachable=true`. TCP 무응답이어도 ICMP Echo Reply -> `reachable=true` + `port` 단계 실패. TCP·ICMP 모두 무응답일 때만 `reachable=false`.
`reachable=true`인데 관리 포트를 열지 못했으면 기존 흐름대로 `port` 단계 실패다. `protocol -> auth -> gather -> fallback` 흐름은 변경 없다.
원칙: TCP 연결 성공과 Protocol 확인 성공은 별개, Timeout만 보고 IP 미사용 단정 금지, Connection Refused만 보고 최종 장비 직접 응답 단정 금지.
Hostname, IPv6, IPAM, ARP 기반 별도 Discovery를 요구 없이 추가하지 않는다.
Precheck 목적은 단순 Alive 판정이 아니라 TCP, Protocol, Authentication, Gathering 실패를 구분하는 것이다.

## 8. Redfish Standard Account / Recovery
표준 Gathering Account를 특정 Username 문자열로 하드코딩하지 않는다.
Standard Account는 **전역 Standard Vault**(`vault/common/redfish/standard.yml`)의 `role: primary`, Recovery Account는 **Location×Vendor Vault**(`vault/<loc>/redfish/<vendor>.yml`)의 `role: recovery`다. 두 파일은 축이 서로 다른 별개 Set이며 Recovery Vault에 `role: primary`를 넣으면 그 항목은 버려진다.
Account Reconcile은 쓰기 전에 Read-only Capability Discovery로 BMC Family를 확정하고 검증된 Write 방식 하나만 실행한다. 쓰기 실패 후 다른 Payload/URI로 순차 재시도하지 않는다.
Account 존재 판정은 `present`/`absent`/`unknown`/`ambiguous` 4-상태다. Account 목록을 완전히 열거하지 못한 `unknown` 상태에서는 Account Write 0건이어야 한다.
Write 성공은 HTTP 2xx가 아니라 Vendor Contract로 판정한다(본문 거부/OEM Status 포함). 반드시 Account 재조회와 Standard Credential 재인증까지 통과해야 성공이다.
현재 Primary Username이 `infraops`여도 `infraops` Literal 자체는 Contract가 아니다. 핵심 Contract는 최종 Gathering이 Standard Account로 수행되는 것이다.
정상: `Primary 인증 성공 -> Account Write 0 -> Primary Gathering`
Recovery 목적: `Standard Account 생성 또는 복구 -> Primary 재인증 -> Primary Gathering`
Password 불일치: `Primary 인증 -> 구조화된 401 -> Recovery 성공 -> Standard Account 조회 -> Profile 값으로 Password 동기화 -> Primary 재인증 -> Primary Gathering`
Standard Account 부재: `Primary 실패 -> Recovery 성공 -> 부재 확인 -> 기존 Vendor별 생성 방식으로 Standard Account 생성 -> Primary 인증 검증 -> Primary Gathering`
생성 Username/Password/Role은 Standard Account Profile을 기준으로 한다.
Reconciliation Write Gate: `Primary 실제 인증 시도 AND 구조화된 401 AND Recovery 인증 성공`
Timeout, TLS 오류, Transport 오류, HTTP 5xx, HTTP 403은 Password 불일치로 해석하지 않으며 Account Write는 0이어야 한다.
문자열 Error Parsing으로 인증 실패 추측 금지, 동일 Standard Username 여러 Slot이면 임의 수정 금지, Credential 후보/Retry 임의 증가 금지, Account Lockout 고려.
Delete/Recreate 보호 정책 임의 완화 금지. Dry-run은 예정 Action 확인일 뿐 실제 생성/변경/재인증 완료 증거가 아니다. OS/ESXi에 Redfish Reconciliation을 확장하지 않는다.

## 9. Diagnosis Contract
유효한 `failure_stage`: `reachable`, `port`, `protocol`, `auth`, `gather`, `fallback`.
Stable `failure_code`: `DNS_RESOLUTION_FAILED`, `TARGET_UNREACHABLE`, `TCP_CONNECT_FAILED`, `TCP_CONNECTION_REFUSED`, `PROTOCOL_CHECK_FAILED`, `AUTH_PROBE_FAILED`, `GATHER_FAILED`, `OUTPUT_BUILD_FAILED`.
`TARGET_UNREACHABLE`(stage=`reachable`)은 TCP·ICMP 모두 무응답이고, `TCP_CONNECT_FAILED`(stage=`port`)는 ICMP는 응답하는데 관리 TCP 포트만 무응답인 경우다. 둘 다 장비 다운 확정이 아니다.
Success: `failure_stage=null`, `failure_code=null`, `failure_reason=null`.
Failed: `failure_stage`, `failure_code`, `failure_reason`이 모두 존재해야 하며 실패인데 `failure_reason=null`인 Result를 만들지 않는다.
`failure_stage`는 Root Cause가 아니라 Workflow가 멈춘 위치다.
`auth_success=true`는 실제 인증 성공, `false`는 구조화된 명시적 인증 거부, `null`은 미시도 또는 확정 불가다.
HTTP 403, Timeout, TLS, Transport 오류를 자동으로 `auth_success=false`로 만들지 않는다.

## 10. Portal Failure Message
Portal Failure Grid는 `errors[].message`를 사용한다. 최종 Failed Result의 사용자 Message는 `diagnosis.failure_reason`과 동일한 중앙 정의를 사용한다.
기술 Evidence는 `errors[].detail`에 둔다. 사용자 Message에는 Port, Timeout, HTTP Status, Raw Exception, SOAP/XML 내부정보, Task/변수명을 넣지 않는다.
대표 메시지:
1. `대상 IP에서 응답을 확인할 수 없습니다. IP 사용 여부와 네트워크 상태를 확인하세요.`
2. `대상 IP의 관리 포트에 연결할 수 없습니다. 방화벽과 관리 서비스 상태를 확인하세요.`
3. `관리 포트에는 연결됐지만 서버 정보 수집에 필요한 응답을 확인할 수 없습니다. 관리 서비스 설정과 상태를 확인하세요.`
4. `대상에 접속할 수 없습니다. 자격증명과 계정 권한을 확인하세요.`
5. `대상 접속은 확인됐지만 정보 수집에 실패했습니다. 대상 상태와 수집 로그를 확인하세요.`
IPv4-only이므로 사용자 Message에서 DNS/Hostname 확인을 안내하지 않는다. `DNS_RESOLUTION_FAILED` enum이 남아 있어도 사용자 안내를 DNS 문제로 단정하지 않는다.

## 11. Result Envelope / Cardinality
요청 Target 1개는 최종 Result Envelope 정확히 1개를 가져야 한다: `requested target count == result envelope count`.
금지: Host 누락, Host 중복, 요청하지 않은 Host 추가.
Gathering 중 unreachable이 되어 일반 OUTPUT Task까지 도달하지 못해도 Envelope가 사라지면 안 된다.
Callback/Result Builder는 Host Lifecycle Evidence로 누락 Result를 보완한다. 모든 unreachable을 `fallback`으로 처리하지 않는다.
현재 Standard Envelope Top-level Contract: `status`, `sections`, `data`, `errors`, `meta`, `diagnosis`, `target_type`, `collection_method`, `ip`, `hostname`, `vendor`, `correlation`, `schema_version`.
새 Top-level Field, `failure_stage`, `failure_code`, Schema Version 변경은 Consumer와 Schema 영향을 확인한 뒤 진행한다. `diagnosis.details`는 기술 Evidence와 확장 Metadata 영역이다.

## 12. Credential / Security / Failure Handling
Credential은 기존 Vault와 Credential Profile 구조를 사용한다.
금지: 새 Password 하드코딩, Debug/Callback/Result Credential 출력, Credential 후보/Retry 이유 없이 증가, 이유 없는 `ignore_errors: true`, 실패 후 정상처럼 계속 진행, Failed Host Result 누락, Timeout/403/5xx를 인증 실패로 단정, Raw stdout 하나에 상태/원인 혼합.
`no_log`가 필요한 기존 Credential Task를 유지한다.
사용자 요청 없이 Secret Rotation, Vault Rekey, Git History Cleanup으로 범위를 확대하지 않는다.

## 13. AI Harness / Session Workflow
세션 시작 시: 현재 Branch/Git 상태 확인 -> 요청/변경 경로 기준 역할 추론 -> 필요한 `.claude/role/`, `.claude/ai-context/`, `.claude/rules/`만 로드.
단순 오타가 아닌 코드 변경은 현재 Impact Preview 정책을 따른다. 사용자가 Preview 생략/바로 진행을 명시하면 현재 정책 범위에서 진행한다.
제품 코드 작업과 Harness 자기개선 작업을 섞지 않는다. 제품 코드 변경 중 `.claude/`, `docs/ai/`, `scripts/ai/`를 이유 없이 수정하지 않는다. Harness 개선 작업에서도 제품 코드를 요청 없이 수정하지 않는다.
사용자 `~/.claude/settings.json`(전역 설정)은 자율 수정하지 않는다. 프로젝트
`.claude/settings.json` 의 권한 모드는 2026-05-01 ADR(harness-full-permissions)로
사용자가 전권을 부여한 결과이며 그 자체가 위반이 아니다.
세부 승인/Role/Hook/Orchestrator 규칙은 현재 `.claude/rules/`, `.claude/policy/`, `.claude/skills/`를 따른다. 오래된 Rule 번호/날짜를 이 파일에 복제하지 않는다.

## 14. Git / Production
`main`: 개발 기준 Branch, 순수 Project Code와 Harness 포함.
`production`: 순수 Gathering 배포 Branch, Harness 제외.
대표 production 제외 경로: `.claude/`, `CLAUDE.md`, `docs/ai/`, `scripts/ai/`, `tests/reference/`, `tests/evidence/`.
원칙: 순수 코드/Harness 변경 가능하면 별도 Commit, `git merge main`으로 production 전체 병합 금지, 순수 Project Code는 현재 Promotion Script/정책으로 승격.
유효한 자동 승격 범위에서는 매번 별도 승인 재요구 금지. force push와 History Rewrite 금지.
Remote URL은 `git remote -v`로 확인하고 Push 성공만으로 Jenkins 반영 완료 판단 금지. 실제 Job의 Repository, Branch, Checkout SHA를 확인한다.

## 15. Protected Changes
수정 전 영향 확인 대상: `vault/**`, `schema/baseline_v1/**`, `Jenkinsfile*`, `common/tasks/normalize/**`, `callback_plugins/**`, `redfish-gather/library/redfish_gather.py`.
Dependency 추가/삭제, Schema Version, Cron, 새 Vendor, 보호 경로 변경은 현재 Approval Policy를 확인한다.
기존 코드 일부 수정 요청이면 전체 구조를 불필요하게 재작성하지 않는다.

## 16. Verification / Completion
코드 변경 후 변경 범위에 맞게 검증한다.
기본: Python compile, YAML parse, Jinja2 compile, `ansible-playbook --syntax-check`, unit, e2e, integration, regression.
Contract: field dictionary, schema drift, envelope, cross-channel, vendor boundary, secret leakage, Harness consistency.
고정 Test Count를 신뢰하지 않고 현재 실행 결과를 기준으로 판단한다.
실장비가 필요한 Protocol/Vendor/Account Write는 Unit Test만으로 실장비 검증 완료라고 하지 않는다. Dry-run과 실제 Write 검증을 구분한다.
완료 보고에는 실제 변경, 검증 결과, Blocked, 실장비 여부, 운영 영향, 남은 작업을 구분한다. 실행하지 않은 코드를 `검증 완료`라고 표현하지 않는다.

## 17. Documentation Guard
문서와 실제 코드가 다르면 실제 코드와 현재 Contract를 우선하고 관련 문서를 갱신한다.
stale 정보를 구현 근거로 사용하지 않는다: `ping -> port -> protocol -> auth`, 과거 Adapter/Fixture/Test 수, 파일 Line 수, Commit SHA, Audit 상태, 실장비 대수, 오래된 Jenkins Stage 설명.
이 파일에는 모든 세션에서 항상 필요한 Project Contract와 Guardrail만 유지한다.
Cycle/Round History, 긴 Troubleshooting, Vendor별 전체 구현, AI Harness History, 고정 수치/날짜, 일회성 작업 결과는 추가하지 않는다.
세부 절차는 `.claude/skills/`, 경로별 규칙은 `.claude/rules/`, 상세 설계와 Evidence는 `docs/`에 둔다.

## 18. Key Documentation
문서 지도는 `docs/README.md` 다. 갈래는 다섯이다.

- `docs/overview/` — 이 시스템이 푸는 문제와 전체 그림
- `docs/operate/` — Jenkins·에이전트 구축, 잡 등록, 자격증명, 현장 작업
- `docs/contract/` — 호출자 계약 (입력 / envelope / 필드 / 실패)
- `docs/develop/` — 수집 구조, 어댑터, 벤더 추가, 디버깅
- `docs/reference/` — 호환성 매트릭스, 실장비 검증, 결정 로그

AI 전용 문서는 `docs/ai/` 에 있고 production 브랜치에는 나가지 않는다.
사람용 문서가 `docs/ai/` 나 `.claude/` 를 참조하면 안 된다 — 배포본에서 깨진 링크가 된다.
