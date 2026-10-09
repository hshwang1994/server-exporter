#!/bin/bash
set -eo pipefail
set +x

PLAYBOOK="${1:-}"; INVENTORY="${2:-}"; LOCATION="${3:-}"; ADDON_OK="${4:-false}"; GATHER_MAX="${5:-}"; AGENT_LOST="${6:-false}"
if [ -z "$PLAYBOOK" ] || [ -z "$INVENTORY" ] || ! [[ "$GATHER_MAX" =~ ^[0-9]+$ ]] || [ "$GATHER_MAX" -lt 1 ]; then
    echo "[수집] 실행 인자가 잘못됐습니다. 필요한 인자: playbook, inventory, 실행 위치, Add-on 검사 결과, 수집 실행 한계(1초 이상)" >&2
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
        runner_restart) echo "Runner가 다시 부팅됐습니다" ;;
        runner_oom) echo "이 실행의 프로세스가 Runner의 메모리 부족(OOM)으로 끝났습니다" ;;
        agent_disconnect) echo "Runner와 Jenkins의 연결이 끊겼습니다" ;;
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
            echo "[$(se_show)] [수집] 수집 중입니다. 경과 $(se_dur $((SECONDS - since))), 결과 확정 $(python3 "$WS/scripts/gather_state.py" count --ws "$WS" 2>/dev/null || echo '?')대."
        fi
        sleep 60 </dev/null >/dev/null 2>&1
    done
}

exec 9>>"$WS/.gather.lock"
if ! flock -n 9; then
    echo "[$(se_show)] [수집] 이 빌드의 이전 수집이 아직 실행 중입니다. 끝나면 남은 대상을 이어서 수집합니다."
    while ! flock -w 300 9; do
        echo "[$(se_show)] [수집] 이전 수집이 끝나기를 기다리고 있습니다. 결과 확정 $(python3 "$WS/scripts/gather_state.py" count --ws "$WS" 2>/dev/null || echo '?')대."
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
    echo "[$(se_show)] [수집] 실행 기록을 준비하지 못해 수집을 시작하지 않았습니다. 원인은 바로 위 [수집 기록] 줄에 있습니다."
    exit 91
fi
eval "$(python3 -c '
import json, shlex, sys
p = json.loads(sys.argv[1])
pairs = (("ATTEMPT", p["attempt"]), ("PENDING", p["pending"]), ("LIMIT", p["limit"]), ("FORKS", p["forks"]),
         ("TOTAL", p["hosts_total"]), ("DONE", p["completed"]), ("PREFAIL", p["precheck_failed"]), ("USED", p["exec_used"]),
         ("PREV", p.get("closed_previous") or ""), ("PREV_EV", p.get("closed_evidence") or ""), ("FIXED", ",".join(p.get("tail_fixed") or [])),
         ("BSTATE", p.get("state") or ""), ("BEVID", p.get("evidence") or ""), ("CHANNEL", p.get("channel") or ""))
print(" ".join("%s=%s" % (k, shlex.quote(str(v))) for k, v in pairs))
' "$PLAN")"

if [ "$ATTEMPT" -gt 1 ] && [ -n "$PREV" ]; then
    echo "[$(se_show)] [수집] 이전 시도는 끝 기록 없이 중단됐습니다: $(se_state_text "$PREV")."
    if [ -n "$PREV_EV" ]; then echo "  근거: ${PREV_EV}"; fi
fi
if [ -n "$FIXED" ]; then
    echo "[$(se_show)] [수집] 결과 파일에서 쓰다 끊긴 마지막 줄을 gather_tail_fragments.jsonl로 옮겼습니다. 그 대상은 다시 수집합니다."
    echo "  옮긴 파일: ${FIXED}"
fi
if [ "$BSTATE" = "resume_impossible" ]; then
    echo "[$(se_show)] [수집] 결과가 확정됐던 대상의 결과가 작업 폴더에 없어 다시 수집하지 않습니다."
    echo "  근거: ${BEVID}"
    echo "  끝나지 않은 대상은 Runner 장애 사유의 실패 결과로 보냅니다."
    echo 92 > "$WS/gather_rc.txt"
    exit 92
fi
if [ "$PENDING" -eq 0 ]; then
    echo "[$(se_show)] [수집] 남은 대상이 없어 수집을 실행하지 않습니다. 접수 ${TOTAL}대의 결과가 모두 확정됐습니다."
    echo 0 > "$WS/gather_rc.txt"
    exit 0
fi
if [ "$LIMIT" -le 0 ]; then
    echo "[$(se_show)] [수집] 수집 실행 한계 $(se_dur "$GATHER_MAX")을 이미 다 써서 남은 ${PENDING}대는 수집하지 않습니다."
    echo "  지금까지 수집 시간: $(se_dur "$USED")"
    echo "  남은 대상은 실패 결과로 보냅니다."
    echo 124 > "$WS/gather_rc.txt"
    exit 124
fi

( se_alive_loop "$$" ) 9>&- &
ALIVE_PID=$!
CH_TEXT="대상"
case "$CHANNEL" in
    os) CH_TEXT="OS 서버" ;;
    esxi) CH_TEXT="ESXi 서버" ;;
    redfish) CH_TEXT="Redfish(BMC)" ;;
esac
if [ "$ATTEMPT" -gt 1 ]; then
    echo "[$(se_show)] [수집] 남은 대상의 수집을 이어서 진행합니다."
else
    echo "[$(se_show)] [수집] ${CH_TEXT} ${PENDING}대의 정보 수집을 시작합니다."
fi
if [ -n "${NODE_NAME:-}" ]; then echo "  Runner: ${NODE_NAME}"; fi
if [ "$ATTEMPT" -gt 1 ]; then
    if [ "$PREFAIL" -gt 0 ]; then
        echo "  처리 완료: $((DONE + PREFAIL))대 (사전 점검 실패 ${PREFAIL}대 포함)"
    else
        echo "  처리 완료: ${DONE}대"
    fi
    echo "  남은 대상: ${PENDING}대"
fi
echo "  동시 수집: ${FORKS}대"
if [ "$ATTEMPT" -gt 1 ]; then echo "  지금까지 수집 시간: $(se_dur "$USED")"; fi
if [ "$LIMIT" -lt "$GATHER_MAX" ]; then echo "  남은 실행 한계: $(se_dur "$LIMIT")"; fi
STARTED=true
SECONDS=0
set +e
timeout --signal=INT --kill-after=90 "$LIMIT" \
    bash -c 'printf "%s\n" "$$" > "$1" 2>/dev/null || true; shift; exec "$@"' se-ansible "$WS/.gather_ansible_pid" \
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
        how="중단 신호(INT)로 멈췄습니다"
        [ "$rc" -eq 137 ] && how="중단 신호를 보낸 뒤 정리 시간 90초가 지나 강제 종료했습니다"
        echo "[$(se_show)] [수집] 이번 실행 한계 $(se_dur "$LIMIT")에 도달해 ${how}. 끝난 대상의 결과는 보존합니다."
        echo "  실행 시간: $(se_dur "$ran")"
        echo "  종료 코드: ${rc}"
        echo "  닫은 원격 연결: ${SSH_CLOSED}개 (대상에서 돌던 명령도 함께 정리)"
        ;;
    runner_oom)
        echo "[$(se_show)] [수집] 이 실행의 프로세스가 Runner의 메모리 부족(OOM)으로 끝났습니다. 끝난 대상의 결과는 보존하고 남은 대상은 이어서 수집합니다."
        echo "  근거: ${EVIDENCE}"
        echo "  실행 시간: $(se_dur "$ran")"
        echo "  종료 코드: ${rc}"
        ;;
    process_lost)
        echo "[$(se_show)] [수집] 수집 프로세스가 실행 한계 전에 강제 종료됐습니다. 이 실행과 연결된 OOM 기록이 없어 원인은 확인하지 못했습니다."
        if [ -n "$EVIDENCE" ]; then echo "  근거: ${EVIDENCE}"; fi
        echo "  실행 시간: $(se_dur "$ran")"
        echo "  종료 코드: ${rc}"
        ;;
    failed_run)
        echo "[$(se_show)] [수집] ansible-playbook이 비정상 종료했습니다. 끝난 대상의 결과는 보존합니다."
        echo "  종료 코드: ${rc}"
        if [ -n "$EVIDENCE" ]; then echo "  근거: ${EVIDENCE}"; fi
        echo "  실행 시간: $(se_dur "$ran")"
        ;;
    *)
        echo "[$(se_show)] [수집] 수집 실행을 마쳤습니다. 소요 시간 $(se_dur "$ran")."
        if [ "$rc" -ne 0 ]; then echo "  ansible-playbook 종료 코드: ${rc}"; fi
        ;;
esac
exit "$rc"
