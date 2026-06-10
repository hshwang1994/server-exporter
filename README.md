# server-exporter — 서버 정보 수집 파이프라인

> **한 줄 요약**
> 호출자가 IP만 알려주면, 이 파이프라인이 OS / VMware ESXi / 서버 BMC 세 경로 중 하나로 접근해 표준 JSON 으로 정보를 돌려준다.

> 검증 기준 환경 및 최소 요구사항은 [REQUIREMENTS.md](REQUIREMENTS.md) 참조.

---

## 이 문서는 누가 읽나

| 역할 | 이 문서로 얻는 것 |
|------|------------------|
| 처음 들어온 사람 | 5분 안에 "이 시스템이 뭘 하는지" 파악 |
| 호출자 시스템 개발자 | "내가 무엇을 보내고, 무엇을 받는지" 윤곽 |
| 운영자 | 어디서부터 설치 문서를 읽어야 하는지 안내 |
| 새 개발자 | 디렉터리 구조와 책임 분리의 큰 그림 |

상세 절차는 본 문서 끝 ["다음에 읽을 문서"](#다음에-읽을-문서) 표에서 역할별로 안내한다.

---

## 5분 빠른 이해

```text
호출자 시스템 (포털 / 백엔드)
  │
  │  HTTPS 443 으로 Jenkins Job 트리거
  │  파라미터: loc, target_type, inventory_json
  ▼
Jenkins Job (server-exporter.{os,esxi,redfish}-gather)
  │
  │  4-Stage 파이프라인:
  │   Stage 1  Validate         입력값 검증
  │   Stage 2  Gather           ansible-playbook 실행
  │   Stage 3  Validate Schema  필드 정합성 검증 (FAIL 게이트)
  │   Stage 4  E2E Regression   기준선 회귀 테스트 (FAIL 게이트)
  ▼
표준 JSON envelope (schema_version: "1")
  - 13 필드 (target_type / status / sections / data / errors / diagnosis ...)
  - 3 채널 모두 동일한 형식
```

3 채널이 같은 JSON 형식을 돌려준다는 점이 핵심이다.
호출자 시스템은 한 가지 파서로 OS, ESXi, BMC 응답을 모두 처리할 수 있다.

---

## 핵심 약속

server-exporter 는 다음 3가지를 호출자에게 약속한다.

1. **호출자는 IP 만 보낸다.** 자격증명 / 호스트명 / 벤더 정보는 호출자 책임이 아니다.
   계정은 vault 에 보관되고, OS 종류와 BMC 제조사(Manufacturer) 는 파이프라인이 자동으로 감지한다.

2. **응답 형식은 어떤 상황에도 동일하다.** 네트워크 단절 / 인증 실패 / 일부 섹션 실패 같은
   모든 실패 상황에서도 `schema_version: "1"` 을 가진 같은 envelope 가 반환된다.
   호출자는 envelope 의 `status` 와 `errors` 만 보고 처리하면 된다.

3. **새 벤더 / 새 세대 추가는 코드 수정 없이 가능하다.** Adapter YAML 1~3개 추가만으로 끝난다.
   site.yml, Python 코드, callback 은 모두 vendor-agnostic 으로 유지된다.

---

## 디렉터리 구조

```text
server-exporter/
├── Jenkinsfile              파이프라인 정의 (호출자 진입점)
├── Jenkinsfile_portal       포털 callback 전용 파이프라인
├── ansible.cfg              프로젝트 Ansible 설정
│
├── vault/                   인증 정보 (ansible-vault 로 암호화)
│   ├── linux.yml / windows.yml / esxi.yml
│   └── redfish/{vendor}.yml 벤더별 BMC 계정
│
├── common/tasks/normalize/  Fragment 병합·정규화 (3 채널 공통 로직)
├── common/library/          Python 모듈 (precheck 등)
│
├── os-gather/               Linux / Windows 수집
├── esxi-gather/             VMware ESXi 수집 (vSphere API)
├── redfish-gather/          서버 BMC 수집 (Redfish API)
│
├── adapters/                벤더 / 세대별 어댑터 YAML
│   ├── redfish/             31개 (Dell / HPE / Lenovo / Supermicro / Cisco / Huawei / Inspur / Fujitsu / Quanta 9 벤더 — HPE 계열에 Superdome Flex, CSUS 3200 포함)
│   ├── os/                  7개 (Linux / Windows 변형)
│   └── esxi/                4개 (ESXi 6.x / 7.x / 8.x)
│
├── schema/                  표준 JSON 스키마
│   ├── sections.yml         10 섹션 정의
│   ├── field_dictionary.yml 83 필드 사전 (호출자 reference)
│   ├── fields/              채널별 필드 정의
│   ├── examples/            success / partial / failed 예시
│   └── baseline_v1/         실장비 회귀 기준선 JSON
│
├── tests/                   회귀 / 검증
│   ├── fixtures/            실장비 raw 응답
│   └── e2e/, e2e_browser/   백엔드·브라우저 E2E
│
└── docs/                    설치 / 운영 / 개발 문서 (01~23)
```

이렇게 나눈 이유:
- **gather 채널 분리** — Linux 이슈가 ESXi 수집에 영향을 주지 않게 한다.
- **common 분리** — 3 채널이 같은 JSON 을 만들도록 정규화 로직을 한 곳에 둔다.
- **adapters 분리** — 벤더 변경이 gather 코드에 침입하지 않게 한다.
- **schema 분리** — 호출자 계약(필드 의미)이 코드와 독립적으로 보존된다.

---

## 호출자 입력 (Input)

| 파라미터 | 필수 | 설명 |
|---------|------|------|
| `loc` | 필수 | 어느 사이트 Agent 에서 실행할지 (예: `ich`, `chj`, `yi`) |
| `target_type` | 필수 | `os` / `esxi` / `redfish` 중 하나 |
| `inventory_json` | 필수 | 대상 IP 배열 (아래 예시 참조) |

```jsonc
// target_type: os 또는 esxi
[{"service_ip": "10.x.x.1"}, {"service_ip": "10.x.x.2"}]

// target_type: redfish (BMC 관리 IP)
[{"bmc_ip": "10.x.x.201"}, {"bmc_ip": "10.x.x.202"}]
```

호출자는 호스트명 / 자격증명 / 벤더를 보내지 않는다.
상세 명세는 [docs/05_inventory-json-spec.md](docs/05_inventory-json-spec.md).

---

## 표준 응답 (Output)

호출자는 다음 13 필드의 JSON envelope 를 받는다. 어떤 채널이든, 어떤 결과든 형식은 같다.

```jsonc
{
  "schema_version":    "1",
  "target_type":       "os | esxi | redfish",
  "collection_method": "agent | vsphere_api | redfish_api",
  "ip":                "10.x.x.1",
  "hostname":          "10.x.x.1",
  "vendor":            "dell | hp | hpCsus | lenovo | supermicro | cisco | null",
  "status":            "success | partial | failed",
  "sections":          { "system": "success", "cpu": "success", ... },
  "diagnosis":         { "reachable": true, "auth_success": true, "failure_stage": null, "details": {...} },
  "meta":              { "duration_ms": 1234, "adapter_id": "...", "ansible_version": "..." },
  "correlation":       { "serial_number": "...", "host_ip": "...", "bmc_ip": "..." },
  "errors":            [ ... ],
  "data":              { "system": {...}, "cpu": {...}, ... }
}
```

- 각 필드 의미: [docs/20_json-schema-fields.md](docs/20_json-schema-fields.md) (정본 사전)
- 채널별 실제 예시: [docs/09_output-examples.md](docs/09_output-examples.md)
- 필드 단위 lookup 메타데이터: `schema/field_dictionary.yml`

### sections 값의 의미

| 값 | 뜻 | 호출자 처리 |
|----|-----|------------|
| `success` | 그 섹션이 정상 수집됨 | data.<section> 사용 |
| `failed` | 지원 채널인데 이번에 실패 | errors[] 확인 후 재시도 또는 알림 |
| `not_supported` | 이 채널/벤더에서는 원래 수집 불가 | 누락이 아닌 정상 |

### data.memory.total_basis 처럼 의미가 미묘한 enum

| 값 | 의미 |
|----|------|
| `physical_installed` | 물리 메모리 (dmidecode / Win32_PhysicalMemory / Redfish DIMM) |
| `os_visible` | OS 가 인식한 메모리 (Linux 의 일부 환경 fallback) |
| `hypervisor_visible` | 하이퍼바이저가 인식한 메모리 (ESXi) |

전체 enum / null 의미는 `schema/field_dictionary.yml` 참조.

---

## 실패 상황별 동작

호출자가 받게 될 envelope 의 모양을 정리한다.

| 상황 | status | sections | errors |
|------|--------|----------|--------|
| SSH / WinRM 응답 없음 (포트 닫힘) | `failed` | 모두 `failed` | precheck 단계 메시지 |
| 인증 실패 | `failed` | 모두 `failed` | auth_failed |
| OS 수집 일부만 실패 (예: storage 권한 부족) | `partial` | 일부 `failed` | 해당 섹션 메시지 |
| Redfish 연결 실패 | `failed` | 모두 `failed` | network 또는 protocol |
| Redfish 일부 섹션 미지원 | `success` 또는 `partial` | 미지원은 `not_supported` | 비어있을 수 있음 |
| ESXi API 라이선스 부족 (Free) | `failed` | 모두 `failed` | api_unavailable |

상세 로직은 [docs/08_failure-handling.md](docs/08_failure-handling.md).

---

## 채널별 가져오는 정보 요약

### OS 채널 (Linux / Windows)
- Linux: SSH 22 → `dmidecode`(메모리 / 시리얼) / `lsblk` / `ip addr` / `getent` / `lastlog`
- Windows: WinRM 5985/5986 → `Get-CimInstance` / `Get-LocalUser` / `Get-Volume`
- Linux 는 Python 미설치 / 구버전 환경을 위한 raw fallback 경로 보유

### ESXi 채널 (VMware)
- vSphere API 443 (HTTPS)
- `vmware_host_facts`, `vmware_host_config_info`, `vmware_datastore_info`

### Redfish 채널 (BMC)
- 표준 라이브러리만 사용 (외부 패키지 의존 없음)
- BMC 인증을 2단계로 처리: 무인증 ServiceRoot 호출 → 제조사 확인 → 해당 벤더 vault 로딩 → 재수집
- 지원 벤더 (9개 + 서브라인):
  - Dell iDRAC 7 ~ 10
  - HPE iLO 4 ~ 7 + Superdome Flex / Flex 280
  - Lenovo IMM2 ~ XCC3
  - Supermicro X9 ~ X14
  - Cisco CIMC M4 ~ M8 + UCS X-Series
  - Huawei iBMC, Inspur ISBMC, Fujitsu iRMC, Quanta QCT BMC
- Dell iDRAC 8 / HPE iLO 4 / Lenovo IMM2 는 fallback adapter 로 storage/power 까지 거의 모든 섹션을 수집한다 (일부 필드 `null` 가능 — FB). Supermicro X9 만 storage/firmware/power 를 `not_supported` 로 보고한다. 세대별 상세는 [docs/22_compatibility-matrix.md](docs/22_compatibility-matrix.md).

(약어 풀이: BMC = Baseboard Management Controller / iDRAC = Integrated Dell Remote Access Controller / iLO = Integrated Lights-Out / XCC = Lenovo XClarity Controller / CIMC = Cisco Integrated Management Controller)

---

## 다음에 읽을 문서

| 역할 | 권장 순서 |
|------|----------|
| 운영자 (Jenkins / 인프라) | [01](docs/01_jenkins-setup.md) → [03](docs/03_agent-setup.md) → [04](docs/04_job-registration.md) → [21](docs/21_vault-operations.md) |
| 호출자 (외부 시스템) | [05](docs/05_inventory-json-spec.md) → [09](docs/09_output-examples.md) → [20](docs/20_json-schema-fields.md) |
| 개발자 (새 벤더 / 섹션 추가) | [06](docs/06_gather-structure.md) → [07](docs/07_normalize-flow.md) → [10](docs/10_adapter-system.md) → [14](docs/14_add-new-gather.md) |
| 검증 담당 | [13](docs/13_redfish-live-validation.md) → [22](docs/22_compatibility-matrix.md) |
| 결정 추적 (왜 지금 이 모습?) | [19](docs/19_decision-log.md) |
| 환경 사전 점검 | [REQUIREMENTS.md](REQUIREMENTS.md) |

Fragment 기반 수집 철학과 변수 규칙, 새 gather 추가 절차는 [docs/07_normalize-flow.md](docs/07_normalize-flow.md) 와 [docs/14_add-new-gather.md](docs/14_add-new-gather.md) 참조.
