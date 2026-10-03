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
- `recover_slow` · `outer_timeout` — Tier 2 기본 off 동작과 외곽 timeout 재전파
- `sandbox_probe` — sandbox 허용 API 실측(정보성)

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

- 2026-10-04 lab 실측: sandbox 는 `JsonSlurperClassic` 생성자 · `FlowNode.getId/getEnclosingBlocks/getEnclosingId` ·
  `FlowInterruptedException.getCauses/getResult` 를 거부한다. 따라서 Tier 2(회수·적재 상한)는 **승인된 Jenkins 에서 `BOUNDED=true` 일 때만** 켜지고,
  기본에서는 상한 없이 종전 동작이다. 사용자 취소(T5)는 Harness 로 자동화하지 않는다 — 실제 main Job 에서 확인한다.
- Harness 의 PASS 는 "함수가 Jenkins 에서 기대대로 동작했다" 이지, 실제 수집 Job(main/production) 의 E2E 나 고객사 실환경 검증이 아니다.
