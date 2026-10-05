#!/bin/bash
# tests/jenkins/harness/remote_cleanup_probe.sh — 수집이 멈출 때 원격 명령이 남는지 관측하는 드라이버 (시험 전용 · main 전용, 2026-10-05 8차 R6).
#
# usage: remote_cleanup_probe.sh <vault-password-file> <linux_ip> [loc=git] [out.jsonl=remote_cleanup_probe.jsonl] [scenarios]
#   scenarios(공백 구분, 기본 전부): silent limit abort drop limit_become abort_become drop_become
#
# 각 시나리오는 운영 실행 스크립트 scripts/run_gather.sh 로 tests/jenkins/harness/remote_cleanup_probe.yml 을 돌려 대상에서
# `sleep <표식>` 을 수집과 같은 raw 경로(pty)로 띄운 뒤 멈추고, 5초 뒤 새 연결로 표식 프로세스가 남았는지 센다. 남았으면 기록하고 이 표식만 정리한다.
#   silent        출력 없이 200초 걸리는 명령, 실행 한계 400초 — 끝까지 돌고 성공해야 한다(task 단위 제한이 없다)
#   limit         실행 한계 25초 — run_gather.sh 의 timeout(INT) 뒤 원격 정리
#   abort         빌드 취소: 같은 표식 환경변수를 가진 프로세스 전부에 TERM, 5초 뒤 KILL (Jenkins 가 빌드 프로세스를 끝내는 방식)
#   drop          연결 종료: 이 실행의 ssh 프로세스(다중화 master 포함)만 KILL — ansible 은 연결 실패를 본다
#   *_become      같은 시나리오를 sudo(become) 로 — 수집의 root 가 필요한 raw 명령과 같은 경로
# run_gather.sh 는 실행마다 자기 SSH 다중화 위치를 쓴다. 이 드라이버의 확인 · 정리 실행도 따로 쓴다.
# Ansible 환경: 이 셸의 PATH 에 있는 ansible-playbook 을 쓰는 임시 venv 모양(bin/activate · bin/python3)을 만들어 SE_ANSIBLE_VENV 로 넘긴다
#   (run_gather.sh 는 scripts/activate_ansible_venv.sh 로 venv 를 고른다). Runner 에서는 SE_ANSIBLE_VENV 를 미리 주면 그것을 쓴다.
# 출력: 시나리오마다 JSON 한 줄 {scenario, become, marker, rc, left, procs, ran_sec, ssh_closed}. 비밀값은 쓰지 않는다.
set -u
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
VPF="${1:?vault password file}"; IP="${2:?linux ip}"; LOC="${3:-git}"; OUT="${4:-remote_cleanup_probe.jsonl}"
SCEN="${5:-silent limit abort drop limit_become abort_become drop_become}"
PB="$REPO/tests/jenkins/harness/remote_cleanup_probe.yml"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/ws" "$work/venv/bin" "$work/cp_check"
ln -s "$REPO/scripts" "$work/ws/scripts"
printf 'localhost ansible_connection=local ansible_python_interpreter=%s\n' "$(command -v python3)" > "$work/inventory.ini"
if [ -z "${SE_ANSIBLE_VENV:-}" ]; then
    ln -s "$(command -v python3)" "$work/venv/bin/python3"
    printf 'export VIRTUAL_ENV="%s"\nexport PATH="%s/bin:%s:$PATH"\n' "$work/venv" "$work/venv" "$(dirname "$(command -v ansible-playbook)")" \
        > "$work/venv/bin/activate"
    export SE_ANSIBLE_VENV="$work/venv"
fi
# 저장소 ansible.cfg 를 쓴다(ControlPersist 등 운영과 같다). 확인 · 정리 실행에서만 성공(ok) 결과를 화면에 낸다(관측 줄 RCP_* 를 읽으려고).
export ANSIBLE_CONFIG="$REPO/ansible.cfg" ANSIBLE_INVENTORY_ENABLED=ini,host_list,script,auto REPO_ROOT="$REPO" RCP_LINUX_IP="$IP" RCP_LOC="$LOC"
VAULT_PASSWORD="$(cat "$VPF")"; export VAULT_PASSWORD
base=$(( (RANDOM % 8000) + 61000 ))

direct() {   # 확인 · 정리 — 운영 스크립트를 거치지 않는 관측용 실행
    ANSIBLE_SSH_CONTROL_PATH_DIR="$work/cp_check" ANSIBLE_STDOUT_CALLBACK=default ANSIBLE_DISPLAY_OK_HOSTS=true \
        ansible-playbook "$PB" -i "$work/inventory.ini" --vault-password-file "$VPF" "$@" 2>&1
}
left() {   # <marker> → "<count>|<processes>"
    local out
    out="$(RCP_MODE=check RCP_SLEEP="$1" direct | grep -o 'RCP_LEFT=[^"]*' | head -1)"
    out="${out#RCP_LEFT=}"
    echo "${out%% *}|${out#* }"
}
clean() { RCP_MODE=cleanup RCP_SLEEP="$1" RCP_BECOME="$2" direct >/dev/null; }
# 표식 환경변수(SE_RCP_COOKIE=<값>)를 가진 프로세스 — Jenkins 는 빌드가 띄운 프로세스를 같은 방식(환경변수 표식)으로 찾아 끝낸다
by_cookie() {   # <cookie> [comm]
    local p
    for p in /proc/[0-9]*; do
        if [ -n "${2:-}" ] && [ "$(cat "$p/comm" 2>/dev/null)" != "$2" ]; then continue; fi
        if grep -qsxz "SE_RCP_COOKIE=$1" "$p/environ"; then echo "${p#/proc/}"; fi
    done
}
run_gather() {   # <cookie> <limit> <sleep> <become> [echo]
    SE_RCP_COOKIE="$1" RCP_MODE=run RCP_SLEEP="$3" RCP_BECOME="$4" RCP_ECHO="${5:-false}" WORKSPACE="$work/ws" \
        bash "$REPO/scripts/run_gather.sh" "$PB" "$work/inventory.ini" 1 "$2" "$LOC" false 1
}
field() { sed -n "s/.*\"$1\":\([0-9a-z]*\).*/\1/p" "$work/ws/gather_run.json" 2>/dev/null; }

i=0
for sc in $SCEN; do
    i=$((i + 1)); n=$((base + i)); become=false
    case "$sc" in *_become) become=true ;; esac
    cookie="rcp${RANDOM}${RANDOM}"
    rm -f "$work/ws/gather_run.json"
    case "$sc" in
        silent)
            run_gather "$cookie" 400 200 false true > "$work/silent.log" 2>&1; rc=$?
            printf '{"scenario":"silent","become":false,"seconds":200,"rc":%s,"ran_sec":%s,"timed_out":%s}\n' \
                "$rc" "$(field ran_sec)" "$(field timed_out)" | tee -a "$OUT"
            continue ;;
        limit|limit_become)
            run_gather "$cookie" 25 "$n" "$become" > "$work/$sc.log" 2>&1; rc=$? ;;
        abort|abort_become)
            setsid bash -c "$(declare -f run_gather); work='$work' REPO='$REPO' PB='$PB' LOC='$LOC' run_gather '$cookie' 3600 '$n' '$become'" \
                > "$work/$sc.log" 2>&1 < /dev/null &
            pid=$!
            sleep 25
            for p in $(by_cookie "$cookie"); do kill -TERM "$p" 2>/dev/null; done
            sleep 5
            for p in $(by_cookie "$cookie"); do kill -KILL "$p" 2>/dev/null; done
            wait "$pid" 2>/dev/null; rc=$? ;;
        drop|drop_become)
            run_gather "$cookie" 3600 "$n" "$become" > "$work/$sc.log" 2>&1 < /dev/null &
            pid=$!
            sleep 25
            for p in $(by_cookie "$cookie" ssh); do kill -KILL "$p" 2>/dev/null; done
            wait "$pid" 2>/dev/null; rc=$? ;;
        *) echo "unknown scenario $sc" >&2; continue ;;
    esac
    sleep 5
    res="$(left "$n")"
    printf '{"scenario":"%s","become":%s,"marker":%s,"rc":%s,"left":%s,"procs":"%s","ran_sec":"%s","ssh_closed":"%s"}\n' \
        "$sc" "$become" "$n" "$rc" "${res%%|*}" "${res#*|}" "$(field ran_sec)" "$(field ssh_closed)" | tee -a "$OUT"
    clean "$n" "$become"
done
