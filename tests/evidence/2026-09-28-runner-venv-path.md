# 2026-09-28 — Agent venv 경로 분리 실측 (`scripts/activate_ansible_venv.sh`)

> 결정: `docs/reference/decision-log.md` 2026-09-28. 코드: `8170ae7d`(feat) · `da91b274`(docs) · production `e7baaa55`.
> 목적: 신규 Jenkins Runner(`/app/ansible-env`)와 lab Agent(`/opt/ansible-env`)에서 같은 파이프라인이 venv 를 찾는지,
> 못 찾을 때 시스템 python 으로 넘어가지 않는지 확인.

## 1. 대상 환경 (읽기 전용 실측)

| 호스트 | 역할 | OS | venv | PATH 의 ansible-playbook | git | Agent 계정 |
|---|---|---|---|---|---|---|
| 10.100.64.33~36 (`SKHynix-Jenkins-Runner01~04`) | 신규 Jenkins(jenkins-prod.gooddi.lab) Runner | RHEL 9.6 | `/app/ansible-env` (Python 3.12.9, ansible-core 2.20.3) | `/usr/local/bin/ansible-playbook → /app/ansible-env/bin/ansible-playbook` (설치 자동화 링크) | 없음 | `jenkins`, `/app/jenkins-agent/agent` |
| 10.100.64.155 (`jenkins-agent-dev`) | lab Jenkins 10.100.64.153 Agent | Ubuntu 24.04 | `/opt/ansible-env` (Python 3.12.3, ansible-core 2.20.3) | 로그인 셸 PATH 에는 없음, Jenkins 빌드 PATH 에는 있음(아래 4절 `source=path`) | 2.43.0 | `cloviradmin`, `/home/cloviradmin/jenkins-agent` |
| 10.100.64.154 (`jenkins-agent-ops`) | (Job 미연결) | Ubuntu 24.04 | `/opt`·`/app` 모두 없음 | — | 2.43.0 | — |

신규 Jenkins 노드 설정(admin API 실측): Tool Location `ansible=/app/ansible-env/bin`, 노드 환경변수 없음, 라벨 `git,linux,redfish,windows`(Runner04 는 `git` 만).
lab Jenkins 노드 설정: Tool Location `ansible=/opt/ansible-env/bin`, 노드 환경변수 없음, 라벨 `yi,git,chj,linux,ic,windows`.

## 2. 헬퍼 단독 실행 (stdin 으로 `bash -s`, 원격에 파일 없음)

명령: `env -i PATH=<Agent 계정 PATH> HOME=$HOME bash -s < (헬퍼 본문 + 확인 명령)`

| 호스트 | 결과 | python3 | ansible-playbook | ansible-vault | PyYAML |
|---|---|---|---|---|---|
| 33 / 34 / 35 / 36 | `[venv] /app/ansible-env python=Python 3.12.9 (source=path)` rc=0 | `/app/ansible-env/bin/python3` | `/app/ansible-env/bin/ansible-playbook` core 2.20.3 | `/app/ansible-env/bin/ansible-vault` core 2.20.3 | 6.0.3, exe=`/app/ansible-env/bin/python3` |
| 155 (PATH=`/usr/local/bin:/usr/bin:/bin`) | `[venv] /opt/ansible-env python=Python 3.12.3 (source=known)` rc=0 | `/opt/ansible-env/bin/python3` | `/opt/ansible-env/bin/ansible-playbook` core 2.20.3 | `/opt/ansible-env/bin/ansible-vault` core 2.20.3 | 6.0.3, exe=`/opt/ansible-env/bin/python3` |

음성 (5대 동일):
- `PATH=/usr/bin:/bin` + `SE_ANSIBLE_VENV_CANDIDATES=""` → rc=1, 이후 `echo SENTINEL` 미실행, stderr `[venv] Ansible 실행환경(venv)을 찾지 못했습니다 … 후보=''`
- `SE_ANSIBLE_VENV=/nonexistent` → rc=1, stderr `SE_ANSIBLE_VENV='/nonexistent' 안에 bin/activate 가 없습니다 … (다른 경로로 넘어가지 않습니다)`

## 3. 로컬 검증

| 항목 | 결과 |
|---|---|
| `pytest tests/unit/test_activate_ansible_venv.py` (Git bash) | 10 passed |
| `pytest tests/unit` | 2446 passed |
| `pytest tests/e2e` | 723 passed / 6 skipped |
| Jenkins 선언형 린터 (`/pipeline-model-converter/validate`, lab 153) | "Jenkinsfile successfully validated." |
| `scripts/ai/verify_harness_consistency.py` | 통과 (rules 28 / skills 47 / agents 47 / policies 7) |
| `scripts/ai/verify_docs_references.py` | 삭제 파일 관련 지적 0건 (남은 지적은 이번 변경과 무관한 기존 항목) |

## 4. lab Jenkins Job 실행 (사용자 지정 테스트 경로)

`http://10.100.64.153:8080/job/clovirone-server-gather/` 빌드 **#20** — 브랜치 `production` `e7baaa55`, 입력은 마지막 정상 빌드 #18 과 동일
(`loc=git`, `target_type=redfish`, BMC 4대, `callbackUrl=http://127.0.0.1:9` sink, `deploymentEnvironmentId=1`).

| Stage | 노드 | 결과 |
|---|---|---|
| Resolve Location | Jenkins(controller) | `git -> agent label 'git'` |
| Validate | jenkins-agent-dev | OK (hosts=4) |
| Gather | jenkins-agent-dev | `[venv] /opt/ansible-env python=Python 3.12.3 (source=path)` → envelope 4건 |
| Validate Schema | jenkins-agent-dev | `[venv] /opt/ansible-env python=Python 3.12.3 (source=path)` → 통과 |
| Callback | Jenkins(controller) | sink 주소라 3회 재시도 실패 → UNSTABLE (의도) |

host 별 결과는 #18(변경 전)과 동일: 10.100.15.27 dell success · 10.50.11.232 lenovo success · 10.100.15.2 cisco success ·
10.50.11.231 `failed / reachable / TARGET_UNREACHABLE` (변경 전에도 같은 상태 — 이번 변경과 무관). 소요 7분 2초 (#18 은 7분 6초).

Jenkins 빌드 안에서는 `source=path` 다 — Agent 기동 셸의 PATH 에 `/opt/ansible-env/bin` 이 있다는 뜻이며, 2절의 `source=known` 은
PATH 를 비운 실험 조건이다. 두 경로 모두 같은 venv 로 귀결됐다.

## 5. 신규 Jenkins (jenkins-prod.gooddi.lab) — 보류

`clovirone-cicd/clovirone-server-gather` 빌드 #3·#4(2026-09-28, 변경 전)는 컨트롤러의 Resolve Location 에서 `main` 전체 체크아웃이
2분 제한을 넘겨 ABORTED. 사용자가 Job 브랜치를 `production` 으로 바꿨다. Runner 4대에 `git` 이 없어 Agent 체크아웃은 아직 불가 —
설치 자동화(I-2, 다른 세션) 반영 뒤 1회 실행해 `[venv] /app/ansible-env … (source=path)` 를 확인한다.
