# Dell iDRAC 9 fixture (2026-05-07)

> 실장비(iDRAC9 7.x)에서 받은 fixture 는 `tests/fixtures/redfish/dell/` 에 있습니다. 검증 기록은 `docs/reference/live-validation.md` 를 보세요.
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
