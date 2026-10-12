# 호출자가 보내는 것

이 문서는 Jenkins Job을 부르는 호출자(Portal)가 보내는 파라미터, 그중 `inventory_json`의 형식, 요청이 거부되는 경우를 정의합니다.

수집에 쓰는 값은 서버마다 IP 하나입니다. 호스트명이나 벤더 같은 다른 키를 함께 보내도 되지만 연결, 자격증명, 벤더 판단에는 쓰지 않습니다. 자격증명은 보내지 않습니다. vault에서 로딩되고, OS 종류와 BMC 제조사는 수집이 스스로 감지합니다.

## 1. 파라미터

| 파라미터 | 필수 | 형식 | 뜻 |
|---|---|---|---|
| `loc` | 필수 | 문자열 | 실행 위치. `common/vars/locations.yml`에 등록된 ID. 등록되지 않으면 실행 위치 확인 단계에서 빌드가 실패합니다 |
| `target_type` | 필수 | `os`, `esxi`, `redfish` | 수집 경로 |
| `inventory_json` | 필수 | JSON 배열 문자열 | 대상 목록 (2절) |
| `deploymentEnvironmentId` | 필수 | 문자열 | 호출자의 환경 식별자. 결과 본문에 그대로 돌려줍니다 |
| `eventUuid` | 필수 | 문자열 | 호출자의 요청 식별자. 결과 본문에 그대로 돌려주며 전송 재시도에서도 같은 값을 씁니다 |
| `callbackUrl` | 필수 | `http://` 또는 `https://` 주소 | 결과를 받을 Portal 주소. 뒤에 `/api/jenkins/gather/<target_type>` 경로를 붙여 POST하므로 `?`나 `#`이 든 주소는 거부합니다 |
| `verbosity` | 선택 | `0`~`4` | Ansible 출력 상세도. 기본 0 |

## 2. `inventory_json` 형식

`target_type`에 따라 읽는 IP 키가 다릅니다.

| target_type | 읽는 키 (앞이 우선) | 연결에 쓰지 않는 IP 키 |
|---|---|---|
| `os`, `esxi` | `service_ip` → `ip` | `bmc_ip` |
| `redfish` | `bmc_ip` → `ip` | `service_ip` |

```jsonc
// os 또는 esxi
[{"service_ip": "192.0.2.10"}, {"service_ip": "192.0.2.11"}]

// redfish (BMC 관리 IP)
[{"bmc_ip": "192.0.2.201"}, {"bmc_ip": "192.0.2.202"}]

// 하위 호환: ip 키도 읽습니다
[{"ip": "192.0.2.10"}]

// 서버 정보를 통째로 보내도 됩니다. target_type 이 고른 키 하나만 읽고 나머지는 보존합니다
[{"service_ip": "192.0.2.10", "bmc_ip": "192.0.2.201", "hostname": "server01", "vendor": "hp", "server_role": "WEB"}]
```

주 키 값이 `""`이거나 `null`이면 `ip` 키로 넘어갑니다. 값 앞뒤의 공백은 지우고 읽습니다.

결과 본문 `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson: [...]}`에서 서버별 결과의 `ip`는 위 표에서 읽은 값입니다. 보낸 객체는 결과에 다시 넣지 않으므로, Portal은 이 `ip`를 os와 esxi면 `service_ip`, redfish면 `bmc_ip`와 맞춰 자기 서버 목록에 연결합니다. 같은 서버 목록을 `target_type`만 바꿔 보내면 os와 esxi는 서비스 IP로, redfish는 BMC IP로 수집합니다.

## 3. 보내지 않는 것과 쓰지 않는 것

| 항목 | 처리 | 이유 |
|---|---|---|
| `username`, `password` | 보내지 마세요 | 계정은 vault에 있습니다. 보내면 서버별 보존값과 Jenkins 빌드 파라미터 화면에 그대로 남습니다 |
| `hostname` | 받지만 쓰지 않습니다 | 결과의 `hostname`은 장비에서 읽은 값이고 없으면 `null`입니다 (6절) |
| `vendor` | 받지만 쓰지 않습니다 | Redfish는 무인증 서비스 루트로 제조사를 감지합니다 |
| `os_family` | 받지만 쓰지 않습니다 | OS 채널은 포트와 프로토콜 확인으로 Linux와 Windows를 나눕니다 |

## 4. 서버별 추가 정보 (추가 수집용)

IP 외의 항목(예: `physical_purpose`)을 서버별로 함께 보내면 그대로 보존되어, 추가 수집(Add-on)이 그 서버에서 실행할 항목을 고르는 조건으로 씁니다. 추가 수집을 켤지는 `target_type`과 Jenkins 설정이 정하며 이 항목은 관여하지 않습니다. 보내지 않아도 기본 수집에는 영향이 없습니다.

```jsonc
[{"service_ip": "192.0.2.10", "physical_purpose": "DB"}]
```

- 키 이름과 값은 정해져 있지 않습니다. 어떤 키를 조건으로 쓸지는 Add-on 설정이 정합니다.
- 값은 글자 그대로 보존됩니다. `{{ }}`가 든 문자열도 해석되지 않습니다.
- `__ansible_`로 시작하는 키는 Ansible의 내부 표식이라 보존하지 않습니다.
- 추가 수집 결과는 `data.addon`에 들어갑니다 ([02-output-envelope.md](02-output-envelope.md)).

## 5. 요청이 통째로 거부되는 경우

대상 목록은 Jenkins의 입력 확인 단계와 각 채널의 `inventory.sh`가 같은 규칙으로 검사합니다. 한 서버라도 아래에 걸리면 요청 전체를 거부하고, 맞는 서버만 골라 수집하지 않습니다.

| 걸리는 경우 | 예 |
|---|---|
| 표준 JSON이 아님 (홑따옴표, 따옴표 없는 키, 끝 쉼표, 주석) | `[{'service_ip': '192.0.2.10'}]` |
| 배열이 아니거나 비어 있음, 원소가 객체가 아님 | `{"service_ip": "..."}`, `[]`, `["192.0.2.10"]` |
| 읽을 키가 없음 | `os` 요청에 `bmc_ip`만 있는 서버가 섞임 |
| 값이 공백뿐 | `"service_ip": "   "` (공백뿐인 값은 `ip` 키로 넘어가지 않습니다) |
| 값이 문자열이 아님 | `"service_ip": 10`, `"service_ip": ["192.0.2.10"]` |
| IPv4가 아님 | `192.0.2.10/24`, `server01`, IPv6, `10.0.0.01` (앞자리 0), 전각 숫자 |
| 같은 IP가 두 번 | 앞뒤 공백을 지운 뒤 같으면 중복입니다. 한쪽은 `service_ip`, 다른 쪽은 `ip`에 있어도 중복입니다 |

거부되면 입력 확인 단계에서 빌드가 FAILURE로 끝나고 Portal로 결과를 보내지 않습니다. 보낼 접수 목록이 없기 때문입니다. 호출자는 Jenkins 빌드 결과로 알아야 하며, 콘솔에 `ERROR: [입력 확인] …` 줄이 남습니다. 거부되지 않은 요청은 접수된 서버마다 결과가 1개씩 오고, 연결되지 않는 서버도 실패 결과로 옵니다.

### 크기

`inventory_json`은 파일로 수집 프로세스에 전달되므로 환경변수 길이 제한을 받지 않습니다. 서버 정보를 통째로 담은 5,000대(약 510 KB) 입력으로 확인했습니다. 한 요청의 대상 수는 수집 실행 한계(누적 6시간) 안에서 끝나는 범위로 정하세요 ([../operate/04-pipeline-runtime.md](../operate/04-pipeline-runtime.md)).

## 6. target_type별 동작

### os

`5986 → 5985 → 22` 순으로 포트를 열어 보고, 열린 포트에서 프로토콜(WinRM 또는 SSH)까지 확인해 Linux와 Windows를 나눕니다.

- 22 (SSH) → Linux → `vault/<loc>/os/linux.yml`
- 5986 또는 5985 (WinRM) → Windows → `vault/<loc>/os/windows.yml`
- 모두 실패 → `status: failed`

### esxi

`vault/<loc>/esxi.yml`의 계정으로 vSphere API에 접속합니다. vCenter 주소를 주면 자격증명을 보내지 않고 `protocol` 단계 실패로 끝납니다.

### redfish

1. 계정 없이 Redfish 서비스 루트를 읽어 벤더를 감지합니다.
2. 표준 수집 계정으로 인증합니다. 표준 계정은 전역 한 벌(`vault/common/redfish/standard.yml`)이라 위치도 벤더도 보지 않고, 벤더를 알아내지 못해도 시도합니다. 최종 수집은 항상 이 계정으로 합니다.
3. 표준 계정이 HTTP 401로 명시적으로 거부되면, 위치와 벤더별 복구 계정(`vault/<loc>/redfish/<vendor>.yml`)으로 표준 계정을 만들거나 비밀번호를 맞춘 뒤 표준 계정으로 다시 인증해 수집합니다.

계정 구조는 [../operate/05-vault.md](../operate/05-vault.md)에 있습니다.

### 결과의 hostname

모든 채널에서 Ansible 대상 이름은 IP입니다. 보낸 `hostname` 키는 쓰지 않습니다. 결과 봉투의 `hostname`은 장비에서 읽은 값으로 OS 호스트명 → FQDN → BMC 호스트명 순으로 채우고, 셋 다 없으면 `null`입니다. IP로 채우지 않습니다. 상세는 [03-fields.md](03-fields.md) 8절입니다.

### 자격증명

수집이 실행 중에 위치(`loc`)와 대상 종류에 맞는 vault 파일을 엽니다. 파일을 열지 못하면 빌드 전체가 멈추지 않고 그 서버가 자격증명 단계 실패 결과(`CREDENTIAL_SET_UNAVAILABLE`)로 끝납니다.

## 7. 이전 명세와의 차이

| 항목 | 이전 | 현재 |
|---|---|---|
| inventory_json 필드 | ip, hostname, username, password | IP만 읽습니다 |
| IP 외 키 | 없음 | 보존만 하고 추가 수집 조건에만 씁니다 (4절) |
| 계정 전달 | inventory_json에 포함 | vault 자동 로딩 |
| hostname | Portal이 전달 | 장비에서 읽은 값 (없으면 `null`) |
| vendor | Portal이 전달 (선택) | 자동 감지 |

## 다음

| 다음 작업 | 문서 |
|---|---|
| 받게 될 응답 형식 | [02-output-envelope.md](02-output-envelope.md) |
| 응답 필드 의미 사전 | [03-fields.md](03-fields.md) |
| 실패 시 호출자 처리 | [04-failure-and-diagnosis.md](04-failure-and-diagnosis.md) |
| Jenkins Job 호출 절차 | [../operate/03-job-registration.md](../operate/03-job-registration.md) |
