#!/bin/bash
set -eo pipefail
set +x

PLAYBOOK="${1:-}"; INVENTORY="${2:-}"; LOCATION="${3:-}"; ADDON_OK="${4:-false}"; GATHER_MAX="${5:-}"; AGENT_LOST="${6:-false}"
if [ -z "$PLAYBOOK" ] || [ -z "$INVENTORY" ] || ! [[ "$GATHER_MAX" =~ ^[0-9]+$ ]] || [ "$GATHER_MAX" -lt 1 ]; then
    echo "[수집] 실행 인자가 잘못됐습니다: playbook · inventory · 실행 위치 · Add-on 검사 결과 · 수집 실행 한계(초, 1 이상)가 필요합니다" >&2
    exit 2
fi
WS="${WORKSPACE:-$(pwd)}"
cd "$WS"

se_show() { date '+%Y-%m-%d %H:%M:%S %:z'; }
se_dur() {
    local s="$1" h m out=""
    h=$(( s / 3600 )); m=$(( (s % 3600) / 60 )); s=$(( s % 60 ))
    [ "$h" -gt 0 ] && out="${h}시간 "
    [ "$m" -gt 0 ] && out="${out}${m}분 "
    if [ "$s" -gt 0 ] || [ -z "$out" ]; then out="${out}${s}초"; fi
    echo "${out% }"
}
se_state_text() {
    case "$1" in
        runner_restart) echo "Runner 가 다시 부팅됐습니다" ;;
        runner_oom) echo "Runner 에서 메모리 부족(OOM) 종료가 기록됐습니다" ;;
        agent_disconnect) echo "Runner 와 Jenkins 의 연결이 끊겼습니다" ;;
        process_lost) echo "수집 프로세스가 끝 기록 없이 사라졌습니다(원인 미확인)" ;;
        *) echo "$1" ;;
    esac
}

VAULT_TMP=""
SE_CP_DIR=""
SSH_CLOSED=0
ALIVE_PID=""
STARTED=false
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
se_stop_alive() {
    if [ -n "$ALIVE_PID" ]; then kill "$ALIVE_PID" >/dev/null 2>&1 || true; fi
    ALIVE_PID=""
    return 0
}
se_cleanup() {
    se_stop_alive
    se_close_ssh
    [ -n "$VAULT_TMP" ] && rm -f "$VAULT_TMP"
    return 0
}
se_on_signal() {
    se_cleanup
    if [ "$STARTED" = true ]; then
        python3 "$WS/scripts/gather_state.py" end --ws "$WS" --rc "$1" --ssh-closed "$SSH_CLOSED" >/dev/null 2>&1 || true
    fi
    exit "$1"
}
trap se_cleanup EXIT
trap 'se_on_signal 143' TERM
trap 'se_on_signal 130' INT
trap 'se_on_signal 129' HUP

se_parent_alive() {
    kill -0 "$1" 2>/dev/null || return 1
    if grep -q '^State:[[:space:]]*Z' "/proc/$1/status" 2>/dev/null; then return 1; fi
    return 0
}
se_alive_loop() {
    local parent="$1" since="$SECONDS" last="$SECONDS"
    while se_parent_alive "$parent"; do
        touch "$WS/.gather_alive" 2>/dev/null || true
        if [ $((SECONDS - last)) -ge 300 ]; then
            last="$SECONDS"
            echo "[$(se_show)] [수집] 진행 중: 이번 시도 경과 $(se_dur $((SECONDS - since))), 결과 확정 $(python3 "$WS/scripts/gather_state.py" count --ws "$WS" 2>/dev/null || echo '?')대."
        fi
        sleep 60 </dev/null >/dev/null 2>&1
    done
}

exec 9>>"$WS/.gather.lock"
if ! flock -n 9; then
    echo "[$(se_show)] [수집] 이 빌드의 이전 수집이 아직 실행 중입니다(Runner 연결이 끊긴 동안에도 계속 돈 실행). 끝나기를 기다린 뒤 남은 대상만 이어서 수집합니다."
    while ! flock -w 300 9; do
        echo "[$(se_show)] [수집] 이전 수집이 끝나기를 계속 기다립니다. 결과 확정 $(python3 "$WS/scripts/gather_state.py" count --ws "$WS" 2>/dev/null || echo '?')대."
    done
fi

. "$WS/scripts/env_guard.sh" "$ADDON_OK"
. "$WS/scripts/activate_ansible_venv.sh" || exit 90
export ANSIBLE_INVENTORY_UNPARSED_FAILED=True
chmod +x "$INVENTORY"
VAULT_TMP="$(mktemp /tmp/se_vault.XXXXXXXXXX)"
printf '%s' "${VAULT_PASSWORD:-}" > "$VAULT_TMP"
chmod 600 "$VAULT_TMP"
SE_CP_DIR="$(mktemp -d /tmp/se_cp.XXXXXX)"
export ANSIBLE_SSH_CONTROL_PATH_DIR="$SE_CP_DIR"

AGENT_FLAG=""
[ "$AGENT_LOST" = true ] && AGENT_FLAG="--prev-agent-lost"
if ! PLAN="$(python3 "$WS/scripts/gather_state.py" begin --ws "$WS" --pid "$$" --vault-tmp "$VAULT_TMP" --cp-dir "$SE_CP_DIR" \
        --gather-max "$GATHER_MAX" --vcpu "$(nproc 2>/dev/null || echo 2)" --os-forks-cap "${SE_FORKS_CAP_OS:-}" $AGENT_FLAG)"; then
    echo "[$(se_show)] [수집] 실행 기록을 준비하지 못했습니다(scripts/gather_state.py begin). 위의 [수집 기록] 줄을 보세요."
    exit 91
fi
eval "$(python3 -c '
import json, shlex, sys
p = json.loads(sys.argv[1])
pairs = (("ATTEMPT", p["attempt"]), ("PENDING", p["pending"]), ("LIMIT", p["limit"]), ("FORKS", p["forks"]),
         ("TOTAL", p["hosts_total"]), ("DONE", p["completed"]), ("PREFAIL", p["precheck_failed"]), ("USED", p["exec_used"]),
         ("PREV", p.get("closed_previous") or ""), ("PREV_EV", p.get("closed_evidence") or ""), ("FIXED", ",".join(p.get("tail_fixed") or [])))
print(" ".join("%s=%s" % (k, shlex.quote(str(v))) for k, v in pairs))
' "$PLAN")"

if [ "$ATTEMPT" -gt 1 ]; then
    msg="[$(se_show)] [수집] ${ATTEMPT}번째 시도로 이어서 수집합니다. 접수 ${TOTAL}대 중 결과가 확정된 ${DONE}대"
    [ "$PREFAIL" -gt 0 ] && msg="${msg}와 사전 점검 실패로 확정된 ${PREFAIL}대"
    echo "${msg}는 다시 수집하지 않습니다. 지금까지 실제 수집 시간 $(se_dur "$USED")."
    if [ -n "$PREV" ]; then
        echo "[$(se_show)] [수집] 이전 시도는 끝 기록 없이 중단됐습니다: $(se_state_text "$PREV")${PREV_EV:+ (근거: ${PREV_EV})}."
    fi
fi
if [ -n "$FIXED" ]; then
    echo "[$(se_show)] [수집] 쓰는 도중 끊긴 마지막 줄을 gather_tail_fragments.jsonl 로 옮겼습니다(${FIXED}). 그 대상은 다시 수집합니다."
fi
if [ "$PENDING" -eq 0 ]; then
    echo "[$(se_show)] [수집] 남은 대상이 없습니다. 접수 ${TOTAL}대의 결과가 모두 확정돼 있어 ansible 을 실행하지 않습니다."
    echo 0 > "$WS/gather_rc.txt"
    exit 0
fi
if [ "$LIMIT" -le 0 ]; then
    echo "[$(se_show)] [수집] 수집 실행 한계 $(se_dur "$GATHER_MAX")을 이미 다 썼습니다(누적 $(se_dur "$USED")). 남은 ${PENDING}대는 수집하지 않고 실패 결과로 보냅니다."
    echo 124 > "$WS/gather_rc.txt"
    exit 124
fi

( se_alive_loop "$$" ) 9>&- &
ALIVE_PID=$!
echo "[$(se_show)] [수집] 시작합니다. 대상 ${PENDING}대(접수 ${TOTAL}대), 동시 실행 ${FORKS}대, 이번 실행 한계 $(se_dur "$LIMIT")(${LIMIT}초)."
STARTED=true
SECONDS=0
set +e
timeout --signal=INT --kill-after=90 "$LIMIT" \
    ansible-playbook "$PLAYBOOK" -i "$INVENTORY" -f "$FORKS" --limit "@$WS/.gather_limit_hosts" --vault-password-file="$VAULT_TMP" -e se_location="$LOCATION"
rc=$?
ran=$SECONDS
se_stop_alive
se_close_ssh
set -e

RESULT="$(python3 "$WS/scripts/gather_state.py" end --ws "$WS" --rc "$rc" --ssh-closed "$SSH_CLOSED" 2>/dev/null \
          | python3 -c 'import json, sys; a = json.load(sys.stdin); print((a.get("state") or "") + "|" + (a.get("evidence") or ""))' 2>/dev/null || echo "|")"
STARTED=false
STATE="${RESULT%%|*}"
EVIDENCE="${RESULT#*|}"
case "$STATE" in
    gather_limit)
        how="INT 로 멈췄습니다"
        [ "$rc" -eq 137 ] && how="INT 뒤 정리 시간 90초가 지나 강제 종료했습니다"
        echo "[$(se_show)] [수집] 이번 실행 한계 $(se_dur "$LIMIT")(${LIMIT}초)에 도달해 ${how}. 실행 시간 $(se_dur "$ran"), 종료 코드 ${rc}. 끝난 대상의 결과는 보존합니다."
        echo "[$(se_show)] [수집] 이 실행이 연 원격 연결을 닫아 대상에서 돌던 명령을 정리했습니다(연결 ${SSH_CLOSED}개)."
        ;;
    runner_oom)
        echo "[$(se_show)] [수집] Runner 에서 메모리 부족(OOM) 종료가 확인됐습니다(근거: ${EVIDENCE}). 실행 시간 $(se_dur "$ran"), 종료 코드 ${rc}. 끝난 대상의 결과는 보존하고 남은 대상은 이어서 수집합니다."
        ;;
    process_lost)
        echo "[$(se_show)] [수집] 실행 한계 전에 강제 종료됐습니다(종료 코드 ${rc}). OOM 기록은 없어 원인 미확인으로 남깁니다. 실행 시간 $(se_dur "$ran")."
        ;;
    failed_run)
        echo "[$(se_show)] [수집] ansible 이 비정상 종료했습니다(종료 코드 ${rc}). 실행 시간 $(se_dur "$ran"). 끝난 대상의 결과는 보존합니다."
        ;;
    *)
        echo "[$(se_show)] [수집] 끝났습니다. 실행 시간 $(se_dur "$ran"), 종료 코드 ${rc}."
        ;;
esac
exit "$rc"
