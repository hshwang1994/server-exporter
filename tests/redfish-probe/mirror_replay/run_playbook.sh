#!/bin/bash
# Tier 1: 운영(Jenkinsfile_portal seGatherEnv + scripts/run_gather.sh)과 같은 환경·인자로 redfish-gather/site.yml 을 실제 엔진으로 실행한다.
# 사용: [SE_REPO_ROOT=<repo>] [SE_VAULT_PASSWORD_FILE=~/.se_vault_pass] [SE_BUILD_ID=...] [SE_GATHER_TIMEOUT=1800]
#       run_playbook.sh <OUT_DIR(linux path)> <LOCATION> [TARGET_IP=127.0.0.1]
# 운영과 같은 것: redfish-gather/inventory.sh + INVENTORY_JSON_FILE([{"bmc_ip":...}]), seGatherEnv 변수 전부, --limit @file,
#   --vault-password-file, -e se_location, timeout --signal=INT --kill-after=90.
# 운영과 다른 것(검증 한계로 기록): run_gather.sh 의 작업 폴더 잠금 · gather_state.py begin/end · FORKS 계산 · 대상 목록 재개는 거치지 않는다.
set -u
OUT="${1:?usage: run_playbook.sh <OUT_DIR> <LOCATION> [TARGET_IP]}"; LOCATION="${2:?LOCATION}"; TARGET="${3:-127.0.0.1}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${SE_REPO_ROOT:-$(cd "$HERE/../../.." && pwd)}"
VAULT="${SE_VAULT_PASSWORD_FILE:-$HOME/.se_vault_pass}"
if [ ! -f "$VAULT" ]; then echo "vault password file not found: $VAULT (SE_VAULT_PASSWORD_FILE)" >&2; exit 91; fi
mkdir -p "$OUT/gather_auth_evidence"
cd "$REPO" || exit 90
printf '[{"bmc_ip":"%s"}]' "$TARGET" > "$OUT/.inventory_input.json"
printf '{"ips":["%s"],"target_type":"redfish","loc":"%s","source":"mirror_replay"}' "$TARGET" "$LOCATION" > "$OUT/gather_manifest.json"
printf '%s\n' "$TARGET" > "$OUT/.gather_limit_hosts"
rm -f "$OUT/gather_output.json" "$OUT/gather_progress.jsonl" "$OUT/gather_checkpoint.jsonl"
export REPO_ROOT="$REPO"
export ANSIBLE_CONFIG="$REPO/ansible.cfg"
export ANSIBLE_JSON_OUTPUT_FILE="$OUT/gather_output.json"
export ANSIBLE_JSON_MANIFEST_FILE="$OUT/gather_manifest.json"
export ANSIBLE_JSON_PROGRESS_FILE="$OUT/gather_progress.jsonl"
export ANSIBLE_JSON_CHECKPOINT_FILE="$OUT/gather_checkpoint.jsonl"
export INVENTORY_JSON_FILE="$OUT/.inventory_input.json"
export SE_AUTH_EVIDENCE_DIR="$OUT/gather_auth_evidence"
export SE_BUILD_ID="${SE_BUILD_ID:-mirror-replay-$(date -u +%Y%m%dT%H%M%SZ)}"
export SE_EVENT_UUID="${SE_EVENT_UUID:-}"
export ANSIBLE_VERBOSITY="${ANSIBLE_VERBOSITY:-0}"
export ANSIBLE_INVENTORY_UNPARSED_FAILED=True
export PYTHONHASHSEED=0
export ANSIBLE_SSH_CONTROL_PATH_DIR="$(mktemp -d /tmp/se_cp.XXXXXX)"
START=$(date +%s)
timeout --signal=INT --kill-after=90 "${SE_GATHER_TIMEOUT:-1800}" \
  ansible-playbook redfish-gather/site.yml -i redfish-gather/inventory.sh -f 2 --limit "@$OUT/.gather_limit_hosts" \
  --vault-password-file="$VAULT" -e se_location="$LOCATION" > "$OUT/ansible_stdout.log" 2> "$OUT/ansible_stderr.log"
RC=$?
END=$(date +%s)
printf '{"rc": %s, "elapsed_s": %s, "location": "%s", "target": "%s", "build_id": "%s", "ansible": "%s"}\n' \
  "$RC" "$((END-START))" "$LOCATION" "$TARGET" "$SE_BUILD_ID" "$(ansible-playbook --version 2>/dev/null | head -1 | tr -d '\n')" > "$OUT/run_meta.json"
rm -rf "$ANSIBLE_SSH_CONTROL_PATH_DIR"
echo "RC=$RC elapsed=$((END-START))s"
exit $RC
