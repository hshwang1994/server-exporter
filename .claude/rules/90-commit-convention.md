# Commit 메시지 컨벤션

## 규칙 표기 구조

본 rule의 각 항목은 **Default / Allowed / Forbidden + Why + 재검토 조건** 3단 구조.

## 적용 대상

- 저장소 전체 (`**`)
- 모든 git commit (사람/AI 공통)

## 현재 관찰된 현실

- `commit_msg_check.py` (commit-msg hook): advisory (위반 시 stderr 경고, commit 허용)
- 일부 `pre_commit_*` hooks는 차단 (보호 경로 / 잔재 어휘 / SKILL.md 형식)
- 현재 commit log: `feat: ...`, `fix: ...`, `harness: ...`, `refactor: ...`, `docs: ...` 일관 사용

## 형식

```
<type>: <제목>

<본문 — 선택, 3줄 이내>
```

## 목표 규칙

### R1. type 8개 고정

- **Default**: type은 다음 8개 중 하나만
  | type | 용도 | 예시 |
  |---|---|---|
  | `feat` | 신규 기능 | `feat: Huawei vendor adapter 추가` |
  | `fix` | 버그 수정 | `fix: callback URL 후행 슬래시 방어` |
  | `refactor` | 기능 변경 없는 구조 개선 | `refactor: gather/normalize 책임 분리` |
  | `docs` | 문서만 | `docs: `docs/reference/live-validation.md` Round 11 추가` |
  | `test` | 테스트 추가/수정 | `test: HPE iLO6 baseline 추가` |
  | `chore` | 빌드/의존성/설정 | `chore: requirements.yml 갱신` |
  | `harness` | AI 하네스 변경 | `harness: rule 22 fragment-philosophy 보강` |
  | `hotfix` | 운영 긴급 수정 | `hotfix: Jenkins Stage 4 timeout 60s` |
- **Allowed**: 추가 type은 본 rule 갱신 + 사용자 승인 후
- **Forbidden**: 위 8개 외 type 사용 (예: `style`, `perf`, `build`, `ci`)
- **Why**: type 다양화 시 분류 일관성 떨어짐. 8개로 모든 변경 분류 가능 검증됨
- **재검토**: 새 운영 도메인 (예: i18n) 추가 시

### R2. 제목 길이 / 표기

- **Default**:
  - **50자 hard limit** (한국어 기준)
  - 한국어/영어 혼용 가능
  - 기술 용어는 영문 (`redfish_gather.py`, `iDRAC9`, `Jenkinsfile`)
  - 끝에 마침표 없음
  - **무엇을/왜** 명시. 모호한 단어 단독 금지
- **Allowed**:
  - 티켓 있는 변경: `feat: [SUB-1] DAY_1 enum 확장`
  - cycle 작업: `refactor: cycle-008 — P2 MED/LOW 11건 일괄 정합`
- **Forbidden**:
  - 50자 초과
  - subject 끝에 `.`
  - scope 괄호 (`feat(adapter): ...` 형식 금지 — 본 컨벤션 미사용)
- **Why**: git log --oneline의 가독성. 50자 hard limit는 git/GitHub UI 표준
- **재검토**: GitHub UI 폭 변경 시

### R3. 금지어 (subject 단독 사용 금지)

- **Default**: 다음 단어가 subject 전부일 수 없음
  - `버그수정`, `수정`, `변경`, `업데이트`, `작업`
  - `fix`, `update`, `change` (subject 단독)
  - `WIP`, `wip`, `임시`, `test` (subject 단독)
- **Allowed**: 다른 단어와 함께 쓰면 OK (`fix: 빌링 합계 오산 수정` ✓)
- **Forbidden**: `fix: 수정` / `버그수정` 같은 단독 사용
- **Why**: 단독 사용은 변경 의도 추적 불가. git log grep 의미 없음
- **재검토**: AI 자동 commit message 생성 시 (의도 추출 자동화)

### R4. 본문 규칙

- **Default**:
  - **3줄 이내** (hard limit)
  - **why > what** (코드만 봐도 알 수 있는 "무엇" 보다 "왜")
  - 관련 티켓: `Ticket: docs/...` 또는 `Refs: ...`
- **Allowed**: 4줄 이상 시 hook 경고 (advisory) — 사용자가 의도된 경우 허용
- **Forbidden**: 본문이 단순 변경 list (코드 diff에 이미 있음)
- **Why**: 본문은 미래 작업자가 "왜 이 변경?" 이해하기 위함. diff에 있는 정보 반복은 noise
- **재검토**: 자동 commit message 생성 도구 도입 시

### R5. 강제 수준 (advisory vs blocking)

- **Default**:
  - `commit_msg_check.py` (commit-msg hook): advisory (stderr 경고, commit 허용)
  - 보호 경로 / 잔재 어휘 / SKILL.md 형식: blocking
- **Allowed**: 사용자 명시 승인 후 advisory 무시 가능. `--no-verify` 는 쓰지 않는다 —
  훅을 통째로 끄면 blocking 검사까지 함께 꺼지기 때문이다. 개별 훅은 각자 문서화한
  skip 환경변수(`ADDITIVE_SKIP_NEW_CYCLE` 등)로 우회한다
- **Forbidden**:
  - `--no-verify` 사용 (2026-10-03 부터 예외 없음 — production 커밋은 prodgen 의 git plumbing 이라 훅을 거치지 않는다)
  - blocking hook 우회
- **Why**: advisory는 학습 목적. 강제 차단은 막대한 정지 비용
- **재검토**: AI 자동 commit message 정합성 100% 도달 시 blocking 격상 검토

### R6. AI vs 사람 commit 동등 적용

- **Default**: AI가 만든 commit과 사람이 만든 commit 모두 본 rule 적용
- **Allowed**: AI commit은 자동 검증 hook 통과 후 진행
- **Forbidden**: AI commit이 사람 commit보다 약한 기준
- **Why**: commit log는 사람 / AI 구분 없이 git log로 읽힘. 일관성 필요
- **재검토**: AI / 사람 분리 표기 도입 시

## 예시 (OK)

```
fix: probe_redfish.py 펌웨어 5.x 응답 형식 정정

- 원인: iDRAC9 5.x 펌웨어부터 SystemId path 변경
- adapter dell_idrac9.yml의 collect.systems_path 수정
- schema/baseline_v1/dell_baseline.json 회귀 추가
```

```
harness: rule 22 fragment-philosophy 보강

- R9 self-test (validate-fragment-philosophy skill) 추가
- 의심 패턴 9종 명시
```

```
feat: Huawei vendor adapter 추가
```

## 예시 (NG)

- `버그수정` — R3 금지어 단독
- `fix: 수정` — R3 subject 전부 금지어
- `Huawei adapter 추가` — R1 type prefix 누락
- `feat(adapter): ...` — R2 scope 괄호 사용
- `feat: 새 기능을 추가합니다.` — R2 마침표 + 모호한 표현

## 금지 패턴

- type 8개 외 사용 — R1
- 50자 초과 / 마침표 / scope 괄호 — R2
- subject 단독 금지어 — R3
- 본문이 단순 변경 list — R4
- `--no-verify` 우회 — R5

## 리뷰 포인트

- [ ] type이 8개 안에 있음
- [ ] 50자 이내
- [ ] 금지어 단독 아님
- [ ] 본문 3줄 이내 + why > what

## 강제

- `commit_msg_check.py` (commit-msg hook): advisory
- self-test: `python scripts/ai/hooks/commit_msg_check.py --self-test`

## 설치

```bash
bash scripts/ai/hooks/install-git-hooks.sh
```

## 관련

- script: `scripts/ai/hooks/commit_msg_check.py`
- rule: `93-branch-merge-gate`
