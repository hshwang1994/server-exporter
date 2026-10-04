# JENKINS_PIPELINES — server-exporter

> Jenkins 파이프라인 카탈로그. rule 28 #4-5 측정 대상 (TTL 7-14일).
> 실측 2026-09-28 — 파이프라인은 `Jenkinsfile_portal` 하나다. 비운영 `Jenkinsfile`(pytest 회귀 게이트) ·
> `Jenkinsfile_portal_test` · `test_sj`(portal 사본)는 2026-09-28 에 삭제됐다 (사용자 결정).

## Stage 매트릭스 (실측 — `Jenkinsfile_portal`)

| Stage | 노드 | 하는 일 | FAIL 게이트 |
|---|---|---|---|
| Validate | 없음 (agent-less, 2026-10-03) | target_type / inventory_json(배열·객체 원소·IP 키) / callbackUrl / deploymentEnvironmentId 검증 → 접수 manifest `env.SE_MANIFEST_JSON` | YES |
| Resolve Location | 없음 (agent-less, 2026-10-03) | `readYaml text: readTrusted('common/vars/locations.yml')` → `SE_LOCATION` / `SE_AGENT_LABEL`. 미등록 `loc`·온라인 노드 없음 즉시 실패 | YES |
| Gather | `SE_AGENT_LABEL` (agent), stage 합산 상한 115 min | `gather_manifest.json` 기록 → (전역 `ADDON_REPO_URL` 이 있으면 Add-on 체크아웃 · 검사 — 아래 절) → venv 활성화 → `scripts/gather_budget.sh` 로 예산 **재계산**(ansible 직전) → `timeout --signal=INT --kill-after=90 <예산> ansible-playbook … -f <forks> --vault-password-file=<mktemp> -e se_location=<loc>` (Add-on 이 켜진 빌드만 `withEnv(ADDON_DIR)`; `redfishAccountDryrun` 이 켜진 빌드만 `-e _rf_account_service_dryrun=true`; `gatherBudgetForceSec` 는 공식 대체) → `gather_rc.txt` + outcome → post{always} Layer A(`scripts/finalize_gather_output.py`) → `archiveArtifacts`(output · manifest · rc · progress · checkpoint · final · report · auth_evidence/**) → `stash` → manifest 가 이 빌드 것일 때만 `deleteDir` | Add-on 을 못 받으면 UNSTABLE + Add-on 없이 수집; ansible rc 는 outcome 으로만 기록(stage 를 끊지 않음) |
| (pipeline post always) 마무리 | `built-in` (controller), `timeout(720 s){ node('built-in') }` | unstash → unarchive → `gather_final.jsonl` 우선 / Groovy 최소 보충(`readTrusted` → `load 'scripts/jenkins/se_finalize.groovy'`; 적재 실패면 raw OUTPUT 줄만 + `layerB=unavailable`) → 접수 = 결과 단언 → `httpRequest` POST(남은 예산 안 ≤3회) → `callback_body.json` · `finalize_summary.json` archive | NO (UNSTABLE: 전송 실패 · 합성 보충 · outcome ≠ completed · 라이브러리 부재) |

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

12 stage, dependency 순. 수집 · Callback · 대상 서버 접속 없음. 자격증명은 **Prodgen Verify**(`se-jenkins-lint` 린터 토큰 · `server-gather-vault-password`) · **Evidence Aggregate**(`se-jenkins-lint` 읽기) · **Prodgen Promote**(`hshwang token` GitHub · `se-gitlab-push` GitLab)에서만 바인딩한다(`tests/unit/test_jenkinsfile_ci.py` 가 stage 단위로 고정). 각 stage 는 `env.CI_STAGE_*` 에 PASS/PARTIAL/FAIL 을 남기고 post 가 `ci_stage_results.json` 으로 archive 한다 — Promote 는 이 값을 **읽어서** 판정한다(Gate 가 FAIL 이어도 뒤 stage 는 진단용으로 계속 돈다).

| Stage | 하는 일 | 실패 |
|---|---|---|
| Checkout | `checkout scm` → `env.MAIN_SHA = GIT_COMMIT` 고정(이후 stage 와 prodgen 입력 SHA) | FAILURE |
| Toolchain | venv(`scripts/activate_ansible_venv.sh`) · 도구 버전 보고 · `pwsh` 가 없으면 `scripts/ai/prodgen/ci_pwsh_bootstrap.sh` 가 사용자 권한으로 `$HOME/.local/powershell` 에 준비(시스템 변경 없음) | FAILURE |
| Gate | `bash scripts/ai/ci_gate.sh` | exit 1 FAILURE(후속 stage 계속) · exit 2 PARTIAL → UNSTABLE |
| Finalize Corpus | Python `tests/scripts/finalize_corpus_check.py` + Groovy `load 'scripts/jenkins/se_finalize.groovy'` 14 case 비교(`seCorpusCompare`) | FAILURE |
| Budget Self-test | `pytest tests/unit/test_gather_budget.py` + `scripts/gather_budget.sh` os/esxi/redfish `start:true` | FAILURE |
| Harness Driver | `build(job: 'clovirone-cicd/clovirone-server-gather-harness', wait: true, propagate: false)` 를 `HARNESS_SCENARIOS`(16) 순서대로(main checkout 의 함수) → `harness_main_results.json`. 기대 결과는 `scenarios.json` 의 `jenkins_result`(user_abort = ABORTED). 이어서 `HARNESS_BOUNDED_SCENARIOS`(Tier 2, BOUNDED=true) → `harness_bounded_results.json` · `HARNESS_BOUNDED`(승인 전 PARTIAL, 승격 조건 아님) | 시나리오 ≠ 기대 결과 → UNSTABLE |
| Prodgen Build | `prodgen build --sha MAIN_SHA` → `prodtree/` · `prodtree.tar.gz` · `prodtree_portal.sha256`(이 빌드의 artifact) | class B > 0 → FAILURE |
| Harness (prodtree) | Build PASS 뒤에만. Harness Job 을 `FUNCTIONS_SRC=artifact` + `ARTIFACT_BASE_URL=${BUILD_URL}artifact` + `EXPECTED_SHA256` 로 — 생성 tree 의 같은 함수를 같은 Harness 로(`HARNESS_TREE_SCENARIOS`) | UNSTABLE |
| Prodgen Drift | `git fetch origin +refs/heads/production:refs/remotes/origin/production` → `drift-check --production refs/remotes/origin/production [--bootstrap-baseline B]` | 승격 가능 상태 아님 → UNSTABLE |
| Prodgen Verify | Build PASS 뒤에만. `verify --tree prodtree --remote origin --netrc <mktemp 0600> --vault-password-file <mktemp 0600> --report-out prodgen_verify_report.json --source-build-url BUILD_URL` — credential 이 없으면 그 gate 없이 실행(PARTIAL). exit 0/2/1 | 2 → UNSTABLE · 1 → FAILURE |
| Evidence Aggregate | 이 빌드의 Harness 결과 + `E2E_MAIN_ENTRIES`(main Job 시나리오 빌드) → `prodgen e2e-evidence`(시나리오 계약으로 판정 — 파라미터·artifact·콘솔 표식 대조) → `evidence-aggregate`(입력 digest 검증) → `prodgen_verify_report.aggregated.json` | 미완료 → UNSTABLE |
| Prodgen Promote | `PROMOTE=true` 일 때만. 필수 stage 전부 PASS · 집계 보고서 존재 · SHA 4값 일치(`PROMOTE_SHA`·`MAIN_SHA`·HEAD·보고서 binding) · `verdict == COMPLETE_PASS` · GitLab credential 있을 때만 양 원격 실 승격(없으면 dry-run) → `prodgen promote` | 조건 미충족 → `error`, 원격 변경 0 |

- 파라미터: `PROMOTE`(false) · `PROMOTE_SHA` · `PROMOTE_DRY_RUN`(true) · `BOOTSTRAP_BASELINE`(빈 값) · `HARNESS_SCENARIOS`(12) · `HARNESS_TREE_SCENARIOS`(4) · `E2E_MAIN_ENTRIES`(`SCENARIO=job/path:build[:EXPECTED]`).
- 등록: 일반 Pipeline-from-SCM(Multibranch 아님), Branch `*/main`, Script Path `Jenkinsfile_ci`, Lightweight, 트리거 없음(수동). 정의 `jenkins/jobs/clovirone-server-gather-ci/config.xml`.
- `Jenkinsfile_portal` 과 공유하는 Layer B 함수 파일 `scripts/jenkins/se_finalize.groovy` 는 production 포함 대상, `Jenkinsfile_ci` · corpus · `scripts/ai/**` · `jenkins/**` · `tests/**` 는 제외.
- 실행 이력은 `docs/ai/catalogs/TEST_HISTORY.md` 와 `tests/evidence/` 에 둔다(이 표는 구조만).

## Harness Job `clovirone-cicd/clovirone-server-gather-harness` (2026-10-04, main 전용)

Script Path `tests/jenkins/harness/Jenkinsfile_harness`(scripted), Branch `*/main`. 시나리오당 빌드 1개(`SCENARIO`), `FUNCTIONS_SRC=checkout|artifact`. `Jenkinsfile_portal` 의 최상위 함수를 `tests/jenkins/harness/build_functions.py` 가 잘라 wrapper(`archiveArtifacts`·`stash`·`unstash`·`readTrusted`·`sh`·`httpRequest`…)를 덧붙인 임시 스크립트를 `load` 하고, `callback_sink.py`(POST sink — **controller(built-in) 의 127.0.0.1**, finalizer 의 `httpRequest` 가 `node('built-in')` 에서 나가므로; 파일은 형제 workspace `…@sink`) 를 향해 `sePreserveGatherOutput()` → `seFinalizeAndCallback()` 을 실제 CPS·sandbox 에서 실행한다. 판정 `harness_verdict.py` → `harness_result.json`(PASS/FAIL/PARTIAL). 운영 코드에는 장애 주입 분기가 없다. 시나리오 정의 `tests/jenkins/harness/scenarios.json`.

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
