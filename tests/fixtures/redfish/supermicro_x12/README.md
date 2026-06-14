# Supermicro X12 mock fixture (cycle 2026-05-07 M-B4)

## 출처 (rule 96 R1-A — lab 부재)

- Supermicro X12 BMC Redfish ref: `https://www.supermicro.com/manuals/other/RedfishUserGuide.pdf`
- Supermicro firmware inventory: `https://www.supermicro.com/manuals/other/redfish-ref-guide-html/Content/general-content/firmware-inventory-update-service.htm`
- Supermicro BIOS/IPMI 리소스: `https://www.supermicro.com/support/resources/bios_ipmi.php?type=BMC`

확인일: 2026-05-07

## Lab 상태

- 부재 — 사용자 명시 2026-05-07 Q2 (Supermicro 사이트 BMC 0대)
- web sources 기반 mock — 실 BMC 응답과 차이 가능

## Generation 특성

- Platform: Whitley / Tatlow (2020-2022)
- CPU: Intel Xeon Ice Lake / Sapphire Rapids 초기
- BMC: Aspeed AST2600 (Root of Trust)
- Redfish: DSP0268 v1.13+
- H12 도 동세대 BMC 공유 (AMD EPYC Rome/Milan)

## 호환성 가정 (X11 대비 변화)

- **PowerSubsystem 도입**: `/redfish/v1/Chassis/{id}/PowerSubsystem` 표준 path 지원 (DSP0268 v1.13+)
- **Storage 표준 path 지원**: `/redfish/v1/Systems/{id}/Storage` (SimpleStorage fallback 불필요)
- **OEM 약함**: `Oem.Supermicro` 응답 minimal (X12 부터 표준 path 우선)
- **Root of Trust**: BMC 펌웨어 secure boot 지원

## endpoint 매트릭스

| endpoint | 파일 | 비고 |
|---|---|---|
| `/redfish/v1/` | service_root.json | RedfishVersion="1.13.0" |
| `/redfish/v1/Chassis` | chassis_collection.json | |
| `/redfish/v1/Chassis/1` | chassis.json | PowerSubsystem link |
| `/redfish/v1/Chassis/1/PowerSubsystem` | chassis_power_subsystem.json | X12+ 신 path |
| `/redfish/v1/Systems` | systems_collection.json | |
| `/redfish/v1/Systems/1` | system.json | Storage link (표준 path) |
| `/redfish/v1/Systems/1/Storage` | system_storage.json | 표준 Storage path |
| `/redfish/v1/Managers` | managers_collection.json | |
| `/redfish/v1/Managers/1` | manager.json | BMC 펌웨어 |
| `/redfish/v1/UpdateService` | update_service.json | |
| `/redfish/v1/UpdateService/FirmwareInventory` | firmware_inventory.json | |
| `/redfish/v1/AccountService` | account_service.json | |
