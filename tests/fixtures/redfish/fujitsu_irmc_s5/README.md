# Fujitsu iRMC S5 mock fixture — PRIMERGY RX2540 M5

> M-E3 cycle 2026-05-07-all-vendor-coverage — lab 부재 vendor mock fixture.

## 메타

| 항목 | 값 |
|---|---|
| Vendor | Fujitsu (FUJITSU) |
| Model | PRIMERGY RX2540 M5 |
| BMC | iRMC S5 |
| Firmware | iRMC S5 4.21F sdr 3.62 |
| Redfish version | 1.8.0 |
| OEM namespace | `Oem.ts_fujitsu` (primary) |
| Lab | 부재 — web sources 기반 (rule 96 R1-A) |

## Sources

- https://github.com/fujitsu/iRMCtools
- https://github.com/fujitsu/iRMC-REST-API
- https://manualzz.com/doc/37690590/irmc-restful-api-v5.0---fujitsu-manual-server (iRMC S5 RESTful API Spec)
- https://docs.ts.fujitsu.com/dl.aspx?id=a5785619-b9c4-448b-9438-00d54f5d0884 (iRMC S5 Login docs)
- https://support.ts.fujitsu.com/IndexDownload.asp (iRMC S5 User Guide 진입점)
- https://mmurayama.blogspot.com/2018/05/fujitsu-irmc-redfish-examples.html

## 주요 endpoint

| File | Path | 비고 |
|---|---|---|
| service_root.json | `/redfish/v1/` | `Product: iRMC S5`, `Oem.ts_fujitsu` 명시 |
| chassis_collection.json | `/redfish/v1/Chassis` | Members 1 |
| chassis.json | `/redfish/v1/Chassis/0` | Model: PRIMERGY RX2540 M5 |
| chassis_power.json | `/redfish/v1/Chassis/0/Power` | PSU 2개 (legacy Power schema, S5 generation) |
| systems_collection.json | `/redfish/v1/Systems` | Members 1 |
| system.json | `/redfish/v1/Systems/0` | `Oem.ts_fujitsu.FtsSystemInfo` 포함 |
| managers_collection.json | `/redfish/v1/Managers` | Members 1 |
| manager.json | `/redfish/v1/Managers/iRMC` | `Oem.ts_fujitsu.FTSiRMCInfo` 포함 |
| update_service.json | `/redfish/v1/UpdateService` | |
| firmware_inventory.json | `/redfish/v1/UpdateService/FirmwareInventory` | iRMC + BIOS 2 entries |
| account_service.json | `/redfish/v1/AccountService` | |

## 검증 포인트

- vendor 감지: `Fujitsu` / `FUJITSU` → `fujitsu`
- adapter 선택: `redfish_fujitsu_irmc` (priority=80)
- OEM namespace: `Oem.ts_fujitsu` 추출 (collect_oem.yml — M-E2)
- generation: iRMC S5 (대표 generation)
- Power schema: legacy (S5 는 PowerSubsystem 미도입 — S6 에서 도입)

## 변형 가능성 (사이트 도입 시 정정)

- `Oem.Fujitsu` (단순 표기 변형) — collect_oem.yml fallback
- iRMC S2: Redfish 미지원 가능 (별도 mock 필요 시 service_root.json 만)
- iRMC S6: PowerSubsystem 도입 (`fujitsu_irmc_s6/` 디렉터리에 별도)
- PRIMEQUEST: mission-critical, `Oem.ts_fujitsu.PartitionInfo` 가능
