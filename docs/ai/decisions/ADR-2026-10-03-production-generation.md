# ADR-2026-10-03 — production 브랜치는 고정 main SHA 에서 생성한 runtime-only tree 다 (prodgen)

- 상태: Accepted (2026-10-03, 사용자 승인 Plan Phase 7a). **7b(시험 반영) 는 보류** — 아래 "결과" 참조
- 구현: `dcfbfded`(prodgen 생성기 · gate · provenance · tests 69) · `6937ba3a`(G14 제외 표식)
- 관련 rule: `.claude/rules/93-branch-merge-gate.md` R2 예외 2 · R4, `.claude/rules/24-completion-gate.md` R5, `.claude/rules/90-commit-convention.md` R5, `CLAUDE.md` §14

## 컨텍스트 (Why)

production 브랜치는 `scripts/ai/promote_to_production.sh` 가 denylist 정규식으로 하네스 경로만 빼고 main 의 파일 상태를 복사해 만들었다(983 파일 · 10.4 MB). 테스트 · 문서 ·
스키마 · 운영자 도구가 그대로 들어가고, 설명성 주석이 남고, sync 커밋에 main SHA 가 없어 provenance 가 없었다(H1). 생성물 gate · 결정성 · drift 검출도 없었다(H2).
지시서는 "production 은 runtime 만, 설명성 주석 전부 자동 제거, 전체 tree gate" 를 요구했다.

## 결정 (What)

1. **입력은 git object store 의 고정 SHA 뿐**이다(작업 트리 금지 — CRLF 체크아웃 차이). 출력은 격리 디렉터리, 현재 checkout 은 바꾸지 않는다, 결정성(같은 SHA + 규칙 → 같은 tree hash).
2. **allowlist manifest** `production_manifest.yml` 이 포함 파일을 **언어 명시**로 정한다(확장자 추정 금지). `runtime_roots` 아래 추적 파일은 allowlist · ignore · excluded 중 하나여야 한다.
   `forbidden`(.claude · docs · tests · schema · scripts/ai · jenkins · Jenkinsfile_ci …)은 fail-closed. 제외 사유 기록: `common/vars/status_rules.yml`(주석에서만 참조),
   `adapters/registry.yml`(런타임 미참조 — adapter_loader 는 채널 디렉터리 glob), `scripts/bootstrap_vault_encrypt.sh` · `scripts/verify_account_provision.sh` · `jenkins/**`(운영자 도구).
3. **주석 제거는 A/B 분류**: A(runtime-required/legal — 셔뱅 · PEP 263 · 플러그인 `DOCUMENTATION` · `#requires` · argparse 가 읽는 모듈 docstring)만 보존하고, 제거를 **증명하지 못한**
   주석은 B(`unstripped-pending`)로 남아 provenance 대신 실패 보고를 내며 승격을 막는다. 언어별 검증: Python `ast.dump` 동치, YAML `safe_load` + `compose` 동치, Jinja AST 동치
   (Ansible templar 설정 기준 — `policy.jinja_trim_blocks: ansible`), 임베디드 셸은 두 lexer 합의 + `bash -n`/`sh -n`, PowerShell 은 실제 파서 토큰 스트림(`pwsh`/`powershell.exe` 없으면 B),
   Groovy 재토큰화, INI configparser, vault 바이트 동일. 모든 제거기는 편집 로그를 내고 엔진이 diff-shape 불변식으로 2차 검증한다.
4. **gate G01~G17**: allowlist 무결성 · EOL · 의미 검증 · 잔존 스캔 · dependency closure · 모드 · vault/평문 스캔 · 3채널 syntax-check · config dump · Jenkins 린터 ·
   tests overlay(`-m "not source_text"`) · 모듈 smoke · inventory 동치 · 결정성. `drift-check`(LEGACY/C/D/A1/A2), `promote`/`restore` 는 git plumbing(`read-tree --empty` 임시 index →
   `write-tree` → `commit-tree -p` + trailer `Main-SHA/Tree-Hash/Generator-Version/Rules-Version/Previous-Production/CI-Build/Generated-At`), plain push(non-ff 거부 = CAS), 양 remote 대조.
5. `scripts/ai/promote_to_production.sh` 는 **deprecation shim**(안내 후 exit 1)이다. 1 cycle 뒤 삭제한다.
6. 승격의 전제는 **G01~G20 전부 + 승격 직후 production Job canary(7c)** 다. canary 를 돌릴 수 없는 세션에서는 승격하지 않는다.

## 결과 (Impact)

- main `f1221234` 기준 생성 tree **192 파일 · 1.04 MB**(production 983 파일 · 10.4 MB), 제거 주석 6,377 전행 + 562 꼬리, A 보존 57줄(셔뱅 9 · coding 17 · 셸 셔뱅 8 · argparse docstring 23),
  **B 0**, **G01~G17 PASS**(G14 는 저장소 메타를 읽는 테스트 7 파일에 `source_text` 표식 + overlay 수집 오류 수정 뒤 3,674 passed — `tests/evidence/2026-10-03-final-report.md` 7절).
- **7b 보류**: 이 세션은 Jenkins 빌드를 실행할 수 없어(권한 모드) production Job canary(7c)를 돌릴 수 없다. 검증되지 않은 파이프라인(Phase 4 재설계 + Phase 1.5 입구)이 Portal 이 쓰는
  브랜치에 올라가는 것을 피하기 위해 `promote --dry-run` 까지만 한다. 재개 조건 · 명령은 `docs/operate/09-production-branch.md`.
- rule 93 R2 예외 2 · R4, rule 24 R5, rule 90 R5, CLAUDE.md §14 의 "promote_to_production.sh 자동 승격" 문구는 prodgen 기준으로 바뀐다. `--no-verify` 예외는 필요 없어졌다
  (plumbing 커밋은 훅을 거치지 않는다).
- 환경 전제(사용자 항목): CI Runner `pwsh`(없으면 PowerShell 주석이 B 로 남아 승격 차단 — GP-16), CI Job 등록(GP-15), write credential(Phase 7 CI stage).

## 대안 비교 (Considered)

| 대안 | 기각 이유 |
|---|---|
| 기존 `promote_to_production.sh`(denylist sync) 유지 + 주석 제거 추가 | denylist 는 새 경로가 생기면 조용히 새고, 작업 트리를 읽어 CRLF 차이가 섞이며, provenance · 결정성 · gate 가 없다 |
| `git merge main → production` | 하네스 누출(rule 93 R2 금지), runtime-only 가 될 수 없다 |
| 주석을 보존 예외 목록으로 넓게 허용(트레일링 · 임베디드 · 파싱 불가 블록) | 지시서 "설명성 주석 전부 제거" 위반. 증명 못 하면 B 로 **차단**하는 쪽을 택했다(Astra R1) |
| 범용 parser framework | 현재 tree 의 패턴만 지원하고 새 패턴은 fail-closed B — 범용화는 비용 대비 가치가 없다 |
| canary 없이 7b 진행 | Plan 7b→7c 는 한 쌍이다. Portal 가 바로 쓰는 브랜치라 되돌림(restore)만으로는 그 사이 수집 실패를 되돌릴 수 없다 |
