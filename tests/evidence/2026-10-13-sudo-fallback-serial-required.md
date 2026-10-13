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
| 전체 pytest (unit · e2e · regression) | (아래 7절) |

## 3. 임시 테스트 계정 (10.100.64.132, 사용자 승인)

| 계정 | 설정 | 용도 |
|---|---|---|
| `se_sudotest` | `sudo` 그룹(비밀번호 요구), 로그인 비밀번호는 후보 목록에 없는 임시값 | 시나리오 2(표준 sudoers) · 3/4/5(드롭인 `Defaults:se_sudotest targetpw` 추가 시) |
| `se_nosudo` | sudo 없음 | 시나리오 6 (정책 거부) · 10 (혼합) |

기존 sudoers · cloviradmin 설정 불변. 드롭인은 `/etc/sudoers.d/90-se-sudotest` 하나만, 검증 뒤 삭제.

## 4. Jenkins 실측 (main Job, loc=git, target_type=os)

| # | 시나리오 | 빌드 | 결과 |
|---|---|---|---|
| 1 | NOPASSWD (cloviradmin) | | |
| 2 | 로그인 비밀번호로 sudo (se_sudotest, 표준 sudoers) | | |
| 3 | Vault Primary (targetpw) | | |
| 4 | Primary 실패 → Fallback 1 (targetpw) | | |
| 5 | 전체 sudo 실패 (targetpw, 모두 틀림) | | |
| 6 | 권한 없는 계정 (se_nosudo) | | |
| 8 | Windows .120 | | |
| 10 | 혼합 배치 | | |
| 11 | 명부 회귀 (승격 전제) | | |

## 5. 봉투 검증 (12)

(13 필드 · enum · errors[0]==failure_reason · 비밀번호 문자열 0건 · details.auth/sudo 에 label/횟수만)

## 6. 정리

(임시 계정 · 드롭인 삭제, git vault 최종 구성 복원, faillock 카운터)

## 7. 전체 pytest

(결과)
