#!/bin/bash
# scripts/run_gather.sh — 서버 정보 수집 실행(ansible-playbook)의 단일 진입점 (2026-10-05 8차 R1 · R2 · R3 · R6, 2026-10-06 9차 재개).
#
# Jenkinsfile_portal 의 서버 정보 수집 단계가 시도마다 vault 비밀번호를 VAULT_PASSWORD 환경변수로 넘겨(withCredentials) 부른다.
# 같은 파일을 단위 시험(tests/unit/test_run_gather.py)과 Harness 가 실행한다 — 시험을 위해 운영 파이프라인에 시험용 입력을 두지 않는다.
# 수집 실행 한계(초)는 이 스크립트의 정상 인자다(운영은 seConstants 의 6시간).
#
# 하는 일
#   1. 작업 폴더의 잠금(.gather.lock)을 잡는다. 이 빌드의 이전 수집이 아직 돌고 있으면(Agent 연결만 끊겼던 동안 계속 돈 실행)
#      끝날 때까지 기다린다. 이전 수집은 자기 실행 한계 안에서 끝난다.
#   2. 빌드 환경 경계(scripts/env_guard.sh) · Ansible venv 선택(scripts/activate_ansible_venv.sh) — 못 찾으면 종료 코드 90
#   3. scripts/gather_state.py begin — 끝 기록 없이 사라진 이전 시도를 근거로 닫고, 쓰는 도중 끊긴 마지막 줄을 옮기고,
#      남은 대상(결과가 확정되지 않은 접수 IP — Precheck 실패로 확정된 대상 제외)과 이번 실행 한계(수집 실행 한계 − 누적 실행 시간),
#      동시 실행 수(채널 상한 그대로, 메모리 계산 없음)를 정한다. 남은 대상이 없으면 ansible 을 실행하지 않고 0 으로,
#      누적 한계를 다 썼으면 실행하지 않고 124 로 끝난다.
#   4. vault 비밀번호를 이 실행만의 임시 파일(600)로 넘기고 끝나면 지운다. 값은 출력하지 않는다
#   5. timeout --signal=INT --kill-after=90 <이번 한계> ansible-playbook … --limit @<남은 대상 파일>
#      실행 중에는 60초마다 생존 표시(.gather_alive — 비정상 종료 때 실행 시간을 보수적으로 세는 근거)를 남기고 5분마다 진행 줄을
#      출력한다. 진행 표시나 출력이 없다는 이유로 중단하지 않는다.
#   6. 원격 명령 정리(8차 R6) — ansible 이 어떻게 끝났든 이 실행이 연 SSH 다중화 연결만 닫는다. 아래 "원격 정리" 참조.
#   7. scripts/gather_state.py end — 끝 시각 · 종료 코드 · 한계 도달(timed_out) · 원인을 gather_run.json 에 남긴다.
#      OOM 은 이 실행 동안 OOM 종료 카운터가 늘었다는 근거가 있을 때만 적는다. 근거가 없으면 원인 미확인이다.
#
# 원격 정리 (2026-10-05 Linux .161 실측, tests/jenkins/harness/remote_cleanup_probe.sh)
#   수집의 Linux 명령은 raw 로, 터미널(pty)과 함께 실행된다(ansible_ssh_use_tty). 연결이 닫히면 원격 명령과 그 자식은 SIGHUP 으로 끝난다.
#   ansible 의 작업 프로세스는 자기 세션에서 돌아 실행 한계의 INT 가 주 프로세스에만 간다 — 그래서 이 실행만의 SSH 다중화 위치
#   (짧은 임시 디렉터리 — 소켓 경로 길이 제한 때문에 /tmp)를 두고, ansible 이 끝나면 그 위치의 연결에 종료(-O exit)를 보낸 뒤 그 위치를
#   명령줄에 가진 ssh 프로세스만 끝낸다. 이름으로 일반 프로세스를 끝내지 않는다.
#
# 인자: <playbook> <inventory> <location> <addon_validated:true|false> <수집 실행 한계 초> [이전 시도 중 Agent 끊김:true|false]
# 출력: gather_run.json(시도 기록) · gather_rc.txt · .gather_limit_hosts · .gather_alive · gather_tail_fragments.jsonl(잘린 줄이 있었을 때)
# 종료 코드: ansible-playbook 의 종료 코드(124 = 한계 도달 뒤 INT, 137 = KILL), 0 = 남은 대상 없음, 90 = 실행 준비 실패,
#           91 = 실행 기록 준비 실패, 2 = 인자 불량, 143/130/129 = 취소 신호
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
# 이 실행이 연 SSH 연결만 닫는다 — 다중화 master 에 종료를 보내고, 이 위치를 명령줄에 가진 ssh 만 끝낸다. 두 번 불러도 무해하다.
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
# 취소 신호(Jenkins 중단은 TERM) — 정리하고, 실행을 시작했으면 끝 기록(믿을 수 있는 끝 시각)을 남긴 뒤 그 코드로 끝낸다
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

# 생존 표시(60초) · 진행 줄(5분). 이 스크립트가 사라지면 같이 끝난다. 잠금 fd 는 물려받지 않는다(아래 9>&-).
#   sleep 은 출력을 물려받지 않는다 — 이 루프를 끝낸 뒤 남은 sleep 이 호출자의 출력(파이프)을 최대 60초 붙잡지 않게.
# 부모가 살아 있는가 — 끝났지만 아직 회수되지 않은 프로세스(zombie)는 살아 있지 않다
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

# ── 1. 같은 작업 폴더의 수집은 한 번에 하나 — 잠금은 이 스크립트와 ansible 이 끝나면 풀린다(ssh 다중화 master 는 물려받지 않는다)
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

# ── 3. 남은 대상 · 이번 실행 한계 · 동시 실행 수 (scripts/gather_state.py begin)
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

# ── 5. 실행
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

# ── 7. 끝 기록
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
