# 03. Agent 노드 구성

> **이 문서는** Jenkins Agent 노드(실제로 ansible-playbook 이 실행되는 머신) 를 새로 구축할 때 따라가는 단계별 가이드입니다.
> VM 사양 산정 → OS 패키지 → Python venv → Ansible / pywinrm / pyvmomi 설치 → Jenkins 마스터 등록까지 한 번에 다룹니다.
>
> **언제 이 문서를 보는가?**
> - 새 사이트 (이천 / 청주 / 용인 등) 에 Agent 를 처음 구축할 때
> - 기존 Agent 가 노후화 / 장애로 재구축이 필요할 때
> - ansible / 컬렉션을 업그레이드해야 할 때

> **사전 준비**
> - 본 절차를 시작하기 전 [01_jenkins-setup.md](01_jenkins-setup.md) (마스터 설치) + [02_redis-install.md](02_redis-install.md) 가 완료되어야 합니다.
> - Agent 노드는 마스터와 같은 사내망에 있어야 하며, 마스터로의 8080/tcp + Redis 6379/tcp 양방향이 필요합니다.

> **검증 기준 환경 (참고)**: Ubuntu 24.04, Python 3.12, ansible-core 2.20, Java 21 (10.100.64.154 에서 2026-03-27 확인)

Jenkins Agent 는 로케이션 (이천 / 청주 / 용인) 별로 구성하며, 개발 / 운영 마스터 각각에 연결된 Agent 가 분리되어 있습니다.
아래 절차를 각 Agent 노드마다 반복 수행합니다.

---

## 1. VM 리소스 산정

### Jenkins 마스터

| 항목 | 사양 |
|------|------|
| CPU | 8 core |
| RAM | 32 GB (Jenkins 16GB + Redis 1GB + 여유) |
| Disk | 500 GB (빌드 로그, 히스토리 누적 고려) |

### Jenkins Agent

| 항목 | 사양 |
|------|------|
| CPU | 8 core |
| RAM | 16 GB |
| Disk | 100 GB (Ansible 가상환경 + workspace) |

### Redis (마스터 노드에 함께 설치)

호스트 약 1만 대 기준 (추정):

```text
호스트당 facts 평균 20~50KB × 10,000대 = 200~500MB
여유분 포함 → maxmemory 1GB
eviction policy: allkeys-lru
fact_caching_timeout: 86400 (24시간)
```

```ini
# /etc/redis.conf
maxmemory 1gb
maxmemory-policy allkeys-lru
```

---

## 2. 방화벽 오픈 목록

| 출발 | 목적지 | 포트 | 프로토콜 | 용도 |
|------|--------|------|----------|------|
| 포털 | Jenkins 마스터 | 8080 | TCP | Jenkins Job 트리거 |
| Jenkins 마스터 | GitLab | 443 | TCP | Jenkinsfile / repo checkout |
| Jenkins 마스터 | Agent | 22 | TCP | SSH — Agent 연결 |
| Agent | Jenkins 마스터 | 6379 | TCP | Redis Fact 캐싱 |
| Agent | 대상서버 Linux/ESXi | 22 | TCP | SSH |
| Agent | 대상서버 Windows | 5985/5986 | TCP | WinRM |
| Agent | 대상서버 Redfish | 443 | TCP | BMC HTTPS API |

> Redis(6379) 는 내부망만 오픈. 외부 차단 필수.

---

## 3. 기본 패키지 설치

```bash
# RHEL 계열
yum install -y java-21-openjdk python3 git jq redis

# Debian 계열
apt update && apt install -y openjdk-21-jdk python3 python3-venv git jq redis-tools
```

> `redis` (RHEL) / `redis-tools` (Debian) 는 `redis-cli` 를 포함한다.
> Agent 에서 마스터 Redis 연결 확인 시 사용한다.

---

## 4. 서비스 계정 생성

```bash
useradd -m -s /bin/bash {서비스계정}
```

> `{서비스계정}` 은 Jenkins Agent 전용 계정이다. 조직 정책에 맞는 이름을 사용한다.

---

## 5. Ansible 가상환경 설치

### Python 패키지

```bash
sudo python3 -m venv /opt/ansible-env
sudo /opt/ansible-env/bin/pip install --upgrade pip
sudo /opt/ansible-env/bin/pip install 'ansible>=2.12'  # 검증 기준: ansible 13.4.0 (ansible-core 2.20.3)
sudo /opt/ansible-env/bin/pip install redis            # 검증 기준: 7.3.0 — Ansible fact_caching Redis 백엔드
sudo /opt/ansible-env/bin/pip install pywinrm          # 검증 기준: 0.5.0 — Windows WinRM 연결
sudo /opt/ansible-env/bin/pip install 'pyvmomi>=7.0'   # 검증 기준: 9.0.0 — VMware ESXi API (community.vmware 의존)
sudo /opt/ansible-env/bin/pip install jmespath         # 검증 기준: 1.1.0 — json_query 필터 (JSON 데이터 파싱)
sudo /opt/ansible-env/bin/pip install netaddr          # 검증 기준: 1.3.0 — ipaddr 필터 (IP/서브넷 연산)
sudo /opt/ansible-env/bin/pip install lxml             # 검증 기준: 6.0.2 — VMware 모듈 XML 파싱
sudo /opt/ansible-env/bin/pip install pytest           # 검증 기준: 9.0.2 — E2E regression 게이트 (Jenkins Stage 4)

# 확인
/opt/ansible-env/bin/ansible --version
```

### Python 인터프리터 경로 확인

Agent 서버에 `/usr/bin/python3` 경로로 Python 3.9 이상이 존재해야 한다 (검증 기준 Agent: 3.12.3).
Ansible 커스텀 모듈 실행 시 이 경로를 사용한다.

```bash
# 확인
ls -la /usr/bin/python3

# 없으면 심볼릭 링크 생성
sudo ln -sf $(which python3) /usr/bin/python3
```

대부분의 Linux 배포판(RHEL 8+, Ubuntu 20.04+, Rocky 8+)에서 기본 설치되어 있다.

### Ansible Collection

`pip install ansible` (풀패키지) 설치 시 아래 Collection 은 기본 포함된다.
`ansible-core` 만 설치한 경우 수동 설치가 필요하다.

```bash
# 프로젝트에서 사용하는 Collection (검증 기준 Agent 버전 주석 참고)
sudo /opt/ansible-env/bin/ansible-galaxy collection install community.vmware    # 검증 기준: 6.2.0 — esxi-gather
sudo /opt/ansible-env/bin/ansible-galaxy collection install ansible.windows     # 검증 기준: 3.3.0 — Windows gather
sudo /opt/ansible-env/bin/ansible-galaxy collection install ansible.posix       # 검증 기준: 2.1.0 — Linux (cron, sysctl 등)
sudo /opt/ansible-env/bin/ansible-galaxy collection install community.general   # 검증 기준: 12.4.0 — 범용 (timezone 등)
sudo /opt/ansible-env/bin/ansible-galaxy collection install ansible.utils       # 검증 기준: 6.0.1 — 유틸리티 필터 (ipaddr 등)

# 확인
/opt/ansible-env/bin/ansible-galaxy collection list
```

> `/opt/ansible-env` 는 사용자 계정에 의존하지 않는 시스템 공용 경로다.
> Jenkins Agent 사용자에게 읽기+실행 권한만 있으면 동작한다.

### Vault 패스워드 (Jenkinsfile_portal — 메인 Jenkinsfile 과 동일)

> **2026-06-18 변경**: `Jenkinsfile_portal` 도 메인 `Jenkinsfile` 과 동일하게 Jenkins Credentials Store
> 의 `server-gather-vault-password` (Secret text) 를 사용한다. 이전의 agent 로컬 `VAULT_PASS_FILE` 파일
> 방식 / 임시 하드코딩은 폐기됐다 — **Agent 에 별도 vault 패스워드 파일을 배치할 필요가 없다.**

`Jenkinsfile_portal` 의 Gather 단계는 `withCredentials([string(credentialsId: 'server-gather-vault-password',
variable: 'VAULT_PASSWORD')])` 로 패스워드를 주입받아(콘솔 마스킹), 런타임 임시파일(`mktemp`, chmod 600)에
써서 `--vault-password-file` 로 ansible-playbook 에 넘기고, 빌드 종료 시 `trap` 으로 임시파일을 삭제한다.

- credential 등록 절차: [01_jenkins-setup.md](01_jenkins-setup.md) §7 (`server-gather-vault-password`, Secret text).
  메인 `Jenkinsfile` 이 이미 같은 credential 을 사용하므로, 대개 추가 등록 작업이 필요 없다.
- 패스워드 회전 절차: [21_vault-operations.md](21_vault-operations.md).
- 보안: Credentials Store 가 콘솔 로그에서 패스워드를 마스킹한다. 운영 빌드는 `verbosity=0` 유지 권장
  (`-vv` 이상 시 vault 변수 노출 가능).

---

## 6. /etc/ansible/ansible.cfg 배치

모든 계정에서 동일하게 적용되도록 `/etc/ansible/ansible.cfg` 에 배치한다.

> **ansible.cfg 우선순위**: Ansible은 `ANSIBLE_CONFIG` 환경변수 → CWD의 `ansible.cfg` → `~/.ansible.cfg` → `/etc/ansible/ansible.cfg` 순으로 탐색한다.
> Jenkins 빌드 시 프로젝트 루트의 `ansible.cfg`가 CWD에 위치하므로 아래 시스템 설정보다 우선 적용된다.
> 여기서 설정하는 `/etc/ansible/ansible.cfg`는 프로젝트 외부에서 Ansible을 실행할 때의 기본값이다.

```bash
sudo mkdir -p /etc/ansible

sudo tee /etc/ansible/ansible.cfg > /dev/null << 'EOF'
[defaults]
host_key_checking       = False
bin_ansible_callbacks   = True
retry_files_enabled     = False
gathering               = smart
interpreter_python      = auto
forks                   = 20
timeout                 = 60
deprecation_warnings    = False
fact_caching            = redis
fact_caching_connection = {Jenkins_마스터_IP}:6379:0:{Redis비밀번호}
fact_caching_timeout    = 86400

[inventory]
enable_plugins = script, auto

[ssh_connection]
pipelining = True

[winrm]
transport = ntlm
EOF
```

> `{Jenkins_마스터_IP}`, `{Redis비밀번호}` 는 실제 값으로 교체한 뒤 실행한다.

> **범용 설정 원칙**: 이 파일은 Agent에서 실행하는 모든 프로젝트의 공통 기본값이다.
> Ansible은 ansible.cfg를 병합하지 않고 우선순위 1개만 사용하므로,
> 프로젝트 루트에 `ansible.cfg`가 있으면 이 시스템 설정은 무시된다.
>
> - **프로젝트 루트에 ansible.cfg가 있는 경우**: 해당 설정이 우선 적용된다
>   (예: `stdout_callback`, `gathering`, 커스텀 플러그인 경로 등).
> - **프로젝트 루트에 ansible.cfg가 없는 경우**: 이 시스템 설정이 그대로 적용된다.
>
> `[inventory] enable_plugins = script, auto` — 동적 인벤토리 스크립트(inventory.sh)를
> INI 파서보다 먼저 인식시킨다. 이 설정이 없으면 Python 스크립트가 INI로 파싱되어 실패한다.

---

## 7. 인벤토리 스크립트 실행 권한

Windows 에서 커밋된 `.sh` 파일은 Git 에 실행 권한(100755)이 기록되지 않아
Jenkins checkout 후 Ansible 동적 인벤토리가 동작하지 않는다.

세 채널의 동적 인벤토리 스크립트(`os-gather/inventory.sh`, `esxi-gather/inventory.sh`, `redfish-gather/inventory.sh`)를 새로 추가한 경우,
아래 명령으로 실행 권한을 Git 에 기록한 뒤 커밋한다.

```bash
# 프로젝트 clone 후
git update-index --chmod=+x os-gather/inventory.sh esxi-gather/inventory.sh redfish-gather/inventory.sh
git commit -m "fix: inventory 스크립트 실행 권한 추가"
git push
```

> 한 번 커밋하면 이후 모든 clone / checkout 에서 실행 권한이 유지된다.

---

## 8. Jenkins 노드 등록

경로: Jenkins → Manage Jenkins → Nodes → New Node

### 기본 설정

| 항목 | 값 | 비고 |
|------|-----|------|
| Name | `agent-{loc}-{dev\|ops}` | 예: `agent-ich-ops`, `agent-chj-dev` |
| Description | `{로케이션} {개발\|운영} Agent` | 예: `이천 운영 Agent` |
| Number of executors | `2` | 동시 실행 잡 수. 서버 사양에 따라 조정 |
| Remote root directory | `/home/{서비스계정}/jenkins-agent` | Agent 워크스페이스 경로 |
| Labels | 로케이션 코드 | 아래 표 참조 |
| Usage | `Only build jobs with label expressions matching this node` | 라벨 매칭 잡만 실행 |
| Launch method | `Launch agents via SSH` | 아래 상세 참조 |
| Availability | `Keep this agent online as much as possible` | |

### Labels 설정

Jenkinsfile 의 `agent { label "${params.loc}" }` 기준:

| 슬레이브 노드 | Labels 값 |
|-------------|----------|
| 이천 | `ich` |
| 청주 | `chj` |
| 용인 | `yi` |

### Launch method (SSH)

| 항목 | 값 |
|------|-----|
| Host | Agent 노드 IP |
| Credentials | `{서비스계정}` SSH 계정 (Jenkins Credentials 에 미리 등록) |
| Host Key Verification Strategy | `Non verifying Verification Strategy` |

> SSH Credentials 등록: Jenkins → Manage Jenkins → Credentials → Add Credentials
> Kind: `SSH Username with private key`, Username: `{서비스계정}`, Private Key: 마스터에서 생성한 SSH 키

---

## 9. Node Properties 설정

경로: Jenkins → Manage Jenkins → Nodes → {노드} → Configure → Node Properties

### Environment variables

| Name | Value |
|------|-------|
| `PATH+ANSIBLE` | `/opt/ansible-env/bin` |

> `PATH+ANSIBLE` 은 Jenkins 가 기존 PATH 에 `/opt/ansible-env/bin` 을 **추가**하는 문법이다.
> Jenkinsfile 에서 Ansible 실행 경로를 하드코딩하지 않아도 된다.

### Tool Locations

| Tool | Home |
|------|------|
| Ansible (`ansible`) | `/opt/ansible-env/bin` |

> Jenkins → Manage Jenkins → Tools → Ansible 에서 등록한 경로와 동일해야 한다.
> Agent 에서 실제로 해석되는 값이므로 Agent 의 가상환경 경로와 일치시킨다.

---

## 10. Redis 연결 테스트

[02_redis-install.md](02_redis-install.md) 의 마스터 Redis 설정이 완료된 상태에서 실행합니다.

```bash
# Agent 에서 마스터 Redis 접속 확인
redis-cli -h {Jenkins_마스터_IP} -a {Redis비밀번호} ping
# 기대 응답: PONG

# Ansible fact caching 동작 확인 (json_only 는 본 프로젝트 전용 콜백이므로 default 로 우회)
ANSIBLE_STDOUT_CALLBACK=default /opt/ansible-env/bin/ansible -m setup localhost | head -5
redis-cli -h {Jenkins_마스터_IP} -a {Redis비밀번호} DBSIZE
# 기대 응답: (integer) 1 이상  ← Redis 에 facts 가 저장됨
```

연결이 실패하면 다음을 차례로 확인합니다.

| 점검 항목 | 위치 |
|----------|------|
| 마스터 `bind` 설정에 마스터 실제 IP 가 포함됐는지 | 마스터 `/etc/redis.conf` |
| `requirepass` 설정 및 비밀번호 일치 | 마스터 `/etc/redis.conf` |
| 6379 방화벽 통과 | 마스터 `firewall-cmd` / `ufw` |
| Agent 측 `ansible.cfg` 의 fact_caching_connection | Agent 의 server-exporter 저장소 루트 |

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Jenkins Job 등록 | [04_job-registration.md](04_job-registration.md) |
| Vault 운영 / 패스워드 회전 | [21_vault-operations.md](21_vault-operations.md) |
| Ansible 프로젝트 설정 (ansible.cfg / 환경변수) | [18_ansible-project-config.md](18_ansible-project-config.md) |
