# Supermicro X10 mock fixture (cycle 2026-05-07 M-B4)

## 출처 (rule 96 R1-A — lab 부재)

- Supermicro X10 IPMI/BMC docs: `https://www.supermicro.com/manuals/superserver/IPMI/IPMI_Users_Guide_X10.pdf`
- DMTF Redfish 표준: `https://redfish.dmtf.org/schemas/v1/` (DSP0268 v1.0~v1.6 영역)
- Supermicro BIOS/IPMI 리소스: `https://www.supermicro.com/support/resources/bios_ipmi.php?type=BMC`

확인일: 2026-05-07

## Lab 상태

- 부재 — 사용자 명시 2026-05-07 Q2 (Supermicro 사이트 BMC 0대)
- web sources 기반 mock — 실 BMC 응답과 차이 가능
- 사이트 도입 시 capture-site-fixture skill 로 보정 (rule 50 R2 단계 10)

## Generation 특성

- Platform: Grantley / Brickland (2014-2018)
- CPU: Intel Xeon E5-2600 v3/v4 / E7 v3/v4
- BMC: Aspeed AST2400 (일부 AST2500)
- BMC 펌웨어: 1.x ~ 3.x
- Redfish: DSP0268 v1.0+ 부분 지원 (legacy IPMI 우선)

## 호환성 가정

- **PowerSubsystem 미지원**: `/redfish/v1/Chassis/{id}/PowerSubsystem` 없음 → Power deprecated path 만 (`Power` resource)
- **Storage 표준 path 부분 지원**: SimpleStorage 우선 fallback
- **OEM 확장 매우 약함**: `Oem.Supermicro` 응답 minimal
- **AccountService 표준 path**: `/redfish/v1/AccountService/Accounts`

## endpoint 매트릭스

| endpoint | 파일 | 비고 |
|---|---|---|
| `/redfish/v1/` | service_root.json | RedfishVersion="1.6.0" |
| `/redfish/v1/Chassis` | chassis_collection.json | |
| `/redfish/v1/Chassis/1` | chassis.json | Manufacturer / Model / Power(deprecated) |
| `/redfish/v1/Chassis/1/Power` | chassis_power.json | PSU + Voltage (deprecated path) |
| `/redfish/v1/Systems` | systems_collection.json | |
| `/redfish/v1/Systems/1` | system.json | CPU summary / Memory summary |
| `/redfish/v1/Systems/1/SimpleStorage` | system_simple_storage.json | SimpleStorage path |
| `/redfish/v1/Managers` | managers_collection.json | |
| `/redfish/v1/Managers/1` | manager.json | BMC 펌웨어 정보 |
| `/redfish/v1/UpdateService` | update_service.json | FirmwareInventory link |
| `/redfish/v1/UpdateService/FirmwareInventory` | firmware_inventory.json | |
| `/redfish/v1/AccountService` | account_service.json | |
