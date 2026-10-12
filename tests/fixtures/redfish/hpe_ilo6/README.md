# HPE iLO 6 fixture (2026-05-07)

> 실장비(DL380 Gen11)에서 받은 fixture 는 `tests/fixtures/redfish/hpe/` 에 있습니다. 검증 기록은 `docs/reference/live-validation.md` 를 보세요.
> 본 fixture 는 Storage standard + SmartStorage fallback / PowerSubsystem dual 변형 시뮬.

## 출처

- Sources: `https://hewlettpackard.github.io/ilo-rest-api-docs/ilo6/`
- Generation: iLO6 (ProLiant Gen11) 2022-2024

## 시뮬레이션 시나리오

- ServiceRoot.RedfishVersion: "1.10.0" (DSP0268 v1.10+)
- iLO version: "iLO 6 v1.51"
- Storage: standard storage 우선 + SmartStorage fallback
- Power + PowerSubsystem dual
- Oem.Hpe namespace

## 매칭 검증

- `hpe_ilo6.yml` (priority=100) 매칭 — firmware_patterns "iLO.*6" / "^1\\.[5-9]"
- iLO7 (priority=120) 패턴 매치 안 됨 (3-part version)
