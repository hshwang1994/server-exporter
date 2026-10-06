# 2026-10-06 — 9차: 실행 기반 대기 · 같은 Runner 재개 · 사전 차단 제거

> 지시서: "ClovirONE Gathering 대기 및 일시 장애 처리 재검토 지시서" 최종본(2026-10-06). 결정 근거: `docs/ai/decisions/ADR-2026-10-06-infra-wait-and-host-resume.md`.
> 운영 설명: `docs/operate/04-pipeline-runtime.md` "실행 기반 대기와 같은 Runner 재개". 호출자 계약: `docs/contract/04-failure-and-diagnosis.md`.

## 0. 요약

- **바뀐 동작**
  - Runner · Jenkins Agent · 결과 처리 노드 같은 실행 기반 장애는 빌드 하나의 합으로 최대 72시간 기다린다. 기다리는 동안 executor 를 잡지 않는다.
  - 기다린 뒤에는 같은 Runner · 같은 작업 폴더에서 끝나지 않은 대상만 이어서 수집한다. 끝난 대상과 Precheck 실패 대상은 다시 수집하지 않는다.
  - 기다린 시간은 실행 시간에 넣지 않는다. 실제 수집 시간은 누적 최대 6시간이다.
  - 실행 시간은 보수적으로 센다 — 끝 기록이 없으면 마지막 생존 표시 + 60초.
  - 지운 것: 빌드 12시간 · 수집 단계 39,000초 · `scripts/gather_budget.sh`(메모리 상한) · `no_agent` · `not_started_*`.
- **대상 측 장애**: 자격 후보는 Redfish 구조화된 401 일 때만, OS · ESXi 는 관리 포트가 다시 응답할 때만 다음 후보로 넘긴다. 응답을 잃은 계정 쓰기는
  다시 보내지 않고 재조회 · 재인증으로 판정한다. 저장장치 하위 401/403 은 섹션 실패로만 남긴다.
- **production 주석**: prodgen 이 utf-8 인코딩 선언을 지운다. 두 스크립트의 argparse 설명은 문자열 상수로 바꿨다(D13).
- **검증 결과**: main 후보 X″ `8af81613` → production P6 `a8833d47`. 실기(se-probe) L1~L6 · L8, Runner03 OOM 격리 시험, main Job 17 시나리오 × 3 후보,
  CI #27 · #29 · #30, production Job 검증.
- **이번 회차에 찾아 고친 결함 6건**(§11): 결과 처리 노드 대기 · G08 · 실기 드라이버 정리 · 운영 문구 · OOM 신호 분류 · Harness 판정과 CI 집계.
- **실기 미확인**(§12): 시험 6 · 18(대상 측 일시 네트워크 장애), Redfish 쓰기 응답 유실(mock 만), 재개 때 Add-on 결정 재사용(단위 시험만), 72시간 자체.

## 1. 커밋 (main)

| SHA | 제목 |
|---|---|
| `6399c411` | feat: 수집 실행 기록과 재개 대상 계산 |
| `53aa1905` | feat: 실행 기반 대기와 같은 Runner 재개 |
| `db110d93` | fix: 자격 후보 전환 · 쓰기 응답 유실 · 하위 403 보존 |
| `74ad93bf` | harness: 9차 ADR · rule 80 · 카탈로그 · prodgen 필수 집합 |
| `da3389dc` | harness: prodgen 이 utf-8 인코딩 선언을 지운다 |
| `6e249700` | docs: 운영 · 계약 문서 — 실행 기반 대기와 재개 |
| `87645c73` | harness: prodgen G08 이 같은 폴더 스크립트 import 를 인정 |
| `eb6df69a` | fix: 대기 한도를 다 쓴 빌드도 결과 처리 노드를 얻는다 |
| `b3bc02dd` | harness: 결과 처리 노드 대기 결함 기록 · ADR 보완 |
| `8beb4e81` | test: 실기 드라이버의 시도 폴더 정리를 sh 없이 한다 |
| `f954c0aa` | fix: 수집 뒤 결과를 넘겨받지 못한 경우를 따로 적는다 |
| `9ba237a6` | fix: OOM 직후 신호 종료도 runner_oom 으로 기록한다 |
| `e4bbd2cb` | harness: OOM 신호 종료 분류 결함 기록 · ADR D7 보완 — 후보 X′ |
| `d1e86297` | test: 수집 단계 재전파와 전송 실패를 나누고 CI 가 판정을 본다 |
| `03a417d8` | harness: Harness 판정을 놓친 CI 집계 결함 기록 |
| `15283d87` | docs: 운영 문서가 AI 결정 문서 대신 결정 기록을 가리킨다 |
| `8af81613` | harness: CI Harness 판정 기준을 카탈로그에 반영 — **승격 후보 X″**(런타임 경로는 X′ 와 같다 — 생성 tree `e6b06e99…`) |

## 2. 지시서 항목별 판정

| 항목 | 판정 | 근거 |
|---|---|---|
| W01 Runner 조회 | 수정 | 등록 Runner(`nodesByLabel offline:true`) 0 → `config_error` FAILURE + 대상마다 실패 결과 전송(main #278 · #295, sink 200). 1 이상 → queue 대기(L1 · L2) |
| W02 시간 한계 | 수정 | 빌드 · 단계 timeout 삭제. 실행 기반 대기 합 72 h · 실제 수집 누적 6 h · 시도 실행 한계(남은 수집 + 90 s + 2 h) · 결과 확인 1 h(노드를 얻은 뒤) |
| W03 메모리 | 삭제 | `gather_budget.sh` · `SE_MEM_AVAILABLE_MB` · `not_started_memory` · CI 의 MemAvailable 실패 조건. 동시 실행 상한(OS 50 · ESXi 2×vCPU · Redfish 4×vCPU)만 남음 |
| 재개를 막던 것 | 수정 | 진입 때 결과 삭제 → 첫 시도에서만. 결과 기록 → 시도마다(`gather_run.json` schema 2). 잘린 마지막 줄 → `gather_tail_fragments.jsonl` 로 옮김 |
| W04 Precheck | 확인만 | Precheck 실패 대상은 결과로 확정 · 재개 제외(Harness `infra_resume`, 단위 시험) |
| W05 Redfish 수집 중 장애 | 일부 수정 | 저장장치 Controllers 하위 401/403 은 비차단 코드 → 섹션 실패 · 대상 partial · 데이터 유지. 429/503 재시도 없음 · 페이지 보존은 그대로 |
| W06 자격 후보 | 수정 | Redfish: 구조화된 401 일 때만 다음 후보, 복구 진입은 시도한 표준 후보 전원 401. OS · ESXi: 실패 뒤 관리 포트 TCP 재확인, 무응답이면 중단 |
| §3 쓰기 응답 유실 | 수정 | 다시 쓰지 않고 슬롯 재조회 + 표준 자격 재인증으로 판정. 슬롯 비우기는 확정 401 일 때만. `HTTPException` = 응답 유실 |
| W07 결과 처리 노드 | 수정 | 같은 대기 합 안에서 기다림, 노드를 얻은 뒤 1 h. 한도를 다 썼어도 바로 얻을 수 있는 노드는 얻음(결함 1 수정, L5) |
| W08 Portal | 확인 + 기록 | 최대 3번 · 시도당 10분 유지. `callback.receipt`(delivered · not_delivered · uncertain · not_attempted) 추가 |
| W09 Add-on | 수정 | 결정(`.se_addon.json`: 사용 여부 · commit)을 작업 폴더에 남겨 재개 때 다시 받지 않음(단위 시험). main 실행에서 Add-on 검사 통과(#281 등) |
| W10 · W11 · W12 | 조건부, 변경 없음 | 정상 수집을 막는 사례 미확인. `addon_checkout.sh` 주석 180 → 1,800초 정정 |

## 3. 시험 1~21

| # | 내용 | 확인 | 결과 |
|---|---|---|---|
| 1 | 오프라인 → 온라인 | 실기 L1 + Harness | 통과 — queue 대기 2분 39초(대기 합), 수집 5초 |
| 2 | executor 사용 중 → 가용 | 실기 L2(#9) | 통과 — 239초 대기, 수집 5초. 운영 Runner executor 점유 없음(se-probe 1개만) |
| 3 | 메모리 0 · 측정 불가 | 단위 시험 · CI Time Limits(os 3 · esxi 50 · redfish 200대 begin) | 통과 — 메모리를 읽지 않음, 한계 21,600 · 대상 전부 |
| 4 | 끊김 · Runner 장애 · OOM 뒤 재개 | 실기 L3 · L4 + Runner03 OOM 격리 + Harness `infra_resume` | 통과 |
| 5 | Precheck 실패 확정, 나머지 계속 | main S2 · Linux B · 단위 시험 | 통과 — S2 4 + 실패 2, Linux B 4 + 실패 3 |
| 6 | 대상 일시 장애가 기존 timeout 안에서 회복 | — | **실기 미확인**(§12) |
| 7 | 결과 처리 노드 확보 뒤 전송 | Harness `infra_resume`(15초 대기) · 실기 L5 | 통과 |
| 8 | Portal 실패 | main T6 | 통과 — 408 × 3, 본문 보존, 재수집 · 대기 없음, `receipt` |
| 9 | Add-on | 단위 시험(결정 재사용) + main Add-on 정상 | 정상 경로 실기 통과 · 재개 때 재사용은 **실기 미확인** |
| 10 | 다수 중 일부 완료 | 실기 L4(50대 중 2대 끝 → 48대만) · Harness(10대 중 5대) | 통과(지시서의 30/20 분할 그대로는 아님) |
| 11 | 72 h 경계 · 시작 시각 유지 · 대기 중 취소 | Harness `infra_wait_expired`(45초) · 실기 L5(480초) · L6 | 통과(72 h 자체는 축소 상수) |
| 12 | 대기 중 정리 · 보관 | `workspace_cleanup` 단위 시험(82 h 안 보호) | 통과(단위) |
| 13 | 인증 실패 · 잘못된 입력 · 잠금 방지 | main 중복 IP · 단위 시험 · 실제 ansible(OS 닫힌 포트 1회 시도) | 통과 |
| 14 | 쓰기 응답 유실 | mock 서버(`test_account_lost_write_response.py`) | 통과(mock) — 실장비 쓰기는 하지 않음 |
| 15 | 수행 시간 누적 | 단위 시험 · 실기 L3(540초 + 0, 다음 한계 1,260초) · L4(보수 60초) | 통과 |
| 16 | Precheck 실패 재개 제외 | Harness `infra_resume` · 단위 시험 | 통과 |
| 17 | 잘못된 Location · 등록 Runner 없음 | main `loc=ic` #278 · #295 | 통과 — FAILURE(`config_error`), 2대 실패 결과 전송 200 |
| 18 | 회복 실패 대상 확정 | — | **실기 미확인**(§12) |
| 19 | 실행 중 대상 미확정 보존 | Harness `infra_resume`(CHECKPOINT 만 있던 대상 재수집) | 통과(가짜 실행 기반) |
| 20 | OOM 근거 | Runner03 격리 시험(§5) | 통과 — 고친 뒤 `runner_oom`, 대조 `kill -9` → `process_lost` |
| 21 | 재개 불가 보고 | 실기 L8 · Harness `resume_impossible` | 통과 — 전체 재수집 없음 |

## 4. se-probe 실기 (L1~L6 · L8)

구성(모두 임시, §13 에서 삭제)

- 노드 `se-probe`: Runner03 호스트, remoteFS `/app/jenkins-agent/se-probe`, executor 1, EXCLUSIVE. 실행 명령 앞 조건 `test ! -e /app/jenkins-agent/se-probe.hold`.
- Job `clovirone-cicd/se-infra-probe`: Pipeline from SCM `*/main`, `tests/jenkins/harness/Jenkinsfile_live_infra`.
  - 운영 함수 `seGatherStage` · `seFinalizeAndCallback` 을 짧은 상수와 실제 `node()` 로 실행한다.
  - 실제 `run_gather.sh` · `gather_state.py` 가 돌고, ansible 만 가짜다.
  - 전송 주소는 닫힌 포트(`127.0.0.1:9`)라 전송만 실패한다.
- 점유용 Job `clovirone-cicd/se-infra-busy`: L2 전용, se-probe executor 를 240초 잡는다.
- 장애 주입: Jenkins REST(임시 오프라인 · 다시 붙이기 · 취소), Runner03 SSH(hold 파일 · se-probe 에이전트 프로세스 종료 · 시도 프로세스 종료 · 작업 폴더 삭제).
  운영 Runner01~04 의 노드 · 라벨 · executor · 설정은 바꾸지 않았다.

| 사례 | 빌드(SHA) | 한 일 | 관측 |
|---|---|---|---|
| L1 오프라인 → 온라인 | #7 (`b3bc02dd`) | 준비 중 임시 오프라인 + hold · 에이전트 종료 → 약 2분 뒤 복구 | `Runner 배정 대기` 159초 acquired. 수집 5초, 6/6. 결과 처리 노드 0초 |
| L2 사용 중 → 가용 | #9 (`b3bc02dd`) | 준비 중 점유 빌드를 바로 queue 에 넣음 | `Runner 배정 대기` 239초 acquired. 수집 5초, 6/6. (#8 은 점유 빌드가 기본 대기 5초 때문에 늦게 들어가 대기 0 — 무효) |
| L3 끊김 · 프로세스 생존 | #10 (`b3bc02dd`) | 수집 중 hold + 에이전트 종료, 5분 판정 뒤 1분 뒤 복구 | Jenkins 가 5분 뒤 step 종료 → retry 분류 → `같은 Runner(se-probe) 복구 대기` 368초(Jenkins 5분 포함). 2번째 시도는 끊긴 동안 돈 이전 수집이 끝나기를 잠금으로 기다린 뒤(16:18:48 → 16:20:58) 4대만 수집. 누적 실행 540초, 이번 한계 1,260초. 6/6 |
| L4 끊김 · 프로세스 종료 | #11 (`b3bc02dd`), 50대 | 수집 중 hold + 에이전트 · 시도 프로세스 종료 | 1번째 시도 `agent_disconnect`, 실행 시간 보수 60초(실제 약 25초). 2번째 시도는 48대만. 50/50 |
| L5 대기 한도 초과 | #12 (`8beb4e81`), 한도 480초 | 수집 중 끊고 복구하지 않음 | `같은 Runner 복구 대기` 480초 expired → `infra_wait_expired`. 결과 처리 노드 0초 확보(결함 1 수정 뒤). 6대 "수집을 실행하던 Runner 가 회복되지 않아 …" |
| L6 대기 중 취소 | #13 (`8beb4e81`) · #15 (`e4bbd2cb`) | 같은 Runner 를 기다리는 중 `/stop` | 대기 구간 interrupted(321초) · 다시 시도 없음 · `aborted` · 결과 처리 노드 확보 · 6대 1번 전송 시도 · ABORTED. #15 에서 고친 문구 확인 |
| L8 끊긴 사이 작업 폴더 삭제 | #14 (`8beb4e81`) · #16 (`e4bbd2cb`) | 끊고 시도 프로세스 종료 + 작업 폴더 삭제, 5분 판정 뒤 복구 | 2번째 시도가 소유 기록 없음을 보고 `resume_impossible`(재수집 없음, 가짜 ansible 수신 1회). 6대 실행 기반 문장 |

관찰

- L1~L4 는 시험 드라이버의 마지막 정리 결함으로 빌드 결과가 FAILURE 다(결함 3). 수집 · 전송 검증 결과와는 무관하고, `8beb4e81` 이후 실행은 정상 종료한다.
- 실기 빌드의 SUCCESS · UNSTABLE 은 운영과 다를 수 있다. 시험 함수 묶음이 `unstable()` 을 기록만 하도록 감쌌기 때문이다(`build_functions.py`).
  운영 Job 의 UNSTABLE 은 main T6 · E2E-A 로 확인했다.
- 오래 기다린 뒤 짧게 끝난 시도는 다음 단계가 최대 5분 늦다. `parallel` 이 대기 한도 타이머의 현재 조회 간격(최대 5분)이 끝나기를 기다리기 때문이다.
  - 실측(수집 보존 끝 → 결과 처리 노드 요청): L1 2분 17초, L2 약 1분, L3 약 15초. executor 는 잡지 않는다.
  - 조회 간격 상한(5분)은 72시간 대기의 flow 노드 수를 억제하려는 설계 값이라 그대로 둔다.

## 5. Runner OOM 격리 시험 (시험 20)

- 방법: Runner03 의 임시 폴더 `/tmp/se-oom-probe-9th` 에서 실제 `run_gather.sh` · `gather_state.py` 를 가짜 ansible 로 돌렸다.
  - OOM 사례: `systemd-run --scope -p MemoryMax=64M -p MemorySwapMax=0` 범위 안에서 가짜가 2대 결과를 쓰고 512 MiB 를 잡는다.
  - 대조 사례: 같은 가짜가 2대를 쓰고 스스로 `kill -9`.
- 시점: Runner03 노드 · se-probe 모두 실행 중 빌드 0 일 때.

| 실행 | OOM 사례 | 대조(`kill -9`) |
|---|---|---|
| 고치기 전 (`9ba237a6` 전) | 커널이 가짜를 OOM 으로 끝낸 뒤 systemd 가 범위를 멈추며 수집 셸에 TERM → `aborted`, 근거 `signal TERM` — **결함 5** | `process_lost`(근거 없음) |
| 고친 뒤 | `runner_oom`, 근거 `… scope memory.events oom_kill +1, 뒤이어 signal TERM` · 실행 기반 장애(`infra: true`) | `process_lost`(근거 없음) |

- Runner03 `/proc/vmstat oom_kill` 은 0 → 2 가 됐다. 두 번 모두 시험 범위 안의 가짜 프로세스이며, 운영 프로세스는 건드리지 않았다.
- 시사점: 이 Runner 들(RHEL 9 · systemd)은 Agent 와 수집이 같은 세션 범위에 있다. 실제 OOM 이 나면 범위가 멈추며 Agent 연결도 끊길 수 있다.
  그때 파이프라인은 연결 끊김으로 기다렸다가 재개하고, 끝 기록에는 OOM 근거가 남는다.

## 6. 로컬 검증

| 구분 | 결과 |
|---|---|
| WSL `ci_gate` (`e4bbd2cb`) | PASS — unit · e2e · regression **4,490 통과** · 145 건너뜀(Windows 전용) · 7 xfail · integration(not live) **324 통과** · 동치 corpus 20/20 MATCH |
| Windows PowerShell 관련 | 185 통과 (`test_windows_*` · `test_precheck_icmp_reachability.py`) |
| 3채널 `--syntax-check` | os · esxi · redfish rc 0 (WSL ansible-core 2.20.7) |
| prodgen 로컬 build/verify (`e4bbd2cb`) | 195 파일 · class B 0 · tree `e6b06e99…` · 오프라인 gate 전부 PASS(라이브 gate 는 CI · 승격 때) |
| 실제 ansible 확인(자격 후보 중단) | OS 닫힌 포트 1회 시도 후 중단 · 열린 비 SSH 포트 2회 · Redfish 비 401 실패 1회 시도 후 중단(scratch 플레이북, 커밋 안 함) |

## 7. Jenkins CI

| 빌드 | 후보 | 결과 |
|---|---|---|
| #26 | `87645c73` | 중단 — Corpus 단계에서 결과 처리 노드 대기 결함(결함 1)을 찾아 고친 뒤 다시 시작 |
| #27 | `b3bc02dd` | **SUCCESS** — Gate PASS(Runner 4,487 + 324) · 동치 20/20 · Time Limits 87 · Harness main **23/23**(#529~#551) · 생성 tree **13/13**(#552~#564, tree `1e993d7d…`) · Drift · Verify **COMPLETE_PASS**(G14 4,260) |
| #28 | `8beb4e81` | 중단 — 실기에서 운영 문구 · OOM 분류 결함(결함 4 · 5)을 찾아 고친 뒤 새 후보로 |
| #29 | `e4bbd2cb` | SUCCESS(Verify COMPLETE_PASS · tree `e6b06e99…`) — 그러나 증거 48항목 중 Harness `gather_wait_abort`(#609) 판정 FAIL. CI 집계는 Jenkins 결과(ABORTED)만 봐 놓쳤다 — 결함 6. CI #27 의 #551 도 같았다 |
| #30 | `8af81613` | **SUCCESS** — Gate PASS(Runner 4,491 + 324) · 동치 20/20 · Time Limits · Harness main **23/23**(#624~#646, 판정 PASS 확인 — 고친 `gather_wait_abort` #646 15/15) · 생성 tree **13/13**(#647~#659) · Build tree `e6b06e99…`(195 파일, 로컬 계산과 같음) · Drift · Verify **COMPLETE_PASS**(G14 4,264) · Vault 복호화 · Evidence **48/48**(main 12 · Harness 36, 전부 직접 결속 — `check_evidence` 문제 0) |

## 8. main Job 매트릭스

같은 17 시나리오를 세 후보에서 돌렸다. 모두 기대 결과다.

| 시나리오 | `8beb4e81` | `e4bbd2cb` | `8af81613` | 결과 |
|---|---|---|---|---|
| T2 TEST-NET 2 → sink | #276 | #293 | #310 | SUCCESS · 실패 2 · 전달 200 |
| T5 TEST-NET 4 → sink, 수집 시작 뒤 취소 | #277 | #294 | #311 | ABORTED · 실패 4 · 전달 200 |
| T17 `loc=ic`(등록 Runner 0) | #278 | #295 | #312 | FAILURE `config_error` · 실패 2 · 전달 200 |
| T6 TEST-NET 2 → 닫힌 포트 | #279 | #296 | #313 | UNSTABLE · 408 × 3 · 본문 보존 |
| S5 Kernel 6.x `.37 .38` | #280 | #297 | #314 | 2/2 |
| S1 `.161~.163 .120` | #281 | #298 | #315 | 4/4 |
| S4 Windows `.120` | #282 | #299 | #316 | 1/1 |
| S2 S1 + TEST-NET 2 | #283 | #300 | #317 | 4 + 실패 2 |
| E2E-A `loc=cj` | #284 | #301 | #318 | UNSTABLE(전송 실패 의도) |
| E2E-A2 `loc=chj`(미등록 Location) | #285 | #302 | #319 | FAILURE · 실패 2 |
| E2E-D ESXi 6 | #286 | #303 | #320 | 6/6 |
| E2E-E Redfish 2 | #287 | #304 | #321 | 2/2 |
| S3 실호스트 13 | #288 | #305 | #322 | 13/13 |
| Linux A 8 | #289 | #306 | #323 | 8/8 |
| Linux B 7 | #290 | #307 | #324 | 4 + 실패 3 |
| Redfish 10 | #291 | #308 | #325 | 7 + 실패 3 |
| 중복 IP | #292 | #309 | #326 | FAILURE(입력 확인에서 거부) |

- 명부 32대(`e4bbd2cb` · `8af81613`): 성공 26 · 부분 0 · 실패 6.
  - 실패는 8차와 같은 환경 항목이다: Linux `.135 .145 .165` · BMC `10.100.15.3` · HPE `10.50.11.231` 은 `TARGET_UNREACHABLE`, Cisco `10.100.15.1` 은 `PROTOCOL_CHECK_FAILED`.
  - 성공 결과의 `errors[]` 0.
- 인증: 모든 채널이 표준(primary) 계정이다. Redfish 닿는 7대는 `used_role primary` · `fallback_used false` · 계정 쓰기 0.
  9차 자격 후보 변경의 정상 경로 회귀가 없다.
- 증거 수집(CI #30 `E2E_MAIN_ENTRIES`): T2 · T5 · T6 · S1 · S2 · S3 · S4 · S5 · E2E-A · E2E-A2 · E2E-D · E2E-E(#310~#322)
  - E2E-A2 의 리비전 결속은 SCM tip 관측으로 한다: 전 `8af81613` · 후 `8af81613`.

## 9. production 주석 제거 (D13)

승격 전(로컬 생성 `e4bbd2cb` — X″ `8af81613` 과 같은 tree `e6b06e99…`, G07 PASS):

| 남은 줄 범주 | 수 | 위치 · 이유 |
|---|---|---|
| Python shebang | 11 | `scripts/*.py` 3 · 모듈 · 필터 · inventory — 실행에 필요 |
| 셸 shebang | 10 | `scripts/*.sh` 4 · `Jenkinsfile_portal` 의 `sh` 본문 6 — 실행에 필요 |
| Ansible plugin `DOCUMENTATION` | 3 | `callback_plugins/json_only.py` · `lookup_plugins/adapter_loader.py` · `credential_resolver.py` — plugin loader 가 옵션을 읽는다 |
| YAML 문자열 안 셸 본문의 `#` 줄 | 37 | `os-gather/tasks/linux/gather_network.yml` 13 · `gather_system.yml` 24 — `set_fact` 문자열(내장 스크립트 데이터)이라 보존 범주 |
| Python 인코딩 선언 | **0** | 이번에 지움(P5 에는 17 파일에 있었다) |

승격 뒤(2026-10-06 19:3x): GitHub · GitLab 에서 production 을 줄끝 변환 없이(`core.autocrlf=false`) 새로 받은 두 사본

| 항목 | GitHub | GitLab |
|---|---|---|
| HEAD | `a8833d47` | `a8833d47` |
| 파일 | 196(runtime 195 + provenance) | 196 |
| 남은 `#` 모양 줄(shebang 제외) | 37 — `gather_network.yml` 13 · `gather_system.yml` 24 | 같음 |
| 인코딩 선언 · 삼중 따옴표 | 0 · 3(`DOCUMENTATION`) | 같음 |
| G07(잔여 주석) | PASS — 195 파일 · 보존 21 | PASS |

- 두 사본은 바이트 단위로 같고, 로컬 생성 tree(`e6b06e99…`)와도 같다(provenance 파일 제외).
- 참고: 이 PC 의 전역 `core.autocrlf=true` 로 받으면 작업 파일이 CRLF 로 바뀐다. 그러면 shebang 의 보존 해시가 달라 G07 이 FAIL 이다.
  production 내용의 문제가 아니라 검사 환경의 문제라, 줄끝 변환 없이 다시 받았다.

## 10. 승격 · production 검증

### 10-1. 승격

`python -m scripts.ai.prodgen promote --sha 8af81613 --verify-report <CI #30 집계> --e2e-evidence --ci-stage-results --push-remote origin,internal`
(8차와 같은 감싼 스크립트). 2026-10-06 19:20:37~19:33:49(13분 12초) → **COMPLETE_PASS → P6 `a8833d47`**.

| 항목 | 값 |
|---|---|
| 게이트 | G01~G20 전부 PASS. 이 PC 에서 다시 실행: G11~G15 · G18~G20(G19 는 vault 암호 사본을 실행 동안만 둠 — `vault_removed=yes`). CI #30 결과 재사용: G01~G10 · G16 · G17 |
| 커밋 | `a8833d47` · parent P5 `f43af470` · tree `95eb32e0` · 196 파일 |
| trailer | `Main-SHA 8af81613` · `Tree-Hash e6b06e99…`(CI #30 Build · 로컬 계산과 같음) · `Previous-Production f43af470` · `CI-Build …/clovirone-server-gather-ci/30/` · `Verdict COMPLETE_PASS` · `CI-Stages verified` · `E2E-Evidence-SHA256` |
| provenance | `main_sha 8af81613` · `tree_hash e6b06e99…` · 파일 195 |
| 게시 | origin "accepted by remote" · internal "already at the new commit"(origin 의 push URL 에 GitLab 이 들어 있다). `git ls-remote` 로 GitHub · GitLab 모두 production `a8833d47` · main `8af81613` 확인 |

### 10-2. production Job 검증

| 빌드 | 시나리오 | 결과 | 확인 |
|---|---|---|---|
| #160 | canary os 3대 → Portal | SUCCESS | 3/3 · Portal 200 · 파라미터 7개 · 보존 14일/100 · 7일/50 그대로 |
| #161 | S1 os 4대(`.161~.163` · Windows `.120`) | SUCCESS | 4/4 |
| #162 | S2 = S1 + TEST-NET 2 | SUCCESS | 4 + 실패 2(`TARGET_UNREACHABLE`) |
| #163 | T2 TEST-NET 2 → sink | SUCCESS | 실패 2 · 전달 200 |
| #164 | T5 TEST-NET 4 → sink, 수집 시작 뒤 취소 | ABORTED | 실패 결과 4 · 1번 전송 200 |
| #165 | T17 `loc=ic`(등록 Runner 0) | FAILURE | `config_error` · 실패 결과 2 · 전송 200 · checkout 없음(수집 단계 전) |
| #166 | T6 TEST-NET 2 → 닫힌 포트 | UNSTABLE | 408 × 3 · 본문 보존 |
| #167 | S5 Kernel 6.x(`.37` · `.38`) | SUCCESS | 2/2 |
| #168 | S3 실호스트 13대 | SUCCESS | 13/13 |
| #169 | Linux A 8대 | SUCCESS | 8/8 |
| #170 | Linux B 7대 | SUCCESS | 4 + 실패 3(`.135 .145 .165` 무응답) |
| #171 | Windows `.120` | SUCCESS | 1/1 |
| #172 | ESXi 6대 | SUCCESS | 6/6 |
| #173 | Redfish 10대 | SUCCESS | 7 + 실패 3(Cisco `.1` 프로토콜 · BMC `.3` · HPE `.231` 무응답) · 계정 쓰기 0 |
| #174 | 중복 IP | FAILURE | 입력 확인에서 거부 — checkout 없음 |

- checkout: 수집한 빌드(#160~#164 · #166~#173) 모두 `a8833d47`. 명부 32대(Linux A 8 · Linux B 7 · Windows 1 · ESXi 6 · Redfish 10): 성공 26 · 부분 0 · 실패 6 — main 과 같다.

## 11. 이번 회차에 찾아 고친 결함

1. **결과 처리 노드 대기** (`eb6df69a`)
   - 증상: Runner 를 기다리다 72시간 합을 다 쓴 빌드는 결과 처리 노드 요청을 queue 배정 전에 거뒀다. 실패 결과를 하나도 보내지 못하는 경로였다.
   - 수정: 요청을 거두는 판단을 첫 조회(5초) 뒤로 미뤘다.
   - 확인: Harness `infra_wait_expired` · 실기 L5.
2. **prodgen G08** (`87645c73`)
   - 증상: 새 `gather_state.py` 가 같은 폴더의 Layer A 를 import 하는데, 의존 폐포 검사가 이를 막았다.
   - 수정: 직접 실행되는 스크립트의, 생성 tree 안 같은 폴더 모듈은 인정한다.
3. **실기 드라이버 정리** (`8beb4e81`)
   - 증상: 지운 폴더 안에서 `sh` 를 띄워 exit -2 가 났다.
   - 수정: 운영 보존과 같은 `dir(@tmp) { deleteDir() }` 로 바꿨다.
4. **운영 문구** (`f954c0aa`)
   - 증상: 수집은 돌았지만 Runner 쪽 결과를 넘겨받지 못한 빌드를 "수집 단계가 실행되지 않아" 로 적었다. 넘겨 둔 결과가 없어도 "넘겨 둔 결과로 전송" 이라고 적었다.
   - 확인: L6 · L8 재실행에서 고친 문구.
5. **OOM 신호 분류** (`9ba237a6`)
   - 증상: OOM 직후 systemd 가 보낸 TERM 을 `aborted` 로 분류해 OOM 근거를 잃었다.
   - 확인: 격리 시험에서 고친 뒤 `runner_oom`.
6. **Harness 판정과 CI 집계** (`d1e86297`, 시험 도구 — production 무관)
   - 증상: `gather_wait_abort` 는 수집 단계에서 취소를 다시 던진 뒤 정상 전송하는데, 판정기가 재전파를 전송 실패로 강제해 FAIL 이었다(#551 · #609).
     CI 는 Jenkins 결과(ABORTED)만 봐 통과로 셌고, 증거 수집기(`pass: false`)에서 드러났다.
   - 수정: Harness 가 재전파 단계와 판정(빌드 변수)을 남기고, 판정기는 finalize 재전파만 전송 실패로 본다. CI 는 판정 PASS 까지 확인한다.
   - 확인: #609 산출물을 고친 판정기로 다시 판정하면 15/15 PASS. CI #30.

## 12. 실기 미확인 · 한계

- **시험 6 · 18**(대상 측 일시 네트워크 장애): 실기 미확인.
  - 장애를 넣을 수 있는 곳이 운영 Runner 방화벽, 대상 `.161` 방화벽, 이 PC 의 WSL 뿐이다.
    - 운영 Runner 방화벽: 운영 Runner 설정 변경 금지(사용자 지시).
    - 대상 `.161` 방화벽: root 접근이 없다.
    - 이 PC 의 WSL: 방화벽 도구가 없고, 일반 사용자 sudo 에 암호가 필요하다.
  - `ansible.cfg` 의 SSH 설정에 ServerAlive 가 없다. 그래서 계획의 "20초/90초" 전제와 실제 동작이 다르다.
  - 9차는 대상 측 장애 처리를 바꾸지 않았다. 대상 측 실패가 실행 기반 대기로 가지 않는다는 것은 분류 코드 · 단위 시험 · Harness 로 확인했다.
- **Redfish 쓰기 응답 유실**: mock 서버 시험만 했다. 실장비 계정 쓰기는 하지 않았다(지시).
- **재개 때 Add-on 결정 재사용**: 단위 시험만 했다. 실기 드라이버는 Add-on 을 끈다.
- **72시간 자체**: 축소 상수(45초 · 480초 · 3,600초)로만 확인했다.
- **Portal 수신 시각**: 72시간 대기 빌드의 결과는 최대 약 79시간 뒤 도착할 수 있다(대기 72 + 수집 6 + 결과 확인 1). Portal 쪽 대기 한도 확인은 사용자 몫이다.
- **강제 종료 뒤의 vault 임시 파일**: 수집 셸이 `kill -9`(또는 끝 처리 없는 종료)로 끝나고 같은 작업 폴더에서 이어서 하는 시도가 없으면
  `/tmp/se_vault.*` 가 남는다(0600, Agent 사용자). 이어서 하는 시도는 지운다. 대기 한도 초과 · 재개 불가 · 대기 중 취소로 끝난 빌드에서 수집 셸이 강제 종료됐을 때만이다.
  이번 실기에서 실제로 남았다(§13) — GP-63.
- **시도 시작 순간의 끊김**: 시도가 노드를 얻은 직후 소유 기록을 읽는 순간 Agent 가 끊기면 `resume_impossible` 로 잘못 끝날 수 있다. 창이 매우 좁아 기록만 한다.

## 13. 임시 자원 정리

2026-10-06 19:50 전후, 모두 삭제 뒤 확인했다.

| 자원 | 처리 | 확인 |
|---|---|---|
| 노드 `se-probe` | `doDelete` | API 404 · 노드 목록 Built-In + Runner01~04 |
| Job `clovirone-cicd/se-infra-probe` · `se-infra-busy` | `doDelete` | API 404 |
| Runner03 `/app/jenkins-agent/se-probe` · `se-probe.hold` · `/tmp/se-oom-probe-9th` | 삭제 | `/app/jenkins-agent` 는 `agent` · `conf` 만, 시험 프로세스 0 |
| Runner03 `/tmp/se_vault.*` · `se_cp.*` 5쌍 | 삭제(내용 읽지 않음) | 실기 L5 · L6 · L8(재실행 포함)에서 수집 셸을 `kill -9` 해 끝 처리가 돌지 않고, 이어서 하는 시도도 없어 남았다 — 시각이 각 시도 시작과 일치. 0 개 |
| Runner01 8쌍 · Runner02 4쌍 `/tmp/se_vault.*` · `se_cp.*` | 삭제 | CI #27 · #29 · #30 의 Harness 수집 단계 시나리오(수집 셸 강제 종료)가 시험용 값(`harness-stub`)으로 남긴 것 — 시각 일치. 0 개 |
| WSL `/tmp` 생성 tree · 로그, scratchpad 의 생성 tree · production 사본 | 삭제 | — |
| scratchpad 접근 파일(Jenkins netrc · Runner SSH 암호) | 작업 마지막(이 문서 커밋 · push 뒤)에 삭제 | 최종 보고에서 확인 |

운영 Runner01~04 의 노드 · 라벨 · executor 는 시작 때와 같다(Runner01 · 02 · 04 `cj esxi git linux redfish windows`, Runner03 `esxi git linux redfish windows`,
각 15 executor, Built-In 12). Runner03 의 `/proc/vmstat oom_kill` 2 는 격리 시험의 기록이라 되돌릴 수 없다(§5).

## 14. 남은 사용자 결정

- GP-52 노출 자격 · 이력 · 공개 범위, GP-37 명부 미해결 6건, GP-38 `cj` 라벨, GP-44 `meta.duration_ms`, GP-50 throttle — 그대로.
- Portal 이 최대 약 79시간 늦은 결과를 받는지(§12, GP-60).
- 시험 6 · 18 의 장애 주입 경로와 기대 timeout(GP-56), 강제 종료 뒤 남는 vault 임시 파일 정리 방식(GP-63).
