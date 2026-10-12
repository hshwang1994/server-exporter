# Job 등록과 첫 수집 실행

이 문서는 Jenkins에 수집 Job을 등록하고 처음 실행해 결과를 확인하는 운영자를 위한 안내입니다. 저장소 접근, Credentials와 Vault, Add-on 설정, Job 생성, 파라미터와 예제, 첫 실행의 콘솔과 결과 파일, Portal 전송 확인 순서로 읽습니다.
[01-jenkins-master.md](01-jenkins-master.md)와 [02-agent-node.md](02-agent-node.md)가 끝난 상태를 전제합니다.

## 1. 저장소 접근

| 구성 | 브랜치 | Job의 Branch Specifier |
|---|---|---|
| 사내 (GitHub `origin`과 사내 GitLab `internal`) | `main`(개발)과 `production`(배포) | 개발 검증 Job은 `*/main`, 운영 Job은 `*/production` |
| 고객사 | `main` 하나 | `*/main` |

고객사 저장소에는 `production` 브랜치가 없습니다. 고객사 `main`에는 배포본(runtime 파일만 있는 tree)이 들어가며, 파이프라인은 브랜치 이름을 가정하지 않습니다. 사내에서 `production`을 만드는 방법은 [09-production-branch.md](09-production-branch.md)에 있습니다.

Controller와 Runner 모두 저장소에 닿아야 합니다. Controller는 `readTrusted`로 파일 몇 개만 읽고, Runner는 수집 단계에서 전체를 checkout합니다.

## 2. Credentials와 Vault

| ID | Kind | 어디에 | 용도 |
|---|---|---|---|
| `server-gather-vault-password` | Secret text | Global credentials | ansible-vault 마스터 비밀번호. ID 고정 |
| 저장소 읽기용 (ID 자유) | Username with password (토큰) | Global 또는 Job 폴더 | Pipeline script from SCM |

Vault 파일은 저장소의 `vault/` 아래에 암호화돼 commit됩니다. 위치별 OS와 ESXi 계정, 전역 Redfish 표준 계정, 위치와 제조사별 Redfish 복구 계정의 구조와 편집 방법은 [05-vault.md](05-vault.md)에 있습니다. 새 Location을 쓰려면 Job을 만들기 전에 그 Location의 vault 파일이 있어야 합니다.

## 3. Job 생성

경로: 사내는 폴더 `clovirone-cicd` 안에 만듭니다. 폴더를 쓰지 않아도 됩니다. New Item → Pipeline을 고르세요.

| 항목 | 값 |
|---|---|
| Definition | Pipeline script from SCM |
| SCM | Git |
| Repository URL | 이 저장소 주소 |
| Credentials | 2절의 저장소 읽기용 credential |
| Branch Specifier | 1절의 값 (`*/main` 또는 `*/production`) |
| Script Path | `Jenkinsfile_portal` |
| Lightweight checkout | 켭니다. Controller가 파이프라인 정의와 `readTrusted` 파일을 저장소 전체를 받지 않고 읽습니다 |

수집 파이프라인은 하나이고 `target_type` 파라미터로 OS, ESXi, Redfish를 고릅니다. 종류별로 Job을 나누고 싶으면 같은 Script Path로 Job을 더 만들고 기본값만 다르게 두세요.

사내 Job은 다음 두 개입니다.

| Job | Branch Specifier | 용도 |
|---|---|---|
| `clovirone-cicd/clovirone-server-gather-main` | `*/main` | 개발 검증 |
| `clovirone-cicd/clovirone-server-gather` | `*/production` | 운영 (Portal이 호출) |

Job을 저장한 뒤 한 번 실행하면 Jenkins가 파라미터 화면을 만듭니다. 첫 실행은 파라미터가 비어 입력 확인 단계에서 실패하며, 그 뒤부터 파라미터를 입력할 수 있습니다.

## 4. Add-on(고객별 추가 수집)을 쓸 때

경로: Manage Jenkins → System → Global properties → Environment variables

| 변수 | 필수 | 기본값 | 의미 |
|---|---|---|---|
| `ADDON_REPO_URL` | 켤 때 필수 | 없음(꺼짐) | Add-on 저장소 주소 (`https://`, `http://`, `ssh://`) |
| `ADDON_REPO_REF` | 선택 | `main` | 브랜치, `refs/tags/<태그>`, 40자 커밋 해시 |
| `ADDON_REPO_CREDENTIALS_ID` | 선택 | 없음(익명) | 비공개 저장소의 Jenkins credential ID (Username with password) |
| `ADDON_REPO_SSL_VERIFY` | 선택 | `false` | `true`면 Add-on을 받는 git 명령이 TLS 인증서를 검증합니다. 기본값은 자체 서명 인증서의 내부 저장소도 CA 설치 없이 받습니다 |

변수가 없으면 Add-on을 실행하지 않습니다. 있으면 빌드마다 Runner가 저장소를 받아 검사한 뒤 그 빌드의 수집에만 씁니다. 받지 못하거나 검사에 실패하면 빌드를 UNSTABLE로 표시하고 Add-on 없이 수집합니다. 콘솔에는 `[addon] unavailable: <사유>`가 남고 서버별 결과에는 Add-on 오류가 붙지 않습니다. 동작은 [04-pipeline-runtime.md](04-pipeline-runtime.md) 3절, hook 계약은 [../develop/07-addon-hook.md](../develop/07-addon-hook.md)에 있습니다.

## 5. 파라미터

`Jenkinsfile_portal`이 정의하는 파라미터 7개입니다.

| 파라미터 | 필수 | 설명 |
|---|---|---|
| `loc` | 필수 | 실행 위치. `common/vars/locations.yml`의 키 (`ic`, `cj`, `yi`, `git`) |
| `target_type` | 필수 (기본 `os`) | `os`, `esxi`, `redfish` |
| `inventory_json` | 필수 | 대상 목록 JSON 배열. os와 esxi는 `service_ip`, redfish는 `bmc_ip`, 둘 다 없으면 `ip`를 읽습니다. 표준 JSON만 받고 IPv4만, 중복 불가. 형식은 [../contract/01-input.md](../contract/01-input.md) |
| `deploymentEnvironmentId` | 필수 | Portal 배포 환경 ID. 전송 본문에 그대로 들어갑니다 |
| `eventUuid` | 선택 | Portal 이벤트 UUID. 전송 본문에 그대로 들어갑니다 |
| `callbackUrl` | 필수 | 결과를 보낼 Portal 주소. `http://` 또는 `https://`로 시작하고, 따옴표, 백틱, 역슬래시, 공백, 계정 정보(`사용자:비밀번호@`), 질의 문자열(`?`), 조각(`#`)을 넣을 수 없습니다. 뒤에 `/api/jenkins/gather/<target_type>`을 붙여 POST합니다 |
| `verbosity` | 선택 (기본 `0`) | Ansible verbosity 0~4. 운영은 0을 권장합니다 |

### 예제

```text
loc                     = git
target_type             = os
inventory_json          = [{"service_ip": "192.0.2.10"}, {"service_ip": "192.0.2.11"}]
deploymentEnvironmentId = 1
eventUuid               = 3b1c7f2e-0000-4000-8000-000000000001
callbackUrl             = http://portal.example.com:8080
verbosity               = 0
```

```text
target_type             = redfish
inventory_json          = [{"bmc_ip": "192.0.2.201"}]
```

위 주소와 IP는 예시입니다. 사내 검증에서는 `loc=git`, Portal 주소로 사내 Portal의 주소를 씁니다.

Portal에서 REST로 실행할 때는 Jenkins의 `buildWithParameters`를 씁니다.

```bash
# 호출 측 서버 셸. <계정>:<API 토큰> 은 Jenkins 사용자 설정에서 발급한 값입니다. 비밀값을 스크립트나 로그에 적지 마세요
curl -sS -u '<계정>:<API 토큰>' -X POST '<Jenkins 주소>/job/<폴더>/job/<Job 이름>/buildWithParameters' \
  --data-urlencode 'loc=git' --data-urlencode 'target_type=os' \
  --data-urlencode 'inventory_json=[{"service_ip":"192.0.2.10"}]' \
  --data-urlencode 'deploymentEnvironmentId=1' --data-urlencode 'eventUuid=<UUID>' \
  --data-urlencode 'callbackUrl=http://portal.example.com:8080'
```

HTTP 201이 돌아오면 요청이 큐에 들어간 것입니다.

## 6. 첫 수집 실행과 확인

1. Job의 Build with Parameters에서 5절의 값을 넣고 실행하세요. 대상은 Runner에서 닿는 서버 1~3대로 시작하세요.
2. Stage View에 `입력 확인`, `실행 위치 확인`, `서버 정보 수집`, `결과 확인 및 전송`이 차례로 보입니다. 마지막 단계는 `post` 안에서 돕니다.
3. 콘솔에서 다음 줄을 확인하세요.

| 줄 | 뜻 |
|---|---|
| `[입력 확인] 요청을 접수했습니다. OS 2대, 실행 위치 git.` | 대상 목록이 접수됐습니다 |
| `[실행 위치] git 위치의 os 대상은 'git && (linux && windows)' 라벨의 Runner에서 실행합니다.` | 라벨식과 등록된 Runner 수 |
| `Running on <Runner 이름> in <작업 폴더>` | 수집을 실행하는 Runner |
| `[venv] /app/ansible-env python=Python 3.12.9 (source=path)` | 고른 Ansible 실행환경 |
| `[수집] OS 서버 2대의 정보 수집을 시작합니다.` | 수집 시작. 5분마다 진행 줄이 나옵니다 |
| `[수집] 수집 실행을 마쳤습니다. 소요 시간 25초.` | 수집 끝 |
| `[결과 보존] 결과를 빌드에 저장하고 다음 단계로 전달했습니다.` | 결과 파일을 빌드에 보관했습니다 |
| `[결과] 성공 2대, 부분 성공 0대, 실패 0대` | 보낼 결과의 집계 |
| `[Portal 전송] HTTP 200 응답을 받았습니다. 소요 시간 0.2초.` | Portal이 요청을 받았습니다 |
| `[요약] 정상 종료 (SUCCESS)` | 빌드 요약 |

4. 빌드 페이지의 Artifacts에서 결과 파일을 여세요.

| 파일 | 내용 |
|---|---|
| `gather_final.jsonl` | 서버마다 한 줄씩 결과 봉투(JSON). 형식은 [../contract/02-output-envelope.md](../contract/02-output-envelope.md) |
| `callback_body.json` | Portal에 보낸 본문 `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson:[...]}` |
| `finalize_summary.json` | 실행 요약. 접수 수, 보낸 결과 수, 전송 기록(`callback.tries[]`), 수집 시도 기록(`gather_run`), 경고 |
| `gather_output.json`, `gather_run.json` | 수집 단계의 원본 결과와 시도 기록 |

5. 결과 봉투의 값을 대상에서 직접 확인하세요. 예를 들어 Linux 대상에서 `hostname`, `cat /proc/cpuinfo`, `free -m`를 본 값과 봉투의 `data.system`, `data.cpu`, `data.memory`를 맞춰 보세요. Jenkins 결과가 SUCCESS이고 Portal 응답이 200이라는 것만으로 값이 맞다고 보지 마세요.
6. Portal 쪽에서 같은 `eventUuid`의 요청이 접수됐는지 확인하세요. 파이프라인은 HTTP 2xx를 받으면 전달을 마친 것으로 봅니다. Portal의 저장과 반영은 Portal의 역할입니다.

## 7. 실패했을 때 먼저 볼 것

| 증상 | 원인과 조치 |
|---|---|
| `ERROR: [입력 확인] inventory_json[<번호>] ...` | 그 번호의 대상 값이 규칙에 어긋납니다. 요청 전체가 거부되고 Portal로 결과가 가지 않습니다 |
| `ERROR: [입력 확인] inventory_json을 JSON으로 읽지 못했습니다.` | 표준 JSON이 아닙니다(홑따옴표, 따옴표 없는 키, 끝 쉼표, 주석) |
| `ERROR: [입력 확인] callbackUrl에는 질의 문자열(?)이나 조각(#)을 넣을 수 없습니다.` | 주소 뒤에 경로를 붙여야 하므로 `?`와 `#`는 받지 않습니다 |
| `[실행 위치] 등록되지 않은 Location: '...'` | `loc`가 `common/vars/locations.yml`에 없습니다 |
| `[실행 위치] 라벨 '...'에 해당하는 Runner가 Jenkins에 등록돼 있지 않습니다.` | [02-agent-node.md](02-agent-node.md) 7절의 라벨을 확인하세요. 접수된 대상마다 실패 결과는 보냅니다 |
| `[Portal 전송] N번째 전송에 실패했습니다.` 와 `Portal 주소를 해석하지 못했습니다(이름 풀이 실패).` | Controller가 `callbackUrl`의 호스트 이름을 해석하지 못합니다. Controller의 DNS와 주소를 확인하세요. 요청은 Portal에 닿지 않았고 남은 횟수 안에서 다시 보냅니다 |
| `[Portal 전송] N번째 전송에 실패했습니다.` 와 `연결하지 못했거나 응답을 받지 못했습니다.` | Portal 주소, 포트, 방화벽을 확인하세요. 3번 모두 실패하면 UNSTABLE이고 본문은 `callback_body.json`에 남습니다 |
| `[Portal 전송] Portal이 요청을 거부했습니다. HTTP 4xx.` | Portal이 요청을 받고 거부했습니다. 다시 보내지 않습니다. Portal 쪽 로그를 보세요 |
| `[venv] Ansible 실행환경(venv)을 찾지 못했습니다.` | [02-agent-node.md](02-agent-node.md) 5절 |
| 빌드가 UNSTABLE이고 `[addon] unavailable: ...` | Add-on 저장소를 받지 못했거나 검사에 실패했습니다. 4절의 변수와 그 위 `[addon]` 줄을 보세요. 기본 수집은 정상입니다 |

## 8. 사내 개발 환경의 검증 Job

사내 개발 환경에는 수집 Job 외에 개발 검증용 Job이 더 있습니다. 고객사 설치에는 필요 없습니다.

| Job | Script Path | 용도 |
|---|---|---|
| `clovirone-server-gather-ci` | `Jenkinsfile_ci` (`*/main`) | 정적 검사와 회귀 시험, production tree 생성과 검증 |
| `clovirone-server-gather-harness` | `tests/jenkins/harness/Jenkinsfile_harness` (`*/main`) | 파이프라인 함수의 장애 시나리오 시험 |
| `clovirone-server-gather-net-probe`, `clovirone-server-gather-term-probe`, `clovirone-server-gather-perf-observe` | `tests/jenkins/harness/Jenkinsfile_*` (`*/main`) | 진단과 관측 |

이 Job들은 수집을 하지 않으며 `production` 브랜치에는 그 파일이 없습니다. 정의는 `jenkins/jobs/<Job 이름>/config.xml`에 있습니다.

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 파이프라인이 실제로 하는 일 | [04-pipeline-runtime.md](04-pipeline-runtime.md) |
| 호출자 입력 형식 | [../contract/01-input.md](../contract/01-input.md) |
| 결과 봉투와 실패 진단 | [../contract/02-output-envelope.md](../contract/02-output-envelope.md), [../contract/04-failure-and-diagnosis.md](../contract/04-failure-and-diagnosis.md) |
| 업데이트와 되돌리기 | [07-update-and-rollback.md](07-update-and-rollback.md) |
