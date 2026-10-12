# server-exporter: 서버 정보 수집 파이프라인

호출자가 서버의 IP 주소만 보내면 이 파이프라인이 OS(Linux, Windows), VMware ESXi, 서버 BMC(Redfish) 세 경로 중 하나로 접속해 같은 형식의 JSON으로 정보를 돌려줍니다.
환경 요건은 [REQUIREMENTS.md](REQUIREMENTS.md), 문서 전체 지도는 [docs/README.md](docs/README.md)에 있습니다.

## 누가 읽나

| 역할 | 이 문서에서 얻는 것 | 이어서 읽을 문서 |
|---|---|---|
| 처음 보는 사람 | 무엇을 하는 시스템인지 | [docs/overview/01-what-and-why.md](docs/overview/01-what-and-why.md) |
| 호출자(Portal) 개발자 | 무엇을 보내고 무엇을 받는지 | [docs/contract/01-input.md](docs/contract/01-input.md) |
| 운영자 | 어디서부터 설치하는지 | [docs/operate/01-jenkins-master.md](docs/operate/01-jenkins-master.md) |
| 개발자 | 저장소 구조와 책임 분리 | [docs/develop/01-gather-structure.md](docs/develop/01-gather-structure.md) |

## 동작 개요

```text
호출자 (Portal)
  │  Jenkins Job 호출 (파라미터: loc, target_type, inventory_json, deploymentEnvironmentId, eventUuid, callbackUrl)
  ▼
Jenkins Controller — Jenkinsfile_portal
  1. 입력 확인          파라미터 형식과 대상 목록 검사. 한 대라도 틀리면 요청 전체 거부
  2. 실행 위치 확인     loc → Runner 라벨 (common/vars/locations.yml)
  3. 서버 정보 수집     Runner 에서 저장소 checkout → ansible-playbook (target_type 별 site.yml)
  4. 결과 확인 및 전송  Controller 에서 결과 회수 → 접수 수와 결과 수 대조 → callbackUrl 로 POST
  ▼
서버마다 JSON 봉투 1개 (schema_version "1", 최상위 13 필드)
```

- 세 채널이 같은 봉투 형식을 돌려주므로 호출자는 파서 하나로 처리합니다.
- 접속 계정은 저장소의 암호화된 vault에 있고, OS 종류와 BMC 제조사는 파이프라인이 감지합니다. 호출자는 계정, 호스트명, 벤더를 보내지 않습니다.
- 연결 실패, 인증 실패, 일부 섹션 실패 모두 같은 형식의 봉투로 돌아옵니다. 접수한 서버 수와 결과 봉투 수는 항상 같습니다.

## 입력

| 파라미터 | 필수 | 뜻 |
|---|---|---|
| `loc` | 필수 | 실행 위치. `common/vars/locations.yml`에 등록된 ID |
| `target_type` | 필수 | `os`, `esxi`, `redfish` 중 하나 |
| `inventory_json` | 필수 | 대상 목록 JSON 배열 |
| `deploymentEnvironmentId` | 필수 | 호출자의 환경 식별자. 결과 본문에 그대로 돌려줍니다 |
| `eventUuid` | 필수 | 호출자의 요청 식별자. 결과 본문에 그대로 돌려줍니다 |
| `callbackUrl` | 필수 | 결과를 받을 Portal 주소 |
| `verbosity` | 선택 | ansible 출력 상세도 (기본 0) |

```jsonc
// target_type 이 os 또는 esxi
[{"service_ip": "192.0.2.10"}, {"service_ip": "192.0.2.11"}]
// target_type 이 redfish (BMC 관리 IP)
[{"bmc_ip": "192.0.2.201"}]
```

상세는 [docs/contract/01-input.md](docs/contract/01-input.md)에 있습니다.

## 출력

호출자는 서버마다 다음 13개 필드의 봉투를 받습니다.

```jsonc
{
  "schema_version":    "1",
  "target_type":       "os | esxi | redfish",
  "collection_method": "agent | vsphere_api | redfish_api",
  "ip":                "192.0.2.10",
  "hostname":          "server01",            // 장비에서 읽은 값. 없으면 null (IP 로 대체하지 않습니다)
  "vendor":            "dell | hp | hpCsus | lenovo | supermicro | cisco | huawei | inspur | fujitsu | quanta | vmware | qemu | microsoft | xen | null",
  "status":            "success | partial | failed",
  "sections":          { "system": "success", "cpu": "success", "bmc": "not_supported", ... },
  "diagnosis":         { "reachable": true, "auth_success": true, "failure_stage": null, "failure_code": null, "failure_reason": null, "details": {...} },
  "meta":              { "started_at": "...", "duration_ms": 1234, "adapter_id": "...", ... },
  "correlation":       { "serial_number": "...", "system_uuid": "...", "host_ip": "...", "bmc_ip": null },
  "errors":            [ { "section": "...", "message": "...", "detail": "..." } ],
  "data":              { "system": {...}, "cpu": {...}, ... }
}
```

- 필드 사전: [docs/contract/03-fields.md](docs/contract/03-fields.md)
- 봉투 모양과 채널별 예시: [docs/contract/02-output-envelope.md](docs/contract/02-output-envelope.md)
- 실패했을 때 읽는 법: [docs/contract/04-failure-and-diagnosis.md](docs/contract/04-failure-and-diagnosis.md)

`sections`의 값은 `success`(채웠음), `failed`(지원하는데 이번에 못 채움), `not_supported`(이 경로로는 원래 못 얻음) 셋입니다. 섹션은 11개(`system`, `hardware`, `bmc`, `cpu`, `memory`, `storage`, `network`, `firmware`, `users`, `power`, `thermal`)이고 항상 모두 나옵니다.

| 채널 | `success`로 나오는 섹션 |
|---|---|
| OS (Linux, Windows) | system, hardware, cpu, memory, storage, network, users |
| ESXi | system, hardware, cpu, memory, storage, network |
| Redfish | hardware, bmc, cpu, memory, storage, network, firmware, power, thermal |

## 채널별 접속 방식

| 채널 | 접속 | 수집 방법 |
|---|---|---|
| OS Linux | SSH 22 | 셸 명령과 `/proc`, `/sys` 읽기. 대상에 Python 3.9 이상이 있으면 Ansible 모듈 경로, 없거나 낮으면 같은 결과를 내는 raw 경로 |
| OS Windows | WinRM 5986 또는 5985 (NTLM) | PowerShell과 CIM 조회 |
| ESXi | HTTPS 443 (vSphere API) | `community.vmware` 모듈과 pyvmomi |
| Redfish | HTTPS 443 | 표준 Redfish API. 무인증 서비스 루트로 제조사를 감지하고 표준 계정으로 인증 |

Redfish는 벤더와 세대별 어댑터 YAML(`adapters/redfish/`)이 응답 차이를 흡수합니다. 어느 벤더와 세대를 실장비로 확인했는지는 [REQUIREMENTS.md](REQUIREMENTS.md)와 [docs/reference/compatibility-matrix.md](docs/reference/compatibility-matrix.md)에 있습니다.

## 저장소 구조

```text
Jenkinsfile_portal        수집 파이프라인 (호출자 진입점). Jenkinsfile_portal_Byid 는 기본값 1줄만 다른 사본
Jenkinsfile_ci            사내 개발 저장소 전용 CI 진입점
ansible.cfg               프로젝트 Ansible 설정
production_manifest.yml   배포본(production 브랜치)에 들어가는 파일 목록
os-gather/                Linux, Windows 수집 (site.yml, inventory.sh, tasks/)
esxi-gather/              ESXi 수집
redfish-gather/           BMC 수집 (library/redfish_gather.py 가 Redfish 호출)
common/                   세 채널 공통: 사전 진단, 자격증명 로딩, 정규화, 변수 정본 (common/vars/)
adapters/                 벤더, 세대, OS 종류별 어댑터 YAML (redfish/, os/, esxi/)
vault/                    암호화된 계정 파일 (vault/<loc>/..., vault/common/redfish/standard.yml)
callback_plugins/         json_only: 결과 봉투와 진행 기록 출력
filter_plugins/ lookup_plugins/ module_utils/   정규화 필터, 어댑터 선택, 공용 Python 모듈
scripts/                  Jenkins 가 부르는 수집, 보존, 정리 스크립트와 운영자 도구
schema/                   섹션 정의, 필드 사전, 예제, 실장비 기준선 (개발 저장소 전용)
tests/                    단위, 통합, 회귀 시험과 fixture (개발 저장소 전용)
docs/                     설치, 운영, 계약, 개발 문서
```

이렇게 나눈 이유는 다음과 같습니다.

- 채널을 나눠 한 채널의 문제가 다른 채널에 번지지 않게 합니다.
- 정규화를 `common/`에 모아 세 채널이 같은 봉투를 만들게 합니다.
- 벤더 차이를 `adapters/`에 두어 수집 코드에 벤더 분기를 넣지 않습니다.
- 호출자 계약(필드 의미)을 `schema/`와 `docs/contract/`에 두어 코드와 따로 보존합니다.

## 브랜치

사내 개발 저장소는 `main`(개발)과 `production`(배포본) 두 브랜치를 씁니다. `production`은 생성기가 `main`의 특정 커밋에서 운영에 필요한 파일만 뽑아 만듭니다. 고객사 저장소는 `main` 하나이며 사내 `production`의 내용을 받습니다. 절차는 [docs/operate/09-production-branch.md](docs/operate/09-production-branch.md)와 [docs/operate/07-update-and-rollback.md](docs/operate/07-update-and-rollback.md)에 있습니다.

## 다음에 읽을 문서

| 역할 | 순서 |
|---|---|
| 운영자 | [operate/01](docs/operate/01-jenkins-master.md) → [02](docs/operate/02-agent-node.md) → [03](docs/operate/03-job-registration.md) → [05](docs/operate/05-vault.md) |
| 호출자 | [contract/01](docs/contract/01-input.md) → [02](docs/contract/02-output-envelope.md) → [03](docs/contract/03-fields.md) → [04](docs/contract/04-failure-and-diagnosis.md) |
| 개발자 | [develop/01](docs/develop/01-gather-structure.md) → [02](docs/develop/02-normalize-flow.md) → [03](docs/develop/03-adapter-system.md) → [04](docs/develop/04-add-vendor.md) |
| 검증 기록 | [reference/live-validation.md](docs/reference/live-validation.md), [reference/compatibility-matrix.md](docs/reference/compatibility-matrix.md) |
| 결정 이력 | [reference/decision-log.md](docs/reference/decision-log.md) |
