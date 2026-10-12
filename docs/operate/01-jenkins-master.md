# Jenkins Controller 설치와 설정

이 문서는 서버 정보 수집 파이프라인을 실행할 Jenkins Controller(기존 명칭 Master)를 새로 준비하거나 점검하는 운영자를 위한 안내입니다.
전체 구성, 통신 경로, Controller 설치와 설정, 설치 결과 확인 순서로 읽습니다. Runner 구성은 [02-agent-node.md](02-agent-node.md), Job 등록은
[03-job-registration.md](03-job-registration.md)에 이어집니다.

## 1. 전체 구성과 역할

| 구성 요소 | 역할 | 이 저장소에서 쓰는 것 |
|---|---|---|
| Portal(호출자) | Jenkins Job을 파라미터와 함께 실행하고, 결과를 HTTP POST로 받습니다 | Job 파라미터 7개, `callbackUrl` 뒤에 붙는 `/api/jenkins/gather/<target_type>` |
| Jenkins Controller | 파이프라인(`Jenkinsfile_portal`)을 읽고 단계를 지휘합니다. 입력 확인과 실행 위치 확인은 Controller에서 노드 없이 돌고, 결과 확인과 Portal 전송은 Controller의 built-in 노드에서 돕니다 | Pipeline 플러그인, 저장소 읽기 credential, vault 비밀번호 credential |
| Runner(Jenkins Agent) | 저장소를 받고 `ansible-playbook`으로 대상에 접속해 정보를 수집합니다. 결과 파일을 Controller로 넘깁니다 | Ansible 실행환경(venv), 대상 서버와 BMC로 가는 통신 경로 |
| 대상 | Linux(SSH), Windows(WinRM), ESXi(vSphere API), BMC(Redfish API) | 자격증명은 저장소의 vault에 있습니다 |

Controller에는 Python도 Ansible도 필요 없습니다. 수집은 모두 Runner에서 돕니다.

## 2. 설치 환경을 적는 기준

이 문서와 이어지는 문서는 환경 값을 세 가지로 나눠 적습니다.

| 구분 | 뜻 | 예 |
|---|---|---|
| 확인한 조합 | 사내 검증 환경에서 설치하고 실행을 확인한 값입니다. 다른 환경의 필수 조건이 아닙니다 | Jenkins 2.528.3, Java 21 |
| 필수 | 공식 문서나 이 저장소의 코드가 요구하는 값입니다. 근거를 함께 적습니다 | 파이프라인이 호출하는 step의 플러그인 |
| 선택 또는 미확인 | 바꿔도 되는 설정이거나, 사내에서 확인하지 않은 범위입니다. 지원하지 않는다는 뜻이 아닙니다 | Jenkins 포트, HTTPS 구성 방식 |

### 확인한 조합(사내 검증 환경)

| 항목 | 값 |
|---|---|
| Jenkins | 2.528.3 (LTS) |
| 접속 주소 | `https://jenkins-prod.gooddi.lab` (HTTPS 443) |
| Controller OS와 Java | Linux, Java 21 |
| built-in 노드 executor | 12 |
| Runner 연결 방식 | SSH (Controller가 Runner에 접속해 Agent를 띄웁니다) |

## 3. 통신 경로, 인증서, 권한

| 출발 | 목적지 | 포트 | 용도 | 근거 |
|---|---|---|---|---|
| Portal | Jenkins Controller | Jenkins 접속 주소의 포트 (사내 443) | Job 실행 요청 | Jenkins 접속 주소 |
| Jenkins Controller | Git 저장소 | 443 (HTTPS) | 파이프라인 정의와 `common/vars/locations.yml`, `scripts/jenkins/se_finalize.groovy`, `common/vars/*.yml`을 저장소에서 파일 단위로 읽습니다. Controller는 저장소 전체를 받지 않습니다 | `Jenkinsfile_portal`의 `readTrusted` |
| Jenkins Controller | Runner | 22 (SSH) | SSH 방식으로 Agent를 띄울 때. inbound 방식이면 방향이 반대입니다 | 노드 설정 |
| Jenkins Controller | Portal | `callbackUrl`의 포트 | 결과 전송(HTTP POST). Runner가 아니라 Controller의 built-in 노드가 보냅니다 | `Jenkinsfile_portal`의 `seCallback` |
| Runner | Git 저장소 | 443 (HTTPS) | 수집 단계의 저장소 checkout | `Jenkinsfile_portal`의 수집 단계 |
| Runner | Add-on 저장소 | 저장소 주소의 포트 | 전역 환경변수 `ADDON_REPO_URL`을 설정한 경우에만 | `scripts/addon_checkout.sh` |
| Runner | 대상 서버와 BMC | 22, 5985, 5986, 443 | 수집. 자세한 포트는 [02-agent-node.md](02-agent-node.md) 2절 | `common/library/precheck_bundle.py` |

인증서는 세 곳에서 다룹니다.

- Jenkins를 HTTPS로 열면 Jenkins 또는 앞단 프록시에 서버 인증서를 둡니다. 구성 방식은 조직 정책에 따릅니다(사내는 HTTPS 443).
- Git 저장소가 자체 서명 인증서를 쓰면 Controller와 Runner의 git이 그 CA를 신뢰해야 합니다. Add-on 저장소만은 `ADDON_REPO_SSL_VERIFY`로 검증을 끌 수 있습니다([03-job-registration.md](03-job-registration.md) 4절).
- 대상 BMC와 ESXi의 자체 서명 인증서는 수집 코드가 검증하지 않습니다. Runner에 CA를 설치할 필요가 없습니다.

권한은 다음 세 가지입니다.

- Portal이 쓰는 Jenkins 계정에는 해당 Job의 Read와 Build 권한이 필요합니다.
- 운영자 계정에는 노드, credential, 전역 설정을 바꿀 Administer 권한이 필요합니다.
- Runner의 OS 계정에는 Agent 작업 폴더(remote root)에 대한 쓰기 권한이 필요합니다([02-agent-node.md](02-agent-node.md) 3절).

## 4. Controller 설치

모든 명령은 Controller 서버의 셸에서 root 또는 sudo로 실행합니다.

### 4.1 Java

설치하려는 Jenkins LTS가 지원하는 Java 버전을 Jenkins 공식 지원 정책 페이지(`https://www.jenkins.io/doc/book/platform-information/support-policy-java/`)에서 먼저 확인하세요.
이 문서를 쓴 시점의 공식 표에서 Java 21은 Jenkins 2.479.1 이후 LTS가 지원하고, Java 17 지원은 2.541.3 LTS까지이며, Java 25는 2.541.1 이후 LTS가 지원합니다.
사내 확인 조합은 Jenkins 2.528.3과 Java 21입니다.

```bash
# RHEL 계열
dnf install -y java-21-openjdk

# Debian 계열
apt update && apt install -y openjdk-21-jre

# 확인
java -version
```

### 4.2 Jenkins 패키지

Jenkins 공식 저장소를 등록하고 LTS 패키지를 설치합니다. 저장소 주소와 서명 키는 Jenkins 공식 설치 문서(`https://www.jenkins.io/doc/book/installing/linux/`)의 현재 값을 쓰세요. 키 파일 이름은 해마다 바뀝니다.

```bash
# RHEL 계열
wget -O /etc/yum.repos.d/jenkins.repo https://pkg.jenkins.io/redhat-stable/jenkins.repo
rpm --import <공식 문서의 현재 키 URL>
dnf install -y jenkins

# Debian 계열
curl -fsSL <공식 문서의 현재 키 URL> | tee /usr/share/keyrings/jenkins-keyring.asc > /dev/null
echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/" | tee /etc/apt/sources.list.d/jenkins.list > /dev/null
apt update && apt install -y jenkins
```

### 4.3 서비스 시작과 초기 설정

```bash
systemctl enable jenkins --now
systemctl status jenkins
cat /var/lib/jenkins/secrets/initialAdminPassword
```

1. 브라우저에서 Jenkins 주소에 접속하세요. 기본 포트는 8080입니다. HTTPS로 열려면 Jenkins의 HTTPS 설정이나 앞단 프록시를 조직 방식대로 구성하세요.
2. 초기 관리자 비밀번호를 입력하세요.
3. `Install suggested plugins`를 선택하세요. 5절의 필수 플러그인 대부분이 여기서 설치됩니다.
4. 관리자 계정을 만드세요.
5. 방화벽에서 Jenkins 포트를 여세요.

```bash
# RHEL 계열 (8080 을 쓰는 경우)
firewall-cmd --permanent --add-port=8080/tcp && firewall-cmd --reload
```

## 5. 플러그인

경로: Manage Jenkins → Plugins → Installed plugins에서 확인하고, 없으면 Available plugins에서 설치하세요.

### 필수 플러그인

파이프라인 `Jenkinsfile_portal`이 실제로 호출하는 step 기준입니다. 플러그인 버전은 고정하지 않습니다. 설치된 Jenkins LTS가 제공하는 현재 버전을 쓰세요.

| 플러그인 | 파이프라인이 쓰는 step | suggested plugins 포함 |
|---|---|---|
| Pipeline (Declarative, Groovy, Job, Basic Steps, Nodes and Processes) | `pipeline {}`, `retry`, `timeout`, `stash`, `unstash`, `archiveArtifacts`, `unarchive`, `node`, `sh`, `ws`, `load` | 예 |
| Pipeline: Multibranch | `readTrusted` (실행 위치 확인과 결과 확인이 저장소 파일을 읽습니다) | 예 |
| Pipeline Utility Steps | `readJSON`, `readYaml`, `nodesByLabel`, `findFiles` | 아니오 |
| Credentials Binding | `withCredentials` (vault 비밀번호) | 예 |
| Git | Pipeline script from SCM, 수집 단계의 checkout | 예 |
| HTTP Request | `httpRequest` (Portal 전송) | 아니오 |

### 선택 플러그인

| 플러그인 | 용도 |
|---|---|
| Timestamper | 콘솔 줄마다 시각을 붙입니다. 없어도 파이프라인은 그대로 돕니다. 업무 사건 줄은 본문에 시각을 적습니다 |
| SSH Build Agents | Runner를 SSH 방식으로 띄울 때 필요합니다(사내 방식). inbound 방식을 쓰면 필요 없습니다 |
| Folders | Job을 폴더로 묶을 때. 사내는 `clovirone-cicd` 폴더를 씁니다 |

### 필요 없는 플러그인

Ansible, AnsiColor, GitLab, Role-based Authorization Strategy, Blue Ocean은 이 파이프라인이 쓰지 않습니다. 수집은 `sh`로 `ansible-playbook`을 직접 실행하고, 권한은 Jenkins 기본 권한 설정으로 충분합니다. 설치돼 있어도 영향은 없습니다.

### 사내 확인 조합(플러그인 버전)

Jenkins 2.528.3에서 http_request 1.25, workflow-basic-steps 1098, workflow-durable-task-step 1479, pipeline-utility-steps 3.810, credentials-binding 728, git 5.10.1, timestamper 1.30, ssh-slaves 3.1097 조합으로 실행을 확인했습니다. 참고 값이며 이 버전을 맞출 필요는 없습니다.

## 6. Credentials

경로: Manage Jenkins → Credentials → System → Global credentials (또는 Job을 둔 폴더의 Credentials)

| ID | Kind | 내용 | 쓰는 곳 |
|---|---|---|---|
| `server-gather-vault-password` | Secret text | ansible-vault 마스터 비밀번호 한 줄 | 수집 단계가 `withCredentials([string(...)])`로 주입합니다. ID는 `Jenkinsfile_portal`에 고정돼 있어 바꾸면 수집이 시작되지 않습니다 |
| 저장소 읽기용 (ID는 자유) | Username with password | Git 사용자 이름과 접근 토큰 | Job의 Pipeline script from SCM 설정에서 고릅니다. Controller의 `readTrusted`와 Runner의 checkout이 같은 credential을 씁니다 |
| Runner 접속용 (ID는 자유) | SSH Username with private key | Runner OS 계정과 개인키 | SSH 방식 노드 설정에서 고릅니다 |

vault 비밀번호 등록 순서는 다음과 같습니다.

1. 운영 담당자가 vault 마스터 비밀번호를 정합니다.
2. 작업 PC에서 그 값을 `.vault_pass` 파일에 한 줄로 두고 `bash scripts/bootstrap_vault_encrypt.sh`로 `vault/**/*.yml`을 암호화한 뒤 commit합니다. `.vault_pass`는 `.gitignore`에 들어 있어 commit되지 않습니다.
3. 같은 값을 Jenkins에 Secret text, ID `server-gather-vault-password`로 등록합니다.

수집 단계는 이 값을 Runner의 임시 파일(권한 600)에 써서 `ansible-playbook --vault-password-file`로 넘기고 실행이 끝나면 지웁니다. 값은 콘솔에서 마스킹됩니다.
이 credential이 없으면 수집 단계가 다음 오류로 바로 실패합니다.

```text
Could not find credentials entry with ID 'server-gather-vault-password'
```

## 7. 전역 환경변수(Add-on을 쓸 때만)

경로: Manage Jenkins → System → Global properties → Environment variables

고객별 추가 수집(Add-on)을 켤 때만 등록합니다. 변수가 없으면 Add-on 없이 기본 수집만 합니다. 변수 목록과 동작은 [03-job-registration.md](03-job-registration.md) 4절에 있습니다. Runner에 파일을 두거나 노드 환경변수를 등록하지 않습니다.

## 8. built-in 노드

결과 확인과 Portal 전송은 Controller의 built-in 노드에서 돕니다(`Jenkinsfile_portal`의 `seWithNode('built-in')`). built-in 노드의 executor 수가 0이면 모든 빌드가 결과 처리 노드를 기다리다 끝납니다. executor를 1개 이상 두세요. 사내는 12개입니다.

built-in 노드에는 Python, Ansible, git CLI가 필요 없습니다. 결과 처리는 Jenkins step만 씁니다.

## 9. Script Approval

파이프라인은 Jenkins sandbox 안에서 실행되도록 작성돼 있습니다. 수집 Job이 `Scripts not permitted to use ...` 오류로 끝나면 Manage Jenkins → In-process Script Approval에서 해당 서명을 승인한 뒤 다시 실행하세요.
사내 Jenkins의 승인 목록에는 `groovy.json.JsonOutput toJson(Object)`와 `groovy.json.JsonSlurperClassic` 생성자 등 5개 서명이 있으며, 수집 Job은 이 상태에서 실행을 확인했습니다.

## 10. 설치 확인

| 확인 항목 | 방법 | 기대 |
|---|---|---|
| Jenkins 버전 | Manage Jenkins → System Information, 또는 `curl -sI <Jenkins 주소>/ \| grep -i x-jenkins` | 설치한 LTS 버전 |
| 플러그인 | Manage Jenkins → Plugins → Installed plugins | 5절 필수 플러그인이 모두 있음 |
| credential | Manage Jenkins → Credentials | `server-gather-vault-password`(Secret text)와 저장소 읽기 credential이 있음 |
| built-in executor | Manage Jenkins → Nodes → Built-In Node | executor 1 이상 |
| Portal에서 접근 | Portal 서버에서 `curl -sI <Jenkins 주소>/login` | HTTP 200 |

이 뒤의 순서는 Runner 구성([02-agent-node.md](02-agent-node.md)), Job 등록과 첫 실행([03-job-registration.md](03-job-registration.md))입니다.

## 자주 막히는 곳

| 증상 | 원인과 조치 |
|---|---|
| `Could not find credentials entry with ID 'server-gather-vault-password'` | 6절의 vault 비밀번호 credential이 없거나 ID가 다릅니다 |
| `No such DSL method 'readTrusted'` 또는 `'httpRequest'` | Pipeline: Multibranch 또는 HTTP Request 플러그인이 없습니다. 5절 |
| 결과 확인 단계가 `결과 처리 노드`를 기다리기만 함 | built-in 노드 executor가 0입니다. 8절 |
| `Scripts not permitted to use ...` | 9절의 Script Approval |
| Jenkins가 저장소를 읽지 못해 빌드가 stage 없이 끝남 | Controller에서 Git 저장소 주소를 해석하거나 연결하지 못합니다. 3절의 Controller → Git 경로 |
