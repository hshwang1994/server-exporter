# OS Vault 2차 infraops fallback 계정 추가 — 검증 기록

**일자**: 2026-09-14
**커밋**: 15f95dca (main)
**유형**: 사용자 지시 — OS(Linux/Windows) 접속 계정 fallback 을 Vault `accounts[]` 에 반영
**작업 환경**: Windows 11 + WSL(Ubuntu, ansible-core 2.20.7). 네이티브 Windows `ansible-vault` 는
`OSError WinError 87`(`os.get_blocking`)로 불가 → 편집/암호화는 WSL, 구조 검증은 네이티브
`scripts/ai/vault_decrypt_check.py`(pure `cryptography`). password 평문은 어디에도 기록하지 않음.

## 1. 요구사항
- Linux: 1차 `infra / ********` → 2차 `infraops / ********`
- Windows: 1차 `administrator / ********` → 2차 `infraops / ********`
- 기존 fallback 구조(`accounts[]` 순차 시도) 재사용, 새 로직 금지, 코드/컨트랙트 미변경.

## 2. 변경 전 상태 (복호화 실측 — password 는 hash 로만 대조, 평문 미기록)
| Vault | before |
|---|---|
| ic/chj/yi linux | 1 acct `infra`(linux_current/primary) + legacy 키. password 이미 = 목표 infra 값 |
| ic/chj/yi windows | 1 acct `administrator`(windows_current/primary) + legacy 키. password 이미 = 목표 admin 값 |
| git linux | 1 acct `cloviradmin`(linux_current/primary) + legacy 키. git 전용 password |
| git windows | 1 acct `administrator`(windows_current/primary) + legacy 키. git 전용 password(git linux 와 동일 hash) |

## 3. 사용자 결정 (예외)
- **git Windows**: 2026-09-01(`8fd7ea4b`) administrator 통일 제외 이력 → "1차 보존 + fallback 추가".
- **git Linux**: 복호화로 `cloviradmin`(예상 밖 전용 계정) 발견 → 동일하게 "1차 보존 + fallback 추가".
- ic/chj/yi 는 1차 primary 가 이미 목표 값과 동일 → 2차만 추가.

## 4. 최종 상태 (8 파일, accounts-only / legacy 제거)
- Linux ic/chj/yi: `[infra primary(linux_current), infraops secondary(linux_fallback)]`
- Linux git: `[cloviradmin primary(보존), infraops secondary]`
- Windows ic/chj/yi: `[administrator primary(windows_current), infraops secondary(windows_fallback)]`
- Windows git: `[administrator primary(git 전용 password 보존), infraops secondary]`
- 4 Location 이 동일 fallback(`infraops`) 공유. 2차 role = `secondary` → 성공 시 `fallback_used=true`.

## 5. 검증
- 구조: `scripts/ai/vault_decrypt_check.py --password-file .vault_pass` → `[PASS] 전량 통과` (exit 0)
- **스테이징 바이트(실제 커밋 대상) 복호화 8/8 PASS**: username/label/role/order/standard password 일치,
  git primary password hash 불변 확인.
- 암호화 무결성: 8 파일 전부 `$ANSIBLE_VAULT;1.1;AES256`, `git diff` ciphertext-only, 커밋 blob LF(0 CR).
- 테스트: 타깃 credential/vault 130 passed; 전체 `pytest tests/ --ignore=tests/e2e_browser`
  → **3311 passed / 11 skipped / 7 xfailed / 0 failed**.
- `ansible-playbook --syntax-check os-gather/site.yml` 정상.
- become: `os-gather/tasks/try_one_credential.yml:22-25` 가 후보별로
  `ansible_user`/`ansible_password`/`ansible_become_pass` 를 함께 `set_fact` → infraops fallback 성공 시
  `ansible_become_pass` 도 infraops password (정적 확인).

## 6. 실장비 미검증 (후속 — 저장소 밖)
- Jenkins `os` 게더 6 케이스: Linux/Windows × (1차 성공 / fallback 성공 / 전부 실패).
  `diagnosis.details.auth.{used_label, used_role, fallback_used}` 로 확인. 실제 SSH/WinRM 인증은 여기서 불가.
- `tests/e2e_browser/*` 는 `playwright` 미설치로 collection skip — 본 변경과 무관(테스트 파일 미변경).

## 7. 참고 (발견 사항, 미변경)
- `os-gather/site.yml:234` 의 `ansible_become_pass` play-var 는 후보별 `set_fact` 에 항상 덮여 dead(기존 결함).
- `core.autocrlf=true` + `vault/**` gitattributes 부재 — 커밋 blob 은 LF(안전), Windows 재체크아웃 시
  작업본만 CRLF smudge. 선택적 hardening: `vault/** -text` (본 작업 범위 밖).
