# Dell iDRAC 8 fixture — M-H1 (cycle 2026-05-07)

> Lab 부재 — web sources only (rule 96 R1-A)

## 출처

- Sources: `https://developer.dell.com/apis/2978/versions/2/docs/`
- Generation: iDRAC8 (PowerEdge 13G) 2014-2018
- Tested against (web): iDRAC8 2.30+ / 2.50+ / 2.70+

## 시뮬레이션 시나리오

- ServiceRoot.RedfishVersion: "1.4.0" (DSP0268 v1.4+)
- BiosVersion 형식: "2.x.x"
- Standard storage path (Volumes 표준 미도입)
- Power deprecated path only (PowerSubsystem 미도입)
- Oem.Dell namespace

## 매칭 검증

- `dell_idrac8.yml` (priority=50) 매칭 — firmware_patterns "iDRAC.*8" / "^2\\."
- iDRAC9 (priority=100) 패턴 매치 안 됨
