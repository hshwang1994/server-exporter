# 20. JSON 출력 — 받았는데 무슨 뜻이지?

## 이 문서는 누가 읽나

server-exporter 가 던져주는 JSON 을 **받아서 쓰는 쪽** 사람들이 본다. 화면에 띄우든, DB 에 넣든, 알람을 만들든 — 일단 "이 필드가 뭘 의미하나" 를 알아야 시작이 된다.

이 문서를 끝까지 읽으면 다음 4가지를 안다.

1. JSON 한 통이 어떻게 생겼는지 (예시 1개 통째로)
2. 최상위 13개 키가 각각 뭘 가리키는지
3. `status` 가 `success` 인데 `errors` 가 비어있지 않을 수 있는지 (있다)
4. OS / ESXi / Redfish 채널마다 뭐가 다른지

코드 / 주석 달린 실물 JSON 을 먼저 보고 싶으면 → `schema/output_examples/redfish_dell_idrac10.jsonc` 부터 보면 빠르다.

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
    "power":   "success"
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
    "firmware": [ { "name": "BIOS", "version": "2.21.2", ... }, ... ],
    "power":    { "power_supplies": [...], "power_control": {...} },
    "users":    [],
    "system":   { "fqdn": "LENOVO01", ... }
  },

  "schema_version": "1"
}
```

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
| `hostname` | 문자열 | 풀어낸 호스트명. fallback chain: `system.hostname → system.fqdn → ip`. 상세: 8절 hostname fallback |
| `vendor` | `dell` / `hp` / `hpCsus` / `lenovo` / `supermicro` / `cisco` / `null` | 호출자 노출 표시값. 내부 canonical(`hpe`)을 `vendor_output_display`/`adapter_output_display`(vendor_aliases.yml)로 매핑. HPE 계열→`hp`, HPE Compute Scale-up 패밀리(CSUS 3200 + Superdome Flex)→`hpCsus`(camelCase 예외, 2026-06-04 ADR). 대부분 소문자 한 단어 |

### 그룹 B — 결과 (2개)

| 키 | 무슨 값 | 의미 |
|---|---|---|
| `status` | `success` / `partial` / `failed` | **수집 결과**. 장비 상태 아님 |
| `sections` | 섹션 10개 각각 `success` / `failed` / `not_supported` | 섹션별 결과 |

`status` 가 어떻게 결정되는지는 4절에서 따로 정리.

### 그룹 C — 무슨 일이 있었는지 (4개)

| 키 | 무슨 값 | 의미 |
|---|---|---|
| `diagnosis` | 객체 | precheck 4단계 (ping → port → protocol → auth) 결과. 어디서 막혔는지 |
| `meta` | 객체 | 시작/종료 시각, 소요 시간, 사용된 adapter ID |
| `errors` | 배열 | 수집 중 발생한 오류 목록. 정상이면 `[]` |
| `correlation` | 객체 | 시리얼 / UUID / IP — 다른 시스템 데이터와 묶을 때 쓰는 키들 |

### 그룹 D — 알맹이 (2개)

| 키 | 무슨 값 | 의미 |
|---|---|---|
| `data` | 객체 | 실제 수집한 정보. 섹션별로 들어있음 |
| `schema_version` | `"1"` | envelope 자체 버전. 깨지는 변경 시 `"2"` 로 올라감 |

---

## 3. 섹션 10개 — 어떤 채널이 뭘 채우나

JSON 의 `sections` 와 `data` 는 같은 10개 키를 갖는다. 각 채널이 채울 수 있는 영역이 다르다.

| 섹션 | 무엇 | OS | ESXi | Redfish |
|---|---|:-:|:-:|:-:|
| `system` | 운영체제 / 호스트명 / 가동시간 | O | O | (X) |
| `hardware` | 벤더 / 모델 / 시리얼 / BIOS | | O | O |
| `bmc` | iDRAC / iLO / XCC 자체 정보 | | | O |
| `cpu` | 소켓 / 코어 / 모델 | O | O | O |
| `memory` | 총량 / DIMM 슬롯 | O | O | O |
| `storage` | 디스크 / RAID / 파일시스템 | O | O | O |
| `network` | NIC / IP / DNS / 게이트웨이 | O | O | O |
| `firmware` | 펌웨어 인벤토리 | | | O |
| `users` | OS 로컬 계정 | O | | |
| `power` | PSU / 전력 사용 | | | O |

(X) = `not_supported`. 그 채널 특성상 원래 못 가져오는 영역이다. 수집 실패와 다른 의미다.

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
| **D. 실패** | `failed` | 비어있지 않음 | 거의 다 `failed` | precheck 4단계 어디서 막힘 (ping/port/protocol/auth) |

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

## 5. `diagnosis` — 어디서 막혔는지

연결이 안 됐을 때 가장 먼저 보는 곳. precheck 4단계가 순서대로 체크되고, 막힌 단계의 boolean 이 `false` 로 찍힌다.

```json
"diagnosis": {
  "reachable":          true,    // 1단계: ping 응답?
  "port_open":          false,   // 2단계: 해당 포트 (Redfish=443, SSH=22 등) 응답?
  "protocol_supported": false,
  "auth_success":       false,
  "failure_stage":      "port",  // 막힌 단계 이름
  "failure_reason":     "TCP 443 connection refused",
  "details": { ... }             // 채널별 부가 정보 (선택된 adapter, BMC product 명 등)
}
```

읽는 법: **위에서 아래로 첫 번째 false 찍힌 단계가 실패 지점**.

| `failure_stage` | 의미 | 해결 방향 |
|---|---|---|
| `null` | 실패 안 함 | 정상 |
| `reachable` | 호스트 자체가 응답 없음 | 호스트 전원 / 네트워크 / 라우팅 |
| `port` | 호스트는 응답하나 포트 닫힘 | 방화벽 / 서비스 미기동 / 포트 번호 오설정 |
| `protocol` | 포트는 열렸는데 응답 형식이 이상함 | TLS 버전 / cipher / 펌웨어 버그 |
| `auth` | 자격증명 거부됨 | 비밀번호 회전 / 계정 잠김 / 권한 부족 |

---

## 6. `data.<section>` — 알맹이는 어떻게 생겼나

10개 섹션을 다 풀면 길어진다. 가장 자주 쓰이는 5개만 여기서 정리하고, 나머지는 라인별 한국어 주석본 (`schema/output_examples/redfish_dell_idrac10.jsonc`) 을 본다.

### 6.1 `data.hardware`

장비 본체 정보. **`health` 필드가 가장 중요**하다.

```json
"hardware": {
  "vendor":       "Dell Inc.",        // BMC 가 보고한 원본 manufacturer (정규화 안 한 값)
  "model":        "PowerEdge R740",
  "serial":       "CNIVC009CP0282",
  "uuid":         "4c4c4544-...",
  "sku":          "2BJ8033",          // 벤더마다 의미 다름 (Dell=서비스 태그 / HPE=파트번호 / Lenovo=CTO 주문)
  "bios_version": "2.21.2",
  "power_state":  "On",               // On / Off / PoweringOn / PoweringOff
  "health":       "Critical",         // OK / Warning / Critical
  "oem":          { ... }             // 벤더 전용 확장 — 키가 벤더마다 완전히 다름
}
```

`health` 가 `OK` 가 아닌 이유는 **`data.power.power_supplies[]` / `data.storage` / `data.memory.slots[]`** 등을 차례로 봐야 알 수 있다. BMC 가 rollup 만 보고하고 원인은 직접 찾아야 한다.

### 6.2 `data.memory`

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

**Channel 매핑 (cycle 2026-05-11 field-channel-refinement)**:
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

### 6.3 `data.storage`

스토리지는 다음 하위 list 가 있다.

| 키 | 무엇 | 누가 채우나 |
|---|---|---|
| `physical_disks[]` | 물리 디스크 (모든 컨트롤러 합쳐서 중복 제거) | 모든 채널 |
| `controllers[].drives[]` | 컨트롤러별 드라이브 | Redfish |
| `logical_volumes[]` | RAID 논리 볼륨 | Redfish |
| `filesystems[]` | OS 파일시스템 마운트 | OS-gather |
| `datastores[]` | ESXi 데이터스토어 | ESXi-gather |
| `hbas[]` | FC HBA (+ iSCSI) | 모든 채널 |
| `infiniband[]` | InfiniBand 어댑터 | 모든 채널 (best-effort) |

물리 디스크와 논리 볼륨 사이는 ID 로 묶인다.

```text
physical_disks[*].id  ─┐
                       ├─ logical_volumes[*].member_drive_ids 에서 참조
controllers[*].id  ────┤
                       └─ logical_volumes[*].controller_id 에서 참조
```

#### 6.3.1 `hbas[]` / `infiniband[]` — FC HBA / InfiniBand (cycle 2026-05-29)

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
    { "adapter": "mlx5_0", "port": "1", "node_guid": "0011:...:6677", "port_guid": "...",
      "link_status": "up", "rate": "200 Gb/sec (4X HDR)", "rate_gbps": 200,
      "vendor": "MT4125", "firmware": "20.35.1012", "source": "os" }
  ]
}
```

채널별 수집원 + 한계:

| 채널 | FC HBA 수집원 | InfiniBand 수집원 / 한계 |
|---|---|---|
| Redfish | `Chassis/NetworkAdapters/NetworkDeviceFunctions` (FC=`PortProtocol`/`NetDevFuncType`, **PortType enum 아님**) | `Port.LinkNetworkTechnology`/`NetworkDeviceTechnology`. 주류 BMC(iDRAC/iLO/XCC) 는 add-in IB HCA 거의 미노출 → OS 채널 정본 |
| OS Linux | `/sys/class/fc_host/*` (wwpn/wwnn/driver/firmware) | `/sys/class/infiniband/*` (node_guid/port_guid/rate/fw) — **정본** |
| OS Windows | `Get-InitiatorPort` + `MSFC_*` WMI (FC 만 필터) | `Get-NetAdapter` PhysicalMediaType=InfiniBand. **node_guid 표준 API 부재 → null** |
| ESXi | `vmware_host_vmhba_info` (FC/iSCSI, SAS/RAID 제외) | native IB 미노출 (SR-IOV/passthrough 만) → `nmlx` NIC best-effort 추론 (`note` 포함) |

- `wwpn`/`wwnn`/`link_speed_gbps`/`node_guid` 는 미연결·미노출 시 `null` (정상 — error 아님).
- `port_type` ∈ {`FibreChannel`, `FCoE`, `iSCSI`}. `source` ∈ {`redfish`, `os`, `esxi`}.
- 서브필드 정의는 `schema/field_dictionary.yml` (`storage.hbas[].*` / `storage.infiniband[].*`, Nice).

### 6.4 `data.network`

```json
"network": {
  "interfaces": [
    { "id": "...", "kind": "server_nic", "mac": "...", "speed_mbps": 10240,
      "link_status": "linkup", "addresses": [...] },
    ...
  ],
  "dns_servers":      [],
  "default_gateways": [],
  "summary":          { /* 같은 속도 NIC 묶은 집계 */ }
}
```

`link_status` 값:
- `linkup` / `linkdown` — 정상 보고
- `none` — BMC 가 link 상태 정보 자체를 안 줌 (HPE iLO / Cisco System NIC 등에서 종종 발생)
- `null` — 응답에 필드 자체가 없음

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

---

## 7. 자주 묻는 질문

**Q. `status: success` 인데 `errors[]` 에 항목이 있다. 정상인가?**
정상이다. **수집은 성공했고**, 다만 수집 도중 보인 비정상 신호 (PSU fault / SMART warning 등) 가 errors 에 기록된다. 알람을 errors 만 보고 띄우면 정상 케이스에도 시끄러워진다.

**Q. `vendor` 가 `null` 이면 어떡하나?**
새 펌웨어 / 보지 못한 모델이라 정규화 못 했다는 뜻. `data.hardware.vendor` 에 BMC 원본 값이 들어있으니 거기서 사람이 판단해야 한다. (그리고 `common/vars/vendor_aliases.yml` 에 별칭 추가하면 다음부터는 정규화된다.)

**Q. `hostname` 이 `ip` 와 같은 값이다. 버그인가?**
아니다. DNS 역순회가 안 됐거나 BMC 가 fqdn 을 안 줘서 `ip` 로 fallback 한 **의도된 동작** 이다. 상세 fallback chain 은 8절 참조.

**Q. `correlation.bmc_ip` 와 `correlation.host_ip` 가 같다. 버그인가?**
Redfish 채널은 둘이 같은 게 정상이다 (BMC 를 통해 수집). OS / ESXi 채널은 다를 수 있다 (서비스 IP 와 BMC IP 가 분리되어 있으면).

**Q. `schema_version` 이 바뀔 수 있나?**
바뀐다. 하지만 envelope 13 필드의 의미가 깨지는 변경이면 `"2"` 로 올라가고, 사람이 명시 승인을 해야 한다. 이전 버전 호환은 보장되지 않으니 호출 시 항상 schema_version 을 같이 본다.

---

## 8. hostname fallback chain (의도된 동작 — cycle 2026-05-07 보강)

`envelope.hostname` 은 다음 우선순위로 결정된다 (정본: `common/tasks/normalize/build_output.yml:31-33`):

```text
hostname = system.hostname  OR  system.fqdn  OR  ip_fallback
```

### 우선순위

| 순위 | 후보 | 출처 (3 채널 별) |
|---:|---|---|
| 1 | `data.system.hostname` | OS Linux: `ansible_hostname` / Windows: `inventory_hostname` / Redfish: `Manager.HostName` 또는 `System.HostName` / ESXi: `vSphere.summary.config.name` |
| 2 | `data.system.fqdn` | OS Linux: `ansible_fqdn` (raw fallback: `hostname -f`) / Windows: 같음 / Redfish: 일부 vendor 만 / ESXi: 같음 |
| 3 | `envelope.ip` (fallback) | 호출자가 넘긴 `service_ip` / `bmc_ip` |

### 4 시나리오 별 동작

| 시나리오 | system.hostname | system.fqdn | 결과 envelope.hostname |
|---|---|---|---|
| A 정상 (FQDN 있음) | `null` | `"server01.lab.local"` | `"server01.lab.local"` (fqdn) |
| B 정상 (호스트명만) | `"server01"` | `null` | `"server01"` (hostname 우선) |
| C BMC HostName 미응답 (DMTF spec 권장 동작) | `null` | `null` | `"10.50.11.162"` (ip fallback) |
| D Linux raw fallback (RHEL 8.10 py3.6) | `null` | `"server01.lab.local"` (raw `hostname -f`) | `"server01.lab.local"` |

### 호출자가 hostname/IP 구분이 필요한 경우

- **간단한 방법**: `envelope.hostname == envelope.ip` 비교
  - `True` → ip fallback 발생 (BMC 가 hostname 미응답)
  - `False` → 정상 hostname 또는 fqdn 응답
- **상세 추적**: `ansible-playbook -vvv` 로그에서 `_merged_data.system` raw 값 확인
- **회귀 차단**: `tests/regression/test_cross_channel_consistency.py::test_hostname_never_null` (cycle 2026-05-07 추가) — 모든 baseline 의 hostname 이 non-null 보장

### 왜 ip fallback 이 정상인가 (DMTF spec 근거)

- **Redfish**: BMC 가 `Manager.HostName` 을 응답하지 않는 환경 (DHCP 미사용 / hostname 미설정) 다수 존재. DMTF spec 도 HostName 을 optional 로 정의.
- **ESXi**: vSphere host 가 DNS 에 등록 안 된 환경 다수.
- **Linux/Windows**: ansible_facts 가 hostname/fqdn 둘 다 추출 불가 시 (예: 컨테이너 / minimal 이미지).

`envelope.hostname` 을 항상 non-null 로 보장 (호출자 시스템 파싱 안전성) 위해 ip 로 fallback. 호출자가 IP 인지 hostname 인지 구분이 필요하면 위 비교 방법 사용.

### 알려진 baseline drift

- `cisco_baseline.json` 은 `hostname == ip` (`10.100.15.2`, IP fallback) — `data.system.fqdn` 은 `C220-FCH2116V1V0` 로 non-null 이지만 hostname 해석이 IP 로 폴백된 상태. 후속 작업: lab Cisco UCS 실측 후 hostname/fqdn 해석 재검증 + baseline 갱신.

---

## 9. RMC 멀티-노드 토폴로지 (`data.multi_node`)

> cycle 2026-05-12 (ADR-2026-05-12) 추가. HPE Compute Scale-up Server 3200 / Superdome Flex 처럼 단일 RMC (Rack Management Controller) 가 N개 chassis × N개 nPartition × 다중 Manager 를 통합 노출하는 환경 정식 지원.
>
> cycle 2026-06-09 (ADR-2026-06-09) 확장. CSUS 3200 Redfish 모델 검수 결과 누락분 5종 Additive 추가 — per-partition `boot` (부팅 순서), per-chassis `thermal` (온도/팬), per-manager `log_services` (LogServices), `multi_node.composition` (CompositionService/ResourceBlocks), `multi_node.fabrics` (Fabrics/FlexGrid Switches+Endpoints, NUMAlink). 모두 `data.multi_node` 내부 신 키 (envelope 13 필드 / 기존 9 section path 변경 0).

### 활성 조건

`data.multi_node` 는 adapter `vendor_notes.manager_layout` 정의 vendor 에서만 활성:

| vendor | adapter | manager_layout | 활성 |
|---|---|---|---|
| HPE CSUS 3200 | `hpe_csus_3200.yml` | `rmc_primary` | YES |
| HPE Superdome Flex | `hpe_superdome_flex.yml` | `rmc_primary_ilo_secondary` | YES |
| 기타 13 vendor (HPE iLO 4~7 / Dell / Cisco / Lenovo / Supermicro / Huawei / Inspur / Fujitsu / Quanta) | — | (미정의) | NO — `data.multi_node = null` |

### Envelope shape (Additive only — rule 92 R2 / 96 R1-B)

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
  },
  "diagnosis": {
    "details": {
      "multi_node_layout": "rmc_primary",
      "rmc_activation_check": true
    }
  }
}
```

### 확장 컴포넌트 (cycle 2026-06-09 — ADR-2026-06-09)

CSUS 3200 Redfish 모델 검수 결과 추가된 5종. 모두 `data.multi_node` 내부 (Additive). Redfish 표준 리소스 미노출 시 graceful (boot/thermal=`{}`, log_services=`[]`, composition/fabrics=`null`).

| 키 | 출처 Redfish 리소스 | 필드 | 비고 |
|---|---|---|---|
| `partitions[].boot` | `Systems/{id}.Boot` | `boot_order[]`, `boot_source_override_enabled/target/mode`, `boot_next`, `uefi_target` | nPartition 별 부팅 순서 (설명 모델 요구). 미노출 시 `{}` |
| `chassis[].thermal` | `Chassis/{id}/Thermal` (404 시 `/ThermalSubsystem` DMTF 2020.4 fallback) | `temperatures[]` (name/reading_celsius/health/upper_critical), `fans[]` (name/reading/reading_units/health) | chassis 별 온도/팬. `power` 와 쌍 (설명 모델). 미노출 시 `{}` |
| `managers[].log_services` | `Managers/{id}/LogServices` | `id`, `name`, `overwrite_policy`, `service_enabled`, `log_entry_type`, `date_time` | RMC 의 Services/Logs (설명 모델). 로그 엔트리 자체는 범위 외. 미노출 시 `[]` |
| `composition` | `CompositionService` + `ResourceBlocks` | `enabled`, `state/health`, `resource_block_count`, `resource_blocks[]` (id/types/composition_state/processor_count/memory_count/`chassis[]`/`computer_systems[]`) | nPartition 조합 구조. 각 ResourceBlock ↔ chassis 대응 (설명 모델). ServiceRoot 미노출 시 `null` |
| `fabrics` | `Fabrics` + `Fabrics/{id}` (Switches/Endpoints) | `[]` of {id/fabric_type/health/`switch_count`/`endpoint_count`/`switches[]`/`endpoints[]`} | NUMAlink FlexGrid (Switches+Endpoints, Links/Zones 미사용 — 설명 모델). ServiceRoot 미노출 시 `null` |

> **Lab 부재 주의**: 위 5종은 lab 부재 web sources (DMTF DSP0266 + HPE CSUS 3200 Admin Guide + Superdome Flex 상속) 합성 검증. `fabric_type` 은 DMTF enum 에 NUMAlink 가 없어 placeholder (`PCIe`) — 사이트 실측 시 정정 (NEXT_ACTIONS).

### 호출자 가이드

| 시나리오 | 권장 처리 |
|---|---|
| 기존 호출자 (`data.system` / `data.bmc` 만 사용) | 변경 0 — Partition0 데이터로 동일 동작 |
| 멀티-노드 인식 호출자 | `data.multi_node != null` 확인 후 `partitions[]` / `managers[]` / `chassis[]` 순회 |
| 확장 컴포넌트 인식 호출자 | `multi_node.composition` / `multi_node.fabrics` (null 가드) + `partitions[].boot` / `chassis[].thermal` / `managers[].log_services` 순회 |
| 활성화 미상 진단 | `diagnosis.details.rmc_activation_check == false` 시 사이트 RMC Redfish 서비스 / Subscription 라이선스 확인 (`docs/22_rmc-activation-guide.md`) |

### Lab 부재 한계 (NEXT_ACTIONS C1~C8)

현재 mock fixture 는 sdflexutils + DMTF v1.15 + iLO 5 API ref 합성. ServiceRoot.Product 정확 문자열 / Manager ID 패턴 / Oem.Hpe schema 는 사이트 실측 후 정정 의무.

---

## 10. 더 깊이 보고 싶을 때

| 보고 싶은 것 | 파일 |
|---|---|
| 라인별 한국어 주석 달린 실물 JSON | `schema/output_examples/redfish_dell_idrac10.jsonc` |
| 정상 / 부분 / 실패 / 미지원 4가지 케이스 JSON | `schema/examples/redfish_*.json`, `os_partial.json` |
| 벤더별 회귀 기준선 JSON | `schema/baseline_v1/{vendor}_baseline.json` |
| 섹션 정의 원본 | `schema/sections.yml` |
| 필드 사전 원본 | `schema/field_dictionary.yml` |
| 출력 조립 코드 | `common/tasks/normalize/build_output.yml` |
| 채널 처리 과정 | `docs/06_gather-structure.md`, `docs/07_normalize-flow.md` |
| 진단 단계 상세 | `docs/11_precheck-module.md` |
| 어댑터 매칭 규칙 | `docs/10_adapter-system.md` |
