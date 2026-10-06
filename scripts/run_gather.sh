#!/bin/bash
set -eo pipefail
set +x

PLAYBOOK="${1:-}"; INVENTORY="${2:-}"; FORKS="${3:-}"; LIMIT="${4:-}"; LOCATION="${5:-}"; ADDON_OK="${6:-false}"; HOSTS="${7:-?}"
if [ -z "$PLAYBOOK" ] || [ -z "$INVENTORY" ] || ! [[ "$FORKS" =~ ^[0-9]+$ ]] || ! [[ "$LIMIT" =~ ^[0-9]+$ ]] || [ "$FORKS" -lt 1 ] || [ "$LIMIT" -lt 1 ]; then
    echo "[수집] 실행 인자가 잘못됐습니다: playbook · inventory · forks(1 이상) · 한계(초, 1 이상)가 필요합니다" >&2
    exit 2
fi
WS="${WORKSPACE:-$(pwd)}"
cd "$WS"

se_show() { date '+%Y-%m-%d %H:%M:%S %:z'; }
se_iso() { date -u '+%Y-%m-%dT%H:%M:%S.%3NZ'; }
se_dur() {
    local s="$1" h m out=""
    h=$(( s / 3600 )); m=$(( (s % 3600) / 60 )); s=$(( s % 60 ))
    [ "$h" -gt 0 ] && out="${h}시간 "
    [ "$m" -gt 0 ] && out="${out}${m}분 "
    if [ "$s" -gt 0 ] || [ -z "$out" ]; then out="${out}${s}초"; fi
    echo "${out% }"
}

VAULT_TMP=""
SE_CP_DIR=""
SSH_CLOSED=0
se_close_ssh() {
    local s
    [ -n "$SE_CP_DIR" ] && [ -d "$SE_CP_DIR" ] || return 0
    for s in "$SE_CP_DIR"/*; do
        [ -S "$s" ] || continue
        if ssh -o ControlPath="$s" -O exit se-close >/dev/null 2>&1; then SSH_CLOSED=$((SSH_CLOSED + 1)); fi
    done
    pkill -TERM -f "$SE_CP_DIR/" >/dev/null 2>&1 || true
    rm -rf "$SE_CP_DIR" 2>/dev/null || true
}
se_cleanup() {
    se_close_ssh
    [ -n "$VAULT_TMP" ] && rm -f "$VAULT_TMP"
    return 0
}
trap se_cleanup EXIT
trap 'se_cleanup; exit 143' TERM
trap 'se_cleanup; exit 130' INT
trap 'se_cleanup; exit 129' HUP

. "$WS/scripts/env_guard.sh" "$ADDON_OK"
. "$WS/scripts/activate_ansible_venv.sh" || exit 90
export ANSIBLE_INVENTORY_UNPARSED_FAILED=True
chmod +x "$INVENTORY"
VAULT_TMP="$(mktemp)"
printf '%s' "${VAULT_PASSWORD:-}" > "$VAULT_TMP"
chmod 600 "$VAULT_TMP"
SE_CP_DIR="$(mktemp -d /tmp/se_cp.XXXXXX)"
export ANSIBLE_SSH_CONTROL_PATH_DIR="$SE_CP_DIR"

STARTED_AT="$(se_iso)"
echo "[$(se_show)] [수집] 시작합니다. 대상 ${HOSTS}대, 동시 실행 ${FORKS}대, 실행 한계 $(se_dur "$LIMIT")(${LIMIT}초)."
SECONDS=0
set +e
timeout --signal=INT --kill-after=90 "$LIMIT" \
    ansible-playbook "$PLAYBOOK" -i "$INVENTORY" -f "$FORKS" --vault-password-file="$VAULT_TMP" -e se_location="$LOCATION"
rc=$?
ran=$SECONDS
se_close_ssh
set -e
ENDED_AT="$(se_iso)"
timed_out=false
if { [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; } && [ "$ran" -ge "$LIMIT" ]; then timed_out=true; fi
echo "$rc" > "$WS/gather_rc.txt"
printf '{"started_at":"%s","ended_at":"%s","ran_sec":%d,"limit_sec":%d,"rc":%d,"timed_out":%s,"ssh_closed":%d}\n' \
    "$STARTED_AT" "$ENDED_AT" "$ran" "$LIMIT" "$rc" "$timed_out" "$SSH_CLOSED" > "$WS/gather_run.json"
if [ "$timed_out" = true ]; then
    how="INT 로 멈췄습니다"
    [ "$rc" -eq 137 ] && how="INT 뒤 정리 시간 90초가 지나 강제 종료했습니다"
    echo "[$(se_show)] [수집] 실행 한계 $(se_dur "$LIMIT")(${LIMIT}초)에 도달해 ${how}. 실행 시간 $(se_dur "$ran"), 종료 코드 ${rc}. 끝난 대상의 결과는 보존합니다."
    echo "[$(se_show)] [수집] 이 실행이 연 원격 연결을 닫아 대상에서 돌던 명령을 정리했습니다(연결 ${SSH_CLOSED}개)."
elif [ "$rc" -eq 137 ]; then
    echo "[$(se_show)] [수집] 실행 한계 전에 강제 종료됐습니다(종료 코드 137). 메모리 부족 같은 다른 원인을 Runner 에서 확인하세요. 실행 시간 $(se_dur "$ran")."
else
    echo "[$(se_show)] [수집] 끝났습니다. 실행 시간 $(se_dur "$ran"), 종료 코드 ${rc}."
fi
exit "$rc"
