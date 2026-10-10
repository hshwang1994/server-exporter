#!/usr/bin/env bash
# =============================================================================
# scripts/bootstrap_vault_encrypt.sh
#
# 평문 vault/**/*.yml 을 ansible-vault 로 일괄 암호화한다 (vault/common/redfish/standard.yml + vault/<loc>/...).
# 사용자 결정 (cycle 2026-04-28):
#   - vault 처리 정책 = "ansible-vault encrypt 후 commit"
#   - Jenkins credentials ID = "server-gather-vault-password" (Secret File)
#
# 사용법:
#   1. vault 마스터 password 를 결정 후 .vault_pass 파일에 저장
#        echo -n 'YOUR_VAULT_PASSWORD' > .vault_pass
#        chmod 600 .vault_pass
#      .vault_pass 는 .gitignore 에 의해 commit 되지 않는다.
#   2. 본 스크립트 실행
#        bash scripts/bootstrap_vault_encrypt.sh
#   3. 변경된 vault/*.yml 을 commit + push
#   4. 동일한 .vault_pass 파일을 Jenkins credentials store 에 등록
#        (Secret file, ID = server-gather-vault-password)
#
# 본 스크립트는 idempotent: 이미 암호화된 파일은 건너뛴다.
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VAULT_PASS_FILE="${REPO_ROOT}/.vault_pass"

if [[ ! -f "${VAULT_PASS_FILE}" ]]; then
    echo "[ERROR] .vault_pass 파일이 없습니다: ${VAULT_PASS_FILE}" >&2
    echo "        먼저 'echo -n PASSWORD > .vault_pass && chmod 600 .vault_pass' 로 생성하세요." >&2
    exit 1
fi

if [[ "$(stat -c '%a' "${VAULT_PASS_FILE}" 2>/dev/null || stat -f '%Lp' "${VAULT_PASS_FILE}")" != "600" ]]; then
    echo "[WARN] .vault_pass 권한이 600 이 아닙니다. chmod 600 으로 보정합니다." >&2
    chmod 600 "${VAULT_PASS_FILE}"
fi

# 현재 vault 배치(2026-08-12 flat 제거 뒤): vault/common/redfish/standard.yml(전역 표준 계정) + vault/<loc>/{os/linux.yml,os/windows.yml,esxi.yml,redfish/<vendor>.yml}.
# 디렉터리를 재귀로 훑는다 — 평문 lab 자격 파일(.lab-credentials.yml, gitignored)과 README 는 대상이 아니다. 0건이면 실패다(2026-10-11: 종전 flat 경로 목록은 0건을 성공으로 보고했다).
mapfile -t VAULT_FILES < <(find "${REPO_ROOT}/vault" -type f -name '*.yml' ! -name '.*' ! -iname 'README*' | sort)
if [[ "${#VAULT_FILES[@]}" -eq 0 ]]; then
    echo "[ERROR] vault/ 아래에 암호화할 *.yml 이 없습니다: ${REPO_ROOT}/vault" >&2
    exit 1
fi

encrypted_count=0
skipped_count=0
missing_count=0

for f in "${VAULT_FILES[@]}"; do
    if [[ ! -f "${f}" ]]; then
        echo "[SKIP] 파일 없음: ${f}"
        missing_count=$((missing_count + 1))
        continue
    fi

    # 이미 암호화된 파일은 첫 줄이 '$ANSIBLE_VAULT;1.1;AES256' 형태
    if head -n 1 "${f}" | grep -q '^\$ANSIBLE_VAULT'; then
        echo "[SKIP] 이미 암호화: ${f}"
        skipped_count=$((skipped_count + 1))
        continue
    fi

    echo "[ENCRYPT] ${f}"
    ansible-vault encrypt \
        --vault-password-file="${VAULT_PASS_FILE}" \
        "${f}"
    encrypted_count=$((encrypted_count + 1))
done

cat <<EOF

[OK] vault 부트스트랩 완료
- 암호화: ${encrypted_count}
- 이미 암호화: ${skipped_count}
- 파일 없음: ${missing_count}

다음 단계:
  1. git diff vault/ 로 변경 확인
  2. git add vault/ && git commit -m "feat: vault encrypt (P0)"
  3. Jenkins credentials store 에 server-gather-vault-password (Secret File) 등록
     상세 절차: docs/operate/01-jenkins-master.md
EOF
