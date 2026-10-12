# Runner(Jenkins Agent) 구성

이 문서는 수집을 실제로 실행하는 Runner를 준비하는 운영자를 위한 안내입니다. Runner의 OS 계정과 경로, Ansible 실행환경과 의존성, Jenkins에 Runner를 연결하고 라벨을 붙이는 방법, 연결 확인 순서로 읽습니다.
[01-jenkins-master.md](01-jenkins-master.md)의 Controller 설치가 끝난 상태를 전제합니다.

환경 값은 [01-jenkins-master.md](01-jenkins-master.md) 2절의 기준(확인한 조합, 필수, 선택 또는 미확인)으로 적습니다.

## 1. Runner가 하는 일

Runner는 빌드마다 저장소를 받고(`git`), `scripts/run_gather.sh`가 Ansible 실행환경(venv)을 골라 `ansible-playbook`을 실행합니다. 수집이 끝나면 결과 파일을 Controller로 넘깁니다. 한 Runner가 세 종류(OS, ESXi, Redfish)를 모두 수집할 수 있고, 종류별로 Runner를 나눠도 됩니다.

### 확인한 조합(사내 검증 환경)

| 항목 | 값 |
|---|---|
| OS | Red Hat Enterprise Linux 9.6 |
| Agent OS 계정 | `jenkins` |
| Agent 작업 폴더(remote root) | `/app/jenkins-agent/agent` |
| Java | OpenJDK 21.0.10 (`/app/clovirone-agent-java` 경로를 노드 설정의 JavaPath로 지정) |
| 시스템 `/usr/bin/python3` | 3.9.21 (동적 인벤토리 스크립트 실행용) |
| Ansible 실행환경 | `/app/ansible-env` (Python 3.12.9, ansible-core 2.20.3, ansible 13.4.0) |
| Ansible Collection | community.vmware 6.2.0, ansible.windows 3.3.0 (그 밖에 community.windows, ansible.posix, community.general, ansible.utils도 설치돼 있으나 파이프라인은 쓰지 않습니다) |
| Python 패키지 | pywinrm 0.5.0, pyvmomi 9.0.0, requests 2.33.1, lxml 6.0.2 (jmespath, netaddr, pytest도 설치돼 있으나 수집은 쓰지 않습니다) |
| git | 2.47.3 |
| 연결 방식 | SSH (Controller → Runner 22), credential `master-to-runner-ssh` |
| executor | 15 |
| 라벨 | `git redfish windows linux cj esxi` (3번 Runner만 `cj` 없음) |

## 2. 통신 경로

| 출발 | 목적지 | 포트 | 용도 | 근거 |
|---|---|---|---|---|
| Jenkins Controller | Runner | 22 (TCP) | SSH 방식 Agent 실행. inbound 방식이면 Runner → Controller의 Jenkins 포트와 TCP 50000(또는 설정한 Agent 포트) | 노드 설정 |
| Runner | Git 저장소 | 443 (TCP) | 저장소 checkout | 수집 단계 |
| Runner | Add-on 저장소 | 저장소 주소의 포트 | `ADDON_REPO_URL`을 켰을 때 빌드마다 받습니다 | `scripts/addon_checkout.sh` |
| Runner | Linux 대상 | 22 (TCP) | SSH | `common/library/precheck_bundle.py`의 OS 후보 순서 `5986 → 5985 → 22` |
| Runner | Windows 대상 | 5986, 5985 (TCP) | WinRM. HTTPS를 먼저 시도합니다 | 같은 후보 순서 |
| Runner | ESXi 대상 | 443 (TCP) | vSphere API. ESXi에 SSH는 쓰지 않습니다 | `precheck_bundle.py`의 esxi 포트 `[443]` |
| Runner | BMC | 443 (TCP) | Redfish API | `precheck_bundle.py`의 redfish 포트 `[443]` |
| Runner | 대상 전체 | ICMP Echo | 도달 여부 보조 확인. 선택입니다 | `precheck_bundle.py` |

ICMP는 관문이 아닙니다. 관리 포트 TCP가 아무 응답도 주지 않을 때만 Echo를 한 번 보내 "장비는 켜져 있는데 관리 포트만 막혔다"를 구분합니다. ICMP가 막혀 있어도 수집은 그대로 동작합니다.

Runner에서 Controller 방향으로 열 포트는 SSH 방식에서는 없습니다.

## 3. OS 계정과 경로

필수 사항입니다.

- Agent용 OS 계정 1개. 이 계정으로 Agent 프로세스와 `ansible-playbook`이 실행됩니다.
- Agent 작업 폴더(remote root). 이 계정이 쓸 수 있어야 합니다. 빌드마다 `<remote root>/workspace/<Job 폴더>/<Job 이름>-<빌드 번호>` 작업 폴더가 생깁니다.
- `/tmp`에 쓰기 권한. 수집 실행마다 vault 비밀번호 임시 파일(`/tmp/se_vault.*`, 권한 600)과 SSH 다중화 폴더(`/tmp/se_cp.*`)를 만들고 끝나면 지웁니다.

```bash
# Runner 서버 셸, root 또는 sudo
useradd -m -s /bin/bash <Agent 계정>
mkdir -p <remote root> && chown <Agent 계정>:<Agent 계정> <remote root>
```

사내는 계정 `jenkins`, remote root `/app/jenkins-agent/agent`입니다. 계정 이름과 경로는 조직 방식대로 정해도 됩니다.

## 4. 기본 패키지

| 패키지 | 필수 여부 | 근거 |
|---|---|---|
| Java (Jenkins가 지원하는 버전) | 필수 | Agent 프로세스 실행. Controller와 같은 기준으로 고릅니다([01-jenkins-master.md](01-jenkins-master.md) 4.1절) |
| `git` | 필수 | 수집 단계의 checkout과 Add-on 받기(`scripts/addon_checkout.sh`) |
| `/usr/bin/python3` | 필수 | 세 채널의 동적 인벤토리 `*-gather/inventory.sh`가 이 경로로 실행됩니다(표준 라이브러리만 씁니다). 사내 확인 3.9.21 |
| `bash`, `coreutils`의 `timeout`과 `nproc`, `util-linux`의 `flock` | 필수 | `scripts/run_gather.sh`가 수집 실행 한계와 작업 폴더 잠금에 씁니다 |
| `iputils` (`ping`) | 선택 | ICMP 보조 확인. 없으면 도달 판정이 TCP만으로 돕니다 |

```bash
# RHEL 계열
dnf install -y java-21-openjdk git python3 util-linux coreutils iputils

# Debian 계열
apt update && apt install -y openjdk-21-jre git python3 util-linux coreutils iputils-ping
```

## 5. Ansible 실행환경(venv)

파이프라인은 `scripts/activate_ansible_venv.sh`로 venv를 고릅니다. 순서는 다음과 같고, 못 찾으면 시스템 Python으로 넘어가지 않고 수집이 실패합니다.

1. 노드 환경변수 `SE_ANSIBLE_VENV`에 적힌 venv 루트. 값이 있는데 `bin/activate`가 없으면 다른 경로를 보지 않고 실패합니다.
2. PATH의 `ansible-playbook` 실제 경로 옆에 `activate`가 있는 venv.
3. 알려진 경로 `/app/ansible-env`, 그다음 `/opt/ansible-env`.

| 요구 | 값 | 근거 |
|---|---|---|
| Python | 3.12 이상 3.14 미만 | `production_manifest.yml`의 runtime 범위 |
| ansible-core | 2.16 이상 2.21 미만 | `production_manifest.yml`의 runtime 범위 |
| Collection `community.vmware` | ESXi 수집에 필수 | `esxi-gather/tasks/*.yml`의 `vmware_host_*` 모듈 |
| Collection `ansible.windows` | Windows 수집에 필수 | `os-gather/tasks/windows/*.yml`의 `win_shell`, `win_ping` |
| Python 패키지 `pywinrm` | Windows 수집에 필수 | Ansible WinRM 연결 |
| Python 패키지 `pyvmomi` | ESXi 수집에 필수 | `community.vmware`와 `esxi-gather/library/esxi_disks.py` |

Redfish 수집은 표준 라이브러리만 씁니다. Linux 수집도 추가 패키지가 없습니다.

```bash
# Runner 서버 셸, root 또는 sudo. 경로는 예시이며 조직 방식대로 바꿔도 됩니다
VENV=/app/ansible-env
python3.12 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install 'ansible-core>=2.16,<2.21' pywinrm pyvmomi
"$VENV/bin/ansible-galaxy" collection install community.vmware ansible.windows

# 확인 (Agent 계정으로)
"$VENV/bin/ansible" --version
"$VENV/bin/ansible-galaxy" collection list | grep -E 'community.vmware|ansible.windows'
```

사내는 `ansible` 풀 패키지(13.4.0)를 설치해 위 두 Collection과 함께 다른 Collection도 들어 있습니다. 풀 패키지를 설치해도 되고, 위처럼 필요한 것만 설치해도 됩니다.

venv를 알려진 경로 밖에 두면 노드 설정의 환경변수 `SE_ANSIBLE_VENV`에 그 루트를 적으세요(7절).

## 6. Jenkins에 Runner 등록

경로: Manage Jenkins → Nodes → New Node → Permanent Agent

| 항목 | 값 | 비고 |
|---|---|---|
| Name | Runner 이름 (예: `agent-ic-01`) | 수집을 시작한 뒤 연결이 끊기면 파이프라인은 이 이름의 Runner가 돌아오기를 기다려 같은 작업 폴더에서 이어서 수집합니다. 빌드가 기다리는 중에는 이름, 라벨, remote root를 바꾸지 마세요 |
| Remote root directory | 3절의 remote root | |
| Labels | 7절의 Location 라벨과 능력 라벨 | 공백으로 구분 |
| Usage | `Only build jobs with label expressions matching this node` | 선택. 사내 설정 |
| Launch method | `Launch agents via SSH` (사내 방식) | Host는 Runner 주소, Credentials는 SSH Username with private key, Host Key Verification Strategy는 조직 정책대로. 사내는 Manually trusted key Verification Strategy에 첫 연결 수동 승인 없음 |
| JavaPath (SSH 방식의 Advanced) | Runner의 java 경로 | 비우면 PATH의 java를 씁니다. 사내는 `/app/clovirone-agent-java` |
| Number of executors | 동시에 실행할 빌드 수 | 선택. 사내 15 |
| Availability | `Keep this agent online as much as possible` | |

inbound(JNLP) 방식으로 연결해도 파이프라인은 같습니다. 사내에서는 확인하지 않았습니다.

## 7. 라벨과 노드 환경변수

파이프라인은 `common/vars/locations.yml`의 `agent_label`(Location 라벨)과 `target_type`의 능력 라벨을 `&&`로 이어 Runner를 고릅니다. 두 라벨을 모두 가진 Runner가 하나도 등록돼 있지 않으면 실행 위치 확인 단계가 설정 오류로 실패합니다. 등록돼 있으면 연결이 끊겨 있거나 바빠도 수집 단계가 기다립니다.

| Location (`loc` 값) | 라벨 |
|---|---|
| `ic` | `ic` |
| `cj` | `cj` |
| `yi` | `yi` |
| `git` (사내 검증) | `git` |

| `target_type` | Runner에 있어야 하는 능력 라벨 |
|---|---|
| `os` | `linux`와 `windows` 둘 다. 한 요청에 Linux와 Windows가 섞일 수 있습니다 |
| `esxi` | `esxi` |
| `redfish` | `redfish` |

예를 들어 이천에서 세 종류를 모두 수집하는 Runner의 Labels는 `ic linux windows esxi redfish`입니다. Location을 추가하려면 `common/vars/locations.yml`에 키와 `agent_label`을 추가하고, 그 Location의 vault 파일을 만들고, 그 라벨을 가진 Runner를 등록합니다([05-vault.md](05-vault.md)).

노드 환경변수(Node Properties → Environment variables)는 다음 두 가지만 씁니다. 둘 다 선택입니다.

| 이름 | 값 | 언제 |
|---|---|---|
| `SE_ANSIBLE_VENV` | venv 루트 | venv가 `/app/ansible-env`, `/opt/ansible-env`가 아니고 PATH로도 찾을 수 없을 때 |
| `SE_FORKS_CAP_OS` | 정수 | OS 수집의 동시 실행 수 상한을 기본값(50)과 다르게 둘 때 |

Add-on 관련 값은 노드에 두지 않습니다. 전역 환경변수 하나로 켭니다([03-job-registration.md](03-job-registration.md) 4절).

## 8. 연결 확인

1. Manage Jenkins → Nodes에서 Runner가 online인지 확인하세요. SSH 방식은 노드의 Log 화면에 `Agent successfully connected and online`이 나옵니다.
2. Runner 서버 셸에서 Agent 계정으로 저장소 접근과 venv를 확인하세요.

```bash
# Runner 서버 셸, Agent 계정
git ls-remote <저장소 URL> refs/heads/main
git clone --depth 1 <저장소 URL> /tmp/se-check && cd /tmp/se-check
. scripts/activate_ansible_venv.sh && ansible --version
cd / && rm -rf /tmp/se-check
```

`[venv] <경로> python=<버전> (source=env|path|known)` 한 줄이 나오면 파이프라인도 같은 venv를 씁니다.

3. 대상 포트는 빌드마다 사전 진단이 판정합니다. 미리 보려면 Runner에서 `timeout 3 bash -c '</dev/tcp/<대상 IP>/443' && echo open`처럼 확인하세요.
4. 첫 수집 실행과 결과 확인은 [03-job-registration.md](03-job-registration.md) 5절을 따르세요.

## 9. Runner 임시 폴더 정리

수집 단계의 마지막 보존이 결과를 빌드에 보관했다고 확인하면 그 빌드의 작업 폴더를 바로 지웁니다. 남은 작업 폴더는 같은 Runner에서 하루에 한 번 `scripts/workspace_cleanup.py`가 정리합니다. 운영자가 따로 cron을 둘 필요가 없습니다.

- 대상은 같은 Job의 `<Job 이름>-<빌드 번호>` 폴더이고, 소유 기록(`.se_workspace.json`)이 그 Job과 번호를 가리킬 때만 봅니다.
- 끝난 지 7일이 지난 폴더 가운데 결과를 보관한 폴더와 결과 파일이 없는 폴더는 통째로 지웁니다.
- 결과를 보관하지 못한 폴더는 결과 파일(`gather_*`, `callback_body.json`, `finalize_summary.json`, `gather_auth_evidence/`)만 남기고 저장소 사본과 Add-on 사본을 지웁니다. 남긴 목록은 `.se_kept_results.json`에 적고 콘솔 `[작업 폴더 정리]` 줄로 알립니다. 사람이 확인한 뒤 지우세요.
- 실행 중일 수 있는 폴더(끝 기록이 없고 시작 뒤 83시간 이내)와 다른 Job의 폴더는 건드리지 않습니다.

수집 셸이 끝 처리 없이 강제 종료되고 같은 작업 폴더에서 이어서 하는 시도가 없으면 `/tmp/se_vault.*`와 `/tmp/se_cp.*`가 남을 수 있습니다. 이어서 하는 시도가 있으면 그 시도가 지웁니다. 남은 것은 Agent 계정이 지워도 됩니다.

## 자주 막히는 곳

| 증상 | 원인과 조치 |
|---|---|
| 콘솔 `[venv] Ansible 실행환경(venv)을 찾지 못했습니다.` | 5절의 세 경로 어디에도 venv가 없습니다. `SE_ANSIBLE_VENV`를 등록하거나 알려진 경로에 설치하세요 |
| `[실행 위치] 라벨 '...'에 해당하는 Runner가 Jenkins에 등록돼 있지 않습니다.` | 7절의 Location 라벨과 능력 라벨을 모두 가진 Runner가 없습니다 |
| 수집 단계가 `[실행 대기] 수집을 실행할 Runner를 기다립니다.`를 반복 | Runner가 offline이거나 executor가 모두 사용 중입니다. 노드 상태와 Log 화면을 보세요. 최대 72시간 기다린 뒤 실패 결과를 보냅니다 |
| `git: command not found` | Runner에 git이 없습니다. 4절 |
| Windows 대상만 실패하고 콘솔에 `winrm` 모듈 오류 | venv에 `pywinrm`이 없습니다. 5절 |
| ESXi 대상만 실패하고 `pyvmomi` 또는 `community.vmware` 오류 | venv에 `pyvmomi`나 Collection이 없습니다. 5절 |
