# Cisco BMC (legacy UCS C-series Standalone BMC) fixture — M-H4 (cycle 2026-05-07)

> Lab 부재 — web sources only (rule 96 R1-A). Legacy generation.

## 출처

- Sources: Cisco UCS C-series Standalone archive
- Generation: BMC legacy (UCS C-series 1세대 Standalone) 2009-2014

## 시뮬레이션 시나리오

- Redfish 미지원 또는 v1.0 부분 — IPMI / xml-api 우선
- 본 디렉터리는 README + 부재 fixture (graceful degradation 회귀용)

## 매칭 검증

- 정상 service_root 응답 없음 또는 부분 → precheck protocol 단계 graceful
- `cisco_bmc.yml` generic fallback (priority=10) 매칭
- cisco_cimc.yml priority=100 패턴 매치 안 됨 (firmware "^[4-6]\\.")
