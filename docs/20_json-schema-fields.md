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
    "system":   { "fqdn": "LENOVO01", ... }
  },
  "schema_version": "1"
}
```

> cycle 2026-06-15 (field_dictionary 134 entries): `firmware[].category` (bios/cpld/tpm/drive/
> backplane/nic/storage_controller/psu/... id·name 추론) + `firmware[].pending` (적용 보류) 정식 등록.
> `cpu.architecture` 는 redfish 채널도 emit (channel=[redfish,os,esxi]).

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
| `hostname` | 문자열\|null | 풀어낸 호스트명. `system.hostname → system.fqdn → null` (IP fallback 안 함, 2026-06-16). 상세: 8절 |
| `vendor` | `dell` / `hp` / `hpCsus` / `lenovo` / `supermicro` / `cisco` / `null` | 호출자 노출 표시값. 내부 canonical(`hpe`)을 `vendor_output_display`/`adapter_output_display`(vendor_aliases.yml)로 매핑. HPE 계열→`hp`, HPE Compute Scale-up 패밀리(CSUS 3200 + Superdome Flex)→`hpCsus`(camelCase 예외, 2026-06-04 ADR). 대부분 소문자 한 단어 |

### 그룹 B — 결과 (2개)

| 키 | 무슨 값 | 의미 |
|---|---|---|
| `status` | `success` / `partial` / `failed` | **수집 결과**. 장비 상태 아님 |
| `sections` | 섹션 11개 각각 `success` / `failed` / `not_supported` | 섹션별 결과 |

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

## 3. 섹션 11개 — 어떤 채널이 뭘 채우나

JSON 의 `sections` 와 `data` 는 같은 11개 키를 갖는다. 각 채널이 채울 수 있는 영역이 다르다.

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
| `thermal` | 온도 센서 / 팬 (Chassis/Thermal) | | | O |

(X) = `not_supported`. 그 채널 특성상 원래 못 가져오는 영역이다. 수집 실패와 다른 의미다.
cycle 2026-08-03: `not_supported` 판정 신호에 **HTTP 400** 추가 (기존 404 만). 표준상 미구현 리소스는 404 지만
실제 벤더 BMC 는 미구현/미인가 리소스에 400 을 주기도 한다(실측: 사이트 Dell iDRAC 8대 `NetworkAdapters`).
오분류를 막기 위해 **컬렉션 GET 자체 실패 + 결과가 완전히 빈 경우에만** 적용하고, 부분 수집은 그대로 `failed` 로 둔다.
cycle 2026-06-15: `thermal` 을 `sections` 맵에 정식 배선 (이전엔 `data.thermal` 만 채워지고 `sections.thermal` 누락 — Track4 미완. 이제 redfish 는 수집 성공 시 `success`, os/esxi 는 `not_supported`).

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

> **보조(OEM) 단계 실패는 D 가 아니다 (2026-06-16, redfish).** vendor OEM 수집/정규화는 표준 섹션 수집 **뒤**에 도는 보조 단계다.
> 여기서 예외가 나도 표준 섹션은 그대로 `success` 로 유지되고, OEM 실패는 `errors[]` 에 `section: "oem"` 경고로만 남는다
> (→ 시나리오 B, 또는 일부 표준 섹션이 실패했으면 C). 즉 OEM 한 단계 실패가 전체를 `failed` 로 만들지 않는다.
> (`redfish-gather/site.yml` 의 OEM local block/rescue — 과거엔 단일 top-level rescue 로 cascade 되어 표준 섹션까지 전부 `failed` 였음.)

> **보조 수집 실패도 C 가 아니다 (2026-08-03, redfish `network`).** `network` 섹션은 두 갈래로 모은다.
> **주** = 호스트 NIC/IP(`Systems/{id}/EthernetInterfaces`) → `data.network.interfaces[]` 등,
> **보조** = NIC 카드 모델·펌웨어(`Chassis/{id}/NetworkAdapters`) → `data.network.adapters[]` / `ports[]`.
> `sections.network` 는 **주 수집 결과만으로** 정해진다. 보조가 실패해도 주 수집이 됐으면 `success` 이고,
> 사유는 `errors[]` 에 `section: "network_adapters"` 로 남는다 (→ 시나리오 B).
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
      "link_status": "up", "addresses": [...] },
    ...
  ],
  "dns_servers":      [],
  "default_gateways": [],
  "bonds":            [],   // Linux 본딩 (cycle 2026-06-15) — bond 없으면 빈 []
  "bridges":          [],   // Linux 브리지 — 없으면 빈 []
  "teams":            [],   // Windows 티밍(LBFO/SET) — 없으면 빈 []
  "summary":          { /* 같은 속도 NIC 묶은 집계 (slave NIC 미포함 — 기존과 동일) */ }
}
```

`link_status` 값 (cycle 2026-06-14 전 채널 통일 canonical — 이전 linkup/linkdown/none 폐기):
- `up` / `down` — 링크 활성 / 비활성(미연결·disabled·offline 포함)
- `unknown` — 상태 미제공/판별 불가 (HPE iLO / Cisco System NIC 등에서 종종 발생)
- `null` — 응답에 필드 자체가 없음

#### 6.4.1 본딩/티밍 토폴로지 (cycle 2026-06-15 — OS 채널, Additive)

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

### 6.6 `data.bmc` (Redfish 전용)

> cycle 2026-06-14 (DELL R740 BMC-1): bmc 하위 필드가 field_dictionary 에 문서화됨 (이전엔 `bmc.ip` 만).

```json
"bmc": {
  "firmware_version": "7.00.00.184",   // Manager.FirmwareVersion (FirmwareInventory 아님 — 더 권위)
  "model": "14G Monolithic",           // Manager.Model
  "name": "iDRAC",                      // 벤더 표시 라벨 (iDRAC/iLO/XCC/CIMC)
  "health": "OK",                       // Manager.Status.Health (BMC 자체 — 장비 health 아님)
  "ip": "10.x.x.x",                     // BMC 관리 NIC (Manager 자체 EthernetInterface)
  "mac_address": "f4:02:70:...",        //  "  서버 OS NIC 아님
  "dns_name": "iDRAC-<ServiceTag>",
  "uuid": "3330...",                    // Manager UUID — System UUID(hardware.uuid)와 다름!
  "datetime": "2026-06-12T01:42:11-05:00", "datetime_offset": "-05:00",
  "oem": { "idrac_url": "https://...", "idrac_ipmi_version": "2.0", ... }
}
```

주의: `bmc.uuid` 는 **BMC 식별자**(Manager UUID)이고 `hardware.uuid` 는 **서버 식별자**(System UUID)다.
`bmc.firmware_version` 은 Manager 가 직접 보고하는 BMC 펌웨어로, FirmwareInventory 의 BMC 항목(때로 stale)이 아니다.

### 6.7 `data.thermal` (Redfish 전용)

> cycle 2026-06-14 (Track 4): 단일노드 thermal 수집 — 이전엔 multi_node(CSUS/Superdome) 경로만 수집했음.
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
> - cycle 2026-05-07: hostname 미해석 시 `ip` fallback.
> - 2026-06-16 (사용자 지시): **IP fallback 폐지** ("없는 건 없는 것"). 단 IP 와 달리 장비에
>   고정된 실명인 **BMC 관리 호스트명**(`Manager.NetworkProtocol.HostName/FQDN` — iLO/XCC/RMC
>   이름)은 System.HostName 부재 시 fallback 허용. BMC 공장기본명(`ILOSGHD3KHHRP` 등)이 섞일 수
>   있어 `hostname_source` 로 출처를 명시 — 호출자가 "OS 호스트명 vs BMC 대체값"을 구분.

### 우선순위

| 순위 | 후보 | source | 출처 (채널/벤더) |
|---:|---|---|---|
| 1 | `data.system.hostname` | system | OS hostname / Redfish System.HostName / ESXi config.name |
| 2 | `data.system.fqdn` | system | OS fqdn(`hostname -f`) / Redfish System.HostName(정규화) |
| 3 | `data.bmc.network_hostname` | bmc | Manager.NetworkProtocol.HostName/FQDN (**redfish 전용**) |
| 4 | (없음) | none | 전부 비면 `null` — **IP fallback 안 함** |

### 시나리오 (실측 2026-06-16)

| 장비 | System.HostName | BMC NetworkProtocol | hostname | source |
|---|---|---|---|---|
| Dell R740 | `DELL01` | `iDRAC-J0KV603` | `DELL01` | system |
| HPE DL380 | `""` | `ILOSGHD3KHHRP` | `ILOSGHD3KHHRP` | bmc |
| Lenovo SR650 | (필드없음) | `XCC-7DGD-J902E57T` | `XCC-7DGD-J902E57T` | bmc |
| CSUS node01 | `null` | `RMC7CA62A413692` | `RMC7CA62A413692` | bmc |
| CSUS node03 | `m10mesdb11` | `M10MESDB11-RMC` | `m10mesdb11` | system |
| Cisco C220 | `C220-FCH2116V1V0` | `null` | `C220-FCH2116V1V0` | system |
| (System없음+BMC null) | `null` | `null` | **`null`** | none |

### 벤더별 BMC fallback 동작 (중요 — 만능 아님)

`Manager.NetworkProtocol.HostName` 은 DMTF 표준 optional 속성이라 벤더/세대별 populate 여부가 다르다:
- **populate (bmc fallback 동작)**: Dell iDRAC9 / HPE iLO7·RMC / Lenovo XCC3 — 실측.
- **null (bmc fallback 도 null)**: Cisco CIMC — 실측(reference crawl). System.HostName 으로만 채워짐.
- **lab 부재(미확인)**: Supermicro / Huawei / Inspur / Fujitsu / Quanta + 구세대(iDRAC8 / iLO4~6 /
  XCC2 등) — DMTF 표준상 가능하나 실측 미확인. 매트릭스:
  `tests/evidence/2026-06-16-hostname-source-matrix.md` (lab 도입 후 검증 — NEXT_ACTIONS).

구현은 **graceful**: 각 순위가 비면 다음으로, 전부 비면 null → 어느 벤더/세대든 안전.

### 호출자 주의

- `hostname` 은 nullable. `hostname_source == 'bmc'` 면 그 값은 **서버 OS 호스트명이 아니라
  관리 컨트롤러(BMC) 이름** — 식별엔 쓰되 OS hostname 으로 단정 금지.
- `hostname == ip` 는 금지(옛 ip-fallback 잔재). 회귀:
  `test_cross_channel_consistency.py::test_hostname_not_ip_fallback` +
  `test_hostname_fallback_chain.py` (체인 정본 + IP 미참조) +
  `test_real_capture_replay.py::test_bmc_network_hostname_collected`.

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

현재 mock fixture 는 sdflexutils + DMTF v1.15 + iLO 5 API ref 합성. ServiceRoot.Product 정확 문자열 / Manager ID 패턴 / Oem.Hpe schema 는 사이트 실측 후 정정 의무 (`docs/ai/NEXT_ACTIONS.md` C1~C8 참조).

---

## 10. 더 깊이 보고 싶을 때

| 보고 싶은 것 | 파일 |
|---|---|
| 라인별 한국어 주석 달린 실물 JSON | `schema/output_examples/redfish_dell_idrac10.jsonc` |
| 정상 / 부분 / 실패 / 미지원 4가지 케이스 JSON | `schema/examples/redfish_*.json`, `os_partial.json` |
| 벤더별 회귀 기준선 JSON | `schema/baseline_v1/{vendor}_baseline.json` |
| 섹션 정의 원본 | `schema/sections.yml` |
| 필드 사전 원본 | `schema/field_dictionary.yml` |
| **필드 × baseline 사용 실태 매트릭스 (4 상태)** | **`docs/ai/catalogs/FIELD_USAGE_MATRIX.md` (cycle 2026-05-11 신규, 측정 대상 #13)** |
| 출력 조립 코드 | `common/tasks/normalize/build_output.yml` |
| 채널 처리 과정 | `docs/06_gather-structure.md`, `docs/07_normalize-flow.md` |
| 진단 단계 상세 | `docs/11_precheck-module.md` |
| 어댑터 매칭 규칙 | `docs/10_adapter-system.md` |
