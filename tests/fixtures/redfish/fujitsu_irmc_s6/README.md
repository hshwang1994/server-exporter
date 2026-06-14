# Fujitsu iRMC S6 mock fixture — PRIMERGY RX2540 M7

> M-E3 cycle 2026-05-07-all-vendor-coverage — lab 부재 vendor mock fixture (최신 generation).

## 메타

| 항목 | 값 |
|---|---|
| Vendor | Fujitsu (FUJITSU) |
| Model | PRIMERGY RX2540 M7 |
| BMC | iRMC S6 |
| Firmware | iRMC S6 1.20F sdr 1.10 |
| Redfish version | 1.13.0 |
| OEM namespace | `Oem.ts_fujitsu` (primary) |
| PowerSubsystem | YES (S6 도입) |
| Lab | 부재 — web sources 기반 (rule 96 R1-A) |

## Sources

- https://support.ts.fujitsu.com/IndexDownload.asp (iRMC S6 User Guide 진입점)
- https://www.fujitsu.com/global/products/computing/servers/primergy/ (PRIMERGY M7 라인업)
- https://redfish.dmtf.org/schemas/v1/PowerSubsystem_v1.xml (DSP0268 v1.10+ PowerSubsystem)

## iRMC S5 vs S6 차이 (web sources)

| 항목 | S5 | S6 |
|---|---|---|
| DSP0268 spec | v1.6+ | v1.10+ |
| OEM 강도 | 강화 | 강화 + |
| PowerSubsystem | 미도입 (legacy Power) | 도입 |
| ThermalSubsystem | 미도입 | 도입 |
| PRIMERGY generation | M5 | M6/M7 |

## 주요 endpoint

| File | Path | 비고 |
|---|---|---|
| service_root.json | `/redfish/v1/` | `Product: iRMC S6`, RedfishVersion 1.13.0 |
| chassis.json | `/redfish/v1/Chassis/0` | Model: PRIMERGY RX2540 M7, `PowerSubsystem` link |
| chassis_powersubsystem.json | `/redfish/v1/Chassis/0/PowerSubsystem` | S6 신규 도입 영역 |
| system.json | `/redfish/v1/Systems/0` | `Oem.ts_fujitsu.FtsSystemInfo` |
| manager.json | `/redfish/v1/Managers/iRMC` | `PowerSubsystemSupported: true` |

## 검증 포인트

- adapter 선택: `redfish_fujitsu_irmc` (firmware_patterns: `iRMC*S6*` 매칭 — M-E1)
- PowerSubsystem 도입 — `capabilities.power_subsystem: "conditional"` 분기 활성
- OEM namespace `Oem.ts_fujitsu` 추출 (M-E2)
