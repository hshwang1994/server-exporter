# 03. Agent 노드 구성

> **이 문서는** Jenkins Agent 노드(실제로 ansible-playbook 이 실행되는 머신) 를 새로 구축할 때 따라가는 단계별 가이드입니다.
> VM 사양 산정 → OS 패키지 → Python venv → Ansible / pywinrm / pyvmomi 설치 → Jenkins 마스터 등록까지 한 번에 다룹니다.
>
> **언제 이 문서를 보는가?**
> - 새 사이트 (이천 / 청주 / 용인 등) 에 Agent 를 처음 구축할 때
> - 기존 Agent 가 노후화 / 장애로 재구축이 필요할 때
> - ansible / 컬렉션을 업그레이드해야 할 때

> **사전 준비**
> - 본 절차 전에 [01-jenkins-master.md](01-jenkins-master.md) (마스터 설치) 를 먼저 끝내야 합니다.

> [!NOTE]
> **Redis 는 쓰지 않는다.** 프로젝트 `ansible.cfg` 는 `gathering = explicit` 이고 `fact_caching` 이 없다. Ansible 은 설정 파일을
> 병합하지 않고 가장 먼저 찾은 하나만 읽으며, Jenkins 빌드에서는 그것이 저장소 루트의 `ansible.cfg` 다. 그래서 Agent 공통
> `/etc/ansible/ansible.cfg` 에 fact 캐시를 적어도 이 파이프라인에는 적용되지 않는다. Redis 서버 · 클라이언트 · 6379 포트 개방은
> 필요 없다 (2026-10-10 정정 — 이전 판은 Redis 설치 · 연결 시험 · 방화벽 행을 두고 있었다).
> - Agent 노드는 마스터와 같은 사내망에 있어야 한다. 필요한 연결은 2절 표가 전부다. 마스터가 SSH 로 Agent 에 접속하므로
>   Agent → 마스터 방향 포트는 열지 않아도 된다.

> **검증 기준 환경 (참고)**: Ubuntu 24.04, Python 3.12, ansible-core 2.20, Java 21 (10.100.64.154 에서 2026-03-27 확인)

Jenkins Agent 는 로케이션 (이천 / 청주 / 용인) 별로 구성하며 개발 / 운영 마스터에는 각각 다른 Agent 를 연결합니다.
각 Agent 노드마다 아래 절차를 반복합니다.

---

## 1. VM 리소스 산정

### Jenkins 마스터

| 항목 | 사양 |
|------|------|
| CPU | 8 core |
| RAM | 32 GB (Jenkins 16 GB + 여유) |
| Disk | 500 GB (빌드 로그, 히스토리 누적 고려) |

### Jenkins Agent

| 항목 | 사양 |
|------|------|
| CPU | 8 core |
| RAM | 16 GB |
| Disk | 100 GB (Ansible 가상환경 + workspace) |

---

## 2. 방화벽 오픈 목록

| 출발 | 목적지 | 포트 | 프로토콜 | 용도 | 근거 |
|------|--------|------|----------|------|------|
| 포털 | Jenkins 마스터 | Jenkins URL 의 포트 (기본 8080, HTTPS 구성이면 443) | TCP | Job 트리거 (REST) | [01-jenkins-master.md](01-jenkins-master.md) 5절 |
| Jenkins 마스터 | Git 서버 (GitHub / GitLab) | 443 | TCP | Pipeline 정의(lightweight) 와 실행 위치 확인의 `readTrusted`(`common/vars/locations.yml`) — 마스터에서 저장소 전체를 받지 않는다 | `Jenkinsfile_portal` Resolve Location |
| Jenkins 마스터 | Agent | 22 | TCP | Launch agents via SSH (8절). 원격 채널이 이 연결 위에서 동작한다 | 노드 설정 |
| Jenkins 마스터 | 포털 | `callbackUrl` 의 포트 | TCP | 결과 전송 `httpRequest` POST — Agent 가 아니라 built-in 노드가 보낸다 | `Jenkinsfile_portal` seCallback |
| Agent | Git 서버 (GitHub / GitLab) | 443 | TCP | 수집 단계 첫 시도의 저장소 checkout | `Jenkinsfile_portal` Gather |
| Agent | Add-on 저장소 | 저장소 URL 의 포트 (보통 443) | TCP | 전역 환경변수 `ADDON_REPO_URL` 을 켰을 때만, 빌드마다 받는다 | `scripts/addon_checkout.sh` |
| Agent | 대상 서버 Linux | 22 | TCP | SSH | `precheck_bundle.py` os 후보 `5986 → 5985 → 22` |
| Agent | 대상 서버 Windows | 5986 / 5985 | TCP | WinRM — HTTPS 먼저, 다음 HTTP | 같은 후보 순서 |
| Agent | 대상 서버 ESXi | 443 | TCP | vSphere API (`community.vmware`). ESXi 에 SSH 22 는 쓰지 않는다 | `precheck_bundle.py` esxi `[443]` |
| Agent | 대상 BMC | 443 | TCP | Redfish API | `precheck_bundle.py` redfish `[443]` |
| Agent | 대상 서버 전체 | — | ICMP Echo | 도달성 보조 확인 (선택) | `precheck_bundle.py` `_icmp_command` |

> 2026-10-10 정정: 이전 판은 ESXi 를 22 로, Agent → 마스터 6379(Redis) 를 필수로 적고 마스터 → 포털(결과 전송) · Agent → Git 저장소 ·
> Add-on 저장소 행이 없었다. 위 표는 사전 진단의 기본 포트(`CHANNEL_DEFAULT_PORTS`)와 `Jenkinsfile_portal` 의 실제 호출 위치에서 옮겼다.
>
> ICMP 는 **선택**이다. 열려 있으면 관리 포트 TCP 가 방화벽에서 조용히 버려지는 구간에서
> "장비는 살아 있고 관리 포트만 막혔다" 를 구분해 준다 (실패가 `reachable` 이 아니라 `port`
> 단계가 되고, 안내 문장도 방화벽·관리 서비스를 가리킨다). 막혀 있어도 수집은 종전대로
> 동작한다 — ICMP 는 관문이 아니라 보조 근거다.

---

## 3. 기본 패키지 설치

```bash
# RHEL 계열
yum install -y java-21-openjdk python3 git jq iputils

# Debian 계열
apt update && apt install -y openjdk-21-jdk python3 python3-venv git jq iputils-ping
```

> `iputils` / `iputils-ping` 은 도달성 보조 확인용 `ping` 이다. 사전 진단이 관리 포트 TCP 로
> 아무 응답도 못 받았을 때만 Echo 를 1회 보낸다. 서비스 계정(비특권)으로 아래가 되면 준비 완료다.
>
> ```bash
> sudo -u {서비스계정} ping -c 1 -n -W 1 -w 1 <대상IP>; echo "rc=$?"
> ```
>
> 없거나 권한이 부족해도 수집은 그대로 동작한다 — 도달 판정이 종전처럼 TCP 전용이 되고,
> 그 사실이 결과의 `errors[].detail` 에 `icmp: 확인 불가 ...` 로 남는다.

---

## 4. 서비스 계정 생성

```bash
useradd -m -s /bin/bash {서비스계정}
```

> `{서비스계정}` 은 Jenkins Agent 전용 계정이다. 조직 정책에 맞는 이름을 사용한다.

---

## 5. Ansible 가상환경 설치

venv 위치는 설치 방식에 따라 다르다. 파이프라인은 어느 쪽이든 그대로 찾는다.

| 설치 방식 | venv 루트 | 비고 |
|---|---|---|
| 설치 자동화 `install-jenkins-runner` (RHEL 9, Agent 계정 `jenkins`) | `/app/ansible-env` | `/usr/local/bin/ansible-*` 이 venv 로 가는 링크로 함께 생긴다 |
| 이 문서대로 직접 구축 | `/opt/ansible-env` | 아래 절차 |
| 그 밖의 경로 | 임의 | 노드 환경변수 `SE_ANSIBLE_VENV=<venv 루트>` 를 등록한다 (9절) |

> 파이프라인의 Gather 는 저장소의 `scripts/activate_ansible_venv.sh` 를 source 한다.
> 이 스크립트가 `SE_ANSIBLE_VENV` → PATH 의 `ansible-playbook` 이 가리키는 venv → 위 두 경로 순으로 찾고,
> 못 찾으면 시스템 python 으로 넘어가지 않고 Stage 를 실패시킨다.

### Python 패키지

```bash
VENV=/opt/ansible-env   # 직접 구축 기준. 설치 자동화 Runner 는 /app/ansible-env
sudo python3 -m venv $VENV
sudo $VENV/bin/pip install --upgrade pip
sudo $VENV/bin/pip install 'ansible>=2.12'  # 검증 기준: ansible 13.4.0 (ansible-core 2.20.3)
sudo $VENV/bin/pip install pywinrm          # 검증 기준: 0.5.0 — Windows WinRM 연결
sudo $VENV/bin/pip install 'pyvmomi>=7.0'   # 검증 기준: 9.0.0 — VMware ESXi API (community.vmware 의존)
sudo $VENV/bin/pip install jmespath         # 검증 기준: 1.1.0 — json_query 필터 (JSON 데이터 파싱)
sudo $VENV/bin/pip install netaddr          # 검증 기준: 1.3.0 — ipaddr 필터 (IP/서브넷 연산)
sudo $VENV/bin/pip install lxml             # 검증 기준: 6.0.2 — VMware 모듈 XML 파싱
sudo $VENV/bin/pip install pytest           # 검증 기준: 9.0.2 — main 전용 CI Job(`Jenkinsfile_ci`)의 `scripts/ai/ci_gate.sh` 가 Runner 에서 돈다. 수집 Job 은 쓰지 않는다

# 확인
$VENV/bin/ansible --version
```

### Python 인터프리터 경로 확인

Agent 서버에 `/usr/bin/python3` 경로로 Python 3.9 이상이 존재해야 한다 (검증 기준 Agent: 3.12.3).
동적 인벤토리 `*-gather/inventory.sh` 가 이 경로로 실행된다 (표준 라이브러리만 쓴다). 수집 모듈은 venv 의 python 을 쓴다.

```bash
# 확인
ls -la /usr/bin/python3

# 없으면 심볼릭 링크 생성
sudo ln -sf $(which python3) /usr/bin/python3
```

대부분의 Linux 배포판(RHEL 8+, Ubuntu 20.04+, Rocky 8+)에는 기본으로 들어 있다.

### Ansible Collection

`pip install ansible` (풀패키지) 로 설치하면 아래 Collection 이 기본으로 포함된다.
`ansible-core` 만 설치했다면 직접 설치해야 한다.

```bash
# 프로젝트에서 사용하는 Collection (검증 기준 Agent 버전 주석 참고)
sudo $VENV/bin/ansible-galaxy collection install community.vmware    # 검증 기준: 6.2.0 — esxi-gather
sudo $VENV/bin/ansible-galaxy collection install ansible.windows     # 검증 기준: 3.3.0 — Windows gather
sudo $VENV/bin/ansible-galaxy collection install ansible.posix       # 검증 기준: 2.1.0 — Linux (cron, sysctl 등)
sudo $VENV/bin/ansible-galaxy collection install community.general   # 검증 기준: 12.4.0 — 범용 (timezone 등)
sudo $VENV/bin/ansible-galaxy collection install ansible.utils       # 검증 기준: 6.0.1 — 유틸리티 필터 (ipaddr 등)

# 확인
$VENV/bin/ansible-galaxy collection list
```

> venv 는 사용자 계정에 의존하지 않는 시스템 공용 경로에 둔다. Jenkins Agent 사용자에게 읽기+실행 권한만 있으면 동작한다.

### Vault 패스워드 (Jenkinsfile_portal — 메인 Jenkinsfile 과 동일)

> **2026-06-18 변경**: `Jenkinsfile_portal` 도 메인 `Jenkinsfile` 과 동일하게 Jenkins Credentials Store
> 의 `server-gather-vault-password` (Secret text) 를 사용한다. 이전의 agent 로컬 `VAULT_PASS_FILE` 파일
> 방식 / 임시 하드코딩은 폐기됐다 — **Agent 에 별도 vault 패스워드 파일을 배치할 필요가 없다.**

`Jenkinsfile_portal` 의 Gather 단계는 `withCredentials([string(credentialsId: 'server-gather-vault-password',
variable: 'VAULT_PASSWORD')])` 로 패스워드를 주입받는다(콘솔 마스킹). 이를 런타임 임시파일(`mktemp`, chmod 600)에
써서 `--vault-password-file` 로 ansible-playbook 에 넘기고 빌드가 끝나면 `trap` 으로 임시파일을 삭제한다.

- credential 등록 절차: [01-jenkins-master.md](01-jenkins-master.md) §7 (`server-gather-vault-password`, Secret text).
  메인 `Jenkinsfile` 이 이미 같은 credential 을 쓰므로 추가 등록은 대개 필요 없다.
- 패스워드 회전 절차: [05-vault.md](05-vault.md).
- 보안: Credentials Store 가 콘솔 로그에서 패스워드를 마스킹한다. 운영 빌드는 `verbosity=0` 유지 권장
  (`-vv` 이상 시 vault 변수 노출 가능).

---

## 6. /etc/ansible/ansible.cfg 배치

모든 계정에서 동일하게 적용되도록 `/etc/ansible/ansible.cfg` 에 배치한다.

> **ansible.cfg 우선순위**: Ansible은 `ANSIBLE_CONFIG` 환경변수 → CWD의 `ansible.cfg` → `~/.ansible.cfg` → `/etc/ansible/ansible.cfg` 순으로 탐색한다.
> Jenkins 빌드에서는 프로젝트 루트의 `ansible.cfg`가 CWD에 있으므로 아래 시스템 설정보다 우선 적용된다.
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

[inventory]
enable_plugins = script, auto

[ssh_connection]
pipelining = True

[winrm]
transport = ntlm
EOF
```

> **범용 설정 원칙**: 이 파일은 Agent에서 실행하는 모든 프로젝트의 공통 기본값이다.
> Ansible은 ansible.cfg를 병합하지 않고 우선순위 1개만 쓰므로
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

세 채널의 동적 인벤토리 스크립트(`os-gather/inventory.sh`, `esxi-gather/inventory.sh`, `redfish-gather/inventory.sh`)를 새로 추가했다면
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
| Name | `agent-{loc}-{dev\|ops}` | 예: `agent-ic-ops`, `agent-cj-dev` |
| Description | `{로케이션} {개발\|운영} Agent` | 예: `이천 운영 Agent` |
| Number of executors | `2` | 동시 실행 잡 수. 서버 사양에 따라 조정 |
| Remote root directory | `/home/{서비스계정}/jenkins-agent` | Agent 워크스페이스 경로. 설치 자동화 Runner 는 계정 `jenkins` · `/app/jenkins-agent/agent` |
| Labels | 로케이션 코드 + 이 노드가 수집할 target_type 의 능력 라벨 | 아래 표 참조 |
| Usage | `Only build jobs with label expressions matching this node` | 라벨 매칭 잡만 실행 |
| Launch method | `Launch agents via SSH` | 아래 상세 참조 |
| Availability | `Keep this agent online as much as possible` | |

### Labels 설정

`Jenkinsfile_portal` 은 `common/vars/locations.yml` 의 `agent_label`(Location 라벨)과 `target_type` 의 능력 라벨을 `&&` 로 이어
노드를 고른다. 두 종류를 모두 가진 노드가 Jenkins 에 **하나도 등록돼 있지 않으면** 실행 위치 확인이 설정 오류로 FAILURE 다(접수된 대상마다 실패 결과는
보낸다). 등록돼 있으면 지금 연결이 끊겼거나 executor 가 모두 사용 중이어도 수집 단계가 Jenkins queue 로 기다린다 — executor 를 잡지 않고 빌드 하나의
실행 기반 대기 합 최대 72시간(2026-10-06 9차, [04-pipeline-runtime.md](04-pipeline-runtime.md) "실행 기반 대기와 같은 Runner 재개").
수집을 시작한 뒤 연결이 끊기면 **그 노드**가 돌아오기를 기다려 같은 작업 폴더에서 끝나지 않은 대상만 이어서 수집한다 — 노드를 지우거나 이름을 바꾸면
그 빌드는 이어 가지 못한다(`resume_impossible`). 빌드가 기다리는 중에는 노드의 라벨 · 작업 폴더 위치를 바꾸지 않는다.

| Location | Labels 값 |
|-------------|----------|
| 이천 | `ic` |
| 청주 | `cj` (2026-10-04 까지 `chj`) |
| 용인 | `yi` |
| 사내 테스트 | `git` |

| target_type | 노드에 있어야 하는 능력 라벨 | 뜻 |
|---|---|---|
| `os` | `linux` 와 `windows` 둘 다 | 한 요청에 Linux · Windows 서버가 섞이므로 SSH 와 WinRM 수집이 모두 돼야 한다 |
| `esxi` | `esxi` | vSphere API(443)로 ESXi 에 붙는다 |
| `redfish` | `redfish` | BMC 망의 Redfish API(443)에 붙는다 |

예: 이천에서 세 종류를 모두 수집하는 노드의 Labels 는 `ic linux windows esxi redfish` 다. 능력 라벨이 없는 노드에는 수집이 배정되지 않는다.

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

### Environment variables (선택)

수집 파이프라인은 venv 를 `scripts/activate_ansible_venv.sh` 로 찾으므로 5절의 두 경로 중 하나에 venv 가 있으면
노드 환경변수가 필요 없다. 다른 경로를 썼을 때만 등록한다.

| Name | Value | 언제 |
|------|-------|------|
| `SE_ANSIBLE_VENV` | venv 루트 (예: `/data/ansible-env`) | venv 가 `/app/ansible-env` · `/opt/ansible-env` 가 아닐 때. 값이 있는데 그 안에 `bin/activate` 가 없으면 다른 경로로 넘어가지 않고 실패한다 |
| `PATH+ANSIBLE` | venv 의 `bin` (예: `/opt/ansible-env/bin`) | 선택. Jenkins 가 기존 PATH 앞에 **추가**하는 문법이라 PATH 의 `ansible-playbook` 으로도 venv 를 찾게 된다 |

고객별 추가 수집(Add-on)은 노드 설정이 필요 없다 — Jenkins 전역 환경변수 `ADDON_REPO_URL` 하나로 켜고, 파이프라인이
빌드마다 저장소를 받아 간다 ([03-job-registration.md](03-job-registration.md) Add-on 절). 노드에 `ADDON_DIR` 을 두지 않는다.

### Tool Locations

| Tool | Home |
|------|------|
| Ansible (`ansible`) | Agent 의 venv `bin` (설치 자동화 Runner `/app/ansible-env/bin`, 직접 구축 `/opt/ansible-env/bin`) |

> `ansiblePlaybook()` 스텝을 쓰는 파이프라인용이다. Jenkins → Manage Jenkins → Tools → Ansible 의 전역 값과
> 다른 노드는 여기서 덮는다. 수집 파이프라인 `Jenkinsfile_portal` 은 이 값을 보지 않는다.

---

## 10. 연결 확인

노드를 등록한 뒤 Agent 서비스 계정으로 아래를 확인한다. 2절 표의 연결이 전부다.

```bash
# 1) 마스터 → Agent: Jenkins → Nodes 에서 노드가 online 인가 (SSH 접속 · Java 실행이 됐다는 뜻)

# 2) Agent → Git 서버: Job 에 등록된 저장소 URL 로 (자격이 필요하면 Job credential 과 같은 것으로)
git ls-remote <저장소 URL> refs/heads/main

# 3) venv: 파이프라인이 쓰는 선택 스크립트 그대로 (저장소 clone 안에서)
. scripts/activate_ansible_venv.sh && ansible --version && ansible-galaxy collection list | grep -E 'community.vmware|ansible.windows'

# 4) 대상 서버 포트: 사전 진단이 빌드마다 판정한다 — 결과의 diagnosis.details.checked_ports 를 본다. 미리 확인하려면
#    (bash 내장) timeout 3 bash -c '</dev/tcp/<대상IP>/443' && echo open

# 5) ICMP 보조 확인 (선택, 3절) — 없어도 수집은 동작한다
```

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| Jenkins Job 등록 | [03-job-registration.md](03-job-registration.md) |
| Vault 운영 / 패스워드 회전 | [05-vault.md](05-vault.md) |
| Ansible 프로젝트 설정 (ansible.cfg / 환경변수) | [08-ansible-config.md](08-ansible-config.md) |
