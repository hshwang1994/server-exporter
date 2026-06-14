# Lenovo IMM2 fixture — M-H3 (cycle 2026-05-07)

> Lab 부재 — web sources only (rule 96 R1-A).

## 출처

- Sources: `https://pubs.lenovo.com/imm2/` / IBM System x archive
- Generation: IMM2 (System x M5) 2014-2017
- History: IBM IMM2 → Lenovo IMM2 (2014 인수 후)

## 시뮬레이션 시나리오

- ServiceRoot.RedfishVersion: "1.0.2" (DSP0268 v1.0+, IMM2 시기)
- Manufacturer: "Lenovo" (IBM 인수 후. legacy 시스템은 "IBM" 가능)
- Storage: SimpleStorage path (IMM2 일부 펌웨어 — Volumes/Storage 미지원)

> 이 fixture 는 최소 구성이다 (`service_root.json` + `system.json` 2개). system.json 에는 Oem 블록이 없고 Power/chassis fixture 도 없다 — vendor/firmware detection 검증용 최소 쌍.

## 매칭 검증

- `lenovo_imm2.yml` (priority=50) 매칭 — firmware_patterns "IMM2"
- XCC / XCC3 패턴 매치 안 됨
