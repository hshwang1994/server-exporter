# 2026-10-09 — 운영 로그 문구 정리 실측 · production 승격

> 결정: `docs/reference/decision-log.md` 2026-10-09 · `docs/ai/decisions/ADR-2026-10-05-time-limits-and-test-inputs.md` 보완 문단.
> 대상 Job: `clovirone-cicd/clovirone-server-gather-main` · `…-ci` · `…-harness` · production `…-gather`.
> 비밀값(Jenkins 계정 · vault 암호 · cookie)은 이 문서와 증거 폴더에 없다. 원본 증거는 저장소 밖 `C:\github\ClovirONE\evidence-log-wording-2026-10-09`.

## 1. 목적과 범위

- 사용자 작업지시서 "ClovirONE Gathering 로그 문구 개선 작업지시서"(2026-10-08 작성 · 2026-10-09 문안 보완)와 같은 날 검토 보정:
  운영자가 읽는 Jenkins 콘솔 · 수집 스크립트 · CI 안내를 한국어 업무 문장으로 바꾸고, 반복 · 설계 설명 · 내부 코드값 나열을 없앤다.
  유일한 진단 근거(revision · 경로 · 원본 오류)는 남긴다.
- 바꾸지 않은 것: stage 이름 · 순서 · 개수, 분기 · 판정 · 종료 코드 · timeout · retry · 대기와 재개, `unstable` · `error` 조건, 실행 동작의 호출 순서,
  JSON 구조 · 필드 · 코드값, `OUTPUT` · `CHECKPOINT` · `ADDON_START` · `ADDON_DONE`, `precheck |` task, `[Trusted] <path> len= jhash=`, `[기술 기록] 수집 시도 …`,
  `callback_plugins/json_only.py`(보호 경로).

## 2. 커밋 (main)

| 커밋 | 내용 |
|---|---|
| `1d8bc4c3` | Portal 화면 문구 2건 — `infra_unavailable` 띄어쓰기(카탈로그 · `se_finalize.groovy` · corpus 정답 19 · 20), Redfish 표준 계정 Vault 없음 문장 |
| `b2ad4aa6` | os 수집 include 블록 이름 15개(`사전 점검: 관리 포트 연결 확인` · `Linux: 메모리 정보 수집` 등) |
| `57ecdd14` | `run_gather.sh` · `workspace_cleanup.py` · `finalize_gather_output.py` 문구 |
| `7d915a37` | `Jenkinsfile_portal` 문구 + 문구를 읽는 곳(Harness needle · sh label · `evidence.py` 표식 추가 · 단위 시험) |
| `11907cb6` | `Jenkinsfile_portal_Byid` 를 portal 과 맞춤(차이 1줄 유지) |
| `afaf9e43` | `Jenkinsfile_ci` · `scripts/ai/ci_gate.sh` 문구 |
| `a9e26059` | 운영 문서 인용 · decision-log |
| `56160f33` | 콘솔 확인(#354) 뒤 — 작업 폴더 정리 건너뜀 문장 |
| `2c6d71f3` | 콘솔 확인(#356 · #367) 뒤 — 수집을 시작하지 않은 빌드의 회수 실패 원본 6줄 → 한 줄, `[수집 종료]` 머리 문장 (Byid 동시) |

## 3. 로컬 검증

| 구분 | 결과 |
|---|---|
| WSL `ci_gate`(LF clone `a9e26059`) | PASS — unit · e2e · regression 4,535 통과 · 145 건너뜀 · 7 xfail · integration 324 통과 · 3채널 syntax-check · corpus 20/20 |
| 문구를 읽는 시험(Windows, `7d915a37`) | 568 통과 · 5 건너뜀 (portal 4종 · Harness 도구 · prodgen · 입력 접수 · 시간 한계 · 작업 폴더 정리 · corpus 등 17파일) |
| 뒤 수정 시험 | `56160f33` 작업 폴더 정리 9 통과(WSL) · `2c6d71f3` portal 시험 99 통과 · 2 건너뜀 · CI 시험 41 통과 |
| Groovy 2.4.21 CONVERSION | `Jenkinsfile_portal` · `_Byid` · `_ci` · `se_finalize.groovy` OK |
| 표시 함수 실행 | `@NonCPS` 표시 함수 · `seExplainGatherEnd` · CI 안내 식을 Groovy 2.4 로 실행해 §6 문안과 대조(요약 · 전송 · 대기 · 보존 · 수집 종료) |
| prodgen build/verify(`a9e26059`, 이 PC) | 195 파일 · class B 0 · G01~G12 · G14~G17 PASS(G14 pytest 4,344 통과, `portal_contract` 43) — G13 · G18~G20 은 CI 에서 |

## 4. main Job 매트릭스 (같은 입력 — 10차 #327~#339 · 11차 #346~#353 의 파라미터)

1차(`56160f33`, #355~#367)에서 콘솔을 읽어 고칠 곳 2개를 찾았고(§2 `2c6d71f3`), 최종 SHA 에서 다시 돌렸다.

| 시나리오 | 빌드(`2c6d71f3`) | 결과 | outcome · 결과 · 전송 |
|---|---|---|---|
| T2 TEST-NET 2 → 수신기 | #368 | SUCCESS | completed · 실패 2 · HTTP 200 |
| T17 `loc=ic`(등록 Runner 0) | #369 | FAILURE | config_error · 실패 2(새로 만듦) · HTTP 200 |
| T5 TEST-NET 4 → 수신기, 수집 시작 뒤 취소 | #370 | ABORTED | aborted · 실패 4(새로 만듦) · HTTP 200 |
| T6 TEST-NET 2 → 닫힌 포트 | #371 | UNSTABLE | completed · 실패 2 · 408 × 3 · receipt uncertain |
| S1 `.161~.163 .120` | #372 | SUCCESS | 성공 4 · HTTP 200 |
| S2 S1 + TEST-NET 2 | #373 | SUCCESS | 성공 4 · 실패 2 · HTTP 200 |
| S3 실호스트 13 | #374 | SUCCESS | 성공 13 · HTTP 200 |
| S4 Windows `.120` | #375 | SUCCESS | 성공 1 · HTTP 200 |
| S5 Kernel 6.x `.37 .38` | #376 | SUCCESS | 성공 2 · HTTP 200 |
| E2E-A `loc=cj` | #377 | UNSTABLE | 실패 2 · 408 × 3(의도) |
| E2E-D ESXi 6 | #378 | SUCCESS | 성공 6 · HTTP 200 |
| E2E-E Redfish 2 | #379 | SUCCESS | 성공 2 · HTTP 200 |
| E2E-A2 `loc=chj`(미등록) | #380 | FAILURE | interrupted_unknown · 실패 2(새로 만듦) · 408 × 3 · tip 전후 `2c6d71f3` |

- 수신기: T2 · T5 · T17 은 Harness `sink_hold` 의 127.0.0.1:18080. 최종 회차의 새 수신기 #1032 는 앞 회차 #1031 이 아직 포트를 쥐고 있어 뜨지 못했고,
  세 빌드의 POST 는 #1031 수신기가 HTTP 200 으로 받았다(#1031 유지 시간 안). 판정은 각 빌드의 `finalize_summary.callback` 으로 한다.
- Harness `sink_close` #1033(`2c6d71f3`, 기본 목록 밖이라 따로 1회): PASS 7/7 — 바뀐 표식 `Portal 전송을 확인하지 못했습니다` 로 판정.
- 계약 판정(`prodgen e2e-evidence`, 이 PC에서 읽기 전용): 12 시나리오 모두 `pass` · revision 결속 `direct`(E2E-A2 는 tip 관측).

## 5. 변경 전후 대조 (같은 입력 13쌍)

`callback_body.json` 을 대상별로 비교: IP 집합 · `status` · `sections` · `failure_stage` · `failure_code` · `failure_reason` · `auth_success` · `errors[]`(section · code · message) ·
`vendor` · 수집 데이터 키 구조. T2 #346→#368 · T17 #329→#369 · T5 #347→#370 · T6 #348→#371 · S1 #349→#372 · S2 #350→#373 · S3 #353→#374 · S4 #333→#375 ·
S5 #331→#376 · E2E-A #351→#377 · E2E-D #337→#378 · E2E-E #338→#379 · E2E-A2 #352→#380 — **차이 0건**. outcome · warnings 코드 · 시도 수 · 수신 상태도 같다.
수집 값 자체(가용 메모리 · 가동 시간 등)는 실서버라 비교하지 않았다.

## 6. 대표 문장 전후

정상(production #191 → main #372):

```text
전  [수집] 시작합니다. 대상 3대(접수 3대), 동시 실행 3대, 이번 실행 한계 6시간(21600초).
전  [Portal 전송] 결과를 http://…/api/jenkins/gather/os 로 보냅니다. 최대 3번 시도합니다. 본문 25312자.
전  [Portal 전송] HTTP 200 응답을 받았습니다. 소요 시간: 0.3초. 2xx 는 Portal 이 요청을 받았다는 뜻입니다.
전  [요약] 실행 기반 대기 0초(2구간), 실제 수집 25초(시도 1번). 기다린 시간은 수집 실행 한계에 넣지 않습니다.  (요약 7줄)

후  [수집] OS 서버 4대의 정보 수집을 시작합니다.
      Runner: SKHynix-Jenkins-Runner03
      동시 수집: 4대
후  [Portal 전송] 1번째 전송을 시작합니다.
      주소: http://10.100.64.151:8080/api/jenkins/gather/os
후  [Portal 전송] HTTP 200 응답을 받았습니다. 소요 시간 0.2초.
후  [요약] 정상 종료 (SUCCESS)
      대상: OS 4대, 실행 위치 git
      수집 결과: 성공 4대, 부분 성공 0대, 실패 0대
      소요 시간: 전체 2분 46초, 수집 1분 52초, 실행 대기 1초
      Portal 전송: HTTP 200, 응답 시각 2026-10-09 02:44:35 +09:00
```

전송 실패(#348 → #371): `1번째 전송이 실패했습니다. HTTP 408. 연결하지 못했거나 응답 시간이 지났습니다(요청 도구는 연결 실패도 408 로 표시합니다).` →
`1번째 전송에 실패했습니다.` + `  연결하지 못했거나 응답을 받지 못했습니다.` + `  전송 도구 상태: 408` + `  소요 시간: 0.3초`. 마지막
`전달하지 못했습니다. 시도 3번, 마지막 상태 408.` → `전송을 확인하지 못했습니다. 총 3번 시도했습니다.` + `  마지막 전송 도구 상태: 408`(응답 전에 끊겨 수신 여부를 모른다).
요약 `확인할 것: callback_failed` · `위의 [경고] 줄과 [결과 파일] 링크를 보세요.` → `Portal 전송: 확인하지 못함`.

취소(#347 → #370): `중단됨: 사용자 취소입니다. 확보한 결과를 보존하고 전송으로 넘어갑니다. (outcome=aborted)` → `중단됨: 사용자가 빌드를 취소했습니다.` +
`  지금까지 확보한 결과를 저장하고 Portal 전송을 시도합니다.`. `[경고]` 2줄과 `확인할 것: filled, outcome_aborted` → 요약의 `미완료: 사용자 취소로 4대의 수집을 마치지 못했습니다.`

잘못된 위치(#352 → #380): 회수 실패 원본 6줄 → `[결과 확인] 수집을 시작하지 않아 수집 결과 파일이 없습니다.`,
`실제 수집 수집을 시작하지 않았습니다` → `수집 시간: 수집을 시작하지 않았습니다.`,
`허용: [cj, git, ic, yi]. 새 Location 은 …` → `등록되지 않은 Location: 'chj'.` + `  사용할 수 있는 값: cj, git, ic, yi` + `  loc 값을 확인하세요.`

CI(#36 → #37): `[Prodgen Verify] gate COMPLETE_PASS — 생성물 gate 통과일 뿐이다. Harness · main E2E 증거는 아직 없다(…)` →
`[Prodgen Verify] COMPLETE_PASS: production 파일 검사를 통과했습니다.` + `  다음 검사: Jenkins 파이프라인 시험(Harness)`(선행 실패가 없을 때만).
`[Post] 결과: SUCCESS MAIN_SHA=… 소요: 46 min and counting` → `[Post] 결과: SUCCESS, MAIN_SHA=…, 소요 시간 47분 58초`.

## 7. CI #37 (`2c6d71f3`, `PROMOTE=true` · `PROMOTE_DRY_RUN=true`, 47분 58초 SUCCESS)

- 단계: GATE · CORPUS · BUDGET · HARNESS_MAIN · PRODGEN_BUILD · HARNESS_TREE · PRODGEN_DRIFT · PRODGEN_VERIFY · VAULT_DECRYPT · EVIDENCE 모두 PASS, PROMOTE `DRY_RUN`.
- Harness main 45/45 · 생성 tree 21/21(verdict PASS · binding ok) · Corpus 20/20 · 입력 접수 35 × 3 · JUnit 대조 105 · Build 195 파일 tree `cc5d8df5…` ·
  Verify COMPLETE_PASS(전체 실행) · Evidence(Harness 66 + main 12).
- Promote: `[Promote] GitLab push 자격증명(se-gitlab-push)이 없어 실제 승격 없이 dry-run으로 진행합니다.` — Jenkins 에 GitLab push 자격증명이 없어 CI 로는
  실제 승격을 할 수 없다. 실제 승격은 P8 과 같은 세션 CLI 로 했다(§8).

## 8. production 승격 (P9)

| 항목 | 값 |
|---|---|
| 방식 | 세션 CLI(main 작업 사본, Windows): dry-run(`--dry-run --skip-live`, push 없음) → 실제 `promote --sha 2c6d71f3 --verify-report <CI #37 집계> --e2e-evidence <CI #37> --ci-stage-results <CI #37> --ci-build #37 --netrc <세션 파일> --vault-password-file <임시 사본> --push-remote origin,internal`(2026-10-09 09:50~10:05). vault 암호는 이 PC 에 있던 파일을 프로젝트 검사 도구(`vault_decrypt_check.py`, 평문 · username 미출력)로 확인한 뒤 임시 사본으로 넘기고 승격 직후 지웠다 |
| dry-run | 배포 정책 · CI 단계 · E2E 문제 0 · 생성 tree 195 파일 · class B 0 · parent P8 · production 상태 PROVENANCE · 실행 환경이 CI 와 달라(Windows/WSL · Python 3.13 · ansible-core 2.20.7) G11~G15 · G19 재실행 예정 |
| 결과 | **P9 `c69a0d33`** — parent P8 `347ab74e` · `Main-SHA: 2c6d71f3` · `Tree-Hash: cc5d8df5…` · 196 파일(runtime 195 + provenance) · `CI-Build` #37 · `CI-Stages: verified` · Verdict COMPLETE_PASS |
| 게이트 | G01~G20 전부 PASS. 이 PC 에서 다시 실행: G11~G15 · G18~G20. CI #37 결과 재사용: G01~G10 · G16 · G17 |
| 원격 | origin "accepted by remote" · internal 은 origin 의 공유 push 주소로 이미 도달 · 로컬 ref 갱신. 사후 `ls-remote` origin · internal · 로컬 · `origin/production` 모두 `c69a0d33` · drift-check PROVENANCE |

## 9. canary (production Job `clovirone-cicd/clovirone-server-gather`, `*/production`)

| 항목 | 값 |
|---|---|
| 빌드 | **#194 SUCCESS**(2026-10-09 10:07:19, 58초) · 파라미터 7개(시험용 없음) |
| 입력 | #191(P8 canary)과 같다 — loc `git` · os `.161 .162 .163` · deploymentEnvironmentId 1 · Portal `http://10.100.64.151:8080` |
| checkout | `c69a0d33` = P9 (`[수집] 저장소를 준비했습니다. revision c69a0d33…`) |
| 결과 | 접수 3 = 결과 3 · 성공 3 · Portal 1번째 전송 HTTP 200(0.2초) · 수집 26초 · 전체 55초 · 실행 대기 0초 |
| 대조 | #191 과 대상별 차이 0건(§5 와 같은 항목) |
| 콘솔 | 처음부터 끝까지 읽었다 — 입력 확인 · 실행 위치 · 수집 시작/끝 · 결과 보존 · 결과 확인 · 전송 · `[결과]` · 결과 파일 3개 · `[요약]` 이 §6.3 문안과 같은 배치 |

## 10. 남은 것 · 한계

- `[json_only] NOTICE: inventory 와 접수 manifest 가 다르다 …` — OS 정상 배치(S1 · S2)에서도 play 마다 나온다. `callback_plugins/json_only.py` 는 보호 경로라
  이번에 바꾸지 않았다(NEXT_ACTIONS — 승인 필요).
- esxi · redfish 빌드의 `[addon] 검사 통과: … 실행할 기능이 없습니다` 는 Add-on 저장소 출력이라 범위 밖이다. `[venv] …` 기술 줄은 sh 단계마다 1줄씩 2번 나온다(그대로 둠).
- `[수집] 수집 실행을 마쳤습니다. 소요 시간` 은 ansible 실행 시간, `[요약]` 의 수집 시간은 실행 기록(`exec_used`)이라 1초 차이가 날 수 있다(종전과 같은 측정).
- 실장비 OOM · 72시간 대기 · 결과 처리 노드 장애는 Harness 와 단위 시험으로만 확인했다(지시서 §8 — 새로 재현하지 않음).
- `Jenkinsfile_portal_Byid` 처리 결정(DRIFT-019)은 여전히 열려 있다.
