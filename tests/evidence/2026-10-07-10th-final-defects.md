# 2026-10-07 — 10차: 결과 처리 재진입 · 기록 읽기 예외 · 끊긴 준비 · OOM 귀속 · 실환경 검증

> 지시서: "ClovirONE Gathering 최종 결함 보완 및 실환경 검증 작업지시서"(2026-10-06), 같은 날 "10차 실행계획 최종 보정기준" ·
> "10차 계획 검토 결과와 구현 확인 사항". 결정 근거: `docs/ai/decisions/ADR-2026-10-07-finalize-reentry-and-oom-attribution.md`.
> 운영 설명: `docs/operate/04-pipeline-runtime.md`. 호출자 계약: `docs/contract/04-failure-and-diagnosis.md`. 9차 결과: `tests/evidence/2026-10-06-9th-infra-wait-resume.md`.

## 0. 요약

- **고친 결함**(지시서 R1~R5 · 이번에 찾은 N1 · 보정 1)
  - R1: 결과 처리 중 실행 기반 오류 뒤 전송 없이 SUCCESS → 같은 빌드 안에서 다시 처리, 확인된 전송은 다시 보내지 않음, 결과 처리 시간 · Portal 시도 수를 진입 사이에 이어 센다.
  - R2(GP-61): 기록 파일 읽기 예외를 '기록 없음' 으로 → 원래 예외를 `retry(agent(), nonresumable())` 로 넘긴다(해석 실패만 손상).
  - R3: 첫 준비 도중 끊김 → 남은 준비만 마침(`prepared`) · 접수 목록 복원 · 확정 결과 IP 대조(사라졌으면 재수집 없이 재개 불가).
  - R4(GP-58): Add-on 결정 읽기 실패 뒤 다른 ref 를 새로 받음 → 결정 재사용 · 손상이면 남은 사본 commit · 사본도 없으면 Add-on 없이.
  - R5: 공유 cgroup 의 OOM 카운터를 이 실행의 원인으로 → 커널 로그의 OOM 종료 PID 가 이 실행의 것일 때만 원인.
  - N1: 마지막 보존 뒤 끊김 → 재개 불가로 끝나던 것을, 보관 또는 전달을 마쳤으면 다시 시도하지 않고 직전 판정으로 끝낸다.
  - 보정 1: 끊긴 뒤의 대기를 Jenkins 처리 유예(5분)만큼 앞당기던 계산을 없애고 감지 시각부터 센다.
- **실기에서 찾아 고친 결함 1건**: 커널 로그 시각(printk)을 `/proc/uptime` 과 비교해 이 실행의 OOM 을 놓쳤다(§5, `f9f38cea`).
- **실기 결과**: se-probe L3 · L4 · L5 · L6 · L8 재실행 · L9(Add-on 을 켠 재개) · R6(Linux · Windows · Redfish 대상 측 일시 장애) · Runner03 실제 커널 OOM 6사례 —
  모두 기대 동작(§4 · §5 · §6). Windows 는 대상 쪽 TCP 가 약 20초에 연결을 닫는 경계가 있고, Redfish 의 긴 차단은 섹션 실패(partial)로 끝난다(§6).
- **CI · 승격**: 최종 후보 main `fa05d122`(실행 코드는 `5dc8d0af` 와 같다) — CI #33 SUCCESS(Harness main 44/44 · 생성 tree 21/21 · Verify COMPLETE_PASS · Evidence PASS) · main Job 17 시나리오 기대 결과 · 명부 32대 성공 26 · 실패 6(9차와 같은 환경 항목) → **production P7 `61b9dd4a`**(GitHub · GitLab 일치, G01~G20 PASS) → production Job canary · 같은 매트릭스 · 명부 32대 같은 결과(§8~§10).
- **실기 미확인**(§12): GP-57 실장비 계정 쓰기 응답 유실 · ansible 작업자(fork) OOM 의 PID 연결(GP-64) · 72시간 자체.

## 1. 커밋 (main, `6ac78062` 다음)

| SHA | 제목 |
|---|---|
| `88c9250a` | fix: 결과 처리 재진입 · 기록 읽기 · 준비 · OOM 귀속 |
| `574454f5` | test: Harness 재진입 · 읽기 · 준비 · 보존 · Add-on 시나리오 |
| `ad2b08cf` | test: 실기 드라이버 실제 수집 · 망 장애 주입 도구 |
| `dcd89274` | harness: CI · prodgen 필수 시나리오 · rule 80 · 10차 ADR |
| `4fb63d6a` | docs: 10차 운영 · 계약 문서 갱신 |
| `2a0ef58f` | harness: PROJECT_MAP 지문을 10차 시험 도구로 갱신 |
| `f9f38cea` | fix: OOM 판정 기준점을 커널 로그 시계로 잡는다 |
| `af9402e6` | docs: OOM 판정 기준점 · 작업자 OOM 한계를 운영 문서에 |
| `5dc8d0af` | harness: 커널 로그 시계 결함을 ADR · 실패 패턴에 기록 |
| `e12eea21` | test: 보존 뒤 소유 기록 쓰기 중 끊김 시나리오 |
| `9c9f62c6` | harness: 보존 시나리오를 CI · prodgen 필수 집합에 더한다 |
| `98626e4a` | docs: 호출자 계약에 10차 OOM 근거 · 재개 불가 사유 |
| `f414887c` | test: 누적 한계 시나리오의 끊는 지점을 catch 밖으로 |
| `fa05d122` | test: 소유 기록 쓰기 끊김 시나리오를 이어지는 장애로 — **최종 후보(실행 코드는 `5dc8d0af` 와 같다)** |

`88c9250a` 뒤 실행 파일(`Jenkinsfile_portal` · `scripts/gather_state.py` · `scripts/run_gather.sh`)은 `f9f38cea`(gather_state.py) 한 번만 바뀌었다.
`5dc8d0af` 이후는 시험 · CI 목록 · 문서뿐이다.

## 2. 지시서 항목별 판정

| 항목 | 코드 근거 | 시험 | 빌드 · 기록 | 판정 |
|---|---|---|---|---|
| R1 결과 처리 재진입 | `seFinalizeAndCallback` 반복 · `fs`(진입 · 전송 · 시간 · 표식) · `seCallback` 시도 수 이어받기 · `seFinalizeIncomplete` | Harness `finalize_reentry` · `_after_delivery` · `_expired` · `_abort` · `finalize_limit_cumulative` · pytest 구조 | CI #32 Harness(main · tree) · 단일 #762 | 통과 |
| R2 기록 읽기 예외 | `seReadJsonFile`(absent · corrupt · 예외는 그대로) — 소유 기록 · 실행 기록 · Add-on 결정 | Harness `owner_read_transient` · `run_record_read_transient` · `addon_decision_transient` | CI #32 | 통과 |
| R3 끊긴 준비 · 접수 목록 · 사라진 결과 | `sePrepareWorkspace`(`prepared`) · 접수 목록 복원 · `gather_state.py begin` 확정 IP 대조(rc 92) | Harness `prep_cut_*` 3 · `manifest_missing_restore` · `results_missing_refuse` · pytest(같은 수 다른 대상 · 확정 기록 없는 대상) | CI #32 | 통과 |
| R4 Add-on 결정 | `seAddonPrepare`(결정 재사용 · 사본 commit 복원 · 없으면 끔) | Harness `addon_*` 3 · **실기 L9** | CI #32 · se-probe #6 | 통과 |
| R5 OOM 귀속 | `oom_link`(PID) · `kernel_log_mark` · `classify --user-abort` · `run_gather.sh` PID 기록 | pytest 반례 · **Runner03 실제 커널 OOM 6사례** | §5 | 통과(실기에서 결함 1건 찾아 고침) |
| N1 보존 표식 | `SE_FINAL_PRESERVED`(보관 또는 전달) · `seWriteOwner` | Harness `preserve_*` 6 | CI #32 · 단일 #764 | 통과 |
| 보정 1 확인된 시각 | `OFFLINE_GRACE` 삭제 · 감지 시각부터 대기 | 실기 L3 · L4 · L8 · L9(대기 시작 = 감지 시각) | §4 | 통과 |
| R6 시험 6 · 18 | 운영 설정 그대로(제품 코드 변경 없음) | **se-probe 실제 수집 + 대상 1대 패킷 차단** | se-probe #7~#10 | 통과 — Windows 는 대상 쪽 약 20초 경계(§6) |
| R7 전체 회귀 · 명부 · Kernel 6.x | — | main Job 매트릭스 · 명부 32대 · `.37 .38` | §9 | §9 |
| GP-57 실장비 쓰기 응답 유실 | — | — | — | **실기 미확인**(§12) |
| GP-58 Add-on 을 켠 재개 | R4 | 실기 L9 | se-probe #6 | 통과 |

## 3. Harness (main 함수 · 생성 tree 함수)

- CI #32(`5dc8d0af`): main 43 중 42 통과, 생성 tree 21/21 통과.
  - 실패 1: `finalize_limit_cumulative` #725 — 끊는 지점(`fileExists gather_final.jsonl` 2번째)이 회수 직후의 확인이라 "stash 를 못 쓰면 보관본으로" 넘어가는
    catch 안이었다. 오류는 다음 회수 수단으로 흡수돼 재진입이 없었다(그 흡수는 의도된 회수 동작이다). 끊는 지점을 catch 밖(3번째 — 정리 결과 선택)으로 옮겼다(`f414887c`).
  - 단일 실행 #762(`f414887c`): PASS — 진입 2 · 앞 진입이 쓴 결과 처리 시간 24초 · 남은 한계 3,575초(재진입이 처음부터 세지 않는다).
- 단일 실행 #763(`f414887c`) `preserve_cut_owner_write`: FAIL — 보존 끝의 소유 기록 쓰기는 실패를 기록만 하는 정리용 단계라 한 번 끊으면 재시도 없이 정상 종료한다
  (수집 결과 · 전달은 정상). 연결이 이어서 끊긴 경우(다음 `deleteDir` 도 실패)로 시나리오를 고쳤다(`fa05d122`) → #764 PASS(재시도 없음 · 재수집 없음 · completed).
  실행 기반 예외 종류를 Groovy 에서 가려 다시 던지는 수정은 하지 않았다(보정 3 — Jenkins 조건을 복제하지 않는다).
- 최종 CI #33(`fa05d122`): main 44/44 · 생성 tree 21/21(§8).

## 4. se-probe 실기 (Job `clovirone-cicd/se-infra-probe`, 노드 se-probe — Runner03 호스트의 별도 작업 폴더 · executor 1)

| 사례 | 빌드 | 한 일 | 관측 | 9차와 다른 점 |
|---|---|---|---|---|
| L3 끊김 · 프로세스 생존 | #1 | 수집 중 hold + 에이전트 종료, Jenkins 판정(5분) 뒤 1분 뒤 복구 | 1번째 시도는 끊긴 동안 2대를 끝내고 정상 종료(540초) · 2번째 시도는 남은 4대만 · 6/6. `같은 Runner 복구 대기` **63초**, 시작 = 감지 시각(06:48:21) | 9차 368초(5분 앞당김 포함) |
| L4 끊김 · 프로세스 종료 | #2 | 수집 중 hold + 에이전트 · 시도 프로세스 종료 | 1번째 `agent_disconnect`, 실행 시간 보수 60초(생존 표시) · 2번째는 4대만 · 6/6 · 대기 37초 | 같음 |
| L5 대기 한도 초과 | #3, 한도 480초 | 끊고 복구하지 않음 | `infra_wait_expired`(480/480초) · 6대 "수집을 실행하던 Runner 가 회복되지 않아 …" | 같음 |
| L6 대기 중 취소 | #4 | 같은 Runner 를 기다리는 중 `/stop` | 대기 interrupted 22초 · 다시 시도 없음 · ABORTED · 전송 1번 시도 · 6대 실패 결과 | 같음 |
| L8 끊긴 사이 작업 폴더 삭제 | #5 | 끊고 시도 프로세스 종료 + 작업 폴더 삭제 | `resume_impossible`(소유 기록 없음) · 가짜 ansible 수신 1번(재수집 없음) · 6대 실행 기반 문장 | 같음 |
| **L9 Add-on 을 켠 재개**(GP-58) | #6, 실제 수집 · 운영 상수 | 시험 Add-on(file://, commit A · B, main=A — 한 대만 Add-on 안에서 300초 대기). 다른 2대가 확정된 뒤 끊고 시도 프로세스 종료, 그 뒤 main 을 B 로 옮김(07:33:12), 복구 | 2번째 시도: "앞 시도에서 받고 검사한 Add-on(39e6dfb7…)을 그대로 씁니다" · 확정된 2대는 다시 수집하지 않음 · 남은 1대만 · 3/3 success · 세 대 모두 `data.addon.live_addon_version = "A"` · Add-on 완료(`addon_done`)는 대상마다 1번(끊긴 대상은 시작 2번 · 완료 1번) | 새 사례 |

- 끊긴 대상의 `meta.duration_ms` 312,972 는 Add-on 대기 300초를 포함한다 — GP-44(Add-on 시간 포함)의 실측이다.
- 실기 빌드의 SUCCESS · UNSTABLE 은 운영과 다를 수 있다 — 시험 함수 묶음이 `unstable()` 을 기록만 한다(`build_functions.py`).
- 시험 조건(`live_env.json`, Agent 사용자 `jenkins`): OpenSSH 8.7p1 · `ssh -G` 유효 값 ServerAliveInterval 10 · ServerAliveCountMax 3 · ConnectTimeout 60 ·
  ConnectionAttempts 1 · ControlPersist 60 · TCPKeepAlive yes · `tcp_keepalive_time` 7200 · `tcp_retries2` 15 · `dmesg_restrict` 0(커널 로그 읽기 가능).

## 5. Runner OOM 실기 (R5, Runner03, 실제 커널 OOM)

- 방법: Runner03 `/tmp/se-oom-probe-10th` 에서 후보의 실제 `scripts/run_gather.sh` · `gather_state.py` 를 가짜 ansible 로, Agent 사용자(jenkins)로 실행했다.
  모든 OOM 은 작은 임시 systemd scope(MemoryMax 64~128 MiB) 안에서만 났다. Runner03 노드 · se-probe 에 실행 중 빌드 0 일 때. 운영 프로세스는 건드리지 않았다.
- 가짜 ansible 은 `run_gather.sh` 의 PID 기록 래퍼로 실행돼 기록된 ansible PID 와 같은 PID 다.

| 사례 | 범위 | 일어난 일 | 고치기 전(기준점 /proc/uptime) | 고친 뒤(`f9f38cea`) |
|---|---|---|---|---|
| 다른 프로세스 OOM + 이 수집 rc 1 | 공유(OOMPolicy=continue) | 시도 시작 4초 뒤 들어온 다른 프로세스(512 MiB)가 OOM 으로 끝남, 수집은 스스로 1 로 끝남 | `failed_run`(관측만) | `failed_run`(관측만) |
| 다른 프로세스 OOM + 이 수집 `kill -9` | 공유 | 같은 OOM, 수집은 KILL | `process_lost`(원인 미확인) | `process_lost`(원인 미확인) |
| 다른 프로세스 OOM + 사용자 취소 | 공유 | 같은 OOM, 수집 트리에 TERM, `classify --user-abort` | `aborted`(Jenkins 사용자 취소) | `aborted` |
| 이 수집의 OOM | 공유(OOMPolicy=stop) | 커널이 기록된 ansible PID 를 OOM 으로 끝냄 → systemd 가 범위 정지(TERM) | **`aborted` — 결함** | `runner_oom`(PID 연결) |
| 9차 방식 격리 | 격리(64 MiB) | 같음 | **`aborted` — 결함** | `runner_oom`(PID 연결) |
| 대조 `kill -9` | 범위 없음 | OOM 없음 | `process_lost` | `process_lost` |

- 결함: 시도 시작을 `/proc/uptime` 으로 잡았는데 이 VM(VMware, clocksource tsc)의 커널 로그 시각이 약 22초 늦었다 — 시작 uptime 1357006.19, 그 뒤의 OOM 기록
  1356984.27. 기준점을 커널 로그 자신의 시계(시도 시작 때 마지막 줄 시각)로 바꿨다. 회귀 시험은 Runner03 실측 줄 그대로다
  (`test_this_runs_oom_is_linked_even_when_the_kernel_log_clock_lags_uptime`).
- Runner03 `/proc/vmstat oom_kill`: 2(9차) → 12. 모두 시험 범위 안의 가짜 프로세스다. 실패 상태로 남은 임시 scope 6개(9차 2개 포함)는 `systemctl reset-failed` 로 지웠다.
- 한계: ansible 작업자(fork) 프로세스의 PID 는 남지 않아 연결할 수 없다 — 작업자만 OOM 으로 끝나면 원인 미확인이다(GP-64).

## 6. 대상 측 일시 네트워크 장애 (R6 — 시험 6 · 18)

- 방법: se-probe 의 실제 수집(운영 상수 · 실 ansible · 실 vault)에서, `tests/jenkins/harness/net_fault_inject.sh`(root)가 se-probe Agent 세션 cgroup
  (`/user.slice/user-985.slice/session-1170.scope`)에서 대상 1대로 나가는 패킷만 버렸다. OS 는 그 대상의 `auth_proven`, Redfish 는 `cred_load` 진행 기록 뒤 3~5초에
  걸었다(Redfish 는 local 연결이라 `auth_proven` 이 없다). 끝나면 nftables 표를 지웠다 — 매번 `nft list tables` 는 `inet firewalld` 하나, 주입기 프로세스 0.
- 운영에 새 SSH · WinRM · HTTP 제한을 넣지 않았다. 유효 설정은 §4 시험 조건과 같다(WinRM operation 60 · read 70, Redfish 연결 60 · 응답 1,800초).

| 빌드 | 대상(대조) | 끊김 | 결과 | 다른 대상 | 실행 기반 대기 |
|---|---|---|---|---|---|
| #7 | Linux `.163` (대조 `.162`) | 15초(22:45:53~22:46:08, 8 패킷) | success — 30.5초(대조 10.5초) | success | 없음 |
| #7 | Windows `.120` | 20초(22:46:31~22:46:51, 20 패킷) | **그 대상만 failed** — `gather` · `GATHER_FAILED` "대상 OS에는 로그인했지만 정보를 가져오지 못했습니다." (`setup`: `RemoteDisconnected`) | success | 없음 |
| #8 | Linux `.163` | 600초(22:50:08~23:00:08, 47 패킷) | **그 대상만 failed** — 차단 40초 뒤 `lost`(ServerAlive 10 × 3), callback 보충 `gather` · `GATHER_FAILED` "정보 수집 중 대상 서버와 연결이 끊겼습니다." · `auth_success` true · ansible rc 4 · 시도 `completed` | success | 없음 |
| #8 | Windows `.120` | 8초 | success — 56초 | — | 없음 |
| #9 | Redfish `10.100.15.27` (대조 `.28`) | 20초(23:01:39~23:01:59, 8 패킷) | success — 67.6초(대조 36.5초) · 표준 계정 · 계정 쓰기 0 | success | 없음 |
| #10 | Redfish `10.100.15.27` | 600초(23:04:34~23:14:34, 64 패킷) | **그 대상만 partial** — 차단 중 요청마다 연결 60초에서 `URLError: timed out` → bmc · cpu · memory · storage · network · firmware · power 섹션 실패(섹션별 errors[]), 나머지 섹션은 차단이 풀린 뒤 성공 · 621.7초 · 표준 계정 · 계정 쓰기 0 | success | 없음 |

- Windows 경계: 20초 차단에서 클라이언트 설정(60/70초)보다 먼저 **대상(Windows) 쪽 TCP 가 재전송을 포기하고 연결을 닫았다**(Windows 기본 재전송 한계 약 20초 범위).
  끊긴 대상 하나만 실패하고 나머지는 계속됐으므로 지시서 기준(대상 측 장애는 기존 timeout · retry 로만, 그 대상의 결과로 끝냄)과 맞다. 8초는 회복됐다.
  Windows 의 장시간 차단은 같은 경로(대상이 연결을 닫음 → 그 대상만 실패)라 따로 돌리지 않았다.
- Redfish 는 요청마다 새 연결이라 차단 시간 동안의 요청만 연결 60초에서 실패하고 섹션 실패로 남는다. 차단이 길수록 실패 섹션이 늘 뿐, 실행 기반 대기 · 재수집 · 계정 쓰기로 번지지 않는다(timeout · TLS · transport 오류는 인증 실패로 보지 않는다 — CLAUDE.md §8).

## 7. 로컬 검증

| 구분 | 결과 |
|---|---|
| WSL `ci_gate`(커밋 전 작업 사본) | PASS — unit · e2e · regression 4,476 통과 · 182 건너뜀(Windows 전용) · 7 xfail · integration 324 · corpus 20/20 · 3채널 syntax-check |
| 커밋마다(`88c9250a` · `574454f5` · `dcd89274`, WSL) | 전부 통과. 줄끝 시험 4건 실패는 Windows `git archive` 가 CRLF 로 내보낸 탓 — `core.autocrlf=false` 로 다시 내보내 40 통과 |
| 고친 뒤(`f9f38cea` 등) | Windows `test_gather_state.py` · `test_run_gather.py` 56 통과(22 Linux 전용 건너뜀) · WSL 같은 파일 + `test_harness_tools.py` 103 통과 · Harness 도구 · CI · prodgen 169 통과 · schema · contract 925 통과 |
| Groovy | `Jenkinsfile_portal` 문법 검사(CompilationUnit CONVERSION, groovy 2.4.21) · 로컬 driver R1~R4 15/15 |
| prodgen 오프라인(`2a0ef58f`) | build OK · verify 정적 gate 전부 PASS · live gate SKIP → PARTIAL(오프라인 미리보기라 예상대로) |

## 8. Jenkins CI (`clovirone-cicd/clovirone-server-gather-ci`)

| 빌드 | 후보 | 결과 |
|---|---|---|
| #31 | `2a0ef58f` | 중단 — 실행 중 OOM 수정을 push 해 main 이 움직였고, Harness 의 MAIN_SHA 대조가 이후 빌드를 막았다(의도된 보호). 막히기 전 13개 PASS |
| #32 | `5dc8d0af` | UNSTABLE — Gate PASS(Runner 4,515 + 324) · corpus 20/20 · Time Limits 104 · Harness main 42/43(위 §3) · Build 195 파일 tree `9816ed3b…` · Harness tree 21/21 · Drift · Verify **COMPLETE_PASS**(G14 4,288 · G19 PASS) · Evidence(main 증거 없이 — PARTIAL) |
| **#33** | `fa05d122` | **SUCCESS**(1시간 19분) — Gate PASS(Runner 4,515 + 324 · 3채널 syntax-check · field_dictionary 195) · corpus 20/20 · Time Limits 104 · Harness main **44/44** · 생성 tree **21/21**(#766~#830) · Build 195 파일 tree `9816ed3b…` · Drift · Verify **COMPLETE_PASS**(G14 4,288 · G19 PASS) · Vault 복호화 · Evidence PASS(main Job 12 시나리오 #327~#339 + Harness · E2E-A2 는 SCM tip 관측 결속) · 필수 stage 전부 PASS |

## 9. main Job 매트릭스 (`fa05d122`)

9차와 같은 17 시나리오(같은 입력 — 9차 #310~#326 의 파라미터를 그대로 썼다). checkout 은 모두 `fa05d122`(입력 · 위치 단계에서 끝나는 T17 · E2E-A2 · DUP 는 checkout 없음).

| 시나리오 | 빌드 | 결과 |
|---|---|---|
| T2 TEST-NET 2 → sink | #327 | SUCCESS · 실패 2 · 전달 200 |
| T5 TEST-NET 4 → sink, 수집 시작 뒤 취소 | #328 | ABORTED · 실패 4 · 전달 200 |
| T17 `loc=ic`(등록 Runner 0) | #329 | FAILURE `config_error` · 실패 2(보충) · 전달 200 |
| T6 TEST-NET 2 → 닫힌 포트 | #330 | UNSTABLE · 408 × 3 |
| S5 Kernel 6.x `.37 .38` | #331 | 2/2 · 두 대 모두 `total_basis=physical_installed` 4,096 MB · 슬롯 1개 4,096 MB(visible 3,652) — 9차와 같다 |
| S1 `.161~.163 .120` | #332 | 4/4 |
| S4 Windows `.120` | #333 | 1/1 |
| S2 S1 + TEST-NET 2 | #334 | 4 + 실패 2 |
| E2E-A `loc=cj` | #335 | UNSTABLE(전송 실패 의도 — 닫힌 포트) |
| E2E-A2 `loc=chj`(미등록) | #336 | FAILURE · 실패 2(보충) |
| E2E-D ESXi 6 | #337 | 6/6 |
| E2E-E Redfish 2 | #338 | 2/2 |
| S3 실호스트 13 | #339 | 13/13 |
| Linux A 8 | #340 | 8/8 |
| Linux B 7 | #341 | 4 + 실패 3(`.135 .145 .165` — 9차와 같은 환경 항목) |
| Redfish 10 | #342 → **#344** 7 + 실패 3 · 전달 200 · 7대 표준(primary) 계정 · 계정 쓰기 0 | #342 는 파이프라인 시작 전 controller 의 `github.com` 이름 해석 실패(`Could not resolve host`)로 Jenkinsfile 을 받지 못했다(GP-55 와 같은 종류 — 결과 · 전송 없음). 같은 입력으로 다시 실행 |
| 중복 IP | #343 | FAILURE(입력 확인에서 거부 — `inventory_json[1] IP 가 중복됩니다`) |

- 명부 32대(Linux A 8 · Linux B 7 · Redfish 10 · Windows 1 · ESXi 6): **성공 26 · 부분 0 · 실패 6** — 9차와 같다. 실패는 같은 환경 항목이다:
  Linux `.135 .145 .165` · BMC `10.100.15.3` · HPE `10.50.11.231` 은 `TARGET_UNREACHABLE`, Cisco `10.100.15.1` 은 `PROTOCOL_CHECK_FAILED`(정상 Precheck 실패 6건).
- 증거 수집(최종 CI `E2E_MAIN_ENTRIES`): T2 · T5 · T6 · S1 · S2 · S3 · S4 · S5 · E2E-A · E2E-A2 · E2E-D · E2E-E(#327~#339).
  E2E-A2 의 리비전 결속은 SCM tip 관측으로 한다: 전 `fa05d122` · 후 `fa05d122`.

## 10. 승격 · production 검증

### 10-1. 승격

| 항목 | 값 |
|---|---|
| 방식 | 세션 CLI `python -m scripts.ai.prodgen promote --sha fa05d122 --verify-report <CI #33 집계> --e2e-evidence --ci-stage-results --push-remote origin,internal`(2026-10-07 09:36~09:51). G19 용 vault 암호 사본은 실행 동안만 두고 지웠다(`vault_removed=yes`) |
| 결과 | **P7 `61b9dd4a`** — parent P6 `a8833d47` · `Main-SHA: fa05d122` · `Tree-Hash: 9816ed3b…` · 196 파일(runtime 195 + provenance) · `CI-Build` #33 · `CI-Stages: verified` |
| 게이트 | G01~G20 전부 PASS. 이 PC 에서 다시 실행: G11~G15 · G18~G20. CI #33 결과 재사용: G01~G10 · G16 · G17 |
| 원격 | GitHub · GitLab · 로컬 production 모두 `61b9dd4a`(GitLab 은 origin 의 공유 push URL 로 도달) |
| 승격 뒤 G07 | 두 원격에서 줄끝 변환 없이(`core.autocrlf=false`) 새로 받은 사본: HEAD `61b9dd4a` · 196 파일 · G07 PASS(195 파일 · 보존 22) · 남은 `#` 모양 줄 37(YAML 문자열 안 셸 본문 — 9차와 같음) · 인코딩 선언 0 · 두 사본 동일 · 로컬 생성 tree 와 provenance 외 동일 |

### 10-2. production Job 검증 (`clovirone-cicd/clovirone-server-gather`, `*/production`)

승격 직후(2026-10-07 09:53~10:05). checkout 은 모두 `61b9dd4a`(입력 · 위치 단계에서 끝나는 T17 · DUP 는 checkout 없음).

| 시나리오 | 빌드 | 결과 |
|---|---|---|
| CAN-1 canary `.161 .162 .163` → Portal | #176 | SUCCESS 3/3 · 전달 200 · 파라미터 7개(시험용 없음) · 보존 14일/100 · 결과 파일 7일/50 |
| S1 | #177 | 4/4 |
| S2 | #178 | 4 + 실패 2(TEST-NET `TARGET_UNREACHABLE`) |
| T2 → sink | #179 | SUCCESS · 실패 2 · 전달 200 |
| T5 수집 시작 뒤 취소 | #180 | ABORTED · 실패 4 · 전달 200(1번) |
| T17 `loc=ic` | #181 | FAILURE `config_error` · 실패 2(보충) · 전달 200 |
| T6 → 닫힌 포트 | #182 | UNSTABLE · 실패 2 |
| S5 Kernel 6.x `.37 .38` | #183 | 2/2 · 두 대 모두 `physical_installed` 4,096 MB · 슬롯 1개(`RAM slot #0` 4,096 MB) |
| S3 실호스트 13 | #184 | 13/13 |
| Linux A 8 | #185 | 8/8 |
| Linux B 7 | #186 | 4 + 실패 3(`.135 .145 .165` `TARGET_UNREACHABLE`) |
| Windows | #187 | 1/1 |
| ESXi 6 | #188 | 6/6 |
| Redfish 10 | #189 | 7 + 실패 3(Cisco `10.100.15.1` `PROTOCOL_CHECK_FAILED` · `10.100.15.3` · HPE `10.50.11.231` `TARGET_UNREACHABLE`) |
| 중복 IP | #190 | FAILURE(입력 확인에서 거부) |

- 명부 32대: **성공 26 · 부분 0 · 실패 6**(정상 Precheck 실패 6건 — main Job · 9차와 같다). 모든 빌드에서 계정 쓰기(`account_service`) 0.

## 11. 이번 회차에 찾아 고친 결함

1. (R1~R5 · N1 · 보정 1 — §0) 지시서 결함.
2. 커널 로그 시각과 `/proc/uptime` 비교로 이 실행의 OOM 을 놓침 — Runner03 실기에서 발견, `f9f38cea`.
3. Harness 시나리오 설계 2건 — 끊는 지점이 의도된 흡수 catch 안이었다(`finalize_limit_cumulative`, `f414887c`) · 정리용 기록 쓰기만 끊었다(`preserve_cut_owner_write`, `fa05d122`).
   제품 코드 결함이 아니다.

## 12. 실기 미확인 · 한계

- **GP-57** Redfish 계정 쓰기 응답 유실의 실장비 확인: 하지 않았다. 응답 유실 중계 · 시험 계정 생성 도구를 이 세션의 안전 장치가 멈췄고, 우회하지 않았다.
  확인 근거는 9차의 mock 서버 시험(`test_account_lost_write_response.py`)뿐이다. 실장비에서 하려면 사용자가 직접 실행하거나 승인 경로를 정해야 한다.
- **GP-64** ansible 작업자(fork) 프로세스만 OOM 으로 끝나면 PID 를 이을 수 없어 원인 미확인이다(작업자는 자기 세션에서 돌고 PID 가 남지 않는다).
  systemd 가 범위를 멈추면 연결 끊김 경로로 재개되고, 아니면 ansible 이 그 실행을 실패로 끝낸다.
- 72시간 자체는 줄인 상수(Harness · L5 480초)로만 확인했다.
- Windows 장시간 차단은 20초 사례(대상이 연결을 닫음)로 갈음했다(§6).

## 13. 임시 자원 정리

| 자원 | 처리 | 확인 |
|---|---|---|
| Jenkins 노드 `se-probe` · Job `clovirone-cicd/se-infra-probe` | 삭제(2026-10-07 09:54) | 노드 목록 Built-In · Runner01~04 만, Job 404 |
| Runner03 `/app/jenkins-agent/se-probe` · `se-probe.hold` · 시험 Add-on `se-probe-addon.git` | 삭제 | `/app/jenkins-agent` 는 `agent` · `conf` 만, se-probe 에이전트 프로세스 0 |
| Runner03 OOM 시험 `/tmp/se-oom-probe-10th` · 임시 scope(9차 2개 포함 6개) | 삭제 · `systemctl reset-failed` | scope 0 · `/proc/vmstat oom_kill` 12(되돌릴 수 없음 — 모두 시험 범위 안) |
| Runner03 장애 주입 `/tmp/se-net_fault_inject.sh` · 기록 · nftables 표 | 삭제(표는 주입기가 매번 스스로 삭제) | `nft list tables` = `inet firewalld` 하나 · 주입기 프로세스 0 |
| Runner03 끝나지 않고 끝난 시험 시도의 `/tmp/se_vault.*` · `/tmp/se_cp.*`(L5 · L6 · L8, GP-63) | 이름을 지정해 삭제(L4 · L9 는 재개 시도가 스스로 지움) | 남은 것 0 |
| 이 PC 의 접근 파일 · 시험 도구(scratchpad) | 작업 끝에 삭제 | §14 직전 확인 |

운영 Runner01~04 의 노드 · 라벨 · executor · 설정은 바꾸지 않았다.

## 14. 남은 사용자 결정

- GP-38: Runner01 · 02 · 04 의 `cj` 라벨은 이 프로젝트의 임시 설정임을 확인할 근거가 없어(설정 이력 없음) 지우지 않았다. `loc=cj` 배정이 이 라벨을 쓴다.
- GP-52: 추적 파일의 자격 값 0건(이번 회차 확인) · 이력 재작성은 하지 않았다.
- GP-57 · GP-64: §12.
