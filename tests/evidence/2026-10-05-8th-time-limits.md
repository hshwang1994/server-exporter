# 2026-10-05~06 — 8차: 시험 입력 제거 · 실제 시각 · 장시간 대기 · 숨은 실패 · 원격 정리 · 운영 문구 · 보존 정리 (R1~R8)

지시서 "ClovirONE Gathering 최종 통합 후속 작업지시서"(2026-10-05, R1~R8)에 대한 실행 기록이다.
시작 기준은 main `6dc4f829` · production P4 `5ac5566c` 다. 7차 기록은 `2026-10-05-final-maintenance.md`. 결정 기록은
`docs/ai/decisions/ADR-2026-10-05-time-limits-and-test-inputs.md`.

## 0. 요약

| 항목 | 결과 |
|---|---|
| 최종 후보 (main) | **`8c9e04a9`** — GitHub · GitLab · 로컬 일치 (첫 후보 `85630d2c` 의 실행에서 운영 문구 2건 · 시험 표식 2건을 찾아 고쳤다, §8) |
| production | **P5 `f43af470`**(main `8c9e04a9` · parent P4 `5ac5566c` · Tree-Hash `54cf8028…`) — GitHub · GitLab · 로컬 일치, 승격 판정 COMPLETE_PASS (§9) |
| 로컬 시험 | WSL unit · e2e · regression 4,380 통과 · integration(not live) 324 통과 · Windows 전용 PowerShell 99 + 71 통과 · 생성 tree G14(4,220) · G15 PASS (§3) |
| main Job (후보 `8c9e04a9`) | #260~#275 16 빌드 전부 기대 결과 — 정상 입력만, 시험용 파라미터 없음 (§8) |
| CI | #24(`85630d2c`) FAILURE — G14 의 시험 표식 2건(§8-3) → **#25(`8c9e04a9`)** SUCCESS — 10 stage PASS(승격은 CI 에서 하지 않음) · Verify COMPLETE_PASS · Evidence 42/42 (§8-4) |
| R6 원격 정리 | Linux `.161` 7 상황 모두 남은 원격 명령 0(고치기 전 한계 1 · sudo 한계 3) — WSL(ansible-core 2.20.7) · Runner02(2.20.3) 둘 다 (§6) |
| R8 보존 · 정리 | main · production Job 빌드 기록 14일/100 · 결과 파일 7일/50 등록 확인 · Runner 첫 정리에서 지난 제어 폴더 main 210개 · production 157개 삭제(+ 소유 기록 없는 옛 폴더 1개는 확인 뒤 수동 삭제) · 디스크 `/app` 60 GB 중 3~4 % 사용 (§7) |
| production 검증 | production Job #144~#159 16 빌드 전부 기대 결과 · 수집 빌드 checkout `f43af470` · 명부 32대 성공 26(main 과 같음) · 파라미터 7개 · 보존 14일/100 · 7일/50 등록 · Tier 2 설정 해제 뒤 #158 · #159 정상 (§9) |

## 1. 판정표 (R1~R8)

| # | 원인 | 수정 | 회귀 · 증거 |
|---|---|---|---|
| R1 | 운영 수집 Job 에 시험 전용 `redfishAccountDryrun` · `gatherBudgetForceSec` 와 배선(`-e _rf_account_service_dryrun` · `SE_FORCE_SEC` · 빌드 이름 `[시험: …]` · 감시 끄기)이 남아 있었고, 승격 증거(S3 · E2E-E)가 그 입력에 기댔다 | 파라미터 · 배선 삭제(다른 환경변수로 옮기지 않음). 증거 분담: 운영 Job 은 정상 입력만 — S3 = 실호스트 13대 정상 배치(운영 한계, 보충 0), E2E-E = 정상 Redfish(표준 계정 · 계정 쓰기 0). 한계 도달 · 보존은 Harness `gather_limit_preserve`(실제 `run_gather.sh`), 계정 쓰기 방지는 CI Gate 단위 시험. 증거 수집기는 없앤 파라미터가 빌드에 남았거나 콘솔에 `[시험:` 이 있으면 그 빌드를 받지 않는다. Redfish 모듈 dry-run · 복구 계약은 유지 | `test_jenkinsfile_portal_preserve_and_params.py` · `test_env_guard.py` · `test_gather_budget.py` · `prodgen/test_verdict_evidence.py`(S3 · E2E-E · `test_params_absent` · `no_test_tag`) · Harness `gather_limit_preserve` main · 생성 tree. 실측: main Job 파라미터 7개뿐(main #243 이후), E2E-E #270 표준 계정 · `account_service` 비어 있음 |
| R2 | 콘솔에 실제 시각이 없었다. 기록용 시각 · 시도별 전송 기록이 없었고, 전송을 시작하지 않아도 `attempted=true` 였다 | Timestamper `timestamps {}`(Job 범위, 없으면 생략) · 업무 줄 본문에 `[YYYY-MM-DD HH:MM:SS +09:00]` · `finalize_summary.json` 의 `times` · `callback.tries[]`(UTC ISO) · `gather_run.json`. 기계용 줄 · JSON 줄에는 접두어 없음. 증거 수집기는 Timestamper 접두어를 견딘다. envelope · `duration_ms` 불변 | `test_jenkinsfile_portal_finalize.py` · `test_run_gather.py` · `prodgen/test_verdict_evidence.py`(접두어) · 실측 §5 |
| R3 · R4 | 짧은 제한이 여러 겹이라 정상적으로 오래 걸리는 수집이 잘렸다(작업 단위 120~300 s · Redfish 모듈 1,200 s/120 s · 정체 감시 420 s · `df` 20 s · 결과 정리 120 s · 보존 · 조립 30~60 s) | 한계 셋: 빌드 12 h · 수집 실행 최대 6 h(실제 시작 기준) · 결과 확인 및 전송 1 h. 나머지 삭제, 연결 60 s · 응답 대기(수집 API 30 min · Portal 시도당 10 min)는 통신 규약 값으로 유지. 표 §4 | `test_time_limits.py`(값 일치 · 합) · `test_remote_task_timeouts.py` · `test_redfish_request_timeouts.py` · `test_gather_budget.py` · `test_run_gather.py` · Add-on 실제 ansible(오래 걸리는 태스크 대기 · 한계로 멈춘 뒤 CHECKPOINT 복원) |
| R5 | ESXi 디스크 모듈 실패 · Windows Hyper-V 서비스 조회 실패(없음 · 멈춤과 구분 안 됨) · `Get-NetAdapter` 등의 끝나지 않는 오류 · setup 실패 · `Get-Volume` 실패가 기록 없이 빈 값이나 잘못된 값이 됐다 | 섹션 상태는 그대로, 받은 값은 보존, `errors[]` 1건(문장 · 기술 근거). "찾는 항목 없음"(IPv6 기본 경로 없음 등)은 실패가 아니다 — 이 PC 의 실제 PowerShell 로 오류 종류를 실측 | `test_windows_hidden_failures.py`(실제 powershell.exe) · `test_windows_call_consolidation_*` · `test_esxi_section_errors.py` · main S4 #265 오류 0 · ESXi 6/6 |
| R6 | ansible 작업 프로세스가 자기 세션에서 돌아 한계의 INT 가 주 프로세스에만 갔고, SSH 다중화 연결이 남아 원격 명령이 계속 돌았다 | `scripts/run_gather.sh` 가 실행마다 자기 다중화 위치를 쓰고 끝나면 그 연결만 닫는다(`ssh -O exit` + 그 위치를 가진 ssh 만 종료). Linux 명령은 pty 와 함께(`ansible_ssh_use_tty`) | `test_run_gather.py`(가짜 master · 다른 프로세스 보존) · 실측 §6 |
| R7 | 운영 문구에 구분 기호 · 내부 용어가 섞였고, 한계로 끝난 실행이 무엇이 어떻게 됐는지 설명하지 않았다. 2xx 를 저장 완료처럼 적을 여지가 있었다 | 문장으로 · 하는 일로. `[수집 종료]` 가 한계 · 실행 시간 · 끝난/끝나지 않은 대상 · 보존 · 전송을 나눠 적는다. 2xx = "Portal 이 요청을 받았다". 운영 결함과 환경 항목을 나눈다(§10). 후보 실행에서 찾은 3건(새 빌드 폴더를 소유 불명으로 알림 · 수집 안 한 빌드를 보존 실패로 적음 · 취소된 수집의 실행 시간 없음)도 고쳤다 | `test_jenkinsfile_portal_finalize.py` · `test_workspace_cleanup.py` · 실측 #261 · #268 |
| R8 | 빌드 기록 · 결과 파일 보존 기간이 없었다. 보관 실패 빌드의 작업 폴더와 제어 폴더(`@tmp`)가 쌓였다. 빈 보관도 성공으로 셌다 | `buildDiscarder` 14일/100 · 7일/50. 빌드별 작업 폴더 `<Job>-<번호>` 소유 기록 · 필수 결과를 이름으로 보관(빈 보관은 실패)했을 때만 삭제 · `scripts/workspace_cleanup.py` 하루 한 번 7일 정리(보관 못 한 결과는 남김) · 컨트롤러 결과 확인 폴더도 빌드별 | `test_workspace_cleanup.py` · `test_jenkinsfile_portal_preserve_and_params.py` · 실측 §7 |

## 2. 커밋 (main)

| 커밋 | 내용 |
|---|---|
| `1787673c` | feat: 시간 한계 셋 · 원격 명령 정리 · 보존 기간(R1~R8 runtime + 시험) |
| `8d05fc23` | test: 시험 경로를 Harness 와 CI 로(gather_limit_preserve · Tier 2 삭제 · 증거 수집기) |
| `111f0241` | docs: 시간 한계 표 · 원격 정리 · 보존 기간 |
| `85630d2c` | harness: ADR · rule 80 Stage 표 · 파이프라인 카탈로그 · PROJECT_MAP 지문 |
| `c0117fd6` | fix: 시작 중인 빌드 폴더 · 보존 없는 빌드의 문구(main #244 · #252 관측) |
| `38e39c75` | fix: 취소된 수집도 실행 시간(main #245 관측) |
| `8c9e04a9` | test: main 전용 파일을 읽는 새 시험 2건 source_text(CI #24 G14) |

## 3. 로컬 검증

- WSL(ansible-core 2.20.7 · Python 3.12): unit · e2e · regression **4,380 통과** · 건너뜀 145(Windows 전용) · xfail 7, integration(not live) **324 통과**.
- Windows: PowerShell 실제 실행 시험 99(`test_windows_call_consolidation_powershell` 42 · `_render` 57) · `test_windows_hidden_failures` 71 통과.
- `ci_gate.sh`(WSL, pytest 제외): corpus 18/18 MATCH · 3채널 syntax-check · vendor boundary · harness consistency PASS.
- 생성 tree(`8c9e04a9`, tree `54cf8028…`) 위 G14 **4,220 통과**(41 source_text 제외) · G15 PASS — CI #24 의 G14 실패 2건이 고쳐졌음을 push 전에 확인.

## 4. 시간 한계 표 (분류)

| 한계 | 값 | 분류 | 근거 |
|---|---|---|---|
| 빌드 전체 | 12 h | 유지(바깥 틀) | `options.timeout` = 5 min + 5 min + 39,000 s + 1 h |
| 입력 확인 · 실행 위치 확인 | 각 5 min | 병합(PRE 600) | 노드 없음, 파일 하나 |
| 서버 정보 수집 단계 | 39,000 s | 유지 | Runner 대기 · 준비 · 수집 · 보존 몫 포함 |
| 수집 실행 한계 | 최대 6 h(실제 시작 기준, 빌드 남은 시간 안) | **유지 — 유일하게 멈추는 한계** | `gather_budget.sh` → `run_gather.sh` |
| INT 뒤 정리 | 90 s | 유지(규약) | `--kill-after` |
| 결과 보존 몫 | 900 s | 병합(예약) | 단계별 제한 없음 |
| 결과 확인 및 전송 | 1 h | 유지 | 노드 대기 포함 합산 |
| Portal 응답 대기 | 시도당 10 min · 최대 3번 | 유지(규약) | http_request 는 연결 · 응답 같은 값 |
| SSH 연결 · keepalive | 60 s · 10 s × 3 | 유지(규약) | 연결 수립만 |
| OS 후보 포트 연결 | 포트당 10 s | 유지(규약) | DROP 방화벽 · SYN 재시도 |
| OS 프로토콜 응답 | 60 s | 유지(규약) | 배너 · Identify |
| WinRM 작업 · 읽기 | 60 · 70 s | 유지(규약) | 긴 명령은 다시 받아 기다린다 |
| Windows setup 수집기 | 30 min | 유지 | 기본 10 s 는 값을 빼먹는다 |
| Redfish 연결 · 응답 | 60 s · 30 min | 유지(규약) | 읽기 한 번마다 |
| ESXi 응답 · 사전 점검 | 30 min · 포트 60 s | 유지(규약) | 읽기 한 번마다 |
| Add-on 받기 | git 명령당 30 min × 2 | 유지(준비) | 준비가 길면 수집 한계가 줄어든다 |
| 작업 단위(Linux 120 · Windows/ESXi 180 · Add-on 300 · Redfish 탐지 120 · 수집 1,260 · 계정 240 s) | — | **삭제** | 정상 작업을 잘랐다 |
| Redfish 모듈 마감(절대 1,200 · 새 응답 없음 120 · 탐지 90 · 계정 180 s) · 진행 표시 | — | **삭제** | 진행 판정이 HTML 200 도 진행으로 셌다 |
| 정체 감시 420 s(`gather_watch.py`) | — | **삭제** | |
| `df` 20 s · 결과 정리 120 s · 보존 archive/stash 30 s · 회수 30 · 조립 60 · 본문 60 s · Tier 2 · Script Approval | — | **삭제** | |
| 시험용 강제 한계 `SE_FORCE_SEC` | — | **삭제(R1)** | |

## 5. 시각 기록 예시 (main #245 · #246, Timestamper 접두어 포함)

```text
[2026-10-05T22:52:28.275Z] [2026-10-06 07:52:28 +09:00] [수집] 시작합니다. 대상 4대, 동시 실행 4대, 실행 한계 6시간(21600초).
[2026-10-05T22:52:30.740Z] [2026-10-06 07:52:30 +09:00] [수집] 중단됨: 사용자 취소 또는 다른 중단입니다. 확보한 결과를 보존하고 전송으로 넘어갑니다. (outcome=aborted)
[2026-10-05T22:52:31.672Z] [2026-10-06 07:52:31 +09:00] [결과 보존] 시작합니다. 수집 종료 상태: 사용자 취소 또는 단계 시간 한계로 중단(aborted)
[2026-10-05T22:52:42.286Z] [2026-10-06 07:52:42 +09:00] [Portal 전송] 1번째 전송을 시작합니다. 응답은 최대 10분 기다립니다.
[2026-10-05T22:52:42.532Z] [2026-10-06 07:52:42 +09:00] [Portal 전송] HTTP 200 응답을 받았습니다. 소요 시간: 0.2초. 2xx 는 Portal 이 요청을 받았다는 뜻입니다.
```

`finalize_summary.json`(#246 T6): `times{build_started_at 22:52:26.505Z · gather_started_at 22:52:43.122Z · gather_ended_at 22:53:22.361Z · finalize_started_at 22:53:35.755Z}` ·
`limits{gather_limit_sec 21600 · gather_limit_source gather_limit · finalize_limit_sec 3600}` · `callback.tries[]` 3건(시도마다 `started_at` · `timeout_sec 600` · `ended_at` · `elapsed_ms` · `http_code 408` · 재시도 대기 10 · 20 s).

## 6. 원격 명령 정리 실측 (R6)

`tests/jenkins/harness/remote_cleanup_probe.sh` 가 운영 실행 스크립트 `scripts/run_gather.sh` 로 Linux `.161`(RHEL 8.10)에 표식 `sleep` 을 띄운 뒤 멈추고, 새 연결로 남은 표식 프로세스를 센다.

| 상황 | 고치기 전(WSL) | 고친 뒤 WSL(2.20.7) | 고친 뒤 Runner02(2.20.3) |
|---|---|---|---|
| 출력 없이 200 s 걸리는 명령, 한계 400 s | 완료 | 완료(rc 0, 202 s) | 완료(rc 0, 202 s) |
| 실행 한계 25 s | **1개 남음** | 0 (rc 124, 연결 1개 닫음) | 0 |
| 빌드 취소(빌드 프로세스 전부 TERM → KILL) | 0 | 0 (rc 143) | 0 |
| 연결 종료(ssh KILL) | 0 | 0 (rc 2) | 0 |
| 실행 한계 + sudo | **3개 남음** | 0 | 0 |
| 취소 + sudo · 연결 종료 + sudo | 0 | 0 | 0 |

Runner02 실행은 CI 작업 폴더(`8c9e04a9` 이전 후보 `85630d2c` 의 checkout)에서 필요한 파일만 cloviradmin 홈으로 복사해 돌렸고, vault 암호 파일(600)은 실행 끝에 지웠다(확인). 남는 한계: D 상태 프로세스, 네트워크 단절로 대상 sshd 가 모르는 연결.

## 7. 보존 · 디스크 · 정리 (R8)

- Job 설정(main, #243 첫 실행 뒤 `config.xml`): `daysToKeep 14 · numToKeep 100 · artifactDaysToKeep 7 · artifactNumToKeep 50`. 파라미터 7개. production 도 P5 첫 빌드 #144 뒤 같은 값 · 파라미터 7개(§9).
- Runner 디스크(2026-10-06 07:3x, sudo 읽기): `/app` 60 GB — 사용 2.0 · 2.0 · 1.8 · 1.6 GB(3~4 %). 에이전트 루트 868 · 874 · 701 · 534 MB(대부분 CI · Harness 작업 폴더).
- 정리 전: 지난 빌드의 빈 제어 폴더(`@tmp`) main 86 · 55 · 40 · 42개, production 57 · 45 · 30 · 26개, Runner01 에 소유 기록 없는 `clovirone-server-gather-28`(2026-09-30, `.git` 만).
- 첫 정리(main Job, Runner 마다 첫 빌드): Runner01 #243 **81개** · Runner04 #244 **39개** · Runner03 #245 **38개** · Runner02 #246 **52개** 삭제(빈 폴더라 0.0 MB). 같은 날 뒤 빌드는 "하루 한 번" 으로 건너뜀.
- 정리 뒤: main 기본 폴더 0 · 이번 빌드의 제어 폴더 0(빌드가 보관 확인 뒤 스스로 지움) · 13시간이 안 된 #229~#242 제어 폴더 13개는 남김(다음 날 정리).
- production 첫 정리(P5, Runner 마다 첫 빌드): Runner02 #144 **45개** · Runner04 #146 **26개** · Runner03 #147 **30개** · Runner01 #148 **56개** 삭제(빈 제어 폴더) — 정리 전 집계와 같다(Runner01 은 57개 중 `-28@tmp` 를 `-28` 과 함께 남김). 소유 기록 없는 `clovirone-server-gather-28` 은 정리가 남긴 것을 확인한 뒤 수동 삭제(§12).
- 모든 정리 뒤(10:07): production 작업 폴더 4대 모두 0 · main 은 위 13개만 · `/app` 사용 2.0 · 2.0 · 1.8 · 1.6 GB(3~4 %) · 에이전트 루트 868 · 876 · 701 · 535 MB.
- 컨트롤러 결과 확인 폴더: 빌드별 `fin-<번호>`, 보관 확인 뒤 삭제. "정리할 결과 확인 폴더가 없습니다"(첫 실행).

## 8. Jenkins 실행

### 8-1. 첫 후보 `85630d2c`

- 등록 실행 main #243(TEST-NET → 닫힌 포트, UNSTABLE 기대) — 새 Jenkinsfile 이 파라미터 7개 · 보존 기간을 등록. 증거로 쓰지 않는다(옛 파라미터 이름이 남은 빌드).
- 증거 실행 #244~#259 16 빌드 전부 기대 결과(T2 SUCCESS · T5 ABORTED · T6 UNSTABLE · S5 · S1 · S4 · S2 SUCCESS · E2E-A UNSTABLE · E2E-A2 FAILURE · ESXi 6/6 · E2E-E 2/2 · S3 13/13 · Linux A 8/8 · Linux B 4+3 · Redfish 7+3 · 중복 IP FAILURE).
- 운영 문구에서 찾은 것(고침 → `c0117fd6` · `38e39c75`): #244 의 정리가 막 시작한 #249 의 폴더를 "소유를 모르는 폴더" 로 알림 · #252(수집 안 함)가 "결과 보존: 실패" · #245(취소)가 "실행 시간 기록 없음".

### 8-2. CI #24 (`85630d2c`)

Gate PASS(Runner pytest 4,378 + integration 324 · syntax-check) · Corpus(Groovy 18 · 입력 규칙 35 × 3) · Time Limits Self-test 39 passed · Harness main **19/19**(gather_limit_preserve #485: 실제 `run_gather.sh` 8 s 한계 · rc 124 · timed_out · 2대 보존 · 1대 보충 · 전달 200 · 25 checks) · 생성 tree **11/11** · Verify **FAIL — G14 2건**.

### 8-3. G14 실패와 수정

`test_workspace_cleanup.py::test_pipeline_wires_the_cleanup_and_records_ownership`(production_manifest.yml) · `test_harness_tools.py::test_harness_pipeline_has_no_tier2_and_runs_the_real_run_gather`(jenkins/jobs) 가
production tree overlay 에 없는 파일을 읽었다 — 7차 FAILURE_PATTERNS 의 재발 방지(로컬 G14 먼저)를 이번에도 지키지 않았다. `source_text` 표식(`8c9e04a9`) 뒤 로컬 G14 4,220 · G15 PASS 를 확인하고 push 했다.

### 8-4. 최종 후보 `8c9e04a9`

main #260~#275 16 빌드 전부 기대 결과(위와 같은 분포) · 전부 checkout `8c9e04a9`(E2E-A2 · 중복 IP 는 수집 단계 없음) · 고친 문구 확인(#261 "실행 시간 4초" · #268 "수집을 시작하지 않았습니다" · "수집 단계가 실행되지 않아 보존할 결과가 없습니다").
E2E-E #270 · Redfish 10 #274: 닿는 BMC 7대 모두 표준 계정 첫 시도 성공(`used_role primary` · `fallback_used false`) · `account_service` 비어 있음 = 계정 쓰기 0.

CI #25(`8c9e04a9`, 37분) **SUCCESS** — Gate PASS(Runner pytest unit · e2e · regression 4,380 · integration 324 · 3채널 syntax-check) · Corpus Python/Groovy 18/18 MATCH · Time Limits Self-test 39 passed · Harness main **19/19**(#498~#516, `gather_limit_preserve` #516) · Prodgen Build tree `54cf8028…`(195 파일, 로컬 계산과 같음) · Harness 생성 tree **11/11**(#517~#527) · Drift PASS · Verify **COMPLETE_PASS**(G14 Runner 4,166 통과) · Vault 복호화 · 구조 PASS(값 미출력) · Evidence **42/42**(main #260~#271 12 빌드 + Harness 30, 전부 `8c9e04a9` 직접 결속, E2E-A2 는 tip 관측으로 결속). 승격(PROMOTE)은 CI 에서 실행하지 않는다 — 세션 CLI(§9).

## 9. 승격 · production 검증

### 9-1. 승격 (세션 CLI)

`python -m scripts.ai.prodgen promote --sha 8c9e04a9 --verify-report <CI #25 집계> --e2e-evidence --ci-stage-results --push-remote origin,internal` —
2026-10-06 09:34:40~09:49:58(15분 18초) → **COMPLETE_PASS → P5 `f43af470c17c`**.

| 항목 | 값 |
|---|---|
| 게이트 | G01~G20 전부 PASS. 이 PC 에서 다시 실행: G11 G12 G13 G14 G15 G18 G19 G20(G14 = Windows pytest 09:36~09:46, G19 = WSL 3채널 실제 실행 — vault 암호 파일은 실행마다 만들고 지움). CI #25 결과 재사용: G01~G10 G16 G17 |
| 커밋 | `f43af470` · parent P4 `5ac5566c` · tree `00708384` · 196 파일(runtime 195 + `.production-provenance.json`) |
| trailer | `Main-SHA 8c9e04a9` · `Tree-Hash 54cf8028…`(CI #25 Build · 로컬 계산과 같음) · `Previous-Production 5ac5566c` · `CI-Build …/clovirone-server-gather-ci/25/` · `Verdict COMPLETE_PASS` · `CI-Stages verified` · `Gates-Rerun` · `E2E-Evidence-SHA256` |
| 게시 | origin "accepted by remote" · internal "already at the new commit (reached via a shared push URL)" — origin 의 push URL 에 GitLab 이 들어 있다. `git ls-remote` 로 GitHub · GitLab 모두 production `f43af470` · main `8c9e04a9` 확인 |
| 비밀값 · 임시 폴더 | scratchpad 의 vault 암호 사본은 승격 직후 삭제(`vault_removed=yes`). WSL 작업 폴더 4개(약 12 MB)는 검증 뒤 삭제 |

### 9-2. production Job 검증 (P5, #144~#159)

| 빌드 | 시나리오 | 결과 | 확인 |
|---|---|---|---|
| #144 | canary os 3대 → Portal | SUCCESS 53초 | 3/3 · Portal 200 · 파라미터 7개 · 보존 14일/100 · 7일/50 등록 · Runner02 첫 정리 45개 |
| #145 | S1 os 4대(`.161~.163` · Windows `.120`) | SUCCESS | 4/4 |
| #146 | S2 = S1 + TEST-NET 2 | SUCCESS | 4 + 실패 2(`TARGET_UNREACHABLE`) · Runner04 첫 정리 26개 |
| #147 | T2 TEST-NET 2 → sink | SUCCESS | 실패 2 · 전달 200 · Runner03 첫 정리 30개 |
| #148 | T5 TEST-NET 4 → sink, 수집 중 취소 | ABORTED | 1번 전송 200 · 결과 보존 완료 · Runner01 첫 정리 56개(`-28` 은 소유 기록이 없어 남김) |
| #149 | T6 TEST-NET 2 → 닫힌 포트 | UNSTABLE | 3번 시도 408 · 본문 `callback_body.json` 보존 |
| #150 | S5 Kernel 6.12(`.37` · `.38`) | SUCCESS | 2/2 — §10 memory 대조 |
| #151 | S3 실호스트 13대 | SUCCESS 3분 37초 | 13/13 · 보충 0 · 한계 사유 없음 |
| #152 | Linux A 8대 | SUCCESS | 8/8 |
| #153 | Linux B 7대 | SUCCESS | 4 + 실패 3(명부 미해결) |
| #154 | Windows `.120` | SUCCESS | 1/1 · `errors[]` 0 |
| #155 | ESXi 6대 | SUCCESS | 6/6 |
| #156 | Redfish 10대 | SUCCESS 6분 34초 | 7 + 실패 3(명부 미해결) · 표준 계정 7/7 · 계정 쓰기 0 · Cisco `.2` 348초 |
| #157 | 중복 IP | FAILURE | 입력 확인에서 거부 — 수집 · 작업 공간 checkout 없음 |
| #158 | Tier 2 해제 뒤 정상 1대 | SUCCESS | 승인 오류 0 · Portal 200 |
| #159 | Tier 2 해제 뒤 취소 | ABORTED | 승인 오류 0 · 보존 완료 · 닫힌 포트라 전송 실패(의도) |

- checkout: 수집한 빌드(#144~#156 · #158 · #159) 모두 `f43af470`. 단계 화면(wfapi · Blue Ocean) `입력 확인 → 실행 위치 확인 → 서버 정보 수집 → 결과 확인 및 전송`, 빌드 이름 `os 3대` 형식 — main 과 같다.
- production #143(2026-10-06 07:48:05, admin, 파라미터 없음)은 이 세션이 실행하지 않았다(그 시각 이 세션의 Jenkins 호출은 읽기뿐이고 CI #24 실행은 16초 뒤). 컨트롤러가 `github.com` 이름을 해석하지 못해 Jenkinsfile 을 가져오지 못한 FAILURE 로, 파이프라인 코드가 실행되지 않아 결과 · 전송이 없다 — `docs/operate/04` 8절에 적었다. 07:49 이후 빌드는 모두 정상적으로 가져왔다.
- Cisco `.2` 는 production 단독 실행 348초, main #274 는 같은 BMC 를 E2E-E #270 과 동시에 요청해 632초 — GP-49 와 같은 현상이며, Redfish 모듈 상한이 없어져 끊기지 않았다.

### 9-3. Jenkins 설정 정리 (P5 검증 뒤)

- 전역 환경변수 `SE_FINALIZER_BOUNDED` 삭제 → 남은 전역 변수는 `ADDON_REPO_URL` 하나.
- Script Approval: Tier 2 서명 4개(`FlowInterruptedException getCauses` · `TimeoutStepExecution$ExceededTimeout getNodeId` · `FlowNode getEnclosingBlocks` · `FlowNode getId`) 해제 → 승인 9 → 5, 나머지 5개는 그대로, 대기 0. 이 Jenkins 의 script-security 에는 서명별 해제(`denyApprovedSignature`)가 없어 1차 시도가 실패했고(목록 변화 없음), 목록 지정(`setApprovedSignatures`)으로 4개만 뺐다.
- 해제 뒤 확인: #158 · #159 승인 오류 0.

## 10. 명부 집계 (최종 후보 main · production)

| 채널 | 대상 | main `8c9e04a9` | production `f43af470` |
|---|---|---|---|
| Linux A | 8 | #272 8/8 | #152 8/8 |
| Linux B | 7 | #273 4 + 실패 3 | #153 4 + 실패 3 |
| Windows | 1 | #265 1/1 | #154 1/1 |
| ESXi | 6 | #269 6/6 | #155 6/6 |
| Redfish | 10 | #274 7 + 실패 3 | #156 7 + 실패 3 |
| 합계 | **32** | 시도 32 · 성공 26 · 부분 0 · 실패 6 · 사용자 제외 0 | 시도 32 · 성공 26 · 부분 0 · 실패 6 · 사용자 제외 0 |

실패 6대(두 실행 같음): Linux `.135` · `.145` · `.165`, BMC `10.100.15.3`, HPE `10.50.11.231` — `TARGET_UNREACHABLE`. Cisco CIMC `10.100.15.1` — `PROTOCOL_CHECK_FAILED`(GP-37).

Kernel 6.x · memory 대조 — 7차 행렬과 같다. 모두 `physical_installed` · `errors[]` 0, 대조 행 main 24 · production 27 전부 일치.

| 대상 | 커널 | memory | main | production |
|---|---|---|---|---|
| `.37` · `.38` | 6.12.0-211.7.3.el10_2(RHEL 10.2) | 4,096 MB · 슬롯 1 | #263 · #271 · #272 | #150 · #151 · #152 |
| `.95` | 6.8.0-101-generic | 262,144 MB · 슬롯 4 | #271 · #272 | #151 · #152 |
| `.96` | 6.8.0-88-generic | 131,072 MB · 슬롯 8 | #271 · #272 | #151 · #152 |
| `.156` | 6.8.0-100-generic | 4,096 MB · 슬롯 1 | #271 · #272 | #151 · #152 |
| `.161` · `.162` · `.163` | 4.18 · 5.14 · 5.14(RHEL 8.10 · 9.2 · 9.6) | 8,192 MB · 슬롯 1 | #264 · #266 · #271 · #272 | #144 · #145 · #146 · #151 · #152 |

Redfish 인증(10대 중 닿는 7대): 표준 계정 첫 시도 성공(`used_role primary` · `fallback_used false`) 7/7, `account_service` 비어 있음 = 계정 쓰기 0 — main #274 · production #156 같음(main E2E-E #270 2/2). 성공한 결과 중 `errors[]` 가 남은 대상은 main · production 모두 0.

운영 결함과 환경 항목: 이번 실행의 실패는 전부 환경 항목이다 — Linux `.135 · .145 · .165` 와 BMC `10.100.15.3` · HPE `10.50.11.231` 은 TCP · ICMP 무응답(`TARGET_UNREACHABLE`), Cisco `10.100.15.1` 은 ServiceRoot 비정상(`PROTOCOL_CHECK_FAILED`). 코드 결함 0.

## 11. 남은 한계 · 사용자 결정

- 원격 정리: D 상태 프로세스 · 네트워크 단절로 대상이 모르는 연결은 남을 수 있다(§6).
- 6시간 보장: Runner 대기 · 준비가 길면 그 빌드의 수집 한계는 6시간보다 짧다(`build_limit`, 콘솔 `[시간]` 이 미리 알린다).
- 소유 기록이 없는 폴더는 자동으로 지우지 않는다 — 콘솔 `[작업 폴더 정리] 소유 빌드를 확인할 수 없어 건드리지 않은 폴더` 줄로 알리고, 확인 뒤 수동으로 지운다(이번 Runner01 `clovirone-server-gather-28` 은 §12 에서 삭제).
- 파이프라인이 시작되기 전의 실패(예: 컨트롤러가 저장소 이름을 해석하지 못함 — production #143)는 결과 · 전송이 없다. 다시 보낼지는 호출 측 몫이다(`docs/operate/04` 8절).
- 같은 BMC 를 여러 빌드가 동시에 요청하면 느려진다(Cisco `.2` 단독 348초 → 동시 632초, GP-49). 이제 끊기지는 않는다.
- 그대로 남은 사용자 결정: 노출 자격 회전 · 이력 정리 · 공개 범위(GP-52) · 미해결 자산 6건(GP-37) · Runner01/02/04 `cj` 라벨(GP-38) · `meta.duration_ms` 의미(GP-44) · throttle(GP-50).

## 12. 임시 자원 정리

| 자원 | 처리 |
|---|---|
| Jenkins 접속 netrc(admin) · Runner SSH 비밀번호 파일(scratchpad) | 작업 끝에 삭제, 다른 scratchpad 파일에 같은 값이 없음을 확인(값은 출력하지 않음) |
| vault 암호 사본(승격용) | 승격 직후 삭제 확인 |
| WSL 승격 작업 폴더 `/tmp/prodgen-*-54cf80287e27` 4개(약 12 MB) | 삭제 |
| Runner02 `/tmp/se_raw_tools_nsevuqkg`(2026-10-04 CI pytest 가 중간에 끊겨 남긴 시험 도구 래퍼) | sudo 로 삭제 |
| Runner01 `clovirone-server-gather-28` · `@tmp`(2026-09-30, 커밋 없는 `.git` 84 KB · 빈 폴더, 소유 빌드 #28 기록은 보존 정책으로 이미 삭제) | production 첫 정리가 "소유 기록 없음" 으로 남긴 것을 확인한 뒤 sudo 로 삭제 |
| Harness `sink_hold` 빌드 | T2 · T5 전송 뒤 중지 |
| Jenkins 전역 `SE_FINALIZER_BOUNDED` · Tier 2 승인 4개 | 삭제 · 해제(§9-3) |
| Runner cloviradmin 홈 · `/tmp/se_cp.*` · 시험 프로세스 | 0 (4대 확인) |
| 남겨 둔 것 | main #229~#242 의 빈 제어 폴더 13개(10-05 19시 — 첫 정리 때 13시간이 안 돼 남김, 다음 날 main 정리가 지운다) · WSL `/tmp/tmp.*` 11,452개(09-21~09-30, 이번 회차에 만든 것이 아님) |
