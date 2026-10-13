# 2026-10-13 — Linux sudo Vault 후보 · 잠금 예산 · OS Serial Number 필수 — 실측 기록

> 결정 근거: `docs/reference/decision-log.md` 2026-10-13 절, `docs/ai/decisions/ADR-2026-10-13-sudo-vault-fallback-and-serial-required.md`.
> 비밀번호는 어디에도 적지 않는다. 임시 테스트 계정은 검증 뒤 삭제한다(6절).

## 1. 사전 점검 (읽기 전용)

| 항목 | 관측 (2026-10-13) |
|---|---|
| 10.100.64.132 | `infra-test-vm-02`, Ubuntu 24.04.2 LTS, kernel 6.8.0-146-generic, VMware VM, Python 3.12.3, sudo 1.9.15p5 |
| cloviradmin | `(ALL) NOPASSWD: ALL` + `%sudo` 그룹. `sudo -k -n /bin/sh -c 'id -u'` → `0`, rc 0 |
| sudoers | `Defaults env_reset, mail_badpass, secure_path, use_pty`. `/etc/sudoers.d/90-cloud-init-users`(ubuntu NOPASSWD). `passwd_tries` · `targetpw` 없음 |
| 잠금 정책 | `/etc/pam.d/common-auth` 에 `pam_faillock`/`pam_tally2` 없음(Ubuntu 기본). `faillock.conf` 전부 주석(기본 deny=3, unlock 600, 900s). → 예산 3 |
| sshd | `PasswordAuthentication yes`(cloudimg drop-in), `UsePAM yes`, `AcceptEnv LANG LC_*` |
| DMI | 비특권 `cat /sys/class/dmi/id/product_serial` → Permission denied, sudo → `VMware-42 34 …` |
| jenkins-prod | `https://jenkins-prod.gooddi.lab` = 10.100.64.30, `admin` 인증 OK, Runner01~04 online(라벨 git linux redfish windows + 일부 cj esxi), main Job `clovirone-cicd/clovirone-server-gather-main`(SCM GitHub `*/main`), 마지막 #555 |
| Portal 수신기 | `http://10.100.64.151:8080` 응답(로그인 리다이렉트), `POST /api/jenkins/gather/os` → 200 → 테스트 `callbackUrl` 로 사용 |
| 로컬 도구 | Windows ansible-core 2.21.3(소스 확인용, fcntl 로 실행 불가), WSL `Ubuntu` ansible-core 2.20.7(syntax-check 용) |

## 2. 정적 검증

| 검사 | 결과 |
|---|---|
| `ansible-playbook --syntax-check` 3채널 (WSL 2.20.7) | os · esxi · redfish 통과 |
| 신규 단위 시험 (`test_credential_sudo_passwords` · `test_linux_sudo_probe` · `test_status_serial_required_scenario_e`) | 통과 |
| 갱신 시험 (`test_linux_raw_scripts_shim` python 13 · raw 12 · no_sysfs 15, `test_credential_probe_classification`, `test_credential_candidate_stop`, `test_errors_message_contract`, `test_vault_check_no_secret_output`) | 통과 |
| `verify_harness_consistency` · `verify_vendor_boundary` · `validate_field_dictionary` · `output_schema_drift_check` · Jinja compile/namespace 훅 · `verify_no_plaintext_secret`(digest) | 통과 (vault 복호화 전수 검사는 Windows 에서 `ansible` import 불가로 미실행) |
| 전체 pytest (unit · e2e · regression) | 5,098 passed · 36 skipped · 7 xfailed · 0 failed (변경 후, 로컬 Windows Python 3.13 / pytest 9.1.1) |

## 3. 임시 테스트 계정 (10.100.64.132, 사용자 승인)

| 계정 | 설정 | 용도 |
|---|---|---|
| `se_sudotest` | `sudo` 그룹(비밀번호 요구), 로그인 비밀번호는 후보 목록에 없는 임시값 | 시나리오 2(표준 sudoers) · 3/4/5(드롭인 `Defaults:se_sudotest targetpw` 추가 시) |
| `se_nosudo` | sudo 없음 | 시나리오 6 (정책 거부) · 10 (혼합) |

기존 sudoers · cloviradmin 설정 불변. 드롭인은 `/etc/sudoers.d/90-se-sudotest` 하나만, 검증 뒤 삭제.

## 4. Jenkins 실측 (main Job, loc=git, target_type=os)

모든 빌드는 SCM checkout 이 그 시점의 main HEAD 였고(콘솔 `revision`), Portal 수신기(10.100.64.151:8080)에 HTTP 200 으로 전달됐다. 봉투는 artifact `gather_final.jsonl` 로 판독했다.

| # | 시나리오 | 빌드 (main 커밋) | 결과 (봉투) |
|---|---|---|---|
| 1 | NOPASSWD (cloviradmin) | #556 (`f19b366e`) | success · serial 있음 · `details.sudo` mode=nopasswd · attempted 0 · policy {pam_files 2, lock_module false, deny 3, even_deny_root false} → max_rejections 3 · errors [] |
| 2 | 로그인 비밀번호로 sudo (se_sudotest, 표준 sudoers) | #557 (`4ec67401`) | success · mode=password · used_label=login · attempted 1 · rejected 0 · faillock 0 |
| 3 (1차) | Vault Primary (targetpw) — **결함 발견** | #558 (`4ec67401`) | failed(`gather_after_auth`) — Runner ansible-core 2.20.3 은 비밀번호 거부를 `failed_when` 으로 지울 수 없는 태스크 예외로 올려 play rescue 로 떨어뜨렸다(errors detail `Task failed: Incorrect sudo password`). 결과 모양(rc 없음 · msg)은 설계대로 → 프로브를 block/rescue 로 감싸는 수정 `0ec559e4` |
| 3 (재) | Vault [Primary, Fallback 1] (targetpw — .132 의 root 비밀번호는 Fallback 1 값과 같았다) | #559 (`0ec559e4`) | success · 로그인 rejected → Primary rejected → **Fallback 1 ok** · attempted 3 · rejected 2 · used_label=sudo_fallback1 · fallback_used true. auth.log: 후보당 `1 incorrect password attempt` 정확히 1줄, NOPASSWD 확인은 `a password is required`(PAM 실패 0). (.132 의 root 비밀번호가 둘째 값과 같았다 → 시나리오 4 의 의미) |
| 4 | Vault 순서 교체 [Fallback 1 값을 Primary 자리에, Primary 값을 Fallback 1 자리에] (targetpw) | #560 (`75450a46`) | success · 로그인 rejected → **Primary ok** · attempted 2 · rejected 1 · used_label=sudo_primary (시나리오 3 의 의미) |
| 5 | 전부 틀림 [Primary 값, Fallback 1 의 대소문자 변형] (targetpw) | #561 (`91b2d8df`) | **failed** · stage gather · GATHER_FAILED · 문장 serial_missing · `details.sudo` mode=rejected outcome=budget_exhausted attempted 3 rejected 3 (= 예산) · `details.serial_number` {present false, cause privilege_unavailable, sudo rejected} · sections 7개 success 유지 · data 보존 · errors[0].message == failure_reason · PAM 실패 +3 |
| 6 · 10 | se_nosudo 우선 + 혼합 배치 [.162 .163 .120 .132] | #562 (`fcf9fe0d`) | 접수 4 = 봉투 4. `.132` 만 failed(mode=denied · outcome=policy_denied · attempted 1 · rejected 0 · PAM 실패 +0) · `.162` `.163` success(nopasswd) · `.120` Windows success(serial 있음, sudo 키 없음, 인증 경로 불변) |
| 8 | Windows .120 | #562 | 위 — success · serial 있음 |
| 9 | Windows Serial 누락 → failed | — | 실 VM 에서 Serial 을 없앨 수 없어 렌더 단위시험(`test_status_serial_required_scenario_e.py::test_windows_uses_its_own_section_name_and_no_sudo`)으로만 |
| 11 | 명부 회귀 (승격 전제) | #563 (`03a5637b`) | 접수 13 = 봉투 13. Linux 11/12 success(Runner 4 · tanzu 2 · r760 2 · .156 은 mode=password used_label=login attempted 1 rejected 0, .162 .163 은 nopasswd) · Windows .120 success — serial 전부 있음. `.161` 만 failed(reachable · `TARGET_UNREACHABLE`, TCP 3포트 · ICMP 모두 무응답 — 수집 로직 무관, 승격 S3 는 .161 을 뺀 11대 — 8절). PAM 실패 +0 · Portal 200 |

PAM 실패 누적(auth.log `incorrect password attempt`): #558 1 · #559 2 · #560 1 · #561 3 · #562 0 = 7 — 후보당 정확히 1회, 재시도 0. 계정 잠금 0(`faillock` 비활성 host).

## 5. 봉투 검증 (12)

모든 빌드의 `gather_final.jsonl`: 13 필드 · `status`/`failure_code` enum 안 · failed 봉투의 `errors[0].message == diagnosis.failure_reason` · 비밀번호 문자열(테스트 계정 · Vault 값) 0건(grep) · `details.auth`/`details.sudo` 에 label · 횟수 · rc · verdict 만.

## 6. 정리

- `.132`: `se_sudotest` · `se_nosudo` 삭제(`userdel -r`), `/etc/sudoers.d/90-se-sudotest` 삭제, faillock 카운터 reset — `getent` 0건, sudoers.d 는 원래의 2개 파일만.
- git vault: `03a5637b` 로 계획 5절 구성(accounts 2 · sudo_passwords Primary + Fallback 1) 복원 — 구조 검사 통과(값 미출력).
- 임시 변경 커밋(`4ec67401` `75450a46` `91b2d8df` `fcf9fe0d`)은 암호화 bytes 만 history 에 남는다.

## 7. 전체 pytest

변경 후 전체(unit · e2e · regression) 5,098 passed · 36 skipped · 7 xfailed · 0 failed (14분 42초). 수정 `0ec559e4` 뒤 관련 84건 재통과.

## 8. production 승격 (P14)

- 1차 후보 `03a5637b`: main Job 시나리오 10건(#564~#573)은 전부 계약대로 끝났지만 CI #53 Gate 가 `tests/integration/test_addon_hook_playbook.py` 15건 ERROR 로 FAIL —
  `build_output.yml` 끝의 `require_serial.yml` include 가 `playbook_dir` 기준이라 add-on harness playbook 에서 경로를 찾지 못했다(운영 site.yml 에서는 정상이라 실장비 빌드는 통과).
  `b203fd45` 로 REPO_ROOT 기준으로 고치고(단위 시험 가드 추가, WSL 통합 시험 16 통과) 매트릭스를 다시 돌렸다(`docs/ai/catalogs/FAILURE_PATTERNS.md` 2026-10-13).
- 최종 후보 main `b203fd45`(두 원격 동일). 아래 빌드는 전부 이 SHA 다(콘솔 `Checking out Revision b203fd45…`, Portal 수신기 10.100.64.151:8080).
  .161 은 전원이 꺼져 있어(#563: TCP 3포트 · ICMP 무응답, 작업 PC 에서도 22 무응답) S3 명부에서 뺐다. host 가 겹치지 않게 묶어 병렬로 돌렸다(S3 · S4 · E2E-D · T2 · T6 · E2E-A · E2E-A2 → S1 · S2 → T5).

| 시나리오 | 빌드 | 결과 | 관측 |
|---|---|---|---|
| S1 Linux 3 (.162 .163 .156) | #581 | SUCCESS | 3/3 success · serial 있음 · `details.sudo` nopasswd 2 · password(login) 1 · Portal 200 |
| S2 혼합(실호스트 3 + TEST-NET 2) | #582 | SUCCESS | .132 .33 .34 success + 2 `TARGET_UNREACHABLE` · Portal 200 · 보충 0 |
| S3 Linux 11 | #574 | SUCCESS | 11/11 success · serial 있음(password/login 9 · nopasswd 2) · Portal 200 |
| S4 Windows 1 (.120) | #575 | SUCCESS | 1/1 · serial 있음 · Portal 200 |
| T2 TEST-NET 2 | #577 | SUCCESS | 2대 `TARGET_UNREACHABLE` 봉투 · Portal 200 |
| T5 사용자 중단 | #583 | ABORTED | 6대 수집 시작 15초 뒤 API stop → `[수집] 중단됨: 빌드가 중단됐습니다` · 6대 실패 봉투(gather / GATHER_FAILED) · Portal 200 · `callback_body.json` 보존 · ABORTED 유지 |
| T6 Callback 거부 주소 | #578 | UNSTABLE | `http://127.0.0.1:9` 3회 실패(10초 · 20초 대기) · delivered=false · body 보존 |
| E2E-A loc=cj | #579 | UNSTABLE | cj Runner 에서 실행 · 2대 실패 봉투 · Callback 3회 실패 |
| E2E-A2 loc=chj | #580 | FAILURE | `[실행 위치] 등록되지 않은 Location: 'chj'` · 수집 없이 봉투 2 · Portal 200 · fail-closed · tip 관측(`git ls-remote` origin · internal 전후 모두 `b203fd45`) |
| E2E-D ESXi 6 | #576 | SUCCESS | 6/6 · serial 있음 · Portal 200 |

- CI `clovirone-server-gather-ci` #54(`b203fd45`, E2E 10건 + E2E-A2 tip 관측, PROMOTE dry-run): SUCCESS(59분 17초) · GATE · CORPUS · BUDGET · HARNESS_MAIN · PRODGEN_BUILD · HARNESS_TREE · PRODGEN_DRIFT · PRODGEN_VERIFY · VAULT_DECRYPT · EVIDENCE 전부 PASS · verify COMPLETE_PASS(tree `6ddf2a0b…`) · e2e 증거 main 10 + Harness 77 항목 전부 pass(E2E-A2 는 tip 관측으로 direct 바인딩) · PROMOTE 는 dry-run(Jenkins 에 `se-gitlab-push` 자격 없음) — 집행 조건 6항 통과
- 승격(작업 PC — `PYTHONIOENCODING=utf-8 python -m scripts.ai.prodgen promote --sha b203fd45… --verify-report <CI #54 aggregated> --e2e-evidence <CI #54 e2e_evidence.json> --ci-stage-results <CI #54 ci_stage_results.json> --netrc … --vault-password-file … --push-remote origin,internal`;
  netrc · vault 암호 파일은 실행 중에만 저장소 밖에 두고 지웠다): production P14 `604062c0`(trailer `Main-SHA b203fd45…` · `Tree-Hash 6ddf2a0bfbb9b7a534a5ca9b25e283fa7c0cdb6275c5385c9cdcc02bbf1e9a44` · Verdict COMPLETE_PASS · 다시 실행한 gate G11 G12 G13 G14 G15 G18 G19 G20(환경 차이 — Runner python 3.12.9 · Linux · ansible 2.20.3 ↔ 작업 PC python 3.13.15 · Windows 11 · WSL ansible 2.20.7)).
  `git ls-remote origin` · `internal` · 로컬 `production` 세 값 동일, drift-check `PROVENANCE`.
- canary(production Job `clovirone-server-gather`, `*/production`): canary os 2 #288(.132 Linux NOPASSWD · .120 Windows — 2/2 success · serial 있음) · Linux 11 #289(11/11 success · sudo password/login 9 · nopasswd 2) · ESXi 6 #290(6/6) · Redfish 10 #291(8 success + 10.100.15.1 `PROTOCOL_CHECK_FAILED` · 10.100.15.3 `TARGET_UNREACHABLE` — P13 #285 와 같은 기존 실패). checkout 전부 == `604062c0`(`refs/remotes/origin/production`) · 결과 수 == 접수 수 · Portal 200 · Jenkins 결과 전부 SUCCESS
- 이 기록을 담은 docs · harness 커밋은 production tree 에 영향이 없다(`docs/**` · `docs/ai` · `tests` · `.claude` 는 manifest 제외).
