# JENKINS_PIPELINES — server-exporter

> Jenkins 파이프라인 카탈로그. rule 28 #4-5 측정 대상 (TTL 7-14일).
> 실측 2026-09-28 — 파이프라인은 `Jenkinsfile_portal` 하나다. 비운영 `Jenkinsfile`(pytest 회귀 게이트) ·
> `Jenkinsfile_portal_test` · `test_sj`(portal 사본)는 2026-09-28 에 삭제됐다 (사용자 결정).

## Stage 매트릭스 (실측 — `Jenkinsfile_portal`)

| Stage | 노드 | 하는 일 | FAIL 게이트 |
|---|---|---|---|
| Resolve Location | `built-in` (controller) | `readYaml common/vars/locations.yml` → `SE_LOCATION` / `SE_AGENT_LABEL`. 미등록 `loc` 즉시 실패 | YES |
| Validate | `SE_AGENT_LABEL` (agent, `skipDefaultCheckout`) | target_type / inventory_json / callbackUrl / deploymentEnvironmentId 검증 | YES |
| Gather | `SE_AGENT_LABEL` (agent) | (전역 `SE_ADDON_REPO` 가 있으면 Add-on 체크아웃 · 검사 — 아래 절) → venv 활성화 → `ansible-playbook … --vault-password-file=<mktemp> -e se_location=<loc>` (Add-on 이 켜진 빌드만 `withEnv(SE_ADDON_DIR)`) → `gather_output.json` stash | Add-on 을 못 받으면 UNSTABLE + Add-on 없이 수집, ansible 실패 UNSTABLE, 출력 0바이트 FAILURE |
| Validate Schema | `SE_AGENT_LABEL` (agent) | venv 활성화 → `python3 tests/validate_field_dictionary.py` | YES |
| Callback | `built-in` (controller) | unstash → `httpRequest` POST 3회 재시도 | NO (UNSTABLE) |

> 종전 catalog 의 "Validate / Validate Schema = master" 표기는 코드와 달랐다. 실제 노드는 위와 같다
> (`Jenkinsfile_portal` 의 `agent { node { label "${env.SE_AGENT_LABEL}" } }`).

## Ansible 실행환경(venv) 선택 (2026-09-28)

Gather · Validate Schema 는 `. "${WORKSPACE}/scripts/activate_ansible_venv.sh" || exit 1` 한 줄로 venv 를 고른다.
순서: `SE_ANSIBLE_VENV`(노드 환경변수, 설정됐는데 틀리면 실패) → PATH 의 `ansible-playbook` 실경로 옆 `activate`
→ 알려진 경로 `/app/ansible-env` → `/opt/ansible-env` → 실패(시스템 python 으로 넘어가지 않음).
콘솔에 `[venv] <경로> python=<버전> (source=env|path|known)` 이 남는다. 실측: 설치 자동화 Runner 4대 = `/app`(path),
lab Agent 155 = `/opt`(known). 정본: `scripts/activate_ansible_venv.sh`, `tests/unit/test_activate_ansible_venv.py`.

## Add-on 빌드별 체크아웃 (2026-09-29)

켜기는 Jenkins 전역 환경변수 `SE_ADDON_REPO` 하나 (선택 `SE_ADDON_REF`=main · `SE_ADDON_CREDENTIALS_ID` · `SE_ADDON_SSL_VERIFY`=false).
없으면 Gather 의 Add-on 블록은 통째로 실행되지 않아 결과가 도입 전과 같다. 있으면 Gather 가
`bash scripts/addon_checkout.sh <URL> <ref> ${WORKSPACE}/addon`(`git init` → `fetch --depth 1 <ref>` → 실패 시 전체 fetch 해석,
`retry(2)`, 검증 해제는 그 git 명령에만 `-c http.sslVerify=false`) → venv python 으로 `addon/tools/check_layout.py addon --targets
<서버 종류>`(os→`linux,windows` · esxi · redfish) → rc 0 이면 ansible `sh` 만 `withEnv(["SE_ADDON_DIR=${WORKSPACE}/addon"])`,
rc 3 이면 켜지 않음(`[addon] 실행할 기능 없음`), 그 밖에는 `unstable("[addon] unavailable: …")` + Add-on 없이 수집.
Job 파라미터 `addonRef`(선택)는 빌드 한정 ref override. 정본: `docs/operate/04-pipeline-runtime.md` 3절,
`tests/unit/test_jenkinsfile_portal_addon.py`, `tests/unit/test_addon_checkout.py`. 노드 환경변수 · 배포 Job · `ADDON_HOME` 은 없다.

## pytest 회귀 게이트

Jenkins 단계가 아니다 (2026-09-28 부터). `pytest tests/e2e`, `pytest tests/integration -m "not live"`,
`pytest tests/regression` 은 커밋 전 로컬 검증. Jenkins 의 FAIL 게이트는 Validate Schema 뿐이다.

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
(신규 Jenkins 빌드 #4) — Job 은 `production` 을 본다.

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
