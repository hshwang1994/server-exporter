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
| `stub_ansible.py` | gather_stage 시나리오의 가짜 `ansible-playbook`(2026-10-06 9차). `--limit @<남은 대상>` 의 대상만 시도별 계획(plan.json)대로 결과 · Precheck 실패 · CHECKPOINT 를 쓰고, 받은 대상을 기록한다. 계획에 따라 수집 셸을 끝 기록 없이 끝내거나(crash) 잠금을 쥔 이전 수집을 남긴다(orphan_hold) |
| `harness_verdict.py` | 관측 ↔ 기대 대조 → `harness_result.json` (PASS / FAIL / PARTIAL) |

## 시나리오 (요약 — 정본은 `scenarios.json`)

- `normal_success` — R5 정상 경로: delivered=true · 보충 0 · lineCount==accepted · `unstable()` 미호출 · deleteDir 도달
- `archive_fail` · `stash_fail` · `both_fail` — R7 보존 단계 독립(F1~F3)
- `truncate_jsonl` · `report_corrupt` · `raw_fallback` — 손상 입력에서도 유효한 Callback body(3차 §6)
- `checkpoint_only_a`(정상 Layer A 가 checkpoint 복구) · `checkpoint_only_b`(Layer A 실패 뒤 Layer B 가 checkpoint 복구) · `layer_a_fail`
- `sink_5xx` · `sink_close` — Callback 실패(통제된 조건)
- `recover_slow` · `archive_slow` · `layer_a_read_slow` — 느린 회수 · 보존 · 읽기. 2026-10-05(8차 R3)부터 안쪽 단계 상한이 없으므로 기다려 완주한다
- gather_stage 시나리오(2026-10-06 9차, 8차 `stub_gather` 를 대신한다) — 운영 함수 **`seGatherStage`** 를 짧은 시험 상수(`constants`)로 그대로 실행한다.
  시도마다 실제 `scripts/run_gather.sh` · `scripts/gather_state.py` 가 가짜 ansible(`stub_ansible.py`)을 남은 대상만 넘겨 실행하고, 마지막 시도가 보존한 뒤
  `seFinalizeAndCallback` 이 전달한다. 실행 기반만 wrapper 가 흉내 낸다 — `node()` 는 Harness 가 이미 잡은 executor 안에서 계획한 만큼 늦게 실행하고
  (결과 처리 노드는 실제 `node('built-in')`), Runner 연결 끊김은 수집 step 뒤 실제 interruption + `retry(agent())` 재호출로, 작업 폴더 사라짐은 `ws` 안 삭제로.
  **운영 Runner 의 executor 를 더 잡지 않는다**(사용자 지시 2026-10-06). 끝나면 이 빌드가 만든 시도 작업 폴더를 지운다.
  - `gather_limit_preserve` — 누적 한계 8초. 3대 중 2대 결과를 쓰고 기다리면 INT 로 멈춘다 → `timeout` · `gather_limit` · 2대 보존 · 1대 보충 · delivered
  - `infra_resume` — 10대 중 4대 결과 · 1대 Precheck 실패 · 1대 CHECKPOINT 만 남기고 끊긴다(Jenkins 가 끊긴 Runner 의 step 을 끝냄) → 같은 Runner 를 20초
    기다린 뒤 결과가 확정되지 않은 5대만 다시 수집(저장소를 다시 받지 않음) → 결과 처리 노드 15초 대기 → 10대 전달. 2번째 시도의 한계 = 누적 − 1번째 실행 시간
  - `infra_wait_expired` — 대기 한도 45초. 1번째 시도는 2대를 끝내고 잠금을 쥔 이전 수집이 남은 채 끊긴다(원본 stash · 즉시 다시 시도 · 이전 수집이 끝나기를 기다림),
    2번째 시도는 1대를 쓰고 끊긴다 → 같은 Runner 를 기다리다 한도 초과 → `infra_wait_expired` · 넘겨 둔 2대 + 실행 기반 문장 2대
  - `resume_impossible` — 끊긴 사이 작업 폴더가 사라졌다 → 전체를 다시 수집하지 않고 `resume_impossible` · 3대 모두 실행 기반 문장
  - `gather_wait_abort` — 같은 Runner 를 기다리는 중 자기 빌드에 `POST …/stop` → 다시 시도하지 않음 · 대기 구간 '취소' · 넘겨 둔 1대 + 실패 2대를 1번 전송 · ABORTED
- 10차 재진입 · 읽기 · 준비 · 보존 · Add-on 시나리오(2026-10-07) — 범용 장애 주입(`faults`: step · 대상 · 몇 번째 · `infra`(실행 기반 오류 → `retry(agent())` 재호출) |
  `fail`(일반 오류))과 느린 step(`slow`)으로 운영 함수를 그대로 끊는다.
  - 결과 처리 재진입(R1): `finalize_reentry`(전송 전 끊김 → 같은 폴더에서 다시 처리 · 1번 전송) · `finalize_reentry_after_delivery`(2xx 뒤 끊김 → 다시 보내지 않음) ·
    `finalize_reentry_expired`(노드를 끝내 못 얻음 → 보내지 못하면 FAILURE) · `finalize_reentry_abort`(취소는 삼키지 않음) · `finalize_limit_cumulative`(긴 step 뒤 끊김 — 결과 처리 시간을 이어 센다)
  - 기록 읽기 예외(R2): `owner_read_transient` · `run_record_read_transient` — 읽기 순간의 실행 기반 오류는 재시도, '기록 없음' 이 아니다
  - 끊긴 준비(R3): `prep_cut_after_owner` · `prep_cut_after_cleanup` · `prep_cut_after_manifest` · `manifest_missing_restore`(접수 원본으로 복원) ·
    `results_missing_refuse`(확정 결과가 사라짐 → 다시 수집하지 않고 재개 불가)
  - 마지막 보존(N1): `preserve_archive_ok_stash_fail` · `preserve_stash_ok_archive_fail` · `preserve_both_fail` · `preserve_cut_before_marker` ·
    `preserve_cut_owner_write` · `preserve_cut_delete` — 보관 또는 전달을 마친 뒤 끊기면 다시 시도하지 않는다
  - Add-on 결정(R4): `addon_decision_transient` · `addon_reuse_disabled` · `addon_copy_restore` — 시험 Add-on 저장소(file://, commit A · B)로 재개가 같은 commit 을 쓰는지 본다
- 실기 드라이버 `Jenkinsfile_live_infra`(main 전용, 임시 노드 se-probe — 운영 Runner 의 executor 를 잡지 않는다): L1~L8 은 가짜 ansible 로 실제 node · 연결 끊김 ·
  작업 폴더 삭제 · 취소를, `REAL` 은 운영 상수 · 실제 ansible · 실제 vault 로 실제 대상을 수집한다(시험 조건 `live_env.json` — 유효 SSH 설정 · 커널 로그 읽기).
  `net_fault_inject.sh` 는 시험 6 · 18(대상 측 일시 네트워크 장애)용 — se-probe Agent 의 cgroup 에서 대상 1대로 가는 패킷만, 그 대상의 인증 통과 진행 기록 뒤에,
  정해진 초 동안 버리고 nftables 표를 지운다(root, 운영 경로 아님).
- interruption 조건(3차 §4, 2026-10-04 검토 C5) — 아래 표
- `aborted_outcome_finalize` — ABORTED 빌드(outcome=aborted)의 사후 보존·finalize: Callback 1회만 시도, 완료 host 데이터 전달, 비정상 종료 unstable
- `sink_hold` — 판정 없음. controller loopback sink 를 `hold_seconds` 동안 열어 두어 **main Job T2**(TEST-NET, `callbackUrl=http://127.0.0.1:<SINK_PORT>`)의 Callback 수신 증거를 `sink/record.jsonl` 로 남긴다

| 조건 | Harness 시나리오 | 기대 | 비고 |
|---|---|---|---|
| ① 느린 회수 | `recover_slow`(unstash 45 s) | 상한 없이 완주(`source=stash`) · delivered | 8차 R3: 안쪽 단계 상한(Tier 2)을 없앴다 |
| ② 수집 실행 한계 | `gather_limit_preserve`(운영 함수 seGatherStage + 실제 run_gather.sh, 누적 한계 8 s) | `outcome=timeout` · `limit_reason=gather_limit` · 끝난 2대 보존 · 1대 보충 · delivered | 운영 Job 의 강제 한계 S3 대체(8차 R1) |
| ③ 외곽 finalizer timeout | `outer_timeout` | 재전파(`rethrown=true`) · Callback 미시도 | |
| ④ 수집 중 · 대기 중 취소 | `gather_wait_abort`(실행 기반 대기 중 취소, 9차) · 수집 실행 중 취소는 main Job T5 | `aborted` 기록 · 재전파 · 다시 시도 없음 | 9차부터 수집 단계 한계는 없다(시도 하나의 실행 한계만) · 사후 finalize 경로는 `aborted_outcome_finalize` |
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
