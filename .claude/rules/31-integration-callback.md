---
paths:
  - "Jenkinsfile_portal"
  - "Jenkinsfile_portal_Byid"
  - "scripts/jenkins/**"
---
# Callback URL 무결성

## 적용 대상
- 호출자 통보용 callback URL 처리
- `Jenkinsfile_portal` 의 Callback stage (운영 경로)

## 현재 관찰된 현실

- 호출자가 Jenkins Job 트리거 시 callback URL 전달
- 4-Stage 완료 후 결과 통지 (POST + JSON envelope)
- 이전 commit `4ccc1d7`에서 공백/후행 슬래시 방어 fix

## 목표 규칙

### R1. URL 정규화 의무

- **Default**: callback URL 사용 전 정규화:
  ```python
  url = url.strip().rstrip('/')
  ```
- **Forbidden**: 입력 URL을 그대로 사용
- **Why**: commit 4ccc1d7 이전 사고 — 공백/후행 슬래시로 잘못된 endpoint POST → 실패

### R2. POST 실패 처리

- **Default**: callback POST 실패 시 Jenkins 빌드는 성공으로 유지하되 console log에 명시
- **Allowed**: 일부 재시도 (1~3회, exponential backoff)
- **Forbidden**: callback 실패로 빌드 자체를 fail (수집 자체는 성공했는데 통보만 실패)

### R3. payload 무결성

- **Default**: callback payload는 `callback_plugins/json_only.py` 출력 envelope 그대로 (rule 20)
- **Forbidden**: callback 단계에서 envelope 수정/추가
- **Why**: 호출자 시스템과의 계약 안정성

### R4. 보안 — URL에 자격증명 포함 금지

- **Default**: callback URL은 path 기반 인증 (예: `/api/notify/<job_id>?token=<token>`)
- **Forbidden**: `https://user:pass@host/...` 형식
- **Why**: Jenkins console log에 노출

## 금지 패턴

- URL 정규화 skip — R1
- callback 실패로 빌드 fail — R2
- callback 단계에서 envelope 수정 — R3
- URL에 평문 자격증명 — R4

## 리뷰 포인트

- [ ] URL 정규화 (strip + rstrip /)
- [ ] callback 실패 처리 graceful
- [ ] payload 무수정
- [ ] URL 자격증명 형식 안 씀

## 관련

- rule: `20-output-json-callback`, `80-ci-jenkins-policy` (cycle-011: rule 60 보안 정책 해제됨)
- 정본: commit 4ccc1d7
