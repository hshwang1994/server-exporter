---
name: classify-precheck-layer
description: 새 검증을 어느 layer (Jenkins Stage 1 / precheck 1-4 / Stage 3 / adapter capabilities)에 배치할지 분류 (rule 27 R5). 사용자가 "이 검증 어디에 넣지?", "precheck 단계 분류", "validation layer" 등 요청 시. - 새 입력 검증 / 새 graceful degradation 단계 / Validator 작성 / "어느 단계에서 막을까?" 같은 질의 (server-exporter는 호출자/Stage1)
---

# classify-precheck-layer

## 목적

server-exporter의 검증 / 차단 logic을 적절한 layer에 배치. 너무 늦으면 시간 낭비, 너무 이르면 graceful degradation 무력화.

## Layer 분류 (rule 27 R5)

| Layer | 위치 | 검증 종류 |
|---|---|---|
| 1. Jenkins Stage 1 (Validate) | Jenkinsfile | 입력 형식 (JSON 파싱 / IP 형식 / target_type 값) |
| 2a. precheck 도달 | precheck_bundle.py | 호스트 도달성 (관리 TCP 응답 OR ICMP Echo 응답) |
| 2b. precheck port | precheck_bundle.py | target_type별 port 응답 (SSH 22 / WinRM 5985-5986 / vSphere 443 / Redfish 443) |
| 2c. precheck protocol | precheck_bundle.py | TCP 응답 + 첫 응답 형식 |
| 2d. precheck auth | precheck_bundle.py | 자격증명 인증 |
| 3. adapter capabilities | adapters/{channel}/{vendor}_*.yml | vendor-specific 비즈니스 규칙 (예: "이 펌웨어는 Volumes endpoint 미지원") |
| 4. gather 중 graceful degradation | gather_*.yml | 일부 endpoint 실패 → 가능한 데이터만 + errors 기록 |
| 5. Jenkins Stage 3 (Validate Schema) | Jenkinsfile + output_schema_drift_check | envelope 13 필드 / field_dictionary 정합 |
| 6. Jenkins Stage 4 (E2E Regression) | Jenkinsfile + pytest | baseline 회귀 |

## 분류 판단 질문 (Q1-Q3)

| Q | 답 | layer |
|---|---|---|
| Q1: 외부 시스템 호출 없이 판정 가능? | YES → 입력 형식 / payload 검증 | Stage 1 |
| | NO → 외부 의존 | precheck (2a-2d) |
| Q2: vendor 자동 감지 후에야 적용 가능? | YES → vendor 결정 후 | adapter capabilities (3) |
| | NO → vendor agnostic | precheck 또는 gather (2/4) |
| Q3: 출력 envelope 형식 검증? | YES | Stage 3 (5) |
| | NO → 데이터 무결성 | Stage 4 baseline (6) |

## 출력

```markdown
## 검증 layer 분류 — <검증 항목>

### Q1-Q3 답
- Q1: NO (외부 의존)
- Q2: YES (vendor 자동 감지 후만 적용)
- Q3: NO

### 권장 layer: 3 (adapter capabilities)

### 이유
- 펌웨어 5.x 미만은 Volumes endpoint 미지원 — vendor + 펌웨어 결정 후 분기 가능
- adapter dell_idrac9.yml의 capabilities에 `volumes_endpoint: ">=5.0"` 추가

### 대안 (기각)
- precheck protocol에 추가 → vendor 모르고 분기 불가
- gather 중 try/except → silent degradation 위험 (rule 95 R1 #8)
```

## 적용 rule / 관련

- **rule 27** (precheck-guard-first) R5 정본
- rule 12 (adapter-vendor-boundary)
- rule 95 R1 (silent degradation 의심)
- skill: `debug-precheck-failure`, `task-impact-preview`
- agent: `precheck-engineer`
- 정본: `docs/contract/04-failure-and-diagnosis.md`
