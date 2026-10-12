# 환경 요건

이 문서는 수집을 시도하기 전에 대상 서버, Runner(Jenkins Agent), Jenkins Controller, 네트워크에 무엇이 필요한지 정리합니다. 설치 절차는 [docs/operate/01-jenkins-master.md](docs/operate/01-jenkins-master.md)부터 이어지는 운영 문서에 있습니다.

## 표기 구분

요건은 세 가지로 나눠 적습니다.

| 구분 | 뜻 | 예 |
|---|---|---|
| 필수 | 코드나 공식 의존성에 근거가 있는 요구. 충족하지 않으면 수집이 되지 않습니다 | Runner의 Python 3.12 이상, 대상 Linux의 SSH |
| 확인한 조합 | 사내 검증 환경에서 실제로 실행해 본 버전과 구성. 필수 조건이 아닙니다 | Runner RHEL 9.6, ESXi 7.0.3과 9.0.0 |
| 미확인 | 코드가 막지 않지만 실장비로 확인하지 않은 범위. 지원 불가로 단정하지 않습니다 | ESXi 6.x, 8.x, Supermicro BMC |

요건을 충족하지 못했을 때의 결과는 둘 중 하나입니다. 수집 자체가 실패하면 `status: failed` 봉투가 오고, 일부 정보만 못 읽으면 해당 필드가 `null`이고 `errors[]`에 이유가 남습니다.

약어: BMC는 서버 관리 컨트롤러, iDRAC(Dell), iLO(HPE), XCC(Lenovo), CIMC(Cisco), iBMC(Huawei), iRMC(Fujitsu)는 각 벤더의 BMC 이름입니다. WinRM은 Windows 원격 관리, DMI는 메인보드가 제공하는 시리얼과 UUID 정보입니다.

## 1. 대상 서버

### 1.1 Linux

| 항목 | 구분 | 내용 |
|---|---|---|
| SSH | 필수 | TCP 22. 비밀번호 인증 계정 |
| 셸과 기본 명령 | 필수 | POSIX sh, `awk`, `grep`, `cat`, `uname`. `/proc`, `/sys` 읽기 |
| `ip` (iproute2) | 필수 | 네트워크 수집. 없으면 `ifconfig`로 일부만 읽습니다 |
| `getent` (glibc) | 필수 | 사용자 수집. 없으면 `users`가 `not_supported` |
| `lsblk`, `df` | 필수 | 스토리지 수집. `lsblk -J`가 안 되면 옛 형식으로 한 번 더 시도합니다 |
| Python | 선택 | 대상에 Python 3.9 이상이 있으면 Ansible 모듈 경로, 없거나 낮으면 raw 경로로 수집합니다. 결과 형식은 같습니다 |
| sudo | 선택 | DMI 시리얼과 UUID, `dmidecode` 메모리 슬롯 정보에 필요합니다. 없으면 시리얼과 UUID는 `null`, 메모리는 `/proc/meminfo` 값(`total_basis: os_visible`)으로 채우고 `errors[]`에 남깁니다 |
| `dmidecode`, `lastlog` 또는 `last`, `getenforce`, `systemd-detect-virt`, `lscpu`, `lspci` | 선택 | 있으면 더 채웁니다. 없으면 해당 필드가 `null`입니다 |

vault의 `ansible_become_password`를 따로 두면 sudo에 그 값을 쓰고, 없으면 로그인 비밀번호를 씁니다([docs/operate/05-vault.md](docs/operate/05-vault.md)).

Python 상태별 경로는 `os-gather/tasks/linux/preflight.yml`이 정합니다. 사전 점검은 Python 없이 돌고 `python3`, `python` 순으로 찾아 버전을 봅니다. 어느 경로였는지는 결과의 `diagnosis.details.gather_mode`에 `python_ok`, `python_incompatible`, `python_missing`, `raw_forced` 중 하나로 남습니다.

| 구분 | 배포판 |
|---|---|
| 확인한 조합 | RHEL 8.10 (Python 3.6, raw 경로), RHEL 9.2, RHEL 9.6, RHEL 10.2 (kernel 6.12), Ubuntu 24.04 (kernel 6.8) |
| 미확인 | Rocky, Debian, Ubuntu 20.04와 22.04, SLES, RHEL 7 이하. 같은 경로로 시도하지만 명령 출력 형식을 확인하지 않았습니다 |

### 1.2 Windows

| 항목 | 구분 | 내용 |
|---|---|---|
| WinRM | 필수 | TCP 5986(HTTPS) 또는 5985(HTTP). 5986을 먼저 시도합니다 |
| 인증 | 필수 | NTLM (`ansible.cfg`의 `[winrm] transport = ntlm`). 로컬 또는 도메인 계정 |
| PowerShell | 필수 | `Get-CimInstance`를 쓰므로 PowerShell 3.0 이상 |
| 계정 권한 | 선택 | 관리자 권한이 없으면 디스크 상세, 로컬 사용자 일부, 일부 식별자가 `null`이고 `errors[]`에 남습니다 |

`Get-LocalUser`가 없는 버전은 `Win32_UserAccount`로 대신 읽고, `Get-Volume`이 실패하면 볼륨 정보를 비우고 `errors[]`에 남깁니다.

| 구분 | OS |
|---|---|
| 확인한 조합 | Windows Server 2022 Standard (build 20348) |
| 미확인 | Windows Server 2012 R2, 2016, 2019. 코드가 막지 않습니다 |

### 1.3 ESXi

| 항목 | 구분 | 내용 |
|---|---|---|
| vSphere API | 필수 | TCP 443. ESXi 호스트 주소여야 합니다. vCenter 주소를 주면 자격증명을 보내지 않고 `protocol` 단계에서 멈춥니다 |
| 계정 | 필수 | 호스트 정보를 읽을 수 있는 계정(읽기 권한) |
| 사용하는 모듈 | 필수 | `community.vmware`의 host facts, host config, datastore, DNS, NTP, firewall, service, vmnic, vmhba, vswitch, portgroup 정보 모듈과 이 저장소의 `esxi_disks` 모듈(pyvmomi) |

| 구분 | 버전 |
|---|---|
| 확인한 조합 | ESXi 7.0.3 (Cisco 서버 3대), ESXi 9.0.0 (Dell R760 3대) |
| 미확인 | ESXi 6.x, 8.x. 어댑터(`adapters/esxi/`)는 있고 코드가 막지 않습니다. 무료 라이선스에서의 동작은 확인하지 않았습니다 |

### 1.4 Redfish (BMC)

| 항목 | 구분 | 내용 |
|---|---|---|
| Redfish 서비스 | 필수 | TCP 443. `/redfish/v1/`이 무인증으로 응답해야 제조사를 감지합니다 |
| 인증 | 필수 | Basic 인증. 표준 수집 계정은 전역 vault 한 벌입니다([docs/operate/05-vault.md](docs/operate/05-vault.md)) |
| 계정 권한 | 필수 | Systems, Chassis, Managers, UpdateService 읽기. 표준 계정 복구를 쓰려면 복구 계정에 AccountService 쓰기 권한 |
| Python 외부 라이브러리 | 없음 | `redfish-gather/library/redfish_gather.py`는 표준 라이브러리만 씁니다 |

어댑터가 있는 벤더와 세대, 그리고 확인 상태입니다. 어댑터가 없는 장비도 `redfish_generic` 어댑터로 표준 필드를 수집합니다.

| 벤더 | 어댑터가 있는 세대 | 실장비 확인 |
|---|---|---|
| Dell | iDRAC 8, 9, 10과 벤더 기본 | iDRAC 9: PowerEdge R760 5대(사내 명부), PowerEdge R740 FW 4.00 (2026-03-18) |
| HPE | iLO 4, 5, 6, 7과 벤더 기본. Superdome Flex, Compute Scale-up Server 3200 | iLO 6: ProLiant DL380 Gen11 FW 1.73 (2026-03-18). 사내 명부의 DL380 Gen11은 Runner 망에서 닿지 않습니다. Superdome Flex, CSUS 3200은 합성 fixture만 |
| Lenovo | IMM2, XCC, XCC3와 벤더 기본 | XCC: ThinkSystem SR650 V2 FW 5.70 (2026-03-18), 사내 명부 XCC 1대 |
| Cisco | CIMC(M4 이후), UCS X-Series와 벤더 기본 | CIMC: UCS C220 M4 1대(사내 명부). M5 이후는 미확인 |
| Supermicro | X9, X10, X11, X12, X13, X14, ARS와 벤더 기본 | 미확인 |
| Huawei, Inspur, Fujitsu, Quanta | 벤더별 1개 | 미확인. 벤더 공식 문서와 DMTF 표준으로 작성 |

벤더와 세대별로 어느 섹션이 나오는지는 [docs/reference/compatibility-matrix.md](docs/reference/compatibility-matrix.md), 실장비 검증 기록은 [docs/reference/live-validation.md](docs/reference/live-validation.md)에 있습니다.

### 1.5 `system.hosting_type` (OS 채널)

OS 채널은 서버가 가상 머신인지 물리 서버인지를 `data.system.hosting_type`에 `virtual`, `baremetal`, `unknown`으로 냅니다. 물리 서버 위에서 KVM이나 Hyper-V 호스트 역할을 해도 `baremetal`입니다. ESXi와 Redfish 채널에는 이 필드가 없습니다.

## 2. Runner (Jenkins Agent)

수집은 Runner에서 실행됩니다. 요건의 근거는 `production_manifest.yml`의 `toolchain`과 각 채널이 쓰는 모듈입니다.

| 항목 | 구분 | 내용 |
|---|---|---|
| OS | 필수 | Linux. `bash`, `git`, `flock`, `timeout`, `nproc`, `ping` 명령 |
| Java | 필수 | 설치한 Jenkins 버전이 요구하는 Java. 버전 범위는 Jenkins 공식 문서를 보세요 |
| 시스템 Python | 필수 | `/usr/bin/python3`. 각 채널의 `inventory.sh`가 이 경로로 실행됩니다 |
| Ansible 실행환경(venv) | 필수 | Python 3.12 이상 3.14 미만, ansible-core 2.16 이상 2.21 미만. 위치는 `SE_ANSIBLE_VENV` 또는 `/app/ansible-env`, `/opt/ansible-env` ([docs/operate/02-agent-node.md](docs/operate/02-agent-node.md)) |
| `ansible.windows` 컬렉션 | Windows 수집 시 필수 | `win_shell`, `win_ping` |
| `pywinrm` | Windows 수집 시 필수 | WinRM 연결 |
| `community.vmware` 컬렉션 | ESXi 수집 시 필수 | 1.3절의 정보 모듈 |
| `pyvmomi` | ESXi 수집 시 필수 | `community.vmware`와 `esxi_disks` 모듈 |
| 그 밖의 pip 패키지와 컬렉션 | 불필요 | `jmespath`, `netaddr`, `lxml`, `redis`, `community.windows`, `community.general`은 수집 코드가 쓰지 않습니다 |

사내에서 확인한 Runner 조합(2026-10-12)입니다.

| 항목 | 값 |
|---|---|
| OS | RHEL 9.6 |
| Java | OpenJDK 21.0.10 |
| 시스템 Python | 3.9.21 |
| venv | `/app/ansible-env`: Python 3.12.9, ansible-core 2.20.3 (ansible 13.4.0) |
| 컬렉션 | ansible.windows 3.3.0, community.vmware 6.2.0, ansible.posix 2.1.0, ansible.utils 6.0.1, community.general 12.4.0, community.windows 3.1.0 |
| pip | pywinrm 0.5.0, pyvmomi 9.0.0.0, requests 2.33.1, jmespath 1.1.0, netaddr 1.3.0, lxml 6.0.2 |
| git | 2.47.3 |

Runner 노드에는 실행 위치 라벨(`common/vars/locations.yml`의 `agent_label`)과 수집할 대상 종류의 능력 라벨(`linux`, `windows`, `esxi`, `redfish`)이 있어야 합니다.

## 3. Jenkins Controller

| 항목 | 구분 | 내용 |
|---|---|---|
| Jenkins | 필수 | 파이프라인이 쓰는 플러그인: Pipeline, Git, Credentials Binding, Pipeline Utility Steps, Pipeline: Multibranch(`readTrusted`), HTTP Request. Timestamper는 선택 |
| credential | 필수 | `server-gather-vault-password` (Secret text), 저장소 읽기 credential |
| 결과 확인 실행 위치 | 필수 | 결과 확인 및 전송 단계는 Controller(built-in 노드)에서 실행되므로 built-in 노드에 executor가 1개 이상 있어야 합니다 |
| 확인한 조합 | | Jenkins 2.528.3, Java 21 |

상세는 [docs/operate/01-jenkins-master.md](docs/operate/01-jenkins-master.md)에 있습니다.

## 4. 네트워크 경로

| 방향 | 포트 | 용도 |
|---|---|---|
| 호출자 → Controller | 443 (또는 Jenkins 설정 포트) | Job 호출 |
| Controller → Git 저장소 | 443 또는 22 | `Jenkinsfile_portal`과 변수 파일 읽기 |
| Controller → Runner | 22 (SSH 연결) 또는 Runner → Controller 50000 (inbound 연결) | Agent 연결 |
| Runner → Git 저장소 | 443 또는 22 | 수집 코드 checkout. Add-on을 쓰면 Add-on 저장소도 |
| Runner → Linux 대상 | 22 | SSH |
| Runner → Windows 대상 | 5986 또는 5985 | WinRM |
| Runner → ESXi 대상 | 443 | vSphere API |
| Runner → BMC | 443 | Redfish |
| Controller → Portal | `callbackUrl`의 포트 | 결과 전송 |

사전 진단은 관리 포트 TCP가 응답하지 않을 때만 ICMP Echo를 한 번 보냅니다. ICMP가 막혀 있어도 관리 포트가 응답하면 수집합니다.

## 5. 식별자 수집 (호출자의 교차 매칭용)

호출자가 같은 물리 서버를 OS 결과와 Redfish 결과에서 맞추려면 식별자가 필요합니다.

| 채널 | 필드 | 출처 | 권한 |
|---|---|---|---|
| OS Linux | `system.serial_number`, `system.system_uuid`, `hardware.serial`, `hardware.uuid` | `/sys/class/dmi/id/` | sudo 권장 |
| OS Windows | `system.serial_number`, `system.system_uuid`, `hardware.serial`, `hardware.uuid` | `Win32_BIOS`, `Win32_ComputerSystemProduct` | 관리자 권장 |
| ESXi | `hardware.serial`, `hardware.uuid` | vSphere host facts | 읽기 권한 |
| Redfish | `hardware.serial`, `hardware.uuid` | `ComputerSystem` | BMC 계정 |

- 매칭은 `system_uuid`(또는 `hardware.uuid`)를 먼저 쓰고 `serial_number`를 보조로 씁니다. `hosting_type`이 `virtual`인 OS 결과는 물리 Redfish 결과와 맞추지 않습니다.
- 식별자를 못 읽어도 수집은 실패하지 않습니다. 필드가 `null`이고 `errors[]`의 `detail`에 `cause=insufficient_privilege`(권한 부족) 또는 `cause=identifier_not_available`(출처가 값을 주지 않음)이 남습니다. `status`와 `sections`에는 영향이 없습니다.
- 제조사 자리표시자(`To Be Filled By O.E.M.` 등)와 SMBIOS 공장 기본 UUID는 `null`로 정리합니다.

자세한 수집 경로는 [docs/develop/05-field-mapping.md](docs/develop/05-field-mapping.md)에 있습니다.

## 6. 요약

| 환경 | 상태 |
|---|---|
| Linux RHEL 8, 9, 10과 Ubuntu 24.04, Windows Server 2022, ESXi 7.0.3과 9.0.0, Dell iDRAC 9, HPE iLO 6, Lenovo XCC, Cisco CIMC M4 | 실장비로 확인했습니다 |
| 그 밖의 Linux 배포판, Windows Server 2012 R2부터 2019, ESXi 6.x와 8.x, 다른 BMC 세대, Supermicro, Huawei, Inspur, Fujitsu, Quanta | 코드와 어댑터는 있고 실장비로 확인하지 않았습니다 |
| Redfish 서비스가 꺼진 BMC, vCenter 주소, SSH와 WinRM이 모두 닫힌 서버 | 실패 봉투가 옵니다. 실패 단계는 [docs/contract/04-failure-and-diagnosis.md](docs/contract/04-failure-and-diagnosis.md) |
