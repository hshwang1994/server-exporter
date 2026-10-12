# 2026-10-12 — 독립 점검: 결함 수정 · 실제 Jenkins 검증 · 문서 재작성 · production 승격

지시서 "ClovirONE Gathering 독립 점검 및 개선"(2026-10-12)에 따른 작업 기록이다. 점검 기준은 main `c1f818cb`(= production P12 `410317a7` 의 runtime tree)였고,
결함은 현재 코드와 실행 결과로만 확정했다. 하네스(`.claude/`, `docs/ai/`, `scripts/ai/`, `tests/jenkins/harness/`)는 고치지 않고 검증 도구로만 썼다.
비밀값(Jenkins 계정 · API 토큰 · vault 암호)은 이 문서와 저장소 어디에도 없다.

## 1. 고친 결함과 달라진 동작

### 1-A. 파이프라인 · 결과 보존 · 전송 (`Jenkinsfile_portal`, `scripts/`)

| # | 종전 | 지금 |
|---|---|---|
| P1 | 시도 실행 한계의 timeout 이 ansible 셸 도중 나면 `seAttemptBody` 의 catch 가 Runner 연결 상태로 "사용자 취소" 를 확정하고 보존 · 삭제한 뒤, 바깥 handler 가 빈 폴더에서 보존을 반복했다(빈 stash 가 정상 stash 를 덮음) | 중단 원인은 Jenkins 의 분류로만 가른다. `seAttempt` 가 `timeout(한계){본문}` 을 조건 없는 `retry(count: 2)` 안에 두고 예외를 그대로 다시 던진다 — 두 번째 호출이 일어나면 이 블록의 timeout(또는 Runner 제거), 아니면 "실제 중단"(사용자 취소 등). 두 번째 호출에서는 Runner 연결 상태로 경로만 가른다(연결됨 → `attempt_limit` · 아니면 원본 예외를 바깥 `retry(agent())` 로). "실제 중단" 은 원인을 확정하지 않고(`aborted`, 문구 "사용자 취소 또는 그 밖의 중단") 보존하되 작업 폴더를 남긴다. 보존은 한 곳에서 1회다 |
| P2 | 결과 파일이 하나도 없어도 `stash(allowEmpty: true)` 가 성공해 `SE_FINAL_STASHED=true` 로 앞 stash 를 덮고 재시도를 포기했다 | 전달할 파일이 없으면 stash 하지 않는다(`allowEmpty: false`). 보존 확인 전 `deleteDir` 없음, 중단 원인 미확정이면 작업 폴더 유지 |
| P3 | 재개 시도가 `begin` 전에 rc 90/91 이외로 끝나면 `classify` 가 앞 시도 기록을 돌려줘 무한 재시도가 될 수 있었다 | `run_gather.sh` 준비 단계마다 종료 코드(93 chmod · 94 임시 파일 · 95 잠금)와 원인 문장을 남기고, 파이프라인은 새 시도 기록이 없으면 앞 기록을 재사용하지 않는다(확인된 준비 오류 → `prep_failed`, 그 밖 → `failed_run`). 재시도 상한은 두지 않았다 |
| P4 | `report.kept ?: accepted - filled` 가 kept=0 을 거짓으로 봐 과장 | `!= null` 비교 |
| P5 | rc 91 도 "Ansible 환경 없음" 문구 | 원인별 문구(90 환경 없음 · 91 기록 준비 실패 · 93/94/95 준비 실패) |
| P6 | `seFinMarker` 의 `writeFile` 이 예외면 전송 없이 결과 확인 실패 | `FlowInterruptedException` 즉시 재전달. `IOException` 이고 내부 원인에 remoting/연결 종료가 없으며 같은 폴더의 `fileExists('.')` 가 정상일 때만 경고 뒤 계속. 그 밖은 원본 예외 그대로 |
| P7 | `callbackUrl` 에 `?`·`#` 가 있으면 깨진 주소 | 입력 확인에서 거부 |
| P8 | Layer A 셸이 스크립트 부재(rc 2)와 "손상 줄 제외"(exit 2) 를 구분 못함 | 파일 존재를 먼저 확인(없으면 3) |
| P9 | `gather_state.py end … 2>/dev/null` | stderr 를 콘솔로 |
| P10 | `env.SE_GATHER_RUN` 에 IP 목록 전체 | IP 목록을 뺀 요약만(`seGatherRunForEnv`) |
| P11 | http_request 플러그인(1.25)이 이름 풀이 실패를 합성 404 로 돌려주는데 모든 404 를 Portal 거부로 처리 | 헤더 없음 + 본문이 플러그인 고정 문구(`UnknownHostException as 404 Not Found`)인 경우만 통신 실패(`transport=unknown_host`)로 보고 기존 재시도 범위에서 처리. 실제 404 는 거부 그대로 |
| P12 | 입력 확인의 `readJSON`(관대)이 `inventory.sh`(엄격)보다 넓어 접수 뒤 전 대상 실패 | `groovy.json.JsonSlurper` 기반 엄격 파서(제어 문자 · 첫 값 뒤 내용 거부). 반환은 `[value:]`/`[error:]` — sandbox 가 거부하는 생성자(`new ArrayList`)를 쓰지 않는다(main #520 실측) |
| P13 | `running` 상태에도 "보존했고" 출력 | 상태별 문장 분리 |
| P14 | `bootstrap_vault_encrypt.sh` 가 credential 을 Secret File 로 안내 | Secret text |
| P15 | `production_manifest.yml` 의 `se_finalize.groovy` 가 optional | 필수 |

### 1-B. 수집 채널 · normalize

| # | 종전 | 지금 |
|---|---|---|
| G1 | 어느 섹션 오류든 'HTTP 403' 문자열이 있으면 host 전체 `failed` → 수집한 데이터 폐기 | 첫 인증 응답이 2xx 면 하위 403 은 그 섹션 실패(partial). 첫 인증 403/401 은 종전대로 실패 |
| G2 | Linux memory 가 sudo 성공에 의존(실패 시 섹션 failed) | 비특권 raw 가 `/proc/meminfo` 를 내고 특권 값이 없으면 `total_basis: os_visible` + `errors[]`(`cause=privilege_failed`) |
| G3 | Power·PowerSubsystem(또는 Thermal) 둘 다 404 면 `({}, [])` → `sections.power=success`, `data.power=null` | 404 를 오류로 돌려 `not_supported`. 멀티 노드 chassis 루프에서도 404-only 는 오류로 남기지 않는다 |
| G4 | Redfish 섹션 목록이 경로마다 다름(adapter 에 `system`, `thermal` 없음) | adapter 30개 `capabilities` 에서 `system` 제거 · `thermal` 추가(power 지원 adapter). rescue 경로도 9 섹션. 시험 `test_adapter_capabilities_channel_sections.py` |
| G5 | Linux users: raw 실패도 `not_supported` + errors 0 | `getent` 부재만 `not_supported`, 그 밖 실패는 `failed` + errors 1건 |
| G6 | `iLO.*6` 이 "iLO 5 v2.65" 에 맞음, `dell_idrac8` 의 `^3\.`, `lenovo_xcc` 의 glob 식 | 세대 토큰은 단어 경계(`iLO\s*6\b`, `iDRAC\s*9\b`, `XCC\s*3\b`), 버전 숫자 패턴은 보조. fixture 64 사례 전후표에서 바뀐 것은 오탐 3건뿐(iLO 5 v2.65 → ilo5, iLO 3 v1.95 → hpe_ilo fallback, R740 3.21 → idrac9) |
| G7 | `cpu.summary` 결측 0 · `hardware.uuid` 소문자 누락 · 메모리 합계 floor · Windows DMI 자리표시자 미필터 · Linux 식별자 진단이 파일 부재를 권한으로 단정 · fallback `vendor: "unknown"` | 각각 null · 소문자 · 반올림 · `dmi_sentinel_null` · `cause` 분리 · null |
| G8 | `field_dictionary` vendor enum 에 huawei/inspur/fujitsu/quanta/vmware/qemu/microsoft/xen 없음, examples 가 옛 모양 | enum · 설명 보강, examples 갱신 |
| 추가 | `gather_system.yml` 의 `. /etc/os-release 2>/dev/null \|\| true` 가 파일 부재 시 POSIX sh(dash) 를 중단시킴 | `if [ -r /etc/os-release ]` 뒤에만 읽는다 |

### 1-C. 정리

- 읽히지 않는 fact(`_l_python_path` · `_l_has_*` · `_l_cpu_ok` · `_l_mem_phys_ok` · `_l_stor_ok` · `_rf_vault_loaded` · `_rf_used_account_role/password` · `_precheck_result`), Jenkinsfile 의 dead code(`SE_PRESERVE_FILES` · `st.attempts` · `limit_left` · `canon.source`) 제거.
- 참조 0 인 `tests/expected/**` · `tests/scripts/phase5_*` · `identifier_verify.sh` · `remote_identifier_test.py` · 해시가 어긋난 `tests/evidence/manifest.json` · 빈 fixture README 3개 삭제. `requirements-test.txt` 의 playwright · pytest-asyncio 제거.
- 작업 진행 기록만 담은 evidence 25건 삭제(코드 · 시험 · 사람용 문서 참조 0, decision-log 의 경로 언급 5곳은 문장으로).

## 2. 확인 방법

### 2-1. 로컬 · CI gate

- WSL `scripts/ai/ci_gate.sh`(후보 working tree): corpus 20/20 · unit/e2e/regression 4,878 통과(153 건너뜀 · 7 xfail) · integration 333 통과 · 3채널 syntax-check · 스키마 정합 · vendor 경계 · 하네스 일관성 — PASS.
- 새 재현 시험: `test_redfish_status_after_authenticated_403.py` · `test_redfish_power_thermal_absent_not_supported.py` · `test_adapter_generation_tokens.py` · `test_adapter_capabilities_channel_sections.py` · `test_linux_memory_without_privilege.py` · `test_linux_users_failure_vs_unsupported.py` · `test_jenkinsfile_portal_audit_2026_10_12.py`(P1~P13 + sandbox 생성자 가드). 기존 시험 보정: `test_jenkinsfile_portal_finalize.py` · `test_jenkinsfile_portal_preserve_and_params.py` · `test_run_gather.py` · `test_time_limits.py` · `test_os_users_unsupported_f23.py` · `test_linux_remote_consolidation.py` · `test_csus_extended_topology.py` · `test_hpe_superdome_flex_m_e2.py` · 골든 6건(thermal collected → unsupported).
- 생성 tree 위 시험(G14 overlay)에서 주석에 의존하던 단언 2건을 코드 anchor 로 바꿨다(CI #46 G14 FAIL → 수정).

### 2-2. 설치 Jenkins 의 동작 실측 (임시 격리 Job `…-audit-probe-20261012`, 삭제함)

- 자기 블록 `timeout` 의 FlowInterruptedException 이 경계를 나가면 조건 없는 `retry(count: 2)` 가 본문을 다시 부른다(catch+rethrow · `sh` 가 timeout 으로 죽은 경우 포함).
- `/stop` 의 예외는 다시 부르지 않고 그대로 던져진다(`getResult()=ABORTED`, "Aborted by admin"). Agent 연결 해제(launcher inbound 전환 + doDisconnect)는 5분 뒤 "terminating shell step" → 재호출되며 `nodesByLabel` online=[] 다.
- `readJSON`(json-lib) 은 홑따옴표 · 따옴표 없는 키 · 끝 쉼표 · 앞자리 0 · 제어 문자를 받아들이고, `JsonSlurper` 는 앞 셋을 거부하지만 첫 값 뒤의 내용을 무시한다 — P12 파서는 JsonSlurper + 제어 문자 거부 + 배열/객체 끝 문자 확인.
- sandbox: `new java.util.ArrayList` 거부(main #520). 새 Script Approval 없이 리터럴로 해결.

### 2-3. 임시 격리 검증 Job (`…-audit-verify-20261012`, 후보 SHA 의 실제 `Jenkinsfile_portal` 함수 적재 · 가짜 ansible(stub) · Portal 수신기, 검증 전용 임시 Agent `se-audit-tmp-agent`, 삭제함)

| 사례 | 빌드 | 관측 |
|---|---|---|
| gather_limit (ansible 실행 중 수집 한계 8초) | #1 (`c5cf3b94`) | outcome `timeout`/`gather_limit` · 완료 2/3 보존 1회(archived+stashed) · 접수 3 = 결과 3(보충 1) · Portal 1회 200 · 작업 폴더 삭제 · UNSTABLE |
| attempt_limit_lockwait (1번째 시도 2대 뒤 끊김 → 2번째 시도 재개) | #2 (`0dd409e4`) | 1번째 rc 137 `running` 기록 → 2번째가 같은 폴더에서 "이전 시도는 끝 기록 없이 중단됐습니다(원인 미확인)" 뒤 남은 1대만 수집 · 3/3 · Portal 1회. stub 의 고아 잠금 보유는 이 환경에서 재현되지 않아 잠금 대기 자체는 미검증 |
| attempt_limit_hang (venv activate 150초 멈춤, 한계 80초 — Jenkins timeout 이 셸 도중) | v2 #1 (`43d78f7c`) | "Cancelling nested steps due to timeout → Retrying" → Runner 연결됨 → `attempt_limit` · 보존 1회 · 접수 3 = 보충 3 · Portal 1회 200 · UNSTABLE |
| stop_during_gather (`/stop` 20초 뒤) | v2 #2 | "Aborted by admin" 이 retry 에서 재호출 없이 전파 → `aborted` · `SE_GATHER_INTERRUPTION=user_or_other` · 문구 "빌드가 중단됐습니다(사용자 취소 또는 그 밖의 중단)" · 끝난 2대 + 보충 1 보존 1회 · 작업 폴더 유지 · Portal 1회 200 · ABORTED |
| race_stop_at_limit (한계 80초, 76초에 `/stop`) | v2 #3 | 콘솔에 "Aborted by admin" 과 "Timeout has been exceeded → Retrying" 이 함께 — Jenkins 가 "실제 중단 아님" 으로 분류해 `attempt_limit` 로 기록 · 보존 1회 · Portal 1회 · 빌드 결과는 ABORTED. 경과시간으로 원인을 정하는 코드는 없다 |
| marker_write_fail (`.se_fin.json` 자리에 디렉터리) | #3 (`b5ee0a7c`) | "기록 파일(.se_fin.json)을 쓰지 못했습니다. 결과 처리는 계속합니다. 오류: … Is a directory" → Portal 1회 200 · SUCCESS |
| agent_lost_during_preserve (Layer A 150초 멈춤 중 Agent 연결 해제) | (아래 3절) | |

stub ansible 을 쓰는 이 사례들은 "Jenkins 중단과 보존 흐름" 검증이다. 실제 대상 수집은 2-4 의 main Job 으로 따로 확인했다.

### 2-4. main Job · CI · 승격 · production

- 후보 SHA `46002a2b60cbf62e80a9a1a9e50977cdc6d4b5ab`(main HEAD, 두 원격 동일). 아래 main 빌드 전부의 `[수집] 저장소를 준비했습니다. revision` 이 이 SHA 다.
- main Job 매트릭스(3절) 의 결과 봉투를 P12 production 명부(#274~#279)와 대상별로 대조했다(저장소 밖 `compare_envelopes.py`, 휘발 필드 제외). 비휘발 차이는 의도한 것(`hardware.uuid` 소문자 정규화 1대)뿐이고
  섹션 상태 · vendor · hostname · diagnosis 차이는 0 이다. G3(Power·Thermal 둘 다 404)은 lab 장비에 해당 장비가 없어 fixture 와 단위 시험으로만 확인했다.
- CI `clovirone-server-gather-ci`: #46(`c5cf3b94`) G14 FAIL(주석 의존 단언 2건 → 수정) · #47(`43d78f7c`) Harness `prep_failed_on_resume` FAIL(P10 env 사본 순서 → `46002a2b` 로 수정, `outer_timeout` 는 controller 의 GitHub fetch timeout) ·
  #48(`46002a2b`, E2E 없음) ABORTED(같은 SHA 의 E2E 포함 실행 #49 로 대체 — Gate · Corpus · Prodgen Build · Drift · Verify 는 PASS 상태에서 중단) · #49(`46002a2b` + E2E S1 S2 S3 T2 T5 T6 E2E-A E2E-A2, S2 = Linux B #532 · E2E-A2 = #543) COMPLETE_PASS — 승격 dry-run 의 증거 검사가 S2 혼합 배치(실호스트 + TEST-NET) 부재와 E2E-A2 revision 추정 바인딩(이웃 빌드)을 거부해 #549 · #550 으로 보강 · #50(#549 · #550 + 트리거 측 tip 관측) Jenkins Controller 재시작(18:30 KST)으로 Gate 도중 중단 → 파이프라인 제한 2시간 30분 초과로 ABORTED · #51(#50 과 같은 입력) UNSTABLE — 단계 전부 PASS 이지만 prodtree 하네스 2 시나리오(하네스 #1819 · #1824)가 controller 의 일시적 이름 풀이 실패(`Could not resolve host: github.com`)로 Jenkinsfile checkout 에서 1초 안에 끝나 판정 없음(직후 빌드는 정상, 제품 · 하네스 기대값 문제 아님) · #52(같은 입력) SUCCESS · COMPLETE_PASS(전 단계 PASS).
- 승격: `python -m scripts.ai.prodgen promote --sha 46002a2b…`(verify report · e2e evidence · ci_stage_results 는 CI #52 산출물, vault 암호 파일은 실행 중에만) → production P13 `b86c5942`
  (trailer `Main-SHA 46002a2b…` · `Tree-Hash 3cf198ed969342544775ecf9e8f3cfbaee8c573516dfcb50751fe82bc57aba8d` · Verdict COMPLETE_PASS). `git ls-remote origin` · `internal` · 로컬 `production` 세 값 동일, drift-check `PROVENANCE`.
- production Job `clovirone-server-gather`: canary #280(os 3) · 명부 #281~#285 · Redfish 재실행 #286(main #555 와 같은 명부로 동시 실행) · loopback 수신기 canary #287 — checkout 전부 == P13 · 결과 수 == 접수 수. 승격 시점에 Portal 테스트 수신 백엔드가 내려가 있어(10.100.64.151:8080 은 Tomcat 기본 404, 80 · 8081 · 8082 의 nginx 는 502) #280~#286 은 서버가 돌려준 실제 404 를 확정 거부로 1회 기록했고 재전송하지 않았다(P11 ①). Portal 200 은 저장소의 `tests/jenkins/harness/callback_sink.py` 를 controller loopback(127.0.0.1:18090)에 띄운 임시 Job(삭제)으로 #287 에서 확인했다 — 수신 기록 1건, `/api/jenkins/gather/os`, 18,902 bytes, 본문 sha256 == 보관된 `callback_body.json`, eventUuid 일치. 오전 main 매트릭스와의 데이터 차이는 모두 대상 쪽 변화였다(10.100.64.161 전원 꺼짐 — 이 PC 에서도 ping · TCP 22 무응답, 10.100.64.156 · .95 · .96 커널 6.8.0-100/101 → 146 재부팅과 .156 의 /dev/sdb 제거, Runner 4대 재부팅으로 `df` 순서 변화, Windows VM NIC 교체(MAC), ESXi .2 물리 NIC 링크, Dell BMC · 서버 재시작 11:57~12:01 UTC). 같은 대상을 main Job 으로 다시 수집해 대조한 #551↔#281(.156 .95) · #553↔#283(Windows) · #554↔#284(ESXi 6) · #555↔#286(Redfish 10, 동시 실행) 은 비휘발 차이 0, #552↔#282(Runner 4대) 는 파일시스템 사용률 1건뿐이다.
- 이 기록을 담은 뒤속 docs 커밋은 prodgen build tree hash 가 P13 과 같아(`3cf198ed969342544775ecf9e8f3cfbaee8c573516dfcb50751fe82bc57aba8d`) 재승격 대상이 아니다(docs 커밋 뒤 `prodgen build` 로 확인).

## 3. 실행 결과표

| 구분 | 빌드 | 결과 | 관측 |
|---|---|---|---|
| main S1 canary os 3 | #528 | SUCCESS | 3/3 success · Portal 200 1회 · #274 대조 차이 0 |
| main S3 Linux 12 | #530 | SUCCESS | 12/12 · Portal 200 |
| main S2 혼합(실호스트 4 + TEST-NET 2) | #549 | SUCCESS | 4 success + 2 `TARGET_UNREACHABLE` · Portal 200 · 보충 0 — 승격 증거 계약이 요구하는 혼합 배치. Linux B 7대 #532 는 4 + 실패 3(기존) · #276 대조 차이 0 |
| main Linux A 8 | #533 | SUCCESS | 8/8 · #275 대조: 파일시스템 사용률만 |
| main S4 Windows 1 | #534 | SUCCESS | 1/1 · #277 대조 차이 0 |
| main E2E-D ESXi 6 | #535 (#529) | SUCCESS | 6/6 · #278 대조: datastore 사용률만 |
| main E2E-E Redfish 7 | #536 (#531) | SUCCESS | 7/7 · #279 대조: 시각 · 전력 · `hardware.uuid` 소문자 |
| main Redfish 10 | #537 | SUCCESS | 7 success + 3 실패(10.100.15.1 `PROTOCOL_CHECK_FAILED` · 10.100.15.3 · 10.50.11.231 `TARGET_UNREACHABLE`, 모두 기존) · Portal 200 · #279 대조: 실패 3대의 `sections.system` failed → not_supported(의도 — 채널 섹션 통일) · 시각 · 전력 · `hardware.uuid` 소문자 |
| main T2 TEST-NET 2 | #538 | SUCCESS | 2대 `TARGET_UNREACHABLE` 봉투 · Portal 200 1회 |
| main T6 Callback `127.0.0.1:9` | #539 | UNSTABLE | 전송 도구 상태 408(연결 거부) 3회(대기 10초 · 20초) · delivered=false · receipt uncertain · 거부 아님 · `callback_body.json` 보존 |
| main P11 실제 404(`/nonexistent-base`) | #548 | UNSTABLE | controller loopback 의 임시 404 서버 — HTTP 404 · `refused=true` · 전송 1회 · 재전송 없음 · "Portal이 요청을 거부했습니다. HTTP 404." (시험용 Portal 은 없는 경로에 302 를 주어 #540 은 302 · 3회 실패 · 거부 아님. #545 GitLab https 는 TLS 예외, #547 Runner 호스트 포트는 NoRouteToHost 예외 — 둘 다 예외형 통신 실패로 재시도 3회) |
| main P11 이름 풀이 실패(`portal.invalid`) | #541 | UNSTABLE | HTTP 404 + `transport=unknown_host`(플러그인 합성 404 식별) 3회 · 거부 아님 · receipt not_delivered · 기존 재시도 범위 그대로 |
| main E2E-A loc=cj | #542 | UNSTABLE | cj Runner 에서 실행 · 2대 실패 봉투 · Callback 408 3회 · delivered=false |
| main E2E-A2 loc=chj | #550 (#543 동일) | FAILURE | `[실행 위치] 등록되지 않은 Location: 'chj'` — 수집 없이 `OUTPUT_BUILD_FAILED` 봉투 2 · Portal 200 · fail-closed · #550 은 트리거 측 tip 관측(빌드 전후 `git ls-remote` 두 원격 모두 `46002a2b`)으로 revision 을 직접 바인딩 |
| main T5 `/stop` 8초 뒤 | #544 | ABORTED | `Aborted by admin` → `[수집] 중단됨: 빌드가 중단됐습니다(사용자 취소 또는 그 밖의 중단)` · 결과 보존 뒤 작업 폴더 유지(원인 미확정) · 12대 실패 봉투 · Portal 200 1회 · ABORTED 유지 |
| main 입력 확인 실측 | #520 · #521 · #522 | FAILURE · FAILURE · SUCCESS | sandbox `new ArrayList` 거부 → 리터럴 · Groovy 줄바꿈 이스케이프 → 수정 · os 3(미도달) 봉투 3 + Portal 200 |
| verify agent_lost_during_preserve | v2 #6 (`b16df688`) | SUCCESS | 실제 ChannelClosedException → 5분 뒤 shell step 종료 → Retrying → Runner 없음 → 바깥 재시도 → `[실행 대기]` → Agent 복귀 → "마지막 결과 보존이 끊겨 같은 작업 폴더에서 보존만 다시 합니다"(gather_attempts 1, 재수집 없음) → Portal 1회 200 |
| CI | #48 · #49 · #50 · #51 · #52 | ABORTED(#49 로 대체) · COMPLETE_PASS(승격 증거 보강 필요 → #549 · #550) · ABORTED(Controller 재시작) · UNSTABLE(일시적 이름 풀이 실패로 prodtree 2건 미판정) · SUCCESS · COMPLETE_PASS(전 단계 PASS) | 2-4 절 |
| production canary os 3 | #280 · #287 | UNSTABLE · SUCCESS | checkout == P13 · #280: 2 success + 10.100.64.161 `TARGET_UNREACHABLE`(대상 전원 꺼짐, 오전 #528 은 3/3) · Portal 수신 백엔드 미배포로 실제 404 → `refused=true` 1회 · 재전송 없음 · #528 대조(.162 .163) 차이 0 · #287(controller loopback 수신기): HTTP 200 1회 · 수신 본문 sha256 == `callback_body.json` · 2 success + .161 실패 |
| production 명부 | #281~#286 | UNSTABLE(전부 Portal 실제 404) | checkout == P13 · 결과 수 == 접수 수 · Linux A 7/8(.161) · Linux B 4/7(기존 .135 .145 .165) · Windows 1/1 · ESXi 6/6 · Redfish 8/10(10.100.15.1 `PROTOCOL_CHECK_FAILED` · 10.100.15.3 `TARGET_UNREACHABLE`, 10.50.11.231 은 오전 실패였으나 지금 success) · 오전 main 매트릭스와의 차이는 대상 쪽 변화라 같은 대상을 main Job 으로 다시 수집해 대조: #551↔#281 · #553↔#283 · #554↔#284 · #555↔#286 비휘발 차이 0, #552↔#282 사용률 1건 |

## 4. 문서

- 재작성: `README.md` · `REQUIREMENTS.md` · `docs/README.md` · `docs/overview/01,02` · `docs/operate/01~09`(07 업데이트·되돌리기 신설, 운영망 캡처는 `docs/develop/08` 로 이동) · `docs/contract/01,02,04` · `docs/develop/01~06` · 하위 README(common · normalize · redfish library · schema 4종 · tests 3종).
- 정정: `docs/contract/03-fields.md`(없는 `diagnosis.details.rmc_activation_check` 서술 제거 · vendor enum · 내부 어휘) · `docs/develop/05`(IPv6 · 채널 섹션 표) · `docs/reference/compatibility-matrix.md`(Redfish `system` 열 N/A) · `docs/reference/live-validation.md`(작업 진행 기록 절 삭제 · 끊긴 링크 4건 제거) · `docs/reference/decision-log.md`(도구 · 사람 이름 중립화).
- 사람용 문서의 개발 도구 전용 어휘(규칙 번호 · 작업 주기 · 내부 목록 · 작업자 이름) 0건, 상대 링크 깨짐 0건(`verify_docs_references.py` 통과). `docs/contract/03-fields.md` 와 참조 문서는 내용만 정정했고 문체(평서문)는 그대로다.

## 5. 확인하지 못한 것 · 남은 한계

- 실장비가 없는 벤더(Supermicro · Huawei · Inspur · Fujitsu · Quanta)와 세대(iDRAC 8 · iLO 4/5/7 · IMM2 · XCC3 · ESXi 6.x/8.x · Windows 2012R2~2019)는 fixture 와 어댑터만 확인했다.
- attempt_limit_lockwait 의 "고아가 잠금을 쥔 채 다음 시도가 기다리는" 상황은 stub 이 이 환경에서 만들지 못해 미검증이다(잠금 대기 코드 경로는 그대로다). 하네스 `attempt_limit_preserve` 시나리오도 실제 Jenkins timeout 경로가 아니라 40초 지연으로 흉내 내므로 그 통과를 실제 timeout 검증으로 적지 않는다(하네스 결함 — 보고만).
- P12 파서의 남는 차이(문자열 안의 탭 · 줄바꿈, 앞자리 0)는 `inventory.sh` 가 거부한다 — 대상 IP 문자열에는 해당하지 않는다.
- 기준선 JSON 에는 `thermal` 키가 없고 `hpe_baseline.json` 의 adapter 는 iLO6 adapter 추가 전 캡처라 실측 재캡처가 남아 있다(이번 범위 밖 — 실측 없이 기준선을 고치지 않았다).
- 설계 결정이 필요한 항목(변경하지 않음): ESXi storage 상태가 datastore 모듈에만 의존 · Windows IP 없는 NIC 제외 · `cpu.max_speed_mhz` 의미 채널 간 차이.
- production Job 에서 실제 Portal 200 은 받지 못했다. 승격 시점(11:52 UTC 이후)에 Portal 테스트 수신 백엔드(10.100.64.151:8080 의 `clovirone` 앱)가 내려가 있어 production 빌드 #280~#286 은 Tomcat 이 돌려준 실제 404 를 확정 거부로 기록했다(설계대로 재전송 없음). 같은 runtime tree 의 main 매트릭스(#528~#550)는 오전에 같은 주소에서 Portal 200 을 받았고, production 의 전송 경로는 저장소 `callback_sink.py` 수신기(#287, HTTP 200, 본문 sha256 일치)로 확인했다. 백엔드가 다시 배포되면 production canary 1회로 재확인한다(`docs/ai/NEXT_ACTIONS.md`).
- 이날 사내 환경 변동이 검증에 섞였다: Jenkins Controller 재시작(CI #50 ABORTED) · controller 의 일시적 이름 풀이 실패(CI #51 UNSTABLE) · Portal 수신 백엔드 중단(06:0x~10:01 UTC, 11:5x UTC 이후 재중단) · 대상 서버 재부팅 · 커널 업그레이드 · VM NIC 교체 · Dell BMC 재시작(11:57~12:01 UTC) · 10.100.64.161 전원 꺼짐. 제품 결함과 구분하기 위해 영향받은 대상은 main Job 으로 같은 시각에 다시 수집해 production 결과와 대조했다(#551~#555).
