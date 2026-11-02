# ADR-2026-11-02 — 사내 GitLab 을 고객사 형태로 (`main` = production) · jenkins-prod 는 GitHub

- 상태: Accepted (2026-11-02, 사용자 결정 — 아래 승인 기록) · GitLab 정리 실행 2026-11-02(아래 실행 기록)
- 관련: rule 93 R1 · R2 예외 2 · R4 · R7 · rule 24 R5 · `CLAUDE.md` §14 · ADR-2026-05-01-autonomous-main-push(§2 대체) ·
  ADR-2026-10-03-production-generation · `docs/operate/09-production-branch.md`

## 컨텍스트 (Why)

- 2026-05-01 부터 `origin` 은 push URL 이 둘이었다(GitHub + 사내 GitLab `10.100.64.156/root/server-expoter`). 그래서 개발 `main` · 작업 브랜치 ·
  `production` 이 GitLab 에도 그대로 복제됐다. 2026-11-02 기준 GitLab 에는 `main`(개발) · `production` · 작업 브랜치 5개가 있었다.
- 사용자는 2026-11-02 GitLab 을 **고객사처럼** 다루기로 정했다. GitHub 는 `main` · `production` 을 그대로 두고, GitLab 은 개발 `main` 을 지우고
  `production` 이 `main` 이 된다. jenkins-prod 의 CI · Job 은 GitLab 이 아니라 GitHub 에 연결돼 있어야 한다.
- prodgen(production 생성기)은 두 원격 모두 `refs/heads/production` 에 같은 커밋을 올리는 구조였다(deploy policy: 둘 다 아니면 실패).
  이 구조 그대로면 GitLab 에 `production` 이 있어야 해서 고객사 형태(브랜치 `main` 하나)와 맞지 않는다.
- G19 는 이미 "생성 tree 를 브랜치 `main` 하나뿐인 저장소에 올려 clone 해서 실행" 하는 고객사 형태 검사다. 이번 결정으로 GitLab 의 실제 형태가 G19 의 가정과 같아진다.

## 결정 (What)

1. **GitHub(`origin`)** — `main`(개발) · `production`(배포) · 작업 브랜치. 변경 없음. jenkins-prod 의 모든 Job 은 GitHub 저장소를 SCM 으로 쓴다.
2. **사내 GitLab(`internal`)** — 브랜치는 `main` 하나. 그 커밋은 GitHub `production` 과 같다. 개발 `main` · `production` · 작업 브랜치는 두지 않는다.
3. **prodgen** — 원격마다 production 을 담는 ref 를 따로 둔다: `DEPLOY_TARGET_REFS = {"origin": refs/heads/production, "internal": refs/heads/main}`
   (`scripts/ai/prodgen/__init__.py` `remote_ref`). promote · restore · push-sync · G20 · `remote_baseline` 이 원격마다 그 ref 를 읽고 쓴다.
   로컬 ref 는 그대로 `refs/heads/production` 이다. 기본값이 아닌 `--production-ref`(시험용 ref)는 매핑하지 않는다 — 고객사 `main` 에 시험 ref 가 실리지 않게.
   deploy policy(실 승격 · 복구는 두 원격 모두 아니면 거부)는 바꾸지 않는다.
4. **공유 push URL 거부** — 한 저장소가 대상 ref 가 서로 다른 두 원격의 push 대상이면(예: `origin` 에 GitLab push URL 이 다시 들어감) GitLab 에
   `production` 이 생긴다. 실 promote · restore · push-sync 는 아무것도 쓰기 전에 거부하고, dry-run 은 `preview_refusals` 로 보여 준다.
   저장소 동일성은 scheme · 자격 정보 · port · `.git` · 끝 슬래시를 무시한 host/path 로 본다(`_repo_key` — http 와 https 를 같은 GitLab 으로 본다).
5. **작업 PC git 설정** — `origin` 에서 GitLab push URL 제거(GitHub 하나만). `remote.internal.push = refs/heads/production:refs/heads/main`
   (refspec 없는 `git push internal` 이 개발 브랜치 대신 로컬 production 만 GitLab `main` 으로 보내는 안전장치).
6. **GitLab 저장소 정리** — 보호 설정 · 기본 브랜치 · 미러링 · Webhooks 는 GitLab 관리 화면 작업이라 사용자가 한다. 브랜치 갱신 · 삭제는 보호가 풀린 뒤
   push 로 한다. GitLab 은 보호를 풀어도 기본 브랜치를 지울 수 없다. 절차는 `docs/operate/09-production-branch.md` 8절, 2026-11-02 실행은 아래 실행 기록.

## 결과 (Impact)

- 코드: `scripts/ai/prodgen/` 5개 파일(`__init__.py` · `promote.py` · `verify/gates_promotion.py` · `cli.py` 도움말 · `evidence.py` 설명 1줄)과
  `tests/unit/prodgen/test_promotion_cycle.py`. 하네스 경로라 production tree(runtime-only)는 바뀌지 않는다 — 이 변경 자체로는 승격할 것이 없다.
- prodgen 소스가 바뀌어 `generator_hash` 가 달라진다. 이 커밋 이전 SHA 로 만든 CI 검증 보고서는 binding 이 맞지 않아 `--verify-report` 로
  재사용되지 않는다 — 다음 승격은 이 커밋 이후 main SHA 의 CI 보고서로 한다.
- GitLab 정리 전에는 실 승격 · push-sync 가 "remotes disagree on production"(GitHub production ≠ GitLab main) 으로 **쓰기 전에** 멈춘다.
  fail-closed 이고 일부만 바뀌는 일은 없다. 2026-11-02 정리로 두 원격이 같아져 해소됐다(실행 기록).
- 다른 작업 사본(다른 PC · WSL clone)에 dual push 설정이 남아 있으면 prodgen 이 거부하고, 맨 `git push` 는 작업 브랜치를 GitLab 에 다시 만든다.
  각 사본에서 GitLab push URL 을 지워야 한다(rule 93 R7 재구성).
- GitLab `main` 에는 production 생성 대상(`production_manifest.yml`)만 남는다. `Jenkinsfile_portal_Byid` 같은 main 전용 파일은 GitLab 에서 사라진다.
  2026-10-09 ADR 은 Byid 를 쓰는 Job 이 이 Jenkins 밖에 있을 수 있다고 적었다 — 그런 소비자가 있으면 깨진다.
- production 이력은 첫 production(`4ce90a00`, parent `d549596d`)에서 개발 이력과 이어져 있다. GitLab `main` 의 조상에는 옛 개발 커밋이 남는다.
  이력 재작성은 하지 않는다(요청 없음 · `CLAUDE.md` §14 금지).
- CI 의 Promote stage 는 GitLab 자격(`se-gitlab-push`)이 없어 지금도 dry-run 만 한다. 자격이 생기면 같은 매핑(GitLab 은 `main`)으로 올린다 — `Jenkinsfile_ci` 수정 없음.
- Add-on 저장소(`clovirone-server-gathering-addon`, GitLab)는 별개 저장소라 이 결정의 범위 밖이다. 사용자 지시(2026-11-02)로 그대로 둔다.

## 대안 비교 (Considered)

- *dual push 유지(GitLab = 개발 미러)* — 거부. 사용자 결정과 반대이고, 고객사 형태(브랜치 `main` 하나)를 만들 수 없다.
- *GitLab 에 `production` 이름 유지, 개발 `main` 만 삭제* — 거부. 사용자는 "production 브랜치가 main 이 되는 것" 을 요구했다.
  고객사 checkout 형태(`main` 하나)와도 어긋난다.
- *GitLab `main` 을 production 커밋만 있는 새 이력(orphan)으로 재작성* — 거부. 요청 범위 밖이고 force push · 이력 재작성이 필요하며,
  G18 · G20 이 기대는 production parent 사슬과 `Main-SHA` 조상 검사가 끊긴다.
- *GitLab 납품을 prodgen 밖의 별도 도구(예: CI 미러 Job)로* — 보류. 같은 고객사 ref 에 쓰는 길이 둘이 된다. prodgen 의 "둘 다 아니면 실패" 정책이
  이미 두 원격의 일치를 지키므로 대상 ref 매핑만 더했다.

## 실행 기록 (2026-11-02)

- 정리 전 GitLab: 기본 브랜치 `main`(옛 개발 `e8b5ae9b`) · `production` `d464de4b` · 작업 브랜치 5개. GitHub `production` 도 `d464de4b`.
- 사용자가 GitLab `main` 의 보호를 풀었다. 보호를 풀어도 기본 브랜치는 지울 수 없어서, 09-production-branch 8절 2~5단계(기본 브랜치 두 번 변경 ·
  `main` 삭제 · 재생성) 대신 GitLab `main` 을 production 커밋으로 **한 번 강제 갱신**했다. rule 93 R1(force push 금지)의 1회 예외이며 사용자가 승인했다(승인 기록).
  - 갱신 전 확인: `e8b5ae9b` 는 GitHub `main` 의 조상이다(`git merge-base --is-ancestor`) — 잃는 커밋 없음.
  - `git push --force-with-lease=refs/heads/main:e8b5ae9b2f0e4075d1e9f65d6e47475e3bd7b17c internal d464de4b785a1c1a4b738c347578933d2c742ab6:refs/heads/main`
    → `+ e8b5ae9b...d464de4b -> main (forced update)`. lease 로 GitLab `main` 이 `e8b5ae9b` 일 때만 바뀌게 했다.
  - `git push internal --delete production` → `[deleted] production`.
- 작업 브랜치 5개는 사용자 지시("작업중인게 있어서 나중에 없어질 예정")로 남겼다. 사용자가 작업을 마친 뒤 지운다.
- 정리 뒤 확인(생성기 main `d158ce30`, `git fetch --prune internal` 뒤): GitLab HEAD → `main` `d464de4b` · `production` 없음 · 작업 브랜치 5개.
  `prodgen push-sync --remote origin --remote internal --dry-run` ok · 할 일 0 · `preview_refusals` 없음(`remote_refs` origin → `refs/heads/production`,
  internal → `refs/heads/main`). `prodgen drift-check --production origin/production` ok · `PROVENANCE`(C_tree_hash · D_trailers · A1 True).
- 남은 것(사용자): GitLab `main` 재보호(push · merge 는 Maintainer, force push 불허) · Mirroring · Webhooks 확인 · 작업 브랜치 삭제.
  강제 갱신 예외는 이 1회로 끝났다 — 이후 GitLab 에 대한 force push 는 다시 금지다.

## 승인 기록

| 일자 | 승인자 | 내용 |
|---|---|---|
| 2026-11-02 | hshwang1994 | "github에는 main이랑 production을 그대로 냅두고 … gitlab에는 현재 main 브랜치를 지우고 production 브랜치가 main이 되는거임 gitlab이 고객사인것처럼 … jenkins-prod 에 연결된 각종 ci 및 액션들은 gitlab이랑 연결돼있는게아니라 github랑 연결돼있어야함. 작업진행해줘. 하네스에 저장해주고 이부분" |
| 2026-11-02 | hshwang1994 | "main의 보호를 풀었어 나머지는 너가 진행해줘. GitLab 작업 브랜치 5개 삭제는 하지마 지금 작업중인게 있어서 나중에 없어질 예정임. Add-on 저장소는 냅둬라 지금 범위가 아님" |
| 2026-11-02 | hshwang1994 | 선택지 "강제 갱신 1회 허용" — GitLab `main` 을 lease 를 건 force push 1회로 GitHub `production`(`d464de4b`)에 맞추고 GitLab `production` 을 삭제. 사용자 몫: `main` 재보호(force push 금지) · Webhooks · Mirroring 확인 |
