# JENKINS_PIPELINES — server-exporter

> Jenkins 파이프라인 카탈로그. rule 28 #4-5 측정 대상 (TTL 7-14일).
> 실측 2026-09-28 — 파이프라인은 `Jenkinsfile_portal` 하나다. 비운영 `Jenkinsfile`(pytest 회귀 게이트) ·
> `Jenkinsfile_portal_test` · `test_sj`(portal 사본)는 2026-09-28 에 삭제됐다 (사용자 결정).
> 실측 2026-10-08 — main 에 `Jenkinsfile_portal_Byid` 가 있다. GitLab 관리자가 웹에서 올린 `Jenkinsfile_portal` 사본이다
> (`87c47f8d` · `09fb4890`, 병합 `2cd63067`, 줄끝 LF 정규화 `1566454a`). 원본과 차이는 `inventory_json` 의
> `defaultValue: '[{"bmc_ip":"","by_id":""}]'` 1줄, cron · trigger 없음, production 생성 대상 아님. 처리 미정 — CONVENTION_DRIFT DRIFT-019.
> 실측 2026-10-09 — 운영 로그 문구 정리(작업지시서 "로그 문구 개선"): `Jenkinsfile_portal` · `Jenkinsfile_portal_Byid`(차이 1줄 유지) ·
>   `Jenkinsfile_ci` · `scripts/run_gather.sh` · `scripts/ai/ci_gate.sh` 의 사람이 읽는 문장만 바꿨다. stage 이름 · 순서 · 개수, 판정 · 호출 순서,
>   `[Trusted] … len= jhash=` · `[기술 기록] 수집 시도 …` · `OUTPUT`/`CHECKPOINT`/`ADDON_*` 는 그대로다. 콘솔 문구를 읽는 곳(Harness `unstable_contains` ·
>   sh label `수집 결과 정리` · `scripts/ai/prodgen/evidence.py` 표식)은 같은 커밋에서 맞췄다 — 정본 `docs/reference/decision-log.md` 2026-10-09.

## Stage 매트릭스 (실측 — `Jenkinsfile_portal`)

| Stage | 노드 | 하는 일 | FAIL 게이트 |
|---|---|---|---|
| 입력 확인 (Validate) | 없음 (agent-less, 2026-10-03) | target_type / inventory_json(배열·객체 원소·IP 키) / callbackUrl / deploymentEnvironmentId 검증 → 접수 manifest `env.SE_MANIFEST_JSON` | YES |
| 실행 위치 확인 (Resolve Location) | 없음 (agent-less, 2026-10-03) | `readYaml text: seTrusted('common/vars/locations.yml')`(readTrusted + `[Trusted] … len · jhash` 식별 echo, 2026-10-04) → `SE_LOCATION` / `SE_AGENT_LABEL` → `seCheckRunners`(등록된 Runner 수, `nodesByLabel offline:true` — 2026-10-06 9차) | YES — 미등록 `loc` · 등록 Runner 0(`config_error`) 은 FAILURE, 접수 대상마다 실패 결과는 보낸다. 온라인 후보가 지금 없다는 이유로 건너뛰지 않는다(`no_agent` 삭제) |
| 서버 정보 수집 (Gather) | stage 에 agent · timeout 없음 — `seGatherStage(seConstants())` 가 시도마다 `seWithNode`(Jenkins queue · executor 미점유 · 빌드의 실행 기반 대기 합 72 h) → `node(라벨 → 수집 시작 뒤 그 Runner)` · `ws("<Job>-<번호>")` · `timeout(6 h + 90 s + 2 h)` | 첫 시도: `sePrepareWorkspace` — `checkout(scm)` · `.se_workspace.json`(받은 commit · `prepared:false`) · 지난 결과 정리 · `gather_manifest.json` · `prepared:true`(끊기면 다음 시도가 남은 준비만, 2026-10-07 10차) / 이어서: revision 대조 · 접수 목록 파일이 없으면 `SE_MANIFEST_JSON` 으로 복원 → `seAddonPrepare`(결정 `.se_addon.json` 재사용, 손상이면 `addon/` 사본 commit) → `bash scripts/run_gather.sh <playbook> <inventory> <loc> <addon> <GATHER_MAX> <이전 끊김>`(flock · `gather_state.py begin/end` · `--limit @.gather_limit_hosts` · 60 s 생존 표시) → `seClassifyAttempt`(`gather_state.py classify`) → 실행 기반 장애(`agent_disconnect` · `runner_oom`(커널 로그 PID 근거만, 10차) · `runner_restart` · `running`)면 `seSnapshotGatherOutput`(stash) 뒤 다시 시도, 끝이면 `sePreserveGatherOutput`(보관 또는 전달을 마치면 `SE_FINAL_PRESERVED` — 그 뒤 끊김은 다시 시도하지 않는다) | NO — outcome 기록(stage 를 끊지 않는다). `infra_wait_expired` · `resume_impossible`(확정 결과가 사라진 경우 포함, `run_gather.sh` rc 92) 은 UNSTABLE |
| 결과 확인 및 전송 (pipeline post always 안의 표시 단계) | `built-in` (controller) — `seFinalizeAndCallback` 반복: `seWithNode('built-in')`(실행 기반 대기 합 안, 취소된 빌드는 합 5분) → 노드를 얻은 뒤 `timeout(남은 결과 처리 합, 최대 1 h){ dir("fin-<번호>") }`. 실행 기반 오류면 같은 폴더로 다시 들어간다(2xx 받은 전송은 다시 보내지 않음, 2026-10-07 10차) | unstash → 파일별 unarchive → `gather_final.jsonl` 우선 / Groovy 최소 보충(`readTrusted` → `load 'scripts/jenkins/se_finalize.groovy'`, `infraReason` 포함) → 접수 수 == 결과 수 → Portal POST(≤3회 · 시도당 10분) → `callback_body.json` · `finalize_summary.json`(`infra` · `callback.receipt`) | NO (UNSTABLE) — 끝내 처리하지 못하면 보내지 못했을 때 FAILURE, 보냈지만 마무리만 못 했을 때 UNSTABLE(`finalize_incomplete`) |

> 2026-10-07 (10차): 결과 처리 재진입 · 결과 처리 시간 합 · 확인된 시각부터 세는 대기(`OFFLINE_GRACE` 삭제) · 기록 읽기 예외를 `retry(agent(), nonresumable())` 로 ·
> 끊긴 준비(`prepared`) · 접수 목록 복원 · 확정 결과 IP 대조 · 보존 표식 · OOM 은 커널 로그 PID 근거만. 정본
> `docs/ai/decisions/ADR-2026-10-07-finalize-reentry-and-oom-attribution.md` · `docs/operate/04-pipeline-runtime.md`.

> 2026-10-06 (9차): 빌드 12 h · 수집 단계 39,000 s · `scripts/gather_budget.sh` · 메모리 상한 · `no_agent` · `not_started_*` 삭제. 실행 기반 대기 합 72 h ·
> 실제 수집 누적 6 h(`scripts/gather_state.py`) · 같은 Runner · 같은 작업 폴더 재개(끝난 대상 · Precheck 실패 대상 제외). 정본
> `docs/ai/decisions/ADR-2026-10-06-infra-wait-and-host-resume.md` · `docs/operate/04-pipeline-runtime.md`.

> 2026-10-05 (8차): 시험용 파라미터(`redfishAccountDryrun` · `gatherBudgetForceSec`) 삭제, 시간 한계 셋(빌드 12 h · 수집 실행 최대 6 h · 결과 확인 및 전송 1 h),
> 작업 단위 제한 · 정체 감시(`gather_watch.py`) · Tier 2(`SE_FINALIZER_BOUNDED`) 삭제, 업무 줄 시각 · Timestamper(`timestamps {}` — 플러그인 없으면 생략),
> 작업 폴더 정리. 정본 `docs/operate/04-pipeline-runtime.md` · `tests/unit/test_time_limits.py`.
> 2026-10-07 (마무리): `buildDiscarder`(로그·빌드 기록 보관)는 Jenkinsfile(`_portal` · `_ci`)에서 제거 — 보관 정책은 Jenkins 전역 설정으로 관리한다. ansible.cfg `forks` 200 → 50. Portal 결과 전송은 확정 거부(4xx)도 재진입 재전송 금지 · 응답 확인 전 중단은 `receipt=uncertain`.

> 2026-10-05 (7차 F13): 단계 표시 이름을 한국어로(괄호 안이 종전 이름) — Stage View · Blue Ocean 에 '결과 확인 및 전송' 이 별도 단계로 보인다(post 안의 `stage`,
> 추가 executor 없음). sh 7개 모두 label, 콘솔 태그 `[입력 확인]` `[실행 위치]` `[수집]` `[시간]` `[결과 보존]` `[마무리]` `[Portal 전송]` `[결과]` `[경고]` `[결과 파일]` `[요약]`,
> 빌드 이름 `#N <종류> N대`(+시험 표시). Portal 전송은 2xx 수신까지가 계약(응답 본문 미판독). 정본 `tests/evidence/2026-10-05-final-maintenance.md` §9.

> 2026-10-03 (Phase 4): `Validate Schema`(FAIL 게이트) 와 `Callback` stage 삭제. field_dictionary 정합은 `scripts/ai/ci_gate.sh`(커밋 전 · CI)로,
> 결과 전달은 pipeline `post { always }` 로. 설계 정본은 Plan §6 과 `tests/unit/test_jenkinsfile_portal_finalize.py`.

> 종전 catalog 의 "Validate / Validate Schema = master" 표기는 코드와 달랐다. 실제 노드는 위와 같다
> (`Jenkinsfile_portal` 의 `agent { node { label "${env.SE_AGENT_LABEL}" } }`).

## Ansible 실행환경(venv) 선택 (2026-09-28)

Gather · Validate Schema 는 `. "${WORKSPACE}/scripts/activate_ansible_venv.sh" || exit 1` 한 줄로 venv 를 고른다.
순서: `SE_ANSIBLE_VENV`(노드 환경변수, 설정됐는데 틀리면 실패) → PATH 의 `ansible-playbook` 실경로 옆 `activate`
→ 알려진 경로 `/app/ansible-env` → `/opt/ansible-env` → 실패(시스템 python 으로 넘어가지 않음).
콘솔에 `[venv] <경로> python=<버전> (source=env|path|known)` 이 남는다. 실측: 설치 자동화 Runner 4대 = `/app`(path),
lab Agent 155 = `/opt`(known). 정본: `scripts/activate_ansible_venv.sh`, `tests/unit/test_activate_ansible_venv.py`.

## Add-on 빌드별 체크아웃 (2026-09-29)

켜기는 Jenkins 전역 환경변수 `ADDON_REPO_URL` 하나 (선택 `ADDON_REPO_REF`=main · `ADDON_REPO_CREDENTIALS_ID` · `ADDON_REPO_SSL_VERIFY`=false).
없으면 Gather 의 Add-on 블록은 통째로 실행되지 않아 결과가 도입 전과 같다. 있으면 Gather 가
`bash scripts/addon_checkout.sh <URL> <ref> ${WORKSPACE}/addon`(`git init` → `fetch --depth 1 <ref>` → 실패 시 전체 fetch 해석,
`retry(2)`, 검증 해제는 그 git 명령에만 `-c http.sslVerify=false`) → venv python 으로 `addon/tools/check_layout.py addon --targets
<서버 종류>`(os→`linux,windows` · esxi · redfish) → rc 0 이면 ansible `sh` 만 `withEnv(["ADDON_DIR=${WORKSPACE}/addon"])`,
rc 3 이면 켜지 않음(`[addon] 실행할 기능 없음`), 그 밖에는 `unstable("[addon] unavailable: …")` + Add-on 없이 수집.
ref 는 전역 `ADDON_REPO_REF`(없으면 `main`) 하나다 — 빌드마다 바꾸는 Job 파라미터는 없다. 정본: `docs/operate/04-pipeline-runtime.md` 3절,
`tests/unit/test_jenkinsfile_portal_addon.py`, `tests/unit/test_addon_checkout.py`. 노드 환경변수 · 배포 Job · `ADDON_HOME` 은 없다.

## CI 진입점 `Jenkinsfile_ci` (2026-10-04, main 전용 — Job `clovirone-cicd/clovirone-server-gather-ci` 등록됨)

12 stage — 2026-10-08 부터 확정 오류를 긴 Harness 전에 잡는 순서(생성 tree 를 쓰는 단계는 Build 뒤). 수집 · Callback · 대상 서버 접속 없음. 자격증명은 **Prodgen Verify**(`se-jenkins-lint` 린터 토큰 · `server-gather-vault-password`) · **Evidence Aggregate**(`se-jenkins-lint` 읽기) · **Prodgen Promote**(`hshwang token` GitHub · `se-gitlab-push` GitLab)에서만 바인딩한다(`tests/unit/test_jenkinsfile_ci.py` 가 stage 단위로 고정). 각 stage 는 `env.CI_STAGE_*` 에 PASS/PARTIAL/FAIL 을 남기고 post 가 `ci_stage_results.json` 으로 archive 한다 — Promote 는 이 값을 **읽어서** 판정한다(Gate 가 FAIL 이어도 뒤 stage 는 진단용으로 계속 돈다).

| Stage | 하는 일 | 실패 |
|---|---|---|
| Checkout | `checkout scm` → `env.MAIN_SHA = GIT_COMMIT` 고정(이후 stage 와 prodgen 입력 SHA) | FAILURE |
| Toolchain | 지난 빌드 산출물 정리(workspace 를 비우지 않는다 — 건너뛴 단계의 오래된 결과가 집계되지 않게, 2026-10-08) · venv(`scripts/activate_ansible_venv.sh`) · 도구 버전 보고 · `pwsh` 가 없으면 `scripts/ai/prodgen/ci_pwsh_bootstrap.sh` 가 사용자 권한으로 `$HOME/.local/powershell` 에 준비(시스템 변경 없음) | FAILURE |
| Gate | `CI_GATE_JUNIT_DIR=$WORKSPACE bash scripts/ai/ci_gate.sh` — pytest 실행 기록(JUnit `ci_gate_junit_{unit,integration}.xml`)을 남긴다(2026-10-08) | exit 1 FAILURE(짧은 후속 검사는 계속, Harness · Evidence 는 건너뜀) · exit 2 PARTIAL → UNSTABLE |
| Finalize Corpus | Python `tests/scripts/finalize_corpus_check.py` + Groovy `load 'scripts/jenkins/se_finalize.groovy'` 14 case 비교(`seCorpusCompare`) | FAILURE |
| Time Limits Self-test (stage 키 `BUDGET`) | 5개 시험 파일(`test_gather_state` · `test_run_gather` · `test_env_guard` · `test_time_limits` · `test_workspace_cleanup`)은 Gate 가 같은 SHA · 같은 Runner · 같은 venv 로 이미 실행한다 — 다시 돌리지 않고 `tests/scripts/junit_evidence_check.py` 가 Gate 의 JUnit 기록을 시험 ID 단위로 대조한다(지금 모이는 ID 가 전부 한 번씩 통과 · 기록이 이 빌드 시작 뒤 · 같은 host · HEAD == MAIN_SHA, 2026-10-08) + 이 Runner 로 대표 입력 3건의 시작 계산(`gather_state.py begin`, `budget_selftest.jsonl`) | 실패 · 누락 → FAILURE · 건너뜀 · 기록 없음 → PARTIAL(UNSTABLE) |
| Prodgen Build | `prodgen build --sha MAIN_SHA` → `prodtree/` · `prodtree.tar.gz` · `prodtree_portal.sha256` · `prodtree_archive.sha256` + `tree_hash`(이 빌드의 artifact — Harness 가 대조한다) | class B > 0 → FAILURE |
| Prodgen Drift | `git fetch origin +refs/heads/production:refs/remotes/origin/production` → `drift-check --production refs/remotes/origin/production [--bootstrap-baseline B]` | 승격 가능 상태 아님 → UNSTABLE (Harness 는 막지 않는다 — 원격 상태). Verify 의 G18/G20 이 읽는 로컬 production ref 를 만든다(그래서 Verify 앞) |
| Prodgen Verify | Build PASS 뒤에만. `verify --tree prodtree --remote origin --netrc <mktemp 0600> --vault-password-file <mktemp 0600> --report-out prodgen_verify_report.json --source-build-url BUILD_URL` — credential 이 없으면 그 gate 없이 실행(PARTIAL). exit 0/2/1 | 2 → UNSTABLE · 1 → FAILURE. 여기의 COMPLETE_PASS 는 생성물 gate 통과일 뿐(Harness · main E2E 증거는 Evidence · promote) |
| ── | GATE · CORPUS · BUDGET · PRODGEN_BUILD · PRODGEN_VERIFY 중 FAIL 이 있으면 아래 두 Harness 와 Evidence 는 `when` 으로 건너뛴다(`seFailedPrereqs`) — `ci_stage_results.json` 에 `SKIPPED` + `skipped_because`(PASS 아님 → promote 거부) | |
| Harness Driver | `seRunHarnessGroup('checkout', …)` — `HARNESS_SCENARIOS` 를 두 고정 lane(i % 2)이 나눠 동시에 부른다. 시나리오당 빌드 1개는 그대로: `build(job: harnessJob, wait: true, propagate: false, quietPeriod: 0, parameters: [SCENARIO, MAIN_SHA, FUNCTIONS_SRC, SINK_PORT=0])`. 결과는 parallel 반환값으로 모아 요청 순서로 정렬(`seMergeLanes` — 누락 · 중복 · 섞인 함수 해시는 문제). 판정 `seHarnessOk` = 기대 Jenkins 결과(scenarios.json `jenkins_result`) · 내부 verdict PASS · 결속(자식 빌드 변수 `SE_HARNESS_SHA` == MAIN_SHA · 함수 해시). 그룹마다 판정 · 집계 자체 시험표(`seHarnessJudgeSelfTest`)를 먼저 돈다 | 불통과 · 집계 문제 → UNSTABLE(stage FAIL) |
| Harness (prodtree) | Build PASS 뒤. 같은 방식으로 `FUNCTIONS_SRC=artifact` + `ARTIFACT_BASE_URL=${BUILD_URL}artifact` + `EXPECTED_SHA256` · `EXPECTED_ARCHIVE_SHA256` · `EXPECTED_TREE_HASH` (`HARNESS_TREE_SCENARIOS`). main 단계와 같은 판정 + 생성물 결속(Jenkinsfile_portal sha · 압축 파일 sha · tree_hash) — 종전의 Jenkins 결과만 보던 판정을 바꿨다(2026-10-08 C5) | 같음 |
| Evidence Aggregate | (선행 FAIL 이면 건너뜀) 이 빌드의 Harness 결과(결과 파일의 `harness_job` · 빌드 번호) + `E2E_MAIN_ENTRIES`(main Job 시나리오 빌드) [+ `E2E_TIP_OBSERVATIONS_JSON` → `--tip-observations`: fail-closed 빌드의 직접 revision 바인딩] → `prodgen e2e-evidence`(시나리오 계약으로 판정 — 파라미터·artifact·콘솔 표식 · `[Trusted]` 내용 대조; 이웃 빌드 추정은 `binding=estimated` 로 기록될 뿐 승격 증거로 인정되지 않는다) → `evidence-aggregate`(입력 digest 검증) → `prodgen_verify_report.aggregated.json` | 미완료 → UNSTABLE |
| Prodgen Promote | `PROMOTE=true` 일 때만. 필수 stage 전부 PASS · 집계 보고서 존재 · SHA 4값 일치(`PROMOTE_SHA`·`MAIN_SHA`·HEAD·보고서 binding) · `verdict == COMPLETE_PASS` · GitLab credential 있을 때만 양 원격 실 승격(없으면 dry-run) → `prodgen promote` | 조건 미충족 → `error`, 원격 변경 0 |

- 파라미터: `PROMOTE`(false) · `PROMOTE_SHA` · `PROMOTE_DRY_RUN`(true) · `BOOTSTRAP_BASELINE`(빈 값) · `HARNESS_SCENARIOS` · `HARNESS_TREE_SCENARIOS` · `HARNESS_JOB`(빈 값 = 공유 Harness Job, 시험용 CI 사본은 시험용 Harness Job — 공유 Job 을 부르지 않는다) · `E2E_MAIN_ENTRIES`(`SCENARIO=job/path:build[:EXPECTED]`) · `E2E_TIP_OBSERVATIONS_JSON`. 시나리오 목록의 정본은 `Jenkinsfile_ci` 기본값과 `scripts/ai/prodgen/evidence.py` 의 REQUIRED_* 집합(테스트가 둘을 맞춘다).
- 사내 Jenkins 전역 환경변수: `ADDON_REPO_URL`(Add-on 빌드별 체크아웃). `SE_FINALIZER_BOUNDED`(Tier 2)는 2026-10-05 8차에서 코드가 더 읽지 않는다 — 전역 설정에서도 지운다(실행 기록은 TEST_HISTORY).
- 등록: 일반 Pipeline-from-SCM(Multibranch 아님), Branch `*/main`, Script Path `Jenkinsfile_ci`, Lightweight, 트리거 없음(수동). 정의 `jenkins/jobs/clovirone-server-gather-ci/config.xml`.
- `Jenkinsfile_portal` 과 공유하는 Layer B 함수 파일 `scripts/jenkins/se_finalize.groovy` 는 production 포함 대상, `Jenkinsfile_ci` · corpus · `scripts/ai/**` · `jenkins/**` · `tests/**` 는 제외.
- 실행 이력은 `docs/ai/catalogs/TEST_HISTORY.md` 와 `tests/evidence/` 에 둔다(이 표는 구조만).

## Harness Job `clovirone-cicd/clovirone-server-gather-harness` (2026-10-04, main 전용)

Script Path `tests/jenkins/harness/Jenkinsfile_harness`(scripted), Branch `*/main`. 시나리오당 빌드 1개(`SCENARIO`), `FUNCTIONS_SRC=checkout|artifact`. `Jenkinsfile_portal` 의 최상위 함수를 `tests/jenkins/harness/build_functions.py` 가 잘라 wrapper(`archiveArtifacts`·`stash`·`unstash`·`readTrusted`·`sh`·`httpRequest`…)를 덧붙인 임시 스크립트를 `load` 하고, `callback_sink.py`(POST sink — **controller(built-in) 의 127.0.0.1**, finalizer 의 `httpRequest` 가 `node('built-in')` 에서 나가므로; 파일은 형제 workspace 아래 빌드 전용 `…@sink/<빌드 번호>`) 를 향해 `sePreserveGatherOutput()` → `seFinalizeAndCallback()` 을 실제 CPS·sandbox 에서 실행한다. 판정 `harness_verdict.py` → `harness_result.json`(PASS/FAIL/PARTIAL). 운영 코드에는 장애 주입 분기가 없다. 시나리오 정의 `tests/jenkins/harness/scenarios.json`.

2026-10-08: **동시 빌드 허용**(CI 의 두 lane) — `disableConcurrentBuilds` 없음. 수신기는 빌드마다 따로다: `SINK_PORT=0` 이면 OS 배정 포트(`callback_sink.py --ready-file` 이 실제 포트 · pid 를 알린다, 고정 sleep 없음), 남의 수신기 `pkill` 없음(고정 포트가 쓰이는 중이면 PARTIAL · Callback 은 닫힌 포트로), `finally` 에서 이 빌드의 수신기만(명령줄의 ready 경로 확인) TERM → 최대 10초 → 그 pid 만 KILL. 판정이 수신 기록의 eventUuid(`harness-<BUILD_TAG>`)를 본다(`sink_isolation`). `MAIN_SHA` 를 주면 그 commit 을 받고(비교 유지) readTrusted 3개 파일을 받은 소스에서 미리 읽으며(목록 밖 → `trusted_pinned` FAIL), Pipeline 정의(Job branch 끝, revision 미기록)는 후보 뒤 `Jenkinsfile_harness` 변경 commit 이 없는지 git 이력으로 확인한다. 부모 CI 에 빌드 변수 `SE_HARNESS_SHA` · `_FUNCTIONS_SHA256` · `_SOURCE_SHA256` · `_ARCHIVE_SHA256` · `_TREE_HASH` 를 남긴다. 수동 실행 `SINK_PORT` 기본값 18080(main E2E T2 · T5) 은 그대로.

## 진단 Job (2026-10-04 최종 실행 지시, main 전용 · 읽기 전용)

| Job | Script Path | 하는 일 |
|---|---|---|
| `clovirone-cicd/clovirone-server-gather-perf-observe` | `tests/jenkins/harness/Jenkinsfile_perf_observe` | `NODE_NAME` 노드에서 `perf_observe.py` 가 `/proc` 만 읽어 같은 Runner 의 Gather 빌드를 `SE_BUILD_ID` 로 귀속해 PSS(smaps_rollup) · RSS · 활성 worker 수 · 메인 프로세스 PSS · MemAvailable · swap · CPU 를 `INTERVAL_SEC` 마다 JSONL 로; `IDLE_EXIT_SEC` 뒤 자동 종료. 집계 `perf_observe_report.py` — forks 메모리 상수(`per_fork_mb` · `fixed_mb` · `node_share`) 의 실측 근거 |
| `clovirone-cicd/clovirone-server-gather-term-probe` | `tests/jenkins/harness/Jenkinsfile_term_probe` | `term_probe.sh`: 이 Runner 의 ansible-core · coreutils `timeout` 으로 ① 태스크 timeout 3 s(Add-on `apply.timeout` 장치) ② `timeout --signal=INT --kill-after` 배치 경로 ③ INT 무시 → kill-after(ansible · 대조 sleep)를 localhost 대상으로 실행하고 rc · 경과 · 자식 잔존 · 정리 결과를 남긴다(고유 marker 프로세스만 다룬다) + `tests/integration/test_addon_hook_playbook.py -v` |
| `clovirone-cicd/clovirone-server-gather-net-probe` | `tests/jenkins/harness/Jenkinsfile_net_probe` | `TARGETS`(ip[:port,…]) 마다 route · ICMP · 관리 TCP connect · ARP/neighbour(같은 L2 의 존재 근거) · tracepath · Redfish ServiceRoot 무인증 GET 상태코드 — Runner 망에서의 무응답 자산 진단. 설정 변경 · 인증 시도 없음 |

정의 `jenkins/jobs/<job>/config.xml`(2026-10-04 등록). 둘 다 `production_manifest.yml` forbidden(`tests/**` · `jenkins/**`) 이라 production 에 없다.

## pytest 회귀 게이트

Jenkins 수집 Job 의 단계가 아니다 (2026-09-28 부터; 2026-10-03 부터 field_dictionary 정합도). `bash scripts/ai/ci_gate.sh` 가
pytest(unit · e2e · regression · integration not live) · field_dictionary · drift · vendor boundary · harness consistency · syntax-check 를
한 번에 돌린다. 수집 Job 의 FAIL 게이트는 입력 검증(Validate · Resolve Location)뿐이고 수집 이후는 결과 전달로 수렴한다.

## vault binding (cycle-012 / 2026-06-18 갱신)

Jenkins credential `server-gather-vault-password` (type: **Secret text**). `withCredentials` 가 `$VAULT_PASSWORD` 를
주입(콘솔 마스킹), Pipeline 이 런타임 임시파일(mktemp, chmod 600)에 써서 `--vault-password-file` 로 ansible-playbook 에
넘기고 `trap` 으로 삭제.

| 항목 | 값 |
|---|---|
| credential ID | `server-gather-vault-password` |
| credential type | Secret text |
| 패턴 | `withCredentials([string(credentialsId: 'server-gather-vault-password', variable: 'VAULT_PASSWORD')]) { ... }` |
| ansible-playbook 인자 | `--vault-password-file=<임시파일>` |
| 적용 stage | Gather |

**참조**: `docs/operate/01-jenkins-master.md` (credential 등록 절차).

## Job 등록 실측 (2026-09-28)

| Jenkins | Job | Script Path | 브랜치 | Agent |
|---|---|---|---|---|
| lab 10.100.64.153 | `clovirone-server-gather` | `Jenkinsfile_portal` | `*/production` | `jenkins-agent-dev` = 10.100.64.155 (`/opt/ansible-env`, 라벨 yi/git/chj/ic/linux/windows) |
| 신규 jenkins-prod.gooddi.lab | `clovirone-cicd/clovirone-server-gather` | `Jenkinsfile_portal` | `production` (사용자 전환) | `SKHynix-Jenkins-Runner01~04` = 10.100.64.33~36 (`/app/ansible-env`, 라벨 git/linux/redfish/windows — `ic/chj/yi` 노드 없음, git 2.47.3 은 2026-09-28 설치됨, 시스템 CA 가 내부 GitLab 자체 서명 인증서를 모름 → Add-on 은 기본값(검증 안 함)으로 받는다) |

`main` 은 tests/reference 를 포함해 약 17k 파일이라 컨트롤러의 Resolve Location(2분 제한)이 체크아웃 도중 끊겼다
(신규 Jenkins 빌드 #4, `clovirone-server-gather-main` #1 @ a45ba808 도 같은 원인으로 ABORTED). 2026-10-03 부터 Resolve Location 은
`readTrusted` 로 파일 하나만 읽어 체크아웃 자체를 하지 않는다 — main Job 에서의 실제 확인은 다음 빌드에서(미확인이면 미확인으로 적는다).
2026-10-03 노드 실측(jenkins-prod): Runner01~03 라벨 `git linux redfish windows`(15 executor), Runner04 는 `git` 만, **`esxi` 라벨 노드 없음**
→ `target_type=esxi` 는 Resolve Location 에서 끝난다(환경 항목). 플러그인: workflow-basic-steps(`unarchive`), workflow-multibranch(`readTrusted`),
pipeline-utility-steps, http_request; artifact manager 는 기본 파일시스템.

## cron 인벤토리 (rule 28 #5)

`Jenkinsfile_portal` 에 `triggers` 블록 없음 (cron 0건). 변경 시 사용자 명시 승인 (rule 80 + 92 R5).

## callback URL (rule 31)

Callback stage 가 호출자에게 결과 통지:
- 전송: HTTP Request 플러그인 `httpRequest()` 스텝 (curl/셸 미사용). `validResponseCodes:'100:599'` 로 비-2xx 에도 예외 미발생 → status 직접 판정 (graceful, rule 31 R2). `ignoreSslErrors` 미설정 → SSL 검증 유지.
- 정규화: 후행 `/` 제거 후 `/api/jenkins/gather/<target_type>` 부착
- Method: POST (`Content-Type: application/json`)
- Body: `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson:[...]}` — gatherInfoJson 은 `callback_plugins/json_only.py` envelope (rule 20) 라인 배열
- 재시도: 3회 + backoff(attempt*10s), 최종 실패 시 unstable (빌드 fail 아님 — rule 31 R2)

## 갱신 trigger (rule 28 #4 / #5)

- TTL 7-14일
- `Jenkinsfile_portal` 수정
- cron 표현식 변경 (사용자 명시 승인 필수)
- 새 Jenkinsfile 추가

## 측정 명령

```bash
grep -nE "stage\s*\(|label" Jenkinsfile_portal
grep -nE "triggers|cron" Jenkinsfile_portal
grep -n "activate_ansible_venv" Jenkinsfile_portal jenkins/jobs/*/config.xml scripts/*.sh
```

## 정본 reference

- `Jenkinsfile_portal` (정본), `scripts/activate_ansible_venv.sh`
- `docs/operate/01-jenkins-master.md`, `docs/operate/03-job-registration.md`, `docs/operate/04-pipeline-runtime.md`
- `.claude/ai-context/infra/convention.md`
- `docs/ai/references/jenkins/pipeline-syntax.md`

## 후속 작업 (사용자 결정)

- [x] rule 80 R1-A에 pipeline별 Stage 4 차이 명시 (cycle-006) — 2026-09-28 단일 파이프라인으로 재정리
- [x] vault encrypt + credential `server-gather-vault-password` 등록 (cycle-012)
- [x] grafana 파이프라인 제거 (cycle-015)
- [x] venv 경로 하드코딩 제거 (2026-09-28)
- [ ] 신규 Jenkins Runner 에 `git` (설치 자동화 I-2) 뒤 `clovirone-cicd/clovirone-server-gather` 1회 실행 확인
- [ ] OPS-1 빌드 시범 1회 후 envelope `meta.auth.fallback_used` 값 추가 검증
