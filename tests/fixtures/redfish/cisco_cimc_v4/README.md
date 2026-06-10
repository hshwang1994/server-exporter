# Cisco CIMC 4.x (UCS C-series M5/M6) fixture

> Lab 검증된 fixture `tests/fixtures/redfish/cisco/` (CIMC 4.1) 와 동일 generation.
> 본 fixture 는 CIMC 4.x 신 펌웨어 (PowerSubsystem 일부 도입) 변형 시뮬.

## 출처

- Sources: `https://www.cisco.com/c/en/us/td/docs/unified_computing/ucs/c/sw/api/4_3/`
- Generation: CIMC 4.x (UCS C-series M5/M6) 2020-2022
- Lab tested 4.1

## 시뮬레이션 시나리오

- ServiceRoot.RedfishVersion: "1.10.0" (DSP0268 v1.10+)
- Manufacturer: "Cisco Systems Inc."
- Standard storage path
- PowerSubsystem 일부 도입 (Power deprecated 와 dual)
- OEM strategy: standard_only

## 매칭 검증

- `cisco_cimc.yml` (priority=100) 매칭 — firmware_patterns "^[4-6]\\." 매치
- model_patterns "UCSC-C[0-9]+[ -]M[4-8]" / "C240[ -]M[4-8]" 매칭 (실제 fixture Model: `UCSC-C240-M6L`)

## 기존 lab fixture

- `tests/fixtures/redfish/cisco/` (CIMC 4.1 / M4 + 0x4.1 펌웨어 — Q1~Q7 quirks 적용 확정)
