# 시크릿 회전 + 히스토리 정리 런북 (SECRET ROTATION RUNBOOK)

> 작성: 2026-05-29 audit-cleanup cycle. 분류: **[CRIT] 운영 보안**.
> 본 cycle 사용자 결정 = **"문서화만"** — 저(AI)는 repo 안 시크릿을 자동 스크럽하지 **않았다**.
> 본 런북은 사용자/운영자가 실행할 회전·정리 절차를 정리한 것이다. 실제 암호 교체와 히스토리 재작성은 사용자 권한.
> **2026-10-05 갱신**: 추적 파일 재검사(2절) · 85행 평문 1건 가림 · 3.3 해소 표시. 값은 어디에도 다시 적지 않았다.

---

## 1. 무엇이 / 왜 / 영향

| 항목 | 값 (현재 평문 노출) | 실제 역할 | 영향 |
|---|---|---|---|
| **vault 마스터 암호** | `__REDACTED__` | `ansible-vault` 복호화 키 — `vault/**/*.yml` 전체 (linux/windows/esxi + redfish/{vendor}) 를 복호화 | 이 한 줄로 **repo 안 모든 자격(전 벤더 BMC / OS / ESXi)** 복호화 가능 → vault 암호화가 사실상 무효 |
| (동일 값) | `__REDACTED__` | Dell BMC `root` 암호 + lab Linux SSH/sudo 암호 | BMC/호스트 직접 장악 |
| **BMC primary 계정** | `__REDACTED__Infra` (`infraops`) | 5 벤더 통일 primary Redfish 계정 | 전 벤더 BMC 인증 장악 |
| **BMC recovery** | `__REDACTED__` (HPE admin / Lenovo USERID), `__REDACTED__` (Cisco admin) | 공장/복구 계정 — 최고 권한 fallback | BMC 복구 경로 장악 |

> 정본 확인: `docs/operate/05-vault.md` (vault 암호 = `__REDACTED__`), `jenkins/jobs/redfish-account-provision-verify/config.xml:100` (`echo '__REDACTED__' > .vault_pass`).

## 2. 노출 인벤토리 (추적 파일 기준 — 2026-10-05 재검사)

검사 방법: 현재 vault 마스터 암호로 `vault/**` 추적 파일 49개를 모두 열어(49/49) password 계열 값 15개를 꺼내고, 이 런북 85행에 있던
옛 값 1개를 더해 **모든 추적 텍스트 파일**에서 찾았다. 값은 메모리에서만 다뤘고 출력 · 파일 기록은 하지 않았다(경로와 개수만 기록).

| 대상 | 추적 파일 | 판정 |
|---|---|---|
| 현재 vault 마스터 암호 | 0 | 노출 없음 |
| 현재 vault 안 자격 값(OS · ESXi · Redfish 표준 · 복구) | 0 | 노출 없음 — 아래 공개 기본값 2종 제외 |
| Cisco 공장 기본값 (`password` 라는 일반 단어) | 452 | 노출 아님 — 일반 단어라 설정 키 이름 · 문서와 겹친다 |
| Huawei 공장 기본값 | 4 | 노출 아님 — 제조사가 공개한 값. `docs/operate/05-vault.md` 기본값 표와 secret_guard 허용 목록 |
| 이 런북 85행의 옛 값 | 1 → **0** | 2026-10-05 에 `__REDACTED__` 로 가렸다. 현재 vault 마스터 암호가 아니고 현재 vault 의 어떤 자격 값과도 같지 않다 |

- **git 히스토리에는 남아 있다**: 85행의 옛 값은 이 런북에 그 값이 들어간 2026-08-12 commit 1개에 남아 있다. 이 값이 아직 어느 장비에서
  쓰이는지는 확인하지 않았다 — 교체(회전)와 히스토리 정리는 사용자 결정이다(4절, 사용자 지시: 토큰 폐기 · 재발급 금지).
- 저장소 공개 범위: GitHub 저장소는 익명 읽기가 된다(2026-10-05 확인). 히스토리에 남은 값은 그대로 읽힌다.
- 2026-05-29 실측(이력): 당시 추적 파일 387개에 평문이 있었다(reference 캡처 289 · evidence 65 · 기타 33). 이후 정리로 현재 값 기준 0개다.

## 3. 회전 절차 (사용자/운영자 실행)

### 3.1 vault 마스터 암호 재키 (rekey) — [CRIT] 최우선
```bash
# 새 강력 암호 생성 후 (예: 32+ random):
NEW=$(openssl rand -base64 24)
for f in $(git ls-files 'vault/**/*.yml'); do
  ansible-vault rekey --new-vault-password-file <(echo "$NEW") "$f"
done
# Jenkins credential 'server-gather-vault-password' 값을 NEW 로 갱신
# (docs/operate/05-vault.md 시나리오 A 참조)
```

### 3.2 실제 자격 교체 (BMC/호스트 — vault 안 값 자체)
- Dell BMC `root` (= `__REDACTED__`), lab Linux SSH/sudo: 각 장비에서 암호 변경 후 `vault/<loc>/redfish/dell.yml` / `vault/<loc>/os/linux.yml` 갱신
- primary `infraops/__REDACTED__Infra`: 전 벤더 BMC 에서 변경 후 `vault/<loc>/redfish/<vendor>.yml` 갱신
- recovery `__REDACTED__` / `__REDACTED__`: HPE/Lenovo/Cisco BMC recovery 계정 변경 후 vault 갱신
> 회전 후 `vault/**` 재암호화 (3.1 의 NEW 키로). 회전 전·후 모두 `git ls-files vault/` 가 암호화 상태인지 확인.

### 3.3 운영 메커니즘 수정 — config.xml (2026-10-05 확인: 해소)
`jenkins/jobs/redfish-account-provision-verify/config.xml` 은 이제 평문 대신 자격 증명 변수(`${VAULT_PASSWORD}`)를 `.vault_pass` 에 쓴다.
수집 Job(`Jenkinsfile_portal`)은 `withCredentials(string 'server-gather-vault-password')` 로 받은 값을 임시 파일(권한 600)에만 쓰고 끝나면 지운다.

## 4. git 히스토리 정리 (선택 — force-push 필요, rule 93)

회전(3.x)을 먼저 하면 히스토리의 옛 값은 "이미 폐기된 값"이 되어 위험이 크게 감소한다. 그래도 히스토리에서 제거하려면:
```bash
# git filter-repo 권장 (BFG 대안)
pip install git-filter-repo
git filter-repo --replace-text <(printf '__REDACTED__==>REDACTED\n__REDACTED__Infra==>REDACTED\n__REDACTED__==>REDACTED\n__REDACTED__==>REDACTED\n')
```
> **[CRIT] 제약**: 히스토리 재작성은 **force-push** 가 필수 (rule 93 R1 — AI 자율 금지, **사용자 명시 승인 필요**). 모든 클론/포크가 재clone 해야 함. github + gitlab 양쪽(rule 93 R7) 좌표. 본 audit 에서는 **미수행** (사용자 결정 "문서화만" + force-push 미승인).

## 5. 본 audit 가 한 것 / 안 한 것

- **안 함 (사용자 "문서화만")**: 시크릿 자동 스크럽, config.xml 수정, vault 회전, 히스토리 재작성.
- **함 (2026-10-05)**: 85행 평문 1건 가림, 추적 파일 재검사(2절), 3.3 해소 확인. 회전 · 히스토리 재작성 · 토큰 폐기는 하지 않았다(사용자 결정 대기).
- **함**: 본 런북 작성 + 인벤토리. (task 6 docs cleanup 이 일부 완료-cycle 덤프 시크릿분을 HEAD 에서 부수적 제거 — 의도는 doc 정리.)

## 6. 검증 체크리스트 (회전 후)
- [ ] `ansible-vault view vault/<loc>/redfish/dell.yml` 가 NEW 키로만 열림 (옛 키 거부)
- [ ] `git grep -I '__REDACTED__'` → 0 (스크럽 선택 시)
- [ ] Jenkins `redfish-account-provision-verify` job 이 credential binding 으로 동작
- [ ] BMC 로그인: 옛 암호 거부 / NEW 암호 허용
- [ ] (히스토리 정리 시) `git log -S '__REDACTED__' --oneline` → 0

## 관련
- rule: `60-security-and-secrets`(해제됨, 참고), `93-branch-merge-gate` R1(force-push), `27-precheck-guard-first` R6(vault)
- 정본: `docs/operate/05-vault.md`, `docs/ai/policy/SECURITY_POLICY.md`
- 인접 권고(인증 동작): `docs/ai/contracts/account-write-vendor-compat.md` §AUTH (lockout/dryrun)
