# 20. JSON 출력 — 받았는데 무슨 뜻이지?

## 이 문서는 누가 읽나

server-exporter 가 던져주는 JSON 을 **받아서 쓰는 쪽** 사람들이 본다. 화면에 띄우든, DB 에 넣든, 알람을 만들든 — 일단 "이 필드가 뭘 의미하나" 를 알아야 시작이 된다.

이 문서를 끝까지 읽으면 다음 4가지를 안다.

1. JSON 한 통이 어떻게 생겼는지 (예시 1개 통째로)
2. 최상위 13개 키가 각각 뭘 가리키는지
3. `status` 가 `success` 인데 `errors` 가 비어있지 않을 수 있는지 (있다)
4. OS / ESXi / Redfish 채널마다 뭐가 다른지

코드 / 주석 달린 실물 JSON 을 먼저 보고 싶으면 → `schema/output_examples/redfish_dell_idrac9.jsonc` 부터 보면 빠르다.

---

## 1. 일단 한 통 생긴 모양

Dell PowerEdge R740 한 대를 Redfish 로 수집한 결과 (요약). 실물 전체는 `schema/baseline_v1/dell_baseline.json`.

```json
{
  "target_type": "redfish",
  "collection_method": "redfish_api",
  "ip": "10.50.11.162",
  "hostname": "LENOVO01",
  "vendor": "dell",

  "status": "success",
  "sections": {
    "system":  "not_supported",
    "hardware":"success",
    "bmc":     "success",
    "cpu":     "success",
    "memory":  "success",
    "storage": "success",
    "network": "success",
    "firmware":"success",
    "users":   "not_supported",
    "power":   "success",
    "thermal": "success"
  },

  "diagnosis": {
    "reachable": true, "port_open": true,
    "protocol_supported": true, "auth_success": true,
    "failure_stage": null, "failure_reason": null
  },
  "meta":         { "duration_ms": 106000, "adapter_id": "redfish_dell_idrac9" },
  "correlation":  { "serial_number": "...", "bmc_ip": "10.50.11.162", "host_ip": "10.50.11.162" },
  "errors":       [],

  "data": {
    "hardware": { "vendor": "Dell Inc.", "model": "PowerEdge R740", "health": "Critical", ... },
    "bmc":      { "name": "iDRAC", "firmware_version": "4.00.00.00", "ip": "10.50.11.162" },
    "cpu":      { "sockets": 2, "cores_physical": 24, ... },
    "memory":   { "total_mb": 655360, "total_basis": "physical_installed", ... },
    "storage":  { "physical_disks": [...], "logical_volumes": [...], ... },
    "network":  { "interfaces": [...], "summary": {...} },
    "firmware": [ { "name": "BIOS", "version": "2.21.2", "component": "...", "updateable": true, "category": "bios", "pending": false }, ... ],
    "power":    { "power_supplies": [...], "power_control": {...} },
    "users":    [],
    "system":   { "hostname": "LENOVO01", "fqdn": null, ... }
  },
  "schema_version": "1"
}
```

> 2026-06-15: `firmware[].category` (bios/cpld/tpm/drive/
> backplane/nic/storage_controller/psu/... id·name 추론) + `firmware[].pending` (적용 보류) 정식 등록.
> `cpu.architecture` 는 redfish 채널도 emit (channel=[redfish,os,esxi]).
>
> 2026-10-10: `cpu.summary.groups[].l2_cache_kb` · `l3_cache_kb` 는 그대로 **소켓당 KB** 다(의미 불변). Linux 는 lscpu 값이 합계인지
> 인스턴스당인지를 util-linux 버전으로 가른다 — 2.34 이상(`(N instances)` 문구 유무와 무관)은 합계라 소켓 수로 나누고, 2.33 이하는
> 인스턴스당 값이다. 버전을 알 수 없고 문구도 없으면 추측하지 않는다(L2 `null`, L3 는 `/proc/cpuinfo` 값).
> 2026-10-10 (후속): 구형 lscpu(<2.34)가 인스턴스 하나의 값만 줄 때는 sysfs(`shared_cpu_list`)로 센 인스턴스 수로 소켓당 합계를 만든다 — AMD(Zen) 는
> L3 가 CCX 마다 있어 "L3 = 소켓당 1개" 가정이 틀렸다. sysfs 를 읽지 못하면 종전 가정으로 떨어진다. lab 에 AMD 가 없어 공개 사양 재현(fixture) 수준이다.

이 JSON 한 통이 보내는 메시지를 한 줄씩 풀면 이렇다.

> "10.50.11.162 라는 BMC 에 Redfish 로 붙어서 1분 46초 동안 8개 섹션을 다 수집했다. 다만 `hardware.health` 가 `Critical` 인데, 이유는 `data.power.power_supplies[]` 에서 PS1 이 `UnavailableOffline` 이라서다. 수집 자체는 성공이고 (`status: success` / `errors: []`), 장비 자체에 PSU 1대 fault 가 있는 상태."

여기서 중요한 게 두 가지다.

- **`status: success`** = 수집이 성공했다는 뜻. **장비가 정상이라는 뜻이 아니다.**
- **장비 정상 여부**는 `data.hardware.health` 와 각 섹션 안의 `health` 필드를 본다.

이 둘을 헷갈리면 알람이 죄다 어긋난다.

---

## 2. 최상위 13개 키 — 그룹으로 묶어서

13개를 한꺼번에 보면 어지러우니 의미별로 4그룹.

### 그룹 A — 누구한테 갔다 왔는지 (5개)

| 키 | 무슨 값 | 의미 |
|---|---|---|
| `target_type` | `os` / `esxi` / `redfish` | 어떤 채널로 수집했나 |
| `collection_method` | `agent` / `vsphere_api` / `redfish_api` | 실제로 쓴 방법. `target_type` 에 따라 자동으로 결정 |
| `ip` | 문자열 | 호출자가 넘긴 대상 IP. Redfish 면 BMC IP, OS 면 서버 IP |
| `hostname` | 문자열\|null | 풀어낸 호스트명. `system.hostname → system.fqdn → bmc.network_hostname → null` (IP fallback 안 함, 2026-06-16). 실패 envelope 과 `always` 최종 fallback 도 같은 체인 (2026-09-03). 2026-10-03 부터 **콜백이 보충하는 envelope 과 Redfish `always` fallback 도 같다** — `hostname=null`, `sections` 11 키(채널 지원 섹션은 `failed`, 나머지 `not_supported`), `meta` 6 키, `correlation` 4 키, `data` 빈 뼈대. 실패 종류에 따라 다른 모양을 보지 않는다. 상세: 8절 |
| `vendor` | `dell` / `hp` / `hpCsus` / `lenovo` / `supermicro` / `cisco` / `huawei` / `inspur` / `fujitsu` / `quanta` / `vmware` / `qemu` / `microsoft` / `xen` / `null` | 호출자 노출 표시값. 가상 머신(OS 채널)은 DMI 제조사가 하이퍼바이저라 `vmware`·`qemu`·`microsoft`·`xen` 이 나갑니다(`common/tasks/normalize/resolve_vendor.yml`). 내부 canonical(`hpe`)을 `vendor_output_display`/`adapter_output_display`(vendor_aliases.yml)로 매핑. HPE 계열→`hp`, HPE Compute Scale-up 패밀리(CSUS 3200 + Superdome Flex)→`hpCsus`(camelCase 예외, 2026-06-04 결정). 대부분 소문자 한 단어 |

### 그룹 B — 결과 (2개)

| 키 | 무슨 값 | 의미 |
|---|---|---|
| `status` | `success` / `partial` / `failed` | **수집 결과**. 장비 상태 아님 |
| `sections` | 섹션 11개 각각 `success` / `failed` / `not_supported` | 섹션별 결과 |

`status` 가 어떻게 결정되는지는 4절에서 따로 정리.

### 그룹 C — 무슨 일이 있었는지 (4개)

| 키 | 무슨 값 | 의미 |
|---|---|---|
| `diagnosis` | 객체 | precheck 진단(TCP 도달 → 프로토콜 → 인증) 결과. 어디서 막혔는지 |
| `meta` | 객체 | 시작/종료 시각, 소요 시간, 사용된 adapter ID. 소요 시간(`duration_ms`)은 그 대상 한 대의 시작~끝이며 Add-on 이 켜진 빌드에서는 Add-on 실행 시간이 포함된다(끝 시각을 Add-on 종료 시각으로 다시 적는다 — 2026-10-03 부터, 상세 `docs/contract/02-output-envelope.md`) |
| `errors` | 배열 | 수집 중 발생한 오류 목록. 정상이면 `[]` |
| `correlation` | 객체 | 시리얼 / UUID / IP — 다른 시스템 데이터와 묶을 때 쓰는 키들 |

### 그룹 D — 알맹이 (2개)

| 키 | 무슨 값 | 의미 |
|---|---|---|
| `data` | 객체 | 실제 수집한 정보. 섹션별로 들어있음 |
| `schema_version` | `"1"` | envelope 자체 버전. 깨지는 변경 시 `"2"` 로 올라감 |

---

## 3. 섹션 11개 — 어떤 채널이 뭘 채우나

JSON 의 `sections` 와 `data` 는 같은 11개 키를 갖는다. 각 채널이 채울 수 있는 영역이 다르다.

| 섹션 | 무엇 | OS | ESXi | Redfish |
|---|---|:-:|:-:|:-:|
| `system` | 운영체제 / 호스트명 / 가동시간 | O | O | (X) |
| `hardware` | 벤더 / 모델 / 시리얼 / BIOS | O | O | O |
| `bmc` | iDRAC / iLO / XCC 자체 정보 | | | O |
| `cpu` | 소켓 / 코어 / 모델 | O | O | O |
| `memory` | 총량 / DIMM 슬롯 | O | O | O |
| `storage` | 디스크 / RAID / 파일시스템 | O | O | O |
| `network` | NIC / IP / DNS / 게이트웨이 | O | O | O |
| `firmware` | 펌웨어 인벤토리 | | | O |
| `users` | OS 로컬 계정 | O | | |
| `power` | PSU / 전력 사용 | | | O |
| `thermal` | 온도 센서 / 팬 (Chassis/Thermal) | | | O |

Redfish `data` 에는 섹션이 아닌 보조 키도 있다 — `multi_node`(9절)와 `bios`(6.8절). 이 둘은 `sections` 에 나오지 않고 `status` 판정에도 쓰이지 않는다.
추가 수집(Add-on)을 쓰는 환경에서는 채널과 관계없이 보조 키 `addon` 이 붙을 수 있다. 이것도 `sections` · `status` 와 무관하다 ([02-output-envelope.md](02-output-envelope.md) data 절).

(X) = `not_supported`. 그 채널 특성상 원래 못 가져오는 영역이다. 수집 실패와 다른 의미다.
`not_supported` 판정 신호는 **HTTP 404(엔드포인트 부재)만**이다. 400 등 다른 실패는 `failed` 로 남아 `errors[]` 에 보인다.
(2026-08-03: 400 도 미지원으로 보려다 되돌림 — 사이트 사례의 400 은 장비 미지원이 아니라 **수집 측 경로 오류**였다.
400 을 미지원으로 분류하면 수집 측 버그가 `not_supported` 로 조용히 덮인다.)
2026-09-03: `hardware` 를 OS 채널 정식 섹션으로 배선 — Linux 는 DMI(setup fact → `/sys/class/dmi/id`), Windows 는 `Win32_ComputerSystem`/`Win32_BIOS`. 종전에는 Windows 만 스키마 밖에서 냈고 Linux 는 모델·BIOS 를 버렸다.
2026-06-15: `thermal` 을 `sections` 맵에 정식 배선 (이전엔 `data.thermal` 만 채워지고 `sections.thermal` 누락. 이제 redfish 는 수집 성공 시 `success`, os/esxi 는 `not_supported`).

같은 서버라도 채널별로 채워지는 영역이 다르다는 게 핵심. 예를 들어:
- Dell 서버를 **Redfish** 로 보면 `bmc` / `firmware` / `power` 가 풍부하고 OS 정보는 없다.
- 같은 서버에 **OS-gather** 로 Linux 에 들어가면 `system` / `users` 가 채워지지만 `bmc` / `firmware` / `power` 는 비어있다.

두 채널을 동시에 호출해 결과를 합치면 한 서버의 그림이 완성된다.

---

## 4. `status` 는 어떻게 정해지나 — 4가지 시나리오

호출하는 쪽에서 가장 자주 헷갈리는 부분이다. 표로 정리하면:

| 시나리오 | `status` | `errors` | `sections` | 어떤 상황 |
|---|---|---|---|---|
| **A. 완전 성공** | `success` | `[]` | 모두 `success` 또는 `not_supported` | 인증 통과 + 모든 지원 섹션 수집됨 |
| **B. 성공이지만 부속 문제 있음** | `success` | 비어있지 않음 | 모두 `success` 또는 `not_supported` | 수집은 다 됐는데, 장비 어딘가에 문제가 있어 **기록**만 errors[] 에 남김 |
| **C. 부분 성공** | `partial` | 비어있지 않음 | 일부 `failed`, 나머지 `success`/`not_supported` | 인증은 됐는데 일부 섹션 응답이 안 옴 (예: firmware endpoint 만 timeout) |
| **D. 실패** | `failed` | 비어있지 않음 (첫 원소 = 대표 사유) | 거의 다 `failed` | 사전 점검(도달/포트/프로토콜/인증)에서 막혔거나, 수집까지 갔는데 성공 섹션이 0개 |
| **E. 필수 식별자 누락 (OS 채널만)** | `failed` | 비어있지 않음 | `success` 가 섞여 있을 수 있음 | 인증은 통과했고 다른 섹션은 수집됐지만 **Serial Number 를 끝내 얻지 못함**. `data` 의 수집 값은 그대로 남는다 (2026-10-13 사용자 정책) |

> **E 는 섹션 규칙 위에 얹힌 유일한 예외다 (2026-10-13).** OS 채널(Linux · Windows)에서 Serial Number 는 필수 식별자다.
> `correlation.serial_number`(= `hardware.serial` → `system.serial_number`)가 `null` 이면 `os-gather/tasks/normalize/require_serial.yml` 이
> 조립된 봉투의 `status` 를 `failed` 로 확정한다. `sections` · `data` · `hostname` · `meta` · `correlation` 은 바꾸지 않는다 — 호출자는
> `status: failed` 인데 `sections.cpu: success` 이고 `data.cpu` 가 차 있는 봉투를 받을 수 있다. 원인은 `diagnosis.failure_code: GATHER_FAILED`
> + `diagnosis.details.serial_number.cause`(`privilege_unavailable` · `read_failed` · `not_provided` · `facts_failed` · `not_collected`)
> 와 Linux 의 `diagnosis.details.sudo` 로 가른다. 인증 단계에서 끝난 봉투(`failure_stage: auth`)에는 적용하지 않는다.
> 사용자 문장은 하나다: "OS 내부에서 Serial Number를 수집하지 못했습니다. Vault에 등록된 OS 계정의 권한 및 서버의 Serial Number 제공 여부를 확인하세요."

> **보조(OEM) 단계 실패는 D 가 아니다 (2026-06-16, redfish).** vendor OEM 수집/정규화는 표준 섹션 수집 **뒤**에 도는 보조 단계다.
> 여기서 예외가 나도 표준 섹션은 그대로 `success` 로 유지되고, OEM 실패는 `errors[]` 에 `section: "oem"` 경고로만 남는다
> (→ 시나리오 B, 또는 일부 표준 섹션이 실패했으면 C). 즉 OEM 한 단계 실패가 전체를 `failed` 로 만들지 않는다.
> (`redfish-gather/site.yml` 의 OEM local block/rescue — 과거엔 단일 top-level rescue 로 cascade 되어 표준 섹션까지 전부 `failed` 였음.)

> **보조 수집 실패도 C 가 아니다 (2026-08-03, redfish `network`).** `network` 섹션은 두 갈래로 모은다.
> **주** = 호스트 NIC/IP(`Systems/{id}/EthernetInterfaces`) → `data.network.interfaces[]` 등,
> **보조** = NIC 카드 모델·펌웨어(`Chassis/{id}/NetworkAdapters`) → `data.network.adapters[]` / `ports[]`.
> `sections.network` 는 **주 수집 결과만으로** 정해진다. 보조가 실패해도 주 수집이 됐으면 `success` 이고,
> 사유는 `errors[]` 에 `section: "network"` 로 남는다 (→ 시나리오 B. 2026-10-18 정정 — 실제 코드(`normalize_standard.yml` 의 보조 수집 오류 정규화)는
> `network` 로 적고, `network_adapters` 는 `diagnosis.details.notices[].section` 에만 쓴다).
> 즉 호출자가 받는 `adapters[]` 가 비어 있어도 `sections.network` 는 `success` 일 수 있다 —
> **NIC 카드 상세가 필요하면 `sections` 가 아니라 `data.network.adapters[]` 자체를 확인**해야 한다.
> (과거엔 보조 실패가 주 성공을 덮어 `sections.network=failed` + `status=partial` 이 됐다.
> 사이트 Dell iDRAC 8대가 `data.network` 는 정상인데 매번 `partial` 을 받던 원인.)

특히 **B 시나리오**가 헷갈린다. 호출자 코드에서 이렇게 짜면 안 된다.

```python
# 잘못된 예 — errors 만 보고 알람 띄우면 정상 케이스도 알람 발생
if response["errors"]:
    raise Alert("수집 실패!")
```

올바른 분기:

```python
# 수집 성공 여부는 status 로
if response["status"] == "failed":
    handle_collection_failure(response["diagnosis"])
elif response["status"] == "partial":
    record_partial(response["sections"])

# 장비 자체 상태는 별도 필드로
if response["data"]["hardware"].get("health") == "Critical":
    raise HardwareAlert(response["data"]["hardware"])
```

`errors[]` 는 **수집기가 본 비정상 신호의 기록장**이다. status 와는 별개 축이다.

---

**rescue(예외) 경로도 같은 매트릭스를 따른다 (2026-09-03).** 예외 직전까지 성공한 섹션은 `success` 로 남고
성공 섹션이 하나라도 있으면 `partial`, 없으면 `failed` 다. 종전에는 지원 섹션 전부를 `failed` 로 표기해
`data` 에는 값이 있는데 `sections` 는 실패인 자기모순이 났다.

## 4-1. `errors[]` 원소 — 무엇이 어디에 들어가나 (2026-08-12 확정)

원소는 항상 이 3개 키를 갖는다. 다른 키는 없다.

| 키 | 타입 | 무엇 |
|---|---|---|
| `section` | 문자열 | 오류가 난 영역. 수집 섹션 이름 11종, 수집 단계 이름 (`precheck` / `auth` / `gather` / `oem` / `vendor_detect` / `account_service` / `multi_node`), 보조 데이터 이름 `bios` (Redfish BIOS Current Attributes 조회 실패 — 6.8절), 또는 추가 수집 `addon` (Add-on 경로 · 설정 · 실행 문제). 값이 없으면 `unknown` |
| `message` | 문자열 (**절대 비지 않음**) | 사용자에게 그대로 보여주는 한국어 문장 |
| `detail` | 문자열 또는 `null` | 기술 근거. 객체나 배열이 아니다 |

### `message` 규칙

- **항상 비어 있지 않은 문자열**이다. `null` / `""` / 파이썬 자료구조 표현이 들어가는 경로는 없다.
- 다음은 `message` 에 **넣지 않는다**. 전부 `detail` 로 간다.
  관리 포트 번호 · HTTP 상태 코드 · 타임아웃 초 · 리소스 경로(URI) · 원본 stderr/stdout ·
  예외 문자열 · 내부 태스크명/변수명 · 영문 내부 코드 · 대상 IP
- **전체 실패 문장과 섹션 문장은 다르다.**

| 상황 | `status` | `message` |
|---|---|---|
| 전체 실패 | `failed` | 대표 문장 (아래 문장 카탈로그 중 하나). `errors[0].message == diagnosis.failure_reason` |
| 섹션 부분 실패 | `partial` 또는 `success` | 섹션 의미를 유지한 문장. 예: `"CPU 정보 수집에 실패한 항목이 있습니다. 대상 상태와 수집 로그를 확인하세요."` — 이때 `diagnosis.failure_reason` 은 `null` 이다 |

> `errors[0]` 규칙은 실패가 어디서 났든 같다 (2026-10-13). 예외로 끝난 봉투(rescue)뿐 아니라, 수집까지 갔는데 성공 섹션이
> 0개라 `failed` 가 된 봉투(문장 "대상 서버에서 수집된 정보가 없습니다.")에서도 `errors[0]` 은 대표 오류다 — `section` 은 채널
> 표시(`linux_gather` · `windows_gather` · `esxi_gather` · `redfish_gather`), `message` 는 `diagnosis.failure_reason` 과 같고,
> `detail` 은 섹션 결과 요약(`success_sections=0; supported=…; failed=…`)이다. 섹션 단위 오류는 그 뒤에 그대로 남는다
> (상한 10, 넘치면 절단 표시 1건). OS 채널은 그 뒤에 Serial Number 오류 1건이 더 붙을 수 있다 (4절 E).

전체 실패 대표 문장 카탈로그 (정본: `common/vars/failure_reasons.yml` 의 `_fr_catalog`).

**2026-09-21 변경** — 문장을 `failure_code` 하나가 아니라 **`failure_code` + 대상 종류(target_type) + 세부 사유**로
고른다. 종전에는 9개 code 가 6문장으로 뭉쳐 방화벽 차단과 서비스 중지, Vault 설정 문제와 대상 계정 문제가
같은 문장이었다. `failure_stage` / `failure_code` 값은 아래 한 가지 예외를 빼고 그대로다.
`{loc}` 은 실행 위치(Jenkins `loc` 파라미터) 값으로 채워지고, 값이 없으면 `미지정` 이 보인다.

| `failure_code` | 언제 | 문장 |
|---|---|---|
| `DNS_RESOLUTION_FAILED` | IP 문자열을 주소로 해석하지 못함 | 대상 IP가 올바르지 않습니다. 개더링 대상 IP를 확인하세요. |
| `TARGET_UNREACHABLE` | 관리 TCP 도 ICMP 도 무응답 | 대상 서버가 응답하지 않습니다. 서버 전원 상태와 네트워크 연결을 확인하세요. |
| `TCP_CONNECT_FAILED` | ICMP 는 응답, 관리 포트만 무응답 | 대상 서버와 통신은 되지만 관리 포트에 연결할 수 없습니다. 방화벽과 접속 설정을 확인하세요. |
| `TCP_CONNECTION_REFUSED` | 관리 포트가 연결을 거부 (OS) | OS 접속이 거부되었습니다. 대상 서버의 OS 원격 접속 설정과 방화벽을 확인하세요. |
|  | (ESXi) | ESXi 접속이 거부되었습니다. 대상 서버의 ESXi 접속 설정과 방화벽을 확인하세요. |
|  | (Redfish) | Redfish 접속이 거부되었습니다. 대상 장비의 Redfish 접속 설정과 방화벽을 확인하세요. |
| `PROTOCOL_CHECK_FAILED` | 포트는 열렸는데 기대 응답이 아님 (OS) | 접속한 대상에서 OS 원격 접속 응답을 확인하지 못했습니다. 대상 종류와 OS 원격 접속 설정을 확인하세요. |
|  | (ESXi) | 접속한 대상에서 ESXi 응답을 확인하지 못했습니다. 대상 종류와 ESXi 서비스 상태를 확인하세요. |
|  | (Redfish) | 접속한 대상에서 Redfish 응답을 확인하지 못했습니다. 대상 종류와 Redfish 서비스 설정을 확인하세요. |
| `CREDENTIAL_SET_UNAVAILABLE` | 실행 위치가 등록되지 않음 | 해당 위치({loc})가 개더링 프로젝트에 등록되지 않았습니다. |
|  | (OS/ESXi) 위치 Vault 폴더 없음 | 해당 위치({loc})에 Vault가 등록되지 않았습니다. |
|  | (OS/ESXi) 위치 Vault 복호화 실패 | 해당 위치({loc})의 Vault를 읽을 수 없습니다. |
|  | (OS/ESXi) 위치 폴더는 있는데 대상 종류 파일 없음 | 해당 위치({loc})의 Vault에 OS용 계정이 없습니다. / …ESXi용 계정이 없습니다. |
|  | (Redfish) 표준 Vault 파일 없음 | 개더링 프로젝트에 Vault가 등록되지 않았습니다. |
|  | (Redfish) 표준 Vault 복호화 실패 | 개더링 프로젝트의 Vault를 읽을 수 없습니다. |
|  | (Redfish) 표준 계정 0개 | 개더링 프로젝트의 Vault에 Redfish 표준 계정이 없습니다. |
| `AUTH_PROBE_FAILED` | 계정을 보냈지만 원인 미확정 (OS) | 해당 위치({loc})의 Vault 계정으로 대상 OS에 로그인하지 못했습니다. |
|  | (ESXi) | 해당 위치({loc})의 Vault 계정으로 대상 ESXi에 로그인하지 못했습니다. |
|  | (Redfish) | 개더링 표준 계정으로 대상 Redfish에 인증하지 못했습니다. |
|  | (Redfish) 표준 후보 **전원** 401 확인 | 대상 Redfish 계정과 개더링 표준 계정이 다르거나 권한이 없습니다. |
|  | Vault 계정 0개인 채로 시도 후 실패 | 위 Vault 계정 없음 문장 (OS/ESXi: 위치 Vault, Redfish: 표준 Vault) |
| `GATHER_FAILED` | 인증 통과 후 수집 실패 (OS) | 대상 OS에는 로그인했지만 정보를 가져오지 못했습니다. |
|  | (ESXi) | 대상 ESXi에는 로그인했지만 정보를 가져오지 못했습니다. |
|  | (Redfish) | 대상 Redfish 인증은 성공했지만 정보를 가져오지 못했습니다. |
|  | 수집 중 대상 연결 끊김 (인증 성공 뒤) | 정보 수집 중 대상 서버와 연결이 끊겼습니다. |
|  | 예외 없이 끝났는데 성공 섹션 0개 | 대상 서버에서 수집된 정보가 없습니다. |
|  | (Redfish) 계정 요청 전 수집기 내부 오류 | 개더링 프로젝트에서 정보 수집 중 오류가 발생했습니다. |
| `OUTPUT_BUILD_FAILED` | 결과 객체 자체를 만들지 못함 | 개더링 프로젝트에서 수집 결과를 만들지 못했습니다. |

> **code 가 바뀐 경우 (2026-09-21, Redfish 한정)** — 실행 위치 미등록, 표준 계정 0개(vendor 식별),
> vendor 미식별 + 표준 Vault 부재 세 경우는 인증을 시도하지 않았는데도 종전에는 `GATHER_FAILED` /
> `failure_stage: gather` 로 나갔다. 이제 `CREDENTIAL_SET_UNAVAILABLE` / `failure_stage: auth` 다.
> 이 두 값으로 분기하던 소비자는 확인이 필요하다. 운영 파이프라인(`Jenkinsfile_portal`)은
> 미등록 loc 를 Ansible 실행 전에 막으므로, 실행 위치 미등록 문장은 Jenkins 밖 직접 실행에서만 나온다.
>
> **Vault 복호화 실패 판정 수정 (2026-09-21)** — 종전에는 Vault 비밀번호가 없거나 틀려도
> "계정 0개" 로 잘못 분류됐다 (`load_one.yml` 의 `failed_when: false` 가 실패 표시를 지웠다).
> 이제 "Vault를 읽을 수 없습니다" 문장과 `CREDENTIAL_SET_UNAVAILABLE` 이 나온다.
>
> **아직 문장이 없는 경우** — OS/ESXi 의 계정 불일치 확인, 조회 권한 부족 확인, OS/ESXi 내부 오류 구분은
> 지금 구조적으로 판정할 근거가 없다(거부 사실이 오류 문자열로만 온다). 이 경우는 "로그인하지 못했습니다" /
> "로그인했지만 정보를 가져오지 못했습니다" 문장으로 나간다.

### `errors[]` 에 **들어가지 않는** 것

- **성공한 fallback** — 예: 구형 BMC 에서 `SimpleStorage` 경로로 스토리지를 **정상 수집**한 경우.
  데이터를 얻었으므로 실패가 아니다. 이 사실은 `diagnosis.details.notices` 에 남는다.
  (종전에는 여기가 `errors[]` 라서 정상 수집인데도 `status` 가 `partial` 로 강등됐다.)
- **지원하지 않는 optional 기능** — `sections.<name> = "not_supported"` 가 이미 표현한다.

### 호출자 가이드

```python
# message 는 그대로 사용자에게 보여도 된다 (문자열 보장)
for e in response["errors"]:
    show(e["section"], e["message"])

# 기술 근거가 필요하면 detail — 없을 수 있다
    log(e.get("detail"))
```

`errors[]` 개수만으로 알람을 띄우지 않는다 (§4 시나리오 B). 알람 기준은 `status` 와 섹션 status 다.

---

## 5. `diagnosis` — 어디서 막혔는지

연결이 안 됐을 때 가장 먼저 보는 곳. precheck 단계가 순서대로 체크되고, 막힌 단계의 boolean 이 `false` 로 찍힌다.

```json
"diagnosis": {
  "reachable":          true,    // 1단계: TCP 응답 확인? (ICMP ping 아님 — 아래 주의 참조)
  "port_open":          false,   // 2단계: 해당 포트 (Redfish=443, SSH=22 등) 연결 성공?
  "protocol_supported": false,   // 3단계: 기대 프로토콜 응답? (2단계 실패 시 미수행)
  "auth_success":       null,    // 4단계: 미수행이면 null (false 가 아니다 — 아래 주의)
  "failure_stage":      "port",  // 실행이 멈춘 단계 이름 (원인 아님)
  "failure_code":       "TCP_CONNECTION_REFUSED",  // 시스템 분기용 안정 식별자 (성공 시 null)
  "failure_reason":     "Redfish 접속이 거부되었습니다. 대상 장비의 Redfish 접속 설정과 방화벽을 확인하세요.",
  "details": { ... }             // 채널별 부가 정보 (선택된 adapter, BMC product 명, credential_scope 등)
}
```

읽는 법: **위에서 아래로 첫 번째 false 찍힌 단계가 실패 지점**.

> **주의 1 — `reachable` 은 ICMP ping 이 아니다.** 주소를 IPv4/IPv6 양쪽으로 풀어 **실제 TCP
> 연결을 시도**하고 그 결과로 판정한다 (`common/library/precheck_bundle.py:109-142`).
> 핑이 막힌 관리망에서도 BMC 는 443 으로 응답하므로 ICMP 로 판정하면 정상 장비를 오판한다.
> 연결이 **거부(RST)** 되면 호스트는 살아 있는 것이므로 `reachable=true` + `port_open=false` 가 된다.
>
> **주의 2 — `auth_success` 는 3-값이다.** `true`/`false` 외에 **`null`(인증 단계 미수행)** 이 있다.
> precheck 는 인증정보를 받지 않아 4단계를 수행하지 않으므로(`precheck_bundle.py:546-548`),
> precheck 단계에서 실패한 결과의 `auth_success` 는 **항상 `null`** 이다. 실제 인증 성공 여부는
> 본 수집 성공 후 각 채널이 `true` 로 덮어쓴다(`redfish-gather/site.yml:191-206` 등).
> 따라서 **`auth_success` 가 `null` 이라고 해서 인증이 실패한 것이 아니다.**
> (OS 채널의 포트 감지 실패 경로만 예외적으로 `false` 를 넣고 있다 — `os-gather/site.yml:162`.
> 인증을 시도하지 않은 상태이므로 의미상 `null` 이 맞고, 정정은 별도 단계로 분리돼 있다.)

| `failure_stage` | 의미 | 해결 방향 |
|---|---|---|
| `null` | 실패 안 함 | 정상 |
| `reachable` | 호스트 자체가 응답 없음 | 호스트 전원 / 네트워크 / 라우팅 |
| `port` | 호스트는 응답하나 포트 닫힘 | 방화벽 / 서비스 미기동 / 포트 번호 오설정 |
| `protocol` | 포트는 열렸는데 응답 형식이 이상함 | TLS 버전 / cipher / 펌웨어 버그 |
| `auth` | 인증 단계에서 멈춤 | 비밀번호 회전 / 계정 잠김 / 권한 부족 |
| `gather` | 연결·인증 통과 후 수집/정규화 단계에서 중단 | 계정 권한 / 펌웨어 호환성 / OEM 경로 |
| `fallback` | `_output` 미생성 (block·rescue 모두 실패) | 수집기 내부 오류. Jenkins console log 확인 |

> `failure_stage` 는 **원인**이 아니라 **실행이 멈춘 단계**를 가리킨다. 구체적인 기술 오류는
> `errors[].detail` 에 원문 그대로 들어간다 (예: `"port=443: 연결 시간 초과 (timeout=3.0s)"`).

### 5-1. `failure_code` — 시스템이 분기할 때 쓰는 값

`failure_reason` 은 사람이 읽는 문장이라 **파싱 대상이 아니다.** 외부 시스템이 실패 종류로
분기해야 하면 `failure_code` 를 본다. 성공/부분 성공에서는 `null` 이며, **키 자체는 항상 존재한다.**

| `failure_code` | 대응 `failure_stage` | 관측한 사실 |
|---|---|---|
| `DNS_RESOLUTION_FAILED` | `reachable` | 주소 해석 실패로 TCP 연결 시도 자체를 못 함 |
| `TARGET_UNREACHABLE` | `reachable` | 관리 TCP 도 ICMP Echo 도 응답이 없음. **장비 다운으로 확정하지 않음** — 우리가 쓴 probe 로 응답을 못 봤다는 관측이다 |
| `TCP_CONNECT_FAILED` | `port` | ICMP 응답으로 도달은 확인됐는데 관리 TCP 포트가 무응답 (timeout / no route, RST 미관측). 방화벽 DROP 이 대표 사례 |
| `TCP_CONNECTION_REFUSED` | `port` | 명시적 TCP 거부(RST)를 관측 |
| `PROTOCOL_CHECK_FAILED` | `protocol` | 기대한 프로토콜 응답을 확인하지 못함 |
| `AUTH_PROBE_FAILED` | `auth` | **자격증명을 실제로 보냈고** 확인 단계에서 중단. 인증 거부 확정은 `auth_success` 가 표현 |
| `CREDENTIAL_SET_UNAVAILABLE` | `auth` | 자격증명 세트를 열 수 없어 **인증을 시도조차 못 함** (`auth_success` 는 항상 `null`) |
| `GATHER_FAILED` | `gather` | 연결·인증 통과 후 수집/정규화 실패 |
| `OUTPUT_BUILD_FAILED` | `fallback` | 정상 결과 객체 생성 실패 |

> **`AUTH_PROBE_FAILED` 와 `CREDENTIAL_SET_UNAVAILABLE` 의 차이** (2026-08-12 신설)
>
> **운영자가 확인할 곳이 다르다.** 2026-09-21 부터 사용자 문장도 다르다 (위 카탈로그).
>
> | | `AUTH_PROBE_FAILED` | `CREDENTIAL_SET_UNAVAILABLE` |
> |---|---|---|
> | 무슨 일이 있었나 | 자격을 실어 보냈는데 통하지 않았다 | 보낼 자격 자체가 없었다 |
> | `auth_success` | `false`(명시적 거부) 또는 `null`(원인 미확정) | **항상 `null`** (미시도) |
> | 확인할 곳 | 대상 장비의 계정 / 권한 / 잠금 | 자격증명 배치 (해당 Location 의 세트 존재·복호화) |
> | 대표 상황 | 401 거부, timeout, TLS 오류, 403 | Location 미전달·미등록, 세트 파일 부재, 복호화 실패, 계정 0개(시도 전) |
>
> `stage` 는 둘 다 `auth` 다 — `failure_stage` 는 원인이 아니라 **멈춘 위치**이고,
> 멈춘 곳은 두 경우 모두 자격증명 단계다.
> 어떤 세트를 열었는지는 `diagnosis.details.credential_scope` 로 확인한다.

> **Credential scope 두 개 — Redfish 만** (2026-08-12)
>
> Redfish 는 계정 축이 둘이라 `details` 에 scope 가 둘 나온다.
>
> | 필드 | 값 | 무엇인가 | 채널 |
> |---|---|---|---|
> | `credential_scope` | `common/redfish/standard` | **실제 인증·수집에 쓴** 표준 수집 계정. Location / Vendor 와 무관한 전역 1개 | 3채널 (OS/ESXi 는 `<loc>/os/<type>`, `<loc>/esxi`) |
> | `recovery_credential_scope` | `<loc>/redfish/<vendor>` | 표준 계정을 **만들거나 되살리기 위한** 복구 계정 범위. 수집에는 쓰지 않는다 | Redfish 전용 |
>
> 최종 수집은 **반드시** 표준 계정으로 수행된다. 복구 계정으로 수집한 결과가
> 정상 결과로 나가는 경로는 없다 — 복구가 확인되면 표준 계정으로 **재수집**한다.
> `diagnosis.details.auth.used_role` 이 `recovery` 인 성공 결과는 존재할 수 없다.

> **도달성은 TCP 와 ICMP 의 OR 이다** (2026-09-03)
>
> `reachable` 은 "관리 TCP 응답 **또는** ICMP Echo 응답" 으로 판정한다. 관리망에서 TCP 를
> DROP 하는 구성이 흔해, TCP 만 보면 살아 있는 장비가 `reachable` 실패로 떨어졌다.
>
> | 관측 | `reachable` | `failure_stage` | `failure_code` |
> |---|---|---|---|
> | 관리 TCP 연결 성공 | `true` | — | `null` |
> | 관리 TCP 거부(RST) | `true` | `port` | `TCP_CONNECTION_REFUSED` |
> | TCP 무응답 + ICMP 응답 | `true` | `port` | `TCP_CONNECT_FAILED` |
> | TCP 무응답 + ICMP 무응답 | `false` | `reachable` | `TARGET_UNREACHABLE` |
> | 주소 해석 실패 | `false` | `reachable` | `DNS_RESOLUTION_FAILED` |
>
> ICMP 는 **Gate 가 아니다.** TCP 가 응답하면 ICMP 는 확인조차 하지 않고, ICMP 무응답은
> 그 자체로 아무것도 실패시키지 않는다 (ICMP 전용 `failure_code` 도 없다). ICMP 를 못 쓰는
> 환경(차단·`ping` 부재·권한 부족)에서는 판정이 종전 TCP 전용과 같아진다.
>
> **호출자 영향**: 종전 `TCP_CONNECT_FAILED` + `stage=reachable` 로 분기하던 소비자는
> `TARGET_UNREACHABLE` 을 함께 받도록 갱신해야 한다. 사용자 문장은 종전과 동일하다.
>
> Raw Exception 종류(socket timeout / SSL 오류 / HTTP 500 등)는 code 로 만들지 않는다.
> 그 정보는 `errors[].detail` 과 `diagnosis.details` 에 보존된다
> (ICMP 관측 근거도 `errors[].detail` 에만 남는다 — 봉투 shape 은 그대로다).

---

## 6. `data.<section>` — 알맹이는 어떻게 생겼나

> **2026-10-03 의미 정정 (값 shape 불변)** — `data.system.runtime.listening_ports[]` 는 ESXi 에서 **방화벽 허용 inbound 규칙의
> port** 이지 실제 listener 가 아니다 (vSphere API 로는 listener 를 볼 수 없다). 범위 규칙(`port`~`endPort`)은 시작 port 만
> 표기하고 범위 사실은 수집기 notice 로만 남긴다. UDP 제외·범위 표기 확장은 호출자 확인 전까지 바꾸지 않는다.
> **2026-10-10 의미 확정** — `data.system.runtime.firewall_state` 는 세 채널 모두 **유효 정책**이다: Windows 는 `Get-NetFirewallProfile -PolicyStore ActiveStore`
> (GPO 적용 뒤 활성 프로필), ESXi 는 `config.firewall.defaultPolicy.incomingBlocked`, Linux 는 firewalld 실행 → `active`, ufw 는 `Status:` 값, nftables/iptables 는
> 입력 체인 정책이 drop|reject 이거나 규칙이 1개 이상이면 `active` · 정책 accept 에 규칙 0 이면 `inactive`(종전 iptables 는 설치만 돼 있어도 `active` 였다).
> 판정 근거를 읽지 못하면(Linux 는 sudo 실패) `firewall_tool` · `firewall_state` 가 `null` 이고 `errors[]` 에 system 오류 1건이 남는다.
> `system.hosting_type`(Windows): `HypervisorPresent=True` 이고 Hyper-V 역할이 없어도 VBS(Device Guard)가 Running 이면 `baremetal` 이다 —
> VBS 를 켠 물리 Windows 는 하이퍼바이저가 있다고 보고한다. VBS 상태를 못 읽으면 종전 규칙(`virtual`)이다.

10개 섹션을 다 풀면 길어진다. 가장 자주 쓰이는 5개만 여기서 정리하고, 나머지는 라인별 한국어 주석본 (`schema/output_examples/redfish_dell_idrac9.jsonc`) 을 본다.

### 6.1 `data.hardware`

장비 본체 정보. **`health` 필드가 가장 중요**하다.

```json
"hardware": {
  "vendor":       "Dell Inc.",        // BMC 가 보고한 원본 manufacturer (정규화 안 한 값)
  "model":        "PowerEdge R740",
  "serial":       "2BJ8033",          // Dell 은 ServiceRoot.Oem.Dell.ServiceTag (2026-08-11 교정)
  "uuid":         "4c4c4544-...",
  "sku":          "2BJ8033",          // 벤더마다 의미 다름 (Dell=서비스 태그 / HPE=파트번호 / Lenovo=CTO 주문)
  "bios_version": "2.21.2",
  "power_state":  "On",               // On / Off / PoweringOn / PoweringOff
  "health":       "Critical",         // OK / Warning / Critical
  "oem":          { ... }             // 벤더 전용 확장 — 키가 벤더마다 완전히 다름
}
```

`health` 가 `OK` 가 아닌 이유는 **`data.power.power_supplies[]` / `data.storage` / `data.memory.slots[]`** 등을 차례로 봐야 알 수 있다. BMC 가 rollup 만 보고하고 원인은 직접 찾아야 한다.

**OS 채널(2026-09-03)**: Linux / Windows 도 `hardware` 를 낸다 — `vendor` / `model` / `serial` / `uuid` / `bios_version` / `bios_date`
(Windows 는 `sku` / `asset_tag` / `chassis_type` / `system_family` / `bios_vendor` 추가). `health` / `power_state` 는 OS 에서 알 수 없어 키가 없다.
`uuid` 는 3채널 모두 소문자 `8-4-4-4-12` 로 정규화한다. Redfish 와 OS/ESXi 의 UUID 는 SMBIOS 바이트 순서 규약이 달라
앞 3그룹이 반전돼 보일 수 있다 — 같은 장비 판정은 `filter_plugins/identity_normalizer.py` 의 `uuid_equal` 로 한다.
`serial` 은 `system.serial_number` 와 같은 값이고, `envelope.vendor` 는 `hardware.vendor` 원문을 `vendor_aliases.yml` 로 정규화한 표시값이다.
> **2026-10-10** — (1) 식별자 자리표시자는 세 채널이 **같은 집합**으로 거른다 (`filter_plugins/identity_normalizer.py` `DMI_SENTINELS`:
> `To Be Filled By O.E.M.` · `Not Specified` · `Default string` · `System Serial Number` · `NA` · `N/A` · `None` · `0` · `00000000` 등 — 대소문자 · 공백 무시).
> ESXi 도 이제 `NA` 를 `serial` 로 내지 않는다. SMBIOS 공장 기본 UUID `03000200-0400-0500-0006-000700080009`(바이트 순서 반전형 포함)는
> all-0 · all-f 와 같이 `uuid` / `system_uuid` 를 `null` 로 둔다 — 보드 공장값은 장비 식별자가 아니다.
> (2) Linux 는 수집을 비특권(OS · 호스트명 · 읽을 수 있는 DMI: vendor · model · bios)과 특권(serial · uuid · dmidecode)으로 나눠 실행한다. sudo 가
> 실패하면 특권 값만 `null` 이고 `errors[]` 에 권한 문장(시스템 제조번호 · 고유 식별자)이 남는다 — 종전에는 섹션 전체가 비었다.

### 6.2 `data.memory`

> **2026-10-03** — (1) `slots[].speed_mhz` 는 세 채널 모두 "현재 동작 속도" 다: Redfish `OperatingSpeedMhz`, Linux 는 dmidecode
> `Configured Memory Speed`(없으면 정격 `Speed`), Windows 는 `ConfiguredClockSpeed`(없으면 `Speed`). 단위 변환은 없다. 종전 Linux 는
> 정격 `Speed` 를 냈으므로 같은 장비에서 값이 바뀔 수 있다(예: DDR5 정격 5600 → 동작 4400). (2) Redfish 에서 장착 DIMM 의 `CapacityMiB` 가
> 없으면 합계를 과소집계하지 않는다 — `total_mb` 는 `System.MemorySummary` fallback, 없으면 `null`; slot 은 전부 보존(`capacity_mb: null`).
> (3) Linux 에서 총량은 있는데 DIMM 상세가 0건이면 `errors[]` 에 memory 섹션 오류 1건이 남는다(섹션 status 는 총량 기준 `success` 유지;
> detail 에 dmidecode 종료 코드 · 레코드 수 · stderr 첫 줄). dmidecode 가 비루트로 머리말만 찍고 rc≠0 으로 끝나면 sudo 로 1회 재시도한다.
> dmidecode 3.2 미만의 `Configured Clock Speed` 는 `Configured Memory Speed` 와 같은 필드로 읽는다.
> **2026-10-10 (JEDEC)** — `slots[].manufacturer` 의 JEDEC 코드 해석은 bank(continuation 바이트 수)를 본다. 같은 7-bit ID 가 bank 마다 다른 제조사라
> (0x18: bank 1 = Kingston, bank 0 = Toshiba/Kioxia) 종전 byte 전용 표는 bank 0 의 0x98 도 Kingston 으로 적었다. 표는 JEP106BE 기준이며 모르는 코드는
> 원문 그대로 둔다(지어내지 않는다). 종전 표의 `0B → Intel` 은 오류였다(0x0B 는 Intersil, Intel 은 0x89/0x09). OS 채널과 Redfish 채널이 같은 표를 쓴다.

```json
"memory": {
  "total_mb":     655360,                // 합계 메모리 (이 케이스 640 GB)
  "total_basis":  "physical_installed",  // 합계의 산출 기준
  "installed_mb": 655360,                // 물리 장착 (Redfish / OS 채널)
  "visible_mb":   null,                  // OS / ESXi 가 보는 양 (Redfish 미수집 — spec 미정의)
  "free_mb":      null,                  // 가용량 (OS 채널 전용)
  "slots":        [ /* DIMM 개별 정보 */ ],
  "summary":      { /* 같은 단위 DIMM 묶은 집계 */ }
}
```

**Channel 매핑 (2026-05-11)**:
- `installed_mb` channel: `[redfish, os]` — ESXi 는 ansible_memtotal_mb 만 (DIMM slot 미수집) → channel 제외
- `visible_mb` channel: `[os, esxi]` — Redfish API spec 미정의 (`Memory.v1_*.json` 에 `VisibleMiB` 없음) → channel 제외
- `free_mb` channel: `[os]` — OS 채널 전용
- 정본: `schema/field_dictionary.yml` 의 memory.installed_mb / memory.visible_mb / memory.free_mb 의 `channel:` 배열

`total_basis` 값으로 어느 채널 기준인지 안다.

| `total_basis` | 채워주는 채널 | 의미 |
|---|---|---|
| `physical_installed` | Redfish | DIMM 장착량 합계 |
| `os_visible` | OS-gather | OS 가 인식하는 양 |
| `hypervisor_visible` | ESXi-gather | ESXi 가 인식하는 양 |

같은 서버라도 channel 마다 값이 다를 수 있다 (가상화 / 불량 DIMM / BIOS 예약 영역 등으로).

> **2026-10-10 (Windows DIMM 조회 일부 실패)**: `Win32_PhysicalMemory` 조회가 공급자 오류를 내면서 일부 DIMM 행만 돌려주면, 받은 슬롯 · 그룹은 그대로 두되
> 설치량을 확정하지 않는다 — `total_mb` = OS 가시량, `total_basis` = `os_visible`, `installed_mb` = `null`, `summary.grand_total_gb` = `null`(일부 슬롯 합을 전체
> 합계로 쓰지 않는다), memory 섹션 경고 1건(`cause=read_failed` · 받은 슬롯 수 · 오류 원문). 섹션은 성공이다. 슬롯을 하나도 받지 못하면 종전 fallback(가시량 기준 합계) 그대로.

### 6.3 `data.storage`

> **2026-10-03** — (1) `physical_disks[].protocol` 의 enum 은 그대로다. Windows BusType 가 enum 밖(ATAPI/ATA/SSA/Virtual/
> File Backed Virtual/Storage Spaces/SCM/UFS)이면 `null` 로 두고 원값은 storage 섹션 오류 1건의 `detail` 에 남긴다. 정수형(Int32/UInt16/
> 숫자 문자열)과 문자열(`"SAS"`, `"Fibre Channel"`) 모두 같은 표로 매핑한다. (2) Linux `lsblk` 실패는 더 이상 빈 목록으로 가려지지
> 않는다 — `lsblk -J` 가 실패하면(옵션 미지원 · 구 util-linux) 레거시 열(`NAME,SIZE,TYPE,ROTA,MODEL`) 1회 fallback 으로 목록을 만들고
> (`serial`/`wwn` 은 udev 에서만, `protocol` 은 null), 그래도 못 만들면 `physical_disks` 가 빈다. 어느 쪽이든 `errors[]` 에 storage
> 오류 1건(detail: `source=lsblk; lsblk_rc=; state=unknown|unsupported|permission|malformed|empty|ok; disks=; sys_block=; stderr=`).
> 스토리지가 통째로 비면(디스크 0 · 파일시스템 0) 기존 실패 항목 하나에 lsblk 근거를 합친다. `df` 는 `timeout 20` 아래서 돈다
> (`timeout 20 true` 가 되는 환경에서만). filesystems 만으로 섹션이 `success` 이면 "success + errors" (4절 시나리오 B) 다. (3) Windows HBA 포트가 어댑터와 매칭되지 않으면 첫 어댑터 값을 빌리지
> 않고 `model/vendor/driver/firmware` 가 `null` 이다.
> **2026-10-10** — (1) Linux multipath: 같은 LUN 의 경로 디스크(`/sys/block/dm-*` 의 `mpath-*` 구성원, 또는 같은 WWN·크기)는 `physical_disks[]` 1개로
> 접고 `id`/`device` 는 `/dev/mapper/<이름>`(구성원 정보가 없으면 첫 경로)이다 — 종전에는 경로마다 1개라 디스크 수와 `summary` 합계가 경로 수만큼
> 부풀었다. ESXi 의 `physical_disks[]` 는 종전대로 **LUN 단위**다(2026-09-03 결정 유지). (2) Windows `total_mb` 는 `MSFT_PhysicalDisk.Size` 가 우선이고
> `Win32_DiskDrive.Size`(디스크 기하값 계산이라 실제보다 작다)는 없을 때만 쓴다. (3) ESXi `controllers[].controller_type` 은 BlockHba 를 전부 SATA 로
> 적지 않고 드라이버 계열(`vmw_ahci`=SATA · `lsi_mr3`/`megaraid`/`smartpqi`=RAID · `nvme`=NVMe)로 정하며 모르면 `null` 이다. (4) ESXi `datastores[]` 의
> 문자열 용량은 TB · GB · MB 단위를 모두 읽는다(종전에는 TB 만 보고 MB 를 GB 로 읽었다).

스토리지는 다음 하위 list 가 있다.

| 키 | 무엇 | 누가 채우나 |
|---|---|---|
| `physical_disks[]` | 물리 디스크 (모든 컨트롤러 합쳐서 중복 제거) | 모든 채널 |
| `controllers[].drives[]` | 컨트롤러별 드라이브 | Redfish |
| `logical_volumes[]` | RAID 논리 볼륨 (OS/ESXi 는 RAID 컨트롤러 뒤 디스크 — 6.3.0b) | 모든 채널 (2026-10-18) |
| `filesystems[]` | OS 파일시스템 마운트 | OS-gather |
| `datastores[]` | ESXi 데이터스토어 | ESXi-gather |
| `hbas[]` | FC HBA (+ iSCSI) | 모든 채널 |
| `infiniband[]` | InfiniBand **포트** (현재 IB 모드로 확인된 포트만) | OS Linux · OS Windows · Redfish (ESXi 는 항상 빈 목록 — 6.3.1) |

물리 디스크와 논리 볼륨 사이는 ID 로 묶인다.

```text
physical_disks[*].id  ─┐
                       ├─ logical_volumes[*].member_drive_ids 에서 참조
controllers[*].id  ────┤
                       └─ logical_volumes[*].controller_id 에서 참조
```

#### 6.3.0 `physical_disks[]` 식별자 — `serial` / `wwn` (2026-06-22)

각 물리 디스크는 식별자로 `serial`(시리얼) / `wwn`(World Wide Name) 을 가진다. 둘 다 **Nice**
(`schema/field_dictionary.yml`) 이며, OS/디스크가 제공하지 않으면 `null` (정상 — 누락 아님).

| 필드 | 채널 | 수집원 |
|---|---|---|
| `serial` | Redfish, OS, ESXi | Redfish=`Drive.SerialNumber` / OS Linux=`lsblk SERIAL`(빈값 시 `udevadm ID_SERIAL_SHORT`) / OS Windows=`Get-PhysicalDisk.SerialNumber`(빈값 시 `Win32_DiskDrive.SerialNumber`, hex/공백 정규화) / ESXi=`ScsiLun.alternateName[SERIALNUM]` |
| `wwn` | OS, ESXi | OS Linux=`lsblk WWN`(udev `ID_WWN`; SATA/SAS=NAA `0x...`, NVMe=`eui.`) / OS Windows=`Get-PhysicalDisk.UniqueId` (UniqueIdFormat 이 EUI64/FCPHName/SCSI Name String 일 때만) / ESXi=`ScsiLun.canonicalName`(naa.*) |

- **`null` 정상 케이스**: virtio 가상디스크 / 로컬 SATA(특히 Windows WWN) / RAID 가상 디스크 일부 → best-effort.
- redfish 는 `serial` 만 emit (디스크 `wwn` 미수집). **ESXi 는 2026-06-22부터 `physical_disks` 수집**
  (`esxi_disks` pyvmomi 모듈 — id/device/wwn=canonicalName naa.*, serial=SERIALNUM, model=vendor+model, media_type=ssd flag).

#### 6.3.0a `physical_disks[].is_os_disk` — OS 설치 디스크 여부 (2026-07-02)

각 물리 디스크에 **OS 루트가 설치돼 있는지**를 boolean 으로 표시한다. **Nice / `boolean|null`**,
**OS 채널 전용**(`channel: [os]` — ESXi/Redfish 는 미수집, 필드 부재).

| 값 | 의미 |
|---|---|
| `true` | 이 디스크에 OS 루트(`/`, Windows `%SystemDrive%`)가 있음. RAID/LVM 구성 시 멤버 디스크 **모두** true |
| `false` | 판정 성공 + 이 디스크는 OS 루트 구성에 속하지 않음 |
| `null` | 판정 불가 — SAN/iSCSI/NFS 루트 또는 `findmnt`/`Get-Partition` 부재 (거짓 false 를 내지 않음) |

- OS Linux: `findmnt /` 로 root source → `lsblk -s` 로 하위 물리 디스크 역추적(파티션/LVM/mdadm/multipath). python_ok + raw fallback 동일 구현. root 불필요.
- OS Windows: `%SystemDrive%` → `Get-Partition.DiskNumber` (부재 시 WMI `Win32_DiskPartition.DiskIndex` fallback). `Win32_DiskDrive.Index` 와 매칭. hardware-RAID/단일디스크는 정확하나, **software-RAID/Storage Spaces/동적미러 OS 는 가상 DiskNumber 라 물리 Index 매칭이 0 → 전 디스크 `null`** (Linux 의 멤버 all-true 와 비대칭 — 거짓 false 대신 null).
- **주의**: 기준은 **OS 루트**(`/`)이며 `/boot`·EFI 파티션이 다른 디스크에 있어도 그 디스크는 `false`. Dell BOSS-N1 같은 부팅 전용 NVMe 에 OS 가 있으면 대용량 데이터 디스크가 아니라 그 NVMe 가 `true` (예: `os_linux_baremetal_dell.jsonc`).

#### 6.3.0b `logical_volumes[]` — OS/ESXi 의 RAID 컨트롤러 뒤 디스크 (2026-10-18, 사용자 결정)

Redfish 는 `/Storage/{id}/Volumes` 의 논리 볼륨을, OS/ESXi 는 종전에 빈 목록을 냈다. 같은 서버에서 Redfish 는 "물리 10 + 볼륨 3", Linux 는
"물리 3(= RAID VD 2 + BOSS VD) + 볼륨 0" 으로 보여 두 채널을 맞춰 볼 수 없었다. 2026-10-18 부터 OS/ESXi 는 **RAID 컨트롤러 뒤에서 보이는 디스크**
(= `physical_disks[]` 의 그 항목 — 그대로 남긴다, Additive)를 `logical_volumes[]` 에도 싣는다.

| 채널 | 판정 | `controller_id` | `member_drive_ids` · `raid_level` |
|---|---|---|---|
| Linux | 디스크의 PCI 컨트롤러(`/sys/block/<dev>` 실경로의 마지막 PCI 주소, raw `DISKPCI` 줄)가 `controllers[]` 중 lspci 클래스 `RAID bus controller` 항목 | 그 PCI 주소(= `controllers[].id`) | `[]` · `null` (OS 는 RAID 뒤 물리 디스크를 못 본다) |
| Windows | `physical_disks[].protocol == 'RAID'`(MSFT_PhysicalDisk BusType 8) | `null` (표준 API 가 볼륨 ↔ 컨트롤러를 주지 않는다) | `[]` · `null` |
| ESXi | `storageDevice.scsiTopology` 로 LUN 이 붙은 어댑터를 찾아 `controller_type == 'RAID'`(드라이버 계열 lsi_mr3 · megaraid · smartpqi · hpsa · aacraid) | 그 vmhba(= `controllers[].id`) | `[]` · `null` |

- 키는 Redfish 와 같다(`id` `name` `controller_id` `member_drive_ids` `raid_level` `total_mb` `health` `state` `boot_volume`). `name` 은 Linux/Windows 디스크 모델, ESXi 는 `displayName`.
- ESXi 의 RAID 뒤 LUN 은 `physical_disks[].media_type` 이 `null` 이다 — `ScsiDisk.ssd` 는 컨트롤러 보고값이라 매체가 아니다(실측 esxi02: SSD RAID5 LUN 이 `HDD` 로 나왔다).
- 들어오지 않는 것: BOSS 처럼 lspci 클래스가 `SATA controller` 인 RAID 카드의 볼륨(모델 문자열 `DELLBOSS VD` 로 추정하지 않는다). 한계: pass-through 디스크가 RAID 클래스
  컨트롤러 뒤에 있으면 볼륨으로 보인다(컨트롤러 종류만 본다).
- 개수 비교의 뜻: Redfish `physical_disks` 는 RAID 뒤 물리 디스크, OS/ESXi `physical_disks` 는 OS 가 보는 블록 장치(RAID 볼륨 포함)라 **수가 같을 필요가 없다**.
  맞춰 볼 수 있는 것은 `logical_volumes` 의 수와 용량이다.

#### 6.3.1 `hbas[]` / `infiniband[]` — FC HBA / InfiniBand (2026-05-29, IB 는 2026-10-17 정비)

전 채널 (Redfish / OS Linux·Windows / ESXi) 이 **동일 canonical 키** 로 emit 한다.
호출자는 채널 무관하게 같은 키로 파싱하고, `wwpn` / `node_guid` 로 동일 물리 장치를
채널 간 상관(correlation)할 수 있다. `source` 필드로 출처 채널을 구분한다.

```json
"storage": {
  "hbas": [
    { "wwpn": "20:00:...:01", "wwnn": "20:00:...:00", "model": "HPE SN1610Q 32Gb 2p FC HBA",
      "vendor": "Marvell", "driver": null, "firmware": "9.12.00",
      "link_status": "up", "link_speed_gbps": 32, "port_type": "FibreChannel",
      "source": "redfish" }
  ],
  "infiniband": [
    { "adapter": "mlx5_0", "port": "1", "node_guid": "0c42:a103:0012:3456", "port_guid": "0c42:a103:0012:3456",
      "link_status": "up", "rate": "200 Gb/sec (4X HDR)", "rate_gbps": 200,
      "model": "MT28908 Family [ConnectX-6]", "vendor": "Mellanox Technologies", "firmware": "20.35.1012",
      "source": "os" }
  ]
}
```

(위 값은 형식 설명용 합성 예시다 — 실장비 IB 수집 결과는 아직 없다. 2026-10-17 기준 실장비 결과는 모두 `"infiniband": []` 이다.)

**`infiniband[]` 항목 1개 = 현재 InfiniBand 모드로 확인된 포트 1개** (2026-10-17). 2포트 카드는 IB 모드인 포트 수만큼이고,
VPI 카드의 Ethernet 모드 포트는 들어가지 않는다. 판정 근거는 채널이 주는 "현재 모드" 속성뿐이다 — 제조사명(Mellanox) ·
드라이버명(`mlx*`/`nmlx*`) · RDMA 지원 여부 · IB 지원 가능 목록 · GUID 존재 · 카드 이름으로 추정하지 않는다.
공통 키 11개(`adapter` `port` `node_guid` `port_guid` `link_status` `rate` `rate_gbps` `model` `vendor` `firmware` `source`)에
Redfish 는 호환 키 `adapter_model`(=`model`), Windows 는 `note` 를 더 가진다. 값의 뜻은 `schema/field_dictionary.yml` `storage.infiniband[].*`.

채널별 수집원 + 한계:

| 채널 | FC HBA 수집원 | InfiniBand 수집원 / 판정 / 한계 |
|---|---|---|
| Redfish | System 에 연결된 섀시의 `NetworkAdapters` → `Ports`/`NetworkPorts` + `NetworkDeviceFunctions` (FC=`PortProtocol`/`NetDevFuncType`/`Port.FibreChannel` 블록, 기능이 연결되지 않은 포트는 링크 기술 `FibreChannel`. **PortType enum 아님**). 2026-10-18 보완: FC 링크 기술 포트의 Ethernet 블록은 Ethernet 근거가 아니고, 짝 없는 기능은 이름으로 찾은 부모 포트의 링크·속도를 상속하며, 정수 Id · 카드 1장의 예외 · 이름 없는 카드가 섹션 전체를 지우지 않는다. 범위와 빈 목록의 뜻은 6.3.2 | 포트의 현재 모드(`Port.LinkNetworkTechnology` / `NetworkPort.ActiveLinkTechnology` / `Port.PortProtocol`)와 연결된 기능의 `NetDevFuncType` 이 `InfiniBand` 일 때. 둘이 다르면 IB 로 확정하지 않고 notice 1건. GUID 는 기능의 `InfiniBand.NodeGUID/PortGUID`, 없으면 `Port.InfiniBand.Associated*GUIDs` 가 한 값일 때만. 상세 6.3.3. 주류 BMC(iDRAC/iLO/XCC) 는 add-in IB HCA 거의 미노출 → OS 채널 정본 |
| OS Linux | `/sys/class/fc_host/*`(port_name/node_name/port_state/port_type/speed) + `scsi_host/<host>/`(proc_name = 드라이버 · model_name/modelname · fw_version/fwrev · manufacturer) + PCI uevent → `lspci` 이름. NPIV 가상 포트 제외. link_status up/down/null (2026-10-18) | `/sys/class/infiniband/<dev>/ports/<n>/` 중 **`link_layer == InfiniBand` 인 포트만** (RoCE·iWARP 는 `Ethernet` 이라 제외 — 같은 디렉터리에 등록되고 `rate` 도 IB 식으로 찍힌다). `node_guid` 파일 · `port_guid` = `gids/0` 하위 64비트 · `rate` 원문 · `rate_gbps` 는 `state` ACTIVE 일 때만(커널은 DOWN 포트에도 기본 SDR 값을 찍는다) · `model`/`vendor` 는 `lspci`(pci.ids) 이름(없으면 model=`hca_type`, vendor=null) · `firmware` = `fw_ver`. **정본** |
| OS Windows | `Get-InitiatorPort` + `MSFC_*` WMI (FC/iSCSI 만). 구성요소(initiator_ports · adapter_attrs · port_attrs) 성패를 적어 접근 거부 · 제공자 오류는 errors[] 1건, cmdlet · 클래스 부재는 "HBA 없음" 과 같은 환경. PortSpeed 비트 1~0x2000 → Gbps, PortState 보강 (2026-10-18) | `Get-NetAdapter -IncludeHidden` 중 `NdisPhysicalMedium 11`(Infiniband) 또는 표시값 `Infiniband`; 2차로 `Get-NetAdapterRdma` 의 `RdmaTechnology == InfiniBand`(iWARP/RoCE 아님). 팀 멀티플렉서(`Multiplexor`/`MS_IMPLAT`) 제외. `rate` = `LinkSpeed`, `rate_gbps` = `ReceiveLinkSpeed`(bps)/1e9. **`port`·`node_guid`·`port_guid`·`firmware` 는 표준 API 가 없어 null** (`note` 에 그 뜻). WinOF-2 는 Windows Server 2019 에서 IPoIB 의 물리 매체를 802.3 으로 보고하는 알려진 이슈가 있어 2차 신호가 없으면 놓칠 수 있다(벤더 도구 `mlx5cmd` 는 쓰지 않는다) |
| ESXi | `vmware_host_vmhba_info` — type + driver 두 신호(FC/FCoE/iSCSI, 하드웨어 iSCSI 클래스 `InternetScsiHba` 포함, SAS/RAID 제외). 같은 (wwpn, wwnn) 1건(ESXi 7 FC-NVMe 쌍둥이), speed 자릿수 정규화, WWN 형식 검증(깨진 값은 null + errors[]) (2026-10-18) | **수집하지 않는다 — 항상 `[]`.** 네이티브 nmlx5 드라이버는 Ethernet 전용이고 IB 는 SR-IOV/passthrough 로 VM 에만 간다. IB 모드 카드는 vmnic 없이 PCI `Infiniband controller` 로만 보인다(Broadcom KB 381748). 종전 "`nmlx` 드라이버 NIC = IB" 추정은 이더넷 NIC 오탐이라 제거했다. 빈 목록은 "IB 없음" 의 증거가 아니라 "이 채널은 수집하지 않는다" 는 뜻이다 |

- `wwpn`/`wwnn`/`link_speed_gbps`/`node_guid`/`port_guid`/`rate_gbps` 는 미연결·미노출 시 `null` (정상 — error 아님). 단 Linux 에서 sysfs 속성 파일이
  **있는데 읽지 못하면**(권한 등) storage 섹션 오류 1건이 남는다 (detail: `scope=fc_host[,infiniband]; cause=attribute_unreadable;
  count=; paths=` 최대 10개). 속성 파일 자체가 없는 것은 오류가 아니다 (2026-10-03). IB 포트의 `link_layer` 를 읽지 못하면 그 포트는
  IB 로 추정하지 않고(제외) 같은 오류로 근거를 남긴다 (2026-10-17).
- `port_type` ∈ {`FibreChannel`, `FCoE`, `iSCSI`}. `source` ∈ {`redfish`, `os`, `esxi`}.
- **IB `link_status`** — `up` = 활성(Linux `ACTIVE` · Windows `Up` · Redfish `LinkUp`/`Up`), `down` = 명확한 링크 없음(`DOWN` · `Disconnected` ·
  `LinkDown`/`NoLink`), `unknown` = 중간 상태 또는 미확인(Linux `INIT`/`ARMED`/`ACTIVE_DEFER` · Windows `Disabled`/`Not Present` · Redfish
  `Starting`/`Training`/없음). **`rate_gbps` 는 `up` 일 때만 숫자**(정수는 int, 2.5 같은 소수는 그대로)이고 `rate` 는 원천의 속도 문자열 원문이다
  (Redfish 는 문자열 원천이 없어 항상 null — 합성하지 않는다). GUID 는 소문자 `xxxx:xxxx:xxxx:xxxx` 로 통일하고 형식 오류·all-zero 는 null 이다.
- **빈 `infiniband` 의 뜻** — 어느 채널이든 "IB 장치 없음" 의 확정 증거가 아니다. 드라이버 미적재(Linux) · 매체 오보고(Windows) · 미수집(ESXi) ·
  BMC 미노출(Redfish) 이 모두 같은 모양이다. 조회 실패는 `errors[]`(Linux 속성 읽기 실패 · Redfish 하위 리소스 실패) 또는
  `diagnosis.details.notices`(Redfish 충돌 · 연결되지 않은 기능) 로 구분한다.
- **Windows `link_speed_gbps` (2026-10-10 · 2026-10-18)**: `MSFC_FibrePortHBAAttributes.PortSpeed` 는 비트 값이다 — Microsoft SDK `hbaapi.h` 정의대로
  1 → 1, 2 → 2, 4 → 10, 8 → 4, 16 → 8, 32 → 16 Gbps. 2026-10-18(사용자 결정)부터 T11 FC-HBA / SNIA HBA API · Linux `scsi_transport_fc.h` 와 같은 비트로
  64 → 32, 128 → 20, 256 → 40, 0x200 → 50, 0x400 → 100, 0x800 → 25, 0x1000 → 64, 0x2000 → 128 Gbps 도 바꾼다(Windows WMI 제공자가 같은 비트를 쓰는지는
  실장비 미확인 — 32G 이상 HBA 사이트 실측 시 정정). 0(미확인) · 0x8000(미협상) · 그 밖은 `null`. 종전 표는 4 · 8 · 16 을 4 · 8 · 10 으로 잘못 바꿨다.
- **HBA `link_status` (2026-10-18, 사용자 결정)** — 문자열은 `up` · `down` 둘뿐이고 **장비가 링크 상태 속성을 주지 않으면 `null`** 이다. 확인되지 않은 상태를
  `down` 으로 적지 않고, 종전 `unknown` 문자열은 폐지했다(`link_speed_gbps` · `wwnn` 의 "미노출 → null" 과 같은 규칙). 채널별 매핑은 `schema/field_dictionary.yml`
  `storage.hbas[].link_status` 가 정본이다: Redfish `LinkStatus`(없으면 null + notice `링크 상태 미제공`), Linux `port_state`(Online·Marginal → up / Offline·Linkdown·Error·
  Blocked·Bypassed·Loopback·Diagnostics → down / Unknown·Deleted·없음 → null), Windows `OperationalStatus`(2 → up / 3~8 → down / 1·없음 → MSFC `PortState` → null),
  ESXi `status`(online → up / offline → down / unbound·unknown·없음 → null). HPE CSUS 3200(RMC 1.75.108 · Redfish 1.19.0)은 FC Port 리소스에 `LinkStatus`·`Status`
  키가 없어 Redfish 로는 항상 `null` 이다 — 전수 크롤(2,264 리소스) 어디에도 FC 링크 상태가 없고(PCIe 장치의 `H3Alert.1.7.LinkUp` 은 RAID 컨트롤러에도 있는 슬롯
  링크다) 알림 로그 리소스도 없다(EventService 는 구독 전용). Portal 은 `wwpn` 으로 OS 채널 값을 조인해 보인다.
- **개수 원칙 (2026-10-18)** — 네 채널 모두 항목 1개 = 물리 FC 포트 1개. Linux 는 NPIV 가상 포트(`port_type` 'NPIV VPORT')를 빼고, ESXi 는 같은 (wwpn, wwnn) 의
  vmhba(ESXi 7 FC-NVMe: 포트당 SCSI vmhba + NVMe vmhba, 같은 WWPN)를 1건으로 접는다 — "ESXi 8 vs Redfish 4" 의 원인이었다. 그래도 Redfish(물리) ≥ OS/ESXi(논리) 일 수
  있다: lab Cisco C220 은 CIMC 가 카드 2장의 vHBA 4개를 정의하지만 ESXi 는 카드 1장의 fnic 2개만 열거한다(코드 결함 아님). 교차 대조 키는 `wwpn` 이고
  `tests/regression/test_cross_channel_same_server.py` 가 같은 서버 2쌍에서 "OS ⊆ Redfish" 를 고정한다.
- **FCoE 지원 CNA 는 여기 안 들어온다 (2026-08-03)**: Broadcom 57800 같은 CNA 는 *이더넷* 기능에도
  MAC 파생 WWN 을 달고 나온다. WWN 이 있다는 이유로 HBA 로 잡으면 같은 물리 포트가
  `network.ports[]`=Ethernet / `storage.hbas[]`=FibreChannel 로 갈리는 모순이 생긴다.
  → 분류는 **명시 신호**(`PortProtocol` / `NetDevFuncType`)를 우선하고, WWN 존재는 명시 신호가
  전무할 때만 쓴다. FCoE 를 실제로 설정한 장비는 `NetDevFuncType=FibreChannelOverEthernet` 을 주므로
  정상적으로 `port_type="FCoE"` 로 잡힌다.
- 서브필드 정의는 `schema/field_dictionary.yml` (`storage.hbas[].*` / `storage.infiniband[].*`, Nice).

#### 6.3.2 Redfish `hbas[]` — 어디서 읽나, 빈 목록과 `null` 의 뜻 (2026-10-15 · 2026-10-18)

항목 1개는 FC 포트(기능) 1개다. 2포트 카드면 2건이고, 소속 카드는 `adapter_id` / `adapter_model` 이다.

**읽는 곳과 순서**

1. System 의 `Links.Chassis` 첫 섀시의 `Chassis/{id}/NetworkAdapters`.
2. `Links.Chassis` 의 나머지 섀시. **다른 System 이 그 섀시를 연결하지 않았다는 것을 확인했을 때만** 본다. 다른 System(다른 파티션)도 연결한 섀시이거나 System 목록을 끝까지 읽지 못했으면 그 섀시는 보지 않고 notice 를 남긴다. 섀시가 가리키는 `NetworkAdapters` 링크를 따라가며, 링크가 없는 섀시(랙 · 인클로저)는 건너뛴다. Chassis 컬렉션 전체는 보지 않는다.
3. 위에서 카드를 하나도 얻지 못했을 때만(실패 또는 빈 목록) `Systems/{id}/NetworkAdapters`. 이 경로는 일부 펌웨어(iDRAC8)의 위치이고, 섀시 목록과 섞지 않는다.

같은 카드가 두 섀시 목록에 다시 나오면(같은 리소스 주소) 한 번만 담는다. 다른 주소로 같은 WWPN 의 FC 포트가 다시 나오면 그 포트만 뺀다. WWPN 을 모르는 포트는 같은 포트인지 확인할 수 없어 남긴다. 섀시가 다르면 `adapter_id` 가 겹칠 수 있다 — 포트를 가리키는 고유 키는 `wwpn` 이다.

**`wwpn` 은 기능(NetworkDeviceFunction)의 WWPN 이 첫째다.** 기능에 WWPN 이 없으면(2026-10-18) 포트의 FC 주소 목록 — 신 `Port.FibreChannel.AssociatedWorldWideNames`, 또는 FC 링크 기술
포트의 `Ethernet.AssociatedMACAddresses` 중 8옥텟 값 — 에서 알려진 WWNN 을 뺀 값이 **정확히 1개 남을 때만** 그것을 쓴다. 구 `NetworkPort.AssociatedNetworkAddresses` 는 쓰지 않는다
(실측 Dell R740: `20:00:…` = WWNN). 못 정하면 `wwpn: null` 로 행을 남기고 notice `WWPN 미확정` 을 적는다 — 행은 어떤 경우에도 빠지지 않는다. 2026-10-15~18 사이 운영 환경에
`_make_fc_hba` 의 wwpn 에 포트 주소를 넣은 임시 조치가 있었는데 그 값은 장비에 따라 WWNN 이라 틀린 값이었다 — 위 규칙이 그 자리를 대신한다.

**빈 `hbas` 의 뜻**

| `storage.hbas` | `errors[]` 중 `section: "network"` | `diagnosis.details.notices` 중 `section: "network_adapters"` | 뜻 |
|---|---|---|---|
| `[]` | 없음 | 없음 | 정상 수집. BMC 가 보여 준 카드에 FC 포트가 없다 |
| `[]` | 없음 | `NetworkAdapters 리소스 404, …미수집` | BMC 가 네트워크 카드 정보를 주지 않는다. 이 채널로는 HBA 유무를 확인하지 못했다 |
| `[]` | 없음 | `NetworkAdapters 목록이 비어 있음, …미확인` | BMC 가 빈 카드 목록을 줬다. HBA 유무를 확인하지 못했다 |
| `[]` 또는 일부 | 있음 (detail 에 경로와 HTTP 상태) | — | 수집이 일부 또는 전부 실패했다. 목록이 불완전할 수 있다 |
| 일부 | — | `…소유를 확인할 수 없어 …미수집` | 다른 System 도 연결한 섀시(또는 확인하지 못한 섀시)의 카드는 넣지 않았다 |

어느 경우든 `status` 와 `sections` 는 바뀌지 않는다. HBA 수집은 보조 수집이고, HBA 가 없다는 이유로 수집이 실패가 되지 않는다.

**`link_status`** — 포트의 `LinkStatus` 를 `up`(LinkUp · Up · Connected) / `down`(LinkDown · Down · NoLink · Starting · Training) 두 값으로 바꾸고, **키 자체가 없으면 `null`** 이다
(2026-10-18 — 종전 `unknown` 폐지, 임의 `down` 금지). `null` 의 원인은 두 가지고 둘 다 notice `네트워크 카드 … 링크 상태 미제공` 으로 남는다.
(a) 포트 응답에 `LinkStatus` 키가 없다 — 실측 HPE CSUS 3200 RMC 1.75.108: FC Port 리소스의 키는 `FibreChannel.AssociatedWorldWideNames` · `Id` · `Name` 셋뿐이고 다른 어느 리소스에도 FC 링크 상태가 없다.
(b) FC 기능에 짝이 되는 포트 리소스가 없고 이름(`<PortId>-n`)으로 부모 포트도 못 찾았다 — 이때 `link_speed_gbps` 도 `null` 이다. 부모를 찾으면 그 포트의 링크 · 속도를 상속한다(iDRAC8 형).
실제 링크 상태가 필요하면 OS 채널 결과와 `wwpn` 으로 맞춰 본다 — Portal 은 그렇게 표시한다.

**조용히 빠지던 경로 (2026-10-18 보완)** — 녹화본 변형으로 재현해 고쳤다: FC 링크 기술 포트에 `Ethernet` 블록만 있어 Ethernet 으로 오분류(HBA 0건 · 오류 0건) · 포트 `Id` 가 정수이고
짝 없는 기능이 있으면 TypeError 로 섹션 전체 소실 · 카드 목록은 200 인데 카드 GET 이 전부 404 면 흔적 없이 미지원 · 한 경로가 200 빈 목록이면 다른 경로의 5xx 가 묻힘 · 이름 · 컨트롤러
근거 없는 카드가 FC 기능을 가져도 제외 · 짝 없는 기능의 부모 포트 링크 버림. 카드 1장의 예외는 그 카드에서 격리되고(errors[] 1건) 다른 카드는 남는다. 사이트에서 보고된 "HBA 누락"
장비(벤더 미확정)는 이 중 어느 경로였는지 Redfish 덤프로 확정해야 한다.

**남은 사각지대** — BMC 가 카드 목록에서 FC 카드 자체를 빼고 주면 이 채널로는 알 수 없다. 이때는 OS 채널(`source: "os"`)로 교차 확인한다.
다중 섀시 수집과 소유 판정은 실장비의 다중 섀시 응답으로 아직 검증되지 않았다(합성 자료 시험만 통과).

#### 6.3.3 Redfish `infiniband[]` — 판정 · GUID · 빈 목록의 뜻 (2026-10-17)

항목 1개는 **현재 InfiniBand 모드로 확인된 포트 1개**다. 읽는 곳과 순서(섀시 · 소유 확인 · Systems 경로)는 6.3.2 와 같다 — 같은 카드 루프에서
FC 와 IB 를 함께 판정하고, IB 경로가 추가로 읽는 리소스는 없다.

**판정 — 현재 모드만 본다**

| 포트가 말하는 현재 모드 (`Port.LinkNetworkTechnology` / `NetworkPort.ActiveLinkTechnology` / `Port.PortProtocol`) | 포트에 연결된 기능의 `NetDevFuncType` | 결과 |
|---|---|---|
| `InfiniBand` | 없음 또는 전부 `InfiniBand` | IB 포트 — 항목 1개, `network.ports[].port_type = "InfiniBand"` |
| `InfiniBand` | `Ethernet`/`FibreChannel`/… 섞임 | **충돌** — 항목 없음, notice 1건 |
| `Ethernet` · `FibreChannel` · `RoCE` · `RoCEv2` · `iWARP` … | `InfiniBand` 있음 | **충돌** — 항목 없음, `port_type` 은 포트의 링크 기술, notice 1건 |
| `Ethernet` · … | `InfiniBand` 없음 | IB 아님 (종전 FC/Ethernet 규칙) |
| 없음 | 전부 `InfiniBand` | IB 포트 |
| 없음 | `InfiniBand` + 다른 것 | 충돌 |
| 없음 | `InfiniBand` 없음 | IB 아님 |

- 링크 기술과 `PortProtocol` 이 서로 다르면 그것도 충돌이다. `Disabled` 기능은 근거로 세지 않는다.
- **근거가 아닌 것**: `NetDevFuncCapabilities`(지원 가능 목록), `LinkConfiguration[].LinkNetworkTechnology`, `Port.InfiniBand` 블록의 존재, GUID 의 존재,
  `PortType`(IB/FC 값이 없다), `LinkState`(관리자가 바라는 상태), 카드 이름("InfiniBand NDR200/Ethernet 200GbE" 같은 VPI 제품명).
  HPE iLO 에뮬레이터의 MCX755106 VPI 카드는 이 모든 것을 가지고도 `NetDevFuncType: Ethernet` · `LinkNetworkTechnology: Ethernet` 이라 IB 가 아니다.
- **포트에 연결되지 않은 IB 기능**(`Links.PhysicalNetworkPortAssignment` 없음)은 항목이 되지 않는다 — 기능은 포트가 아니다. Dell 식 `<PortId>-<n>` 이름으로
  부모 포트를 찾을 수 있고 그 포트가 IB 항목이면 **비어 있는 GUID 만** 그 기능 값으로 채운다. 부모가 IB 가 아니면 충돌 notice, 부모를 못 찾으면
  "연결되지 않음" notice.

**GUID** — 연결된 IB 기능들의 `InfiniBand.NodeGUID` / `PortGUID`(없으면 `Permanent*`)가 하나로 일치할 때 그 값. 기능끼리 다르면 null(증거 충돌 —
배열로 대체하지 않는다). 기능이 값을 전혀 주지 않을 때만 `Port.InfiniBand.AssociatedNodeGUIDs` / `AssociatedPortGUIDs` 를 보되 **서로 다른 값이 정확히
하나일 때만** 쓴다. 이 배열은 DMTF 정의상 "lowest-numbered function 의 주소, configured but not active 주소, teaming 주소" 를 함께 담을 수 있어 첫 원소를
무조건 쓰지 않는다. 표기는 소문자 `xxxx:xxxx:xxxx:xxxx`.

**`link_status` · 속도** — IB 항목은 `LinkUp`/`Up` → `up`, `LinkDown`/`NoLink`/`Down` → `down`, `Starting`/`Training`/없음 → `unknown`.
`network.ports[].link_status` 는 종전 규칙(협상 중 = `down`)이라 같은 포트가 training 중이면 둘이 다를 수 있다.
`rate_gbps` 는 `up` 일 때만 `CurrentSpeedGbps`(없으면 `CurrentLinkSpeedMbps`/1000, 정수는 int)이고 `rate` 는 항상 null 이다.

**빈 `infiniband` 의 뜻**

| `storage.infiniband` | `diagnosis.details.notices` 중 `section: "network_adapters"` | 뜻 |
|---|---|---|
| `[]` | 없음 | 정상 수집. BMC 가 보여 준 카드에 IB 모드 포트가 없다 (또는 BMC 가 IB HCA 를 노출하지 않는다 — 6.3.2 의 카드 목록 notice 와 함께 본다) |
| `[]` | `…포트 링크 기술과 기능 유형이 서로 달라 InfiniBand 여부를 확정할 수 없음…` | 현재 모드 신호가 충돌한다. IB 로 확정하지 않았다 |
| `[]` | `…InfiniBand 기능 <id> 이(가) 어느 포트에도 연결되지 않음…` | IB 기능은 있으나 포트를 확인하지 못했다 |

어느 경우든 `status` 와 `sections` 는 바뀌지 않는다. **실장비 IB 모드 BMC 응답으로는 아직 검증되지 않았다** — 공개 mockup 도 없어
합성 fixture(`tests/fixtures/redfish/synthetic_ib_mode`, DMTF 스키마 기준)로만 재생했다.

### 6.4 `data.network`

```json
"network": {
  "interfaces": [
    { "id": "...", "kind": "server_nic", "mac": "...", "speed_mbps": 10240,
      "link_status": "up", "addresses": [...] },
    ...
  ],
  "dns_servers":      [],
  "default_gateways": [],
  "bonds":            [],   // Linux 본딩 (2026-06-15) — bond 없으면 빈 []
  "bridges":          [],   // Linux 브리지 — 없으면 빈 []
  "teams":            [],   // Windows 티밍(LBFO/SET) — 없으면 빈 []
  "summary":          { /* 같은 속도 NIC 묶은 집계 (slave NIC 미포함 — 기존과 동일) */ }
}
```

`link_status` 값 (2026-06-14 전 채널 통일 canonical — 이전 linkup/linkdown/none 폐기):
- `up` / `down` — 링크 활성 / 비활성(미연결·disabled·offline 포함)
- `unknown` — 상태 미제공/판별 불가 (HPE iLO / Cisco System NIC 등에서 종종 발생)
- `null` — 응답에 필드 자체가 없음
> **2026-10-10** — (1) `default_gateways[]` 는 **기본 경로 전부**다: Linux 는 metric 이 다른 복수 기본 경로 · ECMP(nexthop 마다) · IPv6 를 모두 내고(`ip route`
> 의 via/dev 토큰을 읽는다 — `default dev ppp0` · `nhid` 형식도 바르게 읽는다), Windows 는 IPv4 · IPv6 를 가족별로 낸다. 기본 경로가 없는 host 는 `[]` 다
> (종전 Linux 는 `"None"` 문자열이 들어갔다). (2) `interfaces[].addresses[].gateway` 는 그 주소 가족의 기본 경로가 그 인터페이스에 있을 때만 값이 있고,
> IPv6 주소의 게이트웨이는 `::/0` 경로의 인터페이스로 판정한다(Windows 종전에는 IPv4 기본 경로 인터페이스로 판정했다). `is_primary` 는 기본 경로를
> 가진 인터페이스다(IPv4 가 없으면 IPv6 기준). (3) **Redfish 채널**의 `dns_servers` · `default_gateways` 는 BMC 관리 NIC 의 값이다(2026-04-29 결정 유지 —
> 호스트 OS 값은 Redfish 로 얻을 수 없다). (4) Windows `dns_servers` 에서 IPv6 스택 자리표시자 `fec0:0:0:ffff::1~3` 은 뺀다. `driver_map[]` 은 연결이 끊긴
> 어댑터도 포함한다(Linux 와 같다). (5) ESXi 이름 서버 수집 실패 오류는 `dns_info` 가 실패했을 때만 남는다 — 종전에는 `config_info` 가 인자 오류로 늘
> 실패해 이름 서버가 비어 있는 host 가 `partial` 이었다(lab 의 ESXi 는 이름 서버가 있어 결과가 바뀌지 않았다 — 매트릭스 E2E-D 확인). (6) Linux `lspci` 오류(권한 등)는 stdout 표식으로 읽어 `errors[]` 에 남는다(종전 조건은 참이 될 수 없었다).

#### 6.4.1 본딩/티밍 토폴로지 (2026-06-15 — OS 채널, Additive)

`data.network.bonds[]` (Linux). python_ok(shell)·raw fallback 두 경로 동일 수집
(`/sys/class/net/*/bonding` + `/proc/net/bonding` + `ip -d link` 병합):

```json
"bonds": [
  {
    "name": "bond1", "mode": "active-backup", "active_slave": "ens161",
    "primary": "ens161", "miimon": 100, "lacp_rate": "slow",
    "xmit_hash_policy": "layer2", "ad_select": "stable",
    "addresses": [ { "family": "ipv4", "address": "10.x.x.169", ... } ],  // bond 자체 IP
    "slaves": [
      { "name": "ens161", "state": "active", "mii_status": "up",
        "perm_hwaddr": "00:50:56:...", "speed_mbps": 10000,
        "link_failure_count": 0, "mtu": 1500, "link_status": "up" },
      { "name": "ens193", "state": "backup", ... }
    ]
  }
]
```

`interfaces[]` 추가(Additive) 하위 필드 — bond/team 관련 인터페이스에만 존재(일반 NIC 는 키 부재):
- bond master: `bond_role:"master"`, `bond_mode`, `active_slave`, `bond_slaves[]`
- 물리 slave: `bond_role:"slave"`, `bond_master`, `slave_state(active|backup)`, `addresses:[]`(IP 없음)
- VLAN: `vlan_id`, `vlan_parent`
- Windows team master/member: `team_role(master|member)`, `team_master`, `team_type(lbfo|set)`, `teaming_mode`, `team_members[]`

`teams[]` (Windows LBFO/Get-NetLbfoTeam + SET/Get-NetSwitchTeam):
```json
"teams": [
  { "name": "Team1", "team_type": "lbfo", "teaming_mode": "Lacp",
    "load_balancing": "Dynamic", "lacp_timer": "Fast", "status": "Up",
    "members": [ { "name": "Ethernet", "mac": "...", "admin_mode": "Active",
                   "status": "Up", "speed_mbps": 10000 } ] }
]
```

구조 표현: 물리 NIC 는 IP 없이 `interfaces[]` 에 노출되고 IP 는 bond/team 인터페이스에 위치한다
(원본 `ip -br addr` 와 동일). `summary` 집계는 기존과 동일(slave 미포함)하여 호출자 호환.

#### 6.4.2 주소 alias / secondary 메타 (2026-06-17 OS Linux + 2026-06-30 Windows, Additive)

`interfaces[].addresses[]` 와 `bonds[].addresses[]` 의 각 주소 레코드는 기존 5 키
(`family` / `address` / `prefix_length` / `subnet_mask` / `gateway`) 에 다음 5 키를 **추가**한다.
수집 소스는 `ip -j addr show`(1순위) → `ip -o addr show`(2순위) → `ifconfig -a`(3순위) 의
다중 소스 폴백이다(nmcli/ifcfg 비의존 — Linux 계열 공통). bond alias(`bond1:1`)는 **새 인터페이스가
아니라** parent bond 의 추가 IP label 이므로 `interfaces[]` 에 별도 항목을 만들지 않고 parent 의
`addresses[]` 에 append 되며, bond master 면 `bonds[].addresses[]` 에도 동일하게 mirror 된다.

```json
"addresses": [
  { "family": "ipv4", "address": "10.100.64.169", "prefix_length": 24,
    "subnet_mask": "255.255.255.0", "gateway": null,
    "scope": "global", "label": "bond1",   "parent_interface": "bond1",
    "is_alias": false, "is_secondary": false },          // primary
  { "family": "ipv4", "address": "10.100.10.100", "prefix_length": 24,
    "subnet_mask": "255.255.255.0", "gateway": null,
    "scope": "global", "label": "bond1:1", "parent_interface": "bond1",
    "is_alias": true,  "is_secondary": false }            // bond alias (bond1:1)
]
```

| 키 | 의미 |
|---|---|
| `label` | `ip addr` 의 주소 label. alias 면 `bondX:N`, 일반 주소면 부모 ifname |
| `parent_interface` | 주소가 실제 바인딩된 인터페이스(=`ip` 의 dev). alias 도 parent=bond |
| `is_alias` | `label != parent_interface` 면 `true` (예: `bond1:1`) |
| `scope` | `global` / `link`(IPv6 fe80::) / `host`(loopback) — 기존 IPv6 scope 와 동일 키 |
| `is_secondary` | 커널 secondary(같은 서브넷 2번째+ IPv4). 다른 서브넷 alias 는 `false` |

- **호환성**: alias 없는 서버는 주소 수/기존 값 불변, 위 5 키만 Additive 추가(호출자 파싱 영향 없음).
- **채널**: `channel:[os]` (priority nice) — Linux + Windows 모두 채움. ESXi/Redfish addresses 는 기존 5 키 유지.
- **Windows (2026-06-30)**: 커널 secondary 플래그 API 가 없어 controller-side 파생(best-effort).
  - `is_secondary`: 같은 인터페이스+같은 서브넷 2번째+ IPv4 → `true` (Linux 커널 동작 모사). 예: `Ethernet4` 가
    `192.168.50.40` + `192.168.50.41`(같은 /24) 보유 시 `.41` 이 `is_secondary:true`.
  - `is_alias`: Windows 는 `bond1:1` 같은 alias 라벨 개념이 없어 **항상 `false`**, `label`/`parent_interface` = 인터페이스명.
  - `scope`: 커널 scope API 부재 → 주소로 best-effort 판정(`fe80::`→`link`, `127.`→`host`, 그 외 `global`).
- **검증**: Linux 실장비 10.100.64.161(RHEL 8.10 raw) / 10.100.64.165(RHEL 9.6 python) — `tests/evidence/2026-06-17-bond-alias-collection.md`.
  Windows 실장비 10.100.64.120(Server 2022) — `tests/evidence/2026-06-26-windows-net-ib-driver-team-vlan.md`.

### 6.5 `data.power` (Redfish 전용)

```json
"power": {
  "power_supplies": [
    { "name": "PS1 Status", "health": "Critical", "state": "UnavailableOffline", ... },
    { "name": "PS2 Status", "health": "OK",       "state": "Enabled", ... }
  ],
  "power_control": {
    "power_consumed_watts": 261,   // 현재 사용량
    "power_capacity_watts": 806,
    "min_consumed_watts":   260,
    "avg_consumed_watts":   260,
    "max_consumed_watts":   261
  }
}
```

PSU 한 대만 fault 여도 `hardware.health` 가 `Critical` 로 올라간다. 위 예시가 그 케이스.
> **2026-10-10** — PSU 요약(`psu_count` · `power_capacity_watts` 의 PSU 합)은 `State=Absent` 슬롯을 제외한다. `power_capacity_watts` 의 출처는 둘이다:
> legacy `Power.PowerControl.PowerCapacityWatts`(장비 예산값)와 `PowerSubsystem` 경로의 PSU 용량 합 — 같은 장비에서 값이 다를 수 있다.
> Power 와 Thermal 이 모두 404 면 `sections.power/thermal = not_supported` 다. PSU 컬렉션 · 멤버 조회가 404 가 아닌 오류로 끝나면 `errors[]` 에 남고
> "PSU 0" 처럼 성공으로 보이지 않는다.

### 6.6 `data.bmc` (Redfish 전용)

> 2026-06-14 (DELL R740 BMC-1): bmc 하위 필드가 field_dictionary 에 문서화됨 (이전엔 `bmc.ip` 만).

```json
"bmc": {
  "firmware_version": "7.00.00.184",   // Manager.FirmwareVersion (FirmwareInventory 아님 — 더 권위)
  "model": "14G Monolithic",           // Manager.Model
  "name": "iDRAC",                      // 벤더 표시 라벨 (iDRAC/iLO/XCC/CIMC)
  "health": "OK",                       // Manager.Status.Health (BMC 자체 — 장비 health 아님)
  "ip": "10.x.x.x",                     // BMC 관리 NIC (Manager 자체 EthernetInterface)
  "mac_address": "f4:02:70:...",        //  "  서버 OS NIC 아님
  "dns_name": "iDRAC-<ServiceTag>",       // BMC 자기 이름 (Manager NIC FQDN → HostName) — 서버 OS 이름 아님
  "network_hostname": "iDRAC-<ServiceTag>", // BMC 자기 이름 (Manager.NetworkProtocol FQDN → HostName) — hostname 3순위 후보
  "uuid": "3330...",                    // Manager UUID — System UUID(hardware.uuid)와 다름!
  "datetime": "2026-06-12T01:42:11-05:00", "datetime_offset": "-05:00",
  "oem": { "idrac_url": "https://...", "idrac_ipmi_version": "2.0", ... }
}
```

주의: `bmc.uuid` 는 **BMC 식별자**(Manager UUID)이고 `hardware.uuid` 는 **서버 식별자**(System UUID)다.
`bmc.dns_name` · `bmc.network_hostname` 은 **BMC 자기 이름**이라 봉투 `hostname`(서버 이름)과 값이 달라도 정상이다 — 8절.
`bmc.firmware_version` 은 Manager 가 직접 보고하는 BMC 펌웨어로, FirmwareInventory 의 BMC 항목(때로 stale)이 아니다.

### 6.7 `data.thermal` (Redfish 전용)

> 2026-06-14: 단일노드 thermal 수집 — 이전엔 multi_node(CSUS/Superdome) 경로만 수집했음.
> Chassis/{id}/Thermal (신 펌웨어는 ThermalSubsystem). 미지원/미노출 벤더는 빈 `{temperatures:[], fans:[]}` (graceful).

```json
"thermal": {
  "temperatures": [
    { "name": "CPU1 Temp", "reading_celsius": 47, "health": "OK",
      "state": "Enabled", "upper_critical": 104, "physical_context": "CPU" }
  ],
  "fans": [
    { "name": "System Board Fan1", "reading": 5760, "reading_units": "RPM",
      "health": "OK", "state": "Enabled" }
  ]
}
```

`reading_units` 는 `RPM`(legacy /Thermal) 또는 `Percent`(신 ThermalSubsystem.SpeedPercent). 팬 속도 비교 시
`reading_units` 를 반드시 확인. `upper_critical` 은 legacy 경로에서만 채워지고 신 schema 경로는 null.

### 6.8 `data.bios` (Redfish 전용 보조 데이터, 2026-09-15)

BIOS 설정값이다. **섹션이 아니다** — `sections` 에 `bios` 가 없고 `status` 판정에 쓰이지 않는다.
모든 Vendor 가 같은 경로 `data.bios.current.attributes` 를 쓴다.

어디서 오나: 수집기가 대표 ComputerSystem(`Systems` 컬렉션 첫 멤버 — `data.hardware` 와 같은 System)을
받을 때 응답의 `Bios.@odata.id` 를 기록해 두고, 그 링크로 Bios 리소스를 **1회** 조회한다.
ComputerSystem 을 다시 조회하지 않고, 링크가 없으면 System ID 로 `/Bios` 를 조립하지 않는다.

```json
"bios": {
  "current": {
    "attributes": {
      "AssetTag": "",
      "BootMode": "Uefi",
      "Proc1NumCores": 12,
      "ProcVirtualization": "Enabled",
      "SysPassword": null
    }
  }
}
```

`attributes` 규칙:

- 장비가 돌려준 `Attributes` **전체**다. Key 이름·Value·JSON 자료형을 바꾸지 않는다.
  문자열 `"0"`, 숫자 `0`, `false`, 빈 문자열 `""`, `null` 은 서로 다른 값으로 그대로 남는다.
  숫자처럼 보이는 문자열(예: `"BaudRate": "115200"`)도 문자열 그대로다.
- 필터·마스킹·이름 표준화·값 변환·개수 제한이 없다. Key 집합과 개수는 Vendor / 모델 / 펌웨어마다 다르다
  (실캡처 예: Dell R760 571개, Lenovo SR650 V2 392개, HPE DL380 Gen11 285개, Cisco CIMC 장비 87개).
  **고정 컬럼으로 다루지 말고 Key/Value 목록으로 표시한다.**
- Key 는 **이름순(대소문자를 구분하는 문자열 정렬)** 으로 담는다. 대문자가 소문자보다 앞이라 `cdnEnable` 처럼
  소문자로 시작하는 Key 는 뒤에 오고, 숫자는 글자 단위로 비교해 `Slot10` 이 `Slot2` 앞에 온다.
  장비가 준 순서는 쓰지 않는다 — Dell·HPE 는 원래 이 순서로 주지만 Lenovo 는 같은 장비도 수집할 때마다 순서가
  달랐고(서로 다른 시점 3건) Cisco 는 이름순이 아니다. BIOS 설정 화면의 메뉴 순서와도 다르다.
  JSON 객체의 Key 순서는 의미를 갖지 않으므로 받는 쪽은 순서에 기대지 않는다. 화면에 정렬이 필요하면 받는 쪽에서
  정렬한다 — DB 의 JSON 전용 타입처럼 저장할 때 Key 순서를 바꾸는 저장소도 있다.
- Current 값만 담는다. AttributeRegistry, `@Redfish.Settings` 가 가리키는 Settings, Pending / SD,
  Vendor OEM BIOS 하위 리소스는 수집하지 않는다. BIOS 설정 변경 기능도 없다.
- HPE Compute Scale-up Server 처럼 System 이 여럿이면 대표 System(Partition0) 1개만 본다.
  `multi_node.partitions[]` 에는 넣지 않는다.

`attributes` 값과 결과:

| `attributes` | 뜻 | `errors[]` 중 `section: "bios"` | `diagnosis.details.notices` 중 `section: "bios"` |
|---|---|---|---|
| 객체 | 정상 수집 | 없음 | 없음 |
| `{}` | 장비가 빈 `Attributes` 를 돌려줌 | 없음 | 있음 |
| `null` — ComputerSystem 에 `Bios` 링크 없음 / ComputerSystem 을 받지 못함 | 조회하지 않음 | 없음 | 있음 |
| `null` — Bios 리소스 HTTP 404 | 리소스 없음 | 없음 | 있음 |
| `null` — 응답이 표준 Bios 리소스가 아님 (최상위 `@odata.type` 이 `#Bios.` 로 시작하지 않음) | 표준 계약 밖 형식 | 없음 | 있음 |
| `null` — timeout / 연결 오류 / HTTP 401·403·기타 4xx·5xx / JSON 아님 / `Attributes` 없음·객체 아님 | 조회 실패 | `section: "bios"` 1건 | 없음 |

어느 경우든 `status`, `sections`, `diagnosis.failure_stage/code/reason`, `auth_success`, 다른 `data` 는
**바뀌지 않는다.** BIOS 조회의 401·403 이 host 를 실패로 만들거나 표준 계정 후보 재시도를 일으키지 않는다.
실패 `errors[]` 의 `message` 는 `"BIOS 설정 정보 수집에 실패한 항목이 있습니다. 대상 상태와 수집 로그를 확인하세요."` 이고
HTTP status 같은 기술 근거는 `detail` 에 있다.

수집에 들어가기 전에 멈춘 실패 envelope (rescue / `always` 최종 fallback / 콜백 보충) 에는 `data.bios` 키가 없다.
그 경로의 `data` 는 기존 뼈대 또는 `{}` 이다 (`multi_node` 와 같다).

**기술 경계 (Ansible no_log)**: 수집 모듈은 계정 비밀번호를 no_log 파라미터로 받는다. Ansible 은 모듈 결과에서
그 비밀번호 값을 치환하므로, BIOS Attribute 값이 **수집 계정 비밀번호와 같으면** `"VALUE_SPECIFIED_IN_NO_LOG_PARAMETER"`,
**비밀번호를 포함하면** 그 부분이 `********`, **문자열로 적었을 때 비밀번호를 포함하는 숫자**는
`"VALUE_SPECIFIED_IN_NO_LOG_PARAMETER"` 문자열로 나올 수 있다. Key 이름과 비밀번호와 무관한 값은 영향이 없다.
수집기는 비밀번호를 비교하거나 검출하지 않는다 (2026-09-15 결정).

검증 범위: Dell / HPE / Lenovo / Cisco 는 저장소 실캡처 재생으로, 나머지 Vendor 는 표준 응답 mock 으로만 확인했다.
Vendor·세대별 근거 수준은 `docs/reference/compatibility-matrix.md` 를 본다.

---

## 7. 자주 묻는 질문

**Q. `status: success` 인데 `errors[]` 에 항목이 있다. 정상인가?**
정상이다. **수집은 성공했고**, 다만 수집 도중 보인 비정상 신호 (PSU fault / SMART warning 등) 가 errors 에 기록된다. 알람을 errors 만 보고 띄우면 정상 케이스에도 시끄러워진다.

**Q. `vendor` 가 `null` 이면 어떡하나?**
새 펌웨어 / 보지 못한 모델이라 정규화 못 했다는 뜻. `data.hardware.vendor` 에 BMC 원본 값이 들어있으니 거기서 사람이 판단해야 한다. (그리고 `common/vars/vendor_aliases.yml` 에 별칭 추가하면 다음부터는 정규화된다.)

**Q. `hostname` 이 `null` 이다. 버그인가?**
아니다. 장비(BMC / OS / ESXi)가 hostname 을 제공하지 않으면 `null` 이다 (2026-06-16 정책 — "없는 건 없는 것"). **IP 로 fallback 하지 않는다.** 주소가 필요하면 별도 `ip` 필드를 본다. `hostname` 이 `ip` 와 같은 값으로 나오면 그건 옛 ip-fallback 잔재(정책 위반)다. 상세는 8절 참조.

**Q. `correlation.bmc_ip` 와 `correlation.host_ip` 가 같다. 버그인가?**
Redfish 채널은 둘이 같은 게 정상이다 (BMC 를 통해 수집). OS / ESXi 채널은 다를 수 있다 (서비스 IP 와 BMC IP 가 분리되어 있으면).

**Q. HPE Compute Scale-up Server 3200 의 시리얼에 `-000` 이 붙는다 / OS 와 Redfish 가 다르다. 버그인가?**
이 장비는 파티션(nPartition) 구조라 시스템 시리얼이 `<물리 시리얼>-<파티션번호 3자리>` 형식이다 (`SGHD3TLNDD-000`).
자산 관리는 물리 장비 시리얼 기준이므로 **OS 채널(`system.serial_number`)과 Redfish 채널(`data.hardware.serial`, 2026-10-17 부터)
모두 이 접미사를 뗀 값(`SGHD3TLNDD`)** 을 내보내고, `correlation.serial_number` 도 같은 값이다 — 같은 장비를 어느 채널로 봐도
시리얼이 같다. Redfish 의 `data.multi_node.partitions[].system.serial` 은 파티션 원본(`SGHD3TLNDD-000`)을 그대로 둔다.
그 외 장비는 수집한 값을 손대지 않는다 — 접미사 제거는 제조사(HPE)·모델(CSUS 3200)·접미사 형식 세 조건을 모두 만족할 때만
일어나므로, 시리얼에 하이픈이 정상적으로 들어간 다른 장비(ProLiant · Superdome Flex · Dell …)는 영향을 받지 않는다.
2026-10-17 이전 Redfish 결과는 `SGHD3TLNDD-000` 이었다(호출자가 저장한 값과 다를 수 있다).
자세한 규칙은 `docs/develop/05-field-mapping.md` 의 "nPartition 시리얼 접미사 정규화" 절을 본다.

**Q. Windows 의 `system.version` 이 `24H2` 로만 나온다. `2025-24H2` 가 아닌가? (2026-10-17)**
`system.version` 은 Windows 레지스트리 `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion` 의 `DisplayVersion`(없으면 `ReleaseId`, 그것도 없으면
`Win32_OperatingSystem.Version`)을 **자르지 않고 그대로** 낸 값이다. Windows Server 2025 는 `24H2`, 2022 는 `21H2` 를 준다(Microsoft 도 "Windows 11, version 24H2
and Windows Server 2025" 로 묶어 적는다). 제품명과 연도(`Microsoft Windows Server 2025 Datacenter`)는 `system.distribution`, 빌드 번호(`26100`)는 `system.kernel` 에 있다.
어떤 Windows API 도 `2025-24H2` 같은 합성 문자열을 주지 않으므로 수집기는 합성하지 않는다 — 그렇게 표시하려면 호출자가 `distribution` 의 연도와 `version` 을 합친다
(2026-10-17 사용자 결정: 수집기 현행 유지).

**Q. `schema_version` 이 바뀔 수 있나?**
바뀐다. 하지만 envelope 13 필드의 의미가 깨지는 변경이면 `"2"` 로 올라가고, 사람이 명시 승인을 해야 한다. 이전 버전 호환은 보장되지 않으니 호출 시 항상 schema_version 을 같이 본다.

---

## 8. hostname 해석 (System → BMC NetworkProtocol → null, 2026-06-16 정책)

`envelope.hostname` 은 다음 우선순위로 결정된다 (정본: `common/tasks/normalize/build_output.yml`):

```text
hostname = system.hostname  OR  system.fqdn  OR  bmc.network_hostname  OR  null
```

출처는 `diagnosis.details.hostname_source` (`system` | `bmc` | `none`) 로 표시한다.

> **정책 변천**:
> - 2026-05-07: hostname 미해석 시 `ip` fallback.
> - 2026-06-16 (사용자 지시): **IP fallback 폐지** ("없는 건 없는 것"). 단 IP 와 달리 장비에
>   고정된 실명인 **BMC 관리 호스트명**(`Manager.NetworkProtocol.HostName/FQDN` — iLO/XCC/RMC
>   이름)은 System.HostName 부재 시 fallback 허용. BMC 공장기본명(`ILOSGHD3KHHRP` 등)이 섞일 수
>   있어 `hostname_source` 로 출처를 명시 — 호출자가 "OS 호스트명 vs BMC 대체값"을 구분.
> - 2026-09-03 (OS/ESXi 전수 검수): OS 채널이 `system.hostname`(짧은 이름) 을 내기 시작했다 (종전 부재).
>   `system.fqdn` 은 3채널 모두 **hostname + 설정 도메인** 이며 도메인이 없으면 `null` — resolver(`getfqdn`)
>   결과가 아니다. 실패 envelope(rescue) 과 `always` 최종 fallback 도 같은 체인 + `hostname_source` 를 낸다
>   (종전에는 이 두 경로가 IP 를 넣었다).
> - 2026-10-15 (사용자 결정): Redfish 도 같은 계약을 따른다 — `system.hostname` = 원천 이름의 첫 라벨(종전 Redfish 는 이 키를
>   내지 않았다), `system.fqdn` = 도메인이 붙어 있을 때만 전체(종전에는 System.HostName 원본). 원천 순서는 adapter
>   `vendor_notes.hostname_priority` 로 정한다. **HPE CSUS 3200 은 `bmc_first`** — CSUS 1대 = RMC 1개 = 파티션 1개 = OS 1개라
>   RMC 이름이 서버 이름이다. RMC NetworkProtocol 이름을 쓰고, 없을 때만 Partition HostName 을 쓴다. 근거
>   `../reference/decision-log.md` 2026-10-15.

### 우선순위

| 순위 | 후보 | source | 출처 (채널/벤더) |
|---:|---|---|---|
| 1 | `data.system.hostname` | system | Linux `uname -n` 첫 라벨 / Windows `COMPUTERNAME`(DNSHostName) / ESXi `dnsConfig.hostName` / Redfish System.HostName 첫 라벨 (**HPE CSUS 3200: RMC NetworkProtocol 이름 → 없으면 Partition HostName**) |
| 2 | `data.system.fqdn` | system | hostname + 설정 도메인 (Linux `uname -n` 도메인부·`hostname -d` / Windows AD 도메인·DNS 접미사 / ESXi `dnsConfig.domainName` / Redfish 원천 이름에 도메인이 붙어 있을 때 그 전체). 도메인 없으면 null |
| 3 | `data.bmc.network_hostname` | bmc | Manager.NetworkProtocol.HostName/FQDN (**redfish 전용**) |
| 4 | (없음) | none | 전부 비면 `null` — **IP fallback 안 함** |

### 시나리오 (실측 2026-06-16, 2026-10-15 갱신)

| 장비 | System.HostName | BMC NetworkProtocol | hostname | `system.hostname` / `fqdn` | source |
|---|---|---|---|---|---|
| Dell R740 | `DELL01` | `iDRAC-J0KV603` | `DELL01` | `DELL01` / null | system |
| Dell R760 (production #296) | `r760-1.gooddi.lab` | `idrac-64CXJ54` | `r760-1` (종전 FQDN 전체) | `r760-1` / `r760-1.gooddi.lab` | system |
| HPE DL380 | `""` | `ILOSGHD3KHHRP` | `ILOSGHD3KHHRP` | null / null | bmc |
| Lenovo SR650 | (필드없음) | `XCC-7DGD-J902E57T` | `XCC-7DGD-J902E57T` | null / null | bmc |
| CSUS 사이트 장비 (2026-10-15) | `svu703327-net7` | `ycgsfaibap01` | **`ycgsfaibap01`** (종전 `svu703327-net7`) | `ycgsfaibap01` / null | system |
| CSUS node01 | `null` | `RMC7CA62A413692` | `RMC7CA62A413692` | `RMC7CA62A413692` / null | system (종전 bmc) |
| CSUS node03 | `m10mesdb11` | `M10MESDB11-RMC` | **`M10MESDB11-RMC`** (종전 `m10mesdb11`) | `M10MESDB11-RMC` / null | system |
| Cisco C220 | `C220-FCH2116V1V0` | `null` | `C220-FCH2116V1V0` | `C220-FCH2116V1V0` / null | system |
| (System없음+BMC null) | `null` | `null` | **`null`** | null / null | none |

CSUS 3200 은 `data.system.hostname` 을 RMC 이름으로 정하므로 `hostname_source` 가 `system` 이다. 파티션별 원본은
`data.multi_node.partitions[].system.hostname` 에 그대로 남고, `bmc.dns_name` · `bmc.network_hostname` 도 RMC 원본 그대로다.

### 벤더별 BMC fallback 동작 (중요 — 만능 아님)

`Manager.NetworkProtocol.HostName` 은 DMTF 표준 optional 속성이라 벤더/세대별 populate 여부가 다르다:
- **populate (bmc fallback 동작)**: Dell iDRAC9 / HPE iLO7·RMC / Lenovo XCC3 — 실측.
- **null (bmc fallback 도 null)**: Cisco CIMC — 실측(reference crawl). System.HostName 으로만 채워짐.
- **lab 부재(미확인)**: Supermicro / Huawei / Inspur / Fujitsu / Quanta + 구세대(iDRAC8 / iLO4~6 /
  XCC2 등) — DMTF 표준상 가능하나 실측 미확인. 매트릭스:
  `tests/evidence/2026-06-16-hostname-source-matrix.md` (lab 도입 후 검증).

구현은 **graceful**: 각 순위가 비면 다음으로, 전부 비면 null → 어느 벤더/세대든 안전.

### 호출자 주의

- `hostname` 은 nullable. `hostname_source == 'bmc'` 면 그 값은 **서버 OS 호스트명이 아니라
  관리 컨트롤러(BMC) 이름** — 식별엔 쓰되 OS hostname 으로 단정 금지.
- `hostname`(서버 이름)과 `bmc.dns_name` · `bmc.network_hostname`(BMC 자기 이름)은 다른 장치의 이름이라 값이 달라도 정상이다.
  예외는 HPE CSUS 3200 — 서버 이름을 RMC 이름으로 정하므로 둘이 같아진다(위 표).
- `hostname == ip` 는 금지(옛 ip-fallback 잔재). 회귀:
  `test_cross_channel_consistency.py::test_hostname_not_ip_fallback` +
  `test_hostname_fallback_chain.py` (체인 정본 + IP 미참조) +
  `test_real_capture_replay.py::test_bmc_network_hostname_collected`.

---

## 9. RMC 멀티-노드 토폴로지 (`data.multi_node`)

> 2026-05-12 추가. HPE Compute Scale-up Server 3200 / Superdome Flex 처럼 단일 RMC (Rack Management Controller) 가 N개 chassis × N개 nPartition × 다중 Manager 를 통합 노출하는 환경 정식 지원.
>
> 2026-06-09 확장. CSUS 3200 Redfish 모델 검수 결과 누락분 5종 Additive 추가 — per-partition `boot` (부팅 순서), per-chassis `thermal` (온도/팬), per-manager `log_services` (LogServices), `multi_node.composition` (CompositionService/ResourceBlocks), `multi_node.fabrics` (Fabrics/FlexGrid Switches+Endpoints, NUMAlink). 모두 `data.multi_node` 내부 신 키 (envelope 13 필드 / 기존 9 section path 변경 0).

### 활성 조건

`data.multi_node` 는 adapter `vendor_notes.manager_layout` 정의 vendor 에서만 활성:

| vendor | adapter | manager_layout | 활성 |
|---|---|---|---|
| HPE CSUS 3200 | `hpe_csus_3200.yml` | `rmc_primary` | YES |
| HPE Superdome Flex | `hpe_superdome_flex.yml` | `rmc_primary_ilo_secondary` | YES |
| 기타 13 vendor (HPE iLO 4~7 / Dell / Cisco / Lenovo / Supermicro / Huawei / Inspur / Fujitsu / Quanta) | — | (미정의) | NO — `data.multi_node = null` |

### Envelope shape (기존 path 는 유지하고 추가만 한다)

기존 9 section path (`data.system` / `data.bmc` / `data.cpu` / `data.memory` / `data.storage` / `data.network` / `data.firmware` / `data.power` / `data.hardware`) 는 **Partition0 representative** 로 그대로 유지. 호출자 시스템 파싱 변경 0.

```json
{
  "data": {
    "system": { ... },
    "bmc":    { "name": "RMC", ... },
    "cpu":    { ... },
    "...":    {},
    "multi_node": {
      "enabled": true,
      "layout": "rmc_primary",
      "summary": {
        "partition_count": 3,
        "manager_count": 4,
        "chassis_count": 3,
        "representative_partition": "Partition0",
        "resource_block_count": 3,
        "fabric_count": 1
      },
      "partitions": [
        { "id": "Partition0", "system_uri": "/redfish/v1/Systems/Partition0",
          "system": {}, "cpu": {}, "memory": {}, "storage": {}, "network": {},
          "boot": { "boot_order": ["Boot0001", "Boot0002"],
                    "boot_source_override_enabled": "Disabled",
                    "boot_source_override_target": "None",
                    "boot_source_override_mode": "UEFI" } },
        { "id": "Partition1" },
        { "id": "Partition2" }
      ],
      "managers": [
        { "id": "RMC",       "uri": "/redfish/v1/Managers/RMC",
          "role": "primary",   "bmc": { "name": "RMC" },
          "log_services": [ { "id": "IML", "name": "Integrated Management Log",
                              "overwrite_policy": "WrapsWhenFull", "service_enabled": true } ] },
        { "id": "PDHC0",     "role": "secondary", "bmc": { "name": "PDHC" }, "log_services": [] },
        { "id": "Bay1.iLO5", "role": "secondary", "bmc": { "name": "iLO" }, "log_services": [] }
      ],
      "chassis": [
        { "id": "Base",       "kind": "base",      "chassis_type": "Enclosure",
          "power": {}, "thermal": { "temperatures": [ { "name": "Inlet", "reading_celsius": 22, "health": "OK" } ],
                                    "fans": [ { "name": "Fan 1", "reading": 8000, "reading_units": "RPM", "health": "OK" } ] } },
        { "id": "Expansion1", "kind": "expansion" },
        { "id": "Expansion2", "kind": "expansion" }
      ],
      "composition": {
        "enabled": true, "state": "Enabled", "health": "OK", "resource_block_count": 3,
        "resource_blocks": [
          { "id": "Block0", "resource_block_types": ["Compute"], "composition_state": "Composed",
            "processor_count": 4, "memory_count": 8,
            "chassis": ["/redfish/v1/Chassis/Base"],
            "computer_systems": ["/redfish/v1/Systems/Partition0"] }
        ]
      },
      "fabrics": [
        { "id": "FlexGrid", "fabric_type": "PCIe", "health": "OK",
          "switch_count": 2, "endpoint_count": 2,
          "switches":  [ { "id": "Switch0", "switch_type": "PCIe", "health": "OK" } ],
          "endpoints": [ { "id": "Endpoint0", "endpoint_protocol": "PCIe", "health": "OK" } ] }
      ]
    }
  }
}
```

### 확장 컴포넌트 (2026-06-09)

CSUS 3200 Redfish 모델 검수 결과 추가된 5종. 모두 `data.multi_node` 내부 (Additive). Redfish 표준 리소스 미노출 시 graceful (boot/thermal=`{}`, log_services=`[]`, composition/fabrics=`null`).

| 키 | 출처 Redfish 리소스 | 필드 | 비고 |
|---|---|---|---|
| `partitions[].boot` | `Systems/{id}.Boot` | `boot_order[]`, `boot_source_override_enabled/target/mode`, `boot_next`, `uefi_target` | nPartition 별 부팅 순서 (설명 모델 요구). 미노출 시 `{}` |
| `chassis[].thermal` | `Chassis/{id}/Thermal` (404 시 `/ThermalSubsystem` DMTF 2020.4 fallback) | `temperatures[]` (name/reading_celsius/health/upper_critical), `fans[]` (name/reading/reading_units/health) | chassis 별 온도/팬. `power` 와 쌍 (설명 모델). 미노출 시 `{}` |
| `managers[].log_services` | `Managers/{id}/LogServices` | `id`, `name`, `overwrite_policy`, `service_enabled`, `log_entry_type`, `date_time` | RMC 의 Services/Logs (설명 모델). 로그 엔트리 자체는 범위 외. 미노출 시 `[]` |
| `composition` | `CompositionService` + `ResourceBlocks` | `enabled`, `state/health`, `resource_block_count`, `resource_blocks[]` (id/types/composition_state/processor_count/memory_count/`chassis[]`/`computer_systems[]`) | nPartition 조합 구조. 각 ResourceBlock ↔ chassis 대응 (설명 모델). ServiceRoot 미노출 시 `null` |
| `fabrics` | `Fabrics` + `Fabrics/{id}` (Switches/Endpoints) | `[]` of {id/fabric_type/health/`switch_count`/`endpoint_count`/`switches[]`/`endpoints[]`} | NUMAlink FlexGrid (Switches+Endpoints, Links/Zones 미사용 — 설명 모델). ServiceRoot 미노출 시 `null` |

> **Lab 부재 주의**: 위 5종은 lab 부재 web sources (DMTF DSP0266 + HPE CSUS 3200 Admin Guide + Superdome Flex 상속) 합성 검증. `fabric_type` 은 DMTF enum 에 NUMAlink 가 없어 placeholder (`PCIe`) — 사이트 실측 시 정정.

### 호출자 가이드

| 시나리오 | 권장 처리 |
|---|---|
| 기존 호출자 (`data.system` / `data.bmc` 만 사용) | 변경 0 — Partition0 데이터로 동일 동작 |
| 멀티-노드 인식 호출자 | `data.multi_node != null` 확인 후 `partitions[]` / `managers[]` / `chassis[]` 순회 |
| 확장 컴포넌트 인식 호출자 | `multi_node.composition` / `multi_node.fabrics` (null 가드) + `partitions[].boot` / `chassis[].thermal` / `managers[].log_services` 순회 |
| RMC 응답 없음 | `diagnosis.failure_stage` 가 `protocol` 이면 사이트 RMC 의 Redfish 서비스가 꺼져 있을 수 있다 ([../operate/06-rmc-activation.md](../operate/06-rmc-activation.md)) |

### Lab 부재 한계
- (2026-10-10) `multi_node.partitions[].network.summary` 는 빈 그룹, `memory.total_basis` 는 고정값이다 — CSUS lab 이 없어 파티션 단위 계산 근거를
  만들 수 없다. 두 값은 파티션 하위 섹션의 한계로 두고 지어내지 않는다.

현재 mock fixture 는 sdflexutils + DMTF v1.15 + iLO 5 API ref 합성. ServiceRoot.Product 정확 문자열 / Manager ID 패턴 / Oem.Hpe schema 는 사이트 실측 후 정정 의무 (내부 후속 작업 목록 C1~C8 참조).

---

## 10. 더 깊이 보고 싶을 때

| 보고 싶은 것 | 파일 |
|---|---|
| 라인별 한국어 주석 달린 실물 JSON | `schema/output_examples/redfish_dell_idrac9.jsonc` |
| 정상 / 부분 / 실패 / 미지원 4가지 케이스 JSON | `schema/examples/redfish_*.json`, `os_partial.json` |
| 벤더별 회귀 기준선 JSON | `schema/baseline_v1/{vendor}_baseline.json` |
| 섹션 정의 원본 | `schema/sections.yml` |
| 필드 사전 원본 | `schema/field_dictionary.yml` |
| 출력 조립 코드 | `common/tasks/normalize/build_output.yml` |
| 채널 처리 과정 | `docs/develop/01-gather-structure.md`, `docs/develop/02-normalize-flow.md` |
| 진단 단계 상세 | `docs/contract/04-failure-and-diagnosis.md` |
| 어댑터 매칭 규칙 | `docs/develop/03-adapter-system.md` |
