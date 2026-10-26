#!/bin/bash
# 운영(Jenkinsfile_portal seGatherEnv + scripts/run_gather.sh)과 같은 환경·인자로 redfish-gather/site.yml 을 실제 엔진으로 실행한다.
# 사용: run_playbook.sh <OUT_DIR(linux path)> <LOCATION> [TARGET_IP=127.0.0.1]
# 차이(검증 한계로 기록): run_gather.sh 의 작업 폴더 잠금 · gather_state.py begin/end · FORKS 계산 · 대상 목록 재개는 거치지 않는다.
set -u
OUT="$1"; LOCATION="${2:-yi}"; TARGET="${3:-127.0.0.1}"
REPO=/mnt/c/github/ClovirONE/clovirone-server-gathering
mkdir -p "$OUT/gather_auth_evidence"
cd "$REPO" || exit 90
printf '[{"service_ip":"%s"}]' "$TARGET" > "$OUT/.inventory_input.json"
printf '%s\n' "$TARGET" > "$OUT/.gather_limit_hosts"
rm -f "$OUT/gather_output.json" "$OUT/gather_progress.jsonl" "$OUT/gather_checkpoint.jsonl"
export REPO_ROOT="$REPO"
export ANSIBLE_CONFIG="$REPO/ansible.cfg"
export ANSIBLE_JSON_OUTPUT_FILE="$OUT/gather_output.json"
export ANSIBLE_JSON_PROGRESS_FILE="$OUT/gather_progress.jsonl"
export ANSIBLE_JSON_CHECKPOINT_FILE="$OUT/gather_checkpoint.jsonl"
export INVENTORY_JSON_FILE="$OUT/.inventory_input.json"
export SE_AUTH_EVIDENCE_DIR="$OUT/gather_auth_evidence"
export SE_BUILD_ID="mock2-audit-20261026"
export SE_EVENT_UUID=""
export ANSIBLE_VERBOSITY="${ANSIBLE_VERBOSITY:-0}"
export ANSIBLE_INVENTORY_UNPARSED_FAILED=True
export PYTHONHASHSEED=0
export ANSIBLE_SSH_CONTROL_PATH_DIR="$(mktemp -d /tmp/se_cp.XXXXXX)"
START=$(date +%s)
timeout --signal=INT --kill-after=90 1800 \
  ansible-playbook redfish-gather/site.yml -i os-gather/inventory.sh -f 2 --limit "@$OUT/.gather_limit_hosts" \
  --vault-password-file="$HOME/.se_vault_pass" -e se_location="$LOCATION" > "$OUT/ansible_stdout.log" 2> "$OUT/ansible_stderr.log"
RC=$?
END=$(date +%s)
echo "{\"rc\": $RC, \"elapsed_s\": $((END-START)), \"location\": \"$LOCATION\", \"target\": \"$TARGET\"}" > "$OUT/run_meta.json"
rm -rf "$ANSIBLE_SSH_CONTROL_PATH_DIR"
echo "RC=$RC elapsed=$((END-START))s"
exit $RC
