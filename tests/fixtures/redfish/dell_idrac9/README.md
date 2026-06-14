# Dell iDRAC 9 fixture — M-H1 (cycle 2026-05-07)

> Round 11 lab 검증 (iDRAC9 7.x — `tests/fixtures/redfish/dell/`).
> 본 fixture 는 iDRAC9 5.x (PLDM RDE + standard dual) 변형 시뮬 — web sources only.

## 출처

- Sources: `https://developer.dell.com/apis/2978/versions/3/docs/`
- Generation: iDRAC9 (PowerEdge 14G/15G/16G) 2017-2024
- Storage strategy evolution:
  - 3.x-4.x: standard storage path
  - 5.x: PLDM RDE 우선 + standard fallback (본 fixture)
  - 6.x+: PLDM RDE only

## 시뮬레이션 시나리오

- ServiceRoot.RedfishVersion: "1.13.0" (iDRAC9 5.x 시기 DSP0268)
- BiosVersion 형식: "2.x.x"
- Standard storage path 응답 (5.x dual 모드)
- Power + PowerSubsystem dual
- Oem.Dell namespace

## 매칭 검증

- `dell_idrac9.yml` (priority=100) 매칭 — firmware_patterns "iDRAC.*9" / "^[4-7]\\."
- iDRAC10 (priority=120) 패턴 매치 안 됨
