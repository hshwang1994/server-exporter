# HPE iLO 5 fixture — M-H2 (cycle 2026-05-07)

> Lab 부재 — web sources only (rule 96 R1-A). Priority 1 fixture.

## 출처

- Sources: `https://hewlettpackard.github.io/ilo-rest-api-docs/ilo5/`
- Generation: iLO5 (ProLiant Gen10 / Gen10 Plus) 2017-2022

## 시뮬레이션 시나리오

- ServiceRoot.RedfishVersion: "1.6.0" (DSP0268 v1.4+ ~ v1.6)
- iLO version: "iLO 5 v2.95"
- Storage: SmartStorage + Standard storage dual
- Power deprecated path only
- Oem.Hpe namespace (rebrand 후)

## 매칭 검증

- `hpe_ilo5.yml` (priority=90) 매칭 — firmware_patterns "iLO.*5" / "^2\\.[0-9]"
- iLO6 (priority=100) / iLO7 (priority=120) 패턴 매치 안 됨
