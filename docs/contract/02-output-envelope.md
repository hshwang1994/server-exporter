# 돌려받는 봉투의 모양

호출자가 받는 것은 항상 같은 모양의 JSON 하나다. 성공했든 실패했든, 어느 채널로 갔든
필드 구성이 같다. 이 문서는 그 봉투의 껍데기를 설명한다. 각 필드의 세부 의미는
[03-fields.md](03-fields.md)에 있다.

## 13개 필드

작성 순서 그대로다. `common/tasks/normalize/build_output.yml`이 12개를 만들고 각
채널이 `schema_version`을 붙여 13개가 된다.

```jsonc
{
  "target_type":       "os | esxi | redfish",
  "collection_method": "agent | vsphere_api | redfish_api",
  "ip":                "10.100.64.96",
  "hostname":          "r760-6",
  "vendor":            "dell",
  "status":            "success | partial | failed",
  "sections":          { "system": "success", "bmc": "not_supported", ... },
  "diagnosis":         { "reachable": true, ..., "details": { ... } },
  "meta":              { "started_at": "...", "duration_ms": 12345, ... },
  "correlation":       { "serial_number": "GSBPK54", ... },
  "errors":            [ ],
  "data":              { "cpu": { ... }, "memory": { ... }, ... },
  "schema_version":    "1"
}
```

`collection_method`는 채널에 따라 고정이다 — OS는 `agent`, ESXi는 `vsphere_api`,
Redfish는 `redfish_api`.

실제 응답 예시는 `schema/output_examples/` 아래에 채널·벤더별로 있다.

## status — 세 값이 어떻게 갈리나

`sections`의 값만 보고 정한다. `not_supported`인 섹션은 계산에서 빼고, 남은 것 중에

- 남은 게 하나도 없으면 `failed`
- 실패가 하나도 없으면 `success`
- 성공이 하나도 없으면 `failed`
- 그 밖에는 `partial`

**`errors`는 판정에 쓰지 않는다.** 이게 처음 보면 이상하게 느껴지는 지점이라 짚어 둔다.
`status`가 `success`인데 `errors`에 항목이 있을 수 있다. 예를 들어 Linux에서 메모리
총량을 `dmidecode`로 못 읽어 OS가 보는 값으로 대체했다면, 메모리 섹션은 정상 수집된
것이니 `success`지만 "물리 장착량이 아니라 OS 인식량이다"라는 경고가 `errors`에 남는다.

즉 `status`는 "섹션을 채웠는가", `errors`는 "채우는 과정에서 알아둘 일이 있었는가"다.
호출자는 둘을 따로 봐야 한다.

## sections — 11개가 항상 다 나온다

키는 언제나 11개다. 그 채널이 지원하지 않는 섹션은 빠지는 게 아니라 `not_supported`로
나온다.

```
system  hardware  bmc  cpu  memory  storage  network  firmware  users  power  thermal
```

값은 셋 중 하나다.

| 값 | 뜻 | 호출자가 할 일 |
|---|---|---|
| `success` | 채웠다 | `data.<섹션>`을 쓴다 |
| `failed` | 지원하는데 이번엔 못 채웠다 | `errors` 확인 후 재시도나 알림 |
| `not_supported` | 이 경로로는 원래 못 얻는다 | 누락이 아니다. 그냥 넘어간다 |

### 채널별로 실제 나오는 것

실장비에서 측정한 값이다 (2026-08-13).

| 채널 | success 로 나오는 섹션 |
|---|---|
| OS / Linux | system, cpu, memory, storage, network, users (6) |
| OS / Windows | 위 6개 + hardware (7) |
| ESXi | system, hardware, cpu, memory, storage, network (6) |
| Redfish | hardware, bmc, cpu, memory, storage, network, firmware, power, thermal (9) |

두 가지가 눈에 띌 것이다.

**Redfish에는 `system`이 없다.** `sections.system`은 `not_supported`로 나온다. 그런데
`data.system`에는 값이 들어 있다 — 대부분 `null`이고 `fqdn` 정도만 채워진다. 수집
코드가 내용은 넣으면서 지원 선언은 하지 않기 때문이다
(`redfish-gather/tasks/normalize_standard.yml:470-478`, `:580-581`). 호출자는
`sections`를 기준으로 판단하는 편이 안전하다.

**Windows만 `hardware`가 나온다.** 스키마 정의(`schema/sections.yml`)는 `hardware`를
ESXi·Redfish 전용으로 적어 두었지만, Windows 수집이 이 섹션을 채운다. 정의와 동작이
어긋난 상태이고, 실제 동작은 위 표대로다.

## diagnosis — 어디까지 갔는지

평평한 8개 키다. 중첩은 `details` 하나뿐이고 그것도 객체다.

```jsonc
"diagnosis": {
  "reachable":          true,     // TCP 연결이 됐거나 RST 를 받았다
  "port_open":          true,
  "protocol_supported": true,
  "auth_success":       true,
  "failure_stage":      null,     // 성공이면 셋 다 null
  "failure_code":       null,
  "failure_reason":     null,
  "details":            { "channel": "redfish", "checked_ports": [443], ... }
}
```

`reachable`은 **ICMP 응답이 아니다.** 이 시스템은 핑을 쓰지 않는다. 관리망에서 핑이
막혀 있어도 BMC는 443으로 답하기 때문이다.

`auth_success`의 값 세 가지가 각각 다른 뜻이다 — `true`는 실제로 인증에 성공, `false`는
장비가 명시적으로 거부, `null`은 시도하지 않았거나 확정할 수 없음. 타임아웃이나 TLS
오류, HTTP 403은 `false`가 되지 않는다.

실패했을 때 무엇을 보는지는 [04-failure-and-diagnosis.md](04-failure-and-diagnosis.md)에서
따로 다룬다.

## errors — 항목 하나의 모양

키가 정확히 셋이다.

```jsonc
{ "section": "memory", "message": "사용자에게 보일 문장", "detail": "기술 근거 또는 null" }
```

`message`는 절대 비지 않는다. 화면에 그대로 띄울 수 있는 한국어 문장이고, 포트 번호나
HTTP 상태 같은 내부 사정은 들어가지 않는다. 그런 건 `detail`에 간다.

## meta

```jsonc
"meta": {
  "started_at": "2026-08-13T00:12:03Z",
  "finished_at": "2026-08-13T00:12:41Z",
  "duration_ms": 38210,
  "adapter_id": "redfish_dell_idrac10",
  "adapter_version": null,
  "ansible_version": "2.20.7"
}
```

`adapter_version`은 **항상 `null`**이다. 어떤 어댑터 파일도 버전을 정의하지 않는다.
필드가 남아 있는 건 형태를 유지하기 위해서다.

`adapter_id`는 어떤 수집 규칙이 쓰였는지 알려 준다. 다만 이 값이 장비의 실제 세대와
다를 수 있다 — 자세한 건 [reference/live-validation.md](../reference/live-validation.md)에
기록해 두었다.

## correlation — 같은 기계를 알아보는 열쇠

```jsonc
"correlation": {
  "serial_number": "GSBPK54",
  "system_uuid":   "4c4c4544-...",
  "bmc_ip":        null,
  "host_ip":       "10.100.64.96"
}
```

한 물리 서버를 BMC로도 OS로도 조회했을 때 이 값으로 같은 기계임을 알 수 있다.
실제로 확인했다 — Dell R760 한 대를 BMC(`10.100.15.34`)와 그 위의 Ubuntu(`10.100.64.96`)
양쪽에서 수집했더니 둘 다 `GSBPK54`가 나왔다.

다만 **값이 같은 이유는 계약이 보장해서가 아니라 두 경로가 같은 SMBIOS를 읽기
때문이다.** 읽는 위치는 채널마다 다르다.

| 채널 | 어디서 읽나 |
|---|---|
| Redfish | BMC가 보고하는 `ComputerSystem.SerialNumber` |
| ESXi | 하이퍼바이저가 본 SMBIOS |
| Windows | WMI `Win32_BIOS`의 serial |
| Linux | DMI `product_serial` |

게다가 Linux만 봉투 안에서 다른 경로를 탄다. 다른 채널은 `data.hardware.serial`에서
가져오는데, Linux는 `hardware` 섹션 자체가 없어 `data.system.serial_number`로 떨어진다
(`common/tasks/normalize/build_correlation.yml:18-39`). 결과는 같지만 경로가 다르다는 걸
알아 두면 값이 안 맞을 때 어디를 봐야 할지 판단이 선다.

## hostname 이 비는 경우

`data.system.hostname` → `data.system.fqdn` → `data.bmc.network_hostname` 순으로 찾고,
셋 다 없으면 `null`이다. **IP로 대체하지 않는다.** 어느 것에서 왔는지는
`diagnosis.details.hostname_source`에 `system` / `bmc` / `none`으로 적힌다.

## data

섹션 이름이 그대로 키가 된다. 수집하지 못한 섹션은 그 섹션의 빈 모양으로 남는다 —
객체인 섹션은 `null`, 배열인 섹션은 `[]`. 빈 문자열은 쓰지 않는다.

## 다음

- 필드 하나하나의 의미: [03-fields.md](03-fields.md)
- 실패 봉투 읽는 법: [04-failure-and-diagnosis.md](04-failure-and-diagnosis.md)
- 보내는 쪽: [01-input.md](01-input.md)
