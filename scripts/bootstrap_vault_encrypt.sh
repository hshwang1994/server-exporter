#!/usr/bin/env bash
# =============================================================================
# scripts/bootstrap_vault_encrypt.sh
#
# 평문 vault/*.yml 을 ansible-vault 로 일괄 암호화한다.
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

VAULT_FILES=(
    "${REPO_ROOT}/vault/linux.yml"
    "${REPO_ROOT}/vault/windows.yml"
    "${REPO_ROOT}/vault/esxi.yml"
    "${REPO_ROOT}/vault/redfish/dell.yml"
    "${REPO_ROOT}/vault/redfish/hpe.yml"
    "${REPO_ROOT}/vault/redfish/lenovo.yml"
    "${REPO_ROOT}/vault/redfish/supermicro.yml"
    "${REPO_ROOT}/vault/redfish/cisco.yml"
)

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
     상세 절차: docs/01_jenkins-setup.md
EOF
