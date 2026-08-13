# 05. inventory_json 입력 형식 (호출자 명세)

> **이 문서는** Jenkins Job 을 외부에서 트리거하는 호출자 (포털 / 백엔드 서비스) 가 보내야 하는 `inventory_json` 파라미터의 형식을 정의합니다.
>
> **핵심 약속 (꼭 기억해 주세요)**: 호출자는 **IP 만** 전달합니다. 호스트명 / 자격증명 / 벤더는 보내지 않습니다.
> 자격증명은 vault 에서 자동 로딩되고 OS 종류 / BMC 제조사 / 벤더는 server-exporter 가 스스로 감지합니다.

## 5초 요약

| target_type | 보내야 할 형식 |
|-------------|---------------|
| `os` (Linux 또는 Windows 자동 분기) | `[{"service_ip": "10.x.x.1"}]` |
| `esxi` | `[{"service_ip": "10.x.x.1"}]` |
| `redfish` (서버 BMC) | `[{"bmc_ip": "10.x.x.201"}]` |

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
```

## 2. 필드 이름이 다른 이유

| target_type | 필드 | 왜 다른가 |
|-------------|------|----------|
| `os` / `esxi` | `service_ip` | OS / 하이퍼바이저가 직접 응답하는 서비스 IP |
| `redfish` | `bmc_ip` | 서버 BMC 의 별도 관리 IP (서비스 IP 와 다른 경우가 많음) |

호출자가 "어느 IP 를 사용해야 하는지" 헷갈리지 않도록 필드 이름에 의도를 담았습니다.

## 3. 보내지 않는 것

호출자가 다음 항목을 보내면 무시되거나 보안 정책상 거부됩니다.

| 항목 | 왜 보내지 않는가 |
|------|----------------|
| `username`, `password` | vault 에 저장됨 — 호출자에게 노출 금지 |
| `hostname` | 등록 전 서버일 수 있어 의미 없음. envelope 의 hostname 필드는 IP 로 채워짐 |
| `vendor` | Redfish 의 경우 무인증 ServiceRoot 호출로 자동 감지 |
| `os_family` (linux / windows) | OS 채널은 SSH 22 / WinRM 5985-5986 포트 감지로 자동 분기 |

---

## target_type 별 동작

### os

포트 감지로 Linux/Windows 자동 분기:
- SSH 22 열림 → Linux → `vault/<loc>/os/linux.yml`
- WinRM 5986 또는 5985 열림 → Windows → `vault/<loc>/os/windows.yml`
- 둘 다 닫힘 → `status: failed`

### esxi

단일 계정 로딩:
- `vault/<loc>/esxi.yml`

### redfish

2단계 벤더 감지:
1. 빈 계정으로 Redfish ServiceRoot → `System.Manufacturer` 읽기
2. 감지된 벤더에 맞는 `vault/<loc>/redfish/<vendor>.yml` 로딩 (dell/hpe/lenovo/supermicro/cisco/huawei/inspur/fujitsu/quanta)
3. 올바른 계정으로 전체 재수집

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

추가로 `environment` 블록에서 대문자 변수를 명시해서 매핑하면
두 가지 이름을 모두 쓸 수 있다:

```groovy
environment {
    INVENTORY_JSON = "${params.inventory_json}"   // 대문자 별칭
}
```

### inventory.sh 읽기 우선순위

각 gather 프로젝트의 `inventory.sh` 는 다음 순서로 인벤토리 JSON 을 탐색한다.

| 우선순위 | 소스 | 설명 |
|----------|------|------|
| 1순위 | 환경변수 `INVENTORY_JSON` (대문자) | `environment` 블록에서 명시 설정 |
| 2순위 | 환경변수 `inventory_json` (소문자) | Jenkins 파라미터 자동 전달 |
| 3순위 | `.inventory_input.json` 파일 | Jenkinsfile `writeFile` fallback |

세 가지가 모두 비어 있거나 없으면 에러로 종료한다.

> **참고** — 현재 Jenkinsfile v3 에서는 `environment` 블록에서 `INVENTORY_JSON` 을
> 명시 설정하므로 실제 동작 시 1순위(대문자 환경변수) 로 전달된다.
> 2·3순위는 `environment` 블록 없이 파라미터만 정의하거나
> 수동 실행(writeFile) 시 fallback 으로 동작한다.

---

## inventory_hostname

모든 gather 에서 `inventory_hostname = ip` 로 통일한다.
포털 등록 전 서버이므로 hostname 을 알 수 없다.
OUTPUT JSON 의 `hostname` 필드도 ip 값으로 채워진다.

---

## Ansible 연결 파라미터 (vault 에서 로딩)

### vault/<loc>/os/linux.yml
```yaml
ansible_user:     "..."
ansible_password: "..."
```

Ansible 연결 파라미터는 site.yml 의 `vars_files` 에서 자동 로딩:
```yaml
vars_files:
  - "{{ lookup('env', 'REPO_ROOT') }}/vault/<loc>/os/linux.yml"
```

---

## 기존 명세에서 변경된 사항 (참고)

이전 버전의 호출자 명세에 익숙하다면 다음 표를 보세요.

| 항목 | 이전 | 현재 |
|------|------|------|
| inventory_json 필드 | ip, hostname, username, password | **IP 만** |
| 계정 전달 방식 | inventory_json 에 포함 | vault 자동 로딩 |
| hostname 처리 | 포털이 전달 | 없음 (IP 그대로 사용) |
| vendor 처리 | 포털이 전달 (선택) | 없음 (자동 감지) |

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 받게 될 응답 형식 | [02-output-envelope.md](02-output-envelope.md) |
| 응답 필드 의미 사전 | [03-fields.md](03-fields.md) |
| 실패 시 호출자 처리 | [04-failure-and-diagnosis.md](04-failure-and-diagnosis.md) |
| Jenkins Job 자체 호출 절차 | [../operate/03-job-registration.md](../operate/03-job-registration.md) |
