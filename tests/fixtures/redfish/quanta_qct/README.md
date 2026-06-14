# Quanta QCT BMC mock fixture — QuantaGrid D54Q-2U (OpenBMC base)

> M-F2 cycle 2026-05-07-all-vendor-coverage — lab 부재 vendor mock fixture.

## 메타

| 항목 | 값 |
|---|---|
| Vendor | Quanta Computer Inc. |
| Model | QuantaGrid D54Q-2U |
| BMC | OpenBMC base (Quanta QCT BMC) |
| Firmware | obmc-1.05 |
| Redfish version | 1.9.0 |
| OEM namespace | `Oem.Quanta_Computer_Inc` (System) / `Oem.OpenBmc` (Manager) |
| Lab | 부재 — web sources 기반 (rule 96 R1-A) |

## Sources

- https://www.qct.io/product/index/Server/rackmount-server/2U-Rackmount-Server/QuantaGrid-D54Q-2U
- https://www.exalit.com/storage/2023/09/D54Q-2U_v20230330.pdf (QuantaGrid D54Q-2U manual)
- https://www.hyperscalers.com/image/catalog/00-Products/Servers/QuantaGrid-D52BQ-2U-UG%202.0%20-%20HS.pdf
- https://catalog.redhat.com/en/hardware/system/detail/218837 (Red Hat 인증)
- https://bmc-toolbox.github.io/ (multi-vendor BMC abstraction reference)

## 특이점

- OpenBMC base — OEM 영역 일반적으로 약함 (정상)
- ODM 모델 (Microsoft Olympus / Open Compute Project / Meta) 은 customer-specific 변형 가능 (lab 도입 시 보정)
- Manager namespace: `Oem.OpenBmc` (OpenBMC base 시그니처)
- System namespace: `Oem.Quanta_Computer_Inc` (vendor 표기)
- 일부 펌웨어는 `Oem.QCT` (단축 표기) 변형 가능 — collect_oem.yml fallback

## 주요 endpoint

| File | Path | 비고 |
|---|---|---|
| service_root.json | `/redfish/v1/` | `Product: OpenBmc`, `Vendor: Quanta Computer` |
| chassis_collection.json | `/redfish/v1/Chassis` | Members 1 — `chassis` (OpenBMC 표준 ID) |
| chassis.json | `/redfish/v1/Chassis/chassis` | Model: QuantaGrid D54Q-2U |
| chassis_power.json | `/redfish/v1/Chassis/chassis/Power` | PSU 2개 (Delta) |
| systems_collection.json | `/redfish/v1/Systems` | Members 1 — `system` (OpenBMC 표준 ID) |
| system.json | `/redfish/v1/Systems/system` | `Oem.Quanta_Computer_Inc.QuantaSystemInfo` |
| managers_collection.json | `/redfish/v1/Managers` | Members 1 — `bmc` (OpenBMC 표준 ID) |
| manager.json | `/redfish/v1/Managers/bmc` | `Oem.OpenBmc` 시그니처 |

## 검증 포인트

- adapter 선택: `redfish_quanta_qct_bmc` (priority=80)
- OEM 추출 우선순위: `Oem.Quanta_Computer_Inc` → `Oem.QCT` → `Oem.OpenBmc` (collect_oem.yml — M-F1)
- Manager URI: `/redfish/v1/Managers/bmc` (OpenBMC 표준)
- System URI: `/redfish/v1/Systems/system` (OpenBMC 표준)

## 변형 가능성 (사이트 도입 시 정정)

- QuantaPlex (blade) series
- D52BQ-2U / T42S-2U 등 model 변형
- ODM customer 별 OEM 영역 (lab 도입 후 별도 fixture)
