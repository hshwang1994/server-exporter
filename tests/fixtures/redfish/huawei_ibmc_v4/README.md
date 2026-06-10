# Huawei iBMC 4.x mock fixture — FusionServer Pro V6

> Lab 부재 web sources 기반

## Vendor

- Manufacturer: Huawei
- Model: 2288H V6 (FusionServer Pro V6)
- iBMC generation: 4.x (2021-2023, DSP0268 v1.10+, **PowerSubsystem 완전 지원**)
- BMC firmware: iBMC 4.12

## 핵심 차이 (vs iBMC 2.x)

| 항목 | iBMC 2.x | iBMC 4.x |
|---|---|---|
| Power path | legacy `/Power` | **PowerSubsystem** (이 fixture 는 `chassis_1_powersubsystem.json` 만 수록; legacy `/Power` 병행은 펌웨어 의존, fixture 미수록) |
| Storage | standard | standard |
| OEM | Oem.Huawei 강화 | 표준 가까움 + Oem.Huawei 유지 |

## Web sources

- Huawei iBMC 4.x Redfish API guide (확인 2026-05-07)
- DMTF DSP0268 v1.10 — PowerSubsystem schema

## lab 상태

- **부재** — 사이트 fixture 도입 시 보정 의무
