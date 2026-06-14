# Supermicro X14 mock fixture (cycle 2026-05-07 M-B4)

## 출처 (rule 96 R1-A — lab 부재)

- Supermicro X14/H14 BMC docs: `https://www.supermicro.com/manuals/other/BMC_IPMI_X14_H14.pdf`
- Supermicro Redfish ref: `https://www.supermicro.com/manuals/other/RedfishUserGuide.pdf`
- Supermicro BIOS/IPMI 리소스: `https://www.supermicro.com/support/resources/bios_ipmi.php?type=BMC`

확인일: 2026-05-07

## Lab 상태

- 부재 — 사용자 명시 2026-05-07 Q2 (Supermicro 사이트 BMC 0대)
- web sources 기반 mock — 실 BMC 응답과 차이 가능

## Generation 특성

- Platform: 2024-2025 출하
- CPU: Intel Granite Rapids / Sierra Forest / AMD EPYC 신세대 (H14)
- BMC: Aspeed AST2600 + 신 features (CPLD inventory / iHDT)
- Redfish: 1.21.0 / bundle 2024.3
- H14 도 동세대 BMC 공유

## 호환성 가정 (X12/X13 대비 변화)

- **신 features (server-exporter read-only 영향 검증)**:
  - CPLD firmware inventory (gather_firmware 자동 cover)
  - StartTLS / Boot Certificates (server-exporter 사용 안 함)
  - ClearCMOS action (read-only — 미호출)
  - iHDT (intelligent hardware diagnostic test, read-only 영향 없음)
  - CPU power capping (read-only 영향 없음)
- **PowerSubsystem / Storage 표준**: X12/X13 와 동일 path 구조 (호환)

## endpoint 매트릭스

| endpoint | 파일 | 비고 |
|---|---|---|
| `/redfish/v1/` | service_root.json | RedfishVersion="1.21.0" |
| `/redfish/v1/Chassis` | chassis_collection.json | |
| `/redfish/v1/Chassis/1` | chassis.json | PowerSubsystem link |
| `/redfish/v1/Chassis/1/PowerSubsystem` | chassis_power_subsystem.json | X12+ standard |
| `/redfish/v1/Systems` | systems_collection.json | |
| `/redfish/v1/Systems/1` | system.json | Storage link |
| `/redfish/v1/Systems/1/Storage` | system_storage.json | 표준 Storage path |
| `/redfish/v1/Managers` | managers_collection.json | |
| `/redfish/v1/Managers/1` | manager.json | BMC 펌웨어 (최신) |
| `/redfish/v1/UpdateService` | update_service.json | |
| `/redfish/v1/UpdateService/FirmwareInventory` | firmware_inventory.json | CPLD 추가 |
| `/redfish/v1/AccountService` | account_service.json | |
