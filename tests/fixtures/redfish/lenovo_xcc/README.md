# Lenovo XCC (XCC1 + XCC2) fixture — M-H3 (cycle 2026-05-07)

> Round 11 lab 검증 (XCC1 V2 — `tests/fixtures/redfish/lenovo/`).
> 본 fixture 는 XCC2 (ThinkSystem V3) 변형 시뮬 — web sources only.

## 출처

- Sources: `https://pubs.lenovo.com/xcc/` / `https://lenovopress.lenovo.com/lp1604-lenovo-xclarity-controller-xcc`
- Generation: XCC2 (ThinkSystem V3) 2020-2024

## 시뮬레이션 시나리오 (의도)

- ServiceRoot.RedfishVersion: "1.17.0" (DSP0268 v1.10+, XCC2 시기) — `service_root.json` 에 수록
- XCC version: "TAOT 3.10" (XCC2 V3 모델 펌웨어 prefix) — manager FirmwareVersion 의도값
- Standard storage path
- Oem.Lenovo namespace

> 이 fixture 는 최소 구성이다 (`service_root.json` + `system.json` 2개, `manager.json` 없음). 따라서 "TAOT 3.10" firmware / Power 항목은 의도한 변형이며 fixture 에 전부 수록되진 않았다 — vendor/firmware detection 검증용 최소 쌍.

## HTTP 헤더 정책 (rule 25 R7-A-1)

- cycle 2026-04-30 사이트 사고 — Accept + OData-Version + User-Agent reject
- "Accept만" hotfix 적용 (redfish_gather.py _get())
- XCC1 / XCC2 모두 보수적 정책

## 매칭 검증

- `lenovo_xcc.yml` (priority=100) 매칭 — firmware_patterns "XCC" / "TAOT*"
- model_patterns "ThinkSystem.*V3" 매칭
- XCC3 (priority=120) 패턴 (firmware "XCC3" / "ThinkSystem.*V4") 매치 안 됨
