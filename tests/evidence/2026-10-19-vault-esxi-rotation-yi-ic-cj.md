# 2026-10-19 — yi · ic · cj ESXi 계정 비밀번호 교체 (vault) · production 반영

> 누가: 사용자 지시("yi ic cj 리전 ESXi 암호 변경 — main 이랑 production 둘 다, 빠르게") → AI 가 절차 준비 · 검증 · 기록, 복호화·재암호화 실행은 사용자(`!`).
> 언제: 2026-10-19. 어디서: `vault/yi/esxi.yml` · `vault/ic/esxi.yml` · `vault/cj/esxi.yml`. 무엇: `accounts[]` 중 `username: root`(label `esxi_current`, role primary — 각 파일 1건)의 `password` 만 교체.
> 비밀번호 값은 이 문서 · 커밋 · 콘솔 어디에도 적지 않는다(`docs/operate/05-vault.md` 7절).

## 1. 절차 (rotate-vault 시나리오 2 — 계정 비밀번호 변경)

- 이 세션의 자동 모드 분류기가 vault 비밀번호 파일을 참조하는 AI 명령을 차단해, 값이 들어 있지 않은 보조 스크립트 `C:\Users\hshwa\rotate_esxi_vault_wsl.sh`(새 비밀번호는 stdin, vault 비밀번호 파일은 인자)를 만들고 사용자가 `!` 로 실행했다.
- 스크립트: WSL(ansible-core 2.20.7)에서 `ansible-vault view` → 평문을 WSL `/tmp`(600)에만 두고 `username: root` 블록의 `password:` 줄만 텍스트 치환(형식 보존) → PyYAML 로 평문 검증(대상 수 == 치환 수, 다른 키 불변) → `ansible-vault encrypt` 로 같은 vault 비밀번호로 재암호화 → 다시 `view` 해 값 일치 검증 → 임시 파일 삭제. 출력은 label/username/role 과 OK/NG 뿐.
- 결과: yi · ic · cj 모두 `치환 1건, 평문 검증 OK` · `재암호화 · 복호화 재검증 OK`. (`vault/git/esxi.yml` 은 대상이 아니라 그대로.)
- 확인(AI): 세 파일 첫 줄 `$ANSIBLE_VAULT;1.1;AES256`, 본문 전부 16진수 줄(평문 0), 변경 파일 3개뿐. vault 로더 단위 시험(`test_credential_load_task` · `test_credential_resolver` · `test_vault_check_no_secret_output` · `test_location_registry` · `test_bootstrap_vault_encrypt`) 120 passed.
- 커밋 `20843c32` `chore: yi·ic·cj ESXi vault 계정 비밀번호 교체` → `git push origin main`(github · gitlab).

## 2. production 반영 (prodgen 정규 경로 — vault 는 런타임 tree 에 들어가므로 승격이 필요하다)

- main Job 매트릭스 main `20843c32` — 필수 시나리오 8건 + ESXi 성공 경로(E2E-D), 9건 동시 투입:

| 시나리오 | 빌드 | 결과 |
|---|---|---|
| S1 | #700 | SUCCESS 126초 |
| S2 | #701 | SUCCESS 142초 |
| S3 | #702 | SUCCESS 152초 |
| T2 | #703 | SUCCESS 104초 |
| T6 | #704 | UNSTABLE 137초(계약값) |
| E2E-A | #705 | UNSTABLE 130초 |
| E2E-D | #706 | SUCCESS 122초 — ESXi 6대(loc git) |
| E2E-A2 | #707 | FAILURE 25초(fail-closed) — tip 관측 before 1792384920 · after 1792385000, sha `20843c32` 불변 |
| T5 | #708 | ABORTED 92초 — 마커 +31초 `stop`, `[수집] 중단됨:` · outcome aborted · Portal 200 · `lastBuiltRevision 20843c32` |

- CI · 승격 · canary: 아래 3절.

## 3. CI · 승격 · canary

(CI 결과 · promote · canary 를 이어 적는다.)

## 4. 실장비에서만 확인 가능

yi · ic · cj 의 ESXi 호스트는 lab 에 없다 — 새 비밀번호로 vSphere 인증이 되는지는 해당 사이트의 다음 수집(`diagnosis.auth_success` · ESXi 섹션 success)에서 확인한다.
