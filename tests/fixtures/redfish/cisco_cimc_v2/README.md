# Cisco CIMC 2.x (UCS C-series M4) fixture — M-H4 (cycle 2026-05-07)

> Lab 부재 — web sources only (rule 96 R1-A). Priority 2 fixture.

## 출처

- Sources: Cisco UCS C-series API guide (CIMC 2.x)
- Generation: CIMC 2.x (UCS C-series M4 — Broadwell-EP) 2014-2017

## 시뮬레이션 시나리오

- ServiceRoot.RedfishVersion: "1.4.0" (DSP0268 v1.4+)
- Manufacturer: "Cisco Systems Inc."
- Standard storage path (CIMC 2.30+ 부터 Storage 표준)
- Power deprecated only

## 매칭 검증

- 본 fixture 의 펌웨어 "2.0(13)" 는 `^[4-6]\\.` 에 미매치 → `cisco_bmc.yml` (priority=10) fallback
- M4 시기는 CIMC 2.x 대표적 → cisco_cimc.yml 의 model_patterns "C220 M4" 매칭은 가능하나 firmware 미매치
- 기존 lab 검증된 fixture `tests/fixtures/redfish/cisco/` 는 CIMC 4.1 (M4 신 펌웨어). 본 디렉터리는 M4 출시 초기 시뮬

## 주의

- CIMC 2.x는 Redfish 1.4+ 표준 도입 시기로 응답 형식 호환성 변동 큼
- lab 도입 후 별도 cycle (real CIMC 2.x 응답 확정)
