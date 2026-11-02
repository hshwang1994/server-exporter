# Branch / Merge / Push 게이트

## 적용 대상
- 저장소 전체 (`**`) — 모든 branch 간 merge / cherry-pick / push

## 사용자 명시 (2026-05-01)
> "작업 끝나면 무조건 commit + push. 승인받지 말고 main에. git + gitlab 룰에 넣어라."

→ 본 rule 93의 main 보호 + main push 승인 의무는 **해제**. force push만 차단 유지.

## 사용자 명시 (2026-11-02) — 사내 GitLab 은 고객사 형태
> "github에는 main이랑 production을 그대로 냅두고 … gitlab에는 현재 main 브랜치를 지우고 production 브랜치가 main이 되는거임
> gitlab이 고객사인것처럼 … jenkins-prod 에 연결된 각종 ci 및 액션들은 gitlab이랑 연결돼있는게아니라 github랑 연결돼있어야함"

→ 2026-05-01 의 "git + gitlab" 동시 push 는 **폐기**. GitHub 가 개발(`main`)·배포(`production`) 저장소이고, 사내 GitLab 은
고객사처럼 **`main` 하나**만 갖는다 — 그 커밋은 GitHub `production` 과 같다. 근거 ADR: `docs/ai/decisions/ADR-2026-11-02-gitlab-customer-form.md`.

## Branch 역할 (단순 운영)

| 브랜치 | 역할 | AI 권한 |
|---|---|---|
| `main` (운영 기준선, GitHub) | 모든 변경의 최종 도착점 | **자율 commit + push 허용** (force 외) |
| `production` (배포, GitHub) | prodgen 생성 커밋만. 사내 GitLab `main` 과 같은 커밋 | 직접 commit · merge 금지 — `prodgen promote` / `restore` / `push-sync` 만 |
| `feature/<name>` | 기능 추가 | AI 자유 작업 |
| `fix/<name>` | 버그 수정 | AI 자유 작업 |
| `vendor/<name>` | 새 벤더 추가 | AI 자유 작업 |
| `docs/<name>` | 문서 작업 | AI 자유 작업 |
| `harness/<name>` | 하네스 변경 | AI 자유 작업 |

## Remote 구성 (2026-11-02 — GitHub 개발·배포 / 사내 GitLab 고객사 형태)

| 원격 | 저장소 | 브랜치 | 쓰는 쪽 |
|---|---|---|---|
| `origin` | GitHub `hshwang1994/server-exporter` — push URL **1개** | `main`(개발) · `production`(배포) · 작업 브랜치 | 개발 push · jenkins-prod 의 모든 Job(SCM `https://github.com/hshwang1994/server-expoter`) |
| `internal` | 사내 GitLab `root/server-expoter` | **`main` 하나** = GitHub `production` 과 같은 커밋 | prodgen 만 |

```
$ git remote -v
internal  https://10.100.64.156/root/server-expoter.git (fetch)
internal  https://10.100.64.156/root/server-expoter.git (push)
origin    git@github.com:hshwang1994/server-exporter.git (fetch)
origin    git@github.com:hshwang1994/server-exporter.git (push)
$ git config remote.internal.push
refs/heads/production:refs/heads/main
```

→ `git push origin <브랜치>` 는 GitHub 에만 간다. GitLab 에 쓰는 길은 prodgen(`--push-remote origin,internal`)뿐이며
origin 에는 `refs/heads/production`, internal 에는 `refs/heads/main` 으로 **같은 커밋**을 올린다 (`scripts/ai/prodgen/__init__.py` `DEPLOY_TARGET_REFS`).
`remote.internal.push` 는 refspec 없는 `git push internal` 이 개발 브랜치 대신 로컬 production 만 GitLab `main` 으로 보내게 하는 안전장치다.

## 목표 규칙

### R1. 작업 브랜치 push 자율 진행

- **Default**: AI는 현재 체크아웃된 브랜치에 자율 push. main 포함.
  - main → `git push origin main` (GitHub 만 — 2026-11-02 부터 사내 GitLab 은 개발 브랜치를 받지 않는다)
  - feature/* → `git push -u origin feature/<name>` (신규) 또는 `git push origin feature/<name>` (기존)
- **Allowed**: 작업 종료 시 별도 승인 없이 commit + push 진행
- **Forbidden**:
  - `git push --force` / `-f` / `--force-with-lease`
  - `git push --all` (여러 브랜치 일괄)
  - 다른 브랜치 push (`git push origin <체크아웃 안 된 브랜치>`)
  - 사내 GitLab(`internal`)에 직접 push (`git push internal main` 등) — GitLab 은 prodgen 만 쓴다 (R2 예외 2 · R7).
    예외: 사용자가 지시한 GitLab 정비 작업
- **Why**: 사용자 명시 (2026-05-01) — 자율 진행. force만 차단해서 이력 보호. (2026-11-02) GitLab 은 고객사 형태
- **재검토**: force push 사고 발생 시 R1 강화

### R2. Branch 간 merge 사용자 승인

- **Default**: 모든 `git merge`, `git rebase <다른브랜치>`, `git cherry-pick` 작업은 **실행 전 사용자 승인** 필수
- **Allowed**: 사용자가 4 요소 명시 후 승인:
  1. 소스 브랜치
  2. 타겟 브랜치
  3. 포함 commit 범위 (예상 diff 요약)
  4. 영향 (vendor / 채널 / Jenkins pipeline)
- **Forbidden**:
  - 승인 없는 git merge
  - "로컬 merge만 하니까" — push 직전 추가 승인 필요
  - `git pull origin <다른브랜치>` (실질적 merge)
  - `git merge main` → production (하네스 누출 — 아래 예외 2 의 production 승격은 **생성기(prodgen) append 커밋만**)
- **Allowed (예외 1)**: 같은 브랜치 동기화 `git pull origin main` (현재 main에서 origin/main fetch+ff)는 자율 진행
- **Allowed (예외 2 — production 승격, 2026-06-30 사용자 명시 · 2026-10-03 prodgen 으로 개정)**: main → production 승격은
  **사용자 per-instance 승인 불요**(R6 승인 포맷 면제)이되, 방식과 전제가 바뀌었다 (ADR-2026-10-03-production-generation).
  - 방식: `python -m scripts.ai.prodgen promote --sha <main sha>` — 고정 SHA 의 object store 에서 **runtime-only tree** 를 생성해 gate(G01~G20) 통과 뒤
    git plumbing append 커밋(trailer `Main-SHA` 등)으로 올린다. 파일 state sync 와 `git merge` 는 금지 — 종전 `promote_to_production.sh` 는 shim 을 거쳐 2026-10-11 삭제됐다.
  - 전제(하나라도 빠지면 승격하지 않는다): gate 전부 PASS · class B 0 · drift-check 정합 · **같은 main SHA 가 main Job 에서 1회 이상 성공** · 승격 직후 production Job
    canary 가능. canary 를 돌릴 수 없는 세션은 `--dry-run` 까지만 한다 (`docs/operate/09-production-branch.md` 3절).
  - plumbing 커밋은 pre-commit 훅을 거치지 않으므로 `--no-verify` 예외는 더 이상 필요 없다. force push 는 여전히 금지 (R1). 되돌림은 `prodgen restore`(append).
  - 대상 ref (2026-11-02): GitHub `origin` 은 `production`, 사내 GitLab `internal` 은 `main` 에 같은 커밋을 올린다. 두 원격 중 하나라도 빠진
    실 승격 · 복구는 거부된다 (deploy policy). 승격 뒤 확인: `git ls-remote origin refs/heads/production` == `git ls-remote internal refs/heads/main`.

### R3. 현재 브랜치 확인 의무

- **Default**: 모든 git 작업 시작 전 `git branch --show-current` 확인
- **Forbidden**: 브랜치 이름 추정만으로 작업

### R4. 작업 종료 시 commit + push 의무

- **Default**: AI 작업 종료 (rule 24 완료 게이트 6/6 통과) 직후 다음 자동 진행:
  1. 변경 파일 add (pathspec — `git add .` 금지, rule 26 R3)
  2. commit (rule 90 type prefix)
  3. push (현재 브랜치 → origin = GitHub)
  4. **production 승격** (순수 게더링 코드 변경이 있을 때) — `python -m scripts.ai.prodgen promote --sha <main sha>`
     (R2 예외 2 의 전제가 충족될 때; 아니면 `--dry-run` 결과와 보류 사유를 보고). 순수 코드 변경이 없으면 tree hash 가 같아 no-op.
- **Allowed**: 사용자 명시 "push 보류" / "commit만" / "production 보류" 시 해당 단계 skip
- **Forbidden**:
  - 변경 후 commit/push 없이 세션 종료 (사용자가 명시 보류 한 경우 외)
  - rule 24 6 체크 미통과 + push 강행
  - **순수 코드 변경 후 production 승격(또는 전제 미충족 시 `--dry-run` + 보류 사유 보고) 누락** (사용자 명시 보류 외) — 본 누락이
    "자꾸 말을 해줘야 하는" 사용자 불만의 원인 (2026-06-30)
- **Why**: 사용자 명시 (2026-05-01) commit+push 자동 + (2026-06-30) production 승격 자동. 분산
  협업 + 배포 브랜치 동기화 보장
- **재검토**: 자동 push/promote hook(예: post-push) 도입 시 본 R4 를 hook 책임으로 위임

### R5. 머지 전략 (default: squash)

배포/main으로의 머지는 squash 기본:

| 머지 대상 | 기본 전략 | 이유 |
|---|---|---|
| main | squash | 1개 의미 있는 커밋으로 history 깔끔 |
| feature 간 (개인) | merge / rebase 자유 | 개인 작업 |

**예외 (fast-forward)**: feature의 모든 커밋이 의미 있는 단일 변경이고 main history에 그대로 남길 가치 있을 때만. 사용자 명시 "fast-forward로" 지시 필요.

승인 요청 시 머지 방식 선택지 제시:
```
머지 방식 선택:
(A) squash   — N개 commit을 1개 "<요약>"으로 압축 (main 추천)
(B) fast-forward — N개 그대로 전파
(C) merge commit — 병합 commit 추가
```

### R6. 승인 요청 포맷 (R2 merge 시만)

```
# 머지 승인 요청

무엇: <소스 브랜치> → <타겟 브랜치> 머지
왜:   <목적, 1-2 문장>
영향: <commit 개수> commit 포함, 영향 vendor: <list>, 영향 채널: <list>
      주요 변경: <bullet 3줄>
결정 필요: 진행 / 조정 / 취소 (squash / ff / merge 중)
```

→ 단순 push (main 포함)는 R1 자율 — 본 R6 적용 안 됨.

### R7. 원격 구성 검증 (2026-11-02 개정 — 종전 "github + gitlab 동시 push 보장" 폐기)

- **Default**:
  - `origin` push URL 은 GitHub **1개**: `git remote get-url --push --all origin` → `git@github.com:hshwang1994/server-exporter.git` 한 줄
  - 사내 GitLab 은 고객사 형태: `git ls-remote --heads internal` → `refs/heads/main` 한 줄, 그 SHA == `git ls-remote origin refs/heads/production`
  - `python -m scripts.ai.prodgen push-sync --remote origin --remote internal --dry-run` 이 `ok` 이고 `preview_refusals` 가 없다
- **Forbidden**:
  - `origin` 에 GitLab push URL 재추가 (종전 dual push) — 개발 main · 작업 브랜치가 GitLab 에 나가고, prodgen 이 GitLab 에 `production` 을
    만든다. prodgen 은 이 구성(서로 다른 대상 ref 를 가진 두 원격이 같은 저장소를 가리킴)을 보면 실 승격 · 복구 · push-sync 를 쓰기 전에 거부한다
  - 사내 GitLab 에 `production` · 작업 브랜치 생성, GitLab `main` 에 개발 커밋 push
- **재구성** (사고 시):
  ```bash
  git config --unset remote.origin.pushurl '10\.100\.64\.156'          # GitLab push URL 제거 (Git Bash 는 앞에 MSYS_NO_PATHCONV=1)
  git config remote.internal.push refs/heads/production:refs/heads/main
  ```
- **Why**: 사용자 명시 (2026-11-02) — GitHub 는 main · production 그대로, 사내 GitLab 은 고객사처럼 main 하나(= production).
  jenkins-prod 의 CI · Job 은 GitHub 에 연결한다
- **재검토**: 고객사 납품 경로가 바뀌거나 GitLab 이 다시 개발 미러가 될 때

## 금지 패턴

- 현재 브랜치 확인 없이 git 작업 — R3
- 다른 브랜치 push — R1
- force push (`--force` / `-f`) — R1
- `git push --all` — R1
- 승인 없는 merge — R2
- 작업 종료 + commit/push 누락 — R4
- merge 승인 포맷 생략 — R6
- origin 에 GitLab push URL 재추가 / 사내 GitLab 에 직접 push(개발 main · 작업 브랜치 · `production`) — R1 · R7

## 리뷰 포인트

- [ ] force / --all 사용 없음
- [ ] 작업 종료 시 commit + push 진행
- [ ] origin push URL = GitHub 1개 · 사내 GitLab 은 `main` 하나 (= GitHub production)
- [ ] merge 시 4 요소 명시 + 승인 기록
- [ ] 현재 브랜치 확인 흔적

## 관련

- rule: `00-core-repo`, `24-completion-gate` R5, `50-vendor-adapter-policy`, `90-commit-convention`
- ADR: `docs/ai/decisions/ADR-2026-11-02-gitlab-customer-form.md` · `docs/ai/decisions/ADR-2026-10-03-production-generation.md`
- docs: `docs/operate/09-production-branch.md` (production 승격 · GitLab 형태)
