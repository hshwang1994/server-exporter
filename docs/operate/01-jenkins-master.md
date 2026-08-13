# 01. Jenkins 마스터 설치 및 설정

> **이 문서는** Jenkins 마스터 서버를 새로 구축하는 운영자를 위한 단계별 설치 가이드다.
> 처음부터 끝까지 순서대로 따라가면 Jenkins 가 켜지고, 플러그인이 깔리고, RBAC 권한까지 잡힌다.
>
> 개발 / 운영 두 환경을 운영하는 경우, 본 절차를 **두 마스터에 각각 동일하게** 수행한다.
> 두 환경은 네트워크 / 자격증명 / Job 정의가 모두 분리되어야 한다.

> **사전 준비**
> - Linux 서버 1대 (RHEL/Rocky 8+ 또는 Ubuntu 18.04+)
> - root 또는 sudo 권한이 있는 계정
> - 인바운드 8080/tcp 가 열려 있어야 한다 (사내망 한정 권장)

> 모든 명령은 **root** 또는 **sudo** 로 실행한다.

---

## 1. Java 설치

```bash
# RHEL 계열
yum install -y java-21-openjdk

# Debian 계열
apt update && apt install -y openjdk-21-jdk

# 확인
java -version
```

> **Java 21 필수**: Jenkins 의 Java 17 지원은 종료되었다 (2026-03-31).
> Java 21 은 Jenkins LTS 2.426.1 부터 지원된다. 신규 설치 시 반드시 Java 21 을 사용한다.
> 기존 Java 17 환경은 위 패키지 설치 후 Jenkins 재시작으로 전환한다.
> 검증 기준 Agent: OpenJDK 21.0.10.

---

## 2. Jenkins 설치

```bash
# RHEL 계열
wget -O /etc/yum.repos.d/jenkins.repo https://pkg.jenkins.io/redhat-stable/jenkins.repo
rpm --import https://pkg.jenkins.io/redhat-stable/jenkins.io-2026.key
yum install -y jenkins

# Debian 계열
curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key \
  | tee /usr/share/keyrings/jenkins-keyring.asc > /dev/null
echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc] \
  https://pkg.jenkins.io/debian-stable binary/" \
  | tee /etc/apt/sources.list.d/jenkins.list > /dev/null
apt update && apt install -y jenkins
```

> **GPG 키 갱신**: 기존 `jenkins.io-2023.key` 는 2026-03-26 만료.
> 이미 설치된 환경에서는 아래 명령으로 키만 교체할 수 있다.
> ```bash
> # RHEL
> rpm --import https://pkg.jenkins.io/redhat-stable/jenkins.io-2026.key
> # Debian
> curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key \
>   | tee /usr/share/keyrings/jenkins-keyring.asc > /dev/null
> ```

---

## 3. 서비스 시작

```bash
systemctl enable jenkins --now
systemctl status jenkins

# 초기 관리자 비밀번호
cat /var/lib/jenkins/secrets/initialAdminPassword
```

---

## 4. 초기 설정

1. 브라우저에서 `http://{마스터IP}:8080` 접속
2. 초기 관리자 비밀번호 입력
3. **Install suggested plugins** 선택
4. 관리자 계정 생성

---

## 5. 방화벽 설정

```bash
# RHEL 계열
firewall-cmd --permanent --add-port=8080/tcp
firewall-cmd --reload

# Debian 계열
ufw allow 8080/tcp
```

---

## 6. 플러그인 설치

경로: Jenkins → Manage Jenkins → Plugins → Available plugins

> 4절 초기 설정에서 **Install suggested plugins** 를 선택하면
> Pipeline, Credentials, Git 등 기본 플러그인은 자동 설치된다.
> 아래 표에서 ★ 표시가 없는 항목만 별도 설치하면 된다.

### 필수 플러그인

| 플러그인 | 용도 | suggested 포함 |
|----------|------|:--------------:|
| **Ansible** | `ansiblePlaybook()` 스텝 | |
| **GitLab** | GitLab SCM 연동 | |
| **Role-based Authorization Strategy** | Job 단위 권한 분리 | |
| **Credentials** | GitLab 계정 중앙 관리 | ★ |
| **Pipeline** | Declarative Pipeline 실행 | ★ |
| **Pipeline Utility Steps** | `readJSON` 스텝 (Jenkinsfile 파라미터 파싱) | |
| **AnsiColor** | `ansiColor('xterm')` 옵션 — Ansible 컬러 출력 | |
| **HTTP Request** | `httpRequest()` 스텝 — 외부 시스템 콜백/알림 | |
| **Git** | SCM checkout | ★ |

### 권장 플러그인

| 플러그인 | 용도 |
|----------|------|
| **Pipeline: Stage View** | Stage 별 실행 결과 시각화 |
| **Blue Ocean** | 파이프라인 실행 과정 UI |
| **Timestamper** | 콘솔 로그 타임스탬프 |
| **Workspace Cleanup** | 빌드 후 workspace 자동 정리 |

### Ansible 플러그인 경로 설정

경로: Jenkins → Manage Jenkins → Tools → Ansible installations

| 항목 | 값 |
|------|----|
| Name | `ansible` |
| Path to ansible executables directory | `/opt/ansible-env/bin` |

> 이 경로는 02-agent-node.md 5절 에서 Agent 에 가상환경을 생성한 뒤 실제로 동작한다.
> 마스터에서는 경로만 미리 등록해두면 된다.

---

## 7. Credentials 등록

경로: Jenkins → Manage Jenkins → Credentials → System → Global credentials → Add Credentials

### gitlab-credentials

GitLab 레포지토리 checkout 에 사용하는 계정.

| 항목 | 값 |
|------|----|
| Kind | Username with password |
| Username | GitLab 계정 아이디 |
| Password | GitLab Access Token (api 권한) — 비밀번호가 아닌 토큰 입력 |
| ID | `gitlab-credentials` |

**GitLab Access Token 발급**
1. GitLab → Preferences → Access Tokens
2. Scopes: `api` 체크
3. Create → 발급된 토큰을 Password 에 입력

### server-gather-vault-password (vault 복호화용)

저장소의 `vault/*.yml` 파일들은 ansible-vault 로 암호화된 상태로 commit 됩니다.
Jenkins 가 ansible-playbook 을 실행할 때 이 credential 로 vault 를 복호화합니다.

| 항목 | 값 |
|------|----|
| Kind | **Secret text** |
| Secret | vault 마스터 패스워드 (단일 라인 문자열) |
| ID | `server-gather-vault-password` |

**등록 절차**

1. 운영자가 vault 마스터 패스워드를 결정한다.
2. 로컬 작업자 PC 에서 그 패스워드를 한 줄짜리 `.vault_pass` 파일로 두고 `bash scripts/bootstrap_vault_encrypt.sh` 로 `vault/*.yml` 을 일괄 encrypt 후 commit 한다.
3. 같은 패스워드 문자열을 Jenkins credentials store 에 **Secret text** 로 등록한다 (ID `server-gather-vault-password`).
4. `.vault_pass` 는 `.gitignore` 에 의해 절대 commit 되지 않는다 — 로컬 작업자 PC 에만 둔다.

**Jenkins 빌드 동작**

`withCredentials([string(credentialsId: 'server-gather-vault-password', variable: 'VAULT_PASSWORD')])`
가 `$VAULT_PASSWORD` 를 주입한다. Pipeline 이 그 값을 임시 파일(`.vault_pass_tmp`, chmod 600)에 써서
`--vault-password-file` 로 ansible-playbook 에 넘기고, 빌드 종료 시 임시 파일을 삭제한다.
패스워드 값은 콘솔 로그에 자동 마스킹됩니다.

**검증 (로컬)**

```bash
# 로컬에서 ansible-playbook 단독 실행 시
ansible-playbook --vault-password-file=.vault_pass redfish-gather/site.yml -i ...
```

**[CRIT] 본 credential 미등록 시 발생하는 오류**

이 credential 이 Jenkins 에 등록되지 않은 상태에서 빌드를 실행하면
다음 오류로 빌드가 즉시 실패합니다.

```text
Could not find credentials entry with ID 'server-gather-vault-password'
```

새 Jenkins 환경 초기 셋업 시 본 절차를 가장 먼저 수행하세요.

---

## 8. RBAC 권한 설정

Role Strategy Plugin 으로 Job 단위 접근 권한을 제어합니다.
Job 이름이 패턴과 일치하면 권한이 자동 적용되므로, 신규 Job 추가 시 별도 권한 설정이 필요 없습니다.

### RBAC 가 하는 일 (한 줄 요약)

- 포털 서비스 계정은 server-exporter 의 Job 만 보고/실행할 수 있다.
- 인프라 엔지니어 계정은 인프라 자동화 Job 만 보고/실행할 수 있다.
- admin 계정만 Jenkins 시스템 전체를 관리한다.

### Global Roles

경로: Jenkins → Manage Jenkins → Manage and Assign Roles → Manage Roles → Global roles

| Role | Overall 권한 | 설명 |
|------|-------------|------|
| `admin` | Administer | 시스템 전체 관리자 |
| `portal` | Read | 포털 서비스 계정 |
| `engineer` | Read | 인프라 엔지니어 |

### Item Roles

| Role | Pattern | 부여 권한 |
|------|---------|----------|
| `portal` | `server-exporter.*` | Job Build, Read |
| `engineer` | `infra-automation.*` | Job Build, Create, Configure, Read |

### 동작 확인

- `engineer` 계정 로그인 시 `server-exporter.*` Job 이 보이지 않아야 함
- `portal` 계정 로그인 시 `infra-automation.*` Job 이 보이지 않아야 함

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Redis 설치 (마스터에 함께) | [02-agent-node.md](02-agent-node.md) |
| Agent 노드 구성 | [02-agent-node.md](02-agent-node.md) |
| Jenkins Job 등록 | [03-job-registration.md](03-job-registration.md) |
| Vault 운영 (회전 / 검증) | [05-vault.md](05-vault.md) |

## 자주 막히는 곳

| 증상 | 원인 / 해결 |
|------|------------|
| Jenkins 가 시작은 되는데 Pipeline 빌드가 실패 | `Ansible installations` 등록 누락 — 6절 "Ansible 플러그인 경로 설정" 다시 확인 |
| `Could not find credentials entry with ID 'server-gather-vault-password'` | 7절 vault credential 등록 안 됨 |
| Job 은 보이는데 Build 버튼이 없음 | RBAC 의 Item Role pattern 미스매치 — 8절 |
| GitLab checkout 실패 | gitlab-credentials 의 Password 자리에 비밀번호 대신 Access Token 입력 필요 |
