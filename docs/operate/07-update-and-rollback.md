# 업데이트, 설정 보존, 되돌리기

이 문서는 이미 설치된 환경의 수집 코드를 새 버전으로 바꾸거나 이전 버전으로 되돌리는 운영자를 위한 안내입니다. 신규 설치는 [01-jenkins-master.md](01-jenkins-master.md)부터 읽으세요.

## 1. 무엇이 어디에 있나

수집 코드는 전부 Git 저장소에 있고 Jenkins Job은 빌드마다 저장소에서 읽습니다. 그래서 업데이트는 저장소의 브랜치를 바꾸는 일이고, Jenkins와 Runner를 다시 설치하지 않습니다.

| 저장소 밖에 있어 업데이트와 무관하게 보존되는 것 | 위치 |
|---|---|
| vault 마스터 비밀번호 | Jenkins credential `server-gather-vault-password` |
| 저장소 읽기 credential, Runner 접속 credential | Jenkins credentials |
| Add-on 전역 환경변수 (`ADDON_REPO_URL` 등) | Manage Jenkins → System |
| Runner 노드 설정 (이름, remote root, 라벨, executor, 연결 방식, `SE_ANSIBLE_VENV`) | Manage Jenkins → Nodes |
| Runner의 Ansible 실행환경(venv)과 OS 패키지 | Runner 서버 |
| Job 설정 (저장소, 브랜치, Script Path) | Job → Configure |

| 저장소 안에 있어 업데이트에 포함되는 것 |
|---|
| `Jenkinsfile_portal`과 `scripts/` |
| 세 채널의 playbook, 공통 정규화, 어댑터, 플러그인 |
| 암호화된 vault 파일 (`vault/**`) |
| `common/vars/locations.yml` (Location과 라벨) |

## 2. 사내: main과 production

사내는 `main`(개발)과 `production`(배포) 두 브랜치를 씁니다. 운영 Job은 `*/production`을 보므로, 업데이트는 `production`에 새 커밋이 올라가는 일입니다. `production`은 사람이 편집하거나 `main`을 병합하는 브랜치가 아니라 생성기가 고정된 `main` SHA에서 만든 runtime 파일만 올리는 브랜치입니다. 절차와 전제는 [09-production-branch.md](09-production-branch.md)에 있습니다.

업데이트 뒤에는 다음을 확인하세요.

1. `git ls-remote <GitHub 주소> production`과 `git ls-remote <사내 GitLab 주소> production`이 같은 SHA인지.
2. 운영 Job을 대상 1~3대로 한 번 실행해 콘솔의 `Checking out Revision <SHA>`가 새 커밋인지, `[Portal 전송] HTTP 2xx` 줄이 있는지.
3. 결과 봉투의 값이 업데이트 전 빌드와 같은 대상에서 같은지. 바뀐 값은 변경 내역에 적힌 것만이어야 합니다.

## 3. 고객사: main 하나

고객사 저장소는 `main` 하나이고 운영 Job이 `*/main`을 봅니다. 업데이트는 사내 `production`의 tree를 고객사 `main`에 반영하는 일입니다. 반영 방식은 고객사 저장소 운영 방식에 따릅니다(`git archive` 사본 반입 또는 커밋 반영). 커밋 SHA가 보존되지 않을 수 있으므로 동일성은 tree로 확인합니다.

- 배포본의 `.production-provenance.json`에 `tree_hash`(파일 목록의 SHA-256)가 있습니다. 고객사 `main`을 checkout한 뒤 같은 방식으로 계산한 값과 비교하면 같은 내용인지 알 수 있습니다.
- 고객사에 `production` 브랜치, 생성기, 개발용 시험 도구는 필요 없습니다.
- 고객사 Jenkins에서 맞출 값은 설치 때와 같습니다: Job의 Branch Specifier `*/main`, Script Path `Jenkinsfile_portal`, credential `server-gather-vault-password`, Runner 라벨, Runner의 venv.

반영 뒤 확인은 2절의 2와 3과 같습니다.

## 4. 업데이트에 설정 변경이 따르는 경우

변경 내역에 다음이 있으면 코드 반영과 별도로 Jenkins나 Runner 설정을 바꿔야 합니다.

| 변경 | 할 일 |
|---|---|
| `common/vars/locations.yml`에 Location 추가 또는 라벨 변경 | 그 라벨을 가진 Runner 등록, 그 Location의 vault 파일 추가 ([05-vault.md](05-vault.md)) |
| vault 파일 추가 또는 값 변경 | 저장소에 암호화된 파일로 commit. 마스터 비밀번호가 바뀌었으면 Jenkins credential도 갱신 |
| 파이프라인이 새 step을 쓰기 시작 | 해당 플러그인 설치 ([01-jenkins-master.md](01-jenkins-master.md) 5절) |
| Ansible Collection 또는 Python 패키지 요구 변경 | Runner venv 갱신 ([02-agent-node.md](02-agent-node.md) 5절) |
| Script Approval 서명 추가 | 첫 실행에서 `Scripts not permitted` 오류가 나면 승인 |

이 문서를 쓴 시점의 코드는 위 어느 것도 새로 요구하지 않습니다.

## 5. 되돌리기

### 사내 production

이전 정상 `production` 커밋의 tree를 새 커밋으로 두 원격에 올립니다. force push와 reset은 쓰지 않습니다.

```bash
# 작업 PC의 main checkout 에서. <이전 커밋> 은 되돌릴 production 커밋 SHA
python -m scripts.ai.prodgen restore --to <이전 커밋> --push-remote origin,internal
git ls-remote origin production && git ls-remote internal production
```

운영 Job은 브랜치를 고정해 보므로 Job 설정은 바꾸지 않습니다. 되돌린 뒤 2절의 확인을 반복하세요. 상세는 [09-production-branch.md](09-production-branch.md) 5절입니다.

### 고객사 main

이전 정상 tree(배포본 `.production-provenance.json`의 `tree_hash`에 해당하는 사본)를 고객사 `main`에 다시 반영합니다. 사내 production을 되돌린 것만으로 고객사가 복구됐다고 보지 마세요. 고객사 `main`의 실제 내용으로 확인합니다.

### Jenkins와 Runner 설정

Jenkins 설정은 코드 업데이트와 함께 바뀌지 않으므로 되돌릴 것이 없습니다. 4절에서 바꾼 설정이 있다면 그 항목만 이전 값으로 돌리세요.

## 6. 빌드 기록과 Runner 폴더

- 빌드 기록, 콘솔 로그, 결과 파일(artifact)의 보관 기간은 Jenkins 전역 설정(Manage Jenkins → System의 Global Build Discarders)으로 관리합니다. `Jenkinsfile_portal`은 Job별 보관 설정을 두지 않습니다.
- Runner의 작업 폴더는 수집 단계가 결과 보관을 확인하면 바로 지우고, 남은 것은 하루에 한 번 정리합니다([02-agent-node.md](02-agent-node.md) 9절). 업데이트 때 따로 정리할 것은 없습니다.
- Controller의 결과 확인 폴더(`<Job 작업 폴더>/fin-<빌드 번호>`)는 보관을 확인하면 지우고, 남은 것은 7일 뒤 정리합니다. 보관하지 못한 폴더는 지우지 않고 콘솔로 알리므로 사람이 확인한 뒤 지웁니다.

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| production 생성과 승격 전제 | [09-production-branch.md](09-production-branch.md) |
| 파이프라인 동작과 장애 확인 | [04-pipeline-runtime.md](04-pipeline-runtime.md) |
