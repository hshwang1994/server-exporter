#!/bin/bash
# scripts/run_gather.sh — 서버 정보 수집 실행(ansible-playbook)의 단일 진입점 (2026-10-05, 8차 R1 · R2 · R3 · R6).
#
# Jenkinsfile_portal 의 서버 정보 수집 단계가 vault 비밀번호를 VAULT_PASSWORD 환경변수로 넘겨(withCredentials) 부른다.
# 같은 파일을 단위 시험(tests/unit/test_run_gather.py)과 원격 정리 관측(tests/jenkins/harness/remote_cleanup_probe.sh)이 실행해
# 한계 · 중단 · 기록 · 원격 정리를 확인한다 — 시험을 위해 운영 파이프라인에 시험용 입력을 두지 않는다(R1). 실행 한계는 이 스크립트의 정상 인자다.
#
# 하는 일
#   1. 빌드 환경 경계(scripts/env_guard.sh) — 상위 환경에서 넘어온 시험용 · 재정의 값을 이번 실행에서 지운다
#   2. Ansible venv 선택(scripts/activate_ansible_venv.sh) — 못 찾으면 종료 코드 90
#   3. inventory 스크립트가 요청을 거부하면(exit 1) 빈 inventory 로 성공하지 않고 실행을 실패로 끝낸다(F03, 이 실행에만)
#   4. vault 비밀번호를 이 실행만의 임시 파일(600)로 넘기고 끝나면 지운다. 값은 출력하지 않는다
#   5. timeout --signal=INT --kill-after=90 <한계> ansible-playbook … — 한계에 닿으면 INT 로 ansible 이 멈추게 하고, 90초 뒤에도
#      남으면 KILL 한다. 한계는 Jenkinsfile 이 바로 앞에서 scripts/gather_budget.sh 로 계산한 값이다(최대 6시간).
#      예상 시간이나 진행 신호로는 중단하지 않는다.
#   6. 원격 명령 정리(R6) — ansible 이 어떻게 끝났든(정상 · 한계 · 취소 신호) 이 실행이 연 SSH 연결만 닫는다. 아래 "원격 정리" 참조.
#   7. 시작 · 끝 시각과 실행 시간을 콘솔(사람용 — 날짜 · 시각 · 시간대)과 gather_run.json(기록용 — UTC ISO 8601)에 남긴다.
#      시각은 이 Runner 의 시계다. 한계 도달 여부는 종료 코드만이 아니라 실제 실행 시간으로 확인한다(timed_out) —
#      한계 전에 KILL(137)로 끝났으면 메모리 부족 같은 다른 원인이다.
#
# 원격 정리 (2026-10-05 Linux .161 실측, tests/jenkins/harness/remote_cleanup_probe.sh)
#   수집의 Linux 명령은 raw 로, 터미널(pty)과 함께 실행된다(ansible_ssh_use_tty). 연결이 닫히면 원격 명령과 그 자식은 SIGHUP 으로 끝난다 —
#   실측: SSH 연결을 끊거나 빌드 취소처럼 이 실행의 프로세스를 모두 끝내면 남은 원격 명령 0개(sudo 경로 포함).
#   그런데 ansible 의 작업 프로세스는 자기 세션에서 돌아 실행 한계의 INT 가 ansible 주 프로세스에만 간다. 주 프로세스가 멈춰도 SSH
#   다중화 연결(ControlMaster)과 세션이 남아 원격 명령이 계속 돌았다(실측: 한계 뒤 sleep 1개 · sudo 경로 3개 남음).
#   그래서 이 실행만의 SSH 다중화 위치(짧은 임시 디렉터리 — 소켓 경로 길이 제한 때문에 작업 폴더가 아니라 /tmp)를 두고, ansible 이 끝나면
#   그 위치의 연결에 종료(-O exit)를 보낸 뒤, 그 위치를 명령줄에 가진 ssh 프로세스만 끝낸다. 이름으로 일반 프로세스를 끝내지 않는다.
#   한계: 디스크 대기(D 상태) 같은 중단 불가능한 원격 프로세스는 신호로 끝나지 않는다. 네트워크가 갑자기 끊겨 대상 sshd 가 연결이 닫힌 것을
#   모르면, 대상 쪽 TCP keepalive · ClientAlive 설정이 그 연결을 정리할 때까지 남을 수 있다.
#
# 인자: <playbook> <inventory> <forks> <limit_sec> <location> <addon_validated:true|false> <대상 수>
# 출력: gather_rc.txt(종료 코드), gather_run.json {started_at, ended_at, ran_sec, limit_sec, rc, timed_out, ssh_closed}
# 종료 코드: ansible-playbook 의 종료 코드(124 = 한계 도달 뒤 INT 로 끝남, 137 = KILL), 90 = 실행 준비 실패, 2 = 인자 불량
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
