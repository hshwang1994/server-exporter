# Huawei Atlas 800 mock fixture — AI training server

> cycle 2026-05-11 M-C3 — lab 부재 web sources 기반 (rule 96 R1-A)

## Vendor

- Manufacturer: Huawei
- Model: Atlas 800 (AI training server)
- iBMC generation: 5.x (2023+, DSP0268 v1.13+)
- BMC firmware: iBMC 5.06
- Platform: AI compute (Ascend 910 accelerator x8)

## 핵심 차이 (vs FusionServer Pro)

- Oem.Huawei.AIComputeInfo 추가 (accelerator metadata)
- ARM64 Kunpeng CPU (vs Intel Xeon)
- 더 큰 메모리 / 전력 (1TB / 2400W accelerator)

## Web sources

- https://www.huawei.com/en/products/cloud-computing-dc/atlas (확인 2026-05-07)
- iBMC 5.x Redfish API guide
- DMTF DSP0268 v1.13

## lab 상태

- **부재** — AI 서버는 lab 도입 가능성 낮음. 사이트 도입 시 보정 의무
