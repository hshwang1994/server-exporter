# QA — pytest + redfish-probe + Baseline 회귀

## 적용 대상
- `tests/redfish-probe/**`, `tests/fixtures/**`, `schema/baseline_v1/**`, `tests/scripts/**`, `tests/evidence/**`
- pytest 테스트

## 목표 규칙

### R1. 테스트 분류

| 분류 | 위치 | 용도 |
|---|---|---|
| Live probe | `tests/redfish-probe/probe_redfish.py` | 실장비 검증 (Round) |
| Deep probe | `tests/redfish-probe/deep_probe_redfish.py` | 새 펌웨어 프로파일링 |
| Mock fixtures | `tests/fixtures/**` | Mock 회귀 입력 |
| Baseline | `schema/baseline_v1/**` | 회귀 기준선 |
| Evidence | `tests/evidence/**` | Round 검증 결과 |
| Scripts | `tests/scripts/conditional_review.py`, `os_esxi_verify.sh` | 보조 검증 |

### R2. 실장비 검증 절차 (Round)

1. probe_redfish.py 또는 채널별 검증 스크립트 실행
2. 결과를 `schema/baseline_v1/{vendor}_baseline.json`과 비교
3. 차이가 있으면:
   - 외부 시스템 변경 → baseline 갱신 (rule 13 R4) + evidence 기록
   - 코드 회귀 → 코드 수정
4. evidence 파일 (`tests/evidence/<날짜>-<vendor>-<펌웨어>.md`) 작성
5. docs/reference/decision-log.md 업데이트

### R3. pytest 명령

```bash
pytest tests/ -v
python tests/redfish-probe/probe_redfish.py --vendor dell
pytest tests/regression/ -k dell
```

### R4. 새 펌웨어 추가 시 deep_probe

- **Default**: 새 펌웨어 / 새 모델은 `probe-redfish-vendor` skill로 deep_probe 실행 → fixture + baseline 추가
- **Forbidden**: deep_probe 없이 새 펌웨어 baseline 작성

### R5. Schema 변경 후 baseline 회귀

- **Default**: rule 13 R1 3종 동반 갱신 후 영향 vendor baseline 전수 회귀
- **Forbidden**: schema 변경 + baseline 회귀 skip

### R6. pytest 회귀 통과 (커밋 전 로컬)

- **Default**: 모든 PR은 로컬 `pytest tests/e2e tests/regression` (+ `tests/integration -m "not live"`) 통과 — 영향 vendor baseline 회귀.
  2026-09-28 부터 Jenkins 에는 이 회귀 단계가 없다 (비운영 `Jenkinsfile` 삭제, rule 80 R1)
- **Forbidden**: 회귀 FAIL인 채로 머지

## 금지 패턴

- 실장비 검증 없이 baseline 갱신 — R2
- deep_probe 없이 새 펌웨어 — R4
- schema 변경 후 회귀 skip — R5
- pytest 회귀 FAIL 머지 — R6

## 리뷰 포인트

- [ ] Round 검증 evidence 첨부
- [ ] deep_probe 결과 (새 펌웨어 시)
- [ ] baseline 회귀 통과 (로컬 pytest)

## 관련

- rule: `13-output-schema-fields`, `21-output-baseline-fixtures`, `80-ci-jenkins-policy`
- skill: `prepare-regression-check`, `update-vendor-baseline`, `probe-redfish-vendor`, `run-baseline-smoke`
- agent: `qa-regression-worker`
- 정본: `docs/reference/live-validation.md`
