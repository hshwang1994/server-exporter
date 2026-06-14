# Lenovo BMC (legacy IBM xSeries BMC / IMM) fixture — M-H3 (cycle 2026-05-07)

> Lab 부재 — web sources only (rule 96 R1-A). Legacy generation.

## 출처

- Sources: IBM xSeries archive (legacy BMC / IMM 1세대)
- Generation: BMC legacy (IBM xSeries) 2007-2014
- History: IBM 시기 — Manufacturer aliases 에 "IBM" 포함

## 시뮬레이션 시나리오

- Redfish 미지원 시뮬: service_root.json 부재 또는 HTTP 404
- IPMI only — precheck protocol 단계에서 graceful 실패
- 본 디렉터리는 README + 부재 fixture (graceful degradation 회귀용)

## 매칭 검증

- 정상 service_root 응답 없음 → precheck protocol fail
- vendor 추출 불가 → `lenovo_bmc.yml` generic fallback (priority=10) 도 미매칭
- diagnosis.protocol_unsupported 시나리오
