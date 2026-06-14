#!/bin/bash
# F49 (cycle 2026-05-01): redfish account_provision 검증 자동화 스크립트.
#
# 목적:
#   - server-exporter agent 에서 5 BMC 대상 redfish-gather 실행
#   - envelope.diagnosis.details.account_service 결과 표 형식으로 정리
#   - dryrun=true 가 default (실 변경 없음)
#   - 실 적용은 ACCOUNT_PROVISION_DRYRUN=false 명시 필요
#
# 사용:
#   bash scripts/verify_account_provision.sh                        # dryrun
#   bash scripts/verify_account_provision.sh --target 10.100.15.27  # 1대만
#   ACCOUNT_PROVISION_DRYRUN=false bash scripts/verify_account_provision.sh  # 실 적용
#
# 환경 가정:
#   - cwd: server-exporter repo root
#   - /opt/ansible-env/bin/activate 가능 (Jenkins agent 표준)
#   - .vault_pass 파일 존재 (Jenkins credentials 또는 수동 작성)
#   - inventory yaml 자동 생성

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(pwd)}"
DRYRUN="${ACCOUNT_PROVISION_DRYRUN:-true}"

# 5 BMC 매트릭스 (lab 기준선 — vault/.lab-credentials.yml 와 동기)
declare -A BMC_VENDORS=(
  ["10.100.15.27"]="dell"
  ["10.100.15.31"]="dell"
  ["10.50.11.231"]="hpe"
  ["10.50.11.232"]="lenovo"
  ["10.100.15.2"]="cisco"
)

# CLI 파라미터
SINGLE_TARGET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) SINGLE_TARGET="$2"; shift 2 ;;
    --dryrun) DRYRUN="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

# 단일 타겟 모드
if [[ -n "$SINGLE_TARGET" ]]; then
  if [[ -z "${BMC_VENDORS[$SINGLE_TARGET]:-}" ]]; then
    echo "[ERR] $SINGLE_TARGET 은 등록된 BMC 가 아닙니다 (BMC_VENDORS 갱신 필요)"
    exit 2
  fi
  TARGETS=("$SINGLE_TARGET")
else
  TARGETS=("${!BMC_VENDORS[@]}")
fi

# venv activate (Jenkins agent 환경)
if [[ -f /opt/ansible-env/bin/activate ]]; then
  # shellcheck disable=SC1091
  source /opt/ansible-env/bin/activate
fi

# .vault_pass 확인
if [[ ! -f "$REPO_ROOT/.vault_pass" ]]; then
  echo "[ERR] $REPO_ROOT/.vault_pass 파일이 없습니다."
  echo "    Jenkins: credentials binding 으로 작성"
  echo "    수동: echo 'YOUR_VAULT_PASS' > $REPO_ROOT/.vault_pass; chmod 600 $REPO_ROOT/.vault_pass"
  exit 3
fi

# results dir
OUT_DIR="${REPO_ROOT}/tests/evidence/account_provision_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"

echo "================================================================="
echo "F49 redfish account_provision 검증 — dryrun=$DRYRUN"
echo "Targets: ${TARGETS[*]}"
echo "Output : $OUT_DIR"
echo "================================================================="

declare -a SUMMARY_ROWS

for ip in "${TARGETS[@]}"; do
  vendor="${BMC_VENDORS[$ip]}"
  echo
  echo "---- $ip ($vendor) ----"

  # inventory yaml
  inv="$OUT_DIR/inv_${ip//./_}.yml"
  cat > "$inv" <<EOF
all:
  hosts:
    $ip:
      ansible_connection: local
      ansible_host: $ip
EOF

  log="$OUT_DIR/run_${ip//./_}.log"
  REPO_ROOT="$REPO_ROOT" \
  ANSIBLE_CONFIG="$REPO_ROOT/ansible.cfg" \
  ANSIBLE_INVENTORY_ENABLED="auto,yaml,ini,script" \
  ansible-playbook \
    -i "$inv" \
    --vault-password-file "$REPO_ROOT/.vault_pass" \
    "$REPO_ROOT/redfish-gather/site.yml" \
    -e "_rf_account_service_dryrun=$DRYRUN" \
    > "$log" 2>&1 || true

  # envelope 추출 (json_only callback OUTPUT)
  envelope_json="$OUT_DIR/envelope_${ip//./_}.json"
  python3 - "$log" "$envelope_json" <<'PY'
import json, re, sys
log_path, out_path = sys.argv[1], sys.argv[2]
with open(log_path, encoding='utf-8', errors='replace') as f:
    text = f.read()
idx = text.find('"target_type"')
if idx < 0:
    print("NO_ENVELOPE")
    sys.exit(0)
for start in range(idx, -1, -1):
    if text[start] == '{':
        depth = 0
        for end in range(start, len(text)):
            if text[end] == '{':
                depth += 1
            elif text[end] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        env = json.loads(text[start:end+1])
                        with open(out_path, 'w', encoding='utf-8') as out:
                            json.dump(env, out, indent=2, ensure_ascii=False)
                        diag = (env.get('diagnosis') or {}).get('details') or {}
                        auth = diag.get('auth') if isinstance(diag, dict) else {}
                        acct = diag.get('account_service') if isinstance(diag, dict) else {}
                        print(f"status={env.get('status')}|"
                              f"vendor={env.get('vendor')}|"
                              f"used_label={(auth or {}).get('used_label')}|"
                              f"used_role={(auth or {}).get('used_role')}|"
                              f"acct_method={(acct or {}).get('method', 'noop')}|"
                              f"acct_recovered={(acct or {}).get('recovered', False)}")
                        sys.exit(0)
                    except json.JSONDecodeError:
                        continue
        break
print("PARSE_FAIL")
PY
  parsed=$(python3 - "$log" <<'PY'
import json, sys
with open(sys.argv[1], encoding='utf-8', errors='replace') as f:
    text = f.read()
idx = text.find('"target_type"')
if idx < 0:
    print("NO_ENVELOPE")
    sys.exit(0)
for start in range(idx, -1, -1):
    if text[start] == '{':
        depth = 0
        for end in range(start, len(text)):
            if text[end] == '{':
                depth += 1
            elif text[end] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        env = json.loads(text[start:end+1])
                        diag = (env.get('diagnosis') or {}).get('details') or {}
                        auth = diag.get('auth') if isinstance(diag, dict) else {}
                        acct = diag.get('account_service') if isinstance(diag, dict) else {}
                        print(f"status={env.get('status')}|used_role={(auth or {}).get('used_role')}|method={(acct or {}).get('method', 'noop')}|recovered={(acct or {}).get('recovered', False)}")
                        sys.exit(0)
                    except json.JSONDecodeError:
                        continue
        break
print("PARSE_FAIL")
PY
)
  echo "  parsed: $parsed"
  SUMMARY_ROWS+=("$ip|$vendor|$parsed")
done

echo
echo "================================================================="
echo "SUMMARY ($DRYRUN)"
echo "================================================================="
printf "%-15s %-10s %s\n" "IP" "Vendor" "Result"
for row in "${SUMMARY_ROWS[@]}"; do
  ip=$(echo "$row" | cut -d'|' -f1)
  vendor=$(echo "$row" | cut -d'|' -f2)
  rest=$(echo "$row" | cut -d'|' -f3-)
  printf "%-15s %-10s %s\n" "$ip" "$vendor" "$rest"
done

echo
echo "Logs / envelopes saved to: $OUT_DIR"
