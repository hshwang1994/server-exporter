---

description: UltraCode dynamic workflow로 사람이 읽는 Markdown 문서를 전체 리팩토링하고, 프로젝트 전체 파일을 검수해 미사용 비코드 파일을 정리한다. 코드 파일은 삭제하지 않는다.
argument-hint: "(선택) 점검 범위, 예: 전체 / root / README.md / docs/ / schema/ / tests/"
--------------------------------------------------------------------------------

# /ultracode-human-docs-and-file-audit

ultracode.

너는 이 프로젝트의 **UltraCode Human Docs and File Audit Orchestrator**다.

이 명령은 일반 단일 에이전트 작업이 아니다.
UltraCode dynamic workflow를 사용해 프로젝트 전체를 병렬 검수하고, 독립 에이전트들이 서로의 결과를 반박 검토하게 하라.

목표는 두 가지다.

1. 사람이 읽는 Markdown 문서 전체를 리팩토링한다.
2. 프로젝트 전체 파일을 검수해 더 이상 사용하지 않는 **비코드 파일**을 삭제하거나 정리한다.

단, 코드 파일은 삭제하지 않는다.
코드가 불필요해 보여도 삭제하지 말고 `Deferred Code Cleanup`으로 남긴다.

---

## 0. UltraCode 실행 원칙

이 작업은 repo-wide audit이다.
반드시 UltraCode의 workflow orchestration을 사용하라.

수행 방식:

* 작업을 여러 phase로 나눈다.
* phase마다 독립 subagent를 배치한다.
* 같은 영역을 최소 2개 관점에서 검토한다.
* 한 에이전트의 결과를 다른 에이전트가 반박 검토한다.
* 문서 변경, 파일 삭제, 링크 검증, 코드 정합성 검증을 별도 phase로 나눈다.
* 마지막에는 Final Cross Reviewer가 전체 결과를 다시 뒤집어 검토한다.
* 새 문제가 발견되면 수정 후 다시 검수 루프로 돌아간다.
* 한 번 고친 항목만 보지 말고 매 반복마다 프로젝트 전체에서 새 문제를 다시 찾는다.

UltraCode에서 사용할 수 있는 기능은 모두 사용해도 된다.

사용 가능:

* dynamic workflows
* parallel subagents
* agent teams
* task planning
* repo-wide search
* file edit
* shell command
* web search
* markdown lint
* link check
* grep/rg 기반 참조 검색
* git diff 검토
* 반복 검수
* 반박 검토
* 필요 시 작은 범위 smoke test

단, 파일 삭제는 안전 규칙을 따른다.

---

## 1. 절대 원칙

이 명령은 문서와 파일 정리 명령이다.
코드 리팩터링 명령이 아니다.

다음은 절대 삭제하지 마라.

* Python 코드
* Ansible playbook, role, task
* Jenkinsfile
* shell script
* schema
* adapter
* test code
* 테스트 fixture
* baseline
* inventory 예시
* 설정 파일
* lock 파일
* CI/CD 파일
* `.claude` 하네스 파일
* 자동화가 참조할 수 있는 파일

코드 파일은 삭제 금지다.

코드 또는 실행 계약으로 간주할 파일:

```text
*.py
*.sh
*.bash
*.ps1
*.yml
*.yaml
*.json
*.toml
*.ini
*.cfg
*.conf
*.env.example
Jenkinsfile
Dockerfile
Makefile
requirements*.txt
pyproject.toml
package.json
package-lock.json
```

예외:

* JSON/YAML이 명백한 오래된 export, 임시 산출물, 중복 샘플, debug dump이고
* 코드, 테스트, 문서, 하네스, CI에서 참조되지 않으며
* 더 최신 파일로 대체되었고
* 삭제 후 프로젝트 사용성이 떨어지지 않는 경우

이 경우에도 즉시 삭제하지 말고 먼저 삭제 후보로 올린 뒤 참조 검색을 수행한다.

확실하지 않으면 삭제하지 않는다.

---

## 2. 프로젝트 전체 범위

프로젝트 전체를 검수한다.

반드시 포함:

* 프로젝트 루트의 모든 파일
* 숨김 파일
* 설정 파일
* 샘플 파일
* export 파일
* report 파일
* log 파일
* backup 파일
* archive 파일
* `README.md`
* `REQUIREMENTS.md`
* `docs/**/*.md`
* `schema/README.md`
* `tests/README.md`
* `common/README.md`
* docs asset
* examples
* scripts 산출물
* 테스트 fixture
* baseline
* `.claude` 아래 파일

단, `.claude`는 하네스 영역이므로 읽고 분류하되 원칙적으로 수정하지 않는다.
이 command 파일 자체를 만들거나 수정하는 것은 허용한다.

직접 수정하지 않을 디렉터리:

```text
.git/
.venv/
venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
node_modules/
dist/
build/
```

---

## 3. Markdown 문서 분류

모든 `.md` 파일을 먼저 분류한다.

### A. 사람용 문서

이번 작업의 주 대상이다.

예상 후보:

```text
README.md
REQUIREMENTS.md
docs/**/*.md
schema/README.md
tests/README.md
common/README.md
```

### B. 하네스/AI 전용 문서

원칙적으로 수정하지 않는다.

예상 후보:

```text
CLAUDE.md
rule 22 (fragment-philosophy)
.claude/agents/**/*.md
.claude/rules/**/*.md
.claude/skills/**/SKILL.md
.claude/commands/**/*.md
.claude/ai-context/**/*.md
.claude/templates/**/*.md
```

단, 이 command 파일 자체는 예외다.

### C. 혼합 문서

사람도 읽고 하네스도 읽을 수 있는 문서다.

처리 기준:

* 사용처를 먼저 검색한다.
* 하네스가 참조하면 구조를 바꾸지 않는다.
* 사람이 읽기 어려운 내용은 별도 사람용 문서로 분리한다.
* 원본 계약은 보존한다.
* 내용 삭제 전 반드시 다른 문서로 흡수했는지 확인한다.

### D. 삭제/통합 후보 문서

다음 조건이면 삭제, 통합, archive 후보로 분류한다.

* 같은 내용을 최신 문서가 이미 설명한다.
* 코드 구조와 맞지 않는다.
* 링크가 끊겨 있다.
* 파일명과 내용이 다르다.
* README나 docs index에서 연결되지 않는다.
* 독립 문서로 남을 가치가 없다.
* 설치, 실행, 운영 절차가 다른 문서와 충돌한다.
* 과거 작업 로그인데 현재 가이드처럼 남아 있다.

삭제 전에는 반드시 참조 검색을 수행한다.

---

## 4. GitHub Markdown 기준 조사

문서를 고치기 전에 web search로 최신 GitHub Markdown 기준을 확인한다.

반드시 확인:

* GitHub Flavored Markdown 공식 스펙
* GitHub Docs basic writing and formatting syntax
* GitHub Markdown alerts
* GitHub relative links
* GitHub heading anchor
* GitHub Mermaid diagram 지원
* GitHub collapsed sections, `<details>`
* markdownlint 규칙
* README 작성 관례
* code fence language identifier 관례

조사 후 이 프로젝트에 적용할 기능 목록을 만든다.

```text
[Markdown Feature Palette]
- Headings: H1은 파일당 하나만 둔다.
- Relative links: repo 내부 문서는 상대 경로를 쓴다.
- Alerts: 전제 조건, 주의, 위험에만 제한적으로 쓴다.
- Tables: 명령 요약, 파일 책임, 비교에만 쓴다.
- Task lists: 운영 점검표나 migration checklist에만 쓴다.
- Mermaid: gather 흐름, adapter routing, Jenkins pipeline 설명에 쓴다.
- details: 긴 로그, 긴 JSON, legacy 예시를 접는다.
- Code fences: bash, yaml, json, python, mermaid 등 언어를 지정한다.
```

웹에서 확인하지 않은 Markdown 기능을 확정된 GitHub 기능처럼 쓰지 마라.

---

## 5. 사람용 Markdown 리팩토링 기준

문서는 예쁜 글이 아니라 길 찾기 도구다.

좋은 문서는 다음 질문에 바로 답한다.

* 이 프로젝트가 무엇인가
* 처음 보는 사람이 어디부터 읽어야 하는가
* 설치와 실행은 어떻게 하는가
* 입력과 출력은 무엇인가
* 운영 중 문제를 어디서 디버깅하는가
* 새 gather, adapter, schema를 추가할 때 어디를 보면 되는가
* 현재 코드 구조와 설명이 맞는가
* 어떤 문서가 canonical source인가

### README.md 역할

README는 입구다.

포함할 것:

* 프로젝트 한 줄 설명
* 빠른 시작
* 주요 실행 명령
* 입력과 출력 요약
* 문서 지도
* 주요 디렉터리 구조
* 운영자, 개발자, 기여자별 다음 문서 링크

넣지 말 것:

* 긴 설계 논쟁
* 모든 schema 필드 설명
* 긴 로그 예시
* 오래된 의사결정 내역
* 하네스 사용 규칙
* 중복된 troubleshooting 전체 내용

### docs 역할

상세 설명은 docs로 보낸다.

현재 구조 (2026-08-13 재편):

```text
docs/README.md        읽는 순서 안내
docs/overview/        무엇이고 왜 있는가, 아키텍처
docs/contract/        입력 / envelope / 필드 / 실패 진단
docs/operate/         Jenkins, agent, job 등록, vault, 현장 수집
docs/develop/         gather 구조, normalize, adapter, vendor 추가, 디버깅
docs/reference/       호환성 매트릭스, 실장비 검증, 의사결정 로그
docs/ai/              AI 전용 — 카탈로그, ADR, 계약, 티켓
```

감사 대상은 이 구조다. 새 구조를 제안하기 전에 현재 구조로 설명되지 않는
문서가 실제로 있는지 먼저 확인한다.

큰 이동이 위험하면 기존 구조를 유지하되 `docs/README.md`부터 만든다.

### REQUIREMENTS.md 역할

현재 요구사항과 외부 계약만 남긴다.

남길 것:

* 현재 요구사항
* 입력 계약
* 출력 계약
* 운영 제약
* 비기능 요구사항
* 호환성 요구사항

빼거나 분리할 것:

* 오래된 논의
* 이미 끝난 작업 로그
* README와 중복되는 실행 방법
* decision log에 더 어울리는 배경 설명

---

## 6. 프로젝트 전체 파일 인벤토리

Markdown만 보지 마라.
프로젝트 전체 파일을 검수한다.

먼저 전체 파일 목록을 만든다.

가능하면 다음 명령을 사용한다.

```bash
git ls-files
find . -maxdepth 2 -type f | sort
find . -type f | sort
```

그다음 파일을 분류한다.

```text
[Project File Inventory]
- Code:
- Tests:
- Config:
- Schema:
- CI/CD:
- Human docs:
- Harness docs:
- Examples:
- Fixtures:
- Baselines:
- Assets:
- Generated outputs:
- Logs:
- Backups:
- Archives:
- Unknown:
```

프로젝트 루트 파일은 반드시 별도 섹션으로 검수한다.

```text
[Root File Audit]
- 유지:
- 문서로 이동:
- docs에 통합:
- 삭제 후보:
- 삭제 금지:
- 판단 보류:
```

루트에 있는 파일이라고 자동으로 중요하다고 보지 마라.
반대로 루트에 있다고 함부로 삭제하지도 마라.

---

## 7. 미사용 비코드 파일 정리

Markdown 외의 파일도 정리한다.

단, 삭제 가능한 것은 **비코드 파일**뿐이다.

삭제 후보 예:

```text
*.log
*.tmp
*.bak
*.backup
*.old
*.orig
*.rej
*.swp
.DS_Store
Thumbs.db
*.zip
*.tar
*.tar.gz
*.tgz
*.7z
old_report.*
export_*.json
debug_*.txt
unused screenshot
duplicate image
obsolete generated artifact
stale local output
```

하지만 다음은 삭제하지 마라.

* 테스트 fixture
* baseline
* sample input
* sample output
* docs에서 참조하는 이미지
* README에서 링크하는 파일
* schema 예시
* 운영자가 복사해서 쓰는 template
* CI에서 참조하는 artifact
* 하네스가 참조하는 파일

삭제 후보는 반드시 참조 검색한다.

```bash
grep -R "파일명" .
grep -R "상대경로" .
grep -R "basename" .
```

가능하면 `rg`를 사용한다.

```bash
rg "파일명"
rg "상대경로"
rg "basename"
```

삭제 가능한 파일 조건:

* 코드에서 참조하지 않는다.
* 테스트에서 참조하지 않는다.
* 문서에서 참조하지 않는다.
* 하네스에서 참조하지 않는다.
* CI/CD에서 참조하지 않는다.
* 샘플이나 fixture로 쓰이지 않는다.
* 더 최신 파일로 대체되었다.
* 삭제 후 사용자가 길을 잃지 않는다.

확실하지 않으면 삭제하지 않는다.
`Deferred File Cleanup`으로 남긴다.

---

## 8. UltraCode Agent 설계

이 작업은 반드시 여러 agent로 나눈다.

### A. Repo Inventory Agent

전체 파일 목록을 만든다.

산출물:

* 전체 파일 수
* 루트 파일 목록
* tracked/untracked 구분
* hidden file 목록
* generated output 후보
* backup/log/archive 후보
* unknown 파일 목록

### B. Markdown Inventory Agent

모든 `.md` 파일을 분류한다.

산출물:

* 사람용 문서
* 하네스 문서
* 혼합 문서
* 삭제 후보
* 통합 후보
* archive 후보
* 깨진 링크 후보

### C. GitHub Markdown Research Agent

웹에서 GitHub Markdown 기능과 markdownlint 기준을 조사한다.

산출물:

* 적용할 Markdown 기능
* 쓰지 않을 기능
* 문서 렌더링 기준
* lint 기준
* 이 프로젝트에 맞는 사용 예시

### D. Human Reader Advocate Agent

처음 보는 사람이 읽는다고 가정하고 문서를 본다.

확인할 것:

* 어디부터 읽어야 하는가
* 실행까지 이어지는가
* 운영자가 장애 대응 경로를 찾을 수 있는가
* 개발자가 확장 방법을 찾을 수 있는가
* 문서가 너무 많아서 길을 잃지 않는가

### E. Code Truth Reviewer Agent

문서 설명을 실제 코드와 대조한다.

확인할 것:

* 디렉터리 구조
* 실행 명령
* Ansible playbook 경로
* Jenkinsfile stage
* schema 필드
* adapter 동작
* test 경로
* fixture
* baseline
* inventory 예시
* vault
* callback
* output 경로

### F. Duplication and Deletion Agent

중복 문서, 통합, 삭제를 판단한다.

확인할 것:

* canonical 문서는 어디인가
* 같은 설명이 반복되는가
* 삭제 가능한 문서인가
* archive로 보낼 문서인가
* decision log로 분리할 내용인가

### G. Whole Project File Auditor Agent

프로젝트 전체 파일을 검수한다.

확인할 것:

* 루트 파일 전체
* 숨김 파일
* 설정 파일
* 샘플 파일
* export 파일
* 로그 파일
* backup 파일
* docs asset
* examples
* generated output
* fixture와 baseline
* 하네스 참조 파일

코드 파일은 삭제하지 않는다.
비코드 파일만 삭제 후보로 판단한다.

### H. Markdown Lint Agent

Markdown 렌더링과 형식을 검수한다.

확인할 것:

* H1 하나
* heading level 순서
* 상대 링크
* code fence 언어
* table 렌더링
* list indentation
* 파일 마지막 newline
* GitHub alert 문법
* Mermaid 문법
* `<details>` 렌더링

### I. Safety Gate Agent

삭제와 이동을 검증한다.

확인할 것:

* 코드 파일 삭제가 없는가
* 삭제 후보가 진짜 비코드 파일인가
* 참조 검색을 했는가
* 삭제 후 링크가 깨지지 않는가
* 삭제 대신 archive가 더 안전하지 않은가
* CI, 테스트, 하네스 참조가 없는가

### J. Final Cross Reviewer Agent

다른 에이전트 결과를 반박 검토한다.

확인할 것:

* 하네스 문서를 실수로 건드리지 않았는가
* 코드 파일을 삭제하지 않았는가
* 비코드 파일 삭제 근거가 충분한가
* 삭제 후 링크가 깨지지 않았는가
* README가 너무 커지지 않았는가
* docs 구조가 더 복잡해지지 않았는가
* 문서가 실제 코드와 맞는가
* 현재 루프에서 새 문제가 0건이라고 말할 근거가 충분한가

---

## 9. 반복 루프

반드시 아래 루프를 반복한다.

### Loop 0. 기준선 수집

수행할 것:

* 전체 파일 목록 수집
* 전체 `.md` 목록 수집
* 루트 파일 목록 수집
* 사람용, 하네스용, 혼합 문서 분류
* 비코드 파일 분류
* 삭제 후보 수집
* 중복 문서 수집
* 깨진 링크 후보 수집
* 코드 대조 필요 문서 수집
* UltraCode agent별 작업 계획 작성

산출물:

```text
[Baseline]
- 전체 파일 수:
- 전체 Markdown 파일 수:
- 루트 파일 수:
- 사람용 문서:
- 하네스 문서:
- 혼합 문서:
- 비코드 삭제 후보:
- 문서 통합 후보:
- 문서 삭제 후보:
- 깨진 링크 후보:
- 코드 대조 필요 문서:
- UltraCode phase plan:
```

### Loop 1. 구조 설계

바로 수정하지 말고 먼저 구조를 설계한다.

산출물:

```text
[Documentation and File Cleanup Plan]
- README 역할:
- docs index 역할:
- canonical 문서:
- 통합할 문서:
- 삭제할 문서:
- archive로 보낼 문서:
- decision log로 보낼 내용:
- 정리할 루트 파일:
- 삭제할 비코드 파일:
- 삭제 금지 파일:
- 판단 보류 파일:
- 위험:
```

### Loop 2. 첫 번째 수정

수행할 것:

* README 재정리
* docs index 생성 또는 수정
* 중복 문서 통합
* 오래된 문서 수정
* 필요 없는 사람용 MD 삭제 또는 archive
* 긴 예시는 `<details>`로 접기
* 필요한 흐름은 Mermaid로 표현
* 중요한 주의사항만 GitHub alert 사용
* 내부 문서 링크 상대 경로로 정리
* 루트 파일 정리
* 확실한 미사용 비코드 파일 삭제
* 판단 애매한 파일은 Deferred로 남김

수정 후 바로 완료하지 마라.

### Loop 3. 코드와 파일 참조 재검수

수정한 문서와 삭제한 파일을 검증한다.

확인할 것:

* 문서의 명령어가 실제로 존재하는가
* 파일 경로가 실제로 존재하는가
* 삭제한 비코드 파일이 어디에서도 참조되지 않는가
* README 링크가 살아 있는가
* docs index 링크가 살아 있는가
* schema 설명이 실제 schema와 맞는가
* Jenkins 설명이 Jenkinsfile과 맞는가
* Ansible 설명이 실제 playbook과 맞는가
* 테스트 설명이 실제 테스트와 맞는가
* fixture와 baseline 설명이 실제 파일과 맞는가
* root 파일 정리로 자동화가 깨지지 않았는가

문제가 있으면 즉시 고친다.

### Loop 4. Markdown 렌더링 검수

확인할 것:

* H1은 파일당 하나인가
* heading level이 건너뛰지 않는가
* code fence가 닫혔는가
* code fence 언어가 지정되었는가
* table이 깨지지 않는가
* 상대 링크가 맞는가
* heading anchor가 맞는가
* GitHub alert 문법이 맞는가
* Mermaid가 렌더링 가능한가
* `<details>` 내부 Markdown이 정상인가
* 파일 마지막 newline이 있는가

문제가 있으면 수정하고 다시 검수한다.

### Loop 5. 새 문제 탐색

기존에 고친 것만 보지 마라.
프로젝트 전체에서 새 문제를 다시 찾는다.

찾을 것:

* 새로 생긴 중복 문서
* 삭제 후 생긴 고아 링크
* docs index에서 빠진 문서
* README와 docs의 설명 충돌
* REQUIREMENTS와 실제 코드의 충돌
* 루트에 남은 불필요한 비코드 파일
* 사용하지 않는 asset
* 오래된 export
* 중복 sample
* 하네스 문서 침범
* 코드 파일 삭제 위험
* 문서가 예뻐졌지만 실제 작업자가 따라 하기 어려운 부분

### Loop 6. 재수정

Loop 3, 4, 5에서 발견한 문제를 수정한다.

그다음 다시 Loop 3으로 돌아간다.

### Loop N. 종료 판단

다음 조건을 모두 만족할 때만 종료한다.

* 이번 루프에서 새로 발견된 중복 문서 0건
* 이번 루프에서 새로 발견된 코드 불일치 설명 0건
* 이번 루프에서 새로 발견된 깨진 링크 0건
* 이번 루프에서 새로 발견된 불필요 사람용 MD 0건
* 이번 루프에서 새로 발견된 미사용 비코드 파일 0건
* 이번 루프에서 새로 발견된 하네스 문서 침범 0건
* 이번 루프에서 새로 발견된 코드 삭제 위험 0건
* Markdown lint 또는 대체 검증 통과
* 삭제한 파일의 참조 검색 완료
* Safety Gate Agent 통과
* Final Cross Reviewer Agent 반박 검토에서 새 문제가 0건

한 에이전트가 완료라고 해도 끝내지 마라.
반드시 다른 에이전트가 최종 반박 검토를 수행한다.

---

## 10. 검증 명령 후보

프로젝트에 실제 존재하는 도구만 사용한다.
없는 명령을 만들어내지 않는다.

파일 인벤토리:

```bash
git ls-files
find . -type f | sort
find . -maxdepth 2 -type f | sort
```

Markdown 목록:

```bash
find . -name "*.md" -type f | sort
```

참조 검색:

```bash
grep -R "파일명" .
grep -R "상대경로" .
rg "파일명"
rg "상대경로"
```

Markdown 검증:

```bash
npx markdownlint-cli2 "**/*.md"
markdownlint "**/*.md"
markdown-link-check README.md
```

프로젝트 검증:

```bash
python -m compileall .
pytest
ansible-playbook --syntax-check os-gather/site.yml
ansible-playbook --syntax-check esxi-gather/site.yml
ansible-playbook --syntax-check redfish-gather/site.yml
```

문서 링크 검사 스크립트가 있으면 우선 사용한다.

```bash
python scripts/ai/verify_docs_references.py
```

실행하지 않은 검증은 “미실행”이라고 적고 이유를 남긴다.
실행하지 않고 통과했다고 말하지 마라.

---

## 11. 삭제 보고 형식

문서 삭제, 이동, 통합은 다음 형식으로 남긴다.

```text
[Doc Move/Delete Decision]
- 대상:
- 현재 역할:
- 문제:
- 새 위치:
- 통합 대상:
- 참조 검색 결과:
- 삭제/이동 이유:
- 남은 위험:
```

비코드 파일 삭제는 다음 형식으로 남긴다.

```text
[Non-Code File Delete Decision]
- 대상:
- 파일 종류:
- 삭제 이유:
- 참조 검색 결과:
- 코드 참조 여부:
- 테스트 참조 여부:
- 문서 참조 여부:
- 하네스 참조 여부:
- 삭제 후 검증:
- 남은 위험:
```

코드 삭제 후보는 삭제하지 않고 다음 형식으로 남긴다.

```text
[Deferred Code Cleanup]
- 대상:
- 삭제하고 싶어 보이는 이유:
- 참조 검색 결과:
- 삭제하지 않은 이유:
- 필요한 추가 검증:
```

비코드 파일이지만 확신이 없으면 다음 형식으로 남긴다.

```text
[Deferred File Cleanup]
- 대상:
- 파일 종류:
- 삭제 후보인 이유:
- 참조 검색 결과:
- 삭제하지 않은 이유:
- 필요한 추가 검증:
```

---

## 12. 루프 보고 형식

각 루프가 끝날 때마다 보고한다.

```text
[UltraCode Human Docs and File Audit Loop R{번호}]

1. 이번 루프에서 수정한 것
- 파일:
- 변경:
- 이유:

2. UltraCode agent 결과
- Repo Inventory:
- Markdown Inventory:
- Markdown Research:
- Human Reader Advocate:
- Code Truth Reviewer:
- Duplication and Deletion:
- Whole Project File Auditor:
- Markdown Lint:
- Safety Gate:
- Final Cross Reviewer:

3. 문서 통합/삭제/이동
- 대상:
- 판단:
- 근거:
- 참조 검색 결과:

4. 비코드 파일 정리
- 삭제:
- 유지:
- Deferred:
- 근거:

5. 코드와 대조한 것
- 문서:
- 확인한 코드/파일:
- 판정: 일치 / 불일치 / 수정 필요

6. Markdown 렌더링 검수
- 링크:
- heading:
- table:
- code fence:
- alert:
- details:
- Mermaid:

7. 새로 발견한 문제
- 중복 문서:
- 오래된 설명:
- 깨진 링크:
- 하네스 문서 침범:
- 코드 불일치:
- 미사용 비코드 파일:
- 코드 삭제 위험:

8. 실행한 검증
- 명령:
- 결과:
- 실패 원인:

9. 다음 루프로 넘길 항목
- 남은 문제:
- 위험도:
- 다음 조치:
```

---

## 13. 최종 보고 형식

최종 보고는 아래 형식으로 작성한다.

```text
[Final UltraCode Human Docs and File Audit Report]

1. 완료 판단
- 새로 발견된 중복 문서: 0건
- 새로 발견된 코드 불일치 설명: 0건
- 새로 발견된 깨진 링크: 0건
- 새로 발견된 불필요 사람용 MD: 0건
- 새로 발견된 미사용 비코드 파일: 0건
- 하네스 문서 침범: 0건
- 코드 파일 삭제: 0건
- 미처리 고위험 항목: 0건

2. 변경 요약
- 수정한 문서:
- 새로 만든 문서:
- 통합한 문서:
- 삭제한 문서:
- archive로 보낸 문서:
- 삭제한 비코드 파일:
- Deferred 파일:

3. UltraCode workflow 요약
- 사용한 phase:
- 사용한 agent:
- 병렬 검토 결과:
- 반박 검토에서 뒤집힌 판단:
- 최종 수렴 근거:

4. 새 문서 구조
- entrypoint:
- reader path:
- canonical docs:

5. 루트 파일 정리
- 유지:
- 이동:
- 삭제:
- Deferred:

6. Markdown 개선
- 적용한 GitHub Markdown 기능:
- Mermaid:
- details:
- alerts:
- tables:
- task lists:

7. 코드 정합성 검수
- 확인한 코드 경로:
- 확인한 명령:
- 수정한 불일치:

8. 링크와 렌더링 검수
- 내부 링크:
- code fence:
- heading:
- table:
- Mermaid:

9. 실행한 검증
- 명령:
- 결과:

10. 남은 위험
- 없음 / 있음
- 있다면 이유:
```

---

## 14. 엄격한 금지 사항

다음은 하지 마라.

* 코드 파일 삭제
* 설정 파일을 단순히 “안 쓰는 것 같다”는 이유로 삭제
* 하네스 전용 문서를 사람용 문서처럼 리라이팅
* 웹에서 확인하지 않은 Markdown 기능 사용
* 실제 코드와 대조하지 않고 문서만 예쁘게 수정
* 삭제 근거 없이 문서 삭제
* 참조 검색 없이 비코드 파일 삭제
* 링크 검사 없이 파일 이동
* README에 모든 내용을 몰아넣기
* docs 구조를 쪼개서 오히려 길을 잃게 만들기
* Mermaid를 장식처럼 남발
* alert를 강조 장식처럼 남발
* `<details>`로 중요한 내용을 숨기기
* 테스트하지 않은 명령을 검증됨이라고 쓰기
* 검증하지 못한 항목을 0건으로 보고하기
* 한 번 수정한 뒤 재검수 없이 완료하기
* UltraCode agent 결과를 종합하지 않고 단일 판단으로 완료하기

---

## 15. 최종 목표

이 명령이 끝났을 때 프로젝트는 다음 상태여야 한다.

* README가 입구 역할을 한다.
* docs가 상세 설명을 맡는다.
* 사람용 문서와 하네스 문서가 섞이지 않는다.
* 중복 문서가 없다.
* 오래된 설명이 없다.
* 내부 링크가 깨지지 않는다.
* 루트 파일이 방치되어 있지 않다.
* 미사용 비코드 파일이 정리되어 있다.
* 코드 파일은 삭제되지 않았다.
* 문서 설명은 실제 코드와 맞다.
* GitHub에서 열었을 때 읽기 쉽다.
* UltraCode agent들이 서로 검토했을 때 새 문제가 나오지 않는다.
* 새로 발견되는 문서 문제와 미사용 비코드 파일이 0건이다.

더 이상 수정, 통합, 삭제, 정리할 항목이 없고, Safety Gate와 Final Cross Reviewer의 반박 검토에서도 새 문제가 나오지 않을 때만 완료로 판단한다.
