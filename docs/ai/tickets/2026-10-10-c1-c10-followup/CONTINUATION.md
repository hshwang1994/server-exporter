# 2026-10-10 C1~C10 결함 수정 후속 — 다음 세션 인계 (CONTINUATION)

> 작업지시서: "ClovirONE Gathering 코드 검수 후속 작업지시서"(2026-10-09) + 사용자 보정 8건(2026-10-10, 아래 5절 요약).
> 이 세션은 결함 수정 · 로컬 검증 · Harness 사전 확인까지 했고, **새 후보를 원격 main 에 올리는 push 가 자동 권한 판정으로 거부돼** 멈췄다(우회하지 않음).
> 남은 일은 이 문서 4절 순서로 이어 간다. 작업을 마치면 이 폴더는 지운다(rule 70 R5 — 완료된 ticket).

## 1. 현재 상태 (2026-10-10 11:15 기준)

| 항목 | 값 |
|---|---|
| 로컬 main | 이 인계 문서 커밋이 HEAD. 그 아래 `f905f145`(docs) · `410c8604`(harness) · `e27c642d`(test) — **원격에 없음** |
| GitHub(`origin`) · GitLab(`internal`) main | 둘 다 `a64654aa` (이 세션이 첫 push 로 올림) |
| production | P10 `9ddc174a` 그대로 (승격 안 함) |
| 생성 tree(runtime) | `b7e61c03d291f6275b2f5c502cdaa52cddafe45b2d0836d9980b68b8f3bb5377` · 195 파일 · class B 0 — `fa4d025c` · `a64654aa` 동일. 이후 커밋은 시험 · 문서 · 하네스뿐이라 같아야 한다 |
| Jenkins | 대기 상태. main #406 · Harness #1177 · CI #39 · production #197 이후 이 작업의 실행 없음 |

결함별 커밋(모두 로컬 → `a64654aa` 까지 원격):

| 결함 | 커밋 | 회귀 시험(대표) |
|---|---|---|
| C2 개행만 빠진 완전한 결과 줄 | `16afc210` | `test_gather_state.py` · `test_finalize_gather_output.py` · `test_run_gather.py`(Linux 전용, WSL 통과) |
| C3 Redfish 계정 다음 페이지 · 완결성 | `e1c2295c` | `test_account_pagination_c3.py`(40) |
| C4 Redfish 하위 조회 실패 | `69faa107` | `tests/integration/test_redfish_subresource_failures_c4.py`(9) |
| C5 인증 뒤 vendor 로 adapter 재선택 | `5a3b99ed` | `test_redfish_vendor_reselect_c5.py`(21) |
| C6 Windows FC PortSpeed | `75c55e38` | `test_windows_storage_powershell_static.py`(실제 PowerShell) |
| C7 lscpu 버전별 캐시 합계 | `cce90cb4` | `test_linux_cpu_cache_c7.py`(18) |
| C8 Windows 비종료 오류 · DIMM 일부 | `e9b77177` | `test_windows_nonterminating_c8.py`(6) |
| C9 ESXi 부가 조회 실패 | `1672538a` | `test_esxi_partial_failures_c9.py`(12) |
| C10 별도 sudo 비밀번호 | `5bada078` | `test_become_password_c10.py`(13, root · NOPASSWD 포함) |
| C1 결과 회수 매체 선택 | `e07da9ad`(제품) · `fa4d025c`(Harness 5종 · CI 목록 · prodgen 필수 집합) | `test_jenkinsfile_portal_finalize.py` · Harness `recover_*` 5종 |
| 시험 격리 · G14 | `a64654aa`(C4 · C5 시험 전역 상태 되돌림) · `e27c642d`(주석 기준 index 제거) | — |

이미 확인한 것(증거: 저장소 밖 `C:\github\ClovirONE\evidence-c1-c10-2026-10-10\`):
- WSL LF clone `ci_gate` PASS — `a64654aa` · `f905f145` 각각 unit/e2e/regression 4,679 통과 · integration 333 · corpus 20/20 · 3채널 syntax-check(`local/ci_gate_wsl_2.log` · `_3.log`).
  첫 실행(`fa4d025c`)의 1건 실패(시험 순서 의존)는 `a64654aa` 로 고쳤다(`local/ci_gate_wsl.log`).
- Windows 실제 PowerShell 시험 506 통과(`local/windows_powershell_pytest.txt`). Groovy 2.4.21 CONVERSION OK(portal · Byid · ci · harness · se_finalize).
- C1 로컬 구동(가짜 step, 실제 Jenkins 아님) 12/12 — 종전 코드는 2대 + 실패 1대를 보내는 것도 재현(`c1_local/`).
- 로컬 prodgen: build OK(class B 0) · verify `--skip-live` G01~G10 · G16~G18 · G20 PASS · **G14 는 `a64654aa` 에서 1건 FAIL** → `e27c642d` 로 고침(생성 tree 사본에서 그 파일 45 통과). 전체 G14 재실행은 아직이다.
- **실제 Jenkins Harness 사전 확인 10/10 PASS(`a64654aa`)**: #1168 `recover_final_archive_over_snapshot` · #1169 `recover_flag_unwritten_archive` · #1170 `recover_partial_archive_keeps_stash` ·
  #1171 `recover_checkpoint_only_archive` · #1172 `recover_archive_unavailable_stash` · #1173 `finalize_limit_cumulative` · #1174 `stash_fail` · #1175 `raw_fallback` · #1176 `checkpoint_only_b` · #1177 `infra_wait_expired`
  (증거 폴더 `evidence-c1-c10-2026-10-10/jenkins/harness_precheck.json` — 저장소 밖).
- 감사 재현 전/후(`pre/` · `post/`): C2 재개 불가 → 정상 재개, C3 다음 페이지 계정 PATCH · 중복 슬롯이면 쓰기 0, C4 Volumes · Port 오류 기록, C6 4→10 · 8→4 · 16→8,
  C8 · C9 오류 기록. C7 은 감사 입력에 `lscpu --version` 줄이 없어 고친 코드가 추측하지 않고 `null`(버전이 있는 경우는 C7 시험이 확인).

## 2. 세션별 담당

| 세션 | 담당 | 대상 |
|---|---|---|
| 이 세션(종료) | C1~C10 수정 · 로컬 검증 · Harness 사전 확인 · 인계 | — |
| 다음 세션 | 4절 전부(push · main Job · CI · 승격 · production · 문서 · 정리) | main · production 브랜치, 공유 Jenkins Job 4개 |

다음 세션이 끝날 때까지 다른 세션은 main · production push, 공유 Jenkins Job(`clovirone-server-gather-main` · `-harness` · `-ci` · `clovirone-server-gather`) 실행, vault 수정을 하지 않는다.

## 3. 세션 간 의존성

- 원격 main 이 이 HEAD 와 같아야 main Job · Harness · CI · 승격을 **같은 SHA 하나**로 묶을 수 있다(main Job 은 원격 main 끝을, Harness 는 `MAIN_SHA` commit 을 받는다).
  원격 `a64654aa` 그대로 CI 를 돌리면 Prodgen Verify G14 가 1건 실패한다(`e27c642d` 가 없다).
- Jenkins 접속 netrc 와 승격용 vault 비밀번호 임시 사본은 넘기지 않았다(이 세션 종료 때 삭제). 다음 세션이 사용자에게 받아 그 세션 scratchpad 에만 둔다.
- Jenkins 스크립트(이 세션이 만든 것, 비밀값 없음): `C:\github\ClovirONE\evidence-c1-c10-2026-10-10\scripts\jenkins\` — `jlib.py`(netrc 경로는 `SE_JENKINS_NETRC` 로) ·
  `harness_lanes.py` · `main_matrix.py` · `compare_bodies.py` · `ci_run.py` · `prod_regression.py`. Byid 재생성 `scripts\regen_byid.py`, Groovy jar `tools\`.

## 4. 다음 세션 순서 (첫 지시 템플릿 포함)

첫 지시 예시(사용자 → 다음 세션):

```text
docs/ai/tickets/2026-10-10-c1-c10-followup/CONTINUATION.md 를 읽고 4절 1번부터 이어서 진행하라.
Jenkins 접속: admin / <비밀번호> — 그 세션 scratchpad netrc(권한 600)에만 저장하고 끝나면 지워라.
main push 와 production 승격 push(origin · internal)는 승인한다.
```

1. **push** — `git push origin main`(origin 에 GitHub · GitLab push URL 둘). `git ls-remote origin|internal refs/heads/main` 이 둘 다 로컬 HEAD 인지 확인. 이 HEAD 를 후보 X 로 고정.
   이후 다른 커밋을 더하면 X 가 바뀐다 — 문서 결과 기록은 승격 뒤 커밋으로 한다(6번).
2. **(선택) 로컬 G14** — `python -m scripts.ai.prodgen build --sha X --out <scratch>/prodtree` → `verify --tree … --only G14`(Windows 약 10분). CI 가 다시 하므로 건너뛰어도 된다.
3. **main Job 매트릭스** — `SE_JENKINS_NETRC=<netrc> python main_matrix.py X <repo> <out>/main_matrix.json`(약 40분, 15빌드: 지난 #394~#406 입력 13 시나리오 +
   R10 Redfish 10대(production #189 입력) + LB Linux B(production #186 입력)). 기대 결과: T2 · S1~S5 · E2E-D · E2E-E · R10 · LB SUCCESS, T6 UNSTABLE, E2E-A SUCCESS 또는 UNSTABLE,
   T5 ABORTED, T17 · E2E-A2 FAILURE. checkout == X. 기존 도달 불가 대상(.135 · .145 · .165 · BMC 10.100.15.1 프로토콜 · 10.100.15.3 · 10.50.11.231)은 정상 Precheck 실패다.
4. **대상별 대조** — `python compare_bodies.py <out>/main_matrix.json <out>/compare.json`. 지난 빌드와 status · 섹션 · failure stage/code · errors · 데이터 경로를 대조한다.
   기대: 정상 경로는 차이 없음. 실제 장비가 하위 조회에서 오류를 돌려주면 C4 · C9 의 새 오류 1건이 생길 수 있다 — 그 장비 · 경로를 기록한다(결함 아님, 종전엔 침묵).
5. **CI** — `python ci_run.py X <repo> <out>/main_matrix.json <out>/ci`(약 50분). Harness 목록은 후보의 `Jenkinsfile_ci` 기본값을 명시해 넘긴다(main 50 · tree 23 —
   Jenkins 는 지난 빌드의 기본값을 들고 있다). `PROMOTE=true` · `PROMOTE_DRY_RUN=true` · `PROMOTE_SHA=X`. 필수 단계 전부 PASS · Verify COMPLETE_PASS 확인.
6. **승격(세션 CLI)** — `git config core.autocrlf` 가 이 PC 에서 `true` 다(GP-45) → 승격하는 동안만 `false` 로 두고 끝나면 되돌린다. vault 비밀번호는 저장소 루트 `.vault_pass` 의
   임시 사본(권한 600)을 쓰고 끝나면 지운다. `python -m scripts.ai.prodgen promote --sha X --dry-run` → 실제:
   `promote --sha X --verify-report <ci>/prodgen_verify_report.aggregated.json --e2e-evidence <ci>/e2e_evidence.json --ci-stage-results <ci>/ci_stage_results.json --ci-build <CI 번호> --netrc <netrc> --vault-password-file <임시 사본> --push-remote origin,internal`.
   확인: origin · internal · 로컬 production 같은 SHA, `drift-check --production origin/production` PROVENANCE, 새 clone tree hash == `b7e61c03…`, trailer(Main-SHA X · Previous-Production `9ddc174a`).
7. **production** — `python prod_regression.py <P11 SHA> <out>/prod.json`: canary(os .161~.163) 먼저, 맞으면 Linux A · Linux B · Windows · ESXi 6 · Redfish 10. checkout == P11 · Portal HTTP 2xx ·
   대상별 본문을 지난 production #185~#189 · #197 과 대조.
8. **문서 · 증거 · 최종 push** — `docs/ai/CURRENT_STATE.md` · `docs/ai/catalogs/TEST_HISTORY.md`(이 세션의 중간 기록에 Jenkins 결과를 더한다) · `docs/reference/decision-log.md` 2026-10-10 ·
   `docs/operate/09-production-branch.md` 7절(P11) · 새 `tests/evidence/2026-10-10-full-audit.md`(만들 예정 — 2026-10-10 전체 감사 요약 1편에 C1~C10 결함별 전후를 넣는다; · 재현/fixture/실서버 구분 · 빌드 번호 · checkout SHA · 대상 분류 ·
   미확인 항목) · 이 ticket 폴더 삭제 · `docs/ai/NEXT_ACTIONS.md` 의 이 후속 항목 정리. 커밋 → `git push origin main` → 양 원격 최종 SHA 확인.
   승격 뒤 커밋이 문서 · 시험 기록뿐이면 runtime 차이 없음(생성 tree hash 동일)을 확인해 기록한다(재승격 · 전체 E2E 반복 없음 — 사용자 보정 8).
9. **정리** — 그 세션의 netrc · vault 임시 사본 · WSL clone · 생성 tree 사본 삭제. 다른 프로젝트 Runner 설정 · 라벨 · token 은 건드리지 않는다.

## 5. 에스컬레이션 포인트 · 지켜야 할 것

- push · 승격이 자동 권한 판정으로 거부되면 우회하지 않는다 — 사용자에게 `! <명령>` 직접 실행 또는 `/permissions` 허용을 요청한다.
- main Job · CI · Harness 결과가 기대와 다르면 승격하지 않는다. 원인을 고친 커밋은 새 후보다(1번부터).
- 운영 기준(작업지시서 §4): Precheck 실패는 확정(재수집 없음) · 실행 기반 대기 72 h · 같은 Runner · 작업 폴더 · 끝난 대상 재수집 금지 · 실제 수집 누적 6 h · CPU/메모리 사전 차단 없음 ·
  새 timeout · 시험 파라미터 없음 · forks 50 · Jenkinsfile 에 로그 보관 설정 없음 · yi/ic/cj Windows `infraops` 도메인 계정 유지 · production 은 prodgen 생성 tree 만 · 새 큐 · DB · 스케줄러 없음.
- 사용자 보정 요약: C1 CHECKPOINT 단독 회수 유지 · 매체는 기존 검문으로 평가(파일 존재 아님) · 일부 보관본은 더 나은 stash 에 진다 · 격리 폴더 · 정리 결과 파일이 없으면 두 번째 보관 없음 /
  C2 치환 전 원래 bytes 로 엄격 UTF-8 판정 / C3 불완전 열거 쓰기 0 · 일치를 본 경우만 `account_existed` · 21개 소비자 불변 / C6 미상 코드 `null` / C8 일부 DIMM 이면 `grand_total_gb null` ·
  C9 결과 키 부재 = 실패 / C10 로그인 · sudo 비밀번호 차이는 정상 구성(위험 · 차단 아님) / 최종 커밋 뒤 양 원격 SHA 재확인.
- 실장비 미확인으로 남는 것(이번 범위에서 해소 대상 아님): GP-57(실장비 계정 쓰기 응답 유실) · lscpu 2.34~2.36 실장비 · 별도 sudo 비밀번호를 쓰는 실서버 · C6 미상 코드 · Portal 화면 반영.
