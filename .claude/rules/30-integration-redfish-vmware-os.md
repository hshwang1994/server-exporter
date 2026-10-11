---
paths:
  - "redfish-gather/**"
  - "os-gather/**"
  - "esxi-gather/**"
---
# 외부 시스템 통합 — Redfish / IPMI / SSH / WinRM / vSphere

## 적용 대상
- 외부 시스템 응답 처리 코드
- `redfish-gather/library/redfish_gather.py`
- `os-gather/`, `esxi-gather/` 의 외부 호출

## 외부 시스템 list

| 시스템 | 채널 | 라이브러리 | 인증 |
|---|---|---|---|
| Redfish API | redfish-gather | stdlib (urllib/ssl/json) | Basic Auth (표준 계정 `vault/common/redfish/standard.yml` 전역 · 복구 계정 `vault/<loc>/redfish/<vendor>.yml`) |
| IPMI | (현재 사용 안 함, 향후 fallback) | — | — |
| SSH | os-gather Linux | paramiko (Ansible 내부) | key 또는 password (vault/<loc>/os/linux.yml) |
| WinRM | os-gather Windows | pywinrm 0.5.0 | NTLM/Basic (vault/<loc>/os/windows.yml) |
| vSphere | esxi-gather | pyvmomi 9.0.0, community.vmware 6.2.0 | password (vault/<loc>/esxi.yml) |

## 목표 규칙

### R1. 외부 응답 신뢰 금지

- **Default**: 외부 시스템 응답 (JSON / XML / 명령 출력)을 직접 fragment에 넣지 말 것. 정규화 단계 (`normalize_*.yml`) 거쳐야 함
- **Forbidden**: `set_fact: _data_fragment: "{{ redfish_response.json }}"` 같은 직접 dump
- **Why**: 외부 응답 형식 변경 시 envelope 깨짐

### R2. HTTPS verify 정책

- **Default**: Redfish는 자체 서명 인증서 환경이 일반적 → `verify=False` 허용. 단 코드에 의도 명시 주석 (cycle-011 보안 정책 해제 후에도 트레이스 차원 유지)
- **Forbidden**: verify 정책 명시 없이 random fallback

### R3. Timeout

- **Default**: 모든 외부 호출에 timeout 명시 (Redfish 30초, SSH 10초, WinRM 30초)
- **Forbidden**: timeout 없는 호출 (Agent 무한 대기)

### R4. 외부 응답 schema drift 대응 (rule 96 연동)

- **Default**: Redfish path / IPMI sensor / SSH 명령 출력 형식이 펌웨어 업그레이드로 변경 가능 → adapter YAML metadata에 origin 주석
- 상세: rule 96 (external-contract-integrity)

### R5. callback URL POST는 rule 31

호출자에게 결과 통지 = rule 31 (integration-callback) 영역.

## 금지 패턴

- 외부 응답을 fragment에 직접 넣음 — R1
- HTTPS verify 정책 묵시 — R2
- timeout 없는 외부 호출 — R3

## 리뷰 포인트

- [ ] 외부 응답이 normalize 거쳐 fragment로
- [ ] verify 정책 명시
- [ ] timeout 설정

## 관련

- rule: `12-adapter-vendor-boundary`, `27-precheck-guard-first`, `31-integration-callback`, `96-external-contract-integrity`
- 정본: `.claude/ai-context/external/integration.md`
