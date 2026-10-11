---
paths:
  - "docs/ai/tickets/**"
---
# 다중 세션 운영 가이드

> 꼭 필요한 경우에만 별도 Claude CLI 세션. 기본은 단일 세션 + Agent tool 병렬 (rule 25).

## 규칙 표기 구조

본 rule의 각 항목은 **Default / Allowed / Forbidden + Why + 재검토 조건** 3단 구조.

## 적용 대상

- 한 브랜치에서 여러 Claude CLI 세션 동시 운영
- 한 작업을 여러 세션에 분할 (handoff)

## 현재 관찰된 현실

- Claude Code CLI 간 실시간 이벤트 공유 불가
- 세션 간 동기화는 Git 마커 polling이 유일
- 단일 세션 + Agent tool (rule 25)이 대부분의 경우 충분
- 이전 사고: 세션 간 staged 파일 충돌로 commit 오염

## 목표 규칙

### R1. 다중 세션 진입 조건

- **Default**: 단일 세션 + Agent tool (rule 25) 우선
- **Allowed (다중 세션)**: 다음 중 하나 이상 해당 시
  1. 작업 규모가 단일 컨텍스트 윈도우 초과
  2. 장기 작업의 세션 중단 후 재개 (다른 시간대)
  3. 사용자가 2 환경 (노트북 + 데스크톱)에서 병행
- **Forbidden**: 위 조건 없는데 다중 세션 (Agent tool로 대체 가능한 경우)
- **Why**: 다중 세션은 동기화 비용이 높음. 단일 세션 Agent tool이 컨텍스트 일관성 + 결과 통합 자동
- **재검토**: 세션 간 실시간 이벤트 공유 메커니즘 도입 시

### R2. 오너십 표 명시 의무

- **Default**: 다중 세션 시작 전 `docs/ai/tickets/<날짜>-<주제>/CONTINUATION.md` 에 오너십 표를 쓴다:
  ```markdown
  | 세션 | 담당 영역 | 오너십 파일 |
  |---|---|---|
  | A | adapter Huawei 신규 | adapters/redfish/huawei_*.yml |
  | B | tests/fixtures Huawei | tests/fixtures/huawei_*.json |
  | C | docs 갱신 | .claude/ai-context/vendors/huawei.md + docs/reference/live-validation.md |
  ```
- **Allowed**: 오너십이 명백한 경우 (1 세션이 1 디렉터리만) 표 생략 가능. 단 README에 명시
- **Forbidden**: 오너십 정의 없이 다중 세션 시작
- **Why**: 충돌 방지의 첫 번째 안전망. 사후 협상보다 사전 계약이 비용 낮음
- **재검토**: 오너십 자동 검출 도구 도입 시

### R3. Commit pathspec 사용 의무

- **Default**: 다중 세션에서 commit은 `git commit <pathspec>` 형식. `git add .` / `git commit -a` 금지
- **Allowed**: 자기 오너십 영역만 add 후 commit
- **Forbidden**: 다른 세션의 staged 파일 오염
- **Why**: 다른 세션이 staging area에 무엇을 추가했는지 불확정 → 의도치 않은 commit 발생
- **재검토**: 세션별 git index 분리 도구 도입 시

### R4. 공용 파일 순차 편집

- **Default**: 다음 공용 파일은 한 세션이 먼저 편집 + 다른 세션은 pull 후 append
  - `schema/sections.yml`
  - `schema/field_dictionary.yml`
  - `vault/<loc>/redfish/<vendor>.yml`
  - `common/vars/vendor_aliases.yml`
  - `Jenkinsfile*`
- **Allowed**: 다른 영역의 동시 편집은 OK
- **Forbidden**: 두 세션이 공용 파일 동시 편집 후 merge conflict 발생
- **Why**: schema / vault / Jenkinsfile은 모든 채널의 공용. conflict 해결이 위험
- **재검토**: 공용 파일 자동 lock 도구 도입 시

### R5. 세션 간 동기화 메커니즘

- **Default**: Git 마커 polling 사용
  ```bash
  # scripts/ai/wait_for_markers.sh (예시)
  MARKER="[SUB-3 DONE]"
  while ! git log --grep "$MARKER" -1 --oneline >/dev/null 2>&1; do
      git fetch origin
      sleep 30
  done
  ```
- **Allowed**: 사용자가 직접 세션 간 메시지 전달
- **Forbidden**: polling 간격 30초 미만 (Git 부하)
- **Why**: 실시간 이벤트 공유 메커니즘이 없는 환경에서 polling이 가장 안정
- **재검토**: 실시간 IPC 도구 도입 시

### R6. CONTINUATION.md 필수 섹션

- **Default**: handoff 문서에 다음 5 섹션 모두 포함
  1. 현재 상태 (각 영역 완결 여부)
  2. 세션별 담당 (오너십 표)
  3. 세션 간 의존성
  4. 다음 세션 첫 지시 템플릿
  5. 에스컬레이션 포인트
- **Allowed**: 단순 작업은 1~3만
- **Forbidden**: 다음 세션 진입을 위한 컨텍스트 누락
- **Why**: 다음 세션이 cold start로 진입 가능해야 함. 누락 시 사용자가 같은 컨텍스트 반복 설명
- **재검토**: handoff 자동 생성 도구 도입 시

### R7. Commit 마커 의무

- **Default**: 다중 세션 commit 메시지에 `[SUB-N DONE]` 마커 포함
- **Allowed**: 세션 1개만 운영 시 마커 생략
- **Forbidden**: 마커 없는 다중 세션 commit (다른 세션이 진행 상황 추적 불가)
- **Why**: rule 90 type prefix와 별개로 세션 진행 상황을 grep 가능하게
- **재검토**: 자동 진행 상황 추적 도구 도입 시

### R8. 세션 종료 전 CONTINUATION.md 갱신

- **Default**: 세션 종료 시 CONTINUATION.md를 다음 세션이 cold start로 진입 가능한 상태로 갱신
- **Forbidden**: CONTINUATION.md 갱신 없이 세션 종료
- **Why**: 다음 세션이 stale 정보로 시작 → 작업 중복 또는 충돌
- **재검토**: 종료 hook으로 자동 갱신 시

### R9. 다중 worker 4 정본 (cycle 2026-05-06 정착)

다중 worker (N≥3) cycle 운영 시 다음 4 정본 파일 모두 의무:

| # | 정본 파일 | 책임 | 정본 skill / agent |
|---|---|---|---|
| 1 | `INDEX.md` | cycle 진입점 + cold-start 가이드 + ticket 구조 | write-cold-start-ticket |
| 2 | `SESSION-HANDOFF.md` | 직전 세션 종료 시점 + 다음 세션 첫 지시 | write-cold-start-ticket |
| 3 | `DEPENDENCIES.md` | ticket 의존 그래프 (mermaid) + 진행 가능 ticket 식별 | cycle-orchestrator |
| 4 | `SESSION-PROMPTS.md` | worker N별 진입 prompt 템플릿 | cycle-orchestrator |

- **Default**: N≥3 worker cycle 진입 시 4 정본 모두 작성. fixes/INDEX.md (ticket 분류 + 진행 상태) 추가 권장
- **Allowed**: N=1 (단일 worker / 호환성 cycle 1 worker) 시 DEPENDENCIES.md / SESSION-PROMPTS.md skip 가능. INDEX + SESSION-HANDOFF 만 의무
- **Forbidden**:
  - N≥3 worker + 4 정본 일부 누락 → worker 충돌 위험
  - INDEX.md 없이 ticket 작업 시작 (다음 세션 진입점 부재)
  - DEPENDENCIES 없는 다중 worker (진행 가능 ticket 식별 불가)
- **Why**: cycle 2026-05-06 학습 — 24 ticket × 5 worker 운영 시 4 정본 부재로 worker 진입 어려움 발생 → DEPENDENCIES + SESSION-PROMPTS 추가 후 cold-start 0 진입 달성. 본 R10 으로 향후 cycle 재발 차단
- **재검토**: 4 정본 자동 생성 도구 (cycle-orchestrator skill) 정착 시 advisory → blocking 격상

## 금지 패턴

- 오너십 정의 없이 다중 세션 — R2
- `git add .` / `git commit -a` 사용 — R3
- 공용 파일 동시 편집 — R4
- polling 간격 30초 미만 — R5
- CONTINUATION.md 5 섹션 누락 — R6
- 마커 없는 commit — R7
- CONTINUATION 갱신 없이 종료 — R8
- N≥3 worker + 4 정본 일부 누락 — R9

## 리뷰 포인트

- [ ] CONTINUATION.md에 오너십 표 + 의존성
- [ ] 각 세션 commit에 [SUB-N] 태그
- [ ] 공용 파일 충돌 없음
- [ ] 세션 종료 전 CONTINUATION.md 갱신
- [ ] N≥3 worker 시 4 정본 (INDEX/HANDOFF/DEPENDENCIES/SESSION-PROMPTS) 모두 — R9

## 관련

- rule: `25-parallel-agents`, `93-branch-merge-gate`
- skill: `write-cold-start-ticket`, `cycle-orchestrator`
- agent: `ticket-decomposer`
- hook: `pre_commit_ticket_consistency.py` (cold-start 6 절 advisory)
- 정본: `docs/ai/tickets/`, 24 ticket × 5 worker cycle (2026-05-06 — git history)
