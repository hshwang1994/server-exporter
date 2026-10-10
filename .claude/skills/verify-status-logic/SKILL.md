---
name: verify-status-logic
description: build_status.yml 4 시나리오 매트릭스 (A/B/C/D) 정합 검증. server-exporter overall.status 판정 로직 (rule 13 R8 + cycle 2026-05-06 M-A 학습). 사용자가 "status 로직 검증", "errors 있는데 success?", "시나리오 매트릭스 확인" 등 요청 시 또는 build_status.yml / build_sections.yml / build_errors.yml 변경 후. - status 판정 의도 검증 / 사용자 의심 (시나리오 B 모순 의심) 재발 차단 / 새 시나리오 추가 시 매트릭스 갱신 / status 로직 정본 변경 후 회귀
---

# verify-status-logic

## 목적

server-exporter overall.status 판정 로직의 4 시나리오 매트릭스 (A/B/C/D) 정합 검증. M-A 학습 (cycle 2026-05-06) 형식화 — 사용자 의심 "errors 있는데 success 모순" 재발 차단.

## 입력

- 검증 대상: `common/tasks/normalize/build_status.yml` (정본) / `build_sections.yml` / `build_errors.yml`
- 동반 정본 4종: 코드 주석 + `docs/reference/decision-log.md` + `docs/contract/03-fields.md` + tests mock fixture

## 4 시나리오 매트릭스 정본

| # | 섹션 status | errors[] | overall.status | 의도 |
|---|---|---|---|---|
| A | 모두 success | empty | **success** | 정상 수집 |
| B | 모두 success | warnings | **success** | 의도된 동작 — 사유 추적용 분리 영역 |
| C | success + failed 혼재 | any | **partial** | 일부 실패 graceful degradation |
| D | 모두 failed | any | **failed** | 전수 실패 |

→ **시나리오 B**: section 자체는 정상 수집. errors[] 는 warning / partial enumeration / fallback 사용 통보용. envelope.errors[] 별도 검사로 호출자가 분리 인식.

## 검증 항목

1. **build_status.yml 코드 주석 매트릭스 일치** (rule 13 R8 정본):
   - 24~31 line 4 시나리오 표 존재
   - "errors[] 는 보지 않는다" 의도 명시
   - 시나리오 B 발생 위치 3 reference 명시 (gather_memory / gather_network / normalize_storage)

2. **판정 로직 정합** (인라인 Jinja2):
   ```
   supported_vals = sec_vals reject 'not_supported'
   if supported_vals == 0          → "failed"
   elif failed_count == 0          → "success"
   elif success_count == 0         → "failed"
   else                            → "partial"
   ```

3. **errors[] 분리 영역 보존** (rule 22 R7/R8 + rule 13 R5):
   - `_errors_fragment` 5 fragment 변수 정본 유지
   - severity (warning / error) 도입 안 함 (envelope shape 보존 — rule 96 R1-B)

4. **status 규칙 데이터 파일 없음**: 판정 규칙은 `build_status.yml` 인라인 Jinja2 하나다(`common/vars/status_rules.yml` 은 읽는 코드가 없어 2026-10-11 삭제)

5. **시나리오 B 재현 mock fixture 존재** (M-A3 commit `78611714`):
   - `tests/test_*status*.py` — 13건 회귀 (시나리오 A/B/C/D 모두)

6. **동반 정본 4 곳 일관성**:
   - `common/tasks/normalize/build_status.yml` 본문 주석
   - `docs/reference/decision-log.md` (M-A2 / 2026-05-06 결정)
   - `docs/contract/03-fields.md` (호출자 reference)
   - `tests/` mock fixture 13건

## 절차

1. **build_status.yml Read** — 24~31 line 매트릭스 + 39~42 line 시나리오 B 발생 위치 확인
2. **판정 로직 인라인 Jinja2** — 4 시나리오 결과 확인 (Mock evaluation)
3. **시나리오 B 발생 위치 3 reference 검증**:
   - `os-gather/tasks/linux/gather_memory.yml:171-175` (dmidecode fallback)
   - `os-gather/tasks/linux/gather_network.yml:208-209` (lspci stderr)
   - `esxi-gather/tasks/normalize_storage.yml:79-83` (NFS/vSAN/vVOL capacity 미수집)
4. **status 규칙 파일 부재** 확인 — `ls common/vars/status_rules.yml` 없음, `grep -r status_rules common/ *-gather/` 0 결과
5. **동반 정본 4 곳 일관성** — `docs/reference/decision-log.md` + `docs/contract/03-fields.md` + mock fixture diff
6. **회귀 — pytest tests/test_*status*.py** PASS

## 출력

```markdown
## status 로직 검증 결과 (rule 13 R8 + M-A 학습)

### 4 시나리오 매트릭스 정본: PASS
- build_status.yml 24~31 line 매트릭스 일치
- 시나리오 B 발생 위치 3 reference 명시 (gather_memory / gather_network / normalize_storage)
- "errors[] 는 보지 않는다" 의도 명시

### errors[] 분리 영역 보존: PASS
- _errors_fragment 5 fragment 변수 정본 유지
- severity 미도입 (envelope shape 보존)

### status 규칙 데이터 파일: 없음(정상)
- `common/vars/status_rules.yml` 삭제됨(2026-10-11), 판정은 build_status.yml 인라인만
- 명시 주석 "삭제 금지 / reserved" 유지

### 시나리오 B 재현 mock fixture: PASS
- tests/test_*status*.py — 13건 회귀

### 동반 정본 4 곳 일관성: PASS
- build_status.yml + `docs/reference/decision-log.md` + `docs/contract/03-fields.md` + tests mock 모두 일관

### 의심 발견: 0
```

## 적용 rule / 관련

- **rule 13 R8** (status 시나리오 매트릭스 동반 갱신 — 정본)
- rule 13 R5 (envelope 13 필드)
- rule 13 R7 (`docs/contract/03-fields.md` 동기화)
- rule 22 R7/R8 (5 fragment 변수 / 타입 정본)
- rule 92 R5 (schema 변경 사용자 승인)
- rule 96 R1-B (envelope shape 보존 — 호환성 외 schema 확장 금지)
- skill: `verify-json-output`, `validate-fragment-philosophy`, `update-output-schema-evidence`
- agent: `schema-reviewer`
- script: `scripts/ai/hooks/pre_commit_status_logic_check.py` (advisory)
- 정본 코드: `common/tasks/normalize/build_status.yml`
- 정본 결정: `docs/reference/decision-log.md` (M-A2 / 2026-05-06)
- 정본 reference: `docs/contract/03-fields.md`
- 회귀 fixture: M-A3 commit `78611714` (13건)
