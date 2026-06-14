# Inspur ISBMC mock fixture — NF5280M5

> cycle 2026-05-11 M-D2 — lab 부재 web sources 기반 (rule 96 R1-A)

## Vendor

- Manufacturer: Inspur (`Inspur` / `Inspur Information Technology Company Limited`)
- Model: NF5280M5
- BMC: ISBMC
- BMC firmware: 4.16.11
- Manager URI: `/redfish/v1/Managers/1` (표준)

## Web sources (rule 96 R1-A)

- https://manualzz.com/doc/o/v7c5h/inspur-server-user-manual-nf5280m5-9.14-redfish (확인 2026-05-07)
- https://www.inspur.com/eportal/fileDir/defaultCurSite/resource/cms/2020/04/2020040211224398612.pdf
- DMTF Redfish DSP0268 — 표준 Redfish (Inspur OEM 영역 약함)

## lab 상태

- **부재** (사용자 명시 2026-05-01)
- Inspur 영문 docs 약함 — 가장 표준 가까운 응답 가정
- 사이트 도입 시 보정 의무 (NEXT_ACTIONS 등재됨)

## fixture 구성

| 파일 | 용도 |
|---|---|
| service_root.json | ServiceRoot — Vendor=Inspur |
| chassis_collection.json | Chassis collection |
| chassis_1.json | Chassis 1 — Model=NF5280M5 |
| chassis_1_power.json | Power (legacy path) |
| systems_collection.json | Systems collection |
| **system_1.json** | System 1 — `Oem.Inspur` 표준 form |
| **system_1_underscore_variant.json** | (variant) `Oem.Inspur_System` underscore form — collect_oem.yml fallback 분기 검증 입력 |
| managers_collection.json | Managers collection |
| manager_1.json | Manager 1 — ISBMC firmware 4.16.11 |
| update_service.json | UpdateService entry |
| firmware_inventory.json | Firmware Inventory collection |
| account_service.json | AccountService entry |

## OEM 영역 검증 입력

- `system_1.json` → `Oem.Inspur.SystemInfo` / `NetworkInfo` → primary path
- `system_1_underscore_variant.json` → `Oem.Inspur_System.SystemInfo` → fallback path
  (`redfish-gather/tasks/vendors/inspur/collect_oem.yml` 의 fallback 분기 검증)

## NP / SA series

NP / SA series (e.g., NP5280, SA5212) 별도 fixture 누락 — 사이트 도입 시 추가 의무.
