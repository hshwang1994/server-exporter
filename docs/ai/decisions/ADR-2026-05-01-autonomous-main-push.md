# ADR-2026-05-01-autonomous-main-push

## 상태
Accepted (2026-05-01). §2(github + gitlab 동시 push)는 2026-11-02 사용자 결정으로 **대체**됐다 —
`ADR-2026-11-02-gitlab-customer-form.md`(사내 GitLab 은 `main` 하나 = GitHub production, `origin` push URL 은 GitHub 하나). §1 · §3 은 유효.

## 컨텍스트 (Why)

기존 rule 93 R1+R4 / rule 24 R5는 **main 브랜치 직접 commit/push 금지**를 명시.
모든 main push는 사용자 명시 승인 후만 진행. 의도: main 보호 + 사고 차단.

실제 운영에서:
- 사용자가 "다음 작업?" 물어볼 때마다 매번 push 승인 요청 → 흐름 끊김
- AI가 작업 종료 시 commit 까지만 + push 보류 → 다음 세션이 origin 동기화 안 된 상태로 시작
- github 외 gitlab 동기화 누락 사고 (cycle-014 직전)

사용자 명시 (2026-05-01):
> "작업 끝나면 무조건 commit + push. 승인받지 말고 main에. git + gitlab 룰에 넣어라."

→ main push 자율 진행 + github + gitlab 동시 보장 정책 채택.

## 결정 (What)

### 1. main 자율 push 허용

- rule 93 R1: 작업 브랜치 push 자율 진행 (main 포함). force / `--all` / 다른 브랜치 push만 차단
- rule 93 R4 (신설): 작업 종료 시 commit + push 의무 — 사용자 "보류" 명시 시만 skip
- rule 24 R5: main 직접 push 사용자 명시 승인 → 자율 진행
- CLAUDE.md Step 6 R2: "main 직접 push" 항목 제거 → "force push"만 명시 승인 필요

### 2. github + gitlab 동시 push 보장 (2026-11-02 대체 — ADR-2026-11-02-gitlab-customer-form)

- origin remote가 두 push URL 등록 (github + gitlab) → `git push origin main` 한 번이면 양쪽 push
- rule 93 R7 (신설): origin push URL ≥ 2개 보장. 한 개로 단일화 금지
- 검증 명령: `git remote -v | grep origin | grep push | wc -l` ≥ 2

### 3. force push만 명시 승인 유지

- `--force` / `-f` / `--force-with-lease` 모두 차단
- main 브랜치 history 손상 방지의 마지막 안전망

## 결과 (Impact)

- AI 작업 종료 흐름 자동화 — pytest PASS → commit → push (origin = github + gitlab)
- main 보호는 사용자 책임 (force push 명시 차단 + branch protection)
- 향후 force push 사고 발생 시 rule 93 R1 강화 검토 (재검토 조건)

### 변경 파일
- `.claude/rules/93-branch-merge-gate.md` — R1/R4/R6/R7 본문 변경
- `.claude/rules/24-completion-gate.md` — R5 본문 변경
- `CLAUDE.md` — Step 6 R1/R2 본문 변경

### 표면 카운트 영향
- rules: 28 (변경 없음 — 본문만 의미 변경)
- skills/agents/policies: 변경 없음

## 대안 비교 (Considered)

### A. 기존 유지 (사용자 명시 승인 후만 main push)
- 장점: main 보호 강함
- 단점: 사용자 매번 승인 요청 → 흐름 끊김 (사용자 명시 거절)

### B. 자율 진행 (force 외) ← **채택**
- 장점: 작업 흐름 자동화, github + gitlab 동기화 보장
- 단점: main 사고 risk (force push만 차단으로 완화)

### C. main 자율 + 사후 검증 hook
- 장점: 자율 + 안전망
- 단점: 검증 hook 정의 + 거짓 양성 risk. 단계적 도입 (R1 강화 시점)

→ B 채택. C는 "force push 사고 발생 시" 단계로 검토.

## 관련

- rule: `93-branch-merge-gate` R1/R4/R7, `24-completion-gate` R5, `90-commit-convention`
- ADR: `ADR-2026-05-01-harness-full-permissions` (자율 권한 확대 흐름)
- CLAUDE.md: Step 6 자율 판단 원칙

## 승인 기록

| 일시 | 승인자 | 비고 |
|---|---|---|
| 2026-05-01 | hshwang1994 | "작업 끝나면 무조건 commit + push. 승인받지 말고 main에. git + gitlab 룰에 넣어라." |
