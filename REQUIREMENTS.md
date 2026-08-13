# REQUIREMENTS — Server Exporter 환경 요건

> **이 문서를 보는 이유**
> 수집을 시도하기 전에 "내 환경에서 정말 동작할까?" 를 빠르게 확인하기 위함이다.
> **대상 서버 / Jenkins Agent / 네트워크** 세 측면에서 무엇이 필요한지 표로 정리한다.

## 표를 읽는 법

각 절의 표는 다음 3가지 정보를 한 줄에 담는다.

| 컬럼 | 의미 |
|------|------|
| 최소 요구사항 | 이 값보다 낮으면 수집이 실패하거나 일부 필드가 `null` |
| 검증 기준 (선택 컬럼) | 프로젝트 측이 실제로 검증한 환경 — "권장 운영" 의 의미 |
| 미충족 시 동작 | 위반했을 때 호출자가 받게 될 결과 |

"미충족 시 동작" 은 보통 두 가지 중 하나다.

1. **수집 자체 실패** — envelope `status: failed`. 호출자는 errors[] 만 받고 data 는 비어 있음.
2. **부분 미수집** — 수집은 성공하지만 해당 필드가 `null`. 호출자는 다른 필드는 정상 사용 가능.

## 약어 풀이

| 약어 | 풀이 |
|------|------|
| BMC | Baseboard Management Controller (서버 관리 컨트롤러) |
| iDRAC | Dell 의 BMC 브랜드 |
| iLO | HPE 의 BMC 브랜드 |
| XCC | Lenovo XClarity Controller |
| CIMC | Cisco Integrated Management Controller |
| WinRM | Windows Remote Management |
| WMI / CIM | Windows Management Instrumentation / Common Information Model |
| DMI | Desktop Management Interface (메인보드 시리얼 / UUID 등) |
| DMTF | Distributed Management Task Force (Redfish 표준 단체) |

---

## 함께 읽으면 좋은 문서

- 설치 절차: [docs/operate/01-jenkins-master.md](docs/operate/01-jenkins-master.md) (Jenkins 마스터) / [docs/operate/02-agent-node.md](docs/operate/02-agent-node.md) (Agent 노드)
- 호출자 입력 형식: [docs/contract/01-input.md](docs/contract/01-input.md)
- 호출자 출력 형식: [docs/contract/02-output-envelope.md](docs/contract/02-output-envelope.md)

---

## 1. os-gather (Linux / Windows)

### 1-1. Linux 대상 서버

| 항목 | 최소 요구사항 | 미충족 시 동작 |
|------|-------------|--------------|
| **SSH 포트** | 22 오픈 | 연결 실패 → `status: failed` |
| **Python** | **3.9 이상** | 모듈 실행 실패 → 수집 불가 |
| **배포판** | 아래 참조 | 구버전은 제한 지원 또는 미지원 |
| **계정 권한** | **sudo(become) 권한 권장** | 권한 없으면 serial_number, system_uuid 등 DMI 정보 `null` 반환 |
| **커널** | 2.6.32+ | `ip` 명령 없으면 `/proc/net` fallback |
| **ip 명령** | `iproute2` 패키지 (`ip addr`) | 네트워크 수집 실패 가능 |
| **lsblk** | util-linux 2.19+ | 없으면 `df` fallback (물리 디스크 정보 제한) |
| **getent** | glibc 포함 (기본 설치) | users 수집 실패 |
| **lastlog / last** | shadow-utils (기본 설치) | `last_access_time` → `null` 반환 |
| **Python3 경로** | `/usr/bin/python3` (3.9 이상) 또는 `/usr/bin/python3.9` | `ansible_python_interpreter`로 경로 지정 가능 |

> **타겟 서버 Python 기준:**
> - ansible-core 2.20은 타겟 서버 Python 3.9 이상을 요구한다.
> - RHEL 8 기본 Python은 3.6이므로 미지원. `sudo yum install python39` 후 사용.
> - RHEL 9+, Ubuntu 22.04+는 기본 Python이 3.9 이상이므로 별도 조치 불필요.
> - `ansible_python_interpreter`로 경로 지정 가능 (`/usr/bin/python3.9` 등).

> **계정 권한 기준:**
> - 모든 섹션을 수집하려면 sudo(become) 권한이 있는 계정을 사용해야 한다.
> - sudo 없이도 기본 수집(hostname, OS, CPU, memory, network)은 가능하다.
> - serial_number, system_uuid 등 DMI 정보는 `/sys/class/dmi/id/` 읽기 권한이 필요하며 일반 사용자는 접근 불가한 경우가 많다.
> - 권한 부족 시 해당 필드는 `null`로 반환되며 수집 자체는 실패하지 않는다 (non-fatal).
> - vault에 `become_password`를 포함하면 자동으로 sudo 권한 사용.

> **미지원**: Python 3.8 이하 (RHEL 8 기본 Python 3.6 포함).

**Linux 배포판 지원 수준:**

| 수준 | 배포판 | Python 상태 | 비고 |
|------|--------|------------|------|
| 기본 Python으로 바로 사용 가능 | RHEL 9+, Rocky 9+, Ubuntu 22.04+, Debian 12+ | 3.9 이상 기본 설치 | 별도 조치 불필요 |
| 추가 Python 설치 후 사용 가능 | RHEL 8, Rocky 8, Ubuntu 20.04, Debian 11 | 기본 3.6~3.8 | python39 이상 별도 설치 필요 |
| 프로젝트 기준 밖 (별도 검증 필요) | RHEL 7, CentOS 7, Ubuntu 18.04, Debian 10 | 3.6 이하 기본 | python39 설치 가능하나 프로젝트에서 검증하지 않음 |
| 미지원 | RHEL 6, CentOS 6, Ubuntu 14.04, Debian 8 | 3.9 설치 불가 | |

---

### 1-2. Windows 대상 서버

| 항목 | 최소 요구사항 | 미충족 시 동작 |
|------|-------------|--------------|
| **WinRM** | 활성화 (5985 또는 5986 오픈) | 연결 실패 → `status: failed` |
| **PowerShell** | **5.1 이상** | 하위 참고 |
| **OS 버전** | **Windows Server 2016 이상** 권장 | 하위 참고 |
| **WinRM 인증** | NTLM 활성화 | 인증 실패 → `status: failed` |
| **CIM (WMI)** | 활성화 (기본) | 수집 실패 |

**운영 기준:**

| PowerShell | OS | 지원 내용 |
|------------|---|---------|
| 5.1 | Server 2016+ | `Get-LocalUser`, `Get-Volume`, `Get-NetIPAddress` 전체 cmdlet 지원 |

**레거시 제한 지원:**

| PowerShell | OS | 제한 사항 |
|------------|---|---------|
| 5.0 | Server 2012 R2 | `Get-LocalUser` 없음 → WMI fallback (`last_access_time: null`) |
| 3.0–4.0 | Server 2012 | `Get-Volume` 없음 → WMI fallback |

**미지원:**

| PowerShell | OS | 이유 |
|------------|---|------|
| 2.0 이하 | Server 2008 R2 | WinRM NTLM 불안정, `Get-CimInstance` 없음 |

> **계정 권한 기준:**
> - 모든 섹션을 수집하려면 **관리자(Administrator) 권한**이 있는 계정을 사용해야 한다.
> - 비관리자 계정으로도 기본 WMI 정보(hostname, OS, CPU, memory)는 수집 가능하다.
> - `Get-LocalUser`, 디스크 상세, serial_number 등은 관리자 권한이 필요하다.
> - 권한 부족 시 해당 필드는 `null`로 반환되며 수집 자체는 실패하지 않는다 (non-fatal).
> - vault에 관리자 계정 정보를 포함하면 전체 수집 가능.

> **미지원**: Windows Server 2008, Windows Server 2008 R2, Windows 7 이하

---

### 1-3. hosting_type 필드 (OS 채널 전용)

OS 채널은 `system.hosting_type` 필드를 제공한다.

| 값 | 의미 |
|---|---|
| `virtual` | 가상머신 guest (VMware, KVM, Hyper-V 등) |
| `baremetal` | 물리 서버에 직접 설치된 OS |
| `unknown` | 판별 근거 부족 또는 신호 충돌 |

적용 범위:
- OS 채널 (Linux, Windows)에서만 제공한다
- Redfish, ESXi 채널에는 적용하지 않는다
- 물리 서버에 직접 설치된 OS는 그 위에서 KVM/Hyper-V host 역할을 하더라도 `baremetal`로 분류한다

---

### 1-4. Agent 노드 (Linux → Windows 수집 시)

| 항목 | 최소 요구사항 |
|------|-------------|
| **pywinrm** | 0.4.0 이상 (`pip install pywinrm`) |
| **Ansible** | ansible-core 2.16 이상 (ansible.windows 컬렉션 포함) |

---

## 2. esxi-gather (VMware ESXi)

### 2-1. ESXi 대상 서버

| 항목 | 최소 요구사항 | 미충족 시 동작 |
|------|-------------|--------------|
| **ESXi 버전** | **6.5 이상** | 하위 버전은 vSphere API 일부 미지원 |
| **HTTPS 포트** | 443 오픈 (vSphere API) | 연결 실패 → `status: failed` |
| **라이선스** | **유료 라이선스 필요** (Essentials 이상) | Free 라이선스는 API write access 없어 수집 불가 |
| **관리자 계정** | 읽기 권한 이상 (`ReadOnly` role) | 인증 실패 → `status: failed` |

**ESXi 버전별 수집 가능 항목:**

| ESXi 버전 | 수집 가능 여부 | 비고 |
|----------|-------------|------|
| 9.x | 완전 지원 | 2026-08-13 lab 실측 (9.0.0 3대). 6섹션 수집 확인 |
| 8.x | 완전 지원 | |
| 7.x | 완전 지원 | |
| 6.7 | 완전 지원 | |
| 6.5 | 대부분 지원 | 일부 항목 `null` 가능 |
| 6.0 이하 | 미지원 | `community.vmware` 모듈 호환 안 됨 |

> **중요**: Free ESXi(vSphere Hypervisor)는 API write access 가 없어 `vmware_host_facts` 실행 시 오류 발생

---

### 2-2. Agent 노드

| 항목 | 최소 요구사항 |
|------|-------------|
| **Python** | 3.12 이상 (Agent venv) |
| **pyvmomi** | 7.0 이상 (`pip install pyvmomi`) |
| **Ansible Collection** | `community.vmware` 3.0 이상 (`ansible-galaxy collection install community.vmware`) |

---

## 3. redfish-gather (Dell / HPE / Lenovo / Supermicro / Cisco BMC)

### 3-1. BMC 대상 서버

**공통 요구사항:**

| 항목 | 최소 요구사항 | 미충족 시 동작 |
|------|-------------|--------------|
| **HTTPS 포트** | 443 오픈 (Redfish API) | 연결 실패 → `status: failed` |
| **Redfish 버전** | DSP0266 1.0 이상 | 하위 버전 미지원 |
| **인증** | Basic Authentication 지원 | 인증 실패 → `status: failed` |

**벤더별 최소 BMC 버전:**

| 벤더 | BMC | 최소 버전 | Systems URI | Managers URI |
|------|-----|---------|-------------|-------------|
| **Dell** | iDRAC | **iDRAC 9** (FW 3.00+) | `Systems/System.Embedded.1` | `Managers/iDRAC.Embedded.1` |
| **HPE** | iLO | **iLO 5** (FW 1.10+) | `Systems/1` | `Managers/1` |
| **Lenovo** | XCC | **XCC** (FW 1.xx+, X11 이상) | `Systems/1` | `Managers/1` |
| **Supermicro** | BMC | **X10 이상** (BMC FW 3.xx+) | `Systems/1` | `Managers/1` |
| **Cisco** | CIMC | **CIMC** (UCS C-Series M4+) | 동적 탐색 (Members[0]) | `Managers/CIMC` |

> [!NOTE]
> 위 5개 벤더 외에 Huawei iBMC / Inspur ISBMC / Fujitsu iRMC / Quanta QCT BMC adapter 도 있다.
> 이 4개는 lab 부재라 vendor 공식 문서와 DMTF 표준만 보고 작성했고 실장비로는 검증하지 않았다.

**검증 기준 장비 (2026-03-18 직접 HTTPS 호출 검증):**

| 벤더 | 모델 | BMC | FW 버전 | Redfish Version | 매칭 Adapter |
|------|------|-----|---------|-----------------|-------------|
| Dell | PowerEdge R740 | iDRAC 9 | 4.00 | 1.6.0 | redfish_dell_idrac9 (P100) |
| HPE | ProLiant DL380 Gen11 | iLO 6 | 1.73 | 1.20.0 | redfish_hpe_ilo6 (P100) |
| Lenovo | ThinkSystem SR650 V2 | XCC | 5.70 | 1.15.0 | redfish_lenovo_xcc (P100) |

> 검증 기준 장비에서 확인된 Redfish Version 범위는 1.6.0 ~ 1.20.0 이다.
> 이 범위는 지원 범위가 아니라 실장비 검증 시점에 확인된 값이다.
> HPE iLO 6 은 전용 어댑터 `redfish_hpe_ilo6` (P100) 로 매칭된다 (`hpe_ilo` P10 은 미세대 fallback).

**벤더별 지원/미지원 상세:**

| 벤더 | 지원 | 미지원 | 실장비 검증 |
|------|------|--------|-----------|
| Dell | iDRAC 9 (PowerEdge 14G+) | iDRAC 7 — Redfish 미성숙 (iDRAC 8 은 FB 제한 수집) | 검증 완료 |
| HPE | iLO 5 (ProLiant Gen10+), iLO 6 (Gen11) | iLO 3 이하 미지원. iLO 4 는 FB 제한 수집 (`Oem.Hp`) | 검증 완료 |
| Lenovo | ThinkSystem (X11, SR/ST/SD 시리즈) | ThinkServer — Redfish 미지원 (IMM2 는 FB 제한 수집) | 검증 완료 |
| Supermicro | X10/X11/X12/X13/H11/H12 이상 | X8 이하 미지원. X9 는 6 섹션 부분 수집 | 미검증 (어댑터만 존재) |
| Cisco | UCS C-Series M4+ (CIMC Redfish 지원) | UCS C-Series M3 이하 — Redfish 미지원 | M4 partial lab 검증 (M5~M8 미검증) |

> 코드는 Redfish 표준 API(DSP0266)를 동적 탐색(API Discovery)하므로,
> 검증 기준 장비 및 유사한 Redfish 표준 구현에서 **표준 필드**가 정상 수집됐다.
> OEM 확장 필드(`data.*.oem`)는 위 표의 BMC 버전에서 검증됐다.

---

### 3-2. Agent 노드

| 항목 | 최소 요구사항 |
|------|-------------|
| **Python** | **3.12 이상** (Agent venv) |
| **외부 라이브러리** | **없음** — stdlib(urllib, ssl, socket) 만 사용 |

---

## 4. Jenkins Agent 공통 요구사항

> **검증 기준 Agent**: 10.100.64.154 (Ubuntu 24.04.4 LTS), 2026-03-27 확인.
> 아래 "검증 기준" 컬럼은 해당 Agent에서 실측한 값이며 전체 운영 환경의 표준을 의미하지 않는다.
> 설치 절차는 [docs/operate/02-agent-node.md](docs/operate/02-agent-node.md) 참조.

### 4-1. 런타임 환경

| 항목 | 최소 | 검증 기준 Agent | 비고 |
|------|------|----------------|------|
| **OS** | RHEL/CentOS 7+, Ubuntu 18.04+, Rocky 8+ | Ubuntu 24.04.4 LTS | |
| **Python** | **3.12** | 3.12.3 | venv: `/opt/ansible-env/` |
| **Java** | **21** | OpenJDK 21.0.10 | Jenkins Agent 실행 |
| **ansible-core** | **2.16** | 2.20.3 | Python 3.12 필요 시 2.16+. `ansible.builtin` 최신 필터 사용 |
| **ansible (package)** | — | 13.4.0 | 풀패키지 설치 시 core + bundled collections 포함 |

### 4-2. pip 패키지

| 패키지 | 최소 | 검증 기준 Agent | 용도 | 필수 여부 |
|--------|------|----------------|------|----------|
| **pywinrm** | 0.4.0 | 0.5.0 | Windows WinRM 연결 | Windows 수집 시 필수 |
| **pyvmomi** | 7.0 | 9.0.0 | ESXi vSphere API | ESXi 수집 시 필수 |
| **redis** | 4.0 | 7.3.0 | Ansible fact caching | fact caching 사용 시 필수 |
| **jmespath** | — | 1.1.0 | json_query 필터 | json_query 사용 시 필수 |
| **netaddr** | — | 1.3.0 | ipaddr 필터 | ipaddr 사용 시 필수 |
| **lxml** | — | 6.0.2 | VMware XML 파싱 | ESXi 수집 시 필수 |
| **requests** | — | 2.32.5 | HTTP 클라이언트 | pywinrm 의존 |

### 4-3. Ansible Collections

| Collection | 최소 | 검증 기준 Agent | 용도 | 필수 여부 |
|-----------|------|----------------|------|----------|
| **ansible.windows** | 1.x | 3.3.0 | Windows gather | Windows 수집 시 필수 |
| **community.vmware** | 3.0 | 6.2.0 | ESXi gather | ESXi 수집 시 필수 |
| **community.windows** | — | 3.1.0 | Windows 보조 모듈 | Windows 수집 시 권장 |
| **ansible.posix** | — | 2.1.0 | Linux 모듈 | ansible 풀패키지에 포함 |
| **community.general** | — | 12.4.0 | 범용 모듈 | ansible 풀패키지에 포함 |
| **ansible.utils** | — | 6.0.1 | 유틸리티 필터 | ansible 풀패키지에 포함 |

> 검증 기준 Agent에는 `vmware.vmware` (2.7.0), `vmware.vmware_rest` (4.10.0),
> `dellemc.openmanage` (10.0.1) 등도 설치되어 있으나, 현재 프로젝트에서 직접 사용하지 않는다.

---

## 5. 네트워크 요구사항

| 방향 | 포트 | 용도 |
|------|------|------|
| Agent → Linux 대상 | TCP 22 | SSH |
| Agent → Windows 대상 | TCP 5985 또는 5986 | WinRM HTTP / HTTPS |
| Agent → ESXi 대상 | TCP 443 | vSphere API (HTTPS) |
| Agent → BMC (Redfish) | TCP 443 | Redfish API (HTTPS) |

---

## 6. tasks/ 구조 개요

3개 gather 모두 `tasks/` 디렉터리로 수집/정규화 로직이 분리되어 있다.
상세 구조와 처리 과정은 [docs/develop/01-gather-structure.md](docs/develop/01-gather-structure.md) 참조.

> `REPO_ROOT` 환경변수로 공통 태스크 경로를 참조하므로 Jenkins 에서 `REPO_ROOT=${WORKSPACE}` 설정 필수.

---

## 7. 식별자 수집 정책 (호출자 cross-channel 매칭용)

호출자 시스템이 같은 물리 서버를 OS 채널 응답과 Redfish 채널 응답에서 매칭하려면 식별자가 필요하다. 본 절은 그 식별자가 어떤 조건에서 채워지는지 정리한다.

### 7-1. 채널별 식별자 필드

| 채널 | 필드 | 출처 | 권한 |
|------|------|------|------|
| OS (Linux) | `system.serial_number`, `system.system_uuid` | `/sys/class/dmi/id/` | sudo / become 권장 |
| OS (Windows) | `system.serial_number`, `system.system_uuid` | WMI Win32_BIOS / Win32_ComputerSystemProduct | 관리자 권장 |
| Redfish | `data.hardware.serial`, `data.system.uuid` | Redfish ComputerSystem | BMC 인증 |
| ESXi | `data.hardware.serial` | vSphere API host facts | ESXi 관리자 권장 |

### 7-2. 매칭 권장 키

호출자가 같은 서버를 두 채널에서 매칭할 때 이 순서로 시도한다.

1. `system_uuid` 우선 (OS ↔ Redfish 가장 신뢰 가능)
2. `serial_number` (벤더 / 채널별 의미 차이가 있어 보조 키)
3. `hosting_type == "virtual"` 인 OS 응답은 물리 Redfish 와 매칭 시도하지 않음

### 7-3. 권한 부족 시의 동작

- 식별자 미수집은 gather 실패가 아니다. 수집 자체는 계속 진행된다 (non-fatal).
- 식별자 필드는 `null` 로 반환되고 errors[] 에는 사유가 추가될 수 있다.
  - `insufficient_privilege` — 권한 부족으로 DMI / WMI 접근 불가
  - `identifier_not_available` — 출처 자체가 유효한 값을 제공하지 않음
- envelope 의 `status` / `sections` 판정에는 영향 없음.

### 7-4. 권장

정확한 식별자 수집을 위해 다음 중 하나를 vault 에 포함하는 것을 권장한다.

- Linux: `become_password` (sudo 권한)
- Windows: 관리자 계정 비밀번호

상세 구현 (수집 우선순위 / fallback / baseline 기준) 은 [docs/develop/05-field-mapping.md](docs/develop/05-field-mapping.md) "식별자 수집 경로" 절 참조.

---

## 8. 한눈에 보는 차단 사유

**완전 미지원** (수집 시도 자체 실패):

| 환경 | 차단 사유 |
|------|----------|
| Windows Server 2008 / 2008 R2 | WinRM NTLM 불안정, PowerShell 2.0, CIM 미지원 |
| ESXi 6.0 이하 | community.vmware 컬렉션 호환성 부재 |
| ESXi Free 라이선스 | vSphere API write access 없음 |
| Dell iDRAC 7 이하 | Redfish API 미성숙 — 일부 endpoint 자체가 응답 안 함 (iDRAC 8 은 8절 NOTE 의 FB 수집) |
| HPE iLO 3 이하 | 옛 `Oem.Hp` 구조 (iLO 4 는 8절 NOTE 의 FB 수집) |
| Lenovo ThinkServer | Redfish 자체 미지원 (ThinkSystem 만 지원) |
| Supermicro X8 이하 | Redfish 미지원 (X9 는 6 섹션 부분 수집 — 8절 NOTE) |
| Cisco UCS C-Series M3 이하 | Redfish 미지원 |
| Python 3.8 이하 (타겟 Linux) | ansible-core 2.20 모듈 실행 불가 |
| Python 3.11 이하 (Agent) | 프로젝트 검증 기준 외 |

> [!NOTE]
> 이 표는 "벤더별 최소 BMC 버전"(3-1절)에 못 미치는 세대를 모은 것이다.
> 이 중 Dell iDRAC 8 / HPE iLO 4 / Lenovo IMM2 는 priority 50 fallback adapter 가 storage/power 까지 fallback 으로 수집한다 (cycle 2026-05-06 M-D3 — 일부 필드 `null` 가능). Supermicro X9 만 storage/firmware/power 를 `not_supported` 로 보고한다. 완전 차단은 adapter 자체가 없는 더 낮은 세대와 Redfish 미지원 장비(Lenovo ThinkServer 등)다.

**제한 지원** (수집은 되지만 일부 필드 `null`):

| 환경 | 어떤 필드가 빠지나 |
|------|------------------|
| Windows Server 2012 / 2012 R2 | `last_access_time` (Get-LocalUser 부재), 일부 볼륨 정보 (Get-Volume 부재) |
| ESXi 6.5 | 일부 vSphere API 항목 |
| Linux 에서 sudo 권한 없는 계정 | `serial_number`, `system_uuid` 등 DMI 정보 |
| Windows 에서 비관리자 계정 | `serial_number`, 디스크 상세, 로컬 사용자 일부 |

이 표의 "차단" 환경은 호출자에게 `status: failed` 가 반환되고 "제한 지원" 환경은 정상 응답 안에서 일부 필드만 `null` 로 보인다.
