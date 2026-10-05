# main 전용 실행 Harness — `Jenkinsfile_portal` 함수의 실제 실행 regression

> 작성 2026-10-04 (Astra 2·3·4차 검토 R5/R6/R7 · §5 · §6 반영). **운영 수집 Job 이 아니다.** production 생성 tree 에는 들어가지 않는다
> (`production_manifest.yml` forbidden: `tests/**`, `jenkins/**`). 운영 코드에는 장애 주입 분기가 없다 — 주입은 전부 여기서, 바깥에서 한다.

## 무엇을 검증하나

`Jenkinsfile_portal` 의 최상위 함수(`sePreserveGatherOutput` · `seFinalizeAndCallback` 와 그 helper)를 **글자 그대로** 잘라내어
wrapper 와 함께 `load` 하고, 실제 Jenkins step(`archiveArtifacts` · `stash` · `unstash` · `unarchive` · `node('built-in')` · `httpRequest`)으로
실행한다. 텍스트 검사(`tests/unit/test_jenkinsfile_portal_*.py`)가 "코드가 그렇게 생겼다" 를 보는 것이라면, Harness 는 "그 코드가 Jenkins 에서
그렇게 **동작한다**" 를 본다.

| 파일 | 역할 |
|---|---|
| `Jenkinsfile_harness` | Harness Job 의 파이프라인(scripted). 시나리오당 빌드 1개 |
| `build_functions.py` | 함수부 추출(원본 불변 · 해시 기록) + wrapper 생성. `getParams()` 가 `params` 를 그림자로 덮어 함수가 Harness 의 값을 읽는다 |
| `fixture.py` | corpus case 입력 복사 + **현재 빌드**(job/number/url)와 시험 request 로 manifest 재생성 + 시나리오 변형 |
| `callback_sink.py` | Callback **POST** 수신기(검증 · 응답 통제 · 기록). `python3 -m http.server` 는 POST 를 받지 못한다. Harness 는 이것을 **controller(built-in) 의 127.0.0.1** 에 띄운다 — finalizer 의 `httpRequest` 가 `node('built-in')` 안에서 실행되고(http_request 1.25 는 node 컨텍스트의 노드에서 요청), Runner 는 controller 발 인바운드를 거부했다(Harness #6, NoRouteToHost). Python 3.6 호환(controller python 을 고를 수 없다) |
| `scenarios.json` | 시나리오 정본(입력 case · 변형 · 기대값) |
| `harness_verdict.py` | 관측 ↔ 기대 대조 → `harness_result.json` (PASS / FAIL / PARTIAL) |

## 시나리오 (요약 — 정본은 `scenarios.json`)

- `normal_success` — R5 정상 경로: delivered=true · 보충 0 · lineCount==accepted · `unstable()` 미호출 · deleteDir 도달
- `archive_fail` · `stash_fail` · `both_fail` — R7 보존 단계 독립(F1~F3)
- `truncate_jsonl` · `report_corrupt` · `raw_fallback` — 손상 입력에서도 유효한 Callback body(3차 §6)
- `checkpoint_only_a`(정상 Layer A 가 checkpoint 복구) · `checkpoint_only_b`(Layer A 실패 뒤 Layer B 가 checkpoint 복구) · `layer_a_fail`
- `sink_5xx` · `sink_close` — Callback 실패(통제된 조건)
- `recover_slow` · `archive_slow` · `layer_a_read_slow` — 느린 회수 · 보존 · 읽기. 2026-10-05(8차 R3)부터 안쪽 단계 상한이 없으므로 기다려 완주한다
- `gather_limit_preserve` — 2026-10-05(8차 R1 · R3). **실제 `scripts/run_gather.sh`** 를 가짜 `ansible-playbook`(3대 중 2대의 결과 줄을 쓰고 대기)과
  시험 한계 8초로 실행한다. 한계에 닿아 INT 로 멈춘 실행 기록(`gather_run.json`: rc 124 · timed_out)을 운영 함수 `seGatherOutcome` 이 `timeout` ·
  `gather_limit` 으로 정하고, 같은 빌드에서 `sePreserveGatherOutput` → `seFinalizeAndCallback` 이 끝난 2대는 수집 결과 그대로, 끝나지 않은 1대만
  실패 결과로 채워 전달하는지 본다. 운영 Job 의 시험용 파라미터(`gatherBudgetForceSec`)로 하던 S3 를 대신한다 — 운영 파이프라인에는 시험 입력이 없다.
- interruption 조건(3차 §4, 2026-10-04 검토 C5) — 아래 표
- `aborted_outcome_finalize` — ABORTED 빌드(outcome=aborted)의 사후 보존·finalize: Callback 1회만 시도, 완료 host 데이터 전달, 비정상 종료 unstable
- `sink_hold` — 판정 없음. controller loopback sink 를 `hold_seconds` 동안 열어 두어 **main Job T2**(TEST-NET, `callbackUrl=http://127.0.0.1:<SINK_PORT>`)의 Callback 수신 증거를 `sink/record.jsonl` 로 남긴다

| 조건 | Harness 시나리오 | 기대 | 비고 |
|---|---|---|---|
| ① 느린 회수 | `recover_slow`(unstash 45 s) | 상한 없이 완주(`source=stash`) · delivered | 8차 R3: 안쪽 단계 상한(Tier 2)을 없앴다 |
| ② 수집 실행 한계 | `gather_limit_preserve`(실제 run_gather.sh, 시험 한계 8 s) | `outcome=timeout` · `limit_reason=gather_limit` · 끝난 2대 보존 · 1대 보충 · delivered | 운영 Job 의 강제 한계 S3 대체(8차 R1) |
| ③ 외곽 finalizer timeout | `outer_timeout` | 재전파(`rethrown=true`) · Callback 미시도 | |
| ④ 수집 단계 한계 · 취소 | — (stage 본문은 함수가 아니라 Harness 가 실행하지 못한다) | main Job T5 와 같은 catch(`aborted` 기록 · 재전파) — main Job 에서 확인 | 사후 finalize 경로는 `aborted_outcome_finalize` |
| ⑤ 사용자 중단 | `user_abort`(느린 unstash 중 자기 빌드에 `POST …/stop`) + main Job T5 | 재전파 · Callback 미시도 · Jenkins ABORTED 유지 | |
| ⑥ 다른 원인의 interruption | `foreign_timeout_interruption`(wrapper 가 unstash 안에서 다른 timeout 2 s) | 재전파 — 결과 확인 및 전송 단계는 어떤 interruption 도 삼키지 않는다 | |
| 느린 보존 · 읽기 | `archive_slow`(archive 45 s) · `layer_a_read_slow`(gather_final.jsonl 읽기 45 s) | 상한 없이 완주 | 2026-10-04 최종 지시 §4-3 · 8차 R3 |

## 진단 Job (Harness 와 같은 디렉터리, 2026-10-04~05)

| 파일 | Job | 하는 일 |
|---|---|---|
| `Jenkinsfile_perf_observe` · `perf_observe.py` · `perf_observe_report.py` | `clovirone-server-gather-perf-observe` | 같은 Runner 의 Gather 빌드 프로세스 트리를 `SE_BUILD_ID` 로 귀속해 PSS · 활성 worker · MemAvailable · swap 샘플링(읽기 전용) |
| `Jenkinsfile_net_probe` | `clovirone-server-gather-net-probe` | Runner 망에서 route · ICMP · 관리 TCP · ARP · tracepath · Redfish ServiceRoot(무인증 GET) |
| `Jenkinsfile_term_probe` · `term_probe.sh` | `clovirone-server-gather-term-probe` | 태스크 timeout · 배치 INT · kill-after 경로의 rc · 자식 잔존(자기 marker 만 정리) + Add-on hook 통합 테스트 -v |

## 격리 규칙

- finalizer 는 stash 이름 `gather-output` · 고정 artifact 이름 · `currentBuild.result` 를 쓰므로 **한 빌드에 시나리오 하나**.
- 함수가 부른 `unstable()` 은 wrapper 가 **기록만** 한다 — Jenkins 결과는 verdict 가 정한다(기대 불일치 = UNSTABLE, 도구 실패 = FAILURE).
- 운영 함수가 보는 WORKSPACE 는 `gather_ws/`(하위 디렉터리) — `deleteDir()` 이 Harness 파일을 지우지 않는다.
- 생성 tree 검증(`FUNCTIONS_SRC=artifact`)은 CI 가 archive 한 `prodtree.tar.gz` 를 받아 SHA-256 을 대조하고, `readTrusted` 는 그 tree 의 파일 **내용**을 돌려준다.

## 실행

```text
Jenkins: clovirone-cicd/clovirone-server-gather-harness  (정의: jenkins/jobs/clovirone-server-gather-harness/config.xml)
  SCENARIO=normal_success  [MAIN_SHA=<X>]  [FUNCTIONS_SRC=artifact ARTIFACT_BASE_URL=<ci build>/artifact EXPECTED_SHA256=<sha>]
로컬 도구 검증: python -m pytest tests/unit/test_harness_tools.py tests/unit/test_harness_callback_sink.py -q
```

## 보장 범위와 한계

- 2026-10-05(8차 R3): 결과 확인 및 전송 단계는 안쪽 단계 상한 없이 자기 한계 하나(1시간, `seConstants().FINALIZER`)만 쓰고 어떤 interruption 도 삼키지 않는다.
  그래서 Tier 2(`SE_FINALIZER_BOUNDED`)와 그것이 쓰던 Script Approval 4 서명 실측(`probe_approvals` · `sandbox_probe`)은 없앴다.
  사용자 취소는 `user_abort`(함수 범위)로 자동화하고, 수집 단계를 포함한 전체 경로는 실제 main Job T5 에서 확인한다.
- `gather_limit_preserve` 는 실제 `run_gather.sh` · 운영 함수를 실행하지만 `ansible-playbook` 은 가짜다 — 실제 대상의 원격 정리(R6)는
  `remote_cleanup_probe.sh` 가, 실제 수집은 main · production Job 이 확인한다.
- Harness 의 PASS 는 "함수가 Jenkins 에서 기대대로 동작했다" 이지, 실제 수집 Job(main/production) 의 E2E 나 고객사 실환경 검증이 아니다.
