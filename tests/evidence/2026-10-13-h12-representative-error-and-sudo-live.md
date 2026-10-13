# 2026-10-13 — 정상 경로 failed 봉투의 errors[0] 대표 문장(H12 후속) · Linux sudo 프로브 live 매트릭스

같은 날 앞선 작업(`2026-10-13-sudo-fallback-serial-required.md`, production P14)이 NEXT_ACTIONS 에 남긴 두 항목을 닫은 기록이다.

## 1. 범위

| 항목 | 무엇 | 커밋 |
|---|---|---|
| H12 후속 | `common/tasks/normalize/build_output.yml` 에 "ensure representative error" 1 태스크 추가. 정상 경로에서 성공 섹션 0개로 `status=failed` 가 됐을 때(문장 `gather_no_data`) `errors[0]` 이 섹션 오류였던 것을 rescue(`build_failed_output.yml`)와 같은 규칙으로 대표 오류(채널 표시 `<linux|windows|esxi|redfish>_gather` · message = failure_reason · detail = 섹션 결과 요약)로 바꾼다. 섹션 오류는 뒤에 보존(완전히 같은 원소만 제외 · 상한 10 · 절단 표시). errors[0] 이 이미 그 문장이면 no-op. 문장을 새로 만들지 않는다 | `75ca57c2` |
| sudo live 매트릭스 | `tests/integration/test_sudo_probe_live.py`(-m live, 기본 skip) + `tests/fixtures/sudo_live/{harness.yml, fake_sudo.sh}`. 실 Linux 대상에서 `preflight.yml → try_sudo.yml` 을 돌려 분류를 결과 모양으로 재확인. 거부 · rc 1 · 무응답 · 부재는 가짜 sudo(PAM 미접촉), 통과 · 정책 거부 · NOPASSWD 는 실 sudo | `341433af` |

건드리지 않은 것: `build_status.yml` 로직 · `build_failed_output.yml` · `require_serial.yml` · failure_code/stage enum · envelope 13 필드 · 문장 카탈로그.

## 2. 정적 검증 (작업 PC)

| 검사 | 결과 |
|---|---|
| 전체 pytest(unit · e2e · regression, Windows Python 3.13) | 5,113 passed · 36 skipped · 7 xfailed · 0 failed (신규 e2e 15건 포함) |
| `ansible-playbook --syntax-check` 3채널 (WSL ansible-core 2.20.7) | os · esxi · redfish 통과 |
| 실제 엔진 통합 (WSL) `test_build_output_no_data_playbook.py` 7 + `test_addon_hook_playbook.py` 16 | 23 passed |
| Jinja compile / namespace 훅 · `verify_harness_consistency` · `verify_vendor_boundary` · `validate_field_dictionary` · `output_schema_drift_check` · PROJECT_MAP fingerprint | 통과 |
| pre-commit 훅 (docs20 sync — `03-fields.md` 동반 · additive-only — 추가 줄만 · commit-msg) | 통과 |

## 3. 실제 엔진 통합 — `tests/fixtures/no_data/harness.yml` (connection local, json_only 콜백)

| 사례 | 관측 |
|---|---|
| `no_data` (linux, 섹션 오류 2) | status failed · gather/GATHER_FAILED/`gather_no_data` · errors = [대표(`linux_gather`, detail `success_sections=0; supported=system,cpu; failed=system,cpu`), cpu 오류 2(detail 보존), Serial 오류(require_serial, `cause=not_collected`)] · 13 필드 |
| `no_errors` | errors = [대표, Serial 오류] |
| `many` (섹션 오류 12) | 대표 + 9 + 절단 표시(`3건`) + Serial 오류 = 12 |
| `windows` | 대표 section `windows_gather`, Serial 오류도 `windows_gather` |
| `esxi` · `redfish` | 대표 section `esxi_gather` · `redfish_gather`, Serial 규칙 없음 |
| `partial` (대조군, Serial 있음) | status partial · failure_* null · errors 불변(1) · `details.serial_number` 없음 |

## 4. sudo live 매트릭스 — 10.100.64.132 (Ubuntu 24.04, sudo 1.9.15p5, pam_faillock 없음 → 예산 3)

임시 계정은 앞선 작업에서 사용자가 승인한 범위(계정 2개)로 orchestrator 가 만들고 끝나면 지웠다: `se_sudotest`(sudo 그룹, 비밀번호 요구) · `se_nosudo`(sudo 없음).
드롭인 없음. 비밀번호는 생성 시 메모리와 WSL `/tmp` 0600 파일에만 있었고 출력 · 저장소 · 커밋에 없다. 종료 뒤 `id` → "no such user" 둘 다 확인, `/home` 에 cloviradmin · infraops 만.

| 사례 | 계정 · 입력 | 관측 (`_l_sudo_meta`) |
|---|---|---|
| `nopasswd` | cloviradmin | ok · mode nopasswd · attempted 0 · attempts [] · become_pass 비움 · policy {pam_files 2, lock_module false, deny 3, even_deny_root false} · max_rejections 3 |
| `login` | se_sudotest, Vault 후보 0 | ok · mode password · used_label login · attempts [{login, rc 0, ok}] · fallback_used false |
| `vault_dup` | se_sudotest, Vault 후보 = 로그인 값 | attempted 1 (login 만) — 같은 값은 한 번 |
| `denied` | se_nosudo | mode denied · outcome policy_denied · attempts [{login, rc 1, denied}] · auth.log `user NOT in sudoers` · become_pass 비움 |
| `reject` (가짜 sudo) | se_sudotest, 후보 [login, wrong×3] | mode rejected · outcome budget_exhausted · attempted 3 = rejected 3 = 예산 · attempts rc None/unreachable false/verdict rejected ×3 · 가짜 sudo 로그 3줄(후보당 제출 1회, 4번째 후보는 보내지 않음) |
| `rc1` (가짜 sudo, `passwd_tries=1` 모양) | se_sudotest, 후보 [login, wrong] | mode denied · outcome policy_denied · attempts [{login, rc 1, denied}] · 로그 1줄 (Vault 후보 미제출) |
| `hang` (가짜 sudo, prompt 뒤 무응답) | se_sudotest | mode unavailable · outcome prompt_timeout · attempts [{login, rc None, unreachable true, unavailable}] · 로그 1줄 · 62초 뒤 unreachable 을 `ignore_unreachable` 로 받고 play 가 이어짐(결과 파일 기록, rc 0) |
| `absent` (`ansible_become_exe=/nonexistent/se_sudo`) | se_sudotest | mode unavailable · outcome sudo_absent · attempts [{login, rc 127, unavailable}] |

- 9/9 통과, 107초. auth.log 의 임시 계정 `incorrect password` 줄: 실행 전 7 → 실행 뒤 7 (가짜 sudo 는 PAM 을 거치지 않고 실 sudo 사례는 전부 올바른 비밀번호). NOPASSWD 확인(`sudo -k -n`)은 `a password is required` 로만 남는다(제출 0).
- 결과 JSON(meta · policy · 가짜 sudo 로그)에 비밀번호 문자열 0건을 테스트가 검사한다.
- 첫 실행에서 harness 의 정리 명령 `pkill -f <경로>` 가 그 raw 명령을 돌리는 셸 자신을 죽여 연결이 끊겼다(가짜 sudo 3사례 실패, Jenkins 결과와 무관한 시험 결함) → 패턴을 `^/bin/sh <경로> ` 로 고쳐 재실행. ansible.cfg 가 동적 인벤토리만 켜므로 시험은 `ANSIBLE_INVENTORY_ENABLED=yaml,script,auto` 를 준다.

## 5. 승격 전제 매트릭스 — jenkins-prod main Job, main `341433af` (checkout 전부 == `341433af`)

| 시나리오 | 빌드 | 결과 | 봉투 |
|---|---|---|---|
| S1 Linux 3 | #590 | SUCCESS | 3/3 success · serial 있음 · sudo nopasswd 2 · password(login) 1 · Portal 200 |
| S2 혼합 5 | #591 | SUCCESS | .132 .33 .34 success(serial 있음) + TEST-NET 2 `TARGET_UNREACHABLE` · Portal 200 |
| S3 Linux 11 | #584 | SUCCESS | 11/11 success · serial 전부 · sudo password(login) 9 · nopasswd 2 |
| S4 Windows .120 | #587 | SUCCESS | 1/1 · serial 있음 |
| T2 TEST-NET 2 | #586 | SUCCESS | 2/2 `TARGET_UNREACHABLE` · Portal 200 |
| T5 중단 6 | #592 | ABORTED | `[수집] 중단됨` · 6 봉투 GATHER_FAILED · Portal 200 |
| T6 Callback 거부 | #588 | UNSTABLE | 3회 실패 · delivered=false · body 보존 |
| E2E-A cj | #589 | UNSTABLE | cj Runner · TEST-NET 실패 봉투 2 · Callback 3회 실패 |
| E2E-A2 chj | #593 | FAILURE | 등록되지 않은 Location · tip 전후 `341433af` |
| E2E-D ESXi 6 | #585 | SUCCESS | 6/6 · serial 있음 |

봉투 38(실패 14) 전수 검사: 13 필드 · status/failure_code enum · failed → `errors[0].message == failure_reason` · `details.auth`/`details.sudo` 에 label · 횟수 · rc 만 · lab 자격 문자열 0건 — 위반 0.
H12 경로(정상 경로 성공 섹션 0개)는 실장비 매트릭스에서 발생하지 않았다(정상) — 3절의 실제 엔진 통합 시험이 그 경로의 증거다.

## 6. CI #55 — `clovirone-cicd/clovirone-server-gather-ci`, main `341433af`

| 항목 | 결과 |
|---|---|
| 결과 · 시간 | SUCCESS · 59분 48초 · checkout `341433af` |
| stage | GATE · CORPUS · BUDGET · HARNESS_MAIN · PRODGEN_BUILD · HARNESS_TREE · PRODGEN_DRIFT · PRODGEN_VERIFY · VAULT_DECRYPT · EVIDENCE 전부 PASS · PROMOTE = DRY_RUN(Jenkins 에 GitLab push 자격 `se-gitlab-push` 가 없어 원격 변경 0 — P13 · P14 와 같은 운영 상태) |
| verify | `COMPLETE_PASS` · gate 20개 전부 PASS · `mandatory_missing` 없음 · e2e 증거 · ci stage 결과 문제 0 |
| 입력 | 5절 매트릭스 10 빌드(#584~#593)와 E2E-A2 의 tip 관측(`git ls-remote` origin · internal 전후 모두 `341433af`) |
| 산출물 | `prodgen_verify_report.aggregated.json` · `e2e_evidence.json` · `ci_stage_results.json` — 작업 PC 승격(7절)의 입력 |

## 7. production P15 — `6193660c` (main `341433af`, 직전 `604062c0`) · production Job canary #292~#295

승격은 작업 PC 의 `prodgen promote`(CI #55 산출물 재사용, 환경 의존 gate G11~G15 · G18~G20 재실행, 나머지 재사용) — 20:14 → 20:27. 결과 `ok` · `stage=commit` · class B 0 · tree hash `196c8615…`(194 파일) ·
origin(github) 수락 · internal(gitlab)은 공유 push URL 로 같은 커밋 · 로컬 ref 갱신. 승격 뒤 `drift-check --production production` = `PROVENANCE`(기록된 생성기로 재생성한 tree hash 일치 · trailer 16개 정합 — `Main-SHA` · `Previous-Production` · `CI-Build` #55 · `Verdict COMPLETE_PASS`) ·
`git ls-remote` origin · internal · 로컬 `git rev-parse production` 모두 `6193660c`.

| 빌드 | 대상 | 결과 | 봉투 |
|---|---|---|---|
| #292 canary os 2 | .132 Linux(NOPASSWD) · .120 Windows | SUCCESS · 2분 39초 | 2/2 success · serial 있음 · `details.sudo` nopasswd(attempted 0) · Portal 200 |
| #293 Linux 11 | .33~.38 · .95 · .96 · .156 · .162 · .163 | SUCCESS · 2분 11초 | 11/11 success · serial 전부 · sudo password/login 9(attempted 1) · nopasswd 2 · Portal 200 |
| #294 ESXi 6 | .1 .2 .3 .91 .92 .93 | SUCCESS · 1분 15초 | 6/6 success · serial 있음 · Portal 200 |
| #295 Redfish 10 | 10.100.15.x 8 + 10.50.11.231/232 | SUCCESS · 6분 25초 | 8 success + 10.100.15.1 `PROTOCOL_CHECK_FAILED`(protocol) · 10.100.15.3 `TARGET_UNREACHABLE`(reachable) — P13 #285 · P14 #291 과 같은 기존 실패 · Portal 200 |

checkout 전부 `Checking out Revision 6193660c… (refs/remotes/origin/production)` · 접수 수 == 봉투 수 == callback 항목 수(2 · 11 · 6 · 10) · finalize `outcome=completed` · `filled 0`(Layer A/B 보충 없음) · Callback 1회 시도 HTTP 200.
봉투 29(실패 2) 전수: 13 필드 · status/failure_code enum · failed → `errors[0].message == failure_reason` · success 봉투의 failure_* null · 자격 문자열 0건(lab 자격 파일 값 + sudo 후보 값, `gather_final.jsonl` · `callback_body.json` · `gather_output.json` · 콘솔).

## 8. 정리 · 남은 것

- 임시 테스트 계정 2개(.132) 삭제 확인(4절) · 가짜 sudo 스크립트 · 로그 삭제. 비밀번호는 저장소 · 문서 · 커밋 · 빌드 산출물에 없다.
- 실장비로 검증하지 못한 것: 틀린 비밀번호의 실 PAM 제출(live 매트릭스는 가짜 sudo — 실측은 앞선 작업의 #558~#561 auth.log) · Windows Serial 누락(렌더 시험만) · `targetpw`+`even_deny_root` 서버의 15분 안 반복 수집 누적(콘솔 advisory + 문서).
- 운영 영향: 정상 경로에서 성공 섹션 0개로 failed 가 된 봉투의 `errors[0]` 이 섹션 오류 대신 대표 문장이 된다(Portal Failure Grid 첫 행 · 섹션 오류는 뒤에 보존). 다른 봉투는 불변 — 매트릭스 · canary 봉투 67건에서 그 경로는 발생하지 않았다.
