# Huawei iBMC 2.x mock fixture — FusionServer Pro RH2288 V5

> cycle 2026-05-11 M-C3 — lab 부재 web sources 기반 (rule 96 R1-A)

## Vendor

- Manufacturer: Huawei (`Huawei` / `Huawei Technologies Co., Ltd.`)
- Model: RH2288 V5 (FusionServer Pro 시리즈)
- iBMC generation: 2.x (2016-2019, DSP0268 v1.4+, Oem.Huawei 강화)
- BMC firmware: iBMC 2.85
- Manager URI: `/redfish/v1/Managers/iBMC`

## Web sources (rule 96 R1-A)

- https://support.huawei.com/enterprise/en/doc/EDOC1000163550/41dfb258/ibmc
- https://github.com/Huawei/Huawei-iBMC-Cmdlets (Huawei 공식 PowerShell repo)
- https://networktelecom.ru/images/data/gallery/3071_9834_Huawei-FusionServer-Pro-V5-Rack-Server-Data-Sheet.pdf
- https://manualzz.com/doc/o/1wk3dz/huawei-fusionserver-pro-2288h-v5-user-manual-9.2-logging-in-to-the-ibmc-webui
- DMTF Redfish DSP0268 v1.4 — https://redfish.dmtf.org/schemas/v1/

## lab 상태

- **부재** (사용자 명시 2026-05-01)
- web sources 만으로 응답 형식 가정 — 사이트 fixture 도입 시 보정 의무
- NEXT_ACTIONS 등재됨 (rule 50 R2 단계 10 / rule 96 R1-C)

## fixture 구성

| 파일 | 용도 |
|---|---|
| service_root.json | ServiceRoot — Vendor 식별 (Manufacturer=Huawei) |
| chassis_collection.json | Chassis collection index |
| chassis_1.json | Chassis 1 — Manufacturer + Oem.Huawei.BoardInfo |
| chassis_1_power.json | Power (legacy path — iBMC 2.x) |
| systems_collection.json | Systems collection index |
| system_1.json | System 1 — Oem.Huawei.{SystemHealth,SystemInfo,NetworkBindings,SmartProvisioning} |
| managers_collection.json | Managers collection index |
| manager_iBMC.json | Manager iBMC — firmware 2.85 |
| update_service.json | UpdateService entry |
| firmware_inventory.json | Firmware Inventory collection |
| firmware_iBMC.json | iBMC firmware entry |
| account_service.json | AccountService entry |

## OEM 영역 검증 입력

`system_1.json` → `Oem.Huawei.SystemInfo` / `SmartProvisioning` / `NetworkBindings` →
`redfish-gather/tasks/vendors/huawei/collect_oem.yml` → `_data_fragment.bmc.oem_huawei.*`
