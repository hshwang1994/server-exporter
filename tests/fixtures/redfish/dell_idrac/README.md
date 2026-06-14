# Dell iDRAC (legacy iDRAC7) fixture — M-H1 (cycle 2026-05-07)

> Lab 부재 — web sources only (rule 96 R1-A)

## 출처

- Sources: `https://developer.dell.com/apis/2978/versions/1/docs/`
- Generation: iDRAC7 (PowerEdge 12G) 2010-2014
- Redfish: 미지원 또는 v1.0 부분 — SimpleStorage path 만

## 시뮬레이션 시나리오

- ServiceRoot.RedfishVersion: "1.0.0" (legacy)
- Systems → SimpleStorage 만 (Storage path 미지원)
- Power deprecated path only (PowerSubsystem 부재)

## 매칭 검증

- `dell_idrac.yml` (priority=10) 매칭 — generic fallback
- iDRAC9/iDRAC10 패턴 매치 안 됨 → fallback 경로 확인
