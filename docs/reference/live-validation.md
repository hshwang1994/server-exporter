# Redfish 실장비 API 검증 결과

> 이 문서는 실제 BMC 장비를 대상으로 Redfish API 호출을 검증한 결과를 누적 기록한다.
> 새 펌웨어 / 새 모델이 들어왔을 때 "어떤 endpoint 가 응답하는지", "OEM 영역이 어떻게 다른지" 를 비교하는 데 참고한다.
>
> 회귀 검증 단위(Round)별로 결과를 추가하며 검증 시점의 정확한 펌웨어 버전과 응답 차이를 보존한다.
> 펌웨어 업그레이드 후 응답이 달라지면 이 문서가 비교 기준이 된다.

> 검증일: 2026-03-18 | 검증 방식: 직접 HTTPS 호출 (curl/Python urllib)

> [!NOTE]
> 이 문서를 읽는 법: 1~14절은 2026-03-18 3대 실장비 검증 스냅샷이다. 그 안의 "수정 필요" 표시는 검증 시점 기준이며 이후 작업에서 해결된 항목이 있다 (해결 내역은 `docs/reference/decision-log.md`).
> 그 뒤의 절은 최근 실장비 명부 실행 기록이다. 현재 adapter/vendor 전체 목록은 `adapters/redfish/` 디렉터리와 `docs/reference/compatibility-matrix.md` 를 본다.

## 1. 대상 장비

| 벤더 | IP | 모델 | BMC | Redfish Version |
|------|----|------|-----|-----------------|
| Lenovo | 10.50.11.232 | ThinkSystem SR650 V2 | XCC (FW: 5.70) | 1.15.0 |
| HPE | 10.50.11.231 | ProLiant DL380 Gen11 | iLO 6 (FW: 1.73) | 1.20.0 |
| Dell | 10.50.11.162 | PowerEdge R740 | iDRAC 9 (FW: 4.00) | 1.6.0 |

## 2. 연결 검증 결과

| 항목 | Lenovo | HPE | Dell |
|------|--------|-----|------|
| HTTPS 연결 | OK | OK | OK |
| Basic Auth | OK | OK | OK (Python urllib만 — curl bash 이스케이핑 주의) |
| Self-signed cert | 필요 (verify=False) | 필요 | 필요 |
| Service Root 인증 | 필요 | 필요 | 불필요 (공개) |

### Dell 인증 주의사항
- 비밀번호에 `!` 포함 → bash curl에서 이스케이핑 문제 발생
- Python urllib.request + base64 수동 인코딩으로 해결
- `redfish_gather.py`는 Python이므로 문제 없음

## 3. URI 패턴 비교 (확정)

| 리소스 | Lenovo | HPE | Dell |
|--------|--------|-----|------|
| System | /redfish/v1/Systems/1 | /redfish/v1/Systems/1 | /redfish/v1/Systems/System.Embedded.1 |
| Manager | /redfish/v1/Managers/1 | /redfish/v1/Managers/1 | /redfish/v1/Managers/iDRAC.Embedded.1 |
| Chassis (주) | /redfish/v1/Chassis/1 | /redfish/v1/Chassis/1 | /redfish/v1/Chassis/System.Embedded.1 |
| Chassis (부) | /redfish/v1/Chassis/3 | /redfish/v1/Chassis/DE00C000 | /redfish/v1/Chassis/Enclosure.Internal.0-1:RAID.Slot.6-1 |

**확정**: 코드가 Systems/Managers/Chassis 컬렉션 Members[0]을 동적으로 가져오므로 하드코딩된 URI 패턴 불필요. `detect_vendor()` 로직은 3사 모두에서 동작을 확인했다.

## 4. 엔드포인트별 검증 결과

### 4-1. Service Root (`/redfish/v1/`)

| 필드 | Lenovo | HPE | Dell | 코드 사용 |
|------|--------|-----|------|----------|
| Vendor | "Lenovo" | "HPE" | MISSING | 미사용 (Manufacturer 기반) |
| RedfishVersion | 1.15.0 | 1.20.0 | 1.6.0 | 미사용 |
| UUID | OK | OK | MISSING | 미사용 |
| Systems/@odata.id | OK | OK | OK | detect_vendor에서 사용 |
| Managers/@odata.id | OK | OK | OK | detect_vendor에서 사용 |
| Chassis/@odata.id | OK | OK | OK | gather_power에서 사용 |
| Oem 키 | None | {Hpe} | {Dell} | 미사용 (System 레벨에서 사용) |
| UpdateService | OK | OK | OK | gather_firmware에서 사용 |

### 4-2. System (`/redfish/v1/Systems/{id}`)

| 필드 | Lenovo | HPE | Dell | 코드 추출 키 | 상태 |
|------|--------|-----|------|-------------|------|
| Manufacturer | "Lenovo" | "HPE" | "Dell Inc." | `Manufacturer` | OK — 3사 모두 존재 |
| Model | "ThinkSystem SR650 V2" | "ProLiant DL380 Gen11" | "PowerEdge R740" | `Model` | OK |
| 대표 시리얼 | "J30AF7LC" | "SGH504HNZK" | "2BJ8033" | Lenovo/HPE=`SerialNumber` / Dell=`ServiceRoot.Oem.Dell.ServiceTag` (2026-08-11 교정) | OK |
| SKU | "7Z73CTO1WW" | "P52534-B21" | "2BJ8033" | `SKU` | OK |
| UUID | OK | OK | OK | `UUID` | OK |
| HostName | "XCC-7Z73-J30AF7LC" | "" (빈 문자열) | "LENOVO01" | `HostName` | **주의**: HPE는 빈 문자열 |
| PowerState | "On" | "On" | "On" | `PowerState` | OK |
| Status.Health | "Critical" | "Warning" | "Critical" | `Status.Health` | OK |
| Status.State | "Enabled" | "Enabled" | "Enabled" | `Status.State` | OK |
| IndicatorLED | "Off" | MISSING | "Off" | `IndicatorLED` | **주의**: HPE Gen11은 미제공 |
| BiosVersion | "AFE136D" | "U54 v2.16..." | "2.21.2" | `BiosVersion` | OK |
| ProcessorSummary.Count | 2 | 2 | 2 | `ProcessorSummary.Count` | OK |
| ProcessorSummary.Model | OK | OK | OK | `ProcessorSummary.Model` | OK |
| ProcessorSummary.Status.Health | "OK" | MISSING | "OK" | `ProcessorSummary.Status.Health` | **주의**: HPE 미제공 |
| MemorySummary.TotalSystemMemoryGiB | 512 | 512 | 640 | `MemorySummary.TotalSystemMemoryGiB` | OK |
| MemorySummary.Status.Health | "OK" | MISSING | "OK" | `MemorySummary.Status.Health` | **주의**: HPE는 HealthRollup만 제공 |

#### OEM 확장 (System 레벨)

| 벤더 | Oem 최상위 키 | 코드 추출 | 실제 존재 |
|------|--------------|----------|----------|
| Lenovo | `Oem.Lenovo` | `ProductName` | **확인 필요** — 실제 sub-keys에 ProductName 직접 미확인 |
| HPE | `Oem.Hpe` | `PostState`, `ServerSignature` | Oem.Hpe 존재, 내부 구조 확인 필요 |
| Dell | `Oem.Dell.DellSystem` | `LifecycleControllerVersion` | Oem.Dell 존재, DellSystem sub-key 확인 필요 |

### 4-3. Manager (BMC) (`/redfish/v1/Managers/{id}`)

| 필드 | Lenovo | HPE | Dell | 코드 추출 키 |
|------|--------|-----|------|-------------|
| FirmwareVersion | "AFBT58B 5.70 2025-08-11" | "iLO 6 v1.73" | "4.00.00.00" | OK |
| Model | "Lenovo XClarity Controller" | "iLO 6" | "14G Monolithic" | OK |
| ManagerType | "BMC" | "BMC" | "BMC" | OK |
| Status.Health | **MISSING** | "OK" | "OK" | **Lenovo 누락** |
| UUID | OK | OK | OK | 미사용 |

### 4-4. Processors (`/redfish/v1/Systems/{id}/Processors/{pid}`)

| 필드 | Lenovo | HPE | Dell | 코드 추출 |
|------|--------|-----|------|----------|
| Model | OK | OK | OK | OK |
| Manufacturer | "Intel(R) Corporation" | "Intel(R) Corporation" | "Intel" | OK |
| Socket | "CPU 1" | "Proc 1" | "CPU.Socket.2" | OK — 형식 다르지만 문자열로 저장 |
| TotalCores | 32 | 32 | 12 | OK |
| TotalThreads | 64 | 64 | 12 | OK |
| MaxSpeedMHz | 3200 | 4000 | 4000 | OK |
| Status.Health | "OK" | "OK" | "OK" | OK |
| Status.State | "Enabled" | "Enabled" | "Enabled" | OK — Absent 필터링 동작 |

### 4-5. Memory (`/redfish/v1/Systems/{id}/Memory/{mid}`)

| 필드 | Lenovo | HPE | Dell | 코드 추출 |
|------|--------|-----|------|----------|
| CapacityMiB | 32768 | 32768 | 32768 | OK |
| MemoryDeviceType | "DDR4" | "DDR5" | "DDR4" | OK |
| OperatingSpeedMhz | 3200 | 4400 | 2400 | OK |
| Manufacturer | OK | OK | OK | OK |
| SerialNumber | OK | OK | OK | OK |
| PartNumber | OK | OK | OK | OK |
| Status.Health | "OK" | "OK" | "OK" | OK |
| Status.State | "Enabled" | "Enabled" | "Enabled" | OK — Absent 필터링 동작 |

**메모리 요약**: Lenovo 16/32 populated (512GB), HPE 16/32 (512GB), Dell 20/20 (640GB)

### 4-6. Storage (`/redfish/v1/Systems/{id}/Storage/{sid}`)

| 항목 | Lenovo | HPE | Dell |
|------|--------|-----|------|
| Storage 컬렉션 | 200 OK (1 member) | 200 OK (1 member) | 200 OK (4 members) |
| SimpleStorage | 404 | 404 | 200 OK |
| StorageControllers (inline) | 1개 | **MISSING** (Controllers 링크) | 1개 |
| Drives 링크 | 4개 | 8개 | 6개 (RAID) |

#### 발견사항: HPE Storage Controllers

HPE Gen11은 `StorageControllers` 인라인 배열이 아닌 `Controllers` 서브 링크를 사용:
- `/redfish/v1/Systems/1/Storage/DE00C000/Controllers` → 200 OK
- 코드(`gather_storage`)는 `StorageControllers` 배열만 처리 → **HPE에서 컨트롤러 정보 누락**
- **수정 필요**: Controllers 링크 fallback 추가

#### Drive 필드 매핑

| 필드 | Lenovo | HPE | Dell | 코드 추출 |
|------|--------|-----|------|----------|
| Name | OK | OK | OK | OK |
| Model | OK | OK | OK | OK |
| SerialNumber | OK | OK | OK | OK |
| Manufacturer | "Samsung" | **MISSING** | "DELL" | **HPE 누락** |
| MediaType | "SSD" | "SSD" | "SSD" | OK |
| Protocol | "SATA" | "SATA" | "SATA" | OK |
| CapacityBytes | OK | OK | OK | OK |
| Status.Health | "OK" | "OK" | **MISSING** | **Dell Drive Health 누락** |

### 4-7. Network (`/redfish/v1/Systems/{id}/EthernetInterfaces/{eid}`)

| 필드 | Lenovo | HPE | Dell | 코드 추출 |
|------|--------|-----|------|----------|
| MACAddress | OK | OK | OK | OK |
| SpeedMbps | 100 | **MISSING** | 0 | **HPE 누락**, Dell 0 (link down) |
| LinkStatus | "LinkUp" | **MISSING** | "LinkDown" | **HPE 누락** |
| Status.Health | "OK" | **MISSING** | "OK" | **HPE 누락** |
| IPv4Addresses | [0 items] | [0 items] | [0 items] | OK — 호스트 NIC에 IP 없는 것은 정상 |

**참고**: HPE EthernetInterfaces는 최소한의 필드만 제공. SpeedMbps, LinkStatus, Status 모두 미제공.

### 4-8. Firmware (`/redfish/v1/UpdateService/FirmwareInventory/{fid}`)

| 필드 | Lenovo | HPE | Dell | 코드 추출 |
|------|--------|-----|------|----------|
| Name | OK | OK | OK | OK |
| Version | OK | OK | OK | OK |
| Updateable | OK | OK | OK | OK |
| SoftwareId | OK | **MISSING** | OK | **HPE 미제공** → `fw_id` fallback |
| 항목 수 | 17개 | 28개 | 36개 | OK |

### 4-9. Power (`/redfish/v1/Chassis/{id}/Power`)

| 항목 | Lenovo | HPE | Dell |
|------|--------|-----|------|
| PowerControl 수 | 3 | 1 | 1 |
| PowerConsumedWatts | 389W | 206W | 261W |
| PowerCapacityWatts | 750W | 800W | 806W |
| PowerSupplies 수 | 2 | 2 | 2 |
| PSU Name | OK | OK | OK |
| PSU Model | OK | OK | OK |
| PSU Serial | OK | OK | OK |
| PSU FirmwareVersion | OK | OK | OK |
| PSU Health | "Critical" | "Critical" | "Critical" |

### 4-10. Thermal (`/redfish/v1/Chassis/{id}/Thermal`)

| 항목 | Lenovo | HPE | Dell |
|------|--------|-----|------|
| Temperatures 수 | 40 | 46 | 4 |
| Fans 수 | 6 | 6 | 6 |

**참고**: 이 검증 시점에 코드는 Thermal을 수집하지 않는다. 향후 추가 고려.

## 5. Vendor Detection 검증

| 판별 기준 | Lenovo | HPE | Dell |
|-----------|--------|-----|------|
| ServiceRoot.Vendor | "Lenovo" | "HPE" | MISSING |
| System.Manufacturer | "Lenovo" | "HPE" | "Dell Inc." |
| Oem 키 (ServiceRoot) | 없음 | {Hpe} | {Dell} |
| Oem 키 (System) | {Lenovo} | {Hpe} | {Dell} |

**코드 검증**: `detect_vendor()`는 `System.Manufacturer`를 소문자로 변환 후 `_normalize_vendor_from_aliases()`로 매핑.
- "lenovo" → "lenovo"
- "hpe" → "hpe"
- "dell inc." → "dell" (내장맵에 "dell inc." 항목 있음)

**확정**: 1차 기준 = `System.Manufacturer` (3사 모두 동작), 2차 = ServiceRoot.Vendor (Dell 미제공), 3차 = Oem 키

## 6. Negative Test 결과

| 경로 | Lenovo | HPE | Dell |
|------|--------|-----|------|
| /redfish/v1/Systems/NONEXISTENT | 404 | 404 | 404 |
| /redfish/v1/Chassis/BOGUS/Power | 404 | 404 | 404 |
| SimpleStorage (Lenovo) | 404 | 404 | 200 (Dell만 지원) |
| PowerSubsystem (Dell) | — | — | 404 (구형 iDRAC) |
| ThermalSubsystem (Dell) | — | — | 404 |

## 7. Minimum Viable Gather 정의 (확정)

### Success 기준 (최소 4개 section 성공)
- system (필수): Manufacturer, Model, Serial 최소 확보
- bmc (필수): FirmwareVersion 확보
- processors: 최소 1개 CPU 정보
- memory: total_mib 값 존재

### Partial 기준 (1~3개 section 성공)
- system만 성공해도 partial 처리 (나머지 section 에러)

### Failed 기준
- system_uri 자체를 얻지 못한 경우 (ServiceRoot or Systems 컬렉션 실패)

## 8. OEM 사용 기준 (확정)

### 표준 Redfish만으로 충분한 항목
- System: Manufacturer, Model, Serial, UUID, HostName, PowerState, BiosVersion
- BMC: FirmwareVersion, Model, ManagerType
- Processors: 전체 필드
- Memory: 전체 필드
- Storage: Drives 전체, StorageControllers (Dell/Lenovo)
- Network: MACAddress, IPv4 (HPE는 Speed/LinkStatus 미제공이지만 OEM으로도 해결 불가)
- Firmware: Name, Version, Updateable
- Power: PowerSupplies 전체

### OEM 보강이 필요한 항목
- HPE Storage Controllers: `Controllers` 서브링크 fallback 필요 (표준 Redfish 1.13+ 스펙)
- Dell System OEM: `Oem.Dell.DellSystem.LifecycleControllerVersion` (선택적)
- HPE System OEM: `Oem.Hpe.PostState` (선택적)

### OEM 있지만 표준으로 충분한 항목
- Lenovo `Oem.Lenovo.ProductName` → `System.Model`로 대체 가능
- HPE `ServiceRoot.Oem.Hpe.Manager[0].ManagerFirmwareVersion` → `Managers/{id}.FirmwareVersion`으로 대체

## 9. 수집 가능 여부 판단

> 검증 기준 장비에서 확인된 Redfish Version 범위: 1.6.0 (Dell) ~ 1.20.0 (HPE).
> 이 범위는 지원 범위가 아니라, 검증 시점에 실장비에서 확인된 값이다.

| 항목 | 상태 | 근거 |
|------|------|------|
| vendor detect | 가능 | Manufacturer 기반 — 3사 모두 동작 |
| model detect | 가능 | System.Model — 3사 모두 동작 |
| firmware detect | 가능 | Manager.FirmwareVersion — 3사 모두 동작 |
| cpu | 가능 | Processors 컬렉션 — 3사 모두 동작 |
| memory | 가능 | Memory 컬렉션 — 3사 모두 동작 |
| storage.controllers | 조건부 | Lenovo/Dell: StorageControllers 인라인. HPE: Controllers 링크 필요 |
| storage.physical_disks | 가능 | Drives — 3사 모두 동작 |
| network.interfaces | 가능 | EthernetInterfaces — 3사 모두 동작 (HPE는 필드 최소) |
| network.default_gateways | 불가 | Redfish EthernetInterfaces는 호스트 NIC. 게이트웨이 = OS 레벨 정보 |
| firmware inventory | 가능 | FirmwareInventory — 3사 모두 동작 |
| power | 가능 | Power — 3사 모두 동작 |
| thermal | 가능 (미구현) | Thermal 엔드포인트 존재하나 코드 미수집 |
| bmc/system | 가능 | Managers — 3사 모두 동작 |

## 10. Collection 순서 검증

코드 순서 (검증 시점 기준):
```text
detect_vendor → gather_system → gather_bmc → gather_processors →
gather_memory → gather_storage → gather_network → gather_firmware → gather_power
```

**검증 결과**: detect_vendor() 단계에서 system_uri와 manager_uri를 함께 확보하므로 이후 수집 단계의 중복 조회를 줄일 수 있다.

**개선 제안**: gather_power()가 ServiceRoot를 다시 조회하여 Chassis URI를 얻는데, detect_vendor에서 이미
ServiceRoot를 조회했으므로 chassis_uri를 함께 반환하면 HTTP 호출 1회 절약 가능.

## 11. 코드 기준 Endpoint Inventory (20개 고유 패턴)

| # | Endpoint Path Pattern | 카테고리 | 호출 함수 | 필수/선택 |
|---|----------------------|---------|----------|----------|
| 1 | `/redfish/v1/` | ServiceRoot | detect_vendor, gather_power | 필수 |
| 2 | `/redfish/v1/Systems` | System collection | detect_vendor | 필수 |
| 3 | `/redfish/v1/Systems/{id}` | System instance | detect_vendor, gather_system | 필수 |
| 4 | `/redfish/v1/Managers` | Manager collection | detect_vendor | 선택 |
| 5 | `/redfish/v1/Managers/{id}` | Manager instance | gather_bmc | 필수 |
| 6 | `/redfish/v1/Systems/{id}/Processors` | CPU collection | gather_processors | 필수 |
| 7 | `/redfish/v1/Systems/{id}/Processors/{pid}` | CPU instance | gather_processors | 필수 |
| 8 | `/redfish/v1/Systems/{id}/Memory` | Memory collection | gather_memory | 필수 |
| 9 | `/redfish/v1/Systems/{id}/Memory/{mid}` | Memory instance | gather_memory | 필수 |
| 10 | `/redfish/v1/Systems/{id}/Storage` | Storage collection | gather_storage | 필수(주) |
| 11 | `/redfish/v1/Systems/{id}/Storage/{sid}` | Storage controller | gather_storage | 필수 |
| 12 | `/redfish/v1/Systems/{id}/Storage/.../Drives/{did}` | Drive instance | gather_storage | 필수 |
| 13 | `/redfish/v1/Systems/{id}/SimpleStorage` | Simple storage collection | gather_storage | Fallback |
| 14 | `/redfish/v1/Systems/{id}/SimpleStorage/{ssid}` | Simple storage instance | gather_storage | Fallback |
| 15 | `/redfish/v1/Systems/{id}/EthernetInterfaces` | NIC collection | gather_network | 필수 |
| 16 | `/redfish/v1/Systems/{id}/EthernetInterfaces/{eid}` | NIC instance | gather_network | 필수 |
| 17 | `/redfish/v1/UpdateService/FirmwareInventory` | Firmware collection | gather_firmware | 선택 |
| 18 | `/redfish/v1/UpdateService/FirmwareInventory/{fid}` | Firmware instance | gather_firmware | 조건부 |
| 19 | `/redfish/v1/Chassis` | Chassis collection | gather_power | 선택 |
| 20 | `/redfish/v1/Chassis/{cid}/Power` | Power/PSU | gather_power | 선택 |

### 실장비 검증 커버리지: 20/20 (100%)

모든 코드 사용 엔드포인트가 검증 기준 3대 장비에서 검증됐다.

## 12. Adapter Inventory (검증 시점 발췌 — 현재 전체 31개)

> [!NOTE]
> 아래 표는 2026-03-18 검증 시점의 주요 adapter 발췌다. 이후 adapter 가 추가돼 현재 `adapters/redfish/` 에는 31개가 있다 (dell_idrac10, hpe_ilo6/ilo7, lenovo_xcc3, supermicro_x10~x14, cisco 3종, HPE Superdome/CSUS, lab 부재 4벤더 포함). 현재 전체 목록과 priority 는 `adapters/redfish/` 디렉터리에서 확인한다.

| adapter_id | Priority | Match 조건 | 지원 섹션 |
|------------|----------|-----------|----------|
| redfish_generic | 0 | any (fallback) | 9개 전체 |
| redfish_dell_idrac | 10 | vendor: Dell | 9개 전체 |
| redfish_dell_idrac8 | 50 | Dell + firmware iDRAC 8 | 9개 (power FB — 2026-05-06 M-D3) |
| redfish_dell_idrac9 | 100 | Dell + firmware iDRAC 9 | 9개 전체 |
| redfish_hpe_ilo | 10 | vendor: HPE | 9개 전체 |
| redfish_hpe_ilo4 | 50 | HPE + firmware iLO 4 | 9개 (storage/power FB — 2026-05-06 M-D3) |
| redfish_hpe_ilo5 | 100 | HPE + firmware iLO 5 | 9개 전체 |
| redfish_lenovo_imm2 | 50 | Lenovo + firmware IMM2 | 9개 (storage/power FB — 2026-05-06 M-D3) |
| redfish_lenovo_xcc | 100 | Lenovo + firmware XCC | 9개 전체 |
| redfish_supermicro_bmc | 10 | vendor: Supermicro | 9개 전체 |
| redfish_supermicro_x9 | 50 | Supermicro + model X9 | 6개 |
| redfish_supermicro_x11 | 100 | Supermicro + model X11 | 9개 전체 |

### 실장비 Adapter 매칭 예상

| 장비 | BMC FW | 매칭 Adapter | Priority |
|------|--------|-------------|----------|
| Lenovo SR650 V2 | "AFBT58B 5.70 2025-08-11" | **redfish_lenovo_xcc** (XCC 패턴 매칭) | 100 |
| HPE DL380 Gen11 | "iLO 6 v1.73" | **redfish_hpe_ilo6** (iLO 6 전용 adapter) | 100 |
| Dell R740 | "4.00.00.00" | **redfish_dell_idrac9** (^[4-7]\. 패턴 매칭) | 100 |

> 해결됨: hpe_ilo6.yml adapter가 추가되었다 (docs/reference/decision-log.md P0-3).

## 13. Payload 심층 분석 — 벤더 간 차이점 10건

실장비 JSON fixture 심층 비교에서 발견한 차이점 중 정규화 코드에 직접 영향을 주는 항목:

| # | 항목 | Lenovo | HPE | Dell | 코드 영향 |
|---|------|--------|-----|------|----------|
| 1 | Resource ID 패턴 | `1` | `1` | `System.Embedded.1` | 동적 취득으로 문제 없음 |
| 2 | Storage Controllers | `StorageControllers[]` 인라인 | `Controllers` 서브링크 | `StorageControllers[]` 인라인 | **P0 수정 필요** |
| 3 | Fan ReadingUnits | `RPM` (7500) | `Percent` (20%) | `RPM` (9840) | Thermal 수집 시 단위 정규화 필요 |
| 4 | IndicatorLED | `"Off"` (legacy) | `LocationIndicatorActive` (신규) | `"Off"` (legacy) | HPE에서 IndicatorLED MISSING |
| 5 | Voltages 배열 | 실제 전압값 (12.1V 등) | **배열 없음** | Power Good 센서 (1/0) | 벤더별 완전 다른 구조 |
| 6 | PSU 출력 필드 | `LastPowerOutputWatts` | `LastPowerOutputWatts` | `PowerOutputWatts` + `LastPowerOutputWatts=null` | Dell fallback 필요 |
| 7 | ProcessorSummary.Status | Health+HealthRollup+State | **HealthRollup만** | Health+HealthRollup+State | HPE fallback 필요 |
| 8 | MemorySummary.Status | 전체 제공 | **HealthRollup만** | 전체 제공 | HPE fallback 필요 |
| 9 | NIC 필드 | SpeedMbps+LinkStatus | **모두 null** | SpeedMbps=0 + LinkDown | HPE 최소 데이터 |
| 10 | OEM 네임스페이스 깊이 | `Oem.Lenovo.X` | `Oem.Hpe.X` | `Oem.Dell.DellSystem.X` (2단 깊음) | Dell OEM 접근 시 추가 `.` 필요 |

## 14. 미검증 항목

- Lenovo/HPE/Dell OEM System 확장 필드 상세 확인
- Thermal 수집 추가 시 필드 매핑
- Session Auth 방식 지원 검토 (이번 검증에서는 Basic Auth만 확인했다)
- 다른 세대 장비 (Gen10, R640 등) 검증
- 다중 Chassis member 처리 (이번 검증에서는 Members[0] 기준 동작만 확인했다)


## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 새 어댑터 추가 | [../develop/04-add-vendor.md](../develop/04-add-vendor.md) |
| 호환성 매트릭스 | [compatibility-matrix.md](compatibility-matrix.md) |
| Adapter 시스템 (점수 계산) | [../develop/03-adapter-system.md](../develop/03-adapter-system.md) |
| 결정 추적 | [decision-log.md](decision-log.md) |

## 자주 헷갈리는 점

| 질문 | 답 |
|------|----|
| 검증 결과가 baseline 과 다른데? | 펌웨어 / 모델 변경으로 응답이 달라졌는지 먼저 확인한다. 변경이 정당하면 실측으로 새 기준선을 만든다. |
| 새 펌웨어는 어디서 raw 응답을 캡처? | `tests/redfish-probe/probe_redfish.py` 또는 `deep_probe_redfish.py` 로 endpoint 별 응답 수집. |
| 미검증 벤더의 어댑터를 도입해도 되나? | 가능하지만 호환성 매트릭스에 "미검증" 으로 표시 필요. 실장비 검증 후 baseline 업데이트 권장. |

## CSUS 3200 / HBA·InfiniBand — lab 부재 (2026-05-29)

| 대상 | 상태 | 비고 |
|---|---|---|
| HPE CSUS 3200 | **mock baseline (미검증)** | 2026-05-29 에 전 공통 섹션 realistic mock 작성 (FC HBA + RAID1 SATA + DDR5 + 3 partition). web evidence (HPE Superdome Flex Admin Guide P/N 10-192008-Q123 등). 사이트 RMC 실측 시 정정한다 |
| FC HBA (전 vendor) | **미검증** | redfish/os/windows baseline 은 lab FC 부재로 빈. esxi_baseline 은 offline FC 2 (Cisco UCS VIC) |
| InfiniBand | **미검증** | Linux sysfs 가 정본 채널. lab IB HCA 부재 |

> mock/미검증 = pytest 통과 ≠ 사이트 실측 통과. 실장비 확보 시 원본 응답을 캡처해 실 baseline 으로 교체한다 ([../develop/08-onsite-capture.md](../develop/08-onsite-capture.md)).

## 2026-10-10 감사 — Redfish 수정의 증거 수준 (fixture · replay · main Job 매트릭스)

실장비 BMC 에 인증 실패를 유발하는 시험은 하지 않았다(계정 잠금 위험 — 계정 쓰기는 HOLD). 아래 항목의 "실장비" 란은 main Job 매트릭스(R10 · E2E-E)
에서 lab 10대의 결과가 바뀌었는지로만 확인한다 — 결과 차이는 `expected_diffs.json` 에 선언한 것만 허용한다.

| 항목 | 바뀐 것 | 증거 수준 |
|---|---|---|
| RD-F03 | `_get`/`_get_noauth`/`_probe_realm_hint` 가 `http.client.HTTPException`(IncompleteRead) 을 transport 오류로 분류 | unit (가짜 응답) |
| D-09 (RA-F03/F08) | vendor alias 탐색 — 최장 alias · 3자 이하 토큰 경계 (`iBMC` ≠ `ibm`) | unit (적대 문자열) · canonical SoT 시험 |
| RA-F05/F06 | 복구 인증 예산이 표준 계정 401 을 선소비 · 검증 간격은 장비 선언 패널티 먼저 · 예산 소진 시 counter-reset 뒤 1회 | unit (HPE 10s · Dell 3/60 fixture) — 실장비 401 유발 금지 |
| RD-F18 | BMC NIC · NetworkProtocol · PSU 컬렉션/멤버 · ResourceBlock/Switch/Endpoint 의 404 아닌 실패를 errors[] 로 | unit fixture (500/timeout 주입) |
| RD-F15 | 한 포트에 Ethernet + FC/FCoE 기능이 같이 있으면 FC 분류 · FC NDF 마다 hba 1개 | unit (멤버 순서 뒤집은 fixture) — lab CNA 없음 |
| D-07 (RD-F02/F08/F09) | Power·Thermal 둘 다 404 → not_supported · PSU 요약/용량 합에서 Absent 제외 | unit + 매트릭스(Absent PSU 슬롯이 있는 lab 장비에서 값 변화 선언) |
| RD-FW1 | firmware 분류에서 raid/perc/megaraid 가 nic/broadcom 보다 먼저 | unit (Broadcom RAID/NIC) |
| RD-UNK / RD-FW2 | cpu model 자리표시자 'unknown' → null · 버전 N/A 멤버 수 notice | unit |
| 죽은 코드 | `normalize_{system,network,storage}.yml`(redfish) · `normalize_sections.yml`(esxi) · `_endpoint_with_fallback` 삭제 — 참조 0 | grep · ci_gate · prodgen build |

> 모든 항목은 mock/fixture 통과 ≠ 사이트 실측 통과. 매트릭스에서 확인한 lab 장비 결과 차이와 그 선언은 `tests/evidence/2026-10-10-full-audit.md` 에 적는다.

### 2026-10-10 production P11 명부 (실장비)

production P11 `35b9ad5e`(main `c2d76de2`) 승격 직후 production Job #233~#238: canary os 3 · Linux A 8 · Linux B 7(미도달 3 기존) · Windows 1 · ESXi 6 · Redfish 10(실패 3 기존).
checkout == P11 · Portal 200 · P10 대조 회귀 0 — 선언 사용 D-03 (Windows), LX-F04, WIN-02, WIN-DM. 정본 `tests/evidence/2026-10-10-full-audit.md` 9절.

### 2026-10-11 production P12 명부 (실장비)

production P12 `410317a7`(main `9a6ee77b` — adapter 미참조 절 제거, 수집 경로 불변) 승격 직후 production Job #274~#279: canary #274 os 3/3 · Linux A #275 8/8 · Linux B #276 4 + 실패 3/7 · Windows #277 1/1 · ESXi #278 6/6 · Redfish #279 7 + 실패 3/10.
checkout == P12 · Portal 200 · P11 명부(#233~#238) 직접 대조 회귀 0 — 선언 사용 없음(입력 원본 P10 빌드 대조도 회귀 0 — 선언 사용 D-03 (Windows) · LX-F04 · WIN-02 · WIN-DM). 정본 `tests/evidence/2026-10-10-full-audit.md` 9절(2026-10-11).

## 2026-10-12 독립 점검 — main 매트릭스 · production P13 명부 (실장비)

실장비 BMC 에 인증 실패를 유발하는 시험은 하지 않았다(계정 쓰기 HOLD 유지). 수집 코드 변경(Redfish 403/404 판정 · adapter capabilities · 세대 토큰 · Linux memory/users · 정규화)의
실장비 영향은 main Job 매트릭스와 production 명부를 P12 명부(#274~#279)와 대상별로 대조해 확인했다(휘발 값 제외 — 시각 · 사용률 · 전력 · 온도). 정본 `tests/evidence/2026-10-12-independent-audit.md` 3절.

### main `46002a2b` 매트릭스 (main Job #528~#550, checkout 전부 == `46002a2b`)

| 시나리오 | 빌드 | 결과 | 관측 |
|---|---|---|---|
| S1 canary os 3 | #528 | SUCCESS | 3/3 · Portal 200 · #274 대조 비휘발 차이 0 |
| S3 Linux 12 | #530 | SUCCESS | 12/12 · Portal 200 |
| S2 혼합(실호스트 4 + TEST-NET 2) | #549 | SUCCESS | 4 success + 2 `TARGET_UNREACHABLE` · Portal 200 · 보충 0 (Linux B 7대 #532 는 4 + 실패 3(기존 .135 .145 .165) · #276 대조 차이 0) |
| Linux A 8 | #533 | SUCCESS | 8/8 · #275 대조: 파일시스템 사용률만 |
| S4 Windows 1 | #534 | SUCCESS | 1/1 · #277 대조 차이 0 |
| E2E-D ESXi 6 | #535 (#529 동일) | SUCCESS | 6/6 · #278 대조: datastore 사용률만 |
| E2E-E Redfish 7 | #536 (#531 동일) | SUCCESS | 7/7 · #279 대조: 시각 · 전력 · `hardware.uuid` 소문자(의도한 정규화) |
| Redfish 10 | #537 | SUCCESS | 7 success + 3 실패(10.100.15.1 `PROTOCOL_CHECK_FAILED` · 10.100.15.3 · 10.50.11.231 `TARGET_UNREACHABLE`, 모두 기존) · Portal 200 · #279 대조: 실패 3대의 `sections.system` failed → not_supported(의도 — 채널 섹션 통일) · 시각 · 전력 · `hardware.uuid` 소문자 |
| T2 TEST-NET 2 | #538 | SUCCESS | 2대 `TARGET_UNREACHABLE` 봉투 · Portal 200 1회 |
| T6 Callback 거부 주소 | #539 | UNSTABLE | 전송 도구 상태 408(연결 거부) 3회(대기 10초 · 20초) · delivered=false · receipt uncertain · 거부 아님 · `callback_body.json` 보존 |
| P11 실제 404 | #548 | UNSTABLE | controller loopback 의 임시 404 서버 — HTTP 404 · `refused=true` · 전송 1회 · 재전송 없음 · "Portal이 요청을 거부했습니다. HTTP 404." (시험용 Portal 은 없는 경로에 302 를 주어 #540 은 302 · 3회 실패 · 거부 아님. #545 GitLab https 는 TLS 예외, #547 Runner 호스트 포트는 NoRouteToHost 예외 — 둘 다 예외형 통신 실패로 재시도 3회) |
| P11 이름 풀이 실패 | #541 | UNSTABLE | HTTP 404 + `transport=unknown_host`(플러그인 합성 404 식별) 3회 · 거부 아님 · receipt not_delivered · 기존 재시도 범위 그대로 |
| E2E-A loc=cj | #542 | UNSTABLE | cj Runner 에서 실행 · 2대 실패 봉투 · Callback 408 3회 · delivered=false |
| E2E-A2 loc=chj | #550 (#543 동일) | FAILURE | `[실행 위치] 등록되지 않은 Location: 'chj'` — 수집 없이 `OUTPUT_BUILD_FAILED` 봉투 2 · Portal 200 · fail-closed |
| T5 사용자 중단 | #544 | ABORTED | `Aborted by admin` → `[수집] 중단됨: 빌드가 중단됐습니다(사용자 취소 또는 그 밖의 중단)` · 결과 보존 뒤 작업 폴더 유지(원인 미확정) · 12대 실패 봉투 · Portal 200 1회 · ABORTED 유지 |

### production P13 명부

production P13 `b86c5942`(main `46002a2b`) 승격 직후 production Job #280~#287: canary os 3 #280 · Linux A 8 #281 · Linux B 7 #282 · Windows 1 #283 · ESXi 6 #284 · Redfish 10 #285 · Redfish 10 재실행 #286(main #555 와 동시) · loopback 수신기 canary #287.
checkout 전부 == P13 · 결과 수 == 접수 수. 승격 시점에 Portal 테스트 수신 백엔드가 내려가 있어 #280~#286 은 서버가 돌려준 실제 404 를 확정 거부로 1회 기록했고(재전송 없음), Portal 200 은 저장소 `callback_sink.py` 를 controller loopback 에 띄운 임시 Job 으로 #287 에서 확인했다(수신 본문 sha256 == `callback_body.json`).
오전 main 매트릭스와의 차이는 대상 쪽 변화(10.100.64.161 전원 꺼짐 · 커널 업그레이드 재부팅 · Windows VM NIC 교체 · ESXi .2 물리 NIC 링크 · Dell BMC 재시작)이며, 같은 대상을 main Job 으로 다시 수집한 #551↔#281 · #553↔#283 · #554↔#284 · #555↔#286 은 비휘발 차이 0, #552↔#282 는 파일시스템 사용률 1건이다.
호스트별 상태: Linux A 7/8 · Linux B 4/7(기존 .135 .145 .165) · Windows 1/1 · ESXi 6/6 · Redfish 8/10(10.100.15.1 `PROTOCOL_CHECK_FAILED` · 10.100.15.3 `TARGET_UNREACHABLE`).

## 2026-10-13 Linux sudo Vault 후보 · OS Serial 필수 · H12 대표 오류 — main 매트릭스 · production P14 · P15 명부 (실장비)

수집 코드 변경(Linux sudo 후보 · 잠금 예산 · Serial 필수 · `diagnosis.details.sudo`)의 실장비 증거는 `../../tests/evidence/2026-10-13-sudo-fallback-serial-required.md` 다
(10.100.64.132 테스트 계정 시나리오 #556~#562 · 명부 #563). 승격 전제의 매트릭스는 최종 후보 main `b203fd45` 에서 돌렸다(1차 후보 `03a5637b` 의 매트릭스 #564~#573 은 CI Gate 실패로 증거에서 제외).
.161 은 전원이 꺼져 있어 S3 명부에서 뺐다.

### main `b203fd45` 매트릭스 (main Job #574~#583, checkout 전부 == `b203fd45`)

| 시나리오 | 빌드 | 결과 | 관측 |
|---|---|---|---|
| S1 Linux 3 (.162 .163 .156) | #581 | SUCCESS | 3/3 success · serial 있음 · `details.sudo` nopasswd 2 · password(login) 1 · Portal 200 |
| S2 혼합(실호스트 3 + TEST-NET 2) | #582 | SUCCESS | .132 .33 .34 success + 2 `TARGET_UNREACHABLE` · Portal 200 · 보충 0 |
| S3 Linux 11 | #574 | SUCCESS | 11/11 success · serial 있음(password/login 9 · nopasswd 2) · Portal 200 |
| S4 Windows 1 (.120) | #575 | SUCCESS | 1/1 · serial 있음 · Portal 200 |
| T2 TEST-NET 2 | #577 | SUCCESS | 2대 `TARGET_UNREACHABLE` 봉투 · Portal 200 |
| T5 사용자 중단 | #583 | ABORTED | 6대 수집 시작 15초 뒤 API stop → `[수집] 중단됨: 빌드가 중단됐습니다` · 6대 실패 봉투(gather / GATHER_FAILED) · Portal 200 · `callback_body.json` 보존 · ABORTED 유지 |
| T6 Callback 거부 주소 | #578 | UNSTABLE | `http://127.0.0.1:9` 3회 실패(10초 · 20초 대기) · delivered=false · body 보존 |
| E2E-A loc=cj | #579 | UNSTABLE | cj Runner 에서 실행 · 2대 실패 봉투 · Callback 3회 실패 |
| E2E-A2 loc=chj | #580 | FAILURE | `[실행 위치] 등록되지 않은 Location: 'chj'` · 수집 없이 봉투 2 · Portal 200 · fail-closed · tip 관측(`git ls-remote` origin · internal 전후 모두 `b203fd45`) |
| E2E-D ESXi 6 | #576 | SUCCESS | 6/6 · serial 있음 · Portal 200 |

### production P14 명부

production P14 `604062c0`(main `b203fd45`) 승격 직후 production Job: canary os 2 #288(.132 Linux NOPASSWD · .120 Windows — 2/2 success · serial 있음) · Linux 11 #289(11/11 success · sudo password/login 9 · nopasswd 2) · ESXi 6 #290(6/6) · Redfish 10 #291(8 success + 10.100.15.1 `PROTOCOL_CHECK_FAILED` · 10.100.15.3 `TARGET_UNREACHABLE` — P13 #285 와 같은 기존 실패). checkout 전부 == `604062c0`(`refs/remotes/origin/production`) · 결과 수 == 접수 수 · Portal 200 · Jenkins 결과 전부 SUCCESS

### main `341433af` 매트릭스 — H12 대표 오류 · sudo live 시험 (main Job #584~#593, checkout 전부 == `341433af`)

`75ca57c2`(정상 경로 failed 봉투의 errors[0] 대표 문장) + `341433af`(sudo live 매트릭스 시험) 의 승격 전제. 증거 `../../tests/evidence/2026-10-13-h12-representative-error-and-sudo-live.md`.

| 시나리오 | 빌드 | 결과 | 관측 |
|---|---|---|---|
| S1 Linux 3 (.162 .163 .156) | #590 | SUCCESS | 3/3 success · serial 있음 · sudo nopasswd 2 · password(login) 1 · Portal 200 |
| S2 혼합 (.132 .33 .34 + TEST-NET 2) | #591 | SUCCESS | 3 success(serial 있음) + 2 `TARGET_UNREACHABLE` · 봉투 5 = 접수 5 · Portal 200 |
| S3 Linux 11 (.161 제외) | #584 | SUCCESS | 11/11 success · serial 전부 · sudo password(login) 9 · nopasswd 2 · Portal 200 |
| S4 Windows .120 | #587 | SUCCESS | 1/1 success · serial 있음 · Portal 200 |
| T2 TEST-NET 2 | #586 | SUCCESS | 2/2 `TARGET_UNREACHABLE` · Portal 200 |
| T5 사용자 중단 (6대) | #592 | ABORTED | 수집 시작 15초 뒤 API stop · `[수집] 중단됨` · 6 봉투 GATHER_FAILED · Portal 200 · body 보존 |
| T6 Callback 거부 주소 | #588 | UNSTABLE | `http://127.0.0.1:9` 3회 실패(10초 · 20초 대기) · delivered=false · body 보존 |
| E2E-A loc=cj | #589 | UNSTABLE | cj Runner 에서 실행 · 2대 실패 봉투 · Callback 3회 실패 |
| E2E-A2 loc=chj | #593 | FAILURE | `[실행 위치] 등록되지 않은 Location: 'chj'` · 수집 없이 봉투 2 · Portal 200 · fail-closed · tip 관측(origin · internal 전후 모두 `341433af`) |
| E2E-D ESXi 6 | #585 | SUCCESS | 6/6 · serial 있음 · Portal 200 |

봉투 38(실패 14) 전수: 13 필드 · enum · failed → `errors[0].message == failure_reason` · lab 자격 문자열 0건. 이 매트릭스에서 H12 경로(정상 경로 성공 섹션 0개)는 발생하지 않았다 —
그 경로는 실제 엔진 통합 시험으로 검증했다.

### production P15 명부

production P15 `6193660c`(main `341433af`, 직전 `604062c0`) 승격 직후 production Job: canary os 2 #292(.132 Linux NOPASSWD · .120 Windows — 2/2 success · serial 있음) · Linux 11 #293(11/11 success · sudo password/login 9 · nopasswd 2) · ESXi 6 #294(6/6) · Redfish 10 #295(8 success + 10.100.15.1 `PROTOCOL_CHECK_FAILED` · 10.100.15.3 `TARGET_UNREACHABLE` — P14 #291 과 같은 기존 실패). checkout 전부 == `6193660c`(`refs/remotes/origin/production`) · 결과 수 == 접수 수 · Portal 200 · Jenkins 결과 전부 SUCCESS. 봉투 29 전수 계약 검사 위반 0 · 자격 문자열 0건 — `../../tests/evidence/2026-10-13-h12-representative-error-and-sudo-live.md` 7절.
