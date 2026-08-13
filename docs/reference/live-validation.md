# Redfish 실장비 API 검증 결과

> 이 문서는 실제 BMC 장비를 대상으로 Redfish API 호출을 검증한 결과를 누적 기록한다.
> 새 펌웨어 / 새 모델이 들어왔을 때 "어떤 endpoint 가 응답하는지", "OEM 영역이 어떻게 다른지" 를 비교하는 데 참고한다.
>
> 회귀 검증 단위(Round)별로 결과를 추가하며 검증 시점의 정확한 펌웨어 버전과 응답 차이를 보존한다.
> 펌웨어 업그레이드 후 응답이 달라지면 이 문서가 비교 기준이 된다.

> 검증일: 2026-03-18 | 검증 방식: 직접 HTTPS 호출 (curl/Python urllib)

> [!NOTE]
> 이 문서를 읽는 법: 1~14절은 2026-03-18 3대 실장비 검증 스냅샷이다. 그 안의 "수정 필요" 표시는 검증 시점 기준이며 이후 cycle 에서 해결된 항목이 있다 (해결 내역은 `docs/reference/decision-log.md`).
> 15~16절은 이후 lab 부재(web sources) 호환성 cycle 기록이다. 현재 adapter/vendor 전체 목록은 `adapters/redfish/` 디렉터리와 `docs/reference/compatibility-matrix.md` 를 본다.

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
| redfish_dell_idrac8 | 50 | Dell + firmware iDRAC 8 | 9개 (power FB — cycle 2026-05-06 M-D3) |
| redfish_dell_idrac9 | 100 | Dell + firmware iDRAC 9 | 9개 전체 |
| redfish_hpe_ilo | 10 | vendor: HPE | 9개 전체 |
| redfish_hpe_ilo4 | 50 | HPE + firmware iLO 4 | 9개 (storage/power FB — cycle 2026-05-06 M-D3) |
| redfish_hpe_ilo5 | 100 | HPE + firmware iLO 5 | 9개 전체 |
| redfish_lenovo_imm2 | 50 | Lenovo + firmware IMM2 | 9개 (storage/power FB — cycle 2026-05-06 M-D3) |
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

## 15. cycle 2026-05-06 — 무 lab 환경 호환성 cycle (M-cycle)

### 15-1. 사용자 명시 (2026-05-06)

> "lab 접속 가능 장비 없음 → 프로젝트 코드를 모든 vendor / 모든 장비에 호환되도록 작성. 실 검증은 향후."

### 15-2. M-cycle 결과

| 영역 | 결과 |
|---|---|
| status 로직 (M-A) | Case A 채택 (의도 주석 강화 only) — pytest 13건 추가 (총 294 PASS) |
| account_service (M-B) | 9 vendor 매트릭스 25 row 정적 검증 — Gap 0, BLOCK 1 (Supermicro X9) |
| vault 자동 반영 (M-C) | YES (다음 ansible run 부터) — cacheable 0 / fact_caching 0 / gather_facts: no |
| 호환성 매트릭스 (M-D) | 240 cell 전수 분류 — M-D 분석 시점 OK 27 / OK★ 167 / FB 9 / GAP 7 / BLOCK 6 / N/A 24 (W1~W6 적용 후 현재 36/157/14/3/6/24 — docs/22) |
| Superdome 추가 (M-E) | hpe_superdome_flex.yml (priority=95 → 현재 101, lab 부재 web sources 14건) |
| docs/20 신설 (M-F) | envelope 13 + sections 10 + field_dictionary 83 정본 + 3채널 비교 |
| 학습 추출 (M-G) | (cycle 종료 시) |

### 15-3. M-D3 W1~W6 호환성 활성화 (2026-05-06)

| 작업 | 영향 adapter | 변경 |
|---|---|---|
| W1 | dell_idrac8.yml | `+ power` capabilities 추가 (cycle 2026-05-01 PowerSubsystem fallback 활용) |
| W2 | hpe_ilo4.yml | `+ storage` (A1 SimpleStorage fallback 활용) |
| W3 | hpe_ilo4.yml | `+ power` (A2 PowerSubsystem→Power) |
| W4 | lenovo_imm2.yml | `+ storage` (A1) |
| W5 | lenovo_imm2.yml | `+ power` (A2) |
| W6 | huawei/inspur/fujitsu/quanta_*.yml | `- users` 4 곳 제거 (sections.yml channels=[os] 정합) |

→ **9 라인 변경 (Additive only — rule 92 R2)** + pytest 294/294 PASS + envelope 13 필드 변경 0.

### 15-4. HPE Superdome Flex 추가 (M-E2)

| 항목 | 내용 |
|---|---|
| 위치 | `adapters/redfish/hpe_superdome_flex.yml` (priority=95 → 현재 101) |
| 모델 | Superdome Flex 280 (2020+) / Superdome Flex (2017+) |
| BMC | RMC + per-node iLO 5 (dual-manager) |
| Multi-partition | nPAR — Systems ID = `Partition<N>`. 첫 partition (Partition0) 만 수집 |
| OEM | Oem.Hpe (기존 HPE OEM 재사용) |
| vault | hpe (별도 불필요) |
| Legacy 처리 | Superdome 2/Integrity → `redfish_generic.yml`. Superdome X → `hpe_ilo4.yml` |
| sources | vendor docs 6 + DMTF 2 + GitHub 6 = 14건 (rule 96 R1-A) |
| lab | 부재 — 사이트 실측 시 정정 가능 |

### 15-5. 후속 lab 도입 시 작업

- Supermicro X9 6 cell BLOCK 해제 (capture-site-fixture skill)
- Superdome Flex multi-partition 전수 수집 (별도 cycle)
- Lenovo XCC v3 OpenBMC 1.17.0 reverse regression fixture (사이트 fixture)
- Cisco UCS X-Series IMM 모드 (Intersight) 통합

---

## 16. cycle 2026-05-07 — all-vendor-coverage (Phase 1/2/3)

> cycle 2026-05-07-all-vendor-coverage Phase 3 M-L4 — 38 ticket 통합 + 사이트 검증 4 + lab 부재 명시.
> Worker: W5 (Phase 3). Phase 1 (23 ticket) + Phase 2 (5 ticket) + Phase 3 (7 ticket) = 38 ticket.

### 16.1 Round 2026-05-07 — 사이트 검증 4 vendor × 1 generation

> 본 Round 는 사용자 사이트 BMC 1대 이상 보유 vendor / generation 의 실 검증 결과.
> 검증 commit: `0a485823` (cycle 2026-05-06 multi-session-compatibility 종료 commit).

#### 결과 매트릭스

| vendor | generation | 사이트 BMC | 검증 commit | 결과 |
|---|---|---|---|---|
| Dell | iDRAC10 | 5대 (10.100.15.27 / 28 / 31 / 33 / 34) | `0a485823` | [PASS] — 8 Redfish endpoint 모두 SUCCESS |
| HPE | iLO6 | 1대 (10.50.11.231) | `0a485823` | [PASS] |
| Lenovo | XCC3 | 1대 (10.50.11.232) | `0a485823` | [PASS] — Accept-only header 정책 (cycle 2026-04-30 reverse regression) |
| Cisco | UCS X-series | 1대 (10.100.15.2) | `0a485823` | [PASS] — standalone CIMC |

#### 검증 항목

- ServiceRoot ~ AccountService 9 endpoint 모두 SUCCESS
- 8 Redfish + 7 OS + 3 ESXi 통합 검증 commit `0a485823` 에 PASS 기록
- 본 검증 시점 baseline_v1 4 vendor (Dell/HPE/Lenovo/Cisco) 갱신

#### 사이트 사고 / 학습 (cycle 2026-04-30 reverse regression)

- Lenovo XCC3 펌웨어 1.17.0 — Accept + OData-Version + User-Agent 추가 시 reject
- "Accept 만" 으로 hotfix (rule 25 R7-A-1 — 사용자 실측 > spec)
- 본 정책은 다른 사이트 (Lenovo XCC2 / iLO5+ / Supermicro X12+) 도 동일 가능성 — 보수적 header 정책 의무

### 16.2 lab 부재 영역 (cycle 2026-05-07 명시)

> 사용자 명시 (2026-05-07 Q2/Q3): Supermicro 사이트 BMC 0대 + Huawei/Inspur/Fujitsu/Quanta lab 도입 timeline 장기 (미정).
> 본 영역 코드 path 는 web sources 기반 (rule 96 R1-A) — 사이트 도입 시 별도 cycle 검증.

#### lab 부재 vendor / generation 매트릭스

| vendor | generation | lab status | 코드 path | NEXT_ACTIONS 등재 |
|---|---|---|---|---|
| Dell | iDRAC7 (legacy) | 부재 | adapter dell_idrac.yml + M-H1 mock | [PENDING] — Dell iDRAC7 lab cycle |
| Dell | iDRAC8 | 부재 | adapter dell_idrac8.yml + M-H1 mock | [PENDING] (PowerSubsystem fallback W1 검증) |
| Dell | iDRAC9 | 부재 | adapter dell_idrac9.yml + M-H1 mock (3 variants — 3.x/5.x/7.x) | [PENDING] |
| HPE | iLO (legacy 1/2/3) | 부재 (Redfish 미지원) | adapter hpe_ilo.yml + IPMI fallback 별도 검토 | [SKIP] |
| HPE | iLO4 | 부재 | adapter hpe_ilo4.yml + M-H2 mock | [PENDING] (SimpleStorage W2 + Power W3 검증) |
| HPE | iLO5 | 부재 | adapter hpe_ilo5.yml + M-H2 mock | [PENDING] |
| HPE | iLO6 | partial (Round 11 + 사이트 Gen12) | adapter hpe_ilo6.yml + M-H2 mock | [PENDING] (PowerSubsystem dual + SmartStorage fallback) |
| HPE | Superdome Flex (Gen 1/2 + 280) | 부재 | adapter hpe_superdome_flex.yml (priority=95 → 현재 101, docs/10 §3.5) + M-G1 OEM 분기 + M-G2 mock | [PENDING] (RMC + Partition0 + iLO5 dual-manager) |
| Lenovo | BMC (IBM 시기) | 부재 (Redfish 미지원) | adapter lenovo_bmc.yml | [SKIP] |
| Lenovo | IMM (legacy) | 부재 (Redfish 미지원) | (별도 분기 없음 — lenovo_bmc fallback) | [SKIP] |
| Lenovo | IMM2 | 부재 | adapter lenovo_imm2.yml + M-H3 mock | [PENDING] (SimpleStorage W4 + Power W5 검증) |
| Lenovo | XCC | 부재 | adapter lenovo_xcc.yml (firmware_patterns XCC + XCC2) + M-H3 mock | [PENDING] |
| Lenovo | XCC2 | 부재 | (위 동일) | [PENDING] |
| Cisco | BMC (legacy) | 부재 (Redfish 미지원) | adapter cisco_bmc.yml | [SKIP] |
| Cisco | CIMC C-series 1.x ~ 4.x | partial (M4 lab tested) | adapter cisco_cimc.yml (firmware_patterns 4.x~6.x) + M-H4 mock (4 variants) | [PENDING] (M5~M8 web sources only) |
| Cisco | UCS S-series | 부재 | adapter cisco_cimc.yml (model_patterns UCS-S3260) | [PENDING] (M-H4 — Storage 강화 검증) |
| Cisco | UCS B-series | 부재 (UCS Manager 매개) | adapter cisco_cimc.yml + 별도 cycle | [PENDING] — UCS Manager 통합 cycle |
| Supermicro | BMC (legacy) ~ X14 (7 gen) | 부재 (Q2 — 사이트 0대) | adapter 8개 + OEM tasks 보강 (M-B2) + mock (M-B4) | [PENDING] — Supermicro lab 도입 cycle |
| Supermicro | H11 ~ H14 (AMD) | 부재 | adapter X11~X14 model_patterns 확장 (M-B3) | [PENDING] |
| Supermicro | **X10 (cycle 2026-05-07 신설)** | 부재 | adapter supermicro_x10.yml (priority=75 — M-B1) | [PENDING] |
| Supermicro | **ARS (ARM, cycle 2026-05-07 신설)** | 부재 | adapter supermicro_ars.yml (priority=80 — M-B3) | [PENDING] |
| **HPE** | **Compute Scale-up Server 3200 (CSUS 3200, cycle 2026-05-11 신설)** | **부재 (lab 도입 시 별도 cycle)** | **adapter hpe_csus_3200.yml (priority=96 → 현재 102, docs/10 §3.5) + HPE OEM tasks 재사용 (regex 확장 Additive)** | **[PENDING]** |
| Huawei | iBMC 1.x ~ 5.x + Atlas | 부재 (cycle 2026-05-01 명시) | adapter huawei_ibmc.yml (M-C1) + OEM tasks (M-C2) + mock (M-C3) | [PENDING] |
| Inspur | ISBMC | 부재 (cycle 2026-05-01) | adapter inspur_isbmc.yml + OEM tasks (M-D1) + mock (M-D2) | [PENDING] |
| Fujitsu | iRMC S2 | 부재 (Redfish 미지원 가능성) | adapter fujitsu_irmc.yml (firmware_patterns) | [SKIP] |
| Fujitsu | iRMC S4 / S5 / S6 | 부재 (cycle 2026-05-01) | (위 동일) + OEM tasks (M-E2) + mock (M-E3) | [PENDING] |
| Quanta | QCT BMC (S/D/T/J) | 부재 (cycle 2026-05-01) | adapter quanta_qct_bmc.yml + OEM tasks (M-F1) + mock (M-F2) | [PENDING] |

### 16.3 web sources 의무 (rule 96 R1-A)

본 lab 부재 영역의 모든 adapter / OEM tasks / mock 은 다음 sources 기반:

| source | 영역 |
|---|---|
| vendor 공식 docs | 9 vendor 공식 매뉴얼 (URL — adapter 헤더 주석 `# source: ...`) |
| DMTF Redfish spec | DSP0268 v1.0 ~ v1.13+ (PowerSubsystem / Storage / AccountService schema) |
| GitHub community / issue | Inspur / Quanta / Huawei / Fujitsu (영문 docs 약함 영역) |
| 사이트 실측 | 본 Round 16.1 (Dell/HPE/Lenovo/Cisco × 1 generation) |

cycle 2026-05-07 M-K1 검증: 30/30 adapter origin 주석 일관성 PASS (verify 도구: `python 내부 검증 스크립트 --all --redfish-only`).

### 16.3.1 cycle 2026-05-11 hpe-csus-add 추가 (lab 부재)

사용자 요청 (2026-05-11): "hpe csus 장비도 개더링이 필요하다"

- **HPE Compute Scale-up Server 3200 (CSUS 3200)** — HPE 공식 명시 *"built on the proven HPE Superdome Flex architecture"* (HPE psnow doc/a50009596enw)
- **관리**: RMC (Rack Management Controller) primary + PDHC (per-chassis) + RMP (redundancy)
- **Redfish**: 표준 (RMC = API host) + HPE OneView profile 동시 지원
- **adapter**: `adapters/redfish/hpe_csus_3200.yml` (priority=96 → 현재 102 — Superdome Flex 95→101 직상, docs/10 §3.5)
- **OEM 추출**: 라이브러리 `_extract_oem_hpe` (Ansible task 층은 2026-08-13 제거)
- **regex 확장**: `(?i)Superdome|Flex` → `(?i)Superdome|Flex|Compute Scale-up|CSUS` (Additive only — rule 92 R2)
- **vault profile**: `hpe` 재사용 (사용자 명시 승인 시 향후 분리)
- **web sources 7건** (rule 96 R1-A — adapter 헤더 origin 주석)
- **lab 도입 후 cycle**: `hpe-csus-3200-lab-validation` round (NEXT_ACTIONS 등재 — rule 96 R1-C)

### 16.4 본 cycle (2026-05-07 all-vendor-coverage) 산출 요약

| 항목 | 변경 |
|---|---|
| adapter (Redfish) | 28 → 30 (+supermicro_x10 M-B1 / +supermicro_ars M-B3) |
| vault encrypted | 5 → 9 (+huawei M-A1 / +inspur M-A2 / +fujitsu M-A3 / +quanta M-A4) |
| vendor OEM tasks | 4 → 9 (+cisco M-J1 / +huawei M-C2 / +inspur M-D1 / +fujitsu M-E2 / +quanta M-F1) |
| mock fixture | 4 → 22+ generation |
| catalog 갱신 | NEXT_ACTIONS (M-L1) / VENDOR_ADAPTERS (M-L2) / COMPATIBILITY-MATRIX (M-L3) / EXTERNAL_CONTRACTS (M-K2) / docs/13 (M-L4) |
| baseline_v1 | 변경 0 (lab 부재 vendor SKIP — rule 13 R4) |
| schema/sections.yml + field_dictionary.yml | 변경 0 (Q7 — schema 변경 0) |
| OEM namespace 매트릭스 | 5 → 9 vendor (M-I3 helper + M-J1 Cisco vendor task) |
| origin 주석 일관성 (M-K1) | 30/30 PASS |
| Phase 2 helpers | +7 (`_gather_smart_storage` / `_merge_power_dual` / `_extract_oem_unified` / `_detect_nic_ocp_slot` / `_detect_nic_sriov_capable` / `_normalize_role_id` / `_normalize_dimm_label`) |
| redfish_gather.py | +338 lines (stdlib only — rule 10 R2) |
| ticket | 38/38 DONE (Phase 1/2/3 통합) |

---

## 다음 단계

| 다음 작업 | 문서 |
|---|---|
| 새 어댑터 추가 | [../develop/04-add-vendor.md](../develop/04-add-vendor.md) |
| 호환성 매트릭스 | [compatibility-matrix.md](compatibility-matrix.md) |
| Adapter 시스템 (점수 계산) | [../develop/03-adapter-system.md](../develop/03-adapter-system.md) |
| 결정 추적 | [decision-log.md](decision-log.md) |
| lab 도입 후 별도 cycle | [내부 후속 작업 목록](ai/NEXT_ACTIONS.md) (M-L1) |
| vendor adapter 매트릭스 | [내부 카탈로그](ai/catalogs/VENDOR_ADAPTERS.md) (M-L2) |
| compatibility matrix 상세 | [내부 카탈로그](ai/catalogs/COMPATIBILITY-MATRIX.md) (M-L3) |
| 외부 계약 매트릭스 | [내부 카탈로그](ai/catalogs/EXTERNAL_CONTRACTS.md) (M-K2) |

## 자주 헷갈리는 점

| 질문 | 답 |
|------|----|
| 검증 결과가 baseline 과 다른데? | 펌웨어 / 모델 변경으로 응답이 달라졌는지 먼저 확인. 변경이 정당하면 baseline_v2/ 로 새 정답지 도입 (rule 13 R4). |
| 새 펌웨어는 어디서 raw 응답을 캡처? | `tests/redfish-probe/probe_redfish.py` 또는 `deep_probe_redfish.py` 로 endpoint 별 응답 수집. |
| 미검증 벤더의 어댑터를 도입해도 되나? | 가능하지만 호환성 매트릭스에 "미검증" 으로 표시 필요. 실장비 검증 후 baseline 업데이트 권장. |

## CSUS 3200 / HBA·InfiniBand — lab 부재 (cycle 2026-05-29)

| 대상 | 상태 | 비고 |
|---|---|---|
| HPE CSUS 3200 | **mock baseline (미검증)** | cycle 2026-05-29 에 전 공통 섹션 realistic mock 작성 (FC HBA + RAID1 SATA + DDR5 + 3 partition). web evidence (HPE Superdome Flex Admin Guide P/N 10-192008-Q123 등). **사이트 RMC 실측 시 정정 의무** — NEXT_ACTIONS §2.2 |
| FC HBA (전 vendor) | **미검증** | redfish/os/windows baseline 은 lab FC 부재로 빈. esxi_baseline 은 offline FC 2 (Cisco UCS VIC). NEXT_ACTIONS §2.4 |
| InfiniBand | **미검증** | Linux sysfs 가 정본 채널. lab IB HCA 부재. NEXT_ACTIONS §2.4 |

> mock/미검증 = pytest 통과 ≠ 사이트 실측 통과 (rule 25 R7-B). 실장비 확보 시 `capture-site-fixture` + rule 13 R4 절차로 실 baseline 교체.
