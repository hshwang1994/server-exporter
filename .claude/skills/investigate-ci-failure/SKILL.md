---
name: investigate-ci-failure
description: Jenkins 빌드 / 테스트 실패 로그 분석. 4-Stage 어디서 실패했는지 + 원인 + 수정 방향. 사용자가 "Jenkins 빌드 깨졌어", "파이프라인 실패", "왜 실패?" 등 요청 시. - Jenkins Stage FAIL / 빌드 console log 분석 필요
---

# investigate-ci-failure

## 목적

server-exporter Jenkins 실패 분석. 파이프라인은 `Jenkinsfile_portal`(5 stage, 운영) 하나다 — 비운영 `Jenkinsfile` 과 `Jenkinsfile_portal_test` 는 2026-09-28 에 삭제됐다. Gather · Validate Schema 의 `[venv] ...` 실패는 `scripts/activate_ansible_venv.sh` 의 진단 줄을 본다.

## 4-Stage 실패 패턴

| Stage | 일반 실패 원인 |
|---|---|
| 1. Validate | 입력 형식 오류 (target_type 잘못 / inventory_json 파싱 실패 / IP 형식) |
| 2. Gather | precheck 실패 / vault 자격증명 stale / 외부 시스템 응답 변경 / fragment 침범 |
| 3. Validate Schema | sections.yml ↔ field_dictionary 정합 위반 / Must 필드 누락 / output envelope 13 필드 위반 |
| 4. E2E Regression | baseline 회귀 실패 (외부 시스템 변경 / 코드 회귀 / fixture stale) |
| Post (callback) | callback URL 무결성 (공백/슬래시) / 호출자 시스템 다운 |

## 절차

1. **Jenkins console log 수집** (Jenkins UI 또는 `gh run view`)
2. **Stage 식별**: 어느 Stage에서 실패
3. **Stage별 분석**:
   - Stage 1: 입력 spec (`docs/contract/01-input.md`) 비교
   - Stage 2: ansible -vvv 로그 + precheck 진단 (debug-precheck-failure skill)
   - Stage 3: output_schema_drift_check.py 결과
   - Stage 4: 영향 vendor baseline diff
4. **근본 원인 가설** + 검증 방법 제시
5. **수정 방향**: 코드 / vault / Jenkinsfile / fixture
6. **rule 95 R2 (개발자 답변 검증)**: 사용자 / 운영자 답변도 commit log 교차 확인

## 출력

```markdown
## Jenkins 실패 분석 — Build #1234

### 실패 Stage: 4 (E2E Regression)

### 원인 (가설)
- HPE iLO5 2.x 펌웨어 응답에 새 필드 등장
- baseline_v1/hpe_ilo5_baseline.json과 diff 발생

### 증거
- Jenkins log: `tests/regression/test_cross_channel_consistency.py::test_envelope_fields[hpe] FAILED`
- diff: storage.controllers[0].vendor 필드 누락

### 수정 방향
1. probe-redfish-vendor로 펌웨어 응답 재프로파일링
2. update-vendor-baseline으로 baseline 갱신
3. PR 머지 후 재빌드

### 만약 코드 회귀라면
- recent commit list: HEAD~5..HEAD
- adapter dell_idrac9.yml 또는 hpe_ilo5.yml 최근 변경 검토
```

## 적용 rule / 관련

- **rule 80** (ci-jenkins-policy) 정본
- rule 95 R1 R2 (의심 패턴 + 개발자 답변 검증)
- skill: `debug-precheck-failure`, `debug-external-integrated-feature`, `update-vendor-baseline`, `task-impact-preview`
- agent: `ci-failure-investigator`, `qa-regression-worker`
- 정본: `docs/operate/04-pipeline-runtime.md`
