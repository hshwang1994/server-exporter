# ADR-2026-10-08 — CI 실행시간 개선: 생성물 검증 선행 · Harness 2-lane 동시 실행 · 빌드별 격리 · 후보 고정

상태: Accepted (2026-10-08). 사용자 지시서 "ClovirONE Gathering CI 개선 실행 지시서"(2026-10-07, Astra 실측 기반)의 결정 기록.
`ADR-2026-10-04-promotion-verdict-and-harness.md` 의 CI stage 순서(Harness → Build → Harness(tree) → Drift → Verify)를 대체한다. 승격 조건 · 필수 stage
집합(`REQUIRED_CI_STAGES`) · Evidence 계약 · 시나리오 집합은 바꾸지 않는다.

## 컨텍스트 (Why)

- `clovirone-server-gather-ci` 한 번이 약 80분이었다(#33 80.1 · #34 80.5 · #35 80.3분). 두 Harness 단계가 약 79% 다(#35 2,624 + 1,219초).
  - 시험 66개(main 45 · 생성 tree 21)를 Jenkins 빌드 하나씩 **순서대로** 돌았다.
  - 빌드를 부를 때마다 전역 quiet period 5초를 기다렸다(66회 ≈ 330초). 부모 호출부터 자식 시작까지 중앙값은 7.3~7.7초였다.
  - 생성물 검사(Prodgen Verify, G13 린터 0.5초)가 Harness **뒤**에 있었다. #34 는 빈 `options {}` 를 60분 넘는 Harness 뒤에야 발견했다.
- Harness Job 은 `disableConcurrentBuilds()` 였고, 고정 포트 18080 + 같은 포트 `pkill` + 공유 `…@sink` 폴더를 썼다. 그래서 동시에 돌리면 서로의 수신기를 죽이고
  기록을 지웠다. 또 `checkout scm`(*/main 최신)으로 받은 뒤 MAIN_SHA 와 비교해서, CI 도중 main 이 움직이면 이후 빌드가 모두 실패했다(CI #31).
- 생성 tree 단계 판정이 `result != 'SUCCESS'` 라 기대 ABORTED 와 내부 verdict 를 보지 않았다(main 단계와 달랐다).
- Time Limits 단계가 Gate 의 `tests/unit` 에 이미 들어 있는 시험 5개 파일을 다시 돌렸다(약 80초).

## 결정 (What)

1. **순서**: Checkout → Toolchain → Gate → Corpus → Time Limits → **Prodgen Build → Drift → Verify** → Harness(main) → Harness(tree) → Evidence → Promote.
   Build · Drift · Verify 는 Harness 산출물을 읽지 않는다(G14 는 `git archive` 의 시험). Drift 가 만드는 로컬 production ref 를 G18/G20 이 읽으므로 Drift → Verify 순서는 유지한다.
2. **확정 실패면 긴 시험 생략**: GATE · CORPUS · BUDGET · PRODGEN_BUILD · PRODGEN_VERIFY 중 FAIL 이면 두 Harness 와 Evidence 를 `when` 으로 건너뛴다.
   `ci_stage_results.json` 에 `SKIPPED` + `skipped_because` 로 남긴다 — PASS 가 아니므로 promote 가 거부한다. Drift FAIL(원격 상태)과 PARTIAL 은 막지 않는다.
   앞당긴 Verify 의 COMPLETE_PASS 는 gate 통과일 뿐이다. Harness · main E2E 증거는 Evidence 가 붙이고 promote 의 `check_evidence` 가 본다.
3. **Harness 2-lane**: 시나리오당 빌드 1개는 그대로 두고, 두 고정 lane(i % 2)이 각자 목록을 순서대로 부른다(scripted `parallel`, failFast 없음).
   - `build(..., quietPeriod: 0)` — 고정 후보라 모아서 기다릴 이유가 없다. 전역 quiet period 는 바꾸지 않는다.
   - 결과는 `parallel` 반환값으로만 모은다(공유 List · env 를 분기에서 고치지 않는다). `seMergeLanes` 가 요청 순서로 정렬하고 누락 · 중복 · 섞인 함수 해시를 문제로 남긴다.
   - 동시 실행 수 2 는 Harness 시험 전용이다. main 그룹과 tree 그룹은 겹치지 않는다(그룹 안에서만 2).
4. **판정 통일**: 두 단계 모두 `seHarnessOk(result, expected, verdict, bound)` — 기대 Jenkins 결과 · 내부 verdict PASS · 결속(자식 빌드 변수 `SE_HARNESS_SHA` == MAIN_SHA,
   tree 는 Jenkinsfile_portal sha · 압축 파일 sha · tree_hash 도 같음). 그룹마다 판정 · 집계 자체 시험표(`seHarnessJudgeSelfTest`)를 이 Jenkins 에서 먼저 돈다.
5. **Harness 빌드별 격리**: 동시 실행 금지를 뺀다. 수신기는 `SINK_PORT=0` 이면 OS 가 포트를 정하고 `--ready-file` 로 실제 포트 · pid 를 알린다(고정 sleep 대신).
   controller 폴더는 `<ws>@sink/<빌드 번호>`. 남의 수신기를 `pkill` 하지 않는다. `finally` 에서 이 빌드의 수신기만 — pid 명령줄에 이 빌드의 ready 경로가 있을 때 — 끝낸다.
   판정이 수신 기록의 eventUuid 를 본다. 수동 `SINK_PORT` 기본값 18080(main E2E T2 · T5)은 그대로다.
6. **후보 고정**: `MAIN_SHA` 를 주면 그 commit 을 받는다(SHA 비교 유지). readTrusted 3개 파일은 두 모드 모두 받은 소스에서 읽고, 목록 밖이면 실패시킨다.
   Pipeline 정의는 Job branch 끝에서 와 revision 이 기록되지 않는다. 그래서 `merge-base --is-ancestor MAIN_SHA origin/<branch>` 와
   `git log MAIN_SHA..origin/<branch> -- tests/jenkins/harness/Jenkinsfile_harness` 가 비었는지로 같은 정의임을 확인하고, 아니면 멈춘다.
7. **Time Limits 중복 제거**: Gate 가 `CI_GATE_JUNIT_DIR` 로 JUnit 을 남긴다. Time Limits 는 5개 파일을 다시 돌리지 않고, `tests/scripts/junit_evidence_check.py` 로 대조한다.
   - 지금 모이는 시험 ID 가 기록에 정확히 한 번씩 있고 통과여야 PASS 다.
   - 기록은 이 빌드 시작 뒤에, 같은 host 에서, HEAD == MAIN_SHA 로 남은 것이어야 한다.
   - 건너뜀 · 기록 없음은 PARTIAL, 실패 · 누락은 FAIL.
   - 3채널 시작 계산(`budget_selftest.jsonl`)은 그대로 둔다.
8. **지난 산출물 정리**: CI workspace 를 비우지 않으므로 Toolchain 이 지난 빌드의 산출물을 지운다. 그래야 생략된 단계의 오래된 결과가 집계되지 않는다.
9. **격리 시험 가드**: `HARNESS_JOB` 파라미터를 둔다(비우면 공유 Harness Job). 공유 CI Job 이 아닌 사본은 공유 Harness Job 을 부를 수 없다.

## 결과 (Impact)

- **예상**: 전체 약 45~46분(Harness 약 30분 + 앞 단계 약 15분). 실측은 `tests/evidence/` 의 이 날짜 기록과 `TEST_HISTORY` 를 본다.
- **확정 오류**: Gate · Verify 단계(약 14분)에서 끝난다. #34 같은 실패에 60분 넘는 Harness 를 쓰지 않는다.
- **유지**: 시험 범위(45 · 21 · G14 · G19 · Evidence) · 시나리오당 빌드 1개 · 승격 조건 · runtime 파일은 그대로다. production 생성 tree 에는 변화가 없다.
- **공유 Harness Job**: 반영 뒤 첫 빌드의 `properties()` 에서 동시 실행 설정이 바뀐다. 수동 실행은 여전히 고정 포트 18080 을 쓸 수 있다.
- **남는 틈**: `Jenkinsfile_ci` 자체도 시작할 때 */main 에서 정의를 읽으며 revision 이 기록되지 않는다. 시작부터 Checkout 까지 수 초다. 기존 동작이며 이 결정의 범위 밖이다.

## 대안 비교 (Considered)

| 대안 | 거절 이유 |
|---|---|
| 여러 시나리오를 한 빌드로 합치는 실행기 | ABORTED · UNSTABLE · stash · archive · 빌드 결과가 빌드 단위다 — 흉내 내면 검증이 약해진다(지시서 §3) |
| 동적 작업 대기열(lane 이 다음 시나리오를 가져감) | Scheduler/Queue 성격 · 공유 상태 — 지시서가 금지. 고정 배정의 불균형은 #33/#34 기준 약 1~2분 |
| 시나리오별 Job 복제 · 두 번째 Harness Job | 증거 Job 경로가 갈리고 관리 대상이 늘어난다 — 같은 Job 의 빌드 둘로 충분 |
| Verify 를 Harness 와 동시에 · Gate 와 동시에 | 같은 workspace 경합 · 복잡도 증가. 지시서의 기본 해법은 순서 이동 |
| 빈 포트를 찾아 닫고 다시 열기 | 경쟁 조건 — 수신기가 직접 port 0 에 bind 한다 |
| Evidence 단계가 `check_evidence` 로 판정 | 일상 CI(main E2E 없이)를 UNSTABLE 로 바꾸는 범위 밖 변경 — 승격 경로(promote)가 이미 같은 함수로 판정한다 |
| checkout 재사용(작업 폴더의 .git 유지) | 병렬화 뒤 측정에서 의미 있는 병목일 때만 — 앞 시험 · 다른 후보의 파일을 읽지 않는다는 보장이 먼저다 |
