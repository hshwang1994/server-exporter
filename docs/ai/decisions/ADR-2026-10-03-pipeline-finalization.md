# ADR-2026-10-03 — 수집 파이프라인의 시간 예산·마무리(finalization)·Callback 재설계

- 상태: Accepted (2026-10-03, 사용자 승인 Plan Phase 4 — Astra 3차 검토 조건부 통과)
- 구현: `5c2c8839`(feat) · `5683a778`(Layer B 라이브러리 분리) · `5fc09eac`(OS forks 상한 50) · `182f5228`(first_seen ip)
- 관련 rule: `.claude/rules/80-ci-jenkins-policy.md` R1 · R1-C, `.claude/rules/27-precheck-guard-first.md` R4(실패해도 봉투는 나온다)

## 컨텍스트 (Why)

`Jenkinsfile_portal` 은 결과 보존(stash)과 Callback 을 **정상 경로의 stage** 로만 가지고 있었다. Gather 가 중간에 끊기거나(stage timeout · Abort · 출력 0바이트 `error`)
Validate Schema(정적 FAIL 게이트)가 실패하면 완료된 host 의 OUTPUT 까지 Callback 에 닿지 못했다(2026-08-11 envelope 1개 소실 사례). timeout 은 작업량과 무관한 고정값
(Gather 60분 · Callback 15분 vs HTTP 300 s × 3)이었고, 콜백 보충(`on_stats`)은 강제 종료 뒤에는 돌지 않는다(WSL 실측). Redfish 모듈이 task timeout 으로 끊기면 `register` 가
없어 rescue 가 자격 오류를 **추정**할 위험이 있었다(Astra 3차 acceptance ②).

## 결정 (What)

1. **결과 전달은 pipeline `post { always }`** 의 마무리 단계다(`timeout(720 s){ node('built-in') }` 합산 제한 하나). `Validate Schema` · `Callback` stage 는 삭제했다 —
   정적 정합은 커밋 전 `scripts/ai/ci_gate.sh`(와 `Jenkinsfile_ci`)가 맡는다.
2. **배치 제한은 셸 `timeout --signal=INT --kill-after=90`** 이고 집행 예산은 `ansible-playbook` **직전에 재계산**한다(`scripts/gather_budget.sh`: 전체 150분 − 마무리 예비 990 s,
   stage 잔여(115분) − 유예 − post, host 수·채널·forks 기반 상한, 검증 강제값 중 최소; 120 s 미만이면 시작하지 않는다). node 진입 시 값은 로그용 예상값이다.
3. **2계층 마무리**: Layer A(`scripts/finalize_gather_output.py`, agent) 가 OUTPUT → CHECKPOINT → 진행 기록 기반 합성 봉투로 접수 수 == 결과 수를 맞추고, Layer B(Groovy
   `scripts/jenkins/se_finalize.groovy`, 컨트롤러가 `load`)는 Layer A 결과를 우선 쓰고 없을 때만 최소 경로로 같은 수를 맞춘다. 선택 규칙: 출처 우선순위(output > checkpoint > synthetic)
   → 같은 출처는 뒤 줄 우선, 상충 OUTPUT 은 conflicts 로 보고.
4. **콜백이 진행 이벤트를 파일로 남긴다**(`gather_progress.jsonl` host 당 append, `gather_checkpoint.jsonl`, manifest 대조, OUTPUT/CHECKPOINT fsync).
5. **Add-on 은 조립 뒤**: 조립 → `CHECKPOINT` → Add-on → `_output` 의 data.addon · errors[] 1건 · meta 시각에만 결합 → OUTPUT. role 태스크별 `apply: timeout`(300 s) —
   2026-09-21 "Add-on 전용 timeout 없음" 결정을 바꿨다(hang 한 태스크 하나를 끊는 2차 장치).
6. **task-level `timeout`**(개별 hang 격리, host 상한 아님): Linux 120 · 자격 probe 60(+`ansible_timeout: 15`) · precheck 120 · Windows 180 · ESXi 180 · Redfish 120/600/240
   (모듈 `deadline` 90/540/180 이 먼저 끝난다).
7. **Redfish 인증 증거 side-channel**: 모듈이 시도(attempt)마다 `<SE_AUTH_EVIDENCE_DIR>/<ip>/<attempt_id>.json` 을 시작 즉시 만들고 첫 자격 응답을 기록한다(비밀값 없음).
   rescue 는 현재 attempt 의 파일만 읽어 401 / 2xx 뒤 정지 / 증거 없음을 가른다. 새 failure code 는 없다.
8. 온라인 Runner 부재는 접수 후 실행 실패(`no_agent`)로 Callback 한다(Q2′). OS forks 기본 상한은 Phase 5 실측(슬롯당 PSS ≈ 36 MB) 뒤 50 으로 내렸다(`SE_FORKS_CAP_OS`).

## 결과 (Impact)

- 호출자 계약 불변: Callback 본문 `{loc, deploymentEnvironmentId, eventUuid, gatherInfoJson[]}` · endpoint · envelope 13 필드 · failure code 집합. 실패 봉투 shape 는 `build_failed_output.yml`
  모양으로 통일됐다(hostname null 등 — 의도된 정합).
- 새 산출물: `gather_manifest.json` · `gather_progress.jsonl` · `gather_checkpoint.jsonl` · `gather_final.jsonl` · `gather_finalize_report.json` · `callback_body.json` ·
  `finalize_summary.json` · `gather_auth_evidence/**`(artifact).
- 검증은 오프라인뿐이다(단위 · 렌더 · WSL 실제 ansible · Groovy 로컬 실행 · 린터). Jenkins 실제 빌드(§10-4 live 열)는 세션 권한으로 실행하지 못했다 — `docs/ai/NEXT_ACTIONS.md` GP-2 · GP-3 · GP-19.
- 남는 한계: Layer B 는 progress 기반 stage 세분을 하지 않는다(보고서에 남는 차이), Add-on 태스크 timeout 이 끊은 원격 자식 프로세스는 남을 수 있다, Runner(2.20.3)에서의 timeout 동작 재확인 전.

## 대안 비교 (Considered)

| 대안 | 기각 이유 |
|---|---|
| stage timeout 만 유지 + Callback stage 재시도 강화 | stage timeout 이 `catchError` 안에서 잡히면 ABORTED 로 확정돼 뒤 stage 가 skip 된다 — 제어가 남지 않는다 |
| 영속 outbox · Controller 재시작 복구 · 재전송 서비스(HA) | 현재 손실 사례는 같은 빌드 안의 전달 경로 손실이다. Controller crash 는 관측된 적 없고 재요청보다 비싸다 — 장기 항목으로 분리(Plan §4) |
| Groovy 한 층으로만 보충 | 정직한 stage/code 판정에는 Ansible 쪽 진행 증거가 필요하다. Groovy 는 Agent 가 사라져도 수를 맞추는 최소 경로로만 둔다 |
| `register` 부재를 자격 오류로 간주 | 관측하지 않은 것을 단정한다(CLAUDE.md §9). attempt 단위 증거 파일로 3분류하고, 없으면 `gather`/auth null |
| ICMP · 외부 상태 등으로 Interruption 원인 추정 | 셸 rc · `currentBuild.result` 만 쓰고 확정 못 하면 `interrupted_unknown` 으로 기록한다 |
