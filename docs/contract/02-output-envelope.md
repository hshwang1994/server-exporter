# 돌려받는 봉투의 모양

호출자가 받는 것은 항상 같은 모양의 JSON 하나입니다. 성공했든 실패했든, 어느 채널로 갔든 필드 구성이 같습니다. 이 문서는 그 봉투의 껍데기를 설명하고, 각 필드의 세부 의미는 [03-fields.md](03-fields.md)에 있습니다.

## 전송 본문

Portal은 `callbackUrl`에 `/api/jenkins/gather/<target_type>` 경로를 붙인 주소로 POST 하나를 받습니다. 본문은 다음 모양이고 `gatherInfoJson`에 접수한 서버마다 봉투가 하나씩 들어 있습니다.

```jsonc
{
  "loc": "ic",
  "deploymentEnvironmentId": "1",
  "eventUuid": "요청 때 보낸 값",
  "gatherInfoJson": [ { ...봉투... }, { ...봉투... } ]
}
```

접수한 서버 수와 봉투 수는 항상 같습니다. 전송은 2xx 응답을 받으면 끝이고, 같은 요청을 다시 보내지 않습니다.

## 13개 필드

작성 순서 그대로입니다. `common/tasks/normalize/build_output.yml`이 12개를 만들고 각 채널이 `schema_version`을 붙여 13개가 됩니다.

```jsonc
{
  "target_type":       "os | esxi | redfish",
  "collection_method": "agent | vsphere_api | redfish_api",
  "ip":                "192.0.2.10",
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

`collection_method`는 채널마다 고정입니다. OS는 `agent`, ESXi는 `vsphere_api`, Redfish는 `redfish_api`입니다.

실제 응답 예시는 `schema/output_examples/`와 `schema/examples/` 아래에 채널과 벤더별로 있습니다.

## status: 세 값이 어떻게 갈리나

`sections`의 값만 보고 정합니다. `not_supported`인 섹션은 계산에서 빼고 남은 것 중에

- 남은 것이 하나도 없으면 `failed`
- 실패가 하나도 없으면 `success`
- 성공이 하나도 없으면 `failed`
- 그 밖에는 `partial`

예외는 하나입니다(2026-10-13). OS 채널에서 Serial Number 를 수집하지 못한 서버는 섹션이 모두 `success` 여도 `failed` 입니다 — [03-fields.md](03-fields.md) 4절의 시나리오 E.

`errors`는 판정에 쓰지 않습니다. `status`가 `success`인데 `errors`에 항목이 있을 수 있습니다. 예를 들어 Linux에서 메모리 총량을 `dmidecode`로 못 읽어 OS가 보는 값으로 대체했다면, 메모리 섹션은 정상 수집된 것이니 `success`지만 "물리 장착량이 아니라 OS 인식량이다"라는 안내가 `errors`에 남습니다.

즉 `status`는 "섹션을 채웠는가", `errors`는 "채우는 과정에서 알아둘 일이 있었는가"입니다. 호출자는 둘을 따로 봐야 합니다.

## sections: 11개가 항상 다 나옵니다

키는 언제나 11개입니다. 그 채널이 지원하지 않는 섹션은 빠지는 것이 아니라 `not_supported`로 나옵니다.

```text
system  hardware  bmc  cpu  memory  storage  network  firmware  users  power  thermal
```

| 값 | 뜻 | 호출자가 할 일 |
|---|---|---|
| `success` | 채웠습니다 | `data.<섹션>`을 씁니다 |
| `failed` | 지원하는데 이번엔 못 채웠습니다 | `errors` 확인 후 재시도나 알림 |
| `not_supported` | 이 경로로는 원래 못 얻습니다 | 누락이 아닙니다. 넘어갑니다 |

채널별로 `success`로 나오는 섹션입니다 (사내 실장비 명부, 2026-10-11 production 빌드 #275~#279).

| 채널 | `success`로 나오는 섹션 |
|---|---|
| OS / Linux | system, hardware, cpu, memory, storage, network, users (7) |
| OS / Windows | system, hardware, cpu, memory, storage, network, users (7) |
| ESXi | system, hardware, cpu, memory, storage, network (6) |
| Redfish | hardware, bmc, cpu, memory, storage, network, firmware, power, thermal (9) |

Redfish에는 `system`이 없습니다. `sections.system`은 `not_supported`로 나오지만 `data.system`에는 값이 들어 있습니다. 대부분 `null`이고 `fqdn`만 채워지는데, 이 `fqdn`은 `hostname` 필드를 채우는 데 쓰입니다. 호출자는 `sections`를 기준으로 판단하는 편이 안전합니다. Redfish의 `power`와 `thermal`은 BMC가 해당 리소스를 주지 않으면 `not_supported`입니다.

## diagnosis: 어디까지 갔는지

평평한 8개 키입니다. 중첩은 `details` 하나뿐이고 그것도 객체입니다.

```jsonc
"diagnosis": {
  "reachable":          true,     // TCP 연결이 됐거나 RST 를 받았거나 ICMP 가 응답했다
  "port_open":          true,
  "protocol_supported": true,
  "auth_success":       true,
  "failure_stage":      null,     // 성공이면 셋 다 null
  "failure_code":       null,
  "failure_reason":     null,
  "details":            { "channel": "redfish", "checked_ports": [443], ... }
}
```

`reachable`은 관리 TCP 응답 또는 ICMP Echo 응답입니다. 순서가 있습니다. 관리 포트를 먼저 보고, TCP가 아무 응답도 주지 않았을 때만 Echo를 한 번 더 보냅니다. 핑은 관문이 아니라서 관리망이 핑을 막아 둬도 BMC가 443으로 답하면 그대로 통과합니다. 반대로 방화벽이 관리 포트 TCP를 조용히 버리는 구간에서는 Echo 응답이 "장비는 있다"를 증명해 실패가 `reachable`이 아니라 `port` 단계로 내려갑니다.

`auth_success`의 값 세 가지는 각각 다른 뜻입니다. `true`는 실제로 인증에 성공, `false`는 장비가 명시적으로 거부, `null`은 시도하지 않았거나 확정할 수 없음입니다. 타임아웃이나 TLS 오류, HTTP 403은 `false`가 되지 않습니다.

실패했을 때 무엇을 보는지는 [04-failure-and-diagnosis.md](04-failure-and-diagnosis.md)에서 따로 다룹니다.

## errors: 항목 하나의 모양

키가 정확히 셋입니다.

```jsonc
{ "section": "memory", "message": "사용자에게 보일 문장", "detail": "기술 근거 또는 null" }
```

`message`는 비지 않습니다. 화면에 그대로 띄울 수 있는 한국어 문장이고 포트 번호나 HTTP 상태 같은 내부 사정은 들어가지 않습니다. 그런 것은 `detail`에 갑니다.

`section`에는 섹션 이름 말고도 수집 단계 이름, 보조 데이터 이름 `bios`, 추가 수집 `addon`이 올 수 있습니다. 전체 목록은 [03-fields.md](03-fields.md) 4-1절에 있습니다.

## meta

```jsonc
"meta": {
  "started_at": "2026-08-13T00:12:03Z",
  "finished_at": "2026-08-13T00:12:41Z",
  "duration_ms": 38210,
  "adapter_id": "redfish_dell_idrac9",
  "adapter_version": null,
  "ansible_version": "2.20.3"
}
```

`adapter_version`은 항상 `null`입니다. 어댑터 파일이 버전을 정의하지 않고, 필드는 형태를 유지하기 위해 남아 있습니다.

`duration_ms`는 그 대상 한 대의 수집 시작부터 끝까지의 밀리초이고 배치 전체 시간이 아닙니다. 추가 수집(Add-on)이 켜진 빌드에서는 Add-on이 끝난 시각으로 `finished_at`과 `duration_ms`를 다시 적으므로 Add-on 시간이 들어갑니다.

`adapter_id`는 어떤 수집 규칙이 쓰였는지 알려 줍니다 ([../develop/03-adapter-system.md](../develop/03-adapter-system.md)).

## correlation: 같은 기계를 알아보는 열쇠

```jsonc
"correlation": {
  "serial_number": "GSBPK54",
  "system_uuid":   "4c4c4544-...",
  "bmc_ip":        null,
  "host_ip":       "192.0.2.10"
}
```

한 물리 서버를 BMC로도 OS로도 조회했을 때 이 값으로 같은 기계임을 알 수 있습니다. 사내 Dell R760 한 대를 BMC와 그 위의 Ubuntu 양쪽에서 수집했을 때 둘 다 같은 시리얼이 나왔습니다.

다만 값이 같은 이유는 계약이 보장해서가 아니라 두 경로가 같은 SMBIOS를 읽기 때문입니다. 읽는 위치는 채널마다 다릅니다.

| 채널 | 어디서 읽나 |
|---|---|
| Redfish | BMC가 보고하는 `ComputerSystem.SerialNumber` |
| ESXi | 하이퍼바이저가 본 SMBIOS |
| Windows | `Win32_BIOS`의 serial |
| Linux | DMI `product_serial` |

Linux는 `data.hardware.serial`과 `data.system.serial_number`에 같은 값이 들어가고, `correlation`은 `hardware.serial`이 없으면 `system.serial_number`를 씁니다 (`common/tasks/normalize/build_correlation.yml`).

## hostname이 비는 경우

`data.system.hostname` → `data.system.fqdn` → `data.bmc.network_hostname` 순으로 찾고 셋 다 없으면 `null`입니다. IP로 대체하지 않습니다. 어느 것에서 왔는지는 `diagnosis.details.hostname_source`에 `system`, `bmc`, `none`으로 적힙니다.

## data

섹션 이름이 그대로 키가 됩니다. 수집하지 못한 섹션은 그 섹션의 빈 모양으로 남습니다. 객체인 섹션은 `null`, 배열인 섹션은 `[]`입니다. 빈 문자열은 쓰지 않습니다.

Redfish 결과의 `data`에는 섹션이 아닌 보조 키가 둘 더 있습니다. `multi_node`(멀티 노드 장비만 채워지고 나머지는 `null`)와 `bios`(BIOS 설정값, `data.bios.current.attributes`)입니다. 둘 다 `sections`에 나오지 않고 `status` 판정에도 쓰이지 않습니다. 수집에 들어가기 전에 멈춘 실패 봉투에는 키 자체가 없습니다. 규칙은 [03-fields.md](03-fields.md) 6.8절과 9절에 있습니다.

추가 수집(Add-on)을 쓰는 환경에서는 `data`에 보조 키 `addon`이 붙을 수 있습니다. Add-on 설정에 맞는 Linux와 Windows 서버에만 생기고 그 밖에는 키 자체가 없으니 읽기 전에 키가 있는지 확인합니다.

```jsonc
"addon": {
  "swList":   [ { "name": "bash", "value": "5.1.8-9.el9" }, { "name": "oracle", "value": null } ],
  "dbIpList": [ { "ip": "10.10.10.11", "purpose": "vip" } ]
}
```

| 키 | 서버 | 내용 |
|---|---|---|
| `swList[]` | Linux, Windows | `{name, value}`. 그 서버에서 실행 대상이 된 Software마다 1개, 설정 순서대로 |
| `dbIpList[]` | Add-on hosts 기능이 적용된 Linux 서버 | `{ip, purpose}`. `/etc/hosts`에서 고른 DB IP와 용도 |

- `sections`에 나오지 않고 `status`와 `diagnosis` 판정에도 쓰이지 않습니다. 추가 수집이 실패해도 기본 수집 결과는 그대로입니다.
- `swList[].value`는 명령이 종료코드 0으로 끝나고 출력이 있을 때 그 출력에서 앞뒤 공백을 지운 문자열입니다. 값을 얻지 못하면 항목은 남고 `value`는 `null`입니다.
- 출력에 UTF-8로 읽을 수 없는 바이트가 있으면 그 바이트만 `\xNN` 네 글자로 옵니다.
- Add-on 기능 단위의 문제는 `errors[]`에 `section: "addon"` 1건으로 남고 이유는 `detail`에 있습니다.
- ESXi와 Redfish 서버에는 `addon`이 생기지 않습니다.

Add-on 계약의 상세는 [../develop/07-addon-hook.md](../develop/07-addon-hook.md)에 있습니다.

## 다음

- 필드 하나하나의 의미: [03-fields.md](03-fields.md)
- 실패 봉투 읽는 법: [04-failure-and-diagnosis.md](04-failure-and-diagnosis.md)
- 보내는 쪽: [01-input.md](01-input.md)
