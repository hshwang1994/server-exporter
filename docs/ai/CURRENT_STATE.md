# server-exporter 현재 상태

## 일자: 2026-10-10 (진행 중) — 검수 후속 C1~C10 결함 수정 · 원격 main `a64654aa` · production P10 `9ddc174a` 그대로

> 인계: `docs/ai/tickets/2026-10-10-c1-c10-followup/CONTINUATION.md`. 결정: `docs/ai/decisions/ADR-2026-10-10-finalize-recovery-medium.md`.

- **고친 것**: C1 결과 확인이 중간 전달본(stash)을 마지막 보존의 보관본보다 먼저 씀 → 표식(`SE_FINAL_STASHED`) · 격리 폴더 · 같은 검문으로 매체 평가 /
  C2 개행만 빠진 완전한 결과 줄 보존 / C3 Redfish 계정 다음 페이지 · 불완전 열거 쓰기 0 / C4 Redfish Volumes · Port 하위 실패 기록 / C5 인증 뒤 vendor 로 adapter 재선택 /
  C6 Windows FC PortSpeed 공식 값맵(미상 코드 `null`) / C7 lscpu 버전별 캐시 합계 / C8 Windows 비종료 오류 · DIMM 일부 조회(설치량 미확정) / C9 ESXi 결과 키 부재 = 실패 기록 /
  C10 Linux 별도 sudo 비밀번호 우선. 커밋 `16afc210` ~ `5bada078` · `e07da9ad` · `fa4d025c`.
- **확인한 것**: WSL `ci_gate` PASS(`a64654aa` · `f905f145`) · Windows PowerShell 506 · Groovy CONVERSION · C1 로컬 구동 12/12 · 실제 Jenkins Harness 사전 확인 10/10(#1168~#1177) ·
  감사 재현 전후(저장소 밖 `evidence-c1-c10-2026-10-10`).
- **멈춘 곳**: 새 후보(`e27c642d` G14 시험 수정 포함) push 가 자동 권한 판정으로 거부 — main Job · CI · 승격 · production 확인은 아직 하지 않았다.
## 일자: 2026-10-09 (후속) — `json_only` 오경보 수정 · Byid 동기화 결정 · **main `04a0d6c9` → production P10 `9ddc174a`**

> 정본: `tests/evidence/2026-10-09-log-wording.md` 11절 · `docs/ai/decisions/ADR-2026-10-09-portal-byid-copy.md`.

- **`[json_only] NOTICE` 오경보**(사용자 승인 — 보호 경로): play 시작 때 inventory 가 그 play 대상으로 좁혀져 OS 정상 배치에서 play 마다 경고가 났다.
  실행마다 한 번, 좁히기 전 전체 inventory(`ignore_limits` · `ignore_restrictions`)로 대조하도록 고쳤다. 진행 기록은 그대로. main Job 26빌드 콘솔 NOTICE 0줄.
- **Byid**: 사용자 결정 "맞춰라" — 사본 유지 · portal 과 동기화(`test_jenkinsfile_portal_byid_sync.py`, source_text). rule 80 · rule 00 정정, DRIFT-019 resolved.
- **실측**: CI #38 FAIL(새 시험의 source_text 표식 누락 — G14) → 수정 · 로컬 G14 PASS → main Job #394~#406 계약대로 · 차이 0 → CI #39 SUCCESS →
  세션 CLI 승격 **P10 `9ddc174a`** COMPLETE_PASS · 양 원격 · canary #197 SUCCESS 3/3.

## 일자: 2026-10-09 — 운영 로그 문구 정리(수집 Job · 수집 스크립트 · CI) · **main `2c6d71f3` → production P9 `c69a0d33`**

> 정본: 결정 `docs/reference/decision-log.md` 2026-10-09 · `ADR-2026-10-05` 보완 문단 · 실측 `tests/evidence/2026-10-09-log-wording.md`.

- **바꾼 것**: 운영자가 읽는 문장만 — 한 사건은 첫 줄 + 두 칸 들여쓴 상세 줄, 업무 시각은 첫 줄에만, 설계 설명 · 코드값 나열 삭제. Portal 전송 상태는 기록
  (delivered · refused · 시도 기록)으로 고른다(`HTTP 200 응답을 받았습니다` / `Portal이 요청을 거부했습니다` / `전송을 확인하지 못했습니다. 총 3번 시도했습니다` /
  `Portal 전송을 시작하지 않았습니다`). `[결과] 성공 N대, …` 는 제자리 유지, `[요약]` 은 한 블록. CI 는 `COMPLETE_PASS: production 파일 검사를 통과했습니다` + 다음 검사(Harness)일 때만 둘째 줄.
  Portal 화면 문구 2건(`Runner가` 띄어쓰기 · Redfish 표준 계정 Vault 없음 문장) · os 수집 include 블록 이름 15개 · `Jenkinsfile_portal_Byid` 동기화(차이 1줄 유지).
- **바꾸지 않은 것**: stage · 판정 · 호출 순서 · `unstable`/`error` 조건 · JSON · `OUTPUT`/`CHECKPOINT`/`ADDON_*` · `[Trusted]` · `[기술 기록] 수집 시도` · `json_only.py`.
  문구를 읽는 곳(Harness needle · sh label · `evidence.py` 표식 — 새 문구를 더하고 옛 표식 유지)은 같은 커밋에서 맞췄다.
- **실측**: main Job #368~#380(13 시나리오) 콘솔 전수 · 지난 빌드 13쌍과 대상별 결과 차이 0 · Harness `sink_close` #1033 PASS · CI #37 SUCCESS(47분 58초 —
  Harness 45 · 21, Evidence 78, Verify COMPLETE_PASS) · 세션 CLI 승격 **P9 `c69a0d33`**(G11~G15 · G18~G20 이 PC 재실행) · 양 원격 · canary #194 SUCCESS 3/3 · HTTP 200.
- **참고**: CI Promote 는 2026-10-04 CI 도입 때부터 dry-run 이다 — Jenkins 에 GitLab push 자격증명(`se-gitlab-push`)이 없다(바뀐 것 없음).
  승격은 P1~P9 모두 이 PC 세션 CLI(이 PC 의 git 자격)로 했다.
- **이번에 확인한 것**: OS 정상 배치에도 `[json_only] NOTICE` 가 play 마다 나왔다 — 같은 날 후속(위 항목)에서 사용자 승인으로 고쳤다.

## 일자: 2026-10-08 — CI 실행시간 개선(Harness 2-lane · 생성물 검증 선행 · 빌드별 격리 · 후보 고정) · **main `21b24c0a` → production P8 `347ab74e`**

> 정본: 결정 `docs/ai/decisions/ADR-2026-10-08-ci-harness-parallel.md` · 실측 `tests/evidence/2026-10-08-ci-speed-p8.md`. 수집 runtime 은 바꾸지 않았다(생성 tree `8dac1eb2…` = `004a500e`).

- **순서**: Gate → Corpus → Time Limits → **Prodgen Build · Drift · Verify** → Harness(main · tree) → Evidence. 선행 필수 검사(GATE · CORPUS · BUDGET · PRODGEN_BUILD ·
  PRODGEN_VERIFY) FAIL 이면 Harness · Evidence 는 `SKIPPED`(PASS 아님). Verify 의 COMPLETE_PASS 는 gate 통과일 뿐 — 증거는 Evidence · promote.
- **Harness**: 시나리오당 빌드 1개 유지, 두 고정 lane 동시(`quietPeriod: 0`) · parallel 반환값을 요청 순서로 · 두 단계 같은 판정(`seHarnessOk` — 기대 결과 · 내부 verdict ·
  후보/생성물 결속) · 판정 자체 시험표. Harness Job 은 동시 실행 허용 — 수신기 OS 배정 포트(`--ready-file`) · 빌드별 controller 폴더 · 자기 수신기만 finally 정리 ·
  eventUuid 격리 판정 · `MAIN_SHA` commit checkout · readTrusted 고정 · Pipeline 정의 revision 확인(git 이력).
- **Time Limits**: 5개 파일을 다시 돌리지 않고 Gate JUnit 을 시험 ID 단위로 대조(`tests/scripts/junit_evidence_check.py`, WSL 실측 105/105 통과). 3채널 시작 계산은 그대로.
- **격리 시험(임시 Job, 작업 뒤 삭제)**: R1 동시 쌍 10빌드 — 순차와 같은 판정 · 포트 · eventUuid 격리 · 고정 포트 sink_hold 중단 정리 / R2 넓은 대표 CI — 호출 → 자식 시작 0.08초 · branch 가 움직여도 고정 commit /
  R3 #34 결함 재현 15.1분 FAILURE · Harness · Evidence SKIPPED / R5 부모 취소 — 자기 자식만 중단 · 수동 빌드 PASS. `HARNESS_JOB` 가드로 사본이 공유 Harness Job 을 부르지 않는다.
- **실측**: CI #36(`21b24c0a`) **46.94분 SUCCESS**(#35 80.31분, −41.6%) — Harness main 1,298.5초(2,623.6) · tree 600.5초(1,218.9) · Time Limits 2.4초(81.7) · Harness 45/45 · 21/21 ·
  Verify COMPLETE_PASS(Harness 앞) · Evidence 74 · 오프라인 `check_evidence` 문제 0. 자식 실행 합 +8~10%(동시 실행 경합 — 판정 영향 없음). main Job E2E #346~#353 8/8.
- **승격**: **P8 `347ab74e`**(parent P7 `61b9dd4a` · Main-SHA `21b24c0a` · Tree-Hash `8dac1eb2…`) — 세션 CLI COMPLETE_PASS(G11~G15 · G18~G20 이 PC 재실행) · origin · internal · 로컬 일치 ·
  새 clone tree 일치 · drift-check PROVENANCE · canary production #191 SUCCESS 3/3 · Portal 200 · checkout P8.
- **정리 · 실기 범위**: 임시 Job 4개 · 그 작업 폴더(약 1 GB) · WSL staging · feature branch · worktree · 접속 파일 삭제, 증거는 저장소 밖 보관. 실장비는 main E2E 8 시나리오 + canary 1회.
  후보 · 정보로 남긴 것: GP-65(checkout 재사용) · GP-66(Evidence 판정 범위) · GP-67(`Jenkinsfile_ci` 자기 정의 revision).

## 일자: 2026-10-07 (최종 마무리) — 로그 보관 전역화 · forks 50 · Windows vault 도메인 · Portal 재진입 4.1/4.2 · GP-64 확인 · **main push(양 원격) · production P7 `61b9dd4a` 유지**

> 정본: `tests/evidence/2026-10-07-final-wrapup.md`. 10차 결과·회귀는 그대로 유지하고 아래 변경만 더했다.

- **로그 보관 전역화(지시 1)**: `Jenkinsfile_portal` · `Jenkinsfile_ci` 의 `buildDiscarder(logRotator(...))` 제거 — 보관 정책은 Jenkins 전역 설정으로 관리한다(전역 설정은 이번에 바꾸지 않음). 운영 문서(`docs/operate/04` · `08` · `JENKINS_PIPELINES`)에서 Jenkinsfile 이 보관기간을 지정한다던 부분만 갱신.
- **forks 50(지시 2)**: `ansible.cfg` `[defaults] forks` 200 → 50(현재 운영 설정). CPU/메모리 계산·동적 forks·사전 차단 로직은 추가하지 않음.
- **Windows vault 도메인(지시 3)**: `vault/{yi,ic,cj}/os/windows.yml` 의 secondary(`windows_fallback`) username 만 `yimad\infraops` · `icmad\infraops` · `cjmad\infraops` 로. password·label·role·순서·primary(`administrator`)·`vault/git`·Linux/ESXi/Redfish 불변(복호화→수정→재암호화, 비밀값 미출력). 전달 경로 확인: vault username → `_cred_accounts` → `_os_accounts` → `try_one_credential.yml` `ansible_user`(NTLM `ansible_winrm_transport: ntlm`). YAML plain scalar 라 역슬래시는 그대로 전달.
- **Portal 결과 재진입(지시 4)**: 4.1 확정 거부(408·429 제외 4xx)는 `state.refused` 를 진입 사이에 유지해 재진입에도 다시 POST 안 함(2xx 미재전송은 유지). 4.2 응답 확인 전 중단(`outcome=interrupted`)도 수신 불명 → `receipt=uncertain`(그 뒤 재진입에서 4xx 를 받아도 uncertain). `eventUuid`·본문·누적 시도·시간 유지, 새 전송 체계·시도 초기화 없음.
- **GP-64 확인(지시 6)**: Jenkins Agent·ansible 주 프로세스가 살아 있고 작업자(fork)만 OOM 인 경우 — 작업자 PID 는 `run_gather.sh`·ansible 주 프로세스가 아니라 직접 귀속 불가. `classify_end` 는 이미 PID 연결(link) 있을 때만 `runner_oom`, 스스로 끝난 rc(1 등)는 OOM 관측이 있어도 `failed_run`. 새 추정 로직을 두지 않고 한계로 남김(회귀 `test_worker_fork_oom_is_not_this_runs_oom_gp64`).
- **검증**: 로컬 WSL `ci_gate`(오프라인 gate — 컴파일·field_dictionary·schema drift·vendor/harness 일관성·finalize corpus·pytest·3채널 syntax) · 영향 단위 시험(`test_jenkinsfile_portal_finalize` · `test_jenkinsfile_ci` · `test_time_limits` · `test_gather_state` · `test_harness_tools` · `test_finalize_corpus` · prodgen verdict). Harness 시나리오 `finalize_refused_no_resend` 추가(CI·prodgen 목록 동기).
- **[HOLD] 이 세션 Jenkins 자격 부재**: Jenkins controller 는 닿지만(HTTP 200) 인증 netrc 가 이 세션에 없다(10차 종료 시 접근 파일 삭제, 재발급 안 됨). 그래서 **CI 실행 · production 승격·canary · production 실환경 재검증 · GP-57 실장비는 이 세션에서 수행하지 못했다** — 우회하지 않고 미수행으로 남긴다. main 코드는 양 원격에 push, production 은 P7 `61b9dd4a` 유지.
- **실기 미확인**: GP-57(실장비 계정 쓰기 응답 유실) · GP-64(작업자 OOM PID 연결) · Windows 도메인 계정 실인증(승인된 도메인 가입 시험 대상 없음 · 반복 실패 시 운영 `infraops` 잠금 위험) · 72 h 자체 · 이번 세션의 Jenkins 실행 검증.

## 일자: 2026-10-07 (10차) — 결과 처리 재진입 · 기록 읽기 예외 · 끊긴 준비 · OOM 귀속 · 실환경 검증 · **main `fa05d122` → production P7 `61b9dd4a`**

> 정본: `tests/evidence/2026-10-07-10th-final-defects.md` · 결정 `docs/ai/decisions/ADR-2026-10-07-finalize-reentry-and-oom-attribution.md` · 운영 `docs/operate/04-pipeline-runtime.md`.

- **결과 처리 재진입(R1)**: 결과 확인 및 전송 중 실행 기반 오류면 같은 빌드에서 노드를 다시 기다려 같은 폴더에서 다시 처리한다. 2xx 받은 전송은 다시 보내지 않고, 결과 처리 시간 1 h · Portal 시도 3번 · 취소 빌드 노드 대기 5분은 진입 사이에 이어 센다. 끝내 못 하면 FAILURE(미전송) · UNSTABLE(전송 뒤).
- **대기 시각(보정 1)**: 끊긴 뒤 대기는 감지 시각부터(`OFFLINE_GRACE` 삭제). 실기 L3 대기 63초(9차 368초).
- **기록 읽기(R2 · R4)**: `seReadJsonFile` — 없음 · 손상(해석 실패만)과 읽기 예외를 나누고 예외는 `retry(agent(), nonresumable())` 로. Add-on 결정은 재사용 · 손상이면 사본 commit · 없으면 끔.
- **준비 · 보존(R3 · N1)**: 소유 기록 `prepared` · 접수 목록 복원 · 확정 결과 IP 대조(사라지면 rc 92 · 재개 불가) · 보관 또는 전달 뒤 표식(그 뒤 끊김은 다시 시도하지 않음).
- **OOM(R5)**: 커널 로그 OOM 종료 PID == 이 실행(run_gather.sh · ansible-playbook 주 프로세스)일 때만 `runner_oom`. 기준점은 커널 로그 자신의 시계(실기에서 /proc/uptime 과 22초 차이로 놓치던 결함을 찾아 고침). 카운터 증가는 관측만.
- **실기**: se-probe L3 · L4 · L5 · L6 · L8 재실행 · L9(Add-on 을 켠 재개 — A 재사용) · R6 대상 측 장애(Linux · Windows · Redfish, Windows 는 대상 쪽 약 20초 경계) · Runner03 실제 커널 OOM 6사례 — 모두 기대 동작.
- **검증**: WSL `ci_gate` PASS(4,476 + 324) · CI #32 Verify COMPLETE_PASS(Harness 63/64 — 시나리오 설계 고침) · **최종 CI #33(`fa05d122`) SUCCESS** — Harness main 44/44 · 생성 tree 21/21 · Verify COMPLETE_PASS · Evidence PASS · main Job #327~#344 17 시나리오 기대 결과 · 명부 32대 성공 26 · 실패 6 → **P7 `61b9dd4a`**(양 원격 일치 · G07 재검사 PASS) · production #176 canary 3/3 · #177~#190 같은 매트릭스 · 명부 같은 결과.
- **실기 미확인**: GP-57(실장비 계정 쓰기 응답 유실 — 도구 차단) · GP-64(ansible 작업자 OOM 의 PID 연결) · 72 h 자체(축소 상수).

## 일자: 2026-10-06 (9차) — 실행 기반 대기 · 같은 Runner 재개 · 사전 차단 제거 · **main `8af81613` → production P6 `a8833d47`**

> 정본: `tests/evidence/2026-10-06-9th-infra-wait-resume.md` · 결정 `docs/ai/decisions/ADR-2026-10-06-infra-wait-and-host-resume.md` · 운영 `docs/operate/04-pipeline-runtime.md`.

- **실행 기반 대기**: Runner · Jenkins Agent · 결과 처리 노드 장애는 빌드 하나의 합 72 h 까지 executor 를 잡지 않고 Jenkins queue 로 기다린다(`seWithNode` — `parallel(failFast)` 의 node 요청 + 대기 한도 타이머, 끊김 판정은 `retry(agent())` 의 두 번째 호출).
- **같은 Runner 재개**: 수집을 시작한 Runner · 작업 폴더로만 다시 시도하고 끝난 대상 · Precheck 실패 대상은 빼고 이어서 수집한다(`scripts/gather_state.py` · `run_gather.sh` 의 flock · `--limit @파일`). 이어 갈 수 없으면 `resume_impossible`, 한도를 넘으면 `infra_wait_expired` — 둘 다 새 문장 `infra_unavailable`(`OUTPUT_BUILD_FAILED`).
- **시간**: 빌드 12 h · 수집 단계 39,000 s · `gather_budget.sh`(메모리 상한) · `no_agent` · `not_started_*` 삭제. 실제 수집 누적 6 h(끝 기록이 없으면 마지막 생존 표시 + 60 s 로 보수 계산) · 시도 실행 한계 · 결과 확인 1 h(노드를 얻은 뒤).
- **대상 측**: 자격 후보는 Redfish 구조화된 401 · OS/ESXi 관리 포트 재응답일 때만 전환, 응답 잃은 계정 쓰기는 재조회 · 재인증으로 판정(다시 쓰지 않음), 저장장치 하위 401/403 은 섹션 실패만.
- **production 주석(D13)**: prodgen 이 utf-8 인코딩 선언을 지운다 · argparse 설명 상수화 — 남은 `#` 모양 줄은 shebang 21 · plugin `DOCUMENTATION` 3 · YAML 문자열 안 셸 본문 37 뿐(승격 전후 같은 검사).
- **검증**: 로컬 WSL 4,490 + 324 · Windows PowerShell 185 · CI #27(`b3bc02dd`) SUCCESS(Harness 23/23 · 생성 tree 13/13 · Verify COMPLETE_PASS) · CI #29(`e4bbd2cb`) SUCCESS 이나 증거에서 Harness 판정 FAIL 1건 발견(결함 6) · CI #30(`8af81613`) SUCCESS(Harness 23/23 · 생성 tree 13/13 · Verify COMPLETE_PASS · Evidence 48/48) · se-probe 실기 L1~L6 · L8 · Runner03 OOM 격리 시험 · main 17 시나리오 × 3 후보(#276~#292 · #293~#309 · #310~#326) · production Job #160~#174 15/15 기대 결과(canary 3/3 · 명부 32대 성공 26 · 실패 6 환경 항목 · 계정 쓰기 0).
- **도중 결함 6건 수정**: 결과 처리 노드 대기(한도 소진 뒤 0초 대기로 전송 못 함) · G08 같은 폴더 import · 실기 드라이버 정리 · 운영 문구 2건 · OOM 직후 TERM 분류 · Harness 판정(수집 단계 재전파를 전송 실패로 봄)과 CI 집계(ABORTED 시나리오는 Jenkins 결과만 봄).
- **실기 미확인**: 시험 6 · 18(대상 측 네트워크 장애 주입 경로 없음) · Redfish 쓰기 응답 유실(mock) · 재개 때 Add-on 재사용(단위) · 72 h 자체(축소 상수).
- 남은 사용자 결정: GP-52 · GP-37 · GP-38 · GP-44 · GP-50 그대로, 시험 6 · 18 주입 경로(GP-56). 사용자 결정(2026-10-06): Portal 은 결과를 늦게(최대 약 79 h) 받아도 된다(GP-60) · 강제 종료 뒤 남는 Runner `/tmp` 임시 파일은 그대로 둔다(GP-63).

## 일자: 2026-10-05~06 (8차) — 시험 입력 제거 · 실제 시각 · 장시간 대기 · 숨은 실패 · 원격 정리 · 운영 문구 · 보존 정리(R1~R8) · **main `8c9e04a9` → production P5 `f43af470`**

> 정본: `tests/evidence/2026-10-05-8th-time-limits.md` · 결정 `docs/ai/decisions/ADR-2026-10-05-time-limits-and-test-inputs.md`.

- **R1 시험 입력 제거**: 운영 수집 Job 의 `redfishAccountDryrun` · `gatherBudgetForceSec` 와 배선 삭제(Job 파라미터 7개 — main #243 · production #144 첫 실행이 등록). 증거 분담 — S3 = 실호스트 13대 정상 배치, E2E-E = 정상 Redfish(표준 계정 · 계정 쓰기 0), 한계 도달 · 보존 = Harness `gather_limit_preserve`(실제 `scripts/run_gather.sh`), 계정 쓰기 방지 = CI Gate 단위 시험. 증거 수집기는 없앤 파라미터 · `[시험:` 이 남은 빌드를 받지 않는다.
- **R3 · R4 시간 한계 셋**: 빌드 12 h · 수집 실행 최대 6 h(실제 시작 기준, `gather_limit`/`build_limit`) · 결과 확인 및 전송 1 h. 작업 단위 제한 · Redfish 모듈 마감 · 정체 감시(`gather_watch.py` 삭제) · `df` 20 s · 결과 정리 120 s · Tier 2(`SE_FINALIZER_BOUNDED` · Script Approval 4 서명) 삭제. 연결 60 s · 응답 대기(수집 API 30 min · Portal 시도당 10 min) 유지. 정본 표 `docs/operate/04` · `tests/unit/test_time_limits.py`.
- **R2 실제 시각**: Timestamper `timestamps {}`(Job 범위, 없으면 생략) · 업무 줄 `[YYYY-MM-DD HH:MM:SS +09:00]` · `finalize_summary` 의 `times` · `callback.tries[]` · `gather_run.json`(UTC ISO). envelope · `duration_ms` 불변.
- **R5 숨은 실패**: ESXi 디스크 모듈 실패 · Windows Hyper-V 서비스 조회 실패(없음 · 멈춤과 구분) · 네트워크 조회 비종료 오류 · setup 실패 · `Get-Volume` 실패를 `errors[]` 1건으로(섹션 상태 · 받은 값 유지).
- **R6 원격 정리**: `run_gather.sh` 가 이 실행의 SSH 다중화 연결만 닫는다 — Linux `.161` 7 상황 남은 원격 명령 0(고치기 전 한계 1 · sudo 3), WSL · Runner02 둘 다.
- **R7 운영 문구**: 문장 · 하는 일로, `[수집 종료]` 가 한계 · 실행 시간 · 대상 수 · 보존 · 전송을 나눈다. 2xx = "Portal 이 요청을 받았다". 후보 실행에서 찾은 문구 3건 고침(`c0117fd6` · `38e39c75`).
- **R8 보존 · 정리**: `buildDiscarder` 14일/100 · 7일/50 · 빌드별 작업 폴더 소유 기록 · 보관 확인 뒤에만 삭제(빈 보관은 실패) · `scripts/workspace_cleanup.py` 하루 한 번 7일 정리(보관 못 한 결과는 남김) · 컨트롤러 `fin-<번호>`. 첫 정리에서 main 지난 제어 폴더 210개 · production 157개(소유 기록 없는 옛 폴더 1개는 확인 뒤 수동 삭제) 삭제, `/app` 사용 3~4 %.
- **검증**: 로컬 4,380 + integration 324 · Windows PowerShell 170 · 생성 tree G14 4,220 · G15 · CI #24 FAILURE(G14 시험 표식 2건 — 고침) → **CI #25 SUCCESS(10 stage PASS · Verify COMPLETE_PASS · Evidence 42/42)** · main #260~#275 16/16 기대 결과 · production P5 #144~#159 16/16 기대 결과(명부 32대 성공 26 = main 과 같음 · Kernel 6.12/6.8 memory 가 7차 행렬과 일치 · Redfish 표준 계정 7/7 · 계정 쓰기 0).
- **설정 정리**: production 검증 뒤 Jenkins 전역 `SE_FINALIZER_BOUNDED` 삭제 · Script Approval Tier 2 서명 4개 해제(9 → 5, 나머지 5개 그대로 — 이 Jenkins 에는 서명별 해제가 없어 목록 지정으로) · 해제 뒤 production #158 · #159 승인 오류 0. production #143(07:48, admin, 파라미터 없음 — 이 세션이 실행하지 않음)은 컨트롤러 DNS 실패로 Jenkinsfile 을 못 읽은 빌드다(결과 · 전송 없음, GP-55).
- 남은 사용자 결정: 노출 자격(GP-52) · 미해결 자산 6건(GP-37) · `cj` 라벨(GP-38) · `meta.duration_ms`(GP-44) · throttle(GP-50).

## 일자: 2026-10-05 (7차) — 최종 정비 지시서 F01~F13 · §5 예외 무시 감사: 결과 보존 · 형태 계약 · 입력 규칙 · Redfish redirect · 환경 경계 · 시간 제한 분리 · 운영 화면 · Windows 숨은 실패 · **X13 `1e15bf6f` → P4 `5ac5566c`**

> 정본: `tests/evidence/2026-10-05-final-maintenance.md`. 사용자 결정(2026-10-05): ① 6차 마무리 먼저 ② **Portal 전송은 HTTP 2xx 수신까지가 계약**(응답 본문 판독 · 저장 확인 없음 — 지시서 F09 · §8-5 대체) ③ 메모리 부족으로 중단된 로컬 전체 회귀는 묶음으로 나눠 다시.

- **runtime 수정(F01~F06 · F12 · F13)**: 종료 보충이 CHECKPOINT 를 쓴다(`5d1c17c5`) · 결과 형태 최소 계약을 Python Layer A · Groovy Layer B · 전송 직전 검문에 같게(값 종류 먼저, NaN 거부, `b482a5fb`) · 입력 확인을 inventory 규칙과 일치 + 계정 정보 든 callbackUrl 거부(`13984b64` · `6a74faf1`) · Redfish redirect 는 같은 origin 의 GET/HEAD 만, 응답 캐시 8 MiB(`e06033c3`) · 환경 경계 `scripts/env_guard.sh`(`2ba192b5`) · **예상 시간과 중단 기준 분리 + 정체 감시**(`scripts/gather_watch.py`, 예상 뒤 420 s 무진행, Redfish 절대 1200 s + 무응답 120 s, `ef7575b2`) · 본문 단계 상한 60 s · CLI 승격이 CI 의 `require_bounded` 를 낮추지 못함(`c15a52c8`) · 운영 화면(단계 표시 이름 입력 확인 / 실행 위치 확인 / 서버 정보 수집 / 결과 확인 및 전송, sh label 7, `[결과]` 집계 · `[경고]` · `[결과 파일]` 링크 · 빌드 이름 · `finalize_summary` 의 `status_counts` · `warnings` · `callback`, `6a74faf1` · `444db56e`) · inventory 해석 실패 처리는 Jenkins 수집 실행에만(`6f83cb33`).
- **Windows 숨은 실패 기록(지시서 §5 감사, X13 `1e15bf6f`)**: Windows · ESXi 예외 무시 지점 81개 전수 분류 → 필수 데이터를 숨기는 원인 8개 중 4개 수정 — 사용자 목록 조회 실패(0명이면 섹션 실패 · 일부면 부분 오류) · 그룹 조회 실패(실패한 그룹 이름 기록) · system 구성요소 실패 · 물리 디스크 조회 실패를 errors[] 로. 실제 CIM 실패는 비종료 오류라 공용 조회 3개가 `-ErrorVariable` 로 받는다(실측). 명령 부재(F23)는 종전처럼 미지원(종료 코드 1). 나머지 4개 · 볼륨 실패는 NEXT_ACTIONS GP-51.
- **문서 · 시험 도구**: REQUIREMENTS 의 Python 요건 정정(3.8 이하 · 없음은 raw 경로로 수집 — RHEL 8.10 실측) · runbook 85행 평문 1건 가림 + 추적 파일 재검사(현재 자격 값 0건, 이력 1 commit 잔존 — 사용자 결정 GP-52) · 원격 태스크 timeout 관측 플레이북 · `ci_gate.sh` syntax-check 를 실제 inventory 로 · 동시 실행 권장값(`docs/operate/04` 7절) · Windows users 섹션 상태 계약(`docs/contract/04`).
- **원격 태스크 timeout 실측(F12 d·e)**: `.161`(SSH raw) · `.120`(WinRM) 모두 무출력 장기 명령은 상한 안에서 성공, 끝나지 않는 명령은 상한에서 끊김. **Linux 는 끊긴 명령이 원격에 남는다**(연결을 닫아도) — Windows 는 0. 대응 결정은 GP-48.
- **F07 동시 실행 · 메모리**: perf-observe 로 노드별 PSS · MemAvailable 실측 — K=2(Redfish 10 ×2, 분산) · K=12 혼합(노드마다 3개 겹침)에서 노드 PSS 합 최대 1.27 GB · MemAvailable 최소 4.68 GB(전체 7.5 GB) · swap 증가 0 → **throttle 미적용**(설정 변경 없음). 같은 BMC 동시 요청은 느린 BMC 를 늦춘다 — Cisco CIMC 367 → 673 → 1,245 s(4개 동시에서 Redfish 상한 1,200 s 로 partial, 결과 보존, GP-49).
- **성능(P3 ↔ X12, 채널별 5회 교대)**: 총 시간 중앙값 OS 154.0 → 155.2 s · ESXi 72.5 → 75.1 s · Redfish 400.4 → 383.1 s — 퇴행 없음. HPE iLO `.231` 이 Runner 망에서 10회 중 2회 닿음(GP-37 새 근거).
- **검증**: 로컬(X13) unit · e2e · regression 4,411 + integration 308 · 정적 gate · 3채널 syntax-check · 로컬 prodgen G14(4,131) · G15 · main X12 #187~#198 · X13 #231~#242 12 시나리오 기대 결과 일치(S4 `.120` 오류 0 · 사용자 데이터 X12 와 동일) · **CI #23 SUCCESS**(Gate 4,297 + 323 · Harness 18/18 · 상한 6/6 · 생성 tree 10/10 · Verify COMPLETE_PASS 20/20 · tree `1c16ca55…` · 증거 46건 전부 direct · Promote dry-run `require_bounded` cli+ci).
- **승격**: P4 `5ac5566c`(main X13, parent P3) — 세션 CLI COMPLETE_PASS(Gates-Rerun G11~G15 G18~G20), GitHub · GitLab · 로컬 production 동일. production 검증: production Job 12 빌드 #131~#142 — canary #131 SUCCESS 3/3 → S1 · S2 · T2 · Linux A 8 · Linux B 7 · Windows · ESXi 6 · Redfish 10 SUCCESS, T6 · S3 UNSTABLE(기대), 중복 IP FAILURE(입력 거부) — 모두 checkout `5ac5566c`(중복 IP 는 checkout 전 거부), 결과는 main X13 과 같다. 명부 전 채널 성공 26/32(미해결 6건은 명부 그대로).
- **도중 실패와 수정**: CI #21 — Gate(전역 `unparsed_is_failed`) · G14(새 시험 `source_text` 누락) · G15 · Harness 22건(CI 중 push 로 SHA 불일치) → X11 · X12. X13 작업 중 — 가짜 cmdlet 이 종료 오류만 내 실제 비종료 CIM 실패를 놓친 시험 · 종료 코드 변화로 F23 이 깨질 뻔한 회귀를 실제 powershell.exe 대조로 찾아 고침. 원인 · 재발 방지는 FAILURE_PATTERNS 6건.
- 남은 사용자 결정: 노출 자격 회전 · 이력 정리 · GitHub 공개 범위(GP-52) · 미해결 자산 6건(GP-37) · Runner01/02/04 `cj` 라벨(GP-38) · `meta.duration_ms` 의미(GP-44) · Linux 원격 잔존 프로세스 대응(GP-48) · throttle 적용 여부(GP-50).

## 일자: 2026-10-05 (6차) — Tier 2 승인 완료 · **사내 Jenkins 상한 모드 적용**(`SE_FINALIZER_BOUNDED=true`) · 적용 뒤 production 11 · main 12 · CI #20

> 정본: `tests/evidence/2026-10-04-review-c1-c6.md` §11.

- 승인 4/4(대기 0) → bounded Harness 5/5 PASS(#318~#322, main `031a15e6`) — 자기 timeout step id 판별이 sandbox 에서 동작.
- 사내 Jenkins 전역 환경변수에 `SE_FINALIZER_BOUNDED=true` 추가(기존 `ADDON_REPO_URL` 보존). 실측 여유: archive ≤ 0.55 s · stash ≤ 0.25 s · unstash ≤ 0.23 s · 조립 ≤ 5 s(상한 30 s · 60 s). 되돌림 = 그 항목 삭제(코드 변경 없음).
- 적용 뒤: production P3 11 빌드(#105~#115) · main X5 `27f7f4f1` 12 시나리오(#134~#145) 모두 기대 결과, 빌드마다 상한 표시(30 s ×3 · 60 s ×1) · 초과 0, T5 사용자 중단은 상한 모드에서도 ABORTED 유지. CI #20: #20 SUCCESS(35 min) · 필수 stage 전부 PASS(HARNESS_BOUNDED 포함) · Harness 18/18 · bounded 5/5 · 생성 tree 10/10 · Verify COMPLETE_PASS 20/20 · tree_hash `fd93e76b…`(= P3 trailer) · E2E 45건 전부 direct · Promote dry-run ok(`require_bounded=true`)
- 도구(X5): CI `REQUIRE_BOUNDED`(기본 true; 미등록 첫 빌드 null → true) · `promote --require-bounded`. runtime 변경 0 → production tree 불변, 새 승격 없음(P3 유지).
- 고객사 main-only: 기본 false 유지 — 켜지 않으면 기본 모드의 보장 축소(느린 보존·회수·조립을 단계에서 끊지 못함)가 남는다.
- 남은 사용자 조치: 자산 6건(GP-37) · Runner01/02/04 `cj` 라벨(GP-38) · Portal 저장/중복(GP-42) · Runner /tmp 샘플러(GP-43) · `duration_ms`(GP-44) · GitHub public 정책.

## 일자: 2026-10-05 (5차) — 남은 실행 검증 · GP-23 실장비 결함 수정 · **X4 `17843cf0` → P3 `915dec4e`(양 원격)** · 시험 설정 원복

> 정본: `tests/evidence/2026-10-04-review-c1-c6.md` §10(J/P/C/H 최종 판정표 §10-3). 사용자 지시 "남김없이".

- **GP-23 결함 수정(runtime)**: `driver_map[].vlan_id` 가 실제 VLAN 장치에서 null — `/proc/net/vlan/<if>` 가 root 전용(0600)이라 비루트 수집에서 읽기 실패. VLAN 장치에 한해 `ip -d link show dev` 로 보완(`795c6ff7`, become 추가 없음). 실장비 main #121: `.96` 64/656 · `.95` 64 일치.
- **§6-2 실제 Runner 종료 동작(term-probe Job, 신규)**: Runner03 · Runner01(ansible-core 2.20.3) — 태스크 timeout 은 자식 1개를 남긴다(GP-14 확인) · INT 경로 rc 124 잔존 0 · kill-after 대조 rc 137 잔존 0 · ansible 은 상속된 INT 무시를 덮어 "INT 소실" 재현 불가(GP-19) · Add-on hook 통합 테스트 14 passed ×2(GP-10 직접 증거).
- **X4 → P3**: main E2E 12/12(#122~#133) · CI #19 SUCCESS — 12 stage PASS(bounded PARTIAL) · Harness main 18/18 · 생성 tree 10/10 · Verify COMPLETE_PASS 20/20(tree `fd93e76b…`) · VAULT_DECRYPT PASS · Evidence PASS(main 12 항목 전부 `binding=direct` — 11 BuildData + E2E-A2 `tip_frozen:ls-remote`, `[Trusted]` 전부 utf-8 일치) · Promote DRY_RUN `e2e ok, problems []` · parent P2 `07ecf7ac` · 실 승격 세션 CLI 1회(02:59~03:10, **autocrlf=true 그대로** — GP-45 수정 효과) **COMPLETE_PASS → P3 `915dec4e`**: Gates-Rerun G11 G12 G13 G14 G15 G18 G19 G20(G19 WSL 3채널 실제 실행) · Gates-Reused G01~G10 G16 G17 · publish origin "accepted by remote" · internal "already at the new commit (reached via a shared push URL)" · 로컬 ref 갱신 · 193 파일 · 개발 경로 0 · P2 대비 runtime 차이 `os-gather/tasks/linux/gather_network.yml` 1 파일 · trailer Main-SHA `17843cf0` · Tree-Hash `fd93e76b…` · Previous-Production `07ecf7ac` · CI-Build #19 · Verdict COMPLETE_PASS · CI-Stages verified. vault 암호 파일은 실행 동안만 존재(래퍼가 삭제 확인) · production production Job(P3 `915dec4e`, 11 빌드 #94~#104): 전부 checkout == P3 · 기대 결과 전부 일치(CAN-1/S1/S2/T2/Linux 15/Windows/ESXi 6/Redfish 10 SUCCESS, T6·S3 UNSTABLE 기대) — main 과 동일한 결과.
- **정정**: DIMM 원인의 버전 귀속 — IEC 표기는 upstream 2025-04-24 "Use binary unit prefixes"(3.6 릴리스 이후), RHEL 9.6 의 3.6 은 SI. 결론 불변(EXTERNAL_CONTRACTS · FAILURE_PATTERNS).
- **원복·정리**: Runner03 임시 `cj` 제거(나머지 라벨 유지) · Runner01/02/04 는 주체 미상이라 유지 · 임시 파일 정리: vault 암호 파일(실행마다 생성·삭제, 잔존 0) · 세션 시험용 자체 서명 인증서/키(`cert.pem`·`key.pem`, CN=localhost, 만료) · cookie 파일 삭제 · WSL `/tmp` 의 이 세션 prodgen staging(G11/G15/G19, 비밀 없음) 정리(잔존 0) · WSL `/tmp` 에 암호 사본(12 바이트 mktemp) 없음 확인 · Jenkins API netrc 는 마지막 확인 뒤 삭제
- 남은 사용자 조치(5차 시점 — 6차에서 GP-39 해소): `getNodeId` 승인(GP-39) · 자산 6건(GP-37) · 라벨(GP-38) · Portal(GP-42) · Runner /tmp 샘플러(GP-43) · `duration_ms`(GP-44) · GitHub public 정책.

## 일자: 2026-10-04 (4차) — 최종 실행 지시 대응: timeout 상한 범위 · readTrusted 식별 · 증거 직접/추정 · 생성 tree Harness 10 · Runner 자원 실측 · 자산 진단 · **X2 `ec6a494f` → P2 `07ecf7ac`(양 원격)**

> 정본: `tests/evidence/2026-10-04-review-c1-c6.md` §9, `-test-server-roster.md`(정정판), `-kernel6x-compat-matrix.md`, `-gp36-duration-window.md`. 지시서 §2 의 완료 항목(P1 승격 · X7b · DIMM · cj · publish 수정 등)은 다시 열지 않았다.

- **§4 timeout 실제 범위(runtime X2)**: Declarative 소스로 stage `options.timeout` 이 agent 할당과 stage `post` 를 모두 감싸고 pipeline `post` 가 전역 timeout 안임을 확인. Tier 2 상한을 보존 archive/stash(`PRESERVE_STEP` 30 s 각)와 줄 집합 조립 전체(Layer A 읽기·Layer B 적재·raw 검문 — `ASSEMBLE` 60 s → 최소 경로 `ASSEMBLE_MIN` 20 s)로 확장. 기본 모드(`SE_FINALIZER_BOUNDED` false — 사내 main·production·고객사 공통)는 동작 불변이며 선점은 stage 115 min · finalizer 720 s · 전역 150 min 뿐임을 `docs/operate/04` 표로 명시. 숫자 증가 0. 식별 규칙(자기 nodeId만 지역 처리, 그 외 재전파·ABORTED 유지) 불변. 네 번째 서명 `getNodeId` 는 여전히 pending → bounded Harness 5건 PARTIAL/승인.
- **§5 실행 SHA 와 helper**: `seTrusted()` 가 4 readTrusted 뒤 `[Trusted] <path> len jhash` 를 남기고 증거 수집기가 bound revision 의 `git show` 와 대조(UTF-8/ISO-8859-1). fail-closed(E2E-A2) 의 이웃 revision 바인딩은 **추정**으로만 기록되고 승격 증거로 인정되지 않는다 — 직접 증거 = BuildData 또는 트리거 측 tip 관측(`--tip-observations`, CI `E2E_TIP_OBSERVATIONS_JSON`). X2 E2E-A2 #117: `binding=direct` · `tip_frozen:ls-remote`(SCM tip `ec6a494f` 트리거 전후 동일, 빌드 창 포함) · `[Trusted]` 4 파일 UTF-8 일치 — 이웃 추정이 아니다.
- **§6-1**: 생성 tree Harness 10(기존 4 + archive_fail · stash_fail · truncate_jsonl · checkpoint_only_a/b · layer_a_fail) — CI #18: 10/10 PASS(archive_fail · stash_fail · truncate_jsonl · checkpoint_only_a/b · layer_a_fail 포함). **§6-2**: Add-on 정상 실행은 production #76 `data.addon`, Runner 에서의 태스크별 timeout·끊김·격리는 CI Gate 통합 테스트(실제 ansible-playbook)로 종료; 원격 자식 프로세스 잔존(GP-14)·137 경로(GP-19)는 PARTIAL(환경/재현 불가)로 문서화.
- **§7 Runner 용량(GP-18 완료)**: perf-observe Job(/proc 읽기 전용, SE_BUILD_ID 귀속 PSS) 6 빌드 — 13 host 트리 peak PSS 463 MB · 18 host 620 MB · slot 당 36 MB(최악 69 MB Windows worker) · 메인 python 86 MB · swap 0 → `per_fork_mb` 80 · `fixed_mb` 200 · `node_share` 40 % 확정. 같은 Runner 겹침은 Jenkins(LeastLoad)가 분산해 미관측(offline 강제 금지) — 산술 확인만. GP-36 `.161` +1.9 s 는 `duration_ms` 창 변화(Add-on 뒤 재스탬프 + CHECKPOINT)가 59~74 %, 잔여 ≤0.7 s(p=0.068) — 코드 변경 없음. P6/P8 은 trace 상 유의미하지 않아 미구현 종료.
- **§8-2 자산 6건 진단(Runner 망 읽기 전용 net-probe + 워크스테이션)**: `.135 .145 .165` 같은 L2 ARP INCOMPLETE(켜진 호스트 없음) · BMC `10.100.15.3` 양쪽 무응답 · CIMC `10.100.15.1` ServiceRoot **503 "Redfish Service is disabled"**(BMC 설정) · HPE `10.50.11.231` Runner 망 경로만 차단(워크스테이션 ServiceRoot 200). 명부 합계 Linux **15/12** 로 정정(32 실행 · 성공 26 · 미해결 6). 결정은 사용자.
- **§8-3 Portal**: HTTP 200 ≠ 저장. Portal 조회 API 없음(GET 은 HTML 예외 페이지) · UI 로그인 자격 없음 → 저장·반영 **미확인**. 통제된 중복 POST 1회 → 200 + HTML 예외 페이지(본문 재판독은 분류기 거부). X2 부터 2xx 응답 본문 앞부분을 콘솔에 기록: 정상 전달(main #100 S5 · #101 S1 · #102 S4 · #106 ESXi, body 12~47 KB)의 Portal 응답은 **HTTP 200 · 본문 0 B**(JSON 확인 없음) — Harness sink 는 `{"received": true, …}` 를 돌려주므로 echo 자체는 동작한다. 세션의 통제된 중복 재전송(curl, 같은 eventUuid·body)은 200 + HTML 예외 페이지(3,047 B)였다 — 중복 거절일 가능성이 있으나 요청 헤더(Jenkins httpRequest vs curl) 차이 때문일 수도 있어 **미확정**. 저장·반영은 Portal 측 로그/DB 로만 확인 가능(GP-42).
- **X2 → P2**: main E2E 12/12(X2 `e2afb2ef` #97~#108 과 X3 `ec6a494f` #109~#120 두 번 모두 12/12 계약 PASS(T5 ABORTED · T6/cj/S3 UNSTABLE · chj FAILURE 기대값) · Portal 200 · `[Trusted]` 전부 일치) · CI #18 SUCCESS — Gate · Corpus · Budget · Harness main 18/18 · Build · prodtree 10/10 · Drift · Verify COMPLETE_PASS 20/20(tree `de9422fb…`) · VAULT_DECRYPT · Evidence PASS(main 12 항목 전부 direct 바인딩) · Promote DRY_RUN `e2e ok, problems []`; bounded 5 PARTIAL/승인(`getNodeId` pending) · 승격 세션 CLI `promote --sha ec6a494f … --verify-report(CI #18) --e2e-evidence --ci-stage-results --push-remote origin,internal` — 1차(00:50) G18 FAIL 로 거부(원인: 작업 PC git `core.autocrlf=true` 가 drift A1 의 `git archive` export 를 CRLF 로 → manifest 거부, GP-45; 원격 변경 0) · 2차(01:06) G14/G15/G19 FAIL 로 거부(같은 시각 PC 메모리 부족 사건으로 WSL staging·하위 프로세스 실패; 원격 변경 0) · 3차(01:17~01:28, 저장소 설정을 잠시 autocrlf=false) **COMPLETE_PASS → P2 `07ecf7ac`**: Gates-Rerun G11 G12 G13 G14 G15 G18 G19 G20(G19 WSL 3채널 실제 실행 PASS) · Gates-Reused G01~G10 G16 G17 · publish origin "accepted by remote" · internal "already at the new commit (reached via a shared push URL)"(GP-40 수정 동작 확인, partial_push 없음) · 로컬 ref 갱신 · 193 파일 · 개발 경로 0 · trailer Main-SHA `ec6a494f` · Tree-Hash `de9422fb…` · Previous-Production `1f725071` · CI-Build #18 · Verdict COMPLETE_PASS · CI-Stages verified. vault 암호 파일은 실행마다 생성·삭제. · production 재검증 production Job(P2 `07ecf7ac`, 11 빌드 #83~#93): 전부 checkout == P2 · 기대 결과 전부 일치(CAN-1/S1/S2/T2/Linux 15/Windows/ESXi 6/Redfish 10 SUCCESS, T6·S3 UNSTABLE 기대) — main X3 와 동일한 결과.
- 남은 사용자 조치: `getNodeId` 서명 승인(GP-39) · 자산 6건 결정(GP-37) · Runner 라벨 `cj` 정리 지시(GP-38) · Portal 저장/중복 계약 확인(GP-42) · Runner `/tmp` SSH 샘플러 잔여 파일 정리(GP-43, 분류기가 이 세션의 정리를 거부) · `meta.duration_ms` 의미 결정(GP-44).

## 일자: 2026-10-04 (3차) — 재개 지시 대응: 전체 명부 실수집 완료 · S3(Redfish) · E2E-A/A′/D/E · CI #14/#16 · 성능 전후 · 수집기 수정(X7/X7b) · **실 승격 P1 `1f725071`(양 원격) + production 전수 재검증**

> 정본: `tests/evidence/2026-10-04-review-c1-c6.md` §5-7·§5-8, `-test-server-roster.md`(X6 갱신), `-auto-mode-config-proposal.md`(정정판). 사용자 지시(2026-10-04): 동일 이름 API 토큰 폐기·재발급 **진행하지 않음**.

- **전체 명부 실수집(main X6 `70e4ec8a`)**: OS Linux 16/16 실행(성공 13 · `TARGET_UNREACHABLE` 3 = `.135 .145 .165`) _(4차 정정: 적용 채널 기준 Linux **15/12** — `.95` 를 두 축에 센 집계 오류; 32 실행 · 성공 26 · 미해결 6)_ · Windows 1/1 · ESXi 7/7 실행(성공 6, `.95` 는 ESXi 가 아니라 Ubuntu 24.04 베어메탈 — OS 채널 #54 성공으로 명부 정정) · Redfish 10/10 dry-run(#53: 성공 7, `10.100.15.1` protocol · `10.100.15.3`·HPE `10.50.11.231` reachable 실패) — 누락 0, 미해결 6(자산 상태 사용자 확인 요청, 임의 제외 없음).
- **S3**: OS 채널은 기본 forks 로 유효 창이 120 s 아래(INVALID). 기존 설정 `SE_FORKS_CAP_OS`(Runner03 노드 env) + 다른 Runner 임시 offline 측정창은 분류기 `Node Lifecycle Operations` 거부 → HOLD/권한. **Redfish 채널 #55 PASS**(forced 150 s · rc 124 · outcome timeout · kept 6 실 BMC · filled 1 · Portal 200) — 계약은 채널 무관.
- **E2E-A #42(cj resolve) · E2E-A′ #43(chj 거부) · E2E-D #44→#61(ESXi 6 success) · E2E-E #41(dry-run, Account Write 0)** 모두 계약 PASS. T6 #47 은 controller DNS 일시 장애로 INVALID → #52 PASS.
- **CI #14(X6) SUCCESS**: COMPLETE_PASS(tree `8d0f05c3…` 불변) · VAULT_DECRYPT PASS · Harness 16/16 + 4/4 · Promote dry-run. E2E 탈락 2건은 수집기 결함(E2E-A2: fail-closed 빌드에 BuildData 없음)과 입력 결함(E2E-D 에 `.95`) — **X7 수정**: `evidence.py` `neighbour_revision`(같은 Job 앞·뒤 빌드 revision 일치 시만, `checkout_sha_source` 기록, `fail_closed: True` 계약에 한정) + E2E-A2 검사 보강(`jenkinsfile_obtained` · `stopped_before_agent`); regression 추가(`tests/unit/prodgen` 전부 PASS).
- **성능(GP-30)**: 같은 host 집합 교대 5회 — 총시간 191.2→151.7 s(−21 %, 대부분 Resolve Location 25.9→2.0 s), Gather 152.4→141.0 s(−7 %), Windows `.120` 97.2→74.5 s(−23 %), `.161` 12.6→14.5 s(+15 %, 재확인). Runner peak 자원은 SSH 샘플러 시리즈(§5-9)로 측정 중.
- **Script Approval**: 요구 서명 3건 승인됨(사용자 UI) → bounded 재실행 #187/#188 이 네 번째 `ExceededTimeout getNodeId` 에서 멈춤(이제 pending, hash `dfa1e15`) → 승인 뒤 자동 재실행 대기.
- **승격 완료(GP-21)**: 사용자가 사내 테스트 vault 암호를 제공해 세션 CLI 로 `promote --sha ce50ccf7 … --push-remote origin,internal` 실행 → 환경 의존 gate 재실행(G11~G15·G18~G20, G19 WSL 실행 PASS) → **COMPLETE_PASS → P1 `1f725071`**(parent `4ce90a00`, trailer 완비, runtime-only 193 파일) **양 원격 반영**. `origin` 의 push URL 2개(GitHub+GitLab) 때문에 `internal` 사전 검사가 거짓 partial_push 를 냈고 `push-sync` 로 로컬 ref 정합 — 그 결함은 `_publish` idempotent 처리 + regression 으로 수정(§5-13). **production Job(P1) 재검증**: canary #71 → P-S1/S2/T2/T6 → Linux 15 · Windows 1 · ESXi 6 · Redfish 10 · S3-Redfish 전부 main 과 같은 결과(§5-13). (종전의 "credential 대기" 문구는 이 승격으로 해소됐다 — 4차 §9 정합.)
- Runner SSH(사용자 허용): Runner01~04 사실 기록(RHEL 9.6 · 4 vCPU · 7.5 GB · ansible-core 2.20.3 · dmidecode 3.6) + 자원 샘플러 5쌍(peak ansible RSS 합 ≈ 290~330 MB · CPU 15~17 % · swap 0, 전후 차이 없음 — §5-9·§5-10). 자격은 저장소·문서·로그에 적지 않는다.
- **X7 `24c9fd34` → X7b `ce50ccf7`**: X7 재실행 12/12 계약 PASS(§5-11) 뒤 E2E-A2 검사의 거짓 탈락(controller `Running on Jenkins` 을 agent 로 봄)을 Gather stage 블록 기준으로 고쳐 X7b push; CI #15(X7) 는 그 결함 때문에 내가 중단. X7b 재실행: T2 #80 · T5 #81 · T6 #82 · S5 #83(slot 1·4096) · S1 #84 · S4 #85 · S2 #86 · E2E-A #87 · E2E-A′ #88(neighbours:#87,#89 바인딩) · E2E-D #89(6/6) · E2E-E #90 · S3 #91(timeout·kept 6·filled 1) — 12/12 계약 PASS. CI #16(X7b): SUCCESS — COMPLETE_PASS 20/20(tree 8d0f05c3…) · VAULT_DECRYPT PASS · Harness 16/16 + prodtree 4/4 · bounded 2 PARTIAL/승인 · Promote DRY_RUN e2e ok(problems []) · parent 4ce90a00 — 실 push 는 같은 날 P1 로 완료(위 승격 완료 항목). bounded: 4번째 서명 pending → 승인 뒤 재실행(GP-39).

## 일자: 2026-10-04 (2차) — 완료 보고 검토 C1~C6 대응: 시나리오 계약 E2E 증거 · baseline 기록 탐색 · 환경 미확인 재실행 · 배포 원격 정책 · interruption Harness · vault 복호화 검증 — 승격 미수행, 전체 완료 아님

> 검토(2026-10-04, HEAD `ae4db48b`)가 1차 보고의 "코드 완료 PASS" · "Harness interruption 충족" 을 뒤집었다. 결함 6건은 모두 코드에서 재확인됐다. 정본: `tests/evidence/2026-10-04-review-c1-c6.md`, 결정 `docs/reference/decision-log.md`(2026-10-04 2차), ADR 보완절.
> 사용자 확정 완료 기준(§0): 사내 전체 테스트 서버 실수집 · Kernel 6.x 해결 · 최종 push 와 원격 코드 재검증 — **미충족**(명부 초안 `tests/evidence/2026-10-04-test-server-roster.md`, 실호스트 수집 0).

- **C1 증거 계약**(`scripts/ai/prodgen/evidence.py`): `MAIN_CONTRACT`(S1~S5 · T2 · T5 · T6 · E2E-A/A2/D/E 의 입력 조건·판정 항목·기대 Jenkins 결과)와 Harness 대조(파라미터 `SCENARIO`/`FUNCTIONS_SRC` · `harness_result.json` · `harness_control.json` · 함수 해시).
  main 함수 그룹(16)과 생성 tree 그룹(4, `provenance.tree_hash` == 승격 대상)은 따로 충족. 호출자 EXPECTED 는 계약과 같을 때만. 집계는 입력 digest 선검증. 종전 T2(연결 거부) 증거는 T6 로 재분류.
- **C2 baseline 복구**(`drift.py` · `promote.py`): `baseline_record()` 이력 탐색 + 정상 승격의 `Bootstrap-Baseline(-Tree)` 계승 + `Restore-From`(최신 생성)/`Baseline-Recorded-By`(기록) 분리. B→P1→P2→R→P3 regression + 실 `4ce90a00` 복제 훈련.
- **C3 환경**(`verify/__init__.py`): 식별자 `python · platform · ansible_runtime · ansible_version · collections_sha256 · pwsh/groovy 버전 · jenkins_version`; 미확인 = 불일치; promote 가 환경 의존 gate(G11~G15·G19)를 재실행하고 `gates_rerun/gates_reused`(trailer `Gates-Rerun/Reused`) 기록; `jenkins_version` 은 `/api/json` 헤더(GP-29 종결).
- **C4 정책**(`prodgen/__init__.py` `DEPLOY_REMOTES` · `REQUIRED_CI_STAGES`): 실제 promote/restore 는 `origin,internal` 정확히 — 부분 집합·0개는 `policy` 단계 거부(객체 생성 0); `--ci-stage-results` 필수(같은 SHA · 필수 stage PASS · 보고서 출처 빌드 일치); G20 원격 없음 = PARTIAL. CI Promote 는 호출 전에 `ci_stage_results.json` 을 써서 넘긴다.
- **C5 Harness**: 시나리오 `recover_slow`(필수 승격) · `inner_recover_timeout`/`inner_assemble_timeout`(BOUNDED=true, 승인 실측 → PARTIAL/승인) · `foreign_timeout_interruption` · `user_abort`(자기 빌드 `/stop`) · `aborted_outcome_finalize` · `sink_hold`(T2 수신용). CI 기본 16 + `HARNESS_BOUNDED_SCENARIOS`(stage 결과 `HARNESS_BOUNDED`, 승격 조건 아님). Harness 가 기대 Jenkins 결과(`jenkins_result`)로 판정.
- **C6 vault**: CI Verify 가 같은 바인딩으로 `vault_decrypt_check.py --password-file`(전 Location, 평문 미출력) → `VAULT_DECRYPT`. `location-cj.md` ④' 정정.
- **GP-4**: CI Toolchain 이 `pyVmomi`/`community.vmware` 를 보고(라벨 변경 없음).
- **(뒤) 사용자 명시 승인 뒤 실행된 것**: 사용자가 `!` 로 X2 push → CI #10(Verify COMPLETE_PASS, 환경 식별자 완비; VAULT_DECRYPT FAIL=도구 미추적; Promote dry-run 은 자격 미바인딩으로 PARTIAL 미리보기) · main #8 T2 · #9 T6 · #10 T5 · **#11 S5(RHEL 10.2 kernel 6.12 두 대 — DIMM slot 0 재현)** · #12 S1 · #13 S4 · #14 S2 — 실호스트 6대 수집 success, Portal 200. S3 는 INVALID(환경).
- **X3(진행 중)**: Linux DMI collector 가 SLOT 0 일 때 `handles=`/`raw_head=` 근거를 detail 에 남긴다(`os-gather/tasks/linux/gather_system.yml` · `gather_memory.yml`, 정상 host 영향 0) · CI Promote 가 린터/vault 자격을 바인딩 · `scripts/ai/vault_decrypt_check.py` 추적 복귀(.gitignore 해제) · Harness bounded 시나리오의 설계된 재전파를 PARTIAL/승인 으로 기록.
- **X4 `41fb14b9`(push 됨)**: Kernel 6.x DIMM 제보의 원인은 **RHEL 10 dmidecode 3.6 의 IEC 단위**(`Size: 4 GiB`) — X3 의 raw 근거 marker 로 판정(main #20), 두 단위 환산에 kib/mib/gib/tib 추가(`34808480`), **main #29 에서 `.37/.38` slot 1 · 4096 MB · physical_installed 확인**. 외부 계약 drift 로 EXTERNAL_CONTRACTS 기록. 명부 Linux 15대 실수집: 12 성공 · 3 `TARGET_UNREACHABLE`(.135 .145 .165); Windows 1 성공; ESXi 7 · Redfish 10 은 라벨/트리거 거부로 0.
- **X5 `07affa30`(최종 push)**: 수집기가 Harness 기대 Jenkins 결과를 scenarios.json 에서 읽는다. **CI #13 SUCCESS**: Verify COMPLETE_PASS(tree `8d0f05c3…` = X4) · Harness 16/16 + 4/4 · VAULT_DECRYPT PASS · main E2E 7/7(#33~#40) · Promote dry-run 의 미충족은 S3 · E2E-A · E2E-A2 뿐.
- 남은 차단(실제 거부): E2E-E redfish 트리거 · Runner03 `cj` 라벨(→ E2E-A/A' 와 `esxi` 라벨) · 접속정보 파일 읽기(SSH 원본) · Script Approval API(500 → UI 3건 pending). 승격은 S3 INVALID(환경) · E2E-A/A' HOLD 로 계약상 불가 — 원격 production 은 양쪽 `4ce90a00` 그대로.

## 일자: 2026-10-04 — 잔여 결함 R1~R7 · main 전용 Harness · CI 12 stage · prodgen 판정/승격 모델 · 청주 `cj` — 코드·로컬 회귀·Jenkins 실행(일부) 완료, 승격 미수행

> 결정: `docs/reference/decision-log.md` 2026-10-04 두 항목, `docs/ai/decisions/ADR-2026-10-04-promotion-verdict-and-harness.md`. 실측: `tests/evidence/2026-10-04-residual-r1-r7.md` · `-live-e2e.md` · `-location-cj.md`.
> 2026-10-03 보고서의 "Phase 6 완료 / Phase 7a 완료 / Phase 4 finalizer 완료" 는 정정됐다 — Phase 6 은 CI 미연결(R3), 7a 는 R1·R2·R4 결함, 4 는 R5·R6·R7 결함이었다(`tests/evidence/2026-10-04-final-report.md`).

- **finalizer(R5·R6·R7)**: `lineCount` 로 NPE 제거; stage 기준점은 Resolve Location 끝(`pre/wait_checkout/prep` 로그); interruption 은 어디서도 삼키지 않고 `aborted` 를 기록해 재전파; Tier 1 예산 게이트, Tier 2 `seBounded` 는 nodeId 식별이 되는 Jenkins 에서만(opt-in, 기본 재전파);
  보존은 Layer A / archive / stash 각각 독립(`sePreserveGatherOutput`), `archived && manifestOk && hasResult` 일 때만 deleteDir; 손상 입력에도 host 당 1개 유효 JSON(`seFilterEnvelopeLines` · `unrecovered` · `damage`);
  회수 사다리는 파일별 `unarchive` 이고 `source` 는 입력(final·output·checkpoint)을 돌려준 **매체**다(Harness #30/#34 가 잡은 결함). `not_started_memory` outcome 연결.
- **main 전용 Harness**(`tests/jenkins/harness/`, Job `clovirone-server-gather-harness`): 시나리오당 빌드 1개, wrapper 로 장애 주입(운영 코드 변경 0), POST sink 는 **controller 127.0.0.1**(finalizer 의 httpRequest 가 built-in 에서 나간다), verdict PASS/FAIL/PARTIAL.
  main 함수 12 시나리오 중 10 PASS + 결함 2건 수정 후 CI #7 재검증; 생성 tree 함수(`FUNCTIONS_SRC=artifact`) 는 CI artifact + sha256.
- **prodgen**: `COMPLETE_PASS/PARTIAL/FAIL` · 필수 G01~G20 · binding/`report_sha256` · G14 필수 테스트 그룹 · `e2e-evidence`/`evidence-aggregate` · 상태 LEGACY/PROVENANCE/RESTORED_BASELINE/UNVERIFIED · `--bootstrap-baseline <sha>` · 양 원격 ff 승격(사전/사후 ls-remote · `partial_push` · `push-sync`) ·
  `restore --push-remote` · G19 고객사 main 형태 3채널 실제 실행 · G20 · commit identity 기본값 · POSIX exec bit. **CI #5 Verify COMPLETE_PASS(Runner)**.
- **CI**(`Jenkinsfile_ci`, 12 stage): Checkout → Toolchain(사용자 권한 `pwsh` bootstrap) → Gate → Corpus → Budget → Harness Driver → Prodgen Build → Harness(prodtree) → Drift → Verify(린터 토큰 `se-jenkins-lint` + vault) → Evidence Aggregate → Promote(6항, 기본 dry-run, GitLab 자격 없으면 dry-run 까지).
  Job 정의 `jenkins/jobs/clovirone-server-gather-ci/config.xml`. 실행 중 main 이 움직이면 Harness 는 `MAIN_SHA` 불일치로 거부된다(설계).
- **청주 `cj`**: registry · `vault/cj/`(blob 12 동일) · 테스트 · 문서. alias 없음 → `loc=chj` fail-closed. lab smoke(임시 라벨)는 HOLD/권한.
- **환경(Jenkins)**: `se-jenkins-lint` 폴더 credential(새 API 토큰) 생성 · CI Job config 갱신 · Harness Job 운영 · Runner `pwsh 7.4.6`(사용자 권한). 노드 라벨 변경 0(거부). GitLab push 자격 없음.
- **승격 미수행**: 필수 E2E(S1·S2·S3·T5·E2E-A/A') HOLD/권한, `se-gitlab-push` 없음, `push-sync` 미실행 — `docs/operate/09` §3 · `NEXT_ACTIONS` GP-21/24/25.
- **실환경에서 PASS 한 것**: Harness normal_success(#27/#28/#44) · F 시나리오(§3) · main T2+T6(#4/#5/#6: `TARGET_UNREACHABLE` 관측 · Callback 연결 거부 관측 · body 보존) · G19(CI #3/#5) · CI Verify COMPLETE_PASS(#5).

## 일자: 2026-10-03 — Gathering 개선 Phase 2 · 3 · 4 (정확성 · 성능 · 예산/마무리/Callback) — 코드 수준 완료, 실환경 미검증

> 결정: `docs/reference/decision-log.md` 2026-10-03 (Phase 2~4). 실측: `tests/evidence/2026-10-03-phase2-correctness.md`, `tests/evidence/2026-10-03-phase4-finalization.md`.
> 커밋: `9f94c2ef`(Redfish 페이지네이션·펌웨어·실패 shape) · `b935b20e`(Windows BusType·HBA·DIMM 속도) · `6371ba57`(ESXi host 선택·endPort·timeout) ·
> `a38c6339`(Redfish detect·캐시·deadline·요청 수 gate) · `4fe9712a`(Linux C1/C2/C7) · `954b1b0c`(ESXi P5 facts 재사용) · `5c2c8839`(Phase 4).

- **Pipeline (Phase 4)**: stage 는 Validate → Resolve Location → Gather 셋이고 결과 전달은 pipeline `post { always }` 마무리(`timeout(720 s){ node('built-in') }`)다.
  `Validate Schema` · `Callback` stage 삭제(정합은 `scripts/ai/ci_gate.sh`). Gather 는 `scripts/gather_budget.sh` 로 **ansible 직전** 예산을 재계산해
  `timeout --signal=INT --kill-after=90 <예산> ansible-playbook … -f <forks>` 로 돌리고 rc → outcome 을 기록, post{always} 에서 Layer A
  (`scripts/finalize_gather_output.py`) → archive → stash → 조건부 deleteDir. 마무리는 Layer A 결과 우선 / Groovy 최소 보충으로 접수 수 == 결과 수를 맞춰
  남은 예산 안 ≤3회 POST. 온라인 Runner 부재 = `no_agent` 접수 후 실패 + Callback.
- **콜백·Add-on**: `json_only` 가 host 전이 이벤트(`gather_progress.jsonl`) · `CHECKPOINT`(`gather_checkpoint.jsonl`) · manifest 대조를 기록(OUTPUT/CHECKPOINT fsync).
  4 play 모두 조립 → `inject schema_version` → `CHECKPOINT` → Add-on → OUTPUT 순서(D8); `run_addon.yml` 은 fragment 를 만들지 않고 `_output` 의
  data.addon · errors[] 1건 · meta.finished_at/duration_ms 에만 결합, `ADDON_START`/`ADDON_DONE` 마커, role 태스크별 `apply: timeout`(기본 300 s —
  2026-09-21 "전용 timeout 없음" 결정을 바꿈).
- **task timeout / 인증 증거**: Linux 120 · 자격 probe 60(+ Linux `add_host` `ansible_timeout: 15`, N6) · precheck 120 · ESXi 180 · Redfish detect 120/collect 600/
  account 240(deadline 90/540/180). Redfish 모듈 `attempt` 인자 → `<SE_AUTH_EVIDENCE_DIR>/<ip>/<attempt_id>.json`(비밀값 없음), rescue 가 현재 attempt 파일만 읽어
  401 / 2xx 뒤 정지(`gather`, auth true) / 증거 없음(`stopped_before_auth` → `gather`, auth null) 로 가른다. Windows win_shell 180 은 P4 뒤(strict xfail 추적).
- **정확성·성능 (Phase 2·3)**: 실패 envelope shape 통일(json_only · redfish always); Redfish 멤버 401/403 비차단 · nextLink 페이지네이션 · memory 용량 미확인 구분 ·
  firmware 동일 version 중복만 GET 전 제거 + 대체 fallback · NDF/WWN · C9 판정 · `mode: detect` · 200 캐시 · `deadline` · 8 MiB cap · N3 backoff 생략 — 재생 요청
  R740 168→137 · CSUS 218→134 · DL380 132→131 · SR650 124→123(추가 0); Windows BusType 표·정수형·HBA 미매칭 null·ConnectionType·속도; ESXi `endPort`·Host 선택·
  view 1회·SmartConnect timeout, P5 facts 재사용(13→12); Linux C1/C2/C7(+ 비루트 dmidecode sudo 재시도 수정, `speed_mhz` Configured 우선).
- **Windows P4 (완료, 실 WinRM 미실행)**: win_shell 20→11(왕복 22→13), 항목별 `{ok,error,rows,data}` JSON 문서 + parse/split 로 종전 변수 재구성(아래 체인 글자 동일),
  `-EncodedCommand` 32,767자 한도 발견 → 주석 이동 + 30,000자 상한 테스트, GP-9 `_win_task_timeout` 180 적용(xfail 해제).
- **Phase 6 (완료, Job 미등록)**: `Jenkinsfile_ci`(Checkout MAIN_SHA → Toolchain → Gate → Finalize Corpus(Python+Groovy) → Budget Self-test), corpus 14 case,
  `finalize_corpus_check.py`, `ci_gate.sh` corpus 단계. GP-11: Layer B 함수를 `scripts/jenkins/se_finalize.groovy` 로 분리하고 `Jenkinsfile_portal` 은 `load`(실패 시
  raw 줄 + UNSTABLE). 등록 절차 `docs/operate/03-job-registration.md`.
- **Phase 5 (WSL emulation 완료, 실장비 0대 — `tests/evidence/2026-10-03-phase5-emulation.md`)**: 실패 경로 10~200 host wall ≈ 0.5–0.6 s/host, 요청 == 결과 36회 전부,
  슬롯당 PSS ≈ 36 MB → **OS forks 기본 상한 50**(`SE_FORKS_CAP_OS` 로 상향), INT 6회 중 1회 weakref 콜백에서 소실 → `--kill-after=90` rc 137 경로 실증, progress 비용 노이즈 이하,
  Layer A 1000 host 0.2 s, Redfish 에뮬레이터 불가(443 권한 · 포트 고정 · vault). json_only `first_seen` 이벤트 ip null 수정.
- **Linux P3 (완료)**: 원격 실행 Python 18→10 · raw 13→9(`8616ac48`), fragment 동일(6 캡처 × 6 권한 × 2 모드), driver_map `vlan_id` 항상 null 버그 수정(`5a60d420`).
- **Phase 7a (완료, 7b 보류)**: `scripts/ai/prodgen`(`dcfbfded`) — allowlist manifest · 언어별 주석 제거(A/B) · gate G01~G17 · provenance · drift · plumbing promote/restore;
  `f1221234` 기준 192 파일 · 1.04 MB · B 0 · G01~G13/G15~G17 PASS, G14 는 `source_text` 표식(`6937ba3a`) 뒤 재실행. production push 는 canary 불가로 보류
  (`docs/operate/09-production-branch.md` 3절). `promote_to_production.sh` 는 shim, rule 93/24/90 · CLAUDE.md §14 개정, ADR 2건.
- **미실행(권한 차단 — 사용자 결정 대기)**: Jenkins 두 Job 실제 빌드(§10-4 · §10-5), `.33~.38` SSH, BMC/ESXi 실장비, Runner(2.20.3)에서의 timeout 동작 재확인.
  main Job #1 의 Resolve Location 2분 초과(N1)는 Phase 1.5 코드로 고쳤으나 live 확인 전이다.

## 일자: 2026-10-03 — Gathering 개선 작업 Phase 1(baseline) · 1.5(최소 선행 변경)

> 계획: 사용자 승인 Plan(Astra 3차 검토 조건부 통과, 2026-10-03). 실측: `tests/evidence/2026-10-03-phase1-baseline.md`.
> 후속 표: `docs/ai/NEXT_ACTIONS.md` GP-1 ~ GP-8.

- **왜**: (1) main Job 이 Resolve Location 의 컨트롤러 **전체 checkout** 으로 2분 제한을 넘겨 끊긴다(`clovirone-server-gather-main` #1 ABORTED @ a45ba808).
  (2) 수집이 중단·실패하면 stash 전 단계라 완료된 host 결과까지 유실된다. (3) 이후 Phase 의 live 검증에 Redfish 쓰기 차단(dry-run 강제)과
  배치 상한 파라미터가 먼저 필요하다.
- **Jenkinsfile_portal (Phase 1.5)**: stage 순서 **Validate → Resolve Location → Gather → Validate Schema → Callback**. Validate·Resolve Location 은
  agent 없이 돈다 — Resolve 는 `readYaml text: readTrusted('common/vars/locations.yml')` 로 파일 하나만 읽는다(checkout 0). Validate 가 접수 manifest 를
  `env.SE_MANIFEST_JSON`(빌드·채널·요청 식별·접수 IP) 으로 만들고 Gather 가 node 진입 직후 `gather_manifest.json` 으로 쓴다. Gather `post{always}` 가
  `archiveArtifacts(gather_output.json · gather_manifest.json · gather_rc.txt)` → `stash(allowEmpty)` → `deleteDir` — steps 안 stash 삭제.
  검증용 파라미터 `redfishAccountDryrun`(false → true 일 때만 `-e _rf_account_service_dryrun=true`) · `gatherBudgetForceSec`('' → 값이 있을 때만
  `timeout --signal=INT --kill-after=90`, rc 는 `gather_rc.txt`). inventory_json 이 배열이 아니거나 원소가 객체가 아니면 NPE 대신 명확한 오류(새 거부 없음).
  온라인 Runner 부재는 아직 Resolve 에서 `error`(접수 후 실패 + Callback 은 Phase 4 finalizer 와 함께).
- **WSL 선행 검증(§6-7)**: `include_tasks/include_role apply: {timeout}` 은 task 단위; task timeout 시 `register` 가 `timedout` 키로 채워지고
  `failed_when: false` 는 막지 못함(`ignore_errors` 는 막음); **timeout 뒤 local 모듈 프로세스는 살아남는다**(모듈 내부 deadline 이 1차 가드);
  `timeout --signal=INT` 종료 시 완료된 OUTPUT 줄 보존·`on_stats` 미호출·자식 정리(KILL 은 고아 잔존); SSH `ConnectTimeout` 은 플러그인 값(cfg 60)이
  앞에 와서 `ssh_common_args` 의 15 가 무시됨(N6 확정 — `ansible_timeout` hostvar 로 고쳐야 함).
- **오프라인 baseline**: Redfish 재생 GET 167/217/131/123(+noauth 1) — firmware 멤버 GET R740 62 · DL380 22 · SR650 26 · CSUS 2; 원격 실행 task
  Linux python 18(+0~2)/raw 13, Windows 20(+2), ESXi 13.
- **Jenkins 실측**: 2.528.3, Runner01~03 라벨 `git linux redfish windows`, Runner04 `git` 만, **`esxi` 라벨 노드 없음**(esxi 수집 불가 — 환경 항목).
  플러그인 `unarchive`·`readTrusted`·`readYaml` 가용, artifact manager 기본. production #58(d549596d, runtime 동등) Stage 시간 23/1.5/170/5.8/33 s.
- **하네스**: `scripts/ai/ci_gate.sh` 신설(compile · field_dictionary · drift · vendor boundary · harness consistency · pytest 2 묶음 · syntax-check;
  건너뛴 단계가 있으면 PARTIAL). `redfish_gather.py` 의 기존 vendor-boundary 위반 2건(iLO 정규식 · XCC 로그)은 rule 12 의 `# nosec rule12-r1` 로 표식.
- **검증**: Jenkinsfile 계약 테스트 69 passed(신규 `tests/unit/test_jenkinsfile_portal_preserve_and_params.py` 10), Jenkins 선언형 린터 validated,
  ci_gate — Windows: pytest 3369 passed/35 skipped/7 xfailed + integration 300 passed/4 skipped, WSL: 3채널 syntax-check 통과.
- **미실행(권한 차단 — 사용자 결정 대기)**: `.33~.38` SSH 읽기 전용 정찰, production Job baseline 빌드 트리거, BMC/ESXi Job 밖 읽기 전용 실행 —
  이 세션의 auto mode 분류기가 거부(Production Reads / Production Deploy). main Job 에서의 Phase 1.5 실제 확인(readTrusted lightweight 동작)도 같은 이유로 미실행.

## 일자: 2026-09-30 — Add-on 변수 이름 정리 (`SE_ADDON_*` → `ADDON_REPO_*` · `ADDON_DIR`)

> 결정 · 대응표: `docs/reference/decision-log.md` 2026-09-30. 실측: `tests/evidence/2026-09-29-addon-per-build-checkout.md` 5절.

- **왜**: `SE_` 접두사는 처음 보는 사람이 뜻을 알기 어렵다 (사용자 요청). 범위는 Add-on 관련 이름만 — Gathering 전체
  변수 이름은 그대로 (사용자 지정).
- **바뀐 이름**: Jenkins 전역 `ADDON_REPO_URL`(켤 때 필수, 유일한 등록값) · `ADDON_REPO_REF` · `ADDON_REPO_CREDENTIALS_ID` ·
  `ADDON_REPO_SSL_VERIFY`, hook 입력 `ADDON_DIR`(`errors[].detail` 포함), 파이프라인 내부 `ADDON_REPO_USER/PASSWORD`.
  `addon_checkout.sh` 의 숨은 timeout override 삭제(180초 고정). 옛 이름은 호환용으로도 읽지 않는다.
- **바뀐 파일**: 메인 `Jenkinsfile_portal` · `scripts/addon_checkout.sh` · `scripts/addon_askpass.sh` · `common/tasks/addon/run_addon.yml` ·
  3채널 `site.yml`(call site 4곳) · 테스트 4 + fixture · 운영/개발 문서 5 · ADR 2 · rule 80 · JENKINS_PIPELINES.
  Add-on 저장소 README · e2e(run.py · Jenkinsfile 주석 · scale_spike) · test_layout. 옛 이름 부재 확인 테스트 2곳.
- **검증**: 메인 unit+e2e 3185 passed, Add-on 단위 74 · hook 통합(WSL) 10 · 3채널 syntax-check · 선언형 린터 통과,
  Add-on 181 passed + WSL 17 passed.
- **Jenkins**: jenkins-prod #11(production `afe3a90c`, 변수 없음) OS 3대가 #10 과 동일. lab Add-on e2e #8 은 PASS 137 / FAIL 3 —
  Windows 에서 Linux 전용 기능 이름(`hosts`)을 "없는 기능" 으로 알리는 2026-09-29 결함(Ansible `fileglob` 이 디렉터리 `*` 를 안 풂)을
  드러냈다. Add-on `6ef226a` 로 수정(controller `glob` filter + 회귀 테스트 5) 뒤 e2e #9 는 PASS 140 / FAIL 0.
- **대기(사용자)**: jenkins-prod 에 `ADDON_REPO_URL` 등록(AP-2) → 제가(AI) 켜진 실행 확인(AP-3).

## 일자: 2026-09-29 — Add-on 을 빌드마다 받는다 (켜기 = 전역 `SE_ADDON_REPO` 1개 · 추가 = 파일 1개 · Runner 무관)

> 결정: `docs/reference/decision-log.md` 2026-09-29, `docs/ai/decisions/ADR-2026-09-29-addon-per-build-checkout.md`.
> 실측: `tests/evidence/2026-09-29-addon-per-build-checkout.md`. 후속 표: `docs/ai/NEXT_ACTIONS.md` AP-1 ~ AP-6.

- **왜**: 신규 Jenkins 는 `git` 라벨 Runner 4대 — 배포 Job 이 노드 한 대에 파일을 놓고 그 노드 환경변수 `SE_ADDON_DIR` 로 켜는
  구조는 스케줄링과 availability 가 묶여 있어 lab(Runner 1대)에서만 맞았다. 사용자 결정: 땜질 대신 구조 재설계, 선택 기준은
  `target_type` 하나, Runner 사전 작업 0, 새 Add-on 은 파일 1개.
- **메인 코드** `3d0fbfa2`(feat) — `Jenkinsfile_portal`: 파라미터 `addonRef`(선택), Validate 형식 검사, Gather 가 전역
  `SE_ADDON_REPO` 가 있을 때만 `scripts/addon_checkout.sh`(신규, `git init` → `fetch --depth 1 <ref>` → 실패 시 전체 fetch 해석;
  브랜치 · `refs/tags/` · 40자 해시, 짧은 해시 거부, `-c http.sslVerify=false` 를 그 git 명령에만) 로 `${WORKSPACE}/addon` 에 받고
  `addon/tools/check_layout.py --targets <서버 종류>` 로 검사한 뒤 ansible `sh` 만 `withEnv(SE_ADDON_DIR)`. 실패 → `unstable("[addon]
  unavailable: …")` + Add-on 없이 수집(host 별 오류 없음), collector 없는 target(rc 3) → 켜지 않음. 자격증명은
  `withCredentials(usernamePassword)` + `GIT_ASKPASS`(`scripts/addon_askpass.sh`, 신규). hook · site.yml 4곳 · 계약 테스트 무변경.
  테스트 신규 2: `tests/unit/test_addon_checkout.py`(bash + 실제 git 14 케이스), `tests/unit/test_jenkinsfile_portal_addon.py`(12).
- **Add-on 저장소** `ed8f320`(로컬, push 는 사용자) — `collectors/<target>/<이름>.yml`(디렉터리 = 지원 target, 파일 = Add-on),
  엔진 `tasks/main.yml` 은 target 디렉터리 fileglob 으로 실행 여부 결정, `addon_plan` 은 이름별 설정 붙이기(`false` 끄기 · 없으면 `{}`),
  `config.yml` 은 rule 대신 `software: {linux: [...], windows: [...]}` + 항목별 `only`, `tools/check_layout.py`(최소 검사),
  `deploy/` 삭제, README 재작성, 테스트 · e2e 시나리오(s01~s15) 새 모양. Windows pytest 177 passed, WSL role 실행 17 passed.
- **문서** `3bba2edf` — `docs/operate/03·04·08`, `02-agent-node`, `contract/01`, `develop/07`, decision-log.
- **검증**: 메인 unit+e2e 3171 passed, 선언형 린터 통과, production `9a194619` 승격(github + gitlab). 실제 Agent 실측: 신규
  Runner01(RHEL 9, 시스템 CA 가 GitLab 자체 서명 인증서를 모름)에서 기본값으로 main · 40자 해시 체크아웃 성공, `SSL_VERIFY=true` 는
  실패(기대) — CA 설치 없이 동작한다는 요구 확인. lab Jenkins #21(전역 변수 없음): `[addon]` 줄 없음, host 결과 #20 과 동일.
- **대기(사용자)**: Add-on `ed8f320` push(AP-1) → lab · 신규 Master 에 `SE_ADDON_REPO` 등록(AP-2) → Jenkins 실행 확인(AP-3, 제가 진행) →
  옛 배포 Job 삭제(AP-4). JV-4(설치 자동화 시드)는 후속만 기록.

## 일자: 2026-09-28 — Agent venv 경로를 파이프라인에서 분리 (`scripts/activate_ansible_venv.sh`)

> 결정: `docs/reference/decision-log.md` 2026-09-28. 실측: `tests/evidence/2026-09-28-runner-venv-path.md`. 후속 표: `docs/ai/NEXT_ACTIONS.md` JV-1 ~ JV-6.

- **코드** `8170ae7d`(feat) — 신규 Runner(`/app/ansible-env`)에서 `. /opt/ansible-env/bin/activate` 가 Gather 를 즉시 실패시키고
  Validate Schema 는 시스템 python 3.9 로 조용히 통과하던 문제. venv 선택 규칙을 `scripts/activate_ansible_venv.sh` 한 파일로
  (`SE_ANSIBLE_VENV` → PATH 의 `ansible-playbook` → `/app/ansible-env` → `/opt/ansible-env` → 실패). 호출부는
  `Jenkinsfile_portal` Gather · Validate Schema(`set -eo pipefail` 추가), freestyle Job 사본, `verify_account_provision.sh` 각 한 줄.
  비운영 `Jenkinsfile` · `Jenkinsfile_portal_test` · `test_sj` 삭제(사용자 결정 — pytest 회귀는 로컬), `.gitattributes` `Jenkinsfile* eol=lf`.
- **문서** `da91b274` — `docs/operate/01·02·03·04·08`, overview/02, contract/01, develop/01·06, README, REQUIREMENTS, decision-log.
  Job 은 `production` 브랜치(사용자가 전환) — `main` 전체 체크아웃(약 17k 파일)이 Resolve Location 2분 제한을 넘겼다.
- **하네스** `7b36aaa6` — rule 80 R1/R1-A(단일 파이프라인 + venv 규칙), rule 00/13/22/23/40/92, infra/output-schema 컨텍스트,
  jenkinsfile-engineer agent, JENKINS_PIPELINES 노드 표 실측 정정, `verify_docs_references.py` 는 산문의 `Jenkinsfile` 을 경로로 보지 않는다.
- **검증**: unit 2446 · e2e 723 · 헬퍼 단위 10 · 선언형 린터 · Runner 4대 + lab 155 stdin 실행 · lab Jenkins #20(production `e7baaa55`)
  Gather/Validate Schema `[venv] /opt/ansible-env (source=path)`, host 결과 #18 과 동일, Callback 은 sink 라 UNSTABLE(의도).
  신규 Jenkins `clovirone-cicd/clovirone-server-gather` #8(Runner git 설치 + credential 등록 뒤): Gather(Runner03)/Validate Schema(Runner01)
  `[venv] /app/ansible-env python=3.12.9 (source=path)`, host 결과 동일 — 두 배치 모두 코드 변경 없이 통과.
- **보류(사용자·설치자동화 몫)**: `ic/chj/yi` 라벨 부재, `SE_ADDON_DIR` 경로가 `jenkins` 계정과 불일치,
  설치 자동화 시드 사본 동기화, 154 venv 부재, lab `git/테스트 액션` Job(삭제된 `Jenkinsfile` 사용).

## 일자: 2026-09-22 (4) — Add-on 사용자 관점 감사 — README 사용 설명서화 · 주석 최소화 · match 누락 알림

> 배경: 사용자 요청(현장 엔지니어가 README · config.yml 만 보고 쓰는가). 구조 · 계약 불변, 새 Markdown 없음.
> 후속 표: `docs/ai/NEXT_ACTIONS.md` AO-17 · AO-18.

- **Add-on** `f59d819`(docs) · `4be4bfb`(fix) · `83cddde`(test) — GitLab main.
  - README 를 사용 설명서 순서(무엇 → 어떻게 실행 → 기능 상태 → config 고치기 → 반영 → 결과 → 실수 표 → 알려진 동작
    → 관리자용 → 수집 기능 추가)로 다시 씀. "~다" 체. IP · Job 이름 · Agent 경로 · 날짜 · 작업 번호 없음. 예시는 실제
    제품명(Oracle · Tibero / Java · Tomcat / WebLogic) — 코드 · 테스트에는 여전히 Software 이름 없음.
  - `config.yml` 주석 5줄 + 뼈대 예시 1개. runtime · 테스트 주석은 비직관적인 이유 8줄만 남기고 삭제.
  - `addon_core.addon_plan`: match 가 없거나 빈 rule 을 `errors[]` 알림으로 드러냄(적용은 여전히 하지 않음).
- **메인** `18b59ad9`(docs) — `docs/operate/03-job-registration.md` 에 Add-on Job 등록 위치(개인 폴더 · 저장소 URL ·
  credential), `docs/develop/07-addon-hook.md` 참조 2곳. 메인 코드 0줄.
- **검증**: Add-on pytest Windows 133 passed / 14 skipped, WSL role 실행 14 passed. 흔적 grep 은 배포 · e2e 파라미터
  기본값만 남음. e2e 재실행 없음(runtime 변경은 필터 알림 1가지).
- **사용자 몫**: AO-7 → AO-10, AO-12, AO-9, AO-5 (변동 없음). AO-17 이름 통일 · AO-18 Job 폴더 이동은 선택.

## 일자: 2026-09-22 (3) — Add-on 구조 감사 (사용자 요청 · 계획서 대조) — 구조 유지, 문서 정합

> 결정: `docs/reference/decision-log.md` "2026-09-22 구조 감사". 후속 표: `docs/ai/NEXT_ACTIONS.md` AO-14 ~ AO-17.

- **감사 결론**: 구현은 원 계획서와 일치한다. target 별 디렉터리 분리 · 저장소 이름 통일 · `\xNN` 치환 위치 이동은
  하지 않는다 (이유는 decision-log).
- **고친 것 (메인 코드 0줄)**: Add-on `3b1df8e` — `config.yml` 에 `rules` 키가 없으면(`rule:` 오타) 알림 (종전엔
  조용히 아무 것도 안 함). Add-on `30080c2` — README 반영 절차(저장소에서 고치고 배포 Job) · `target` 4값 · 미지원
  대상 알림 · 구조도(`addon_text.py` · `deploy/` · `tests/e2e`). 메인 문서 `docs:` commit — `02-output-envelope.md`
  (Portal 이 받는 `\xNN` · Windows 오류 글자 · `data.addon` 없이 addon 오류만 올 수 있음), `07-addon-hook.md`(미지원
  target 은 알림 1문장 — 계약으로 확정), decision-log.
- **확인**: Add-on 저장소 없이도 메인은 문제 없다 — 사용자 질문에 실측으로 답함 (WSL 엔진 테스트 10 passed, 계약 ·
  인벤토리 66 passed, 메인 코드에 Add-on 경로 참조 0 — `test_addon_hook_contract.py:121` 이 오히려 금지한다).
- **사용자 몫(변동 없음)**: AO-7 환경변수 → AO-10, AO-12, AO-9, AO-5. 새로 AO-17(이름 통일 여부)은 선택.

## 일자: 2026-09-22 (2) — Add-on AO-2 · AO-3 적용, Agent 규모 시험, 배포 Job (사용자 지시 "추천대로")

> 후속 표: `docs/ai/NEXT_ACTIONS.md` AO-2 · AO-3 · AO-7 ~ AO-13. 실측: `tests/evidence/2026-09-21-addon-hook-live.md` 9절.

- **Add-on 만 바뀌었다 (메인 코드 0줄)**: Add-on `c3c34ff` — Windows 감싸기 `& { … } *>&1 | Out-String -Stream`
  + 종료 오류 알림(AO-2), 돌려주기 직전 비 UTF-8 바이트를 `\xNN` 글자로(AO-3). 메인은 문서만 — hook 약속에
  "돌려주는 글자는 UTF-8 로 쓸 수 있어야 한다" 추가 (`docs/develop/07-addon-hook.md` 3절).
- **실제 Agent 검증**: e2e #7 PASS 127 / FAIL 0 / KNOWN 0, 엔진 테스트 10 passed, 규모 시험(host 200 · forks 200 ·
  동시 2회) PASS 8/8 · 최대 메모리 0.35GiB.
- **배포**: 배포 Job `형섭/clovirone-gathering-addon-deploy` 로 Agent 에 배치 끝
  (`/home/cloviradmin/clovirone-gathering-addon` → release `7dec7d2`, 기본 config). 노드 환경변수 `SE_ADDON_DIR`
  등록은 공유 Agent 설정이라 자동 권한 검사가 막아 사용자 몫으로 남김 — 등록 전에는 영향 없음.
- **사용자 몫**: AO-7 환경변수 등록 → AO-10 실제 `Jenkinsfile_portal` 확인, AO-12 credential 설명란 정리(API 로는
  비밀값이 깨질 위험이 있어 하지 않음), AO-9 Portal 안내 전달, AO-5 고객 `/etc/hosts` 샘플.

## 일자: 2026-09-22 — Add-on main 병합 · production · GitLab 등록 · Jenkins e2e (사용자 지시)

> 후속 표: `docs/ai/NEXT_ACTIONS.md` AO-1 ~ AO-12. 실측: `tests/evidence/2026-09-21-addon-hook-live.md` 5 ~ 8절.

- **병합 · 배포**: `feature/gathering-addon` 과 다른 세션의 failure_reason 작업을 main 에 병합(`014f0e20`),
  `*.sh` LF 고정(`d6ed2278`), production 승격. Add-on 저장소는 GitLab
  `https://10.100.64.156/root/clovirone-server-gathering-addon.git` main.
- **Jenkins e2e Job**: `형섭/clovirone-gathering-addon-e2e` (10.100.64.153). 실제 Agent `jenkins-agent-dev`
  (ansible-core 2.20.3)에서 운영 Job 과 같은 메인 저장소 · 명령 · vault 로 시나리오를 돌린다. FAIL 0,
  `KNOWN` 은 결정 대기 항목(AO-2 · AO-3)뿐.
- **추가 조사 (수정 적용 안 함 — 사용자 지시)**: AO-3 UTF-8 이 아닌 출력의 실패 지점과 추천안, AO-2 Windows
  PowerShell 5.1 오류 스트림 48 조합 실측과 추천안. 적용은 사용자 결정 대기.
- **테스트 보강**: 엔진 테스트에 `SE_ADDON_DIR` 설정 실수(상위 폴더 · 끝 `/`) 추가. e2e Job 이 같은 엔진 테스트를
  실제 Agent 에서도 돌린다.
- **결정**: Linux `\r\n` 유지(AO-4, 사용자). AO-2 · AO-3 는 같은 날 적용 (위 (2) 항목).

## 일자: 2026-09-21 — 고객별 추가 수집(Add-on) 확장점 추가 (사용자 지시)

> 결정 근거: `docs/ai/decisions/ADR-2026-09-21-gathering-addon-hook.md`, `docs/reference/decision-log.md` 2026-09-21.
> 실측: `tests/evidence/2026-09-21-addon-hook-live.md`. 브랜치 `feature/gathering-addon` — 2026-09-22 main 병합
> (같은 시각 main 작업 트리에서 다른 세션이 failure_reason 작업 중이라 worktree 로 분리해 작업).

- **범용 hook 1개**: `common/tasks/addon/run_addon.yml`. 4 play(Linux · Windows · ESXi · Redfish)가 마지막 수집 뒤 ·
  조립 앞에서 `SE_ADDON_DIR` 이 있을 때만 include 한다. Add-on(별도 저장소 `clovirone-gathering-addon`, Ansible
  role)을 `include_role` 로 실행하고 `_addon_result` → `data.addon`, `_addon_errors` → `errors[]` `section: addon` 1건.
- **inventory.sh 3종**: 호출자 host object 전체를 hostvar `se_host_input` 으로 보존. 문자열은 `__ansible_unsafe`,
  `__ansible_*` 예약 키만 제외 (제외하지 않으면 인벤토리 해석 전체 실패 — 실측).
- **불변**: status · sections · diagnosis, `common/tasks/normalize/**`, `callback_plugins/**`, `schema/**`,
  `ansible.cfg`, `vault/**`, `Jenkinsfile*`. `SE_ADDON_DIR` 미설정이면 봉투가 hook 도입 전과 byte 동일 (엔진 테스트).
- **문서**: contract 01 · 02 · 03, `docs/develop/07-addon-hook.md`(신규), `docs/operate/08-ansible-config.md`, decision-log.
- **결정 대기** (`NEXT_ACTIONS.md` AO): Windows 오류 출력 합치기 · UTF-8 이 아닌 바이트 · Linux `\r\n`(결정 T) ·
  hosts DB 판별 규칙. (main 병합 / production 승격은 2026-09-22 완료 — 위 항목)

## 일자: 2026-09-21 — failure_reason 문장 카탈로그 개편 (사용자 확정)

> 결정 근거: `docs/ai/decisions/ADR-2026-09-21-failure-reason-catalog.md`,
> `docs/reference/decision-log.md` 2026-09-21. 후속: `docs/ai/NEXT_ACTIONS.md` FR-1~FR-6.

- **문장 = (failure_code, 대상 종류, 세부 사유).** 정본 `common/vars/failure_reasons.yml` `_fr_catalog[키][채널]`
  (19 키, 채널 os/esxi/redfish/default). 선택은 신규 필터 `filter_plugins/failure_reason.py` 한 곳.
  복제본: `precheck_bundle.FAILURE_REASON_CATALOG`(사전 점검 키), `json_only._FAILURE_REASON_CATALOG`(보충 경로 키).
  `_fr_code_keys` = code 별 허용 키 계약표(런타임 미사용). 종전 `_fr_*` 6문장 / `REASON_*` / `CHANNEL_PROTOCOL_MESSAGES` 폐지.
- **`{loc}` = 실제 실행 위치** (`_cred_location` ← `se_location`, 없으면 `미지정`, 안전 문자 40자).
- **failure_stage / failure_code 불변** — 예외: Redfish 시도 0회 3경우(위치 미등록 / 표준 계정 0개 /
  vendor 미상 + 표준 Vault 부재)가 `GATHER_FAILED`/`gather` → `CREDENTIAL_SET_UNAVAILABLE`/`auth` (결함 수정).
- **결함 수정 2**: `load_one.yml` include_vars `failed_when: false` → `ignore_errors: true`. 복호화 실패가
  empty_accounts 로 오분류되던 것 (WSL ansible-core 2.20.7 실측). 이제 중단 게이트가 수집 전에 멈춘다.
- **OS/ESXi Vault 원인 구분**: `resolve_and_load.yml` 이 파일 부재 시 `vault/<loc>/` 폴더 stat
  (`_cred_location_vault_exists`) → 폴더 없음 = Vault 미등록, 폴더 있음 = 종류별 계정 없음.
- **envelope shape 불변** (13 필드 / diagnosis 8키 / enum). 섹션 문장(section_messages.yml) 불변 —
  단 Redfish 복구계정 부재 행은 `_sm_overrides.account_service`, errors 절단 행은 `_fr_errors_truncated`.
- 변경 파일: `common/vars/failure_reasons.yml`, `filter_plugins/failure_reason.py`(신규),
  `common/library/precheck_bundle.py`, `callback_plugins/json_only.py`, `common/tasks/credential/{load_one,resolve_and_load,resolve_and_load_redfish}.yml`,
  `common/tasks/normalize/{build_output,build_failed_output}.yml`, 3 channel `site.yml`, 테스트 13파일(+1 신규),
  `docs/contract/{03,04}`, `docs/overview/02-architecture.md`, `docs/reference/decision-log.md`, `schema/examples` 2, `schema/output_examples/redfish_failed.jsonc`, `CLAUDE.md` §9 §10.
- **검증**: pytest 전수(브라우저 제외) 통과, 실제 Ansible Templar 렌더 22 통과, WSL `--syntax-check` 3채널 통과,
  WSL 실제 플레이북 실행 5건(3채널 연결 거부 + Redfish 가짜 ServiceRoot 로 위치 미등록 / Vault 복호화 실패).
  **실장비·Portal 표시는 미확인.**

## 일자: 2026-09-14 — OS Vault 2차 infraops fallback 계정 추가 (사용자 지시)

> 커밋 `15f95dca` (main). 순수 데이터 변경 — 코드/스키마/컨트랙트 변경 0.
> 검증 기록: `tests/evidence/2026-09-14-os-vault-infraops-fallback.md`.

- **8개 OS Vault `accounts[]` 재작성.** Linux `infra → infraops`, Windows `administrator → infraops`
  (2차 = `infraops`, role `secondary`, label `{linux,windows}_fallback`). 배열 순서 = 인증 시도 순서.
  기존 `os-gather/tasks/try_credentials.yml` fallback 구조 그대로 사용 — 새 로직/Resolver 없음.
- **ic/chj/yi**: 1차 primary 는 기존 값과 동일(변경 없음), 2차 `infraops` 추가 + legacy 키 제거.
- **git (전용 primary 보존 — 사용자 결정)**: Linux `cloviradmin` / Windows `administrator`(git 전용 password)
  를 1차로 **그대로 유지**하고 2차 `infraops` 만 추가. 4 Location 이 동일 fallback 공유.
- **legacy 키 제거**: `ansible_user`/`ansible_password`/`ansible_become_password` 삭제.
  `accounts[]` 가 우선하고 OS become 은 후보별 `set_fact`(`try_one_credential.yml:22-25`)가 담당 → 동작 불변.
- **검증**: `vault_decrypt_check.py` `[PASS]`, 스테이징 바이트 복호화 8/8 PASS,
  `pytest tests/`(브라우저 제외) **3311 passed / 0 failed**, `--syntax-check os-gather` 정상.
  실장비(SSH/WinRM 실인증)는 Jenkins `os` 게더 6 케이스로 사용자 측 확인 필요 (미완).
- **미변경**: 코드 / Resolver / Precheck / failure contract / Jenkins / inventory / Redfish·ESXi vault.

## 일자: 2026-09-03 — reachable 판정에 ICMP Echo OR 조건 추가 (사용자 지시)

> 결정 근거: `docs/ai/decisions/ADR-2026-09-03-icmp-or-reachability.md`,
> `docs/reference/decision-log.md` 2026-09-03. 후속: `docs/ai/NEXT_ACTIONS.md` RE-1~RE-4.

- **도달성 = 관리 TCP 응답 OR ICMP Echo 응답.** `precheck_bundle._resolve_reachability` 가 정본.
  TCP 를 먼저 보고 **전 포트 무응답일 때만** ICMP Echo 1회(`icmp_check`, `ping` 명령)를 확인한다.
  TCP 가 응답하면(연결 성공/RST) ICMP 는 호출조차 되지 않는다 — 성공·RST 경로 예산 증가 0.
- **ICMP 는 Gate 가 아니다.** 무응답 / 차단 / `ping` 부재 / 권한 부족을 "근거 없음" 하나로 취급해
  판정이 종전(TCP 전용)과 같아진다. ICMP 전용 `failure_code` / `failure_stage` 없음.
  `icmp_probe=false`(`_precheck_icmp_probe`)로 완전히 끌 수 있다.
- **failure_code 9개** (8 → 9): `TARGET_UNREACHABLE` 신설(`stage=reachable`, TCP·ICMP 모두 무응답),
  `TCP_CONNECT_FAILED` 는 `stage=port` 로 범위 축소(ICMP 는 응답, 관리 TCP 만 무응답 — 방화벽 DROP).
  문장 매핑: `TARGET_UNREACHABLE`→1번(종전과 동일), `TCP_CONNECT_FAILED`→**2번으로 이동**
  (ICMP 로 존재가 확인된 대상에게 "IP 사용 여부" 를 묻지 않는다). 표준 5문장 집합은 불변.
- **envelope shape 불변**: 최상위 13 필드 / `diagnosis` 7키 + `details` 그대로. ICMP 관측 근거는
  `errors[].detail` 문자열에만 붙는다 (`icmp: Echo Reply 확인` / `icmp: 응답 없음 (rc=1)`).
- 변경 파일: `common/library/precheck_bundle.py`(+163줄), `common/tasks/precheck/run_precheck.yml`,
  `schema/field_dictionary.yml`(enum + help), `common/vars/failure_reasons.yml`(매핑 주석),
  3 channel `site.yml`(주석만), rule 27 / rule 10 / `CLAUDE.md` §7 §9, `docs/contract/{02,03,04}`,
  `docs/overview/02-architecture.md`, `docs/develop/06-debugging.md`.
- **회귀**: `tests/unit/test_precheck_icmp_reachability.py` 신설(24), 기존 precheck 하네스 10곳은
  `tests/precheck_stub.py` 로 ICMP 결과 주입(실 `ping` 금지). 전체 **3312 passed / 0 failed**.
- **실장비 검증 완료**: Jenkins `clovirone-server-gather` #200(`os`: .163/.145/.120) + #201(`redfish`: .145),
  둘 다 체크아웃 `1fd9fa6d` 확인. `.163` = `TARGET_UNREACHABLE`, redfish `.145`(ICMP 응답 + 443 DROP) =
  `reachable=true` / `stage=port` / `TCP_CONNECT_FAILED` / 2번 문장. `.145`(os) `.120`(Windows, **ICMP 차단**) 은
  vault 자격증명까지 태운 **실수집 success** — ICMP 가 Gate 가 아님이 end-to-end 로 확인됐다.
  에이전트 `ping` 은 `cap_net_raw=ep`, `ping_group_range = 1 0` (비특권 소켓 방식이었으면 실패했을 조건).
  dead host 예산 +1.0~1.1초/대. 증거 `tests/evidence/2026-09-03-icmp-reachability-live.md`.
  남은 것은 Portal 소비자 이행(RE-4) 하나다.

## 일자: 2026-09-03 — OS(Linux/Windows) / ESXi 게더링 전수 검수 후속 (37건 정정, Redfish 제외)

> 결정 근거: `docs/reference/decision-log.md` 2026-09-03 항목. 후속: `docs/ai/NEXT_ACTIONS.md` GA-1~GA-6.

- **hostname 계약**: `system.hostname`(짧은 이름) + `system.fqdn`(hostname + 설정 도메인, 없으면 null).
  Linux `uname -n`/`hostname -d`, Windows `DNSHostName` + AD 도메인/DNS 접미사, ESXi `dnsConfig.hostName/domainName`.
  IP 대체는 rescue(`build_failed_output.yml`) 와 `always` 최종 fallback 까지 제거 — `hostname: null` + `hostname_source`.
- **Linux 는 raw 명령 단일 구현**: `gather_system/cpu/memory/storage/network.yml` 을 다시 썼다. setup fact 는 system 필드
  1순위로만 쓰고 hardware/cpu/memory/storage/network 는 raw 명령(dmidecode/lscpu/lsblk/df/ip) 결과를 python·raw 공통 판정식으로
  만든다. `gather_runtime.yml` 은 삭제 (runtime 이중 구현 제거). hardware 섹션(vendor/model/serial/uuid/bios) 을 낸다.
- **Windows**: `gather_system.yml`(hostname/fqdn/kernel/version/architecture/hosting_type — OEM 목록 없음),
  `gather_hardware.yml`(sku, 수집 판정), `gather_cpu.yml`(캐시 0→null, turbo null), `gather_memory.yml`(JEDEC, null 정합),
  `gather_storage.yml`(int MB, 시리얼 디코딩 조건 강화, health OK/Warning/Critical, IB 벤더),
  `gather_network.yml`(id=어댑터 이름, IPv6, adapters[], MAC 정규화), `gather_runtime.yml`(단일 구현, tri-state, rescue all-null).
- **ESXi**: `esxi_disks.py` 에 `host_info` 파트(dnsConfig / ipRouteConfig / vnic IPv6 / pnic↔pciDevice / cpuInfo.hz / uptime).
  `normalize_system.yml`(hostname/fqdn/정격 클럭/arch 추론/uptime null), `normalize_network.yml`(gateway/is_primary/IPv6/MAC),
  `normalize_storage.yml`(summary = LUN 기준), `collect_runtime.yml`(gateway 경로 제거, `.get()|default` None 버그 제거,
  ntp_synchronized null, firewall enum), `collect_network_extended.yml`(adapters 키 통일, WWN 정규화, HBA vendor).
- **공통**: `common/tasks/normalize/resolve_vendor.yml` 신설(envelope.vendor 단일 경로, 미등록 제조사 null),
  `build_failed_output.yml`(성공 섹션 보존 + partial, hostname 체인, correlation 파생), `build_correlation.yml`(uuid 정규화),
  `filter_plugins/identity_normalizer.py`(normalize_mac / normalize_wwn / normalize_uuid / uuid_byteswap / uuid_equal),
  `supported_sections.yml` + `adapters/os/*.yml` + `schema/sections.yml` 에 hardware(os).
- **schema**: `field_dictionary.yml` +16 항목 / channel·enum 정정 (Must 52 / Nice 134 / Skip 6 = 192), `fields/{common,os,esxi}.yml`,
  `examples/os_partial.json` 정정(hostname IP / bare_metal / uid int / 10 섹션).
- **실장비 검증 완료 (같은 날, Jenkins #190~#196)**: RHEL 8.10 raw fallback / RHEL 9.6 / Dell R760 베어메탈 / Windows Server 2022 /
  ESXi 7.0.3 ×2 — 전부 `status=success`, 자동 계약 점검 이슈 0. 실장비에서만 드러난 6건은 같은 날 후속 커밋으로 정정했다:
  `0076ca67`(SMBIOS Current/Max Speed 3순위 클럭 fallback, Windows 팀 멤버 MAC·IPv6 zone, ESXi cpu_mhz 반올림·vmk link_status 근거),
  `d38bc31b`(정격보다 낮은 터보는 null). 무응답 장비(.163)의 실패 envelope 도 새 계약대로 나왔다.
  증거: `tests/evidence/2026-09-03-os-esxi-live-verification.md` (+ `2026-09-03-live/*.json`).
- **남은 것**: baseline 10건 미재생성 — `schema/baseline_v1/README.md`(수정 금지) 와 rule 13 R4(실장비 검증 후 갱신) 가 충돌해
  **사용자 결정 대기** (갱신용 원본 envelope 은 evidence 디렉터리에 있다). lab 목록의 .167/.169 는 Ubuntu/Rocky 가 아니라 RHEL VM 의
  bond IP 였다 (목록 정정 필요). `ansible-playbook --syntax-check` 로컬 미실행은 Jenkins Agent 실행으로 대체됐다.

## 일자: 2026-09-01 — OS Windows 자격증명 교체 (git 제외 3 Location)

- 사용자 지시로 `vault/{chj,ic,yi}/os/windows.yml` 의 Windows 계정을 교체했다.
  username 을 `administrator` 로, password 를 사용자 제공값으로 바꿨다.
  **`vault/git/os/windows.yml` 은 지시대로 건드리지 않았다** — 이 파일은 이미
  `administrator` 를 쓰고 있고 password 는 별개 값이라 3 Location 과 다르다.
- `locations.yml` 정본이 정의한 Location 은 `cj / git / ic / yi` 4개다 (2026-10-04 `chj` → `cj`).
  `git` 을 뺀 나머지가 정확히 3개이므로 대상 누락은 없다
  (`resolve_credential_scope()` 로 4 Location 전수 경로 판정 확인).
- **평문 구조는 이전과 같다.** `accounts[]` 1개(label `windows_current`, role `primary`)
  + legacy `ansible_user` / `ansible_password` 동기. 값만 바뀌었고 키 추가·삭제 0.
  `normalize_accounts()` 가 이전과 같이 후보 1개를 돌려준다.
- 코드·schema·envelope 무변경이다. Windows 계정 이름을 쓰는 코드가 없기 때문에
  (자격은 전부 vault → `_cred_accounts` 경로로만 흐른다) 분기 영향도 0이다.
- 검증: `vault_decrypt_check.py` 로 vault 49개 전량 복호화 + 구조 검증 통과(exit 0).
  변경 3파일은 기록 후 디스크에서 다시 읽어 복호화 대조까지 했다.
  `git diff --stat -- vault/git/` 0 으로 제외 대상 불변을 확인했다.
- **이 세션에서 못 한 것**: 실 Windows 호스트 WinRM 인증은 시도하지 않았다. 대상 장비에
  `administrator` 계정과 새 password 가 실제로 존재하는지는 저장소 밖 사실이다.
  Jenkins 로 os 채널을 한 번 돌려 `used_label=windows_current` / `fallback_used=false`
  를 확인하기 전까지 실장비 검증은 미완이다.
- `vault/.lab-credentials.yml` 은 손대지 않았다. gitignore 대상이고 vault resolver 가
  읽지 않는 lab 대상 목록이라 이번 계정 교체와 축이 다르다.

## 일자: 2026-08-27 — OS 채널 CSUS 3200 nPartition 시리얼 접미사 정규화

> 후속: `docs/ai/NEXT_ACTIONS.md` CSUS-OS-1

- HPE Compute Scale-up Server 3200 은 OS 안에서 읽는 SMBIOS Type 1 System Serial 이
  `<물리 시리얼>-<파티션번호 3자리>` 형식이다 (`SGHD3TLNDD-000`). 자산 관리 시스템은 물리
  시리얼(`SGHD3TLNDD`)로 서버를 관리하므로 그대로 내보내면 같은 서버가 다른 시리얼로 판정된다.
  **OS 채널에서만** 접미사를 뗀다.
- 새 필터 `filter_plugins/serial_normalizer.py` 하나에 벤더 지식을 모았다.
  `normalize_os_serial(serial, vendor, model)` 은 **세 조건을 모두** 만족할 때만 값을 바꾼다:
  vendor 가 HPE alias 완전 일치 · model 이 CSUS 3200 패턴 매칭 · 시리얼이 `-[0-9]{3}` 로 종료.
  하나라도 어긋나면 입력을 **글자 그대로** 돌려준다. `split('-')[0]` 같은 절단은 쓰지 않는다.
- 호출부 3곳(`linux/gather_system.yml`, `windows/gather_system.yml`,
  `windows/gather_hardware.yml`)은 필터만 부르고 vendor 이름을 모른다 — rule 12 R1 유지
  (`verify_vendor_boundary.py` 기본 모드 위반 증감 0).
- vendor / model 은 시리얼과 **같은 원천**에서 읽는다. Linux = DMI `sys_vendor` /
  `product_name` (setup fact → raw 경로 동일 sysfs), Windows = `Win32_ComputerSystem`.
  둘 다 판정에만 쓰는 task 범위 변수다 — **envelope 필드 추가 0, schema 변경 0**.
- 필터 안의 alias / model pattern 은 저장소 정본(`common/vars/vendor_aliases.yml`,
  `adapters/redfish/hpe_csus_3200.yml`)의 미러이고 drift 가드 테스트가 상시 비교한다.
- Redfish / ESXi 채널은 무변경이다. Redfish `data.hardware.serial` 은 여전히
  `Systems/Partition0.SerialNumber` 원문(`SGHD3TLNDD-000`)이다
  (`docs/ai/contracts/serial-number.md` 29-6). 즉 같은 장비를 OS 로 보면 `SGHD3TLNDD`,
  Redfish 로 보면 `SGHD3TLNDD-000` 이다 — 요구 범위가 OS 채널이라 의도된 차이다.
- **아직 확인 못 한 것**: CSUS 3200 의 **OS 측 DMI 값**(`sys_vendor` / `product_name`)
  실측이 없다. 모델 패턴은 2026-06-15 사이트 실 4노드 Redfish 미러 캡처의 표기를 그대로 썼다.
  사이트 DMI 표기가 다르면 패턴 미매치 → **정규화가 일어나지 않는다**(무해한 no-op).

## 일자: 2026-08-14 — Location ID `ich` → `ic` 개명

> 후속: `docs/ai/NEXT_ACTIONS.md` LOC-1 ~ LOC-3

- Location ID 를 `ich` 에서 `ic` 로 바꿨다. `agent_label` 도 같이 `ic` 로 맞췄다
  (사용자 결정 — 두 값을 분리해 둔 설계상 유지도 가능했으나 맞추기로 했다).
- 실제 변경은 셋뿐이다: `vault/ich/` → `vault/ic/` 디렉터리 rename(내용 무변경),
  `common/vars/locations.yml` 의 키와 label, 그리고 예시 문자열. **코드 분기는 0줄 바뀌었다** —
  Location 목록 정본이 `locations.yml` 하나라서 나머지는 전부 주석·문서·테스트 샘플값이다.
- 4 Location (`ic / cj / yi / git`, 2026-10-04 개명) × 12 = 48개 + 전역 표준 1개 = 49개 vault 구성 유지.
  `vault_decrypt_check.py --layout-only` 로 `ic: 12/12 존재` 확인.
- **아직 반영 안 된 것**: Jenkins 노드의 실제 Labels 는 `ich` 다. 재설정 전까지 `loc=ic` 잡은
  Agent 를 못 잡는다. 호출자가 보내는 `loc` 값도 함께 바뀌어야 한다 (저장소 밖 작업).
- 과거 evidence 의 `ich` 문자열도 사용자 결정으로 함께 치환했다. 단
  `tests/reference/esxi/10_100_64_2/` 의 `nexus-ich` 는 실제 ESXi VM 이름이라 그대로 뒀다 —
  Location 참조가 아니고, 실측 덤프의 장비 사실을 고치면 fixture 가 거짓이 된다.

## 일자: 2026-08-13 — 9 Vendor 조사 반영: 계정 쓰기 계약 정합

> 정본: `tests/evidence/2026-08-13-account-write-contract-alignment.md`
> 계획: `docs/ai/contracts/redfish-account-write.md`

- blind write fallback 을 전부 걷어냈다. `PasswordChangeRequired` 를 덧붙여 다시 POST 하던
  경로와 거부 속성을 빼고 재PATCH 하던 사다리를 제거했다. 무엇을 보낼지는 쓰기 전에
  Family Property Contract 가 정한다. 응답을 보고 정하는 방식이 아니다. 허용되는 다중 쓰기는
  ETag 412 재시도(동일 URI·동일 payload)와 HPE 의 사전 확정 sequence 둘뿐이다.
- Property Contract 를 데이터로 만들었다. Family × Operation 별로
  `writable / read_only / verify_only / unsupported / unverified`. **표에 없는 Property 의
  기본값은 `unverified` 이고 자동으로 쓰지 않는다**. 모르는 속성을 writable 로 가정하는 일은 없다.
- Dell 정책 거부를 200 응답에서 잡는다. `RelatedProperties` / `Severity` 를 읽어 SYS474 류를
  포착한다. 같은 응답에 `Base.1.12.Success` 와 `SYS413` 이 함께 오기 때문에 "성공 메시지가 있으니
  성공" 도 "HTTP 200 이니 성공" 도 성립하지 않는다.
- HPE 는 Family 를 쪼개지 않고 근거만 분리했다. 쓰기 동작(Password 단독 PATCH)은 iLO5/6/7
  동일하다. Evidence 만 `live_proven`(iLO6 1.73) / `advisory_derived`(1.74·iLO7 1.19·1.20) /
  `safety_strategy`(iLO5·1.75+·1.21+) 로 갈린다. **한 대의 실측이 세대 전체로
  번지지 않는다.**
- 보호 계정 판정 축을 바로잡았다. 이제 DMTF `HostBootstrapAccount` Property 를
  본다(실미러 10.50.11.232 에 존재하므로 XCC3 전용 개념이 아니다). slot 번호는 판정 근거에서 뺐다.
  열거·진단에는 남기고 후보에서만 제외한다. 표준 계정 이름이 겹치면 `protected_conflict` → Write 0.
- Family 세분화: Lenovo XCC2/XCC3(PCR 계약 차이), Cisco IMC 3.x(Instance POST),
  QCT 3 Family(동작 동일·경계 기록), Supermicro Superchip 경계. Supermicro Create URI 는
  **장비값으로 Generation+Firmware 를 확정했을 때만** 최신 계약으로 전환한다.
- 진단 축 추가: Huawei 계정별 Redfish Login Interface(읽기 전용), HTTPBasicAuth/AuthMethods,
  `policy_conflict`, 계정 잠금 전 검증 중단, 미지원 RoleId. 전부 진단만 하고 정책은 그대로다.
- 실장비를 재검증했다. git 4대 × (Check Mode + 1차 + 2차) 전부 `success` / `used_role=primary` /
  **Account Write 0**. Create / Repair 는 조건이 발생하지 않아 이번에도 미증명이다.
- 테스트: **3063 passed** (종전 2843 → +220). 계약 불변식 146건을 Family 표 전수로 고정.
- envelope 13 필드 불변 — 신규 진단은 전부 `diagnosis.details.account_service` 하위.

## 일자: 2026-08-12 (r) — 표준 비밀번호 회전 수렴 + Repair 실증 + 평문 Secret 정리

> 정본: `tests/evidence/2026-08-12-standard-password-convergence.md`,
> `tests/evidence/2026-08-12-plaintext-secret-sanitization.md`

- 전역 표준 계정 비밀번호를 회전하고 git Redfish 4대에 수렴시켰다. Credential Contract
  불변: 전역 표준은 `vault/common/redfish/standard.yml` 1벌, Vendor Vault 는 recovery 전용,
  최종 수집은 표준 계정. Vault 49개 decrypt/YAML 전량 성공, Redfish `role: primary` 정확히 1개.
- 1·2차 실행 모두 4대 전부 `status=success` / `used_role=primary` / `attempts=1` /
  **Account Write 0**. Password Convergence 성공.
- Repair 경로 첫 실장비 완주 (Lenovo XCC): 표준 401 → recovery 인증 → `present` →
  `patch_existing` → `write_accepted` → **표준 자격 재인증 성공(`verification=verified`)** →
  표준 계정으로 수집 → 2차 실행 Write 0. Case B 를 `PROVEN` 으로 올렸다.
- Dell Password Strength HOLD → CLOSED. 회전된 값으로 1·2차 표준 인증 성공 + Write 0.
  BMC 정책은 건드리지 않았다. 다만 "Dell 은 선언된 규칙만으로 수용 여부를 알 수 없다"는
  계약은 유효하게 남긴다 (`Security.1.MinimumPasswordScore` 만 활성).
- HPE iLO 쓰기 계약 결함을 발견하고 수정했다. 실장비 통제 실험으로 확정: iLO 는 `Password` 가
  다른 속성과 같은 PATCH 에 오면 **검사도 적용도 하지 않고 버리면서 200 `AccountModified`
  를 준다.** 같은 잘못된 값이 단독일 때는 400 으로 걸린다. 응답으로는 구분 불가라
  Family 가 쓰기 전에 방식을 정해야 한다 → `hpe_ilo5plus.isolated_write_patch = True`.
  부수 2건도 고쳤다: `Locked` 를 실제 잠김일 때만 전송(쓰기 1회 감소),
  재인증 간격을 장비 선언값(`AuthFailureDelayTimeSeconds`)에서 산출.
  검증 의무화(audit H-1)가 없었다면 이 결함은 "쓰기 성공"으로 보고됐을 것이다.
- Dell 세대 판정 버그를 수정했다. `10.100.15.34` 는 iDRAC9(FW 7.10.70.00)인데 Family 가
  `dell_idrac10_slot_patch` 였다. 원인은 adapter 오선택(무인증 probe → fact 없음 →
  priority 로 결정) + 그 hint 를 세대 근거로 그대로 사용(`Manager.Model` 조건은 Dell 에서
  죽은 조건). `reserved_slot_ids` 가 `{1}` vs `{1,2}` 라 빈 슬롯이 2번일 때 PATCH 대상 URI 가
  갈린다. **이름만의 차이가 아니다.** 세대 근거를 Firmware major 로 교정.
  Adapter 오선택 자체는 별도 과제로 남았다(NEXT_ACTIONS PWC-4).
- 저장소 평문 Secret 을 전량 제거했다. tracked 391개 파일에 실 자격증명 10종이 평문으로
  있었다(이번 cycle 이 만든 것이 아니라 사전 존재). 그중 8개가 누출 방지 테스트 자신
  이었다. 가드를 sha256 digest 대조로 바꾸고(`tests/secret_guard.py`) 입력 자격은 합성
  canary 로 교체했다. tracked 17,982개 전수 검사 **digest 0건 / literal 0건**.
  Secret Leak Gate(`scripts/ai/verify_no_plaintext_secret.py`) 신설.
  Git history 와 rotation 은 사용자 지시(§12/§13)로 범위 밖 — NEXT_ACTIONS PWC-1/2.
- 테스트: unit+regression 2007 / e2e 590 / integration 243 = **2840 passed**. 게이트 전량 통과
  (3채널 syntax-check 포함).

---

## 일자: 2026-08-12 (q) — Credential Vault 정리 + git Location 실장비 검증

> 정본: `tests/evidence/2026-08-12-git-location-live-verification.md`

- Vault 26개를 갱신했다. 사용자 제공 Credential 을 기존 Schema 그대로 반영했다.
  표준 계정은 `vault/common/redfish/standard.yml` 1벌, Redfish vendor vault 36개는
  전부 `role: recovery` 단독. 사용자가 제공하지 않은 20개 파일은 확인만 하고 변경 0.
  `vault_decrypt_check.py` 전량 통과(마스터 키 제공, exit=0).
- 후보 정리에는 부수 효과가 따랐다. git Dell 4→1 / Lenovo 3→1 / HPE 3→1 후보. 실측에서 전 채널
  `attempted_count=1`, `fallback_used=false`. 실패 인증 0회로 lockout 위험이 줄었다.
- git Location 실장비 7대상 검증 (WSL ansible-core 2.20.7, production 과 동일 호출).
  Linux 10.100.64.161 / Windows 10.100.64.120 / ESXi 10.100.64.1 / Lenovo 10.50.11.232 /
  HPE 10.50.11.231 / Cisco 10.100.15.2 / Dell 10.100.15.34.
  - OS·ESXi 3대: `success`, scope `git/os/{linux,windows}` · `git/esxi`, used_role=primary
  - Redfish Lenovo·HPE·Cisco: `success`, `credential_scope=common/redfish/standard`,
    used_role=primary, Account Write 0. Lenovo·Cisco 는 **2차 실행도 Write 0** 확인
  - Dell: 표준 401 → 복구 인증 성공 → `presence=present` → `patch_existing` →
    `Locked` read-only 재시도 → 비밀번호가 Security Strengthen Policy 로 거부 →
    `verification=failed`. **계정 상태 변화 0건**(16 slot 전수 전후 비교)
- Family 판정이 Adapter 오선택을 이겼다. Cisco 10.100.15.2 는 adapter 가
  `redfish_cisco_ucs_xseries` 를 골랐지만 장비가 노출한 Roles 어휘
  (`admin/user/readonly/SNMPOnly`)를 근거로 `cisco_cimc_collection_post_id` + `RoleId=admin`
  으로 확정했다. "실제 Capability > Adapter hint" 설계가 실장비에서 동작한다.
- Dell 비밀번호 거부 원인을 규명했다. 길이/대문자/숫자/특수문자/정규식 규칙이 전부 비활성
  (`PasswordMinimumLength=0`, `Require*=Disabled`, `Regex=""`, `MaxPasswordLength=127`)인데도
  거부된다. 남은 강제 조건은 `Security.1.MinimumPasswordScore="Weak Protection"` 하나이며
  Registry 가 이를 *"Password must have this minimum strength score"* 로 정의한다.
  → 규칙이 아니라 **강도 점수(사전/패턴 기반)** 검사가 원인일 가능성이 높다(LIKELY).
  점수 산출 알고리즘·검증 endpoint 는 노출되지 않아 확정 불가(UNKNOWN).
- lockout 예산을 실측했다. Dell 실패 경로에서 `auth_budget={'infraops': 3}`. 종전 구조라면
  최대 9회였고 Dell IP Blocking 기본값(FailCount 3 / FailWindow 60s)을 넘겼을 값이다.
- Compatibility Matrix 를 갱신했다. `hpe_ilo5plus` / `lenovo_xcc_accounttypes` /
  `cisco_cimc_collection_post_id` 3 Family 를 Case A 한정 `PROVEN` 으로 승격
  (검증된 Model+Firmware 범위만). Dell iDRAC9 는 `HOLD`.
  **Account Create 경로는 여전히 어느 Family 에서도 실장비 미증명**. git 4대 모두 표준
  계정이 이미 존재해 `presence=absent` 조건이 발생하지 않았다.
- Production 승격 없음 (사용자 지시).

## 일자: 2026-08-12 (p) — Redfish 계정 Reconcile: Capability Discovery + Family Strategy

> 정본 기록: `tests/evidence/2026-08-12-redfish-standard-account-final-compatibility.md`
> 매트릭스: Vendor × Family 매트릭스
> 결정: `docs/ai/decisions/ADR-2026-08-12-account-family-strategy.md`

9 Vendor 공식조사 9건 + AS-IS 감사를 현재 HEAD 와 대조해 남아 있던 결함을 처리했다.

- C-1 (CRITICAL) 해소 — 계정 열거를 `complete/incomplete/failed` 3-상태로, 존재 판정을
  `present/absent/unknown/ambiguous` 4-상태로 만들었다. Accounts 컬렉션 403/5xx/timeout /
  링크 부재 / member 일부 실패 / `Members@odata.count` 불일치는 전부 `unknown` 이고
  **`unknown` 에서는 Account Write 0건**이다. 종전에는 이 상태가 "계정 없음" 이 되어 실제
  생성 POST 가 나갔다(감사가 production 함수를 실행해 증명).
- C-2 해소: `site.yml` 의 `_rf_auth_rejected` 분모를 `_rf_accounts`(표준+복구 병합) →
  `_rf_standard_accounts` 로 교정. 종전 구조에서는 복구 후보가 있으면 `auth_success` 가
  영영 false 로 확정되지 못했다. **정확히 reconcile 이 가능한 상황에서만 진단이 비는** 셈이었다.
- H-1 은 모든 쓰기 경로에 재조회(`_confirm_account_state`) + 표준 자격 재인증을
  의무화해 해소했다. Ansible 게이트를 `verification == 'verified'` 로 좁혔다(종전은 `'none'` 도 성공).
- H-2 는 `module.check_mode` 를 dryrun 에 OR 해서 해소했다. `--check` 가 실제 PATCH/POST 를
  내보내던 결함이 닫혔다.
- H-3 해소를 위해 `account_service_discover()` 를 신설했다. ServiceRoot 링크 추종(AccountService URI
  하드코딩 제거), Accounts/Roles URI, Password·Lockout 정책, AccountTypes, Manager Firmware
  까지 **읽기 전용**으로 확보한다. 생성 POST URI 하드코딩 5곳도 discovery 결과로 교체.
- Family Strategy 도입: vendor 이름 분기 + 실패 시 payload 사다리(무작위 Write fallback)
  제거. 읽기로 Family 를 확정하고 검증된 방식 하나만 실행한다. 판정 근거 우선순위는
  실제 Resource Capability -> Vendor -> BMC Family -> Firmware -> Generation -> Adapter hint.
  주요 교정: Lenovo Purley = 빈 slot PATCH(POST 아님), Cisco RoleId 는 Roles 어휘에서 선택
  (전 Cisco `admin` 고정 remap 제거), HPE iLO4 `Oem/Hp`, HPE CSUS/Superdome 을 iLO 로
  처리하지 않음, Supermicro 계정분리 세대는 AccountTypes/Firmware 로 판정,
  Inspur `Oem.Public.Status` + Family gated If-Match, Dell iDRAC10 reserved slot 2.
- Lockout: Dell 생성 슬롯 순회 3->1, 표준계정 실패 인증 최대 9회->3회, 후보 간 backoff 는
  **401 일 때만** 65초(설정 가능)로 확대하고 transport 오류는 종전 5초 유지.
- UNVERIFIED Family 는 현행 유지 (사용자 결정) — Fujitsu / Quanta / X-Series / IMM2 /
  Supermicro X9 / Inspur M5·M7 / HPE RMC 는 generic POST 경로와 400/405 retry 를 그대로 둔다.
- 실장비 미러 재생을 신설했다. `tests/reference/redfish/**` 를 읽는 테스트가 0건이던 것을
  (감사 D-8) `tests/integration/test_account_reconcile_replay.py` 로 연결했다. Dell 5 / HPE 1 /
  Lenovo 1 / Cisco 1 호스트 실응답으로 읽기 단계를 검증한다 (43 tests).
- 테스트 2694 -> 2794 passed (실패 0). unit+regression 실행 66.6s -> 18.1s (M-9 부수 효과).
- envelope 13 필드 / sections / field_dictionary 의미 변경 0. 추가는 전부
  `diagnosis.details.account_service` 하위 (Additive only).
- 미해결로 남긴 것: 실장비 Write E2E 0건(어떤 Family 도 `PROVEN` 아님), Dell `HOLD`(E-6
  비밀번호 정책), 운영 Job 은 게이트가 열리면 여전히 실쓰기(사용자 결정), audit H-5 는
  Portal 문장 변경을 수반해 미처리.

## 일자: 2026-08-12 (o) — 실환경 검증 + Fragment/include 버그 2건 수정

> 정본 기록: `tests/evidence/2026-08-12-runtime-verification-and-bugfix.md`.
> 실행 환경: WSL Ubuntu / ansible-core **2.20.7** / Python 3.12.3.

- BUG-1 ESXi `listening_ports` 항상 `[]` — `collect_runtime.yml` 이 `system.runtime` dict 를
  통째로 다시 만들면서 `listening_ports: []` 하드코딩 → `normalize_system.yml` 이 넣은 실제
  수집값을 덮어썼다. `merge_fragment` 는 깊이 2 에서 dict 를 통째로 교체한다.
  실측 `STEP1 ['22','443','902'] → STEP2 []`. 키 제거는 불가(`STEP3 MISSING`).
  → 같은 원본(`_e_raw_listening_ports`)을 이어받도록 수정. **실장비 검증: esxi02 13개 포트 관측.**
- BUG-2 Redfish vendor OEM include 경로 — `{{ playbook_dir }}` 는 `<repo>/redfish-gather`
  이고 그 아래 `common/` 이 없다. 실측 `exit=2 Could not find or access …`.
  영향은 병합 누락보다 크다 — site.yml OEM block 의 rescue 가 발동해 **OEM 데이터가 버려지고
  가짜 오류 1건이 매번 추가**됐다 (재현 실측: errors 1→0, OEM 소실→보존, collected []→['hardware']).
  adapter 전수 파싱 결과 실제 영향은 HPE 7 adapter 전 세대 / Fujitsu / Huawei / Inspur /
  Quanta. `cisco/collect_oem.yml` 은 어떤 adapter 도 참조하지 않는 dead file.
  → 저장소 정식 방식(`REPO_ROOT` 기준)으로 통일. 벤더별 실장비 확인은 lab 부재로 미수행.
- 회귀를 신설했다. `test_fragment_overwrite_and_include_paths.py`(84) /
  `test_auth_evidence_contract.py`(4). 두 버그 주입 실험에서 `exit=1` 검출 확인.
- 3채널 syntax-check os/esxi/redfish 모두 exit=0 (ansible-core 2.20.7).
- 실장비 스모크 6대상: esxi02 / Cisco CIMC / Dell iDRAC / Redfish 503 / RHEL 8.10 /
  Windows 2022. 전부 요청 1 → envelope 1, 13필드 정합.
  503 대상이 `failed + stage=protocol + code=PROTOCOL_CHECK_FAILED + 정본 3번 문장`,
  HTTP 503 은 `detail` 에만 → P0-2/P0-3/§10 실증.
  Dell 은 recovery fallback 성공 + `account_service.dryrun=true`(쓰기 0) 인데
  `status=success, errors=[]` → **P0-7 실증**.
- §4 인증 근거를 검증했다. `_all_sec_collected > 0` 을 인증 근거로 쓰는 것이 타당함을 전수 확인
  (controller-side / precheck / 빈 fragment 경로 모두 0건). 3경로를 테스트로 고정.
- **BLOCKED** — Jenkins 실제 checkout SHA(§8): `10.100.64.153:8080` 은 응답하나 API 가 403
  (자격증명 없음). GitLab internal(`10.100.64.156`)은 이 세션 네트워크에서 timeout.

## 일자: 2026-08-12 — errors[].message 계약 개선 (조사 → 실제 수정)

> 입력: 에러 메시지 전수조사(정리됨) (조사 전용, 코드 변경 0).
> 그 주장을 **현재 코드로 재검증**한 뒤 수정. 정본 기록: `tests/evidence/2026-08-12-errors-message-contract.md`.

- Message 4계층을 확정했다. 전체 실패(6문장, `failure_reasons.yml`) / 섹션 부분 실패(섹션 의미 유지,
  `section_messages.yml`) / 기술 Evidence(`errors[].detail`, string|null) /
  성공 fallback·정보성(`diagnosis.details.notices` — errors 아님).
- 문장은 `failure_code` 에서만 파생: `precheck_bundle.REASON_BY_FAILURE_CODE` 단일 매핑.
  종전에는 문장과 stage/code 가 서로 다른 조건으로 갈려 같은 결과를 Portal 과 대시보드가 다르게 해석했다.
  `TCP_CONNECTION_REFUSED` → 2번 문장("대상 IP의 관리 포트에 연결할 수 없습니다…").
  존재하지 않던 presence 판정(`ip_in_use`) 제거 — **ICMP/IPAM/ARP 기능은 만들지 않았다.**
- Redfish rescue 4필드를 `_rf_auth_outcome` 하나에서 파생 (passed/rejected/unknown).
  인증 통과가 관측된 뒤의 수집 실패에는 자격증명 문장을 붙이지 않는다.
- 성공한 fallback 이 status 를 partial 로 강등하던 경로를 제거했다.
  `redfish_gather.notices()` 신설. DMTF rackmount1 오프라인 재생이 `partial → success` (golden 재생성).
- 소실 경로 배선 — account_service errors 25지점(종전 전량 폐기) / 실패 후보·무인증 probe 근거 /
  rescue 진입 시 누적 섹션 errors / ESXi `_e_disks_ok`·`_e_dns_ok`·`_e_config_ok`(소비처 0건이었음).
- 정규화를 단일화했다. `filter_plugins/errors_normalizer.py` 신설(멱등).
  `message` 는 항상 비지 않은 문자열(파이썬 dict repr 노출 경로 제거), `detail` 은 string|null 통일.
- 게이트를 신설했다. `schema/field_dictionary.yml` 에 `errors[]` 4항목(종전 정의 **0건**),
  `tests/e2e/test_section_message_contract.py`(partial/success 문구 게이트 종전 0건),
  `tests/unit/test_esxi_section_errors.py`.
- 회귀: `pytest tests/` **2094 passed / 10 skipped / 7 xfailed** (착수 전 1974 passed) ·
  field_dictionary PASS · schema-drift exit 0 · vendor-boundary / harness-consistency 통과.
- 미검증: 실장비 / 실 Jenkins / `ansible-playbook --syntax-check` (이 환경에 ansible 미설치).
  Ansible 검증은 production YAML 템플릿을 추출해 Jinja 로 렌더하는 방식이며 실제 플레이북 실행이 아니다.

## 일자: 2026-08-11 (o) — Phase 6-C: 실제 Jenkins Agent / lab BMC 검증

> **코드 변경 0건.** Phase 6-B 결과를 실환경에서 검증만 했다.

- 실제 Jenkins Agent(10.100.64.154) 검증 성공
  - 환경: Ubuntu 24.04.4 / Python 3.12.3 / **ansible-core 2.20.3**(`/opt/ansible-env`)
  - 내부 GitLab main clone = **`ab7f687a`**(= 우리 HEAD). 최신 구현 9종 전부 존재
  - `ansible-playbook --syntax-check` 3채널 exit 0 — **운영 Agent 에서** 통과했다. WSL 통과가 아니다
  - 요청 host 2 → **envelope 정확히 2개**, 중복 0 / 미지 host 0 / 전부 13필드 /
    `errors[0].message == diagnosis.failure_reason`
- lab BMC 실측 (쓰기 강제 off: `-e _rf_account_service_dryrun=true`)
  - Lenovo 10.50.11.232 — `used_role=primary`, `fallback_used=false` →
    **account_service 미진입 = Write 0**. status success / 9 sections
  - Dell 10.100.15.28 — `used_role=recovery`, `attempted=5` → 401 게이트 통과,
    `account_existed=true` / `action=password_sync` / `method=patch_existing` /
    `slot_uri=.../Accounts/3` / `dryrun=true` 라 `recovered=false`, `verification=skipped`
    → **실제 PATCH 미발생 확인**. status success / 9 sections / errors 0
  - → A→B 동기화 경로가 실장비에서 의도대로 진입하고 override 로 쓰기를 막을 수 있음을 확인
- [발견] Dell 10.100.15.28 의 `infraops` password 가 vault 값과 다르다 —
  override 없이 운영 실행하면 이 장비는 password_sync PATCH 가 발생한다(설계된 동작).
- [BLOCKED] 실제 Jenkins 빌드 트리거 불가 — job 60여 개 전부 build token 0,
  익명 API 403, Jenkins admin 자격 없음. **"Job 이 실제로 최신 SHA 를 checkout" 은 미검증**.
  다만 전 job 의 SCM 이 내부 GitLab `origin/main` 이고 그 브랜치가 우리 HEAD 와 같음을 확인했다.
- 회귀: `pytest tests/` **1971 passed / 10 skipped / 7 xfailed** ·
  하네스/경계/schema-drift/envelope/cross-channel exit 0 · field_dictionary PASS.
- Phase 6-C 완료 (빌드 트리거 1건 blocked).

## 일자: 2026-08-11 (o) — Dell 대표 시리얼 1차 교정 (ServiceRoot Service Tag)

- Dell 만 원천을 교체했다. `data.hardware.serial` / `correlation.serial_number` 의 Dell 원천을
  `ComputerSystem.SerialNumber` → **`ServiceRoot.Oem.Dell.ServiceTag`** 로 바꿨다. 사용자 지시
  (2026-08-11) 로 수행한 독립 작업이며 Phase 6-B 와 무관하다. 커밋 `0fb63799`.
- 왜 — Dell 의 `System.SerialNumber` 는 보드 제조 시리얼이다. 동일 R760 실측에서 그 값
  (`CNIVC0048R0159`)은 SMBIOS Type 2(Baseboard) 문자열 `.GSBPK54.CNIVC0048R0159.` 안에만 있고
  Type 1/Type 3 에는 없다 → 같은 장비 Linux(`GSBPK54`)와 값이 달라 채널 매칭이 깨져 있었다.
  교정 후 **Redfish = Linux = `GSBPK54`** 로 일치.
- 원천 근거: Dell iDRAC9 Redfish API Guide "Table 70. Properties for DellServiceRoot" 가
  `ServiceTag` 를 "System Service Tag" 로 정의 (후보 4종 중 Dell 공식 정의가 있는 유일한 필드).
  `SKU` / `ChassisServiceTag` / `NodeID` / BIOS `SystemServiceTag` 는 **폴백으로도 쓰지 않는다**.
- 못 얻으면 실패 — Dell 시리얼은 필수값이라 null 인 채로 success/partial 을 내보내지 않는다.
  기존 실패 계약 재사용(`failure_stage=gather` / `failure_code=GATHER_FAILED`) — **신규 code 0**.
  무인증 ServiceRoot 에 OEM 블록이 없을 때만 인증 ServiceRoot 를 1회 재조회(정상 경로 추가 GET 0).
- schema 무변경 — envelope 13 필드 / sections / field_dictionary entry 추가·삭제 0.
  배선(`normalize_standard.yml` / `build_correlation.yml`) 무변경. 새 필드 만들지 않음.
- 다른 벤더 무변경 — `_SERIAL_RESOLVERS` 에 `dell` 만 등록. HPE / HPE CSUS(`SGHD3TLNDD-000`) /
  Lenovo / Cisco 외 전 벤더는 코드 경로 자체를 타지 않는다. 비-Dell baseline 9종 무변경.
- [INFO] 되돌림 → 재적용 경위 — 이 작업이 진행되는 동안 Phase 6-B 세션이 같은 작업 트리에서
  동시 작업했다. 그 세션은 미커밋 상태였던 본 변경을 "범위 밖 혼입" 으로 판단해 되돌렸다(그 세션
  기록은 아래 (n) 항목). 실제로는 사용자 지시로 수행 중이던 별개 작업이라 Phase 6-B 커밋 완료 후
  **다시 적용**해 `0fb63799` 로 커밋했다. 되돌림 당시 주석 블록 일부가 `5af488ef` 에 섞여
  들어가 있었고(함수 본문 없는 고아 주석) 이번 재적용으로 해소됐다.
- 회귀: unit 1186 / e2e 416 / integration 200 / regression 169 passed ·
  `validate_field_dictionary` / `verify_vendor_boundary` / `verify_harness_consistency` PASS.
- 실 Jenkins 검증 완료 — job `clovirone-server-gather` #188(redfish, Dell 2대) /
  #189(os, 짝 호스트). BMC 10.100.15.34 = OS 10.100.64.96 이 동일 `system_uuid` 위에서
  `correlation.serial_number` **둘 다 `GSBPK54`** → 교정 전 DIFFERENT 가 SAME 으로 해소.
  envelope 13필드 일치 / Stage 3 PASS / errors 0 / 콘솔 `CNIVC` 0회.
- 정본: `docs/ai/contracts/serial-number.md` Part III (29절) /
  `tests/evidence/2026-08-11-dell-serial-service-tag.md`.

## 일자: 2026-08-11 (n) — Phase 6-B: 계정 보정 안전화 + 결과 누락 제거 + 문구 통일

- 평문 자격증명을 제거했다. vault master 와 표준계정 password 가 추적 파일 4곳(3곳은 production)에
  평문으로 있었다. 전부 참조 표기로 교체했고 live vault 자격 16종 전수 잔존 0 확인.
  단 **git history 에는 그대로 남아 있다** (history rewrite 미수행 — 별도 대상).
- [BLOCKED] vault master rotation 미수행 — Jenkins credential store 를 갱신할 수단이 없다
  (익명 API 403 / `cloviradmin` 은 sudo 불가 / CLI SSH 비활성 / Jenkins admin 토큰 없음).
  갱신 없이 rekey 하면 **운영 수집이 전면 중단**되므로 실행하지 않았다.
- 과거 노출 영향 (실측) — BMC `infraops` 5/5 와 vendor recovery 5/5 가 **과거 커밋의 vault 로
  지금도 복호화 가능**. Linux/Windows/ESXi 는 그 사이 변경돼 해당 커밋으로는 유효하지 않다.
- 계정 보정 진입 조건을 강화했다. 종전 "primary 실패 + recovery 성공" → 이제
  **primary 가 구조화된 401 로 거부됐을 때만**. timeout / TLS / 5xx / transport / 403 은 write 0.
  동일 username 다중 slot 이면 중단. `delete_recreate` 는 opt-in(default off).
  A→B password 동기화 기능은 그대로 유지된다.
- unreachable host envelope 소실을 없앴다. 콜백이 host lifecycle 을 추적해 play 종료 시
  누락 host 를 보충한다. 요청 host 1개 = envelope 1개.
- Portal 문구 통일 — Portal 이 실제로 읽는 `errors[].message` 를 `diagnosis.failure_reason`
  에서 **복사**하도록 구조화(`build_failed_output.yml`). 문구는 5종으로 통일하고 정의를 1곳
  (`common/vars/failure_reasons.yml`)으로 모았다. DNS·호스트이름 안내 제거(Portal 은 IPv4 만 전달).
- 운영 Jenkins 정합화 — 내부 GitLab main 이 `c00e2422` 에 머물러 있었다.
  기존 커밋을 지우지 않는 **병합**으로 정합화(`e57598c3`). `Jenkinsfile_portal_test` 보존.
  force/rewrite/reset 미사용.
- 범위 밖 변경 되돌림 — 작업 중 Dell 대표 시리얼을 Service Tag 로 바꾸는 변경이 섞여 들어와
  `schema/baseline_v1/dell_baseline.json`(보호 경로)까지 수정돼 있었다. 이번 Phase 지시에 없고
  `correlation.serial_number` 의 **값 의미**를 바꾸므로 전부 되돌렸다.
- 회귀: `pytest tests/` **1926 passed / 10 skipped / 7 xfailed** ·
  Linux `--syntax-check` 3채널 exit 0 · 하네스/경계/schema-drift/envelope/cross-channel exit 0 ·
  `schema/baseline_v1` 무변경.
- Phase 6-B 완료. vault rotation 과 실장비 계정 검증은 미수행(사유는 위).

## 일자: 2026-08-11 (m) — 실환경 검증 (Phase 6-A) + WinRM 전송 버그 수정

> lab 네트워크가 개발 PC 에서 직접 도달 가능함을 확인해 **실장비 검증**을 처음 수행했다.
> 코드 수정은 실측으로 재현·대조군까지 확보한 **1건**만 했다.

- `ansible-playbook --syntax-check` 최초 실제 통과 — WSL Ubuntu 24.04.3 /
  ansible-core 2.20.7 / vault 암호 적용. 3 채널 전부 exit 0. Phase 1~5-A 내내 "미실행"
  이던 항목이 해소됐다. (`/mnt/c` 는 world-writable 이라 ansible.cfg 가 무시되므로
  Linux 네이티브 경로 사본에서 실행해야 한다.)
- [CRIT] WinRM Identify 전송 버그 수정 — lab Windows(10.100.64.120)가 5985/5986
  양쪽에서 HTTP 401 + 본문 0 을 반환해 정상 Windows 호스트가 전부
  `detected_os=None` 으로 떨어졌다. Phase 3-B 이후 **Windows 수집이 전면 차단**되는 상태.
  원인은 전송 계층이었다. `urllib.request` 가 헤더 이름을
  `capitalize()` / `title()` 로 두 번 정규화해 `WSMANIDENTIFY` 가 `Wsmanidentify` 로 나갔다.
  판정 로직 쪽 문제가 아니다.
  양성 대조군: 헤더 이름만 보존해 보내면 같은 호스트가 HTTP 200 + 완전한
  IdentifyResponse(ProductVendor=Microsoft Corporation)를 반환.
  → `http_post_soap` 의 전송만 `http.client` 로 교체(stdlib 유지). 요청 본문 / 판정 로직 /
  timeout / retry / 인증 시도 횟수 / JSON contract 전부 무변경.
  수정 후 실장비 재검증: `probe_os` OK, `detected_os=windows`, `winrm_scheme=https`.
- 테스트 seam 을 교정했다. 기존 WinRM 테스트는 `http_post_soap` 자체를 mock 해서 버그가 사는
  계층이 테스트에 없었다(전수 통과 ↔ 실장비 100% 실패 동시 성립).
  `tests/unit/test_soap_header_case_preserved.py` 15건이 `http.client` 를 seam 으로 잡는다.
- ESXi 7.0.3 실장비 3대 검증 완료 — `versionId=6.0` 수락, HTTP 200,
  `RetrieveServiceContentResponse`, `about.apiType=HostAgent` / `apiVersion=7.0.3.0`.
  Phase 4-B 의 "wire capture 없음" 한계 해소. probe 0.06~0.11s.
- Redfish BMC 11대 검증 — 9대 정상(Dell iDRAC9 ×5 / AMI ×1 / HPE iLO Gen11 / Lenovo XCC /
  Cisco ×1), cisco 1대는 502·503 흔들림, 1대는 다운. **무인증 ServiceRoot 에서 401/403 을
  반환한 장비 0대** → Phase 4-A 판정을 완화하지 않는다(근거 없음).
  Dell iDRAC 은 HTTP 200 과 함께 `WWW-Authenticate: Basic realm="RedfishService"` 를 보낸다
  — 과거 "401 반환" 기록의 출처로 보인다. trailing slash 는 실장비에서도 갈린다
  (Dell `/redfish/v1` / 그 외 `/redfish/v1/`) → Phase 4-A 의 양쪽 허용이 실제로 필요.
- [CRIT, 미수정] 운영 Jenkins 가 우리 코드를 실행하지 않는다 — job SCM 은 내부 GitLab
  `origin/main`(= `c00e2422`)이고 agent 워크스페이스 지문도 `a382bdee` 시점이다.
  Phase 1~5-A 33 커밋 **0% 반영**. `production` 은 최신이지만 그 브랜치를 보는 job 이 없다.
  → 사용자 결정 필요(rule 93 R1 force 계열 금지).
- [CRIT, 미수정] 수집 도중 unreachable 이면 해당 host envelope 이 사라진다 —
  2 host 투입 → 1 envelope 재현. 두 Jenkinsfile 모두 감지하지 못한다.
- [CRIT, 미수정] Portal 실패 Grid 의 실제 소스는 `errors[].message` —
  `diagnosis.failure_reason` 은 Portal 코드에서 읽는 곳이 0건. Phase 5-A 문구 정화가
  사용자에게 보이는 필드에 적용되지 않았다.
- [CRIT, 사고] 검증 중 BMC 쓰기 1건 발생 — `account_service.yml:43` 이 dryrun 을
  false 로 덮어써 Dell 10.100.15.27 에 `PATCH .../Accounts/3` 이 실행됐다.
- 회귀: `pytest tests/` **1775 passed / 11 skipped / 7 xfailed** · Linux syntax-check 3/3 exit 0 ·
  하네스/경계/schema-drift/envelope/cross-channel exit 0 · `schema/` 무변경.
- Phase 6-A 완료. 위 미수정 CRIT 3건은 사용자 지시 대기.

## 일자: 2026-08-11 (l) — Portal Grid 실패 사유 최종 정리 + 자격 실패 분류 (Phase 5-A)

> `diagnosis.failure_reason` 문구와 자격 실패 해석만 변경. Protocol Probe(OS TCP 폴링 /
> SSH Identification / WinRM Identify / Redfish ServiceRoot / ESXi RetrieveServiceContent)와
> Gathering / Timeout / Retry / 인증 시도 횟수는 손대지 않았다.

- failure_reason 을 Portal Grid 문장으로 통일 — "확인된 상태 + 실패한 현재 단계 +
  확인할 항목" 구조. 앞 단계 성공은 **실제 관측된 경우에만** 표현한다.
  TCP 실패에 "통신은 되지만", RST 에 "서버는 응답하지만" 을 쓰지 않는다(중간 방화벽이
  대신 응답했을 수 있다).
- 관리 포트 번호를 제거했다. os-gather PLAY 1.5 의 `failure_reason` 덮어쓰기 태스크를 삭제했다.
  종전 문구는 `SSH(22)/WinRM(5985, 5986)` 을 Grid 에 그대로 노출했다. 포트 정보는
  `errors[].message` 로 옮겼고 포트별 원본 사유는 `errors[].detail` 에 그대로 남는다.
- OS rescue 의 protocol_supported 정정 — 종전엔 자격 probe 결과를 그대로 썼다.
  Phase 3-B 이후 PLAY 1 이 SSH identification / WinRM Identify 를 실제로 확인해야만
  PLAY 2/3 에 도달한다. 자격 결과와 무관하게 `true` 가 관측된 사실이다.
- Redfish 구조화 인증 거부 — `redfish_gather` 가 module result 에
  `auth_evidence.first_auth_status`(정수)를 싣는다. **자격증명을 실은 요청의 첫 status** 만
  기록하며 새 요청을 만들지 않는다(인증 시도 횟수 = 계정 잠금 위험 불변). 401 이면
  `auth_success=false` + `failure_stage=auth`, 403 은 인증 이후 권한 부족일 수 있어
  거부로 확정하지 않는다(null 유지). 문자열 파싱은 쓰는 곳이 없다.
- Linux / Windows / ESXi 는 auth_success=null 유지 — HEAD 실측 결과 세 채널 모두
  인증 거부와 transport 실패 / 권한 부족 / 제한 쉘 / 모듈 오류를 구조적으로 구분할 필드가
  없다(판정식은 각각 `rc==0 and '__auth_ok__' in stdout` / `ping=='pong'` /
  `ansible_facts is defined`). 남는 단서는 `msg` 문자열뿐이라 확정하지 않는다.
- failure_stage / failure_code enum 무변경 — 7 stage / 7 code 그대로. 신규 stage·code 0개.
- JSON Contract 변경 0 — 새 envelope 필드 없음, `schema_version` `"1"`.
  `auth_evidence` 는 **module result 내부 키**이며 envelope 으로 나가지 않는다.
- 회귀: `pytest tests/` **1731 passed / 11 skipped / 7 xfailed**
  (unit 1063 / e2e 299 / integration 200 / regression 169). 신규
  `test_failure_reason_case_matrix.py` 27건(18 Case 전수 + 단계 진행 관계) +
  `test_credential_probe_classification.py` 13건 + `test_redfish_auth_evidence.py` 14건.
- 보정 3건 (2026-08-11):
  1. Redfish Stage 4 비-401 실패 문구를 `Redfish 서비스는 확인되었지만 BMC에 접속하지 못했습니다.
     자격증명과 계정 권한을 확인하세요.` 로 교체 (다른 채널과 같은 어휘).
  2. `REASON_PORT_REFUSED` 를 `관리 서비스 연결 시도가 거부되었습니다.` 로 교체 — RST 를
     보낸 주체가 최종 대상인지 중간 네트워크 장비인지 확정할 수 없다.
  3. Redfish 복수 후보 집계 규칙 도입 — 후보 하나의 401 로 전체를 확정하던 것을 고쳤다.
     `try_one_account.yml` 이 후보별 `first_auth_status` 를 `_rf_auth_statuses` 에 누적하고
     site.yml 이 (시도 후보 1개 이상) + (후보 수만큼 관측) + (전부 401) 셋을 모두 만족할 때만
     `auth_success=false`. timeout / TLS / 403 / 200 이 하나라도 섞이면 null 유지.
     `first_auth_status` 는 **첫** 인증 응답이라 인증 통과 후의 리소스 401 은 승격되지 않는다.
- Phase 5-A 완료. Authorization 별도 분류 / Portal Receiver 확인 / 실장비 검증 미착수.

## 일자: 2026-08-10 (k) — ESXi 판정을 실제 vim25 SOAP 응답 검증으로 강화 (Phase 4-B)

> ESXi Precheck 의 Protocol Detection 만 변경. Gathering(community.vmware / pyVmomi / facts /
> adapter / normalize)과 OS / Redfish 판정은 손대지 않았다.

- status 기반 판정 폐기 — 종전 `probe_esxi` 는 `GET /sdk` 의 HTTP status
  (`200/301/302/401/403/404/405/500/503`) 만 봤다. 443 에서 뭐라도 응답하면 통과라 일반
  HTTPS 서버가 vSphere 로 판정될 수 있었다. 이제 `/sdk` 에 vim25
  `RetrieveServiceContent` 를 POST 하고 **응답 본문 구조**로 판정한다.
- 요청은 추측하지 않았다 — 설치본 pyVmomi 9.x 의 `SoapStubAdapter.SerializeRequest` 가
  만드는 요청과 **바이트 단위로 동일**함을 오프라인 대조로 확인했다. Content-Type
  (`text/xml; charset=UTF-8`, SOAP 1.1) / `SOAPAction: "urn:vim25/6.0"` 도 pyVmomi
  `InvokeMethod` 헤더와 같다. `versionId=6.0` 은 VMware 자체 CLI govc 의 기본값
  (`GOVC_VIM_VERSION`)이며 저장소 지원 하한(ESXi 6.0)과도 맞는다.
- 비인증 호출 근거: `RetrieveServiceContent` 의 privId 는 `System.Anonymous`
  (pyVmomi typeinfo 실측). Broadcom vSphere WS API 문서도 ServiceInstance 는 인증 없이
  접근 가능하다고 기술한다.
- 최소 성공 조건 2가지
  1) `{urn:vim25}RetrieveServiceContentResponse` → `returnval` → `about` 에
     `apiType` / `apiVersion` 이 채워져 있다. (`about` 은 ServiceContent 필수,
     `apiType`/`apiVersion` 은 AboutInfo 필수 — 둘 다 **API 2.0(version1)부터** 존재해
     6.x/7.x/8.x 공통이다. pyVmomi typeinfo 로 실측.)
  2) SOAP Fault 인데 detail 안 요소의 네임스페이스가 `urn:vim25` / `urn:internalvim25`.
     vSphere 자신이 만든 구조화 Fault 이므로 endpoint 존재의 직접 증거다. 네임스페이스가
     없는 일반 SOAP Fault 는 구별할 수 없으므로 성공으로 쓰지 않는다(문자열 검색 아님).
- 인증과 분리(§9) — Probe 는 자격증명을 보내지 않는다. HTTP 401/403 을 받아도
  `auth_success` 는 `null` 을 유지한다. 실패 시 `protocol` / `PROTOCOL_CHECK_FAILED`.
- failure_reason 무변경 — "예상한 vSphere API 응답을 확인하지 못했습니다..." 문구가
  강화된 관측 수준과도 일치해 그대로 뒀다.
- Timeout / Retry 무변경 — 요청 1회, retry 없음. 최악 수행 시간은 종전과 같다
  (GET 1회 → POST 1회, `timeout_protocol` 은 esxi-gather 가 주는 30초 그대로).
- JSON Contract 변경 0 — 새 필드 없음, enum 추가 없음, `schema_version` `"1"`,
  `schema/` 파일 무변경. `diagnosis.details` 로 나가는 probe_facts 는 종전과 같은 키만
  싣는다(`vsphere_endpoint`, 비-200 일 때 `root_status_code`). 확보한 `apiType`/`apiVersion`
  은 판정 근거로만 쓰고 envelope 에 넣지 않았다(§21 — 필요하면 별도 결정).
  `requires_auth_at_root` 는 도달 불가가 되어 제거했다(baseline 에 없던 키).
- 공통 helper 영향 차단 — `http_post_soap` 에 `content_type` / `max_bytes` 인자를 더했으나
  **기본값이 종전 상수와 같아** WinRM Identify(OS) 동작은 그대로다. `http_get` 는 손대지 않아
  Redfish 경로도 무영향.
- 실장비 미검증(보고 대상) — 저장소에 `/sdk` **wire capture 가 없다.** Positive fixture 는
  lab ESXi 3대(모두 7.0.3 build-20842708)의 실측 AboutInfo 를 pyVmomi 직렬화기로 감싼 것이다.
  6.x / 8.x / vCenter fixture 는 합성이며 "해당 버전 검증 완료" 로 취급하지 않는다.
- 회귀: `pytest tests/` **1676 passed / 11 skipped / 7 xfailed**
  (unit 1049 / e2e 258 / integration 200 / regression 169). 신규
  `test_esxi_precheck_contract.py` 14건 + `test_precheck_probe_esxi.py` 재작성 54건.
  Stage 3(output_schema_drift) PASS / 하네스·경계·envelope·cross-channel 전부 exit 0 /
  Jinja2 239 표현식 컴파일 0 오류.
- Phase 4-B 완료. Credential Probe 원인 세분화 / Authorization 구분 / Portal Receiver 미착수.

---

> 이 아래로 76개 항목이 더 있었다. 작업 이력은 git log 에 그대로 있으므로 여기서는 최근 12건만 유지한다.
> 과거 항목이 필요하면 `git log -p -- docs/ai/CURRENT_STATE.md` 로 본다.
