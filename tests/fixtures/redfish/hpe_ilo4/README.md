# HPE iLO 4 fixture — M-H2 (cycle 2026-05-07)

> Lab 부재 — web sources only (rule 96 R1-A). Priority 2 fixture.

## 출처

- Sources: `https://hewlettpackard.github.io/ilo-rest-api-docs/ilo4/`
- Generation: iLO4 (ProLiant Gen9) 2014-2017

## 시뮬레이션 시나리오

- ServiceRoot.RedfishVersion: "1.0.0" (DSP0268 v1.0+)
- iLO version: "iLO 4 v2.77"
- Storage: SmartStorage only (legacy — 표준 Storage path 미지원)
- Power deprecated path only
- Oem.Hp namespace (iLO4 시기 — HPE rebrand 전)

## 매칭 검증

- `hpe_ilo4.yml` (priority=50) 매칭 — firmware_patterns "iLO.*4" / "^1\\.[0-9]"
- iLO5/6/7 패턴 매치 안 됨
