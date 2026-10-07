# 2026-10-07 — 최종 마무리: 로그 보관 전역화 · forks 50 · Windows vault 도메인 · Portal 재진입 4.1/4.2 · GP-64

> 지시서: "ClovirONE Gathering 최종 마무리 실행 지시서"(2026-10-07). 10차 결과·회귀는 유지하고 추가 6개 항목만. 새 문제 없는 기능 재설계·범위 확대 금지.
> 10차 정본: `tests/evidence/2026-10-07-10th-final-defects.md`. 운영: `docs/operate/04-pipeline-runtime.md`. 결정: `docs/reference/decision-log.md` 2026-10-07(최종 마무리).

## 0. 요약

| 지시 | 내용 | 판정 |
|---|---|---|
| 1 | `Jenkinsfile_portal` · `Jenkinsfile_ci` 의 `buildDiscarder(logRotator(...))` 제거 — 보관은 Jenkins 전역 설정 | [PASS] 코드·문서·단위시험 |
| 2 | `ansible.cfg` `[defaults] forks` 200 → 50 | [PASS] 코드·문서 |
| 3 | Windows vault(yi·ic·cj) secondary username → `{yi,ic,cj}mad\infraops` | [PASS] 재암호화·구조/비밀 fingerprint 확인·전달 경로 확인. 실인증 [HOLD] |
| 4.1 | 확정 거부(408·429 제외 4xx) 뒤 재진입 재전송 금지 | [PASS] 코드·단위시험·Harness 시나리오 |
| 4.2 | 응답 확인 전 중단 → `receipt=uncertain`, 2xx 뒤 `delivered` | [PASS] 코드·단위시험(순수 판정) |
| 5 (GP-57) | Redfish 계정 쓰기 응답 유실 실장비 | [HOLD] 이 세션 Jenkins/Runner 자격 부재 — 미수행(우회 안 함) |
| 6 (GP-64) | 작업자 fork OOM 직접 귀속 — 근거 없으면 새 로직 없이 한계 기록 | [PASS] 확인·회귀시험(코드 변경 없음) |
| 7 | 회귀 · CI · 승격 · canary · 재검증 · 양 원격 SHA | [부분] main 양 원격 push · 오프라인 gate PASS. CI·승격·canary·production 재검증은 Jenkins 자격 부재로 미수행 |

## 1. 지시 1 — 로그 보관 전역화

- 코드: `Jenkinsfile_portal` `options{}` 에서 `buildDiscarder(logRotator(daysToKeepStr '14'…))` 줄 삭제(주석도 보관 설명 → 전역 설명으로). `Jenkinsfile_ci` `options{}` 에서 `buildDiscarder(logRotator(numToKeepStr '50'))` 삭제.
- 전역 설정은 바꾸지 않았다. 향후 필요하면 Jenkinsfile 에 되넣지 않고 전역 정책으로 할지 사용자에게 먼저 확인한다(지시서 문구).
- 문서: `docs/operate/04-pipeline-runtime.md` §9(보관 표) · `docs/operate/08-ansible-config.md` 아님 · `docs/ai/catalogs/JENKINS_PIPELINES.md` — Jenkinsfile 이 보관기간을 지정한다던 부분만 전역 관리로 갱신. 작업 폴더 정리(`scripts/workspace_cleanup.py`, KEEP_DAYS 7)는 보관 정책과 별개라 그대로.
- 시험: `test_jenkinsfile_portal_finalize.py::test_retention_policy`(buildDiscarder/logRotator 부재 + 전역 설명 존재) · `::test_time_limits_count_execution_and_waiting_separately`(options 에 buildDiscarder 없음) · `test_time_limits.py::test_retention_and_cleanup_values`(portal 부재 + 작업 폴더 정리 유지) · `test_jenkinsfile_ci.py::test_ci_is_declarative…`(ci 부재). Harness Jenkinsfile(portal·ci 아님)은 대상이 아니라 그대로.

## 2. 지시 2 — forks 50

- 코드: `ansible.cfg` `[defaults]` `forks = 200` → `forks = 50` + 주석(현재 운영 설정·향후 변경 가능·자원 로직 없음).
- 이 변경 때문에 CPU/메모리 계산·동적 forks·사전 차단·자원 제한을 추가하지 않았다(8차에 제거된 자원 로직을 되살리지 않음).
- 문서: `docs/operate/08-ansible-config.md` 발췌 블록 50 으로 갱신.

## 3. 지시 3 — Windows vault 도메인 계정

- 대상: `vault/yi/os/windows.yml` · `vault/ic/os/windows.yml` · `vault/cj/os/windows.yml` 의 secondary(`role: secondary`, `label: windows_fallback`) 계정 username 만.
  - yi → `yimad\infraops` · ic → `icmad\infraops` · cj → `cjmad\infraops`.
- 불변 확인(복호화는 /dev/shm 0600, 평문·비밀 미출력, 끝나고 shred): password(secondary fingerprint sha256 `14465ae6…` 변경 전후 동일) · label · role · 계정 순서 · primary(`administrator`). `vault/git/os/windows.yml`(대상 아님) · Linux · ESXi · Redfish 불변. git diff 는 세 파일만.
- 전달 경로(`DOMAIN\username`): vault `accounts[].username` → `common/tasks/credential/resolve_and_load.yml` `_cred_accounts`(순서 유지) → `os-gather/site.yml` `_os_accounts` → `os-gather/tasks/try_credentials.yml` 루프 → `try_one_credential.yml` `set_fact ansible_user: "{{ _try_cred.username }}"`. WinRM `ansible_winrm_transport: ntlm`. YAML plain scalar 라 역슬래시는 literal(YAML 은 plain scalar 에서 escape 를 해석하지 않음), Jinja `{{ }}` 치환도 그대로라 `DOMAIN\user` 가 NTLM 에 손실 없이 전달된다.
- 실인증 [HOLD]: 승인된 도메인(yimad/icmad/cjmad) 가입 Windows 시험 대상이 확보되지 않았고, 틀린 자격으로 반복 시도하면 운영 `infraops` 계정 잠금 위험이 있어 실인증은 하지 않았다(지시서: 없으면 실기 미확인으로 구분). vault 파일은 git 추적이라 되돌림은 `git checkout`.

## 4. 지시 4 — Portal 결과 처리 재진입

함수 `seCallback`(`Jenkinsfile_portal`)와 호출부 `seFinalizeIn`.

### 4.1 확정 거부 뒤 재전송 금지
- 틈: 결정적 4xx(408·429 제외)를 받으면 그 호출 안에서는 멈추지만(`break`), 거부 상태가 진입 사이에 유지되지 않아 재진입 시 `done < maxAttempts` 면 다시 POST 했다.
- 수정: 4xx 분기에서 `state.refused = true`. 진입 머리에서 `state.refused = (state.refused == true)` 로 유지. `boolean resolved = delivered || refused` 로 for 루프를 막음(`!resolved && …`). 호출부는 `cb.delivered` 와 나란히 `else if (cb.refused == true)` 로 `seCallback` 자체를 건너뜀. 408·429 는 refused 가 아니라 재시도 대상(그대로).
- 시험: 단위 `test_jenkinsfile_portal_finalize.py::test_finalizer_reentry_does_not_resend_…`(refused 유지·resolved·루프 가드·호출부 분기) + `test_callback_rules_and_attempt_records`(seCallbackRecord 에 refused). Harness `finalize_refused_no_resend`(sink HTTP 400 → 거부, 요약 쓰기에서 실행 기반 오류로 재진입 → `httpRequest` 1회 · `sink_posts_eq 1` · delivered=false). CI·prodgen 목록 동기.

### 4.2 응답 확인 전 중단 → uncertain
- 틈: 보낸 뒤 응답 확인 전 중단(`catch FlowInterruptedException` → `rec.outcome='interrupted'`)이 `unknownReceipt` 계산에서 빠져(연결 실패·408 만 셌다), interrupted-then-400 또는 중단 누적 시 `not_delivered` 로 분류됐다.
- 수정: `unknownReceipt` 에 `t.outcome == 'interrupted'` 포함. `receipt = delivered ? 'delivered' : (!attempted ? 'not_attempted' : (unknownReceipt ? 'uncertain' : 'not_delivered'))` 그대로. 중단은 전달됐을 수 있어 그 뒤 재진입에서 확정 거부(4xx)를 받아도 uncertain 이 우선. 2xx 가 확인되면 delivered. `eventUuid`·본문·누적 시도·시간 유지, 새 전송 체계·시도 초기화 없음.
- 시험: 단위 `test_callback_rules_and_attempt_records`(interrupted 가 unknownReceipt 에 들어가는 정확한 Groovy 조건 + receipt 식). receipt 는 순수 판정이라 단위 문자열 시험으로 결정적으로 고정. `interrupted` 산출·재전파 자체는 기존 interruption 시나리오(`outer_timeout`·`user_abort`)가 다룬다. 재개 가능한 중단을 POST 도중에 결정적으로 주입하는 경로는 Harness 에 더하지 않았다(범위 제한) — 이 한 점은 단위 판정으로 고정.

## 5. 지시 5 (GP-57) — [HOLD]

이 세션은 Jenkins/Runner 인증 netrc 가 없어(10차 종료 시 접근 파일 삭제, 재발급 안 됨) Runner 를 통한 BMC 접근 자체를 시작하지 못했다. 우회하지 않고 미수행으로 남긴다. 기존 운영 계정은 바꾸지 않는다. 사용자가 Jenkins/Runner 자격과 안전한 시험 BMC · 시험 전용 ReadOnly 계정 범위를 주면 9차 mock 과 같은 순서(쓰기 응답 유실 → 재조회 → 표준 계정 재인증 판정)를 실장비로 확인할 수 있다.

## 6. 지시 6 (GP-64) — 작업자 fork OOM

- 확인: Jenkins Agent·ansible 주 프로세스가 살아 있고 작업자(fork)만 OOM 인 경우, 작업자 PID 는 `run_gather.sh`·ansible-playbook 주 프로세스가 아니고 기록되지 않는다(`run_pids` = 두 PID 뿐). 그래서 커널 로그의 OOM 종료 기록에 작업자 PID 가 있어도 `oom_link` 는 None 이다.
- 현 코드는 이미 올바르다: `classify_end` 는 PID 연결(link)이 있을 때만 `runner_oom`. 스스로 끝난 rc(1 등)는 OOM 관측(obs)이 있어도 `failed_run`. 신호/137 이어도 작업자 PID 뿐이면 연결 없음 → `process_lost`(원인 미확인). → 제품 로직 변경 없음(지시: 직접 귀속 근거 없으면 공유 카운터·종료 코드만으로 추정하는 새 로직 금지).
- 완료 Host 보존 · 미완료 Host 재개는 `runner_oom`(INFRA_STATES)일 때의 동작이다. 작업자-only OOM 은 `failed_run`(TERMINAL)이라 이 재개 경로로 가지 않는다 — 직접 귀속 근거가 없으므로 올바르다.
- 회귀: `tests/unit/test_gather_state.py::test_worker_fork_oom_is_not_this_runs_oom_gp64` — (a) `oom_link({pid:4242}, ws, 작업자 PID 8888 kill) is None`, (b) 주 프로세스 rc=1 + OOM 카운터 +1 → `failed_run`·`oom_link None`·관측만·INFRA_STATES 아님, (c) rc=137 + 작업자 PID OOM → `process_lost`·원인 미확인.
- 한계: 작업자 PID 를 남기는 방법(전략 plugin 등)은 범위 밖이라 하지 않았다. GP-64 는 한계로 남긴다.

## 7. 검증 · 반영

### 오프라인 gate (로컬 WSL)
`bash scripts/ai/ci_gate.sh` — python compile · field_dictionary 정합(종전 Jenkins Validate Schema) · output schema drift · vendor boundary · harness consistency · finalize corpus(Layer A oracle) · pytest(unit·e2e·regression) **4,516 passed · 145 skipped · 7 xfailed** · integration · 3채널 `ansible-playbook --syntax-check` PASS. 영향 단위 시험도 별도로 PASS.

### 미수행 (이 세션 Jenkins 자격 부재 — 우회 안 함)
- CI Job 실행(`clovirone-server-gather-ci`), main Job 재검증, prodgen `promote`(production 승격), production Job canary·실환경 재검증, GP-57 실장비.
- 이유: Jenkins controller 는 닿지만(HTTP 200) 이 세션에 인증 netrc 가 없다. 승인된 자격을 우회하거나 지어내지 않는다.
- 남은 경로(자격이 주어지면): 최종 후보 SHA 로 CI(첫 실행은 `HARNESS_SCENARIOS` 에 `finalize_refused_no_resend` 포함해 명시, prodgen `REQUIRED_HARNESS` 와 일치) → main Job 영향 시나리오 → `prodgen promote`(G01~G20) → 양 원격 production push → production canary·재검증.

### 양 원격
- main: 이 마무리 커밋을 GitHub·GitLab(internal) 양 원격에 push, `git ls-remote` 로 각각 대조.
- production: P7 `61b9dd4a` 유지(이 세션 승격 안 함). 양 원격 production 은 변동 없음.

## 8. 원복 · 정리
- vault 복호화 임시 파일은 /dev/shm 0600 에서 처리하고 shred — 추적 파일·로그·artifact 에 비밀 없음.
- `.vault_pass`(repo 루트, gitignore)는 사용자가 둔 금고 비밀번호 파일이라 그대로 둔다. 이 세션이 새로 만든 접근 파일 없음.
- 작업 산출물은 세션 scratchpad(`r11/`)에만 — 저장소에 넣지 않는다.
