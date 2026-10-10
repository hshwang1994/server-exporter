# 05. inventory_json 입력 형식 (호출자 명세)

> **이 문서는** Jenkins Job 을 외부에서 트리거하는 호출자 (포털 / 백엔드 서비스) 가 보내야 하는 `inventory_json` 파라미터의 형식을 정의합니다.
>
> **핵심 약속 (꼭 기억해 주세요)**: 수집에 쓰는 값은 서버마다 **IP 하나**입니다. 호스트명 · 벤더 같은 다른 키를 함께 보내도 되지만
> 연결 · 자격증명 · 벤더 판단에는 쓰지 않습니다. 자격증명은 보내지 않습니다 — vault 에서 자동 로딩되고,
> OS 종류 / BMC 제조사 / 벤더는 server-exporter 가 스스로 감지합니다.

## 5초 요약

| target_type | 보내야 할 형식 |
|-------------|---------------|
| `os` (Linux 또는 Windows 자동 분기) | `[{"service_ip": "10.x.x.1"}]` |
| `esxi` | `[{"service_ip": "10.x.x.1"}]` |
| `redfish` (서버 BMC) | `[{"bmc_ip": "10.x.x.201"}]` |

서버 정보를 통째로 보내도 됩니다. 한 객체에 `service_ip` 와 `bmc_ip` 가 함께 있으면 `target_type` 이 고른 키 하나만 읽습니다 (2절).
단, 한 서버라도 그 키가 없으면 요청 전체가 거부되고 Portal 로 결과가 가지 않습니다 (5절).

---

## 1. 표준 형식

target_type 에 따라 IP 필드명이 다릅니다.

```jsonc
// os 또는 esxi 채널
[{"service_ip": "10.x.x.1"}, {"service_ip": "10.x.x.2"}]

// redfish 채널 — BMC 관리 IP 를 보냄 (서비스 IP 와 별개)
[{"bmc_ip": "10.x.x.201"}, {"bmc_ip": "10.x.x.202"}]

// 하위 호환: 혹시 모를 경우 ip 키도 받아줌
[{"ip": "10.x.x.1"}]

// 서버 정보를 통째로 보내도 됨 — os/esxi 는 service_ip, redfish 는 bmc_ip 만 읽고 나머지 키는 보존만 함 (2 · 4절)
[{"service_ip": "10.x.x.1", "bmc_ip": "10.x.x.201", "hostname": "server01", "vendor": "hp", "server_role": "WEB"}]
```

## 2. 필드 이름이 다른 이유

| target_type | 필드 | 왜 다른가 |
|-------------|------|----------|
| `os` / `esxi` | `service_ip` | OS / 하이퍼바이저가 직접 응답하는 서비스 IP |
| `redfish` | `bmc_ip` | 서버 BMC 의 별도 관리 IP (서비스 IP 와 다른 경우가 많음) |

호출자가 "어느 IP 를 사용해야 하는지" 헷갈리지 않도록 필드 이름에 의도를 담았습니다.

### 서버 정보를 통째로 보낼 때 — 실제로 읽는 키

한 객체에 두 IP 가 함께 있어도 된다. `target_type` 이 읽을 키 하나를 정하고, 다른 IP 키는 연결에 쓰지 않는다.

| target_type | 읽는 키 (앞이 우선) | 연결에 쓰지 않는 IP 키 |
|-------------|--------------------|----------------------|
| `os` / `esxi` | `service_ip` → `ip` | `bmc_ip` |
| `redfish` | `bmc_ip` → `ip` | `service_ip` |

결과 전송 본문 `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson:[…]}` 에서 서버별 결과의 `ip` 는 위 표에서 읽은 값
(앞뒤 공백을 지운 값)이다. 보낸 객체는 결과에 다시 넣지 않으므로, Portal 은 이 `ip` 를 os · esxi 면 `service_ip`,
redfish 면 `bmc_ip` 와 맞춰 자기 서버 목록에 연결한다. 같은 서버 목록을 `target_type` 만 바꿔 보내면 os · esxi 는 서비스 IP 로,
redfish 는 BMC IP 로 수집한다.

## 3. 보내지 않는 것

자격증명은 보내지 않습니다. 나머지 항목은 보내도 되지만 연결 · 자격증명 · 벤더 판단에는 쓰이지 않습니다 (4절처럼 보존만 됩니다).

| 항목 | 처리 | 이유 |
|------|------|------|
| `username`, `password` | **보내지 않는다** | vault 에 저장됨 — 호출자에게 노출 금지. 보내면 서버별 보존값(4절)과 Jenkins 빌드 파라미터 화면에 그대로 남는다 |
| `hostname` | 받지만 쓰지 않는다 | 결과의 `hostname` 은 장비에서 읽은 값이다 (없으면 `null` — 아래 "inventory_hostname 과 결과의 hostname" 절) |
| `vendor` | 받지만 쓰지 않는다 | Redfish 는 무인증 ServiceRoot 호출로 자동 감지한다. 보낸 값은 참고하지 않는다 |
| `os_family` (linux / windows) | 받지만 쓰지 않는다 | OS 채널은 포트와 프로토콜(SSH / WinRM) 확인으로 자동 분기한다 |

## 4. 서버별 추가 정보 (추가 수집용)

IP 외의 항목(예: `physical_purpose`)을 서버별로 함께 보내면 그대로 보존돼, 추가 수집(Add-on)이 그 서버에서
실행할 Software 항목을 고르는 데 쓴다 (Add-on Software 설정의 `when`). DB IP 수집(Add-on hosts 기능, 결과 `dbIpList`)은
이 항목과 관계없이 장비에서 읽은 hostname(결과의 `data.system.hostname`)으로 정해진다 — 보낸 `hostname` 키가 아니다.
추가 수집을 켤지 자체는 `target_type` 과 Jenkins 설정이 정하고 이 항목은
관여하지 않는다. 보내지 않아도 기본 수집에는 아무 영향이 없다.

```jsonc
[{"service_ip": "10.x.x.1", "physical_purpose": "DB"}]
```

- 키 이름과 값은 정해져 있지 않다. 어떤 키를 조건으로 쓸지는 Add-on 설정이 정한다.
- IP 선택 · 형식 검증 · 중복 검사는 그대로다. 추가 항목은 연결 · 자격증명에 쓰이지 않는다.
- 값은 글자 그대로 보존된다 (`{{ }}` 가 든 문자열도 해석되지 않는다).
- `__ansible_` 로 시작하는 키는 Ansible 이 내부 표식으로 쓰는 이름이라 보존하지 않는다.
- 추가 수집 결과는 `data.addon` 에 들어간다 — [02-output-envelope.md](02-output-envelope.md) 의 data 절.

## 5. 요청이 통째로 거부되는 경우

대상 목록은 Jenkins 의 입력 확인 단계와 `inventory.sh` 가 같은 규칙으로 검사한다. 한 서버라도 아래에 걸리면
**요청 전체를 거부**하고, 맞는 서버만 골라 수집하지 않는다.

| 걸리는 경우 | 예 |
|-------------|----|
| JSON 이 아님, 배열이 아니거나 비어 있음, 원소가 객체가 아님 | `{"service_ip": "10.x.x.1"}`, `[]`, `["10.x.x.1"]` |
| 읽을 키가 없음 | `os` · `esxi` 요청에 `bmc_ip` 만 있는 서버(OS 설치 전 서버 등)가 섞임. `redfish` 요청에 `service_ip` 만 있는 서버가 섞임 |
| 값이 공백뿐 | `"service_ip": "   "` — 공백뿐인 값은 `ip` 키로 넘어가지 않는다 |
| 값이 문자열이 아님 | `"service_ip": 10`, `"service_ip": ["10.x.x.1"]` |
| IPv4 가 아님 | `10.x.x.1/24`(CIDR), `server01`(hostname), IPv6, `10.0.0.01`(앞자리 0), 전각 숫자 |
| 같은 IP 가 두 번 | 앞뒤 공백을 지운 뒤 같으면 중복이다. 한쪽은 `service_ip`, 다른 쪽은 `ip` 에 있어도 중복이다 |

- 주 키 값이 `""` 또는 `null` 이면 `ip` 키로 넘어간다. 값 앞뒤의 공백은 지우고 읽는다.
- 거부되면 입력 확인 단계에서 빌드가 FAILURE 로 끝나고 **Portal 로 결과를 보내지 않는다** — 보낼 접수 목록이 없다.
  호출자는 Jenkins 빌드 결과로 알아야 하며, 콘솔에 `[입력 확인] inventory_json …` 오류 줄이 남는다.
- 거부되지 않은 요청은 접수된 서버마다 결과가 1개씩 온다. 연결되지 않는 서버도 실패 결과로 온다.

## 6. 크기 주의 (계산값 — 실측하지 않음)

`inventory_json` 은 Jenkins 에서 환경변수로 수집 프로세스에 전달된다. Linux 는 환경변수 하나의 길이를
131,072바이트(128 KiB)로 제한하므로, 이보다 긴 요청은 수집 프로세스를 시작하지 못할 수 있다.

| 형태 | 서버 1대 크기 (예) | 한 요청의 대략적인 한도 |
|------|------------------|----------------------|
| IP 만 (`{"service_ip": "…"}`) | 약 30자 | 약 4,000대 |
| 서버 정보를 통째로 (키 9개 예시) | 약 200자 | 약 600대 |

커널 한도에서 계산한 값이다. 이보다 큰 요청을 보낼 계획이면 먼저 시험해 보거나 요청을 나눈다.

---

## target_type 별 동작

### os

`5986 → 5985 → 22` 순으로 포트를 열어 보고, 열린 포트에서 프로토콜(WinRM / SSH)까지 확인해 Linux/Windows 를 나눈다:
- 22 (SSH) → Linux → `vault/<loc>/os/linux.yml`
- 5986 / 5985 (WinRM) → Windows → `vault/<loc>/os/windows.yml`
- 모두 실패 → `status: failed`

### esxi

단일 계정 로딩:
- `vault/<loc>/esxi.yml`

### redfish

계정이 두 종류다:
1. 계정 없이 Redfish ServiceRoot 를 읽어 벤더를 감지한다.
2. 표준 수집 계정으로 인증한다. 표준 계정은 전역 1벌(`vault/common/redfish/standard.yml`)이라 위치도 벤더도 보지 않고,
   벤더를 알아내지 못해도 시도한다. 최종 수집은 항상 이 계정으로 한다.
3. 표준 계정 인증이 명시적으로 거부(HTTP 401)되면, 위치 × 벤더별 복구 계정(`vault/<loc>/redfish/<vendor>.yml`)으로
   표준 계정을 만들거나 비밀번호를 맞춘 뒤 표준 계정으로 다시 인증해 수집한다.

자세한 계정 구조는 [../operate/05-vault.md](../operate/05-vault.md) 3.3.1절에 있다.

---

## Jenkins → inventory 스크립트 전달 과정

### Jenkins 파라미터 → 환경변수 자동 전달

Jenkins Declarative Pipeline 의 `parameters` 블록에 정의한 파라미터는
빌드 실행 시 **자동으로 같은 이름의 환경변수로 내보내진다.**

```groovy
parameters {
    text(name: 'inventory_json', ...)   // → 환경변수 $inventory_json (소문자)
}
```

따라서 파라미터명이 `inventory_json` 이면 쉘·Python 에서
`$inventory_json` (소문자) 으로 바로 접근할 수 있다.

`Jenkinsfile_portal` 은 접수 목록을 **환경변수로 넘기지 않는다** (2026-10-10 정정). Linux 는 환경변수 하나가
131,072 바이트를 넘으면 그 빌드의 모든 셸 단계가 "Argument list too long" 으로 실패한다 — 확장형 입력 5,000대(510 KB)로
확인했다. 수집 단계가 작업 폴더에 `.inventory_input.json` 을 쓰고 `INVENTORY_JSON_FILE` 환경변수로 그 경로만 넘긴다.

### inventory.sh 읽기 우선순위

각 gather 프로젝트의 `inventory.sh` 는 다음 순서로 인벤토리 JSON 을 찾는다.

| 우선순위 | 소스 | 설명 |
|----------|------|------|
| 1순위 | 환경변수 `INVENTORY_JSON_FILE` 이 가리키는 파일 | `Jenkinsfile_portal` 수집 단계가 작업 폴더에 쓴 `.inventory_input.json`. 변수가 있는데 파일이 없거나 비어 있으면 다른 곳으로 넘어가지 않고 오류다 |
| 2순위 | 환경변수 `INVENTORY_JSON` / `inventory_json` | 로컬 실행 · `scripts/ai/ci_gate.sh` 의 syntax-check 같은 작은 입력 |
| 3순위 | `$WORKSPACE/.inventory_input.json` (없으면 저장소 루트) | Jenkins 밖에서 직접 실행할 때 |

모두 비어 있거나 없으면 에러로 종료한다. 파일 내용은 `inventory_json` 파라미터 원문 그대로다 — 호출자가 보낸 host object 전체가
`se_host_input` 으로 보존된다(2절).

---

## inventory_hostname 과 결과의 hostname

모든 gather 에서 `inventory_hostname = ip` 로 통일한다 (Ansible 대상 이름이 IP 다). 보낸 `hostname` 키는 쓰지 않는다.

결과(envelope)의 `hostname` 은 장비에서 읽은 값이다. OS hostname → FQDN → BMC hostname 순으로 채우고, 셋 다 없으면 `null` 이다.
**IP 로 채우지 않는다.** 상세는 [03-fields.md](03-fields.md) 8절.

---

## 자격증명 (vault 에서 로딩)

호출자는 자격증명을 보내지 않는다. 수집이 실행 중에 위치(`loc` → `se_location`)와 대상 종류에 맞는 vault 파일을 연다.
파일을 열지 못하면 빌드 전체가 멈추지 않고 그 서버가 자격증명 단계 실패 결과(`CREDENTIAL_SET_UNAVAILABLE`)로 끝난다.
경로와 파일 형식은 [../operate/05-vault.md](../operate/05-vault.md) 에 있다.

---

## 기존 명세에서 변경된 사항 (참고)

이전 버전의 호출자 명세에 익숙하다면 다음 표를 보세요.

| 항목 | 이전 | 현재 |
|------|------|------|
| inventory_json 필드 | ip, hostname, username, password | **IP 만 읽는다** |
| IP 외 키 | — | 보존만 하고 추가 수집(Add-on) 조건에만 쓴다 (4절) |
| 계정 전달 방식 | inventory_json 에 포함 | vault 자동 로딩 |
| hostname 처리 | 포털이 전달 | 장비에서 읽은 값 (없으면 `null`) |
| vendor 처리 | 포털이 전달 (선택) | 없음 (자동 감지) |

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 받게 될 응답 형식 | [02-output-envelope.md](02-output-envelope.md) |
| 응답 필드 의미 사전 | [03-fields.md](03-fields.md) |
| 실패 시 호출자 처리 | [04-failure-and-diagnosis.md](04-failure-and-diagnosis.md) |
| Jenkins Job 자체 호출 절차 | [../operate/03-job-registration.md](../operate/03-job-registration.md) |
